"""
Awareness-controlled rubric analysis.

Uses cached scored data + awareness classifications to test whether
rubric dimensions predict ROAS *within* the same awareness level,
or whether they're just proxies for awareness level.
"""

import json
import sys
from collections import Counter, defaultdict
sys.path.insert(0, '.')

CACHE_FILE = "/tmp/rubric_scored_cache.json"


def _rank(values):
    """Assign ranks (average rank for ties)."""
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
        return None  # Not enough data
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


def main():
    # Load cached scores
    with open(CACHE_FILE) as f:
        scored = json.load(f)
    print(f"Loaded {len(scored)} scored ads from cache")

    # Fetch awareness classifications
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()

    meta_ids = [s['meta_ad_id'] for s in scored]
    result = supabase.table('ad_creative_classifications').select(
        'meta_ad_id, creative_awareness_level, copy_awareness_level'
    ).in_('meta_ad_id', meta_ids).order('classified_at', desc=True).execute()

    # Dedupe: keep latest classification per ad
    awareness_map = {}
    for row in result.data:
        mid = row['meta_ad_id']
        if mid not in awareness_map:
            awareness_map[mid] = row['creative_awareness_level']

    # Merge awareness into scored data
    for s in scored:
        s['awareness'] = awareness_map.get(s['meta_ad_id'], 'unknown')

    # Stats
    awareness_counts = Counter(s['awareness'] for s in scored)
    print(f"\nAwareness distribution:")
    for level, count in sorted(awareness_counts.items(), key=lambda x: -x[1]):
        avg_roas = sum(s['roas'] for s in scored if s['awareness'] == level) / max(count, 1)
        avg_rubric = sum(s['rubric_score'] for s in scored if s['awareness'] == level) / max(count, 1)
        print(f"  {level:<20s} n={count:>2}  avg ROAS={avg_roas:>5.1f}x  avg rubric={avg_rubric:>4.0f}")

    # ======================================================================
    # 1. Does awareness level predict ROAS? (confirming the user's hypothesis)
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("1. DOES AWARENESS LEVEL PREDICT ROAS?")
    print(f"{'=' * 80}")

    # Encode awareness as ordinal
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

        if sp_aw_roas and abs(sp_aw_roas) > 0.2:
            print(f"\n  ⚠ CONFIRMED: Awareness level predicts ROAS (ρ={sp_aw_roas:+.3f}).")
            print(f"    Rubric dimensions that correlate with ROAS may just be proxies for awareness.")
        else:
            print(f"\n  Awareness level does NOT strongly predict ROAS in this dataset.")

    # ======================================================================
    # 2. ROAS by awareness level breakdown
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("2. DETAILED BREAKDOWN BY AWARENESS LEVEL")
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
        print(f"    Ads:")
        for s in sorted(group, key=lambda x: -x['roas']):
            print(f"      {s['roas']:>5.1f}x  {s['rubric_score']:>3.0f} ({s['grade']})  {s['ad_name'][:45]}")

    # ======================================================================
    # 3. WITHIN-AWARENESS correlations (the real test)
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("3. WITHIN-AWARENESS CORRELATIONS (controlling for funnel position)")
    print(f"{'=' * 80}")
    print(f"\n  Testing: do rubric dimensions predict ROAS *within the same awareness level*?")

    # Get all dimension names
    all_dims = set()
    for s in scored:
        all_dims.update(s['dim_scores'].keys())

    for level in ['solution_aware', 'product_aware']:
        group = [s for s in scored if s['awareness'] == level]
        if len(group) < 5:
            print(f"\n  {level.upper()}: skipping (n={len(group)}, need ≥5)")
            continue

        print(f"\n  {'─' * 70}")
        print(f"  {level.upper()} (n={len(group)})")
        print(f"  {'─' * 70}")

        roas_vals = [s['roas'] for s in group]

        # Overall rubric vs ROAS within this level
        rubric_vals = [s['rubric_score'] for s in group]
        sp_overall = _spearman(rubric_vals, roas_vals)
        print(f"\n    Overall Rubric vs ROAS: ρ = {sp_overall:+.3f}" if sp_overall is not None else "\n    Overall: insufficient data")

        # Gate-level
        from viraltracker.services.rubric_scoring_service import GATE_NAMES
        print(f"\n    Gate-level:")
        gate_results = []
        for gn in range(10):
            gate_vals = [s['gates'].get(str(gn), 0) for s in group]
            sp = _spearman(gate_vals, roas_vals)
            if sp is not None:
                gate_results.append((gn, sp))

        gate_results.sort(key=lambda x: x[1], reverse=True)
        for gn, sp in gate_results:
            flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  " if abs(sp) >= 0.15 else "   "
            print(f"      G{gn} {GATE_NAMES[gn]:<32s} ρ = {sp:+.3f} {flag}")

        # Dimension-level (only show |ρ| > 0.2)
        print(f"\n    Dimensions with |ρ| > 0.20:")
        dim_results = []
        for dim in sorted(all_dims):
            vals = [s['dim_scores'].get(dim, 0) for s in group]
            if max(vals) > min(vals):
                sp = _spearman(vals, roas_vals)
                if sp is not None and abs(sp) > 0.20:
                    dim_results.append((dim, sp))

        dim_results.sort(key=lambda x: abs(x[1]), reverse=True)
        if dim_results:
            for dim, sp in dim_results:
                flag = "***" if abs(sp) >= 0.4 else "** " if abs(sp) >= 0.25 else "*  "
                direction = "↑ROAS" if sp > 0 else "↓ROAS"
                print(f"      {dim:<48s} ρ = {sp:+.3f} {flag} {direction}")
        else:
            print(f"      (none)")

    # ======================================================================
    # 4. PARTIAL CORRELATION — rubric dims controlling for awareness
    # ======================================================================
    print(f"\n{'=' * 80}")
    print("4. RESIDUALIZED ANALYSIS — Rubric Dimensions After Removing Awareness Effect")
    print(f"{'=' * 80}")
    print(f"\n  Method: Rank-residualize ROAS against awareness level,")
    print(f"  then correlate rubric dimensions with the residual.")
    print(f"  This removes the 'BOF ads just perform better' confound.\n")

    ads_known = [s for s in scored if s['awareness'] != 'unknown']
    if len(ads_known) < 10:
        print("  Not enough ads with known awareness level.")
        return

    # Compute awareness-adjusted ROAS (residual)
    # Group by awareness, compute within-group rank percentile
    by_awareness = defaultdict(list)
    for s in ads_known:
        by_awareness[s['awareness']].append(s)

    # For each ad, compute its ROAS percentile within its awareness group
    for level, group in by_awareness.items():
        sorted_group = sorted(group, key=lambda x: x['roas'])
        for rank_idx, s in enumerate(sorted_group):
            s['roas_percentile_within_awareness'] = rank_idx / max(len(sorted_group) - 1, 1)

    # Now correlate dimensions with awareness-adjusted ROAS percentile
    adjusted_roas = [s['roas_percentile_within_awareness'] for s in ads_known]

    dim_adj_results = []
    for dim in sorted(all_dims):
        vals = [s['dim_scores'].get(dim, 0) for s in ads_known]
        if max(vals) > min(vals):
            sp = _spearman(vals, adjusted_roas)
            if sp is not None:
                # Also get the unadjusted correlation for comparison
                sp_raw = _spearman(vals, [s['roas'] for s in ads_known])
                dim_adj_results.append((dim, sp, sp_raw))

    dim_adj_results.sort(key=lambda x: abs(x[1]), reverse=True)

    print(f"  {'Dimension':<48s} {'ρ adjusted':>11} {'ρ raw':>8} {'Change':>8}")
    print(f"  {'─'*78}")
    for dim, sp_adj, sp_raw in dim_adj_results:
        change = sp_adj - (sp_raw or 0)
        flag = "***" if abs(sp_adj) >= 0.35 else "** " if abs(sp_adj) >= 0.25 else "*  " if abs(sp_adj) >= 0.15 else "   "
        print(f"  {dim:<48s} {sp_adj:>+10.3f} {sp_raw:>+7.3f} {change:>+7.3f} {flag}")

    # Summary: which signals survive awareness adjustment?
    print(f"\n{'=' * 80}")
    print("5. VERDICT — WHICH SIGNALS SURVIVE AWARENESS ADJUSTMENT?")
    print(f"{'=' * 80}")

    survived_pos = [(d, adj, raw) for d, adj, raw in dim_adj_results if adj > 0.20]
    survived_neg = [(d, adj, raw) for d, adj, raw in dim_adj_results if adj < -0.20]
    lost = [(d, adj, raw) for d, adj, raw in dim_adj_results if abs(raw or 0) > 0.20 and abs(adj) < 0.15]

    if survived_pos:
        print(f"\n  ✓ SURVIVED (positive — still predict higher ROAS after controlling for awareness):")
        for d, adj, raw in survived_pos:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    if survived_neg:
        print(f"\n  ✓ SURVIVED (negative — still predict lower ROAS after controlling):")
        for d, adj, raw in survived_neg:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    if lost:
        print(f"\n  ✗ LOST (were significant, now not — were just awareness proxies):")
        for d, adj, raw in lost:
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    neither = [d for d, adj, raw in dim_adj_results
               if abs(raw or 0) <= 0.15 and abs(adj) > 0.25]
    if neither:
        print(f"\n  ★ NEW SIGNALS (hidden by awareness confound, now visible):")
        for d in neither:
            adj = next(a for dim, a, r in dim_adj_results if dim == d)
            raw = next(r for dim, a, r in dim_adj_results if dim == d)
            print(f"    {d:<48s} ρ={adj:+.3f} (was {raw:+.3f})")

    # Composite test with adjusted values
    print(f"\n{'=' * 80}")
    print("6. ADJUSTED COMPOSITE SIGNAL")
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


if __name__ == "__main__":
    main()
