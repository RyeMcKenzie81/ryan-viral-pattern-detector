"""Unit tests for viraltracker.worker.scheduler_concurrency.

PR 1 of 2 scope: covers the building blocks of the new claim/dispatch/worker
pool. Mock-only — no real DB. The advisory-lock SQL behavior was already
verified end-to-end via /tmp/smoke_supabase_rpc_lock.py (PASS, 2026-05-28).

PR 2 will add wired-up integration tests for run_scheduler at pool>1.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from viraltracker.worker import scheduler_concurrency as sc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Snapshot module-level mutable state, install a clean copy for the
    test, then restore the original. Without restore, JOB_HANDLERS.clear()
    here would empty the registry that test_scheduler_registry.py expects
    to be populated by the scheduler_worker import.

    Also rebinds shutdown_requested to a fresh asyncio.Event per test —
    asyncio.Event binds to a loop on first use, and pytest-asyncio creates
    a new loop per test, so reusing the Event trips "bound to a different
    event loop" on the second test."""
    import sys
    saved_handlers = dict(sc.JOB_HANDLERS)
    saved_event = sc.shutdown_requested
    sc.JOB_HANDLERS.clear()
    sc._SATURATED.pairs.clear()
    sc._CAP_CACHE.last_fetched = 0.0
    sc._CAP_CACHE.last_global_cap = None
    sys.modules[sc.__name__].shutdown_requested = asyncio.Event()
    try:
        yield
    finally:
        sc.JOB_HANDLERS.clear()
        sc.JOB_HANDLERS.update(saved_handlers)
        sys.modules[sc.__name__].shutdown_requested = saved_event


@pytest.fixture
def mock_db():
    """Fake supabase client with a chainable .rpc().execute() shape."""
    db = MagicMock()
    db.rpc.return_value.execute.return_value = MagicMock(data=[])
    return db


def _claim_payload(**overrides):
    """Build a fake claim_next_job RPC return row."""
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
        "counts_global": 0,
        "counts_job_type": 0,
        "counts_brand": 0,
        "counts_brand_jt": 0,
        "cap_global": 8,
        "cap_job_type": 4,
        "cap_brand": 3,
        "cap_brand_jt": 4,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# JOB_HANDLERS registry
# ===========================================================================

class TestJobHandlersRegistry:

    def test_register_populates_dict(self):
        @sc.register_job_handler("test_job_type")
        def handler(job):
            return {"ok": True}
        assert sc.JOB_HANDLERS["test_job_type"] is handler

    def test_duplicate_registration_raises(self):
        @sc.register_job_handler("dupe")
        def first(job): return None
        with pytest.raises(RuntimeError, match="Duplicate handler"):
            @sc.register_job_handler("dupe")
            def second(job): return None

    def test_re_decorating_same_function_is_idempotent(self):
        """Re-importing the module shouldn't fail even though the decorator
        runs again with the same function object."""
        @sc.register_job_handler("idempo")
        def handler(job): return None
        # Simulate re-import: same function pointer.
        # The decorator detects this via identity check and is a no-op.
        sc.register_job_handler("idempo")(handler)
        assert sc.JOB_HANDLERS["idempo"] is handler

    def test_dispatch_returns_registered_handler(self):
        @sc.register_job_handler("dispatched")
        def handler(job): return "ran"
        assert sc.dispatch_job("dispatched") is handler

    def test_dispatch_unknown_raises_clear_keyerror(self):
        @sc.register_job_handler("only_known")
        def h(job): return None
        with pytest.raises(KeyError) as ei:
            sc.dispatch_job("not_a_real_job_type")
        # Error must name what IS registered, not just what's missing.
        # This is the contract: a clearer signal than the current silent-elif.
        assert "not_a_real_job_type" in str(ei.value)
        assert "only_known" in str(ei.value)


# ===========================================================================
# Worker ID
# ===========================================================================

class TestWorkerId:

    def test_make_worker_id_includes_boot_id(self):
        wid = sc.make_worker_id(0)
        assert wid.startswith(sc.boot_id())
        assert wid.endswith(":0")

    def test_different_slots_produce_distinct_ids(self):
        assert sc.make_worker_id(0) != sc.make_worker_id(1)

    def test_boot_id_is_stable_within_process(self):
        # Two calls in the same process must agree. Across process restarts
        # the boot_id changes — that's the whole point.
        assert sc.boot_id() == sc.boot_id()


# ===========================================================================
# Saturated-pair LRU (starvation guard)
# ===========================================================================

class TestSaturatedRegistry:

    @pytest.mark.asyncio
    async def test_marked_pair_is_saturated(self):
        reg = sc._SaturatedRegistry()
        await reg.mark("brand-X", "template_scrape", ttl=10)
        assert await reg.is_saturated("brand-X", "template_scrape") is True

    @pytest.mark.asyncio
    async def test_unmarked_pair_is_not_saturated(self):
        reg = sc._SaturatedRegistry()
        assert await reg.is_saturated("brand-Y", "ad_creation") is False

    @pytest.mark.asyncio
    async def test_expired_entry_is_pruned_on_check(self):
        reg = sc._SaturatedRegistry()
        await reg.mark("brand-X", "ad_creation", ttl=0.05)
        await asyncio.sleep(0.1)
        assert await reg.is_saturated("brand-X", "ad_creation") is False
        # And the entry is gone after the check.
        assert ("brand-X", "ad_creation") not in reg.pairs

    @pytest.mark.asyncio
    async def test_prune_drops_expired_only(self):
        reg = sc._SaturatedRegistry()
        await reg.mark("brand-fresh", "jt", ttl=10)
        await reg.mark("brand-stale", "jt", ttl=0.01)
        await asyncio.sleep(0.05)
        n = await reg.prune()
        assert n == 1
        assert ("brand-fresh", "jt") in reg.pairs
        assert ("brand-stale", "jt") not in reg.pairs


# ===========================================================================
# claim_next_job wrapper
# ===========================================================================

class TestClaimNextJobWrapper:

    @pytest.mark.asyncio
    async def test_returns_payload_when_rpc_returns_row(self, mock_db):
        payload = _claim_payload(job_type="scorecard")
        mock_db.rpc.return_value.execute.return_value = MagicMock(data=[payload])
        result = await sc.claim_next_job(mock_db, "worker-test:0")
        assert result is not None
        assert result["job_type"] == "scorecard"
        # The wrapper called the right RPC name with the worker_id_text arg.
        mock_db.rpc.assert_called_once_with(
            "claim_next_job", {"worker_id_text": "worker-test:0"}
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_rpc_returns_empty(self, mock_db):
        mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
        result = await sc.claim_next_job(mock_db, "worker-test:0")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_rpc_exception(self, mock_db):
        # The wrapper logs and returns None — a worker should keep trying
        # on transient DB hiccups, not crash.
        mock_db.rpc.return_value.execute.side_effect = RuntimeError("boom")
        result = await sc.claim_next_job(mock_db, "worker-test:0")
        assert result is None


# ===========================================================================
# worker_loop
# ===========================================================================

class TestWorkerLoop:

    @pytest.mark.asyncio
    async def test_loop_exits_on_shutdown_request(self, mock_db):
        """worker_loop must exit promptly when shutdown_requested is set,
        even mid-idle-backoff."""
        import sys
        sys.modules[sc.__name__].shutdown_requested.set()
        executed = []

        async def execute_fn(claimed):
            executed.append(claimed)

        t0 = time.monotonic()
        await sc.worker_loop(
            mock_db, slot=0, execute_fn=execute_fn,
            poll_idle_seconds=10,  # would block 10s if shutdown weren't honored
        )
        elapsed = time.monotonic() - t0
        # Should be near-instant; well under the 10s backoff.
        assert elapsed < 1.0
        assert executed == []  # no work was claimed

    @pytest.mark.asyncio
    async def test_loop_dispatches_claimed_work_then_exits(self, mock_db):
        import sys
        payload = _claim_payload(job_type="meta_sync")
        # First call returns a claim; second call returns nothing; then we shut down.
        mock_db.rpc.return_value.execute.side_effect = [
            MagicMock(data=[payload]),
            MagicMock(data=[]),
        ]
        executed = []

        async def execute_fn(claimed):
            executed.append(claimed)
            sys.modules[sc.__name__].shutdown_requested.set()

        await sc.worker_loop(
            mock_db, slot=2, execute_fn=execute_fn,
            poll_idle_seconds=0.05,
        )
        assert len(executed) == 1
        assert executed[0]["job_type"] == "meta_sync"

    @pytest.mark.asyncio
    async def test_loop_swallows_execute_exceptions(self, mock_db):
        """If execute_fn raises, the worker logs and keeps going; a single
        broken job must not take the whole worker down."""
        import sys
        payload = _claim_payload(job_type="meta_sync")
        mock_db.rpc.return_value.execute.return_value = MagicMock(data=[payload])

        call_count = {"n": 0}

        async def execute_fn(claimed):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                sys.modules[sc.__name__].shutdown_requested.set()
            raise ValueError("simulated job failure")

        # Should NOT raise out of worker_loop.
        await sc.worker_loop(
            mock_db, slot=0, execute_fn=execute_fn,
            poll_idle_seconds=0.05,
        )
        # Both attempts ran; the exception didn't kill the loop after the first.
        assert call_count["n"] >= 2


# ===========================================================================
# recovery_loop
# ===========================================================================

class TestRecoveryLoop:

    @pytest.mark.asyncio
    async def test_calls_recover_rpc_then_exits_on_shutdown(self, mock_db):
        mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])

        async def stop_soon():
            await asyncio.sleep(0.05)
            sc.shutdown_requested.set()

        await asyncio.gather(
            sc.recovery_loop(
                mock_db,
                interval_seconds=0.01,
                jitter_max_seconds=0.0,  # deterministic for the test
            ),
            stop_soon(),
        )
        # The recovery RPC was called at least once.
        called_names = [c.args[0] for c in mock_db.rpc.call_args_list]
        assert "recover_stuck_runs_v2" in called_names

    @pytest.mark.asyncio
    async def test_logs_warning_on_recoveries_but_does_not_raise(self, mock_db, caplog):
        # Simulate the RPC returning one recovered row.
        mock_db.rpc.return_value.execute.return_value = MagicMock(
            data=[{"recovered_run_id": "abc", "recovered_job_id": "def",
                   "job_type": "template_scrape", "runtime_seconds": 14500.0}]
        )

        async def stop_soon():
            await asyncio.sleep(0.05)
            sc.shutdown_requested.set()

        with caplog.at_level("WARNING"):
            await asyncio.gather(
                sc.recovery_loop(
                    mock_db, interval_seconds=0.01, jitter_max_seconds=0.0
                ),
                stop_soon(),
            )

        assert any("recovery_loop reset" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_extra_sweep_runs_and_errors_contained(self, mock_db):
        """The worker injects heal_orphaned_recurring_jobs as extra_sweep —
        it must run each tick, and a sweep exception must not kill the loop."""
        mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
        calls = {"n": 0}

        def sweep():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("sweep boom")  # first tick fails — loop survives
            return []

        async def stop_soon():
            await asyncio.sleep(0.08)
            sc.shutdown_requested.set()

        await asyncio.gather(
            sc.recovery_loop(
                mock_db, interval_seconds=0.01, jitter_max_seconds=0.0,
                extra_sweep=sweep,
            ),
            stop_soon(),
        )
        # Sweep ran at least twice: the failing tick did not end the loop.
        assert calls["n"] >= 2


# ============================================================================
# run_coroutine_in_thread — thread-per-job dispatch (starvation fix)
# ============================================================================

class TestRunCoroutineInThread:
    """Job handlers do sync work inside async-def; on a shared loop that
    starves every other slot/timer (verified live 2026-06-09). These prove the
    thread-per-job primitive actually fixes it."""

    @pytest.mark.asyncio
    async def test_sync_blocking_handlers_run_in_parallel(self):
        """Two handlers that BLOCK (time.sleep) must overlap — on a shared
        loop they would serialize (>=0.7s); in threads they take ~0.35s."""
        import time as _t
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        async def blocking_handler(_job):
            _t.sleep(0.35)  # sync block, like a Supabase/Gemini call
            return "done"

        start = _t.monotonic()
        r1, r2 = await asyncio.gather(
            run_coroutine_in_thread(blocking_handler, {"id": 1}),
            run_coroutine_in_thread(blocking_handler, {"id": 2}),
        )
        elapsed = _t.monotonic() - start
        assert (r1, r2) == ("done", "done")
        assert elapsed < 0.6, f"handlers serialized ({elapsed:.2f}s) — loop still starved"

    @pytest.mark.asyncio
    async def test_event_loop_stays_responsive_during_sync_block(self):
        """While a handler sync-blocks in its thread, a timer on the MAIN loop
        must fire promptly — this is the recovery-loop/claim-loop guarantee."""
        import time as _t
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        async def blocking_handler(_job):
            _t.sleep(0.5)

        task = asyncio.create_task(run_coroutine_in_thread(blocking_handler, {}))
        start = _t.monotonic()
        await asyncio.sleep(0.05)  # would wait the full 0.5s on a starved loop
        timer_latency = _t.monotonic() - start
        await task
        assert timer_latency < 0.25, f"main loop starved: timer took {timer_latency:.2f}s"

    @pytest.mark.asyncio
    async def test_exception_propagates_to_awaiter(self):
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        async def failing_handler(_job):
            raise ValueError("handler blew up")

        with pytest.raises(ValueError, match="handler blew up"):
            await run_coroutine_in_thread(failing_handler, {})

    @pytest.mark.asyncio
    async def test_thread_is_daemon_and_named(self):
        """Daemon so SIGTERM drain-timeout can exit the process behind an
        hours-long job (recover_stuck_runs_v2 picks up the orphan next boot)."""
        import threading as _th
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        seen = {}

        async def introspect_handler(_job):
            t = _th.current_thread()
            seen["daemon"] = t.daemon
            seen["name"] = t.name

        await run_coroutine_in_thread(introspect_handler, {}, name="job-test-abc")
        assert seen["daemon"] is True
        assert seen["name"] == "job-test-abc"

    @pytest.mark.asyncio
    async def test_handler_gets_its_own_event_loop(self):
        """asyncio primitives inside the handler must work (own loop), and it
        must NOT be the caller's loop."""
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        caller_loop = asyncio.get_running_loop()

        async def loop_handler(_job):
            await asyncio.sleep(0.01)  # asyncio works in the thread's loop
            return asyncio.get_running_loop() is not caller_loop

        assert await run_coroutine_in_thread(loop_handler, {}) is True

    @pytest.mark.asyncio
    async def test_handler_cancelled_error_becomes_failure(self):
        """A CancelledError raised INSIDE the handler's own loop must surface
        as a normal failure (RuntimeError) so the dispatcher's
        `except Exception` marks the run failed + reschedules — re-raising it
        raw would bypass cleanup and kill the worker task (codex finding)."""
        from viraltracker.worker.scheduler_concurrency import run_coroutine_in_thread

        async def cancelling_handler(_job):
            raise asyncio.CancelledError()

        with pytest.raises(RuntimeError, match="CancelledError internally"):
            await run_coroutine_in_thread(cancelling_handler, {}, name="job-x")
