"""
Sora Service - API wrapper for OpenAI's Sora video generation.
"""

import logging
from typing import Optional, Dict, Any
from openai import AsyncOpenAI

from viraltracker.core.config import Config

logger = logging.getLogger(__name__)


class SoraService:
    """
    Service for generating videos using OpenAI's Sora API.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize SoraService.
        
        Args:
            api_key: Optional API key (defaults to Config.OPENAI_API_KEY)
        """
        self.api_key = api_key or Config.OPENAI_API_KEY
        self.client = None
        
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            logger.warning("SoraService initialized without API key")

    def estimate_cost(self, duration_seconds: int, model: str) -> float:
        """
        Estimate the cost of video generation.
        
        Args:
            duration_seconds: Duration of the video in seconds
            model: Model identifier
            
        Returns:
            Estimated cost in USD
        """
        price_per_second = Config.SORA_MODELS.get(model)
        
        if price_per_second is None:
            logger.warning(f"Unknown model {model}, assuming default pricing")
            price_per_second = 0.50  # Conservative estimate
            
        return round(duration_seconds * price_per_second, 2)

    async def generate_video(
        self, 
        prompt: str, 
        model: str, 
        duration_seconds: int = 5,
        resolution: str = "1280x720",
        aspect_ratio: str = "16:9",
        reference_image_data: Optional[bytes] = None,
        reference_image_mime: str = "image/jpeg"
    ) -> Dict[str, Any]:
        """
        Generate a video from a text prompt using Sora 2 API (Async Polling).
        
        Args:
            prompt: Text description of the video
            model: Sora model to use
            duration_seconds: Length in seconds
            resolution: Video resolution (e.g. "1280x720", "1920x1080")
            aspect_ratio: Aspect ratio (default 16:9)
            reference_image_data: Optional bytes of a reference image
            reference_image_mime: Mime type of the reference image
            
        Returns:
            Dictionary containing the video URL and other metadata
        """
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
            
        import httpx
        import asyncio
        
        # 1. Start Generation Job
        base_url = "https://api.openai.com/v1/videos"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
            # Content-Type header will be set automatically by httpx for JSON or Multipart
        }
        
        # Note: Sora 2 accepts strict 'size' values like "1280x720"
        size = resolution
        if resolution == "1080p": # Legacy fallback
             size = "1920x1080" # This will likely fail but keeping logic to avoid breaking legacy calls

        logger.info(f"Starting Sora job: {model}, {duration_seconds}s, {size} (Image: {bool(reference_image_data)})")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            if reference_image_data:
                # Use Multipart/Form-Data
                # Note: valid params must be passed stringified in 'data'
                data_payload = {
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "seconds": str(duration_seconds)
                }
                files_payload = {
                    "input_reference": ("reference_image", reference_image_data, reference_image_mime)
                }
                response = await client.post(base_url, headers=headers, data=data_payload, files=files_payload)
            else:
                # Use JSON
                headers["Content-Type"] = "application/json"
                json_payload = {
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "seconds": str(duration_seconds)
                }
                response = await client.post(base_url, headers=headers, json=json_payload)

            if response.status_code != 200:
                logger.error(f"Sora Start Failed ({response.status_code}): {response.text}")
                raise Exception(f"Failed to start video generation: {response.text}")
            
            data = response.json()
            job_id = data.get("id")
            if not job_id:
                raise Exception(f"No job ID in response: {data}")
                
            logger.info(f"Sora job started: {job_id}")
            
            # 2. Poll for Completion
            attempts = 0
            max_attempts = 120  # 2 minutes max (assuming 1s poll)
            
            while attempts < max_attempts:
                # Poll status
                poll_resp = await client.get(f"{base_url}/{job_id}", headers=headers)
                
                if poll_resp.status_code != 200:
                    logger.warning(f"Polling failed ({poll_resp.status_code}), retrying...")
                    await asyncio.sleep(2)
                    attempts += 1
                    continue
                
                job_data = poll_resp.json()
                status = job_data.get("status")
                
                if status == "completed":
                    logger.info(f"Job {job_id} completed. Downloading content...")
                    
                    # 3. Download Content (Docs: GET /videos/{id}/content)
                    content_url = f"{base_url}/{job_id}/content"
                    # Note: We need to increase timeout for download
                    content_resp = await client.get(content_url, headers=headers, follow_redirects=True, timeout=60.0)
                    
                    if content_resp.status_code != 200:
                         raise Exception(f"Failed to download video content: {content_resp.status_code}")
                         
                    video_bytes = content_resp.content
                    
                    return {
                        "video_data": video_bytes, # Return bytes for UI
                        "model": model,
                        "duration": duration_seconds,
                        "cost": self.estimate_cost(duration_seconds, model),
                        "prompt": prompt,
                        "raw_response": job_data
                    }
                    
                elif status == "failed":
                    error = job_data.get("error", "Unknown error")
                    raise Exception(f"Video generation failed: {error}")
                
                elif status in ["processing", "pending", "queued", "in_progress"]:
                    await asyncio.sleep(2) # Wait 2s between polls
                    attempts += 1
                else:
                    logger.warning(f"Unknown status '{status}', waiting...")
                    await asyncio.sleep(2)
                    attempts += 1
            
            raise TimeoutError("Video generation timed out after polling.")
