# Video Tools Suite - Implementation Plan (v2)

## Context

ViralTracker needs a video content research and recreation pipeline. The goal: scrape AI-focused Instagram accounts, analyze their best-performing content with Gemini, identify reusable patterns (avatars, hooks, storyboards), then recreate similar content using VEO 3.1 and Kling AI with our own brand avatars.

**User decisions:** Apify for IG scraping, Kling AI included in MVP (native API), per-brand watched accounts, new "Video Tools" section in 50s pages.

**Review panel findings incorporated:** MIT SWE, QA, AI Video Production, Evals, Scrum Master.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Streamlit UI (50s pages)                          │
│  50_Instagram_Content  │  51_Video_Studio  │  (47_Veo_Avatars)       │
└────────┬───────────────┴────────┬──────────┴─────────────────────────┘
         │                        │
┌────────▼────────────────────────▼────────────────────────────────────┐
│                         Service Layer                                 │
│  InstagramContentService  │  InstagramAnalysisService                │
│  KlingVideoService        │  VideoRecreationService                  │
│  VideoGenerationProtocol  │  (shared interface: VEO + Kling + Sora)  │
│  (existing: VeoService, AvatarService, VideoAnalysisService,         │
│   ElevenLabsService, FFmpegService, comic_render_service)            │
└────────┬──────────────────┬─────────────┬───────────┬────────────────┘
         │                  │             │           │
    ┌────▼────┐     ┌──────▼──────┐  ┌───▼────────┐ ┌───▼──────────┐
    │  Apify  │     │ Gemini 3.1  │  │ Kling API  │ │ ElevenLabs   │
    │  (IG)   │     │ (Analysis)  │  │ (native)   │ │ (Voice/Audio)│
    └─────────┘     └─────────────┘  └────────────┘ └──────────────┘
```

### Key Design Decisions (from reviews)

1. **Reuse existing tables**: Extend `posts`/`accounts`/`project_accounts` — do NOT duplicate with new Instagram-specific tables for posts/accounts
2. **Outlier detection BEFORE media download**: Only download media for outlier posts (saves ~90% storage)
3. **Generalize `ad_video_analysis`**: Add `source_type` column instead of creating a duplicate `instagram_content_analysis` table
4. **`VideoGenerationProtocol`**: Shared interface for VEO 3.1, Kling, and Sora
5. **Audio-first workflow**: Generate ElevenLabs audio BEFORE video for accurate timing
6. **Scene type → tool mapping**: Kling for talking-head, VEO for action/B-roll
7. **Two-pass Gemini analysis**: Pass 1 (Flash) = structural extraction, Pass 2 (Pro) = production shot sheet
8. **FFmpeg concat filter**: Reuse existing pattern from `comic_render_service.py` for clip stitching
9. **Native Kling API**: Direct integration via `api-singapore.klingai.com` with JWT auth (native API, not fal.ai gateway)
10. **MVP scope**: Read-only storyboard view for V1, defer storyboard editor and agent tools to V2

---

## Existing Infrastructure to Reuse

| Component | File | What We Get |
|-----------|------|-------------|
| **Instagram Scraper** | `viraltracker/scrapers/instagram.py` | Apify integration, `_normalize_items()`, upsert to `posts` table, account metadata |
| **Posts/Accounts tables** | Existing DB | `posts` (views, likes, comments, caption, length_sec), `accounts` (follower_count, bio, is_verified), `project_accounts` linking |
| **VideoAnalysisService** | `viraltracker/services/video_analysis_service.py` | Gemini Files API upload, structured analysis prompt, immutable versioned rows, `ad_video_analysis` table |
| **VeoService** | `viraltracker/services/veo_service.py` | Video generation with reference images, async polling, Supabase storage upload, usage tracking |
| **AvatarService** | `viraltracker/services/avatar_service.py` | `brand_avatars` CRUD, 3-slot reference images, Gemini image generation |
| **ElevenLabsService** | `viraltracker/services/elevenlabs_service.py` | Voice profiles, beat-based audio, clean text generation |
| **FFmpeg concat** | `viraltracker/services/comic_video/comic_render_service.py` | Concat filter (not demuxer), SAR normalization, silent audio injection, background music mixing |
| **OutlierDetector** | `viraltracker/generation/outlier_detector.py` | Z-score/percentile methods, `Config.DEFAULT_SD_THRESHOLD` |
| **ApifyService** | `viraltracker/services/apify_service.py` | `run_actor()`, `run_actor_batch()`, `@retry`, `ApifyRunResult` |
| **AdScrapingService** | `viraltracker/services/ad_scraping_service.py` | Media download with browser headers, Supabase storage upload, MIME detection |

---

## Phase 1: Instagram Content Library (Sprint 1, Week 1)

**Goal:** Extend existing scraper with per-brand watched accounts, outlier detection, media download (outliers only), and a Streamlit content library page.

### Database Migration: `migrations/2026-02-25_instagram_content.sql`

```sql
-- Per-brand watched accounts (extends existing accounts system)
CREATE TABLE instagram_watched_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    account_id UUID NOT NULL REFERENCES accounts(id),  -- Links to existing accounts table
    is_active BOOLEAN DEFAULT true,
    scrape_frequency_hours INTEGER DEFAULT 168,  -- weekly default
    min_scrape_interval_hours INTEGER DEFAULT 24, -- prevent over-scraping
    last_scraped_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(brand_id, account_id)
);

CREATE INDEX idx_ig_watched_brand ON instagram_watched_accounts(brand_id);
CREATE INDEX idx_ig_watched_org ON instagram_watched_accounts(organization_id);

-- Media files for downloaded content (only outliers get downloaded)
CREATE TABLE instagram_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,  -- Links to existing posts table
    media_type TEXT NOT NULL,             -- 'image', 'video'
    media_index INTEGER DEFAULT 0,        -- carousel order
    original_cdn_url TEXT,               -- CDN URL (expires, for reference only)
    cdn_url_captured_at TIMESTAMPTZ,     -- when URL was captured (track staleness)
    storage_path TEXT,                    -- Supabase storage path (persistent)
    thumbnail_path TEXT,
    width INTEGER,
    height INTEGER,
    file_size_bytes BIGINT,
    download_status TEXT DEFAULT 'pending',  -- pending, downloading, downloaded, failed
    download_error TEXT,
    downloaded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ig_media_post ON instagram_media(post_id);
CREATE INDEX idx_ig_media_status ON instagram_media(download_status);

-- Add outlier tracking columns to existing posts table
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_outlier BOOLEAN DEFAULT false;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS outlier_score FLOAT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS post_type TEXT;  -- 'image', 'video', 'carousel'
ALTER TABLE posts ADD COLUMN IF NOT EXISTS media_type TEXT;  -- 'reel', 'image', 'carousel', 'story'
```

### New Service: `viraltracker/services/instagram_content_service.py`

**Wraps existing `InstagramScraper` + adds outlier detection + media download.**

```python
class InstagramContentService:
    """Instagram content research: scraping, outlier detection, media download."""

    STORAGE_BUCKET = "instagram-media"

    def __init__(self, apify_service=None):
        self.scraper = InstagramScraper()  # Reuse existing
        self.supabase = get_supabase_client()
        self._tracker = None
        self._user_id = None
        self._org_id = None
```

**Key methods:**
| Method | Purpose |
|--------|---------|
| `add_watched_account(brand_id, username, org_id)` | Add account to watch list (creates in `accounts` + `instagram_watched_accounts`) |
| `remove_watched_account(watched_id)` | Soft delete (is_active=false) |
| `list_watched_accounts(brand_id)` | Get active watched accounts |
| `scrape_account(watched_account_id)` | Delegates to existing `InstagramScraper`, enforces min_scrape_interval |
| `scrape_all_active(brand_id)` | Batch scrape all active accounts for a brand |
| `calculate_outliers(brand_id, days=30)` | Z-score on engagement, updates `is_outlier` + `outlier_score` on `posts` |
| `download_outlier_media(brand_id)` | Download media ONLY for outlier posts (CDN URLs → Supabase storage) |
| `get_top_content(brand_id, days, limit, post_type)` | Filtered query on `posts` table with outlier ranking |

**Critical flow:** `scrape → outlier detection → download media for outliers only`

**Outlier edge cases (from QA review):**
- N < 3 posts: skip outlier detection, flag all as candidates
- std = 0 (identical engagement): all posts get z-score = 0, none flagged
- CDN URL expiration: download immediately after scrape, track `cdn_url_captured_at`

### UI Page: `viraltracker/ui/pages/50_📸_Instagram_Content.py`

**Tabs:**
1. **Watched Accounts** — Add/remove IG usernames, last scraped date, trigger manual scrape
2. **Content Library** — Grid of scraped posts with filters (account, date range, post type, outliers only), engagement stats, thumbnails
3. **Top Content** — Outlier dashboard with time-range selector

---

## Phase 2: Content Analysis (Sprint 2-3, Weeks 2-3)

**Goal:** Two-pass Gemini analysis of outlier videos/images. Production-quality storyboard extraction.

### Database Changes: Generalize `ad_video_analysis`

```sql
-- Add source_type to existing ad_video_analysis table
ALTER TABLE ad_video_analysis ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'meta_ad';
  -- Values: 'meta_ad', 'instagram_scrape', 'upload'
ALTER TABLE ad_video_analysis ADD COLUMN IF NOT EXISTS source_post_id UUID REFERENCES posts(id);

-- Add production shot sheet fields (Pass 2)
ALTER TABLE ad_video_analysis ADD COLUMN IF NOT EXISTS production_storyboard JSONB;
  -- Detailed per-beat: camera_shot_type, camera_movement, camera_angle,
  -- subject_action, subject_emotion, lighting, transition, pacing, duration_sec

-- Image analysis (for carousel/image posts)
CREATE TABLE instagram_image_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    post_id UUID NOT NULL REFERENCES posts(id),
    media_id UUID REFERENCES instagram_media(id),
    status TEXT DEFAULT 'pending',
    -- Image-specific fields
    image_description TEXT,
    image_style TEXT,               -- art style, color palette, composition
    image_elements JSONB,           -- [{element, position, description}]
    image_text_content TEXT,
    recreation_notes TEXT,
    -- Person detection
    people_detected INTEGER DEFAULT 0,
    has_talking_head BOOLEAN DEFAULT false,  -- simplified avatar detection for V1
    people_details JSONB,
    -- Metadata
    model_used TEXT,
    prompt_version TEXT DEFAULT 'v1',
    input_hash TEXT,
    raw_response JSONB,
    error_message TEXT,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(post_id, media_id, prompt_version, input_hash)
);
```

### New Service: `viraltracker/services/instagram_analysis_service.py`

**Two-pass analysis (from AI Video Production review):**

**Pass 1 (Gemini Flash — structural extraction):**
- Full transcript with timestamps
- Text overlays with position/style/confidence
- Basic storyboard (timestamp, scene description, key elements)
- Hook analysis (spoken + visual + type)
- People detection (count, has_talking_head boolean)
- Stored in generalized `ad_video_analysis` with `source_type='instagram_scrape'`

**Pass 2 (Gemini Pro — production shot sheet, only for approved candidates):**
- Per-beat: `camera_shot_type`, `camera_movement`, `camera_angle`, `duration_sec`
- `subject_action` (specific continuous-tense verbs for VEO prompts)
- `subject_emotion`, `subject_framing`
- `lighting_description`, `background_description`
- `audio_type` (voiceover / direct-to-camera / music-only / sfx)
- `transition_to_next` (cut / dissolve / whip-pan / jump-cut)
- `pacing` (fast / medium / slow)
- Stored in `production_storyboard` JSONB column

**Key methods:**
| Method | Purpose |
|--------|---------|
| `analyze_video(media_id)` | Pass 1: structural extraction (Flash model) |
| `analyze_image(media_id)` | Image analysis for recreation potential |
| `analyze_carousel(post_id)` | Batch image analysis for all carousel items |
| `deep_production_analysis(analysis_id)` | Pass 2: production shot sheet (Pro model, for approved candidates only) |
| `get_analysis(post_id)` | Retrieve analysis results |
| `batch_analyze_outliers(brand_id)` | Queue analysis for all outlier posts |

**Automated consistency checks (from Evals review, run on every analysis):**

| Check | Validation | Pass Criteria |
|-------|-----------|---------------|
| VA-1 | Duration match vs FFprobe | abs(diff) <= 2s |
| VA-2 | Transcript non-empty | len > 20 chars (if video has audio) |
| VA-3 | Storyboard coverage | last_ts >= 0.7 * duration |
| VA-4 | Timestamp monotonicity | No reversals |
| VA-5 | Segment coverage | Sum(segment_lengths) / duration >= 0.6 |
| VA-6 | Hook window | Hook fields non-null when transcript exists |
| VA-7 | JSON completeness | All required keys present |
| VA-8 | Overlay coherence | If text_overlays empty, confidence = 0.0 |

Store as `eval_scores` JSONB on analysis row. Flag for human review if < 0.6 overall.

### UI Enhancement: Add "Analysis" tab to page 50

- "Analyze" button per outlier post, "Analyze All Outliers" batch button
- Analysis results: expandable transcript, visual storyboard timeline, hook breakdown
- Talking-head detection flag per account

---

## Phase 3: Kling Video Service + VideoGenerationProtocol (Sprint 1-2, parallel with Phase 1)

**Goal:** Native Kling AI integration via `api-singapore.klingai.com` + shared interface for all video generation engines.

**Official API docs:** https://app.klingai.com/global/dev/document-api/

### VideoGenerationProtocol: `viraltracker/services/video_generation_protocol.py`

```python
from typing import Protocol, Optional, List, runtime_checkable

@runtime_checkable
class VideoGenerationProtocol(Protocol):
    """Shared interface for VEO 3.1, Kling, and Sora.

    Covers core generation patterns. Engine-specific operations
    (lip-sync, multi-shot, video-extend) are called directly on
    the engine's service class.
    """

    async def generate_from_prompt(
        self, prompt: str, duration_sec: int, aspect_ratio: str,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None
    ) -> "VideoGenerationResult": ...

    async def generate_talking_head(
        self, avatar_image_url: str, audio_url: str,
        prompt: Optional[str] = None
    ) -> "VideoGenerationResult": ...

    async def get_status(self, generation_id: str) -> "VideoGenerationResult": ...
    async def download_and_store(self, generation_id: str) -> str: ...
```

### New Service: `viraltracker/services/kling_video_service.py`

**Implements `VideoGenerationProtocol`. Direct integration with native Kling API.**

**Base URL:** `https://api-singapore.klingai.com`

**Authentication:** JWT with HS256 (AccessKey + SecretKey, 30-min expiry, cached with 25-min TTL)

```python
import jwt
import time
import httpx

class KlingVideoService:
    """Kling AI video generation via native API (api-singapore.klingai.com)."""

    BASE_URL = "https://api-singapore.klingai.com"
    STORAGE_BUCKET = "kling-videos"

    # Endpoint path mapping (each endpoint type has its OWN query path)
    ENDPOINTS = {
        KlingEndpoint.TEXT2VIDEO:     "/v1/videos/text2video",
        KlingEndpoint.IMAGE2VIDEO:    "/v1/videos/image2video",
        KlingEndpoint.AVATAR:         "/v1/videos/avatar/image2video",
        KlingEndpoint.IDENTIFY_FACE:  "/v1/videos/identify-face",
        KlingEndpoint.LIP_SYNC:       "/v1/videos/advanced-lip-sync",
        KlingEndpoint.VIDEO_EXTEND:   "/v1/videos/video-extend",
        KlingEndpoint.MULTI_SHOT:     "/v1/general/ai-multi-shot",
        KlingEndpoint.OMNI_VIDEO:     "/v1/videos/omni-video",
    }

    # Task statuses from Kling API
    STATUS_SUBMITTED = "submitted"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCEED = "succeed"
    STATUS_FAILED = "failed"
    TERMINAL_STATUSES = {STATUS_SUCCEED, STATUS_FAILED}

    # Models: model_name + separate mode param
    DEFAULT_MODELS = {
        KlingEndpoint.TEXT2VIDEO: "kling-v2-6",
        KlingEndpoint.IMAGE2VIDEO: "kling-v2-6",
    }

    def __init__(self, access_key=None, secret_key=None, max_concurrent=None):
        self.access_key = access_key or Config.KLING_ACCESS_KEY
        self.secret_key = secret_key or Config.KLING_SECRET_KEY
        self.supabase = get_supabase_client()
        self._cached_jwt = None
        self._jwt_expires_at = 0
        self._generation_semaphore = asyncio.Semaphore(
            max_concurrent or Config.KLING_MAX_CONCURRENT or 3
        )

    def _get_jwt(self) -> str:
        """Get JWT token, caching with 25-min TTL."""
        now = time.time()
        if self._cached_jwt and self._jwt_expires_at > now + 300:  # 5 min buffer
            return self._cached_jwt
        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.access_key,
            "exp": int(now) + 1800,   # 30 min expiry
            "nbf": int(now) - 30      # 30s buffer for clock skew
        }
        self._cached_jwt = jwt.encode(payload, self.secret_key, headers=headers)
        self._jwt_expires_at = now + 1800
        return self._cached_jwt
```

**Models use `model_name` + separate `mode` param:**

| model_name | mode | Notes |
|---|---|---|
| `kling-v2-6` | `pro` | Best quality, `sound: "on"` supported |
| `kling-v2-6` | `std` | Cost-effective |
| `kling-v2-5-turbo` | `std`/`pro` | Fastest |
| `kling-video-o1` | `std`/`pro` | Unified omni model (deferred to V2) |

**Key methods:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `generate_avatar_video(image, sound_file/audio_id, prompt, mode)` | POST `/v1/videos/avatar/image2video` | Talking-head from image + audio (2-300s) |
| `generate_text_to_video(prompt, model_name, mode, duration, ...)` | POST `/v1/videos/text2video` | B-roll, scenes (5s or 10s) |
| `generate_image_to_video(image, prompt, model_name, mode, ...)` | POST `/v1/videos/image2video` | Animate still image |
| `identify_faces(video_id/video_url)` | POST `/v1/videos/identify-face` | Step 1 of lip-sync (sync response, returns face data) |
| `apply_lip_sync(session_id, face_id, audio, ...)` | POST `/v1/videos/advanced-lip-sync` | Step 2 of lip-sync (wraps into `face_choose` array) |
| `create_multi_shot(element_frontal_image)` | POST `/v1/general/ai-multi-shot` | 3 angles from 1 image for element consistency |
| `poll_task(task_id, endpoint_type: KlingEndpoint)` | GET `{endpoint}/{task_id}` | Poll with exponential backoff, 10-min timeout |
| `download_and_store(video_url, generation_id)` | -- | Kling CDN -> Supabase |

**Deferred from MVP** (moved to V2):
- `extend_video` -- only works with v1.x model outputs, our default is v2.6
- Omni Video (`kling-video-o1`) -- complex unified interface

**CRITICAL implementation details:**
- **Base64 prefix stripping**: Kling API requires raw Base64 only -- NO `data:image/...;base64,` prefix. Strip on EVERY image/audio parameter.
- **Duration is STRING**: `Literal["5", "10"]` not int.
- **cfg_scale**: Only for v1.x models. Auto-omit for v2.x.
- **Mutual exclusions**: `sound_file` vs `audio_id`, `image_tail` vs `camera_control`.
- **Lip-sync two-step**: `identify_faces()` is synchronous (returns immediately), `apply_lip_sync()` is async (needs polling).
- **Concurrency semaphore**: Prevents exceeding account-level Kling concurrent task limit.

**Avatar video input requirements:**
- Image: front-facing, clear face, min 300px, ratio 1:2.5~2.5:1, JPEG/PNG, <=10MB
- Audio: MP3/WAV/M4A/AAC, 2-300 seconds, <=5MB
- Lip-sync audio: MP3/WAV/M4A, 2-60 seconds (NOT 300s like avatar!), <=5MB

**Text-to-video parameters:**
- `prompt`: max 2500 chars (required)
- `model_name`: `kling-v2-6` (default), `kling-v2-5-turbo`
- `mode`: `std` or `pro`
- `duration`: `"5"` or `"10"` (STRING, not int)
- `aspect_ratio`: `16:9`, `9:16`, `1:1`
- `negative_prompt`: max 2500 chars
- `sound`: `"on"`/`"off"` (native audio, v2.6+ only)
- `cfg_scale`: 0-1 (v1.x ONLY, auto-omitted for v2.x)

**Task status flow:** `submitted → processing → succeed/failed`

**Additional app-level status:** `awaiting_face_selection` (lip-sync between step 1 and step 2)

**Cost control (from QA review):**
- `UsageLimitService.enforce_limit()` called BEFORE every API call
- Estimated cost displayed to user before generation
- Max cost per single operation: configurable (default $25)
- DB record created with `status=pending` BEFORE API call
- Retry with exponential backoff on transient errors (429, 500, 503)
- Download generated video immediately (Kling CDN URLs expire after 30 days)

### Error Handling

| HTTP | Code | Meaning | Retry? | Max Retries | Action |
|------|------|---------|--------|-------------|--------|
| 429 | 1303 | Concurrent task limit | Yes | 5 | Exponential backoff (2s, 4s, 8s, 16s, 32s) |
| 429 | 1302 | Rate limit | Yes | 5 | Exponential backoff |
| 400 | 1301 | Content safety filter | No | 0 | Store `error_code=1301`, show user: "Content safety filter triggered" |
| 401 | 1004 | JWT expired | Yes | 1 | Invalidate JWT cache, regenerate, retry once |
| 500 | 5000 | Server error | Yes | 3 | Exponential backoff (2s, 4s, 8s) |
| 503 | 5001 | Maintenance | Yes | 3 | Exponential backoff |

**Content Safety UX:**
- 1301: "Content safety filter triggered. Try modifying your prompt or image."
- 1303 exhausted: "Service busy. Please try again in a few minutes."
- 5000: "Kling service error. This is temporary -- try again."

**Download failure recovery:** If Kling CDN download fails after generation succeeds, store `download_status='failed'` with CDN URL preserved. URLs valid for 30 days. Background retry job can periodically check for `status=succeed, download_status=failed`.

### API Response Schemas

**Create response** (all endpoints):
```json
{
    "code": 0,
    "message": "string",
    "request_id": "string",
    "data": {
        "task_id": "string",
        "task_status": "submitted",
        "task_info": { "external_task_id": "string" },
        "created_at": 1722769557708,
        "updated_at": 1722769557708
    }
}
```

**Query response** (on succeed):
```json
{
    "code": 0,
    "data": {
        "task_id": "string",
        "task_status": "succeed",
        "task_status_msg": "string",
        "final_unit_deduction": "string",
        "task_result": {
            "videos": [{ "id": "string", "url": "string", "duration": "string" }]
        }
    }
}
```

**Identify-face response** (synchronous, not async task):
```json
{
    "code": 0,
    "data": {
        "session_id": "string",
        "face_data": [{
            "face_id": "string",
            "face_image": "url",
            "start_time": 0,
            "end_time": 5200
        }]
    }
}
```

**Multi-shot query response**:
```json
{
    "data": {
        "task_result": {
            "images": [
                { "index": 0, "url": "string" },
                { "index": 1, "url": "string" },
                { "index": 2, "url": "string" }
            ]
        }
    }
}
```

Video URLs expire after 30 days. Download to Supabase immediately after `succeed`.

### Lip-Sync Workflow Design

Two-step process with two separate DB records:

1. User triggers "Identify Faces" → creates `kling_video_generations` record with `generation_type='identify_face'`, `status='awaiting_face_selection'`
2. Store `lip_sync_face_data` JSONB and `lip_sync_session_expires_at` (now + 24h)
3. UI shows face thumbnails with time ranges
4. User selects face → creates a NEW record with `generation_type='lip_sync'`, `parent_generation_id` pointing to step 1
5. Poll step 2 task → download result

Two separate DB records (not one overloaded record) ensures clean error recovery.

### Multi-Shot Image Storage

AI Multi-Shot output (3 angle images) downloaded immediately to Supabase:
- Path: `kling-videos/{generation_id}/multi_shot_{0,1,2}.png`
- Stored in `multi_shot_images` JSONB: `[{index: 0, storage_path: "...", kling_url: "..."}]`
- Referenced by downstream image-to-video calls as the `image` parameter

### Database Migration: `migrations/2026-02-25_kling_generations.sql`

```sql
CREATE TABLE kling_video_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    avatar_id UUID REFERENCES brand_avatars(id),
    candidate_id UUID REFERENCES video_recreation_candidates(id),
    parent_generation_id UUID REFERENCES kling_video_generations(id),

    -- Request
    generation_type TEXT NOT NULL,       -- 'avatar', 'text_to_video', 'image_to_video', 'identify_face', 'lip_sync', 'video_extend', 'multi_shot'
    model_name TEXT,                     -- 'kling-v2-6', etc. (NULL for avatar, identify_face)
    mode TEXT DEFAULT 'std',
    prompt TEXT,
    negative_prompt TEXT,
    input_image_url TEXT,
    input_audio_url TEXT,
    duration TEXT,                       -- STRING: "5" or "10" (matches API)
    aspect_ratio TEXT,
    cfg_scale FLOAT,
    sound TEXT DEFAULT 'off',

    -- Kling task tracking
    kling_task_id TEXT,
    kling_external_task_id TEXT,
    kling_request_id TEXT,
    status TEXT DEFAULT 'pending',      -- pending, submitted, processing, succeed, failed, awaiting_face_selection, cancelled

    -- Lip-sync specific
    lip_sync_session_id TEXT,
    lip_sync_session_expires_at TIMESTAMPTZ,
    lip_sync_face_id TEXT,
    lip_sync_face_data JSONB,

    -- Multi-shot specific
    multi_shot_images JSONB,

    -- Result
    video_url TEXT,                     -- Kling CDN output URL (expires in 30 days)
    video_storage_path TEXT,           -- Supabase storage (persistent)
    download_status TEXT DEFAULT 'pending',
    error_message TEXT,
    error_code INTEGER,
    task_status_msg TEXT,

    -- Cost
    estimated_cost_usd FLOAT,
    actual_kling_units TEXT,
    generation_time_seconds FLOAT,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_kling_brand ON kling_video_generations(brand_id);
CREATE INDEX idx_kling_org ON kling_video_generations(organization_id);
CREATE INDEX idx_kling_status ON kling_video_generations(status);
CREATE INDEX idx_kling_candidate ON kling_video_generations(candidate_id);
CREATE INDEX idx_kling_task_id ON kling_video_generations(kling_task_id);
CREATE INDEX idx_kling_parent ON kling_video_generations(parent_generation_id);
```

### Pre-Sprint Blockers (must verify before coding):
- [ ] Kling developer account created at `app.klingai.com/global/dev`
- [ ] `KLING_ACCESS_KEY` and `KLING_SECRET_KEY` obtained and added to `.env`
- [ ] Config.py updated with Kling env vars and unit costs
- [ ] `PyJWT` in `requirements.txt` (already present: v2.10.1)
- [ ] Create `kling-videos` Supabase storage bucket
- [ ] Run migration to create `kling_video_generations` table
- [ ] Verify existing Apify Instagram actor still works (Sprint 1 Track A dependency)

---

## Phase 4: Video Recreation Workflow (Sprint 3-4, Weeks 3-4)

**Goal:** Score candidates, adapt storyboards, generate recreation videos with audio-first workflow.

### Database Migration: `migrations/2026-02-25_video_candidates.sql`

```sql
CREATE TABLE video_recreation_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    post_id UUID NOT NULL REFERENCES posts(id),
    analysis_id UUID REFERENCES ad_video_analysis(id),
    status TEXT DEFAULT 'candidate',    -- candidate, approved, rejected, generating, completed
    -- Scoring (extensible JSONB)
    composite_score FLOAT,
    score_components JSONB,             -- {"engagement": 0.8, "hook_quality": 0.7, ...}
    scoring_version TEXT DEFAULT 'v1',
    scoring_notes TEXT,
    -- Scene classification
    has_talking_head BOOLEAN DEFAULT false,
    scene_types JSONB,                  -- ["talking_head", "broll_product", "broll_lifestyle"]
    -- Recreation plan
    adapted_storyboard JSONB,           -- LLM-adapted storyboard for our brand
    production_storyboard JSONB,        -- Detailed shot sheet from Pass 2
    adapted_hook TEXT,
    adapted_script TEXT,
    text_overlay_instructions JSONB,    -- instructions for human editor
    -- Avatar & generation
    avatar_id UUID REFERENCES brand_avatars(id),
    generation_engine TEXT,             -- 'veo', 'kling', 'mixed'
    target_aspect_ratio TEXT DEFAULT '9:16',
    -- Audio (audio-first workflow)
    audio_segments JSONB,               -- [{scene_idx, audio_storage_path, duration_sec}]
    total_audio_duration_sec FLOAT,
    -- Output
    generated_clips JSONB DEFAULT '[]', -- [{scene_idx, generation_id, storage_path, engine}]
    final_video_path TEXT,              -- concatenated final video
    final_video_duration_sec FLOAT,
    total_generation_cost_usd FLOAT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_rec_candidates_brand ON video_recreation_candidates(brand_id);
CREATE INDEX idx_rec_candidates_status ON video_recreation_candidates(status);
```

### New Service: `viraltracker/services/video_recreation_service.py`

**Orchestrates the full recreation workflow.**

**Scoring (initial weights, calibratable later via ScorerWeightLearningService):**
| Factor | Weight | Source |
|--------|--------|--------|
| Engagement | 0.30 | `posts.outlier_score` |
| Hook quality | 0.25 | Gemini analysis hook effectiveness |
| Recreation feasibility | 0.25 | LLM assessment (penalizes multi-person, animals, complex interactions) |
| Avatar compatibility | 0.20 | Talking-head + we have a matching brand avatar |

**Audio-first workflow (from AI Video Production review):**
```
1. Adapt storyboard → brand-specific script/dialogue
2. Generate audio segments (ElevenLabs) for each dialogue/voiceover scene
3. Get exact durations → determine VEO/Kling clip durations per scene
4. Scene type routing:
   - Talking-head scenes → Kling Avatar v2 (image + audio)
   - Avatar action scenes → VEO 3.1 (with reference images)
   - B-roll scenes → VEO 3.1 text-to-video
5. Generate video clips (one per scene)
6. HUMAN CHECKPOINT: preview clips, approve or re-generate
7. Concatenate clips (FFmpeg concat filter from comic_render_service)
8. Mix background music (optional)
9. Output: final video + text overlay instructions JSON + cost report
```

**Key methods:**
| Method | Purpose |
|--------|---------|
| `score_candidates(brand_id)` | Score all analyzed outlier videos |
| `approve_candidate(candidate_id)` | Move to approved, trigger Pass 2 analysis |
| `reject_candidate(candidate_id)` | Mark rejected |
| `adapt_storyboard(candidate_id)` | LLM-adapted storyboard for brand |
| `generate_audio_segments(candidate_id)` | ElevenLabs audio for each scene |
| `generate_video_clips(candidate_id)` | Scene-by-scene generation (VEO/Kling) |
| `concatenate_clips(candidate_id)` | FFmpeg final assembly |
| `get_cost_estimate(candidate_id)` | Estimate before generation |

**Scene splitting rules (from AI Video Production review):**
- Scenes 3-8s → single VEO clip (nearest duration: 4, 6, 8)
- Scenes 8-16s → split into 2 clips at natural cut point
- Kling Avatar: 5-30s optimal (longer scenes natively, major advantage)
- Never split mid-sentence for talking-head scenes

---

## Phase 5: Video Studio UI (Sprint 4-5, Weeks 4-5)

**Goal:** Streamlit UI for the full workflow. Read-only storyboard for V1.

### UI Page: `viraltracker/ui/pages/51_🎬_Video_Studio.py`

**Tabs:**

1. **Candidates** — Scored recreation candidates
   - Cards: thumbnail, engagement stats, composite score breakdown, hook preview, talking-head flag
   - Approve / reject buttons
   - Filter by score, post type, account, has_talking_head

2. **Recreation** — Generate from an approved candidate (read-only storyboard for V1)
   - View original storyboard (from analysis) — read-only
   - View adapted storyboard (LLM-generated) — read-only
   - Script/dialogue display
   - Text overlay instructions display (for human editor)
   - Select avatar (reuses existing AvatarService + brand_avatars)
   - Upload reference images (front + side view) via existing avatar system
   - Choose engine per scene type: auto (recommended) / VEO only / Kling only
   - Side-by-side cost estimate: VEO vs Kling vs Mixed
   - "Generate Audio" button → "Generate Video Clips" button → "Assemble" button
   - Progress indicator per scene

3. **History** — All generated recreation videos
   - Grid of final videos with status, cost, link to original IG post
   - Individual clip previews
   - Download / share
   - Text overlay instructions download (JSON)

---

## Feature Gating & Navigation

Add to `viraltracker/services/feature_service.py`:
```python
FeatureKey.VIDEO_TOOLS = "video_tools"  # Opt-in
```

Add to `viraltracker/ui/nav.py` (new "Video Tools" section):
```python
("50_📸_Instagram_Content", "Instagram Content", FeatureKey.VIDEO_TOOLS),
("51_🎬_Video_Studio", "Video Studio", FeatureKey.VIDEO_TOOLS),
("47_🎬_Veo_Avatars", "Veo Avatars", FeatureKey.VEO_AVATARS),  # moved here
```

---

## New Dependencies & Environment Variables

```
# Already in requirements.txt
PyJWT==2.10.1       # JWT token generation for Kling API auth
httpx==0.28.1       # HTTP client for all Kling API calls
Pillow>=10.0.0      # Image dimension validation

# New env vars (add to .env)
KLING_ACCESS_KEY=   # Kling API access key (from app.klingai.com/global/dev)
KLING_SECRET_KEY=   # Kling API secret key
KLING_MAX_CONCURRENT=3  # Max concurrent Kling generation tasks
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `migrations/2026-02-25_instagram_content.sql` | Watched accounts, media, posts table extensions |
| `migrations/2026-02-25_video_analysis_extensions.sql` | Generalize ad_video_analysis + image analysis table |
| `migrations/2026-02-25_kling_generations.sql` | Kling generation tracking (full schema with lip-sync, multi-shot) |
| `migrations/2026-02-25_video_candidates.sql` | Recreation candidates |
| `viraltracker/services/instagram_content_service.py` | Scraping extension, outliers, media download |
| `viraltracker/services/instagram_analysis_service.py` | Two-pass Gemini analysis |
| `viraltracker/services/video_generation_protocol.py` | Shared VEO/Kling/Sora interface |
| `viraltracker/services/kling_models.py` | Pydantic models (KlingEndpoint enum, request/response models, Literal["5","10"] duration) |
| `viraltracker/services/kling_video_service.py` | Kling via native API (api-singapore.klingai.com) |
| `viraltracker/services/video_recreation_service.py` | Recreation orchestration |
| `viraltracker/ui/pages/50_📸_Instagram_Content.py` | Content library page |
| `viraltracker/ui/pages/51_🎬_Video_Studio.py` | Recreation studio page |

## Files to Modify

| File | Change |
|------|--------|
| `viraltracker/services/feature_service.py` | Add `VIDEO_TOOLS` feature key |
| `viraltracker/ui/nav.py` | Add Video Tools section |
| `viraltracker/core/config.py` | Add `KLING_ACCESS_KEY`, `KLING_SECRET_KEY`, `KLING_MAX_CONCURRENT`, unit costs |
| `viraltracker/agent/dependencies.py` | Add new services (V2: agent tools) |

---

## Sprint Plan (1-week sprints)

### Sprint 1 (Week 1): Foundation — Parallel Tracks

**Track A: Instagram Content Library**
- DB migration (watched accounts, media, posts extensions)
- `InstagramContentService` (wraps existing scraper + outlier detection + media download)
- Feature gating + navigation

**Track B: Kling Service (independent, parallelizable)**
- `PyJWT` + `httpx` dependencies (already present), `KlingVideoService` skeleton
- DB migration for `kling_video_generations`
- Smoke test against Kling native API (`api-singapore.klingai.com`)
- `VideoGenerationProtocol` definition + `kling_models.py`

### Sprint 2 (Week 2): Content Library UI + Kling Completion

- `50_📸_Instagram_Content.py` (watched accounts + content library + top content tabs)
- Kling service completion (avatar video, text-to-video, image-to-video, lip-sync, multi-shot)
- Kling manual test via script

### Sprint 3 (Week 3): Content Analysis

- DB migration (generalize `ad_video_analysis` + image analysis table)
- `InstagramAnalysisService` (Pass 1: Flash structural extraction)
- Automated consistency checks (VA-1 through VA-8)
- Add Analysis tab to page 50
- Integration test: analyze 5-10 real scraped videos

### Sprint 4 (Week 4): Recreation Workflow

- DB migration (video recreation candidates)
- `VideoRecreationService` (scoring, storyboard adaptation, audio-first generation)
- Recreation workflow: score → adapt → audio → generate clips → concatenate
- First end-to-end demo

### Sprint 5 (Week 5): Studio UI + Polish

- `51_🎬_Video_Studio.py` (candidates, recreation, history tabs)
- Pass 2 production analysis (Pro model, for approved candidates)
- Edge case handling, error states, cost tracking verification
- Multi-tenant audit (org_id on all queries)
- Documentation updates

---

## Deferred to V2

| Feature | Why Defer |
|---------|-----------|
| Storyboard editor (editable UI) | Read-only is sufficient for V1; editing adds massive UI complexity |
| Full avatar fingerprinting across posts | Simple `has_talking_head` boolean sufficient for V1 |
| PydanticAI agent tools | Thin wrappers, can be added in 1 day after services stabilize |
| Scoring calibration via Thompson Sampling | Need 30+ outcome data points per brand first |
| Human review queue for analysis quality | Build after golden set of verified analyses exists |
| Prompt A/B testing framework | Need baseline quality metrics first |
| Omni Video (`kling-video-o1`) | Powerful unified model but complex; add after individual endpoints stable |
| Motion Control endpoint | Advanced character animation -- nice-to-have |
| Multi-Elements (video editing) | Session-based editing, complex workflow |
| Video Effects (222 effects) | Nice-to-have, not critical for MVP |
| Custom Voice creation via Kling | Use preset voices or ElevenLabs for MVP |
| TTS via Kling | Use ElevenLabs instead |
| Callback URL integration | Polling is simpler for MVP |
| Video Extension (`extend_video`) | Only works with v1.x model outputs; our default is v2.6 |
| `static_mask`/`dynamic_masks` for image2video | Motion brush feature, defer to V2 |
| `voice_list` for image2video v2.6 | Voice control for image2video, defer to V2 |

---

## Verification Per Sprint

1. `python3 -m py_compile` all new/modified files
2. Run Streamlit page, verify UI renders and filters work
3. Test with real IG account scrape + media download
4. Test Gemini analysis on scraped video (check VA-1 through VA-8 pass)
5. Test Kling generation with test avatar + audio
6. Verify all endpoint paths match official docs
7. Verify status enum uses `submitted/processing/succeed/failed` (not old 5-step flow)
8. Verify model names use hyphen format (`kling-v2-6`, not `kling-v2.6`)
9. Verify duration params are `Literal["5", "10"]` strings in models
10. Verify base64 prefix stripping on all image/audio inputs
11. Verify mutual exclusion validation on all applicable methods
12. Verify lip-sync two-step workflow with `face_choose` array wrapping
13. Verify no references to `fal.ai` or `fal-client` remain
14. Verify org_id filtering on ALL new queries
15. Verify `UsageTracker` records created for Gemini + Kling calls
16. Verify cost estimates match actual costs within 20%
17. Smoke test: generate one avatar video, one text-to-video, one image-to-video
18. Smoke test: identify-face on a generated video, then apply lip-sync

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Kling API downtime | VEO 3.1 as fallback for all generation modes (VideoGenerationProtocol enables engine switching) |
| IG CDN URLs expire | Download immediately after scrape, track `cdn_url_captured_at` |
| Gemini analysis timeout on long videos | 90-second max video cutoff; 300s Gemini timeout |
| Storage explosion | Only download outlier media (~5-10% of posts) |
| Runaway generation costs | `UsageLimitService.enforce_limit()` before every API call; max $25/operation |
| Z-score edge cases (N<3, std=0) | Handle in outlier detection: skip if N<3, all z-score=0 if std=0 |
| Supabase bucket missing | Create buckets in migration or service init |
| Kling CDN download failure | Store `download_status=failed`, CDN URLs valid 30 days, background retry job |
| 1303 concurrent limit exhausted | Semaphore limits local concurrency; exponential backoff for API-level limits |
| JWT clock skew | 30s `nbf` buffer for clock drift between systems |
