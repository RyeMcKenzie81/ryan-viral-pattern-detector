"""Tests for WS1 — ad-intelligence attribution engine correctness fixes.

Covers the three WS1 changes from the attribution design:

1. ``_get_total_spend`` now accepts an optional ``ad_ids`` filter and scopes the
   sum with ``.in_("meta_ad_id", ad_ids)`` when provided — fixing the header bug
   where a product-scoped report summed the whole account ($54K vs ~$3K).
   Brand-level runs (ad_ids=None) keep the account-wide behavior.
2. ``full_analysis`` validates that ``product_id`` belongs to ``brand_id`` and
   raises ValueError on a cross-brand (or missing) product, instead of silently
   producing an empty report.
3. A zero-ad scope returns ``no_ads_in_scope=True`` and ``ChatRenderer`` renders
   an explicit "no active ads in scope" message rather than a blank success.

Mock-based — no live Supabase.

Run with: pytest tests/test_attribution_ws1_engine_fixes.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from viraltracker.services.ad_intelligence.ad_intelligence_service import AdIntelligenceService
from viraltracker.services.ad_intelligence.chat_renderer import ChatRenderer
from viraltracker.services.ad_intelligence.models import AccountAnalysisResult


class _FakeQuery:
    """Minimal Supabase query-builder stand-in for _get_total_spend.

    Records whether ``.in_()`` was called (and with what) so we can assert
    scoping behavior, and returns ``pages`` one per ``.execute()`` call so the
    pagination loop terminates."""

    def __init__(self, pages):
        self._pages = pages
        self._idx = 0
        self.in_called_with = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def in_(self, col, vals):
        self.in_called_with = (col, list(vals))
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        idx = self._idx
        self._idx += 1
        data = self._pages[idx] if idx < len(self._pages) else []
        return MagicMock(data=data)


def _service_with_query(fake_query):
    svc = AdIntelligenceService(MagicMock())
    svc.supabase = MagicMock()
    svc.supabase.table.return_value = fake_query
    return svc


# ---------------------------------------------------------------------------
# WS1.1 — _get_total_spend scoping
# ---------------------------------------------------------------------------


class TestGetTotalSpendScoping:

    @pytest.mark.asyncio
    async def test_brand_level_sums_all_rows_no_in_filter(self):
        """ad_ids=None → account-wide sum, no .in_() filter (unchanged)."""
        from datetime import date
        fq = _FakeQuery(pages=[[{"spend": "100"}, {"spend": "50.50"}]])
        svc = _service_with_query(fq)

        total = await svc._get_total_spend(
            uuid4(), date(2026, 5, 1), date(2026, 5, 31), ad_ids=None
        )
        assert total == 150.50
        assert fq.in_called_with is None  # no scoping applied

    @pytest.mark.asyncio
    async def test_product_scope_applies_in_filter(self):
        """ad_ids=[...] → sum scoped via .in_("meta_ad_id", ad_ids)."""
        from datetime import date
        fq = _FakeQuery(pages=[[{"spend": "3000"}, {"spend": "137.67"}]])
        svc = _service_with_query(fq)

        ad_ids = ["ad_a", "ad_b", "ad_c"]
        total = await svc._get_total_spend(
            uuid4(), date(2026, 5, 1), date(2026, 5, 31), ad_ids=ad_ids
        )
        assert total == 3137.67
        assert fq.in_called_with == ("meta_ad_id", ad_ids)

    @pytest.mark.asyncio
    async def test_empty_ad_ids_returns_zero_without_query(self):
        """An empty product scope means 0 ads → 0 spend, no DB round-trip."""
        from datetime import date
        fq = _FakeQuery(pages=[[{"spend": "9999"}]])  # would be summed if queried
        svc = _service_with_query(fq)

        total = await svc._get_total_spend(
            uuid4(), date(2026, 5, 1), date(2026, 5, 31), ad_ids=[]
        )
        assert total == 0.0
        assert fq._idx == 0  # execute() never called


# ---------------------------------------------------------------------------
# WS1.2 — product∈brand validation (service layer)
# ---------------------------------------------------------------------------


def _service_with_product_owner(owner_brand_id):
    """Service whose products lookup returns the given owner brand (or no row
    if owner_brand_id is None)."""
    svc = AdIntelligenceService(MagicMock())
    svc.supabase = MagicMock()
    data = [] if owner_brand_id is None else [{"brand_id": owner_brand_id}]
    svc.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=data
    )
    return svc


class TestProductBrandValidation:

    @pytest.mark.asyncio
    async def test_cross_brand_product_raises(self):
        brand_id = uuid4()
        other_brand = uuid4()
        product_id = uuid4()
        svc = _service_with_product_owner(str(other_brand))

        with pytest.raises(ValueError, match="cross-brand|belongs to brand"):
            await svc.full_analysis(
                brand_id=brand_id, org_id=uuid4(), product_id=product_id
            )

    @pytest.mark.asyncio
    async def test_missing_product_raises(self):
        svc = _service_with_product_owner(None)  # no product row
        with pytest.raises(ValueError, match="does not exist"):
            await svc.full_analysis(
                brand_id=uuid4(), org_id=uuid4(), product_id=uuid4()
            )


# ---------------------------------------------------------------------------
# WS1.3 — no-ads-in-scope rendering
# ---------------------------------------------------------------------------


class TestNoAdsInScopeRendering:

    def test_renderer_shows_explicit_no_ads_message(self):
        result = AccountAnalysisResult(
            run_id=uuid4(),
            brand_name="Martin Clinic",
            date_range="Last 30 days",
            total_ads=0,
            active_ads=0,
            total_spend=0.0,
            no_ads_in_scope=True,
        )
        md = ChatRenderer.render_account_analysis(result)
        assert "No active ads in scope" in md
        assert "Martin Clinic" in md
        # Must NOT render the normal analysis table for an empty scope.
        assert "Awareness Distribution" not in md

    def test_default_flag_is_false_and_normal_render_unaffected(self):
        result = AccountAnalysisResult(
            run_id=uuid4(),
            brand_name="Martin Clinic",
            date_range="Last 30 days",
            total_ads=5,
            active_ads=5,
            total_spend=3137.67,
        )
        assert result.no_ads_in_scope is False
        md = ChatRenderer.render_account_analysis(result)
        assert "No active ads in scope" not in md
        assert "Total Spend**: $3,137.67" in md
