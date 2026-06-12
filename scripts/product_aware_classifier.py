"""
Product-aware creative feature classifier.
Codes ~30 binary/categorical features for product-aware ads and correlates
against performance metrics (ROAS, CTR, ATC rate, etc.).

Usage:
  Score:   python3 scripts/product_aware_classifier.py score "Martin Clinic" [--model sonnet]
  Analyze: python3 scripts/product_aware_classifier.py analyze "Martin Clinic"
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
sys.path.insert(0, '.')

PA_CACHE_PREFIX = "/tmp/pa_features_"

PA_CLASSIFIER_PROMPT = """You are analyzing a static image ad. Code each feature exactly as specified — no elaboration, just the values.

Return ONLY valid JSON matching this schema:

```json
{
  "product_presentation": {
    "product_visible": 0,
    "product_dominant": 0,
    "product_context": "isolated",
    "image_quality_ok": 1,
    "product_count": 1,
    "human_present": 0,
    "face_visible": 0
  },
  "branding": {
    "logo_present": 0,
    "logo_placement": "absent"
  },
  "copy_text": {
    "text_overlay_present": 0,
    "headline_word_count": 0,
    "total_word_count": 0,
    "headline_type": "other",
    "cta_present": 0,
    "cta_action_verb": 0,
    "text_readable": 1
  },
  "value_hook": {
    "price_shown": 0,
    "discount_shown": 0,
    "urgency_cue": 0,
    "social_proof_present": 0,
    "feature_callout": 0,
    "guarantee_language": 0
  },
  "composition": {
    "single_focal_point": 0,
    "clean_layout": 0,
    "product_bg_contrast": 0,
    "cta_accent_color": 0,
    "background_type": "solid"
  },
  "audience_context": {
    "use_case_depicted": 0,
    "complementary_props": 0,
    "demographic_signaling": 0
  }
}
```

## Field definitions

**product_presentation:**
- product_visible (0/1): Is the actual product (bottle, box, supplement, etc.) visible in the image?
- product_dominant (0/1): Is the product the largest/most prominent visual element?
- product_context: "in_use" (product shown being used or in a lifestyle setting), "isolated" (product on plain/simple background), "hybrid" (mix), "none" (product not visible)
- image_quality_ok (0/1): Is the image free of visible artifacts, distortion, low-res blurriness?
- product_count (integer): Number of distinct product items/SKUs visible (0 if no product shown)
- human_present (0/1): Is a person (photo, not illustration) visible?
- face_visible (0/1): Is a human face clearly visible?

**branding:**
- logo_present (0/1): Is a brand/company logo visible?
- logo_placement: "corner" (small, in a corner), "center" (prominently centered), "integrated" (worked into the design), "absent" (no logo)

**copy_text:**
- text_overlay_present (0/1): Is there ANY text overlaid on the image?
- headline_word_count (integer): Number of words in the primary/largest text element (0 if no text)
- total_word_count (integer): Total words visible on the image
- headline_type: What does the main text communicate? "benefit" (what user gains), "feature" (product spec/ingredient), "offer" (price/discount/deal), "brand" (brand name/slogan only), "question" (asks a question), "statistic" (cites a number/stat), "other"
- cta_present (0/1): Is there a call-to-action button or text (Shop Now, Learn More, Get Yours, etc.)?
- cta_action_verb (0/1): Does the CTA start with an action verb (Shop, Get, Try, Buy, Order, etc.)?
- text_readable (0/1): Is ALL text large enough to read easily on a mobile phone screen?

**value_hook:**
- price_shown (0/1): Is a specific price or price point visible ($XX, $XX.XX)?
- discount_shown (0/1): Is a discount, percentage off, or savings amount shown?
- urgency_cue (0/1): Is there urgency language visible (limited time, ends soon, today only, last chance, etc.)?
- social_proof_present (0/1): Is there social proof visible (star rating, review count, press logo, "bestseller", "X sold", testimonial quote)?
- feature_callout (0/1): Is there a product feature or ingredient callout/badge visible?
- guarantee_language (0/1): Is there guarantee or risk-reversal language (free returns, money-back, satisfaction guaranteed)?

**composition:**
- single_focal_point (0/1): Does the image have ONE clear main subject/focus area (vs. multiple competing elements)?
- clean_layout (0/1): Does the ad have breathing room / negative space (vs. being cluttered with text and elements)?
- product_bg_contrast (0/1): Does the product stand out clearly against its background through color/value contrast?
- cta_accent_color (0/1): Is there a contrasting accent color used for the CTA button or offer text?
- background_type: "solid" (single color), "gradient" (color gradient), "lifestyle" (real photo/scene), "pattern" (repeating pattern/texture), "product_closeup" (zoomed in on product)

**audience_context:**
- use_case_depicted (0/1): Is the product shown in a real-world use scenario (someone taking a supplement, product on a nightstand, etc.)?
- complementary_props (0/1): Are there scene-setting objects that suggest a lifestyle (coffee cup, gym equipment, book, etc.)?
- demographic_signaling (0/1): Does the image signal a specific demographic through model choice, setting, or styling?

## Important
- Code ONLY what is visible in the image. Do not infer from the ad name or copy provided.
- For binary fields, use exactly 0 or 1 (integers, not strings).
- For categorical fields, use exactly one of the listed options.
- Return ONLY the JSON object, no explanation or commentary.
"""


def cache_path(brand_name):
    slug = brand_name.lower().replace(' ', '_')
    return f"{PA_CACHE_PREFIX}{slug}.json"


def rubric_cache_path(brand_name):
    slug = brand_name.lower().replace(' ', '_')
    return f"/tmp/rubric_scored_{slug}.json"


def load_cache(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_cache(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def flatten_features(features_dict):
    """Flatten nested feature dict into flat key->value."""
    flat = {}
    for category, dims in features_dict.items():
        if isinstance(dims, dict):
            for key, val in dims.items():
                flat[f"{category}__{key}"] = val
    return flat


# ── Correlation helpers (same as rubric_analyze_brand.py) ──

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


def _cohens_d(group_a, group_b):
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    mean_a = sum(group_a) / len(group_a)
    mean_b = sum(group_b) / len(group_b)
    var_a = sum((x - mean_a) ** 2 for x in group_a) / (len(group_a) - 1)
    var_b = sum((x - mean_b) ** 2 for x in group_b) / (len(group_b) - 1)
    pooled = (((len(group_a) - 1) * var_a + (len(group_b) - 1) * var_b)
              / (len(group_a) + len(group_b) - 2))
    pooled_sd = pooled ** 0.5
    if pooled_sd == 0:
        return 0.0
    return (mean_a - mean_b) / pooled_sd


# ── Score command ──

async def cmd_score(args):
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.rubric_scoring_service import RubricScoringService

    supabase = get_supabase_client()

    # Find brand — prefer exact match, fall back to substring
    brand_result = supabase.table('brands').select('id, name').ilike('name', args.brand).limit(1).execute()
    if not brand_result.data:
        brand_result = supabase.table('brands').select('id, name').ilike('name', f'%{args.brand}%').limit(1).execute()
    if not brand_result.data:
        print(f"ERROR: Brand matching '{args.brand}' not found")
        return
    brand = brand_result.data[0]
    brand_id = brand['id']
    brand_name = brand['name']

    # Try rubric cache first, fall back to DB for ad list
    rcpath = rubric_cache_path(brand_name)
    rubric_data = load_cache(rcpath)

    if rubric_data:
        print(f"Using rubric cache ({len(rubric_data)} ads)")
        meta_ids = [s['meta_ad_id'] for s in rubric_data]
    else:
        print(f"No rubric cache — pulling image ads from DB (min spend ${args.min_spend})")
        from datetime import date, timedelta
        from collections import defaultdict

        # Get image-classified ad IDs with assets
        img_cls = supabase.table('ad_creative_classifications').select(
            'meta_ad_id'
        ).eq('brand_id', brand_id).ilike('creative_format', 'image%').execute()
        classified_ids = list(set(r['meta_ad_id'] for r in img_cls.data))

        assets = supabase.table('meta_ad_assets').select(
            'meta_ad_id'
        ).eq('brand_id', brand_id).execute()
        asset_ids = set(r['meta_ad_id'] for r in assets.data)

        scoreable_ids = [mid for mid in classified_ids if mid in asset_ids]
        print(f"  {len(classified_ids)} image-classified, {len(asset_ids)} with assets, {len(scoreable_ids)} scoreable")

        # Get performance data to filter by spend and get ROAS
        end = date.today()
        start = end - timedelta(days=args.days)
        scoreable_set = set(scoreable_ids)
        all_rows = []
        offset = 0
        while True:
            result = supabase.table("meta_ads_performance").select(
                "meta_ad_id, spend, purchase_value, ad_name"
            ).eq("brand_id", brand_id).gte("date", start.isoformat()).lte(
                "date", end.isoformat()
            ).range(offset, offset + 999).execute()
            if not result.data:
                break
            # Filter to scoreable ads in Python
            all_rows.extend(r for r in result.data if r.get("meta_ad_id") in scoreable_set)
            if len(result.data) < 1000:
                break
            offset += 1000

        # Aggregate per ad
        agg = defaultdict(lambda: {"spend": 0, "pv": 0, "name": ""})
        for row in all_rows:
            mid = row.get("meta_ad_id")
            if mid:
                agg[mid]["spend"] += float(row.get("spend") or 0)
                agg[mid]["pv"] += float(row.get("purchase_value") or 0)
                if row.get("ad_name"):
                    agg[mid]["name"] = row["ad_name"]

        # Build rubric_data-like list filtered by min spend
        rubric_data = []
        for mid, a in agg.items():
            if a["spend"] >= args.min_spend:
                rubric_data.append({
                    "meta_ad_id": mid,
                    "ad_name": a["name"],
                    "roas": (a["pv"] / a["spend"]) if a["spend"] > 0 else 0,
                    "spend": a["spend"],
                })

        rubric_data.sort(key=lambda x: x["roas"], reverse=True)
        print(f"  {len(rubric_data)} ads with ${args.min_spend}+ spend")
        meta_ids = [s['meta_ad_id'] for s in rubric_data]

    if not rubric_data:
        print("No ads found.")
        return

    # Get awareness classifications
    cls_result = supabase.table('ad_creative_classifications').select(
        'meta_ad_id, creative_awareness_level'
    ).in_('meta_ad_id', meta_ids).order('classified_at', desc=True).execute()

    awareness_map = {}
    for row in cls_result.data:
        mid = row['meta_ad_id']
        if mid not in awareness_map:
            awareness_map[mid] = row['creative_awareness_level']

    # Filter to product-aware only (unless --all)
    if args.all_awareness:
        target_ads = rubric_data
        print(f"Targeting ALL awareness levels ({len(target_ads)} ads)")
    else:
        target_ads = [s for s in rubric_data if awareness_map.get(s['meta_ad_id']) == 'product_aware']
        print(f"Product-aware ads: {len(target_ads)} of {len(rubric_data)} total")

    if not target_ads:
        print("No target ads found.")
        return

    # Load existing PA cache
    pa_cpath = cache_path(brand_name)
    cached = load_cache(pa_cpath)
    cached_ids = {s['meta_ad_id'] for s in cached}
    new_ads = [s for s in target_ads if s['meta_ad_id'] not in cached_ids]

    print(f"Cache: {len(cached)} already scored, {len(new_ads)} new to score")

    if not new_ads:
        print("Nothing new to score.")
        return

    rubric_service = RubricScoringService(supabase=supabase)
    new_scored = []
    skipped = 0
    total_start = time.time()

    model_id = {
        "sonnet": "anthropic:claude-sonnet-4-5-20250929",
        "opus": "anthropic:claude-opus-4-7",
    }[args.model]

    print(f"\n{'#':<3} {'Ad Name':<45} {'ROAS':>6} {'Status':>8}")
    print("-" * 65)

    for i, ad in enumerate(new_ads, 1):
        meta_ad_id = ad['meta_ad_id']
        ad_name = (ad.get('ad_name') or 'Unnamed')[:43]
        roas = ad.get('roas', 0) or 0

        image_bytes = await rubric_service._download_ad_image(meta_ad_id, brand_id)
        if not image_bytes:
            print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x   SKIP")
            skipped += 1
            continue

        # Score with Claude
        try:
            from pydantic_ai import Agent
            from pydantic_ai.messages import BinaryContent
            from viraltracker.services.rubric_scoring_service import _detect_media_type, _parse_json_response

            agent = Agent(
                model=model_id,
                system_prompt="You are an expert ad creative analyst. Code visual features of ads precisely.",
            )
            media_type = _detect_media_type(image_bytes)
            result = await agent.run([
                PA_CLASSIFIER_PROMPT,
                BinaryContent(data=image_bytes, media_type=media_type),
            ])
            features = _parse_json_response(result.output)
        except Exception as e:
            print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x   ERR: {str(e)[:30]}")
            skipped += 1
            continue

        entry = {
            "meta_ad_id": meta_ad_id,
            "ad_name": ad_name,
            "roas": roas,
            "spend": ad.get('spend', 0) or 0,
            "awareness": awareness_map.get(meta_ad_id, 'unknown'),
            "features": features,
        }
        new_scored.append(entry)
        print(f"{i:<3} {ad_name:<45} {roas:>5.1f}x   OK")

    elapsed = time.time() - total_start
    merged = cached + new_scored
    save_cache(pa_cpath, merged)

    print(f"\n{'=' * 65}")
    print(f"Scored {len(new_scored)} ads ({skipped} skipped) in {elapsed:.0f}s")
    print(f"Cache: {pa_cpath} ({len(merged)} total)")
    print(f"{'=' * 65}")
    print(f"\nNext: python3 scripts/product_aware_classifier.py analyze \"{brand_name}\"")


# ── Analyze command ──

def cmd_analyze(args):
    from datetime import date, timedelta
    from viraltracker.core.database import get_supabase_client

    supabase = get_supabase_client()

    # Load PA feature cache
    pa_cpath = cache_path(args.brand)
    scored = load_cache(pa_cpath)
    if not scored:
        print(f"ERROR: No PA feature cache at {pa_cpath}. Run 'score' first.")
        return

    # Resolve brand for performance enrichment
    brand_result = supabase.table('brands').select('id, name').ilike('name', args.brand).limit(1).execute()
    if not brand_result.data:
        brand_result = supabase.table('brands').select('id, name').ilike('name', f'%{args.brand}%').limit(1).execute()
    brand_id = brand_result.data[0]['id'] if brand_result.data else None
    brand_name = brand_result.data[0]['name'] if brand_result.data else args.brand

    print(f"{'=' * 80}")
    print(f"PRODUCT-AWARE FEATURE ANALYSIS — {brand_name}")
    print(f"{'=' * 80}")
    print(f"Loaded {len(scored)} scored ads")

    # ── Enrich with fresh performance metrics ──
    if brand_id:
        meta_ids = [s['meta_ad_id'] for s in scored]
        end = date.today()
        start = end - timedelta(days=args.days)

        all_rows = []
        offset = 0
        while True:
            result = (
                supabase.table("meta_ads_performance")
                .select("meta_ad_id, spend, impressions, link_clicks, add_to_carts, "
                        "initiate_checkouts, purchases, purchase_value")
                .eq("brand_id", brand_id)
                .gte("date", start.isoformat())
                .lte("date", end.isoformat())
                .in_("meta_ad_id", meta_ids)
                .range(offset, offset + 999)
                .execute()
            )
            if not result.data:
                break
            all_rows.extend(result.data)
            if len(result.data) < 1000:
                break
            offset += 1000

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

        for s in scored:
            mid = s["meta_ad_id"]
            a = agg.get(mid)
            if not a:
                continue
            imp = a["impressions"]
            clicks = a["link_clicks"]
            spend = a["spend"]
            pv = a["purchase_value"]
            s["_roas"] = (pv / spend) if spend > 0 else 0
            s["_ctr"] = (clicks / imp * 100) if imp > 0 else 0
            s["_cpm"] = (spend / imp * 1000) if imp > 0 else 0
            s["_add_to_carts"] = a["add_to_carts"]
            s["_atc_rate"] = (a["add_to_carts"] / clicks * 100) if clicks > 0 else 0
            s["_cost_per_atc"] = (spend / a["add_to_carts"]) if a["add_to_carts"] > 0 else None
            s["_initiate_checkouts"] = a["initiate_checkouts"]
            s["_cost_per_ic"] = (spend / a["initiate_checkouts"]) if a["initiate_checkouts"] > 0 else None
            s["_conv_rate"] = (a["purchases"] / clicks * 100) if clicks > 0 else 0
            s["_purchases"] = a["purchases"]
            s["_cpa"] = (spend / a["purchases"]) if a["purchases"] > 0 else None
            s["_spend"] = spend

    has_perf = [s for s in scored if '_roas' in s]
    print(f"Enriched {len(has_perf)}/{len(scored)} with performance data\n")

    if not has_perf:
        print("ERROR: No performance data available.")
        return

    # Flatten features
    for s in has_perf:
        s['_flat'] = flatten_features(s.get('features', {}))

    # Collect all feature keys
    all_keys = set()
    for s in has_perf:
        all_keys.update(s['_flat'].keys())

    # Separate binary/numeric features from categorical
    binary_keys = []
    categorical_keys = []
    numeric_keys = []
    for key in sorted(all_keys):
        sample_vals = [s['_flat'].get(key) for s in has_perf if key in s['_flat']]
        if not sample_vals:
            continue
        if all(isinstance(v, (int, float)) for v in sample_vals):
            unique = set(sample_vals)
            if unique <= {0, 1, 0.0, 1.0}:
                binary_keys.append(key)
            else:
                numeric_keys.append(key)
        else:
            categorical_keys.append(key)

    outcome_metrics = [
        ('_roas', 'ROAS', True),
        ('_ctr', 'CTR %', True),
        ('_cpm', 'CPM', False),
        ('_atc_rate', 'ATC Rate %', True),
        ('_cost_per_atc', 'Cost/ATC', False),
        ('_conv_rate', 'Conv Rate %', True),
        ('_cost_per_ic', 'Cost/IC', False),
        ('_cpa', 'CPA', False),
    ]

    # ── 1. Feature prevalence ──
    print(f"{'=' * 80}")
    print("1. FEATURE PREVALENCE (binary features)")
    print(f"{'=' * 80}")

    print(f"\n  {'Feature':<45s} {'Present':>8} {'Absent':>8} {'%':>6}")
    print(f"  {'─'*70}")
    for key in binary_keys:
        present = sum(1 for s in has_perf if s['_flat'].get(key) == 1)
        absent = len(has_perf) - present
        pct = present / len(has_perf) * 100
        print(f"  {key:<45s} {present:>8} {absent:>8} {pct:>5.0f}%")

    # ── 2. Binary features vs outcome metrics (Cohen's d) ──
    print(f"\n{'=' * 80}")
    print("2. BINARY FEATURES vs OUTCOME METRICS (Cohen's d)")
    print(f"   Positive d = feature PRESENT performs better")
    print(f"{'=' * 80}")

    header = [f"{l[:8]:>8}" for _, l, _ in outcome_metrics]
    print(f"\n  {'Feature':<42s} " + " ".join(header))
    print(f"  {'─'*42} " + " ".join("─" * 8 for _ in outcome_metrics))

    feature_hits = defaultdict(list)  # for cross-metric consistency

    for key in binary_keys:
        row_parts = [f"  {key:<42s}"]
        for metric_key, label, higher_better in outcome_metrics:
            present = [s[metric_key] for s in has_perf if s['_flat'].get(key) == 1 and s.get(metric_key) is not None]
            absent = [s[metric_key] for s in has_perf if s['_flat'].get(key) == 0 and s.get(metric_key) is not None]
            d = _cohens_d(present, absent)
            if d is None or len(present) < 3 or len(absent) < 3:
                row_parts.append(f"{'---':>8}")
                continue
            # For cost metrics, flip sign so positive = good
            effective_d = d if higher_better else -d
            flag = "**" if abs(d) >= 0.5 else "* " if abs(d) >= 0.3 else "  "
            row_parts.append(f"{d:>+6.2f}{flag}")
            if abs(d) >= 0.3:
                feature_hits[key].append((label, d, effective_d))
        print(" ".join(row_parts))

    # ── 3. Numeric features vs outcome metrics (Spearman) ──
    if numeric_keys:
        print(f"\n{'=' * 80}")
        print("3. NUMERIC FEATURES vs OUTCOME METRICS (Spearman ρ)")
        print(f"{'=' * 80}")

        print(f"\n  {'Feature':<42s} " + " ".join(header))
        print(f"  {'─'*42} " + " ".join("─" * 8 for _ in outcome_metrics))

        for key in numeric_keys:
            row_parts = [f"  {key:<42s}"]
            for metric_key, label, higher_better in outcome_metrics:
                subset = [(s['_flat'][key], s[metric_key])
                          for s in has_perf
                          if key in s['_flat'] and s.get(metric_key) is not None]
                if len(subset) < 5:
                    row_parts.append(f"{'---':>8}")
                    continue
                xs, ys = zip(*subset)
                sp = _spearman(list(xs), list(ys))
                if sp is None:
                    row_parts.append(f"{'---':>8}")
                    continue
                flag = "**" if abs(sp) >= 0.35 else "* " if abs(sp) >= 0.20 else "  "
                row_parts.append(f"{sp:>+6.3f}{flag}")
                effective_sp = sp if higher_better else -sp
                if abs(sp) >= 0.20:
                    feature_hits[key].append((label, sp, effective_sp))
            print(" ".join(row_parts))

    # ── 4. Categorical features vs ROAS (mean comparison) ──
    if categorical_keys:
        print(f"\n{'=' * 80}")
        print("4. CATEGORICAL FEATURES vs ROAS")
        print(f"{'=' * 80}")

        for key in categorical_keys:
            by_cat = defaultdict(list)
            for s in has_perf:
                val = s['_flat'].get(key)
                if val is not None:
                    by_cat[str(val)].append(s)

            if len(by_cat) < 2:
                continue

            print(f"\n  {key}:")
            print(f"    {'Value':<20s} {'n':>4} {'ROAS':>8} {'CTR':>8} {'ATC%':>8} {'Conv%':>8}")
            print(f"    {'─'*52}")
            for val in sorted(by_cat.keys()):
                group = by_cat[val]
                n = len(group)
                avg_roas = sum(s['_roas'] for s in group) / n
                avg_ctr = sum(s['_ctr'] for s in group) / n
                avg_atc = sum(s['_atc_rate'] for s in group) / n
                avg_conv = sum(s['_conv_rate'] for s in group) / n
                print(f"    {val:<20s} {n:>4} {avg_roas:>7.1f}x {avg_ctr:>7.2f} {avg_atc:>7.2f} {avg_conv:>7.2f}")

    # ── 5. Cross-metric signal consistency ──
    print(f"\n{'=' * 80}")
    print("5. CROSS-METRIC SIGNAL CONSISTENCY")
    print(f"   Features that affect 2+ metrics (|d| > 0.3 or |ρ| > 0.20)")
    print(f"{'=' * 80}")

    consistent = [(k, v) for k, v in feature_hits.items() if len(v) >= 2]
    consistent.sort(key=lambda x: len(x[1]), reverse=True)

    if consistent:
        for key, hits in consistent:
            avg_eff = sum(h[2] for h in hits) / len(hits)
            direction = "HELPS" if avg_eff > 0 else "HURTS"
            print(f"\n  {key} — {len(hits)} metrics, avg effect: {avg_eff:+.2f} ({direction})")
            for label, raw, eff in hits:
                print(f"    {label:<18s} d/ρ = {raw:+.3f}")
    else:
        print("\n  No features hit 2+ metrics at threshold.")

    # ── 6. Winners vs Losers feature profile ──
    print(f"\n{'=' * 80}")
    print("6. WINNERS vs LOSERS — Feature Profile")
    print(f"{'=' * 80}")

    if args.cpa_threshold is not None:
        # CPA-based fixed threshold
        winners = [s for s in has_perf if s.get('_cpa') is not None and s['_cpa'] <= args.cpa_threshold]
        losers = [s for s in has_perf
                  if (s.get('_cpa') is None and s.get('_spend', 0) >= args.min_loser_spend)
                  or (s.get('_cpa') is not None and s['_cpa'] > args.cpa_threshold)]
        print(f"\n  Winners (CPA ≤ ${args.cpa_threshold:.0f}): n={len(winners)}")
        print(f"  Losers  (CPA > ${args.cpa_threshold:.0f} or 0 conv w/ ${args.min_loser_spend:.0f}+ spend): n={len(losers)}")
    elif args.roas_threshold is not None:
        # ROAS-based fixed threshold (legacy)
        winners = [s for s in has_perf if s['_roas'] >= args.roas_threshold]
        losers = [s for s in has_perf if s['_roas'] < args.roas_threshold]
        print(f"\n  Winners (≥{args.roas_threshold}x ROAS): n={len(winners)}")
        print(f"  Losers  (<{args.roas_threshold}x ROAS): n={len(losers)}")
    else:
        # Percentile-based — rank by chosen metric
        rank_metric = args.rank_by  # 'roas' or 'cpa'
        if rank_metric == 'cpa':
            # Lower CPA is better; no-purchase ads get worst rank
            scored_ads = []
            for s in has_perf:
                cpa = s.get('_cpa')
                # Sortable key: real CPAs get their value; no-purchase ads get infinity
                sort_key = cpa if cpa is not None else float('inf')
                scored_ads.append((sort_key, s))
            scored_ads.sort(key=lambda x: x[0])  # ascending — best (lowest CPA) first
            ranked = [s for _, s in scored_ads]
        else:
            # ROAS — higher is better
            scored_ads = [(s['_roas'], s) for s in has_perf]
            scored_ads.sort(key=lambda x: -x[0])  # descending — best first
            ranked = [s for _, s in scored_ads]

        n = len(ranked)
        top_n = max(1, int(n * args.top_pct / 100))
        bottom_n = max(1, int(n * args.bottom_pct / 100))
        winners = ranked[:top_n]
        losers = ranked[-bottom_n:]

        # Threshold values for transparency
        if rank_metric == 'cpa':
            win_cutoff_cpa = winners[-1].get('_cpa')
            lose_cutoff_cpa = losers[0].get('_cpa')
            win_str = f"CPA ≤ ${win_cutoff_cpa:.0f}" if win_cutoff_cpa is not None else "CPA"
            lose_str = f"CPA ≥ ${lose_cutoff_cpa:.0f}" if lose_cutoff_cpa is not None else "no conv / worst CPA"
        else:
            win_cutoff = winners[-1]['_roas']
            lose_cutoff = losers[0]['_roas']
            win_str = f"ROAS ≥ {win_cutoff:.2f}x"
            lose_str = f"ROAS ≤ {lose_cutoff:.2f}x"

        print(f"\n  Ranked by: {rank_metric.upper()}")
        print(f"  Winners (top {args.top_pct:.0f}% — {win_str}): n={len(winners)}")
        print(f"  Losers  (bottom {args.bottom_pct:.0f}% — {lose_str}): n={len(losers)}")

    if len(winners) >= 3 and len(losers) >= 3:
        print(f"\n  {'Feature':<42s} {'Win %':>7} {'Loss %':>8} {'Δ':>6} {'d':>6}")
        print(f"  {'─'*72}")

        effects = []
        for key in binary_keys:
            w_pct = sum(1 for s in winners if s['_flat'].get(key) == 1) / len(winners) * 100
            l_pct = sum(1 for s in losers if s['_flat'].get(key) == 1) / len(losers) * 100
            delta = w_pct - l_pct
            w_vals = [s['_flat'].get(key, 0) for s in winners]
            l_vals = [s['_flat'].get(key, 0) for s in losers]
            d = _cohens_d(w_vals, l_vals)
            if d is not None and abs(delta) >= 10:
                effects.append((key, w_pct, l_pct, delta, d))

        effects.sort(key=lambda x: abs(x[4]), reverse=True)
        for key, w_pct, l_pct, delta, d in effects:
            print(f"  {key:<42s} {w_pct:>6.0f}% {l_pct:>7.0f}% {delta:>+5.0f} {d:>+5.2f}")

    # ── 7. Breakdown by awareness level ──
    # Get awareness classifications for all ads
    meta_ids = [s['meta_ad_id'] for s in has_perf]
    cls_result = supabase.table('ad_creative_classifications').select(
        'meta_ad_id, creative_awareness_level'
    ).in_('meta_ad_id', meta_ids).order('classified_at', desc=True).execute()

    aw_map = {}
    for row in cls_result.data:
        mid = row['meta_ad_id']
        if mid not in aw_map:
            aw_map[mid] = row['creative_awareness_level']

    for s in has_perf:
        s['_awareness'] = aw_map.get(s['meta_ad_id'], s.get('awareness', 'unknown'))

    awareness_levels = ['problem_aware', 'solution_aware', 'product_aware']
    awareness_groups = {level: [s for s in has_perf if s['_awareness'] == level] for level in awareness_levels}

    print(f"\n{'=' * 80}")
    print("7. FEATURE EFFECTS BY AWARENESS LEVEL (Cohen's d for ROAS)")
    print(f"   Positive d = feature present → higher ROAS")
    print(f"{'=' * 80}")

    # Header
    level_labels = []
    for level in awareness_levels:
        n = len(awareness_groups[level])
        if n >= 6:
            level_labels.append((level, n))

    if level_labels:
        header = f"  {'Feature':<42s} " + " ".join(f"{l[:12]:>12}({n})" for l, n in level_labels)
        print(f"\n{header}")
        print(f"  {'─'*42} " + " ".join("─" * 15 for _ in level_labels))

        for key in binary_keys:
            row_parts = [f"  {key:<42s}"]
            any_signal = False
            for level, n in level_labels:
                group = awareness_groups[level]
                present = [s['_roas'] for s in group if s['_flat'].get(key) == 1]
                absent = [s['_roas'] for s in group if s['_flat'].get(key) == 0]
                d = _cohens_d(present, absent)
                if d is None or len(present) < 2 or len(absent) < 2:
                    row_parts.append(f"{'---':>15}")
                else:
                    flag = "**" if abs(d) >= 0.5 else "* " if abs(d) >= 0.3 else "  "
                    row_parts.append(f"{d:>+12.2f}{flag} ")
                    if abs(d) >= 0.3:
                        any_signal = True
            if any_signal:
                print(" ".join(row_parts))

        # Numeric features
        for key in numeric_keys:
            row_parts = [f"  {key:<42s}"]
            any_signal = False
            for level, n in level_labels:
                group = awareness_groups[level]
                subset = [(s['_flat'][key], s['_roas']) for s in group if key in s['_flat']]
                if len(subset) < 5:
                    row_parts.append(f"{'---':>15}")
                    continue
                xs, ys = zip(*subset)
                sp = _spearman(list(xs), list(ys))
                if sp is None:
                    row_parts.append(f"{'---':>15}")
                else:
                    flag = "**" if abs(sp) >= 0.4 else "* " if abs(sp) >= 0.25 else "  "
                    row_parts.append(f"{sp:>+12.3f}{flag} ")
                    if abs(sp) >= 0.25:
                        any_signal = True
            if any_signal:
                print(" ".join(row_parts))

    # ── 7b. Winners vs Losers WITHIN each awareness level ──
    print(f"\n{'=' * 80}")
    print(f"7b. WINNERS vs LOSERS BY AWARENESS LEVEL (top {args.top_pct:.0f}% / bottom {args.bottom_pct:.0f}% by {args.rank_by.upper()})")
    print(f"{'=' * 80}")

    rank_metric = args.rank_by

    for level, n in level_labels:
        group = awareness_groups[level]
        if n < 8:  # need enough ads to split into percentiles
            print(f"\n  {level.upper()} (n={n}) — sample too small for percentile split")
            continue

        # Rank within this awareness level
        if rank_metric == 'cpa':
            scored_ads = [(s.get('_cpa') if s.get('_cpa') is not None else float('inf'), s) for s in group]
            scored_ads.sort(key=lambda x: x[0])
        else:
            scored_ads = [(s['_roas'], s) for s in group]
            scored_ads.sort(key=lambda x: -x[0])
        ranked = [s for _, s in scored_ads]

        top_n = max(2, int(n * args.top_pct / 100))
        bottom_n = max(2, int(n * args.bottom_pct / 100))
        # Ensure no overlap when sample is small
        if top_n + bottom_n > n:
            top_n = n // 2
            bottom_n = n - top_n
        winners = ranked[:top_n]
        losers = ranked[-bottom_n:]

        # Cutoff values
        if rank_metric == 'cpa':
            w_cut = winners[-1].get('_cpa')
            l_cut = losers[0].get('_cpa')
            win_str = f"CPA ≤ ${w_cut:.0f}" if w_cut is not None else "CPA"
            lose_str = f"CPA ≥ ${l_cut:.0f}" if l_cut is not None else "no conv"
        else:
            win_str = f"ROAS ≥ {winners[-1]['_roas']:.2f}x"
            lose_str = f"ROAS ≤ {losers[0]['_roas']:.2f}x"

        print(f"\n  {'─' * 72}")
        print(f"  {level.upper()} (n={n})")
        print(f"  Winners ({win_str}): n={len(winners)}  |  Losers ({lose_str}): n={len(losers)}")
        print(f"  {'─' * 72}")
        print(f"    {'Feature':<42s} {'Win %':>6} {'Loss %':>7} {'Δ':>6} {'d':>6}")
        print(f"    {'─'*68}")

        effects = []
        for key in binary_keys:
            w_pct = sum(1 for s in winners if s['_flat'].get(key) == 1) / len(winners) * 100
            l_pct = sum(1 for s in losers if s['_flat'].get(key) == 1) / len(losers) * 100
            delta = w_pct - l_pct
            w_vals = [s['_flat'].get(key, 0) for s in winners]
            l_vals = [s['_flat'].get(key, 0) for s in losers]
            d = _cohens_d(w_vals, l_vals)
            if d is not None and abs(delta) >= 15:
                effects.append((key, w_pct, l_pct, delta, d))

        effects.sort(key=lambda x: abs(x[4]), reverse=True)
        if effects:
            for key, w_pct, l_pct, delta, d in effects:
                print(f"    {key:<42s} {w_pct:>5.0f}% {l_pct:>6.0f}% {delta:>+5.0f} {d:>+5.2f}")
        else:
            print(f"    (no features with |Δ| >= 15%)")

    # ── 8. Categorical features by awareness level ──
    print(f"\n{'=' * 80}")
    print("8. CATEGORICAL FEATURES BY AWARENESS LEVEL (avg ROAS)")
    print(f"{'=' * 80}")

    for key in categorical_keys:
        has_data = False
        for level, n in level_labels:
            group = awareness_groups[level]
            by_cat = defaultdict(list)
            for s in group:
                val = s['_flat'].get(key)
                if val is not None:
                    by_cat[str(val)].append(s['_roas'])
            if len(by_cat) >= 2 and any(len(v) >= 2 for v in by_cat.values()):
                if not has_data:
                    print(f"\n  {key}:")
                    has_data = True
                print(f"    {level} (n={n}):")
                for val in sorted(by_cat.keys()):
                    vals = by_cat[val]
                    if vals:
                        print(f"      {val:<18s} n={len(vals):>2}  avg ROAS={sum(vals)/len(vals):>5.1f}x")

    # ── 9. Features that FLIP direction across awareness levels ──
    print(f"\n{'=' * 80}")
    print("9. FEATURES THAT FLIP ACROSS AWARENESS LEVELS")
    print(f"   (positive in one level, negative in another)")
    print(f"{'=' * 80}")

    flips = []
    for key in binary_keys:
        level_effects = {}
        for level, n in level_labels:
            group = awareness_groups[level]
            present = [s['_roas'] for s in group if s['_flat'].get(key) == 1]
            absent = [s['_roas'] for s in group if s['_flat'].get(key) == 0]
            d = _cohens_d(present, absent)
            if d is not None and len(present) >= 2 and len(absent) >= 2:
                level_effects[level] = d

        if len(level_effects) >= 2:
            signs = [v > 0 for v in level_effects.values()]
            if any(signs) and not all(signs):  # mixed signs
                max_d = max(abs(v) for v in level_effects.values())
                if max_d >= 0.3:
                    flips.append((key, level_effects))

    if flips:
        flips.sort(key=lambda x: max(abs(v) for v in x[1].values()), reverse=True)
        for key, effects in flips:
            parts = [f"{l}: d={d:+.2f}" for l, d in effects.items()]
            print(f"  {key:<42s}  {' | '.join(parts)}")
    else:
        print("  No features flip direction across awareness levels.")

    print(f"\n{'=' * 80}")
    print("DONE")
    print(f"{'=' * 80}")


# ── Main ──

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    score_parser = subparsers.add_parser('score', help='Score ads with PA classifier')
    score_parser.add_argument('brand', help='Brand name')
    score_parser.add_argument('--model', default='sonnet', choices=['sonnet', 'opus'])
    score_parser.add_argument('--all-awareness', action='store_true',
                              help='Score all awareness levels, not just product_aware')
    score_parser.add_argument('--min-spend', type=float, default=100,
                              help='Minimum spend for DB ad selection (default: 100)')
    score_parser.add_argument('--days', type=int, default=90,
                              help='Days back for DB ad selection (default: 90)')

    analyze_parser = subparsers.add_parser('analyze', help='Analyze PA features vs performance')
    analyze_parser.add_argument('brand', help='Brand name')
    analyze_parser.add_argument('--days', type=int, default=90)
    # Default: top/bottom 25% percentile, ranked by ROAS
    analyze_parser.add_argument('--rank-by', choices=['roas', 'cpa'], default='roas',
                                help='Metric to rank ads by for winners/losers (default: roas)')
    analyze_parser.add_argument('--top-pct', type=float, default=25.0,
                                help='Top percentile = winners (default: 25)')
    analyze_parser.add_argument('--bottom-pct', type=float, default=25.0,
                                help='Bottom percentile = losers (default: 25)')
    # Optional fixed-threshold overrides
    analyze_parser.add_argument('--cpa-threshold', type=float, default=None,
                                help='Override: CPA fixed threshold (e.g. 150 = CPA<=$150 wins)')
    analyze_parser.add_argument('--roas-threshold', type=float, default=None,
                                help='Override: ROAS fixed threshold (legacy)')
    analyze_parser.add_argument('--min-loser-spend', type=float, default=100.0,
                                help='Min spend for an ad with 0 conv to count as loser (default: 100)')

    args = parser.parse_args()

    if args.command == 'score':
        asyncio.run(cmd_score(args))
    elif args.command == 'analyze':
        cmd_analyze(args)


if __name__ == "__main__":
    main()
