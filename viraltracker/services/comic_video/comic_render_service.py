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
    PanelOverrides,
    EffectInstance,
    AspectRatio,
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
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
        output_width: Optional[int] = None,
        output_height: Optional[int] = None
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
            aspect_ratio: Output aspect ratio (determines dimensions)
            output_width: Override output width (uses aspect_ratio if None)
            output_height: Override output height (uses aspect_ratio if None)

        Returns:
            Path to rendered preview video
        """
        if not self.available:
            raise RuntimeError("FFmpeg not available")

        # Get output dimensions from aspect ratio or overrides
        if output_width is None or output_height is None:
            output_width, output_height = aspect_ratio.dimensions

        # Create output directory
        project_dir = self.output_base / project_id / "previews"
        project_dir.mkdir(parents=True, exist_ok=True)

        output_path = project_dir / f"panel_{panel_number:02d}_preview.mp4"

        logger.info(f"Rendering preview for panel {panel_number} at {output_width}x{output_height}")

        # Detect actual image dimensions and update layout
        actual_width, actual_height = await self._get_image_dimensions(comic_grid_path)
        if actual_width and actual_height:
            # Update layout with actual dimensions for accurate panel positioning
            layout = ComicLayout(
                grid_cols=layout.grid_cols,
                grid_rows=layout.grid_rows,
                total_panels=layout.total_panels,
                panel_cells=layout.panel_cells,
                row_cols=layout.row_cols,  # Important: preserve row column counts
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

    async def render_all_panels(
        self,
        project_id: str,
        comic_grid_path: Path,
        instructions: List[PanelInstruction],
        layout: ComicLayout,
        audio_paths: Dict[int, Path],
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
        force_rerender: bool = False,
        progress_callback: Optional[callable] = None
    ) -> Dict[int, str]:
        """
        Render preview videos for all panels.

        Args:
            project_id: Project UUID
            comic_grid_path: Path to comic grid image
            instructions: All panel instructions
            layout: Comic layout
            audio_paths: Map of panel_number -> audio file path
            aspect_ratio: Output aspect ratio
            force_rerender: Re-render even if preview exists
            progress_callback: Optional callback(panel_number, total) for progress

        Returns:
            Dict of panel_number -> preview path
        """
        if not self.available:
            raise RuntimeError("FFmpeg not available")

        output_width, output_height = aspect_ratio.dimensions
        results = {}
        total = len(instructions)

        logger.info(f"Rendering all {total} panels at {output_width}x{output_height}")

        for i, instruction in enumerate(instructions):
            panel_num = instruction.panel_number
            audio_path = audio_paths.get(panel_num)

            # Check if preview already exists (unless force_rerender)
            if not force_rerender and instruction.preview_url:
                results[panel_num] = instruction.preview_url
                if progress_callback:
                    progress_callback(panel_num, total)
                continue

            try:
                preview_path = await self.render_panel_preview(
                    project_id=project_id,
                    panel_number=panel_num,
                    comic_grid_path=comic_grid_path,
                    instruction=instruction,
                    layout=layout,
                    audio_path=Path(audio_path) if audio_path else None,
                    aspect_ratio=aspect_ratio
                )
                results[panel_num] = preview_path

                if progress_callback:
                    progress_callback(panel_num, total)

            except Exception as e:
                logger.error(f"Failed to render panel {panel_num}: {e}")
                results[panel_num] = None

        logger.info(f"Rendered {len([r for r in results.values() if r])} of {total} panels")
        return results

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
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
        output_width: Optional[int] = None,
        output_height: Optional[int] = None,
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
            aspect_ratio: Output aspect ratio (determines dimensions)
            output_width: Override output width (uses aspect_ratio if None)
            output_height: Override output height (uses aspect_ratio if None)
            background_music_path: Optional background music

        Returns:
            Path to final rendered video
        """
        if not self.available:
            raise RuntimeError("FFmpeg not available")

        # Get output dimensions from aspect ratio or overrides
        if output_width is None or output_height is None:
            output_width, output_height = aspect_ratio.dimensions

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
                row_cols=layout.row_cols,  # Important: preserve row column counts
                canvas_width=actual_width,
                canvas_height=actual_height
            )
            logger.info(f"Using actual image dimensions: {actual_width}x{actual_height}")

        # Strategy: Render each panel as a segment, then concatenate
        # This is more reliable than a single complex filter graph

        logger.info(f"Rendering full video with {len(instructions)} panels")

        # Clean up any existing segment files to ensure fresh render
        for old_segment in project_dir.glob("segment_*.mp4"):
            old_segment.unlink()
            logger.debug(f"Deleted old segment: {old_segment}")

        # Debug: write camera positions to file for debugging
        debug_file = project_dir / "camera_debug.txt"
        self._debug_file = debug_file  # Store for use in segment rendering
        with open(debug_file, "w") as f:
            f.write(f"=== RENDER DEBUG LOG ===\n")
            f.write(f"Canvas: {layout.canvas_width}x{layout.canvas_height}\n")
            f.write(f"Layout: {layout.grid_cols}x{layout.grid_rows}, row_cols={layout.row_cols}\n")
            f.write(f"Panel cells: {layout.panel_cells}\n\n")
            f.write(f"=== INSTRUCTION ORDER (as received) ===\n")
            for i, instr in enumerate(instructions):
                f.write(f"  [{i}] Panel {instr.panel_number}: camera=({instr.camera.center_x:.4f}, {instr.camera.center_y:.4f})\n")
            f.write(f"\n")
        logger.info(f"Debug info written to {debug_file}")

        # 1. Render each panel segment (with transition to next panel)
        segment_paths = []

        # Debug: log iteration order
        with open(debug_file, "a") as f:
            f.write(f"=== RENDER LOOP ===\n")

        for i, instruction in enumerate(instructions):
            panel_num = instruction.panel_number
            audio_path = audio_paths.get(panel_num)

            # Get next instruction for transition target (if not last panel)
            next_instruction = instructions[i + 1] if i < len(instructions) - 1 else None

            # Debug: log loop iteration
            with open(debug_file, "a") as f:
                f.write(f"Loop [{i}]: rendering panel {panel_num}")
                if next_instruction:
                    f.write(f" (transition to panel {next_instruction.panel_number})")
                f.write(f"\n")

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

            # Debug: verify segment was created and extract first frame for visual verification
            if segment_path.exists():
                size_kb = segment_path.stat().st_size / 1024
                with open(self._debug_file, "a") as f:
                    f.write(f"  -> Segment created: {segment_path.name} ({size_kb:.1f} KB)\n")

                # Extract first frame as JPEG for visual verification
                frame_path = project_dir / f"frame_{panel_num:02d}.jpg"
                try:
                    frame_cmd = [
                        self._ffmpeg_path, "-y",
                        "-i", str(segment_path),
                        "-vframes", "1",
                        "-q:v", "2",
                        str(frame_path)
                    ]
                    await self._run_ffmpeg(frame_cmd)
                    if frame_path.exists():
                        frame_kb = frame_path.stat().st_size / 1024
                        with open(self._debug_file, "a") as f:
                            f.write(f"  -> First frame: {frame_path.name} ({frame_kb:.1f} KB)\n\n")
                except Exception as e:
                    with open(self._debug_file, "a") as f:
                        f.write(f"  -> Frame extraction failed: {e}\n\n")
            else:
                with open(self._debug_file, "a") as f:
                    f.write(f"  -> ERROR: Segment NOT created: {segment_path}\n\n")

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

        # Get audio delay from user overrides or use default
        # Default 0ms = audio starts exactly when segment starts (camera at panel)
        # Add delay if you want a pause after camera arrives before voice starts
        audio_delay_ms = 0
        if instruction.user_overrides and instruction.user_overrides.audio_delay_ms is not None:
            audio_delay_ms = instruction.user_overrides.audio_delay_ms

        # Get actual audio duration to sync video precisely
        # Use EXACT audio duration - no buffer to prevent drift accumulation
        if audio_path and audio_path.exists():
            actual_audio_ms = await self._get_audio_duration_ms(audio_path)
            if actual_audio_ms:
                # Content duration = exact audio length (no buffer to prevent cumulative drift)
                content_duration_ms = actual_audio_ms
                logger.info(
                    f"Panel {instruction.panel_number}: audio={actual_audio_ms}ms (exact)"
                )
            else:
                content_duration_ms = instruction.duration_ms
                logger.info(f"Panel {instruction.panel_number}: using stored duration {content_duration_ms}ms")
        else:
            # Panel has no audio - use stored duration with minimum fallback
            # IMPORTANT: Ensure silent segments have enough duration so they don't cause sync issues
            content_duration_ms = instruction.duration_ms
            MIN_NO_AUDIO_DURATION_MS = 2000  # Minimum 2 seconds for panels without voice
            if content_duration_ms < MIN_NO_AUDIO_DURATION_MS:
                logger.warning(
                    f"Panel {instruction.panel_number}: no audio, stored duration {content_duration_ms}ms too short, "
                    f"using minimum {MIN_NO_AUDIO_DURATION_MS}ms"
                )
                content_duration_ms = MIN_NO_AUDIO_DURATION_MS

        transition_duration_ms = instruction.transition.duration_ms if next_instruction else 0

        # No transition for last panel or CUT transitions
        if not next_instruction or instruction.transition.transition_type.value == "cut":
            transition_duration_ms = 0

        total_duration_ms = content_duration_ms + transition_duration_ms
        total_duration_sec = total_duration_ms / 1000
        total_frames = int(total_duration_sec * fps)

        content_frames = int((content_duration_ms / 1000) * fps)
        transition_frames = total_frames - content_frames

        # Debug: log segment details
        if hasattr(self, '_debug_file') and self._debug_file:
            with open(self._debug_file, "a") as f:
                f.write(f"=== SEGMENT: Panel {instruction.panel_number} ===\n")
                f.write(f"  Camera: ({instruction.camera.center_x:.4f}, {instruction.camera.center_y:.4f})\n")
                f.write(f"  Pixel pos: ({instruction.camera.center_x * layout.canvas_width:.1f}, {instruction.camera.center_y * layout.canvas_height:.1f})\n")
                if next_instruction:
                    f.write(f"  Next panel {next_instruction.panel_number}: ({next_instruction.camera.center_x:.4f}, {next_instruction.camera.center_y:.4f})\n")
                f.write(f"  Content frames: {content_frames}, Transition frames: {transition_frames}\n")

        # Build zoompan filter with transition
        zoompan_filter = self._build_zoompan_with_transition(
            camera=instruction.camera,
            next_camera=next_instruction.camera if next_instruction else None,
            transition=instruction.transition,
            layout=layout,
            content_frames=content_frames,
            transition_frames=transition_frames,
            output_size=(output_width, output_height),
            fps=fps,
            panel_number=instruction.panel_number  # Pass for debugging
        )

        # Build effects filter (only for content portion)
        effects_filter = self._build_effects_filter(
            effects=instruction.effects,
            duration_ms=content_duration_ms
        )

        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(grid_path),
        ]

        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])

        # Build filter complex with video and optional audio delay
        # IMPORTANT: Always add a final scale to ensure consistent output dimensions
        # The shake effect uses DEFAULT_OUTPUT dimensions (1080x1920), so we must match that
        # for ALL segments to ensure they can be concatenated properly
        has_shake_scale = effects_filter and "scale=" in effects_filter
        # Use class defaults to match shake filter output (1080x1920 for vertical video)
        target_width = self.DEFAULT_OUTPUT_WIDTH
        target_height = self.DEFAULT_OUTPUT_HEIGHT
        final_scale = "" if has_shake_scale else f",scale={target_width}:{target_height}:flags=lanczos"

        if audio_path and audio_path.exists():
            if effects_filter:
                video_chain = f"[0:v]{zoompan_filter},{effects_filter}{final_scale}[vout]"
            else:
                video_chain = f"[0:v]{zoompan_filter}{final_scale}[vout]"

            # Only add audio delay filter if delay > 0
            if audio_delay_ms > 0:
                audio_chain = f"[1:a]adelay={audio_delay_ms}|{audio_delay_ms}[aout]"
                filter_complex = f"{video_chain};{audio_chain}"
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[vout]",
                    "-map", "[aout]",
                ])
            else:
                # No audio delay - simpler filter graph
                filter_complex = video_chain
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[vout]",
                    "-map", "1:a",
                ])
        else:
            # No voice audio - generate silent audio track
            # IMPORTANT: All segments must have audio for proper concatenation
            if effects_filter:
                video_chain = f"[0:v]{zoompan_filter},{effects_filter}{final_scale}[vout]"
            else:
                video_chain = f"[0:v]{zoompan_filter}{final_scale}[vout]"

            # Generate silent audio using anullsrc
            # Must match the segment duration exactly
            silent_audio = f"anullsrc=r=44100:cl=stereo,atrim=0:{total_duration_sec}[aout]"
            filter_complex = f"{video_chain};{silent_audio}"
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "[aout]",
            ])

        cmd.extend([
            "-t", str(total_duration_sec),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
        ])

        cmd.append(str(output_path))

        has_audio = audio_path and audio_path.exists()
        logger.info(
            f"Rendering panel {instruction.panel_number}: "
            f"has_audio={has_audio}, audio_delay={audio_delay_ms}ms, "
            f"video={content_duration_ms}ms content + {transition_duration_ms}ms transition = {total_duration_ms}ms total, "
            f"camera=({instruction.camera.center_x:.3f}, {instruction.camera.center_y:.3f})"
            + (f" -> next=({next_instruction.camera.center_x:.3f}, {next_instruction.camera.center_y:.3f})"
               if next_instruction else "")
        )

        # Debug: log the full ffmpeg command (filter_complex especially)
        if hasattr(self, '_debug_file') and self._debug_file:
            with open(self._debug_file, "a") as f:
                # Find filter_complex in command
                try:
                    fc_idx = cmd.index("-filter_complex")
                    filter_complex = cmd[fc_idx + 1]
                    f.write(f"  FFmpeg filter_complex:\n")
                    # Split by semicolon for readability
                    parts = filter_complex.split(";")
                    for part in parts:
                        f.write(f"    {part}\n")
                except (ValueError, IndexError):
                    f.write(f"  (no filter_complex found)\n")

        await self._run_ffmpeg(cmd)

    async def _concatenate_segments(
        self,
        segment_paths: List[Path],
        output_path: Path
    ) -> None:
        """
        Concatenate video segments using FFmpeg concat FILTER.

        IMPORTANT: We use the concat filter (not concat demuxer) because:
        - The demuxer with -c copy has known audio sync issues
        - Segments with different audio sources (voice vs anullsrc silence)
          can have timestamp mismatches causing audio drift
        - The concat filter re-encodes everything, ensuring perfect sync

        See: https://trac.ffmpeg.org/wiki/Concatenate
        """
        # Debug: log concatenation details
        if hasattr(self, '_debug_file') and self._debug_file:
            with open(self._debug_file, "a") as f:
                f.write(f"\n=== CONCATENATION (using concat filter) ===\n")
                f.write(f"Total segments to concatenate: {len(segment_paths)}\n")
                for i, path in enumerate(segment_paths):
                    exists = path.exists()
                    size_kb = path.stat().st_size / 1024 if exists else 0
                    f.write(f"  [{i}] {path.name}: exists={exists}, size={size_kb:.1f}KB\n")
                f.write(f"\n")

        # Build FFmpeg command using concat filter
        # This approach re-encodes but guarantees proper audio sync
        cmd = [self._ffmpeg_path, "-y"]

        # Add all input files
        for path in segment_paths:
            cmd.extend(["-i", str(path)])

        # Build the filter_complex for concat filter
        # Format: [0:v][0:a][1:v][1:a][2:v][2:a]...concat=n=N:v=1:a=1[outv][outa]
        n = len(segment_paths)
        filter_inputs = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        filter_complex = f"{filter_inputs}concat=n={n}:v=1:a=1[outv][outa]"

        # Debug: log the filter
        if hasattr(self, '_debug_file') and self._debug_file:
            with open(self._debug_file, "a") as f:
                f.write(f"Concat filter: {filter_complex}\n\n")

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ])

        await self._run_ffmpeg(cmd)

        # Debug: log concat result
        if hasattr(self, '_debug_file') and self._debug_file:
            if output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                with open(self._debug_file, "a") as f:
                    f.write(f"Concatenation complete: {output_path.name} ({size_mb:.2f}MB)\n\n")

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
        panel_width = canvas_w / layout.grid_cols
        panel_height = canvas_h / layout.grid_rows

        # Calculate panel and output aspect ratios
        panel_aspect = panel_width / panel_height
        output_aspect = out_w / out_h

        # Determine zoom based on which dimension is the limiting factor
        # We want the panel to fit entirely within the output frame
        if output_aspect > panel_aspect:
            # Output is wider than panel - height is the constraint
            # Panel height should fit output height, leaving horizontal margins
            base_zoom = canvas_h / panel_height  # = grid_rows
        else:
            # Output is taller/narrower than panel - width is the constraint
            # Panel width should fit output width, leaving vertical margins
            base_zoom = canvas_w / panel_width  # = grid_cols

        # Multiply by factor < 1 to zoom OUT and show entire panel with margin
        # 0.75 means the panel takes up ~75% of frame, showing some neighbors
        panel_zoom = base_zoom * 0.75

        # Apply camera zoom modifiers (1.0 = panel at 75% of frame, 1.2 = tighter)
        # Note: start_zoom/end_zoom default to ~0.95-1.0, so effective zoom is reasonable
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

        logger.debug(
            f"Zoompan: panel at ({camera.center_x:.2f}, {camera.center_y:.2f}), "
            f"zoom {z_start:.1f} -> {z_end:.1f}, output {out_w}x{out_h}"
        )

        return (
            f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
            f":d={duration_frames}:s={out_w}x{out_h}:fps={fps}"
        )

    def _build_zoompan_with_transition(
        self,
        camera: PanelCamera,
        next_camera: Optional[PanelCamera],
        transition: PanelTransition,
        layout: ComicLayout,
        content_frames: int,
        transition_frames: int,
        output_size: Tuple[int, int],
        fps: int,
        panel_number: int = 0
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
            panel_number: Panel number for debugging
        """
        out_w, out_h = output_size
        canvas_w, canvas_h = layout.canvas_width, layout.canvas_height
        total_frames = content_frames + transition_frames

        # Calculate panel zoom (same logic as _build_zoompan_filter)
        panel_width = canvas_w / layout.grid_cols
        panel_height = canvas_h / layout.grid_rows

        # Calculate panel and output aspect ratios
        panel_aspect = panel_width / panel_height
        output_aspect = out_w / out_h

        # Determine zoom based on which dimension is the limiting factor
        # We want the panel to fit entirely within the output frame
        if output_aspect > panel_aspect:
            # Output is wider than panel - height is the constraint
            base_zoom = canvas_h / panel_height  # = grid_rows
        else:
            # Output is taller/narrower than panel - width is the constraint
            base_zoom = canvas_w / panel_width  # = grid_cols

        # Multiply by factor < 1 to zoom OUT and show entire panel with margin
        panel_zoom = base_zoom * 0.75

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

            # Debug: write zoompan details to file
            if hasattr(self, '_debug_file') and self._debug_file:
                with open(self._debug_file, "a") as f:
                    f.write(f"  Zoompan (no transition) for panel {panel_number}:\n")
                    f.write(f"    curr_cx={curr_cx:.1f}, curr_cy={curr_cy:.1f}\n")
                    f.write(f"    x_expr: {x_expr}\n\n")

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

        # Debug: write zoompan details to file
        if hasattr(self, '_debug_file') and self._debug_file:
            with open(self._debug_file, "a") as f:
                f.write(f"  Zoompan build for panel {panel_number}:\n")
                f.write(f"    curr_cx={curr_cx:.1f}, curr_cy={curr_cy:.1f}\n")
                f.write(f"    next_cx={next_cx:.1f}, next_cy={next_cy:.1f}\n")
                f.write(f"    x_expr: {x_expr}\n")
                f.write(f"    y_expr: {y_expr}\n\n")

        logger.debug(
            f"Zoompan with transition: ({curr_cx:.0f},{curr_cy:.0f}) -> ({next_cx:.0f},{next_cy:.0f}), "
            f"{content_frames} content + {transition_frames} transition frames"
        )

        return (
            f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
            f":d={total_frames}:s={out_w}x{out_h}:fps={fps}"
        )

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
            softness = effect.params.get("softness")
            logger.info(f"Building vignette filter: intensity={intensity}, softness={softness}, params={effect.params}")
            filter_str = self._vignette_filter(intensity, softness=softness)

        elif effect_type == EffectType.VIGNETTE_LIGHT:
            softness = effect.params.get("softness")
            filter_str = self._vignette_filter(intensity * 0.5, softness=softness)

        elif effect_type == EffectType.VIGNETTE_HEAVY:
            softness = effect.params.get("softness")
            filter_str = self._vignette_filter(intensity, softness=softness or 0.7)

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

    def _vignette_filter(
        self,
        intensity: float,
        softness: Optional[float] = None,
        fade_in_ms: int = 500
    ) -> str:
        """Build vignette filter with fade-in.

        Args:
            intensity: Darkness of vignette edges (0.0-1.0). Higher = darker.
            softness: How far the vignette extends from edges (0.0-1.0).
                     Higher = extends further toward center. None = use default.
            fade_in_ms: Duration of fade-in effect in milliseconds.

        FFmpeg vignette parameters:
        - angle: Controls the vignette spread. PI/4 = subtle, PI/2 = strong
        - The vignette filter darkens edges naturally based on angle

        The fade-in is achieved by using an expression-based alpha blend that
        gradually increases the vignette strength from 0 to target over fade_in_ms.
        """
        # Softness controls the spread/distance from edges
        # Default to 0.4 if not specified
        soft = softness if softness is not None else 0.4
        # Map softness 0.1-1.0 to angle range PI*0.2 (tight) to PI*0.7 (very spread)
        # This gives a much more noticeable range of effect
        base_angle = 0.2 + (soft * 0.5)

        # For fade-in, we animate the angle from a very small value (no vignette)
        # to the target angle over the fade duration
        fade_in_sec = fade_in_ms / 1000
        # Start at PI*0.1 (nearly invisible) and ramp to target angle
        start_angle = 0.1
        angle_expr = f"PI*({start_angle}+({base_angle}-{start_angle})*min(t/{fade_in_sec},1))"

        # Build the vignette filter with animated angle
        vignette = f"vignette=angle='{angle_expr}'"

        # Intensity controls additional brightness reduction for darker edges
        # Now affects the full range: intensity 0.1 = slight, 1.0 = very dark
        # Map intensity to brightness reduction: 0.1->0.02, 0.5->0.10, 1.0->0.25
        brightness_reduction = intensity * 0.25
        if brightness_reduction > 0.02:
            return f"{vignette},eq=brightness=-{brightness_reduction:.2f}"
        else:
            return vignette

    def _pulse_filter(self, intensity: float) -> str:
        """Build brightness pulse filter."""
        amount = intensity * 0.15
        return f"eq=brightness='{amount:.3f}*sin(t*3)'"

    def _shake_filter(
        self,
        intensity: float,
        duration_ms: int,
        output_width: int = DEFAULT_OUTPUT_WIDTH,
        output_height: int = DEFAULT_OUTPUT_HEIGHT
    ) -> str:
        """Build camera shake filter."""
        # Amplitude in pixels
        amp = int(intensity * 10)
        freq = 15 + int(intensity * 10)

        # Shake using crop with animated offset, then scale back
        return (
            f"crop=iw-{amp*2}:ih-{amp*2}:"
            f"x='{amp}+{amp}*sin(t*{freq})':"
            f"y='{amp}+{amp}*cos(t*{freq*0.7})',"
            f"scale={output_width}:{output_height}:flags=lanczos"
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

    async def _get_audio_duration_ms(
        self,
        audio_path: Path
    ) -> Optional[int]:
        """
        Get audio duration in milliseconds using ffprobe.

        Args:
            audio_path: Path to audio file

        Returns:
            Duration in milliseconds or None if detection fails
        """
        if not self._ffprobe_path:
            logger.warning("ffprobe not available, cannot detect audio duration")
            return None

        cmd = [
            self._ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(audio_path)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()

            if process.returncode == 0:
                duration_sec = float(stdout.decode().strip())
                return int(duration_sec * 1000)

        except Exception as e:
            logger.warning(f"Failed to detect audio duration: {e}")

        return None

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

        Overwrites existing file if it exists.

        Returns:
            Storage URL
        """
        storage_path = f"{project_id}/videos/{filename}"

        video_data = local_path.read_bytes()

        # Try to upload, if file exists delete and re-upload
        try:
            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                    storage_path,
                    video_data,
                    {"content-type": "video/mp4"}
                )
            )
        except Exception as e:
            if "Duplicate" in str(e) or "already exists" in str(e).lower():
                # Delete existing and re-upload
                logger.info(f"File exists, replacing: {storage_path}")
                await asyncio.to_thread(
                    lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).remove([storage_path])
                )
                await asyncio.to_thread(
                    lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                        storage_path,
                        video_data,
                        {"content-type": "video/mp4"}
                    )
                )
            else:
                raise

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
