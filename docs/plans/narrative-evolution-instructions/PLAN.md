# Plan: Narrative-Aware Evolution Instructions

## Phase 1: Intake

### Problem

When iterating on winning ads, the pipeline doesn't understand *what makes the parent ad work*. The evolution instructions say "change hook type to X" and "keep visuals identical," but when the new hook type contradicts the parent's visual narrative, the result is incoherent.

**Example:** Parent ad shows an exhausted woman hitting snooze alarms (problem-state visual, `hook_type=problem_solution`). We iterate with `hook_type=transformation`. The pipeline keeps the zombie lady visual but writes "I no longer wake up at 2am" — the transformation message contradicts the exhausted visual.

**Root cause (two layers):**

1. **Instructions layer:** The instructions treat visual content and messaging as independent. They say "change the hook" but "keep visuals identical." The visual IS part of the hook.

2. **Architecture layer (deeper):** Even if we write better instructions, the V2 pipeline passes the parent image as a **reference image** to Gemini's `generate_image()`. Image generation models weigh visual references much more heavily than text instructions. Telling Gemini "show the solution state" while simultaneously showing it the exhausted-woman image as the visual reference means the instructions are fighting the architecture. Gemini will reproduce the exhausted woman because that's what the reference image shows.

**The fix must address both layers:**
- Better instructions that understand the visual-text relationship
- Remove the parent image as visual reference when it conflicts with the new hook

### Solution

Three-part enhancement to the evolution pipeline:

1. **Narrative analysis:** Use Gemini 3 Pro to analyze the parent image and describe what it shows. Cache in `element_tags`.
2. **Contextual instructions:** Build evolution instructions that use the narrative + transition rules to tell the pipeline what to change and why.
3. **Reference image control:** When a visual conflict is detected (e.g., problem_solution → transformation), **skip the parent image as a Gemini reference** so the instructions drive the visual, not the reference image. Keep product images and logo as references for brand consistency.

### Requirements (gathered from user)

| Decision | Choice |
|----------|--------|
| Analysis model | `gemini-3-pro` (best understanding of visual narratives) |
| Caching | Cache narrative in parent's `element_tags` JSONB (one-time cost per parent) |
| Scope | Both winner iteration AND anti-fatigue refresh |
| Visual freedom | Adapt visual to match hook — keep brand style/layout, but scene can change |

### Trigger

Runs automatically inside `_evolve_winner_iteration()` and `_evolve_anti_fatigue()` whenever an evolution job executes. No UI changes needed.

### Inputs

- Parent ad's base64 image (already loaded in `evolve_winner()`)
- Parent ad's `element_tags` (already loaded)
- Parent ad's `hook_text` (already loaded in `parent` dict)

### Outputs

- Cached `visual_narrative` string in parent's `element_tags`
- Contextual `additional_instructions` string passed to V2 pipeline
- `skip_template_reference` flag when visual conflict detected

---

## Phase 2: Architecture Decision

**Pattern: Service method additions + minimal pipeline state extension**

This is primarily an enhancement to `WinnerEvolutionService` methods, with one small addition to the V2 pipeline state (`skip_template_reference` boolean flag).

Flow:

1. Evolution job fires (existing)
2. **NEW:** Analyze parent image narrative (Gemini call or cache hit)
3. **NEW:** Detect if new hook conflicts with parent visual
4. **CHANGED:** Build contextual instructions using narrative + transition rules
5. **NEW:** If conflict detected, set `skip_template_reference=True` in pipeline params
6. Run V2 pipeline (existing, but respects the new flag)

---

## Phase 3: Inventory & Gap Analysis

### Existing Components (Reuse)

| Component | Location | How Used |
|-----------|----------|----------|
| `GeminiService.analyze_image()` | `viraltracker/services/gemini_service.py` | Analyze parent image narrative |
| `WinnerEvolutionService._evolve_winner_iteration()` | `viraltracker/services/winner_evolution_service.py` | Add narrative analysis + instructions |
| `WinnerEvolutionService._evolve_anti_fatigue()` | Same file | Add narrative context for what to preserve |
| `SpecialInstructions` model | `viraltracker/pipelines/ad_creation_v2/models/prompt.py` | Instructions flow as `priority: "HIGHEST"` |
| `element_tags` JSONB on `generated_ads` | Supabase | Cache `visual_narrative` field |
| `AdCreationPipelineState` | `viraltracker/pipelines/ad_creation_v2/state.py` | Add `skip_template_reference` flag |

### New Components (Build)

| Component | Type | Location |
|-----------|------|----------|
| `HOOK_TRANSITION_GUIDANCE` | Static dict | `winner_evolution_service.py` (module-level constant) |
| `_analyze_parent_narrative()` | Private async method | `WinnerEvolutionService` |
| `_build_evolution_instructions()` | Private sync method | `WinnerEvolutionService` |
| `skip_template_reference` | Boolean field | `AdCreationPipelineState` |
| Skip-reference logic | 3-line conditional | `generation_service.py:execute_generation()` |

### Database Impact

**No migration needed.** `element_tags` is an existing JSONB column. We add a `visual_narrative` key. No schema change.

**Cache write pattern:** The service has the full `element_tags` dict in memory (loaded at line 926). Mutate in-memory, write full dict back. Safe because it's the complete dict, not partial.

```python
element_tags["visual_narrative"] = narrative
self.supabase.table("generated_ads").update(
    {"element_tags": element_tags}
).eq("id", str(parent_ad_id)).execute()
```

**Concurrent writes:** If two jobs for the same parent fire simultaneously, both produce the same narrative (same image → same description). Last-writer-wins is benign. One wasted Gemini call (~$0.005) is acceptable.

### Gap Analysis

- [x] Can we use an existing service? **Yes** — `GeminiService.analyze_image()`
- [x] Can we extend existing services? **Yes** — add methods to `WinnerEvolutionService`
- [ ] Do we need a new service? **No**
- [ ] Do we need new tools? **No**
- [ ] Do we need new tables/columns? **No** (JSONB extension + state field only)

---

## Phase 4: Build Plan

### Step 1: Add `skip_template_reference` to pipeline state + generation service

**File:** `viraltracker/pipelines/ad_creation_v2/state.py`

Add one field to `AdCreationPipelineState`:

```python
skip_template_reference: bool = False  # When True, omit template image from Gemini reference_images
```

**File:** `viraltracker/pipelines/ad_creation_v2/services/generation_service.py`

In `execute_generation()` (line ~386-405), add a conditional:

```python
# Download template reference image
template_data = await ad_creation_service.download_image(
    nano_banana_prompt['template_reference_path']
)

# Build reference images
# When skip_template_reference is set (visual conflict detected in evolution),
# omit the template to let instructions drive the visual instead of the
# reference image anchoring on the parent's incompatible scene.
if nano_banana_prompt.get('skip_template_reference'):
    reference_images = logo_data + product_images_data
    logger.info("Skipping template reference image (visual conflict evolution)")
else:
    reference_images = [template_data] + logo_data + product_images_data
```

**File:** `viraltracker/pipelines/ad_creation_v2/services/generation_service.py`

In `generate_prompt()` (line ~340-356), pass the flag through:

```python
return {
    "prompt_index": prompt_index,
    ...
    "template_reference_path": reference_ad_path,
    "skip_template_reference": getattr(ctx_state, 'skip_template_reference', False) if ctx_state else False,
    ...
}
```

**File:** `viraltracker/pipelines/ad_creation_v2/orchestrator.py`

Pass through in `run_ad_creation_v2()`:

```python
skip_template_reference: bool = False,
```

And into the state:

```python
state = AdCreationPipelineState(
    ...
    skip_template_reference=skip_template_reference,
)
```

This is a minimal, backward-compatible change. Existing callers don't pass `skip_template_reference`, so it defaults to `False` (no behavior change).

### Step 2: Add `HOOK_TRANSITION_GUIDANCE` constant

**File:** `viraltracker/services/winner_evolution_service.py`

Static dict mapping hook_type transitions to visual guidance and conflict detection. Covers the 8 hook types most likely to create visual-message conflicts.

```python
HOOK_TRANSITION_GUIDANCE = {
    "transformation": {
        "visual_rule": "show the AFTER/solution state, not the problem",
        "conflicts_with": ["problem_solution", "before_after"],
        "guidance": "The parent visual shows a problem/struggle state. "
                    "Adapt the visual to show the resolved/transformed outcome instead.",
    },
    "direct_benefit": {
        "visual_rule": "show the benefit being enjoyed",
        "conflicts_with": ["problem_solution", "fear_of_missing_out"],
        "guidance": "The parent visual shows a negative state. Adapt to show "
                    "the positive outcome — the person enjoying the benefit.",
    },
    "problem_solution": {
        "visual_rule": "show the problem state or pain point",
        "conflicts_with": ["transformation", "direct_benefit"],
        "guidance": "The parent visual shows a resolved/positive state. "
                    "Adapt to show the problem or struggle the product solves.",
    },
    "fear_of_missing_out": {
        "visual_rule": "show what others enjoy that the viewer might miss",
        "conflicts_with": ["testimonial", "story"],
        "guidance": "The visual should create desire and exclusion anxiety. "
                    "Add social energy and aspirational elements.",
    },
    "social_proof": {
        "visual_rule": "show social validation or community",
        "conflicts_with": [],
        "guidance": "Social proof works with most visuals. Add elements "
                    "suggesting popularity or community endorsement.",
    },
    "urgency": {
        "visual_rule": "convey time pressure or limited availability",
        "conflicts_with": ["story", "testimonial"],
        "guidance": "The visual should feel urgent. If calm or reflective, "
                    "add energy and immediacy.",
    },
    "testimonial": {
        "visual_rule": "show a real person's authentic experience",
        "conflicts_with": ["statistic", "bold_claim"],
        "guidance": "The visual should feel personal and authentic. "
                    "If clinical or abstract, humanize it.",
    },
    "before_after": {
        "visual_rule": "show clear contrast between before and after states",
        "conflicts_with": [],
        "guidance": "The visual must show contrast. If the parent only shows "
                    "one state, create a split or progression visual.",
    },
}
```

### Step 3: Add `_analyze_parent_narrative()` method

**File:** `viraltracker/services/winner_evolution_service.py`

```python
async def _analyze_parent_narrative(
    self,
    parent_ad_id: UUID,
    parent_image_b64: str,
    element_tags: Dict,
    hook_text: Optional[str] = None,
) -> str:
    """Analyze the parent ad's visual narrative using Gemini 3 Pro.

    Checks element_tags for a cached 'visual_narrative' first.
    If not cached, calls Gemini, caches the result in element_tags,
    and writes it back to the generated_ads row.

    Args:
        parent_ad_id: Parent generated_ad UUID (for cache update).
        parent_image_b64: Base64-encoded parent image.
        element_tags: Parent's element_tags dict (mutated with cache on miss).
        hook_text: Optional hook text for richer analysis context.

    Returns:
        Narrative description (2-4 sentences). Empty string on error.
    """
```

Logic:
1. Check `element_tags.get("visual_narrative")` — if present, log cache hit, return it
2. Call `GeminiService(model="gemini-3-pro").analyze_image()` with prompt
3. Truncate at last sentence boundary before 500 chars
4. Mutate `element_tags["visual_narrative"] = narrative`
5. Write full `element_tags` back to DB
6. Return narrative

**Prompt:**

```
Analyze this ad image in 2-4 sentences. Describe:
1. WHAT the visual shows (people, objects, scene, emotional state)
2. WHY it works as an ad (what psychological lever does the visual pull?)
3. The relationship between the visual content and the messaging

{f"Current hook text: '{hook_text}'" if hook_text else ""}

Be specific and concrete about what you see.
```

Note: No example in the prompt (avoids biasing Gemini's output format).

**Error handling:** On failure, log warning, return empty string. Do NOT cache empty (so next iteration retries).

**Logging:**
- Cache hit: `logger.info(f"Narrative cache hit for {parent_ad_id}")`
- Miss: `logger.info(f"Narrative analyzed for {parent_ad_id}: '{narrative[:100]}...'")`
- Failure: `logger.warning(f"Narrative analysis failed for {parent_ad_id}: {e}")`

### Step 4: Add `_build_evolution_instructions()` method

**File:** `viraltracker/services/winner_evolution_service.py`

```python
def _build_evolution_instructions(
    self,
    variable: str,
    new_value: str,
    parent_value: str,
    narrative: str,
    element_tags: Dict,
) -> str:
    """Build contextual evolution instructions using parent narrative.

    Args:
        variable: Element being changed.
        new_value: The new value.
        parent_value: The parent's current value.
        narrative: Visual narrative from _analyze_parent_narrative().
        element_tags: Full parent element_tags.

    Returns:
        Instruction string for pipeline SpecialInstructions.
    """
```

**Hook type template:**

```
EVOLUTION: Change the hook persuasion type from '{parent_value}' to '{new_value}'.

{f"PARENT AD VISUAL: {narrative}" if narrative else ""}

{transition_guidance if conflict detected}

The visual and messaging must tell a coherent story together.
Keep the same brand style, color palette, and product presentation.
{f"Since the visual reference has been removed (visual conflict), describe the scene that matches a '{new_value}' hook." if conflict else ""}
```

When a conflict is detected, the instructions explicitly note that the reference image was removed, so Gemini knows to generate the scene from the text description rather than expecting a visual reference to anchor on.

**Template category template:**

```
EVOLUTION: Change the layout from '{parent_value}' to '{new_value}' template style.

{f"PARENT AD VISUAL: {narrative}" if narrative else ""}

Restructure the visual layout to match '{new_value}' conventions.
Preserve the core message, psychological approach, and brand style.
```

**Awareness stage template:**

```
EVOLUTION: Adapt the ad from '{parent_value}' to '{new_value}' awareness stage.

{f"PARENT AD VISUAL: {narrative}" if narrative else ""}

Adjust messaging sophistication for '{new_value}' awareness:
- unaware: Lead with the problem, don't mention the product yet
- problem_aware: Agitate the problem, hint at solutions
- solution_aware: Position the product as the best solution
- product_aware: Differentiate from alternatives, handle objections
- most_aware: Drive action with offers, urgency, social proof

Keep the same visual style and brand identity.
```

**Color mode:** Add narrative context if available:

```python
if variable == "color_mode" and narrative:
    return (
        f"PARENT AD VISUAL: {narrative}\n\n"
        f"Apply '{new_value}' color treatment while preserving the visual narrative."
    )
```

**Method also returns a `has_visual_conflict` boolean** (or the caller checks separately) to drive the `skip_template_reference` flag. Implementation detail: simplest is a separate helper:

```python
def _has_visual_conflict(self, variable: str, new_value: str, parent_value: str) -> bool:
    """Check if the variable change creates a visual-message conflict."""
    if variable != "hook_type":
        return False
    transition = HOOK_TRANSITION_GUIDANCE.get(new_value, {})
    return parent_value in transition.get("conflicts_with", [])
```

### Step 5: Update `_evolve_winner_iteration()`

Replace the inline instruction blocks with the new methods:

```python
# Analyze parent narrative (cached after first call)
narrative = await self._analyze_parent_narrative(
    UUID(parent["id"]),
    parent_image_b64,
    element_tags,
    hook_text=parent.get("hook_text"),
)

# Detect visual conflict
visual_conflict = self._has_visual_conflict(variable, new_value, parent_value)

# Build contextual instructions
pipeline_params["additional_instructions"] = self._build_evolution_instructions(
    variable=variable,
    new_value=new_value,
    parent_value=parent_value,
    narrative=narrative,
    element_tags=element_tags,
)

# When visual conflict detected, skip template reference so instructions drive the visual
if visual_conflict:
    pipeline_params["skip_template_reference"] = True
    logger.info(
        f"Visual conflict: {parent_value} → {new_value}. "
        f"Skipping template reference image."
    )

# color_mode is still set mechanically
if variable == "color_mode":
    pipeline_params["color_modes"] = [new_value]
```

**Note:** Do NOT pop `creative_direction`. The `SpecialInstructions.priority = "HIGHEST"` already handles priority. Brand-level constraints in `creative_direction` (prohibited claims, required disclaimers, taglines) should be preserved.

Log the final instructions:

```python
logger.info(
    f"Evolution instructions ({len(pipeline_params['additional_instructions'])} chars): "
    f"'{pipeline_params['additional_instructions'][:150]}...'"
)
```

### Step 6: Update `_evolve_anti_fatigue()`

Add narrative context so the pipeline knows what to preserve:

```python
narrative = await self._analyze_parent_narrative(
    UUID(parent["id"]),
    parent_image_b64,
    element_tags,
    hook_text=parent.get("hook_text"),
)

anti_fatigue_instructions = (
    "ANTI-FATIGUE REFRESH: Create a fresh visual execution while preserving "
    "the exact same psychological approach and messaging."
)
if narrative:
    anti_fatigue_instructions += (
        f"\n\nPARENT AD VISUAL: {narrative}\n\n"
        f"PRESERVE: The core psychological lever described above — what makes "
        f"this ad effective must remain in the new version.\n"
        f"CHANGE: Layout, color palette, image composition, headline wording. "
        f"The viewer should feel it's the same message in new packaging."
    )
else:
    anti_fatigue_instructions += (
        "\n\nKeep the same hook type and messaging angle. "
        "Fresh visual execution: new image, different color treatment."
    )

pipeline_params["additional_instructions"] = anti_fatigue_instructions
```

Anti-fatigue does NOT skip the template reference — it wants to preserve the psychology while changing the surface. The parent image as reference is helpful here (Gemini can see what style to keep while changing the execution).

### Step 7: Tests

Add tests in `tests/services/test_winner_evolution_service.py`:

1. `test_analyze_parent_narrative_cache_hit` — returns cached value, no Gemini call
2. `test_analyze_parent_narrative_cache_miss` — calls Gemini, caches result, writes DB
3. `test_analyze_parent_narrative_gemini_failure` — returns empty string, does NOT cache
4. `test_analyze_parent_narrative_truncation` — truncates at sentence boundary before 500 chars
5. `test_build_evolution_instructions_hook_with_conflict` — includes transition guidance + conflict note
6. `test_build_evolution_instructions_hook_no_conflict` — standard instructions with narrative
7. `test_build_evolution_instructions_template_category` — template-specific instructions
8. `test_build_evolution_instructions_awareness_stage` — all 5 stages listed
9. `test_build_evolution_instructions_no_narrative` — works gracefully with empty narrative
10. `test_has_visual_conflict_detects_problem_to_transformation` — True
11. `test_has_visual_conflict_no_conflict_same_family` — False
12. `test_has_visual_conflict_non_hook_variable` — always False

### Step 8: Compile check + verify

- `python3 -m py_compile` all modified files
- Run full test suite for winner evolution service
- Verify no regressions

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/winner_evolution_service.py` | Add `HOOK_TRANSITION_GUIDANCE`, `_analyze_parent_narrative()`, `_build_evolution_instructions()`, `_has_visual_conflict()`. Update `_evolve_winner_iteration()` and `_evolve_anti_fatigue()`. |
| `viraltracker/pipelines/ad_creation_v2/state.py` | Add `skip_template_reference: bool = False` field |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | Accept and pass through `skip_template_reference` param |
| `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` | Pass through `skip_template_reference` in prompt dict; conditionally omit template from `reference_images` |
| `tests/services/test_winner_evolution_service.py` | Add 12 tests for new methods |

**No new files. No migrations. No new dependencies.**

---

## Cost Analysis

| Item | Cost | Frequency |
|------|------|-----------|
| Gemini 3 Pro `analyze_image` call | ~$0.002-0.005 | Once per parent ad (cached) |
| Cached hits | $0 | All subsequent iterations of same parent |

Batch of 9 winners from 9 parents: ~$0.02-0.05 total. Negligible.

---

## Why This Works: The Zombie Lady Walkthrough

Let's trace the exact scenario with the proposed changes:

1. **Parent ad:** exhausted woman + alarm snooze, `hook_type=problem_solution`
2. **Evolution:** change to `hook_type=transformation`
3. **`_analyze_parent_narrative()`** calls Gemini 3 Pro, returns: *"Shows an exhausted woman repeatedly hitting snooze on multiple alarm notifications. A problem-state visual that triggers recognition in sleep-deprived viewers. The overwhelming alarms create a sense of daily defeat."*
4. **`_has_visual_conflict()`** checks: `transformation` conflicts_with includes `problem_solution` → **True**
5. **`_build_evolution_instructions()`** produces:

```
EVOLUTION: Change the hook persuasion type from 'problem_solution' to 'transformation'.

PARENT AD VISUAL: Shows an exhausted woman repeatedly hitting snooze on multiple
alarm notifications. A problem-state visual that triggers recognition in sleep-deprived
viewers. The overwhelming alarms create a sense of daily defeat.

The parent visual shows a problem/struggle state. Adapt the visual to show the
resolved/transformed outcome instead.

The visual and messaging must tell a coherent story together.
Keep the same brand style, color palette, and product presentation.
Since the visual reference has been removed (visual conflict), create a scene that
matches a 'transformation' hook — show the after state.
```

6. **`skip_template_reference=True`** → pipeline omits the exhausted-woman image from Gemini's reference_images
7. **Gemini image generation** receives: text instructions (above) + product images + logo. NO exhausted woman reference.
8. **Result:** Gemini generates a fresh scene showing a well-rested person (transformation state) with the same brand style and product.

The key difference: without the exhausted-woman reference image anchoring the output, Gemini is free to follow the text instructions and create the transformation scene.

---

## QA Review — All Issues Addressed

### Critical Issues (Fixed)

| ID | Issue | Resolution |
|----|-------|------------|
| C1 | Reference image anchor — Gemini reproduces parent visual regardless of instructions | **Fixed.** Added `skip_template_reference` flag. When visual conflict detected, template image is omitted from `reference_images`. Product images + logo still provide brand consistency. |
| C2 | DB write pattern — naive JSONB update could destroy data | Specified: mutate in-memory dict, write full dict back. |
| C3 | Race condition on concurrent jobs | Accepted: same image → same narrative. Benign last-writer-wins. |

### Warnings (Addressed)

| ID | Issue | Resolution |
|----|-------|------------|
| W1 | `creative_direction` may conflict with evolution | Do NOT pop it. `SpecialInstructions.priority = "HIGHEST"` handles conflicts. Brand constraints preserved. |
| W2 | Missing `problem_solution` and `fear_of_missing_out` | Added to `HOOK_TRANSITION_GUIDANCE`. Now 8 of 15 types. |
| W3 | No truncation | Truncate at last sentence boundary before 500 chars. |
| W4 | No logging | Added logging for cache hit/miss, narrative preview, final instructions. |

### Improvements (Incorporated)

| ID | Improvement | Resolution |
|----|-------------|------------|
| I1 | Biasing example in analysis prompt | Removed example from prompt. |
| I2 | Truncation at sentence boundary | `rfind('.')` before 500 chars. |
| I3 | Creative direction override too aggressive | Changed to not pop it at all. |
| I4 | Log final instructions | Added `logger.info` with first 150 chars. |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| `gemini-3-pro` unavailable | Graceful fallback: empty narrative, instructions degrade to generic (still functional) |
| Narrative hallucination | Prompt says "describe what you see." Even if wrong, instructions still direct Gemini coherently. When template is skipped, hallucinated narrative can't conflict with the reference image (there isn't one). |
| Without reference image, generated ad diverges too much from brand | Product images + logo are still passed as references. Brand colors/fonts are in the JSON prompt. The parent's style is preserved through these channels. |
| Anti-fatigue still has reference image issues | Anti-fatigue doesn't skip the reference — it WANTS to preserve visual style. The reference helps here because anti-fatigue changes execution, not psychology. |
| `skip_template_reference` breaks other pipeline callers | Default is `False`. Only set by evolution service when conflict detected. All other callers unaffected. |
| Instructions too long | Max ~700 chars (narrative 500 + template ~200). Well within Gemini's capability. |
