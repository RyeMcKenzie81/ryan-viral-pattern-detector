"""WeeklyDigestService — assemble the weekly per-product digest data.

A digest is a REPORT, so it reads the already-stored classifications + baselines
+ performance directly from the DB — it does NOT re-run the classification
pipeline. (full_analysis with max_new=0 was unreliable here: classify_batch's
cache key includes the volatile Meta thumbnail URL, which rotates between the
daily classification and the digest run, so cache hits silently vanish and every
product came back with an empty awareness table.)

Per product: awareness/CPA from stored classifications (latest level per ad) +
meta_ads_performance; split spend/CPA by market (US/CA); brand-level coverage +
unmapped worklist. No Gemini/Meta calls (except a one-time currency self-heal).
All money is in the ad-account currency.
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


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Linear-interpolated percentile (numpy-style) of a list of values.

    Returns None for an empty list. Used for the per-product median (p50) and
    p75 of per-ad CPAs, so the figures are specific to the product + window
    rather than the brand-wide baseline.
    """
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return round(vals[0], 2)
    k = (len(vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    frac = k - lo
    return round(vals[lo] * (1 - frac) + vals[hi] * frac, 2)


# Awareness stages, least-aware → most-aware, so the digest reads as a CPA
# waterfall down the funnel. Anything off-ladder (unclassified/unknown) sorts last.
_LEVEL_ORDER = {
    "unaware": 0, "problem_aware": 1, "solution_aware": 2,
    "product_aware": 3, "most_aware": 4,
}


class WeeklyDigestService:
    def __init__(self, supabase, market_service, meta_service):
        self.supabase = supabase
        self.market = market_service
        self.meta = meta_service

    async def build_brand_digest(self, brand_id: UUID, days_back: int = 30) -> Dict[str, Any]:
        from .helpers import get_spending_ad_ids, resolve_product_ad_ids

        bid = str(brand_id)
        currency = await self.meta.get_brand_currency(brand_id)

        # select(*) so a missing logo_url column (pre-migration) degrades to no
        # logo rather than 400-ing the whole digest.
        bn = self.supabase.table("brands").select("*").eq("id", bid).limit(1).execute()
        brow = bn.data[0] if bn.data else {}
        brand_name = brow.get("name") or "Brand"
        brand_logo_url = brow.get("logo_url")

        end = date.today()
        start = end - timedelta(days=days_back)
        start_s, end_s = start.isoformat(), end.isoformat()

        # Scope by SPEND over the full reporting window — NOT delivery status. An
        # ad that spent in the window and was then paused still drove cost and must
        # count toward its level's aggregate CPA. (get_active_ad_ids excludes
        # PAUSED/ARCHIVED and only looks back active_window_days (7), which silently
        # dropped real spend from a 30-day report.)
        spend_ids = await get_spending_ad_ids(self.supabase, brand_id, start, end)
        baselines = self._latest_baselines(bid)

        prods = (self.supabase.table("products").select("id, name")
                 .eq("brand_id", bid).order("name").execute().data or [])

        products_out: List[Dict[str, Any]] = []
        for prod in prods:
            pid, pname = prod["id"], prod.get("name", "Unnamed")
            product_ad_ids = list(resolve_product_ad_ids(self.supabase, bid, pid, spend_ids))
            if not product_ad_ids:
                products_out.append({"name": pname, "no_ads": True})
                continue
            try:
                total_spend, n_ads, rows = self._product_awareness(
                    bid, product_ad_ids, start_s, end_s, baselines
                )
                markets = self.market.split_spend_by_market(brand_id, product_ad_ids, start_s, end_s)
            except Exception as e:
                logger.warning(f"Digest: product {pname} failed: {e}")
                products_out.append({"name": pname, "error": True})
                continue

            products_out.append({
                "name": pname,
                "total_spend": total_spend,
                "spending_ads": n_ads,
                "no_ads": False,
                "awareness": rows,
                "markets": markets,
                "insight": self._insight(rows),
            })

        try:
            coverage, unmapped = self._coverage_and_unmapped(bid, start_s, end_s)
        except Exception as e:
            logger.warning(f"Digest: coverage computation failed for brand {bid}: {e}")
            coverage, unmapped = {}, []

        return {
            "brand_name": brand_name,
            "brand_logo_url": brand_logo_url,
            "currency": currency,
            "date_range": f"Last {days_back} days",
            "products": products_out,
            "coverage": coverage,
            "unmapped_funnels": unmapped,
        }

    def publish_html_report(self, brand_id: UUID, data: Dict[str, Any]) -> Optional[str]:
        """Render the digest as a standalone HTML page, upload it to storage, and
        return a URL for the 'Open full report' link in the Slack message.

        The link points at the API's /api/public/digest/<brand>/<date> route, NOT
        the raw storage URL: Supabase Storage serves uploaded HTML as text/plain
        (anti-XSS), so a direct storage link shows raw source. The API route reads
        the stored HTML back and serves it as text/html so it renders.

        Non-fatal: returns None on any failure so the Slack digest still posts
        (just without the link).
        """
        import os
        from .digest_renderer import render_brand_digest_html
        try:
            html_doc = render_brand_digest_html(data)
            report_date = date.today().isoformat()
            path = f"digests/{brand_id}/{report_date}.html"
            self.supabase.storage.from_("cron-outputs").upload(
                path,
                html_doc.encode("utf-8"),
                file_options={"content-type": "text/html", "upsert": "true"},
            )
            base = os.getenv(
                "DIGEST_VIEWER_BASE_URL",
                "https://ryan-viral-pattern-detector-production.up.railway.app",
            ).rstrip("/")
            return f"{base}/api/public/digest/{brand_id}/{report_date}"
        except Exception as e:
            logger.warning(f"Digest HTML publish failed for brand {brand_id} (non-fatal): {e}")
            return None

    # ------------------------------------------------------------------ #
    # Awareness from stored classifications (no re-classification)
    # ------------------------------------------------------------------ #

    def _latest_baselines(self, bid: str) -> Dict[str, float]:
        """Latest median CPA per awareness level (creative_format='all') from the
        daily-computed ad_intelligence_baselines."""
        rows = (self.supabase.table("ad_intelligence_baselines")
                .select("awareness_level, median_cost_per_purchase, computed_at")
                .eq("brand_id", bid).eq("creative_format", "all")
                .order("computed_at", desc=True).execute().data or [])
        out: Dict[str, float] = {}
        for r in rows:
            lvl = r.get("awareness_level")
            if lvl and lvl != "all" and lvl not in out:  # first per level = latest
                mcpa = r.get("median_cost_per_purchase")
                if mcpa is not None:
                    out[lvl] = _num(mcpa)
        return out

    def _product_awareness(
        self, bid: str, ad_ids: List[str], start_s: str, end_s: str, baselines: Dict[str, float]
    ) -> Tuple[float, int, List[Dict[str, Any]]]:
        """(total_spend, n_ads, awareness_rows) computed directly from the latest
        stored classification per ad + windowed performance. ``ad_ids`` is the
        spend-scoped product set, so paused-but-spent ads are included."""
        # latest awareness level per ad
        level_by_ad: Dict[str, str] = {}
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            rows = (self.supabase.table("ad_creative_classifications")
                    .select("meta_ad_id, creative_awareness_level, classified_at")
                    .eq("brand_id", bid).in_("meta_ad_id", batch)
                    .order("classified_at", desc=True).execute().data or [])
            for r in rows:
                a = r.get("meta_ad_id")
                if a and a not in level_by_ad and r.get("creative_awareness_level"):
                    level_by_ad[a] = r["creative_awareness_level"]

        # spend + purchases + revenue + add-to-carts + link-clicks per ad (paginated)
        perf: Dict[str, List[float]] = {}
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            offset, page = 0, 1000
            while True:
                rows = (self.supabase.table("meta_ads_performance")
                        .select("meta_ad_id, spend, purchases, purchase_value, add_to_carts, link_clicks")
                        .eq("brand_id", bid).gte("date", start_s).lte("date", end_s)
                        .in_("meta_ad_id", batch).order("id")
                        .range(offset, offset + page - 1).execute().data or [])
                if not rows:
                    break
                for r in rows:
                    a = r.get("meta_ad_id")
                    if not a:
                        continue
                    e = perf.setdefault(a, [0.0, 0.0, 0.0, 0.0, 0.0])
                    e[0] += _num(r.get("spend"))
                    e[1] += _num(r.get("purchases"))
                    e[2] += _num(r.get("purchase_value"))
                    e[3] += _num(r.get("add_to_carts"))
                    e[4] += _num(r.get("link_clicks"))
                if len(rows) < page:
                    break
                offset += page

        total_spend = round(sum(v[0] for v in perf.values()), 2)
        n_ads = len(ad_ids)

        # level -> [ads, spend, purchases, revenue, add_to_carts, link_clicks]
        agg: Dict[str, List[float]] = {}
        cpa_samples: Dict[str, List[float]] = {}   # per-ad $/purchase (purchases>0)
        catc_samples: Dict[str, List[float]] = {}  # per-ad $/add-to-cart (add_to_carts>0)
        for ad, (s, p, rev, atc, clk) in perf.items():
            # Bucket ads with no stored classification under "unclassified" so the
            # table sums to the product total (rather than silently dropping spend
            # and leaving a confusing gap vs the header). Classification coverage
            # is the daily job's responsibility — this just surfaces it honestly.
            lvl = level_by_ad.get(ad) or "unclassified"
            e = agg.setdefault(lvl, [0, 0.0, 0.0, 0.0, 0.0, 0.0])
            e[0] += 1
            e[1] += s
            e[2] += p
            e[3] += rev
            e[4] += atc
            e[5] += clk
            # Per-ad cost ratios only exist where the denominator fired; ads with no
            # purchase / no add-to-cart have no defined CPA / cost-per-ATC, so they
            # don't enter the median/p25 samples.
            if p > 0:
                cpa_samples.setdefault(lvl, []).append(s / p)
            if atc > 0:
                catc_samples.setdefault(lvl, []).append(s / atc)

        rows_out: List[Dict[str, Any]] = []
        for lvl, (ads, s, p, rev, atc, clk) in agg.items():
            # The baselines job buckets ads with no awareness classification under
            # "unknown"; the digest labels that same population "unclassified". Map
            # across so the brand benchmark column shows for it too.
            base_key = "unknown" if lvl == "unclassified" else lvl
            cpa_s = cpa_samples.get(lvl, [])
            catc_s = catc_samples.get(lvl, [])
            rows_out.append({
                "level": lvl, "ads": int(ads), "spend": round(s, 2),
                "roas": round(rev / s, 2) if s else None,         # revenue ÷ spend (blended)
                "cvr": round(p / clk, 4) if clk else None,        # purchases ÷ link-clicks
                "agg_cpa": round(s / p, 2) if p else None,        # blended $/purchase
                "prod_med_cpa": _percentile(cpa_s, 50),           # product median $/purchase
                "prod_p25_cpa": _percentile(cpa_s, 25),           # product top-quartile target
                "brand_med_cpa": baselines.get(base_key),         # brand-wide CPA benchmark
                "agg_catc": round(s / atc, 2) if atc else None,   # blended $/add-to-cart
                "prod_med_catc": _percentile(catc_s, 50),         # product median $/ATC
                "prod_p25_catc": _percentile(catc_s, 25),         # product top-quartile $/ATC
            })
        # Order by awareness stage (Unaware → Most Aware) so it reads as a CPA
        # waterfall; unclassified/unknown fall to the end.
        rows_out.sort(key=lambda r: _LEVEL_ORDER.get(r["level"], 99))
        return total_spend, n_ads, rows_out

    @staticmethod
    def _insight(rows: List[Dict[str, Any]]) -> Optional[str]:
        """A simple 'what to work on': the level whose aggregate CPA is furthest
        OVER the brand-wide median benchmark (≥20% gap, with real spend)."""
        worst, worst_gap = None, 0.0
        for r in rows:
            a, m = r.get("agg_cpa"), r.get("brand_med_cpa")
            if a and m and m > 0 and (r.get("spend") or 0) > 0:
                gap = (a - m) / m
                if gap > worst_gap:
                    worst, worst_gap = r, gap
        if worst and worst_gap >= 0.2:
            lvl = str(worst["level"]).replace("_", " ")
            return f"{lvl} CPA {worst_gap * 100:.0f}% over brand baseline (${worst['agg_cpa']:.0f} vs ${worst['brand_med_cpa']:.0f})."
        return None

    # ------------------------------------------------------------------ #
    # Coverage + unmapped worklist (unchanged)
    # ------------------------------------------------------------------ #

    def _coverage_and_unmapped(
        self, bid: str, start_s: str, end_s: str, top_n: int = 5
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Coverage line + top unmapped funnels, over ads that HAVE a captured
        destination. Attributed = canonical maps to a product-tagged landing page;
        unmapped = canonical has no product tag (the tag-this worklist)."""
        tagged = set()
        lp_rows = (self.supabase.table("brand_landing_pages")
                   .select("canonical_url, product_id").eq("brand_id", bid).execute().data or [])
        for r in lp_rows:
            if r.get("canonical_url") and r.get("product_id"):
                tagged.add(r["canonical_url"])

        canon_by_ad: Dict[str, str] = {}
        dest_rows = (self.supabase.table("meta_ad_destinations")
                     .select("meta_ad_id, canonical_url").eq("brand_id", bid).execute().data or [])
        for r in dest_rows:
            a, c = r.get("meta_ad_id"), r.get("canonical_url")
            if a and c and a not in canon_by_ad:
                canon_by_ad[a] = c

        if not canon_by_ad:
            return {}, []

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
