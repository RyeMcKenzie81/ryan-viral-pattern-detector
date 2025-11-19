"""
Agent layer for Viraltracker platform.

Provides Pydantic AI agent with typed dependencies and tools for:
- Finding viral outlier tweets
- Analyzing tweet hooks
- Exporting analysis results
"""

from .agent import agent
from .dependencies import AgentDependencies
from .tools import (
    find_outliers_tool,
    analyze_hooks_tool,
    export_results_tool
)

__all__ = [
    "agent",
    "AgentDependencies",
    "find_outliers_tool",
    "analyze_hooks_tool",
    "export_results_tool",
]
