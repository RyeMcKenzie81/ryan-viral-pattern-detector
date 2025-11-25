"""
Tool Collector - Collect tools from all agents for documentation and UI.

This replaces the old tool_registry pattern. Instead of manually registering
tools in a central registry, this module discovers tools directly from agent
instances using Pydantic AI's native `agent.tools` attribute.

Usage:
    from viraltracker.agent.tool_collector import get_all_tools

    tools = get_all_tools()
    for tool_name, tool_info in tools.items():
        print(f"{tool_name}: {tool_info['description']}")
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from pydantic_ai.tools import Tool


@dataclass
class ToolInfo:
    """Information about a tool extracted from agent."""
    name: str
    description: str
    category: str
    platform: str
    api_path: str
    rate_limit: str
    use_cases: List[str]
    examples: List[str]
    requires_auth: bool = True


def extract_tool_info(tool_name: str, tool: Any, platform: str) -> ToolInfo:
    """
    Extract tool information from a Pydantic AI Tool object.

    Args:
        tool_name: Name of the tool
        tool: Pydantic AI Tool object with metadata
        platform: Platform name (e.g., "Twitter", "TikTok")

    Returns:
        ToolInfo dataclass with extracted metadata
    """
    # Get metadata from tool's function if it exists
    metadata = {}
    if hasattr(tool, 'function') and hasattr(tool.function, 'metadata'):
        metadata = tool.function.metadata

    # Get description from tool
    description = tool.description if hasattr(tool, 'description') and tool.description else "No description available"

    # Extract metadata with defaults
    category = metadata.get('category', 'Unknown')
    platform_name = metadata.get('platform', platform)
    rate_limit = metadata.get('rate_limit', 'N/A')
    use_cases = metadata.get('use_cases', [])
    examples = metadata.get('examples', [])

    # Generate API path
    api_path = f"/tools/{tool_name.replace('_', '-')}"

    return ToolInfo(
        name=tool_name,
        description=description,
        category=category,
        platform=platform_name,
        api_path=api_path,
        rate_limit=rate_limit,
        use_cases=use_cases,
        examples=examples,
        requires_auth=True
    )


def get_all_tools() -> Dict[str, ToolInfo]:
    """
    Collect all tools from all agents.

    Returns:
        Dictionary mapping tool names to ToolInfo objects
    """
    # Import agents (this triggers tool registration via decorators)
    from .agents.twitter_agent import twitter_agent
    from .agents.tiktok_agent import tiktok_agent
    from .agents.youtube_agent import youtube_agent
    from .agents.facebook_agent import facebook_agent
    from .agents.analysis_agent import analysis_agent

    agents = {
        'Twitter': twitter_agent,
        'TikTok': tiktok_agent,
        'YouTube': youtube_agent,
        'Facebook': facebook_agent,
        'Analysis': analysis_agent
    }

    all_tools = {}

    for platform, agent in agents.items():
        # Access agent's function toolset (same as endpoint_generator does)
        toolset = agent._function_toolset
        tools_dict = toolset.tools

        # Iterate through tools dictionary
        for tool_name, tool in tools_dict.items():
            tool_info = extract_tool_info(tool_name, tool, platform)
            all_tools[tool_name] = tool_info

    return all_tools


def get_tools_by_category() -> Dict[str, List[ToolInfo]]:
    """
    Organize tools by category.

    Returns:
        Dictionary mapping categories to lists of ToolInfo objects
    """
    tools = get_all_tools()
    categories = {}

    for tool_info in tools.values():
        category = tool_info.category
        if category not in categories:
            categories[category] = []
        categories[category].append(tool_info)

    return categories


def get_tools_by_platform() -> Dict[str, List[ToolInfo]]:
    """
    Organize tools by platform.

    Returns:
        Dictionary mapping platforms to lists of ToolInfo objects
    """
    tools = get_all_tools()
    platforms = {}

    for tool_info in tools.values():
        platform = tool_info.platform
        if platform not in platforms:
            platforms[platform] = []
        platforms[platform].append(tool_info)

    return platforms
