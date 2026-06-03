"""Tests for BrandMarketService — per-brand host → market resolution + CRUD.

Run with: pytest tests/test_brand_market_service.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from viraltracker.services.brand_market_service import (
    BrandMarketService, host_of, _norm_hosts,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHostOf:
    def test_strips_scheme_and_lowercases(self):
        assert host_of("https://US.Martinclinic.com/pages/x") == "us.martinclinic.com"

    def test_tolerates_missing_scheme(self):
        assert host_of("martinclinic.com/pages/probiotic") == "martinclinic.com"

    def test_strips_port(self):
        assert host_of("http://example.com:8080/p") == "example.com"

    def test_empty(self):
        assert host_of("") == ""
        assert host_of(None) == ""


class TestNormHosts:
    def test_lowercase_dedup_and_bare_host(self):
        assert _norm_hosts(["US.Martin.com", "https://us.martin.com/x", "martin.com"]) == \
            ["us.martin.com", "martin.com"]


# ---------------------------------------------------------------------------
# resolve_market_for_url
# ---------------------------------------------------------------------------


class TestResolveMarket:
    def _svc(self, markets):
        svc = BrandMarketService(supabase_client=MagicMock())
        svc.list_markets = lambda brand_id: markets
        return svc

    def test_exact_host_match(self):
        svc = self._svc([
            {"code": "US", "currency": "USD", "host_patterns": ["us.martinclinic.com"], "is_default": True},
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ])
        assert svc.resolve_market_for_url(uuid4(), "https://martinclinic.com/pages/probiotic")["code"] == "CA"
        assert svc.resolve_market_for_url(uuid4(), "https://us.martinclinic.com/pages/v3-adv")["code"] == "US"

    def test_falls_back_to_default_when_no_host_match(self):
        svc = self._svc([
            {"code": "US", "currency": "USD", "host_patterns": ["us.martinclinic.com"], "is_default": True},
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ])
        m = svc.resolve_market_for_url(uuid4(), "https://some-other-domain.com/lp")
        assert m["code"] == "US"  # the default

    def test_none_when_no_match_and_no_default(self):
        svc = self._svc([
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ])
        assert svc.resolve_market_for_url(uuid4(), "https://elsewhere.com") is None

    def test_case_insensitive_host(self):
        svc = self._svc([
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ])
        assert svc.resolve_market_for_url(uuid4(), "https://MARTINCLINIC.com/x")["code"] == "CA"

    def test_www_host_matches_bare_pattern(self):
        """A bare-host pattern must match a www-prefixed destination (www is
        stripped on both sides), regardless of raw vs canonical URL field."""
        svc = self._svc([
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ])
        assert svc.resolve_market_for_url(uuid4(), "https://www.martinclinic.com/pages/x")["code"] == "CA"

    def test_www_pattern_normalized_so_it_matches_bare_host(self):
        """A pattern entered WITH www still matches a bare host (both normalize)."""
        svc = self._svc([
            {"code": "CA", "currency": "CAD", "host_patterns": ["www.martinclinic.com"], "is_default": False},
        ])
        # host_patterns as stored would be normalized by _norm_hosts on write;
        # simulate the stored (bare) form to mirror production.
        svc2 = self._svc([
            {"code": "CA", "currency": "CAD", "host_patterns": [_norm_hosts(["www.martinclinic.com"])[0]], "is_default": False},
        ])
        assert svc2.resolve_market_for_url(uuid4(), "https://martinclinic.com/x")["code"] == "CA"


# ---------------------------------------------------------------------------
# create_market normalization + default-clearing
# ---------------------------------------------------------------------------


class _FakeTable:
    def __init__(self, name, rec):
        self.name = name
        self.rec = rec
        self._op = "select"
        self._payload = None

    def select(self, *a):
        self._op = "select"
        return self

    def insert(self, r):
        self._payload = r
        self.rec.append(("insert", self.name, r))
        return self

    def update(self, r):
        self._op = "update"
        self._payload = r
        self.rec.append(("update", self.name, r))
        return self

    def delete(self):
        self.rec.append(("delete", self.name))
        return self

    def eq(self, *a):
        return self

    def neq(self, *a):
        return self

    def order(self, *a):
        return self

    def limit(self, *a):
        return self

    def execute(self):
        if self._op == "select":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[self._payload] if self._payload else [{"id": "x"}])


class _FakeSupa:
    def __init__(self):
        self.rec = []

    def table(self, name):
        return _FakeTable(name, self.rec)


class TestCreateMarket:
    def test_normalizes_and_clears_default(self):
        fake = _FakeSupa()
        svc = BrandMarketService(supabase_client=fake)
        svc.create_market(
            uuid4(), code="ca", label="Canada", currency="cad",
            host_patterns=["MARTINCLINIC.com", "https://martinclinic.com/x"], is_default=True,
        )
        # is_default=True → defaults cleared (an update) BEFORE the insert.
        ops = [r[0] for r in fake.rec]
        assert ops == ["update", "insert"]
        insert = next(r for r in fake.rec if r[0] == "insert")[2]
        assert insert["code"] == "CA"          # upper
        assert insert["currency"] == "CAD"     # upper
        assert insert["host_patterns"] == ["martinclinic.com"]  # lowercased + de-duped
        assert insert["is_default"] is True

    def test_no_clear_when_not_default(self):
        fake = _FakeSupa()
        svc = BrandMarketService(supabase_client=fake)
        svc.create_market(uuid4(), code="US", currency="USD", host_patterns=["us.martinclinic.com"])
        ops = [r[0] for r in fake.rec]
        assert ops == ["insert"]  # no default-clearing update


class TestUpdateMarket:
    def test_normalizes_fields_and_stamps_updated_at(self):
        fake = _FakeSupa()
        svc = BrandMarketService(supabase_client=fake)
        svc.update_market("mkt-1", {"code": "ca", "currency": "cad", "host_patterns": ["WWW.Martin.com"]})
        upd = next(r for r in fake.rec if r[0] == "update")[2]
        assert upd["code"] == "CA"
        assert upd["currency"] == "CAD"
        assert upd["host_patterns"] == ["martin.com"]   # www stripped + lowercased
        assert "updated_at" in upd


# ---------------------------------------------------------------------------
# split_spend_by_market
# ---------------------------------------------------------------------------


class _SplitTable:
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
            return SimpleNamespace(data=[])  # page 2 is empty → terminate loop
        rows = list(self.data_map.get(self.name, []))
        if "meta_ad_id" in self.ins:
            rows = [r for r in rows if r.get("meta_ad_id") in self.ins["meta_ad_id"]]
        return SimpleNamespace(data=rows)


class _SplitSupa:
    def __init__(self, data_map):
        self.data_map = data_map

    def table(self, name):
        return _SplitTable(name, self.data_map)


class TestSplitSpendByMarket:
    def _svc(self, data_map, markets):
        svc = BrandMarketService(supabase_client=_SplitSupa(data_map))
        svc.list_markets = lambda brand_id: markets
        return svc

    def test_splits_us_ca_and_unknown(self):
        markets = [
            {"code": "US", "currency": "USD", "host_patterns": ["us.martinclinic.com"], "is_default": False},
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ]
        data_map = {
            "meta_ad_destinations": [
                {"meta_ad_id": "ad1", "canonical_url": "https://us.martinclinic.com/pages/v3-adv"},
                {"meta_ad_id": "ad2", "canonical_url": "https://martinclinic.com/pages/navitol"},
                {"meta_ad_id": "ad3", "canonical_url": "https://elsewhere.com/x"},
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "ad1", "spend": "100", "purchases": "2"},
                {"meta_ad_id": "ad2", "spend": "50", "purchases": "1"},
                {"meta_ad_id": "ad3", "spend": "30", "purchases": "0"},
            ],
        }
        svc = self._svc(data_map, markets)
        out = svc.split_spend_by_market(uuid4(), ["ad1", "ad2", "ad3"], "2026-05-01", "2026-05-31")
        assert out["US"] == {"spend": 100.0, "purchases": 2, "ads": 1, "currency": "USD", "cpa": 50.0}
        assert out["CA"] == {"spend": 50.0, "purchases": 1, "ads": 1, "currency": "CAD", "cpa": 50.0}
        # ad3 host matches no market and there's no default → UNKNOWN, CPA None (0 purchases)
        assert out["UNKNOWN"]["spend"] == 30.0
        assert out["UNKNOWN"]["cpa"] is None
        assert out["UNKNOWN"]["currency"] is None

    def test_unmatched_host_falls_to_default_market(self):
        markets = [
            {"code": "US", "currency": "USD", "host_patterns": ["us.martinclinic.com"], "is_default": True},
            {"code": "CA", "currency": "CAD", "host_patterns": ["martinclinic.com"], "is_default": False},
        ]
        data_map = {
            "meta_ad_destinations": [
                {"meta_ad_id": "adX", "canonical_url": "https://random.com/y"},
            ],
            "meta_ads_performance": [
                {"meta_ad_id": "adX", "spend": "20", "purchases": "4"},
            ],
        }
        svc = self._svc(data_map, markets)
        out = svc.split_spend_by_market(uuid4(), ["adX"], "2026-05-01", "2026-05-31")
        assert "US" in out and "UNKNOWN" not in out  # default soaks up the unmatched host
        assert out["US"]["cpa"] == 5.0

    def test_empty_ad_ids(self):
        svc = self._svc({}, [])
        assert svc.split_spend_by_market(uuid4(), [], "2026-05-01", "2026-05-31") == {}
