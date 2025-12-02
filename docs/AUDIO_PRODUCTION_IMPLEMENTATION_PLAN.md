# 🎙️ ElevenLabs Audio Production Workflow — Implementation Plan

**Version**: 1.0
**Date**: 2025-12-01
**Branch**: `feature/audio-production`
**Status**: Ready for Implementation

---

## Table of Contents

1. [Workflow Overview](#workflow-overview)
2. [Step-by-Step Tool Flow](#step-by-step-tool-flow)
3. [Phase 1: Data Models](#phase-1-data-models)
4. [Phase 2: Database Migration](#phase-2-database-migration)
5. [Phase 3: FFmpeg Service](#phase-3-ffmpeg-service)
6. [Phase 4: ELS Parser Service](#phase-4-els-parser-service)
7. [Phase 5: ElevenLabs Service](#phase-5-elevenlabs-service)
8. [Phase 6: Audio Production Service](#phase-6-audio-production-service)
9. [Phase 7: Pydantic AI Agent & Tools](#phase-7-pydantic-ai-agent--tools)
10. [Phase 8: Orchestration Workflow](#phase-8-orchestration-workflow)
11. [Phase 9: Streamlit UI](#phase-9-streamlit-ui)
12. [Phase 10: Integration](#phase-10-integration)
13. [File Summary](#file-summary)

---

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUDIO PRODUCTION WORKFLOW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. USER INPUT                                                              │
│     └── Paste/Upload ELS Script                                             │
│                                                                             │
│  2. VALIDATION & PARSING                                                    │
│     └── Validate ELS format → Parse into ScriptBeat objects                 │
│                                                                             │
│  3. SESSION CREATION                                                        │
│     └── Create production session in database                               │
│                                                                             │
│  4. AUDIO GENERATION (per beat)                                             │
│     ├── Load character voice profile from database                          │
│     ├── Send clean text to ElevenLabs API                                   │
│     ├── Add pauses via FFmpeg post-processing                               │
│     └── Save take to database & storage                                     │
│                                                                             │
│  5. REVIEW & SELECTION                                                      │
│     ├── Play/compare takes                                                  │
│     ├── Regenerate with different settings                                  │
│     └── Select best take per beat                                           │
│                                                                             │
│  6. EXPORT                                                                  │
│     └── Export selected takes: 01_hook.mp3, 02_setup.mp3, etc.              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Tool Flow

This section shows exactly what happens when `complete_audio_workflow()` is called.

### Tool Execution Sequence

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ complete_audio_workflow(els_content, project_name)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ STEP 1: validate_els_script                                                 │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  els_content (string)                                                │
│ Output: {                                                                   │
│           "is_valid": true,                                                 │
│           "beat_count": 8,                                                  │
│           "character_count": {"every-coon": 6, "boomer": 2},                │
│           "warnings": [],                                                   │
│           "errors": []                                                      │
│         }                                                                   │
│                                                                             │
│ STEP 2: parse_els_script                                                    │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  els_content (string)                                                │
│ Output: {                                                                   │
│           "video_title": "Shrinkflation 2.0",                               │
│           "project": "trash-panda",                                         │
│           "beats": [                                                        │
│             {                                                               │
│               "beat_id": "01_hook",                                         │
│               "beat_name": "Hook",                                          │
│               "character": "every-coon",                                    │
│               "lines": [                                                    │
│                 {"text": "Corporation stole your chips.", "pause_after_ms": 50},
│                 {"text": "Bag look same.", "pause_after_ms": 50},           │
│                 {"text": "Bag not same.", "pause_after_ms": 100},           │
│                 {"text": "You got scammed.", "pause_after_ms": 100}         │
│               ],                                                            │
│               "combined_script": "Corporation stole your chips. ...",       │
│               "primary_direction": "Punchy, accusatory, deadpan",           │
│               "primary_pace": "fast",                                       │
│               "pause_after_ms": 300                                         │
│             },                                                              │
│             ...                                                             │
│           ]                                                                 │
│         }                                                                   │
│                                                                             │
│ STEP 3: create_production_session                                           │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  video_title, project_name, beats[]                                  │
│ Output: {                                                                   │
│           "session_id": "uuid-here",                                        │
│           "status": "draft",                                                │
│           "beat_count": 8                                                   │
│         }                                                                   │
│                                                                             │
│ STEP 4: get_voice_profile (called per unique character)                     │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  character_name ("every-coon")                                       │
│ Output: {                                                                   │
│           "character": "every-coon",                                        │
│           "voice_id": "BRruTxiLM2nszrcCIpz1",                               │
│           "display_name": "Every-Coon",                                     │
│           "stability": 0.35,                                                │
│           "similarity_boost": 0.78,                                         │
│           "style": 0.45,                                                    │
│           "speed": 1.00                                                     │
│         }                                                                   │
│                                                                             │
│ STEP 5: generate_beat_audio (called per beat, sequentially)                 │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  session_id, beat (ScriptBeat object)                                │
│ Process:                                                                    │
│   1. Get voice profile for beat.character                                   │
│   2. Merge beat settings with profile defaults                              │
│   3. Call ElevenLabs API with clean text (no SSML)                          │
│   4. Save raw audio to temp file                                            │
│   5. Call FFmpeg to add pauses between lines                                │
│   6. Save final audio to storage                                            │
│   7. Get duration via FFmpeg                                                │
│   8. Save take to database                                                  │
│ Output: {                                                                   │
│           "take_id": "abc123",                                              │
│           "beat_id": "01_hook",                                             │
│           "audio_path": "audio-production/{session_id}/01_hook_abc123.mp3", │
│           "audio_duration_ms": 4200,                                        │
│           "settings_used": {"stability": 0.35, "style": 0.45, "speed": 1.15}│
│         }                                                                   │
│                                                                             │
│ STEP 6: update_session_status                                               │
│ ────────────────────────────────────────────────────────────────────────── │
│ Input:  session_id, status="in_progress"                                    │
│ Output: {"success": true}                                                   │
│                                                                             │
│ FINAL OUTPUT                                                                │
│ ────────────────────────────────────────────────────────────────────────── │
│ {                                                                           │
│   "session_id": "uuid-here",                                                │
│   "video_title": "Shrinkflation 2.0",                                       │
│   "status": "in_progress",                                                  │
│   "beats": [                                                                │
│     {                                                                       │
│       "beat_id": "01_hook",                                                 │
│       "beat_name": "Hook",                                                  │
│       "character": "every-coon",                                            │
│       "takes": [{"take_id": "abc123", "duration_ms": 4200, ...}],           │
│       "selected_take_id": "abc123"                                          │
│     },                                                                      │
│     ...                                                                     │
│   ],                                                                        │
│   "total_duration_ms": 45000,                                               │
│   "summary": "Generated 8 beats, 45 seconds total audio"                    │
│ }                                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Regeneration Flow (User clicks "Revise" on a beat)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ regenerate_beat_audio(session_id, beat_id, new_settings)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Input: {                                                                    │
│   "session_id": "uuid",                                                     │
│   "beat_id": "01_hook",                                                     │
│   "new_direction": "More sarcastic, slower buildup",                        │
│   "new_pace": "deliberate",                                                 │
│   "stability": 0.30,                                                        │
│   "style": 0.55                                                             │
│ }                                                                           │
│                                                                             │
│ Process:                                                                    │
│   1. Load existing beat from session                                        │
│   2. Override settings with new values                                      │
│   3. Generate new audio (same flow as Step 5)                               │
│   4. Save as new take (preserves old takes)                                 │
│                                                                             │
│ Output: {                                                                   │
│   "take_id": "def456",                                                      │
│   "beat_id": "01_hook",                                                     │
│   "audio_path": "audio-production/{session_id}/01_hook_def456.mp3",         │
│   "audio_duration_ms": 4800,                                                │
│   "settings_used": {"stability": 0.30, "style": 0.55, "speed": 0.85}        │
│ }                                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Export Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ export_selected_takes(session_id)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Input:  session_id                                                          │
│                                                                             │
│ Process:                                                                    │
│   1. Load session with all beats and selected takes                         │
│   2. For each beat with a selected take:                                    │
│      - Copy audio file with clean name: 01_hook.mp3, 02_setup.mp3, etc.     │
│   3. Update session status to "exported"                                    │
│                                                                             │
│ Output: {                                                                   │
│   "exported_files": [                                                       │
│     "01_hook.mp3",                                                          │
│     "02_setup.mp3",                                                         │
│     "03_chaos.mp3",                                                         │
│     ...                                                                     │
│   ],                                                                        │
│   "total_duration_ms": 45000,                                               │
│   "export_path": "exports/{session_id}/"                                    │
│ }                                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Data Models

**File**: `viraltracker/services/audio_models.py`

> **Note**: Models go in `services/` directory directly, not a subdirectory (matches existing `services/models.py` pattern)

```python
"""
Audio Production Models

Pydantic models for the ElevenLabs audio production workflow.
Following existing codebase patterns from services/models.py.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
from uuid import UUID


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


class VoiceSettings(BaseModel):
    """ElevenLabs voice generation settings"""
    stability: float = Field(default=0.35, ge=0, le=1)
    similarity_boost: float = Field(default=0.78, ge=0, le=1)
    style: float = Field(default=0.45, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)


class CharacterVoiceProfile(BaseModel):
    """Voice profile for a character, stored in database"""
    id: Optional[UUID] = None
    character: Character
    voice_id: str  # ElevenLabs voice ID
    display_name: str
    description: Optional[str] = None
    stability: float = 0.35
    similarity_boost: float = 0.78
    style: float = 0.45
    speed: float = 1.0

    def to_voice_settings(self) -> VoiceSettings:
        """Convert profile to VoiceSettings"""
        return VoiceSettings(
            stability=self.stability,
            similarity_boost=self.similarity_boost,
            style=self.style,
            speed=self.speed
        )


class ParsedLine(BaseModel):
    """A single parsed line from ELS format"""
    text: str
    direction: Optional[str] = None
    pace: Pace = Pace.NORMAL
    pause_after_ms: int = Field(default=150, ge=0, le=2000)
    stability_override: Optional[float] = None
    style_override: Optional[float] = None
    emphasis_words: List[str] = Field(default_factory=list)
    strong_emphasis_words: List[str] = Field(default_factory=list)


class ScriptBeat(BaseModel):
    """A beat ready for audio generation"""
    beat_id: str
    beat_number: int
    beat_name: str
    character: Character
    lines: List[ParsedLine]
    combined_script: str  # All lines joined for generation
    primary_direction: Optional[str] = None
    primary_pace: Pace = Pace.NORMAL
    settings_override: Optional[VoiceSettings] = None
    pause_after_ms: int = Field(default=300, ge=0, le=2000)


class AudioTake(BaseModel):
    """A single generated audio take"""
    take_id: str
    beat_id: str
    audio_path: str  # Storage path
    audio_duration_ms: int
    generation_settings: VoiceSettings
    direction_used: Optional[str] = None
    created_at: datetime
    is_selected: bool = False


class BeatWithTakes(BaseModel):
    """A beat with all its generated takes"""
    beat: ScriptBeat
    takes: List[AudioTake] = Field(default_factory=list)
    selected_take_id: Optional[str] = None


class ProductionSession(BaseModel):
    """A full audio production session"""
    session_id: str
    video_title: str
    project_name: str
    beats: List[BeatWithTakes]
    source_els: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    status: str = "draft"  # draft, generating, in_progress, completed, exported


class ELSValidationResult(BaseModel):
    """Result of ELS format validation"""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    beat_count: int = 0
    character_count: Dict[str, int] = Field(default_factory=dict)


class ELSParseResult(BaseModel):
    """Result of ELS parsing"""
    video_title: str
    project: str
    default_character: Character = Character.EVERY_COON
    default_pace: Pace = Pace.NORMAL
    beats: List[ScriptBeat]


class AudioGenerationResult(BaseModel):
    """Result of complete audio workflow"""
    session_id: str
    video_title: str
    status: str
    beats: List[Dict[str, Any]]
    total_duration_ms: int
    summary: str
```

---

## Phase 2: Database Migration

**File**: `migrations/2025_12_audio_production.sql`

```sql
-- =====================================================
-- AUDIO PRODUCTION WORKFLOW SCHEMA
-- =====================================================

-- Character voice profiles
-- Stores ElevenLabs voice IDs and default settings per character
CREATE TABLE IF NOT EXISTS character_voice_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    character VARCHAR(50) NOT NULL UNIQUE,
    voice_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    stability FLOAT DEFAULT 0.35 CHECK (stability >= 0 AND stability <= 1),
    similarity_boost FLOAT DEFAULT 0.78 CHECK (similarity_boost >= 0 AND similarity_boost <= 1),
    style FLOAT DEFAULT 0.45 CHECK (style >= 0 AND style <= 1),
    speed FLOAT DEFAULT 1.0 CHECK (speed >= 0.7 AND speed <= 1.2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Production sessions
CREATE TABLE IF NOT EXISTS audio_production_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_title VARCHAR(255) NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'generating', 'in_progress', 'completed', 'exported')),
    source_els TEXT,
    beats_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual audio takes
CREATE TABLE IF NOT EXISTS audio_takes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES audio_production_sessions(id) ON DELETE CASCADE,
    beat_id VARCHAR(100) NOT NULL,
    audio_path VARCHAR(500) NOT NULL,
    audio_duration_ms INT,
    settings_json JSONB NOT NULL,
    direction_used TEXT,
    is_selected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audio_sessions_project ON audio_production_sessions(project_name);
CREATE INDEX IF NOT EXISTS idx_audio_sessions_status ON audio_production_sessions(status);
CREATE INDEX IF NOT EXISTS idx_audio_takes_session ON audio_takes(session_id);
CREATE INDEX IF NOT EXISTS idx_audio_takes_session_beat ON audio_takes(session_id, beat_id);

-- =====================================================
-- SEED DATA: Trash Panda character profiles
-- All use same voice ID with different settings
-- =====================================================

INSERT INTO character_voice_profiles
(character, voice_id, display_name, description, stability, similarity_boost, style, speed)
VALUES
(
    'every-coon',
    'BRruTxiLM2nszrcCIpz1',
    'Every-Coon',
    'Main narrator. Deadpan curious raccoon. Confused but trying. Caveman speech pattern.',
    0.35, 0.78, 0.45, 1.0
),
(
    'boomer',
    'BRruTxiLM2nszrcCIpz1',
    'Boomer',
    'Old raccoon. Slow, grumbly, nostalgic. Slightly condescending.',
    0.50, 0.78, 0.30, 0.85
),
(
    'fed',
    'BRruTxiLM2nszrcCIpz1',
    'Fed',
    'Federal Reserve raccoon. Monotone, bureaucratic, completely detached.',
    0.65, 0.78, 0.20, 0.70
),
(
    'whale',
    'BRruTxiLM2nszrcCIpz1',
    'Whale',
    'Big money raccoon. Deep, confident, slightly menacing.',
    0.40, 0.78, 0.50, 0.95
),
(
    'wojak',
    'BRruTxiLM2nszrcCIpz1',
    'Wojak',
    'Panic raccoon. Whiny, panicked, defeated. Always losing.',
    0.30, 0.78, 0.60, 1.10
),
(
    'chad',
    'BRruTxiLM2nszrcCIpz1',
    'Chad',
    'Overconfident raccoon. Fast-talking, uses crypto slang. WAGMI energy.',
    0.40, 0.78, 0.55, 1.05
)
ON CONFLICT (character) DO UPDATE SET
    voice_id = EXCLUDED.voice_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    stability = EXCLUDED.stability,
    similarity_boost = EXCLUDED.similarity_boost,
    style = EXCLUDED.style,
    speed = EXCLUDED.speed,
    updated_at = NOW();

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_audio_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_voice_profiles_updated_at ON character_voice_profiles;
CREATE TRIGGER update_voice_profiles_updated_at
    BEFORE UPDATE ON character_voice_profiles
    FOR EACH ROW EXECUTE FUNCTION update_audio_updated_at_column();

DROP TRIGGER IF EXISTS update_audio_sessions_updated_at ON audio_production_sessions;
CREATE TRIGGER update_audio_sessions_updated_at
    BEFORE UPDATE ON audio_production_sessions
    FOR EACH ROW EXECUTE FUNCTION update_audio_updated_at_column();
```

---

## Phase 3: FFmpeg Service

**File**: `viraltracker/services/ffmpeg_service.py`

```python
"""
FFmpeg Service

Audio processing service using FFmpeg for:
- Getting audio duration
- Adding silence/pauses
- Concatenating audio files
- Future: pitch adjustment

Follows existing service patterns in the codebase.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional
import shutil

logger = logging.getLogger(__name__)


class FFmpegService:
    """Service for audio processing via FFmpeg"""

    def __init__(self):
        self._ffmpeg_path = self._find_ffmpeg()
        self._ffprobe_path = self._find_ffprobe()
        logger.info(f"FFmpegService initialized (ffmpeg: {self._ffmpeg_path})")

    def _find_ffmpeg(self) -> str:
        """Find ffmpeg executable"""
        path = shutil.which("ffmpeg")
        if not path:
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
        return path

    def _find_ffprobe(self) -> str:
        """Find ffprobe executable"""
        path = shutil.which("ffprobe")
        if not path:
            raise RuntimeError("FFprobe not found. Please install FFmpeg.")
        return path

    @property
    def available(self) -> bool:
        """Check if FFmpeg is available"""
        return bool(self._ffmpeg_path and self._ffprobe_path)

    def get_duration_ms(self, audio_path: Path) -> int:
        """
        Get audio duration in milliseconds.

        Args:
            audio_path: Path to audio file

        Returns:
            Duration in milliseconds
        """
        try:
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(audio_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            duration_sec = float(result.stdout.strip())
            return int(duration_sec * 1000)

        except (ValueError, subprocess.TimeoutExpired) as e:
            logger.error(f"Failed to get duration for {audio_path}: {e}")
            return 0

    def add_silence_after(
        self,
        input_path: Path,
        output_path: Path,
        silence_ms: int
    ) -> bool:
        """
        Add silence to the end of an audio file.

        Args:
            input_path: Source audio file
            output_path: Destination audio file
            silence_ms: Silence duration in milliseconds

        Returns:
            True if successful
        """
        try:
            silence_sec = silence_ms / 1000.0

            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",  # Overwrite output
                    "-i", str(input_path),
                    "-af", f"apad=pad_dur={silence_sec}",
                    "-acodec", "libmp3lame",
                    "-q:a", "2",
                    str(output_path)
                ],
                capture_output=True,
                timeout=60,
                check=True
            )

            logger.debug(f"Added {silence_ms}ms silence to {output_path}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to add silence: {e.stderr}")
            return False

    def concatenate_with_pauses(
        self,
        audio_segments: List[dict],
        output_path: Path
    ) -> bool:
        """
        Concatenate multiple audio segments with pauses between them.

        Args:
            audio_segments: List of {"path": Path, "pause_after_ms": int}
            output_path: Destination file

        Returns:
            True if successful
        """
        if not audio_segments:
            return False

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                processed_files = []

                for i, segment in enumerate(audio_segments):
                    src_path = segment["path"]
                    pause_ms = segment.get("pause_after_ms", 0)

                    if pause_ms > 0:
                        # Add silence to this segment
                        processed_path = tmpdir / f"segment_{i:03d}.mp3"
                        self.add_silence_after(src_path, processed_path, pause_ms)
                        processed_files.append(processed_path)
                    else:
                        processed_files.append(src_path)

                # Create concat file list
                concat_list = tmpdir / "concat.txt"
                with open(concat_list, "w") as f:
                    for pf in processed_files:
                        f.write(f"file '{pf}'\n")

                # Concatenate all files
                subprocess.run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_list),
                        "-acodec", "libmp3lame",
                        "-q:a", "2",
                        str(output_path)
                    ],
                    capture_output=True,
                    timeout=120,
                    check=True
                )

                logger.info(f"Concatenated {len(audio_segments)} segments to {output_path}")
                return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Concatenation failed: {e.stderr}")
            return False

    def generate_silence(self, output_path: Path, duration_ms: int) -> bool:
        """
        Generate a silent audio file.

        Args:
            output_path: Destination file
            duration_ms: Duration in milliseconds

        Returns:
            True if successful
        """
        try:
            duration_sec = duration_ms / 1000.0

            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=stereo:d={duration_sec}",
                    "-acodec", "libmp3lame",
                    "-q:a", "2",
                    str(output_path)
                ],
                capture_output=True,
                timeout=30,
                check=True
            )

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate silence: {e.stderr}")
            return False
```

---

## Phase 4: ELS Parser Service

**File**: `viraltracker/services/els_parser_service.py`

```python
"""
ElevenLabs Script (ELS) Parser Service

Parses the ELS markup format (Production Bible Section 19) into structured
beat data for audio generation.

ELS Format Example:
    [META]
    video_title: Shrinkflation 2.0
    project: trash-panda

    [BEAT: 01_hook]
    name: Hook
    ---
    [DIRECTION: Punchy, accusatory]
    [PACE: fast]
    Corporation stole your chips.
    [PAUSE: 50ms]
    [END_BEAT]
"""

import re
import logging
from typing import Optional, List, Dict

from .audio_models import (
    ScriptBeat,
    ParsedLine,
    Character,
    Pace,
    VoiceSettings,
    ELSValidationResult,
    ELSParseResult
)

logger = logging.getLogger(__name__)


class ELSParserService:
    """Parses ElevenLabs Script format into structured beats"""

    # Regex patterns
    META_PATTERN = re.compile(r'\[META\](.*?)(?=\[BEAT:|\Z)', re.DOTALL | re.IGNORECASE)
    BEAT_PATTERN = re.compile(
        r'\[BEAT:\s*([^\]]+)\]\s*\n\s*name:\s*([^\n]+)\s*\n\s*---\s*\n(.*?)\[END_BEAT\]',
        re.DOTALL | re.IGNORECASE
    )

    TAG_PATTERNS = {
        'character': re.compile(r'\[CHARACTER:\s*([^\]]+)\]', re.IGNORECASE),
        'direction': re.compile(r'\[DIRECTION:\s*([^\]]+)\]', re.IGNORECASE),
        'pace': re.compile(r'\[PACE:\s*([^\]]+)\]', re.IGNORECASE),
        'pause': re.compile(r'\[PAUSE:\s*([^\]]+)\]', re.IGNORECASE),
        'stability': re.compile(r'\[STABILITY:\s*([^\]]+)\]', re.IGNORECASE),
        'style': re.compile(r'\[STYLE:\s*([^\]]+)\]', re.IGNORECASE),
    }

    EMPHASIS_PATTERN = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
    STRONG_EMPHASIS_PATTERN = re.compile(r'\*\*([^*]+)\*\*')

    PAUSE_VALUES = {
        'beat': 150,
        'short': 250,
        'medium': 400,
        'long': 600,
        'dramatic': 900,
    }

    CHARACTER_MAP = {
        'every-coon': Character.EVERY_COON,
        'everycoon': Character.EVERY_COON,
        'boomer': Character.BOOMER,
        'fed': Character.FED,
        'whale': Character.WHALE,
        'wojak': Character.WOJAK,
        'chad': Character.CHAD,
    }

    PACE_MAP = {
        'slow': Pace.SLOW,
        'deliberate': Pace.DELIBERATE,
        'normal': Pace.NORMAL,
        'quick': Pace.QUICK,
        'fast': Pace.FAST,
        'chaos': Pace.CHAOS,
    }

    def __init__(self):
        self.video_title: str = ""
        self.project: str = ""
        self.default_character = Character.EVERY_COON
        self.default_pace = Pace.NORMAL
        logger.info("ELSParserService initialized")

    def validate(self, content: str) -> ELSValidationResult:
        """
        Validate ELS content without parsing.

        Args:
            content: ELS script content

        Returns:
            ELSValidationResult with errors and warnings
        """
        errors = []
        warnings = []
        beat_count = 0
        character_counts: Dict[str, int] = {}

        # Check META block
        if '[META]' not in content.upper():
            errors.append("Missing [META] block at start of file")

        # Check beat structure
        beat_starts = len(re.findall(r'\[BEAT:', content, re.IGNORECASE))
        beat_ends = len(re.findall(r'\[END_BEAT\]', content, re.IGNORECASE))

        if beat_starts == 0:
            errors.append("No [BEAT:] blocks found")
        elif beat_starts != beat_ends:
            errors.append(f"Mismatched beats: {beat_starts} [BEAT:] but {beat_ends} [END_BEAT]")
        else:
            beat_count = beat_starts

        # Check characters
        for match in self.TAG_PATTERNS['character'].finditer(content):
            char_name = match.group(1).strip().lower()
            if char_name not in self.CHARACTER_MAP:
                errors.append(f"Unknown character: '{char_name}' (valid: {', '.join(self.CHARACTER_MAP.keys())})")

        # Check paces
        for match in self.TAG_PATTERNS['pace'].finditer(content):
            pace_name = match.group(1).strip().lower()
            if pace_name not in self.PACE_MAP:
                errors.append(f"Unknown pace: '{pace_name}' (valid: {', '.join(self.PACE_MAP.keys())})")

        # Check line lengths and count characters
        current_char = 'every-coon'
        for match in self.BEAT_PATTERN.finditer(content):
            beat_id = match.group(1).strip()
            beat_content = match.group(3)

            line_num = 0
            for line in beat_content.split('\n'):
                line = line.strip()
                if not line or line.startswith('['):
                    # Check for character switch
                    char_match = self.TAG_PATTERNS['character'].search(line)
                    if char_match:
                        current_char = char_match.group(1).strip().lower()
                    continue

                line_num += 1

                # Remove tags for length check
                clean = re.sub(r'\[[^\]]+\]', '', line).strip()
                if len(clean) > 500:
                    errors.append(f"Beat '{beat_id}' line {line_num}: exceeds 500 chars ({len(clean)})")

                # Count characters
                if current_char not in character_counts:
                    character_counts[current_char] = 0
                character_counts[current_char] += 1

        # Warnings
        if beat_count > 50:
            warnings.append(f"Large script: {beat_count} beats may take a while to generate")

        meta_match = self.META_PATTERN.search(content)
        if meta_match:
            meta_content = meta_match.group(1)
            if 'video_title:' not in meta_content.lower():
                warnings.append("No video_title in [META] block")
            if 'project:' not in meta_content.lower():
                warnings.append("No project in [META] block")

        return ELSValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            beat_count=beat_count,
            character_count=character_counts
        )

    def parse(self, content: str) -> ELSParseResult:
        """
        Parse ELS content into structured data.

        Args:
            content: ELS script content

        Returns:
            ELSParseResult with video title, project, and beats

        Raises:
            ValueError: If content is invalid
        """
        validation = self.validate(content)
        if not validation.is_valid:
            raise ValueError(f"Invalid ELS content: {'; '.join(validation.errors)}")

        self._parse_meta(content)
        beats = self._parse_beats(content)

        return ELSParseResult(
            video_title=self.video_title,
            project=self.project,
            default_character=self.default_character,
            default_pace=self.default_pace,
            beats=beats
        )

    def _parse_meta(self, content: str) -> None:
        """Extract metadata from [META] block"""
        match = self.META_PATTERN.search(content)
        if not match:
            return

        for line in match.group(1).strip().split('\n'):
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()

            if key == 'video_title':
                self.video_title = value
            elif key == 'project':
                self.project = value
            elif key == 'default_character':
                self.default_character = self.CHARACTER_MAP.get(value.lower(), Character.EVERY_COON)
            elif key == 'default_pace':
                self.default_pace = self.PACE_MAP.get(value.lower(), Pace.NORMAL)

    def _parse_beats(self, content: str) -> List[ScriptBeat]:
        """Parse all beat blocks"""
        beats = []

        for match in self.BEAT_PATTERN.finditer(content):
            beat_id = match.group(1).strip()
            beat_name = match.group(2).strip()
            beat_content = match.group(3)

            beat = self._parse_beat_content(beat_id, beat_name, beat_content)
            if beat:
                beats.append(beat)

        return beats

    def _parse_beat_content(self, beat_id: str, name: str, content: str) -> Optional[ScriptBeat]:
        """Parse content of a single beat"""
        lines: List[ParsedLine] = []

        # State
        current_character = self.default_character
        current_direction: Optional[str] = None
        current_pace = self.default_pace
        current_stability: Optional[float] = None
        current_style: Optional[float] = None
        final_pause = 300

        for raw_line in content.split('\n'):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Process tags
            if raw_line.startswith('['):
                # CHARACTER
                match = self.TAG_PATTERNS['character'].search(raw_line)
                if match:
                    char_name = match.group(1).strip().lower()
                    current_character = self.CHARACTER_MAP.get(char_name, current_character)
                    continue

                # DIRECTION
                match = self.TAG_PATTERNS['direction'].search(raw_line)
                if match:
                    current_direction = match.group(1).strip()
                    continue

                # PACE
                match = self.TAG_PATTERNS['pace'].search(raw_line)
                if match:
                    pace_name = match.group(1).strip().lower()
                    current_pace = self.PACE_MAP.get(pace_name, current_pace)
                    continue

                # Standalone PAUSE
                match = self.TAG_PATTERNS['pause'].search(raw_line)
                if match and raw_line.strip() == match.group(0):
                    pause_val = self._parse_pause(match.group(1))
                    final_pause = pause_val
                    if lines:
                        lines[-1].pause_after_ms = pause_val
                    continue

                # STABILITY
                match = self.TAG_PATTERNS['stability'].search(raw_line)
                if match:
                    try:
                        current_stability = float(match.group(1).strip())
                    except ValueError:
                        pass
                    continue

                # STYLE
                match = self.TAG_PATTERNS['style'].search(raw_line)
                if match:
                    try:
                        current_style = float(match.group(1).strip())
                    except ValueError:
                        pass
                    continue

            # Script text line
            text = raw_line
            pause_after = 150  # Default inter-line pause

            # Inline pause at end
            pause_match = self.TAG_PATTERNS['pause'].search(text)
            if pause_match:
                pause_after = self._parse_pause(pause_match.group(1))
                text = self.TAG_PATTERNS['pause'].sub('', text).strip()

            # Extract emphasis
            emphasis = self.EMPHASIS_PATTERN.findall(text)
            strong_emphasis = self.STRONG_EMPHASIS_PATTERN.findall(text)

            # Convert strong emphasis to caps (per spec)
            for word in strong_emphasis:
                text = text.replace(f'**{word}**', word.upper())

            # Remove single emphasis markers (keep word)
            text = self.EMPHASIS_PATTERN.sub(r'\1', text)

            if text:
                lines.append(ParsedLine(
                    text=text,
                    direction=current_direction,
                    pace=current_pace,
                    pause_after_ms=pause_after,
                    stability_override=current_stability,
                    style_override=current_style,
                    emphasis_words=emphasis,
                    strong_emphasis_words=strong_emphasis
                ))

        if not lines:
            return None

        # Build combined script (clean text for ElevenLabs)
        combined = ' '.join(line.text for line in lines)

        # Get primary direction and pace
        primary_direction = next((l.direction for l in lines if l.direction), None)
        primary_pace = lines[0].pace if lines else Pace.NORMAL

        # Build settings override
        settings_override = None
        first_stability = next((l.stability_override for l in lines if l.stability_override), None)
        first_style = next((l.style_override for l in lines if l.style_override), None)

        if first_stability or first_style or primary_pace != Pace.NORMAL:
            settings_override = VoiceSettings(
                stability=first_stability or 0.35,
                style=first_style or 0.45,
                speed=primary_pace.to_speed()
            )

        # Extract beat number
        num_match = re.match(r'(\d+)', beat_id)
        beat_number = int(num_match.group(1)) if num_match else 0

        return ScriptBeat(
            beat_id=beat_id,
            beat_number=beat_number,
            beat_name=name,
            character=current_character,
            lines=lines,
            combined_script=combined,
            primary_direction=primary_direction,
            primary_pace=primary_pace,
            settings_override=settings_override,
            pause_after_ms=final_pause
        )

    def _parse_pause(self, value: str) -> int:
        """Convert pause value to milliseconds"""
        value = value.lower().strip()

        if value in self.PAUSE_VALUES:
            return self.PAUSE_VALUES[value]

        if value.endswith('ms'):
            try:
                return int(value[:-2])
            except ValueError:
                return 150

        try:
            return int(value)
        except ValueError:
            return 150


# Convenience functions
def validate_els(content: str) -> ELSValidationResult:
    """Validate ELS content"""
    parser = ELSParserService()
    return parser.validate(content)


def parse_els(content: str) -> ELSParseResult:
    """Parse ELS content"""
    parser = ELSParserService()
    return parser.parse(content)
```

---

## Phase 5: ElevenLabs Service

**File**: `viraltracker/services/elevenlabs_service.py`

```python
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

from .audio_models import (
    VoiceSettings,
    CharacterVoiceProfile,
    ScriptBeat,
    AudioTake,
    Character
)
from ..core.config import Config
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
        self.api_key = api_key or Config.ELEVENLABS_API_KEY
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
        """
        if self._profiles_loaded:
            return self._voice_profiles

        db = get_supabase_client()

        # Run sync Supabase call
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
        """Get voice profile for a character"""
        await self.load_voice_profiles()

        if character not in self._voice_profiles:
            raise ValueError(f"No voice profile configured for character: {character.value}")

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
                speed=self._clamp_speed(beat.settings_override.speed or base_settings.speed)
            )
        else:
            # Apply pace from beat
            settings = VoiceSettings(
                stability=base_settings.stability,
                similarity_boost=base_settings.similarity_boost,
                style=base_settings.style,
                speed=self._clamp_speed(beat.primary_pace.to_speed())
            )

        # Generate unique take ID
        take_id = str(uuid.uuid4())[:8]
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

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
```

---

## Phase 6: Audio Production Service

**File**: `viraltracker/services/audio_production_service.py`

```python
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
from .els_parser_service import ELSParserService, validate_els
from .elevenlabs_service import ElevenLabsService
from .ffmpeg_service import FFmpegService
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class AudioProductionService:
    """Service for audio production workflow operations"""

    def __init__(self):
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
        """Load full session from database"""
        # Get session record
        result = await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions")
                .select("*")
                .eq("id", session_id)
                .single()
                .execute()
        )

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
                created_at=datetime.fromisoformat(row["created_at"].replace('Z', '+00:00')),
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
            created_at=datetime.fromisoformat(data["created_at"].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(data["updated_at"].replace('Z', '+00:00')),
            status=data["status"]
        )

    async def update_session_status(self, session_id: str, status: str) -> None:
        """Update session status"""
        await asyncio.to_thread(
            lambda: self.supabase.table("audio_production_sessions")
                .update({"status": status})
                .eq("id", session_id)
                .execute()
        )
        logger.info(f"Session {session_id} status -> {status}")

    async def get_recent_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent sessions for sidebar"""
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
        """Save a generated take to database"""
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

    async def select_take(self, session_id: str, beat_id: str, take_id: str) -> None:
        """Select which take to use for a beat"""
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

    # =========================================================================
    # Voice Profile Operations
    # =========================================================================

    async def get_all_voice_profiles(self) -> List[CharacterVoiceProfile]:
        """Get all voice profiles from database"""
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
        """Update a voice profile"""
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
```

---

## Phase 7: Pydantic AI Agent & Tools

**File**: `viraltracker/agent/agents/audio_production_agent.py`

```python
"""
Audio Production Agent - Specialized agent for ElevenLabs audio generation.

This agent orchestrates the audio production workflow:
1. Validate and parse ELS scripts
2. Create production sessions
3. Generate audio for each beat
4. Manage takes and selection
5. Export final audio

Tools follow Pydantic AI best practices with @agent.tool() decorator.
"""

import logging
from typing import Dict, List, Optional, Any
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# Create Audio Production Agent
audio_production_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Audio Production specialist agent.

Your ONLY responsibility is generating voice audio from ELS scripts:
- Validating ElevenLabs Script (ELS) format
- Parsing scripts into structured beats
- Managing production sessions
- Generating audio via ElevenLabs API
- Adding pauses via FFmpeg post-processing
- Managing takes and selection
- Exporting final audio files

CRITICAL RULES:
1. Direction tags are NOT sent to ElevenLabs (they inform settings only)
2. Pauses are added via FFmpeg, not SSML (more reliable)
3. Generate beats ONE AT A TIME for resilience
4. Each character has voice settings in database - look them up
5. Speed must be between 0.7 and 1.2 (ElevenLabs API limit)

You have access to specialized tools for this workflow.
"""
)


# ============================================================================
# VALIDATION & PARSING TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',  # Validation/parsing is preprocessing
        'platform': 'All',  # Audio - use 'All' until Platform literal is extended
        'rate_limit': '60/minute',
        'use_cases': [
            'Validate ELS script format before processing',
            'Check for syntax errors in script',
            'Get beat and character counts'
        ],
        'examples': [
            'Validate my ELS script',
            'Check if this script is valid'
        ]
    }
)
async def validate_els_script(
    ctx: RunContext[AgentDependencies],
    els_content: str
) -> Dict:
    """
    Validate ELS script format without parsing.

    Checks for:
    - Required [META] block
    - Matching [BEAT:] and [END_BEAT] tags
    - Valid character names
    - Valid pace values
    - Line length limits (500 chars max)

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content to validate

    Returns:
        Dictionary with validation results:
        {
            "is_valid": true/false,
            "errors": ["error1", ...],
            "warnings": ["warning1", ...],
            "beat_count": 8,
            "character_count": {"every-coon": 6, "boomer": 2}
        }
    """
    from viraltracker.services.els_parser_service import validate_els

    logger.info("Validating ELS script")
    result = validate_els(els_content)

    return {
        "is_valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "beat_count": result.beat_count,
        "character_count": result.character_count
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',  # Parsing is preprocessing
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Parse ELS script into structured beats',
            'Extract metadata from script',
            'Prepare script for audio generation'
        ],
        'examples': [
            'Parse this ELS script',
            'Extract beats from script'
        ]
    }
)
async def parse_els_script(
    ctx: RunContext[AgentDependencies],
    els_content: str
) -> Dict:
    """
    Parse ELS script into structured beat data.

    Extracts:
    - Video title and project from [META]
    - Each beat with character, direction, pace
    - Individual lines with pause values
    - Combined script text for generation

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content to parse

    Returns:
        Dictionary with parsed data including video_title, project, and beats array

    Raises:
        ValueError: If script is invalid
    """
    from viraltracker.services.els_parser_service import parse_els

    logger.info("Parsing ELS script")
    result = parse_els(els_content)

    return {
        "video_title": result.video_title,
        "project": result.project,
        "default_character": result.default_character.value,
        "default_pace": result.default_pace.value,
        "beats": [beat.model_dump(mode='json') for beat in result.beats]
    }


# ============================================================================
# SESSION MANAGEMENT TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',  # Session management is data ingestion
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Create new audio production session',
            'Initialize session from parsed script',
            'Start new audio project'
        ],
        'examples': [
            'Create session for my script',
            'Start new audio production'
        ]
    }
)
async def create_production_session(
    ctx: RunContext[AgentDependencies],
    video_title: str,
    project_name: str,
    beats_json: List[Dict],
    source_els: Optional[str] = None
) -> Dict:
    """
    Create a new production session in database.

    Args:
        ctx: Run context with AgentDependencies
        video_title: Title of the video
        project_name: Project name (e.g., "trash-panda")
        beats_json: List of beat dictionaries from parse_els_script
        source_els: Optional original ELS content

    Returns:
        Dictionary with session_id and status
    """
    from viraltracker.services.models.audio_models import ScriptBeat

    logger.info(f"Creating production session: {video_title}")

    # Convert beat dicts back to ScriptBeat objects
    beats = [ScriptBeat(**b) for b in beats_json]

    session = await ctx.deps.audio_production.create_session(
        video_title=video_title,
        project_name=project_name,
        beats=beats,
        source_els=source_els
    )

    return {
        "session_id": session.session_id,
        "status": session.status,
        "beat_count": len(session.beats)
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',  # Session management is data ingestion
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Load existing production session',
            'Get session with all takes',
            'Resume previous session'
        ],
        'examples': [
            'Load session abc123',
            'Get my previous session'
        ]
    }
)
async def get_production_session(
    ctx: RunContext[AgentDependencies],
    session_id: str
) -> Dict:
    """
    Load a production session with all beats and takes.

    Args:
        ctx: Run context with AgentDependencies
        session_id: UUID of the session

    Returns:
        Full session data including beats, takes, and status
    """
    logger.info(f"Loading session: {session_id}")

    session = await ctx.deps.audio_production.get_session(session_id)

    return {
        "session_id": session.session_id,
        "video_title": session.video_title,
        "project_name": session.project_name,
        "status": session.status,
        "beats": [
            {
                "beat_id": bwt.beat.beat_id,
                "beat_name": bwt.beat.beat_name,
                "character": bwt.beat.character.value,
                "combined_script": bwt.beat.combined_script,
                "primary_direction": bwt.beat.primary_direction,
                "takes": [
                    {
                        "take_id": t.take_id,
                        "audio_path": t.audio_path,
                        "audio_duration_ms": t.audio_duration_ms,
                        "is_selected": t.is_selected
                    }
                    for t in bwt.takes
                ],
                "selected_take_id": bwt.selected_take_id
            }
            for bwt in session.beats
        ],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat()
    }


# ============================================================================
# VOICE PROFILE TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',  # Voice profile retrieval is data ingestion
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Get voice settings for a character',
            'Look up voice ID and settings',
            'Check character configuration'
        ],
        'examples': [
            'Get voice profile for every-coon',
            'What are boomers voice settings'
        ]
    }
)
async def get_voice_profile(
    ctx: RunContext[AgentDependencies],
    character_name: str
) -> Dict:
    """
    Get voice profile for a character from database.

    Args:
        ctx: Run context with AgentDependencies
        character_name: Character name (e.g., "every-coon", "boomer")

    Returns:
        Voice profile with voice_id and settings
    """
    from viraltracker.services.models.audio_models import Character

    logger.info(f"Getting voice profile for: {character_name}")

    char = Character(character_name.lower())
    profile = await ctx.deps.elevenlabs.get_voice_profile(char)

    return {
        "character": profile.character.value,
        "voice_id": profile.voice_id,
        "display_name": profile.display_name,
        "description": profile.description,
        "stability": profile.stability,
        "similarity_boost": profile.similarity_boost,
        "style": profile.style,
        "speed": profile.speed
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',  # Voice profile retrieval is data ingestion
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'List all character voice profiles',
            'See available characters',
            'Check voice configurations'
        ],
        'examples': [
            'List all voice profiles',
            'Show me all characters'
        ]
    }
)
async def list_voice_profiles(
    ctx: RunContext[AgentDependencies]
) -> List[Dict]:
    """
    Get all voice profiles from database.

    Returns:
        List of all character voice profiles
    """
    logger.info("Listing all voice profiles")

    profiles = await ctx.deps.audio_production.get_all_voice_profiles()

    return [
        {
            "character": p.character.value,
            "display_name": p.display_name,
            "voice_id": p.voice_id,
            "stability": p.stability,
            "style": p.style,
            "speed": p.speed
        }
        for p in profiles
    ]


# ============================================================================
# AUDIO GENERATION TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'All',
        'rate_limit': '5/minute',
        'use_cases': [
            'Generate audio for a single beat',
            'Create voice audio from script',
            'Generate with specific settings'
        ],
        'examples': [
            'Generate audio for beat 01_hook',
            'Create audio for the first beat'
        ]
    }
)
async def generate_beat_audio(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_json: Dict
) -> Dict:
    """
    Generate audio for a single beat.

    Process:
    1. Load character voice profile from database
    2. Merge beat settings with character defaults
    3. Generate audio via ElevenLabs (clean text, no SSML)
    4. Add pauses via FFmpeg post-processing
    5. Get duration and save take to database

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_json: Beat data dictionary

    Returns:
        Take data with audio path and duration
    """
    from pathlib import Path
    from viraltracker.services.models.audio_models import ScriptBeat

    beat = ScriptBeat(**beat_json)
    logger.info(f"Generating audio for beat: {beat.beat_id}")

    # Output directory
    output_dir = Path("audio_production") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate via ElevenLabs
    take = await ctx.deps.elevenlabs.generate_beat_audio(
        beat=beat,
        output_dir=output_dir,
        session_id=session_id
    )

    # Add pause after beat via FFmpeg (sync calls wrapped for async)
    if beat.pause_after_ms > 0:
        audio_path = Path(take.audio_path)
        temp_path = audio_path.with_suffix('.temp.mp3')

        success = await asyncio.to_thread(
            ctx.deps.ffmpeg.add_silence_after,
            audio_path,
            temp_path,
            beat.pause_after_ms
        )

        if success and temp_path.exists():
            temp_path.rename(audio_path)

    # Get final duration (sync call wrapped for async)
    audio_path = Path(take.audio_path)
    take.audio_duration_ms = await asyncio.to_thread(
        ctx.deps.ffmpeg.get_duration_ms, audio_path
    )

    # Save to database
    await ctx.deps.audio_production.save_take(session_id, take)

    # Auto-select first take
    await ctx.deps.audio_production.select_take(session_id, beat.beat_id, take.take_id)

    return {
        "take_id": take.take_id,
        "beat_id": take.beat_id,
        "audio_path": take.audio_path,
        "audio_duration_ms": take.audio_duration_ms,
        "settings_used": take.generation_settings.model_dump()
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'All',
        'rate_limit': '5/minute',
        'use_cases': [
            'Regenerate audio with different settings',
            'Create alternative take for beat',
            'Adjust voice and try again'
        ],
        'examples': [
            'Regenerate beat 01_hook with slower pace',
            'Create new take with more stability'
        ]
    }
)
async def regenerate_beat_audio(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_id: str,
    new_direction: Optional[str] = None,
    new_pace: Optional[str] = None,
    stability: Optional[float] = None,
    style: Optional[float] = None
) -> Dict:
    """
    Generate a new take for a beat with modified settings.

    Preserves existing takes - adds a new one with the specified overrides.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_id: ID of beat to regenerate
        new_direction: Optional new direction text
        new_pace: Optional new pace (slow, normal, fast, etc.)
        stability: Optional stability override (0-1)
        style: Optional style override (0-1)

    Returns:
        New take data
    """
    from pathlib import Path
    from viraltracker.services.models.audio_models import ScriptBeat, VoiceSettings, Pace

    logger.info(f"Regenerating beat: {beat_id}")

    # Load session to get beat
    session = await ctx.deps.audio_production.get_session(session_id)

    # Find the beat
    bwt = next((b for b in session.beats if b.beat.beat_id == beat_id), None)
    if not bwt:
        raise ValueError(f"Beat not found: {beat_id}")

    # Create modified beat
    beat = bwt.beat.model_copy(deep=True)

    if new_direction:
        beat.primary_direction = new_direction

    # Apply setting overrides
    if any([stability is not None, style is not None, new_pace]):
        current = beat.settings_override or VoiceSettings()
        beat.settings_override = VoiceSettings(
            stability=stability if stability is not None else current.stability,
            style=style if style is not None else current.style,
            speed=Pace(new_pace).to_speed() if new_pace else current.speed
        )

    # Generate new take
    output_dir = Path("audio_production") / session_id
    take = await ctx.deps.elevenlabs.generate_beat_audio(
        beat=beat,
        output_dir=output_dir,
        session_id=session_id
    )

    # Add pause after (sync FFmpeg calls wrapped for async)
    if beat.pause_after_ms > 0:
        audio_path = Path(take.audio_path)
        temp_path = audio_path.with_suffix('.temp.mp3')

        success = await asyncio.to_thread(
            ctx.deps.ffmpeg.add_silence_after,
            audio_path,
            temp_path,
            beat.pause_after_ms
        )

        if success and temp_path.exists():
            temp_path.rename(audio_path)

    # Get duration (sync call wrapped for async)
    take.audio_duration_ms = await asyncio.to_thread(
        ctx.deps.ffmpeg.get_duration_ms, Path(take.audio_path)
    )

    # Save to database
    await ctx.deps.audio_production.save_take(session_id, take)

    return {
        "take_id": take.take_id,
        "beat_id": take.beat_id,
        "audio_path": take.audio_path,
        "audio_duration_ms": take.audio_duration_ms,
        "settings_used": take.generation_settings.model_dump()
    }


# ============================================================================
# SELECTION & EXPORT TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',  # Selection is curation/filtering
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Select which take to use for a beat',
            'Choose best audio take',
            'Set active take'
        ],
        'examples': [
            'Select take abc123 for beat 01_hook',
            'Use this take for the hook'
        ]
    }
)
async def select_take(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_id: str,
    take_id: str
) -> Dict:
    """
    Select which take to use for a beat.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_id: Beat ID
        take_id: Take ID to select

    Returns:
        Confirmation
    """
    logger.info(f"Selecting take {take_id} for beat {beat_id}")

    await ctx.deps.audio_production.select_take(session_id, beat_id, take_id)

    return {
        "success": True,
        "beat_id": beat_id,
        "selected_take_id": take_id
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Export all selected takes',
            'Save final audio files',
            'Complete production'
        ],
        'examples': [
            'Export selected takes',
            'Save final audio'
        ]
    }
)
async def export_selected_takes(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    output_path: Optional[str] = None
) -> Dict:
    """
    Export all selected takes with clean filenames.

    Output: 01_hook.mp3, 02_setup.mp3, etc.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        output_path: Optional custom output directory

    Returns:
        List of exported files
    """
    from pathlib import Path

    logger.info(f"Exporting selected takes for session {session_id}")

    out_dir = Path(output_path) if output_path else None

    exported = await ctx.deps.audio_production.export_selected_takes(
        session_id=session_id,
        output_dir=out_dir
    )

    return {
        "exported_files": [str(f) for f in exported],
        "count": len(exported),
        "export_path": str(exported[0].parent) if exported else None
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',  # Session management is data ingestion
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Update session status',
            'Mark session as complete',
            'Change session state'
        ],
        'examples': [
            'Mark session as completed',
            'Update status to in_progress'
        ]
    }
)
async def update_session_status(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    status: str
) -> Dict:
    """
    Update session status.

    Valid statuses: draft, generating, in_progress, completed, exported

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        status: New status

    Returns:
        Confirmation
    """
    valid_statuses = ["draft", "generating", "in_progress", "completed", "exported"]
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")

    await ctx.deps.audio_production.update_session_status(session_id, status)

    return {"success": True, "status": status}


logger.info("Audio Production Agent initialized with 11 tools")
```

---

## Phase 8: Orchestration Workflow

Add to the same file (`audio_production_agent.py`) after the tools:

```python
# ============================================================================
# COMPLETE WORKFLOW ORCHESTRATION
# ============================================================================

async def complete_audio_workflow(
    ctx: RunContext[AgentDependencies],
    els_content: str,
    project_name: str = "trash-panda"
) -> Dict:
    """
    Execute complete audio production workflow from start to finish.

    This orchestration function:
    1. Validates ELS script
    2. Parses into structured beats
    3. Creates production session
    4. Generates audio for each beat (ONE AT A TIME)
    5. Adds pauses via FFmpeg
    6. Auto-selects first take per beat
    7. Returns complete session with all takes

    Called directly by Streamlit UI, similar to complete_ad_workflow.

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content
        project_name: Project name override (default: from script)

    Returns:
        Complete session data with all beats and takes
    """
    from datetime import datetime
    from pathlib import Path
    from viraltracker.services.els_parser_service import validate_els, parse_els
    from viraltracker.services.models.audio_models import ScriptBeat

    logger.info("=== STARTING COMPLETE AUDIO WORKFLOW ===")

    # Step 1: Validate
    logger.info("Step 1: Validating ELS script")
    validation = validate_els(els_content)

    if not validation.is_valid:
        raise ValueError(f"Invalid ELS script: {'; '.join(validation.errors)}")

    logger.info(f"Validation passed: {validation.beat_count} beats, characters: {validation.character_count}")

    # Step 2: Parse
    logger.info("Step 2: Parsing ELS script")
    parsed = parse_els(els_content)

    video_title = parsed.video_title or "Untitled"
    project = project_name or parsed.project or "trash-panda"

    logger.info(f"Parsed: '{video_title}' with {len(parsed.beats)} beats")

    # Step 3: Create session
    logger.info("Step 3: Creating production session")
    session = await ctx.deps.audio_production.create_session(
        video_title=video_title,
        project_name=project,
        beats=parsed.beats,
        source_els=els_content
    )

    session_id = session.session_id
    logger.info(f"Created session: {session_id}")

    # Step 4: Update status to generating
    await ctx.deps.audio_production.update_session_status(session_id, "generating")

    # Step 5: Generate audio for each beat (ONE AT A TIME for resilience)
    logger.info("Step 5: Generating audio for all beats")
    output_dir = Path("audio_production") / session_id

    generated_takes = []
    total_duration_ms = 0

    for i, beat in enumerate(parsed.beats):
        logger.info(f"Generating beat {i+1}/{len(parsed.beats)}: {beat.beat_id}")

        try:
            # Generate via ElevenLabs
            take = await ctx.deps.elevenlabs.generate_beat_audio(
                beat=beat,
                output_dir=output_dir,
                session_id=session_id
            )

            # Add pause after beat via FFmpeg (sync calls wrapped for async)
            if beat.pause_after_ms > 0:
                audio_path = Path(take.audio_path)
                temp_path = audio_path.with_suffix('.temp.mp3')

                success = await asyncio.to_thread(
                    ctx.deps.ffmpeg.add_silence_after,
                    audio_path,
                    temp_path,
                    beat.pause_after_ms
                )

                if success and temp_path.exists():
                    temp_path.rename(audio_path)

            # Get final duration (sync call wrapped for async)
            audio_path = Path(take.audio_path)
            take.audio_duration_ms = await asyncio.to_thread(
                ctx.deps.ffmpeg.get_duration_ms, audio_path
            )
            total_duration_ms += take.audio_duration_ms

            # Save to database
            await ctx.deps.audio_production.save_take(session_id, take)

            # Auto-select first take
            await ctx.deps.audio_production.select_take(session_id, beat.beat_id, take.take_id)

            generated_takes.append({
                "beat_id": beat.beat_id,
                "beat_name": beat.beat_name,
                "take_id": take.take_id,
                "audio_path": take.audio_path,
                "audio_duration_ms": take.audio_duration_ms,
                "character": beat.character.value
            })

            logger.info(f"Generated {beat.beat_id}: {take.audio_duration_ms}ms")

        except Exception as e:
            logger.error(f"Failed to generate beat {beat.beat_id}: {str(e)}")
            # Continue with other beats
            generated_takes.append({
                "beat_id": beat.beat_id,
                "beat_name": beat.beat_name,
                "error": str(e)
            })

    # Step 6: Update status to in_progress
    await ctx.deps.audio_production.update_session_status(session_id, "in_progress")

    # Build summary
    successful = len([t for t in generated_takes if "take_id" in t])
    failed = len([t for t in generated_takes if "error" in t])
    total_sec = total_duration_ms / 1000

    summary = f"Generated {successful}/{len(parsed.beats)} beats, {total_sec:.1f} seconds total"
    if failed > 0:
        summary += f" ({failed} failed)"

    logger.info(f"=== WORKFLOW COMPLETE: {summary} ===")

    return {
        "session_id": session_id,
        "video_title": video_title,
        "project_name": project,
        "status": "in_progress",
        "beats": generated_takes,
        "total_duration_ms": total_duration_ms,
        "summary": summary,
        "created_at": datetime.utcnow().isoformat()
    }
```

---

## Phase 9: Streamlit UI

**File**: `viraltracker/ui/pages/8_🎙️_Audio_Production.py`

```python
"""
Audio Production UI

Streamlit interface for:
- Pasting/uploading ELS scripts
- Generating audio via ElevenLabs
- Reviewing and selecting takes
- Exporting final audio files
"""

import streamlit as st
import asyncio
from pathlib import Path
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Audio Production",
    page_icon="🎙️",
    layout="wide"
)

# Initialize session state
if 'audio_session_id' not in st.session_state:
    st.session_state.audio_session_id = None
if 'audio_workflow_running' not in st.session_state:
    st.session_state.audio_workflow_running = False
if 'audio_workflow_result' not in st.session_state:
    st.session_state.audio_workflow_result = None


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Async Helpers
# ============================================================================

async def run_audio_workflow(els_content: str, project_name: str = "trash-panda"):
    """Run the complete audio workflow."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.audio_production_agent import complete_audio_workflow
    from viraltracker.agent.dependencies import AgentDependencies

    deps = AgentDependencies.create(project_name=project_name)
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    return await complete_audio_workflow(ctx, els_content, project_name)


async def load_session(session_id: str):
    """Load a production session."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_session(session_id)


async def load_recent_sessions():
    """Load recent sessions for sidebar."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_recent_sessions()


async def regenerate_beat(session_id, beat_id, direction, pace, stability, style):
    """Regenerate a beat with new settings."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.audio_production_agent import regenerate_beat_audio
    from viraltracker.agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    return await regenerate_beat_audio(
        ctx, session_id, beat_id,
        new_direction=direction if direction else None,
        new_pace=pace if pace != "normal" else None,
        stability=stability,
        style=style
    )


async def select_take_async(session_id, beat_id, take_id):
    """Select a take."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    await service.select_take(session_id, beat_id, take_id)


async def export_session(session_id):
    """Export selected takes."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.export_selected_takes(session_id)


async def load_voice_profiles():
    """Load voice profiles."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_all_voice_profiles()


# ============================================================================
# UI Components
# ============================================================================

def render_sidebar():
    """Render sidebar with sessions and profiles."""
    st.sidebar.header("📁 Sessions")

    # Load recent sessions
    try:
        sessions = asyncio.run(load_recent_sessions())

        for s in sessions[:10]:
            status_emoji = {
                'draft': '📝',
                'generating': '⏳',
                'in_progress': '🎵',
                'completed': '✅',
                'exported': '📦'
            }.get(s.get('status', ''), '❓')

            title = s.get('video_title', 'Untitled')[:25]
            if st.sidebar.button(f"{status_emoji} {title}", key=f"load_{s['id']}"):
                st.session_state.audio_session_id = s['id']
                st.session_state.audio_workflow_result = None
                st.rerun()
    except Exception as e:
        st.sidebar.caption(f"Could not load sessions: {e}")

    st.sidebar.divider()

    if st.sidebar.button("➕ New Session"):
        st.session_state.audio_session_id = None
        st.session_state.audio_workflow_result = None
        st.rerun()

    st.sidebar.divider()

    # Voice profiles
    with st.sidebar.expander("🎭 Voice Profiles"):
        try:
            profiles = asyncio.run(load_voice_profiles())
            for p in profiles:
                st.markdown(f"**{p.display_name}**")
                st.caption(f"stability={p.stability}, style={p.style}, speed={p.speed}")
        except Exception as e:
            st.caption(f"Error: {e}")


def render_new_session():
    """Render new session creation UI."""
    st.header("Create New Audio Session")

    tab1, tab2 = st.tabs(["📝 Paste ELS Script", "📁 Upload File"])

    with tab1:
        els_content = st.text_area(
            "ElevenLabs Script (ELS Format)",
            height=400,
            placeholder="""[META]
video_title: My Video Title
project: trash-panda
default_character: every-coon

[BEAT: 01_hook]
name: Hook
---
[DIRECTION: Punchy and direct]
[PACE: fast]
Your script here.
[PAUSE: 100ms]
[END_BEAT]""",
            key="els_input"
        )

        if els_content:
            # Validate
            from viraltracker.services.els_parser_service import validate_els
            validation = validate_els(els_content)

            if validation.errors:
                for err in validation.errors:
                    st.error(f"❌ {err}")
            else:
                st.success(f"✅ Valid — {validation.beat_count} beats")

                for warn in validation.warnings:
                    st.warning(f"⚠️ {warn}")

                if validation.character_count:
                    chars = ", ".join(f"{k} ({v})" for k, v in validation.character_count.items())
                    st.caption(f"Characters: {chars}")

                # Generate button
                if st.button("🎵 Generate Audio", type="primary", disabled=st.session_state.audio_workflow_running):
                    st.session_state.audio_workflow_running = True
                    st.rerun()

    with tab2:
        uploaded = st.file_uploader("Upload ELS file", type=["els", "txt", "md"])

        if uploaded:
            content = uploaded.read().decode()
            st.text_area("Preview", content, height=300, disabled=True)

            from viraltracker.services.els_parser_service import validate_els
            validation = validate_els(content)

            if validation.is_valid:
                st.success(f"✅ Valid — {validation.beat_count} beats")
                if st.button("🎵 Generate Audio", type="primary"):
                    st.session_state.els_input = content
                    st.session_state.audio_workflow_running = True
                    st.rerun()
            else:
                for err in validation.errors:
                    st.error(err)

    # Run workflow if triggered
    if st.session_state.audio_workflow_running:
        els = st.session_state.get('els_input', '')
        if els:
            st.info("🎵 Generating audio... This may take a few minutes.")
            st.warning("⏳ Please wait. Do not refresh the page.")

            try:
                result = asyncio.run(run_audio_workflow(els))
                st.session_state.audio_workflow_result = result
                st.session_state.audio_session_id = result['session_id']
                st.session_state.audio_workflow_running = False
                st.rerun()
            except Exception as e:
                st.session_state.audio_workflow_running = False
                st.error(f"Workflow failed: {str(e)}")


def render_session_editor():
    """Render session editing interface."""
    try:
        session = asyncio.run(load_session(st.session_state.audio_session_id))
    except Exception as e:
        st.error(f"Failed to load session: {e}")
        return

    # Header
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.header(f"🎙️ {session.video_title}")
    with col2:
        status_emoji = {'draft': '📝', 'generating': '⏳', 'in_progress': '🎵', 'completed': '✅', 'exported': '📦'}
        st.metric("Status", f"{status_emoji.get(session.status, '❓')} {session.status}")
    with col3:
        st.metric("Beats", len(session.beats))

    # Action bar
    col1, col2, col3 = st.columns(3)

    with col1:
        has_selections = any(b.selected_take_id for b in session.beats)
        if st.button("📦 Export Selected", disabled=not has_selections):
            with st.spinner("Exporting..."):
                exported = asyncio.run(export_session(session.session_id))
                st.success(f"Exported {len(exported)} files!")

    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()

    with col3:
        if st.button("← Back to New"):
            st.session_state.audio_session_id = None
            st.rerun()

    st.divider()

    # Beat list
    for bwt in session.beats:
        render_beat_row(session.session_id, bwt)


def render_beat_row(session_id: str, bwt):
    """Render a single beat with audio player."""
    beat = bwt.beat

    with st.container():
        col1, col2, col3 = st.columns([1, 2, 3])

        with col1:
            st.markdown(f"**{beat.beat_number:02d}**")
            st.caption(beat.character.value)

        with col2:
            st.markdown(f"**{beat.beat_name}**")
            with st.expander("Script"):
                st.text(beat.combined_script)
                if beat.primary_direction:
                    st.caption(f"Direction: {beat.primary_direction}")

        with col3:
            takes = bwt.takes

            if takes:
                # Take selector
                take_options = {
                    f"Take {i+1} ({t.audio_duration_ms/1000:.1f}s)": t.take_id
                    for i, t in enumerate(takes)
                }

                current = bwt.selected_take_id
                current_label = next(
                    (k for k, v in take_options.items() if v == current),
                    list(take_options.keys())[0] if take_options else None
                )

                if take_options:
                    selected_label = st.selectbox(
                        "Take",
                        list(take_options.keys()),
                        index=list(take_options.keys()).index(current_label) if current_label else 0,
                        key=f"select_{beat.beat_id}",
                        label_visibility="collapsed"
                    )

                    selected_take_id = take_options[selected_label]

                    # Update if changed
                    if selected_take_id != current:
                        asyncio.run(select_take_async(session_id, beat.beat_id, selected_take_id))
                        st.rerun()

                    # Audio player
                    selected_take = next((t for t in takes if t.take_id == selected_take_id), None)
                    if selected_take:
                        audio_path = Path(selected_take.audio_path)
                        if audio_path.exists():
                            st.audio(str(audio_path), format="audio/mp3")
                        else:
                            st.warning("Audio file not found")

                # Revise button
                if st.button("🔄 Revise", key=f"revise_{beat.beat_id}"):
                    st.session_state[f"show_revise_{beat.beat_id}"] = True
            else:
                st.caption("No audio generated")

        # Revise panel
        if st.session_state.get(f"show_revise_{beat.beat_id}"):
            with st.expander("Revise Settings", expanded=True):
                new_dir = st.text_input("Direction", value=beat.primary_direction or "", key=f"dir_{beat.beat_id}")

                c1, c2, c3 = st.columns(3)
                with c1:
                    pace = st.selectbox("Pace", ["slow", "deliberate", "normal", "quick", "fast", "chaos"], index=2, key=f"pace_{beat.beat_id}")
                with c2:
                    stab = st.slider("Stability", 0.0, 1.0, 0.35, key=f"stab_{beat.beat_id}")
                with c3:
                    style = st.slider("Style", 0.0, 1.0, 0.45, key=f"style_{beat.beat_id}")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Generate", key=f"gen_{beat.beat_id}"):
                        with st.spinner("Generating..."):
                            asyncio.run(regenerate_beat(session_id, beat.beat_id, new_dir, pace, stab, style))
                            st.session_state[f"show_revise_{beat.beat_id}"] = False
                            st.rerun()
                with c2:
                    if st.button("Cancel", key=f"cancel_{beat.beat_id}"):
                        st.session_state[f"show_revise_{beat.beat_id}"] = False
                        st.rerun()

        st.divider()


# ============================================================================
# Main
# ============================================================================

st.title("🎙️ Audio Production")
st.markdown("**Generate voice audio from ElevenLabs Script (ELS) files**")

render_sidebar()

if st.session_state.audio_session_id:
    render_session_editor()
else:
    render_new_session()
```

---

## Phase 10: Integration

### 10.1: Update Config

**File**: `viraltracker/core/config.py` (add to existing)

```python
# ElevenLabs
ELEVENLABS_API_KEY: str = os.getenv('ELEVENLABS_API_KEY', '')
```

### 10.2: Update .env.example

```bash
# ElevenLabs (Audio Production)
ELEVENLABS_API_KEY=your-elevenlabs-api-key
```

### 10.3: Update AgentDependencies

**File**: `viraltracker/agent/dependencies.py` (add imports and fields)

```python
# Add imports
from ..services.elevenlabs_service import ElevenLabsService
from ..services.ffmpeg_service import FFmpegService
from ..services.audio_production_service import AudioProductionService

# Add to AgentDependencies class
elevenlabs: ElevenLabsService
ffmpeg: FFmpegService
audio_production: AudioProductionService

# Add to create() method
elevenlabs = ElevenLabsService()
logger.info(f"ElevenLabsService initialized (enabled={elevenlabs.enabled})")

ffmpeg = FFmpegService()
logger.info(f"FFmpegService initialized (available={ffmpeg.available})")

audio_production = AudioProductionService()
logger.info("AudioProductionService initialized")

# Add to return statement
elevenlabs=elevenlabs,
ffmpeg=ffmpeg,
audio_production=audio_production,
```

### 10.4: Update Orchestrator (Optional)

**File**: `viraltracker/agent/orchestrator.py` (add routing tool)

```python
@orchestrator.tool
async def route_to_audio_agent(
    ctx: RunContext[AgentDependencies],
    query: str
) -> str:
    """
    Route request to Audio Production Agent.

    Use this when the user wants to:
    - Generate voice audio from scripts
    - Work with ELS (ElevenLabs Script) files
    - Manage audio production sessions
    - Export audio files

    Args:
        ctx: Run context with dependencies
        query: The user's request

    Returns:
        Result from Audio Production Agent
    """
    from .agents.audio_production_agent import audio_production_agent

    logger.info(f"Routing to Audio Production Agent: {query}")
    result = await audio_production_agent.run(query, deps=ctx.deps)
    return result.output
```

### 10.5: Railway Configuration (FFmpeg)

Add to Railway build or Dockerfile:

```dockerfile
# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg
```

Or in Railway dashboard, add to build command or use a buildpack that includes FFmpeg.

---

## File Summary

| Phase | File | Description |
|-------|------|-------------|
| 1 | `viraltracker/services/models/audio_models.py` | Pydantic models |
| 2 | `migrations/2025_12_audio_production.sql` | Database schema + seed data |
| 3 | `viraltracker/services/ffmpeg_service.py` | FFmpeg audio processing |
| 4 | `viraltracker/services/els_parser_service.py` | ELS format parser |
| 5 | `viraltracker/services/elevenlabs_service.py` | ElevenLabs API client |
| 6 | `viraltracker/services/audio_production_service.py` | Database operations |
| 7 | `viraltracker/agent/agents/audio_production_agent.py` | Pydantic AI agent + tools |
| 8 | (same file) | `complete_audio_workflow()` orchestration |
| 9 | `viraltracker/ui/pages/8_🎙️_Audio_Production.py` | Streamlit UI |
| 10 | Various | Config, dependencies, orchestrator |

---

## Build Order

1. **Phase 1**: Models (foundation for all other phases)
2. **Phase 2**: Database migration (run against Supabase)
3. **Phase 3**: FFmpeg Service (no dependencies)
4. **Phase 4**: ELS Parser Service (depends on models)
5. **Phase 5**: ElevenLabs Service (depends on models, config)
6. **Phase 6**: Audio Production Service (depends on models, database)
7. **Phase 7-8**: Agent + Workflow (depends on all services)
8. **Phase 9**: Streamlit UI (depends on agent)
9. **Phase 10**: Integration (wire everything together)

---

## Testing Checklist

- [ ] ELS parser validates correct format
- [ ] ELS parser rejects invalid format with clear errors
- [ ] Voice profiles load from database
- [ ] ElevenLabs generates audio successfully
- [ ] FFmpeg adds pauses correctly
- [ ] FFmpeg gets duration correctly
- [ ] Session creates in database
- [ ] Takes save to database
- [ ] Take selection persists
- [ ] Export creates clean filenames
- [ ] UI validates ELS before generation
- [ ] UI plays audio correctly
- [ ] UI regeneration works
- [ ] Full workflow completes end-to-end
