"""
Account Leverage Service — Orchestrates cross-dimensional analysis to find
the highest-leverage moves in a Meta ad account.

Phase 1: Uses existing services (coverage, genome, interactions, whitespace,
performance) to rank opportunities. No new API calls or migrations.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Awareness levels in funnel order (top to bottom)
AWARENESS_FUNNEL = [
    "unaware",
    "problem_aware",
    "solution_aware",
    "product_aware",
    "most_aware",
]

AWARENESS_LABELS = {
    "unaware": "cold audiences who don't know they have a problem",
    "problem_aware": "people who know their problem but not solutions",
    "solution_aware": "people exploring solutions but haven't found yours",
    "product_aware": "people who know your product but haven't bought",
    "most_aware": "your warmest audience, ready to buy",
}

# Elements tracked by the creative genome
TRACKED_ELEMENTS = [
    "hook_type", "awareness_stage", "template_category",
    "creative_direction", "color_mode", "canvas_size",
]


@dataclass
class LeverageMove:
    """A single actionable recommendation for improving the ad account."""

    leverage_type: str  # coverage_gap, element_opportunity, whitespace, angle_expansion, format_expansion, persona_insight
    move_category: str  # "Quick Win", "Strategic Bet", "Explore"
    confidence: float  # 0-1
    title: str  # Plain-language headline
    why: str  # 1-2 sentences with real numbers
    expected_outcome: str  # Concrete prediction
    next_step: str  # Single clear action
    recommended_action: Dict[str, Any]  # Scheduler-compatible params
    evidence: Dict[str, Any]  # Supporting data
    effort: int  # Recommended number of ads to create


class AccountLeverageService:
    """Orchestrates cross-dimensional analysis to find high-leverage ad account moves."""

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def analyze_account(
        self,
        brand_id: str,
        org_id: str,
        days_back: int = 30,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze the ad account and return ranked leverage moves.

        Returns dict with: account_score, dimension_scores, leverage_moves,
        data_quality, warnings.
        """
        warnings: List[str] = []

        # -- Gather data from existing services --
        awareness_data, format_data, coverage_result, interactions, whitespace, element_scores = (
            self._gather_data(brand_id, days_back, product_id)
        )

        # Debug: log what we got back
        logger.info(
            f"Leverage gather results: awareness_levels={len(awareness_data.get('levels', []))}, "
            f"total_classified={awareness_data.get('total_classified', 'MISSING')}, "
            f"date_range={awareness_data.get('date_range', 'MISSING')}, "
            f"format_groups={len(format_data.get('groups', []))}, "
            f"interactions={len(interactions)}, whitespace={len(whitespace)}, "
            f"element_keys={list(element_scores.keys())}"
        )

        # -- Check data quality --
        data_quality = self._assess_data_quality(awareness_data, element_scores)
        if data_quality["classified_ads"] < 15:
            warnings.append(
                f"Only {data_quality['classified_ads']} classified ads found. "
                "Recommendations may be less reliable. Run Ad Classification to improve."
            )
        if data_quality["days_of_data"] < 7:
            warnings.append(
                f"Only {data_quality['days_of_data']} days of data. "
                "Wait for more data to accumulate for better recommendations."
            )

        genome_coverage = data_quality["coverage_pct"]
        suppress_element_moves = genome_coverage < 0.5
        if suppress_element_moves and data_quality["genome_scored_ads"] > 0:
            warnings.append(
                f"{data_quality['genome_scored_ads']} of {data_quality['total_ads']} ads "
                f"have creative element data ({genome_coverage:.0%}). "
                "Some recommendations are hidden until more ads are scored."
            )

        low_confidence = data_quality["classified_ads"] < 15 or data_quality["days_of_data"] < 7

        # -- Generate leverage moves from each dimension --
        moves: List[LeverageMove] = []

        moves.extend(self._awareness_gap_moves(awareness_data, coverage_result))

        if not suppress_element_moves:
            moves.extend(self._element_opportunity_moves(element_scores, interactions))
            moves.extend(self._whitespace_moves(whitespace))

        moves.extend(self._format_expansion_moves(format_data, element_scores))
        moves.extend(self._persona_insight_moves(brand_id))
        moves.extend(self._angle_expansion_moves(brand_id))
        moves.extend(self._creative_insight_moves(brand_id))

        # Apply low-confidence cap
        if low_confidence:
            for m in moves:
                m.confidence = min(m.confidence, 0.4)

        # Sort: Quick Win first, then Strategic Bet, then Explore. Within category, by confidence desc.
        category_order = {"Quick Win": 0, "Strategic Bet": 1, "Explore": 2}
        moves.sort(key=lambda m: (category_order.get(m.move_category, 9), -m.confidence))

        # Cap at 15
        moves = moves[:15]

        # -- Compute dimension scores --
        dimension_scores = self._compute_dimension_scores(
            awareness_data, coverage_result, element_scores, format_data
        )

        # Account score = weighted average
        account_score = int(
            dimension_scores["awareness_coverage"] * 0.30
            + dimension_scores["element_diversity"] * 0.25
            + dimension_scores["angle_coverage"] * 0.25
            + dimension_scores["format_coverage"] * 0.20
        )

        return {
            "account_score": account_score,
            "dimension_scores": dimension_scores,
            "leverage_moves": moves,
            "data_quality": data_quality,
            "warnings": warnings,
        }

    # ========================================================================
    # DATA GATHERING
    # ========================================================================

    def _gather_data(
        self,
        brand_id: str,
        days_back: int,
        product_id: Optional[str],
    ):
        """Gather data from all child services sequentially."""
        from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
        from viraltracker.services.creative_genome_service import CreativeGenomeService
        from viraltracker.services.whitespace_identification_service import WhitespaceIdentificationService

        perf_service = AdPerformanceQueryService(self.supabase)
        genome_service = CreativeGenomeService()
        whitespace_service = WhitespaceIdentificationService()

        brand_uuid = UUID(brand_id) if isinstance(brand_id, str) else brand_id

        # Awareness breakdown (sync)
        try:
            awareness_data = perf_service.get_breakdown_by_awareness(
                brand_id, days_back, product_id
            )
            logger.info(
                f"Awareness data: {len(awareness_data.get('levels', []))} levels, "
                f"total_classified={awareness_data.get('total_classified', 'MISSING')}"
            )
        except Exception as e:
            logger.error(f"Awareness breakdown failed: {e}", exc_info=True)
            awareness_data = {"levels": [], "gaps": [], "total_classified": 0, "total_unclassified": 0, "date_range": {}}

        # Format breakdown (sync)
        try:
            format_data = perf_service.get_breakdown_by_media_type(brand_id, days_back)
        except Exception as e:
            logger.error(f"Format breakdown failed: {e}")
            format_data = {"groups": []}

        # Coverage analyzer (async — run in a small event loop)
        coverage_result = None
        try:
            from viraltracker.services.ad_intelligence.coverage_analyzer import CoverageAnalyzer
            coverage_analyzer = CoverageAnalyzer(self.supabase)
            coverage_result = asyncio.run(
                coverage_analyzer.analyze_coverage(brand_uuid, date.today(), days_back)
            )
        except Exception as e:
            logger.error(f"Coverage analysis failed: {e}")

        # Interactions (async — run in a small event loop)
        try:
            from viraltracker.services.interaction_detector_service import InteractionDetectorService
            interaction_service = InteractionDetectorService()
            interactions = asyncio.run(
                interaction_service.get_top_interactions(brand_uuid, 15)
            )
        except Exception as e:
            logger.error(f"Interactions lookup failed: {e}")
            interactions = []

        # Element scores (sync, fast per call)
        element_scores = {}
        for elem in TRACKED_ELEMENTS:
            try:
                element_scores[elem] = genome_service.sample_element_scores(brand_uuid, elem)
            except Exception as e:
                logger.warning(f"Element score lookup failed for {elem}: {e}")
                element_scores[elem] = []

        # Whitespace (sync)
        try:
            whitespace = whitespace_service.get_whitespace_candidates(brand_uuid, 20)
        except Exception as e:
            logger.warning(f"Whitespace lookup failed: {e}")
            whitespace = []

        return awareness_data, format_data, coverage_result, interactions, whitespace, element_scores

    # ========================================================================
    # DATA QUALITY
    # ========================================================================

    def _assess_data_quality(
        self,
        awareness_data: Dict[str, Any],
        element_scores: Dict[str, List],
    ) -> Dict[str, Any]:
        """Assess data quality for confidence gating."""
        # get_breakdown_by_awareness returns: total_classified, total_unclassified,
        # date_range: {start, end}, levels: [...]
        classified_ads = awareness_data.get("total_classified", 0)
        total_unclassified = awareness_data.get("total_unclassified", 0)
        total_ads = classified_ads + total_unclassified

        # Also count unique ads across levels as a fallback
        if total_ads == 0:
            levels = awareness_data.get("levels", [])
            total_ads = sum(lv.get("ad_count", 0) for lv in levels)
            classified_ads = total_ads  # all returned ads are classified

        # Count genome-scored ads by looking at total_observations across elements
        total_obs = 0
        for elem_list in element_scores.values():
            for item in elem_list:
                total_obs += item.get("total_observations", 0)
        # Rough estimate: each scored ad contributes ~len(TRACKED_ELEMENTS) observations
        genome_scored_ads = total_obs // max(len(TRACKED_ELEMENTS), 1) if total_obs > 0 else 0

        # Days of data
        date_range = awareness_data.get("date_range", {})
        date_start = date_range.get("start")
        date_end = date_range.get("end")
        if date_start and date_end:
            try:
                d1 = datetime.fromisoformat(date_start).date() if isinstance(date_start, str) else date_start
                d2 = datetime.fromisoformat(date_end).date() if isinstance(date_end, str) else date_end
                days_of_data = (d2 - d1).days + 1
            except (ValueError, TypeError):
                days_of_data = 0
        else:
            days_of_data = 0

        coverage_pct = genome_scored_ads / max(total_ads, 1)

        return {
            "total_ads": total_ads,
            "classified_ads": classified_ads,
            "genome_scored_ads": genome_scored_ads,
            "days_of_data": days_of_data,
            "coverage_pct": coverage_pct,
        }

    # ========================================================================
    # DIMENSION SCORES
    # ========================================================================

    def _compute_dimension_scores(
        self,
        awareness_data: Dict,
        coverage_result,
        element_scores: Dict[str, List],
        format_data: Dict,
    ) -> Dict[str, int]:
        """Compute 0-100 scores for each dimension."""
        # Awareness coverage: based on gaps
        gap_count = len(coverage_result.gaps) if coverage_result and hasattr(coverage_result, 'gaps') else 0
        awareness_coverage = max(0, 100 - (gap_count * 20))

        # Element diversity: how many element values have been tested
        tested = 0
        possible = 0
        for elem_list in element_scores.values():
            possible += max(len(elem_list), 1)
            tested += sum(1 for item in elem_list if item.get("total_observations", 0) >= 3)
        element_diversity = int((tested / max(possible, 1)) * 100)

        # Angle coverage: check if angles exist
        try:
            result = self.supabase.table("belief_angles").select(
                "id", count="exact"
            ).eq("status", "active").execute()
            total_angles = result.count or 0
            # Count angles that have been used in ads
            used_result = self.supabase.table("belief_angles").select(
                "id", count="exact"
            ).eq("status", "active").neq("ad_count", 0).execute()
            tested_angles = used_result.count or 0
        except Exception:
            total_angles = 0
            tested_angles = 0

        if total_angles > 0:
            angle_coverage = int((tested_angles / max(total_angles, 1)) * 100)
        else:
            angle_coverage = 50  # Neutral when no angles exist

        # Format coverage: formats with at least one winning ad
        format_groups = format_data.get("groups", [])
        total_formats = max(len(format_groups), 1)
        with_winners = sum(1 for g in format_groups if g.get("roas", 0) > 1.0)
        format_coverage = int((with_winners / max(total_formats, 1)) * 100)

        return {
            "awareness_coverage": min(awareness_coverage, 100),
            "element_diversity": min(element_diversity, 100),
            "angle_coverage": min(angle_coverage, 100),
            "format_coverage": min(format_coverage, 100),
        }

    # ========================================================================
    # LEVERAGE MOVE GENERATORS
    # ========================================================================

    def _awareness_gap_moves(
        self,
        awareness_data: Dict[str, Any],
        coverage_result,
    ) -> List[LeverageMove]:
        """Find gaps in awareness level coverage and under-resourced high-performers."""
        moves = []
        levels = awareness_data.get("levels", [])
        if not levels:
            return moves

        # Build lookup by awareness_level
        level_map = {lv["awareness_level"]: lv for lv in levels}

        # Compute account average ROAS
        total_spend = sum(lv.get("spend", 0) for lv in levels)
        total_value = sum(lv.get("purchase_value", 0) for lv in levels)
        avg_roas = total_value / max(total_spend, 0.01)

        # Check if this is a deliberate bottom-funnel brand
        # (no unaware or problem_aware ads at all)
        has_top_funnel = any(
            level_map.get(lv, {}).get("ad_count", 0) > 0
            for lv in ["unaware", "problem_aware"]
        )

        for i, level_key in enumerate(AWARENESS_FUNNEL):
            level_data = level_map.get(level_key)
            ad_count = level_data.get("ad_count", 0) if level_data else 0
            level_label = (level_data.get("label") or level_data.get("level_label") or level_key.replace("_", " ").title()) if level_data else level_key.replace("_", " ").title()
            plain_label = AWARENESS_LABELS.get(level_key, level_key)

            if ad_count == 0:
                # Skip suggesting top-funnel ads for deliberate bottom-funnel brands
                if not has_top_funnel and level_key in ["unaware", "problem_aware"]:
                    continue

                # Find adjacent levels with data
                adjacent_roas = []
                for offset in [-1, 1]:
                    adj_idx = i + offset
                    if 0 <= adj_idx < len(AWARENESS_FUNNEL):
                        adj_key = AWARENESS_FUNNEL[adj_idx]
                        adj_data = level_map.get(adj_key)
                        if adj_data and adj_data.get("ad_count", 0) > 0:
                            adjacent_roas.append(adj_data.get("roas", 0))

                if not adjacent_roas:
                    continue  # No adjacent data to base prediction on

                adj_avg_roas = sum(adjacent_roas) / len(adjacent_roas)

                moves.append(LeverageMove(
                    leverage_type="coverage_gap",
                    move_category="Quick Win" if adj_avg_roas > avg_roas else "Strategic Bet",
                    confidence=min(0.85, 0.5 + (adj_avg_roas / max(avg_roas, 0.01)) * 0.2),
                    title=f"You have zero ads for {plain_label}",
                    why=(
                        f"You have 0 {level_label} ads, but adjacent awareness levels "
                        f"are converting at {adj_avg_roas:.1f}x ROAS. "
                        f"This is a gap in your funnel."
                    ),
                    expected_outcome=(
                        f"Could improve overall ROAS by filling this funnel gap. "
                        f"Adjacent levels average {adj_avg_roas:.1f}x ROAS."
                    ),
                    next_step=f"Create 5 ads targeting {plain_label}.",
                    recommended_action={
                        "awareness_stage": level_key,
                        "num_variations": 5,
                    },
                    evidence={
                        "gap_level": level_key,
                        "adjacent_roas": adj_avg_roas,
                        "account_avg_roas": avg_roas,
                    },
                    effort=5,
                ))

            elif ad_count > 0 and level_data:
                # Check for under-resourced high performers
                level_roas = level_data.get("roas", 0)
                level_spend_pct = level_data.get("spend", 0) / max(total_spend, 0.01)
                level_value_pct = level_data.get("purchase_value", 0) / max(total_value, 0.01)

                # High ROAS but low spend allocation = under-resourced
                if level_roas > avg_roas * 1.3 and level_spend_pct < 0.15 and ad_count < 10:
                    moves.append(LeverageMove(
                        leverage_type="coverage_gap",
                        move_category="Quick Win",
                        confidence=min(0.90, 0.6 + (level_roas / max(avg_roas, 0.01)) * 0.1),
                        title=f"Your {plain_label} ads are outperforming but under-funded",
                        why=(
                            f"{level_label} is converting at {level_roas:.1f}x ROAS "
                            f"({level_roas/max(avg_roas, 0.01):.1f}x your account average) "
                            f"but only gets {level_spend_pct:.0%} of spend with just {ad_count} ads."
                        ),
                        expected_outcome=(
                            f"More creative variety at this level could capture "
                            f"additional conversions at {level_roas:.1f}x ROAS."
                        ),
                        next_step=f"Create {5 - min(ad_count, 4)} more ads for {plain_label}.",
                        recommended_action={
                            "awareness_stage": level_key,
                            "num_variations": max(3, 5 - ad_count),
                        },
                        evidence={
                            "level": level_key,
                            "roas": level_roas,
                            "account_avg_roas": avg_roas,
                            "spend_pct": level_spend_pct,
                            "ad_count": ad_count,
                        },
                        effort=max(3, 5 - ad_count),
                    ))

        return moves

    def _element_opportunity_moves(
        self,
        element_scores: Dict[str, List],
        interactions: List[Dict],
    ) -> List[LeverageMove]:
        """Find high-performing but under-tested elements and synergy pairs."""
        moves = []

        # Find elements with high mean_reward but low observations
        for elem_name, scores in element_scores.items():
            if not scores:
                continue

            # Get top quartile threshold
            rewards = [s.get("mean_reward", 0) for s in scores if s.get("total_observations", 0) >= 3]
            if len(rewards) < 4:
                continue
            top_quartile = sorted(rewards, reverse=True)[len(rewards) // 4]

            for score in scores:
                obs = score.get("total_observations", 0)
                reward = score.get("mean_reward", 0)
                value = score.get("value", "unknown")

                if reward >= top_quartile and obs < 10 and obs >= 2:
                    elem_label = elem_name.replace("_", " ")
                    moves.append(LeverageMove(
                        leverage_type="element_opportunity",
                        move_category="Strategic Bet",
                        confidence=min(0.7, 0.3 + (obs / 20)),
                        title=f"'{value}' {elem_label} is promising but undertested",
                        why=(
                            f"'{value}' has a {reward:.2f} reward score (top 25% for {elem_label}) "
                            f"but only {obs} observations. More testing could confirm this winner."
                        ),
                        expected_outcome=(
                            f"If confirmed, using '{value}' more could improve "
                            f"performance across ads using this {elem_label}."
                        ),
                        next_step=f"Create 3 ads using '{value}' as the {elem_label}.",
                        recommended_action={
                            elem_name: value,
                            "num_variations": 3,
                        },
                        evidence={
                            "element_name": elem_name,
                            "element_value": value,
                            "mean_reward": reward,
                            "observations": obs,
                            "top_quartile_threshold": top_quartile,
                        },
                        effort=3,
                    ))

        # Find under-utilized synergy pairs
        for inter in interactions[:5]:
            if inter.get("effect_direction") != "synergy":
                continue
            effect = inter.get("interaction_effect", 0)
            sample = inter.get("sample_size", 0)
            if effect > 0.1 and sample < 15:
                a_name = inter.get("element_a_name", "")
                a_value = inter.get("element_a_value", "")
                b_name = inter.get("element_b_name", "")
                b_value = inter.get("element_b_value", "")

                moves.append(LeverageMove(
                    leverage_type="element_opportunity",
                    move_category="Strategic Bet",
                    confidence=min(0.65, 0.3 + (sample / 30)),
                    title=f"'{a_value}' + '{b_value}' work well together but are underused",
                    why=(
                        f"When '{a_value}' ({a_name.replace('_', ' ')}) appears with "
                        f"'{b_value}' ({b_name.replace('_', ' ')}), ads perform "
                        f"{effect:.0%} better than expected. Only seen in {sample} ads."
                    ),
                    expected_outcome=(
                        f"Combining these elements could boost ad performance by ~{effect:.0%}."
                    ),
                    next_step=(
                        f"Create 3 ads combining '{a_value}' with '{b_value}'."
                    ),
                    recommended_action={
                        a_name: a_value,
                        b_name: b_value,
                        "num_variations": 3,
                    },
                    evidence={
                        "synergy_effect": effect,
                        "sample_size": sample,
                        "element_a": f"{a_name}={a_value}",
                        "element_b": f"{b_name}={b_value}",
                    },
                    effort=3,
                ))

        return moves

    def _whitespace_moves(
        self,
        whitespace_candidates: List[Dict],
    ) -> List[LeverageMove]:
        """Convert high-potential whitespace candidates into moves."""
        moves = []

        for ws in whitespace_candidates[:5]:
            potential = ws.get("predicted_potential", 0)
            if potential < 0.6:
                continue

            a_name = ws.get("element_a_name", "")
            a_value = ws.get("element_a_value", "")
            b_name = ws.get("element_b_name", "")
            b_value = ws.get("element_b_value", "")
            usage = ws.get("usage_count", 0)

            if usage > 0:
                continue  # Not truly whitespace

            moves.append(LeverageMove(
                leverage_type="whitespace",
                move_category="Explore",
                confidence=min(0.55, potential * 0.7),
                title=f"Untested combo: '{a_value}' with '{b_value}'",
                why=(
                    f"'{a_value}' ({a_name.replace('_', ' ')}) and "
                    f"'{b_value}' ({b_name.replace('_', ' ')}) each perform well individually "
                    f"but have never been combined. Predicted potential: {potential:.0%}."
                ),
                expected_outcome=(
                    f"This untested combination has {potential:.0%} predicted potential "
                    f"based on individual element performance."
                ),
                next_step=f"Create 2 test ads combining '{a_value}' with '{b_value}'.",
                recommended_action={
                    a_name: a_value,
                    b_name: b_value,
                    "num_variations": 2,
                },
                evidence={
                    "predicted_potential": potential,
                    "element_a": f"{a_name}={a_value}",
                    "element_b": f"{b_name}={b_value}",
                    "usage_count": usage,
                },
                effort=2,
            ))

        return moves

    def _format_expansion_moves(
        self,
        format_data: Dict[str, Any],
        element_scores: Dict[str, List],
    ) -> List[LeverageMove]:
        """Find formats that are under-represented relative to their performance."""
        moves = []
        groups = format_data.get("groups", [])
        if not groups:
            return moves

        total_spend = sum(g.get("spend", 0) for g in groups)
        total_value = sum(g.get("purchase_value", 0) for g in groups)
        avg_roas = total_value / max(total_spend, 0.01)

        for group in groups:
            fmt = group.get("media_type", "unknown")
            roas = group.get("roas", 0)
            ad_count = group.get("ad_count", 0)
            spend_pct = group.get("spend", 0) / max(total_spend, 0.01)

            # High ROAS format with few ads
            if roas > avg_roas * 1.2 and ad_count < 5 and ad_count > 0:
                moves.append(LeverageMove(
                    leverage_type="format_expansion",
                    move_category="Quick Win" if roas > avg_roas * 1.5 else "Strategic Bet",
                    confidence=min(0.80, 0.5 + (roas / max(avg_roas, 0.01)) * 0.15),
                    title=f"{fmt} ads are working well but you only have {ad_count}",
                    why=(
                        f"{fmt} is converting at {roas:.1f}x ROAS "
                        f"({roas/max(avg_roas, 0.01):.1f}x your average) "
                        f"with only {ad_count} ads and {spend_pct:.0%} of spend."
                    ),
                    expected_outcome=(
                        f"More {fmt.lower()} creative variety could maintain "
                        f"the {roas:.1f}x ROAS while reaching more people."
                    ),
                    next_step=f"Create {5 - min(ad_count, 4)} more {fmt.lower()} ads.",
                    recommended_action={
                        "media_type": fmt.lower(),
                        "num_variations": max(3, 5 - ad_count),
                    },
                    evidence={
                        "format": fmt,
                        "roas": roas,
                        "account_avg_roas": avg_roas,
                        "ad_count": ad_count,
                        "spend_pct": spend_pct,
                    },
                    effort=max(3, 5 - ad_count),
                ))

            # Format with zero ads but others are performing
            if ad_count == 0 and avg_roas > 1.0:
                moves.append(LeverageMove(
                    leverage_type="format_expansion",
                    move_category="Explore",
                    confidence=0.35,
                    title=f"You have no {fmt.lower()} ads yet",
                    why=(
                        f"Your account has no {fmt.lower()} ads. "
                        f"Other formats are averaging {avg_roas:.1f}x ROAS, "
                        f"so {fmt.lower()} could be worth testing."
                    ),
                    expected_outcome=(
                        f"Adding {fmt.lower()} ads diversifies your creative mix "
                        f"and could find new winning formats."
                    ),
                    next_step=f"Create 3 {fmt.lower()} ads to test this format.",
                    recommended_action={
                        "media_type": fmt.lower(),
                        "num_variations": 3,
                    },
                    evidence={
                        "format": fmt,
                        "account_avg_roas": avg_roas,
                    },
                    effort=3,
                ))

        return moves

    def _persona_insight_moves(self, brand_id: str) -> List[LeverageMove]:
        """Find personas with high reward but few ads."""
        moves = []

        try:
            # Query: generated_ads with persona_id -> creative_element_rewards
            result = self.supabase.rpc("get_persona_performance", {
                "p_brand_id": brand_id
            }).execute()

            if not result.data:
                # Fall back to manual query if RPC doesn't exist
                return self._persona_insight_moves_fallback(brand_id)

        except Exception:
            return self._persona_insight_moves_fallback(brand_id)

        return moves

    def _persona_insight_moves_fallback(self, brand_id: str) -> List[LeverageMove]:
        """Fallback persona analysis using direct queries."""
        moves = []
        try:
            # Get generated ads with persona tags and their rewards
            result = self.supabase.table("generated_ads").select(
                "id, element_tags"
            ).eq("brand_id", brand_id).not_.is_("element_tags", "null").execute()

            if not result.data:
                return moves

            # Group by persona_id
            persona_ads: Dict[str, List[str]] = {}
            for ad in result.data:
                tags = ad.get("element_tags") or {}
                pid = tags.get("persona_id")
                if pid:
                    persona_ads.setdefault(pid, []).append(ad["id"])

            if not persona_ads:
                return moves

            # Get rewards for these ads
            all_ad_ids = [aid for aids in persona_ads.values() for aid in aids]
            if len(all_ad_ids) > 500:
                all_ad_ids = all_ad_ids[:500]

            rewards_result = self.supabase.table("creative_element_rewards").select(
                "generated_ad_id, reward_score"
            ).in_("generated_ad_id", all_ad_ids).execute()

            reward_map: Dict[str, float] = {}
            for r in (rewards_result.data or []):
                reward_map[r["generated_ad_id"]] = r.get("reward_score", 0)

            # Compute per-persona stats
            persona_stats = []
            for pid, ad_ids in persona_ads.items():
                rewards = [reward_map.get(aid, 0) for aid in ad_ids if aid in reward_map]
                if rewards:
                    persona_stats.append({
                        "persona_id": pid,
                        "mean_reward": sum(rewards) / len(rewards),
                        "ad_count": len(ad_ids),
                        "scored_count": len(rewards),
                    })

            if not persona_stats:
                return moves

            # Find average reward across all personas
            all_rewards = [p["mean_reward"] for p in persona_stats]
            avg_reward = sum(all_rewards) / len(all_rewards)

            # Get persona names
            persona_ids = [p["persona_id"] for p in persona_stats]
            name_result = self.supabase.table("personas_4d").select(
                "id, persona_name, age_range, gender"
            ).in_("id", persona_ids).execute()
            name_map = {p["id"]: p for p in (name_result.data or [])}

            for ps in persona_stats:
                if ps["mean_reward"] > avg_reward * 1.2 and ps["ad_count"] < 8:
                    persona_info = name_map.get(ps["persona_id"], {})
                    name = persona_info.get("persona_name", "this audience")
                    age = persona_info.get("age_range", "")
                    gender = persona_info.get("gender", "")
                    desc = name
                    if age and gender:
                        desc = f"{name} ({gender}, {age})"

                    moves.append(LeverageMove(
                        leverage_type="persona_insight",
                        move_category="Quick Win" if ps["mean_reward"] > avg_reward * 1.5 else "Strategic Bet",
                        confidence=min(0.75, 0.4 + (ps["scored_count"] / 20)),
                        title=f"'{desc}' audience is responding well but has few ads",
                        why=(
                            f"Ads targeting '{desc}' have a {ps['mean_reward']:.2f} reward score "
                            f"({ps['mean_reward']/max(avg_reward, 0.01):.1f}x your average) "
                            f"but only {ps['ad_count']} ads exist for this audience."
                        ),
                        expected_outcome=(
                            f"Creating more ads for this audience could replicate "
                            f"the {ps['mean_reward']:.2f} reward performance at scale."
                        ),
                        next_step=f"Create 5 ads targeting '{desc}'.",
                        recommended_action={
                            "persona_id": ps["persona_id"],
                            "num_variations": 5,
                        },
                        evidence={
                            "persona_id": ps["persona_id"],
                            "persona_name": name,
                            "mean_reward": ps["mean_reward"],
                            "avg_reward": avg_reward,
                            "ad_count": ps["ad_count"],
                        },
                        effort=5,
                    ))

        except Exception as e:
            logger.warning(f"Persona insight analysis failed: {e}")

        return moves

    def _angle_expansion_moves(self, brand_id: str) -> List[LeverageMove]:
        """Find belief angles with high reward but few ad variants."""
        moves = []
        try:
            # Get angles with their ad counts and performance
            angles_result = self.supabase.table("belief_angles").select(
                "id, belief_statement, status"
            ).eq("status", "active").execute()

            if not angles_result.data:
                return moves

            # For each angle, find generated ads that used it
            for angle in angles_result.data:
                angle_id = angle["id"]
                belief = angle.get("belief_statement", "")[:80]

                # Find ads scheduled with this angle
                jobs_result = self.supabase.table("scheduled_jobs").select(
                    "id, parameters"
                ).eq("brand_id", brand_id).execute()

                angle_ad_ids = []
                for job in (jobs_result.data or []):
                    params = job.get("parameters") or {}
                    if angle_id in (params.get("angle_ids") or []):
                        # Get generated ads from this job
                        ads_result = self.supabase.table("generated_ads").select(
                            "id"
                        ).eq("scheduled_job_id", job["id"]).execute()
                        angle_ad_ids.extend([a["id"] for a in (ads_result.data or [])])

                if not angle_ad_ids:
                    continue

                # Get rewards
                rewards_result = self.supabase.table("creative_element_rewards").select(
                    "reward_score"
                ).in_("generated_ad_id", angle_ad_ids[:100]).execute()

                rewards = [r.get("reward_score", 0) for r in (rewards_result.data or [])]
                if not rewards:
                    continue

                mean_reward = sum(rewards) / len(rewards)
                ad_count = len(angle_ad_ids)

                if mean_reward > 0.5 and ad_count < 5:
                    moves.append(LeverageMove(
                        leverage_type="angle_expansion",
                        move_category="Strategic Bet",
                        confidence=min(0.70, 0.35 + (len(rewards) / 15)),
                        title=f"Your '{belief[:50]}...' angle is working but undertested",
                        why=(
                            f"This belief angle has a {mean_reward:.2f} reward score "
                            f"across {ad_count} ads. More variations could confirm it as a winner."
                        ),
                        expected_outcome=(
                            f"Testing more creative with this angle could validate "
                            f"the {mean_reward:.2f} reward and scale it."
                        ),
                        next_step=f"Create 3 more ads using this belief angle.",
                        recommended_action={
                            "content_source": "angles",
                            "angle_ids": [angle_id],
                            "num_variations": 3,
                        },
                        evidence={
                            "angle_id": angle_id,
                            "belief_statement": belief,
                            "mean_reward": mean_reward,
                            "ad_count": ad_count,
                        },
                        effort=3,
                    ))

                # Cap angle moves
                if len(moves) >= 3:
                    break

        except Exception as e:
            logger.warning(f"Angle expansion analysis failed: {e}")

        return moves

    def _creative_insight_moves(self, brand_id: str) -> List[LeverageMove]:
        """Generate moves from Gemini creative analysis correlations.

        Reads creative_performance_correlations to find messaging themes,
        emotional tones, hook patterns, and persona types that significantly
        outperform or underperform the account average.
        """
        moves = []
        try:
            from viraltracker.services.creative_correlation_service import CreativeCorrelationService
            corr_service = CreativeCorrelationService(supabase_client=self.supabase)

            top = corr_service.get_top_correlations(
                UUID(brand_id), min_confidence=0.3, limit=10
            )

            if not top:
                return moves

            # Field name → plain language label
            field_labels = {
                "emotional_tone": "emotional tone",
                "hook_pattern": "hook pattern",
                "cta_style": "CTA style",
                "messaging_theme": "messaging theme",
                "people_role": "person type",
                "visual_color_mood": "color mood",
                "visual_imagery_type": "imagery type",
                "visual_production_quality": "production quality",
                "hook_type": "hook type",
                "format_type": "ad format",
                "production_quality": "production quality",
                "video_emotional_drivers": "emotional driver",
                "video_people_role": "person type (video)",
                "awareness_level": "awareness level",
            }

            for corr in top:
                vs_avg = corr.get("vs_account_avg", 1.0)
                ad_count = corr.get("ad_count", 0)
                confidence = corr.get("confidence", 0)
                field = corr.get("analysis_field", "")
                value = corr.get("field_value", "")
                field_label = field_labels.get(field, field.replace("_", " "))

                # Only surface strong outperformers (> 1.5x) or patterns with many ads
                if vs_avg < 1.5:
                    continue

                multiplier = f"{vs_avg:.1f}x"

                if confidence >= 0.7 and ad_count >= 5:
                    category = "Quick Win"
                elif confidence >= 0.4:
                    category = "Strategic Bet"
                else:
                    category = "Explore"

                moves.append(LeverageMove(
                    leverage_type="creative_insight",
                    move_category=category,
                    confidence=confidence,
                    title=f"Ads with '{value}' {field_label} outperform by {multiplier}",
                    why=(
                        f"Across {ad_count} ads, those using '{value}' as the "
                        f"{field_label} perform {multiplier} better than your account average."
                    ),
                    expected_outcome=(
                        f"Creating more ads with this {field_label} could improve "
                        f"overall ROAS based on the {multiplier} outperformance pattern."
                    ),
                    next_step=f"Create 5 ads that use '{value}' as the {field_label}.",
                    recommended_action={
                        "creative_insight": field,
                        "creative_value": value,
                        "num_variations": 5,
                    },
                    evidence={
                        "analysis_field": field,
                        "field_value": value,
                        "vs_account_avg": vs_avg,
                        "ad_count": ad_count,
                        "mean_roas": corr.get("mean_roas"),
                        "mean_ctr": corr.get("mean_ctr"),
                        "source_table": corr.get("source_table"),
                    },
                    effort=5,
                ))

                if len(moves) >= 4:
                    break

        except Exception as e:
            logger.warning(f"Creative insight analysis failed: {e}")

        return moves
