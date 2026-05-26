# Asset Tagging for Ad Creator V2

## Why this exists

Ad Creator V2 scores templates against the actual visual assets you've uploaded for each product. A template that needs a bottle shot and a vet portrait will score higher for a product that has those assets tagged correctly.

If your product images aren't tagged, the matching system has nothing to score against, the effective template pool collapses (often to ~14% of total templates), and the readiness check on the V2 page flags it as a warning.

This doc covers the three ways to tag product images and the vocabulary they use.

## The vocabulary

All tags are free-form strings stored as a JSONB array on `product_images.asset_tags`. The matching system intersects these with `scraped_templates.required_assets` (and `optional_assets`). The canonical vocabulary lives in `viraltracker/services/template_element_service.py`.

### Product form factor

Pick what visibly appears in the image:

| Tag | Use when the image shows |
|---|---|
| `product:bottle` | Bottle, jar with screw lid, dropper, spray |
| `product:jar` | Wide-mouth jar (cream, powder jar) |
| `product:bag` | Pouch, stand-up bag, sachet |
| `product:box` | Carton, blister-pack box, retail packaging |
| `product:tube` | Squeeze tube |
| `product:container` | Other container that doesn't fit above |
| `product:supplements` | Loose capsules, tablets, softgels visible |
| `product:capsules` | Capsule-form supplement specifically |
| `product:powder` | Loose powder visible (in a scoop, spilled, etc.) |

### People

Only if a person is clearly visible:

| Tag | Use when the image shows |
|---|---|
| `person:man` | Adult man |
| `person:woman` | Adult woman |
| `person:vet` | Person in vet attire or setting |
| `person:athlete` | Person in athletic / gym context |
| `person:expert` | Person in lab coat or professional setting |

### Other

| Tag | Use when the image shows |
|---|---|
| `logo` | Pure logo or logo-dominant image |
| `lifestyle` | In-use shot, real environment, not isolated packshot |
| `packaging` | Packaging-focused image (label readability, retail-shelf feel) |
| `ingredients` | Raw ingredients visible (herbs, fruit, powder pile) |

### Custom tags

You can write any string you want via the custom-tag input. Use only when none of the canonical tags fit. Be aware that template matching will only fire if the template's `required_assets` includes the same custom string, so custom tags are usually low-leverage.

## Three ways to tag

All live in **Brand Manager → Product → Images tab**.

### 1. Per-image manual editor

Each image card has a `🏷️ Tags (N)` expander. Open it, pick from the multi-select, optionally add a custom tag, hit Save.

Best for:
- Correcting a single image that the AI got wrong
- Adding a one-off tag
- Tagging when you only have 1-2 images

### 2. Bulk manual editor (apply to many at once)

Above the image grid: `🏷️ Tag all images (N)` expander. Pick tags, choose:

- **Mode:** Add to existing (safe default) or Replace existing (destructive, requires confirmation)
- **Scope:** All images, or Only untagged images

Click Apply. Works in a single batched UPDATE for Replace, or per-image with union logic for Add.

Best for:
- A product with 12 photos that all show the same bottle
- Backfilling a tag you forgot earlier (Add mode, all images)
- Resetting a tag set after a vocabulary change (Replace mode)

### 3. AI auto-tag with Gemini

Above the image grid, next to the Analyze All button: `🤖 Auto-tag with AI (N untagged)` button.

Runs a focused Gemini Vision call on each untagged image, asking only for the asset_tags list. Cheaper and faster than the full image analysis.

Best for:
- New brand onboarding: tag everything in one click
- SAVAGE-style scenarios where you have 10-20 images and you don't want to think about them

The AI call uses `gemini-flash-latest` (Google's rolling alias to the latest stable Flash model). Constrained by prompt to the canonical vocabulary above. Gemini is explicitly told:

- Pick tags by what's visibly in the image, not what it infers from context
- Return an empty array if nothing fits
- Don't invent tags outside the vocabulary
- Combine tags when both apply (e.g., bottle with visible capsules: `["product:bottle", "product:capsules"]`)

After auto-tag completes, spot-check the results via the per-image editor and correct anything Gemini got wrong.

### Bonus: full Analyze All also tags

The existing **🔍 Analyze All** button (which runs the full image analysis Gemini call for quality scoring, lighting, background detection, etc.) also fills in asset_tags as a side effect. So re-analyzing an image gets you both the quality metrics and the tags in one call.

If asset tags are all you need, the dedicated 🤖 Auto-tag button is cheaper because the prompt is smaller and Gemini doesn't generate the full analysis JSON.

## How the matching works

When you run Ad Creator V2 for a product:

1. `template_scoring_service.prefetch_product_asset_tags(product_id)` does one SELECT to `product_images.asset_tags` for that product and returns the union of all tags.
2. The scoring loop intersects that set with each candidate template's `required_assets` and `optional_assets`.
3. Templates whose `required_assets` are fully covered get full match credit. Partial matches get partial credit. Missing required assets reduce the template's effective score.
4. The readiness check (`ad_creator_readiness_service._check_asset_tags`) reports the effective pool as: how many templates have all their `required_assets` covered by your product's tags. Plus templates with no required_assets (which always match).

So tagging more images, accurately, expands the effective pool which means more template variety which means less repetition in your generated ads.

## File reference

| Concern | File |
|---|---|
| Vocabulary source of truth | `viraltracker/services/template_element_service.py` |
| Per-image and bulk manual editors | `viraltracker/ui/pages/02_🏢_Brand_Manager.py` |
| AI auto-tag (focused prompt) | `viraltracker/ui/pages/02_🏢_Brand_Manager.py:gemini_infer_asset_tags` |
| Full image analysis (also writes tags) | `viraltracker/agent/agents/ad_creation_agent.py:analyze_product_image` |
| Scoring + matching | `viraltracker/services/template_scoring_service.py` |
| Readiness check | `viraltracker/services/ad_creator_readiness_service.py:_check_asset_tags` |
| DB migration that added the column | `migrations/2026-01-21_template_element_detection.sql` |

## Related PRs

- #205 per-image manual tag editor
- #206 bulk manual tag editor (apply same tags to many images)
- #207 AI auto-tag via Gemini, full Analyze All now also tags

## Troubleshooting

**"Effective pool 14%" on a brand that already has tags.**
The query may be stale. Refresh the page. If it persists, check `product_images.asset_tags` directly in Supabase to confirm the array isn't empty.

**Auto-tag returned an empty list for every image.**
Gemini returned `{"asset_tags": []}` for those images, meaning nothing in the canonical vocabulary visibly fit. Likely candidates: very abstract brand graphics, screenshots, charts. Tag these manually if they should match a template.

**My custom tag doesn't seem to do anything.**
The matching system is set-intersection on exact strings. If no template has the custom string in its `required_assets`, the custom tag won't widen the pool. Check `scraped_templates.required_assets` for what's actually being matched against.
