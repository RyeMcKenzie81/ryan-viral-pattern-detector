"""Tests for the weekly per-product digest (WS5): renderer, service helpers, job.

Run with: pytest tests/test_weekly_digest.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from viraltracker.services.ad_intelligence.digest_renderer import render_brand_digest
from viraltracker.services.ad_intelligence.weekly_digest_service import WeeklyDigestService


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

_DATA = {
    "brand_name": "Martin Clinic",
    "currency": "CAD",
    "date_range": "Last 30 days",
    "products": [
        {
            "name": "Big Three Bundle", "total_spend": 3719.0, "active_ads": 80, "no_ads": False,
            "awareness": [
                {"level": "unaware", "ads": 31, "spend": 1200.0, "agg_cpa": 51.0, "med_cpa": 40.0},
                {"level": "problem_aware", "ads": 28, "spend": 1400.0, "agg_cpa": 38.0, "med_cpa": 41.0},
            ],
            "markets": {"US": {"spend": 3719.0, "cpa": 46.0, "ads": 80, "currency": "CAD"}},
            "insight": "Unaware CPA 28% over baseline.",
        },
        {"name": "DHA Upgraded", "no_ads": True},
    ],
    "coverage": {"attributed": 31312.0, "unmapped": 1591.0, "pct": 95.2},
    "unmapped_funnels": [{"url": "us.martinclinic.com/pages/7reasons-w", "spend": 120.0, "ads": 44}],
}


class TestRenderer:
    def test_blocks_structure(self):
        text, blocks = render_brand_digest(_DATA)
        assert "Martin Clinic" in text and "CAD" in text
        types = [b["type"] for b in blocks]
        assert types[0] == "header"
        assert "divider" in types
        # one section per product (2) + footer section
        sections = [b for b in blocks if b["type"] == "section"]
        assert len(sections) >= 3

    def test_product_section_has_table_and_market(self):
        _, blocks = render_brand_digest(_DATA)
        joined = "\n".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
        assert "Big Three Bundle" in joined
        assert "```" in joined            # monospace awareness table
        assert "unaware" in joined
        assert "*US*" in joined            # market split line
        assert "3,719" in joined

    def test_no_ads_product_message(self):
        _, blocks = render_brand_digest(_DATA)
        joined = "\n".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
        assert "DHA Upgraded" in joined
        assert "No active ads in scope" in joined

    def test_coverage_footer(self):
        _, blocks = render_brand_digest(_DATA)
        joined = "\n".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
        assert "Coverage:" in joined and "95%" in joined
        assert "Unmapped" in joined and "7reasons-w" in joined


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


class TestAwarenessRows:
    def test_sorted_by_spend_desc_with_baselines(self):
        result = SimpleNamespace(
            awareness_distribution={"unaware": 31, "problem_aware": 28},
            awareness_aggregates={"unaware": {"spend": 1200.0, "cpa": 51.0},
                                  "problem_aware": {"spend": 1400.0, "cpa": 38.0}},
            awareness_baselines={"unaware": {"cpa": 40.0}, "problem_aware": {"cpa": 41.0}},
        )
        rows = WeeklyDigestService._awareness_rows(result)
        assert [r["level"] for r in rows] == ["problem_aware", "unaware"]  # 1400 > 1200
        assert rows[0]["med_cpa"] == 41.0 and rows[0]["agg_cpa"] == 38.0


class _CovTable:
    def __init__(self, name, data_map):
        self.name = name
        self.data_map = data_map
        self.ins = {}
        self._start = 0

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def order(self, *a):
        return self

    def in_(self, col, vals):
        self.ins[col] = set(vals)
        return self

    def range(self, start, end):
        self._start = start
        return self

    def execute(self):
        if self._start and self._start > 0:
            return SimpleNamespace(data=[])
        rows = list(self.data_map.get(self.name, []))
        if "meta_ad_id" in self.ins:
            rows = [r for r in rows if r.get("meta_ad_id") in self.ins["meta_ad_id"]]
        return SimpleNamespace(data=rows)


class _CovSupa:
    def __init__(self, data_map):
        self.data_map = data_map

    def table(self, name):
        return _CovTable(name, self.data_map)


class TestCoverageAndUnmapped:
    def test_attributed_vs_unmapped(self):
        data_map = {
            "brand_landing_pages": [
                {"canonical_url": "c/tagged", "product_id": "p1"},
                {"canonical_url": "c/untagged", "product_id": None},
            ],
            "meta_ad_destinations": [
                {"meta_ad_id": "a1", "canonical_url": "c/tagged"},
                {"meta_ad_id": "a2", "canonical_url": "c/untagged"},
                {"meta_ad_id": "a3", "canonical_url": "c/never-seen"},
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "a1", "spend": "900"},
                {"meta_ad_id": "a2", "spend": "100"},
                {"meta_ad_id": "a3", "spend": "50"},
            ],
        }
        svc = WeeklyDigestService(_CovSupa(data_map), MagicMock(), MagicMock(), MagicMock())
        coverage, unmapped = svc._coverage_and_unmapped("BRAND", "2026-05-01", "2026-05-31")
        # a1 tagged ($900); a2 + a3 untagged ($150) → 900 / 1050 = 85.7%
        assert coverage["attributed"] == 900.0
        assert coverage["unmapped"] == 150.0
        assert coverage["pct"] == 85.7
        # top unmapped funnel is c/untagged ($100)
        assert unmapped[0]["url"] == "c/untagged"
        assert unmapped[0]["spend"] == 100.0


# ---------------------------------------------------------------------------
# Job handler
# ---------------------------------------------------------------------------


def _claimed_job(**over):
    job = {
        "id": "job-d", "name": "Weekly Digest", "brand_id": "d0cfa5c5-1132-447b-ade3-4db87995315b",
        "brands": {"name": "Martin"}, "parameters": {"days_back": 30, "webhook_url": "https://hooks.slack.com/x"},
        "schedule_type": "recurring", "cron_expression": "0 8 * * 6",
        "runs_completed": 0, "_claimed": True, "_run_id": "run-d",
    }
    job.update(over)
    return job


class TestDigestHandler:
    @pytest.mark.asyncio
    async def test_builds_renders_and_posts(self):
        from viraltracker.worker import scheduler_worker as sw

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": "44444444-4444-4444-4444-444444444444"}]
        )
        wds = MagicMock()
        wds.build_brand_digest = AsyncMock(return_value=_DATA)
        slack = MagicMock()
        slack.enabled = True
        slack.send_message = AsyncMock(return_value=SimpleNamespace(success=True, error=None))

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch("viraltracker.services.gemini_service.GeminiService", MagicMock()), \
             patch("viraltracker.services.ad_intelligence.ad_intelligence_service.AdIntelligenceService", MagicMock()), \
             patch("viraltracker.services.ad_intelligence.weekly_digest_service.WeeklyDigestService", return_value=wds), \
             patch("viraltracker.services.brand_market_service.BrandMarketService", MagicMock()), \
             patch("viraltracker.services.meta_ads_service.MetaAdsService", MagicMock()), \
             patch("viraltracker.services.slack_service.SlackService", return_value=slack), \
             patch.object(sw, "update_job_run") as upd_run, \
             patch.object(sw, "update_job") as upd_job:
            result = await sw.execute_weekly_product_digest_job(_claimed_job())

        assert result["success"] is True and result["delivered"] is True
        wds.build_brand_digest.assert_awaited_once()
        slack.send_message.assert_awaited_once()
        assert any(c.args[1].get("status") == "completed" for c in upd_run.call_args_list)
        # recurring → re-armed
        assert any(u.get("next_run_at") for u in [c.args[1] for c in upd_job.call_args_list])

    @pytest.mark.asyncio
    async def test_no_webhook_builds_but_does_not_deliver(self):
        from viraltracker.worker import scheduler_worker as sw
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": "44444444-4444-4444-4444-444444444444"}]
        )
        wds = MagicMock()
        wds.build_brand_digest = AsyncMock(return_value=_DATA)
        slack = MagicMock()
        slack.enabled = False  # no webhook
        slack.send_message = AsyncMock()

        with patch.object(sw, "get_supabase_client", return_value=db), \
             patch("viraltracker.services.gemini_service.GeminiService", MagicMock()), \
             patch("viraltracker.services.ad_intelligence.ad_intelligence_service.AdIntelligenceService", MagicMock()), \
             patch("viraltracker.services.ad_intelligence.weekly_digest_service.WeeklyDigestService", return_value=wds), \
             patch("viraltracker.services.brand_market_service.BrandMarketService", MagicMock()), \
             patch("viraltracker.services.meta_ads_service.MetaAdsService", MagicMock()), \
             patch("viraltracker.services.slack_service.SlackService", return_value=slack), \
             patch.object(sw, "update_job_run"), patch.object(sw, "update_job"):
            result = await sw.execute_weekly_product_digest_job(_claimed_job(parameters={"days_back": 30}))

        assert result["success"] is True and result["delivered"] is False
        slack.send_message.assert_not_awaited()
