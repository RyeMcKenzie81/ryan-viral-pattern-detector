"""
Winner DNA Analyzer — Decomposes what makes winning ads work.

Provides per-winner deep dives (element attribution, visual properties, messaging,
cohort comparison) and cross-winner pattern extraction (common elements, anti-patterns,
replication blueprint).

Usage:
    from viraltracker.services.winner_dna_analyzer import WinnerDNAAnalyzer

    analyzer = WinnerDNAAnalyzer(supabase_client, gemini_service)
    dna = await analyzer.analyze_winner(meta_ad_id, brand_id, org_id)
    cross = await analyzer.analyze_cross_winners(brand_id, org_id, top_n=10)
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Humanized element labels for display
ELEMENT_DISPLAY_NAMES = {
    "hook_type": "Hook Style",
    "awareness_stage": "Audience Awareness",
    "color_mode": "Color Strategy",
    "template_category": "Layout Style",
    "canvas_size": "Ad Size",
    "content_source": "Content Source",
    "creative_direction": "Creative Direction",
    "visual_style": "Visual Style",
}

# Minimum frequency for cross-winner common elements (70%)
COMMON_ELEMENT_THRESHOLD = 0.7


@dataclass
class WinnerDNA:
    """Full DNA decomposition for a single winning ad."""

    meta_ad_id: str
    metrics: Dict[str, Any]
    element_scores: List[Dict[str, Any]]
    top_elements: List[Dict[str, Any]]
    weak_elements: List[Dict[str, Any]]
    visual_properties: Optional[Dict[str, Any]]
    messaging: Dict[str, Any]
    cohort_comparison: Dict[str, Any]
    active_synergies: List[Dict[str, Any]]
    active_conflicts: List[Dict[str, Any]]


@dataclass
class CrossWinnerAnalysis:
    """Cross-winner pattern extraction results."""

    winner_count: int
    common_elements: Dict[str, Any]
    common_visual_traits: Dict[str, Any]
    anti_patterns: List[Dict[str, Any]]
    iteration_directions: List[Dict[str, Any]]
    replication_blueprint: Dict[str, Any]
    winner_dnas: List[WinnerDNA] = field(default_factory=list)


class WinnerDNAAnalyzer:
    """Analyzes winner ad DNA for element attribution and pattern extraction."""

    def __init__(self, supabase_client, gemini_service=None):
        self.supabase = supabase_client
        self.gemini = gemini_service

    async def analyze_winner(
        self,
        meta_ad_id: str,
        brand_id: str,
        org_id: str,
    ) -> Optional[WinnerDNA]:
        """Full per-winner DNA decomposition.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID string.
            org_id: Organization UUID.

        Returns:
            WinnerDNA object, or None if insufficient data.
        """
        # 1. Get performance metrics
        metrics = self._get_ad_metrics(meta_ad_id, brand_id)
        if not metrics:
            return None

        # 2. Get classification
        classification = self._get_classification(meta_ad_id, brand_id)

        # 3. Get element scores from genome (if generated ad)
        generated_ad_id = self._find_generated_ad(meta_ad_id, brand_id)
        element_tags = {}
        if generated_ad_id:
            element_tags = self._get_element_tags(generated_ad_id)

        element_scores = []
        if element_tags:
            element_scores = self._get_element_attribution(element_tags, brand_id)

        # Sort by mean_reward desc
        element_scores.sort(key=lambda e: e.get("mean_reward", 0), reverse=True)
        top_elements = element_scores[:3] if len(element_scores) >= 3 else element_scores
        weak_elements = element_scores[-3:] if len(element_scores) >= 6 else []

        # 4. Extract visual properties (with caching)
        visual_properties = await self._extract_visual_properties(
            meta_ad_id, brand_id, org_id
        )

        # 5. Build messaging profile
        messaging = self._build_messaging_profile(classification, element_tags)

        # 6. Cohort comparison
        cohort_comparison = await self._compute_cohort_comparison(
            meta_ad_id, brand_id, metrics
        )

        # 7. Get interaction effects
        synergies, conflicts = self._get_interaction_effects(element_tags, brand_id)

        # 8. Store analysis
        real_org_id = self._resolve_org_id(org_id, brand_id)
        dna = WinnerDNA(
            meta_ad_id=meta_ad_id,
            metrics=metrics,
            element_scores=element_scores,
            top_elements=top_elements,
            weak_elements=weak_elements,
            visual_properties=visual_properties,
            messaging=messaging,
            cohort_comparison=cohort_comparison,
            active_synergies=synergies,
            active_conflicts=conflicts,
        )

        self._store_analysis(dna, brand_id, real_org_id, "per_winner")
        return dna

    async def analyze_cross_winners(
        self,
        brand_id: str,
        org_id: str,
        top_n: int = 10,
        min_reward: float = 0.65,
    ) -> Optional[CrossWinnerAnalysis]:
        """Cross-winner pattern extraction.

        Args:
            brand_id: Brand UUID string.
            org_id: Organization UUID.
            top_n: Number of top winners to analyze.
            min_reward: Minimum reward score to qualify as winner.

        Returns:
            CrossWinnerAnalysis object, or None if insufficient winners.
        """
        # 1. Identify top winners
        winner_ads = self._find_top_winners(brand_id, top_n, min_reward)
        if len(winner_ads) < 3:
            logger.info(f"Only {len(winner_ads)} winners found for brand {brand_id}, need at least 3")
            return None

        # 2. Run per-winner DNA on each
        winner_dnas = []
        for ad in winner_ads:
            try:
                dna = await self.analyze_winner(ad["meta_ad_id"], brand_id, org_id)
                if dna:
                    winner_dnas.append(dna)
            except Exception as e:
                logger.warning(f"Failed to analyze winner {ad['meta_ad_id']}: {e}")

        if len(winner_dnas) < 3:
            return None

        # 3. Find common elements (>=70% frequency)
        common_elements = self._find_common_elements(winner_dnas)

        # 4. Find common visual traits
        common_visuals = self._find_common_visual_traits(winner_dnas)

        # 5. Anti-patterns (common in losers, absent in winners)
        anti_patterns = await self._identify_anti_patterns(winner_dnas, brand_id)

        # 6. Build iteration directions
        iteration_directions = self._build_iteration_directions(
            common_elements, common_visuals, anti_patterns, len(winner_dnas)
        )

        # 7. Build replication blueprint
        blueprint = self._build_replication_blueprint(
            common_elements, common_visuals, winner_dnas
        )

        real_org_id = self._resolve_org_id(org_id, brand_id)

        analysis = CrossWinnerAnalysis(
            winner_count=len(winner_dnas),
            common_elements=common_elements,
            common_visual_traits=common_visuals,
            anti_patterns=anti_patterns,
            iteration_directions=iteration_directions,
            replication_blueprint=blueprint,
            winner_dnas=winner_dnas,
        )

        # Store cross-winner analysis
        meta_ad_ids = [d.meta_ad_id for d in winner_dnas]
        self._store_cross_analysis(analysis, brand_id, real_org_id, meta_ad_ids)

        return analysis

    def build_action_brief(
        self, dna: WinnerDNA, opportunity: Optional[Dict] = None
    ) -> str:
        """Build a formatted action brief for a video winner.

        Args:
            dna: WinnerDNA from analyze_winner.
            opportunity: Optional IterationOpportunity dict for context.

        Returns:
            Formatted text brief.
        """
        lines = []
        lines.append(f"Ad: {dna.meta_ad_id}")

        # Performance
        m = dna.metrics
        perf_parts = []
        if m.get("roas"):
            perf_parts.append(f"ROAS: {m['roas']:.1f}x")
        if m.get("ctr"):
            perf_parts.append(f"CTR: {m['ctr']:.2f}%")
        if m.get("cpc"):
            perf_parts.append(f"CPC: ${m['cpc']:.2f}")
        if perf_parts:
            lines.append(" | ".join(perf_parts))

        if opportunity:
            lines.append(f"Pattern: {opportunity.get('pattern_label', '')}")

        # What's working
        lines.append("")
        lines.append("WHAT'S WORKING:")
        for elem in dna.top_elements[:3]:
            name = ELEMENT_DISPLAY_NAMES.get(elem.get("element"), elem.get("element", ""))
            val = elem.get("value", "")
            reward = elem.get("mean_reward", 0)
            pct = elem.get("percentile_rank", "")
            lines.append(f"  - {name}: \"{val}\" (reward {reward:.2f}, {pct})")

        if dna.active_synergies:
            for syn in dna.active_synergies[:2]:
                lines.append(f"  - Synergy: {syn.get('pair', '')} (+{syn.get('effect', 0):.0%} lift)")

        # What to change
        if dna.visual_properties or dna.weak_elements:
            lines.append("")
            lines.append("WHAT TO CHANGE:")

            if dna.visual_properties:
                vp = dna.visual_properties
                if vp.get("contrast_level") in ("low", "medium"):
                    lines.append(f"  - CONTRAST: Currently {vp['contrast_level'].upper()} \u2192 try HIGH")
                if vp.get("text_density") == "none":
                    lines.append("  - TEXT: No text overlay \u2192 add bold 3-word hook")
                if not vp.get("face_presence"):
                    lines.append("  - FACE: No face present \u2192 try face with eye contact")
                if vp.get("color_palette_type") in ("cool", "neutral", "monochrome"):
                    lines.append(f"  - COLOR: {vp['color_palette_type']} palette \u2192 try warm tones")

            for elem in dna.weak_elements[:2]:
                name = ELEMENT_DISPLAY_NAMES.get(elem.get("element"), elem.get("element", ""))
                val = elem.get("value", "")
                lines.append(f"  - {name}: \"{val}\" is underperforming")

        # Specific recommendations
        lines.append("")
        lines.append("RECOMMENDATIONS:")
        rec_num = 1
        if opportunity and opportunity.get("strategy_actions"):
            for action in opportunity["strategy_actions"][:3]:
                lines.append(f"  {rec_num}. {action}")
                rec_num += 1
        else:
            lines.append(f"  {rec_num}. Test variations of weakest elements while keeping top performers")
            rec_num += 1
            if dna.visual_properties:
                lines.append(f"  {rec_num}. Create image version using key visual + high contrast treatment")

        return "\n".join(lines)

    # ---------------------------------------------------------------------------
    # Per-winner helpers
    # ---------------------------------------------------------------------------

    def _get_ad_metrics(self, meta_ad_id: str, brand_id: str) -> Optional[Dict]:
        """Get aggregated performance metrics for an ad."""
        try:
            result = (
                self.supabase.table("meta_ads_performance")
                .select("spend, impressions, link_clicks, link_ctr, roas, purchases, purchase_value")
                .eq("meta_ad_id", meta_ad_id)
                .eq("brand_id", brand_id)
                .execute()
            )
            if not result.data:
                return None

            # Aggregate
            total_spend = sum(float(r.get("spend") or 0) for r in result.data)
            total_imps = sum(int(r.get("impressions") or 0) for r in result.data)
            total_clicks = sum(int(r.get("link_clicks") or 0) for r in result.data)
            total_purchases = sum(int(r.get("purchases") or 0) for r in result.data)
            total_value = sum(float(r.get("purchase_value") or 0) for r in result.data)

            return {
                "spend": total_spend,
                "impressions": total_imps,
                "link_clicks": total_clicks,
                "ctr": (total_clicks / total_imps * 100) if total_imps > 0 else 0,
                "cpc": (total_spend / total_clicks) if total_clicks > 0 else 0,
                "roas": (total_value / total_spend) if total_spend > 0 else 0,
                "purchases": total_purchases,
                "cpa": (total_spend / total_purchases) if total_purchases > 0 else 0,
                "conversion_rate": (total_purchases / total_clicks * 100) if total_clicks > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Failed to get metrics for {meta_ad_id}: {e}")
            return None

    def _get_classification(self, meta_ad_id: str, brand_id: str) -> Dict:
        """Get classification for an ad."""
        try:
            result = (
                self.supabase.table("ad_creative_classifications")
                .select("creative_format, creative_awareness_level, hook_type, primary_cta, creative_angle")
                .eq("meta_ad_id", meta_ad_id)
                .eq("brand_id", brand_id)
                .order("classified_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.warning(f"Failed to get classification for {meta_ad_id}: {e}")
            return {}

    def _find_generated_ad(self, meta_ad_id: str, brand_id: str) -> Optional[str]:
        """Find generated_ad_id for a meta ad."""
        try:
            result = (
                self.supabase.table("meta_ad_mapping")
                .select("generated_ad_id")
                .eq("meta_ad_id", meta_ad_id)
                .limit(1)
                .execute()
            )
            return result.data[0]["generated_ad_id"] if result.data else None
        except Exception as e:
            logger.warning(f"Failed to find generated ad for {meta_ad_id}: {e}")
            return None

    def _get_element_tags(self, generated_ad_id: str) -> Dict[str, str]:
        """Get element_tags from generated_ads."""
        try:
            result = (
                self.supabase.table("generated_ads")
                .select("element_tags")
                .eq("id", generated_ad_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0].get("element_tags") or {}
        except Exception as e:
            logger.warning(f"Failed to get element tags: {e}")
        return {}

    def _get_element_attribution(
        self, element_tags: Dict[str, str], brand_id: str
    ) -> List[Dict[str, Any]]:
        """Look up genome scores for each element in the ad's tags."""
        scores = []
        for elem_name, elem_value in element_tags.items():
            if elem_name in ("canvas_size", "content_source"):
                continue  # Skip non-creative elements

            try:
                result = (
                    self.supabase.table("creative_element_scores")
                    .select("mean_reward, total_observations, alpha, beta")
                    .eq("brand_id", brand_id)
                    .eq("element_name", elem_name)
                    .eq("element_value", elem_value)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    row = result.data[0]
                    obs = row.get("total_observations", 0) or 0

                    # Compute percentile rank among all values for this element
                    all_scores = (
                        self.supabase.table("creative_element_scores")
                        .select("mean_reward")
                        .eq("brand_id", brand_id)
                        .eq("element_name", elem_name)
                        .execute()
                    )
                    pct_rank = "n/a"
                    if all_scores.data:
                        all_rewards = sorted(r.get("mean_reward", 0) or 0 for r in all_scores.data)
                        current_reward = row.get("mean_reward", 0) or 0
                        below = sum(1 for r in all_rewards if r < current_reward)
                        pct_rank = f"top {100 - int(below / len(all_rewards) * 100)}%"

                    scores.append({
                        "element": elem_name,
                        "display_name": ELEMENT_DISPLAY_NAMES.get(elem_name, elem_name),
                        "value": elem_value,
                        "mean_reward": round(row.get("mean_reward", 0) or 0, 3),
                        "observations": obs,
                        "percentile_rank": pct_rank,
                    })
            except Exception as e:
                logger.warning(f"Failed to get score for {elem_name}={elem_value}: {e}")

        return scores

    async def _extract_visual_properties(
        self, meta_ad_id: str, brand_id: str, org_id: str
    ) -> Optional[Dict]:
        """Extract visual properties using VisualPropertyExtractor."""
        try:
            from viraltracker.services.visual_property_extractor import VisualPropertyExtractor
            extractor = VisualPropertyExtractor(self.supabase, self.gemini)
            return await extractor.extract(meta_ad_id, brand_id, org_id)
        except Exception as e:
            logger.warning(f"Visual extraction failed for {meta_ad_id}: {e}")
            return None

    def _build_messaging_profile(
        self, classification: Dict, element_tags: Dict
    ) -> Dict[str, Any]:
        """Build messaging profile from classification and element tags."""
        return {
            "hook_type": element_tags.get("hook_type") or classification.get("hook_type"),
            "awareness_level": classification.get("creative_awareness_level"),
            "creative_angle": classification.get("creative_angle"),
            "primary_cta": classification.get("primary_cta"),
            "creative_format": classification.get("creative_format"),
        }

    async def _compute_cohort_comparison(
        self, meta_ad_id: str, brand_id: str, metrics: Dict
    ) -> Dict[str, Any]:
        """Compare ad metrics against cohort baselines."""
        try:
            from viraltracker.services.ad_intelligence.baseline_service import BaselineService
            baseline_service = BaselineService(self.supabase)
            baseline = await baseline_service.get_baseline_for_ad(
                meta_ad_id=meta_ad_id,
                brand_id=UUID(brand_id),
            )
        except Exception as e:
            logger.warning(f"Failed to get baseline for cohort comparison: {e}")
            return {}

        if not baseline:
            return {}

        comparison = {}
        metric_map = {
            "ctr": ("p25_ctr", "median_ctr", "p75_ctr"),
            "roas": ("p25_roas", "median_roas", "p75_roas"),
            "cpc": ("p25_cpc", "median_cpc", "p75_cpc"),
            "conversion_rate": ("p25_conversion_rate", "median_conversion_rate", "p75_conversion_rate"),
        }

        for metric, (p25_field, p50_field, p75_field) in metric_map.items():
            value = metrics.get(metric)
            if value is None:
                continue

            p25 = getattr(baseline, p25_field, None)
            p50 = getattr(baseline, p50_field, None)
            p75 = getattr(baseline, p75_field, None)

            if p25 is None or p50 is None:
                continue

            # Determine verdict
            if value >= (p75 or float("inf")):
                verdict = "excellent"
            elif value >= p50:
                verdict = "above_average"
            elif value >= p25:
                verdict = "below_average"
            else:
                verdict = "poor"

            comparison[metric] = {
                "value": round(value, 4),
                "p25": round(p25, 4) if p25 else None,
                "median": round(p50, 4) if p50 else None,
                "p75": round(p75, 4) if p75 else None,
                "verdict": verdict,
            }

        return comparison

    def _get_interaction_effects(
        self, element_tags: Dict, brand_id: str
    ) -> tuple:
        """Get known interaction effects for the ad's element pairs."""
        synergies = []
        conflicts = []

        if len(element_tags) < 2:
            return synergies, conflicts

        # Build all pairs
        items = list(element_tags.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                name_a, val_a = items[i]
                name_b, val_b = items[j]

                # Canonical ordering
                if (name_a, val_a) > (name_b, val_b):
                    name_a, val_a, name_b, val_b = name_b, val_b, name_a, val_a

                try:
                    result = (
                        self.supabase.table("element_interactions")
                        .select("interaction_effect, effect_direction, sample_size, confidence_interval_low, confidence_interval_high")
                        .eq("brand_id", brand_id)
                        .eq("element_a_name", name_a)
                        .eq("element_a_value", val_a)
                        .eq("element_b_name", name_b)
                        .eq("element_b_value", val_b)
                        .limit(1)
                        .execute()
                    )
                    if result.data:
                        row = result.data[0]
                        effect = row.get("interaction_effect", 0) or 0
                        direction = row.get("effect_direction", "neutral")
                        entry = {
                            "pair": f"{name_a}:{val_a} + {name_b}:{val_b}",
                            "effect": round(effect, 3),
                            "direction": direction,
                            "sample_size": row.get("sample_size", 0),
                        }
                        if direction == "synergy":
                            synergies.append(entry)
                        elif direction == "conflict":
                            conflicts.append(entry)
                except Exception as e:
                    logger.debug(f"Interaction lookup skipped for {name_a}:{val_a} + {name_b}:{val_b}: {e}")

        synergies.sort(key=lambda s: s["effect"], reverse=True)
        conflicts.sort(key=lambda c: c["effect"])
        return synergies, conflicts

    # ---------------------------------------------------------------------------
    # Cross-winner helpers
    # ---------------------------------------------------------------------------

    def _find_top_winners(
        self, brand_id: str, top_n: int, min_reward: float
    ) -> List[Dict]:
        """Find top N winning ads by ROAS."""
        from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
        perf_service = AdPerformanceQueryService(self.supabase)

        result = perf_service.get_top_ads(
            brand_id=brand_id,
            sort_by="roas",
            days_back=30,
            limit=top_n * 2,  # Fetch more to filter
            min_spend=10.0,
        )

        ads = result.get("ads", [])
        # Filter to those with meaningful performance
        winners = [
            a for a in ads
            if a.get("roas", 0) > 1.0
            and a.get("impressions", 0) >= 1000
            and a.get("spend", 0) >= 10
        ][:top_n]

        return winners

    def _find_common_elements(self, dnas: List[WinnerDNA]) -> Dict[str, Any]:
        """Find elements common across winners (>=70% frequency).

        Uses both genome element_scores AND messaging properties from
        classifications, so non-generated ads still contribute patterns.
        """
        n = len(dnas)
        element_counter: Dict[str, Counter] = {}

        for dna in dnas:
            # From genome element_scores (generated ads only)
            for score in dna.element_scores:
                elem = score["element"]
                val = score["value"]
                if elem not in element_counter:
                    element_counter[elem] = Counter()
                element_counter[elem][val] += 1

            # From messaging profile (all ads — derived from classifications)
            messaging = dna.messaging or {}
            messaging_fields = {
                "hook_type": "Hook Style",
                "awareness_level": "Audience Awareness",
                "creative_format": "Creative Format",
                "creative_angle": "Creative Angle",
            }
            for field_key, display_name in messaging_fields.items():
                val = messaging.get(field_key)
                if val and field_key not in element_counter.get(field_key, Counter()):
                    # Only add from messaging if not already counted from element_scores
                    if field_key not in element_counter:
                        element_counter[field_key] = Counter()
                    # Check we haven't already counted this dna via element_scores
                    already_counted = any(
                        s["element"] == field_key for s in dna.element_scores
                    )
                    if not already_counted:
                        element_counter[field_key][val] += 1

        common = {}
        for elem, counter in element_counter.items():
            for val, count in counter.items():
                freq = count / n
                if freq >= COMMON_ELEMENT_THRESHOLD:
                    common[f"{elem}:{val}"] = {
                        "element": elem,
                        "display_name": ELEMENT_DISPLAY_NAMES.get(elem, elem.replace("_", " ").title()),
                        "value": val,
                        "frequency": round(freq, 2),
                        "count": count,
                        "total": n,
                    }

        return common

    def _find_common_visual_traits(self, dnas: List[WinnerDNA]) -> Dict[str, Any]:
        """Find visual traits common across winners."""
        n = len(dnas)
        trait_counters: Dict[str, Counter] = {}

        visual_fields = [
            "contrast_level", "color_palette_type", "text_density",
            "visual_hierarchy", "composition_style", "face_presence",
            "person_framing", "product_prominence", "headline_style",
        ]

        for dna in dnas:
            if not dna.visual_properties:
                continue
            for field in visual_fields:
                val = dna.visual_properties.get(field)
                if val is not None:
                    if field not in trait_counters:
                        trait_counters[field] = Counter()
                    trait_counters[field][str(val)] += 1

        # Count how many dnas have visual data
        n_with_visuals = sum(1 for d in dnas if d.visual_properties)
        if n_with_visuals < 3:
            return {}

        common = {}
        for field, counter in trait_counters.items():
            for val, count in counter.items():
                freq = count / n_with_visuals
                if freq >= COMMON_ELEMENT_THRESHOLD:
                    common[field] = {
                        "value": val,
                        "frequency": round(freq, 2),
                        "count": count,
                        "total": n_with_visuals,
                    }

        return common

    async def _identify_anti_patterns(
        self, winner_dnas: List[WinnerDNA], brand_id: str
    ) -> List[Dict[str, Any]]:
        """Find elements common in bottom performers but absent from winners."""
        # Get bottom performers
        from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
        perf_service = AdPerformanceQueryService(self.supabase)

        bottom_result = perf_service.get_top_ads(
            brand_id=brand_id,
            sort_by="roas",
            sort_order="asc",
            days_back=30,
            limit=15,
            min_spend=10.0,
        )
        bottom_ads = bottom_result.get("ads", [])

        # Collect elements from bottom performers
        loser_elements: Counter = Counter()
        loser_count = 0
        for ad in bottom_ads:
            gen_id = self._find_generated_ad(ad["meta_ad_id"], brand_id)
            if not gen_id:
                continue
            tags = self._get_element_tags(gen_id)
            if not tags:
                continue
            loser_count += 1
            for elem, val in tags.items():
                if elem in ("canvas_size", "content_source"):
                    continue
                loser_elements[f"{elem}:{val}"] += 1

        if loser_count < 3:
            return []

        # Collect winner element set
        winner_element_set = set()
        for dna in winner_dnas:
            for score in dna.element_scores:
                winner_element_set.add(f"{score['element']}:{score['value']}")

        # Find anti-patterns: common in losers, absent in winners
        anti_patterns = []
        for elem_key, count in loser_elements.items():
            loser_freq = count / loser_count
            if loser_freq >= 0.3 and elem_key not in winner_element_set:
                parts = elem_key.split(":", 1)
                anti_patterns.append({
                    "element": parts[0] if len(parts) > 0 else elem_key,
                    "value": parts[1] if len(parts) > 1 else "",
                    "loser_frequency": round(loser_freq, 2),
                    "loser_count": count,
                    "total_losers": loser_count,
                    "winner_count": 0,
                })

        anti_patterns.sort(key=lambda a: a["loser_frequency"], reverse=True)
        return anti_patterns[:10]

    def _build_iteration_directions(
        self,
        common_elements: Dict,
        common_visuals: Dict,
        anti_patterns: List,
        winner_count: int,
    ) -> List[Dict[str, Any]]:
        """Build actionable iteration directions from analysis."""
        directions = []

        # From common elements
        for key, elem in common_elements.items():
            directions.append({
                "direction": f"Use {elem['display_name']}: \"{elem['value']}\"",
                "confidence": elem["frequency"],
                "rationale": f"{elem['count']}/{elem['total']} winners use this",
                "source": "element",
            })

        # From common visuals
        for field, trait in common_visuals.items():
            label = field.replace("_", " ").title()
            directions.append({
                "direction": f"{label}: {trait['value']}",
                "confidence": trait["frequency"],
                "rationale": f"{trait['count']}/{trait['total']} winners share this",
                "source": "visual",
            })

        # From anti-patterns (negative direction)
        for ap in anti_patterns[:3]:
            elem_name = ELEMENT_DISPLAY_NAMES.get(ap["element"], ap["element"])
            directions.append({
                "direction": f"Avoid {elem_name}: \"{ap['value']}\"",
                "confidence": ap["loser_frequency"],
                "rationale": f"Common in losers ({ap['loser_count']}/{ap['total_losers']}), absent in winners",
                "source": "anti_pattern",
            })

        directions.sort(key=lambda d: d["confidence"], reverse=True)
        return directions

    def _build_replication_blueprint(
        self,
        common_elements: Dict,
        common_visuals: Dict,
        winner_dnas: List[WinnerDNA],
    ) -> Dict[str, Any]:
        """Build a replication blueprint combining element and visual directives."""
        blueprint = {
            "element_combo": {},
            "visual_directives": {},
            "messaging_directives": {},
        }

        # Element combo from common elements
        for key, elem in common_elements.items():
            blueprint["element_combo"][elem["element"]] = elem["value"]

        # Visual directives from common visuals
        for field, trait in common_visuals.items():
            blueprint["visual_directives"][field] = trait["value"]

        # Messaging from most common hook_type/awareness
        hook_counter = Counter()
        awareness_counter = Counter()
        for dna in winner_dnas:
            ht = dna.messaging.get("hook_type")
            al = dna.messaging.get("awareness_level")
            if ht:
                hook_counter[ht] += 1
            if al:
                awareness_counter[al] += 1

        if hook_counter:
            most_common_hook = hook_counter.most_common(1)[0]
            blueprint["messaging_directives"]["hook_type"] = most_common_hook[0]
        if awareness_counter:
            most_common_awareness = awareness_counter.most_common(1)[0]
            blueprint["messaging_directives"]["awareness_level"] = most_common_awareness[0]

        return blueprint

    # ---------------------------------------------------------------------------
    # Storage
    # ---------------------------------------------------------------------------

    def _store_analysis(
        self, dna: WinnerDNA, brand_id: str, org_id: str, analysis_type: str
    ) -> None:
        """Store a per-winner DNA analysis."""
        try:
            row = {
                "organization_id": org_id,
                "brand_id": brand_id,
                "analysis_type": analysis_type,
                "meta_ad_ids": [dna.meta_ad_id],
                "element_scores": json.dumps(dna.element_scores),
                "top_elements": json.dumps(dna.top_elements),
                "weak_elements": json.dumps(dna.weak_elements),
                "visual_properties": json.dumps(dna.visual_properties) if dna.visual_properties else None,
                "messaging_properties": json.dumps(dna.messaging),
                "cohort_comparison": json.dumps(dna.cohort_comparison),
                "active_synergies": json.dumps(dna.active_synergies),
                "active_conflicts": json.dumps(dna.active_conflicts),
            }
            self.supabase.table("winner_dna_analyses").insert(row).execute()
        except Exception as e:
            logger.warning(f"Failed to store DNA analysis: {e}")

    def _store_cross_analysis(
        self, analysis: CrossWinnerAnalysis, brand_id: str, org_id: str, meta_ad_ids: List[str]
    ) -> None:
        """Store a cross-winner analysis."""
        try:
            row = {
                "organization_id": org_id,
                "brand_id": brand_id,
                "analysis_type": "cross_winner",
                "meta_ad_ids": meta_ad_ids,
                "common_elements": json.dumps(analysis.common_elements),
                "common_visual_traits": json.dumps(analysis.common_visual_traits),
                "anti_patterns": json.dumps(analysis.anti_patterns),
                "iteration_directions": json.dumps(analysis.iteration_directions),
                "replication_blueprint": json.dumps(analysis.replication_blueprint),
            }
            self.supabase.table("winner_dna_analyses").insert(row).execute()
        except Exception as e:
            logger.warning(f"Failed to store cross-winner analysis: {e}")

    def _resolve_org_id(self, org_id: str, brand_id: str) -> str:
        """Resolve 'all' org_id to real UUID."""
        if org_id != "all":
            return org_id
        try:
            row = (
                self.supabase.table("brands")
                .select("organization_id")
                .eq("id", str(brand_id))
                .limit(1)
                .execute()
            )
            if row.data:
                return row.data[0]["organization_id"]
        except Exception as e:
            logger.warning(f"Failed to resolve org_id: {e}")
        return org_id
