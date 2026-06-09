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
        threshold = self._completeness_threshold()

        prods = (self.supabase.table("products").select("id, name")
                 .eq("brand_id", bid).order("name").execute().data or [])

        products_out: List[Dict[str, Any]] = []
        for prod in prods:
            pid, pname = prod["id"], prod.get("name", "Unnamed")
            product_ad_ids = list(resolve_product_ad_ids(self.supabase, bid, pid, spend_ids))
            if not product_ad_ids:
                continue  # no spend in the period — omit the product from the report
            try:
                total_spend, n_ads, rows, completeness = self._product_awareness(
                    bid, product_ad_ids, start_s, end_s, baselines
                )
                markets = self.market.split_spend_by_market(brand_id, product_ad_ids, start_s, end_s)
            except Exception as e:
                logger.warning(f"Digest: product {pname} failed: {e}")
                products_out.append({"name": pname, "error": True})
                continue

            if total_spend <= 0:
                continue  # defensive: resolved ads but zero windowed spend → omit

            # Publish gate: below the threshold the distribution is a non-representative
            # sample, so the renderer suppresses the percentages and shows "pending" +
            # the itemized gap. The completeness + cannot-classify lines always render.
            awareness_pending = completeness["current_pct"] < threshold
            products_out.append({
                "name": pname,
                "total_spend": total_spend,
                "spending_ads": n_ads,
                "no_ads": False,
                "awareness": rows,
                "completeness": completeness,
                "awareness_pending": awareness_pending,
                "markets": markets,
                # Only surface "what to work on" when the mix is trustworthy.
                "insight": None if awareness_pending else self._insight(rows),
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

    def _completeness_threshold(self) -> float:
        """Per-product awareness-completeness gate, in (0, 1]. At or above it the digest
        shows the full awareness distribution; below it, it suppresses the percentages and
        shows "pending" + the itemized gap. Configurable via the system_settings key
        'digest.completeness_threshold'; default 0.90, clamped to (0, 1]."""
        default = 0.90
        try:
            r = (self.supabase.table("system_settings").select("value")
                 .eq("key", "digest.completeness_threshold").limit(1).execute())
            if r.data:
                v = float(r.data[0]["value"])
                if 0.0 < v <= 1.0:
                    return v
        except Exception:
            pass
        return default

    def _product_awareness(
        self, bid: str, ad_ids: List[str], start_s: str, end_s: str, baselines: Dict[str, float]
    ) -> Tuple[float, int, List[Dict[str, Any]], Dict[str, Any]]:
        """(total_spend, n_ads, awareness_rows, completeness).

        The awareness distribution is computed ONLY from CURRENT-version classifications
        (deep image at the current image-analysis version, or current video). Stale
        (old light / unlinked), low_res (64x64 thumbnail), and never-classified spend are
        EXCLUDED from the buckets and reported in ``completeness`` instead, so the client
        mix is never built on the unreliable old light-path labels and low_res spend is
        shown as "cannot classify" rather than silently bucketed. Currency uses the SAME
        rule as the classifier (awareness_currency.awareness_state). ``ad_ids`` is the
        spend-scoped product set (paused-but-spent ads included).
        """
        from .awareness_currency import (
            awareness_state, CURRENT, STALE, LOW_RES, UNCLASSIFIED,
        )
        from ..image_analysis_service import PROMPT_VERSION as _IMG_VER
        from ..video_analysis_service import PROMPT_VERSION as _VID_VER

        # GENUINE latest classification row per ad (NOT latest-with-awareness: an older
        # stale row must never win over a newer NULL-awareness row).
        latest_by_ad: Dict[str, Dict[str, Any]] = {}
        # Current-version deep-analysis id sets + low_res markers (bulk, no N+1).
        current_image_ids: set = set()
        current_video_ids: set = set()
        low_res_ids: set = set()
        for i in range(0, len(ad_ids), 500):
            batch = ad_ids[i:i + 500]
            lim = max(1000, len(batch) * 3)
            # GENUINE latest classification row per ad. PAGINATE: ad_creative_classifications
            # is append-only (one row per run, accumulating across prompt/schema versions),
            # so a 500-ad chunk can exceed PostgREST's 1000-row default. Without paging the
            # cap drops the OLDEST rows GLOBALLY (the order is global desc), and an ad whose
            # rows all fall past the cut would vanish from latest_by_ad -> read as
            # unclassified -> deflate current_pct -> wrongly trip the publish gate. Global
            # desc + range means the first time we see an ad IS its genuine latest.
            offset, page = 0, 1000
            while True:
                rows = (self.supabase.table("ad_creative_classifications")
                        .select("meta_ad_id, creative_awareness_level, creative_format, "
                                "image_analysis_id, video_analysis_id, classified_at")
                        .eq("brand_id", bid).in_("meta_ad_id", batch)
                        .order("classified_at", desc=True)
                        .range(offset, offset + page - 1).execute().data or [])
                if not rows:
                    break
                for r in rows:
                    a = r.get("meta_ad_id")
                    if a and a not in latest_by_ad:
                        latest_by_ad[a] = r   # first seen (global desc) == genuine latest
                if len(rows) < page:
                    break
                offset += page
            # Current-version deep-analysis id sets + low_res markers. ONE ad_image_analysis
            # query yields both (partition on status in Python); one ad_video_analysis query.
            # .limit(max(1000, len*3)) mirrors the classifier's Query 5/6/7 headroom so the
            # 1000-row default can't silently truncate the current-version sets.
            try:
                ia = (self.supabase.table("ad_image_analysis").select("id, meta_ad_id, status")
                      .eq("brand_id", bid).eq("prompt_version", _IMG_VER)
                      .in_("meta_ad_id", batch).limit(lim).execute().data or [])
                current_image_ids.update(str(x["id"]) for x in ia if x.get("id"))
                low_res_ids.update(x["meta_ad_id"] for x in ia
                                   if x.get("status") == "low_res" and x.get("meta_ad_id"))
                vv = (self.supabase.table("ad_video_analysis").select("id")
                      .eq("brand_id", bid).eq("prompt_version", _VID_VER)
                      .in_("meta_ad_id", batch).limit(lim).execute().data or [])
                current_video_ids.update(str(x["id"]) for x in vv if x.get("id"))
            except Exception as e:
                logger.warning(f"Digest currency prefetch failed for brand {bid}: {e}")

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

        # Only CURRENT-version classifications contribute to the awareness distribution.
        # Everything else (stale / low_res / unclassified) is tallied for the completeness
        # line and EXCLUDED from the buckets, so the client mix is never built on the
        # unreliable old light-path labels.
        agg: Dict[str, List[float]] = {}
        cpa_samples: Dict[str, List[float]] = {}   # per-ad $/purchase (purchases>0)
        catc_samples: Dict[str, List[float]] = {}  # per-ad $/add-to-cart (add_to_carts>0)
        comp = {CURRENT: 0.0, STALE: 0.0, LOW_RES: 0.0, UNCLASSIFIED: 0.0}
        for ad, (s, p, rev, atc, clk) in perf.items():
            state = awareness_state(
                ad, latest_by_ad.get(ad), current_image_ids, current_video_ids, low_res_ids,
            )
            comp[state] += s
            if state != CURRENT:
                continue
            lvl = latest_by_ad[ad].get("creative_awareness_level")
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
            cpa_s = cpa_samples.get(lvl, [])
            catc_s = catc_samples.get(lvl, [])
            rows_out.append({
                "level": lvl, "ads": int(ads), "spend": round(s, 2),
                "roas": round(rev / s, 2) if s else None,         # revenue ÷ spend (blended)
                "cvr": round(p / clk, 4) if clk else None,        # purchases ÷ link-clicks
                "agg_cpa": round(s / p, 2) if p else None,        # blended $/purchase
                "prod_med_cpa": _percentile(cpa_s, 50),           # product median $/purchase
                "prod_p25_cpa": _percentile(cpa_s, 25),           # product top-quartile target
                "brand_med_cpa": baselines.get(lvl),              # brand-wide CPA benchmark
                "agg_catc": round(s / atc, 2) if atc else None,   # blended $/add-to-cart
                "prod_med_catc": _percentile(catc_s, 50),         # product median $/ATC
                "prod_p25_catc": _percentile(catc_s, 25),         # product top-quartile $/ATC
            })
        # Order by awareness stage (Unaware → Most Aware) so it reads as a CPA waterfall.
        rows_out.sort(key=lambda r: _LEVEL_ORDER.get(r["level"], 99))

        # Completeness: low_res is EXCLUDED from the denominator (cannot be classified
        # without a high-res re-fetch — its own "cannot classify" line), like attribution
        # bucket C. stale + unclassified ARE in the denominator (fixable by the backfill).
        classifiable = max(total_spend - comp[LOW_RES], 0.0)
        current_pct = (comp[CURRENT] / classifiable) if classifiable > 0 else 0.0
        completeness = {
            "current_spend": round(comp[CURRENT], 2),
            "stale_spend": round(comp[STALE], 2),
            "low_res_spend": round(comp[LOW_RES], 2),
            "unclassified_spend": round(comp[UNCLASSIFIED], 2),
            "attributable_spend": round(total_spend, 2),
            "classifiable_spend": round(classifiable, 2),
            "current_pct": round(current_pct, 4),
        }
        return total_spend, n_ads, rows_out, completeness

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
