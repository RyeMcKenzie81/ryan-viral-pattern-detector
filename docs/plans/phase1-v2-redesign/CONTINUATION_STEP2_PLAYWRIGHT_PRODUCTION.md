# Continuation Prompt: Step 2 — Wire Playwright Capture into Production

## Context

Read these checkpoints first:
- `docs/plans/phase1-v2-redesign/CHECKPOINT_PLAYWRIGHT_CAPTURE_COMPLETE.md`
- `docs/plans/phase1-v2-redesign/CHECKPOINT_S3_CSS_SCOPING_FIX.md`
- `docs/plans/phase1-v2-redesign/CHECKPOINT_VIDEO_IFRAME_PRESERVATION.md`
- `docs/plans/phase1-v2-redesign/CONTINUATION_SURGERY_TO_BLUEPRINTS.md` (for Steps 2-3 details)

**Branch**: `feat/ad-creator-v2-phase0`

The surgery pipeline S0 sanitizer is now feature-complete:
- Playwright DOM capture with chrome/overlay removal
- S3 CSS scoping (no regression from S0)
- Video elements → poster images or gray placeholders
- YouTube iframes → visible thumbnails with semantic data
- All other iframes → labeled placeholders with semantic data

---

## Task: Step 2 — Wire Playwright Capture into Production `scrape_landing_page()`

See `CONTINUATION_SURGERY_TO_BLUEPRINTS.md` Step 2 for full context.

**Problem**: Playwright DOM capture works in test mode (`--playwright-dom` flag) but isn't wired into the production `scrape_landing_page()` flow. The `check_scrape_consistency()` function rejects Playwright DOMs that have more content than Firecrawl markdown (which they always will, since Playwright captures the full rendered DOM).

**What to do**:

1. **Adjust `check_scrape_consistency()`** — The current consistency check compares heading counts between Firecrawl markdown and Playwright HTML. Playwright will always have MORE headings/content than markdown extraction. Either:
   - Skip the consistency check when Playwright is the primary source
   - Adjust thresholds to account for the asymmetry
   - Only check consistency when both sources exist and use the richer one

2. **Store Playwright full-page screenshot** as the primary screenshot. Use `_prepare_screenshot()` but increase max width from 1200 to 1280 to match the render viewport.

3. **Add `capture_method` field** to the analysis record metadata to track whether Playwright or Firecrawl was used.

4. **Ensure Firecrawl fallback** still works cleanly when Playwright is unavailable (import failure, timeout, bot detection).

**Key files to investigate**:
- `viraltracker/services/landing_page_analysis/analysis_service.py` — `scrape_landing_page()` and `check_scrape_consistency()`
- `viraltracker/services/landing_page_analysis/page_capture.py` — Playwright capture (already working)

**Acceptance criteria**:
- `scrape_landing_page('https://thenordstick.com/...')` succeeds without manual intervention
- `page_html` is populated from Playwright DOM
- Screenshot is full-page (not truncated)
- Firecrawl-only path still works (mock Playwright import failure)
- No regression on existing test pages

**Verification**:
```bash
# Test the full scrape flow
PYTHONPATH=. python3 -c "
import logging; logging.basicConfig(level=logging.INFO)
from viraltracker.services.landing_page_analysis.analysis_service import LandingPageAnalysisService
svc = LandingPageAnalysisService()
result = svc.scrape_landing_page('https://thenordstick.com/pages/nordbench-founder-story-solve-body-pain')
print(f'markdown: {len(result.get(\"page_markdown\", \"\") or \"\"):,}')
print(f'html: {len(result.get(\"page_html\", \"\") or \"\"):,}')
print(f'screenshot: {result.get(\"screenshot_storage_path\", \"none\")}')
"
```

**STOP after Step 2. Confirm production scrape flow works end-to-end. Only proceed to Step 3 (connect surgery output to blueprints) if user confirms.**

---

## Step 3 Preview: Connect Surgery Output to Blueprints

(Only after Step 2 is confirmed.)

See `CONTINUATION_SURGERY_TO_BLUEPRINTS.md` Step 3 for full details. Summary:
1. Investigate mockup/blueprint generation flow in `mockup_service.py`
2. Add quality gate: if surgery S4 SSIM > threshold, prefer surgery output
3. Wire into landing page analysis pipeline
4. **Discuss approach with user before building** — integration point depends on downstream usage

---

## Current Baseline Scores

| Page | S0 SSIM | S3 SSIM | Final SSIM | Text Fidelity |
|------|---------|---------|------------|---------------|
| NordStick | 0.7245 | **0.7245** | 0.7245 | 0.78 |
| InfiniteAge | 0.8512 | **0.7408** | 0.7408 | 0.84 |
| Boba | 0.6807 | **0.6366** | 0.6366 | 0.90 |

## Regression Thresholds

| Metric | Floor | Notes |
|--------|-------|-------|
| NordStick S3 SSIM | >= 0.72 | YouTube thumbnails add content not in reference |
| InfiniteAge S3 SSIM | >= 0.74 | |
| Boba S3 SSIM | >= 0.63 | |
| Unit tests | 387 pass | |

## Verification Commands

```bash
# Run all 3 test pages
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "thenordstick.com/pages/nordbench-founder-story-solve-body-pain" --playwright-dom --visual

MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --playwright-dom --visual

MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --playwright-dom --visual

python3 -m pytest tests/test_multipass_v4.py -x -q
```
