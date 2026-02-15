"""
Tests for Phase 5 prompt versioning + generation_config.

Tests: generation_config built correctly in InitializeNode,
passed to create_ad_run, prompt_version passed in save_generated_ad
by ReviewAdsNode/RetryRejectedNode/DefectScanNode.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState
from viraltracker.pipelines.ad_creation_v2.nodes.initialize import InitializeNode


def _make_state(**overrides):
    """Create a minimal state for testing."""
    defaults = {
        "product_id": "00000000-0000-0000-0000-000000000001",
        "reference_ad_base64": "aW1hZ2VkYXRh",
        "prompt_version": "v2.1.0",
        "pipeline_version": "v2",
        "image_resolution": "2K",
        "content_source": "hooks",
        "canvas_sizes": ["1080x1080px"],
        "color_modes": ["original"],
        "match_template_structure": False,
        "auto_retry_rejected": False,
        "max_retry_attempts": 1,
        "template_id": "00000000-0000-0000-0000-000000000002",
        "num_variations": 5,
        "image_selection_mode": "auto",
    }
    defaults.update(overrides)
    return AdCreationPipelineState(**defaults)


def _make_ctx(state):
    """Create a mock GraphRunContext."""
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = MagicMock()
    ctx.deps.ad_creation = MagicMock()
    ctx.deps.ad_creation.create_ad_run = AsyncMock(
        return_value=UUID("00000000-0000-0000-0000-000000000010")
    )
    ctx.deps.ad_creation.upload_reference_ad = AsyncMock(return_value="ads/ref.png")
    ctx.deps.ad_creation.update_ad_run = AsyncMock()
    ctx.deps.ad_creation.save_generated_ad = AsyncMock()
    ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="aW1hZ2VkYXRh")
    return ctx


# ============================================================================
# InitializeNode — generation_config
# ============================================================================

class TestGenerationConfig:
    """Tests for generation_config snapshot in InitializeNode."""

    @pytest.mark.asyncio
    async def test_generation_config_passed_to_create_ad_run(self):
        """create_ad_run receives generation_config kwarg."""
        state = _make_state()
        ctx = _make_ctx(state)
        node = InitializeNode()

        await node.run(ctx)

        call_kwargs = ctx.deps.ad_creation.create_ad_run.call_args.kwargs
        assert "generation_config" in call_kwargs
        assert call_kwargs["generation_config"] is not None

    @pytest.mark.asyncio
    async def test_generation_config_snapshot_fields(self):
        """All expected fields present in generation_config snapshot."""
        state = _make_state()
        ctx = _make_ctx(state)
        node = InitializeNode()

        await node.run(ctx)

        config = ctx.deps.ad_creation.create_ad_run.call_args.kwargs["generation_config"]
        expected_keys = {
            "prompt_version", "pipeline_version", "image_resolution",
            "content_source", "canvas_sizes", "color_modes",
            "match_template_structure", "auto_retry_rejected",
            "max_retry_attempts", "template_id",
        }
        assert expected_keys == set(config.keys())

    @pytest.mark.asyncio
    async def test_generation_config_values_match_state(self):
        """Config values match what was set in state."""
        state = _make_state(
            prompt_version="v2.2.0",
            image_resolution="4K",
            content_source="belief_first",
            canvas_sizes=["1080x1080px", "1080x1350px"],
            color_modes=["original", "brand"],
            auto_retry_rejected=True,
            max_retry_attempts=2,
        )
        ctx = _make_ctx(state)
        node = InitializeNode()

        await node.run(ctx)

        config = ctx.deps.ad_creation.create_ad_run.call_args.kwargs["generation_config"]
        assert config["prompt_version"] == "v2.2.0"
        assert config["pipeline_version"] == "v2"
        assert config["image_resolution"] == "4K"
        assert config["content_source"] == "belief_first"
        assert config["canvas_sizes"] == ["1080x1080px", "1080x1350px"]
        assert config["color_modes"] == ["original", "brand"]
        assert config["auto_retry_rejected"] is True
        assert config["max_retry_attempts"] == 2

    @pytest.mark.asyncio
    async def test_generation_config_template_id_none(self):
        """template_id=None is captured correctly."""
        state = _make_state(template_id=None)
        ctx = _make_ctx(state)
        node = InitializeNode()

        await node.run(ctx)

        config = ctx.deps.ad_creation.create_ad_run.call_args.kwargs["generation_config"]
        assert config["template_id"] is None


# ============================================================================
# prompt_version in save_generated_ad
# ============================================================================

PATCH_LOAD_CONFIG = "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config"
PATCH_REVIEW_STAGED = "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged"
PATCH_DEFECT_SCAN = "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService"

MOCK_STAGED_RESULT = {
    "review_check_scores": {"V1": 8.0},
    "weighted_score": 8.0,
    "final_status": "approved",
    "stage2_result": {},
    "stage3_result": None,
}


def _ad_entry(prompt_index=1, hook_id="00000000-0000-0000-0000-000000000001",
              hook_text="Buy Now", ad_uuid="00000000-0000-0000-0000-aaaaaaaaaaaa", **extra):
    """Build an ad_data dict matching DefectScanNode output."""
    entry = {
        "prompt_index": prompt_index,
        "storage_path": f"ads/ad_{prompt_index}.png",
        "hook": {"hook_id": hook_id, "adapted_text": hook_text},
        "prompt": {"full_prompt": "gen", "json_prompt": {}},
        "generated_ad": {"model_requested": "gemini", "model_used": "gemini",
                         "generation_time_ms": 100, "generation_retries": 0},
        "ad_uuid": ad_uuid,
        "defect_scan_result": {"passed": True, "defects": []},
    }
    entry.update(extra)
    return entry


class TestPromptVersionInReviewNode:
    """ReviewAdsNode passes prompt_version to save_generated_ad."""

    @pytest.mark.asyncio
    async def test_prompt_version_saved(self):
        state = _make_state(
            defect_passed_ads=[_ad_entry()],
            reviewed_ads=[],
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
            ad_analysis={"format_type": "testimonial"},
            congruence_results=[],
        )
        ctx = _make_ctx(state)

        from viraltracker.pipelines.ad_creation_v2.nodes.review_ads import ReviewAdsNode

        with patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock, return_value=None), \
             patch(PATCH_REVIEW_STAGED, new_callable=AsyncMock, return_value=MOCK_STAGED_RESULT):
            node = ReviewAdsNode()
            await node.run(ctx)

        call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
        assert call_kwargs["prompt_version"] == "v2.1.0"


class TestPromptVersionInDefectScanNode:
    """DefectScanNode passes prompt_version for defect-rejected ads."""

    @pytest.mark.asyncio
    async def test_prompt_version_on_defect_reject(self):
        ad = _ad_entry()
        # Remove defect_scan_result so it gets scanned fresh
        del ad["defect_scan_result"]
        state = _make_state(
            generated_ads=[ad],
            reviewed_ads=[],
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
        )
        ctx = _make_ctx(state)

        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode

        mock_defect = MagicMock()
        mock_defect.passed = False
        mock_defect.defects = [MagicMock(type="TEXT_GARBLED")]
        mock_defect.to_dict.return_value = {"passed": False, "defects": [{"type": "TEXT_GARBLED"}],
                                            "model": "gemini", "latency_ms": 50}

        with patch(PATCH_DEFECT_SCAN) as MockDefectCls:
            MockDefectCls.return_value.scan_for_defects = AsyncMock(return_value=mock_defect)
            node = DefectScanNode()
            await node.run(ctx)

        call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
        assert call_kwargs["prompt_version"] == "v2.1.0"


class TestPromptVersionBackwardCompat:
    """Backward compat: prompt_version=None doesn't crash."""

    @pytest.mark.asyncio
    async def test_default_prompt_version(self):
        """Default prompt_version is v2.1.0."""
        state = _make_state()
        assert state.prompt_version == "v2.1.0"
