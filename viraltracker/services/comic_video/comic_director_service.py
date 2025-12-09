"""
Comic Director Service

Generates camera movement and effects instructions for comic panels.
Phase 1: Rule-based logic based on panel mood and content.
Phase 3: Agent-powered with content analysis.

This service is the "cinematographer" that decides:
- How the camera moves (zoom, pan, focus points)
- What effects to apply (vignette, color tint, shake)
- How to transition between panels
"""

import logging
import asyncio
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from .models import (
    PanelMood,
    EffectType,
    TransitionType,
    CameraEasing,
    ComicLayout,
    PanelBounds,
    FocusPoint,
    EffectInstance,
    PanelCamera,
    PanelEffects,
    PanelTransition,
    PanelInstruction,
    PanelOverrides,
    MOOD_EFFECT_PRESETS,
)
from ...core.database import get_supabase_client

logger = logging.getLogger(__name__)


# Content keywords that trigger specific effects
CONTENT_EFFECT_TRIGGERS: Dict[str, List[EffectInstance]] = {
    "fire": [
        EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.4),
    ],
    "burn": [
        EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.3),
    ],
    "money": [
        EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.4),
    ],
    "print": [
        EffectInstance(effect_type=EffectType.GREEN_GLOW, intensity=0.3),
    ],
    "flood": [
        EffectInstance(effect_type=EffectType.PULSE, intensity=0.4),
    ],
    "break": [
        EffectInstance(effect_type=EffectType.SHAKE, intensity=0.5, duration_ms=500),
    ],
    "crazy": [
        EffectInstance(effect_type=EffectType.SHAKE, intensity=0.3, duration_ms=400),
    ],
    "crash": [
        EffectInstance(effect_type=EffectType.SHAKE, intensity=0.6, duration_ms=600),
        EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.3),
    ],
    "panic": [
        EffectInstance(effect_type=EffectType.SHAKE, intensity=0.4, duration_ms=500),
        EffectInstance(effect_type=EffectType.VIGNETTE_HEAVY, intensity=0.6),
    ],
    "win": [
        EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.5),
        EffectInstance(effect_type=EffectType.PULSE, intensity=0.3),
    ],
    "victory": [
        EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.5),
    ],
    "grow": [
        EffectInstance(effect_type=EffectType.GREEN_GLOW, intensity=0.4),
    ],
    "subscribe": [
        EffectInstance(effect_type=EffectType.PULSE, intensity=0.3),
    ],
    "danger": [
        EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.4),
        EffectInstance(effect_type=EffectType.VIGNETTE, intensity=0.5),
    ],
    "warning": [
        EffectInstance(effect_type=EffectType.PULSE, intensity=0.4),
        EffectInstance(effect_type=EffectType.VIGNETTE_LIGHT, intensity=0.4),
    ],
}


class ComicDirectorService:
    """
    Service for generating cinematography instructions.

    Determines camera movement, effects, and transitions for each panel
    based on content analysis and mood detection.
    """

    def __init__(self):
        """Initialize Director Service."""
        self.supabase = get_supabase_client()
        logger.info("ComicDirectorService initialized")

    # =========================================================================
    # Layout Parsing
    # =========================================================================

    def parse_layout_from_json(self, comic_json: Dict[str, Any]) -> ComicLayout:
        """
        Parse comic JSON layout_recommendation into ComicLayout.

        Supports both:
        - grid_structure: [{row: 1, columns: 4, panels: [1,2,3,4]}, ...]
        - panel_arrangement: [["Panel 1", "Panel 2"], ...]

        Args:
            comic_json: Full comic JSON with layout_recommendation

        Returns:
            ComicLayout with grid dimensions and panel_cells mapping
        """
        layout_rec = comic_json.get("layout_recommendation", {})

        # Parse format (e.g., "4-4-4-3 grid" or "3 columns x 5 rows")
        format_str = layout_rec.get("format", "4 columns x 4 rows")
        cols, rows = self._parse_format_string(format_str)

        # Try grid_structure first (more explicit format)
        grid_structure = layout_rec.get("grid_structure", [])
        row_cols = {}
        if grid_structure:
            panel_cells, row_cols = self._parse_grid_structure(grid_structure)
            # Update rows from actual grid structure
            rows = len(grid_structure)
        else:
            # Fallback to panel_arrangement
            arrangement = layout_rec.get("panel_arrangement", [])
            panel_cells = self._parse_arrangement(arrangement, cols)

        # Get canvas dimensions from video_production or defaults
        video_prod = comic_json.get("video_production", {})
        canvas_size = video_prod.get("canvas_size", [1080, 1920])

        # For the source image, estimate based on grid
        # Actual image dimensions will be detected at render time
        canvas_width = comic_json.get("canvas_width", cols * 1000)
        canvas_height = comic_json.get("canvas_height", rows * 1000)

        layout = ComicLayout(
            grid_cols=cols,
            grid_rows=rows,
            total_panels=len(panel_cells),
            panel_cells=panel_cells,
            row_cols=row_cols,
            canvas_width=canvas_width,
            canvas_height=canvas_height
        )

        logger.info(
            f"Parsed layout: {cols}x{rows} grid, "
            f"{len(panel_cells)} panels, "
            f"{canvas_width}x{canvas_height}px canvas"
        )

        return layout

    def _parse_grid_structure(
        self,
        grid_structure: List[Dict[str, Any]]
    ) -> Tuple[Dict[int, List[Tuple[int, int]]], Dict[int, int]]:
        """
        Parse grid_structure format into panel_cells and row_cols mappings.

        Args:
            grid_structure: List of {row, columns, panels} dicts

        Returns:
            Tuple of:
            - Dict mapping panel_number -> list of (row, col) cells
            - Dict mapping row_index -> number of columns in that row
        """
        panel_cells = {}
        row_cols = {}

        for row_data in grid_structure:
            row_idx = row_data.get("row", 1) - 1  # Convert to 0-indexed
            panels = row_data.get("panels", [])
            num_cols = row_data.get("columns", len(panels))

            # Store the number of columns for this row
            row_cols[row_idx] = num_cols

            # Track actual column position (in case panels array has 0s as placeholders)
            col_idx = 0
            for panel_num in panels:
                if panel_num > 0:
                    panel_cells[panel_num] = [(row_idx, col_idx)]
                col_idx += 1

        return panel_cells, row_cols

    def _parse_format_string(self, format_str: str) -> Tuple[int, int]:
        """
        Parse layout format string into (columns, rows).

        Supports formats:
        - '3 columns x 5 rows' -> (3, 5)
        - '4-4-4-3 grid' -> (4, 4) based on grid_structure
        - '3x5' -> (3, 5)
        """
        format_lower = format_str.lower()

        try:
            # Handle "4-4-4-3 grid" format (columns per row)
            if "grid" in format_lower and "-" in format_str:
                # Parse "4-4-4-3" to get max columns and row count
                parts = format_str.split()[0].split("-")
                cols = max(int(p) for p in parts)
                rows = len(parts)
                return cols, rows

            # Handle "3 columns x 5 rows" format
            if "column" in format_lower and "row" in format_lower:
                nums = re.findall(r'\d+', format_str)
                if len(nums) >= 2:
                    return int(nums[0]), int(nums[1])

            # Handle simple "3x5" format
            if "x" in format_lower:
                nums = re.findall(r'\d+', format_str)
                if len(nums) >= 2:
                    return int(nums[0]), int(nums[1])

            # Fallback: extract any two numbers
            nums = re.findall(r'\d+', format_str)
            if len(nums) >= 2:
                return int(nums[0]), int(nums[1])

        except (ValueError, IndexError):
            pass

        logger.warning(f"Could not parse format '{format_str}', using default 4x4")
        return 4, 4

    def _parse_arrangement(
        self,
        arrangement: List[List[str]],
        cols: int
    ) -> Dict[int, List[Tuple[int, int]]]:
        """
        Parse panel_arrangement into panel_cells mapping.

        Handles wide panels that span multiple columns.
        """
        panel_cells = {}
        panel_num = 1

        for row_idx, row in enumerate(arrangement):
            col_idx = 0

            for item in row:
                # Check for wide panels
                span = 1
                item_lower = item.lower()

                if "spans 3 columns" in item_lower or "wide" in item_lower and "3" in item_lower:
                    span = 3
                elif "spans 2 columns" in item_lower or "wide" in item_lower and "2" in item_lower:
                    span = 2
                elif "spans" in item_lower:
                    # Try to extract span number
                    span_match = re.search(r'spans?\s*(\d+)', item_lower)
                    if span_match:
                        span = int(span_match.group(1))

                # Record cells for this panel
                cells = [(row_idx, col_idx + i) for i in range(span)]
                panel_cells[panel_num] = cells

                col_idx += span
                panel_num += 1

        return panel_cells

    def calculate_panel_bounds(
        self,
        panel_number: int,
        layout: ComicLayout
    ) -> PanelBounds:
        """
        Calculate the bounding box of a panel on the master canvas.

        Args:
            panel_number: Panel number (1-indexed)
            layout: Comic layout with grid info

        Returns:
            PanelBounds with normalized and pixel coordinates

        Raises:
            ValueError: If panel not found in layout
        """
        cells = layout.panel_cells.get(panel_number, [])
        if not cells:
            raise ValueError(f"Panel {panel_number} not found in layout")

        # Find which row this panel is in
        panel_row = cells[0][0]

        # Get number of columns for this specific row (or default to grid_cols)
        row_col_count = layout.row_cols.get(panel_row, layout.grid_cols)

        # Calculate cell dimensions using row-specific column count
        cell_width = layout.canvas_width / row_col_count
        cell_height = layout.canvas_height / layout.grid_rows

        # Find bounding box of all cells this panel occupies
        min_col = min(c[1] for c in cells)
        max_col = max(c[1] for c in cells)
        min_row = min(c[0] for c in cells)
        max_row = max(c[0] for c in cells)

        # Pixel bounds
        left = int(min_col * cell_width)
        right = int((max_col + 1) * cell_width)
        top = int(min_row * cell_height)
        bottom = int((max_row + 1) * cell_height)

        # Normalized values
        center_x = (left + right) / 2 / layout.canvas_width
        center_y = (top + bottom) / 2 / layout.canvas_height
        width = (right - left) / layout.canvas_width
        height = (bottom - top) / layout.canvas_height

        return PanelBounds(
            panel_number=panel_number,
            center_x=center_x,
            center_y=center_y,
            width=width,
            height=height,
            pixel_left=left,
            pixel_top=top,
            pixel_right=right,
            pixel_bottom=bottom
        )

    # =========================================================================
    # Mood Detection
    # =========================================================================

    def infer_panel_mood(
        self,
        panel: Dict[str, Any],
        comic_json: Dict[str, Any]
    ) -> PanelMood:
        """
        Infer mood from panel content and comic color_coding.

        Priority:
        1. Explicit 'mood' field in panel
        2. color_coding from visual_flow
        3. Content-based inference from text

        Args:
            panel: Single panel dict from comic JSON
            comic_json: Full comic JSON (for visual_flow.color_coding)

        Returns:
            PanelMood enum value
        """
        # Priority 1: Use explicit mood field if present
        explicit_mood = panel.get("mood", "").lower()
        if explicit_mood:
            mood_map = {
                "dramatic": PanelMood.DRAMATIC,
                "positive": PanelMood.POSITIVE,
                "negative": PanelMood.DANGER,
                "warning": PanelMood.WARNING,
                "danger": PanelMood.DANGER,
                "chaos": PanelMood.CHAOS,
                "chaotic": PanelMood.CHAOS,
                "chaotic_positive": PanelMood.CHAOS,  # Treat as chaos with positive color
                "celebration": PanelMood.CELEBRATION,
                "hopeful": PanelMood.POSITIVE,
                "contemplative": PanelMood.NEUTRAL,
                "neutral": PanelMood.NEUTRAL,
                "mixed": PanelMood.WARNING,  # Mixed emotions -> warning treatment
            }
            if explicit_mood in mood_map:
                return mood_map[explicit_mood]

        panel_type = panel.get("panel_type", "").lower()
        header = panel.get("header_text", "").lower()
        dialogue = panel.get("dialogue", "").lower()
        combined_text = f"{header} {dialogue}"

        # Check panel type
        if "title" in panel_type or "intro" in panel_type:
            return PanelMood.DRAMATIC

        if "outro" in panel_type or "cta" in panel_type:
            return PanelMood.CELEBRATION

        # Priority 2: Check color_coding from visual_flow
        visual_flow = comic_json.get("visual_flow", {})
        color_coding = visual_flow.get("color_coding", {})
        panel_num = panel.get("panel_number", 0)

        # Look for this panel in color_coding (handles "panel_1", "panels_2_3" formats)
        for color_key, color_value in color_coding.items():
            # Check if this panel number is mentioned in the key
            key_lower = color_key.lower()
            panel_str = str(panel_num)

            # Handle "panel_1" or "panels_5_6_7" format
            if f"panel_{panel_str}" in key_lower or f"panels_{panel_str}" in key_lower or f"_{panel_str}_" in key_lower or key_lower.endswith(f"_{panel_str}"):
                color_lower = color_value.lower() if isinstance(color_value, str) else ""
                if "chaos" in color_lower or "danger_red" in color_lower:
                    return PanelMood.CHAOS
                if "danger" in color_lower or "red" in color_lower:
                    return PanelMood.DANGER
                if "warning" in color_lower or "orange" in color_lower:
                    return PanelMood.WARNING
                if "celebration" in color_lower or "gold" in color_lower:
                    return PanelMood.CELEBRATION
                if "positive" in color_lower or "green" in color_lower:
                    return PanelMood.POSITIVE
                if "dramatic" in color_lower or "dark" in color_lower:
                    return PanelMood.DRAMATIC

        # Priority 3: Content-based mood detection
        danger_words = ["crash", "panic", "lose", "lost", "fail", "die", "death", "destroy", "poorer"]
        chaos_words = ["crazy", "insane", "hyperinflation", "collapse", "break"]
        warning_words = ["warning", "careful", "risk", "danger"]
        positive_words = ["win", "gain", "profit", "grow", "success", "value", "high", "smart"]
        celebration_words = ["celebrate", "victory", "win", "subscribe", "thanks", "own"]

        if any(word in combined_text for word in chaos_words):
            return PanelMood.CHAOS
        if any(word in combined_text for word in danger_words):
            return PanelMood.DANGER
        if any(word in combined_text for word in warning_words):
            return PanelMood.WARNING
        if any(word in combined_text for word in celebration_words):
            return PanelMood.CELEBRATION
        if any(word in combined_text for word in positive_words):
            return PanelMood.POSITIVE

        return PanelMood.NEUTRAL

    # =========================================================================
    # Instruction Generation
    # =========================================================================

    def generate_panel_instruction(
        self,
        panel: Dict[str, Any],
        comic_json: Dict[str, Any],
        layout: ComicLayout,
        audio_duration_ms: Optional[int] = None
    ) -> PanelInstruction:
        """
        Generate complete instructions for a single panel.

        Args:
            panel: Panel dict from comic JSON
            comic_json: Full comic JSON
            layout: Parsed ComicLayout
            audio_duration_ms: Audio duration (for timing)

        Returns:
            PanelInstruction with camera, effects, and transition
        """
        panel_number = panel.get("panel_number", 1)
        panel_type = panel.get("panel_type", "CONTENT")

        # Calculate duration
        duration_ms = self._calculate_duration(panel, audio_duration_ms)

        # Infer mood
        mood = self.infer_panel_mood(panel, comic_json)

        # Get panel bounds
        bounds = self.calculate_panel_bounds(panel_number, layout)

        # Generate camera instructions
        camera = self._generate_camera(panel, bounds, mood, duration_ms)

        # Generate effects (mood preset + content triggers)
        effects = self._generate_effects(panel, mood)

        # Generate transition
        next_panel = self._get_next_panel(panel_number, comic_json)
        transition = self._generate_transition(panel, next_panel, comic_json)

        return PanelInstruction(
            panel_number=panel_number,
            panel_type=panel_type,
            duration_ms=duration_ms,
            header_text=panel.get("header_text"),
            dialogue=panel.get("dialogue"),
            mood=mood,
            camera=camera,
            effects=effects,
            transition=transition,
            is_approved=False,
            preview_url=None
        )

    def generate_all_instructions(
        self,
        comic_json: Dict[str, Any],
        layout: ComicLayout,
        audio_durations: Optional[Dict[int, int]] = None
    ) -> List[PanelInstruction]:
        """
        Generate instructions for all panels.

        Args:
            comic_json: Full comic JSON
            layout: Parsed ComicLayout
            audio_durations: Map of panel_number -> duration_ms

        Returns:
            List of PanelInstruction for all panels
        """
        audio_durations = audio_durations or {}
        instructions = []

        panels = comic_json.get("panels", [])

        for panel in panels:
            panel_num = panel.get("panel_number", 0)
            if panel_num <= 0:
                continue

            duration_ms = audio_durations.get(panel_num)

            try:
                instruction = self.generate_panel_instruction(
                    panel=panel,
                    comic_json=comic_json,
                    layout=layout,
                    audio_duration_ms=duration_ms
                )
                instructions.append(instruction)

            except Exception as e:
                logger.error(f"Failed to generate instruction for panel {panel_num}: {e}")
                continue

        logger.info(f"Generated instructions for {len(instructions)} panels")
        return instructions

    # =========================================================================
    # Camera Generation
    # =========================================================================

    def _generate_camera(
        self,
        panel: Dict[str, Any],
        bounds: PanelBounds,
        mood: PanelMood,
        duration_ms: int
    ) -> PanelCamera:
        """Generate camera instructions based on panel content and mood."""
        panel_type = panel.get("panel_type", "").lower()

        # Default zoom behavior
        start_zoom = 1.0
        end_zoom = 1.15  # Slight zoom in

        # Adjust zoom based on panel type
        if "title" in panel_type:
            # Dramatic reveal for title
            start_zoom = 1.3
            end_zoom = 1.0
        elif "outro" in panel_type or "cta" in panel_type:
            # Slight zoom out for outro
            start_zoom = 1.1
            end_zoom = 1.0

        # Adjust zoom based on mood
        if mood == PanelMood.DRAMATIC:
            end_zoom = 1.3  # More dramatic zoom
        elif mood == PanelMood.CHAOS:
            # Varied zoom for chaos
            start_zoom = 1.0
            end_zoom = 1.2
        elif mood == PanelMood.CELEBRATION:
            start_zoom = 0.95
            end_zoom = 1.1

        # Choose easing based on mood
        easing = CameraEasing.EASE_IN_OUT
        if mood == PanelMood.CHAOS:
            easing = CameraEasing.LINEAR  # More frantic
        elif mood == PanelMood.DRAMATIC:
            easing = CameraEasing.EASE_OUT  # Dramatic slowdown

        return PanelCamera(
            panel_number=bounds.panel_number,
            center_x=bounds.center_x,
            center_y=bounds.center_y,
            start_zoom=start_zoom,
            end_zoom=end_zoom,
            pan_start=None,
            pan_end=None,
            focus_points=[],
            easing=easing,
            end_hold_ms=200
        )

    # =========================================================================
    # Effects Generation
    # =========================================================================

    def _generate_effects(
        self,
        panel: Dict[str, Any],
        mood: PanelMood
    ) -> PanelEffects:
        """Generate effects based on mood preset and content triggers."""
        # Start with mood preset
        base_effects = MOOD_EFFECT_PRESETS.get(mood, PanelEffects())

        # Copy to avoid modifying the preset
        effects = PanelEffects(
            ambient_effects=list(base_effects.ambient_effects),
            triggered_effects=list(base_effects.triggered_effects),
            color_tint=base_effects.color_tint,
            tint_opacity=base_effects.tint_opacity
        )

        # Detect content-triggered effects
        content_effects = self._detect_content_effects(panel)
        effects.triggered_effects.extend(content_effects)

        return effects

    def _detect_content_effects(
        self,
        panel: Dict[str, Any]
    ) -> List[EffectInstance]:
        """Detect effects to trigger based on dialogue/header keywords."""
        header = panel.get("header_text", "").lower()
        dialogue = panel.get("dialogue", "").lower()
        combined = f"{header} {dialogue}"

        triggered = []

        for keyword, effect_list in CONTENT_EFFECT_TRIGGERS.items():
            if keyword in combined:
                triggered.extend(effect_list)

        return triggered

    # =========================================================================
    # Transition Generation
    # =========================================================================

    def _generate_transition(
        self,
        current_panel: Dict[str, Any],
        next_panel: Optional[Dict[str, Any]],
        comic_json: Dict[str, Any]
    ) -> PanelTransition:
        """Generate transition to next panel based on context."""
        if next_panel is None:
            # Last panel - no transition needed
            return PanelTransition(
                transition_type=TransitionType.CUT,
                duration_ms=0,
                easing=CameraEasing.LINEAR
            )

        current_type = current_panel.get("panel_type", "").lower()
        next_type = next_panel.get("panel_type", "").lower()

        # Determine transition type based on context
        transition_type = TransitionType.PAN
        duration_ms = 400

        # Title to content: elegant glide
        if "title" in current_type:
            transition_type = TransitionType.GLIDE
            duration_ms = 600

        # Act change: zoom out/in
        current_act = self._extract_act(current_type)
        next_act = self._extract_act(next_type)
        if current_act != next_act and current_act and next_act:
            transition_type = TransitionType.ZOOM_OUT_IN
            duration_ms = 700

        # Dramatic to anything: snap
        current_mood = self.infer_panel_mood(current_panel, comic_json)
        if current_mood == PanelMood.DRAMATIC:
            transition_type = TransitionType.SNAP
            duration_ms = 300

        # Chaos: whip pan
        if current_mood == PanelMood.CHAOS:
            transition_type = TransitionType.WHIP
            duration_ms = 250

        # To outro: fade
        if "outro" in next_type or "cta" in next_type:
            transition_type = TransitionType.FADE
            duration_ms = 500

        return PanelTransition(
            transition_type=transition_type,
            duration_ms=duration_ms,
            easing=CameraEasing.EASE_IN_OUT,
            transition_effects=[]
        )

    def _extract_act(self, panel_type: str) -> Optional[str]:
        """Extract act identifier from panel type (e.g., 'ACT 1' from 'ACT 1 - CONTENT')."""
        match = re.search(r'act\s*(\d+)', panel_type.lower())
        return match.group(1) if match else None

    def _get_next_panel(
        self,
        current_panel_number: int,
        comic_json: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get the next panel in sequence."""
        panels = comic_json.get("panels", [])
        for panel in panels:
            if panel.get("panel_number") == current_panel_number + 1:
                return panel
        return None

    # =========================================================================
    # Duration Calculation
    # =========================================================================

    def _calculate_duration(
        self,
        panel: Dict[str, Any],
        audio_duration_ms: Optional[int]
    ) -> int:
        """
        Calculate panel duration.

        Primary: audio duration + buffer
        Fallback: estimate from text length
        """
        if audio_duration_ms:
            # Add 500ms buffer after audio
            return audio_duration_ms + 500

        # Fallback: estimate from text
        header = panel.get("header_text", "")
        dialogue = panel.get("dialogue", "")
        total_chars = len(header) + len(dialogue)

        # Rough estimate: 150ms per character (average speaking rate)
        # Plus 1 second minimum
        estimated_ms = max(1000, total_chars * 80 + 500)

        return estimated_ms

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def save_panel_instruction(
        self,
        project_id: str,
        instruction: PanelInstruction
    ) -> None:
        """Save panel instruction to database."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions").upsert({
                "project_id": project_id,
                "panel_number": instruction.panel_number,
                "panel_type": instruction.panel_type,
                "duration_ms": instruction.duration_ms,
                "header_text": instruction.header_text,
                "dialogue": instruction.dialogue,
                "mood": instruction.mood.value,
                "camera_json": instruction.camera.model_dump(mode="json"),
                "effects_json": instruction.effects.model_dump(mode="json"),
                "transition_json": instruction.transition.model_dump(mode="json"),
                "is_approved": instruction.is_approved,
                "preview_url": instruction.preview_url
            }).execute()
        )

    async def get_panel_instruction(
        self,
        project_id: str,
        panel_number: int
    ) -> Optional[PanelInstruction]:
        """Get instruction for a specific panel."""
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .select("*")
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .maybe_single()
                .execute()
        )

        if not result.data:
            return None

        return self._row_to_instruction(result.data)

    async def get_all_instructions(
        self,
        project_id: str
    ) -> List[PanelInstruction]:
        """Get all instructions for a project."""
        result = await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .select("*")
                .eq("project_id", project_id)
                .order("panel_number")
                .execute()
        )

        return [self._row_to_instruction(row) for row in result.data]

    async def approve_instruction(
        self,
        project_id: str,
        panel_number: int
    ) -> None:
        """Mark panel instruction as approved."""
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .update({"is_approved": True})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )

    def _row_to_instruction(self, row: Dict[str, Any]) -> PanelInstruction:
        """Convert database row to PanelInstruction."""
        # Parse user_overrides if present
        user_overrides = None
        if row.get("user_overrides"):
            user_overrides = PanelOverrides(**row["user_overrides"])

        return PanelInstruction(
            panel_number=row["panel_number"],
            panel_type=row["panel_type"],
            duration_ms=row["duration_ms"],
            header_text=row.get("header_text"),
            dialogue=row.get("dialogue"),
            mood=PanelMood(row.get("mood", "neutral")),
            camera=PanelCamera(**row["camera_json"]),
            effects=PanelEffects(**row["effects_json"]),
            transition=PanelTransition(**row["transition_json"]),
            user_overrides=user_overrides,
            is_approved=row.get("is_approved", False),
            preview_url=row.get("preview_url")
        )

    # =========================================================================
    # Override Application (Phase 5.5)
    # =========================================================================

    def apply_overrides(
        self,
        instruction: PanelInstruction,
        overrides: PanelOverrides
    ) -> PanelInstruction:
        """
        Apply user overrides to auto-generated panel instruction.

        Creates a new PanelInstruction with overrides applied. The original
        instruction is not modified.

        Args:
            instruction: Original auto-generated instruction
            overrides: User overrides to apply

        Returns:
            New PanelInstruction with overrides applied
        """
        if not overrides.has_overrides():
            # No overrides, return original with overrides attached
            return instruction.model_copy(update={"user_overrides": overrides})

        # Deep copy to avoid modifying original
        updated = instruction.model_copy(deep=True)

        # Apply mood override first (affects effect preset)
        if overrides.mood_override is not None:
            updated.mood = overrides.mood_override
            # Regenerate effects from new mood preset
            base_effects = MOOD_EFFECT_PRESETS.get(overrides.mood_override, PanelEffects())
            updated.effects = PanelEffects(
                ambient_effects=list(base_effects.ambient_effects),
                triggered_effects=list(base_effects.triggered_effects),
                color_tint=base_effects.color_tint,
                tint_opacity=base_effects.tint_opacity
            )

        # Apply camera overrides
        updated.camera = self._apply_camera_overrides(updated.camera, overrides)

        # Apply effect overrides
        updated.effects = self._apply_effect_overrides(updated.effects, overrides)

        # Store overrides on the instruction
        updated.user_overrides = overrides

        logger.info(f"Applied overrides to panel {instruction.panel_number}")
        return updated

    def _apply_camera_overrides(
        self,
        camera: PanelCamera,
        overrides: PanelOverrides
    ) -> PanelCamera:
        """Apply camera-related overrides."""
        updated = camera.model_copy(deep=True)

        if overrides.camera_start_zoom is not None:
            updated.start_zoom = overrides.camera_start_zoom

        if overrides.camera_end_zoom is not None:
            updated.end_zoom = overrides.camera_end_zoom

        if overrides.camera_easing is not None:
            updated.easing = overrides.camera_easing

        # Apply custom focus point if specified
        if overrides.camera_focus_x is not None or overrides.camera_focus_y is not None:
            # Use provided values or default to center (0.5)
            focus_x = overrides.camera_focus_x if overrides.camera_focus_x is not None else 0.5
            focus_y = overrides.camera_focus_y if overrides.camera_focus_y is not None else 0.5

            # Add or replace focus point
            updated.focus_points = [FocusPoint(x=focus_x, y=focus_y, hold_ms=0, zoom_boost=0)]

        return updated

    def _apply_effect_overrides(
        self,
        effects: PanelEffects,
        overrides: PanelOverrides
    ) -> PanelEffects:
        """Apply effect-related overrides."""
        updated = effects.model_copy(deep=True)

        # Helper to toggle effect type on/off
        def toggle_effect(
            effect_type: EffectType,
            enabled: Optional[bool],
            intensity: Optional[float],
            also_remove: Optional[List[EffectType]] = None,
            extra_params: Optional[Dict[str, Any]] = None
        ):
            """Toggle an effect on/off with optional intensity.

            Args:
                effect_type: The effect type to add if enabled
                enabled: Whether to enable the effect
                intensity: Effect intensity (0.0-1.0)
                also_remove: Additional effect types to remove (for variants)
                extra_params: Additional effect-specific parameters
            """
            if enabled is None and intensity is None:
                return  # No override, keep as-is

            # Build list of effect types to remove
            types_to_remove = {effect_type}
            if also_remove:
                types_to_remove.update(also_remove)

            # Find and remove existing effects of these types
            updated.ambient_effects = [
                e for e in updated.ambient_effects
                if e.effect_type not in types_to_remove
            ]
            updated.triggered_effects = [
                e for e in updated.triggered_effects
                if e.effect_type not in types_to_remove
            ]

            # Add effect if enabled (or intensity specified implies enabled)
            if enabled is True or (enabled is None and intensity is not None):
                effect_intensity = intensity if intensity is not None else 0.5
                effect_params = extra_params or {}
                updated.ambient_effects.append(
                    EffectInstance(
                        effect_type=effect_type,
                        intensity=effect_intensity,
                        params=effect_params
                    )
                )

        # All vignette variants to remove when toggling vignette
        vignette_variants = [EffectType.VIGNETTE_LIGHT, EffectType.VIGNETTE_HEAVY]

        # Build vignette params (softness if specified)
        vignette_params = {}
        if overrides.vignette_softness is not None:
            vignette_params["softness"] = overrides.vignette_softness

        # Apply vignette toggle (removes all vignette variants)
        toggle_effect(
            EffectType.VIGNETTE,
            overrides.vignette_enabled,
            overrides.vignette_intensity,
            also_remove=vignette_variants,
            extra_params=vignette_params if vignette_params else None
        )

        # Apply shake toggle
        toggle_effect(
            EffectType.SHAKE,
            overrides.shake_enabled,
            overrides.shake_intensity
        )

        # Apply pulse toggle
        toggle_effect(
            EffectType.PULSE,
            overrides.pulse_enabled,
            overrides.pulse_intensity
        )

        # Apply golden glow toggle
        toggle_effect(
            EffectType.GOLDEN_GLOW,
            overrides.golden_glow_enabled,
            overrides.golden_glow_intensity
        )

        # Apply red glow toggle
        toggle_effect(
            EffectType.RED_GLOW,
            overrides.red_glow_enabled,
            overrides.red_glow_intensity
        )

        # Apply color tint override
        if overrides.color_tint_enabled is False:
            updated.color_tint = None
            updated.tint_opacity = 0.0
        elif overrides.color_tint_enabled is True or overrides.color_tint_color is not None:
            if overrides.color_tint_color is not None:
                updated.color_tint = overrides.color_tint_color
            elif updated.color_tint is None:
                updated.color_tint = "#FFD700"  # Default to gold

            if overrides.color_tint_opacity is not None:
                updated.tint_opacity = overrides.color_tint_opacity
            elif updated.tint_opacity == 0.0:
                updated.tint_opacity = 0.15  # Default opacity

        return updated

    async def save_overrides(
        self,
        project_id: str,
        panel_number: int,
        overrides: PanelOverrides
    ) -> None:
        """
        Save user overrides to database.

        Args:
            project_id: Project ID
            panel_number: Panel number
            overrides: Overrides to save
        """
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .update({"user_overrides": overrides.model_dump(mode="json")})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )
        logger.info(f"Saved overrides for project {project_id} panel {panel_number}")

    async def clear_overrides(
        self,
        project_id: str,
        panel_number: int
    ) -> None:
        """
        Clear user overrides (reset to auto).

        Args:
            project_id: Project ID
            panel_number: Panel number
        """
        await asyncio.to_thread(
            lambda: self.supabase.table("comic_panel_instructions")
                .update({"user_overrides": None})
                .eq("project_id", project_id)
                .eq("panel_number", panel_number)
                .execute()
        )
        logger.info(f"Cleared overrides for project {project_id} panel {panel_number}")
