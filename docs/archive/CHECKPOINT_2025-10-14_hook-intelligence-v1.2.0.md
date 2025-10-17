# ViralTracker - Hook Intelligence Upgrade v1.2.0 (IN PROGRESS)
**Date:** 2025-10-14
**Session Status:** 50% Complete - Paused for context window refresh

## 🎯 Project Goal

Upgrade ViralTracker's hook analysis from simple scoring to **Hook Intelligence v1.2.0**, which:
1. **Identifies hook types** (multi-label taxonomy of 14 hook strategies)
2. **Attributes modality** (which channel drives attention: audio, visual, or overlay)
3. **Extracts catalysts** (specific visual/audio/overlay elements that grab attention)
4. **Measures windowed performance** (0-1s, 0-2s, 0-3s, 0-5s metrics)
5. **Detects risk flags** (content moderation risks)
6. **Scores adaptively** (blends content quality + pace, adjusts for hook length)

## ✅ Completed (50%)

### 1. Python Video Analyzer (vid-1.2.0) ✅ COMPLETE

**Files Modified:**
- `viraltracker/analysis/video_analyzer.py`

**Changes:**
1. **Line 71**: Version bumped to `vid-1.2.0`
2. **Lines 330-396**: Added Hook Intelligence v1.2.0 fields to Gemini prompt:
   - `hook_type_probs` (14 hook types with probabilities)
   - `hook_modality_attribution` (audio/visual/overlay attribution)
   - `hook_visual_catalysts` (face, hands, motion, color, etc.)
   - `hook_audio_catalysts` (questions, callouts, numbers, prosody, beat sync)
   - `hook_overlay_catalysts` (text metrics in first 2 seconds)
   - `hook_risk_flags` (suggestive, violence, minors, medical, brand risks)
   - `hook_span` (t_start, t_end timestamps)
   - `payoff_time_sec` (when promised value is delivered)
   - `hook_windows` (w1_0_1s, w2_0_2s, w3_0_3s, w4_0_5s_or_hook_end)
   - `hook_modifiers` (stakes_clarity, curiosity_gap, specificity)

3. **Lines 552-558**: Extract hook intelligence from Gemini response
4. **Line 577**: Store in `video_analysis.hook_features` JSONB column

**Status:** ✅ Ready for testing with Gemini 2.5 Pro

### 2. TypeScript Scorer Schema ✅ COMPLETE

**Files Modified:**
- `scorer/src/schema.ts`

**Changes:**
1. **Lines 88-141**: Added `HookContentSchema` with full Zod validation:
   - All hook intelligence fields from Python prompt
   - Proper type constraints (0-1 for scores, booleans, enums)
   - Optional fields with nullable support

2. **Line 152**: Added `hook_content: HookContentSchema` to `MeasuresSchema`

**Status:** ✅ Schema ready for formulas

## 🔄 Remaining (50%)

### 3. TypeScript Scorer Formulas (NOT STARTED)

**File:** `scorer/src/formulas.ts`

**Required Changes:**

#### A. Add `scoreHookContent()` function
```typescript
export function scoreHookContent(hc: any): number | null {
  if (!hc || !hc.hook_type_probs) return null;
  const p = (k: string, w = 1) => clamp((hc.hook_type_probs?.[k] ?? 0) * w, 0, 1);

  // Motifs (weights sum ≈ 0.7)
  const motifs =
      0.12*p("result_first")     + 0.10*p("reveal_transform")
    + 0.10*p("open_question")    + 0.08*p("direct_callout")
    + 0.08*p("challenge_stakes") + 0.07*p("contradiction_mythbust")
    + 0.06*p("humor_gag")        + 0.05*p("demo_novelty")
    + 0.05*p("relatable_slice")  + 0.05*p("tension_wait")
    + 0.05*p("social_proof")     + 0.04*p("authority_flex")
    + 0.05*p("shock_violation");

  // Modifiers (~0.2)
  const m = hc.modifiers ?? {};
  const mods = 0.08*clamp(m.stakes_clarity ?? 0,0,1)
             + 0.07*clamp(m.curiosity_gap ?? 0,0,1)
             + 0.05*clamp(m.specificity ?? 0,0,1);

  // Modality (~0.1)
  const att = hc.hook_modality_attribution ?? {};
  const modality = 0.04*clamp(att.audio ?? 0,0,1)
                 + 0.05*clamp(att.visual ?? 0,0,1)
                 + 0.01*clamp(att.overlay ?? 0,0,1);

  let s = 100 * (motifs + mods + modality);

  // Overlay readability & risk nudges
  const ov = hc.hook_overlay_catalysts ?? {};
  if ((ov.overlay_chars_per_sec_2s ?? 0) > 140) s -= 5;
  if ((ov.overlay_contrast_score ?? 1) < 0.6)   s -= 4;
  const risk = hc.hook_risk_flags ?? {};
  if (risk.suggestive_visual_risk === true) s -= 3;

  return clamp(s, 0, 100);
}
```

#### B. Add `scoreHookAdaptive()` function (replaces `scoreHook`)
```typescript
function windowScore(w:any): number {
  if (!w) return 0;
  const face   = clamp((w.face_pct ?? 0), 0, 1);
  const cuts   = clamp((w.cuts ?? 0)/3, 0, 1);
  const motion = clamp((w.motion_intensity ?? 0), 0, 1);
  const words  = clamp((w.words_per_sec ?? 0)/5, 0, 1);
  const ovChar = w.overlay_chars_per_sec ?? 0;
  const overlayOK = ovChar <= 140 ? 1 : clamp(1 - (ovChar-140)/120, 0, 1);
  const ma = w.modality_attribution ?? {};
  const modality = clamp(0.5*(ma.visual ?? 0) + 0.4*(ma.audio ?? 0) + 0.1*(ma.overlay ?? 0), 0, 1);
  const s = 0.30*face + 0.22*cuts + 0.18*motion + 0.18*words + 0.07*overlayOK + 0.05*modality;
  return clamp(s*100, 0, 100);
}

export function scoreHookAdaptive(h:any, hc:any): number | null {
  if (!h && !hc) return null;
  const hw = hc?.hook_windows ?? {};
  const s1 = windowScore(hw.w1_0_1s);
  const s2 = windowScore(hw.w2_0_2s);
  const s3 = windowScore(hw.w3_0_3s);
  const s4 = windowScore(hw.w4_0_5s_or_hook_end);

  let w1 = 0.55, w2 = 0.30, w3 = 0.10, w4 = 0.05;
  const hookEnd = hc?.hook_span?.t_end ?? 2.0;
  if (hookEnd <= 2.2) { const sum = w1+w2; w1/=sum; w2/=sum; w3=0; w4=0; }

  const payoff = hc?.payoff_time_sec ?? h?.time_to_value_sec ?? null;
  if (payoff != null && payoff <= 0.8) { w1 += 0.05; w2 -= 0.05; }

  const stakes = hc?.modifiers?.stakes_clarity ?? 0;
  let ttvPenalty = 0;
  if (payoff != null) {
    const x = Math.max(0, payoff - 1.0);
    const sig = 1/(1+Math.exp(2.2*x));
    const base = (1 - sig)*25;
    ttvPenalty = - base * (1 - 0.5*stakes);
  }

  const anyWin = (hw.w1_0_1s || hw.w2_0_2s || hw.w3_0_3s || hw.w4_0_5s_or_hook_end);
  if (!anyWin) {
    // Legacy fallback
    const ttv = h?.time_to_value_sec;
    const face = h?.first_frame_face_present_pct != null ? h.first_frame_face_present_pct/100 : null;
    const motion = h?.first_2s_motion_intensity ?? null;
    if (ttv==null && face==null && motion==null) return null;
    let s = 0;
    if (ttv!=null){ const x=Math.max(0, ttv-1.0); const sig=1/(1+Math.exp(2.2*x)); s += sig*50; }
    if (face!=null)   s += clamp(face*25, 0, 25);
    if (motion!=null) s += clamp(motion*25, 0, 25);
    return clamp(s, 0, 100);
  }

  const sBlend = w1*s1 + w2*s2 + w3*s3 + w4*s4;
  return clamp(sBlend + ttvPenalty, 0, 100);
}
```

### 4. TypeScript Scorer Integration (NOT STARTED)

**File:** `scorer/src/scorer.ts`

**Required Changes:**

1. **Import new functions:**
```typescript
import {
  scoreHook,  // Remove this
  scoreHookAdaptive,  // Add this
  scoreHookContent,   // Add this
  // ... rest
} from './formulas.js';
```

2. **Update computeSubscores (around line 142):**
```typescript
// OLD:
const subscores: any = {
  hook: scoreHook(validated.measures.hook),
  // ...
};

// NEW:
const hookPace = scoreHookAdaptive(validated.measures.hook, validated.measures.hook_content);
const hookContent = scoreHookContent(validated.measures.hook_content);
let hookFinal: number | null = null;
if (hookPace != null && hookContent != null) {
  hookFinal = clamp(0.7*hookPace + 0.3*hookContent, 0, 100);
} else {
  hookFinal = hookPace ?? hookContent;
}

const subscores: any = {
  hook: hookFinal,
  // ... rest unchanged
};
```

3. **Add diagnostics (around line 189):**
```typescript
// Build output
const output: any = {
  version: SCORER_VERSION,
  subscores,
  penalties,
  overall: Math.round(overall * 10) / 10,
  weights: normalizedWeights,
  diagnostics,
  flags: {
    incomplete,
    low_confidence,
  },
  score_details: {  // ADD THIS
    hook_attribution: {
      modality: input.measures.hook_content?.hook_modality_attribution ?? null,
      top_motifs: Object.entries(input.measures.hook_content?.hook_type_probs || {})
        .sort((a,b)=> (b[1]??0) - (a[1]??0)).slice(0,3)
    },
    hook_span: input.measures.hook_content?.hook_span ?? null,
    payoff_time_sec: input.measures.hook_content?.payoff_time_sec ?? null
  }
};
```

4. **Version bump:**
```typescript
// File: scorer/src/types.ts
export const SCORER_VERSION = "1.2.0";  // Change from "1.1.0"
```

### 5. Build & Test (NOT STARTED)

**Steps:**
```bash
cd /Users/ryemckenzie/projects/viraltracker/scorer
npm run build
npm test
```

## 📊 Previous Session Context

### Completed Work (Earlier Today)
- Correlation analysis complete: n=103 videos
- `emotion_intensity` confirmed as strongest predictor (r=0.258, p=0.0085)
- Gemini 2.5 Pro analysis of 34 new videos: ✅ COMPLETE
- All 103 videos now analyzed with v1.1.0

### Database State
- **Total posts in project:** 128
- **Analyzed videos:** 103 (with Gemini 2.5 Pro v1.1.0)
- **Unanalyzed videos:** 25 (already processed/downloaded)

## 🚀 Resume Instructions for Next Session

### Context to Provide
Copy this entire checkpoint + the original spec at the top of the conversation. The original spec is in the task description that started this upgrade.

### Immediate Next Steps

1. **Complete TypeScript Scorer Formulas** (30 min estimated)
   - Add `scoreHookContent()` to `scorer/src/formulas.ts`
   - Add `scoreHookAdaptive()` to `scorer/src/formulas.ts`
   - Update imports/exports

2. **Integrate into Scorer** (15 min estimated)
   - Update `scorer/src/scorer.ts` to blend hook scores (70/30)
   - Add diagnostics to output
   - Update `scorer/src/types.ts` version to 1.2.0

3. **Build & Test** (10 min estimated)
   ```bash
   cd scorer
   npm run build
   npm test  # May need to update tests
   ```

4. **Database Migration** (5 min estimated)
   - Check if `video_analysis.hook_features` JSONB column exists
   - If not, run migration:
   ```sql
   ALTER TABLE video_analysis ADD COLUMN IF NOT EXISTS hook_features JSONB;
   ```

5. **Test with Sample Videos** (15 min estimated)
   - Re-analyze 2-3 videos with v1.2.0
   - Inspect `hook_features` JSONB output
   - Verify scorer can consume the new fields

6. **Optional: Re-analyze Full Dataset** (depends on budget)
   - 103 videos × ~40 sec/video = ~68 minutes
   - Cost: ~103 × $0.10 = ~$10.30 in Gemini API credits
   - Decision: Analyze a stratified sample (20 videos) OR full dataset

### Files Modified This Session
1. `/Users/ryemckenzie/projects/viraltracker/viraltracker/analysis/video_analyzer.py`
2. `/Users/ryemckenzie/projects/viraltracker/scorer/src/schema.ts`

### Files To Modify Next Session
1. `/Users/ryemckenzie/projects/viraltracker/scorer/src/formulas.ts` (add 2 functions)
2. `/Users/ryemckenzie/projects/viraltracker/scorer/src/scorer.ts` (update hook scoring)
3. `/Users/ryemckenzie/projects/viraltracker/scorer/src/types.ts` (version bump)

### Key Decisions Needed
1. **Database column:** Confirm `hook_features` JSONB column exists (may need migration)
2. **Re-analysis scope:** Sample (20 videos) vs Full dataset (103 videos)
3. **Scorer deployment:** How/where is the TypeScript scorer currently used?

## 📁 Reference Files

### Original Spec Location
See the task message that started this conversation - it contains the full Hook Intelligence Upgrade spec with all formula details.

### Related Checkpoints
- `CHECKPOINT_2025-10-13.md` - Clockworks migration & correlation results (n=103)
- `CHECKPOINT_2025-10-11.md` - Initial v1.1.0 correlation results (n=69)

## 🎯 Success Criteria

When complete, we should have:
1. ✅ Python analyzer extracting 14 hook types + modality + catalysts + windows
2. ✅ Hook data stored in `video_analysis.hook_features` JSONB
3. ⏳ TypeScript scorer computing Hook Content Score (0-100)
4. ⏳ TypeScript scorer computing Adaptive Hook Pace Score with windowing
5. ⏳ Final hook score = 70% pace + 30% content
6. ⏳ Scorer version 1.2.0 with diagnostics
7. ⏳ Sample videos analyzed with v1.2.0 showing hook intelligence data

---

**Session End:** 2025-10-14
**Next Session:** Continue with TypeScript formulas implementation
