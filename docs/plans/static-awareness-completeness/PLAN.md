# Static-Awareness Completeness Gate + low_res Churn Fix

**Status:** Eng-reviewed (plan-eng-review, 2026-06-09). 6 decisions locked. Ready to build.
**Predecessor:** `docs/plans/static-awareness-calibration/PLAN.md` (deep static-image classification, merged PR #267).

## Sequencing and related plans (do not lose track)
This workstream is one piece of the larger **weekly per-product Slack digest** effort. The map so the dependencies stay visible:

1. **Weekly digest (the goal / consumer).** Design: `ad-attribution-weekly-slack-design-20260602-130100` (WS1-5: attribution correctness + the Saturday Slack digest, `WeeklyDigestService`). The digest engine is BUILT; the remaining blockers to a TRUSTWORTHY publish are:
   - **THIS plan** — awareness completeness gate (stop counting stale/low_res spend as current) + the low_res churn fix.
   - **The Martin backfill** — run `classify_batch` (deep path, merged PR #267) over Martin's image ads so they move stale -> current; the gate holds "pending" until it drains.
   - **Parked: low_res asset recovery** — the 64x64 thumbnails (incl. the ~$12k POV ad) need re-fetch at higher res, which needs Meta `pages_read_engagement` / Page Public Content Access. Until then they sit permanently in the completeness line. (Separate Meta-permissions effort; see NOT in scope.)
2. **Template-classifier unification (NEXT workstream, task #47).** Follow-up #1 from `docs/plans/static-awareness-calibration/PLAN.md`: bring `template_queue_service` onto the shared `AWARENESS_RUBRIC` so ads and templates use ONE awareness definition (no drift). Independent of the digest path; scheduled right after this completeness gate ships. See memory `awareness_rubric_platform_consistency`.

Order: **this completeness gate -> Martin backfill -> digest publish** (the digest path), then **template-classifier unification** (the consistency follow-up). The low_res Meta-permissions recovery is parallel/parked.

## Why
The weekly per-product Slack digest (`WeeklyDigestService`) buckets spend by `creative_awareness_level`, reading the latest classification per ad with **no filter on version, source, or `image_analysis_id`** (`weekly_digest_service.py:200-203`). So a low_res ad that still carries an OLD `gemini_light_stored` row (current `prompt_version`, `image_analysis_id` NULL) has that stale, pre-deep label silently counted as current. ~13% of Martin's image spend is 64x64 thumbnails (incl. a ~$12k POV ad) that the deep path SKIPS and never persists, so they keep their old label and never converge. Two rooted-in-one-cause problems:
1. **Completeness gate** (digest blocker): the digest must count stale / low_res / not-current spend as INCOMPLETE, not silently fold it into the buckets, and must not headline a mix computed from a non-representative sample.
2. **low_res re-download churn**: skipped image ads re-download + re-decode every classification run because no settling row is persisted (bounded, no Gemini spend, but unbounded over time).

## Locked decisions (plan-eng-review 2026-06-09; D1/D3/D5 REVISED after the Codex outside voice)
- **D1 (Issue 1, REVISED -> marker-only) Settling lives ONLY in `ad_image_analysis`, never in a classification.** On a genuine low_res result, persist a `status='low_res'` marker row in `ad_image_analysis` (awareness NULL, keyed on `input_hash`+`prompt_version`). Do NOT write any `ad_creative_classifications` row for a skip, and do NOT link the marker into a classification. The classifier prefetch reads the low_res markers (new bulk query) and skips those ads from the to-classify loop (stops the re-download); the digest reads them (bulk query) to label low_res. **No timestamp re-open** (`meta_ad_assets.downloaded_at` does not exist — only `created_at` — and the asset job does not re-download existing assets): the marker is PERMANENT until a future high-res re-fetch capability explicitly clears it. (Codex VERIFIED that the originally-locked "skip-row" design poisoned 5 latest-classification consumers — `baseline_service`, `congruence_checker`, `winner_dna_analyzer`, `get_latest_classification`, `get_classification_for_run` — and that the re-open column does not exist. Marker-only avoids both.)
- **D2 (Issue 2) Distribution = current-version only.** Awareness buckets contain ONLY current-version classifications (deep image at current image version + current video). Stale (old light / unlinked), low_res, and never-classified spend are EXCLUDED from the buckets and itemized in a completeness line. (Chosen over mixing the unreliable light-path labels into client buckets.)
- **D3 (Issue 3, REVISED denominator) Per-product publish gate, default 90% (configurable), low_res EXCLUDED from the denominator.** `current_pct = current_spend / (attributable_spend - low_res_spend)`. low_res is shown as its OWN "cannot classify (needs high-res re-fetch): $X" line, exactly like attribution bucket C (unattributable by design) — NOT counted as classified, NOT in the gate denominator (otherwise ~13% permanent low_res caps Martin at ~87% and it sits "pending" forever). At/above threshold: full distribution + footnote. Below: suppress percentages, show "awareness mix pending: X% classified" + $stale / $never-classified itemization + the separate low_res line. CPA, attribution coverage, unmapped worklist ALWAYS publish. Per-product; the whole digest is never withheld.
- **D4 (Issue 4) One shared awareness-currency helper.** A pure helper maps a classification row (+ current image/video version maps + the low_res-marker set) to `current | stale | low_res | unclassified`, used by BOTH the classifier staleness gate AND the digest. No duplicated rule, no classify-vs-report drift.
- **D5 (Issue 5, REVISED -> low_res only) Marker scoped to genuine low_res only.** Only the image-too-small (`low_res`) outcome gets a marker. The no-asset / transient `deep_unavailable` outcome stays an UNPERSISTED skip (retried each run), because settling it would freeze transient Gemini/parse failures forever (Codex). Martin has ~no clean no-asset image ads (98% storage coverage), so the low_res marker fixes the real churn; transient failures correctly keep retrying. Video / missing-image skips unchanged.
- **D6 (Issue 6) Bulk-prefetch, no N+1.** The digest currency check and the classifier prefetch bulk-fetch the current-version image/video analysis-id maps + the current-version low_res-marker set (mirror the classifier's Query 5/6), not per-ad. (No `downloaded_at` to fetch anymore.)

## Settling design (REVISED, marker-only)
```
analyze_image(meta_ad_id):
  _get_image -> bytes?
    no bytes (no-asset) -> return None.  classify_ad returns an UNPERSISTED
                           skipped_image_deep_unavailable (retried each run; correct
                           for transient failures, negligible for Martin @98% coverage).
    bytes, too small (low_res) -> compute input_hash(bytes);
                           _check_existing(input_hash, current prompt_version)?
                             exists -> return it (short-circuit, no re-store)
                             none   -> STORE ad_image_analysis row status='low_res',
                                       awareness NULL  (the marker)  -> return result.
                           classify_ad returns an UNPERSISTED skipped_image_low_res
                           (no ad_creative_classifications row; no consumer poisoning).

classify_batch prefetch (stops the churn WITHOUT a classification row):
  Query 7: current-version low_res markers for the batch  -> low_res_ad_set
  in the loop: if meta_ad_id in low_res_ad_set AND no current deep classification
               -> SKIP it (do not call classify_ad -> no re-download). count skipped.
  NO timestamp re-open. The marker is permanent until a FUTURE high-res re-fetch
  capability (out of scope; needs Meta perms + an asset-job re-download) deletes the
  low_res markers for re-fetched ads, which re-admits them to the to-classify loop.
```
Why marker-only (Codex): a `skipped_*` classification row with NULL awareness/format becomes the "latest classification" for `baseline_service`, `congruence_checker`, `winner_dna_analyzer`, `get_latest_classification`, `get_classification_for_run` (all read latest-per-ad with NO source filter) and corrupts them. The marker lives in `ad_image_analysis`, which those consumers never read, so it cannot poison them. The marker is NOT linked into any classification, so it cannot create a false-fresh `image_analysis_id` either.

## Completeness gate design (REVISED denominator)
```
per ad in the spend-scoped, product-attributed set:
  state = awareness_currency(genuine-latest classification row, image_vers, video_vers, low_res_set)
    current      -> contributes creative_awareness_level to the distribution
    low_res      -> "cannot classify" line; EXCLUDED from the gate denominator
    stale        -> completeness gap (old light / unlinked / old-version link); IN denominator
    unclassified -> completeness gap (no row, or NULL awareness); IN denominator

per product:
  current_pct = current_spend / (attributable_spend - low_res_spend)
  if current_pct >= threshold(default 0.90): full distribution + footnote
  else: suppress percentages, "awareness mix pending: {current_pct}%"
        + $stale / $unclassified itemization
  ALWAYS also show: "cannot classify (needs high-res re-fetch): $low_res across N ads"
  CPA, attribution coverage, unmapped worklist render regardless.
```
Currency is judged from the GENUINE latest classification row per ad (order desc, FIRST row), not the latest-row-that-has-awareness — the current code (`_product_awareness:206`) skips NULL-awareness rows and can let an OLDER stale row win (Codex). Fix that read.

## Build steps
1. **Migration:** extend `ad_image_analysis.status` CHECK to `('ok','error','low_res')`. Existing rows are all `ok` (verified) so it is non-breaking.
2. **Shared helper (D4):** `awareness_currency(row, image_versions, video_versions, low_res_set) -> state`. Refactor `_image_analysis_is_stale` to share its core. (No `image_analysis_id` link for low_res, so this helper, not a link, is what tells the classifier an ad is settled-low_res.)
3. **ImageAnalysisService (D1, low_res only):** on the low_res branch, compute `input_hash`, `_check_existing` (short-circuit if a marker exists), else STORE a `status='low_res'` marker. This is a real control-flow change (today low_res returns before `_check_existing`/`_store_result`).
4. **classify_ad:** UNCHANGED for skips (keep returning unpersisted skip classifications). No skip rows in `ad_creative_classifications`.
5. **classify_batch prefetch (D1/D6):** add Query 7 (current-version low_res markers); skip ads in that set (no current deep classification) from the to-classify loop. No `downloaded_at`. `_image_analysis_is_stale` unchanged (no skip rows reach it).
6. **Digest (D2/D3/D4/D6):** `_product_awareness` reads the genuine latest row per ad (+`image_analysis_id`,`source`); bulk-fetch the image/video version maps + the low_res-marker set; bucket via `awareness_currency`; compute per-product `current_pct` with low_res EXCLUDED from the denominator; apply the threshold gate; render the "cannot classify" line + the completeness gap. Threshold = Platform Setting (default 0.90, clamped to (0,1]).
7. **Tests (D4 + diagram).**

## Test coverage (target 100% of new paths)
- `awareness_currency`: current / stale / low_res (in low_res_set) / unclassified (unit).
- ImageAnalysisService: low_res STORES a status='low_res' marker; re-entry short-circuits via `_check_existing` (unit, mock supabase).
- classify_batch prefetch: ad in low_res_set with no current deep classification is SKIPPED (classify_ad NOT called -> no re-download); ad NOT in the set still classifies (unit).
- **REGRESSION:** a `skipped_*` classification is NEVER written for low_res / no-asset (assert no `ad_creative_classifications` insert on those paths) — guards against re-introducing consumer poisoning (unit, CRITICAL).
- digest: only-current in buckets; genuine-latest read (an older stale row never wins over a NULL-awareness newer row); low_res EXCLUDED from `current_pct` denominator; stale/unclassified in the gap (unit).
- digest gate: >=T full+footnote; <T suppress+pending; "cannot classify" line always shown; CPA/coverage/unmapped always publish (unit).
- digest_renderer completeness + cannot-classify lines (unit).
- E2E: live classify_batch — a known low_res ad gets a marker run 1, is SKIPPED with no re-download run 2; digest shows it on the "cannot classify" line and computes `current_pct` excluding it.

## Failure modes
- **low_res marker never re-opens (by design):** there is no `downloaded_at` and the asset job does not re-download, so a low_res ad stays low_res until the future re-fetch workstream clears its marker. Honest and bounded; the digest shows it on the "cannot classify" line. Failure mode only if we LATER add re-fetch and forget to clear markers — track that as a dependency of the re-fetch workstream.
- **Transient Gemini/parse failure mis-marked as low_res:** only `_image_too_small` produces low_res; transient failures return None (no marker), so they keep retrying. Test: a transient None does NOT write a marker.
- **Threshold mis-set to 0 or 1:** clamp/validate the Platform Setting to (0,1]; default 0.90.
- **Version-map prefetch empty (pre-backfill):** every image ad reads stale -> products "pending" (correct). Test the all-pending path.
- **Re-introducing skip-row poisoning:** the CRITICAL regression test asserts no `ad_creative_classifications` row is written for a skip; if a future change persists one, baselines/congruence/winner_dna/get_latest break (Codex-verified). The test is the guard.

## NOT in scope
- **low_res recovery (its own future workstream):** re-fetching the 64x64 thumbnails at higher res needs (a) Meta `pages_read_engagement` / Page Public Content Access AND (b) an asset-job change to RE-download existing `downloaded`/`not_downloadable` assets (today it excludes them via `existing_set`, `meta_ads_service.py:2284,2327`) AND (c) clearing the `status='low_res'` markers for re-fetched ads so they re-admit to classification. Until that ships, low_res ads stay on the "cannot classify" line.
- Settling no-asset / transient `deep_unavailable` skips (D5: left as unpersisted retried skips — settling them would freeze transient failures).
- Video / missing-image skip churn (separate signal, out of scope).
- The template-classifier unification (the next workstream, task #47).
- Currency-blending across markets (pre-existing tech debt).

## What already exists (reuse, do not rebuild)
- `WeeklyDigestService._product_awareness` (`weekly_digest_service.py:190-287`) — extend its read + bucketing.
- `_image_analysis_is_stale` (`classifier_service.py:935-973`) — refactor into the shared currency helper.
- `_coverage_and_unmapped` + `digest_renderer._awareness_table` — mirror for the completeness line.
- `get_spending_ad_ids` / `resolve_product_ad_ids` — ad set is already correct; no change.
- The classifier's Query 5/6 bulk-prefetch — the pattern to copy for the version + downloaded_at maps.
- Platform Settings (e.g. `MAX_ADS_PER_SCHEDULED_RUN`) — add the completeness threshold the same way.

## Worktree parallelization
- **Lane 0 (do first, shared):** the `awareness_currency` helper + its state contract (`current|stale|low_res|unclassified`) in a shared module. Both lanes import it; define it once to avoid the conflict.
- **Lane A (classifier/image):** migration (`status` CHECK) -> ImageAnalysisService low_res marker store -> classify_batch Query 7 + prefetch skip. `classify_ad` is UNCHANGED (no skip rows).
- **Lane B (digest):** `_product_awareness` genuine-latest read + version/low_res-marker prefetch + `awareness_currency` bucketing + denominator-excludes-low_res gate -> `digest_renderer` completeness + cannot-classify lines -> Platform Setting threshold.
- After Lane 0, Lane A and Lane B are largely independent (different modules: classifier/image vs digest). Merge Lane 0 first.

## Codex outside-voice revisions (2026-06-09)
Codex caught issues the inside review missed; both decisive ones were code-verified:
1. (verified) `meta_ad_assets` has only `created_at`, no `downloaded_at` -> the original timestamp re-open was non-implementable. Dropped; marker is permanent-until-refetch.
2. (verified) persisting `skipped_*`/NULL-awareness classification rows poisons `baseline_service` + `congruence_checker` + `winner_dna_analyzer` + `get_latest_classification` + `get_classification_for_run` (all read latest-per-ad, no source filter) -> flipped to marker-only (no classification row).
3. (verified) ~13% permanent low_res caps Martin at ~87% < 90% -> low_res excluded from the gate denominator (own "cannot classify" line), mirroring attribution bucket C.
4. transient `deep_unavailable` must NOT be marked low_res (would freeze transient failures) -> marker is low_res-only.
5. the asset job does not re-download existing assets -> low_res recovery is its own future workstream (NOT in scope).
6. `_product_awareness` must read the GENUINE latest row (it currently skips NULL-awareness rows, letting an older stale row win).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 13 problems; 2 code-verified fatal (no `downloaded_at` column; skip-rows poison 5 consumers) -> design flipped to marker-only + denominator-excludes-low_res |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | 8 issues across Architecture/CodeQuality/Tests/Perf; 6 decisions locked, 2 reversed after Codex; 0 unresolved, 0 open critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend; Slack text output) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | n/a |

- **CODEX:** flipped Issue 1 (skip-row -> marker-only, consumer-poisoning), fixed the gate denominator (low_res excluded), dropped a non-existent re-open column, scoped the marker to genuine low_res.
- **CROSS-MODEL:** 2 tensions, both resolved in Codex's favor after code verification (user confirmed both).
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — 6 decisions locked (D1/D3/D5 revised post-Codex), design simpler and shippable, no skip-row consumer poisoning, gate reachable for Martin.
