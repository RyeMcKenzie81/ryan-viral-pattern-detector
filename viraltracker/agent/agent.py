"""
Agent Module - Backwards Compatibility Layer

⚠️ DEPRECATION NOTICE:
This module now acts as a backwards compatibility layer for the new orchestrator pattern.
The monolithic agent has been replaced with a specialized orchestrator that routes
requests to platform-specific agents.

For new code, import directly from orchestrator:
    from viraltracker.agent.orchestrator import orchestrator

For backwards compatibility, this module re-exports the orchestrator as 'agent':
    from viraltracker.agent.agent import agent  # Still works!

Architecture:
    User Request → agent (orchestrator) → Specialized Agents → Tools

The orchestrator routes requests to 5 specialized agents:
- Twitter Agent: 8 tools (search, top tweets, export, comments, analysis, content gen, verify)
- TikTok Agent: 5 tools (search, hashtag, user scrape, video analysis, batch analysis)
- YouTube Agent: 1 tool (search)
- Facebook Agent: 2 tools (ad search, page ads scrape)
- Analysis Agent: 3 tools (outliers, hooks, export results)

See also:
- viraltracker/agent/orchestrator.py - Main orchestrator implementation
- viraltracker/agent/agents/ - Specialized agents (twitter, tiktok, youtube, facebook, analysis)
- viraltracker/agent/dependencies.py - Dependency injection
- docs/ORCHESTRATOR_REFACTOR_PLAN.md - Complete refactor documentation
"""

import logging
from .orchestrator import orchestrator
from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# ============================================================================
# Re-export orchestrator as 'agent' for backwards compatibility
# ============================================================================

agent = orchestrator

logger.info("Agent module loaded - using orchestrator pattern with 5 specialized agents")

# ============================================================================
# Export
# ============================================================================

__all__ = ['agent', 'AgentDependencies']
