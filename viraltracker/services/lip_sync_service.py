"""
LipSyncService - Clip-based lip-sync orchestration.

Handles multi-face video lip-sync by:
1. Normalizing video to Kling specs
2. Detecting faces via Kling API
3. Planning clips based on face time ranges
4. Processing each face clip independently (clip, upload, identify, lip-sync, poll)
5. Reassembling all clips into final video

Methods are granular for UI-driven progress (the UI calls each step
and updates st.status() between calls).
"""

import asyncio
import base64
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class LipSyncService:
    """Orchestration service for clip-based lip-sync processing."""

    PADDING_MS = 500
    MIN_CLIP_DURATION_MS = 2000  # Kling minimum
    LIP_SYNC_BUCKET = "kling-videos"

    def __init__(self):
        self.supabase = get_supabase_client()

    def _get_ffmpeg(self):
        from .ffmpeg_service import FFmpegService
        return FFmpegService()

    def _get_kling(self):
        from .kling_video_service import KlingVideoService
        return KlingVideoService()

    # =========================================================================
    # Job lifecycle
    # =========================================================================

    async def create_job(
        self,
        org_id: str,
        brand_id: str,
        filename: str,
        video_info: Dict[str, Any],
        original_audio_volume: float = 0.0,
        padding_ms: int = 500,
    ) -> str:
        """Create a lip_sync_jobs DB record.

        Args:
            org_id: Organization UUID.
            brand_id: Brand UUID.
            filename: Original filename.
            video_info: Output from FFmpegService.probe_video_info().
            original_audio_volume: Volume for original video audio (0-2).
            padding_ms: Edge padding in ms.

        Returns:
            Job UUID string.
        """
        job_id = str(uuid.uuid4())
        resolution = f"{video_info.get('width', 0)}x{video_info.get('height', 0)}"

        await asyncio.to_thread(
            lambda: self.supabase.table("lip_sync_jobs").insert({
                "id": job_id,
                "organization_id": org_id,
                "brand_id": brand_id,
                "original_filename": filename,
                "video_duration_ms": video_info.get("duration_ms"),
                "video_resolution": resolution,
                "status": "normalizing",
                "original_audio_volume": original_audio_volume,
                "padding_ms": padding_ms,
            }).execute()
        )

        logger.info(f"Created lip-sync job {job_id} for {filename}")
        return job_id

    async def update_job(self, job_id: str, **kwargs) -> None:
        """Update job record in DB."""
        if "completed_at" not in kwargs and kwargs.get("status") == "completed":
            kwargs["completed_at"] = datetime.now(timezone.utc).isoformat()

        await asyncio.to_thread(
            lambda: self.supabase.table("lip_sync_jobs")
            .update(kwargs)
            .eq("id", job_id)
            .execute()
        )

    # =========================================================================
    # Step 1: Normalize
    # =========================================================================

    async def normalize_video(self, video_bytes: bytes) -> bytes:
        """Normalize video to 1080p Kling specs without duration cap.

        Args:
            video_bytes: Raw video bytes.

        Returns:
            Normalized video bytes.
        """
        ffmpeg = self._get_ffmpeg()
        normalized = await asyncio.to_thread(
            ffmpeg.normalize_video_for_kling, video_bytes, None
        )
        logger.info(
            f"Normalized video: {len(video_bytes)} -> {len(normalized)} bytes"
        )
        return normalized

    # =========================================================================
    # Step 2: Detect faces
    # =========================================================================

    async def detect_faces(
        self, org_id: str, brand_id: str, video_url: str
    ) -> Dict[str, Any]:
        """Call Kling identify_faces API.

        Args:
            org_id: Organization UUID.
            brand_id: Brand UUID.
            video_url: Public URL of the normalized video.

        Returns:
            Dict with generation_id, session_id, face_data, session_expires_at.
        """
        kling = self._get_kling()
        result = await kling.identify_faces(
            organization_id=org_id,
            brand_id=brand_id,
            video_url=video_url,
        )
        face_count = len(result.get("face_data", []))
        logger.info(f"Detected {face_count} face(s)")
        return result

    # =========================================================================
    # Step 3: Plan clips
    # =========================================================================

    def plan_clips(
        self,
        face_data: List[Dict[str, Any]],
        video_duration_ms: int,
        padding_ms: int = 500,
    ) -> Dict[str, Any]:
        """Plan face clips and gap clips from face detection ranges.

        Pure logic (no I/O). Pads each face range and ensures
        MIN_CLIP_DURATION_MS. Identifies gap segments between face clips.

        Args:
            face_data: List of {face_id, start_time, end_time, ...} from Kling.
                Times are in seconds (float).
            video_duration_ms: Total video duration in ms.
            padding_ms: Padding to add around face ranges in ms.

        Returns:
            Dict with face_clips and gap_clips lists.
        """
        if not face_data:
            return {"face_clips": [], "gap_clips": []}

        face_clips = []
        for face in face_data:
            face_id = face.get("face_id", "")
            # Kling returns times in seconds
            start_s = float(face.get("start_time", 0))
            end_s = float(face.get("end_time", 0))
            start_ms = int(start_s * 1000)
            end_ms = int(end_s * 1000)

            # Apply padding
            padded_start = max(0, start_ms - padding_ms)
            padded_end = min(video_duration_ms, end_ms + padding_ms)

            # Enforce minimum clip duration
            clip_duration = padded_end - padded_start
            if clip_duration < self.MIN_CLIP_DURATION_MS:
                deficit = self.MIN_CLIP_DURATION_MS - clip_duration
                half = deficit // 2
                padded_start = max(0, padded_start - half)
                padded_end = min(video_duration_ms, padded_end + half + (deficit % 2))

            face_clips.append({
                "face_id": face_id,
                "start_ms": padded_start,
                "end_ms": padded_end,
                "original_start_ms": start_ms,
                "original_end_ms": end_ms,
            })

        # Sort by start time
        face_clips.sort(key=lambda c: c["start_ms"])

        # Identify gap clips (segments between face clips, and before/after)
        gap_clips = []
        prev_end = 0
        for fc in face_clips:
            if fc["start_ms"] > prev_end:
                gap_clips.append({
                    "start_ms": prev_end,
                    "end_ms": fc["start_ms"],
                })
            prev_end = fc["end_ms"]

        if prev_end < video_duration_ms:
            gap_clips.append({
                "start_ms": prev_end,
                "end_ms": video_duration_ms,
            })

        logger.info(
            f"Planned {len(face_clips)} face clip(s) and {len(gap_clips)} gap clip(s)"
        )
        return {"face_clips": face_clips, "gap_clips": gap_clips}

    # =========================================================================
    # Step 4: Process individual clips
    # =========================================================================

    async def process_face_clip(
        self,
        org_id: str,
        brand_id: str,
        job_id: str,
        clip_index: int,
        face_clip: Dict[str, Any],
        norm_video_path: Path,
        full_audio_path: Path,
        original_audio_volume: float = 0.0,
    ) -> Dict[str, Any]:
        """Process ONE face clip: clip video/audio, upload, identify face, lip-sync, poll.

        Args:
            org_id: Organization UUID.
            brand_id: Brand UUID.
            job_id: Parent lip_sync_jobs UUID.
            clip_index: Index of this clip for naming.
            face_clip: Dict with face_id, start_ms, end_ms.
            norm_video_path: Local path to the normalized video.
            full_audio_path: Local path to the full audio file.
            original_audio_volume: Volume for original video audio (0-2).

        Returns:
            Dict with status, storage_path, generation_id, error.
        """
        from .kling_video_service import KlingEndpoint

        ffmpeg = self._get_ffmpeg()
        kling = self._get_kling()

        start_ms = face_clip["start_ms"]
        end_ms = face_clip["end_ms"]
        face_id = face_clip["face_id"]

        with tempfile.TemporaryDirectory(prefix="lip_clip_") as tmpdir:
            tmpdir = Path(tmpdir)
            clip_video_path = tmpdir / f"clip_{clip_index}.mp4"
            clip_audio_path = tmpdir / f"clip_{clip_index}.m4a"

            # Clip video and audio segments
            video_ok = await asyncio.to_thread(
                ffmpeg.clip_video, norm_video_path, start_ms, end_ms, clip_video_path
            )
            if not video_ok:
                return {"status": "failed", "error": "Failed to clip video segment"}

            audio_ok = await asyncio.to_thread(
                ffmpeg.clip_audio, full_audio_path, start_ms, end_ms, clip_audio_path
            )
            if not audio_ok:
                return {"status": "failed", "error": "Failed to clip audio segment"}

            # Upload clip video to Supabase for Kling API
            clip_storage_key = f"lip-sync/{brand_id}/{job_id}/face_clip_{clip_index}.mp4"
            clip_video_bytes = clip_video_path.read_bytes()

            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(self.LIP_SYNC_BUCKET).upload(
                    clip_storage_key, clip_video_bytes,
                    {"content-type": "video/mp4", "upsert": "true"},
                )
            )

            # Get signed URL for Kling API
            signed = self.supabase.storage.from_(self.LIP_SYNC_BUCKET).create_signed_url(
                clip_storage_key, 3600
            )
            clip_video_url = signed.get("signedURL", "") if isinstance(signed, dict) else ""

            if not clip_video_url:
                return {"status": "failed", "error": "Failed to get signed URL for clip"}

            try:
                # Step A: Identify face in the clip
                face_result = await kling.identify_faces(
                    organization_id=org_id,
                    brand_id=brand_id,
                    video_url=clip_video_url,
                )

                clip_session_id = face_result.get("session_id")
                clip_faces = face_result.get("face_data", [])
                identify_gen_id = face_result.get("generation_id")

                if not clip_faces:
                    logger.warning(f"No faces in clip {clip_index}, using original")
                    return {
                        "status": "no_face",
                        "storage_path": f"{self.LIP_SYNC_BUCKET}/{clip_storage_key}",
                        "generation_id": identify_gen_id,
                        "error": None,
                    }

                # Use the first detected face in the clip
                clip_face_id = clip_faces[0].get("face_id", "")

                # Prepare audio as base64 for Kling API
                clip_audio_bytes = clip_audio_path.read_bytes()
                audio_b64 = base64.b64encode(clip_audio_bytes).decode("utf-8")

                # Compute sound_end_time: min(audio_duration, video_duration)
                clip_video_info = await asyncio.to_thread(
                    ffmpeg.probe_video_info, clip_video_path
                )
                clip_video_duration_ms = clip_video_info.get("duration_ms", end_ms - start_ms)
                clip_audio_duration_ms = await asyncio.to_thread(
                    ffmpeg.get_duration_ms, clip_audio_path
                )
                # Subtract 100ms safety margin — Kling may re-encode the video
                # with a slightly different duration than what ffprobe reports,
                # causing "audio end timestamp > video duration" errors.
                sound_end_time = min(clip_audio_duration_ms, clip_video_duration_ms) - 100
                sound_end_time = max(sound_end_time, 0)

                logger.info(
                    f"Clip {clip_index}: video={clip_video_duration_ms}ms, "
                    f"audio={clip_audio_duration_ms}ms, sound_end_time={sound_end_time}ms"
                )

                # Step B: Apply lip-sync
                ls_result = await kling.apply_lip_sync(
                    organization_id=org_id,
                    brand_id=brand_id,
                    session_id=clip_session_id,
                    face_id=clip_face_id,
                    sound_file=audio_b64,
                    sound_end_time=sound_end_time,
                    original_audio_volume=original_audio_volume,
                    parent_generation_id=identify_gen_id,
                )

                ls_gen_id = ls_result.get("generation_id")
                ls_task_id = ls_result.get("kling_task_id")

                # Link generations to the lip_sync_job
                for gen_id in [identify_gen_id, ls_gen_id]:
                    if gen_id:
                        try:
                            await asyncio.to_thread(
                                lambda gid=gen_id: self.supabase.table("kling_video_generations")
                                .update({"lip_sync_job_id": job_id})
                                .eq("id", gid)
                                .execute()
                            )
                        except Exception as e:
                            logger.warning(f"Failed to link generation {gen_id} to job: {e}")

                if not ls_task_id:
                    return {
                        "status": "failed",
                        "generation_id": ls_gen_id,
                        "error": "No task ID from lip-sync API",
                    }

                # Step C: Poll to completion
                poll_result = await kling.poll_and_complete(
                    generation_id=ls_gen_id,
                    kling_task_id=ls_task_id,
                    endpoint_type=KlingEndpoint.LIP_SYNC,
                    timeout_seconds=600,
                )

                return {
                    "status": poll_result.get("status", "failed"),
                    "storage_path": poll_result.get("video_storage_path"),
                    "generation_id": ls_gen_id,
                    "error": poll_result.get("error_message"),
                }

            except Exception as e:
                logger.error(f"Face clip {clip_index} processing failed: {e}")
                # Return original clip as fallback
                return {
                    "status": "failed",
                    "storage_path": f"{self.LIP_SYNC_BUCKET}/{clip_storage_key}",
                    "generation_id": None,
                    "error": str(e),
                }

    async def extract_gap_clip(
        self,
        job_id: str,
        brand_id: str,
        gap_index: int,
        gap_clip: Dict[str, Any],
        norm_video_path: Path,
    ) -> Dict[str, Any]:
        """Extract ONE gap clip (no lip-sync needed), upload to storage.

        Args:
            job_id: Parent job UUID.
            brand_id: Brand UUID.
            gap_index: Index of gap clip.
            gap_clip: Dict with start_ms, end_ms.
            norm_video_path: Local path to the normalized video.

        Returns:
            Dict with storage_path.
        """
        ffmpeg = self._get_ffmpeg()

        with tempfile.TemporaryDirectory(prefix="lip_gap_") as tmpdir:
            tmpdir = Path(tmpdir)
            clip_path = tmpdir / f"gap_{gap_index}.mp4"

            ok = await asyncio.to_thread(
                ffmpeg.clip_video,
                norm_video_path,
                gap_clip["start_ms"],
                gap_clip["end_ms"],
                clip_path,
            )

            if not ok:
                return {"storage_path": None, "error": "Failed to extract gap clip"}

            # Upload
            storage_key = f"lip-sync/{brand_id}/{job_id}/gap_clip_{gap_index}.mp4"
            clip_bytes = clip_path.read_bytes()

            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(self.LIP_SYNC_BUCKET).upload(
                    storage_key, clip_bytes,
                    {"content-type": "video/mp4", "upsert": "true"},
                )
            )

            return {
                "storage_path": f"{self.LIP_SYNC_BUCKET}/{storage_key}",
            }

    # =========================================================================
    # Step 5: Reassemble
    # =========================================================================

    async def reassemble(
        self,
        job_id: str,
        brand_id: str,
        face_results: List[Dict[str, Any]],
        gap_results: List[Dict[str, Any]],
        face_clips: List[Dict[str, Any]],
        gap_clips: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Sort all clips by start_ms, download, concat, upload final.

        Args:
            job_id: Job UUID.
            brand_id: Brand UUID.
            face_results: Results from process_face_clip() calls.
            gap_results: Results from extract_gap_clip() calls.
            face_clips: Face clip plans (with start_ms).
            gap_clips: Gap clip plans (with start_ms).

        Returns:
            Dict with final_video_path, signed_url.
        """
        ffmpeg = self._get_ffmpeg()

        # Build ordered list of all clips with their start times
        all_clips = []
        for i, (fc, result) in enumerate(zip(face_clips, face_results)):
            path = result.get("storage_path")
            if path:
                all_clips.append({"start_ms": fc["start_ms"], "storage_path": path})

        for i, (gc, result) in enumerate(zip(gap_clips, gap_results)):
            path = result.get("storage_path")
            if path:
                all_clips.append({"start_ms": gc["start_ms"], "storage_path": path})

        # Sort by start time
        all_clips.sort(key=lambda c: c["start_ms"])

        if not all_clips:
            return {"final_video_path": None, "error": "No clips to reassemble"}

        if len(all_clips) == 1:
            # Single clip, no concat needed
            path = all_clips[0]["storage_path"]
            signed = self._sign_path(path)
            return {"final_video_path": path, "signed_url": signed}

        with tempfile.TemporaryDirectory(prefix="lip_reassemble_") as tmpdir:
            tmpdir = Path(tmpdir)

            # Download all clips
            local_paths = []
            for i, clip in enumerate(all_clips):
                storage_path = clip["storage_path"]
                parts = storage_path.split("/", 1)
                if len(parts) != 2:
                    continue
                bucket, key = parts

                data = await asyncio.to_thread(
                    lambda b=bucket, k=key: self.supabase.storage.from_(b).download(k)
                )
                local_path = tmpdir / f"clip_{i:03d}.mp4"
                local_path.write_bytes(data)
                local_paths.append(local_path)

            if len(local_paths) < 2:
                if local_paths:
                    # Only one clip downloaded successfully
                    path = all_clips[0]["storage_path"]
                    signed = self._sign_path(path)
                    return {"final_video_path": path, "signed_url": signed}
                return {"final_video_path": None, "error": "No clips downloaded"}

            # Concatenate
            output_path = tmpdir / "final.mp4"
            ok = await asyncio.to_thread(
                ffmpeg.concatenate_video_files, local_paths, output_path
            )

            if not ok:
                return {"final_video_path": None, "error": "FFmpeg concatenation failed"}

            # Upload final
            final_key = f"lip-sync/{brand_id}/{job_id}/final.mp4"
            final_bytes = output_path.read_bytes()

            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(self.LIP_SYNC_BUCKET).upload(
                    final_key, final_bytes,
                    {"content-type": "video/mp4", "upsert": "true"},
                )
            )

            final_path = f"{self.LIP_SYNC_BUCKET}/{final_key}"
            signed = self._sign_path(final_path)

            # Get duration
            info = await asyncio.to_thread(ffmpeg.probe_video_info, output_path)

            return {
                "final_video_path": final_path,
                "final_video_duration_ms": info.get("duration_ms"),
                "signed_url": signed,
            }

    # =========================================================================
    # Job listing
    # =========================================================================

    async def list_jobs(
        self, org_id: str, brand_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """List past lip-sync jobs for a brand.

        Args:
            org_id: Organization UUID.
            brand_id: Brand UUID.
            limit: Max results.

        Returns:
            List of job records.
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("lip_sync_jobs")
            .select("*")
            .eq("organization_id", org_id)
            .eq("brand_id", brand_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    # =========================================================================
    # Helpers
    # =========================================================================

    def _sign_path(self, storage_path: str) -> str:
        """Create a signed URL from a bucket/key storage path."""
        parts = storage_path.split("/", 1)
        if len(parts) != 2:
            return ""
        bucket, key = parts
        signed = self.supabase.storage.from_(bucket).create_signed_url(key, 3600)
        return signed.get("signedURL", "") if isinstance(signed, dict) else ""
