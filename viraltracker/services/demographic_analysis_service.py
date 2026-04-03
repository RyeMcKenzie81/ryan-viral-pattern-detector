"""
DemographicAnalysisService — Analyzes ad performance by demographic segments.

Aggregates data from meta_ads_demographic_performance (age/gender and placement
breakdowns) to surface insights like "25-34 Female converts at 2x average" or
"Instagram Stories outperforms Feed by 40%".

Integrates with CreativeCorrelationService for product-level filtering and
cross-analysis of creative elements × demographics.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Minimum impressions for a segment to be included in analysis
MIN_SEGMENT_IMPRESSIONS = 100

# Age range display order
AGE_RANGES = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]

# Gender display order
GENDERS = ["male", "female", "unknown"]


class DemographicAnalysisService:
    """Analyzes ad performance by demographic segments."""

    def __init__(self, supabase_client=None):
        if supabase_client:
            self.supabase = supabase_client
        else:
            from viraltracker.core.database import get_supabase_client
            self.supabase = get_supabase_client()

    def _get_format_ad_ids(self, brand_id: UUID, source_filter: str) -> Optional[set]:
        """Get ad IDs matching a format filter ('image' or 'video')."""
        if not source_filter:
            return None

        ad_ids = set()
        try:
            if source_filter != "video":
                result = self.supabase.table("ad_image_analysis").select(
                    "meta_ad_id"
                ).eq("brand_id", str(brand_id)).eq("status", "ok").execute()
                ad_ids.update(r["meta_ad_id"] for r in (result.data or []))
            if source_filter != "image":
                result = self.supabase.table("ad_video_analysis").select(
                    "meta_ad_id"
                ).eq("brand_id", str(brand_id)).eq("status", "ok").execute()
                ad_ids.update(r["meta_ad_id"] for r in (result.data or []))
        except Exception as e:
            logger.warning(f"Failed to load format ad IDs: {e}")
            return None

        return ad_ids if ad_ids else set()

    def get_demographic_performance(
        self,
        brand_id: UUID,
        breakdown_type: str,
        days_back: int = 60,
        product_id: str = None,
        source_filter: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate demographic performance across all ads for a brand.

        Args:
            brand_id: Brand UUID.
            breakdown_type: 'age_gender' or 'placement'.
            days_back: How far back to look.
            product_id: Optional product filter (uses URL-based matching).
            source_filter: Optional 'image' or 'video' format filter.

        Returns:
            List of segment dicts with aggregated metrics and vs_account_avg.
        """
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Get product-filtered ad IDs if needed
        product_ad_ids = None
        if product_id:
            from viraltracker.services.creative_correlation_service import CreativeCorrelationService
            corr_service = CreativeCorrelationService(supabase_client=self.supabase)
            product_ad_ids = corr_service.get_product_ad_ids(brand_id, product_id)
            if not product_ad_ids:
                return []

        # Get format-filtered ad IDs if needed
        format_ad_ids = self._get_format_ad_ids(brand_id, source_filter)
        if format_ad_ids is not None:
            if not format_ad_ids:
                return []
            if product_ad_ids is not None:
                product_ad_ids = product_ad_ids & format_ad_ids
            else:
                product_ad_ids = format_ad_ids

        # Load raw breakdown rows
        rows = self._load_breakdown_rows(brand_id, breakdown_type, cutoff, product_ad_ids)
        if not rows:
            return []

        # Group by segment
        segments: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = self._segment_key(row, breakdown_type)
            if key not in segments:
                segments[key] = {
                    "impressions": 0,
                    "spend": 0.0,
                    "link_clicks": 0,
                    "purchases": 0,
                    "purchase_value": 0.0,
                    "reach": 0,
                    "add_to_carts": 0,
                    "video_views": 0,
                    "ad_ids": set(),
                    "_ctr_weighted_sum": 0.0,
                    "_roas_weighted_sum": 0.0,
                }
                # Copy dimension columns
                if breakdown_type == "age_gender":
                    segments[key]["age_range"] = row.get("age_range", "")
                    segments[key]["gender"] = row.get("gender", "")
                else:
                    segments[key]["publisher_platform"] = row.get("publisher_platform", "")
                    segments[key]["platform_position"] = row.get("platform_position", "")

            seg = segments[key]
            imp = row.get("impressions") or 0
            seg["impressions"] += imp
            seg["spend"] += float(row.get("spend") or 0)
            seg["link_clicks"] += row.get("link_clicks") or 0
            seg["purchases"] += row.get("purchases") or 0
            seg["purchase_value"] += float(row.get("purchase_value") or 0)
            seg["reach"] += row.get("reach") or 0
            seg["add_to_carts"] += row.get("add_to_carts") or 0
            seg["video_views"] += row.get("video_views") or 0
            seg["ad_ids"].add(row.get("meta_ad_id"))

            ctr = float(row.get("link_ctr") or 0)
            roas = float(row.get("roas") or 0)
            seg["_ctr_weighted_sum"] += ctr * imp
            seg["_roas_weighted_sum"] += roas * imp

        # Compute averages per segment
        result = []
        total_impressions = sum(s["impressions"] for s in segments.values())
        total_ctr_weighted = sum(s["_ctr_weighted_sum"] for s in segments.values())
        total_roas_weighted = sum(s["_roas_weighted_sum"] for s in segments.values())

        account_avg_ctr = total_ctr_weighted / total_impressions if total_impressions > 0 else 0
        account_avg_roas = total_roas_weighted / total_impressions if total_impressions > 0 else 0

        for key, seg in segments.items():
            imp = seg["impressions"]
            if imp < MIN_SEGMENT_IMPRESSIONS:
                continue

            ctr = seg["_ctr_weighted_sum"] / imp if imp > 0 else 0
            roas = seg["_roas_weighted_sum"] / imp if imp > 0 else 0

            entry = {
                "segment_key": key,
                "impressions": imp,
                "spend": round(seg["spend"], 2),
                "link_clicks": seg["link_clicks"],
                "purchases": seg["purchases"],
                "purchase_value": round(seg["purchase_value"], 2),
                "reach": seg["reach"],
                "add_to_carts": seg["add_to_carts"],
                "video_views": seg["video_views"],
                "ad_count": len(seg["ad_ids"]),
                "ctr": round(ctr, 4),
                "roas": round(roas, 4),
                "vs_account_avg_ctr": round(ctr / account_avg_ctr, 2) if account_avg_ctr > 0 else 1.0,
                "vs_account_avg_roas": round(roas / account_avg_roas, 2) if account_avg_roas > 0 else 1.0,
            }

            if breakdown_type == "age_gender":
                entry["age_range"] = seg["age_range"]
                entry["gender"] = seg["gender"]
                entry["label"] = f"{seg['age_range']} {seg['gender'].title()}"
            else:
                entry["publisher_platform"] = seg["publisher_platform"]
                entry["platform_position"] = seg["platform_position"]
                plat = seg["publisher_platform"].replace("_", " ").title()
                pos = seg["platform_position"].replace("_", " ").title()
                entry["label"] = f"{plat} {pos}"

            result.append(entry)

        # Sort by impressions descending
        result.sort(key=lambda x: x["impressions"], reverse=True)
        return result

    def get_top_segments(
        self,
        brand_id: UUID,
        days_back: int = 60,
        metric: str = "roas",
        limit: int = 5,
        product_id: str = None,
        source_filter: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Get the top-performing demographic segments across all breakdown types.

        Args:
            brand_id: Brand UUID.
            days_back: How far back to look.
            metric: 'roas' or 'ctr' — which metric to rank by.
            limit: Max segments to return.
            product_id: Optional product filter.
            source_filter: Optional 'image' or 'video' format filter.

        Returns:
            List of top segments with labels and vs_account_avg.
        """
        all_segments = []

        for bt in ["age_gender", "placement"]:
            segments = self.get_demographic_performance(
                brand_id, bt, days_back, product_id, source_filter,
            )
            for seg in segments:
                vs_key = f"vs_account_avg_{metric}"
                all_segments.append({
                    "label": seg["label"],
                    "breakdown_type": bt,
                    "metric_value": seg.get(metric, 0),
                    "vs_avg": seg.get(vs_key, 1.0),
                    "spend": seg["spend"],
                    "impressions": seg["impressions"],
                    "ad_count": seg["ad_count"],
                    "purchases": seg["purchases"],
                })

        # Sort by vs_avg descending, filter to outperformers
        all_segments.sort(key=lambda x: x["vs_avg"], reverse=True)
        return [s for s in all_segments if s["vs_avg"] > 1.0][:limit]

    def get_creative_demographic_cross(
        self,
        brand_id: UUID,
        analysis_field: str,
        breakdown_type: str,
        days_back: int = 60,
        product_id: str = None,
        source_filter: str = None,
    ) -> Dict[str, Any]:
        """
        Cross-analyze creative elements with demographic segments.

        E.g., "How does fear-based tone perform with 25-34 females vs 45-54 males?"

        Args:
            brand_id: Brand UUID.
            analysis_field: Creative field (emotional_tone, hook_pattern, etc.).
            breakdown_type: 'age_gender' or 'placement'.
            days_back: How far back to look.
            product_id: Optional product filter.
            source_filter: Optional 'image' or 'video' format filter.

        Returns:
            Dict with 'rows' (field values), 'cols' (segments), 'z' (matrix),
            'text' (labels), and 'hover' (hover text).
        """
        from viraltracker.services.creative_correlation_service import CreativeCorrelationService

        corr_service = CreativeCorrelationService(supabase_client=self.supabase)
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Load creative analyses (filtered by format)
        image_analyses = {} if source_filter == "video" else corr_service._load_image_analyses(brand_id)
        video_analyses = {} if source_filter == "image" else corr_service._load_video_analyses(brand_id)

        # Merge all analyses keyed by meta_ad_id
        ad_field_values: Dict[str, str] = {}
        is_array = analysis_field in ("emotional_tone", "people_role", "video_emotional_drivers")

        for ad_id, analysis in {**image_analyses, **video_analyses}.items():
            val = self._extract_field_value(analysis, analysis_field)
            if val:
                if is_array and isinstance(val, list):
                    # For array fields, use first value for simplicity
                    for v in val:
                        # Store with suffix to allow multiple entries per ad
                        ad_field_values[ad_id] = str(v).lower()
                        break
                else:
                    ad_field_values[ad_id] = str(val).lower()

        if not ad_field_values:
            return {"rows": [], "cols": [], "z": [], "text": [], "hover": []}

        # Get product filter if needed
        product_ad_ids = None
        if product_id:
            product_ad_ids = corr_service.get_product_ad_ids(brand_id, product_id)

        # Load demographic rows for ads that have creative analysis
        target_ad_ids = set(ad_field_values.keys())
        if product_ad_ids:
            target_ad_ids = target_ad_ids & product_ad_ids

        rows = self._load_breakdown_rows(brand_id, breakdown_type, cutoff, target_ad_ids)
        if not rows:
            return {"rows": [], "cols": [], "z": [], "text": [], "hover": []}

        # Group by (field_value, segment)
        cross: Dict[str, Dict[str, Dict]] = {}  # field_value -> segment -> metrics
        for row in rows:
            ad_id = row.get("meta_ad_id")
            field_val = ad_field_values.get(ad_id)
            if not field_val:
                continue

            seg_key = self._segment_key(row, breakdown_type)
            imp = row.get("impressions") or 0
            if imp == 0:
                continue

            if field_val not in cross:
                cross[field_val] = {}
            if seg_key not in cross[field_val]:
                cross[field_val][seg_key] = {
                    "impressions": 0,
                    "_ctr_weighted": 0.0,
                    "_roas_weighted": 0.0,
                    "ad_count": 0,
                }

            cell = cross[field_val][seg_key]
            cell["impressions"] += imp
            cell["_ctr_weighted"] += float(row.get("link_ctr") or 0) * imp
            cell["_roas_weighted"] += float(row.get("roas") or 0) * imp
            cell["ad_count"] += 1

        if not cross:
            return {"rows": [], "cols": [], "z": [], "text": [], "hover": []}

        # Compute account average across all cells
        total_imp = sum(
            c["impressions"]
            for fv in cross.values()
            for c in fv.values()
        )
        total_roas_w = sum(
            c["_roas_weighted"]
            for fv in cross.values()
            for c in fv.values()
        )
        account_avg_roas = total_roas_w / total_imp if total_imp > 0 else 1.0

        # Collect unique segments and field values
        all_segments = sorted(set(
            sk for fv in cross.values() for sk in fv.keys()
        ))
        all_field_values = sorted(cross.keys())

        # Build matrices
        z_matrix = []
        text_matrix = []
        hover_matrix = []

        for fv in all_field_values:
            z_row = []
            text_row = []
            hover_row = []
            for seg in all_segments:
                cell = cross.get(fv, {}).get(seg)
                if cell and cell["impressions"] >= 50:
                    roas = cell["_roas_weighted"] / cell["impressions"]
                    vs_avg = round(roas / account_avg_roas, 2) if account_avg_roas > 0 else 1.0
                    z_row.append(vs_avg)
                    text_row.append(f"{vs_avg:.1f}x\n({cell['ad_count']})")
                    hover_row.append(
                        f"{fv.replace('_', ' ').title()} × {seg}<br>"
                        f"ROAS: {roas:.2f}x<br>"
                        f"vs Avg: {vs_avg:.1f}x<br>"
                        f"{cell['ad_count']} ads, {cell['impressions']:,} imp"
                    )
                else:
                    z_row.append(None)
                    text_row.append("")
                    hover_row.append("")
            z_matrix.append(z_row)
            text_matrix.append(text_row)
            hover_matrix.append(hover_row)

        return {
            "rows": [fv.replace("_", " ").title() for fv in all_field_values],
            "cols": all_segments,
            "z": z_matrix,
            "text": text_matrix,
            "hover": hover_matrix,
        }

    # ---- Private helpers ----

    def _load_breakdown_rows(
        self,
        brand_id: UUID,
        breakdown_type: str,
        cutoff: str,
        meta_ad_ids: set = None,
    ) -> List[Dict]:
        """Load raw breakdown rows from meta_ads_demographic_performance."""
        try:
            if meta_ad_ids is not None and not meta_ad_ids:
                return []

            if meta_ad_ids and len(meta_ad_ids) <= 50:
                # Direct filter for small sets
                result = self.supabase.table("meta_ads_demographic_performance").select(
                    "*"
                ).eq(
                    "brand_id", str(brand_id)
                ).eq(
                    "breakdown_type", breakdown_type
                ).gte(
                    "date", cutoff
                ).in_(
                    "meta_ad_id", list(meta_ad_ids)
                ).execute()
                return result.data or []

            # Load all rows for brand + type, then filter client-side if needed
            all_rows = []
            offset = 0
            while True:
                result = self.supabase.table("meta_ads_demographic_performance").select(
                    "*"
                ).eq(
                    "brand_id", str(brand_id)
                ).eq(
                    "breakdown_type", breakdown_type
                ).gte(
                    "date", cutoff
                ).limit(1000).offset(offset).execute()

                rows = result.data or []
                all_rows.extend(rows)
                if len(rows) < 1000:
                    break
                offset += 1000

            if meta_ad_ids:
                all_rows = [r for r in all_rows if r.get("meta_ad_id") in meta_ad_ids]

            return all_rows

        except Exception as e:
            logger.error(f"Failed to load {breakdown_type} breakdown rows: {e}")
            return []

    def _segment_key(self, row: Dict, breakdown_type: str) -> str:
        """Build a human-readable segment key from a breakdown row."""
        if breakdown_type == "age_gender":
            return f"{row.get('age_range', '')}|{row.get('gender', '')}"
        else:
            return f"{row.get('publisher_platform', '')}|{row.get('platform_position', '')}"

    def _extract_field_value(self, analysis: Dict, field: str) -> Any:
        """Extract a creative analysis field value, handling nested fields."""
        # Direct fields
        if field in analysis and analysis[field] is not None:
            return analysis[field]

        # Nested visual_style fields
        if field.startswith("visual_"):
            sub_field = field.replace("visual_", "")
            vs = analysis.get("visual_style")
            if isinstance(vs, dict):
                return vs.get(sub_field)

        # People role extraction
        if field == "people_role":
            people = analysis.get("people_in_ad")
            if isinstance(people, list):
                return [p.get("role") for p in people if isinstance(p, dict) and p.get("role")]

        # Video emotional drivers
        if field == "video_emotional_drivers":
            return analysis.get("emotional_drivers")

        return None
