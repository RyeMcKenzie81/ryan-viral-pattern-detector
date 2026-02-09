"""
Pydantic output models for the landing page analysis pipeline.

These define the expected JSON structure from each skill's LLM call.
Currently used as reference schemas only — the service stores raw dicts
from LLM JSON output. These models document the contract and can be
wired up for validation (via model_validate) when prompt output is stable.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Skill 1: Page Classifier
# ---------------------------------------------------------------------------

class AwarenessLevel(BaseModel):
    primary: str = Field(description="unaware | problem_aware | solution_aware | product_aware | most_aware")
    confidence: str = Field(default="medium", description="high | medium | low")
    evidence: List[str] = Field(default_factory=list, description="Specific observations from the page")
    notes: str = Field(default="", description="Classification reasoning")


class MarketSophistication(BaseModel):
    level: int = Field(ge=1, le=5, description="Market sophistication level 1-5")
    confidence: str = Field(default="medium", description="high | medium | low")
    evidence: List[str] = Field(default_factory=list)
    notes: str = Field(default="")


class PageArchitecture(BaseModel):
    type: str = Field(description="long_form_sales_letter | ecomm_dr_hybrid | short_form_product_page | vsl_order_form | squeeze_page | other")
    estimated_word_count: str = Field(default="medium", description="short (<1000) | medium (1000-3000) | long (3000+)")
    has_navigation: bool = Field(default=True)
    notes: str = Field(default="")


class TargetDemographic(BaseModel):
    age_range: str = Field(default="", description="e.g. '35-55'")
    gender_skew: str = Field(default="neutral", description="male | female | neutral")
    income_level: str = Field(default="middle", description="budget | middle | upper_middle | premium")
    health_consciousness: str = Field(default="moderate", description="low | moderate | high")
    tech_savviness: str = Field(default="moderate", description="low | moderate | high")
    location: str = Field(default="United States")
    evidence: List[str] = Field(default_factory=list)


class BuyerPersona(BaseModel):
    persona_name: str = Field(default="", description="Alliterative memorable name")
    core_identity: str = Field(default="")
    key_pain_points: List[str] = Field(default_factory=list)
    key_desires: List[str] = Field(default_factory=list)
    purchase_hesitations: List[str] = Field(default_factory=list)
    values: List[str] = Field(default_factory=list)


class PageClassification(BaseModel):
    """Skill 1 output: full page classification."""
    url_or_source: str = Field(default="")
    product_name: str = Field(default="")
    product_category: str = Field(default="other")
    awareness_level: AwarenessLevel
    market_sophistication: MarketSophistication
    page_architecture: PageArchitecture
    target_demographic: TargetDemographic
    buyer_persona: BuyerPersona


# ---------------------------------------------------------------------------
# Skill 2: Element Detector
# ---------------------------------------------------------------------------

class DetectedElement(BaseModel):
    element_name: str
    element_type: str = Field(description="Classification subtype")
    present: bool = True
    content_summary: str = Field(default="")
    quality_notes: str = Field(default="")
    position: str = Field(default="")


class CTAItem(BaseModel):
    position: str = Field(default="")
    button_text: str = Field(default="")
    type: str = Field(default="action_driven")
    has_click_trigger: bool = False
    click_trigger_text: Optional[str] = None


class SocialProofItem(BaseModel):
    type: str = Field(default="text_testimonial")
    position: str = Field(default="")
    content_summary: str = Field(default="")


class ElementSection(BaseModel):
    elements_found: List[DetectedElement] = Field(default_factory=list)


class ElementDetection(BaseModel):
    """Skill 2 output: detected elements."""
    url_or_source: str = Field(default="")
    total_elements_detected: int = Field(default=0)
    page_flow_order: List[str] = Field(default_factory=list)
    sections: Dict[str, ElementSection] = Field(default_factory=dict)
    element_count_by_section: Dict[str, int] = Field(default_factory=dict)
    cta_inventory: List[CTAItem] = Field(default_factory=list)
    social_proof_inventory: List[SocialProofItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Skill 3: Gap Analyzer
# ---------------------------------------------------------------------------

class GapItem(BaseModel):
    element_name: str
    why_missing_matters: str = Field(default="")
    estimated_impact: str = Field(default="medium", description="high | medium | low")
    recommendation: str = Field(default="")
    priority: int = Field(default=1)


class MisplacedElement(BaseModel):
    element_name: str
    current_position: str = Field(default="")
    recommended_position: str = Field(default="")
    why_it_matters: str = Field(default="")


class FlowIssue(BaseModel):
    issue: str
    description: str = Field(default="")
    recommendation: str = Field(default="")


class QuickWin(BaseModel):
    action: str
    estimated_effort: str = Field(default="low", description="low | medium | high")
    estimated_impact: str = Field(default="high", description="high | medium | low")
    details: str = Field(default="")


class OptimizationRoadmap(BaseModel):
    immediate: List[str] = Field(default_factory=list)
    short_term: List[str] = Field(default_factory=list)
    long_term: List[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    """Skill 3 output: gap analysis."""
    url_or_source: str = Field(default="")
    awareness_level: str = Field(default="")
    architecture_type: str = Field(default="")
    overall_completeness_score: int = Field(default=0, ge=0, le=100)
    overall_risk_level: str = Field(default="moderate", description="critical | moderate | low")
    critical_gaps: List[GapItem] = Field(default_factory=list)
    moderate_gaps: List[GapItem] = Field(default_factory=list)
    minor_gaps: List[GapItem] = Field(default_factory=list)
    misplaced_elements: List[MisplacedElement] = Field(default_factory=list)
    flow_issues: List[FlowIssue] = Field(default_factory=list)
    quick_wins: List[QuickWin] = Field(default_factory=list)
    optimization_roadmap: OptimizationRoadmap = Field(default_factory=OptimizationRoadmap)


# ---------------------------------------------------------------------------
# Skill 4: Copy Scorer
# ---------------------------------------------------------------------------

class ScoringBreakdown(BaseModel):
    clarity: int = Field(default=0, ge=0, le=2)
    benefit_strength: int = Field(default=0, ge=0, le=2)
    emotional_impact: int = Field(default=0, ge=0, le=2)
    specificity: int = Field(default=0, ge=0, le=2)
    audience_alignment: int = Field(default=0, ge=0, le=2)


class ElementScore(BaseModel):
    score: int = Field(default=0, ge=0, le=10)
    current_copy: str = Field(default="")
    classification: str = Field(default="")
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    rewrite_suggestions: List[str] = Field(default_factory=list)
    scoring_breakdown: Dict[str, int] = Field(default_factory=dict)


class ComplianceFlag(BaseModel):
    issue: str
    location: str = Field(default="")
    severity: str = Field(default="note", description="critical | warning | note")
    recommendation: str = Field(default="")


class CopyScore(BaseModel):
    """Skill 4 output: copy quality scores."""
    url_or_source: str = Field(default="")
    overall_score: int = Field(default=0, ge=0, le=100)
    overall_grade: str = Field(default="C")
    strongest_element: str = Field(default="")
    weakest_element: str = Field(default="")
    top_3_rewrite_priorities: List[str] = Field(default_factory=list)
    element_scores: Dict[str, ElementScore] = Field(default_factory=dict)
    compliance_flags: List[ComplianceFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Combined result
# ---------------------------------------------------------------------------

class LandingPageAnalysisResult(BaseModel):
    """Combined result from all 4 skills."""
    analysis_id: Optional[str] = None
    url: str = Field(default="")
    status: str = Field(default="pending")
    classification: Optional[Dict[str, Any]] = None
    elements: Optional[Dict[str, Any]] = None
    gap_analysis: Optional[Dict[str, Any]] = None
    copy_scores: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
