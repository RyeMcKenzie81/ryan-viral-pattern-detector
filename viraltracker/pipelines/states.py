"""
Pipeline state dataclasses for Pydantic Graph workflows.

These state classes are passed through pipeline nodes, accumulating
data at each step. They enable:
- Clean data flow between nodes
- State persistence for resumable workflows
- Error tracking and recovery

Part of the Brand Research Pipeline (Phase 2A).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from uuid import UUID


@dataclass
class BrandOnboardingState:
    """
    State for brand onboarding pipeline.

    Tracks data through the pipeline:
    ScrapeAds → DownloadAssets → AnalyzeImages → AnalyzeVideos → Synthesize

    Attributes:
        ad_library_url: Facebook Ad Library search URL
        brand_id: Optional brand UUID to link research to
        max_ads: Maximum ads to scrape (default 50)
        analyze_videos: Whether to analyze video ads (default True)
        ad_ids: UUIDs of scraped facebook_ads records
        image_asset_ids: UUIDs of image assets
        video_asset_ids: UUIDs of video assets
        image_analyses: Results from Claude Vision analysis
        video_analyses: Results from Gemini video analysis
        summary: Final synthesized brand research
        product_data: Formatted data for product onboarding
        current_step: Current pipeline step for tracking
        error: Error message if pipeline failed
    """

    # Input parameters
    ad_library_url: str
    brand_id: Optional[UUID] = None
    max_ads: int = 50
    analyze_videos: bool = True

    # Populated by ScrapeAdsNode
    ad_ids: List[UUID] = field(default_factory=list)

    # Populated by DownloadAssetsNode
    image_asset_ids: List[UUID] = field(default_factory=list)
    video_asset_ids: List[UUID] = field(default_factory=list)

    # Populated by AnalyzeImagesNode
    image_analyses: List[Dict] = field(default_factory=list)

    # Populated by AnalyzeVideosNode
    video_analyses: List[Dict] = field(default_factory=list)

    # Populated by SynthesizeNode
    summary: Optional[Dict] = None
    product_data: Optional[Dict] = None

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None

    # Metrics
    total_ads_scraped: int = 0
    total_images: int = 0
    total_videos: int = 0


@dataclass
class TemplateIngestionState:
    """
    State for template ingestion pipeline.

    Tracks data through the pipeline:
    ScrapeAds → DownloadAssets → QueueForReview → [PAUSE] → Approve

    The pipeline pauses at QueueForReview for human review in the UI.

    Attributes:
        ad_library_url: Facebook Ad Library search URL
        max_ads: Maximum ads to scrape (default 50)
        images_only: Only queue images, not videos (default True)
        run_ai_analysis: Run AI pre-analysis for reviewers (default True)
        ad_ids: UUIDs of scraped facebook_ads records
        asset_ids: UUIDs of downloaded assets
        queue_ids: UUIDs of template_queue records
        current_step: Current pipeline step
        awaiting_approval: Whether pipeline is paused for approval
        error: Error message if failed
    """

    # Input parameters
    ad_library_url: str
    max_ads: int = 50
    images_only: bool = True
    run_ai_analysis: bool = True

    # Populated by ScrapeAdsNode
    ad_ids: List[UUID] = field(default_factory=list)

    # Populated by DownloadAssetsNode
    asset_ids: List[UUID] = field(default_factory=list)

    # Populated by QueueForReviewNode
    queue_ids: List[UUID] = field(default_factory=list)

    # Tracking
    current_step: str = "pending"
    awaiting_approval: bool = False
    error: Optional[str] = None


@dataclass
class CompetitorResearchState:
    """
    State for competitor research pipeline (future).

    Similar to BrandOnboardingState but doesn't create brand records.
    Used for competitive intelligence without onboarding.
    """

    # Input
    ad_library_url: str
    competitor_name: str
    max_ads: int = 30

    # Results
    ad_ids: List[UUID] = field(default_factory=list)
    analyses: List[Dict] = field(default_factory=list)
    insights: Optional[Dict] = None

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None


@dataclass
class BeliefPlanExecutionState:
    """
    State for Phase 1-2 belief plan execution pipeline.

    Pipeline: LoadPlan → BuildPrompts → GenerateImages → ReviewAds → Complete

    This pipeline generates belief-testing ads for Phase 1-2 plans where:
    - Templates are STYLE references, not final images
    - No product images are composited
    - Only observational anchor text appears on images
    - Copy scaffolds provide Meta headline/primary text (not on image)

    Attributes:
        belief_plan_id: UUID of the belief plan to execute
        variations_per_angle: How many variations per angle×template combo
        canvas_size: Output image dimensions

        plan_data: Full plan with angles, templates, copy sets
        angles: List of angles from the plan
        templates: List of templates from the plan
        persona_data: Persona context for situational generation
        jtbd_data: Job-to-be-done for situational context

        prompts: List of prepared prompts for generation
        total_ads_planned: Count of ads to generate

        generated_ads: Results from image generation
        ad_run_id: UUID of the ad_runs record

        approved_count: Count of approved ads
        rejected_count: Count of rejected ads

        current_step: Current node for status display
        error: Error message if failed
        ads_generated: Progress counter
        ads_reviewed: Progress counter
    """

    # Input parameters
    belief_plan_id: UUID
    variations_per_angle: int = 3
    canvas_size: str = "1080x1080px"

    # Populated by LoadPlanNode
    plan_data: Optional[Dict] = None
    phase_id: int = 1
    angles: List[Dict] = field(default_factory=list)
    templates: List[Dict] = field(default_factory=list)
    persona_data: Optional[Dict] = None
    jtbd_data: Optional[Dict] = None

    # Populated by BuildPromptsNode
    prompts: List[Dict] = field(default_factory=list)
    total_ads_planned: int = 0

    # Populated by GenerateImagesNode
    generated_ads: List[Dict] = field(default_factory=list)
    ad_run_id: Optional[UUID] = None

    # Populated by ReviewAdsNode
    approved_count: int = 0
    rejected_count: int = 0

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None
    ads_generated: int = 0
    ads_reviewed: int = 0
    pipeline_run_id: Optional[str] = None  # For real-time progress updates


@dataclass
class RedditSentimentState:
    """
    State for Reddit domain sentiment analysis pipeline.

    Pipeline: ScrapeReddit → EngagementFilter → RelevanceFilter →
              SignalFilter → IntentScore → TopSelection →
              Categorize → Save

    This pipeline:
    1. Scrapes Reddit posts via Apify
    2. Filters by engagement (upvotes, comments)
    3. Scores relevance using Claude Sonnet
    4. Filters signal from noise using Claude Sonnet
    5. Scores buyer intent/sophistication
    6. Selects top 20% of posts
    7. Categorizes into 6 sentiment buckets using Claude Opus 4.5
    8. Extracts quotes and saves to DB
    9. Optionally syncs to persona fields

    Attributes:
        search_queries: List of search terms to use
        brand_id: Optional brand association
        persona_id: Optional persona for auto-sync
        subreddits: Optional subreddit filter
        ...
    """

    # Input parameters (required)
    search_queries: List[str]

    # Input parameters (optional associations)
    brand_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None

    # Configuration
    subreddits: Optional[List[str]] = None
    timeframe: str = "month"  # hour, day, week, month, year, all
    sort_by: str = "relevance"  # relevance, hot, top, new, comments
    max_posts: int = 500
    min_upvotes: int = 20
    min_comments: int = 5
    relevance_threshold: float = 0.6
    signal_threshold: float = 0.5
    top_percentile: float = 0.20
    scrape_comments: bool = True
    auto_sync_to_persona: bool = True

    # Context for LLM prompts
    persona_context: Optional[str] = None
    topic_context: Optional[str] = None
    brand_context: Optional[str] = None
    product_context: Optional[str] = None

    # Pipeline data - populated by ScrapeRedditNode
    run_id: Optional[UUID] = None
    scraped_posts: List[Dict] = field(default_factory=list)
    scraped_comments: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by EngagementFilterNode
    engagement_filtered: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by RelevanceFilterNode
    relevance_filtered: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by SignalFilterNode
    signal_filtered: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by IntentScoreNode
    intent_scored: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by TopSelectionNode
    top_selected: List[Dict] = field(default_factory=list)

    # Pipeline data - populated by CategorizeNode
    categorized_quotes: Dict[str, List[Dict]] = field(default_factory=dict)

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None

    # Metrics
    posts_scraped: int = 0
    posts_after_engagement: int = 0
    posts_after_relevance: int = 0
    posts_after_signal: int = 0
    posts_top_selected: int = 0
    quotes_extracted: int = 0
    quotes_synced: int = 0

    # Cost tracking
    apify_cost: float = 0.0
    llm_cost_estimate: float = 0.0
