# SEO Content Workflow — Phase 1 Checkpoint

**Date**: 2026-03-11
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Phase 1 implementation complete, testing in progress

---

## What's Built (Steps 1-8)

### Step 1: Database Migration ✅
- `seo_brand_config` table created
- `seo_workflow_jobs` table created
- Partial unique indexes for job dedup

### Step 2: Bug Fixes ✅
- Tags sent to Shopify correctly
- Image style passthrough (3-method chain)
- `content_html` saved after publish
- `pre_write_check()` brand-wide
- `create_keyword()` added to KeywordDiscoveryService
- Dynamic search intent fix

### Step 3: SEOBrandConfigService ✅
- CRUD for brand config
- Content Guide UI in Dashboard (with author management)
- YaketyPack brand config seeded

### Step 4: PrePublishChecklistService ✅
- Validates author, images, tags, meta, uniqueness
- Text-based 3-gram Jaccard similarity for cannibalization

### Step 5: Content Generation Prompts ✅
- Phase B: em dash prohibition, no H1 title, article role context
- Phase C: inline image markers (6-8 distributed), tag selection, author bio
- Phase C CRITICAL section removed (was contradicting inline image placement)

### Step 6: ClusterResearchRegistry ✅
- Extensible source registry (GSC, manual seeds)
- AI-powered cluster analysis

### Step 7: SEOWorkflowService ✅
- `start_one_off()` — full Quick Write pipeline
- `start_cluster_batch()` — pillar + spokes + interlinking
- `regenerate_images()` — retry all images
- `regenerate_single_image()` — retry one image with custom prompt
- `get_article_images()` — load image data for UI
- `_inject_image_markers()` — scales with article length (2-7 inline)
- `_resolve_org_id()` — superuser "all" → real UUID
- ThreadPoolExecutor pattern for Streamlit thread safety
- Max 3 concurrent jobs via Semaphore

### Step 8: SEO Workflow UI ✅
- Quick Write tab with form + progress panel + recent jobs
- Cluster Builder tab with research form + cluster report
- Image management panel (per-image preview, editable prompts, regenerate)
- Publish tab with Re-publish to Shopify button
- Author metafields sent to Shopify (`article.*` namespace)
- Feature gated via FeatureKey.SEO_WORKFLOW

---

## Bugs Found & Fixed During Testing

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `invalid uuid "all"` | Superuser org_id passed to DB | `_resolve_org_id()` helper |
| `brands.positioning` doesn't exist | Wrong column name | Changed to `brands.description` |
| Phase result key `"output"` vs `"content"` | Wrong dict key | Fixed all 3 references |
| `seo_cluster_spokes` has no `keyword` column | Only has `keyword_id` FK | Join through `seo_keywords` |
| Shopify draft URL 404 | Public URL doesn't work for drafts | Return `admin_url` instead |
| Duplicate H1 | Shopify renders title as H1 | Added prompt instruction |
| `asyncio.run()` crashes in Streamlit | Streamlit has running event loop | ThreadPoolExecutor + new event loop |
| Retry images no-op | `[IMAGE:]` markers destroyed after generation | Reconstruct from metadata or H2s |
| Stats key mismatch | UI read `stats.generated` not `stats.success` | Fixed key |
| Cross-thread Supabase client | httpx.Client not thread-safe | Fresh `get_supabase_client()` in child |
| 502 HTML error dump | Raw Cloudflare HTML shown | Regex extraction of code/message |
| Stale `content_html` on re-publish | Old HTML from first publish bypassed `_markdown_to_html` | Always re-render from markdown |
| Hero image duplicated in body | Hero `<img>` in body + featured image | Strip `loading="eager"` images |
| Frontmatter visible in Shopify | Hero `<img>` prepended before `---` broke regex | `lstrip()` + `^` anchor |
| Phase C image markers at end of article | Contradicting prompt sections | Removed CRITICAL section, inline markers |
| `content_markdown` priority over `phase_c_output` | Wrong fallback order | Swapped to `phase_c_output` first |
| `_get_author_name` only returned name | No metafield data | Changed to `_get_author_data` returning full record |

---

## Testing Status

### ✅ Tested
- [x] Quick Write: keyword → pipeline runs → Shopify draft created
- [x] Retry Images: regenerates all images from H2 headings
- [x] Image management panel loads images with previews

### 🔲 Needs Testing (Test Plan Below)

#### Test 1: Re-publish existing article
1. SEO Workflow → load completed gaming channel article
2. Publish tab → Re-publish to Shopify
3. **Verify in Shopify admin:**
   - [ ] Inline images appear in article body
   - [ ] No frontmatter text visible
   - [ ] Hero image NOT duplicated in body (only featured image)
   - [ ] Author metafields set (`article.author_name`, `article.author_bio`, etc.)

#### Test 2: Single image regeneration
1. Images tab → find bad image (kid looking away from TV)
2. Edit the prompt to something more specific
3. Click Regenerate → spinner → new image appears
4. Publish tab → Re-publish → verify updated image in Shopify

#### Test 3: Full pipeline (new article)
1. Pick a new YaketyPack keyword
2. Run Quick Write
3. **Verify:**
   - [ ] 6-8 images generated (hero + 5-7 inline), distributed evenly
   - [ ] Each image has descriptive, scene-specific prompt
   - [ ] Images visible throughout Shopify article body (not just top)
   - [ ] Author = Kevin Hinton in Shopify
   - [ ] Author metafields populated
   - [ ] No frontmatter in body
   - [ ] No duplicate hero in body

#### Test 4: Content Guide
1. SEO Dashboard → Content Guide expander
2. Verify YaketyPack config is loaded (style guide, tags, image style, product rules)
3. Add/edit/delete an author
4. Verify changes persist on page reload

---

## What's Next (Steps 9-10)

### Step 9a: Dashboard Integration ✅ (already done)
- Content Guide in Dashboard settings
- Author management UI

### Step 9b: Cluster Batch UI ✅
- "Generate Cluster" button per cluster recommendation (disabled during active batch)
- `save_cluster_from_research()` persists cluster + spokes to DB before batch start
- Batch progress panel: per-article status, progress bar, current step label
- Batch completion view: per-article expanders with image management + re-publish
- Per-article Shopify draft links
- Recent Batches section with "Load" to revisit completed batches
- Fixed `asyncio.run()` crash in Streamlit (ThreadPoolExecutor pattern)
- Fixed pillar duplication: filtered pillar from spoke list in `start_cluster_batch()`

### Step 10: SEO Content Agent (Phase 2 of plan)
- Chat agent with tools wrapping workflow services
- Tools: `quick_write`, `cluster_research`, `batch_generate`, `check_status`
- Agent can answer questions about article performance, suggest next topics

---

## Files Modified This Session

| File | Key Changes |
|------|-------------|
| `services/seo_pipeline/services/seo_workflow_service.py` | `regenerate_single_image()`, `get_article_images()`, improved `_inject_image_markers()`, content priority fix, `save_cluster_from_research()`, batch progress labels, pillar dedup fix |
| `services/seo_pipeline/services/cms_publisher_service.py` | Author metafields, `_get_author_data()`, hero stripping, frontmatter fix, always re-render from markdown |
| `services/seo_pipeline/services/seo_image_service.py` | `image_style` param on `regenerate_image()` |
| `services/seo_pipeline/prompts/phase_c_optimize.txt` | Inline image markers, removed contradicting CRITICAL section |
| `ui/pages/53_🚀_SEO_Workflow.py` | Image management panel, Publish tab, per-image regen, Cluster Batch UI (progress, completion, image mgmt, recent batches) |
| `ui/pages/48_🔍_SEO_Dashboard.py` | Author management UI, missing import fix |
| `ui/nav.py` | FeatureKey.SEO_WORKFLOW registration |
| `services/feature_service.py` | SEO_WORKFLOW enum |
| `CLAUDE.md` | Rule #6: resolve "all" org_id before DB inserts |
