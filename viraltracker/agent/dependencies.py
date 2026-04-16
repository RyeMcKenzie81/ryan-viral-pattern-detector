"""
Agent Dependencies - Typed dependency injection for Pydantic AI agent.

Provides typed access to all services (Twitter, Gemini, Stats, Scraping, Comment)
and configuration needed by agent tools.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from ..core.database import get_supabase_client

from ..services.twitter_service import TwitterService
from ..services.gemini_service import GeminiService
from ..services.stats_service import StatsService
from ..services.scraping_service import ScrapingService
from ..services.comment_service import CommentService
from ..services.tiktok_service import TikTokService
from ..services.youtube_service import YouTubeService
from ..services.facebook_service import FacebookService
from ..services.ad_creation_service import AdCreationService
from ..services.email_service import EmailService
from ..services.slack_service import SlackService
from ..services.elevenlabs_service import ElevenLabsService
from ..services.ffmpeg_service import FFmpegService
from ..services.audio_production_service import AudioProductionService
from ..services.knowledge_base import DocService
from ..services.ad_scraping_service import AdScrapingService
from ..services.brand_research_service import BrandResearchService
from ..services.template_queue_service import TemplateQueueService
from ..services.persona_service import PersonaService
from ..services.product_url_service import ProductURLService
from ..services.content_pipeline.services.content_pipeline_service import ContentPipelineService
from ..services.content_pipeline.services.sora_service import SoraService
from ..services.reddit_sentiment_service import RedditSentimentService
from ..services.product_context_service import ProductContextService
from ..services.belief_analysis_service import BeliefAnalysisService
from ..services.usage_tracker import UsageTracker
from ..services.ad_intelligence.ad_intelligence_service import AdIntelligenceService
from ..services.meta_ads_service import MetaAdsService
from ..services.seo_pipeline.services.seo_project_service import SEOProjectService
from ..services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
from ..services.seo_pipeline.services.seo_analytics_service import SEOAnalyticsService
from ..services.seo_pipeline.services.opportunity_miner_service import OpportunityMinerService
from ..services.seo_pipeline.services.article_tracking_service import ArticleTrackingService
from ..services.seo_pipeline.services.ga4_service import GA4Service
from ..services.ad_performance_query_service import AdPerformanceQueryService
from ..services.klaviyo_service import KlaviyoService
from ..services.competitor_service import CompetitorService
from ..services.competitor_intel_service import CompetitorIntelService

logger = logging.getLogger(__name__)



class ResultCache(BaseModel):
    """
    Shared result cache for inter-agent data passing.

    Enables agents to share data and build on each other's results
    without re-querying or re-scraping data.

    Attributes:
        last_twitter_query: Results from Twitter agent's last query
        last_tiktok_query: Results from TikTok agent's last query
        last_youtube_query: Results from YouTube agent's last query
        last_facebook_query: Results from Facebook agent's last query
        last_analysis: Results from Analysis agent's last analysis
        custom: Arbitrary key-value storage for agent-specific data

    Example:
        >>> cache = ResultCache()
        >>> cache.last_twitter_query = [tweet1, tweet2, tweet3]
        >>> # Later, another agent can access these results
        >>> tweets = cache.last_twitter_query
        >>> cache.clear()  # Clear all cached results
    """
    model_config = {"arbitrary_types_allowed": True}

    last_twitter_query: Optional[List[Any]] = None
    last_tiktok_query: Optional[List[Any]] = None
    last_youtube_query: Optional[List[Any]] = None
    last_facebook_query: Optional[List[Any]] = None
    last_analysis: Optional[Any] = None
    custom: Dict[str, Any] = Field(default_factory=dict)

    def clear(self) -> None:
        """Clear all cached results."""
        self.last_twitter_query = None
        self.last_tiktok_query = None
        self.last_youtube_query = None
        self.last_facebook_query = None
        self.last_analysis = None
        self.custom = {}


class AgentDependencies(BaseModel):
    """
    Typed dependencies for Pydantic AI agent.

    Attributes:
        twitter: TwitterService for Twitter operations
        gemini: GeminiService for AI analysis
        stats: StatsService for metrics
        scraping: ScrapingService for generic scraping
        comment: CommentService for replying
        tiktok: TikTokService for TikTok operations
        youtube: YouTubeService for YouTube video scraping operations
        facebook: FacebookService for Facebook Ads scraping operations
        project_name: Name of the project being analyzed (e.g., 'yakety-pack-instagram')
        result_cache: Shared result cache for inter-agent communication
    """
    model_config = {"arbitrary_types_allowed": True}

    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    scraping: ScrapingService
    comment: CommentService
    tiktok: TikTokService
    youtube: YouTubeService
    facebook: FacebookService
    ad_creation: AdCreationService
    email: EmailService
    slack: SlackService
    elevenlabs: ElevenLabsService
    ffmpeg: FFmpegService
    audio_production: AudioProductionService
    ad_scraping: AdScrapingService
    brand_research: BrandResearchService
    template_queue: TemplateQueueService
    persona: PersonaService
    product_url: ProductURLService
    content_pipeline: ContentPipelineService
    reddit_sentiment: RedditSentimentService
    product_context: ProductContextService
    belief_analysis: BeliefAnalysisService
    sora: SoraService
    ad_intelligence: AdIntelligenceService
    meta_ads: MetaAdsService
    klaviyo: KlaviyoService
    competitor: CompetitorService
    competitor_intel: CompetitorIntelService
    seo_project: Optional[SEOProjectService] = None
    seo_keyword_discovery: Optional[KeywordDiscoveryService] = None
    seo_analytics: Optional[SEOAnalyticsService] = None
    seo_opportunity_miner: Optional[OpportunityMinerService] = None
    seo_article_tracking: Optional[ArticleTrackingService] = None
    seo_ga4: Optional[GA4Service] = None
    ad_performance_query: AdPerformanceQueryService
    docs: Optional[DocService] = None
    project_name: str = "yakety-pack-instagram"
    result_cache: ResultCache = Field(default_factory=ResultCache)

    @classmethod
    def create(
        cls,
        project_name: str = "yakety-pack-instagram",
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "models/gemini-3-pro-image-preview",
        rate_limit_rpm: int = 9,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> "AgentDependencies":
        """
        Factory method to create AgentDependencies with initialized services.

        Args:
            project_name: Project name for context
            gemini_api_key: Optional Gemini API key (uses env var if not provided)
            gemini_model: Gemini model to use
            rate_limit_rpm: Rate limit for Gemini API
            user_id: Optional user ID for usage tracking
            organization_id: Optional organization ID for usage tracking/billing
        """
        logger.info(f"Initializing agent dependencies for project: {project_name}")

        # Initialize TwitterService (uses environment variables for credentials)
        twitter = TwitterService()
        logger.info("TwitterService initialized")

        # Initialize GeminiService with optional custom API key
        gemini = GeminiService(api_key=gemini_api_key, model=gemini_model)
        gemini.set_rate_limit(rate_limit_rpm)
        logger.info(f"GeminiService initialized (model: {gemini_model}, rate limit: {rate_limit_rpm} req/min)")

        # Set up usage tracking if organization_id is provided
        if organization_id:
            try:
                supabase_client = get_supabase_client()
                usage_tracker = UsageTracker(supabase_client)
                gemini.set_tracking_context(usage_tracker, user_id, organization_id)
                logger.info(f"GeminiService usage tracking enabled (org: {organization_id})")
            except Exception as e:
                logger.warning(f"Failed to set up usage tracking: {e}")

        # Initialize StatsService (no initialization needed, static methods)
        stats = StatsService()
        logger.info("StatsService initialized")

        # Initialize ScrapingService for Twitter scraping
        scraping = ScrapingService()
        logger.info("ScrapingService initialized")

        # Initialize CommentService for comment opportunities
        comment = CommentService()
        logger.info("CommentService initialized")

        # Initialize TikTokService for TikTok operations
        tiktok = TikTokService()
        logger.info("TikTokService initialized")

        # Initialize YouTubeService for YouTube operations
        youtube = YouTubeService()
        logger.info("YouTubeService initialized")

        # Initialize FacebookService for Facebook Ads operations
        facebook = FacebookService()
        logger.info("FacebookService initialized")

        # Initialize AdCreationService for ad creative generation
        ad_creation = AdCreationService()
        logger.info("AdCreationService initialized")

        # Initialize EmailService for email notifications
        email = EmailService()
        logger.info(f"EmailService initialized (enabled={email.enabled})")

        # Initialize SlackService for Slack notifications
        slack = SlackService()
        logger.info(f"SlackService initialized (enabled={slack.enabled})")

        # Initialize ElevenLabsService for audio generation
        elevenlabs = ElevenLabsService()
        logger.info(f"ElevenLabsService initialized (enabled={elevenlabs.enabled})")

        # Initialize FFmpegService for audio processing
        ffmpeg = FFmpegService()
        logger.info(f"FFmpegService initialized (available={ffmpeg.available})")

        # Initialize AudioProductionService for production workflow
        audio_production = AudioProductionService()
        logger.info("AudioProductionService initialized")

        # Initialize AdScrapingService for downloading FB ad assets
        ad_scraping = AdScrapingService()
        logger.info("AdScrapingService initialized")

        # Initialize BrandResearchService for AI analysis of brand ads
        brand_research = BrandResearchService()
        logger.info("BrandResearchService initialized")

        # Initialize TemplateQueueService for template approval workflow
        template_queue = TemplateQueueService()
        logger.info("TemplateQueueService initialized")

        # Initialize PersonaService for 4D persona management
        persona = PersonaService()
        logger.info("PersonaService initialized")

        # Initialize ProductURLService for URL-to-product mapping
        product_url = ProductURLService()
        logger.info("ProductURLService initialized")

        # Initialize DocService for knowledge base (optional - requires OPENAI_API_KEY)
        docs = None
        supabase = None
        if os.getenv("OPENAI_API_KEY"):
            try:
                supabase = get_supabase_client()
                docs = DocService(supabase=supabase)

                # Set up usage tracking for DocService if org context available
                if organization_id and organization_id != "all":
                    docs.set_tracking_context(
                        UsageTracker(supabase), user_id, organization_id
                    )

                logger.info("DocService initialized (knowledge base enabled)")
            except Exception as e:
                logger.warning(f"DocService initialization failed: {e}")
        else:
            logger.info("DocService skipped (OPENAI_API_KEY not set)")

        # Initialize ContentPipelineService for content pipeline workflow
        # Pass gemini service with tracking context for AI operations
        content_pipeline = ContentPipelineService(
            supabase_client=supabase,
            docs_service=docs,
            gemini_service=gemini  # Inherits tracking context from above
        )
        logger.info("ContentPipelineService initialized")

        # Initialize RedditSentimentService for Reddit sentiment analysis
        reddit_sentiment = RedditSentimentService()
        logger.info("RedditSentimentService initialized")

        # Initialize ProductContextService for product context retrieval
        product_context = ProductContextService()
        logger.info("ProductContextService initialized")

        # Initialize BeliefAnalysisService for belief-first canvas analysis
        belief_analysis = BeliefAnalysisService()
        logger.info("BeliefAnalysisService initialized")

        # Initialize SoraService
        sora = SoraService()
        logger.info("SoraService initialized")

        # Initialize MetaAdsService for Meta Ads API operations
        meta_ads = MetaAdsService()
        logger.info("MetaAdsService initialized")

        # Initialize KlaviyoService for email marketing
        klaviyo = KlaviyoService()
        logger.info("KlaviyoService initialized")

        # Initialize CompetitorService and CompetitorIntelService
        competitor = CompetitorService()
        competitor_intel = CompetitorIntelService()
        logger.info("CompetitorService + CompetitorIntelService initialized")

        # Initialize SEO pipeline services
        seo_project = SEOProjectService(supabase_client=supabase)
        seo_keyword_discovery = KeywordDiscoveryService(supabase_client=supabase)
        seo_analytics = SEOAnalyticsService(supabase_client=supabase)
        seo_opportunity_miner = OpportunityMinerService(supabase_client=supabase)
        seo_article_tracking = ArticleTrackingService(supabase_client=supabase)
        seo_ga4 = GA4Service(supabase_client=supabase)
        logger.info("SEO pipeline services initialized (6 services)")

        # Initialize AdIntelligenceService for ad account analysis
        if supabase is None:
            supabase = get_supabase_client()
        ad_intelligence = AdIntelligenceService(
            supabase, gemini_service=gemini, meta_ads_service=meta_ads
        )
        logger.info("AdIntelligenceService initialized")

        # Initialize AdPerformanceQueryService for conversational performance queries
        ad_performance_query = AdPerformanceQueryService(supabase)
        logger.info("AdPerformanceQueryService initialized")

        return cls(
            twitter=twitter,
            gemini=gemini,
            stats=stats,
            scraping=scraping,
            comment=comment,
            tiktok=tiktok,
            youtube=youtube,
            facebook=facebook,
            ad_creation=ad_creation,
            email=email,
            slack=slack,
            elevenlabs=elevenlabs,
            ffmpeg=ffmpeg,
            audio_production=audio_production,
            ad_scraping=ad_scraping,
            brand_research=brand_research,
            template_queue=template_queue,
            persona=persona,
            product_url=product_url,
            content_pipeline=content_pipeline,
            reddit_sentiment=reddit_sentiment,
            product_context=product_context,
            belief_analysis=belief_analysis,
            sora=sora,
            ad_intelligence=ad_intelligence,
            meta_ads=meta_ads,
            klaviyo=klaviyo,
            competitor=competitor,
            competitor_intel=competitor_intel,
            seo_project=seo_project,
            seo_keyword_discovery=seo_keyword_discovery,
            seo_analytics=seo_analytics,
            seo_opportunity_miner=seo_opportunity_miner,
            seo_article_tracking=seo_article_tracking,
            seo_ga4=seo_ga4,
            ad_performance_query=ad_performance_query,
            docs=docs,
            project_name=project_name
        )

    def __str__(self) -> str:
        """String representation for debugging."""
        docs_status = "enabled" if self.docs else "disabled"
        return (
            f"AgentDependencies(project_name='{self.project_name}', "
            f"services=[TwitterService, GeminiService, StatsService, ScrapingService, CommentService, "
            f"TikTokService, YouTubeService, FacebookService, AdCreationService, EmailService, SlackService, "
            f"SoraService, DocService({docs_status})], result_cache={self.result_cache})"
        )

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return self.__str__()
