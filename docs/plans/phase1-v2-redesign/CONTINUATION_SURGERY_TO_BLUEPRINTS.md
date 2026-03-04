# Continuation Prompt: Surgery Pipeline → Blueprint Integration

## Context

Read the checkpoint first:
- `docs/plans/phase1-v2-redesign/CHECKPOINT_PLAYWRIGHT_CAPTURE_COMPLETE.md`

The Playwright DOM capture + surgery pipeline chrome removal is complete and working well. Surgery S0 output quality is surprisingly good (SSIM 0.68-0.85 across 3 test pages). The main remaining issue is S3 CSS scoping which regresses SSIM by 0.04-0.13 on all pages.

**Branch**: `feat/ad-creator-v2-phase0`

## Philosophy

Each step below should be validated independently. Only proceed to the next step if the current step provides **measurable, considerable improvement** in output quality. The S0 output is already quite good — don't over-engineer steps that provide marginal benefit.

After each step: run all 3 test pages, compare before/after SSIM and visual output, and get user confirmation before proceeding.

---

## Step 1: Fix S3 CSS Scoping Regression

**Problem**: Phase 3 (Gemini per-section refinement) strips global `<style>` blocks before sending section HTML to Gemini. Gemini can't see CSS class definitions and adds conflicting inline styles that destroy layout.

**Evidence**:
- InfiniteAge: S0 0.85 → S3 0.72 (-0.13)
- NordStick: S0 0.74 → S3 0.70 (-0.04)
- Boba: S0 0.68 → S3 0.63 (-0.05)

**Plan**: See `docs/plans/phase1-v2-redesign/PHASE3_ADAPTATION_PLAN.md` for the detailed approach:
1. Pass skeleton CSS context to Phase 3 prompts
2. Add CSS preservation constraints to Phase 3 prompt
3. Post-Phase-3 inline style cleanup
4. Phase 4 prompt hardening

**Acceptance criteria**:
- S3 SSIM should NOT regress from S0 (flat or improving trajectory)
- InfiniteAge S3 >= 0.80, Boba S3 >= 0.65, NordStick S3 >= 0.70
- 387+ unit tests passing

**Verification**:
```bash
# Run all 3 pages and check S0→S3 trajectory
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --playwright-dom --visual

MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --playwright-dom --visual

MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "thenordstick.com/pages/nordbench-founder-story-solve-body-pain" --playwright-dom --visual

python3 -m pytest tests/test_multipass_v4.py -x -q
```

**STOP after this step. Show user the visual comparisons and SSIM results. Only proceed if user confirms improvement is meaningful.**

---

## Step 2: Wire Playwright Capture into Production `scrape_landing_page()`

**Problem**: The Playwright DOM capture works in test mode (`--playwright-dom` flag) but isn't wired into the production `scrape_landing_page()` flow reliably. The `check_scrape_consistency()` function rejects Playwright DOMs that have more content than Firecrawl markdown (which they always will).

**What to do**:
1. Adjust `check_scrape_consistency()` to handle Playwright DOM vs Firecrawl markdown asymmetry — Playwright will always have MORE headings/content than the markdown extraction
2. Store Playwright full-page screenshot as the primary screenshot (not the truncated Firecrawl one). Use `_prepare_screenshot()` but increase the max width from 1200 to 1280 to match the render viewport
3. Add `capture_method` field to the analysis record metadata to track whether Playwright or Firecrawl was used
4. Ensure Firecrawl fallback still works cleanly when Playwright is unavailable

**Acceptance criteria**:
- `scrape_landing_page('https://thenordstick.com/...')` succeeds without manual intervention (no "Dual-scrape drift detected" rejection)
- page_html is populated from Playwright
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

**STOP after this step. Confirm the production scrape flow works end-to-end before proceeding.**

---

## Step 3: Connect Surgery Output to Blueprint/Mockup Generation

**Problem**: The surgery pipeline produces high-fidelity HTML, but the blueprint/mockup generation path doesn't use it. Currently `mockup_service.py` uses the reconstruction pipeline (which builds HTML from markdown). The surgery output is significantly better for pages with complex CSS/Shopify themes.

**What to do**:
1. Investigate the current mockup/blueprint generation flow — read `mockup_service.py` and understand how it selects between reconstruction and surgery paths
2. Add a quality gate: if surgery S4 SSIM > threshold (e.g., 0.60), prefer surgery output for the blueprint
3. The mockup service should be able to accept pre-computed surgery HTML as input (skipping reconstruction)
4. Wire this into the landing page analysis pipeline so blueprints automatically use the best available output

**Before building**: Discuss the approach with the user. The right integration point depends on how blueprints are currently consumed downstream. Don't assume — ask.

**STOP after this step. The user should validate that blueprints generated from surgery output are actually better than reconstruction output for their use case.**

---

## Important Notes

- **Don't over-engineer**: The S0 output is already surprisingly good. If S3 CSS scoping fix doesn't provide meaningful improvement, skip it and go straight to Step 2.
- **Measure everything**: Before/after SSIM, visual comparisons, and user confirmation at every step.
- **One step at a time**: Complete each step fully, commit, and get user sign-off before starting the next.
- **Feature flag**: All changes behind `MULTIPASS_PHASE1_MODE=v2` and `MULTIPASS_PIPELINE_MODE=surgery` flags. Default behavior unchanged.
- **Test pages**: Always test all 3 pages (Boba, InfiniteAge, NordStick) to catch regressions.

## Current Baseline Scores (Playwright reference screenshots)

| Page | S0 SSIM | S3 SSIM | Final SSIM | Text Fidelity |
|------|---------|---------|------------|---------------|
| InfiniteAge | 0.8512 | 0.7195 | 0.7195 | 0.84 |
| Boba | 0.6807 | 0.6301 | 0.6301 | 0.90 |
| NordStick | 0.7373 | 0.6994 | 0.6994 | 0.78 |
