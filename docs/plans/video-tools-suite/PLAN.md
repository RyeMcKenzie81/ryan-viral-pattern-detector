# Video Tools Suite - Implementation Plan (v2)

## Context

ViralTracker needs a video content research and recreation pipeline. The goal: scrape AI-focused Instagram accounts, analyze their best-performing content with Gemini, identify reusable patterns (avatars, hooks, storyboards), then recreate similar content using VEO 3.1 and Kling AI with our own brand avatars.

**User decisions:** Apify for IG scraping, Kling AI included in MVP (via fal.ai), per-brand watched accounts, new "Video Tools" section in 50s pages.

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
    ┌────▼────┐     ┌──────▼──────┐  ┌───▼────┐ ┌───▼──────────┐
    │  Apify  │     │ Gemini 3.1  │  │ fal.ai │ │ ElevenLabs   │
    │  (IG)   │     │ (Analysis)  │  │ (Kling)│ │ (Voice/Audio)│
    └─────────┘     └─────────────┘  └────────┘ └──────────────┘
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
9. **Native Kling API**: Direct integration via `api.klingai.com` with JWT auth (not fal.ai gateway)
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

**Goal:** Native Kling AI integration via `api.klingai.com` + shared interface for all video generation engines.

### VideoGenerationProtocol: `viraltracker/services/video_generation_protocol.py`

```python
from typing import Protocol, Optional, List

class VideoGenerationProtocol(Protocol):
    """Shared interface for VEO 3.1, Kling, and Sora."""

    async def generate_from_prompt(
        self, prompt: str, duration_sec: int, aspect_ratio: str,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None
    ) -> "VideoGenerationResult": ...

    async def generate_talking_head(
        self, avatar_image_url: str, audio_url: str,
        prompt: Optional[str] = None
    ) -> "VideoGenerationResult": ...

    async def get_status(self, generation_id: str) -> "VideoGenerationStatus": ...
    async def download_and_store(self, generation_id: str) -> str: ...
```

### New Service: `viraltracker/services/kling_video_service.py`

**Implements `VideoGenerationProtocol`. Direct integration with native Kling API.**

**Authentication:** JWT with HS256 (AccessKey + SecretKey, 30-min expiry)

```python
import jwt
import time
import requests

class KlingVideoService:
    """Kling AI video generation via native API (api.klingai.com)."""

    BASE_URL = "https://api.klingai.com"
    STORAGE_BUCKET = "kling-videos"

    # Endpoints
    TEXT_TO_VIDEO = "/v1/videos/text2video"
    IMAGE_TO_VIDEO = "/v1/videos/image2video"
    AVATAR = "/v1/videos/avatar"          # Avatar talking-head
    LIP_SYNC = "/v1/videos/lip-sync"
    TASK_STATUS = "/v1/videos/{task_id}"
    VIDEO_EXTEND = "/v1/videos/extend"

    # Models
    MODELS = {
        "kling-v2.6-pro": {"mode": "pro", "audio": True},   # Best quality + native audio
        "kling-v2.6-std": {"mode": "std", "audio": True},   # Fast + native audio
        "kling-v2.5-turbo": {"mode": "std", "audio": False}, # Fastest
        "kling-video-o1": {"mode": "pro", "audio": True},   # Unified multimodal
    }

    def __init__(self, access_key: str = None, secret_key: str = None):
        self.access_key = access_key or Config.KLING_ACCESS_KEY
        self.secret_key = secret_key or Config.KLING_SECRET_KEY
        self.supabase = get_supabase_client()
        self._tracker = None
        self._user_id = None
        self._org_id = None

    def _make_jwt(self) -> str:
        """Generate JWT token for Kling API auth."""
        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.access_key,
            "exp": int(time.time()) + 1800,   # 30 min expiry
            "nbf": int(time.time()) - 5        # valid 5s ago
        }
        return jwt.encode(payload, self.secret_key, headers=headers)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._make_jwt()}",
            "Content-Type": "application/json"
        }
```

**Key methods:**
| Method | Endpoint | Purpose | Cost (per 5s) |
|--------|----------|---------|---------------|
| `generate_avatar_video(image_url, audio_url, prompt, mode)` | POST `/v1/videos/avatar` | Talking-head from image + audio | std: $0.052/s, pro: $0.104/s |
| `generate_text_to_video(prompt, duration, aspect_ratio, model, mode)` | POST `/v1/videos/text2video` | B-roll, scenes | std: $0.20, pro: $0.33 |
| `generate_image_to_video(image_url, prompt, duration, model, mode)` | POST `/v1/videos/image2video` | Animate still image | std: $0.20, pro: $0.33 |
| `add_lip_sync(task_id, audio_url)` | POST `/v1/videos/lip-sync` | Lip-sync existing video | varies |
| `extend_video(task_id, prompt)` | POST `/v1/videos/extend` | Extend generated video | varies |
| `poll_task(task_id, timeout=600)` | GET `/v1/videos/{task_id}` | Poll with 10-min max, exponential backoff | - |
| `download_and_store(video_url, generation_id)` | - | Download from Kling CDN → Supabase | - |

**Avatar video input requirements:**
- Image: front-facing, clear face, min 512x512, JPEG/PNG
- Audio: MP3/WAV/AAC, 2-60 seconds, clear speech, max 5MB
- Output: 1080p, 48fps, up to 1 minute
- Languages: English, Japanese, Korean, Chinese

**Text-to-video parameters:**
- `prompt`: max 2500 chars
- `negative_prompt`: max 2500 chars
- `duration`: 5 or 10 seconds (v3.0: 3-15s)
- `aspect_ratio`: 16:9, 9:16, 1:1
- `mode`: "std" or "pro"
- `cfg_scale`: 0-1 (default 0.5)
- `enable_audio`: boolean (native audio generation)

**Task status flow:** `CREATED → QUEUED → RUNNING → FINALIZING → SUCCEEDED/FAILED`

**Cost control (from QA review):**
- `UsageLimitService.enforce_limit()` called BEFORE every API call
- Estimated cost displayed to user before generation
- Max cost per single operation: configurable (default $25)
- DB record created with `status=pending` BEFORE API call
- Retry with exponential backoff on transient errors (429, 500, 503)
- Download generated video immediately (Kling CDN URLs may expire ~30 days)

### Database Migration: `migrations/2026-02-25_kling_generations.sql`

```sql
CREATE TABLE kling_video_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    avatar_id UUID REFERENCES brand_avatars(id),
    candidate_id UUID REFERENCES video_recreation_candidates(id),
    -- Request
    model_name TEXT NOT NULL,           -- kling-v2.6-pro, etc.
    generation_type TEXT NOT NULL,      -- 'avatar', 'text_to_video', 'image_to_video', 'lipsync', 'extend'
    prompt TEXT,
    negative_prompt TEXT,
    mode TEXT DEFAULT 'std',            -- 'std' or 'pro'
    input_image_url TEXT,
    input_audio_url TEXT,
    duration_seconds FLOAT,
    aspect_ratio TEXT,
    cfg_scale FLOAT,
    enable_audio BOOLEAN DEFAULT false,
    -- Response
    kling_task_id TEXT,                 -- Kling's task_id for polling
    status TEXT DEFAULT 'pending',     -- pending, created, queued, running, succeeded, failed
    video_url TEXT,                     -- Kling CDN output URL (may expire)
    video_storage_path TEXT,           -- Supabase storage (persistent)
    error_message TEXT,
    -- Cost
    estimated_cost_usd FLOAT,
    actual_cost_usd FLOAT,
    generation_time_seconds FLOAT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_kling_brand ON kling_video_generations(brand_id);
CREATE INDEX idx_kling_org ON kling_video_generations(organization_id);
CREATE INDEX idx_kling_status ON kling_video_generations(status);
CREATE INDEX idx_kling_candidate ON kling_video_generations(candidate_id);
```

### Pre-Sprint Blockers (must verify before coding):
- [ ] Kling developer account created at `app.klingai.com/global/dev`
- [ ] `KLING_ACCESS_KEY` and `KLING_SECRET_KEY` obtained
- [ ] Verify avatar endpoint is accessible on your Kling plan tier
- [ ] Test existing Apify Instagram actor still works (run 1 account scrape)
- [ ] Create `instagram-media` Supabase storage bucket
- [ ] Create `kling-videos` Supabase storage bucket

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
PyJWT               # JWT token generation for Kling API auth
KLING_ACCESS_KEY=   # Kling API access key (from app.klingai.com/global/dev)
KLING_SECRET_KEY=   # Kling API secret key
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `migrations/2026-02-25_instagram_content.sql` | Watched accounts, media, posts table extensions |
| `migrations/2026-02-25_video_analysis_extensions.sql` | Generalize ad_video_analysis + image analysis table |
| `migrations/2026-02-25_kling_generations.sql` | Kling generation tracking |
| `migrations/2026-02-25_video_candidates.sql` | Recreation candidates |
| `viraltracker/services/instagram_content_service.py` | Scraping extension, outliers, media download |
| `viraltracker/services/instagram_analysis_service.py` | Two-pass Gemini analysis |
| `viraltracker/services/video_generation_protocol.py` | Shared VEO/Kling/Sora interface |
| `viraltracker/services/kling_video_service.py` | Kling via fal.ai |
| `viraltracker/services/video_recreation_service.py` | Recreation orchestration |
| `viraltracker/ui/pages/50_📸_Instagram_Content.py` | Content library page |
| `viraltracker/ui/pages/51_🎬_Video_Studio.py` | Recreation studio page |

## Files to Modify

| File | Change |
|------|--------|
| `viraltracker/services/feature_service.py` | Add `VIDEO_TOOLS` feature key |
| `viraltracker/ui/nav.py` | Add Video Tools section |
| `viraltracker/core/config.py` | Add `KLING_ACCESS_KEY`, `KLING_SECRET_KEY` |
| `viraltracker/agent/dependencies.py` | Add new services (V2: agent tools) |

---

## Sprint Plan (1-week sprints)

### Sprint 1 (Week 1): Foundation — Parallel Tracks

**Track A: Instagram Content Library**
- DB migration (watched accounts, media, posts extensions)
- `InstagramContentService` (wraps existing scraper + outlier detection + media download)
- Feature gating + navigation

**Track B: Kling Service (independent, parallelizable)**
- `fal-client` dependency, `KlingVideoService` skeleton
- DB migration for `kling_video_generations`
- Smoke test against fal.ai API
- `VideoGenerationProtocol` definition

### Sprint 2 (Week 2): Content Library UI + Kling Completion

- `50_📸_Instagram_Content.py` (watched accounts + content library + top content tabs)
- Kling service completion (avatar video, text-to-video, lip-sync modes)
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
| Kling lip-sync mode | Focus on avatar + text-to-video first |
| Scoring calibration via Thompson Sampling | Need 30+ outcome data points per brand first |
| Human review queue for analysis quality | Build after golden set of verified analyses exists |
| Prompt A/B testing framework | Need baseline quality metrics first |

---

## Verification Per Sprint

1. `python3 -m py_compile` all new/modified files
2. Run Streamlit page, verify UI renders and filters work
3. Test with real IG account scrape + media download
4. Test Gemini analysis on scraped video (check VA-1 through VA-8 pass)
5. Test Kling generation with test avatar + audio
6. Verify org_id filtering on ALL new queries
7. Verify `UsageTracker` records created for Gemini + Kling calls
8. Verify cost estimates match actual costs within 20%

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
