"""
Tests for AssetContext construction in generation_service._build_asset_context.

Covers happy path and all failure modes from the P3-C3 plan.
"""

import pytest

from viraltracker.pipelines.ad_creation_v2.services.generation_service import AdGenerationService


def _svc():
    return AdGenerationService()


class TestAssetContextHappyPath:
    """AssetContext built correctly from template elements + brand info + selected tags."""

    def test_full_match(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": ["product:bottle", "logo"],
                "optional_assets": ["person:vet"],
                "text_areas": [
                    {"type": "headline", "position": "top", "max_chars": 40},
                    {"type": "cta", "position": "bottom", "max_chars": 20},
                ],
                "logo_areas": [{"position": "top-right"}],
            },
            brand_asset_info={"has_logo": True, "logo_path": "logos/brand.png", "has_badge": False},
            selected_image_tags=["product:bottle", "logo", "person:vet"],
        )

        assert ctx.template_requires_logo is True
        assert ctx.brand_has_logo is True
        assert ctx.logo_placement == "top-right"
        assert ctx.template_requires_person is True
        assert ctx.available_person_tags == ["person:vet"]
        assert ctx.asset_match_score == 1.0
        assert "product:bottle" in ctx.matched_assets
        assert "logo" in ctx.matched_assets
        assert ctx.missing_assets == []
        assert len(ctx.template_text_areas) == 2
        assert ctx.template_text_areas[0].type == "headline"
        assert ctx.template_text_areas[0].max_chars == 40

    def test_partial_match(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": ["product:bottle", "person:model"],
                "optional_assets": [],
            },
            brand_asset_info=None,
            selected_image_tags=["product:bottle"],
        )

        assert ctx.asset_match_score == 0.5
        assert "product:bottle" in ctx.matched_assets
        assert "person:model" in ctx.missing_assets


class TestNoRequiredAssets:
    """Empty required_assets means score = 1.0."""

    def test_empty_required_assets(self):
        ctx = _svc()._build_asset_context(
            template_elements={"required_assets": [], "optional_assets": []},
            brand_asset_info=None,
            selected_image_tags=[],
        )
        assert ctx.asset_match_score == 1.0
        assert ctx.matched_assets == []
        assert ctx.missing_assets == []


class TestDetectionRanButEmpty:
    """template_elements == {} means detection ran but found nothing."""

    def test_empty_dict_elements(self):
        ctx = _svc()._build_asset_context(
            template_elements={},
            brand_asset_info=None,
            selected_image_tags=[],
        )
        assert ctx.asset_match_score == 1.0
        assert ctx.template_requires_logo is False
        assert ctx.template_requires_person is False
        assert ctx.template_text_areas == []
        assert ctx.asset_instructions == ""


class TestLogoGap:
    """Logo in requirements but brand has no logo."""

    def test_logo_gap_instruction(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": [],
                "optional_assets": ["logo"],
                "logo_areas": [{"position": "bottom-left"}],
            },
            brand_asset_info={"has_logo": False, "has_badge": False},
            selected_image_tags=[],
        )

        assert ctx.template_requires_logo is True
        assert ctx.brand_has_logo is False
        assert "logo area" in ctx.asset_instructions.lower()
        assert "brand name text" in ctx.asset_instructions.lower()

    def test_logo_gap_resolved_by_brand(self):
        """Brand has logo → no gap instruction."""
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": [],
                "optional_assets": ["logo"],
                "logo_areas": [{"position": "top-left"}],
            },
            brand_asset_info={"has_logo": True, "logo_path": "logo.png", "has_badge": False},
            selected_image_tags=[],
        )

        assert ctx.template_requires_logo is True
        assert ctx.brand_has_logo is True
        # No logo gap instruction
        assert "logo area" not in ctx.asset_instructions.lower()


class TestPersonGap:
    """Person in optional_assets but no person images selected."""

    def test_person_gap_instruction(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": [],
                "optional_assets": ["person:model"],
            },
            brand_asset_info=None,
            selected_image_tags=["product:bottle"],
        )

        assert ctx.template_requires_person is True
        assert "product-focused composition" in ctx.asset_instructions.lower()

    def test_person_gap_resolved_by_selected(self):
        """Person in selected images → no gap."""
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": [],
                "optional_assets": ["person:model"],
            },
            brand_asset_info=None,
            selected_image_tags=["product:bottle", "person:doctor"],
        )

        assert ctx.template_requires_person is True
        assert "product-focused" not in ctx.asset_instructions.lower()
        assert ctx.available_person_tags == ["person:doctor"]


class TestTextAreaCharLimits:
    """Char limits from text_areas appear in instructions."""

    def test_char_limit_in_instructions(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "text_areas": [
                    {"type": "headline", "max_chars": 35},
                ],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )

        assert "~35 characters" in ctx.asset_instructions
        assert "headline" in ctx.asset_instructions.lower()

    def test_no_char_limit_no_instruction(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "text_areas": [
                    {"type": "headline"},  # no max_chars
                ],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )

        assert "characters" not in ctx.asset_instructions


class TestSelectedImageTagsEmpty:
    """Empty selected_image_tags → all required assets missing."""

    def test_all_missing(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": ["product:bottle", "person:model"],
                "optional_assets": [],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )

        assert ctx.asset_match_score == 0.0
        assert len(ctx.missing_assets) == 2


class TestMissingRequiredAssetInstruction:
    """Missing required assets generate specific instructions."""

    def test_missing_asset_instruction(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": ["product:bottle"],
                "optional_assets": [],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )

        assert "product:bottle" in ctx.asset_instructions
        assert "not in the selected images" in ctx.asset_instructions


class TestBrandAssetInfoNone:
    """brand_asset_info is None → defaults to no logo/badge."""

    def test_none_brand_info(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "required_assets": [],
                "optional_assets": ["logo"],
                "logo_areas": [{}],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )

        assert ctx.brand_has_logo is False
        assert ctx.brand_has_badge is False


class TestMalformedTextAreas:
    """Malformed text_areas are handled gracefully."""

    def test_non_list_text_areas(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "text_areas": "not a list",
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )
        assert ctx.template_text_areas == []

    def test_non_dict_text_area_entry(self):
        ctx = _svc()._build_asset_context(
            template_elements={
                "text_areas": ["not_a_dict", {"type": "cta"}],
            },
            brand_asset_info=None,
            selected_image_tags=[],
        )
        # Only the valid dict entry should be parsed
        assert len(ctx.template_text_areas) == 1
        assert ctx.template_text_areas[0].type == "cta"
