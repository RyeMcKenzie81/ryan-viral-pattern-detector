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
    # ... (existing fields)
    content_pipeline: ContentPipelineService
    reddit_sentiment: RedditSentimentService
    sora: SoraService
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
    ) -> "AgentDependencies":
        # ... (logging)

        # ... (Service initializations)

        # Initialize SoraService for OpenAI video generation
        sora = SoraService()
        logger.info("SoraService initialized")

        return cls(
            # ... (other services)
            content_pipeline=content_pipeline,
            reddit_sentiment=reddit_sentiment,
            sora=sora,
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
