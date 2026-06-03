"""WeeklyDigestService — assemble the weekly per-product digest data.

Per product: run full_analysis (with classification OFF — the daily jobs handle
classifying, so this is pure DB aggregation) → awareness/CPA. Split each product's
spend/CPA by market (US/CA). Compute a brand-level coverage line + unmapped-spend
worklist. The renderer (digest_renderer) turns the returned dict into Slack blocks.

All money is in the ad-account currency (from MetaAdsService.get_brand_currency).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class WeeklyDigestService:
    def __init__(self, supabase, intel_service, market_service, meta_service):
        self.supabase = supabase
        self.intel = intel_service
        self.market = market_service
        self.meta = meta_service

    async def build_brand_digest(self, brand_id: UUID, org_id: UUID, days_back: int = 30) -> Dict[str, Any]:
        from .helpers import get_active_ad_ids, resolve_product_ad_ids
        from .models import RunConfig

        bid = str(brand_id)
        currency = await self.meta.get_brand_currency(brand_id)

        bn = self.supabase.table("brands").select("name").eq("id", bid).limit(1).execute()
        brand_name = (bn.data[0]["name"] if bn.data else "Brand")

        end = date.today()
        start = end - timedelta(days=days_back)
        start_s, end_s = start.isoformat(), end.isoformat()

        # Use full_analysis's active-ad window (not days_back) so the market-split
        # ad set matches the product header/awareness ad set — otherwise the
        # `Market:` spend and the header spend describe different ads and diverge.
        active_window = RunConfig().active_window_days
        active_ids = await get_active_ad_ids(self.supabase, brand_id, end, active_window)

        prods = (self.supabase.table("products").select("id, name")
                 .eq("brand_id", bid).order("name").execute().data or [])

        products_out: List[Dict[str, Any]] = []
        for prod in prods:
            pid, pname = prod["id"], prod.get("name", "Unnamed")
            try:
                # Classification OFF (max_new=0) → reuse existing classifications,
                # pure DB aggregation, no Gemini cost in the digest path.
                config = RunConfig(
                    days_back=days_back,
                    max_classifications_per_run=0,
                    max_video_classifications_per_run=0,
                )
                result = await self.intel.full_analysis(
                    brand_id=brand_id, org_id=org_id, config=config,
                    product_id=UUID(pid) if isinstance(pid, str) else pid,
                )
            except Exception as e:
                logger.warning(f"Digest: analysis failed for product {pname}: {e}")
                products_out.append({"name": pname, "error": True})
                continue

            if getattr(result, "no_ads_in_scope", False) or result.active_ads == 0:
                products_out.append({"name": pname, "no_ads": True})
                continue

            rows = self._awareness_rows(result)
            product_ad_ids = list(resolve_product_ad_ids(self.supabase, bid, pid, active_ids))
            try:
                markets = self.market.split_spend_by_market(brand_id, product_ad_ids, start_s, end_s)
            except Exception as e:
                logger.warning(f"Digest: market split failed for {pname}: {e}")
                markets = {}
            insight = (result.creative_insights or [None])[0]

            products_out.append({
                "name": pname,
                "total_spend": result.total_spend,
                "active_ads": result.active_ads,
                "no_ads": False,
                "awareness": rows,
                "markets": markets,
                "insight": insight,
            })

        try:
            coverage, unmapped = self._coverage_and_unmapped(bid, start_s, end_s)
        except Exception as e:
            logger.warning(f"Digest: coverage computation failed for brand {bid}: {e}")
            coverage, unmapped = {}, []

        return {
            "brand_name": brand_name,
            "currency": currency,
            "date_range": f"Last {days_back} days",
            "products": products_out,
            "coverage": coverage,
            "unmapped_funnels": unmapped,
        }

    @staticmethod
    def _awareness_rows(result) -> List[Dict[str, Any]]:
        dist = result.awareness_distribution or {}
        agg = result.awareness_aggregates or {}
        base = result.awareness_baselines or {}
        rows = []
        for level, count in dist.items():
            a = agg.get(level, {})
            b = base.get(level, {})
            rows.append({
                "level": level, "ads": count,
                "spend": a.get("spend"), "agg_cpa": a.get("cpa"), "med_cpa": b.get("cpa"),
            })
        rows.sort(key=lambda r: (r.get("spend") or 0), reverse=True)
        return rows

    def _coverage_and_unmapped(
        self, bid: str, start_s: str, end_s: str, top_n: int = 5
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Coverage line + top unmapped funnels, over ads that HAVE a captured
        destination. Attributed = canonical maps to a product-tagged landing page;
        unmapped = canonical has no product tag (the tag-this worklist)."""
        # Product-tagged canonicals.
        tagged = set()
        lp_rows = (self.supabase.table("brand_landing_pages")
                   .select("canonical_url, product_id").eq("brand_id", bid).execute().data or [])
        for r in lp_rows:
            if r.get("canonical_url") and r.get("product_id"):
                tagged.add(r["canonical_url"])

        # ad -> canonical (first seen).
        canon_by_ad: Dict[str, str] = {}
        dest_rows = (self.supabase.table("meta_ad_destinations")
                     .select("meta_ad_id, canonical_url").eq("brand_id", bid).execute().data or [])
        for r in dest_rows:
            a, c = r.get("meta_ad_id"), r.get("canonical_url")
            if a and c and a not in canon_by_ad:
                canon_by_ad[a] = c

        if not canon_by_ad:
            return {}, []

        # spend per ad over the window (paginated).
        ad_ids = list(canon_by_ad.keys())
        spend_by_ad: Dict[str, float] = {}
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            offset, page = 0, 1000
            while True:
                rows = (self.supabase.table("meta_ads_performance")
                        .select("meta_ad_id, spend")
                        .eq("brand_id", bid).gte("date", start_s).lte("date", end_s)
                        .in_("meta_ad_id", batch).order("id")
                        .range(offset, offset + page - 1).execute().data or [])
                if not rows:
                    break
                for r in rows:
                    a = r.get("meta_ad_id")
                    if a:
                        spend_by_ad[a] = spend_by_ad.get(a, 0.0) + _num(r.get("spend"))
                if len(rows) < page:
                    break
                offset += page

        attributed = 0.0
        unmapped_by_canon: Dict[str, Dict[str, Any]] = {}
        for ad_id, canon in canon_by_ad.items():
            s = spend_by_ad.get(ad_id, 0.0)
            if canon in tagged:
                attributed += s
            else:
                e = unmapped_by_canon.setdefault(canon, {"url": canon, "spend": 0.0, "ads": 0})
                e["spend"] += s
                e["ads"] += 1

        unmapped_total = sum(e["spend"] for e in unmapped_by_canon.values())
        denom = attributed + unmapped_total
        coverage = {
            "attributed": round(attributed, 2),
            "unmapped": round(unmapped_total, 2),
            "pct": round(100.0 * attributed / denom, 1) if denom else None,
        }
        unmapped = sorted(unmapped_by_canon.values(), key=lambda e: e["spend"], reverse=True)
        for e in unmapped:
            e["spend"] = round(e["spend"], 2)
        return coverage, unmapped[:top_n]
