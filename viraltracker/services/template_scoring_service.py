"""
Template Scoring Service — Pluggable scoring pipeline for V2 template selection.

Provides weighted-random template selection using pluggable scorers.
Phase 3 includes: AssetMatchScorer, UnusedBonusScorer, CategoryMatchScorer,
AwarenessAlignScorer, AudienceMatchScorer.

Usage:
    from viraltracker.services.template_scoring_service import (
        select_templates_with_fallback, fetch_template_candidates,
        prefetch_product_asset_tags, SelectionContext,
        ROLL_THE_DICE_WEIGHTS, SMART_SELECT_WEIGHTS,
    )

    # Prefetch asset tags once (N+1 prevention)
    asset_tags = await prefetch_product_asset_tags(product_id)

    context = SelectionContext(
        product_id=product_id,
        brand_id=brand_id,
        product_asset_tags=asset_tags,
    )

    # Fetch candidates once
    candidates = await fetch_template_candidates(product_id, category="Testimonial")

    # Select with fallback
    result = select_templates_with_fallback(
        candidates=candidates,
        context=context,
        weights=ROLL_THE_DICE_WEIGHTS,
        count=3,
    )
"""

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


# ============================================================================
# Weight Presets
# ============================================================================

ROLL_THE_DICE_WEIGHTS: Dict[str, float] = {
    "asset_match": 0.0,
    "unused_bonus": 1.0,
    "category_match": 0.5,
    "awareness_align": 0.0,
    "audience_match": 0.0,
}

SMART_SELECT_WEIGHTS: Dict[str, float] = {
    "asset_match": 1.0,
    "unused_bonus": 0.8,
    "category_match": 0.6,
    "awareness_align": 0.5,
    "audience_match": 0.4,
}


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SelectionContext:
    """Context passed to all scorers during template selection.

    All state lives here or in the candidate row dict — scorers are stateless.

    Attributes:
        product_id: Product UUID for this selection.
        brand_id: Brand UUID for this selection.
        product_asset_tags: Set of asset tag strings prefetched from
            product_images.asset_tags for this product. Used by AssetMatchScorer
            for inline set intersection (no per-template DB calls).
        requested_category: If provided, CategoryMatchScorer uses exact match.
            If None, all categories score 0.5.
        awareness_stage: Persona awareness level (1-5). If None,
            AwarenessAlignScorer returns 0.5 (neutral).
        target_sex: Target audience sex ("male", "female", "unisex", None).
            If None, AudienceMatchScorer returns 0.7 (neutral).
        has_meta_connection: Whether the brand has a Meta connection.
    """
    product_id: UUID
    brand_id: UUID
    product_asset_tags: Set[str] = field(default_factory=set)
    requested_category: Optional[str] = None
    awareness_stage: Optional[int] = None
    target_sex: Optional[str] = None
    has_meta_connection: bool = False


@dataclass
class SelectionResult:
    """Structured result from template selection.

    Always structured — never a raw list. Check `empty` to determine
    if any templates were selected.

    Attributes:
        templates: Selected template dicts (may be empty).
        scores: Per-template scorer breakdown, parallel to templates.
        empty: True if no templates were selected.
        reason: Non-None only when empty=True, explains why.
        candidates_before_gate: Total candidates from query.
        candidates_after_gate: Candidates surviving asset gate.
    """
    templates: List[dict] = field(default_factory=list)
    scores: List[Dict[str, float]] = field(default_factory=list)
    empty: bool = True
    reason: Optional[str] = None
    candidates_before_gate: int = 0
    candidates_after_gate: int = 0


# ============================================================================
# Scorer Interface + Phase 1 Scorers
# ============================================================================

class TemplateScorer(ABC):
    """Base class for template scorers.

    Each scorer implements one method: score(template, context) -> float [0.0, 1.0].
    Scorers are stateless — all state lives in the DB or in SelectionContext.
    """
    name: str

    @abstractmethod
    def score(self, template: dict, context: SelectionContext) -> float:
        """Score a template candidate.

        Args:
            template: Template row dict from fetch_template_candidates().
            context: Selection context with product info and prefetched data.

        Returns:
            Float score in [0.0, 1.0].
        """
        ...


class AssetMatchScorer(TemplateScorer):
    """Score based on product asset coverage of template requirements.

    Computes set intersection between template's required_assets and
    product's asset_tags. Returns 1.0 if template has no requirements.

    Also doubles as a gate when min_asset_score > 0 (handled by select_templates).
    """
    name = "asset_match"

    def score(self, template: dict, context: SelectionContext) -> float:
        template_elements = template.get("template_elements") or {}
        required_assets = template_elements.get("required_assets", [])

        if not required_assets:
            return 1.0

        required_set = set(required_assets)
        matched = required_set & context.product_asset_tags
        return len(matched) / len(required_set)


class UnusedBonusScorer(TemplateScorer):
    """Score based on whether template has been used for this product.

    Returns 1.0 if unused, 0.3 if previously used.
    """
    name = "unused_bonus"

    def score(self, template: dict, context: SelectionContext) -> float:
        return 1.0 if template.get("is_unused", True) else 0.3


class CategoryMatchScorer(TemplateScorer):
    """Score based on template category matching the requested category.

    Returns 1.0 for exact match, 0.5 if no category requested (All/None),
    0.0 for mismatch.
    """
    name = "category_match"

    def score(self, template: dict, context: SelectionContext) -> float:
        if context.requested_category is None:
            return 0.5

        template_category = template.get("category", "")
        if template_category == context.requested_category:
            return 1.0
        return 0.0


class AwarenessAlignScorer(TemplateScorer):
    """Score based on alignment between template and persona awareness level.

    Input: template["awareness_level"] (INT 1-5, nullable) vs context.awareness_stage (INT 1-5, nullable).
    Logic: 1.0 - abs(template_level - persona_level) / 4.0.
    If either is None → 0.5 (neutral).
    """
    name = "awareness_align"

    def score(self, template: dict, context: SelectionContext) -> float:
        template_level = template.get("awareness_level")
        persona_level = context.awareness_stage

        if template_level is None or persona_level is None:
            return 0.5

        return 1.0 - abs(template_level - persona_level) / 4.0


class AudienceMatchScorer(TemplateScorer):
    """Score based on template target_sex matching context target_sex.

    Exact match → 1.0, either unisex/None → 0.7, mismatch → 0.2.
    """
    name = "audience_match"

    def score(self, template: dict, context: SelectionContext) -> float:
        template_sex = template.get("target_sex")
        context_sex = context.target_sex

        if template_sex is None or context_sex is None:
            return 0.7

        if template_sex == context_sex:
            return 1.0

        if template_sex == "unisex" or context_sex == "unisex":
            return 0.7

        return 0.2


# Phase 1 scorer instances (kept for backward compat)
PHASE_1_SCORERS: List[TemplateScorer] = [
    AssetMatchScorer(),
    UnusedBonusScorer(),
    CategoryMatchScorer(),
]

# Phase 3 scorer instances (default for select_templates_with_fallback)
PHASE_3_SCORERS: List[TemplateScorer] = [
    AssetMatchScorer(),
    UnusedBonusScorer(),
    CategoryMatchScorer(),
    AwarenessAlignScorer(),
    AudienceMatchScorer(),
]


# ============================================================================
# Selection Function
# ============================================================================

def select_templates(
    candidates: List[dict],
    context: SelectionContext,
    scorers: List[TemplateScorer],
    weights: Dict[str, float],
    min_asset_score: float = 0.0,
    count: int = 3,
) -> SelectionResult:
    """Weighted-random selection from scored candidates.

    Algorithm:
        0. Validate weights (runtime check)
        1. Score each candidate with all active scorers
        2. Gate: if min_asset_score > 0, drop candidates with asset_match < threshold
           AND candidates with has_detection = false
        3. Compute composite score per candidate
        4. Normalize to probability distribution
        5. Draw without replacement using numpy.random.choice

    Args:
        candidates: Template row dicts from fetch_template_candidates().
        context: Selection context with product info.
        scorers: List of TemplateScorer instances to apply.
        weights: Dict mapping scorer.name to weight (>= 0, finite).
        min_asset_score: Gate threshold. 0.0 = no gate.
        count: Number of templates to select.

    Returns:
        SelectionResult with selected templates and score breakdowns.
    """
    candidates_before_gate = len(candidates)

    if not candidates:
        return SelectionResult(
            empty=True,
            reason="No candidates provided",
            candidates_before_gate=0,
            candidates_after_gate=0,
        )

    # Step 0: Validate weights
    for name, w in weights.items():
        if not (isinstance(w, (int, float)) and math.isfinite(w) and w >= 0):
            raise ValueError(f"Invalid weight for {name}: {w} (must be finite and >= 0)")

    # Step 1: Score each candidate with all scorers
    all_scores: List[Dict[str, float]] = []
    for candidate in candidates:
        candidate_scores = {}
        for scorer in scorers:
            candidate_scores[scorer.name] = scorer.score(candidate, context)
        all_scores.append(candidate_scores)

    # Step 2: Asset gate
    if min_asset_score > 0:
        gated_candidates = []
        gated_scores = []
        for candidate, scores in zip(candidates, all_scores):
            has_detection = candidate.get("has_detection", False)
            asset_score = scores.get("asset_match", 1.0)

            # Drop if no detection data (gate requires detection to be meaningful)
            if not has_detection:
                continue
            # Drop if below threshold
            if asset_score < min_asset_score:
                continue

            gated_candidates.append(candidate)
            gated_scores.append(scores)

        candidates = gated_candidates
        all_scores = gated_scores

    candidates_after_gate = len(candidates)

    # Step 3: Edge cases after gating
    if candidates_after_gate == 0:
        return SelectionResult(
            empty=True,
            reason=f"No templates passed asset gate (min_score={min_asset_score}, "
                   f"0/{candidates_before_gate} passed)",
            candidates_before_gate=candidates_before_gate,
            candidates_after_gate=0,
        )

    if count > candidates_after_gate:
        logger.warning(
            f"Requested {count} templates but only {candidates_after_gate} available. "
            f"Clamping to {candidates_after_gate}."
        )
        count = candidates_after_gate

    # Step 4: Compute composite scores
    w_total = sum(weights.get(s.name, 0.0) for s in scorers)
    composites = []
    for scores in all_scores:
        if w_total == 0:
            composites.append(1.0)
        else:
            composite = sum(weights.get(s.name, 0.0) * scores.get(s.name, 0.0) for s in scorers)
            composites.append(composite / w_total)

    # Step 5: Normalize to probability distribution
    score_total = sum(composites)
    if score_total == 0:
        p = [1.0 / len(composites)] * len(composites)
    else:
        p = [c / score_total for c in composites]

    # Step 6: Clamp draw count to nonzero-probability candidates
    nonzero_count = sum(1 for x in p if x > 0)
    draw_count = min(count, len(candidates), nonzero_count)
    if draw_count < count:
        logger.warning(f"Only {draw_count} candidates with nonzero score (requested {count})")

    # Step 7: Draw without replacement
    indices = np.random.choice(
        len(candidates),
        size=draw_count,
        replace=False,
        p=np.array(p),
    )

    selected_templates = [candidates[i] for i in indices]
    selected_scores = [all_scores[i] for i in indices]

    # Add composite score to each score dict
    for i, idx in enumerate(indices):
        selected_scores[i]["composite"] = composites[idx]

    return SelectionResult(
        templates=selected_templates,
        scores=selected_scores,
        empty=False,
        candidates_before_gate=candidates_before_gate,
        candidates_after_gate=candidates_after_gate,
    )


# ============================================================================
# Database Helpers
# ============================================================================

async def fetch_template_candidates(
    product_id: str,
    category: Optional[str] = None,
) -> List[dict]:
    """Fetch template candidates with usage data merged in Python.

    Runs two queries:
    1. scraped_templates WHERE is_active = TRUE (+ optional category filter)
    2. product_template_usage WHERE product_id = :product_id

    Merges in Python, adding:
    - is_unused: bool (template_id not found in usage)
    - has_detection: bool (element_detection_version IS NOT NULL)

    Args:
        product_id: Product UUID string.
        category: Optional category filter. None = all categories.

    Returns:
        List of template row dicts with is_unused and has_detection added.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    # Query 1: All active templates
    query = db.table("scraped_templates").select("*").eq("is_active", True)
    if category:
        query = query.eq("category", category)
    query = query.order("id")

    templates_result = query.execute()
    templates = templates_result.data or []

    if not templates:
        return []

    # Query 2: Usage for this product
    usage_result = db.table("product_template_usage").select(
        "template_id"
    ).eq("product_id", product_id).execute()

    used_template_ids = {
        r["template_id"] for r in (usage_result.data or []) if r.get("template_id")
    }

    # Merge: add is_unused and has_detection to each template
    for template in templates:
        template["is_unused"] = template["id"] not in used_template_ids
        template["has_detection"] = template.get("element_detection_version") is not None

    return templates


async def prefetch_product_asset_tags(product_id: str) -> Set[str]:
    """Prefetch asset tags for a product's images.

    Single query to product_images, returns union of all asset_tags.
    Called once before the scoring loop (N+1 prevention).

    Args:
        product_id: Product UUID string.

    Returns:
        Set of asset tag strings (e.g., {"person:vet", "product:bottle", "logo"}).
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    result = db.table("product_images").select(
        "asset_tags"
    ).eq("product_id", product_id).execute()

    tags: Set[str] = set()
    for row in (result.data or []):
        row_tags = row.get("asset_tags") or []
        if isinstance(row_tags, list):
            tags.update(str(t) for t in row_tags)

    return tags


def fetch_brand_min_asset_score(brand_id: str) -> float:
    """Read min_asset_score from brands.template_selection_config JSONB.

    Args:
        brand_id: Brand UUID string.

    Returns:
        Float in [0.0, 1.0]. Defaults to 0.0 if not configured or malformed.
    """
    try:
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        result = db.table("brands").select(
            "template_selection_config"
        ).eq("id", brand_id).single().execute()

        if not result.data:
            return 0.0

        config = result.data.get("template_selection_config")
        if not config or not isinstance(config, dict):
            return 0.0

        raw_value = config.get("min_asset_score")
        if raw_value is None:
            return 0.0

        value = float(raw_value)
        return max(0.0, min(1.0, value))

    except Exception as e:
        logger.warning(f"Failed to read brand min_asset_score for {brand_id}: {e}")
        return 0.0


# ============================================================================
# Fallback Selection
# ============================================================================

def select_templates_with_fallback(
    candidates: List[dict],
    context: SelectionContext,
    weights: Dict[str, float],
    count: int = 3,
    min_asset_score: float = 0.0,
    scorers: Optional[List[TemplateScorer]] = None,
) -> SelectionResult:
    """Select templates with 3-tier fallback.

    Fallback tiers:
        1. Normal selection with given params
        2. Retry with gate off (min_asset_score = 0)
        3. Retry with category filter removed (requested_category = None)
        4. Return SelectionResult(empty=True) with reason

    Important: When using this function, fetch candidates WITHOUT a category
    filter (``fetch_template_candidates(product_id)``). Set the category
    preference via ``context.requested_category`` instead — CategoryMatchScorer
    handles scoring. This ensures tier 3 fallback has non-matching-category
    templates available to select from.

    Args:
        candidates: Template row dicts from fetch_template_candidates().
            Fetch without category filter for fallback to work.
        context: Selection context.
        weights: Scorer weight dict.
        count: Number of templates to select.
        min_asset_score: Asset gate threshold.
        scorers: Scorer instances (defaults to PHASE_1_SCORERS).

    Returns:
        SelectionResult — check result.empty to see if selection succeeded.
    """
    if scorers is None:
        scorers = PHASE_3_SCORERS

    # Tier 1: Normal selection
    result = select_templates(
        candidates=candidates,
        context=context,
        scorers=scorers,
        weights=weights,
        min_asset_score=min_asset_score,
        count=count,
    )

    if not result.empty:
        logger.info(
            f"Template selection succeeded (tier 1): {len(result.templates)} selected "
            f"from {result.candidates_after_gate}/{result.candidates_before_gate} candidates"
        )
        return result

    # Tier 2: Retry with gate off (if gate was active)
    if min_asset_score > 0:
        logger.warning(
            f"Tier 1 failed ({result.reason}). Retrying with asset gate off."
        )
        result = select_templates(
            candidates=candidates,
            context=context,
            scorers=scorers,
            weights=weights,
            min_asset_score=0.0,
            count=count,
        )

        if not result.empty:
            logger.info(
                f"Template selection succeeded (tier 2, gate off): "
                f"{len(result.templates)} selected"
            )
            return result

    # Tier 3: Retry with category filter removed (if category was active)
    if context.requested_category is not None:
        logger.warning(
            f"Tier 2 failed. Retrying with category filter removed "
            f"(was: {context.requested_category})."
        )
        # Create a modified context without category filter
        relaxed_context = SelectionContext(
            product_id=context.product_id,
            brand_id=context.brand_id,
            product_asset_tags=context.product_asset_tags,
            requested_category=None,
            awareness_stage=context.awareness_stage,
            target_sex=context.target_sex,
            has_meta_connection=context.has_meta_connection,
        )
        result = select_templates(
            candidates=candidates,
            context=relaxed_context,
            scorers=scorers,
            weights=weights,
            min_asset_score=0.0,
            count=count,
        )

        if not result.empty:
            logger.info(
                f"Template selection succeeded (tier 3, no category): "
                f"{len(result.templates)} selected"
            )
            return result

    # Tier 4: All retries exhausted
    logger.error(
        f"Template selection failed after all fallback tiers. "
        f"Candidates: {len(candidates)}, Category: {context.requested_category}"
    )
    return SelectionResult(
        empty=True,
        reason=f"No templates available after all fallback tiers "
               f"(candidates={len(candidates)}, category={context.requested_category})",
        candidates_before_gate=len(candidates),
        candidates_after_gate=0,
    )
