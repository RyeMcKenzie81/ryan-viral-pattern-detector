# Static (Image) Awareness Calibration — DEEP PATH

**Status:** Reviewed (multi-agent workflow + independent Codex). Deep path chosen; all must-fixes folded in. Ready to build.

## Why
Martin: **1,202 image ads / $228,563 spend (69%)** vs 111 video (31%). The weekly digest buckets both by `creative_awareness_level` (per ad, spend-scoped). Image ads still run on the OLD thin `CLASSIFICATION_PROMPT` (bare labels, no rubric), so ~2/3 of the awareness mix is un-calibrated and inconsistent with the just-shipped video rubric.

## Decision: DEEP path (symmetric to video)
Route image **creative** awareness through the existing `ImageAnalysisService` (deep extraction of on-image `headline_text` / `body_text` / `text_overlays` + `awareness_level`, immutable versioned `ad_image_analysis` rows) — NOT the light thumbnail+caption path.

Rationale (settled by the creative-vs-copy question): the **on-image headline determines creative awareness, and it lives in no DB field** — only deep image analysis reads it. The light path would lean on `ad_copy` (the Facebook caption = COPY, not creative) → conflation that also corrupts congruence.

**Feasibility (verified):** 1,182/1,202 Martin images (98%) already in storage; 1,114 have an old awareness label (the "before"); 358 existing v1 `ad_image_analysis` rows.

## Creative vs Copy — locked mapping
- `creative_awareness_level` <- `ImageAnalysisService` on-image text (`headline_text`/`text_overlays`) + visual. = the text INSIDE the static ad.
- `copy_awareness_level` <- `ad_copy` (the Facebook primary text/caption), judged separately with the SAME rubric.
- Keeps creative-vs-copy congruence meaningful (no self-fulfilling overlap).

## Locked decisions (eng-review 2026-06-08)
- **D1 Inline** (symmetric to video): `classify_ad` runs the deep image analysis itself. Accuracy is identical to two-step (same Gemini call) — chosen for fewer moving parts.
- **D2 Image-version gate, NO global bump:** re-classification is driven by bumping `ImageAnalysisService.PROMPT_VERSION` (v1->v2) + an image-version staleness gate (parallel to `_video_analysis_is_stale`). Only IMAGE ads re-run; video + other brands stay cached; classifier `CURRENT_PROMPT_VERSION` is NOT touched -> the global blast radius disappears.
- **D3 Image-pure creative + separate copy:** `ImageAnalysisService` judges `creative_awareness` from the ON-IMAGE text/visual ONLY (it does NOT use `ad_copy` for the awareness call). `copy_awareness` is a SEPARATE text-only judgment of `ad_copy`. The two judgments never see each other's input -> zero conflation, congruence stays meaningful.
- **D4 Tests:** before/after diff + unit + golden set, PLUS a creative-vs-copy separation test + a completeness-gate test.
- **Perf:** the image-version staleness check MUST bulk-prefetch `ad_image_analysis` versions (Query 6, parallel to video's Query 5) to avoid an N+1.

## Build steps
1. **Fix #180 in `ImageAnalysisService`** — import `make_genai_client` (3rd instance of the regression, after video_analysis + classifier). Smoke test it constructs + resolves the name.
2. **Refactor the rubric -> medium-neutral core + per-medium wrapper.** Pull "judge the OPENING (first ~10s)" out of `AWARENESS_RUBRIC` into the VIDEO wrapper. Add a STATIC wrapper: a static is a SINGLE moment; judge by the DOMINANT readable on-image element (headline > visual > offer hierarchy), not every tiny text block; if on-image text is unreadable, LOWER confidence and do NOT hallucinate OCR. **Regression gate:** re-run the 9 validated videos via their path; must still 100% match.
3. **Wire rubric + static wrapper into the `ImageAnalysisService` prompt.** Bump its `PROMPT_VERSION` v1 -> v2.
4. **Static-specific sub-rules** (seed, then refine in calibration): product-hero (product-only -> judge by copy/format or visual context; +problem visual -> problem; +desired-state visual -> product), before/after (visual-only -> product; +mechanism text -> solution), pure-offer badge -> most, listicle/article headline -> problem/unaware, advertorial (judge the HEADLINE/lead, not the body), review-screenshot (content-routed like testimonials), comparison-chart -> product.
5. **Route the classifier image branch through `ImageAnalysisService` INLINE** (D1, parallel to `_classify_video_with_gemini`): `creative_awareness_level` <- image analysis `awareness_level` (on-image text only); `copy_awareness_level` <- a SEPARATE text-only judgment of `ad_copy` with the rubric (D3); link `image_analysis_id`; add an image-version staleness gate to classify-once (parallel to `_video_analysis_is_stale`, gated on `ad_image_analysis.PROMPT_VERSION`) + a bulk prefetch of image-analysis versions (Query 6, parallel to Query 5) to avoid N+1.
6. **Before/After comparison harness** (data-quality + calibration): for Martin image ads with an old label, run the new deep path (preview, NO write) and emit an old->new diff (+ the on-image headline keyed on + a view link). Hand-validate a FORMAT-DIVERSE sample; then quantify the brand-wide shift (% changed bucket) as a client deliverable.
7. **Tests (D4):** unit (result parse/fallback; mapping creative<-image vs copy<-ad_copy; image version-staleness branches; #180 import smoke) + a **creative-vs-copy separation test** (assert creative is judged from the image and copy from `ad_copy`, never conflated) + a **completeness-gate test** (digest behaves correctly mid-backfill) + a golden-set agreement check on the hand-validated sample.
8. **Rollout (D2 — no global bump):** re-classification is triggered by the IMAGE-version gate (bump `ImageAnalysisService.PROMPT_VERSION`), so the classifier `CURRENT_PROMPT_VERSION` is untouched and there is **no non-Martin blast radius** — only image ads re-run, on their next classification job. Run **Martin-first**. Do NOT use `force=True`. **Completeness gate:** do not publish the digest until all of Martin's spend-scoped image ads are at the current image-analysis version (track the stale count to 0), same pattern as the video backfill.

## Must-fixes folded in (from the adversarial reviews)
1. Creative/copy split (steps 1,5 — deep path makes this clean).
2. Mixed v2/v3 digest during partial backfill -> completeness gate / version filter (step 8).
3. Global version-bump blast radius + no `force=True` (step 8).
4. Static hierarchy + legibility + per-format sub-rules (steps 2,4).
5. Readability of advertorials -> deep on-image extraction + 98% storage coverage (the decision itself).

## Open items — RESOLVED during build (S4)
- `ad_image_analysis` schema: awareness_level + confidence exist; static is single-value (no opening/ending). `ImageAnalysisResult` now also surfaces `analysis_id` (the saved row id) so the classification can link `image_analysis_id`.
- Inline vs two-step: **INLINE** (D1). `classify_ad` calls `ImageAnalysisService.analyze_image` directly. The image call is made WITHOUT `ad_copy` (creative awareness is image-pure — exactly how the rubric was hand-calibrated, store=False evals passed no copy), so D3 holds at the strongest level.
- `ImageAnalysisResult` did NOT need a `copy_awareness_level`: copy is judged by a SEPARATE text-only call in the classifier (`_classify_copy_awareness` + `COPY_AWARENESS_PROMPT`), so the two judgments never share a model call.
- **Deep-or-SKIP (no light fallback when the deep image service is wired):** when `ImageAnalysisService` is present, image ads route deep-or-skip. If deep can't run (no full-res asset in storage, too low-res, transient parse failure) the ad is SKIPPED (not persisted) rather than falling back to the legacy light thumbnail+caption path (which conflates the caption into creative awareness). This makes classify-once converge — the only PERSISTED non-video outcome is a current-version deep row — and matches the plan's "not in storage → stays at old classification, degrades gracefully" failure mode. The deep service is wired into ALL production `ClassifierService` constructions (scheduler `ad_classification` + `congruence_reanalysis`, `AdIntelligenceService.full_analysis`, `DiagnosticEngine` lazy classifier), consistent with the user's "one shared awareness definition platform-wide" goal. Callers WITHOUT the service keep the legacy light path and never re-flag (`_image_analysis_is_stale` returns False when unwired).

## E2E Tier 1 findings (read-only live run, 2026-06-08)
Adversarial design pass (multi-agent) + a read-only live run on a grounded 18-ad Martin sample (real Gemini, no DB writes):
- **Golden creative agreement: 7/7** through the real classifier path — incl. the two ads the OLD v1 deep label got wrong (Text Oct 8 v1=solution→v2=**product** ✅; 3am(4) v1=problem→v2=**solution** ✅). v2 recalibration reproduces the hand labels.
- **low_res: 4/4 skipped** (incl. the **$12,104 POV - Emoji** 64×64) — guard fires before any Gemini call.
- **Format mapping correct** (product_hero→image_product, before_after→image_before_after, testimonial_card→image_testimonial, …). **7.3MB / 4096² ad → OK** (no payload timeout). **Video control → image gate correctly skips.**
- **BUG FOUND & FIXED — copy awareness was judging the internal ad_name.** `_fetch_ad_data` falls back to `ad_name` (e.g. `'POV - Emoji- cortisol reducer'`, `'concept_placeholder_…png'`) when the LATEST perf row's `ad_copy` is empty — and Martin's real captions live in EARLIER rows. The new copy path would have judged the ad_name's awareness (noise) and corrupted congruence. Fix: `_get_latest_caption` returns the most-recent NON-EMPTY genuine `ad_copy` across rows (no ad_name fallback); None ⇒ copy awareness skipped, congruence not computed. With the fix, copy awareness is meaningful and D3 divergence is clean (Fall-asleep: creative product_aware vs copy problem_aware).

### Rollout-critical (surfaced by the live sample)
- **5 of the 14 hand-validated golden ads are 64×64 thumbnails → low_res skip**, so they get NO deep label; the `solution_aware` bucket is hit worst (4 of 5 solution golden ads are 64×64). The brand-wide deep `solution_aware` share is under-sampled until those are re-fetched full-res from Meta.
- **A $12,104 ad (POV - Emoji) is a 64×64 thumbnail.** The **completeness gate (step 8) MUST count low_res/skipped spend as STALE/unclassified, not silently exclude it**, or a $12k ad vanishes from the awareness mix and the digest is materially wrong. This is the #1 rollout gate.
- **No clean image no-asset case exists on live Martin** (98% storage coverage): the "deep returns None (no image)" branch is effectively untestable live; the realistic skip path is low_res.

## E2E Tier 2 findings (persisting run-twice, 2026-06-08)
Ran the REAL `classify_batch` on a 16-ad Martin image sample, twice. It caught **two blocking bugs invisible to mocks + the read-only Tier 1** (both stopped the deep path from ever persisting a row), now fixed:
1. **`classify_ad`'s legacy input_hash cache overrode `classify_batch`'s staleness decision.** Batch flagged stale light rows (no `image_analysis_id`) → called `classify_ad(force=False)` → `_find_existing_classification` re-served the same stale row → deep branch never ran. Fix: `classify_batch` passes `force=True` (it is the cache authority via the prefetch + `_video/_image_analysis_is_stale` gates; the prefetch cache is intentionally not input_hash-gated). Only other prod caller (congruence_reanalysis) already used `force=True`.
2. **`creative_format` CHECK constraint** allows only `image_static / image_before_after / image_testimonial / image_product` among image formats; the mapping emitted `image_lifestyle / image_infographic / image_screenshot / …` → every non-{product,before_after,testimonial} deep INSERT failed. Fix: map within the allowed vocabulary (unknown → `image_static`), matching the legacy light path. Test locks creative_format to the allowed set.

**Verified after fixes (run-twice):** all 12 full-res sample ads → `gemini_image_deep` with a linked current-v2 `image_analysis_id`; **run 2 cached=12, new=0, zero new `ad_image_analysis` rows** (classify-once converges, no Gemini re-billing); 4 low_res correctly skipped (no deep row, old row remains). Tier 2: 19/19. The ~12 deep classifications it persisted are correct and a legitimate slice of the Martin backfill (kept).

## Code review (PR #267, multi-agent adversarial — 18 confirmed, verified)
**Fixed in-PR:**
- **Awareness normalization at the trust boundary** (the one consensus real bug, flagged by 3 reviewers): the deep path wrote Gemini's `awareness_level` raw, so an off-canonical label ("Product Aware", trailing space, hallucination) would violate the CHECK constraint → INSERT throws → ad never classified + re-bills every run. Fix: `ImageAnalysisService._normalize_awareness_level` normalizes at parse (recovers casing/spacing variants, NULLs true garbage) so the stored row is always valid and `_check_existing` then short-circuits re-bills; plus defense-in-depth `self._normalize_awareness(...)` in the classifier mapper. Copy awareness was already safe (goes through `_parse_gemini_response`).
- **Stale docstring/comments** on `_classify_image_with_analysis_service` said "falls back to the light path" — the caller actually deep-or-SKIPs. Corrected (a real maintenance trap).
- **`creative_format` constraint guardrail**: extracted `IMAGE_CREATIVE_FORMATS` constant (single source of truth), mapper clamps to it, test binds to it (not a re-typed literal).
- **`classify_ad` force=True footgun note**: documented that all prod callers pass force=True and the legacy input_hash cache is not staleness-aware.
- **Regression tests** (the highest-value gaps): `classify_batch`→`classify_ad(force=True)` for a stale-light row + cached-branch convergence; deep-or-skip persistence (None→`skipped_image_deep_unavailable`, low_res→`skipped_image_low_res`, light path never called); awareness normalization; `_image_too_small`. Static suite 22→30; 49 classifier tests green.

**Deferred (verifiers agreed: tech-debt, not blockers):**
- low_res / no-asset image ads re-download + re-decode every batch (skips never persist a settling row → never converge). Bounded, cheap, NO Gemini spend, NO budget. Fold into the completeness-gate follow-up (which re-fetches low_res assets full-res).
- `_get_latest_caption` is +1 query per newly-classified image ad; could be folded into prefetch Query 1. Marginal (classify_ad already does ~4 per-ad queries; cached ads never hit it). Optional cleanup.
- Copy-awareness uses `gemini-pro-latest` (via VIDEO_ANALYSIS_MODEL) for a text-only task; a `gemini-flash-latest` swap ~halves pro cost per image ad. Deferred because it would change the copy judgment and deserves its own validation.
- video vs image staleness-gate / prefetch duplication → natural shared seam for the FOLLOW-UP #1 template-classifier unification.

## Build status
- **S1-S5: done.** #180 fix, rubric refactor (+ video regression gate), deep ImageAnalysisService wiring (PROMPT_VERSION v2), static sub-rules, before/after harness — all committed in `cba45a0d` and hand-validated on ~50 Martin ads.
- **S4: done.** Classifier image branch routed INLINE through ImageAnalysisService (deep-or-skip), creative/copy split (D3), `image_analysis_id` link + migration, image-version staleness gate (`_image_analysis_is_stale`), Query 6 bulk prefetch (4-tuple). Wired into all production ClassifierService constructions.
- **S6: unit suite done** (`tests/test_static_awareness.py`, 19 tests): creative<-image vs copy<-ad_copy separation, image-pure call (ad_copy never passed to the image), imagery->format mapping, deep-or-skip routing (ok/low_res/None/error/exception), image-version staleness branches, copy-empty short-circuit, brace-safe copy prompt, #180 import smoke. All 38 classifier tests green.
- **DEFERRED to rollout (steps 6/8):** the golden-set agreement check (needs live Gemini + stored images — run as a network-gated script, like the calibration evals) and the completeness-gate test (needs the digest version-coverage gate, which is built in step 8). These are rollout gates, not mergeable unit tests.
- **REQUIRED before this runs in prod:** apply `migrations/2026-06-08_classifications_image_analysis_id.sql` (the INSERT writes `image_analysis_id`; the column must exist). Reads are backward-compatible (graceful None pre-migration).

## Follow-ups (priority order)
1. **FIRST after this plan — unify the TEMPLATE classifier onto the shared AWARENESS_RUBRIC.** Today `template_queue_service.py` classifies scraped templates with its OWN simple "rate 1-5" prompt via `GeminiService.analyze_image` (stored as INT 1-5 in `scraped_templates.awareness_level`, consumed by `template_scoring_service`'s awareness_align scorer for template<->persona matching). This is a SEPARATE, un-calibrated path -> the platform uses two different awareness definitions (ads = calibrated Schwartz rubric string enum; templates = loose 1-5 int). The user flagged this as very important: one shared definition across the platform to ensure congruence and avoid drift. Bring templates onto `AWARENESS_RUBRIC` (map the rubric output to the 1-5 scale or migrate templates to the string enum), then re-classify the template library.

## NOT in scope (this plan)
Video (already validated/shipped). Landing-page awareness prompt. The digest publish itself (after both backfills). The template-classifier unification (it's follow-up #1 above, right after this).

## Worktree parallelization
Sequential implementation, no parallelization opportunity — every step funnels through `ImageAnalysisService` + `classifier_service.py` (one shared module pair). Build order: #180 fix -> rubric refactor (+ video regression gate) -> wire ImageAnalysisService -> route classifier inline -> comparison harness -> tests -> rollout.

## Failure modes
- Image not in storage (20 of 1,202) -> deep analysis can't run; the ad stays at its old classification (degrades gracefully, like video's not-in-storage path). Covered by the staleness gate (re-attempts when stored).
- Unreadable on-image text (low-res / dense advertorial) -> rubric instructs "lower confidence, do NOT hallucinate"; surfaces as low `awareness_confidence` rather than a wrong bucket. Test: assert low-confidence path.
- Partial backfill -> completeness gate blocks the digest publish until Martin's spend-scoped images are all current (no mixed-version report). Test: completeness-gate test.
- Rubric refactor regresses video -> the video regression gate (re-run the 9 validated videos) catches it before merge.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | needs-fixes; 8 findings folded in (ImageAnalysisService, creative/copy split, blast radius) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | 4 decisions locked (D1 inline, D2 image-version gate, D3 image-pure creative, D4 +2 tests); 0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | n/a |

- **CROSS-MODEL:** the multi-agent workflow and Codex independently flagged the global blast-radius and the creative/copy conflation; both are resolved (D2 image-version gate; D3 image-pure creative).
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — 4 architecture decisions locked, scope tight (reuse-heavy, 0 new classes), ready to implement.
