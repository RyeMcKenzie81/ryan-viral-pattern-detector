"""
Comic Audio Service

Handles audio generation for comic panels using ElevenLabs.
Wraps the existing ElevenLabsService for comic-specific workflows.

Following patterns from AudioProductionService.
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from .models import PanelAudio, ComicLayout
from ..elevenlabs_service import ElevenLabsService
from ..audio_models import VoiceSettings, Character
from ..ffmpeg_service import FFmpegService
from ...core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ComicAudioService:
    """Service for generating comic panel audio via ElevenLabs."""

    STORAGE_BUCKET = "comic-video"

    # Default voice for comic narration
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (ElevenLabs)
    DEFAULT_VOICE_NAME = "Rachel"

    def __init__(
        self,
        elevenlabs: Optional[ElevenLabsService] = None,
        ffmpeg: Optional[FFmpegService] = None
    ):
        """
        Initialize Comic Audio Service.

        Args:
            elevenlabs: ElevenLabs service instance (created if not provided)
            ffmpeg: FFmpeg service instance (created if not provided)
        """
        self.elevenlabs = elevenlabs or ElevenLabsService()
        self.ffmpeg = ffmpeg or FFmpegService()
        self.supabase = get_supabase_client()

        # Local output directory
        self.output_base = Path("comic_video_audio")
        self.output_base.mkdir(exist_ok=True)

        logger.info("ComicAudioService initialized")

    @property
    def enabled(self) -> bool:
        """Check if service is enabled (ElevenLabs configured)."""
        return self.elevenlabs.enabled

    # =========================================================================
    # Text Extraction
    # =========================================================================

    def extract_panel_text(self, panel: Dict[str, Any]) -> str:
        """
        Extract speakable text from a comic panel.

        Priority:
        1. script_for_audio - pre-formatted TTS text (preferred)
        2. dialogue - fallback to dialogue text
        3. header_text + dialogue - legacy fallback

        Args:
            panel: Panel dict from comic JSON

        Returns:
            Text for TTS
        """
        # Prefer script_for_audio if available (pre-formatted for TTS)
        script = panel.get("script_for_audio", "").strip()
        if script:
            return script

        # Fallback to dialogue
        dialogue = panel.get("dialogue", "").strip()
        if dialogue:
            return dialogue

        # Legacy fallback: combine header and dialogue
        parts = []
        header = panel.get("header_text", "").strip()
        if header:
            parts.append(header)

        return " ".join(parts)

    def extract_all_panel_texts(
        self,
        comic_json: Dict[str, Any]
    ) -> Dict[int, str]:
        """
        Extract text from all panels in comic JSON.

        Args:
            comic_json: Full comic JSON with panels array

        Returns:
            Dict mapping panel_number -> text
        """
        texts = {}
        panels = comic_json.get("panels", [])

        for panel in panels:
            panel_num = panel.get("panel_number", 0)
            if panel_num > 0:
                text = self.extract_panel_text(panel)
                if text:
                    texts[panel_num] = text

        logger.info(f"Extracted text from {len(texts)} panels")
        return texts

    # =========================================================================
    # Audio Generation
    # =========================================================================

    async def generate_panel_audio(
        self,
        project_id: str,
        panel_number: int,
        text: str,
        voice_id: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_settings: Optional[VoiceSettings] = None
    ) -> PanelAudio:
        """
        Generate audio for a single panel.

        Args:
            project_id: Project UUID
            panel_number: Panel number (1-indexed)
            text: Text to speak
            voice_id: ElevenLabs voice ID (defaults to Rachel)
            voice_name: Voice display name
            voice_settings: Voice generation settings

        Returns:
            PanelAudio with file URL and duration
        """
        if not self.enabled:
            raise RuntimeError("ElevenLabs service not configured")

        voice_id = voice_id or self.DEFAULT_VOICE_ID
        voice_name = voice_name or self.DEFAULT_VOICE_NAME
        settings = voice_settings or VoiceSettings()

        # Generate filename
        filename = f"{panel_number:02d}_panel.mp3"

        # Create output path
        project_dir = self.output_base / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = project_dir / filename

        logger.info(f"Generating audio for panel {panel_number}: {len(text)} chars")

        # Generate speech via ElevenLabs
        result = await self.elevenlabs.generate_speech(
            text=text,
            voice_id=voice_id,
            settings=settings,
            output_path=output_path
        )

        # Get duration
        duration_ms = await asyncio.to_thread(
            self.ffmpeg.get_duration_ms, output_path
        )

        # Upload to storage
        audio_url = await self._upload_audio(
            project_id=project_id,
            filename=filename,
            local_path=output_path
        )

        # Create PanelAudio
        panel_audio = PanelAudio(
            panel_number=panel_number,
            audio_url=audio_url,
            audio_filename=filename,
            duration_ms=duration_ms,
            voice_id=voice_id,
            voice_name=voice_name,
            text_content=text,
            created_at=datetime.utcnow(),
            is_approved=False
        )

        # Save to database
        await self._save_panel_audio(project_id, panel_audio)

        logger.info(
            f"Generated panel {panel_number} audio: {duration_ms}ms, "
            f"uploaded to {audio_url}"
        )

        return panel_audio

    async def generate_all_audio(
        self,
        project_id: str,
        comic_json: Dict[str, Any],
        voice_id: Optional[str] = None,
        voice_name: Optional[str] = None
    ) -> List[PanelAudio]:
        """
        Generate audio for all panels in a comic.

        Args:
            project_id: Project UUID
            comic_json: Full comic JSON with panels array
            voice_id: ElevenLabs voice ID
            voice_name: Voice display name

        Returns:
            List of PanelAudio for each panel
        """
        # Extract texts
        panel_texts = self.extract_all_panel_texts(comic_json)

        if not panel_texts:
            logger.warning("No panel texts found in comic JSON")
            return []

        results = []

        # Generate audio for each panel sequentially
        # (ElevenLabs rate limits apply)
        for panel_number, text in sorted(panel_texts.items()):
            try:
                audio = await self.generate_panel_audio(
                    project_id=project_id,
                    panel_number=panel_number,
                    text=text,
                    voice_id=voice_id,
                    voice_name=voice_name
                )
                results.append(audio)

            except Exception as e:
                logger.error(f"Failed to generate audio for panel {panel_number}: {e}")
                # Continue with other panels
                continue

        logger.info(f"Generated audio for {len(results)}/{len(panel_texts)} panels")
        return results

    async def regenerate_panel_audio(
        self,
        project_id: str,
        panel_number: int,
        text: str,
        voice_id: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_settings: Optional[VoiceSettings] = None
    ) -> PanelAudio:
        """
        Regenerate audio for a single panel (e.g., with different voice settings).

        Args:
            project_id: Project UUID
            panel_number: Panel number
            text: Text to speak
            voice_id: New voice ID
            voice_name: New voice name
            voice_settings: New voice settings

        Returns:
            New PanelAudio
        """
        # Delete existing audio record (if any)
        await self._delete_panel_audio(project_id, panel_number)

        # Generate new audio
        return await self.generate_panel_audio(
            project_id=project_id,
            panel_number=panel_number,
            text=text,
            voice_id=voice_id,
            voice_name=voice_name,
            voice_settings=voice_settings
        )

    # =========================================================================
    # Audio Retrieval
    # =========================================================================

    async def get_panel_audio(
        self,
        project_id: str,
        panel_number: int
    ) -> Optional[PanelAudio]:
        """
        Get audio info for a specific panel.

        Args:
            project_id: Project UUID
            panel_number: Panel number

        Returns:
            PanelAudio or None if not found
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio")
                .select("*")
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .maybe_single()
                .execute()
        )

        if not result.data:
            return None

        return self._row_to_panel_audio(result.data)

    async def get_all_panel_audio(
        self,
        project_id: str
    ) -> List[PanelAudio]:
        """
        Get all audio for a project.

        Args:
            project_id: Project UUID

        Returns:
            List of PanelAudio ordered by panel number
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio")
                .select("*")
                .eq("project_id", project_id)
                .order("panel_number")
                .execute()
        )

        return [self._row_to_panel_audio(row) for row in result.data]

    async def approve_panel_audio(
        self,
        project_id: str,
        panel_number: int
    ) -> None:
        """
        Mark panel audio as approved.

        Args:
            project_id: Project UUID
            panel_number: Panel number
        """
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio")
                .update({"is_approved": True})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )
        logger.info(f"Approved audio for project {project_id} panel {panel_number}")

    # =========================================================================
    # Storage Operations
    # =========================================================================

    async def _upload_audio(
        self,
        project_id: str,
        filename: str,
        local_path: Path
    ) -> str:
        """
        Upload audio file to Supabase Storage.

        Args:
            project_id: Project UUID
            filename: Audio filename
            local_path: Local file path

        Returns:
            Storage URL
        """
        storage_path = f"{project_id}/audio/{filename}"

        # Read file
        audio_data = local_path.read_bytes()

        # Upload
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                storage_path,
                audio_data,
                {"content-type": "audio/mpeg"}
            )
        )

        logger.debug(f"Uploaded audio: {storage_path}")
        return f"{self.STORAGE_BUCKET}/{storage_path}"

    async def get_audio_url(
        self,
        storage_path: str,
        expires_in: int = 3600
    ) -> str:
        """
        Get a signed URL for audio playback.

        Args:
            storage_path: Full storage path
            expires_in: URL expiry in seconds

        Returns:
            Signed URL
        """
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        result = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).create_signed_url(
                path, expires_in
            )
        )

        return result.get("signedURL", "")

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def _save_panel_audio(
        self,
        project_id: str,
        audio: PanelAudio
    ) -> None:
        """Save panel audio to database."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio").upsert({
                "project_id": project_id,
                "panel_number": audio.panel_number,
                "audio_url": audio.audio_url,
                "audio_filename": audio.audio_filename,
                "duration_ms": audio.duration_ms,
                "voice_id": audio.voice_id,
                "voice_name": audio.voice_name,
                "text_content": audio.text_content,
                "is_approved": audio.is_approved
            }).execute()
        )

    async def _delete_panel_audio(
        self,
        project_id: str,
        panel_number: int
    ) -> None:
        """Delete panel audio record."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio")
                .delete()
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )

    def _row_to_panel_audio(self, row: Dict[str, Any]) -> PanelAudio:
        """Convert database row to PanelAudio."""
        return PanelAudio(
            panel_number=row["panel_number"],
            audio_url=row["audio_url"],
            audio_filename=row["audio_filename"],
            duration_ms=row["duration_ms"],
            voice_id=row.get("voice_id"),
            voice_name=row.get("voice_name"),
            text_content=row.get("text_content", ""),
            created_at=datetime.fromisoformat(
                row["created_at"].replace("Z", "+00:00")
            ) if row.get("created_at") else datetime.utcnow(),
            is_approved=row.get("is_approved", False)
        )
