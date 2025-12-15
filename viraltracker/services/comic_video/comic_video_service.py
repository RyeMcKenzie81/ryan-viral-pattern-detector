"""
Comic Video Service

Main orchestration service for comic panel video generation.
Coordinates audio generation, director instructions, and video rendering.

This is the primary entry point for the comic video workflow.
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import httpx
import tempfile

from .models import (
    ProjectStatus,
    ComicLayout,
    PanelAudio,
    PanelInstruction,
    ComicVideoProject,
    AspectRatio,
)
from .comic_audio_service import ComicAudioService
from .comic_director_service import ComicDirectorService
from .comic_render_service import ComicRenderService
from ..elevenlabs_service import ElevenLabsService
from ..ffmpeg_service import FFmpegService
from ...core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ComicVideoService:
    """
    Main service for comic video workflow orchestration.

    Manages project lifecycle:
    1. Project creation (upload comic grid + JSON)
    2. Layout parsing
    3. Audio generation for all panels
    4. Director instruction generation
    5. Panel preview rendering
    6. Final video rendering
    """

    STORAGE_BUCKET = "comic-video"

    def __init__(
        self,
        audio_service: Optional[ComicAudioService] = None,
        director_service: Optional[ComicDirectorService] = None,
        render_service: Optional[ComicRenderService] = None
    ):
        """
        Initialize Comic Video Service.

        Args:
            audio_service: Audio generation service
            director_service: Cinematography instruction service
            render_service: Video rendering service
        """
        self.supabase = get_supabase_client()

        # Initialize sub-services
        self.audio = audio_service or ComicAudioService()
        self.director = director_service or ComicDirectorService()
        self.render = render_service or ComicRenderService()

        # Local storage for downloaded files
        self.cache_dir = Path("comic_video_cache")
        self.cache_dir.mkdir(exist_ok=True)

        logger.info("ComicVideoService initialized")

    # =========================================================================
    # Project CRUD
    # =========================================================================

    async def create_project(
        self,
        title: str,
        comic_grid_url: str,
        comic_json: Dict[str, Any]
    ) -> ComicVideoProject:
        """
        Create a new comic video project.

        Args:
            title: Project title
            comic_grid_url: URL to uploaded comic grid image
            comic_json: Comic JSON with panel metadata

        Returns:
            New ComicVideoProject
        """
        project_id = str(uuid.uuid4())
        slug = self._generate_slug(title)
        now = datetime.utcnow()

        # Insert into database
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_video_projects").insert({
                "id": project_id,
                "title": title,
                "slug": slug,
                "comic_grid_url": comic_grid_url,
                "comic_json": comic_json,
                "status": ProjectStatus.DRAFT.value,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat()
            }).execute()
        )

        logger.info(f"Created project: {project_id} ({title})")

        return ComicVideoProject(
            project_id=project_id,
            title=title,
            comic_grid_url=comic_grid_url,
            comic_json=comic_json,
            status=ProjectStatus.DRAFT,
            created_at=now,
            updated_at=now
        )

    async def get_project(self, project_id: str) -> Optional[ComicVideoProject]:
        """
        Get project by ID.

        Args:
            project_id: Project UUID

        Returns:
            ComicVideoProject or None if not found
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_video_projects")
                .select("*")
                .eq("id", project_id)
                .maybe_single()
                .execute()
        )

        if not result or not result.data:
            return None

        return self._row_to_project(result.data)

    async def list_projects(
        self,
        status: Optional[ProjectStatus] = None,
        limit: int = 20
    ) -> List[ComicVideoProject]:
        """
        List projects with optional status filter.

        Args:
            status: Filter by status
            limit: Max results

        Returns:
            List of projects
        """
        query = self.supabase.table("comic_video_projects").select("*")

        if status:
            query = query.eq("status", status.value)

        query = query.order("created_at", desc=True).limit(limit)

        result = await asyncio.to_thread(lambda: query.execute())

        if not result or not result.data:
            return []

        return [self._row_to_project(row) for row in result.data]

    async def update_status(
        self,
        project_id: str,
        status: ProjectStatus,
        error_message: Optional[str] = None
    ) -> None:
        """Update project status."""
        update_data = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat()
        }

        if error_message:
            update_data["error_message"] = error_message

        await asyncio.to_thread(
            lambda: self.supabase.table("comic_video_projects")
                .update(update_data)
                .eq("id", project_id)
                .execute()
        )

    async def delete_project(self, project_id: str) -> None:
        """Delete project and all associated data."""
        # Cascade delete handles audio, instructions, render jobs
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_video_projects")
                .delete()
                .eq("id", project_id)
                .execute()
        )
        logger.info(f"Deleted project: {project_id}")

    # =========================================================================
    # Layout Parsing
    # =========================================================================

    async def parse_layout(self, project_id: str) -> ComicLayout:
        """
        Parse layout from project's comic JSON.

        Args:
            project_id: Project UUID

        Returns:
            Parsed ComicLayout
        """
        await self.update_status(project_id, ProjectStatus.PARSING)

        try:
            project = await self.get_project(project_id)
            if not project:
                raise ValueError(f"Project not found: {project_id}")

            layout = self.director.parse_layout_from_json(project.comic_json)

            # Save layout to project
            await asyncio.to_thread(
                lambda: self.supabase.table("comic_video_projects")
                    .update({
                        "layout": layout.model_dump(mode="json"),
                        "updated_at": datetime.utcnow().isoformat()
                    })
                    .eq("id", project_id)
                    .execute()
            )

            await self.update_status(project_id, ProjectStatus.DRAFT)

            return layout

        except Exception as e:
            await self.update_status(project_id, ProjectStatus.FAILED, str(e))
            raise

    # =========================================================================
    # Audio Generation
    # =========================================================================

    async def generate_all_audio(
        self,
        project_id: str,
        voice_id: Optional[str] = None,
        voice_name: Optional[str] = None
    ) -> List[PanelAudio]:
        """
        Generate audio for all panels in project.

        Args:
            project_id: Project UUID
            voice_id: ElevenLabs voice ID
            voice_name: Voice display name

        Returns:
            List of generated PanelAudio
        """
        await self.update_status(project_id, ProjectStatus.AUDIO_GENERATING)

        try:
            project = await self.get_project(project_id)
            if not project:
                raise ValueError(f"Project not found: {project_id}")

            audio_list = await self.audio.generate_all_audio(
                project_id=project_id,
                comic_json=project.comic_json,
                voice_id=voice_id,
                voice_name=voice_name
            )

            await self.update_status(project_id, ProjectStatus.AUDIO_READY)

            return audio_list

        except Exception as e:
            await self.update_status(project_id, ProjectStatus.FAILED, str(e))
            raise

    async def regenerate_panel_audio(
        self,
        project_id: str,
        panel_number: int,
        voice_id: Optional[str] = None,
        voice_name: Optional[str] = None
    ) -> PanelAudio:
        """
        Regenerate audio for a single panel.

        Args:
            project_id: Project UUID
            panel_number: Panel to regenerate
            voice_id: New voice ID
            voice_name: New voice name

        Returns:
            New PanelAudio
        """
        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        # Get text for this panel
        panel_texts = self.audio.extract_all_panel_texts(project.comic_json)
        text = panel_texts.get(panel_number, "")

        if not text:
            raise ValueError(f"No text found for panel {panel_number}")

        return await self.audio.regenerate_panel_audio(
            project_id=project_id,
            panel_number=panel_number,
            text=text,
            voice_id=voice_id,
            voice_name=voice_name
        )

    # =========================================================================
    # Director Instructions
    # =========================================================================

    async def generate_all_instructions(
        self,
        project_id: str
    ) -> List[PanelInstruction]:
        """
        Generate cinematography instructions for all panels.

        Args:
            project_id: Project UUID

        Returns:
            List of PanelInstruction
        """
        await self.update_status(project_id, ProjectStatus.DIRECTING)

        try:
            project = await self.get_project(project_id)
            if not project:
                raise ValueError(f"Project not found: {project_id}")

            # Get layout (parse if not already done)
            layout = project.layout
            if not layout:
                layout = await self.parse_layout(project_id)

            # Get audio durations
            audio_list = await self.audio.get_all_panel_audio(project_id)
            audio_durations = {a.panel_number: a.duration_ms for a in audio_list}

            # Generate instructions
            instructions = self.director.generate_all_instructions(
                comic_json=project.comic_json,
                layout=layout,
                audio_durations=audio_durations
            )

            # Save to database
            for instruction in instructions:
                await self.director.save_panel_instruction(project_id, instruction)

            await self.update_status(project_id, ProjectStatus.READY_FOR_REVIEW)

            return instructions

        except Exception as e:
            await self.update_status(project_id, ProjectStatus.FAILED, str(e))
            raise

    async def update_panel_instruction(
        self,
        project_id: str,
        panel_number: int,
        camera_updates: Optional[Dict[str, Any]] = None,
        effects_updates: Optional[Dict[str, Any]] = None,
        transition_updates: Optional[Dict[str, Any]] = None
    ) -> PanelInstruction:
        """
        Update instruction for a single panel.

        Args:
            project_id: Project UUID
            panel_number: Panel to update
            camera_updates: Updates to camera settings
            effects_updates: Updates to effects
            transition_updates: Updates to transition

        Returns:
            Updated PanelInstruction
        """
        instruction = await self.director.get_panel_instruction(
            project_id, panel_number
        )
        if not instruction:
            raise ValueError(f"Instruction not found for panel {panel_number}")

        # Apply updates
        if camera_updates:
            camera_dict = instruction.camera.model_dump()
            camera_dict.update(camera_updates)
            instruction.camera = type(instruction.camera)(**camera_dict)

        if effects_updates:
            effects_dict = instruction.effects.model_dump()
            effects_dict.update(effects_updates)
            instruction.effects = type(instruction.effects)(**effects_dict)

        if transition_updates:
            transition_dict = instruction.transition.model_dump()
            transition_dict.update(transition_updates)
            instruction.transition = type(instruction.transition)(**transition_dict)

        # Mark as not approved (needs re-review)
        instruction.is_approved = False
        instruction.preview_url = None

        # Save
        await self.director.save_panel_instruction(project_id, instruction)

        return instruction

    # =========================================================================
    # Panel Preview
    # =========================================================================

    async def render_panel_preview(
        self,
        project_id: str,
        panel_number: int
    ) -> str:
        """
        Render preview video for a single panel.

        Args:
            project_id: Project UUID
            panel_number: Panel to preview

        Returns:
            URL to preview video
        """
        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        instruction = await self.director.get_panel_instruction(
            project_id, panel_number
        )
        if not instruction:
            raise ValueError(f"Instruction not found for panel {panel_number}")

        # Apply user overrides if present
        if instruction.user_overrides and instruction.user_overrides.has_overrides():
            logger.info(f"Panel {panel_number}: Applying overrides: {instruction.user_overrides}")
            instruction = self.director.apply_overrides(instruction, instruction.user_overrides)
            logger.info(f"Panel {panel_number}: Effects after override: {instruction.effects}")
        else:
            logger.info(f"Panel {panel_number}: No overrides to apply (user_overrides={instruction.user_overrides})")

        # Download comic grid
        grid_path = await self._download_file(
            project.comic_grid_url,
            project_id,
            "comic_grid.png"
        )

        # Get audio file
        panel_audio = await self.audio.get_panel_audio(project_id, panel_number)
        audio_path = None
        if panel_audio:
            audio_path = await self._download_file(
                panel_audio.audio_url,
                project_id,
                panel_audio.audio_filename
            )

        # Get aspect ratio from project
        aspect_ratio = project.aspect_ratio

        # Render preview
        preview_path = await self.render.render_panel_preview(
            project_id=project_id,
            panel_number=panel_number,
            comic_grid_path=grid_path,
            instruction=instruction,
            layout=project.layout,
            audio_path=audio_path,
            aspect_ratio=aspect_ratio
        )

        # Upload preview (returns storage path)
        storage_path = await self.render.upload_video(
            project_id=project_id,
            local_path=Path(preview_path),
            filename=f"preview_panel_{panel_number:02d}.mp4"
        )

        # Update instruction with storage path (for later retrieval)
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .update({"preview_url": storage_path})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )

        # Return signed URL for immediate playback
        signed_url = await self.render.get_video_url(storage_path)
        return signed_url

    async def approve_panel(
        self,
        project_id: str,
        panel_number: int
    ) -> None:
        """
        Approve audio (if exists) and instruction for a panel.

        Args:
            project_id: Project UUID
            panel_number: Panel to approve
        """
        # Check if audio exists before trying to approve
        panel_audio = await self.audio.get_panel_audio(project_id, panel_number)
        if panel_audio:
            await self.audio.approve_panel_audio(project_id, panel_number)

        # Always approve instruction
        await self.director.approve_instruction(project_id, panel_number)

        logger.info(f"Approved panel {panel_number} for project {project_id}")

    # =========================================================================
    # Final Video Rendering
    # =========================================================================

    async def render_final_video(self, project_id: str) -> str:
        """
        Render the final complete video.

        All panels must be approved before rendering.

        Args:
            project_id: Project UUID

        Returns:
            URL to final video
        """
        await self.update_status(project_id, ProjectStatus.RENDERING)

        try:
            project = await self.get_project(project_id)
            if not project:
                raise ValueError(f"Project not found: {project_id}")

            # Verify all panels approved
            instructions = await self.director.get_all_instructions(project_id)
            # IMPORTANT: Sort by panel number to ensure correct render order
            instructions = sorted(instructions, key=lambda x: x.panel_number)
            audio_list = await self.audio.get_all_panel_audio(project_id)

            unapproved = [i for i in instructions if not i.is_approved]
            if unapproved:
                panel_nums = [i.panel_number for i in unapproved]
                raise ValueError(f"Panels not approved: {panel_nums}")

            unapproved_audio = [a for a in audio_list if not a.is_approved]
            if unapproved_audio:
                panel_nums = [a.panel_number for a in unapproved_audio]
                raise ValueError(f"Audio not approved for panels: {panel_nums}")

            # Apply user overrides to each instruction
            instructions = [
                self.director.apply_overrides(instr, instr.user_overrides)
                if instr.user_overrides and instr.user_overrides.has_overrides()
                else instr
                for instr in instructions
            ]

            # Recalculate camera positions from layout to ensure correct coordinates
            # (stored instructions may have outdated center_x/center_y values)
            logger.info(f"Layout: {project.layout.grid_cols}x{project.layout.grid_rows}, panel_cells={project.layout.panel_cells}, row_cols={project.layout.row_cols}")
            for instr in instructions:
                try:
                    bounds = self.director.calculate_panel_bounds(
                        instr.panel_number,
                        project.layout
                    )
                    old_x, old_y = instr.camera.center_x, instr.camera.center_y
                    instr.camera.center_x = bounds.center_x
                    instr.camera.center_y = bounds.center_y
                    logger.info(
                        f"Panel {instr.panel_number}: camera ({old_x:.3f}, {old_y:.3f}) -> "
                        f"({bounds.center_x:.3f}, {bounds.center_y:.3f})"
                    )
                except ValueError as e:
                    logger.warning(f"Could not recalculate bounds for panel {instr.panel_number}: {e}")

            # Get aspect ratio from project
            aspect_ratio = project.aspect_ratio

            # Download comic grid
            grid_path = await self._download_file(
                project.comic_grid_url,
                project_id,
                "comic_grid.png"
            )

            # Download all audio files
            audio_paths = {}
            for audio in audio_list:
                path = await self._download_file(
                    audio.audio_url,
                    project_id,
                    audio.audio_filename
                )
                audio_paths[audio.panel_number] = path

            # Download background music if specified
            bg_music_path = None
            if project.background_music_url:
                bg_music_path = await self._download_file(
                    project.background_music_url,
                    project_id,
                    "background_music.mp3"
                )

            # Render full video
            video_path = await self.render.render_full_video(
                project_id=project_id,
                comic_grid_path=grid_path,
                instructions=instructions,
                layout=project.layout,
                audio_paths=audio_paths,
                aspect_ratio=aspect_ratio,
                background_music_path=bg_music_path
            )

            # Upload final video (returns storage path)
            storage_path = await self.render.upload_video(
                project_id=project_id,
                local_path=Path(video_path),
                filename="final_video.mp4"
            )

            # Update project with storage path
            # Note: Add rendered_at column to DB then uncomment below
            render_time = datetime.utcnow()
            await asyncio.to_thread(
                lambda: self.supabase.table("comic_video_projects")
                    .update({
                        "final_video_url": storage_path,
                        "status": ProjectStatus.COMPLETE.value,
                        # "rendered_at": render_time.isoformat(),  # Needs DB migration
                        "updated_at": render_time.isoformat()
                    })
                    .eq("id", project_id)
                    .execute()
            )

            logger.info(f"Rendered final video for project {project_id}")

            # Return signed URL for immediate playback
            signed_url = await self.render.get_video_url(storage_path)
            return signed_url

        except Exception as e:
            await self.update_status(project_id, ProjectStatus.FAILED, str(e))
            raise

    # =========================================================================
    # Bulk Actions (Phase 5.5)
    # =========================================================================

    async def render_all_panels(
        self,
        project_id: str,
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
        force_rerender: bool = False
    ) -> Dict[int, str]:
        """
        Render preview videos for all panels.

        Args:
            project_id: Project UUID
            aspect_ratio: Output aspect ratio
            force_rerender: Re-render even if preview exists

        Returns:
            Dict of panel_number -> preview URL
        """
        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        instructions = await self.director.get_all_instructions(project_id)
        if not instructions:
            raise ValueError("No instructions found. Generate instructions first.")

        # Download comic grid
        grid_path = await self._download_file(
            project.comic_grid_url,
            project_id,
            "comic_grid.png"
        )

        # Download all audio files
        audio_list = await self.audio.get_all_panel_audio(project_id)
        audio_paths = {}
        for audio in audio_list:
            path = await self._download_file(
                audio.audio_url,
                project_id,
                audio.audio_filename
            )
            audio_paths[audio.panel_number] = path

        results = {}

        for instruction in instructions:
            panel_num = instruction.panel_number

            # Skip if already has preview (unless force)
            if not force_rerender and instruction.preview_url:
                results[panel_num] = instruction.preview_url
                continue

            try:
                audio_path = audio_paths.get(panel_num)

                preview_path = await self.render.render_panel_preview(
                    project_id=project_id,
                    panel_number=panel_num,
                    comic_grid_path=grid_path,
                    instruction=instruction,
                    layout=project.layout,
                    audio_path=audio_path,
                    aspect_ratio=aspect_ratio
                )

                # Upload preview (returns storage path)
                storage_path = await self.render.upload_video(
                    project_id=project_id,
                    local_path=Path(preview_path),
                    filename=f"preview_panel_{panel_num:02d}.mp4"
                )

                # Update instruction with storage path
                await asyncio.to_thread(
                    lambda pn=panel_num, path=storage_path: self.supabase.table("comic_panel_instructions")
                        .update({"preview_url": path})
                        .eq("project_id", project_id)
                        .eq("panel_number", pn)
                        .execute()
                )

                # Return signed URL for playback
                signed_url = await self.render.get_video_url(storage_path)
                results[panel_num] = signed_url

            except Exception as e:
                logger.error(f"Failed to render panel {panel_num}: {e}")
                results[panel_num] = None

        logger.info(f"Rendered {len([r for r in results.values() if r])} of {len(instructions)} panels")
        return results

    async def approve_all_panels(self, project_id: str) -> int:
        """
        Approve all panels at once.

        Args:
            project_id: Project UUID

        Returns:
            Number of panels approved
        """
        instructions = await self.director.get_all_instructions(project_id)
        audio_list = await self.audio.get_all_panel_audio(project_id)

        approved_count = 0

        for instruction in instructions:
            if not instruction.is_approved:
                await self.director.approve_instruction(project_id, instruction.panel_number)
                approved_count += 1

        for audio in audio_list:
            if not audio.is_approved:
                await self.audio.approve_panel_audio(project_id, audio.panel_number)

        logger.info(f"Approved {approved_count} panels for project {project_id}")
        return approved_count

    async def update_aspect_ratio(
        self,
        project_id: str,
        aspect_ratio: str
    ) -> None:
        """
        Update project aspect ratio.

        Args:
            project_id: Project UUID
            aspect_ratio: New aspect ratio (e.g., "9:16", "16:9")
        """
        # Validate aspect ratio
        ratio = AspectRatio.from_string(aspect_ratio)
        width, height = ratio.dimensions

        await asyncio.to_thread(
            lambda: self.supabase.table("comic_video_projects")
                .update({
                    "aspect_ratio": aspect_ratio,
                    "output_width": width,
                    "output_height": height,
                    "updated_at": datetime.utcnow().isoformat()
                })
                .eq("id", project_id)
                .execute()
        )

        logger.info(f"Updated aspect ratio to {aspect_ratio} for project {project_id}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def get_project_summary(self, project_id: str) -> Dict[str, Any]:
        """
        Get summary of project state.

        Returns dict with panel counts, approval status, etc.
        """
        project = await self.get_project(project_id)
        if not project:
            return {"error": "Project not found"}

        audio_list = await self.audio.get_all_panel_audio(project_id)
        instructions = await self.director.get_all_instructions(project_id)

        total_panels = len(project.comic_json.get("panels", []))
        audio_generated = len(audio_list)
        audio_approved = sum(1 for a in audio_list if a.is_approved)
        instructions_generated = len(instructions)
        instructions_approved = sum(1 for i in instructions if i.is_approved)

        return {
            "project_id": project_id,
            "title": project.title,
            "status": project.status.value,
            "total_panels": total_panels,
            "audio": {
                "generated": audio_generated,
                "approved": audio_approved,
                "complete": audio_generated == total_panels
            },
            "instructions": {
                "generated": instructions_generated,
                "approved": instructions_approved,
                "complete": instructions_generated == total_panels
            },
            "ready_for_final_render": (
                audio_approved == total_panels and
                instructions_approved == total_panels
            ),
            "final_video_url": project.final_video_url
        }

    async def _download_file(
        self,
        url: str,
        project_id: str,
        filename: str
    ) -> Path:
        """Download file from URL or storage to local cache."""
        cache_path = self.cache_dir / project_id
        cache_path.mkdir(parents=True, exist_ok=True)
        local_path = cache_path / filename

        # Check if already cached
        if local_path.exists():
            return local_path

        # Handle storage URLs vs external URLs
        if url.startswith(self.STORAGE_BUCKET):
            # Supabase storage URL - get signed URL
            signed_url = await self.audio.get_audio_url(url)
            url = signed_url

        # Download
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            local_path.write_bytes(response.content)

        return local_path

    def _generate_slug(self, title: str) -> str:
        """Generate URL-safe slug from title."""
        import re
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        slug = slug.strip('-')
        return f"{slug}-{uuid.uuid4().hex[:8]}"

    def _row_to_project(self, row: Dict[str, Any]) -> ComicVideoProject:
        """Convert database row to ComicVideoProject."""
        layout = None
        if row.get("layout"):
            layout = ComicLayout(**row["layout"])

        # Parse aspect ratio
        aspect_ratio_str = row.get("aspect_ratio", "9:16")
        aspect_ratio = AspectRatio.from_string(aspect_ratio_str)

        return ComicVideoProject(
            project_id=row["id"],
            title=row["title"],
            comic_grid_url=row["comic_grid_url"],
            comic_json=row["comic_json"],
            layout=layout,
            aspect_ratio=aspect_ratio,
            output_width=row.get("output_width", 1080),
            output_height=row.get("output_height", 1920),
            fps=row.get("fps", 30),
            background_music_url=row.get("background_music_url"),
            status=ProjectStatus(row.get("status", "draft")),
            error_message=row.get("error_message"),
            final_video_url=row.get("final_video_url"),
            created_at=datetime.fromisoformat(
                row["created_at"].replace("Z", "+00:00")
            ) if row.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(
                row["updated_at"].replace("Z", "+00:00")
            ) if row.get("updated_at") else datetime.utcnow(),
            panel_audio=[],  # Loaded separately
            panel_instructions=[]  # Loaded separately
        )
