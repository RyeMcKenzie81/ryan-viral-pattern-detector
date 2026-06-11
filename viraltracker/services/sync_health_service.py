"""Sync health / staleness monitor.

Detects when scheduled data syncs have stopped succeeding and when Meta OAuth
tokens are near expiry, so a brand can't silently go stale for weeks (e.g. a
Meta sync failing on an invalidated token while nobody notices). Pure read-only
business logic — the scheduler handler (`sync_health_check`) calls this and emits
the alerts. Reusable by a UI panel later.

Staleness is computed from the actual run history (`scheduled_job_runs`): the most
recent `completed` run per active recurring sync job. A job with no completed run
in `threshold_hours` (or none ever) is stale. We deliberately scope to daily data
syncs (see DEFAULT_SYNC_JOB_TYPES) so weekly jobs aren't flagged as false positives.

Token health is Meta-only on purpose: `brand_ad_accounts.token_expires_at` is a
meaningful 60-day expiry. Google/Shopify `config.token_expiry` is the ~1h ACCESS
token (auto-refreshed), so it is NOT a staleness signal; the real Google risk
(a refresh token dying after 7 days in OAuth "Testing" mode) isn't observable
from stored data, and is caught indirectly by the staleness check on the GA
`analytics_sync` job.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Daily data-freshness syncs. Weekly/seo/reporting jobs are intentionally excluded
# so their normal cadence isn't misread as "stale". Override via job parameters.
DEFAULT_SYNC_JOB_TYPES: List[str] = [
    "meta_sync",
    "analytics_sync",
    "destination_sync",
    "asset_download",
]

# PostgREST caps a single response (default 1000 rows). A monitor must scan
# everything, so list reads page through with .range() up to this size.
_PAGE_SIZE = 1000


class SyncHealthService:
    """Read-only checks for stale syncs and expiring Meta tokens."""

    def __init__(self, supabase=None):
        if supabase is None:
            from viraltracker.core.database import get_supabase_client
            supabase = get_supabase_client()
        self.supabase = supabase

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_ts(value: Any) -> Optional[datetime]:
        """Parse a Supabase ISO timestamp into a tz-aware datetime (UTC default)."""
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                dt = value
            else:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _fetch_all(self, build_query) -> List[Dict[str, Any]]:
        """Page through a filtered query so the scan never silently stops at the
        PostgREST row cap (a partial scan would hide staleness). `build_query` must
        return a FRESH query builder each call (it is consumed by .range/.execute)."""
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            # Stable order by id is required: offset paging over an unordered
            # result is not guaranteed consistent across pages (rows could be
            # skipped or duplicated).
            page = build_query().order("id").range(offset, offset + _PAGE_SIZE - 1).execute()
            batch = page.data or []
            rows.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        return rows

    def _brand_lookup(self, brand_ids) -> Dict[str, Dict[str, Any]]:
        """Map brand_id -> {name, organization_id} for the given ids."""
        ids = sorted({b for b in brand_ids if b})
        if not ids:
            return {}
        res = self.supabase.table("brands").select(
            "id, name, organization_id"
        ).in_("id", ids).execute()
        return {r["id"]: r for r in (res.data or [])}

    # ------------------------------------------------------------- staleness
    def check_sync_staleness(
        self,
        threshold_hours: int = 48,
        job_types: Optional[List[str]] = None,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return active recurring sync jobs whose last successful run is older
        than `threshold_hours` (or that have never succeeded).

        Each finding: brand_id, brand_name, organization_id, job_type, job_name,
        last_success_at (ISO str or None), hours_stale (float or None if never).
        """
        job_types = job_types or DEFAULT_SYNC_JOB_TYPES
        now = now or datetime.now(timezone.utc)

        job_rows = self._fetch_all(lambda: self.supabase.table("scheduled_jobs").select(
            "id, brand_id, job_type, name"
        ).eq("status", "active").eq("schedule_type", "recurring").in_("job_type", job_types))
        if not job_rows:
            return []

        brands = self._brand_lookup({r.get("brand_id") for r in job_rows})
        stale: List[Dict[str, Any]] = []

        for job in job_rows:
            # Most recent genuinely-completed run. Exclude completed_at IS NULL so a
            # malformed completed row can't sort first (NULLS FIRST under DESC) and
            # be misread as 'never succeeded'.
            last = self.supabase.table("scheduled_job_runs").select(
                "completed_at"
            ).eq("scheduled_job_id", job["id"]).eq(
                "status", "completed"
            ).not_.is_("completed_at", "null").order(
                "completed_at", desc=True
            ).limit(1).execute()
            last_success_at = last.data[0]["completed_at"] if last.data else None

            hours_stale: Optional[float] = None
            if last_success_at:
                ts = self._parse_ts(last_success_at)
                if ts is not None:
                    hours_stale = (now - ts).total_seconds() / 3600.0

            is_stale = last_success_at is None or (
                hours_stale is not None and hours_stale > threshold_hours
            )
            if not is_stale:
                continue

            binfo = brands.get(job.get("brand_id"), {})
            stale.append({
                "brand_id": job.get("brand_id"),
                "brand_name": binfo.get("name", "(unknown)"),
                "organization_id": binfo.get("organization_id"),
                "job_type": job["job_type"],
                "job_name": job.get("name"),
                "last_success_at": last_success_at,
                "hours_stale": round(hours_stale, 1) if hours_stale is not None else None,
            })

        # Most stale first; "never succeeded" (None) is the worst -> treat as infinite.
        stale.sort(
            key=lambda s: s["hours_stale"] if s["hours_stale"] is not None else float("inf"),
            reverse=True,
        )
        return stale

    # --------------------------------------------------------- token health
    def check_meta_token_health(
        self,
        warn_days: int = 7,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return Meta OAuth ad-account tokens that are expired or expiring within
        `warn_days`. Each finding: brand_id, brand_name, organization_id, platform,
        ad_account_id, status ('expired'|'expiring'), expires_at, days_until_expiry.
        """
        now = now or datetime.now(timezone.utc)
        warn_cutoff = now + timedelta(days=warn_days)

        rows = self._fetch_all(lambda: self.supabase.table("brand_ad_accounts").select(
            "brand_id, meta_ad_account_id, token_expires_at, auth_method"
        ).eq("auth_method", "oauth"))
        brands = self._brand_lookup({r.get("brand_id") for r in rows})

        findings: List[Dict[str, Any]] = []
        for r in rows:
            exp = self._parse_ts(r.get("token_expires_at"))
            if exp is None:
                continue
            if exp < now:
                status = "expired"
            elif exp < warn_cutoff:
                status = "expiring"
            else:
                continue

            binfo = brands.get(r.get("brand_id"), {})
            findings.append({
                "brand_id": r.get("brand_id"),
                "brand_name": binfo.get("name", "(unknown)"),
                "organization_id": binfo.get("organization_id"),
                "platform": "meta",
                "ad_account_id": r.get("meta_ad_account_id"),
                "status": status,
                "expires_at": r.get("token_expires_at"),
                "days_until_expiry": round((exp - now).total_seconds() / 86400.0, 1),
            })

        findings.sort(key=lambda f: f["days_until_expiry"])
        return findings

    # ----------------------------------------------------------- summarize
    def summarize(
        self,
        stale: List[Dict[str, Any]],
        tokens: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build an alert summary. severity is None when everything is healthy,
        'error' when any sync is stale or a token has expired (these break data
        flow and should page/Slack), else 'warning' for tokens merely expiring."""
        expired = [t for t in tokens if t["status"] == "expired"]
        expiring = [t for t in tokens if t["status"] == "expiring"]

        parts: List[str] = []
        if stale:
            parts.append(f"{len(stale)} stale sync(s)")
        if expired:
            parts.append(f"{len(expired)} expired Meta token(s)")
        if expiring:
            parts.append(f"{len(expiring)} Meta token(s) expiring soon")

        details = {"stale": stale, "tokens": tokens}
        if not parts:
            return {"severity": None, "title": "Sync health: all syncs fresh", "details": details}

        severity = "error" if (stale or expired) else "warning"
        return {
            "severity": severity,
            "title": "Sync health: " + ", ".join(parts),
            "details": details,
        }
