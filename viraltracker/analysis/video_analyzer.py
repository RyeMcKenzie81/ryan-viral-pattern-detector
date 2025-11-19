"""
Video Analyzer using Gemini AI

Analyzes viral videos to extract hooks, transcripts, and viral factors.
Product-aware implementation for multi-brand schema.
"""

import os
import logging
import time
import json
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
import tempfile

from google import genai
from google.genai import types
from supabase import Client
from tqdm import tqdm

from ..core.config import Config


logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of video analysis."""
    post_id: str
    status: str
    hook_transcript: Optional[str] = None
    hook_type: Optional[str] = None
    viral_explanation: Optional[str] = None
    processing_time: Optional[float] = None
    error_message: Optional[str] = None


class VideoAnalyzer:
    """
    Analyzes videos using Gemini AI to extract viral patterns.

    Product-aware implementation that generates brand/product-specific adaptations.
    """

    def __init__(
        self,
        supabase_client: Client,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None
    ):
        """
        Initialize video analyzer.

        Args:
            supabase_client: Initialized Supabase client
            gemini_api_key: Gemini API key (defaults to env var)
            gemini_model: Gemini model to use (defaults to Config.GEMINI_VIDEO_MODEL)
        """
        self.supabase = supabase_client

        # Configure Gemini
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment or passed to constructor")

        self.client = genai.Client(api_key=api_key)
        # Use explicit model for video analysis - Gemini 2.5 Pro
        self.model_name = gemini_model or Config.GEMINI_VIDEO_MODEL
        self.analysis_version = "vid-1.2.0"  # Hook Intelligence upgrade

        self.storage_bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "videos")

        logger.info(f"VideoAnalyzer initialized with model: {self.model_name} (version: {self.analysis_version})")

    def get_unanalyzed_videos(
        self,
        project_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get videos that have been processed but not yet analyzed.

        Args:
            project_id: Filter by project ID (optional)
            limit: Maximum number of videos to return

        Returns:
            List of video records ready for analysis
        """
        logger.info("Fetching unanalyzed videos")

        # Get all completed videos with post details
        query = (self.supabase.table("video_processing_log")
                .select("post_id, storage_path, file_size_mb, video_duration_sec, posts(id, post_url, caption, views, account_id, accounts(platform_username, platform_id, platforms(slug)))")
                .eq("status", "completed"))

        result = query.execute()

        # Get all analyzed videos
        analyzed_result = self.supabase.table("video_analysis").select("post_id").execute()
        analyzed_post_ids = {row["post_id"] for row in analyzed_result.data}

        # Filter to get only unanalyzed
        unanalyzed = [v for v in result.data if v["post_id"] not in analyzed_post_ids]

        # Filter by project if specified
        if project_id:
            # Get post IDs for this project
            project_posts = self.supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
            project_post_ids = {row["post_id"] for row in project_posts.data}

            unanalyzed = [v for v in unanalyzed if v["post_id"] in project_post_ids]

        # Apply limit if specified
        if limit:
            unanalyzed = unanalyzed[:limit]

        logger.info(f"Found {len(unanalyzed)} unanalyzed videos")
        return unanalyzed

    def get_product_context(self, product_id: str) -> Dict:
        """
        Get product context for adaptation generation.

        Args:
            product_id: Product UUID

        Returns:
            Product context dict with prompt template
        """
        result = self.supabase.table("products").select("*").eq("id", product_id).execute()

        if not result.data:
            raise ValueError(f"Product not found: {product_id}")

        product = result.data[0]

        logger.info(f"Loaded product context: {product['name']}")
        return product

    def download_video_from_storage(self, storage_path: str) -> Path:
        """
        Download video from Supabase Storage to temporary file.

        Args:
            storage_path: Path in Supabase Storage

        Returns:
            Path to downloaded temporary file
        """
        logger.info(f"Downloading video from storage: {storage_path}")

        # Get the video data from Supabase Storage
        data = self.supabase.storage.from_(self.storage_bucket).download(storage_path)

        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        temp_file.write(data)
        temp_file.close()

        logger.info(f"Video downloaded to: {temp_file.name}")
        return Path(temp_file.name)

    def analyze_video(
        self,
        video_path: Path,
        post_data: Dict,
        product_context: Optional[Dict] = None
    ) -> Dict:
        """
        Analyze a video using Gemini AI.

        Args:
            video_path: Path to video file
            post_data: Metadata about the post
            product_context: Product context for adaptation (optional)

        Returns:
            Analysis results as dict
        """
        logger.info(f"Analyzing video: {video_path}")

        # Create analysis prompt
        prompt = self._create_analysis_prompt(post_data, product_context)

        # Upload video file to Gemini
        video_file = self.client.files.upload(file=str(video_path))
        logger.info(f"Uploaded file to Gemini: {video_file.uri}")

        # Wait for file to be processed
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = self.client.files.get(name=video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError(f"Video processing failed: {video_file.state}")

        # Generate analysis using new SDK syntax
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[video_file, prompt]
        )

        # Parse the response
        analysis = self._parse_analysis_response(response.text)

        # Clean up uploaded file
        self.client.files.delete(name=video_file.name)
        logger.info("Deleted temporary Gemini file")

        return analysis

    def _create_analysis_prompt(
        self,
        post_data: Dict,
        product_context: Optional[Dict] = None
    ) -> str:
        """
        Create a comprehensive analysis prompt for Gemini.

        Args:
            post_data: Post metadata
            product_context: Product context for adaptation

        Returns:
            Formatted prompt string
        """
        # Extract post details
        posts = post_data.get('posts', {})
        caption = posts.get('caption', 'No caption')
        views = posts.get('views', 0)

        accounts = posts.get('accounts', {})
        username = accounts.get('platform_username', 'unknown')

        # Get platform name
        platforms = accounts.get('platforms', {})
        platform_slug = platforms.get('slug', 'instagram')
        platform_name = {
            'instagram': 'Instagram',
            'tiktok': 'TikTok',
            'youtube_shorts': 'YouTube Shorts'
        }.get(platform_slug, 'Instagram')

        # New v1.1.0 analysis prompt with continuous values and nulls
        base_prompt = f"""SYSTEM: You are a video analysis model. Output strict JSON only. No explanations.

USER: Analyze the attached vertical {platform_name}-style video. Return strict JSON matching this TypeScript type (include every key; use null if unknown; use floating-point values with up to 3 decimals; do not round/bucket):

**Video Context:**
- Username: @{username}
- Caption: {caption}
- Views: {views:,}

{{
  "hook": {{
    "time_to_value_sec": number | null,
    "first_frame_face_present_pct": number | null,
    "first_2s_motion_intensity": number | null
  }},
  "story": {{
    "beats_count": number | null,
    "avg_beat_length_sec": number | null,
    "storyboard": Array<{{ t_start:number, t_end:number, label?:string, description?:string }}> | null
  }},
  "relatability": {{
    "authenticity_signals": number | null,
    "jargon_density_pct": number | null
  }},
  "visuals": {{
    "avg_scene_duration_sec": number | null,
    "edit_rate_per_10s": number | null,
    "brightness_mean": number | null,
    "contrast_mean": number | null,
    "camera_motion_pct": number | null,
    "text_overlay_occlusion_pct": number | null
  }},
  "audio": {{
    "music_to_voice_db_diff": number | null,
    "beat_sync_score": number | null,
    "speech_intelligibility_score": number | null,
    "trending_sound_used": boolean | null,
    "original_sound_created": boolean | null
  }},
  "watchtime": {{
    "length_sec": number | null
  }},
  "engagement": {{
    "comment_prompt_present": boolean | null
  }},
  "shareability": {{
    "emotion_intensity": number | null,
    "simplicity_score": number | null
  }},
  "algo": {{
    "caption_length_chars": number | null,
    "hashtag_count": number | null,
    "hashtag_niche_mix_ok": boolean | null
  }},
  "penalties": {{
    "slow_intro_flag": boolean | null,
    "poor_lighting_flag": boolean | null,
    "audio_mix_poor_flag": boolean | null,
    "audience_mismatch_flag": boolean | null,
    "trend_stale_flag": boolean | null
  }}
}}

Constraints:
- Return floating-point values with up to 3 decimals where applicable.
- time_to_value_sec: seconds until value proposition is clear (0.0-10.0 range)
- first_frame_face_present_pct: percentage of first frame showing human face (0-100)
- first_2s_motion_intensity: motion/action level in first 2 seconds (0.0-1.0)
- authenticity_signals: genuine/relatable feel score (0.0-1.0)
- jargon_density_pct: percentage of technical/niche terms (0-100)
- brightness_mean: average brightness level (0.0-1.0)
- contrast_mean: average contrast level (0.0-1.0)
- camera_motion_pct: percentage of video with camera movement (0-100)
- text_overlay_occlusion_pct: percentage of frame covered by text (0-100)
- music_to_voice_db_diff: dB difference between music and voice (negative = music quieter; aim ~ -10.0)
- beat_sync_score: how well edits align with audio beats (0.0-1.0)
- speech_intelligibility_score: clarity of speech (0.0-1.0)
- emotion_intensity: emotional impact strength (0.0-1.0)
- simplicity_score: ease of understanding (0.0-1.0, higher = simpler)
- If unknown, return null (do not omit the key).
- No qualitative text outside the JSON.

Hook Intelligence v1.2.0 - Add these additional hook analysis fields:

"hook_type_probs": {{
  "result_first": number | null, "shock_violation": number | null, "reveal_transform": number | null,
  "challenge_stakes": number | null, "authority_flex": number | null, "confession_secret": number | null,
  "contradiction_mythbust": number | null, "open_question": number | null, "direct_callout": number | null,
  "demo_novelty": number | null, "relatable_slice": number | null, "humor_gag": number | null,
  "social_proof": number | null, "tension_wait": number | null
}},
"hook_modality_attribution": {{ "audio": number | null, "visual": number | null, "overlay": number | null }},
"hook_visual_catalysts": {{
  "face_closeup": number | null, "hands_object": number | null, "large_motion_burst": number | null,
  "color_pop": number | null, "visual_evidence_present": boolean | null,
  "first_frame_shot_type": "face_closeup" | "hands_object" | "full_body_motion" | "product_macro" | "screen_recording" | "establishing" | null,
  "skin_exposure_suggestive": boolean | null
}},
"hook_audio_catalysts": {{
  "spoken_question_present": boolean | null, "spoken_callout_niche": boolean | null,
  "spoken_numbers_present": boolean | null, "prosody_energy": number | null, "beat_drop_sync": number | null
}},
"hook_overlay_catalysts": {{
  "overlay_words_in_2s": number | null, "overlay_chars_per_sec_2s": number | null,
  "overlay_contrast_score": number | null, "overlay_safe_area_pct": number | null,
  "overlay_alignment_delay_ms": number | null, "overlay_dup_spoken_pct": number | null
}},
"hook_risk_flags": {{
  "suggestive_visual_risk": boolean | null, "violence_risk": boolean | null,
  "minors_present_risk": boolean | null, "medical_sensitive_risk": boolean | null, "brand_logo_risk": boolean | null
}},
"hook_span": {{ "t_start": number | null, "t_end": number | null }},
"payoff_time_sec": number | null,
"hook_windows": {{
  "w1_0_1s": {{
    "face_pct": number | null, "cuts": number | null, "motion_intensity": number | null,
    "words_per_sec": number | null, "overlay_chars_per_sec": number | null,
    "modality_attribution": {{ "audio": number | null, "visual": number | null, "overlay": number | null }}
  }},
  "w2_0_2s": {{
    "face_pct": number | null, "cuts": number | null, "motion_intensity": number | null,
    "words_per_sec": number | null, "overlay_chars_per_sec": number | null,
    "modality_attribution": {{ "audio": number | null, "visual": number | null, "overlay": number | null }}
  }},
  "w3_0_3s": {{
    "face_pct": number | null, "cuts": number | null, "motion_intensity": number | null,
    "words_per_sec": number | null, "overlay_chars_per_sec": number | null,
    "modality_attribution": {{ "audio": number | null, "visual": number | null, "overlay": number | null }}
  }},
  "w4_0_5s_or_hook_end": {{
    "face_pct": number | null, "cuts": number | null, "motion_intensity": number | null,
    "words_per_sec": number | null, "overlay_chars_per_sec": number | null,
    "modality_attribution": {{ "audio": number | null, "visual": number | null, "overlay": number | null }}
  }}
}},
"hook_modifiers": {{
  "stakes_clarity": number | null, "curiosity_gap": number | null, "specificity": number | null
}}

Hook Type Probabilities (0.0-1.0): Multi-label probabilities for hook strategies used (can have multiple).
Hook Modality Attribution (0.0-1.0, should sum to ~1.0): Which channel drives attention - audio, visual, or overlay text.
Hook Visual Catalysts: Visual elements in the hook that capture attention.
Hook Audio Catalysts: Audio elements that drive hook effectiveness.
Hook Overlay Catalysts: Text overlay metrics in first 2 seconds.
Hook Risk Flags: Content moderation risks detected.
Hook Span: Start and end timestamps of the hook in seconds.
Payoff Time: When the promised value/answer is delivered (seconds).
Hook Windows: Metrics measured in 4 time windows (0-1s, 0-2s, 0-3s, 0-5s or hook end).
Hook Modifiers: Additional hook quality factors (0.0-1.0).

For backwards compatibility, also include these legacy fields:

{{
  "hook_analysis": {{
    "transcript": string | null,
    "visual_description": string | null,
    "hook_type": string | null,
    "timestamp_end": number | null,
    "effectiveness_score": number | null
  }},
  "viral_explanation": string | null
}}"""

        # Add product adaptation section if product context provided
        if product_context:
            product_name = product_context.get('name', 'Unknown Product')
            description = product_context.get('description', '')
            target_audience = product_context.get('target_audience', '')

            # Use custom context prompt if available
            if product_context.get('context_prompt'):
                product_section = f"""

**Product Adaptation Context:**
{product_context['context_prompt']}

Add this additional section to your JSON response:

{{
  "product_adaptation": {{
    "how_this_video_style_applies": "2-3 sentences on how this viral video's style/approach could work for {product_name}",
    "adaptation_ideas": [
      "Specific idea 1 for adapting this viral pattern to {product_name}",
      "Specific idea 2...",
      "Specific idea 3..."
    ],
    "script_outline": "Rough script outline adapting this video's structure for {product_name}",
    "key_differences": "What would need to change from the original to make it work for {product_name}",
    "target_audience_fit": "How well this viral style matches {product_name}'s target audience (1-10 score with explanation)"
  }}
}}"""
            else:
                # Fallback to basic product info
                product_section = f"""

**Product Adaptation:**
Analyze how this viral video's approach could be adapted for:
- Product: {product_name}
- Description: {description}
- Target Audience: {target_audience}

Add this section to your JSON response:

{{
  "product_adaptation": {{
    "how_this_video_style_applies": "2-3 sentences on how this viral pattern could work for this product",
    "adaptation_ideas": [
      "Specific adaptation idea 1",
      "Specific adaptation idea 2",
      "Specific adaptation idea 3"
    ],
    "script_outline": "Rough script outline adapting this video's structure",
    "key_differences": "What would need to change from the original",
    "target_audience_fit": "How well this style matches the target audience (1-10 with explanation)"
  }}
}}"""

            base_prompt += product_section

        # Add guidelines
        base_prompt += """

**Guidelines:**
- Be extremely specific and detailed
- Include exact timestamps for all events
- Identify the emotional triggers used
- Note any trends, memes, or cultural references
- Analyze pacing and editing choices
- Identify the target audience
- Note any call-to-action elements

Provide ONLY the JSON response, no additional text."""

        return base_prompt

    def _parse_analysis_response(self, response_text: str) -> Dict:
        """
        Parse Gemini's JSON response.

        Args:
            response_text: Raw response from Gemini

        Returns:
            Parsed analysis dict
        """
        try:
            # Extract JSON from response (in case there's markdown formatting)
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            analysis = json.loads(response_text.strip())
            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")

            # Return a fallback structure
            return {
                "error": "Failed to parse response",
                "raw_response": response_text[:1000]
            }

    def save_analysis(
        self,
        post_id: str,
        analysis: Dict,
        processing_time: float,
        product_id: Optional[str] = None,
        tokens_used: int = 0
    ) -> None:
        """
        Save analysis results to database.

        Args:
            post_id: UUID of the post
            analysis: Analysis results dict
            processing_time: Time taken for analysis
            product_id: Product ID if adaptation was generated
            tokens_used: Number of tokens consumed
        """
        logger.info(f"Saving analysis for post {post_id}")

        # Extract components from analysis
        hook = analysis.get("hook_analysis", {})
        transcript = analysis.get("full_transcript", {})
        overlays = analysis.get("text_overlays", {})
        storyboard = analysis.get("visual_storyboard", {})
        moments = analysis.get("key_moments", {})
        factors = analysis.get("viral_factors", {})
        product_adaptation = analysis.get("product_adaptation", {})

        # Extract v1.1.0 structured metrics if available
        platform_metrics = {}
        for key in ['hook', 'story', 'relatability', 'visuals', 'audio', 'watchtime',
                    'engagement', 'shareability', 'algo', 'penalties']:
            if key in analysis:
                platform_metrics[key] = analysis[key]

        # Extract v1.2.0 hook intelligence features
        hook_features = {}
        for key in ['hook_type_probs', 'hook_modality_attribution', 'hook_visual_catalysts',
                    'hook_audio_catalysts', 'hook_overlay_catalysts', 'hook_risk_flags',
                    'hook_span', 'payoff_time_sec', 'hook_windows', 'hook_modifiers']:
            if key in analysis:
                hook_features[key] = analysis[key]

        # Prepare record with product columns
        record = {
            "post_id": post_id,
            "product_id": product_id,
            "hook_transcript": hook.get("transcript"),
            "hook_visual_storyboard": json.dumps(hook) if hook else None,
            "hook_type": hook.get("hook_type"),
            "hook_timestamp": hook.get("timestamp_end"),
            "transcript": json.dumps(transcript) if transcript else None,
            "text_overlays": json.dumps(overlays) if overlays else None,
            "storyboard": json.dumps(storyboard) if storyboard else None,
            "key_moments": json.dumps(moments) if moments else None,
            "viral_factors": json.dumps(factors) if factors else None,
            "viral_explanation": analysis.get("viral_explanation"),
            "improvement_suggestions": analysis.get("improvement_suggestions"),
            "product_adaptation": json.dumps(product_adaptation) if product_adaptation else None,
            "platform_specific_metrics": json.dumps(platform_metrics) if platform_metrics else None,
            "hook_features": hook_features if hook_features else None,  # Store as dict for JSONB column
            "analysis_model": self.model_name,
            "analysis_version": self.analysis_version,
            "analysis_tokens_used": tokens_used,
            "processing_time_sec": processing_time
        }

        # Log product adaptation if generated
        if product_adaptation:
            logger.info(f"Product adaptation saved for {product_id}: {len(json.dumps(product_adaptation))} chars")

        # Insert into video_analysis table
        result = self.supabase.table("video_analysis").insert(record).execute()
        logger.info(f"Analysis saved successfully: {len(result.data)} record(s)")

    def process_video(
        self,
        video_record: Dict,
        product_id: Optional[str] = None
    ) -> AnalysisResult:
        """
        Process a single video: download, analyze, save results.

        Args:
            video_record: Video record from database
            product_id: Product ID for adaptation generation (optional)

        Returns:
            AnalysisResult with status
        """
        post_id = video_record['post_id']
        storage_path = video_record['storage_path']

        start_time = time.time()
        temp_path = None

        try:
            logger.info(f"Processing video for post {post_id}")

            # Get product context if product_id provided
            product_context = None
            if product_id:
                product_context = self.get_product_context(product_id)

            # Download video from storage
            temp_path = self.download_video_from_storage(storage_path)

            # Analyze with Gemini
            analysis = self.analyze_video(temp_path, video_record, product_context)

            # Calculate processing time
            processing_time = time.time() - start_time

            # Save to database
            self.save_analysis(post_id, analysis, processing_time, product_id)

            return AnalysisResult(
                post_id=post_id,
                status="completed",
                hook_transcript=analysis.get("hook_analysis", {}).get("transcript"),
                hook_type=analysis.get("hook_analysis", {}).get("hook_type"),
                viral_explanation=analysis.get("viral_explanation"),
                processing_time=processing_time
            )

        except Exception as e:
            logger.error(f"Error processing video {post_id}: {e}")
            return AnalysisResult(
                post_id=post_id,
                status="failed",
                error_message=str(e),
                processing_time=time.time() - start_time
            )

        finally:
            # Clean up temporary file
            if temp_path and temp_path.exists():
                temp_path.unlink()
                logger.info(f"Deleted temporary file: {temp_path}")

    def process_batch(
        self,
        project_id: Optional[str] = None,
        product_id: Optional[str] = None,
        limit: Optional[int] = None,
        show_progress: bool = True
    ) -> Dict[str, int]:
        """
        Process a batch of unanalyzed videos.

        Args:
            project_id: Filter by project ID (optional)
            product_id: Product ID for adaptations (optional)
            limit: Maximum number of videos to process
            show_progress: Whether to show progress bar

        Returns:
            Summary dict with counts
        """
        videos = self.get_unanalyzed_videos(project_id=project_id, limit=limit)

        if not videos:
            logger.info("No videos to analyze")
            return {"total": 0, "completed": 0, "failed": 0}

        results = {"completed": 0, "failed": 0}

        # Process with progress bar
        iterator = tqdm(videos, desc="Analyzing videos") if show_progress else videos

        for video in iterator:
            result = self.process_video(video, product_id=product_id)

            if result.status == "completed":
                results["completed"] += 1
            else:
                results["failed"] += 1

            # Add small delay to avoid rate limits
            time.sleep(2)

        results["total"] = len(videos)

        logger.info(f"Batch complete: {results['completed']} succeeded, {results['failed']} failed")
        return results
