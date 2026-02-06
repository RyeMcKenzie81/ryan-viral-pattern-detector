"""CongruenceAnalyzer: Per-dimension congruence evaluation.

Evaluates alignment between video content, ad copy, and landing page
across 5 dimensions:
1. Awareness alignment - video ↔ copy ↔ LP awareness levels
2. Hook ↔ headline - video hook vs LP headline/subhead
3. Benefits match - video benefits vs LP benefits
4. Messaging angle - video angle vs LP angle
5. Claims consistency - video claims vs LP claims

Each dimension produces:
- assessment: aligned | weak | missing
- explanation: Why this assessment was given
- suggestion: How to improve (if weak/missing)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# Congruence analysis prompt - evaluates all 5 dimensions
CONGRUENCE_ANALYSIS_PROMPT = """Analyze the congruence between video ad content and landing page.

**VIDEO AD DATA:**
- Awareness Level: {video_awareness}
- Hook (Spoken): {hook_spoken}
- Hook (Overlay): {hook_overlay}
- Hook (Visual): {hook_visual}
- Benefits Shown: {video_benefits}
- Angles Used: {video_angles}
- Claims Made: {video_claims}
- Pain Points Addressed: {video_pain_points}

**AD COPY DATA:**
- Copy Awareness Level: {copy_awareness}
- Primary CTA: {primary_cta}

**LANDING PAGE DATA:**
- Page Title: {lp_title}
- Product Name: {lp_product_name}
- Benefits Listed: {lp_benefits}
- Features Listed: {lp_features}
- Call to Action: {lp_cta}
- Headline/First Content: {lp_headline}

**EVALUATE THESE 5 DIMENSIONS:**

1. **awareness_alignment**: Is the awareness level consistent across video, copy, and LP?
   - "aligned" = same level or 1-step difference
   - "weak" = 2-step difference
   - "missing" = 3+ step difference or can't evaluate

2. **hook_headline**: Does the video hook message match the LP headline/subhead?
   - "aligned" = same core message/promise
   - "weak" = related but different emphasis
   - "missing" = completely different messages

3. **benefits_match**: Are the benefits shown in video also emphasized on LP?
   - "aligned" = most benefits appear on both
   - "weak" = some benefits missing from LP
   - "missing" = LP doesn't feature the video's benefits

4. **messaging_angle**: Is the video's framing/angle consistent with LP messaging?
   - "aligned" = same angle/framing approach
   - "weak" = similar but different emphasis
   - "missing" = completely different angles

5. **claims_consistency**: Are video claims supported on LP (no promise drop-off)?
   - "aligned" = claims are reinforced on LP
   - "weak" = some claims not supported
   - "missing" = LP contradicts or ignores video claims

**RETURN JSON ONLY:**
```json
[
  {{
    "dimension": "awareness_alignment",
    "assessment": "aligned|weak|missing",
    "explanation": "Brief explanation of the assessment",
    "suggestion": "Actionable suggestion if weak/missing, null if aligned"
  }},
  {{
    "dimension": "hook_headline",
    "assessment": "aligned|weak|missing",
    "explanation": "...",
    "suggestion": "..."
  }},
  {{
    "dimension": "benefits_match",
    "assessment": "aligned|weak|missing",
    "explanation": "...",
    "suggestion": "..."
  }},
  {{
    "dimension": "messaging_angle",
    "assessment": "aligned|weak|missing",
    "explanation": "...",
    "suggestion": "..."
  }},
  {{
    "dimension": "claims_consistency",
    "assessment": "aligned|weak|missing",
    "explanation": "...",
    "suggestion": "..."
  }}
]
```

Return ONLY the JSON array, no other text.
"""


@dataclass
class CongruenceComponent:
    """A single dimension of congruence evaluation."""
    dimension: str
    assessment: str  # aligned | weak | missing | unevaluated
    explanation: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "dimension": self.dimension,
            "assessment": self.assessment,
            "explanation": self.explanation,
            "suggestion": self.suggestion,
        }


@dataclass
class CongruenceResult:
    """Full congruence analysis result."""
    components: List[CongruenceComponent] = field(default_factory=list)
    overall_score: Optional[float] = None
    model_used: Optional[str] = None
    error: Optional[str] = None

    def to_components_list(self) -> List[Dict[str, Any]]:
        """Convert components to list of dicts for storage."""
        return [c.to_dict() for c in self.components]


class CongruenceAnalyzer:
    """Analyzes congruence between video, copy, and landing page.

    Evaluates 5 dimensions of alignment and provides actionable
    suggestions for improvement.
    """

    # Weights for computing overall score
    DIMENSION_WEIGHTS = {
        "awareness_alignment": 0.25,
        "hook_headline": 0.25,
        "benefits_match": 0.20,
        "messaging_angle": 0.15,
        "claims_consistency": 0.15,
    }

    # Assessment scores
    ASSESSMENT_SCORES = {
        "aligned": 1.0,
        "weak": 0.5,
        "missing": 0.0,
        "unevaluated": None,  # Don't count in score
    }

    def __init__(self, gemini_service=None):
        """Initialize CongruenceAnalyzer.

        Args:
            gemini_service: Optional GeminiService instance. If not provided,
                will create one when needed.
        """
        self._gemini = gemini_service

    async def analyze_congruence(
        self,
        video_data: Dict[str, Any],
        copy_data: Dict[str, Any],
        lp_data: Optional[Dict[str, Any]],
    ) -> CongruenceResult:
        """Analyze congruence across all dimensions.

        Args:
            video_data: Video analysis data (from ad_video_analysis).
            copy_data: Copy classification data (from ad_creative_classifications).
            lp_data: Landing page data (from brand_landing_pages). May be None.

        Returns:
            CongruenceResult with per-dimension assessments.
        """
        # Handle missing LP data
        if not lp_data:
            return self._create_unevaluated_result(
                "No landing page data available"
            )

        # Handle missing video data
        if not video_data or not video_data.get("awareness_level"):
            return self._create_unevaluated_result(
                "No video analysis data available"
            )

        try:
            # Build prompt with all available data
            prompt = self._build_prompt(video_data, copy_data, lp_data)

            # Call Gemini for analysis
            response_text = await self._call_gemini(prompt)

            # Parse response
            components = self._parse_response(response_text)

            if not components:
                return CongruenceResult(
                    components=self._create_default_components("Failed to parse analysis"),
                    error="Failed to parse Gemini response",
                )

            # Compute overall score
            overall_score = self._compute_overall_score(components)

            return CongruenceResult(
                components=components,
                overall_score=overall_score,
                model_used="gemini-2.5-flash",
            )

        except Exception as e:
            logger.error(f"Congruence analysis failed: {e}")
            return CongruenceResult(
                components=self._create_default_components(f"Error: {str(e)[:100]}"),
                error=str(e),
            )

    def _build_prompt(
        self,
        video_data: Dict[str, Any],
        copy_data: Dict[str, Any],
        lp_data: Dict[str, Any],
    ) -> str:
        """Build the analysis prompt with all data.

        Args:
            video_data: Video analysis data.
            copy_data: Copy classification data.
            lp_data: Landing page data.

        Returns:
            Formatted prompt string.
        """
        # Extract video data
        video_awareness = video_data.get("awareness_level", "unknown")
        hook_spoken = video_data.get("hook_transcript_spoken", "")
        hook_overlay = video_data.get("hook_transcript_overlay", "")
        hook_visual = video_data.get("hook_visual_description", "")
        video_benefits = video_data.get("benefits_shown", [])
        video_angles = video_data.get("angles_used", [])
        video_claims = video_data.get("claims_made", [])
        video_pain_points = video_data.get("pain_points_addressed", [])

        # Extract copy data
        copy_awareness = copy_data.get("copy_awareness_level", "unknown")
        primary_cta = copy_data.get("primary_cta", "")

        # Extract LP data
        lp_title = lp_data.get("page_title", "")
        lp_product_name = lp_data.get("product_name", "")
        lp_benefits = lp_data.get("benefits", [])
        lp_features = lp_data.get("features", [])
        lp_cta = lp_data.get("call_to_action", "")

        # Extract headline from raw_markdown or extracted_data
        lp_headline = self._extract_lp_headline(lp_data)

        # Format lists for prompt
        video_benefits_str = ", ".join(video_benefits) if video_benefits else "None extracted"
        video_angles_str = ", ".join(video_angles) if video_angles else "None extracted"
        video_claims_str = self._format_claims(video_claims)
        video_pain_points_str = ", ".join(video_pain_points) if video_pain_points else "None extracted"
        lp_benefits_str = ", ".join(lp_benefits) if lp_benefits else "None extracted"
        lp_features_str = ", ".join(lp_features) if lp_features else "None extracted"

        return CONGRUENCE_ANALYSIS_PROMPT.format(
            video_awareness=video_awareness,
            hook_spoken=hook_spoken or "None",
            hook_overlay=hook_overlay or "None",
            hook_visual=hook_visual or "None",
            video_benefits=video_benefits_str,
            video_angles=video_angles_str,
            video_claims=video_claims_str,
            video_pain_points=video_pain_points_str,
            copy_awareness=copy_awareness,
            primary_cta=primary_cta or "None",
            lp_title=lp_title or "Unknown",
            lp_product_name=lp_product_name or "Unknown",
            lp_benefits=lp_benefits_str,
            lp_features=lp_features_str,
            lp_cta=lp_cta or "None",
            lp_headline=lp_headline or "Unknown",
        )

    def _extract_lp_headline(self, lp_data: Dict[str, Any]) -> str:
        """Extract headline/first content from LP data.

        Args:
            lp_data: Landing page data dict.

        Returns:
            Headline or first content excerpt.
        """
        # Try extracted_data first
        extracted = lp_data.get("extracted_data", {})
        if isinstance(extracted, dict):
            if extracted.get("headline"):
                return extracted["headline"]
            if extracted.get("h1"):
                return extracted["h1"]

        # Try page_title
        if lp_data.get("page_title"):
            return lp_data["page_title"]

        # Try raw_markdown - get first meaningful line
        raw_md = lp_data.get("raw_markdown", "")
        if raw_md:
            # Find first heading or substantial line
            lines = raw_md.split("\n")
            for line in lines[:20]:  # Check first 20 lines
                line = line.strip()
                if line.startswith("#"):
                    return line.lstrip("#").strip()
                if len(line) > 20 and not line.startswith("["):
                    return line[:200]

        return ""

    def _format_claims(self, claims: List[Dict]) -> str:
        """Format claims list for prompt.

        Args:
            claims: List of claim dicts.

        Returns:
            Formatted string.
        """
        if not claims:
            return "None extracted"

        claim_texts = []
        for c in claims[:5]:  # Limit to 5 claims
            if isinstance(c, dict):
                claim_texts.append(c.get("claim", str(c)))
            else:
                claim_texts.append(str(c))

        return "; ".join(claim_texts)

    async def _call_gemini(self, prompt: str) -> str:
        """Call Gemini API for analysis.

        Args:
            prompt: Analysis prompt.

        Returns:
            Response text.
        """
        try:
            from google import genai

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set")

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )

            return response.text.strip() if response.text else ""

        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise

    def _parse_response(self, text: str) -> List[CongruenceComponent]:
        """Parse Gemini JSON response.

        Args:
            text: Raw response text.

        Returns:
            List of CongruenceComponent objects.
        """
        if not text:
            return []

        # Extract JSON from markdown code block if present
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            text = json_match.group(1)

        try:
            data = json.loads(text)
            if not isinstance(data, list):
                return []

            components = []
            for item in data:
                if not isinstance(item, dict):
                    continue

                component = CongruenceComponent(
                    dimension=item.get("dimension", "unknown"),
                    assessment=self._normalize_assessment(item.get("assessment", "unevaluated")),
                    explanation=item.get("explanation", ""),
                    suggestion=item.get("suggestion"),
                )
                components.append(component)

            return components

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse congruence response: {e}")
            return []

    def _normalize_assessment(self, value: str) -> str:
        """Normalize assessment value.

        Args:
            value: Raw assessment string.

        Returns:
            Normalized value (aligned|weak|missing|unevaluated).
        """
        if not value:
            return "unevaluated"

        value = value.lower().strip()
        if value in ("aligned", "strong", "good", "match"):
            return "aligned"
        elif value in ("weak", "partial", "moderate"):
            return "weak"
        elif value in ("missing", "none", "poor", "no match", "mismatch"):
            return "missing"
        else:
            return "unevaluated"

    def _compute_overall_score(
        self,
        components: List[CongruenceComponent],
    ) -> Optional[float]:
        """Compute weighted overall congruence score.

        Args:
            components: List of CongruenceComponent objects.

        Returns:
            Overall score (0.0-1.0) or None if can't compute.
        """
        total_weight = 0.0
        weighted_sum = 0.0

        for comp in components:
            weight = self.DIMENSION_WEIGHTS.get(comp.dimension, 0.1)
            score = self.ASSESSMENT_SCORES.get(comp.assessment)

            if score is not None:
                weighted_sum += score * weight
                total_weight += weight

        if total_weight == 0:
            return None

        return round(weighted_sum / total_weight, 3)

    def _create_unevaluated_result(self, reason: str) -> CongruenceResult:
        """Create result when evaluation is not possible.

        Args:
            reason: Why evaluation couldn't be done.

        Returns:
            CongruenceResult with unevaluated components.
        """
        return CongruenceResult(
            components=self._create_default_components(reason),
            overall_score=None,
            error=reason,
        )

    def _create_default_components(self, reason: str) -> List[CongruenceComponent]:
        """Create default unevaluated components.

        Args:
            reason: Explanation for unevaluated status.

        Returns:
            List of CongruenceComponent objects.
        """
        dimensions = [
            "awareness_alignment",
            "hook_headline",
            "benefits_match",
            "messaging_angle",
            "claims_consistency",
        ]

        return [
            CongruenceComponent(
                dimension=dim,
                assessment="unevaluated",
                explanation=reason,
                suggestion=None,
            )
            for dim in dimensions
        ]

    def compute_awareness_gap(
        self,
        video_awareness: Optional[str],
        copy_awareness: Optional[str],
        lp_awareness: Optional[str],
    ) -> Dict[str, Any]:
        """Compute simple awareness level gap (programmatic, no LLM).

        This is a quick check that can be run without LLM calls.

        Args:
            video_awareness: Video awareness level.
            copy_awareness: Copy awareness level.
            lp_awareness: LP awareness level (optional).

        Returns:
            Dict with gap_size, assessment, and explanation.
        """
        ordinal = {
            "unaware": 1,
            "problem_aware": 2,
            "solution_aware": 3,
            "product_aware": 4,
            "most_aware": 5,
        }

        video_ord = ordinal.get(video_awareness, 0)
        copy_ord = ordinal.get(copy_awareness, 0)
        lp_ord = ordinal.get(lp_awareness, 0) if lp_awareness else None

        if video_ord == 0 or copy_ord == 0:
            return {
                "gap_size": None,
                "assessment": "unevaluated",
                "explanation": "Missing awareness level data",
            }

        # Compute gaps
        gaps = [abs(video_ord - copy_ord)]
        if lp_ord:
            gaps.append(abs(video_ord - lp_ord))
            gaps.append(abs(copy_ord - lp_ord))

        max_gap = max(gaps)

        if max_gap == 0:
            assessment = "aligned"
            explanation = "Perfect awareness alignment across all elements"
        elif max_gap == 1:
            assessment = "aligned"
            explanation = "Good alignment (1-step gap)"
        elif max_gap == 2:
            assessment = "weak"
            explanation = f"Moderate misalignment ({max_gap}-step gap)"
        else:
            assessment = "missing"
            explanation = f"Significant misalignment ({max_gap}-step gap)"

        return {
            "gap_size": max_gap,
            "assessment": assessment,
            "explanation": explanation,
        }
