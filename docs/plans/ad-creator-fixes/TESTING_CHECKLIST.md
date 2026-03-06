# Ad Creator Batch Fixes - Testing Checklist

## Manual Testing (UI Verification)

### Fix 1: Scheduler Time Display
- [ ] Schedule a job, verify displayed time matches input time (PST)
- [ ] Check job list view AND detail view show same time
- [ ] Verify DST handling (`%Z` shows PDT during daylight savings)
- [ ] Check run history timestamps show PST/PDT

### Fix 2: Smart Edit Ratio
- [ ] Smart edit a 4:5 ad -> result is 4:5, not 1:1
- [ ] Smart edit a 9:16 ad -> result is 9:16
- [ ] Smart edit a 1:1 ad -> still works (no regression)
- [ ] Legacy ad with no prompt_spec -> falls back to 1:1 with warning in logs
- [ ] Verify info box shows correct ratio in Smart Edit modal

### Fix 3: Listicle LP Number Matching
- [ ] Create ad from listicle LP (e.g., "7 ways to...") -> ad uses exactly 7
- [ ] Create ad from non-listicle LP -> no listicle constraint applied
- [ ] Create ad without blueprint -> no change in behavior
- [ ] Edge case: LP has no content_patterns data -> graceful fallback (null listicle_count)

### Fix 4: Guarantee Hallucination
- [ ] Brand WITH guarantee -> ad copy may reference it
- [ ] Brand WITHOUT guarantee -> ad copy must NOT mention guarantees
- [ ] USP containing word "guarantee" but no product.guarantee field -> no guarantee claim
- [ ] Verify Brand Manager guarantee field has help text tooltip

### Fix 5: V2 "View Results"
- [ ] Verify existing V2 runs show up in "View Results" (backfill worked)
- [ ] Create new V2 ad -> verify `source_scraped_template_id` populated in DB
- [ ] Open "View Results" -> summary stats show real numbers
- [ ] Verify ads can be grouped/filtered by template
- [ ] Test status filter, date range, pagination
- [ ] Test that runs without templates (NULL) still appear (left join)

### Fix 6: Template Sorting
- [ ] Brand dropdown populates with distinct source brand names
- [ ] Brand filter narrows templates correctly
- [ ] "All" shows everything
- [ ] Sort by newest/oldest changes visual order
- [ ] Combined filters work (brand + sort + category)
- [ ] Pagination resets on filter change

### Fix 8: Manual Template Upload
- [ ] Upload single PNG -> appears in Pending Review tab
- [ ] Upload multiple files -> progress bar + all appear
- [ ] Auto-approve -> template goes directly to library + warning shown
- [ ] AI analysis -> suggestions populate review form
- [ ] Without AI -> plain queue entry (no crash)
- [ ] Verify JPG, WEBP formats work
- [ ] Verify no crash when Facebook metadata is NULL (manual upload path)

---

## Unit Tests Needed (from Post-Plan Review)

### tests/services/test_template_queue_service.py

1. `test_add_manual_template_queued`:
   - Mock: `supabase.storage.from_().upload()`, `supabase.table().insert()`
   - Setup: Provide image bytes + filename
   - Assert: Returns dict with `asset_id`, `queue_id`, `status="queued"`
   - Assert: `scraped_ad_assets` insert has `scrape_source="manual_upload"`, no `facebook_ad_id`

2. `test_add_manual_template_auto_approved`:
   - Mock: Same + `start_approval()`, `finalize_approval()`
   - Assert: Returns `template_id`, `status="auto_approved"`

3. `test_get_templates_source_brand_filter`:
   - Mock: `supabase.table().select().eq().ilike().order().limit().execute()`
   - Assert: `ilike("source_brand", "%Test Brand%")` called

4. `test_get_templates_sort_by_newest`:
   - Mock: `supabase.table().select().eq().order().limit().execute()`
   - Assert: `.order("created_at", desc=True)` called

5. `test_get_source_brands`:
   - Mock: Return 3 records with distinct `source_brand` values
   - Assert: Returns sorted unique list

### tests/services/test_ad_creation_service.py

6. `test_create_ad_run_with_source_template_id`:
   - Mock: `supabase.table().insert().execute()`
   - Assert: Insert data includes `source_scraped_template_id`

7. `test_create_edited_ad_dimension_fallback_explicit_dims`:
   - Setup: `prompt_spec.canvas.dimensions = "1080x1350"`
   - Assert: dimensions = "1080x1350"

8. `test_create_edited_ad_dimension_fallback_aspect_ratio`:
   - Setup: `prompt_spec.canvas.aspect_ratio = "4:5"`, no dimensions
   - Assert: dimensions = "1080x1350"

9. `test_create_edited_ad_dimension_fallback_variant_size`:
   - Setup: No canvas data, `source_ad.variant_size = "9:16"`
   - Assert: dimensions = "1080x1920"

10. `test_create_edited_ad_dimension_fallback_default`:
    - Setup: No canvas, no variant_size
    - Assert: dimensions = "1080x1080", logger.warning called

### tests/pipelines/ad_creation_v2/test_content_service.py

11. `test_get_listicle_count_found`:
    - Mock: `get_supabase_client().table().select().eq().order().limit().execute()` returns content_patterns with `listicle_item_count: 7`
    - Assert: Returns 7

12. `test_get_listicle_count_not_found`:
    - Mock: Return empty result
    - Assert: Returns None

13. `test_generate_benefit_variations_guarantee_in_prompt`:
    - Mock: Claude API call, capture prompt text
    - Setup: `product["guarantee"] = "365-day money-back guarantee"`
    - Assert: Prompt contains "VERIFIED GUARANTEE"

14. `test_generate_benefit_variations_no_guarantee_in_prompt`:
    - Mock: Claude API call, capture prompt text
    - Setup: `product["guarantee"] = None`
    - Assert: Prompt contains "NO verified guarantee"

15. `test_usp_filter_keeps_guarantee`:
    - Test that USPs containing "guarantee" are no longer classified as technical_specs
    - Assert: "100% satisfaction guarantee" stays in `emotional_usps`

### tests/pipelines/ad_creation_v2/test_select_content_node.py

16. `test_listicle_count_extracted_from_blueprint`:
    - Mock: `AdContentService.get_listicle_count` returns 7
    - Setup: `state.blueprint_context = {"source_url": "https://example.com"}`
    - Assert: `state.blueprint_context["listicle_count"] == 7` after run

### tests/pipelines/ad_creation_v2/test_initialize_node.py

17. `test_source_scraped_template_id_passed`:
    - Mock: `ctx.deps.ad_creation.create_ad_run`
    - Setup: `state.template_id = "some-uuid"`
    - Assert: `create_ad_run` called with `source_scraped_template_id=UUID("some-uuid")`
