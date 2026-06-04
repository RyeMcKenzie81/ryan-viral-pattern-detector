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
                {"level": "unaware", "ads": 31, "spend": 1200.0, "roas": 2.3, "cvr": 0.021,
                 "agg_cpa": 51.0, "prod_med_cpa": 48.0, "prod_p25_cpa": 38.0, "brand_med_cpa": 40.0,
                 "agg_catc": 24.0, "prod_med_catc": 22.0, "prod_p25_catc": 15.0},
                {"level": "problem_aware", "ads": 28, "spend": 1400.0, "roas": 1.8, "cvr": 0.014,
                 "agg_cpa": 38.0, "prod_med_cpa": 36.0, "prod_p25_cpa": 29.0, "brand_med_cpa": 41.0,
                 "agg_catc": 19.0, "prod_med_catc": 18.0, "prod_p25_catc": 12.0},
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
        # overview table cols + targets table cols both present
        assert "ROAS" in joined and "CVR" in joined and "ATC" in joined
        assert "cpaP25" in joined and "atcP25" in joined and "BrMed" in joined
        assert "2.3x" in joined           # unaware ROAS rendered
        assert "2.1%" in joined           # unaware CVR (0.021) rendered as percent
        assert "$38" in joined            # unaware prod_p25_cpa rendered
        assert "$15" in joined            # unaware prod_p25_catc rendered
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
            {"level": "unaware", "spend": 1200.0, "agg_cpa": 60.0, "brand_med_cpa": 40.0},   # +50%
            {"level": "problem_aware", "spend": 1400.0, "agg_cpa": 38.0, "brand_med_cpa": 41.0},  # under
        ]
        msg = WeeklyDigestService._insight(rows)
        assert msg is not None and "unaware" in msg and "50%" in msg

    def test_none_when_all_under_or_small(self):
        rows = [{"level": "x", "spend": 100.0, "agg_cpa": 30.0, "brand_med_cpa": 40.0}]  # under baseline
        assert WeeklyDigestService._insight(rows) is None


class TestPercentile:
    def test_interpolated_percentiles(self):
        from viraltracker.services.ad_intelligence.weekly_digest_service import _percentile
        assert _percentile([], 50) is None
        assert _percentile([42.0], 75) == 42.0          # single sample
        assert _percentile([10.0, 20.0, 30.0], 50) == 20.0   # median
        # p75 of [10,20,30,40] = interpolate at k=2.25 → 30 + .25*(40-30) = 32.5
        assert _percentile([10.0, 20.0, 30.0, 40.0], 75) == 32.5


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
                {"meta_ad_id": "a1", "spend": "100", "purchases": "2", "purchase_value": "250",
                 "add_to_carts": "5", "link_clicks": "40"},
                {"meta_ad_id": "a2", "spend": "50", "purchases": "1", "purchase_value": "100",
                 "add_to_carts": "2", "link_clicks": "25"},
                {"meta_ad_id": "a3", "spend": "200", "purchases": "5", "purchase_value": "600",
                 "add_to_carts": "10", "link_clicks": "100"},  # highest spend, most-aware
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
        # rows[0]=unaware (a1: spend 100, purchases 2 → per-ad CPA 50; single sample
        # so product median == p75 == 50). brand_med_cpa from the baselines dict.
        assert rows[0]["spend"] == 100.0 and rows[0]["brand_med_cpa"] == 40.0
        assert rows[0]["agg_cpa"] == 50.0
        assert rows[0]["prod_med_cpa"] == 50.0 and rows[0]["prod_p25_cpa"] == 50.0
        assert rows[0]["roas"] == 2.5    # a1 revenue 250 / spend 100
        assert rows[0]["cvr"] == 0.05    # a1 purchases 2 / link_clicks 40
        assert rows[0]["agg_catc"] == 20.0  # a1 spend 100 / add_to_carts 5
        assert rows[0]["prod_med_catc"] == 20.0  # single sample

    def test_unclassified_row_uses_unknown_baseline(self):
        """Ads with no classification bucket as 'unclassified'; that's the same
        population the baselines job stores under 'unknown', so the row should
        show that brand-wide median rather than a blank."""
        data_map = {
            "ad_creative_classifications": [
                {"meta_ad_id": "a1", "creative_awareness_level": "unaware", "classified_at": "2026-06-03"},
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "a1", "spend": "100", "purchases": "2"},
                {"meta_ad_id": "a2", "spend": "50", "purchases": "1"},   # no classification
            ],
        }
        svc = WeeklyDigestService(_CovSupa(data_map), MagicMock(), MagicMock())
        _, _, rows = svc._product_awareness(
            "BRAND", ["a1", "a2"], "2026-05-01", "2026-05-31",
            baselines={"unaware": 40.0, "unknown": 61.29},
        )
        by_level = {r["level"]: r for r in rows}
        assert by_level["unclassified"]["brand_med_cpa"] == 61.29   # mapped from "unknown"
        assert by_level["unaware"]["brand_med_cpa"] == 40.0


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
        assert "zero" not in ids          # zero-spend excluded
        assert "fully_refunded" not in ids  # net 0 excluded
        assert "bad" not in ids and "blank" not in ids and "nullspend" not in ids
        assert None not in ids
        # Ordered by spend DESC (tie-break meta_ad_id): paused_big=2500,
        # refund_net_pos=1900 (2000-100), small=10. So the biggest-dollar ad
        # leads, which is what a capped classifier should classify first.
        assert ids == ["paused_big", "refund_net_pos", "small"]

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
# HTML report + storage publish
# ---------------------------------------------------------------------------


class _Bucket:
    def __init__(self, raise_upload=False):
        self.calls = []
        self.raise_upload = raise_upload

    def upload(self, path, content, file_options=None):
        if self.raise_upload:
            raise RuntimeError("storage boom")
        self.calls.append(("upload", path, file_options, content))
        return {}

    def get_public_url(self, path):
        self.calls.append(("public", path))
        return f"https://ex/storage/cron-outputs/{path}"


class _StorageSupa:
    def __init__(self, bucket):
        self.storage = SimpleNamespace(from_=lambda name: bucket)


class TestHtmlReport:
    def test_render_html_has_grid_and_values(self):
        from viraltracker.services.ad_intelligence.digest_renderer import render_brand_digest_html
        doc = render_brand_digest_html(_DATA)
        assert doc.startswith("<!DOCTYPE html>")
        assert "Martin Clinic" in doc and "Big Three Bundle" in doc
        assert "<table" in doc and "ROAS" in doc and "Cost / add-to-cart" in doc
        # values: roas 2.3 -> 2.3x, cvr 0.021 -> 2.1%, p25 cpa 38 -> $38, p25 atc 15 -> $15
        assert "2.3x" in doc and "2.1%" in doc and "$38" in doc and "$15" in doc
        assert "No ads with spend in scope" in doc   # DHA Upgraded (no_ads)
        assert "Coverage" in doc and "95%" in doc

    def test_render_html_escapes_names(self):
        from viraltracker.services.ad_intelligence.digest_renderer import render_brand_digest_html
        doc = render_brand_digest_html(dict(_DATA, brand_name="A & <b>B</b>"))
        assert "A &amp; &lt;b&gt;B&lt;/b&gt;" in doc
        assert "<b>B</b>" not in doc   # not injected raw

    def test_publish_uploads_and_returns_signed_url(self):
        bucket = _Bucket()
        svc = WeeklyDigestService(_StorageSupa(bucket), MagicMock(), MagicMock())
        url = svc.publish_html_report("BRAND", _DATA)
        assert url and url.startswith("https://ex/storage/cron-outputs/digests/BRAND/")
        up = next(c for c in bucket.calls if c[0] == "upload")
        assert up[2]["content-type"] == "text/html" and up[2]["upsert"] == "true"

    def test_publish_non_fatal_on_error(self):
        svc = WeeklyDigestService(_StorageSupa(_Bucket(raise_upload=True)), MagicMock(), MagicMock())
        assert svc.publish_html_report("BRAND", _DATA) is None


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
