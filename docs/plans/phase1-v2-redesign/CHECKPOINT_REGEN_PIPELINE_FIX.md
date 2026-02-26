# Checkpoint: Regen Pipeline Fix — No Truncation, Batched Regen, Quality Gates

**Date**: 2026-02-25
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Planning → Implementation
**Depends on**: `CHECKPOINT_BLUEPRINT_LENGTH_SPECS.md`

## Problem

The slot rewrite pipeline has three compounding bugs that produce broken copy:

### Bug 1: Regen Batching Failure
When 50+ over-length slots are sent to the regen AI in a single call, structured output validation fails (`Exceeded maximum retries (2) for output validation`). ALL 50 slots fall through to dumb truncation.

### Bug 2: Dumb Truncation Produces Nonsense
The truncation fallback cuts at word boundaries then hunts backward for punctuation. This creates:
- **Truncated headlines**: "7 Reasons Women Over 45 Are Finally" (mid-sentence nonsense)
- No awareness of slot type (headlines need different treatment than body text)
- No semantic understanding (cuts can reverse meaning)

### Bug 3: No Content Quality Validation
The AI can hallucinate content not in the source material:
- "Shop Our Story Podcast Login Cart" appeared as a headline — pure hallucination of nav text
- No gate catches this before it reaches the final output

## Root Cause Analysis (from 4-agent expert panel)

| Agent | Key Finding |
|-------|-------------|
| Copywriter | "Condense" prompt produces telegram-quality output; regen should be "rewrite tighter" not "cut words" |
| UX Expert | Truncation tolerance should vary by slot type; headlines need 100% semantic completeness |
| Developer | Regen sends ALL violations in 1 call; needs batching into ~12 slots/batch with section affinity |
| QA Agent | No validation for nav junk, incomplete sentences, or hallucinated content |

## User Direction (CRITICAL)

> "I actually don't think we should ever truncate, there isn't many situations where truncating is going to work. I think we should just take what was written (provided it is good) and tell it to rewrite it with less words while maintaining persuasiveness and context"

**Translation**: Remove truncation entirely. Always regen (rewrite shorter). If regen fails, fall back to the original text rather than destroying copy with truncation.

## Implementation Plan

### Change 1: Batch Regen into Small Groups (12 slots/batch, section affinity)
- Split violations into batches of ~12 slots, keeping same-section slots together
- Each batch gets its own regen AI call (same pattern as initial write batching)
- Increases MAX_REGEN_ROUNDS from 2 to 3 (more rounds, smaller batches = higher success)

### Change 2: Improve Regen Prompts
- **Blueprint mode**: Already good ("rewrite tighter, not condense") — keep as-is
- **Runtime mode**: Replace "condense" framing with "rewrite tighter" language matching blueprint
- Add `slot_type` awareness: "headlines must be complete thoughts", "body can lose setup language"

### Change 3: Add Content Quality Gates
- **Nav junk detection**: Flag slots whose text looks like navigation (pattern: consecutive capitalized 1-2 word phrases)
- **Incomplete sentence detection**: Flag headline/subheadline slots that end mid-sentence
- Quality gates run after each AI call and flag violations for regen

### Change 4: Remove Truncation, Replace with Regen-Only + Original Fallback
- Delete the truncation fallback block entirely (lines 2449-2472)
- After all regen rounds, any remaining over-length slots get their ORIGINAL text (from `slot_contents`)
- Log these as "kept original" rather than "truncated"

### Change 5: Improve Blueprint Addendum Prompt
- Current "Overshooting by a few words is a minor issue" encourages overshooting (74% first-pass compliance)
- Add sentence-count planning: "Plan your sentence count before writing"
- Rebalance to "Aim for 90-95% of target range"

## Files to Modify

| File | Changes |
|------|---------|
| `mockup_service.py` | Batched regen, remove truncation, quality gates, prompt improvements |

## Verification

```bash
# Syntax check
python3 -m py_compile viraltracker/services/landing_page_analysis/mockup_service.py

# Unit tests
python3 -m pytest tests/ -k mockup -x --ignore=tests/test_chainlit_app.py

# Live test on Boba (section_guided strategy)
PYTHONPATH=. python3 scripts/test_slot_pipeline_martin.py --ab
```
