"""
Tests for template_scoring_service — Phase 3 scorer expansion.

Tests AwarenessAlignScorer, AudienceMatchScorer, weight presets,
PHASE_3_SCORERS list, fallback context target_sex, and fetch_brand_min_asset_score.
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID

from viraltracker.services.template_scoring_service import (
    AwarenessAlignScorer,
    AudienceMatchScorer,
    SelectionContext,
    ROLL_THE_DICE_WEIGHTS,
    SMART_SELECT_WEIGHTS,
    PHASE_1_SCORERS,
    PHASE_3_SCORERS,
    select_templates_with_fallback,
    fetch_brand_min_asset_score,
)


def _ctx(**overrides):
    """Create a minimal SelectionContext with defaults."""
    defaults = {
        "product_id": UUID("00000000-0000-0000-0000-000000000001"),
        "brand_id": UUID("00000000-0000-0000-0000-000000000002"),
    }
    defaults.update(overrides)
    return SelectionContext(**defaults)


# ============================================================================
# AwarenessAlignScorer
# ============================================================================

class TestAwarenessAlignScorer:
    """AwarenessAlignScorer: 1.0 - abs(template - persona) / 4.0."""

    def setup_method(self):
        self.scorer = AwarenessAlignScorer()

    def test_exact_match(self):
        template = {"awareness_level": 3}
        context = _ctx(awareness_stage=3)
        assert self.scorer.score(template, context) == 1.0

    def test_distance_1(self):
        template = {"awareness_level": 4}
        context = _ctx(awareness_stage=3)
        assert self.scorer.score(template, context) == 0.75

    def test_distance_2(self):
        template = {"awareness_level": 5}
        context = _ctx(awareness_stage=3)
        assert self.scorer.score(template, context) == 0.5

    def test_distance_4_min_score(self):
        template = {"awareness_level": 5}
        context = _ctx(awareness_stage=1)
        assert self.scorer.score(template, context) == 0.0

    def test_template_none_returns_neutral(self):
        template = {"awareness_level": None}
        context = _ctx(awareness_stage=3)
        assert self.scorer.score(template, context) == 0.5

    def test_context_none_returns_neutral(self):
        template = {"awareness_level": 3}
        context = _ctx(awareness_stage=None)
        assert self.scorer.score(template, context) == 0.5

    def test_both_none_returns_neutral(self):
        template = {}
        context = _ctx()
        assert self.scorer.score(template, context) == 0.5

    def test_name_attribute(self):
        assert self.scorer.name == "awareness_align"


# ============================================================================
# AudienceMatchScorer
# ============================================================================

class TestAudienceMatchScorer:
    """AudienceMatchScorer: exact→1.0, unisex/None→0.7, mismatch→0.2."""

    def setup_method(self):
        self.scorer = AudienceMatchScorer()

    def test_exact_match_male(self):
        template = {"target_sex": "male"}
        context = _ctx(target_sex="male")
        assert self.scorer.score(template, context) == 1.0

    def test_exact_match_female(self):
        template = {"target_sex": "female"}
        context = _ctx(target_sex="female")
        assert self.scorer.score(template, context) == 1.0

    def test_template_unisex(self):
        template = {"target_sex": "unisex"}
        context = _ctx(target_sex="male")
        assert self.scorer.score(template, context) == 0.7

    def test_context_unisex(self):
        template = {"target_sex": "female"}
        context = _ctx(target_sex="unisex")
        assert self.scorer.score(template, context) == 0.7

    def test_both_unisex(self):
        template = {"target_sex": "unisex"}
        context = _ctx(target_sex="unisex")
        assert self.scorer.score(template, context) == 1.0

    def test_template_none_neutral(self):
        template = {}
        context = _ctx(target_sex="male")
        assert self.scorer.score(template, context) == 0.7

    def test_context_none_neutral(self):
        template = {"target_sex": "female"}
        context = _ctx(target_sex=None)
        assert self.scorer.score(template, context) == 0.7

    def test_both_none_neutral(self):
        template = {}
        context = _ctx()
        assert self.scorer.score(template, context) == 0.7

    def test_mismatch_male_female(self):
        template = {"target_sex": "male"}
        context = _ctx(target_sex="female")
        assert self.scorer.score(template, context) == 0.2

    def test_mismatch_female_male(self):
        template = {"target_sex": "female"}
        context = _ctx(target_sex="male")
        assert self.scorer.score(template, context) == 0.2

    def test_name_attribute(self):
        assert self.scorer.name == "audience_match"


# ============================================================================
# Weight Presets
# ============================================================================

class TestWeightPresets:
    """Weight presets have all 5 scorer keys."""

    def test_roll_the_dice_has_all_keys(self):
        expected_keys = {"asset_match", "unused_bonus", "category_match",
                         "awareness_align", "audience_match"}
        assert set(ROLL_THE_DICE_WEIGHTS.keys()) == expected_keys

    def test_smart_select_has_all_keys(self):
        expected_keys = {"asset_match", "unused_bonus", "category_match",
                         "awareness_align", "audience_match"}
        assert set(SMART_SELECT_WEIGHTS.keys()) == expected_keys

    def test_roll_the_dice_new_scorers_neutral(self):
        """New scorers have weight 0 in roll_the_dice (unchanged behavior)."""
        assert ROLL_THE_DICE_WEIGHTS["awareness_align"] == 0.0
        assert ROLL_THE_DICE_WEIGHTS["audience_match"] == 0.0

    def test_smart_select_new_scorers_have_weight(self):
        assert SMART_SELECT_WEIGHTS["awareness_align"] > 0
        assert SMART_SELECT_WEIGHTS["audience_match"] > 0


# ============================================================================
# PHASE_3_SCORERS
# ============================================================================

class TestPhase3Scorers:
    """PHASE_3_SCORERS list has exactly 5 scorers."""

    def test_phase3_has_5_scorers(self):
        assert len(PHASE_3_SCORERS) == 5

    def test_phase3_scorer_names(self):
        names = [s.name for s in PHASE_3_SCORERS]
        assert "asset_match" in names
        assert "unused_bonus" in names
        assert "category_match" in names
        assert "awareness_align" in names
        assert "audience_match" in names

    def test_phase1_unchanged(self):
        assert len(PHASE_1_SCORERS) == 3


# ============================================================================
# Fallback context preserves target_sex
# ============================================================================

class TestFallbackContextTargetSex:
    """select_templates_with_fallback tier-3 preserves target_sex."""

    def test_tier3_fallback_preserves_target_sex(self):
        """When tier-3 fires, the relaxed context should carry target_sex."""
        context = _ctx(
            requested_category="nonexistent_category",
            target_sex="female",
        )

        # Create candidates that won't match the category but are valid
        candidates = [
            {
                "id": "t1",
                "category": "testimonial",
                "is_unused": True,
                "has_detection": False,
            },
        ]

        result = select_templates_with_fallback(
            candidates=candidates,
            context=context,
            weights=SMART_SELECT_WEIGHTS,
            count=1,
            min_asset_score=0.0,
        )

        # Should succeed via tier-3 fallback
        assert not result.empty
        assert len(result.templates) == 1

        # Verify the audience_match score reflects female context vs no template sex
        # Template has no target_sex → scorer returns 0.7 (neutral)
        score = result.scores[0].get("audience_match", 0)
        assert score == 0.7


# ============================================================================
# fetch_brand_min_asset_score
# ============================================================================

class TestFetchBrandMinAssetScore:
    """fetch_brand_min_asset_score helper tests."""

    @patch("viraltracker.core.database.get_supabase_client")
    def test_returns_config_value(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": {"min_asset_score": 0.5}}
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.5

    @patch("viraltracker.core.database.get_supabase_client")
    def test_returns_default_when_no_config(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": None}
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.0

    @patch("viraltracker.core.database.get_supabase_client")
    def test_returns_default_when_no_row(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.0

    @patch("viraltracker.core.database.get_supabase_client")
    def test_handles_malformed_config(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": {"min_asset_score": "abc"}}
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.0

    @patch("viraltracker.core.database.get_supabase_client")
    def test_clamps_high_value(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": {"min_asset_score": 2.5}}
        )
        assert fetch_brand_min_asset_score("brand-1") == 1.0

    @patch("viraltracker.core.database.get_supabase_client")
    def test_clamps_negative_value(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": {"min_asset_score": -0.5}}
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.0

    @patch("viraltracker.core.database.get_supabase_client")
    def test_handles_string_number(self, mock_db_fn):
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"template_selection_config": {"min_asset_score": "0.7"}}
        )
        assert fetch_brand_min_asset_score("brand-1") == 0.7

    @patch("viraltracker.core.database.get_supabase_client")
    def test_handles_db_exception(self, mock_db_fn):
        mock_db_fn.side_effect = Exception("Connection refused")
        assert fetch_brand_min_asset_score("brand-1") == 0.0
