"""Layer 1: ClassifierService — Awareness classification for ad creatives.

Classifies ads by awareness level, creative format, and congruence.
Produces immutable classification snapshots stored in ad_creative_classifications.

Classification sources (in priority order):
1. existing_brand_ad_analysis — Reuse existing Gemini analysis from brand research
2. gemini_light — Lightweight Gemini classification from thumbnail + copy

Reclassification triggers:
- force=True (explicit user request)
- now > stale_after (time-based staleness)
- input_hash changed (ad creative was updated)
- prompt_version changed (batch re-run)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from .helpers import _safe_numeric
from .models import AwarenessLevel, CreativeClassification, CreativeFormat

logger = logging.getLogger(__name__)

# Default staleness: reclassify after 30 days
DEFAULT_STALE_DAYS = 30

# Lightweight classification prompt for Gemini
CLASSIFICATION_PROMPT = """Analyze this ad creative and return a JSON classification.

Given the ad thumbnail image and copy text below, classify:

Ad Copy:
{ad_copy}

Return ONLY valid JSON with these fields:
{{
    "creative_awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",
    "creative_awareness_confidence": 0.0-1.0,
    "creative_format": "video_ugc|video_professional|video_testimonial|video_demo|image_static|image_before_after|image_testimonial|image_product|carousel|collection|other",
    "creative_angle": "Brief description of the advertising angle",
    "copy_awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",
    "copy_awareness_confidence": 0.0-1.0,
    "hook_type": "curiosity|fear|benefit|social_proof|urgency|transformation|question|statistic|testimonial",
    "primary_cta": "The main call-to-action text"
}}

Return ONLY the JSON object, no other text."""


class ClassifierService:
    """Classifies ad creatives by awareness level and format.

    Produces immutable classification snapshots. New classifications always
    create new rows; old rows are never overwritten.
    """

    CURRENT_PROMPT_VERSION = "v1"
    CURRENT_SCHEMA_VERSION = "1.0"

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance for DB operations.
        """
        self.supabase = supabase_client

    async def classify_ad(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        force: bool = False,
    ) -> CreativeClassification:
        """Classify a single ad's creative, copy, and landing page awareness.

        run_id is required — every classification is run-scoped.
        Code-level dedup: queries for existing row matching
        (meta_ad_id, brand_id, prompt_version, schema_version, input_hash, source).
        If match exists and not stale → reuse. Otherwise → create new immutable row.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID (required).
            force: Force reclassification even if fresh.

        Returns:
            CreativeClassification model.
        """
        assert run_id is not None, "run_id is required for classification"

        # Gather ad data (thumbnail, copy, landing page)
        ad_data = await self._fetch_ad_data(meta_ad_id, brand_id)
        thumbnail_url = ad_data.get("thumbnail_url", "")
        ad_copy = ad_data.get("ad_copy", "")
        lp_id = ad_data.get("landing_page_id")

        current_hash = self._compute_input_hash(thumbnail_url, ad_copy, str(lp_id) if lp_id else None)

        # Check for existing classification
        if not force:
            existing = await self._find_existing_classification(
                meta_ad_id, brand_id, current_hash
            )
            if existing:
                logger.debug(f"Reusing existing classification for {meta_ad_id}")
                return self._row_to_model(existing)

        # Try to extract from existing brand_ad_analysis first
        existing_analysis = await self._find_existing_analysis(meta_ad_id, brand_id)
        if existing_analysis:
            classification_data = self._extract_from_existing_analysis(existing_analysis)
            source = "existing_brand_ad_analysis"
        else:
            # Classify with Gemini
            classification_data = await self._classify_with_gemini(
                thumbnail_url, ad_copy, ad_data.get("lp_data")
            )
            source = "gemini_light"

        # Build classification record
        now = datetime.now(timezone.utc)
        record = {
            "organization_id": str(org_id),
            "brand_id": str(brand_id),
            "meta_ad_id": meta_ad_id,
            "run_id": str(run_id),
            "creative_awareness_level": classification_data.get("creative_awareness_level"),
            "creative_awareness_confidence": classification_data.get("creative_awareness_confidence"),
            "creative_format": classification_data.get("creative_format"),
            "creative_angle": classification_data.get("creative_angle"),
            "video_length_bucket": classification_data.get("video_length_bucket"),
            "copy_awareness_level": classification_data.get("copy_awareness_level"),
            "copy_awareness_confidence": classification_data.get("copy_awareness_confidence"),
            "hook_type": classification_data.get("hook_type"),
            "primary_cta": classification_data.get("primary_cta"),
            "landing_page_awareness_level": classification_data.get("landing_page_awareness_level"),
            "landing_page_confidence": classification_data.get("landing_page_confidence"),
            "landing_page_id": str(lp_id) if lp_id else None,
            "congruence_score": classification_data.get("congruence_score"),
            "congruence_notes": classification_data.get("congruence_notes"),
            "source": source,
            "prompt_version": self.CURRENT_PROMPT_VERSION,
            "schema_version": self.CURRENT_SCHEMA_VERSION,
            "input_hash": current_hash,
            "model_used": classification_data.get("model_used"),
            "raw_classification": classification_data.get("raw_classification", {}),
            "classified_at": now.isoformat(),
            "stale_after": (now + timedelta(days=DEFAULT_STALE_DAYS)).isoformat(),
        }

        # Compute congruence if we have both creative and copy levels
        if record["creative_awareness_level"] and record["copy_awareness_level"]:
            score, notes = self._compute_congruence(
                record["creative_awareness_level"],
                record["copy_awareness_level"],
                record.get("landing_page_awareness_level"),
            )
            record["congruence_score"] = score
            record["congruence_notes"] = notes

        # Insert immutable row
        result = self.supabase.table("ad_creative_classifications").insert(record).execute()
        if result.data:
            return self._row_to_model(result.data[0])

        logger.error(f"Failed to insert classification for {meta_ad_id}")
        return self._dict_to_model(record, brand_id, org_id)

    async def classify_batch(
        self,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        meta_ad_ids: List[str],
        max_new: int = 200,
    ) -> List[CreativeClassification]:
        """Classify a batch of ads, prioritizing by spend.

        Sorts unclassified ads by spend descending. Caps new Gemini calls
        at max_new to prevent runaway costs.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID.
            meta_ad_ids: List of meta ad IDs to classify.
            max_new: Max new Gemini classifications (from RunConfig).

        Returns:
            List of CreativeClassification models.
        """
        classifications: List[CreativeClassification] = []
        new_classification_count = 0

        # Sort ads by spend to prioritize high-spend ads
        spend_order = await self._get_ad_spend_order(brand_id, meta_ad_ids)
        sorted_ids = sorted(meta_ad_ids, key=lambda x: spend_order.get(x, 0), reverse=True)

        for meta_ad_id in sorted_ids:
            try:
                # Check if already classified (fresh)
                ad_data = await self._fetch_ad_data(meta_ad_id, brand_id)
                thumbnail_url = ad_data.get("thumbnail_url", "")
                ad_copy = ad_data.get("ad_copy", "")
                lp_id = ad_data.get("landing_page_id")
                current_hash = self._compute_input_hash(
                    thumbnail_url, ad_copy, str(lp_id) if lp_id else None
                )

                existing = await self._find_existing_classification(
                    meta_ad_id, brand_id, current_hash
                )
                if existing:
                    classifications.append(self._row_to_model(existing))
                    continue

                # Need new classification
                if new_classification_count >= max_new:
                    logger.warning(
                        f"Classification cap reached ({max_new}). "
                        f"Skipping {meta_ad_id} and remaining ads."
                    )
                    break

                classification = await self.classify_ad(
                    meta_ad_id, brand_id, org_id, run_id
                )
                classifications.append(classification)
                new_classification_count += 1

            except Exception as e:
                logger.error(f"Error classifying ad {meta_ad_id}: {e}")
                continue

        logger.info(
            f"Classified batch: {len(classifications)} total, "
            f"{new_classification_count} new Gemini calls"
        )
        return classifications

    async def get_latest_classification(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Optional[CreativeClassification]:
        """Return the most recent classification for an ad.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.

        Returns:
            Most recent CreativeClassification or None.
        """
        result = self.supabase.table("ad_creative_classifications").select("*").eq(
            "meta_ad_id", meta_ad_id
        ).eq(
            "brand_id", str(brand_id)
        ).order(
            "classified_at", desc=True
        ).limit(1).execute()

        if result.data:
            return self._row_to_model(result.data[0])
        return None

    async def get_classification_for_run(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        run_id: UUID,
        run_created_at: datetime,
    ) -> Optional[CreativeClassification]:
        """Get the classification to use for a specific run's diagnostics.

        Deterministic selection policy:
        1) Latest where run_id == run_id (same-run classification)
        2) Else latest where classified_at <= run_created_at (pre-run)
        Prevents diagnostics from referencing a future classification.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            run_id: Current run UUID.
            run_created_at: When the run was created.

        Returns:
            CreativeClassification or None.
        """
        # 1. Prefer same-run classification
        result = self.supabase.table("ad_creative_classifications").select("*").eq(
            "run_id", str(run_id)
        ).eq(
            "meta_ad_id", meta_ad_id
        ).eq(
            "brand_id", str(brand_id)
        ).order(
            "classified_at", desc=True
        ).limit(1).execute()

        if result.data:
            return self._row_to_model(result.data[0])

        # 2. Fallback: latest pre-run classification
        result = self.supabase.table("ad_creative_classifications").select("*").eq(
            "meta_ad_id", meta_ad_id
        ).eq(
            "brand_id", str(brand_id)
        ).lte(
            "classified_at", run_created_at.isoformat()
        ).order(
            "classified_at", desc=True
        ).limit(1).execute()

        if result.data:
            return self._row_to_model(result.data[0])

        return None

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _compute_input_hash(
        self,
        thumbnail_url: str,
        ad_copy: str,
        lp_id: Optional[str] = None,
    ) -> str:
        """Compute SHA256 hash of ad inputs for change detection.

        Args:
            thumbnail_url: Ad thumbnail URL.
            ad_copy: Ad copy text.
            lp_id: Landing page ID string (optional).

        Returns:
            Hex digest string.
        """
        content = f"{thumbnail_url or ''}|{ad_copy or ''}|{lp_id or ''}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _needs_new_classification(
        self,
        existing: Optional[Dict],
        current_input_hash: str,
        force: bool,
    ) -> bool:
        """Check if a new classification is needed.

        Returns True if:
        - force is True
        - No existing row for current (prompt_version, schema_version, input_hash, source)
        - Latest row is past stale_after

        Args:
            existing: Existing classification row dict (or None).
            current_input_hash: Current computed input hash.
            force: Force flag.

        Returns:
            True if new classification needed.
        """
        if force:
            return True
        if not existing:
            return True

        # Check staleness
        stale_after = existing.get("stale_after")
        if stale_after:
            try:
                stale_dt = datetime.fromisoformat(stale_after.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > stale_dt:
                    return True
            except (ValueError, TypeError):
                pass

        # Check input hash change
        if existing.get("input_hash") != current_input_hash:
            return True

        # Check prompt version change
        if existing.get("prompt_version") != self.CURRENT_PROMPT_VERSION:
            return True

        return False

    async def _find_existing_classification(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        current_input_hash: str,
    ) -> Optional[Dict]:
        """Find an existing classification that matches current parameters.

        Queries for matching (meta_ad_id, brand_id, prompt_version,
        schema_version, input_hash) and checks staleness.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            current_input_hash: Current input hash for change detection.

        Returns:
            Existing classification row dict or None.
        """
        result = self.supabase.table("ad_creative_classifications").select("*").eq(
            "meta_ad_id", meta_ad_id
        ).eq(
            "brand_id", str(brand_id)
        ).eq(
            "prompt_version", self.CURRENT_PROMPT_VERSION
        ).eq(
            "schema_version", self.CURRENT_SCHEMA_VERSION
        ).eq(
            "input_hash", current_input_hash
        ).order(
            "classified_at", desc=True
        ).limit(1).execute()

        if not result.data:
            return None

        row = result.data[0]
        if not self._needs_new_classification(row, current_input_hash, force=False):
            return row
        return None

    async def _fetch_ad_data(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Dict[str, Any]:
        """Fetch ad thumbnail, copy, and landing page data.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.

        Returns:
            Dict with thumbnail_url, ad_copy, landing_page_id, lp_data.
        """
        result = {}

        # Get thumbnail and ad copy from meta_ads_performance
        try:
            perf_result = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url, ad_name, meta_campaign_id"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).order(
                "date", desc=True
            ).limit(1).execute()

            if perf_result.data:
                row = perf_result.data[0]
                result["thumbnail_url"] = row.get("thumbnail_url", "")
                result["ad_name"] = row.get("ad_name", "")
                result["campaign_id"] = row.get("meta_campaign_id", "")
        except Exception as e:
            logger.warning(f"Error fetching performance data for {meta_ad_id}: {e}")

        # Try to get ad copy from facebook_ads via ad_archive_id match
        try:
            perf_archive = self.supabase.table("meta_ads_performance").select(
                "ad_archive_id"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).limit(1).execute()

            ad_archive_id = None
            if perf_archive.data:
                ad_archive_id = perf_archive.data[0].get("ad_archive_id")

            if ad_archive_id:
                fb_result = self.supabase.table("facebook_ads").select(
                    "id, snapshot"
                ).eq(
                    "ad_archive_id", str(ad_archive_id)
                ).limit(1).execute()

                if fb_result.data:
                    snapshot = fb_result.data[0].get("snapshot", {})
                    if isinstance(snapshot, str):
                        try:
                            snapshot = json.loads(snapshot)
                        except (json.JSONDecodeError, TypeError):
                            snapshot = {}
                    body_data = snapshot.get("body", {})
                    ad_copy = body_data.get("text", "") if isinstance(body_data, dict) else ""
                    headline = snapshot.get("title", "")
                    result["ad_copy"] = f"{headline}\n{ad_copy}".strip()
                    result["facebook_ad_id"] = fb_result.data[0].get("id")
        except Exception as e:
            logger.warning(f"Error fetching ad copy for {meta_ad_id}: {e}")

        # Use ad_name as fallback for ad_copy
        if not result.get("ad_copy"):
            result["ad_copy"] = result.get("ad_name", "")

        return result

    async def _find_existing_analysis(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Optional[Dict]:
        """Find existing brand_ad_analysis for this ad.

        Links through facebook_ads table via ad_archive_id.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.

        Returns:
            raw_response dict from brand_ad_analysis or None.
        """
        try:
            # Get facebook_ad_id via ad_archive_id linkage
            perf_result = self.supabase.table("meta_ads_performance").select(
                "ad_archive_id"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).limit(1).execute()

            if not perf_result.data:
                return None

            ad_archive_id = perf_result.data[0].get("ad_archive_id")
            if not ad_archive_id:
                return None

            # Find facebook_ads record
            fb_result = self.supabase.table("facebook_ads").select(
                "id"
            ).eq(
                "ad_archive_id", str(ad_archive_id)
            ).limit(1).execute()

            if not fb_result.data:
                return None

            facebook_ad_id = fb_result.data[0]["id"]

            # Find analysis
            analysis_result = self.supabase.table("brand_ad_analysis").select(
                "raw_response, analysis_type"
            ).eq(
                "facebook_ad_id", str(facebook_ad_id)
            ).eq(
                "brand_id", str(brand_id)
            ).order(
                "created_at", desc=True
            ).limit(1).execute()

            if analysis_result.data:
                return analysis_result.data[0].get("raw_response")

        except Exception as e:
            logger.warning(f"Error finding existing analysis for {meta_ad_id}: {e}")

        return None

    def _extract_from_existing_analysis(self, raw_response: Dict) -> Dict:
        """Extract classification fields from existing brand_ad_analysis.

        Normalizes existing Gemini analysis fields to our classification schema.

        Args:
            raw_response: The raw_response JSONB from brand_ad_analysis.

        Returns:
            Dict with normalized classification fields.
        """
        if not isinstance(raw_response, dict):
            return {}

        ad_structure = raw_response.get("advertising_structure", {})
        if not isinstance(ad_structure, dict):
            ad_structure = {}

        # Extract awareness level
        awareness = ad_structure.get("awareness_level", "")
        creative_awareness = self._normalize_awareness(awareness)

        # Extract format type
        format_type = raw_response.get("format_type", "")
        video_style = raw_response.get("video_style", {})
        if isinstance(video_style, dict) and video_style.get("format"):
            format_type = video_style["format"]
        creative_format = self._normalize_format(format_type)

        # Extract angle
        creative_angle = ad_structure.get("advertising_angle", "")

        # Extract hook type
        hooks = raw_response.get("hooks", [])
        hook_data = raw_response.get("hook", {})
        hook_type = None
        if isinstance(hooks, list) and hooks:
            hook_type = hooks[0].get("hook_type") if isinstance(hooks[0], dict) else None
        elif isinstance(hook_data, dict):
            hook_type = hook_data.get("hook_type")

        return {
            "creative_awareness_level": creative_awareness,
            "creative_awareness_confidence": 0.8,  # High confidence for full analysis
            "creative_format": creative_format,
            "creative_angle": creative_angle,
            "copy_awareness_level": creative_awareness,  # Same for existing analysis
            "copy_awareness_confidence": 0.7,
            "hook_type": hook_type,
            "model_used": "existing_analysis",
            "raw_classification": raw_response,
        }

    async def _classify_with_gemini(
        self,
        thumbnail_url: str,
        ad_copy: str,
        lp_data: Optional[Dict] = None,
    ) -> Dict:
        """Run lightweight Gemini classification on ad thumbnail + copy.

        Args:
            thumbnail_url: URL to ad thumbnail image.
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional).

        Returns:
            Dict with classification fields.
        """
        try:
            from ...services.gemini_service import GeminiService

            gemini = GeminiService()
            prompt = CLASSIFICATION_PROMPT.format(ad_copy=ad_copy or "(no copy available)")

            if thumbnail_url:
                # Download thumbnail and classify with image
                import base64
                import urllib.request

                try:
                    with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                        image_bytes = response.read()
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                    result_text = await gemini.analyze_image(image_b64, prompt)
                except Exception as img_err:
                    logger.warning(f"Failed to download thumbnail, classifying from copy only: {img_err}")
                    result_text = await gemini.generate_text(prompt)
            else:
                # No thumbnail, classify from copy only
                result_text = await gemini.generate_text(prompt)

            # Parse JSON response
            parsed = self._parse_gemini_response(result_text)
            parsed["model_used"] = "gemini_light"
            parsed["raw_classification"] = parsed.copy()
            return parsed

        except Exception as e:
            logger.error(f"Gemini classification failed: {e}")
            return {
                "creative_awareness_level": None,
                "creative_format": None,
                "model_used": "gemini_light_failed",
                "raw_classification": {"error": str(e)},
            }

    def _parse_gemini_response(self, text: str) -> Dict:
        """Parse Gemini JSON response, handling markdown code blocks.

        Args:
            text: Raw text response from Gemini.

        Returns:
            Parsed dict with normalized fields.
        """
        if not text:
            return {}

        # Strip markdown code blocks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Gemini classification response")
            return {}

        # Normalize enum values
        result = {}
        result["creative_awareness_level"] = self._normalize_awareness(
            data.get("creative_awareness_level")
        )
        result["creative_awareness_confidence"] = _safe_numeric(
            data.get("creative_awareness_confidence")
        )
        result["creative_format"] = self._normalize_format(
            data.get("creative_format")
        )
        result["creative_angle"] = data.get("creative_angle")
        result["copy_awareness_level"] = self._normalize_awareness(
            data.get("copy_awareness_level")
        )
        result["copy_awareness_confidence"] = _safe_numeric(
            data.get("copy_awareness_confidence")
        )
        result["hook_type"] = data.get("hook_type")
        result["primary_cta"] = data.get("primary_cta")

        return result

    def _normalize_awareness(self, value: Any) -> Optional[str]:
        """Normalize awareness level to valid enum value.

        Args:
            value: Raw awareness level string.

        Returns:
            Valid AwarenessLevel value or None.
        """
        if not value or not isinstance(value, str):
            return None
        normalized = value.lower().strip().replace(" ", "_").replace("-", "_")
        valid = {level.value for level in AwarenessLevel}
        return normalized if normalized in valid else None

    def _normalize_format(self, value: Any) -> Optional[str]:
        """Normalize creative format to valid enum value.

        Maps existing brand_research format types to our enum.

        Args:
            value: Raw format type string.

        Returns:
            Valid CreativeFormat value or None.
        """
        if not value or not isinstance(value, str):
            return None
        normalized = value.lower().strip().replace(" ", "_").replace("-", "_")

        # Map existing brand_research format types
        format_mapping = {
            "ugc": "video_ugc",
            "ugc_style": "video_ugc",
            "professional": "video_professional",
            "testimonial": "video_testimonial",
            "demo": "video_demo",
            "talking_head": "video_professional",
            "mixed": "other",
            "static": "image_static",
            "image_static": "image_static",
            "before_after": "image_before_after",
            "image_before_after": "image_before_after",
            "product_showcase": "image_product",
            "image_product": "image_product",
            "image_testimonial": "image_testimonial",
            "quote_card": "image_static",
            "meme": "image_static",
            "lifestyle": "image_static",
            "comparison": "image_before_after",
            "carousel": "carousel",
            "collection": "collection",
        }

        # Check direct match first
        valid = {fmt.value for fmt in CreativeFormat}
        if normalized in valid:
            return normalized

        # Try mapping
        return format_mapping.get(normalized, "other")

    def _compute_congruence(
        self,
        creative_level: str,
        copy_level: str,
        lp_level: Optional[str] = None,
    ) -> tuple:
        """Compute congruence score between creative, copy, and LP awareness levels.

        Score = 1.0 - (max_ordinal_gap / 4).
        Uses 2-way score when LP data missing.

        Args:
            creative_level: Creative awareness level.
            copy_level: Copy awareness level.
            lp_level: Landing page awareness level (optional).

        Returns:
            Tuple of (score, notes).
        """
        ordinal = {
            "unaware": 1,
            "problem_aware": 2,
            "solution_aware": 3,
            "product_aware": 4,
            "most_aware": 5,
        }

        creative_ord = ordinal.get(creative_level, 0)
        copy_ord = ordinal.get(copy_level, 0)

        if creative_ord == 0 or copy_ord == 0:
            return None, "Could not compute congruence: invalid awareness levels"

        if lp_level and ordinal.get(lp_level, 0) > 0:
            lp_ord = ordinal[lp_level]
            max_gap = max(
                abs(creative_ord - copy_ord),
                abs(creative_ord - lp_ord),
                abs(copy_ord - lp_ord),
            )
            score = round(1.0 - (max_gap / 4), 3)
            if max_gap == 0:
                notes = "Perfect alignment across creative, copy, and landing page"
            elif max_gap <= 1:
                notes = "Good alignment (1-step gap)"
            else:
                notes = f"Misalignment detected ({max_gap}-step gap across creative/copy/LP)"
        else:
            max_gap = abs(creative_ord - copy_ord)
            score = round(1.0 - (max_gap / 4), 3)
            if max_gap == 0:
                notes = "Perfect creative-copy alignment (no LP data)"
            elif max_gap <= 1:
                notes = "Good creative-copy alignment (no LP data)"
            else:
                notes = f"Creative-copy misalignment ({max_gap}-step gap, no LP data)"

        return score, notes

    async def _get_ad_spend_order(
        self,
        brand_id: UUID,
        meta_ad_ids: List[str],
    ) -> Dict[str, float]:
        """Get total spend per ad for prioritization.

        Args:
            brand_id: Brand UUID.
            meta_ad_ids: List of meta ad IDs.

        Returns:
            Dict mapping meta_ad_id to total spend.
        """
        try:
            result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, spend"
            ).eq(
                "brand_id", str(brand_id)
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).execute()

            spend_map: Dict[str, float] = {}
            for row in result.data or []:
                ad_id = row.get("meta_ad_id")
                spend = _safe_numeric(row.get("spend"))
                if ad_id and spend is not None:
                    spend_map[ad_id] = spend_map.get(ad_id, 0) + spend
            return spend_map

        except Exception as e:
            logger.warning(f"Error fetching spend order: {e}")
            return {}

    def _row_to_model(self, row: Dict) -> CreativeClassification:
        """Convert a DB row dict to a CreativeClassification model.

        Args:
            row: Database row as dict.

        Returns:
            CreativeClassification model.
        """
        return CreativeClassification(
            id=row.get("id"),
            meta_ad_id=row.get("meta_ad_id", ""),
            brand_id=UUID(row["brand_id"]) if row.get("brand_id") else UUID(int=0),
            organization_id=UUID(row["organization_id"]) if row.get("organization_id") else None,
            run_id=UUID(row["run_id"]) if row.get("run_id") else None,
            creative_awareness_level=row.get("creative_awareness_level"),
            creative_awareness_confidence=_safe_numeric(row.get("creative_awareness_confidence")),
            creative_format=row.get("creative_format"),
            creative_angle=row.get("creative_angle"),
            video_length_bucket=row.get("video_length_bucket"),
            copy_awareness_level=row.get("copy_awareness_level"),
            copy_awareness_confidence=_safe_numeric(row.get("copy_awareness_confidence")),
            hook_type=row.get("hook_type"),
            primary_cta=row.get("primary_cta"),
            landing_page_awareness_level=row.get("landing_page_awareness_level"),
            landing_page_confidence=_safe_numeric(row.get("landing_page_confidence")),
            landing_page_id=UUID(row["landing_page_id"]) if row.get("landing_page_id") else None,
            congruence_score=_safe_numeric(row.get("congruence_score")),
            congruence_notes=row.get("congruence_notes"),
            source=row.get("source", "gemini_light"),
            prompt_version=row.get("prompt_version", "v1"),
            schema_version=row.get("schema_version", "1.0"),
            input_hash=row.get("input_hash"),
            model_used=row.get("model_used"),
            raw_classification=row.get("raw_classification", {}),
            classified_at=row.get("classified_at"),
            stale_after=row.get("stale_after"),
        )

    def _dict_to_model(
        self, record: Dict, brand_id: UUID, org_id: UUID
    ) -> CreativeClassification:
        """Convert an insert record dict to a model (fallback when insert fails).

        Args:
            record: Insert record dict.
            brand_id: Brand UUID.
            org_id: Organization UUID.

        Returns:
            CreativeClassification model.
        """
        return CreativeClassification(
            meta_ad_id=record.get("meta_ad_id", ""),
            brand_id=brand_id,
            organization_id=org_id,
            run_id=UUID(record["run_id"]) if record.get("run_id") else None,
            creative_awareness_level=record.get("creative_awareness_level"),
            creative_awareness_confidence=_safe_numeric(record.get("creative_awareness_confidence")),
            creative_format=record.get("creative_format"),
            creative_angle=record.get("creative_angle"),
            source=record.get("source", "gemini_light"),
            prompt_version=record.get("prompt_version", "v1"),
            schema_version=record.get("schema_version", "1.0"),
            input_hash=record.get("input_hash"),
        )
