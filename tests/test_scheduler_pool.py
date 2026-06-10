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

    @pytest.mark.asyncio
    async def test_missing_job_transient_fetch_reschedules(self):
        """_fetch_full_job returns None on ANY exception (transient blip), not
        only a deleted row. The claim already cleared next_run_at, so bailing
        without a reschedule kills a recurring job permanently (killed
        seo_publish on 2026-06-05 after 2,725 runs). The fix retries a minimal
        fetch and reschedules when the row exists."""
        from viraltracker.worker import scheduler_worker as sw

        job_row = {
            "id": "22222222-2222-2222-2222-222222222222",
            "job_type": "seo_publish",
            "schedule_type": "recurring",
            "cron_expression": "*/30 * * * *",
            "max_retries": 3,
            "name": "SEO Publish",
        }
        fake_db = MagicMock()
        # The retry fetch in the job-None branch finds the row.
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[job_row]
        )

        with patch.object(sw, "_fetch_full_job", return_value=None), \
             patch.object(sw, "update_job_run") as upd, \
             patch.object(sw, "_reschedule_after_failure") as resched:
            await sw._dispatch_claimed_job(fake_db, _claim_payload(job_type="seo_publish"))

        upd.assert_called_once()  # run marked failed
        resched.assert_called_once()
        args = resched.call_args[0]
        assert args[0] == job_row
        assert args[1] == "22222222-2222-2222-2222-222222222222"

    @pytest.mark.asyncio
    async def test_missing_job_truly_gone_no_reschedule(self):
        """Row absent on the retry fetch too — nothing to reschedule; must not
        raise."""
        from viraltracker.worker import scheduler_worker as sw

        fake_db = MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        with patch.object(sw, "_fetch_full_job", return_value=None), \
             patch.object(sw, "update_job_run"), \
             patch.object(sw, "_reschedule_after_failure") as resched:
            await sw._dispatch_claimed_job(fake_db, _claim_payload())

        resched.assert_not_called()


class TestHealOrphanedRecurringJobs:
    """Self-heal sweep: active recurring + next_run_at NULL + no live run =
    orphaned-forever (invisible to claim_next_job). The sweep recomputes
    next_run_at from cron. Covers the class behind BOTH live bugs found
    2026-06-09 (analytics_sync never initialized; seo_publish killed by a
    dispatch-time fetch failure)."""

    def _db(self, orphans, live_runs, cas_wins=True):
        """Router: scheduled_jobs select → orphans; scheduled_job_runs select
        → live_runs; scheduled_jobs update recorded. cas_wins=False simulates
        a concurrent reschedule winning the compare-and-swap (update matches
        zero rows)."""
        db = MagicMock()
        updates = []

        def table_side_effect(name):
            chain = MagicMock()
            for m in ["select", "eq", "is_", "in_", "limit", "order"]:
                getattr(chain, m).return_value = chain
            chain.not_ = chain
            if name == "scheduled_jobs":
                chain.execute.return_value = MagicMock(data=orphans)

                def _update(payload):
                    upd_chain = MagicMock()
                    upd_chain.eq.return_value = upd_chain
                    upd_chain.is_.return_value = upd_chain
                    # CAS: PostgREST returns the updated rows; [] = lost the race.
                    upd_chain.execute.return_value = MagicMock(
                        data=[{"id": "j1"}] if cas_wins else []
                    )
                    updates.append(payload)
                    return upd_chain

                chain.update.side_effect = _update
            elif name == "scheduled_job_runs":
                chain.execute.return_value = MagicMock(data=live_runs)
            return chain

        db.table.side_effect = table_side_effect
        return db, updates

    def test_heals_orphan_with_no_live_run(self):
        from datetime import datetime, timezone
        from viraltracker.worker import scheduler_worker as sw

        orphan = {
            "id": "j1", "name": "Analytics Sync", "job_type": "analytics_sync",
            "brand_id": "b1", "cron_expression": "0 2 * * *",
        }
        db, updates = self._db([orphan], live_runs=[])
        fixed = datetime(2026, 6, 10, 2, 0, tzinfo=timezone.utc)

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "calculate_next_run", return_value=fixed), \
             patch.object(sw, "_emit_activity_event"):
            healed = sw.heal_orphaned_recurring_jobs()

        assert len(healed) == 1
        assert healed[0]["job_id"] == "j1"
        assert updates == [{"next_run_at": fixed.isoformat()}]

    def test_skips_job_with_live_run(self):
        """A claimed job has next_run_at NULL by design while running — the
        sweep must not resurrect it mid-execution (double-run)."""
        from viraltracker.worker import scheduler_worker as sw

        orphan = {
            "id": "j1", "name": "X", "job_type": "seo_publish",
            "brand_id": "b1", "cron_expression": "*/30 * * * *",
        }
        db, updates = self._db([orphan], live_runs=[{"id": "r1"}])

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "_emit_activity_event"):
            healed = sw.heal_orphaned_recurring_jobs()

        assert healed == []
        assert updates == []

    def test_skips_uncomputable_cron(self):
        from viraltracker.worker import scheduler_worker as sw

        orphan = {
            "id": "j1", "name": "Bad", "job_type": "meta_sync",
            "brand_id": "b1", "cron_expression": "not a cron",
        }
        db, updates = self._db([orphan], live_runs=[])

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "calculate_next_run", return_value=None), \
             patch.object(sw, "_emit_activity_event"):
            healed = sw.heal_orphaned_recurring_jobs()

        assert healed == []
        assert updates == []

    def test_no_orphans_no_writes(self):
        from viraltracker.worker import scheduler_worker as sw

        db, updates = self._db([], live_runs=[])
        with patch.object(sw, "get_supabase_client", return_value=db):
            assert sw.heal_orphaned_recurring_jobs() == []
        assert updates == []

    def test_cas_lost_to_concurrent_reschedule(self):
        """If another path set next_run_at between our select and update, the
        conditional update matches zero rows — do NOT report healed, do NOT
        clobber."""
        from datetime import datetime, timezone
        from viraltracker.worker import scheduler_worker as sw

        orphan = {
            "id": "j1", "name": "X", "job_type": "seo_publish",
            "brand_id": "b1", "cron_expression": "*/30 * * * *",
        }
        db, updates = self._db([orphan], live_runs=[], cas_wins=False)
        fixed = datetime(2026, 6, 10, 2, 0, tzinfo=timezone.utc)

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "calculate_next_run", return_value=fixed), \
             patch.object(sw, "_emit_activity_event") as emit:
            healed = sw.heal_orphaned_recurring_jobs()

        assert healed == []
        assert len(updates) == 1  # the attempt happened, but lost the CAS
        emit.assert_not_called()  # no misleading "self-healed" event


class TestRecoveryThread:
    """The recovery owner runs in a daemon THREAD because long sync handlers
    starve the asyncio event loop (verified live 2026-06-09: zero recovery
    RPCs, two claims at boot then silence). These cover the tick + lifecycle."""

    def test_tick_runs_rpc_then_heal(self):
        from viraltracker.worker import scheduler_worker as sw

        fake_db = MagicMock()
        fake_db.rpc.return_value.execute.return_value = MagicMock(data=[])

        with patch.object(sw, "get_supabase_client", return_value=fake_db), \
             patch.object(sw, "heal_orphaned_recurring_jobs") as heal:
            sw._recovery_tick()

        assert fake_db.rpc.call_args[0][0] == "recover_stuck_runs_v2"
        heal.assert_called_once()

    def test_tick_rpc_failure_does_not_block_heal(self):
        """The two halves are independent: a missing/failing RPC must not
        stop the orphan heal (and vice versa)."""
        from viraltracker.worker import scheduler_worker as sw

        fake_db = MagicMock()
        fake_db.rpc.return_value.execute.side_effect = RuntimeError("rpc down")

        with patch.object(sw, "get_supabase_client", return_value=fake_db), \
             patch.object(sw, "heal_orphaned_recurring_jobs") as heal:
            sw._recovery_tick()  # must not raise

        heal.assert_called_once()

    def test_tick_heal_failure_contained(self):
        from viraltracker.worker import scheduler_worker as sw

        fake_db = MagicMock()
        fake_db.rpc.return_value.execute.return_value = MagicMock(data=[])

        with patch.object(sw, "get_supabase_client", return_value=fake_db), \
             patch.object(sw, "heal_orphaned_recurring_jobs", side_effect=RuntimeError("boom")):
            sw._recovery_tick()  # must not raise

    def test_thread_ticks_and_stops_on_shutdown_flag(self):
        import time
        from viraltracker.worker import scheduler_worker as sw

        ticks = {"n": 0}
        saved_flag = sw.shutdown_requested
        sw.shutdown_requested = False
        try:
            with patch.object(sw, "_recovery_tick", side_effect=lambda: ticks.__setitem__("n", ticks["n"] + 1)):
                t = sw.start_recovery_thread(interval_seconds=0.05, jitter_max_seconds=0.0)
                deadline = time.time() + 2.0
                while ticks["n"] < 2 and time.time() < deadline:
                    time.sleep(0.02)
                sw.shutdown_requested = True
                t.join(timeout=3.0)
                assert not t.is_alive()
                assert ticks["n"] >= 2  # ticked repeatedly before shutdown
        finally:
            sw.shutdown_requested = saved_flag


class TestScanHealthRegression:
    """CRITICAL (iron rule, plan §11): the interlink-health extension must
    leave the scan's existing outputs unchanged — opportunities upserted and
    the weekly report event emitted — even when the health section THROWS
    (non-fatal wrap / failure budget)."""

    @pytest.mark.asyncio
    async def test_scan_completes_when_health_section_throws(self):
        from viraltracker.worker import scheduler_worker as sw

        # One GSC-connected brand; brands lookup resolves org.
        def table_side_effect(name):
            chain = MagicMock()
            for m in ["select", "eq", "neq", "in_", "is_", "lt", "order", "limit"]:
                getattr(chain, m).return_value = chain
            if name == "brand_integrations":
                chain.execute.return_value = MagicMock(
                    data=[{"brand_id": "b1", "organization_id": "o1"}]
                )
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        fake_db = MagicMock()
        fake_db.table.side_effect = table_side_effect

        fake_miner = MagicMock()
        fake_miner.scan_opportunities.return_value = [{"keyword": "k", "opportunity_score": 50}]
        fake_miner.upsert_opportunities.return_value = 1
        fake_miner.update_rank_deltas.return_value = 0
        fake_miner.generate_weekly_report.return_value = {
            "articles_published": 3,
            "total_impressions_delta": "+100",
            "feed_freshness": {},
        }

        # Health section blows up (e.g. migration missing in a bad way).
        fake_il = MagicMock()
        fake_il.capture_coverage_snapshots.side_effect = RuntimeError("health boom")

        events = []
        job = {
            "id": "job-1", "name": "scan", "_claimed": True,
            "_run_id": "run-1", "_attempt_number": 1,
            "schedule_type": "recurring", "cron_expression": "0 13 * * 0",
        }

        with patch.object(sw, "get_supabase_client", return_value=fake_db), \
             patch("viraltracker.services.seo_pipeline.services.opportunity_miner_service.OpportunityMinerService", return_value=fake_miner), \
             patch("viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService", return_value=fake_il), \
             patch.object(sw, "_emit_activity_event", side_effect=lambda **kw: events.append(kw)), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "_update_job_next_run"):
            result = await sw.execute_seo_opportunity_scan_job(job)

        # Existing outputs unchanged: opportunities upserted, report emitted,
        # run completed — the health failure was contained.
        assert result["success"] is True
        fake_miner.upsert_opportunities.assert_called_once()
        report_events = [e for e in events if e.get("event_type") == "seo_weekly_report"]
        assert len(report_events) == 1
        final_updates = upd_run.call_args[0][1]
        assert final_updates["status"] == "completed"
        # No orphan alarms emitted (health failed before alerts).
        assert not [e for e in events if e.get("event_type") == "seo_orphan_alert"]

    @pytest.mark.asyncio
    async def test_scan_emits_orphan_alarms_when_health_finds_regressions(self):
        from viraltracker.worker import scheduler_worker as sw

        def table_side_effect(name):
            chain = MagicMock()
            for m in ["select", "eq", "neq", "in_", "is_", "lt", "order", "limit"]:
                getattr(chain, m).return_value = chain
            if name == "brand_integrations":
                chain.execute.return_value = MagicMock(
                    data=[{"brand_id": "b1", "organization_id": "o1"}]
                )
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        fake_db = MagicMock()
        fake_db.table.side_effect = table_side_effect

        fake_miner = MagicMock()
        fake_miner.scan_opportunities.return_value = []
        fake_miner.upsert_opportunities.return_value = 0
        fake_miner.update_rank_deltas.return_value = 0
        fake_miner.generate_weekly_report.return_value = {
            "articles_published": 0,
            "total_impressions_delta": "+0",
            "feed_freshness": {},
        }

        fake_il = MagicMock()
        fake_il.capture_coverage_snapshots.return_value = {"captured": 2, "articles": []}
        fake_il.process_orphan_alerts.return_value = {
            "new_alarms": [{"article_id": "a9", "keyword": "lonely page"}],
            "refreshed": 0, "resolved": 0, "open_total": 1,
        }
        fake_il.build_interlink_health.return_value = {
            "published_count": 2, "orphan_count": 1, "exempt_count": 0,
            "coverage_pct": 50.0, "previous_orphan_count": None,
            "new_alarm_count": 1, "open_alert_count": 1, "resolved_count": 0,
        }

        events = []
        job = {
            "id": "job-1", "name": "scan", "_claimed": True,
            "_run_id": "run-1", "_attempt_number": 1,
            "schedule_type": "recurring", "cron_expression": "0 13 * * 0",
        }

        with patch.object(sw, "get_supabase_client", return_value=fake_db), \
             patch("viraltracker.services.seo_pipeline.services.opportunity_miner_service.OpportunityMinerService", return_value=fake_miner), \
             patch("viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService", return_value=fake_il), \
             patch.object(sw, "_emit_activity_event", side_effect=lambda **kw: events.append(kw)), \
             patch.object(sw, "update_job_run"), \
             patch.object(sw, "_update_job_next_run"):
            result = await sw.execute_seo_opportunity_scan_job(job)

        assert result["success"] is True
        report_events = [e for e in events if e.get("event_type") == "seo_weekly_report"]
        assert len(report_events) == 1
        # Health block landed in the report payload
        assert report_events[0]["details"]["interlink_health"]["orphan_count"] == 1
        # Exactly one alarm-styled orphan event for the NEW regression
        alarms = [e for e in events if e.get("event_type") == "seo_orphan_alert"]
        assert len(alarms) == 1
        assert alarms[0]["severity"] == "error"
        assert alarms[0]["details"]["article_id"] == "a9"


class TestMetaSdkSerialization:
    """Meta SDK jobs switch process-global FacebookAdsApi state — under
    thread-per-job dispatch they must SERIALIZE (lock held in the job thread)
    while non-Meta jobs still run in parallel."""

    def _claim(self, n, job_type):
        return {
            "job_id": f"job-{n}", "run_id": f"run-{n}", "attempt_number": 1,
            "job_type": job_type,
        }

    def _wire(self, sw, job_type, handler):
        fake_db = MagicMock()
        job_row = {"id": "j", "job_type": job_type, "schedule_type": "one_time"}
        return fake_db, job_row, handler

    @pytest.mark.asyncio
    async def test_meta_jobs_serialize_non_meta_overlap(self):
        import time as _t
        from viraltracker.worker import scheduler_worker as sw

        running = {"meta": 0, "max_meta": 0}

        async def meta_handler(_job):
            running["meta"] += 1
            running["max_meta"] = max(running["max_meta"], running["meta"])
            _t.sleep(0.25)
            running["meta"] -= 1

        job_row = {"id": "j", "job_type": "meta_sync", "schedule_type": "one_time"}
        with patch.object(sw, "_fetch_full_job", return_value=job_row), \
             patch.object(sw, "_emit_job_started_event"), \
             patch.object(sw, "dispatch_job", return_value=meta_handler), \
             patch.object(sw, "update_job_run"):
            start = _t.monotonic()
            await asyncio.gather(
                sw._dispatch_claimed_job(MagicMock(), self._claim(1, "meta_sync")),
                sw._dispatch_claimed_job(MagicMock(), self._claim(2, "meta_sync")),
            )
            elapsed = _t.monotonic() - start

        assert running["max_meta"] == 1, "two Meta SDK jobs overlapped — token race"
        assert elapsed >= 0.45, f"meta jobs did not serialize ({elapsed:.2f}s)"

    @pytest.mark.asyncio
    async def test_non_meta_jobs_still_parallel(self):
        import time as _t
        from viraltracker.worker import scheduler_worker as sw

        async def blocking_handler(_job):
            _t.sleep(0.3)

        job_row = {"id": "j", "job_type": "seo_publish", "schedule_type": "one_time"}
        with patch.object(sw, "_fetch_full_job", return_value=job_row), \
             patch.object(sw, "_emit_job_started_event"), \
             patch.object(sw, "dispatch_job", return_value=blocking_handler), \
             patch.object(sw, "update_job_run"):
            start = _t.monotonic()
            await asyncio.gather(
                sw._dispatch_claimed_job(MagicMock(), self._claim(1, "seo_publish")),
                sw._dispatch_claimed_job(MagicMock(), self._claim(2, "seo_publish")),
            )
            elapsed = _t.monotonic() - start

        assert elapsed < 0.55, f"non-meta jobs serialized ({elapsed:.2f}s) — starvation regressed"
