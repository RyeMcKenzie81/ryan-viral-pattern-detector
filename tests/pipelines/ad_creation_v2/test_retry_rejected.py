"""
Tests for RetryRejectedNode — Phase 5 refactor to staged review.

Tests: skip when disabled, skip when no rejected, defect scan → reject,
staged review → approve/reject/flagged, generation failure, review failure,
congruence lookup, reviewed_ads dict shape, index incrementing, hook passthrough.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState
from viraltracker.pipelines.ad_creation_v2.nodes.retry_rejected import RetryRejectedNode


# Patch paths — services are imported inside run() via deferred imports
# so we patch at the source module level
PATCH_GEN_SERVICE = "viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService"
PATCH_REVIEW_SERVICE = "viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService"
PATCH_DEFECT_SERVICE = "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService"
PATCH_LOAD_CONFIG = "viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config"


def _make_state(**overrides):
    """Create a minimal state for RetryRejectedNode."""
    defaults = {
        "product_id": "prod-1",
        "reference_ad_base64": "base64data",
        "ad_run_id": "00000000-0000-0000-0000-000000000010",
        "product_dict": {"name": "TestProduct"},
        "ad_analysis": {"format_type": "testimonial"},
        "content_source": "hooks",
        "auto_retry_rejected": True,
        "max_retry_attempts": 1,
        "selected_images": [
            {"storage_path": "images/img1.png", "asset_tags": ["product"]},
        ],
        "congruence_results": [],
        "reviewed_ads": [],
        "ad_brief_instructions": "Make a great ad",
        "reference_ad_path": "ads/ref.png",
        "brand_colors": None,
        "brand_fonts": None,
        "prompt_version": "v2.1.0",
    }
    defaults.update(overrides)
    return AdCreationPipelineState(**defaults)


def _make_ctx(state):
    """Create a mock GraphRunContext."""
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = MagicMock()
    ctx.deps.ad_creation = MagicMock()
    ctx.deps.ad_creation.get_product_id_for_run = AsyncMock(return_value="prod-1")
    ctx.deps.ad_creation.upload_generated_ad = AsyncMock(
        return_value=("ads/retry_1.png", "signed_url")
    )
    ctx.deps.ad_creation.save_generated_ad = AsyncMock()
    ctx.deps.gemini = MagicMock()
    return ctx


def _rejected_ad(prompt_index=1, hook_text="Buy Now",
                 hook_id="00000000-0000-0000-0000-000000000001",
                 ad_uuid="00000000-0000-0000-0000-000000000099", **extra):
    """Build a rejected ad dict matching ReviewAdsNode output."""
    entry = {
        "prompt_index": prompt_index,
        "prompt": {
            "full_prompt": "generate ad",
            "json_prompt": {},
            "hook": {
                "adapted_text": hook_text,
                "hook_id": hook_id,
                "name": "test_hook",
            },
        },
        "storage_path": f"ads/ad_{prompt_index}.png",
        "final_status": "rejected",
        "ad_uuid": ad_uuid,
        "canvas_size": "1080x1080px",
        "color_mode": "original",
        "review_check_scores": {"V1": 4.0},
        "weighted_score": 4.0,
    }
    entry.update(extra)
    return entry


# Mock objects reused across tests
def _mock_defect_passed():
    m = MagicMock()
    m.passed = True
    m.defects = []
    m.to_dict.return_value = {"passed": True, "defects": [], "model": "gemini-2.0-flash", "latency_ms": 50}
    return m


def _mock_defect_failed():
    m = MagicMock()
    m.passed = False
    m.defects = [MagicMock(type="TEXT_GARBLED")]
    m.to_dict.return_value = {
        "passed": False,
        "defects": [{"type": "TEXT_GARBLED", "description": "Garbled text"}],
        "model": "gemini-2.0-flash", "latency_ms": 50,
    }
    return m


MOCK_STAGED_APPROVED = {
    "review_check_scores": {"V1": 8.0, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0,
                            "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5,
                            "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0,
                            "G1": 7.0, "G2": 8.0},
    "weighted_score": 8.12,
    "final_status": "approved",
    "stage2_result": {"scores": {}, "weighted": 8.12},
    "stage3_result": None,
}

MOCK_STAGED_REJECTED = {
    "review_check_scores": {"V1": 3.0, "V2": 4.0, "V3": 3.5},
    "weighted_score": 3.5,
    "final_status": "rejected",
    "stage2_result": {"scores": {}, "weighted": 3.5},
    "stage3_result": None,
}

MOCK_STAGED_FLAGGED = {
    "review_check_scores": {"V1": 6.0, "V2": 6.5, "V3": 5.5},
    "weighted_score": 6.0,
    "final_status": "flagged",
    "stage2_result": {"scores": {}, "weighted": 5.8},
    "stage3_result": {"scores": {}, "weighted": 6.0},
}

MOCK_GENERATED_AD = {
    "image_base64": "aW1hZ2VkYXRh",  # "imagedata" in base64
    "model_requested": "gemini",
    "model_used": "gemini",
    "generation_time_ms": 120,
    "generation_retries": 0,
}

MOCK_PROMPT = {
    "full_prompt": "generate ad",
    "json_prompt": {},
    "hook": {"adapted_text": "Buy Now", "hook_id": "00000000-0000-0000-0000-000000000001"},
}


def _setup_mocks(mock_gen_cls, mock_defect_cls, mock_review_cls, mock_config,
                 defect_result=None, review_result=None, gen_error=None, review_error=None):
    """Configure mock services for retry tests."""
    gen_svc = mock_gen_cls.return_value
    gen_svc.generate_prompt.return_value = MOCK_PROMPT
    if gen_error:
        gen_svc.execute_generation = AsyncMock(side_effect=gen_error)
    else:
        gen_svc.execute_generation = AsyncMock(return_value=MOCK_GENERATED_AD)

    defect_svc = mock_defect_cls.return_value
    defect_svc.scan_for_defects = AsyncMock(return_value=defect_result or _mock_defect_passed())
    defect_svc.scan_for_offer_hallucination = AsyncMock(return_value=_mock_defect_passed())

    review_svc = mock_review_cls.return_value
    if review_error:
        review_svc.review_ad_staged = AsyncMock(side_effect=review_error)
    else:
        review_svc.review_ad_staged = AsyncMock(return_value=review_result or MOCK_STAGED_APPROVED)

    mock_config.return_value = None

    return gen_svc, defect_svc, review_svc


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.asyncio
async def test_skip_when_disabled():
    """auto_retry_rejected=False → pass through."""
    state = _make_state(auto_retry_rejected=False, reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    result = await node.run(ctx)
    assert result.__class__.__name__ == "CompileResultsNode"
    assert len(ctx.state.reviewed_ads) == 1  # Unchanged


@pytest.mark.asyncio
async def test_skip_when_no_rejected():
    """No rejected ads → pass through."""
    approved_ad = _rejected_ad()
    approved_ad["final_status"] = "approved"
    state = _make_state(reviewed_ads=[approved_ad])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    result = await node.run(ctx)
    assert result.__class__.__name__ == "CompileResultsNode"
    assert len(ctx.state.reviewed_ads) == 1


@pytest.mark.asyncio
async def test_retry_defect_rejected():
    """Defect scan finds defects → saved as rejected with defect_scan_result."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     defect_result=_mock_defect_failed())

        result = await node.run(ctx)

    assert result.__class__.__name__ == "CompileResultsNode"
    assert len(ctx.state.reviewed_ads) == 2  # original + retry
    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["final_status"] == "rejected"
    assert retry_ad["defect_rejected"] is True
    assert retry_ad["defect_scan_result"]["passed"] is False
    assert retry_ad["is_retry"] is True

    # Verify save was called with defect_scan_result
    save_call = ctx.deps.ad_creation.save_generated_ad
    assert save_call.await_count == 1
    call_kwargs = save_call.call_args.kwargs
    assert call_kwargs["final_status"] == "rejected"
    assert call_kwargs["defect_scan_result"]["passed"] is False


@pytest.mark.asyncio
async def test_retry_review_approved():
    """Staged review approves → saved with review_check_scores."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     review_result=MOCK_STAGED_APPROVED)

        result = await node.run(ctx)

    assert result.__class__.__name__ == "CompileResultsNode"
    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["final_status"] == "approved"
    assert retry_ad["review_check_scores"] == MOCK_STAGED_APPROVED["review_check_scores"]
    assert retry_ad["weighted_score"] == 8.12
    assert retry_ad["is_retry"] is True

    # Verify save with structured scores
    call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
    assert call_kwargs["review_check_scores"] == MOCK_STAGED_APPROVED["review_check_scores"]
    assert call_kwargs["defect_scan_result"]["passed"] is True


@pytest.mark.asyncio
async def test_retry_review_rejected():
    """Staged review rejects → final_status=rejected."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     review_result=MOCK_STAGED_REJECTED)

        await node.run(ctx)

    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["final_status"] == "rejected"
    assert retry_ad["weighted_score"] == 3.5


@pytest.mark.asyncio
async def test_retry_review_flagged():
    """Borderline → Stage 3 triggered, final_status=flagged."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     review_result=MOCK_STAGED_FLAGGED)

        await node.run(ctx)

    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["final_status"] == "flagged"


@pytest.mark.asyncio
async def test_retry_generation_failure():
    """execute_generation raises → logged, skipped, no crash."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     gen_error=Exception("API error"))

        result = await node.run(ctx)

    assert result.__class__.__name__ == "CompileResultsNode"
    # Original rejected ad still there, no retry appended
    assert len(ctx.state.reviewed_ads) == 1


@pytest.mark.asyncio
async def test_retry_review_failure():
    """review_ad_staged raises → final_status=review_failed."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig,
                     review_error=Exception("Review API down"))

        await node.run(ctx)

    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["final_status"] == "review_failed"
    assert retry_ad["review_check_scores"] is None


@pytest.mark.asyncio
async def test_retry_congruence_lookup():
    """congruence_score looked up from state.congruence_results."""
    state = _make_state(
        reviewed_ads=[_rejected_ad(hook_text="Buy Now", hook_list_index=0)],
        congruence_results=[{"hook_index": 0, "headline": "Buy Now", "overall_score": 0.85}],
    )
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    retry_ad = ctx.state.reviewed_ads[1]
    assert retry_ad["congruence_score"] == 0.85

    # Also verify it was passed to save
    call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
    assert call_kwargs["congruence_score"] == 0.85


@pytest.mark.asyncio
async def test_retry_appends_correct_shape():
    """New dict shape matches ReviewAdsNode output keys."""
    state = _make_state(reviewed_ads=[_rejected_ad()])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    retry_ad = ctx.state.reviewed_ads[1]
    # Keys present in ReviewAdsNode output
    assert "prompt_index" in retry_ad
    assert "prompt" in retry_ad
    assert "storage_path" in retry_ad
    assert "review_check_scores" in retry_ad
    assert "final_status" in retry_ad
    assert "ad_uuid" in retry_ad
    assert "canvas_size" in retry_ad
    assert "color_mode" in retry_ad
    assert "weighted_score" in retry_ad
    assert "congruence_score" in retry_ad
    # Retry-specific keys
    assert retry_ad["is_retry"] is True
    assert retry_ad["retry_of_index"] == 1


@pytest.mark.asyncio
async def test_retry_increments_index():
    """next_index increments correctly past existing max."""
    state = _make_state(reviewed_ads=[
        _rejected_ad(prompt_index=3),
        {**_rejected_ad(prompt_index=5), "final_status": "approved"},
    ])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    # Rejected was index 3, max was 5, so retry should be 6
    retry_ad = ctx.state.reviewed_ads[2]
    assert retry_ad["prompt_index"] == 6


@pytest.mark.asyncio
async def test_retry_hook_passthrough():
    """Hook data preserved from original rejected ad."""
    state = _make_state(reviewed_ads=[
        _rejected_ad(hook_text="Special Offer", hook_id="00000000-0000-0000-0000-000000000042"),
    ])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        gen_svc, _, _ = _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    # Verify generate_prompt was called with the hook data
    assert gen_svc.generate_prompt.call_count == 1
    call_kwargs = gen_svc.generate_prompt.call_args.kwargs
    assert call_kwargs["selected_hook"]["adapted_text"] == "Special Offer"
    assert call_kwargs["selected_hook"]["hook_id"] == "00000000-0000-0000-0000-000000000042"


@pytest.mark.asyncio
async def test_retry_no_hook_data_skipped():
    """Rejected ad with no hook data → skipped."""
    rejected = _rejected_ad()
    rejected["prompt"] = {"full_prompt": "generate", "json_prompt": {}}  # No "hook" key
    state = _make_state(reviewed_ads=[rejected])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        gen_svc, _, _ = _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        result = await node.run(ctx)

    assert result.__class__.__name__ == "CompileResultsNode"
    # No retry appended (hook data missing)
    assert len(ctx.state.reviewed_ads) == 1
    # Generation service should not have been called
    gen_svc.generate_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_retry_non_hooks_content_source():
    """content_source != 'hooks' → hook_id=None in save."""
    state = _make_state(
        content_source="recreate_template",
        reviewed_ads=[_rejected_ad()],
    )
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
    assert call_kwargs["hook_id"] is None


@pytest.mark.asyncio
async def test_retry_regenerate_parent_id():
    """Retried ad has regenerate_parent_id pointing to original ad UUID."""
    original_uuid = "00000000-0000-0000-0000-000000000099"
    state = _make_state(reviewed_ads=[_rejected_ad(ad_uuid=original_uuid)])
    ctx = _make_ctx(state)
    node = RetryRejectedNode()

    with patch(PATCH_GEN_SERVICE) as MockGen, \
         patch(PATCH_DEFECT_SERVICE) as MockDefect, \
         patch(PATCH_REVIEW_SERVICE) as MockReview, \
         patch(PATCH_LOAD_CONFIG, new_callable=AsyncMock) as MockConfig:

        _setup_mocks(MockGen, MockDefect, MockReview, MockConfig)

        await node.run(ctx)

    from uuid import UUID
    call_kwargs = ctx.deps.ad_creation.save_generated_ad.call_args.kwargs
    assert call_kwargs["regenerate_parent_id"] == UUID(original_uuid)
