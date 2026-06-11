"""Tests for SyncHealthService — the sync-staleness + Meta-token monitor.

Uses a small fake Supabase (PostgREST-style chainable query) so the real
filter/order/limit logic in the service is exercised, not mocked away.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from viraltracker.services.sync_health_service import SyncHealthService

NOW = datetime(2026, 6, 11, 16, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


class FakeQuery:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.filters = {}
        self.null_filters = []          # (col, must_be_null)
        self._order = None
        self._desc = False
        self._limit = None
        self._range = None
        self._negate_next = False

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = ("__in__", list(vals))
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def is_(self, col, val):
        if val == "null":
            # .is_("col","null") -> must be null; .not_.is_(...) -> must NOT be null
            self.null_filters.append((col, not self._negate_next))
        self._negate_next = False
        return self

    def order(self, col, desc=False):
        self._order = col
        self._desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        return SimpleNamespace(data=self.store.resolve(
            self.table, self.filters, self.null_filters,
            self._order, self._desc, self._limit, self._range,
        ))


class FakeStore:
    def __init__(self, brands=None, jobs=None, runs=None, ad_accounts=None, cap=None):
        self.brands = brands or []
        self.jobs = jobs or []
        self.runs = runs or []          # each run has scheduled_job_id, status, completed_at
        self.ad_accounts = ad_accounts or []
        # Simulates the PostgREST per-response row cap for an UNRANGED read, so a
        # test fails if the service forgets to paginate (.range()).
        self.cap = cap

    def table(self, name):
        return FakeQuery(name, self)

    def _match(self, row, filters):
        for col, val in filters.items():
            if isinstance(val, tuple) and val and val[0] == "__in__":
                if row.get(col) not in val[1]:
                    return False
            elif row.get(col) != val:
                return False
        return True

    def _match_null(self, row, null_filters):
        for col, must_be_null in null_filters:
            if (row.get(col) is None) != must_be_null:
                return False
        return True

    def resolve(self, table, filters, null_filters, order, desc, limit, rng):
        data = {
            "brands": self.brands,
            "scheduled_jobs": self.jobs,
            "scheduled_job_runs": self.runs,
            "brand_ad_accounts": self.ad_accounts,
        }[table]
        rows = [r for r in data if self._match(r, filters) and self._match_null(r, null_filters)]
        if order:
            # Replicate Postgres null ordering: DESC -> NULLS FIRST, ASC -> NULLS LAST.
            rows = sorted(
                rows,
                key=lambda r: (r.get(order) is None, r.get(order) if r.get(order) is not None else ""),
                reverse=desc,
            )
        if rng is not None:
            rows = rows[rng[0]:rng[1] + 1]
        elif limit is not None:
            rows = rows[:limit]
        elif self.cap is not None:
            rows = rows[:self.cap]
        return rows


BRANDS = [
    {"id": "bX", "name": "BrandX", "organization_id": "orgX"},
    {"id": "bY", "name": "BrandY", "organization_id": "orgY"},
    {"id": "bZ", "name": "BrandZ", "organization_id": "orgZ"},
]


class TestCheckSyncStaleness:
    def _store(self):
        base = {"status": "active", "schedule_type": "recurring"}
        jobs = [
            {**base, "id": "jA", "brand_id": "bX", "job_type": "meta_sync", "name": "X Meta"},
            {**base, "id": "jB", "brand_id": "bY", "job_type": "meta_sync", "name": "Y Meta"},
            {**base, "id": "jC", "brand_id": "bZ", "job_type": "analytics_sync", "name": "Z GA"},
        ]
        runs = [
            # jA: fresh (10h ago)
            {"scheduled_job_id": "jA", "status": "completed", "completed_at": iso(NOW - timedelta(hours=10))},
            # jB: stale (100h ago) + a more recent FAILED run that must be ignored
            {"scheduled_job_id": "jB", "status": "completed", "completed_at": iso(NOW - timedelta(hours=100))},
            {"scheduled_job_id": "jB", "status": "failed", "completed_at": iso(NOW - timedelta(hours=2))},
            # jC: never completed (no completed runs at all)
        ]
        return FakeStore(brands=BRANDS, jobs=jobs, runs=runs)

    def test_flags_stale_and_never_succeeded_only(self):
        svc = SyncHealthService(supabase=self._store())
        stale = svc.check_sync_staleness(threshold_hours=48, now=NOW)
        names = {s["brand_name"] for s in stale}
        assert names == {"BrandY", "BrandZ"}        # BrandX (fresh) excluded

    def test_recent_failed_run_does_not_count_as_success(self):
        svc = SyncHealthService(supabase=self._store())
        stale = svc.check_sync_staleness(threshold_hours=48, now=NOW)
        bY = next(s for s in stale if s["brand_name"] == "BrandY")
        # last SUCCESS is 100h ago even though a failed run is 2h ago
        assert bY["hours_stale"] == 100.0

    def test_never_succeeded_sorts_first_and_has_null_age(self):
        svc = SyncHealthService(supabase=self._store())
        stale = svc.check_sync_staleness(threshold_hours=48, now=NOW)
        assert stale[0]["brand_name"] == "BrandZ"
        assert stale[0]["hours_stale"] is None
        assert stale[0]["organization_id"] == "orgZ"

    def test_respects_job_type_filter(self):
        svc = SyncHealthService(supabase=self._store())
        stale = svc.check_sync_staleness(threshold_hours=48, job_types=["analytics_sync"], now=NOW)
        assert {s["brand_name"] for s in stale} == {"BrandZ"}

    def test_completed_run_with_null_completed_at_is_ignored(self):
        # A 'completed' run with NULL completed_at must not be read as a success
        # nor mask the real (fresh) completion -> job is NOT stale.
        base = {"status": "active", "schedule_type": "recurring"}
        jobs = [{**base, "id": "jD", "brand_id": "bX", "job_type": "meta_sync", "name": "D"}]
        runs = [
            {"scheduled_job_id": "jD", "status": "completed", "completed_at": None},
            {"scheduled_job_id": "jD", "status": "completed", "completed_at": iso(NOW - timedelta(hours=10))},
        ]
        svc = SyncHealthService(supabase=FakeStore(brands=BRANDS, jobs=jobs, runs=runs))
        stale = svc.check_sync_staleness(threshold_hours=48, now=NOW)
        assert stale == []

    def test_pages_past_the_row_cap(self, monkeypatch):
        # With a tiny page size, all jobs across multiple pages must still be scanned.
        import viraltracker.services.sync_health_service as mod
        monkeypatch.setattr(mod, "_PAGE_SIZE", 2)
        base = {"status": "active", "schedule_type": "recurring", "job_type": "meta_sync"}
        jobs = [{**base, "id": f"j{i}", "brand_id": "bX", "name": f"J{i}"} for i in range(5)]
        # cap=2 simulates the server row cap: an unpaginated scan would see only 2.
        svc = SyncHealthService(supabase=FakeStore(brands=BRANDS, jobs=jobs, runs=[], cap=2))
        stale = svc.check_sync_staleness(threshold_hours=48, now=NOW)
        assert len(stale) == 5   # all 5 (never-succeeded) found despite page size 2


class TestCheckMetaTokenHealth:
    def _store(self):
        accounts = [
            {"brand_id": "bX", "meta_ad_account_id": "act_1", "auth_method": "oauth",
             "token_expires_at": iso(NOW + timedelta(days=30))},   # healthy
            {"brand_id": "bY", "meta_ad_account_id": "act_2", "auth_method": "oauth",
             "token_expires_at": iso(NOW + timedelta(days=3))},    # expiring
            {"brand_id": "bZ", "meta_ad_account_id": "act_3", "auth_method": "oauth",
             "token_expires_at": iso(NOW - timedelta(days=2))},    # expired
            {"brand_id": "bX", "meta_ad_account_id": "act_4", "auth_method": "app_secret",
             "token_expires_at": iso(NOW - timedelta(days=2))},    # not oauth -> ignored
        ]
        return FakeStore(brands=BRANDS, ad_accounts=accounts)

    def test_flags_expired_and_expiring_only(self):
        svc = SyncHealthService(supabase=self._store())
        out = svc.check_meta_token_health(warn_days=7, now=NOW)
        by_acct = {f["ad_account_id"]: f for f in out}
        assert set(by_acct) == {"act_2", "act_3"}
        assert by_acct["act_2"]["status"] == "expiring"
        assert by_acct["act_3"]["status"] == "expired"

    def test_app_secret_accounts_ignored(self):
        svc = SyncHealthService(supabase=self._store())
        out = svc.check_meta_token_health(warn_days=7, now=NOW)
        assert all(f["ad_account_id"] != "act_4" for f in out)

    def test_sorted_expired_first(self):
        svc = SyncHealthService(supabase=self._store())
        out = svc.check_meta_token_health(warn_days=7, now=NOW)
        assert out[0]["ad_account_id"] == "act_3"   # most-negative days_until_expiry


class TestSummarize:
    def test_severity_error_when_any_stale(self):
        svc = SyncHealthService(supabase=FakeStore())
        s = svc.summarize(
            stale=[{"brand_name": "Y", "job_type": "meta_sync", "hours_stale": 100, "last_success_at": "x"}],
            tokens=[],
        )
        assert s["severity"] == "error"
        assert "stale sync" in s["title"]

    def test_severity_error_when_token_expired(self):
        svc = SyncHealthService(supabase=FakeStore())
        s = svc.summarize(stale=[], tokens=[{"status": "expired"}])
        assert s["severity"] == "error"

    def test_severity_warning_when_only_expiring(self):
        svc = SyncHealthService(supabase=FakeStore())
        s = svc.summarize(stale=[], tokens=[{"status": "expiring"}])
        assert s["severity"] == "warning"

    def test_severity_none_when_all_healthy(self):
        svc = SyncHealthService(supabase=FakeStore())
        s = svc.summarize(stale=[], tokens=[])
        assert s["severity"] is None
        assert s["details"] == {"stale": [], "tokens": []}
