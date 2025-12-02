"""
Audio Production Service

Database operations and orchestration for audio production workflow.
Handles sessions, takes, and voice profiles.

Follows existing service patterns (like AdCreationService).
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
import uuid
import shutil

from .audio_models import (
    ScriptBeat,
    AudioTake,
    BeatWithTakes,
    ProductionSession,
    CharacterVoiceProfile,
    VoiceSettings,
    Character,
    Pace
)
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class AudioProductionService:
    """Service for audio production workflow operations"""

    def __init__(self):
        """Initialize service with Supabase client."""
        self.supabase = get_supabase_client()
        self.output_base = Path("audio_production")
        self.output_base.mkdir(exist_ok=True)
        logger.info("AudioProductionService initialized")

    # =========================================================================
    # Session Operations
    # =========================================================================

    async def create_session(
        self,
        video_title: str,
        project_name: str,
        beats: List[ScriptBeat],
        source_els: Optional[str] = None
    ) -> ProductionSession:
        """
        Create a new production session in database.

        Args:
            video_title: Title of the video
            project_name: Project name (e.g., "trash-panda")
            beats: Parsed script beats
            source_els: Original ELS content for reference

        Returns:
            New ProductionSession
        """
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Create output directory
        session_dir = self.output_base / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Initialize beats with empty takes
        beats_with_takes = [
            BeatWithTakes(beat=beat, takes=[], selected_take_id=None)
            for beat in beats
        ]

        # Serialize beats for database
        beats_json = [b.beat.model_dump(mode='json') for b in beats_with_takes]

        # Insert into database
        await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions").insert({
                "id": session_id,
                "video_title": video_title,
                "project_name": project_name,
                "status": "draft",
                "source_els": source_els,
                "beats_json": beats_json
            }).execute()
        )

        logger.info(f"Created session: {session_id} ({video_title})")

        return ProductionSession(
            session_id=session_id,
            video_title=video_title,
            project_name=project_name,
            beats=beats_with_takes,
            source_els=source_els,
            created_at=now,
            updated_at=now,
            status="draft"
        )

    async def get_session(self, session_id: str) -> ProductionSession:
        """
        Load full session from database.

        Args:
            session_id: Session UUID

        Returns:
            ProductionSession with all beats and takes

        Raises:
            ValueError: If session not found
        """
        # Get session record
        result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions")
                .select("*")
                .eq("id", session_id)
                .single()
                .execute()
        )

        if not result.data:
            raise ValueError(f"Session not found: {session_id}")

        data = result.data

        # Get all takes for this session
        takes_result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes")
                .select("*")
                .eq("session_id", session_id)
                .execute()
        )

        # Group takes by beat
        takes_by_beat: Dict[str, List[AudioTake]] = {}
        for row in takes_result.data:
            take = AudioTake(
                take_id=row["id"],
                beat_id=row["beat_id"],
                audio_path=row["audio_path"],
                audio_duration_ms=row["audio_duration_ms"] or 0,
                generation_settings=VoiceSettings(**row["settings_json"]),
                direction_used=row["direction_used"],
                created_at=datetime.fromisoformat(
                    row["created_at"].replace('Z', '+00:00')
                ),
                is_selected=row["is_selected"]
            )
            takes_by_beat.setdefault(take.beat_id, []).append(take)

        # Reconstruct beats with takes
        beats_with_takes = []
        for beat_data in data["beats_json"]:
            beat = ScriptBeat(**beat_data)
            takes = takes_by_beat.get(beat.beat_id, [])
            selected = next((t.take_id for t in takes if t.is_selected), None)
            beats_with_takes.append(BeatWithTakes(
                beat=beat,
                takes=takes,
                selected_take_id=selected
            ))

        return ProductionSession(
            session_id=session_id,
            video_title=data["video_title"],
            project_name=data["project_name"],
            beats=beats_with_takes,
            source_els=data.get("source_els"),
            created_at=datetime.fromisoformat(
                data["created_at"].replace('Z', '+00:00')
            ),
            updated_at=datetime.fromisoformat(
                data["updated_at"].replace('Z', '+00:00')
            ),
            status=data["status"]
        )

    async def update_session_status(self, session_id: str, status: str) -> None:
        """
        Update session status.

        Args:
            session_id: Session UUID
            status: New status (draft, generating, in_progress, completed, exported)
        """
        valid_statuses = ["draft", "generating", "in_progress", "completed", "exported"]
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}")

        await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions")
                .update({"status": status})
                .eq("id", session_id)
                .execute()
        )
        logger.info(f"Session {session_id} status -> {status}")

    async def get_recent_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recent sessions for sidebar.

        Args:
            limit: Maximum sessions to return

        Returns:
            List of session summary dicts
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions")
                .select("id, video_title, status, created_at")
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
        )
        return result.data

    # =========================================================================
    # Take Operations
    # =========================================================================

    async def save_take(self, session_id: str, take: AudioTake) -> None:
        """
        Save a generated take to database.

        Args:
            session_id: Session UUID
            take: AudioTake to save
        """
        await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes").insert({
                "id": take.take_id,
                "session_id": session_id,
                "beat_id": take.beat_id,
                "audio_path": take.audio_path,
                "audio_duration_ms": take.audio_duration_ms,
                "settings_json": take.generation_settings.model_dump(),
                "direction_used": take.direction_used,
                "is_selected": take.is_selected
            }).execute()
        )
        logger.debug(f"Saved take {take.take_id} for beat {take.beat_id}")

    async def select_take(
        self,
        session_id: str,
        beat_id: str,
        take_id: str
    ) -> None:
        """
        Select which take to use for a beat.

        Args:
            session_id: Session UUID
            beat_id: Beat ID
            take_id: Take ID to select
        """
        # Deselect all takes for this beat
        await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes")
                .update({"is_selected": False})
                .eq("session_id", session_id)
                .eq("beat_id", beat_id)
                .execute()
        )

        # Select the chosen take
        await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes")
                .update({"is_selected": True})
                .eq("id", take_id)
                .execute()
        )
        logger.info(f"Selected take {take_id} for beat {beat_id}")

    async def get_takes_for_beat(
        self,
        session_id: str,
        beat_id: str
    ) -> List[AudioTake]:
        """
        Get all takes for a specific beat.

        Args:
            session_id: Session UUID
            beat_id: Beat ID

        Returns:
            List of AudioTake objects
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes")
                .select("*")
                .eq("session_id", session_id)
                .eq("beat_id", beat_id)
                .order("created_at", desc=True)
                .execute()
        )

        takes = []
        for row in result.data:
            takes.append(AudioTake(
                take_id=row["id"],
                beat_id=row["beat_id"],
                audio_path=row["audio_path"],
                audio_duration_ms=row["audio_duration_ms"] or 0,
                generation_settings=VoiceSettings(**row["settings_json"]),
                direction_used=row["direction_used"],
                created_at=datetime.fromisoformat(
                    row["created_at"].replace('Z', '+00:00')
                ),
                is_selected=row["is_selected"]
            ))

        return takes

    # =========================================================================
    # Voice Profile Operations
    # =========================================================================

    async def get_all_voice_profiles(self) -> List[CharacterVoiceProfile]:
        """
        Get all voice profiles from database.

        Returns:
            List of CharacterVoiceProfile objects
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("character_voice_profiles")
                .select("*")
                .execute()
        )

        profiles = []
        for row in result.data:
            try:
                profiles.append(CharacterVoiceProfile(
                    id=row["id"],
                    character=Character(row["character"]),
                    voice_id=row["voice_id"],
                    display_name=row["display_name"],
                    description=row.get("description"),
                    stability=row["stability"],
                    similarity_boost=row["similarity_boost"],
                    style=row["style"],
                    speed=row["speed"]
                ))
            except ValueError:
                continue

        return profiles

    async def update_voice_profile(
        self,
        character: str,
        voice_id: Optional[str] = None,
        stability: Optional[float] = None,
        style: Optional[float] = None,
        speed: Optional[float] = None
    ) -> None:
        """
        Update a voice profile.

        Args:
            character: Character name
            voice_id: Optional new voice ID
            stability: Optional new stability (0-1)
            style: Optional new style (0-1)
            speed: Optional new speed (0.7-1.2)
        """
        updates = {}
        if voice_id is not None:
            updates["voice_id"] = voice_id
        if stability is not None:
            updates["stability"] = stability
        if style is not None:
            updates["style"] = style
        if speed is not None:
            updates["speed"] = speed

        if updates:
            await asyncio.to_thread(
                lambda: self.supabase.table("character_voice_profiles")
                    .update(updates)
                    .eq("character", character)
                    .execute()
            )
            logger.info(f"Updated voice profile for {character}")

    # =========================================================================
    # Export Operations
    # =========================================================================

    async def export_selected_takes(
        self,
        session_id: str,
        output_dir: Optional[Path] = None
    ) -> List[Path]:
        """
        Export all selected takes with clean filenames.

        Output: 01_hook.mp3, 02_setup.mp3, etc.

        Args:
            session_id: Session UUID
            output_dir: Optional custom output directory

        Returns:
            List of exported file paths
        """
        session = await self.get_session(session_id)

        if output_dir is None:
            output_dir = Path("exports") / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        exported = []

        for bwt in session.beats:
            if not bwt.selected_take_id:
                continue

            # Find selected take
            selected = next(
                (t for t in bwt.takes if t.take_id == bwt.selected_take_id),
                None
            )
            if not selected:
                continue

            src = Path(selected.audio_path)
            if not src.exists():
                logger.warning(f"Audio file not found: {src}")
                continue

            # Clean filename: 01_hook.mp3
            dest = output_dir / f"{bwt.beat.beat_id}.mp3"
            shutil.copy(src, dest)
            exported.append(dest)
            logger.debug(f"Exported {dest.name}")

        # Update session status
        await self.update_session_status(session_id, "exported")

        logger.info(f"Exported {len(exported)} files to {output_dir}")
        return exported

    async def get_session_duration(self, session_id: str) -> int:
        """
        Get total duration of selected takes.

        Args:
            session_id: Session UUID

        Returns:
            Total duration in milliseconds
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_takes")
                .select("audio_duration_ms")
                .eq("session_id", session_id)
                .eq("is_selected", True)
                .execute()
        )

        total = sum(row["audio_duration_ms"] or 0 for row in result.data)
        return total
