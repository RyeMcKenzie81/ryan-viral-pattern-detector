"""Pydantic models for the Ad Intelligence 4-layer system.

Enums, configs, layer models, and slash command response models.
No database access in this file -- pure type definitions.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class AwarenessLevel(str, Enum):
    UNAWARE = "unaware"
    PROBLEM_AWARE = "problem_aware"
    SOLUTION_AWARE = "solution_aware"
    PRODUCT_AWARE = "product_aware"
    MOST_AWARE = "most_aware"


class CreativeFormat(str, Enum):
    VIDEO_UGC = "video_ugc"
    VIDEO_PROFESSIONAL = "video_professional"
    VIDEO_TESTIMONIAL = "video_testimonial"
    VIDEO_DEMO = "video_demo"
    IMAGE_STATIC = "image_static"
    IMAGE_BEFORE_AFTER = "image_before_after"
    IMAGE_TESTIMONIAL = "image_testimonial"
    IMAGE_PRODUCT = "image_product"
    CAROUSEL = "carousel"
    COLLECTION = "collection"
    OTHER = "other"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"


class RecommendationCategory(str, Enum):
    KILL = "kill"
    SCALE = "scale"
    ITERATE = "iterate"
    TEST = "test"
    REFRESH = "refresh"
    COVERAGE_GAP = "coverage_gap"
    CONGRUENCE_FIX = "congruence_fix"
    BUDGET_REALLOC = "budget_realloc"
    CREATIVE_TEST = "creative_test"


class RecommendationStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    ACTED_ON = "acted_on"
    PARTIALLY_ACTED = "partially_acted"
    IGNORED = "ignored"
    DISMISSED = "dismissed"


# =============================================================================
# Analysis Run Config
# =============================================================================

class RunConfig(BaseModel):
    """Typed config for ad_intelligence_runs.config JSONB."""

    days_back: int = 30
    active_window_days: int = 7
    force_reclassify: bool = False
    primary_conversion_event: str = "purchase"
    value_field: str = "purchase_value"
    kpi: str = "cpa"
    max_classifications_per_run: int = 200
    max_video_classifications_per_run: int = 15
    thresholds: Dict[str, Any] = Field(default_factory=dict)


class AnalysisRun(BaseModel):
    """Represents an ad_intelligence_runs row."""

    id: Optional[UUID] = None
    organization_id: UUID
    brand_id: UUID
    date_range_start: date
    date_range_end: date
    goal: Optional[str] = None
    triggered_by: Optional[UUID] = None
    config: RunConfig = Field(default_factory=RunConfig)
    status: str = "running"
    summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# =============================================================================
# Layer 1: Classification
# =============================================================================

class CreativeClassification(BaseModel):
    """Represents an ad_creative_classifications row."""

    id: Optional[UUID] = None
    meta_ad_id: str
    brand_id: UUID
    organization_id: Optional[UUID] = None
    run_id: Optional[UUID] = None

    # Creative classification
    creative_awareness_level: Optional[AwarenessLevel] = None
    creative_awareness_confidence: Optional[float] = Field(None, ge=0, le=1)
    creative_format: Optional[CreativeFormat] = None
    creative_angle: Optional[str] = None
    video_length_bucket: Optional[str] = None
    video_duration_sec: Optional[int] = None

    # Copy classification
    copy_awareness_level: Optional[AwarenessLevel] = None
    copy_awareness_confidence: Optional[float] = Field(None, ge=0, le=1)
    hook_type: Optional[str] = None
    primary_cta: Optional[str] = None

    # Landing page classification
    landing_page_awareness_level: Optional[AwarenessLevel] = None
    landing_page_confidence: Optional[float] = Field(None, ge=0, le=1)
    landing_page_id: Optional[UUID] = None

    # Congruence
    congruence_score: Optional[float] = Field(None, ge=0, le=1)
    congruence_notes: Optional[str] = None
    # Per-dimension congruence: [{dimension, assessment, explanation, suggestion}]
    congruence_components: List[Dict[str, Any]] = Field(default_factory=list)

    # Deep video analysis link
    video_analysis_id: Optional[UUID] = None

    # Versioning & provenance
    source: str = "gemini_light"
    prompt_version: str = "v1"
    schema_version: str = "1.0"
    input_hash: Optional[str] = None
    model_used: Optional[str] = None
    raw_classification: Dict[str, Any] = Field(default_factory=dict)

    # Staleness
    classified_at: Optional[datetime] = None
    stale_after: Optional[datetime] = None


# =============================================================================
# Layer 2: Baselines
# =============================================================================

class BaselineSnapshot(BaseModel):
    """Represents an ad_intelligence_baselines row."""

    id: Optional[UUID] = None
    brand_id: UUID
    organization_id: Optional[UUID] = None
    run_id: Optional[UUID] = None

    # Cohort definition
    awareness_level: str = "all"
    creative_format: str = "all"
    video_length_bucket: str = "all"
    campaign_objective: str = "all"

    # Sample info
    sample_size: int
    unique_ads: int

    # Performance baselines (p25 / median / p75)
    median_ctr: Optional[float] = None
    p25_ctr: Optional[float] = None
    p75_ctr: Optional[float] = None

    median_cpc: Optional[float] = None
    p25_cpc: Optional[float] = None
    p75_cpc: Optional[float] = None

    median_cpm: Optional[float] = None
    p25_cpm: Optional[float] = None
    p75_cpm: Optional[float] = None

    median_roas: Optional[float] = None
    p25_roas: Optional[float] = None
    p75_roas: Optional[float] = None

    median_conversion_rate: Optional[float] = None
    p25_conversion_rate: Optional[float] = None
    p75_conversion_rate: Optional[float] = None

    median_cost_per_purchase: Optional[float] = None
    median_cost_per_add_to_cart: Optional[float] = None

    # Video-specific
    median_hook_rate: Optional[float] = None
    median_hold_rate: Optional[float] = None
    median_completion_rate: Optional[float] = None

    # Frequency
    median_frequency: Optional[float] = None
    p75_frequency: Optional[float] = None

    # Date range
    date_range_start: date
    date_range_end: date
    computed_at: Optional[datetime] = None

    @property
    def is_sufficient(self) -> bool:
        """Whether this baseline has enough data to be meaningful."""
        return self.unique_ads >= 5 and self.sample_size >= 30


# =============================================================================
# Layer 3: Diagnostics
# =============================================================================

class FiredRule(BaseModel):
    """A single diagnostic rule evaluation result (fired or skipped)."""

    rule_id: str
    rule_name: str
    category: str  # efficiency | fatigue | creative | funnel | frequency
    severity: str  # info | warning | critical
    confidence: float = Field(ge=0, le=1)
    metric_name: str
    actual_value: Optional[float] = None
    baseline_value: Optional[float] = None
    explanation: str
    days_in_state: Optional[int] = None

    # Rule evaluation context
    aggregation: str = "total"  # "total" | "daily_series"
    window_days: Optional[int] = None  # trailing window used (None = full run)

    # Metric prerequisite tracking
    skipped: bool = False
    missing_metrics: List[str] = Field(default_factory=list)

    # Aggregation context (populated on top_issues summary, not per-ad diagnostics)
    affected_ad_ids: List[str] = Field(default_factory=list)


class AdDiagnostic(BaseModel):
    """Represents an ad_intelligence_diagnostics row."""

    id: Optional[UUID] = None
    meta_ad_id: str
    brand_id: UUID
    organization_id: Optional[UUID] = None
    run_id: UUID
    overall_health: HealthStatus
    kill_recommendation: bool = False
    kill_reason: Optional[str] = None
    fired_rules: List[FiredRule] = Field(default_factory=list)
    trend_direction: Optional[str] = None
    days_analyzed: Optional[int] = None
    baseline_id: Optional[UUID] = None
    classification_id: Optional[UUID] = None
    diagnosed_at: Optional[datetime] = None

    @property
    def critical_count(self) -> int:
        """Number of critical (non-skipped) rules that fired."""
        return sum(1 for r in self.fired_rules if r.severity == "critical" and not r.skipped)

    @property
    def skipped_count(self) -> int:
        """Number of rules that were skipped due to insufficient data."""
        return sum(1 for r in self.fired_rules if r.skipped)


# =============================================================================
# Layer 4: Recommendations
# =============================================================================

class AffectedAd(BaseModel):
    """Structured link between recommendation and affected ad."""

    ad_id: str
    ad_name: Optional[str] = None
    reason: Optional[str] = None


class EvidencePoint(BaseModel):
    """A single piece of evidence supporting a recommendation."""

    metric: str
    observation: str
    data: Dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    """Represents an ad_intelligence_recommendations row."""

    id: Optional[UUID] = None
    brand_id: UUID
    organization_id: Optional[UUID] = None
    run_id: UUID
    title: str
    category: RecommendationCategory
    priority: str  # critical | high | medium | low
    confidence: float = Field(ge=0, le=1)
    summary: str
    evidence: List[EvidencePoint] = Field(default_factory=list)
    affected_ads: List[AffectedAd] = Field(default_factory=list)
    affected_ad_ids: List[str] = Field(default_factory=list)
    affected_campaign_ids: List[str] = Field(default_factory=list)
    action_description: str
    action_type: str  # pause_ad | increase_budget | ... | no_action
    status: RecommendationStatus = RecommendationStatus.PENDING
    user_note: Optional[str] = None
    acted_at: Optional[datetime] = None
    acted_by: Optional[UUID] = None
    diagnostic_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


# =============================================================================
# Slash Command Response Models
# =============================================================================

class AccountAnalysisResult(BaseModel):
    """Response model for /analyze_account."""

    run_id: UUID
    brand_name: str
    date_range: str
    total_ads: int
    active_ads: int
    total_spend: float
    awareness_distribution: Dict[str, int] = Field(default_factory=dict)
    format_distribution: Dict[str, int] = Field(default_factory=dict)
    health_distribution: Dict[str, int] = Field(default_factory=dict)
    healthy_ad_ids: List[str] = Field(default_factory=list)
    top_issues: List[FiredRule] = Field(default_factory=list)
    pending_recommendations: int = 0
    critical_recommendations: int = 0
    recommendations: List[Recommendation] = Field(default_factory=list)

    # Baseline metrics by awareness level: {level: {cpm, ctr, cpa, cost_per_atc}}
    awareness_baselines: Dict[str, Dict[str, Optional[float]]] = Field(default_factory=dict)
    # Aggregate metrics by awareness level: {level: {spend, purchases, clicks, conversion_rate, cpa}}
    awareness_aggregates: Dict[str, Dict[str, Optional[float]]] = Field(default_factory=dict)
    # Format breakdown: {"awareness|format": {spend, purchases, clicks, cpa}}
    format_aggregates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Auto-generated creative strategy insights
    creative_insights: List[str] = Field(default_factory=list)


class FatigueCheckResult(BaseModel):
    """Response model for /fatigue_check."""

    brand_name: str
    fatigued_ads: List[Dict[str, Any]] = Field(default_factory=list)
    at_risk_ads: List[Dict[str, Any]] = Field(default_factory=list)
    healthy_ads_count: int = 0
    summary: str = ""


class CoverageGapResult(BaseModel):
    """Response model for /coverage_gaps."""

    brand_name: str
    coverage_matrix: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    gaps: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class CongruenceCheckResult(BaseModel):
    """Response model for /congruence_check."""

    brand_name: str
    checked_ads: int = 0
    misaligned_ads: List[Dict[str, Any]] = Field(default_factory=list)
    deep_analysis_ads: List[Dict[str, Any]] = Field(default_factory=list)
    average_congruence: float = 0.0
