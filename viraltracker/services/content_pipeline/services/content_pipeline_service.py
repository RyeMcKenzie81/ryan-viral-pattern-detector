"""
Content Pipeline Service - Main orchestration service for the content pipeline.

This service wraps all sub-services (topic, script, comic, etc.) and provides
convenience methods for project management and state persistence.

Part of the Trash Panda Content Pipeline.
"""

import logging
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
from datetime import datetime

logger = logging.getLogger(__name__)


class ContentPipelineService:
    """
    Main service for content pipeline orchestration.

    Provides:
    - Project creation and management
    - State persistence (load/save to database)
    - Access to sub-services (topic, script, comic, etc.)

    This service is added to AgentDependencies and accessed via
    ctx.deps.content_pipeline in pipeline nodes.
    """

    def __init__(
        self,
        supabase_client: Optional[Any] = None,
        docs_service: Optional[Any] = None,
        gemini_service: Optional[Any] = None,
        topic_service: Optional["TopicDiscoveryService"] = None,
        script_service: Optional["ScriptGenerationService"] = None,
        asset_service: Optional["AssetManagementService"] = None
    ):
        """
        Initialize the ContentPipelineService.

        Args:
            supabase_client: Supabase client for database operations
            docs_service: DocService for knowledge base queries
            gemini_service: GeminiService for AI-powered operations
            topic_service: TopicDiscoveryService instance (created if not provided)
            script_service: ScriptGenerationService instance (created if not provided)
            asset_service: AssetManagementService instance (created if not provided)
        """
        self.supabase = supabase_client
        self.docs = docs_service
        self.gemini = gemini_service

        # Import here to avoid circular imports
        from .topic_service import TopicDiscoveryService
        from .script_service import ScriptGenerationService
        from .asset_service import AssetManagementService

        # Initialize sub-services
        self.topic_service = topic_service or TopicDiscoveryService(
            supabase_client=supabase_client,
            docs_service=docs_service
        )

        self.script_service = script_service or ScriptGenerationService(
            supabase_client=supabase_client,
            docs_service=docs_service
        )

        self.asset_service = asset_service or AssetManagementService(
            supabase_client=supabase_client,
            gemini_service=gemini_service
        )

        # Placeholder for future services
        self.comic_service = None
        self.seo_service = None
        self.thumbnail_service = None

    # =========================================================================
    # PROJECT MANAGEMENT
    # =========================================================================

    async def create_project(
        self,
        brand_id: UUID,
        workflow_path: str = "both"
    ) -> Dict[str, Any]:
        """
        Create a new content pipeline project.

        Args:
            brand_id: Brand UUID this project belongs to
            workflow_path: Which path(s) to follow ("video_only", "comic_only", "both")

        Returns:
            Created project dictionary with id
        """
        project_id = uuid4()

        project_data = {
            "id": str(project_id),
            "brand_id": str(brand_id),
            "workflow_state": "pending",
            "workflow_data": {
                "workflow_path": workflow_path,
                "created_at": datetime.utcnow().isoformat()
            },
            "created_at": datetime.utcnow().isoformat()
        }

        if self.supabase:
            try:
                result = self.supabase.table("content_projects").insert(
                    project_data
                ).execute()

                if result.data:
                    logger.info(f"Created content project {project_id}")
                    return result.data[0]

            except Exception as e:
                logger.error(f"Failed to create project in database: {e}")
                # Fall through to return local data

        logger.info(f"Created content project {project_id} (not persisted)")
        return project_data

    async def get_project(self, project_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get a project by ID.

        Args:
            project_id: Content project UUID

        Returns:
            Project dictionary or None if not found
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return None

        try:
            result = self.supabase.table("content_projects").select("*").eq(
                "id", str(project_id)
            ).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to fetch project: {e}")
            return None

    async def list_projects(
        self,
        brand_id: Optional[UUID] = None,
        workflow_state: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List content projects with optional filters.

        Args:
            brand_id: Filter by brand UUID
            workflow_state: Filter by workflow state
            limit: Maximum projects to return

        Returns:
            List of project dictionaries
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return []

        try:
            query = self.supabase.table("content_projects").select("*")

            if brand_id:
                query = query.eq("brand_id", str(brand_id))

            if workflow_state:
                query = query.eq("workflow_state", workflow_state)

            result = query.order("created_at", desc=True).limit(limit).execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to list projects: {e}")
            return []

    # =========================================================================
    # STATE PERSISTENCE
    # =========================================================================

    async def load_project_state(self, project_id: UUID) -> Dict[str, Any]:
        """
        Load workflow state from database.

        Args:
            project_id: Content project UUID

        Returns:
            State dictionary (from workflow_data column)
        """
        project = await self.get_project(project_id)

        if not project:
            raise ValueError(f"Project {project_id} not found")

        state_data = project.get("workflow_data", {})
        state_data["project_id"] = project_id
        state_data["brand_id"] = UUID(project.get("brand_id"))

        return state_data

    async def save_project_state(
        self,
        project_id: UUID,
        state_dict: Dict[str, Any]
    ) -> None:
        """
        Save workflow state to database.

        Args:
            project_id: Content project UUID
            state_dict: State dictionary to persist
        """
        if not self.supabase:
            logger.warning("Supabase not configured - state not saved")
            return

        try:
            # Extract workflow_state for quick filtering
            workflow_state = state_dict.get("current_step", "unknown")

            self.supabase.table("content_projects").update({
                "workflow_state": workflow_state,
                "workflow_data": state_dict,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", str(project_id)).execute()

            logger.debug(f"Saved state for project {project_id}")

        except Exception as e:
            logger.error(f"Failed to save project state: {e}")
            raise

    async def update_workflow_state(
        self,
        project_id: UUID,
        new_state: str
    ) -> None:
        """
        Update just the workflow state (for quick status updates).

        Args:
            project_id: Content project UUID
            new_state: New workflow state string
        """
        if not self.supabase:
            return

        try:
            self.supabase.table("content_projects").update({
                "workflow_state": new_state,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", str(project_id)).execute()

        except Exception as e:
            logger.error(f"Failed to update workflow state: {e}")

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    async def get_project_summary(self, project_id: UUID) -> Dict[str, Any]:
        """
        Get a summary of project status including all related data.

        Args:
            project_id: Content project UUID

        Returns:
            Summary dictionary with project, topics, scripts, etc.
        """
        project = await self.get_project(project_id)
        if not project:
            return {"error": "Project not found"}

        summary = {
            "project": project,
            "topics": [],
            "scripts": [],
            "comics": []
        }

        if self.supabase:
            # Fetch related data
            try:
                topics = self.supabase.table("topic_suggestions").select("*").eq(
                    "project_id", str(project_id)
                ).order("score", desc=True).execute()
                summary["topics"] = topics.data or []

                scripts = self.supabase.table("script_versions").select("*").eq(
                    "project_id", str(project_id)
                ).order("version_number", desc=True).execute()
                summary["scripts"] = scripts.data or []

                comics = self.supabase.table("comic_versions").select("*").eq(
                    "project_id", str(project_id)
                ).order("version_number", desc=True).execute()
                summary["comics"] = comics.data or []

            except Exception as e:
                logger.error(f"Failed to fetch project summary data: {e}")

        return summary

    async def get_projects_at_checkpoint(
        self,
        checkpoint: str,
        brand_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all projects waiting at a specific checkpoint.

        Args:
            checkpoint: Checkpoint name (e.g., "topic_selection")
            brand_id: Optional filter by brand

        Returns:
            List of projects awaiting human input at this checkpoint
        """
        # Map checkpoint names to workflow states
        checkpoint_states = {
            "topic_selection": "topic_selection",
            "script_approval": "script_approval",
            "audio_production": "audio_production",
            "asset_review": "asset_review",
            "metadata_selection": "metadata_selection",
            "comic_script_approval": "comic_script_approval",
            "comic_image_review": "comic_image_review",
            "comic_video": "comic_video",
        }

        workflow_state = checkpoint_states.get(checkpoint)
        if not workflow_state:
            return []

        return await self.list_projects(
            brand_id=brand_id,
            workflow_state=workflow_state
        )
