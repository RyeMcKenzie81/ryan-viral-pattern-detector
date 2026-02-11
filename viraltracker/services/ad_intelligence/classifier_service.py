"""Layer 1: ClassifierService — Awareness classification for ad creatives.

Classifies ads by awareness level, creative format, and congruence.
Produces immutable classification snapshots stored in ad_creative_classifications.

Classification sources (in priority order):
1. existing_brand_ad_analysis — Reuse existing Gemini analysis from brand research
2. gemini_video — Video analysis via Gemini Files API (first 3-5 seconds)
3. gemini_light_stored — Lightweight Gemini classification from stored image + copy
4. gemini_light_thumbnail — Same, using CDN thumbnail (may expire)
5. skipped_missing_image — No image available, ad skipped (no copy-only fallback)
6. skipped_missing_video_file / skipped_video_budget_exhausted — Video skip variants

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
from .models import AwarenessLevel, BatchClassificationResult, CreativeClassification, CreativeFormat

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

    def __init__(
        self,
        supabase_client,
        gemini_service=None,
        meta_ads_service=None,
        video_analysis_service=None,
        congruence_analyzer=None,
    ):
        """Initialize with Supabase client and optional services.

        Args:
            supabase_client: Supabase client instance for DB operations.
            gemini_service: Optional GeminiService instance with configured
                rate limiting and usage tracking. If not provided, a new
                instance will be created per classification call (not
                recommended for production use).
            meta_ads_service: Optional MetaAdsService instance for fetching
                video source URLs. Required for video classification.
            video_analysis_service: Optional VideoAnalysisService for deep
                video analysis. If provided, will be used for comprehensive
                video analysis with transcripts, hooks, and storyboards.
            congruence_analyzer: Optional CongruenceAnalyzer for per-dimension
                congruence evaluation. If provided, will analyze video-copy-LP
                alignment when video analysis and LP data are available.
        """
        self.supabase = supabase_client
        self._gemini = gemini_service
        self._meta_ads = meta_ads_service
        self._video_analysis = video_analysis_service
        self._congruence_analyzer = congruence_analyzer

    async def classify_ad(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        force: bool = False,
        video_budget_remaining: int = 0,
        scrape_missing_lp: bool = False,
    ) -> CreativeClassification:
        """Classify a single ad's creative, copy, and landing page awareness.

        run_id is required — every classification is run-scoped.
        Code-level dedup: queries for existing row matching
        (meta_ad_id, brand_id, prompt_version, schema_version, input_hash, source).
        If match exists and not stale → reuse. Otherwise → create new immutable row.

        Fallback chain:
        1. existing_brand_ad_analysis — reuse full Gemini analysis
        2. gemini_video — download video → Gemini Files API (if video + budget)
        3. gemini_light_stored — image from storage + copy classification
        4. gemini_light_thumbnail — image from CDN thumbnail + copy
        5. skipped_missing_image — no image available, skip (no copy-only)

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID (required).
            force: Force reclassification even if fresh.
            video_budget_remaining: How many video classifications are still
                allowed in this run. 0 means skip video classification.
            scrape_missing_lp: If True, create and scrape landing pages for
                unmatched destination URLs. Slower but ensures LP data is
                available for congruence analysis.

        Returns:
            CreativeClassification model.
        """
        assert run_id is not None, "run_id is required for classification"

        # Gather ad data (thumbnail, copy, landing page, video metadata)
        ad_data = await self._fetch_ad_data(meta_ad_id, brand_id, scrape_missing_lp)
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
        # REQUIRE has_video_in_storage — having a meta_video_id alone is not enough
        # because the video may be marked not_downloadable (e.g. Reels without source URL)
        has_video_in_storage = ad_data.get("has_video_in_storage", False)
        if not classification_data and is_video and has_video_in_storage and video_budget_remaining > 0:
            logger.info(f"Attempting video classification for {meta_ad_id} (video_id={video_id})")
            video_result = await self._classify_video_with_gemini(
                video_id, ad_copy, ad_data.get("lp_data"),
                meta_ad_id=meta_ad_id, brand_id=brand_id, org_id=org_id,
            )
            if video_result:
                classification_data = video_result
                source = "gemini_video"

        # 2b. Skip video ads that can't be properly classified (don't pollute data with copy-only)
        if not classification_data and is_video:
            # Determine skip reason
            if video_budget_remaining <= 0:
                skip_reason = "video_budget_exhausted"
                logger.warning(
                    f"Skipping video ad {meta_ad_id}: video classification budget exhausted. "
                    f"Rerun analysis or increase budget to classify remaining video ads."
                )
            elif not has_video_in_storage:
                skip_reason = "missing_video_file"
                logger.warning(
                    f"Skipping video ad {meta_ad_id}: no video file in storage "
                    f"(video_id={video_id}). "
                    f"Run 'Download Assets' or video may be not_downloadable (e.g. Reel)."
                )
            else:
                skip_reason = "video_classification_failed"
                logger.warning(
                    f"Skipping video ad {meta_ad_id}: video classification failed. "
                    f"Check video file in storage."
                )

            # Return a minimal classification marking it as skipped
            return CreativeClassification(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                organization_id=org_id,
                run_id=run_id,
                source=f"skipped_{skip_reason}",
                prompt_version=self.CURRENT_PROMPT_VERSION,
                schema_version=self.CURRENT_SCHEMA_VERSION,
                input_hash=current_hash,
                raw_classification={"skip_reason": skip_reason},
            )

        # 3. Fallback to image+copy classification (for non-video ads only)
        if not classification_data:
            classification_data = await self._classify_with_gemini(
                thumbnail_url, ad_copy, ad_data.get("lp_data"),
                meta_ad_id=meta_ad_id,
            )
            if classification_data is not None:
                media_source = classification_data.pop("_media_source", None)
                source = f"gemini_light_{media_source}" if media_source else "gemini_light"
            else:
                # Skip — no image available for this ad
                return CreativeClassification(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    organization_id=org_id,
                    run_id=run_id,
                    source="skipped_missing_image",
                    prompt_version=self.CURRENT_PROMPT_VERSION,
                    schema_version=self.CURRENT_SCHEMA_VERSION,
                    input_hash=current_hash,
                    raw_classification={"skip_reason": "missing_image"},
                )

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
            # Deep video analysis link (Phase 2 - populated when VideoAnalysisService is used)
            "video_analysis_id": classification_data.get("video_analysis_id"),
            # Per-dimension congruence (Phase 5 - populated by CongruenceAnalyzer)
            "congruence_components": classification_data.get("congruence_components", []),
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

        # Run deep congruence analysis if we have video analysis and LP data
        if record.get("video_analysis_id") and ad_data.get("lp_data"):
            copy_data = {
                "copy_awareness_level": record.get("copy_awareness_level"),
                "primary_cta": record.get("primary_cta"),
            }
            congruence_components = await self._run_deep_congruence_analysis(
                video_analysis_id=record.get("video_analysis_id"),
                lp_data=ad_data.get("lp_data"),
                copy_data=copy_data,
            )
            if congruence_components:
                record["congruence_components"] = congruence_components

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
        max_video: int = 15,
    ) -> BatchClassificationResult:
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
            BatchClassificationResult with classifications list and
            breakdown of new, cached, skipped, and error counts.
        """
        classifications: List[CreativeClassification] = []
        new_count = 0
        cached_count = 0
        error_count = 0
        video_classification_count = 0

        # Sort ads by spend to prioritize high-spend ads
        spend_order = await self._get_ad_spend_order(brand_id, meta_ad_ids)
        sorted_ids = sorted(meta_ad_ids, key=lambda x: spend_order.get(x, 0), reverse=True)

        skipped_count = 0
        for i, meta_ad_id in enumerate(sorted_ids):
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
                    cached_count += 1
                    continue

                # Need new classification — check cap
                if new_count >= max_new:
                    remaining = len(sorted_ids) - i
                    logger.info(
                        f"Classification cap reached ({max_new}). "
                        f"Skipping {remaining} remaining ads."
                    )
                    skipped_count += remaining
                    break

                video_budget = max_video - video_classification_count
                classification = await self.classify_ad(
                    meta_ad_id, brand_id, org_id, run_id,
                    video_budget_remaining=video_budget,
                )
                classifications.append(classification)

                # Track skip vs new vs video
                if classification.source and classification.source.startswith("skipped_"):
                    skipped_count += 1
                elif classification.source == "gemini_video":
                    new_count += 1
                    video_classification_count += 1
                else:
                    new_count += 1

            except Exception as e:
                logger.error(f"Error classifying ad {meta_ad_id}: {e}")
                error_count += 1
                continue

        logger.info(
            f"Classified batch: {len(classifications)} total "
            f"({cached_count} cached, {new_count} new, "
            f"{video_classification_count} video), "
            f"{skipped_count} skipped, {error_count} errors"
        )
        return BatchClassificationResult(
            classifications=classifications,
            new_count=new_count,
            cached_count=cached_count,
            skipped_count=skipped_count,
            error_count=error_count,
        )

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

    async def _ensure_landing_page_exists(
        self,
        canonical_url: str,
        destination_url: str,
        brand_id: UUID,
    ) -> Optional[Dict]:
        """Ensure landing page exists, creating and scraping if needed.

        If the landing page doesn't exist in brand_landing_pages, creates a new
        record and scrapes it with FireCrawl.

        Args:
            canonical_url: Normalized URL for matching.
            destination_url: Original URL from Meta API.
            brand_id: Brand UUID.

        Returns:
            LP data dict with id, url, page_title, extracted_data, or None on failure.
        """
        from uuid import uuid4

        # 1. Check if LP already exists
        existing = self.supabase.table("brand_landing_pages").select(
            "id, url, page_title, extracted_data"
        ).eq("brand_id", str(brand_id)).eq(
            "canonical_url", canonical_url
        ).limit(1).execute()

        if existing.data:
            return existing.data[0]

        # 2. Create pending LP record
        lp_id = uuid4()
        try:
            self.supabase.table("brand_landing_pages").insert({
                "id": str(lp_id),
                "brand_id": str(brand_id),
                "url": destination_url,
                "canonical_url": canonical_url,
                "scrape_status": "pending",
            }).execute()
        except Exception as e:
            # Handle race condition - LP may have been created by another process
            logger.warning(f"Failed to create LP record for {canonical_url}: {e}")
            # Try to fetch the existing record
            existing = self.supabase.table("brand_landing_pages").select(
                "id, url, page_title, extracted_data"
            ).eq("brand_id", str(brand_id)).eq(
                "canonical_url", canonical_url
            ).limit(1).execute()
            if existing.data:
                return existing.data[0]
            return None

        # 3. Scrape with FireCrawl
        try:
            from viraltracker.services.web_scraping_service import WebScrapingService
            scraper = WebScrapingService()
            scrape_result = await scraper.scrape_url_async(destination_url)

            if not scrape_result.success:
                # Mark as failed
                self.supabase.table("brand_landing_pages").update({
                    "scrape_status": "failed",
                    "scrape_error": scrape_result.error or "Unknown error",
                }).eq("id", str(lp_id)).execute()
                logger.warning(f"Failed to scrape {destination_url}: {scrape_result.error}")
                return None

            # 4. Extract page title from metadata
            # Note: metadata may be a DocumentMetadata object, not a dict
            page_title = None
            metadata_dict = None
            if scrape_result.metadata:
                # Try to get title - handle both dict and object
                if hasattr(scrape_result.metadata, 'title'):
                    page_title = scrape_result.metadata.title
                elif isinstance(scrape_result.metadata, dict):
                    page_title = scrape_result.metadata.get("title")

                # Convert metadata to dict for storage
                if hasattr(scrape_result.metadata, '__dict__'):
                    metadata_dict = {k: v for k, v in vars(scrape_result.metadata).items()
                                    if not k.startswith('_')}
                elif isinstance(scrape_result.metadata, dict):
                    metadata_dict = scrape_result.metadata

            # 5. Update LP with scraped data
            extracted_data = {
                "markdown": scrape_result.markdown,
                "links": scrape_result.links,
                "metadata": metadata_dict,
            }

            self.supabase.table("brand_landing_pages").update({
                "scrape_status": "scraped",
                "page_title": page_title,
                "extracted_data": extracted_data,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", str(lp_id)).execute()

            logger.info(f"Scraped and saved LP for {canonical_url}")

            return {
                "id": str(lp_id),
                "url": destination_url,
                "page_title": page_title,
                "extracted_data": extracted_data,
            }

        except Exception as e:
            logger.error(f"Error scraping {destination_url}: {e}")
            # Mark as failed
            try:
                self.supabase.table("brand_landing_pages").update({
                    "scrape_status": "failed",
                    "scrape_error": str(e),
                }).eq("id", str(lp_id)).execute()
            except Exception:
                pass
            return None

    async def _fetch_ad_data(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        scrape_missing_lp: bool = False,
    ) -> Dict[str, Any]:
        """Fetch ad thumbnail, copy, video metadata, and landing page data.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            scrape_missing_lp: If True, create and scrape landing pages for
                unmatched destination URLs (slower but complete).

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

        # For ALL video ads, check meta_ad_assets for an actual downloaded video file.
        # Having a meta_video_id does NOT mean the video was downloaded — many are
        # marked not_downloadable (e.g. Reels with no source URL from Meta API).
        if result.get("is_video"):
            try:
                asset_result = self.supabase.table("meta_ad_assets").select(
                    "storage_path"
                ).eq("meta_ad_id", meta_ad_id).eq(
                    "asset_type", "video"
                ).eq("status", "downloaded").limit(1).execute()

                if asset_result.data:
                    result["has_video_in_storage"] = True
                else:
                    result["has_video_in_storage"] = False
            except Exception as e:
                logger.warning(f"Error checking meta_ad_assets for {meta_ad_id}: {e}")

        # Note: ad_archive_id linkage to facebook_ads not implemented.
        # Ad copy falls back to ad_name below.

        # Use ad_name as fallback for ad_copy
        if not result.get("ad_copy"):
            result["ad_copy"] = result.get("ad_name", "")

        # Look up landing page from ad destination
        try:
            dest_result = self.supabase.table("meta_ad_destinations").select(
                "canonical_url, destination_url"
            ).eq("meta_ad_id", meta_ad_id).eq("brand_id", str(brand_id)).limit(1).execute()

            if dest_result.data:
                canonical_url = dest_result.data[0].get("canonical_url")
                destination_url = dest_result.data[0].get("destination_url")
                if canonical_url:
                    # Try to find existing LP - fetch all fields needed for congruence analysis
                    lp_result = self.supabase.table("brand_landing_pages").select(
                        "id, url, page_title, extracted_data, benefits, features, "
                        "call_to_action, product_name, raw_markdown"
                    ).eq("brand_id", str(brand_id)).eq("canonical_url", canonical_url).limit(1).execute()

                    if lp_result.data:
                        result["landing_page_id"] = lp_result.data[0]["id"]
                        result["lp_data"] = lp_result.data[0]
                    elif scrape_missing_lp and destination_url:
                        # No existing LP - create and scrape it
                        logger.info(f"No LP match for {canonical_url}, scraping...")
                        lp_data = await self._ensure_landing_page_exists(
                            canonical_url, destination_url, brand_id
                        )
                        if lp_data:
                            result["landing_page_id"] = lp_data["id"]
                            result["lp_data"] = lp_data
        except Exception as e:
            logger.warning(f"Error looking up landing page for {meta_ad_id}: {e}")

        return result

    async def _find_existing_analysis(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Optional[Dict]:
        """Find existing brand_ad_analysis for this ad.

        Note: ad_archive_id linkage between meta_ads_performance and facebook_ads
        is not implemented. This method is a placeholder for future functionality
        when we have a way to link Meta Ads API data to Ad Library data.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.

        Returns:
            raw_response dict from brand_ad_analysis or None.
        """
        # Linkage not implemented - always classify fresh
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
        org_id: Optional[UUID] = None,
    ) -> Optional[Dict]:
        """Classify a video ad using VideoAnalysisService for deep analysis.

        Uses VideoAnalysisService.deep_analyze_video() for comprehensive video
        analysis including transcripts, hooks, storyboard, and messaging. The
        analysis is saved to ad_video_analysis and the video_analysis_id is
        returned for linking.

        Falls back to legacy Gemini video classification if VideoAnalysisService
        is not available.

        Video must be pre-downloaded into meta_ad_assets by the nightly
        meta_sync job or the manual "Download Assets" button. If the video
        isn't in storage, returns None -> caller falls back to image+copy.

        Args:
            video_id: Meta video ID from AdCreative.
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional, unused currently).
            meta_ad_id: Meta ad ID for looking up video in storage.
            brand_id: Brand UUID for VideoAnalysisService.
            org_id: Organization UUID for VideoAnalysisService.

        Returns:
            Dict with classification fields including video_analysis_id, or None on failure.
        """
        if not meta_ad_id:
            logger.warning(f"No meta_ad_id provided for video classification (video_id={video_id})")
            return None

        # Use VideoAnalysisService if available
        if self._video_analysis and brand_id and org_id:
            return await self._classify_video_with_analysis_service(
                meta_ad_id, brand_id, org_id, ad_copy
            )

        # Fallback to legacy Gemini video classification
        return await self._classify_video_with_gemini_legacy(
            video_id, ad_copy, lp_data, meta_ad_id
        )

    async def _classify_video_with_analysis_service(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        org_id: UUID,
        ad_copy: Optional[str] = None,
    ) -> Optional[Dict]:
        """Classify video using VideoAnalysisService for deep analysis.

        Performs comprehensive analysis and maps the result to classification fields.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            ad_copy: Ad copy text for context.

        Returns:
            Dict with classification fields including video_analysis_id, or None on failure.
        """
        try:
            logger.info(f"Using VideoAnalysisService for deep analysis of {meta_ad_id}")

            # Perform deep video analysis
            analysis_result = await self._video_analysis.deep_analyze_video(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                organization_id=org_id,
                ad_copy=ad_copy,
            )

            if not analysis_result:
                logger.info(f"VideoAnalysisService returned None for {meta_ad_id}")
                return None

            # Check for error status
            if analysis_result.status == "error":
                logger.warning(
                    f"VideoAnalysisService error for {meta_ad_id}: {analysis_result.error_message}"
                )
                return None

            # Save the analysis result to database
            video_analysis_id = await self._video_analysis.save_video_analysis(
                analysis_result, org_id
            )

            if not video_analysis_id:
                logger.warning(f"Failed to save video analysis for {meta_ad_id}")
                # Continue with classification but without video_analysis_id

            # Map VideoAnalysisResult fields to classification fields
            classification = self._map_video_analysis_to_classification(
                analysis_result, video_analysis_id
            )

            logger.info(
                f"Deep video classification complete for {meta_ad_id}: "
                f"awareness={classification.get('creative_awareness_level')}, "
                f"duration={classification.get('video_duration_sec')}s, "
                f"video_analysis_id={video_analysis_id}"
            )

            return classification

        except Exception as e:
            logger.error(f"VideoAnalysisService classification failed for {meta_ad_id}: {e}")
            return None

    def _map_video_analysis_to_classification(
        self,
        result,  # VideoAnalysisResult
        video_analysis_id: Optional[UUID] = None,
    ) -> Dict:
        """Map VideoAnalysisResult fields to classification schema.

        Args:
            result: VideoAnalysisResult from deep analysis.
            video_analysis_id: UUID of the saved analysis row.

        Returns:
            Dict with classification fields.
        """
        # Compute video_length_bucket from duration
        video_length_bucket = None
        if result.video_duration_sec is not None:
            video_length_bucket = self._duration_to_bucket(result.video_duration_sec)

        # Map format_type to creative_format
        format_mapping = {
            "ugc": "video_ugc",
            "professional": "video_professional",
            "testimonial": "video_testimonial",
            "demo": "video_demo",
            "animation": "video_professional",
            "mixed": "video_ugc",
        }
        creative_format = format_mapping.get(result.format_type, "video_ugc")

        # Build raw classification with all analysis data for reference
        raw_classification = {
            "full_transcript": result.full_transcript,
            "transcript_segments": result.transcript_segments,
            "text_overlays": result.text_overlays,
            "text_overlay_confidence": result.text_overlay_confidence,
            "hook_transcript_spoken": result.hook_transcript_spoken,
            "hook_transcript_overlay": result.hook_transcript_overlay,
            "hook_fingerprint": result.hook_fingerprint,
            "hook_type": result.hook_type,
            "hook_effectiveness_signals": result.hook_effectiveness_signals,
            "hook_visual_description": result.hook_visual_description,
            "hook_visual_elements": result.hook_visual_elements,
            "hook_visual_type": result.hook_visual_type,
            "storyboard": result.storyboard,
            "benefits_shown": result.benefits_shown,
            "features_demonstrated": result.features_demonstrated,
            "pain_points_addressed": result.pain_points_addressed,
            "angles_used": result.angles_used,
            "jobs_to_be_done": result.jobs_to_be_done,
            "claims_made": result.claims_made,
            "awareness_level": result.awareness_level,
            "awareness_confidence": result.awareness_confidence,
            "target_persona": result.target_persona,
            "emotional_drivers": result.emotional_drivers,
            "production_quality": result.production_quality,
            "format_type": result.format_type,
            "validation_errors": result.validation_errors,
            "input_hash": result.input_hash,
            "prompt_version": result.prompt_version,
        }

        # Build hook_transcript combining spoken and overlay
        hook_transcript = result.hook_transcript_spoken or ""
        if result.hook_transcript_overlay:
            hook_transcript = f"{hook_transcript} [{result.hook_transcript_overlay}]".strip()

        return {
            # Awareness level (from video analysis)
            "creative_awareness_level": result.awareness_level,
            "creative_awareness_confidence": result.awareness_confidence,
            # Format
            "creative_format": creative_format,
            # Angle (use first angle if available, or summary)
            "creative_angle": result.angles_used[0] if result.angles_used else None,
            # Video metadata
            "video_duration_sec": result.video_duration_sec,
            "video_length_bucket": video_length_bucket,
            # Hook
            "hook_type": result.hook_type,
            "hook_transcript": hook_transcript if hook_transcript else None,
            # Benefits (for reference in raw)
            "benefits_shown": result.benefits_shown,
            # Link to deep analysis
            "video_analysis_id": str(video_analysis_id) if video_analysis_id else None,
            # Model info
            "model_used": "gemini_video_deep",
            "raw_classification": raw_classification,
        }

    async def _classify_video_with_gemini_legacy(
        self,
        video_id: str,
        ad_copy: str,
        lp_data: Optional[Dict] = None,
        meta_ad_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Legacy video classification using direct Gemini Files API.

        This is the fallback method when VideoAnalysisService is not available.
        Focuses on the first 3-5 seconds for awareness level classification.

        Args:
            video_id: Meta video ID from AdCreative.
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional, unused currently).
            meta_ad_id: Meta ad ID for looking up video in storage.

        Returns:
            Dict with classification fields, or None on failure.
        """
        temp_path = None
        gemini_file = None
        client = None

        try:
            from google import genai

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

            # Write to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_file.write(video_content)
            temp_file.close()
            temp_path = temp_file.name

            # Upload to Gemini Files API
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("GEMINI_API_KEY not set — cannot classify video")
                return None

            client = genai.Client(api_key=api_key)
            logger.info(f"Uploading video to Gemini Files API ({meta_ad_id or video_id})")
            gemini_file = client.files.upload(file=str(temp_path))
            logger.info(f"Uploaded to Gemini: {gemini_file.uri}")

            # Wait for processing (up to 120s, polling every 2s)
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

            # Generate classification
            prompt = VIDEO_CLASSIFICATION_PROMPT.format(
                ad_copy=ad_copy or "(no copy available)"
            )
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=[gemini_file, prompt],
            )

            # Parse response
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
            Bucket string: short_0_15, medium_15_30, long_30_60, very_long_60_plus.
        """
        if duration_sec <= 15:
            return "short_0_15"
        elif duration_sec <= 30:
            return "medium_15_30"
        elif duration_sec <= 60:
            return "long_30_60"
        else:
            return "very_long_60_plus"

    async def _classify_with_gemini(
        self,
        thumbnail_url: str,
        ad_copy: str,
        lp_data: Optional[Dict] = None,
        meta_ad_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Run lightweight Gemini classification on ad image + copy.

        Tries stored image from meta_ad_assets first (permanent, reliable),
        then falls back to the thumbnail_url (may expire). If neither source
        provides an image, returns None to signal the caller to skip.

        Args:
            thumbnail_url: URL to ad thumbnail/image (fallback).
            ad_copy: Ad copy text.
            lp_data: Landing page data (optional).
            meta_ad_id: Meta ad ID for stored image lookup.

        Returns:
            Dict with classification fields including ``_media_source``
            (``"stored"`` or ``"thumbnail"``), or None if no image available.
        """
        if self._gemini is not None:
            gemini = self._gemini
        else:
            from ...services.gemini_service import GeminiService
            logger.warning("No shared GeminiService provided, creating new instance (no rate limiting)")
            gemini = GeminiService()
        prompt = CLASSIFICATION_PROMPT.format(ad_copy=ad_copy or "(no copy available)")

        image_bytes = None
        media_source = None

        # 1. Try stored image from meta_ad_assets (permanent copy)
        if meta_ad_id:
            storage_path = await self._find_asset_in_storage(meta_ad_id, "image")
            if storage_path:
                image_bytes = await self._download_from_storage(storage_path)
                if image_bytes:
                    media_source = "stored"
                    logger.info(f"Using stored image for {meta_ad_id}")

        # 2. Fall back to thumbnail_url (may be expired CDN link)
        if not image_bytes and thumbnail_url:
            import urllib.request

            try:
                with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                    image_bytes = response.read()
                if image_bytes:
                    media_source = "thumbnail"
            except Exception as img_err:
                logger.warning(f"Failed to download thumbnail for {meta_ad_id}: {img_err}")

        # 3. Skip if no image available (no copy-only fallback)
        if not image_bytes:
            logger.warning(f"No image available for {meta_ad_id or 'unknown'}, skipping classification.")
            return None

        # 4. Classify with image
        import base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        result_text = await gemini.analyze_image(image_b64, prompt)

        # Parse JSON response
        parsed = self._parse_gemini_response(result_text)
        parsed["model_used"] = "gemini_light"
        parsed["raw_classification"] = parsed.copy()
        parsed["_media_source"] = media_source
        return parsed

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

    async def _run_deep_congruence_analysis(
        self,
        video_analysis_id: Optional[str],
        lp_data: Optional[Dict],
        copy_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Run deep congruence analysis if data is available.

        Evaluates per-dimension alignment between video content, copy, and LP.

        Args:
            video_analysis_id: UUID of video analysis row (may be None).
            lp_data: Landing page data dict (may be None).
            copy_data: Copy classification data dict.

        Returns:
            List of congruence component dicts, or empty list if not possible.
        """
        # Skip if no congruence analyzer configured
        if not self._congruence_analyzer:
            return []

        # Skip if no video analysis or LP data
        if not video_analysis_id or not lp_data:
            return []

        try:
            # Fetch video analysis data
            video_result = self.supabase.table("ad_video_analysis").select(
                "awareness_level, hook_transcript_spoken, hook_transcript_overlay, "
                "hook_visual_description, benefits_shown, angles_used, claims_made, "
                "pain_points_addressed"
            ).eq("id", video_analysis_id).limit(1).execute()

            if not video_result.data:
                logger.warning(f"Video analysis {video_analysis_id} not found for congruence")
                return []

            video_data = video_result.data[0]

            # Run congruence analysis
            from .congruence_analyzer import CongruenceAnalyzer

            result = await self._congruence_analyzer.analyze_congruence(
                video_data=video_data,
                copy_data=copy_data,
                lp_data=lp_data,
            )

            if result.error:
                logger.warning(f"Congruence analysis error: {result.error}")

            logger.info(
                f"Deep congruence analysis complete: "
                f"overall_score={result.overall_score}, "
                f"components={len(result.components)}"
            )

            return result.to_components_list()

        except Exception as e:
            logger.error(f"Deep congruence analysis failed: {e}")
            return []

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
            congruence_components=row.get("congruence_components", []),
            video_analysis_id=UUID(row["video_analysis_id"]) if row.get("video_analysis_id") else None,
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
            congruence_components=record.get("congruence_components", []),
            video_analysis_id=UUID(record["video_analysis_id"]) if record.get("video_analysis_id") else None,
            source=record.get("source", "gemini_light"),
            prompt_version=record.get("prompt_version", "v1"),
            schema_version=record.get("schema_version", "1.0"),
            input_hash=record.get("input_hash"),
        )
