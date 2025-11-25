"""
Specialized Agent Exports

This module exports all specialized agents for the viraltracker orchestrator pattern.
Each agent is responsible for a specific platform or analysis task.

Available Agents:
- twitter_agent: Twitter/X platform operations (8 tools)
- tiktok_agent: TikTok platform operations (5 tools)
- youtube_agent: YouTube platform operations (1 tool)
- facebook_agent: Facebook Ad Library operations (2 tools)
- analysis_agent: Advanced statistical and AI analysis (3 tools)
- ad_creation_agent: Facebook ad creative generation (14 tools)

Total: 33 tools across 6 specialized agents

Example usage:
    from viraltracker.agent.agents import twitter_agent, analysis_agent, ad_creation_agent

    # Use twitter agent
    result = await twitter_agent.run("Find top tweets about AI", deps=deps)

    # Use analysis agent
    outliers = await analysis_agent.run("Find viral outliers", deps=deps)

    # Use ad creation agent
    ads = await ad_creation_agent.run("Create 5 ads for Wonder Paws", deps=deps)
"""

from .twitter_agent import twitter_agent
from .tiktok_agent import tiktok_agent
from .youtube_agent import youtube_agent
from .facebook_agent import facebook_agent
from .analysis_agent import analysis_agent
from .ad_creation_agent import ad_creation_agent

__all__ = [
    "twitter_agent",
    "tiktok_agent",
    "youtube_agent",
    "facebook_agent",
    "analysis_agent",
    "ad_creation_agent",
]
