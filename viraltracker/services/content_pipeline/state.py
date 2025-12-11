"""
Content Pipeline State - Dataclass for pydantic-graph workflow.

This state is passed through all pipeline nodes, accumulating data
at each step. It enables:
- Clean data flow between nodes
- State persistence for resumable workflows (stored in content_projects.workflow_data)
- Human checkpoint pausing and resumption
- Error tracking and recovery

Part of the Trash Panda Content Pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from uuid import UUID
from enum import Enum


class WorkflowPath(str, Enum):
    """Which path(s) the project is taking after script approval."""
    VIDEO_ONLY = "video_only"
    COMIC_ONLY = "comic_only"
    BOTH = "both"


class HumanCheckpoint(str, Enum):
    """Human checkpoints that pause the workflow for approval."""
    TOPIC_SELECTION = "topic_selection"
    SCRIPT_APPROVAL = "script_approval"
    AUDIO_PRODUCTION = "audio_production"
    ASSET_REVIEW = "asset_review"
    METADATA_SELECTION = "metadata_selection"
    THUMBNAIL_SELECTION = "thumbnail_selection"
    COMIC_SCRIPT_APPROVAL = "comic_script_approval"
    COMIC_IMAGE_REVIEW = "comic_image_review"
    COMIC_VIDEO = "comic_video"
    COMIC_METADATA_SELECTION = "comic_metadata_selection"
    COMIC_THUMBNAIL_SELECTION = "comic_thumbnail_selection"


@dataclass
class ContentPipelineState:
    """
    State for content pipeline workflow.

    Tracks data through the entire pipeline from topic discovery
    through editor handoff (video path) or comic video (comic path).

    The workflow has 9 human checkpoints that pause execution for
    approval. Quick Approve can auto-advance if AI evaluation
    exceeds configured thresholds.

    Attributes:
        brand_id: Brand UUID this project belongs to
        project_id: Content project UUID (from database)
        workflow_path: Which path(s) to follow after script approval
        quick_approve_enabled: Whether to auto-approve high-scoring items

        # Topic Discovery (Steps 1-3)
        topic_batch_size: Number of topics to discover (default 10)
        topic_focus_areas: Optional focus areas for discovery
        topic_suggestions: List of discovered topics with scores
        selected_topic_id: UUID of selected topic

        # Script Generation (Steps 4-6)
        script_version_ids: List of script version UUIDs
        current_script_version_id: Currently active script version
        bible_checklist_results: Latest checklist review results

        # Video Path (Steps 7-15)
        els_version_id: Current ELS version UUID
        audio_session_id: Audio production session UUID
        asset_requirements: List of required assets
        asset_generation_results: Generated asset URLs
        video_metadata_id: Project metadata UUID for video

        # Comic Path (Steps 16-29)
        comic_config: Panel count, platform, grid layout
        comic_version_ids: List of comic version UUIDs
        current_comic_version_id: Currently active comic version
        comic_image_url: Generated comic image URL
        comic_els_version_id: Comic-specific ELS version
        comic_metadata_id: Project metadata UUID for comic

        # Tracking
        current_step: Current workflow step name
        current_checkpoint: Current human checkpoint (if paused)
        awaiting_human: Whether workflow is paused for human input
        human_input: Data provided by human at checkpoint
        error: Error message if workflow failed
        retry_count: Number of retries for current step
    """

    # Required input
    brand_id: UUID

    # Set after project creation in database
    project_id: Optional[UUID] = None

    # Configuration
    workflow_path: WorkflowPath = WorkflowPath.BOTH
    quick_approve_enabled: bool = True

    # Quick Approve thresholds (can be customized)
    topic_score_threshold: int = 90
    checklist_pass_threshold: float = 100.0  # Percentage
    metadata_score_threshold: int = 90
    comic_script_score_threshold: int = 85
    comic_image_score_threshold: int = 90

    # =========================================================================
    # TOPIC DISCOVERY (Steps 1-3)
    # =========================================================================

    topic_batch_size: int = 10
    topic_focus_areas: Optional[List[str]] = None
    topic_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    selected_topic_id: Optional[UUID] = None
    selected_topic: Optional[Dict[str, Any]] = None

    # =========================================================================
    # SCRIPT GENERATION (Steps 4-6)
    # =========================================================================

    script_version_ids: List[UUID] = field(default_factory=list)
    current_script_version_id: Optional[UUID] = None
    bible_checklist_results: Optional[Dict[str, Any]] = None
    script_revision_notes: Optional[str] = None

    # =========================================================================
    # VIDEO PATH (Steps 7-15)
    # =========================================================================

    # ELS & Audio (Steps 7-8)
    els_version_id: Optional[UUID] = None
    audio_session_id: Optional[UUID] = None

    # Assets (Steps 9-12)
    asset_requirements: List[Dict[str, Any]] = field(default_factory=list)
    matched_asset_ids: List[UUID] = field(default_factory=list)
    missing_asset_requirements: List[Dict[str, Any]] = field(default_factory=list)
    generated_asset_urls: List[str] = field(default_factory=list)

    # SEO & Thumbnails (Steps 13-15)
    video_metadata_id: Optional[UUID] = None
    video_title_options: List[Dict[str, Any]] = field(default_factory=list)
    selected_video_title: Optional[str] = None
    video_thumbnail_urls: List[str] = field(default_factory=list)
    selected_video_thumbnail: Optional[str] = None

    # Editor Handoff
    handoff_slug: Optional[str] = None
    handoff_created_at: Optional[str] = None

    # =========================================================================
    # COMIC PATH (Steps 16-29)
    # =========================================================================

    # Configuration (Step 16)
    comic_config: Dict[str, Any] = field(default_factory=lambda: {
        "panel_count": 6,
        "target_platform": "instagram",
        "grid_layout": "2x3"
    })

    # Comic Script (Steps 16-18)
    comic_version_ids: List[UUID] = field(default_factory=list)
    current_comic_version_id: Optional[UUID] = None
    comic_script_evaluation: Optional[Dict[str, Any]] = None
    comic_revision_notes: Optional[str] = None

    # Comic Image (Steps 19-21)
    comic_image_url: Optional[str] = None
    comic_image_prompt: Optional[str] = None
    comic_image_evaluation: Optional[Dict[str, Any]] = None
    comic_image_retry_count: int = 0

    # Comic Audio (Steps 22-23)
    comic_els_version_id: Optional[UUID] = None
    comic_audio_verification: Optional[Dict[str, Any]] = None

    # Comic Video (Steps 24-25)
    comic_json: Optional[Dict[str, Any]] = None

    # Comic SEO & Thumbnails (Steps 26-29)
    comic_metadata_id: Optional[UUID] = None
    comic_title_options: List[Dict[str, Any]] = field(default_factory=list)
    selected_comic_title: Optional[str] = None
    comic_thumbnail_urls: List[str] = field(default_factory=list)
    selected_comic_thumbnail: Optional[str] = None

    # =========================================================================
    # WORKFLOW TRACKING
    # =========================================================================

    current_step: str = "pending"
    current_checkpoint: Optional[HumanCheckpoint] = None
    awaiting_human: bool = False
    human_input: Optional[Dict[str, Any]] = None

    # Error handling
    error: Optional[str] = None
    error_step: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Progress metrics
    steps_completed: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def mark_step_complete(self, step_name: str) -> None:
        """Mark a step as completed and update current step."""
        if step_name not in self.steps_completed:
            self.steps_completed.append(step_name)

    def is_quick_approve_eligible(self, checkpoint: HumanCheckpoint, score: float) -> bool:
        """Check if a checkpoint can be auto-approved based on score."""
        if not self.quick_approve_enabled:
            return False

        thresholds = {
            HumanCheckpoint.TOPIC_SELECTION: self.topic_score_threshold,
            HumanCheckpoint.SCRIPT_APPROVAL: self.checklist_pass_threshold,
            HumanCheckpoint.METADATA_SELECTION: self.metadata_score_threshold,
            HumanCheckpoint.COMIC_SCRIPT_APPROVAL: self.comic_script_score_threshold,
            HumanCheckpoint.COMIC_IMAGE_REVIEW: self.comic_image_score_threshold,
            HumanCheckpoint.COMIC_METADATA_SELECTION: self.metadata_score_threshold,
        }

        threshold = thresholds.get(checkpoint)
        if threshold is None:
            return False

        return score >= threshold

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for JSON serialization."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, UUID):
                result[key] = str(value)
            elif isinstance(value, (WorkflowPath, HumanCheckpoint)):
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
    def from_dict(cls, data: Dict[str, Any]) -> "ContentPipelineState":
        """Create state from dictionary (for loading from database)."""
        # Convert string UUIDs back to UUID objects
        uuid_fields = {
            'brand_id', 'project_id', 'selected_topic_id',
            'current_script_version_id', 'els_version_id', 'audio_session_id',
            'video_metadata_id', 'current_comic_version_id',
            'comic_els_version_id', 'comic_metadata_id'
        }

        for field_name in uuid_fields:
            if field_name in data and data[field_name]:
                if isinstance(data[field_name], str):
                    data[field_name] = UUID(data[field_name])

        # Convert list UUID fields
        list_uuid_fields = {
            'script_version_ids', 'matched_asset_ids', 'comic_version_ids'
        }

        for field_name in list_uuid_fields:
            if field_name in data and data[field_name]:
                data[field_name] = [
                    UUID(v) if isinstance(v, str) else v
                    for v in data[field_name]
                ]

        # Convert enums
        if 'workflow_path' in data and isinstance(data['workflow_path'], str):
            data['workflow_path'] = WorkflowPath(data['workflow_path'])

        if 'current_checkpoint' in data and data['current_checkpoint']:
            if isinstance(data['current_checkpoint'], str):
                data['current_checkpoint'] = HumanCheckpoint(data['current_checkpoint'])

        return cls(**data)
