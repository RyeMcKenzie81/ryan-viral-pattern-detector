"""Tests for video OPENING/ENDING awareness + video classify-once staleness.

A video ad is bucketed by the awareness stage it MEETS the viewer at (its
opening, ~first 10s = entry temperature), not the most-aware stage it closes on.
The ending is captured for future journey analysis. Because the video deep-
analysis prompt is versioned independently of the classifier's prompt_version,
the classify-once cache must re-analyze a video ad whose linked analysis is stale
(or was never linked) while leaving image ads cached.

Covers:
- _map_video_analysis_to_classification buckets by OPENING, falls back to legacy.
- save_video_analysis / _fetch_existing_result persist + read the split fields,
  backfilling opening<-legacy for pre-v3 rows.
- _video_analysis_is_stale: video-prompt bump AND the convergence hole (analysis
  saved but classifier row never linked) invalidate the cache; images stay cached.

Run with: pytest tests/test_video_awareness.py -v
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from viraltracker.services.ad_intelligence.classifier_service import (
    ClassifierService,
    VIDEO_ANALYSIS_PROMPT_VERSION,
)
from viraltracker.services.video_analysis_service import (
    VideoAnalysisService,
    VideoAnalysisResult,
    PROMPT_VERSION as VIDEO_PROMPT_VERSION,
)


def _classifier():
    return ClassifierService(MagicMock())


def _result(**kw) -> VideoAnalysisResult:
    base = dict(
        meta_ad_id="ad1",
        brand_id=uuid4(),
        input_hash="h",
        prompt_version=VIDEO_PROMPT_VERSION,
        storage_path="bucket/path.mp4",
    )
    base.update(kw)
    return VideoAnalysisResult(**base)


# ---------------------------------------------------------------------------
# Mapping: creative_awareness_level <- opening (not whole-video)
# ---------------------------------------------------------------------------
class TestMappingBucketsByOpening:
    def test_creative_awareness_uses_opening_not_legacy(self):
        s = _classifier()
        r = _result(
            awareness_level="most_aware",          # whole-video label — must NOT win
            awareness_level_opening="unaware",      # entry temperature — must win
            awareness_level_opening_confidence=0.9,
            awareness_level_ending="most_aware",
            awareness_level_ending_confidence=0.8,
        )
        out = s._map_video_analysis_to_classification(r, "va-123")
        assert out["creative_awareness_level"] == "unaware"
        assert out["creative_awareness_confidence"] == 0.9
        # ending captured in raw_classification for future journey analysis
        assert out["raw_classification"]["awareness_level_ending"] == "most_aware"
        assert out["raw_classification"]["awareness_level_opening"] == "unaware"
        assert out["video_analysis_id"] == "va-123"

    def test_falls_back_to_legacy_when_opening_missing(self):
        s = _classifier()
        r = _result(awareness_level="problem_aware")  # opening None (degraded parse)
        out = s._map_video_analysis_to_classification(r, None)
        assert out["creative_awareness_level"] == "problem_aware"
        assert out["video_analysis_id"] is None


# ---------------------------------------------------------------------------
# Save + fetch plumbing (Codex: columns alone are not enough)
# ---------------------------------------------------------------------------
class TestSaveAndFetchPlumbing:
    def test_save_includes_opening_and_ending_columns(self):
        db = MagicMock()
        insert_mock = db.table.return_value.insert
        insert_mock.return_value.execute.return_value = SimpleNamespace(data=[{"id": str(uuid4())}])
        svc = VideoAnalysisService(db)

        r = _result(
            awareness_level="unaware",
            awareness_level_opening="unaware",
            awareness_level_opening_confidence=0.7,
            awareness_level_ending="most_aware",
            awareness_level_ending_confidence=0.6,
        )
        asyncio.run(svc.save_video_analysis(r, uuid4()))

        payload = insert_mock.call_args[0][0]
        assert payload["awareness_level_opening"] == "unaware"
        assert payload["awareness_level_ending"] == "most_aware"
        assert payload["awareness_level_opening_confidence"] == 0.7
        assert payload["awareness_level_ending_confidence"] == 0.6

    def test_fetch_backfills_opening_from_legacy_for_pre_v3_rows(self):
        # A pre-migration row has only awareness_level (no opening/ending columns).
        row = {
            "meta_ad_id": "ad1",
            "brand_id": str(uuid4()),
            "input_hash": "h",
            "prompt_version": "v2",
            "storage_path": "bucket/path.mp4",
            "status": "ok",
            "awareness_level": "solution_aware",
            "awareness_confidence": 0.8,
        }
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            SimpleNamespace(data=[row])
        )
        svc = VideoAnalysisService(db)

        res = asyncio.run(svc._fetch_existing_result(uuid4()))
        assert res is not None
        # opening backfilled from the legacy column; ending := opening
        assert res.awareness_level_opening == "solution_aware"
        assert res.awareness_level_ending == "solution_aware"
        assert res.awareness_level_opening_confidence == 0.8


# ---------------------------------------------------------------------------
# Video classify-once staleness (1A + convergence fix)
# ---------------------------------------------------------------------------
class TestVideoClassifyOnceStaleness:
    CUR = VIDEO_ANALYSIS_PROMPT_VERSION

    def test_image_ad_stays_cached(self):
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"creative_format": "image_static"}, {"is_video": False}, {}
        ) is False

    def test_video_current_version_cached(self):
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"creative_format": "video_ugc", "video_analysis_id": "A"},
            {"is_video": True},
            {"A": self.CUR},
        ) is False

    def test_video_stale_version_reanalyzed(self):
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"video_analysis_id": "A"}, {"is_video": True}, {"A": "v2"}
        ) is True

    def test_video_without_link_reanalyzed_convergence_hole(self):
        # analysis may have saved, but the classifier row never linked it ->
        # checking "some current analysis exists" would wrongly cache; we re-run.
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"video_analysis_id": None}, {"is_video": True}, {}
        ) is True

    def test_video_link_missing_from_map_reanalyzed(self):
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"video_analysis_id": "Z"}, {"is_video": True}, {"A": self.CUR}
        ) is True

    def test_video_detected_by_creative_format_when_ad_data_absent(self):
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"creative_format": "video_testimonial", "video_analysis_id": "A"},
            {},  # ad_data has no is_video flag
            {"A": "v2"},
        ) is True

    def test_converges_after_backfill(self):
        # once the cached row links to a current-version analysis, it stays cached
        s = _classifier()
        assert s._video_analysis_is_stale(
            {"creative_format": "video_ugc", "video_analysis_id": "A"},
            {"is_video": True},
            {"A": self.CUR},
        ) is False
