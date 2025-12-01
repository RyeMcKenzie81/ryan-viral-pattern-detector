"""
Agent Dependencies - Typed dependency injection for Pydantic AI agent.

Provides typed access to all services (Twitter, Gemini, Stats, Scraping, Comment)
and configuration needed by agent tools.
"""

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

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

    Provides access to all services and configuration needed by agent tools.
    Uses dependency injection pattern for clean separation of concerns.

    Attributes:
        twitter: TwitterService for database operations
        gemini: GeminiService for AI hook analysis and content generation
        stats: StatsService for statistical calculations
        scraping: ScrapingService for Twitter scraping operations
        comment: CommentService for comment opportunity operations
        tiktok: TikTokService for TikTok scraping and analysis operations
        youtube: YouTubeService for YouTube video scraping operations
        facebook: FacebookService for Facebook Ads scraping operations
        ad_creation: AdCreationService for Facebook ad creative generation
        email: EmailService for sending emails via Resend
        slack: SlackService for sending Slack messages via webhooks
        project_name: Name of the project being analyzed (e.g., 'yakety-pack-instagram')
        result_cache: Shared result cache for inter-agent communication

    Example:
        >>> deps = AgentDependencies.create(project_name="yakety-pack-instagram")
        >>> tweets = await deps.twitter.get_tweets(project=deps.project_name, hours_back=24)
        >>> analysis = await deps.gemini.analyze_hook(tweet_text=tweets[0].text)
        >>> # Cache results for other agents
        >>> deps.result_cache.last_twitter_query = tweets
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
        """
        Factory method to create AgentDependencies with initialized services.

        Args:
            project_name: Name of the project to analyze (default: "yakety-pack-instagram")
            gemini_api_key: Optional Gemini API key (default: uses environment variable)
            gemini_model: Gemini model to use (default: "models/gemini-3-pro-image-preview")
            rate_limit_rpm: Rate limit for Gemini API in requests per minute (default: 9)

        Returns:
            AgentDependencies instance with all services initialized

        Raises:
            ValueError: If required credentials (Supabase, Gemini) are missing

        Example:
            >>> # Use defaults
            >>> deps = AgentDependencies.create()

            >>> # Customize project and rate limiting
            >>> deps = AgentDependencies.create(
            ...     project_name="my-project",
            ...     rate_limit_rpm=6
            ... )

            >>> # Use custom API key
            >>> deps = AgentDependencies.create(
            ...     gemini_api_key="your-api-key-here"
            ... )
        """
        logger.info(f"Initializing agent dependencies for project: {project_name}")

        # Initialize TwitterService (uses environment variables for credentials)
        twitter = TwitterService()
        logger.info("TwitterService initialized")

        # Initialize GeminiService with optional custom API key
        gemini = GeminiService(api_key=gemini_api_key, model=gemini_model)
        gemini.set_rate_limit(rate_limit_rpm)
        logger.info(f"GeminiService initialized (model: {gemini_model}, rate limit: {rate_limit_rpm} req/min)")

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
            project_name=project_name
        )

    def __str__(self) -> str:
        """String representation for debugging."""
        return (
            f"AgentDependencies(project_name='{self.project_name}', "
            f"services=[TwitterService, GeminiService, StatsService, ScrapingService, CommentService, "
            f"TikTokService, YouTubeService, FacebookService, AdCreationService, EmailService, SlackService], "
            f"result_cache={self.result_cache})"
        )

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return self.__str__()
