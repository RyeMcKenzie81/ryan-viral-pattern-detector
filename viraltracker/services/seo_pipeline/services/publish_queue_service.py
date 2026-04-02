"""
Publish Queue Service — staggered article publishing with idempotency.

Manages the seo_publish_queue table. Handles:
- Slot calculation based on brand publish cadence
- Enqueue with idempotency keys (content hash)
- Due article lookup for the scheduler job
- Status transitions and error tracking
"""

import logging
import math
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)


class PublishQueueService:
    """Manages scheduled article publishing with staggered slots."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def enqueue_article(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str,
        content_hash: str,
        policy: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Enqueue an article for scheduled publishing.

        Calculates the next available publish slot based on the brand's
        cadence configuration and inserts into the publish queue.

        Args:
            article_id: Article UUID
            brand_id: Brand UUID
            organization_id: Organization UUID
            content_hash: SHA256 hash for idempotency
            policy: Brand content policy dict

        Returns:
            Queue entry dict, or None if already enqueued
        """
        idempotency_key = f"{article_id}:{content_hash}"

        # Check if already enqueued with same content
        existing = (
            self.supabase.table("seo_publish_queue")
            .select("id, status")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
        if existing.data:
            logger.info(f"Article {article_id} already enqueued (key: {idempotency_key})")
            return None

        # Cancel any previous queued entries for this article
        self.supabase.table("seo_publish_queue").update(
            {"status": "cancelled"}
        ).eq("article_id", article_id).eq("status", "queued").execute()

        # Calculate next publish slot
        publish_at = self._calculate_next_slot(brand_id, policy)

        record = {
            "article_id": article_id,
            "brand_id": brand_id,
            "organization_id": organization_id,
            "publish_at": publish_at.isoformat(),
            "status": "queued",
            "idempotency_key": idempotency_key,
        }

        try:
            result = self.supabase.table("seo_publish_queue").insert(record).execute()
            if result.data:
                logger.info(
                    f"Article {article_id} enqueued for {publish_at.strftime('%Y-%m-%d %H:%M %Z')}"
                )

                # Update article status to publish_queued
                self.supabase.table("seo_articles").update(
                    {"status": "publish_queued"}
                ).eq("id", article_id).execute()

                return result.data[0]
        except Exception as e:
            if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                logger.info(f"Article {article_id} already enqueued (race condition)")
                return None
            raise

        return None

    def get_due_articles(self) -> List[Dict[str, Any]]:
        """
        Find articles due for publishing (queued and past their publish_at time).

        Returns:
            List of queue entries ready to publish
        """
        now = datetime.now(pytz.UTC).isoformat()
        result = (
            self.supabase.table("seo_publish_queue")
            .select("*, seo_articles(id, keyword, title, content_html, cms_article_id, brand_id, organization_id)")
            .eq("status", "queued")
            .lte("publish_at", now)
            .order("publish_at")
            .execute()
        )
        return result.data or []

    def mark_publishing(self, queue_id: str) -> None:
        """Mark a queue entry as currently publishing."""
        self.supabase.table("seo_publish_queue").update(
            {"status": "publishing", "updated_at": datetime.now(pytz.UTC).isoformat()}
        ).eq("id", queue_id).execute()

    def mark_published(self, queue_id: str, article_id: str) -> None:
        """Mark a queue entry as successfully published."""
        now = datetime.now(pytz.UTC).isoformat()
        self.supabase.table("seo_publish_queue").update(
            {"status": "published", "published_at": now, "updated_at": now}
        ).eq("id", queue_id).execute()

        # Update article status
        self.supabase.table("seo_articles").update(
            {"status": "published"}
        ).eq("id", article_id).execute()

    def mark_failed(self, queue_id: str, error_message: str) -> bool:
        """
        Mark a queue entry as failed. Returns True if retries remain.

        Args:
            queue_id: Queue entry UUID
            error_message: Error description

        Returns:
            True if the entry will be retried, False if max retries exceeded
        """
        entry = (
            self.supabase.table("seo_publish_queue")
            .select("retry_count, max_retries")
            .eq("id", queue_id)
            .limit(1)
            .execute()
        )
        if not entry.data:
            return False

        retry_count = entry.data[0].get("retry_count", 0) + 1
        max_retries = entry.data[0].get("max_retries", 3)

        if retry_count >= max_retries:
            self.supabase.table("seo_publish_queue").update({
                "status": "failed",
                "error_message": error_message,
                "retry_count": retry_count,
                "updated_at": datetime.now(pytz.UTC).isoformat(),
            }).eq("id", queue_id).execute()
            return False
        else:
            # Keep queued for retry — retries are not constrained to publish window
            self.supabase.table("seo_publish_queue").update({
                "status": "queued",
                "error_message": error_message,
                "retry_count": retry_count,
                "updated_at": datetime.now(pytz.UTC).isoformat(),
            }).eq("id", queue_id).execute()
            return True

    def get_failed_publishes(
        self,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get failed publish entries for the exceptions dashboard."""
        query = (
            self.supabase.table("seo_publish_queue")
            .select("*, seo_articles(keyword, title)")
            .eq("status", "failed")
            .order("updated_at", desc=True)
            .limit(limit)
        )
        if brand_id:
            query = query.eq("brand_id", brand_id)
        if organization_id:
            query = query.eq("organization_id", organization_id)
        return (query.execute()).data or []

    def retry_publish(self, queue_id: str) -> None:
        """Reset a failed publish entry to queued for immediate retry."""
        self.supabase.table("seo_publish_queue").update({
            "status": "queued",
            "error_message": None,
            "retry_count": 0,
            "updated_at": datetime.now(pytz.UTC).isoformat(),
        }).eq("id", queue_id).execute()

    def cancel_publish(self, queue_id: str) -> None:
        """Cancel a queued or failed publish entry."""
        self.supabase.table("seo_publish_queue").update({
            "status": "cancelled",
            "updated_at": datetime.now(pytz.UTC).isoformat(),
        }).eq("id", queue_id).execute()

    def get_queue_stats(
        self, brand_id: Optional[str] = None
    ) -> Dict[str, int]:
        """Get queue status counts."""
        query = self.supabase.table("seo_publish_queue").select("status")
        if brand_id:
            query = query.eq("brand_id", brand_id)
        entries = (query.execute()).data or []

        stats = {"queued": 0, "publishing": 0, "published": 0, "failed": 0, "cancelled": 0}
        for entry in entries:
            status = entry.get("status", "unknown")
            if status in stats:
                stats[status] += 1
        return stats

    # =========================================================================
    # PRIVATE — Slot calculation
    # =========================================================================

    def _calculate_next_slot(
        self, brand_id: str, policy: Dict[str, Any]
    ) -> datetime:
        """
        Calculate the next available publish slot for a brand.

        Slot formula: slot_i = window_start + i * (window_end - window_start) / (N - 1)
        for N >= 2. For N = 1, slot = window_start.

        publish_window_end is inclusive.
        """
        tz_name = policy.get("publish_timezone", "America/New_York")
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("America/New_York")

        times_per_day = max(1, policy.get("publish_times_per_day", 2))
        days_of_week = policy.get("publish_days_of_week", [1, 2, 3, 4, 5])

        window_start_str = policy.get("publish_window_start", "09:00")
        window_end_str = policy.get("publish_window_end", "17:00")

        start_parts = str(window_start_str).split(":")
        h_start, m_start = int(start_parts[0]), int(start_parts[1])
        end_parts = str(window_end_str).split(":")
        h_end, m_end = int(end_parts[0]), int(end_parts[1])

        window_start = time(h_start, m_start)
        window_end = time(h_end, m_end)

        # Calculate slot times within the window
        start_minutes = h_start * 60 + m_start
        end_minutes = h_end * 60 + m_end
        window_minutes = end_minutes - start_minutes

        if times_per_day == 1:
            slot_offsets = [0]
        else:
            slot_offsets = [
                round(i * window_minutes / (times_per_day - 1))
                for i in range(times_per_day)
            ]

        slot_times = [
            time((start_minutes + offset) // 60, (start_minutes + offset) % 60)
            for offset in slot_offsets
        ]

        # Get existing queued entries for this brand to find taken slots
        existing = (
            self.supabase.table("seo_publish_queue")
            .select("publish_at")
            .eq("brand_id", brand_id)
            .eq("status", "queued")
            .order("publish_at")
            .execute()
        )
        taken_slots = set()
        for entry in (existing.data or []):
            try:
                dt = datetime.fromisoformat(entry["publish_at"].replace("Z", "+00:00"))
                taken_slots.add(dt.astimezone(tz).strftime("%Y-%m-%d %H:%M"))
            except (ValueError, KeyError):
                pass

        # Find next available slot
        now = datetime.now(tz)
        check_date = now.date()

        for day_offset in range(30):  # Look up to 30 days ahead
            candidate_date = check_date + timedelta(days=day_offset)
            # isoweekday: 1=Mon, 7=Sun
            if candidate_date.isoweekday() not in days_of_week:
                continue

            for slot_time in slot_times:
                candidate = tz.localize(
                    datetime.combine(candidate_date, slot_time)
                )

                # Skip slots in the past
                if candidate <= now:
                    continue

                slot_key = candidate.strftime("%Y-%m-%d %H:%M")
                if slot_key not in taken_slots:
                    return candidate

        # Fallback: 24 hours from now
        logger.warning(f"Could not find available slot for brand {brand_id}, using 24h fallback")
        return now + timedelta(hours=24)
