"""
Cluster Build Service - turn a winning ("Top Mover") article into a pillar+spoke
topic cluster.

Thin orchestration over existing services (ClusterManagementService,
KeywordDiscoveryService) - NO new cluster algorithms. The operator triggers this
from a Top Mover card on the SEO Dashboard.

Two phases:

    plan_cluster_from_article(...)   -> propose pillar + spoke topics (NO writes)
    create_cluster_from_plan(...)    -> create cluster + pillar spoke + spoke
                                        keywords (idempotent, re-runnable)

Article *generation* is intentionally NOT here. Creating spoke keywords is cheap
and synchronous; generating N articles is a heavy multi-minute job per article
and is a separate, reviewed step (fast-follow). The existing pipeline
(start_one_off with cluster_context + role='spoke') generates them later.

    rising article (the winner)
          |  plan_cluster_from_article  (no writes; LLM or entity-list seeds)
          v
    { pillar_keyword, proposed_spokes[] }  -- operator reviews / edits / picks --,
          |                                                                       |
          v  create_cluster_from_plan  (writes; idempotent best-effort)           |
    seo_clusters (source='cluster_builder', created_from_article_id) <------------'
          |
          +-- pillar spoke  -- LINKED to the rising article (NEVER regenerated)
          +-- spoke keywords (role='spoke', no article yet)
                    |  (fast-follow PR)
                    v  start_one_off(cluster_context, role='spoke') per spoke
                generated spoke articles

Multi-tenancy: seo_clusters has no organization_id (isolation is via
seo_projects); but create_keyword/articles are project-scoped and the LLM calls
need a real org for usage tracking, so a superuser "all" org is resolved to a
real UUID (fail-closed) before any write.

Idempotency (re-running "Build out this cluster" on the same article is safe):
  - the cluster is found-or-created via created_from_article_id (+ pillar/spoke
    article fallbacks), so a second run reuses the same cluster;
  - keywords are found-or-created by normalized text (create_keyword has no
    find-by-text, so a naive call would duplicate rows and defeat the
    UNIQUE(cluster_id, keyword_id) spoke guard);
  - spokes are ensured (pre-check + tolerate the UNIQUE conflict), so existing
    spokes are skipped, not duplicated, and a mid-run failure can be re-run.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from viraltracker.services.seo_pipeline.models import (
    ClusterIntent,
    SpokeRole,
    SpokeStatus,
)

logger = logging.getLogger(__name__)


class ClusterBuildService:
    """Build a pillar+spoke cluster from a single winning article."""

    MODEL = "claude-sonnet-4-20250514"
    SOURCE = "cluster_builder"
    MAX_SPOKES = 8  # cap per build (the approval gate is the main control)

    # Seed-generation modes (D3 - both, brand-universal)
    MODE_LLM = "llm"        # LLM proposes spoke topics from the pillar (default)
    MODE_ENTITY = "entity"  # deterministic "{entity}" template expansion

    # Pillar modes (D5 - both, operator picks)
    PILLAR_IS_RISER = "pillar"   # the winning article IS the pillar
    PILLAR_IS_PARENT = "spoke"   # the winner is a spoke under a broader pillar

    def __init__(
        self,
        supabase_client=None,
        cluster_service=None,
        keyword_service=None,
        anthropic_client=None,
    ):
        self._supabase = supabase_client
        self._cluster_service = cluster_service
        self._keyword_service = keyword_service
        self._anthropic = anthropic_client

    # -------------------------------------------------------------------------
    # Lazy dependencies
    # -------------------------------------------------------------------------
    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def cluster_service(self):
        if self._cluster_service is None:
            from viraltracker.services.seo_pipeline.services.cluster_management_service import (
                ClusterManagementService,
            )
            self._cluster_service = ClusterManagementService(self.supabase)
        return self._cluster_service

    @property
    def keyword_service(self):
        if self._keyword_service is None:
            from viraltracker.services.seo_pipeline.services.keyword_discovery_service import (
                KeywordDiscoveryService,
            )
            self._keyword_service = KeywordDiscoveryService(self.supabase)
        return self._keyword_service

    @property
    def anthropic_client(self):
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # =========================================================================
    # PHASE 1 - PLAN (no writes)
    # =========================================================================
    def plan_cluster_from_article(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str = "all",
        mode: str = MODE_LLM,
        pillar_mode: str = PILLAR_IS_RISER,
        entities: Optional[List[str]] = None,
        template: Optional[str] = None,
        n: int = 6,
    ) -> Dict[str, Any]:
        """
        Propose a pillar + spoke topics from a winning article. Writes nothing.

        Args:
            article_id: The winning (Top Mover) article.
            brand_id: Owning brand (validated against the article).
            organization_id: Org or "all" (resolved for LLM usage tracking).
            mode: 'llm' (default) or 'entity'.
            pillar_mode: 'pillar' (riser is the pillar) or 'spoke' (riser sits
                under an LLM-discovered broader pillar).
            entities: Entity list for MODE_ENTITY (e.g. ["Fortnite", "Roblox"]).
            template: Template for MODE_ENTITY, must contain '{entity}'
                (e.g. "Common {entity} Gaming Slang").
            n: Number of spokes to propose (capped at MAX_SPOKES).

        Returns:
            { article_id, project_id, pillar_keyword, pillar_mode, mode,
              riser_keyword, proposed_spokes: [str, ...], warnings: [str, ...] }
        """
        warnings: List[str] = []
        art = self._load_article(article_id, brand_id)
        project_id = art["project_id"]
        riser_keyword = (art.get("keyword") or "").strip()
        org_id = self._resolve_org_id(organization_id, brand_id)

        # Pillar topic
        if pillar_mode == self.PILLAR_IS_PARENT:
            pillar_keyword = self._discover_pillar_llm(riser_keyword, art.get("brand_name"), org_id)
            if not pillar_keyword or self._norm(pillar_keyword) == self._norm(riser_keyword):
                warnings.append("Could not discover a broader pillar; using the article itself as the pillar.")
                pillar_keyword = riser_keyword
                pillar_mode = self.PILLAR_IS_RISER
        else:
            pillar_mode = self.PILLAR_IS_RISER
            pillar_keyword = riser_keyword

        n = max(1, min(int(n or 6), self.MAX_SPOKES))

        # Spoke topics
        if mode == self.MODE_ENTITY:
            proposed = self.expand_by_entities(entities, template)
        else:
            mode = self.MODE_LLM
            proposed = self.propose_spokes_llm(pillar_keyword, art.get("brand_name"), n, org_id)
            if not proposed:
                warnings.append("The LLM returned no spoke topics; try the entity-list mode or edit manually.")

        # Drop anything that collides with the pillar (or, in parent mode, the riser
        # which becomes its own spoke) and dedupe.
        reserved = {self._norm(pillar_keyword)}
        if pillar_mode == self.PILLAR_IS_PARENT:
            reserved.add(self._norm(riser_keyword))
        proposed = self._dedupe_keep_order(proposed, reserved)[:n]

        return {
            "article_id": article_id,
            "project_id": project_id,
            "pillar_keyword": pillar_keyword,
            "pillar_mode": pillar_mode,
            "mode": mode,
            "riser_keyword": riser_keyword,
            "proposed_spokes": proposed,
            "warnings": warnings,
        }

    # =========================================================================
    # PHASE 2 - CREATE (writes, idempotent best-effort)
    # =========================================================================
    def create_cluster_from_plan(
        self,
        article_id: str,
        pillar_keyword: str,
        spoke_keywords: List[str],
        brand_id: str,
        organization_id: str = "all",
        pillar_mode: str = PILLAR_IS_RISER,
        cluster_name: Optional[str] = None,
        intent: str = ClusterIntent.INFORMATIONAL.value,
    ) -> Dict[str, Any]:
        """
        Create (or reuse) the cluster, wire the rising article as the pillar (or as
        a spoke under a parent pillar), and add the approved spoke keywords.

        Idempotent: safe to re-run (reuses the cluster, skips existing spokes).
        Best-effort: one bad spoke is skipped, the rest proceed, and a per-spoke
        breakdown is returned. NO article generation happens here.

        Returns:
            { cluster_id, project_id, pillar_keyword, pillar_mode, pillar_article_id,
              reused_cluster, spokes_created[], spokes_skipped[], spokes_failed[],
              warnings[] }
        """
        warnings: List[str] = []
        org_id = self._resolve_org_id(organization_id, brand_id)  # fail-closed
        art = self._load_article(article_id, brand_id)
        project_id = art["project_id"]
        riser_keyword = (art.get("keyword") or "").strip()

        pillar_keyword = (pillar_keyword or "").strip() or riser_keyword
        # Riser-pillar mode: the pillar IS the rising article's topic.
        if pillar_mode != self.PILLAR_IS_PARENT:
            pillar_mode = self.PILLAR_IS_RISER

        # --- 1. Find or create the cluster (idempotent on re-run) ---------------
        cluster, reused = self._find_or_create_cluster(
            project_id,
            article_id,
            name=cluster_name or pillar_keyword or riser_keyword or "Cluster",
            pillar_keyword=pillar_keyword,
            intent=intent,
        )
        cluster_id = cluster["id"]

        # --- 2. Pillar wiring ---------------------------------------------------
        # The pillar keyword must exist as a spoke before set_pillar() can promote
        # it (set_pillar only flips role on an EXISTING spoke row).
        pillar_kw = self._find_or_create_keyword(project_id, pillar_keyword)
        self._ensure_spoke(cluster_id, pillar_kw["id"], SpokeRole.PILLAR.value)
        self.cluster_service.set_pillar(cluster_id, pillar_kw["id"])

        pillar_article_id: Optional[str] = None
        live_status = (
            SpokeStatus.PUBLISHED.value if art.get("published_url") else SpokeStatus.PLANNED.value
        )
        if pillar_mode == self.PILLAR_IS_RISER:
            # The winning article IS the pillar page - link it, never regenerate it.
            pillar_article_id = article_id
            pillar_spoke = self._get_spoke(cluster_id, pillar_kw["id"])
            if pillar_spoke:
                self.cluster_service.update_spoke(
                    pillar_spoke["id"], article_id=article_id, status=live_status
                )
            self._set_cluster_pillar_article(cluster_id, article_id, live_status)
        else:
            # Parent-pillar mode: the discovered pillar has no article yet (a future
            # build/generation makes it); the rising article becomes a spoke.
            riser_kw = self._find_or_create_keyword(project_id, riser_keyword)
            riser_spoke, _ = self._ensure_spoke(cluster_id, riser_kw["id"], SpokeRole.SPOKE.value)
            if riser_spoke:
                self.cluster_service.update_spoke(
                    riser_spoke["id"], article_id=article_id, status=live_status
                )
            # If we reused a cluster previously built riser-as-pillar, the riser is
            # now a spoke and the discovered pillar has no article yet - clear ONLY
            # that stale riser link (never some other real pillar article) so health
            # views don't keep showing the demoted riser as the pillar.
            if cluster.get("pillar_article_id") == article_id:
                self._set_cluster_pillar_article(cluster_id, None, SpokeStatus.PLANNED.value)

        # --- 3. Spoke keywords (no articles; generation is a fast-follow) -------
        reserved = {self._norm(pillar_keyword)}
        if pillar_mode == self.PILLAR_IS_PARENT:
            reserved.add(self._norm(riser_keyword))
        accepted = self._dedupe_keep_order(spoke_keywords or [], reserved)[: self.MAX_SPOKES]
        if spoke_keywords and len(spoke_keywords) > len(accepted):
            warnings.append(
                f"Capped/deduped to {len(accepted)} spokes (max {self.MAX_SPOKES})."
            )

        created, skipped, failed = [], [], []
        for kw in accepted:
            try:
                rec = self._find_or_create_keyword(project_id, kw)
                spoke, was_created = self._ensure_spoke(
                    cluster_id, rec["id"], SpokeRole.SPOKE.value
                )
                entry = {"keyword": kw, "keyword_id": rec["id"],
                         "spoke_id": (spoke or {}).get("id")}
                (created if was_created else skipped).append(entry)
            except Exception as e:  # one bad spoke must not abort the rest
                logger.warning(f"Cluster build: spoke '{kw}' failed: {e}")
                failed.append({"keyword": kw, "error": str(e)})

        logger.info(
            f"Cluster build {cluster_id}: {len(created)} created, "
            f"{len(skipped)} existing, {len(failed)} failed "
            f"(reused_cluster={reused}, pillar_mode={pillar_mode})"
        )
        return {
            "cluster_id": cluster_id,
            "project_id": project_id,
            "pillar_keyword": pillar_keyword,
            "pillar_mode": pillar_mode,
            "pillar_article_id": pillar_article_id,
            "reused_cluster": reused,
            "spokes_created": created,
            "spokes_skipped": skipped,
            "spokes_failed": failed,
            "warnings": warnings,
        }

    # =========================================================================
    # SEED GENERATION
    # =========================================================================
    @staticmethod
    def expand_by_entities(
        entities: Optional[List[str]], template: Optional[str]
    ) -> List[str]:
        """Deterministically expand a template over an entity list (MODE_ENTITY).

        e.g. ["Fortnite", "Roblox"] + "Common {entity} Gaming Slang"
             -> ["Common Fortnite Gaming Slang", "Common Roblox Gaming Slang"]
        Universal: the template carries the topic, so this works for any brand.
        """
        if not template or "{entity}" not in template:
            raise ValueError("Entity template must contain '{entity}'.")
        out: List[str] = []
        seen = set()
        for raw in (entities or []):
            ent = (raw or "").strip()
            if not ent:
                continue
            kw = template.replace("{entity}", ent).strip()
            key = ClusterBuildService._norm(kw)
            if key and key not in seen:
                seen.add(key)
                out.append(kw)
        return out

    def propose_spokes_llm(
        self,
        pillar_keyword: str,
        brand_name: Optional[str],
        n: int,
        organization_id: str,
    ) -> List[str]:
        """Ask the LLM for N supporting spoke topics under a pillar (MODE_LLM).

        Brand-universal: works for any pillar, not just the gaming example.
        """
        brand_clause = f' for the brand "{brand_name}"' if brand_name else ""
        prompt = (
            "You are an SEO content strategist building a topic cluster. The pillar "
            f'topic is "{pillar_keyword}"{brand_clause}. Propose {n} supporting "spoke" '
            "article topics. Each spoke must cover a specific sub-aspect of the pillar, "
            "be a distinct search-worthy long-tail keyword phrase, and clearly differ "
            "from the pillar and from the other spokes (so they interlink rather than "
            "cannibalize). Do NOT restate the pillar. Return ONLY a JSON array of "
            'strings and nothing else, e.g. ["first spoke keyword", "second spoke keyword"].'
        )
        data = self._llm_json(prompt, "cluster_spoke_proposal", organization_id)
        if not isinstance(data, list):
            return []
        return [s.strip() for s in data if isinstance(s, str) and s.strip()][:n]

    def _discover_pillar_llm(
        self, riser_keyword: str, brand_name: Optional[str], organization_id: str
    ) -> str:
        """Ask the LLM for the broader pillar topic above a specific article."""
        brand_clause = f" (brand: {brand_name})" if brand_name else ""
        prompt = (
            "You are an SEO strategist. A specific article ranks for "
            f'"{riser_keyword}"{brand_clause}. Name the single BROADER "pillar" topic '
            "this article is one sub-topic of - a more general keyword that this and "
            "several sibling articles would all support to build topical authority. "
            'Return ONLY JSON and nothing else: {"pillar_keyword": "..."}.'
        )
        data = self._llm_json(prompt, "cluster_pillar_discovery", organization_id)
        if isinstance(data, dict):
            pk = (data.get("pillar_keyword") or "").strip()
            if pk:
                return pk
        return riser_keyword

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================
    @staticmethod
    def _norm(text: Optional[str]) -> str:
        """Normalize keyword text for dedupe/lookup (case + whitespace folded)."""
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _dedupe_keep_order(items: List[str], reserved: set) -> List[str]:
        out: List[str] = []
        seen = set(reserved)
        for raw in (items or []):
            kw = (raw or "").strip()
            key = ClusterBuildService._norm(kw)
            if key and key not in seen:
                seen.add(key)
                out.append(kw)
        return out

    def _resolve_org_id(self, organization_id: str, brand_id: str) -> str:
        """Resolve a real org UUID from the brand when a superuser passes 'all'.

        Fails CLOSED: raises if it cannot resolve, rather than returning 'all'
        (which would later blow up usage tracking / any org-scoped insert).
        """
        if organization_id and organization_id != "all":
            return organization_id
        row = (
            self.supabase.table("brands")
            .select("organization_id")
            .eq("id", brand_id)
            .limit(1)
            .execute()
        )
        if row.data and row.data[0].get("organization_id"):
            return row.data[0]["organization_id"]
        raise ValueError(
            f"Could not resolve organization for brand {brand_id} (org='all')."
        )

    def _load_article(self, article_id: str, brand_id: str) -> Dict[str, Any]:
        """Load + ownership-validate the seed article (find_top_movers is
        brand-only, so re-validate brand/project before any write)."""
        row = (
            self.supabase.table("seo_articles")
            .select(
                "id, keyword, keyword_id, title, project_id, brand_id, "
                "organization_id, published_url, status"
            )
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
        if not row.data:
            raise ValueError(f"Article not found: {article_id}")
        art = row.data[0]
        if brand_id and art.get("brand_id") and art["brand_id"] != brand_id:
            raise ValueError(
                f"Article {article_id} does not belong to brand {brand_id}."
            )
        if not art.get("project_id"):
            raise ValueError(
                f"Article {article_id} has no project_id; cannot build a cluster."
            )
        if not (art.get("keyword") or "").strip():
            raise ValueError(f"Article {article_id} has no keyword to seed a cluster.")
        return art

    def _find_or_create_keyword(self, project_id: str, keyword: str) -> Dict[str, Any]:
        """Find a keyword by normalized text within the project, else create it.

        create_keyword has no find-by-text, so without this every run would insert
        duplicate seo_keywords rows (each with a new id), defeating the
        UNIQUE(cluster_id, keyword_id) spoke guard and breaking idempotency.
        """
        norm = self._norm(keyword)
        if not norm:
            raise ValueError("Empty keyword.")
        # Match on normalized tokens (%-joined) so case, collapsed whitespace, and
        # separator variants all surface as candidates; the Python normalized check
        # below is authoritative (over-matches are filtered out, none are missed).
        pattern = "%" + "%".join(norm.split()) + "%"
        candidates = (
            self.supabase.table("seo_keywords")
            .select("id, keyword")
            .eq("project_id", project_id)
            .ilike("keyword", pattern)
            .execute()
        )
        for row in (candidates.data or []):
            if self._norm(row.get("keyword")) == norm:
                return row
        return self.keyword_service.create_keyword(project_id, keyword)

    def _get_spoke(self, cluster_id: str, keyword_id: str) -> Optional[Dict[str, Any]]:
        row = (
            self.supabase.table("seo_cluster_spokes")
            .select("id, role, article_id, status")
            .eq("cluster_id", cluster_id)
            .eq("keyword_id", keyword_id)
            .limit(1)
            .execute()
        )
        return row.data[0] if row.data else None

    def _ensure_spoke(
        self, cluster_id: str, keyword_id: str, role: str
    ) -> tuple:
        """Idempotently ensure a (cluster, keyword) spoke exists.

        Pre-checks, then tolerates the UNIQUE(cluster_id, keyword_id) conflict on a
        race (add_spoke plain-inserts, so a duplicate would otherwise raise and
        leave the denormalized centroid/count half-updated).

        Returns (spoke_record_or_None, was_created).
        """
        existing = self._get_spoke(cluster_id, keyword_id)
        if existing:
            return existing, False
        try:
            spoke = self.cluster_service.add_spoke(cluster_id, keyword_id, role=role)
            return spoke, True
        except Exception as e:
            # Only a genuine UNIQUE(cluster_id, keyword_id) conflict (a concurrent
            # insert) counts as "already there". Any other failure - e.g. add_spoke
            # inserted the row but its denormalized keyword/count update then threw -
            # must surface (recorded as a failed spoke), not be silently swallowed.
            if self._is_duplicate_error(e):
                again = self._get_spoke(cluster_id, keyword_id)
                if again:
                    return again, False
            raise

    @staticmethod
    def _is_duplicate_error(e: Exception) -> bool:
        msg = str(e).lower()
        return any(
            tok in msg for tok in ("duplicate", "unique", "already exists", "23505")
        )

    def _find_or_create_cluster(
        self,
        project_id: str,
        article_id: str,
        name: str,
        pillar_keyword: Optional[str],
        intent: str,
    ) -> tuple:
        """Find the builder cluster for this seed article, else create one.

        Idempotency anchors ONLY on this builder's own marker
        (created_from_article_id). It deliberately does NOT reuse a cluster just
        because the article is already a pillar/spoke in it - that article may
        belong to a hand-curated cluster, and reusing it would let set_pillar()
        demote someone's real pillar and dump spokes into the wrong cluster.

        Respects UNIQUE(project_id, name): on a name clash with an unrelated
        cluster, disambiguates our name rather than throwing or hijacking.
        (Single-operator flow; true concurrent builds of the same article are not
        guarded beyond the marker lookup.)

        Returns (cluster_record, reused).
        """
        by_src = (
            self.supabase.table("seo_clusters")
            .select("*")
            .eq("project_id", project_id)
            .eq("created_from_article_id", article_id)
            .limit(1)
            .execute()
        )
        if by_src.data:
            return by_src.data[0], True

        if self._cluster_name_taken(project_id, name):
            base = name
            name = f"{base} (cluster builder)"
            suffix = 2
            while self._cluster_name_taken(project_id, name) and suffix <= 50:
                name = f"{base} (cluster builder {suffix})"
                suffix += 1

        created = self.cluster_service.create_cluster(
            project_id=project_id,
            name=name,
            pillar_keyword=pillar_keyword,
            intent=intent,
            source=self.SOURCE,
            created_from_article_id=article_id,
        )
        return created, False

    def _cluster_name_taken(self, project_id: str, name: str) -> bool:
        row = (
            self.supabase.table("seo_clusters")
            .select("id")
            .eq("project_id", project_id)
            .eq("name", name)
            .limit(1)
            .execute()
        )
        return bool(row.data)

    def _set_cluster_pillar_article(
        self, cluster_id: str, article_id: str, pillar_status: str
    ) -> None:
        self.supabase.table("seo_clusters").update(
            {"pillar_article_id": article_id, "pillar_status": pillar_status}
        ).eq("id", cluster_id).execute()

    def _llm_json(
        self, prompt: str, operation: str, organization_id: str
    ) -> Any:
        """Single LLM call returning parsed JSON, with usage tracking."""
        start = time.time()
        resp = self.anthropic_client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        self._track_usage(
            organization_id=organization_id,
            operation=operation,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            duration_ms=int((time.time() - start) * 1000),
        )
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract the first JSON array/object from an LLM response."""
        import json

        if not text:
            return None
        # Strip ```json fences if present.
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        candidate = fenced.group(1).strip() if fenced else text.strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass
        # Fall back to the first bracketed span.
        m = re.search(r"(\[.*\]|\{.*\})", candidate, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        return None

    def _track_usage(
        self,
        organization_id: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
    ) -> None:
        """Track LLM usage via UsageTracker (multi-tenant accounting)."""
        try:
            from viraltracker.services.usage_tracker import UsageRecord, UsageTracker

            tracker = UsageTracker(self.supabase)
            record = UsageRecord(
                provider="anthropic",
                model=self.MODEL,
                tool_name="seo_pipeline",
                operation=f"cluster_build_{operation}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
            tracker.track(
                user_id=None, organization_id=organization_id, record=record
            )
        except Exception as e:
            logger.warning(f"Failed to track cluster-build usage: {e}")
