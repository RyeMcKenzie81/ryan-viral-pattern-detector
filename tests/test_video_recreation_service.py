"""Unit tests for VideoRecreationService.

Tests scoring functions, scene classification, engine routing,
duration computation, cost estimation, and service CRUD operations.

All external dependencies (Supabase, Kling, VEO, ElevenLabs, Gemini) are mocked.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from viraltracker.services.video_recreation_service import (
    # Scoring functions
    compute_engagement_score,
    compute_hook_quality_score,
    compute_recreation_feasibility,
    compute_avatar_compatibility,
    compute_composite_score,
    # Scene utilities
    classify_scenes,
    route_scene_to_engine,
    compute_nearest_veo_duration,
    compute_nearest_kling_duration,
    split_scene_if_needed,
    estimate_generation_cost,
    # Constants
    SCENE_TALKING_HEAD,
    SCENE_BROLL,
    ENGINE_KLING,
    ENGINE_VEO,
    SCORING_WEIGHTS,
    SCORING_VERSION,
    STATUS_CANDIDATE,
    STATUS_APPROVED,
    STATUS_REJECTED,
    # Service
    VideoRecreationService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    """Mock Supabase client with fluent API."""
    mock = MagicMock()

    # Default table chain
    table = MagicMock()
    table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "candidate-1"}]
    )
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "candidate-1", "status": "approved"}]
    )
    table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data=None
    )
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock.table.return_value = table

    # Storage
    storage_bucket = MagicMock()
    storage_bucket.upload.return_value = None
    storage_bucket.download.return_value = b"fake-video-data"
    storage_bucket.create_signed_url.return_value = {
        "signedURL": "https://example.com/signed"
    }
    mock.storage.from_.return_value = storage_bucket

    return mock


@pytest.fixture
def service(mock_supabase):
    """Create VideoRecreationService with mocked Supabase."""
    with patch(
        "viraltracker.services.video_recreation_service.get_supabase_client",
        return_value=mock_supabase,
    ):
        svc = VideoRecreationService(supabase=mock_supabase)
    return svc


# ---------------------------------------------------------------------------
# Engagement Score
# ---------------------------------------------------------------------------

class TestEngagementScore:
    """Tests for compute_engagement_score."""

    def test_none_returns_zero(self):
        assert compute_engagement_score(None) == 0.0

    def test_zero_outlier(self):
        assert compute_engagement_score(0.0) == 0.0

    def test_moderate_outlier(self):
        """Z-score 1.5 should be 0.5 (midpoint)."""
        result = compute_engagement_score(1.5)
        assert abs(result - 0.5) < 0.01

    def test_high_outlier(self):
        """Z-score >= 3 should be 1.0."""
        assert compute_engagement_score(3.0) == 1.0

    def test_very_high_outlier_capped(self):
        """Z-score > 3 should still be capped at 1.0."""
        assert compute_engagement_score(5.0) == 1.0

    def test_negative_outlier(self):
        """Negative Z-score should be 0.0."""
        assert compute_engagement_score(-1.0) == 0.0


# ---------------------------------------------------------------------------
# Hook Quality Score
# ---------------------------------------------------------------------------

class TestHookQualityScore:
    """Tests for compute_hook_quality_score."""

    def test_none_returns_zero(self):
        assert compute_hook_quality_score(None) == 0.0

    def test_empty_dict_returns_zero(self):
        assert compute_hook_quality_score({}) == 0.0

    def test_perfect_scores(self):
        eval_scores = {"overall_score": 1.0, "va6_hook_window": 1.0}
        result = compute_hook_quality_score(eval_scores)
        assert result == 1.0

    def test_mixed_scores(self):
        eval_scores = {"overall_score": 0.8, "va6_hook_window": 0.5}
        result = compute_hook_quality_score(eval_scores)
        # 0.8 * 0.6 + 0.5 * 0.4 = 0.48 + 0.20 = 0.68
        assert abs(result - 0.68) < 0.01

    def test_missing_hook_window(self):
        eval_scores = {"overall_score": 0.9, "va6_hook_window": None}
        result = compute_hook_quality_score(eval_scores)
        # 0.9 * 0.6 + 0.0 * 0.4 = 0.54
        assert abs(result - 0.54) < 0.01

    def test_zero_overall(self):
        eval_scores = {"overall_score": 0.0, "va6_hook_window": 0.0}
        assert compute_hook_quality_score(eval_scores) == 0.0


# ---------------------------------------------------------------------------
# Recreation Feasibility
# ---------------------------------------------------------------------------

class TestRecreationFeasibility:
    """Tests for compute_recreation_feasibility."""

    def test_none_returns_zero(self):
        assert compute_recreation_feasibility(None) == 0.0

    def test_empty_analysis(self):
        # Empty dict is falsy in Python → returns 0.0
        assert compute_recreation_feasibility({}) == 0.0

    def test_minimal_analysis(self):
        # Dict with at least one key is truthy → base score applies
        analysis = {"people_detected": 0}
        result = compute_recreation_feasibility(analysis)
        assert result == pytest.approx(0.8, abs=0.01)

    def test_single_person_boosts_score(self):
        analysis = {"people_detected": 1, "storyboard": [{}, {}, {}]}
        result = compute_recreation_feasibility(analysis)
        # 0.7 + 0.2 (single person) + 0.1 (3 scenes) = 1.0
        assert result == pytest.approx(1.0, abs=0.001)

    def test_no_people_moderate(self):
        analysis = {"people_detected": 0}
        result = compute_recreation_feasibility(analysis)
        # 0.7 + 0.1 = 0.8
        assert abs(result - 0.8) < 0.01

    def test_many_people_penalized(self):
        analysis = {"people_detected": 4}
        result = compute_recreation_feasibility(analysis)
        # 0.7 - 0.3 = 0.4
        assert abs(result - 0.4) < 0.01

    def test_skit_format_penalized(self):
        analysis = {"people_detected": 1, "format_type": "skit"}
        result = compute_recreation_feasibility(analysis)
        # 0.7 + 0.2 - 0.2 = 0.7
        assert abs(result - 0.7) < 0.01

    def test_ugc_format_boosted(self):
        analysis = {"people_detected": 1, "format_type": "ugc"}
        result = compute_recreation_feasibility(analysis)
        # 0.7 + 0.2 + 0.1 = 1.0
        assert result == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Avatar Compatibility
# ---------------------------------------------------------------------------

class TestAvatarCompatibility:
    """Tests for compute_avatar_compatibility."""

    def test_none_analysis(self):
        assert compute_avatar_compatibility(None, True) == 0.0

    def test_talking_head_with_avatar(self):
        assert compute_avatar_compatibility({"has_talking_head": True}, True) == 1.0

    def test_talking_head_without_avatar(self):
        assert compute_avatar_compatibility({"has_talking_head": True}, False) == 0.3

    def test_no_talking_head(self):
        assert compute_avatar_compatibility({"has_talking_head": False}, True) == 0.6

    def test_no_talking_head_no_avatar(self):
        assert compute_avatar_compatibility({"has_talking_head": False}, False) == 0.6


# ---------------------------------------------------------------------------
# Composite Score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    """Tests for compute_composite_score."""

    def test_all_perfect(self):
        analysis = {
            "people_detected": 1,
            "has_talking_head": True,
            "storyboard": [{}, {}, {}],
            "format_type": "ugc",
        }
        composite, components = compute_composite_score(
            outlier_score=3.0,
            eval_scores={"overall_score": 1.0, "va6_hook_window": 1.0},
            analysis=analysis,
            has_avatar=True,
        )
        assert composite == 1.0
        assert components["engagement"] == 1.0
        assert components["hook_quality"] == 1.0
        assert components["avatar_compatibility"] == 1.0

    def test_all_zero(self):
        composite, components = compute_composite_score(
            outlier_score=None,
            eval_scores=None,
            analysis=None,
            has_avatar=False,
        )
        assert composite == 0.0

    def test_weights_sum_to_one(self):
        total = sum(SCORING_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_intermediate_scores(self):
        analysis = {
            "people_detected": 1,
            "has_talking_head": False,
            "storyboard": [{}, {}],
        }
        composite, components = compute_composite_score(
            outlier_score=1.5,
            eval_scores={"overall_score": 0.7, "va6_hook_window": 0.8},
            analysis=analysis,
            has_avatar=True,
        )
        # Should be between 0 and 1
        assert 0.0 < composite < 1.0
        # Components should be reasonable
        assert abs(components["engagement"] - 0.5) < 0.01
        assert len(components) == 4


# ---------------------------------------------------------------------------
# Scene Classification
# ---------------------------------------------------------------------------

class TestClassifyScenes:
    """Tests for classify_scenes."""

    def test_empty_storyboard(self):
        assert classify_scenes([], True) == []

    def test_speaking_scene_detected(self):
        storyboard = [
            {"scene_description": "Person speaking to camera", "key_elements": ["host"]}
        ]
        result = classify_scenes(storyboard, has_talking_head=True)
        assert result == [SCENE_TALKING_HEAD]

    def test_broll_scene(self):
        storyboard = [
            {"scene_description": "Product on table", "key_elements": ["product"]}
        ]
        result = classify_scenes(storyboard, has_talking_head=True)
        assert result == [SCENE_BROLL]

    def test_no_talking_head_forces_broll(self):
        """Even if description mentions speaking, no talking_head flag → broll."""
        storyboard = [
            {"scene_description": "Person speaking", "key_elements": ["person"]}
        ]
        result = classify_scenes(storyboard, has_talking_head=False)
        assert result == [SCENE_BROLL]

    def test_mixed_scenes(self):
        storyboard = [
            {"scene_description": "Host talking to camera", "key_elements": ["face"]},
            {"scene_description": "Product close-up", "key_elements": ["product"]},
            {"scene_description": "Narrator continues", "key_elements": ["narrator"]},
        ]
        result = classify_scenes(storyboard, has_talking_head=True)
        assert result == [SCENE_TALKING_HEAD, SCENE_BROLL, SCENE_TALKING_HEAD]


# ---------------------------------------------------------------------------
# Engine Routing
# ---------------------------------------------------------------------------

class TestRouteSceneToEngine:
    """Tests for route_scene_to_engine."""

    def test_talking_head_routes_to_kling(self):
        assert route_scene_to_engine(SCENE_TALKING_HEAD, 10) == ENGINE_KLING

    def test_broll_routes_to_veo(self):
        assert route_scene_to_engine(SCENE_BROLL, 5) == ENGINE_VEO

    def test_action_routes_to_veo(self):
        assert route_scene_to_engine("action", 8) == ENGINE_VEO

    def test_unknown_type_routes_to_veo(self):
        assert route_scene_to_engine("unknown", 5) == ENGINE_VEO


# ---------------------------------------------------------------------------
# Duration Computation
# ---------------------------------------------------------------------------

class TestDurationComputation:
    """Tests for compute_nearest_veo_duration and compute_nearest_kling_duration."""

    def test_veo_short(self):
        assert compute_nearest_veo_duration(3.0) == 4

    def test_veo_mid(self):
        assert compute_nearest_veo_duration(5.5) == 6

    def test_veo_long(self):
        assert compute_nearest_veo_duration(7.5) == 8

    def test_veo_exact(self):
        assert compute_nearest_veo_duration(6.0) == 6

    def test_kling_short(self):
        assert compute_nearest_kling_duration(3.0) == "5"

    def test_kling_mid(self):
        assert compute_nearest_kling_duration(7.0) == "5"

    def test_kling_boundary(self):
        assert compute_nearest_kling_duration(7.5) == "5"

    def test_kling_long(self):
        assert compute_nearest_kling_duration(8.0) == "10"

    def test_kling_very_long(self):
        assert compute_nearest_kling_duration(12.0) == "10"


# ---------------------------------------------------------------------------
# Scene Splitting
# ---------------------------------------------------------------------------

class TestSplitSceneIfNeeded:
    """Tests for split_scene_if_needed."""

    def test_short_scene_no_split(self):
        scene = {"duration_sec": 5.0, "scene_idx": 0}
        result = split_scene_if_needed(scene)
        assert len(result) == 1
        assert result[0]["duration_sec"] == 5.0

    def test_max_duration_no_split(self):
        scene = {"duration_sec": 16.0, "scene_idx": 0}
        result = split_scene_if_needed(scene)
        assert len(result) == 1

    def test_long_scene_splits(self):
        scene = {"duration_sec": 20.0, "scene_idx": 0}
        result = split_scene_if_needed(scene)
        assert len(result) == 2
        assert result[0]["duration_sec"] == 10.0
        assert result[1]["duration_sec"] == 10.0

    def test_split_preserves_scene_idx(self):
        scene = {"duration_sec": 20.0, "scene_idx": 3}
        result = split_scene_if_needed(scene)
        assert all(r.get("scene_idx") == 3 for r in result)

    def test_split_dialogue_at_sentence(self):
        scene = {
            "duration_sec": 20.0,
            "scene_idx": 0,
            "scene_type": "talking_head",
            "dialogue": "This is sentence one. This is sentence two. And sentence three.",
        }
        result = split_scene_if_needed(scene)
        assert len(result) == 2
        # First part should have first sentence
        assert "sentence one" in result[0]["dialogue"]
        # Second part should have remaining
        assert "sentence three" in result[1]["dialogue"]

    def test_split_single_sentence_dialogue(self):
        """Single sentence should not crash splitting."""
        scene = {
            "duration_sec": 20.0,
            "scene_idx": 0,
            "scene_type": "talking_head",
            "dialogue": "Just one long sentence without any periods here",
        }
        result = split_scene_if_needed(scene)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Cost Estimation
# ---------------------------------------------------------------------------

class TestEstimateGenerationCost:
    """Tests for estimate_generation_cost."""

    def test_empty_scenes(self):
        result = estimate_generation_cost([])
        assert result["total_estimated"] == 0.0

    def test_broll_only(self):
        scenes = [
            {"scene_type": SCENE_BROLL, "duration_sec": 5},
            {"scene_type": SCENE_BROLL, "duration_sec": 8},
        ]
        result = estimate_generation_cost(scenes)
        assert result["veo_cost"] > 0
        assert result["kling_cost"] == 0.0
        assert result["elevenlabs_cost"] == 0.0

    def test_talking_head_only(self):
        scenes = [
            {"scene_type": SCENE_TALKING_HEAD, "duration_sec": 10},
        ]
        result = estimate_generation_cost(scenes)
        assert result["kling_cost"] > 0
        assert result["veo_cost"] == 0.0
        assert result["elevenlabs_cost"] > 0  # Talking head needs audio

    def test_mixed_scenes(self):
        scenes = [
            {"scene_type": SCENE_TALKING_HEAD, "duration_sec": 5},
            {"scene_type": SCENE_BROLL, "duration_sec": 5},
        ]
        result = estimate_generation_cost(scenes)
        assert result["kling_cost"] > 0
        assert result["veo_cost"] > 0
        assert result["total_estimated"] == (
            result["kling_cost"] + result["veo_cost"] + result["elevenlabs_cost"]
        )

    def test_cost_keys_present(self):
        scenes = [{"scene_type": SCENE_BROLL, "duration_sec": 5}]
        result = estimate_generation_cost(scenes)
        assert "kling_cost" in result
        assert "veo_cost" in result
        assert "elevenlabs_cost" in result
        assert "total_estimated" in result


# ---------------------------------------------------------------------------
# Service: Score Candidates
# ---------------------------------------------------------------------------

class TestScoreCandidates:
    """Tests for VideoRecreationService.score_candidates."""

    def test_no_analyses_returns_empty(self, service, mock_supabase):
        """No analyzed posts → empty list."""
        # Setup: analyses query returns empty
        analyses_chain = MagicMock()
        analyses_chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        mock_supabase.table.return_value = analyses_chain

        result = service.score_candidates("brand-1", "org-1")
        assert result == []

    def test_scores_single_analysis(self, service, mock_supabase):
        """Single analysis should produce one scored candidate."""
        analysis = {
            "id": "analysis-1",
            "source_post_id": "post-1",
            "storyboard": [{"scene_description": "test"}],
            "has_talking_head": False,
            "eval_scores": {"overall_score": 0.8, "va6_hook_window": 0.7},
            "people_detected": 1,
            "format_type": "ugc",
            "posts": {"id": "post-1", "outlier_score": 2.0, "is_outlier": True},
        }

        # Setup analyses query
        analyses_table = MagicMock()
        analyses_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[analysis]
        )

        # Setup avatars query
        avatars_table = MagicMock()
        avatars_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        # Setup existing check (no existing candidate)
        candidates_table = MagicMock()
        candidates_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        candidates_table.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "new-candidate-1"}]
        )

        def table_router(name):
            if name == "ad_video_analysis":
                return analyses_table
            elif name == "brand_avatars":
                return avatars_table
            elif name == "video_recreation_candidates":
                return candidates_table
            return MagicMock()

        mock_supabase.table.side_effect = table_router

        result = service.score_candidates("brand-1", "org-1")
        assert len(result) == 1
        assert result[0]["composite_score"] > 0
        assert "engagement" in result[0]["score_components"]
        assert result[0]["scoring_version"] == SCORING_VERSION


# ---------------------------------------------------------------------------
# Service: Approve / Reject
# ---------------------------------------------------------------------------

class TestApproveReject:
    """Tests for approve_candidate and reject_candidate."""

    def test_approve_candidate(self, service, mock_supabase):
        table = MagicMock()
        table.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "c-1", "status": STATUS_APPROVED}]
        )
        mock_supabase.table.return_value = table

        result = service.approve_candidate("c-1")
        assert result is not None
        assert result["status"] == STATUS_APPROVED

    def test_reject_candidate(self, service, mock_supabase):
        table = MagicMock()
        table.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "c-1", "status": STATUS_REJECTED}]
        )
        mock_supabase.table.return_value = table

        result = service.reject_candidate("c-1")
        assert result is not None
        assert result["status"] == STATUS_REJECTED

    def test_approve_not_found(self, service, mock_supabase):
        table = MagicMock()
        table.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_supabase.table.return_value = table

        result = service.approve_candidate("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Service: Get / List Candidates
# ---------------------------------------------------------------------------

class TestGetListCandidates:
    """Tests for get_candidate and list_candidates."""

    def test_get_candidate_found(self, service, mock_supabase):
        table = MagicMock()
        table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id": "c-1", "status": "candidate", "composite_score": 0.75}
        )
        mock_supabase.table.return_value = table

        result = service.get_candidate("c-1")
        assert result is not None
        assert result["id"] == "c-1"

    def test_get_candidate_not_found(self, service, mock_supabase):
        table = MagicMock()
        table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )
        mock_supabase.table.return_value = table

        result = service.get_candidate("nonexistent")
        assert result is None

    def test_list_candidates_empty(self, service, mock_supabase):
        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_supabase.table.return_value = table

        result = service.list_candidates("brand-1", "org-1")
        assert result == []

    def test_list_candidates_with_status_filter(self, service, mock_supabase):
        table = MagicMock()
        chain = table.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(
            data=[{"id": "c-1", "status": "approved"}]
        )
        mock_supabase.table.return_value = table

        result = service.list_candidates("brand-1", "org-1", status="approved")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Service: Cost Estimation
# ---------------------------------------------------------------------------

class TestGetCostEstimate:
    """Tests for VideoRecreationService.get_cost_estimate."""

    def test_candidate_not_found(self, service, mock_supabase):
        table = MagicMock()
        table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )
        mock_supabase.table.return_value = table

        result = service.get_cost_estimate("nonexistent")
        assert result is None

    def test_with_adapted_storyboard(self, service, mock_supabase):
        candidate_table = MagicMock()
        candidate_table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "c-1",
                "adapted_storyboard": [
                    {"scene_type": SCENE_BROLL, "duration_sec": 5},
                    {"scene_type": SCENE_TALKING_HEAD, "duration_sec": 8},
                ],
                "analysis_id": None,
            }
        )
        mock_supabase.table.return_value = candidate_table

        result = service.get_cost_estimate("c-1")
        assert result is not None
        assert "total_estimated" in result
        assert result["total_estimated"] > 0


# ---------------------------------------------------------------------------
# Constants Validation
# ---------------------------------------------------------------------------

class TestConstants:
    """Verify scoring constants are well-formed."""

    def test_weights_sum_to_one(self):
        assert abs(sum(SCORING_WEIGHTS.values()) - 1.0) < 0.001

    def test_scoring_version_is_string(self):
        assert isinstance(SCORING_VERSION, str)

    def test_all_weight_keys_present(self):
        expected = {"engagement", "hook_quality", "recreation_feasibility", "avatar_compatibility"}
        assert set(SCORING_WEIGHTS.keys()) == expected

    def test_all_weights_positive(self):
        assert all(v > 0 for v in SCORING_WEIGHTS.values())
