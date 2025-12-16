"""
Services layer for Viraltracker agent platform.

Provides clean separation between data access (TwitterService),
AI operations (GeminiService), and business logic (agent tools).
"""

from .models import (
    Tweet,
    HookAnalysis,
    OutlierTweet,
    CommentCandidate,
    OutlierResult,
    HookAnalysisResult,
    # Belief-First Planning Models
    BeliefOffer,
    BeliefSubLayer,
    BeliefJTBDFramed,
    BeliefAngle,
    BeliefPlan,
    BeliefPlanRun,
    CompiledPlanPayload,
    # Copy Scaffolds & Template Evaluation Models
    CopyScaffold,
    AngleCopySet,
    TemplateEvaluation,
)

from .planning_service import PlanningService
from .template_evaluation_service import TemplateEvaluationService
from .copy_scaffold_service import CopyScaffoldService

__all__ = [
    "Tweet",
    "HookAnalysis",
    "OutlierTweet",
    "CommentCandidate",
    "OutlierResult",
    "HookAnalysisResult",
    # Belief-First Planning
    "PlanningService",
    "BeliefOffer",
    "BeliefSubLayer",
    "BeliefJTBDFramed",
    "BeliefAngle",
    "BeliefPlan",
    "BeliefPlanRun",
    "CompiledPlanPayload",
    # Copy Scaffolds & Template Evaluation
    "TemplateEvaluationService",
    "CopyScaffoldService",
    "CopyScaffold",
    "AngleCopySet",
    "TemplateEvaluation",
]
