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
        messaging=messaging if messaging is not None else {"hook_type": "curiosity", "awareness_level": "problem_aware"},
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
        """3/4 winners with same element passes 50% threshold."""
        dnas = [
            _make_dna("ad_1", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_2", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_3", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_4", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
        ]
        common = analyzer._find_common_elements(dnas)
        assert "hook_type:curiosity" in common
        assert common["hook_type:curiosity"]["frequency"] == 0.75

    def test_at_threshold(self, analyzer):
        """2/4 winners = 50% passes 50% threshold."""
        dnas = [
            _make_dna("ad_1", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_2", element_scores=[{"element": "hook_type", "value": "curiosity"}]),
            _make_dna("ad_3", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
            _make_dna("ad_4", element_scores=[{"element": "hook_type", "value": "direct_benefit"}]),
        ]
        common = analyzer._find_common_elements(dnas)
        assert "hook_type:curiosity" in common  # 2/4 = 50% = threshold
        assert "hook_type:direct_benefit" in common

    def test_below_threshold(self, analyzer):
        """1/4 winners = 25% does NOT pass 50% threshold."""
        dnas = [
            _make_dna("ad_1", element_scores=[{"element": "hook_type", "value": "curiosity"}], messaging={}),
            _make_dna("ad_2", element_scores=[{"element": "hook_type", "value": "direct_benefit"}], messaging={}),
            _make_dna("ad_3", element_scores=[{"element": "hook_type", "value": "social_proof"}], messaging={}),
            _make_dna("ad_4", element_scores=[{"element": "hook_type", "value": "urgency"}], messaging={}),
        ]
        common = analyzer._find_common_elements(dnas)
        assert len(common) == 0

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
        assert "color_mode:complementary" in common  # 2/3 = 67% >= 50%


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


# ============================================================================
# _find_notable_elements tests
# ============================================================================

class TestFindNotableElements:
    def test_finds_sub_threshold_elements(self, analyzer):
        """Elements at 25-49% frequency are returned; common_elements are excluded."""
        # 4 winners: hook_type:curiosity appears in 3/4 (75% -> common),
        # color_mode:complementary in 1/4 (25% -> notable),
        # creative_format:video in 2/4 (50% -> common, not notable)
        dnas = [
            _make_dna("ad_1", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
                {"element": "color_mode", "value": "complementary"},
            ], messaging={}),
            _make_dna("ad_2", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
            ], messaging={}),
            _make_dna("ad_3", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
            ], messaging={}),
            _make_dna("ad_4", element_scores=[
                {"element": "hook_type", "value": "direct_benefit"},
            ], messaging={}),
        ]
        common_elements = {
            "hook_type:curiosity": {"element": "hook_type", "value": "curiosity", "frequency": 0.75},
        }
        notable = analyzer._find_notable_elements(dnas, common_elements)
        # color_mode:complementary is 1/4 = 25% -> right at the 25% lower bound
        assert "color_mode:complementary" in notable
        assert notable["color_mode:complementary"]["frequency"] == 0.25
        # hook_type:curiosity is common, should be excluded
        assert "hook_type:curiosity" not in notable

    def test_caps_at_five(self, analyzer):
        """Returns at most 5 items even when more qualify."""
        # Create 8 distinct elements each at 25% frequency (1 out of 4 winners)
        dnas = [
            _make_dna("ad_1", element_scores=[
                {"element": "elem_a", "value": "v1"},
                {"element": "elem_b", "value": "v1"},
                {"element": "elem_c", "value": "v1"},
                {"element": "elem_d", "value": "v1"},
                {"element": "elem_e", "value": "v1"},
                {"element": "elem_f", "value": "v1"},
                {"element": "elem_g", "value": "v1"},
                {"element": "elem_h", "value": "v1"},
            ], messaging={}),
            _make_dna("ad_2", element_scores=[], messaging={}),
            _make_dna("ad_3", element_scores=[], messaging={}),
            _make_dna("ad_4", element_scores=[], messaging={}),
        ]
        notable = analyzer._find_notable_elements(dnas, {})
        assert len(notable) <= 5

    def test_excludes_common(self, analyzer):
        """Elements already in common_elements dict are not in the result."""
        dnas = [
            _make_dna("ad_1", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
            ], messaging={}),
            _make_dna("ad_2", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
            ], messaging={}),
            _make_dna("ad_3", element_scores=[], messaging={}),
            _make_dna("ad_4", element_scores=[], messaging={}),
        ]
        # hook_type:curiosity is 2/4 = 50% which is >= COMMON_ELEMENT_THRESHOLD,
        # so it wouldn't be notable by freq anyway. But also verify the common_elements
        # exclusion by putting it in common_elements and making freq exactly at boundary.
        # Actually, 2/4 = 0.5 which is NOT < 0.5, so it would be excluded by freq check.
        # Use 3 dnas to get exactly within range for a cleaner test:
        dnas_3 = [
            _make_dna("ad_1", element_scores=[
                {"element": "hook_type", "value": "curiosity"},
            ], messaging={}),
            _make_dna("ad_2", element_scores=[], messaging={}),
            _make_dna("ad_3", element_scores=[], messaging={}),
        ]
        # hook_type:curiosity is 1/3 = 0.333 -> in 25-49% range -> would be notable
        common_elements = {
            "hook_type:curiosity": {"element": "hook_type", "value": "curiosity", "frequency": 0.75},
        }
        notable = analyzer._find_notable_elements(dnas_3, common_elements)
        assert "hook_type:curiosity" not in notable


# ============================================================================
# _find_notable_visual_traits tests
# ============================================================================

class TestFindNotableVisualTraits:
    def test_finds_sub_threshold_traits(self, analyzer):
        """Visual traits at 25-49% frequency are returned."""
        dnas = [
            _make_dna("ad_1", visual_properties={"contrast_level": "high", "text_density": "low"}),
            _make_dna("ad_2", visual_properties={"contrast_level": "medium", "text_density": "high"}),
            _make_dna("ad_3", visual_properties={"contrast_level": "medium", "text_density": "high"}),
            _make_dna("ad_4", visual_properties={"contrast_level": "low", "text_density": "high"}),
        ]
        # contrast_level:high = 1/4 = 25% -> notable
        # contrast_level:medium = 2/4 = 50% -> NOT notable (>= threshold)
        # text_density:low = 1/4 = 25% -> notable
        # text_density:high = 3/4 = 75% -> NOT notable (>= threshold)
        common_visuals = {}
        notable = analyzer._find_notable_visual_traits(dnas, common_visuals)
        # At least one of the 25% traits should appear
        # Note: _find_notable_visual_traits uses field name as key (not field:value)
        # and only keeps one value per field (last seen in iteration)
        # From the code: notable[fld] = {...} so each field only has one entry
        found_values = {v["value"] for v in notable.values()}
        # "high" contrast or "low" text_density should be present
        assert "high" in found_values or "low" in found_values

    def test_excludes_common_visuals(self, analyzer):
        """Traits already in common_visual_traits are excluded."""
        dnas = [
            _make_dna("ad_1", visual_properties={"contrast_level": "high"}),
            _make_dna("ad_2", visual_properties={"contrast_level": "medium"}),
            _make_dna("ad_3", visual_properties={"contrast_level": "medium"}),
            _make_dna("ad_4", visual_properties={"contrast_level": "high"}),
        ]
        # contrast_level:high = 2/4 = 50% -> at threshold, excluded by freq
        # contrast_level:medium = 2/4 = 50% -> at threshold, excluded by freq
        # Now set up where a trait IS in range but also in common_visuals
        dnas_notable = [
            _make_dna("ad_1", visual_properties={"contrast_level": "high"}),
            _make_dna("ad_2", visual_properties={"contrast_level": "medium"}),
            _make_dna("ad_3", visual_properties={"contrast_level": "medium"}),
        ]
        # contrast_level:high = 1/3 = 0.33 -> in range, would be notable
        # But contrast_level is in common_visuals -> excluded
        common_visuals = {
            "contrast_level": {"value": "medium", "frequency": 0.67},
        }
        notable = analyzer._find_notable_visual_traits(dnas_notable, common_visuals)
        assert "contrast_level" not in notable


# ============================================================================
# _collect_winner_thumbnails tests
# ============================================================================

class TestCollectWinnerThumbnails:
    def test_collects_thumbnails_for_matching_ads(self, analyzer):
        """Only includes ads whose meta_ad_id matches a WinnerDNA."""
        winner_ads = [
            {"meta_ad_id": "ad_1", "thumbnail_url": "http://img1.png", "roas": 3.0, "ad_name": "Ad One"},
            {"meta_ad_id": "ad_2", "thumbnail_url": "http://img2.png", "roas": 2.5, "ad_name": "Ad Two"},
            {"meta_ad_id": "ad_3", "thumbnail_url": "http://img3.png", "roas": 1.0, "ad_name": "Ad Three"},
        ]
        winner_dnas = [
            _make_dna("ad_1"),
            _make_dna("ad_2"),
        ]
        thumbnails = analyzer._collect_winner_thumbnails(winner_ads, winner_dnas)
        ids = [t["meta_ad_id"] for t in thumbnails]
        assert "ad_1" in ids
        assert "ad_2" in ids
        assert "ad_3" not in ids

    def test_returns_correct_fields(self, analyzer):
        """Each item has meta_ad_id, thumbnail_url, roas, ad_name."""
        winner_ads = [
            {"meta_ad_id": "ad_1", "thumbnail_url": "http://img1.png", "roas": 4.2, "ad_name": "Winner Ad"},
        ]
        winner_dnas = [_make_dna("ad_1")]
        thumbnails = analyzer._collect_winner_thumbnails(winner_ads, winner_dnas)
        assert len(thumbnails) == 1
        thumb = thumbnails[0]
        assert thumb["meta_ad_id"] == "ad_1"
        assert thumb["thumbnail_url"] == "http://img1.png"
        assert thumb["roas"] == 4.2
        assert thumb["ad_name"] == "Winner Ad"


# ============================================================================
# _compute_cohort_summary tests
# ============================================================================

class TestComputeCohortSummary:
    def test_computes_averages_and_ranges(self, analyzer):
        """avg_roas, roas_range, avg_ctr, ctr_range, total_spend computed correctly."""
        dna1 = WinnerDNA(
            meta_ad_id="ad_1",
            metrics={"roas": 4.0, "ctr": 2.0, "cpa": 10.0, "spend": 100.0},
            element_scores=[], top_elements=[], weak_elements=[],
            visual_properties=None, messaging={}, cohort_comparison={},
            active_synergies=[], active_conflicts=[],
        )
        dna2 = WinnerDNA(
            meta_ad_id="ad_2",
            metrics={"roas": 6.0, "ctr": 4.0, "cpa": 20.0, "spend": 200.0},
            element_scores=[], top_elements=[], weak_elements=[],
            visual_properties=None, messaging={}, cohort_comparison={},
            active_synergies=[], active_conflicts=[],
        )
        summary = analyzer._compute_cohort_summary([dna1, dna2])
        assert summary["avg_roas"] == 5.0       # (4+6)/2
        assert summary["roas_range"] == [4.0, 6.0]
        assert summary["avg_ctr"] == 3.0         # (2+4)/2
        assert summary["ctr_range"] == [2.0, 4.0]
        assert summary["total_spend"] == 300.0    # 100+200

    def test_handles_empty_metrics(self, analyzer):
        """Doesn't crash on WinnerDNA with empty/zero metrics."""
        dna_empty = WinnerDNA(
            meta_ad_id="ad_empty",
            metrics={},
            element_scores=[], top_elements=[], weak_elements=[],
            visual_properties=None, messaging={}, cohort_comparison={},
            active_synergies=[], active_conflicts=[],
        )
        dna_zero = WinnerDNA(
            meta_ad_id="ad_zero",
            metrics={"roas": 0, "ctr": 0, "cpa": 0, "spend": 0},
            element_scores=[], top_elements=[], weak_elements=[],
            visual_properties=None, messaging={}, cohort_comparison={},
            active_synergies=[], active_conflicts=[],
        )
        summary = analyzer._compute_cohort_summary([dna_empty, dna_zero])
        # Should not crash, return safe defaults
        assert summary["avg_roas"] == 0
        assert summary["roas_range"] == [0, 0]
        assert summary["avg_ctr"] == 0
        assert summary["ctr_range"] == [0, 0]
        assert summary["total_spend"] == 0
