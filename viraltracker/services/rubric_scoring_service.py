"""
Rubric Scoring Service — scores ads against the 10-gate creative effectiveness rubric.

Supports multi-model scoring (Claude Opus, Claude Sonnet, Gemini) for comparison testing
and production use. Includes back-testing against ad performance data.

Gates:
  0: Format & Native Camouflage (12%)
  1: Pattern Interrupt (11%)
  2: Visual Engagement (7%)
  3: Message & Hook (12%)
  4: Emotional Activation (16%)
  5: Credibility Architecture (10%)
  6: Desire Amplification (9%)
  7: Action Engineering (4%)
  8: Algorithmic Resonance (11%)
  9: Strategic Distinction (8%)
"""

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from viraltracker.core.config import Config

logger = logging.getLogger(__name__)

# Gate weights (sum to 100%)
GATE_WEIGHTS = {
    0: 0.12,  # Format & Native Camouflage
    1: 0.11,  # Pattern Interrupt
    2: 0.07,  # Visual Engagement
    3: 0.12,  # Message & Hook
    4: 0.16,  # Emotional Activation
    5: 0.10,  # Credibility Architecture
    6: 0.09,  # Desire Amplification
    7: 0.04,  # Action Engineering
    8: 0.11,  # Algorithmic Resonance
    9: 0.08,  # Strategic Distinction
}

# Gate dimension counts for validation
GATE_DIMENSIONS = {
    0: ["format_innovation", "native_camouflage", "format_audience_match", "frequency_cap_survival"],
    1: ["feed_contrast", "cognitive_tension", "identity_magnet", "headline_stopping_power", "persona_signature_test", "headline_visual_tension"],
    2: ["visual_copy_integration", "information_hierarchy", "processing_fluency", "first_object_dominance", "reading_order", "whitespace_breathing"],
    3: ["hook_construction", "awareness_level_match", "specificity_score", "concreteness_vs_abstraction", "vivid_verb_density", "falsifiability"],
    4: ["emotional_specificity", "psychological_trigger_precision", "desire_vs_pain_calibration", "bias_choice_matrix", "reciprocity_activation", "pre_suasion_frame"],
    5: ["proof_presence", "credibility_claim_proportionality", "native_authority", "mechanism_clarity", "objection_demolition", "source_credibility_independence"],
    6: ["future_state_clarity", "cost_of_inaction", "unique_mechanism", "outcome_vividness", "identity_stakes", "implicit_promise_dominance"],
    7: ["forward_momentum", "curiosity_gap", "click_friction", "curiosity_pattern_type"],
    8: ["dwell_worthiness", "save_worthiness", "shareability", "comment_bait_potential"],
    9: ["one_idea_discipline", "pick_a_fight", "memory_encoding", "decision_criteria_reframe", "outgroup_rejection"],
}

HARD_FAIL_CONDITIONS = [
    "fabricated_statistics",
    "fabricated_testimonials",
    "product_misrepresentation",
    "bait_and_switch_cta",
    "compliance_violation",
    "ai_tell_detected",
    "wrong_product_photo",
    "cta_on_cold_creative",
    "short_phrase_period_headline",
]


@dataclass
class GateScore:
    """Score for a single gate with per-dimension breakdown."""
    gate_number: int
    gate_name: str
    dimensions: Dict[str, float]  # dimension_name -> score (0-10)
    rationales: Dict[str, str]  # dimension_name -> brief rationale
    average: float = 0.0

    def __post_init__(self):
        if self.dimensions:
            self.average = sum(self.dimensions.values()) / len(self.dimensions)


@dataclass
class CoherenceMultipliers:
    """Three coherence multipliers that compound (capped at ±20%)."""
    strategic_coherence: float = 1.0  # 0.8-1.2
    offer_alignment: float = 1.0  # 0.9-1.1
    belief_distance: float = 1.0  # 0.9-1.1
    rationales: Dict[str, str] = field(default_factory=dict)

    @property
    def combined(self) -> float:
        raw = self.strategic_coherence * self.offer_alignment * self.belief_distance
        return max(0.8, min(1.2, raw))


@dataclass
class RubricResult:
    """Complete rubric scoring result for a single ad."""
    gates: List[GateScore]
    multipliers: CoherenceMultipliers
    hard_fails: List[str]
    gate_caps_applied: List[str]
    raw_score: float
    final_score: float
    letter_grade: str
    model_used: str
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def gate_scores_dict(self) -> Dict[int, float]:
        return {g.gate_number: g.average for g in self.gates}


@dataclass
class ComparisonResult:
    """Result of scoring the same ad across multiple models."""
    results: Dict[str, RubricResult]  # model_name -> result
    gate_variance: Dict[int, float]  # gate_number -> std dev across models
    overall_variance: float
    recommendation: str  # Which model to use based on results


@dataclass
class BacktestEntry:
    """A single ad's rubric score paired with its performance metrics."""
    meta_ad_id: str
    rubric_result: RubricResult
    performance: Dict[str, float]  # metric_name -> value (CTR, ROAS, CPC, etc.)


@dataclass
class BacktestResult:
    """Results of back-testing rubric against ad performance."""
    entries: List[BacktestEntry]
    correlations: Dict[str, Dict[int, float]]  # metric -> {gate_number -> correlation}
    overall_correlations: Dict[str, float]  # metric -> correlation with final_score
    model_used: str
    total_ads_scored: int
    scoring_time_ms: int


# ============================================================================
# RUBRIC PROMPT
# ============================================================================

RUBRIC_SYSTEM_PROMPT = """You are an expert direct-response advertising analyst. You score ads against a rigorous 10-gate creative effectiveness rubric.

You will receive:
1. An ad creative image
2. The ad's primary text / body copy
3. The headline
4. CTA text (if any)
5. Context: target audience, awareness level, product info

Score each dimension 0-10 with a brief rationale (1 sentence max). Be brutally honest — most ads score 4-6. Reserve 8+ for genuinely exceptional work. A score of 9-10 should be rare.

Return ONLY valid JSON matching this exact structure."""

RUBRIC_SCORING_PROMPT = """Score this ad against ALL gates below. For each dimension, give a score (0-10) and one-sentence rationale.

## GATES

### GATE 0: FORMAT & NATIVE CAMOUFLAGE (12%)
- format_innovation: Is this a recognizable hijacked format (classified post, leaked memo, text convo, dashboard) vs. standard ad layout?
- native_camouflage: If you scrolled past this in your feed, would you recognize it as an ad before reading it?
- format_audience_match: Does the format match how this audience already consumes content?
- frequency_cap_survival: Will this ad still work after the user has seen it 5 times?

Hard rules: Generic stock photo + headline overlay = 0 on format_innovation. AI face that looks "off" = max 4 on entire gate. Logo + CTA button + clear product placement = max 5 on native_camouflage.

### GATE 1: PATTERN INTERRUPT (11%)
- feed_contrast: Does this look/feel DIFFERENT from what currently dominates the Meta feed?
- cognitive_tension: Does the creative present something demanding resolution (question, contradiction, incomplete story)?
- identity_magnet: How powerfully does it pull the target viewer in with "this is about ME"?
- headline_stopping_power: Could the text alone stop the scroll even with a generic visual?
- persona_signature_test: Cover the brand/product — could the target persona STILL recognize this is for them?
- headline_visual_tension: Is there productive friction between headline and image?

At least 3 of 6 must score 6+ for gate to pass. Generic stock penalty: if it could be any brand's ad with a logo swap, automatic -2 on feed_contrast.

### GATE 2: VISUAL ENGAGEMENT (7%)
- visual_copy_integration: Do image and text work as a single unified communication?
- information_hierarchy: Can the viewer extract the core message in under 3 seconds?
- processing_fluency: How easy is the core message to understand?
- first_object_dominance: What is the dominant object in first 200ms? Does it do the work of the headline?
- reading_order: Is the most important value prop at eye-path position 1?
- whitespace_breathing: Does the ad have credibility-signaling negative space, or is it cluttered?

Text too small to read on mobile = entire gate capped at 3. Safe zone violation = automatic -2 on information_hierarchy.

### GATE 3: MESSAGE & HOOK (12%)
- hook_construction: Does the primary text use a proven hook structure (specific number + mechanism, identity callout, counterintuitive claim, problem-as-narrative)?
- awareness_level_match: Is this the right message for where the audience actually is? (Schwartz ladder)
- specificity_score: Specific, concrete details creating credibility through precision?
- concreteness_vs_abstraction: Does the copy use concrete sensory language or abstract benefit language?
- vivid_verb_density: Are the verbs doing work or just connecting nouns?
- falsifiability: Could a skeptic test the claim and prove it wrong? (Specific = credible)

### GATE 4: EMOTIONAL ACTIVATION (16%) — THE GATE
- emotional_specificity: Does the creative RECREATE the feeling, not just name it?
- psychological_trigger_precision: Is the RIGHT behavioral science principle being leveraged for this audience?
- desire_vs_pain_calibration: Cold = lean pain. Warm = lean desire. Is the balance right?
- bias_choice_matrix: Is the correct cognitive bias being activated for this stage?
- reciprocity_activation: Does the ad give genuine value before asking for anything?
- pre_suasion_frame: Does the first second set an associative frame making the offer feel inevitable?

Below 6/10 avg = final score capped at 75.

### GATE 5: CREDIBILITY ARCHITECTURE (10%)
- proof_presence: Demonstrated proof (before/after, real testimonial, media logos) vs. merely claimed?
- credibility_claim_proportionality: Does weight of proof match magnitude of claim?
- native_authority: Does the creative's format inherently convey credibility?
- mechanism_clarity: Is there a clear, believable explanation of WHY the product works?
- objection_demolition: Does the creative preemptively handle the #1 objection?
- source_credibility_independence: How credible is the proof source independent of the brand?

Fabricated proof = automatic 0 for the entire ad.

### GATE 6: DESIRE AMPLIFICATION (9%)
- future_state_clarity: Can the viewer SEE their life after the solution (specific, not abstract)?
- cost_of_inaction: Does NOT acting feel painful with a specific price?
- unique_mechanism: A proprietary "reason why" this works when others haven't?
- outcome_vividness: How visually/sensorially clear is the promised outcome?
- identity_stakes: Does acting confirm who the viewer believes they are?
- implicit_promise_dominance: Is the most powerful promise implicit rather than explicit?

Manufactured urgency = 0 on cost_of_inaction.

### GATE 7: ACTION ENGINEERING (4%)
- forward_momentum: Does the creative generate psychological movement toward clicking?
- curiosity_gap: Is there an unresolved thread that REQUIRES clicking to resolve?
- click_friction: Does the creative feel like content or a sales pitch?
- curiosity_pattern_type: Which specific curiosity pattern is executed? (information, resolution, identity, mechanism gap)

CTA on creative for cold/Unaware/Problem Aware traffic = hard fail.

### GATE 8: ALGORITHMIC RESONANCE (11%)
- dwell_worthiness: Is there enough to look at/read that viewers naturally spend 3-5+ seconds?
- save_worthiness: Would someone save this to refer back to?
- shareability: Would someone DM this to a friend with "this is literally you"?
- comment_bait_potential: Does the creative invite response, debate, or confession?

Below 5 avg = total score capped at 60.

### GATE 9: STRATEGIC DISTINCTION (8%)
- one_idea_discipline: Does the ad commit to exactly ONE idea without hedging?
- pick_a_fight: Does the ad name a villain, challenge a convention, or declare an enemy?
- memory_encoding: Will the viewer remember this ad 24 hours later?
- decision_criteria_reframe: Does the ad rewrite what the buyer should be evaluating?
- outgroup_rejection: Does the ad explicitly exclude people it's NOT for?

## COHERENCE MULTIPLIERS
- strategic_coherence (0.8-1.2): Do all gates serve ONE unified psychological objective?
- offer_alignment (0.9-1.1): Does the ad promise match the offer AND landing page?
- belief_distance (0.9-1.1): Is proof load proportional to cognitive distance audience must travel?

## HARD FAIL CONDITIONS (any = automatic 0/100)
- fabricated_statistics
- fabricated_testimonials
- product_misrepresentation
- bait_and_switch_cta
- compliance_violation (health disease claims, FINRA, immigration)
- ai_tell_detected (uncanny face, gibberish text, wrong fingers)
- wrong_product_photo
- cta_on_cold_creative (CTA on creative for cold/Unaware/Problem Aware)
- short_phrase_period_headline (short phrase ending in period anti-pattern)

## RESPONSE FORMAT

```json
{
  "gates": {
    "0": {"format_innovation": {"score": 0, "rationale": ""}, ...},
    "1": {"feed_contrast": {"score": 0, "rationale": ""}, ...},
    ...
  },
  "multipliers": {
    "strategic_coherence": {"value": 1.0, "rationale": ""},
    "offer_alignment": {"value": 1.0, "rationale": ""},
    "belief_distance": {"value": 1.0, "rationale": ""}
  },
  "hard_fails": [],
  "overall_impression": ""
}
```

## AD CONTEXT
{context}

Now score the ad image provided."""


def _build_context_block(
    headline: str = "",
    body_text: str = "",
    cta_text: str = "",
    target_audience: str = "",
    awareness_level: str = "",
    product_info: str = "",
) -> str:
    """Build the context block injected into the scoring prompt."""
    parts = []
    if headline:
        parts.append(f"**Headline:** {headline}")
    if body_text:
        parts.append(f"**Primary Text:** {body_text}")
    if cta_text:
        parts.append(f"**CTA:** {cta_text}")
    if target_audience:
        parts.append(f"**Target Audience:** {target_audience}")
    if awareness_level:
        parts.append(f"**Awareness Level:** {awareness_level}")
    if product_info:
        parts.append(f"**Product:** {product_info}")
    return "\n".join(parts) if parts else "No additional context provided."


# ============================================================================
# SCORE COMPUTATION (deterministic post-processing)
# ============================================================================

def compute_final_score(gates: List[GateScore], multipliers: CoherenceMultipliers, hard_fails: List[str]) -> Tuple[float, float, str, List[str]]:
    """
    Compute raw score, apply caps and multipliers, return (raw, final, grade, caps_applied).
    """
    if hard_fails:
        return 0.0, 0.0, "F", [f"HARD FAIL: {', '.join(hard_fails)}"]

    # Raw weighted score (0-10 scale)
    raw = sum(g.average * GATE_WEIGHTS[g.gate_number] for g in gates) * 10
    gate_avgs = {g.gate_number: g.average for g in gates}

    # Apply gate cap system
    caps_applied = []
    cap = 100.0

    # Any gate below 3 → 40
    for gn, avg in gate_avgs.items():
        if avg < 3.0:
            caps_applied.append(f"Gate {gn} ({avg:.1f}) < 3 → cap 40")
            cap = min(cap, 40.0)

    # Gate 1 below 4 → 40
    if gate_avgs.get(1, 10) < 4.0:
        caps_applied.append(f"Gate 1 ({gate_avgs[1]:.1f}) < 4 → cap 40")
        cap = min(cap, 40.0)

    # Any gate below 4 → 50
    for gn, avg in gate_avgs.items():
        if avg < 4.0:
            caps_applied.append(f"Gate {gn} ({avg:.1f}) < 4 → cap 50")
            cap = min(cap, 50.0)

    # Gate 0 below 5 → 50
    if gate_avgs.get(0, 10) < 5.0:
        caps_applied.append(f"Gate 0 ({gate_avgs[0]:.1f}) < 5 → cap 50")
        cap = min(cap, 50.0)

    # Awareness Level Match (Gate 3, dimension 1) below 5 → 65
    gate3 = next((g for g in gates if g.gate_number == 3), None)
    if gate3 and gate3.dimensions.get("awareness_level_match", 10) < 5.0:
        alm = gate3.dimensions["awareness_level_match"]
        caps_applied.append(f"Awareness match ({alm:.1f}) < 5 → cap 65")
        cap = min(cap, 65.0)

    # Gate 1 below 6 → 72
    if gate_avgs.get(1, 10) < 6.0 and cap > 72.0:
        caps_applied.append(f"Gate 1 ({gate_avgs[1]:.1f}) < 6 → cap 72")
        cap = min(cap, 72.0)

    # Gate 8 below 5 → 60
    if gate_avgs.get(8, 10) < 5.0:
        caps_applied.append(f"Gate 8 ({gate_avgs[8]:.1f}) < 5 → cap 60")
        cap = min(cap, 60.0)

    # Gate 4 below 6 → 75
    if gate_avgs.get(4, 10) < 6.0 and cap > 75.0:
        caps_applied.append(f"Gate 4 ({gate_avgs[4]:.1f}) < 6 → cap 75")
        cap = min(cap, 75.0)

    # Apply multiplier
    multiplied = raw * multipliers.combined

    # Apply cap (lowest wins)
    final = min(multiplied, cap)

    # Letter grade
    grade = _score_to_grade(final)

    return raw, final, grade, caps_applied


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C+"
    elif score >= 40:
        return "C"
    elif score >= 30:
        return "D"
    else:
        return "F"


# ============================================================================
# SERVICE
# ============================================================================

GATE_NAMES = {
    0: "Format & Native Camouflage",
    1: "Pattern Interrupt",
    2: "Visual Engagement",
    3: "Message & Hook",
    4: "Emotional Activation",
    5: "Credibility Architecture",
    6: "Desire Amplification",
    7: "Action Engineering",
    8: "Algorithmic Resonance",
    9: "Strategic Distinction",
}


class RubricScoringService:
    """
    Scores ads against the 10-gate creative effectiveness rubric.

    Supports Claude (Opus/Sonnet via pydantic_ai) and Gemini for multi-model comparison.
    """

    def __init__(self, supabase=None, gemini_service=None):
        self.supabase = supabase
        self._gemini = gemini_service

    @property
    def gemini(self):
        if self._gemini is None:
            from viraltracker.services.gemini_service import GeminiService
            self._gemini = GeminiService()
        return self._gemini

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    async def score_ad(
        self,
        image_data: bytes,
        headline: str = "",
        body_text: str = "",
        cta_text: str = "",
        target_audience: str = "",
        awareness_level: str = "",
        product_info: str = "",
        model: str = "sonnet",
    ) -> RubricResult:
        """
        Score a single ad against the full rubric.

        Args:
            image_data: Raw image bytes (PNG/JPEG/WebP)
            headline: Ad headline text
            body_text: Primary text / body copy
            cta_text: Call-to-action text
            target_audience: Description of target audience
            awareness_level: Schwartz awareness level
            product_info: Product name and key info
            model: "opus", "sonnet", or "gemini"

        Returns:
            RubricResult with all gate scores, multipliers, caps, and final grade
        """
        context = _build_context_block(
            headline=headline,
            body_text=body_text,
            cta_text=cta_text,
            target_audience=target_audience,
            awareness_level=awareness_level,
            product_info=product_info,
        )

        prompt = RUBRIC_SCORING_PROMPT.replace("{context}", context)

        start = time.time()
        try:
            if model in ("opus", "sonnet"):
                raw_response = await self._score_with_claude(image_data, prompt, model)
            elif model == "gemini":
                raw_response = await self._score_with_gemini(image_data, prompt)
            else:
                raise ValueError(f"Unknown model: {model}. Use 'opus', 'sonnet', or 'gemini'.")
        except Exception as e:
            logger.error(f"Rubric scoring failed with {model}: {e}")
            return RubricResult(
                gates=[], multipliers=CoherenceMultipliers(), hard_fails=[],
                gate_caps_applied=[], raw_score=0, final_score=0,
                letter_grade="ERR", model_used=model, error=str(e),
            )

        latency_ms = int((time.time() - start) * 1000)

        # Parse LLM response into structured result
        result = self._parse_and_compute(raw_response, model, latency_ms)
        return result

    async def score_meta_ad(
        self,
        meta_ad_id: str,
        brand_id: str,
        model: str = "sonnet",
    ) -> RubricResult:
        """
        Score a Meta ad by ID. Fetches image + copy from storage/DB.

        Args:
            meta_ad_id: Meta ad ID
            brand_id: Brand UUID
            model: Scoring model

        Returns:
            RubricResult
        """
        ad_data = await self._fetch_meta_ad_data(meta_ad_id, brand_id)
        if not ad_data:
            return RubricResult(
                gates=[], multipliers=CoherenceMultipliers(), hard_fails=[],
                gate_caps_applied=[], raw_score=0, final_score=0,
                letter_grade="ERR", model_used=model,
                error=f"Could not fetch data for meta_ad_id={meta_ad_id}",
            )

        return await self.score_ad(
            image_data=ad_data["image_bytes"],
            headline=ad_data.get("headline", ""),
            body_text=ad_data.get("body_text", ""),
            cta_text=ad_data.get("cta_text", ""),
            target_audience=ad_data.get("target_audience", ""),
            awareness_level=ad_data.get("awareness_level", ""),
            product_info=ad_data.get("product_info", ""),
            model=model,
        )

    async def score_generated_ad(
        self,
        generated_ad_id: str,
        model: str = "sonnet",
    ) -> RubricResult:
        """Score a generated ad by ID."""
        ad_data = await self._fetch_generated_ad_data(generated_ad_id)
        if not ad_data:
            return RubricResult(
                gates=[], multipliers=CoherenceMultipliers(), hard_fails=[],
                gate_caps_applied=[], raw_score=0, final_score=0,
                letter_grade="ERR", model_used=model,
                error=f"Could not fetch generated_ad_id={generated_ad_id}",
            )

        return await self.score_ad(
            image_data=ad_data["image_bytes"],
            headline=ad_data.get("headline", ""),
            body_text=ad_data.get("body_text", ""),
            cta_text=ad_data.get("cta_text", ""),
            product_info=ad_data.get("product_info", ""),
            model=model,
        )

    async def compare_models(
        self,
        image_data: bytes,
        headline: str = "",
        body_text: str = "",
        cta_text: str = "",
        target_audience: str = "",
        awareness_level: str = "",
        product_info: str = "",
        models: Optional[List[str]] = None,
    ) -> ComparisonResult:
        """
        Score the same ad across multiple models for comparison.

        Args:
            image_data: Raw image bytes
            ... (same as score_ad)
            models: List of models to compare (default: ["opus", "sonnet", "gemini"])

        Returns:
            ComparisonResult with per-model scores and variance analysis
        """
        if models is None:
            models = ["opus", "sonnet", "gemini"]

        # Score in parallel across models
        tasks = [
            self.score_ad(
                image_data=image_data,
                headline=headline,
                body_text=body_text,
                cta_text=cta_text,
                target_audience=target_audience,
                awareness_level=awareness_level,
                product_info=product_info,
                model=m,
            )
            for m in models
        ]
        results = await asyncio.gather(*tasks)

        results_dict = {m: r for m, r in zip(models, results)}

        # Compute variance per gate
        gate_variance = {}
        for gate_num in range(10):
            scores = []
            for r in results:
                if not r.error:
                    gate_dict = r.gate_scores_dict
                    if gate_num in gate_dict:
                        scores.append(gate_dict[gate_num])
            if len(scores) >= 2:
                mean = sum(scores) / len(scores)
                variance = sum((s - mean) ** 2 for s in scores) / len(scores)
                gate_variance[gate_num] = variance ** 0.5
            else:
                gate_variance[gate_num] = 0.0

        # Overall variance on final scores
        final_scores = [r.final_score for r in results if not r.error]
        if len(final_scores) >= 2:
            mean = sum(final_scores) / len(final_scores)
            overall_var = (sum((s - mean) ** 2 for s in final_scores) / len(final_scores)) ** 0.5
        else:
            overall_var = 0.0

        # Recommendation
        if overall_var < 5.0:
            recommendation = "All models agree closely. Sonnet is safe for production."
        elif overall_var < 10.0:
            recommendation = "Moderate variance. Review gate-level differences before choosing."
        else:
            recommendation = "High variance. Models disagree significantly — manual calibration needed."

        return ComparisonResult(
            results=results_dict,
            gate_variance=gate_variance,
            overall_variance=overall_var,
            recommendation=recommendation,
        )

    async def backtest_batch(
        self,
        brand_id: str,
        limit: int = 100,
        model: str = "sonnet",
        metric: str = "roas",
    ) -> BacktestResult:
        """
        Score a batch of ads with known performance data and compute correlations.

        Pulls top and bottom performers, scores each, and correlates
        rubric gate scores with actual performance metrics.

        Args:
            brand_id: Brand to analyze
            limit: Total ads to score (splits 50/50 top/bottom)
            model: Scoring model
            metric: Primary metric to rank by (roas, ctr, cpc)

        Returns:
            BacktestResult with correlations per gate
        """
        if not self.supabase:
            raise ValueError("Supabase client required for backtest")

        half = limit // 2

        # Fetch top and bottom performers
        top_ads = await self._fetch_top_performers(brand_id, metric, half)
        bottom_ads = await self._fetch_bottom_performers(brand_id, metric, half)
        all_ads = top_ads + bottom_ads

        if not all_ads:
            return BacktestResult(
                entries=[], correlations={}, overall_correlations={},
                model_used=model, total_ads_scored=0, scoring_time_ms=0,
            )

        logger.info(f"Back-testing {len(all_ads)} ads (top {len(top_ads)} + bottom {len(bottom_ads)})")

        start = time.time()
        entries = []

        for ad in all_ads:
            image_bytes = await self._download_ad_image(ad["meta_ad_id"], brand_id)
            if not image_bytes:
                logger.warning(f"Skipping {ad['meta_ad_id']}: no image available")
                continue

            result = await self.score_ad(
                image_data=image_bytes,
                headline=ad.get("ad_name", ""),
                body_text=ad.get("ad_copy", ""),
                awareness_level=ad.get("awareness_level", ""),
                model=model,
            )

            if not result.error:
                entries.append(BacktestEntry(
                    meta_ad_id=ad["meta_ad_id"],
                    rubric_result=result,
                    performance={
                        "roas": ad.get("roas", 0),
                        "ctr": ad.get("ctr", 0),
                        "cpc": ad.get("cpc", 0),
                        "cpm": ad.get("cpm", 0),
                        "spend": ad.get("spend", 0),
                        "purchases": ad.get("purchases", 0),
                    },
                ))

        scoring_time_ms = int((time.time() - start) * 1000)

        # Compute correlations
        correlations = self._compute_correlations(entries)
        overall_correlations = self._compute_overall_correlations(entries)

        return BacktestResult(
            entries=entries,
            correlations=correlations,
            overall_correlations=overall_correlations,
            model_used=model,
            total_ads_scored=len(entries),
            scoring_time_ms=scoring_time_ms,
        )

    # --------------------------------------------------------------------------
    # LLM Backends
    # --------------------------------------------------------------------------

    async def _score_with_claude(self, image_data: bytes, prompt: str, model: str) -> Dict[str, Any]:
        """Score using Claude (Opus or Sonnet) via pydantic_ai."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent

        model_id = {
            "opus": "anthropic:claude-opus-4-7",
            "sonnet": "anthropic:claude-sonnet-4-5-20250929",
        }[model]

        agent = Agent(
            model=model_id,
            system_prompt=RUBRIC_SYSTEM_PROMPT,
        )

        media_type = _detect_media_type(image_data)

        result = await agent.run(
            [
                prompt,
                BinaryContent(data=image_data, media_type=media_type),
            ]
        )

        return _parse_json_response(result.output)

    async def _score_with_gemini(self, image_data: bytes, prompt: str) -> Dict[str, Any]:
        """Score using Gemini via GeminiService."""
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        full_prompt = RUBRIC_SYSTEM_PROMPT + "\n\n" + prompt + "\n\nReturn ONLY valid JSON, no other text."

        response_text = await self.gemini.analyze_image(
            image_data=image_b64,
            prompt=full_prompt,
        )

        return _parse_json_response(response_text)

    # --------------------------------------------------------------------------
    # Data Fetching
    # --------------------------------------------------------------------------

    async def _fetch_meta_ad_data(self, meta_ad_id: str, brand_id: str) -> Optional[Dict[str, Any]]:
        """Fetch image + copy for a Meta ad."""
        if not self.supabase:
            return None

        # Get performance record for copy
        perf = self.supabase.table("meta_ads_performance").select(
            "meta_ad_id, ad_name, ad_copy, thumbnail_url"
        ).eq("meta_ad_id", meta_ad_id).eq("brand_id", brand_id).limit(1).execute()

        ad_info = perf.data[0] if perf.data else {}

        # Get classification for awareness level
        classification = self.supabase.table("ad_creative_classifications").select(
            "creative_awareness_level"
        ).eq("meta_ad_id", meta_ad_id).order("classified_at", desc=True).limit(1).execute()

        awareness = ""
        if classification.data:
            awareness = classification.data[0].get("creative_awareness_level", "")

        # Get image bytes
        image_bytes = await self._download_ad_image(meta_ad_id, brand_id)
        if not image_bytes:
            return None

        return {
            "image_bytes": image_bytes,
            "headline": ad_info.get("ad_name", ""),
            "body_text": ad_info.get("ad_copy", ""),
            "cta_text": "",
            "target_audience": "",
            "awareness_level": awareness,
            "product_info": "",
        }

    async def _fetch_generated_ad_data(self, generated_ad_id: str) -> Optional[Dict[str, Any]]:
        """Fetch image + copy for a generated ad."""
        if not self.supabase:
            return None

        # Get generated ad
        ad = self.supabase.table("generated_ads").select(
            "storage_path, hook_text, prompt_spec"
        ).eq("id", generated_ad_id).limit(1).execute()

        if not ad.data:
            return None

        ad_row = ad.data[0]
        storage_path = ad_row.get("storage_path")
        if not storage_path:
            return None

        # Download image
        image_bytes = await self._download_from_storage(storage_path)
        if not image_bytes:
            return None

        # Extract headline from prompt_spec if available
        headline = ""
        prompt_spec = ad_row.get("prompt_spec")
        if prompt_spec and isinstance(prompt_spec, dict):
            text_elements = prompt_spec.get("text_elements", [])
            for elem in text_elements:
                if isinstance(elem, dict) and elem.get("role") == "headline":
                    headline = elem.get("text", "")
                    break

        return {
            "image_bytes": image_bytes,
            "headline": headline,
            "body_text": ad_row.get("hook_text", ""),
            "cta_text": "",
            "product_info": "",
        }

    async def _download_ad_image(self, meta_ad_id: str, brand_id: str) -> Optional[bytes]:
        """Download ad image from storage (meta_ad_assets or scraped_ad_assets)."""
        if not self.supabase:
            return None

        # Try meta_ad_assets first (owned ads)
        try:
            asset = self.supabase.table("meta_ad_assets").select(
                "storage_path"
            ).eq("meta_ad_id", meta_ad_id).eq("asset_type", "image").eq(
                "status", "downloaded"
            ).limit(1).execute()

            if asset.data:
                return await self._download_from_storage(asset.data[0]["storage_path"])
        except Exception as e:
            logger.debug(f"meta_ad_assets lookup failed for {meta_ad_id}: {e}")

        # Try scraped_ad_assets (competitor/library ads) — only if meta_ad_id looks like a UUID
        if "-" in meta_ad_id:
            try:
                scraped = self.supabase.table("scraped_ad_assets").select(
                    "storage_path"
                ).eq("facebook_ad_id", meta_ad_id).eq("asset_type", "image").limit(1).execute()

                if scraped.data:
                    return await self._download_from_storage(scraped.data[0]["storage_path"])
            except Exception as e:
                logger.debug(f"scraped_ad_assets lookup failed for {meta_ad_id}: {e}")

        # Fallback: try thumbnail URL from performance data
        try:
            perf = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url"
            ).eq("meta_ad_id", meta_ad_id).limit(1).execute()

            if perf.data and perf.data[0].get("thumbnail_url"):
                return await self._download_from_url(perf.data[0]["thumbnail_url"])
        except Exception as e:
            logger.debug(f"thumbnail_url lookup failed for {meta_ad_id}: {e}")

        return None

    async def _download_from_storage(self, storage_path: str) -> Optional[bytes]:
        """Download from Supabase storage."""
        try:
            parts = storage_path.split("/", 1)
            bucket = parts[0]
            path = parts[1] if len(parts) > 1 else storage_path
            data = await asyncio.to_thread(
                lambda: self.supabase.storage.from_(bucket).download(path)
            )
            return data
        except Exception as e:
            logger.warning(f"Failed to download {storage_path}: {e}")
            return None

    async def _download_from_url(self, url: str) -> Optional[bytes]:
        """Download image from URL (thumbnail fallback)."""
        try:
            import urllib.request
            data = await asyncio.to_thread(
                lambda: urllib.request.urlopen(url, timeout=10).read()
            )
            return data
        except Exception as e:
            logger.warning(f"Failed to download from URL: {e}")
            return None

    async def _fetch_top_performers(self, brand_id: str, metric: str, limit: int) -> List[Dict]:
        """Fetch top-performing ads by metric."""
        metric_col = {
            "roas": "return_on_ad_spend",
            "ctr": "click_through_rate",
            "cpc": "cost_per_click",
        }.get(metric, "return_on_ad_spend")

        # Aggregate by ad, require minimum spend
        result = self.supabase.rpc("get_top_ads_for_rubric", {
            "p_brand_id": brand_id,
            "p_metric": metric_col,
            "p_limit": limit,
            "p_direction": "desc",
            "p_min_spend": 50.0,
        }).execute()

        if result.data:
            return result.data

        # Fallback: direct query if RPC doesn't exist
        return await self._fetch_performers_direct(brand_id, metric_col, limit, desc=True)

    async def _fetch_bottom_performers(self, brand_id: str, metric: str, limit: int) -> List[Dict]:
        """Fetch bottom-performing ads by metric."""
        metric_col = {
            "roas": "return_on_ad_spend",
            "ctr": "click_through_rate",
            "cpc": "cost_per_click",
        }.get(metric, "return_on_ad_spend")

        result = self.supabase.rpc("get_top_ads_for_rubric", {
            "p_brand_id": brand_id,
            "p_metric": metric_col,
            "p_limit": limit,
            "p_direction": "asc",
            "p_min_spend": 50.0,
        }).execute()

        if result.data:
            return result.data

        return await self._fetch_performers_direct(brand_id, metric_col, limit, desc=False)

    async def _fetch_performers_direct(
        self, brand_id: str, metric_col: str, limit: int, desc: bool
    ) -> List[Dict]:
        """Direct query fallback for fetching performers."""
        try:
            query = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, ad_name, ad_copy, spend, "
                "return_on_ad_spend, click_through_rate, cost_per_click, "
                "cost_per_mille, purchases"
            ).eq("brand_id", brand_id).gte("spend", 50)

            if desc:
                query = query.order(metric_col, desc=True)
            else:
                query = query.order(metric_col, desc=False)

            result = query.limit(limit).execute()

            # Deduplicate by meta_ad_id (keep best/worst per ad)
            seen = set()
            unique = []
            for row in (result.data or []):
                aid = row.get("meta_ad_id")
                if aid and aid not in seen:
                    seen.add(aid)
                    unique.append({
                        "meta_ad_id": aid,
                        "ad_name": row.get("ad_name", ""),
                        "ad_copy": row.get("ad_copy", ""),
                        "roas": row.get("return_on_ad_spend", 0) or 0,
                        "ctr": row.get("click_through_rate", 0) or 0,
                        "cpc": row.get("cost_per_click", 0) or 0,
                        "cpm": row.get("cost_per_mille", 0) or 0,
                        "spend": row.get("spend", 0) or 0,
                        "purchases": row.get("purchases", 0) or 0,
                    })
            return unique[:limit]
        except Exception as e:
            logger.error(f"Failed to fetch performers: {e}")
            return []

    # --------------------------------------------------------------------------
    # Parsing & Computation
    # --------------------------------------------------------------------------

    def _parse_and_compute(self, raw: Dict[str, Any], model: str, latency_ms: int) -> RubricResult:
        """Parse LLM JSON response into RubricResult with computed scores."""
        gates_raw = raw.get("gates", {})
        multipliers_raw = raw.get("multipliers", {})
        hard_fails = raw.get("hard_fails", [])

        # Parse gates
        gates = []
        for gate_num in range(10):
            gate_key = str(gate_num)
            gate_data = gates_raw.get(gate_key, {})

            dimensions = {}
            rationales = {}
            for dim_name, dim_data in gate_data.items():
                if isinstance(dim_data, dict):
                    dimensions[dim_name] = float(dim_data.get("score", 0))
                    rationales[dim_name] = dim_data.get("rationale", "")
                elif isinstance(dim_data, (int, float)):
                    dimensions[dim_name] = float(dim_data)

            gates.append(GateScore(
                gate_number=gate_num,
                gate_name=GATE_NAMES.get(gate_num, f"Gate {gate_num}"),
                dimensions=dimensions,
                rationales=rationales,
            ))

        # Parse multipliers
        sc = multipliers_raw.get("strategic_coherence", {})
        oa = multipliers_raw.get("offer_alignment", {})
        bd = multipliers_raw.get("belief_distance", {})

        multipliers = CoherenceMultipliers(
            strategic_coherence=float(sc.get("value", 1.0) if isinstance(sc, dict) else sc),
            offer_alignment=float(oa.get("value", 1.0) if isinstance(oa, dict) else oa),
            belief_distance=float(bd.get("value", 1.0) if isinstance(bd, dict) else bd),
            rationales={
                "strategic_coherence": sc.get("rationale", "") if isinstance(sc, dict) else "",
                "offer_alignment": oa.get("rationale", "") if isinstance(oa, dict) else "",
                "belief_distance": bd.get("rationale", "") if isinstance(bd, dict) else "",
            },
        )

        # Compute final score
        raw_score, final_score, letter_grade, caps_applied = compute_final_score(
            gates, multipliers, hard_fails
        )

        return RubricResult(
            gates=gates,
            multipliers=multipliers,
            hard_fails=hard_fails,
            gate_caps_applied=caps_applied,
            raw_score=round(raw_score, 1),
            final_score=round(final_score, 1),
            letter_grade=letter_grade,
            model_used=model,
            latency_ms=latency_ms,
        )

    def _compute_correlations(self, entries: List[BacktestEntry]) -> Dict[str, Dict[int, float]]:
        """Compute Pearson correlation between each gate score and each performance metric."""
        if len(entries) < 5:
            return {}

        metrics = ["roas", "ctr", "cpc", "cpm"]
        correlations = {}

        for metric in metrics:
            correlations[metric] = {}
            metric_values = [e.performance.get(metric, 0) for e in entries]

            for gate_num in range(10):
                gate_values = [e.rubric_result.gate_scores_dict.get(gate_num, 0) for e in entries]
                r = _pearson_correlation(gate_values, metric_values)
                correlations[metric][gate_num] = round(r, 3)

        return correlations

    def _compute_overall_correlations(self, entries: List[BacktestEntry]) -> Dict[str, float]:
        """Compute correlation between final rubric score and each performance metric."""
        if len(entries) < 5:
            return {}

        metrics = ["roas", "ctr", "cpc", "cpm"]
        correlations = {}

        final_scores = [e.rubric_result.final_score for e in entries]
        for metric in metrics:
            metric_values = [e.performance.get(metric, 0) for e in entries]
            r = _pearson_correlation(final_scores, metric_values)
            correlations[metric] = round(r, 3)

        return correlations


# ============================================================================
# UTILITIES
# ============================================================================

def _detect_media_type(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if data[:4] == b'\x89PNG':
        return "image/png"
    elif data[:2] == b'\xff\xd8':
        return "image/jpeg"
    elif data[:4] == b'RIFF':
        return "image/webp"
    return "image/jpeg"  # default


def _parse_json_response(text: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code blocks."""
    if isinstance(text, dict):
        return text

    cleaned = text.strip()

    # Strip markdown code blocks
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last lines if they're code fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to find JSON object in the response
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
        logger.error(f"Failed to parse rubric JSON: {e}\nResponse: {cleaned[:500]}")
        raise ValueError(f"Failed to parse rubric scoring response as JSON: {e}")


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Compute Pearson correlation coefficient between two lists."""
    n = len(x)
    if n < 2:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5

    if den_x == 0 or den_y == 0:
        return 0.0

    return num / (den_x * den_y)
