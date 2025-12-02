"""
Audio Production Models

Pydantic models for the ElevenLabs audio production workflow.
Following existing codebase patterns from services/models.py.

Models include:
- Character/Voice profile configuration
- ELS script parsing structures
- Audio generation and production session management
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
from uuid import UUID


# ============================================================================
# Core Enums
# ============================================================================

class Character(str, Enum):
    """Available character voices for Trash Panda"""
    EVERY_COON = "every-coon"
    BOOMER = "boomer"
    FED = "fed"
    WHALE = "whale"
    WOJAK = "wojak"
    CHAD = "chad"


class Pace(str, Enum):
    """Pacing options mapped to ElevenLabs speed values (API range: 0.7-1.2)"""
    SLOW = "slow"           # 0.75x
    DELIBERATE = "deliberate"  # 0.85x
    NORMAL = "normal"       # 1.00x
    QUICK = "quick"         # 1.08x
    FAST = "fast"           # 1.15x
    CHAOS = "chaos"         # 1.20x

    def to_speed(self) -> float:
        """Convert pace to ElevenLabs speed parameter"""
        mapping = {
            "slow": 0.75,
            "deliberate": 0.85,
            "normal": 1.00,
            "quick": 1.08,
            "fast": 1.15,
            "chaos": 1.20
        }
        return mapping.get(self.value, 1.0)


# ============================================================================
# Voice Settings Models
# ============================================================================

class VoiceSettings(BaseModel):
    """ElevenLabs voice generation settings"""
    stability: float = Field(default=0.35, ge=0, le=1, description="Voice stability (0-1)")
    similarity_boost: float = Field(default=0.78, ge=0, le=1, description="Voice similarity boost (0-1)")
    style: float = Field(default=0.45, ge=0, le=1, description="Voice style exaggeration (0-1)")
    speed: float = Field(default=1.0, ge=0.7, le=1.2, description="Speech speed (0.7-1.2)")


class CharacterVoiceProfile(BaseModel):
    """Voice profile for a character, stored in database"""
    id: Optional[UUID] = None
    character: Character
    voice_id: str = Field(..., description="ElevenLabs voice ID")
    display_name: str = Field(..., description="Display name for UI")
    description: Optional[str] = Field(None, description="Character description")
    stability: float = Field(default=0.35, ge=0, le=1)
    similarity_boost: float = Field(default=0.78, ge=0, le=1)
    style: float = Field(default=0.45, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)

    def to_voice_settings(self) -> VoiceSettings:
        """Convert profile to VoiceSettings"""
        return VoiceSettings(
            stability=self.stability,
            similarity_boost=self.similarity_boost,
            style=self.style,
            speed=self.speed
        )


# ============================================================================
# ELS Script Parsing Models
# ============================================================================

class ParsedLine(BaseModel):
    """A single parsed line from ELS format"""
    text: str = Field(..., description="The text content to speak")
    direction: Optional[str] = Field(None, description="Acting direction (not sent to ElevenLabs)")
    pace: Pace = Field(default=Pace.NORMAL, description="Pacing for this line")
    pause_after_ms: int = Field(default=150, ge=0, le=2000, description="Pause after line in ms")
    stability_override: Optional[float] = Field(None, ge=0, le=1, description="Override stability")
    style_override: Optional[float] = Field(None, ge=0, le=1, description="Override style")
    emphasis_words: List[str] = Field(default_factory=list, description="Words with single emphasis")
    strong_emphasis_words: List[str] = Field(default_factory=list, description="Words with strong emphasis")


class ScriptBeat(BaseModel):
    """A beat ready for audio generation"""
    beat_id: str = Field(..., description="Beat identifier (e.g., '01_hook')")
    beat_number: int = Field(..., ge=0, description="Beat sequence number")
    beat_name: str = Field(..., description="Beat display name (e.g., 'Hook')")
    character: Character = Field(..., description="Character speaking this beat")
    lines: List[ParsedLine] = Field(default_factory=list, description="Parsed script lines")
    combined_script: str = Field(..., description="All lines joined for generation")
    primary_direction: Optional[str] = Field(None, description="Primary acting direction")
    primary_pace: Pace = Field(default=Pace.NORMAL, description="Primary pace for beat")
    settings_override: Optional[VoiceSettings] = Field(None, description="Voice settings override")
    pause_after_ms: int = Field(default=300, ge=0, le=2000, description="Pause after beat in ms")


# ============================================================================
# Audio Take & Session Models
# ============================================================================

class AudioTake(BaseModel):
    """A single generated audio take"""
    take_id: str = Field(..., description="Unique take identifier")
    beat_id: str = Field(..., description="Associated beat ID")
    audio_path: str = Field(..., description="File path to audio")
    audio_duration_ms: int = Field(default=0, ge=0, description="Audio duration in ms")
    generation_settings: VoiceSettings = Field(..., description="Settings used for generation")
    direction_used: Optional[str] = Field(None, description="Direction used for generation")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When take was created")
    is_selected: bool = Field(default=False, description="Whether this take is selected for export")


class BeatWithTakes(BaseModel):
    """A beat with all its generated takes"""
    beat: ScriptBeat = Field(..., description="The script beat")
    takes: List[AudioTake] = Field(default_factory=list, description="Generated takes for this beat")
    selected_take_id: Optional[str] = Field(None, description="Currently selected take ID")


class ProductionSession(BaseModel):
    """A full audio production session"""
    session_id: str = Field(..., description="Session UUID")
    video_title: str = Field(..., description="Title of the video")
    project_name: str = Field(..., description="Project name (e.g., 'trash-panda')")
    beats: List[BeatWithTakes] = Field(default_factory=list, description="All beats with takes")
    source_els: Optional[str] = Field(None, description="Original ELS script content")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Session creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    status: str = Field(
        default="draft",
        description="Session status: draft, generating, in_progress, completed, exported"
    )


# ============================================================================
# Validation & Result Models
# ============================================================================

class ELSValidationResult(BaseModel):
    """Result of ELS format validation"""
    is_valid: bool = Field(..., description="Whether script is valid")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    beat_count: int = Field(default=0, ge=0, description="Number of beats found")
    character_count: Dict[str, int] = Field(default_factory=dict, description="Lines per character")


class ELSParseResult(BaseModel):
    """Result of ELS parsing"""
    video_title: str = Field(..., description="Video title from META block")
    project: str = Field(..., description="Project name from META block")
    default_character: Character = Field(default=Character.EVERY_COON, description="Default character")
    default_pace: Pace = Field(default=Pace.NORMAL, description="Default pace")
    beats: List[ScriptBeat] = Field(default_factory=list, description="Parsed beats")


class AudioGenerationResult(BaseModel):
    """Result of complete audio workflow"""
    session_id: str = Field(..., description="Production session ID")
    video_title: str = Field(..., description="Video title")
    status: str = Field(..., description="Workflow status")
    beats: List[Dict[str, Any]] = Field(default_factory=list, description="Generated beat data")
    total_duration_ms: int = Field(default=0, ge=0, description="Total audio duration in ms")
    summary: str = Field(..., description="Human-readable summary")
