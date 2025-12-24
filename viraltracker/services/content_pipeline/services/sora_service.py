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
        resolution: str = "1080p",
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """
        Generate a video from a text prompt.
        
        Args:
            prompt: Text description of the video
            model: Sora model to use
            duration_seconds: Length in seconds (default 5, max typically 20)
            resolution: Video resolution (default 1080p)
            aspect_ratio: Aspect ratio (default 16:9)
            
        Returns:
            Dictionary containing the video URL and other metadata
        """
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
            
        logger.info(f"Generating video with {model} ({duration_seconds}s): {prompt[:50]}...")
        
        # Use direct HTTP request since client.video is not available in current SDK
        import httpx
        
        url = "https://api.openai.com/v1/video/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "prompt": prompt,
            "quality": "standard",
            "response_format": "url",
            "size": resolution,
            # Pass duration only if model supports it (Sora 2 implies it might)
            # For now passing it as top level, if API rejects, we might need to adjust
            # "duration": duration_seconds 
        }
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                response = await http_client.post(url, headers=headers, json=payload)
                
                # Check for error
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Sora API Error ({response.status_code}): {error_text}")
                    raise Exception(f"OpenAI API returned {response.status_code}: {error_text}")
                
                data = response.json()
                
                # OpenAI typically returns a list of results in 'data'
                # Example: {"created": ..., "data": [{"url": "..."}]}
                if "data" in data and len(data["data"]) > 0:
                     video_url = data["data"][0]["url"]
                else:
                    # Fallback for unexpected structure
                    logger.warning(f"Unexpected response structure: {data.keys()}")
                    # If 'url' is at root?
                    video_url = data.get("url")
                
                if not video_url:
                    raise Exception(f"No video URL found in response: {str(data)[:200]}")
            
            return {
                "url": video_url,
                "model": model,
                "duration": duration_seconds,
                "cost": self.estimate_cost(duration_seconds, model),
                "prompt": prompt,
                "raw_response": data
            }
            
        except Exception as e:
            logger.error(f"Sora generation failed: {e}")
            raise
