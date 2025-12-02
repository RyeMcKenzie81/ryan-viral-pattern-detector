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

    # Emphasis patterns: *word* for light, **word** for strong
    EMPHASIS_PATTERN = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
    STRONG_EMPHASIS_PATTERN = re.compile(r'\*\*([^*]+)\*\*')

    # Named pause values in milliseconds
    PAUSE_VALUES = {
        'beat': 150,
        'short': 250,
        'medium': 400,
        'long': 600,
        'dramatic': 900,
    }

    # Character name mapping (handles variations)
    CHARACTER_MAP = {
        'every-coon': Character.EVERY_COON,
        'everycoon': Character.EVERY_COON,
        'every_coon': Character.EVERY_COON,
        'boomer': Character.BOOMER,
        'fed': Character.FED,
        'whale': Character.WHALE,
        'wojak': Character.WOJAK,
        'chad': Character.CHAD,
    }

    # Pace mapping
    PACE_MAP = {
        'slow': Pace.SLOW,
        'deliberate': Pace.DELIBERATE,
        'normal': Pace.NORMAL,
        'quick': Pace.QUICK,
        'fast': Pace.FAST,
        'chaos': Pace.CHAOS,
    }

    def __init__(self):
        """Initialize parser with default state."""
        self.video_title: str = ""
        self.project: str = ""
        self.default_character = Character.EVERY_COON
        self.default_pace = Pace.NORMAL
        logger.info("ELSParserService initialized")

    def validate(self, content: str) -> ELSValidationResult:
        """
        Validate ELS content without fully parsing.

        Args:
            content: ELS script content

        Returns:
            ELSValidationResult with errors and warnings
        """
        errors: List[str] = []
        warnings: List[str] = []
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
                errors.append(
                    f"Unknown character: '{char_name}' "
                    f"(valid: {', '.join(self.CHARACTER_MAP.keys())})"
                )

        # Check paces
        for match in self.TAG_PATTERNS['pace'].finditer(content):
            pace_name = match.group(1).strip().lower()
            if pace_name not in self.PACE_MAP:
                errors.append(
                    f"Unknown pace: '{pace_name}' "
                    f"(valid: {', '.join(self.PACE_MAP.keys())})"
                )

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
                    errors.append(
                        f"Beat '{beat_id}' line {line_num}: exceeds 500 chars ({len(clean)})"
                    )

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
                self.default_character = self.CHARACTER_MAP.get(
                    value.lower(), Character.EVERY_COON
                )
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

    def _parse_beat_content(
        self,
        beat_id: str,
        name: str,
        content: str
    ) -> Optional[ScriptBeat]:
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
                    current_character = self.CHARACTER_MAP.get(
                        char_name, current_character
                    )
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

            # Extract emphasis markers
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
        first_stability = next(
            (l.stability_override for l in lines if l.stability_override), None
        )
        first_style = next(
            (l.style_override for l in lines if l.style_override), None
        )

        if first_stability or first_style or primary_pace != Pace.NORMAL:
            settings_override = VoiceSettings(
                stability=first_stability or 0.35,
                style=first_style or 0.45,
                speed=primary_pace.to_speed()
            )

        # Extract beat number from ID
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

        # Check named values
        if value in self.PAUSE_VALUES:
            return self.PAUSE_VALUES[value]

        # Check ms suffix
        if value.endswith('ms'):
            try:
                return int(value[:-2])
            except ValueError:
                return 150

        # Try as raw number
        try:
            return int(value)
        except ValueError:
            return 150


# ============================================================================
# Convenience Functions
# ============================================================================

def validate_els(content: str) -> ELSValidationResult:
    """
    Validate ELS content.

    Args:
        content: ELS script content

    Returns:
        ELSValidationResult with validation status
    """
    parser = ELSParserService()
    return parser.validate(content)


def parse_els(content: str) -> ELSParseResult:
    """
    Parse ELS content.

    Args:
        content: ELS script content

    Returns:
        ELSParseResult with parsed data

    Raises:
        ValueError: If content is invalid
    """
    parser = ELSParserService()
    return parser.parse(content)
