"""
TemplateQueueService - Template approval queue management.

This service handles:
- Adding scraped assets to review queue
- AI pre-analysis for reviewer assistance
- Approval/rejection workflow with AI-assisted metadata
- Template library management

Part of the Brand Research Pipeline (Phase 2B: Template Queue).
"""

import logging
import base64
import json
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


# =============================================================================
# AI Analysis Prompt for Template Approval
# =============================================================================

TEMPLATE_ANALYSIS_PROMPT = """Analyze this Facebook ad image and extract metadata for a template library.

Context: This is a scraped Facebook ad being categorized for reuse as a creative template.

Brand Info:
- Page Name: {page_name}
- Landing Page: {link_url}

Analyze the visual content and return a JSON response with the following structure:

{{
  "suggested_name": "Short descriptive name for this template (3-6 words, e.g., 'Dog Owner Testimonial Card')",
  "suggested_description": "1-2 sentence description of the template style, layout, and ideal use case",
  "format_type": "Choose ONE: testimonial | quote_card | before_after | product_showcase | ugc_style | meme | carousel_frame | story_format | other",
  "industry_niche": "Choose ONE: supplements | pets | skincare | fitness | fashion | tech | food_beverage | home_garden | finance | health_wellness | beauty | automotive | travel | education | other",
  "target_sex": "Choose ONE: male | female | unisex",
  "awareness_level": <integer 1-5>,
  "awareness_level_reasoning": "Brief explanation of why this awareness level (1=Unaware, 2=Problem Aware, 3=Solution Aware, 4=Product Aware, 5=Most Aware)",
  "sales_event": null or "Choose if applicable: black_friday | cyber_monday | mothers_day | fathers_day | valentines_day | christmas | new_year | summer_sale | labor_day | memorial_day | other",
  "visual_notes": "Notable visual elements: colors, layout style, text placement, imagery type"
}}

AWARENESS LEVEL GUIDE:
- Level 1 (Unaware): Educational content, story-driven, no direct product mention, pattern interrupts
- Level 2 (Problem Aware): Focuses on the problem/pain point, agitates the issue, introduces concept that solutions exist
- Level 3 (Solution Aware): Uses category nicknames ("Brain Fog Killer") not brand names, listicle hooks ("11 Reasons..."), shows results to differentiate the solution TYPE, explains unique mechanism. Before/after photos used to showcase the solution category, not a specific known product.
- Level 4 (Product Aware): Mentions specific brand/product BY NAME, named customer testimonials for a KNOWN product, addresses objections about a product the reader has already heard of, retargeting-style ads
- Level 5 (Most Aware): Direct offer, promotional, discount/sale focused, minimal persuasion, assumes reader is ready to buy

KEY DISTINCTION: Before/after photos showing transformation WITHOUT naming the specific product = Level 3 (differentiating a solution type). Before/after WITH product name and "I used [Brand X]" = Level 4 (building trust for known product).

Return ONLY valid JSON, no additional text."""


class TemplateQueueService:
    """Service for template queue management."""

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize TemplateQueueService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("TemplateQueueService initialized")

    async def add_to_queue(
        self,
        asset_ids: List[UUID],
        run_ai_analysis: bool = True
    ) -> int:
        """
        Add assets to template review queue.

        Args:
            asset_ids: List of scraped_ad_assets UUIDs
            run_ai_analysis: Whether to run AI pre-analysis

        Returns:
            Number of items added to queue
        """
        count = 0
        for asset_id in asset_ids:
            try:
                # Get asset info
                asset_result = self.supabase.table("scraped_ad_assets").select(
                    "id, facebook_ad_id, storage_path, asset_type"
                ).eq("id", str(asset_id)).execute()

                if not asset_result.data:
                    logger.warning(f"Asset not found: {asset_id}")
                    continue

                asset_data = asset_result.data[0]

                # Check if already in queue
                existing = self.supabase.table("template_queue").select(
                    "id"
                ).eq("asset_id", str(asset_id)).execute()

                if existing.data:
                    logger.debug(f"Asset already in queue: {asset_id}")
                    continue

                # Create queue item
                queue_item = {
                    "asset_id": str(asset_id),
                    "facebook_ad_id": asset_data.get("facebook_ad_id"),
                    "status": "pending"
                }

                # Run AI pre-analysis if requested
                if run_ai_analysis:
                    try:
                        ai_analysis = await self._run_pre_analysis(
                            asset_data["storage_path"],
                            asset_data.get("asset_type", "image")
                        )
                        queue_item["ai_analysis"] = ai_analysis
                        queue_item["ai_quality_score"] = ai_analysis.get("quality_score")
                        queue_item["ai_suggested_category"] = ai_analysis.get("suggested_category")
                    except Exception as e:
                        logger.warning(f"AI pre-analysis failed for {asset_id}: {e}")

                self.supabase.table("template_queue").insert(queue_item).execute()
                count += 1

            except Exception as e:
                logger.error(f"Failed to add asset {asset_id} to queue: {e}")
                continue

        logger.info(f"Added {count} items to template queue")
        return count

    async def _run_pre_analysis(
        self,
        storage_path: str,
        asset_type: str = "image"
    ) -> Dict:
        """
        Run quick AI analysis for reviewer assistance.

        Uses Gemini Flash for fast, cheap pre-analysis to help
        reviewers categorize and assess templates.

        Args:
            storage_path: Supabase storage path
            asset_type: 'image' or 'video'

        Returns:
            Analysis dict with layout_type, suggested_category, quality_score
        """
        # For now, return placeholder - can implement Gemini Flash later
        # This keeps the service functional without API costs
        return {
            "layout_type": "unknown",
            "suggested_category": "other",
            "quality_score": 5.0,
            "style_notes": "",
            "analyzed": False
        }

    def get_pending_queue(
        self,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get pending items for review.

        Args:
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            List of queue items with asset details
        """
        result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(id, storage_path, asset_type, mime_type, file_size_bytes)"
        ).eq("status", "pending").order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        return result.data

    def get_queue_by_status(
        self,
        status: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get queue items by status.

        Args:
            status: pending, approved, rejected, archived
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            List of queue items
        """
        result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(id, storage_path, asset_type)"
        ).eq("status", status).order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        return result.data

    def get_queue_stats(self) -> Dict:
        """
        Get queue statistics using count queries (not limited by Supabase 1000 row default).

        Returns:
            Dict with counts by status
        """
        stats = {"pending": 0, "approved": 0, "rejected": 0, "archived": 0, "pending_details": 0, "total": 0}

        # Query count for each status separately to avoid Supabase 1000 row limit
        for status in ["pending", "approved", "rejected", "archived", "pending_details"]:
            result = self.supabase.table("template_queue").select(
                "id", count="exact"
            ).eq("status", status).execute()
            count = result.count if result.count is not None else 0
            stats[status] = count
            stats["total"] += count

        return stats

    def approve_template(
        self,
        queue_id: UUID,
        category: str,
        name: str,
        description: Optional[str] = None,
        reviewed_by: str = "system"
    ) -> Dict:
        """
        Approve queue item and create template.

        Args:
            queue_id: UUID of the template_queue record
            category: Template category (testimonial, quote_card, etc.)
            name: Template name
            description: Optional description
            reviewed_by: Who approved it

        Returns:
            Created template record
        """
        # Get queue item with asset
        queue_result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, facebook_ad_id, asset_type)"
        ).eq("id", str(queue_id)).execute()

        if not queue_result.data:
            raise ValueError(f"Queue item not found: {queue_id}")

        queue_item = queue_result.data[0]
        asset = queue_item.get("scraped_ad_assets", {})

        # Update queue status
        self.supabase.table("template_queue").update({
            "status": "approved",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat(),
            "template_category": category,
            "template_name": name
        }).eq("id", str(queue_id)).execute()

        # Create template in scraped_templates table
        template = {
            "source_asset_id": queue_item["asset_id"],
            "source_facebook_ad_id": queue_item.get("facebook_ad_id"),
            "source_queue_id": str(queue_id),
            "name": name,
            "description": description,
            "category": category,
            "storage_path": asset.get("storage_path", ""),
            "layout_analysis": queue_item.get("ai_analysis", {}),
            "is_active": True
        }

        result = self.supabase.table("scraped_templates").insert(template).execute()

        if result.data:
            logger.info(f"Created template: {name} ({category})")
            return result.data[0]

        raise Exception("Failed to create template")

    def reject_template(
        self,
        queue_id: UUID,
        reason: str,
        reviewed_by: str = "system"
    ) -> None:
        """
        Reject queue item with reason.

        Args:
            queue_id: UUID of the template_queue record
            reason: Rejection reason
            reviewed_by: Who rejected it
        """
        self.supabase.table("template_queue").update({
            "status": "rejected",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat(),
            "rejection_reason": reason
        }).eq("id", str(queue_id)).execute()

        logger.info(f"Rejected template queue item: {queue_id}")

    def archive_template(
        self,
        queue_id: UUID,
        reviewed_by: str = "system"
    ) -> None:
        """
        Archive queue item (skip without rejecting).

        Args:
            queue_id: UUID of the template_queue record
            reviewed_by: Who archived it
        """
        self.supabase.table("template_queue").update({
            "status": "archived",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat()
        }).eq("id", str(queue_id)).execute()

        logger.info(f"Archived template queue item: {queue_id}")

    def get_templates(
        self,
        category: Optional[str] = None,
        awareness_level: Optional[int] = None,
        industry_niche: Optional[str] = None,
        target_sex: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
        source_brand: Optional[str] = None,
        sort_by: str = "most_used",
    ) -> List[Dict]:
        """
        Get approved templates from library.

        Args:
            category: Optional category filter
            awareness_level: Optional awareness level (1-5)
            industry_niche: Optional industry/niche filter
            target_sex: Optional target sex filter (male/female/unisex)
            active_only: Only return active templates
            limit: Maximum templates to return
            source_brand: Optional source brand (advertiser) name substring filter
            sort_by: Sort order — "most_used", "least_used", "highest_rank", "hottest", "newest", "oldest"

        Returns:
            List of template records
        """
        # Always join facebook_ads for position data (used by badges + sorting)
        use_position_sort = sort_by in ("highest_rank", "hottest")
        select_cols = (
            "*, facebook_ads!source_facebook_ad_id("
            "best_scrape_position, latest_scrape_position, scrape_total, "
            "start_date, collation_count)"
        )

        query = self.supabase.table("scraped_templates").select(select_cols)

        if active_only:
            query = query.eq("is_active", True)
        if category:
            query = query.eq("category", category)
        if awareness_level:
            query = query.eq("awareness_level", awareness_level)
        if industry_niche:
            query = query.eq("industry_niche", industry_niche)
        if target_sex:
            query = query.eq("target_sex", target_sex)
        if source_brand:
            query = query.ilike("source_brand", f"%{source_brand}%")

        # Sort — position-based sorts are computed in Python after fetch
        if sort_by == "newest":
            query = query.order("created_at", desc=True)
        elif sort_by == "oldest":
            query = query.order("created_at", desc=False)
        elif sort_by == "least_used":
            query = query.order("times_used", desc=False)
        elif use_position_sort:
            query = query.order("created_at", desc=True)
        else:  # most_used (default)
            query = query.order("times_used", desc=True)

        query = query.limit(limit)
        result = query.execute()

        if not result.data:
            return []

        # Always flatten facebook_ads join data onto template rows
        fb_ad_ids = []
        for row in result.data:
            fb = row.pop("facebook_ads", None) or {}
            row["best_scrape_position"] = fb.get("best_scrape_position")
            row["latest_scrape_position"] = fb.get("latest_scrape_position")
            row["scrape_total"] = fb.get("scrape_total")
            row["start_date"] = fb.get("start_date")
            row["collation_count"] = fb.get("collation_count")
            fb_id = row.get("source_facebook_ad_id")
            if fb_id:
                fb_ad_ids.append(fb_id)

        # Batch fetch position trends from history table
        trends = self._compute_position_trends(fb_ad_ids) if fb_ad_ids else {}
        for row in result.data:
            fb_id = row.get("source_facebook_ad_id")
            row["position_trend"] = trends.get(fb_id) if fb_id else None

        # Position-based sorts computed in Python
        if use_position_sort:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)

            for row in result.data:
                best_pos = row.get("best_scrape_position")
                latest_pos = row.get("latest_scrape_position")
                total = row.get("scrape_total")
                start_date = row.get("start_date")

                if sort_by == "highest_rank":
                    row["_sort_key"] = (best_pos is None, best_pos or 0)

                else:  # hottest — velocity formula from plan
                    if latest_pos is not None and start_date is not None:
                        if total and total > 1:
                            pos_pct = 1.0 - (latest_pos - 1) / (total - 1)
                        else:
                            pos_pct = 1.0 if latest_pos == 1 else 0.5

                        try:
                            if isinstance(start_date, str):
                                start_dt = datetime.fromisoformat(
                                    start_date.replace("Z", "+00:00")
                                )
                            else:
                                start_dt = start_date
                            days_active = max((now - start_dt).days, 1)
                        except (ValueError, TypeError):
                            days_active = 365

                        recency_factor = 2 ** (-days_active / 30)
                        velocity = pos_pct * (0.4 + 0.6 * recency_factor)
                    else:
                        velocity = 0.0

                    row["_sort_key"] = (velocity == 0.0, -velocity)

            result.data.sort(key=lambda r: r.get("_sort_key", (True, 0)))

            for row in result.data:
                row.pop("_sort_key", None)

        return result.data

    def _compute_position_trends(self, facebook_ad_ids: List[str]) -> Dict[str, str]:
        """Compute position trends from last 3 scrapes per ad.

        Returns:
            Dict mapping facebook_ad_id → trend string: "rising", "falling", "stable", or None.
        """
        if not facebook_ad_ids:
            return {}

        try:
            # Batch fetch recent position history (last 3 per ad, ordered by date desc)
            # Supabase doesn't support LATERAL joins, so fetch all recent history
            # and group in Python
            unique_ids = list(set(facebook_ad_ids))
            all_history = []
            batch_size = 50
            for i in range(0, len(unique_ids), batch_size):
                batch = unique_ids[i:i + batch_size]
                hist_result = self.supabase.table("facebook_ad_position_history").select(
                    "facebook_ad_id, deduped_position, scraped_at"
                ).in_("facebook_ad_id", batch).order(
                    "scraped_at", desc=True
                ).limit(batch_size * 3).execute()
                if hist_result.data:
                    all_history.extend(hist_result.data)

            # Group by ad, keep last 3
            from collections import defaultdict
            by_ad = defaultdict(list)
            for row in all_history:
                ad_id = row["facebook_ad_id"]
                pos = row.get("deduped_position")
                if pos is not None and len(by_ad[ad_id]) < 3:
                    by_ad[ad_id].append(pos)

            # Compute trend from positions (ordered newest-first)
            trends = {}
            for ad_id, positions in by_ad.items():
                if len(positions) < 2:
                    trends[ad_id] = None
                    continue

                # positions[0] = most recent, positions[-1] = oldest
                # Rising = position number going down (improving)
                newest = positions[0]
                oldest = positions[-1]
                diff = oldest - newest  # positive = improving (position dropped)

                if diff >= 2:
                    trends[ad_id] = "rising"
                elif diff <= -2:
                    trends[ad_id] = "falling"
                else:
                    trends[ad_id] = "stable"

            return trends
        except Exception as e:
            logger.warning(f"Failed to compute position trends: {e}")
            return {}

    def get_source_brands(self) -> List[str]:
        """Get distinct non-null source brand names from active templates."""
        # Paginate to avoid Supabase default 1000-row limit
        all_brands = set()
        page_size = 1000
        offset = 0
        while True:
            result = self.supabase.table("scraped_templates").select(
                "source_brand"
            ).eq("is_active", True).not_.is_(
                "source_brand", "null"
            ).range(offset, offset + page_size - 1).execute()

            rows = result.data or []
            for r in rows:
                if r.get("source_brand"):
                    all_brands.add(r["source_brand"])

            if len(rows) < page_size:
                break
            offset += page_size

        return sorted(all_brands, key=lambda x: x.lower())

    def get_template_categories(self) -> List[str]:
        """Get list of valid template categories."""
        return [
            "testimonial",
            "quote_card",
            "before_after",
            "product_showcase",
            "ugc_style",
            "meme",
            "carousel_frame",
            "story_format",
            "other"
        ]

    def get_awareness_levels(self) -> List[Dict[str, Any]]:
        """Get awareness level options for filtering."""
        return [
            {"value": 1, "label": "1 - Unaware"},
            {"value": 2, "label": "2 - Problem Aware"},
            {"value": 3, "label": "3 - Solution Aware"},
            {"value": 4, "label": "4 - Product Aware"},
            {"value": 5, "label": "5 - Most Aware"},
        ]

    def get_industry_niches(self) -> List[str]:
        """Get distinct industry niches from active templates."""
        result = self.supabase.table("scraped_templates")\
            .select("industry_niche")\
            .eq("is_active", True)\
            .not_.is_("industry_niche", "null")\
            .execute()
        niches = sorted(set(r['industry_niche'] for r in result.data if r.get('industry_niche')))
        return niches

    def get_target_sex_options(self) -> List[str]:
        """Get target sex options for filtering."""
        return ["male", "female", "unisex"]

    def record_template_usage(
        self,
        template_id: UUID,
        ad_run_id: Optional[UUID] = None
    ) -> None:
        """
        Record that a template was used.

        Args:
            template_id: UUID of the template
            ad_run_id: Optional ad_run to link
        """
        # Increment times_used
        template = self.supabase.table("scraped_templates").select(
            "times_used"
        ).eq("id", str(template_id)).execute()

        if template.data:
            current_count = template.data[0].get("times_used", 0) or 0
            self.supabase.table("scraped_templates").update({
                "times_used": current_count + 1,
                "last_used_at": datetime.utcnow().isoformat()
            }).eq("id", str(template_id)).execute()

        # Link to ad_run if provided (column may not exist in all deployments)
        if ad_run_id:
            try:
                self.supabase.table("ad_runs").update({
                    "source_template_id": str(template_id)
                }).eq("id", str(ad_run_id)).execute()
            except Exception as e:
                # source_template_id column may not exist - log but don't fail
                logger.warning(f"Could not link template to ad_run (column may not exist): {e}")

        logger.info(f"Recorded usage for template: {template_id}")

    def get_asset_preview_url(self, storage_path: str) -> str:
        """
        Get public URL for asset preview.

        Args:
            storage_path: Full storage path (bucket/path)

        Returns:
            Public URL for the asset
        """
        try:
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                return ""

            bucket = parts[0]
            path = parts[1]

            # Get public URL
            result = self.supabase.storage.from_(bucket).get_public_url(path)
            return result

        except Exception as e:
            logger.error(f"Failed to get preview URL: {e}")
            return ""

    # =========================================================================
    # AI-Enhanced Approval Methods (Two-Step Flow)
    # =========================================================================

    async def analyze_template_for_approval(self, queue_id: UUID) -> Dict[str, Any]:
        """
        Run AI analysis on a queued template image.

        Args:
            queue_id: UUID of the template_queue record

        Returns:
            Dict with AI suggestions for template metadata
        """
        from .gemini_service import GeminiService

        # Get queue item with asset and facebook_ad data
        result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, facebook_ad_id), "
            "facebook_ads:scraped_ad_assets(facebook_ad_id(page_name, link_url, ad_body, ad_title))"
        ).eq("id", str(queue_id)).execute()

        if not result.data:
            raise ValueError(f"Queue item not found: {queue_id}")

        queue_item = result.data[0]
        asset = queue_item.get("scraped_ad_assets", {})
        storage_path = asset.get("storage_path", "")

        # Get facebook_ad data for context
        fb_ad = {}
        if queue_item.get("facebook_ads"):
            fb_nested = queue_item["facebook_ads"]
            if isinstance(fb_nested, dict) and fb_nested.get("facebook_ad_id"):
                fb_ad = fb_nested["facebook_ad_id"]
            elif isinstance(fb_nested, list) and len(fb_nested) > 0:
                fb_ad = fb_nested[0].get("facebook_ad_id", {}) or {}

        page_name = fb_ad.get("page_name", "Unknown Brand")
        link_url = fb_ad.get("link_url", "")

        # Download image from storage
        if not storage_path:
            raise ValueError("No storage path for asset")

        parts = storage_path.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid storage path: {storage_path}")

        bucket, path = parts
        image_data = self.supabase.storage.from_(bucket).download(path)

        if not image_data:
            raise ValueError(f"Failed to download image: {storage_path}")

        # Convert to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        # Build prompt with context
        prompt = TEMPLATE_ANALYSIS_PROMPT.format(
            page_name=page_name,
            link_url=link_url or "Not available"
        )

        # Call Gemini for analysis
        gemini = GeminiService()
        response_text = await gemini.analyze_image(image_base64, prompt)

        # Parse JSON response
        try:
            # Clean response (remove markdown code blocks if present)
            clean_response = response_text.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]
            clean_response = clean_response.strip()

            suggestions = json.loads(clean_response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}\nResponse: {response_text[:500]}")
            # Return default suggestions
            suggestions = {
                "suggested_name": "Untitled Template",
                "suggested_description": "Template from Facebook ad",
                "format_type": "other",
                "industry_niche": "other",
                "target_sex": "unisex",
                "awareness_level": 3,
                "awareness_level_reasoning": "Could not determine",
                "sales_event": None,
                "visual_notes": ""
            }

        # Add source data
        suggestions["source_brand"] = page_name
        suggestions["source_landing_page"] = link_url
        suggestions["raw_response"] = response_text

        logger.info(f"AI analysis complete for queue item {queue_id}")
        return suggestions

    async def start_approval(self, queue_id: UUID) -> Dict[str, Any]:
        """
        Start two-step approval: set status to pending_details and run AI analysis.

        Args:
            queue_id: UUID of the template_queue record

        Returns:
            Dict with AI suggestions for user review
        """
        # Run AI analysis
        suggestions = await self.analyze_template_for_approval(queue_id)

        # Update queue status and store suggestions
        self.supabase.table("template_queue").update({
            "status": "pending_details",
            "ai_suggestions": suggestions
        }).eq("id", str(queue_id)).execute()

        logger.info(f"Started approval for queue item {queue_id} - awaiting details confirmation")
        return suggestions

    def finalize_approval(
        self,
        queue_id: UUID,
        name: str,
        description: str,
        category: str,
        industry_niche: str,
        target_sex: str,
        awareness_level: int,
        sales_event: Optional[str] = None,
        reviewed_by: str = "system"
    ) -> Dict:
        """
        Finalize approval with user-confirmed metadata.

        Args:
            queue_id: UUID of the template_queue record
            name: Confirmed template name
            description: Confirmed description
            category: Format category (testimonial, quote_card, etc.)
            industry_niche: Industry category
            target_sex: Target gender (male/female/unisex)
            awareness_level: Consumer awareness level 1-5
            sales_event: Optional sales event tag
            reviewed_by: Who approved it

        Returns:
            Created template record
        """
        # Awareness level names
        awareness_names = {
            1: "Unaware",
            2: "Problem Aware",
            3: "Solution Aware",
            4: "Product Aware",
            5: "Most Aware"
        }

        # Get queue item with asset and stored suggestions
        queue_result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, facebook_ad_id, asset_type)"
        ).eq("id", str(queue_id)).execute()

        if not queue_result.data:
            raise ValueError(f"Queue item not found: {queue_id}")

        queue_item = queue_result.data[0]
        asset = queue_item.get("scraped_ad_assets", {})
        ai_suggestions = queue_item.get("ai_suggestions", {})

        # Update queue status
        self.supabase.table("template_queue").update({
            "status": "approved",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat(),
            "template_category": category,
            "template_name": name
        }).eq("id", str(queue_id)).execute()

        # Create template with all metadata
        template = {
            "source_asset_id": queue_item["asset_id"],
            "source_facebook_ad_id": queue_item.get("facebook_ad_id"),
            "source_queue_id": str(queue_id),
            "name": name,
            "description": description,
            "category": category,
            "storage_path": asset.get("storage_path", ""),
            "is_active": True,
            # New AI-enhanced fields
            "source_brand": ai_suggestions.get("source_brand", ""),
            "source_landing_page": ai_suggestions.get("source_landing_page", ""),
            "industry_niche": industry_niche,
            "target_sex": target_sex,
            "awareness_level": awareness_level,
            "awareness_level_name": awareness_names.get(awareness_level, "Unknown"),
            "sales_event": sales_event if sales_event else None,
            "ai_suggested_name": ai_suggestions.get("suggested_name", ""),
            "ai_suggested_description": ai_suggestions.get("suggested_description", ""),
            "ai_analysis_raw": ai_suggestions
        }

        result = self.supabase.table("scraped_templates").insert(template).execute()

        if result.data:
            logger.info(f"Created template: {name} ({category}) - {industry_niche}")
            return result.data[0]

        raise Exception("Failed to create template")

    def get_pending_details_item(self, queue_id: UUID) -> Optional[Dict]:
        """
        Get a queue item that's pending details confirmation.

        Args:
            queue_id: UUID of the template_queue record

        Returns:
            Queue item with AI suggestions, or None if not found/wrong status
        """
        result = self.supabase.table("template_queue").select(
            "*, scraped_ad_assets(storage_path, asset_type)"
        ).eq("id", str(queue_id)).eq("status", "pending_details").execute()

        if result.data:
            return result.data[0]
        return None

    def cancel_approval(self, queue_id: UUID) -> None:
        """
        Cancel an in-progress approval (return to pending status).

        Args:
            queue_id: UUID of the template_queue record
        """
        self.supabase.table("template_queue").update({
            "status": "pending",
            "ai_suggestions": {}
        }).eq("id", str(queue_id)).execute()

        logger.info(f"Cancelled approval for queue item {queue_id} - returned to pending")

    async def start_bulk_approval(self, queue_ids: List[UUID]) -> List[Dict[str, Any]]:
        """
        Run AI analysis on multiple queue items concurrently.

        Args:
            queue_ids: List of queue item UUIDs to analyze

        Returns:
            List of dicts with {queue_id, suggestions, success} for successful items
        """
        import asyncio

        async def analyze_one(qid: UUID) -> Dict[str, Any]:
            try:
                suggestions = await self.analyze_template_for_approval(qid)
                # Update status to pending_details
                self.supabase.table("template_queue").update({
                    "status": "pending_details",
                    "ai_suggestions": suggestions
                }).eq("id", str(qid)).execute()
                return {"queue_id": str(qid), "suggestions": suggestions, "success": True}
            except Exception as e:
                logger.error(f"AI analysis failed for {qid}: {e}")
                return {"queue_id": str(qid), "error": str(e), "success": False}

        results = await asyncio.gather(*[analyze_one(qid) for qid in queue_ids])
        successful = [r for r in results if r.get("success")]
        logger.info(f"Bulk approval started: {len(successful)}/{len(queue_ids)} items analyzed successfully")
        return successful

    def finalize_bulk_approval(
        self,
        items: List[Dict[str, Any]],
        reviewed_by: str = "streamlit_user"
    ) -> Dict[str, Any]:
        """
        Finalize multiple approvals using AI suggestions as defaults.

        Args:
            items: List of dicts with {queue_id, suggestions}
            reviewed_by: Who approved the items

        Returns:
            Dict with 'approved' count and 'template_ids' list
        """
        template_ids = []
        for item in items:
            try:
                queue_id = UUID(item["queue_id"])
                s = item["suggestions"]
                template = self.finalize_approval(
                    queue_id=queue_id,
                    name=s.get("suggested_name", "Template"),
                    description=s.get("suggested_description", ""),
                    category=s.get("format_type", "other"),
                    industry_niche=s.get("industry_niche", "other"),
                    target_sex=s.get("target_sex", "unisex"),
                    awareness_level=s.get("awareness_level", 3),
                    sales_event=s.get("sales_event"),
                    reviewed_by=reviewed_by
                )
                template_ids.append(template["id"])
            except Exception as e:
                logger.error(f"Failed to finalize {item.get('queue_id')}: {e}")

        logger.info(f"Bulk approval finalized: {len(template_ids)}/{len(items)} items approved")
        return {"approved": len(template_ids), "template_ids": template_ids}

    async def add_manual_template(
        self,
        image_data: bytes,
        filename: str,
        brand_id: Optional[str] = None,
        run_ai_analysis: bool = True,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """
        Manually upload a template image and route it through the ingestion pipeline.

        Args:
            image_data: Raw image bytes
            filename: Original filename
            brand_id: Optional brand ID for organization
            run_ai_analysis: Whether to run AI pre-analysis
            auto_approve: Whether to auto-approve with AI defaults (skips human review)

        Returns:
            Dict with asset_id, queue_id, template_id (if auto-approved), status
        """
        import uuid as _uuid

        # Determine file extension
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'png'
        if ext not in ('png', 'jpg', 'jpeg', 'webp'):
            ext = 'png'

        # Upload to S3
        unique_name = f"{_uuid.uuid4()}.{ext}"
        storage_path = f"scraped-assets/manual/{unique_name}"

        # Detect content type
        content_type = {
            'png': 'image/png', 'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg', 'webp': 'image/webp',
        }.get(ext, 'image/png')

        bucket, path = storage_path.split("/", 1)
        self.supabase.storage.from_(bucket).upload(
            path, image_data, {"content-type": content_type}
        )

        # Create scraped_ad_assets record (facebook_ad_id is NULL for manual uploads)
        asset_data = {
            "storage_path": storage_path,
            "asset_type": "image",
            "scrape_source": "manual_upload",
        }
        asset_result = self.supabase.table("scraped_ad_assets").insert(asset_data).execute()
        asset_id = asset_result.data[0]["id"]

        # Create template_queue record
        queue_data = {
            "asset_id": asset_id,
            "status": "pending",
        }
        queue_result = self.supabase.table("template_queue").insert(queue_data).execute()
        queue_id = queue_result.data[0]["id"]

        result = {
            "asset_id": asset_id,
            "queue_id": queue_id,
            "template_id": None,
            "status": "queued",
        }

        # Run AI analysis if requested
        if run_ai_analysis:
            try:
                suggestions = await self.start_approval(UUID(queue_id))
                result["status"] = "analyzed"
                result["suggestions"] = suggestions

                # Auto-approve with AI defaults
                if auto_approve and suggestions:
                    template = self.finalize_approval(
                        queue_id=UUID(queue_id),
                        name=suggestions.get("suggested_name", filename),
                        description=suggestions.get("suggested_description", "Manually uploaded template"),
                        category=suggestions.get("format_type", "other"),
                        industry_niche=suggestions.get("industry_niche", "other"),
                        target_sex=suggestions.get("target_sex", "unisex"),
                        awareness_level=suggestions.get("awareness_level", 3),
                        sales_event=suggestions.get("sales_event"),
                        reviewed_by="auto_approve",
                    )
                    result["template_id"] = template["id"]
                    result["status"] = "auto_approved"
            except Exception as e:
                logger.error(f"AI analysis failed for manual upload {queue_id}: {e}")
                result["status"] = "queued_no_analysis"
                result["error"] = str(e)

        logger.info(f"Manual template uploaded: asset={asset_id}, queue={queue_id}, status={result['status']}")
        return result

    def download_template_image(self, template_id: str) -> Optional[str]:
        """Download a template image from Supabase storage and return as base64.

        Args:
            template_id: UUID of the scraped_templates record.

        Returns:
            Base64-encoded image string, or None if not found or download fails.
        """
        try:
            result = (
                self.supabase.table("scraped_templates")
                .select("id, storage_path")
                .eq("id", template_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                logger.warning(f"Template {template_id} not found")
                return None

            row = result.data[0]
            storage_path = row.get("storage_path", "")

            if not storage_path:
                logger.warning(f"Template {template_id} has no storage_path")
                return None

            # storage_path is "bucket/path/to/file" — split into bucket + path
            if "/" in storage_path:
                parts = storage_path.split("/", 1)
                bucket = parts[0]
                path = parts[1]
            else:
                bucket = "scraped-assets"
                path = storage_path

            data = self.supabase.storage.from_(bucket).download(path)
            return base64.b64encode(data).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to download template image {template_id}: {e}")
            return None
