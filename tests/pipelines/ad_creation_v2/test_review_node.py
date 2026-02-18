"""
Tests for ReviewAdsNode — Phase 4 staged review integration.

Tests: defect_passed_ads input, staged review delegation, structured score
persistence, generation_failed passthrough, congruence lookup, save_generated_ad
params, append-to-reviewed_ads behavior.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState
from viraltracker.pipelines.ad_creation_v2.nodes.review_ads import ReviewAdsNode


def _make_state(**overrides):
    """Create a minimal state for ReviewAdsNode."""
    defaults = {
        "product_id": "prod-1",
        "reference_ad_base64": "base64data",
        "ad_run_id": "00000000-0000-0000-0000-000000000010",
        "product_dict": {"name": "TestProduct"},
        "ad_analysis": {"format_type": "testimonial"},
        "content_source": "hooks",
        "congruence_results": [],
        "defect_passed_ads": [],
        "generated_ads": [],
        "reviewed_ads": [],
    }
    defaults.update(overrides)
    return AdCreationPipelineState(**defaults)


def _make_ctx(state):
    """Create a mock GraphRunContext."""
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = MagicMock()
    ctx.deps.ad_creation = MagicMock()
    ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="aW1hZ2VkYXRh")
    ctx.deps.ad_creation.save_generated_ad = AsyncMock()
    return ctx


def _ad_entry(prompt_index=1, hook_id="00000000-0000-0000-0000-000000000001",
              hook_text="Buy Now", ad_uuid=None, **extra):
    """Build an ad_data dict matching GenerateAdsNode / DefectScanNode output."""
    entry = {
        "prompt_index": prompt_index,
        "storage_path": f"ads/ad_{prompt_index}.png",
        "hook": {
            "hook_id": hook_id,
            "adapted_text": hook_text,
        },
        "prompt": {"full_prompt": "generate ad", "json_prompt": {}},
        "generated_ad": {
            "model_requested": "gemini",
            "model_used": "gemini",
            "generation_time_ms": 120,
            "generation_retries": 0,
        },
    }
    if ad_uuid:
        entry["ad_uuid"] = ad_uuid
    entry.update(extra)
    return entry


MOCK_STAGED_RESULT = {
    "review_check_scores": {"V1": 8.0, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0,
                            "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5,
                            "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0,
                            "G1": 7.0, "G2": 8.0},
    "weighted_score": 8.12,
    "final_status": "approved",
    "stage2_result": {"scores": {}, "weighted": 8.12},
    "stage3_result": None,
}


# ============================================================================
# ReviewAdsNode — reads from defect_passed_ads
# ============================================================================

class TestReviewAdsNodeDefectPassedInput:
    """ReviewAdsNode reads defect_passed_ads (not generated_ads)."""

    @pytest.mark.asyncio
    async def test_uses_defect_passed_ads(self):
        """When defect_passed_ads is populated, those are reviewed."""
        state = _make_state(
            defect_passed_ads=[_ad_entry(1), _ad_entry(2)],
            generated_ads=[_ad_entry(1), _ad_entry(2), _ad_entry(3)],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            next_node = await node.run(ctx)

        from viraltracker.pipelines.ad_creation_v2.nodes.retry_rejected import RetryRejectedNode
        assert isinstance(next_node, RetryRejectedNode)
        # Should review 2 ads (from defect_passed), not 3 (from generated_ads)
        assert state.ads_reviewed == 2
        assert len(state.reviewed_ads) == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_generated_ads(self):
        """When defect_passed_ads is empty, falls back to generated_ads."""
        state = _make_state(
            defect_passed_ads=[],
            generated_ads=[_ad_entry(1)],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.ads_reviewed == 1


# ============================================================================
# Staged review delegation
# ============================================================================

class TestStagedReviewDelegation:
    """ReviewAdsNode calls review_ad_staged() with correct args."""

    @pytest.mark.asyncio
    async def test_calls_review_ad_staged(self):
        state = _make_state(
            defect_passed_ads=[_ad_entry(1, hook_text="Amazing Product")],
        )
        ctx = _make_ctx(state)

        mock_staged = AsyncMock(return_value=MOCK_STAGED_RESULT)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            mock_staged,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        mock_staged.assert_called_once()
        call_kwargs = mock_staged.call_args[1]
        assert call_kwargs["product_name"] == "TestProduct"
        assert call_kwargs["hook_text"] == "Amazing Product"
        assert call_kwargs["ad_analysis"] == {"format_type": "testimonial"}

    @pytest.mark.asyncio
    async def test_approved_status_from_staged(self):
        state = _make_state(
            defect_passed_ads=[_ad_entry(1)],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.reviewed_ads[0]["final_status"] == "approved"
        assert state.reviewed_ads[0]["weighted_score"] == 8.12
        assert state.reviewed_ads[0]["review_check_scores"] is not None


# ============================================================================
# Generation-failed passthrough
# ============================================================================

class TestGenerationFailedPassthrough:

    @pytest.mark.asyncio
    async def test_generation_failed_skipped(self):
        """Generation-failed ads are appended without review."""
        state = _make_state(
            defect_passed_ads=[
                {"prompt_index": 1, "final_status": "generation_failed", "error": "API timeout"},
            ],
        )
        ctx = _make_ctx(state)

        mock_staged = AsyncMock(return_value=MOCK_STAGED_RESULT)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            mock_staged,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        mock_staged.assert_not_called()
        assert len(state.reviewed_ads) == 1
        assert state.reviewed_ads[0]["final_status"] == "generation_failed"
        assert state.reviewed_ads[0]["error"] == "API timeout"


# ============================================================================
# Error handling
# ============================================================================

class TestReviewErrorHandling:

    @pytest.mark.asyncio
    async def test_image_load_failure_marks_review_failed(self):
        """If image can't be loaded, status is review_failed."""
        state = _make_state(
            defect_passed_ads=[_ad_entry(1)],
        )
        ctx = _make_ctx(state)
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(side_effect=Exception("Storage error"))

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.reviewed_ads[0]["final_status"] == "review_failed"

    @pytest.mark.asyncio
    async def test_staged_review_exception_marks_review_failed(self):
        """If review_ad_staged raises, status is review_failed."""
        state = _make_state(
            defect_passed_ads=[_ad_entry(1)],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            side_effect=Exception("Claude Vision timeout"),
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.reviewed_ads[0]["final_status"] == "review_failed"


# ============================================================================
# Congruence score lookup
# ============================================================================

class TestCongruenceLookup:

    @pytest.mark.asyncio
    async def test_congruence_score_from_state(self):
        """Congruence score is looked up from state.congruence_results."""
        state = _make_state(
            defect_passed_ads=[_ad_entry(1, hook_text="Buy Now", hook_list_index=0)],
            congruence_results=[
                {"hook_index": 0, "headline": "Buy Now", "overall_score": 0.85},
                {"hook_index": 1, "headline": "Other Hook", "overall_score": 0.5},
            ],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.reviewed_ads[0]["congruence_score"] == 0.85

    @pytest.mark.asyncio
    async def test_congruence_none_when_no_match(self):
        """Congruence score is None when no matching hook_index."""
        state = _make_state(
            defect_passed_ads=[_ad_entry(1, hook_text="Unique Hook", hook_list_index=0)],
            congruence_results=[
                {"hook_index": 5, "headline": "Different Hook", "overall_score": 0.9},
            ],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.reviewed_ads[0]["congruence_score"] is None


# ============================================================================
# save_generated_ad Phase 4 params
# ============================================================================

class TestSaveGeneratedAdParams:

    @pytest.mark.asyncio
    async def test_passes_structured_scores_to_save(self):
        """save_generated_ad receives review_check_scores, congruence_score, defect_scan_result."""
        state = _make_state(
            defect_passed_ads=[
                _ad_entry(1, hook_text="Buy Now", hook_list_index=0,
                          defect_scan_result={"passed": True, "defects": []}),
            ],
            congruence_results=[
                {"hook_index": 0, "headline": "Buy Now", "overall_score": 0.9},
            ],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        ctx.deps.ad_creation.save_generated_ad.assert_called_once()
        call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args[1]
        assert call_kwargs["review_check_scores"] == MOCK_STAGED_RESULT["review_check_scores"]
        assert call_kwargs["congruence_score"] == 0.9
        assert call_kwargs["defect_scan_result"] == {"passed": True, "defects": []}


# ============================================================================
# Append-to-reviewed_ads behavior
# ============================================================================

class TestAppendBehavior:

    @pytest.mark.asyncio
    async def test_extends_existing_reviewed_ads(self):
        """ReviewAdsNode appends to existing reviewed_ads (from DefectScanNode)."""
        existing_rejected = {
            "prompt_index": 0,
            "final_status": "rejected",
            "defect_rejected": True,
        }
        state = _make_state(
            defect_passed_ads=[_ad_entry(1)],
            reviewed_ads=[existing_rejected],
        )
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        # 1 existing + 1 new
        assert len(state.reviewed_ads) == 2
        assert state.reviewed_ads[0]["defect_rejected"] is True
        assert state.reviewed_ads[1]["final_status"] == "approved"

    @pytest.mark.asyncio
    async def test_marks_step_complete(self):
        state = _make_state(defect_passed_ads=[_ad_entry(1)])
        ctx = _make_ctx(state)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService.review_ad_staged",
            new_callable=AsyncMock,
            return_value=MOCK_STAGED_RESULT,
        ):
            node = ReviewAdsNode()
            await node.run(ctx)

        assert state.current_step == "review_ads_complete"
