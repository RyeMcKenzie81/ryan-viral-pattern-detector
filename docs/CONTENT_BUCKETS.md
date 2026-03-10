# Content Buckets

**Last Updated**: 2026-03-09
**UI Page**: `viraltracker/ui/pages/37_📦_Content_Buckets.py`
**Service**: `viraltracker/services/content_bucket_service.py`
**Tests**: `tests/services/test_content_bucket_service.py`

---

## Overview

Content Buckets helps users organize bulk uploads (images and videos) into thematic content buckets for ad campaigns. Users define buckets (e.g., "Gut Health", "Energy & Focus"), upload files or import from Google Drive, and Gemini AI analyzes each file's content to auto-categorize it into the best-matching bucket.

### Workflow

```
Define Buckets → Upload Files / Import from Drive → Gemini Analysis → Auto-Categorize
     ↓                                                                       ↓
Manage Buckets tab                                                Categorize tab (results)
                                                                          ↓
                                                                Download ZIPs per bucket
                                                                Export to Google Drive
                                                                          ↓
                                                                Upload to ad platform
                                                                          ↓
                                                                Mark as Uploaded (Results tab)
                                                                          ↓
                                                                View in Uploaded tab
```

---

## UI Tabs

### Tab 1: Manage Buckets

CRUD interface for content bucket definitions. Each bucket has:

| Field | Description |
|-------|-------------|
| `name` | Unique name per product (e.g., "Digestion & Gut Health") |
| `best_for` | What types of content belong here |
| `angle` | The approach (e.g., fear-based, educational) |
| `avatar` | Target audience description |
| `pain_points` | List of pain points this bucket addresses |
| `solution_mechanism` | List of solution approaches |
| `key_copy_hooks` | List of copy hooks for this angle |

### Tab 2: Categorize Content

**Local Upload:**
1. Upload 1-30 files (images: jpg/jpeg/png/webp/heic/heif, videos: mp4/mov/avi/webm/mpeg)
2. Click "Analyze & Categorize" to start batch processing
3. Each file is routed: images → inline Gemini analysis, videos → Gemini Files API
4. Results show filename, media type, bucket assignment, confidence score, and reasoning
5. Failed files can be retried individually or in bulk

**Google Drive Import:**
1. Connect Google Drive via OAuth (one-time per brand)
2. Browse folders using the folder picker (browse/search/paste-URL)
3. Select files from the chosen folder (filtered to image/video MIME types)
4. Click "Import & Categorize" — files are downloaded and processed through the same pipeline

**Download per Bucket**: After categorization, download buttons create ZIP files per bucket from in-memory file bytes. Only available during the current session.

**Rate Limiting**: 2s delay between images, 7s between videos.

### Tab 3: Results

View past categorization sessions with:
- Session selector (last 10 sessions)
- Media type filter (All / Images / Videos)
- Summary metrics (total, categorized, buckets used, errors)
- Results dataframe with Type and Uploaded columns
- CSV download
- Export to Google Drive (per-bucket subfolders)
- Retry errored files by re-uploading

**Mark as Uploaded**: After uploading to your ad platform, mark them here:
- "Mark All as Uploaded" bulk button
- Per-row toggle
- Status persists in `is_uploaded` column on `content_bucket_categorizations`

### Tab 4: Uploaded

Read-only reference of all files marked as uploaded, grouped by bucket.

---

## Database Schema

### `content_buckets`

Bucket definitions owned by a product within an organization. (No changes from original.)

### `content_bucket_categorizations`

Individual file analysis and categorization results. (Renamed from `video_bucket_categorizations`.)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated |
| `organization_id` | UUID (FK) | Multi-tenant isolation |
| `product_id` | UUID (FK) | Product |
| `bucket_id` | UUID (FK, nullable) | Assigned bucket |
| `session_id` | UUID | Groups files from same upload batch |
| `filename` | TEXT | Original filename |
| `bucket_name` | TEXT | Denormalized bucket name |
| `confidence_score` | FLOAT | Categorization confidence (0-1) |
| `reasoning` | TEXT | Why this bucket was chosen |
| `summary` | TEXT | Gemini-generated content summary |
| `transcript` | TEXT | Full transcript (videos only) |
| `analysis_data` | JSONB | Complete Gemini analysis JSON |
| `status` | TEXT | `categorized`, `analyzed`, or `error` |
| `error_message` | TEXT | Error details if status=error |
| `media_type` | TEXT | `image` or `video` |
| `source` | TEXT | `upload` or `google_drive` |
| `is_uploaded` | BOOLEAN | Whether file has been uploaded to ad platform |
| `created_at` | TIMESTAMPTZ | Auto-set |

---

## Migrations

| Migration | Date | Purpose |
|-----------|------|---------|
| `2026-02-18_content_buckets.sql` | 2026-02-18 | Initial schema |
| `2026-02-18_content_buckets_uploaded.sql` | 2026-02-18 | Add `is_uploaded` column |
| `2026-03-09_rename_content_buckets.sql` | 2026-03-09 | Rename table, add `media_type` + `source` columns, rename `video_summary` → `summary` |

---

## Service API

### `ContentBucketService`

**Location**: `viraltracker/services/content_bucket_service.py`

#### Bucket CRUD

| Method | Description |
|--------|-------------|
| `create_bucket(org_id, product_id, name, ...)` | Create a new bucket |
| `get_buckets(product_id, org_id)` | Get all buckets for a product |
| `update_bucket(bucket_id, **fields)` | Update bucket fields |
| `delete_bucket(bucket_id)` | Delete a bucket |

#### Content Analysis & Categorization

| Method | Description |
|--------|-------------|
| `analyze_video(file_bytes, filename, mime_type)` | Analyze a video via Gemini Files API |
| `analyze_image(file_bytes, filename, mime_type)` | Analyze an image via Gemini inline (Part.from_bytes) |
| `categorize_content(analysis, buckets)` | Categorize content into a bucket (media-agnostic) |
| `analyze_and_categorize_batch(files, buckets, ..., source)` | Process mixed batch: detect type → analyze → categorize → save |
| `_detect_media_type(filename)` | Route by extension: image vs video |

#### Results & Upload Tracking

| Method | Description |
|--------|-------------|
| `get_session_results(session_id)` | Get all results for a session |
| `get_recent_sessions(product_id, org_id, limit)` | Get recent sessions with file counts |
| `delete_categorization(session_id, filename)` | Delete a record (for retry) |
| `mark_as_uploaded(categorization_ids, uploaded)` | Bulk mark/unmark as uploaded |
| `get_uploaded_files(product_id, org_id)` | Get all uploaded files for a product |

### `GoogleDriveService` additions

| Method | Description |
|--------|-------------|
| `list_files(access_token, folder_id, mime_types, ...)` | List files in a folder with MIME filtering |
| `download_file(access_token, file_id, ...)` | Download file bytes with size guard |

---

## Google Drive Integration

The Content Buckets page supports importing from and exporting to Google Drive:

- **Import**: Browse → select files → download → analyze → categorize (same pipeline as local upload)
- **Export**: Select target folder → upload categorized files with per-bucket subfolders
- Uses the shared `drive_picker.py` component (prefix `cb_import` / `cb_export`)
- OAuth redirect URI: `{APP_BASE_URL}/Content_Buckets`
- **Deployment note**: The redirect URI must be registered in Google Cloud Console

---

## AI Models Used

| Task | Model | Method |
|------|-------|--------|
| Video analysis | `gemini-2.5-flash` | Gemini Files API (upload → poll → analyze) |
| Image analysis | `gemini-2.5-flash` | Inline via `Part.from_bytes` (~3s per image) |
| Bucket categorization | `gemini-2.5-flash` | Text-only call (media-agnostic) |

**Image format notes**: Supports JPEG, PNG, WebP, HEIC, HEIF. GIF is **not supported** by Gemini 2.0+.

---

## Multi-Tenancy

- All queries filter by `organization_id` (except superuser `"all"` mode)
- `_resolve_org_id()` converts superuser `"all"` to the actual org owning the product
- Feature-gated via `require_feature("video_buckets", "Content Buckets")`
- Feature key remains `video_buckets` in DB for backward compatibility

---

## Test Coverage

48 tests in `tests/services/test_content_bucket_service.py`:

| Test Class | Count | What's Tested |
|------------|-------|---------------|
| `TestCreateBucket` | 3 | Required fields, list serialization, empty data |
| `TestGetBuckets` | 2 | Product/org filtering, empty results |
| `TestDeleteBucket` | 1 | Delete by ID |
| `TestDeleteCategorization` | 1 | Delete by session + filename |
| `TestDetectMediaType` | 6 | Image/video extensions, case insensitivity, no extension, unsupported, GIF |
| `TestAnalyzeVideo` | 3 | No API key, successful analysis, failed processing |
| `TestAnalyzeImage` | 3 | No API key, oversized rejection, successful analysis |
| `TestCategorizeContent` | 5 | No API key, success, exception, video fields, image fields |
| `TestAnalyzeAndCategorizeBatch` | 6 | Batch processing, errors, callbacks, image routing, mixed batch, source param |
| `TestGetSessionResults` | 2 | Session results, empty results |
| `TestGetRecentSessions` | 2 | Session grouping, empty results |
| `TestParseJsonResponse` | 6 | Plain JSON, code blocks, empty/invalid, nested |
| `TestMarkAsUploaded` | 5 | Single, multiple, unmark, empty list, no data |
| `TestGetUploadedFiles` | 3 | Filtered results, empty, superuser org skip |

8 additional tests in `tests/test_google_drive_service.py`:

| Test Class | Count | What's Tested |
|------------|-------|---------------|
| `TestListFiles` | 4 | Basic listing, MIME filtering, empty folder, max results cap |
| `TestDownloadFile` | 4 | Successful download, oversized image/video rejection, metadata error |
