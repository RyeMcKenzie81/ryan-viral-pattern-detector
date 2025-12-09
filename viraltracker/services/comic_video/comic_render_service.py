"""
Comic Render Service

Handles FFmpeg video rendering for comic panel videos.
Generates Ken Burns camera movement, applies effects, and concatenates panels.

Phase 1: FFmpeg-only effects (no external particle assets)
"""

import logging
import asyncio
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import uuid

from .models import (
    EffectType,
    TransitionType,
    CameraEasing,
    ComicLayout,
    PanelCamera,
    PanelEffects,
    PanelTransition,
    PanelInstruction,
    EffectInstance,
)
from ..ffmpeg_service import FFmpegService
from ...core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ComicRenderService:
    """
    Service for rendering comic panel videos using FFmpeg.

    Uses zoompan filter for Ken Burns effect and various filters for effects.
    """

    STORAGE_BUCKET = "comic-video"

    # Output settings
    DEFAULT_OUTPUT_WIDTH = 1080
    DEFAULT_OUTPUT_HEIGHT = 1920
    DEFAULT_FPS = 30

    def __init__(self, ffmpeg: Optional[FFmpegService] = None):
        """
        Initialize Render Service.

        Args:
            ffmpeg: FFmpeg service instance
        """
        self.ffmpeg = ffmpeg or FFmpegService()
        self.supabase = get_supabase_client()

        # FFmpeg paths
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._ffprobe_path = shutil.which("ffprobe")

        # Local output directory
        self.output_base = Path("comic_video_renders")
        self.output_base.mkdir(exist_ok=True)

        if not self._ffmpeg_path:
            logger.warning("FFmpeg not found. Video rendering will be unavailable.")
        else:
            logger.info("ComicRenderService initialized")

    @property
    def available(self) -> bool:
        """Check if FFmpeg is available."""
        return bool(self._ffmpeg_path)

    # =========================================================================
    # Panel Preview Rendering
    # =========================================================================

    async def render_panel_preview(
        self,
        project_id: str,
        panel_number: int,
        comic_grid_path: Path,
        instruction: PanelInstruction,
        layout: ComicLayout,
        audio_path: Optional[Path] = None,
        output_width: int = DEFAULT_OUTPUT_WIDTH,
        output_height: int = DEFAULT_OUTPUT_HEIGHT
    ) -> str:
        """
        Render a single panel preview video.

        Args:
            project_id: Project UUID
            panel_number: Panel number
            comic_grid_path: Path to comic grid image
            instruction: Panel instruction with camera/effects
            layout: Comic layout
            audio_path: Optional audio file to include
            output_width: Output video width
            output_height: Output video height

        Returns:
            Path to rendered preview video
        """
        if not self.available:
            raise RuntimeError("FFmpeg not available")

        # Create output directory
        project_dir = self.output_base / project_id / "previews"
        project_dir.mkdir(parents=True, exist_ok=True)

        output_path = project_dir / f"panel_{panel_number:02d}_preview.mp4"

        logger.info(f"Rendering preview for panel {panel_number}")

        # Detect actual image dimensions and update layout
        actual_width, actual_height = await self._get_image_dimensions(comic_grid_path)
        if actual_width and actual_height:
            # Update layout with actual dimensions for accurate panel positioning
            layout = ComicLayout(
                grid_cols=layout.grid_cols,
                grid_rows=layout.grid_rows,
                total_panels=layout.total_panels,
                panel_cells=layout.panel_cells,
                canvas_width=actual_width,
                canvas_height=actual_height
            )
            logger.info(f"Using actual image dimensions: {actual_width}x{actual_height}")

        # Build FFmpeg command
        cmd = self._build_panel_render_command(
            grid_path=comic_grid_path,
            instruction=instruction,
            layout=layout,
            output_path=output_path,
            audio_path=audio_path,
            output_width=output_width,
            output_height=output_height
        )

        # Execute render
        await self._run_ffmpeg(cmd)

        logger.info(f"Rendered preview: {output_path}")
        return str(output_path)

    def _build_panel_render_command(
        self,
        grid_path: Path,
        instruction: PanelInstruction,
        layout: ComicLayout,
        output_path: Path,
        audio_path: Optional[Path] = None,
        output_width: int = DEFAULT_OUTPUT_WIDTH,
        output_height: int = DEFAULT_OUTPUT_HEIGHT
    ) -> List[str]:
        """Build FFmpeg command for single panel render."""
        duration_sec = instruction.duration_ms / 1000
        fps = self.DEFAULT_FPS
        total_frames = int(duration_sec * fps)

        # Build zoompan filter for Ken Burns effect
        zoompan_filter = self._build_zoompan_filter(
            camera=instruction.camera,
            layout=layout,
            duration_frames=total_frames,
            output_size=(output_width, output_height),
            fps=fps
        )

        # Build effects filter chain
        effects_filter = self._build_effects_filter(
            effects=instruction.effects,
            duration_ms=instruction.duration_ms
        )

        # Combine filters
        if effects_filter:
            filter_complex = f"{zoompan_filter},{effects_filter}"
        else:
            filter_complex = zoompan_filter

        # Build command
        cmd = [
            self._ffmpeg_path,
            "-y",  # Overwrite output
            "-loop", "1",  # Loop input image
            "-i", str(grid_path),  # Input image
        ]

        # Add audio input if provided
        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])

        # Video filters
        cmd.extend([
            "-filter_complex", filter_complex,
            "-t", str(duration_sec),  # Duration
            "-c:v", "libx264",  # Video codec
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
        ])

        # Audio settings
        if audio_path and audio_path.exists():
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",  # End when shortest stream ends
            ])
        else:
            cmd.extend(["-an"])  # No audio

        cmd.append(str(output_path))

        return cmd

    # =========================================================================
    # Full Video Rendering
    # =========================================================================

    async def render_full_video(
        self,
        project_id: str,
        comic_grid_path: Path,
        instructions: List[PanelInstruction],
        layout: ComicLayout,
        audio_paths: Dict[int, Path],
        output_width: int = DEFAULT_OUTPUT_WIDTH,
        output_height: int = DEFAULT_OUTPUT_HEIGHT,
        background_music_path: Optional[Path] = None
    ) -> str:
        """
        Render complete video from all panels.

        Args:
            project_id: Project UUID
            comic_grid_path: Path to comic grid image
            instructions: All panel instructions
            layout: Comic layout
            audio_paths: Map of panel_number -> audio file path
            output_width: Output video width
            output_height: Output video height
            background_music_path: Optional background music

        Returns:
            Path to final rendered video
        """
        if not self.available:
            raise RuntimeError("FFmpeg not available")

        project_dir = self.output_base / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Detect actual image dimensions and update layout
        actual_width, actual_height = await self._get_image_dimensions(comic_grid_path)
        if actual_width and actual_height:
            layout = ComicLayout(
                grid_cols=layout.grid_cols,
                grid_rows=layout.grid_rows,
                total_panels=layout.total_panels,
                panel_cells=layout.panel_cells,
                canvas_width=actual_width,
                canvas_height=actual_height
            )
            logger.info(f"Using actual image dimensions: {actual_width}x{actual_height}")

        # Strategy: Render each panel as a segment, then concatenate
        # This is more reliable than a single complex filter graph

        logger.info(f"Rendering full video with {len(instructions)} panels")

        # 1. Render each panel segment (with transition to next panel)
        segment_paths = []
        for i, instruction in enumerate(instructions):
            panel_num = instruction.panel_number
            audio_path = audio_paths.get(panel_num)

            # Get next instruction for transition target (if not last panel)
            next_instruction = instructions[i + 1] if i < len(instructions) - 1 else None

            segment_path = project_dir / f"segment_{panel_num:02d}.mp4"

            await self._render_segment_with_transition(
                grid_path=comic_grid_path,
                instruction=instruction,
                next_instruction=next_instruction,
                layout=layout,
                output_path=segment_path,
                audio_path=audio_path,
                output_width=output_width,
                output_height=output_height
            )

            segment_paths.append(segment_path)

        # 2. Concatenate segments
        concat_path = project_dir / "concat.mp4"
        await self._concatenate_segments(segment_paths, concat_path)

        # 3. Add background music if provided
        if background_music_path and background_music_path.exists():
            final_path = project_dir / "final.mp4"
            await self._mix_background_music(concat_path, background_music_path, final_path)
        else:
            final_path = concat_path

        logger.info(f"Rendered full video: {final_path}")
        return str(final_path)

    async def _render_segment_with_transition(
        self,
        grid_path: Path,
        instruction: PanelInstruction,
        next_instruction: Optional[PanelInstruction],
        layout: ComicLayout,
        output_path: Path,
        audio_path: Optional[Path],
        output_width: int,
        output_height: int
    ) -> None:
        """
        Render a segment: panel content + transition to next panel.

        The segment consists of:
        1. Main content: Ken Burns on current panel (synced with audio)
        2. Transition: Camera moves from current panel to next panel position
        """
        fps = self.DEFAULT_FPS

        # Calculate durations
        content_duration_ms = instruction.duration_ms
        transition_duration_ms = instruction.transition.duration_ms if next_instruction else 0

        # No transition for last panel or CUT transitions
        if not next_instruction or instruction.transition.transition_type.value == "cut":
            transition_duration_ms = 0

        total_duration_ms = content_duration_ms + transition_duration_ms
        total_duration_sec = total_duration_ms / 1000
        total_frames = int(total_duration_sec * fps)

        content_frames = int((content_duration_ms / 1000) * fps)
        transition_frames = total_frames - content_frames

        # Build zoompan filter with transition
        zoompan_filter = self._build_zoompan_with_transition(
            camera=instruction.camera,
            next_camera=next_instruction.camera if next_instruction else None,
            transition=instruction.transition,
            layout=layout,
            content_frames=content_frames,
            transition_frames=transition_frames,
            output_size=(output_width, output_height),
            fps=fps
        )

        # Build effects filter (only for content portion)
        effects_filter = self._build_effects_filter(
            effects=instruction.effects,
            duration_ms=content_duration_ms
        )

        # Combine filters
        if effects_filter:
            filter_complex = f"{zoompan_filter},{effects_filter}"
        else:
            filter_complex = zoompan_filter

        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(grid_path),
        ]

        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-t", str(total_duration_sec),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
        ])

        if audio_path and audio_path.exists():
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "128k",
            ])
        else:
            cmd.extend(["-an"])

        cmd.append(str(output_path))

        logger.info(
            f"Rendering panel {instruction.panel_number}: "
            f"{content_duration_ms}ms content + {transition_duration_ms}ms transition"
        )

        await self._run_ffmpeg(cmd)

    async def _concatenate_segments(
        self,
        segment_paths: List[Path],
        output_path: Path
    ) -> None:
        """Concatenate video segments using FFmpeg concat demuxer."""
        # Create concat list file
        concat_list = output_path.parent / "concat_list.txt"
        with open(concat_list, "w") as f:
            for path in segment_paths:
                # Use absolute path to avoid path resolution issues
                abs_path = path.resolve()
                # Escape single quotes
                escaped = str(abs_path).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            self._ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",  # Just copy streams, no re-encoding
            str(output_path)
        ]

        await self._run_ffmpeg(cmd)

        # Cleanup
        concat_list.unlink(missing_ok=True)

    async def _mix_background_music(
        self,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        music_volume: float = 0.15
    ) -> None:
        """Mix background music with video audio."""
        cmd = [
            self._ffmpeg_path,
            "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ]

        await self._run_ffmpeg(cmd)

    # =========================================================================
    # FFmpeg Filter Builders
    # =========================================================================

    def _build_zoompan_filter(
        self,
        camera: PanelCamera,
        layout: ComicLayout,
        duration_frames: int,
        output_size: Tuple[int, int],
        fps: int
    ) -> str:
        """
        Build zoompan filter for Ken Burns effect.

        The zoompan filter zooms into a specific panel on the comic grid.

        Key concept: zoompan's 'z' parameter = output_size / visible_input_size
        - z=1 means 1:1 (see entire input at output resolution)
        - z=4 means zoomed in 4x (see 1/4 of input width/height)

        For a 4x4 grid, we need z≈4 to show one panel filling the frame.
        """
        out_w, out_h = output_size
        canvas_w, canvas_h = layout.canvas_width, layout.canvas_height

        # Calculate the zoom needed to fill the output with a single panel
        # Panel width = canvas_width / grid_cols
        # To fill output_width with panel_width, we need:
        # zoom = canvas_width / panel_width = grid_cols (approximately)

        # For vertical video (1080x1920) viewing a square-ish panel,
        # we want the panel width to fill the frame width
        panel_width = canvas_w / layout.grid_cols
        panel_height = canvas_h / layout.grid_rows

        # Base zoom to fit panel width into output width
        # (we zoom based on width since vertical video is narrower)
        base_zoom_w = canvas_w / panel_width  # = grid_cols
        base_zoom_h = canvas_h / panel_height  # = grid_rows

        # Use width-based zoom (panel fills width, may crop top/bottom)
        # Multiply by 0.85 to leave a small margin showing neighboring panels
        panel_zoom = base_zoom_w * 0.85

        # Apply camera zoom modifiers (1.0 = panel fills frame, 1.2 = tighter)
        z_start = panel_zoom * camera.start_zoom
        z_end = panel_zoom * camera.end_zoom

        # Zoom expression: interpolate from start to end over duration
        z_expr = f"'{z_start:.2f}+({z_end - z_start:.2f})*on/{duration_frames}'"

        # Position expressions - center on the panel
        # camera.center_x/y are normalized (0-1) positions on the canvas
        cx_px = camera.center_x * canvas_w
        cy_px = camera.center_y * canvas_h

        # x,y = top-left corner of visible area
        # To center on (cx, cy): x = cx - visible_width/2 = cx - (out_w/zoom)/2
        # But zoompan uses input coordinates, so: x = cx - iw/(2*zoom)
        x_expr = f"'{cx_px:.1f}-iw/zoom/2'"
        y_expr = f"'{cy_px:.1f}-ih/zoom/2'"

        # Build zoompan filter
        zoompan = (
            f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
            f":d={duration_frames}:s={out_w}x{out_h}:fps={fps}"
        )

        logger.debug(
            f"Zoompan: panel at ({camera.center_x:.2f}, {camera.center_y:.2f}), "
            f"zoom {z_start:.1f} -> {z_end:.1f}"
        )

        return zoompan

    def _build_zoompan_with_transition(
        self,
        camera: PanelCamera,
        next_camera: Optional[PanelCamera],
        transition: PanelTransition,
        layout: ComicLayout,
        content_frames: int,
        transition_frames: int,
        output_size: Tuple[int, int],
        fps: int
    ) -> str:
        """
        Build zoompan filter that includes transition to next panel.

        Structure:
        - Frames 0 to content_frames: Ken Burns on current panel
        - Frames content_frames to total: Animate to next panel position

        Args:
            camera: Current panel camera settings
            next_camera: Next panel camera settings (None if last panel)
            transition: Transition settings
            layout: Comic layout with dimensions
            content_frames: Number of frames for panel content
            transition_frames: Number of frames for transition
            output_size: Output video dimensions
            fps: Frames per second
        """
        out_w, out_h = output_size
        canvas_w, canvas_h = layout.canvas_width, layout.canvas_height
        total_frames = content_frames + transition_frames

        # Calculate panel zoom (same logic as _build_zoompan_filter)
        panel_width = canvas_w / layout.grid_cols
        panel_zoom = (canvas_w / panel_width) * 0.85  # = grid_cols * 0.85

        # Current panel positions (in pixels)
        curr_cx = camera.center_x * canvas_w
        curr_cy = camera.center_y * canvas_h
        curr_z_start = panel_zoom * camera.start_zoom
        curr_z_end = panel_zoom * camera.end_zoom

        # If no transition or no next panel, use simple zoompan
        if transition_frames == 0 or next_camera is None:
            z_expr = f"'{curr_z_start:.2f}+({curr_z_end - curr_z_start:.2f})*on/{content_frames}'"
            x_expr = f"'{curr_cx:.1f}-iw/zoom/2'"
            y_expr = f"'{curr_cy:.1f}-ih/zoom/2'"

            return (
                f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
                f":d={total_frames}:s={out_w}x{out_h}:fps={fps}"
            )

        # Next panel positions
        next_cx = next_camera.center_x * canvas_w
        next_cy = next_camera.center_y * canvas_h
        next_z_start = panel_zoom * next_camera.start_zoom

        # Build expressions with two phases:
        # Phase 1 (content): on < content_frames - zoom within current panel
        # Phase 2 (transition): on >= content_frames - animate to next panel

        # Zoom expression:
        # During content: interpolate curr_z_start -> curr_z_end
        # During transition: interpolate curr_z_end -> next_z_start
        z_expr = (
            f"'if(lt(on,{content_frames}),"
            f"{curr_z_start:.2f}+({curr_z_end - curr_z_start:.2f})*on/{content_frames},"
            f"{curr_z_end:.2f}+({next_z_start - curr_z_end:.2f})*(on-{content_frames})/{transition_frames})'"
        )

        # X position expression:
        # During content: stay centered on current panel
        # During transition: interpolate from curr_cx to next_cx
        x_expr = (
            f"'if(lt(on,{content_frames}),"
            f"{curr_cx:.1f}-iw/zoom/2,"
            f"{curr_cx:.1f}+({next_cx - curr_cx:.1f})*(on-{content_frames})/{transition_frames}-iw/zoom/2)'"
        )

        # Y position expression (same logic)
        y_expr = (
            f"'if(lt(on,{content_frames}),"
            f"{curr_cy:.1f}-ih/zoom/2,"
            f"{curr_cy:.1f}+({next_cy - curr_cy:.1f})*(on-{content_frames})/{transition_frames}-ih/zoom/2)'"
        )

        zoompan = (
            f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
            f":d={total_frames}:s={out_w}x{out_h}:fps={fps}"
        )

        logger.debug(
            f"Zoompan with transition: ({curr_cx:.0f},{curr_cy:.0f}) -> ({next_cx:.0f},{next_cy:.0f}), "
            f"{content_frames} content + {transition_frames} transition frames"
        )

        return zoompan

    def _build_effects_filter(
        self,
        effects: PanelEffects,
        duration_ms: int
    ) -> str:
        """Build FFmpeg filter chain for all effects."""
        filters = []

        # Color tint
        if effects.color_tint and effects.tint_opacity > 0:
            tint_filter = self._build_color_tint_filter(
                effects.color_tint,
                effects.tint_opacity
            )
            if tint_filter:
                filters.append(tint_filter)

        # Ambient effects
        for effect in effects.ambient_effects:
            effect_filter = self._build_effect_filter(effect, duration_ms)
            if effect_filter:
                filters.append(effect_filter)

        # Triggered effects (with enable expressions for timing)
        for effect in effects.triggered_effects:
            effect_filter = self._build_effect_filter(
                effect,
                duration_ms,
                with_timing=True
            )
            if effect_filter:
                filters.append(effect_filter)

        return ",".join(filters) if filters else ""

    def _build_effect_filter(
        self,
        effect: EffectInstance,
        duration_ms: int,
        with_timing: bool = False
    ) -> Optional[str]:
        """Build filter for a single effect."""
        effect_type = effect.effect_type
        intensity = effect.intensity

        filter_str = None

        if effect_type == EffectType.VIGNETTE:
            filter_str = self._vignette_filter(intensity * 0.5)

        elif effect_type == EffectType.VIGNETTE_LIGHT:
            filter_str = self._vignette_filter(intensity * 0.3)

        elif effect_type == EffectType.VIGNETTE_HEAVY:
            filter_str = self._vignette_filter(intensity * 0.7)

        elif effect_type == EffectType.GOLDEN_GLOW:
            filter_str = self._build_color_tint_filter("#FFD700", intensity * 0.2)

        elif effect_type == EffectType.RED_GLOW:
            filter_str = self._build_color_tint_filter("#FF4444", intensity * 0.2)

        elif effect_type == EffectType.GREEN_GLOW:
            filter_str = self._build_color_tint_filter("#44FF44", intensity * 0.2)

        elif effect_type == EffectType.PULSE:
            filter_str = self._pulse_filter(intensity)

        elif effect_type == EffectType.SHAKE:
            shake_duration = effect.duration_ms or 500
            filter_str = self._shake_filter(intensity, shake_duration)

        elif effect_type == EffectType.FLASH:
            flash_duration = effect.duration_ms or 200
            filter_str = self._flash_filter(intensity, flash_duration)

        elif effect_type == EffectType.ZOOM_PULSE:
            # Zoom pulse is handled in zoompan, skip here
            pass

        # Add timing enable expression if needed
        if filter_str and with_timing and effect.start_ms > 0:
            start_sec = effect.start_ms / 1000
            end_sec = (effect.start_ms + (effect.duration_ms or duration_ms)) / 1000
            filter_str = f"{filter_str}:enable='between(t,{start_sec},{end_sec})'"

        return filter_str

    def _build_color_tint_filter(
        self,
        color_hex: str,
        opacity: float
    ) -> str:
        """Build colorbalance filter for color tint."""
        # Parse hex color
        hex_clean = color_hex.lstrip("#")
        r = int(hex_clean[0:2], 16) / 255
        g = int(hex_clean[2:4], 16) / 255
        b = int(hex_clean[4:6], 16) / 255

        # Calculate color balance shifts
        # Shift toward the tint color
        rs = (r - 0.5) * opacity
        gs = (g - 0.5) * opacity
        bs = (b - 0.5) * opacity

        return f"colorbalance=rs={rs:.3f}:gs={gs:.3f}:bs={bs:.3f}:rm={rs:.3f}:gm={gs:.3f}:bm={bs:.3f}"

    def _vignette_filter(self, intensity: float) -> str:
        """Build vignette filter."""
        # angle controls vignette spread (PI/4 to PI/2)
        angle = 0.4 + (intensity * 0.4)
        return f"vignette=PI*{angle:.2f}"

    def _pulse_filter(self, intensity: float) -> str:
        """Build brightness pulse filter."""
        amount = intensity * 0.15
        return f"eq=brightness='{amount:.3f}*sin(t*3)'"

    def _shake_filter(self, intensity: float, duration_ms: int) -> str:
        """Build camera shake filter."""
        # Amplitude in pixels
        amp = int(intensity * 10)
        freq = 15 + int(intensity * 10)

        # Shake using crop with animated offset, then scale back
        return (
            f"crop=iw-{amp*2}:ih-{amp*2}:"
            f"x='{amp}+{amp}*sin(t*{freq})':"
            f"y='{amp}+{amp}*cos(t*{freq*0.7})',"
            f"scale=1080:1920:flags=lanczos"
        )

    def _flash_filter(self, intensity: float, duration_ms: int) -> str:
        """Build flash filter."""
        duration_sec = duration_ms / 1000
        max_brightness = intensity * 0.5

        return (
            f"eq=brightness='if(lt(t,{duration_sec}),"
            f"{max_brightness}*sin(PI*t/{duration_sec}),0)'"
        )

    # =========================================================================
    # Image Dimension Detection
    # =========================================================================

    async def _get_image_dimensions(
        self,
        image_path: Path
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Get image dimensions using ffprobe.

        Args:
            image_path: Path to image file

        Returns:
            Tuple of (width, height) or (None, None) if detection fails
        """
        if not self._ffprobe_path:
            logger.warning("ffprobe not available, cannot detect image dimensions")
            return None, None

        cmd = [
            self._ffprobe_path,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(image_path)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                output = stdout.decode().strip()
                if "x" in output:
                    width, height = output.split("x")
                    return int(width), int(height)

        except Exception as e:
            logger.warning(f"Failed to detect image dimensions: {e}")

        return None, None

    # =========================================================================
    # FFmpeg Execution
    # =========================================================================

    async def _run_ffmpeg(
        self,
        cmd: List[str],
        timeout: int = 300
    ) -> None:
        """Run FFmpeg command asynchronously."""
        logger.debug(f"Running FFmpeg: {' '.join(cmd[:5])}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"FFmpeg failed: {error_msg}")
                raise RuntimeError(f"FFmpeg failed: {error_msg[:500]}")

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(f"FFmpeg timeout after {timeout}s")

    # =========================================================================
    # Storage Operations
    # =========================================================================

    async def upload_video(
        self,
        project_id: str,
        local_path: Path,
        filename: str
    ) -> str:
        """
        Upload rendered video to Supabase Storage.

        Returns:
            Storage URL
        """
        storage_path = f"{project_id}/videos/{filename}"

        video_data = local_path.read_bytes()

        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                storage_path,
                video_data,
                {"content-type": "video/mp4"}
            )
        )

        logger.info(f"Uploaded video: {storage_path}")
        return f"{self.STORAGE_BUCKET}/{storage_path}"

    async def get_video_url(
        self,
        storage_path: str,
        expires_in: int = 3600
    ) -> str:
        """Get signed URL for video playback."""
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
    # Render Job Management
    # =========================================================================

    async def create_render_job(
        self,
        project_id: str,
        job_type: str,
        panel_number: Optional[int] = None,
        total_panels: Optional[int] = None
    ) -> str:
        """Create a render job record."""
        job_id = str(uuid.uuid4())

        await asyncio.to_thread(
            lambda: self.supabase.table("comic_render_jobs").insert({
                "id": job_id,
                "project_id": project_id,
                "job_type": job_type,
                "panel_number": panel_number,
                "total_panels": total_panels,
                "status": "queued"
            }).execute()
        )

        return job_id

    async def update_render_job(
        self,
        job_id: str,
        status: str,
        current_panel: Optional[int] = None,
        output_url: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Update render job status."""
        update_data = {"status": status}

        if current_panel is not None:
            update_data["current_panel"] = current_panel

        if output_url:
            update_data["output_url"] = output_url

        if error_message:
            update_data["error_message"] = error_message

        if status == "processing":
            update_data["started_at"] = datetime.utcnow().isoformat()
        elif status in ("complete", "failed"):
            update_data["completed_at"] = datetime.utcnow().isoformat()

        await asyncio.to_thread(
            lambda: self.supabase.table("comic_render_jobs")
                .update(update_data)
                .eq("id", job_id)
                .execute()
        )
