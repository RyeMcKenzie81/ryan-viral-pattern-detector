"""
Tests for GenerateAdsNode — Phase 2 triple-loop variant generation.

Tests the triple-nested loop (hooks × sizes × colors), per-ad metadata,
and variant counter logic. All services are mocked — no DB or API calls.
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
        "product_dict": {"name": "TestProduct", "id": "p1"},
        "ad_analysis": {"format_type": "testimonial"},
        "ad_brief_instructions": "Be creative",
        "selected_images": [
            {"storage_path": "images/main.png"},
        ],
        "selected_hooks": [
            {"adapted_text": "Hook A", "id": "h1"},
            {"adapted_text": "Hook B", "id": "h2"},
        ],
        "canvas_sizes": ["1080x1080px"],
        "color_modes": ["original"],
        "num_variations": 2,
        "prompt_version": "v2.1.0",
    }
    defaults.update(overrides)
    return AdCreationPipelineState(**defaults)


def _make_ctx(state):
    """Create a mock GraphRunContext with the given state."""
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


class TestTripleLoopVariantCount:
    """Triple loop generates hooks × sizes × colors variants."""

    @pytest.mark.asyncio
    async def test_single_hook_single_size_single_color(self):
        state = _make_state(
            selected_hooks=[{"adapted_text": "H1", "id": "h1"}],
            canvas_sizes=["1080x1080px"],
            color_modes=["original"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 1
        assert state.ads_generated == 1

    @pytest.mark.asyncio
    async def test_2_hooks_2_sizes_2_colors(self):
        """2 hooks × 2 sizes × 2 colors = 8 variants."""
        state = _make_state(
            selected_hooks=[
                {"adapted_text": "H1", "id": "h1"},
                {"adapted_text": "H2", "id": "h2"},
            ],
            canvas_sizes=["1080x1080px", "1080x1350px"],
            color_modes=["original", "brand"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 8
        assert state.ads_generated == 8

    @pytest.mark.asyncio
    async def test_3_hooks_3_sizes_1_color(self):
        """3 hooks × 3 sizes × 1 color = 9 variants."""
        state = _make_state(
            selected_hooks=[
                {"adapted_text": f"H{i}", "id": f"h{i}"} for i in range(3)
            ],
            canvas_sizes=["1080x1080px", "1080x1350px", "1080x1920px"],
            color_modes=["original"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 9
        assert state.ads_generated == 9


class TestPerAdMetadata:
    """Each generated ad dict tracks canvas_size and color_mode."""

    @pytest.mark.asyncio
    async def test_metadata_per_variant(self):
        state = _make_state(
            selected_hooks=[{"adapted_text": "H1", "id": "h1"}],
            canvas_sizes=["1080x1080px", "1080x1350px"],
            color_modes=["original", "brand"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        # 1 hook × 2 sizes × 2 colors = 4
        assert len(state.generated_ads) == 4

        combos = [(ad["canvas_size"], ad["color_mode"]) for ad in state.generated_ads]
        assert ("1080x1080px", "original") in combos
        assert ("1080x1080px", "brand") in combos
        assert ("1080x1350px", "original") in combos
        assert ("1080x1350px", "brand") in combos


class TestVariantCounter:
    """variant_counter increments correctly across the triple loop."""

    @pytest.mark.asyncio
    async def test_prompt_indices_sequential(self):
        state = _make_state(
            selected_hooks=[
                {"adapted_text": "H1", "id": "h1"},
                {"adapted_text": "H2", "id": "h2"},
            ],
            canvas_sizes=["1080x1080px"],
            color_modes=["original", "brand"],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = AsyncMock(return_value={
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            })

            node = GenerateAdsNode()
            await node.run(ctx)

        indices = [ad["prompt_index"] for ad in state.generated_ads]
        assert indices == [1, 2, 3, 4]


class TestGenerationFailureResilience:
    """Failed generation for one variant doesn't stop others."""

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        state = _make_state(
            selected_hooks=[
                {"adapted_text": "H1", "id": "h1"},
                {"adapted_text": "H2", "id": "h2"},
            ],
            canvas_sizes=["1080x1080px"],
            color_modes=["original"],
        )
        ctx = _make_ctx(state)

        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Gemini API error")
            return {
                "image_base64": "abc", "model_requested": "gemini",
                "model_used": "gemini", "generation_time_ms": 100,
            }

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
        ) as MockGenSvc:
            svc = MockGenSvc.return_value
            svc.generate_prompt.return_value = {"prompt_index": 1, "full_prompt": "{}"}
            svc.execute_generation = _mock_execute

            node = GenerateAdsNode()
            await node.run(ctx)

        assert len(state.generated_ads) == 2  # both appended
        assert state.ads_generated == 1  # only 1 succeeded

        failed = [ad for ad in state.generated_ads if ad.get("final_status") == "generation_failed"]
        succeeded = [ad for ad in state.generated_ads if ad.get("storage_path") is not None]
        assert len(failed) == 1
        assert len(succeeded) == 1
