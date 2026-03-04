"""
Tests for template_scoring_service — Phase 4 scorer expansion.

Tests AwarenessAlignScorer, AudienceMatchScorer, BeliefClarityScorer,
weight presets, PHASE_3/4_SCORERS lists, fallback context, and
fetch_brand_min_asset_score.
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID

from viraltracker.services.template_scoring_service import (
    AwarenessAlignScorer,
    AudienceMatchScorer,
    BeliefClarityScorer,
    SelectionContext,
    ROLL_THE_DICE_WEIGHTS,
    SMART_SELECT_WEIGHTS,
    PHASE_1_SCORERS,
    PHASE_3_SCORERS,
    PHASE_4_SCORERS,
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
# BeliefClarityScorer
# ============================================================================

class TestBeliefClarityScorer:
    """BeliefClarityScorer: no eval→0.5, D6=false→0.0, else D1-D5/15."""

    def setup_method(self):
        self.scorer = BeliefClarityScorer()

    def test_no_eval_key_returns_neutral(self):
        """Template without eval_total_score key → 0.5 (no data)."""
        template = {"id": "t1"}
        assert self.scorer.score(template, _ctx()) == 0.5

    def test_eval_total_score_none_returns_neutral(self):
        """LEFT JOIN returned NULL (no evaluation row) → 0.5."""
        template = {
            "id": "t1",
            "eval_total_score": None,
            "eval_d6_compliance_pass": None,
        }
        assert self.scorer.score(template, _ctx()) == 0.5

    def test_d6_false_returns_zero(self):
        """D6 compliance fail → 0.0 regardless of D1-D5 scores."""
        template = {
            "id": "t1",
            "eval_total_score": 15,
            "eval_d6_compliance_pass": False,
        }
        assert self.scorer.score(template, _ctx()) == 0.0

    def test_perfect_scores_returns_one(self):
        """D6=true, D1-D5 all 3 (total=15) → 1.0."""
        template = {
            "id": "t1",
            "eval_total_score": 15,
            "eval_d6_compliance_pass": True,
        }
        assert self.scorer.score(template, _ctx()) == 1.0

    def test_mixed_scores(self):
        """D6=true, D1-D5 mixed: (3+2+1+3+2)=11 → 11/15 ≈ 0.7333."""
        template = {
            "id": "t1",
            "eval_total_score": 11,
            "eval_d6_compliance_pass": True,
        }
        assert abs(self.scorer.score(template, _ctx()) - 11 / 15.0) < 1e-9

    def test_all_zeros(self):
        """D6=true, all D1-D5 are 0 → 0/15 = 0.0."""
        template = {
            "id": "t1",
            "eval_total_score": 0,
            "eval_d6_compliance_pass": True,
        }
        assert self.scorer.score(template, _ctx()) == 0.0

    def test_partial_nulls_coalesced(self):
        """D1-D5 with some NULLs: DB COALESCE(0) → total_score reflects that.

        If D1=3, D2=None(0), D3=2, D4=None(0), D5=3 → total=8 → 8/15.
        """
        template = {
            "id": "t1",
            "eval_total_score": 8,
            "eval_d6_compliance_pass": True,
        }
        assert abs(self.scorer.score(template, _ctx()) - 8 / 15.0) < 1e-9

    def test_d6_none_treated_as_no_penalty(self):
        """d6_compliance_pass=None (not False) → not penalized, scores normally."""
        template = {
            "id": "t1",
            "eval_total_score": 12,
            "eval_d6_compliance_pass": None,
        }
        assert abs(self.scorer.score(template, _ctx()) - 12 / 15.0) < 1e-9

    def test_name_attribute(self):
        assert self.scorer.name == "belief_clarity"


# ============================================================================
# Weight Presets
# ============================================================================

class TestWeightPresets:
    """Weight presets have all scorer keys."""

    def test_roll_the_dice_has_all_keys(self):
        expected_keys = {"asset_match", "unused_bonus", "category_match",
                         "awareness_align", "audience_match", "belief_clarity",
                         "performance", "fatigue"}
        assert set(ROLL_THE_DICE_WEIGHTS.keys()) == expected_keys

    def test_smart_select_has_all_keys(self):
        expected_keys = {"asset_match", "unused_bonus", "category_match",
                         "awareness_align", "audience_match", "belief_clarity",
                         "performance", "fatigue"}
        assert set(SMART_SELECT_WEIGHTS.keys()) == expected_keys

    def test_roll_the_dice_new_scorers_neutral(self):
        """New scorers have weight 0 in roll_the_dice (unchanged behavior)."""
        assert ROLL_THE_DICE_WEIGHTS["awareness_align"] == 0.0
        assert ROLL_THE_DICE_WEIGHTS["audience_match"] == 0.0
        assert ROLL_THE_DICE_WEIGHTS["belief_clarity"] == 0.0
        assert ROLL_THE_DICE_WEIGHTS["performance"] == 0.0

    def test_smart_select_new_scorers_have_weight(self):
        assert SMART_SELECT_WEIGHTS["awareness_align"] > 0
        assert SMART_SELECT_WEIGHTS["audience_match"] > 0
        assert SMART_SELECT_WEIGHTS["belief_clarity"] > 0
        assert SMART_SELECT_WEIGHTS["performance"] > 0


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


class TestPhase4Scorers:
    """PHASE_4_SCORERS list has exactly 6 scorers (Phase 3 + BeliefClarity)."""

    def test_phase4_has_6_scorers(self):
        assert len(PHASE_4_SCORERS) == 6

    def test_phase4_scorer_names(self):
        names = [s.name for s in PHASE_4_SCORERS]
        assert "asset_match" in names
        assert "unused_bonus" in names
        assert "category_match" in names
        assert "awareness_align" in names
        assert "audience_match" in names
        assert "belief_clarity" in names

    def test_phase8_is_default(self):
        """select_templates_with_fallback uses PHASE_8_SCORERS by default (Phase 8B change)."""
        # Verify by checking the function uses 8 scorers when none provided
        # We do this by calling with a single candidate and checking score keys
        candidates = [
            {
                "id": "t1",
                "category": "testimonial",
                "is_unused": True,
                "has_detection": False,
            },
        ]
        context = _ctx()
        result = select_templates_with_fallback(
            candidates=candidates,
            context=context,
            weights=SMART_SELECT_WEIGHTS,
            count=1,
        )
        assert not result.empty
        # Should have all 8 scorer names + composite (Phase 8B: PHASE_8_SCORERS is default)
        score_keys = set(result.scores[0].keys()) - {"composite"}
        assert "belief_clarity" in score_keys
        assert "performance" in score_keys
        assert "fatigue" in score_keys
        assert len(score_keys) == 8

    def test_phase3_backward_compat(self):
        """Phase 3 scorer list is still 5 (no belief_clarity)."""
        names = [s.name for s in PHASE_3_SCORERS]
        assert "belief_clarity" not in names


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
