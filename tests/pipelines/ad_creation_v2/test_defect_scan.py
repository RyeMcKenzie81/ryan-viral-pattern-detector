"""
Tests for DefectScanService and DefectScanNode (Phase 4 — Stage 1).

Tests:
- DefectScanService: parsing, prompt building, defect detection
- DefectScanNode: all pass, all fail, mixed, generation_failed pass-through
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.services.defect_scan_service import (
    DefectScanService,
    DefectScanResult,
    Defect,
    DEFECT_TYPES,
)


# ============================================================================
# DefectScanResult / Defect dataclasses
# ============================================================================

class TestDefectScanResult:
    def test_passed_result(self):
        r = DefectScanResult(passed=True, model="gemini-2.0-flash", latency_ms=150)
        d = r.to_dict()
        assert d["passed"] is True
        assert d["defects"] == []
        assert d["model"] == "gemini-2.0-flash"
        assert d["latency_ms"] == 150

    def test_failed_result_with_defects(self):
        r = DefectScanResult(
            passed=False,
            defects=[Defect(type="TEXT_GARBLED", description="Unreadable text on button")],
            model="gemini-2.0-flash",
            latency_ms=200,
        )
        d = r.to_dict()
        assert d["passed"] is False
        assert len(d["defects"]) == 1
        assert d["defects"][0]["type"] == "TEXT_GARBLED"
        assert d["defects"][0]["severity"] == "critical"

    def test_defect_to_dict(self):
        defect = Defect(type="ANATOMY_ERROR", description="Extra finger")
        d = defect.to_dict()
        assert d == {"type": "ANATOMY_ERROR", "description": "Extra finger", "severity": "critical"}


# ============================================================================
# DefectScanService — parsing
# ============================================================================

class TestDefectScanServiceParsing:
    def setup_method(self):
        self.service = DefectScanService()

    def test_parse_clean_result(self):
        raw = '{"passed": true, "defects": []}'
        result = self.service._parse_scan_result(raw, "gemini-2.0-flash", 100)
        assert result.passed is True
        assert result.defects == []

    def test_parse_defects_found(self):
        raw = '{"passed": false, "defects": [{"type": "TEXT_GARBLED", "description": "Garbled CTA"}]}'
        result = self.service._parse_scan_result(raw, "gemini-2.0-flash", 200)
        assert result.passed is False
        assert len(result.defects) == 1
        assert result.defects[0].type == "TEXT_GARBLED"

    def test_parse_multiple_defects(self):
        raw = '{"passed": false, "defects": [{"type": "TEXT_GARBLED", "description": "a"}, {"type": "ANATOMY_ERROR", "description": "b"}]}'
        result = self.service._parse_scan_result(raw, "model", 100)
        assert len(result.defects) == 2
        assert result.defects[0].type == "TEXT_GARBLED"
        assert result.defects[1].type == "ANATOMY_ERROR"

    def test_parse_unknown_defect_type(self):
        raw = '{"passed": false, "defects": [{"type": "WEIRD_THING", "description": "unknown"}]}'
        result = self.service._parse_scan_result(raw, "model", 100)
        assert result.defects[0].type == "UNKNOWN"

    def test_parse_markdown_fences(self):
        raw = '```json\n{"passed": true, "defects": []}\n```'
        result = self.service._parse_scan_result(raw, "model", 100)
        assert result.passed is True

    def test_parse_invalid_json_passes(self):
        result = self.service._parse_scan_result("not json", "model", 100)
        assert result.passed is True  # Fail-safe: treat as passed

    def test_parse_passed_true_but_defects_present(self):
        """If LLM says passed=true but lists defects, override to false."""
        raw = '{"passed": true, "defects": [{"type": "PHYSICS_VIOLATION", "description": "floating"}]}'
        result = self.service._parse_scan_result(raw, "model", 100)
        assert result.passed is False  # Overridden because defects present

    def test_defect_types_constant(self):
        assert len(DEFECT_TYPES) == 6
        assert "TEXT_GARBLED" in DEFECT_TYPES
        assert "ANATOMY_ERROR" in DEFECT_TYPES
        assert "PHYSICS_VIOLATION" in DEFECT_TYPES
        assert "PACKAGING_TEXT_ERROR" in DEFECT_TYPES
        assert "PRODUCT_DISTORTION" in DEFECT_TYPES
        assert "OFFER_HALLUCINATION" in DEFECT_TYPES


# ============================================================================
# DefectScanService — prompt building
# ============================================================================

class TestDefectScanPrompt:
    def test_prompt_includes_product_name(self):
        service = DefectScanService()
        prompt = service._build_scan_prompt("Super Serum")
        assert "Super Serum" in prompt
        assert "TEXT_GARBLED" in prompt
        assert "ANATOMY_ERROR" in prompt
        assert "PHYSICS_VIOLATION" in prompt
        assert "PACKAGING_TEXT_ERROR" in prompt
        assert "PRODUCT_DISTORTION" in prompt


# ============================================================================
# DefectScanNode
# ============================================================================

class TestDefectScanNode:

    @pytest.mark.asyncio
    async def test_all_ads_pass_defect_scan(self):
        """All ads pass → all go to defect_passed_ads, none rejected."""
        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
            generated_ads=[
                {"prompt_index": 1, "storage_path": "path/ad1.png", "hook": {"hook_id": "00000000-0000-0000-0000-000000000001", "adapted_text": "Hook 1"}, "prompt": {}, "generated_ad": {}},
                {"prompt_index": 2, "storage_path": "path/ad2.png", "hook": {"hook_id": "00000000-0000-0000-0000-000000000002", "adapted_text": "Hook 2"}, "prompt": {}, "generated_ad": {}},
            ],
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="base64img")
        ctx.deps.ad_creation.save_generated_ad = AsyncMock()

        passed_result = DefectScanResult(passed=True, model="gemini-2.0-flash", latency_ms=100)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService.scan_for_defects",
            new_callable=AsyncMock,
            return_value=passed_result,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService.scan_for_offer_hallucination",
            new_callable=AsyncMock,
            return_value=passed_result,
        ):
            node = DefectScanNode()
            next_node = await node.run(ctx)

        from viraltracker.pipelines.ad_creation_v2.nodes.review_ads import ReviewAdsNode
        assert isinstance(next_node, ReviewAdsNode)

        assert len(state.defect_passed_ads) == 2
        assert len(state.reviewed_ads) == 0  # No rejects
        assert len(state.defect_scan_results) == 2
        ctx.deps.ad_creation.save_generated_ad.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_ads_fail_defect_scan(self):
        """All ads have defects → all rejected, none in defect_passed_ads."""
        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
            content_source="hooks",
            generated_ads=[
                {"prompt_index": 1, "storage_path": "path/ad1.png", "hook": {"hook_id": "00000000-0000-0000-0000-000000000001", "adapted_text": "Hook 1"}, "prompt": {}, "generated_ad": {}, "ad_uuid": "00000000-0000-0000-0000-000000000099"},
            ],
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="base64img")
        ctx.deps.ad_creation.save_generated_ad = AsyncMock()

        failed_result = DefectScanResult(
            passed=False,
            defects=[Defect(type="TEXT_GARBLED", description="Garbled text")],
            model="gemini-2.0-flash",
            latency_ms=200,
        )

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService.scan_for_defects",
            new_callable=AsyncMock,
            return_value=failed_result,
        ):
            node = DefectScanNode()
            next_node = await node.run(ctx)

        assert len(state.defect_passed_ads) == 0
        assert len(state.reviewed_ads) == 1
        assert state.reviewed_ads[0]["final_status"] == "rejected"
        assert state.reviewed_ads[0]["defect_rejected"] is True
        ctx.deps.ad_creation.save_generated_ad.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_pass_and_fail(self):
        """Some pass, some fail → correct split."""
        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
            content_source="hooks",
            generated_ads=[
                {"prompt_index": 1, "storage_path": "path/ad1.png", "hook": {"hook_id": "00000000-0000-0000-0000-000000000001", "adapted_text": "Hook 1"}, "prompt": {}, "generated_ad": {}, "ad_uuid": "00000000-0000-0000-0000-000000000099"},
                {"prompt_index": 2, "storage_path": "path/ad2.png", "hook": {"hook_id": "00000000-0000-0000-0000-000000000002", "adapted_text": "Hook 2"}, "prompt": {}, "generated_ad": {}},
            ],
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="base64img")
        ctx.deps.ad_creation.save_generated_ad = AsyncMock()

        call_count = 0

        async def alternating_scan(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DefectScanResult(passed=False, defects=[Defect("TEXT_GARBLED", "bad")], model="m", latency_ms=100)
            return DefectScanResult(passed=True, model="m", latency_ms=100)

        offer_passed = DefectScanResult(passed=True, model="m", latency_ms=50)

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService.scan_for_defects",
            new_callable=AsyncMock,
            side_effect=alternating_scan,
        ), patch(
            "viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService.scan_for_offer_hallucination",
            new_callable=AsyncMock,
            return_value=offer_passed,
        ):
            node = DefectScanNode()
            await node.run(ctx)

        assert len(state.defect_passed_ads) == 1
        assert len(state.reviewed_ads) == 1
        assert state.reviewed_ads[0]["defect_rejected"] is True

    @pytest.mark.asyncio
    async def test_generation_failed_passes_through(self):
        """Generation-failed ads go straight to reviewed_ads, not scanned."""
        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            ad_run_id="00000000-0000-0000-0000-000000000010",
            product_dict={"name": "TestProduct"},
            generated_ads=[
                {"prompt_index": 1, "final_status": "generation_failed", "error": "API timeout"},
            ],
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()

        node = DefectScanNode()
        await node.run(ctx)

        assert len(state.defect_passed_ads) == 0
        assert len(state.reviewed_ads) == 1
        assert state.reviewed_ads[0]["final_status"] == "generation_failed"
        assert len(state.defect_scan_results) == 0  # Not scanned
