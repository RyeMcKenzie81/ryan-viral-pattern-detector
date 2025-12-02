"""
FFmpeg Service

Audio processing service using FFmpeg for:
- Getting audio duration
- Adding silence/pauses
- Concatenating audio files
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
