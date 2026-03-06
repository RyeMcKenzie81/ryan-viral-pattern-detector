"""
FFmpeg Service

Audio and video processing service using FFmpeg for:
- Getting audio duration
- Adding silence/pauses
- Concatenating audio files
- Video normalization for Kling element creation
- Video clipping, probing, and concatenation
- Lip-sync validation
- Future: pitch adjustment

All sync subprocess calls should be wrapped with asyncio.to_thread()
when called from async code.

Follows existing service patterns in the codebase.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil

logger = logging.getLogger(__name__)


class FFmpegService:
    """Service for audio processing via FFmpeg"""

    def __init__(self):
        """Initialize FFmpeg service and locate executables."""
        self._ffmpeg_path = self._find_ffmpeg()
        self._ffprobe_path = self._find_ffprobe()
        logger.info(f"FFmpegService initialized (ffmpeg: {self._ffmpeg_path})")

    def _find_ffmpeg(self) -> Optional[str]:
        """Find ffmpeg executable"""
        path = shutil.which("ffmpeg")
        if not path:
            logger.warning("FFmpeg not found. Audio processing will be unavailable.")
        return path

    def _find_ffprobe(self) -> Optional[str]:
        """Find ffprobe executable"""
        path = shutil.which("ffprobe")
        if not path:
            logger.warning("FFprobe not found. Duration detection will be unavailable.")
        return path

    @property
    def available(self) -> bool:
        """Check if FFmpeg is available"""
        return bool(self._ffmpeg_path and self._ffprobe_path)

    def get_duration_ms(self, audio_path: Path) -> int:
        """
        Get audio duration in milliseconds.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.get_duration_ms, path)

        Args:
            audio_path: Path to audio file

        Returns:
            Duration in milliseconds, or 0 if detection fails
        """
        if not self._ffprobe_path:
            logger.warning("FFprobe not available, cannot get duration")
            return 0

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
            duration_ms = int(duration_sec * 1000)
            logger.debug(f"Duration of {audio_path.name}: {duration_ms}ms")
            return duration_ms

        except (ValueError, subprocess.TimeoutExpired) as e:
            logger.error(f"Failed to get duration for {audio_path}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error getting duration: {e}")
            return 0

    def add_silence_after(
        self,
        input_path: Path,
        output_path: Path,
        silence_ms: int
    ) -> bool:
        """
        Add silence to the end of an audio file.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.add_silence_after, ...)

        Args:
            input_path: Source audio file
            output_path: Destination audio file
            silence_ms: Silence duration in milliseconds

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot add silence")
            return False

        if silence_ms <= 0:
            # No silence needed, just copy
            shutil.copy(input_path, output_path)
            return True

        try:
            silence_sec = silence_ms / 1000.0

            result = subprocess.run(
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
            logger.error(f"Failed to add silence: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout adding silence to {input_path}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error adding silence: {e}")
            return False

    def concatenate_with_pauses(
        self,
        audio_segments: List[dict],
        output_path: Path
    ) -> bool:
        """
        Concatenate multiple audio segments with pauses between them.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.concatenate_with_pauses, ...)

        Args:
            audio_segments: List of {"path": Path, "pause_after_ms": int}
            output_path: Destination file

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot concatenate")
            return False

        if not audio_segments:
            logger.warning("No audio segments to concatenate")
            return False

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                processed_files = []

                for i, segment in enumerate(audio_segments):
                    src_path = Path(segment["path"])
                    pause_ms = segment.get("pause_after_ms", 0)

                    if not src_path.exists():
                        logger.warning(f"Segment file not found: {src_path}")
                        continue

                    if pause_ms > 0:
                        # Add silence to this segment
                        processed_path = tmpdir / f"segment_{i:03d}.mp3"
                        if self.add_silence_after(src_path, processed_path, pause_ms):
                            processed_files.append(processed_path)
                        else:
                            # Fall back to original if silence fails
                            processed_files.append(src_path)
                    else:
                        processed_files.append(src_path)

                if not processed_files:
                    logger.error("No valid segments to concatenate")
                    return False

                # Create concat file list
                concat_list = tmpdir / "concat.txt"
                with open(concat_list, "w") as f:
                    for pf in processed_files:
                        # Escape single quotes in paths
                        escaped_path = str(pf).replace("'", "'\\''")
                        f.write(f"file '{escaped_path}'\n")

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

                logger.info(f"Concatenated {len(processed_files)} segments to {output_path}")
                return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Concatenation failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout during concatenation")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during concatenation: {e}")
            return False

    def generate_silence(self, output_path: Path, duration_ms: int) -> bool:
        """
        Generate a silent audio file.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.generate_silence, ...)

        Args:
            output_path: Destination file
            duration_ms: Duration in milliseconds

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot generate silence")
            return False

        if duration_ms <= 0:
            logger.warning("Duration must be positive")
            return False

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

            logger.debug(f"Generated {duration_ms}ms silence at {output_path}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate silence: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout generating silence")
            return False
        except Exception as e:
            logger.error(f"Unexpected error generating silence: {e}")
            return False

    def convert_to_mp3(
        self,
        input_path: Path,
        output_path: Path,
        quality: int = 2
    ) -> bool:
        """
        Convert audio file to MP3 format.

        Args:
            input_path: Source audio file
            output_path: Destination MP3 file
            quality: LAME quality (0-9, lower is better, default 2)

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot convert")
            return False

        try:
            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-i", str(input_path),
                    "-acodec", "libmp3lame",
                    "-q:a", str(quality),
                    str(output_path)
                ],
                capture_output=True,
                timeout=60,
                check=True
            )

            logger.debug(f"Converted {input_path} to {output_path}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Conversion failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during conversion: {e}")
            return False

    def extract_audio(self, video_bytes: bytes, format: str = "mp3") -> bytes:
        """
        Extract audio track from a video file.

        Used for previewing voice samples in the UI via st.audio().

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.extract_audio, video_bytes)

        Args:
            video_bytes: Raw video file bytes.
            format: Output audio format ("mp3" or "wav").

        Returns:
            Audio bytes in the requested format.

        Raises:
            ValueError: If FFmpeg not available or video has no audio.
            RuntimeError: If extraction fails.
        """
        if not self._ffmpeg_path:
            raise ValueError("FFmpeg not available. Cannot extract audio.")

        suffix = f".{format}"
        codec = "libmp3lame" if format == "mp3" else "pcm_s16le"

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            output_path = Path(tmpdir) / f"output{suffix}"

            input_path.write_bytes(video_bytes)

            try:
                subprocess.run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-i", str(input_path),
                        "-vn",
                        "-acodec", codec,
                        "-q:a", "2",
                        str(output_path),
                    ],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                if "does not contain any stream" in stderr or "no audio" in stderr.lower():
                    raise ValueError("Video has no audio track.")
                raise RuntimeError(f"Audio extraction failed: {stderr}")

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise ValueError("Video has no audio track.")

            audio_bytes = output_path.read_bytes()
            logger.info(
                f"Extracted audio: {len(video_bytes)} video bytes -> "
                f"{len(audio_bytes)} {format} bytes"
            )
            return audio_bytes

    def normalize_video_for_kling(
        self, video_bytes: bytes, max_duration_seconds: Optional[float] = 8.0
    ) -> bytes:
        """
        Normalize a video to meet Kling element creation specs.

        Kling's video element API silently fails voice extraction if the video
        doesn't meet exact specs. This re-encodes to guaranteed-safe output:
        - Exact 1080x1920 (portrait) or 1920x1080 (landscape) via scale+crop
        - H.264 Main profile level 4.1, yuv420p, 30fps
        - AAC-LC audio at 128kbps, 48kHz mono
        - SAR 1:1, movflags +faststart
        - Capped at max_duration_seconds (default 8s, pass None to skip)

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.normalize_video_for_kling, video_bytes)

        Args:
            video_bytes: Raw video file bytes.
            max_duration_seconds: Max duration cap in seconds. Default 8.0.
                Pass None to skip duration capping (e.g. for lip-sync).

        Returns:
            Normalized video bytes (MP4).

        Raises:
            ValueError: If FFmpeg not available, no audio track, or duration < 3s.
            RuntimeError: If FFmpeg encoding fails.
        """
        if not self.available:
            raise ValueError("FFmpeg/FFprobe not available. Cannot normalize video.")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            output_path = Path(tmpdir) / "output.mp4"

            input_path.write_bytes(video_bytes)

            # Probe video properties
            try:
                probe_result = subprocess.run(
                    [
                        self._ffprobe_path,
                        "-v", "quiet",
                        "-print_format", "json",
                        "-show_format",
                        "-show_streams",
                        str(input_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"FFprobe failed: {e.stderr}")

            probe = json.loads(probe_result.stdout)

            # Check for audio stream
            streams = probe.get("streams", [])
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            if not has_audio:
                raise ValueError(
                    "Video has no audio track. Voice extraction requires speech."
                )

            # Check duration
            duration = float(probe.get("format", {}).get("duration", 0))
            if duration < 3.0:
                raise ValueError(
                    f"Video must be at least 3 seconds (got {duration:.1f}s)."
                )

            # Determine target resolution based on orientation
            video_stream = next(
                (s for s in streams if s.get("codec_type") == "video"), None
            )
            if not video_stream:
                raise ValueError("Video has no video stream.")

            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))

            if height > width:
                # Portrait
                target_w, target_h = 1080, 1920
            else:
                # Landscape
                target_w, target_h = 1920, 1080

            cap_msg = f"cap {max_duration_seconds}s" if max_duration_seconds else "no cap"
            logger.info(
                f"Normalizing video: {width}x{height} -> {target_w}x{target_h}, "
                f"duration={duration:.1f}s ({cap_msg})"
            )

            # Re-encode with FFmpeg
            # Uses scale+crop to avoid any aspect ratio distortion,
            # forces 30fps, H.264 Main level 4.1, AAC 48kHz mono
            # per Kling API requirements for voice extraction.
            vf = (
                f"scale={target_w}:{target_h}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h},"
                f"setsar=1,"
                f"fps=30,"
                f"format=yuv420p"
            )
            try:
                cmd_args = [
                    self._ffmpeg_path,
                    "-y",
                    "-i", str(input_path),
                ]
                if max_duration_seconds is not None:
                    cmd_args.extend(["-t", str(max_duration_seconds)])
                cmd_args.extend([
                    "-vf", vf,
                    "-c:v", "libx264",
                    "-profile:v", "main",
                    "-level", "4.1",
                    "-preset", "medium",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-map", "0:v:0",
                    "-map", "0:a:0",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-ar", "48000",
                    "-ac", "1",
                    "-movflags", "+faststart",
                    str(output_path),
                ])
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    timeout=120,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                raise RuntimeError(f"FFmpeg encoding failed: {stderr}")

            normalized_bytes = output_path.read_bytes()
            logger.info(
                f"Video normalized: {len(video_bytes)} -> {len(normalized_bytes)} bytes"
            )
            return normalized_bytes

    def probe_video_info(self, video_path: Path) -> Dict[str, Any]:
        """
        Probe a video file and return its properties.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.probe_video_info, path)

        Args:
            video_path: Path to the video file.

        Returns:
            Dict with width, height, duration_ms, has_audio, codec_name.

        Raises:
            RuntimeError: If ffprobe fails.
        """
        if not self._ffprobe_path:
            raise RuntimeError("FFprobe not available")

        try:
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFprobe failed: {e.stderr}")

        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])

        video_stream = next(
            (s for s in streams if s.get("codec_type") == "video"), None
        )
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        duration = float(probe.get("format", {}).get("duration", 0))

        info = {
            "width": int(video_stream.get("width", 0)) if video_stream else 0,
            "height": int(video_stream.get("height", 0)) if video_stream else 0,
            "duration_ms": int(duration * 1000),
            "has_audio": has_audio,
            "codec_name": video_stream.get("codec_name", "") if video_stream else "",
        }
        logger.debug(f"Probed {video_path.name}: {info}")
        return info

    def clip_video(
        self,
        video_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Path,
    ) -> bool:
        """
        Extract a frame-accurate video clip via re-encode.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.clip_video, ...)

        Args:
            video_path: Source video file.
            start_ms: Start time in milliseconds.
            end_ms: End time in milliseconds.
            output_path: Destination file.

        Returns:
            True if successful, False otherwise.
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot clip video")
            return False

        start_sec = start_ms / 1000.0
        duration_sec = (end_ms - start_ms) / 1000.0

        try:
            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-i", str(video_path),
                    "-ss", str(start_sec),
                    "-t", str(duration_sec),
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(output_path),
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            logger.debug(f"Clipped video {start_ms}-{end_ms}ms -> {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Video clip failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout during video clipping")
            return False

    def clip_audio(
        self,
        audio_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Path,
    ) -> bool:
        """
        Extract an audio segment.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.clip_audio, ...)

        Args:
            audio_path: Source audio file.
            start_ms: Start time in milliseconds.
            end_ms: End time in milliseconds.
            output_path: Destination file.

        Returns:
            True if successful, False otherwise.
        """
        if not self._ffmpeg_path:
            logger.error("FFmpeg not available, cannot clip audio")
            return False

        start_sec = start_ms / 1000.0
        duration_sec = (end_ms - start_ms) / 1000.0

        try:
            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-i", str(audio_path),
                    "-ss", str(start_sec),
                    "-t", str(duration_sec),
                    "-c:a", "aac",
                    "-b:a", "128k",
                    str(output_path),
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
            logger.debug(f"Clipped audio {start_ms}-{end_ms}ms -> {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Audio clip failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout during audio clipping")
            return False

    def concatenate_video_files(
        self,
        input_paths: List[Path],
        output_path: Path,
    ) -> bool:
        """
        Concatenate multiple video files using FFmpeg concat filter with SAR normalization.

        Adds silent audio to any clip missing an audio track before concatenation.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.concatenate_video_files, ...)

        Args:
            input_paths: List of video file paths in order.
            output_path: Destination file.

        Returns:
            True if successful, False otherwise.
        """
        if not self._ffmpeg_path or not self._ffprobe_path:
            logger.error("FFmpeg/FFprobe not available, cannot concatenate")
            return False

        if len(input_paths) < 2:
            logger.error("Need at least 2 files to concatenate")
            return False

        try:
            # Ensure all clips have audio
            for path in input_paths:
                if not self._file_has_audio(path):
                    self._add_silent_audio_sync(path)

            n = len(input_paths)
            cmd = [self._ffmpeg_path, "-y"]
            for path in input_paths:
                cmd.extend(["-i", str(path)])

            # SAR normalization + concat filter
            sar_filters = []
            concat_inputs = []
            for i in range(n):
                sar_filters.append(f"[{i}:v]setsar=1:1[v{i}]")
                concat_inputs.append(f"[v{i}][{i}:a]")

            filter_complex = (
                ";".join(sar_filters)
                + ";"
                + "".join(concat_inputs)
                + f"concat=n={n}:v=1:a=1[outv][outa]"
            )

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
                str(output_path),
            ])

            subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,
                check=True,
            )

            logger.info(f"Concatenated {n} clips -> {output_path}")
            return True

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode()[-1500:] if e.stderr else "Unknown error"
            logger.error(f"Concatenation failed: {error_msg}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout during concatenation")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during concatenation: {e}")
            return False

    def validate_for_lip_sync(self, video_path: Path) -> Dict[str, Any]:
        """
        Validate a video file for lip-sync processing.

        Checks: duration 2-60s, resolution within Kling bounds, file size <= 100MB.

        NOTE: This is a sync method.

        Args:
            video_path: Path to the video file.

        Returns:
            Dict with valid (bool), errors (list of str), info (dict).
        """
        errors = []

        # File size check
        file_size = video_path.stat().st_size
        if file_size > 100 * 1024 * 1024:
            errors.append(f"File too large: {file_size / (1024*1024):.1f}MB (max 100MB)")

        # Probe info
        try:
            info = self.probe_video_info(video_path)
        except RuntimeError as e:
            return {"valid": False, "errors": [f"Cannot probe video: {e}"], "info": {}}

        # Duration check
        duration_ms = info["duration_ms"]
        if duration_ms < 2000:
            errors.append(f"Video too short: {duration_ms}ms (min 2000ms)")
        if duration_ms > 60000:
            errors.append(f"Video too long: {duration_ms}ms (max 60000ms)")

        # Resolution check
        width, height = info["width"], info["height"]
        if width == 0 or height == 0:
            errors.append("Cannot determine video resolution")
        elif width > 3840 or height > 3840:
            errors.append(f"Resolution too high: {width}x{height} (max 3840)")

        # Audio check
        if not info["has_audio"]:
            errors.append("Video has no audio track")

        return {"valid": len(errors) == 0, "errors": errors, "info": info}

    # =========================================================================
    # Private helpers for concatenation
    # =========================================================================

    def _file_has_audio(self, video_path: Path) -> bool:
        """Check if a video file has an audio stream (sync)."""
        try:
            result = subprocess.run(
                [
                    self._ffprobe_path, "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.debug(f"Audio stream check failed for {video_path}: {e}")
            return False

    def _add_silent_audio_sync(self, video_path: Path) -> None:
        """Add a silent audio track to a video that's missing one (sync)."""
        try:
            info = self.probe_video_info(video_path)
            duration_sec = info["duration_ms"] / 1000.0
        except Exception as e:
            logger.debug(f"Duration probe failed for {video_path}, using default: {e}")
            duration_sec = 5.0

        output_path = video_path.with_suffix(".with_audio.mp4")
        try:
            subprocess.run(
                [
                    self._ffmpeg_path, "-y",
                    "-i", str(video_path),
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(duration_sec),
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-shortest",
                    str(output_path),
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
            if output_path.exists():
                output_path.replace(video_path)
        except Exception as e:
            logger.warning(f"Failed to add silent audio to {video_path}: {e}")
