"""
Tests for AdCreationPipelineState — Phase 2 compat properties and serialization.
"""

import pytest

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState


class TestCanvasSizeCompatProperty:
    """canvas_size property returns first element of canvas_sizes list."""

    def test_default_canvas_size(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img"
        )
        assert state.canvas_size == "1080x1080px"

    def test_single_size(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            canvas_sizes=["1080x1350px"],
        )
        assert state.canvas_size == "1080x1350px"

    def test_multi_size_returns_first(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            canvas_sizes=["1200x628px", "1080x1080px", "1080x1920px"],
        )
        assert state.canvas_size == "1200x628px"

    def test_empty_list_fallback(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            canvas_sizes=[],
        )
        assert state.canvas_size == "1080x1080px"


class TestColorModeCompatProperty:
    """color_mode property returns first element of color_modes list."""

    def test_default_color_mode(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img"
        )
        assert state.color_mode == "original"

    def test_single_mode(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            color_modes=["brand"],
        )
        assert state.color_mode == "brand"

    def test_multi_mode_returns_first(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            color_modes=["complementary", "brand", "original"],
        )
        assert state.color_mode == "complementary"

    def test_empty_list_fallback(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            color_modes=[],
        )
        assert state.color_mode == "original"


class TestStateSerialization:
    """to_dict() / from_dict() round-trip preserves state."""

    def test_round_trip_required_fields(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img"
        )
        data = state.to_dict()
        restored = AdCreationPipelineState.from_dict(data)
        assert restored.product_id == "p1"
        assert restored.reference_ad_base64 == "img"

    def test_round_trip_phase2_fields(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            canvas_sizes=["1080x1350px", "1080x1920px"],
            color_modes=["brand", "original"],
            num_variations=3,
            template_id="tmpl-123",
        )
        data = state.to_dict()
        restored = AdCreationPipelineState.from_dict(data)
        assert restored.canvas_sizes == ["1080x1350px", "1080x1920px"]
        assert restored.color_modes == ["brand", "original"]
        assert restored.num_variations == 3
        assert restored.template_id == "tmpl-123"

    def test_from_dict_ignores_extra_keys(self):
        data = {
            "product_id": "p1",
            "reference_ad_base64": "img",
            "unknown_future_field": "should_be_ignored",
        }
        state = AdCreationPipelineState.from_dict(data)
        assert state.product_id == "p1"
        assert not hasattr(state, "unknown_future_field")

    def test_round_trip_populated_by_nodes(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
        )
        state.ad_run_id = "run-456"
        state.generated_ads = [{"prompt_index": 1}]
        state.current_step = "generate_ads_complete"

        data = state.to_dict()
        restored = AdCreationPipelineState.from_dict(data)
        assert restored.ad_run_id == "run-456"
        assert restored.generated_ads == [{"prompt_index": 1}]
        assert restored.current_step == "generate_ads_complete"

    def test_to_dict_contains_all_fields(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img"
        )
        data = state.to_dict()
        # Verify key fields are present
        assert "product_id" in data
        assert "canvas_sizes" in data
        assert "color_modes" in data
        assert "num_variations" in data
        assert "pipeline_version" in data
        assert data["pipeline_version"] == "v2"
