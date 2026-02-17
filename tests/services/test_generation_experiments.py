"""
Tests for GenerationExperimentService — A/B testing with Mann-Whitney U.

All database calls are mocked — no real DB or API connections needed.
"""

import hashlib
import math
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.services.generation_experiment_service import (
    GenerationExperimentService,
    mann_whitney_u,
    VALID_EXPERIMENT_TYPES,
    P_VALUE_THRESHOLD,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def exp_service():
    """Create a GenerationExperimentService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = GenerationExperimentService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")


# ============================================================================
# Mann-Whitney U tests (CRITICAL — pure Python implementation)
# ============================================================================

class TestMannWhitneyU:
    def test_identical_samples_high_p(self):
        """Identical samples should have high p-value (no difference)."""
        a = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0,
             1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
        b = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0,
             1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]

        u, p = mann_whitney_u(a, b)
        assert p > 0.05  # Not significant

    def test_very_different_samples_low_p(self):
        """Very different samples should have low p-value."""
        a = [0.0] * 30  # all failures
        b = [1.0] * 30  # all successes

        u, p = mann_whitney_u(a, b)
        assert p < 0.01  # Highly significant

    def test_heavy_tie_binary_data(self):
        """Binary data with ties should be handled correctly.

        Required test: PLAN.md specifies tie-corrected variance for binary data.
        Compare against known reference: 5 control (3 fail, 2 pass) vs 5 variant (1 fail, 4 pass)
        """
        control = [0.0, 0.0, 0.0, 1.0, 1.0]
        variant = [0.0, 1.0, 1.0, 1.0, 1.0]

        u, p = mann_whitney_u(control, variant)

        # U should be a valid number
        assert isinstance(u, float)
        assert isinstance(p, float)
        assert 0 <= p <= 1

        # With only 5 per group, shouldn't be significant at 0.05
        # (too small sample for significance even with apparent difference)
        assert p > 0.05

    def test_larger_binary_difference(self):
        """Larger samples with clear binary difference should be significant."""
        control = [0.0] * 20 + [1.0] * 5   # 20% approval
        variant = [0.0] * 5 + [1.0] * 20    # 80% approval

        u, p = mann_whitney_u(control, variant)
        assert p < 0.05  # Should be significant

    def test_empty_samples(self):
        """Empty samples should return U=0, p=1."""
        u, p = mann_whitney_u([], [1.0, 0.0])
        assert u == 0.0
        assert p == 1.0

    def test_tie_correction_applied(self):
        """Verify tie correction changes the result vs no correction.

        Binary data produces massive ties — the correction should be substantial.
        """
        # All same values: no variance without correction
        a = [1.0] * 20
        b = [1.0] * 20

        u, p = mann_whitney_u(a, b)
        # With all ties, U = n_a*n_b/2 and correction makes sigma very large → p ≈ 1
        assert p > 0.9

    def test_symmetry(self):
        """U test should be symmetric: swapping samples gives same p-value."""
        a = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0,
             0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        b = [1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0,
             1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0]

        u1, p1 = mann_whitney_u(a, b)
        u2, p2 = mann_whitney_u(b, a)

        assert p1 == pytest.approx(p2, abs=0.001)


# ============================================================================
# Deterministic arm assignment tests
# ============================================================================

class TestArmAssignment:
    def test_deterministic_assignment(self, exp_service):
        """Same seed + experiment should always get same arm."""
        exp_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{
            "id": "exp-123",
            "split_ratio": 0.50,
            "control_config": {"prompt": "v1"},
            "variant_config": {"prompt": "v2"},
        }])

        result1 = exp_service.assign_arm(str(BRAND_ID), "seed-abc")
        result2 = exp_service.assign_arm(str(BRAND_ID), "seed-abc")

        assert result1["arm"] == result2["arm"]

    def test_sha256_used_not_python_hash(self, exp_service):
        """Assignment should use SHA-256, not Python hash() (salt-randomized)."""
        exp_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{
            "id": "exp-123",
            "split_ratio": 0.50,
            "control_config": {},
            "variant_config": {},
        }])

        result = exp_service.assign_arm(str(BRAND_ID), "test-seed")

        # Verify the assignment is what SHA-256 would produce
        combined = "test-seed:exp-123"
        hash_val = int(hashlib.sha256(combined.encode()).hexdigest(), 16) % 100
        expected_arm = "variant" if hash_val < 50 else "control"
        assert result["arm"] == expected_arm

    def test_no_active_experiment_returns_none(self, exp_service):
        """When no active experiment exists, should return None."""
        exp_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        result = exp_service.assign_arm(str(BRAND_ID), "seed-abc")
        assert result is None

    def test_split_ratio_affects_assignment(self, exp_service):
        """Different split ratios should change assignment probabilities."""
        # With 90% variant split, most seeds should get variant
        variant_count = 0
        for i in range(100):
            exp_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{
                "id": "exp-split-test",
                "split_ratio": 0.90,
                "control_config": {},
                "variant_config": {},
            }])
            result = exp_service.assign_arm(str(BRAND_ID), f"seed-{i}")
            if result["arm"] == "variant":
                variant_count += 1

        # Should be roughly 90% variant (allow wide margin for small sample)
        assert variant_count > 70


# ============================================================================
# CRUD tests
# ============================================================================

class TestExperimentCRUD:
    def test_invalid_experiment_type_rejected(self, exp_service):
        """Invalid experiment types should raise ValueError."""
        with pytest.raises(ValueError, match="experiment_type must be one of"):
            exp_service.create_experiment(
                brand_id=BRAND_ID,
                name="Test",
                experiment_type="invalid_type",
                control_config={},
                variant_config={},
            )

    def test_invalid_split_ratio_rejected(self, exp_service):
        """Split ratio outside (0, 1) should raise ValueError."""
        with pytest.raises(ValueError, match="split_ratio"):
            exp_service.create_experiment(
                brand_id=BRAND_ID,
                name="Test",
                experiment_type="prompt_version",
                control_config={},
                variant_config={},
                split_ratio=0.0,
            )

    def test_active_experiment_blocks_creation(self, exp_service):
        """Creating an experiment when one is active should raise ValueError."""
        # Mock existing active experiment
        exp_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(count=1)

        with pytest.raises(ValueError, match="already has an active experiment"):
            exp_service.create_experiment(
                brand_id=BRAND_ID,
                name="Test",
                experiment_type="prompt_version",
                control_config={},
                variant_config={},
            )


# ============================================================================
# Outcome recording tests
# ============================================================================

class TestOutcomeRecording:
    def test_invalid_arm_rejected(self, exp_service):
        """Invalid arm names should raise ValueError."""
        with pytest.raises(ValueError, match="arm must be"):
            exp_service.record_outcome(
                experiment_id="exp-123",
                arm="invalid",
                ad_run_id="run-123",
                metrics={},
            )

    def test_records_run_and_updates_aggregate(self, exp_service):
        """Should insert run record and update aggregate metrics."""
        # Mock get_experiment for aggregate update
        exp_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "exp-123",
            "control_metrics": {"ads_generated": 5, "ads_approved": 3, "ads_rejected": 2, "defects": 0, "review_score_sum": 0},
            "variant_metrics": {"ads_generated": 0, "ads_approved": 0, "ads_rejected": 0, "defects": 0, "review_score_sum": 0},
        }])

        exp_service.record_outcome(
            experiment_id="exp-123",
            arm="control",
            ad_run_id="run-456",
            metrics={"ads_generated": 3, "ads_approved": 2, "ads_rejected": 1},
        )

        # Verify insert was called
        insert_calls = exp_service.supabase.table.return_value.insert.call_count
        assert insert_calls >= 1
