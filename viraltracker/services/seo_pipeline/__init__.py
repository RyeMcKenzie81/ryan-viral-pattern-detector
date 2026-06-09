"""
SEO Pipeline Service Package.

This package provides the SEO content pipeline for multi-tenant,
brand-scoped article creation and publishing.

Main components:
- state.py: SEOPipelineState dataclass
- models.py: Enums and Pydantic models
- services/: Business logic services

Execution model (hardening plan §11 R1): production runs through the
imperative SEOWorkflowService (services/seo_workflow_service.py). The
pydantic-graph orchestrator + nodes/ were dead code (zero callers) and were
deleted 2026-06-09; the durable worker-driven execution design lives in
docs/plans/seo-pipeline-hardening/DURABLE_JOBS_CONTRACT.md and is built at
the API-foundation roadmap phase.

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
