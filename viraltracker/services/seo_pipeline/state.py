"""
SEO Pipeline State - Dataclass for pydantic-graph workflow.

This state is passed through all pipeline nodes, accumulating data
at each step. It enables:
- Clean data flow between nodes
- State persistence for resumable workflows (stored in seo_projects.workflow_data)
- Human checkpoint pausing and resumption
- Error tracking and recovery

Part of the SEO Content Pipeline.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from uuid import UUID
from enum import Enum


class SEOHumanCheckpoint(str, Enum):
    """Human checkpoints that pause the workflow for approval."""
    KEYWORD_SELECTION = "keyword_selection"
    OUTLINE_REVIEW = "outline_review"
    ARTICLE_REVIEW = "article_review"
    QA_APPROVAL = "qa_approval"


@dataclass
class SEOPipelineState:
    """
    State for SEO pipeline workflow.

    Tracks data through the entire pipeline from keyword discovery
    through article publishing and interlinking.

    The workflow has 4 human checkpoints that pause execution:
    1. keyword_selection - After discovery, user picks target keyword
    2. outline_review - After Phase A, user reviews outline
    3. article_review - After Phase B/C, user reviews article
    4. qa_approval - After QA, user approves for publishing

    Attributes:
        project_id: SEO project UUID
        brand_id: Brand UUID this project belongs to
        organization_id: Organization UUID for multi-tenancy

        # Keyword Discovery
        seed_keywords: Initial seed keywords for discovery
        discovered_keywords: List of discovered keywords with metadata
        selected_keyword_id: UUID of selected keyword

        # Competitor Analysis
        competitor_urls: URLs to analyze (manually provided)
        competitor_results: Analysis results per URL
        winning_formula: Aggregated competitor metrics

        # Content Generation
        author_id: UUID of the author for this article
        article_id: UUID of the article being generated
        phase_a_output: Research & outline output
        phase_b_output: Free-write output
        phase_c_output: SEO-optimized output

        # QA & Publishing
        qa_result: QA validation result
        published_url: URL after publishing

        # Tracking
        current_step: Current workflow step name
        current_checkpoint: Current human checkpoint (if paused)
        awaiting_human: Whether workflow is paused for human input
        human_input: Data provided by human at checkpoint
        error: Error message if workflow failed
    """

    # Required input
    project_id: UUID
    brand_id: UUID
    organization_id: UUID

    # Configuration
    generation_mode: str = "api"  # "api" or "cli"

    # =========================================================================
    # KEYWORD DISCOVERY
    # =========================================================================

    seed_keywords: List[str] = field(default_factory=list)
    min_word_count: int = 3
    max_word_count: int = 10
    discovered_keywords: List[Dict[str, Any]] = field(default_factory=list)
    selected_keyword_id: Optional[UUID] = None
    selected_keyword: Optional[str] = None

    # =========================================================================
    # COMPETITOR ANALYSIS
    # =========================================================================

    competitor_urls: List[str] = field(default_factory=list)
    competitor_results: List[Dict[str, Any]] = field(default_factory=list)
    winning_formula: Optional[Dict[str, Any]] = None

    # =========================================================================
    # CONTENT GENERATION
    # =========================================================================

    author_id: Optional[UUID] = None
    article_id: Optional[UUID] = None
    phase_a_output: Optional[str] = None
    phase_b_output: Optional[str] = None
    phase_c_output: Optional[str] = None

    # =========================================================================
    # IMAGE GENERATION
    # =========================================================================

    hero_image_url: Optional[str] = None
    image_results: Optional[Dict[str, Any]] = None

    # =========================================================================
    # QA & PUBLISHING
    # =========================================================================

    qa_result: Optional[Dict[str, Any]] = None
    published_url: Optional[str] = None
    cms_article_id: Optional[str] = None

    # =========================================================================
    # WORKFLOW TRACKING
    # =========================================================================

    current_step: str = "pending"
    current_checkpoint: Optional[SEOHumanCheckpoint] = None
    awaiting_human: bool = False
    human_input: Optional[Dict[str, Any]] = None

    # Error handling
    error: Optional[str] = None
    error_step: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Progress
    steps_completed: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def mark_step_complete(self, step_name: str) -> None:
        """Mark a step as completed."""
        if step_name not in self.steps_completed:
            self.steps_completed.append(step_name)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for JSON serialization."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, UUID):
                result[key] = str(value)
            elif isinstance(value, SEOHumanCheckpoint):
                result[key] = value.value
            elif isinstance(value, list):
                result[key] = [
                    str(v) if isinstance(v, UUID) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SEOPipelineState":
        """Create state from dictionary (for loading from database).

        Strips unknown keys for rollback safety (e.g., fields removed in a
        code rollback won't crash deserialization).
        """
        # Strip unknown keys
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        data = {k: v for k, v in data.items() if k in valid_fields}

        uuid_fields = {
            'project_id', 'brand_id', 'organization_id',
            'selected_keyword_id', 'author_id', 'article_id'
        }

        for field_name in uuid_fields:
            if field_name in data and data[field_name]:
                if isinstance(data[field_name], str):
                    data[field_name] = UUID(data[field_name])

        # Convert enum
        if 'current_checkpoint' in data and data['current_checkpoint']:
            if isinstance(data['current_checkpoint'], str):
                data['current_checkpoint'] = SEOHumanCheckpoint(data['current_checkpoint'])

        return cls(**data)
