"""
SEO Pipeline Service Package.

This package provides the SEO content pipeline for multi-tenant,
brand-scoped article creation and publishing.

Main components:
- state.py: SEOPipelineState dataclass
- models.py: Enums and Pydantic models
- orchestrator.py: Graph definition and convenience functions
- nodes/: Thin node wrappers for each pipeline step
- services/: Business logic services

Usage:
    from viraltracker.services.seo_pipeline.state import SEOPipelineState
    from viraltracker.services.seo_pipeline.models import KeywordStatus, ArticleStatus
"""

# Only import state and model classes to avoid circular imports
from .state import SEOPipelineState, SEOHumanCheckpoint
from .models import (
    KeywordStatus,
    ArticleStatus,
    ArticlePhase,
    ProjectStatus,
    SearchIntent,
    LinkType,
    LinkStatus,
    LinkPriority,
    LinkPlacement,
)

__all__ = [
    # State
    "SEOPipelineState",
    "SEOHumanCheckpoint",
    # Enums
    "KeywordStatus",
    "ArticleStatus",
    "ArticlePhase",
    "ProjectStatus",
    "SearchIntent",
    "LinkType",
    "LinkStatus",
    "LinkPriority",
    "LinkPlacement",
]
