"""Tests for WS2 — destination-URL capture fixes.

Covers the four WS2 changes from the attribution design:

1. ``_fetch_ad_destinations_sync`` makes ONE Graph call per ad (field expansion)
   and returns a per-ad outcome dict (url / fetch_ok / creative_id / url_count).
   Transient errors omit the ad (retried next run); a fetched-but-linkless
   creative is a terminal "no url".
2. ``_extract_destination_from_creative`` resolves the URL via the documented
   waterfall and counts distinct DCO links for the multi-URL flag.
3. ``_select_missing_destination_ads`` ranks missing ads by recent spend and
   excludes already-found ads and terminally-marked (no_url) ads.
4. ``sync_ad_destinations_to_db`` stores found URLs, writes terminal ``no_url``
   markers (only on fetch_ok), flags ``multi_url`` ads, and never marks a
   transient failure.

Mock-based — no live Meta or Supabase.

Run with: pytest tests/test_attribution_ws2_destination_capture.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from viraltracker.services.meta_ads_service import MetaAdsService


# ---------------------------------------------------------------------------
# WS2.2 — _extract_destination_from_creative (pure)
# ---------------------------------------------------------------------------


class TestExtractDestinationFromCreative:

    def test_direct_link_url(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"link_url": "https://us.brand.com/p"}
        )
        assert url == "https://us.brand.com/p"
        assert n == 1

    def test_object_story_link_data(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"object_story_spec": {"link_data": {"link": "https://b.com/lp"}}}
        )
        assert url == "https://b.com/lp"
        assert n == 1

    def test_link_data_cta_value(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"object_story_spec": {"link_data": {
                "call_to_action": {"value": {"link": "https://b.com/cta"}}
            }}}
        )
        assert url == "https://b.com/cta"

    def test_video_data_cta_value(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"object_story_spec": {"video_data": {
                "call_to_action": {"value": {"link": "https://b.com/vid"}}
            }}}
        )
        assert url == "https://b.com/vid"

    def test_dco_multiple_distinct_links_flags_count(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"asset_feed_spec": {"link_urls": [
                {"website_url": "https://b.com/a"},
                {"website_url": "https://b.com/b"},
                {"website_url": "https://b.com/a"},  # dup → not double-counted
            ]}}
        )
        assert url == "https://b.com/a"  # first link attributed
        assert n == 2  # two DISTINCT links → multi-URL

    def test_dco_single_link_count_one(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"asset_feed_spec": {"link_urls": ["https://b.com/only"]}}
        )
        assert url == "https://b.com/only"
        assert n == 1

    def test_no_link_anywhere(self):
        url, n = MetaAdsService._extract_destination_from_creative(
            {"object_story_spec": {"link_data": {}}}
        )
        assert url is None
        assert n == 0


# ---------------------------------------------------------------------------
# WS2.1 — _fetch_ad_destinations_sync (one call/ad, outcome shape)
# ---------------------------------------------------------------------------


class TestFetchAdDestinationsSync:

    def _run(self, ad_ids):
        svc = MetaAdsService(access_token="fake")
        created = {}

        def make_ad(ad_id):
            m = MagicMock(name=f"Ad({ad_id})")
            if ad_id == "transient":
                m.api_get.side_effect = RuntimeError("rate limited (#80004)")
            elif ad_id == "nocreative":
                m.api_get.return_value = {"id": ad_id}
            elif ad_id == "nolink":
                # Link fields present but empty → genuinely no link → TERMINAL.
                m.api_get.return_value = {
                    "id": ad_id,
                    "creative": {"id": "c_nolink", "object_story_spec": {"link_data": {}}},
                }
            elif ad_id == "inconclusive":
                # Expansion returned only {id} (no link fields) → inconclusive.
                m.api_get.return_value = {"id": ad_id, "creative": {"id": "c_incon"}}
            else:
                m.api_get.return_value = {
                    "id": ad_id,
                    "creative": {"id": "c_good", "link_url": "https://b.com/p"},
                }
            created[ad_id] = m
            return m

        with patch("facebook_business.adobjects.ad.Ad", side_effect=make_ad):
            outcomes = svc._fetch_ad_destinations_sync(ad_ids)
        return outcomes, created

    def test_found_url_outcome(self):
        outcomes, created = self._run(["good"])
        assert outcomes["good"] == {
            "url": "https://b.com/p", "fetch_ok": True,
            "creative_id": "c_good", "url_count": 1,
        }
        # The 2→1 win: exactly one Graph call for the ad.
        assert created["good"].api_get.call_count == 1

    def test_single_call_uses_field_expansion(self):
        _, created = self._run(["good"])
        fields = created["good"].api_get.call_args.kwargs["fields"]
        # creative is expanded inline rather than fetched in a second call.
        assert any("creative{" in f for f in fields)

    def test_no_creative_is_terminal(self):
        outcomes, _ = self._run(["nocreative"])
        assert outcomes["nocreative"]["fetch_ok"] is True
        assert outcomes["nocreative"]["url"] is None

    def test_creative_with_empty_link_fields_is_terminal(self):
        outcomes, _ = self._run(["nolink"])
        assert outcomes["nolink"]["fetch_ok"] is True
        assert outcomes["nolink"]["url"] is None
        assert outcomes["nolink"]["creative_id"] == "c_nolink"

    def test_creative_without_any_link_fields_is_inconclusive(self):
        """Field expansion returning only {id} must NOT mark terminal — else a
        real-URL ad could be permanently excluded by an SDK/permission quirk."""
        outcomes, _ = self._run(["inconclusive", "good"])
        assert "inconclusive" not in outcomes  # omitted → retried next run
        assert "good" in outcomes

    def test_transient_error_is_omitted(self):
        outcomes, _ = self._run(["transient", "good"])
        # Transient ad is NOT in the outcomes → no marker written → retried.
        assert "transient" not in outcomes
        assert "good" in outcomes


# ---------------------------------------------------------------------------
# Fake Supabase for selection + storage tests
# ---------------------------------------------------------------------------


class _FakeBuilder:
    def __init__(self, table, data_map, recorder):
        self._table = table
        self._data_map = data_map
        self._recorder = recorder
        self._cols = None

    def select(self, cols):
        self._cols = cols
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._data_map.get((self._table, self._cols), [])))

    def upsert(self, record, on_conflict=None):
        self._recorder.append({"table": self._table, "record": record, "on_conflict": on_conflict})
        return self


class _FakeSupabase:
    def __init__(self, data_map):
        self.data_map = data_map
        self.upserts = []

    def table(self, name):
        return _FakeBuilder(name, self.data_map, self.upserts)


# ---------------------------------------------------------------------------
# WS2.3 — _select_missing_destination_ads (spend-prioritized, exclusions)
# ---------------------------------------------------------------------------


class TestSelectMissingDestinationAds:

    def test_spend_ranked_excludes_found_and_terminal(self):
        brand = uuid4()
        data_map = {
            ("meta_ad_destinations", "meta_ad_id"): [{"meta_ad_id": "adF"}],          # found
            ("meta_ad_destination_status", "meta_ad_id"): [{"meta_ad_id": "adT"}],    # terminal
            ("meta_ads_performance", "meta_ad_id, spend"): [
                {"meta_ad_id": "adH", "spend": "5000"},
                {"meta_ad_id": "adL", "spend": "10"},
                {"meta_ad_id": "adF", "spend": "9999"},   # found → excluded
                {"meta_ad_id": "adT", "spend": "8888"},   # terminal → excluded
            ],
            ("meta_ads_performance", "meta_ad_id"): [
                {"meta_ad_id": "adH"}, {"meta_ad_id": "adL"},
                {"meta_ad_id": "adF"}, {"meta_ad_id": "adT"},
                {"meta_ad_id": "adZ"},  # no recent spend → spend 0
            ],
        }
        svc = MetaAdsService(access_token="fake")
        picked = svc._select_missing_destination_ads(
            _FakeSupabase(data_map), brand, limit=10, spend_window_days=30
        )
        # Excludes found + terminal; ranks by spend desc; adZ (0 spend) last.
        assert picked == ["adH", "adL", "adZ"]

    def test_limit_caps_to_highest_spend(self):
        brand = uuid4()
        data_map = {
            ("meta_ad_destinations", "meta_ad_id"): [],
            ("meta_ad_destination_status", "meta_ad_id"): [],
            ("meta_ads_performance", "meta_ad_id, spend"): [
                {"meta_ad_id": "a", "spend": "1"},
                {"meta_ad_id": "b", "spend": "100"},
                {"meta_ad_id": "c", "spend": "50"},
            ],
            ("meta_ads_performance", "meta_ad_id"): [
                {"meta_ad_id": "a"}, {"meta_ad_id": "b"}, {"meta_ad_id": "c"},
            ],
        }
        svc = MetaAdsService(access_token="fake")
        picked = svc._select_missing_destination_ads(
            _FakeSupabase(data_map), brand, limit=2, spend_window_days=30
        )
        assert picked == ["b", "c"]  # top-2 by spend


# ---------------------------------------------------------------------------
# WS2.4 — sync_ad_destinations_to_db storage + markers
# ---------------------------------------------------------------------------


class TestSyncStorageAndMarkers:

    @pytest.mark.asyncio
    async def test_stores_found_marks_no_url_and_multi_url_skips_transient(self):
        brand = uuid4()
        org = uuid4()
        fake = _FakeSupabase({})  # ad_ids provided → no selection queries
        outcomes = {
            "adFound": {"url": "https://b.com/p", "fetch_ok": True, "creative_id": "c1", "url_count": 1},
            "adMulti": {"url": "https://b.com/a", "fetch_ok": True, "creative_id": "c2", "url_count": 3},
            "adNo":    {"url": None, "fetch_ok": True, "creative_id": "c3", "url_count": 0},
            # adTransient intentionally absent from outcomes
        }
        svc = MetaAdsService(access_token="fake")
        svc.fetch_ad_destination_urls = AsyncMock(return_value=outcomes)

        with patch("viraltracker.core.database.get_supabase_client", return_value=fake):
            stats = await svc.sync_ad_destinations_to_db(
                brand_id=brand, organization_id=org,
                ad_ids=["adFound", "adMulti", "adNo", "adTransient"],
            )

        # Found URLs stored in meta_ad_destinations.
        dest_upserts = [u for u in fake.upserts if u["table"] == "meta_ad_destinations"]
        stored_ads = {u["record"]["meta_ad_id"] for u in dest_upserts}
        assert stored_ads == {"adFound", "adMulti"}

        # Status markers: multi_url for adMulti, no_url for adNo; nothing for transient.
        status_upserts = [u for u in fake.upserts if u["table"] == "meta_ad_destination_status"]
        by_ad = {u["record"]["meta_ad_id"]: u["record"]["status"] for u in status_upserts}
        assert by_ad == {"adMulti": "multi_url", "adNo": "no_url"}
        assert "adTransient" not in by_ad

        assert stats["stored"] == 2
        assert stats["no_url"] == 1
        assert stats["multi_url"] == 1

    @pytest.mark.asyncio
    async def test_transient_only_writes_no_markers(self):
        """A run where every ad hit a transient error writes nothing — so all
        ads are retried next run (no permanent give-up)."""
        brand, org = uuid4(), uuid4()
        fake = _FakeSupabase({})
        svc = MetaAdsService(access_token="fake")
        svc.fetch_ad_destination_urls = AsyncMock(return_value={})  # all omitted

        with patch("viraltracker.core.database.get_supabase_client", return_value=fake):
            stats = await svc.sync_ad_destinations_to_db(
                brand_id=brand, organization_id=org, ad_ids=["x", "y"],
            )
        assert fake.upserts == []
        assert stats == {"fetched": 0, "stored": 0, "matched": 0, "no_url": 0, "multi_url": 0}
