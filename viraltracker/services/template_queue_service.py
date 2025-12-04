"""
TemplateQueueService - Template approval queue management.

This service handles:
- Adding scraped assets to review queue
- AI pre-analysis for reviewer assistance
- Approval/rejection workflow
- Template library management

Part of the Brand Research Pipeline (Phase 2B: Template Queue).
"""

import logging
import base64
from typing import List, Dict, Optional
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


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
