"""Unit tests for InstagramAnalysisService.

Tests eval checks (VA-1 through VA-8), input hashing, JSON parsing,
and service method logic with mocked Gemini and Supabase dependencies.
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from viraltracker.services.instagram_analysis_service import (
    InstagramAnalysisService,
    compute_input_hash,
    run_eval_checks,
    EvalScores,
    _parse_json_response,
    PASS1_PROMPT_VERSION,
    IMAGE_PROMPT_VERSION,
    FLASH_MODEL,
    PRO_MODEL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    """Mock Supabase client with fluent API."""
    mock = MagicMock()

    table = MagicMock()
    table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "analysis-1"}])
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mock.table.return_value = table

    storage_bucket = MagicMock()
    storage_bucket.download.return_value = b"fake video content"
    mock.storage.from_.return_value = storage_bucket

    return mock


@pytest.fixture
def service(mock_supabase):
    """Create InstagramAnalysisService with mocked Supabase."""
    with patch(
        "viraltracker.services.instagram_analysis_service.get_supabase_client",
        return_value=mock_supabase,
    ):
        svc = InstagramAnalysisService(supabase=mock_supabase)
    return svc


# ---------------------------------------------------------------------------
# compute_input_hash
# ---------------------------------------------------------------------------

class TestComputeInputHash:
    """Tests for input hash computation."""

    def test_hash_with_file_size(self):
        expected = hashlib.sha256(b"path/to/file.mp4:12345").hexdigest()
        assert compute_input_hash("path/to/file.mp4", file_size=12345) == expected

    def test_hash_without_file_size(self):
        expected = hashlib.sha256(b"path/to/file.mp4:unknown").hexdigest()
        assert compute_input_hash("path/to/file.mp4") == expected

    def test_different_paths_different_hashes(self):
        h1 = compute_input_hash("path/a.mp4", 100)
        h2 = compute_input_hash("path/b.mp4", 100)
        assert h1 != h2

    def test_different_sizes_different_hashes(self):
        h1 = compute_input_hash("path/a.mp4", 100)
        h2 = compute_input_hash("path/a.mp4", 200)
        assert h1 != h2

    def test_same_inputs_same_hash(self):
        h1 = compute_input_hash("path/a.mp4", 100)
        h2 = compute_input_hash("path/a.mp4", 100)
        assert h1 == h2


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    """Tests for Gemini response JSON parsing."""

    def test_plain_json(self):
        data = {"key": "value", "number": 42}
        result = _parse_json_response(json.dumps(data))
        assert result == data

    def test_json_in_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_in_code_block_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_empty_string(self):
        assert _parse_json_response("") is None

    def test_none(self):
        assert _parse_json_response(None) is None

    def test_invalid_json(self):
        assert _parse_json_response("not json at all") is None

    def test_complex_nested_json(self):
        data = {
            "storyboard": [
                {"timestamp_sec": 0.0, "scene_description": "test"},
                {"timestamp_sec": 5.0, "scene_description": "test2"},
            ],
            "full_transcript": "Hello world",
        }
        result = _parse_json_response(json.dumps(data))
        assert result["storyboard"][0]["timestamp_sec"] == 0.0


# ---------------------------------------------------------------------------
# run_eval_checks (VA-1 through VA-8)
# ---------------------------------------------------------------------------

class TestEvalChecks:
    """Tests for VA-1 through VA-8 consistency checks."""

    def _make_good_parsed(self) -> dict:
        """Create a well-formed analysis response that should pass all checks."""
        return {
            "video_duration_sec": 30.0,
            "full_transcript": "This is a test transcript that is definitely long enough to pass the check.",
            "transcript_segments": [
                {"start_sec": 0.0, "end_sec": 10.0, "text": "First segment"},
                {"start_sec": 10.0, "end_sec": 20.0, "text": "Second segment"},
                {"start_sec": 20.0, "end_sec": 28.0, "text": "Third segment"},
            ],
            "text_overlays": [
                {"start_sec": 0.0, "end_sec": 5.0, "text": "Hook text"}
            ],
            "text_overlay_confidence": 0.8,
            "storyboard": [
                {"timestamp_sec": 0.0, "scene_description": "Opening"},
                {"timestamp_sec": 10.0, "scene_description": "Middle"},
                {"timestamp_sec": 22.0, "scene_description": "End"},
            ],
            "hook_transcript_spoken": "Hey check this out",
            "hook_type": "callout",
            "hook_visual_description": "Person waving at camera",
            "people_detected": 1,
            "has_talking_head": True,
            "production_quality": "polished",
            "format_type": "ugc",
        }

    def test_all_checks_pass(self):
        """A well-formed response should get high overall score."""
        parsed = self._make_good_parsed()
        scores = run_eval_checks(parsed, actual_duration_sec=30.0)
        assert scores.overall_score >= 0.8
        assert scores.va1_duration_match == 1.0
        assert scores.va2_transcript_present == 1.0
        assert scores.va4_timestamp_monotonicity == 1.0
        assert scores.va7_json_completeness == 1.0

    def test_va1_duration_match_pass(self):
        """VA-1: Duration within 2s tolerance should pass."""
        parsed = {"video_duration_sec": 31.0}
        scores = run_eval_checks(parsed, actual_duration_sec=30.0)
        assert scores.va1_duration_match == 1.0

    def test_va1_duration_match_fail(self):
        """VA-1: Duration > 2s off should fail."""
        parsed = {"video_duration_sec": 40.0}
        scores = run_eval_checks(parsed, actual_duration_sec=30.0)
        assert scores.va1_duration_match == 0.0

    def test_va1_no_actual_duration(self):
        """VA-1: When no actual duration known, skip check."""
        parsed = {"video_duration_sec": 30.0}
        scores = run_eval_checks(parsed, actual_duration_sec=None)
        assert scores.va1_duration_match is None

    def test_va2_transcript_present(self):
        """VA-2: Non-empty transcript passes."""
        parsed = {"full_transcript": "This is a sufficient transcript."}
        scores = run_eval_checks(parsed)
        assert scores.va2_transcript_present == 1.0

    def test_va2_transcript_empty(self):
        """VA-2: Empty/short transcript fails."""
        parsed = {"full_transcript": "Hi"}
        scores = run_eval_checks(parsed)
        assert scores.va2_transcript_present == 0.0

    def test_va2_animation_partial_pass(self):
        """VA-2: Animation format gets partial pass for missing transcript."""
        parsed = {"full_transcript": "", "format_type": "animation"}
        scores = run_eval_checks(parsed)
        assert scores.va2_transcript_present == 0.5

    def test_va3_storyboard_coverage_good(self):
        """VA-3: Storyboard covering >= 70% of duration passes."""
        parsed = {
            "video_duration_sec": 30.0,
            "storyboard": [
                {"timestamp_sec": 0.0},
                {"timestamp_sec": 15.0},
                {"timestamp_sec": 25.0},
            ],
        }
        scores = run_eval_checks(parsed)
        assert scores.va3_storyboard_coverage is not None
        assert scores.va3_storyboard_coverage > 0.9

    def test_va3_storyboard_coverage_poor(self):
        """VA-3: Storyboard only covering first 10% should score low."""
        parsed = {
            "video_duration_sec": 100.0,
            "storyboard": [{"timestamp_sec": 0.0}, {"timestamp_sec": 5.0}],
        }
        scores = run_eval_checks(parsed)
        assert scores.va3_storyboard_coverage is not None
        assert scores.va3_storyboard_coverage < 0.2

    def test_va4_timestamps_monotonic(self):
        """VA-4: Properly ordered timestamps pass."""
        parsed = {
            "storyboard": [
                {"timestamp_sec": 0.0},
                {"timestamp_sec": 5.0},
                {"timestamp_sec": 10.0},
            ]
        }
        scores = run_eval_checks(parsed)
        assert scores.va4_timestamp_monotonicity == 1.0

    def test_va4_timestamps_not_monotonic(self):
        """VA-4: Out-of-order timestamps fail."""
        parsed = {
            "storyboard": [
                {"timestamp_sec": 0.0},
                {"timestamp_sec": 10.0},
                {"timestamp_sec": 5.0},
            ]
        }
        scores = run_eval_checks(parsed)
        assert scores.va4_timestamp_monotonicity == 0.0

    def test_va5_segment_coverage(self):
        """VA-5: Segments covering >= 60% of duration pass."""
        parsed = {
            "video_duration_sec": 30.0,
            "transcript_segments": [
                {"start_sec": 0.0, "end_sec": 10.0, "text": "a"},
                {"start_sec": 10.0, "end_sec": 25.0, "text": "b"},
            ],
        }
        scores = run_eval_checks(parsed)
        assert scores.va5_segment_coverage == 1.0

    def test_va5_segment_coverage_low(self):
        """VA-5: Short segment coverage scores lower."""
        parsed = {
            "video_duration_sec": 60.0,
            "transcript_segments": [
                {"start_sec": 0.0, "end_sec": 5.0, "text": "a"},
            ],
        }
        scores = run_eval_checks(parsed)
        assert scores.va5_segment_coverage is not None
        assert scores.va5_segment_coverage < 0.5

    def test_va6_hook_window_all_present(self):
        """VA-6: All hook fields present when transcript exists."""
        parsed = {
            "full_transcript": "A sufficient transcript for the check to work.",
            "hook_transcript_spoken": "Hey check this out",
            "hook_type": "callout",
            "hook_visual_description": "Person waving",
        }
        scores = run_eval_checks(parsed)
        assert scores.va6_hook_window == 1.0

    def test_va6_hook_window_partial(self):
        """VA-6: Only some hook fields present."""
        parsed = {
            "full_transcript": "A sufficient transcript for the check to work.",
            "hook_transcript_spoken": "Hey",
            "hook_type": None,
            "hook_visual_description": None,
        }
        scores = run_eval_checks(parsed)
        assert 0.0 < scores.va6_hook_window < 1.0

    def test_va6_hook_window_no_transcript(self):
        """VA-6: No transcript = N/A = pass."""
        parsed = {"full_transcript": ""}
        scores = run_eval_checks(parsed)
        assert scores.va6_hook_window == 1.0

    def test_va7_json_completeness_all_keys(self):
        """VA-7: All required keys present."""
        parsed = self._make_good_parsed()
        scores = run_eval_checks(parsed)
        assert scores.va7_json_completeness == 1.0

    def test_va7_json_completeness_missing_keys(self):
        """VA-7: Missing required keys reduce score."""
        parsed = {"video_duration_sec": 30}  # Only 1 of 7 keys
        scores = run_eval_checks(parsed)
        assert scores.va7_json_completeness < 0.5

    def test_va8_overlay_coherence_no_overlays_no_confidence(self):
        """VA-8: No overlays + no confidence = coherent."""
        parsed = {"text_overlays": [], "text_overlay_confidence": None}
        scores = run_eval_checks(parsed)
        assert scores.va8_overlay_coherence == 1.0

    def test_va8_overlay_coherence_no_overlays_with_confidence(self):
        """VA-8: No overlays but confidence > 0 = incoherent."""
        parsed = {"text_overlays": [], "text_overlay_confidence": 0.8}
        scores = run_eval_checks(parsed)
        assert scores.va8_overlay_coherence == 0.0

    def test_va8_overlay_coherence_overlays_with_confidence(self):
        """VA-8: Has overlays + confidence > 0 = coherent."""
        parsed = {
            "text_overlays": [{"start_sec": 0, "text": "Hi"}],
            "text_overlay_confidence": 0.9,
        }
        scores = run_eval_checks(parsed)
        assert scores.va8_overlay_coherence == 1.0

    def test_overall_score_is_average(self):
        """Overall score should be the mean of all checks that ran."""
        parsed = self._make_good_parsed()
        scores = run_eval_checks(parsed, actual_duration_sec=30.0)
        # All checks should pass, overall should be high
        assert 0.8 <= scores.overall_score <= 1.0


# ---------------------------------------------------------------------------
# EvalScores
# ---------------------------------------------------------------------------

class TestEvalScores:
    """Tests for EvalScores dataclass."""

    def test_to_dict(self):
        scores = EvalScores(
            va1_duration_match=1.0,
            va2_transcript_present=0.5,
            overall_score=0.75,
        )
        d = scores.to_dict()
        assert d["va1_duration_match"] == 1.0
        assert d["va2_transcript_present"] == 0.5
        assert d["overall_score"] == 0.75
        assert "va3_storyboard_coverage" in d

    def test_default_values(self):
        scores = EvalScores()
        assert scores.overall_score == 0.0
        assert scores.va1_duration_match is None


# ---------------------------------------------------------------------------
# Service: get_analysis
# ---------------------------------------------------------------------------

class TestGetAnalysis:
    """Tests for get_analysis method."""

    def test_returns_video_analysis(self, service, mock_supabase):
        """Returns video analysis when it exists."""
        video_data = {"id": "v-1", "source_type": "instagram_scrape", "status": "ok"}

        # Mock: video analysis found
        video_chain = MagicMock()
        video_chain.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[video_data])

        # Mock: image analysis (won't be checked since video found first)
        image_chain = MagicMock()
        image_chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        def table_router(name):
            t = MagicMock()
            if name == "ad_video_analysis":
                t.select.return_value = video_chain
            elif name == "instagram_image_analysis":
                t.select.return_value = image_chain
            return t

        mock_supabase.table.side_effect = table_router

        result = service.get_analysis("post-1")
        assert result is not None
        assert result["_analysis_type"] == "video"

    def test_returns_image_analysis_when_no_video(self, service, mock_supabase):
        """Falls back to image analysis when no video analysis exists."""
        image_data = {"id": "i-1", "status": "ok"}

        video_chain = MagicMock()
        video_chain.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        image_chain = MagicMock()
        image_chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[image_data])

        def table_router(name):
            t = MagicMock()
            if name == "ad_video_analysis":
                t.select.return_value = video_chain
            elif name == "instagram_image_analysis":
                t.select.return_value = image_chain
            return t

        mock_supabase.table.side_effect = table_router

        result = service.get_analysis("post-1")
        assert result is not None
        assert result["_analysis_type"] == "image"

    def test_returns_none_when_no_analysis(self, service, mock_supabase):
        """Returns None when no analysis exists."""
        empty_chain = MagicMock()
        empty_chain.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        empty_chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        def table_router(name):
            t = MagicMock()
            t.select.return_value = empty_chain
            return t

        mock_supabase.table.side_effect = table_router

        result = service.get_analysis("post-1")
        assert result is None


# ---------------------------------------------------------------------------
# Service: internal helpers
# ---------------------------------------------------------------------------

class TestInternalHelpers:
    """Tests for internal helper methods."""

    def test_get_media_record_found(self, service, mock_supabase):
        media_data = {"id": "m-1", "post_id": "p-1", "storage_path": "path/file.mp4", "media_type": "video"}

        chain = MagicMock()
        chain.eq.return_value.single.return_value.execute.return_value = MagicMock(data=media_data)
        mock_supabase.table.return_value.select.return_value = chain

        result = service._get_media_record("m-1")
        assert result == media_data

    def test_get_media_record_not_found(self, service, mock_supabase):
        chain = MagicMock()
        chain.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
        mock_supabase.table.return_value.select.return_value = chain

        result = service._get_media_record("missing")
        assert result is None

    def test_download_from_storage(self, service, mock_supabase):
        mock_supabase.storage.from_.return_value.download.return_value = b"content"
        result = service._download_from_storage("path/file.mp4")
        assert result == b"content"

    def test_download_from_storage_failure(self, service, mock_supabase):
        mock_supabase.storage.from_.return_value.download.side_effect = Exception("fail")
        result = service._download_from_storage("path/file.mp4")
        assert result is None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    """Verify constant values are set correctly."""

    def test_prompt_versions(self):
        assert PASS1_PROMPT_VERSION == "ig_v1"
        assert IMAGE_PROMPT_VERSION == "ig_img_v1"

    def test_models(self):
        assert FLASH_MODEL == "gemini-3-flash-preview"
        assert PRO_MODEL == "gemini-3.1-pro-preview"
