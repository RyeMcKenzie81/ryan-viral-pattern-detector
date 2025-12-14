"""
Asset Management Service - Business logic for visual asset extraction and management.

Uses Gemini AI to:
1. Extract asset requirements from script visual_notes
2. Match against existing asset library
3. Track generation status

Part of the Trash Panda Content Pipeline (MVP 4).
"""

import logging
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4
from datetime import datetime

logger = logging.getLogger(__name__)

# Storage bucket for comic assets
COMIC_ASSETS_BUCKET = "comic-assets"


class AssetManagementService:
    """
    Service for managing visual assets in the content pipeline.

    Uses Gemini AI to intelligently extract asset requirements from
    script visual_notes, then matches against the existing asset library.
    """

    # Gemini prompt for extracting assets from visual_notes
    ASSET_EXTRACTION_PROMPT = """Analyze these visual notes from a video script and identify ALL visual assets needed.

For each asset, classify it as:
- character: Named characters (Every-Coon, Fed, Boomer, Whale, Wojak, Chad, etc.)
- prop: Objects, items, tools (money, printer, charts, dumpster, etc.)
- background: Scene backgrounds, environments (street, office, bank, etc.)
- effect: ONLY custom visual effects that need to be drawn (NOT standard editor effects)

CRITICAL RULES:
1. EVERY BEAT NEEDS A BACKGROUND - If a beat doesn't explicitly mention a location, infer one from context (e.g., "generic-interior", "abstract-background")
2. EVERY CHARACTER mentioned in a beat MUST be extracted with that beat_id in script_references
3. Deduplicate - if an asset appears multiple times, list it once with ALL beat references where it appears
4. Use lowercase-hyphenated names (e.g., "every-coon", "money-printer", "wall-street")
5. DO NOT include standard editor effects (sparkles, glows, shakes, zooms, fades, transitions, tears, motion blur, lens flare, explosions, fire)

CHARACTER EXTRACTION:
- Look for character names: Every-Coon, Fed, Boomer, Whale, Wojak, Chad
- If a beat says "Chad appears" or "Chad walks in", Chad MUST be in script_references for that beat
- Extract the main narrator character for beats with dialogue

BACKGROUND EXTRACTION:
- Extract explicit locations (office, street, bank, etc.)
- If no location mentioned, create a sensible default (e.g., "generic-background", "simple-interior")
- Each beat_id should appear in at least one background's script_references

<visual_notes>
{visual_notes}
</visual_notes>

Return valid JSON:
{{
    "assets": [
        {{
            "name": "asset-name-lowercase",
            "type": "character|prop|background|effect",
            "description": "Visual description for asset generation",
            "script_references": ["beat_id_1", "beat_id_2"],
            "suggested_prompt": "Flat vector cartoon, [description], thick black outlines, Cyanide and Happiness style"
        }}
    ],
    "extraction_notes": "Any notes about ambiguous or unclear asset references"
}}"""

    # Known character names for better matching
    KNOWN_CHARACTERS = {
        "every-coon", "everycoon", "every coon",
        "fed", "the fed", "federal reserve",
        "boomer", "the boomer",
        "whale", "the whale",
        "wojak", "the wojak",
        "chad", "the chad"
    }

    # Asset type priorities for matching
    ASSET_TYPE_PRIORITY = {
        "character": 1,
        "prop": 2,
        "background": 3,
        "effect": 4
    }

    def __init__(
        self,
        supabase_client: Optional[Any] = None,
        gemini_service: Optional[Any] = None
    ):
        """
        Initialize the AssetManagementService.

        Args:
            supabase_client: Supabase client for database operations
            gemini_service: GeminiService for AI-powered extraction
        """
        self.supabase = supabase_client
        self.gemini = gemini_service

    def _ensure_gemini(self) -> None:
        """Raise error if Gemini service not configured."""
        if not self.gemini:
            raise ValueError(
                "GeminiService not configured. Cannot extract assets without AI."
            )

    # =========================================================================
    # ASSET EXTRACTION
    # =========================================================================

    async def extract_requirements(
        self,
        script_version_id: UUID,
        script_data: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Parse visual_notes from a script to identify all required assets.

        Uses Gemini AI to intelligently extract and categorize assets,
        handling variations in naming and deduplication.

        Args:
            script_version_id: Script version UUID to extract from
            script_data: Optional pre-loaded script data (avoids DB lookup)

        Returns:
            List of asset requirement dictionaries with:
                - name: Normalized asset name
                - type: character|prop|background|effect
                - description: Visual description
                - script_references: List of beat IDs
                - suggested_prompt: Generation prompt suggestion
        """
        self._ensure_gemini()

        # Load script if not provided
        if not script_data:
            script_data = await self._load_script(script_version_id)
            if not script_data:
                raise ValueError(f"Script version {script_version_id} not found")

        # Collect all visual_notes from beats
        visual_notes_parts = []
        beats = script_data.get("beats", [])

        for beat in beats:
            beat_id = beat.get("beat_id", "unknown")
            visual_notes = beat.get("visual_notes", "")
            if visual_notes:
                visual_notes_parts.append(f"[{beat_id}]: {visual_notes}")

        if not visual_notes_parts:
            logger.warning(f"No visual_notes found in script {script_version_id}")
            return []

        combined_notes = "\n\n".join(visual_notes_parts)
        logger.info(f"Extracting assets from {len(visual_notes_parts)} beats")

        # Call Gemini for intelligent extraction
        prompt = self.ASSET_EXTRACTION_PROMPT.format(visual_notes=combined_notes)

        try:
            response = await self.gemini.analyze_text(
                text="",  # Text is embedded in prompt
                prompt=prompt,
                max_retries=3
            )

            # Parse JSON response
            assets = self._parse_extraction_response(response)
            logger.info(f"Extracted {len(assets)} unique assets")

            return assets

        except Exception as e:
            logger.error(f"Asset extraction failed: {e}")
            raise

    def _parse_extraction_response(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse Gemini's extraction response into structured asset list.

        Args:
            response: Raw Gemini response text

        Returns:
            List of asset dictionaries
        """
        response = response.strip()

        # Remove markdown code blocks if present
        if response.startswith("```"):
            lines = response.split("\n")
            start_idx = 1 if lines[0].startswith("```") else 0
            end_idx = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            response = "\n".join(lines[start_idx:end_idx])

        try:
            data = json.loads(response)
            assets = data.get("assets", [])

            # Log extraction notes if present
            notes = data.get("extraction_notes")
            if notes:
                logger.info(f"Extraction notes: {notes}")

            # Normalize and validate each asset
            normalized = []
            for asset in assets:
                norm = self._normalize_asset(asset)
                if norm:
                    normalized.append(norm)

            return normalized

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction response: {e}")
            logger.debug(f"Raw response: {response[:500]}")
            raise ValueError(f"Failed to parse asset extraction: {e}")

    def _normalize_asset(self, asset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize and validate a single asset entry.

        Args:
            asset: Raw asset dictionary from extraction

        Returns:
            Normalized asset dictionary or None if invalid
        """
        name = asset.get("name", "").lower().strip()
        asset_type = asset.get("type", "").lower().strip()

        if not name or not asset_type:
            return None

        # Validate asset type
        if asset_type not in self.ASSET_TYPE_PRIORITY:
            logger.warning(f"Unknown asset type '{asset_type}' for {name}, defaulting to prop")
            asset_type = "prop"

        # Normalize name (lowercase, hyphens)
        name = name.replace(" ", "-").replace("_", "-")

        # Handle known character aliases
        for known in self.KNOWN_CHARACTERS:
            if known in name or name in known:
                if "every" in name.lower() or "coon" in name.lower():
                    name = "every-coon"
                    break

        return {
            "name": name,
            "type": asset_type,
            "description": asset.get("description", ""),
            "script_references": asset.get("script_references", []),
            "suggested_prompt": asset.get("suggested_prompt", "")
        }

    # =========================================================================
    # ASSET MATCHING
    # =========================================================================

    def match_existing_assets(
        self,
        requirements: List[Dict[str, Any]],
        brand_id: UUID
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Match asset requirements against existing library.

        Args:
            requirements: List of asset requirements from extraction
            brand_id: Brand UUID to search library

        Returns:
            Tuple of (matched_assets, unmatched_assets)
            - matched_assets: Requirements with asset_id populated
            - unmatched_assets: Requirements that need generation
        """
        if not self.supabase:
            logger.warning("Supabase not configured - no matching possible")
            return [], requirements

        # Fetch existing assets for this brand
        try:
            result = self.supabase.table("comic_assets").select(
                "id, name, asset_type, description, tags, image_url, is_core_asset"
            ).eq("brand_id", str(brand_id)).execute()

            existing_assets = result.data or []
            logger.info(f"Found {len(existing_assets)} existing assets for brand")

        except Exception as e:
            logger.error(f"Failed to fetch existing assets: {e}")
            return [], requirements

        # Build lookup for fast matching
        asset_lookup = {}
        for asset in existing_assets:
            # Index by normalized name
            norm_name = asset["name"].lower().replace(" ", "-").replace("_", "-")
            asset_lookup[norm_name] = asset

            # Also index by tags
            for tag in (asset.get("tags") or []):
                tag_norm = tag.lower().replace(" ", "-")
                if tag_norm not in asset_lookup:
                    asset_lookup[tag_norm] = asset

        # Match requirements
        matched = []
        unmatched = []

        for req in requirements:
            req_name = req["name"].lower()
            match = asset_lookup.get(req_name)

            # Try partial match for characters
            if not match and req["type"] == "character":
                for key, asset in asset_lookup.items():
                    if req_name in key or key in req_name:
                        if asset["asset_type"] == "character":
                            match = asset
                            break

            if match:
                matched_req = {
                    **req,
                    "asset_id": match["id"],
                    "existing_asset": match,
                    "status": "matched"
                }
                matched.append(matched_req)
                logger.debug(f"Matched '{req['name']}' → '{match['name']}'")
            else:
                unmatched_req = {
                    **req,
                    "asset_id": None,
                    "status": "needed"
                }
                unmatched.append(unmatched_req)
                logger.debug(f"No match for '{req['name']}'")

        logger.info(f"Asset matching: {len(matched)} matched, {len(unmatched)} needed")
        return matched, unmatched

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    async def save_requirements(
        self,
        project_id: UUID,
        requirements: List[Dict[str, Any]]
    ) -> List[UUID]:
        """
        Save asset requirements to project_asset_requirements table.

        Args:
            project_id: Content project UUID
            requirements: List of requirements (matched and unmatched)

        Returns:
            List of created requirement UUIDs
        """
        if not self.supabase:
            logger.warning("Supabase not configured - requirements not saved")
            return []

        created_ids = []

        try:
            for req in requirements:
                record = {
                    "project_id": str(project_id),
                    "asset_id": str(req["asset_id"]) if req.get("asset_id") else None,
                    "asset_name": req["name"],
                    "asset_type": req["type"],
                    "asset_description": req.get("description", ""),
                    "suggested_prompt": req.get("suggested_prompt", ""),
                    "script_reference": json.dumps(req.get("script_references", [])),
                    "status": req.get("status", "needed")
                }

                result = self.supabase.table("project_asset_requirements").insert(
                    record
                ).execute()

                if result.data:
                    created_ids.append(UUID(result.data[0]["id"]))

            logger.info(f"Saved {len(created_ids)} asset requirements for project {project_id}")
            return created_ids

        except Exception as e:
            logger.error(f"Failed to save requirements: {e}")
            raise

    async def get_requirements(
        self,
        project_id: UUID,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch asset requirements for a project.

        Args:
            project_id: Content project UUID
            status_filter: Optional filter by status (needed, matched, generating, etc.)

        Returns:
            List of requirement dictionaries
        """
        if not self.supabase:
            return []

        try:
            query = self.supabase.table("project_asset_requirements").select(
                "*, comic_assets(*)"
            ).eq("project_id", str(project_id))

            if status_filter:
                query = query.eq("status", status_filter)

            result = query.order("asset_type").execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to fetch requirements: {e}")
            return []

    async def update_requirement_status(
        self,
        requirement_id: UUID,
        status: str,
        generated_image_url: Optional[str] = None
    ) -> None:
        """
        Update the status of an asset requirement.

        Args:
            requirement_id: Requirement UUID
            status: New status (needed, matched, generating, generated, approved, rejected)
            generated_image_url: Optional URL of generated image
        """
        if not self.supabase:
            return

        try:
            update_data = {"status": status}
            if generated_image_url:
                update_data["generated_image_url"] = generated_image_url

            self.supabase.table("project_asset_requirements").update(
                update_data
            ).eq("id", str(requirement_id)).execute()

            logger.debug(f"Updated requirement {requirement_id} status to '{status}'")

        except Exception as e:
            logger.error(f"Failed to update requirement status: {e}")

    # =========================================================================
    # ASSET LIBRARY OPERATIONS
    # =========================================================================

    async def get_asset_library(
        self,
        brand_id: UUID,
        asset_type: Optional[str] = None,
        core_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get assets from the library.

        Args:
            brand_id: Brand UUID
            asset_type: Optional filter by type (character, prop, background, effect)
            core_only: If True, only return core/main assets

        Returns:
            List of asset dictionaries
        """
        if not self.supabase:
            return []

        try:
            query = self.supabase.table("comic_assets").select("*").eq(
                "brand_id", str(brand_id)
            )

            if asset_type:
                query = query.eq("asset_type", asset_type)

            if core_only:
                query = query.eq("is_core_asset", True)

            result = query.order("asset_type").order("name").execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to fetch asset library: {e}")
            return []

    async def upload_asset(
        self,
        brand_id: UUID,
        name: str,
        asset_type: str,
        description: str = "",
        tags: List[str] = None,
        image_url: str = None,
        thumbnail_url: str = None,
        prompt_template: str = None,
        is_core_asset: bool = False
    ) -> UUID:
        """
        Add a new asset to the library.

        Args:
            brand_id: Brand UUID
            name: Asset name (will be normalized)
            asset_type: character|prop|background|effect
            description: Visual description
            tags: Searchable tags
            image_url: URL to asset image
            thumbnail_url: URL to thumbnail
            prompt_template: Template for generating variations
            is_core_asset: Whether this is a core/main asset

        Returns:
            Created asset UUID
        """
        if not self.supabase:
            logger.warning("Supabase not configured - asset not uploaded")
            return uuid4()

        # Normalize name
        norm_name = name.lower().replace(" ", "-").replace("_", "-")

        try:
            record = {
                "brand_id": str(brand_id),
                "name": norm_name,
                "asset_type": asset_type,
                "description": description,
                "tags": tags or [],
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
                "prompt_template": prompt_template,
                "is_core_asset": is_core_asset,
                "style_suffix": "flat vector cartoon art, minimal design, thick black outlines, simple geometric shapes, style of Cyanide and Happiness, 2D, high contrast"
            }

            result = self.supabase.table("comic_assets").insert(record).execute()

            if result.data:
                asset_id = UUID(result.data[0]["id"])
                logger.info(f"Created asset '{norm_name}' ({asset_type}) id={asset_id}")
                return asset_id

            return uuid4()

        except Exception as e:
            logger.error(f"Failed to upload asset: {e}")
            raise

    async def update_asset(
        self,
        asset_id: UUID,
        updates: Dict[str, Any]
    ) -> None:
        """
        Update an existing asset.

        Args:
            asset_id: Asset UUID
            updates: Fields to update
        """
        if not self.supabase:
            return

        try:
            updates["updated_at"] = datetime.utcnow().isoformat()

            self.supabase.table("comic_assets").update(
                updates
            ).eq("id", str(asset_id)).execute()

            logger.debug(f"Updated asset {asset_id}")

        except Exception as e:
            logger.error(f"Failed to update asset: {e}")

    async def delete_asset(self, asset_id: UUID) -> bool:
        """
        Delete an asset from the library.

        Args:
            asset_id: Asset UUID

        Returns:
            True if deleted, False otherwise
        """
        if not self.supabase:
            return False

        try:
            self.supabase.table("comic_assets").delete().eq(
                "id", str(asset_id)
            ).execute()

            logger.info(f"Deleted asset {asset_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete asset: {e}")
            return False

    # =========================================================================
    # FILE UPLOAD METHODS
    # =========================================================================

    async def upload_asset_file(
        self,
        brand_id: UUID,
        file_data: bytes,
        filename: str,
        content_type: str = "image/png"
    ) -> str:
        """
        Upload an asset image file to Supabase Storage.

        Args:
            brand_id: Brand UUID (used for storage path organization)
            file_data: Raw file bytes
            filename: Original filename
            content_type: MIME type (default: image/png)

        Returns:
            Storage path (e.g., "comic-assets/brand-uuid/filename.png")
        """
        if not self.supabase:
            raise ValueError("Supabase not configured - cannot upload file")

        # Normalize filename
        safe_filename = filename.lower().replace(" ", "-").replace("_", "-")

        # Build storage path
        storage_path = f"{brand_id}/{safe_filename}"

        try:
            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(COMIC_ASSETS_BUCKET).upload(
                    storage_path,
                    file_data,
                    {"content-type": content_type}
                )
            )

            logger.info(f"Uploaded asset file: {COMIC_ASSETS_BUCKET}/{storage_path}")
            return f"{COMIC_ASSETS_BUCKET}/{storage_path}"

        except Exception as e:
            logger.error(f"Failed to upload asset file: {e}")
            raise

    async def get_asset_url(self, storage_path: str) -> str:
        """
        Get a permanent public URL for an asset file.

        Args:
            storage_path: Storage path (e.g., "comic-assets/brand-uuid/file.png")

        Returns:
            Public URL for the asset (never expires)
        """
        if not self.supabase:
            return ""

        try:
            # Parse bucket and path
            parts = storage_path.split("/", 1)
            bucket = parts[0]
            path = parts[1] if len(parts) > 1 else storage_path

            # Use public URL (never expires) instead of signed URL
            public_url = self.supabase.storage.from_(bucket).get_public_url(path)

            # Remove trailing ? if present
            return public_url.rstrip("?") if public_url else ""

        except Exception as e:
            logger.error(f"Failed to get asset URL: {e}")
            return ""

    async def upload_asset_with_file(
        self,
        brand_id: UUID,
        name: str,
        asset_type: str,
        file_data: bytes,
        filename: str,
        content_type: str = "image/png",
        description: str = "",
        tags: List[str] = None,
        is_core_asset: bool = False
    ) -> UUID:
        """
        Upload an asset with its image file in one operation.

        Combines file upload to storage with database record creation.

        Args:
            brand_id: Brand UUID
            name: Asset name
            asset_type: character|prop|background|effect
            file_data: Raw image bytes
            filename: Original filename
            content_type: MIME type
            description: Visual description
            tags: Searchable tags
            is_core_asset: Whether this is a core/main asset

        Returns:
            Created asset UUID
        """
        # Upload file first
        storage_path = await self.upload_asset_file(
            brand_id=brand_id,
            file_data=file_data,
            filename=filename,
            content_type=content_type
        )

        # Get public URL
        image_url = await self.get_asset_url(storage_path)

        # Create database record
        asset_id = await self.upload_asset(
            brand_id=brand_id,
            name=name,
            asset_type=asset_type,
            description=description,
            tags=tags,
            image_url=image_url,
            is_core_asset=is_core_asset
        )

        return asset_id

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _load_script(self, script_version_id: UUID) -> Optional[Dict[str, Any]]:
        """Load script data from database."""
        if not self.supabase:
            return None

        try:
            result = self.supabase.table("script_versions").select(
                "script_content, storyboard_json"
            ).eq("id", str(script_version_id)).execute()

            if not result.data:
                return None

            row = result.data[0]

            # Parse script_content if it's a JSON string
            script_content = row.get("script_content")
            if isinstance(script_content, str):
                try:
                    script_content = json.loads(script_content)
                except json.JSONDecodeError:
                    script_content = {"title": "Unknown", "beats": []}

            # Merge with storyboard_json for complete data
            storyboard = row.get("storyboard_json") or {}
            if storyboard.get("beats") and not script_content.get("beats"):
                script_content["beats"] = storyboard["beats"]

            return script_content

        except Exception as e:
            logger.error(f"Failed to load script: {e}")
            return None

    async def clear_requirements(self, project_id: UUID) -> int:
        """
        Clear all asset requirements for a project (for re-extraction).

        Args:
            project_id: Content project UUID

        Returns:
            Number of deleted requirements
        """
        if not self.supabase:
            return 0

        try:
            # Count before delete
            count_result = self.supabase.table("project_asset_requirements").select(
                "id", count="exact"
            ).eq("project_id", str(project_id)).execute()

            deleted_count = count_result.count or 0

            # Delete
            self.supabase.table("project_asset_requirements").delete().eq(
                "project_id", str(project_id)
            ).execute()

            logger.info(f"Cleared {deleted_count} asset requirements for project {project_id}")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to clear requirements: {e}")
            return 0

    def get_asset_summary(
        self,
        requirements: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate a summary of asset requirements.

        Args:
            requirements: List of requirements

        Returns:
            Summary dictionary with counts by type and status
        """
        summary = {
            "total": len(requirements),
            "by_type": {
                "character": 0,
                "prop": 0,
                "background": 0,
                "effect": 0
            },
            "by_status": {
                "matched": 0,
                "needed": 0,
                "generating": 0,
                "generated": 0,
                "approved": 0,
                "rejected": 0
            }
        }

        for req in requirements:
            asset_type = req.get("asset_type", req.get("type", "prop"))
            status = req.get("status", "needed")

            if asset_type in summary["by_type"]:
                summary["by_type"][asset_type] += 1

            if status in summary["by_status"]:
                summary["by_status"][status] += 1

        return summary
