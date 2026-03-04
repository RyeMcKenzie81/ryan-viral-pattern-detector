"""
V2 Review Service - Dual AI review (Claude + Gemini) with OR logic.

Phase 4 adds staged review:
- Stage 2: Claude Vision with 15-check rubric (V1-V9, C1-C4, G1-G2)
- Stage 3: Conditional Gemini Vision (only if borderline Stage 2 scores)

V1 methods (review_ad_claude, review_ad_gemini, apply_dual_review_logic)
kept for backward compatibility.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 16-check rubric: V1-V9 (visual), C1-C5 (content), G1-G2 (congruence)
RUBRIC_CHECKS = [
    "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9",
    "C1", "C2", "C3", "C4", "C5",
    "G1", "G2",
]

DEFAULT_QUALITY_CONFIG: Dict[str, Any] = {
    "pass_threshold": 7.0,
    "check_weights": {
        "V1": 1.5, "V2": 1.5, "V3": 1.0, "V4": 0.8, "V5": 0.8,
        "V6": 1.0, "V7": 1.0, "V8": 0.8, "V9": 1.2,
        "C1": 1.0, "C2": 0.8, "C3": 0.8, "C4": 0.8, "C5": 1.5,
        "G1": 1.0, "G2": 0.8,
    },
    "borderline_range": {"low": 5.0, "high": 7.0},
    "auto_reject_checks": ["V9", "C5"],
}


class AdReviewService:
    """Handles dual AI review of generated ads."""

    async def review_ad_claude(
        self,
        storage_path: str,
        product_name: str,
        hook_text: str,
        ad_analysis: Dict[str, Any],
        *,
        ad_creation_service: Any,
    ) -> Dict[str, Any]:
        """
        Review generated ad using Claude Vision API.

        Args:
            storage_path: Storage path to generated ad image
            product_name: Name of product for context
            hook_text: Hook text used in ad
            ad_analysis: Ad analysis dict
            ad_creation_service: AdCreationService for image download

        Returns:
            ReviewResult dict with reviewer, scores, issues, status
        """
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        from viraltracker.core.config import Config

        logger.info(f"Claude reviewing ad: {storage_path}")

        if not storage_path:
            raise ValueError("storage_path cannot be empty")

        image_data = await ad_creation_service.download_image(storage_path)

        review_prompt = _build_review_prompt("claude", product_name, hook_text, ad_analysis)

        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are an expert creative director. Return ONLY valid JSON."
        )

        # Detect image format from magic bytes
        media_type = _detect_media_type(image_data)

        result = await vision_agent.run(
            [
                review_prompt + "\n\nReturn ONLY valid JSON, no other text.",
                BinaryContent(data=image_data, media_type=media_type)
            ]
        )

        review_text = result.output
        review_dict = _parse_review_json(review_text)

        logger.info(f"Claude review complete: status={review_dict.get('status')}, "
                    f"product_acc={review_dict.get('product_accuracy')}, "
                    f"text_acc={review_dict.get('text_accuracy')}")
        return review_dict

    async def review_ad_gemini(
        self,
        storage_path: str,
        product_name: str,
        hook_text: str,
        ad_analysis: Dict[str, Any],
        *,
        ad_creation_service: Any,
        gemini_service: Any,
    ) -> Dict[str, Any]:
        """
        Review generated ad using Gemini Vision API.

        Args:
            storage_path: Storage path to generated ad image
            product_name: Name of product for context
            hook_text: Hook text used in ad
            ad_analysis: Ad analysis dict
            ad_creation_service: AdCreationService for image download
            gemini_service: GeminiService for vision review

        Returns:
            ReviewResult dict with reviewer, scores, issues, status
        """
        logger.info(f"Gemini reviewing ad: {storage_path}")

        if not storage_path:
            raise ValueError("storage_path cannot be empty")

        image_data = await ad_creation_service.download_image(storage_path)

        review_prompt = _build_review_prompt("gemini", product_name, hook_text, ad_analysis)

        # Call Gemini Vision API via service
        review_result = await gemini_service.review_image(
            image_data=image_data,
            prompt=review_prompt
        )

        review_dict = _parse_review_json(review_result)

        logger.info(f"Gemini review complete: status={review_dict.get('status')}, "
                    f"product_acc={review_dict.get('product_accuracy')}, "
                    f"text_acc={review_dict.get('text_accuracy')}")
        return review_dict

    def apply_dual_review_logic(
        self,
        claude_review: Dict[str, Any],
        gemini_review: Dict[str, Any],
    ) -> tuple:
        """
        Apply OR logic for dual review system.

        Returns:
            Tuple of (final_status, reviewers_agree)
            - final_status: "approved", "rejected", "flagged", or "review_failed"
            - reviewers_agree: bool or None if one failed
        """
        claude_status = claude_review.get('status', 'review_failed')
        gemini_status = gemini_review.get('status', 'review_failed')
        claude_approved = claude_status == 'approved'
        gemini_approved = gemini_status == 'approved'

        # Handle review failures
        if claude_status == 'review_failed' and gemini_status == 'review_failed':
            final_status = 'review_failed'
        elif claude_status == 'review_failed':
            final_status = 'approved' if gemini_approved else gemini_status
        elif gemini_status == 'review_failed':
            final_status = 'approved' if claude_approved else claude_status
        elif claude_approved or gemini_approved:
            final_status = 'approved'  # OR logic
        elif not claude_approved and not gemini_approved:
            final_status = 'rejected'
        else:
            final_status = 'flagged'

        # Agreement check
        if claude_status != 'review_failed' and gemini_status != 'review_failed':
            reviewers_agree = (claude_approved == gemini_approved)
        else:
            reviewers_agree = None

        return final_status, reviewers_agree

    def make_failed_review(self, reviewer: str, error: str) -> Dict[str, Any]:
        """Create a failed review dict for error cases."""
        return {
            "reviewer": reviewer,
            "status": "review_failed",
            "error": error,
            "product_accuracy": 0,
            "text_accuracy": 0,
            "layout_accuracy": 0,
            "overall_quality": 0,
            "notes": f"Review failed: {error}"
        }

    # ========================================================================
    # Phase 4: Staged Review (15-check rubric)
    # ========================================================================

    async def review_ad_staged(
        self,
        image_data: bytes,
        product_name: str,
        hook_text: str,
        ad_analysis: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        exemplar_context: Optional[str] = None,
        current_offer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run 3-stage review pipeline.

        Stage 2: Claude Vision with 16-check rubric (V1-V9, C1-C5, G1-G2).
        Stage 3: Conditional Gemini Vision (same rubric) — only if borderline.
        Final decision uses OR logic across stages.

        Args:
            image_data: Raw image bytes.
            product_name: Product name for context.
            hook_text: Hook text used in ad.
            ad_analysis: Ad analysis dict.
            config: quality_scoring_config dict. If None, uses defaults.
            exemplar_context: Optional few-shot exemplar context for review calibration (Phase 8A).
            current_offer: Product's actual offer text, or None if no offer exists.

        Returns:
            Dict with review_check_scores, weighted_score, final_status,
            stage2_result, stage3_result (if triggered).
        """
        if config is None:
            config = DEFAULT_QUALITY_CONFIG

        check_weights = config.get("check_weights", DEFAULT_QUALITY_CONFIG["check_weights"])
        pass_threshold = config.get("pass_threshold", 7.0)
        borderline_range = config.get("borderline_range", {"low": 5.0, "high": 7.0})
        auto_reject_checks = config.get("auto_reject_checks", ["V9"])

        # Stage 2: Claude Vision
        try:
            stage2_scores = await self._run_rubric_review_claude(
                image_data, product_name, hook_text, ad_analysis,
                exemplar_context=exemplar_context,
                current_offer=current_offer,
            )
        except Exception as e:
            logger.warning(f"Stage 2 Claude review failed: {e}")
            return {
                "review_check_scores": None,
                "weighted_score": 0.0,
                "final_status": "review_failed",
                "stage2_result": {"error": str(e)},
                "stage3_result": None,
            }

        stage2_weighted = compute_weighted_score(stage2_scores, check_weights)

        # Check auto-reject
        for check_name in auto_reject_checks:
            score = stage2_scores.get(check_name, 10.0)
            if score < 3.0:
                logger.info(f"Auto-reject: {check_name}={score} < 3.0")
                return {
                    "review_check_scores": stage2_scores,
                    "weighted_score": stage2_weighted,
                    "final_status": "rejected",
                    "stage2_result": {"scores": stage2_scores, "weighted": stage2_weighted},
                    "stage3_result": None,
                    "auto_rejected_check": check_name,
                }

        # Determine if Stage 3 needed (borderline detection)
        borderline_low = borderline_range.get("low", 5.0)
        borderline_high = borderline_range.get("high", 7.0)
        has_borderline = any(
            borderline_low <= stage2_scores.get(k, 10.0) <= borderline_high
            for k in RUBRIC_CHECKS
        )

        stage3_result = None
        final_scores = stage2_scores
        final_weighted = stage2_weighted

        if has_borderline:
            # Stage 3: Gemini Vision (same rubric)
            try:
                stage3_scores = await self._run_rubric_review_gemini(
                    image_data, product_name, hook_text, ad_analysis,
                    exemplar_context=exemplar_context,
                    current_offer=current_offer,
                )
                stage3_weighted = compute_weighted_score(stage3_scores, check_weights)
                stage3_result = {"scores": stage3_scores, "weighted": stage3_weighted}

                # OR logic: use better weighted score
                if stage3_weighted >= stage2_weighted:
                    final_scores = stage3_scores
                    final_weighted = stage3_weighted
            except Exception as e:
                logger.warning(f"Stage 3 Gemini review failed (non-fatal): {e}")
                stage3_result = {"error": str(e)}

        # Final status based on weighted score
        final_status = apply_staged_review_logic(final_weighted, pass_threshold, borderline_range)

        return {
            "review_check_scores": final_scores,
            "weighted_score": round(final_weighted, 2),
            "final_status": final_status,
            "stage2_result": {"scores": stage2_scores, "weighted": round(stage2_weighted, 2)},
            "stage3_result": stage3_result,
        }

    async def _run_rubric_review_claude(
        self,
        image_data: bytes,
        product_name: str,
        hook_text: str,
        ad_analysis: Dict[str, Any],
        exemplar_context: Optional[str] = None,
        current_offer: Optional[str] = None,
    ) -> Dict[str, float]:
        """Run 16-check rubric review with Claude Vision."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        from viraltracker.core.config import Config

        prompt = _build_rubric_prompt(product_name, hook_text, ad_analysis, exemplar_context, current_offer=current_offer)
        media_type = _detect_media_type(image_data)

        agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are an expert creative director. Score each check precisely 0-10. Return ONLY valid JSON."
        )

        result = await agent.run([
            prompt,
            BinaryContent(data=image_data, media_type=media_type),
        ])

        return _parse_rubric_scores(result.output)

    async def _run_rubric_review_gemini(
        self,
        image_data: bytes,
        product_name: str,
        hook_text: str,
        ad_analysis: Dict[str, Any],
        exemplar_context: Optional[str] = None,
        current_offer: Optional[str] = None,
    ) -> Dict[str, float]:
        """Run 16-check rubric review with Gemini Vision."""
        from viraltracker.services.gemini_service import GeminiService
        import base64

        prompt = _build_rubric_prompt(product_name, hook_text, ad_analysis, exemplar_context, current_offer=current_offer)
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        gemini = GeminiService()
        result = await gemini.analyze_image(
            image_base64=image_b64,
            prompt=prompt,
        )

        return _parse_rubric_scores(result)


def _build_review_prompt(
    reviewer: str,
    product_name: str,
    hook_text: str,
    ad_analysis: Dict[str, Any],
) -> str:
    """Build the review prompt used by both Claude and Gemini."""
    return f"""
        You are reviewing a generated Facebook ad image for production readiness.

        **Context:**
        - Product: {product_name}
        - Hook/Headline: "{hook_text}"
        - Expected Format: {ad_analysis.get('format_type')}
        - Expected Layout: {ad_analysis.get('layout_structure')}

        **Review Criteria:**

        1. **Product Accuracy** (0.0-1.0 score):
           - Is the product image reproduced EXACTLY as provided?
           - No hallucinations or modifications to product appearance?
           - Product visible and clearly identifiable?
           - Score 1.0 = perfect reproduction, 0.0 = completely wrong

        2. **Text Accuracy** (0.0-1.0 score):
           - Is all text readable and correct?
           - No gibberish, misspellings, or garbled text?
           - Hook text matches what was requested?
           - Score 1.0 = all text perfect, 0.0 = unreadable

        3. **Layout Accuracy** (0.0-1.0 score):
           - Does layout match reference ad format?
           - Elements positioned correctly?
           - Colors and spacing appropriate?
           - Score 1.0 = matches reference, 0.0 = completely different

        4. **Overall Quality** (0.0-1.0 score):
           - Production-ready quality?
           - No AI artifacts (distortions, glitches)?
           - Professional appearance?
           - Score 1.0 = ready to publish, 0.0 = not usable

        **Approval Logic:**
        - APPROVED: product_accuracy >= 0.8 AND text_accuracy >= 0.8
        - NEEDS_REVISION: One score between 0.5-0.79
        - REJECTED: Any score < 0.5

        Return JSON with this structure:
        {{
            "reviewer": "{reviewer}",
            "product_accuracy": 0.0-1.0,
            "text_accuracy": 0.0-1.0,
            "layout_accuracy": 0.0-1.0,
            "overall_quality": 0.0-1.0,
            "product_issues": ["list of specific issues with product image"],
            "text_issues": ["list of text problems found"],
            "ai_artifacts": ["list of AI generation artifacts detected"],
            "status": "approved" | "needs_revision" | "rejected",
            "notes": "Brief summary of review findings"
        }}
        """


def _parse_review_json(review_text: str) -> Dict[str, Any]:
    """Parse review JSON from AI response, stripping markdown fences."""
    review_clean = review_text.strip()
    if review_clean.startswith('```'):
        lines = review_clean.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        review_clean = '\n'.join(lines)

    return json.loads(review_clean)


def _detect_media_type(image_data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
        return "image/webp"
    elif image_data[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    elif image_data[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    return "image/png"


# ============================================================================
# Phase 4: 15-check rubric helpers
# ============================================================================

def _build_rubric_prompt(
    product_name: str,
    hook_text: str,
    ad_analysis: Dict[str, Any],
    exemplar_context: Optional[str] = None,
    current_offer: Optional[str] = None,
) -> str:
    """Build the 16-check structured rubric prompt.

    Args:
        product_name: Product name for context.
        hook_text: Hook text used in ad.
        ad_analysis: Ad analysis dict.
        exemplar_context: Optional Phase 8A few-shot calibration examples.
        current_offer: Product's actual offer text, or None if no offer.
    """
    exemplar_section = ""
    if exemplar_context:
        exemplar_section = f"\n{exemplar_context}\n"

    offer_context = current_offer if current_offer else "NONE — no offer exists, any promotional language is hallucinated"

    return f"""Score this generated ad image on 16 quality checks. Each check is scored 0-10.

CONTEXT:
- Product: {product_name}
- Hook/Headline: "{hook_text}"
- Expected Format: {ad_analysis.get('format_type', 'N/A')}
- Expected Layout: {ad_analysis.get('layout_structure', 'N/A')}
- Provided Offer: {offer_context}
{exemplar_section}
VISUAL CHECKS (V1-V9):
- V1: Product accuracy — product image matches reference exactly (0=wrong product, 10=perfect)
- V2: Text readability — all text is crisp, readable, no garbling (0=unreadable, 10=perfect)
- V3: Layout accuracy — matches reference ad layout structure (0=wrong layout, 10=exact match)
- V4: Color consistency — colors are appropriate and consistent (0=jarring, 10=perfect)
- V5: Spacing/alignment — elements properly spaced and aligned (0=messy, 10=perfect)
- V6: Image resolution — no pixelation, blur, or compression artifacts (0=blurry, 10=crisp)
- V7: Background quality — background is clean and appropriate (0=distracting, 10=perfect)
- V8: Font quality — fonts are consistent and professional (0=messy, 10=professional)
- V9: AI artifacts — no visible AI generation artifacts (extra fingers, distortions) (0=severe artifacts, 10=none)

CONTENT CHECKS (C1-C5):
- C1: Hook effectiveness — headline is compelling and relevant (0=irrelevant, 10=compelling)
- C2: Brand consistency — ad feels on-brand (0=off-brand, 10=perfect fit)
- C3: CTA clarity — call-to-action is clear if present (0=confusing, 10=clear)
- C4: Message coherence — all elements tell a coherent story (0=disjointed, 10=cohesive)
- C5: Offer accuracy — ad contains ONLY the provided offer, no hallucinated discounts/promos (0=invented offers, 10=accurate or no offers present)

CONGRUENCE CHECKS (G1-G2):
- G1: Headline-offer alignment — headline matches offer/product promise (0=mismatch, 10=aligned)
- G2: Visual-message alignment — image supports the text message (0=contradicts, 10=reinforces)

Return ONLY a JSON object with check names as keys and scores (0-10) as values:
{{"V1": 8.5, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0, "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5, "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0, "C5": 9.0, "G1": 7.0, "G2": 8.0}}
"""


def _parse_rubric_scores(raw_output: str) -> Dict[str, float]:
    """Parse 15-check rubric scores from LLM output."""
    text = raw_output.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse rubric scores JSON")
        return {k: 5.0 for k in RUBRIC_CHECKS}

    scores = {}
    for check in RUBRIC_CHECKS:
        val = parsed.get(check)
        if val is not None:
            try:
                scores[check] = max(0.0, min(10.0, float(val)))
            except (ValueError, TypeError):
                scores[check] = 5.0
        else:
            scores[check] = 5.0  # Default neutral

    return scores


def compute_weighted_score(
    scores: Dict[str, float],
    weights: Dict[str, float],
) -> float:
    """Compute weighted average score from rubric check scores.

    Args:
        scores: Dict of check_name → score (0-10).
        weights: Dict of check_name → weight.

    Returns:
        Weighted average score (0-10 scale).
    """
    total_weight = 0.0
    weighted_sum = 0.0

    for check in RUBRIC_CHECKS:
        w = weights.get(check, 0.0)
        s = scores.get(check, 5.0)
        weighted_sum += w * s
        total_weight += w

    if total_weight == 0:
        return 5.0

    return weighted_sum / total_weight


def apply_staged_review_logic(
    weighted_score: float,
    pass_threshold: float,
    borderline_range: Dict[str, float],
) -> str:
    """Determine final status from weighted score.

    Args:
        weighted_score: Weighted average (0-10).
        pass_threshold: Score at or above = approved.
        borderline_range: Dict with "low" and "high".

    Returns:
        "approved", "rejected", or "flagged".
    """
    if weighted_score >= pass_threshold:
        return "approved"
    elif weighted_score >= borderline_range.get("low", 5.0):
        return "flagged"
    else:
        return "rejected"


async def load_quality_config(organization_id: Optional[str] = None) -> Dict[str, Any]:
    """Load active quality_scoring_config from database.

    Falls back to global config, then to DEFAULT_QUALITY_CONFIG.

    Args:
        organization_id: Optional org UUID string. None = use global.

    Returns:
        Config dict with pass_threshold, check_weights, borderline_range, auto_reject_checks.
    """
    try:
        from viraltracker.core.database import get_supabase_client
        db = get_supabase_client()

        # Try org-specific config first
        if organization_id:
            result = db.table("quality_scoring_config").select("*").eq(
                "organization_id", organization_id
            ).eq("is_active", True).limit(1).execute()

            if result.data:
                return result.data[0]

        # Fall back to global config (org_id IS NULL)
        result = db.table("quality_scoring_config").select("*").is_(
            "organization_id", "null"
        ).eq("is_active", True).limit(1).execute()

        if result.data:
            return result.data[0]

    except Exception as e:
        logger.warning(f"Failed to load quality config, using defaults: {e}")

    return DEFAULT_QUALITY_CONFIG
