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

import google.generativeai as genai
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
        gemini_model: str = "models/gemini-1.5-flash-latest"
    ):
        """
        Initialize video analyzer.

        Args:
            supabase_client: Initialized Supabase client
            gemini_api_key: Gemini API key (defaults to env var)
            gemini_model: Gemini model to use
        """
        self.supabase = supabase_client

        # Configure Gemini
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment or passed to constructor")

        genai.configure(api_key=api_key)
        self.model_name = gemini_model
        self.model = genai.GenerativeModel(gemini_model)

        self.storage_bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "videos")

        logger.info(f"VideoAnalyzer initialized with model: {gemini_model}")

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

        # Upload video to Gemini
        video_file = genai.upload_file(path=str(video_path))
        logger.info(f"Uploaded file to Gemini: {video_file.uri}")

        # Wait for file to be processed
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError(f"Video processing failed: {video_file.state}")

        # Create analysis prompt
        prompt = self._create_analysis_prompt(post_data, product_context)

        # Generate analysis
        response = self.model.generate_content(
            [video_file, prompt],
            request_options={"timeout": 600}
        )

        # Parse the response
        analysis = self._parse_analysis_response(response.text)

        # Clean up uploaded file
        genai.delete_file(video_file.name)
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

        # Base analysis prompt
        base_prompt = f"""Analyze this viral {platform_name} video and provide a comprehensive breakdown.

**Video Context:**
- Username: @{username}
- Caption: {caption}
- Views: {views:,}

**Your Task:**
Provide a detailed JSON analysis with the following structure:

{{
  "hook_analysis": {{
    "transcript": "What is said/shown in the first 3-5 seconds",
    "visual_description": "Detailed description of opening visuals",
    "hook_type": "question|shock|curiosity|problem|story|trend",
    "timestamp_end": 5.0,
    "effectiveness_score": 8.5
  }},

  "full_transcript": {{
    "segments": [
      {{"timestamp": 0.0, "text": "spoken or on-screen text", "speaker": "narrator|text_overlay"}}
    ]
  }},

  "text_overlays": {{
    "overlays": [
      {{"timestamp": 0.0, "text": "overlay text", "style": "bold|caption|animated"}}
    ]
  }},

  "visual_storyboard": {{
    "scenes": [
      {{"timestamp": 0.0, "description": "what's happening visually", "duration": 3.0}}
    ]
  }},

  "key_moments": {{
    "moments": [
      {{"timestamp": 5.0, "type": "reveal|transition|climax|cta", "description": "what makes this moment significant"}}
    ]
  }},

  "viral_factors": {{
    "hook_strength": 9.0,
    "emotional_impact": 8.5,
    "relatability": 9.5,
    "novelty": 7.0,
    "production_quality": 8.0,
    "pacing": 9.0,
    "overall_score": 8.5
  }},

  "viral_explanation": "2-3 sentences explaining WHY this video went viral. What specific elements drove engagement?",

  "improvement_suggestions": "3-5 specific, actionable suggestions for similar content creators to replicate this video's success"
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
            "analysis_model": self.model_name,
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
