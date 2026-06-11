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
- prompt_version / schema_version changed (the cache prefetch filters on both)

NOTE: the batch path (classify_batch) is "classified-once" — an ad already
classified at the current prompt+schema version is reused and never re-run on
input_hash drift. Meta ad creatives are immutable, and the thumbnail is a
rotating signed URL, so hashing it caused needless re-classification. The single
classify_ad() path still tracks input_hash for provenance.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse
import json
import logging
import os
import asyncio
import tempfile
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from .helpers import _safe_numeric
from .models import AwarenessLevel, BatchClassificationResult, CreativeClassification, CreativeFormat
# Video-analysis versioning + model. The video deep-analysis prompt is versioned
# independently of this classifier's CURRENT_PROMPT_VERSION, so a video-prompt
# bump must invalidate the classify-once cache for video ads (see classify_batch).
from ..video_analysis_service import (
    PROMPT_VERSION as VIDEO_ANALYSIS_PROMPT_VERSION,
    VIDEO_ANALYSIS_MODEL,
)
from ..image_analysis_service import PROMPT_VERSION as IMAGE_ANALYSIS_PROMPT_VERSION
from ..awareness_rubric import AWARENESS_RUBRIC
from .awareness_currency import image_link_is_current

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

# Video-specific classification prompt — judges awareness from the opening (~10s).
# Degraded single-value fallback used only when VideoAnalysisService is unavailable;
# the deep path captures opening AND ending (see DEEP_VIDEO_ANALYSIS_PROMPT).
VIDEO_CLASSIFICATION_PROMPT = """Analyze this video ad creative and return a JSON classification.

Determine awareness level from the video's OPENING — roughly the FIRST 10 SECONDS —
i.e. the stage the messaging positions the viewer at (their entry temperature), NOT
where the video ends. Video ads commonly move the viewer down the funnel, so judge by
the opening, not the close. If the first moments are a pure attention-grab / pattern
interrupt unrelated to the offer, judge by the first substantive message that follows
within that ~10s window.

Use this awareness rubric (classify by what the opening PRESUMES the viewer knows):

{awareness_rubric}

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


# Text-only awareness judgment of the Facebook caption (COPY), used by the static-image
# path so copy awareness is judged INDEPENDENTLY of the on-image creative (D3). The model
# sees only the caption text — never the image — so creative<->copy congruence stays real.
COPY_AWARENESS_PROMPT = """Classify the awareness level of the PRIMARY TEXT / caption of a
Facebook ad — the copy that runs ABOVE the creative in the feed. Judge this text on its own,
as a standalone message, using the rubric below.

{awareness_rubric}

AD CAPTION (copy):
{ad_copy}

Return ONLY valid JSON, no other text:
{{
    "copy_awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",
    "copy_awareness_confidence": 0.0-1.0
}}"""


# The ONLY image creative_format values allowed by the DB CHECK constraint
# ad_creative_classifications_creative_format_check. The static deep path must map
# every imagery_type into this set (unknown -> image_static), or the INSERT fails.
# Single source of truth shared with the mapper and its test.
IMAGE_CREATIVE_FORMATS = frozenset(
    {"image_static", "image_before_after", "image_testimonial", "image_product"}
)


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
        image_analysis_service=None,
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
        # Deep static-image analysis (creative awareness from on-image text, calibrated
        # rubric). When present, image ads route through it instead of the light path.
        self._image_analysis = image_analysis_service

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

        # Check for existing classification.
        # NOTE: this legacy input_hash cache is NOT deep-analysis-staleness-aware (it does
        # not consult _video/_image_analysis_is_stale), so it could re-serve a stale light
        # row whose linked deep analysis is outdated. Every PRODUCTION caller therefore
        # passes force=True — classify_batch (its prefetch + staleness gates are the cache
        # authority) and the congruence_reanalysis job. The default force=False path is
        # used only by standalone scripts; if you add a new force=False caller for image/
        # video ads, route through classify_batch or make this block staleness-aware first.
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

        # 2c. Deep image classification (non-video ads), symmetric to the video path.
        # When the deep image service is wired this is the ONLY image path: creative
        # awareness comes from ImageAnalysisService reading the ON-IMAGE text (calibrated
        # rubric); copy awareness is judged SEPARATELY from ad_copy (D3 — the two never
        # see each other's input, so creative<->copy congruence stays meaningful).
        #
        # Deep-or-SKIP (no light fallback when deep is wired): if the deep path can't run
        # — no full-res asset in storage, too low-res to read, or a transient parse
        # failure — we SKIP rather than fall back to the light thumbnail+caption path.
        # The light path leans on ad_copy (the caption = COPY, not the creative), which
        # conflates copy into creative awareness and corrupts congruence. A skip is NOT
        # persisted, so the ad keeps its previous classification for the digest and
        # re-runs once the asset is downloaded / becomes readable (same graceful
        # degradation as video's not-in-storage path).
        if not classification_data and not is_video and self._image_analysis is not None:
            # Copy awareness is judged from the GENUINE caption only (most-recent
            # non-empty ad_copy across perf rows), NOT the `ad_copy` variable above:
            # _fetch_ad_data falls back to the internal ad_name when the latest row's
            # ad_copy is empty, and judging an ad name's awareness is noise. None here
            # means "no caption" -> copy awareness is skipped, congruence not computed.
            caption = self._get_latest_caption(meta_ad_id, brand_id)
            # The deep image helper is synchronous end-to-end (sync Gemini SDK call
            # inside ImageAnalysisService); running it inline blocks the event loop
            # for the whole ~30s analysis and would serialize
            # CLASSIFIER_MAX_CONCURRENCY. to_thread frees the loop so concurrent
            # dispatch actually overlaps Gemini calls.
            image_result = await asyncio.to_thread(
                self._classify_image_with_analysis_service,
                meta_ad_id, brand_id, org_id, caption,
            )
            if image_result and image_result != "low_res":
                classification_data = image_result
                source = "gemini_image_deep"
            else:
                skip_reason = (
                    "image_low_res" if image_result == "low_res"
                    else "image_deep_unavailable"  # no stored asset / transient failure
                )
                logger.info(f"Skipping image ad {meta_ad_id}: {skip_reason}")
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

        # 3. Fallback to image+copy classification (only when the deep image service is
        # NOT wired — preserves the legacy light path for callers without it).
        if not classification_data:
            classification_data = await self._classify_with_gemini(
                ad_data=ad_data,
                ad_copy=ad_copy,
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
            # Deep image analysis link (static path — populated when ImageAnalysisService is used)
            "image_analysis_id": classification_data.get("image_analysis_id"),
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
        scrape_missing_lp: bool = False,
        force: bool = False,
    ) -> BatchClassificationResult:
        """Classify a batch of ads, prioritizing by spend.

        Sorts unclassified ads by spend descending. Caps new Gemini calls
        at max_new to prevent runaway costs. Video classifications are
        additionally capped at max_video per run.

        Uses batch-prefetch to load all ad data and existing classifications
        in bulk queries (4 queries total) instead of per-ad N+1 queries.

        Classified-once: an ad already classified at the CURRENT prompt+schema
        version is treated as cached and never re-run (Meta ad creatives are
        immutable), regardless of input_hash drift. Only ``force`` re-classifies.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID.
            meta_ad_ids: List of meta ad IDs to classify.
            max_new: Max new Gemini classifications (from RunConfig).
            max_video: Max video classifications per run (from RunConfig).
            scrape_missing_lp: If True, create and scrape landing pages for
                unmatched destination URLs during classification.
            force: Re-classify even ads that already have a current-version
                classification (e.g. after a prompt change). Default False.

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

        # Batch-prefetch all ad data, classifications, and deep-analysis versions
        # in bulk (queries instead of ~5 per ad). The ad-data map (is_video) and the
        # video/image analysis version maps ARE consulted in the cache decision so a
        # video- OR image-prompt bump invalidates the corresponding classify-once (see
        # the cache block below + _video_analysis_is_stale / _image_analysis_is_stale);
        # the classification map drives the rest.
        (
            prefetched_ads,
            prefetched_classifications,
            video_analysis_versions,
            image_analysis_versions,
            low_res_marker_ids,
        ) = await self._batch_prefetch(brand_id, sorted_ids)

        # Dispatch concurrency for the slow classify_ad calls. Default 1 preserves
        # the exact sequential behavior; tier-3 Gemini accounts can raise it via
        # CLASSIFIER_MAX_CONCURRENCY (pair with GEMINI_REQUESTS_PER_MINUTE).
        try:
            _concurrency = max(1, int(os.getenv("CLASSIFIER_MAX_CONCURRENCY", "1")))
        except ValueError:
            _concurrency = 1

        # PHASE 1 (sequential, fast): cache/skip/cap decisions build the dispatch
        # work list. Caps are enforced HERE so they stay deterministic regardless
        # of dispatch concurrency: at most max_new ads are dispatched at all, and
        # video-capable ads beyond the first max_video get a zero video budget
        # (classify_ad then returns skipped_video_budget, same as sequentially).
        # One conservative divergence from the old inline loop: a video slot freed
        # by a failed video analysis is NOT reused by a later ad.
        todo: List[tuple] = []  # (meta_ad_id, video_budget_for_this_ad)
        _video_slots_left = max_video
        skipped_count = 0
        for i, meta_ad_id in enumerate(sorted_ids):
            try:
                # 0. Settled low_res: this image ad has a current-version low_res marker
                # (64x64 thumbnail we can't read). Skip it entirely — do NOT call
                # classify_ad, which would re-download + re-decode the same thumbnail
                # every run for no result. It stays settled until a future high-res
                # re-fetch clears the marker. We only skip when there is no current deep
                # classification to serve (there normally isn't — low_res never produces
                # one); if a real classification exists, fall through and let the cache
                # decision below handle it.
                if meta_ad_id in low_res_marker_ids:
                    existing_lr = self._match_prefetched_classification(
                        prefetched_classifications.get(meta_ad_id, []), force=force,
                    )
                    if not (existing_lr and not self._image_analysis_is_stale(
                        existing_lr, prefetched_ads.get(meta_ad_id, {}), image_analysis_versions,
                    )):
                        skipped_count += 1
                        continue

                # Cache hit: any prefetched classification for this ad is already at
                # the CURRENT prompt+schema version (the prefetch filters on both),
                # and Meta ad creatives are immutable — so it's reusable. We do NOT
                # gate on input_hash: the thumbnail is a rotating signed URL and
                # ad_copy/LP get re-fetched, so hashing them made already-classified
                # ads miss cache and get needlessly re-classified, burning the
                # max_new budget. Only force re-classifies.
                existing = self._match_prefetched_classification(
                    prefetched_classifications.get(meta_ad_id, []),
                    force=force,
                )
                # 1A: a video ad's cached classification is only reusable if its OWN
                # linked deep analysis is at the current video-analysis prompt
                # version. Otherwise the awareness was judged by a stale video prompt
                # (or the analysis row was never linked) — fall through to re-analyze.
                # 1B (symmetric): an IMAGE ad's cached classification is only reusable
                # if its linked deep image analysis is at the current image-analysis
                # prompt version. A PROMPT_VERSION bump on ImageAnalysisService thus
                # re-runs only image ads; video + light-path ads stay cached.
                if (
                    existing
                    and not self._video_analysis_is_stale(
                        existing,
                        prefetched_ads.get(meta_ad_id, {}),
                        video_analysis_versions,
                    )
                    and not self._image_analysis_is_stale(
                        existing,
                        prefetched_ads.get(meta_ad_id, {}),
                        image_analysis_versions,
                    )
                ):
                    classifications.append(self._row_to_model(existing))
                    cached_count += 1
                    continue

                # Need new classification — check the dispatch cap (each dispatch
                # is a potential billable Gemini call, which is what max_new exists
                # to bound).
                if len(todo) >= max_new:
                    remaining = len(sorted_ids) - i
                    logger.info(
                        f"Classification cap reached ({max_new}). "
                        f"Skipping {remaining} remaining ads."
                    )
                    skipped_count += remaining
                    break

                # Pre-allocate a video slot when the prefetch says this is a video
                # ad and budget remains; classify_ad makes the true routing decision.
                _is_video = bool((prefetched_ads.get(meta_ad_id) or {}).get("is_video"))
                if _is_video and _video_slots_left > 0:
                    todo.append((meta_ad_id, 1))
                    _video_slots_left -= 1
                else:
                    todo.append((meta_ad_id, 0 if _is_video else max_video))

            except Exception as e:
                logger.error(f"Error classifying ad {meta_ad_id}: {e}")
                error_count += 1
                continue

        # PHASE 2: dispatch the slow calls. force=True is REQUIRED here: we only
        # reach dispatch after the prefetch cache decision above (which DOES apply
        # the video/image staleness gates) decided the ad needs (re)classification.
        # classify_ad has its OWN legacy input_hash cache that is NOT staleness-
        # aware — with force=False it would re-serve the very stale row we just
        # decided to replace. The prefetch cache above is the single source of truth.
        async def _dispatch(ad_id: str, video_budget: int):
            try:
                return await self.classify_ad(
                    ad_id, brand_id, org_id, run_id,
                    video_budget_remaining=video_budget,
                    scrape_missing_lp=scrape_missing_lp,
                    force=True,
                )
            except Exception as e:
                logger.error(f"Error classifying ad {ad_id}: {e}")
                return e

        if _concurrency <= 1:
            results = [await _dispatch(ad_id, vb) for ad_id, vb in todo]
        else:
            _sem = asyncio.Semaphore(_concurrency)

            async def _bounded(ad_id: str, vb: int):
                async with _sem:
                    return await _dispatch(ad_id, vb)

            results = await asyncio.gather(*(_bounded(a, v) for a, v in todo))

        for result in results:
            if isinstance(result, Exception):
                error_count += 1
                continue
            classifications.append(result)
            if result.source and result.source.startswith("skipped_"):
                skipped_count += 1
            elif result.source == "gemini_video":
                new_count += 1
                video_classification_count += 1
            else:
                new_count += 1

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

    async def _batch_prefetch(
        self,
        brand_id: UUID,
        meta_ad_ids: List[str],
    ) -> tuple:
        """Batch-prefetch ad data and classifications in bulk queries.

        Replaces per-ad N+1 queries with 4 bulk queries:
        1. meta_ads_performance (perf data, thumbnails, video info)
        2. meta_ad_destinations (landing page URLs)
        3. brand_landing_pages (LP data by canonical URL)
        4. ad_creative_classifications (existing classifications)

        Plus 1 conditional query for video asset checks.

        Args:
            brand_id: Brand UUID.
            meta_ad_ids: List of meta ad IDs.

        Returns:
            Tuple of (ad_data_map, classifications_map, video_analysis_versions,
            image_analysis_versions, low_res_marker_ids):
            - ad_data_map: Dict[meta_ad_id] -> ad_data dict (same shape as _fetch_ad_data)
            - classifications_map: Dict[meta_ad_id] -> List[classification rows]
            - video_analysis_versions: Dict[analysis_id(str)] -> prompt_version, for
              the video classify-once staleness check.
            - image_analysis_versions: Dict[analysis_id(str)] -> prompt_version, for
              the image classify-once staleness check.
            - low_res_marker_ids: Set[meta_ad_id] with a current-version low_res marker
              (the classify loop skips these to stop the re-download churn).
        """
        brand_str = str(brand_id)
        ad_data_map: Dict[str, Dict[str, Any]] = {
            ad_id: {"meta_ad_id": ad_id} for ad_id in meta_ad_ids
        }

        # --- Query 1: meta_ads_performance (bulk) ---
        # Limit high enough to cover all ads (we only keep the latest per ad).
        # Supabase defaults to 1000 rows; with many dates per ad we may need more.
        perf_limit = max(1000, len(meta_ad_ids) * 5)
        try:
            perf_result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, thumbnail_url, ad_name, ad_copy, meta_campaign_id, "
                "meta_video_id, is_video, video_views, object_type, date"
            ).eq(
                "brand_id", brand_str
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).order("date", desc=True).limit(perf_limit).execute()

            # Keep only the most recent row per ad (ordered by date desc)
            seen = set()
            for row in (perf_result.data or []):
                ad_id = row.get("meta_ad_id")
                if ad_id in seen:
                    continue
                seen.add(ad_id)

                data = ad_data_map.get(ad_id, {})
                data["thumbnail_url"] = row.get("thumbnail_url", "")
                data["ad_name"] = row.get("ad_name", "")
                data["ad_copy"] = row.get("ad_copy") or ""
                data["campaign_id"] = row.get("meta_campaign_id", "")
                data["meta_video_id"] = row.get("meta_video_id")
                data["is_video"] = row.get("is_video", False)
                data["object_type"] = row.get("object_type", "unknown")

                video_views = _safe_numeric(row.get("video_views"))
                if not data["meta_video_id"] and video_views and video_views > 0:
                    data["is_video"] = True

                if not data.get("ad_copy"):
                    data["ad_copy"] = data.get("ad_name", "")

                ad_data_map[ad_id] = data
        except Exception as e:
            logger.warning(f"Batch prefetch perf failed: {e}")

        # --- Query 2: meta_ad_destinations (bulk) ---
        canonical_urls: Dict[str, str] = {}  # ad_id -> canonical_url
        try:
            dest_result = self.supabase.table("meta_ad_destinations").select(
                "meta_ad_id, canonical_url, destination_url"
            ).eq(
                "brand_id", brand_str
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).execute()

            for row in (dest_result.data or []):
                ad_id = row.get("meta_ad_id")
                if ad_id and row.get("canonical_url"):
                    canonical_urls[ad_id] = row["canonical_url"]
        except Exception as e:
            logger.warning(f"Batch prefetch destinations failed: {e}")

        # --- Query 3: brand_landing_pages (bulk by canonical URLs) ---
        if canonical_urls:
            unique_urls = list(set(canonical_urls.values()))
            try:
                lp_result = self.supabase.table("brand_landing_pages").select(
                    "id, url, page_title, extracted_data, benefits, features, "
                    "call_to_action, product_name, raw_markdown, canonical_url"
                ).eq(
                    "brand_id", brand_str
                ).in_(
                    "canonical_url", unique_urls
                ).execute()

                # Index LPs by canonical_url
                lp_by_url: Dict[str, Dict] = {}
                for lp in (lp_result.data or []):
                    curl = lp.get("canonical_url")
                    if curl:
                        lp_by_url[curl] = lp

                # Map back to ads
                for ad_id, curl in canonical_urls.items():
                    lp = lp_by_url.get(curl)
                    if lp:
                        data = ad_data_map.get(ad_id, {})
                        data["landing_page_id"] = lp["id"]
                        data["lp_data"] = lp
                        ad_data_map[ad_id] = data
            except Exception as e:
                logger.warning(f"Batch prefetch landing pages failed: {e}")

        # --- Query 3b: meta_ad_assets for video ads (bulk) ---
        video_ad_ids = [
            ad_id for ad_id, data in ad_data_map.items()
            if data.get("is_video")
        ]
        if video_ad_ids:
            try:
                asset_result = self.supabase.table("meta_ad_assets").select(
                    "meta_ad_id"
                ).eq(
                    "asset_type", "video"
                ).eq(
                    "status", "downloaded"
                ).in_(
                    "meta_ad_id", video_ad_ids
                ).execute()

                video_in_storage = {
                    row["meta_ad_id"] for row in (asset_result.data or [])
                }
                for ad_id in video_ad_ids:
                    ad_data_map[ad_id]["has_video_in_storage"] = ad_id in video_in_storage
            except Exception as e:
                logger.warning(f"Batch prefetch video assets failed: {e}")

        # --- Query 4: ad_creative_classifications (bulk) ---
        classifications_map: Dict[str, List[Dict]] = {
            ad_id: [] for ad_id in meta_ad_ids
        }
        try:
            cls_limit = max(1000, len(meta_ad_ids) * 3)
            cls_result = self.supabase.table("ad_creative_classifications").select(
                "*"
            ).eq(
                "brand_id", brand_str
            ).eq(
                "prompt_version", self.CURRENT_PROMPT_VERSION
            ).eq(
                "schema_version", self.CURRENT_SCHEMA_VERSION
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).order("classified_at", desc=True).limit(cls_limit).execute()

            for row in (cls_result.data or []):
                ad_id = row.get("meta_ad_id")
                if ad_id in classifications_map:
                    classifications_map[ad_id].append(row)
        except Exception as e:
            logger.warning(f"Batch prefetch classifications failed: {e}")

        # --- Query 5: CURRENT-version ad_video_analysis ids (video classify-once) ---
        # Map analysis_id -> prompt_version so the cache decision can tell whether a
        # video ad's cached classification points at a CURRENT-version deep analysis.
        # The video-analysis prompt is versioned independently of this classifier's
        # prompt_version, so a video-prompt bump must invalidate classify-once for
        # video ads (see _video_analysis_is_stale).
        #
        # Scoped to the current version on purpose: ad_video_analysis is append-only,
        # so a single ad accumulates one row per prompt version (v1/v2/v3...). Filtering
        # to the current version keeps the map at ~1 row/ad, so the row cap is
        # effectively unreachable and a linked-but-OLD analysis is simply absent from
        # the map (-> correctly treated as stale by _video_analysis_is_stale).
        video_analysis_versions: Dict[str, str] = {}
        try:
            va_limit = max(1000, len(meta_ad_ids) * 3)
            va_result = self.supabase.table("ad_video_analysis").select(
                "id, prompt_version"
            ).eq(
                "brand_id", brand_str
            ).eq(
                "prompt_version", VIDEO_ANALYSIS_PROMPT_VERSION
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).limit(va_limit).execute()
            for row in (va_result.data or []):
                vid = row.get("id")
                if vid:
                    video_analysis_versions[str(vid)] = row.get("prompt_version")
        except Exception as e:
            logger.warning(f"Batch prefetch video-analysis versions failed: {e}")

        # --- Query 6: CURRENT-version ad_image_analysis ids (image classify-once) ---
        # Symmetric to Query 5 for static images. ImageAnalysisService versions its
        # prompt independently of this classifier, so an image-prompt bump must
        # invalidate classify-once for image ads (see _image_analysis_is_stale).
        # Scoped to the current version: ad_image_analysis is append-only (one row per
        # prompt version per ad), so the map stays ~1 row/ad and a linked-but-OLD
        # analysis is simply absent (-> correctly treated as stale).
        image_analysis_versions: Dict[str, str] = {}
        try:
            ia_limit = max(1000, len(meta_ad_ids) * 3)
            ia_result = self.supabase.table("ad_image_analysis").select(
                "id, prompt_version"
            ).eq(
                "brand_id", brand_str
            ).eq(
                "prompt_version", IMAGE_ANALYSIS_PROMPT_VERSION
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).limit(ia_limit).execute()
            for row in (ia_result.data or []):
                iid = row.get("id")
                if iid:
                    image_analysis_versions[str(iid)] = row.get("prompt_version")
        except Exception as e:
            logger.warning(f"Batch prefetch image-analysis versions failed: {e}")

        # --- Query 7: CURRENT-version low_res markers (image churn-stop) ---
        # ImageAnalysisService persists a status='low_res' marker for 64x64-thumbnail
        # ads it can't read. An ad with a current-version low_res marker is SETTLED: the
        # classify loop skips it so we stop re-downloading + re-decoding it every run. The
        # marker is permanent until a future high-res re-fetch clears it (no timestamp
        # re-open: meta_ad_assets has no downloaded_at and the asset job does not
        # re-download). No classification row is involved, so no consumer is poisoned.
        low_res_marker_ids: set = set()
        try:
            lr_limit = max(1000, len(meta_ad_ids) * 3)
            lr_result = self.supabase.table("ad_image_analysis").select(
                "meta_ad_id"
            ).eq(
                "brand_id", brand_str
            ).eq(
                "status", "low_res"
            ).eq(
                "prompt_version", IMAGE_ANALYSIS_PROMPT_VERSION
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).limit(lr_limit).execute()
            for row in (lr_result.data or []):
                mid = row.get("meta_ad_id")
                if mid:
                    low_res_marker_ids.add(mid)
        except Exception as e:
            logger.warning(f"Batch prefetch low_res markers failed: {e}")

        logger.info(
            f"Batch prefetch complete for {len(meta_ad_ids)} ads: "
            f"{len(canonical_urls)} destinations, "
            f"{len(video_ad_ids)} video ads, "
            f"{sum(len(v) for v in classifications_map.values())} cached classifications, "
            f"{len(video_analysis_versions)} video analyses, "
            f"{len(image_analysis_versions)} image analyses, "
            f"{len(low_res_marker_ids)} low_res markers"
        )

        return (
            ad_data_map,
            classifications_map,
            video_analysis_versions,
            image_analysis_versions,
            low_res_marker_ids,
        )

    def _match_prefetched_classification(
        self,
        cached_rows: List[Dict],
        force: bool = False,
    ) -> Optional[Dict]:
        """Return a reusable classification for this ad, or None to (re)classify.

        The prefetch already filters rows to the CURRENT prompt+schema version, so
        a non-empty ``cached_rows`` means this ad is already classified at the
        current version. Meta ad creatives are immutable (you create a NEW ad to
        change a creative), so that classification is reusable — we deliberately do
        NOT compare input_hash. Gating on input_hash (built from the rotating signed
        thumbnail URL + re-fetched ad_copy/LP) caused already-classified ads to miss
        cache and be re-run every batch, wasting the max_new budget.

        We also intentionally do NOT apply time-based staleness (stale_after) here:
        because creatives are immutable, the only reasons to re-classify are a
        prompt/schema bump (the prefetch filter excludes those rows automatically)
        or an explicit force. (The single classify_ad() path still honors stale_after
        for on-demand re-classification.) Skipped ads — e.g. skipped_missing_image —
        are NOT persisted, so a skip is retried every run until it succeeds; only
        successful classifications land here as reusable rows.

        Args:
            cached_rows: Prefetched current-version classification rows for this ad
                (already ordered by classified_at desc).
            force: If True, never reuse (caller wants a fresh classification).

        Returns:
            The most-recent reusable row, or None.
        """
        if force or not cached_rows:
            return None
        return cached_rows[0]  # most recent (rows are ordered classified_at desc)

    def _video_analysis_is_stale(
        self,
        cached_row: Dict,
        ad_data: Dict,
        video_analysis_versions: Dict[str, str],
    ) -> bool:
        """True if this cached classification is for a VIDEO ad whose linked deep
        analysis is NOT at the current video-analysis prompt version (so it must be
        re-analyzed despite being a current-version classification).

        Classify-once normally treats any current prompt+schema classification as
        reusable. But the video deep-analysis prompt (VideoAnalysisService) is
        versioned INDEPENDENTLY of this classifier's CURRENT_PROMPT_VERSION, so:
          - a video-prompt bump (e.g. v2 -> v3 opening/ending) would otherwise
            leave the old whole-video awareness cached forever, and
          - the convergence hole where the analysis row saved but the classifier
            row never linked it would never self-heal,
        unless we require the cached row's OWN video_analysis_id to resolve to a
        CURRENT-version analysis — not merely that some current analysis exists.

        Image/other ads return False (stay cached) — this is O(1) and never touches
        the network.
        """
        is_video = bool(ad_data.get("is_video")) or str(
            cached_row.get("creative_format") or ""
        ).startswith("video")
        if not is_video:
            return False
        va_id = cached_row.get("video_analysis_id")
        if not va_id:
            # Video ad whose cached classification was never linked to a deep
            # analysis -> it has no real opening-awareness; (re)analyze it.
            return True
        # Missing from the map (deleted/other-brand) or an older version -> stale.
        return video_analysis_versions.get(str(va_id)) != VIDEO_ANALYSIS_PROMPT_VERSION

    def _image_analysis_is_stale(
        self,
        cached_row: Dict,
        ad_data: Dict,
        image_analysis_versions: Dict[str, str],
    ) -> bool:
        """True if this cached classification is for a STATIC (image) ad whose linked
        deep image analysis is NOT at the current image-analysis prompt version (so it
        must be re-analyzed despite being a current-version classification).

        Symmetric to _video_analysis_is_stale. ImageAnalysisService versions its prompt
        INDEPENDENTLY of this classifier's CURRENT_PROMPT_VERSION, so an image-prompt bump
        (or an OLD light/legacy classification that predates the deep path) must invalidate
        image classify-once. Because the wired image path is deep-or-SKIP, the only
        PERSISTED non-video outcome is a current-version deep row, so this converges:
          - current deep row -> fresh (cached),
          - bumped/legacy/unlinked -> stale -> re-run -> deep success persists a current
            row (then fresh), or skip (NOT persisted: the old row remains and is re-checked
            cheaply each run — no Gemini call, no max_new budget, same as video's
            not-in-storage path).

        Returns False when the deep image service is NOT wired (no upgrade is possible —
        re-running would only hit the light path again) and for video ads (governed by
        _video_analysis_is_stale). O(1), never touches the network.
        """
        if self._image_analysis is None:
            return False
        is_video = bool(ad_data.get("is_video")) or str(
            cached_row.get("creative_format") or ""
        ).startswith("video")
        if is_video:
            return False
        # Shared rule (no drift with the digest completeness gate): an image ad is stale
        # iff its cached classification does NOT link a CURRENT-version deep image
        # analysis. image_analysis_versions is the current-version {id: prompt_version}
        # map (Query 6 filters to the current version), so membership == current. A missing
        # link (legacy/light row) -> not current -> stale; an older/deleted link -> not in
        # the map -> stale.
        return not image_link_is_current(cached_row, image_analysis_versions)

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
        content = f"{self._stable_image_key(thumbnail_url)}|{ad_copy or ''}|{lp_id or ''}|{video_id or ''}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _stable_image_key(thumbnail_url: Optional[str]) -> str:
        """Stable key for an ad's image, immune to Meta CDN signed-URL rotation.

        Meta thumbnail URLs look like
        ``https://scontent-<node>.xx.fbcdn.net/v/t45.../<imageid>_n.png?stp=...&_nc_ohc=...&_nc_oc=...``
        The PATH (with the image-id filename) is stable for a given image; the
        host (CDN node) and query string (signed/expiring params) rotate
        constantly. Keying the input hash on the full URL therefore re-fires
        classification on every refresh (one ad seen here had 55 distinct hashes
        across 58 runs). Key on the path only — it changes when the image changes,
        not when the signed URL is refreshed.
        """
        if not thumbnail_url:
            return ""
        try:
            return urlparse(thumbnail_url).path or thumbnail_url
        except Exception:
            return thumbnail_url

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
        result = {"meta_ad_id": meta_ad_id}

        # Get thumbnail, ad copy, and video metadata from meta_ads_performance
        try:
            perf_result = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url, ad_name, ad_copy, meta_campaign_id, meta_video_id, is_video, video_views, object_type"
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
                result["ad_copy"] = row.get("ad_copy") or ""
                result["campaign_id"] = row.get("meta_campaign_id", "")
                result["meta_video_id"] = row.get("meta_video_id")
                result["is_video"] = row.get("is_video", False)
                result["object_type"] = row.get("object_type", "unknown")

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

        # Use ad_copy from meta_ads_performance if populated (extracted from
        # object_story_spec by _fetch_thumbnails_sync). Fall back to ad_name.
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
            "awareness_level_opening": result.awareness_level_opening,
            "awareness_level_opening_confidence": result.awareness_level_opening_confidence,
            "awareness_level_ending": result.awareness_level_ending,
            "awareness_level_ending_confidence": result.awareness_level_ending_confidence,
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
            # Awareness level — bucket by the OPENING (entry temperature), not the
            # whole-video label. result.awareness_level is kept == opening, but be
            # explicit and fall back if a stale/under-filled result lacks opening.
            "creative_awareness_level": result.awareness_level_opening or result.awareness_level,
            "creative_awareness_confidence": result.awareness_level_opening_confidence or result.awareness_confidence,
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

    def _get_latest_caption(self, meta_ad_id: str, brand_id: UUID) -> Optional[str]:
        """Return the most-recent NON-EMPTY Facebook caption (ad_copy) for this ad.

        For copy-awareness only. Deliberately does NOT apply the ad_name fallback that
        _fetch_ad_data uses — an internal ad name (e.g. 'POV - Emoji- cortisol reducer')
        is not a caption, and judging its awareness is noise. Scans recent perf rows
        because Martin's LATEST row is often a placeholder refresh with empty ad_copy
        while the real caption lives in an earlier row. Returns None when the ad genuinely
        has no caption (copy awareness is then skipped and congruence is not computed).
        """
        try:
            rows = self.supabase.table("meta_ads_performance").select(
                "ad_copy, date"
            ).eq("brand_id", str(brand_id)).eq(
                "meta_ad_id", meta_ad_id
            ).order("date", desc=True).limit(60).execute()
            for row in (rows.data or []):
                cap = (row.get("ad_copy") or "").strip()
                if cap:
                    return cap
        except Exception as e:
            logger.warning(f"Caption lookup failed for {meta_ad_id}: {e}")
        return None

    def _classify_image_with_analysis_service(
        self,
        meta_ad_id: str,
        brand_id,
        org_id,
        caption: Optional[str],
    ):
        """Deep static-image classification via ImageAnalysisService (D1 inline, D3 split).

        creative_awareness comes from the ON-IMAGE text/visual ONLY — the caption is NOT
        passed to the image call (exactly how the rubric was hand-calibrated), so the
        awareness bucket can never leak from the caption. copy awareness is judged
        separately from the caption (the genuine FB caption, or None).

        Returns (the caller is deep-or-SKIP — it does NOT fall back to the light path):
            - a classification dict on success,
            - the sentinel string "low_res" when the image is too small to read (caller
              skips the ad rather than persist a guessed bucket),
            - None when there is no image / a hard failure / an off-enum awareness
              (caller SKIPS the ad; it is retried next run once the asset is available).
        """
        try:
            result = self._image_analysis.analyze_image(
                meta_ad_id=meta_ad_id,
                brand_id=UUID(str(brand_id)),
                organization_id=UUID(str(org_id)),
                ad_copy=None,  # D3: creative awareness must be image-pure
            )
        except Exception as e:
            logger.error(f"ImageAnalysisService failed for {meta_ad_id}: {e}")
            return None

        if result is None:
            # No image in storage / hard failure — caller SKIPS this ad (deep-or-skip);
            # it does NOT fall back to the light path when the deep service is wired.
            return None
        if getattr(result, "status", None) == "low_res":
            return "low_res"
        if getattr(result, "status", None) != "ok" or not result.awareness_level:
            # Parse error or an off-enum/empty awareness (normalized to None) — caller
            # SKIPS (retried next run); never the light path.
            return None

        return self._map_image_analysis_to_classification(result, caption)

    def _map_image_analysis_to_classification(self, result, caption: Optional[str]) -> Dict:
        """Map an ImageAnalysisResult to the classification schema.

        creative_awareness <- the deep image analysis (on-image text/visual). copy_awareness
        is a SEPARATE text-only judgment of the caption (D3 — the two never see each other's
        input). Static ads are a single moment: no opening/ending, no duration.

        Args:
            result: ImageAnalysisResult from deep analysis.
            caption: The genuine Facebook caption (or None), judged separately for copy
                awareness.

        Returns:
            Dict with classification fields.
        """
        copy_level, copy_conf = self._classify_copy_awareness(caption)

        # Map imagery_type -> creative_format. MUST stay within the DB CHECK constraint
        # ad_creative_classifications_creative_format_check, whose only image values are
        # image_static / image_before_after / image_testimonial / image_product. Anything
        # else (lifestyle, infographic, ugc, meme, screenshot, unknown) maps to the
        # generic image_static bucket — awareness (the digest signal) is unaffected; this
        # is only the coarse format tag, matching the legacy light path's vocabulary.
        imagery_type = (result.visual_style or {}).get("imagery_type")
        format_mapping = {
            "product_hero": "image_product",
            "before_after": "image_before_after",
            "testimonial_card": "image_testimonial",
        }
        creative_format = format_mapping.get(imagery_type, "image_static")
        # Belt-and-suspenders: never emit a value outside the DB CHECK constraint.
        if creative_format not in IMAGE_CREATIVE_FORMATS:
            creative_format = "image_static"

        raw_classification = {
            "messaging_theme": result.messaging_theme,
            "headline_text": result.headline_text,
            "body_text": result.body_text,
            "text_overlays": result.text_overlays,
            "hook_pattern": result.hook_pattern,
            "cta_style": result.cta_style,
            "benefits_shown": result.benefits_shown,
            "pain_points_addressed": result.pain_points_addressed,
            "claims_made": result.claims_made,
            "visual_style": result.visual_style,
            "awareness_level": result.awareness_level,
            "awareness_confidence": result.awareness_confidence,
            "input_hash": result.input_hash,
            "prompt_version": result.prompt_version,
        }

        return {
            # Creative awareness from the on-image text/visual (calibrated rubric).
            # Normalize defensively: ImageAnalysisService already normalizes, but a row
            # stored before that fix (or any off-enum value) must degrade to NULL rather
            # than violate the creative_awareness_level CHECK constraint on insert —
            # matching how every legacy path handles awareness.
            "creative_awareness_level": self._normalize_awareness(result.awareness_level),
            "creative_awareness_confidence": result.awareness_confidence,
            "creative_format": creative_format,
            "creative_angle": result.messaging_theme,
            # Copy awareness judged separately from the FB caption (D3)
            "copy_awareness_level": copy_level,
            "copy_awareness_confidence": copy_conf,
            "hook_type": result.hook_pattern,
            "primary_cta": result.cta_style,
            # Link to the deep image-analysis row (parallel to video_analysis_id)
            "image_analysis_id": str(result.analysis_id) if result.analysis_id else None,
            "model_used": "gemini_image_deep",
            "raw_classification": raw_classification,
        }

    def _classify_copy_awareness(self, ad_copy: Optional[str]):
        """Judge the awareness level of the Facebook caption (copy) as text only.

        Kept separate from the image's creative awareness (D3) so creative<->copy
        congruence stays meaningful. Returns (level, confidence), or (None, None) when
        there is no copy or the call fails (congruence then simply isn't computed).
        """
        if not ad_copy or not ad_copy.strip():
            return None, None
        try:
            from ...core.genai_client import make_genai_client

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("GEMINI_API_KEY not set — skipping copy awareness")
                return None, None

            client = make_genai_client(api_key)
            prompt = COPY_AWARENESS_PROMPT.format(
                awareness_rubric=AWARENESS_RUBRIC,
                ad_copy=ad_copy[:4000],
            )
            response = client.models.generate_content(
                model=VIDEO_ANALYSIS_MODEL,
                contents=[prompt],
            )
            parsed = self._parse_gemini_response(response.text or "")
            if not parsed:
                return None, None
            return (
                parsed.get("copy_awareness_level"),
                parsed.get("copy_awareness_confidence"),
            )
        except Exception as e:
            logger.warning(f"Copy awareness classification failed: {e}")
            return None, None

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
            # make_genai_client was used below but never imported (PR #180
            # regression) — left this legacy video path raising NameError.
            from ...core.genai_client import make_genai_client

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

            client = make_genai_client(api_key)
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
                ad_copy=ad_copy or "(no copy available)",
                awareness_rubric=AWARENESS_RUBRIC,
            )
            response = client.models.generate_content(
                model=VIDEO_ANALYSIS_MODEL,
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
        ad_data: Dict,
        ad_copy: str,
    ) -> Optional[Dict]:
        """Run lightweight Gemini classification on ad image + copy.

        Tries stored image from meta_ad_assets first (permanent, reliable),
        then falls back to the thumbnail_url (may expire). If neither source
        provides an image, returns None to signal the caller to skip.

        Args:
            ad_data: Dict from _fetch_ad_data with thumbnail_url, meta_ad_id,
                     object_type, lp_data etc.
            ad_copy: Ad copy text.

        Returns:
            Dict with classification fields including ``_media_source``
            (``"stored"`` or ``"thumbnail"``), or None if no image available.
        """
        meta_ad_id = ad_data.get("meta_ad_id")
        thumbnail_url = ad_data.get("thumbnail_url")
        object_type = ad_data.get("object_type", "unknown")

        if self._gemini is not None:
            gemini = self._gemini
        else:
            from ...services.gemini_service import GeminiService
            logger.warning("No shared GeminiService provided, creating new instance (no rate limiting)")
            gemini = GeminiService()
        prompt = CLASSIFICATION_PROMPT.format(ad_copy=ad_copy or "(no copy available)")

        image_bytes = None
        media_source = None
        storage_path = None

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

        # 3. Skip if no image available — log with reason codes
        if not image_bytes:
            reason = "unknown"
            nd_reason = None
            if meta_ad_id:
                try:
                    nd_result = self.supabase.table("meta_ad_assets").select(
                        "status, not_downloadable_reason"
                    ).eq("meta_ad_id", meta_ad_id).eq("asset_type", "image").limit(1).execute()
                    if nd_result.data and nd_result.data[0].get("status") == "not_downloadable":
                        reason = "asset_not_downloadable"
                        nd_reason = nd_result.data[0].get("not_downloadable_reason")
                except Exception:
                    pass

            if reason == "unknown":
                if not meta_ad_id:
                    reason = "no_meta_ad_id"
                elif not storage_path and not thumbnail_url:
                    reason = "no_image_source"
                elif storage_path and not image_bytes:
                    reason = "storage_download_failed"
                elif thumbnail_url and not image_bytes:
                    reason = "thumbnail_expired"

            logger.warning(
                f"No image available for {meta_ad_id or 'unknown'} "
                f"(object_type={object_type}, reason={reason}"
                f"{f', nd_reason={nd_reason}' if nd_reason else ''}), "
                f"skipping classification."
            )
            return None

        # 4. Classify with image
        import base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        result_text = await gemini.analyze_image_async(image_b64, prompt)

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
            image_analysis_id=UUID(row["image_analysis_id"]) if row.get("image_analysis_id") else None,
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
            image_analysis_id=UUID(record["image_analysis_id"]) if record.get("image_analysis_id") else None,
            source=record.get("source", "gemini_light"),
            prompt_version=record.get("prompt_version", "v1"),
            schema_version=record.get("schema_version", "1.0"),
            input_hash=record.get("input_hash"),
        )
