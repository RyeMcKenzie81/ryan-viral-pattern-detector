"""Layer 1: ClassifierService — Awareness classification for ad creatives.

Classifies ads by awareness level, creative format, and congruence.
Produces immutable classification snapshots stored in ad_creative_classifications.

Classification sources (in priority order):
1. existing_brand_ad_analysis — Reuse existing Gemini analysis from brand research
2. gemini_video — Video analysis via Gemini Files API (first 3-5 seconds)
3. gemini_light — Lightweight Gemini classification from image + copy

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
import os
import tempfile
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

# Video-specific classification prompt — focuses on the first 3-5 seconds
VIDEO_CLASSIFICATION_PROMPT = """Analyze this video ad creative and return a JSON classification.

Focus on the FIRST 3-5 SECONDS of the video to determine awareness level.
The opening hook, framing, and first statement are the primary signals.

Also consider the ad copy below:

Ad Copy:
{ad_copy}

Return ONLY valid JSON with these fields:
{{
    "creative_awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",
    "creative_awareness_confidence": 0.0-1.0,
    "creative_format": "video_ugc|video_professional|video_testimonial|video_demo|other",
    "creative_angle": "Brief description of the advertising angle",
    "video_duration_sec": <integer seconds of the full video>,
    "hook_type": "curiosity|fear|benefit|social_proof|urgency|transformation|question|statistic|testimonial",
    "hook_transcript": "Exact words spoken or shown in the first 3-5 seconds",
    "copy_awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",
    "copy_awareness_confidence": 0.0-1.0,
    "primary_cta": "The main call-to-action text"
}}

Return ONLY the JSON object, no other text."""


class ClassifierService:
    """Classifies ad creatives by awareness level and format.

    Produces immutable classification snapshots. New classifications always
    create new rows; old rows are never overwritten.
    """

    CURRENT_PROMPT_VERSION = "v2"
    CURRENT_SCHEMA_VERSION = "1.0"

    def __init__(self, supabase_client, gemini_service=None, meta_ads_service=None):
        """Initialize with Supabase client and optional services.

        Args:
            supabase_client: Supabase client instance for DB operations.
            gemini_service: Optional GeminiService instance with configured
                rate limiting and usage tracking. If not provided, a new
                instance will be created per classification call (not
                recommended for production use).
            meta_ads_service: Optional MetaAdsService instance for fetching
                video source URLs. Required for video classification.
        """
        self.supabase = supabase_client
        self._gemini = gemini_service
        self._meta_ads = meta_ads_service

    async def classify_ad(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        force: bool = False,
        video_budget_remaining: int = 0,
    ) -> CreativeClassification:
        """Classify a single ad's creative, copy, and landing page awareness.

        run_id is required — every classification is run-scoped.
        Code-level dedup: queries for existing row matching
        (meta_ad_id, brand_id, prompt_version, schema_version, input_hash, source).
        If match exists and not stale → reuse. Otherwise → create new immutable row.

        Fallback chain:
        1. existing_brand_ad_analysis — reuse full Gemini analysis
        2. gemini_video — download video → Gemini Files API (if video + budget)
        3. gemini_light — image + copy classification
        4. copy-only — if no thumbnail available

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID (required).
            force: Force reclassification even if fresh.
            video_budget_remaining: How many video classifications are still
                allowed in this run. 0 means skip video classification.

        Returns:
            CreativeClassification model.
        """
        assert run_id is not None, "run_id is required for classification"

        # Gather ad data (thumbnail, copy, landing page, video metadata)
        ad_data = await self._fetch_ad_data(meta_ad_id, brand_id)
        thumbnail_url = ad_data.get("thumbnail_url", "")
        ad_copy = ad_data.get("ad_copy", "")
        lp_id = ad_data.get("landing_page_id")
        video_id = ad_data.get("meta_video_id")
        is_video = ad_data.get("is_video", False)

        current_hash = self._compute_input_hash(
            thumbnail_url, ad_copy,
            str(lp_id) if lp_id else None,
            video_id=video_id,
        )

        # Check for existing classification
        if not force:
            existing = await self._find_existing_classification(
                meta_ad_id, brand_id, current_hash
            )
            if existing:
                logger.debug(f"Reusing existing classification for {meta_ad_id}")
                return self._row_to_model(existing)

        # Classification fallback chain
        classification_data = None
        source = None

        # 1. Try to extract from existing brand_ad_analysis
        existing_analysis = await self._find_existing_analysis(meta_ad_id, brand_id)
        if existing_analysis:
            classification_data = self._extract_from_existing_analysis(existing_analysis)
            source = "existing_brand_ad_analysis"

        # 2. Try video classification if this is a video ad with budget
        if not classification_data and is_video and video_id and video_budget_remaining > 0:
            logger.info(f"Attempting video classification for {meta_ad_id} (video_id={video_id})")
            video_result = await self._classify_video_with_gemini(
                video_id, ad_copy, ad_data.get("lp_data"),
                meta_ad_id=meta_ad_id, brand_id=brand_id,
            )
            if video_result:
                classification_data = video_result
                source = "gemini_video"

        # 3. Fallback to image+copy classification
        if not classification_data:
            classification_data = await self._classify_with_gemini(
                thumbnail_url, ad_copy, ad_data.get("lp_data"),
                meta_ad_id=meta_ad_id,
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
            "video_duration_sec": classification_data.get("video_duration_sec"),
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
        max_video: int = 5,
    ) -> List[CreativeClassification]:
        """Classify a batch of ads, prioritizing by spend.

        Sorts unclassified ads by spend descending. Caps new Gemini calls
        at max_new to prevent runaway costs. Video classifications are
        additionally capped at max_video per run.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID.
            meta_ad_ids: List of meta ad IDs to classify.
            max_new: Max new Gemini classifications (from RunConfig).
            max_video: Max video classifications per run (from RunConfig).

        Returns:
            List of CreativeClassification models.
        """
        classifications: List[CreativeClassification] = []
        new_classification_count = 0
        video_classification_count = 0

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
                video_id = ad_data.get("meta_video_id")
                current_hash = self._compute_input_hash(
                    thumbnail_url, ad_copy,
                    str(lp_id) if lp_id else None,
                    video_id=video_id,
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

                video_budget = max_video - video_classification_count
                classification = await self.classify_ad(
                    meta_ad_id, brand_id, org_id, run_id,
                    video_budget_remaining=video_budget,
                )
                classifications.append(classification)
                new_classification_count += 1

                # Track video classifications
                if classification.source == "gemini_video":
                    video_classification_count += 1

            except Exception as e:
                logger.error(f"Error classifying ad {meta_ad_id}: {e}")
                continue

        logger.info(
            f"Classified batch: {len(classifications)} total, "
            f"{new_classification_count} new Gemini calls, "
            f"{video_classification_count} video classifications"
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
        video_id: Optional[str] = None,
    ) -> str:
        """Compute SHA256 hash of ad inputs for change detection.

        Args:
            thumbnail_url: Ad thumbnail URL.
            ad_copy: Ad copy text.
            lp_id: Landing page ID string (optional).
            video_id: Meta video ID (optional). Including this forces
                reclassification for video ads on first run after deployment.

        Returns:
            Hex digest string.
        """
        content = f"{thumbnail_url or ''}|{ad_copy or ''}|{lp_id or ''}|{video_id or ''}"
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
        """Fetch ad thumbnail, copy, video metadata, and landing page data.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.

        Returns:
            Dict with thumbnail_url, ad_copy, landing_page_id, lp_data,
            meta_video_id, is_video.
        """
        result = {}

        # Get thumbnail, ad copy, and video metadata from meta_ads_performance
        try:
            perf_result = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url, ad_name, meta_campaign_id, meta_video_id, is_video, video_views"
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
                result["meta_video_id"] = row.get("meta_video_id")
                result["is_video"] = row.get("is_video", False)

                # Bootstrap: if meta_video_id is NULL but video_views > 0,
                # this is likely a video ad whose metadata hasn't been populated yet
                video_views = _safe_numeric(row.get("video_views"))
                if not result["meta_video_id"] and video_views and video_views > 0:
                    result["is_video"] = True
                    logger.info(
                        f"Ad {meta_ad_id} has video_views={video_views} but no "
                        f"meta_video_id — flagging as likely video"
                    )
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

    async def _find_asset_in_storage(
        self,
        meta_ad_id: str,
        asset_type: str = "video",
    ) -> Optional[str]:
        """Find a pre-downloaded ad asset in meta_ad_assets.

        Assets are downloaded by MetaAdsService.download_new_ad_assets()
        during the nightly meta_sync job or via the manual "Download Assets"
        button on the Ad Performance page.

        Args:
            meta_ad_id: Meta ad ID string.
            asset_type: 'video' or 'image'.

        Returns:
            Supabase storage path (e.g. "meta-ad-assets/{brand}/{ad}.mp4")
            or None if not found.
        """
        try:
            result = self.supabase.table("meta_ad_assets").select(
                "storage_path"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "asset_type", asset_type
            ).eq(
                "status", "downloaded"
            ).limit(1).execute()

            if result.data:
                return result.data[0]["storage_path"]
            return None

        except Exception as e:
            logger.warning(f"Error looking up {asset_type} in storage for {meta_ad_id}: {e}")
            return None

    async def _download_from_storage(self, storage_path: str) -> Optional[bytes]:
        """Download a file from Supabase storage.

        Args:
            storage_path: Full storage path (e.g. "scraped-assets/uuid/video.mp4").

        Returns:
            File contents as bytes, or None on failure.
        """
        try:
            # Split "bucket/path" on first "/"
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                logger.warning(f"Invalid storage path format: {storage_path}")
                return None

            bucket, path = parts
            content = self.supabase.storage.from_(bucket).download(path)
            return content

        except Exception as e:
            logger.warning(f"Failed to download from storage {storage_path}: {e}")
            return None

    async def _classify_video_with_gemini(
        self,
        video_id: str,
        ad_copy: str,
        lp_data: Optional[Dict] = None,
        meta_ad_id: Optional[str] = None,
        brand_id: Optional[UUID] = None,
    ) -> Optional[Dict]:
        """Classify a video ad with Gemini Files API.

        Video must be pre-downloaded into meta_ad_assets by the nightly
        meta_sync job or the manual "Download Assets" button. If the video
        isn't in storage, returns None → caller falls back to image+copy.

        Args:
            video_id: Meta video ID from AdCreative.
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional, unused currently).
            meta_ad_id: Meta ad ID for looking up video in storage.
            brand_id: Brand UUID (unused, kept for interface compat).

        Returns:
            Dict with classification fields, or None on failure.
        """
        temp_path = None
        gemini_file = None
        client = None

        try:
            from google import genai

            # Look up pre-downloaded video in meta_ad_assets
            if not meta_ad_id:
                logger.warning(f"No meta_ad_id provided for video classification (video_id={video_id})")
                return None

            storage_path = await self._find_asset_in_storage(meta_ad_id, "video")
            if not storage_path:
                logger.info(
                    f"Video not in storage for {meta_ad_id} — "
                    f"run 'Download Assets' or wait for nightly sync"
                )
                return None

            video_content = await self._download_from_storage(storage_path)
            if not video_content:
                logger.warning(f"Failed to download video from storage: {storage_path}")
                return None

            logger.info(f"Loaded video from storage for {meta_ad_id}: {len(video_content) / 1024 / 1024:.1f}MB")

            # 3. Write to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_file.write(video_content)
            temp_file.close()
            temp_path = temp_file.name

            # 4. Upload to Gemini Files API
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("GEMINI_API_KEY not set — cannot classify video")
                return None

            client = genai.Client(api_key=api_key)
            logger.info(f"Uploading video to Gemini Files API ({meta_ad_id or video_id})")
            gemini_file = client.files.upload(file=str(temp_path))
            logger.info(f"Uploaded to Gemini: {gemini_file.uri}")

            # 5. Wait for processing (up to 120s, polling every 2s)
            max_wait = 120
            wait_time = 0
            while gemini_file.state.name == "PROCESSING" and wait_time < max_wait:
                time_module.sleep(2)
                wait_time += 2
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name == "FAILED":
                logger.warning(f"Gemini video processing failed for {video_id}")
                return None
            if gemini_file.state.name == "PROCESSING":
                logger.warning(f"Gemini video processing timed out for {video_id}")
                return None

            # 6. Generate classification
            prompt = VIDEO_CLASSIFICATION_PROMPT.format(
                ad_copy=ad_copy or "(no copy available)"
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[gemini_file, prompt],
            )

            # 7. Parse response
            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_gemini_response(result_text)
            if not parsed:
                logger.warning(f"Empty/unparseable video classification for {video_id}")
                return None

            # Extract video_duration_sec and compute video_length_bucket
            duration = parsed.get("video_duration_sec")
            if duration is not None:
                try:
                    duration = int(duration)
                    parsed["video_duration_sec"] = duration
                    parsed["video_length_bucket"] = self._duration_to_bucket(duration)
                except (ValueError, TypeError):
                    parsed["video_duration_sec"] = None

            parsed["model_used"] = "gemini_video"
            parsed["raw_classification"] = parsed.copy()

            logger.info(
                f"Video classification complete for {meta_ad_id or video_id}: "
                f"awareness={parsed.get('creative_awareness_level')}, "
                f"duration={parsed.get('video_duration_sec')}s"
            )
            return parsed

        except Exception as e:
            logger.error(f"Video classification failed for {meta_ad_id or video_id}: {e}")
            return None

        finally:
            # Cleanup: delete Gemini file
            if gemini_file and client:
                try:
                    client.files.delete(name=gemini_file.name)
                except Exception:
                    pass
            # Cleanup: delete temp file
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    @staticmethod
    def _duration_to_bucket(duration_sec: int) -> str:
        """Convert video duration in seconds to a length bucket.

        Args:
            duration_sec: Duration in seconds.

        Returns:
            Bucket string like "0-15s", "15-30s", "30-60s", "60-180s", "180s+".
        """
        if duration_sec <= 15:
            return "0-15s"
        elif duration_sec <= 30:
            return "15-30s"
        elif duration_sec <= 60:
            return "30-60s"
        elif duration_sec <= 180:
            return "60-180s"
        else:
            return "180s+"

    async def _classify_with_gemini(
        self,
        thumbnail_url: str,
        ad_copy: str,
        lp_data: Optional[Dict] = None,
        meta_ad_id: Optional[str] = None,
    ) -> Dict:
        """Run lightweight Gemini classification on ad image + copy.

        Tries stored image from meta_ad_assets first (permanent, reliable),
        then falls back to the thumbnail_url (may expire). If neither works,
        classifies from copy only.

        Args:
            thumbnail_url: URL to ad thumbnail/image (fallback).
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional).
            meta_ad_id: Meta ad ID for stored image lookup.

        Returns:
            Dict with classification fields.
        """
        try:
            if self._gemini is not None:
                gemini = self._gemini
            else:
                from ...services.gemini_service import GeminiService
                logger.warning("No shared GeminiService provided, creating new instance (no rate limiting)")
                gemini = GeminiService()
            prompt = CLASSIFICATION_PROMPT.format(ad_copy=ad_copy or "(no copy available)")

            image_bytes = None

            # 1. Try stored image from meta_ad_assets (permanent copy)
            if meta_ad_id:
                storage_path = await self._find_asset_in_storage(meta_ad_id, "image")
                if storage_path:
                    image_bytes = await self._download_from_storage(storage_path)
                    if image_bytes:
                        logger.info(f"Using stored image for {meta_ad_id}")

            # 2. Fall back to thumbnail_url (may be expired CDN link)
            if not image_bytes and thumbnail_url:
                import urllib.request

                try:
                    with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                        image_bytes = response.read()
                except Exception as img_err:
                    logger.warning(f"Failed to download thumbnail for {meta_ad_id}: {img_err}")

            # 3. Classify with image or copy-only
            if image_bytes:
                import base64
                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                result_text = await gemini.analyze_image(image_b64, prompt)
            else:
                logger.warning(f"No image available for {meta_ad_id or 'unknown'}, classifying from copy only")
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
            video_duration_sec=row.get("video_duration_sec"),
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
            video_duration_sec=record.get("video_duration_sec"),
            source=record.get("source", "gemini_light"),
            prompt_version=record.get("prompt_version", "v1"),
            schema_version=record.get("schema_version", "1.0"),
            input_hash=record.get("input_hash"),
        )
