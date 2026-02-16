"""
Tests for CreativeGenomeService — Thompson Sampling, reward computation, monitoring.

All database calls are mocked — no real DB or API connections needed.
"""

import math
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.services.creative_genome_service import (
    CreativeGenomeService,
    REWARD_WEIGHTS,
    MATURATION_WINDOWS,
    TRACKED_ELEMENTS,
    MONITORING_THRESHOLDS,
    CROSS_BRAND_SHRINKAGE,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def genome_service():
    """Create a CreativeGenomeService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = CreativeGenomeService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")


# ============================================================================
# _normalize_metric tests
# ============================================================================

class TestNormalizeMetric:
    def test_at_p25_returns_zero(self, genome_service):
        assert genome_service._normalize_metric(0.005, 0.005, 0.02) == 0.0

    def test_at_p75_returns_one(self, genome_service):
        assert genome_service._normalize_metric(0.02, 0.005, 0.02) == 1.0

    def test_between_p25_p75(self, genome_service):
        result = genome_service._normalize_metric(0.0125, 0.005, 0.02)
        assert 0.49 < result < 0.51  # approximately 0.5

    def test_below_p25_clamped_to_zero(self, genome_service):
        assert genome_service._normalize_metric(0.001, 0.005, 0.02) == 0.0

    def test_above_p75_clamped_to_one(self, genome_service):
        assert genome_service._normalize_metric(0.05, 0.005, 0.02) == 1.0

    def test_none_returns_neutral(self, genome_service):
        assert genome_service._normalize_metric(None, 0.005, 0.02) == 0.5

    def test_equal_p25_p75_returns_neutral(self, genome_service):
        assert genome_service._normalize_metric(0.01, 0.01, 0.01) == 0.5


# ============================================================================
# _compute_composite_reward tests
# ============================================================================

class TestCompositeReward:
    def test_conversions_objective_weights(self, genome_service):
        perf = {"avg_ctr": 0.02, "avg_conversion_rate": 0.03, "avg_roas": 3.0}
        baselines = {
            "p25_ctr": 0.005, "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005, "p75_conversion_rate": 0.03,
            "p25_roas": 0.5, "p75_roas": 3.0,
        }
        reward, components = genome_service._compute_composite_reward(
            perf, baselines, "CONVERSIONS"
        )
        # All metrics at p75 → all norm = 1.0 → reward = 1.0
        assert reward == 1.0
        assert components["ctr_norm"] == 1.0
        assert components["conv_norm"] == 1.0
        assert components["roas_norm"] == 1.0

    def test_all_at_p25_gives_zero(self, genome_service):
        perf = {"avg_ctr": 0.005, "avg_conversion_rate": 0.005, "avg_roas": 0.5}
        baselines = {
            "p25_ctr": 0.005, "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005, "p75_conversion_rate": 0.03,
            "p25_roas": 0.5, "p75_roas": 3.0,
        }
        reward, components = genome_service._compute_composite_reward(
            perf, baselines, "CONVERSIONS"
        )
        assert reward == 0.0

    def test_traffic_objective_favors_ctr(self, genome_service):
        perf = {"avg_ctr": 0.02, "avg_conversion_rate": 0.005, "avg_roas": 0.5}
        baselines = {
            "p25_ctr": 0.005, "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005, "p75_conversion_rate": 0.03,
            "p25_roas": 0.5, "p75_roas": 3.0,
        }
        reward, components = genome_service._compute_composite_reward(
            perf, baselines, "TRAFFIC"
        )
        # ctr at p75=1.0 with weight 0.6, conv and roas at p25=0.0
        assert reward == pytest.approx(0.6)

    def test_default_objective_when_unknown(self, genome_service):
        perf = {"avg_ctr": 0.0125, "avg_conversion_rate": 0.0175, "avg_roas": 1.75}
        baselines = {
            "p25_ctr": 0.005, "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005, "p75_conversion_rate": 0.03,
            "p25_roas": 0.5, "p75_roas": 3.0,
        }
        reward, components = genome_service._compute_composite_reward(
            perf, baselines, "UNKNOWN_OBJECTIVE"
        )
        # Uses DEFAULT weights: ctr=0.4, conv=0.3, roas=0.3
        # All metrics at midpoint (0.5), so reward ≈ 0.5
        assert 0.49 < reward < 0.51

    def test_none_metrics_get_neutral(self, genome_service):
        perf = {"avg_ctr": None, "avg_conversion_rate": None, "avg_roas": None}
        baselines = {
            "p25_ctr": 0.005, "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005, "p75_conversion_rate": 0.03,
            "p25_roas": 0.5, "p75_roas": 3.0,
        }
        reward, components = genome_service._compute_composite_reward(
            perf, baselines, "CONVERSIONS"
        )
        assert reward == 0.5  # all neutral


# ============================================================================
# _weighted_avg tests
# ============================================================================

class TestWeightedAvg:
    def test_basic_weighted_average(self, genome_service):
        rows = [
            {"ctr": 0.01, "impressions": 1000},
            {"ctr": 0.02, "impressions": 3000},
        ]
        result = genome_service._weighted_avg(rows, "ctr", "impressions")
        # (0.01*1000 + 0.02*3000) / 4000 = (10 + 60) / 4000 = 0.0175
        assert result == pytest.approx(0.0175)

    def test_none_values_skipped(self, genome_service):
        rows = [
            {"ctr": None, "impressions": 1000},
            {"ctr": 0.02, "impressions": 2000},
        ]
        result = genome_service._weighted_avg(rows, "ctr", "impressions")
        assert result == pytest.approx(0.02)

    def test_all_none_returns_none(self, genome_service):
        rows = [{"ctr": None, "impressions": 1000}]
        result = genome_service._weighted_avg(rows, "ctr", "impressions")
        assert result is None

    def test_empty_rows(self, genome_service):
        result = genome_service._weighted_avg([], "ctr", "impressions")
        assert result is None


# ============================================================================
# _exploration_rate tests
# ============================================================================

class TestExplorationRate:
    def test_zero_ads_gives_initial(self, genome_service):
        rate = genome_service._exploration_rate(0)
        assert rate == pytest.approx(0.30)

    def test_high_ads_approaches_floor(self, genome_service):
        rate = genome_service._exploration_rate(1000)
        assert rate == pytest.approx(0.05, abs=0.001)

    def test_moderate_ads(self, genome_service):
        rate = genome_service._exploration_rate(100)
        # 0.30 * exp(-1) ≈ 0.110
        assert 0.10 < rate < 0.12


# ============================================================================
# _check_threshold tests
# ============================================================================

class TestCheckThreshold:
    def test_below_critical_creates_critical_alert(self, genome_service):
        mock_insert = MagicMock()
        mock_insert.execute = MagicMock()
        genome_service.supabase.table.return_value.insert.return_value = mock_insert

        result = genome_service._check_threshold(
            BRAND_ID, "approval_rate", 0.05, lower_is_worse=True
        )
        assert result == 1
        genome_service.supabase.table.assert_called_with("system_alerts")

    def test_between_warning_and_ok_no_alert(self, genome_service):
        result = genome_service._check_threshold(
            BRAND_ID, "approval_rate", 0.50, lower_is_worse=True
        )
        assert result == 0

    def test_higher_is_worse_critical(self, genome_service):
        mock_insert = MagicMock()
        mock_insert.execute = MagicMock()
        genome_service.supabase.table.return_value.insert.return_value = mock_insert

        result = genome_service._check_threshold(
            BRAND_ID, "data_freshness_days", 45, lower_is_worse=False
        )
        assert result == 1

    def test_higher_is_worse_ok(self, genome_service):
        result = genome_service._check_threshold(
            BRAND_ID, "data_freshness_days", 5, lower_is_worse=False
        )
        assert result == 0


# ============================================================================
# get_pre_gen_score tests
# ============================================================================

class TestPreGenScore:
    @pytest.mark.asyncio
    async def test_no_data_returns_neutral(self, genome_service):
        """When no element scores exist, returns 0.5."""
        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        score = await genome_service.get_pre_gen_score(BRAND_ID, {
            "hook_type": "curiosity_gap",
            "color_mode": "original",
        })
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_with_data_returns_average(self, genome_service):
        """When element scores exist, averages their posterior means."""
        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                # First two calls return data (for two tracked elements)
                result.data = [{"alpha": 8.0, "beta": 2.0}]  # mean = 0.8
            else:
                result.data = []
            return result

        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute = mock_execute
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        score = await genome_service.get_pre_gen_score(BRAND_ID, {
            "hook_type": "curiosity_gap",
            "color_mode": "original",
        })
        assert score == pytest.approx(0.8)


# ============================================================================
# sample_element_scores tests
# ============================================================================

class TestSampleElementScores:
    def test_returns_ranked_samples(self, genome_service):
        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[
            {"element_value": "complementary", "alpha": 8.0, "beta": 2.0,
             "mean_reward": 0.8, "total_observations": 10},
            {"element_value": "original", "alpha": 2.0, "beta": 8.0,
             "mean_reward": 0.2, "total_observations": 10},
        ])
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        results = genome_service.sample_element_scores(BRAND_ID, "color_mode")
        assert len(results) == 2
        # Both have value, sample, alpha, beta keys
        assert "value" in results[0]
        assert "sample" in results[0]
        # Results are sorted by sample (highest first)
        assert results[0]["sample"] >= results[1]["sample"]

    def test_no_data_returns_empty(self, genome_service):
        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        results = genome_service.sample_element_scores(BRAND_ID, "color_mode")
        assert results == []


# ============================================================================
# get_category_priors tests
# ============================================================================

class TestCategoryPriors:
    @pytest.mark.asyncio
    async def test_no_data_returns_uniform(self, genome_service):
        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        alpha, beta = await genome_service.get_category_priors("hook_type")
        assert alpha == 1.0
        assert beta == 1.0

    @pytest.mark.asyncio
    async def test_with_data_applies_shrinkage(self, genome_service):
        mock_chain = MagicMock()
        mock_chain.eq.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[
            {"alpha": 5.0, "beta": 2.0, "total_observations": 10},
            {"alpha": 3.0, "beta": 4.0, "total_observations": 10},
        ])
        genome_service.supabase.table.return_value.select.return_value = mock_chain

        alpha, beta = await genome_service.get_category_priors("hook_type")

        # avg_alpha = (5*10 + 3*10) / 20 = 4.0
        # avg_beta = (2*10 + 4*10) / 20 = 3.0
        # prior_alpha = 1.0 + 0.3 * (4.0 - 1.0) = 1.9
        # prior_beta = 1.0 + 0.3 * (3.0 - 1.0) = 1.6
        assert alpha == pytest.approx(1.9)
        assert beta == pytest.approx(1.6)


# ============================================================================
# Constants validation
# ============================================================================

class TestConstants:
    def test_reward_weights_sum_to_one(self):
        for objective, weights in REWARD_WEIGHTS.items():
            total = sum(weights.values())
            assert total == pytest.approx(1.0), f"{objective} weights don't sum to 1.0"

    def test_tracked_elements_are_strings(self):
        for elem in TRACKED_ELEMENTS:
            assert isinstance(elem, str)

    def test_maturation_windows_have_required_keys(self):
        for key, (days, imp) in MATURATION_WINDOWS.items():
            assert days > 0
            assert imp > 0

    def test_monitoring_thresholds_have_severity_levels(self):
        for metric, thresholds in MONITORING_THRESHOLDS.items():
            assert "warning" in thresholds
            assert "critical" in thresholds
