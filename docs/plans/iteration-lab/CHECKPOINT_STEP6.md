# Checkpoint: Step 6 - Winner Blueprint: gallery + notable + cohort + replicate button

## Status: COMPLETE

## What Was Done

### Service (`winner_dna_analyzer.py`)
- Added 4 new fields to `CrossWinnerAnalysis` dataclass:
  - `notable_elements: Dict[str, Any]` — 25-49% frequency elements
  - `notable_visual_traits: Dict[str, Any]` — 25-49% frequency visual traits
  - `cohort_summary: Dict[str, Any]` — avg ROAS, CTR range, total spend, avg CPA
  - `winner_thumbnails: List[Dict]` — thumbnails from winner ads
- Added 4 new methods:
  - `_find_notable_elements()` — sub-threshold elements (25-49%, capped at 5)
  - `_find_notable_visual_traits()` — sub-threshold visuals (25-49%, capped at 5)
  - `_collect_winner_thumbnails()` — gathers thumbnail_url, meta_ad_id, roas, ad_name
  - `_compute_cohort_summary()` — avg ROAS, CTR range, total spend, avg CPA using statistics module
- Updated `analyze_cross_winners()` to call all new methods and pass results to `CrossWinnerAnalysis`

### UI (`38_Iteration_Lab.py`)
- Updated session state serialization with 4 new fields
- Added cohort performance summary (4 metric columns) above the Blueprint
- Added winner thumbnail gallery (up to 6 thumbnails with ROAS labels)
- Added "Also Notable" section (25-49% frequency elements/visuals)
- Added "Replicate Winner DNA" button:
  - Winner selector from thumbnail gallery
  - Product selector
  - Pre-filled editable instructions from blueprint via `_blueprint_to_instructions()`
  - Number of variations selector
  - Creates one-time `ad_creation_v2` scheduled job with `recreate_template` mode
  - Auto-imports winning ad via `MetaWinnerImportService` if needed
  - `scraped_template_ids` as top-level column (not in parameters JSONB)
  - No `organization_id` on `scheduled_jobs` (column doesn't exist)

### New functions added to UI:
- `_blueprint_to_instructions()` — converts blueprint dict to human-readable text
- `_render_replicate_button()` — renders the replicate confirmation section
- `_execute_replication()` — creates the scheduled job

## QA Blockers Addressed
- `MetaWinnerImportService()` called with 0 args (correct)
- `scraped_template_ids` as top-level column on `scheduled_jobs`
- No `organization_id` in job_row
- Private methods accessed through detector instance (`detector._find_generated_ad()`)
- No bogus `reference_ad_filename` query

## Files Changed
- `viraltracker/services/winner_dna_analyzer.py` — dataclass, `analyze_cross_winners()`, 4 new methods
- `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` — `_render_cross_winner()`, session serialization, 3 new functions

## QA
- `python3 -m py_compile` passes for both files
