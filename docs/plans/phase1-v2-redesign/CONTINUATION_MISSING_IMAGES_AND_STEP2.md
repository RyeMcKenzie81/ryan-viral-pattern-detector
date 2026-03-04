# Continuation Prompt: Fix Missing Images + Step 2 (Playwright Production Wiring)

## Context

Read these checkpoints first:
- `docs/plans/phase1-v2-redesign/CHECKPOINT_PLAYWRIGHT_CAPTURE_COMPLETE.md`
- `docs/plans/phase1-v2-redesign/CHECKPOINT_S3_CSS_SCOPING_FIX.md`
- `docs/plans/phase1-v2-redesign/CONTINUATION_SURGERY_TO_BLUEPRINTS.md` (for Steps 2-3)

**Branch**: `feat/ad-creator-v2-phase0`

The S3 CSS scoping fix is done. NordStick regression eliminated (S3=S0), InfiniteAge and Boba improved. But there's a remaining issue before moving to Step 2.

---

## Task A: Fix Missing Images on NordStick (Quick Fix)

**Problem**: The NordStick S3 render is missing several images compared to the original:
1. The NordBench product photo (woman using the bench) in the "That's why we built the NordBench" section — appears on the LEFT side in the original, completely absent in S3
2. Testimonial video thumbnail (man exercising) in the "We're Not Saying This Is Life-Changing" section
3. Some testimonial card profile images

**Likely causes to investigate** (in order of probability):

1. **`background-image:none !important` CSS rule in the sanitizer** — The S0 sanitized HTML contains:
   ```css
   div:not(.w3_bg), section:not(.w3_bg), iframelazy:not(.w3_bg) {background-image:none !important;}
   ```
   This strips ALL background images from divs/sections that don't have `.w3_bg` class. If the NordStick images are CSS background-images (common in Shopify themes), they'd be stripped. Check whether these missing images are `<img>` tags or CSS `background-image`.

2. **`loading="lazy"` not converted to `loading="eager"`** — The `page_capture.py` converts lazy→eager, but verify the NordStick images actually have this conversion applied.

3. **CSS `overflow:hidden` on `.lp-mockup`** clipping absolutely-positioned images — Less likely since NordStick S3=S0 SSIM, but worth checking.

**How to diagnose**:
```bash
# Check if images are <img> tags or background-image in the NordStick S0 HTML
# Look in the "That's why we built the NordBench" section
PYTHONPATH=. python3 -c "
s0 = open('test_multipass_snapshots/latest/phase_s0_sanitized.html').read()
# Search for NordBench-related image URLs
import re
for m in re.finditer(r'(nordbench|bench|transformation)', s0, re.IGNORECASE):
    ctx = s0[max(0,m.start()-200):m.end()+200]
    if 'img' in ctx.lower() or 'background' in ctx.lower() or 'src' in ctx.lower():
        print(f'...{ctx[:300]}...')
        print('---')
"

# Compare image count between S0 and S3 rendered output
# The S0 render has the images, S3 doesn't — so the images exist in the HTML
# but are being hidden by CSS
```

**Acceptance criteria**:
- The NordBench product photo visible in S3 render
- Testimonial images visible
- No regression on InfiniteAge or Boba SSIM
- 387+ unit tests passing

**STOP after this task. Show user the visual comparison. Only proceed to Step 2 if user confirms.**

---

## Task B: Step 2 — Wire Playwright Capture into Production `scrape_landing_page()`

(Only after Task A is confirmed.)

See `CONTINUATION_SURGERY_TO_BLUEPRINTS.md` Step 2 for full details. Summary:

1. Adjust `check_scrape_consistency()` to handle Playwright DOM vs Firecrawl markdown asymmetry
2. Store Playwright full-page screenshot as the primary screenshot
3. Add `capture_method` field to analysis record metadata
4. Ensure Firecrawl fallback still works

**STOP after Step 2. Confirm production scrape flow works end-to-end.**

---

## Task C: Step 3 — Connect Surgery Output to Blueprints

(Only after Step 2 is confirmed.)

See `CONTINUATION_SURGERY_TO_BLUEPRINTS.md` Step 3 for full details.

---

## Current Baseline Scores

| Page | S0 SSIM | S3 SSIM | Final SSIM | Text Fidelity |
|------|---------|---------|------------|---------------|
| NordStick | 0.7373 | **0.7373** | 0.7373 | 0.78 |
| InfiniteAge | 0.8512 | **0.7408** | 0.7408 | 0.84 |
| Boba | 0.6807 | **0.6366** | 0.6366 | 0.90 |

## Verification Commands

```bash
# Run all 3 pages after each change
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
