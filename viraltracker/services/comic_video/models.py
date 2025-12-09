"""
Comic Video Models

Pydantic models for the comic panel video system.
Transforms static comic grid images into dynamic, cinematic vertical videos.

Following existing codebase patterns from services/audio_models.py.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
from uuid import UUID


# ============================================================================
# Core Enums
# ============================================================================

class PanelMood(str, Enum):
    """Mood determines default effects and camera behavior."""
    NEUTRAL = "neutral"           # Educational, calm
    POSITIVE = "positive"         # Gains, hope, victory
    WARNING = "warning"           # Building tension
    DANGER = "danger"             # Losses, panic
    CHAOS = "chaos"               # System breaking, hyperinflation
    DRAMATIC = "dramatic"         # Big reveals, Fed entrance
    CELEBRATION = "celebration"   # Outro, victories


class EffectType(str, Enum):
    """
    Available visual effects.

    Phase 1: FFmpeg-only effects (no external assets needed)
    Phase 2: Particle overlays (require WebM assets)
    """
    NONE = "none"

    # Color effects (colorbalance, hue, eq filters)
    COLOR_TINT = "color_tint"          # Tint overlay color
    GOLDEN_GLOW = "golden_glow"        # Warm yellow/gold tint
    RED_GLOW = "red_glow"              # Danger red tint
    GREEN_GLOW = "green_glow"          # Money/growth green tint

    # Vignette (vignette filter)
    VIGNETTE = "vignette"              # Dark edges
    VIGNETTE_LIGHT = "vignette_light"  # Subtle dark edges
    VIGNETTE_HEAVY = "vignette_heavy"  # Dramatic dark edges

    # Camera effects (crop, zoompan expressions)
    SHAKE = "shake"                    # Camera shake
    ZOOM_PULSE = "zoom_pulse"          # Quick zoom in/out

    # Brightness effects (eq, curves filters)
    PULSE = "pulse"                    # Subtle brightness pulse
    FLASH = "flash"                    # Brief bright flash

    # Phase 2 particle effects (require external assets)
    # SPARKLES = "sparkles"
    # CONFETTI = "confetti"
    # COINS_FALLING = "coins_falling"
    # EMBERS = "embers"


class TransitionType(str, Enum):
    """Transitions between panels."""
    CUT = "cut"                        # Instant cut
    PAN = "pan"                        # Smooth pan across canvas
    ZOOM_OUT_IN = "zoom_out_in"        # Pull out, move, zoom in
    SNAP = "snap"                      # Fast snap with motion blur
    GLIDE = "glide"                    # Slow elegant glide
    WHIP = "whip"                      # Fast whip pan
    FADE = "fade"                      # Fade through black


class CameraEasing(str, Enum):
    """Easing functions for camera movement."""
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BOUNCE = "bounce"


class ProjectStatus(str, Enum):
    """Project lifecycle status."""
    DRAFT = "draft"                    # Initial state, uploading assets
    PARSING = "parsing"                # Parsing layout from JSON
    AUDIO_GENERATING = "audio_generating"  # Generating voiceover
    AUDIO_READY = "audio_ready"        # Audio complete, ready for direction
    DIRECTING = "directing"            # Generating camera/effects
    READY_FOR_REVIEW = "ready_for_review"  # All panels ready for preview
    RENDERING = "rendering"            # Final video rendering
    COMPLETE = "complete"              # Final video ready
    FAILED = "failed"                  # Error state


class AspectRatio(str, Enum):
    """Supported output aspect ratios."""
    VERTICAL = "9:16"      # 1080×1920 - TikTok, Reels, Shorts (default)
    HORIZONTAL = "16:9"    # 1920×1080 - YouTube, Twitter
    SQUARE = "1:1"         # 1080×1080 - Instagram Feed
    PORTRAIT = "4:5"       # 1080×1350 - Instagram Portrait

    @property
    def dimensions(self) -> Tuple[int, int]:
        """Return (width, height) for this ratio."""
        return {
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1080, 1080),
            "4:5": (1080, 1350),
        }[self.value]

    @property
    def label(self) -> str:
        """Human-readable label."""
        return {
            "9:16": "Vertical (TikTok/Reels)",
            "16:9": "Horizontal (YouTube)",
            "1:1": "Square (Instagram)",
            "4:5": "Portrait (Instagram)",
        }[self.value]

    @classmethod
    def from_string(cls, value: str) -> "AspectRatio":
        """Get AspectRatio from string value."""
        for ratio in cls:
            if ratio.value == value:
                return ratio
        return cls.VERTICAL  # Default


# ============================================================================
# Layout Models
# ============================================================================

class PanelBounds(BaseModel):
    """Bounding box of a panel on the master canvas."""
    panel_number: int = Field(..., description="Panel number (1-indexed)")

    # Normalized coordinates (0.0 - 1.0)
    center_x: float = Field(..., ge=0, le=1, description="Normalized center X")
    center_y: float = Field(..., ge=0, le=1, description="Normalized center Y")
    width: float = Field(..., ge=0, le=1, description="Normalized width")
    height: float = Field(..., ge=0, le=1, description="Normalized height")

    # Pixel coordinates
    pixel_left: int = Field(..., ge=0, description="Left edge in pixels")
    pixel_top: int = Field(..., ge=0, description="Top edge in pixels")
    pixel_right: int = Field(..., ge=0, description="Right edge in pixels")
    pixel_bottom: int = Field(..., ge=0, description="Bottom edge in pixels")


class ComicLayout(BaseModel):
    """Describes the comic grid structure."""
    grid_cols: int = Field(default=3, ge=1, description="Max number of columns (for reference)")
    grid_rows: int = Field(default=5, ge=1, description="Number of rows")
    total_panels: int = Field(default=15, ge=1, description="Total panel count")

    # Panel arrangement: which cells each panel occupies
    # Key: panel number (1-indexed)
    # Value: list of (row, col) tuples (0-indexed)
    # Standard panels: [[row, col]]
    # Wide panels: [[row, col], [row, col+1], ...]
    panel_cells: Dict[int, List[Tuple[int, int]]] = Field(
        default_factory=dict,
        description="Map of panel number to grid cells occupied"
    )

    # Per-row column counts (for rows with different panel counts)
    # Key: row index (0-indexed), Value: number of columns in that row
    # If not specified for a row, grid_cols is used as default
    row_cols: Dict[int, int] = Field(
        default_factory=dict,
        description="Number of columns per row (for variable-width rows)"
    )

    # Canvas dimensions (from comic grid image)
    canvas_width: int = Field(default=4000, ge=100, description="Canvas width in pixels")
    canvas_height: int = Field(default=6000, ge=100, description="Canvas height in pixels")


# ============================================================================
# Camera & Effects Models
# ============================================================================

class FocusPoint(BaseModel):
    """A point of interest within a panel to focus on."""
    x: float = Field(..., ge=0, le=1, description="X position within panel (0-1)")
    y: float = Field(..., ge=0, le=1, description="Y position within panel (0-1)")
    hold_ms: int = Field(default=500, ge=0, description="How long to hold focus")
    zoom_boost: float = Field(default=0.0, ge=0, le=1, description="Additional zoom at this point")


class EffectInstance(BaseModel):
    """A single effect to apply."""
    effect_type: EffectType = Field(..., description="Type of effect")
    start_ms: int = Field(default=0, ge=0, description="Start time relative to panel")
    duration_ms: Optional[int] = Field(None, ge=0, description="Duration (None = full panel)")
    intensity: float = Field(default=1.0, ge=0, le=1, description="Effect intensity 0-1")

    # Effect-specific parameters
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Effect-specific parameters (e.g., color_hex for tint)"
    )


class PanelCamera(BaseModel):
    """Camera instructions for a single panel."""
    panel_number: int = Field(..., ge=1, description="Panel number")

    # Position on master canvas (normalized 0-1)
    center_x: float = Field(..., ge=0, le=1, description="Camera center X")
    center_y: float = Field(..., ge=0, le=1, description="Camera center Y")

    # Zoom levels (1.0 = one panel fills frame, higher = more zoomed)
    start_zoom: float = Field(default=1.0, ge=0.5, le=3.0, description="Starting zoom level")
    end_zoom: float = Field(default=1.1, ge=0.5, le=3.0, description="Ending zoom level")

    # Optional pan within panel during voiceover
    pan_start: Optional[Tuple[float, float]] = Field(
        None, description="Pan start offset from center (x, y)"
    )
    pan_end: Optional[Tuple[float, float]] = Field(
        None, description="Pan end offset from center (x, y)"
    )

    # Focus points (camera visits these in sequence)
    focus_points: List[FocusPoint] = Field(
        default_factory=list,
        description="Points to focus on within panel"
    )

    # Camera movement style
    easing: CameraEasing = Field(
        default=CameraEasing.EASE_IN_OUT,
        description="Easing function for movement"
    )

    # Hold at end before transition
    end_hold_ms: int = Field(default=200, ge=0, description="Hold duration before transition")


class PanelEffects(BaseModel):
    """Effects to apply during a panel."""
    # Continuous effects (play throughout)
    ambient_effects: List[EffectInstance] = Field(
        default_factory=list,
        description="Effects that play throughout panel"
    )

    # Triggered effects (play at specific times)
    triggered_effects: List[EffectInstance] = Field(
        default_factory=list,
        description="Effects triggered at specific times"
    )

    # Mood-based color grading
    color_tint: Optional[str] = Field(None, description="Hex color for tint overlay")
    tint_opacity: float = Field(default=0.0, ge=0, le=1, description="Tint opacity")


class PanelTransition(BaseModel):
    """Transition FROM this panel to next."""
    transition_type: TransitionType = Field(
        default=TransitionType.PAN,
        description="Type of transition"
    )
    duration_ms: int = Field(default=400, ge=0, le=2000, description="Transition duration")
    easing: CameraEasing = Field(
        default=CameraEasing.EASE_IN_OUT,
        description="Easing function"
    )

    # Optional effects during transition
    transition_effects: List[EffectInstance] = Field(
        default_factory=list,
        description="Effects to apply during transition"
    )


class PanelOverrides(BaseModel):
    """
    User overrides for auto-generated panel settings.

    All fields are optional - None means use the auto-generated value.
    For boolean toggles (effect enabled/disabled):
    - None = use auto (from mood preset)
    - True = force on
    - False = force off
    """
    panel_number: int = Field(..., ge=1, description="Panel number this override applies to")

    # Camera overrides
    camera_start_zoom: Optional[float] = Field(
        None, ge=0.5, le=3.0,
        description="Override start zoom level (None = use auto)"
    )
    camera_end_zoom: Optional[float] = Field(
        None, ge=0.5, le=3.0,
        description="Override end zoom level (None = use auto)"
    )
    camera_easing: Optional[CameraEasing] = Field(
        None,
        description="Override camera easing (None = use auto)"
    )
    camera_focus_x: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Custom focus point X within panel (None = use auto center)"
    )
    camera_focus_y: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Custom focus point Y within panel (None = use auto center)"
    )

    # Mood override
    mood_override: Optional[PanelMood] = Field(
        None,
        description="Override inferred mood (None = use auto)"
    )

    # Effect toggles and intensities
    # Vignette
    vignette_enabled: Optional[bool] = Field(
        None, description="Force vignette on/off (None = use auto)"
    )
    vignette_intensity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Vignette darkness/intensity - higher = darker edges (None = use default)"
    )
    vignette_softness: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Vignette softness/spread - higher = extends further from edges (None = use default)"
    )

    # Color tint
    color_tint_enabled: Optional[bool] = Field(
        None, description="Force color tint on/off (None = use auto)"
    )
    color_tint_color: Optional[str] = Field(
        None, description="Hex color for tint (e.g., '#FFD700')"
    )
    color_tint_opacity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Color tint opacity (None = use default)"
    )

    # Shake
    shake_enabled: Optional[bool] = Field(
        None, description="Force shake on/off (None = use auto)"
    )
    shake_intensity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Shake intensity (None = use default)"
    )

    # Pulse
    pulse_enabled: Optional[bool] = Field(
        None, description="Force pulse on/off (None = use auto)"
    )
    pulse_intensity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Pulse intensity (None = use default)"
    )

    # Golden glow
    golden_glow_enabled: Optional[bool] = Field(
        None, description="Force golden glow on/off (None = use auto)"
    )
    golden_glow_intensity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Golden glow intensity (None = use default)"
    )

    # Red glow
    red_glow_enabled: Optional[bool] = Field(
        None, description="Force red glow on/off (None = use auto)"
    )
    red_glow_intensity: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Red glow intensity (None = use default)"
    )

    def has_overrides(self) -> bool:
        """Check if any overrides are set."""
        for field_name, field_value in self:
            if field_name != "panel_number" and field_value is not None:
                return True
        return False


# ============================================================================
# Panel Instruction & Audio Models
# ============================================================================

class PanelAudio(BaseModel):
    """Audio information for a panel."""
    panel_number: int = Field(..., ge=1, description="Panel number")
    audio_url: str = Field(..., description="Storage URL for audio file")
    audio_filename: str = Field(..., description="Audio filename")
    duration_ms: int = Field(..., ge=0, description="Audio duration in milliseconds")

    # Voice settings used
    voice_id: Optional[str] = Field(None, description="ElevenLabs voice ID used")
    voice_name: Optional[str] = Field(None, description="Voice display name")

    # Generation metadata
    text_content: str = Field(default="", description="Text that was spoken")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_approved: bool = Field(default=False, description="User approved this audio")


class PanelInstruction(BaseModel):
    """Complete instructions for one panel."""
    panel_number: int = Field(..., ge=1, description="Panel number")
    panel_type: str = Field(default="CONTENT", description="TITLE, ACT X - CONTENT, OUTRO, etc.")

    # Duration (from audio or estimated)
    duration_ms: int = Field(..., ge=0, description="Total panel duration")

    # From comic JSON
    header_text: Optional[str] = Field(None, description="Panel header text")
    dialogue: Optional[str] = Field(None, description="Panel dialogue text")
    mood: PanelMood = Field(default=PanelMood.NEUTRAL, description="Panel mood")

    # Generated instructions
    camera: PanelCamera = Field(..., description="Camera movement instructions")
    effects: PanelEffects = Field(
        default_factory=PanelEffects,
        description="Visual effects"
    )
    transition: PanelTransition = Field(
        default_factory=PanelTransition,
        description="Transition to next panel"
    )

    # User overrides (Phase 5.5)
    user_overrides: Optional[PanelOverrides] = Field(
        None,
        description="User overrides for camera/effects (None = use auto-generated)"
    )

    # Approval status
    is_approved: bool = Field(default=False, description="User approved this panel")

    # Preview video (if rendered)
    preview_url: Optional[str] = Field(None, description="URL to preview video clip")


# ============================================================================
# Project Model
# ============================================================================

class ComicVideoProject(BaseModel):
    """Complete video project."""
    project_id: str = Field(..., description="Unique project identifier")
    title: str = Field(..., description="Project title")

    # Source files
    comic_grid_url: str = Field(..., description="URL to master comic image")
    comic_json: Dict[str, Any] = Field(..., description="Panel metadata from generator")

    # Layout (parsed from JSON)
    layout: Optional[ComicLayout] = Field(None, description="Parsed grid layout")

    # Panel data
    panel_audio: List[PanelAudio] = Field(
        default_factory=list,
        description="Audio for each panel"
    )
    panel_instructions: List[PanelInstruction] = Field(
        default_factory=list,
        description="Instructions for each panel"
    )

    # Output settings
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.VERTICAL,
        description="Output aspect ratio (determines dimensions)"
    )
    output_width: int = Field(default=1080, description="Output video width")
    output_height: int = Field(default=1920, description="Output video height")
    fps: int = Field(default=30, description="Output frame rate")

    # Optional
    background_music_url: Optional[str] = Field(None, description="Background music URL")

    def get_output_dimensions(self) -> Tuple[int, int]:
        """Get output dimensions based on aspect ratio."""
        return self.aspect_ratio.dimensions

    # Status
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT)
    error_message: Optional[str] = Field(None, description="Error message if failed")

    # Output
    final_video_url: Optional[str] = Field(None, description="URL to final rendered video")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# Mood Presets (Phase 1 FFmpeg-only effects)
# ============================================================================

MOOD_EFFECT_PRESETS: Dict[PanelMood, PanelEffects] = {
    PanelMood.NEUTRAL: PanelEffects(
        ambient_effects=[],
        color_tint=None
    ),

    PanelMood.POSITIVE: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.3)
        ],
        color_tint="#FFD700",
        tint_opacity=0.1
    ),

    PanelMood.WARNING: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.PULSE, intensity=0.3),
            EffectInstance(effect_type=EffectType.VIGNETTE_LIGHT, intensity=0.4)
        ],
        color_tint="#FFA500",
        tint_opacity=0.1
    ),

    PanelMood.DANGER: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.4),
            EffectInstance(effect_type=EffectType.VIGNETTE, intensity=0.5)
        ],
        triggered_effects=[
            EffectInstance(
                effect_type=EffectType.SHAKE,
                intensity=0.3,
                start_ms=0,
                duration_ms=500
            )
        ],
        color_tint="#FF0000",
        tint_opacity=0.15
    ),

    PanelMood.CHAOS: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.SHAKE, intensity=0.5),
            EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.5),
            EffectInstance(effect_type=EffectType.VIGNETTE_HEAVY, intensity=0.6)
        ],
        color_tint="#FF0000",
        tint_opacity=0.2
    ),

    PanelMood.DRAMATIC: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.VIGNETTE_HEAVY, intensity=0.7)
        ],
        triggered_effects=[
            EffectInstance(
                effect_type=EffectType.ZOOM_PULSE,
                intensity=0.4,
                start_ms=0,
                duration_ms=400
            )
        ]
    ),

    PanelMood.CELEBRATION: PanelEffects(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.4),
            EffectInstance(effect_type=EffectType.PULSE, intensity=0.3)
        ],
        color_tint="#FFD700",
        tint_opacity=0.15
    )
}
