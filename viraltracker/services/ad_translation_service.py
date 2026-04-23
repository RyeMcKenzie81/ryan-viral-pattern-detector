"""
Ad Translation Service

Translates existing winning ads into target languages. Handles:
- Ad lookup by UUID, structured filename fragment, or Meta ad ID
- Marketing-aware copy translation via Claude
- Image regeneration with translated text via Gemini
- Batch translation with performance-based ad selection
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Common language name → IETF tag mapping
_LANGUAGE_MAP = {
    # Full names
    "english": "en",
    "spanish": "es",
    "mexican spanish": "es-MX",
    "latin american spanish": "es-419",
    "american spanish": "es-419",
    "portuguese": "pt",
    "brazilian portuguese": "pt-BR",
    "french": "fr",
    "canadian french": "fr-CA",
    "german": "de",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "simplified chinese": "zh-CN",
    "traditional chinese": "zh-TW",
    "dutch": "nl",
    "russian": "ru",
    "arabic": "ar",
    "hindi": "hi",
    "turkish": "tr",
    "polish": "pl",
    "swedish": "sv",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "malay": "ms",
    # Native names
    "español": "es",
    "português": "pt",
    "français": "fr",
    "deutsch": "de",
    "italiano": "it",
    "日本語": "ja",
    "한국어": "ko",
    "中文": "zh",
}


class AdTranslationService:
    """Service for translating existing ads into target languages."""

    def __init__(self, supabase, gemini_service, ad_creation_service):
        """
        Args:
            supabase: Supabase client for DB operations
            gemini_service: GeminiService for image regeneration
            ad_creation_service: AdCreationService for image download/upload and ad CRUD
        """
        self.supabase = supabase
        self.gemini = gemini_service
        self.ad_creation = ad_creation_service
        self._anthropic = None

    @property
    def anthropic_client(self):
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # =========================================================================
    # AD LOOKUP
    # =========================================================================

    async def lookup_ad(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find an ad by any identifier format.

        Supports:
        - Full UUID: direct lookup on generated_ads.id
        - Structured filename fragment (e.g., "65bb40", "SAV-FTS-65bb40-04161b-SQ"):
          parse and match against id_prefix column
        - Meta ad ID (numeric): lookup via meta_ad_mapping table

        Args:
            query: Any ad identifier string

        Returns:
            Ad dict with copy fields, storage_path, performance data, lineage.
            None if not found.
        """
        query = query.strip()
        parsed = self._parse_ad_identifier(query)

        if parsed["type"] == "uuid":
            return await self._lookup_by_uuid(parsed["value"])
        elif parsed["type"] == "filename_fragment":
            return await self._lookup_by_prefix(parsed["value"])
        elif parsed["type"] == "meta_ad_id":
            return await self._lookup_by_meta_ad_id(parsed["value"])
        else:
            logger.warning(f"Could not parse ad identifier: {query}")
            return None

    async def _lookup_by_uuid(self, uuid_str: str) -> Optional[Dict[str, Any]]:
        """Direct lookup by full UUID."""
        try:
            result = self.supabase.table("generated_ads").select(
                "id, storage_path, prompt_spec, prompt_text, hook_text, hook_id, "
                "meta_headline, meta_primary_text, canvas_size, color_mode, "
                "final_status, language, translation_parent_id, "
                "ad_run_id, ad_runs(product_id, parameters), "
                "template_name, angle_id, belief_plan_id, "
                "parent_ad_id, edit_parent_id, regenerate_parent_id"
            ).eq("id", uuid_str).execute()

            if result.data:
                ad = result.data[0]
                return await self._enrich_with_performance(ad)
            return None
        except Exception as e:
            logger.error(f"UUID lookup failed for {uuid_str}: {e}")
            return None

    async def _lookup_by_prefix(self, prefix: str) -> Optional[Dict[str, Any]]:
        """Lookup by id_prefix column (indexed, fast)."""
        try:
            result = self.supabase.table("generated_ads").select(
                "id, storage_path, prompt_spec, prompt_text, hook_text, hook_id, "
                "meta_headline, meta_primary_text, canvas_size, color_mode, "
                "final_status, language, translation_parent_id, "
                "ad_run_id, ad_runs(product_id, parameters), "
                "template_name, angle_id, belief_plan_id, "
                "parent_ad_id, edit_parent_id, regenerate_parent_id"
            ).like("id_prefix", f"{prefix}%").execute()

            if not result.data:
                return None

            if len(result.data) == 1:
                return await self._enrich_with_performance(result.data[0])

            # Multiple matches: return list for user to choose
            return {
                "multiple_matches": True,
                "count": len(result.data),
                "matches": [
                    {
                        "id": ad["id"],
                        "hook_text": (ad.get("hook_text") or "")[:80],
                        "final_status": ad.get("final_status"),
                        "canvas_size": ad.get("canvas_size"),
                        "language": ad.get("language"),
                    }
                    for ad in result.data[:10]
                ],
            }
        except Exception as e:
            logger.error(f"Prefix lookup failed for {prefix}: {e}")
            return None

    async def _lookup_by_meta_ad_id(self, meta_ad_id: str) -> Optional[Dict[str, Any]]:
        """Lookup via meta_ad_mapping table."""
        try:
            mapping = self.supabase.table("meta_ad_mapping").select(
                "generated_ad_id"
            ).eq("meta_ad_id", meta_ad_id).limit(1).execute()

            if not mapping.data:
                return None

            generated_ad_id = mapping.data[0]["generated_ad_id"]
            return await self._lookup_by_uuid(generated_ad_id)
        except Exception as e:
            logger.error(f"Meta ad ID lookup failed for {meta_ad_id}: {e}")
            return None

    async def _enrich_with_performance(self, ad: Dict) -> Dict:
        """Add performance data and signed image URL."""
        # Signed URL for image display
        storage_path = ad.get("storage_path")
        if storage_path:
            signed_url = self._get_signed_url(storage_path)
            if signed_url:
                ad["image_url"] = signed_url

        try:
            mapping = self.supabase.table("meta_ad_mapping").select(
                "meta_ad_id"
            ).eq("generated_ad_id", ad["id"]).limit(1).execute()

            if mapping.data:
                meta_ad_id = mapping.data[0]["meta_ad_id"]
                perf = self.supabase.table("meta_ads_performance").select(
                    "spend, impressions, link_clicks, link_ctr, roas, purchases, purchase_value"
                ).eq("meta_ad_id", meta_ad_id).order(
                    "date", desc=True
                ).limit(1).execute()

                if perf.data:
                    ad["performance"] = perf.data[0]
                    ad["meta_ad_id"] = meta_ad_id
        except Exception as e:
            logger.debug(f"Performance enrichment failed for ad {ad['id']}: {e}")

        return ad

    def _get_signed_url(self, storage_path: str) -> Optional[str]:
        """Convert Supabase storage path to a signed URL (1 hour expiry)."""
        try:
            parts = storage_path.split("/", 1)
            bucket = parts[0]
            path = parts[1] if len(parts) > 1 else storage_path
            result = self.supabase.storage.from_(bucket).create_signed_url(path, 3600)
            return result.get("signedURL", "")
        except Exception as e:
            logger.debug(f"Failed to create signed URL for {storage_path}: {e}")
            return None

    # =========================================================================
    # COPY TRANSLATION
    # =========================================================================

    async def translate_ad_copy(
        self,
        hook_text: str,
        meta_headline: Optional[str],
        meta_primary_text: Optional[str],
        target_language: str,
        brand_voice_context: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Translate ad copy fields using Claude. Marketing-aware, not literal.

        Args:
            hook_text: The adapted hook text from the ad
            meta_headline: Headline for Meta ad placement (may be None)
            meta_primary_text: Primary text for Meta ad placement (may be None)
            target_language: IETF language tag (e.g., "es-MX", "pt-BR")
            brand_voice_context: Optional brand voice notes for tone matching

        Returns:
            Dict with translated hook_text, meta_headline, meta_primary_text
        """
        fields_to_translate = {"hook_text": hook_text}
        if meta_headline:
            fields_to_translate["meta_headline"] = meta_headline
        if meta_primary_text:
            fields_to_translate["meta_primary_text"] = meta_primary_text

        brand_context = ""
        if brand_voice_context:
            brand_context = f"\n\nBrand voice notes: {brand_voice_context}"

        prompt = f"""You are a marketing copywriter who specializes in ad translation.
Translate the following ad copy into {target_language}. This is for a paid ad, not documentation.

RULES:
- Preserve the persuasive intent and emotional impact, not literal meaning
- Adapt idioms and cultural references for the target market
- Keep the same urgency, tone, and call-to-action energy
- Maintain similar character length (ads have space constraints)
- Do NOT add disclaimers, explanations, or translator notes
{brand_context}

Return ONLY a JSON object with the translated fields. No markdown, no explanation.

Input:
{json.dumps(fields_to_translate, ensure_ascii=False)}

Output (JSON only):"""

        response = self.anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)

        translated = json.loads(response_text)

        result = {
            "hook_text": translated.get("hook_text", hook_text),
            "meta_headline": translated.get("meta_headline", meta_headline),
            "meta_primary_text": translated.get("meta_primary_text", meta_primary_text),
        }

        logger.info(f"Translated ad copy to {target_language}: "
                     f"hook={len(result['hook_text'])} chars")
        return result

    # =========================================================================
    # PROMPT SPEC MODIFICATION
    # =========================================================================

    # Canvas size to Gemini aspect ratio mapping
    # Gemini supports: 1:1, 3:4, 4:3, 9:16, 16:9, 2:3, 3:2, 21:9
    _CANVAS_ASPECT_MAP = {
        (1080, 1080): "1:1",
        (1080, 1350): "3:4",   # 4:5 → closest supported
        (1080, 1920): "9:16",
        (1920, 1080): "16:9",
    }

    def _canvas_size_to_aspect_ratio(self, canvas_size: Optional[str]) -> Optional[str]:
        """Map canvas_size like '1080x1350px' to a Gemini aspect_ratio like '3:4'."""
        if not canvas_size:
            return None
        # Strip non-digit suffixes (e.g. "px") and split
        clean = canvas_size.lower().replace("px", "").strip()
        parts = clean.split("x")
        if len(parts) != 2:
            return None
        try:
            w, h = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        return self._CANVAS_ASPECT_MAP.get((w, h))

    def _build_edit_prompt(
        self,
        original_hook: str,
        translated_hook: str,
        original_benefit: Optional[str] = None,
        translated_benefit: Optional[str] = None,
    ) -> str:
        """Build an image-edit prompt that swaps only overlay text."""
        lines = [
            "Edit this ad image. Change ONLY the overlay text as specified below. "
            "Keep everything else EXACTLY the same — layout, colors, background, "
            "product packaging, logos, and all text ON the product must not change.",
            "",
            "Text changes:",
            f'  Change "{original_hook}" → "{translated_hook}"',
        ]
        if original_benefit and translated_benefit:
            lines.append(f'  Change "{original_benefit}" → "{translated_benefit}"')
        lines.append("")
        lines.append(
            "Do NOT re-render the product, background, or any other element. "
            "The result should look identical to the original except for the "
            "translated overlay text."
        )
        return "\n".join(lines)

    def _swap_prompt_spec_text(
        self,
        prompt_spec: Dict,
        translated_hook: str,
        translated_benefit: Optional[str] = None,
    ) -> Dict:
        """
        Replace text fields in prompt_spec with translated versions.
        Uses defensive path extraction with fallback for schema drift.

        Args:
            prompt_spec: The original prompt_spec JSON dict
            translated_hook: Translated headline/hook text
            translated_benefit: Translated subheadline/benefit text (optional)

        Returns:
            Modified prompt_spec dict with translated text
        """
        import copy
        spec = copy.deepcopy(prompt_spec)

        # Primary path: content.headline.text / content.subheadline.text
        swapped = False
        try:
            if "content" in spec:
                content = spec["content"]
                if "headline" in content and "text" in content["headline"]:
                    content["headline"]["text"] = translated_hook
                    swapped = True
                if translated_benefit and "subheadline" in content and "text" in content["subheadline"]:
                    content["subheadline"]["text"] = translated_benefit
        except (KeyError, TypeError):
            pass

        if swapped:
            return spec

        # Fallback: search for text fields in the JSON tree
        logger.warning("prompt_spec schema drift detected. Using fallback text replacement.")
        self._recursive_text_replace(spec, translated_hook, "headline")
        if translated_benefit:
            self._recursive_text_replace(spec, translated_benefit, "subheadline")

        return spec

    def _recursive_text_replace(self, obj: Any, new_text: str, key_hint: str) -> bool:
        """Recursively search for a 'text' field near a key matching key_hint."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key_hint in key.lower() and isinstance(value, dict) and "text" in value:
                    value["text"] = new_text
                    return True
                if self._recursive_text_replace(value, new_text, key_hint):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if self._recursive_text_replace(item, new_text, key_hint):
                    return True
        return False

    # =========================================================================
    # SINGLE AD TRANSLATION
    # =========================================================================

    async def translate_single_ad(
        self,
        source_ad_id: UUID,
        target_language: str,
        ad_run_id: Optional[UUID] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Translate a single ad into the target language.

        Flow:
        1. Check idempotency (skip if already translated to this language)
        2. Fetch source ad data
        3. Translate copy via Claude
        4. Modify prompt_spec with translated text
        5. Regenerate image via Gemini
        6. Upload and save new ad with language + translation_parent_id

        Args:
            source_ad_id: UUID of the ad to translate
            target_language: IETF language tag (e.g., "es-MX")
            ad_run_id: Optional ad_run_id to group translations into
            force: If True, delete existing translation and redo it

        Returns:
            Dict with new ad info or error details
        """
        # 1. Idempotency check
        existing = self.supabase.table("generated_ads").select("id").eq(
            "translation_parent_id", str(source_ad_id)
        ).eq("language", target_language).limit(1).execute()

        if existing.data:
            if force:
                # Delete the old translation so we can redo it
                old_id = existing.data[0]["id"]
                logger.info(f"Force retranslation: deleting old translation {old_id}")
                self.supabase.table("generated_ads").delete().eq("id", old_id).execute()
            else:
                return {
                    "status": "exists",
                    "reason": "already_translated",
                    "existing_translation_id": existing.data[0]["id"],
                    "source_ad_id": str(source_ad_id),
                    "language": target_language,
                }

        # 2. Fetch source ad
        source_ad = await self.ad_creation.get_ad_for_variant(source_ad_id)
        if not source_ad:
            return {
                "status": "error",
                "reason": "source_not_found",
                "source_ad_id": str(source_ad_id),
            }

        prompt_spec = source_ad.get("prompt_spec")
        if not prompt_spec:
            return {
                "status": "error",
                "reason": "no_prompt_spec",
                "source_ad_id": str(source_ad_id),
                "message": "Source ad has no prompt_spec (may be an old or imported ad)",
            }

        hook_text = source_ad.get("hook_text", "")
        if not hook_text:
            return {
                "status": "error",
                "reason": "no_hook_text",
                "source_ad_id": str(source_ad_id),
                "message": "Source ad has no hook text to translate",
            }

        # Get additional copy fields from the full ad record
        full_ad = self.supabase.table("generated_ads").select(
            "meta_headline, meta_primary_text, canvas_size, color_mode"
        ).eq("id", str(source_ad_id)).execute()
        ad_extras = full_ad.data[0] if full_ad.data else {}

        # 3. Translate copy
        translated = await self.translate_ad_copy(
            hook_text=hook_text,
            meta_headline=ad_extras.get("meta_headline"),
            meta_primary_text=ad_extras.get("meta_primary_text"),
            target_language=target_language,
        )

        # 4. Modify prompt_spec
        # Extract the subheadline/benefit text from prompt_spec for translation
        benefit_text = None
        try:
            benefit_text = prompt_spec.get("content", {}).get("subheadline", {}).get("text")
        except (AttributeError, TypeError):
            pass

        translated_benefit = None
        if benefit_text:
            # Translate the benefit text separately since it's in the image, not Meta copy
            benefit_response = await self.translate_ad_copy(
                hook_text=benefit_text,
                meta_headline=None,
                meta_primary_text=None,
                target_language=target_language,
            )
            translated_benefit = benefit_response.get("hook_text")

        modified_spec = self._swap_prompt_spec_text(
            prompt_spec, translated["hook_text"], translated_benefit
        )
        modified_prompt_text = json.dumps(modified_spec, indent=2, ensure_ascii=False)

        # 5. Edit image via Gemini — change only the overlay text, keep everything else
        reference_images = []
        storage_path = source_ad.get("storage_path")
        if storage_path:
            try:
                template_data = await self.ad_creation.download_image(storage_path)
                reference_images.append(template_data)
            except Exception as e:
                logger.warning(f"Could not download source ad image: {e}")

        # Map canvas_size to Gemini aspect_ratio to preserve original dimensions
        aspect_ratio = self._canvas_size_to_aspect_ratio(ad_extras.get("canvas_size"))

        # Build an edit-style prompt: tell Gemini exactly which text to swap
        edit_prompt = self._build_edit_prompt(
            original_hook=hook_text,
            translated_hook=translated["hook_text"],
            original_benefit=benefit_text,
            translated_benefit=translated_benefit,
        )

        try:
            generation_start = time.time()
            gen_result = await self.gemini.generate_image(
                prompt=edit_prompt,
                reference_images=reference_images if reference_images else None,
                return_metadata=True,
                temperature=0.15,
                image_size="4K",
                aspect_ratio=aspect_ratio,
            )
            generation_time_ms = int((time.time() - generation_start) * 1000)
        except Exception as e:
            logger.error(f"Image generation failed for translation of {source_ad_id}: {e}")
            return {
                "status": "error",
                "reason": "generation_failed",
                "source_ad_id": str(source_ad_id),
                "message": str(e),
            }

        # 6. Upload and save
        # Get product_id from ad_run
        product_id = None
        ad_runs = source_ad.get("ad_runs")
        if ad_runs:
            product_id = ad_runs.get("product_id") if isinstance(ad_runs, dict) else None

        new_ad_id = uuid4()
        run_id = ad_run_id or UUID(source_ad["ad_run_id"])

        try:
            # Upload image
            upload_path, _ = await self.ad_creation.upload_generated_ad(
                ad_run_id=run_id,
                prompt_index=1,
                image_base64=gen_result["image_base64"],
                product_id=UUID(product_id) if product_id else None,
                ad_id=new_ad_id,
                canvas_size=ad_extras.get("canvas_size"),
            )
        except Exception as e:
            logger.error(f"Image upload failed for translation of {source_ad_id}: {e}")
            return {
                "status": "error",
                "reason": "upload_failed",
                "source_ad_id": str(source_ad_id),
                "message": str(e),
            }

        try:
            # Save to generated_ads
            saved_id = await self.ad_creation.save_generated_ad(
                ad_run_id=run_id,
                prompt_index=1,
                prompt_text=modified_prompt_text,
                prompt_spec=modified_spec,
                hook_id=UUID(source_ad["hook_id"]) if source_ad.get("hook_id") else None,
                hook_text=translated["hook_text"],
                storage_path=upload_path,
                final_status="approved",
                model_requested=gen_result.get("model_requested"),
                model_used=gen_result.get("model_used"),
                generation_time_ms=generation_time_ms,
                generation_retries=gen_result.get("retries", 0),
                ad_id=new_ad_id,
                meta_headline=translated.get("meta_headline"),
                meta_primary_text=translated.get("meta_primary_text"),
                canvas_size=ad_extras.get("canvas_size"),
                color_mode=ad_extras.get("color_mode"),
                language=target_language,
                translation_parent_id=source_ad_id,
            )
        except Exception as e:
            logger.error(f"DB save failed for translation of {source_ad_id}: {e}")
            return {
                "status": "error",
                "reason": "save_failed",
                "source_ad_id": str(source_ad_id),
                "message": str(e),
            }

        logger.info(f"Translated ad {source_ad_id} → {saved_id} ({target_language})")
        return {
            "status": "success",
            "source_ad_id": str(source_ad_id),
            "translated_ad_id": str(saved_id),
            "language": target_language,
            "translated_hook_text": translated["hook_text"],
        }

    # =========================================================================
    # BATCH TRANSLATION
    # =========================================================================

    async def translate_batch(
        self,
        ad_ids: Optional[List[str]] = None,
        product_id: Optional[str] = None,
        top_n_by_roas: Optional[int] = None,
        target_language: str = "es-MX",
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Translate a batch of ads into the target language.

        Selection modes:
        - Explicit ad_ids: translate these specific ads
        - Performance filter: top N ads by ROAS for a product (respects winner criteria)

        Creates a translation ad_run to group results.

        Args:
            ad_ids: Explicit list of ad IDs (UUID strings) to translate
            product_id: Product UUID for performance-based selection
            top_n_by_roas: Number of top ads by ROAS to translate
            target_language: IETF language tag
            force: If True, delete existing translations and redo them

        Returns:
            Dict with ad_run_id, results per ad, and summary counts
        """
        target_language = self._normalize_language(target_language)

        # Resolve ad list
        resolved_ids = []
        if ad_ids:
            resolved_ids = [UUID(aid) for aid in ad_ids]
        elif product_id and top_n_by_roas:
            resolved_ids = await self._get_top_ads_by_roas(
                UUID(product_id), top_n_by_roas
            )
        else:
            return {
                "status": "error",
                "reason": "invalid_params",
                "message": "Provide ad_ids OR (product_id + top_n_by_roas)",
            }

        if not resolved_ids:
            return {
                "status": "error",
                "reason": "no_ads_found",
                "message": "No ads match the selection criteria",
            }

        # Create translation ad_run
        # We need the product_id for ad_run creation
        run_product_id = None
        if product_id:
            run_product_id = UUID(product_id)
        elif resolved_ids:
            # Get product_id from first ad's run
            first_ad = await self.ad_creation.get_ad_for_variant(resolved_ids[0])
            if first_ad and first_ad.get("ad_runs"):
                ad_runs = first_ad["ad_runs"]
                pid = ad_runs.get("product_id") if isinstance(ad_runs, dict) else None
                if pid:
                    run_product_id = UUID(pid)

        if not run_product_id:
            return {
                "status": "error",
                "reason": "no_product_id",
                "message": "Could not determine product_id for translation run",
            }

        ad_run_id = await self.ad_creation.create_ad_run(
            product_id=run_product_id,
            reference_ad_storage_path="translation",
            parameters={
                "content_source": "translation",
                "target_language": target_language,
                "source_ad_ids": [str(aid) for aid in resolved_ids],
                "translator_model": "claude-sonnet-4-5-20250929",
                "translator_prompt_version": "v1.0",
                "initiated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )

        # Translate each ad
        results = []
        success_count = 0
        skip_count = 0
        error_count = 0

        for ad_id in resolved_ids:
            try:
                result = await self.translate_single_ad(
                    source_ad_id=ad_id,
                    target_language=target_language,
                    ad_run_id=ad_run_id,
                    force=force,
                )
                results.append(result)
                if result["status"] == "success":
                    success_count += 1
                elif result["status"] in ("skipped", "exists"):
                    skip_count += 1
                else:
                    error_count += 1
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error(f"Translation failed for ad {ad_id}: {e}\n{tb}")
                results.append({
                    "status": "error",
                    "reason": "unexpected_error",
                    "source_ad_id": str(ad_id),
                    "message": f"{type(e).__name__}: {e}",
                })
                error_count += 1

        # Update ad_run status (valid values: pending, running, complete, failed)
        run_status = "complete" if success_count > 0 or skip_count > 0 else "failed"

        await self.ad_creation.update_ad_run(
            ad_run_id=ad_run_id,
            status=run_status,
            error_message=f"{error_count} translation(s) failed" if error_count > 0 else None,
        )

        logger.info(
            f"Translation batch complete: {success_count} success, "
            f"{skip_count} skipped, {error_count} errors"
        )

        # Collect error messages for top-level visibility
        error_messages = [
            r.get("message", "unknown") for r in results if r.get("status") == "error"
        ]

        batch_result = {
            "status": "success" if success_count > 0 else "failed",
            "ad_run_id": str(ad_run_id),
            "target_language": target_language,
            "total": len(resolved_ids),
            "success": success_count,
            "skipped": skip_count,
            "errors": error_count,
            "results": results,
        }

        if error_messages:
            batch_result["error_details"] = " | ".join(error_messages)

        return batch_result

    async def _get_top_ads_by_roas(
        self, product_id: UUID, top_n: int
    ) -> List[UUID]:
        """
        Get top N ads by ROAS for a product.
        Respects winner criteria: linked to Meta, has performance data.

        Args:
            product_id: Product UUID
            top_n: Number of top ads to return

        Returns:
            List of ad UUIDs sorted by ROAS descending
        """
        try:
            # Get ad_runs for this product
            runs = self.supabase.table("ad_runs").select("id").eq(
                "product_id", str(product_id)
            ).execute()

            if not runs.data:
                return []

            run_ids = [r["id"] for r in runs.data]

            # Get approved generated_ads from these runs that are in English
            ads = self.supabase.table("generated_ads").select(
                "id"
            ).in_("ad_run_id", run_ids).eq(
                "final_status", "approved"
            ).eq("language", "en").execute()

            if not ads.data:
                return []

            ad_ids = [a["id"] for a in ads.data]

            # Get performance data via meta_ad_mapping
            mappings = self.supabase.table("meta_ad_mapping").select(
                "generated_ad_id, meta_ad_id"
            ).in_("generated_ad_id", ad_ids).execute()

            if not mappings.data:
                return []

            meta_ad_ids = [m["meta_ad_id"] for m in mappings.data]
            gen_id_by_meta = {m["meta_ad_id"]: m["generated_ad_id"] for m in mappings.data}

            # Get latest ROAS for each Meta ad
            # Use RPC or manual aggregation
            perf_results = []
            for meta_id in meta_ad_ids:
                perf = self.supabase.table("meta_ads_performance").select(
                    "meta_ad_id, roas, impressions, spend"
                ).eq("meta_ad_id", meta_id).order(
                    "date", desc=True
                ).limit(1).execute()
                if perf.data:
                    perf_results.append(perf.data[0])

            # Filter by winner criteria (impressions >= 1000) and sort by ROAS
            qualified = [
                p for p in perf_results
                if (p.get("impressions") or 0) >= 1000
                and (p.get("roas") or 0) > 0
            ]
            qualified.sort(key=lambda p: p.get("roas", 0), reverse=True)

            # Map back to generated_ad UUIDs
            top_ids = []
            for p in qualified[:top_n]:
                gen_id = gen_id_by_meta.get(p["meta_ad_id"])
                if gen_id:
                    top_ids.append(UUID(gen_id))

            logger.info(f"Found {len(top_ids)} top ads by ROAS for product {product_id}")
            return top_ids

        except Exception as e:
            logger.error(f"Failed to get top ads by ROAS: {e}")
            return []

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _parse_ad_identifier(self, query: str) -> Dict[str, str]:
        """
        Parse a user-provided ad identifier into a lookup strategy.

        Returns:
            Dict with "type" and "value" keys.
            type: "uuid", "filename_fragment", "meta_ad_id", or "unknown"
        """
        query = query.strip()

        # Full UUID (with or without hyphens)
        uuid_pattern = r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$"
        if re.match(uuid_pattern, query, re.IGNORECASE):
            # Normalize to hyphenated form
            clean = query.replace("-", "").lower()
            uuid_str = f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
            return {"type": "uuid", "value": uuid_str}

        # Structured filename: SAV-FTS-65bb40-04161b-SQ or SAV-FTS-65bb40-04161b-SQ-ES
        # Extract the ad_id fragment (4th segment, 6 hex chars)
        struct_match = re.match(
            r"[A-Za-z]{2,4}-[A-Za-z0-9]{2,4}-[a-f0-9]{6}-([a-f0-9]{6})-[A-Za-z]{2}",
            query, re.IGNORECASE
        )
        if struct_match:
            return {"type": "filename_fragment", "value": struct_match.group(1).lower()}

        # M5 format: M5-d4e5f6a7-WP-C3-SQ.png (8-char ad ID in 2nd position)
        m5_match = re.match(r"M5-([a-f0-9]{8})", query, re.IGNORECASE)
        if m5_match:
            return {"type": "filename_fragment", "value": m5_match.group(1).lower()}

        # Bare hex fragment (6-8 chars)
        if re.match(r"^[0-9a-f]{6,8}$", query, re.IGNORECASE):
            return {"type": "filename_fragment", "value": query.lower()}

        # Pure numeric (likely Meta ad ID)
        if re.match(r"^\d{10,20}$", query):
            return {"type": "meta_ad_id", "value": query}

        return {"type": "unknown", "value": query}

    def _normalize_language(self, language: str) -> str:
        """
        Normalize language input to IETF language tag.

        Accepts:
        - IETF tags: "es-MX", "pt-BR" → returned as-is (lowercased base, uppercased region)
        - ISO codes: "es", "fr" → returned as-is
        - Full names: "Spanish", "Mexican Spanish" → mapped to IETF tag
        - Native names: "español" → mapped to IETF tag

        Args:
            language: Any language identifier string

        Returns:
            Normalized IETF language tag (e.g., "es-MX", "pt-BR", "fr")
        """
        language = language.strip()

        # Already an IETF tag (e.g., "es-MX", "pt-BR")
        ietf_match = re.match(r"^([a-zA-Z]{2,3})[-_]([a-zA-Z]{2,4})$", language)
        if ietf_match:
            base = ietf_match.group(1).lower()
            region = ietf_match.group(2).upper()
            return f"{base}-{region}"

        # ISO 639-1 code (2-3 lowercase letters)
        if re.match(r"^[a-zA-Z]{2,3}$", language):
            return language.lower()

        # Full name lookup
        normalized = _LANGUAGE_MAP.get(language.lower())
        if normalized:
            return normalized

        # Fallback: return as-is lowercased
        logger.warning(f"Could not normalize language: {language}. Using as-is.")
        return language.lower()
