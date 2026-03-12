"""
Visual Property Extractor — Gemini vision analysis of ad creative images.

Extracts visual properties (contrast, color, composition, faces, etc.) that
affect ad performance. Caches results in the ad_visual_properties table to
avoid re-extracting unchanged images.

Usage:
    from viraltracker.services.visual_property_extractor import VisualPropertyExtractor

    extractor = VisualPropertyExtractor(supabase_client, gemini_service)
    props = await extractor.extract(meta_ad_id, brand_id, org_id)
"""

import base64
import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

VISUAL_EXTRACTION_PROMPT = """Analyze this ad creative image and extract visual properties
that affect ad performance. Return ONLY valid JSON with no markdown formatting:
{
    "contrast_level": "low|medium|high|extreme",
    "color_palette_type": "warm|cool|neutral|high_contrast|monochrome",
    "dominant_colors": [{"hex": "#RRGGBB", "name": "string", "pct": 0.0}],
    "text_density": "none|minimal|moderate|heavy",
    "headline_word_count": 0,
    "visual_hierarchy": "product_centric|text_centric|face_centric|scene_centric",
    "composition_style": "centered|rule_of_thirds|full_bleed|collage|split",
    "face_presence": true,
    "face_count": 0,
    "face_emotion": "happy|neutral|surprised|concerned|excited|null",
    "person_framing": "close_up|medium|full_body|none",
    "product_visible": true,
    "product_prominence": "hero|supporting|absent",
    "before_after_present": false,
    "headline_style": "bold|subtle|handwritten|none",
    "cta_visual_treatment": "button|text_only|overlay|none",
    "visual_quality_score": 0.85,
    "thumb_stop_prediction": 0.70
}

Rules:
- Return ONLY the JSON object, no explanation
- Use null for face_emotion if no faces present
- visual_quality_score and thumb_stop_prediction are 0.0-1.0 floats
- dominant_colors: list top 3 colors with approximate percentage
- headline_word_count: count visible text words (0 if no text)
"""

# Valid enum values for validation
VALID_ENUMS = {
    "contrast_level": {"low", "medium", "high", "extreme"},
    "color_palette_type": {"warm", "cool", "neutral", "high_contrast", "monochrome"},
    "text_density": {"none", "minimal", "moderate", "heavy"},
    "visual_hierarchy": {"product_centric", "text_centric", "face_centric", "scene_centric"},
    "composition_style": {"centered", "rule_of_thirds", "full_bleed", "collage", "split"},
    "face_emotion": {"happy", "neutral", "surprised", "concerned", "excited", None},
    "person_framing": {"close_up", "medium", "full_body", "none"},
    "product_prominence": {"hero", "supporting", "absent"},
    "headline_style": {"bold", "subtle", "handwritten", "none"},
    "cta_visual_treatment": {"button", "text_only", "overlay", "none"},
}


class VisualPropertyExtractor:
    """Extracts visual properties from ad creative images via Gemini vision."""

    def __init__(self, supabase_client, gemini_service=None):
        self.supabase = supabase_client
        self.gemini = gemini_service

    async def extract(
        self,
        meta_ad_id: str,
        brand_id: str,
        org_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Extract visual properties for an ad, using cache if available.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            org_id: Organization UUID (or "all" for superuser).

        Returns:
            Dict of visual properties, or None if extraction failed/no image.
        """
        # 1. Check cache
        cached = self._get_cached(meta_ad_id, brand_id)
        if cached:
            logger.debug(f"Cache hit for visual props: {meta_ad_id}")
            return cached

        # 2. Fetch image bytes
        image_bytes, image_source = await self._fetch_image(meta_ad_id, brand_id)
        if not image_bytes:
            logger.info(f"No image available for {meta_ad_id}, skipping visual extraction")
            return None

        # 3. Extract via Gemini
        if not self.gemini:
            logger.warning("GeminiService not configured, skipping visual extraction")
            return None

        input_hash = self._compute_input_hash(image_bytes)

        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            result_text = await self.gemini.analyze_image(image_b64, VISUAL_EXTRACTION_PROMPT)
            props = self._parse_and_validate(result_text)
        except Exception as e:
            logger.error(f"Gemini visual extraction failed for {meta_ad_id}: {e}")
            return None

        if not props:
            logger.warning(f"Failed to parse visual extraction for {meta_ad_id}")
            return None

        # 4. Store in cache
        real_org_id = self._resolve_org_id(org_id, brand_id)
        self._store(meta_ad_id, brand_id, real_org_id, props, input_hash)

        return props

    async def extract_batch(
        self,
        meta_ad_ids: List[str],
        brand_id: str,
        org_id: str,
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Extract visual properties for multiple ads.

        Returns:
            Dict mapping meta_ad_id → visual properties (or None).
        """
        results = {}
        for ad_id in meta_ad_ids:
            try:
                results[ad_id] = await self.extract(ad_id, brand_id, org_id)
            except Exception as e:
                logger.error(f"Batch extraction failed for {ad_id}: {e}")
                results[ad_id] = None
        return results

    def _get_cached(self, meta_ad_id: str, brand_id: str) -> Optional[Dict[str, Any]]:
        """Check ad_visual_properties cache."""
        try:
            result = (
                self.supabase.table("ad_visual_properties")
                .select("*")
                .eq("meta_ad_id", meta_ad_id)
                .eq("brand_id", str(brand_id))
                .eq("prompt_version", PROMPT_VERSION)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return self._row_to_props(row)
        except Exception as e:
            logger.warning(f"Cache lookup failed for {meta_ad_id}: {e}")
        return None

    async def _fetch_image(self, meta_ad_id: str, brand_id: str) -> tuple:
        """Fetch ad image bytes. Tries stored asset → thumbnail → None.

        Returns:
            (image_bytes, source) or (None, None).
        """
        image_bytes = None
        source = None

        # 1. Try stored image from meta_ad_assets
        try:
            asset_result = (
                self.supabase.table("meta_ad_assets")
                .select("storage_path, source_url")
                .eq("meta_ad_id", meta_ad_id)
                .eq("asset_type", "image")
                .eq("status", "downloaded")
                .limit(1)
                .execute()
            )
            if asset_result.data:
                storage_path = asset_result.data[0].get("storage_path")
                if storage_path:
                    try:
                        data = self.supabase.storage.from_("meta-ad-assets").download(storage_path)
                        if data:
                            image_bytes = data
                            source = "stored"
                            logger.debug(f"Using stored image for {meta_ad_id}")
                    except Exception as dl_err:
                        logger.warning(f"Failed to download stored image for {meta_ad_id}: {dl_err}")
        except Exception as e:
            logger.warning(f"Asset lookup failed for {meta_ad_id}: {e}")

        # 2. Try thumbnail URL from facebook_ads table
        if not image_bytes:
            try:
                fb_result = (
                    self.supabase.table("facebook_ads")
                    .select("thumbnail_url")
                    .eq("ad_id", meta_ad_id)
                    .limit(1)
                    .execute()
                )
                thumbnail_url = None
                if fb_result.data:
                    thumbnail_url = fb_result.data[0].get("thumbnail_url")

                if thumbnail_url:
                    import urllib.request
                    try:
                        with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                            image_bytes = response.read()
                        if image_bytes:
                            source = "thumbnail"
                    except Exception as img_err:
                        logger.warning(f"Failed to download thumbnail for {meta_ad_id}: {img_err}")
            except Exception as e:
                logger.warning(f"Thumbnail lookup failed for {meta_ad_id}: {e}")

        return image_bytes, source

    def _compute_input_hash(self, image_bytes: bytes) -> str:
        """Compute SHA256 hash of image for dedup."""
        return hashlib.sha256(image_bytes).hexdigest()

    def _parse_and_validate(self, result_text: str) -> Optional[Dict[str, Any]]:
        """Parse Gemini JSON response and validate enum values."""
        import json

        # Strip markdown code fences if present
        text = result_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            props = json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse visual extraction JSON: {text[:200]}")
            return None

        if not isinstance(props, dict):
            return None

        # Validate and clamp enum fields
        for field, valid_values in VALID_ENUMS.items():
            if field in props:
                val = props[field]
                if val is not None and val not in valid_values:
                    # Try lowercase
                    lower_val = str(val).lower().replace(" ", "_")
                    if lower_val in valid_values:
                        props[field] = lower_val
                    else:
                        logger.warning(f"Invalid enum {field}={val}, setting to None")
                        props[field] = None

        # Clamp float fields to 0-1
        for field in ("visual_quality_score", "thumb_stop_prediction"):
            if field in props and props[field] is not None:
                try:
                    props[field] = max(0.0, min(1.0, float(props[field])))
                except (TypeError, ValueError):
                    props[field] = None

        # Ensure headline_word_count is int
        if "headline_word_count" in props:
            try:
                props["headline_word_count"] = int(props["headline_word_count"])
            except (TypeError, ValueError):
                props["headline_word_count"] = 0

        # Ensure face_count is int
        if "face_count" in props:
            try:
                props["face_count"] = int(props["face_count"])
            except (TypeError, ValueError):
                props["face_count"] = 0

        return props

    def _store(
        self,
        meta_ad_id: str,
        brand_id: str,
        org_id: str,
        props: Dict[str, Any],
        input_hash: str,
    ) -> None:
        """Store extracted visual properties in ad_visual_properties table."""
        import json

        row = {
            "organization_id": org_id,
            "brand_id": str(brand_id),
            "meta_ad_id": meta_ad_id,
            "contrast_level": props.get("contrast_level"),
            "color_palette_type": props.get("color_palette_type"),
            "dominant_colors": json.dumps(props.get("dominant_colors")) if props.get("dominant_colors") else None,
            "text_density": props.get("text_density"),
            "headline_word_count": props.get("headline_word_count"),
            "visual_hierarchy": props.get("visual_hierarchy"),
            "composition_style": props.get("composition_style"),
            "face_presence": props.get("face_presence", False),
            "face_count": props.get("face_count", 0),
            "face_emotion": props.get("face_emotion"),
            "person_framing": props.get("person_framing"),
            "product_visible": props.get("product_visible", False),
            "product_prominence": props.get("product_prominence"),
            "before_after_present": props.get("before_after_present", False),
            "headline_style": props.get("headline_style"),
            "cta_visual_treatment": props.get("cta_visual_treatment"),
            "visual_quality_score": props.get("visual_quality_score"),
            "thumb_stop_prediction": props.get("thumb_stop_prediction"),
            "raw_extraction": json.dumps(props),
            "model_used": getattr(self.gemini, "model_name", "gemini") if self.gemini else None,
            "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash,
        }

        try:
            self.supabase.table("ad_visual_properties").upsert(
                row, on_conflict="meta_ad_id,brand_id,prompt_version"
            ).execute()
        except Exception as e:
            logger.error(f"Failed to store visual properties for {meta_ad_id}: {e}")

    def _resolve_org_id(self, org_id: str, brand_id: str) -> str:
        """Resolve 'all' org_id to a real UUID from the brand."""
        if org_id != "all":
            return org_id
        try:
            row = (
                self.supabase.table("brands")
                .select("organization_id")
                .eq("id", str(brand_id))
                .limit(1)
                .execute()
            )
            if row.data:
                return row.data[0]["organization_id"]
        except Exception as e:
            logger.warning(f"Failed to resolve org_id for brand {brand_id}: {e}")
        return org_id

    def _row_to_props(self, row: dict) -> Dict[str, Any]:
        """Convert a DB row to a visual properties dict."""
        import json

        # If raw_extraction is stored, use it as the canonical source
        raw = row.get("raw_extraction")
        if raw:
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
            elif isinstance(raw, dict):
                return raw

        # Fallback: reconstruct from individual columns
        return {
            "contrast_level": row.get("contrast_level"),
            "color_palette_type": row.get("color_palette_type"),
            "dominant_colors": row.get("dominant_colors"),
            "text_density": row.get("text_density"),
            "headline_word_count": row.get("headline_word_count"),
            "visual_hierarchy": row.get("visual_hierarchy"),
            "composition_style": row.get("composition_style"),
            "face_presence": row.get("face_presence"),
            "face_count": row.get("face_count"),
            "face_emotion": row.get("face_emotion"),
            "person_framing": row.get("person_framing"),
            "product_visible": row.get("product_visible"),
            "product_prominence": row.get("product_prominence"),
            "before_after_present": row.get("before_after_present"),
            "headline_style": row.get("headline_style"),
            "cta_visual_treatment": row.get("cta_visual_treatment"),
            "visual_quality_score": row.get("visual_quality_score"),
            "thumb_stop_prediction": row.get("thumb_stop_prediction"),
        }
