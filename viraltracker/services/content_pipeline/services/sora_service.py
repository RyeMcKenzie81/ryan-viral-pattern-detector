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
        if not self.client:
            raise ValueError("OpenAI API key not configured")
            
        logger.info(f"Generating video with {model} ({duration_seconds}s): {prompt[:50]}...")
        
        try:
            # Note: This uses the standard OpenAI video generation structure
            # Adjust if Sora 2 specific SDK methods differ significantly
            response = await self.client.video.generations.create(
                model=model,
                prompt=prompt,
                quality="standard", # or "hd" depending on needs/cost
                response_format="url",
                size=f"{resolution}", # This might need specific format like "1920x1080"
                # Duration parameter handling depends on specific API version
                # Some versions might imply duration or take it as a param
                # We'll need to verify if 'duration' is a top-level param
            )
            
            # OpenAI typically returns a list of results
            video_url = response.data[0].url
            
            return {
                "url": video_url,
                "model": model,
                "duration": duration_seconds,
                "cost": self.estimate_cost(duration_seconds, model),
                "prompt": prompt
            }
            
        except Exception as e:
            logger.error(f"Sora generation failed: {e}")
            raise
