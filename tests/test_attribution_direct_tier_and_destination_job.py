"""Tests for the direct-destination attribution tier + dedicated destination_sync job.

1. ``resolve_product_ad_ids`` Tier-0 — resolve a product via
   ad -> meta_ad_destinations.canonical -> brand_landing_pages.product_id
   DIRECTLY, independent of whether the ad was classified. This is the fix for
   the leak where BG3 read $705 (classification-gated) instead of ~$3,719.
   Ambiguous canonicals (tagged to >1 product) are excluded.
2. ``execute_destination_sync_job`` — the handler that runs the destination
   capture + populate out of band from meta_sync.

Mock-based — no live Supabase or Meta.

Run with: pytest tests/test_attribution_direct_tier_and_destination_job.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Filtering fake Supabase — applies eq/in_ filters so the resolver's query
# logic is actually exercised (not just stubbed).
# ---------------------------------------------------------------------------


class _Q:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.cols = None
        self.eqs = {}
        self.ins = {}

    def select(self, cols):
        self.cols = cols
        return self

    def eq(self, c, v):
        self.eqs[c] = v
        return self

    def in_(self, c, vals):
        self.ins[c] = list(vals)
        return self

    def limit(self, n):
        return self

    def execute(self):
        rows = list(self.store.get(self.table, []))
        out = []
        for r in rows:
            if all(r.get(c) == v for c, v in self.eqs.items()) and \
               all(r.get(c) in vals for c, vals in self.ins.items()):
                out.append(r)
        return SimpleNamespace(data=out)


class _Supa:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(name, self.store)


# ---------------------------------------------------------------------------
# Tier-0 direct-destination resolution
# ---------------------------------------------------------------------------

BG3 = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


class TestResolveProductAdIdsTier0:

    def _resolve(self, store, ad_ids):
        from viraltracker.services.ad_intelligence.helpers import resolve_product_ad_ids
        return resolve_product_ad_ids(_Supa(store), "BRAND", BG3, ad_ids)

    def test_direct_match_without_classification(self):
        """An ad whose destination canonical maps to a BG3-tagged landing page is
        attributed to BG3 even with NO classification row (the core fix)."""
        store = {
            "products": [{"id": BG3, "name": "Big Three"}],
            "brand_landing_pages": [
                {"id": "lp_v3", "canonical_url": "c/v3", "product_id": BG3, "brand_id": "BRAND"},
            ],
            "meta_ad_destinations": [
                {"meta_ad_id": "ad1", "canonical_url": "c/v3", "brand_id": "BRAND"},
            ],
            "ad_creative_classifications": [],          # ad1 is NOT classified
            "meta_ads_performance": [
                {"meta_ad_id": "ad1", "ad_name": "x", "campaign_name": "", "adset_name": "", "brand_id": "BRAND"},
            ],
        }
        assert self._resolve(store, ["ad1"]) == {"ad1"}

    def test_ambiguous_canonical_excluded(self):
        """A canonical tagged to two products is ambiguous → not attributed."""
        store = {
            "products": [{"id": BG3, "name": "Big Three"}],
            "brand_landing_pages": [
                {"id": "lpA", "canonical_url": "c/amb", "product_id": BG3, "brand_id": "BRAND"},
                {"id": "lpB", "canonical_url": "c/amb", "product_id": OTHER, "brand_id": "BRAND"},
            ],
            "meta_ad_destinations": [
                {"meta_ad_id": "ad2", "canonical_url": "c/amb", "brand_id": "BRAND"},
            ],
            "ad_creative_classifications": [],
            "meta_ads_performance": [
                {"meta_ad_id": "ad2", "ad_name": "x", "campaign_name": "", "adset_name": "", "brand_id": "BRAND"},
            ],
        }
        assert self._resolve(store, ["ad2"]) == set()

    def test_tier0_and_tier1_union(self):
        """Tier-0 (destination) and Tier-1 (classification) are additive."""
        store = {
            "products": [{"id": BG3, "name": "Big Three"}],
            "brand_landing_pages": [
                {"id": "lp_v3", "canonical_url": "c/v3", "product_id": BG3, "brand_id": "BRAND"},
            ],
            "meta_ad_destinations": [
                {"meta_ad_id": "ad1", "canonical_url": "c/v3", "brand_id": "BRAND"},   # Tier-0
            ],
            "ad_creative_classifications": [
                {"meta_ad_id": "ad3", "landing_page_id": "lp_v3", "brand_id": "BRAND"},  # Tier-1
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "ad1", "ad_name": "", "campaign_name": "", "adset_name": "", "brand_id": "BRAND"},
                {"meta_ad_id": "ad3", "ad_name": "", "campaign_name": "", "adset_name": "", "brand_id": "BRAND"},
            ],
        }
        assert self._resolve(store, ["ad1", "ad3"]) == {"ad1", "ad3"}

    def test_unrelated_ad_not_matched(self):
        store = {
            "products": [{"id": BG3, "name": "Big Three"}],
            "brand_landing_pages": [
                {"id": "lp_v3", "canonical_url": "c/v3", "product_id": BG3, "brand_id": "BRAND"},
            ],
            "meta_ad_destinations": [
                {"meta_ad_id": "adX", "canonical_url": "c/elsewhere", "brand_id": "BRAND"},
            ],
            "ad_creative_classifications": [],
            "meta_ads_performance": [
                {"meta_ad_id": "adX", "ad_name": "n", "campaign_name": "", "adset_name": "", "brand_id": "BRAND"},
            ],
        }
        assert self._resolve(store, ["adX"]) == set()


# ---------------------------------------------------------------------------
# destination_sync job handler
# ---------------------------------------------------------------------------


def _claimed_job(**over):
    job = {
        "id": "job-1", "name": "Destination Sync - Recurring",
        "brand_id": "33333333-3333-3333-3333-333333333333",
        "brands": {"name": "Martin", "organization_id": "44444444-4444-4444-4444-444444444444"},
        "parameters": {}, "schedule_type": "recurring", "cron_expression": "0 8 * * *",
        "runs_completed": 0, "_claimed": True, "_run_id": "run-1",
    }
    job.update(over)
    return job


class TestDestinationSyncHandler:

    @pytest.mark.asyncio
    async def test_runs_sync_then_populate_and_rearms(self):
        from viraltracker.worker import scheduler_worker as sw
        svc = MagicMock()
        svc.get_ad_account_for_brand = AsyncMock(return_value="act_123")
        svc.sync_ad_destinations_to_db = AsyncMock(
            return_value={"fetched": 5, "stored": 3, "no_url": 1, "multi_url": 0, "matched": 0})
        svc.populate_classification_landing_page_ids = AsyncMock(return_value={"updated": 2})

        with patch("viraltracker.services.meta_ads_service.MetaAdsService", return_value=svc), \
             patch("viraltracker.services.dataset_freshness_service.DatasetFreshnessService", return_value=MagicMock()), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "update_job") as upd_job:
            result = await sw.execute_destination_sync_job(_claimed_job())

        assert result["success"] is True
        # Per-brand Meta token MUST be set before the fetch (else OAuth brands
        # silently capture nothing).
        svc.get_ad_account_for_brand.assert_awaited_once()
        svc.sync_ad_destinations_to_db.assert_awaited_once()
        svc.populate_classification_landing_page_ids.assert_awaited_once()
        # Run row marked completed.
        assert any(c.args[1].get("status") == "completed" for c in upd_run.call_args_list)
        # Recurring job re-armed (next_run_at set), not marked completed.
        job_updates = [c.args[1] for c in upd_job.call_args_list]
        assert any(u.get("next_run_at") for u in job_updates)
        assert not any(u.get("status") == "completed" for u in job_updates)

    @pytest.mark.asyncio
    async def test_populate_failure_is_non_fatal(self):
        from viraltracker.worker import scheduler_worker as sw
        svc = MagicMock()
        svc.get_ad_account_for_brand = AsyncMock(return_value="act_123")
        svc.sync_ad_destinations_to_db = AsyncMock(
            return_value={"fetched": 1, "stored": 1, "no_url": 0, "multi_url": 0, "matched": 0})
        svc.populate_classification_landing_page_ids = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("viraltracker.services.meta_ads_service.MetaAdsService", return_value=svc), \
             patch("viraltracker.services.dataset_freshness_service.DatasetFreshnessService", return_value=MagicMock()), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "update_job"):
            result = await sw.execute_destination_sync_job(_claimed_job())

        # Populate blew up but the job still completes (capture already succeeded).
        assert result["success"] is True
        assert any(c.args[1].get("status") == "completed" for c in upd_run.call_args_list)

    @pytest.mark.asyncio
    async def test_no_org_id_skips_cleanly(self):
        from viraltracker.worker import scheduler_worker as sw
        # brand_info lacks org; brands lookup also returns none.
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        svc = MagicMock()
        svc.sync_ad_destinations_to_db = AsyncMock()

        with patch("viraltracker.services.meta_ads_service.MetaAdsService", return_value=svc), \
             patch("viraltracker.services.dataset_freshness_service.DatasetFreshnessService", return_value=MagicMock()), \
             patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "update_job_run"), \
             patch.object(sw, "update_job"):
            job = _claimed_job(brands={"name": "Martin"})  # no organization_id
            result = await sw.execute_destination_sync_job(job)

        assert result["success"] is True
        assert result.get("skipped") == "no_org_id"
        svc.sync_ad_destinations_to_db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_org_resolved_from_brands_table_fallback(self):
        """brand_info lacks organization_id → handler resolves it from the brands
        table and runs the sync with that org."""
        from viraltracker.worker import scheduler_worker as sw
        org = "55555555-5555-5555-5555-555555555555"
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": org}]
        )
        svc = MagicMock()
        svc.get_ad_account_for_brand = AsyncMock(return_value="act_123")
        svc.sync_ad_destinations_to_db = AsyncMock(
            return_value={"fetched": 1, "stored": 1, "no_url": 0, "multi_url": 0, "matched": 0})
        svc.populate_classification_landing_page_ids = AsyncMock(return_value={"updated": 0})

        with patch("viraltracker.services.meta_ads_service.MetaAdsService", return_value=svc), \
             patch("viraltracker.services.dataset_freshness_service.DatasetFreshnessService", return_value=MagicMock()), \
             patch.object(sw, "get_supabase_client", return_value=db), \
             patch.object(sw, "update_job_run"), patch.object(sw, "update_job"):
            job = _claimed_job(brands={"name": "Martin"})  # no organization_id
            result = await sw.execute_destination_sync_job(job)

        assert result["success"] is True
        svc.sync_ad_destinations_to_db.assert_awaited_once()
        # The resolved org (from the brands fallback) was passed through.
        assert str(svc.sync_ad_destinations_to_db.await_args.kwargs["organization_id"]) == org

    @pytest.mark.asyncio
    async def test_sync_failure_marks_failed_and_reschedules(self):
        from viraltracker.worker import scheduler_worker as sw
        svc = MagicMock()
        svc.get_ad_account_for_brand = AsyncMock(return_value="act_123")
        svc.sync_ad_destinations_to_db = AsyncMock(side_effect=RuntimeError("meta down"))

        with patch("viraltracker.services.meta_ads_service.MetaAdsService", return_value=svc), \
             patch("viraltracker.services.dataset_freshness_service.DatasetFreshnessService", return_value=MagicMock()), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "_reschedule_after_failure") as resched, \
             patch.object(sw, "get_run_attempt_number", return_value=1), \
             patch.object(sw, "update_job"):
            result = await sw.execute_destination_sync_job(_claimed_job())

        assert result["success"] is False
        assert any(c.args[1].get("status") == "failed" for c in upd_run.call_args_list)
        resched.assert_called_once()

    @pytest.mark.asyncio
    async def test_assert_requires_claim_path(self):
        from viraltracker.worker.scheduler_worker import execute_destination_sync_job
        with pytest.raises(AssertionError, match="claim_next_job"):
            await execute_destination_sync_job({"id": "x", "name": "n", "brand_id": "b", "parameters": {}})
