# Video Buckets

**Last Updated**: 2026-02-18
**UI Page**: `viraltracker/ui/pages/37_📦_Video_Buckets.py`
**Service**: `viraltracker/services/content_bucket_service.py`
**Tests**: `tests/services/test_content_bucket_service.py`

---

## Overview

Video Buckets helps users organize bulk video uploads into thematic content buckets for Facebook ad campaigns. Users define buckets (e.g., "Gut Health", "Energy & Focus"), upload 10-20 videos at a time, and Gemini AI analyzes each video's content to auto-categorize it into the best-matching bucket.

### Workflow

```
Define Buckets → Upload Videos → Gemini Analysis → Auto-Categorize
     ↓                                                    ↓
Manage Buckets tab                              Categorize tab (results)
                                                         ↓
                                               Download ZIPs per bucket
                                                         ↓
                                               Upload to Facebook manually
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
| `best_for` | What types of videos belong here |
| `angle` | The approach (e.g., fear-based, educational) |
| `avatar` | Target audience description |
| `pain_points` | List of pain points this bucket addresses |
| `solution_mechanism` | List of solution approaches |
| `key_copy_hooks` | List of copy hooks for this angle |

### Tab 2: Categorize Videos

1. Upload 1-20 videos (mp4, mov, avi, webm)
2. Click "Analyze & Categorize" to start batch processing
3. Each video is: uploaded to Gemini Files API → analyzed → categorized via text-only Gemini call
4. Results show filename, bucket assignment, confidence score, and reasoning
5. Failed videos can be retried individually or in bulk

**Download per Bucket**: After categorization, download buttons appear for each bucket. Each creates a ZIP file from the in-memory video bytes containing only the videos assigned to that bucket. This only works while files are in `st.session_state.vb_file_map` (i.e., during the current Categorize session — files are NOT stored persistently).

**Rate Limiting**: 7-second delay between videos to respect Gemini's 9 req/min limit.

### Tab 3: Results

View past categorization sessions with:
- Session selector (last 10 sessions)
- Summary metrics (total, categorized, buckets used, errors)
- Results dataframe with Uploaded status column
- CSV download
- Retry errored videos by re-uploading failed files

**Mark as Uploaded**: After uploading videos to Facebook, mark them here:
- "Mark All as Uploaded" bulk button for all not-yet-uploaded categorized videos
- Per-row "Mark Uploaded" / "Unmark" toggle
- Status persists in the `is_uploaded` column on `video_bucket_categorizations`

### Tab 4: Uploaded

Read-only reference of all videos marked as uploaded, grouped by bucket:
- Each bucket shown as an expander with video count
- Per-video: filename, confidence score, and "Unmark" button
- Total uploaded count displayed in header

---

## Database Schema

### `content_buckets`

Bucket definitions owned by a product within an organization.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated |
| `organization_id` | UUID (FK) | Multi-tenant isolation |
| `product_id` | UUID (FK) | Product this bucket belongs to |
| `name` | TEXT | Bucket name (unique per product) |
| `best_for` | TEXT | What types of videos fit |
| `angle` | TEXT | Content angle |
| `avatar` | TEXT | Target audience |
| `pain_points` | JSONB | JSON array of pain point strings |
| `solution_mechanism` | JSONB | JSON array of solution strings |
| `key_copy_hooks` | JSONB | JSON array of hook strings |
| `display_order` | INT | Sort order |
| `created_at` | TIMESTAMPTZ | Auto-set |
| `updated_at` | TIMESTAMPTZ | Updated on modify |

### `video_bucket_categorizations`

Individual video analysis and categorization results.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated |
| `organization_id` | UUID (FK) | Multi-tenant isolation |
| `product_id` | UUID (FK) | Product |
| `bucket_id` | UUID (FK, nullable) | Assigned bucket (null if uncategorized) |
| `session_id` | UUID | Groups videos from same upload batch |
| `filename` | TEXT | Original filename |
| `bucket_name` | TEXT | Denormalized bucket name |
| `confidence_score` | FLOAT | Categorization confidence (0-1) |
| `reasoning` | TEXT | Why this bucket was chosen |
| `video_summary` | TEXT | Gemini-generated video summary |
| `transcript` | TEXT | Full transcript |
| `analysis_data` | JSONB | Complete Gemini analysis JSON |
| `status` | TEXT | `categorized`, `analyzed`, or `error` |
| `error_message` | TEXT | Error details if status=error |
| `is_uploaded` | BOOLEAN | Whether video has been uploaded to Facebook (default: FALSE) |
| `created_at` | TIMESTAMPTZ | Auto-set |

**Indexes**:
- `idx_video_bucket_cat_uploaded` — Partial index on `(product_id, organization_id) WHERE is_uploaded = TRUE` for efficient Uploaded tab queries

---

## Migrations

| Migration | Date | Purpose |
|-----------|------|---------|
| `2026-02-18_content_buckets.sql` | 2026-02-18 | Initial schema: `content_buckets` and `video_bucket_categorizations` tables |
| `2026-02-18_content_buckets_uploaded.sql` | 2026-02-18 | Add `is_uploaded` column with partial index |

---

## Service API

### `ContentBucketService`

**Location**: `viraltracker/services/content_bucket_service.py`

All methods are dict-based (no Pydantic models). Returns `Dict[str, Any]` or `List[Dict[str, Any]]`.

#### Bucket CRUD

| Method | Description |
|--------|-------------|
| `create_bucket(org_id, product_id, name, ...)` | Create a new bucket |
| `get_buckets(product_id, org_id)` | Get all buckets for a product |
| `update_bucket(bucket_id, **fields)` | Update bucket fields |
| `delete_bucket(bucket_id)` | Delete a bucket |

#### Video Analysis & Categorization

| Method | Description |
|--------|-------------|
| `analyze_video(file_bytes, filename, mime_type)` | Analyze a single video via Gemini Files API |
| `categorize_video(analysis, buckets)` | Categorize a video into a bucket using text-only Gemini |
| `analyze_and_categorize_batch(files, buckets, product_id, org_id, session_id, progress_callback)` | Process a batch of videos: analyze → categorize → save to DB |

#### Results & Sessions

| Method | Description |
|--------|-------------|
| `get_session_results(session_id)` | Get all results for a session |
| `get_recent_sessions(product_id, org_id, limit)` | Get recent sessions with video counts |
| `delete_categorization(session_id, filename)` | Delete a record (for retry) |

#### Upload Tracking

| Method | Description |
|--------|-------------|
| `mark_as_uploaded(categorization_ids, uploaded=True)` | Bulk mark/unmark videos as uploaded. Returns count of updated records. Guards against empty list. |
| `get_uploaded_videos(product_id, org_id)` | Get all uploaded videos for a product, ordered by bucket then filename. Handles superuser `"all"` org. |

---

## Session State

| Key | Type | Purpose |
|-----|------|---------|
| `vb_session_id` | `str \| None` | Current categorization session UUID |
| `vb_results` | `list \| None` | Current batch results (in-memory) |
| `vb_processing` | `bool` | Whether batch processing is running |
| `vb_file_map` | `dict` | Map of `filename → {bytes, name, type}` for retry and download |

**Important**: `vb_file_map` holds raw video bytes in memory. These are NOT persisted — they exist only during the Categorize session. Download-per-bucket ZIPs and retries depend on this data being available.

---

## AI Models Used

| Task | Model | Notes |
|------|-------|-------|
| Video analysis | `gemini-2.5-flash` | Via Gemini Files API (upload → poll → analyze) |
| Bucket categorization | `gemini-2.5-flash` | Text-only call with analysis + bucket descriptions |

---

## Multi-Tenancy

- All queries filter by `organization_id` (except superuser `"all"` mode)
- `_resolve_org_id()` converts superuser `"all"` to the actual org owning the product
- Feature-gated via `require_feature("video_buckets", "Video Buckets")`

---

## Test Coverage

34 tests in `tests/services/test_content_bucket_service.py`:

| Test Class | Count | What's Tested |
|------------|-------|---------------|
| `TestCreateBucket` | 3 | Required fields, list serialization, empty data |
| `TestGetBuckets` | 2 | Product/org filtering, empty results |
| `TestDeleteBucket` | 1 | Delete by ID |
| `TestDeleteCategorization` | 1 | Delete by session + filename |
| `TestAnalyzeVideo` | 3 | No API key, successful analysis, failed processing |
| `TestCategorizeVideo` | 3 | No API key, successful categorization, exception handling |
| `TestAnalyzeAndCategorizeBatch` | 3 | Batch processing, error handling, progress callback |
| `TestGetSessionResults` | 2 | Session results, empty results |
| `TestGetRecentSessions` | 2 | Session grouping, empty results |
| `TestParseJsonResponse` | 6 | Plain JSON, code blocks, empty/invalid, nested |
| `TestMarkAsUploaded` | 5 | Single, multiple, unmark, empty list, no data |
| `TestGetUploadedVideos` | 3 | Filtered results, empty, superuser org skip |
