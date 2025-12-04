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
        Get queue statistics.

        Returns:
            Dict with counts by status
        """
        result = self.supabase.table("template_queue").select(
            "status"
        ).execute()

        stats = {"pending": 0, "approved": 0, "rejected": 0, "archived": 0, "total": 0}
        for item in result.data:
            status = item.get("status", "pending")
            stats[status] = stats.get(status, 0) + 1
            stats["total"] += 1

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
        active_only: bool = True,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get approved templates from library.

        Args:
            category: Optional category filter
            active_only: Only return active templates
            limit: Maximum templates to return

        Returns:
            List of template records
        """
        query = self.supabase.table("scraped_templates").select("*")

        if active_only:
            query = query.eq("is_active", True)
        if category:
            query = query.eq("category", category)

        query = query.order("times_used", desc=True).limit(limit)
        result = query.execute()

        return result.data

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

        # Link to ad_run if provided
        if ad_run_id:
            self.supabase.table("ad_runs").update({
                "source_template_id": str(template_id)
            }).eq("id", str(ad_run_id)).execute()

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
