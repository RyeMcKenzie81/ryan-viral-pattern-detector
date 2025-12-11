"""
Topic Discovery Service - Business logic for topic discovery and evaluation.

Uses ChatGPT 5.1 (or configured model) with extended thinking to:
1. Discover trending financial topics relevant to Trash Panda Economics
2. Evaluate and score topics based on brand bible alignment

Part of the Trash Panda Content Pipeline (MVP 1).
"""

import os
import logging
import json
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

from openai import OpenAI

logger = logging.getLogger(__name__)


class TopicDiscoveryService:
    """
    Service for discovering and evaluating content topics.

    Uses OpenAI's chat completions API with extended thinking
    to generate and rank topic ideas for Trash Panda Economics.

    The service queries the knowledge base for brand context
    (bible, past performance) and uses that to inform topic
    generation and evaluation.
    """

    # Default model - can be overridden
    # Note: "gpt-4o" is used as placeholder; update to actual ChatGPT 5.1 model ID when available
    DEFAULT_MODEL = "gpt-4o"

    # Topic discovery prompt template
    DISCOVERY_PROMPT = """You are a content strategist for "Trash Panda Economics" - a YouTube channel that explains complex financial concepts using raccoon characters in a humorous, accessible way.

Based on the brand context provided, generate {num_topics} unique video topic ideas that would resonate with the audience.

BRAND CONTEXT:
{bible_context}

{focus_areas_section}

For each topic, provide:
1. title: A compelling, clickable video title (include raccoon reference if natural)
2. description: 2-3 sentence summary of what the video would cover
3. hook_options: 3 different hook approaches (curiosity, fear, humor)
4. target_emotion: Primary emotional appeal (curiosity, fear, greed, humor, outrage)
5. difficulty: How complex is this topic (beginner, intermediate, advanced)
6. timeliness: Is this evergreen or trending now? (evergreen, trending, news-driven)

Return as JSON array:
[
  {{
    "title": "...",
    "description": "...",
    "hook_options": ["...", "...", "..."],
    "target_emotion": "...",
    "difficulty": "...",
    "timeliness": "..."
  }}
]

Focus on topics that:
- Are relevant to current financial news or timeless money concepts
- Can be explained with raccoon analogies (trash, dumpster diving, nocturnal behavior)
- Have viral potential through relatability or shock value
- Haven't been overdone by competitors"""

    # Topic evaluation prompt template
    EVALUATION_PROMPT = """You are evaluating video topics for "Trash Panda Economics" - a raccoon-themed financial education YouTube channel.

Rate each topic on a scale of 0-100 based on:
- Brand fit (40%): How well does this match the Trash Panda voice and style?
- Viral potential (30%): How likely is this to get views and engagement?
- Educational value (20%): Does this teach something meaningful?
- Production feasibility (10%): Can this be produced with existing assets?

BRAND CONTEXT:
{bible_context}

TOPICS TO EVALUATE:
{topics_json}

For each topic, provide:
1. score: Overall score 0-100
2. reasoning: 2-3 sentences explaining the score
3. improvement_suggestions: How could this topic be made better?

Return as JSON array matching the input order:
[
  {{
    "score": 85,
    "reasoning": "...",
    "improvement_suggestions": "..."
  }}
]"""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: Optional[str] = None,
        supabase_client: Optional[Any] = None,
        docs_service: Optional[Any] = None
    ):
        """
        Initialize the TopicDiscoveryService.

        Args:
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use for generation (defaults to gpt-4o)
            supabase_client: Supabase client for database operations
            docs_service: DocService for knowledge base queries
        """
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        if not api_key:
            logger.warning("OPENAI_API_KEY not set - topic discovery will fail")
            self.openai = None
        else:
            self.openai = OpenAI(api_key=api_key)

        self.model = model or self.DEFAULT_MODEL
        self.supabase = supabase_client
        self.docs = docs_service

    def _ensure_openai(self) -> None:
        """Raise error if OpenAI client not configured."""
        if not self.openai:
            raise ValueError(
                "OpenAI client not configured. Set OPENAI_API_KEY environment variable."
            )

    async def get_bible_context(self, brand_id: UUID) -> str:
        """
        Fetch brand bible context from knowledge base.

        Args:
            brand_id: Brand UUID to get context for

        Returns:
            Combined context string from bible documents
        """
        if not self.docs:
            logger.warning("DocService not configured - using minimal context")
            return self._get_default_context()

        try:
            # Query knowledge base for brand bible documents
            # Use tags filter to find trash-panda-bible documents
            results = self.docs.search(
                query="Trash Panda Economics brand voice style guide characters hook formulas script rules",
                limit=10,  # Get more chunks for comprehensive context
                tags=["trash-panda-bible"]
            )

            if not results:
                logger.warning("No bible documents found - using default context")
                return self._get_default_context()

            logger.info(f"Found {len(results)} bible chunks (top similarity: {results[0].similarity:.0%})")

            # Combine relevant chunks
            context_parts = []
            for result in results:
                context_parts.append(result.chunk_content)

            return "\n\n---\n\n".join(context_parts)

        except Exception as e:
            logger.error(f"Failed to fetch bible context: {e}")
            return self._get_default_context()

    def _get_default_context(self) -> str:
        """
        Return default context when bible is not available.

        This is a minimal fallback for testing.
        """
        return """Trash Panda Economics is a YouTube channel that explains financial concepts using raccoon characters.

Key characters:
- Every-Coon: Main narrator, curious and confused raccoon learning about money
- The Fed: Monotone, bureaucratic raccoon representing the Federal Reserve
- Whale: Big money raccoon, confident and slightly menacing
- Boomer: Old raccoon with nostalgic views on money
- Wojak: Panicked raccoon always losing money
- Chad: Overconfident crypto bro raccoon

Voice style:
- Simple, deadpan humor
- "Caveman" speech patterns for Every-Coon
- Financial jargon explained through trash/dumpster analogies
- Self-deprecating humor about raccoon life

Target audience:
- Young adults (18-35) interested in personal finance
- Crypto/investing curious but not experts
- Appreciate meme culture and internet humor"""

    async def discover_topics(
        self,
        brand_id: UUID,
        num_topics: int = 10,
        focus_areas: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Discover trending topics using ChatGPT extended thinking.

        Args:
            brand_id: Brand UUID for context
            num_topics: Number of topics to generate (default 10)
            focus_areas: Optional focus areas to constrain generation

        Returns:
            List of topic dictionaries with title, description, hooks, etc.
        """
        self._ensure_openai()

        logger.info(f"Discovering {num_topics} topics for brand {brand_id}")

        # Get brand context
        bible_context = await self.get_bible_context(brand_id)

        # Build focus areas section
        focus_areas_section = ""
        if focus_areas:
            focus_areas_section = f"FOCUS AREAS (prioritize these themes):\n- " + "\n- ".join(focus_areas)

        # Build prompt
        prompt = self.DISCOVERY_PROMPT.format(
            num_topics=num_topics,
            bible_context=bible_context,
            focus_areas_section=focus_areas_section
        )

        try:
            # Call OpenAI
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a creative content strategist. Return valid JSON only, no markdown formatting."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,  # Higher temperature for creative diversity
                max_tokens=4000
            )

            # Parse response
            content = response.choices[0].message.content
            topics = self._parse_json_response(content)

            # Add IDs and metadata
            for topic in topics:
                topic['id'] = str(uuid4())
                topic['created_at'] = datetime.utcnow().isoformat()
                topic['brand_id'] = str(brand_id)

            logger.info(f"Generated {len(topics)} topics")
            return topics

        except Exception as e:
            logger.error(f"Topic discovery failed: {e}")
            raise

    async def evaluate_topics(
        self,
        topics: List[Dict[str, Any]],
        brand_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Evaluate and score topics.

        Args:
            topics: List of topic dictionaries from discover_topics
            brand_id: Brand UUID for context

        Returns:
            Same topics with added score, reasoning, and improvement_suggestions
        """
        self._ensure_openai()

        if not topics:
            return []

        logger.info(f"Evaluating {len(topics)} topics")

        # Get brand context
        bible_context = await self.get_bible_context(brand_id)

        # Build topics JSON for evaluation
        topics_for_eval = [
            {
                "title": t.get("title"),
                "description": t.get("description"),
                "hook_options": t.get("hook_options"),
                "target_emotion": t.get("target_emotion"),
                "difficulty": t.get("difficulty"),
                "timeliness": t.get("timeliness")
            }
            for t in topics
        ]

        # Build prompt
        prompt = self.EVALUATION_PROMPT.format(
            bible_context=bible_context,
            topics_json=json.dumps(topics_for_eval, indent=2)
        )

        try:
            # Call OpenAI
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a content strategist evaluating video topics. Return valid JSON only, no markdown formatting."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for consistent scoring
                max_tokens=3000
            )

            # Parse response
            content = response.choices[0].message.content
            evaluations = self._parse_json_response(content)

            # Merge evaluations with original topics
            for i, topic in enumerate(topics):
                if i < len(evaluations):
                    eval_data = evaluations[i]
                    topic['score'] = eval_data.get('score', 50)
                    topic['reasoning'] = eval_data.get('reasoning', '')
                    topic['improvement_suggestions'] = eval_data.get('improvement_suggestions', '')
                else:
                    # Fallback if evaluation is missing
                    topic['score'] = 50
                    topic['reasoning'] = 'Evaluation not available'
                    topic['improvement_suggestions'] = ''

            logger.info(f"Evaluated {len(topics)} topics")
            return topics

        except Exception as e:
            logger.error(f"Topic evaluation failed: {e}")
            # Return topics with default scores
            for topic in topics:
                topic['score'] = 50
                topic['reasoning'] = f'Evaluation failed: {e}'
                topic['improvement_suggestions'] = ''
            return topics

    def _parse_json_response(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse JSON from LLM response, handling common formatting issues.

        Args:
            content: Raw response content

        Returns:
            Parsed JSON as list of dicts
        """
        # Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            # Remove first and last lines (```json and ```)
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Raw content: {content[:500]}")
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")

    async def save_topics_to_db(
        self,
        project_id: UUID,
        topics: List[Dict[str, Any]]
    ) -> List[UUID]:
        """
        Save discovered topics to the database.

        Args:
            project_id: Content project UUID
            topics: List of topic dictionaries

        Returns:
            List of created topic_suggestion UUIDs
        """
        if not self.supabase:
            logger.warning("Supabase not configured - topics not saved")
            return [UUID(t['id']) for t in topics]

        saved_ids = []
        for topic in topics:
            try:
                result = self.supabase.table("topic_suggestions").insert({
                    "project_id": str(project_id),
                    "title": topic.get("title"),
                    "description": topic.get("description"),
                    "score": topic.get("score"),
                    "reasoning": topic.get("reasoning"),
                    "hook_options": topic.get("hook_options"),
                    "quick_approve_eligible": topic.get("quick_approve_eligible", False)
                }).execute()

                if result.data:
                    saved_ids.append(UUID(result.data[0]["id"]))

            except Exception as e:
                logger.error(f"Failed to save topic '{topic.get('title')}': {e}")

        logger.info(f"Saved {len(saved_ids)} topics to database")
        return saved_ids

    async def get_topics_for_project(
        self,
        project_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all topics for a project from database.

        Args:
            project_id: Content project UUID

        Returns:
            List of topic dictionaries
        """
        if not self.supabase:
            logger.warning("Supabase not configured - returning empty list")
            return []

        try:
            result = self.supabase.table("topic_suggestions").select("*").eq(
                "project_id", str(project_id)
            ).order("score", desc=True).execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to fetch topics: {e}")
            return []

    async def select_topic(
        self,
        topic_id: UUID,
        project_id: UUID
    ) -> Dict[str, Any]:
        """
        Mark a topic as selected for the project.

        Args:
            topic_id: Topic suggestion UUID to select
            project_id: Content project UUID

        Returns:
            Updated topic dictionary
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return {"id": str(topic_id), "is_selected": True}

        try:
            # Deselect all topics for this project
            self.supabase.table("topic_suggestions").update({
                "is_selected": False
            }).eq("project_id", str(project_id)).execute()

            # Select the chosen topic
            result = self.supabase.table("topic_suggestions").update({
                "is_selected": True
            }).eq("id", str(topic_id)).execute()

            # Update project with selected topic
            if result.data:
                topic = result.data[0]
                self.supabase.table("content_projects").update({
                    "topic_title": topic.get("title"),
                    "topic_description": topic.get("description"),
                    "topic_score": topic.get("score"),
                    "topic_reasoning": topic.get("reasoning"),
                    "hook_options": topic.get("hook_options")
                }).eq("id", str(project_id)).execute()

                return topic

            return {"id": str(topic_id), "is_selected": True}

        except Exception as e:
            logger.error(f"Failed to select topic: {e}")
            raise
