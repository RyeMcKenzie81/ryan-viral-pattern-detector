"""
Tests for IterationOpportunityDetector — pattern matching, confidence scoring, baseline comparison.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock

from viraltracker.services.iteration_opportunity_detector import (
    _get_baseline_value,
    _compute_percentile_label,
    _compute_confidence,
    IterationOpportunityDetector,
    PATTERNS,
)


# ============================================================================
# Fixtures
# ============================================================================

class MockBaseline:
    """Mock BaselineSnapshot with percentile values."""
    def __init__(self, **kwargs):
        defaults = {
            "p25_ctr": 0.5, "median_ctr": 1.0, "p75_ctr": 2.0,
            "p25_roas": 0.5, "median_roas": 1.5, "p75_roas": 3.0,
            "p25_cpc": 0.3, "median_cpc": 0.8, "p75_cpc": 1.5,
            "median_hook_rate": 0.15,
            "median_hold_rate": 0.08,
            "p25_conversion_rate": 1.0, "median_conversion_rate": 3.0, "p75_conversion_rate": 6.0,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


@pytest.fixture
def baseline():
    return MockBaseline()


@pytest.fixture
def detector():
    mock_supabase = MagicMock()
    return IterationOpportunityDetector(mock_supabase)


# ============================================================================
# _get_baseline_value tests
# ============================================================================

class TestGetBaselineValue:
    def test_p25_ctr(self, baseline):
        assert _get_baseline_value(baseline, "ctr", "p25") == 0.5

    def test_p50_roas(self, baseline):
        assert _get_baseline_value(baseline, "roas", "p50") == 1.5

    def test_p75_cpc(self, baseline):
        assert _get_baseline_value(baseline, "cpc", "p75") == 1.5

    def test_missing_attr_returns_none(self, baseline):
        assert _get_baseline_value(baseline, "nonexistent", "p50") is None

    def test_p50_below_returns_median(self, baseline):
        # p50_below is used for video metrics where we only have median
        assert _get_baseline_value(baseline, "hold_rate", "p50_below") == 0.08

    def test_hook_rate_p50(self, baseline):
        assert _get_baseline_value(baseline, "hook_rate", "p50") == 0.15


# ============================================================================
# _compute_percentile_label tests
# ============================================================================

class TestComputePercentileLabel:
    def test_below_p25(self, baseline):
        label = _compute_percentile_label(0.2, baseline, "ctr")
        assert label.startswith("p")
        pct = int(label[1:])
        assert 0 <= pct <= 25

    def test_at_p25(self, baseline):
        label = _compute_percentile_label(0.5, baseline, "ctr")
        assert label == "p25"

    def test_between_p25_p50(self, baseline):
        label = _compute_percentile_label(0.75, baseline, "ctr")
        pct = int(label[1:])
        assert 25 <= pct <= 50

    def test_at_median(self, baseline):
        label = _compute_percentile_label(1.0, baseline, "ctr")
        # At median, should be p50
        assert label == "p50"

    def test_above_p75(self, baseline):
        label = _compute_percentile_label(5.0, baseline, "ctr")
        assert label == "p75+"

    def test_missing_baseline_returns_na(self):
        empty = MockBaseline(p25_ctr=None, median_ctr=None, p75_ctr=None)
        assert _compute_percentile_label(1.0, empty, "ctr") == "n/a"


# ============================================================================
# _compute_confidence tests
# ============================================================================

class TestComputeConfidence:
    def test_strong_signal_high_confidence(self):
        # Strong excess and weak gap with good data volume
        conf = _compute_confidence(
            strong_val=5.0, strong_threshold=1.5,
            weak_val=0.1, weak_threshold=0.5,
            impressions=10000, days_active=14,
        )
        assert 0.6 < conf <= 1.0

    def test_weak_signal_lower_confidence(self):
        # Barely above/below thresholds
        conf = _compute_confidence(
            strong_val=1.6, strong_threshold=1.5,
            weak_val=0.45, weak_threshold=0.5,
            impressions=1000, days_active=7,
        )
        assert 0.1 <= conf <= 0.6

    def test_low_data_reduces_confidence(self):
        high_data = _compute_confidence(3.0, 1.5, 0.2, 0.5, 10000, 14)
        low_data = _compute_confidence(3.0, 1.5, 0.2, 0.5, 500, 3)
        assert low_data < high_data

    def test_clamped_to_range(self):
        # Even extreme values stay in [0.1, 1.0]
        conf_max = _compute_confidence(100.0, 1.0, 0.0, 1.0, 50000, 30)
        conf_min = _compute_confidence(1.1, 1.0, 0.9, 1.0, 100, 1)
        assert 0.1 <= conf_min <= 1.0
        assert 0.1 <= conf_max <= 1.0

    def test_zero_threshold_handled(self):
        # Should not crash with zero thresholds
        conf = _compute_confidence(2.0, 0, 0.1, 0, 5000, 10)
        assert 0.1 <= conf <= 1.0


# ============================================================================
# _evaluate_pattern tests
# ============================================================================

class TestEvaluatePattern:
    def test_high_converter_low_stopper_matches(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_123",
            "brand_id": "brand_1",
            "ad_name": "Test Ad",
            "impressions": 5000,
            "days_active": 10,
            "roas": 3.0,      # Above p50 (1.5)
            "ctr": 0.3,       # Below p25 (0.5)
            "spend": 100,
        }
        pattern_def = PATTERNS["high_converter_low_stopper"]
        result = detector._evaluate_pattern(
            ad, baseline, "high_converter_low_stopper", pattern_def, {}
        )
        assert result is not None
        assert result.pattern_type == "high_converter_low_stopper"
        assert result.strong_metric == "roas"
        assert result.weak_metric == "ctr"
        assert result.confidence > 0

    def test_rejects_insufficient_impressions(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_low",
            "brand_id": "brand_1",
            "impressions": 100,  # Below min 1000
            "days_active": 10,
            "roas": 3.0,
            "ctr": 0.3,
        }
        pattern_def = PATTERNS["high_converter_low_stopper"]
        result = detector._evaluate_pattern(
            ad, baseline, "high_converter_low_stopper", pattern_def, {}
        )
        assert result is None

    def test_rejects_insufficient_days(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_short",
            "brand_id": "brand_1",
            "impressions": 5000,
            "days_active": 3,  # Below min 7
            "roas": 3.0,
            "ctr": 0.3,
        }
        pattern_def = PATTERNS["high_converter_low_stopper"]
        result = detector._evaluate_pattern(
            ad, baseline, "high_converter_low_stopper", pattern_def, {}
        )
        assert result is None

    def test_rejects_strong_not_above_threshold(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_weak",
            "brand_id": "brand_1",
            "impressions": 5000,
            "days_active": 10,
            "roas": 1.0,      # Below p50 (1.5) — NOT strong
            "ctr": 0.3,
        }
        pattern_def = PATTERNS["high_converter_low_stopper"]
        result = detector._evaluate_pattern(
            ad, baseline, "high_converter_low_stopper", pattern_def, {}
        )
        assert result is None

    def test_rejects_weak_not_below_threshold(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_ok",
            "brand_id": "brand_1",
            "impressions": 5000,
            "days_active": 10,
            "roas": 3.0,
            "ctr": 1.5,       # Above p25 (0.5) — NOT weak
        }
        pattern_def = PATTERNS["high_converter_low_stopper"]
        result = detector._evaluate_pattern(
            ad, baseline, "high_converter_low_stopper", pattern_def, {}
        )
        assert result is None

    def test_efficient_but_starved_absolute_threshold(self, detector, baseline):
        ad = {
            "meta_ad_id": "ad_starved",
            "brand_id": "brand_1",
            "impressions": 3000,  # Below 5000 absolute threshold
            "days_active": 7,
            "roas": 2.0,         # Above p50 (1.5)
            "spend": 50,
        }
        pattern_def = PATTERNS["efficient_but_starved"]
        result = detector._evaluate_pattern(
            ad, baseline, "efficient_but_starved", pattern_def, {}
        )
        assert result is not None
        assert result.pattern_type == "efficient_but_starved"
        assert result.evolution_mode is None  # Budget recommendation, no evolution


# ============================================================================
# _build_iteration_instructions tests
# ============================================================================

class TestBuildIterationInstructions:
    def test_produces_formatted_string(self, detector):
        opp = {
            "pattern_type": "high_converter_low_stopper",
            "strong_metric": "roas",
            "strong_value": 3.2,
            "weak_metric": "ctr",
            "weak_value": 0.4,
            "strategy_category": "visual",
            "strategy_actions": ["Increase contrast", "Add headline"],
        }
        result = detector._build_iteration_instructions(opp)
        assert "VISUAL" in result
        assert "roas" in result
        assert "ctr" in result
        assert "Increase contrast" in result


# ============================================================================
# _build_strategy_actions tests
# ============================================================================

class TestBuildStrategyActions:
    def test_each_pattern_returns_actions(self, detector, baseline):
        for pattern_type in PATTERNS:
            actions = detector._build_strategy_actions(
                pattern_type, {"roas": 2.0, "spend": 100}, baseline, {}
            )
            assert isinstance(actions, list)
            assert len(actions) > 0
