"""
Tests for ScorerWeightLearningService — Thompson Sampling for scorer weights.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.services.scorer_weight_learning_service import (
    ScorerWeightLearningService,
    STATIC_WEIGHTS,
    COLD_MAX,
    WARM_MAX,
    HOT_MIN,
    WEIGHT_FLOOR,
    WEIGHT_CEILING,
    MAX_DELTA_PER_UPDATE,
    SOFT_UPDATE_FACTOR,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def learning_service():
    """Create a ScorerWeightLearningService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = ScorerWeightLearningService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")


# ============================================================================
# get_learned_weights tests
# ============================================================================

class TestGetLearnedWeights:
    def test_roll_the_dice_always_static(self, learning_service):
        """roll_the_dice mode should always return static weights."""
        result = learning_service.get_learned_weights(BRAND_ID, mode="roll_the_dice")
        assert result == STATIC_WEIGHTS

    def test_no_posteriors_returns_static(self, learning_service):
        """When no posteriors exist, returns static weights."""
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        result = learning_service.get_learned_weights(BRAND_ID, mode="smart_select")
        assert result == STATIC_WEIGHTS

    def test_cold_phase_returns_static(self, learning_service):
        """Cold phase (0-29 obs) should return static weights."""
        posteriors = [{
            "scorer_name": "asset_match",
            "alpha": 5.0, "beta": 3.0,
            "total_observations": 10,
            "learning_phase": "cold",
            "static_weight": 1.0,
        }]
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=posteriors)

        result = learning_service.get_learned_weights(BRAND_ID, mode="smart_select")
        assert result["asset_match"] == 1.0  # static

    def test_hot_phase_uses_learned(self, learning_service):
        """Hot phase (100+) should use fully learned weights."""
        posteriors = [{
            "scorer_name": "asset_match",
            "alpha": 80.0, "beta": 20.0,  # mean = 0.8
            "total_observations": 150,
            "learning_phase": "hot",
            "static_weight": 1.0,
        }]
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=posteriors)

        result = learning_service.get_learned_weights(BRAND_ID, mode="smart_select")
        # Learned: 0.8 * (1.0 / 0.5) = 1.6
        assert result["asset_match"] == pytest.approx(1.6, abs=0.1)

    def test_warm_phase_blends(self, learning_service):
        """Warm phase (30-99) should blend static and learned."""
        posteriors = [{
            "scorer_name": "asset_match",
            "alpha": 40.0, "beta": 10.0,  # mean = 0.8
            "total_observations": 65,  # midpoint of warm
            "learning_phase": "warm",
            "static_weight": 1.0,
        }]
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=posteriors)

        result = learning_service.get_learned_weights(BRAND_ID, mode="smart_select")
        # Should be between static (1.0) and learned (1.6)
        assert 1.0 < result["asset_match"] < 1.6


class TestWeightSafetyRails:
    def test_weight_floor(self, learning_service):
        """Weights should never go below WEIGHT_FLOOR."""
        assert learning_service._clamp_weight(0.01) == WEIGHT_FLOOR

    def test_weight_ceiling(self, learning_service):
        """Weights should never exceed WEIGHT_CEILING."""
        assert learning_service._clamp_weight(5.0) == WEIGHT_CEILING

    def test_normal_weight_unchanged(self, learning_service):
        """Normal weights should pass through unchanged."""
        assert learning_service._clamp_weight(0.5) == 0.5


# ============================================================================
# initialize_posteriors tests
# ============================================================================

class TestInitializePosteriors:
    def test_initializes_all_scorers(self, learning_service):
        """Should create posteriors for all scorer names."""
        # No existing posteriors
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(count=0)

        learning_service.initialize_posteriors(BRAND_ID)

        insert_call = learning_service.supabase.table.return_value.insert
        assert insert_call.called
        rows = insert_call.call_args[0][0]
        assert len(rows) == len(STATIC_WEIGHTS)

        scorer_names = {r["scorer_name"] for r in rows}
        assert scorer_names == set(STATIC_WEIGHTS.keys())

    def test_skips_if_already_initialized(self, learning_service):
        """Should not re-initialize if posteriors already exist."""
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(count=8)

        learning_service.initialize_posteriors(BRAND_ID)

        insert_call = learning_service.supabase.table.return_value.insert
        assert not insert_call.called


# ============================================================================
# record_selection_snapshot tests
# ============================================================================

class TestRecordSelectionSnapshot:
    def test_records_snapshot(self, learning_service):
        """Should insert a selection weight snapshot."""
        # Mock posteriors for phase detection
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        learning_service.record_selection_snapshot(
            brand_id=BRAND_ID,
            ad_run_id="run-123",
            template_id="tmpl-456",
            weights_used={"asset_match": 1.0},
            scorer_breakdown={"asset_match": 0.8},
            composite_score=0.8,
            selection_mode="smart_select",
        )

        insert_call = learning_service.supabase.table.return_value.insert
        assert insert_call.called


# ============================================================================
# Credit assignment tests
# ============================================================================

class TestCreditAssignment:
    def test_contribution_weighted_updates(self):
        """Verify contribution-weighted credit assignment logic."""
        # Test contribution calculation
        weights = {"asset_match": 1.0, "unused_bonus": 0.8}
        scores = {"asset_match": 0.9, "unused_bonus": 0.3}

        total = sum(weights[k] * scores[k] for k in weights)
        contributions = {k: weights[k] * scores[k] / total for k in weights}

        # asset_match has higher contribution (0.9 vs 0.24)
        assert contributions["asset_match"] > contributions["unused_bonus"]
        assert abs(sum(contributions.values()) - 1.0) < 0.001


# ============================================================================
# Phase transition tests
# ============================================================================

class TestPhaseTransitions:
    def test_cold_boundary(self):
        """29 observations should still be cold."""
        assert COLD_MAX == 29

    def test_warm_boundary(self):
        """30-99 observations should be warm."""
        assert WARM_MAX == 99

    def test_hot_boundary(self):
        """100+ observations should be hot."""
        assert HOT_MIN == 100

    def test_get_weight_status(self, learning_service):
        """get_weight_status should return all scorers with status info."""
        posteriors = [{
            "scorer_name": "asset_match",
            "alpha": 5.0, "beta": 3.0,
            "total_observations": 50,
            "learning_phase": "warm",
            "static_weight": 1.0,
            "mean_reward": 0.625,
        }]
        learning_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=posteriors)

        status = learning_service.get_weight_status(BRAND_ID)
        assert len(status) == len(STATIC_WEIGHTS)

        asset_status = next(s for s in status if s["scorer_name"] == "asset_match")
        assert asset_status["learning_phase"] == "warm"
        assert asset_status["total_observations"] == 50
