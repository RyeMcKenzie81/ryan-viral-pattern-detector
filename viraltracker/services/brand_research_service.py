"""
BrandResearchService - AI analysis and synthesis for brand research.

This service handles:
- Image analysis with Claude Vision (extracts hooks, benefits, visual style)
- Video analysis with Gemini (transcripts, storyboards, hooks)
- Synthesis of insights into brand research summary
- Export to product data format for onboarding

Part of the Brand Research Pipeline (Phase 2A: Analysis).
"""

import logging
import json
import base64
import time
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client
from ..core.config import Config

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


VIDEO_ANALYSIS_PROMPT = """Analyze this Facebook ad video. Extract information for brand research and customer personas.

Return ONLY valid JSON (no markdown, no extra text):

{
    "hook": {
        "transcript": "First 3 seconds spoken words",
        "hook_type": "curiosity|fear|benefit|social_proof|transformation|question|testimonial"
    },
    "full_transcript": "Complete transcript of all spoken words",
    "text_overlays": ["List of text shown on screen"],
    "video_style": {
        "format": "ugc|professional|testimonial|demo|talking_head|mixed",
        "duration_sec": 0,
        "production_quality": "raw|polished|professional"
    },
    "target_persona": {
        "age_range": "estimated target age",
        "gender_focus": "male|female|neutral",
        "lifestyle": ["lifestyle indicators like pet parent, busy professional"],
        "identity_statements": ["I'm the kind of person who...", "Because I care about..."]
    },
    "desires_appealed_to": {
        "care_protection": ["caring for loved ones/pets"],
        "freedom_from_fear": ["relief from worry, health concerns"],
        "social_approval": ["being seen as responsible, good parent"],
        "comfort_convenience": ["making life easier"]
    },
    "transformation": {
        "before": ["problems, frustrations BEFORE product"],
        "after": ["benefits, outcomes AFTER product"]
    },
    "pain_points": {
        "emotional": ["guilt, worry, frustration mentioned"],
        "functional": ["practical problems, failures"]
    },
    "benefits_outcomes": {
        "emotional": ["how they'll feel"],
        "functional": ["practical results"]
    },
    "claims_made": ["specific claims - percentages, results"],
    "testimonial": {
        "has_testimonial": true,
        "speaker_type": "customer|expert|founder|none",
        "key_quotes": ["direct quotes"],
        "results_mentioned": ["specific results achieved"]
    },
    "objections_handled": ["concerns pre-emptively addressed"],
    "failed_solutions_mentioned": ["other products that didn't work"],
    "urgency_triggers": ["limited time, scarcity, act now"],
    "activation_events": ["what triggers purchase - vet visit, symptom noticed"],
    "brand_voice": {
        "tone": "casual|professional|empathetic|urgent",
        "key_phrases": ["notable language patterns"]
    },
    "worldview": {
        "values": ["what brand/customer values"],
        "villains": ["what's positioned as bad"],
        "heroes": ["what's positioned as good"]
    }
}

Extract exact quotes where possible. Return ONLY the JSON object."""


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
        storage_path: str,
        brand_id: Optional[UUID] = None,
        facebook_ad_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze video with Gemini.

        Extracts:
        - Full transcript
        - Hook (first 3 seconds)
        - Text overlays with timestamps
        - Benefits, pain points, claims
        - Testimonial content
        - Product showcase details
        - Call-to-action

        Args:
            asset_id: UUID of the scraped_ad_assets record
            storage_path: Storage path of the video (bucket/path format)
            brand_id: Optional brand to link analysis to
            facebook_ad_id: Optional facebook_ads record to link

        Returns:
            Analysis result dict
        """
        from google import genai

        logger.info(f"Analyzing video asset: {asset_id}")

        # Get API key
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment")

        # Download video to temp file
        temp_path = await self._download_video_to_temp(storage_path)
        if not temp_path:
            raise ValueError(f"Failed to download video: {storage_path}")

        try:
            # Initialize Gemini client
            client = genai.Client(api_key=api_key)
            model_name = Config.GEMINI_VIDEO_MODEL

            logger.info(f"Uploading video to Gemini: {temp_path}")

            # Upload video file to Gemini
            video_file = client.files.upload(file=str(temp_path))
            logger.info(f"Uploaded file to Gemini: {video_file.uri}")

            # Wait for file to be processed
            max_wait = 120  # 2 minutes max
            wait_time = 0
            while video_file.state.name == "PROCESSING" and wait_time < max_wait:
                time.sleep(2)
                wait_time += 2
                video_file = client.files.get(name=video_file.name)

            if video_file.state.name == "FAILED":
                raise ValueError(f"Video processing failed: {video_file.state}")

            if video_file.state.name == "PROCESSING":
                raise ValueError("Video processing timed out")

            logger.info("Video processed, generating analysis...")

            # Generate analysis
            response = client.models.generate_content(
                model=model_name,
                contents=[video_file, VIDEO_ANALYSIS_PROMPT]
            )

            # Parse response
            analysis_text = response.text.strip()
            if analysis_text.startswith('```'):
                first_newline = analysis_text.find('\n')
                last_fence = analysis_text.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    analysis_text = analysis_text[first_newline + 1:last_fence].strip()

            analysis_dict = json.loads(analysis_text)

            # Clean up uploaded file from Gemini
            try:
                client.files.delete(name=video_file.name)
                logger.info("Deleted temporary Gemini file")
            except Exception as e:
                logger.warning(f"Failed to delete Gemini file: {e}")

            # Save to database
            self._save_video_analysis(
                asset_id=asset_id,
                brand_id=brand_id,
                facebook_ad_id=facebook_ad_id,
                raw_response=analysis_dict,
                model_used=model_name
            )

            logger.info(f"Video analysis complete: format={analysis_dict.get('video_style', {}).get('format')}")
            return analysis_dict

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            raise ValueError(f"Invalid JSON response from Gemini: {e}")
        except Exception as e:
            logger.error(f"Video analysis failed: {e}")
            raise
        finally:
            # Clean up temp file
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()
                logger.info(f"Deleted temporary file: {temp_path}")

    async def analyze_videos_batch(
        self,
        asset_ids: List[UUID],
        brand_id: Optional[UUID] = None,
        delay_between: float = 5.0
    ) -> List[Dict]:
        """
        Analyze multiple video assets, storing results in database.

        Args:
            asset_ids: List of scraped_ad_assets UUIDs (videos)
            brand_id: Optional brand to link analyses to
            delay_between: Delay between videos to avoid rate limits (default: 5s)

        Returns:
            List of analysis results
        """
        import asyncio

        results = []

        for i, asset_id in enumerate(asset_ids):
            try:
                # Get asset from database
                asset_result = self.supabase.table("scraped_ad_assets").select(
                    "id, facebook_ad_id, storage_path, mime_type"
                ).eq("id", str(asset_id)).execute()

                if not asset_result.data:
                    logger.warning(f"Asset not found: {asset_id}")
                    continue

                asset = asset_result.data[0]

                # Check if it's a video
                mime_type = asset.get("mime_type", "")
                if not mime_type.startswith("video/"):
                    logger.warning(f"Asset {asset_id} is not a video: {mime_type}")
                    continue

                # Analyze
                analysis = await self.analyze_video(
                    asset_id=UUID(asset["id"]),
                    storage_path=asset["storage_path"],
                    brand_id=brand_id,
                    facebook_ad_id=UUID(asset["facebook_ad_id"]) if asset.get("facebook_ad_id") else None
                )

                results.append({
                    "asset_id": str(asset_id),
                    "analysis": analysis
                })

                # Delay between videos (except for last one)
                if i < len(asset_ids) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to analyze video {asset_id}: {e}")
                results.append({
                    "asset_id": str(asset_id),
                    "error": str(e)
                })
                continue

        logger.info(f"Batch video analysis complete: {len([r for r in results if 'analysis' in r])}/{len(asset_ids)} videos analyzed")
        return results

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

    async def _download_video_to_temp(self, storage_path: str) -> Optional[str]:
        """
        Download video from storage to a temporary file.

        Args:
            storage_path: Storage path in format "bucket/path/to/file.mp4"

        Returns:
            Path to temporary file, or None on failure
        """
        try:
            # Parse bucket and path
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                logger.error(f"Invalid storage path: {storage_path}")
                return None

            bucket = parts[0]
            path = parts[1]

            logger.info(f"Downloading video from {bucket}/{path}")

            # Download from Supabase storage
            data = self.supabase.storage.from_(bucket).download(path)

            # Determine file extension
            ext = Path(path).suffix or '.mp4'

            # Write to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            temp_file.write(data)
            temp_file.close()

            logger.info(f"Video downloaded to: {temp_file.name}")
            return temp_file.name

        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            return None

    def _save_video_analysis(
        self,
        asset_id: UUID,
        brand_id: Optional[UUID],
        facebook_ad_id: Optional[UUID],
        raw_response: Dict,
        model_used: str
    ) -> Optional[UUID]:
        """
        Save video analysis to brand_ad_analysis table.

        Args:
            asset_id: UUID of the scraped_ad_assets record
            brand_id: Optional brand UUID
            facebook_ad_id: Optional facebook_ads UUID
            raw_response: Full analysis response from Gemini
            model_used: Model name used for analysis

        Returns:
            UUID of the saved record, or None on failure
        """
        try:
            # Extract hook info for structured fields
            hook = raw_response.get("hook", {})
            hooks_list = [hook] if hook.get("transcript") else []

            # Extract benefits from the structured format
            benefits_outcomes = raw_response.get("benefits_outcomes", {})
            all_benefits = (
                benefits_outcomes.get("emotional", []) +
                benefits_outcomes.get("functional", [])
            )
            # Also include transformation "after" as benefits
            transformation = raw_response.get("transformation", {})
            all_benefits.extend(transformation.get("after", []))

            # Extract pain points from structured format
            pain_points_data = raw_response.get("pain_points", {})
            if isinstance(pain_points_data, dict):
                all_pain_points = (
                    pain_points_data.get("emotional", []) +
                    pain_points_data.get("functional", [])
                )
            else:
                all_pain_points = pain_points_data if isinstance(pain_points_data, list) else []
            # Also include transformation "before" as pain points
            all_pain_points.extend(transformation.get("before", []))

            record = {
                "asset_id": str(asset_id),
                "brand_id": str(brand_id) if brand_id else None,
                "facebook_ad_id": str(facebook_ad_id) if facebook_ad_id else None,
                "analysis_type": "video_vision",
                "raw_response": raw_response,
                "extracted_hooks": hooks_list,
                "extracted_benefits": all_benefits,
                "extracted_usps": raw_response.get("claims_made", []),
                "pain_points": all_pain_points,
                "persona_signals": raw_response.get("target_persona"),
                "brand_voice_notes": json.dumps(raw_response.get("brand_voice", {})),
                "visual_analysis": raw_response.get("video_style"),
                "model_used": model_used,
                "tokens_used": 0,  # Gemini doesn't report tokens the same way
                "cost_usd": 0.0
            }

            result = self.supabase.table("brand_ad_analysis").insert(record).execute()

            if result.data:
                logger.info(f"Saved video analysis for asset: {asset_id}")
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save video analysis: {e}")
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

    async def analyze_video_from_url(
        self,
        video_url: str,
        facebook_ad_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None
    ) -> Dict:
        """
        Download and analyze a video directly from URL.

        Useful for testing or when videos aren't in storage.

        Args:
            video_url: Direct URL to video file
            facebook_ad_id: Optional facebook_ads record to link
            brand_id: Optional brand to link analysis to

        Returns:
            Analysis result dict
        """
        import httpx
        from google import genai

        logger.info(f"Analyzing video from URL: {video_url[:80]}...")

        # Get API key
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment")

        # Download video to temp file
        temp_path = None
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(video_url)
                if response.status_code != 200:
                    raise ValueError(f"Failed to download video: HTTP {response.status_code}")

                content = response.content
                logger.info(f"Downloaded {len(content) / 1024 / 1024:.1f}MB")

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
            temp_file.write(content)
            temp_file.close()
            temp_path = temp_file.name

            # Initialize Gemini client
            client = genai.Client(api_key=api_key)
            model_name = Config.GEMINI_VIDEO_MODEL

            logger.info(f"Uploading video to Gemini: {temp_path}")

            # Upload video file to Gemini
            video_file = client.files.upload(file=str(temp_path))
            logger.info(f"Uploaded file to Gemini: {video_file.uri}")

            # Wait for file to be processed
            max_wait = 120
            wait_time = 0
            while video_file.state.name == "PROCESSING" and wait_time < max_wait:
                time.sleep(2)
                wait_time += 2
                video_file = client.files.get(name=video_file.name)

            if video_file.state.name == "FAILED":
                raise ValueError(f"Video processing failed: {video_file.state}")

            if video_file.state.name == "PROCESSING":
                raise ValueError("Video processing timed out")

            logger.info("Video processed, generating analysis...")

            # Generate analysis
            response = client.models.generate_content(
                model=model_name,
                contents=[video_file, VIDEO_ANALYSIS_PROMPT]
            )

            # Parse response
            analysis_text = response.text.strip()
            if analysis_text.startswith('```'):
                first_newline = analysis_text.find('\n')
                last_fence = analysis_text.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    analysis_text = analysis_text[first_newline + 1:last_fence].strip()

            analysis_dict = json.loads(analysis_text)

            # Clean up Gemini file
            try:
                client.files.delete(name=video_file.name)
            except Exception:
                pass

            logger.info(f"Video analysis complete: {analysis_dict.get('video_style', {}).get('format')}")
            return analysis_dict

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            raise ValueError(f"Invalid JSON response from Gemini: {e}")
        except Exception as e:
            logger.error(f"Video analysis failed: {e}")
            raise
        finally:
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()

    async def download_assets_for_brand(
        self,
        brand_id: UUID,
        limit: int = 50,
        include_videos: bool = True,
        include_images: bool = True
    ) -> Dict[str, int]:
        """
        Download and store assets (videos/images) for a brand's existing ads.

        Uses AdScrapingService to download from URLs in ad snapshots
        and store in Supabase storage.

        Args:
            brand_id: Brand UUID
            limit: Maximum number of ads to process
            include_videos: Download videos
            include_images: Download images

        Returns:
            Dict with counts: {"ads_processed", "videos_downloaded", "images_downloaded"}
        """
        from .ad_scraping_service import AdScrapingService

        scraping_service = AdScrapingService()

        # Get ads for brand via junction table
        link_result = self.supabase.table("brand_facebook_ads").select(
            "ad_id"
        ).eq("brand_id", str(brand_id)).limit(limit).execute()

        if not link_result.data:
            logger.info(f"No ads found for brand: {brand_id}")
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

        ad_ids = [r['ad_id'] for r in link_result.data]

        # Get ads that don't have assets yet
        existing_assets = self.supabase.table("scraped_ad_assets").select(
            "facebook_ad_id"
        ).in_("facebook_ad_id", ad_ids).execute()

        ads_with_assets = {r['facebook_ad_id'] for r in (existing_assets.data or [])}
        ads_needing_assets = [aid for aid in ad_ids if aid not in ads_with_assets]

        if not ads_needing_assets:
            logger.info(f"All ads already have assets for brand: {brand_id}")
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

        # Get ad snapshots
        ads_result = self.supabase.table("facebook_ads").select(
            "id, snapshot"
        ).in_("id", ads_needing_assets[:limit]).execute()

        total_videos = 0
        total_images = 0
        ads_processed = 0

        for ad in ads_result.data:
            snapshot = ad.get('snapshot', {})
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)

            # Check if has any assets to download
            urls = scraping_service.extract_asset_urls(snapshot)
            if not urls.get('videos') and not urls.get('images'):
                continue

            try:
                result = await scraping_service.scrape_and_store_assets(
                    facebook_ad_id=UUID(ad['id']),
                    snapshot=snapshot,
                    brand_id=brand_id,
                    scrape_source="brand_research_backfill"
                )

                if include_videos:
                    total_videos += len(result.get('videos', []))
                if include_images:
                    total_images += len(result.get('images', []))

                ads_processed += 1
                logger.info(f"Downloaded assets for ad {ad['id'][:8]}: {len(result.get('videos', []))} videos, {len(result.get('images', []))} images")

            except Exception as e:
                logger.error(f"Failed to download assets for ad {ad['id']}: {e}")
                continue

        logger.info(f"Asset download complete: {ads_processed} ads, {total_videos} videos, {total_images} images")
        return {
            "ads_processed": ads_processed,
            "videos_downloaded": total_videos,
            "images_downloaded": total_images
        }

    def get_video_assets_for_brand(
        self,
        brand_id: UUID,
        only_unanalyzed: bool = True,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get video assets for a brand.

        Uses junction table brand_facebook_ads to find ads, then gets video assets.

        Args:
            brand_id: Brand UUID
            only_unanalyzed: If True, exclude assets that already have video analysis
            limit: Maximum number of assets to return

        Returns:
            List of video asset records with storage paths
        """
        try:
            # 1. Get ad IDs from junction table
            link_result = self.supabase.table("brand_facebook_ads").select(
                "ad_id"
            ).eq("brand_id", str(brand_id)).execute()

            if not link_result.data:
                logger.info(f"No ads found for brand: {brand_id}")
                return []

            ad_ids = [r['ad_id'] for r in link_result.data]

            # 2. Get video assets for these ads
            assets_result = self.supabase.table("scraped_ad_assets").select(
                "id, facebook_ad_id, storage_path, mime_type, file_size_bytes"
            ).in_("facebook_ad_id", ad_ids).like("mime_type", "video/%").limit(limit * 2).execute()

            if not assets_result.data:
                logger.info(f"No video assets found for brand: {brand_id}")
                return []

            video_assets = assets_result.data

            # 3. Filter out already analyzed if requested
            if only_unanalyzed:
                asset_ids = [a['id'] for a in video_assets]
                analyzed_result = self.supabase.table("brand_ad_analysis").select(
                    "asset_id"
                ).in_("asset_id", asset_ids).eq("analysis_type", "video_vision").execute()

                analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
                video_assets = [a for a in video_assets if a['id'] not in analyzed_ids]

            logger.info(f"Found {len(video_assets)} video assets for brand {brand_id}")
            return video_assets[:limit]

        except Exception as e:
            logger.error(f"Failed to get video assets: {e}")
            return []
