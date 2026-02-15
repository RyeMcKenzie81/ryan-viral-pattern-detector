"""
Tests for CongruenceService and HeadlineCongruenceNode (Phase 4).

Tests:
- CongruenceService: with/without offer variant, LP data, belief data
- CongruenceResult: score computation, adapted headline logic
- HeadlineCongruenceNode: pass-through without offer_variant_id, adapted hooks
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from viraltracker.pipelines.ad_creation_v2.services.congruence_service import (
    CongruenceService,
    CongruenceResult,
    CONGRUENCE_THRESHOLD,
)


# ============================================================================
# CongruenceResult dataclass
# ============================================================================

class TestCongruenceResult:
    """CongruenceResult holds per-dimension scores and optional adapted headline."""

    def test_default_values(self):
        r = CongruenceResult(headline="Test")
        assert r.headline == "Test"
        assert r.overall_score == 1.0
        assert r.offer_alignment is None
        assert r.hero_alignment is None
        assert r.belief_alignment is None
        assert r.adapted_headline is None
        assert r.dimensions_scored == 0

    def test_all_dimensions(self):
        r = CongruenceResult(
            headline="Test",
            offer_alignment=0.8,
            hero_alignment=0.7,
            belief_alignment=0.9,
            overall_score=0.8,
            dimensions_scored=3,
        )
        assert r.dimensions_scored == 3
        assert r.overall_score == 0.8

    def test_adapted_headline(self):
        r = CongruenceResult(
            headline="Bad headline",
            overall_score=0.3,
            adapted_headline="Better headline",
            dimensions_scored=1,
        )
        assert r.adapted_headline == "Better headline"


# ============================================================================
# CongruenceService — check_congruence
# ============================================================================

class TestCongruenceServiceCheckCongruence:
    """CongruenceService.check_congruence() single-headline scoring."""

    def setup_method(self):
        self.service = CongruenceService()

    @pytest.mark.asyncio
    async def test_no_context_returns_neutral(self):
        """No offer/LP/belief data → pass-through with score 1.0."""
        result = await self.service.check_congruence("Buy now!")
        assert result.overall_score == 1.0
        assert result.dimensions_scored == 0
        assert result.adapted_headline is None

    @pytest.mark.asyncio
    async def test_with_offer_variant_only(self):
        """With offer variant data, calls LLM and returns scores."""
        mock_scores = {
            "offer_alignment": 0.85,
            "adapted_headline": None,
        }
        with patch.object(self.service, "_score_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_scores
            result = await self.service.check_congruence(
                "Feel better today!",
                offer_variant_data={"pain_points": ["chronic pain"], "benefits": ["relief"]},
            )
            assert result.offer_alignment == 0.85
            assert result.overall_score == 0.85
            assert result.dimensions_scored == 1
            mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_all_context(self):
        """With all 3 dimensions, computes weighted average."""
        mock_scores = {
            "offer_alignment": 0.8,
            "hero_alignment": 0.6,
            "belief_alignment": 0.9,
            "adapted_headline": None,
        }
        with patch.object(self.service, "_score_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_scores
            result = await self.service.check_congruence(
                "Transform your life",
                offer_variant_data={"pain_points": ["stress"]},
                lp_hero_data={"hero_headline": "Stress Relief"},
                belief_data={"belief_statement": "Stress is manageable"},
            )
            expected = round((0.8 + 0.6 + 0.9) / 3, 3)
            assert result.overall_score == expected
            assert result.dimensions_scored == 3

    @pytest.mark.asyncio
    async def test_below_threshold_returns_adapted(self):
        """Score below threshold with adapted headline → sets adapted_headline."""
        mock_scores = {
            "offer_alignment": 0.3,
            "adapted_headline": "Better headline here",
        }
        with patch.object(self.service, "_score_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_scores
            result = await self.service.check_congruence(
                "Random headline",
                offer_variant_data={"pain_points": ["acne"]},
            )
            assert result.overall_score < CONGRUENCE_THRESHOLD
            assert result.adapted_headline == "Better headline here"

    @pytest.mark.asyncio
    async def test_above_threshold_no_adapted(self):
        """Score above threshold → no adapted headline even if LLM suggests one."""
        mock_scores = {
            "offer_alignment": 0.8,
            "adapted_headline": "Unnecessary suggestion",
        }
        with patch.object(self.service, "_score_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_scores
            result = await self.service.check_congruence(
                "Good headline",
                offer_variant_data={"pain_points": ["fatigue"]},
            )
            assert result.overall_score >= CONGRUENCE_THRESHOLD
            assert result.adapted_headline is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_neutral(self):
        """LLM failure → graceful fallback to neutral score."""
        with patch.object(self.service, "_score_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API timeout")
            result = await self.service.check_congruence(
                "Any headline",
                offer_variant_data={"pain_points": ["pain"]},
            )
            assert result.overall_score == 1.0
            assert result.dimensions_scored == 0


# ============================================================================
# CongruenceService — check_congruence_batch
# ============================================================================

class TestCongruenceServiceBatch:
    """CongruenceService.check_congruence_batch() multi-headline scoring."""

    def setup_method(self):
        self.service = CongruenceService()

    @pytest.mark.asyncio
    async def test_empty_hooks(self):
        result = await self.service.check_congruence_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_context_returns_neutral_batch(self):
        """No context → all neutral."""
        hooks = [{"hook_text": "Hook 1"}, {"hook_text": "Hook 2"}]
        results = await self.service.check_congruence_batch(hooks)
        assert len(results) == 2
        assert all(r.overall_score == 1.0 for r in results)
        assert all(r.dimensions_scored == 0 for r in results)

    @pytest.mark.asyncio
    async def test_batch_with_context(self):
        """Batch call with offer variant returns per-hook scores."""
        hooks = [{"hook_text": "Hook A"}, {"hook_text": "Hook B"}]
        batch_results = [
            CongruenceResult(headline="Hook A", offer_alignment=0.9, overall_score=0.9, dimensions_scored=1),
            CongruenceResult(headline="Hook B", offer_alignment=0.4, overall_score=0.4,
                             adapted_headline="Better B", dimensions_scored=1),
        ]
        with patch.object(self.service, "_score_batch_with_llm", new_callable=AsyncMock) as mock:
            mock.return_value = batch_results
            results = await self.service.check_congruence_batch(
                hooks,
                offer_variant_data={"pain_points": ["issue"]},
            )
            assert len(results) == 2
            assert results[0].overall_score == 0.9
            assert results[1].adapted_headline == "Better B"

    @pytest.mark.asyncio
    async def test_batch_llm_failure(self):
        """LLM failure → neutral for all hooks."""
        hooks = [{"hook_text": "Hook 1"}, {"hook_text": "Hook 2"}]
        with patch.object(self.service, "_score_batch_with_llm", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Batch failure")
            results = await self.service.check_congruence_batch(
                hooks,
                offer_variant_data={"pain_points": ["issue"]},
            )
            assert len(results) == 2
            assert all(r.overall_score == 1.0 for r in results)


# ============================================================================
# CongruenceService — prompt building
# ============================================================================

class TestCongruencePromptBuilding:
    """Test prompt construction for congruence scoring."""

    def setup_method(self):
        self.service = CongruenceService()

    def test_build_prompt_offer_only(self):
        prompt = self.service._build_prompt(
            ["Test headline"],
            offer_variant_data={"pain_points": ["back pain"], "benefits": ["relief"]},
            lp_hero_data=None,
            belief_data=None,
        )
        assert "OFFER VARIANT" in prompt
        assert "back pain" in prompt
        assert "offer_alignment" in prompt
        assert "LANDING PAGE HERO" not in prompt
        assert "BELIEF/ANGLE" not in prompt

    def test_build_prompt_all_context(self):
        prompt = self.service._build_prompt(
            ["Headline 1", "Headline 2"],
            offer_variant_data={"pain_points": ["stress"]},
            lp_hero_data={"hero_headline": "Stress-Free Living"},
            belief_data={"belief_statement": "Everyone deserves peace"},
        )
        assert "OFFER VARIANT" in prompt
        assert "LANDING PAGE HERO" in prompt
        assert "BELIEF/ANGLE" in prompt
        assert "offer_alignment" in prompt
        assert "hero_alignment" in prompt
        assert "belief_alignment" in prompt
        assert "Headline 1" in prompt
        assert "Headline 2" in prompt


# ============================================================================
# CongruenceService — parsing
# ============================================================================

class TestCongruenceParsing:
    """Test JSON response parsing."""

    def setup_method(self):
        self.service = CongruenceService()

    def test_parse_single_result_valid(self):
        raw = '[{"offer_alignment": 0.8, "adapted_headline": null}]'
        result = self.service._parse_single_result(raw)
        assert result["offer_alignment"] == 0.8
        assert result["adapted_headline"] is None

    def test_parse_single_result_dict(self):
        raw = '{"offer_alignment": 0.7}'
        result = self.service._parse_single_result(raw)
        assert result["offer_alignment"] == 0.7

    def test_parse_single_result_markdown_fences(self):
        raw = '```json\n[{"offer_alignment": 0.9}]\n```'
        result = self.service._parse_single_result(raw)
        assert result["offer_alignment"] == 0.9

    def test_parse_single_result_invalid_json(self):
        raw = "Not valid JSON at all"
        result = self.service._parse_single_result(raw)
        assert result == {}

    def test_parse_batch_result_valid(self):
        raw = '[{"offer_alignment": 0.8}, {"offer_alignment": 0.5, "adapted_headline": "Better"}]'
        results = self.service._parse_batch_result(raw, ["H1", "H2"])
        assert len(results) == 2
        assert results[0].offer_alignment == 0.8
        assert results[1].offer_alignment == 0.5
        assert results[1].adapted_headline == "Better"

    def test_parse_batch_result_fewer_results_than_headlines(self):
        raw = '[{"offer_alignment": 0.8}]'
        results = self.service._parse_batch_result(raw, ["H1", "H2"])
        assert len(results) == 2
        # First has score, second gets empty dict → no dimensions scored
        assert results[0].offer_alignment == 0.8
        assert results[1].dimensions_scored == 0

    def test_parse_batch_result_invalid_json(self):
        results = self.service._parse_batch_result("not json", ["H1"])
        assert len(results) == 1
        assert results[0].overall_score == 1.0

    def test_safe_float_valid(self):
        assert CongruenceService._safe_float(0.5) == 0.5
        assert CongruenceService._safe_float("0.7") == 0.7

    def test_safe_float_clamp(self):
        assert CongruenceService._safe_float(1.5) == 1.0
        assert CongruenceService._safe_float(-0.3) == 0.0

    def test_safe_float_none(self):
        assert CongruenceService._safe_float(None) is None

    def test_safe_float_invalid(self):
        assert CongruenceService._safe_float("abc") is None


# ============================================================================
# HeadlineCongruenceNode
# ============================================================================

class TestHeadlineCongruenceNode:
    """HeadlineCongruenceNode: pass-through, adapted hooks, error handling."""

    @pytest.mark.asyncio
    async def test_pass_through_no_offer_variant(self):
        """No offer_variant_id → pass-through, all hooks score 1.0."""
        from viraltracker.pipelines.ad_creation_v2.nodes.headline_congruence import HeadlineCongruenceNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            offer_variant_id=None,
            selected_hooks=[
                {"hook_text": "Hook 1"},
                {"hook_text": "Hook 2"},
            ],
        )

        # Mock context
        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()

        node = HeadlineCongruenceNode()
        next_node = await node.run(ctx)

        # Should return SelectImagesNode
        from viraltracker.pipelines.ad_creation_v2.nodes.select_images import SelectImagesNode
        assert isinstance(next_node, SelectImagesNode)

        # All congruence results should be pass-through
        assert len(state.congruence_results) == 2
        assert all(r["overall_score"] == 1.0 for r in state.congruence_results)
        assert all(r["skipped"] is True for r in state.congruence_results)

    @pytest.mark.asyncio
    async def test_hooks_adapted_below_threshold(self):
        """Hooks below threshold get adapted headlines replaced."""
        from viraltracker.pipelines.ad_creation_v2.nodes.headline_congruence import HeadlineCongruenceNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            offer_variant_id="variant-1",
            selected_hooks=[
                {"hook_text": "Bad hook"},
                {"hook_text": "Good hook"},
            ],
            product_dict={"offer_variant": {"pain_points": ["acne"]}},
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()

        batch_results = [
            CongruenceResult(
                headline="Bad hook", offer_alignment=0.3, overall_score=0.3,
                adapted_headline="Adapted hook", dimensions_scored=1
            ),
            CongruenceResult(
                headline="Good hook", offer_alignment=0.9, overall_score=0.9,
                dimensions_scored=1
            ),
        ]

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.congruence_service.CongruenceService.check_congruence_batch",
            new_callable=AsyncMock,
            return_value=batch_results,
        ):
            node = HeadlineCongruenceNode()
            next_node = await node.run(ctx)

        from viraltracker.pipelines.ad_creation_v2.nodes.select_images import SelectImagesNode
        assert isinstance(next_node, SelectImagesNode)

        # First hook should be adapted
        assert state.selected_hooks[0]["hook_text"] == "Adapted hook"
        assert state.selected_hooks[0]["original_hook_text"] == "Bad hook"
        assert state.selected_hooks[0]["congruence_adapted"] is True

        # Second hook unchanged
        assert state.selected_hooks[1]["hook_text"] == "Good hook"
        assert "congruence_adapted" not in state.selected_hooks[1]

    @pytest.mark.asyncio
    async def test_error_fallback_passes_through(self):
        """Service error → non-fatal pass-through."""
        from viraltracker.pipelines.ad_creation_v2.nodes.headline_congruence import HeadlineCongruenceNode
        from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState

        state = AdCreationPipelineState(
            product_id="prod-1",
            reference_ad_base64="base64data",
            offer_variant_id="variant-1",
            selected_hooks=[{"hook_text": "Hook 1"}],
            product_dict={"offer_variant": {"pain_points": ["pain"]}},
        )

        ctx = MagicMock()
        ctx.state = state
        ctx.deps = MagicMock()

        with patch(
            "viraltracker.pipelines.ad_creation_v2.services.congruence_service.CongruenceService.check_congruence_batch",
            new_callable=AsyncMock,
            side_effect=Exception("LLM down"),
        ):
            node = HeadlineCongruenceNode()
            next_node = await node.run(ctx)

        from viraltracker.pipelines.ad_creation_v2.nodes.select_images import SelectImagesNode
        assert isinstance(next_node, SelectImagesNode)

        # Should have fallback congruence results
        assert len(state.congruence_results) == 1
        assert state.congruence_results[0]["overall_score"] == 1.0
        assert "error" in state.congruence_results[0]
