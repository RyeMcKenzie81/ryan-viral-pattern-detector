"""Tests for the PR 2 worker pool wiring in scheduler_worker.py.

Covers:
  - _dispatch_claimed_job() orchestration (fetch + emit + handler call).
  - Handlers fail loudly when called outside the claim path (the assert).
  - Dispatcher exceptions are caught and marked-failed (no worker crash).
  - SCHEDULER_POOL_SIZE default in scheduler_concurrency.

Mock-based. The real claim_next_job RPC behavior was verified end-to-end
against Supabase via /tmp/smoke_supabase_rpc_lock.py (PASS, 2026-05-28).
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from viraltracker.worker import scheduler_concurrency as sc


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Save/restore the registry and rebind the asyncio.Event per test, same
    pattern as test_scheduler_concurrency.py."""
    saved_handlers = dict(sc.JOB_HANDLERS)
    saved_event = sc.shutdown_requested
    sys.modules[sc.__name__].shutdown_requested = asyncio.Event()
    sc._SATURATED.pairs.clear()
    try:
        yield
    finally:
        sc.JOB_HANDLERS.clear()
        sc.JOB_HANDLERS.update(saved_handlers)
        sys.modules[sc.__name__].shutdown_requested = saved_event


def _claim_payload(**overrides):
    payload = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "job_name": "test job",
        "job_type": "meta_sync",
        "brand_id": "33333333-3333-3333-3333-333333333333",
        "product_id": None,
        "parameters": {},
        "started_at": "2026-05-28T20:00:00+00:00",
        "attempt_number": 1,
        "counts_global": 0, "counts_job_type": 0,
        "counts_brand": 0, "counts_brand_jt": 0,
        "cap_global": 8, "cap_job_type": 4,
        "cap_brand": 3, "cap_brand_jt": 4,
    }
    payload.update(overrides)
    return payload


class TestPoolSizeDefault:

    def test_default_is_2(self, monkeypatch):
        """User chose pool=2 as the conservative initial bump in PR 2."""
        # Reload the module under a clean env to read the default.
        monkeypatch.delenv("SCHEDULER_POOL_SIZE", raising=False)
        import importlib
        reloaded = importlib.reload(sc)
        assert reloaded.DEFAULT_POOL_SIZE == 2

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_POOL_SIZE", "5")
        import importlib
        reloaded = importlib.reload(sc)
        assert reloaded.DEFAULT_POOL_SIZE == 5


class TestDispatchClaimedJob:
    """Cover the _dispatch_claimed_job helper in scheduler_worker.py.

    Imported lazily to avoid pulling scheduler_worker into module-load
    if a test file is collected independently."""

    @pytest.mark.asyncio
    async def test_threads_claim_markers_to_handler(self):
        from viraltracker.worker import scheduler_worker as sw

        received = []

        async def fake_handler(job):
            received.append(job)
            return {"ok": True}

        # Stash a fake handler in the registry just for this test.
        sc.JOB_HANDLERS["meta_sync"] = fake_handler

        fake_db = MagicMock()
        # _fetch_full_job query
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "22222222-2222-2222-2222-222222222222", "job_type": "meta_sync", "name": "test job", "brand_id": "33333333-3333-3333-3333-333333333333"}]
        )

        with patch.object(sw, "_emit_job_started_event") as emit_mock:
            await sw._dispatch_claimed_job(fake_db, _claim_payload())

        assert len(received) == 1
        # The handler MUST see the claim markers — proves the contract that
        # the swept assert in each execute_*_job will pass.
        assert received[0]["_claimed"] is True
        assert received[0]["_run_id"] == "11111111-1111-1111-1111-111111111111"
        assert received[0]["_attempt_number"] == 1
        emit_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_job_marks_run_failed_and_returns(self):
        """If the parent scheduled_jobs row was deleted between claim and
        dispatch, mark the run failed and bail — don't try to dispatch
        against a None job dict."""
        from viraltracker.worker import scheduler_worker as sw

        fake_db = MagicMock()
        # _fetch_full_job finds nothing.
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        with patch.object(sw, "update_job_run") as upd:
            await sw._dispatch_claimed_job(fake_db, _claim_payload())

        upd.assert_called_once()
        # Should have been called with status='failed' and a descriptive message.
        call_args = upd.call_args
        # call_args[0] = positional args; call_args[1] = kwargs
        # update_job_run(run_id, updates_dict) — updates_dict is positional[1]
        updates = call_args[0][1] if len(call_args[0]) >= 2 else call_args[1]
        assert updates["status"] == "failed"
        assert "not found" in updates["error_message"].lower()

    @pytest.mark.asyncio
    async def test_handler_exception_marks_run_failed_and_reschedules(self):
        """If the handler raises, _dispatch_claimed_job must mark the run
        failed and call _reschedule_after_failure. A single bad handler
        MUST NOT crash the worker."""
        from viraltracker.worker import scheduler_worker as sw

        async def boom(job):
            raise ValueError("simulated handler failure")

        sc.JOB_HANDLERS["meta_sync"] = boom

        fake_db = MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "22222222-2222-2222-2222-222222222222", "job_type": "meta_sync",
                   "name": "test job", "brand_id": "33333333-3333-3333-3333-333333333333",
                   "schedule_type": "one_time"}]
        )

        with patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "_reschedule_after_failure") as resched, \
             patch.object(sw, "_emit_job_started_event"):
            # Should NOT raise — that's the contract.
            await sw._dispatch_claimed_job(fake_db, _claim_payload())

        upd_run.assert_called()
        resched.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_job_type_raises_clear_error_inside_dispatcher(self):
        """A claim for a job_type without a registered handler hits the
        dispatcher KeyError. _dispatch_claimed_job catches that and marks
        the run failed — no worker crash, no silent fallthrough."""
        from viraltracker.worker import scheduler_worker as sw

        # JOB_HANDLERS is empty (autouse fixture cleared it for this test).
        # Confirm.
        assert "completely_unknown_type" not in sc.JOB_HANDLERS

        fake_db = MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "22222222-2222-2222-2222-222222222222", "job_type": "completely_unknown_type",
                   "name": "test", "brand_id": "33333333-3333-3333-3333-333333333333",
                   "schedule_type": "one_time"}]
        )

        with patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "_reschedule_after_failure"), \
             patch.object(sw, "_emit_job_started_event"):
            await sw._dispatch_claimed_job(
                fake_db,
                _claim_payload(job_type="completely_unknown_type"),
            )

        upd_run.assert_called()


class TestClaimAssertionAtHandlerEntry:
    """Each of the 32 swept execute_*_job functions has:

        assert job.get('_claimed'), "...claim_next_job..."

    Spot-check that the contract is enforceable: calling an execute_*_job
    with a non-claimed job dict raises AssertionError BEFORE any side
    effects (DB writes, network calls, etc.). This is the safety net for
    future contributors who try to call execute_X_job() directly."""

    @pytest.mark.asyncio
    async def test_meta_sync_asserts_pre_claimed(self):
        from viraltracker.worker.scheduler_worker import execute_meta_sync_job
        bad_job = {
            "id": "x", "name": "test", "brand_id": "y",
            "products": None, "brands": {"name": "Test"},
            "parameters": {},
            # _claimed deliberately omitted
        }
        with pytest.raises(AssertionError, match="claim_next_job"):
            await execute_meta_sync_job(bad_job)

    @pytest.mark.asyncio
    async def test_template_scrape_asserts_pre_claimed(self):
        from viraltracker.worker.scheduler_worker import execute_template_scrape_job
        bad_job = {
            "id": "x", "name": "test", "brand_id": "y",
            "products": None, "brands": {"name": "Test"},
            "parameters": {},
        }
        with pytest.raises(AssertionError, match="claim_next_job"):
            await execute_template_scrape_job(bad_job)

    @pytest.mark.asyncio
    async def test_ad_creation_v2_asserts_pre_claimed(self):
        from viraltracker.worker.scheduler_worker import execute_ad_creation_v2_job
        bad_job = {
            "id": "x", "name": "test", "product_id": "p",
            "products": {"id": "p", "name": "P", "brand_id": "b", "brands": {}},
            "parameters": {},
        }
        with pytest.raises(AssertionError, match="claim_next_job"):
            await execute_ad_creation_v2_job(bad_job)
