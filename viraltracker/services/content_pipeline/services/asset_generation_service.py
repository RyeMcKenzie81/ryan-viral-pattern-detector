"""
Asset Generation Service - AI-powered asset generation for the content pipeline.

Uses:
- Gemini 3 Pro Image Preview for generating visual assets
- ElevenLabs Sound Effects API for generating SFX

Part of the Trash Panda Content Pipeline (MVP 5).
"""

import logging
import asyncio
import base64
import json
import httpx
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

logger = logging.getLogger(__name__)

# Default style suffix for Trash Panda assets
DEFAULT_STYLE_SUFFIX = (
    "flat vector cartoon art, minimal design, thick black outlines, "
    "simple geometric shapes, style of Cyanide and Happiness, 2D, high contrast, "
    "clean white or transparent background"
)

# ElevenLabs Sound Effects API endpoint
ELEVENLABS_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"


class AssetGenerationService:
    """
    Service for generating visual and audio assets using AI.

    Uses Gemini for image generation and ElevenLabs for SFX.
    Integrates with AssetManagementService for saving generated assets.
    """

    def __init__(
        self,
        supabase_client: Optional[Any] = None,
        gemini_service: Optional[Any] = None,
        elevenlabs_api_key: Optional[str] = None
    ):
        """
        Initialize the AssetGenerationService.

        Args:
            supabase_client: Supabase client for database operations
            gemini_service: GeminiService for image generation
            elevenlabs_api_key: ElevenLabs API key for SFX generation
        """
        self.supabase = supabase_client
        self.gemini = gemini_service
        self.elevenlabs_api_key = elevenlabs_api_key

    def _ensure_gemini(self) -> None:
        """Raise error if Gemini service not configured."""
        if not self.gemini:
            raise ValueError(
                "GeminiService not configured. Cannot generate images without AI."
            )

    def _ensure_elevenlabs(self) -> None:
        """Raise error if ElevenLabs not configured."""
        if not self.elevenlabs_api_key:
            raise ValueError(
                "ElevenLabs API key not configured. Cannot generate SFX."
            )

    # =========================================================================
    # IMAGE GENERATION
    # =========================================================================

    async def generate_asset_image(
        self,
        asset_name: str,
        asset_type: str,
        description: str,
        style_suffix: str = None,
        reference_images: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a single asset image using Gemini.

        Args:
            asset_name: Name of the asset (for logging)
            asset_type: character|prop|background|effect
            description: Visual description for generation
            style_suffix: Style instructions (default: Trash Panda style)
            reference_images: Optional base64-encoded reference images

        Returns:
            Dict with:
                - image_base64: Generated image as base64
                - generation_time_ms: Time taken
                - prompt_used: The prompt that was used
        """
        self._ensure_gemini()

        # Build prompt
        style = style_suffix or DEFAULT_STYLE_SUFFIX
        prompt = self._build_image_prompt(asset_name, asset_type, description, style)

        logger.info(f"Generating image for '{asset_name}' ({asset_type})")

        try:
            # Use Gemini's generate_image method
            result = await self.gemini.generate_image(
                prompt=prompt,
                reference_images=reference_images,
                max_retries=3,
                return_metadata=True
            )

            return {
                "image_base64": result["image_base64"],
                "generation_time_ms": result["generation_time_ms"],
                "prompt_used": prompt,
                "model_used": result.get("model_used", "gemini-3-pro-image-preview")
            }

        except Exception as e:
            logger.error(f"Failed to generate image for '{asset_name}': {e}")
            raise

    def _build_image_prompt(
        self,
        asset_name: str,
        asset_type: str,
        description: str,
        style_suffix: str
    ) -> str:
        """
        Build an optimized prompt for asset generation.

        Args:
            asset_name: Asset name
            asset_type: Asset type
            description: Visual description
            style_suffix: Style instructions

        Returns:
            Formatted prompt string
        """
        # Type-specific prefixes
        type_prefixes = {
            "character": "A cartoon character: ",
            "prop": "A cartoon object/prop: ",
            "background": "A cartoon scene background: ",
            "effect": "A visual effect overlay: "
        }

        prefix = type_prefixes.get(asset_type, "")

        # Build prompt
        prompt = f"{prefix}{description}. {style_suffix}"

        # Add specific instructions based on type
        if asset_type == "character":
            prompt += " Full body visible, centered composition, expressive pose."
        elif asset_type == "prop":
            prompt += " Single object, centered, clean isolation."
        elif asset_type == "background":
            prompt += " Wide scene, no characters, suitable for layering."
        elif asset_type == "effect":
            prompt += " Transparent background, suitable for overlay."

        return prompt

    async def generate_batch(
        self,
        requirements: List[Dict[str, Any]],
        brand_id: UUID,
        project_id: UUID,
        delay_between: float = 2.0
    ) -> Dict[str, Any]:
        """
        Generate multiple assets in batch.

        Args:
            requirements: List of asset requirements to generate
            brand_id: Brand UUID for saving assets
            project_id: Project UUID for updating requirements
            delay_between: Seconds to wait between generations (rate limiting)

        Returns:
            Dict with:
                - successful: List of successfully generated assets
                - failed: List of failed generations with errors
                - total_time_ms: Total time for batch
        """
        self._ensure_gemini()

        import time
        start_time = time.time()

        successful = []
        failed = []

        for idx, req in enumerate(requirements):
            req_id = req.get("id")
            asset_name = req.get("asset_name", req.get("name", "unknown"))
            asset_type = req.get("asset_type", req.get("type", "prop"))
            description = req.get("asset_description", req.get("description", ""))
            suggested_prompt = req.get("suggested_prompt", "")

            # Use suggested_prompt if available, otherwise use description
            gen_description = suggested_prompt if suggested_prompt else description

            if not gen_description:
                logger.warning(f"Skipping '{asset_name}' - no description")
                failed.append({
                    "requirement_id": req_id,
                    "asset_name": asset_name,
                    "error": "No description provided"
                })
                continue

            try:
                logger.info(f"[{idx + 1}/{len(requirements)}] Generating '{asset_name}'...")

                # Update status to 'generating'
                if req_id and self.supabase:
                    self.supabase.table("project_asset_requirements").update(
                        {"status": "generating"}
                    ).eq("id", str(req_id)).execute()

                # Generate image
                result = await self.generate_asset_image(
                    asset_name=asset_name,
                    asset_type=asset_type,
                    description=gen_description
                )

                # Save to storage
                image_url = await self._save_generated_image(
                    brand_id=brand_id,
                    asset_name=asset_name,
                    image_base64=result["image_base64"]
                )

                # Update requirement with generated image
                if req_id and self.supabase:
                    self.supabase.table("project_asset_requirements").update({
                        "status": "generated",
                        "generated_image_url": image_url
                    }).eq("id", str(req_id)).execute()

                successful.append({
                    "requirement_id": req_id,
                    "asset_name": asset_name,
                    "image_url": image_url,
                    "generation_time_ms": result["generation_time_ms"]
                })

                # Rate limit delay
                if idx < len(requirements) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to generate '{asset_name}': {e}")

                # Update status to failed
                if req_id and self.supabase:
                    self.supabase.table("project_asset_requirements").update({
                        "status": "generation_failed"
                    }).eq("id", str(req_id)).execute()

                failed.append({
                    "requirement_id": req_id,
                    "asset_name": asset_name,
                    "error": str(e)
                })

        total_time_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Batch generation complete: {len(successful)} successful, "
            f"{len(failed)} failed, {total_time_ms}ms total"
        )

        return {
            "successful": successful,
            "failed": failed,
            "total_time_ms": total_time_ms
        }

    async def _save_generated_image(
        self,
        brand_id: UUID,
        asset_name: str,
        image_base64: str
    ) -> str:
        """
        Save a generated image to Supabase storage.

        Args:
            brand_id: Brand UUID
            asset_name: Asset name for filename
            image_base64: Base64-encoded image

        Returns:
            Public URL for the saved image
        """
        if not self.supabase:
            logger.warning("Supabase not configured - image not saved")
            return ""

        try:
            # Decode base64 to bytes
            image_bytes = base64.b64decode(image_base64)

            # Build storage path
            filename = f"{asset_name}-generated.png"
            storage_path = f"{brand_id}/generated/{filename}"

            # Upload to storage
            await asyncio.to_thread(
                lambda: self.supabase.storage.from_("comic-assets").upload(
                    storage_path,
                    image_bytes,
                    {"content-type": "image/png"}
                )
            )

            # Get signed URL (1 year expiry for generated assets)
            result = await asyncio.to_thread(
                lambda: self.supabase.storage.from_("comic-assets").create_signed_url(
                    storage_path,
                    60 * 60 * 24 * 365  # 1 year
                )
            )

            return result.get("signedURL", "")

        except Exception as e:
            logger.error(f"Failed to save generated image: {e}")
            raise

    # =========================================================================
    # SFX GENERATION (ElevenLabs)
    # =========================================================================

    async def generate_sfx(
        self,
        description: str,
        duration_seconds: float = 2.0
    ) -> Dict[str, Any]:
        """
        Generate a sound effect using ElevenLabs Sound Generation API.

        Args:
            description: Text description of the sound effect
            duration_seconds: Desired duration (0.5 to 22 seconds)

        Returns:
            Dict with:
                - audio_base64: Generated audio as base64 (MP3)
                - duration_seconds: Actual duration
        """
        self._ensure_elevenlabs()

        # Clamp duration
        duration_seconds = max(0.5, min(22.0, duration_seconds))

        logger.info(f"Generating SFX: '{description[:50]}...' ({duration_seconds}s)")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ELEVENLABS_SFX_URL,
                    headers={
                        "xi-api-key": self.elevenlabs_api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "text": description,
                        "duration_seconds": duration_seconds
                    },
                    timeout=60.0
                )

                if response.status_code != 200:
                    error_detail = response.text
                    raise Exception(f"ElevenLabs API error: {response.status_code} - {error_detail}")

                # Response is raw audio bytes (MP3)
                audio_bytes = response.content
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

                logger.info(f"SFX generated: {len(audio_bytes)} bytes")

                return {
                    "audio_base64": audio_base64,
                    "duration_seconds": duration_seconds,
                    "description": description
                }

        except Exception as e:
            logger.error(f"Failed to generate SFX: {e}")
            raise

    async def extract_sfx_from_script(
        self,
        script_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract SFX requirements from a script.

        Looks for SFX cues in beat audio_notes and visual_notes.

        Args:
            script_data: Script JSON data

        Returns:
            List of SFX requirements with:
                - name: SFX name
                - description: What sound to generate
                - beat_references: Which beats need this SFX
        """
        sfx_requirements = []
        sfx_keywords = [
            "sound", "sfx", "audio", "noise", "rumble", "crash",
            "ding", "buzz", "whoosh", "boom", "splash", "click"
        ]

        beats = script_data.get("beats", [])

        for beat in beats:
            beat_id = beat.get("beat_id", "unknown")
            audio_notes = beat.get("audio_notes", "").lower()
            visual_notes = beat.get("visual_notes", "").lower()

            combined = f"{audio_notes} {visual_notes}"

            # Look for SFX keywords
            for keyword in sfx_keywords:
                if keyword in combined:
                    # Extract context around the keyword
                    sfx_requirements.append({
                        "name": f"sfx-{beat_id}",
                        "description": combined[:200],
                        "beat_references": [beat_id],
                        "source": "audio_notes" if keyword in audio_notes else "visual_notes"
                    })
                    break  # Only one SFX per beat

        # Deduplicate similar descriptions
        unique_sfx = self._deduplicate_sfx(sfx_requirements)

        logger.info(f"Extracted {len(unique_sfx)} unique SFX requirements from script")
        return unique_sfx

    def _deduplicate_sfx(
        self,
        sfx_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Deduplicate SFX by similar descriptions."""
        if not sfx_list:
            return []

        # Simple dedup by first 50 chars of description
        seen = {}
        for sfx in sfx_list:
            key = sfx["description"][:50].lower()
            if key not in seen:
                seen[key] = sfx
            else:
                # Merge beat references
                seen[key]["beat_references"].extend(sfx["beat_references"])

        return list(seen.values())

    async def generate_sfx_batch(
        self,
        sfx_requirements: List[Dict[str, Any]],
        project_id: UUID,
        delay_between: float = 1.0
    ) -> Dict[str, Any]:
        """
        Generate multiple SFX in batch.

        Args:
            sfx_requirements: List of SFX to generate
            project_id: Project UUID for saving
            delay_between: Seconds between generations

        Returns:
            Dict with successful and failed lists
        """
        self._ensure_elevenlabs()

        successful = []
        failed = []

        for idx, sfx in enumerate(sfx_requirements):
            sfx_name = sfx.get("name", f"sfx-{idx}")
            description = sfx.get("description", "")

            if not description:
                failed.append({
                    "name": sfx_name,
                    "error": "No description"
                })
                continue

            try:
                logger.info(f"[{idx + 1}/{len(sfx_requirements)}] Generating SFX: {sfx_name}")

                result = await self.generate_sfx(
                    description=description,
                    duration_seconds=2.0
                )

                # Save to storage
                audio_url = await self._save_generated_sfx(
                    project_id=project_id,
                    sfx_name=sfx_name,
                    audio_base64=result["audio_base64"]
                )

                successful.append({
                    "name": sfx_name,
                    "audio_url": audio_url,
                    "beat_references": sfx.get("beat_references", [])
                })

                if idx < len(sfx_requirements) - 1:
                    await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error(f"Failed to generate SFX '{sfx_name}': {e}")
                failed.append({
                    "name": sfx_name,
                    "error": str(e)
                })

        logger.info(f"SFX batch complete: {len(successful)} successful, {len(failed)} failed")

        return {
            "successful": successful,
            "failed": failed
        }

    async def _save_generated_sfx(
        self,
        project_id: UUID,
        sfx_name: str,
        audio_base64: str
    ) -> str:
        """Save generated SFX to storage."""
        if not self.supabase:
            return ""

        try:
            audio_bytes = base64.b64decode(audio_base64)
            filename = f"{sfx_name}.mp3"
            storage_path = f"sfx/{project_id}/{filename}"

            await asyncio.to_thread(
                lambda: self.supabase.storage.from_("comic-assets").upload(
                    storage_path,
                    audio_bytes,
                    {"content-type": "audio/mpeg"}
                )
            )

            result = await asyncio.to_thread(
                lambda: self.supabase.storage.from_("comic-assets").create_signed_url(
                    storage_path,
                    60 * 60 * 24 * 365
                )
            )

            return result.get("signedURL", "")

        except Exception as e:
            logger.error(f"Failed to save SFX: {e}")
            raise

    # =========================================================================
    # ASSET REVIEW
    # =========================================================================

    async def approve_asset(
        self,
        requirement_id: UUID,
        add_to_library: bool = True,
        brand_id: UUID = None
    ) -> Optional[UUID]:
        """
        Approve a generated asset.

        Args:
            requirement_id: Requirement UUID to approve
            add_to_library: If True, also add to comic_assets library
            brand_id: Brand UUID (required if add_to_library=True)

        Returns:
            Asset UUID if added to library, None otherwise
        """
        if not self.supabase:
            return None

        try:
            # Update requirement status
            self.supabase.table("project_asset_requirements").update({
                "status": "approved"
            }).eq("id", str(requirement_id)).execute()

            # Optionally add to library
            if add_to_library and brand_id:
                # Get requirement details
                result = self.supabase.table("project_asset_requirements").select(
                    "*"
                ).eq("id", str(requirement_id)).execute()

                if result.data:
                    req = result.data[0]
                    asset_id = await self._add_to_library(
                        brand_id=brand_id,
                        name=req.get("asset_name"),
                        asset_type=req.get("asset_type"),
                        description=req.get("asset_description", ""),
                        image_url=req.get("generated_image_url")
                    )
                    return asset_id

            return None

        except Exception as e:
            logger.error(f"Failed to approve asset: {e}")
            raise

    async def reject_asset(
        self,
        requirement_id: UUID,
        rejection_reason: str = ""
    ) -> None:
        """
        Reject a generated asset.

        Args:
            requirement_id: Requirement UUID to reject
            rejection_reason: Optional reason for rejection
        """
        if not self.supabase:
            return

        try:
            self.supabase.table("project_asset_requirements").update({
                "status": "rejected",
                "rejection_reason": rejection_reason
            }).eq("id", str(requirement_id)).execute()

            logger.info(f"Asset {requirement_id} rejected: {rejection_reason}")

        except Exception as e:
            logger.error(f"Failed to reject asset: {e}")

    async def _add_to_library(
        self,
        brand_id: UUID,
        name: str,
        asset_type: str,
        description: str,
        image_url: str
    ) -> UUID:
        """Add approved asset to the comic_assets library."""
        try:
            record = {
                "brand_id": str(brand_id),
                "name": name,
                "asset_type": asset_type,
                "description": description,
                "image_url": image_url,
                "is_core_asset": False,
                "tags": ["generated", "approved"],
                "style_suffix": DEFAULT_STYLE_SUFFIX
            }

            result = self.supabase.table("comic_assets").insert(record).execute()

            if result.data:
                asset_id = UUID(result.data[0]["id"])
                logger.info(f"Added approved asset to library: {asset_id}")
                return asset_id

            return uuid4()

        except Exception as e:
            logger.error(f"Failed to add asset to library: {e}")
            raise

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    async def get_pending_generation(
        self,
        project_id: UUID
    ) -> List[Dict[str, Any]]:
        """Get requirements that need generation."""
        if not self.supabase:
            return []

        try:
            result = self.supabase.table("project_asset_requirements").select(
                "*"
            ).eq("project_id", str(project_id)).eq("status", "needed").execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to fetch pending generation: {e}")
            return []

    async def get_pending_review(
        self,
        project_id: UUID
    ) -> List[Dict[str, Any]]:
        """Get generated assets pending review."""
        if not self.supabase:
            return []

        try:
            result = self.supabase.table("project_asset_requirements").select(
                "*"
            ).eq("project_id", str(project_id)).eq("status", "generated").execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to fetch pending review: {e}")
            return []
