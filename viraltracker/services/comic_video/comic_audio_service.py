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

from .models import PanelAudio, ComicLayout, AudioSegment, MultiSpeakerPanelAudio
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

        Automatically detects multi-speaker panels (with segments array)
        and uses appropriate generation method.

        Args:
            project_id: Project UUID
            comic_json: Full comic JSON with panels array
            voice_id: ElevenLabs voice ID (for single-speaker panels)
            voice_name: Voice display name

        Returns:
            List of PanelAudio for each panel
        """
        panels = comic_json.get("panels", [])

        if not panels:
            logger.warning("No panels found in comic JSON")
            return []

        results = []

        # Generate audio for each panel sequentially
        # (ElevenLabs rate limits apply)
        for panel in panels:
            panel_number = panel.get("panel_number", 0)
            if panel_number <= 0:
                continue

            try:
                # Check if panel has multi-speaker segments
                if self.has_multi_speaker(panel):
                    logger.info(f"Panel {panel_number}: Multi-speaker detected, using segment generation")
                    multi_audio = await self.generate_multi_speaker_audio(
                        project_id=project_id,
                        panel_number=panel_number,
                        panel=panel,
                        narrator_voice_id=voice_id,
                        narrator_voice_name=voice_name
                    )
                    # Create a PanelAudio from multi-speaker result for compatibility
                    audio = PanelAudio(
                        panel_number=panel_number,
                        audio_url=multi_audio.combined_audio_url or "",
                        audio_filename=f"{panel_number:02d}_combined.mp3",
                        duration_ms=multi_audio.total_duration_ms,
                        voice_id="multi-speaker",
                        voice_name="Multi-Speaker",
                        text_content=" | ".join(s.text for s in multi_audio.segments),
                        is_approved=False
                    )
                    # Save to panel audio table for compatibility with existing workflow
                    await self._save_panel_audio(project_id, audio)
                    results.append(audio)
                else:
                    # Single speaker - use regular generation
                    text = self.extract_panel_text(panel)
                    if text:
                        audio = await self.generate_panel_audio(
                            project_id=project_id,
                            panel_number=panel_number,
                            text=text,
                            voice_id=voice_id,
                            voice_name=voice_name
                        )
                        results.append(audio)

            except Exception as e:
                import traceback
                logger.error(f"Failed to generate audio for panel {panel_number}: {e}\n{traceback.format_exc()}")
                # Re-raise for first panel to surface errors during development
                if panel_number == 1:
                    raise RuntimeError(f"Panel 1 audio generation failed: {e}") from e
                continue

        logger.info(f"Generated audio for {len(results)} panels")
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

        if not result or not result.data:
            return []

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

    async def _download_audio_file(self, url: str, local_path: Path) -> None:
        """
        Download audio file from URL to local path.

        Args:
            url: URL to download from
            local_path: Local path to save to
        """
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            local_path.write_bytes(response.content)

        logger.debug(f"Downloaded audio to {local_path}")

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

    # =========================================================================
    # Multi-Speaker Audio Generation
    # =========================================================================

    def extract_panel_segments(self, panel: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Extract speaker segments from a comic panel.

        Looks for a 'segments' array in the panel JSON:
        [{"speaker": "narrator", "text": "..."}, {"speaker": "raccoon", "text": "..."}]

        Args:
            panel: Panel dict from comic JSON

        Returns:
            List of segment dicts with speaker and text, or empty list if single-speaker
        """
        segments = panel.get("segments", [])
        if not segments:
            return []

        # Validate and clean segments
        valid_segments = []
        for seg in segments:
            speaker = seg.get("speaker", "").strip().lower()
            text = seg.get("text", "").strip()
            if speaker and text:
                valid_segments.append({
                    "speaker": speaker,
                    "text": text
                })

        return valid_segments

    def has_multi_speaker(self, panel: Dict[str, Any]) -> bool:
        """Check if a panel has multi-speaker segments."""
        segments = self.extract_panel_segments(panel)
        return len(segments) > 1

    async def get_voice_for_speaker(
        self,
        speaker: str,
        narrator_voice_id: Optional[str] = None,
        narrator_voice_name: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Get voice ID and name for a speaker.

        Supports:
        - 'narrator' -> Uses provided narrator voice or default
        - 'raccoon' or 'every-coon' -> Load from character_voice_profiles
        - Other -> Fallback to narrator voice

        Args:
            speaker: Speaker identifier
            narrator_voice_id: Voice ID for narrator (from user selection)
            narrator_voice_name: Voice name for narrator

        Returns:
            Tuple of (voice_id, voice_name)
        """
        speaker_lower = speaker.lower()

        # Narrator uses user-selected voice or default
        if speaker_lower == "narrator":
            voice_id = narrator_voice_id or self.DEFAULT_VOICE_ID
            voice_name = narrator_voice_name or self.DEFAULT_VOICE_NAME
            return voice_id, voice_name

        # Raccoon/every-coon - look up from database
        if speaker_lower in ("raccoon", "every-coon"):
            try:
                result = await asyncio.to_thread(
                    lambda: self.supabase.table("character_voice_profiles")
                        .select("voice_id, display_name")
                        .eq("character", "every-coon")
                        .maybe_single()
                        .execute()
                )
                if result.data:
                    return result.data["voice_id"], result.data.get("display_name", "Every-Coon")
            except Exception as e:
                logger.warning(f"Could not load every-coon voice: {e}")

            # Fallback for raccoon if not found
            logger.info("Using default voice for raccoon (every-coon not found)")
            return self.DEFAULT_VOICE_ID, self.DEFAULT_VOICE_NAME

        # Unknown speaker - use narrator voice
        logger.info(f"Unknown speaker '{speaker}', using narrator voice")
        voice_id = narrator_voice_id or self.DEFAULT_VOICE_ID
        voice_name = narrator_voice_name or self.DEFAULT_VOICE_NAME
        return voice_id, voice_name

    async def generate_segment_audio(
        self,
        project_id: str,
        panel_number: int,
        segment: AudioSegment,
        narrator_voice_id: Optional[str] = None,
        narrator_voice_name: Optional[str] = None,
        voice_settings: Optional[VoiceSettings] = None
    ) -> AudioSegment:
        """
        Generate audio for a single speaker segment.

        Args:
            project_id: Project UUID
            panel_number: Panel number
            segment: AudioSegment with speaker and text
            narrator_voice_id: Voice ID for narrator segments
            narrator_voice_name: Voice name for narrator segments
            voice_settings: Optional voice settings

        Returns:
            Updated AudioSegment with audio_url and duration_ms
        """
        if not self.enabled:
            raise RuntimeError("ElevenLabs service not configured")

        # Get voice for speaker
        voice_id, voice_name = await self.get_voice_for_speaker(
            segment.speaker,
            narrator_voice_id=narrator_voice_id,
            narrator_voice_name=narrator_voice_name
        )
        settings = voice_settings or VoiceSettings()

        # Generate filename
        filename = f"{panel_number:02d}_seg{segment.segment_index:02d}_{segment.speaker}.mp3"

        # Create output path
        project_dir = self.output_base / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = project_dir / filename

        logger.info(
            f"Generating segment {segment.segment_index} for panel {panel_number}: "
            f"{segment.speaker} ({len(segment.text)} chars)"
        )

        # Generate speech
        await self.elevenlabs.generate_speech(
            text=segment.text,
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

        # Update segment with results
        updated_segment = segment.model_copy(update={
            "voice_id": voice_id,
            "voice_name": voice_name,
            "audio_url": audio_url,
            "duration_ms": duration_ms
        })

        # Save to database
        await self._save_audio_segment(project_id, panel_number, updated_segment)

        logger.info(
            f"Generated segment {segment.segment_index}: {duration_ms}ms, "
            f"uploaded to {audio_url}"
        )

        return updated_segment

    async def generate_multi_speaker_audio(
        self,
        project_id: str,
        panel_number: int,
        panel: Dict[str, Any],
        narrator_voice_id: Optional[str] = None,
        narrator_voice_name: Optional[str] = None,
        voice_settings: Optional[VoiceSettings] = None
    ) -> MultiSpeakerPanelAudio:
        """
        Generate all audio segments for a multi-speaker panel.

        Args:
            project_id: Project UUID
            panel_number: Panel number
            panel: Panel dict with segments array
            narrator_voice_id: Voice ID for narrator segments
            narrator_voice_name: Voice name for narrator segments
            voice_settings: Optional voice settings

        Returns:
            MultiSpeakerPanelAudio with all segments generated
        """
        # Extract segments from panel
        raw_segments = self.extract_panel_segments(panel)
        if not raw_segments:
            raise ValueError(f"Panel {panel_number} has no segments")

        # Create AudioSegment objects
        segments = []
        for i, seg_data in enumerate(raw_segments):
            segment = AudioSegment(
                segment_index=i,
                speaker=seg_data["speaker"],
                text=seg_data["text"],
                pause_after_ms=300  # Default pause
            )
            segments.append(segment)

        # Generate audio for each segment
        generated_segments = []
        for segment in segments:
            gen_segment = await self.generate_segment_audio(
                project_id=project_id,
                panel_number=panel_number,
                segment=segment,
                narrator_voice_id=narrator_voice_id,
                narrator_voice_name=narrator_voice_name,
                voice_settings=voice_settings
            )
            generated_segments.append(gen_segment)

        # Create multi-speaker audio object
        multi_audio = MultiSpeakerPanelAudio(
            panel_number=panel_number,
            segments=generated_segments,
            is_approved=False
        )

        # Combine segments with pauses
        combined_audio = await self.combine_segments_with_pauses(
            project_id=project_id,
            panel_number=panel_number,
            segments=generated_segments
        )

        # Update with combined audio info
        multi_audio = multi_audio.model_copy(update={
            "combined_audio_url": combined_audio["url"],
            "total_duration_ms": combined_audio["duration_ms"]
        })

        # Save to database
        await self._save_multi_speaker_audio(project_id, multi_audio)

        logger.info(
            f"Generated multi-speaker audio for panel {panel_number}: "
            f"{len(generated_segments)} segments, {multi_audio.total_duration_ms}ms total"
        )

        return multi_audio

    async def combine_segments_with_pauses(
        self,
        project_id: str,
        panel_number: int,
        segments: List[AudioSegment]
    ) -> Dict[str, Any]:
        """
        Combine audio segments with pauses between them.

        Uses FFmpeg to concatenate segments with silence pauses.

        Args:
            project_id: Project UUID
            panel_number: Panel number
            segments: List of AudioSegment with audio_url set

        Returns:
            Dict with 'url' and 'duration_ms' of combined audio
        """
        if not segments:
            raise ValueError("No segments to combine")

        project_dir = self.output_base / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Download segment audio files locally
        segment_paths = []
        for seg in segments:
            if not seg.audio_url:
                raise ValueError(f"Segment {seg.segment_index} has no audio URL")

            # Get signed URL for download
            signed_url = await self.get_audio_url(seg.audio_url)

            # Download to local path
            local_path = project_dir / f"seg_{seg.segment_index}_temp.mp3"
            await self._download_audio_file(signed_url, local_path)
            segment_paths.append(local_path)

        # Build pause durations (all except last segment)
        pauses = [seg.pause_after_ms for seg in segments[:-1]]

        # Combine using FFmpeg
        output_filename = f"{panel_number:02d}_combined.mp3"
        output_path = project_dir / output_filename

        await asyncio.to_thread(
            self._concatenate_with_pauses,
            segment_paths,
            pauses,
            output_path
        )

        # Get total duration
        total_duration = await asyncio.to_thread(
            self.ffmpeg.get_duration_ms, output_path
        )

        # Upload combined file
        combined_url = await self._upload_audio(
            project_id=project_id,
            filename=output_filename,
            local_path=output_path
        )

        # Cleanup temp files
        for path in segment_paths:
            try:
                path.unlink()
            except Exception:
                pass

        return {
            "url": combined_url,
            "duration_ms": total_duration
        }

    def _concatenate_with_pauses(
        self,
        segment_paths: List[Path],
        pauses: List[int],
        output_path: Path
    ) -> None:
        """
        Concatenate audio segments with silence pauses.

        Args:
            segment_paths: Local paths to segment audio files
            pauses: Pause durations in ms between segments
            output_path: Output file path
        """
        import subprocess

        if len(segment_paths) == 1:
            # Single segment, just copy
            import shutil
            shutil.copy(segment_paths[0], output_path)
            return

        # Build FFmpeg filter complex for concatenation with pauses
        # Format: [0:a][silence1][1:a][silence2]...[n:a]concat
        inputs = []
        filter_parts = []

        for i, seg_path in enumerate(segment_paths):
            inputs.extend(["-i", str(seg_path)])

        # Build filter complex
        filter_complex = []
        concat_inputs = []

        for i in range(len(segment_paths)):
            concat_inputs.append(f"[{i}:a]")

            # Add pause after (except for last segment)
            if i < len(pauses) and pauses[i] > 0:
                pause_sec = pauses[i] / 1000
                # Generate silence
                filter_complex.append(
                    f"anullsrc=r=44100:cl=stereo,atrim=0:{pause_sec}[pause{i}]"
                )
                concat_inputs.append(f"[pause{i}]")

        # Build concat filter
        concat_count = len(concat_inputs)
        filter_complex.append(
            f"{''.join(concat_inputs)}concat=n={concat_count}:v=0:a=1[out]"
        )

        full_filter = ";".join(filter_complex)

        # Run FFmpeg
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            str(output_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concatenation failed: {result.stderr}")

    # =========================================================================
    # Multi-Speaker Database Operations
    # =========================================================================

    async def _save_audio_segment(
        self,
        project_id: str,
        panel_number: int,
        segment: AudioSegment
    ) -> None:
        """Save audio segment to database."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio_segments").upsert({
                "project_id": project_id,
                "panel_number": panel_number,
                "segment_index": segment.segment_index,
                "speaker": segment.speaker,
                "text_content": segment.text,
                "voice_id": segment.voice_id,
                "voice_name": segment.voice_name,
                "audio_url": segment.audio_url,
                "duration_ms": segment.duration_ms,
                "pause_after_ms": segment.pause_after_ms
            }).execute()
        )

    async def _save_multi_speaker_audio(
        self,
        project_id: str,
        multi_audio: MultiSpeakerPanelAudio
    ) -> None:
        """Save multi-speaker audio to database."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_multi_speaker_audio").upsert({
                "project_id": project_id,
                "panel_number": multi_audio.panel_number,
                "combined_audio_url": multi_audio.combined_audio_url,
                "total_duration_ms": multi_audio.total_duration_ms,
                "is_approved": multi_audio.is_approved
            }).execute()
        )

    async def get_multi_speaker_audio(
        self,
        project_id: str,
        panel_number: int
    ) -> Optional[MultiSpeakerPanelAudio]:
        """
        Get multi-speaker audio for a panel.

        Args:
            project_id: Project UUID
            panel_number: Panel number

        Returns:
            MultiSpeakerPanelAudio or None if not found
        """
        # Get multi-speaker record
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_multi_speaker_audio")
                .select("*")
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .maybe_single()
                .execute()
        )

        if not result.data:
            return None

        # Get segments
        segments_result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio_segments")
                .select("*")
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .order("segment_index")
                .execute()
        )

        segments = []
        if segments_result and segments_result.data:
            segments = [
                AudioSegment(
                    segment_index=row["segment_index"],
                    speaker=row["speaker"],
                    text=row["text_content"],
                    voice_id=row.get("voice_id"),
                    voice_name=row.get("voice_name"),
                    audio_url=row.get("audio_url"),
                    duration_ms=row.get("duration_ms", 0),
                    pause_after_ms=row.get("pause_after_ms", 300)
                )
                for row in segments_result.data
            ]

        return MultiSpeakerPanelAudio(
            panel_number=panel_number,
            segments=segments,
            combined_audio_url=result.data.get("combined_audio_url"),
            total_duration_ms=result.data.get("total_duration_ms", 0),
            is_approved=result.data.get("is_approved", False)
        )

    async def update_segment_pause(
        self,
        project_id: str,
        panel_number: int,
        segment_index: int,
        pause_after_ms: int
    ) -> None:
        """
        Update pause duration for a segment.

        Args:
            project_id: Project UUID
            panel_number: Panel number
            segment_index: Segment index
            pause_after_ms: New pause duration
        """
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_audio_segments")
                .update({"pause_after_ms": pause_after_ms})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .eq("segment_index", segment_index)
                .execute()
        )
        logger.info(
            f"Updated pause for segment {segment_index} panel {panel_number}: {pause_after_ms}ms"
        )

    async def regenerate_combined_audio(
        self,
        project_id: str,
        panel_number: int
    ) -> MultiSpeakerPanelAudio:
        """
        Regenerate combined audio with updated pauses.

        Use after updating segment pauses.

        Args:
            project_id: Project UUID
            panel_number: Panel number

        Returns:
            Updated MultiSpeakerPanelAudio
        """
        # Get existing multi-speaker audio
        existing = await self.get_multi_speaker_audio(project_id, panel_number)
        if not existing:
            raise ValueError(f"No multi-speaker audio for panel {panel_number}")

        # Recombine with current pause settings
        combined = await self.combine_segments_with_pauses(
            project_id=project_id,
            panel_number=panel_number,
            segments=existing.segments
        )

        # Update record
        updated = existing.model_copy(update={
            "combined_audio_url": combined["url"],
            "total_duration_ms": combined["duration_ms"]
        })

        await self._save_multi_speaker_audio(project_id, updated)

        logger.info(f"Regenerated combined audio for panel {panel_number}")
        return updated
