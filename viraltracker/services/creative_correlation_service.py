"""
CreativeCorrelationService — Correlates creative analysis with ad performance.

Joins ad_image_analysis and ad_video_analysis with meta_ads_performance to
identify which messaging themes, emotional tones, hook patterns, persona types,
and visual styles correlate with strong performance.

Results stored in creative_performance_correlations for use by AccountLeverageService.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Minimum sample size for a correlation to be considered meaningful
MIN_SAMPLE_SIZE = 3

# Analysis fields to correlate — (field_name, is_array, source_tables)
CORRELATION_FIELDS = [
    # From ad_image_analysis
    ("emotional_tone", True, ["ad_image_analysis"]),
    ("hook_pattern", False, ["ad_image_analysis"]),
    ("cta_style", False, ["ad_image_analysis"]),
    ("messaging_theme", False, ["ad_image_analysis"]),
    ("awareness_level", False, ["ad_image_analysis"]),

    # People in ad — extract role field
    ("people_role", True, ["ad_image_analysis"]),

    # Visual style — extract sub-fields
    ("visual_color_mood", False, ["ad_image_analysis"]),
    ("visual_imagery_type", False, ["ad_image_analysis"]),
    ("visual_production_quality", False, ["ad_image_analysis"]),

    # From ad_video_analysis
    ("hook_type", False, ["ad_video_analysis"]),
    ("format_type", False, ["ad_video_analysis"]),
    ("production_quality", False, ["ad_video_analysis"]),
    ("video_emotional_drivers", True, ["ad_video_analysis"]),
]


class CreativeCorrelationService:
    """Correlates creative analysis fields with ad performance."""

    def __init__(self, supabase_client=None):
        if supabase_client:
            self.supabase = supabase_client
        else:
            from viraltracker.core.database import get_supabase_client
            self.supabase = get_supabase_client()

    def compute_correlations(
        self,
        brand_id: UUID,
        organization_id: UUID,
        days_back: int = 60,
    ) -> Dict[str, Any]:
        """Compute performance correlations for all analysis fields.

        Joins analysis tables with meta_ads_performance, groups by each
        analysis field value, and computes relative performance vs account avg.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            days_back: Performance look-back window.

        Returns:
            Summary dict with correlation counts.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Load image and video analyses first so we know which meta_ad_ids to load perf for
        image_analyses = self._load_image_analyses(brand_id)
        video_analyses = self._load_video_analyses(brand_id)

        # Collect all meta_ad_ids we need performance data for
        analysis_ids = set(image_analyses.keys()) | set(video_analyses.keys())
        logger.info(
            f"Loaded {len(image_analyses)} image analyses + {len(video_analyses)} video analyses "
            f"= {len(analysis_ids)} unique meta_ad_ids"
        )

        if not analysis_ids:
            return {"correlations": 0, "message": "No analyses found"}

        # Load performance data only for ads we have analyses for
        perf_data = self._load_performance(brand_id, cutoff, meta_ad_ids=analysis_ids)
        if not perf_data:
            return {"correlations": 0, "message": "No performance data found for analyzed ads"}

        logger.info(
            f"Performance data: {len(perf_data)} ads with 100+ impressions "
            f"(out of {len(analysis_ids)} analyzed)"
        )

        # Compute account averages
        account_avg = self._compute_averages(list(perf_data.values()))
        if not account_avg:
            return {"correlations": 0, "message": "No performance data for account average"}
        if account_avg.get("mean_ctr", 0) == 0 and account_avg.get("mean_roas", 0) == 0:
            return {"correlations": 0, "message": "No CTR or ROAS data for account average"}

        logger.info(
            f"Account averages: CTR={account_avg.get('mean_ctr', 0):.4f}, "
            f"ROAS={account_avg.get('mean_roas', 0):.2f}"
        )

        total_correlations = 0

        # Process image analysis fields
        if image_analyses:
            total_correlations += self._correlate_image_fields(
                brand_id, organization_id, image_analyses, perf_data, account_avg
            )

        # Process video analysis fields
        if video_analyses:
            total_correlations += self._correlate_video_fields(
                brand_id, organization_id, video_analyses, perf_data, account_avg
            )

        logger.info(
            f"Computed {total_correlations} correlations for brand {brand_id} "
            f"({len(image_analyses)} images, {len(video_analyses)} videos)"
        )
        return {
            "correlations": total_correlations,
            "image_ads_analyzed": len(image_analyses),
            "video_ads_analyzed": len(video_analyses),
        }

    def get_hook_performance(
        self,
        brand_id: UUID,
        days_back: int = 60,
        min_impressions: int = 100,
    ) -> List[Dict]:
        """Get individual hooks ranked by CTR (thumb-stop rate).

        Joins ad_image_analysis.headline_text and ad_video_analysis.hook_transcript_spoken
        with meta_ads_performance to rank hooks by CTR.

        Args:
            brand_id: Brand UUID.
            days_back: Performance look-back window.
            min_impressions: Minimum impressions for a hook to qualify.

        Returns:
            List of hook dicts sorted by CTR descending.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        hooks = []
        image_rows = []
        video_rows = []

        # Load all analyses first to collect meta_ad_ids
        try:
            image_results = self.supabase.table("ad_image_analysis").select(
                "meta_ad_id, headline_text, hook_pattern, messaging_theme, "
                "emotional_tone, visual_style, awareness_level"
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "status", "ok"
            ).execute()
            image_rows = image_results.data or []
        except Exception as e:
            logger.error(f"Failed to load image hooks: {e}")

        try:
            video_results = self.supabase.table("ad_video_analysis").select(
                "meta_ad_id, hook_transcript_spoken, hook_transcript_overlay, "
                "hook_type, awareness_level, emotional_drivers"
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "status", "ok"
            ).execute()
            video_rows = video_results.data or []
        except Exception as e:
            logger.error(f"Failed to load video hooks: {e}")

        # Collect all meta_ad_ids and load perf in batches
        all_ids = {r["meta_ad_id"] for r in image_rows} | {r["meta_ad_id"] for r in video_rows}
        if not all_ids:
            return []

        perf = self._load_performance(brand_id, cutoff, meta_ad_ids=all_ids)
        if not perf:
            return []

        # Build hook list from image analyses
        for row in image_rows:
            hook_text = row.get("headline_text") or row.get("messaging_theme")
            if not hook_text:
                continue
            mid = row["meta_ad_id"]
            p = perf.get(mid)
            if not p or p["impressions"] < min_impressions:
                continue
            hooks.append({
                "hook_text": hook_text,
                "hook_type": row.get("hook_pattern", "unknown"),
                "source": "image",
                "meta_ad_id": mid,
                "ctr": p["mean_ctr"],
                "impressions": p["impressions"],
                "roas": p.get("mean_roas", 0),
                "messaging_theme": row.get("messaging_theme"),
                "emotional_tone": row.get("emotional_tone", []),
                "awareness_level": row.get("awareness_level"),
            })

        # Build hook list from video analyses
        for row in video_rows:
            hook_text = row.get("hook_transcript_spoken") or row.get("hook_transcript_overlay")
            if not hook_text:
                continue
            mid = row["meta_ad_id"]
            p = perf.get(mid)
            if not p or p["impressions"] < min_impressions:
                continue
            hooks.append({
                "hook_text": hook_text,
                "hook_type": row.get("hook_type", "unknown"),
                "source": "video",
                "meta_ad_id": mid,
                "ctr": p["mean_ctr"],
                "impressions": p["impressions"],
                "roas": p.get("mean_roas", 0),
                "messaging_theme": None,
                "emotional_tone": row.get("emotional_drivers", []),
                "awareness_level": row.get("awareness_level"),
            })

        # Sort by CTR descending
        hooks.sort(key=lambda x: x["ctr"], reverse=True)
        return hooks

    def get_top_correlations(
        self,
        brand_id: UUID,
        min_confidence: float = 0.3,
        limit: int = 20,
    ) -> List[Dict]:
        """Get top correlations sorted by relative performance.

        Args:
            brand_id: Brand UUID.
            min_confidence: Minimum confidence threshold.
            limit: Max results.

        Returns:
            List of correlation dicts.
        """
        try:
            result = self.supabase.table("creative_performance_correlations").select(
                "analysis_field, field_value, source_table, ad_count, "
                "mean_reward, mean_ctr, mean_roas, mean_cpa, "
                "vs_account_avg, confidence"
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "confidence", min_confidence
            ).order(
                "vs_account_avg", desc=True
            ).limit(limit).execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get correlations for brand {brand_id}: {e}")
            return []

    def _load_performance(
        self,
        brand_id: UUID,
        cutoff: str,
        meta_ad_ids: set = None,
    ) -> Dict[str, Dict]:
        """Load aggregated performance per meta_ad_id.

        Args:
            brand_id: Brand UUID.
            cutoff: Date cutoff string.
            meta_ad_ids: Optional set of meta_ad_ids to load. If provided,
                loads only these IDs (in batches) to avoid Supabase row limits.

        Returns:
            Dict of meta_ad_id -> {mean_ctr, mean_roas, impressions, total_spend}.
        """
        try:
            all_rows = []

            if meta_ad_ids:
                # Query in batches of 50 to avoid URL length limits
                id_list = list(meta_ad_ids)
                for i in range(0, len(id_list), 50):
                    batch = id_list[i:i + 50]
                    result = self.supabase.table("meta_ads_performance").select(
                        "meta_ad_id, impressions, link_ctr, roas, cpa, spend"
                    ).eq(
                        "brand_id", str(brand_id)
                    ).gte(
                        "date", cutoff
                    ).in_(
                        "meta_ad_id", batch
                    ).limit(5000).execute()
                    all_rows.extend(result.data or [])
            else:
                # Paginate to avoid 1000-row default limit
                offset = 0
                page_size = 1000
                while True:
                    result = self.supabase.table("meta_ads_performance").select(
                        "meta_ad_id, impressions, link_ctr, roas, cpa, spend"
                    ).eq(
                        "brand_id", str(brand_id)
                    ).gte(
                        "date", cutoff
                    ).limit(page_size).offset(offset).execute()
                    rows = result.data or []
                    all_rows.extend(rows)
                    if len(rows) < page_size:
                        break
                    offset += page_size

            if not all_rows:
                logger.warning(f"No performance rows found for brand {brand_id}")
                return {}

            logger.info(f"Loaded {len(all_rows)} performance rows for {len(meta_ad_ids or [])} requested ads")

            # Aggregate by meta_ad_id
            agg: Dict[str, Dict] = {}
            for row in all_rows:
                mid = row["meta_ad_id"]
                if mid not in agg:
                    agg[mid] = {
                        "impressions": 0,
                        "weighted_ctr": 0.0,
                        "weighted_roas": 0.0,
                        "total_spend": 0.0,
                    }
                imp = row.get("impressions") or 0
                agg[mid]["impressions"] += imp
                if row.get("link_ctr") is not None:
                    agg[mid]["weighted_ctr"] += (row["link_ctr"] or 0) * imp
                if row.get("roas") is not None:
                    agg[mid]["weighted_roas"] += (row["roas"] or 0) * imp
                agg[mid]["total_spend"] += row.get("spend") or 0

            # Compute averages
            perf = {}
            for mid, data in agg.items():
                imp = data["impressions"]
                if imp < 100:  # Skip low-impression ads
                    continue
                perf[mid] = {
                    "impressions": imp,
                    "mean_ctr": data["weighted_ctr"] / imp if imp > 0 else 0,
                    "mean_roas": data["weighted_roas"] / imp if imp > 0 else 0,
                    "total_spend": data["total_spend"],
                }

            logger.info(
                f"Aggregated: {len(agg)} unique ads, {len(perf)} with 100+ impressions"
            )

            # Try to join with creative_element_rewards for reward scores
            if perf:
                mappings = self.supabase.table("meta_ad_mapping").select(
                    "meta_ad_id, generated_ad_id"
                ).in_(
                    "meta_ad_id", list(perf.keys())
                ).execute()

                if mappings.data:
                    gen_ids = [m["generated_ad_id"] for m in mappings.data]
                    gen_to_meta = {m["generated_ad_id"]: m["meta_ad_id"] for m in mappings.data}

                    rewards = self.supabase.table("creative_element_rewards").select(
                        "generated_ad_id, reward_score"
                    ).in_(
                        "generated_ad_id", gen_ids
                    ).execute()

                    for r in (rewards.data or []):
                        mid = gen_to_meta.get(r["generated_ad_id"])
                        if mid and mid in perf:
                            perf[mid]["mean_reward"] = r["reward_score"]

            return perf

        except Exception as e:
            logger.error(f"Failed to load performance for brand {brand_id}: {e}")
            return {}

    def _load_image_analyses(self, brand_id: UUID) -> Dict[str, Dict]:
        """Load image analyses keyed by meta_ad_id."""
        try:
            result = self.supabase.table("ad_image_analysis").select(
                "meta_ad_id, messaging_theme, emotional_tone, hook_pattern, "
                "cta_style, people_in_ad, visual_style, awareness_level"
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "status", "ok"
            ).execute()

            analyses = {}
            for row in (result.data or []):
                analyses[row["meta_ad_id"]] = row
            return analyses

        except Exception as e:
            logger.error(f"Failed to load image analyses: {e}")
            return {}

    def _load_video_analyses(self, brand_id: UUID) -> Dict[str, Dict]:
        """Load video analyses keyed by meta_ad_id."""
        try:
            result = self.supabase.table("ad_video_analysis").select(
                "meta_ad_id, hook_type, format_type, production_quality, "
                "emotional_drivers, people_in_ad, awareness_level"
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "status", "ok"
            ).execute()

            analyses = {}
            for row in (result.data or []):
                analyses[row["meta_ad_id"]] = row
            return analyses

        except Exception as e:
            logger.error(f"Failed to load video analyses: {e}")
            return {}

    def _correlate_image_fields(
        self,
        brand_id: UUID,
        organization_id: UUID,
        analyses: Dict[str, Dict],
        perf_data: Dict[str, Dict],
        account_avg: Dict,
    ) -> int:
        """Correlate image analysis fields with performance."""
        correlations = 0

        # Simple string fields
        for field_name in ["hook_pattern", "cta_style", "messaging_theme", "awareness_level"]:
            groups = self._group_by_field(analyses, perf_data, field_name, is_array=False)
            correlations += self._upsert_correlations(
                brand_id, organization_id, field_name, groups,
                account_avg, "ad_image_analysis"
            )

        # Array fields
        for field_name in ["emotional_tone"]:
            groups = self._group_by_field(analyses, perf_data, field_name, is_array=True)
            correlations += self._upsert_correlations(
                brand_id, organization_id, field_name, groups,
                account_avg, "ad_image_analysis"
            )

        # People roles (extract from JSONB array)
        role_groups = self._group_by_people_role(analyses, perf_data)
        correlations += self._upsert_correlations(
            brand_id, organization_id, "people_role", role_groups,
            account_avg, "ad_image_analysis"
        )

        # Visual style sub-fields
        for sub_field, full_name in [
            ("color_mood", "visual_color_mood"),
            ("imagery_type", "visual_imagery_type"),
            ("production_quality", "visual_production_quality"),
        ]:
            groups = self._group_by_nested_field(
                analyses, perf_data, "visual_style", sub_field
            )
            correlations += self._upsert_correlations(
                brand_id, organization_id, full_name, groups,
                account_avg, "ad_image_analysis"
            )

        return correlations

    def _correlate_video_fields(
        self,
        brand_id: UUID,
        organization_id: UUID,
        analyses: Dict[str, Dict],
        perf_data: Dict[str, Dict],
        account_avg: Dict,
    ) -> int:
        """Correlate video analysis fields with performance."""
        correlations = 0

        for field_name in ["hook_type", "format_type", "production_quality", "awareness_level"]:
            groups = self._group_by_field(analyses, perf_data, field_name, is_array=False)
            correlations += self._upsert_correlations(
                brand_id, organization_id, field_name, groups,
                account_avg, "ad_video_analysis"
            )

        # Emotional drivers (array)
        groups = self._group_by_field(
            analyses, perf_data, "emotional_drivers", is_array=True
        )
        correlations += self._upsert_correlations(
            brand_id, organization_id, "video_emotional_drivers", groups,
            account_avg, "ad_video_analysis"
        )

        # People roles from video
        role_groups = self._group_by_people_role(analyses, perf_data)
        correlations += self._upsert_correlations(
            brand_id, organization_id, "video_people_role", role_groups,
            account_avg, "ad_video_analysis"
        )

        return correlations

    def _group_by_field(
        self,
        analyses: Dict[str, Dict],
        perf_data: Dict[str, Dict],
        field_name: str,
        is_array: bool,
    ) -> Dict[str, List[Dict]]:
        """Group ads by a field value, attaching performance data.

        Returns dict of field_value -> [{meta_ad_id, perf_data}].
        """
        groups: Dict[str, List[Dict]] = {}

        for meta_ad_id, analysis in analyses.items():
            perf = perf_data.get(meta_ad_id)
            if not perf:
                continue

            values = analysis.get(field_name)
            if values is None:
                continue

            if is_array:
                if not isinstance(values, list):
                    continue
                for val in values:
                    if val and isinstance(val, str):
                        groups.setdefault(val, []).append({
                            "meta_ad_id": meta_ad_id, **perf
                        })
            else:
                if isinstance(values, str) and values:
                    groups.setdefault(values, []).append({
                        "meta_ad_id": meta_ad_id, **perf
                    })

        return groups

    def _group_by_people_role(
        self,
        analyses: Dict[str, Dict],
        perf_data: Dict[str, Dict],
    ) -> Dict[str, List[Dict]]:
        """Group ads by people_in_ad role field."""
        groups: Dict[str, List[Dict]] = {}

        for meta_ad_id, analysis in analyses.items():
            perf = perf_data.get(meta_ad_id)
            if not perf:
                continue

            people = analysis.get("people_in_ad") or []
            if not isinstance(people, list):
                continue

            # Also track "no_people" as a category
            if not people:
                groups.setdefault("no_people", []).append({
                    "meta_ad_id": meta_ad_id, **perf
                })
                continue

            roles_seen = set()
            for person in people:
                if isinstance(person, dict):
                    role = person.get("role", "unknown")
                    if role and role not in roles_seen:
                        roles_seen.add(role)
                        groups.setdefault(role, []).append({
                            "meta_ad_id": meta_ad_id, **perf
                        })

        return groups

    def _group_by_nested_field(
        self,
        analyses: Dict[str, Dict],
        perf_data: Dict[str, Dict],
        parent_field: str,
        sub_field: str,
    ) -> Dict[str, List[Dict]]:
        """Group ads by a nested JSONB sub-field."""
        groups: Dict[str, List[Dict]] = {}

        for meta_ad_id, analysis in analyses.items():
            perf = perf_data.get(meta_ad_id)
            if not perf:
                continue

            parent = analysis.get(parent_field)
            if not isinstance(parent, dict):
                continue

            val = parent.get(sub_field)
            if val and isinstance(val, str):
                groups.setdefault(val, []).append({
                    "meta_ad_id": meta_ad_id, **perf
                })

        return groups

    def _compute_averages(self, perf_list: List[Dict]) -> Dict:
        """Compute weighted averages across all ads."""
        if not perf_list:
            return {}

        total_imp = sum(p.get("impressions", 0) for p in perf_list)
        if total_imp == 0:
            return {}

        avg = {
            "mean_ctr": sum(
                p.get("mean_ctr", 0) * p.get("impressions", 0) for p in perf_list
            ) / total_imp,
            "mean_roas": sum(
                p.get("mean_roas", 0) * p.get("impressions", 0) for p in perf_list
            ) / total_imp,
        }

        # Mean reward (simple average, not impression-weighted)
        rewards = [p["mean_reward"] for p in perf_list if "mean_reward" in p]
        avg["mean_reward"] = sum(rewards) / len(rewards) if rewards else 0

        return avg

    def _upsert_correlations(
        self,
        brand_id: UUID,
        organization_id: UUID,
        field_name: str,
        groups: Dict[str, List[Dict]],
        account_avg: Dict,
        source_table: str,
    ) -> int:
        """Upsert correlation rows for each field value group."""
        count = 0
        now = datetime.now(timezone.utc).isoformat()

        for field_value, ads in groups.items():
            if len(ads) < MIN_SAMPLE_SIZE:
                continue

            total_imp = sum(a.get("impressions", 0) for a in ads)
            if total_imp == 0:
                continue

            # Weighted averages
            mean_ctr = sum(
                a.get("mean_ctr", 0) * a.get("impressions", 0) for a in ads
            ) / total_imp
            mean_roas = sum(
                a.get("mean_roas", 0) * a.get("impressions", 0) for a in ads
            ) / total_imp

            # Mean reward (simple avg)
            rewards = [a["mean_reward"] for a in ads if "mean_reward" in a]
            mean_reward = sum(rewards) / len(rewards) if rewards else None

            # Relative performance (use ROAS as primary metric, fall back to CTR)
            acct_roas = account_avg.get("mean_roas", 0)
            if acct_roas and acct_roas > 0:
                vs_avg = mean_roas / acct_roas
            else:
                acct_ctr = account_avg.get("mean_ctr", 0)
                vs_avg = mean_ctr / acct_ctr if acct_ctr > 0 else 1.0

            # Confidence based on sample size (sigmoid: 3→0.3, 10→0.7, 30→0.95)
            import math
            confidence = 1 / (1 + math.exp(-0.3 * (len(ads) - 5)))

            meta_ad_ids = [a["meta_ad_id"] for a in ads]

            try:
                self.supabase.table("creative_performance_correlations").upsert({
                    "brand_id": str(brand_id),
                    "organization_id": str(organization_id),
                    "analysis_field": field_name,
                    "field_value": field_value,
                    "source_table": source_table,
                    "ad_count": len(ads),
                    "meta_ad_ids": meta_ad_ids,
                    "mean_reward": mean_reward,
                    "mean_ctr": mean_ctr,
                    "mean_roas": mean_roas,
                    "mean_cpa": None,  # Computed later if CPA data available
                    "vs_account_avg": round(vs_avg, 2),
                    "confidence": round(confidence, 2),
                    "computed_at": now,
                }, on_conflict="brand_id,analysis_field,field_value,source_table").execute()
                count += 1
            except Exception as e:
                logger.error(
                    f"Failed to upsert correlation {field_name}={field_value}: {e}"
                )

        return count
