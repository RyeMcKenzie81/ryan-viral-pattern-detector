"""
BrandResearchService - AI analysis and synthesis for brand research.

This service handles:
- Image analysis with Gemini Vision (extracts hooks, benefits, visual style)
- Video analysis with Gemini (transcripts, storyboards, hooks)
- Copy analysis with Claude (text-based analysis)
- Synthesis of insights into 4D personas
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


COPY_ANALYSIS_PROMPT = """Analyze this Facebook ad copy for brand research and customer persona insights.

Ad Copy:
{ad_copy}

Return ONLY valid JSON:

{{
    "hook": {{
        "text": "The opening hook/first sentence",
        "hook_type": "curiosity|fear|benefit|social_proof|question|transformation|statistic"
    }},
    "headline": "Main headline if present",
    "target_persona": {{
        "age_range": "estimated target age",
        "gender_focus": "male|female|neutral",
        "lifestyle": ["lifestyle indicators"],
        "identity_statements": ["I'm the kind of person who...", "Because I..."]
    }},
    "desires_appealed_to": {{
        "care_protection": ["caring for loved ones"],
        "freedom_from_fear": ["relief from worry"],
        "social_approval": ["being seen as good"],
        "comfort_convenience": ["making life easier"]
    }},
    "transformation": {{
        "before": ["problems before product"],
        "after": ["benefits after product"]
    }},
    "pain_points": {{
        "emotional": ["guilt, worry, frustration"],
        "functional": ["practical problems"]
    }},
    "benefits_outcomes": {{
        "emotional": ["how they'll feel"],
        "functional": ["practical results"]
    }},
    "claims_made": ["specific claims with numbers/results"],
    "objections_handled": ["concerns addressed"],
    "failed_solutions_mentioned": ["other products that didn't work"],
    "urgency_triggers": ["limited time, scarcity"],
    "social_proof": {{
        "type": "testimonial|statistic|authority|none",
        "details": ["specific proof mentioned"]
    }},
    "call_to_action": "The CTA phrase",
    "brand_voice": {{
        "tone": "casual|professional|empathetic|urgent",
        "key_phrases": ["notable language patterns"]
    }},
    "worldview": {{
        "values": ["what brand/customer values"],
        "villains": ["what's bad"],
        "heroes": ["what's good"]
    }}
}}

Extract exact quotes where possible. Return ONLY valid JSON."""


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
        Analyze image with Gemini Vision.

        Uses Gemini instead of Claude Vision to support larger files (up to 20MB)
        and more lenient mime type handling.

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
            mime_type: MIME type of the image (used for logging only)

        Returns:
            Analysis result dict
        """
        from google import genai
        from PIL import Image
        from io import BytesIO

        logger.info(f"Analyzing image asset: {asset_id} (using Gemini)")

        # Get API key
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment")

        try:
            # Initialize Gemini client
            client = genai.Client(api_key=api_key)
            model_name = "gemini-2.0-flash-exp"

            # Decode base64 to PIL Image
            # Clean and decode base64 image
            clean_data = image_base64.strip().replace('\n', '').replace('\r', '').replace(' ', '')
            # Add padding if necessary
            missing_padding = len(clean_data) % 4
            if missing_padding:
                clean_data += '=' * (4 - missing_padding)

            image_bytes = base64.b64decode(clean_data)
            image = Image.open(BytesIO(image_bytes))

            logger.info(f"Image decoded: {image.size[0]}x{image.size[1]}, mode={image.mode}")

            # Generate analysis using Gemini
            response = client.models.generate_content(
                model=model_name,
                contents=[image, IMAGE_ANALYSIS_PROMPT]
            )

            analysis_text = response.text.strip()

            # Strip markdown code fences if present
            if analysis_text.startswith('```'):
                first_newline = analysis_text.find('\n')
                last_fence = analysis_text.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    analysis_text = analysis_text[first_newline + 1:last_fence].strip()

            analysis_dict = json.loads(analysis_text)

            # Save to database
            self._save_analysis(
                asset_id=asset_id,
                brand_id=brand_id,
                facebook_ad_id=facebook_ad_id,
                analysis_type="image_vision",
                raw_response=analysis_dict,
                tokens_used=0,  # Gemini doesn't report tokens the same way
                model_used=model_name
            )

            logger.info(f"Image analysis complete: format={analysis_dict.get('format_type')}")
            return analysis_dict

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            raise ValueError(f"Invalid JSON response from Gemini: {e}")
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            raise

    async def analyze_images_batch(
        self,
        asset_ids: List[UUID],
        brand_id: Optional[UUID] = None,
        delay_between: float = 2.0
    ) -> List[Dict]:
        """
        Analyze multiple images using Gemini, storing results in database.

        Args:
            asset_ids: List of scraped_ad_assets UUIDs
            brand_id: Optional brand to link analyses to
            delay_between: Delay between images to avoid rate limits (default: 2s)

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

                # Delay between images (except for last one)
                if i < len(asset_ids) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to analyze asset {asset_id}: {e}")
                results.append({
                    "asset_id": str(asset_id),
                    "error": str(e)
                })
                continue

        logger.info(f"Batch image analysis complete: {len([r for r in results if 'analysis' in r])}/{len(asset_ids)} images analyzed")
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

    async def analyze_copy(
        self,
        ad_id: UUID,
        ad_copy: str,
        headline: Optional[str] = None,
        brand_id: Optional[UUID] = None
    ) -> Dict:
        """
        Analyze ad copy text with Claude.

        Extracts persona signals, pain points, benefits, hooks from ad text.

        Args:
            ad_id: UUID of the facebook_ads record
            ad_copy: The ad body text
            headline: Optional headline text
            brand_id: Optional brand to link analysis to

        Returns:
            Analysis result dict
        """
        from anthropic import Anthropic

        logger.info(f"Analyzing copy for ad: {ad_id}")

        # Combine headline and body
        full_copy = ""
        if headline:
            full_copy = f"Headline: {headline}\n\n"
        full_copy += ad_copy

        if not full_copy.strip():
            logger.warning(f"Empty copy for ad: {ad_id}")
            return {"error": "Empty ad copy"}

        try:
            client = Anthropic()

            prompt = COPY_ANALYSIS_PROMPT.format(ad_copy=full_copy)

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse response
            response_text = message.content[0].text.strip()
            if response_text.startswith('```'):
                first_newline = response_text.find('\n')
                last_fence = response_text.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    response_text = response_text[first_newline + 1:last_fence].strip()

            analysis_dict = json.loads(response_text)

            # Save to database
            self._save_copy_analysis(
                ad_id=ad_id,
                brand_id=brand_id,
                raw_response=analysis_dict
            )

            logger.info(f"Copy analysis complete for ad: {ad_id}")
            return analysis_dict

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse copy analysis response: {e}")
            logger.error(f"Raw response was: {response_text[:500]}...")
            raise ValueError(f"Invalid JSON response: {e}")
        except Exception as e:
            logger.error(f"Copy analysis failed: {e}")
            raise

    async def analyze_copy_batch(
        self,
        brand_id: UUID,
        limit: int = 50,
        delay_between: float = 2.0,
        ad_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Analyze copy for all ads of a brand.

        Args:
            brand_id: Brand UUID
            limit: Maximum ads to process
            delay_between: Delay between API calls
            ad_ids: Optional list of specific ad IDs to process (for product filtering)

        Returns:
            List of analysis results
        """
        import asyncio

        # Use provided ad_ids or get ALL ads for brand via junction table
        if ad_ids is None:
            link_result = self.supabase.table("brand_facebook_ads").select(
                "ad_id"
            ).eq("brand_id", str(brand_id)).execute()

            if not link_result.data:
                logger.info(f"No ads found for brand: {brand_id}")
                return []

            ad_ids = [r['ad_id'] for r in link_result.data]
        else:
            if not ad_ids:
                logger.info(f"No ads provided for brand: {brand_id}")
                return []

        # Get ads with snapshots (copy is stored in snapshot JSON)
        ads_result = self.supabase.table("facebook_ads").select(
            "id, snapshot"
        ).in_("id", ad_ids).execute()

        # Check which already analyzed
        analyzed_result = self.supabase.table("brand_ad_analysis").select(
            "facebook_ad_id"
        ).in_("facebook_ad_id", ad_ids).eq("analysis_type", "copy_analysis").execute()

        analyzed_ids = {r['facebook_ad_id'] for r in (analyzed_result.data or [])}

        results = []
        ads_to_process = []
        for ad in ads_result.data:
            if ad['id'] in analyzed_ids:
                continue

            # Extract copy from snapshot JSON
            snapshot = ad.get('snapshot', {})
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)

            # Get body text from snapshot.body.text
            body_data = snapshot.get('body', {})
            ad_copy = body_data.get('text', '') if isinstance(body_data, dict) else ''

            # Get headline from snapshot.title
            headline = snapshot.get('title', '')

            if not ad_copy and not headline:
                continue

            # Skip dynamic product catalog ads (contain template variables)
            # Save a "skipped" record so they don't keep showing as pending
            combined_text = f"{ad_copy} {headline}"
            if '{{product.' in combined_text or '{{' in combined_text:
                logger.info(f"Skipping dynamic catalog ad {ad['id']} (contains template variables)")
                self._save_skipped_analysis(
                    ad_id=UUID(ad['id']),
                    brand_id=brand_id,
                    analysis_type="copy_analysis",
                    reason="dynamic_catalog_ad"
                )
                continue

            ads_to_process.append((ad, ad_copy, headline))

        # Apply limit AFTER filtering to ads that need processing
        total_needing = len(ads_to_process)
        ads_to_process = ads_to_process[:limit]
        logger.info(f"Processing {len(ads_to_process)} of {total_needing} ads for copy analysis (limit={limit})")

        for i, (ad, ad_copy, headline) in enumerate(ads_to_process):
            # Delay BEFORE each request (except first) to avoid rate limits
            if i > 0:
                await asyncio.sleep(delay_between)

            try:
                analysis = await self.analyze_copy(
                    ad_id=UUID(ad['id']),
                    ad_copy=ad_copy or '',
                    headline=headline,
                    brand_id=brand_id
                )
                results.append({"ad_id": ad['id'], "analysis": analysis})
                logger.info(f"Copy analysis {i+1}/{len(ads_to_process)} complete")

            except Exception as e:
                logger.error(f"Failed to analyze copy for ad {ad['id']}: {e}")
                results.append({"ad_id": ad['id'], "error": str(e)})

        logger.info(f"Batch copy analysis complete: {len([r for r in results if 'analysis' in r])}/{len(ads_result.data)} ads analyzed")
        return results

    def _save_copy_analysis(
        self,
        ad_id: UUID,
        brand_id: Optional[UUID],
        raw_response: Dict
    ) -> Optional[UUID]:
        """Save copy analysis to brand_ad_analysis table."""
        try:
            # Extract structured fields
            hook = raw_response.get("hook", {})
            hooks_list = [hook] if hook.get("text") else []

            benefits_outcomes = raw_response.get("benefits_outcomes", {})
            all_benefits = (
                benefits_outcomes.get("emotional", []) +
                benefits_outcomes.get("functional", [])
            )
            transformation = raw_response.get("transformation", {})
            all_benefits.extend(transformation.get("after", []))

            pain_points_data = raw_response.get("pain_points", {})
            all_pain_points = (
                pain_points_data.get("emotional", []) +
                pain_points_data.get("functional", [])
            )
            all_pain_points.extend(transformation.get("before", []))

            record = {
                "brand_id": str(brand_id) if brand_id else None,
                "facebook_ad_id": str(ad_id),
                "analysis_type": "copy_analysis",
                "raw_response": raw_response,
                "extracted_hooks": hooks_list,
                "extracted_benefits": all_benefits,
                "extracted_usps": raw_response.get("claims_made", []),
                "pain_points": all_pain_points,
                "persona_signals": raw_response.get("target_persona"),
                "brand_voice_notes": json.dumps(raw_response.get("brand_voice", {})),
                "model_used": "claude-sonnet-4-20250514",
                "tokens_used": 0,
                "cost_usd": 0.0
            }

            result = self.supabase.table("brand_ad_analysis").insert(record).execute()

            if result.data:
                logger.info(f"Saved copy analysis for ad: {ad_id}")
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save copy analysis: {e}")
            return None

    def _save_skipped_analysis(
        self,
        ad_id: UUID,
        brand_id: Optional[UUID],
        analysis_type: str,
        reason: str
    ) -> Optional[UUID]:
        """Save a record for skipped analysis so it doesn't show as pending."""
        try:
            # Check if already exists
            existing = self.supabase.table("brand_ad_analysis").select("id").eq(
                "facebook_ad_id", str(ad_id)
            ).eq("analysis_type", analysis_type).execute()

            if existing.data:
                return UUID(existing.data[0]["id"])

            record = {
                "brand_id": str(brand_id) if brand_id else None,
                "facebook_ad_id": str(ad_id),
                "analysis_type": analysis_type,
                "raw_response": {"skipped": True, "reason": reason},
                "extracted_hooks": [],
                "extracted_benefits": [],
                "extracted_usps": [],
                "pain_points": [],
                "model_used": "skipped",
                "tokens_used": 0,
                "cost_usd": 0.0
            }

            result = self.supabase.table("brand_ad_analysis").insert(record).execute()

            if result.data:
                logger.info(f"Saved skipped analysis for ad: {ad_id} (reason: {reason})")
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save skipped analysis: {e}")
            return None

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
        tokens_used: int = 0,
        model_used: str = "gemini-2.0-flash-exp"
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
                "model_used": model_used,
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
        include_images: bool = True,
        ad_ids: Optional[List[str]] = None
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
            ad_ids: Optional list of specific ad IDs to process (for product filtering)

        Returns:
            Dict with counts: {"ads_processed", "videos_downloaded", "images_downloaded"}
        """
        from .ad_scraping_service import AdScrapingService

        scraping_service = AdScrapingService()

        # Use provided ad_ids or get all ads for brand via junction table
        if ad_ids is None:
            link_result = self.supabase.table("brand_facebook_ads").select(
                "ad_id"
            ).eq("brand_id", str(brand_id)).execute()

            if not link_result.data:
                logger.info(f"No ads found for brand: {brand_id}")
                return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

            ad_ids = [r['ad_id'] for r in link_result.data]
        else:
            if not ad_ids:
                logger.info(f"No ads provided for brand: {brand_id}")
                return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

        # Get ads that already have assets
        existing_assets = self.supabase.table("scraped_ad_assets").select(
            "facebook_ad_id"
        ).in_("facebook_ad_id", ad_ids).execute()

        ads_with_assets = {r['facebook_ad_id'] for r in (existing_assets.data or [])}
        ads_needing_assets = [aid for aid in ad_ids if aid not in ads_with_assets]

        logger.info(f"Brand {brand_id}: {len(ad_ids)} total ads, {len(ads_with_assets)} with assets, {len(ads_needing_assets)} needing download")

        if not ads_needing_assets:
            logger.info(f"All ads already have assets for brand: {brand_id}")
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

        # Apply limit AFTER filtering to ads that need assets
        ads_to_process = ads_needing_assets[:limit]
        logger.info(f"Processing {len(ads_to_process)} ads (limit={limit})")

        # Get ad snapshots
        ads_result = self.supabase.table("facebook_ads").select(
            "id, snapshot"
        ).in_("id", ads_to_process).execute()

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
                logger.info(f"Starting download for ad {ad['id'][:8]}: {len(urls.get('videos', []))} videos, {len(urls.get('images', []))} images to download")

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

                # Log if nothing was downloaded despite having URLs
                if len(urls.get('videos', [])) > 0 and len(result.get('videos', [])) == 0:
                    logger.warning(f"Ad {ad['id'][:8]}: Had {len(urls['videos'])} video URLs but downloaded 0")
                if len(urls.get('images', [])) > 0 and len(result.get('images', [])) == 0:
                    logger.warning(f"Ad {ad['id'][:8]}: Had {len(urls['images'])} image URLs but downloaded 0")

                logger.info(f"Completed ad {ad['id'][:8]}: {len(result.get('videos', []))} videos, {len(result.get('images', []))} images stored")

            except Exception as e:
                logger.error(f"Failed to download assets for ad {ad['id']}: {e}", exc_info=True)
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

    async def analyze_videos_for_brand(
        self,
        brand_id: UUID,
        limit: int = 10,
        delay_between: float = 5.0,
        ad_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Fetch and analyze videos for a brand in one async operation.

        This method combines fetching unanalyzed video assets and analyzing them
        in a single async context, avoiding event loop issues when called from
        Streamlit's sync environment via asyncio.run().

        Args:
            brand_id: Brand UUID
            limit: Maximum videos to analyze
            delay_between: Delay between videos for rate limiting (default: 5s)
            ad_ids: Optional list of specific ad IDs to process (for product filtering)

        Returns:
            List of analysis results
        """
        import asyncio

        logger.info(f"Starting video analysis for brand: {brand_id}, limit={limit}")

        # 1. Use provided ad_ids or get from junction table
        if ad_ids is None:
            link_result = self.supabase.table("brand_facebook_ads").select(
                "ad_id"
            ).eq("brand_id", str(brand_id)).execute()

            if not link_result.data:
                logger.info(f"No ads found for brand: {brand_id}")
                return []

            ad_ids = [r['ad_id'] for r in link_result.data]
        else:
            if not ad_ids:
                logger.info(f"No ads provided for brand: {brand_id}")
                return []

        # 2. Get ALL video assets for these ads (no limit yet)
        assets_result = self.supabase.table("scraped_ad_assets").select(
            "id, facebook_ad_id, storage_path, mime_type, file_size_bytes"
        ).in_("facebook_ad_id", ad_ids).like("mime_type", "video/%").execute()

        if not assets_result.data:
            logger.info(f"No video assets found for brand: {brand_id}")
            return []

        video_assets = assets_result.data

        # 3. Filter out already analyzed
        asset_ids = [a['id'] for a in video_assets]
        analyzed_result = self.supabase.table("brand_ad_analysis").select(
            "asset_id"
        ).in_("asset_id", asset_ids).eq("analysis_type", "video_vision").execute()

        analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
        unanalyzed = [a for a in video_assets if a['id'] not in analyzed_ids]

        # 4. Apply limit AFTER filtering
        total_unanalyzed = len(unanalyzed)
        videos_to_analyze = unanalyzed[:limit]
        logger.info(f"Processing {len(videos_to_analyze)} of {total_unanalyzed} unanalyzed videos (limit={limit})")

        if not videos_to_analyze:
            logger.info("No unanalyzed videos to process")
            return []

        # 5. Analyze each video
        results = []
        for i, asset in enumerate(videos_to_analyze):
            try:
                # Check mime type
                mime_type = asset.get("mime_type", "")
                if not mime_type.startswith("video/"):
                    logger.warning(f"Asset {asset['id']} is not a video: {mime_type}")
                    continue

                # Analyze
                analysis = await self.analyze_video(
                    asset_id=UUID(asset["id"]),
                    storage_path=asset["storage_path"],
                    brand_id=brand_id,
                    facebook_ad_id=UUID(asset["facebook_ad_id"]) if asset.get("facebook_ad_id") else None
                )

                results.append({
                    "asset_id": str(asset["id"]),
                    "analysis": analysis
                })

                logger.info(f"Video analysis {i+1}/{len(videos_to_analyze)} complete")

                # Delay between videos (except for last one)
                if i < len(videos_to_analyze) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to analyze video {asset['id']}: {e}")
                results.append({
                    "asset_id": str(asset["id"]),
                    "error": str(e)
                })
                continue

        logger.info(f"Video analysis complete: {len([r for r in results if 'analysis' in r])}/{len(videos_to_analyze)} videos analyzed")
        return results

    async def analyze_images_for_brand(
        self,
        brand_id: UUID,
        limit: int = 20,
        delay_between: float = 2.0,
        ad_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Fetch and analyze images for a brand in one async operation.

        This method combines fetching unanalyzed image assets and analyzing them
        in a single async context, avoiding event loop issues when called from
        Streamlit's sync environment via asyncio.run().

        Args:
            brand_id: Brand UUID
            limit: Maximum images to analyze
            delay_between: Delay between images for rate limiting (default: 2s)
            ad_ids: Optional list of specific ad IDs to process (for product filtering)

        Returns:
            List of analysis results
        """
        import asyncio

        logger.info(f"Starting image analysis for brand: {brand_id}, limit={limit}")

        # 1. Use provided ad_ids or get from junction table
        if ad_ids is None:
            link_result = self.supabase.table("brand_facebook_ads").select(
                "ad_id"
            ).eq("brand_id", str(brand_id)).execute()

            if not link_result.data:
                logger.info(f"No ads found for brand: {brand_id}")
                return []

            ad_ids = [r['ad_id'] for r in link_result.data]
        else:
            if not ad_ids:
                logger.info(f"No ads provided for brand: {brand_id}")
                return []

        # 2. Get ALL image assets for these ads (no limit yet)
        assets_result = self.supabase.table("scraped_ad_assets").select(
            "id, facebook_ad_id, storage_path, mime_type"
        ).in_("facebook_ad_id", ad_ids).like("mime_type", "image/%").execute()

        if not assets_result.data:
            logger.info(f"No image assets found for brand: {brand_id}")
            return []

        image_assets = assets_result.data

        # 3. Filter out already analyzed
        asset_ids = [a['id'] for a in image_assets]
        analyzed_result = self.supabase.table("brand_ad_analysis").select(
            "asset_id"
        ).in_("asset_id", asset_ids).eq("analysis_type", "image_vision").execute()

        analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
        unanalyzed = [a for a in image_assets if a['id'] not in analyzed_ids]

        # 4. Apply limit AFTER filtering
        total_unanalyzed = len(unanalyzed)
        images_to_analyze = unanalyzed[:limit]
        logger.info(f"Processing {len(images_to_analyze)} of {total_unanalyzed} unanalyzed images (limit={limit})")

        if not images_to_analyze:
            logger.info("No unanalyzed images to process")
            return []

        # 5. Analyze each image
        results = []
        for i, asset in enumerate(images_to_analyze):
            try:
                # Download image from storage
                image_base64 = await self._get_asset_base64(asset["storage_path"])
                if not image_base64:
                    logger.warning(f"Failed to download asset: {asset['id']}")
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
                    "asset_id": str(asset["id"]),
                    "analysis": analysis
                })

                logger.info(f"Image analysis {i+1}/{len(images_to_analyze)} complete")

                # Delay between images (except for last one)
                if i < len(images_to_analyze) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to analyze image {asset['id']}: {e}")
                results.append({
                    "asset_id": str(asset["id"]),
                    "error": str(e)
                })
                continue

        logger.info(f"Image analysis complete: {len([r for r in results if 'analysis' in r])}/{len(images_to_analyze)} images analyzed")
        return results

    async def synthesize_to_personas(
        self,
        brand_id: UUID,
        max_personas: int = 3
    ) -> List[Dict]:
        """
        Synthesize all analyses into suggested 4D personas.

        Aggregates video, image, and copy analyses to:
        1. Detect distinct customer segments/clusters
        2. Generate 1-3 suggested 4D personas
        3. Populate all 4D fields from aggregated data
        4. Include confidence scoring per persona

        Args:
            brand_id: Brand UUID to synthesize for
            max_personas: Maximum number of personas to generate (1-3)

        Returns:
            List of persona dictionaries ready for PersonaService._build_persona_from_ai_response
        """
        from anthropic import Anthropic

        logger.info(f"Synthesizing personas for brand: {brand_id}")

        # Get all analyses for brand
        analyses = self.get_analyses_for_brand(brand_id)

        if not analyses:
            logger.warning(f"No analyses found for brand: {brand_id}")
            return []

        # Aggregate data from all analyses
        aggregated = self._aggregate_analyses(analyses)

        if not aggregated.get("has_data"):
            logger.warning("Insufficient data for persona synthesis")
            return []

        # Build synthesis prompt
        prompt = PERSONA_SYNTHESIS_PROMPT.format(
            max_personas=max_personas,
            aggregated_data=json.dumps(aggregated, indent=2, default=str)
        )

        try:
            client = Anthropic()

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=6000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Strip markdown code fences if present
            if response_text.startswith('```'):
                first_newline = response_text.find('\n')
                last_fence = response_text.rfind('```')
                if first_newline != -1 and last_fence > first_newline:
                    response_text = response_text[first_newline + 1:last_fence].strip()

            result = json.loads(response_text)
            personas = result.get("personas", [])

            logger.info(f"Synthesized {len(personas)} personas for brand: {brand_id}")

            # Save synthesis record
            self._save_synthesis_record(brand_id, aggregated, personas)

            return personas

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse synthesis response: {e}")
            raise ValueError(f"Invalid JSON response: {e}")
        except Exception as e:
            logger.error(f"Persona synthesis failed: {e}")
            raise

    def _aggregate_analyses(self, analyses: List[Dict]) -> Dict[str, Any]:
        """
        Aggregate data from multiple analyses for synthesis.

        Collects and deduplicates:
        - Persona signals (demographics, lifestyle)
        - Pain points (emotional, functional)
        - Desires by category
        - Benefits and outcomes
        - Hooks and messaging patterns
        - Brand voice characteristics
        - Transformation signals (before/after)
        - Objections and failed solutions
        - Activation events

        Args:
            analyses: List of analysis records from brand_ad_analysis

        Returns:
            Aggregated data dictionary
        """
        aggregated = {
            "persona_signals": [],
            "pain_points": {"emotional": [], "functional": []},
            "desires": {
                "care_protection": [],
                "freedom_from_fear": [],
                "social_approval": [],
                "comfort_convenience": [],
                "superiority_status": [],
                "self_actualization": []
            },
            "benefits": {"emotional": [], "functional": []},
            "transformation": {"before": [], "after": []},
            "hooks": [],
            "brand_voice": [],
            "objections": [],
            "failed_solutions": [],
            "activation_events": [],
            "testimonials": [],
            "worldview": {"values": [], "villains": [], "heroes": []},
            "analysis_counts": {
                "video": 0,
                "image": 0,
                "copy": 0
            },
            "has_data": False
        }

        for analysis in analyses:
            analysis_type = analysis.get("analysis_type", "")
            raw = analysis.get("raw_response", {})

            if not raw:
                continue

            # Count by type
            if analysis_type == "video_vision":
                aggregated["analysis_counts"]["video"] += 1
            elif analysis_type == "image_vision":
                aggregated["analysis_counts"]["image"] += 1
            elif analysis_type == "copy_analysis":
                aggregated["analysis_counts"]["copy"] += 1

            # Extract persona signals
            persona_signals = raw.get("target_persona") or raw.get("persona_signals")
            if persona_signals:
                aggregated["persona_signals"].append(persona_signals)

            # Extract pain points
            pain_data = raw.get("pain_points", {})
            if isinstance(pain_data, dict):
                aggregated["pain_points"]["emotional"].extend(pain_data.get("emotional", []))
                aggregated["pain_points"]["functional"].extend(pain_data.get("functional", []))

            # Also get pain from transformation "before"
            transformation = raw.get("transformation", {})
            if transformation.get("before"):
                aggregated["transformation"]["before"].extend(transformation["before"])
            if transformation.get("after"):
                aggregated["transformation"]["after"].extend(transformation["after"])

            # Extract desires
            desires_data = raw.get("desires_appealed_to", {})
            if isinstance(desires_data, dict):
                for category, items in desires_data.items():
                    if category in aggregated["desires"] and items:
                        aggregated["desires"][category].extend(items if isinstance(items, list) else [items])

            # Extract benefits/outcomes
            benefits_data = raw.get("benefits_outcomes", {})
            if isinstance(benefits_data, dict):
                aggregated["benefits"]["emotional"].extend(benefits_data.get("emotional", []))
                aggregated["benefits"]["functional"].extend(benefits_data.get("functional", []))

            # Extract hooks
            hooks = raw.get("hooks", []) or raw.get("extracted_hooks", [])
            if hooks:
                aggregated["hooks"].extend(hooks if isinstance(hooks, list) else [hooks])

            hook = raw.get("hook", {})
            if hook and (hook.get("transcript") or hook.get("text")):
                aggregated["hooks"].append(hook)

            # Extract brand voice
            brand_voice = raw.get("brand_voice", {})
            if brand_voice:
                aggregated["brand_voice"].append(brand_voice)

            # Extract objections
            objections = raw.get("objections_handled", [])
            if objections:
                aggregated["objections"].extend(objections)

            # Extract failed solutions
            failed = raw.get("failed_solutions_mentioned", [])
            if failed:
                aggregated["failed_solutions"].extend(failed)

            # Extract activation events
            activation = raw.get("activation_events", [])
            if activation:
                aggregated["activation_events"].extend(activation)

            # Extract testimonials
            testimonial = raw.get("testimonial", {})
            if testimonial and testimonial.get("has_testimonial"):
                aggregated["testimonials"].append(testimonial)

            # Extract worldview
            worldview = raw.get("worldview", {})
            if isinstance(worldview, dict):
                aggregated["worldview"]["values"].extend(worldview.get("values", []))
                aggregated["worldview"]["villains"].extend(worldview.get("villains", []))
                aggregated["worldview"]["heroes"].extend(worldview.get("heroes", []))

            aggregated["has_data"] = True

        # Deduplicate lists
        for key in ["pain_points", "benefits"]:
            for subkey in aggregated[key]:
                aggregated[key][subkey] = list(set(aggregated[key][subkey]))

        for category in aggregated["desires"]:
            # Flatten if nested and deduplicate
            flat = []
            for item in aggregated["desires"][category]:
                if isinstance(item, list):
                    flat.extend(item)
                else:
                    flat.append(item)
            aggregated["desires"][category] = list(set(flat))

        aggregated["transformation"]["before"] = list(set(aggregated["transformation"]["before"]))
        aggregated["transformation"]["after"] = list(set(aggregated["transformation"]["after"]))
        aggregated["objections"] = list(set(aggregated["objections"]))
        aggregated["failed_solutions"] = list(set(aggregated["failed_solutions"]))
        aggregated["activation_events"] = list(set(aggregated["activation_events"]))

        for key in aggregated["worldview"]:
            aggregated["worldview"][key] = list(set(aggregated["worldview"][key]))

        return aggregated

    def _save_synthesis_record(
        self,
        brand_id: UUID,
        aggregated: Dict,
        personas: List[Dict]
    ) -> Optional[UUID]:
        """Save synthesis record to brand_ad_analysis table."""
        try:
            record = {
                "brand_id": str(brand_id),
                "analysis_type": "synthesis",
                "raw_response": {
                    "aggregated_input": aggregated,
                    "generated_personas": personas
                },
                "extracted_hooks": [],
                "extracted_benefits": [],
                "pain_points": [],
                "persona_signals": {"persona_count": len(personas)},
                "model_used": "claude-sonnet-4-20250514",
                "tokens_used": 0,
                "cost_usd": 0.0
            }

            result = self.supabase.table("brand_ad_analysis").insert(record).execute()

            if result.data:
                logger.info(f"Saved synthesis record for brand: {brand_id}")
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save synthesis record: {e}")
            return None

    async def scrape_landing_pages_for_brand(
        self,
        brand_id: UUID,
        limit: int = 20,
        delay_between: float = 2.0,
        product_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Scrape landing pages for a brand using URL patterns from product_urls.

        This method:
        1. Gets URL patterns from product_urls table (already deduplicated, linked to products)
        2. Filters out already-scraped URLs
        3. Scrapes each URL with FireCrawl
        4. Stores raw content and extracted data

        Args:
            brand_id: Brand UUID
            limit: Maximum pages to scrape
            delay_between: Delay between scrapes for rate limiting
            product_id: Optional product UUID to filter to specific product

        Returns:
            Dict with counts: {"urls_found", "pages_scraped", "pages_failed"}
        """
        import asyncio
        from .web_scraping_service import WebScrapingService, LANDING_PAGE_SCHEMA

        logger.info(f"Starting landing page scrape for brand: {brand_id}, limit={limit}, product_id={product_id}")

        # 1. Get products for this brand (or use specific product)
        if product_id:
            product_ids = [str(product_id)]
        else:
            products_result = self.supabase.table("products").select(
                "id"
            ).eq("brand_id", str(brand_id)).execute()

            if not products_result.data:
                logger.info(f"No products found for brand: {brand_id}")
                return {"urls_found": 0, "pages_scraped": 0, "pages_failed": 0}

            product_ids = [p['id'] for p in products_result.data]

        # 2. Get URL patterns from product_urls table
        urls_result = self.supabase.table("product_urls").select(
            "url_pattern, product_id"
        ).in_("product_id", product_ids).execute()

        if not urls_result.data:
            logger.info(f"No URL patterns found for brand: {brand_id}")
            return {"urls_found": 0, "pages_scraped": 0, "pages_failed": 0}

        # Build full URLs from patterns (patterns are partial, need https://)
        urls_to_scrape = {}  # url -> product_id mapping
        for row in urls_result.data:
            pattern = row['url_pattern']
            # Add https:// if not present
            if not pattern.startswith('http'):
                full_url = f"https://{pattern}"
            else:
                full_url = pattern
            urls_to_scrape[full_url] = row['product_id']

        logger.info(f"Found {len(urls_to_scrape)} URL patterns for brand")

        # 3. Filter out successfully scraped URLs (allow retry of failed ones)
        existing_result = self.supabase.table("brand_landing_pages").select(
            "id, url, scrape_status"
        ).eq("brand_id", str(brand_id)).execute()

        # Only skip URLs that were successfully scraped or analyzed
        scraped_urls = set()
        failed_ids = []  # Track failed entries to delete before retry
        for r in (existing_result.data or []):
            status = r.get('scrape_status')
            if status in ('scraped', 'analyzed'):
                scraped_urls.add(r['url'])
            elif status == 'failed':
                failed_ids.append(r['id'])

        new_urls = {url: product_id for url, product_id in urls_to_scrape.items() if url not in scraped_urls}

        # Delete failed entries so we can retry them
        if failed_ids:
            logger.info(f"Deleting {len(failed_ids)} failed entries for retry")
            self.supabase.table("brand_landing_pages").delete().in_("id", failed_ids).execute()

        total_found = len(urls_to_scrape)
        logger.info(f"Found {total_found} unique URLs, {len(new_urls)} need scraping")

        if not new_urls:
            logger.info(f"All {total_found} URLs already scraped, nothing to do")
            return {"urls_found": total_found, "pages_scraped": 0, "pages_failed": 0, "already_scraped": len(scraped_urls)}

        # 4. Apply limit
        urls_to_process = list(new_urls.items())[:limit]
        logger.info(f"Processing {len(urls_to_process)} URLs (limit={limit})")

        # 5. Scrape each URL
        scraper = WebScrapingService()
        pages_scraped = 0
        pages_failed = 0

        for i, (url, product_id) in enumerate(urls_to_process):
            try:
                logger.info(f"Scraping {i+1}/{len(urls_to_process)}: {url[:60]}...")

                # Scrape with FireCrawl
                scrape_result = await scraper.scrape_url_async(
                    url=url,
                    formats=["markdown", "links"],
                    only_main_content=True,
                    wait_for=1000,  # Wait 1s for JS
                    timeout=30000
                )

                if not scrape_result.success:
                    logger.warning(f"Failed to scrape {url}: {scrape_result.error}")
                    self._save_landing_page_error(brand_id, url, product_id, scrape_result.error)
                    pages_failed += 1
                    continue

                # Try structured extraction
                extract_result = None
                try:
                    extract_result = scraper.extract_structured(
                        url=url,
                        schema=LANDING_PAGE_SCHEMA
                    )
                except Exception as e:
                    logger.warning(f"Structured extraction failed for {url}: {e}")

                # Save to database (product_id already known from product_urls table)
                self._save_landing_page(
                    brand_id=brand_id,
                    url=url,
                    product_id=product_id,
                    scrape_result=scrape_result,
                    extract_result=extract_result
                )

                pages_scraped += 1
                logger.info(f"Scraped page {i+1}/{len(urls_to_process)}")

                # Delay between scrapes (except last)
                if i < len(urls_to_process) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")
                pages_failed += 1
                continue

        logger.info(f"Landing page scrape complete: {pages_scraped} scraped, {pages_failed} failed")
        return {
            "urls_found": total_found,
            "pages_scraped": pages_scraped,
            "pages_failed": pages_failed
        }

    def _clean_url(self, url: str) -> str:
        """Clean URL by removing common tracking parameters."""
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        try:
            parsed = urlparse(url)

            # Parameters to remove
            tracking_params = {
                'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                'fbclid', 'gclid', 'ref', 'mc_cid', 'mc_eid'
            }

            # Parse and filter query params
            params = parse_qs(parsed.query)
            filtered_params = {k: v for k, v in params.items() if k.lower() not in tracking_params}

            # Rebuild URL
            clean_query = urlencode(filtered_params, doseq=True)
            clean_parsed = parsed._replace(query=clean_query)

            return urlunparse(clean_parsed)
        except Exception:
            return url

    def _save_landing_page(
        self,
        brand_id: UUID,
        url: str,
        product_id: Optional[str],
        scrape_result,
        extract_result
    ) -> Optional[UUID]:
        """Save scraped landing page to database.

        Args:
            brand_id: Brand UUID
            url: The landing page URL
            product_id: Product UUID from product_urls table (already matched)
            scrape_result: FireCrawl scrape result
            extract_result: FireCrawl structured extraction result
        """
        try:
            # Extract metadata - may be dict or object
            raw_metadata = scrape_result.metadata
            if raw_metadata is None:
                metadata = {}
            elif isinstance(raw_metadata, dict):
                metadata = raw_metadata
            else:
                # Object with attributes
                metadata = {
                    "title": getattr(raw_metadata, 'title', None),
                    "description": getattr(raw_metadata, 'description', None),
                }

            # Build extracted_data from extract_result
            extracted_data = {}
            if extract_result and extract_result.success and extract_result.data:
                extracted_data = extract_result.data if isinstance(extract_result.data, dict) else {}

            record = {
                "brand_id": str(brand_id),
                "url": url,
                "product_id": str(product_id) if product_id else None,
                "page_title": metadata.get("title") or extracted_data.get("page_title"),
                "meta_description": metadata.get("description") or extracted_data.get("meta_description"),
                "raw_markdown": scrape_result.markdown,
                "extracted_data": extracted_data,
                "product_name": extracted_data.get("product_name"),
                "pricing": extracted_data.get("pricing", {}),
                "benefits": extracted_data.get("benefits", []),
                "features": extracted_data.get("features", []),
                "testimonials": extracted_data.get("testimonials", []),
                "social_proof": extracted_data.get("social_proof", []),
                "call_to_action": extracted_data.get("call_to_action"),
                "objection_handling": extracted_data.get("objection_handling", []),
                "guarantee": extracted_data.get("guarantee"),
                "urgency_elements": extracted_data.get("urgency_elements", []),
                "scrape_status": "scraped",
                "scraped_at": datetime.utcnow().isoformat()
            }

            result = self.supabase.table("brand_landing_pages").insert(record).execute()

            if result.data:
                logger.info(f"Saved landing page: {url[:50]}..." + (f" (product: {product_id})" if product_id else ""))
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.error(f"Failed to save landing page: {e}")
            return None

    def _save_landing_page_error(
        self,
        brand_id: UUID,
        url: str,
        product_id: Optional[str],
        error: str
    ) -> None:
        """Save failed landing page scrape."""
        try:
            record = {
                "brand_id": str(brand_id),
                "url": url,
                "product_id": str(product_id) if product_id else None,
                "scrape_status": "failed",
                "scrape_error": error,
                "scraped_at": datetime.utcnow().isoformat()
            }

            self.supabase.table("brand_landing_pages").insert(record).execute()

        except Exception as e:
            logger.error(f"Failed to save landing page error: {e}")

    async def analyze_landing_pages_for_brand(
        self,
        brand_id: UUID,
        limit: int = 20,
        delay_between: float = 2.0,
        product_id: Optional[UUID] = None
    ) -> List[Dict]:
        """
        Analyze scraped landing pages for persona signals.

        This method:
        1. Gets scraped (but not analyzed) landing pages
        2. Analyzes each with Claude for persona signals
        3. Updates the database with analysis results

        Args:
            brand_id: Brand UUID
            limit: Maximum pages to analyze
            delay_between: Delay between API calls
            product_id: Optional product UUID to filter to specific product

        Returns:
            List of analysis results
        """
        import asyncio
        from anthropic import Anthropic

        logger.info(f"Starting landing page analysis for brand: {brand_id}, limit={limit}, product_id={product_id}")

        # 1. Get scraped but unanalyzed pages
        query = self.supabase.table("brand_landing_pages").select(
            "id, url, raw_markdown, extracted_data, page_title"
        ).eq("brand_id", str(brand_id)).eq("scrape_status", "scraped")

        if product_id:
            query = query.eq("product_id", str(product_id))

        pages_result = query.limit(limit).execute()

        if not pages_result.data:
            logger.info(f"No unanalyzed landing pages for brand: {brand_id}")
            return []

        pages = pages_result.data
        logger.info(f"Analyzing {len(pages)} landing pages")

        # 2. Analyze each page
        client = Anthropic()
        results = []

        for i, page in enumerate(pages):
            try:
                # Delay before each request (except first)
                if i > 0:
                    await asyncio.sleep(delay_between)

                logger.info(f"Analyzing page {i+1}/{len(pages)}: {page['url'][:50]}...")

                # Build prompt
                content = page.get('raw_markdown', '')
                if not content:
                    logger.warning(f"No content for page: {page['id']}")
                    continue

                # Truncate if too long (keep under ~100k chars)
                if len(content) > 80000:
                    content = content[:80000] + "\n\n[Content truncated...]"

                prompt = LANDING_PAGE_ANALYSIS_PROMPT.format(
                    page_title=page.get('page_title', 'Unknown'),
                    url=page['url'],
                    content=content,
                    extracted_data=json.dumps(page.get('extracted_data', {}), indent=2)
                )

                message = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}]
                )

                response_text = message.content[0].text.strip()

                # Strip markdown code fences
                if response_text.startswith('```'):
                    first_newline = response_text.find('\n')
                    last_fence = response_text.rfind('```')
                    if first_newline != -1 and last_fence > first_newline:
                        response_text = response_text[first_newline + 1:last_fence].strip()

                analysis = json.loads(response_text)

                # Save analysis to database
                self._update_landing_page_analysis(
                    page_id=UUID(page['id']),
                    analysis=analysis
                )

                results.append({
                    "page_id": page['id'],
                    "url": page['url'],
                    "analysis": analysis
                })

                logger.info(f"Analyzed page {i+1}/{len(pages)}")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse analysis for {page['id']}: {e}")
                results.append({"page_id": page['id'], "error": str(e)})
            except Exception as e:
                logger.error(f"Failed to analyze page {page['id']}: {e}")
                results.append({"page_id": page['id'], "error": str(e)})

        success_count = len([r for r in results if 'analysis' in r])
        logger.info(f"Landing page analysis complete: {success_count}/{len(pages)} analyzed")
        return results

    def _update_landing_page_analysis(
        self,
        page_id: UUID,
        analysis: Dict
    ) -> None:
        """Update landing page with analysis results."""
        try:
            update = {
                "analysis_raw": analysis,
                "copy_patterns": analysis.get("copy_patterns", {}),
                "persona_signals": analysis.get("persona_signals", {}),
                "scrape_status": "analyzed",
                "analyzed_at": datetime.utcnow().isoformat(),
                "model_used": "claude-sonnet-4-20250514"
            }

            self.supabase.table("brand_landing_pages").update(update).eq(
                "id", str(page_id)
            ).execute()

            logger.info(f"Updated analysis for page: {page_id}")

        except Exception as e:
            logger.error(f"Failed to update landing page analysis: {e}")

    def get_landing_pages_for_brand(self, brand_id: UUID) -> List[Dict]:
        """Get all landing pages for a brand."""
        try:
            result = self.supabase.table("brand_landing_pages").select("*").eq(
                "brand_id", str(brand_id)
            ).order("created_at", desc=True).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get landing pages: {e}")
            return []

    def get_landing_page_stats(self, brand_id: UUID, product_id: Optional[UUID] = None) -> Dict[str, int]:
        """Get landing page statistics for a brand, optionally filtered by product.

        Returns:
            Dict with counts:
            - available: Total URL patterns in product_urls for this brand/product
            - total: Landing pages in database (scraped or attempted)
            - scraped: Successfully scraped pages
            - analyzed: Pages with AI analysis complete
            - failed: Failed scrape attempts
            - pending: Pages pending scrape
            - to_scrape: Available URLs not yet scraped (available - total)
            - to_analyze: Scraped pages not yet analyzed
        """
        try:
            # Get count of available URLs from product_urls
            if product_id:
                # Filter to specific product
                urls_result = self.supabase.table("product_urls").select(
                    "id", count="exact"
                ).eq("product_id", str(product_id)).execute()
                available = urls_result.count or 0
            else:
                # All products for brand
                products_result = self.supabase.table("products").select(
                    "id"
                ).eq("brand_id", str(brand_id)).execute()

                available = 0
                if products_result.data:
                    product_ids = [p['id'] for p in products_result.data]
                    urls_result = self.supabase.table("product_urls").select(
                        "id", count="exact"
                    ).in_("product_id", product_ids).execute()
                    available = urls_result.count or 0

            # Get existing landing page stats
            query = self.supabase.table("brand_landing_pages").select(
                "scrape_status"
            ).eq("brand_id", str(brand_id))

            if product_id:
                query = query.eq("product_id", str(product_id))

            result = query.execute()

            stats = {
                "available": available,
                "total": 0,
                "scraped": 0,      # Pages with 'scraped' status (not yet analyzed)
                "analyzed": 0,     # Pages with 'analyzed' status
                "failed": 0,
                "pending": 0
            }

            for page in result.data or []:
                stats["total"] += 1
                status = page.get("scrape_status", "pending")
                if status in stats:
                    stats[status] += 1

            # Calculate derived stats
            # successfully_scraped = pages that have content (scraped OR analyzed)
            successfully_scraped = stats["scraped"] + stats["analyzed"]
            # to_scrape = URLs that haven't been successfully scraped yet
            stats["to_scrape"] = max(0, available - successfully_scraped)
            # to_analyze = scraped pages that haven't been analyzed yet
            stats["to_analyze"] = stats["scraped"]  # Only 'scraped' status needs analysis
            # For display: total successfully scraped (includes analyzed)
            stats["successfully_scraped"] = successfully_scraped

            return stats

        except Exception as e:
            logger.error(f"Failed to get landing page stats: {e}")
            return {
                "available": 0, "total": 0, "scraped": 0, "analyzed": 0,
                "failed": 0, "pending": 0, "to_scrape": 0, "to_analyze": 0
            }


# Landing page analysis prompt
LANDING_PAGE_ANALYSIS_PROMPT = """Analyze this landing page for brand research and customer persona insights.

PAGE TITLE: {page_title}
URL: {url}

EXTRACTED DATA (from structured extraction):
{extracted_data}

PAGE CONTENT:
{content}

Analyze this landing page to extract:
1. Copy patterns and messaging strategies
2. Persona signals (who is this page targeting?)
3. Pain points and desires being addressed
4. Objection handling techniques
5. Social proof and trust signals

Return JSON:
{{
    "copy_patterns": {{
        "headline_style": "e.g., question, benefit-led, curiosity",
        "tone": "casual|professional|urgent|empathetic",
        "key_phrases": ["Notable phrases that could be reused"],
        "power_words": ["Emotionally charged words used"],
        "cta_patterns": ["Call-to-action styles used"]
    }},

    "persona_signals": {{
        "target_demographics": {{
            "age_range": "estimated age",
            "gender_focus": "male|female|neutral",
            "income_level": "budget|mid|premium|luxury"
        }},
        "psychographics": ["Lifestyle and personality traits targeted"],
        "identity_markers": ["How they see themselves"],
        "values": ["Core values appealed to"]
    }},

    "pain_points_addressed": {{
        "emotional": ["Emotional pains addressed"],
        "functional": ["Practical problems solved"],
        "social": ["Social concerns addressed"]
    }},

    "desires_appealed_to": {{
        "transformation": ["Before/after states promised"],
        "outcomes": ["Specific results promised"],
        "emotional_benefits": ["How they'll feel"]
    }},

    "objection_handling": [
        {{
            "objection": "The concern addressed",
            "response": "How the page handles it"
        }}
    ],

    "social_proof_analysis": {{
        "types_used": ["testimonial|statistic|logo|badge|etc"],
        "strength": "weak|moderate|strong",
        "notable_examples": ["Specific proof points"]
    }},

    "urgency_scarcity": {{
        "techniques_used": ["limited time|limited quantity|etc"],
        "effectiveness": "subtle|moderate|aggressive"
    }},

    "unique_angles": ["What makes this page's approach unique"],

    "persona_synthesis_notes": "2-3 sentences summarizing the ideal customer this page targets"
}}

Return ONLY valid JSON."""


# Persona synthesis prompt
PERSONA_SYNTHESIS_PROMPT = """You are an expert at building detailed 4D customer personas from advertising data.

Given the aggregated ad analysis data below, identify distinct customer segments and generate {max_personas} persona(s).

AGGREGATED DATA:
{aggregated_data}

INSTRUCTIONS:
1. Look for DISTINCT patterns in the data that suggest different customer segments
2. If the data is homogeneous, generate 1 persona. If you see clear distinctions (e.g., different age groups, different motivations), generate up to {max_personas} personas.
3. Each persona should be unique and represent a distinct segment
4. Use the ACTUAL language from the ads - don't make up generic descriptions
5. Assign a confidence score (0.0-1.0) based on how much supporting data exists

Return JSON with this structure:
{{
  "segment_analysis": "Brief explanation of distinct segments found (or why there's only one)",
  "personas": [
    {{
      "name": "Descriptive persona name (e.g., 'Worried Senior Dog Mom')",
      "snapshot": "2-3 sentence description capturing essence",
      "confidence_score": 0.85,

      "demographics": {{
        "age_range": "e.g., 35-55",
        "gender": "male/female/any",
        "location": "e.g., Suburban USA",
        "income_level": "e.g., Middle class",
        "occupation": "e.g., Professional",
        "family_status": "e.g., Pet parent"
      }},

      "transformation_map": {{
        "before": ["Current state/frustration 1", "Current state 2"],
        "after": ["Desired outcome 1", "Desired state 2"]
      }},

      "desires": {{
        "care_protection": [{{"text": "Specific desire text", "source": "ad_analysis"}}],
        "freedom_from_fear": [{{"text": "Specific desire", "source": "ad_analysis"}}],
        "social_approval": [{{"text": "Specific desire", "source": "ad_analysis"}}],
        "self_actualization": [{{"text": "Specific desire", "source": "ad_analysis"}}]
      }},

      "self_narratives": [
        "Because I am X, I do Y",
        "I'm the kind of person who..."
      ],
      "current_self_image": "How they see themselves",
      "desired_self_image": "Who they want to become",
      "identity_artifacts": ["Brands/products tied to identity"],

      "social_relations": {{
        "admire": ["People they look up to, role models"],
        "envy": ["People they secretly want to be like"],
        "want_to_impress": ["Who they want to impress/approval from"],
        "love_loyalty": ["People they feel protective of"],
        "dislike_animosity": ["People/groups they oppose"],
        "compared_to": ["People they measure themselves against"],
        "influence_decisions": ["Who influences their decisions"],
        "fear_judged_by": ["Who they fear judgment from"],
        "want_to_belong": ["Groups they aspire to join"],
        "distance_from": ["Groups they want to separate from"]
      }},

      "worldview": "Their general worldview",
      "core_values": ["Value 1", "Value 2"],
      "forces_of_good": ["What they see as good"],
      "forces_of_evil": ["What they see as bad/villains"],
      "allergies": {{
        "trigger": "reaction that turns them off"
      }},

      "pain_points": {{
        "emotional": ["Emotional pain 1", "Emotional pain 2"],
        "social": ["Social pain"],
        "functional": ["Functional pain 1"]
      }},

      "outcomes_jtbd": {{
        "emotional": ["How they want to feel"],
        "social": ["How they want to be seen"],
        "functional": ["What they want to accomplish"]
      }},

      "failed_solutions": ["What they've tried before"],
      "buying_objections": {{
        "emotional": ["Fear of wasting money"],
        "social": ["Fear of looking foolish"],
        "functional": ["Will it work?"]
      }},
      "familiar_promises": ["Claims they've heard before"],

      "pain_symptoms": ["Observable signs of pain - what you'd notice about them"],
      "activation_events": ["What triggers purchase NOW - specific moments"],
      "purchasing_habits": "How they typically buy (research-heavy, impulse, social proof seeker)",
      "decision_process": "Steps they go through to make a decision",
      "current_workarounds": ["What they do instead of buying"],

      "emotional_risks": ["What they're afraid of feeling if they buy"],
      "barriers_to_behavior": ["What stops them from acting on purchase intent"]
    }}
  ]
}}

Return ONLY valid JSON, no other text."""
