"""
V2 Congruence Service - Headline ↔ offer variant ↔ LP hero alignment scoring.

Scores congruence across 3 dimensions using Claude:
- offer_alignment: headline ↔ offer variant pain points/benefits
- hero_alignment: headline ↔ LP hero headline/subheadline (if available)
- belief_alignment: headline ↔ belief statement (if belief_first mode)

Returns CongruenceResult with per-dimension scores and optional adapted headline.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Threshold below which a headline is considered misaligned
CONGRUENCE_THRESHOLD = 0.6


def _sanitize_dashes(text: str) -> str:
    """Replace em dashes and en dashes with regular dashes/commas."""
    text = text.replace("\u2014", " - ")   # em dash
    text = text.replace("\u2013", "-")     # en dash
    return text


@dataclass
class CongruenceResult:
    """Result from congruence check for a single headline.

    Attributes:
        headline: Original headline text.
        offer_alignment: Score 0-1 for headline ↔ offer variant alignment.
        hero_alignment: Score 0-1 for headline ↔ LP hero alignment. None if no LP data.
        belief_alignment: Score 0-1 for headline ↔ belief statement. None if not belief mode.
        overall_score: Weighted average of available dimensions.
        adapted_headline: Suggested replacement if overall_score < threshold. None otherwise.
        dimensions_scored: Number of dimensions that were scored (1-3).
    """
    headline: str
    offer_alignment: Optional[float] = None
    hero_alignment: Optional[float] = None
    belief_alignment: Optional[float] = None
    overall_score: float = 1.0
    adapted_headline: Optional[str] = None
    dimensions_scored: int = 0


class CongruenceService:
    """Scores headline congruence against offer variant, LP hero, and belief data."""

    async def check_congruence(
        self,
        headline: str,
        offer_variant_data: Optional[Dict[str, Any]] = None,
        lp_hero_data: Optional[Dict[str, Any]] = None,
        belief_data: Optional[Dict[str, Any]] = None,
    ) -> CongruenceResult:
        """Score congruence of a headline against available context.

        If below threshold and enough context is available, returns an
        adapted headline suggestion.

        Args:
            headline: The hook/headline text to evaluate.
            offer_variant_data: Offer variant dict with pain_points, benefits,
                target_audience, landing_page_url.
            lp_hero_data: Landing page hero dict with hero_headline,
                hero_subheadline, key_claims.
            belief_data: Belief/angle dict with belief_statement, jtbd.

        Returns:
            CongruenceResult with per-dimension scores.
        """
        if not offer_variant_data and not lp_hero_data and not belief_data:
            # No context to compare against — neutral pass-through
            return CongruenceResult(
                headline=headline,
                overall_score=1.0,
                dimensions_scored=0,
            )

        try:
            scores = await self._score_with_llm(
                headline, offer_variant_data, lp_hero_data, belief_data
            )
        except Exception as e:
            logger.warning(f"Congruence LLM call failed, returning neutral: {e}")
            return CongruenceResult(
                headline=headline,
                overall_score=1.0,
                dimensions_scored=0,
            )

        # Compute weighted overall from available dimensions
        scored_values: List[float] = []
        offer_alignment = scores.get("offer_alignment")
        hero_alignment = scores.get("hero_alignment")
        belief_alignment = scores.get("belief_alignment")

        if offer_alignment is not None:
            scored_values.append(offer_alignment)
        if hero_alignment is not None:
            scored_values.append(hero_alignment)
        if belief_alignment is not None:
            scored_values.append(belief_alignment)

        overall = sum(scored_values) / len(scored_values) if scored_values else 1.0

        adapted_headline = None
        if overall < CONGRUENCE_THRESHOLD and scores.get("adapted_headline"):
            adapted_headline = scores["adapted_headline"]

        return CongruenceResult(
            headline=headline,
            offer_alignment=offer_alignment,
            hero_alignment=hero_alignment,
            belief_alignment=belief_alignment,
            overall_score=round(overall, 3),
            adapted_headline=adapted_headline,
            dimensions_scored=len(scored_values),
        )

    async def check_congruence_batch(
        self,
        hooks: List[Dict[str, Any]],
        offer_variant_data: Optional[Dict[str, Any]] = None,
        lp_hero_data: Optional[Dict[str, Any]] = None,
        belief_data: Optional[Dict[str, Any]] = None,
    ) -> List[CongruenceResult]:
        """Check congruence for multiple hooks in a single LLM call.

        Batches all hooks into one prompt to reduce latency.

        Args:
            hooks: List of hook dicts with 'hook_text' key.
            offer_variant_data: Offer variant dict.
            lp_hero_data: LP hero dict.
            belief_data: Belief/angle dict.

        Returns:
            List of CongruenceResult, parallel to input hooks.
        """
        if not hooks:
            return []

        if not offer_variant_data and not lp_hero_data and not belief_data:
            return [
                CongruenceResult(
                    headline=h.get("adapted_text") or h.get("hook_text") or h.get("text", ""),
                    overall_score=1.0,
                    dimensions_scored=0,
                )
                for h in hooks
            ]

        try:
            results = await self._score_batch_with_llm(
                hooks, offer_variant_data, lp_hero_data, belief_data
            )
            return results
        except Exception as e:
            logger.warning(f"Batch congruence LLM call failed, returning neutral: {e}")
            return [
                CongruenceResult(
                    headline=h.get("adapted_text") or h.get("hook_text") or h.get("text", ""),
                    overall_score=1.0,
                    dimensions_scored=0,
                )
                for h in hooks
            ]

    async def _score_with_llm(
        self,
        headline: str,
        offer_variant_data: Optional[Dict[str, Any]],
        lp_hero_data: Optional[Dict[str, Any]],
        belief_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Call Claude to score congruence dimensions."""
        from pydantic_ai import Agent
        from viraltracker.core.config import Config

        prompt = self._build_prompt(
            [headline], offer_variant_data, lp_hero_data, belief_data
        )

        agent = Agent(
            f"anthropic:{Config.CLAUDE_SONNET_MODEL}",
            system_prompt="You are a direct-response advertising congruence evaluator. Score alignment precisely.",
        )

        result = await agent.run(prompt)
        return self._parse_single_result(result.output)

    async def _score_batch_with_llm(
        self,
        hooks: List[Dict[str, Any]],
        offer_variant_data: Optional[Dict[str, Any]],
        lp_hero_data: Optional[Dict[str, Any]],
        belief_data: Optional[Dict[str, Any]],
    ) -> List[CongruenceResult]:
        """Call Claude to score congruence for a batch of headlines."""
        from pydantic_ai import Agent
        from viraltracker.core.config import Config

        headlines = [h.get("adapted_text") or h.get("hook_text") or h.get("text", "") for h in hooks]
        prompt = self._build_prompt(
            headlines, offer_variant_data, lp_hero_data, belief_data
        )

        agent = Agent(
            f"anthropic:{Config.CLAUDE_SONNET_MODEL}",
            system_prompt="You are a direct-response advertising congruence evaluator. Score alignment precisely.",
        )

        result = await agent.run(prompt)
        return self._parse_batch_result(result.output, headlines)

    def _build_prompt(
        self,
        headlines: List[str],
        offer_variant_data: Optional[Dict[str, Any]],
        lp_hero_data: Optional[Dict[str, Any]],
        belief_data: Optional[Dict[str, Any]],
    ) -> str:
        """Build congruence evaluation prompt."""
        dimensions = []

        context_sections = []
        if offer_variant_data:
            context_sections.append(
                f"OFFER VARIANT:\n"
                f"- Pain points: {offer_variant_data.get('pain_points', 'N/A')}\n"
                f"- Benefits: {offer_variant_data.get('benefits', 'N/A')}\n"
                f"- Target audience: {offer_variant_data.get('target_audience', 'N/A')}"
            )
            dimensions.append(
                '"offer_alignment": float 0.0-1.0 (how well headline addresses offer pain points/benefits)'
            )

        if lp_hero_data:
            context_sections.append(
                f"LANDING PAGE HERO:\n"
                f"- Headline: {lp_hero_data.get('hero_headline', 'N/A')}\n"
                f"- Subheadline: {lp_hero_data.get('hero_subheadline', 'N/A')}\n"
                f"- Key claims: {lp_hero_data.get('key_claims', 'N/A')}"
            )
            dimensions.append(
                '"hero_alignment": float 0.0-1.0 (how well headline matches LP hero messaging)'
            )

        if belief_data:
            context_sections.append(
                f"BELIEF/ANGLE:\n"
                f"- Belief statement: {belief_data.get('belief_statement', 'N/A')}\n"
                f"- JTBD: {belief_data.get('jtbd', 'N/A')}"
            )
            dimensions.append(
                '"belief_alignment": float 0.0-1.0 (how well headline reinforces the belief)'
            )

        headlines_block = "\n".join(
            f"  {i+1}. \"{h}\"" for i, h in enumerate(headlines)
        )

        return f"""Score the congruence of these ad headlines against the provided context.

CONTEXT:
{chr(10).join(context_sections)}

HEADLINES:
{headlines_block}

For EACH headline, return a JSON object with:
{chr(10).join(f"  - {d}" for d in dimensions)}
  - "adapted_headline": string or null (suggested rewrite if any score < 0.6)

When suggesting adapted_headline rewrites, NEVER use em dashes (\u2014). Use commas, periods, or dashes (-) instead.

Return a JSON array of objects, one per headline, in the same order.
Only return the JSON array, no other text.
"""

    def _parse_single_result(self, raw_output: str) -> Dict[str, Any]:
        """Parse LLM output for a single headline."""
        try:
            text = raw_output.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 0:
                result = parsed[0]
            elif isinstance(parsed, dict):
                result = parsed
            else:
                return {}
            # Sanitize adapted_headline
            if result.get("adapted_headline"):
                result["adapted_headline"] = _sanitize_dashes(result["adapted_headline"])
            return result
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse congruence result: {e}")
            return {}

    def _parse_batch_result(
        self,
        raw_output: str,
        headlines: List[str],
    ) -> List[CongruenceResult]:
        """Parse LLM output for batch headlines."""
        try:
            text = raw_output.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            parsed = json.loads(text)
            if not isinstance(parsed, list):
                parsed = [parsed]
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse batch congruence result: {e}")
            return [
                CongruenceResult(headline=h, overall_score=1.0, dimensions_scored=0)
                for h in headlines
            ]

        results = []
        for i, headline in enumerate(headlines):
            if i < len(parsed):
                scores = parsed[i] if isinstance(parsed[i], dict) else {}
            else:
                scores = {}

            scored_values: List[float] = []
            offer_alignment = self._safe_float(scores.get("offer_alignment"))
            hero_alignment = self._safe_float(scores.get("hero_alignment"))
            belief_alignment = self._safe_float(scores.get("belief_alignment"))

            if offer_alignment is not None:
                scored_values.append(offer_alignment)
            if hero_alignment is not None:
                scored_values.append(hero_alignment)
            if belief_alignment is not None:
                scored_values.append(belief_alignment)

            overall = sum(scored_values) / len(scored_values) if scored_values else 1.0

            adapted = None
            if overall < CONGRUENCE_THRESHOLD and scores.get("adapted_headline"):
                adapted = _sanitize_dashes(scores["adapted_headline"])

            results.append(CongruenceResult(
                headline=headline,
                offer_alignment=offer_alignment,
                hero_alignment=hero_alignment,
                belief_alignment=belief_alignment,
                overall_score=round(overall, 3),
                adapted_headline=adapted,
                dimensions_scored=len(scored_values),
            ))

        return results

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            f = float(value)
            return max(0.0, min(1.0, f))
        except (ValueError, TypeError):
            return None
