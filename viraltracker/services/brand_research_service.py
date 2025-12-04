"""
BrandResearchService - AI analysis and synthesis for brand research.

This service handles:
- Image analysis with Claude Vision (extracts hooks, benefits, visual style)
- Video analysis with Gemini (transcripts, storyboards)
- Synthesis of insights into brand research summary
- Export to product data format for onboarding

Part of the Brand Research Pipeline (Phase 2A: Analysis).
"""

import logging
import json
import base64
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


# Analysis prompts
IMAGE_ANALYSIS_PROMPT = """Analyze this Facebook ad image for brand research purposes.

Extract the following information and return as JSON:

{
    "format_type": "testimonial|quote_card|before_after|product_showcase|ugc_style|meme|lifestyle|comparison|other",
    "layout_structure": "Brief description of visual layout",

    "text_content": {
        "headline": "Main headline text if visible",
        "body_text": "Any body copy visible",
        "cta_text": "Call-to-action text",
        "text_overlays": ["List of other text visible"]
    },

    "hooks": [
        {
            "text": "The exact hook/headline text",
            "hook_type": "curiosity|fear|benefit|social_proof|urgency|transformation|question|statistic",
            "effectiveness_notes": "Why this hook works"
        }
    ],

    "benefits_mentioned": ["List of product benefits explicitly or implicitly shown"],
    "usps_mentioned": ["Unique selling propositions visible"],
    "pain_points_addressed": ["Customer pain points addressed"],

    "persona_signals": {
        "age_range": "estimated target age range",
        "gender_focus": "male|female|neutral",
        "lifestyle_indicators": ["lifestyle traits suggested"],
        "income_signals": "budget|mid|premium|luxury"
    },

    "brand_voice": {
        "tone": "casual|professional|urgent|friendly|authoritative|playful",
        "writing_style": "short-punchy|conversational|formal|emotional",
        "key_phrases": ["Notable brand language patterns"]
    },

    "visual_style": {
        "color_palette": ["hex codes of dominant colors"],
        "imagery_style": "photography|illustration|graphic|mixed",
        "production_quality": "ugc|polished|professional|raw",
        "notable_elements": ["Visual elements that stand out"]
    },

    "confidence_score": 0.0-1.0
}

Return ONLY valid JSON, no other text."""


SYNTHESIS_PROMPT = """You are synthesizing brand research from multiple ad analyses.

Given the following ad analyses, create a comprehensive brand research summary.

AD ANALYSES:
{analyses_json}

Create a JSON response with this structure:
{{
    "top_benefits": ["Ranked list of most common/effective benefits, max 8"],
    "top_usps": ["Most distinctive unique selling propositions, max 5"],
    "common_pain_points": ["Pain points frequently addressed, max 6"],

    "recommended_hooks": [
        {{
            "hook_template": "The hook pattern/template",
            "hook_type": "curiosity|fear|benefit|etc",
            "frequency": "How often this pattern appears",
            "example": "Best example from the ads"
        }}
    ],

    "persona_profile": {{
        "primary_age": "age range",
        "gender_split": "male/female/neutral focus",
        "psychographics": ["Key psychological traits"],
        "lifestyle": ["Lifestyle characteristics"],
        "income_level": "budget|mid|premium|luxury",
        "motivations": ["What drives this persona"],
        "objections": ["Likely purchase objections"]
    }},

    "brand_voice_summary": "2-3 sentence description of brand voice",
    "voice_characteristics": ["Key voice traits"],
    "language_patterns": ["Common phrases/patterns to use"],

    "visual_style_guide": {{
        "primary_colors": ["hex codes"],
        "secondary_colors": ["hex codes"],
        "imagery_preference": "photography|illustration|graphic|mixed",
        "production_style": "ugc|polished|professional",
        "recommended_formats": ["testimonial", "quote_card", etc]
    }},

    "competitive_insights": "Any notable competitive positioning observed",
    "recommendations": ["Strategic recommendations based on analysis"]
}}

Return ONLY valid JSON, no other text."""


class BrandResearchService:
    """Service for brand ad research and analysis."""

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize BrandResearchService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("BrandResearchService initialized")

    async def analyze_image(
        self,
        asset_id: UUID,
        image_base64: str,
        brand_id: Optional[UUID] = None,
        facebook_ad_id: Optional[UUID] = None,
        mime_type: str = "image/jpeg"
    ) -> Dict:
        """
        Analyze image with Claude Vision.

        Extracts:
        - Layout/format type
        - Text overlays and hooks
        - Benefits and USPs
        - Persona signals
        - Brand voice characteristics
        - Visual style elements

        Args:
            asset_id: UUID of the scraped_ad_assets record
            image_base64: Base64 encoded image data
            brand_id: Optional brand to link analysis to
            facebook_ad_id: Optional facebook_ads record to link
            mime_type: MIME type of the image

        Returns:
            Analysis result dict
        """
        from anthropic import Anthropic

        logger.info(f"Analyzing image asset: {asset_id}")

        try:
            anthropic_client = Anthropic()

            message = anthropic_client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": IMAGE_ANALYSIS_PROMPT
                        }
                    ]
                }]
            )

            analysis_text = message.content[0].text

            # Strip markdown code fences if present
            analysis_clean = analysis_text.strip()
            if analysis_clean.startswith('```'):
                first_newline = analysis_clean.find('\n')
                last_fence = analysis_clean.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    analysis_clean = analysis_clean[first_newline + 1:last_fence].strip()

            analysis_dict = json.loads(analysis_clean)

            # Calculate tokens used (approximate)
            tokens_used = message.usage.input_tokens + message.usage.output_tokens

            # Save to database
            self._save_analysis(
                asset_id=asset_id,
                brand_id=brand_id,
                facebook_ad_id=facebook_ad_id,
                analysis_type="image_vision",
                raw_response=analysis_dict,
                tokens_used=tokens_used
            )

            logger.info(f"Image analysis complete: format={analysis_dict.get('format_type')}")
            return analysis_dict

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            raise ValueError(f"Invalid JSON response from Claude: {e}")
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            raise

    async def analyze_images_batch(
        self,
        asset_ids: List[UUID],
        brand_id: Optional[UUID] = None
    ) -> List[Dict]:
        """
        Analyze multiple images, storing results in database.

        Args:
            asset_ids: List of scraped_ad_assets UUIDs
            brand_id: Optional brand to link analyses to

        Returns:
            List of analysis results
        """
        results = []

        for asset_id in asset_ids:
            try:
                # Get asset from database
                asset_result = self.supabase.table("scraped_ad_assets").select(
                    "id, facebook_ad_id, storage_path, mime_type"
                ).eq("id", str(asset_id)).execute()

                if not asset_result.data:
                    logger.warning(f"Asset not found: {asset_id}")
                    continue

                asset = asset_result.data[0]

                # Download from storage
                image_base64 = await self._get_asset_base64(asset["storage_path"])
                if not image_base64:
                    logger.warning(f"Failed to download asset: {asset_id}")
                    continue

                # Analyze
                analysis = await self.analyze_image(
                    asset_id=UUID(asset["id"]),
                    image_base64=image_base64,
                    brand_id=brand_id,
                    facebook_ad_id=UUID(asset["facebook_ad_id"]) if asset.get("facebook_ad_id") else None,
                    mime_type=asset.get("mime_type", "image/jpeg")
                )

                results.append({
                    "asset_id": str(asset_id),
                    "analysis": analysis
                })

            except Exception as e:
                logger.error(f"Failed to analyze asset {asset_id}: {e}")
                continue

        logger.info(f"Batch analysis complete: {len(results)}/{len(asset_ids)} images analyzed")
        return results

    async def analyze_video(
        self,
        asset_id: UUID,
        video_url: str,
        brand_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze video with Gemini.

        Extracts:
        - Full transcript
        - Hook (first 3 seconds)
        - Storyboard with timestamps
        - Text overlays

        Args:
            asset_id: UUID of the scraped_ad_assets record
            video_url: URL or storage path of the video
            brand_id: Optional brand to link analysis to

        Returns:
            Analysis result dict
        """
        # TODO: Implement Gemini video analysis
        # For now, return placeholder
        logger.warning("Video analysis not yet implemented")
        return {
            "status": "not_implemented",
            "message": "Video analysis with Gemini coming in Phase 2A.4"
        }

    async def synthesize_insights(
        self,
        brand_id: UUID,
        image_analyses: List[Dict],
        video_analyses: List[Dict],
        copy_data: List[Dict]
    ) -> Dict:
        """
        Synthesize all analyses into brand research summary.

        Produces:
        - Top benefits (ranked)
        - Top USPs
        - Common pain points
        - Recommended hooks
        - Persona profile
        - Brand voice summary
        - Visual style guide

        Args:
            brand_id: Brand UUID to save summary for
            image_analyses: Results from analyze_images_batch
            video_analyses: Results from video analysis
            copy_data: Extracted ad copy data

        Returns:
            Synthesized brand research summary
        """
        from anthropic import Anthropic

        logger.info(f"Synthesizing insights for brand: {brand_id}")

        # Combine all analyses for the prompt
        all_analyses = []
        for item in image_analyses:
            all_analyses.append({
                "type": "image",
                "analysis": item.get("analysis", item)
            })
        for item in video_analyses:
            all_analyses.append({
                "type": "video",
                "analysis": item.get("analysis", item)
            })
        for item in copy_data:
            all_analyses.append({
                "type": "copy",
                "data": item
            })

        if not all_analyses:
            logger.warning("No analyses to synthesize")
            return {"error": "No analyses provided"}

        # Format for prompt
        analyses_json = json.dumps(all_analyses, indent=2, default=str)
        prompt = SYNTHESIS_PROMPT.format(analyses_json=analyses_json)

        try:
            anthropic_client = Anthropic()

            message = anthropic_client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            synthesis_text = message.content[0].text

            # Strip markdown code fences if present
            synthesis_clean = synthesis_text.strip()
            if synthesis_clean.startswith('```'):
                first_newline = synthesis_clean.find('\n')
                last_fence = synthesis_clean.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    synthesis_clean = synthesis_clean[first_newline + 1:last_fence].strip()

            summary = json.loads(synthesis_clean)

            # Save to database
            self._save_research_summary(brand_id, summary, len(image_analyses), len(video_analyses))

            logger.info(f"Synthesis complete: {len(summary.get('top_benefits', []))} benefits, "
                       f"{len(summary.get('recommended_hooks', []))} hooks")
            return summary

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse synthesis response: {e}")
            raise ValueError(f"Invalid JSON response from Claude: {e}")
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            raise

    def export_to_product_data(self, summary: Dict) -> Dict:
        """
        Format summary for product setup.

        Converts the brand research summary into a format compatible
        with the product onboarding system.

        Args:
            summary: Brand research summary from synthesize_insights

        Returns:
            Product data dict ready for onboarding
        """
        return {
            "benefits": summary.get("top_benefits", []),
            "unique_selling_points": summary.get("top_usps", []),
            "target_audience": self._format_persona(summary.get("persona_profile", {})),
            "brand_voice_notes": summary.get("brand_voice_summary", ""),
            "voice_characteristics": summary.get("voice_characteristics", []),
            "hooks": [
                h.get("example", h.get("hook_template", ""))
                for h in summary.get("recommended_hooks", [])
            ],
            "pain_points": summary.get("common_pain_points", []),
            "visual_style": summary.get("visual_style_guide", {}),
            "recommendations": summary.get("recommendations", [])
        }

    def _format_persona(self, persona: Dict) -> str:
        """Format persona profile as text for product data."""
        if not persona:
            return ""

        lines = []

        if persona.get("primary_age"):
            lines.append(f"Age: {persona['primary_age']}")
        if persona.get("gender_split"):
            lines.append(f"Gender Focus: {persona['gender_split']}")
        if persona.get("income_level"):
            lines.append(f"Income Level: {persona['income_level']}")

        if persona.get("psychographics"):
            lines.append("\nPsychographics:")
            for trait in persona["psychographics"]:
                lines.append(f"- {trait}")

        if persona.get("lifestyle"):
            lines.append("\nLifestyle:")
            for trait in persona["lifestyle"]:
                lines.append(f"- {trait}")

        if persona.get("motivations"):
            lines.append("\nMotivations:")
            for m in persona["motivations"]:
                lines.append(f"- {m}")

        return "\n".join(lines)

    def _save_analysis(
        self,
        asset_id: UUID,
        brand_id: Optional[UUID],
        facebook_ad_id: Optional[UUID],
        analysis_type: str,
        raw_response: Dict,
        tokens_used: int = 0
    ) -> Optional[UUID]:
        """Save analysis to brand_ad_analysis table."""
        try:
            record = {
                "asset_id": str(asset_id),
                "brand_id": str(brand_id) if brand_id else None,
                "facebook_ad_id": str(facebook_ad_id) if facebook_ad_id else None,
                "analysis_type": analysis_type,
                "raw_response": raw_response,
                "extracted_hooks": raw_response.get("hooks"),
                "extracted_benefits": raw_response.get("benefits_mentioned", []),
                "extracted_usps": raw_response.get("usps_mentioned", []),
                "pain_points": raw_response.get("pain_points_addressed", []),
                "persona_signals": raw_response.get("persona_signals"),
                "brand_voice_notes": json.dumps(raw_response.get("brand_voice", {})),
                "visual_analysis": raw_response.get("visual_style"),
                "model_used": "claude-opus-4-5-20251101",
                "tokens_used": tokens_used,
                "cost_usd": tokens_used * 0.00002  # Approximate cost
            }

            result = self.supabase.table("brand_ad_analysis").insert(record).execute()

            if result.data:
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save analysis: {e}")
            return None

    def _save_research_summary(
        self,
        brand_id: UUID,
        summary: Dict,
        images_analyzed: int,
        videos_analyzed: int
    ) -> Optional[UUID]:
        """Save or update brand research summary."""
        try:
            record = {
                "brand_id": str(brand_id),
                "top_benefits": summary.get("top_benefits", []),
                "top_usps": summary.get("top_usps", []),
                "common_pain_points": summary.get("common_pain_points", []),
                "recommended_hooks": summary.get("recommended_hooks"),
                "persona_profile": summary.get("persona_profile"),
                "brand_voice_summary": summary.get("brand_voice_summary"),
                "visual_style_guide": summary.get("visual_style_guide"),
                "images_analyzed": images_analyzed,
                "videos_analyzed": videos_analyzed,
                "model_used": "claude-opus-4-5-20251101",
                "generated_at": datetime.utcnow().isoformat()
            }

            # Upsert based on brand_id
            result = self.supabase.table("brand_research_summary").upsert(
                record,
                on_conflict="brand_id"
            ).execute()

            if result.data:
                logger.info(f"Saved research summary for brand: {brand_id}")
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save research summary: {e}")
            return None

    async def _get_asset_base64(self, storage_path: str) -> Optional[str]:
        """Download asset from storage and return as base64."""
        try:
            # Parse bucket and path
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                logger.error(f"Invalid storage path: {storage_path}")
                return None

            bucket = parts[0]
            path = parts[1]

            # Download from Supabase storage
            data = self.supabase.storage.from_(bucket).download(path)
            return base64.b64encode(data).decode('utf-8')

        except Exception as e:
            logger.error(f"Failed to download asset: {e}")
            return None

    def get_analyses_for_brand(
        self,
        brand_id: UUID,
        analysis_type: Optional[str] = None
    ) -> List[Dict]:
        """Get all analyses for a brand."""
        try:
            query = self.supabase.table("brand_ad_analysis").select("*").eq(
                "brand_id", str(brand_id)
            )

            if analysis_type:
                query = query.eq("analysis_type", analysis_type)

            result = query.order("created_at", desc=True).execute()
            return result.data

        except Exception as e:
            logger.error(f"Failed to get analyses: {e}")
            return []

    def get_research_summary(self, brand_id: UUID) -> Optional[Dict]:
        """Get the research summary for a brand."""
        try:
            result = self.supabase.table("brand_research_summary").select("*").eq(
                "brand_id", str(brand_id)
            ).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to get research summary: {e}")
            return None
