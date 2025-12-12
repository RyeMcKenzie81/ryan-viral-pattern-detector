# Trash Panda Content Pipeline

## Overview

End-to-end workflow for creating Trash Panda Economics YouTube content and comics, from topic discovery through editor handoff. Uses **pydantic-graph** for human-in-the-loop workflow orchestration.

**Branch:** `feature/trash-panda-content-pipeline`
**Status:** Planning

---

## Complete Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CONTENT PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   1. TOPIC   │    │  2. TOPIC    │    │  3. HUMAN    │                   │
│  │  DISCOVERY   │───▶│  EVALUATION  │───▶│  SELECTION   │                   │
│  │   (OpenAI)   │    │   (OpenAI)   │    │   (Manual)   │                   │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                   │
│                                                  │                           │
│                                                  ▼                           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │  6. HUMAN    │    │  5. SCRIPT   │    │  4. SCRIPT   │                   │
│  │  APPROVAL    │◀───│   REVIEW     │◀───│  GENERATION  │                   │
│  │   (Manual)   │    │  (Opus 4.5)  │    │  (Opus 4.5)  │                   │
│  └──────┬───────┘    └──────────────┘    └──────────────┘                   │
│         │                    ▲                                               │
│         │              (Loop until approved)                                 │
│         ▼                                                                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   7. ELS     │───▶│  8. AUDIO    │───▶│  9. ASSET    │                   │
│  │  CONVERSION  │    │  PRODUCTION  │    │  EXTRACTION  │                   │
│  │  (Service)   │    │  (Existing)  │    │   (Gemini)   │                   │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                   │
│                                                  │                           │
│                                                  ▼                           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │  10. HUMAN   │◀───│  11. ASSET   │◀───│  10. ASSET   │                   │
│  │   REVIEW     │    │  GENERATION  │    │   MATCHING   │                   │
│  │   (Manual)   │    │ (Nano Banano)│    │  (Service)   │                   │
│  └──────┬───────┘    └──────────────┘    └──────────────┘                   │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      12. EDITOR HANDOFF                               │   │
│  │   Full Script + Storyboard + ELS + Audio + All Assets                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ════════════════════════════════════════════════════════════════════════   │
│  COMIC PATH (starts after Script Approval - Step 6)                         │
│  ════════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         COMIC PATH                                    │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │   │
│  │  │  13. COMIC   │───▶│  14. COMIC   │───▶│  15. HUMAN   │            │   │
│  │  │ CONDENSATION │    │  EVALUATION  │    │   REVIEW     │            │   │
│  │  │  (Opus 4.5)  │    │   (Gemini)   │    │   (Manual)   │            │   │
│  │  └──────────────┘    └──────────────┘    └──────┬───────┘            │   │
│  │                                                  │                    │   │
│  │                                                  ▼                    │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │   │
│  │  │  18. COMIC   │◀───│  17. COMIC   │◀───│  16. COMIC   │            │   │
│  │  │    VIDEO     │    │     JSON     │    │  GENERATION  │            │   │
│  │  │  (Existing)  │    │  CONVERSION  │    │ (Nano Banano)│            │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Workflow Steps (Detailed)

| Step | Name | Model/Tool | Human Checkpoint | Quick Approve? | Description |
|------|------|------------|------------------|----------------|-------------|
| 1 | Topic Discovery | ChatGPT 5.1 | No | - | Research trending financial topics (batch: 10-20) |
| 2 | Topic Evaluation | ChatGPT 5.1 | No | - | Score & rank topics with reasoning |
| 3 | **Topic Selection** | - | **YES** | If score > 90 | Human picks topic(s) from evaluated list |
| 4 | Script Generation | Claude Opus 4.5 | No | - | Write full script + storyboard |
| 5 | Script Review | Claude Opus 4.5 | No | - | Check against bible checklist |
| 6 | **Script Approval** | - | **YES** | If 100% checklist | Human approves or requests revisions |
| --- | **VIDEO PATH** | --- | --- | --- | --- |
| 7 | ELS Conversion | Service | No | - | Convert script to ELS format |
| 8 | Audio Production | Existing | **YES** | - | Generate audio (existing workflow) |
| 9 | Asset Extraction | Gemini | No | - | Parse script for required assets |
| 10 | Asset Matching | Service | No | - | Match against existing asset library |
| 11 | Asset Generation | Gemini Image | No | - | Generate missing assets |
| 12 | **Asset Review** | - | **YES** | - | Human reviews generated assets |
| 13 | SEO/Metadata Generation | Claude Opus 4.5 | No | - | Generate 3 ranked titles, descriptions, tags |
| 14 | **Metadata Selection** | - | **YES** | If rank 1 score > 90 | Human picks title/description |
| 14b | Thumbnail Generation | Gemini Image | No | - | Generate thumbnail options based on Derral Eves best practices |
| 14c | **Thumbnail Selection** | - | **YES** | - | Human picks/approves thumbnail |
| 15 | Editor Handoff | Service | No | - | Package all materials for video editor |
| --- | **COMIC PATH** | --- | --- | --- | --- |
| 16 | Comic Condensation | Claude Opus 4.5 | **CONFIG** | - | Human sets panel count, platform, then AI condenses |
| 17 | Comic Script Evaluation | Gemini | No | - | Check clarity, humor, flow |
| 18 | **Comic Script Approval** | - | **YES** | If all scores > 85 | Human approves comic script |
| 19 | Comic Image Generation | Gemini Image | No | - | Generate 4K comic grid image |
| 20 | Comic Image Evaluation | Gemini | No | - | Verify image against checklist (must pass 90%+) |
| 21 | **Comic Image Review** | - | **YES** | If eval > 90% | Human approves generated comic image |
| 22 | Comic Audio Script | Claude Opus 4.5 | No | - | Generate ELS script for comic dialogue |
| 23 | Comic Audio Review | Gemini | No | - | Verify audio script matches comic panels |
| 24 | Comic JSON Conversion | Service | No | - | Convert to comic video JSON format |
| 25 | Comic Video | Existing | **YES** | - | Generate video (existing workflow with audio/panel review) |
| 26 | Comic SEO/Metadata | Claude Opus 4.5 | No | - | Generate 3 ranked titles for comic video |
| 27 | **Comic Metadata Selection** | - | **YES** | If rank 1 > 90 | Human picks comic video title |
| 28 | Comic Thumbnail Generation | Gemini Image | No | - | Generate thumbnail for comic video (16:9, 9:16) |
| 29 | **Comic Thumbnail Selection** | - | **YES** | - | Human picks comic thumbnail |

**Quick Approve**: When enabled, if AI evaluation exceeds threshold, checkpoint auto-approves with user notification.

---

## Architecture

### Pydantic-Graph for Human-in-the-Loop

Since this workflow has **8 human checkpoints** (+ 3 with Quick Approve option), we'll use pydantic-graph to:
- Persist workflow state between human interactions
- Allow resumption after human approval
- Track which step the project is at
- Enable branching (revisions loop back)

```python
from pydantic_graph import Graph, Node, Edge

class ContentPipelineGraph(Graph):
    """
    Human-in-the-loop content pipeline with Quick Approve support.

    Human Checkpoints:
    - topic_selection: Human picks topic (Quick Approve if score > 90)
    - script_approval: Human approves script (Quick Approve if 100% checklist)
    - audio_production: Human reviews audio takes
    - asset_review: Human reviews generated assets
    - metadata_selection: Human picks SEO title/description (Quick Approve if rank 1 > 90)
    - comic_script_approval: Human approves comic script (Quick Approve if all > 85)
    - comic_image_review: Human approves comic image (Quick Approve if eval > 90%)
    - comic_video: Human reviews audio & panel adjustments

    Error Recovery:
    - All nodes support retry with configurable attempts
    - Failed nodes enter "error" state for manual intervention
    - Can resume from last successful step
    """

    nodes = [
        # Shared path
        Node("topic_discovery", TopicDiscoveryNode),      # Batch: 10-20 topics
        Node("topic_evaluation", TopicEvaluationNode),
        Node("topic_selection", HumanCheckpointNode),     # HUMAN (Quick Approve)
        Node("script_generation", ScriptGenerationNode),
        Node("script_review", ScriptReviewNode),
        Node("script_approval", HumanCheckpointNode),     # HUMAN (Quick Approve)

        # Video path
        Node("els_conversion", ELSConversionNode),
        Node("audio_production", AudioProductionNode),    # HUMAN
        Node("asset_extraction", AssetExtractionNode),
        Node("asset_matching", AssetMatchingNode),
        Node("asset_generation", AssetGenerationNode),
        Node("asset_review", HumanCheckpointNode),        # HUMAN
        Node("seo_metadata_generation", SEOMetadataNode),
        Node("metadata_selection", HumanCheckpointNode),  # HUMAN (Quick Approve)
        Node("editor_handoff", EditorHandoffNode),

        # Comic path
        Node("comic_condensation", ComicCondensationNode),  # CONFIG: panel count, platform
        Node("comic_script_evaluation", ComicScriptEvalNode),
        Node("comic_script_approval", HumanCheckpointNode), # HUMAN (Quick Approve)
        Node("comic_image_generation", ComicImageGenNode),
        Node("comic_image_evaluation", ComicImageEvalNode), # Must pass 90%+
        Node("comic_image_review", HumanCheckpointNode),    # HUMAN (Quick Approve)
        Node("comic_audio_script", ComicAudioScriptNode),
        Node("comic_audio_review", ComicAudioReviewNode),   # AI verify matches comic
        Node("comic_json_conversion", ComicJSONNode),
        Node("comic_video", ComicVideoNode),                # HUMAN (existing tool)

        # Error state
        Node("error", ErrorNode),
    ]

    edges = [
        # Topic discovery (batch mode)
        Edge("topic_discovery", "topic_evaluation"),
        Edge("topic_evaluation", "topic_selection"),
        Edge("topic_selection", "topic_discovery", condition="request_more"),
        Edge("topic_selection", "script_generation", condition="selected"),

        # Script generation with revision loop
        Edge("script_generation", "script_review"),
        Edge("script_review", "script_approval"),
        Edge("script_approval", "script_generation", condition="needs_revision"),
        Edge("script_approval", "els_conversion", condition="approved"),       # → Video
        Edge("script_approval", "comic_condensation", condition="approved"),   # → Comic

        # Video path
        Edge("els_conversion", "audio_production"),
        Edge("audio_production", "asset_extraction"),
        Edge("asset_extraction", "asset_matching"),
        Edge("asset_matching", "asset_generation"),
        Edge("asset_generation", "asset_review"),
        Edge("asset_review", "asset_generation", condition="regenerate"),
        Edge("asset_review", "seo_metadata_generation", condition="approved"),
        Edge("seo_metadata_generation", "metadata_selection"),
        Edge("metadata_selection", "editor_handoff"),

        # Comic path
        Edge("comic_condensation", "comic_script_evaluation"),
        Edge("comic_script_evaluation", "comic_script_approval"),
        Edge("comic_script_approval", "comic_condensation", condition="needs_revision"),
        Edge("comic_script_approval", "comic_image_generation", condition="approved"),
        Edge("comic_image_generation", "comic_image_evaluation"),
        Edge("comic_image_evaluation", "comic_image_generation", condition="below_90"),
        Edge("comic_image_evaluation", "comic_image_review", condition="above_90"),
        Edge("comic_image_review", "comic_image_generation", condition="regenerate"),
        Edge("comic_image_review", "comic_audio_script", condition="approved"),
        Edge("comic_audio_script", "comic_audio_review"),
        Edge("comic_audio_review", "comic_audio_script", condition="mismatch"),
        Edge("comic_audio_review", "comic_json_conversion", condition="matches"),
        Edge("comic_json_conversion", "comic_video"),

        # Error recovery (any node can transition to error)
        Edge("*", "error", condition="max_retries_exceeded"),
    ]
```

### Error Recovery States

```python
class NodeState(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAITING_HUMAN = "waiting_human"
    ERROR = "error"
    RETRYING = "retrying"

class ErrorRecoveryConfig:
    max_retries: int = 3
    retry_delay_seconds: int = 5
    notify_on_error: bool = True
    allow_manual_override: bool = True
```

### Knowledge Base Collections

**1. Trash Panda Bible Collection** (`trash-panda-bible`)
- Trash Panda Bible (Google Doc export)
- YouTube best practices (6 files, ~3400 lines)
- Used for: Script generation, script review

**2. Comic Production Collection** (`comic-production`)
20 specialized documents for comic creation:

| Category | Documents | Used In |
|----------|-----------|---------|
| **Core Philosophy** | `comic_blueprint_overview`, `comic_planning_4_panel`, `comic_canonical_definitions` | Step 13 (Condensation) |
| **Craft Pillars** | `comic_characters_principles`, `comic_dialogue_rules`, `comic_virality_principles`, `comic_composition_principles` | Steps 13, 14 |
| **Patterns** | `comic_patterns_emotions`, `comic_patterns_gags`, `comic_genres_and_audiences` | Step 13 (Planning) |
| **Platforms** | `comic_platforms_instagram`, `comic_platforms_twitter`, `comic_platforms_tiktok_vertical` | Step 13 (Format) |
| **Evaluation** | `comic_evaluation_checklist`, `comic_troubleshooting_common_problems`, `comic_repair_patterns` | Steps 14, 15 |
| **Examples** | `comic_examples_plans`, `comic_examples_before_after`, `comic_schemas_structures` | Steps 13, 15 |
| **Meta** | `comic_kb_usage_guide` | All comic steps |

Services query KB for relevant context based on step

### Multi-Brand Support
- All tables include `brand_id` FK
- Bible/style per brand
- Character library per brand

---

## Database Schema

### 1. `content_projects`
Main project tracking with workflow state.

```sql
CREATE TABLE content_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),

    -- Topic
    topic_title TEXT NOT NULL,
    topic_description TEXT,
    topic_score INT,
    topic_reasoning TEXT,
    hook_options JSONB,

    -- Workflow state (pydantic-graph)
    workflow_state TEXT DEFAULT 'topic_discovery',
    workflow_data JSONB,  -- Serialized graph state

    -- Current versions
    current_script_version_id UUID,
    current_els_version_id UUID,
    current_comic_version_id UUID,

    -- Links to other systems
    audio_session_id UUID REFERENCES audio_production_sessions(id),
    comic_video_project_id UUID REFERENCES comic_video_projects(id),

    -- Editor handoff
    public_slug TEXT UNIQUE,
    handoff_created_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. `topic_suggestions`
Discovered and evaluated topics.

```sql
CREATE TABLE topic_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES content_projects(id) ON DELETE CASCADE,

    title TEXT NOT NULL,
    description TEXT,
    score INT,  -- 0-100
    reasoning TEXT,
    hook_options JSONB,  -- Array of hook suggestions

    -- Selection
    is_selected BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3. `script_versions`
Version history for full scripts.

```sql
CREATE TABLE script_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    version_number INT NOT NULL,

    -- Content
    script_content TEXT NOT NULL,
    storyboard_json JSONB,

    -- Review
    checklist_results JSONB,
    reviewer_notes TEXT,
    improvement_suggestions JSONB,

    -- Approval
    status TEXT DEFAULT 'draft',
    human_notes TEXT,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 4. `els_versions`
ELS format scripts.

```sql
CREATE TABLE els_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    script_version_id UUID REFERENCES script_versions(id),
    version_number INT NOT NULL,

    els_content TEXT NOT NULL,
    audio_session_id UUID REFERENCES audio_production_sessions(id),

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 5. `comic_versions`
Condensed comic scripts.

```sql
CREATE TABLE comic_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    script_version_id UUID REFERENCES script_versions(id),
    version_number INT NOT NULL,

    -- Content
    comic_script TEXT NOT NULL,
    panel_count INT,

    -- Evaluation
    evaluation_results JSONB,  -- clarity, humor, flow scores
    evaluation_notes TEXT,

    -- Approval
    status TEXT DEFAULT 'draft',
    human_notes TEXT,
    approved_at TIMESTAMPTZ,

    -- Generated comic
    comic_json JSONB,  -- Final comic JSON for video tool
    comic_image_url TEXT,  -- Generated comic image

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 6. `comic_assets`
Visual asset library.

```sql
CREATE TABLE comic_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),

    asset_type TEXT NOT NULL,  -- character, prop, background, effect
    name TEXT NOT NULL,
    description TEXT,
    tags TEXT[],

    -- Generation
    prompt_template TEXT,
    style_suffix TEXT DEFAULT 'flat vector cartoon art, minimal design, thick black outlines, simple geometric shapes, style of Cyanide and Happiness, 2D, high contrast',

    -- Storage
    image_url TEXT,
    thumbnail_url TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, name)
);
```

### 7. `project_asset_requirements`
Assets needed per project.

```sql
CREATE TABLE project_asset_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    -- Existing asset match
    asset_id UUID REFERENCES comic_assets(id),

    -- For new assets
    asset_name TEXT,
    asset_description TEXT,
    suggested_prompt TEXT,

    -- Status
    status TEXT DEFAULT 'needed',  -- needed, matched, generating, generated, approved

    -- Generated result
    generated_image_url TEXT,
    human_approved BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 8. `character_voices`
Character voice mappings for ElevenLabs.

```sql
CREATE TABLE character_voices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),

    -- Character info
    character_name TEXT NOT NULL,  -- "Every-Coon", "The Fed", "Whale", "Boomer"
    character_description TEXT,

    -- ElevenLabs voice
    elevenlabs_voice_id TEXT NOT NULL,
    elevenlabs_voice_name TEXT,  -- Human-readable name

    -- Voice settings
    stability DECIMAL(3,2) DEFAULT 0.5,
    similarity_boost DECIMAL(3,2) DEFAULT 0.75,
    style DECIMAL(3,2) DEFAULT 0.0,

    -- Usage
    is_narrator BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, character_name)
);
```

### 9. `project_metadata`
SEO metadata for YouTube publishing.

```sql
CREATE TABLE project_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,

    -- Title options (ranked)
    title_options JSONB,  -- [{rank: 1, title: "...", reasoning: "..."}, ...]
    selected_title TEXT,

    -- Description
    description TEXT,
    description_with_timestamps TEXT,

    -- Tags
    tags TEXT[],

    -- Thumbnail
    thumbnail_concepts JSONB,  -- AI-generated concepts
    thumbnail_url TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## New Services

### 1. `TopicDiscoveryService`
```python
class TopicDiscoveryService:
    """Discover and evaluate trending topics in batch."""

    async def discover_topics(
        self,
        brand_id: UUID,
        bible_context: str,
        num_topics: int = 10,  # Batch: 10-20 topics
        focus_areas: Optional[List[str]] = None
    ) -> List[TopicSuggestion]:
        """
        Use ChatGPT 5.1 extended thinking to find trending topics.
        Returns batch of topics for user to select from.
        """
        pass

    async def evaluate_topics(
        self,
        topics: List[TopicSuggestion],
        bible_context: str,
        past_performance: Optional[Dict] = None  # Historical video stats
    ) -> List[TopicSuggestion]:
        """Score and rank topics with reasoning. Mark Quick Approve eligible if score > 90."""
        pass

    def check_quick_approve(
        self,
        topic: TopicSuggestion,
        threshold: int = 90
    ) -> bool:
        """Check if topic qualifies for Quick Approve."""
        return topic.score >= threshold
```

### 2. `ScriptGenerationService`
```python
class ScriptGenerationService:
    """Generate and review scripts with Claude Opus 4.5."""

    async def generate_script(
        self,
        project_id: UUID,
        topic: TopicSuggestion,
        bible_context: str,
        youtube_context: str
    ) -> ScriptVersion:
        """Generate full script + storyboard."""
        pass

    async def review_script(
        self,
        script_version_id: UUID,
        bible_checklist: str
    ) -> ReviewResult:
        """Review against bible checklist."""
        pass

    async def revise_script(
        self,
        script_version_id: UUID,
        review_result: ReviewResult,
        human_notes: Optional[str] = None
    ) -> ScriptVersion:
        """Create revised version."""
        pass

    def convert_to_els(self, script_version_id: UUID) -> ELSVersion:
        """Convert to ELS format."""
        pass
```

### 3. `ComicService`
```python
class ComicService:
    """Handle comic condensation, evaluation, image generation, and audio."""

    async def condense_to_comic(
        self,
        script_version_id: UUID,
        config: ComicConfig  # panel_count, target_platform, grid_layout
    ) -> ComicVersion:
        """
        Condense full script to comic format.
        Uses comic-production KB for planning (blueprint, patterns, dialogue rules).
        """
        pass

    async def evaluate_comic_script(
        self,
        comic_version_id: UUID
    ) -> ComicScriptEvaluation:
        """
        Evaluate comic SCRIPT for clarity, humor, flow.
        Uses comic_evaluation_checklist from KB.
        Returns scores and Quick Approve eligibility (all > 85).
        """
        pass

    async def generate_comic_image(
        self,
        comic_version_id: UUID,
        character_assets_url: str  # Core-assets.png
    ) -> str:
        """
        Generate 4K comic grid image using Gemini Image.
        Returns image URL.
        """
        pass

    async def evaluate_comic_image(
        self,
        comic_version_id: UUID,
        image_url: str
    ) -> ComicImageEvaluation:
        """
        Evaluate generated IMAGE against checklist.
        Must pass 90%+ to proceed to human review.
        If < 90%, auto-regenerate with adjusted prompts.
        """
        pass

    async def generate_comic_audio_script(
        self,
        comic_version_id: UUID,
        character_voices: List[CharacterVoice]
    ) -> ELSVersion:
        """
        Generate ELS script specifically for comic panel dialogue.
        Maps each panel's dialogue to character voice.
        """
        pass

    async def verify_audio_script_matches(
        self,
        comic_version_id: UUID,
        els_version_id: UUID
    ) -> AudioScriptVerification:
        """
        AI verifies audio script matches comic panels:
        - All panels have corresponding audio
        - Dialogue matches panel content
        - Character assignments are correct
        """
        pass

    async def generate_comic_json(
        self,
        comic_version_id: UUID,
        els_version_id: UUID
    ) -> Dict:
        """Generate JSON for comic video tool."""
        pass
```

### 4. `SEOMetadataService`
```python
class SEOMetadataService:
    """Generate SEO-optimized metadata for YouTube."""

    async def generate_metadata(
        self,
        project_id: UUID,
        script_content: str,
        youtube_best_practices: str  # From KB
    ) -> ProjectMetadata:
        """
        Generate 3 ranked title options with:
        - Title text
        - SEO score (0-100)
        - Reasoning
        - Corresponding description
        - Suggested tags

        Uses Derral Eves YouTube best practices from KB.
        """
        pass

    def check_quick_approve(
        self,
        metadata: ProjectMetadata,
        threshold: int = 90
    ) -> bool:
        """Check if rank 1 title qualifies for Quick Approve."""
        return metadata.title_options[0].score >= threshold
```

### 5. `ThumbnailService`
```python
class ThumbnailService:
    """Generate YouTube thumbnails using Derral Eves best practices."""

    async def generate_thumbnail_prompt(
        self,
        project_id: UUID,
        selected_title: str,
        script_summary: str,
        youtube_best_practices: str  # From KB
    ) -> ThumbnailPrompt:
        """
        Build JSON prompt for thumbnail generation based on:
        - Derral Eves thumbnail principles (contrast, faces, text rules)
        - Selected video title
        - Key visual from script

        Returns simple JSON prompt structure.
        """
        pass

    async def generate_thumbnails(
        self,
        prompt: ThumbnailPrompt,
        character_assets_url: str,
        sizes: List[ThumbnailSize] = None
    ) -> List[str]:
        """
        Generate 3 thumbnail options using Gemini Image.

        Default sizes:
        - 16:9 (1280×720) - YouTube landscape, Twitter
        - 9:16 (720×1280) - YouTube Shorts, Instagram Reels

        Returns list of image URLs per size.
        """
        pass
```

### 6. `AssetManagementService`
```python
class AssetManagementService:
    """
    Manage visual assets.

    NOTE: Assets are shared between Video and Comic paths.
    - Assets generated for video can be reused in comics
    - All assets stored in Supabase, searchable by brand
    - When generating comics, use style consistency prompts rather than
      passing all assets (to manage context window)
    """

    async def extract_requirements(
        self,
        script_version_id: UUID
    ) -> List[AssetRequirement]:
        """Parse script for required assets."""
        pass

    def match_existing_assets(
        self,
        requirements: List[AssetRequirement],
        brand_id: UUID
    ) -> Tuple[List[AssetRequirement], List[AssetRequirement]]:
        """Split into matched and needed."""
        pass

    async def generate_asset(
        self,
        requirement: AssetRequirement,
        brand_id: UUID
    ) -> str:
        """Generate asset image with Nano Banano 3."""
        pass

    def generate_prompt(
        self,
        asset_name: str,
        description: str,
        brand_style: str
    ) -> str:
        """Build generation prompt."""
        pass
```

### 7. `EditorHandoffService`
```python
class EditorHandoffService:
    """Package materials for editor."""

    def create_handoff(self, project_id: UUID) -> EditorHandoff:
        """
        Package:
        - Script/storyboard document
        - ELS file
        - Audio files
        - All assets (existing + generated)
        - Comic JSON (if applicable)
        """
        pass

    def get_handoff_by_slug(self, slug: str) -> EditorHandoff:
        """Get for public page."""
        pass
```

### 8. `ContentPipelineService`
```python
class ContentPipelineService:
    """Orchestrate the full workflow using pydantic-graph."""

    def create_project(self, brand_id: UUID) -> ContentProject:
        """Initialize new project with graph state."""
        pass

    async def advance_workflow(
        self,
        project_id: UUID,
        human_input: Optional[Dict] = None
    ) -> WorkflowState:
        """
        Advance to next step.
        If at human checkpoint, requires human_input.
        """
        pass

    def get_current_state(self, project_id: UUID) -> WorkflowState:
        """Get current workflow position and available actions."""
        pass
```

---

## UI Pages

### 1. `22_📝_Content_Pipeline.py`
Main workflow UI.

**Sections:**
1. **Project Dashboard** - All projects with workflow status
2. **Topic Discovery** - Run discovery, view evaluated topics, select
3. **Script Workshop** - View/edit script, see review results, approve
4. **Audio Production** - Link to existing audio page
5. **Asset Manager** - View requirements, review generated assets
6. **Editor Handoff** - Generate handoff package
7. **Comic Studio** - Condense, evaluate, generate comic

### 2. `23_📦_Editor_Handoff.py`
Public page (no auth).

**Features:**
- Script/storyboard viewer + PDF download
- ELS file download
- Audio player per beat
- Asset gallery with downloads
- Comic JSON download

---

## Implementation Phases

### Phase 1: Foundation ✅ COMPLETE
- [x] Database migration
- [x] ContentPipelineService skeleton
- [x] Pydantic-graph setup
- [x] Basic UI page with project list
- [x] **KB Ingestion: `trash-panda-bible` collection** (14 chunks)

### Phase 2: Topic Discovery (MVP 1) ✅ COMPLETE
- [x] TopicDiscoveryService
- [x] OpenAI extended thinking integration
- [x] Topic evaluation logic
- [x] Human selection checkpoint UI

### Phase 3: Script Generation (MVP 2) ✅ COMPLETE
- [x] ScriptGenerationService
- [x] Claude Opus 4.5 integration
- [x] Bible checklist review
- [x] Revision loop with interactive UX (checkboxes, revise selected/all)
- [x] Human approval checkpoint UI

### Phase 4: ELS & Audio Integration (MVP 3) ✅ COMPLETE
- [x] ELS conversion (`ScriptGenerationService.convert_to_els()`)
- [x] Save ELS to `els_versions` table
- [x] Add "Audio" tab to Content Pipeline UI
- [x] Auto-create audio session linked to project via `audio_session_id` FK
- [x] Embed audio generation workflow in Content Pipeline
- [x] Audio playback and take selection
- [x] Beat regeneration with take numbering
- [x] Mark Audio Complete button

### Phase 5: Asset Management (MVP 4) ✅ COMPLETE
- [x] AssetManagementService (Gemini-powered extraction)
- [x] Script parsing for assets (visual_notes → characters, props, backgrounds, effects)
- [x] Asset library UI (browse, filter, view)
- [x] Asset matching logic (match requirements against comic_assets)
- [x] File upload to Supabase Storage (single + batch)
- [x] JSON bulk import

### Phase 6: Asset Generation
- [ ] **Image Assets**: `gemini-3-pro-image-preview` for backgrounds, props
- [ ] **SFX Assets**: ElevenLabs Sound Effects API for missing audio
  - Parse script for SFX triggers (whale rumble, printer sounds, "WAGMI", etc.)
  - Check asset library for existing SFX
  - Generate missing SFX via ElevenLabs
  - Review and approve generated SFX
- [ ] Asset generation workflow
- [ ] Human review checkpoint UI
- [ ] Asset approval flow

### Phase 7: Editor Handoff
- [ ] EditorHandoffService
- [ ] Public handoff page
- [ ] Package generation
- [ ] Download endpoints

### Phase 8: Comic Path
- [ ] **KB Ingestion: `comic-production` collection**
  - [ ] ⚠️ **USER ACTION**: Provide 20 Comic KB documents:
    - Core Philosophy (3): `comic_blueprint_overview`, `comic_planning_4_panel`, `comic_canonical_definitions`
    - Craft Pillars (4): `comic_characters_principles`, `comic_dialogue_rules`, `comic_virality_principles`, `comic_composition_principles`
    - Patterns (3): `comic_patterns_emotions`, `comic_patterns_gags`, `comic_genres_and_audiences`
    - Platforms (3): `comic_platforms_instagram`, `comic_platforms_twitter`, `comic_platforms_tiktok_vertical`
    - Evaluation (3): `comic_evaluation_checklist`, `comic_troubleshooting_common_problems`, `comic_repair_patterns`
    - Examples (3): `comic_examples_plans`, `comic_examples_before_after`, `comic_schemas_structures`
    - Meta (1): `comic_kb_usage_guide`
  - [ ] Ingest documents into Knowledge Base
- [ ] ComicService
- [ ] Comic condensation (uses KB for planning)
- [ ] Comic evaluation (uses KB for quality assessment)
- [ ] Human approval checkpoint (uses KB for AI-assisted fixes)

### Phase 9: Comic Generation & JSON
- [ ] Comic panel generation
- [ ] Comic JSON conversion
- [ ] Integration with existing Comic Video tool

### Phase 10: End-to-End Testing
- [ ] Full workflow test
- [ ] Human checkpoint testing
- [ ] Error recovery testing

---

## Future Work (Post-MVP)

### Multi-Brand Bible Management
When adding other brands beyond Trash Panda Economics:
- Each brand uploads their bible via Brand Settings UI
- Bible tagged with `{brand-slug}-bible` in Knowledge Base
- `get_full_bible_content(brand_id)` retrieves complete document for script generation
- RAG search remains as fallback for Q&A queries

### Full Bible Injection for Script Generation
- Topic Discovery: Uses RAG search (10 chunks) for general context
- Script Generation: Should inject FULL bible content (~8K tokens) for quality
- Implementation: Add `TopicService.get_full_bible_content()` method that fetches complete document

---

## Human Checkpoints Summary

| # | Checkpoint | Step | Quick Approve? | Actions |
|---|------------|------|----------------|---------|
| 1 | **Topic Selection** | 3 | If score > 90 | Pick topic(s), request more options |
| 2 | **Script Approval** | 6 | If 100% checklist | Approve, request revision, add notes |
| 3 | **Audio Production** | 8 | - | Select takes, regenerate, adjust pauses |
| 4 | **Asset Review** | 12 | - | Approve, reject, request regeneration |
| 5 | **Metadata Selection** | 14 | If rank 1 > 90 | Pick title/description from 3 options |
| 6 | **Comic Script Approval** | 18 | If all scores > 85 | Edit panels, approve, request revision |
| 7 | **Comic Image Review** | 21 | If eval > 90% | Approve, regenerate with adjusted prompts |
| 8 | **Comic Video** | 25 | - | Audio review, panel adjustments (existing tool) |

**Quick Approve**: User can enable auto-approval for checkpoints that meet threshold. User still receives notification.

---

## Progress & Time Estimates

| Step | Estimated Time | Notes |
|------|---------------|-------|
| 1-2. Topic Discovery & Eval | ~2-3 min | Batch of 10-20 topics |
| 3. Topic Selection | Human | Quick if auto-approved |
| 4-5. Script Generation & Review | ~3-5 min | Depends on script length |
| 6. Script Approval | Human | Quick if auto-approved |
| 7. ELS Conversion | ~10 sec | Deterministic |
| 8. Audio Production | Human | 5-15 min depending on takes |
| 9-11. Asset Pipeline | ~2-5 min | Depends on missing assets |
| 12. Asset Review | Human | Quick if few new assets |
| 13-14. SEO Metadata | ~1-2 min | 3 title options |
| 15. Editor Handoff | ~30 sec | Package generation |
| **Video Path Total** | ~15-30 min | Plus human review time |
| 16-17. Comic Condensation & Eval | ~2-3 min | Uses KB |
| 18. Comic Script Approval | Human | Quick if auto-approved |
| 19-20. Comic Image Gen & Eval | ~1-3 min | May auto-retry if < 90% |
| 21. Comic Image Review | Human | Quick if auto-approved |
| 22-23. Comic Audio Script | ~1-2 min | Generate + verify |
| 24. Comic JSON | ~10 sec | Deterministic |
| 25. Comic Video | Human | Existing tool (5-15 min) |
| **Comic Path Total** | ~10-25 min | Plus human review time |

**Full Pipeline (both paths)**: ~30-60 min active time + human review pauses

---

## Required Files from User

**Phase 1 (Foundation):**
1. ✅ **Trash Panda Bible** - Ingested into KB (14 chunks, tagged `trash-panda-bible`)
2. **YouTube Best Practices** (6 files from Claude project, ~3400 lines)
3. **Core-assets.png** - Character reference image for style consistency
4. **Character Voice Mappings** - ElevenLabs voice IDs for each character:
   - Every-Coon, The Fed, Whale, Boomer, Narrator, etc.

**Phase 8 (Comic Path):**
5. **20 Comic KB Documents** (see KB Collections section)

**Optional:**
6. **Existing Asset Images** (if any to seed library)
7. **Past Video Performance Data** (for topic scoring)

---

## Resolved Questions

1. **Comic image generation**: Generate ONE 4K comic grid image. Comic video tool uses JSON coordinates to "camera pan" around it.
2. **Asset storage**: Supabase Storage
3. **Comic video JSON format**: Verified. See below.
4. **Topic Discovery model**: ChatGPT 5.1 (not o1)
5. **Image generation**: Gemini 3 Pro Image Preview (`models/gemini-3-pro-image-preview`) via existing `GeminiService.generate_image()`
6. **Character assets**: Pass Core-assets.png (or similar) as `reference_images` to comic/asset generation
7. **Comic path timing**: Can start after script approval (doesn't need to wait for full editor handoff)

---

## Existing Services to Use

| Service | Location | Use |
|---------|----------|-----|
| `GeminiService.generate_image()` | `gemini_service.py` | Asset & comic generation |
| Claude/Anthropic | Multiple services | Script generation & review |
| OpenAI (embeddings) | `knowledge_base/service.py` | KB search |
| ElevenLabs | `elevenlabs_service.py` | Audio production |
| Comic Video | `comic_video/` | Final video rendering |

---

## Comic Video JSON Format (Verified)

The comic JSON conversion step (Step 18) must produce this format:

```python
{
    "total_panels": 15,
    "structure": {
        "title": "Panel 1",
        "act_1": "Panels 2-4 (The Basics)",
        "act_2": "Panels 5-8 (The Causes)",
        # ...
        "outro": "Panel 15"
    },
    "panels": [
        {
            "panel_number": 1,
            "panel_type": "TITLE",          # TITLE, ACT X - CONTENT, OUTRO
            "header_text": "INFLATION EXPLAINED BY RACCOONS",
            "dialogue": "Raccoon explain why trash cost more.",
            "mood": "neutral",              # neutral|positive|warning|danger|chaos|dramatic|celebration
            "characters_needed": ["every-coon (neutral)"],
            "prompt": "...",                # Image generation prompt (for reference)
        },
        # ... more panels
    ],
    "layout_recommendation": {
        "format": "3 columns x 5 rows",
        "panel_arrangement": [
            ["TITLE (wide, spans 3 columns)"],
            ["Panel 2", "Panel 3", "Panel 4"],
            # ...
        ]
    }
}
```

**ComicLayout model expects:**
- `grid_cols`: Max columns (e.g., 3)
- `grid_rows`: Number of rows (e.g., 5)
- `total_panels`: Total panel count
- `panel_cells`: Dict mapping panel# → list of (row, col) tuples for wide panels
- `canvas_width`, `canvas_height`: 4K dimensions (e.g., 4000×6000)

**Mood → Effects mapping:**
| Mood | Effects |
|------|---------|
| neutral | No effects |
| positive | Golden glow, slight warmth |
| warning | Pulse, light vignette, orange tint |
| danger | Red glow, vignette, shake |
| chaos | Heavy shake, red glow, heavy vignette |
| dramatic | Heavy vignette, zoom pulse |
| celebration | Golden glow, pulse |
