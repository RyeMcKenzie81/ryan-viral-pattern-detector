"""
Agent Collector - Discover and catalog all PydanticAI agents for documentation.

This module discovers agents from the viraltracker/agent/ directory
and extracts metadata for documentation and the Agent Catalog UI.

Usage:
    from viraltracker.agent.agent_collector import get_all_agents

    agents = get_all_agents()
    for agent_name, agent_info in agents.items():
        print(f"{agent_name}: {agent_info.tool_count} tools")
"""

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolSummary:
    """Brief summary of a tool for agent documentation."""
    name: str
    description: str
    category: str


@dataclass
class AgentInfo:
    """Information about a PydanticAI agent."""
    name: str
    display_name: str
    module_path: str
    description: str
    system_prompt: str
    model: str
    tool_count: int
    tools: List[ToolSummary] = field(default_factory=list)
    role: str = ""
    is_orchestrator: bool = False


# Agent display names and roles
AGENT_METADATA = {
    'orchestrator': {
        'display_name': 'Orchestrator Agent',
        'role': 'Intelligent request routing and coordination',
        'is_orchestrator': True
    },
    'twitter_agent': {
        'display_name': 'Twitter Agent',
        'role': 'Twitter/X platform specialist'
    },
    'tiktok_agent': {
        'display_name': 'TikTok Agent',
        'role': 'TikTok platform specialist'
    },
    'youtube_agent': {
        'display_name': 'YouTube Agent',
        'role': 'YouTube platform specialist'
    },
    'facebook_agent': {
        'display_name': 'Facebook Agent',
        'role': 'Facebook Ad Library specialist'
    },
    'analysis_agent': {
        'display_name': 'Analysis Agent',
        'role': 'Advanced analytics and AI-powered insights'
    },
    'ad_creation_agent': {
        'display_name': 'Ad Creation Agent',
        'role': 'Facebook ad creative generation specialist'
    },
    'audio_production_agent': {
        'display_name': 'Audio Production Agent',
        'role': 'ElevenLabs audio generation specialist'
    }
}


def extract_tool_summary(tool_name: str, tool: Any) -> ToolSummary:
    """
    Extract summary info from a tool object.

    Args:
        tool_name: Name of the tool
        tool: Pydantic AI Tool object

    Returns:
        ToolSummary dataclass
    """
    description = "No description"
    if hasattr(tool, 'description') and tool.description:
        description = tool.description
        # Truncate long descriptions
        if len(description) > 100:
            description = description[:100] + "..."

    category = "Unknown"
    if hasattr(tool, 'metadata') and tool.metadata:
        category = tool.metadata.get('category', 'Unknown')

    return ToolSummary(
        name=tool_name,
        description=description,
        category=category
    )


def extract_agent_info(
    agent_name: str,
    agent: Any,
    module_path: str
) -> Optional[AgentInfo]:
    """
    Extract information from a PydanticAI agent object.

    Args:
        agent_name: Name identifier for the agent
        agent: PydanticAI Agent object
        module_path: Full import path

    Returns:
        AgentInfo dataclass or None if extraction fails
    """
    try:
        # Get metadata from our mapping
        metadata = AGENT_METADATA.get(agent_name, {})
        display_name = metadata.get('display_name', agent_name.replace('_', ' ').title())
        role = metadata.get('role', '')
        is_orchestrator = metadata.get('is_orchestrator', False)

        # Get description from system prompt
        system_prompt = ""
        if hasattr(agent, 'system_prompt'):
            # system_prompt might be a callable or string
            sp = agent.system_prompt
            if callable(sp):
                try:
                    system_prompt = sp()
                except:
                    system_prompt = str(sp)
            else:
                system_prompt = str(sp) if sp else ""

        # First sentence as description
        description = system_prompt.split('.')[0] + '.' if system_prompt else role

        # Get model
        model = "Unknown"
        if hasattr(agent, 'model'):
            model_obj = agent.model
            if hasattr(model_obj, 'name'):
                model = model_obj.name
            elif hasattr(model_obj, 'model_name'):
                model = model_obj.model_name
            else:
                model = str(model_obj)

        # Get tools
        tools = []
        tool_count = 0

        if hasattr(agent, '_function_toolset'):
            toolset = agent._function_toolset
            if hasattr(toolset, 'tools'):
                for tool_name, tool in toolset.tools.items():
                    tool_summary = extract_tool_summary(tool_name, tool)
                    tools.append(tool_summary)
                tool_count = len(tools)

        # Sort tools by name
        tools.sort(key=lambda t: t.name)

        return AgentInfo(
            name=agent_name,
            display_name=display_name,
            module_path=module_path,
            description=description,
            system_prompt=system_prompt,
            model=model,
            tool_count=tool_count,
            tools=tools,
            role=role,
            is_orchestrator=is_orchestrator
        )

    except Exception as e:
        logger.warning(f"Could not extract info for agent {agent_name}: {e}")
        return None


def get_static_agents() -> Dict[str, AgentInfo]:
    """
    Return static agent metadata as fallback when imports fail.

    This ensures the catalog always shows useful information even
    when pydantic_ai or other dependencies aren't available.
    """
    static_agents = {
        'orchestrator': AgentInfo(
            name='orchestrator',
            display_name='Orchestrator Agent',
            module_path='viraltracker.agent.orchestrator',
            description='Routes requests to specialized agents based on intent.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=7,
            tools=[
                ToolSummary('route_to_twitter_agent', 'Route to Twitter Agent', 'Routing'),
                ToolSummary('route_to_tiktok_agent', 'Route to TikTok Agent', 'Routing'),
                ToolSummary('route_to_youtube_agent', 'Route to YouTube Agent', 'Routing'),
                ToolSummary('route_to_facebook_agent', 'Route to Facebook Agent', 'Routing'),
                ToolSummary('route_to_analysis_agent', 'Route to Analysis Agent', 'Routing'),
                ToolSummary('route_to_ad_creation_agent', 'Route to Ad Creation Agent', 'Routing'),
                ToolSummary('resolve_product_name', 'Look up product by name', 'Routing'),
            ],
            role='Intelligent request routing and coordination',
            is_orchestrator=True
        ),
        'twitter_agent': AgentInfo(
            name='twitter_agent',
            display_name='Twitter Agent',
            module_path='viraltracker.agent.agents.twitter_agent',
            description='Handles Twitter/X data operations.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=8,
            tools=[],
            role='Twitter/X platform specialist',
            is_orchestrator=False
        ),
        'tiktok_agent': AgentInfo(
            name='tiktok_agent',
            display_name='TikTok Agent',
            module_path='viraltracker.agent.agents.tiktok_agent',
            description='Handles TikTok video discovery and analysis.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=5,
            tools=[],
            role='TikTok platform specialist',
            is_orchestrator=False
        ),
        'youtube_agent': AgentInfo(
            name='youtube_agent',
            display_name='YouTube Agent',
            module_path='viraltracker.agent.agents.youtube_agent',
            description='Handles YouTube video search and discovery.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=1,
            tools=[],
            role='YouTube platform specialist',
            is_orchestrator=False
        ),
        'facebook_agent': AgentInfo(
            name='facebook_agent',
            display_name='Facebook Agent',
            module_path='viraltracker.agent.agents.facebook_agent',
            description='Handles Facebook Ad Library operations.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=2,
            tools=[],
            role='Facebook Ad Library specialist',
            is_orchestrator=False
        ),
        'analysis_agent': AgentInfo(
            name='analysis_agent',
            display_name='Analysis Agent',
            module_path='viraltracker.agent.agents.analysis_agent',
            description='Handles statistical analysis and AI-powered insights.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=3,
            tools=[],
            role='Advanced analytics and AI-powered insights',
            is_orchestrator=False
        ),
        'ad_creation_agent': AgentInfo(
            name='ad_creation_agent',
            display_name='Ad Creation Agent',
            module_path='viraltracker.agent.agents.ad_creation_agent',
            description='Handles Facebook ad creative generation.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=14,
            tools=[],
            role='Facebook ad creative generation specialist',
            is_orchestrator=False
        ),
        'audio_production_agent': AgentInfo(
            name='audio_production_agent',
            display_name='Audio Production Agent',
            module_path='viraltracker.agent.agents.audio_production_agent',
            description='Handles ElevenLabs audio generation.',
            system_prompt='',
            model='claude-sonnet-4-5-20250929',
            tool_count=11,
            tools=[],
            role='ElevenLabs audio generation specialist',
            is_orchestrator=False
        ),
    }
    return static_agents


def get_all_agents() -> Dict[str, AgentInfo]:
    """
    Discover all agents from viraltracker.agent.

    Falls back to static metadata if imports fail (e.g., pydantic_ai not available).

    Returns:
        Dictionary mapping agent names to AgentInfo objects
    """
    agents = {}

    try:
        # Import orchestrator
        from viraltracker.agent.orchestrator import orchestrator
        orchestrator_info = extract_agent_info(
            'orchestrator',
            orchestrator,
            'viraltracker.agent.orchestrator'
        )
        if orchestrator_info:
            agents['orchestrator'] = orchestrator_info

    except Exception as e:
        logger.warning(f"Could not import orchestrator: {e}")

    # Discover specialized agents
    agent_modules = [
        ('twitter_agent', 'viraltracker.agent.agents.twitter_agent', 'twitter_agent'),
        ('tiktok_agent', 'viraltracker.agent.agents.tiktok_agent', 'tiktok_agent'),
        ('youtube_agent', 'viraltracker.agent.agents.youtube_agent', 'youtube_agent'),
        ('facebook_agent', 'viraltracker.agent.agents.facebook_agent', 'facebook_agent'),
        ('analysis_agent', 'viraltracker.agent.agents.analysis_agent', 'analysis_agent'),
        ('ad_creation_agent', 'viraltracker.agent.agents.ad_creation_agent', 'ad_creation_agent'),
        ('audio_production_agent', 'viraltracker.agent.agents.audio_production_agent', 'audio_production_agent'),
    ]

    for agent_name, module_path, attr_name in agent_modules:
        try:
            module = importlib.import_module(module_path)
            agent = getattr(module, attr_name, None)

            if agent:
                agent_info = extract_agent_info(agent_name, agent, module_path)
                if agent_info:
                    agents[agent_name] = agent_info
                    logger.debug(f"Discovered agent: {agent_name} ({agent_info.tool_count} tools)")

        except Exception as e:
            logger.debug(f"Could not import {module_path}: {e}")

    # If no agents discovered dynamically, use static fallback
    if not agents:
        logger.info("Using static agent metadata (dynamic import failed)")
        return get_static_agents()

    logger.info(f"Discovered {len(agents)} agents dynamically")

    return agents


def get_agent_stats() -> Dict[str, Any]:
    """
    Get statistics about discovered agents.

    Returns:
        Dictionary with agent statistics
    """
    agents = get_all_agents()

    total_tools = sum(a.tool_count for a in agents.values())
    orchestrator_tools = sum(a.tool_count for a in agents.values() if a.is_orchestrator)
    specialist_tools = total_tools - orchestrator_tools
    specialist_count = sum(1 for a in agents.values() if not a.is_orchestrator)

    return {
        'total_agents': len(agents),
        'orchestrator_count': 1 if any(a.is_orchestrator for a in agents.values()) else 0,
        'specialist_count': specialist_count,
        'total_tools': total_tools,
        'routing_tools': orchestrator_tools,
        'platform_tools': specialist_tools,
        'avg_tools_per_agent': round(total_tools / len(agents), 1) if agents else 0
    }


def get_agents_by_type() -> Dict[str, List[AgentInfo]]:
    """
    Organize agents by type (orchestrator vs specialist).

    Returns:
        Dictionary with 'orchestrator' and 'specialist' lists
    """
    agents = get_all_agents()

    return {
        'orchestrator': [a for a in agents.values() if a.is_orchestrator],
        'specialist': [a for a in agents.values() if not a.is_orchestrator]
    }
