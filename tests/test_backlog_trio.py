"""Backlog trio: SIGTERM run hygiene, async video path, has_product_placement.

1. Shutdown hygiene: handle_shutdown marks THIS boot's running runs failed
   (scoped by worker_id prefix) so deploy kills don't leave zombies that hold a
   job type's concurrency slot for hours.
2. Video path: deep_analyze_video's sync SDK calls run via to_thread /
   asyncio.sleep — the event loop is never blocked (source-level assertion,
   mirroring the PR #290 image-path fix).
3. has_product_placement: layout attribute orthogonal to awareness — prompt
   contract, parse-time bool coercion (absent/garbage -> None, never a
   fabricated False), and the get_templates filter.

Run with: pytest tests/test_backlog_trio.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 1. SIGTERM hygiene
# ---------------------------------------------------------------------------
class TestShutdownHygiene:
    def test_fail_runs_scoped_to_this_boot_and_running_only(self):
        from viraltracker.worker import scheduler_worker as sw
        from viraltracker.worker.scheduler_concurrency import boot_id

        db = MagicMock()
        with patch.object(sw, "get_supabase_client", return_value=db):
            sw._fail_runs_for_this_boot()

        db.table.assert_called_once_with("scheduled_job_runs")
        update_payload = db.table.return_value.update.call_args[0][0]
        assert update_payload["status"] == "failed"
        assert "shutdown" in update_payload["error_message"]
        like = db.table.return_value.update.return_value.like
        like.assert_called_once_with("worker_id", f"{boot_id()}:%")
        like.return_value.eq.assert_called_once_with("status", "running")

    def test_handle_shutdown_spawns_hygiene_off_signal_frame_and_sets_flag(self):
        from viraltracker.worker import scheduler_worker as sw

        class _SyncThread:  # run the target inline so the assertion is deterministic
            def __init__(self, target=None, **kw):
                self._target = target
                assert kw.get("daemon") is True, "hygiene thread must be daemon"
            def start(self):
                self._target()

        with patch.object(sw, "_fail_runs_for_this_boot") as hygiene, \
             patch.object(sw.threading, "Thread", _SyncThread):
            sw.handle_shutdown(15, None)
        hygiene.assert_called_once()
        assert sw.shutdown_requested is True
        sw.shutdown_requested = False  # reset module state for other tests

    def test_hygiene_rearms_parent_jobs(self):
        # Job handlers NULL next_run_at at start and claim_next_job requires it
        # NOT NULL — without the re-arm, a deploy-killed job is permanently dead.
        from viraltracker.worker import scheduler_worker as sw
        db = MagicMock()
        runs_update = db.table.return_value.update.return_value.like.return_value.eq.return_value
        runs_update.execute.return_value = MagicMock(
            data=[{"id": "r1", "scheduled_job_id": "j1"}, {"id": "r2", "scheduled_job_id": "j2"}]
        )
        with patch.object(sw, "get_supabase_client", return_value=db):
            sw._fail_runs_for_this_boot()
        rearm_in = db.table.return_value.update.return_value.in_
        rearm_in.assert_called_once()
        assert sorted(rearm_in.call_args.args[1]) == ["j1", "j2"]

    def test_hygiene_never_raises(self):
        from viraltracker.worker import scheduler_worker as sw
        with patch.object(sw, "get_supabase_client", side_effect=RuntimeError("db down")):
            sw._fail_runs_for_this_boot()  # must swallow — shutdown path can't crash


# ---------------------------------------------------------------------------
# 2. Video path: no blocking SDK calls left in deep_analyze_video
# ---------------------------------------------------------------------------
class TestVideoPathAsync:
    def test_no_bare_sync_sdk_calls_in_source(self):
        from viraltracker.services import video_analysis_service as vas
        src = inspect.getsource(vas)
        assert "time_module.sleep(3)" not in src, "poll loop must use asyncio.sleep"
        # Flag only DIRECT invocations (open paren) — a bare function reference
        # passed to to_thread(...) on the preceding line is the fixed form.
        for call in ("client.files.upload(", "client.files.get(",
                     "client.models.generate_content(", "client.files.delete("):
            for line in src.splitlines():
                if call in line and "to_thread" not in line:
                    raise AssertionError(
                        f"blocking SDK call not wrapped in to_thread: {line.strip()!r} "
                        "— this freezes the event loop and serializes "
                        "CLASSIFIER_MAX_CONCURRENCY (see PR #290)"
                    )


# ---------------------------------------------------------------------------
# 3. has_product_placement
# ---------------------------------------------------------------------------
from viraltracker.services.template_queue_service import (
    TemplateQueueService,
    TEMPLATE_ANALYSIS_PROMPT,
)


def _service_with_image():
    svc = TemplateQueueService.__new__(TemplateQueueService)
    svc.supabase = MagicMock()
    svc.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "q1", "asset_id": "a1",
            "scraped_ad_assets": {"storage_path": "bucket/p.jpg", "asset_type": "image"},
            "facebook_ads": {"page_name": "Brand", "link_url": "https://x"},
        }]
    )
    svc.supabase.storage.from_.return_value.download.return_value = b"imagebytes"
    return svc


def _run_analyze(gemini_text):
    svc = _service_with_image()
    fake_gemini = MagicMock()
    fake_gemini.analyze_image_async = AsyncMock(return_value=gemini_text)
    return asyncio.run(svc.analyze_template_for_approval("q1", gemini=fake_gemini))


class TestProductPlacement:
    def test_prompt_contract(self):
        assert '"has_product_placement"' in TEMPLATE_ANALYSIS_PROMPT
        assert "corner signature" in TEMPLATE_ANALYSIS_PROMPT
        assert "INDEPENDENT of" in TEMPLATE_ANALYSIS_PROMPT  # orthogonality stated

    def test_true_false_pass_through(self):
        for val in (True, False):
            out = _run_analyze(json.dumps({
                "awareness_level": "problem_aware", "has_product_placement": val,
            }))
            assert out["has_product_placement"] is val

    def test_garbage_or_absent_is_none_not_false(self):
        out = _run_analyze(json.dumps({
            "awareness_level": "problem_aware", "has_product_placement": "yes",
        }))
        assert out["has_product_placement"] is None
        out = _run_analyze(json.dumps({"awareness_level": "problem_aware"}))
        assert out["has_product_placement"] is None

    def test_get_templates_filter(self):
        svc = TemplateQueueService.__new__(TemplateQueueService)
        svc.supabase = MagicMock()
        query = svc.supabase.table.return_value.select.return_value
        for m in ("eq", "order", "limit", "ilike"):
            getattr(query, m).return_value = query
        query.execute.return_value = MagicMock(data=[])
        svc.get_templates(awareness_level=2, has_product_placement=True)
        assert (("has_product_placement", True) in
                [c.args for c in query.eq.call_args_list]), "filter must reach the query"
        svc.get_templates(awareness_level=2)  # None must NOT filter
        assert ([c for c in query.eq.call_args_list if c.args[0] == "has_product_placement"]
                .__len__() == 1)
