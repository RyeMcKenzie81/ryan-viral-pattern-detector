"""
Tests for Phase 5 cost estimation and batch guardrails.

Tests: basic estimate, multi-size/color multiplier, retry cost,
custom pricing, edge cases, backend cap enforcement.
"""

import pytest

from viraltracker.pipelines.ad_creation_v2.services.cost_estimation import (
    estimate_run_cost,
    PRICING_DEFAULTS,
    MAX_VARIATIONS_PER_RUN,
)


class TestEstimateRunCost:
    """Tests for the estimate_run_cost function."""

    def test_basic_estimate(self):
        """5 variations → correct total with all components."""
        result = estimate_run_cost(num_variations=5)
        assert result["total_ads"] == 5
        assert result["total_cost"] > 0
        assert result["per_ad_cost"] > 0
        assert "breakdown" in result

    def test_total_ads_calculation(self):
        """total_ads = num_variations * num_canvas_sizes * num_color_modes."""
        result = estimate_run_cost(num_variations=5, num_canvas_sizes=2, num_color_modes=3)
        assert result["total_ads"] == 30

    def test_multi_size_multiplier(self):
        """2 sizes → doubled total_ads and proportional cost increase."""
        single = estimate_run_cost(num_variations=5, num_canvas_sizes=1)
        double = estimate_run_cost(num_variations=5, num_canvas_sizes=2)
        assert double["total_ads"] == single["total_ads"] * 2
        # Cost should roughly double (plus fixed costs)
        assert double["total_cost"] > single["total_cost"]

    def test_multi_color_multiplier(self):
        """3 colors → tripled total_ads."""
        single = estimate_run_cost(num_variations=5, num_color_modes=1)
        triple = estimate_run_cost(num_variations=5, num_color_modes=3)
        assert triple["total_ads"] == single["total_ads"] * 3

    def test_retry_adds_cost(self):
        """auto_retry=True increases estimate by retry_rate."""
        no_retry = estimate_run_cost(num_variations=5, auto_retry=False)
        with_retry = estimate_run_cost(num_variations=5, auto_retry=True)
        assert with_retry["total_cost"] > no_retry["total_cost"]
        assert with_retry["retry_multiplier"] > 1.0
        assert no_retry["retry_multiplier"] == 1.0

    def test_custom_pricing(self):
        """Override pricing constants."""
        result = estimate_run_cost(
            num_variations=1,
            pricing={"gemini_image_gen_per_ad": 0.10},
        )
        # With higher gen cost, total should be higher
        default_result = estimate_run_cost(num_variations=1)
        assert result["total_cost"] > default_result["total_cost"]

    def test_breakdown_keys(self):
        """Result has all expected breakdown keys."""
        result = estimate_run_cost(num_variations=5)
        expected_keys = {
            "generation", "defect_scan", "stage2_review",
            "stage3_review", "congruence", "template_analysis",
        }
        assert set(result["breakdown"].keys()) == expected_keys

    def test_zero_variations(self):
        """Edge case: 0 variations → minimal cost."""
        result = estimate_run_cost(num_variations=0)
        assert result["total_ads"] == 0
        # Only fixed cost remains
        assert result["total_cost"] == PRICING_DEFAULTS["template_analysis_per_run"]

    def test_one_variation(self):
        """Edge case: 1 variation → base cost + fixed."""
        result = estimate_run_cost(num_variations=1)
        assert result["total_ads"] == 1
        assert result["total_cost"] > 0

    def test_stage3_conditional_cost(self):
        """Stage 3 cost = stage3_trigger_rate * gemini_review per ad."""
        result = estimate_run_cost(num_variations=1)
        expected_stage3 = (
            PRICING_DEFAULTS["gemini_vision_review_per_ad"]
            * PRICING_DEFAULTS["stage3_trigger_rate"]
        )
        assert result["breakdown"]["stage3_review"] == round(expected_stage3, 2)

    def test_all_values_non_negative(self):
        """No negative costs anywhere."""
        result = estimate_run_cost(num_variations=10, num_canvas_sizes=2, auto_retry=True)
        assert result["total_cost"] >= 0
        assert result["per_ad_cost"] >= 0
        for value in result["breakdown"].values():
            assert value >= 0


class TestBackendCap:
    """Tests for the MAX_VARIATIONS_PER_RUN constant."""

    def test_max_variations_is_50(self):
        """Backend cap is 50."""
        assert MAX_VARIATIONS_PER_RUN == 50

    def test_orchestrator_enforces_cap(self):
        """run_ad_creation_v2 raises ValueError for >50 variations."""
        from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2
        import asyncio

        with pytest.raises(ValueError, match="must be between 1 and 50"):
            asyncio.get_event_loop().run_until_complete(
                run_ad_creation_v2(
                    product_id="test",
                    reference_ad_base64="dGVzdA==",
                    num_variations=51,
                )
            )

    def test_orchestrator_allows_50(self):
        """run_ad_creation_v2 validation accepts exactly 50 (boundary value).

        Calls the real function with num_variations=50 to verify it passes
        validation. Patches the graph.run to avoid executing the full pipeline,
        and passes mock deps to avoid AgentDependencies.create() side effects.

        The orchestrator's except clause wraps all exceptions as
        Exception("Ad V2 workflow failed: ..."), so we check the wrapper
        message contains our sentinel string (proving graph.run was reached,
        meaning validation passed).
        """
        from unittest.mock import MagicMock, patch, AsyncMock
        from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2
        import asyncio

        _SENTINEL = "__graph_run_reached__"
        mock_deps = MagicMock()

        with patch(
            "viraltracker.pipelines.ad_creation_v2.orchestrator.ad_creation_v2_graph.run",
            new_callable=AsyncMock,
            side_effect=Exception(_SENTINEL),
        ):
            # Should NOT raise ValueError (validation passes for 50).
            # Will raise the wrapped Exception from graph.run — that's fine,
            # it proves we got past validation.
            with pytest.raises(Exception, match=_SENTINEL):
                asyncio.get_event_loop().run_until_complete(
                    run_ad_creation_v2(
                        product_id="test",
                        reference_ad_base64="dGVzdA==",
                        num_variations=50,
                        deps=mock_deps,
                    )
                )
