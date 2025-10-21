"""
Comment Generator - AI-Powered Reply Suggestions

Generates 3 types of Twitter reply suggestions using Gemini:
- add_value: Share insights, tips, or data
- ask_question: Ask thoughtful follow-ups
- mirror_reframe: Acknowledge and reframe with fresh angle

V1: Single LLM call per tweet returning JSON with all 3 suggestions
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import google.generativeai as genai

from viraltracker.core.config import FinderConfig
from viraltracker.core.database import get_supabase_client
from viraltracker.generation.comment_finder import TweetMetrics, ScoringResult

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


class CommentGenerator:
    """
    Generates AI-powered comment suggestions using Gemini.

    Uses prompt templates and voice configuration to generate contextual,
    on-brand replies to tweets.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize comment generator.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        # Configure Gemini
        genai.configure(api_key=self.api_key)

        # Load prompts
        self.prompts = self._load_prompts()

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
            model_name = config.generation.get('model', 'gemini-2.5-flash')
            temperature = config.generation.get('temperature', 0.2)
            max_tokens = config.generation.get('max_tokens', 80)

            model = genai.GenerativeModel(model_name)

            response = model.generate_content(
                prompt,
                generation_config={
                    'temperature': temperature,
                    'max_output_tokens': 500,  # For JSON response
                    'response_mime_type': 'application/json'
                }
            )

            # Check safety ratings - multiple ways to detect blocking
            if not response.candidates or not hasattr(response, 'text') or not response.text:
                logger.warning(f"No valid response for tweet {tweet.tweet_id} - likely blocked by safety")
                return GenerationResult(
                    tweet_id=tweet.tweet_id,
                    suggestions=[],
                    success=False,
                    error="Response blocked by safety filters",
                    safety_blocked=True
                )

            # Parse JSON response
            try:
                suggestions_data = json.loads(response.text)
            except (json.JSONDecodeError, AttributeError) as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response text: {response.text}")
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

            # Validate length (should be under max_tokens)
            for suggestion in suggestions:
                if len(suggestion.comment_text) > max_tokens * 2:  # 2x buffer for safety
                    logger.warning(f"Suggestion too long ({len(suggestion.comment_text)} chars): {suggestion.comment_text[:100]}...")

            logger.info(f"Generated {len(suggestions)} suggestions for tweet {tweet.tweet_id}")

            return GenerationResult(
                tweet_id=tweet.tweet_id,
                suggestions=suggestions,
                success=True
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
    scoring_result: ScoringResult
) -> List[str]:
    """
    Save generated comment suggestions to database.

    Args:
        project_id: Project UUID
        tweet_id: Tweet ID
        suggestions: List of CommentSuggestion objects
        scoring_result: Scoring result with scores and label

    Returns:
        List of generated_comments IDs
    """
    db = get_supabase_client()

    # Build "why" rationale
    why = _build_why_rationale(scoring_result)

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
            'status': 'pending'
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


def _build_why_rationale(scoring_result: ScoringResult) -> str:
    """
    Build short rationale explaining why this tweet was selected.

    Args:
        scoring_result: Scoring result

    Returns:
        Short rationale string
    """
    components = []

    # Highlight top scoring factors
    if scoring_result.velocity > 0.7:
        components.append("high velocity")
    if scoring_result.relevance > 0.7:
        components.append(f"topic {scoring_result.best_topic} ({scoring_result.best_topic_similarity:.2f})")
    if scoring_result.openness > 0.5:
        components.append("open/question")
    if scoring_result.author_quality > 0.8:
        components.append("quality author")

    if components:
        return " + ".join(components)
    else:
        return f"score {scoring_result.total_score:.2f}"
