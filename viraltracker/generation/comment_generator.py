"""
Comment Generator - AI-Powered Reply Suggestions

Generates 3 types of Twitter reply suggestions using Gemini:
- add_value: Share insights, tips, or data
- ask_question: Ask thoughtful follow-ups
- mirror_reframe: Acknowledge and reframe with fresh angle

V1: Single LLM call per tweet returning JSON with all 3 suggestions
V1.2: Cost tracking for API usage transparency
"""

import os
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import deque

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from viraltracker.core.config import FinderConfig
from viraltracker.core.database import get_supabase_client
from viraltracker.generation.comment_finder import TweetMetrics, ScoringResult
from viraltracker.generation.cost_tracking import extract_and_calculate_cost

logger = logging.getLogger(__name__)


@dataclass
class CommentSuggestion:
    """A single comment suggestion"""
    suggestion_type: str  # 'add_value', 'ask_question', 'mirror_reframe'
    comment_text: str
    rank: int = 1


@dataclass
class GenerationResult:
    """Result of comment generation for a tweet"""
    tweet_id: str
    suggestions: List[CommentSuggestion]
    success: bool
    error: Optional[str] = None
    safety_blocked: bool = False
    api_cost_usd: Optional[float] = None  # V1.2: Cost tracking


class RateLimiter:
    """
    Rate limiter for Gemini API calls with exponential backoff.

    Tracks API calls per minute and enforces rate limits to prevent 429 errors.
    """

    def __init__(self, max_requests_per_minute: int = 15):
        """
        Initialize rate limiter.

        Args:
            max_requests_per_minute: Maximum API calls allowed per minute
        """
        self.max_rpm = max_requests_per_minute
        self.call_times = deque()  # Timestamps of recent API calls
        self.total_calls = 0

    def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        now = time.time()

        # Remove calls older than 1 minute
        while self.call_times and now - self.call_times[0] > 60:
            self.call_times.popleft()

        # If at limit, wait until oldest call expires
        if len(self.call_times) >= self.max_rpm:
            sleep_time = 60 - (now - self.call_times[0]) + 0.1  # Small buffer
            if sleep_time > 0:
                logger.info(f"Rate limit reached ({self.max_rpm} req/min). Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                # Clean up after waiting
                now = time.time()
                while self.call_times and now - self.call_times[0] > 60:
                    self.call_times.popleft()

    def record_call(self):
        """Record an API call"""
        self.call_times.append(time.time())
        self.total_calls += 1

    def get_current_rate(self) -> int:
        """Get current calls per minute"""
        now = time.time()
        # Count calls in last minute
        return sum(1 for t in self.call_times if now - t <= 60)


class CommentGenerator:
    """
    Generates AI-powered comment suggestions using Gemini.

    Uses prompt templates and voice configuration to generate contextual,
    on-brand replies to tweets.
    """

    def __init__(self, api_key: Optional[str] = None, max_requests_per_minute: int = 15):
        """
        Initialize comment generator.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            max_requests_per_minute: Rate limit for API calls (default: 15)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        # Configure Gemini
        genai.configure(api_key=self.api_key)

        # Load prompts
        self.prompts = self._load_prompts()

        # Initialize rate limiter (V1.1)
        self.rate_limiter = RateLimiter(max_requests_per_minute)

    def _load_prompts(self) -> Dict:
        """Load prompt templates from JSON file"""
        prompt_file = Path(__file__).parent / 'prompts' / 'comments.json'

        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        with open(prompt_file, 'r') as f:
            return json.load(f)

    def generate_suggestions(
        self,
        tweet: TweetMetrics,
        topic: str,
        config: FinderConfig
    ) -> GenerationResult:
        """
        Generate 3 comment suggestions for a tweet.

        Args:
            tweet: Tweet to generate comments for
            topic: Best-match taxonomy topic label
            config: Finder configuration with voice/persona

        Returns:
            GenerationResult with 3 suggestions or error
        """
        try:
            # Build prompt
            prompt = self._build_prompt(tweet.text, topic, config)

            # Call Gemini
            model_name = config.generation.get('model', 'models/gemini-flash-latest')
            temperature = config.generation.get('temperature', 0.2)
            max_tokens = config.generation.get('max_tokens', 80)

            model = genai.GenerativeModel(model_name)

            # Configure safety settings to be less restrictive for business discussions
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            }

            # V1.1: Rate limiting with exponential backoff
            max_retries = 3
            base_delay = 2
            api_cost_usd = None  # V1.2: Initialize cost tracking

            for attempt in range(max_retries):
                try:
                    # Wait if rate limit would be exceeded
                    self.rate_limiter.wait_if_needed()

                    # Make API call
                    response = model.generate_content(
                        prompt,
                        generation_config={
                            'temperature': temperature,
                            'max_output_tokens': 8192,  # Large buffer for JSON response with 3 suggestions
                            'response_mime_type': 'application/json'
                        },
                        safety_settings=safety_settings
                    )

                    # Record successful call
                    self.rate_limiter.record_call()

                    # V1.2: Extract token usage and calculate cost
                    api_cost_obj = extract_and_calculate_cost(response)
                    api_cost_usd = api_cost_obj.total_cost_usd if api_cost_obj else None

                    if api_cost_obj:
                        logger.debug(f"API cost for tweet {tweet.tweet_id}: {api_cost_obj}")

                    break  # Success, exit retry loop

                except Exception as e:
                    error_str = str(e).lower()

                    # Check if it's a rate limit error (429)
                    if '429' in error_str or 'quota' in error_str or 'rate limit' in error_str:
                        if attempt < max_retries - 1:
                            # Exponential backoff
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"Rate limit hit (429). Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                            continue
                        else:
                            # Final attempt failed
                            logger.error(f"Rate limit exceeded after {max_retries} attempts")
                            raise
                    else:
                        # Not a rate limit error, raise immediately
                        raise

            # Check safety ratings - accessing response.text can raise exception if blocked
            response_text = None
            try:
                if response.candidates and hasattr(response, 'text'):
                    response_text = response.text
            except Exception as e:
                # response.text access failed - likely safety blocked
                logger.warning(f"Failed to access response.text: {e}")

            if not response_text:
                # Log safety ratings for debugging
                safety_info = "unknown"
                finish_reason = "unknown"
                if response.candidates:
                    try:
                        safety_info = str(response.candidates[0].safety_ratings)
                        finish_reason = str(response.candidates[0].finish_reason)
                        logger.warning(f"Tweet {tweet.tweet_id} blocked - Finish reason: {finish_reason}")
                        logger.warning(f"Safety ratings: {safety_info}")
                    except Exception as e:
                        logger.warning(f"Could not access safety ratings: {e}")

                logger.warning(f"No valid response for tweet {tweet.tweet_id} - likely blocked by safety")
                return GenerationResult(
                    tweet_id=tweet.tweet_id,
                    suggestions=[],
                    success=False,
                    error=f"Response blocked by safety filters. Finish reason: {finish_reason}. Ratings: {safety_info}",
                    safety_blocked=True
                )

            # Parse JSON response
            try:
                suggestions_data = json.loads(response_text)
            except (json.JSONDecodeError, AttributeError) as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response text: {response_text}")
                return GenerationResult(
                    tweet_id=tweet.tweet_id,
                    suggestions=[],
                    success=False,
                    error=f"JSON parse error: {e}"
                )

            # Validate response structure
            required_keys = ['add_value', 'ask_question', 'mirror_reframe']
            if not all(k in suggestions_data for k in required_keys):
                logger.error(f"Response missing required keys. Got: {suggestions_data.keys()}")
                return GenerationResult(
                    tweet_id=tweet.tweet_id,
                    suggestions=[],
                    success=False,
                    error=f"Missing required suggestion types"
                )

            # Create suggestion objects
            suggestions = [
                CommentSuggestion('add_value', suggestions_data['add_value'], rank=1),
                CommentSuggestion('ask_question', suggestions_data['ask_question'], rank=2),
                CommentSuggestion('mirror_reframe', suggestions_data['mirror_reframe'], rank=3)
            ]

            # V1.1: Apply quality filter to each suggestion
            filtered_suggestions = []
            for suggestion in suggestions:
                passes_filter, rejection_reason = _quality_filter_suggestion(
                    suggestion.comment_text,
                    tweet.text
                )

                if passes_filter:
                    filtered_suggestions.append(suggestion)
                else:
                    logger.info(f"Filtered out {suggestion.suggestion_type} suggestion: {rejection_reason} - '{suggestion.comment_text[:50]}...'")

            # If all suggestions were filtered, log warning but return empty result
            if len(filtered_suggestions) == 0:
                logger.warning(f"All suggestions filtered out for tweet {tweet.tweet_id}")
                return GenerationResult(
                    tweet_id=tweet.tweet_id,
                    suggestions=[],
                    success=False,
                    error="All suggestions filtered by quality checks"
                )

            logger.info(f"Generated {len(filtered_suggestions)}/{len(suggestions)} quality suggestions for tweet {tweet.tweet_id}")

            return GenerationResult(
                tweet_id=tweet.tweet_id,
                suggestions=filtered_suggestions,
                success=True,
                api_cost_usd=api_cost_usd  # V1.2: Include cost
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error generating suggestions for tweet {tweet.tweet_id}: {e}")

            # Check if error is safety-related
            is_safety = any(keyword in error_msg.lower() for keyword in [
                'safety', 'blocked', 'candidate', 'response.text', 'valid `part`'
            ])

            return GenerationResult(
                tweet_id=tweet.tweet_id,
                suggestions=[],
                success=False,
                error=error_msg,
                safety_blocked=is_safety
            )

    def _build_prompt(self, tweet_text: str, topic: str, config: FinderConfig) -> str:
        """
        Build generation prompt from template.

        Args:
            tweet_text: Original tweet text
            topic: Best-match taxonomy topic
            config: Finder configuration

        Returns:
            Formatted prompt string
        """
        # Build voice instructions
        voice_instructions = self._build_voice_instructions(config)

        # Format user prompt
        max_tokens = config.generation.get('max_tokens', 80)

        user_prompt = self.prompts['user_prompt_template'].format(
            tweet_text=tweet_text,
            topic=topic,
            voice_instructions=voice_instructions,
            max_tokens=max_tokens
        )

        # Combine system + user prompts
        system_prompt = self.prompts['system_prompt']
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        return full_prompt

    def _build_voice_instructions(self, config: FinderConfig) -> str:
        """
        Build voice/persona instructions from config.

        Args:
            config: Finder configuration

        Returns:
            Formatted voice instructions
        """
        persona = config.voice.persona
        constraints = "\n".join(f"- {c}" for c in config.voice.constraints)

        good_examples = config.voice.examples.get('good', [])
        good_examples_text = "\n".join(f"- \"{ex}\"" for ex in good_examples[:3])  # Max 3 examples

        bad_examples = config.voice.examples.get('bad', [])
        bad_examples_text = "\n".join(f"- \"{ex}\"" for ex in bad_examples[:3])

        voice_instructions = self.prompts['voice_instructions_template'].format(
            persona=persona,
            constraints=constraints,
            good_examples=good_examples_text if good_examples_text else "- (none provided)",
            bad_examples=bad_examples_text if bad_examples_text else "- (none provided)"
        )

        return voice_instructions


def save_suggestions_to_db(
    project_id: str,
    tweet_id: str,
    suggestions: List[CommentSuggestion],
    scoring_result: ScoringResult,
    tweet: Optional[TweetMetrics] = None,
    api_cost_usd: Optional[float] = None  # V1.2: Cost tracking
) -> List[str]:
    """
    Save generated comment suggestions to database.

    Args:
        project_id: Project UUID
        tweet_id: Tweet ID
        suggestions: List of CommentSuggestion objects
        scoring_result: Scoring result with scores and label
        tweet: Optional tweet metrics for enhanced rationale (V1.1)
        api_cost_usd: Optional API cost in USD (V1.2)

    Returns:
        List of generated_comments IDs
    """
    db = get_supabase_client()

    # Build "why" rationale (V1.1: with enhanced metrics if tweet provided)
    why = _build_why_rationale(scoring_result, tweet)

    # V1.2: Calculate cost per suggestion (divide total by number of suggestions)
    cost_per_suggestion = None
    if api_cost_usd is not None and len(suggestions) > 0:
        cost_per_suggestion = api_cost_usd / len(suggestions)

    # Prepare data for database
    records = []
    for suggestion in suggestions:
        record = {
            'project_id': project_id,
            'tweet_id': tweet_id,
            'suggestion_type': suggestion.suggestion_type,
            'comment_text': suggestion.comment_text,
            'score_total': scoring_result.total_score,
            'label': scoring_result.label,
            'topic': scoring_result.best_topic,
            'why': why,
            'rank': suggestion.rank,
            'review_status': 'pending',
            'status': 'pending',
            'api_cost_usd': cost_per_suggestion  # V1.2: Store cost
        }
        records.append(record)

    # Upsert to generated_comments table
    result = db.table('generated_comments').upsert(
        records,
        on_conflict='project_id,tweet_id,suggestion_type'
    ).execute()

    comment_ids = [r['id'] for r in result.data] if result.data else []

    logger.info(f"Saved {len(comment_ids)} comment suggestions for tweet {tweet_id}")

    return comment_ids


def _quality_filter_suggestion(suggestion_text: str, tweet_text: str) -> tuple[bool, Optional[str]]:
    """
    Filter out low-quality comment suggestions.

    Args:
        suggestion_text: Generated comment text
        tweet_text: Original tweet text

    Returns:
        Tuple of (passes_filter, rejection_reason)
        - True if suggestion passes quality checks
        - False with reason string if suggestion should be filtered out
    """
    # 1. Length check (30-120 chars)
    if len(suggestion_text) < 30:
        return False, "too_short"
    if len(suggestion_text) > 120:
        return False, "too_long"

    # 2. Generic phrase detection
    generic_phrases = [
        "great post",
        "thanks for sharing",
        "well said",
        "i agree",
        "totally agree",
        "this is awesome",
        "love this",
        "so true",
        "couldn't agree more",
        "exactly",
        "100%",
        "this!",
        "yes!",
        "very interesting",
        "interesting point",
        "good point"
    ]

    suggestion_lower = suggestion_text.lower()
    for phrase in generic_phrases:
        if phrase in suggestion_lower:
            # Allow if it's part of a longer sentence (not just the generic phrase)
            # Must have at least 20 chars beyond the generic phrase
            if len(suggestion_text) - len(phrase) < 20:
                return False, f"generic_phrase:{phrase}"

    # 3. Circular response detection (>50% word overlap)
    # Tokenize both texts (simple word splitting)
    tweet_words = set(tweet_text.lower().split())
    suggestion_words = set(suggestion_text.lower().split())

    # Remove common stop words that don't indicate circular responses
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'be', 'been',
                  'this', 'that', 'these', 'those', 'i', 'you', 'we', 'they', 'it'}

    tweet_words = tweet_words - stop_words
    suggestion_words = suggestion_words - stop_words

    if len(suggestion_words) > 0:
        overlap = len(tweet_words & suggestion_words)
        overlap_ratio = overlap / len(suggestion_words)

        if overlap_ratio > 0.5:
            return False, f"circular_response:{overlap_ratio:.2f}"

    return True, None


def _build_why_rationale(scoring_result: ScoringResult, tweet: Optional[TweetMetrics] = None) -> str:
    """
    Build short rationale explaining why this tweet was selected.

    V1.1: Enhanced with engagement metrics when tweet data is provided.

    Args:
        scoring_result: Scoring result
        tweet: Optional tweet metrics for enhanced rationale

    Returns:
        Short rationale string (under 100 chars)
    """
    components = []

    # V1.1: Add engagement metrics if tweet provided
    if tweet:
        # Calculate likes per hour
        tweet_timestamp = tweet.tweeted_at.timestamp()
        tweet_age_hours = (time.time() - tweet_timestamp) / 3600
        if tweet_age_hours > 0 and tweet.likes > 0:
            likes_per_hour = tweet.likes / tweet_age_hours
            if likes_per_hour >= 1000:
                components.append(f"{likes_per_hour/1000:.1f}K likes/hr")
            elif likes_per_hour >= 100:
                components.append(f"{int(likes_per_hour)} likes/hr")

        # Add follower count if significant
        if tweet.author_followers >= 10000:
            components.append(f"{tweet.author_followers/1000:.0f}K followers")
        elif tweet.author_followers >= 1000:
            components.append(f"{tweet.author_followers/1000:.1f}K followers")

    # Highlight top scoring factors
    if scoring_result.relevance > 0.7:
        # Show topic match percentage
        match_pct = int(scoring_result.best_topic_similarity * 100)
        components.append(f"{scoring_result.best_topic} ({match_pct}%)")

    if scoring_result.velocity > 0.7:
        components.append("trending")

    if scoring_result.openness > 0.5:
        components.append("open/question")

    if components:
        result = " + ".join(components)
        # Truncate if over 100 chars
        if len(result) > 100:
            result = result[:97] + "..."
        return result
    else:
        return f"score {scoring_result.total_score:.2f}"
