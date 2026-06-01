"""Tests for the creative_deep_analysis auto-chain fix.

The auto-chain (run deep analysis after ad classification) was dead from
2026-03-30 until this fix: it built a synthetic job with id="chain_<uuid>"
and called the handler inline, which always failed (invalid-UUID run insert,
later a claim-path assert). The fix replaces that with
_enqueue_creative_deep_analysis_chain(), which inserts a REAL one-time
scheduled_jobs row for the brand so the worker pool claims it normally.

These tests are mock-based; they assert the enqueue shape, the dedup guard,
and that no constraint-violating fields are sent.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_db_with_no_pending():
    """A fake supabase client whose dedup SELECT returns no pending job."""
    db = MagicMock()
    # The dedup query chain: .table().select().eq().eq().eq().not_.is_().limit().execute()
    select_chain = db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    select_chain.not_.is_.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    # The insert chain: .table().insert().execute()
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "new-job-id"}])
    return db


def _make_db_with_pending():
    """A fake supabase client whose dedup SELECT returns an existing pending job."""
    db = MagicMock()
    select_chain = db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    select_chain.not_.is_.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "already-pending-job"}]
    )
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "should-not-be-called"}])
    return db


class TestEnqueueDeepAnalysisChain:

    def test_enqueues_real_job_when_none_pending(self):
        from viraltracker.worker import scheduler_worker as sw
        db = _make_db_with_no_pending()
        with patch.object(sw, "get_supabase_client", return_value=db):
            result = sw._enqueue_creative_deep_analysis_chain("brand-123")
        assert result is True
        # An insert into scheduled_jobs happened.
        db.table.return_value.insert.assert_called_once()
        inserted = db.table.return_value.insert.call_args[0][0]
        assert inserted["job_type"] == "creative_deep_analysis"
        assert inserted["brand_id"] == "brand-123"
        assert inserted["schedule_type"] == "one_time"
        assert inserted["status"] == "active"
        assert inserted["next_run_at"]  # set
        # product_id deliberately omitted (nullable column).
        assert "product_id" not in inserted
        # Provenance marker lives in parameters, NOT trigger_source (CHECK constraint).
        assert "trigger_source" not in inserted
        assert inserted["parameters"]["chained_from"] == "ad_classification"
        # Default analysis params present.
        assert inserted["parameters"]["max_images"] == 50
        assert inserted["parameters"]["max_videos"] == 20
        assert inserted["parameters"]["days_back"] == 60

    def test_dedup_skips_when_pending_exists(self):
        from viraltracker.worker import scheduler_worker as sw
        db = _make_db_with_pending()
        with patch.object(sw, "get_supabase_client", return_value=db):
            result = sw._enqueue_creative_deep_analysis_chain("brand-123")
        assert result is False
        # No insert when a pending job already exists.
        db.table.return_value.insert.assert_not_called()

    def test_returns_false_on_empty_brand_id(self):
        from viraltracker.worker import scheduler_worker as sw
        # No DB call at all when brand_id is falsy.
        with patch.object(sw, "get_supabase_client") as gsc:
            result = sw._enqueue_creative_deep_analysis_chain("")
        assert result is False
        gsc.assert_not_called()

    def test_custom_params_override_defaults(self):
        from viraltracker.worker import scheduler_worker as sw
        db = _make_db_with_no_pending()
        with patch.object(sw, "get_supabase_client", return_value=db):
            sw._enqueue_creative_deep_analysis_chain("brand-x", {"max_images": 10, "days_back": 7})
        inserted = db.table.return_value.insert.call_args[0][0]
        assert inserted["parameters"]["max_images"] == 10
        assert inserted["parameters"]["days_back"] == 7
        # Untouched default still present.
        assert inserted["parameters"]["max_videos"] == 20

    def test_insert_failure_is_non_fatal(self):
        from viraltracker.worker import scheduler_worker as sw
        db = _make_db_with_no_pending()
        db.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")
        with patch.object(sw, "get_supabase_client", return_value=db):
            # Must not raise — the chain is a non-fatal side effect of classification.
            result = sw._enqueue_creative_deep_analysis_chain("brand-123")
        assert result is False

    def test_no_synthetic_chain_id_remains_in_source(self):
        """Regression guard: the broken 'chain_<uuid>' inline-call pattern must
        not come back. If someone re-adds a direct execute_creative_deep_analysis_job
        call from the classification handler, this fails."""
        from pathlib import Path
        src = Path("viraltracker/worker/scheduler_worker.py").read_text()
        assert "chain_{job_id}" not in src
        assert "await execute_creative_deep_analysis_job(" not in src


class TestDeepAnalysisHandlerCompletesOneTimeJob:
    """The chained job is a one_time scheduled_jobs row. After the deep-analysis
    handler runs it, the parent row MUST be marked completed (not left as a
    zombie 'active' row). This guards the _update_job_next_run wiring added
    alongside the chain fix."""

    @pytest.mark.asyncio
    async def test_one_time_job_marked_completed(self):
        from unittest.mock import AsyncMock
        from viraltracker.worker import scheduler_worker as sw

        # A claimed one_time deep-analysis job (the shape _dispatch_claimed_job
        # hands to the handler).
        job = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Auto Deep Analysis — abc",
            "brand_id": "22222222-2222-2222-2222-222222222222",
            "parameters": {"max_images": 50, "max_videos": 20, "days_back": 60},
            "schedule_type": "one_time",
            "trigger_source": "scheduled",
            "runs_completed": 0,
            "_claimed": True,
            "_run_id": "33333333-3333-3333-3333-333333333333",
        }

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": "44444444-4444-4444-4444-444444444444"}]
        )

        img = MagicMock()
        img.analyze_batch.return_value = {"analyzed": 3, "skipped": 0, "errors": 0}
        vid = MagicMock()
        vid.analyze_batch = AsyncMock(return_value={"analyzed": 1, "skipped": 0, "errors": 0})
        corr = MagicMock()
        corr.compute_correlations.return_value = {"correlations": 2}

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch("viraltracker.services.image_analysis_service.ImageAnalysisService", return_value=img), \
             patch("viraltracker.services.video_analysis_service.VideoAnalysisService", return_value=vid), \
             patch("viraltracker.services.creative_correlation_service.CreativeCorrelationService", return_value=corr), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "update_job") as upd_job:
            result = await sw.execute_creative_deep_analysis_job(job)

        assert result["success"] is True
        # Run row marked completed.
        assert any(c.args[1].get("status") == "completed" for c in upd_run.call_args_list)
        # Parent job marked completed (the zombie-row fix). update_job is called
        # by _update_job_next_run with status='completed' for a one_time job.
        job_status_updates = [c.args[1] for c in upd_job.call_args_list if "status" in c.args[1]]
        assert job_status_updates, "expected update_job to set a status (zombie-row fix not wired)"
        assert any(u["status"] == "completed" for u in job_status_updates)

    @pytest.mark.asyncio
    async def test_recurring_job_rearms_and_not_completed(self):
        """Guard the inline -> _update_job_next_run swap doesn't regress the
        recurring path. A recurring deep-analysis job must get its next_run_at
        re-armed from cron and must NOT be marked completed."""
        from unittest.mock import AsyncMock
        from viraltracker.worker import scheduler_worker as sw

        job = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Recurring Deep Analysis",
            "brand_id": "22222222-2222-2222-2222-222222222222",
            "parameters": {"max_images": 50, "max_videos": 20, "days_back": 60},
            "schedule_type": "recurring",
            "cron_expression": "0 8 * * *",  # daily at 8am (a format calculate_next_run supports)
            "trigger_source": "scheduled",
            "runs_completed": 0,
            "_claimed": True,
            "_run_id": "33333333-3333-3333-3333-333333333333",
        }

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": "44444444-4444-4444-4444-444444444444"}]
        )
        img = MagicMock()
        img.analyze_batch.return_value = {"analyzed": 1, "skipped": 0, "errors": 0}
        vid = MagicMock()
        vid.analyze_batch = AsyncMock(return_value={"analyzed": 0, "skipped": 0, "errors": 0})
        corr = MagicMock()
        corr.compute_correlations.return_value = {"correlations": 0}

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch("viraltracker.services.image_analysis_service.ImageAnalysisService", return_value=img), \
             patch("viraltracker.services.video_analysis_service.VideoAnalysisService", return_value=vid), \
             patch("viraltracker.services.creative_correlation_service.CreativeCorrelationService", return_value=corr), \
             patch.object(sw, "update_job_run"), \
             patch.object(sw, "update_job") as upd_job:
            result = await sw.execute_creative_deep_analysis_job(job)

        assert result["success"] is True
        job_updates = [c.args[1] for c in upd_job.call_args_list]
        assert job_updates, "expected update_job to be called"
        # Recurring job: re-armed with a next_run_at, NOT marked completed.
        assert any(u.get("next_run_at") for u in job_updates), \
            "recurring job should have next_run_at re-armed from cron"
        assert not any(u.get("status") == "completed" for u in job_updates), \
            "recurring job must NOT be marked completed"
