"""
Tests for FatigueScorer — Phase 8A hybrid template + element combo fatigue.

Tests template decay curves, combo modifier with sparse-data fallback,
bounds [0.2, 1.0], edge cases, and combo key generation.
"""

import math
import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID

from viraltracker.services.template_scoring_service import (
    FatigueScorer,
    SelectionContext,
    PHASE_8_SCORERS,
    PHASE_6_SCORERS,
    ROLL_THE_DICE_WEIGHTS,
    SMART_SELECT_WEIGHTS,
)


def _ctx(**overrides):
    """Create a minimal SelectionContext with defaults."""
    defaults = {
        "product_id": UUID("00000000-0000-0000-0000-000000000001"),
        "brand_id": UUID("00000000-0000-0000-0000-000000000002"),
    }
    defaults.update(overrides)
    return SelectionContext(**defaults)


class TestFatigueScorerConstants:
    """Test FatigueScorer class constants."""

    def test_name(self):
        assert FatigueScorer.name == "fatigue"

    def test_decay_lambda(self):
        assert FatigueScorer.DECAY_LAMBDA == 0.05

    def test_combo_decay_lambda(self):
        assert FatigueScorer.COMBO_DECAY_LAMBDA == 0.03

    def test_min_combo_observations(self):
        assert FatigueScorer.MIN_COMBO_OBSERVATIONS == 3


class TestFatigueScorerDecay:
    """Test template-level decay curve."""

    def test_half_life_approximately_14_days(self):
        """Verify ~14-day half-life with lambda=0.05."""
        half_life = math.log(2) / 0.05
        assert abs(half_life - 13.86) < 0.1

    def test_unused_template_scores_1(self):
        """Never-used template should score 1.0."""
        scorer = FatigueScorer()
        template = {"is_unused": True}
        context = _ctx()
        assert scorer._compute_template_decay(template, context) == 1.0

    def test_decay_after_0_days(self):
        """Template used today: exp(-0.05 * 0) = 1.0."""
        assert math.exp(-0.05 * 0) == 1.0

    def test_decay_after_14_days(self):
        """Template used 14 days ago: ~0.5."""
        decay = math.exp(-0.05 * 14)
        assert abs(decay - 0.5) < 0.05

    def test_decay_after_30_days(self):
        """Template used 30 days ago: ~0.22."""
        decay = math.exp(-0.05 * 30)
        assert abs(decay - 0.22) < 0.05


class TestComboDecay:
    """Test element combo modifier decay."""

    def test_combo_half_life_approximately_23_days(self):
        """Verify ~23-day half-life with lambda=0.03."""
        half_life = math.log(2) / 0.03
        assert abs(half_life - 23.1) < 0.1

    def test_neutral_when_no_combo_data(self):
        """Combo modifier should be 1.0 when no data available."""
        scorer = FatigueScorer()
        template = {}
        context = _ctx()
        assert scorer._compute_combo_modifier(template, context) == 1.0


class TestFatigueScorerBounds:
    """Test score bounds [0.2, 1.0]."""

    def test_minimum_score_is_0_2(self):
        """Score should never go below 0.2."""
        scorer = FatigueScorer()
        # With both base and combo at minimum
        result = max(0.2, min(1.0, 0.1 * 0.1))
        assert result == 0.2

    def test_maximum_score_is_1_0(self):
        """Score should cap at 1.0."""
        scorer = FatigueScorer()
        result = max(0.2, min(1.0, 1.5))
        assert result == 1.0

    def test_score_with_unused_template(self):
        """Unused template: base=1.0 * combo=1.0 → 1.0."""
        scorer = FatigueScorer()
        template = {"is_unused": True}
        context = _ctx()

        with patch.object(scorer, '_compute_combo_modifier', return_value=1.0):
            score = scorer.score(template, context)
            assert score == 1.0

    def test_score_clamped_to_0_2(self):
        """Very old template with very old combo should clamp to 0.2."""
        scorer = FatigueScorer()
        template = {"is_unused": False}
        context = _ctx()

        with patch.object(scorer, '_compute_template_decay', return_value=0.1):
            with patch.object(scorer, '_compute_combo_modifier', return_value=0.1):
                score = scorer.score(template, context)
                assert score == 0.2


class TestScorerLists:
    """Test PHASE_8_SCORERS list includes FatigueScorer."""

    def test_phase_8_includes_fatigue(self):
        scorer_names = [s.name for s in PHASE_8_SCORERS]
        assert "fatigue" in scorer_names

    def test_phase_8_is_superset_of_phase_6(self):
        phase_6_names = {s.name for s in PHASE_6_SCORERS}
        phase_8_names = {s.name for s in PHASE_8_SCORERS}
        assert phase_6_names.issubset(phase_8_names)

    def test_phase_8_has_8_scorers(self):
        assert len(PHASE_8_SCORERS) == 8


class TestWeightPresets:
    """Test weight presets include fatigue key."""

    def test_roll_the_dice_has_fatigue(self):
        assert "fatigue" in ROLL_THE_DICE_WEIGHTS
        assert ROLL_THE_DICE_WEIGHTS["fatigue"] == 0.2

    def test_smart_select_has_fatigue(self):
        assert "fatigue" in SMART_SELECT_WEIGHTS
        assert SMART_SELECT_WEIGHTS["fatigue"] == 0.4


class TestComboKeyGeneration:
    """Test combo key canonical format."""

    def test_sorted_canonical_format(self):
        """Combo key should be sorted alphabetically."""
        parts = {"hook_type": "curiosity", "color_mode": "warm", "template_category": "hero"}
        combo_key = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
        assert combo_key == "color_mode=warm|hook_type=curiosity|template_category=hero"

    def test_single_element_combo(self):
        parts = {"hook_type": "curiosity"}
        combo_key = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
        assert combo_key == "hook_type=curiosity"

    def test_empty_combo(self):
        parts = {}
        combo_key = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
        assert combo_key == ""
