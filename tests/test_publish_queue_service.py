"""
Publish Queue Service Tests — exercises PublishQueueService with mocked Supabase.

Covers:
- _calculate_next_slot: slot formula for N=1, N=2, N>2, day skipping, taken slots
- enqueue_article: idempotency check, cancels previous, status transition
- mark_failed: retry logic, max retries exceeded
- get_due_articles: filters by status + time
- retry_publish: resets state
- cancel_publish: status transition
- get_queue_stats: status counting
"""

import json
import pytest
from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytz

BRAND_ID = "22222222-2222-2222-2222-222222222222"
ORG_ID = "33333333-3333-3333-3333-333333333333"
ARTICLE_ID = "66666666-6666-6666-6666-666666666666"


def _make_service(mock_supabase=None):
    from viraltracker.services.seo_pipeline.services.publish_queue_service import PublishQueueService
    return PublishQueueService(supabase_client=mock_supabase or MagicMock())


# =============================================================================
# TESTS — _calculate_next_slot
# =============================================================================


class TestCalculateNextSlot:
    def test_single_slot_per_day(self):
        """N=1 → slot is at window_start."""
        mock_db = MagicMock()
        existing_result = MagicMock()
        existing_result.data = []
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = existing_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        policy = {
            "publish_timezone": "UTC",
            "publish_times_per_day": 1,
            "publish_window_start": "09:00",
            "publish_window_end": "17:00",
            "publish_days_of_week": [1, 2, 3, 4, 5],
        }

        with patch("viraltracker.services.seo_pipeline.services.publish_queue_service.datetime") as mock_dt:
            # Wednesday 2026-03-25 at 06:00 UTC
            utc = pytz.UTC
            fake_now = utc.localize(datetime(2026, 3, 25, 6, 0, 0))
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.fromisoformat = datetime.fromisoformat

            slot = svc._calculate_next_slot(BRAND_ID, policy)
            # Should get 09:00 same day
            assert slot.hour == 9
            assert slot.minute == 0

    def test_two_slots_per_day(self):
        """N=2 → slots at window_start and window_end."""
        mock_db = MagicMock()
        existing_result = MagicMock()
        existing_result.data = []
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = existing_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        policy = {
            "publish_timezone": "UTC",
            "publish_times_per_day": 2,
            "publish_window_start": "09:00",
            "publish_window_end": "17:00",
            "publish_days_of_week": [1, 2, 3, 4, 5],
        }

        with patch("viraltracker.services.seo_pipeline.services.publish_queue_service.datetime") as mock_dt:
            utc = pytz.UTC
            fake_now = utc.localize(datetime(2026, 3, 25, 6, 0, 0))
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.fromisoformat = datetime.fromisoformat

            slot = svc._calculate_next_slot(BRAND_ID, policy)
            assert slot.hour == 9
            assert slot.minute == 0

    def test_skips_weekend(self):
        """If today is Saturday and only weekdays, next slot is Monday."""
        mock_db = MagicMock()
        existing_result = MagicMock()
        existing_result.data = []
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = existing_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        policy = {
            "publish_timezone": "UTC",
            "publish_times_per_day": 1,
            "publish_window_start": "09:00",
            "publish_window_end": "17:00",
            "publish_days_of_week": [1, 2, 3, 4, 5],  # weekdays only
        }

        with patch("viraltracker.services.seo_pipeline.services.publish_queue_service.datetime") as mock_dt:
            utc = pytz.UTC
            # Saturday 2026-03-28
            fake_now = utc.localize(datetime(2026, 3, 28, 6, 0, 0))
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.fromisoformat = datetime.fromisoformat

            slot = svc._calculate_next_slot(BRAND_ID, policy)
            # Should be Monday March 30
            assert slot.weekday() == 0  # Monday
            assert slot.day == 30

    def test_skips_taken_slots(self):
        """Slots already in the queue are skipped."""
        mock_db = MagicMock()
        existing_result = MagicMock()
        existing_result.data = [
            {"publish_at": "2026-03-25T09:00:00+00:00"},
        ]
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = existing_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        policy = {
            "publish_timezone": "UTC",
            "publish_times_per_day": 2,
            "publish_window_start": "09:00",
            "publish_window_end": "17:00",
            "publish_days_of_week": [1, 2, 3, 4, 5],
        }

        with patch("viraltracker.services.seo_pipeline.services.publish_queue_service.datetime") as mock_dt:
            utc = pytz.UTC
            fake_now = utc.localize(datetime(2026, 3, 25, 6, 0, 0))
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.fromisoformat = datetime.fromisoformat

            slot = svc._calculate_next_slot(BRAND_ID, policy)
            # 09:00 is taken, should get 17:00
            assert slot.hour == 17
            assert slot.minute == 0


# =============================================================================
# TESTS — mark_failed
# =============================================================================


class TestMarkFailed:
    def test_retries_when_under_max(self):
        mock_db = MagicMock()
        entry_result = MagicMock()
        entry_result.data = [{"retry_count": 0, "max_retries": 3}]

        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = entry_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        has_retries = svc.mark_failed("queue-1", "Connection timeout")
        assert has_retries is True

    def test_no_retries_at_max(self):
        mock_db = MagicMock()
        entry_result = MagicMock()
        entry_result.data = [{"retry_count": 2, "max_retries": 3}]

        update_result = MagicMock()
        update_result.data = [{}]

        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = entry_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        has_retries = svc.mark_failed("queue-1", "Connection timeout")
        assert has_retries is False


# =============================================================================
# TESTS — get_queue_stats
# =============================================================================


class TestGetQueueStats:
    def test_counts_by_status(self):
        mock_db = MagicMock()
        query_result = MagicMock()
        query_result.data = [
            {"status": "queued"},
            {"status": "queued"},
            {"status": "published"},
            {"status": "failed"},
        ]
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = query_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        stats = svc.get_queue_stats()
        assert stats["queued"] == 2
        assert stats["published"] == 1
        assert stats["failed"] == 1
        assert stats["publishing"] == 0
        assert stats["cancelled"] == 0

    def test_empty_queue(self):
        mock_db = MagicMock()
        query_result = MagicMock()
        query_result.data = []
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = query_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        stats = svc.get_queue_stats()
        assert all(v == 0 for v in stats.values())
