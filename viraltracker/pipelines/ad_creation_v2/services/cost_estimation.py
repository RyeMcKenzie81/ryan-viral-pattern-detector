"""
Cost estimation for V2 ad creation runs.

Provides configurable per-unit pricing and run cost estimation.
Used by UI to show cost estimates and enforce batch guardrails.
"""

from typing import Dict, Optional

# Configurable pricing constants (USD per unit)
PRICING_DEFAULTS: Dict[str, float] = {
    "gemini_image_gen_per_ad": 0.04,
    "claude_vision_review_per_ad": 0.02,
    "gemini_vision_review_per_ad": 0.01,
    "defect_scan_per_ad": 0.01,
    "congruence_check_per_hook": 0.015,
    "template_analysis_per_run": 0.03,
    "stage3_trigger_rate": 0.4,
    "retry_rate": 0.3,
}

# Backend hard cap
MAX_VARIATIONS_PER_RUN = 50


def estimate_run_cost(
    num_variations: int,
    num_canvas_sizes: int = 1,
    num_color_modes: int = 1,
    auto_retry: bool = False,
    pricing: Optional[Dict[str, float]] = None,
) -> Dict:
    """Estimate cost for a V2 ad creation run.

    Args:
        num_variations: Number of hook variations.
        num_canvas_sizes: Number of canvas sizes per variation.
        num_color_modes: Number of color modes per variation.
        auto_retry: Whether auto-retry is enabled.
        pricing: Optional pricing overrides. Keys from PRICING_DEFAULTS.

    Returns:
        Dict with:
            total_ads: int - total ads that will be generated
            per_ad_cost: float - estimated cost per ad (USD)
            total_cost: float - total estimated cost (USD)
            breakdown: dict - per-component cost breakdown
    """
    p = {**PRICING_DEFAULTS, **(pricing or {})}

    total_ads = num_variations * num_canvas_sizes * num_color_modes

    # Per-ad costs
    generation_cost = p["gemini_image_gen_per_ad"]
    defect_cost = p["defect_scan_per_ad"]
    stage2_cost = p["claude_vision_review_per_ad"]
    stage3_cost = p["gemini_vision_review_per_ad"] * p["stage3_trigger_rate"]
    congruence_cost = p["congruence_check_per_hook"] / max(num_canvas_sizes * num_color_modes, 1)

    per_ad_cost = generation_cost + defect_cost + stage2_cost + stage3_cost + congruence_cost

    # Retry adds fractional cost
    retry_multiplier = 1.0
    if auto_retry:
        retry_multiplier = 1.0 + p["retry_rate"]

    # Fixed per-run costs
    fixed_cost = p["template_analysis_per_run"]

    total_cost = (total_ads * per_ad_cost * retry_multiplier) + fixed_cost

    return {
        "total_ads": total_ads,
        "per_ad_cost": round(per_ad_cost, 4),
        "total_cost": round(total_cost, 2),
        "retry_multiplier": round(retry_multiplier, 2),
        "breakdown": {
            "generation": round(generation_cost * total_ads * retry_multiplier, 2),
            "defect_scan": round(defect_cost * total_ads * retry_multiplier, 2),
            "stage2_review": round(stage2_cost * total_ads * retry_multiplier, 2),
            "stage3_review": round(stage3_cost * total_ads * retry_multiplier, 2),
            "congruence": round(congruence_cost * total_ads, 2),
            "template_analysis": round(fixed_cost, 2),
        },
    }
