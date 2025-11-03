"""
Thread Generator for Twitter

Generates Twitter threads (5-10 tweets) from viral hooks.

Takes hook analysis from Phase 2B and adapts it into a full thread
that maintains the viral hook while promoting the target product/service.

Usage:
    generator = ThreadGenerator(db_connection)
    content = generator.generate(hook_analysis, project_context)
    generator.save_to_db(content)
"""

import logging
from typing import Dict, List
import json
from datetime import datetime

from .content_generator import ContentGenerator, GeneratedContent


logger = logging.getLogger(__name__)


class ThreadGenerator(ContentGenerator):
    """
    Generates Twitter threads from viral hooks

    Creates 5-10 tweet threads that:
    - Open with adapted viral hook
    - Maintain emotional trigger
    - Provide value to target audience
    - End with subtle CTA
    """

    def generate(self,
                 hook_analysis: Dict,
                 project_context: Dict,
                 min_tweets: int = 5,
                 max_tweets: int = 10,
                 include_emoji: bool = True) -> GeneratedContent:
        """
        Generate Twitter thread from hook analysis

        Args:
            hook_analysis: Hook analysis from Phase 2B
            project_context: Project info (name, description, audience, benefits)
            min_tweets: Minimum tweets in thread (default 5)
            max_tweets: Maximum tweets in thread (default 10)
            include_emoji: Include emojis in tweets (default True)

        Returns:
            GeneratedContent with thread data
        """
        logger.info(f"Generating thread from hook: {hook_analysis.get('hook_type')}")

        # Build prompt
        prompt = self._build_thread_prompt(
            hook_analysis,
            project_context,
            min_tweets,
            max_tweets,
            include_emoji
        )

        # Estimate cost (rough estimate)
        prompt_tokens = len(prompt.split()) * 1.3  # Rough token estimate
        output_tokens = max_tweets * 60  # ~60 tokens per tweet
        estimated_cost = self._estimate_cost(int(prompt_tokens), int(output_tokens))

        # Call Gemini
        logger.debug("Calling Gemini API for thread generation")
        response = self.model.generate_content(prompt)

        # Parse response
        thread_data = self._parse_thread_response(response.text)

        # Create GeneratedContent object
        content = GeneratedContent(
            source_tweet_id=hook_analysis.get('tweet_id'),  # Updated to use tweet_id field
            source_tweet_text=hook_analysis.get('tweet_text', ''),
            hook_type=hook_analysis.get('hook_type', 'unknown'),
            emotional_trigger=hook_analysis.get('emotional_trigger', 'unknown'),
            content_pattern=hook_analysis.get('content_pattern', 'unknown'),
            hook_explanation=hook_analysis.get('hook_explanation', ''),
            adaptation_notes=hook_analysis.get('adaptation_notes', ''),
            content_type='thread',
            content_title=thread_data.get('thread_title', 'Twitter Thread'),
            content_body=self._format_thread_as_text(thread_data['tweets']),
            content_metadata=thread_data,
            project_id=project_context.get('project_id'),
            project_context=json.dumps(project_context),
            api_cost_usd=estimated_cost,
            model_used=self.model_name,
            status='pending',
            created_at=datetime.now()
        )

        logger.info(f"Generated thread with {len(thread_data['tweets'])} tweets")
        return content

    def _build_thread_prompt(self,
                            hook_analysis: Dict,
                            project_context: Dict,
                            min_tweets: int,
                            max_tweets: int,
                            include_emoji: bool) -> str:
        """Build AI prompt for thread generation"""

        tweet_text = hook_analysis.get('tweet_text', '')
        hook_type = hook_analysis.get('hook_type', 'unknown')
        emotional_trigger = hook_analysis.get('emotional_trigger', 'unknown')
        hook_explanation = hook_analysis.get('hook_explanation', '')
        adaptation_notes = hook_analysis.get('adaptation_notes', '')

        product_name = project_context.get('product_name', 'our product')
        product_description = project_context.get('product_description', '')
        target_audience = project_context.get('target_audience', 'users')
        key_benefits = project_context.get('key_benefits', [])

        benefits_text = "\n".join([f"- {b}" for b in key_benefits]) if key_benefits else "N/A"
        emoji_instruction = "Include 1-2 relevant emojis per tweet" if include_emoji else "Do not use emojis"

        prompt = f"""You are an expert Twitter content creator who adapts viral hooks into engaging threads.

SOURCE TWEET (went viral):
"{tweet_text}"

HOOK ANALYSIS:
- Hook type: {hook_type}
- Emotional trigger: {emotional_trigger}
- Why it works: {hook_explanation}
- How to adapt: {adaptation_notes}

PROJECT CONTEXT:
- Product/Service: {product_name}
- Description: {product_description}
- Target audience: {target_audience}
- Key benefits:
{benefits_text}

TASK:
Create a Twitter thread ({min_tweets}-{max_tweets} tweets) that:
1. Opens with an ADAPTED version of the viral hook (don't copy it directly)
2. Maintains the "{emotional_trigger}" emotional trigger throughout
3. Expands on the core idea with insights relevant to {product_name}
4. Provides genuine value to {target_audience}
5. Ends with a subtle, natural CTA for {product_name}

REQUIREMENTS:
- Each tweet must be ≤280 characters (STRICT LIMIT)
- Use simple, conversational language
- {emoji_instruction}
- DO NOT use hashtags
- Thread should flow naturally, each tweet connects to the next
- CTA should be subtle and helpful, not pushy or salesy
- Stay true to the emotional trigger and hook type
- Make it authentic and valuable, not just promotional

OUTPUT FORMAT (JSON):
{{
  "thread_title": "Brief title for this thread",
  "tweets": [
    {{"number": 1, "text": "Opening tweet with adapted hook...", "char_count": 145}},
    {{"number": 2, "text": "Expansion or insight...", "char_count": 178}},
    {{"number": 3, "text": "More value...", "char_count": 156}},
    ...
    {{"number": N, "text": "Closing tweet with CTA...", "char_count": 201}}
  ],
  "hook_adaptation_explanation": "Brief explanation of how you adapted the hook",
  "key_insights": ["insight 1", "insight 2", "insight 3"],
  "estimated_engagement_score": 0.75
}}

IMPORTANT:
- Return ONLY valid JSON, no additional text or markdown
- Every tweet must be under 280 characters
- Focus on value first, product mention second
- Make the adaptation feel natural, not forced"""

        return prompt

    def _parse_thread_response(self, response_text: str) -> Dict:
        """
        Parse Gemini response into thread data

        Args:
            response_text: Raw JSON response from Gemini

        Returns:
            Dict with thread data
        """
        try:
            # Clean JSON from markdown code blocks
            json_text = self._clean_json_response(response_text)

            # Parse JSON
            data = json.loads(json_text)

            # Validate required fields
            if 'tweets' not in data:
                raise ValueError("Response missing 'tweets' field")

            # Validate tweet character counts
            for tweet in data['tweets']:
                if len(tweet.get('text', '')) > 280:
                    logger.warning(f"Tweet {tweet.get('number')} exceeds 280 chars, truncating")
                    tweet['text'] = tweet['text'][:277] + "..."
                    tweet['char_count'] = 280

            return {
                'thread_title': data.get('thread_title', 'Twitter Thread'),
                'tweets': data.get('tweets', []),
                'hook_adaptation_explanation': data.get('hook_adaptation_explanation', ''),
                'key_insights': data.get('key_insights', []),
                'estimated_engagement_score': data.get('estimated_engagement_score', 0.0),
                'total_tweets': len(data.get('tweets', []))
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            raise ValueError(f"Invalid JSON response from AI: {e}")

        except Exception as e:
            logger.error(f"Error parsing thread response: {e}")
            raise

    def _format_thread_as_text(self, tweets: List[Dict]) -> str:
        """
        Format thread tweets as plain text

        Args:
            tweets: List of tweet dicts

        Returns:
            Formatted thread text
        """
        lines = []
        for tweet in tweets:
            number = tweet.get('number', 0)
            text = tweet.get('text', '')
            lines.append(f"Tweet {number}/{len(tweets)}:\n{text}\n")

        return "\n".join(lines)

    def format_as_longform(self, content: GeneratedContent) -> str:
        """
        Format thread as a single long-form post for LinkedIn/Instagram

        Args:
            content: GeneratedContent with thread

        Returns:
            Single cohesive post text
        """
        tweets = content.content_metadata.get('tweets', [])

        # Combine all tweets into paragraphs
        paragraphs = []
        for tweet in tweets:
            text = tweet.get('text', '').strip()
            paragraphs.append(text)

        # Join with line breaks
        longform = "\n\n".join(paragraphs)

        return longform

    def format_for_twitter(self, content: GeneratedContent) -> str:
        """
        Format thread for copying to Twitter

        Args:
            content: GeneratedContent with thread

        Returns:
            Ready-to-post thread text
        """
        tweets = content.content_metadata.get('tweets', [])

        lines = ["=== TWITTER THREAD ===\n"]
        for i, tweet in enumerate(tweets, 1):
            text = tweet.get('text', '')
            lines.append(f"{i}/ {text}\n")

        return "\n".join(lines)

    def export_to_typefully(self, content: GeneratedContent) -> Dict:
        """
        Export thread in Typefully-compatible format

        Typefully is a popular Twitter thread scheduling tool

        Args:
            content: GeneratedContent with thread

        Returns:
            Typefully-compatible JSON
        """
        tweets = content.content_metadata.get('tweets', [])

        return {
            "tweets": [t.get('text', '') for t in tweets],
            "metadata": {
                "title": content.content_title,
                "hook_type": content.hook_type,
                "source_tweet": content.source_tweet_text,
                "created_at": content.created_at.isoformat()
            }
        }
