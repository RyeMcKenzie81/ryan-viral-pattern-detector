# Fix 10: Template Ingestion/Scoring — Impression-Based Prioritization

## Status: PLANNED (Not Started)

## Problem Statement

Meta Ad Library now sorts search results by impressions (highest first). Our template scraping pipeline treats all scraped ads equally — an ad at position 1 (massive impressions) gets the same priority as position 50 (low impressions). We should leverage Meta's built-in ranking to prioritize testing high-performing competitor ads.

Additionally, Meta groups duplicate creatives under "X ads use this creative and text" but Apify expands them into individual ads, flooding our template queue with near-identical items.

---

## Empirical Validation (2026-03-06)

Ran two test scrapes against Mars Men (page 184711951390377) sorted by total impressions desc. Key findings:

### Finding 1: Sort Order IS Preserved

Meta's top 5 ads appeared in Apify results at positions 1, 3, 7, 8, 9 — **same relative sequence**. The extra positions in between are creative group variants that Meta collapses but Apify expands.

| Meta Position | Library ID | Apify Position |
|:---:|---|:---:|
| 1 | 781349091042059 | 1 |
| 2 | 1588888479412913 | 3 |
| 3 | 915180691079968 | 7 |
| 4 | 859639866698624 | 8 |
| 5 | 1374786513851936 | 9 |

### Finding 2: Apify Provides `position`, `collation_id`, `collation_count`, and `total` Natively

No need to infer position from array index. Apify returns:

| Field | Example | Meaning |
|-------|---------|---------|
| `position` | `1` | Explicit position in results (1-based) |
| `collation_id` | `"1068767681759850"` | Groups ads sharing same creative |
| `collation_count` | `2` or `0`/`null` | Lead ad has the count; variants have 0/null |
| `total` | `87` | Total ads matching the search |
| `ads_count` | `2` | Same as collation_count (alias) |

### Finding 3: Impression Numbers Are Null for US Commercial Ads

All 20 ads returned `impressions_with_index: {"impressions_text": null, "impressions_index": -1}` and `spend: null`. This confirms position (not impression numbers) must be the primary signal.

### Finding 4: Collation Groups Link Duplicate Creatives

4 collation groups found in 20 results:

| Collation ID | Positions | Count |
|---|---|---|
| 1068767681759850 | #1, #2 | 2 (Meta shows "2 ads use this creative") |
| 1494379175444931 | #3, #4, #5, #6 | 7 (Meta shows "7 ads" — we got 4 of 7) |
| 1986932398545238 | #9, #10 | 2 |
| 1935979336952417 | #16, #17 | 3 (we got 2 of 3) |

Creative comparison of group 1068767681759850: **identical image URLs and body text** between members. These are true duplicates (same creative, different ad IDs — likely different targeting or A/B test splits).

### Finding 5: Start Dates Reveal Velocity

The data shows a critical insight about ad age vs position:

| Position | Library ID | Start Date | Age |
|:---:|---|---|---|
| 1 | 781349091042059 | 2025-08-22 | ~6 months |
| 3 | 1588888479412913 | 2026-02-23 | ~2 weeks |
| 7 | 915180691079968 | 2026-01-15 | ~2 months |

Ad #3 started only 2 weeks ago but already has the 2nd-highest total impressions on the page. This implies massive current daily spend — this is the "hottest" ad to replicate. Ad #1 is a steady workhorse but may have accumulated impressions slowly over 6 months.

---

## Current State Analysis

### What We Already Capture (Underutilized)

| Field | Location | Type | Current Usage |
|-------|----------|------|---------------|
| `impressions` | `facebook_ads` | TEXT | Stored raw from Apify's `impressions_with_index` — often null for US ads. **Silently dropped** when dict: `if isinstance(imp_value, dict): pass` |
| `reach_estimate` | `facebook_ads` | TEXT | Stored but rarely used |
| `spend` | `facebook_ads` | TEXT | Stored but rarely used |
| `start_date` + `last_seen_at` | `facebook_ads` | TIMESTAMPTZ | Used by `LONGEVITY` recommendation methodology. **Not used for velocity calculation.** |
| `times_seen` | `facebook_ads` | INT | Dedup tracking only |
| `collation_id` | `facebook_ads` | TEXT | **Already stored** (scraper captures it) but never used for dedup |
| `collation_count` | `facebook_ads` | INT | **Already stored** but never used |

### What We DON'T Capture

| Signal | Why It Matters |
|--------|---------------|
| **Apify `position` field** | Explicit position in results. Not currently passed through to `save_facebook_ad_with_tracking()` |
| **Apify `total` field** | Total ads in results. Needed to normalize position (position 3 of 5 vs position 3 of 500) |
| **Parsed impression bounds** | Even when impression data exists (EU/political ads), we silently discard it |
| **Collation-based dedup** | Template queue gets flooded with duplicate creatives from the same collation group |
| **Impression velocity** | New ad at high position = massive current spend. `position / age` is the strongest "hot right now" signal |

### Pipeline Flow (Where Changes Enter)

```
Apify returns ads with: position, total, collation_id, collation_count, start_date
    → FacebookAdsScraper._normalize_ads()
        → collation_id, collation_count stored on facebook_ads  ← ALREADY WORKS
        → position, total fields exist but NOT mapped             ← FIX
        → impressions_with_index stored raw as TEXT               ← FIX (parse)
    → execute_template_scrape_job() loops over all ads
        → save_facebook_ad_with_tracking()  ← add position, total
        → template_queue.add_to_queue()     ← add collation dedup
            → scraped_templates             ← no priority signal  ← FIX (Phase 2)
```

### Existing Scoring Infrastructure

The `template_scoring_service.py` has a pluggable scorer architecture with 8 scorers and weighted presets. Adding new scorers fits naturally.

Current sort options in Ad Creator V2: `["most_used", "least_used", "newest", "oldest"]` with a source brand dropdown filter (Fix 6). Adding impression-based sort extends this naturally.

---

## The Velocity Concept

Meta sorts by **total lifetime impressions**. This means:

```
Total Impressions ≈ Daily Spend Rate × Days Active
```

Therefore:

```
Implied Daily Spend ≈ Total Impressions / Days Active
           ≈ Position Rank / Days Active
```

A new ad at a high position is **spending aggressively right now**. An old ad at a high position may have accumulated impressions slowly. Both are interesting, but for different reasons:

| Scenario | Position | Age | What it means | Template value |
|----------|:---:|---|---|---|
| Hot new winner | #2 | 1 week | Massive current spend | **Highest** — replicate now before competitors catch on |
| Scaling fast | #5 | 2 weeks | Rapidly climbing | **Very high** — proven and being scaled |
| Steady workhorse | #1 | 6 months | Consistent spend over time | **High** — proven long-term performer |
| Slow accumulator | #3 | 1 year | Low daily spend, high total | **Medium** — works but may be stale creative |
| New and low | #40 | 1 week | Low spend, testing phase | **Low** — unproven |
| Old and low | #40 | 6 months | Failed or niche | **Lowest** — likely underperformer |

### Velocity Scoring Formula

```python
# Position score: 0.0 (worst) to 1.0 (best)
position_percentile = 1.0 - (position - 1) / max(total - 1, 1)

# Recency factor: exponential decay with ~30-day half-life
# 1 day old → 0.98, 7 days → 0.85, 30 days → 0.50, 365 days → 0.0002
recency_factor = 2 ** (-days_active / 30)

# Velocity = position quality × (base + recency bonus)
# The 0.4/0.6 split means:
#   - 40% of score comes from pure position (always matters)
#   - 60% is boosted by recency (newer = more credit for same position)
velocity_score = position_percentile * (0.4 + 0.6 * recency_factor)
```

| Ad | Position (of 87) | Age | position_percentile | recency_factor | velocity_score |
|---|:---:|---|---|---|---|
| Hot new #2 | 2 | 7 days | 0.99 | 0.85 | **0.90** |
| Scaling #5 | 5 | 14 days | 0.95 | 0.72 | **0.79** |
| Steady #1 | 1 | 180 days | 1.00 | 0.02 | **0.41** |
| Slow #3 | 3 | 365 days | 0.98 | 0.0002 | **0.39** |
| New low #40 | 40 | 7 days | 0.55 | 0.85 | **0.47** |
| Old low #40 | 40 | 180 days | 0.55 | 0.02 | **0.23** |

The hot new ad at #2 (0.90) scores more than double the steady workhorse at #1 (0.41). This correctly captures that current spend velocity is the strongest signal for "which creative to replicate."

---

## Adversarial Analysis

### RESOLVED: Apify Order Preservation
- **Previously a risk** — now empirically validated. Order IS preserved. Apify expands creative groups inline but maintains Meta's impression-based sort.

### Risk 1: Collation Groups May Contain Different Sizes/Aspect Ratios

- **Scenario**: Meta groups a 1080x1080 and a 1080x1350 version of the same creative under one `collation_id`. If we dedup to just the lead ad, we lose the alternate size.
- **Likelihood**: Medium. Advertisers commonly run the same creative in multiple aspect ratios.
- **Evidence**: In our test, group 1068767681759850 had identical image URLs. But larger campaigns may have size variants.
- **Mitigation (Phase 1 — MVP)**: Keep only the lead ad (collation_count > 0). Accept occasional loss of size variants. This is simple and handles the common case.
- **Mitigation (Phase 1 — Enhanced, if time permits)**: Compare `snapshot.cards[0].original_image_url` between collation members. If URLs differ → different creatives/sizes → queue both. If identical → true duplicate → skip variant.
- **Task mapping**: Task 1.3 (collation dedup logic)

### Risk 2: Meta Changes Sort Algorithm or Removes Impression Sorting

- **Scenario**: Meta changes Ad Library to sort by date or relevance instead of impressions.
- **Likelihood**: Medium. Meta iterates their UI regularly.
- **Mitigation**: Position scorer weight is configurable — zero it out without code changes. `collation_count` is an independent signal that survives sort changes. Longevity scoring (already implemented) provides redundancy. Velocity scorer degrades gracefully (still useful for recency even if position is noisy).
- **Monitor**: Track whether position correlates with `times_seen` and longevity. If correlation breaks, reduce weights.
- **Task mapping**: Task 2.4 (configurable weights)

### Risk 3: Impression Data Missing for Most Commercial US Ads

- **Scenario**: `impression_lower`/`impression_upper` are null for nearly all scrapes.
- **Likelihood**: CONFIRMED (all 20 test ads had null).
- **Mitigation**: Position and velocity are the primary signals. Impression bounds are a bonus for EU/political ads if we ever scrape those. The impression parser (Task 1.2) is low-cost to build and ready for when data becomes available.
- **Task mapping**: Task 1.2 (build the parser anyway — low cost, future-proofing)

### Risk 4: Position Is Inflated by Creative Group Expansion

- **Scenario**: Meta shows 5 unique creatives at positions 1-5. Apify expands groups into 20 individual ads at positions 1-20. Position 7 sounds mediocre but is actually Meta's #3.
- **Mitigation**: Compute `deduped_position` counting only lead ads (collation_count > 0). In our test data: Apify position 7 → deduped position 3. Store both raw and deduped.
- **Task mapping**: Task 1.4 (compute deduped_position)

### Risk 5: Partial Collation Groups Across Scrape Batches

- **Scenario**: Group has 7 members but we only get 4 due to `count` limit.
- **Impact**: Low. We have the lead ad. Missing variants just mean fewer duplicates.
- **Mitigation**: None needed — partial groups handled naturally by dedup logic.
- **Task mapping**: N/A (natural handling)

### Risk 6: `collation_count` Field Unreliable or Missing

- **Scenario**: Apify changes reporting, or field is null for some ads.
- **Likelihood**: Low. Field was present on all 20 test ads.
- **Mitigation**: Defensive code — if `collation_id` is null or `collation_count` is missing, treat as singleton (no dedup). Never skip ads that lack collation data.
- **Task mapping**: Task 1.3 (defensive dedup logic)

### Risk 7: Same Creative, Different Targeting — Loss of Ad Intelligence

- **Scenario**: Two collation members target different audiences. Dedup loses targeting diversity insight.
- **Impact**: Low for template purposes — we only care about visual creative, not targeting.
- **Mitigation**: All ads still saved to `facebook_ads` table. Only template_queue dedup affected. Full ad data remains queryable for future intelligence features.
- **Task mapping**: Task 1.3 (dedup at queue level, not facebook_ads level)

### Risk 8: `position` Field Missing or Resets at Pagination Boundaries

- **Scenario**: Apify doesn't always include `position`, or it resets to 1 on each page of results.
- **Likelihood**: Low (confirmed present in test), but pagination behavior unknown for large scrapes.
- **Mitigation**: Fall back to array index if `position` is null. Log a warning when fallback triggers so we detect the issue. For large scrapes crossing pagination boundaries, track whether position values are monotonically increasing — if they reset, use cumulative array index instead.
- **Task mapping**: Task 1.3 (position extraction with fallback)

### Risk 9: Different Scrape Jobs Return Different Positions for Same Ad

- **Scenario**: Daily scrape has ad X at position 5, weekly scrape has it at position 12 because competition changed.
- **Impact**: Which position do we trust for scoring?
- **Mitigation**: Track `best_scrape_position = min(existing, new)` (peak performance) and `latest_scrape_position` (current state). Use best for the ImpressionRankScorer (captures peak quality). Use latest + start_date for the VelocityScorer (captures current momentum).
- **Task mapping**: Task 1.3 (dual position tracking)

### Risk 10: Position Meaningless for Small Pages

- **Scenario**: Page has only 5 active ads. Positions 1-5 are trivially assigned.
- **Impact**: All 5 get high position scores despite no competitive ranking.
- **Mitigation**: Use `total` field from Apify. When `total <= 10`, compress ImpressionRankScorer output to [0.4, 0.6] range (near-neutral). VelocityScorer naturally handles this: `position_percentile` still differentiates within a small set, and the recency factor provides the real signal.
- **Task mapping**: Task 2.1 (ImpressionRankScorer normalization), Task 2.2 (VelocityScorer uses total for percentile)

### Risk 11: Template Queue Already Has Duplicates from Past Scrapes

- **Scenario**: Collation dedup is forward-looking. Existing queue has duplicate creatives from before this fix.
- **Impact**: Low — existing clutter persists but doesn't grow.
- **Mitigation**: One-time cleanup query in backfill script: identify template_queue items sharing a `collation_id` (via scraped_ad_assets → facebook_ads join) and archive the variants.
- **Task mapping**: Task 1.5 (backfill & cleanup)

### Risk 12: Velocity Formula Overweights Very New Ads

- **Scenario**: An ad is 1 day old at position 10. The recency factor gives it a high velocity score, but it might just be a test ad that happened to get early spend. Tomorrow it could be paused.
- **Impact**: We prioritize a flash-in-the-pan over a proven performer.
- **Mitigation**: The velocity scorer is one signal among 10+. The existing UnusedBonusScorer, PerformanceScorer, and FatigueScorer provide counterbalancing signals. Additionally, a 1-day-old ad won't yet have a template approved and available — by the time it's through the queue, more data points will exist. We can also add a minimum age threshold (e.g., ignore velocity for ads < 3 days old) if this proves noisy.
- **Task mapping**: Task 2.2 (optional min_age_days parameter on VelocityScorer)

### Risk 13: `start_date` Is Wrong or Missing

- **Scenario**: Apify returns null or incorrect start_date. Velocity calculation breaks.
- **Likelihood**: Low — start_date was present on all 20 test ads.
- **Mitigation**: VelocityScorer returns neutral 0.5 when start_date is null. When days_active computes to 0 (same-day), treat as 1 day to avoid division issues. The `start_date` field comes from Meta's own records so should be reliable.
- **Task mapping**: Task 2.2 (null handling in scorer)

### Failure Mode Summary

| # | Failure Mode | Severity | Phase | Task |
|---|-------------|----------|-------|------|
| 1 | Size variants deduped incorrectly | Medium | 1 | 1.3 — MVP: keep lead only |
| 2 | Meta changes sort algorithm | Medium | 2 | 2.4 — configurable weights |
| 3 | US ads lack impression numbers | Confirmed | 1 | 1.2 — parser built anyway (low cost) |
| 4 | Position inflated by group expansion | Medium | 1 | 1.4 — compute deduped_position |
| 5 | Partial collation groups | Low | 1 | Natural handling |
| 6 | collation_count unreliable | Low | 1 | 1.3 — defensive singleton fallback |
| 7 | Lose targeting diversity | Low | 1 | 1.3 — dedup at queue, not DB |
| 8 | `position` missing / resets | Low | 1 | 1.3 — fallback to array index |
| 9 | Position differs across jobs | Medium | 1 | 1.3 — track best + latest |
| 10 | Small pages make position meaningless | Medium | 2 | 2.1, 2.2 — normalize by total |
| 11 | Existing queue has duplicates | Low | 1 | 1.5 — one-time cleanup |
| 12 | Velocity overweights very new ads | Medium | 2 | 2.2 — optional min_age, balanced by other scorers |
| 13 | start_date wrong or missing | Low | 2 | 2.2 — null → neutral score |

---

## Phased Plan

### Phase 1 (MVP): Capture Position + Collation Dedup

**Goal**: Stop importing duplicate creatives. Start capturing position and age data for scoring.

#### Task 1.1: DB Migration — Position & Tracking Columns
**Complexity**: Low
**File**: `migrations/2026-03-07_impression_position_tracking.sql`

Add to `facebook_ads`:
```sql
-- Position tracking
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS best_scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS latest_scrape_position INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS scrape_total INT;

-- Parsed impression data (for EU/political ads when available)
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_lower INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_upper INT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS impression_text TEXT;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_facebook_ads_best_position
    ON facebook_ads(best_scrape_position) WHERE best_scrape_position IS NOT NULL;

-- Comments
COMMENT ON COLUMN facebook_ads.scrape_position IS
    'Raw Apify position field from most recent scrape (inflated by creative group expansion)';
COMMENT ON COLUMN facebook_ads.best_scrape_position IS
    'Best (lowest) deduped creative position ever seen — the primary scoring signal';
COMMENT ON COLUMN facebook_ads.latest_scrape_position IS
    'Most recent deduped creative position — used with start_date for velocity';
COMMENT ON COLUMN facebook_ads.scrape_total IS
    'Total ads in search results at time of scrape — for position normalization';
```

Note: `collation_id` (TEXT) and `collation_count` (INT) **already exist** on `facebook_ads` — no migration needed for those.

#### Task 1.2: Parse `impressions_with_index` Properly
**Complexity**: Low
**Files**: `viraltracker/services/ad_scraping_service.py`, `viraltracker/services/facebook_service.py`

New helper in `ad_scraping_service.py`:
```python
def parse_impression_data(raw_value) -> tuple[int | None, int | None, str | None]:
    """Parse Apify's impressions_with_index into (lower, upper, display_text).

    Handles:
    - dict: {"impressions_text": "1K-5K", "impressions_index": 3} → (1000, 5000, "1K-5K")
    - int/float: 12345 → (12345, 12345, "12345")
    - None or {"impressions_text": null}: → (None, None, None)
    """
```

Fix `FacebookService` to use the new parser instead of `if isinstance(imp_value, dict): pass`.

Covers **Risk 3**: parser is cheap to build and ready when EU/political data is available.

#### Task 1.3: Pass Position + Collation Through Scrape Pipeline
**Complexity**: Medium
**Files**: `viraltracker/worker/scheduler_worker.py`, `viraltracker/services/ad_scraping_service.py`

**Changes to `save_facebook_ad_with_tracking()`**:
- Accept new optional params: `scrape_position: int | None`, `scrape_total: int | None`
- Store `scrape_position` (raw Apify position)
- Store `scrape_total` from Apify's `total` field
- Update `best_scrape_position = min(existing, new)` when new deduped position available
- Update `latest_scrape_position` = new deduped position
- Parse and store impression data using Task 1.2 helper
- **Backward compatibility**: all new params optional with default None. Existing callers unaffected.

**Position extraction with fallback** (Risk 8):
```python
# Prefer Apify's native position field
raw_position = getattr(ad, 'position', None) or (index + 1)
if raw_position is None:
    logger.warning(f"No position field for ad {ad.ad_archive_id}, using array index")
    raw_position = index + 1
```

**Collation dedup before queuing** (Risks 1, 6, 7):
```python
# Track which collation_ids we've already queued in this batch
queued_collation_ids = set()

for ad in ads:
    collation_id = ad_dict.get("collation_id")
    collation_count = ad_dict.get("collation_count")

    # Save ALL ads to facebook_ads (preserve complete data — Risk 7)
    result = scraping_service.save_facebook_ad_with_tracking(...)

    # Dedup at queue level only
    if is_new and auto_queue:
        is_lead = (collation_count is not None and collation_count > 0) or collation_id is None
        is_duplicate = collation_id and collation_id in queued_collation_ids

        if is_lead or not is_duplicate:
            # Queue this ad (it's a lead or a singleton)
            await queue_service.add_to_queue(...)
            if collation_id:
                queued_collation_ids.add(collation_id)
            queued_count += 1
        else:
            # Skip — variant of an already-queued creative
            deduped_count += 1

# Risk 6: If collation_id is None, treat as singleton — always queue
```

Log dedup stats: `"Deduped {deduped_count} variant ads across {len(queued_collation_ids)} collation groups"`

**Dual position tracking** (Risk 9): `best_scrape_position` uses minimum; `latest_scrape_position` always updates.

#### Task 1.4: Compute `deduped_position`
**Complexity**: Low
**File**: `viraltracker/worker/scheduler_worker.py`

Raw Apify position is inflated by creative group expansion (Risk 4). Compute the effective creative ranking:

```python
# Before the main loop, compute deduped positions for lead ads
deduped_pos = 0
deduped_positions = {}  # ad_archive_id → deduped_position

for ad in ads:
    collation_id = get_collation_id(ad)
    collation_count = get_collation_count(ad)
    is_lead = (collation_count is not None and collation_count > 0) or collation_id is None

    if is_lead:
        deduped_pos += 1
        deduped_positions[ad.ad_archive_id] = deduped_pos
    # Variants get their group lead's deduped position
    elif collation_id:
        # Find the lead's position (already computed)
        for prev_ad_id, prev_pos in deduped_positions.items():
            # Assign same position — won't be queued anyway
            pass

# Pass deduped_positions[ad.ad_archive_id] as the position to save_facebook_ad_with_tracking()
```

Store deduped position as `best_scrape_position` / `latest_scrape_position`. Store raw position as `scrape_position`.

#### Task 1.5: Backfill & Cleanup
**Complexity**: Low
**Files**: `scripts/backfill_impression_data.py`

One-time script:
1. Parse existing `impressions` TEXT column → `impression_lower`, `impression_upper`, `impression_text`
2. **Existing queue dedup** (Risk 11): Query template_queue items, join to facebook_ads to get collation_id, identify groups where multiple items share a collation_id, archive all but the earliest (most likely the lead).

```sql
-- Find duplicate queue items sharing a collation_id
WITH ranked AS (
    SELECT tq.id, fa.collation_id,
           ROW_NUMBER() OVER (PARTITION BY fa.collation_id ORDER BY tq.created_at) as rn
    FROM template_queue tq
    JOIN scraped_ad_assets saa ON saa.id = tq.asset_id
    JOIN facebook_ads fa ON fa.id = saa.facebook_ad_id
    WHERE fa.collation_id IS NOT NULL
      AND tq.status = 'pending'
)
UPDATE template_queue SET status = 'archived'
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
```

#### Phase 1 Deliverables
- [ ] Migration deployed (new columns exist)
- [ ] Impression parsing helper tested with known formats
- [ ] Worker passes position, does collation dedup, computes deduped_position
- [ ] Backfill script run (impression parsing + queue dedup)
- [ ] `python3 -m py_compile` passes for all changed files
- [ ] Run a real template scrape: verify fewer queue items (~40-60% reduction), position data populated
- [ ] Verify manual uploads still queue normally (no collation data = singleton)
- [ ] Re-scrape same page: verify `best_scrape_position` takes minimum

**Estimated scope**: ~250 lines of code changes, 1 migration, 1 script

---

### Phase 2: Scoring Integration + UI Filters

**Goal**: Use position, velocity, and variant data in template selection. Add impression-based sorting/filtering to Ad Creator V2.

#### Task 2.1: Add `ImpressionRankScorer`
**Complexity**: Medium
**File**: `viraltracker/services/template_scoring_service.py`

Pure position-based scoring — how high does this ad rank by total impressions?

```python
class ImpressionRankScorer(BaseScorer):
    """Score by impression-based position rank.

    Lower position = higher total impressions = higher score.
    Normalizes by total results; mutes for small pages (Risk 10).
    Score range: [0.2, 1.0] with neutral 0.5 for missing data.
    """
    name = "impression_rank"

    def score(self, candidate: Dict, context: SelectionContext) -> float:
        best_pos = candidate.get("best_scrape_position")
        total = candidate.get("scrape_total")
        if best_pos is None:
            return 0.5  # Neutral for manual uploads / old data

        # Risk 10: Mute signal for small result sets
        if total and total <= 10:
            normalized = 1.0 - (best_pos - 1) / max(total - 1, 1)
            return 0.4 + normalized * 0.2  # Compress to [0.4, 0.6]

        # Normal: position 1 → 1.0, position 50+ → 0.2
        return max(0.2, 1.0 - (best_pos - 1) * 0.016)
```

**Data access**: Join `facebook_ads` in `fetch_template_candidates()`:
```python
query = supabase.table("scraped_templates").select(
    "*, facebook_ads:source_facebook_ad_id("
    "best_scrape_position, latest_scrape_position, scrape_total, "
    "start_date, collation_count, impression_lower, impression_upper)"
)
```
Flatten joined fields in Python before passing to scorers.

#### Task 2.2: Add `ImpressionVelocityScorer`
**Complexity**: Medium
**File**: `viraltracker/services/template_scoring_service.py`

The key insight: a NEW ad at a high position implies massive current spend. This is the strongest "hot right now" signal.

```python
class ImpressionVelocityScorer(BaseScorer):
    """Score by implied current spend velocity (position relative to age).

    Meta sorts by total lifetime impressions. A new ad near the top must be
    spending aggressively NOW to accumulate that many impressions so quickly.

    Formula:
        position_percentile = 1.0 - (position - 1) / max(total - 1, 1)
        recency_factor = 2^(-days_active / 30)   # 30-day half-life
        velocity = position_percentile * (0.4 + 0.6 * recency_factor)

    Examples (total=87):
        7-day-old ad at #2:   0.99 * (0.4 + 0.6*0.85) = 0.90  (hot!)
        180-day-old ad at #1: 1.00 * (0.4 + 0.6*0.02) = 0.41  (steady)
        7-day-old ad at #40:  0.55 * (0.4 + 0.6*0.85) = 0.47  (mediocre)
    """
    name = "impression_velocity"

    def score(self, candidate: Dict, context: SelectionContext) -> float:
        position = candidate.get("latest_scrape_position")  # Use latest, not best
        total = candidate.get("scrape_total")
        start_date = candidate.get("start_date")

        # Risk 13: null handling
        if position is None or start_date is None:
            return 0.5

        # Calculate days active
        from datetime import datetime, timezone
        if isinstance(start_date, str):
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                return 0.5
        else:
            start_dt = start_date

        now = datetime.now(timezone.utc)
        days_active = max((now - start_dt).days, 1)  # Floor at 1 day

        # Risk 12: Optional minimum age to avoid flash-in-the-pan noise
        # (can be tuned without code changes via subclass or config)

        # Position percentile (0.0 worst, 1.0 best)
        if total and total > 1:
            position_percentile = 1.0 - (position - 1) / (total - 1)
        else:
            position_percentile = 1.0 if position == 1 else 0.5

        # Recency factor: 30-day half-life exponential decay
        recency_factor = 2 ** (-days_active / 30)

        # Velocity: 40% from pure position, 60% boosted by recency
        return position_percentile * (0.4 + 0.6 * recency_factor)
```

#### Task 2.3: Add `CreativeVariantScorer`
**Complexity**: Low
**File**: `viraltracker/services/template_scoring_service.py`

`collation_count` is an independent signal: more variants = more advertiser investment = stronger creative. This signal survives sort order changes (Risk 2).

```python
class CreativeVariantScorer(BaseScorer):
    """Score by number of creative variants (collation_count).

    More variants = advertiser investing more in testing this creative.
    """
    name = "creative_variants"

    def score(self, candidate: Dict, context: SelectionContext) -> float:
        count = candidate.get("collation_count") or 1
        if count <= 1:
            return 0.3
        elif count <= 3:
            return 0.6
        elif count <= 7:
            return 0.8
        return 1.0  # 8+ variants
```

#### Task 2.4: Update Weight Presets
**Complexity**: Trivial
**File**: `viraltracker/services/template_scoring_service.py`

```python
ROLL_THE_DICE_WEIGHTS = {
    ...,  # existing 8 scorers
    "impression_rank": 0.0,       # Random mode ignores these
    "impression_velocity": 0.0,
    "creative_variants": 0.0,
}

SMART_SELECT_WEIGHTS = {
    ...,  # existing 8 scorers
    "impression_rank": 0.4,       # Total impression position
    "impression_velocity": 0.6,   # Highest weight — hot-right-now signal
    "creative_variants": 0.3,     # Bonus for heavily-tested creatives
}
```

Velocity gets the highest weight of the three because it captures the most actionable signal ("this ad is hot RIGHT NOW"). Rank gets moderate weight (position is useful but doesn't distinguish steady vs hot). Variants gets low weight (supporting signal).

All weights configurable — can be tuned per brand via `template_selection_config` JSONB on brands table (already exists from P0-4 migration).

#### Task 2.5: Ad Creator V2 — Impression Rank Sort + Brand Filter Enhancement
**Complexity**: Medium
**Files**: `viraltracker/services/template_queue_service.py`, `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py`

**New sort options** (extend existing `["most_used", "least_used", "newest", "oldest"]`):
- `"highest_rank"` — Sort by `best_scrape_position` ASC (best first)
- `"hottest"` — Sort by velocity (position / age formula, computed in Python)

**Implementation for `highest_rank`**:
Denormalize `best_scrape_position` onto `scraped_templates` (set during template approval from the source facebook_ad). This allows direct SQL sorting.

```python
# In template_queue_service.py get_templates():
elif sort_by == "highest_rank":
    query = query.order("best_scrape_position", desc=False, nullslast=True)
```

**Implementation for `hottest`**:
Can't compute velocity in SQL easily (needs `now() - start_date` and exponential). Two options:
- **Option A**: Fetch all, sort in Python. Fine for ~100-200 templates.
- **Option B**: Create a materialized view / SQL function. Overkill for MVP.

Use Option A for MVP. The `get_templates()` method already returns all matching templates; sort the list in Python by velocity before returning.

**Brand filter + impression rank** — already works naturally:
```
Source Brand: "Mars Men" + Sort By: "Highest Rank"
→ Shows Mars Men templates ordered by their impression rank
```
This is the "list by highest impressions within a brand" feature — it's just a combination of the existing brand dropdown + the new sort option. No special logic needed.

**UI update** (line 353 of Ad Creator V2):
```python
sort_options = ["most_used", "least_used", "newest", "oldest", "highest_rank", "hottest"]
```

#### Task 2.6: Surface Position/Velocity Data in Template Queue UI
**Complexity**: Medium
**File**: `viraltracker/ui/pages/28_📋_Template_Queue.py`

**Approved template library** — add badges alongside existing ones (industry, awareness, target):
- **Rank badge**: `"#3"` (from `best_scrape_position`) — green if top 10, yellow if top 25, gray otherwise
- **Velocity indicator**: `"Hot"` / `"Warm"` / blank — based on velocity score thresholds
- **Variant badge**: `"7 variants"` (from `collation_count`, only if > 1)

**Pending review queue** — show rank and velocity to help reviewers prioritize:
- Items at high positions should visually stand out
- "Hot: position #2, started 7 days ago" caption helps reviewers prioritize

#### Task 2.7: Show Scores in Scored Selection UI
**Complexity**: Trivial
**File**: `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py`

The scored selection view currently shows 6 metrics. Add the new ones:
```python
st.metric("Rank", f"{scores.get('impression_rank', 0):.2f}")
st.metric("Velocity", f"{scores.get('impression_velocity', 0):.2f}")
st.metric("Variants", f"{scores.get('creative_variants', 0):.2f}")
```

May need to adjust the metrics grid from 6 columns to accommodate 9 total (or use two rows).

#### Phase 2 Deliverables
- [ ] `ImpressionRankScorer`, `ImpressionVelocityScorer`, `CreativeVariantScorer` added
- [ ] Weight presets updated with all 3 new scorers
- [ ] `fetch_template_candidates()` joins facebook_ads for position/date/collation data
- [ ] Ad Creator V2: "Highest Rank" and "Hottest" sort options work
- [ ] Ad Creator V2: Brand + sort combination works ("Mars Men" + "Highest Rank")
- [ ] Template Queue: rank/velocity/variant badges visible
- [ ] Scored selection: 3 new metrics displayed
- [ ] All files compile-checked
- [ ] Test: 7-day-old ad at position 2 scores higher velocity than 180-day-old ad at position 1

**Estimated scope**: ~350 lines of code changes across 5 files

---

### Phase 3 (Deferred): Position History & Trend Tracking

**Goal**: Track how positions change over time. Identify rising/falling ads.

#### Task 3.1: Position History Table
```sql
CREATE TABLE IF NOT EXISTS facebook_ad_position_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facebook_ad_id UUID NOT NULL REFERENCES facebook_ads(id) ON DELETE CASCADE,
    scrape_run_id UUID REFERENCES scheduled_job_runs(id),
    raw_position INT NOT NULL,
    deduped_position INT,
    scrape_total INT,
    is_active BOOLEAN DEFAULT TRUE,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(facebook_ad_id, scrape_run_id)
);

CREATE INDEX ON facebook_ad_position_history(facebook_ad_id, scraped_at DESC);
```

#### Task 3.2: Trend Indicators in UI
Show trend arrows: rising (position improving over last 3 scrapes), falling, stable.

#### Task 3.3: History Compaction
Compact entries older than 30 days to weekly averages. Cap at 100 entries per ad.

**Phase 3 only built if Phase 1-2 prove valuable.**

---

## Files Affected Summary

### Phase 1
| File | Change Type | Scope |
|------|------------|-------|
| `migrations/2026-03-07_impression_position_tracking.sql` | NEW | ~30 lines |
| `viraltracker/services/ad_scraping_service.py` | MODIFY | `parse_impression_data()` helper, position params on `save_facebook_ad_with_tracking()` |
| `viraltracker/worker/scheduler_worker.py` | MODIFY | Position extraction, collation dedup, deduped_position computation |
| `viraltracker/services/facebook_service.py` | MODIFY | Use impression parser instead of dropping dicts |
| `scripts/backfill_impression_data.py` | NEW | One-time impression backfill + queue dedup cleanup |

### Phase 2
| File | Change Type | Scope |
|------|------------|-------|
| `viraltracker/services/template_scoring_service.py` | MODIFY | 3 new scorers, updated presets, facebook_ads join in fetch |
| `viraltracker/services/template_queue_service.py` | MODIFY | 2 new sort options, denormalize position on approval |
| `viraltracker/ui/pages/28_📋_Template_Queue.py` | MODIFY | Rank/velocity/variant badges |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | MODIFY | 2 sort options, 3 score metrics |

---

## Validation Steps

### After Phase 1
- [ ] Template scrape job: collation dedup reduced queue items (~40-60% reduction)
- [ ] `best_scrape_position` and `latest_scrape_position` populated on facebook_ads
- [ ] `scrape_total` populated
- [ ] Collation lead ads (count > 0) queued; variants (count == 0) skipped
- [ ] Deduped positions are sequential (1, 2, 3...) counting only leads
- [ ] Manual upload: no collation data → treated as singleton → queued normally
- [ ] Small page scrape: `scrape_total` correctly captured
- [ ] Re-scrape same page: `best_scrape_position` takes minimum of existing and new

### After Phase 2
- [ ] Smart Select: 7-day-old #2 ad scores higher velocity (~0.90) than 180-day-old #1 (~0.41)
- [ ] Smart Select: templates with collation_count=7 score higher creative_variants than count=1
- [ ] Small page (total <= 10): impression_rank compressed to [0.4, 0.6]
- [ ] Manual uploads: all 3 new scorers return neutral/low scores (not 0.0)
- [ ] "Highest Rank" sort: templates ordered by position (lowest first)
- [ ] "Hottest" sort: recent high-position ads first
- [ ] "Mars Men" + "Highest Rank": shows only Mars Men templates, by rank
- [ ] Template Queue badges: position, velocity label, variant count visible

---

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Order validation | CONFIRMED | Empirically tested 2026-03-06. Relative order preserved. |
| Position source | Apify's native `position` field with array index fallback | Explicit > inferred. Fallback covers Risk 8. |
| Dedup layer | `template_queue` only, not `facebook_ads` | Preserve complete ad data for intelligence (Risk 7). |
| Dedup strategy | Keep collation lead (count > 0), skip variants | Lead represents the group. MVP: don't compare images. |
| Primary scoring signal | `ImpressionVelocityScorer` (weight 0.6) | New ad at high position = hot right now. Strongest actionable signal. |
| Secondary scoring signal | `ImpressionRankScorer` (weight 0.4) | Pure position captures total lifetime quality. |
| Tertiary signal | `CreativeVariantScorer` (weight 0.3) | Independent of sort order (Risk 2). More variants = more investment. |
| Velocity formula | `pos_percentile * (0.4 + 0.6 * 2^(-days/30))` | 30-day half-life balances recency vs position. 40/60 split ensures position always matters. |
| Small page handling | Compress rank score to [0.4, 0.6] when total <= 10 | Position 1 of 5 is less meaningful than 1 of 87 (Risk 10). |
| Store both positions | `best_scrape_position` + `latest_scrape_position` | Best = peak quality. Latest + start_date = velocity input. |
| Store `scrape_total` | On `facebook_ads` | Needed for percentile normalization and small-page detection. |
| "Hottest" sort | Compute in Python, not SQL | Velocity formula uses exponential — simpler in Python. Fine for ~200 templates. |
| New sort in Ad Creator V2 | "Highest Rank" + "Hottest" added to existing dropdown | Natural extension of existing brand filter + sort pattern (Fix 6). |
| Weight configurability | Via existing `brands.template_selection_config` JSONB | Per-brand tuning already supported by P0-4 migration. |
