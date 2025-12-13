"""
Editor Handoff Service - Generate handoff packages for video editors.

Collects all project artifacts (script, audio, assets, SFX) into a structured
package with a shareable beat-by-beat view and ZIP download.

Part of the Trash Panda Content Pipeline (MVP 6).
"""

import logging
import json
import io
import zipfile
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HandoffBeat:
    """A single beat in the handoff package."""
    beat_id: str
    beat_number: int
    beat_name: str
    script_text: str
    visual_notes: str
    character: str
    audio_url: Optional[str] = None
    audio_duration_ms: int = 0
    audio_storage_path: Optional[str] = None
    assets: List[Dict[str, Any]] = field(default_factory=list)
    sfx: List[Dict[str, Any]] = field(default_factory=list)
    timestamp_start: str = ""
    timestamp_end: str = ""


@dataclass
class HandoffPackage:
    """Complete handoff package for an editor."""
    handoff_id: UUID
    project_id: UUID
    title: str
    brand_name: str
    created_at: datetime
    beats: List[HandoffBeat]
    total_duration_ms: int = 0
    full_audio_url: Optional[str] = None
    full_audio_storage_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class EditorHandoffService:
    """
    Service for generating editor handoff packages.

    Collects script, audio, assets, and SFX into a structured package
    that editors can view beat-by-beat and download as a ZIP.
    """

    def __init__(
        self,
        supabase_client: Optional[Any] = None,
        audio_service: Optional[Any] = None,
        asset_service: Optional[Any] = None
    ):
        """
        Initialize the EditorHandoffService.

        Args:
            supabase_client: Supabase client for database operations
            audio_service: AudioProductionService for audio URLs
            asset_service: AssetManagementService for asset URLs
        """
        self.supabase = supabase_client
        self.audio_service = audio_service
        self.asset_service = asset_service

    # =========================================================================
    # PACKAGE GENERATION
    # =========================================================================

    async def generate_handoff(self, project_id: UUID) -> HandoffPackage:
        """
        Generate a complete handoff package for a project.

        Collects all artifacts and creates a structured package.

        Args:
            project_id: Content project UUID

        Returns:
            HandoffPackage with all beats and metadata

        Raises:
            ValueError: If project not found or not ready for handoff
        """
        if not self.supabase:
            raise ValueError("Supabase not configured")

        # Load project
        project = await self._load_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Load brand name
        brand_name = await self._get_brand_name(UUID(project["brand_id"]))

        # Load approved script
        script_data = await self._load_approved_script(project_id)
        if not script_data:
            raise ValueError("No approved script found. Approve script first.")

        # Load audio session
        audio_session = None
        audio_takes = {}
        if project.get("audio_session_id"):
            audio_session, audio_takes = await self._load_audio_session(
                project["audio_session_id"]
            )

        # Load assets
        assets_by_beat = await self._load_assets_by_beat(project_id, script_data)

        # Build handoff beats
        beats = []
        total_duration = 0

        for beat_data in script_data.get("beats", []):
            beat_id = beat_data.get("beat_id", f"beat_{len(beats)+1}")

            # Get audio for this beat
            audio_url = None
            audio_storage_path = None
            audio_duration_ms = 0
            take = audio_takes.get(beat_id)
            if take:
                audio_storage_path = take.get("audio_path")
                audio_duration_ms = take.get("audio_duration_ms", 0)
                if audio_storage_path and self.audio_service:
                    try:
                        audio_url = await self.audio_service.get_audio_url(
                            audio_storage_path
                        )
                    except Exception as e:
                        logger.warning(f"Failed to get audio URL for {beat_id}: {e}")

            total_duration += audio_duration_ms

            # Get assets for this beat
            beat_assets = assets_by_beat.get(beat_id, [])

            # Separate SFX from visual assets
            visual_assets = [a for a in beat_assets if a.get("asset_type") != "effect"]
            sfx_assets = [a for a in beat_assets if a.get("asset_type") == "effect"]

            handoff_beat = HandoffBeat(
                beat_id=beat_id,
                beat_number=beat_data.get("beat_number", len(beats) + 1),
                beat_name=beat_data.get("beat_name", f"Beat {len(beats) + 1}"),
                script_text=beat_data.get("script", ""),
                visual_notes=beat_data.get("visual_notes", ""),
                character=beat_data.get("character", "every-coon"),
                audio_url=audio_url,
                audio_storage_path=audio_storage_path,
                audio_duration_ms=audio_duration_ms,
                assets=visual_assets,
                sfx=sfx_assets,
                timestamp_start=beat_data.get("timestamp_start", ""),
                timestamp_end=beat_data.get("timestamp_end", "")
            )
            beats.append(handoff_beat)

        # Create handoff package
        handoff_id = uuid4()

        package = HandoffPackage(
            handoff_id=handoff_id,
            project_id=project_id,
            title=project.get("topic_title", "Untitled"),
            brand_name=brand_name,
            created_at=datetime.utcnow(),
            beats=beats,
            total_duration_ms=total_duration,
            metadata={
                "script_version": script_data.get("version_number", 1),
                "beat_count": len(beats),
                "has_audio": bool(audio_session),
                "workflow_state": project.get("workflow_state")
            }
        )

        # Save handoff record to database
        await self._save_handoff(package)

        logger.info(f"Generated handoff package {handoff_id} for project {project_id}")
        return package

    async def get_handoff(self, handoff_id: UUID) -> Optional[HandoffPackage]:
        """
        Load an existing handoff package.

        Args:
            handoff_id: Handoff UUID

        Returns:
            HandoffPackage or None if not found
        """
        if not self.supabase:
            return None

        try:
            result = self.supabase.table("editor_handoffs").select("*").eq(
                "id", str(handoff_id)
            ).execute()

            if not result.data:
                return None

            row = result.data[0]
            return await self._deserialize_handoff(row)

        except Exception as e:
            logger.error(f"Failed to load handoff: {e}")
            return None

    async def get_project_handoffs(self, project_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all handoffs for a project.

        Args:
            project_id: Content project UUID

        Returns:
            List of handoff summary dictionaries
        """
        if not self.supabase:
            return []

        try:
            result = self.supabase.table("editor_handoffs").select(
                "id, created_at, metadata"
            ).eq("project_id", str(project_id)).order(
                "created_at", desc=True
            ).execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to list handoffs: {e}")
            return []

    # =========================================================================
    # ZIP GENERATION
    # =========================================================================

    async def generate_zip(self, handoff_id: UUID) -> bytes:
        """
        Generate a ZIP file containing all handoff assets.

        Package structure:
        /project-handoff/
        ├── script.json           # Full script with beats
        ├── script.txt            # Plain text version
        ├── audio/
        │   └── beats/            # Individual beat audio
        ├── assets/
        │   ├── characters/
        │   ├── props/
        │   └── backgrounds/
        ├── sfx/
        └── metadata.json

        Args:
            handoff_id: Handoff UUID

        Returns:
            ZIP file bytes
        """
        package = await self.get_handoff(handoff_id)
        if not package:
            raise ValueError(f"Handoff {handoff_id} not found")

        # Create in-memory ZIP
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            prefix = f"{package.title.replace(' ', '-').lower()}-handoff"

            # Add metadata.json
            metadata = {
                "handoff_id": str(package.handoff_id),
                "project_id": str(package.project_id),
                "title": package.title,
                "brand": package.brand_name,
                "created_at": package.created_at.isoformat(),
                "total_duration_ms": package.total_duration_ms,
                "beat_count": len(package.beats),
                **package.metadata
            }
            zf.writestr(f"{prefix}/metadata.json", json.dumps(metadata, indent=2))

            # Add script.json (structured)
            script_json = {
                "title": package.title,
                "beats": [
                    {
                        "beat_id": b.beat_id,
                        "beat_number": b.beat_number,
                        "beat_name": b.beat_name,
                        "character": b.character,
                        "script": b.script_text,
                        "visual_notes": b.visual_notes,
                        "timestamp_start": b.timestamp_start,
                        "timestamp_end": b.timestamp_end,
                        "audio_duration_ms": b.audio_duration_ms
                    }
                    for b in package.beats
                ]
            }
            zf.writestr(f"{prefix}/script.json", json.dumps(script_json, indent=2))

            # Add script.txt (plain text for reading)
            script_txt = self._generate_plain_script(package)
            zf.writestr(f"{prefix}/script.txt", script_txt)

            # Add audio files
            for beat in package.beats:
                if beat.audio_storage_path and self.audio_service:
                    try:
                        audio_data = await self.audio_service.download_audio(
                            beat.audio_storage_path
                        )
                        filename = f"{beat.beat_number:02d}_{beat.beat_id}.mp3"
                        zf.writestr(f"{prefix}/audio/beats/{filename}", audio_data)
                    except Exception as e:
                        logger.warning(f"Failed to add audio for {beat.beat_id}: {e}")

            # Add asset files
            added_assets = set()  # Track to avoid duplicates
            for beat in package.beats:
                for asset in beat.assets:
                    asset_id = asset.get("id")
                    if asset_id in added_assets:
                        continue
                    added_assets.add(asset_id)

                    image_url = asset.get("image_url")
                    if image_url and self.asset_service:
                        try:
                            # Get asset file data
                            storage_path = self._extract_storage_path(image_url)
                            if storage_path:
                                asset_data = await self._download_file(storage_path)
                                asset_type = asset.get("asset_type", "props")
                                name = asset.get("name", asset_id)
                                ext = Path(image_url).suffix or ".png"
                                folder = f"{asset_type}s"  # characters, props, backgrounds
                                zf.writestr(
                                    f"{prefix}/assets/{folder}/{name}{ext}",
                                    asset_data
                                )
                        except Exception as e:
                            logger.warning(f"Failed to add asset {asset_id}: {e}")

            # Add SFX files
            added_sfx = set()
            for beat in package.beats:
                for sfx in beat.sfx:
                    sfx_id = sfx.get("id")
                    if sfx_id in added_sfx:
                        continue
                    added_sfx.add(sfx_id)

                    sfx_url = sfx.get("audio_url") or sfx.get("image_url")
                    if sfx_url:
                        try:
                            storage_path = self._extract_storage_path(sfx_url)
                            if storage_path:
                                sfx_data = await self._download_file(storage_path)
                                name = sfx.get("name", sfx_id)
                                ext = Path(sfx_url).suffix or ".mp3"
                                zf.writestr(f"{prefix}/sfx/{name}{ext}", sfx_data)
                        except Exception as e:
                            logger.warning(f"Failed to add SFX {sfx_id}: {e}")

        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    def _generate_plain_script(self, package: HandoffPackage) -> str:
        """Generate plain text script for easy reading."""
        lines = [
            f"# {package.title}",
            f"Brand: {package.brand_name}",
            f"Generated: {package.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"Total Duration: {package.total_duration_ms / 1000:.1f}s",
            "",
            "=" * 60,
            ""
        ]

        for beat in package.beats:
            lines.append(f"## Beat {beat.beat_number}: {beat.beat_name}")
            lines.append(f"Character: {beat.character}")
            if beat.timestamp_start:
                lines.append(f"Time: {beat.timestamp_start} - {beat.timestamp_end}")
            lines.append("")
            lines.append(beat.script_text)
            lines.append("")
            if beat.visual_notes:
                lines.append(f"[Visual: {beat.visual_notes}]")
                lines.append("")
            lines.append("-" * 40)
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # DATA LOADING HELPERS
    # =========================================================================

    async def _load_project(self, project_id: UUID) -> Optional[Dict[str, Any]]:
        """Load project from database."""
        try:
            result = self.supabase.table("content_projects").select("*").eq(
                "id", str(project_id)
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to load project: {e}")
            return None

    async def _get_brand_name(self, brand_id: UUID) -> str:
        """Get brand name from database."""
        try:
            result = self.supabase.table("brands").select("name").eq(
                "id", str(brand_id)
            ).execute()
            return result.data[0]["name"] if result.data else "Unknown Brand"
        except Exception:
            return "Unknown Brand"

    async def _load_approved_script(
        self,
        project_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Load the approved script for a project."""
        try:
            result = self.supabase.table("script_versions").select("*").eq(
                "project_id", str(project_id)
            ).eq("status", "approved").order(
                "version_number", desc=True
            ).limit(1).execute()

            if not result.data:
                return None

            row = result.data[0]
            script_content = row.get("script_content")

            if isinstance(script_content, str):
                script_content = json.loads(script_content)

            script_content["version_number"] = row.get("version_number", 1)
            return script_content

        except Exception as e:
            logger.error(f"Failed to load script: {e}")
            return None

    async def _load_audio_session(
        self,
        session_id: str
    ) -> Tuple[Optional[Dict], Dict[str, Dict]]:
        """
        Load audio session and selected takes.

        Returns:
            Tuple of (session_dict, takes_by_beat_id)
        """
        try:
            # Get session
            session_result = self.supabase.table(
                "audio_production_sessions"
            ).select("*").eq("id", session_id).execute()

            session = session_result.data[0] if session_result.data else None

            # Get selected takes
            takes_result = self.supabase.table("audio_takes").select("*").eq(
                "session_id", session_id
            ).eq("is_selected", True).execute()

            takes_by_beat = {}
            for take in (takes_result.data or []):
                takes_by_beat[take["beat_id"]] = take

            return session, takes_by_beat

        except Exception as e:
            logger.error(f"Failed to load audio session: {e}")
            return None, {}

    async def _load_assets_by_beat(
        self,
        project_id: UUID,
        script_data: Dict[str, Any]
    ) -> Dict[str, List[Dict]]:
        """
        Load project assets organized by beat reference.

        Args:
            project_id: Project UUID
            script_data: Script data with beats

        Returns:
            Dictionary mapping beat_id to list of asset dicts
        """
        try:
            # Get project asset requirements with linked assets
            result = self.supabase.table("project_asset_requirements").select(
                "*, comic_assets(*)"
            ).eq("project_id", str(project_id)).execute()

            requirements = result.data or []

            # Build mapping from beat_id to assets
            assets_by_beat = {}

            for req in requirements:
                # Parse script_reference (JSON array of beat IDs)
                refs = req.get("script_reference", "[]")
                if isinstance(refs, str):
                    try:
                        refs = json.loads(refs)
                    except:
                        refs = []

                # Get asset details (from linked comic_assets or requirement itself)
                linked_asset = req.get("comic_assets")
                asset_info = {
                    "id": req.get("asset_id") or req.get("id"),
                    "name": req.get("asset_name"),
                    "asset_type": req.get("asset_type"),
                    "description": req.get("asset_description"),
                    "status": req.get("status"),
                    "image_url": None
                }

                # Get image URL from linked asset or generated image
                if linked_asset:
                    asset_info["image_url"] = linked_asset.get("image_url")
                elif req.get("generated_image_url"):
                    asset_info["image_url"] = req.get("generated_image_url")

                # Add to each referenced beat
                for beat_id in refs:
                    if beat_id not in assets_by_beat:
                        assets_by_beat[beat_id] = []
                    assets_by_beat[beat_id].append(asset_info)

            return assets_by_beat

        except Exception as e:
            logger.error(f"Failed to load assets: {e}")
            return {}

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _save_handoff(self, package: HandoffPackage) -> None:
        """Save handoff record to database."""
        try:
            # Serialize beats
            beats_json = [
                {
                    "beat_id": b.beat_id,
                    "beat_number": b.beat_number,
                    "beat_name": b.beat_name,
                    "script_text": b.script_text,
                    "visual_notes": b.visual_notes,
                    "character": b.character,
                    "audio_url": b.audio_url,
                    "audio_storage_path": b.audio_storage_path,
                    "audio_duration_ms": b.audio_duration_ms,
                    "assets": b.assets,
                    "sfx": b.sfx,
                    "timestamp_start": b.timestamp_start,
                    "timestamp_end": b.timestamp_end
                }
                for b in package.beats
            ]

            record = {
                "id": str(package.handoff_id),
                "project_id": str(package.project_id),
                "title": package.title,
                "brand_name": package.brand_name,
                "beats_json": beats_json,
                "total_duration_ms": package.total_duration_ms,
                "metadata": package.metadata,
                "created_at": package.created_at.isoformat()
            }

            self.supabase.table("editor_handoffs").insert(record).execute()

        except Exception as e:
            logger.error(f"Failed to save handoff: {e}")
            # Don't raise - handoff can still be used even if not saved

    async def _deserialize_handoff(self, row: Dict[str, Any]) -> HandoffPackage:
        """Deserialize handoff from database row."""
        beats = []
        for b in (row.get("beats_json") or []):
            # Refresh audio URLs (they expire)
            audio_url = None
            if b.get("audio_storage_path") and self.audio_service:
                try:
                    audio_url = await self.audio_service.get_audio_url(
                        b["audio_storage_path"]
                    )
                except:
                    pass

            beat = HandoffBeat(
                beat_id=b["beat_id"],
                beat_number=b["beat_number"],
                beat_name=b["beat_name"],
                script_text=b["script_text"],
                visual_notes=b["visual_notes"],
                character=b["character"],
                audio_url=audio_url,
                audio_storage_path=b.get("audio_storage_path"),
                audio_duration_ms=b.get("audio_duration_ms", 0),
                assets=b.get("assets", []),
                sfx=b.get("sfx", []),
                timestamp_start=b.get("timestamp_start", ""),
                timestamp_end=b.get("timestamp_end", "")
            )
            beats.append(beat)

        return HandoffPackage(
            handoff_id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            title=row["title"],
            brand_name=row["brand_name"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            beats=beats,
            total_duration_ms=row.get("total_duration_ms", 0),
            metadata=row.get("metadata", {})
        )

    # =========================================================================
    # URL / FILE HELPERS
    # =========================================================================

    def _extract_storage_path(self, url: str) -> Optional[str]:
        """Extract storage path from a signed URL or storage path."""
        if not url:
            return None

        # If it's already a storage path (bucket/path format)
        if "/" in url and not url.startswith("http"):
            return url

        # Try to extract from signed URL
        # Format: https://xxx.supabase.co/storage/v1/object/sign/bucket/path?token=...
        if "supabase" in url and "/storage/" in url:
            try:
                # Find the bucket/path part after /sign/ or /public/
                for marker in ["/sign/", "/public/"]:
                    if marker in url:
                        path_part = url.split(marker)[1]
                        # Remove query string
                        path_part = path_part.split("?")[0]
                        return path_part
            except:
                pass

        return None

    async def _download_file(self, storage_path: str) -> bytes:
        """Download a file from Supabase storage."""
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        data = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        return data

    # =========================================================================
    # URL GENERATION
    # =========================================================================

    def get_handoff_url(self, handoff_id: UUID, base_url: str = "") -> str:
        """
        Generate a shareable URL for the handoff page.

        Args:
            handoff_id: Handoff UUID
            base_url: Base URL of the application (optional)

        Returns:
            Shareable URL string
        """
        # The handoff page will be at /Handoff?id=<handoff_id>
        if base_url:
            return f"{base_url}/Handoff?id={handoff_id}"
        return f"?id={handoff_id}"
