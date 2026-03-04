"""
Analysis Service - Vision AI analysis of reference ads and template extraction.

Extracted from ad_creation_agent.py tools:
- analyze_reference_ad (lines 369-611)
- extract_template_angle (lines 2327-2495)
"""

import json
import logging
import base64
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AdAnalysisService:
    """Handles Vision AI analysis of reference ads and template extraction."""

    async def analyze_reference_ad(
        self,
        image_base64: str,
        *,
        ad_creation_service: Any,
    ) -> Dict[str, Any]:
        """
        Analyze reference ad using Vision AI to extract format, layout, colors.

        Args:
            image_base64: Base64-encoded reference ad image data
            ad_creation_service: AdCreationService instance (for image download if needed)

        Returns:
            Dict with ad analysis (format_type, layout_structure, color_palette, etc.)
        """
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        from viraltracker.core.config import Config
        from viraltracker.services.models import AdAnalysis

        logger.info("Analyzing reference ad with Vision AI")

        # Decode base64 to bytes
        if isinstance(image_base64, str):
            image_bytes = base64.b64decode(image_base64)
        else:
            image_bytes = image_base64

        # Detect image format from magic bytes
        media_type = _detect_media_type_from_bytes(image_bytes)

        analysis_prompt = """
        Analyze this Facebook ad reference image and extract the following:

        1. **Format Type**: What type of ad is this?
           - testimonial (customer quote/review)
           - quote_style (text overlay on product)
           - before_after (transformation showcase)
           - product_showcase (product-focused with benefits)

        2. **Layout Structure**: How is the ad laid out?
           - single_image (one cohesive design)
           - two_panel (split screen/side-by-side)
           - carousel (multiple frames)

        3. **Fixed Elements**: What elements should stay the same across all 5 variations?
           (e.g., product bottle, logo, offer bar, benefit icons)

        4. **Variable Elements**: What elements should change per variation?
           (e.g., hook text, background color, testimonial name)

        5. **Text Placement**: Where is text positioned?
           Provide a mapping of text type → position
           (e.g., headline: top_center, subheadline: below_headline, benefits: corners)

        6. **Color Palette**: Extract main colors as hex codes
           (background, text, accent colors)

        7. **Authenticity Markers**: What makes this feel authentic?
           (e.g., screenshot style, quote marks, timestamps, usernames, emojis, casual font)

        8. **Social Proof Elements**: Does this ad include trust signals or social proof?
           Look for:
           - Statistical badges (e.g., "100,000+ Sold", "5-Star Rating", "#1 Best Seller")
           - Numerical claims displayed as graphics/badges
           - Award badges or certification marks
           - Customer count indicators
           - Sales volume displays

           Return:
           - "has_social_proof": true/false (whether social proof elements are present)
           - "social_proof_style": description of how social proof is displayed (e.g., "corner badge", "banner across top", "circular seal")
           - "social_proof_placement": where it's positioned (e.g., "top_right", "bottom_left", "center_top")

        9. **Founder/Personal Elements**: Does this ad include founder-related content?

           Look for TWO types:

           A) **Founder Signature** - A sign-off at the end:
              - Personal signatures (e.g., "Love, The Smith Family", "- John & Sarah")
              - Founder names at the bottom
              - Personal sign-offs (e.g., "From our family to yours", "With love,")
              - Handwritten-style signatures

           B) **Founder Mention** - References to founders in the body text:
              - First-person plural ("We created this...", "Our family...")
              - Founder story references ("As parents ourselves...")
              - Personal pronouns indicating the brand team speaking directly

           Return:
           - "has_founder_signature": true/false (sign-off at end)
           - "founder_signature_style": how signature appears (e.g., "handwritten at bottom", "names after dash") or null
           - "founder_signature_placement": position (e.g., "bottom_center") or null
           - "has_founder_mention": true/false (founders referenced in body text)
           - "founder_mention_style": how founders are mentioned (e.g., "first-person narrative", "founder story") or null

        10. **Canvas Size**: What are the dimensions? (e.g., 1080x1080px, 1200x628px)

        11. **Detailed Description**: Provide a comprehensive description of the ad
            that could be used for prompt engineering. Include layout, visual style,
            typography, spacing, and any notable design elements.

        Return the analysis as structured JSON matching this schema:
        {
            "format_type": "string",
            "layout_structure": "string",
            "fixed_elements": ["string"],
            "variable_elements": ["string"],
            "text_placement": {"key": "value"},
            "color_palette": ["#HEX"],
            "authenticity_markers": ["string"],
            "has_social_proof": boolean,
            "social_proof_style": "string or null",
            "social_proof_placement": "string or null",
            "has_founder_signature": boolean,
            "founder_signature_style": "string or null",
            "founder_signature_placement": "string or null",
            "has_founder_mention": boolean,
            "founder_mention_style": "string or null",
            "canvas_size": "WIDTHxHEIGHTpx",
            "detailed_description": "comprehensive description..."
        }
        """

        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are a vision analysis expert. Return ONLY valid JSON, no markdown.",
            retries=3,
        )

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                result = await vision_agent.run(
                    [
                        analysis_prompt + "\n\nIMPORTANT: Return ONLY the JSON object, no markdown code fences, no explanations.",
                        BinaryContent(data=image_bytes, media_type=media_type)
                    ]
                )
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} vision agent failed: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise Exception(f"Failed to get analysis after {max_retries} attempts: {last_error}")

            analysis_result = result.output

            # Clean up response - strip markdown fences if present
            analysis_clean = analysis_result.strip()
            if analysis_clean.startswith('```'):
                first_newline = analysis_clean.find('\n')
                last_fence = analysis_clean.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    analysis_clean = analysis_clean[first_newline + 1:last_fence].strip()

            # Handle double braces from some Gemini responses
            analysis_clean = analysis_clean.replace('{{', '{').replace('}}', '}')

            try:
                analysis_dict = json.loads(analysis_clean)
                validated = AdAnalysis.model_validate(analysis_dict)
                analysis_dict = validated.model_dump()
                break
            except (json.JSONDecodeError, Exception) as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to parse response: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise Exception(f"Failed to parse analysis after {max_retries} attempts: {last_error}")

        logger.info(f"Reference ad analyzed: format={analysis_dict.get('format_type')}, "
                    f"layout={analysis_dict.get('layout_structure')}")
        return analysis_dict

    async def extract_template_angle(
        self,
        image_base64: str,
        ad_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract persuasive angle and messaging structure from reference ad.

        Used for recreate_template mode where we keep the template's angle
        structure but swap in different product benefits.

        Args:
            image_base64: Base64-encoded reference ad image
            ad_analysis: Previous ad analysis dict

        Returns:
            Dict with angle_type, original_text, messaging_template, tone,
            key_elements, adaptation_guidance
        """
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        from viraltracker.core.config import Config

        logger.info("Extracting template angle from reference ad")

        # Decode base64 to bytes
        if isinstance(image_base64, str):
            image_bytes = base64.b64decode(image_base64)
        else:
            image_bytes = image_base64

        media_type = _detect_media_type_from_bytes(image_bytes)

        extraction_prompt = f"""
        Analyze this Facebook ad and extract its persuasive angle and messaging structure.

        **Context from previous analysis:**
        - Format: {ad_analysis.get('format_type')}
        - Layout: {ad_analysis.get('layout_structure')}
        - Authenticity markers: {', '.join(ad_analysis.get('authenticity_markers', []))}

        **Task:** Extract the core persuasive angle so it can be recreated with different product benefits.

        Analyze:

        1. **Angle Type**: What is the primary persuasive approach?
           - before_after: Shows transformation (e.g., "went from X to Y")
           - testimonial: Personal experience/quote format
           - benefit_statement: Direct benefit claim
           - social_proof: Uses numbers/authority (e.g., "100,000+ customers")
           - question_hook: Poses a question to the reader
           - problem_solution: Presents problem then solution

        2. **Original Text**: Extract the EXACT main headline/hook text from the ad.

        3. **Messaging Template**: Create a template version with {{placeholders}}:
           - Replace the specific benefit/result with {{benefit}}
           - Replace specific product name with {{product}}
           - Replace specific timeframe with {{timeframe}} if present
           - Keep the structure and tone intact
           Example: "My dog went from limping to running in 2 weeks!"
           → "My {{subject}} went from {{problem}} to {{result}} in {{timeframe}}!"

        4. **Tone**: What's the emotional tone?
           - casual: Friendly, conversational, relatable
           - professional: Expert, authoritative, clinical
           - urgent: Time-sensitive, action-oriented
           - emotional: Heart-tugging, personal, vulnerable

        5. **Key Elements**: What structural elements are critical?
           (e.g., transformation, timeframe, specific_result, personal_pronoun, exclamation)

        6. **Adaptation Guidance**: Brief notes on how to adapt this template
           for different benefits while maintaining effectiveness.

        Return JSON with this structure:
        {{
            "angle_type": "string",
            "original_text": "exact text from ad",
            "messaging_template": "template with {{placeholders}}",
            "tone": "string",
            "key_elements": ["element1", "element2"],
            "adaptation_guidance": "guidance text"
        }}
        """

        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are a marketing analysis expert. Return ONLY valid JSON.",
            retries=3,
        )

        max_retries = 3
        last_error = None
        result = None

        for attempt in range(max_retries):
            try:
                result = await vision_agent.run(
                    [
                        extraction_prompt + "\n\nReturn ONLY valid JSON, no other text.",
                        BinaryContent(data=image_bytes, media_type=media_type)
                    ]
                )
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} template angle extraction failed: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise Exception(f"Failed to extract template angle after {max_retries} attempts: {last_error}")

        result_text = result.output

        # Strip markdown code fences if present
        result_clean = result_text.strip()
        if result_clean.startswith('```'):
            first_newline = result_clean.find('\n')
            last_fence = result_clean.rfind('```')
            if first_newline != -1 and last_fence > first_newline:
                result_clean = result_clean[first_newline + 1:last_fence].strip()

        angle_dict = json.loads(result_clean)

        logger.info(f"Extracted template angle: type={angle_dict.get('angle_type')}, "
                    f"tone={angle_dict.get('tone')}")
        return angle_dict


def _detect_media_type_from_bytes(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    elif image_bytes[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    elif image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    return "image/png"


def _detect_media_type_from_base64(b64_string: str) -> str:
    """Detect image MIME type from base64 header characters."""
    if b64_string.startswith('/9j/'):
        return "image/jpeg"
    elif b64_string.startswith('iVBORw0KGgo'):
        return "image/png"
    elif b64_string.startswith('R0lGOD'):
        return "image/gif"
    elif b64_string.startswith('UklGR'):
        return "image/webp"
    return "image/png"
