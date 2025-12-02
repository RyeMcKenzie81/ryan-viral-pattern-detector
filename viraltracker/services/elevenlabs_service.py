"""
ElevenLabs Text-to-Speech Service

Handles all interactions with ElevenLabs API for voice generation.

IMPORTANT: Following Section 19 guidelines:
- Direction tags are NOT sent to ElevenLabs (they would be spoken)
- Pauses are added via FFmpeg post-processing (more reliable)
- Speed range: 0.7 to 1.2

Follows existing service patterns in the codebase.
"""

import logging
import httpx
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import os

from .audio_models import (
    VoiceSettings,
    CharacterVoiceProfile,
    ScriptBeat,
    AudioTake,
    Character
)
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ElevenLabsService:
    """Service for generating audio via ElevenLabs API"""

    BASE_URL = "https://api.elevenlabs.io/v1"
    MODEL_ID = "eleven_turbo_v2_5"  # Fast, high-quality model

    # ElevenLabs API limits
    MIN_SPEED = 0.7
    MAX_SPEED = 1.2

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize ElevenLabs service.

        Args:
            api_key: ElevenLabs API key (defaults to env var)
        """
        self.api_key = api_key or os.getenv('ELEVENLABS_API_KEY', '')
        self._client: Optional[httpx.AsyncClient] = None
        self._voice_profiles: Dict[Character, CharacterVoiceProfile] = {}
        self._profiles_loaded = False

        if not self.api_key:
            logger.warning("ElevenLabs API key not configured")
        else:
            logger.info("ElevenLabsService initialized")

    @property
    def enabled(self) -> bool:
        """Check if service is enabled"""
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                timeout=60.0
            )
        return self._client

    async def load_voice_profiles(self) -> Dict[Character, CharacterVoiceProfile]:
        """
        Load character voice profiles from database.

        Voice IDs and settings are stored in the database, so scripts
        only need to reference character names like [CHARACTER: boomer].

        Returns:
            Dict mapping Character enum to CharacterVoiceProfile
        """
        if self._profiles_loaded:
            return self._voice_profiles

        db = get_supabase_client()

        # Run sync Supabase call in thread
        result = await asyncio.to_thread(
            lambda: db.table("character_voice_profiles").select("*").execute()
        )

        for row in result.data:
            try:
                char = Character(row["character"])
            except ValueError:
                logger.warning(f"Unknown character in database: {row['character']}")
                continue

            self._voice_profiles[char] = CharacterVoiceProfile(
                id=row["id"],
                character=char,
                voice_id=row["voice_id"],
                display_name=row["display_name"],
                description=row.get("description"),
                stability=row["stability"],
                similarity_boost=row["similarity_boost"],
                style=row["style"],
                speed=row["speed"]
            )

        self._profiles_loaded = True
        logger.info(f"Loaded {len(self._voice_profiles)} voice profiles")
        return self._voice_profiles

    async def get_voice_profile(self, character: Character) -> CharacterVoiceProfile:
        """
        Get voice profile for a character.

        Args:
            character: Character enum value

        Returns:
            CharacterVoiceProfile for the character

        Raises:
            ValueError: If no profile exists for character
        """
        await self.load_voice_profiles()

        if character not in self._voice_profiles:
            raise ValueError(
                f"No voice profile configured for character: {character.value}"
            )

        return self._voice_profiles[character]

    def _clamp_speed(self, speed: float) -> float:
        """Clamp speed to ElevenLabs API limits (0.7 - 1.2)"""
        return max(self.MIN_SPEED, min(self.MAX_SPEED, speed))

    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        settings: VoiceSettings,
        output_path: Path
    ) -> Dict[str, Any]:
        """
        Generate speech audio from text.

        NOTE: We send clean text only - no direction tags, no SSML.
        Pauses are added via FFmpeg post-processing for reliability.

        Args:
            text: Clean text to speak (no SSML, no direction tags)
            voice_id: ElevenLabs voice ID
            settings: Voice generation settings
            output_path: Where to save the audio file

        Returns:
            Dict with generation metadata

        Raises:
            RuntimeError: If service is not configured
            httpx.HTTPStatusError: If API request fails
        """
        if not self.enabled:
            raise RuntimeError("ElevenLabs service not configured")

        client = await self._get_client()

        # Build API payload
        payload = {
            "text": text,
            "model_id": self.MODEL_ID,
            "voice_settings": {
                "stability": settings.stability,
                "similarity_boost": settings.similarity_boost,
                "style": settings.style,
                "use_speaker_boost": True
            }
        }

        # Speed is a top-level parameter in ElevenLabs API
        clamped_speed = self._clamp_speed(settings.speed)
        if clamped_speed != 1.0:
            payload["speed"] = clamped_speed

        logger.debug(f"Generating speech: {len(text)} chars, speed={clamped_speed}")

        # Make API request
        response = await client.post(
            f"{self.BASE_URL}/text-to-speech/{voice_id}",
            json=payload
        )
        response.raise_for_status()

        # Save audio file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

        logger.info(f"Generated audio: {output_path}")

        return {
            "output_path": str(output_path),
            "text_length": len(text),
            "settings": settings.model_dump()
        }

    async def generate_beat_audio(
        self,
        beat: ScriptBeat,
        output_dir: Path,
        session_id: str
    ) -> AudioTake:
        """
        Generate audio for a single beat.

        Looks up character's voice profile from database,
        merges with beat-specific settings, generates audio.

        Args:
            beat: The script beat to generate
            output_dir: Directory for audio files
            session_id: Production session ID

        Returns:
            AudioTake with file path and metadata
        """
        # Get character's voice profile
        profile = await self.get_voice_profile(beat.character)

        # Merge settings: beat override > character default
        base_settings = profile.to_voice_settings()

        if beat.settings_override:
            settings = VoiceSettings(
                stability=beat.settings_override.stability or base_settings.stability,
                similarity_boost=base_settings.similarity_boost,
                style=beat.settings_override.style or base_settings.style,
                speed=self._clamp_speed(
                    beat.settings_override.speed or base_settings.speed
                )
            )
        else:
            # Apply pace from beat
            settings = VoiceSettings(
                stability=base_settings.stability,
                similarity_boost=base_settings.similarity_boost,
                style=base_settings.style,
                speed=self._clamp_speed(beat.primary_pace.to_speed())
            )

        # Generate unique take ID (full UUID for database)
        take_id = str(uuid.uuid4())
        filename = f"{beat.beat_id}_{take_id}.mp3"
        output_path = output_dir / filename

        # Generate audio (clean text, no SSML)
        await self.generate_speech(
            text=beat.combined_script,
            voice_id=profile.voice_id,
            settings=settings,
            output_path=output_path
        )

        return AudioTake(
            take_id=take_id,
            beat_id=beat.beat_id,
            audio_path=str(output_path),
            audio_duration_ms=0,  # Will be set by FFmpeg
            generation_settings=settings,
            direction_used=beat.primary_direction,
            created_at=datetime.utcnow(),
            is_selected=False
        )

    async def get_usage(self) -> Dict[str, Any]:
        """
        Get ElevenLabs account usage information.

        Returns:
            Dict with character_count, character_limit, etc.
        """
        if not self.enabled:
            return {"error": "Service not configured"}

        client = await self._get_client()

        try:
            response = await client.get(f"{self.BASE_URL}/user/subscription")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get usage: {e}")
            return {"error": str(e)}

    async def list_voices(self) -> Dict[str, Any]:
        """
        List available ElevenLabs voices.

        Returns:
            Dict with voice information
        """
        if not self.enabled:
            return {"error": "Service not configured"}

        client = await self._get_client()

        try:
            response = await client.get(f"{self.BASE_URL}/voices")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            return {"error": str(e)}

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.debug("ElevenLabs HTTP client closed")
