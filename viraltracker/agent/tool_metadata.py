"""
Tool Metadata Schema - Type-safe metadata for Pydantic AI tools.

This module defines the standard metadata schema used across all agent tools.
Metadata is stored in the `metadata` parameter of `@agent.tool` decorator and
is NOT sent to the LLM (unlike docstrings which ARE sent to the LLM).

Usage:
    @twitter_agent.tool(
        metadata=ToolMetadata(
            category='Ingestion',
            platform='Twitter',
            rate_limit='20/minute',
            use_cases=['Search for tweets'],
            examples=['Find tweets about AI']
        )
    )
    async def search_twitter(ctx: RunContext[AgentDependencies], query: str):
        ...
"""

from typing import TypedDict, List, Literal


# Valid categories for pipeline stages
Category = Literal[
    'Routing',      # Orchestrator routing tools
    'Ingestion',    # Data collection from platforms
    'Filtration',   # Data filtering and preprocessing
    'Discovery',    # Pattern and outlier detection
    'Analysis',     # Deep analysis (hooks, sentiment, etc.)
    'Generation',   # Content generation
    'Export'        # Data export and reporting
]

# Valid platforms
Platform = Literal[
    'Twitter',
    'TikTok',
    'YouTube',
    'Facebook',
    'Instagram',
    'All'           # Cross-platform tools
]


class ToolMetadata(TypedDict, total=False):
    """
    Standard metadata schema for all Pydantic AI tools.

    This metadata is used for:
    - FastAPI endpoint generation and configuration
    - Rate limiting
    - Tool categorization and organization
    - Documentation and examples
    - Streamlit UI display

    NOT sent to the LLM (use docstrings for that).

    Attributes:
        category: Pipeline stage category
        platform: Platform the tool operates on
        rate_limit: Rate limit string (e.g., "20/minute", "10/hour")
        requires_auth: Whether API endpoint requires authentication
        use_cases: List of use cases for documentation
        examples: List of example queries that would use this tool
        estimated_cost: Estimated API cost per call (optional)
        requires_services: List of service names this tool depends on
    """
    category: Category
    platform: Platform
    rate_limit: str
    requires_auth: bool
    use_cases: List[str]
    examples: List[str]
    estimated_cost: float  # In USD
    requires_services: List[str]  # e.g., ['twitter', 'gemini']


# Default metadata values
DEFAULT_METADATA: ToolMetadata = {
    'category': 'Discovery',
    'platform': 'All',
    'rate_limit': '20/minute',
    'requires_auth': True,
    'use_cases': [],
    'examples': [],
}


def create_tool_metadata(
    category: Category = 'Discovery',
    platform: Platform = 'All',
    rate_limit: str = '20/minute',
    requires_auth: bool = True,
    use_cases: List[str] = None,
    examples: List[str] = None,
    estimated_cost: float = None,
    requires_services: List[str] = None
) -> ToolMetadata:
    """
    Helper function to create ToolMetadata with defaults.

    Args:
        category: Pipeline stage category
        platform: Platform the tool operates on
        rate_limit: Rate limit string (default: "20/minute")
        requires_auth: Whether API endpoint requires authentication (default: True)
        use_cases: List of use cases (default: [])
        examples: List of example queries (default: [])
        estimated_cost: Estimated API cost per call
        requires_services: List of required service names

    Returns:
        ToolMetadata dictionary

    Example:
        metadata = create_tool_metadata(
            category='Ingestion',
            platform='Twitter',
            rate_limit='10/minute',
            use_cases=['Search tweets', 'Monitor brand'],
            examples=['Find tweets about AI']
        )
    """
    metadata: ToolMetadata = {
        'category': category,
        'platform': platform,
        'rate_limit': rate_limit,
        'requires_auth': requires_auth,
        'use_cases': use_cases or [],
        'examples': examples or [],
    }

    if estimated_cost is not None:
        metadata['estimated_cost'] = estimated_cost

    if requires_services is not None:
        metadata['requires_services'] = requires_services

    return metadata


__all__ = [
    'ToolMetadata',
    'Category',
    'Platform',
    'DEFAULT_METADATA',
    'create_tool_metadata'
]
