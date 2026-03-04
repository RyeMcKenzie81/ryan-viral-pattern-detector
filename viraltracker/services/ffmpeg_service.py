"""
FFmpeg Service

Audio and video processing service using FFmpeg for:
- Getting audio duration
- Adding silence/pauses
- Concatenating audio files
- Video normalization for Kling element creation
- Future: pitch adjustment

All sync subprocess calls should be wrapped with asyncio.to_thread()
when called from async code.

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

    def extract_audio(self, video_bytes: bytes) -> bytes:
        """
        Extract the audio track from a video file as MP3.

        Uses MP3 format for broad browser compatibility with st.audio().
        The MP3 output is also accepted by replace_audio() for re-muxing.

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.extract_audio, video_bytes)

        Args:
            video_bytes: Raw video file bytes.

        Returns:
            Audio bytes (MP3 format).

        Raises:
            ValueError: If FFmpeg not available or video has no audio track.
        """
        if not self.available:
            raise ValueError("FFmpeg/FFprobe not available. Cannot extract audio.")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            output_path = Path(tmpdir) / "output.mp3"

            input_path.write_bytes(video_bytes)

            # Check for audio stream first
            try:
                probe_result = subprocess.run(
                    [
                        self._ffprobe_path,
                        "-v", "quiet",
                        "-select_streams", "a",
                        "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0",
                        str(input_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if not probe_result.stdout.strip():
                    raise ValueError("Video has no audio track.")
            except subprocess.TimeoutExpired:
                raise ValueError("Timed out probing video for audio.")

            # Extract audio as MP3
            try:
                subprocess.run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-i", str(input_path),
                        "-vn",
                        "-acodec", "libmp3lame",
                        "-q:a", "2",
                        str(output_path),
                    ],
                    capture_output=True,
                    timeout=60,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                raise ValueError(f"Failed to extract audio: {stderr}")

            audio_bytes = output_path.read_bytes()
            logger.info(f"Extracted audio: {len(audio_bytes)} bytes")
            return audio_bytes

    def replace_audio(self, video_bytes: bytes, audio_bytes: bytes) -> bytes:
        """
        Replace a video's audio track with new audio.

        Strips the original audio, muxes the new audio onto the video
        with proper specs for Kling voice extraction:
        - AAC codec, 128kbps, 48kHz, mono
        - Audio padded with silence if shorter than video (-af apad)
        - Output trimmed to video length (-shortest)
        - Video stream copied without re-encoding (-c:v copy)
        - moov atom at start for streaming (-movflags +faststart)

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.replace_audio, ...)

        Args:
            video_bytes: Raw video file bytes.
            audio_bytes: Raw audio file bytes (any format FFmpeg can decode).

        Returns:
            Combined video bytes (MP4).

        Raises:
            ValueError: If FFmpeg not available.
            RuntimeError: If FFmpeg muxing fails.
        """
        if not self._ffmpeg_path:
            raise ValueError("FFmpeg not available. Cannot replace audio.")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "audio.m4a"
            output_path = Path(tmpdir) / "output.mp4"

            video_path.write_bytes(video_bytes)
            audio_path.write_bytes(audio_bytes)

            try:
                subprocess.run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-i", str(video_path),
                        "-i", str(audio_path),
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-ar", "48000",
                        "-ac", "1",
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                        "-af", "apad",
                        "-shortest",
                        "-movflags", "+faststart",
                        str(output_path),
                    ],
                    capture_output=True,
                    timeout=120,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                raise RuntimeError(f"FFmpeg audio replacement failed: {stderr}")

            combined_bytes = output_path.read_bytes()
            logger.info(
                f"Replaced audio: video={len(video_bytes)} + audio={len(audio_bytes)} "
                f"-> combined={len(combined_bytes)} bytes"
            )
            return combined_bytes

    def normalize_video_for_kling(self, video_bytes: bytes) -> bytes:
        """
        Normalize a video to meet Kling element creation specs.

        Kling's video element API silently fails voice extraction if the video
        doesn't meet exact specs. This re-encodes to guaranteed-safe output:
        - Exact 1080x1920 (portrait) or 1920x1080 (landscape) via scale+crop
        - H.264 Main profile level 4.1, yuv420p, 30fps
        - AAC-LC audio at 128kbps, 48kHz mono
        - SAR 1:1, movflags +faststart
        - Capped at 8 seconds

        NOTE: This is a sync method. When calling from async code,
        wrap with: await asyncio.to_thread(ffmpeg.normalize_video_for_kling, video_bytes)

        Args:
            video_bytes: Raw video file bytes.

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

            import json
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

            logger.info(
                f"Normalizing video: {width}x{height} -> {target_w}x{target_h}, "
                f"duration={duration:.1f}s (cap 8s)"
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
                result = subprocess.run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-i", str(input_path),
                        "-t", "8",
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
                    ],
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
