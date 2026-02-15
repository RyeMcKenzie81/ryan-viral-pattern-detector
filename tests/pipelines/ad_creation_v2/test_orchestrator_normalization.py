"""
Tests for run_ad_creation_v2 orchestrator — Phase 2 normalization logic.

Tests scalar→list normalization, defaults, list-takes-priority,
and num_variations validation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2


class TestCanvasSizeNormalization:
    """canvas_sizes list normalization from scalar or list inputs."""

    @pytest.mark.asyncio
    async def test_scalar_canvas_size_wrapped_in_list(self):
        """Scalar canvas_size is wrapped into a list."""
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                canvas_size="1080x1350px",
                deps=MagicMock(),
            )

            # Inspect the state passed to graph.run
            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.canvas_sizes == ["1080x1350px"]

    @pytest.mark.asyncio
    async def test_list_canvas_sizes_takes_priority(self):
        """canvas_sizes list takes priority over scalar canvas_size."""
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                canvas_sizes=["1080x1920px", "1200x628px"],
                canvas_size="1080x1080px",  # should be ignored
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.canvas_sizes == ["1080x1920px", "1200x628px"]

    @pytest.mark.asyncio
    async def test_default_canvas_size(self):
        """When neither canvas_size nor canvas_sizes provided, defaults to 1080x1080px."""
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.canvas_sizes == ["1080x1080px"]


class TestColorModeNormalization:
    """color_modes list normalization from scalar or list inputs."""

    @pytest.mark.asyncio
    async def test_scalar_color_mode_wrapped_in_list(self):
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                color_mode="brand",
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.color_modes == ["brand"]

    @pytest.mark.asyncio
    async def test_list_color_modes_takes_priority(self):
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                color_modes=["brand", "complementary"],
                color_mode="original",  # should be ignored
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.color_modes == ["brand", "complementary"]

    @pytest.mark.asyncio
    async def test_default_color_mode(self):
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.color_modes == ["original"]


class TestNumVariationsValidation:
    """num_variations validation in orchestrator."""

    @pytest.mark.asyncio
    async def test_valid_num_variations(self):
        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph"
        ) as mock_graph:
            mock_graph.run = AsyncMock(return_value=MagicMock(output={"ok": True}))

            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                num_variations=10,
                deps=MagicMock(),
            )

            call_kwargs = mock_graph.run.call_args
            state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state")
            assert state.num_variations == 10

    @pytest.mark.asyncio
    async def test_zero_num_variations_raises(self):
        with pytest.raises(ValueError, match="num_variations must be between 1 and 50"):
            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                num_variations=0,
                deps=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_negative_num_variations_raises(self):
        with pytest.raises(ValueError, match="num_variations must be between 1 and 50"):
            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                num_variations=-1,
                deps=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_over_50_num_variations_raises(self):
        with pytest.raises(ValueError, match="num_variations must be between 1 and 50"):
            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                num_variations=51,
                deps=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_invalid_content_source_raises(self):
        with pytest.raises(ValueError, match="content_source must be one of"):
            await run_ad_creation_v2(
                product_id="p1",
                reference_ad_base64="img",
                content_source="invalid_source",
                deps=MagicMock(),
            )
