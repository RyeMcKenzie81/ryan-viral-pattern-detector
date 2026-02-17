"""
Tests for WhitespaceIdentificationService — competitive whitespace detection.

All database calls are mocked — no real DB or API connections needed.
"""

import math
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.services.whitespace_identification_service import (
    WhitespaceIdentificationService,
    TRACKED_ELEMENTS,
    NOVELTY_WEIGHT,
    NOVELTY_DECAY,
    MIN_INDIVIDUAL_SCORE,
    MAX_USAGE_FOR_WHITESPACE,
    MAX_CANDIDATES,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def ws_service():
    """Create a WhitespaceIdentificationService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = WhitespaceIdentificationService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")


# ============================================================================
# Algorithm tests
# ============================================================================

class TestWhitespaceScoring:
    def test_novelty_bonus_decays_with_usage(self):
        """Novelty bonus should decay exponentially with usage count."""
        bonus_0 = NOVELTY_WEIGHT * math.exp(0 / NOVELTY_DECAY)
        bonus_3 = NOVELTY_WEIGHT * math.exp(-3 / NOVELTY_DECAY)
        bonus_10 = NOVELTY_WEIGHT * math.exp(-10 / NOVELTY_DECAY)

        assert bonus_0 > bonus_3 > bonus_10
        assert bonus_0 == pytest.approx(NOVELTY_WEIGHT, abs=0.001)

    def test_low_individual_scores_filtered(self):
        """Elements with individual scores below threshold should be excluded."""
        assert MIN_INDIVIDUAL_SCORE == 0.5

    def test_high_usage_filtered(self):
        """Combos with high usage should be excluded."""
        assert MAX_USAGE_FOR_WHITESPACE == 5

    def test_max_candidates_limit(self):
        """Should keep at most MAX_CANDIDATES."""
        assert MAX_CANDIDATES == 20


class TestWhitespaceIdentification:
    @pytest.mark.asyncio
    async def test_empty_scores_returns_zero(self, ws_service):
        """When no element scores exist, should return 0 candidates."""
        ws_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        result = await ws_service.identify_whitespace(BRAND_ID)
        assert result["candidates_found"] == 0

    @pytest.mark.asyncio
    async def test_identifies_candidates(self, ws_service):
        """Should find candidates from high-scoring elements."""
        # Mock element scores
        scores_data = [
            {"element_name": "hook_type", "element_value": "curiosity", "alpha": 8.0, "beta": 2.0, "total_observations": 20},
            {"element_name": "color_mode", "element_value": "brand", "alpha": 7.0, "beta": 3.0, "total_observations": 15},
        ]

        # Mock interactions (empty)
        interactions_data = []

        # Mock usage (empty)
        usage_data = []

        # Set up mock chain
        table_mock = MagicMock()
        ws_service.supabase.table = MagicMock(side_effect=lambda name: {
            "creative_element_scores": MagicMock(
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        execute=MagicMock(return_value=MagicMock(data=scores_data))
                    ))
                ))
            ),
            "element_interactions": MagicMock(
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        execute=MagicMock(return_value=MagicMock(data=interactions_data))
                    ))
                ))
            ),
            "element_combo_usage": MagicMock(
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        execute=MagicMock(return_value=MagicMock(data=usage_data))
                    ))
                ))
            ),
            "whitespace_candidates": MagicMock(
                upsert=MagicMock(return_value=MagicMock(
                    execute=MagicMock(return_value=MagicMock(data=[]))
                ))
            ),
        }.get(name, MagicMock()))

        result = await ws_service.identify_whitespace(BRAND_ID)
        assert result["candidates_found"] >= 1


class TestFormatWhitespaceAdvisory:
    def test_empty_candidates_returns_none(self, ws_service):
        """No candidates should return None."""
        assert ws_service.format_whitespace_advisory([]) is None

    def test_formats_candidates(self, ws_service):
        """Should format candidates into readable advisory."""
        candidates = [{
            "element_a_name": "hook_type",
            "element_a_value": "curiosity",
            "element_b_name": "color_mode",
            "element_b_value": "brand",
            "predicted_potential": 0.85,
        }]

        result = ws_service.format_whitespace_advisory(candidates)
        assert result is not None
        assert "hook_type=curiosity" in result
        assert "color_mode=brand" in result
        assert "0.85" in result

    def test_limits_output(self, ws_service):
        """Should limit to specified number of candidates."""
        candidates = [
            {"element_a_name": f"e{i}", "element_a_value": f"v{i}",
             "element_b_name": f"e{i+10}", "element_b_value": f"v{i+10}",
             "predicted_potential": 0.9 - i * 0.1}
            for i in range(5)
        ]

        result = ws_service.format_whitespace_advisory(candidates, limit=2)
        assert result is not None
        # Should only contain 2 candidates
        assert "e0=v0" in result
        assert "e1=v1" in result


class TestGetWhitespaceCandidates:
    def test_returns_ordered_candidates(self, ws_service):
        """Should return candidates ordered by rank."""
        mock_data = [
            {"whitespace_rank": 1, "predicted_potential": 0.9},
            {"whitespace_rank": 2, "predicted_potential": 0.8},
        ]
        ws_service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=mock_data)

        result = ws_service.get_whitespace_candidates(BRAND_ID)
        assert len(result) == 2
        assert result[0]["whitespace_rank"] == 1
