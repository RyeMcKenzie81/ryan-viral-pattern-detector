"""
GeminiService - AI-powered hook analysis using Google Gemini.

Handles all Gemini API interactions with intelligent rate limiting and retries.
"""

import logging
import asyncio
import time
import json
from typing import Optional

from google import genai
from google.genai import types

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
    - Usage tracking for billing (optional)
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        """
        Initialize Gemini service.

        Args:
            api_key: Gemini API key (if None, uses Config.GEMINI_API_KEY)
            model: Gemini model to use (default: gemini-2.5-flash for speed/cost)

        Raises:
            ValueError: If API key not found
        """
        self.api_key = api_key or Config.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.model_name = model

        # Configure Gemini client
        self.client = genai.Client(api_key=self.api_key)

        # Rate limiting
        self._last_call_time = 0.0
        self._requests_per_minute = 9  # Default: 9 req/min for safety (under 10 req/min free tier)
        self._min_delay = 60.0 / self._requests_per_minute

        # Usage tracking (optional)
        self._usage_tracker = None
        self._user_id = None
        self._organization_id = None

        logger.info(f"GeminiService initialized with model: {model}, rate limit: {self._requests_per_minute} req/min")

    def set_tracking_context(
        self,
        usage_tracker,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> None:
        """
        Set usage tracking context.

        Call this to enable usage tracking for all subsequent API calls.

        Args:
            usage_tracker: UsageTracker instance
            user_id: User ID for tracking
            organization_id: Organization ID for billing
        """
        self._usage_tracker = usage_tracker
        self._user_id = user_id
        self._organization_id = organization_id
        logger.debug(f"Usage tracking enabled for org: {organization_id}")

    def _track_usage(
        self,
        operation: str,
        model: str,
        response=None,
        units: float = None,
        unit_type: str = None,
        duration_ms: int = None,
        metadata: dict = None
    ) -> None:
        """
        Track API usage (fire-and-forget, never fails).

        Args:
            operation: Operation name (e.g., 'generate_image', 'analyze_image')
            model: Model used
            response: API response (for extracting token counts)
            units: Unit count for non-token APIs
            unit_type: Unit type (e.g., 'image_generation')
            duration_ms: Call duration in milliseconds
            metadata: Additional context
        """
        if not self._usage_tracker or not self._organization_id:
            return

        try:
            from .usage_tracker import UsageRecord

            # Extract token counts from response if available
            input_tokens = 0
            output_tokens = 0
            if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                input_tokens = getattr(um, 'prompt_token_count', 0) or 0
                output_tokens = getattr(um, 'candidates_token_count', 0) or 0

            record = UsageRecord(
                provider="google",
                model=model,
                tool_name="gemini_service",
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                units=units,
                unit_type=unit_type,
                duration_ms=duration_ms,
                request_metadata=metadata,
            )

            self._usage_tracker.track(
                user_id=self._user_id,
                organization_id=self._organization_id,
                record=record
            )

        except Exception as e:
            logger.warning(f"Usage tracking failed (non-fatal): {e}")

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
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[prompt]
                )

                # Track usage (fire-and-forget)
                self._track_usage(
                    operation="analyze_hook",
                    model=self.model_name,
                    response=response,
                )

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

    async def generate_content(
        self,
        hook_analyses: list,
        content_type: str = "thread",
        max_retries: int = 3
    ) -> str:
        """
        Generate long-form content from analyzed hooks using Claude Opus 4.5.

        Uses Claude Opus 4.5 for high-quality creative writing (threads/articles).

        Args:
            hook_analyses: List of HookAnalysis objects to use as inspiration
            content_type: Type of content to generate ('thread' or 'article')
            max_retries: Maximum retries on errors

        Returns:
            Generated content as string

        Raises:
            Exception: If generation fails after retries
        """
        from pydantic_ai import Agent
        from ..core.config import Config

        # Build prompt
        prompt = self._build_content_prompt(hook_analyses, content_type)

        # Use Claude Opus 4.5 for creative writing
        agent = Agent(
            model=Config.CREATIVE_MODEL,
            system_prompt="You are an expert content strategist and writer. Generate engaging, high-quality content."
        )

        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                logger.debug(f"Generating {content_type} content from {len(hook_analyses)} hooks using Claude Opus 4.5...")
                result = await agent.run(prompt)
                return result.data

            except Exception as e:
                error_str = str(e)
                last_error = e
                retry_count += 1

                if retry_count <= max_retries:
                    retry_delay = 15 * (2 ** (retry_count - 1))
                    logger.warning(f"Content generation error. Retry {retry_count}/{max_retries} after {retry_delay}s: {e}")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Max retries exceeded for content generation: {e}")
                    raise

        raise last_error or Exception("Unknown error during content generation")

    def _build_content_prompt(self, hook_analyses: list, content_type: str) -> str:
        """Build content generation prompt for thread/article generation."""
        # Extract key information from hook analyses
        hooks_summary = []
        for i, analysis in enumerate(hook_analyses[:5], 1):  # Limit to top 5
            hooks_summary.append(
                f"{i}. {analysis.hook_type} - \"{analysis.tweet_text[:100]}...\"\n"
                f"   Why it works: {analysis.hook_explanation}"
            )

        hooks_text = "\n\n".join(hooks_summary)

        if content_type == "thread":
            prompt = f"""You are an expert content strategist. Based on these viral tweet hooks, create a Twitter thread (8-12 tweets) that synthesizes the best elements.

VIRAL HOOKS TO DRAW FROM:
{hooks_text}

REQUIREMENTS:
- Start with a strong hook tweet that grabs attention
- Build a logical narrative flow across tweets
- Use the emotional triggers and patterns from the hooks above
- Keep each tweet concise (under 280 characters)
- Include clear takeaways and insights
- End with a call-to-action or thought-provoking question

OUTPUT FORMAT:
Tweet 1/12: [hook tweet]
Tweet 2/12: [content]
...
Tweet 12/12: [conclusion]

Generate the thread now:"""

        else:  # article
            prompt = f"""You are an expert content writer. Based on these viral tweet hooks, create a long-form article (800-1200 words) that explores the themes in depth.

VIRAL HOOKS TO DRAW FROM:
{hooks_text}

REQUIREMENTS:
- Compelling headline
- Strong opening hook
- Clear section structure
- Incorporate insights from the viral patterns
- Practical takeaways for readers
- Engaging, conversational tone

OUTPUT FORMAT:
# [Headline]

[Opening paragraph with hook]

## [Section 1]
[Content]

## [Section 2]
[Content]

...

## Conclusion
[Wrap-up and call-to-action]

Generate the article now:"""

        return prompt

    async def generate_image(
        self,
        prompt: str,
        reference_images: list = None,
        max_retries: int = 3,
        return_metadata: bool = False,
        temperature: float = 0.4,
        image_size: str = "2K"
    ) -> str | dict:
        """
        Generate an image using Gemini 3 Pro Image Preview API.

        Uses gemini-3-pro-image-preview model to generate images from text prompts
        and optional reference images (up to 14). Returns base64-encoded PNG.

        Args:
            prompt: Text prompt for image generation
            reference_images: Optional list of base64-encoded reference images (up to 14)
            max_retries: Maximum retries on rate limit errors
            return_metadata: If True, return dict with image and generation metadata
            temperature: Generation temperature (0.0-1.0). Lower = more deterministic. Default 0.4.
            image_size: Output resolution - "1K", "2K", or "4K". Default "2K" for better text quality.

        Returns:
            If return_metadata=False: Base64-encoded generated image (string)
            If return_metadata=True: Dict with:
                - image_base64: The generated image
                - model_requested: Model we requested
                - model_used: Model that actually processed (from response)
                - generation_time_ms: Time taken
                - retries: Number of retries needed

        Raises:
            Exception: If all retries fail or non-rate-limit error occurs
        """
        import time

        # Track metadata
        model_requested = "models/gemini-3-pro-image-preview"
        model_used = None
        start_time = time.time()
        total_retries = 0

        # Wait for rate limit
        await self._rate_limit()

        # Call API with retries
        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                logger.debug(f"Generating image with prompt: {prompt[:50]}...")

                # Build contents list: [prompt, image1, image2, ...]
                contents = [prompt]

                # Add reference images as PIL.Image objects
                if reference_images:
                    import base64
                    from PIL import Image
                    from io import BytesIO

                    for img_base64 in reference_images[:14]:  # Max 14 reference images
                        # Convert bytes to base64 string if needed (Bug #11 fix)
                        if isinstance(img_base64, bytes):
                            img_base64 = base64.b64encode(img_base64).decode('utf-8')

                        # Clean and decode base64 to PIL.Image
                        # Remove whitespace, newlines, and add padding if needed
                        clean_data = img_base64.strip().replace('\n', '').replace('\r', '').replace(' ', '')
                        # Add padding if necessary
                        missing_padding = len(clean_data) % 4
                        if missing_padding:
                            clean_data += '=' * (4 - missing_padding)

                        # Decode to bytes - encode to ASCII first if needed
                        try:
                            img_bytes = base64.b64decode(clean_data)
                        except (TypeError, ValueError):
                            # If string decode fails, try encoding to bytes first
                            img_bytes = base64.b64decode(clean_data.encode('ascii'))
                        pil_image = Image.open(BytesIO(img_bytes))
                        contents.append(pil_image)

                    logger.debug(f"Added {len(reference_images)} reference images")

                # Use dedicated image generation model (not the default text model)
                # Temperature controls randomness - lower = more deterministic
                # image_size controls output resolution: "1K", "2K", or "4K"
                response = self.client.models.generate_content(
                    model="gemini-3-pro-image-preview",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
                        image_config=types.ImageConfig(
                            image_size=image_size
                        )
                    )
                )

                # Try to extract actual model used from response metadata
                try:
                    # Response may have model_version in metadata
                    if hasattr(response, 'model_version'):
                        model_used = response.model_version
                    elif hasattr(response, '_result') and hasattr(response._result, 'model_version'):
                        model_used = response._result.model_version
                    # Check candidates for model info
                    elif response.candidates and hasattr(response.candidates[0], 'model'):
                        model_used = response.candidates[0].model
                    else:
                        # Fallback - assume requested model was used
                        model_used = model_requested
                except Exception:
                    model_used = model_requested

                # Extract generated image from response
                # Look for parts with inline_data
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # inline_data.data contains raw bytes in Python SDK
                        # Convert to base64 for return
                        import base64
                        image_base64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                        generation_time_ms = int((time.time() - start_time) * 1000)

                        logger.info(f"Image generated successfully ({len(part.inline_data.data)} bytes) "
                                   f"model_requested={model_requested}, model_used={model_used}, "
                                   f"time={generation_time_ms}ms, retries={total_retries}")

                        # Track usage (fire-and-forget)
                        self._track_usage(
                            operation="generate_image",
                            model=model_used or model_requested,
                            response=response,
                            units=1.0,
                            unit_type="image_generation",
                            duration_ms=generation_time_ms,
                        )

                        if return_metadata:
                            return {
                                "image_base64": image_base64,
                                "model_requested": model_requested,
                                "model_used": model_used,
                                "generation_time_ms": generation_time_ms,
                                "retries": total_retries
                            }
                        return image_base64

                # If no image found in response, raise error
                raise Exception("No image found in Gemini response")

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                    retry_count += 1
                    total_retries += 1
                    if retry_count <= max_retries:
                        retry_delay = 15 * (2 ** (retry_count - 1))
                        logger.warning(f"Rate limit hit. Retry {retry_count}/{max_retries} after {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error("Max retries exceeded for image generation")
                        raise Exception(f"Rate limit exceeded after {max_retries} retries: {e}")
                else:
                    logger.error(f"Error generating image: {e}")
                    raise

        raise last_error or Exception("Unknown error during image generation")

    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        Analyze an image using Gemini Vision API.

        Args:
            image_data: Base64-encoded image data
            prompt: Analysis prompt/question about the image
            max_retries: Maximum retries on rate limit errors

        Returns:
            JSON string with analysis results

        Raises:
            Exception: If all retries fail or non-rate-limit error occurs
        """
        # Wait for rate limit
        await self._rate_limit()

        # Call API with retries
        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                logger.debug(f"Analyzing image with prompt: {prompt[:50]}...")

                # Import image handling
                import base64
                from PIL import Image
                from io import BytesIO

                # Convert bytes to base64 string if needed (Bug #14 fix)
                if isinstance(image_data, bytes):
                    image_data = base64.b64encode(image_data).decode('utf-8')

                # Clean and decode base64 image
                # Remove whitespace, newlines, and add padding if needed
                clean_data = image_data.strip().replace('\n', '').replace('\r', '').replace(' ', '')
                # Add padding if necessary
                missing_padding = len(clean_data) % 4
                if missing_padding:
                    clean_data += '=' * (4 - missing_padding)

                # Decode to bytes - encode to ASCII first if needed
                try:
                    image_bytes = base64.b64decode(clean_data)
                except (TypeError, ValueError):
                    # If string decode fails, try encoding to bytes first
                    image_bytes = base64.b64decode(clean_data.encode('ascii'))
                image = Image.open(BytesIO(image_bytes))

                # Call Gemini Vision API
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[prompt, image]
                )

                # Check for blocked or empty response before accessing .text
                if not response.candidates:
                    block_reason = getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')
                    logger.error(f"Gemini response blocked or empty. Block reason: {block_reason}")
                    raise Exception(f"Gemini response blocked: {block_reason}")

                # Check if the candidate was blocked
                # FinishReason.STOP = normal completion, MAX_TOKENS = hit limit (usually OK)
                # SAFETY, RECITATION, OTHER = blocked
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason') and candidate.finish_reason not in (
                    None,
                    types.FinishReason.STOP,
                    types.FinishReason.MAX_TOKENS
                ):
                    finish_reason = candidate.finish_reason
                    logger.error(f"Gemini candidate blocked. Finish reason: {finish_reason}")
                    raise Exception(f"Gemini response blocked: finish_reason={finish_reason}")

                # Check if candidate has content parts (avoids "whichOneof" error)
                if not hasattr(candidate, 'content') or not candidate.content:
                    logger.error("Gemini response has no content")
                    raise Exception("Gemini response has no content")
                if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
                    logger.error("Gemini response has no content parts")
                    raise Exception("Gemini response has no content parts")

                logger.debug(f"Image analysis complete")

                # Track usage (fire-and-forget)
                self._track_usage(
                    operation="analyze_image",
                    model=self.model_name,
                    response=response,
                    duration_ms=int((time.time() - self._last_call_time) * 1000) if self._last_call_time else None,
                )

                return response.text

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                    retry_count += 1
                    if retry_count <= max_retries:
                        retry_delay = 15 * (2 ** (retry_count - 1))
                        logger.warning(f"Rate limit hit. Retry {retry_count}/{max_retries} after {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error("Max retries exceeded for image analysis")
                        raise Exception(f"Rate limit exceeded after {max_retries} retries: {e}")
                # Check for whichOneof error (protobuf error when response is malformed)
                elif "whichOneof" in error_str:
                    logger.error(f"Gemini returned malformed response (whichOneof error). This usually means the image triggered content safety filters or the response was empty.")
                    raise Exception("Gemini image analysis failed: The image may have triggered content safety filters. Try a different reference ad image.")
                else:
                    logger.error(f"Error analyzing image: {e}")
                    raise

        raise last_error or Exception("Unknown error during image analysis")

    async def review_image(
        self,
        image_data: str,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        Review/evaluate an image using Gemini Vision API.

        Args:
            image_data: Base64-encoded image data
            prompt: Review prompt/criteria
            max_retries: Maximum retries on rate limit errors

        Returns:
            JSON string with review results

        Raises:
            Exception: If all retries fail or non-rate-limit error occurs
        """
        # Reuse analyze_image logic - review is a type of analysis
        return await self.analyze_image(image_data, prompt, max_retries)

    async def analyze_text(
        self,
        text: str,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        Analyze text using Gemini AI with custom prompt.

        General-purpose text analysis method for tasks like hook selection,
        content evaluation, or any text-based AI analysis.

        Args:
            text: Text content to analyze
            prompt: Analysis instructions/question
            max_retries: Maximum retries on rate limit errors

        Returns:
            AI analysis result as string

        Raises:
            Exception: If all retries fail or non-rate-limit error occurs
        """
        import asyncio

        # Wait for rate limit
        await self._rate_limit()

        # Build full prompt
        full_prompt = f"{prompt}\n\n{text}"

        # Call API with retries (following analyze_hook pattern)
        retry_count = 0
        last_error = None

        while retry_count <= max_retries:
            try:
                logger.debug(f"Analyzing text with Gemini (prompt: {prompt[:50]}...)")
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[full_prompt]
                )

                # Check for blocked or empty response (avoids "whichOneof" error)
                if not response.candidates:
                    block_reason = getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')
                    logger.error(f"Gemini text response blocked or empty. Block reason: {block_reason}")
                    raise Exception(f"Gemini response blocked: {block_reason}")

                # FinishReason.STOP = normal completion, MAX_TOKENS = hit limit (usually OK)
                # SAFETY, RECITATION, OTHER = blocked
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason') and candidate.finish_reason not in (
                    None,
                    types.FinishReason.STOP,
                    types.FinishReason.MAX_TOKENS
                ):
                    finish_reason = candidate.finish_reason
                    logger.error(f"Gemini text candidate blocked. Finish reason: {finish_reason}")
                    raise Exception(f"Gemini response blocked: finish_reason={finish_reason}")

                if not hasattr(candidate, 'content') or not candidate.content:
                    logger.error("Gemini text response has no content")
                    raise Exception("Gemini response has no content")
                if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
                    logger.error("Gemini text response has no content parts")
                    raise Exception("Gemini response has no content parts")

                logger.info(f"Text analysis completed successfully")

                # Track usage (fire-and-forget)
                self._track_usage(
                    operation="analyze_text",
                    model=self.model_name,
                    response=response,
                )

                return response.text

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                    retry_count += 1
                    if retry_count <= max_retries:
                        retry_delay = 15 * (2 ** (retry_count - 1))
                        logger.warning(
                            f"Rate limit hit during text analysis. "
                            f"Retry {retry_count}/{max_retries} after {retry_delay}s..."
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Max retries exceeded for text analysis")
                        raise Exception(f"Rate limit exceeded after {max_retries} retries: {e}")
                else:
                    logger.error(f"Error analyzing text: {e}")
                    raise

        raise last_error or Exception("Unknown error during text analysis")
