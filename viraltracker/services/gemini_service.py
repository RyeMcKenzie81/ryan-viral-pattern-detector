"""
GeminiService - AI-powered hook analysis using Google Gemini.

Handles all Gemini API interactions with intelligent rate limiting and retries.
"""

import logging
import asyncio
import time
import json
from typing import Optional

import google.generativeai as genai

from ..core.config import Config
from .models import HookAnalysis

logger = logging.getLogger(__name__)


# Hook types from Hook Intelligence framework
HOOK_TYPES = [
    "relatable_slice", "shock_violation", "listicle_howto", "hot_take",
    "question_curiosity", "story_narrative", "data_statistic",
    "personal_confession", "before_after", "mistake_lesson",
    "validation_permission", "call_out", "trend_react", "authority_credibility"
]

EMOTIONAL_TRIGGERS = [
    "humor", "validation", "curiosity", "surprise", "anger",
    "fear", "joy", "sadness", "nostalgia", "pride"
]

CONTENT_PATTERNS = [
    "question", "statement", "listicle", "story",
    "comparison", "hot_take", "observation", "instruction"
]


class GeminiService:
    """
    Service for Gemini AI API calls with intelligent rate limiting.

    Features:
    - Automatic rate limiting (configurable req/min)
    - Exponential backoff on rate limit errors
    - JSON response parsing with validation
    - Structured hook analysis
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash-exp"):
        """
        Initialize Gemini service.

        Args:
            api_key: Gemini API key (if None, uses Config.GEMINI_API_KEY)
            model: Gemini model to use (default: gemini-2.0-flash-exp for speed/cost)

        Raises:
            ValueError: If API key not found
        """
        self.api_key = api_key or Config.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.model_name = model

        # Configure Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model)

        # Rate limiting
        self._last_call_time = 0.0
        self._requests_per_minute = 9  # Default: 9 req/min for safety (under 10 req/min free tier)
        self._min_delay = 60.0 / self._requests_per_minute

        logger.info(f"GeminiService initialized with model: {model}, rate limit: {self._requests_per_minute} req/min")

    def set_rate_limit(self, requests_per_minute: int) -> None:
        """
        Set rate limit for API calls.

        Args:
            requests_per_minute: Maximum requests per minute (e.g., 9 for free tier)
        """
        self._requests_per_minute = requests_per_minute
        self._min_delay = 60.0 / requests_per_minute
        logger.info(f"Rate limit set to {requests_per_minute} req/min (delay: {self._min_delay:.1f}s)")

    async def analyze_hook(
        self,
        tweet_text: str,
        tweet_id: Optional[str] = None,
        max_retries: int = 3
    ) -> HookAnalysis:
        """
        Analyze a tweet's hook using Gemini AI.

        Args:
            tweet_text: Tweet content to analyze
            tweet_id: Optional tweet ID for reference
            max_retries: Maximum retries on rate limit errors

        Returns:
            HookAnalysis with AI classifications and explanations

        Raises:
            Exception: If all retries fail or non-rate-limit error occurs
        """
        # Wait for rate limit
        await self._rate_limit()

        # Build prompt
        prompt = self._build_hook_prompt(tweet_text)

        # Call API with retries
        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                # Call Gemini
                logger.debug(f"Analyzing tweet: {tweet_text[:50]}...")
                response = self.model.generate_content(prompt)

                # Parse response
                analysis = self._parse_response(tweet_text, response.text, tweet_id)
                return analysis

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                    retry_count += 1
                    if retry_count <= max_retries:
                        # Exponential backoff: 15s, 30s, 60s
                        retry_delay = 15 * (2 ** (retry_count - 1))
                        logger.warning(f"Rate limit hit. Retry {retry_count}/{max_retries} after {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Max retries exceeded for tweet: {tweet_text[:50]}...")
                        raise Exception(f"Rate limit exceeded after {max_retries} retries: {e}")
                else:
                    # Non-rate-limit error - don't retry
                    logger.error(f"Error analyzing tweet: {e}")
                    raise

        # Should never reach here, but just in case
        raise last_error or Exception("Unknown error during hook analysis")

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls"""
        now = time.time()
        elapsed = now - self._last_call_time

        if elapsed < self._min_delay:
            wait_time = self._min_delay - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

        self._last_call_time = time.time()

    def _build_hook_prompt(self, tweet_text: str) -> str:
        """Build hook analysis prompt for Gemini"""
        hook_types_list = "\n".join([f"- {ht}" for ht in HOOK_TYPES])
        emotional_triggers_list = "\n".join([f"- {et}" for et in EMOTIONAL_TRIGGERS])
        content_patterns_list = "\n".join([f"- {cp}" for cp in CONTENT_PATTERNS])

        prompt = f"""You are an expert at analyzing viral social media content hooks.

Analyze this tweet and classify it according to three dimensions:

TWEET:
{tweet_text}

CLASSIFICATION DIMENSIONS:

1. HOOK TYPE (choose ONE that best fits):
{hook_types_list}

2. EMOTIONAL TRIGGER (choose ONE primary emotion):
{emotional_triggers_list}

3. CONTENT PATTERN (choose ONE structure):
{content_patterns_list}

OUTPUT FORMAT (JSON):
{{
  "hook_type": "<one of the hook types>",
  "hook_type_confidence": <0.0 to 1.0>,
  "emotional_trigger": "<one of the emotional triggers>",
  "emotional_trigger_confidence": <0.0 to 1.0>,
  "content_pattern": "<one of the content patterns>",
  "content_pattern_confidence": <0.0 to 1.0>,
  "hook_explanation": "<2-3 sentences explaining why this hook works>",
  "adaptation_notes": "<2-3 sentences on how to adapt this hook to long-form content>"
}}

IMPORTANT:
- Return ONLY valid JSON, no additional text
- Use exact classification names from the lists above
- Be specific in explanations
- Focus on what makes this tweet engaging"""

        return prompt

    def _parse_response(
        self,
        tweet_text: str,
        response_text: str,
        tweet_id: Optional[str] = None
    ) -> HookAnalysis:
        """
        Parse Gemini response into HookAnalysis model.

        Args:
            tweet_text: Original tweet text
            response_text: Gemini response text
            tweet_id: Optional tweet ID

        Returns:
            HookAnalysis model

        Raises:
            json.JSONDecodeError: If response is not valid JSON
        """
        try:
            # Extract JSON from response (might have markdown code blocks)
            json_text = response_text.strip()
            if json_text.startswith("```json"):
                json_text = json_text[7:]
            if json_text.startswith("```"):
                json_text = json_text[3:]
            if json_text.endswith("```"):
                json_text = json_text[:-3]
            json_text = json_text.strip()

            # Parse JSON
            data = json.loads(json_text)

            # Extract metadata from tweet
            has_emoji = any(ord(char) > 127 for char in tweet_text)
            has_hashtags = '#' in tweet_text
            has_question_mark = '?' in tweet_text
            word_count = len(tweet_text.split())

            return HookAnalysis(
                tweet_id=tweet_id or "",
                tweet_text=tweet_text,
                hook_type=data.get("hook_type", "unknown"),
                hook_type_confidence=float(data.get("hook_type_confidence", 0.5)),
                emotional_trigger=data.get("emotional_trigger", "unknown"),
                emotional_trigger_confidence=float(data.get("emotional_trigger_confidence", 0.5)),
                content_pattern=data.get("content_pattern", "statement"),
                content_pattern_confidence=float(data.get("content_pattern_confidence", 0.5)),
                hook_explanation=data.get("hook_explanation", ""),
                adaptation_notes=data.get("adaptation_notes", ""),
                has_emoji=has_emoji,
                has_hashtags=has_hashtags,
                has_question_mark=has_question_mark,
                word_count=word_count
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text}")
            raise
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            raise
