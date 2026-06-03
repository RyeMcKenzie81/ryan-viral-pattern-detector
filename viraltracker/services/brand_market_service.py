"""BrandMarketService — per-brand market (host → market) configuration.

A brand's markets (US, CA, …) and the destination hostnames that map to each.
Lets per-product reporting split spend/CPA by market (and currency) instead of
blending a CAD funnel into a USD CPA. The market of an ad is DERIVED from its
captured destination host via this map — no per-offer-variant tagging.

Model: one product, market is a dimension. Per-region price lives on the offer
variant (later phase); this service holds the brand-level market definitions.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


def host_of(url: Optional[str]) -> str:
    """Extract the lowercase, www-stripped hostname from a URL (no port).

    Tolerant of input that omits a scheme ('us.martinclinic.com/pages/x'). The
    leading ``www.`` is dropped so a bare-host market pattern (``martinclinic.com``)
    matches a ``www.`` host too — and so storage and lookup are consistent
    regardless of which URL field (raw or canonical) a caller passes. Note only
    ``www.`` is stripped; meaningful subdomains like ``us.`` are preserved (that's
    the market signal)."""
    if not url:
        return ""
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
        return re.sub(r"^www\.", "", host)
    except Exception:
        return ""


class BrandMarketService:
    def __init__(self, supabase_client=None):
        self.supabase = supabase_client or get_supabase_client()

    def list_markets(self, brand_id) -> List[Dict[str, Any]]:
        """Return a brand's markets, ordered by sort_order then code."""
        try:
            res = (
                self.supabase.table("brand_markets")
                .select("*")
                .eq("brand_id", str(brand_id))
                .order("sort_order")
                .order("code")
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning(f"Failed to list markets for brand {brand_id}: {e}")
            return []

    def create_market(
        self, brand_id, code: str, label: Optional[str] = None,
        currency: str = "USD", host_patterns: Optional[List[str]] = None,
        is_default: bool = False, sort_order: int = 0,
    ) -> Dict[str, Any]:
        if is_default:
            self._clear_defaults(brand_id)
        record = {
            "brand_id": str(brand_id),
            "code": code.strip().upper(),
            "label": (label or "").strip() or None,
            "currency": (currency or "USD").strip().upper(),
            "host_patterns": _norm_hosts(host_patterns),
            "is_default": is_default,
            "sort_order": sort_order,
        }
        res = self.supabase.table("brand_markets").insert(record).execute()
        return res.data[0] if res.data else record

    def update_market(self, market_id, updates: Dict[str, Any]) -> Dict[str, Any]:
        clean = dict(updates)
        if clean.get("is_default"):
            # need brand_id to clear siblings
            row = self.supabase.table("brand_markets").select("brand_id").eq("id", str(market_id)).limit(1).execute()
            if row.data:
                self._clear_defaults(row.data[0]["brand_id"], except_id=str(market_id))
        if "code" in clean and clean["code"]:
            clean["code"] = clean["code"].strip().upper()
        if "currency" in clean and clean["currency"]:
            clean["currency"] = clean["currency"].strip().upper()
        if "host_patterns" in clean:
            clean["host_patterns"] = _norm_hosts(clean["host_patterns"])
        from datetime import datetime, timezone
        clean["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = self.supabase.table("brand_markets").update(clean).eq("id", str(market_id)).execute()
        return res.data[0] if res.data else {}

    def delete_market(self, market_id) -> None:
        self.supabase.table("brand_markets").delete().eq("id", str(market_id)).execute()

    def resolve_market_for_url(self, brand_id, url: str) -> Optional[Dict[str, Any]]:
        """Resolve the market an ad belongs to from its destination URL host.

        Exact host match (case-insensitive) against each market's host_patterns;
        falls back to the brand's default market (if any) when nothing matches.
        Returns None when there is no match and no default.
        """
        host = host_of(url)
        if not host:
            return None
        markets = self.list_markets(brand_id)
        for m in markets:
            patterns = [p.lower() for p in (m.get("host_patterns") or [])]
            if host in patterns:
                return m
        for m in markets:
            if m.get("is_default"):
                return m
        return None

    def _market_for_host(self, host: str, markets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """In-memory market resolution for a host (no DB call) — for batch splits.
        Exact host match against host_patterns, else the default market, else None."""
        if host:
            for m in markets:
                if host in [p.lower() for p in (m.get("host_patterns") or [])]:
                    return m
        for m in markets:
            if m.get("is_default"):
                return m
        return None

    def split_spend_by_market(
        self, brand_id, ad_ids: List[str], date_start: str, date_end: str
    ) -> Dict[str, Dict[str, Any]]:
        """Split a set of ads' spend + purchases + CPA by market.

        Market comes from each ad's captured destination canonical
        (meta_ad_destinations — the reliable WS2/WS3 source, NOT the sparse
        meta_ads_performance.destination_url), resolved against the brand's
        markets. Metrics come from meta_ads_performance over [date_start, date_end]
        (paginated). Ads whose host matches no market (and no default) bucket under
        'UNKNOWN'.

        Returns {market_code: {spend, purchases, cpa, currency, ads}}.
        CPA/spend are in the ad-account currency (caller labels it); this only
        splits the buckets.
        """
        if not ad_ids:
            return {}
        bid = str(brand_id)
        markets = self.list_markets(brand_id)

        # ad -> canonical (first seen) from meta_ad_destinations
        canon_by_ad: Dict[str, str] = {}
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            rows = (self.supabase.table("meta_ad_destinations")
                    .select("meta_ad_id, canonical_url")
                    .eq("brand_id", bid).in_("meta_ad_id", batch).execute().data or [])
            for r in rows:
                a, c = r.get("meta_ad_id"), r.get("canonical_url")
                if a and c and a not in canon_by_ad:
                    canon_by_ad[a] = c

        # ad -> {spend, purchases} from meta_ads_performance (paginated per batch)
        agg_by_ad: Dict[str, Dict[str, float]] = {}
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            offset, page = 0, 1000
            while True:
                rows = (self.supabase.table("meta_ads_performance")
                        .select("meta_ad_id, spend, purchases")
                        .eq("brand_id", bid).gte("date", date_start).lte("date", date_end)
                        .in_("meta_ad_id", batch).order("id")
                        .range(offset, offset + page - 1).execute().data or [])
                if not rows:
                    break
                for r in rows:
                    a = r.get("meta_ad_id")
                    if not a:
                        continue
                    e = agg_by_ad.setdefault(a, {"spend": 0.0, "purchases": 0.0})
                    e["spend"] += _num(r.get("spend"))
                    e["purchases"] += _num(r.get("purchases"))
                if len(rows) < page:
                    break
                offset += page

        out: Dict[str, Dict[str, Any]] = {}
        for ad_id, m in agg_by_ad.items():
            mk = self._market_for_host(host_of(canon_by_ad.get(ad_id)), markets)
            code = mk["code"] if mk else "UNKNOWN"
            cur = mk["currency"] if mk else None
            e = out.setdefault(code, {"spend": 0.0, "purchases": 0.0, "ads": 0, "currency": cur})
            e["spend"] += m["spend"]
            e["purchases"] += m["purchases"]
            e["ads"] += 1
        for code, e in out.items():
            e["cpa"] = round(e["spend"] / e["purchases"], 2) if e["purchases"] else None
            e["spend"] = round(e["spend"], 2)
            e["purchases"] = int(e["purchases"])
        return out

    def _clear_defaults(self, brand_id, except_id: Optional[str] = None) -> None:
        try:
            q = self.supabase.table("brand_markets").update({"is_default": False}).eq("brand_id", str(brand_id))
            if except_id:
                q = q.neq("id", except_id)
            q.execute()
        except Exception as e:
            logger.warning(f"Failed to clear default markets for brand {brand_id}: {e}")


def _num(v) -> float:
    """Coerce a value to float, treating None/garbage as 0.0."""
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _norm_hosts(hosts: Optional[List[str]]) -> List[str]:
    """Normalize host patterns to lowercase, www-stripped bare hostnames,
    de-duplicated. Inputs that don't parse to a hostname are dropped (storing
    raw junk that could never match is worse than dropping it)."""
    out: List[str] = []
    for h in (hosts or []):
        hh = host_of(h)
        if hh and hh not in out:
            out.append(hh)
    return out
