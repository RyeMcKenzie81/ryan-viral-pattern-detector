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

## Open items to verify during build
- `ad_image_analysis` schema has the columns we map (awareness_level + confidence exist; static is single-value, no opening/ending needed).
- Inline call vs two-step: does the classifier call `ImageAnalysisService` inline, or do we keep the existing separate image-analysis job feeding it (mirroring video's download->analyze->classify)? Decide in step 5.
- `ImageAnalysisResult` may need a `copy_awareness_level` add if we judge copy in the same call.

## NOT in scope
Video (already validated/shipped). Landing-page awareness prompt. The digest publish itself (after both backfills).

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
