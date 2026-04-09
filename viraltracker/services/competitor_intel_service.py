"""
Competitor Ad Intelligence Service.

Orchestrates the ingredient pack pipeline:
scrape competitor ads -> composite score ranking -> video analysis via Gemini ->
aggregate extractions -> save to angle pipeline.

Also provides remix: take a competitor video's structure + brand context -> ad script.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from viraltracker.services.models import CandidateSourceType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompt (validated against real competitor videos)
# ---------------------------------------------------------------------------
INGREDIENT_EXTRACTION_PROMPT = """SYSTEM: You are a competitive ad intelligence analyst. Analyze this video ad and extract structured marketing intelligence. Output strict JSON only. No explanations, no markdown.

Return JSON matching this exact schema:

{
  "transcription": {
    "full_text": "Complete transcript of all spoken words",
    "timestamps": [{"time": "0:00-0:03", "text": "spoken words in this segment"}]
  },
  "storyboard": [
    {"timestamp": "0:00-0:03", "description": "Visual description of what's happening on screen"}
  ],
  "text_overlays": [
    {"timestamp": "0:02", "text": "Text shown on screen"}
  ],
  "hook": {
    "text": "The exact hook used in first 3-5 seconds (spoken + text overlay combined)",
    "type": "One of: relatable_slice, shock_violation, hot_take, question, statistic, before_after, social_proof, urgency, curiosity_gap, pain_call_out, transformation, authority, contrarian, story_open",
    "timestamp": "0:00-0:05"
  },
  "persona_4d": {
    "demographics": "Age range, gender, location indicators, income signals",
    "psychographics": "Values, lifestyle, aspirations, self-identity",
    "beliefs": ["Core beliefs this ad assumes the viewer holds"],
    "behaviors": ["Observable behaviors of the target audience (buying patterns, media consumption, daily habits)"]
  },
  "awareness_level": "One of: unaware, problem_aware, solution_aware, product_aware, most_aware",
  "awareness_reasoning": "Why you classified it at this level",
  "benefits": ["Specific benefits promised or implied"],
  "pain_points": ["Specific pain points addressed or agitated"],
  "jtbds": ["Jobs-to-be-done framing: 'When I [situation], I want to [motivation], so I can [outcome]'"],
  "angles": [
    {
      "belief_statement": "The underlying belief this angle targets",
      "evidence_in_video": "What in the video supports this angle"
    }
  ],
  "objections_addressed": ["Specific objections the video preemptively handles"],
  "unique_mechanism": "The unique mechanism (UM) presented - HOW the product/solution works differently",
  "unique_problem_mechanism": "The unique problem mechanism (UMP) - WHY the problem exists in a way others haven't identified",
  "unique_solution_mechanism": "The unique solution mechanism (UMS) - WHY this specific solution works when others don't",
  "cta": {
    "text": "The call to action",
    "type": "One of: shop_now, learn_more, sign_up, get_offer, watch_more, click_link, other"
  },
  "emotional_triggers": ["Primary emotions this ad targets (fear, desire, frustration, hope, curiosity, etc.)"],
  "messaging_sequence": [
    {
      "stage": "One of: hook, problem, agitate, solution, proof, cta, story, transition",
      "content": "What happens at this stage",
      "timestamp": "approximate time range"
    }
  ],
  "ad_format": "One of: ugc, professional, testimonial, demo, talking_head, slideshow, mixed, animated",
  "estimated_production_level": "One of: low_budget, mid_budget, high_budget"
}

Be specific and evidence-based. Quote actual words from the video where possible. Do not fabricate information - if something is unclear, use null."""

PROMPT_VERSION = "v1"
MODEL_VERSION = "gemini-3-pro-preview"


# ---------------------------------------------------------------------------
# Composite scoring (reuses math from template_scoring_service.py)
# ---------------------------------------------------------------------------

def compute_composite_score(position: int, total: int, days_active: int) -> Dict[str, float]:
    """Compute composite ad score: velocity*0.4 + rank*0.3 + durability*0.3.

    Returns dict with composite, velocity, rank, durability scores (all 0-1).
    """
    # Velocity (from ImpressionVelocityScorer)
    if total and total > 1:
        position_percentile = 1.0 - (position - 1) / (total - 1)
    else:
        position_percentile = 1.0 if position == 1 else 0.5
    recency_factor = 2 ** (-max(days_active, 1) / 30)
    velocity = position_percentile * (0.4 + 0.6 * recency_factor)

    # Rank (from ImpressionRankScorer)
    rank = max(0.2, 1.0 - (position - 1) * 0.016)

    # Durability (new: caps at 90 days)
    durability = min(1.0, max(days_active, 0) / 90)

    composite = 0.4 * velocity + 0.3 * rank + 0.3 * durability

    return {
        "composite": round(composite, 4),
        "velocity": round(velocity, 4),
        "rank": round(rank, 4),
        "durability": round(durability, 4),
    }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _text_similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio on lowercased strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _dedup_by_similarity(items: List[Dict], text_key: str, threshold: float = 0.85) -> List[Dict]:
    """Deduplicate dicts by text similarity on a given key. Keeps higher-scored item."""
    if not items:
        return []
    deduped = [items[0]]
    for item in items[1:]:
        is_dup = False
        for existing in deduped:
            if _text_similarity(item.get(text_key, ""), existing.get(text_key, "")) > threshold:
                # Keep higher-scored, bump frequency
                existing["frequency"] = existing.get("frequency", 1) + item.get("frequency", 1)
                is_dup = True
                break
        if not is_dup:
            deduped.append(item)
    return deduped


def _dedup_strings(items: List[str], threshold: float = 0.85) -> List[Dict[str, Any]]:
    """Deduplicate string lists, tracking frequency."""
    if not items:
        return []
    result: List[Dict[str, Any]] = [{"text": items[0], "frequency": 1}]
    for text in items[1:]:
        merged = False
        for existing in result:
            if _text_similarity(text, existing["text"]) > threshold:
                existing["frequency"] += 1
                merged = True
                break
        if not merged:
            result.append({"text": text, "frequency": 1})
    result.sort(key=lambda x: x["frequency"], reverse=True)
    return result


def aggregate_extractions(
    extractions: List[Dict],
    video_scores: List[float],
) -> Dict[str, Any]:
    """Combine N per-video extractions into a single ingredient pack.

    Args:
        extractions: List of raw extraction dicts from Gemini (one per video).
        video_scores: Composite scores parallel to extractions list.

    Returns:
        Aggregated pack_data dict.
    """
    n = len(extractions)
    if n == 0:
        return {}

    # --- Hooks: ranked by source video composite score, deduped >85% ---
    hooks = []
    for ext, score in zip(extractions, video_scores):
        hook = ext.get("hook")
        if hook and isinstance(hook, dict) and hook.get("text"):
            hooks.append({
                "text": hook["text"],
                "type": hook.get("type", "unknown"),
                "timestamp": hook.get("timestamp", ""),
                "score": score,
                "frequency": 1,
            })
    hooks.sort(key=lambda h: h["score"], reverse=True)
    hooks = _dedup_by_similarity(hooks, "text", 0.85)

    # --- 4D Personas: merge if Jaccard >0.60 on beliefs+behaviors ---
    personas = []
    for ext in extractions:
        p = ext.get("persona_4d")
        if not p or not isinstance(p, dict):
            continue
        beliefs = set(b.lower() for b in (p.get("beliefs") or []) if isinstance(b, str))
        behaviors = set(b.lower() for b in (p.get("behaviors") or []) if isinstance(b, str))
        merged = False
        for existing in personas:
            existing_set = set(existing.get("_beliefs_set", set())) | set(existing.get("_behaviors_set", set()))
            new_set = beliefs | behaviors
            if _jaccard(existing_set, new_set) > 0.60:
                # Merge: combine unique beliefs and behaviors
                existing["beliefs"] = list(set(existing.get("beliefs", [])) | set(p.get("beliefs") or []))
                existing["behaviors"] = list(set(existing.get("behaviors", [])) | set(p.get("behaviors") or []))
                existing["_beliefs_set"] = existing["_beliefs_set"] | beliefs
                existing["_behaviors_set"] = existing["_behaviors_set"] | behaviors
                existing["frequency"] = existing.get("frequency", 1) + 1
                merged = True
                break
        if not merged:
            personas.append({
                "demographics": p.get("demographics", ""),
                "psychographics": p.get("psychographics", ""),
                "beliefs": list(p.get("beliefs") or []),
                "behaviors": list(p.get("behaviors") or []),
                "frequency": 1,
                "_beliefs_set": beliefs,
                "_behaviors_set": behaviors,
            })
    # Strip internal tracking sets
    for p in personas:
        p.pop("_beliefs_set", None)
        p.pop("_behaviors_set", None)

    # --- Awareness levels: distribution + mode ---
    awareness_counts: Dict[str, int] = {}
    for ext in extractions:
        level = ext.get("awareness_level")
        if level and isinstance(level, str):
            awareness_counts[level] = awareness_counts.get(level, 0) + 1
    awareness_total = sum(awareness_counts.values()) or 1
    awareness_distribution = {k: round(v / awareness_total, 2) for k, v in awareness_counts.items()}
    primary_awareness = max(awareness_counts, key=awareness_counts.get) if awareness_counts else "unknown"

    # --- Benefits: frequency * source_score ranking ---
    all_benefits: List[Dict] = []
    for ext, score in zip(extractions, video_scores):
        for b in (ext.get("benefits") or []):
            if isinstance(b, str) and b.strip():
                all_benefits.append({"text": b, "source_score": score})
    benefits_deduped = _dedup_strings([b["text"] for b in all_benefits])
    # Attach max source_score per benefit
    for bd in benefits_deduped:
        bd["source_score"] = max(
            (b["source_score"] for b in all_benefits if _text_similarity(b["text"], bd["text"]) > 0.85),
            default=0.0
        )
        bd["rank_score"] = bd["frequency"] * bd["source_score"]
    benefits_deduped.sort(key=lambda x: x["rank_score"], reverse=True)

    # --- Pain points: frequency ranked ---
    all_pains = []
    for ext in extractions:
        for p in (ext.get("pain_points") or []):
            if isinstance(p, str) and p.strip():
                all_pains.append(p)
    pain_points = _dedup_strings(all_pains)

    # --- JTBDs: frequency ranked ---
    all_jtbds = []
    for ext in extractions:
        for j in (ext.get("jtbds") or []):
            if isinstance(j, str) and j.strip():
                all_jtbds.append(j)
    jtbds = _dedup_strings(all_jtbds)

    # --- Angles: dedup >85% on belief_statement ---
    angles = []
    for i, (ext, score) in enumerate(zip(extractions, video_scores)):
        for a in (ext.get("angles") or []):
            if isinstance(a, dict) and a.get("belief_statement"):
                angles.append({
                    "belief_statement": a["belief_statement"],
                    "evidence": a.get("evidence_in_video", a.get("evidence", "")),
                    "score": score,
                    "frequency": 1,
                    "video_index": i,
                })
    angles.sort(key=lambda a: a["score"], reverse=True)
    angles = _dedup_by_similarity(angles, "belief_statement", 0.85)
    for a in angles:
        a.pop("video_index", None)

    # --- Objections: unique, frequency ranked ---
    all_objections = []
    for ext in extractions:
        for o in (ext.get("objections_addressed") or []):
            if isinstance(o, str) and o.strip():
                all_objections.append(o)
    objections = _dedup_strings(all_objections)

    # --- Mechanisms: frequency with variants ---
    def _aggregate_mechanism(field_name: str) -> List[Dict]:
        mechs = []
        for ext in extractions:
            val = ext.get(field_name)
            if val and isinstance(val, str) and val.strip():
                mechs.append(val)
        return _dedup_strings(mechs)

    unique_mechanisms = _aggregate_mechanism("unique_mechanism")
    unique_problem_mechanisms = _aggregate_mechanism("unique_problem_mechanism")
    unique_solution_mechanisms = _aggregate_mechanism("unique_solution_mechanism")

    # --- Emotional triggers ---
    all_triggers = []
    for ext in extractions:
        for t in (ext.get("emotional_triggers") or []):
            if isinstance(t, str) and t.strip():
                all_triggers.append(t)
    emotional_triggers = _dedup_strings(all_triggers)

    # --- Field coverage ---
    coverage_fields = [
        "transcription", "hook", "persona_4d", "awareness_level",
        "benefits", "pain_points", "jtbds", "angles",
        "objections_addressed", "unique_mechanism",
        "unique_problem_mechanism", "unique_solution_mechanism",
        "emotional_triggers", "messaging_sequence",
    ]
    field_coverage = {}
    for field in coverage_fields:
        populated = 0
        for ext in extractions:
            val = ext.get(field)
            if val is not None:
                if isinstance(val, list) and len(val) > 0:
                    populated += 1
                elif isinstance(val, dict) and val:
                    populated += 1
                elif isinstance(val, str) and val.strip():
                    populated += 1
        field_coverage[field] = {"populated": populated, "total": n}

    return {
        "hooks": hooks,
        "personas": personas,
        "benefits": benefits_deduped,
        "pain_points": pain_points,
        "jtbds": jtbds,
        "angles": angles,
        "awareness_distribution": awareness_distribution,
        "primary_awareness_level": primary_awareness,
        "objections": objections,
        "unique_mechanisms": unique_mechanisms,
        "unique_problem_mechanisms": unique_problem_mechanisms,
        "unique_solution_mechanisms": unique_solution_mechanisms,
        "emotional_triggers": emotional_triggers,
        "field_coverage": field_coverage,
    }


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class CompetitorIntelService:
    """Orchestrates competitor ad intelligence extraction and aggregation."""

    def __init__(self):
        from supabase import create_client
        import os
        self.supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    # --- org_id resolution ---

    def _resolve_org_id(self, organization_id: str, brand_id: Optional[str] = None) -> str:
        """Resolve 'all' org_id to real UUID via brand lookup."""
        if organization_id != "all":
            return organization_id
        if not brand_id:
            raise ValueError("Cannot resolve 'all' org_id without a brand_id")
        row = (
            self.supabase.table("brands")
            .select("organization_id")
            .eq("id", brand_id)
            .limit(1)
            .execute()
        )
        if row.data:
            return row.data[0]["organization_id"]
        raise ValueError(f"Brand {brand_id} not found, cannot resolve org_id")

    # --- Scoring ---

    def score_competitor_ads(
        self,
        competitor_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Score and rank competitor ads by composite formula.

        Only includes ads that have downloaded video assets in competitor_ad_assets.
        """
        # First, find which ads have downloaded video assets (source of truth)
        ads_with_videos = self._get_ads_with_video_assets(competitor_id)
        if not ads_with_videos:
            return []

        ad_ids_with_video = set(ads_with_videos.keys())

        # Fetch ad metadata for those ads
        resp = (
            self.supabase.table("competitor_ads")
            .select("id, competitor_id, page_name, snapshot_data, started_running, link_url, ad_archive_id")
            .eq("competitor_id", competitor_id)
            .in_("id", list(ad_ids_with_video))
            .execute()
        )
        if not resp.data:
            return []

        now = datetime.now(timezone.utc)
        scored = []
        total_ads = len(resp.data)

        for ad in resp.data:
            # Determine position and total from snapshot
            snapshot = ad.get("snapshot_data") or {}
            if isinstance(snapshot, str):
                try:
                    snapshot = json.loads(snapshot)
                except (json.JSONDecodeError, TypeError):
                    snapshot = {}

            position = snapshot.get("position") or ad.get("position")
            total = snapshot.get("total") or ad.get("total")

            # Compute days active from started_running column.
            # Falls back to snapshot_data.start_date for rows scraped before column existed.
            start_str = ad.get("started_running") or snapshot.get("start_date")
            if start_str:
                try:
                    if isinstance(start_str, str):
                        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    else:
                        start_dt = start_str
                    # Ensure timezone-aware for subtraction with now (UTC)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    days_active = max((now - start_dt).days, 0)
                except (ValueError, TypeError):
                    days_active = 0
            else:
                days_active = 0

            # Default position/total if missing
            if position is None:
                position = len(scored) + 1
            if total is None:
                total = total_ads

            scores = compute_composite_score(int(position), int(total), days_active)

            scored.append({
                "ad_id": ad["id"],
                "competitor_id": ad["competitor_id"],
                "page_name": ad.get("page_name"),
                "ad_archive_id": ad.get("ad_archive_id"),
                "started_running": ad.get("started_running"),
                "link_url": ad.get("link_url"),
                "days_active": days_active,
                "position": int(position),
                "total": int(total),
                **scores,
            })

        scored.sort(key=lambda x: x["composite"], reverse=True)
        return scored[:limit]

    def _get_ads_with_video_assets(self, competitor_id: str) -> Dict[str, Dict]:
        """Get all competitor ads that have downloaded video assets.

        Returns dict mapping ad_id -> asset info.
        """
        # Get ad IDs for this competitor
        ads_resp = (
            self.supabase.table("competitor_ads")
            .select("id")
            .eq("competitor_id", competitor_id)
            .execute()
        )
        if not ads_resp.data:
            return {}

        ad_ids = [a["id"] for a in ads_resp.data]

        # Find which ones have video assets downloaded
        assets_resp = (
            self.supabase.table("competitor_ad_assets")
            .select("id, competitor_ad_id, storage_path, mime_type")
            .eq("asset_type", "video")
            .in_("competitor_ad_id", ad_ids)
            .execute()
        )

        result = {}
        for a in (assets_resp.data or []):
            if a.get("storage_path"):
                result[a["competitor_ad_id"]] = {
                    "asset_id": a["id"],
                    "storage_path": a["storage_path"],
                    "mime_type": a.get("mime_type"),
                }
        return result

    # --- Video asset lookup ---

    def get_video_assets_for_ads(self, ad_ids: List[str]) -> Dict[str, Dict]:
        """Get downloaded video assets for a list of ad IDs.

        Returns dict mapping ad_id -> asset info (id, storage_path, mime_type).
        """
        if not ad_ids:
            return {}

        resp = (
            self.supabase.table("competitor_ad_assets")
            .select("id, competitor_ad_id, asset_type, storage_path, mime_type")
            .eq("asset_type", "video")
            .in_("competitor_ad_id", ad_ids)
            .execute()
        )

        assets = {}
        for a in (resp.data or []):
            if a.get("storage_path"):
                assets[a["competitor_ad_id"]] = {
                    "asset_id": a["id"],
                    "storage_path": a["storage_path"],
                    "mime_type": a.get("mime_type"),
                }
        return assets

    def check_video_readiness(self, competitor_id: str) -> Dict[str, Any]:
        """Pre-flight check: how many video ads have downloaded assets."""
        assets = self._get_ads_with_video_assets(competitor_id)
        count = len(assets)

        if count == 0:
            return {"total_video_ads": 0, "downloaded": 0, "ready": False, "message": "No video ads found for this competitor."}

        return {
            "total_video_ads": count,
            "downloaded": count,
            "ready": count >= 3,
            "message": f"{count} video ads with downloaded assets."
                       + (" Ready to generate pack." if count >= 3 else " Need at least 3. Download more assets first."),
        }

    # --- Pack generation ---

    def _get_cached_extraction(self, asset_id: str) -> Optional[Dict]:
        """Check if we already have a cached extraction for this asset + prompt version."""
        try:
            resp = (
                self.supabase.table("competitor_intel_video_cache")
                .select("extraction")
                .eq("asset_id", asset_id)
                .eq("prompt_version", PROMPT_VERSION)
                .limit(1)
                .execute()
            )
            if resp.data:
                logger.info(f"Cache hit for asset {asset_id} (prompt {PROMPT_VERSION})")
                return resp.data[0]["extraction"]
        except Exception as e:
            logger.warning(f"Cache lookup failed for {asset_id}: {e}")
        return None

    def _save_to_cache(self, asset_id: str, extraction: Dict):
        """Save extraction to cache for future reuse."""
        try:
            self.supabase.table("competitor_intel_video_cache").upsert({
                "asset_id": asset_id,
                "prompt_version": PROMPT_VERSION,
                "model_version": MODEL_VERSION,
                "extraction": extraction,
            }, on_conflict="asset_id,prompt_version").execute()
        except Exception as e:
            logger.warning(f"Failed to cache extraction for {asset_id}: {e}")

    async def analyze_single_video(
        self,
        asset_id: str,
        storage_path: str,
    ) -> Dict[str, Any]:
        """Analyze a single video using the ingredient extraction prompt.

        Checks cache first — only calls Gemini if no cached result exists
        for this asset_id + prompt_version.
        """
        # Check cache first
        cached = self._get_cached_extraction(asset_id)
        if cached:
            return cached

        # Cache miss — run Gemini analysis
        from viraltracker.services.brand_research_service import BrandResearchService

        service = BrandResearchService()
        result = await service.analyze_video(
            asset_id=asset_id,
            storage_path=storage_path,
            skip_save=True,
            prompt=INGREDIENT_EXTRACTION_PROMPT,
        )

        # Save to cache
        self._save_to_cache(asset_id, result)

        return result

    def create_pack_record(
        self,
        competitor_id: str,
        organization_id: str,
        video_count: int,
        product_id: Optional[str] = None,
        scoring_metadata: Optional[List[Dict]] = None,
    ) -> str:
        """Create a pending pack record and return its ID."""
        pack_id = str(uuid.uuid4())
        self.supabase.table("competitor_intel_packs").insert({
            "id": pack_id,
            "competitor_id": competitor_id,
            "organization_id": organization_id,
            "product_id": product_id,
            "video_count": video_count,
            "videos_completed": 0,
            "status": "processing",
            "scoring_metadata": scoring_metadata or [],
            "prompt_version": PROMPT_VERSION,
            "model_version": MODEL_VERSION,
        }).execute()
        return pack_id

    def update_pack_progress(self, pack_id: str, videos_completed: int, video_analysis: Optional[Dict] = None):
        """Update pack with completed video count and optionally append a video analysis."""
        updates: Dict[str, Any] = {
            "videos_completed": videos_completed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.supabase.table("competitor_intel_packs").update(updates).eq("id", pack_id).execute()

        # Append video analysis to JSONB array if provided
        if video_analysis:
            # Fetch current analyses, append, save
            row = self.supabase.table("competitor_intel_packs").select("video_analyses").eq("id", pack_id).single().execute()
            analyses = row.data.get("video_analyses") or []
            analyses.append(video_analysis)
            self.supabase.table("competitor_intel_packs").update({"video_analyses": analyses}).eq("id", pack_id).execute()

    def finalize_pack(
        self,
        pack_id: str,
        extractions: List[Dict],
        video_scores: List[float],
        failed_count: int,
        total_count: int,
    ):
        """Aggregate extractions and finalize the pack record."""
        success_count = len(extractions)

        # Determine status
        if success_count == 0:
            status = "failed"
        elif failed_count > 0 and success_count / total_count >= 0.5:
            status = "partial"
        elif failed_count > 0:
            status = "failed"
        else:
            status = "complete"

        # Aggregate
        pack_data = aggregate_extractions(extractions, video_scores)

        self.supabase.table("competitor_intel_packs").update({
            "pack_data": pack_data,
            "field_coverage": pack_data.get("field_coverage", {}),
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", pack_id).execute()

        return {"status": status, "pack_data": pack_data}

    # --- Pack retrieval ---

    def get_packs_for_competitor(self, competitor_id: str, organization_id: str) -> List[Dict]:
        """Get all ingredient packs for a competitor, newest first."""
        query = (
            self.supabase.table("competitor_intel_packs")
            .select("*")
            .eq("competitor_id", competitor_id)
        )
        # Superuser "all" is not a valid UUID — skip org filter
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)
        resp = query.order("created_at", desc=True).execute()
        return resp.data or []

    def get_pack(self, pack_id: str) -> Optional[Dict]:
        """Get a single pack by ID."""
        resp = (
            self.supabase.table("competitor_intel_packs")
            .select("*")
            .eq("id", pack_id)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    # --- Save to angle pipeline ---

    def save_to_angle_pipeline(
        self,
        pack_id: str,
        product_id: str,
        organization_id: str,
        brand_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Save pack ingredients as angle candidates.

        Creates candidates from top hooks, angles, pain points, and JTBDs.
        """
        from viraltracker.services.angle_candidate_service import AngleCandidateService

        org_id = self._resolve_org_id(organization_id, brand_id)

        pack = self.get_pack(pack_id)
        if not pack:
            raise ValueError(f"Pack {pack_id} not found")

        pack_data = pack.get("pack_data") or {}
        service = AngleCandidateService()
        counts = {"hooks": 0, "angles": 0, "pain_points": 0, "jtbds": 0}

        # Top hooks -> candidates
        for hook in (pack_data.get("hooks") or [])[:5]:
            try:
                service.create_candidate(
                    product_id=product_id,
                    name=(hook.get("text", "")[:50] or "Competitor hook"),
                    belief_statement=hook.get("text", ""),
                    source_type=CandidateSourceType.COMPETITOR_INTEL.value,
                    candidate_type="ad_hypothesis",
                    explanation=f"Hook type: {hook.get('type', 'unknown')} (from competitor intel pack)",
                    organization_id=org_id,
                )
                counts["hooks"] += 1
            except Exception as e:
                logger.warning(f"Failed to save hook candidate: {e}")

        # Top angles -> candidates
        for angle in (pack_data.get("angles") or [])[:5]:
            try:
                service.create_candidate(
                    product_id=product_id,
                    name=(angle.get("belief_statement", "")[:50] or "Competitor angle"),
                    belief_statement=angle.get("belief_statement", ""),
                    source_type=CandidateSourceType.COMPETITOR_INTEL.value,
                    candidate_type="ad_hypothesis",
                    explanation=angle.get("evidence", "From competitor intel pack"),
                    organization_id=org_id,
                )
                counts["angles"] += 1
            except Exception as e:
                logger.warning(f"Failed to save angle candidate: {e}")

        # Pain points -> candidates
        for pain in (pack_data.get("pain_points") or [])[:5]:
            text = pain.get("text", "") if isinstance(pain, dict) else str(pain)
            if not text:
                continue
            try:
                service.create_candidate(
                    product_id=product_id,
                    name=text[:50],
                    belief_statement=text,
                    source_type=CandidateSourceType.COMPETITOR_INTEL.value,
                    candidate_type="pain_signal",
                    explanation="Pain point from competitor intel pack",
                    organization_id=org_id,
                )
                counts["pain_points"] += 1
            except Exception as e:
                logger.warning(f"Failed to save pain point candidate: {e}")

        # JTBDs -> candidates
        for jtbd in (pack_data.get("jtbds") or [])[:5]:
            text = jtbd.get("text", "") if isinstance(jtbd, dict) else str(jtbd)
            if not text:
                continue
            try:
                service.create_candidate(
                    product_id=product_id,
                    name=text[:50],
                    belief_statement=text,
                    source_type=CandidateSourceType.COMPETITOR_INTEL.value,
                    candidate_type="jtbd",
                    explanation="JTBD from competitor intel pack",
                    organization_id=org_id,
                )
                counts["jtbds"] += 1
            except Exception as e:
                logger.warning(f"Failed to save JTBD candidate: {e}")

        total = sum(counts.values())
        logger.info(f"Saved {total} candidates from pack {pack_id}: {counts}")
        return counts

    # --- Remix ---

    async def remix_video(
        self,
        video_extraction: Dict,
        brand_context: str,
        product_description: Optional[str] = None,
        target_audience: Optional[str] = None,
        brand_guidelines: Optional[str] = None,
        brand_name: Optional[str] = None,
        product_name: Optional[str] = None,
        locked_ingredients: Optional[List[str]] = None,
        creativity: int = 2,
    ) -> Dict[str, Any]:
        """Remix a competitor video's structure into an ad script for the user's brand.

        Takes the competitor's messaging structure, hooks, and emotional arc,
        then generates an adapted script via Claude.

        Args:
            locked_ingredients: List of ingredient keys to keep from the original video.
                Options: hook, messaging_sequence, ad_format, emotional_triggers,
                awareness_level, persona_4d, pain_points, benefits
            creativity: 1-5 scale controlling how different the remix is from the original.
                1=carbon copy (swap product only), 5=reimagined (same insight, new ad)
        """
        import anthropic

        client = anthropic.Anthropic()
        locked = set(locked_ingredients or [])

        # Build competitor structure summary
        transcription = video_extraction.get("transcription", {})
        full_text = transcription.get("full_text", "") if isinstance(transcription, dict) else ""
        hook = video_extraction.get("hook", {})
        hook_text = hook.get("text", "") if isinstance(hook, dict) else ""
        hook_type = hook.get("type", "") if isinstance(hook, dict) else ""
        messaging = video_extraction.get("messaging_sequence", [])
        messaging_text = "\n".join(
            f"- {m.get('stage', '?')}: {m.get('content', '')}" for m in messaging if isinstance(m, dict)
        ) or "Not available"
        triggers = ", ".join(video_extraction.get("emotional_triggers", [])) or "Not specified"
        awareness = video_extraction.get("awareness_level", "unknown")
        ad_format = video_extraction.get("ad_format", "unknown")
        pain_points = video_extraction.get("pain_points", [])
        benefits = video_extraction.get("benefits", [])
        persona = video_extraction.get("persona_4d", {})

        # Build locked-ingredients instruction
        locked_lines = []
        if "hook" in locked:
            locked_lines.append(f"- HOOK: Keep the same hook type ({hook_type}) and style. Mirror the hook closely: \"{hook_text}\"")
        if "messaging_sequence" in locked:
            locked_lines.append(f"- MESSAGING SEQUENCE: Keep the exact same stage order and structure:\n{messaging_text}")
        if "ad_format" in locked:
            locked_lines.append(f"- AD FORMAT: Keep the same format ({ad_format})")
        if "emotional_triggers" in locked:
            locked_lines.append(f"- EMOTIONAL TRIGGERS: Use the same emotional triggers: {triggers}")
        if "awareness_level" in locked:
            locked_lines.append(f"- AWARENESS LEVEL: Target the same awareness level ({awareness})")
        if "persona_4d" in locked:
            persona_str = json.dumps(persona, indent=2) if persona else "Not available"
            locked_lines.append(f"- TARGET PERSONA: Keep the same target persona:\n{persona_str}")
        if "pain_points" in locked:
            pains_str = ", ".join(pain_points) if pain_points else "Not specified"
            locked_lines.append(f"- PAIN POINTS: Address the same pain points: {pains_str}")
        if "benefits" in locked:
            bens_str = ", ".join(benefits) if benefits else "Not specified"
            locked_lines.append(f"- BENEFITS: Highlight the same benefits: {bens_str}")

        locked_section = ""
        if locked_lines:
            locked_section = "\n\nINGREDIENTS TO KEEP FROM ORIGINAL (use these exactly):\n" + "\n".join(locked_lines)

        adapt_items = []
        if "hook" not in locked:
            adapt_items.append("hook")
        if "messaging_sequence" not in locked:
            adapt_items.append("messaging sequence")
        if "emotional_triggers" not in locked:
            adapt_items.append("emotional triggers")
        if "pain_points" not in locked:
            adapt_items.append("pain points")
        if "benefits" not in locked:
            adapt_items.append("benefits")

        adapt_section = ""
        if adapt_items:
            adapt_section = f"\n\nINGREDIENTS TO ADAPT for {brand_name or 'the brand'}: " + ", ".join(adapt_items)

        # Brand identification
        brand_line = ""
        if brand_name and product_name:
            brand_line = f"Brand: {brand_name}\nProduct name: {product_name}"
        elif brand_name:
            brand_line = f"Brand: {brand_name}"
        elif product_name:
            brand_line = f"Product name: {product_name}"

        # Creativity level instructions
        creativity_instructions = {
            1: (
                "CARBON COPY mode. Recreate this ad almost word-for-word, only swapping "
                "the competitor's product/brand for the user's product. Keep the same "
                "characters, setting, scenario, dialogue structure, and pacing. "
                "Change only product names, claims, and CTAs."
            ),
            2: (
                "FAITHFUL REMIX mode. Keep the same scene structure, setting, and character "
                "types. Dialogue should follow the same beats and rhythm but can be "
                "reworded naturally for the new product. Minor adjustments to make "
                "claims authentic to the brand are fine."
            ),
            3: (
                "BALANCED REMIX mode. Keep the same core concept and messaging arc, but "
                "feel free to change the specific scenario, characters, and dialogue. "
                "The ad should feel like it was inspired by the original but is clearly "
                "its own piece of creative."
            ),
            4: (
                "INSPIRED mode. Use the same underlying angle and emotional strategy, "
                "but create a fresh scenario with different characters, settings, and "
                "dialogue. The viewer should not be able to tell this was based on "
                "another ad."
            ),
            5: (
                "REIMAGINED mode. Extract only the core insight — the belief, pain point, "
                "or emotional trigger that makes the original ad effective — and build "
                "an entirely new ad around it. Different format, different story, "
                "different creative approach. Only the strategic DNA carries over."
            ),
        }
        creativity_text = creativity_instructions.get(creativity, creativity_instructions[3])

        prompt = f"""You are an expert ad copywriter and creative director.

COMPETITOR VIDEO STRUCTURE:
Transcript: {full_text[:2000]}
Hook: {hook_text}
Hook type: {hook_type}
Messaging sequence:
{messaging_text}
Emotional triggers: {triggers}
Awareness level: {awareness}
Ad format: {ad_format}
Pain points: {', '.join(pain_points) if pain_points else 'Not specified'}
Benefits: {', '.join(benefits) if benefits else 'Not specified'}{locked_section}{adapt_section}

YOUR BRAND:
{brand_line}
Product description: {product_description or 'Not specified'}
Target audience: {target_audience or 'Not specified'}
Brand guidelines: {brand_guidelines or 'Not specified'}
Additional context: {brand_context}

CREATIVITY LEVEL: {creativity}/5
{creativity_text}

TASK:
Create an ad script for **{brand_name or 'this brand'}**{f" promoting **{product_name}**" if product_name else ""} that uses the competitor video as a template. The script MUST explicitly mention and sell {product_name or brand_name or 'the product'} — do not write a generic script.

For locked ingredients, keep them as close to the original as possible while naturally incorporating {brand_name or 'the brand'}.
For adapted ingredients, reimagine them specifically for {brand_name or 'the brand'}'s product and audience.
Follow the CREATIVITY LEVEL instructions above to determine how closely to mirror the original.

Include:
1. Scene/stage breakdown
2. Dialogue/voiceover copy that names the product
3. Visual directions
4. Production notes (duration, required assets)

Output as JSON:
{{
  "script_text": "Full formatted script",
  "stages": [{{"stage": "hook|problem|solution|proof|cta", "content": "What happens", "dialogue": "Spoken words", "visuals": "Visual direction"}}],
  "estimated_duration": "0:30",
  "production_notes": "Notes on talent, location, props needed"
}}"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        if text.startswith("json"):
            text = text[4:]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"script_text": text, "stages": [], "estimated_duration": "unknown", "production_notes": ""}
