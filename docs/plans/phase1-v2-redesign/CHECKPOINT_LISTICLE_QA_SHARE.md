# Checkpoint: Listicle Detection + QA Approval + Content Patterns + Public Share Links

**Date**: 2026-02-25
**Branch**: `feat/ad-creator-v2-phase0`
**Commit**: `59dc684`
**Status**: Implemented, compiled, pushed. Migrations run on Supabase.

## What Was Done

### Milestone 1: Listicle Detection + Renumbering

**Problem**: Heading slots get rewritten in separate AI batches. Each batch independently assigns numbers, producing duplicate "2." and "3." headings. The AI doesn't know what numbers other batches used.

**Solution**: Deterministic prefix detection + injection + post-processing enforcement.

#### Files Modified
- `mockup_service.py`

#### Changes
1. **`_SlotRewriteConfig`** — Added `listicle_data: Dict = field(default_factory=dict)`
2. **`_detect_listicle_structure()`** — New method with regex-based detection:
   - `_LISTICLE_PREFIX_RE`: Matches "3.", "3)", "#3", "Reason 3:", "Step 3." etc.
   - `_LISTICLE_FALSE_POSITIVE_RE`: Guards against "100% Natural", "24/7 Support", "500mg"
   - Requires 3+ heading matches (or 2 if total headings <= 3)
   - Extracts prefix style (numeric_dot, numeric_paren, hash, word_prefix, numeric_colon)
   - Extracts total count from headline text ("7 Reasons..." -> 7)
   - Returns `{prefixes: {slot_name: "3."}, total_count: 7, prefix_style: "numeric_dot"}`
3. **`_enforce_listicle_numbering()`** — Post-processing safety net:
   - Strips any leading ordinal from AI output via `_LEADING_ORDINAL_RE`
   - Prepends correct prefix from detection map
   - Double-prefix guard: checks if already correctly prefixed before stripping
4. **Prompt additions** — "Numbered Prefix Preservation" section added to `_SLOT_REWRITE_PROMPT_BASE`, prefix rule added to both regen prompts
5. **Config builders** — Both `_build_runtime_rewrite_config()` and `_build_blueprint_rewrite_config()` now detect listicle structure, inject `prefix` into slot payloads and `slot_specs_lookup`
6. **Pipeline integration**:
   - Inline prefix validation after each AI batch
   - Listicle context in `tone_summary` for batch 2+ (items written so far)
   - `prefix` field included in regen payloads for both strategies
   - `_enforce_listicle_numbering()` called after regen loop, before fallback

### Milestone 2: Content Pattern Tags

**Problem**: No way to know if an analysis is a listicle, FAQ, etc. without re-reading the classification JSONB.

**Solution**: Deterministic pattern tagging populated during `_finalize_analysis()`.

#### Files Modified
- `migrations/2026-02-25_content_pattern_tags.sql`
- `analysis_service.py`

#### Changes
1. **Migration** — Adds `content_patterns JSONB DEFAULT '{}'` and `primary_content_pattern TEXT` to `landing_page_analyses`, with GIN and btree indexes
2. **`_extract_content_patterns()`** — Static method mapping element detection patterns to tags:
   - `feature_list` (3+ items, dominant) -> `listicle`
   - `feature_list` (secondary) -> `feature_showcase`
   - `testimonial_list` -> `testimonial_grid`
   - `faq_list` -> `faq`
   - `stats_list` -> `stats_showcase`
   - Multiple patterns -> `mixed` (unless one dominates at 80%+ confidence)
3. **`_finalize_analysis()`** — Now populates `content_patterns` and `primary_content_pattern`
4. **`list_analyses()`** — Includes `qa_status` and `primary_content_pattern` in SELECT

### Milestone 3: QA Approval Status

**Problem**: Templates go from `completed` to production with no human sign-off. User wants opt-in approval workflow.

**Solution**: Non-blocking `qa_status` on both analyses and blueprints. `pending` is default and does NOT block any workflow.

#### Files Modified
- `migrations/2026-02-25_qa_approval_status.sql`
- `analysis_service.py`
- `blueprint_service.py`
- `33_🏗️_Landing_Page_Analyzer.py`

#### Changes
1. **Migration** — Adds `qa_status TEXT DEFAULT 'pending'` (CHECK: pending/approved/rejected/needs_revision), `qa_notes TEXT`, `qa_reviewed_by UUID`, `qa_reviewed_at TIMESTAMPTZ` to both `landing_page_analyses` and `landing_page_blueprints`, with partial indexes on approved status
2. **`update_qa_status()`** — Added to both `analysis_service.py` and `blueprint_service.py` with validation, timestamping
3. **`list_analyses()`/`list_blueprints()`** — Accept optional `qa_status_filter` parameter
4. **UI** — QA filter dropdown on analysis history, QA badges in row headers (✅❌🔄), `_render_qa_controls()` with Approve/Reject/Needs Revision/Reset buttons and notes input
5. **Non-blocking** — No code path refuses to use a template because `qa_status != 'approved'`

### Milestone 4: Public Share Links

**Problem**: No way to share a blueprint preview link with clients after completion.

**Solution**: Token-based unauthenticated preview endpoint.

#### Files Modified
- `migrations/2026-02-25_blueprint_share_links.sql`
- `blueprint_service.py`
- `viraltracker/api/app.py`
- `33_🏗️_Landing_Page_Analyzer.py`

#### Changes
1. **Migration** — Adds `public_share_token TEXT UNIQUE`, `public_share_enabled BOOLEAN DEFAULT FALSE`, `public_share_created_at TIMESTAMPTZ` with unique partial index on token
2. **`generate_share_link()`** — Creates or re-enables token via `secrets.token_urlsafe(9)` (12 chars)
3. **`disable_share_link()`** — Sets `public_share_enabled=False` (preserves token for re-enabling)
4. **`get_blueprint_by_share_token()`** — Fetches by token where enabled, returns HTML (prefers `blueprint_mockup_html_with_images`)
5. **FastAPI endpoint** — `GET /api/public/blueprint/{share_token}`, no auth, rate limited 100/hr, returns `HTMLResponse` wrapped in minimal HTML shell
6. **UI** — `_render_share_controls()` with Generate/Disable toggle and URL display

## Known Bugs (Discovered During Testing)

### BUG-1: Surgery pipeline drops external CSS for Webflow/CDN-hosted pages

**Severity**: HIGH
**Discovered**: Testing Hike Footwear (`offers.hike-footwear.com/o/of01`)

**Root cause**: Two issues in the CSS extraction pipeline:

1. **`_is_first_party()` too restrictive** (`html_extractor.py:789`):
   - The Webflow page at `offers.hike-footwear.com` loads its main stylesheet from `cdn.prod.website-files.com`
   - `_is_first_party()` checks exact match or subdomain match — neither applies
   - `cdn.prod.website-files.com` is not in `_CDN_DOMAINS` blocklist (it's not a generic CDN)
   - Result: The 684K Webflow layout CSS is silently skipped

2. **`CSSExtractor._parse_css()` only extracts fragments** (`html_extractor.py:231`):
   - Even if the external file were fetched, `_parse_css()` only keeps `@media`, `:root` custom properties, and `@font-face` blocks
   - Regular CSS rules (layout, sizing, typography) are discarded
   - The `external_css` passed to `CSSScoper.scope()` is just the responsive/variable subset

**Impact**: Surgery output has correct HTML structure and all content (213/213 text chunks, 100% fidelity) but looks completely different from the original because all layout rules are missing. All classes are present (343/344 match) but have no styling applied.

**Affected pages**: Any page using Webflow, or any page where the primary stylesheet is hosted on a different domain than the page itself (common with CDN-hosted sites).

**Fix needed**:
- Extend `_is_first_party()` or add a `_KNOWN_ASSET_CDNS` allowlist for Webflow, Squarespace, Wix, etc.
- Change `CSSExtractor` or add a separate path to inline the **full** external stylesheet (not just responsive fragments), with a size cap
- The `CSSScoper` already handles combining inline + external CSS and scoping under `.lp-mockup`

### BUG-2: Playwright sync/async conflict in surgery S4 visual QA

**Severity**: LOW (non-blocking — S4 is skipped gracefully)
**Message**: `HTML rendering failed: It looks like you are using Playwright Sync API inside the asyncio loop`
**Impact**: S4 visual QA patches cannot run when the pipeline is invoked from an async context. The pipeline still produces output but skips the visual quality check.

## Verification

```bash
# Syntax verification (all pass)
python3 -m py_compile viraltracker/services/landing_page_analysis/mockup_service.py
python3 -m py_compile viraltracker/services/landing_page_analysis/analysis_service.py
python3 -m py_compile viraltracker/services/landing_page_analysis/blueprint_service.py
python3 -m py_compile viraltracker/api/app.py
python3 -m py_compile "viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py"

# Live test: Hike Footwear analysis
ORG_ID="00000000-0000-0000-0000-000000000001" PYTHONPATH=. python3 scripts/run_analysis_pipeline.py "https://offers.hike-footwear.com/o/of01"
# Result: Grade B, 224s, 51 slots, 100% content fidelity
# But: visual output missing layout CSS (BUG-1)
```

## Files Changed Summary

| File | Lines Changed | Purpose |
|------|--------------|---------|
| `mockup_service.py` | +325 | Listicle detection, prefix injection, numbering enforcement |
| `analysis_service.py` | +127 | Content pattern extraction, QA status, list filtering |
| `blueprint_service.py` | +113 | QA status, share link CRUD, token-based lookup |
| `app.py` | +34 | Public blueprint preview endpoint |
| `33_🏗️_Landing_Page_Analyzer.py` | +122 | QA controls, share controls, filter UI |
| `2026-02-25_content_pattern_tags.sql` | new | content_patterns + primary_content_pattern columns |
| `2026-02-25_qa_approval_status.sql` | new | qa_status columns on analyses + blueprints |
| `2026-02-25_blueprint_share_links.sql` | new | share token columns on blueprints |
