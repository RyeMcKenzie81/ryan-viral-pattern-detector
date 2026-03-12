"""
Tests for WinnerDNAAnalyzer — DNA decomposition, cross-winner patterns, action briefs.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock

from viraltracker.services.winner_dna_analyzer import (
    WinnerDNAAnalyzer,
    WinnerDNA,
    CrossWinnerAnalysis,
    ELEMENT_DISPLAY_NAMES,
    COMMON_ELEMENT_THRESHOLD,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def analyzer():
    mock_supabase = MagicMock()
    mock_gemini = MagicMock()
    return WinnerDNAAnalyzer(mock_supabase, mock_gemini)


def _make_dna(
    meta_ad_id="ad_1",
    element_scores=None,
    visual_properties=None,
    messaging=None,
    synergies=None,
    conflicts=None,
):
    return WinnerDNA(
        meta_ad_id=meta_ad_id,
        metrics={"roas": 3.0, "ctr": 1.5, "cpc": 0.50, "cpa": 15.0},
        element_scores=element_scores or [],
        top_elements=(element_scores or [])[:3],
        weak_elements=(element_scores or [])[-3:] if element_scores and len(element_scores) >= 6 else [],
        visual_properties=visual_properties,
        messaging=messaging or {"hook_type": "curiosity", "awareness_level": "problem_aware"},
        cohort_comparison={},
        active_synergies=synergies or [],
        active_conflicts=conflicts or [],
    )


# ============================================================================
# build_action_brief tests
# ============================================================================

class TestBuildActionBrief:
    def test_includes_performance(self, analyzer):
        dna = _make_dna()
        brief = analyzer.build_action_brief(dna)
        assert "ROAS: 3.0x" in brief
        assert "CTR: 1.50%" in brief

    def test_includes_top_elements(self, analyzer):
        dna = _make_dna(element_scores=[
            {"element": "hook_type", "display_name": "Hook Style", "value": "curiosity", "mean_reward": 0.82, "percentile_rank": "top 9%"},
        ])
        brief = analyzer.build_action_brief(dna)
        assert "Hook Style" in brief
        assert "curiosity" in brief

    def test_includes_visual_changes_when_low_contrast(self, analyzer):
        dna = _make_dna(visual_properties={
            "contrast_level": "low",
            "text_density": "none",
            "face_presence": False,
            "color_palette_type": "cool",
        })
        brief = analyzer.build_action_brief(dna)
        assert "CONTRAST" in brief
        assert "TEXT" in brief
        assert "FACE" in brief

    def test_includes_synergies(self, analyzer):
        dna = _make_dna(synergies=[
            {"pair": "hook_type:curiosity + color_mode:complementary", "effect": 0.15},
        ])
        brief = analyzer.build_action_brief(dna)
        assert "Synergy" in brief
        assert "+15%" in brief

    def test_includes_opportunity_actions(self, analyzer):
        dna = _make_dna()
        opp = {
            "pattern_label": "Strong ROAS, Weak CTR",
            "strategy_actions": ["Add bold headline", "Try face close-up"],
        }
        brief = analyzer.build_action_brief(dna, opp)
        assert "Add bold headline" in brief
        assert "Try face close-up" in brief

    def test_no_visual_props_still_produces_brief(self, analyzer):
        dna = _make_dna(visual_properties=None)
        brief = analyzer.build_action_brief(dna)
        assert "WHAT'S WORKING:" in brief or "RECOMMENDATIONS:" in brief


# ============================================================================
# _find_common_elements tests
# ============================================================================

class TestFindCommonElements:
    def test_above_threshold(self, analyzer):
        """3/4 winners with same element passes 70% threshold."""
        dnas = [
            _make_dna("ad_1", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_2", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_3", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_4", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
        ]
        common = analyzer._find_common_elements(dnas)
        assert "hook_type:curiosity" in common
        assert common["hook_type:curiosity"]["frequency"] == 0.75

    def test_below_threshold(self, analyzer):
        """2/4 winners = 50% does NOT pass 70% threshold."""
        dnas = [
            _make_dna("ad_1", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_2", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_3", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
            _make_dna("ad_4", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
        ]
        common = analyzer._find_common_elements(dnas)
        assert "hook_type:curiosity" not in common
        assert "hook_type:direct_benefit" not in common

    def test_multiple_elements(self, analyzer):
        """Multiple elements can be common independently."""
        dnas = [
            _make_dna("ad_1", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
                {"element": "color_mode", "value": "complementary"},
            ]),
            _make_dna("ad_2", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
                {"element": "color_mode", "value": "complementary"},
            ]),
            _make_dna("ad_3", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
                {"element": "color_mode", "value": "brand"},
            ]),
        ]
        common = analyzer._find_common_elements(dnas)
        assert "hook_type:curiosity" in common  # 3/3 = 100%
        assert "color_mode:complementary" not in common  # 2/3 = 67% < 70%


# ============================================================================
# _find_common_visual_traits tests
# ============================================================================

class TestFindCommonVisualTraits:
    def test_sufficient_visuals(self, analyzer):
        dnas = [
            _make_dna("ad_1", visual_properties={"contrast_level": "high", "face_presence": True}),
            _make_dna("ad_2", visual_properties={"contrast_level": "high", "face_presence": True}),
            _make_dna("ad_3", visual_properties={"contrast_level": "high", "face_presence": False}),
        ]
        common = analyzer._find_common_visual_traits(dnas)
        assert "contrast_level" in common
        assert common["contrast_level"]["value"] == "high"

    def test_insufficient_visuals_returns_empty(self, analyzer):
        dnas = [
            _make_dna("ad_1", visual_properties={"contrast_level": "high"}),
            _make_dna("ad_2", visual_properties=None),
            _make_dna("ad_3", visual_properties=None),
        ]
        common = analyzer._find_common_visual_traits(dnas)
        assert common == {}


# ============================================================================
# _build_iteration_directions tests
# ============================================================================

class TestBuildIterationDirections:
    def test_combines_elements_visuals_antipatterns(self, analyzer):
        common_elements = {
            "hook_type:curiosity": {
                "element": "hook_type",
                "display_name": "Hook Style",
                "value": "curiosity",
                "frequency": 0.8,
                "count": 8,
                "total": 10,
            }
        }
        common_visuals = {
            "contrast_level": {
                "value": "high",
                "frequency": 0.9,
                "count": 9,
                "total": 10,
            }
        }
        anti_patterns = [
            {"element": "color_mode", "value": "brand", "loser_frequency": 0.5, "loser_count": 5, "total_losers": 10},
        ]
        directions = analyzer._build_iteration_directions(
            common_elements, common_visuals, anti_patterns, 10
        )
        assert len(directions) == 3
        sources = {d["source"] for d in directions}
        assert "element" in sources
        assert "visual" in sources
        assert "anti_pattern" in sources

    def test_sorted_by_confidence(self, analyzer):
        common_elements = {
            "a:low": {"element": "a", "display_name": "A", "value": "low", "frequency": 0.5, "count": 5, "total": 10},
            "b:high": {"element": "b", "display_name": "B", "value": "high", "frequency": 0.9, "count": 9, "total": 10},
        }
        directions = analyzer._build_iteration_directions(common_elements, {}, [], 10)
        assert directions[0]["confidence"] >= directions[1]["confidence"]


# ============================================================================
# _build_replication_blueprint tests
# ============================================================================

class TestBuildReplicationBlueprint:
    def test_structure(self, analyzer):
        common_elements = {
            "hook_type:curiosity": {"element": "hook_type", "value": "curiosity"},
        }
        common_visuals = {
            "contrast_level": {"value": "high"},
        }
        dnas = [
            _make_dna("ad_1", messaging={"hook_type": "curiosity", "awareness_level": "problem_aware"}),
            _make_dna("ad_2", messaging={"hook_type": "curiosity", "awareness_level": "problem_aware"}),
        ]
        blueprint = analyzer._build_replication_blueprint(common_elements, common_visuals, dnas)

        assert "element_combo" in blueprint
        assert "visual_directives" in blueprint
        assert "messaging_directives" in blueprint
        assert blueprint["element_combo"]["hook_type"] == "curiosity"
        assert blueprint["visual_directives"]["contrast_level"] == "high"
        assert blueprint["messaging_directives"]["hook_type"] == "curiosity"


# ============================================================================
# _build_messaging_profile tests
# ============================================================================

class TestBuildMessagingProfile:
    def test_merges_classification_and_tags(self, analyzer):
        classification = {
            "creative_awareness_level": "problem_aware",
            "creative_angle": "pain point",
            "primary_cta": "Shop Now",
            "creative_format": "image_static",
        }
        element_tags = {
            "hook_type": "curiosity",
        }
        profile = analyzer._build_messaging_profile(classification, element_tags)
        assert profile["hook_type"] == "curiosity"  # From element_tags
        assert profile["awareness_level"] == "problem_aware"  # From classification
        assert profile["creative_format"] == "image_static"

    def test_element_tags_override_classification(self, analyzer):
        classification = {"hook_type": "direct_benefit"}
        element_tags = {"hook_type": "curiosity"}
        profile = analyzer._build_messaging_profile(classification, element_tags)
        assert profile["hook_type"] == "curiosity"  # element_tags wins
