"""Tests for MetaAdsService ad-account currency capture (WS5 foundation).

get_brand_currency returns the ad-SPEND currency (the primary account's billing
currency), self-healing from Meta when unset.

Run with: pytest tests/test_meta_account_currency.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from viraltracker.services.meta_ads_service import MetaAdsService


def _db_with_currency(cur):
    db = MagicMock()
    (db.table.return_value.select.return_value.eq.return_value.eq.return_value
       .limit.return_value.execute.return_value) = MagicMock(data=[{"currency": cur}])
    return db


class TestGetBrandCurrency:
    @pytest.mark.asyncio
    async def test_returns_stored_currency_without_meta_call(self):
        svc = MetaAdsService(access_token="fake")
        svc.fetch_account_currency = AsyncMock()  # must NOT be called
        db = _db_with_currency("CAD")
        with patch("viraltracker.core.database.get_supabase_client", return_value=db):
            cur = await svc.get_brand_currency(uuid4())
        assert cur == "CAD"
        svc.fetch_account_currency.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_fetches_and_persists_when_null(self):
        svc = MetaAdsService(access_token="fake")
        svc.fetch_account_currency = AsyncMock(return_value="CAD")
        db = _db_with_currency(None)
        with patch("viraltracker.core.database.get_supabase_client", return_value=db):
            cur = await svc.get_brand_currency(uuid4())
        assert cur == "CAD"
        svc.fetch_account_currency.assert_awaited_once()
        db.table.return_value.update.assert_called()  # persisted for next time

    @pytest.mark.asyncio
    async def test_falls_back_to_default_when_meta_has_none(self):
        svc = MetaAdsService(access_token="fake")
        svc.fetch_account_currency = AsyncMock(return_value=None)
        db = _db_with_currency(None)
        with patch("viraltracker.core.database.get_supabase_client", return_value=db):
            cur = await svc.get_brand_currency(uuid4(), default="USD")
        assert cur == "USD"

    def test_fetch_sync_parses_adaccount_currency(self):
        svc = MetaAdsService(access_token="fake")
        with patch("facebook_business.adobjects.adaccount.AdAccount") as AA:
            AA.return_value.api_get.return_value = {"currency": "CAD"}
            cur = svc._fetch_account_currency_sync("act_123")
        assert cur == "CAD"
        AA.return_value.api_get.assert_called_once()
        assert "currency" in AA.return_value.api_get.call_args.kwargs["fields"]
