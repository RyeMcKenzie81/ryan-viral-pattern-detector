# Ad Creator V2 — User Walkthrough

> **Branch**: `feat/ad-creator-v2-phase0`
> **Last Updated**: 2026-02-17

This guide walks through every user-facing feature of the Ad Creator V2 system — from creating your first ad to tuning the intelligence layer.

---

## Table of Contents

1. [Quick Start: Create Your First V2 Ad](#1-quick-start)
2. [Template Selection Modes](#2-template-selection)
3. [Generation Config](#3-generation-config)
4. [Reviewing Generated Ads](#4-reviewing-ads)
5. [Scheduling Automated Runs](#5-scheduling)
6. [Belief-First Ad Creation](#6-belief-first)
7. [Platform Settings (Intelligence Layer)](#7-platform-settings)
8. [Brand Manager (Cross-Brand Learning)](#8-brand-manager)
9. [How the System Learns](#9-how-it-learns)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Quick Start: Create Your First V2 Ad <a name="1-quick-start"></a>

**Page**: Ad Creator V2 (`/pages/21b`)

### Steps

1. **Select a brand** from the brand selector dropdown (top of page)
2. **Select a product** under that brand
3. **Pick a template selection mode** — start with **Smart Select** (recommended)
   - Set template count to 1-2 for your first run
4. **Configure generation**:
   - Content Source: `hooks` (uses existing persuasive hooks)
   - Variations per Template: 2-5
   - Image Resolution: 2K (default)
   - Canvas Size: 1080x1080px (1:1 Feed)
   - Color Mode: original
5. **Review the batch estimate** — shows total ads and estimated cost
6. **Click "Submit V2 Job"** — creates a background job picked up by the worker in ~1 minute
7. **Click "View Results"** to see ads as they complete

The pipeline takes ~3-5 minutes per template (Gemini image generation + Claude review).

---

## 2. Template Selection Modes <a name="2-template-selection"></a>

Templates are the visual blueprint your ad is generated from. V2 offers three selection modes:

### Manual Mode
Browse and hand-pick templates from a grid view.

**Filters available:**
- Category (testimonial, quote_card, before_after, product_showcase, ugc_style, meme, carousel_frame, story_format, other)
- Awareness Level
- Industry/Niche
- Target Audience (all, male, female, unisex)

Click templates to select/deselect them. Good for when you know exactly which style you want.

### Roll the Dice Mode
Weighted random selection — favors templates you haven't used recently.

**Controls:**
- Number of templates (1-10)
- Category filter

Click **Preview** to see what would be selected with composite scores. Good for creative exploration and avoiding repetition.

### Smart Select Mode (Recommended)
Scored best-fit templates using 8 intelligent scorers:

| Scorer | What It Measures |
|--------|-----------------|
| **Asset Match** | How well your product images fit the template layout |
| **Category Match** | Template category vs your ad goals |
| **Awareness Align** | Template awareness level vs audience stage |
| **Audience Match** | Template target demographic vs your product |
| **Performance** | Historical approval rate for this template |
| **Belief Clarity** | How well the template conveys belief messaging |
| **Fatigue** | Penalizes overused templates |
| **Unused Bonus** | Rewards templates never tried |

**Controls:**
- Number of templates (1-10)
- Category filter
- Asset Strictness: `default`, `growth` (lenient), `premium` (strict)

Click **Preview** to see templates ranked by composite score with per-scorer breakdowns. The system learns optimal scorer weights over time (see [How the System Learns](#9-how-it-learns)).

---

## 3. Generation Config <a name="3-generation-config"></a>

After selecting templates, configure how ads are generated:

### Content Source
What drives the ad copy:

| Source | When to Use |
|--------|-------------|
| **Hooks** | Default. Uses persuasive hooks from your hook database |
| **Recreate Template** | Varies by product benefits, less hook-dependent |
| **Belief First** | Angle-driven — uses a specific belief angle (see [Belief-First](#6-belief-first)) |
| **Plan** | Executes a belief plan with multiple angles + templates |
| **Angles** | Direct angle injection from approved angles |

### Output Controls

| Control | Options | Notes |
|---------|---------|-------|
| **Variations per Template** | 1-50 (default 5) | Each variation uses a different hook. Warning at >30. |
| **Image Resolution** | 1K, 2K, 4K | 2K is the sweet spot for quality vs speed |
| **Canvas Sizes** | 1080x1080, 1080x1350, 1080x1920, 1200x628 | Multi-select. Each size generates separately. |
| **Color Modes** | original, complementary, brand | Multi-select. Multiplies with canvas sizes. |
| **Persona** | (optional) | Override which persona the ad targets |
| **Additional Instructions** | (optional) | Free text passed to the LLM prompt |

### Batch Estimate

Before submitting, the system shows:
- Total templates x variations x (sizes x colors) = total attempts
- Estimated cost
- Guardrails: hard block at extreme counts, warning at >30 variations

---

## 4. Reviewing Generated Ads <a name="4-reviewing-ads"></a>

**Page**: Ad Creator V2 > View Results tab

After a job completes, you'll see a results grid with every generated ad.

### Per-Ad Information

Each ad card shows:
- **Status badge**: Approved, Rejected, Flagged, Review Failed, Generation Failed
- **Image preview**
- **Hook text** used to generate it
- **Congruence score** (0-1) — how well headline matches visual
- **Defect scan result** — Passed/Failed with specific defect list
- **15-check rubric scores** (expandable) — V1-V9 visual + C1-C4 content + G1-G2 congruence

### Override Controls

The automated review isn't always right. You can:
- **Override Approve** — force-approve a rejected ad (with optional reason)
- **Override Reject** — force-reject an approved ad (with optional reason)
- **Bulk Approve All / Reject All** — per template group

Overrides are the most important feedback signal. They train the quality calibration system and feed into scorer weight learning.

### Mark as Exemplar (Phase 8A)

For exceptional ads (very good or very bad), mark them as exemplars:
- **Gold Approve** — this ad is a great example of quality
- **Gold Reject** — this ad is a clear example of what to reject
- **Edge Case** — borderline ad useful for calibration

Exemplars are used by the review AI as reference points for future reviews. The system auto-seeds exemplars from your overrides, but manual marking is more precise.

---

## 5. Scheduling Automated Runs <a name="5-scheduling"></a>

**Page**: Ad Scheduler (`/pages/24`)

Schedule recurring V2 ad creation jobs instead of running manually.

### Setup

1. Select brand and product
2. Choose `ad_creation_v2` as the job type
3. Configure the same options as manual creation (content source, variations, sizes, colors)
4. Set a cron schedule (e.g., daily, weekly)
5. The scheduler worker picks up jobs and runs them automatically

### Content Source Options

Same as manual mode, plus:
- **Plan** mode — select a belief plan, runs angles in sequence
- **Angles** mode — select specific angles + persona + JTBD

### Limits

- Max 50 ads per scheduled run (configurable in Platform Settings)
- One active experiment per brand (A/B tests run alongside scheduled jobs)

---

## 6. Belief-First Ad Creation <a name="6-belief-first"></a>

Belief-first mode generates ads driven by research-backed belief angles rather than random hooks.

### The Belief Pipeline

```
Research → Candidates → Patterns → Angles → Plans → Ads
```

1. **Research Insights** (`/pages/32`): View belief angle candidates extracted from 5 sources:
   - Belief Reverse Engineer (pain signals, JTBDs)
   - Reddit Research (quotes, patterns)
   - Ad Performance (winning hooks)
   - Competitor Research (UMPs, angles)
   - Brand Research (customer voice)

2. **Pattern Discovery**: Clusters similar candidates using DBSCAN on embeddings. Recurring themes = strong beliefs.

3. **Promote to Angle**: Convert high-confidence candidates/patterns into formal belief angles with a JTBD frame.

4. **Ad Planning** (`/pages/23`): Create a belief plan pairing angles with templates.

5. **Generate**: Use `plan` or `angles` content source in Ad Creator V2.

### When to Use Belief-First

- When you have 10+ belief candidates with evidence
- When hooks feel repetitive and you want belief-driven messaging
- When you want to systematically test which beliefs convert best
- After running Belief Reverse Engineer or Reddit research

---

## 7. Platform Settings (Intelligence Layer) <a name="7-platform-settings"></a>

**Page**: Platform Settings (`/pages/64`)

This page has 8 tabs controlling the intelligence behind ad creation.

### Tab: AI Models
Configure which AI model to use for each service (generation, review, analysis).

### Tab: Backend Services
Model selection for competitor analysis, brand research, persona generation, etc.

### Tab: Content Pipelines
Model selection for comic generation, video scripts, copy scaffolding.

### Tab: Angle Pipeline
Configure the belief angle system:
- **Stale Threshold** (days) — when candidates without new evidence become stale
- **Evidence Decay Half-Life** (days) — how quickly evidence weight fades
- **Min Candidates for Pattern Discovery** — minimum before clustering runs
- **Max Ads Per Scheduled Run** — cap for scheduled jobs
- **Clustering Sensitivity (epsilon)** — tighter = more patterns, looser = fewer
- **Min Cluster Size** — minimum candidates to form a pattern

### Tab: Calibration Proposals (Phase 8A)
Weekly analysis of your overrides proposes quality threshold adjustments:
- View proposed changes to pass/fail thresholds
- See false positive/negative rates from recent overrides
- **Activate** to apply the new threshold
- **Dismiss** with a reason to reject
- View proposal history

### Tab: Interaction Effects (Phase 8A)
Shows pairwise element interactions discovered from creative performance:
- **Synergies** — element combos that boost approval rates
- **Conflicts** — element combos that hurt performance
- Select a brand to see its discovered interactions
- Data populates after genome_validation runs with sufficient reward data

### Tab: Exemplar Library (Phase 8A)
Manage the reference ad library per brand:
- View all exemplars with their categories (gold_approve, gold_reject, edge_case)
- See visual descriptors and similarity scores
- Remove exemplars that are no longer relevant
- Auto-seed runs when a brand gets its first overrides

### Tab: Scorer Weights (Phase 8B)
Monitor how the 8 template scorers are performing:
- **Per-scorer table**: alpha, beta, observations, learning phase, effective weight
- **Phase summary**: cold (0-29 obs), warm (30-99), hot (100+)
- In cold phase, static weights are used
- In warm phase, a blend of static and learned weights
- In hot phase, fully learned weights from Thompson Sampling

### Tab: Generation Experiments (Phase 8B)
A/B test different generation strategies:
1. **Create** an experiment — pick a name, hypothesis, type (prompt_version, pipeline_config, review_rubric, element_strategy), control/variant configs, split ratio
2. **Activate** — starts routing pipeline runs to control/variant arms
3. **Run Analysis** — Mann-Whitney U test on ad approval rates
4. **Conclude** — declares winner (control, variant, or inconclusive) with p-value

Only 1 active experiment per brand. Arms are assigned deterministically via SHA-256 so retries get the same arm.

### Tab: Visual Clusters (Phase 8B)
DBSCAN clustering of ad visual embeddings per brand:
- Shows clusters ranked by average reward score
- Identifies which visual styles perform best/worst
- Provides diversity check — alerts when new ads are too similar to existing clusters
- Data populates after visual embeddings are stored and genome_validation runs

---

## 8. Brand Manager (Cross-Brand Learning) <a name="8-brand-manager"></a>

**Page**: Brand Manager (`/pages/02`)

### Cross-Brand Knowledge Sharing (Phase 8B)

At the bottom of the brand settings section, there's a toggle:

**Enable cross-brand transfer learning**

When enabled for a brand:
- Statistical performance data (element scores, interaction effects) is shared with other brands in the same organization
- New brands can bootstrap from existing brand data instead of starting cold
- Only aggregate statistics cross boundaries — no raw ad data is shared
- Transfer is weighted by brand similarity (cosine similarity of element score vectors) and shrunk by 0.3x

**When to enable:**
- When launching a new brand in the same organization
- When brands target similar audiences or use similar visual styles
- When you want faster learning for a brand with few ads

**When NOT to enable:**
- Brands in completely different categories
- Brands with conflicting visual identities

---

## 9. How the System Learns <a name="9-how-it-learns"></a>

The V2 system has a multi-layered learning loop:

### Layer 1: Quality Calibration (Weekly)
Your overrides (approve/reject) are analyzed weekly. If the automated review is consistently wrong, the system proposes threshold adjustments. You review and activate them in Platform Settings > Calibration Proposals.

### Layer 2: Creative Genome (Per Ad)
Every generated ad is tagged with creative elements (layout, color, copy style, etc.). Over time, the system tracks which element combinations perform well and uses this to inform template selection.

### Layer 3: Scorer Weight Learning (Weekly via genome_validation)
The 8 template scorers start with static weights. As data accumulates:
- **Cold phase (0-29 observations)**: Static weights only
- **Warm phase (30-99)**: Linear blend of static and learned weights
- **Hot phase (100+)**: Fully learned via Thompson Sampling

This means the system automatically discovers which scoring criteria matter most for your brand.

### Layer 4: Interaction Detection (Weekly via genome_validation)
After enough ads with element tags and rewards, the system discovers pairwise synergies and conflicts between creative elements. These are surfaced as advisories during ad generation.

### Layer 5: Whitespace Identification (Weekly via genome_validation)
Identifies untested element combinations that have high predicted potential — suggesting creative directions you haven't explored yet.

### Layer 6: Visual Style Clustering (Weekly via genome_validation)
Clusters your ads by visual similarity using DBSCAN on visual embeddings. Identifies which visual styles correlate with higher approval rates.

### Data Flow Summary

```
You create ads  →  Automated review (approve/reject)
                →  You override some decisions
                →  Rewards computed from outcomes
                →  Weekly genome_validation job runs:
                     1. Scorer weight posteriors updated (Thompson Sampling)
                     2. Element interactions detected (pairwise effects)
                     3. Whitespace candidates identified (untested combos)
                     4. Visual style clusters updated (DBSCAN)
                →  Next ad creation uses learned weights + advisories
```

The more ads you create and review, the smarter the system gets.

---

## 10. Troubleshooting <a name="10-troubleshooting"></a>

### Job stuck at "running"
If the worker was interrupted (deploy, crash), a job can get stuck. Check:
1. Logfire (`viraltracker-scheduler-worker` service) for the trace
2. If the worker process died, the job will be retried on restart (up to 3 attempts)

### All ads rejected
Common causes:
- Template doesn't match product well (try different templates or Smart Select)
- Image assets are low quality (check Brand Manager > product images)
- Review thresholds too strict (check Platform Settings > Calibration Proposals)

### No learned weights showing
Scorer weight learning requires:
1. Ads with element tags (V2 pipeline does this automatically)
2. Reward data from human overrides (you need to approve/reject ads)
3. genome_validation job to run (weekly, Sundays 4am)

Until you have 30+ overridden ads, the system stays in cold phase with static weights.

### Empty interaction/whitespace/cluster data
These all depend on having `creative_element_rewards` — which are computed from your ad overrides. Start overriding ads (approve good ones, reject bad ones) and the data will populate after the next genome_validation run.

### Visual embeddings not stored
Fixed in commit `477e9cb`. Redeploy the worker and run a V2 pipeline — embeddings will be stored during the review phase for each generated ad.
