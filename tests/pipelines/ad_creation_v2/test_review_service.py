"""
Tests for Phase 4 staged review: 15-check rubric, weighted scoring,
Stage 3 conditional trigger, config loading, and parsing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.services.review_service import (
    AdReviewService,
    RUBRIC_CHECKS,
    DEFAULT_QUALITY_CONFIG,
    compute_weighted_score,
    apply_staged_review_logic,
    load_quality_config,
    _parse_rubric_scores,
    _build_rubric_prompt,
)


# ============================================================================
# Constants
# ============================================================================

class TestRubricConstants:
    def test_rubric_checks_count(self):
        assert len(RUBRIC_CHECKS) == 16

    def test_rubric_visual_checks(self):
        for i in range(1, 10):
            assert f"V{i}" in RUBRIC_CHECKS

    def test_rubric_content_checks(self):
        for i in range(1, 6):
            assert f"C{i}" in RUBRIC_CHECKS

    def test_rubric_congruence_checks(self):
        assert "G1" in RUBRIC_CHECKS
        assert "G2" in RUBRIC_CHECKS

    def test_default_config_has_all_weights(self):
        weights = DEFAULT_QUALITY_CONFIG["check_weights"]
        for check in RUBRIC_CHECKS:
            assert check in weights
            assert weights[check] > 0


# ============================================================================
# _parse_rubric_scores
# ============================================================================

class TestParseRubricScores:
    def test_valid_json(self):
        raw = '{"V1": 8.5, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0, "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5, "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0, "G1": 7.0, "G2": 8.0}'
        scores = _parse_rubric_scores(raw)
        assert scores["V1"] == 8.5
        assert scores["V9"] == 9.5
        assert scores["G2"] == 8.0

    def test_clamps_high_values(self):
        raw = '{"V1": 15.0, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0, "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5, "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0, "G1": 7.0, "G2": 8.0}'
        scores = _parse_rubric_scores(raw)
        assert scores["V1"] == 10.0

    def test_clamps_negative_values(self):
        raw = '{"V1": -5.0, "V2": 9.0, "V3": 7.5, "V4": 8.0, "V5": 7.0, "V6": 8.5, "V7": 9.0, "V8": 7.5, "V9": 9.5, "C1": 8.0, "C2": 7.5, "C3": 8.5, "C4": 8.0, "G1": 7.0, "G2": 8.0}'
        scores = _parse_rubric_scores(raw)
        assert scores["V1"] == 0.0

    def test_missing_checks_default_to_5(self):
        raw = '{"V1": 8.0}'
        scores = _parse_rubric_scores(raw)
        assert scores["V1"] == 8.0
        assert scores["V2"] == 5.0  # Missing → default
        assert scores["G2"] == 5.0

    def test_invalid_json_defaults_all(self):
        scores = _parse_rubric_scores("not json at all")
        assert len(scores) == 16
        assert all(s == 5.0 for s in scores.values())

    def test_markdown_fences(self):
        raw = '```json\n{"V1": 9.0, "V2": 8.0}\n```'
        scores = _parse_rubric_scores(raw)
        assert scores["V1"] == 9.0
        assert scores["V2"] == 8.0


# ============================================================================
# compute_weighted_score
# ============================================================================

class TestComputeWeightedScore:
    def test_all_perfect_scores(self):
        scores = {k: 10.0 for k in RUBRIC_CHECKS}
        weights = DEFAULT_QUALITY_CONFIG["check_weights"]
        result = compute_weighted_score(scores, weights)
        assert abs(result - 10.0) < 0.001

    def test_all_zero_scores(self):
        scores = {k: 0.0 for k in RUBRIC_CHECKS}
        weights = DEFAULT_QUALITY_CONFIG["check_weights"]
        result = compute_weighted_score(scores, weights)
        assert result == 0.0

    def test_all_neutral_scores(self):
        scores = {k: 5.0 for k in RUBRIC_CHECKS}
        weights = DEFAULT_QUALITY_CONFIG["check_weights"]
        result = compute_weighted_score(scores, weights)
        assert abs(result - 5.0) < 0.001

    def test_weighted_avg_correct(self):
        """V1=10 (w=1.5), V2=0 (w=1.5), all others=5 (various weights)."""
        scores = {k: 5.0 for k in RUBRIC_CHECKS}
        scores["V1"] = 10.0
        scores["V2"] = 0.0
        weights = DEFAULT_QUALITY_CONFIG["check_weights"]

        # Manually compute
        total_w = sum(weights.values())
        expected = (1.5 * 10.0 + 1.5 * 0.0 + sum(
            weights[k] * 5.0 for k in RUBRIC_CHECKS if k not in ("V1", "V2")
        )) / total_w

        result = compute_weighted_score(scores, weights)
        assert abs(result - expected) < 0.01

    def test_zero_weights_returns_neutral(self):
        scores = {k: 10.0 for k in RUBRIC_CHECKS}
        weights = {k: 0.0 for k in RUBRIC_CHECKS}
        result = compute_weighted_score(scores, weights)
        assert result == 5.0


# ============================================================================
# apply_staged_review_logic
# ============================================================================

class TestApplyStagedReviewLogic:
    def test_above_threshold_approved(self):
        assert apply_staged_review_logic(8.0, 7.0, {"low": 5.0, "high": 7.0}) == "approved"

    def test_at_threshold_approved(self):
        assert apply_staged_review_logic(7.0, 7.0, {"low": 5.0, "high": 7.0}) == "approved"

    def test_borderline_flagged(self):
        assert apply_staged_review_logic(6.0, 7.0, {"low": 5.0, "high": 7.0}) == "flagged"

    def test_at_borderline_low_flagged(self):
        assert apply_staged_review_logic(5.0, 7.0, {"low": 5.0, "high": 7.0}) == "flagged"

    def test_below_borderline_rejected(self):
        assert apply_staged_review_logic(4.0, 7.0, {"low": 5.0, "high": 7.0}) == "rejected"

    def test_zero_score_rejected(self):
        assert apply_staged_review_logic(0.0, 7.0, {"low": 5.0, "high": 7.0}) == "rejected"


# ============================================================================
# _build_rubric_prompt
# ============================================================================

class TestBuildRubricPrompt:
    def test_contains_all_checks(self):
        prompt = _build_rubric_prompt("Product X", "Hook text", {"format_type": "static"})
        for check in RUBRIC_CHECKS:
            assert check in prompt

    def test_contains_product_info(self):
        prompt = _build_rubric_prompt("SuperSerum", "Feel better", {"format_type": "static"})
        assert "SuperSerum" in prompt
        assert "Feel better" in prompt


# ============================================================================
# AdReviewService.review_ad_staged
# ============================================================================

class TestReviewAdStaged:
    def setup_method(self):
        self.service = AdReviewService()

    @pytest.mark.asyncio
    async def test_high_scores_approved(self):
        """All checks score high → approved."""
        high_scores = {k: 9.0 for k in RUBRIC_CHECKS}
        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock:
            mock.return_value = high_scores
            result = await self.service.review_ad_staged(
                image_data=b"fake_image",
                product_name="Test",
                hook_text="Hook",
                ad_analysis={},
            )
        assert result["final_status"] == "approved"
        assert result["review_check_scores"] is not None
        assert result["weighted_score"] > 7.0
        assert result["stage3_result"] is None  # No borderline → no Stage 3

    @pytest.mark.asyncio
    async def test_low_scores_rejected(self):
        """All checks score low → rejected."""
        low_scores = {k: 2.0 for k in RUBRIC_CHECKS}
        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock:
            mock.return_value = low_scores
            result = await self.service.review_ad_staged(
                image_data=b"fake_image",
                product_name="Test",
                hook_text="Hook",
                ad_analysis={},
            )
        assert result["final_status"] == "rejected"

    @pytest.mark.asyncio
    async def test_auto_reject_v9(self):
        """V9 (AI artifacts) below 3.0 → auto-rejected."""
        scores = {k: 9.0 for k in RUBRIC_CHECKS}
        scores["V9"] = 2.0  # Below auto-reject threshold
        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock:
            mock.return_value = scores
            result = await self.service.review_ad_staged(
                image_data=b"fake_image",
                product_name="Test",
                hook_text="Hook",
                ad_analysis={},
            )
        assert result["final_status"] == "rejected"
        assert result["auto_rejected_check"] == "V9"

    @pytest.mark.asyncio
    async def test_borderline_triggers_stage3(self):
        """Borderline Stage 2 score → triggers Stage 3 Gemini."""
        borderline_scores = {k: 8.0 for k in RUBRIC_CHECKS}
        borderline_scores["V3"] = 6.0  # In borderline range [5, 7]

        gemini_scores = {k: 9.0 for k in RUBRIC_CHECKS}

        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = borderline_scores
            with patch.object(self.service, "_run_rubric_review_gemini", new_callable=AsyncMock) as mock_gemini:
                mock_gemini.return_value = gemini_scores
                result = await self.service.review_ad_staged(
                    image_data=b"fake_image",
                    product_name="Test",
                    hook_text="Hook",
                    ad_analysis={},
                )

        assert result["stage3_result"] is not None
        assert "scores" in result["stage3_result"]
        # Gemini scored higher → should use Gemini scores
        assert result["final_status"] == "approved"

    @pytest.mark.asyncio
    async def test_stage2_failure_returns_review_failed(self):
        """Claude failure → review_failed."""
        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            result = await self.service.review_ad_staged(
                image_data=b"fake_image",
                product_name="Test",
                hook_text="Hook",
                ad_analysis={},
            )
        assert result["final_status"] == "review_failed"

    @pytest.mark.asyncio
    async def test_stage3_failure_non_fatal(self):
        """Stage 3 failure → falls back to Stage 2 score."""
        borderline_scores = {k: 8.0 for k in RUBRIC_CHECKS}
        borderline_scores["C2"] = 6.5  # Borderline

        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = borderline_scores
            with patch.object(self.service, "_run_rubric_review_gemini", new_callable=AsyncMock) as mock_gemini:
                mock_gemini.side_effect = Exception("Gemini down")
                result = await self.service.review_ad_staged(
                    image_data=b"fake_image",
                    product_name="Test",
                    hook_text="Hook",
                    ad_analysis={},
                )

        # Stage 3 attempted but failed → uses Stage 2 scores
        assert result["stage3_result"]["error"] == "Gemini down"
        assert result["review_check_scores"] == borderline_scores

    @pytest.mark.asyncio
    async def test_or_logic_stage3_better(self):
        """Stage 3 scores better → uses Stage 3 for final decision."""
        stage2_scores = {k: 6.0 for k in RUBRIC_CHECKS}  # All borderline
        stage3_scores = {k: 8.5 for k in RUBRIC_CHECKS}  # All good

        with patch.object(self.service, "_run_rubric_review_claude", new_callable=AsyncMock) as mc:
            mc.return_value = stage2_scores
            with patch.object(self.service, "_run_rubric_review_gemini", new_callable=AsyncMock) as mg:
                mg.return_value = stage3_scores
                result = await self.service.review_ad_staged(
                    image_data=b"fake_image",
                    product_name="Test",
                    hook_text="Hook",
                    ad_analysis={},
                )

        assert result["final_status"] == "approved"
        assert result["review_check_scores"] == stage3_scores


# ============================================================================
# load_quality_config
# ============================================================================

class TestLoadQualityConfig:

    @pytest.mark.asyncio
    async def test_returns_org_config_when_found(self):
        org_config = {"pass_threshold": 8.0, "check_weights": {"V1": 2.0}}

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[org_config])
        mock_db.table.return_value = mock_chain

        with patch(
            "viraltracker.core.database.get_supabase_client",
            return_value=mock_db,
        ):
            result = await load_quality_config(organization_id="org-123")

        assert result == org_config

    @pytest.mark.asyncio
    async def test_falls_back_to_global_config(self):
        global_config = {"pass_threshold": 7.0, "check_weights": {"V1": 1.5}}

        mock_db = MagicMock()
        call_count = 0

        def make_chain(data):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.is_.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=data)
            return chain

        def table_side_effect(name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_chain([])  # Org config not found
            return make_chain([global_config])  # Global config found

        mock_db.table.side_effect = table_side_effect

        with patch(
            "viraltracker.core.database.get_supabase_client",
            return_value=mock_db,
        ):
            result = await load_quality_config(organization_id="org-123")

        assert result == global_config

    @pytest.mark.asyncio
    async def test_returns_default_on_db_error(self):
        with patch(
            "viraltracker.core.database.get_supabase_client",
            side_effect=Exception("DB connection failed"),
        ):
            result = await load_quality_config()

        assert result == DEFAULT_QUALITY_CONFIG

    @pytest.mark.asyncio
    async def test_global_config_when_no_org_id(self):
        global_config = {"pass_threshold": 7.0}

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[global_config])
        mock_db.table.return_value = mock_chain

        with patch(
            "viraltracker.core.database.get_supabase_client",
            return_value=mock_db,
        ):
            result = await load_quality_config()

        assert result == global_config
