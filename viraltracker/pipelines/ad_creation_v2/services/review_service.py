"""
V2 Review Service - Dual AI review (Claude + Gemini) with OR logic.

Extracted from ad_creation_agent.py tools:
- review_ad_claude (lines 1882-2057)
- review_ad_gemini (lines 2076-2225)
- Dual review OR logic from complete_ad_workflow (lines 3758-3786)
"""

import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


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
