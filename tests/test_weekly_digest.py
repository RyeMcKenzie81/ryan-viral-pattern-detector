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
            "name": "Big Three Bundle", "total_spend": 3719.0, "spending_ads": 80, "no_ads": False,
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
        assert "No ads with spend in scope" in joined

    def test_coverage_footer(self):
        _, blocks = render_brand_digest(_DATA)
        joined = "\n".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
        assert "Coverage:" in joined and "95%" in joined
        assert "Unmapped" in joined and "7reasons-w" in joined

    def test_error_product_distinct_from_no_ads(self):
        data = dict(_DATA, products=[{"name": "Broken Product", "error": True}])
        _, blocks = render_brand_digest(data)
        joined = "\n".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
        assert "Broken Product" in joined
        assert "Could not analyze" in joined               # error variant
        assert "No ads with spend in scope" not in joined  # NOT the dark-product message


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


class TestInsight:
    def test_flags_worst_over_baseline(self):
        rows = [
            {"level": "unaware", "spend": 1200.0, "agg_cpa": 60.0, "med_cpa": 40.0},   # +50%
            {"level": "problem_aware", "spend": 1400.0, "agg_cpa": 38.0, "med_cpa": 41.0},  # under
        ]
        msg = WeeklyDigestService._insight(rows)
        assert msg is not None and "unaware" in msg and "50%" in msg

    def test_none_when_all_under_or_small(self):
        rows = [{"level": "x", "spend": 100.0, "agg_cpa": 30.0, "med_cpa": 40.0}]  # under baseline
        assert WeeklyDigestService._insight(rows) is None


class _CovTable:
    def __init__(self, name, data_map):
        self.name = name
        self.data_map = data_map
        self.ins = {}
        self._start = 0
        self._end = None  # set by range(); None => no pagination slice

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def in_(self, col, vals):
        self.ins[col] = set(vals)
        return self

    def range(self, start, end):
        self._start = start
        self._end = end
        return self

    def execute(self):
        rows = list(self.data_map.get(self.name, []))
        if "meta_ad_id" in self.ins:
            rows = [r for r in rows if r.get("meta_ad_id") in self.ins["meta_ad_id"]]
        # Faithfully model PostgREST .range(start, end) as an inclusive slice, so
        # multi-page pagination loops (offset += page) are actually exercised
        # instead of short-circuiting after page 1.
        if self._end is not None:
            rows = rows[self._start:self._end + 1]
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
        svc = WeeklyDigestService(_CovSupa(data_map), MagicMock(), MagicMock())
        coverage, unmapped = svc._coverage_and_unmapped("BRAND", "2026-05-01", "2026-05-31")
        # a1 tagged ($900); a2 + a3 untagged ($150) → 900 / 1050 = 85.7%
        assert coverage["attributed"] == 900.0
        assert coverage["unmapped"] == 150.0
        assert coverage["pct"] == 85.7
        # top unmapped funnel is c/untagged ($100)
        assert unmapped[0]["url"] == "c/untagged"
        assert unmapped[0]["spend"] == 100.0


class TestProductAwareness:
    def test_awareness_from_stored_classifications(self):
        data_map = {
            # latest-first per ad; a1's newest level is "unaware"
            "ad_creative_classifications": [
                {"meta_ad_id": "a1", "creative_awareness_level": "unaware", "classified_at": "2026-06-03"},
                {"meta_ad_id": "a2", "creative_awareness_level": "problem_aware", "classified_at": "2026-06-03"},
                {"meta_ad_id": "a3", "creative_awareness_level": "most_aware", "classified_at": "2026-06-03"},
                {"meta_ad_id": "a1", "creative_awareness_level": "solution_aware", "classified_at": "2026-05-01"},
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "a1", "spend": "100", "purchases": "2"},
                {"meta_ad_id": "a2", "spend": "50", "purchases": "1"},
                {"meta_ad_id": "a3", "spend": "200", "purchases": "5"},  # highest spend, but most-aware
            ],
        }
        svc = WeeklyDigestService(_CovSupa(data_map), MagicMock(), MagicMock())
        total, active, rows = svc._product_awareness(
            "BRAND", ["a1", "a2", "a3"], "2026-05-01", "2026-05-31",
            baselines={"unaware": 40.0, "problem_aware": 41.0},
        )
        assert total == 350.0
        assert active == 3
        # Ordered by awareness STAGE (Unaware→Most Aware), NOT spend — so most_aware
        # ($200, highest spend) is LAST, and a1's newest level (unaware) wins over stale.
        assert [r["level"] for r in rows] == ["unaware", "problem_aware", "most_aware"]
        assert rows[0]["spend"] == 100.0 and rows[0]["med_cpa"] == 40.0


class TestSpendingAdIds:
    @pytest.mark.asyncio
    async def test_includes_paused_excludes_zero_and_sums_days(self):
        """Spend-scoped set ignores delivery status: a paused-but-spent ad is in,
        a zero-spend ad is out, and per-day rows sum (net) per ad."""
        from datetime import date
        from viraltracker.services.ad_intelligence.helpers import get_spending_ad_ids
        data_map = {"meta_ads_performance": [
            # 'paused_big' would be dropped by get_active_ad_ids (status), but its
            # spend still drove cost — get_spending_ad_ids never looks at status.
            {"meta_ad_id": "paused_big", "spend": "2000"},
            {"meta_ad_id": "paused_big", "spend": "500"},     # second day, same ad
            {"meta_ad_id": "small", "spend": "10"},
            {"meta_ad_id": "zero", "spend": "0"},             # no spend → excluded
            {"meta_ad_id": "refund_net_pos", "spend": "2000"},
            {"meta_ad_id": "refund_net_pos", "spend": "-100"},  # net 1900 → included
            {"meta_ad_id": "fully_refunded", "spend": "50"},
            {"meta_ad_id": "fully_refunded", "spend": "-50"},   # net 0 → excluded
            {"meta_ad_id": "bad", "spend": "abc"},            # unparseable → skipped
            {"meta_ad_id": "blank", "spend": ""},             # empty → skipped
            {"meta_ad_id": "nullspend", "spend": None},       # null spend → skipped
            {"meta_ad_id": None, "spend": "99"},              # null id → ignored
        ]}
        ids = await get_spending_ad_ids(
            _CovSupa(data_map), "BRAND", date(2026, 5, 1), date(2026, 5, 31)
        )
        assert "paused_big" in ids        # paused-but-spent included
        assert "small" in ids
        assert "refund_net_pos" in ids    # +2000 -100 = 1900 > 0
        assert "zero" not in ids          # zero-spend excluded
        assert "fully_refunded" not in ids  # net 0 excluded
        assert "bad" not in ids and "blank" not in ids and "nullspend" not in ids
        assert None not in ids
        assert ids == sorted(ids)         # returned sorted/deterministic

    @pytest.mark.asyncio
    async def test_paginates_past_first_page(self):
        """>1000 rows must be walked across pages (offset += page), not truncated
        at Supabase's 1000-row default — the whole point of the paginated read."""
        from datetime import date
        from viraltracker.services.ad_intelligence.helpers import get_spending_ad_ids
        # 1200 daily rows for one ad (spend 1 each) + a small ad on the last page.
        rows = [{"meta_ad_id": "big", "spend": "1"} for _ in range(1200)]
        rows.append({"meta_ad_id": "tail", "spend": "5"})  # index 1200 → page 2 only
        ids = await get_spending_ad_ids(
            _CovSupa({"meta_ads_performance": rows}), "BRAND",
            date(2026, 5, 1), date(2026, 5, 31),
        )
        # 'tail' is only reachable if the loop fetched page 2 (offset 1000-1999).
        assert ids == ["big", "tail"]


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
