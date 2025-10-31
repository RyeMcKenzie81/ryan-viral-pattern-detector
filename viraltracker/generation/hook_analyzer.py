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

import google.generativeai as genai

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

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

        logger.info(f"HookAnalyzer initialized with model: {model}")

    def analyze_hook(self, tweet_text: str) -> HookAnalysis:
        """
        Analyze a tweet's hook using AI

        Args:
            tweet_text: Tweet content to analyze

        Returns:
            HookAnalysis with classifications and explanations
        """
        # Build prompt
        prompt = self._build_analysis_prompt(tweet_text)

        # Call Gemini
        logger.debug(f"Analyzing tweet: {tweet_text[:50]}...")
        response = self.model.generate_content(prompt)

        # Parse response
        analysis = self._parse_response(tweet_text, response.text)

        return analysis

    def analyze_batch(self, tweets: List[str], max_concurrent: int = 5) -> List[HookAnalysis]:
        """
        Analyze multiple tweets in batch

        Args:
            tweets: List of tweet texts
            max_concurrent: Max concurrent API calls

        Returns:
            List of HookAnalysis results
        """
        results = []

        for tweet in tweets:
            try:
                analysis = self.analyze_hook(tweet)
                results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing tweet: {e}")
                # Return default analysis on error
                results.append(self._default_analysis(tweet, str(e)))

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
