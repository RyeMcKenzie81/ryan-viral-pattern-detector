"""
Content Generator Base Class

Base class for generating long-form content from viral hooks.

Provides common functionality for:
- Database operations (save/retrieve generated content)
- AI prompt building
- Cost tracking
- Error handling

Subclasses implement specific content types (threads, blogs, etc.)
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
import uuid

from google import genai
from google.genai import types

from ..core.config import Config


logger = logging.getLogger(__name__)


@dataclass
class GeneratedContent:
    """Result of content generation"""
    # Source
    source_tweet_id: Optional[str]
    source_tweet_text: str

    # Hook analysis
    hook_type: str
    emotional_trigger: str
    content_pattern: str
    hook_explanation: str
    adaptation_notes: str

    # Generated content
    content_type: str  # 'thread', 'blog', 'linkedin', 'newsletter'
    content_title: str
    content_body: str
    content_metadata: Dict  # Format-specific data

    # Project context
    project_id: Optional[str]
    project_context: Optional[str]

    # Tracking
    api_cost_usd: float
    model_used: str
    status: str  # 'pending', 'reviewed', 'published'

    # Timestamps
    created_at: datetime
    id: Optional[str] = None


class ContentGenerator:
    """
    Base class for content generators

    Provides common functionality for all content types.
    Subclasses implement generate() for specific formats.
    """

    def __init__(self,
                 model: str = "gemini-2.0-flash-exp",
                 db_connection = None):
        """
        Initialize content generator

        Args:
            model: Gemini model to use
            db_connection: Database connection for saving content
        """
        self.model_name = model
        self.db = db_connection

        # Configure Gemini
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.client = genai.Client(api_key=api_key)

        logger.info(f"ContentGenerator initialized with model: {model}")

    def generate(self,
                 hook_analysis: Dict,
                 project_context: Dict,
                 **kwargs) -> GeneratedContent:
        """
        Generate content from hook analysis

        Must be implemented by subclasses

        Args:
            hook_analysis: Hook analysis from Phase 2B
            project_context: Project info (name, description, audience, etc.)
            **kwargs: Additional generation parameters

        Returns:
            GeneratedContent with generated text and metadata
        """
        raise NotImplementedError("Subclasses must implement generate()")

    def save_to_db(self, content: GeneratedContent) -> str:
        """
        Save generated content to database

        Args:
            content: GeneratedContent to save

        Returns:
            ID of saved content
        """
        if not self.db:
            logger.warning("No database connection, skipping save")
            return None

        try:
            # Generate ID if not provided
            content_id = content.id or str(uuid.uuid4())

            # Prepare data for Supabase insert
            data = {
                'id': content_id,
                'project_id': content.project_id,
                'source_tweet_id': content.source_tweet_id,
                'hook_type': content.hook_type,
                'emotional_trigger': content.emotional_trigger,
                'content_pattern': content.content_pattern,
                'hook_explanation': content.hook_explanation,
                'content_type': content.content_type,
                'content_title': content.content_title,
                'content_body': content.content_body,
                'content_metadata': content.content_metadata,
                'adaptation_notes': content.adaptation_notes,
                'project_context': content.project_context,
                'api_cost_usd': content.api_cost_usd,
                'model_used': content.model_used,
                'status': content.status,
                'created_at': content.created_at.isoformat()
            }

            # Insert using Supabase client
            result = self.db.table('generated_content').insert(data).execute()

            if result.data:
                saved_id = result.data[0]['id']
                logger.info(f"Saved generated content to database: {saved_id}")
                return saved_id
            else:
                raise Exception("No data returned from insert")

        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            raise

    def load_from_db(self, content_id: str) -> Optional[GeneratedContent]:
        """
        Load generated content from database

        Args:
            content_id: UUID of content to load

        Returns:
            GeneratedContent or None if not found
        """
        if not self.db:
            logger.warning("No database connection")
            return None

        try:
            result = self.db.table('generated_content')\
                .select('*')\
                .eq('id', content_id)\
                .execute()

            if not result.data:
                return None

            row = result.data[0]
            return GeneratedContent(
                id=row['id'],
                project_id=row['project_id'],
                source_tweet_id=row.get('source_tweet_id'),
                hook_type=row['hook_type'],
                emotional_trigger=row['emotional_trigger'],
                content_pattern=row['content_pattern'],
                hook_explanation=row['hook_explanation'],
                content_type=row['content_type'],
                content_title=row['content_title'],
                content_body=row['content_body'],
                content_metadata=row['content_metadata'],
                adaptation_notes=row.get('adaptation_notes'),
                project_context=row.get('project_context'),
                api_cost_usd=float(row.get('api_cost_usd', 0)),
                model_used=row['model_used'],
                status=row['status'],
                created_at=datetime.fromisoformat(row['created_at']),
                source_tweet_text=""  # Not stored separately
            )

        except Exception as e:
            logger.error(f"Error loading from database: {e}")
            return None

    def get_project_content(self,
                           project_id: str,
                           content_type: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: int = 100) -> List[GeneratedContent]:
        """
        Get all generated content for a project

        Args:
            project_id: Project UUID
            content_type: Filter by content type (optional)
            status: Filter by status (optional)
            limit: Max results

        Returns:
            List of GeneratedContent
        """
        if not self.db:
            return []

        try:
            query = self.db.table('generated_content')\
                .select('*')\
                .eq('project_id', project_id)

            if content_type:
                query = query.eq('content_type', content_type)

            if status:
                query = query.eq('status', status)

            query = query.order('created_at', desc=True).limit(limit)

            result = query.execute()

            results = []
            for row in result.data:
                results.append(GeneratedContent(
                    id=row['id'],
                    project_id=row['project_id'],
                    source_tweet_id=row.get('source_tweet_id'),
                    hook_type=row['hook_type'],
                    emotional_trigger=row['emotional_trigger'],
                    content_pattern=row['content_pattern'],
                    hook_explanation=row['hook_explanation'],
                    content_type=row['content_type'],
                    content_title=row['content_title'],
                    content_body=row['content_body'],
                    content_metadata=row['content_metadata'],
                    adaptation_notes=row.get('adaptation_notes'),
                    project_context=row.get('project_context'),
                    api_cost_usd=float(row.get('api_cost_usd', 0)),
                    model_used=row['model_used'],
                    status=row['status'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    source_tweet_text=""
                ))

            return results

        except Exception as e:
            logger.error(f"Error getting project content: {e}")
            return []

    def _estimate_cost(self, prompt_tokens: int, output_tokens: int) -> float:
        """
        Estimate API cost in USD

        Gemini 2.0 Flash pricing (as of Oct 2024):
        - Input: $0.075 per 1M tokens
        - Output: $0.30 per 1M tokens

        Args:
            prompt_tokens: Estimated input tokens
            output_tokens: Estimated output tokens

        Returns:
            Cost in USD
        """
        input_cost = (prompt_tokens / 1_000_000) * 0.075
        output_cost = (output_tokens / 1_000_000) * 0.30

        return input_cost + output_cost

    def _clean_json_response(self, response_text: str) -> str:
        """
        Clean JSON from Gemini response (may have markdown code blocks)

        Args:
            response_text: Raw response from Gemini

        Returns:
            Cleaned JSON string
        """
        json_text = response_text.strip()

        # Remove markdown code blocks
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        elif json_text.startswith("```"):
            json_text = json_text[3:]

        if json_text.endswith("```"):
            json_text = json_text[:-3]

        return json_text.strip()
