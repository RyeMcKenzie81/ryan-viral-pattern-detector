"""
Cluster Management Service - Topic cluster CRUD, spoke management, and analytics.

Handles:
- Cluster CRUD (create, list, get, update, delete)
- Spoke management (add, remove, bulk assign, set pillar, link articles)
- Health metrics (completion %, published/written/planned counts, milestones)
- Auto-assignment (keyword-to-cluster scoring with confidence bands)
- Pre-write check (overlap detection to prevent cannibalization)
- Next article suggestion (priority scoring with human-readable reasons)
- Gap analysis (find unassigned keywords with cluster affinity)
- Article import and publication scheduling

Multi-tenancy: seo_clusters has no organization_id — all queries join
through seo_projects(organization_id) for isolation.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

from viraltracker.services.seo_pipeline.models import (
    ClusterStatus,
    ClusterIntent,
    SpokeRole,
    SpokeStatus,
)

logger = logging.getLogger(__name__)


class ClusterManagementService:
    """Service for managing SEO topic clusters and spokes."""

    def __init__(self, supabase_client=None):
        """
        Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance. If None, will be
                created from environment on first use.
        """
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # CLUSTER CRUD
    # =========================================================================

    def create_cluster(
        self,
        project_id: str,
        name: str,
        pillar_keyword: Optional[str] = None,
        intent: str = ClusterIntent.INFORMATIONAL.value,
        description: Optional[str] = None,
        target_spoke_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Create a new topic cluster.

        Args:
            project_id: Project UUID
            name: Cluster name
            pillar_keyword: Main keyword for the pillar article
            intent: Search intent (informational, commercial, etc.)
            description: Optional cluster description
            target_spoke_count: Target number of spoke articles

        Returns:
            Created cluster record
        """
        valid_intents = {e.value for e in ClusterIntent}
        if intent not in valid_intents:
            raise ValueError(
                f"Invalid intent: '{intent}'. Valid: {sorted(valid_intents)}"
            )

        data = {
            "project_id": project_id,
            "name": name,
            "pillar_keyword": pillar_keyword,
            "intent": intent,
            "status": ClusterStatus.DRAFT.value,
            "pillar_status": SpokeStatus.PLANNED.value,
            "target_spoke_count": target_spoke_count,
            "metadata": {},
        }
        if description:
            data["description"] = description

        result = self.supabase.table("seo_clusters").insert(data).execute()
        logger.info(f"Created cluster '{name}' in project {project_id}")
        return result.data[0]

    def list_clusters(self, project_id: str) -> List[Dict[str, Any]]:
        """
        List all clusters for a project with aggregated spoke/article counts.

        Args:
            project_id: Project UUID

        Returns:
            List of cluster records with spoke_stats
        """
        # Get clusters
        result = (
            self.supabase.table("seo_clusters")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at")
            .execute()
        )
        clusters = result.data or []

        if not clusters:
            return []

        # Batch-fetch spoke counts for all clusters
        cluster_ids = [c["id"] for c in clusters]
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("cluster_id, status")
            .in_("cluster_id", cluster_ids)
            .execute()
        )
        spokes = spokes_result.data or []

        # Aggregate per cluster
        stats = {}
        for spoke in spokes:
            cid = spoke["cluster_id"]
            if cid not in stats:
                stats[cid] = {
                    "total": 0,
                    SpokeStatus.PUBLISHED.value: 0,
                    SpokeStatus.WRITING.value: 0,
                    SpokeStatus.PLANNED.value: 0,
                }
            stats[cid]["total"] += 1
            status = spoke.get("status", SpokeStatus.PLANNED.value)
            if status in stats[cid]:
                stats[cid][status] += 1

        for cluster in clusters:
            cluster["spoke_stats"] = stats.get(cluster["id"], {
                "total": 0,
                SpokeStatus.PUBLISHED.value: 0,
                SpokeStatus.WRITING.value: 0,
                SpokeStatus.PLANNED.value: 0,
            })

        return clusters

    def get_cluster(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single cluster with its spokes and keywords.

        Args:
            cluster_id: Cluster UUID

        Returns:
            Cluster record with spokes list, or None
        """
        result = (
            self.supabase.table("seo_clusters")
            .select("*")
            .eq("id", cluster_id)
            .execute()
        )
        if not result.data:
            return None

        cluster = result.data[0]

        # Get spokes with keyword data
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("*, seo_keywords(keyword, search_volume, keyword_difficulty, search_intent)")
            .eq("cluster_id", cluster_id)
            .order("sort_order")
            .order("priority")
            .execute()
        )
        cluster["spokes"] = spokes_result.data or []

        return cluster

    def update_cluster(self, cluster_id: str, **updates) -> Optional[Dict[str, Any]]:
        """
        Update a cluster's fields.

        Args:
            cluster_id: Cluster UUID
            **updates: Fields to update

        Returns:
            Updated cluster record or None
        """
        if "status" in updates:
            valid = {e.value for e in ClusterStatus}
            if updates["status"] not in valid:
                raise ValueError(
                    f"Invalid status: '{updates['status']}'. Valid: {sorted(valid)}"
                )
        if "intent" in updates:
            valid = {e.value for e in ClusterIntent}
            if updates["intent"] not in valid:
                raise ValueError(
                    f"Invalid intent: '{updates['intent']}'. Valid: {sorted(valid)}"
                )

        result = (
            self.supabase.table("seo_clusters")
            .update(updates)
            .eq("id", cluster_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def delete_cluster(self, cluster_id: str) -> Dict[str, Any]:
        """
        Delete a cluster. Returns info about affected items before deletion.

        Spokes are cascade-deleted. seo_keywords.cluster_id is nulled by
        ON DELETE SET NULL on the FK.

        Args:
            cluster_id: Cluster UUID

        Returns:
            Dict with deleted=True and affected_count
        """
        # Count affected spokes for confirmation
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        affected_count = len(spokes_result.data or [])

        # Null out cluster_id on keywords before deletion
        keywords_result = (
            self.supabase.table("seo_keywords")
            .select("id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        keyword_ids = [k["id"] for k in (keywords_result.data or [])]
        for kid in keyword_ids:
            self.supabase.table("seo_keywords").update(
                {"cluster_id": None}
            ).eq("id", kid).execute()

        # Delete cluster (cascades spokes)
        self.supabase.table("seo_clusters").delete().eq("id", cluster_id).execute()
        logger.info(f"Deleted cluster {cluster_id} ({affected_count} spokes)")

        return {"deleted": True, "affected_spokes": affected_count}

    # =========================================================================
    # SPOKE MANAGEMENT
    # =========================================================================

    def add_spoke(
        self,
        cluster_id: str,
        keyword_id: str,
        role: str = SpokeRole.SPOKE.value,
        priority: int = 2,
    ) -> Dict[str, Any]:
        """
        Add a keyword as a spoke to a cluster.

        Also updates seo_keywords.cluster_id for denormalized convenience.

        Args:
            cluster_id: Cluster UUID
            keyword_id: Keyword UUID
            role: 'spoke' or 'pillar'
            priority: 1=high, 2=medium, 3=low

        Returns:
            Created spoke record
        """
        valid_roles = {e.value for e in SpokeRole}
        if role not in valid_roles:
            raise ValueError(f"Invalid role: '{role}'. Valid: {sorted(valid_roles)}")

        data = {
            "cluster_id": cluster_id,
            "keyword_id": keyword_id,
            "role": role,
            "priority": priority,
        }

        # Get keyword metadata for target fields
        kw_result = (
            self.supabase.table("seo_keywords")
            .select("keyword_difficulty, search_volume")
            .eq("id", keyword_id)
            .execute()
        )
        if kw_result.data:
            kw = kw_result.data[0]
            data["target_kd"] = kw.get("keyword_difficulty")
            data["target_volume"] = kw.get("search_volume")

        result = self.supabase.table("seo_cluster_spokes").insert(data).execute()

        # Sync denormalized FK on keywords
        self.supabase.table("seo_keywords").update(
            {"cluster_id": cluster_id}
        ).eq("id", keyword_id).execute()

        # Update spoke_count on cluster
        self._update_spoke_count(cluster_id)

        return result.data[0]

    def remove_spoke(self, cluster_id: str, keyword_id: str) -> bool:
        """
        Remove a keyword from a cluster.

        Args:
            cluster_id: Cluster UUID
            keyword_id: Keyword UUID

        Returns:
            True if removed
        """
        self.supabase.table("seo_cluster_spokes").delete().eq(
            "cluster_id", cluster_id
        ).eq("keyword_id", keyword_id).execute()

        # Null out denormalized FK
        self.supabase.table("seo_keywords").update(
            {"cluster_id": None}
        ).eq("id", keyword_id).execute()

        self._update_spoke_count(cluster_id)
        return True

    def update_spoke(self, spoke_id: str, **updates) -> Optional[Dict[str, Any]]:
        """
        Update a spoke's fields (priority, status, notes, sort_order).

        Args:
            spoke_id: Spoke UUID
            **updates: Fields to update

        Returns:
            Updated spoke record or None
        """
        if "status" in updates:
            valid = {e.value for e in SpokeStatus}
            if updates["status"] not in valid:
                raise ValueError(
                    f"Invalid spoke status: '{updates['status']}'. Valid: {sorted(valid)}"
                )

        result = (
            self.supabase.table("seo_cluster_spokes")
            .update(updates)
            .eq("id", spoke_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def set_pillar(self, cluster_id: str, keyword_id: str) -> Dict[str, Any]:
        """
        Set a keyword as the pillar for a cluster.

        Demotes any existing pillar to spoke role.

        Args:
            cluster_id: Cluster UUID
            keyword_id: Keyword UUID (must already be a spoke)

        Returns:
            Updated spoke record
        """
        # Demote existing pillar
        existing = (
            self.supabase.table("seo_cluster_spokes")
            .select("id")
            .eq("cluster_id", cluster_id)
            .eq("role", SpokeRole.PILLAR.value)
            .execute()
        )
        for spoke in (existing.data or []):
            self.supabase.table("seo_cluster_spokes").update(
                {"role": SpokeRole.SPOKE.value}
            ).eq("id", spoke["id"]).execute()

        # Promote new pillar
        result = (
            self.supabase.table("seo_cluster_spokes")
            .update({"role": SpokeRole.PILLAR.value})
            .eq("cluster_id", cluster_id)
            .eq("keyword_id", keyword_id)
            .execute()
        )

        # Update cluster pillar_keyword
        if result.data:
            kw_result = (
                self.supabase.table("seo_keywords")
                .select("keyword")
                .eq("id", keyword_id)
                .execute()
            )
            if kw_result.data:
                self.supabase.table("seo_clusters").update({
                    "pillar_keyword": kw_result.data[0]["keyword"],
                }).eq("id", cluster_id).execute()

        return result.data[0] if result.data else {}

    def bulk_assign_keywords(
        self,
        cluster_id: str,
        keyword_ids: List[str],
        role: str = SpokeRole.SPOKE.value,
        priority: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Assign multiple keywords to a cluster.

        Skips keywords already assigned to this cluster.

        Args:
            cluster_id: Cluster UUID
            keyword_ids: List of keyword UUIDs
            role: Role for all keywords
            priority: Priority for all keywords

        Returns:
            List of created spoke records
        """
        # Check existing assignments to avoid duplicates
        existing = (
            self.supabase.table("seo_cluster_spokes")
            .select("keyword_id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        existing_ids = {s["keyword_id"] for s in (existing.data or [])}

        results = []
        for kid in keyword_ids:
            if kid in existing_ids:
                continue
            try:
                spoke = self.add_spoke(cluster_id, kid, role, priority)
                results.append(spoke)
            except Exception as e:
                logger.warning(f"Failed to assign keyword {kid} to cluster {cluster_id}: {e}")

        return results

    def assign_article_to_spoke(self, spoke_id: str, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Link an article to a spoke and update spoke status.

        Args:
            spoke_id: Spoke UUID
            article_id: Article UUID

        Returns:
            Updated spoke record
        """
        result = (
            self.supabase.table("seo_cluster_spokes")
            .update({"article_id": article_id, "status": SpokeStatus.WRITING.value})
            .eq("id", spoke_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # =========================================================================
    # HEALTH & ANALYTICS
    # =========================================================================

    def get_cluster_health(self, cluster_id: str) -> Dict[str, Any]:
        """
        Calculate health metrics for a cluster.

        Returns:
            Dict with completion_pct, counts by status, link_coverage,
            milestones, and target progress.
        """
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("status, role, article_id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        spokes = spokes_result.data or []

        total = len(spokes)
        published = sum(1 for s in spokes if s["status"] == SpokeStatus.PUBLISHED.value)
        writing = sum(1 for s in spokes if s["status"] == SpokeStatus.WRITING.value)
        planned = sum(1 for s in spokes if s["status"] == SpokeStatus.PLANNED.value)
        skipped = sum(1 for s in spokes if s["status"] == SpokeStatus.SKIPPED.value)
        has_pillar = any(s["role"] == SpokeRole.PILLAR.value for s in spokes)
        with_articles = sum(1 for s in spokes if s.get("article_id"))

        # Completion: published / (total - skipped)
        active_total = total - skipped
        completion_pct = round((published / active_total * 100) if active_total > 0 else 0, 1)

        # Get cluster for target
        cluster = (
            self.supabase.table("seo_clusters")
            .select("target_spoke_count")
            .eq("id", cluster_id)
            .execute()
        )
        target = (cluster.data[0]["target_spoke_count"] or 0) if cluster.data else 0

        # Link coverage (articles with at least one internal link)
        article_ids = [s["article_id"] for s in spokes if s.get("article_id")]
        link_coverage = 0.0
        if article_ids:
            links_result = (
                self.supabase.table("seo_internal_links")
                .select("source_article_id")
                .in_("source_article_id", article_ids)
                .execute()
            )
            linked_ids = set(l["source_article_id"] for l in (links_result.data or []))
            link_coverage = round(len(linked_ids) / len(article_ids) * 100, 1)

        milestones = []
        if completion_pct >= 60:
            milestones.append("60% milestone reached")
        if completion_pct >= 100:
            milestones.append("cluster complete")
        if has_pillar:
            milestones.append("pillar assigned")

        return {
            "total_spokes": total,
            "published": published,
            "writing": writing,
            "planned": planned,
            "skipped": skipped,
            "completion_pct": completion_pct,
            "has_pillar": has_pillar,
            "with_articles": with_articles,
            "link_coverage_pct": link_coverage,
            "target_spoke_count": target,
            "target_progress": f"{total}/{target}" if target > 0 else "no target",
            "milestones": milestones,
        }

    def get_cluster_overview(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get dashboard overview for all clusters in a project.

        Batch query: 2-3 DB calls total (not N+1).

        Args:
            project_id: Project UUID

        Returns:
            List of cluster summaries with stats
        """
        clusters = self.list_clusters(project_id)

        # Batch article counts by status
        if clusters:
            cluster_ids = [c["id"] for c in clusters]
            spokes_result = (
                self.supabase.table("seo_cluster_spokes")
                .select("cluster_id, article_id, status, role")
                .in_("cluster_id", cluster_ids)
                .execute()
            )

            # Build per-cluster stats
            cluster_stats = {}
            for spoke in (spokes_result.data or []):
                cid = spoke["cluster_id"]
                if cid not in cluster_stats:
                    cluster_stats[cid] = {
                        "total": 0, "published": 0, "writing": 0,
                        "planned": 0, "has_pillar": False,
                    }
                cluster_stats[cid]["total"] += 1
                if spoke["status"] == SpokeStatus.PUBLISHED.value:
                    cluster_stats[cid]["published"] += 1
                elif spoke["status"] == SpokeStatus.WRITING.value:
                    cluster_stats[cid]["writing"] += 1
                elif spoke["status"] == SpokeStatus.PLANNED.value:
                    cluster_stats[cid]["planned"] += 1
                if spoke["role"] == SpokeRole.PILLAR.value:
                    cluster_stats[cid]["has_pillar"] = True

            for cluster in clusters:
                stats = cluster_stats.get(cluster["id"], {
                    "total": 0, "published": 0, "writing": 0,
                    "planned": 0, "has_pillar": False,
                })
                active = stats["total"] - (cluster.get("spoke_stats", {}).get("skipped", 0))
                cluster["overview"] = {
                    **stats,
                    "completion_pct": round(
                        (stats["published"] / active * 100) if active > 0 else 0, 1
                    ),
                }

        return clusters

    def get_interlinking_audit(self, cluster_id: str) -> Dict[str, Any]:
        """
        Audit internal links within a cluster.

        Delegates to InterlinkingService for Jaccard similarity,
        returns spoke-to-pillar and spoke-to-spoke link matrix.

        Args:
            cluster_id: Cluster UUID

        Returns:
            Dict with link_matrix, missing_links, coverage_pct
        """
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        # Get spokes with articles
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("keyword_id, article_id, role, seo_keywords(keyword)")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        spokes = [s for s in (spokes_result.data or []) if s.get("article_id")]

        if len(spokes) < 2:
            return {
                "cluster_id": cluster_id,
                "link_matrix": [],
                "missing_links": [],
                "coverage_pct": 0.0,
                "message": "Need at least 2 published articles to audit links.",
            }

        article_ids = [s["article_id"] for s in spokes]

        # Get existing links between cluster articles
        links_result = (
            self.supabase.table("seo_internal_links")
            .select("source_article_id, target_article_id, status")
            .in_("source_article_id", article_ids)
            .in_("target_article_id", article_ids)
            .execute()
        )
        existing_links = set()
        for link in (links_result.data or []):
            existing_links.add((link["source_article_id"], link["target_article_id"]))

        # Build link matrix
        link_matrix = []
        missing_links = []
        total_possible = 0
        total_linked = 0

        interlinking = InterlinkingService(supabase_client=self._supabase)

        for i, source in enumerate(spokes):
            for j, target in enumerate(spokes):
                if i == j:
                    continue

                total_possible += 1
                source_kw = (source.get("seo_keywords") or {}).get("keyword", "")
                target_kw = (target.get("seo_keywords") or {}).get("keyword", "")
                similarity = interlinking._jaccard_similarity(source_kw, target_kw)
                has_link = (source["article_id"], target["article_id"]) in existing_links

                entry = {
                    "source_article_id": source["article_id"],
                    "target_article_id": target["article_id"],
                    "source_keyword": source_kw,
                    "target_keyword": target_kw,
                    "similarity": round(similarity, 3),
                    "has_link": has_link,
                }
                link_matrix.append(entry)

                if has_link:
                    total_linked += 1
                elif similarity >= 0.2:
                    missing_links.append(entry)

        coverage_pct = round((total_linked / total_possible * 100) if total_possible > 0 else 0, 1)

        return {
            "cluster_id": cluster_id,
            "link_matrix": link_matrix,
            "missing_links": missing_links,
            "coverage_pct": coverage_pct,
            "total_possible": total_possible,
            "total_linked": total_linked,
        }

    # =========================================================================
    # AUTO-ASSIGNMENT
    # =========================================================================

    def auto_assign_keywords(
        self,
        project_id: str,
        dry_run: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Auto-assign unassigned keywords to clusters based on word overlap scoring.

        Scoring:
        - Cluster name word overlap: 3 points per matching word
        - Pillar keyword word overlap: 2 points per matching word
        - Existing spoke keyword overlap: 1 point per matching word

        Confidence bands:
        - HIGH (score >= 5 AND score >= 2x runner-up): auto-assign if not dry_run
        - MEDIUM (score >= 3): suggest with top 3 alternatives
        - LOW (score < 3): skip

        Args:
            project_id: Project UUID
            dry_run: If True, only return suggestions without assigning

        Returns:
            List of suggestion dicts with keyword, cluster, confidence, score
        """
        # Get all clusters with their spokes
        clusters_result = (
            self.supabase.table("seo_clusters")
            .select("id, name, pillar_keyword")
            .eq("project_id", project_id)
            .execute()
        )
        clusters = clusters_result.data or []

        if not clusters:
            return []

        # Get spoke keywords per cluster
        cluster_ids = [c["id"] for c in clusters]
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("cluster_id, seo_keywords(keyword)")
            .in_("cluster_id", cluster_ids)
            .execute()
        )

        cluster_spoke_words = {}
        for spoke in (spokes_result.data or []):
            cid = spoke["cluster_id"]
            kw = (spoke.get("seo_keywords") or {}).get("keyword", "")
            if cid not in cluster_spoke_words:
                cluster_spoke_words[cid] = set()
            cluster_spoke_words[cid].update(self._extract_words(kw))

        # Get unassigned keywords
        unassigned_result = (
            self.supabase.table("seo_keywords")
            .select("id, keyword")
            .eq("project_id", project_id)
            .is_("cluster_id", "null")
            .execute()
        )
        unassigned = unassigned_result.data or []

        results = []
        for kw in unassigned:
            kw_words = self._extract_words(kw["keyword"])
            if not kw_words:
                continue

            scores = []
            for cluster in clusters:
                score = 0

                # Cluster name overlap (3pts per word)
                name_words = self._extract_words(cluster["name"])
                score += len(kw_words & name_words) * 3

                # Pillar keyword overlap (2pts per word)
                pillar_words = self._extract_words(cluster.get("pillar_keyword") or "")
                score += len(kw_words & pillar_words) * 2

                # Spoke keyword overlap (1pt per word)
                spoke_words = cluster_spoke_words.get(cluster["id"], set())
                score += len(kw_words & spoke_words) * 1

                scores.append({
                    "cluster_id": cluster["id"],
                    "cluster_name": cluster["name"],
                    "score": score,
                })

            # Sort by score descending
            scores.sort(key=lambda s: s["score"], reverse=True)

            if not scores or scores[0]["score"] < 1:
                continue

            top = scores[0]
            runner_up_score = scores[1]["score"] if len(scores) > 1 else 0

            # Determine confidence
            if top["score"] >= 5 and top["score"] >= 2 * max(runner_up_score, 1):
                confidence = "HIGH"
            elif top["score"] >= 3:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            suggestion = {
                "keyword_id": kw["id"],
                "keyword": kw["keyword"],
                "cluster_id": top["cluster_id"],
                "cluster_name": top["cluster_name"],
                "confidence": confidence,
                "score": top["score"],
                "alternatives": [
                    {"cluster_id": s["cluster_id"], "cluster_name": s["cluster_name"], "score": s["score"]}
                    for s in scores[1:4]  # top 3 alternatives
                    if s["score"] > 0
                ],
            }
            results.append(suggestion)

            # Auto-assign HIGH confidence if not dry_run
            if not dry_run and confidence == "HIGH":
                try:
                    self.add_spoke(top["cluster_id"], kw["id"])
                except Exception as e:
                    logger.warning(f"Auto-assign failed for {kw['keyword']}: {e}")

        return results

    # =========================================================================
    # PRE-WRITE CHECK
    # =========================================================================

    def pre_write_check(self, keyword: str, project_id: str) -> Dict[str, Any]:
        """
        Check for content overlap before writing a new article.

        Uses Jaccard similarity (words > 3 chars) to detect cannibalization risks.

        Risk levels:
        - HIGH (>60%): recommend merge or unique angle
        - MEDIUM (30-60%): suggest as internal link candidates
        - CLEAR (<30%): safe to proceed

        Args:
            keyword: Keyword to check
            project_id: Project UUID

        Returns:
            Dict with risk_level, overlapping_articles, link_candidates, recommendation
        """
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        # Get all articles in the project
        articles_result = (
            self.supabase.table("seo_articles")
            .select("id, keyword, title, status, published_url")
            .eq("project_id", project_id)
            .execute()
        )
        articles = articles_result.data or []

        overlapping = []
        link_candidates = []
        interlinking = InterlinkingService()

        for article in articles:
            article_kw = article.get("keyword", "")
            overlap = interlinking._jaccard_similarity(keyword, article_kw)
            overlap_pct = round(overlap * 100, 1)

            if overlap_pct > 30:
                entry = {
                    "article_id": article["id"],
                    "keyword": article_kw,
                    "title": article.get("title") or article_kw,
                    "status": article.get("status"),
                    "overlap_pct": overlap_pct,
                }
                if overlap_pct > 60:
                    overlapping.append(entry)
                else:
                    link_candidates.append(entry)

        # Sort by overlap descending
        overlapping.sort(key=lambda x: x["overlap_pct"], reverse=True)
        link_candidates.sort(key=lambda x: x["overlap_pct"], reverse=True)

        if overlapping:
            risk_level = "HIGH"
            recommendation = (
                f"High overlap with {len(overlapping)} existing article(s). "
                "Consider merging or finding a unique angle to differentiate."
            )
        elif link_candidates:
            risk_level = "MEDIUM"
            recommendation = (
                f"Moderate overlap with {len(link_candidates)} article(s). "
                "These are good internal link candidates."
            )
        else:
            risk_level = "CLEAR"
            recommendation = "No significant overlap. Safe to proceed."

        return {
            "keyword": keyword,
            "risk_level": risk_level,
            "overlapping_articles": overlapping,
            "link_candidates": link_candidates,
            "recommendation": recommendation,
        }

    # =========================================================================
    # NEXT ARTICLE SUGGESTION
    # =========================================================================

    def suggest_next_article(
        self,
        project_id: str,
        cluster_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Suggest the best next article to write based on scoring.

        Scoring formula:
        (50 - KD) + log10(volume) * 10 + (10 - priority) * 5 + (cluster < 50% ? 20 : 0)

        Args:
            project_id: Project UUID
            cluster_id: Optional cluster UUID to filter by

        Returns:
            Top 5 suggestions with score breakdown and human-readable reasons
        """
        # Get planned spokes with keyword data
        query = (
            self.supabase.table("seo_cluster_spokes")
            .select("*, seo_keywords(keyword, search_volume, keyword_difficulty), seo_clusters!inner(id, name, project_id)")
            .eq("status", SpokeStatus.PLANNED.value)
        )

        if cluster_id:
            query = query.eq("cluster_id", cluster_id)

        spokes_result = query.execute()
        spokes = spokes_result.data or []

        # Filter to project
        spokes = [
            s for s in spokes
            if (s.get("seo_clusters") or {}).get("project_id") == project_id
        ]

        if not spokes:
            return []

        # Calculate cluster completion for bonus scoring
        cluster_completion = {}
        if spokes:
            unique_clusters = set(s["cluster_id"] for s in spokes)
            for cid in unique_clusters:
                all_spokes = (
                    self.supabase.table("seo_cluster_spokes")
                    .select("status")
                    .eq("cluster_id", cid)
                    .execute()
                )
                all_data = all_spokes.data or []
                total = len(all_data)
                published = sum(1 for s in all_data if s["status"] == SpokeStatus.PUBLISHED.value)
                cluster_completion[cid] = (published / total * 100) if total > 0 else 0

        suggestions = []
        for spoke in spokes:
            kw_data = spoke.get("seo_keywords") or {}
            cluster_data = spoke.get("seo_clusters") or {}

            kd = kw_data.get("keyword_difficulty") or 50
            volume = kw_data.get("search_volume") or 10
            priority = spoke.get("priority") or 2

            # Scoring formula
            kd_score = 50 - kd
            volume_score = math.log10(max(volume, 1)) * 10
            priority_score = (10 - priority) * 5
            completion = cluster_completion.get(spoke["cluster_id"], 100)
            cluster_bonus = 20 if completion < 50 else 0
            total_score = round(kd_score + volume_score + priority_score + cluster_bonus, 1)

            # Build human-readable reasons
            reasons = []
            if kd < 30:
                reasons.append(f"Low difficulty (KD: {kd:.0f}) — easy to rank")
            elif kd < 50:
                reasons.append(f"Medium difficulty (KD: {kd:.0f})")
            if volume >= 1000:
                reasons.append(f"High volume ({volume:,}/mo) — worth the effort")
            elif volume >= 100:
                reasons.append(f"Decent volume ({volume:,}/mo)")
            if priority == 1:
                reasons.append("High priority spoke")
            if completion < 50:
                reasons.append(f"Cluster at {completion:.0f}% — needs more content to build authority")

            suggestions.append({
                "spoke_id": spoke["id"],
                "keyword": kw_data.get("keyword", ""),
                "keyword_id": spoke["keyword_id"],
                "cluster_id": spoke["cluster_id"],
                "cluster_name": cluster_data.get("name", ""),
                "score": total_score,
                "kd": kd,
                "volume": volume,
                "priority": priority,
                "reasons": reasons,
            })

        # Sort by score descending, return top 5
        suggestions.sort(key=lambda s: s["score"], reverse=True)
        return suggestions[:5]

    # =========================================================================
    # GAP ANALYSIS
    # =========================================================================

    def analyze_gaps(self, cluster_id: str) -> List[Dict[str, Any]]:
        """
        Find unassigned keywords with high word overlap to cluster keywords.

        Args:
            cluster_id: Cluster UUID

        Returns:
            List of gap suggestions
        """
        # Get cluster's project and keywords
        cluster = (
            self.supabase.table("seo_clusters")
            .select("project_id, name, pillar_keyword")
            .eq("id", cluster_id)
            .execute()
        )
        if not cluster.data:
            return []

        project_id = cluster.data[0]["project_id"]
        cluster_name = cluster.data[0]["name"]
        pillar_keyword = cluster.data[0].get("pillar_keyword") or ""

        # Get cluster spoke keywords
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("seo_keywords(keyword)")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        cluster_words = self._extract_words(cluster_name)
        cluster_words |= self._extract_words(pillar_keyword)
        for spoke in (spokes_result.data or []):
            kw = (spoke.get("seo_keywords") or {}).get("keyword", "")
            cluster_words |= self._extract_words(kw)

        # Get unassigned keywords in the project
        unassigned_result = (
            self.supabase.table("seo_keywords")
            .select("id, keyword, search_volume, keyword_difficulty")
            .eq("project_id", project_id)
            .is_("cluster_id", "null")
            .execute()
        )

        suggestions = []
        for kw in (unassigned_result.data or []):
            kw_words = self._extract_words(kw["keyword"])
            if not kw_words or not cluster_words:
                continue

            overlap = len(kw_words & cluster_words) / len(kw_words | cluster_words)
            if overlap >= 0.2:
                suggestions.append({
                    "keyword_id": kw["id"],
                    "suggested_keyword": kw["keyword"],
                    "search_volume": kw.get("search_volume"),
                    "keyword_difficulty": kw.get("keyword_difficulty"),
                    "overlap_score": round(overlap, 3),
                    "reason": f"Word overlap with cluster '{cluster_name}': {overlap:.0%}",
                })

        suggestions.sort(key=lambda s: s["overlap_score"], reverse=True)

        # Save suggestions to DB
        for s in suggestions:
            try:
                self.supabase.table("seo_cluster_gap_suggestions").insert({
                    "cluster_id": cluster_id,
                    "suggested_keyword": s["suggested_keyword"],
                    "reason": s["reason"],
                    "search_volume": s["search_volume"],
                    "keyword_difficulty": s["keyword_difficulty"],
                }).execute()
            except Exception as e:
                logger.warning(f"Failed to save gap suggestion: {e}")

        return suggestions

    def accept_gap_suggestion(
        self,
        suggestion_id: str,
        keyword_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Accept a gap suggestion and optionally link to a keyword.

        Args:
            suggestion_id: Gap suggestion UUID
            keyword_id: Optional keyword UUID to link

        Returns:
            Updated suggestion record
        """
        updates = {"status": "accepted"}
        if keyword_id:
            updates["accepted_keyword_id"] = keyword_id

        result = (
            self.supabase.table("seo_cluster_gap_suggestions")
            .update(updates)
            .eq("id", suggestion_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    def reject_gap_suggestion(self, suggestion_id: str) -> None:
        """Reject a gap suggestion."""
        self.supabase.table("seo_cluster_gap_suggestions").update(
            {"status": "rejected"}
        ).eq("id", suggestion_id).execute()

    # =========================================================================
    # IMPORT & SCHEDULING
    # =========================================================================

    def import_existing_articles(
        self,
        cluster_id: str,
        article_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Bulk import existing articles and match to cluster spokes.

        Each article_data item should have: keyword, title, url,
        optionally shopify_id, word_count, status.

        Auto-matches to spokes by keyword text.

        Args:
            cluster_id: Cluster UUID
            article_data: List of article dicts to import

        Returns:
            List of import results with matched spoke info
        """
        # Get cluster's project
        cluster = (
            self.supabase.table("seo_clusters")
            .select("project_id")
            .eq("id", cluster_id)
            .execute()
        )
        if not cluster.data:
            raise ValueError(f"Cluster not found: {cluster_id}")

        project_id = cluster.data[0]["project_id"]

        # Get existing spokes for matching
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("id, keyword_id, seo_keywords(keyword)")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        spokes = spokes_result.data or []

        results = []
        for data in article_data:
            keyword = data.get("keyword", "")
            title = data.get("title", keyword)
            url = data.get("url", "")

            # Find matching spoke by keyword
            matched_spoke = None
            for spoke in spokes:
                spoke_kw = (spoke.get("seo_keywords") or {}).get("keyword", "")
                if spoke_kw.lower().strip() == keyword.lower().strip():
                    matched_spoke = spoke
                    break

            # Create or find article record
            article_status = data.get("status", SpokeStatus.PUBLISHED.value)
            article_result = self.supabase.table("seo_articles").insert({
                "project_id": project_id,
                "keyword": keyword,
                "title": title,
                "published_url": url,
                "cms_article_id": data.get("shopify_id"),
                "word_count": data.get("word_count", 0),
                "status": article_status,
                "brand_id": data.get("brand_id", ""),
                "organization_id": data.get("organization_id", ""),
            }).execute()

            article = article_result.data[0] if article_result.data else None
            result = {
                "keyword": keyword,
                "title": title,
                "article_id": article["id"] if article else None,
                "matched_spoke_id": None,
            }

            # Link to spoke if matched
            if matched_spoke and article:
                self.assign_article_to_spoke(matched_spoke["id"], article["id"])
                if article_status == SpokeStatus.PUBLISHED.value:
                    self.update_spoke(matched_spoke["id"], status=SpokeStatus.PUBLISHED.value)
                result["matched_spoke_id"] = matched_spoke["id"]

            results.append(result)

        return results

    def generate_publication_schedule(
        self,
        cluster_id: str,
        spokes_per_week: int = 3,
        start_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate a publication schedule for planned spokes.

        Pillar goes first, then spokes ordered by priority.

        Args:
            cluster_id: Cluster UUID
            spokes_per_week: Number of articles per week
            start_date: ISO date string (defaults to today)

        Returns:
            List of scheduled items with target dates
        """
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("id, role, priority, seo_keywords(keyword)")
            .eq("cluster_id", cluster_id)
            .eq("status", SpokeStatus.PLANNED.value)
            .order("priority")
            .execute()
        )
        spokes = spokes_result.data or []

        if not spokes:
            return []

        # Pillar first, then by priority
        pillars = [s for s in spokes if s["role"] == SpokeRole.PILLAR.value]
        others = [s for s in spokes if s["role"] != SpokeRole.PILLAR.value]
        ordered = pillars + others

        # Calculate dates
        if start_date:
            current_date = datetime.fromisoformat(start_date)
        else:
            current_date = datetime.now(timezone.utc)

        days_between = 7 / spokes_per_week
        schedule = []

        for i, spoke in enumerate(ordered):
            target_date = current_date + timedelta(days=i * days_between)
            keyword = (spoke.get("seo_keywords") or {}).get("keyword", "")

            schedule.append({
                "spoke_id": spoke["id"],
                "keyword": keyword,
                "role": spoke["role"],
                "priority": spoke["priority"],
                "target_date": target_date.strftime("%Y-%m-%d"),
                "week_number": (i // spokes_per_week) + 1,
            })

        # Persist schedule to cluster metadata
        cluster = (
            self.supabase.table("seo_clusters")
            .select("metadata")
            .eq("id", cluster_id)
            .execute()
        )
        metadata = (cluster.data[0].get("metadata") or {}) if cluster.data else {}
        metadata["publication_schedule"] = schedule
        self.supabase.table("seo_clusters").update(
            {"metadata": metadata}
        ).eq("id", cluster_id).execute()

        return schedule

    def get_publication_schedule(self, cluster_id: str) -> List[Dict[str, Any]]:
        """
        Get the existing publication schedule from cluster metadata.

        Args:
            cluster_id: Cluster UUID

        Returns:
            List of scheduled items or empty list
        """
        cluster = (
            self.supabase.table("seo_clusters")
            .select("metadata")
            .eq("id", cluster_id)
            .execute()
        )
        if not cluster.data:
            return []

        metadata = cluster.data[0].get("metadata") or {}
        return metadata.get("publication_schedule", [])

    # =========================================================================
    # UI CONVENIENCE METHODS
    # =========================================================================

    def get_keywords_for_pool(
        self,
        project_id: str,
        filter_type: str = "unassigned",
        intent: str = "all",
        search_text: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Get keywords for the keyword pool view with filtering.

        Args:
            project_id: Project UUID
            filter_type: 'unassigned', 'assigned', or 'all'
            intent: Intent filter or 'all'
            search_text: Text search filter (client-side)

        Returns:
            List of keyword records
        """
        query = (
            self.supabase.table("seo_keywords")
            .select("id, keyword, search_volume, keyword_difficulty, search_intent, cluster_id, status")
            .eq("project_id", project_id)
            .order("keyword")
        )

        if filter_type == "unassigned":
            query = query.is_("cluster_id", "null")
        elif filter_type == "assigned":
            query = query.not_.is_("cluster_id", "null")

        if intent != "all":
            query = query.eq("search_intent", intent)

        result = query.execute()
        keywords = result.data or []

        if search_text:
            search_lower = search_text.lower()
            keywords = [k for k in keywords if search_lower in k.get("keyword", "").lower()]

        return keywords

    def mark_spokes_published_for_article(self, article_id: str) -> int:
        """
        Mark all spokes linked to an article as published.

        Called after successful article publish.

        Args:
            article_id: Article UUID

        Returns:
            Number of spokes updated
        """
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("id")
            .eq("article_id", article_id)
            .execute()
        )
        count = 0
        for spoke in (spokes_result.data or []):
            self.update_spoke(spoke["id"], status=SpokeStatus.PUBLISHED.value)
            count += 1
        return count

    def get_unlinked_planned_spokes(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get planned spokes without linked articles, for the article writer dropdown.

        Args:
            project_id: Project UUID

        Returns:
            List of dicts with spoke_id, cluster_name, keyword
        """
        clusters = self.list_clusters(project_id)
        results = []
        for cluster in clusters:
            full = self.get_cluster(cluster["id"])
            for spoke in (full or {}).get("spokes", []):
                if spoke.get("status") == SpokeStatus.PLANNED.value and not spoke.get("article_id"):
                    kw = (spoke.get("seo_keywords") or {}).get("keyword", "")
                    results.append({
                        "spoke_id": spoke["id"],
                        "cluster_name": cluster["name"],
                        "keyword": kw,
                    })
        return results

    def get_cluster_spoke_article_ids(self, cluster_id: str) -> List[str]:
        """
        Get article IDs for all spokes in a cluster.

        Args:
            cluster_id: Cluster UUID

        Returns:
            List of article UUIDs (excludes None)
        """
        spokes_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("article_id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        return [s["article_id"] for s in (spokes_result.data or []) if s.get("article_id")]

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _extract_words(text: str) -> set:
        """Extract significant words (>3 chars) from text, lowercased."""
        if not text:
            return set()
        return {w for w in text.lower().split() if len(w) > 3}

    def _update_spoke_count(self, cluster_id: str) -> None:
        """Recompute spoke_count on seo_clusters from the join table."""
        count_result = (
            self.supabase.table("seo_cluster_spokes")
            .select("id")
            .eq("cluster_id", cluster_id)
            .execute()
        )
        count = len(count_result.data or [])
        self.supabase.table("seo_clusters").update(
            {"spoke_count": count}
        ).eq("id", cluster_id).execute()
