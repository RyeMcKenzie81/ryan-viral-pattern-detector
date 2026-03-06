"""
ManualVideoService - Manual multi-scene video creation.

Handles frame generation, scene-by-scene video creation via Kling Omni,
and FFmpeg-based concatenation for the Manual Creator workflow.
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import Config
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ManualVideoService:
    """
    Service for manual multi-scene video creation.

    Workflow:
    1. Generate keyframe images (via Gemini) with avatar reference
    2. Build scenes with prompts, dialogue, start/end frames
    3. Generate scene videos via Kling Omni (element + voice bound)
    4. Concatenate scene clips into final video via FFmpeg
    """

    FRAME_STORAGE_BUCKET = "avatars"

    def __init__(self):
        self.supabase = get_supabase_client()

    # Map Kling aspect ratios to pixel dimensions for frame generation
    ASPECT_RATIO_DIMENSIONS = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
    }

    async def generate_frame(
        self,
        brand_id: str,
        prompt: str,
        avatar_id: Optional[str] = None,
        aspect_ratio: str = "9:16",
        reference_image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Generate a keyframe image using Gemini with optional avatar reference.

        The image is generated at the correct aspect ratio so Kling Omni
        uses it properly when assigned as a first/end frame.

        Args:
            brand_id: Brand UUID string
            prompt: Image generation prompt
            avatar_id: Optional avatar UUID for reference consistency
            aspect_ratio: Target aspect ratio ("9:16", "16:9", "1:1")
            reference_image_bytes: Optional raw image bytes to use as visual reference

        Returns:
            Dict with id, storage_path, signed_url, prompt, created_at
        """
        import base64
        from .avatar_service import AvatarService
        from .gemini_service import GeminiService

        avatar_svc = AvatarService()
        gemini_svc = GeminiService()

        # Collect reference images (avatar + user-provided)
        ref_images_b64 = []
        if avatar_id:
            from uuid import UUID
            ref_bytes = await avatar_svc.get_reference_image_bytes(UUID(avatar_id), slot=1)
            if ref_bytes:
                ref_images_b64.append(base64.b64encode(ref_bytes).decode("utf-8"))
        if reference_image_bytes:
            ref_images_b64.append(base64.b64encode(reference_image_bytes).decode("utf-8"))

        # Pass None if empty
        final_refs = ref_images_b64 if ref_images_b64 else None

        # Add aspect ratio instruction to prompt so Gemini generates the right shape
        w, h = self.ASPECT_RATIO_DIMENSIONS.get(aspect_ratio, (1080, 1920))
        ratio_prompt = (
            f"{prompt}\n\n"
            f"IMPORTANT: Generate this image in {aspect_ratio} aspect ratio "
            f"({w}x{h} pixels, {'portrait/vertical' if h > w else 'landscape/horizontal' if w > h else 'square'} orientation)."
        )

        # Generate via Gemini
        result_b64 = await gemini_svc.generate_image(
            prompt=ratio_prompt,
            reference_images=final_refs,
            temperature=0.4,
            image_size="2K",
        )

        # Decode to bytes
        if isinstance(result_b64, dict):
            image_bytes = base64.b64decode(result_b64["image_base64"])
        else:
            image_bytes = base64.b64decode(result_b64)

        # Upload to Supabase storage
        frame_id = str(uuid.uuid4())
        storage_path = f"{brand_id}/manual_frames/{frame_id}.png"

        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.FRAME_STORAGE_BUCKET).upload(
                storage_path,
                image_bytes,
                {"content-type": "image/png", "upsert": "true"},
            )
        )

        # Get signed URL for display
        signed = self.supabase.storage.from_(self.FRAME_STORAGE_BUCKET).create_signed_url(
            storage_path, 3600
        )
        signed_url = signed.get("signedURL", "") if isinstance(signed, dict) else ""

        return {
            "id": frame_id,
            "storage_path": f"{self.FRAME_STORAGE_BUCKET}/{storage_path}",
            "signed_url": signed_url,
            "prompt": prompt,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def generate_scene_video(
        self,
        organization_id: str,
        brand_id: str,
        scene: Dict[str, Any],
        avatar_id: str,
        frame_gallery: List[Dict[str, Any]],
        mode: str = "pro",
        aspect_ratio: str = "9:16",
    ) -> Dict[str, Any]:
        """
        Generate a single scene video via Kling Omni.

        Args:
            organization_id: Org UUID string
            brand_id: Brand UUID string
            scene: Scene dict with prompt, dialogue, duration, start/end frame IDs
            avatar_id: Avatar UUID string (must have kling_element_id)
            frame_gallery: List of frame dicts from generate_frame()
            mode: Quality mode - "pro" or "std"
            aspect_ratio: Aspect ratio - "16:9", "9:16", or "1:1"

        Returns:
            Dict with generation result including status, video path, etc.

        Raises:
            ValueError: If avatar has no Kling element
        """
        from .avatar_service import AvatarService
        from .kling_video_service import KlingVideoService, KlingEndpoint
        from uuid import UUID

        avatar_svc = AvatarService()
        kling_svc = KlingVideoService()

        # Load avatar
        avatar = await avatar_svc.get_avatar(UUID(avatar_id))
        if not avatar:
            raise ValueError(f"Avatar {avatar_id} not found")
        if not avatar.kling_element_id:
            raise ValueError(
                f"Avatar '{avatar.name}' has no Kling element. "
                "Create an element first in Avatar Manager."
            )

        # Build image_list from start/end frames
        image_list = None
        gallery_by_id = {f["id"]: f for f in frame_gallery}

        start_frame_id = scene.get("start_frame_id")
        end_frame_id = scene.get("end_frame_id")

        if start_frame_id or end_frame_id:
            image_list = []

            if start_frame_id and start_frame_id in gallery_by_id:
                frame = gallery_by_id[start_frame_id]
                url = await self._get_frame_url(frame)
                if url:
                    image_list.append({"image_url": url, "type": "first_frame"})

            if end_frame_id and end_frame_id in gallery_by_id:
                frame = gallery_by_id[end_frame_id]
                url = await self._get_frame_url(frame)
                if url:
                    image_list.append({"image_url": url, "type": "end_frame"})

        # Build element_list
        element_list = [{"element_id": avatar.kling_element_id}]

        # Build prompt with element reference and dialogue
        # The element has a bound voice — attribute dialogue directly to the
        # element so Kling uses the bound voice instead of default TTS.
        visual_prompt = scene.get("prompt", "")
        dialogue = scene.get("dialogue", "").strip()
        if dialogue:
            full_prompt = f"<<<element_1>>> {visual_prompt}. <<<element_1>>> says: '{dialogue}'"
        else:
            full_prompt = f"<<<element_1>>> {visual_prompt}"

        # Duration as string
        duration = str(scene.get("duration", 5))

        # Generate via Kling Omni
        gen_result = await kling_svc.generate_omni_video(
            organization_id=organization_id,
            brand_id=brand_id,
            prompt=full_prompt,
            duration=duration,
            mode=mode,
            sound="on",
            image_list=image_list if image_list else None,
            element_list=element_list,
            aspect_ratio=aspect_ratio,
        )

        generation_id = gen_result.get("generation_id")
        kling_task_id = gen_result.get("kling_task_id")

        if not kling_task_id:
            return {
                "status": "failed",
                "error": "No task ID returned from Kling",
                "generation_id": generation_id,
            }

        # Poll to completion
        poll_result = await kling_svc.poll_and_complete(
            generation_id=generation_id,
            kling_task_id=kling_task_id,
            endpoint_type=KlingEndpoint.OMNI_VIDEO,
            timeout_seconds=900,
        )

        return {
            "generation_id": generation_id,
            "kling_task_id": kling_task_id,
            "status": poll_result.get("status", "failed"),
            "video_storage_path": poll_result.get("video_storage_path"),
            "video_url": poll_result.get("video_url"),
            "error_message": poll_result.get("error_message"),
            "generation_time_seconds": poll_result.get("generation_time_seconds"),
        }

    async def concatenate_scenes(
        self,
        scene_clips: List[Dict[str, Any]],
        brand_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Concatenate multiple scene video clips into a final video using FFmpeg.

        Uses the concat filter pattern (not demuxer) with SAR normalization
        for reliable audio sync across clips.

        Args:
            scene_clips: List of dicts with video_storage_path for each scene
            brand_id: Brand UUID string
            session_id: Session UUID for output path organization

        Returns:
            Dict with final_video_path, duration_sec, signed_url
        """
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")

        if not ffmpeg_path or not ffprobe_path:
            raise RuntimeError("FFmpeg/FFprobe not found on system PATH")

        if len(scene_clips) < 2:
            raise ValueError("Need at least 2 clips to concatenate")

        temp_dir = Path(tempfile.mkdtemp(prefix="manual_concat_"))

        try:
            # Download clips from Supabase to temp dir
            local_paths = []
            for i, clip in enumerate(scene_clips):
                storage_path = clip.get("video_storage_path", "")
                if not storage_path:
                    raise ValueError(f"Scene {i} has no video storage path")

                # Parse bucket/path from full storage path
                parts = storage_path.split("/", 1)
                if len(parts) != 2:
                    raise ValueError(f"Invalid storage path: {storage_path}")
                bucket, path = parts

                video_data = await asyncio.to_thread(
                    lambda b=bucket, p=path: self.supabase.storage.from_(b).download(p)
                )

                local_path = temp_dir / f"clip_{i:03d}.mp4"
                local_path.write_bytes(video_data)
                local_paths.append(local_path)

            # Ensure all clips have audio tracks (required for concat filter)
            for path in local_paths:
                has_audio = await self._has_audio_stream(path, ffprobe_path)
                if not has_audio:
                    await self._add_silent_audio(path, ffmpeg_path, ffprobe_path)

            # Build FFmpeg concat filter command
            output_path = temp_dir / "final.mp4"
            n = len(local_paths)

            cmd = [ffmpeg_path, "-y"]
            for path in local_paths:
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

            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=600
            )

            if process.returncode != 0:
                error_msg = stderr.decode()[-1500:] if stderr else "Unknown error"
                logger.error(f"FFmpeg concat failed: {error_msg}")
                raise RuntimeError(f"FFmpeg concat failed: {error_msg[:200]}")

            # Upload to Supabase storage
            final_storage_key = f"manual/{session_id}/final.mp4"
            final_data = output_path.read_bytes()

            await asyncio.to_thread(
                lambda: self.supabase.storage.from_("kling-videos").upload(
                    final_storage_key, final_data, {"content-type": "video/mp4"}
                )
            )

            full_storage_path = f"kling-videos/{final_storage_key}"

            # Get duration
            duration_sec = await self._get_duration(output_path, ffprobe_path)

            # Get signed URL
            signed = self.supabase.storage.from_("kling-videos").create_signed_url(
                final_storage_key, 3600
            )
            signed_url = signed.get("signedURL", "") if isinstance(signed, dict) else ""

            return {
                "final_video_path": full_storage_path,
                "duration_sec": duration_sec,
                "signed_url": signed_url,
            }

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def estimate_cost(
        self,
        scenes: List[Dict[str, Any]],
        mode: str = "pro",
    ) -> Dict[str, Any]:
        """
        Estimate generation cost for a set of scenes.

        Args:
            scenes: List of scene dicts with duration field
            mode: Quality mode - "pro" or "std"

        Returns:
            Dict with per_scene_costs, total_estimated_cost, total_duration_sec
        """
        cost_key = (
            f"kling_omni_{mode}_audio_seconds"
        )

        per_scene = []
        total_cost = 0.0
        total_duration = 0

        for scene in scenes:
            dur = int(scene.get("duration", 5))
            scene_cost = dur * Config.get_unit_cost(cost_key)
            per_scene.append({
                "scene_id": scene.get("id", "?"),
                "duration": dur,
                "cost": round(scene_cost, 4),
            })
            total_cost += scene_cost
            total_duration += dur

        return {
            "per_scene_costs": per_scene,
            "total_estimated_cost": round(total_cost, 4),
            "total_duration_sec": total_duration,
        }

    async def download_frame_image(self, frame: Dict[str, Any]) -> Optional[bytes]:
        """
        Download a frame image's raw bytes from Supabase storage.

        Args:
            frame: Frame dict from generate_frame() with storage_path

        Returns:
            Image bytes, or None if download fails
        """
        storage_path = frame.get("storage_path", "")
        if not storage_path:
            return None

        parts = storage_path.split("/", 1)
        if len(parts) != 2:
            return None
        bucket, path = parts

        try:
            data = await asyncio.to_thread(
                lambda: self.supabase.storage.from_(bucket).download(path)
            )
            return data
        except Exception as e:
            logger.warning(f"Failed to download frame image {storage_path}: {e}")
            return None

    # =========================================================================
    # Project persistence
    # =========================================================================

    def save_project(
        self,
        organization_id: str,
        brand_id: str,
        project_id: Optional[str],
        name: str,
        avatar_id: Optional[str],
        quality_mode: str,
        aspect_ratio: str,
        scenes: List[Dict[str, Any]],
        frame_gallery: List[Dict[str, Any]],
        final_video_path: Optional[str] = None,
        final_video_duration_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Upsert a manual video project.

        Strips signed_url from frame gallery items (they expire).
        Auto-computes status and scene_count.

        Args:
            organization_id: Org UUID.
            brand_id: Brand UUID.
            project_id: Existing project UUID, or None to create new.
            name: Project name.
            avatar_id: Avatar UUID.
            quality_mode: "pro" or "std".
            aspect_ratio: "9:16", "16:9", or "1:1".
            scenes: Scenes list (same structure as session state).
            frame_gallery: Frame gallery list.
            final_video_path: Storage path of final video if assembled.
            final_video_duration_sec: Duration of final video.

        Returns:
            Dict with id, name, status, updated_at.
        """
        # Strip signed_url from frames (they expire)
        clean_gallery = []
        for frame in frame_gallery:
            clean = {k: v for k, v in frame.items() if k != "signed_url"}
            clean_gallery.append(clean)

        # Auto-compute status
        has_final = bool(final_video_path)
        has_generations = any(
            any(g.get("status") == "succeed" for g in s.get("generations", []))
            for s in scenes
        )
        if has_final:
            status = "completed"
        elif has_generations:
            status = "in_progress"
        else:
            status = "draft"

        record = {
            "organization_id": organization_id,
            "brand_id": brand_id,
            "name": name,
            "status": status,
            "avatar_id": avatar_id,
            "quality_mode": quality_mode,
            "aspect_ratio": aspect_ratio,
            "frame_gallery": clean_gallery,
            "scenes": scenes,
            "final_video_path": final_video_path,
            "final_video_duration_sec": final_video_duration_sec,
            "scene_count": len(scenes),
        }

        if project_id:
            # Update
            result = self.supabase.table("manual_video_projects").update(
                record
            ).eq("id", project_id).execute()
        else:
            # Insert
            project_id = str(uuid.uuid4())
            record["id"] = project_id
            result = self.supabase.table("manual_video_projects").insert(
                record
            ).execute()

        row = result.data[0] if result.data else record
        logger.info(f"Saved project {project_id} ({name}) as {status}")
        return {
            "id": row.get("id", project_id),
            "name": row.get("name", name),
            "status": row.get("status", status),
            "updated_at": row.get("updated_at"),
        }

    def list_projects(
        self,
        brand_id: str,
        organization_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List projects ordered by updated_at DESC.

        Args:
            brand_id: Brand UUID.
            organization_id: Org UUID.
            limit: Max results.

        Returns:
            List of project records (full rows).
        """
        result = self.supabase.table("manual_video_projects").select(
            "id, name, status, avatar_id, quality_mode, aspect_ratio, "
            "scene_count, final_video_path, final_video_duration_sec, "
            "created_at, updated_at"
        ).eq("brand_id", brand_id).eq(
            "organization_id", organization_id
        ).order(
            "updated_at", desc=True
        ).limit(limit).execute()

        return result.data or []

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Load a project and re-sign all storage paths.

        Re-generates signed URLs for frames and scene videos.
        If avatar_id references a deleted avatar, sets avatar_id=None.

        Args:
            project_id: Project UUID.

        Returns:
            Full project dict with refreshed URLs, or None.
        """
        result = self.supabase.table("manual_video_projects").select(
            "*"
        ).eq("id", project_id).single().execute()

        if not result.data:
            return None

        project = result.data

        # Refresh frame gallery URLs
        gallery = project.get("frame_gallery") or []
        for frame in gallery:
            storage_path = frame.get("storage_path", "")
            if storage_path:
                parts = storage_path.split("/", 1)
                if len(parts) == 2:
                    try:
                        signed = self.supabase.storage.from_(parts[0]).create_signed_url(
                            parts[1], 3600
                        )
                        frame["signed_url"] = (
                            signed.get("signedURL", "")
                            if isinstance(signed, dict) else ""
                        )
                    except Exception:
                        frame["signed_url"] = ""
                        frame["missing"] = True
            else:
                frame["signed_url"] = ""

        # Check avatar still exists
        avatar_id = project.get("avatar_id")
        if avatar_id:
            check = self.supabase.table("brand_avatars").select("id").eq(
                "id", avatar_id
            ).execute()
            if not check.data:
                project["avatar_id"] = None
                project["_avatar_warning"] = "Avatar was deleted"

        project["frame_gallery"] = gallery
        logger.info(f"Loaded project {project_id}")
        return project

    def delete_project(self, project_id: str) -> bool:
        """Hard delete a project. Storage files remain.

        Args:
            project_id: Project UUID.

        Returns:
            True if deleted.
        """
        try:
            self.supabase.table("manual_video_projects").delete().eq(
                "id", project_id
            ).execute()
            logger.info(f"Deleted project {project_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete project {project_id}: {e}")
            return False

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _get_frame_url(self, frame: Dict[str, Any]) -> Optional[str]:
        """Get a signed URL for a frame image."""
        storage_path = frame.get("storage_path", "")
        if not storage_path:
            return None

        parts = storage_path.split("/", 1)
        if len(parts) != 2:
            return None
        bucket, path = parts

        signed = self.supabase.storage.from_(bucket).create_signed_url(path, 3600)
        return signed.get("signedURL", "") if isinstance(signed, dict) else None

    async def _has_audio_stream(self, video_path: Path, ffprobe_path: str) -> bool:
        """Check if a video file has an audio stream."""
        cmd = [
            ffprobe_path, "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return bool(stdout.decode().strip())
        except Exception as e:
            logger.debug(f"Audio stream check failed for {video_path}: {e}")
            return False

    async def _add_silent_audio(
        self, video_path: Path, ffmpeg_path: str, ffprobe_path: str
    ) -> None:
        """Add a silent audio track to a video that's missing one."""
        duration = await self._get_duration(video_path, ffprobe_path)
        if duration is None:
            duration = 5.0

        output_path = video_path.with_suffix(".with_audio.mp4")
        cmd = [
            ffmpeg_path, "-y",
            "-i", str(video_path),
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()

        if process.returncode == 0 and output_path.exists():
            # Replace original with version that has audio
            output_path.replace(video_path)

    async def _get_duration(
        self, file_path: Path, ffprobe_path: Optional[str] = None
    ) -> Optional[float]:
        """Get file duration in seconds via ffprobe."""
        if not ffprobe_path:
            ffprobe_path = shutil.which("ffprobe")
        if not ffprobe_path:
            return None

        cmd = [
            ffprobe_path, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(file_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode == 0:
                return float(stdout.decode().strip())
        except Exception as e:
            logger.debug(f"Duration probe failed for {file_path}: {e}")
        return None
