"""
Ad Creation Pipeline V2 State - dataclass passed through all pipeline nodes.

Extends V1 state with:
- template_id: scraped_templates.id UUID for template scoring
- pipeline_version: always "v2"
- canvas_sizes: list of canvas sizes for multi-size generation (Phase 2)
- color_modes: list of color modes for multi-color generation (Phase 2)
- prompt_version: tracks Pydantic prompt schema version

Backward compat properties: canvas_size, color_mode return first element.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class AdCreationPipelineState:
    """
    State passed through all V2 ad creation pipeline nodes.

    Lifecycle:
        1. Caller creates with required inputs + configuration
        2. Each node reads what it needs and writes its outputs
        3. Final node returns compiled results via End()
    """

    # === REQUIRED INPUT ===
    product_id: str
    reference_ad_base64: str

    # === V2-SPECIFIC CONFIGURATION ===
    template_id: Optional[str] = None        # scraped_templates.id UUID
    pipeline_version: str = "v2"
    canvas_sizes: List[str] = field(default_factory=lambda: ["1080x1080px"])
    prompt_version: str = "v2.1.0"

    # === CONFIGURATION (set at creation, not changed by nodes) ===
    reference_ad_filename: str = "reference.png"
    num_variations: int = 5
    content_source: str = "hooks"  # hooks, recreate_template, belief_first, plan, angles
    color_modes: List[str] = field(default_factory=lambda: ["original"])
    brand_colors: Optional[Dict[str, Any]] = None
    brand_fonts: Optional[Dict[str, Any]] = None
    image_selection_mode: str = "auto"  # auto, manual
    selected_image_paths: Optional[List[str]] = None
    persona_id: Optional[str] = None
    variant_id: Optional[str] = None
    offer_variant_id: Optional[str] = None
    current_offer_override: Optional[str] = None
    additional_instructions: Optional[str] = None
    angle_data: Optional[Dict[str, Any]] = None
    match_template_structure: bool = False
    image_resolution: str = "2K"  # "1K", "2K", or "4K" — passed to Gemini generate_image()
    project_id: Optional[str] = None
    auto_retry_rejected: bool = False
    max_retry_attempts: int = 1  # per rejected ad

    # === POPULATED BY NODES ===

    # InitializeNode
    ad_run_id: Optional[str] = None
    reference_ad_path: Optional[str] = None

    # FetchContextNode
    product_dict: Optional[Dict[str, Any]] = None
    persona_data: Optional[Dict[str, Any]] = None
    hooks_list: List[Dict[str, Any]] = field(default_factory=list)
    ad_brief_instructions: str = ""

    # FetchContextNode (Phase 3 — asset-aware prompts)
    template_elements: Optional[Dict[str, Any]] = None     # None = no detection ran, {} = detection ran but empty
    asset_match_result: Optional[Dict[str, Any]] = None     # informational match against all images
    brand_asset_info: Optional[Dict[str, Any]] = None       # logo/badge detection from brand_assets

    # FetchContextNode (Phase 4 — congruence)
    lp_hero_data: Optional[Dict[str, Any]] = None           # LP hero headline/subheadline from brand_landing_pages

    # FetchContextNode (Phase 6 — Creative Genome)
    performance_context: Optional[Dict[str, Any]] = None    # Advisory performance context from genome

    # AnalyzeTemplateNode
    ad_analysis: Optional[Dict[str, Any]] = None

    # SelectContentNode
    template_angle: Optional[Dict[str, Any]] = None  # recreate_template / belief_first w/ match
    selected_hooks: List[Dict[str, Any]] = field(default_factory=list)

    # HeadlineCongruenceNode (Phase 4)
    congruence_results: List[Dict[str, Any]] = field(default_factory=list)

    # SelectImagesNode
    selected_images: List[Dict[str, Any]] = field(default_factory=list)

    # GenerateAdsNode
    generated_ads: List[Dict[str, Any]] = field(default_factory=list)

    # DefectScanNode (Phase 4)
    defect_passed_ads: List[Dict[str, Any]] = field(default_factory=list)
    defect_scan_results: List[Dict[str, Any]] = field(default_factory=list)

    # ReviewAdsNode
    reviewed_ads: List[Dict[str, Any]] = field(default_factory=list)

    # === PHASE 8B: Selection-time scorer data (set by scheduler/UI, used by CompileResultsNode) ===
    selection_weights_used: Optional[Dict[str, float]] = None
    selection_scorer_breakdown: Optional[Dict[str, float]] = None
    selection_composite_score: Optional[float] = None
    selection_mode: Optional[str] = None  # 'smart_select' or 'roll_the_dice'

    # === PHASE 8B: Generation experiment assignment (set pre-graph in orchestrator) ===
    experiment_seed: Optional[str] = None
    generation_experiment_id: Optional[str] = None
    generation_experiment_arm: Optional[str] = None  # 'control' or 'variant'
    generation_experiment_config: Optional[Dict[str, Any]] = None

    # === TRACKING ===
    current_step: str = "pending"
    ads_generated: int = 0
    ads_reviewed: int = 0
    error: Optional[str] = None
    error_step: Optional[str] = None

    @property
    def canvas_size(self) -> str:
        """First canvas size (backward compat for nodes that need a single value)."""
        return self.canvas_sizes[0] if self.canvas_sizes else "1080x1080px"

    @property
    def color_mode(self) -> str:
        """First color mode (backward compat for nodes that need a single value)."""
        return self.color_modes[0] if self.color_modes else "original"

    def mark_step_complete(self, step_name: str) -> None:
        """Mark a step as complete and update current_step."""
        self.current_step = f"{step_name}_complete"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for persistence."""
        import dataclasses
        result = {}
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            result[f.name] = val
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdCreationPipelineState":
        """Deserialize state from persistence."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)
