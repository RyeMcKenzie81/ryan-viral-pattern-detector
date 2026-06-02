"""Tests for WS3 — wire destination→product + self-heal bridge + canonical collision.

Covers:

1. ``ProductOfferVariantService.sync_landing_page_for_variant`` — the bridge that
   makes attribution self-heal: tagging an offer variant must set
   ``brand_landing_pages.product_id`` (what attribution actually reads), matching
   on CANONICAL url so it updates the existing scraped row rather than inserting a
   colliding duplicate, and never overwriting an existing product tag.
2. ``MetaAdsService.match_destinations_to_landing_pages`` canonical-collision
   handling — prefer a product-tagged row; when two rows share a canonical but
   disagree on product, attribute to NONE and surface it as ambiguous.

Mock-based — no live Supabase.

Run with: pytest tests/test_attribution_ws3_wire_and_selfheal.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Flexible fake Supabase (records writes, answers reads via a store callable)
# ---------------------------------------------------------------------------


class _Q:
    def __init__(self, table, store, recorder):
        self.table = table
        self.store = store
        self.recorder = recorder
        self.cols = None
        self.filters = {}
        self._op = "select"
        self._payload = None

    def select(self, cols):
        self.cols = cols
        self._op = "select"
        return self

    def insert(self, rec):
        self._op = "insert"
        self._payload = rec
        return self

    def update(self, rec):
        self._op = "update"
        self._payload = rec
        return self

    def upsert(self, rec, on_conflict=None):
        self._op = "upsert"
        self._payload = rec
        return self

    def eq(self, c, v):
        self.filters[c] = v
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def range(self, *a):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self._op in ("insert", "update", "upsert"):
            self.recorder.append({
                "op": self._op, "table": self.table,
                "payload": self._payload, "filters": dict(self.filters),
            })
            return SimpleNamespace(data=[{"id": "written"}])
        data = self.store(self.table, self.cols, self.filters)
        return SimpleNamespace(data=list(data) if data else [])


class _Supa:
    def __init__(self, store):
        self.store = store
        self.recorder = []

    def table(self, name):
        return _Q(name, self.store, self.recorder)


# ---------------------------------------------------------------------------
# WS3.2 — sync_landing_page_for_variant (the self-heal bridge)
# ---------------------------------------------------------------------------


def _make_service(store):
    from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
    fake = _Supa(store)
    with patch("viraltracker.services.product_offer_variant_service.get_supabase_client", return_value=fake):
        svc = ProductOfferVariantService()
    svc.supabase = fake
    return svc, fake


class TestSyncLandingPageForVariant:

    def test_tags_existing_untagged_row_by_canonical(self):
        product_id = uuid4()

        def store(table, cols, filters):
            if table == "products":
                return [{"brand_id": "BRAND"}]
            if table == "brand_landing_pages" and "canonical_url" in filters:
                # existing scraped row, no product yet
                return [{"id": "lp1", "product_id": None, "canonical_url": "us.b.com/lp"}]
            return []

        svc, fake = _make_service(store)
        # The variant URL differs only by trailing slash → same canonical.
        with patch("viraltracker.services.url_canonicalizer.canonicalize_url",
                   return_value="us.b.com/lp"):
            ok = svc.sync_landing_page_for_variant(product_id, "https://us.b.com/lp/")
        assert ok is True
        updates = [w for w in fake.recorder if w["op"] == "update"]
        assert len(updates) == 1
        assert updates[0]["payload"]["product_id"] == str(product_id)
        assert updates[0]["filters"]["id"] == "lp1"
        # No duplicate insert.
        assert not [w for w in fake.recorder if w["op"] == "insert"]

    def test_does_not_overwrite_existing_product_tag(self):
        product_id = uuid4()
        other = str(uuid4())

        def store(table, cols, filters):
            if table == "products":
                return [{"brand_id": "BRAND"}]
            if table == "brand_landing_pages" and "canonical_url" in filters:
                return [{"id": "lp1", "product_id": other, "canonical_url": "us.b.com/lp"}]
            return []

        svc, fake = _make_service(store)
        with patch("viraltracker.services.url_canonicalizer.canonicalize_url",
                   return_value="us.b.com/lp"):
            svc.sync_landing_page_for_variant(product_id, "https://us.b.com/lp")
        # canonical already set + product already tagged → nothing to update.
        assert not [w for w in fake.recorder if w["op"] in ("update", "insert")]

    def test_inserts_when_no_row_exists(self):
        product_id = uuid4()

        def store(table, cols, filters):
            if table == "products":
                return [{"brand_id": "BRAND"}]
            return []  # no landing page by canonical or by url

        svc, fake = _make_service(store)
        with patch("viraltracker.services.url_canonicalizer.canonicalize_url",
                   return_value="us.b.com/new"):
            ok = svc.sync_landing_page_for_variant(product_id, "https://us.b.com/new")
        assert ok is True
        inserts = [w for w in fake.recorder if w["op"] == "insert"]
        assert len(inserts) == 1
        rec = inserts[0]["payload"]
        assert rec["product_id"] == str(product_id)
        assert rec["canonical_url"] == "us.b.com/new"
        assert rec["brand_id"] == "BRAND"

    def test_missing_product_is_noop(self):
        def store(table, cols, filters):
            return []  # product not found

        svc, fake = _make_service(store)
        with patch("viraltracker.services.url_canonicalizer.canonicalize_url",
                   return_value="x"):
            ok = svc.sync_landing_page_for_variant(uuid4(), "https://x")
        assert ok is False
        assert fake.recorder == []

    def test_empty_url_is_noop(self):
        svc, fake = _make_service(lambda *a: [])
        assert svc.sync_landing_page_for_variant(uuid4(), "") is False
        assert fake.recorder == []


# ---------------------------------------------------------------------------
# WS3.3 — match_destinations_to_landing_pages canonical collision
# ---------------------------------------------------------------------------


def _match_store(dests, lps):
    def store(table, cols, filters):
        if table == "meta_ad_destinations":
            return dests
        if table == "brand_landing_pages":
            return lps
        return []
    return store


async def _run_match(dests, lps):
    from viraltracker.services.meta_ads_service import MetaAdsService
    fake = _Supa(_match_store(dests, lps))
    svc = MetaAdsService(access_token="fake")
    with patch("viraltracker.core.database.get_supabase_client", return_value=fake):
        return await svc.match_destinations_to_landing_pages(uuid4())


class TestMatchCanonicalCollision:

    @pytest.mark.asyncio
    async def test_ambiguous_when_two_products_share_canonical(self):
        dests = [{"meta_ad_id": "ad1", "destination_url": "https://b.com/x", "canonical_url": "b.com/x"}]
        lps = [
            {"id": "lpA", "url": "https://b.com/x", "canonical_url": "b.com/x", "product_id": "P1"},
            {"id": "lpB", "url": "https://b.com/x?", "canonical_url": "b.com/x", "product_id": "P2"},
        ]
        result = await _run_match(dests, lps)
        # Conflicting products → attributed to NONE.
        assert result["matches"] == []
        assert len(result["ambiguous"]) == 1
        amb = result["ambiguous"][0]
        assert amb["canonical_url"] == "b.com/x"
        assert set(amb["product_ids"]) == {"P1", "P2"}

    @pytest.mark.asyncio
    async def test_prefers_tagged_row_over_untagged(self):
        dests = [{"meta_ad_id": "ad1", "destination_url": "https://b.com/x", "canonical_url": "b.com/x"}]
        lps = [
            {"id": "lpUntagged", "url": "https://b.com/x", "canonical_url": "b.com/x", "product_id": None},
            {"id": "lpTagged", "url": "https://b.com/x", "canonical_url": "b.com/x", "product_id": "P1"},
        ]
        result = await _run_match(dests, lps)
        assert len(result["matches"]) == 1
        assert result["matches"][0]["landing_page_id"] == "lpTagged"
        assert result["ambiguous"] == []

    @pytest.mark.asyncio
    async def test_single_tagged_row_matches(self):
        dests = [{"meta_ad_id": "ad1", "destination_url": "https://b.com/x", "canonical_url": "b.com/x"}]
        lps = [{"id": "lp1", "url": "https://b.com/x", "canonical_url": "b.com/x", "product_id": "P1"}]
        result = await _run_match(dests, lps)
        assert result["matches"][0]["landing_page_id"] == "lp1"

    @pytest.mark.asyncio
    async def test_unmatched_when_no_lp(self):
        dests = [{"meta_ad_id": "ad1", "destination_url": "https://b.com/x", "canonical_url": "b.com/x"}]
        result = await _run_match(dests, [])
        assert result["matches"] == []
        assert result["unmatched_count"] == 1
