"""
Unit tests for ExperimentService — Phase 7B Experimentation Framework.

Tests cover:
- Pure functions (_z_score, posteriors, Monte Carlo, decision rules, quality grading)
- Power analysis computations
- Status transition gates
- Arm management constraints
"""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from viraltracker.services.experiment_service import (
    DEFAULT_BASELINE_CTR,
    DEFAULT_MIN_DETECTABLE_EFFECT,
    DEFAULT_MIN_IMPRESSIONS_PER_ARM,
    DEFAULT_MIN_DAYS_RUNNING,
    DEFAULT_MAX_DAYS_RUNNING,
    FUTILITY_MAX_RELATIVE_LIFT,
    METHOD_TYPE_TO_BASE_GRADE,
    MONTE_CARLO_SAMPLES,
    P_BEST_WINNER_THRESHOLD,
    ExperimentService,
    _z_score,
)

SUPABASE_MOCK_PATH = "viraltracker.core.database.get_supabase_client"


# =============================================================================
# _z_score
# =============================================================================

class TestZScore:
    """Tests for the z-score approximation function."""

    def test_z_score_0975_is_about_196(self):
        """Standard z for 97.5% should be ~1.96."""
        z = _z_score(0.975)
        assert abs(z - 1.96) < 0.01

    def test_z_score_050_is_zero(self):
        """z(0.5) should be ~0."""
        z = _z_score(0.5)
        assert abs(z) < 0.01

    def test_z_score_symmetry(self):
        """z(p) = -z(1-p)."""
        z1 = _z_score(0.95)
        z2 = _z_score(0.05)
        assert abs(z1 + z2) < 0.01

    def test_z_score_boundary_raises(self):
        """Should raise for p=0 or p=1."""
        with pytest.raises(ValueError):
            _z_score(0)
        with pytest.raises(ValueError):
            _z_score(1)


# =============================================================================
# Beta-Binomial Posteriors
# =============================================================================

class TestComputePosteriorsCtr:
    """Tests for _compute_posteriors_ctr."""

    def setup_method(self):
        with patch(SUPABASE_MOCK_PATH):
            self.svc = ExperimentService()

    def test_uninformative_prior(self):
        """With no data, posterior should be Beta(1, 1)."""
        result = self.svc._compute_posteriors_ctr([
            {"clicks": 0, "impressions": 0}
        ])
        assert result[0]["alpha"] == 1
        assert result[0]["beta"] == 1

    def test_posterior_updates(self):
        """100 clicks out of 1000 impressions → Beta(101, 901)."""
        result = self.svc._compute_posteriors_ctr([
            {"clicks": 100, "impressions": 1000}
        ])
        assert result[0]["alpha"] == 101
        assert result[0]["beta"] == 901

    def test_multiple_arms(self):
        """Each arm gets independent posterior."""
        result = self.svc._compute_posteriors_ctr([
            {"clicks": 10, "impressions": 1000},
            {"clicks": 20, "impressions": 1000},
        ])
        assert len(result) == 2
        assert result[0]["alpha"] == 11
        assert result[1]["alpha"] == 21


# =============================================================================
# Monte Carlo P(best)
# =============================================================================

class TestMonteCarloPBest:
    """Tests for _monte_carlo_p_best."""

    def setup_method(self):
        with patch(SUPABASE_MOCK_PATH):
            self.svc = ExperimentService()

    def test_clear_winner(self):
        """Arm with much higher CTR should have P(best) near 1.0."""
        posteriors = [
            {"alpha": 100, "beta": 900},   # ~10% CTR
            {"alpha": 10, "beta": 990},     # ~1% CTR
        ]
        p_best = self.svc._monte_carlo_p_best(posteriors, "ctr")
        assert p_best[0] > 0.99
        assert p_best[1] < 0.01

    def test_p_best_sums_to_one(self):
        """P(best) values should sum to 1.0."""
        posteriors = [
            {"alpha": 50, "beta": 950},
            {"alpha": 55, "beta": 945},
            {"alpha": 45, "beta": 955},
        ]
        p_best = self.svc._monte_carlo_p_best(posteriors, "ctr")
        assert abs(sum(p_best) - 1.0) < 0.01

    def test_cpa_lower_is_better(self):
        """For CPA, the arm with lower mean should win."""
        posteriors = [
            {"mean": 5.0, "variance": 1.0},   # Better CPA
            {"mean": 10.0, "variance": 1.0},   # Worse CPA
        ]
        p_best = self.svc._monte_carlo_p_best(posteriors, "cpa")
        assert p_best[0] > 0.90

    def test_empty_posteriors(self):
        """Empty list returns empty list."""
        assert self.svc._monte_carlo_p_best([], "ctr") == []


# =============================================================================
# Decision Rules
# =============================================================================

class TestDetermineDecision:
    """Tests for _determine_decision."""

    def setup_method(self):
        with patch(SUPABASE_MOCK_PATH):
            self.svc = ExperimentService()

    def _make_arms(self, ctrs):
        return [{"ctr": c, "impressions": 2000} for c in ctrs]

    def test_collecting_when_below_min_impressions(self):
        """Should return 'collecting' if not all arms met minimum."""
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.01, 0.02]),
            p_best_values=[0.1, 0.9],
            all_met_min=False,
            days_running=10,
            min_days=7,
            max_days=14,
        )
        assert decision == "collecting"

    def test_winner_when_p_best_high_and_min_days_met(self):
        """Should return 'winner' when P(best) >= 0.90 and min days met."""
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.01, 0.03]),
            p_best_values=[0.05, 0.95],
            all_met_min=True,
            days_running=8,
            min_days=7,
            max_days=14,
        )
        assert decision == "winner"

    def test_leading_when_p_best_high_but_min_days_not_met(self):
        """Should return 'leading' when P(best) >= 0.90 but min days not met."""
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.01, 0.03]),
            p_best_values=[0.05, 0.95],
            all_met_min=True,
            days_running=3,
            min_days=7,
            max_days=14,
        )
        assert decision == "leading"

    def test_futility_when_max_days_and_small_lift(self):
        """Should return 'futility' when max days reached and lift < 2%."""
        # CTRs differ by < 2% relative
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.0100, 0.0101]),
            p_best_values=[0.4, 0.6],
            all_met_min=True,
            days_running=14,
            min_days=7,
            max_days=14,
        )
        assert decision == "futility"

    def test_inconclusive_when_max_days_and_no_winner(self):
        """Should return 'inconclusive' when max days reached but arms differ."""
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.010, 0.015]),
            p_best_values=[0.3, 0.7],
            all_met_min=True,
            days_running=14,
            min_days=7,
            max_days=14,
        )
        assert decision == "inconclusive"

    def test_leading_when_moderate_signal(self):
        """Should return 'leading' when there's a signal but not conclusive."""
        decision = self.svc._determine_decision(
            arm_results=self._make_arms([0.01, 0.02]),
            p_best_values=[0.2, 0.8],
            all_met_min=True,
            days_running=10,
            min_days=7,
            max_days=14,
        )
        assert decision == "leading"


# =============================================================================
# Quality Grading
# =============================================================================

class TestGradeQuality:
    """Tests for _grade_quality."""

    def setup_method(self):
        with patch(SUPABASE_MOCK_PATH):
            self.svc = ExperimentService()

    def _make_experiment(self, method_type, protocol_fields=None, arms_linked=True):
        protocol = {"method_type": method_type}
        if protocol_fields:
            protocol.update(protocol_fields)
        arms = [
            {"name": "Control", "meta_adset_id": "123" if arms_linked else None},
            {"name": "Treatment", "meta_adset_id": "456" if arms_linked else None},
        ]
        return {"protocol": protocol, "arms": arms}

    def test_strict_ab_full_protocol_is_causal(self):
        """strict_ab with all required fields and linked arms = causal."""
        exp = self._make_experiment("strict_ab", {
            "budget_strategy": "equal",
            "randomization_unit": "user",
            "min_impressions_per_arm": 1000,
            "min_days_running": 7,
        })
        grade, notes = self.svc._grade_quality(exp)
        assert grade == "causal"
        assert notes is None

    def test_strict_ab_missing_fields_is_quasi(self):
        """strict_ab with missing protocol fields = quasi."""
        exp = self._make_experiment("strict_ab", {})
        grade, notes = self.svc._grade_quality(exp)
        assert grade == "quasi"
        assert "missing protocol fields" in notes

    def test_strict_ab_unlinked_arms_is_quasi(self):
        """strict_ab with unlinked arms = quasi."""
        exp = self._make_experiment("strict_ab", {
            "budget_strategy": "equal",
            "randomization_unit": "user",
            "min_impressions_per_arm": 1000,
            "min_days_running": 7,
        }, arms_linked=False)
        grade, notes = self.svc._grade_quality(exp)
        assert grade == "quasi"
        assert "unlinked arms" in notes

    def test_pragmatic_split_is_quasi(self):
        """pragmatic_split is always quasi."""
        exp = self._make_experiment("pragmatic_split")
        grade, _ = self.svc._grade_quality(exp)
        assert grade == "quasi"

    def test_observational_is_observational(self):
        """observational method = observational grade."""
        exp = self._make_experiment("observational")
        grade, _ = self.svc._grade_quality(exp)
        assert grade == "observational"

    def test_missing_method_is_observational(self):
        """Missing method_type defaults to observational."""
        exp = {"protocol": {}, "arms": []}
        grade, _ = self.svc._grade_quality(exp)
        assert grade == "observational"


# =============================================================================
# Power Analysis (unit math)
# =============================================================================

class TestPowerAnalysisMath:
    """Tests for the power analysis formula components."""

    def test_sample_size_increases_with_smaller_effect(self):
        """Smaller detectable effect → larger required sample."""
        z_alpha = _z_score(0.975)  # two-sided 5%
        z_beta = _z_score(0.80)

        p1 = 0.015
        p2_large = p1 * 1.30   # 30% lift
        p2_small = p1 * 1.10   # 10% lift

        n_large = (z_alpha + z_beta) ** 2 * (p1*(1-p1) + p2_large*(1-p2_large)) / (p2_large - p1) ** 2
        n_small = (z_alpha + z_beta) ** 2 * (p1*(1-p1) + p2_small*(1-p2_small)) / (p2_small - p1) ** 2

        assert n_small > n_large

    def test_sample_size_reasonable_for_defaults(self):
        """Default params should give a reasonable sample size."""
        z_alpha = _z_score(0.975)
        z_beta = _z_score(0.80)

        p1 = DEFAULT_BASELINE_CTR  # 0.015
        p2 = p1 * (1 + DEFAULT_MIN_DETECTABLE_EFFECT)  # 20% lift

        n = (z_alpha + z_beta) ** 2 * (p1*(1-p1) + p2*(1-p2)) / (p2 - p1) ** 2
        n = math.ceil(n)

        # Should be in the thousands range
        assert 1000 < n < 100000


# =============================================================================
# Status Transitions
# =============================================================================

class TestStatusTransitions:
    """Tests for status transition gate logic."""

    def test_valid_transitions(self):
        """Verify valid transition map."""
        from viraltracker.services.experiment_service import VALID_TRANSITIONS

        assert "ready" in VALID_TRANSITIONS["draft"]
        assert "cancelled" in VALID_TRANSITIONS["draft"]
        assert "deploying" in VALID_TRANSITIONS["ready"]
        assert "running" in VALID_TRANSITIONS["deploying"]
        assert "analyzing" in VALID_TRANSITIONS["running"]
        assert "concluded" in VALID_TRANSITIONS["analyzing"]
        assert VALID_TRANSITIONS["concluded"] == []
        assert VALID_TRANSITIONS["cancelled"] == []

    def test_cancellation_always_valid(self):
        """cancelled should be reachable from any active state."""
        from viraltracker.services.experiment_service import VALID_TRANSITIONS

        for status in ["draft", "ready", "deploying", "running", "analyzing"]:
            assert "cancelled" in VALID_TRANSITIONS[status]


# =============================================================================
# Method type → grade mapping
# =============================================================================

class TestMethodTypeMapping:
    """Tests for METHOD_TYPE_TO_BASE_GRADE mapping."""

    def test_strict_ab_maps_to_causal(self):
        assert METHOD_TYPE_TO_BASE_GRADE["strict_ab"] == "causal"

    def test_pragmatic_split_maps_to_quasi(self):
        assert METHOD_TYPE_TO_BASE_GRADE["pragmatic_split"] == "quasi"

    def test_observational_maps_to_observational(self):
        assert METHOD_TYPE_TO_BASE_GRADE["observational"] == "observational"


# =============================================================================
# Continuous posteriors
# =============================================================================

class TestComputePosteriorsContinuous:
    """Tests for Normal conjugate posteriors."""

    def setup_method(self):
        with patch(SUPABASE_MOCK_PATH):
            self.svc = ExperimentService()

    def test_no_data_returns_prior(self):
        """Arms with None metric should get prior (grand mean)."""
        result = self.svc._compute_posteriors_continuous(
            [{"cpa": None, "impressions": 0}],
            "cpa",
        )
        assert result[0]["mean"] == 0.0

    def test_posterior_moves_toward_data(self):
        """With data, posterior mean should move toward observed value."""
        result = self.svc._compute_posteriors_continuous(
            [
                {"cpa": 5.0, "impressions": 100},
                {"cpa": 10.0, "impressions": 100},
            ],
            "cpa",
        )
        # Grand mean is 7.5, each arm should move toward its value
        assert result[0]["mean"] < 7.5  # Pulled toward 5.0
        assert result[1]["mean"] > 7.5  # Pulled toward 10.0
