"""
Tests for Phase 6 element tagging in GenerateAdsNode.

Verifies that element_tags and pre_gen_score are built correctly
and passed through the pipeline to save_generated_ad().
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState
from viraltracker.pipelines.ad_creation_v2.nodes.generate_ads import GenerateAdsNode


def _make_state(**overrides):
    """Create a minimal state with defaults for GenerateAdsNode."""
    defaults = {
        "product_id": "00000000-0000-0000-0000-000000000001",
        "reference_ad_base64": "img",
        "ad_run_id": "00000000-0000-0000-0000-000000000099",
        "reference_ad_path": "ads/ref.png",
        "product_dict": {
            "name": "TestProduct",
            "id": "p1",
            "brand_id": "00000000-0000-0000-0000-000000000002",
            "awareness_stage": 3,
        },
        "ad_analysis": {"format_type": "testimonial"},
        "ad_brief_instructions": "Be creative",
        "selected_images": [
            {"storage_path": "images/main.png"},
        ],
        "selected_hooks": [
            {"adapted_text": "Hook A", "id": "h1", "persuasion_type": "curiosity_gap"},
        ],
        "canvas_sizes": ["1080x1080px"],
        "color_modes": ["original"],
        "num_variations": 1,
        "prompt_version": "v2.1.0",
        "content_source": "hooks",
        "template_id": "00000000-0000-0000-0000-000000000005",
        "persona_id": "00000000-0000-0000-0000-000000000003",
    }
    defaults.update(overrides)
    return AdCreationPipelineState(**defaults)


def _make_ctx(state):
    """Create a mock GraphRunContext."""
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = MagicMock()
    ctx.deps.ad_creation = AsyncMock()
    ctx.deps.ad_creation.get_product_id_for_run = AsyncMock(
        return_value=UUID(state.product_id)
    )
    ctx.deps.ad_creation.upload_generated_ad = AsyncMock(
        return_value=("ads/gen.png", "url")
    )
    ctx.deps.gemini = MagicMock()
    return ctx


class TestElementTagsBuilt:
    """Verify element_tags dict is built and attached to generated ads."""

    @pytest.mark.asyncio
    async def test_element_tags_present_on_generated_ad(self):
        state = _make_state()
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {
                "prompt_index": 1, "full_prompt": "{}", "json_prompt": {},
                "prompt_version": "v2.1.0",
            }
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 1
        ad = state.generated_ads[0]
        assert "element_tags" in ad
        tags = ad["element_tags"]

        # Verify expected keys
        assert tags["hook_type"] == "curiosity_gap"
        assert tags["persona_id"] == "00000000-0000-0000-0000-000000000003"
        assert tags["color_mode"] == "original"
        assert tags["template_category"] == "testimonial"
        assert tags["awareness_stage"] == 3
        assert tags["canvas_size"] == "1080x1080px"
        assert tags["template_id"] == "00000000-0000-0000-0000-000000000005"
        assert tags["prompt_version"] == "v2.1.0"
        assert tags["content_source"] == "hooks"

    @pytest.mark.asyncio
    async def test_element_tags_with_no_persuasion_type_falls_back_to_category(self):
        state = _make_state(
            selected_hooks=[
                {"adapted_text": "Hook A", "id": "h1", "category": "pain_point"},
            ],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {
                "prompt_index": 1, "full_prompt": "{}", "json_prompt": {},
                "prompt_version": "v2.1.0",
            }
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        tags = state.generated_ads[0]["element_tags"]
        assert tags["hook_type"] == "pain_point"

    @pytest.mark.asyncio
    async def test_pre_gen_score_is_none_without_performance_context(self):
        state = _make_state()
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {
                "prompt_index": 1, "full_prompt": "{}", "json_prompt": {},
                "prompt_version": "v2.1.0",
            }
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        ad = state.generated_ads[0]
        assert ad["pre_gen_score"] is None


class TestMultiSizeColorElementTags:
    """Verify element_tags vary correctly across canvas sizes and color modes."""

    @pytest.mark.asyncio
    async def test_different_sizes_have_different_canvas_size_tag(self):
        state = _make_state(
            canvas_sizes=["1080x1080px", "1080x1350px"],
            color_modes=["original"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {
                "prompt_index": 1, "full_prompt": "{}", "json_prompt": {},
                "prompt_version": "v2.1.0",
            }
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 2
        assert state.generated_ads[0]["element_tags"]["canvas_size"] == "1080x1080px"
        assert state.generated_ads[1]["element_tags"]["canvas_size"] == "1080x1350px"

    @pytest.mark.asyncio
    async def test_different_colors_have_different_color_mode_tag(self):
        state = _make_state(
            canvas_sizes=["1080x1080px"],
            color_modes=["original", "complementary"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {
                "prompt_index": 1, "full_prompt": "{}", "json_prompt": {},
                "prompt_version": "v2.1.0",
            }
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 2
        assert state.generated_ads[0]["element_tags"]["color_mode"] == "original"
        assert state.generated_ads[1]["element_tags"]["color_mode"] == "complementary"


class TestPerformanceContextOnState:
    """Verify performance_context field on AdCreationPipelineState."""

    def test_default_is_none(self):
        state = _make_state()
        assert state.performance_context is None

    def test_can_be_set(self):
        state = _make_state(performance_context={
            "cold_start_level": 2,
            "total_matured_ads": 50,
        })
        assert state.performance_context["cold_start_level"] == 2
