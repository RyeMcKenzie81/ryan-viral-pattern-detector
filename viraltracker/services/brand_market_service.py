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

    def _clear_defaults(self, brand_id, except_id: Optional[str] = None) -> None:
        try:
            q = self.supabase.table("brand_markets").update({"is_default": False}).eq("brand_id", str(brand_id))
            if except_id:
                q = q.neq("id", except_id)
            q.execute()
        except Exception as e:
            logger.warning(f"Failed to clear default markets for brand {brand_id}: {e}")


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
