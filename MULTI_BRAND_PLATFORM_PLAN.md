# Multi-Brand, Multi-Platform Expansion Plan

**Created:** 2025-10-03
**Goal:** Transform ViralTracker from a single-brand Instagram tool into a multi-brand, multi-platform viral content analysis system.

---

## Current State

### What We Have
- ✅ Instagram scraping and analysis
- ✅ Single database schema (no brand/platform isolation)
- ✅ Yakety Pack hardcoded in video-processor
- ✅ Command-line interface
- ✅ Statistical outlier detection
- ✅ Gemini AI video analysis

### What's Missing
- ❌ Multi-brand support
- ❌ Multi-product support (different products per brand)
- ❌ Multi-platform support (TikTok, YouTube Shorts)
- ❌ Platform-specific nuances handling
- ❌ Cross-platform aggregate analysis
- ❌ Generic brand adaptation system
- ❌ Direct URL analysis (analyze specific videos without scraping)

---

## Database Schema Changes

### New Tables

#### 1. `brands` Table
**Purpose:** Track different brands using the system

```sql
CREATE TABLE brands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  slug text UNIQUE NOT NULL,  -- URL-friendly name
  description text,
  website text,
  created_at timestamptz DEFAULT now()
);
```

**Example Data:**
```
id: uuid-1, name: "Yakety Pack", slug: "yakety-pack"
id: uuid-2, name: "Acme Corp", slug: "acme-corp"
```

---

#### 2. `products` Table
**Purpose:** Track different products per brand

```sql
CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text NOT NULL,  -- URL-friendly name
  description text,
  target_audience text,
  price_range text,
  key_problems_solved jsonb,  -- Array of problem statements
  key_benefits jsonb,          -- Array of benefits
  features jsonb,              -- Array of features
  context_prompt text,         -- Full context for AI adaptation
  created_at timestamptz DEFAULT now(),
  UNIQUE(brand_id, slug)
);

CREATE INDEX idx_products_brand_id ON products(brand_id);
```

**Example Data:**
```json
{
  "id": "uuid-1",
  "brand_id": "uuid-1",
  "name": "Yakety Pack - Core Deck",
  "slug": "core-deck",
  "description": "Conversation cards for gaming families",
  "target_audience": "Parents with gaming kids aged 6-15",
  "price_range": "$39",
  "key_problems_solved": [
    "Screen time arguments",
    "Communication gap with gaming kids",
    "Feeling disconnected from child's interests"
  ],
  "key_benefits": [
    "Better parent-child communication",
    "Understanding child's gaming world",
    "Reducing screen time conflicts"
  ],
  "features": [
    "86 conversation cards",
    "Color-coded for emotional depth",
    "Gaming-specific questions"
  ],
  "context_prompt": "Full AI prompt text..."
}
```

---

#### 3. `platforms` Table
**Purpose:** Track different social media platforms

```sql
CREATE TABLE platforms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  slug text UNIQUE NOT NULL,  -- 'instagram', 'tiktok', 'youtube_shorts'
  scraper_type text,           -- 'apify', 'yt-dlp', 'tiktok-api', etc.
  scraper_config jsonb,        -- Platform-specific scraper configuration
  max_video_length_sec int,    -- Platform limits
  typical_video_length_sec int,
  aspect_ratio text,           -- '9:16', '16:9', etc.
  created_at timestamptz DEFAULT now()
);
```

**Example Data:**
```json
{
  "slug": "instagram",
  "name": "Instagram Reels",
  "scraper_type": "apify",
  "scraper_config": {
    "actor_id": "apify/instagram-scraper",
    "post_types": ["reels"]
  },
  "max_video_length_sec": 90,
  "typical_video_length_sec": 30,
  "aspect_ratio": "9:16"
}
```

---

#### 4. Modified `accounts` Table
**Purpose:** Add platform association

```sql
-- Add columns to existing accounts table
ALTER TABLE accounts ADD COLUMN platform_id uuid REFERENCES platforms(id);
ALTER TABLE accounts ADD COLUMN platform_username text;
ALTER TABLE accounts DROP CONSTRAINT accounts_handle_key;  -- Remove old unique constraint
ALTER TABLE accounts ADD CONSTRAINT accounts_platform_username_unique UNIQUE(platform_id, platform_username);

CREATE INDEX idx_accounts_platform_id ON accounts(platform_id);
```

**Why:** Same username might exist across platforms (e.g., @nike on Instagram AND TikTok)

**Note:** Accounts can be NULL for direct URL imports (when we don't track the full account)

---

#### 5. Modified `posts` Table
**Purpose:** Track which platform post came from and how it was imported

```sql
-- Add platform_id for direct lookup
ALTER TABLE posts ADD COLUMN platform_id uuid REFERENCES platforms(id);
ALTER TABLE posts ADD COLUMN import_source text CHECK (import_source IN ('scrape', 'direct_url', 'csv_import'));
ALTER TABLE posts ADD COLUMN is_own_content boolean DEFAULT false;  -- Track if this is brand's own content
ALTER TABLE posts ALTER COLUMN account_id DROP NOT NULL;  -- Allow NULL for direct URL imports

CREATE INDEX idx_posts_platform_id ON posts(platform_id);
CREATE INDEX idx_posts_import_source ON posts(import_source);
CREATE INDEX idx_posts_is_own_content ON posts(is_own_content);
```

**Why:**
- Allows filtering posts by platform for platform-specific analysis
- Track how videos entered the system (scraped vs. manually added)
- Differentiate brand's own content from competitor content
- Support direct URL imports without needing to track the full account

---

#### 6. `projects` Table (NEW)
**Purpose:** Track content creation projects (brand + product combos we're analyzing)

```sql
CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text UNIQUE NOT NULL,
  description text,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_projects_brand_id ON projects(brand_id);
CREATE INDEX idx_projects_product_id ON projects(product_id);
CREATE INDEX idx_projects_is_active ON projects(is_active);
```

**Example:**
```
Project: "Yakety Pack Instagram Campaign"
brand_id: Yakety Pack
product_id: Core Deck
```

---

#### 7. `project_accounts` Table (NEW)
**Purpose:** Track which accounts each project is monitoring

```sql
CREATE TABLE project_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE,
  priority int DEFAULT 1,  -- 1-5, for sorting
  notes text,
  added_at timestamptz DEFAULT now(),
  UNIQUE(project_id, account_id)
);

CREATE INDEX idx_project_accounts_project_id ON project_accounts(project_id);
CREATE INDEX idx_project_accounts_account_id ON project_accounts(account_id);
```

**Why:** Same account might be relevant to multiple projects

---

#### 7b. `project_posts` Table (NEW)
**Purpose:** Track direct URL imports and manually added posts per project

```sql
CREATE TABLE project_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  post_id uuid REFERENCES posts(id) ON DELETE CASCADE,
  import_method text CHECK (import_method IN ('scrape', 'direct_url', 'csv_batch')),
  is_own_content boolean DEFAULT false,
  notes text,
  added_at timestamptz DEFAULT now(),
  UNIQUE(project_id, post_id)
);

CREATE INDEX idx_project_posts_project_id ON project_posts(project_id);
CREATE INDEX idx_project_posts_post_id ON project_posts(post_id);
CREATE INDEX idx_project_posts_is_own_content ON project_posts(is_own_content);
```

**Why:**
- Track posts that were added directly by URL (not from account scraping)
- Support analyzing brand's own content vs. competitor content
- Enable "analyze this specific video" workflow without scraping entire account

---

#### 8. Modified `video_analysis` Table
**Purpose:** Store platform-specific analysis

```sql
-- Add platform context
ALTER TABLE video_analysis ADD COLUMN platform_id uuid REFERENCES platforms(id);
ALTER TABLE video_analysis ADD COLUMN platform_specific_metrics jsonb;  -- TikTok sounds, IG music, etc.

CREATE INDEX idx_video_analysis_platform_id ON video_analysis(platform_id);
```

**Example platform_specific_metrics:**
```json
{
  "tiktok": {
    "sound_id": "12345",
    "sound_name": "Trending Audio",
    "effects_used": ["Green Screen", "Duet"],
    "hashtags_count": 15
  },
  "instagram": {
    "reel_template_used": false,
    "music_id": "67890",
    "filter_name": "Clarendon"
  },
  "youtube_shorts": {
    "thumbnail_style": "text_overlay",
    "chapters": false
  }
}
```

---

#### 9. `product_adaptations` Table (NEW)
**Purpose:** Store AI-generated adaptations for different products

```sql
CREATE TABLE product_adaptations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id uuid REFERENCES posts(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE CASCADE,
  video_analysis_id uuid REFERENCES video_analysis(id) ON DELETE CASCADE,

  -- Scoring
  hook_relevance_score decimal(3,1),      -- 1-10
  audience_match_score decimal(3,1),      -- 1-10
  transition_ease_score decimal(3,1),     -- 1-10
  viral_replicability_score decimal(3,1), -- 1-10
  overall_score decimal(3,1),             -- 1-10

  -- Adaptation content
  adapted_hook text,
  adapted_script text,
  storyboard jsonb,
  text_overlays jsonb,
  transition_strategy text,
  best_use_case text,
  production_notes text,

  -- Metadata
  ai_model text DEFAULT 'gemini-2.5-flash',
  ai_tokens_used int,
  created_at timestamptz DEFAULT now(),

  UNIQUE(post_id, product_id)
);

CREATE INDEX idx_product_adaptations_product_id ON product_adaptations(product_id);
CREATE INDEX idx_product_adaptations_post_id ON product_adaptations(post_id);
CREATE INDEX idx_product_adaptations_overall_score ON product_adaptations(overall_score DESC);
```

**Why:** Same viral video might be adaptable for multiple products with different strategies

---

### Modified Schema Summary

**Before:**
```
accounts (handle)
  └─ posts (post_url, views, etc.)
      ├─ post_review (outlier, yakety_hook_ideas)
      ├─ video_processing_log
      └─ video_analysis
```

**After:**
```
brands (name, slug)
  └─ products (name, slug, context_prompt)
      └─ projects (brand + product combo)
          └─ project_accounts
              └─ accounts (platform_id, platform_username)
                  └─ posts (platform_id, post_url, views)
                      ├─ post_review (generic review fields)
                      ├─ video_processing_log
                      ├─ video_analysis (platform_id, platform_specific_metrics)
                      └─ product_adaptations (product_id, scores, adapted_content)

platforms (slug, name, scraper_config)
  ├─ accounts (platform_id)
  ├─ posts (platform_id)
  └─ video_analysis (platform_id)
```

---

## CLI Changes

### New Command Structure

```bash
# Brand management
./viraltracker brand create --name "Yakety Pack" --description "..."
./viraltracker brand list
./viraltracker brand show yakety-pack

# Product management
./viraltracker product create \
  --brand yakety-pack \
  --name "Core Deck" \
  --target-audience "Parents with gaming kids 6-15" \
  --context-file yakety_pack_context.txt

./viraltracker product list --brand yakety-pack
./viraltracker product show yakety-pack/core-deck

# Project management (brand + product + accounts to track)
./viraltracker project create \
  --name "Yakety Pack Instagram Campaign" \
  --brand yakety-pack \
  --product core-deck

./viraltracker project add-accounts yakety-pack-ig \
  --platform instagram \
  --file usernames.csv

./viraltracker project add-accounts yakety-pack-tiktok \
  --platform tiktok \
  --file tiktok_accounts.csv

./viraltracker project list
./viraltracker project show yakety-pack-ig

# ===== NEW: Direct URL Import =====
# Import single URL
./viraltracker import-url \
  --project yakety-pack-ig \
  --url "https://www.instagram.com/p/ABC123/" \
  --own-content  # Optional flag if this is brand's own video

# Import multiple URLs from file
./viraltracker import-urls \
  --project yakety-pack-ig \
  --file my_videos.txt \
  --own-content

# Import CSV with metadata
./viraltracker import-csv \
  --project yakety-pack-ig \
  --file videos.csv
# CSV format: url,platform,is_own_content,notes

# Example: Analyze brand's existing content
./viraltracker import-urls \
  --project yakety-pack-tiktok \
  --file our_published_videos.txt \
  --own-content \
  --notes "Published Q3 2025"

# Example: Analyze competitor content
./viraltracker import-urls \
  --project yakety-pack-ig \
  --file competitor_videos.txt \
  --notes "Top performing competitor content"
# ===================================

# Scraping (now project-based)
./viraltracker scrape \
  --project yakety-pack-ig \
  --days 120

# Multi-platform scraping
./viraltracker scrape \
  --project yakety-pack-tiktok \
  --platform tiktok \
  --days 30

# Analysis (same as before, but project-aware)
./viraltracker analyze --project yakety-pack-ig --sd-threshold 3.0

# Cross-platform analysis
./viraltracker analyze \
  --project yakety-pack-ig \
  --project yakety-pack-tiktok \
  --aggregate

# Export (now includes product adaptations)
./viraltracker export \
  --project yakety-pack-ig \
  --product core-deck \
  --format adaptations

# Video processing (now platform-aware)
./viraltracker process-videos \
  --project yakety-pack-ig \
  --unprocessed-outliers

# AI Analysis (now product-based)
./viraltracker analyze-videos \
  --project yakety-pack-ig \
  --product core-deck \
  --limit 10

# ===== NEW: Analyze specific imported videos =====
# Analyze own content
./viraltracker analyze-videos \
  --project yakety-pack-ig \
  --own-content \
  --product core-deck

# Analyze direct URL imports only
./viraltracker analyze-videos \
  --project yakety-pack-ig \
  --import-source direct_url

# Compare own vs competitor content
./viraltracker compare-content \
  --project yakety-pack-ig \
  --own vs competitors
# =================================================

# Generate adaptations for different product
./viraltracker analyze-videos \
  --project yakety-pack-ig \
  --product expansion-pack

# Cross-platform aggregate insights
./viraltracker aggregate-insights \
  --brand yakety-pack \
  --platforms instagram,tiktok,youtube_shorts
```

---

## Code Architecture Changes

### 1. New Module Structure

```
viraltracker/
├── core/
│   ├── __init__.py
│   ├── database.py          # Supabase client
│   ├── config.py            # Configuration management
│   └── models.py            # Pydantic models for all tables
│
├── scrapers/
│   ├── __init__.py
│   ├── base.py              # Abstract scraper class
│   ├── instagram.py         # Instagram scraper (Apify)
│   ├── tiktok.py            # TikTok scraper
│   └── youtube_shorts.py    # YouTube Shorts scraper
│
├── importers/
│   ├── __init__.py
│   ├── base.py              # Abstract importer class
│   ├── url_importer.py      # Direct URL import (yt-dlp metadata)
│   ├── csv_importer.py      # Bulk CSV import
│   └── metadata_extractor.py # Extract metadata from URLs
│
├── analysis/
│   ├── __init__.py
│   ├── statistical.py       # Outlier detection
│   ├── video_analyzer.py    # Gemini video analysis
│   ├── product_adapter.py   # Product adaptation generation
│   └── content_comparator.py # Compare own vs competitor content
│
├── cli/
│   ├── __init__.py
│   ├── main.py              # Main CLI entry point
│   ├── brand.py             # Brand commands
│   ├── product.py           # Product commands
│   ├── project.py           # Project commands
│   ├── scrape.py            # Scraping commands
│   ├── import_urls.py       # URL import commands
│   ├── analyze.py           # Analysis commands
│   └── export.py            # Export commands
│
└── utils/
    ├── __init__.py
    ├── logger.py
    ├── validators.py
    └── url_parser.py        # Parse URLs to detect platform
```

---

### 2. Platform Abstraction

**Base Scraper Interface:**

```python
from abc import ABC, abstractmethod
from typing import List, Dict

class BaseScraper(ABC):
    """Abstract base class for platform scrapers"""

    def __init__(self, platform_config: Dict):
        self.platform_config = platform_config
        self.platform_slug = platform_config['slug']

    @abstractmethod
    async def scrape_account(
        self,
        username: str,
        days_back: int,
        post_type: str = 'all'
    ) -> List[Dict]:
        """Scrape posts from an account"""
        pass

    @abstractmethod
    def normalize_post_data(self, raw_post: Dict) -> Dict:
        """Convert platform-specific data to standard format"""
        pass

    @abstractmethod
    def extract_platform_metrics(self, raw_post: Dict) -> Dict:
        """Extract platform-specific metrics"""
        pass

    @abstractmethod
    async def get_post_metadata(self, post_url: str) -> Dict:
        """Get metadata for a single post URL (for direct imports)"""
        pass
```

**Base URL Importer:**

```python
from abc import ABC, abstractmethod
from typing import Dict, Optional
import yt_dlp

class BaseURLImporter(ABC):
    """Abstract base class for URL importers"""

    def __init__(self, platform_slug: str):
        self.platform_slug = platform_slug

    async def import_url(self, url: str, project_id: str, is_own_content: bool = False) -> Dict:
        """Import a single URL into the project"""

        # 1. Validate URL is from correct platform
        if not self.validate_url(url):
            raise ValueError(f"Invalid {self.platform_slug} URL: {url}")

        # 2. Extract metadata using yt-dlp
        metadata = await self.extract_metadata(url)

        # 3. Normalize to standard format
        normalized = self.normalize_metadata(metadata)

        # 4. Save to database
        post = self._save_post(normalized, project_id, is_own_content)

        return post

    @abstractmethod
    def validate_url(self, url: str) -> bool:
        """Check if URL is valid for this platform"""
        pass

    async def extract_metadata(self, url: str) -> Dict:
        """Extract metadata using yt-dlp"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info

    @abstractmethod
    def normalize_metadata(self, metadata: Dict) -> Dict:
        """Convert yt-dlp metadata to standard format"""
        pass
```

**Instagram URL Importer:**

```python
class InstagramURLImporter(BaseURLImporter):
    def __init__(self):
        super().__init__('instagram')

    def validate_url(self, url: str) -> bool:
        return 'instagram.com' in url and ('/p/' in url or '/reel/' in url)

    def normalize_metadata(self, metadata: Dict) -> Dict:
        return {
            'post_url': metadata['webpage_url'],
            'post_id': metadata.get('id'),
            'views': metadata.get('view_count', 0),
            'likes': metadata.get('like_count', 0),
            'comments': metadata.get('comment_count', 0),
            'caption': metadata.get('description', ''),
            'posted_at': metadata.get('timestamp'),
            'length_sec': metadata.get('duration'),
            'platform_username': metadata.get('uploader_id'),
        }
```

**Instagram Scraper:**

```python
class InstagramScraper(BaseScraper):
    def normalize_post_data(self, raw_post: Dict) -> Dict:
        return {
            'post_url': raw_post['url'],
            'post_id': raw_post['shortCode'],
            'views': raw_post.get('videoViewCount', 0),
            'likes': raw_post.get('likesCount', 0),
            'comments': raw_post.get('commentsCount', 0),
            'caption': raw_post.get('caption', ''),
            'posted_at': raw_post.get('timestamp'),
            'length_sec': raw_post.get('videoLength'),
        }

    def extract_platform_metrics(self, raw_post: Dict) -> Dict:
        return {
            'instagram': {
                'reel_template_used': raw_post.get('isReelTemplate'),
                'music_id': raw_post.get('musicId'),
                'filter_name': raw_post.get('filterName'),
            }
        }
```

**TikTok Scraper:**

```python
class TikTokScraper(BaseScraper):
    def normalize_post_data(self, raw_post: Dict) -> Dict:
        return {
            'post_url': raw_post['video_url'],
            'post_id': raw_post['id'],
            'views': raw_post.get('play_count', 0),
            'likes': raw_post.get('digg_count', 0),
            'comments': raw_post.get('comment_count', 0),
            'caption': raw_post.get('desc', ''),
            'posted_at': raw_post.get('create_time'),
            'length_sec': raw_post.get('duration'),
        }

    def extract_platform_metrics(self, raw_post: Dict) -> Dict:
        return {
            'tiktok': {
                'sound_id': raw_post.get('music', {}).get('id'),
                'sound_name': raw_post.get('music', {}).get('title'),
                'effects_used': raw_post.get('effect_stickers', []),
                'hashtags_count': len(raw_post.get('hashtags', [])),
            }
        }
```

---

### 3. Product Adaptation System

**Generic Product Adapter:**

```python
class ProductAdapter:
    """Generate product adaptations from viral videos"""

    def __init__(self, product_id: str, supabase: Client, gemini_client):
        self.product = self._load_product(product_id)
        self.supabase = supabase
        self.gemini = gemini_client

    def _load_product(self, product_id: str) -> Dict:
        """Load product details from database"""
        result = self.supabase.table('products').select('*').eq('id', product_id).single().execute()
        return result.data

    def generate_adaptation(self, post_id: str, video_analysis: Dict) -> Dict:
        """Generate product-specific adaptation using AI"""

        prompt = self._build_adaptation_prompt(video_analysis)

        response = self.gemini.generate_content(prompt)
        adaptation = self._parse_adaptation_response(response)

        # Save to product_adaptations table
        self._save_adaptation(post_id, adaptation)

        return adaptation

    def _build_adaptation_prompt(self, video_analysis: Dict) -> str:
        """Build product-specific prompt using product.context_prompt"""
        return f"""
        You are creating a {self.product['name']} video adaptation.

        PRODUCT CONTEXT:
        {self.product['context_prompt']}

        TARGET AUDIENCE: {self.product['target_audience']}

        ORIGINAL VIDEO:
        Hook: {video_analysis['hook_transcript']}
        Transcript: {video_analysis['transcript']}
        Viral Factors: {video_analysis['viral_factors']}

        Generate a complete adaptation including:
        - Adapted hook
        - Full script
        - Storyboard with timestamps
        - Scores (1-10) for: hook_relevance, audience_match, transition_ease, viral_replicability

        Return JSON format...
        """
```

---

### 4. Cross-Platform Analysis

**Aggregate Analyzer:**

```python
class CrossPlatformAnalyzer:
    """Analyze patterns across multiple platforms"""

    def analyze_brand_across_platforms(
        self,
        brand_id: str,
        platforms: List[str]
    ) -> Dict:
        """Find common viral patterns across platforms"""

        # Get all posts for brand across platforms
        posts = self._get_brand_posts(brand_id, platforms)

        # Analyze common elements
        common_hooks = self._analyze_common_hooks(posts)
        common_structures = self._analyze_common_structures(posts)
        platform_differences = self._analyze_platform_differences(posts)

        return {
            'common_viral_patterns': common_hooks,
            'structure_patterns': common_structures,
            'platform_specific_nuances': platform_differences,
            'recommendations': self._generate_recommendations(posts)
        }

    def _analyze_platform_differences(self, posts: List[Dict]) -> Dict:
        """Identify platform-specific patterns"""

        platform_patterns = {}

        for platform in ['instagram', 'tiktok', 'youtube_shorts']:
            platform_posts = [p for p in posts if p['platform_slug'] == platform]

            platform_patterns[platform] = {
                'avg_length_sec': self._calc_avg_length(platform_posts),
                'common_hooks': self._extract_hook_patterns(platform_posts),
                'common_music': self._extract_music_patterns(platform_posts),
                'optimal_posting_times': self._analyze_timing(platform_posts),
            }

        return platform_patterns
```

---

## Implementation Phases

**NOTE:** Phase order revised 2025-10-03 after completing Phase 3. Original plan assumed URL importers would fetch metadata. We learned URL importers should only save URLs, and Apify populates metadata. Therefore, completing the Instagram workflow end-to-end before adding platforms makes more sense.

---

### Phase 1: Database Migration ✅ COMPLETE (2025-10-03)
**Goal:** Update schema without breaking existing data

1. Create new tables: `brands`, `products`, `platforms`, `projects`, `project_accounts`, `project_posts`, `product_adaptations`
2. Modify existing tables: `accounts`, `posts`, `video_analysis`
3. Migrate existing data:
   - Create "Yakety Pack" brand
   - Create "Core Deck" product with existing context
   - Create "Instagram" platform
   - Migrate existing accounts to have `platform_id`
   - Set `import_source = 'scrape'` for all existing posts
4. Create migration script that preserves all existing data
5. Test migration on staging environment

**Deliverables:**
- ✅ `sql/01_migration_multi_brand.sql`
- ✅ `scripts/migrate_existing_data.py`
- ✅ 100% data migration success (1000 posts, 77 accounts, 104 analyses)

---

### Phase 2: Core Refactoring + URL Import Foundation ✅ COMPLETE (2025-10-03)
**Goal:** Refactor code to use new schema AND add URL import foundation

1. Create new module structure (`core/`, `scrapers/`, `importers/`)
2. Build abstract `BaseScraper` class
3. Build abstract `BaseURLImporter` class
4. Create Pydantic models for all tables
5. Implement Instagram URL importer (URL validation only, no metadata scraping)
6. Update database layer with new models

**Deliverables:**
- ✅ New module structure (`viraltracker/core/`, `scrapers/`, `importers/`)
- ✅ `BaseScraper` abstract class
- ✅ `BaseURLImporter` abstract class
- ✅ `InstagramURLImporter` (URL validation + post ID extraction)
- ✅ Pydantic models for all tables
- ✅ Configuration and database management

**Key Learning:** URL importers should NOT fetch metadata (no yt-dlp). They only validate URLs and extract post IDs. Metadata is populated by Apify scraping.

---

### Phase 3: CLI Implementation - URL Import ✅ COMPLETE (2025-10-03)
**Goal:** Build Click-based CLI with URL import commands

1. ✅ Create CLI framework with Click
2. ✅ Implement `vt import url` command (single URL import)
3. ✅ Implement `vt import urls` command (batch import from file)
4. ✅ URL validation and duplicate detection
5. ✅ Project linking with notes
6. ✅ Own vs competitor content flagging

**Deliverables:**
- ✅ `viraltracker/cli/` module structure
- ✅ `vt` executable CLI script
- ✅ URL import commands working
- ✅ Complete documentation (PHASE_3_SUMMARY.md)

**Architecture Decision:** Simplified URL importers to only save URLs. Metadata (views, likes, comments) deferred to Apify scraping. yt-dlp reserved for future video download/analysis phase.

---

### Phase 4: Complete Instagram Workflow (NEW - REVISED)
**Goal:** Get full end-to-end workflow working for Instagram before adding platforms

**Why this order:** URL import creates posts without metadata. Need Apify integration working to populate metadata. Need project management to create/manage projects. Complete one platform fully before expanding horizontally.

**Sub-Phase 4a: Project/Brand/Product Management CLI**
1. Implement `vt project list/create/show/add-accounts` commands
2. Implement `vt brand list/create/show` commands
3. Implement `vt product list/create/show` commands
4. Allow creating projects, brands, products via CLI (not just Supabase)

**Sub-Phase 4b: Apify Scraper Integration**
1. Update legacy Instagram scraper (`ryan-viral-pattern-detector/ryan_vpd.py`) to use new schema
2. Make scraper project-aware (scrape accounts linked to a project)
3. Populate metadata for imported URLs (find posts by URL, fill in views/likes/comments)
4. Test scraping workflow end-to-end

**Sub-Phase 4c: Video Download & Analysis Pipeline** (Optional - can defer to Phase 6)
1. Implement video download using yt-dlp
2. Update video analysis to use new schema
3. Test analysis workflow end-to-end

**Deliverables:**
- Full CLI for project/brand/product management
- Updated Apify scraper using new multi-brand schema
- Complete Instagram workflow: Import URL → Scrape metadata → Analyze video
- Documentation

**Success Criteria:**
User can:
1. Create a project via CLI
2. Import competitor URLs via CLI
3. Run Apify scraper to populate metadata
4. Analyze videos with Gemini
5. Generate product adaptations

---

### Phase 5: TikTok Integration (MOVED FROM PHASE 4)
**Goal:** Add TikTok scraping, URL import, and analysis

1. Research TikTok scraping options (Apify actor, APIs, etc.)
2. Implement `TikTokURLImporter` class (URL validation + post ID extraction)
3. Implement `TikTokScraper` class (Apify integration)
4. Add TikTok-specific metric extraction
5. Test with real TikTok accounts and URLs
6. Update CLI to support TikTok platform flag

**Deliverables:**
- Working TikTok URL importer
- Working TikTok scraper
- TikTok platform in database
- Documentation

**Note:** User will provide Apify actor for TikTok scraping when we reach this phase

---

### Phase 6: YouTube Shorts Integration (MOVED FROM PHASE 5)
**Goal:** Add YouTube Shorts scraping and URL import

1. Research YouTube scraping options (Apify actor, YouTube Data API, etc.)
2. Implement `YouTubeURLImporter` class (URL validation + post ID extraction)
3. Implement `YouTubeScraper` class
4. Add Shorts-specific metric extraction
5. Handle YouTube-specific nuances (thumbnails, chapters)
6. Test with real accounts and URLs
7. Update CLI to support YouTube platform flag

**Deliverables:**
- Working YouTube Shorts URL importer
- Working YouTube Shorts scraper
- YouTube platform in database
- Documentation

**Note:** User will provide Apify actor for YouTube scraping when we reach this phase

---

### Phase 7: Generic Product Adapter (MOVED FROM PHASE 6)
**Goal:** Make video adaptation work for any product

1. Remove Yakety Pack hardcoding from video analysis
2. Implement generic `ProductAdapter` class
3. Update AI prompts to use `product.context_prompt`
4. Test with multiple products
5. Create product configuration templates

**Deliverables:**
- Generic adaptation system
- Product configuration guide
- Example product setups

---

### Phase 8: Cross-Platform Analysis (MOVED FROM PHASE 7)
**Goal:** Aggregate insights across platforms

1. Implement `CrossPlatformAnalyzer`
2. Build platform comparison reports
3. Create aggregate insights dashboard (CLI output)
4. Test with real multi-platform data

**Deliverables:**
- Cross-platform analyzer
- Aggregate reports
- Documentation

---

### Phase 9: Testing & Documentation (MOVED FROM PHASE 8)
**Goal:** Polish and document everything

1. Comprehensive testing of all platforms
2. Create migration guide from old system
3. Update all README files
4. Create video tutorials for CLI
5. Write troubleshooting guide

**Deliverables:**
- Test suite
- Complete documentation
- Migration guide
- User tutorials

---

## Breaking Changes & Migration

### For Existing Users

**Old Way:**
```bash
python ryan_vpd.py scrape --usernames usernames.csv
python video_processor.py process --unprocessed-outliers
python yakety_pack_evaluator.py
```

**New Way:**
```bash
# One-time setup
./viraltracker project create --name "Yakety Pack IG" --brand yakety-pack --product core-deck
./viraltracker project add-accounts yakety-pack-ig --platform instagram --file usernames.csv

# Regular workflow
./viraltracker scrape --project yakety-pack-ig
./viraltracker analyze --project yakety-pack-ig
./viraltracker process-videos --project yakety-pack-ig
./viraltracker analyze-videos --project yakety-pack-ig --product core-deck
```

### Migration Script

Provide automatic migration:
```bash
./scripts/migrate_to_multi_brand.py
```

This will:
1. Create default brand "Yakety Pack"
2. Create default product "Core Deck"
3. Create default project "Yakety Pack Instagram"
4. Link all existing accounts to Instagram platform
5. Link all existing accounts to default project

---

## Configuration Files

### Product Configuration Template

`products/yakety_pack_core_deck.json`:
```json
{
  "name": "Yakety Pack - Core Deck",
  "slug": "core-deck",
  "brand_slug": "yakety-pack",
  "description": "Conversation cards for gaming families",
  "target_audience": "Parents with gaming kids aged 6-15",
  "price_range": "$39",
  "key_problems_solved": [
    "Screen time arguments and battles",
    "Communication gap between parents and gaming kids",
    "Parents feeling disconnected from their child's gaming interests"
  ],
  "key_benefits": [
    "Better parent-child communication",
    "Understanding your child's gaming world",
    "Reducing screen time conflicts",
    "Building emotional intelligence through gaming discussions"
  ],
  "features": [
    "86 conversation cards (66 prompts + 20 design-your-own)",
    "Color-coded for different emotional depths",
    "Gaming-specific questions (Minecraft, Roblox, Fortnite, etc.)",
    "Transforms screen time into quality family time"
  ],
  "context_prompt": "PRODUCT: Yakety Pack - Conversation Cards for Gaming Families\n\nTARGET AUDIENCE: Parents with children aged 6-15 who play video games\n\n..."
}
```

### Platform Configuration

`platforms/instagram.json`:
```json
{
  "name": "Instagram Reels",
  "slug": "instagram",
  "scraper_type": "apify",
  "scraper_config": {
    "actor_id": "apify/instagram-scraper",
    "default_post_type": "reels",
    "rate_limit_delay": 2
  },
  "max_video_length_sec": 90,
  "typical_video_length_sec": 30,
  "aspect_ratio": "9:16"
}
```

---

## Success Criteria

### Technical
- ✅ All existing Yakety Pack workflows still work
- ✅ Can manage multiple brands simultaneously
- ✅ Can scrape Instagram, TikTok, and YouTube Shorts
- ✅ Can generate adaptations for any product
- ✅ Cross-platform analysis produces meaningful insights
- ✅ Database properly isolates brand/platform data

### User Experience
- ✅ CLI is intuitive and well-documented
- ✅ Migration from old system is smooth
- ✅ Can switch between brands/products easily
- ✅ Error messages are clear and actionable

### Performance
- ✅ Scraping performance matches or exceeds current system
- ✅ Database queries are optimized with proper indexes
- ✅ Cross-platform analysis completes in reasonable time

---

## Risk Mitigation

### Risk 1: Breaking Existing Workflows
**Mitigation:**
- Maintain backward compatibility wrapper
- Provide automated migration script
- Comprehensive testing before rollout

### Risk 2: Platform API Changes
**Mitigation:**
- Abstract scraper interface
- Platform-specific error handling
- Regular monitoring of platform APIs

### Risk 3: Database Migration Failures
**Mitigation:**
- Test migration on staging first
- Create rollback scripts
- Backup data before migration

### Risk 4: Complexity Creep
**Mitigation:**
- Start with minimum viable features
- Iterate based on actual usage
- Keep CLI simple with good defaults

---

## Open Questions

1. **TikTok Scraping:** What's the best approach? Apify actor? Official API? Third-party library?
   - **Answer:** User will provide Apify actor when we reach Phase 4
2. **YouTube API Costs:** YouTube Data API has quotas. Do we need to implement caching?
   - **Answer:** User will provide Apify actor when we reach Phase 5 (may avoid API costs)
3. **Video Storage:** Do we need different storage buckets per platform/brand?
   - **Answer:** TBD - can organize by folders initially
4. **Cross-Platform Video Downloads:** Can yt-dlp handle all three platforms?
   - **Answer:** YES - yt-dlp supports Instagram, TikTok, YouTube, and hundreds of others
5. **AI Costs:** Will analyzing videos across 3 platforms increase costs significantly?
   - **Answer:** Yes, but URL import allows selective analysis of most important videos
6. **URL Import Metadata:** How much metadata can we get from yt-dlp vs. scraping?
   - **Answer:** yt-dlp provides: views, likes, comments, description, duration, uploader - sufficient for analysis

---

## Next Steps

1. Review this plan with stakeholders
2. Answer open questions
3. Set up staging environment for testing
4. Begin Phase 1: Database Migration
5. Create detailed task breakdown for each phase

---

**Total Estimated Time:** 7-8 weeks for full implementation
**Minimum Viable Product:** Phases 1-3 (3 weeks) - Multi-brand support with Instagram scraping AND URL import (all platforms)

**Early Win (Phase 2-3):** URL import via yt-dlp works for Instagram, TikTok, AND YouTube immediately - users can analyze specific videos from any platform before full scraping integration is complete!
