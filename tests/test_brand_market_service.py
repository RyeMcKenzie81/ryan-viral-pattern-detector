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
