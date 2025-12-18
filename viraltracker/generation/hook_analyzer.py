"""
Hook Analyzer for Twitter Content

Analyzes outlier tweets to understand what makes them viral using AI-powered classification.

Uses Google Gemini to classify:
- Hook types (14 types from Hook Intelligence)
- Emotional triggers (humor, validation, curiosity, etc.)
- Content patterns (question, listicle, statement, story)

Usage:
    analyzer = HookAnalyzer()
    analysis = analyzer.analyze_hook(tweet_text)
    print(f"Hook type: {analysis.hook_type}")
    print(f"Emotional trigger: {analysis.emotional_trigger}")
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import json
import time

from google import genai
from google.genai import types

from ..core.config import Config


logger = logging.getLogger(__name__)


# Hook types from Hook Intelligence framework
HOOK_TYPES = [
    "relatable_slice",       # Relatable slice of life moment
    "shock_violation",       # Shock/violation of expectations
    "listicle_howto",       # Listicle/how-to guide
    "hot_take",             # Hot take/controversial opinion
    "question_curiosity",   # Question/curiosity gap
    "story_narrative",      # Story/narrative arc
    "data_statistic",       # Data point/statistic
    "personal_confession",  # Personal confession/vulnerability
    "before_after",         # Before/after transformation
    "mistake_lesson",       # Mistake/lesson learned
    "validation_permission", # Validation/permission to feel
    "call_out",             # Call-out/social commentary
    "trend_react",          # Trend reaction/commentary
    "authority_credibility" # Authority/credibility signal
]

EMOTIONAL_TRIGGERS = [
    "humor",        # Funny, laugh-out-loud
    "validation",   # You're not alone, permission to feel
    "curiosity",    # What happens next? How does this work?
    "surprise",     # Unexpected, shocking, wow
    "anger",        # Injustice, frustration, outrage
    "fear",         # Concern, worry, caution
    "joy",          # Happiness, celebration, delight
    "sadness",      # Empathy, sympathy, grief
    "nostalgia",    # Reminiscence, throwback
    "pride"         # Achievement, accomplishment, inspiration
]

CONTENT_PATTERNS = [
    "question",     # Asks a question
    "statement",    # Makes a statement
    "listicle",     # Numbered list or tips
    "story",        # Narrative arc
    "comparison",   # Before/after, this vs that
    "hot_take",     # Strong opinion/controversial
    "observation",  # Noticing something
    "instruction"   # How-to, step-by-step
]


@dataclass
class HookAnalysis:
    """Result of hook analysis"""
    tweet_text: str

    # Classifications
    hook_type: str
    hook_type_confidence: float  # 0-1

    emotional_trigger: str
    emotional_trigger_confidence: float  # 0-1

    content_pattern: str
    content_pattern_confidence: float  # 0-1

    # Explanations
    hook_explanation: str  # Why this hook works
    adaptation_notes: str  # How to adapt for long-form

    # Metadata
    has_emoji: bool
    has_hashtags: bool
    has_question_mark: bool
    word_count: int

    # Source tweet ID (optional)
    tweet_id: Optional[str] = None


class HookAnalyzer:
    """
    Analyzes tweet hooks using AI classification

    Uses Google Gemini to understand what makes tweets viral and
    how to adapt those hooks for long-form content generation.
    """

    def __init__(self, model: str = "gemini-2.0-flash-exp"):
        """
        Initialize hook analyzer

        Args:
            model: Gemini model to use (default: gemini-2.0-flash-exp for speed/cost)
        """
        self.model_name = model

        # Configure Gemini
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.client = genai.Client(api_key=api_key)

        logger.info(f"HookAnalyzer initialized with model: {model}")

    def analyze_hook(self, tweet_text: str, tweet_id: Optional[str] = None) -> HookAnalysis:
        """
        Analyze a tweet's hook using AI

        Args:
            tweet_text: Tweet content to analyze
            tweet_id: Optional tweet ID for reference

        Returns:
            HookAnalysis with classifications and explanations
        """
        # Build prompt
        prompt = self._build_analysis_prompt(tweet_text)

        # Call Gemini
        logger.debug(f"Analyzing tweet: {tweet_text[:50]}...")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[prompt]
        )

        # Parse response
        analysis = self._parse_response(tweet_text, response.text)

        # Add tweet ID if provided
        if tweet_id:
            analysis.tweet_id = tweet_id

        return analysis

    def analyze_batch(
        self,
        tweets: List[str],
        max_concurrent: int = 5,
        requests_per_minute: int = 9,  # Stay under 10 req/min limit
        max_retries: int = 3
    ) -> List[HookAnalysis]:
        """
        Analyze multiple tweets in batch with rate limiting

        Args:
            tweets: List of tweet texts
            max_concurrent: Max concurrent API calls (unused, kept for compatibility)
            requests_per_minute: Maximum requests per minute (default: 9 for safety)
            max_retries: Maximum retries for rate limit errors (default: 3)

        Returns:
            List of HookAnalysis results
        """
        results = []
        delay_between_requests = 60.0 / requests_per_minute  # Seconds between requests

        logger.info(f"Analyzing {len(tweets)} tweets with rate limit: {requests_per_minute} req/min")
        logger.info(f"Delay between requests: {delay_between_requests:.1f}s")

        for i, tweet in enumerate(tweets, 1):
            retry_count = 0
            success = False

            while not success and retry_count <= max_retries:
                try:
                    analysis = self.analyze_hook(tweet)
                    results.append(analysis)
                    success = True
                    logger.info(f"Analyzed tweet {i}/{len(tweets)}")

                except Exception as e:
                    error_str = str(e)

                    # Check if it's a rate limit error (429)
                    if "429" in error_str or "quota" in error_str.lower():
                        retry_count += 1
                        if retry_count <= max_retries:
                            # Extract retry delay from error if available
                            retry_delay = 45  # Default to 45 seconds
                            if "retry_delay" in error_str:
                                # Try to parse retry delay from error
                                try:
                                    import re
                                    match = re.search(r'seconds:\s*(\d+)', error_str)
                                    if match:
                                        retry_delay = int(match.group(1))
                                except:
                                    pass

                            logger.warning(f"Rate limit hit. Retry {retry_count}/{max_retries} after {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.error(f"Max retries exceeded for tweet {i}/{len(tweets)}: {e}")
                            results.append(self._default_analysis(tweet, f"Rate limit exceeded: {e}"))
                            success = True  # Stop retrying
                    else:
                        # Non-rate-limit error
                        logger.error(f"Error analyzing tweet {i}/{len(tweets)}: {e}")
                        results.append(self._default_analysis(tweet, str(e)))
                        success = True

            # Rate limit: wait between requests (but not after the last one)
            if i < len(tweets):
                time.sleep(delay_between_requests)

        return results

    def _build_analysis_prompt(self, tweet_text: str) -> str:
        """Build analysis prompt for Gemini"""

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

    def _parse_response(self, tweet_text: str, response_text: str) -> HookAnalysis:
        """Parse Gemini response into HookAnalysis"""

        try:
            # Extract JSON from response (might have markdown code blocks)
            json_text = response_text.strip()
            if json_text.startswith("```json"):
                json_text = json_text[7:]  # Remove ```json
            if json_text.startswith("```"):
                json_text = json_text[3:]  # Remove ```
            if json_text.endswith("```"):
                json_text = json_text[:-3]  # Remove ```

            json_text = json_text.strip()

            # Parse JSON
            data = json.loads(json_text)

            # Extract metadata from tweet
            has_emoji = any(char for char in tweet_text if ord(char) > 127)
            has_hashtags = '#' in tweet_text
            has_question_mark = '?' in tweet_text
            word_count = len(tweet_text.split())

            return HookAnalysis(
                tweet_text=tweet_text,
                hook_type=data.get("hook_type", "unknown"),
                hook_type_confidence=float(data.get("hook_type_confidence", 0.5)),
                emotional_trigger=data.get("emotional_trigger", "unknown"),
                emotional_trigger_confidence=float(data.get("emotional_trigger_confidence", 0.5)),
                content_pattern=data.get("content_pattern", "unknown"),
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
            return self._default_analysis(tweet_text, f"JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return self._default_analysis(tweet_text, str(e))

    def _default_analysis(self, tweet_text: str, error: str) -> HookAnalysis:
        """Return default analysis when parsing fails"""

        has_emoji = any(char for char in tweet_text if ord(char) > 127)
        has_hashtags = '#' in tweet_text
        has_question_mark = '?' in tweet_text
        word_count = len(tweet_text.split())

        return HookAnalysis(
            tweet_text=tweet_text,
            hook_type="unknown",
            hook_type_confidence=0.0,
            emotional_trigger="unknown",
            emotional_trigger_confidence=0.0,
            content_pattern="unknown",
            content_pattern_confidence=0.0,
            hook_explanation=f"Analysis failed: {error}",
            adaptation_notes="Unable to provide adaptation notes",
            has_emoji=has_emoji,
            has_hashtags=has_hashtags,
            has_question_mark=has_question_mark,
            word_count=word_count
        )

    def export_analysis(self, analyses: List[HookAnalysis], output_path: str) -> None:
        """
        Export hook analyses to JSON

        Args:
            analyses: List of HookAnalysis results
            output_path: Path to save JSON file
        """
        data = {
            "total_analyzed": len(analyses),
            "analyses": []
        }

        for analysis in analyses:
            data["analyses"].append({
                "tweet_id": analysis.tweet_id,  # Add tweet ID for reference
                "tweet_text": analysis.tweet_text,
                "hook_type": analysis.hook_type,
                "hook_type_confidence": analysis.hook_type_confidence,
                "emotional_trigger": analysis.emotional_trigger,
                "emotional_trigger_confidence": analysis.emotional_trigger_confidence,
                "content_pattern": analysis.content_pattern,
                "content_pattern_confidence": analysis.content_pattern_confidence,
                "hook_explanation": analysis.hook_explanation,
                "adaptation_notes": analysis.adaptation_notes,
                "metadata": {
                    "has_emoji": analysis.has_emoji,
                    "has_hashtags": analysis.has_hashtags,
                    "has_question_mark": analysis.has_question_mark,
                    "word_count": analysis.word_count
                }
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(analyses)} hook analyses to {output_path}")
