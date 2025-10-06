"""
Video Downloader Utility

Downloads videos from Instagram using yt-dlp and uploads to Supabase Storage.
Project-aware implementation for multi-brand schema.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import time

import yt_dlp
from supabase import Client

from ..core.config import Config


logger = logging.getLogger(__name__)


class VideoDownloader:
    """
    Downloads videos from Instagram and uploads to Supabase Storage.

    Uses yt-dlp for downloading and project-aware storage paths.
    """

    def __init__(
        self,
        supabase_client: Client,
        temp_dir: Optional[Path] = None,
        storage_bucket: str = "videos"
    ):
        """
        Initialize video downloader.

        Args:
            supabase_client: Initialized Supabase client
            temp_dir: Temporary directory for downloads (default: ./temp/downloads)
            storage_bucket: Supabase storage bucket name
        """
        self.supabase = supabase_client
        self.storage_bucket = storage_bucket

        # Setup temp directory
        if temp_dir is None:
            temp_dir = Path("./temp/downloads")
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # yt-dlp configuration
        self.ytdlp_format = os.getenv("YTDLP_FORMAT", "best[ext=mp4]/best")
        self.ytdlp_retries = int(os.getenv("YTDLP_RETRIES", "3"))
        self.ytdlp_cookies_browser = os.getenv("YTDLP_COOKIES_BROWSER", "chrome")
        self.download_timeout = int(os.getenv("DOWNLOAD_TIMEOUT_SEC", "180"))
        self.max_video_size_mb = int(os.getenv("MAX_VIDEO_SIZE_MB", "500"))

        logger.info(f"VideoDownloader initialized with bucket: {storage_bucket}")

    def download_video(
        self,
        post_url: str,
        project_slug: str,
        post_id: str
    ) -> Dict:
        """
        Download video from Instagram using yt-dlp.

        Args:
            post_url: Instagram post URL
            project_slug: Project slug for organizing storage
            post_id: Post ID (shortCode) for filename

        Returns:
            Dict with metadata:
                - local_path: Path to downloaded file
                - duration_sec: Video duration
                - file_size_mb: File size
                - format: Video format

        Raises:
            RuntimeError: If download fails
        """
        logger.info(f"Downloading video: {post_url}")

        # Create output path
        output_filename = f"{project_slug}_{post_id}.mp4"
        output_path = self.temp_dir / output_filename

        # yt-dlp options
        ydl_opts = {
            'outtmpl': str(output_path.with_suffix('')),  # yt-dlp adds extension
            'quiet': False,
            'no_warnings': False,
            'format': self.ytdlp_format,
            'retries': self.ytdlp_retries,
            'fragment_retries': self.ytdlp_retries,
            'ignoreerrors': False,
            'no_check_certificate': True,
            'socket_timeout': self.download_timeout,
        }

        # Try to use browser cookies for authentication
        try:
            ydl_opts['cookiesfrombrowser'] = (self.ytdlp_cookies_browser,)
            logger.info(f"Using cookies from browser: {self.ytdlp_cookies_browser}")
        except Exception as e:
            logger.warning(f"Could not load browser cookies: {e}")

        # Download
        start_time = time.time()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(post_url, download=True)

                # Get actual downloaded file path
                actual_file = output_path.with_suffix('.mp4')
                if not actual_file.exists():
                    # Try finding the file (with or without extension)
                    possible_files = list(self.temp_dir.glob(f"{project_slug}_{post_id}*"))
                    if possible_files:
                        actual_file = possible_files[0]
                    else:
                        raise FileNotFoundError(f"Downloaded file not found: {output_path}.mp4")

                # Extract metadata
                duration_sec = info.get('duration', 0)
                file_size_mb = actual_file.stat().st_size / (1024 * 1024)
                video_format = info.get('format_id', 'unknown')

                download_time = time.time() - start_time

                logger.info(f"Download complete: {actual_file.name} ({file_size_mb:.2f}MB, {duration_sec}s)")
                logger.info(f"Download took {download_time:.1f}s")

                # Check file size
                if file_size_mb > self.max_video_size_mb:
                    logger.warning(f"Video exceeds size limit: {file_size_mb:.1f}MB > {self.max_video_size_mb}MB")

                return {
                    'local_path': actual_file,
                    'duration_sec': duration_sec,
                    'file_size_mb': round(file_size_mb, 2),
                    'format': video_format,
                    'download_time_sec': round(download_time, 1)
                }

        except Exception as e:
            logger.error(f"Download failed for {post_url}: {e}")
            raise RuntimeError(f"Video download failed: {e}")

    def upload_to_storage(
        self,
        local_path: Path,
        storage_path: str
    ) -> str:
        """
        Upload video file to Supabase Storage.

        Args:
            local_path: Path to local video file
            storage_path: Destination path in storage (e.g., "projects/yakety-pack/video.mp4")

        Returns:
            Public URL of uploaded video

        Raises:
            RuntimeError: If upload fails
        """
        logger.info(f"Uploading to storage: {storage_path}")

        try:
            # Read file
            with open(local_path, 'rb') as f:
                file_data = f.read()

            # Upload to Supabase Storage
            result = self.supabase.storage.from_(self.storage_bucket).upload(
                storage_path,
                file_data,
                file_options={"content-type": "video/mp4"}
            )

            # Get public URL
            public_url = self.supabase.storage.from_(self.storage_bucket).get_public_url(storage_path)

            logger.info(f"Upload complete: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Upload failed for {local_path}: {e}")
            raise RuntimeError(f"Storage upload failed: {e}")

    def process_post(
        self,
        post_url: str,
        post_db_id: str,
        project_slug: str,
        post_id: str
    ) -> Dict:
        """
        Download and upload video for a post.

        Args:
            post_url: Instagram post URL
            post_db_id: Post UUID in database
            project_slug: Project slug
            post_id: Post ID (shortCode)

        Returns:
            Dict with processing results:
                - status: "completed" | "failed"
                - storage_path: Path in storage (if successful)
                - public_url: Public URL (if successful)
                - duration_sec: Video duration
                - file_size_mb: File size
                - error: Error message (if failed)
        """
        local_path = None

        try:
            # Download video
            download_result = self.download_video(post_url, project_slug, post_id)
            local_path = download_result['local_path']

            # Create storage path
            storage_path = f"projects/{project_slug}/{local_path.name}"

            # Upload to storage
            public_url = self.upload_to_storage(local_path, storage_path)

            # Log processing success
            self._log_processing(
                post_db_id=post_db_id,
                status="completed",
                storage_path=storage_path,
                download_url=post_url,
                file_size_mb=download_result['file_size_mb'],
                duration_sec=download_result['duration_sec']
            )

            return {
                'status': 'completed',
                'storage_path': storage_path,
                'public_url': public_url,
                'duration_sec': download_result['duration_sec'],
                'file_size_mb': download_result['file_size_mb']
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Processing failed for {post_url}: {error_msg}")

            # Log failure
            self._log_processing(
                post_db_id=post_db_id,
                status="failed",
                download_url=post_url,
                error_message=error_msg
            )

            return {
                'status': 'failed',
                'error': error_msg
            }

        finally:
            # Cleanup temporary file
            if local_path and local_path.exists():
                try:
                    local_path.unlink()
                    logger.info(f"Deleted temporary file: {local_path}")
                except Exception as e:
                    logger.warning(f"Could not delete temp file: {e}")

    def _log_processing(
        self,
        post_db_id: str,
        status: str,
        download_url: str,
        storage_path: Optional[str] = None,
        file_size_mb: Optional[float] = None,
        duration_sec: Optional[float] = None,
        error_message: Optional[str] = None
    ):
        """
        Log video processing to database.

        Args:
            post_db_id: Post UUID
            status: "completed" | "failed"
            download_url: Original Instagram URL
            storage_path: Path in storage (if successful)
            file_size_mb: File size in MB
            duration_sec: Video duration
            error_message: Error message (if failed)
        """
        log_entry = {
            'post_id': post_db_id,
            'status': status,
            'download_url': download_url,
            'storage_path': storage_path,
            'file_size_mb': file_size_mb,
            'video_duration_sec': duration_sec,
            'error_message': error_message
        }

        try:
            self.supabase.table('video_processing_log').upsert(
                log_entry,
                on_conflict='post_id'
            ).execute()

            logger.info(f"Logged processing: {status} for post {post_db_id}")

        except Exception as e:
            logger.error(f"Failed to log processing: {e}")

    def cleanup_temp_files(self, older_than_hours: int = 24):
        """
        Clean up old temporary files.

        Args:
            older_than_hours: Delete files older than this many hours
        """
        logger.info(f"Cleaning up temp files older than {older_than_hours} hours")

        cutoff_time = time.time() - (older_than_hours * 3600)
        deleted_count = 0

        for file_path in self.temp_dir.glob("*"):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete {file_path}: {e}")

        logger.info(f"Deleted {deleted_count} old temporary files")
