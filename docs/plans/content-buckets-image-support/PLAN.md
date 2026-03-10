# Workflow Plan: Content Buckets — Image Support + Drive Import

**Branch**: `feature/content-buckets-image-support`
**Created**: 2026-03-09
**Status**: Phase 3 — Reviewed by QA, UX, DBA, SWE agents. Ready for Phase 4.

---

## Phase 1: INTAKE

### 1.1 Original Request

> Add image support to the Video Buckets tool. User wants to upload both images
> and videos simultaneously, with the system detecting file type and routing to
> the appropriate analyzer. Also rename everything from "Video Buckets" to
> "Content Buckets".
>
> **Addition (2026-03-09):** Also add the ability to import files from Google Drive
> for analysis, using the existing `GoogleDriveService`. Browse folders, pick files,
> download and run through the same analyze → categorize pipeline.

### 1.2 Clarifying Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | What is the desired end result? | Upload images + videos together; system auto-detects type and routes to appropriate Gemini analyzer; categorizes into buckets same as before |
| 2 | Who/what triggers this? | UI button on Streamlit Content Buckets page ("Analyze & Categorize") |
| 3 | What inputs are required? | Mixed batch of image + video files (up to 30) |
| 4 | What outputs are expected? | Same as today: bucket assignment, confidence, reasoning, summary per file |
| 5 | Error cases to handle? | Unsupported file types, Gemini image analysis failures, mixed batch partial failures |
| 6 | Should this be chat-routable? | No — UI-only feature |
| 7 | Rename scope? | Full rename: UI page, DB table, feature display labels. Keep `video_buckets` feature key in DB for backward compat. |
| 8 | DB schema change? | Add `media_type TEXT DEFAULT 'video'` column to categorizations table |
| 9 | Image analysis fields? | Parallel set: text_overlays, summary, visual_elements, dominant_colors, cta_text, pain_points, benefits, solution, tone, format_type, key_themes |
| 10 | Google Drive import? | Yes — browse folders, pick files, download and analyze. Same pipeline, different input source. |
| 11 | Drive OAuth scope? | Expand to `drive.file` + `drive.readonly` (both). Users re-authorize once. Keeps upload working + adds browse/download. |
| 12 | Drive import UX? | Folder browser + file picker in the "Categorize Content" tab. Connect button if not connected. |

### 1.3 Desired Outcome

**User Story**: As a media buyer, I want to upload both images and videos in the same batch so that all my ad creatives get sorted into content buckets without needing separate workflows.

**Success Criteria**:
- [ ] Can upload images (jpg, jpeg, png, webp, gif) and videos (mp4, mov, avi, webm, mpeg) in the same batch
- [ ] System auto-detects file type and routes to the correct analyzer
- [ ] Image analysis extracts visual elements, text overlays, tone, themes (no transcript/hook)
- [ ] Categorization into buckets works identically for both media types
- [ ] `media_type` column stored in DB for filtering/reporting
- [ ] Page renamed from "Video Buckets" to "Content Buckets" everywhere in UI
- [ ] DB table renamed from `video_bucket_categorizations` to `content_bucket_categorizations`
- [ ] Existing data preserved with `media_type = 'video'` default
- [ ] Can import files from Google Drive via folder browser + file picker
- [ ] Drive OAuth scope expanded to include `drive.readonly` for browsing
- [ ] Drive-imported files go through same analysis pipeline as uploads

---

## Phase 2: ARCHITECTURE DECISION

**Chosen**: Python workflow (direct service calls)

| Question | Answer |
|----------|--------|
| Who decides what happens next - AI or user? | User (clicks "Analyze & Categorize") |
| Autonomous or interactive? | Interactive — user uploads, clicks button, views results |
| Needs pause/resume capability? | No — runs synchronously per batch |
| Complex branching logic? | No — simple if/else on file type |

### High-Level Flow

**Path A: Local Upload**
```
User uploads mixed files (images + videos)
    ↓
Click "Analyze & Categorize"
    ↓
For each file:
    ├── _detect_media_type(filename, mime_type)
    ├── if VIDEO → analyze_video() [Gemini Files API, upload + poll]
    └── if IMAGE → analyze_image() [Gemini inline via PIL, no upload]
    ↓
categorize_content() [text-only Gemini call, media-agnostic]
    ↓
Save to DB with media_type column
    ↓
Display results (with media type indicator)
```

**Path B: Google Drive Import**
```
User connects Google Drive (OAuth, one-time)
    ↓
Browse folders → select folder → see file list
    ↓
Pick files (checkboxes) → click "Import & Categorize"
    ↓
For each selected file:
    ├── download_file() from Drive API
    ├── _detect_media_type(filename, mime_type)
    ├── route to analyze_video() or analyze_image()
    └── categorize_content()
    ↓
Save to DB with media_type + source='google_drive'
    ↓
Display results (same as Path A)
```

### Key Design Decisions

1. **Image analysis uses Gemini inline** via PIL Image (proven pattern in codebase).
   No Files API upload/polling. ~2-3s vs ~12s for video.

2. **Unified `summary` field** — Both analysis prompts return `summary` (not
   `video_summary`/`image_summary`). DB column renamed from `video_summary` to `summary`.
   Eliminates silent field-name mismatch in categorization step.

3. **Media-agnostic categorization prompt** — `CATEGORIZATION_PROMPT_TEMPLATE` updated to
   say "content categorizer" (not "video content categorizer"). Conditionally includes
   transcript/hook only when present.

4. **Conditional rate-limit delay** — 7s between videos (Gemini Files API), 2s between
   images (inline call). Saves ~3.5 min on a 30-image batch.

5. **Feature key stays `video_buckets`** in DB to avoid migrating `org_features` rows.
   Only display labels change to "Content Buckets".

6. **Drive OAuth scope already sufficient** — Scope is already `drive` (full access)
   from the recent Ad Export rework. No scope change or re-authorization needed.

7. **Reuse `drive_picker.py`** — The folder picker component (browse/search/paste-URL,
   breadcrumbs, recents, caching) is fully reusable. Just change the `prefix` and `label`.

8. **Drive import reuses the same batch pipeline** — Downloaded bytes are fed into
   `analyze_and_categorize_batch()` exactly like local uploads. No separate code path
   for analysis/categorization.

9. **Drive export from Results** — After categorization, users can upload results to
   Drive organized by bucket (auto-creates per-bucket subfolders). Reuses existing
   `upload_file_bytes()` + `get_or_create_folder()`.

10. **`source` column** — Add `source TEXT DEFAULT 'upload'` to `content_bucket_categorizations`
    to distinguish locally uploaded files (`upload`) from Drive imports (`google_drive`).
    Useful for traceability but doesn't change pipeline behavior.

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components to Reuse

| Component | Type | Location | How We'll Use It |
|-----------|------|----------|------------------|
| ContentBucketService | Service | `services/content_bucket_service.py` | Extend with `analyze_image()` + media type detection |
| GoogleDriveService | Service | `services/google_drive_service.py` | Extend with `list_files()` + `download_file()` for import. Upload methods already exist for export. |
| google_oauth_utils | Utility | `services/google_oauth_utils.py` | Reuse as-is for token refresh, state encoding |
| drive_picker.py | UI component | `ui/drive_picker.py` | Reuse `render_drive_folder_picker()` directly — browse/search/paste-URL, breadcrumbs, recents, caching |
| Content Buckets page | UI | `ui/pages/37_📦_Video_Buckets.py` | Rename + expand file types + update labels + add Drive import/export UI |
| Ad Export OAuth pattern | UI pattern | `ui/pages/225_Ad_Export.py` | Copy OAuth callback handler + connect/disconnect button pattern |
| Gemini client | Library | `google.genai` | Already used for video; reuse for image inline |
| PIL Image pattern | Library | `gemini_service.py:818` | Proven pattern for inline image analysis |

### 3.2 Database Evaluation

**Existing Tables to Modify**:

| Table | Change |
|-------|--------|
| `video_bucket_categorizations` | Rename to `content_bucket_categorizations`, add `media_type` + `source` columns, rename `video_summary` to `summary` |

**Schema Check**:
- [x] `content_bucket_categorizations` does not exist yet (no collision)
- [x] `content_buckets` table already uses generic name (no change needed)
- [x] Indexes need renaming to match new table name
- [x] CHECK constraint name needs renaming
- [x] No RLS policies on this table (verified via grep)
- [x] No Supabase views or functions reference this table

**New Columns**:

| Column | Table | Type | Default | Purpose |
|--------|-------|------|---------|---------|
| `media_type` | `content_bucket_categorizations` | `TEXT NOT NULL` | `'video'` | Distinguish image vs video |
| `source` | `content_bucket_categorizations` | `TEXT NOT NULL` | `'upload'` | Track origin: `upload` or `google_drive` |

### 3.3 Files to Modify (Complete List)

| File | Changes |
|------|---------|
| `migrations/2026-03-09_rename_content_buckets.sql` | Rename table, add `media_type` + `source` w/ CHECK, rename `video_summary` → `summary`, rename indexes + constraints |
| `viraltracker/services/content_bucket_service.py` | Add `analyze_image()`, `_detect_media_type()`, `IMAGE_ANALYSIS_PROMPT`; rename `categorize_video()` → `categorize_content()`; make categorization prompt media-agnostic; conditional delay; update 7 table refs; update field names; add `source` to DB inserts |
| `viraltracker/services/google_drive_service.py` | Add `list_files()` and `download_file()` methods (scope already `drive`, no change needed) |
| `viraltracker/ui/pages/37_📦_Video_Buckets.py` | Rename to `37_📦_Content_Buckets.py`; expand file types; update ALL 70+ "video" strings; add image types to retry uploader; fix MIME fallback; smarter time estimate; conditional progress messages; add Drive import + export UI sections |
| `viraltracker/ui/nav.py` | Update page path + title |
| `viraltracker/ui/pages/69_🔧_Admin.py` | Update display label to "Content Buckets" |
| `tests/services/test_content_bucket_service.py` | Update 5 table name assertions; add tests for `analyze_image()`, `_detect_media_type()`, mixed batch |
| `tests/test_google_drive_service.py` | Add tests for `list_files()`, `download_file()`, expanded scope |
| `docs/VIDEO_BUCKETS.md` | Rename to `CONTENT_BUCKETS.md`, update content |

---

## Phase 4: BUILD

### 4.1 Build Order

1. [ ] DB migration
2. [ ] Service changes (ContentBucketService)
3. [ ] Google Drive service additions
4. [ ] UI page rename + updates + Drive import UI
5. [ ] Nav/Admin refs
6. [ ] Test updates (both services)
7. [ ] Doc updates

### 4.2 Component Details

#### Component 1: DB Migration

**File**: `migrations/2026-03-09_rename_content_buckets.sql`

```sql
BEGIN;

-- 1. Rename table
ALTER TABLE video_bucket_categorizations
  RENAME TO content_bucket_categorizations;

-- 2. Rename column: video_summary → summary
ALTER TABLE content_bucket_categorizations
  RENAME COLUMN video_summary TO summary;

-- 3. Add media_type column with CHECK constraint
ALTER TABLE content_bucket_categorizations
  ADD COLUMN IF NOT EXISTS media_type TEXT NOT NULL DEFAULT 'video';

ALTER TABLE content_bucket_categorizations
  ADD CONSTRAINT content_bucket_categorizations_media_type_check
  CHECK (media_type IN ('image', 'video'));

-- 4. Add source column (upload vs google_drive)
ALTER TABLE content_bucket_categorizations
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'upload';

ALTER TABLE content_bucket_categorizations
  ADD CONSTRAINT content_bucket_categorizations_source_check
  CHECK (source IN ('upload', 'google_drive'));

-- 5. Rename indexes
ALTER INDEX IF EXISTS idx_video_bucket_cat_session
  RENAME TO idx_content_bucket_cat_session;
ALTER INDEX IF EXISTS idx_video_bucket_cat_product_org
  RENAME TO idx_content_bucket_cat_product_org;
ALTER INDEX IF EXISTS idx_video_bucket_cat_uploaded
  RENAME TO idx_content_bucket_cat_uploaded;

-- 6. Rename CHECK constraint on status column
-- (Verify actual name with: SELECT conname FROM pg_constraint WHERE conrelid = 'content_bucket_categorizations'::regclass;)
ALTER TABLE content_bucket_categorizations
  RENAME CONSTRAINT video_bucket_categorizations_status_check
  TO content_bucket_categorizations_status_check;

-- 7. Update comments
COMMENT ON TABLE content_bucket_categorizations
  IS 'Per-file (image or video) analysis results and bucket assignments from Gemini.';
COMMENT ON COLUMN content_bucket_categorizations.media_type
  IS 'Type of media: image or video.';
COMMENT ON COLUMN content_bucket_categorizations.summary
  IS 'Content summary from Gemini analysis (was video_summary).';
COMMENT ON COLUMN content_bucket_categorizations.source
  IS 'Origin of the file: upload (local) or google_drive (imported).';

COMMIT;
```

**Rollback script** (save as `migrations/2026-03-09_rename_content_buckets_ROLLBACK.sql`):
```sql
BEGIN;
ALTER TABLE content_bucket_categorizations DROP COLUMN IF EXISTS source;
ALTER TABLE content_bucket_categorizations DROP COLUMN IF EXISTS media_type;
ALTER TABLE content_bucket_categorizations RENAME COLUMN summary TO video_summary;
ALTER INDEX IF EXISTS idx_content_bucket_cat_session RENAME TO idx_video_bucket_cat_session;
ALTER INDEX IF EXISTS idx_content_bucket_cat_product_org RENAME TO idx_video_bucket_cat_product_org;
ALTER INDEX IF EXISTS idx_content_bucket_cat_uploaded RENAME TO idx_video_bucket_cat_uploaded;
ALTER TABLE content_bucket_categorizations
  RENAME CONSTRAINT content_bucket_categorizations_status_check
  TO video_bucket_categorizations_status_check;
ALTER TABLE content_bucket_categorizations RENAME TO video_bucket_categorizations;
COMMIT;
```

#### Component 2: Service Changes

**File**: `viraltracker/services/content_bucket_service.py`

| Change | Details |
|--------|---------|
| Add `IMAGE_ANALYSIS_PROMPT` | Fields: `summary`, `text_overlays`, `visual_elements`, `dominant_colors`, `cta_text`, `pain_points`, `benefits`, `solution`, `tone`, `format_type`, `key_themes` |
| Update `VIDEO_ANALYSIS_PROMPT` | Rename `video_summary` → `summary` in the prompt JSON |
| Add `analyze_image()` | Send image via PIL `Image.open(BytesIO(bytes))` inline to Gemini. Add 20MB size check before call. |
| Add `_detect_media_type()` | `@staticmethod`. Route by extension: `{jpg,jpeg,png,webp,gif}` → `"image"`, else `"video"`. Case-insensitive. |
| Rename `categorize_video()` → `categorize_content()` | Update method name + docstring |
| Update `CATEGORIZATION_PROMPT_TEMPLATE` | "content categorizer" not "video content categorizer". `{content_analysis}` not `{video_analysis}`. Conditionally include transcript only if present. |
| Update `categorize_content()` internals | Read `analysis.get('summary')` instead of `analysis.get('video_summary')`. Only include `Transcript excerpt:` if transcript exists. |
| Conditional delay in batch | `time.sleep(7)` for video, `time.sleep(2)` for image |
| Update 7 table references | `video_bucket_categorizations` → `content_bucket_categorizations` |
| Update `video_summary` → `summary` in DB insert | Line 462: `"summary": analysis.get("summary", "")` |
| Add `media_type` to DB record + result dict | Both INSERT and returned dict include `"media_type"` |
| Rename `get_uploaded_videos()` → `get_uploaded_files()` | Method name + docstring |
| Update `get_recent_sessions()` | Return `file_count` instead of `video_count` |
| Update progress callback messages | Pass media type: `"Analyzing image..."` vs `"Analyzing video..."` |

#### Component 3: Google Drive Service Additions

**File**: `viraltracker/services/google_drive_service.py`

**No scope change needed** — scope is already `drive` (full access) from the recent
Ad Export rework. All existing methods (`list_folders`, `search_folders`, `upload_file_bytes`,
`get_or_create_folder`, etc.) work as-is.

| Change | Details |
|--------|---------|
| Add `list_files()` | `@staticmethod list_files(access_token, folder_id, mime_types=None, page_size=100, max_results=200) → List[Dict]`. Calls `GET /drive/v3/files` with `q='"{folder_id}" in parents and trashed=false'`. Optional MIME filter list (e.g., `["image/jpeg", "image/png", "video/mp4"]`). Returns `[{id, name, mimeType, size, thumbnailLink, modifiedTime}]`. Follows existing pagination pattern from `list_folders()`. |
| Add `download_file()` | `@staticmethod download_file(access_token, file_id) → Tuple[bytes, Dict]`. Two calls: (1) `GET /drive/v3/files/{id}?fields=name,mimeType,size` for metadata, (2) `GET /drive/v3/files/{id}?alt=media` for bytes. Returns `(file_bytes, {name, mimeType, size})`. |
| Add size guard | Check `size` from metadata before downloading. Reject >100MB videos, >20MB images (matching Gemini inline limits). Return descriptive error. |
| Update class docstring | Add browse/download capabilities to docstring. |

**Reusable for other features**: `list_files()` and `download_file()` are generic — any
future feature that needs to read from Drive can use them.

#### Component 4: UI Page

**File**: `viraltracker/ui/pages/37_📦_Content_Buckets.py` (renamed)

| Change | Details |
|--------|---------|
| Page title | `"Content Buckets"` |
| Module docstring | Replace all "video" references |
| `require_feature` display | `"Content Buckets"` |
| File uploader types | Add `jpg, jpeg, png, webp, gif` |
| File uploader label | `"Upload files"` |
| Help text | `"Upload 1-30 files. Images: ~3s each, Videos: ~12s each."` |
| Time estimate | Count images vs videos separately: `images * 4 + videos * 14` |
| Pre-processing message | `"3 images + 2 videos ready. Estimated time: ~40 seconds."` |
| MIME fallback | Infer from extension instead of hardcoded `"video/mp4"` |
| Tab labels | `"Manage Buckets"`, `"Categorize Content"`, `"Results"`, `"Uploaded"` |
| All status messages | `"file(s)"` instead of `"video(s)"` (~30 occurrences) |
| Results tab retry uploader | Add `jpg, jpeg, png, webp, gif` to accepted types |
| CSV filename | `content_buckets_{session[:8]}.csv` |
| Download button labels | `"X files"` not `"X videos"` |
| Session format func | `f"({s['file_count']} files)"` |
| Detail view | Show `summary` (not `video_summary`); suppress transcript for images; show `visual_elements`/`dominant_colors` for images |
| Image thumbnails | For image results, show small `st.image()` preview in the detail expander (bytes available in `vb_file_map` during session, or from `analysis_data` JSONB for past sessions) |
| Media type filter in Results | Add radio button filter (`All` / `Images` / `Videos`) to the Results tab when viewing a session. Filter on `media_type` field. |
| Subheaders | `"File Details"` not `"Video Details"` |
| Uploaded tab | `"Uploaded Files"` not `"Uploaded Videos"` |
| Bucket form placeholder | `"What types of content belong here?"` not `"videos"` |
| Facebook reference | `"after uploading to your ad platform"` not `"Facebook"` |
| Function names | `render_categorize_content()`, `_retry_files()` |

**Drive Import UI** (within the "Categorize Content" tab, below the local uploader):

| Element | Details |
|---------|---------|
| Divider + subheader | `st.divider()` → `"Or Import from Google Drive"` |
| OAuth connect | If Drive not connected for brand: show "Connect Google Drive" button. Copy OAuth callback handler pattern from `225_Ad_Export.py` (state encode/decode, code exchange, token save). |
| Folder picker | `render_drive_folder_picker(brand_id, org_id, prefix="cb_import", label="Select folder")` — reuse component from `ui/drive_picker.py` directly. Browse/search/paste-URL all included. |
| File list | Once folder selected, call `list_files(folder_id, mime_types=IMAGE_AND_VIDEO_MIMES)`. Display as table with columns: checkbox, filename, type badge, size. |
| Select all / none | Convenience buttons for checkbox selection |
| "Import & Categorize" button | For each selected file: `download_file()` → collect as `{bytes, name, type}` dicts → feed into `analyze_and_categorize_batch()` with `source='google_drive'`. Same progress bar. |
| File size guard | Show warning for files exceeding Gemini limits in the file list. Skip with error if selected. |

**Drive Export UI** (within the "Results" tab, alongside existing CSV/ZIP downloads):

| Element | Details |
|---------|---------|
| Divider + subheader | `"Export to Google Drive"` (below downloads, above Mark as Uploaded) |
| OAuth connect | Same pattern — if not connected, show connect button |
| Folder picker | `render_drive_folder_picker(brand_id, org_id, prefix="cb_export", allow_create=True, label="Target folder")` |
| "Upload to Drive" button | Uploads categorized files from current session. Auto-creates per-bucket subfolders using `get_or_create_folder()`. |
| Progress bar | Shows upload progress with file count |
| Success state | Shows Drive folder link + per-file links |
| Limitation | Only works for current-session files (bytes in `vb_file_map`). For past sessions, show info message. |

#### Component 5: Nav + Admin

- `nav.py:315-316`: Update page path to `37_📦_Content_Buckets.py`, title `"Content Buckets"`
- `Admin.py:416`: Display label `"Content Buckets"`

#### Component 5: Tests

**File**: `tests/services/test_content_bucket_service.py`

| Change | Details |
|--------|---------|
| Update 5 table name assertions | `"video_bucket_categorizations"` → `"content_bucket_categorizations"` |
| Update `video_summary` refs | → `summary` |
| Add `TestAnalyzeImage` | 3 tests: no API key, success, failure |
| Add `TestDetectMediaType` | Test each extension + case insensitivity + unknown extension |
| Add mixed batch test | 1 image + 1 video in same batch → both routed correctly |
| Update method name refs | `categorize_video` → `categorize_content`, `get_uploaded_videos` → `get_uploaded_files` |

**File**: `tests/test_google_drive_service.py`

| Change | Details |
|--------|---------|
| Add `TestListFiles` | Test MIME filtering, pagination, empty folder, parent query construction |
| Add `TestDownloadFile` | Test metadata + content download, size guard rejection, error handling |

#### Component 6: Documentation

- Rename `docs/VIDEO_BUCKETS.md` → `docs/CONTENT_BUCKETS.md`, update content
- Update `docs/README.md` link (line 37)
- Update `docs/TECH_DEBT.md` references (lines 720-736)

---

## Phase 5: INTEGRATION & TEST

### 5.1 Deploy Strategy

Migration and code deploy **must be atomic** (same Railway push). Since Railway deploys from the git push and runs migrations before starting the app, this is handled naturally. No bridge VIEW needed.

### 5.2 Testing Plan

**Automated:**
- [ ] `python3 -m py_compile` on all modified files
- [ ] All existing 34 tests pass with updated assertions
- [ ] New tests pass: `analyze_image()`, `_detect_media_type()`, mixed batch

**Manual:**
- [ ] Upload batch of images only → all categorized correctly
- [ ] Upload batch of videos only → same behavior as before (regression check)
- [ ] Upload mixed batch → images and videos both categorized
- [ ] Verify `media_type` stored correctly in DB
- [ ] Check Results tab shows past sessions (backward compat, `summary` column)
- [ ] Retry a failed image from both Categorize and Results tabs
- [ ] Verify conditional delay (images process faster than videos)
- [ ] Test large image (>20MB) gets friendly error, not crash
- [ ] CSV download has `content_buckets_` filename
- [ ] ZIP download works with mixed image+video content
- [ ] Image thumbnail shows in detail expander for image results
- [ ] Media type filter (All/Images/Videos) works in Results tab
- [ ] Drive import: connect OAuth, browse folders, select files, import & categorize
- [ ] Drive import: file list correctly filters to image/video MIME types only
- [ ] Drive import: oversized files show warning and are skipped
- [ ] Drive import: `source='google_drive'` stored correctly in DB
- [ ] Drive export: select folder, upload categorized files with per-bucket subfolders
- [ ] Drive export: progress bar and success links work correctly

---

## Review Agent Findings Log

### Reviewed by: QA, UX, DBA, Software Engineer (2026-03-09)

**CRITICAL fixes incorporated:**
- C1: Unified `summary` field (was `video_summary` / `image_summary` mismatch)
- C2: Media-agnostic categorization prompt
- C3: Test file added to plan with full update scope
- C4: Image types added to Results tab retry uploader

**HIGH fixes incorporated:**
- H1: CHECK constraint on `media_type`
- H2: Conditional rate-limit delay (2s images, 7s videos)
- H3: Atomic deploy strategy documented
- H4: CHECK constraint name rename in migration
- H5: MIME fallback inferred from extension

**MEDIUM fixes incorporated:**
- M1: Full 70+ string audit scope documented
- M2: `categorize_video()` → `categorize_content()` rename
- M3: `video_count` → `file_count`, `get_uploaded_videos()` → `get_uploaded_files()`
- M4: Transaction wrapper on migration
- M5: Rollback script provided
- M6: 20MB file size check for inline images
- M7: Media-type-aware progress callback messages

**LOW fixes incorporated (promoted from deferred):**
- L1: Image thumbnails in detail expander (`st.image()` from file bytes)
- L2: Media type filter (All/Images/Videos) radio button in Results tab

**Google Drive integration (added 2026-03-09):**
- D1: Drive import — browse folders, pick files, download & categorize (same pipeline)
- D2: Drive export — upload categorized files to Drive with per-bucket subfolders
- D3: `list_files()` + `download_file()` added to `GoogleDriveService`
- D4: `source` column added to DB (`upload` or `google_drive`)
- D5: Reuse `drive_picker.py` component (no custom folder browser needed)
- D6: No OAuth scope change needed (already `drive` from Ad Export rework)
- D7: Tests for new Drive service methods

**Not changing (with justification):**
- `vb_` session state key prefix — renaming would break any active user sessions mid-use. Internal only, not user-facing.
- RLS policies on table — pre-existing gap across content_buckets + categorizations tables. Tracked in TECH_DEBT.md, out of scope for this feature.
