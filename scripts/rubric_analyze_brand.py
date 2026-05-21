"""
Awareness-controlled rubric analysis for any brand.
Correlates rubric dimensions against multiple performance metrics:
ROAS, CTR, CPM, Add to Carts, Cost/ATC, Initiate Checkouts, Cost/IC.
Usage: python3 scripts/rubric_analyze_brand.py "Martin Clinic" [--metrics]
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
sys.path.insert(0, '.')


def cache_path(brand_name):
    slug = brand_name.lower().replace(' ', '_')
    return f"/tmp/rubric_scored_{slug}.json"


def _rank(values):
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _spearman(x, y):
    n = len(x)
    if n < 4:
        return None
    rx = _rank(x)
    ry = _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    den_x = sum((a - mean_rx) ** 2 for a in rx) ** 0.5
    den_y = sum((b - mean_ry) ** 2 for b in ry) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _pearson(x, y):
    n = len(x)
    if n < 4:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x) ** 0.5
    dy = sum((b - my) ** 2 for b in y) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _enrich_performance_metrics(supabase, brand_id, scored, days_back=90):
    """Pull fresh performance metrics from meta_ads_performance for all scored ads.

    Aggregates daily rows per ad and computes derived metrics including
    initiate_checkouts and cost-per metrics not in the cached data.
    """
    meta_ids = [s['meta_ad_id'] for s in scored]
    end = date.today()
    start = end - timedelta(days=days_back)

    # Fetch performance rows in batches (Supabase limit = 1000)
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        result = (
            supabase.table("meta_ads_performance")
            .select("meta_ad_id, spend, impressions, link_clicks, add_to_carts, "
                    "initiate_checkouts, purchases, purchase_value, "
                    "cost_per_add_to_cart, cost_per_initiate_checkout")
            .eq("brand_id", brand_id)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .in_("meta_ad_id", meta_ids)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    # Aggregate per ad
    agg = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "link_clicks": 0,
        "add_to_carts": 0, "initiate_checkouts": 0,
        "purchases": 0, "purchase_value": 0,
    })
    for row in all_rows:
        mid = row.get("meta_ad_id")
        if not mid:
            continue
        a = agg[mid]
        a["spend"] += float(row.get("spend") or 0)
        a["impressions"] += int(row.get("impressions") or 0)
        a["link_clicks"] += int(row.get("link_clicks") or 0)
        a["add_to_carts"] += int(row.get("add_to_carts") or 0)
        a["initiate_checkouts"] += int(row.get("initiate_checkouts") or 0)
        a["purchases"] += int(row.get("purchases") or 0)
        a["purchase_value"] += float(row.get("purchase_value") or 0)

    # Compute derived metrics and attach to scored entries
    for s in scored:
        mid = s["meta_ad_id"]
        a = agg.get(mid)
        if not a:
            continue
        imp = a["impressions"]
        clicks = a["link_clicks"]
        spend = a["spend"]
        pv = a["purchase_value"]

        s["_spend"] = spend
        s["_impressions"] = imp
        s["_link_clicks"] = clicks
        s["_roas"] = (pv / spend) if spend > 0 else 0
        s["_ctr"] = (clicks / imp * 100) if imp > 0 else 0
        s["_cpm"] = (spend / imp * 1000) if imp > 0 else 0
        s["_cpc"] = (spend / clicks) if clicks > 0 else 0
        s["_add_to_carts"] = a["add_to_carts"]
        s["_cost_per_atc"] = (spend / a["add_to_carts"]) if a["add_to_carts"] > 0 else None
        s["_initiate_checkouts"] = a["initiate_checkouts"]
        s["_cost_per_ic"] = (spend / a["initiate_checkouts"]) if a["initiate_checkouts"] > 0 else None
        s["_purchases"] = a["purchases"]
        s["_conversion_rate"] = (a["purchases"] / clicks * 100) if clicks > 0 else 0
        s["_atc_rate"] = (a["add_to_carts"] / clicks * 100) if clicks > 0 else 0

    enriched = sum(1 for s in scored if "_roas" in s)
    print(f"Enriched {enriched}/{len(scored)} ads with fresh performance data")
    return scored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('brand', help='Brand name (must match cache file)')
    parser.add_argument('--metrics', action='store_true',
                        help='Run multi-metric correlation analysis (CTR, CPM, ATC, IC)')
    parser.add_argument('--days', type=int, default=90,
                        help='Days back for performance data (default: 90)')
    args = parser.parse_args()

    cpath = cache_path(args.brand)
    try:
        with open(cpath) as f:
            scored = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: No cache at {cpath}. Run rubric_score_brand.py first.")
        return

    print(f"Loaded {len(scored)} scored ads for {args.brand}")

    # Fetch awareness classifications
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()

    # Resolve brand ID for performance queries
    brand_result = supabase.table('brands').select('id, name').ilike('name', f'%{args.brand}%').limit(1).execute()
    if not brand_result.data:
        print(f"WARNING: Brand '{args.brand}' not found in DB — skipping performance enrichment")
        brand_id = None
    else:
        brand_id = brand_result.data[0]['id']

    meta_ids = [s['meta_ad_id'] for s in scored]
    result = supabase.table('ad_creative_classifications').select(
        'meta_ad_id, creative_awareness_level, copy_awareness_level'
    ).in_('meta_ad_id', meta_ids).order('classified_at', desc=True).execute()

    awareness_map = {}
    for row in result.data:
        mid = row['meta_ad_id']
        if mid not in awareness_map:
            awareness_map[mid] = row['creative_awareness_level']

    for s in scored:
        s['awareness'] = awareness_map.get(s['meta_ad_id'], 'unknown')

    # Enrich with full performance metrics
    if brand_id:
        scored = _enrich_performance_metrics(supabase, brand_id, scored, days_back=args.days)

    awareness_counts = Counter(s['awareness'] for s in scored)
    print(f"\nAwareness distribution:")
    for level, count in sorted(awareness_counts.items(), key=lambda x: -x[1]):
        avg_roas = sum(s['roas'] for s in scored if s['awareness'] == level) / max(count, 1)
        avg_rubric = sum(s['rubric_score'] for s in scored if s['awareness'] == level) / max(count, 1)
        print(f"  {level:<20s} n={count:>2}  avg ROAS={avg_roas:>5.1f}x  avg rubric={avg_rubric:>4.0f}")

    # ======================================================================
    # 1. Does awareness level predict ROAS?
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("1. DOES AWARENESS LEVEL PREDICT ROAS?")
    print(f"{'=' * 80}")

    awareness_ordinal = {
        'unaware': 1, 'problem_aware': 2, 'solution_aware': 3,
        'product_aware': 4, 'most_aware': 5, 'unknown': 3,
    }

    ads_with_awareness = [s for s in scored if s['awareness'] != 'unknown']
    if len(ads_with_awareness) >= 4:
        aw_vals = [awareness_ordinal[s['awareness']] for s in ads_with_awareness]
        roas_vals = [s['roas'] for s in ads_with_awareness]
        rubric_vals = [s['rubric_score'] for s in ads_with_awareness]

        sp_aw_roas = _spearman(aw_vals, roas_vals)
        sp_aw_rubric = _spearman(aw_vals, rubric_vals)

        print(f"\n  Awareness Level vs ROAS:         ρ = {sp_aw_roas:+.3f}")
        print(f"  Awareness Level vs Rubric Score:  ρ = {sp_aw_rubric:+.3f}")

    # ======================================================================
    # 2. Overall rubric vs ROAS (Spearman + Pearson)
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("2. OVERALL RUBRIC vs ROAS")
    print(f"{'=' * 80}")

    all_roas = [s['roas'] for s in scored]
    all_rubric = [s['rubric_score'] for s in scored]
    all_raw = [s['raw_score'] for s in scored]

    print(f"\n  {'Metric':<35s} {'Spearman':>10} {'Pearson':>10}")
    print(f"  {'─'*55}")
    print(f"  {'Rubric Score vs ROAS':<35s} {_spearman(all_rubric, all_roas):>+10.3f} {_pearson(all_rubric, all_roas):>+10.3f}")
    print(f"  {'Raw Score vs ROAS':<35s} {_spearman(all_raw, all_roas):>+10.3f} {_pearson(all_raw, all_roas):>+10.3f}")

    # ======================================================================
    # 3. Gate-level correlations
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("3. GATE-LEVEL SPEARMAN vs ROAS")
    print(f"{'=' * 80}")

    from viraltracker.services.rubric_scoring_service import GATE_NAMES

    gate_results = []
    for gn in range(10):
        gate_vals = [s['gates'].get(str(gn), 0) for s in scored]
        sp = _spearman(gate_vals, all_roas)
        pe = _pearson(gate_vals, all_roas)
        if sp is not None:
            gate_results.append((gn, sp, pe))

    gate_results.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  {'Gate':<40s} {'Spearman':>10} {'Pearson':>10}")
    print(f"  {'─'*60}")
    for gn, sp, pe in gate_results:
        print(f"  G{gn} {GATE_NAMES[gn]:<37s} {sp:>+10.3f} {pe:>+10.3f}")

    # ======================================================================
    # 4. All 54 dimensions — Spearman with ROAS
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("4. ALL DIMENSIONS — SPEARMAN vs ROAS (|ρ| > 0.15)")
    print(f"{'=' * 80}")

    all_dims = set()
    for s in scored:
        all_dims.update(s['dim_scores'].keys())

    dim_results = []
    for dim in sorted(all_dims):
        vals = [s['dim_scores'].get(dim, 0) for s in scored]
        if max(vals) > min(vals):
            sp = _spearman(vals, all_roas)
            pe = _pearson(vals, all_roas)
            avg = sum(vals) / len(vals)
            if sp is not None:
                dim_results.append((dim, sp, pe, avg))

    dim_results.sort(key=lambda x: abs(x[1]), reverse=True)
    print(f"\n  {'Dimension':<48s} {'ρ':>7} {'r':>7} {'Avg':>5} {'Signal':>8}")
    print(f"  {'─'*78}")
    for dim, sp, pe, avg in dim_results:
        if abs(sp) < 0.15:
            continue
        sig = "STRONG" if abs(sp) >= 0.35 else "MEDIUM" if abs(sp) >= 0.25 else "weak"
        print(f"  {dim:<48s} {sp:>+6.3f} {pe:>+6.3f} {avg:>5.1f} {sig:>8}")

    # ======================================================================
    # 5. Coherence multipliers
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("5. COHERENCE MULTIPLIERS vs ROAS")
    print(f"{'=' * 80}")

    for mkey in ['strategic_coherence', 'offer_alignment', 'belief_distance', 'combined']:
        vals = [s['multipliers'].get(mkey, 1.0) for s in scored]
        sp = _spearman(vals, all_roas)
        if sp is not None:
            print(f"  {mkey:<35s} ρ = {sp:+.3f}")

    # ======================================================================
    # 6. Detailed breakdown by awareness level
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("6. BREAKDOWN BY AWARENESS LEVEL")
    print(f"{'=' * 80}")

    for level in ['unaware', 'problem_aware', 'solution_aware', 'product_aware', 'most_aware']:
        group = [s for s in scored if s['awareness'] == level]
        if not group:
            continue
        roas_list = sorted([s['roas'] for s in group])
        rubric_list = [s['rubric_score'] for s in group]
        print(f"\n  {level.upper()} (n={len(group)})")
        print(f"    ROAS:   min={min(roas_list):.1f}x  med={roas_list[len(roas_list)//2]:.1f}x  max={max(roas_list):.1f}x  avg={sum(roas_list)/len(roas_list):.1f}x")
        print(f"    Rubric: min={min(rubric_list):.0f}  avg={sum(rubric_list)/len(rubric_list):.0f}  max={max(rubric_list):.0f}")
        for s in sorted(group, key=lambda x: -x['roas']):
            print(f"      {s['roas']:>5.1f}x  {s['rubric_score']:>3.0f} ({s['grade']})  {s['ad_name'][:50]}")

    # ======================================================================
    # 7. Within-awareness correlations
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("7. WITHIN-AWARENESS CORRELATIONS")
    print(f"{'=' * 80}")

    for level in ['problem_aware', 'solution_aware', 'product_aware', 'most_aware']:
        group = [s for s in scored if s['awareness'] == level]
        if len(group) < 5:
            continue

        print(f"\n  {'─' * 70}")
        print(f"  {level.upper()} (n={len(group)})")
        print(f"  {'─' * 70}")

        roas_vals = [s['roas'] for s in group]
        rubric_vals = [s['rubric_score'] for s in group]
        sp_overall = _spearman(rubric_vals, roas_vals)
        print(f"\n    Overall Rubric vs ROAS: ρ = {sp_overall:+.3f}" if sp_overall is not None else "\n    Insufficient data")

        print(f"\n    Gate-level:")
        g_results = []
        for gn in range(10):
            gate_vals = [s['gates'].get(str(gn), 0) for s in group]
            sp = _spearman(gate_vals, roas_vals)
            if sp is not None:
                g_results.append((gn, sp))
        g_results.sort(key=lambda x: x[1], reverse=True)
        for gn, sp in g_results:
            flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  " if abs(sp) >= 0.15 else "   "
            print(f"      G{gn} {GATE_NAMES[gn]:<32s} ρ = {sp:+.3f} {flag}")

        print(f"\n    Dimensions with |ρ| > 0.20:")
        d_results = []
        for dim in sorted(all_dims):
            vals = [s['dim_scores'].get(dim, 0) for s in group]
            if max(vals) > min(vals):
                sp = _spearman(vals, roas_vals)
                if sp is not None and abs(sp) > 0.20:
                    d_results.append((dim, sp))
        d_results.sort(key=lambda x: abs(x[1]), reverse=True)
        if d_results:
            for dim, sp in d_results:
                flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  "
                direction = "↑ROAS" if sp > 0 else "↓ROAS"
                print(f"      {dim:<48s} ρ = {sp:+.3f} {flag} {direction}")
        else:
            print(f"      (none)")

    # ======================================================================
    # 8. Residualized analysis — controlling for awareness
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("8. RESIDUALIZED ANALYSIS — After Removing Awareness Effect")
    print(f"{'=' * 80}")

    ads_known = [s for s in scored if s['awareness'] != 'unknown']
    if len(ads_known) < 10:
        print("  Not enough ads with known awareness level.")
        return

    by_awareness = defaultdict(list)
    for s in ads_known:
        by_awareness[s['awareness']].append(s)

    for level, group in by_awareness.items():
        sorted_group = sorted(group, key=lambda x: x['roas'])
        for rank_idx, s in enumerate(sorted_group):
            s['roas_percentile_within_awareness'] = rank_idx / max(len(sorted_group) - 1, 1)

    adjusted_roas = [s['roas_percentile_within_awareness'] for s in ads_known]

    dim_adj_results = []
    for dim in sorted(all_dims):
        vals = [s['dim_scores'].get(dim, 0) for s in ads_known]
        if max(vals) > min(vals):
            sp = _spearman(vals, adjusted_roas)
            sp_raw = _spearman(vals, [s['roas'] for s in ads_known])
            if sp is not None:
                dim_adj_results.append((dim, sp, sp_raw))

    dim_adj_results.sort(key=lambda x: abs(x[1]), reverse=True)

    print(f"\n  {'Dimension':<48s} {'ρ adj':>8} {'ρ raw':>8} {'Δ':>8}")
    print(f"  {'─'*74}")
    for dim, sp_adj, sp_raw in dim_adj_results:
        change = sp_adj - (sp_raw or 0)
        flag = "***" if abs(sp_adj) >= 0.35 else "** " if abs(sp_adj) >= 0.25 else "*  " if abs(sp_adj) >= 0.15 else "   "
        print(f"  {dim:<48s} {sp_adj:>+7.3f} {sp_raw:>+7.3f} {change:>+7.3f} {flag}")

    # ======================================================================
    # 9. Verdict
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("9. VERDICT — SIGNALS THAT SURVIVE AWARENESS ADJUSTMENT")
    print(f"{'=' * 80}")

    survived_pos = [(d, adj, raw) for d, adj, raw in dim_adj_results if adj > 0.20]
    survived_neg = [(d, adj, raw) for d, adj, raw in dim_adj_results if adj < -0.20]
    lost = [(d, adj, raw) for d, adj, raw in dim_adj_results if abs(raw or 0) > 0.20 and abs(adj) < 0.15]

    if survived_pos:
        print(f"\n  SURVIVED (positive — predict higher ROAS after controlling for awareness):")
        for d, adj, raw in survived_pos:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    if survived_neg:
        print(f"\n  SURVIVED (negative — predict lower ROAS after controlling):")
        for d, adj, raw in survived_neg:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    if lost:
        print(f"\n  LOST (were significant, now not — awareness proxies):")
        for d, adj, raw in lost:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    neither = [d for d, adj, raw in dim_adj_results if abs(raw or 0) <= 0.15 and abs(adj) > 0.25]
    if neither:
        print(f"\n  NEW SIGNALS (hidden by awareness confound, now visible):")
        for d in neither:
            adj = next(a for dim, a, r in dim_adj_results if dim == d)
            raw = next(r for dim, a, r in dim_adj_results if dim == d)
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    # ======================================================================
    # 10. Adjusted composite
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("10. ADJUSTED COMPOSITE SIGNAL")
    print(f"{'=' * 80}")

    top_adj_pos = [d for d, adj, raw in dim_adj_results if adj > 0.15]
    top_adj_neg = [d for d, adj, raw in dim_adj_results if adj < -0.15]

    if top_adj_pos:
        composite_pos = [
            sum(s['dim_scores'].get(d, 0) for d in top_adj_pos) / len(top_adj_pos)
            for s in ads_known
        ]
        sp = _spearman(composite_pos, adjusted_roas)
        print(f"\n  Positive composite ({len(top_adj_pos)} dims): ρ = {sp:+.3f}")
        for d in top_adj_pos:
            print(f"    + {d}")

    if top_adj_neg:
        composite_neg = [
            sum(10 - s['dim_scores'].get(d, 0) for d in top_adj_neg) / len(top_adj_neg)
            for s in ads_known
        ]
        sp = _spearman(composite_neg, adjusted_roas)
        print(f"\n  Negative composite inverted ({len(top_adj_neg)} dims): ρ = {sp:+.3f}")
        for d in top_adj_neg:
            print(f"    - {d}")

    if top_adj_pos and top_adj_neg:
        combined = [
            (sum(s['dim_scores'].get(d, 0) for d in top_adj_pos)
             + sum(10 - s['dim_scores'].get(d, 0) for d in top_adj_neg))
            / (len(top_adj_pos) + len(top_adj_neg))
            for s in ads_known
        ]
        sp = _spearman(combined, adjusted_roas)
        print(f"\n  FULL ADJUSTED COMPOSITE: ρ = {sp:+.3f}")

    # ======================================================================
    # 11. Binary classification: winners vs losers
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("11. BINARY CLASSIFICATION — Winners vs Losers")
    print(f"{'=' * 80}")

    winners = [s for s in scored if s['roas'] >= 3.0]
    losers = [s for s in scored if s['roas'] < 1.0]
    print(f"\n  Winners (≥3x ROAS): n={len(winners)}")
    print(f"  Losers (<1x ROAS):  n={len(losers)}")

    if len(winners) >= 3 and len(losers) >= 3:
        print(f"\n  {'Dimension':<48s} {'Win Avg':>8} {'Loss Avg':>9} {'Δ':>6} {'d':>6}")
        print(f"  {'─'*78}")

        effects = []
        for dim in sorted(all_dims):
            w_vals = [s['dim_scores'].get(dim, 0) for s in winners]
            l_vals = [s['dim_scores'].get(dim, 0) for s in losers]
            w_avg = sum(w_vals) / len(w_vals)
            l_avg = sum(l_vals) / len(l_vals)
            delta = w_avg - l_avg
            # Cohen's d
            pooled_var = ((len(w_vals)-1) * (sum((x-w_avg)**2 for x in w_vals) / max(len(w_vals)-1, 1))
                         + (len(l_vals)-1) * (sum((x-l_avg)**2 for x in l_vals) / max(len(l_vals)-1, 1))) \
                         / max(len(w_vals) + len(l_vals) - 2, 1)
            pooled_sd = pooled_var ** 0.5
            d = delta / pooled_sd if pooled_sd > 0 else 0
            if abs(d) >= 0.4:
                effects.append((dim, w_avg, l_avg, delta, d))

        effects.sort(key=lambda x: abs(x[4]), reverse=True)
        for dim, w_avg, l_avg, delta, d in effects:
            direction = "Winners ↑" if d > 0 else "Losers ↑"
            print(f"  {dim:<48s} {w_avg:>7.1f} {l_avg:>8.1f} {delta:>+5.1f} {d:>+5.2f}  {direction}")

    # ==================================================================
    # 12. MULTI-METRIC CORRELATIONS (--metrics flag)
    # ==================================================================
    if not args.metrics:
        print(f"\n  Tip: run with --metrics to correlate rubric vs CTR, CPM, ATC, IC")
        return

    has_perf = [s for s in scored if '_roas' in s]
    if not has_perf:
        print("\nERROR: No performance data. Cannot run multi-metric analysis.")
        return

    # Define outcome metrics — (key, label, higher_is_better)
    # Cost metrics are inverted: lower cost = better
    outcome_metrics = [
        ('_roas', 'ROAS', True),
        ('_ctr', 'CTR %', True),
        ('_cpm', 'CPM', False),
        ('_atc_rate', 'ATC Rate %', True),
        ('_cost_per_atc', 'Cost/ATC', False),
        ('_conversion_rate', 'Conv Rate %', True),
        ('_cost_per_ic', 'Cost/IC', False),
    ]

    print(f"\n{'=' * 80}")
    print("12. MULTI-METRIC OVERVIEW")
    print(f"{'=' * 80}")

    print(f"\n  {'Metric':<18s} {'n':>4} {'min':>10} {'median':>10} {'max':>10} {'mean':>10}")
    print(f"  {'─'*64}")
    for key, label, _ in outcome_metrics:
        vals = [s[key] for s in has_perf if s.get(key) is not None]
        if not vals:
            print(f"  {label:<18s} {'0':>4}   (no data)")
            continue
        vals_sorted = sorted(vals)
        n = len(vals)
        med = vals_sorted[n // 2]
        print(f"  {label:<18s} {n:>4} {min(vals):>10.2f} {med:>10.2f} {max(vals):>10.2f} {sum(vals)/n:>10.2f}")

    # ==================================================================
    # 13. Overall rubric vs ALL metrics
    # ==================================================================
    print(f"\n{'=' * 80}")
    print("13. OVERALL RUBRIC SCORE vs ALL METRICS")
    print(f"{'=' * 80}")

    rubric_all = [s['rubric_score'] for s in has_perf]

    print(f"\n  {'Outcome Metric':<18s} {'n':>4} {'Spearman':>10} {'Pearson':>10} {'Signal':>8}")
    print(f"  {'─'*55}")
    for key, label, higher_better in outcome_metrics:
        subset = [(s['rubric_score'], s[key]) for s in has_perf if s.get(key) is not None]
        if len(subset) < 4:
            print(f"  {label:<18s} {len(subset):>4}   insufficient data")
            continue
        xs, ys = zip(*subset)
        sp = _spearman(list(xs), list(ys))
        pe = _pearson(list(xs), list(ys))
        # For cost metrics, negative correlation with rubric = good (higher rubric → lower cost)
        effective_sp = sp if higher_better else -sp
        sig = "STRONG" if abs(sp) >= 0.35 else "MEDIUM" if abs(sp) >= 0.25 else "weak" if abs(sp) >= 0.15 else ""
        print(f"  {label:<18s} {len(subset):>4} {sp:>+10.3f} {pe:>+10.3f} {sig:>8}")

    # ==================================================================
    # 14. Gate-level vs ALL metrics
    # ==================================================================
    print(f"\n{'=' * 80}")
    print("14. GATE-LEVEL vs ALL METRICS (Spearman)")
    print(f"{'=' * 80}")

    header_labels = [label[:8] for _, label, _ in outcome_metrics]
    print(f"\n  {'Gate':<38s} " + " ".join(f"{l:>8}" for l in header_labels))
    print(f"  {'─'*38} " + " ".join("─" * 8 for _ in outcome_metrics))

    for gn in range(10):
        row_parts = [f"  G{gn} {GATE_NAMES[gn]:<35s}"]
        for key, label, _ in outcome_metrics:
            subset = [(s['gates'].get(str(gn), 0), s[key]) for s in has_perf if s.get(key) is not None]
            if len(subset) < 4:
                row_parts.append(f"{'---':>8}")
                continue
            xs, ys = zip(*subset)
            sp = _spearman(list(xs), list(ys))
            flag = "**" if abs(sp) >= 0.25 else "* " if abs(sp) >= 0.15 else "  "
            row_parts.append(f"{sp:>+6.3f}{flag}")
        print(" ".join(row_parts))

    # ==================================================================
    # 15. Top dimensions per metric (Spearman > 0.20)
    # ==================================================================
    print(f"\n{'=' * 80}")
    print("15. TOP DIMENSIONS PER METRIC (|ρ| > 0.20)")
    print(f"{'=' * 80}")

    for key, label, higher_better in outcome_metrics:
        subset_ads = [s for s in has_perf if s.get(key) is not None]
        if len(subset_ads) < 8:
            continue
        metric_vals = [s[key] for s in subset_ads]

        print(f"\n  ── {label} (n={len(subset_ads)}) ──")
        dim_corrs = []
        for dim in sorted(all_dims):
            vals = [s['dim_scores'].get(dim, 0) for s in subset_ads]
            if max(vals) > min(vals):
                sp = _spearman(vals, metric_vals)
                if sp is not None and abs(sp) > 0.20:
                    dim_corrs.append((dim, sp))
        dim_corrs.sort(key=lambda x: abs(x[1]), reverse=True)
        if dim_corrs:
            for dim, sp in dim_corrs[:15]:
                direction = ("↑" + label) if (sp > 0) == higher_better else ("↓" + label)
                flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  "
                print(f"    {dim:<48s} ρ = {sp:+.3f} {flag} {direction}")
        else:
            print(f"    (no dimensions with |ρ| > 0.20)")

    # ==================================================================
    # 16. Multi-metric by awareness level
    # ==================================================================
    print(f"\n{'=' * 80}")
    print("16. MULTI-METRIC BY AWARENESS LEVEL")
    print(f"{'=' * 80}")

    for level in ['problem_aware', 'solution_aware', 'product_aware', 'most_aware']:
        group = [s for s in has_perf if s.get('awareness') == level]
        if len(group) < 5:
            continue

        print(f"\n  {'━' * 74}")
        print(f"  {level.upper()} (n={len(group)})")
        print(f"  {'━' * 74}")

        # Summary stats for this level
        print(f"\n    {'Metric':<18s} {'mean':>8} {'median':>8}")
        print(f"    {'─'*36}")
        for key, label, _ in outcome_metrics:
            vals = [s[key] for s in group if s.get(key) is not None]
            if not vals:
                continue
            vals_s = sorted(vals)
            print(f"    {label:<18s} {sum(vals)/len(vals):>8.2f} {vals_s[len(vals_s)//2]:>8.2f}")

        # Rubric score vs each metric within this level
        print(f"\n    Rubric Score vs metrics:")
        for key, label, higher_better in outcome_metrics:
            subset = [(s['rubric_score'], s[key]) for s in group if s.get(key) is not None]
            if len(subset) < 5:
                continue
            xs, ys = zip(*subset)
            sp = _spearman(list(xs), list(ys))
            flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  " if abs(sp) >= 0.15 else "   "
            print(f"      {label:<18s} ρ = {sp:+.3f} {flag}")

        # Top dimensions per metric within this awareness level
        for key, label, higher_better in outcome_metrics:
            subset_ads = [s for s in group if s.get(key) is not None]
            if len(subset_ads) < 5:
                continue
            metric_vals = [s[key] for s in subset_ads]
            dim_corrs = []
            for dim in sorted(all_dims):
                vals = [s['dim_scores'].get(dim, 0) for s in subset_ads]
                if max(vals) > min(vals):
                    sp = _spearman(vals, metric_vals)
                    if sp is not None and abs(sp) > 0.30:
                        dim_corrs.append((dim, sp))
            dim_corrs.sort(key=lambda x: abs(x[1]), reverse=True)
            if dim_corrs:
                print(f"\n    Top dims for {label} (|ρ| > 0.30):")
                for dim, sp in dim_corrs[:10]:
                    flag = "***" if abs(sp) >= 0.5 else "** " if abs(sp) >= 0.4 else "*  "
                    print(f"      {dim:<46s} ρ = {sp:+.3f} {flag}")

    # ==================================================================
    # 17. Cross-metric signal consistency
    # ==================================================================
    print(f"\n{'=' * 80}")
    print("17. CROSS-METRIC SIGNAL CONSISTENCY")
    print("    Dimensions that correlate with 3+ metrics (|ρ| > 0.20)")
    print(f"{'=' * 80}")

    dim_metric_hits = defaultdict(list)
    for key, label, higher_better in outcome_metrics:
        subset_ads = [s for s in has_perf if s.get(key) is not None]
        if len(subset_ads) < 8:
            continue
        metric_vals = [s[key] for s in subset_ads]
        for dim in sorted(all_dims):
            vals = [s['dim_scores'].get(dim, 0) for s in subset_ads]
            if max(vals) > min(vals):
                sp = _spearman(vals, metric_vals)
                if sp is not None and abs(sp) > 0.20:
                    # Normalize direction: positive = helps performance
                    effective_sp = sp if higher_better else -sp
                    dim_metric_hits[dim].append((label, sp, effective_sp))

    consistent_dims = [(dim, hits) for dim, hits in dim_metric_hits.items() if len(hits) >= 3]
    consistent_dims.sort(key=lambda x: len(x[1]), reverse=True)

    if consistent_dims:
        for dim, hits in consistent_dims:
            avg_effective = sum(h[2] for h in hits) / len(hits)
            direction = "HELPS" if avg_effective > 0 else "HURTS"
            print(f"\n  {dim} — {len(hits)} metrics, avg effect: {avg_effective:+.3f} ({direction})")
            for label, raw_sp, eff_sp in hits:
                print(f"    {label:<18s} ρ = {raw_sp:+.3f}")
    else:
        print("\n  No dimensions correlated with 3+ metrics.")


if __name__ == "__main__":
    main()
