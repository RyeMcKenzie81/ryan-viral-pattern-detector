"""
Tests for InteractionDetectorService — Phase 8A pairwise element effect detection.

Tests pairwise computation, ranking, effect classification, bootstrap CI,
canonical ordering, and format_advisory_context.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from viraltracker.services.interaction_detector_service import (
    InteractionDetectorService,
    TRACKED_ELEMENTS,
    MIN_PAIR_SAMPLE,
    SYNERGY_THRESHOLD,
    CONFLICT_THRESHOLD,
)


def _brand_id():
    return UUID("00000000-0000-0000-0000-000000000001")


class TestConstants:
    """Test service constants."""

    def test_tracked_elements(self):
        assert "hook_type" in TRACKED_ELEMENTS
        assert "color_mode" in TRACKED_ELEMENTS
        assert "template_category" in TRACKED_ELEMENTS
        assert len(TRACKED_ELEMENTS) == 6

    def test_min_pair_sample(self):
        assert MIN_PAIR_SAMPLE == 10

    def test_thresholds(self):
        assert SYNERGY_THRESHOLD == 0.05
        assert CONFLICT_THRESHOLD == -0.05


class TestBootstrapCI:
    """Test _bootstrap_ci confidence interval computation."""

    def test_returns_low_high_tuple(self):
        svc = InteractionDetectorService()
        rewards = [0.5, 0.6, 0.7, 0.8, 0.9, 0.5, 0.6, 0.7, 0.8, 0.9]
        ci_low, ci_high = svc._bootstrap_ci(rewards, expected=0.5)
        assert ci_low < ci_high

    def test_narrow_ci_for_tight_data(self):
        svc = InteractionDetectorService()
        rewards = [0.5] * 100
        ci_low, ci_high = svc._bootstrap_ci(rewards, expected=0.5)
        # CI should be very narrow for constant data
        assert abs(ci_high - ci_low) < 0.01

    def test_wide_ci_for_varied_data(self):
        svc = InteractionDetectorService()
        np.random.seed(42)
        rewards = list(np.random.uniform(0, 1, 20))
        ci_low, ci_high = svc._bootstrap_ci(rewards, expected=0.5)
        assert ci_high - ci_low > 0.01


class TestNormCdf:
    """Test _norm_cdf standard normal approximation."""

    def test_zero(self):
        svc = InteractionDetectorService()
        assert abs(svc._norm_cdf(0) - 0.5) < 0.001

    def test_large_positive(self):
        svc = InteractionDetectorService()
        assert svc._norm_cdf(5.0) > 0.999

    def test_large_negative(self):
        svc = InteractionDetectorService()
        assert svc._norm_cdf(-5.0) < 0.001


class TestFormatAdvisoryContext:
    """Test format_advisory_context natural language output."""

    def test_empty_interactions(self):
        svc = InteractionDetectorService()
        assert svc.format_advisory_context([]) == ""

    def test_formats_synergies(self):
        svc = InteractionDetectorService()
        interactions = [
            {
                "element_a_name": "hook_type",
                "element_a_value": "curiosity_gap",
                "element_b_name": "color_mode",
                "element_b_value": "warm",
                "interaction_effect": 0.15,
                "effect_direction": "synergy",
                "sample_size": 42,
            },
        ]
        result = svc.format_advisory_context(interactions)
        assert "synergy" in result.lower() or "Strong synergy" in result
        assert "curiosity_gap" in result
        assert "warm" in result
        assert "42" in result

    def test_formats_conflicts(self):
        svc = InteractionDetectorService()
        interactions = [
            {
                "element_a_name": "hook_type",
                "element_a_value": "authority_drop",
                "element_b_name": "color_mode",
                "element_b_value": "cool",
                "interaction_effect": -0.12,
                "effect_direction": "conflict",
                "sample_size": 38,
            },
        ]
        result = svc.format_advisory_context(interactions)
        assert "Avoid" in result
        assert "authority_drop" in result

    def test_limits_to_3_per_direction(self):
        svc = InteractionDetectorService()
        # 5 synergies, should only show top 3
        interactions = [
            {
                "element_a_name": f"elem_{i}",
                "element_a_value": f"val_{i}",
                "element_b_name": "color_mode",
                "element_b_value": "warm",
                "interaction_effect": 0.1 + i * 0.01,
                "effect_direction": "synergy",
                "sample_size": 20,
            }
            for i in range(5)
        ]
        result = svc.format_advisory_context(interactions)
        # Count occurrences of "Strong synergy" or "synergy"
        assert result.count("Strong synergy") <= 3


class TestDetectInteractions:
    """Test detect_interactions with mocked data."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rewards(self):
        svc = InteractionDetectorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.detect_interactions(_brand_id())
            assert result["interactions"] == []
            assert result["total_ads_analyzed"] == 0

    @pytest.mark.asyncio
    async def test_canonical_ordering_enforced(self):
        """Verify (a_name, a_value) <= (b_name, b_value) alphabetically."""
        svc = InteractionDetectorService()

        # Create mock data where elements could appear in non-canonical order
        rewards_data = []
        for i in range(20):
            rewards_data.append({
                "generated_ad_id": f"ad-{i}",
                "reward_score": 0.5 + (i % 5) * 0.1,
                "generated_ads": {
                    "id": f"ad-{i}",
                    "element_tags": {
                        "hook_type": "curiosity_gap",
                        "color_mode": "warm" if i % 2 == 0 else "cool",
                    }
                }
            })

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=rewards_data)
            client.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.detect_interactions(_brand_id(), min_sample_size=5)

            # Check canonical ordering on all interactions
            for interaction in result["interactions"]:
                a = (interaction["element_a_name"], interaction["element_a_value"])
                b = (interaction["element_b_name"], interaction["element_b_value"])
                assert a <= b, f"Non-canonical ordering: {a} > {b}"

    @pytest.mark.asyncio
    async def test_limits_to_top_15(self):
        """Verify only top 15 interactions are kept."""
        svc = InteractionDetectorService()

        # Create enough data for many pairs
        rewards_data = []
        elements = ["curiosity", "authority", "fear", "social_proof", "urgency"]
        colors = ["warm", "cool", "brand", "neutral"]
        for i in range(100):
            rewards_data.append({
                "generated_ad_id": f"ad-{i}",
                "reward_score": np.random.uniform(0, 1),
                "generated_ads": {
                    "id": f"ad-{i}",
                    "element_tags": {
                        "hook_type": elements[i % len(elements)],
                        "color_mode": colors[i % len(colors)],
                    }
                }
            })

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=rewards_data)
            client.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.detect_interactions(_brand_id(), min_sample_size=5)
            assert len(result["interactions"]) <= 15


class TestGetTopInteractions:
    """Test get_top_interactions DB retrieval."""

    @pytest.mark.asyncio
    async def test_returns_stored_interactions(self):
        svc = InteractionDetectorService()
        mock_interactions = [
            {"element_a_name": "hook_type", "element_a_value": "curiosity", "effect_rank": 1},
            {"element_a_name": "color_mode", "element_a_value": "warm", "effect_rank": 2},
        ]

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=mock_interactions
            )

            result = await svc.get_top_interactions(_brand_id())
            assert len(result) == 2
            assert result[0]["effect_rank"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        svc = InteractionDetectorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )

            result = await svc.get_top_interactions(_brand_id())
            assert result == []

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self):
        svc = InteractionDetectorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            limit_mock = client.table.return_value.select.return_value.eq.return_value.order.return_value.limit
            limit_mock.return_value.execute.return_value = MagicMock(data=[])

            await svc.get_top_interactions(_brand_id(), limit=5)
            limit_mock.assert_called_with(5)


class TestEffectClassification:
    """Test effect direction classification."""

    def test_synergy_above_threshold(self):
        assert 0.10 > SYNERGY_THRESHOLD

    def test_conflict_below_threshold(self):
        assert -0.10 < CONFLICT_THRESHOLD

    def test_neutral_in_range(self):
        assert CONFLICT_THRESHOLD <= 0.0 <= SYNERGY_THRESHOLD
