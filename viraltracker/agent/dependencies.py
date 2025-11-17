"""
Agent Dependencies - Typed dependency injection for Pydantic AI agent.

Provides typed access to all services (Twitter, Gemini, Stats) and configuration
needed by agent tools.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..services.twitter_service import TwitterService
from ..services.gemini_service import GeminiService
from ..services.stats_service import StatsService

logger = logging.getLogger(__name__)


@dataclass
class AgentDependencies:
    """
    Typed dependencies for Pydantic AI agent.

    Provides access to all services and configuration needed by agent tools.
    Uses dependency injection pattern for clean separation of concerns.

    Attributes:
        twitter: TwitterService for database operations
        gemini: GeminiService for AI hook analysis
        stats: StatsService for statistical calculations
        project_name: Name of the project being analyzed (e.g., 'yakety-pack-instagram')

    Example:
        >>> deps = AgentDependencies.create(project_name="yakety-pack-instagram")
        >>> tweets = await deps.twitter.get_tweets(project=deps.project_name, hours_back=24)
        >>> analysis = await deps.gemini.analyze_hook(tweet_text=tweets[0].text)
    """

    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    project_name: str = "yakety-pack-instagram"

    @classmethod
    def create(
        cls,
        project_name: str = "yakety-pack-instagram",
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-2.0-flash-exp",
        rate_limit_rpm: int = 9,
    ) -> "AgentDependencies":
        """
        Factory method to create AgentDependencies with initialized services.

        Args:
            project_name: Name of the project to analyze (default: "yakety-pack-instagram")
            gemini_api_key: Optional Gemini API key (default: uses environment variable)
            gemini_model: Gemini model to use (default: "gemini-2.0-flash-exp")
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

        return cls(
            twitter=twitter,
            gemini=gemini,
            stats=stats,
            project_name=project_name
        )

    def __str__(self) -> str:
        """String representation for debugging."""
        return (
            f"AgentDependencies(project_name='{self.project_name}', "
            f"services=[TwitterService, GeminiService, StatsService])"
        )

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return self.__str__()
