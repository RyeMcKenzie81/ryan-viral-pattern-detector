# Ad Creator V2 — Intelligence System Guide

> **Branch**: `feat/ad-creator-v2-phase0`
> **Last Updated**: 2026-02-17

This document explains how the Ad Creator V2 learns and gets smarter over time, broken down by layer. The second half tells you exactly what you need to do to activate it.

---

## Table of Contents

1. [The Big Picture](#the-big-picture)
2. [Layer 1: Template Scoring (Instant)](#layer-1-template-scoring)
3. [Layer 2: Quality Calibration (Weekly)](#layer-2-quality-calibration)
4. [Layer 3: Creative Genome (Per Ad)](#layer-3-creative-genome)
5. [Layer 4: Scorer Weight Learning (Weekly)](#layer-4-scorer-weight-learning)
6. [Layer 5: Interaction Detection (Weekly)](#layer-5-interaction-detection)
7. [Layer 6: Whitespace Identification (Weekly)](#layer-6-whitespace-identification)
8. [Layer 7: Visual Style Clustering (Weekly)](#layer-7-visual-style-clustering)
9. [Layer 8: Generation Experiments (On Demand)](#layer-8-generation-experiments)
10. [Layer 9: Cross-Brand Transfer (Always On)](#layer-9-cross-brand-transfer)
11. [How to Use It: Step by Step](#how-to-use-it)
12. [Scheduled Jobs Required](#scheduled-jobs-required)
13. [Where to See Everything](#where-to-see-everything)
14. [What Data Each Layer Needs](#what-data-each-layer-needs)

---

## The Big Picture <a name="the-big-picture"></a>

The intelligence system is a feedback loop:

```
You create ads
  → System reviews them automatically (approve/reject)
  → You override some of those decisions
  → Ads go live on Meta, performance data comes back (CTR, conversions, ROAS)
  → Weekly jobs analyze all of this
  → Next time you create ads, the system uses what it learned
```

There are 9 layers, each learning something different. They all feed into each other. You don't need to understand the math — just know that the more ads you create and review, the smarter every layer gets.

---

## Layer 1: Template Scoring (Instant) <a name="layer-1-template-scoring"></a>

### What it does
When you use **Smart Select**, the system scores every template against 8 criteria to find the best ones for your brand and product.

### The 8 Scorers

| Scorer | What It Asks | Score Range |
|--------|-------------|-------------|
| **Asset Match** | "Do this product's images fit this template's layout?" | 0–1 |
| **Category Match** | "Is this template's category what we're looking for?" | 0–1 |
| **Awareness Align** | "Does this template match the customer's awareness stage?" | 0–1 |
| **Audience Match** | "Is this template designed for our target demographic?" | 0–1 |
| **Performance** | "How often have ads from this template been approved historically?" | 0–1 |
| **Belief Clarity** | "How well does this template convey belief-driven messaging?" | 0–1 |
| **Fatigue** | "Have we overused this template recently?" (penalizes repetition) | 0–1 |
| **Unused Bonus** | "Have we never tried this template?" (rewards exploration) | 0–1 |

Each scorer has a **weight** that controls how much it matters. Initially these are static defaults:

```
asset_match:      1.0  (most important)
unused_bonus:     0.8
category_match:   0.6
belief_clarity:   0.6
awareness_align:  0.5
audience_match:   0.4
fatigue:          0.4
performance:      0.3  (least important initially)
```

The system multiplies each score by its weight, adds them up, and picks the highest-scoring templates.

### How it learns
These weights aren't permanent. Layer 4 (Scorer Weight Learning) gradually adjusts them based on which scorers actually predict good ads for your brand. More on that below.

---

## Layer 2: Quality Calibration (Weekly) <a name="layer-2-quality-calibration"></a>

### What it does
The automated review system decides whether each generated ad passes or fails based on a 16-check rubric (9 visual checks + 5 content checks + 2 congruence checks). Sometimes it's wrong — it rejects a good ad or approves a bad one.

Quality Calibration watches your **overrides** (when you manually approve a rejected ad or reject an approved one) and proposes adjustments to the pass/fail thresholds.

### How it works in plain English

1. Every week, the system looks at your recent overrides
2. It calculates your **false positive rate** (ads it approved that you rejected) and **false negative rate** (ads it rejected that you approved)
3. If either rate is too high, it proposes a threshold change
4. You review the proposal in **Platform Settings > Calibration Proposals**
5. You activate it (applies the new threshold) or dismiss it (with a reason)

### Example
Say the system keeps rejecting ads with a congruence score of 0.58, but you keep overriding them to approved. The calibration system will propose lowering the congruence threshold from 0.60 to 0.55, so those borderline ads pass automatically next time.

### What makes it work
Your overrides. Without them, this layer has no signal. Even overriding 5-10 ads per week gives useful data.

---

## Layer 3: Creative Genome (Per Ad) <a name="layer-3-creative-genome"></a>

### What it does
Every ad you create gets tagged with **creative elements** — its hook type, color mode, template category, awareness stage, canvas size, and content source. The Creative Genome tracks how each element value performs over time using real Meta Ads data.

### How it works in plain English

1. You create ads → each gets element tags automatically
2. Ads go live on Meta
3. After enough time and impressions (maturation windows below), performance data is collected:
   - **CTR** — matures after 3 days + 500 impressions
   - **Conversion rate** — matures after 7 days + 500 impressions
   - **ROAS** — matures after 10 days + 500 impressions
4. Performance is normalized against your brand's historical baselines (25th and 75th percentiles)
5. A composite **reward score** (0–1) is computed, weighted by campaign objective:
   - Conversions campaign: 20% CTR + 50% Conv + 30% ROAS
   - Sales campaign: 20% CTR + 30% Conv + 50% ROAS
   - Traffic campaign: 60% CTR + 20% Conv + 20% ROAS
   - Awareness campaign: 70% CTR + 10% Conv + 20% ROAS
6. The reward is attributed to each element that was used in that ad
7. Each element value maintains a Beta distribution (α, β) — a fancy way of tracking "wins vs losses"

### What this enables
When you create the next batch of ads, the system knows:
- "quote_card templates have a 72% success rate for this brand"
- "complementary color mode outperforms original by 15%"
- "1080x1350 canvas performs better than 1080x1080 for this product"

This data feeds into Layers 5, 6, and 7 below.

---

## Layer 4: Scorer Weight Learning (Weekly) <a name="layer-4-scorer-weight-learning"></a>

### What it does
Remembers that Layer 1 has 8 scorers with fixed weights? This layer **learns the optimal weights** for your brand using Thompson Sampling.

### How it works in plain English

Every time Smart Select picks templates and you run ads, the system records:
- Which weights were used
- How each scorer scored each template
- Whether the resulting ads were good or bad (from Layer 3 rewards)

Then it figures out: "For this brand, the Asset Match scorer is really predictive of good ads, but the Audience Match scorer doesn't matter much." It adjusts the weights accordingly.

### The Three Phases

| Phase | Observations | What Happens |
|-------|-------------|--------------|
| **Cold** | 0–29 | Static weights only. System is still learning. |
| **Warm** | 30–99 | Blend of static and learned weights. Gradually trusting the data more. |
| **Hot** | 100+ | Fully learned weights. The system knows what works for your brand. |

"Observations" = the number of ads with both selection data AND performance rewards.

### Safety Rails
The system won't go wild:
- No scorer weight can drop below 0.1 (nothing gets zeroed out)
- No scorer weight can exceed 2.0
- Maximum change per weekly update: ±0.15 per scorer

### Where to see it
**Platform Settings > Scorer Weights tab** — shows each scorer's current phase, observations, static weight, learned weight, and effective weight.

---

## Layer 5: Interaction Detection (Weekly) <a name="layer-5-interaction-detection"></a>

### What it does
Discovers which creative element **pairs** work well together (synergies) and which ones hurt each other (conflicts).

### How it works in plain English

1. Looks at all matured ads with their element tags and reward scores
2. For every pair of elements (e.g., "quote_card template + complementary color"), checks:
   - What's the actual average reward when both elements appear together?
   - What would we *expect* the reward to be if they were independent?
3. If actual is significantly higher than expected → **synergy**
4. If actual is significantly lower than expected → **conflict**
5. Uses bootstrap confidence intervals (1000 iterations) to make sure the effect is real, not noise

### Example
- **Synergy**: "before_after templates + 1080x1350 canvas" → +12% lift. When these appear together, ads perform 12% better than you'd expect from each one alone.
- **Conflict**: "meme template + premium color mode" → -8% drag. These don't mix well.

### Requirements
- Minimum 10 ads with each element pair before computing an interaction
- Effect must be at least ±5% to be flagged
- Keeps top 15 interactions ranked by absolute effect size

### Where to see it
**Platform Settings > Interaction Effects tab** — shows synergies and conflicts per brand.

---

## Layer 6: Whitespace Identification (Weekly) <a name="layer-6-whitespace-identification"></a>

### What it does
Finds untested creative element combinations that **should** perform well based on what's known about each individual element.

### How it works in plain English

Think of it as "suggested experiments." The system says: "You've never tried a quote_card template with awareness stage 3, but quote_cards do well for you AND awareness stage 3 does well for you, so this combo might be worth trying."

Scoring formula:
```
predicted potential = average(score A, score B) + synergy bonus + novelty bonus
```

- **Synergy bonus**: If Layer 5 found a synergy between these elements, add it
- **Novelty bonus**: Extra credit for combos that haven't been tried at all (decays as usage increases)

### Filters
Only suggests combos where:
- Both individual elements score above 0.5 (both proven performers)
- Used fewer than 5 times (actually novel)
- No known conflict between them

### Where to see it
Currently surfaces as advisory context during ad generation. Will appear in Platform Settings in a future update.

---

## Layer 7: Visual Style Clustering (Weekly) <a name="layer-7-visual-style-clustering"></a>

### What it does
Groups your generated ads by visual similarity and tells you which visual styles perform best.

### How it works in plain English

1. Every ad gets a **visual embedding** — a numerical fingerprint of what it looks like (extracted by Gemini Flash, embedded by OpenAI)
2. DBSCAN clustering groups visually similar ads together
3. Each cluster gets labeled with its common visual traits (layout style, dominant colors, etc.)
4. Clusters are correlated with reward scores to see which visual styles win

### Example output
- Cluster 0 (15 ads): "Clean white background, centered product, bold headline" → avg reward 0.72
- Cluster 1 (8 ads): "Before/after split, warm tones, testimonial overlay" → avg reward 0.64
- Cluster 2 (12 ads): "Dark background, neon accents, UGC style" → avg reward 0.45

### Diversity Check
When generating new ads, the system checks: "Is this new ad too visually similar to an existing cluster?" If similarity > 90%, it flags a diversity warning so you don't keep producing the same visual style.

### Where to see it
**Platform Settings > Visual Clusters tab** — clusters ranked by performance.

---

## Layer 8: Generation Experiments (On Demand) <a name="layer-8-generation-experiments"></a>

### What it does
Lets you A/B test different generation strategies. Change one thing about the pipeline (prompt version, config, review rubric, or element strategy) and measure whether it actually improves results.

### How it works in plain English

1. You create an experiment with a **control config** (current approach) and **variant config** (new approach)
2. You activate the experiment
3. Every pipeline run gets deterministically assigned to control or variant (using SHA-256 hashing so retries get the same arm)
4. After enough ads (default: 20 per arm), you run analysis
5. The system uses a **Mann-Whitney U test** to compare approval rates between arms
6. If p-value < 0.05 → statistically significant winner. Otherwise → inconclusive.

### Example
Experiment: "Does adding 'ensure text is readable' to the review prompt improve approval rates?"
- Control: current review prompt
- Variant: review prompt + readability instruction
- Result after 50 ads per arm: variant has 68% approval vs control 52%, p=0.03 → variant wins

### Rules
- Max 1 active experiment per brand at a time
- Both arms run simultaneously (no before/after bias)
- 50/50 split by default (configurable)

### Where to set it up
**Platform Settings > Generation Experiments tab** — create, activate, analyze, conclude.

---

## Layer 9: Cross-Brand Transfer (Always On) <a name="layer-9-cross-brand-transfer"></a>

### What it does
Lets a new brand bootstrap from an established brand's performance data instead of starting from zero.

### How it works in plain English

If Brand A has 200+ ads with performance data, and you launch Brand B in the same organization:
1. Enable "Cross-brand transfer learning" on both brands in Brand Manager
2. Brand B gets Brand A's element scores as a starting point
3. The transfer is **weighted by brand similarity** — if both brands use similar creative elements, more data transfers. If they're very different, less transfers.
4. All transferred data is **shrunk by 70%** (multiplied by 0.3) so Brand B's own data quickly dominates

### What crosses the boundary
Only aggregate statistics (element score means, interaction effects). No raw ad images or copy cross brands.

### When to use it
- New brand in the same org as an established brand
- Brands targeting similar audiences or using similar visual styles
- When you want to skip the cold-start period

### When NOT to use it
- Brands in completely different categories (health vs tech)
- Brands with conflicting visual identities

### Where to enable it
**Brand Manager** (bottom of brand settings) — "Enable cross-brand transfer learning" toggle.

---

## How to Use It: Step by Step <a name="how-to-use-it"></a>

Here's exactly what you need to do to get the intelligence system working.

### Step 1: Verify Scheduled Jobs Exist

You need two scheduled jobs per brand. Check in Supabase or the Ad Scheduler page.

| Job | Schedule | Purpose |
|-----|----------|---------|
| `genome_validation` | Weekly (e.g., Sundays 4am) | Runs Layers 4-7: scorer weight learning, interaction detection, whitespace identification, visual clustering |
| `quality_calibration` | Weekly (e.g., Saturdays 3am) | Runs Layer 2: analyzes your overrides, proposes threshold adjustments |

If these don't exist for your brand, they need to be created. See [Scheduled Jobs Required](#scheduled-jobs-required) below.

### Step 2: Create Ads with Smart Select

Use **Smart Select** mode (not manual or roll the dice) for template selection. This is what generates the selection data that Layers 1 and 4 need.

Run at least 2-3 batches per week with 3-5 templates each.

### Step 3: Review and Override Ads

This is the **most important step**. After each batch:

1. Go to **View Results** tab
2. Look at every ad the system auto-reviewed
3. **Override Approve** any rejected ads that are actually good
4. **Override Reject** any approved ads that are actually bad
5. For exceptional ads, use **Mark as Exemplar** (gold approve, gold reject, or edge case)

**Target: Override at least 10-20 ads per week.** This is the primary signal for Layers 2, 3, 4, and 5.

### Step 4: Push Ads to Meta

For Layers 3, 5, 6, and 7 to work fully, approved ads need to go live on Meta so performance data (CTR, conversions, ROAS) can flow back. The maturation windows are:
- CTR: 3 days after launch + 500 impressions
- Conversion: 7 days + 500 impressions
- ROAS: 10 days + 500 impressions

### Step 5: Wait for Weekly Jobs

The genome_validation job runs once a week. After it runs, check:
- **Platform Settings > Scorer Weights** — are observations increasing?
- **Platform Settings > Interaction Effects** — any synergies/conflicts found?
- **Platform Settings > Visual Clusters** — any clusters forming?

### Step 6: Review Calibration Proposals

When the quality_calibration job finds that your overrides disagree with the automated thresholds:
1. Go to **Platform Settings > Calibration Proposals**
2. Review the proposed threshold change
3. Activate it or dismiss it with a reason

### Step 7: (Optional) Run Experiments

Once you have a baseline (50+ ads):
1. Go to **Platform Settings > Generation Experiments**
2. Create an experiment to test a hypothesis
3. Let it run until you have 20+ ads per arm
4. Run analysis and conclude

### Step 8: (Optional) Enable Cross-Brand Transfer

If launching a new brand:
1. Go to **Brand Manager** for the established brand → enable cross-brand sharing
2. Go to **Brand Manager** for the new brand → enable cross-brand sharing
3. The new brand immediately gets bootstrapped element scores

### Timeline to Expect

| Milestone | When | What Unlocks |
|-----------|------|-------------|
| First batch created | Day 1 | Layer 1 (template scoring with static weights) |
| 10+ overrides | Week 1-2 | Layer 2 starts proposing calibration changes |
| First ads live on Meta, 3+ days old | Week 1-2 | Layer 3 starts computing rewards |
| 30+ observations with rewards | Week 3-6 | Layer 4 enters warm phase (blended weights) |
| 50+ ads with element tags + rewards | Week 4-8 | Layer 5 starts finding interactions |
| Visual embeddings stored | After deploy | Layer 7 starts clustering |
| 100+ observations with rewards | Week 8-12 | Layer 4 enters hot phase (fully learned weights) |

---

## Scheduled Jobs Required <a name="scheduled-jobs-required"></a>

These need to exist in the `scheduled_jobs` table for each brand you want intelligence on.

### genome_validation

**What it runs**: Scorer weight learning, interaction detection, whitespace identification, visual clustering, and genome health validation.

**Recommended schedule**: Weekly, off-peak hours.

```sql
INSERT INTO scheduled_jobs (brand_id, product_id, job_type, parameters, cron_schedule, status)
VALUES (
  'YOUR_BRAND_ID',
  NULL,
  'genome_validation',
  '{}',
  '0 4 * * 0',  -- Sundays at 4am
  'active'
);
```

### quality_calibration

**What it runs**: Override analysis and threshold proposal generation.

**Recommended schedule**: Weekly, before genome_validation.

```sql
INSERT INTO scheduled_jobs (brand_id, product_id, job_type, parameters, cron_schedule, status)
VALUES (
  'YOUR_BRAND_ID',
  NULL,
  'quality_calibration',
  '{"window_days": 30}',
  '0 3 * * 6',  -- Saturdays at 3am
  'active'
);
```

### creative_genome_update (if not already set up)

**What it runs**: Fetches matured Meta Ads performance data, computes rewards, updates element scores.

**Recommended schedule**: Daily (performance data comes in continuously).

```sql
INSERT INTO scheduled_jobs (brand_id, product_id, job_type, parameters, cron_schedule, status)
VALUES (
  'YOUR_BRAND_ID',
  NULL,
  'creative_genome_update',
  '{}',
  '0 5 * * *',  -- Daily at 5am
  'active'
);
```

---

## Where to See Everything <a name="where-to-see-everything"></a>

| Layer | Where to Check | What You'll See |
|-------|---------------|----------------|
| Template Scoring | Ad Creator V2 > Smart Select > Preview | Per-template scores across all 8 scorers |
| Quality Calibration | Platform Settings > Calibration Proposals | Proposed threshold changes, false positive/negative rates |
| Creative Genome | (runs in background) | Feeds into all other layers |
| Scorer Weights | Platform Settings > Scorer Weights | Per-scorer phase, observations, static vs learned vs effective weight |
| Interactions | Platform Settings > Interaction Effects | Synergies and conflicts between element pairs |
| Whitespace | (advisory during generation) | Suggested untested combos |
| Visual Clusters | Platform Settings > Visual Clusters | Clusters ranked by avg reward, top visual descriptors |
| Experiments | Platform Settings > Generation Experiments | Active experiments, analysis results, winners |
| Cross-Brand | Brand Manager > toggle | Enable/disable per brand |

---

## What Data Each Layer Needs <a name="what-data-each-layer-needs"></a>

This is the dependency map — what each layer needs before it can produce useful output.

| Layer | Needs | Minimum Data |
|-------|-------|-------------|
| **1. Template Scoring** | Product images, templates | Works immediately |
| **2. Quality Calibration** | Your manual overrides | 5-10 overrides |
| **3. Creative Genome** | Ads live on Meta with performance data | 3+ days live, 500+ impressions per ad |
| **4. Scorer Weight Learning** | Selection snapshots + rewards (from Layer 3) | 30 observations for warm phase |
| **5. Interaction Detection** | Element tags + rewards (from Layer 3) | 10 ads per element pair |
| **6. Whitespace** | Element scores (from Layer 3) + interactions (from Layer 5) | Sufficient element scores |
| **7. Visual Clustering** | Visual embeddings (stored during review) | 3+ ads with embeddings |
| **8. Experiments** | Pipeline runs assigned to arms | 20 ads per arm |
| **9. Cross-Brand Transfer** | Another brand's data in same org | Any amount helps |

### The Bottom Line

The two things that make everything work:

1. **Create ads regularly** — at least 2-3 batches per week using Smart Select
2. **Override the review decisions** — approve good rejected ads, reject bad approved ads, at least 10-20 per week

Everything else is automated.
