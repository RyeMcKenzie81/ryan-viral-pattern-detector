"""
Tests for ExemplarService — Phase 8A few-shot exemplar library.

Tests auto-seed logic, cap enforcement, diversity constraints,
similarity search, and build_exemplar_context format.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.pipelines.ad_creation_v2.services.exemplar_service import (
    ExemplarService,
    EXEMPLAR_CAPS,
    TOTAL_CAP,
)


def _brand_id():
    return UUID("00000000-0000-0000-0000-000000000001")


def _ad_id(n=1):
    return UUID(f"00000000-0000-0000-0000-{n:012d}")


class TestExemplarCaps:
    """Test per-brand cap enforcement."""

    def test_total_cap_is_30(self):
        assert TOTAL_CAP == 30

    def test_per_category_caps(self):
        assert EXEMPLAR_CAPS["gold_approve"] == 10
        assert EXEMPLAR_CAPS["gold_reject"] == 10
        assert EXEMPLAR_CAPS["edge_case"] == 10

    @pytest.mark.asyncio
    async def test_mark_as_exemplar_rejects_invalid_category(self):
        svc = ExemplarService()
        with pytest.raises(ValueError, match="Invalid category"):
            await svc.mark_as_exemplar(_brand_id(), _ad_id(), "invalid_cat")

    @pytest.mark.asyncio
    @patch("viraltracker.pipelines.ad_creation_v2.services.exemplar_service.ExemplarService.get_exemplar_stats")
    async def test_mark_rejects_when_total_cap_reached(self, mock_stats):
        mock_stats.return_value = {"gold_approve": 10, "gold_reject": 10, "edge_case": 10, "total": 30}
        svc = ExemplarService()
        with pytest.raises(ValueError, match="cap"):
            await svc.mark_as_exemplar(_brand_id(), _ad_id(), "gold_approve")

    @pytest.mark.asyncio
    @patch("viraltracker.pipelines.ad_creation_v2.services.exemplar_service.ExemplarService.get_exemplar_stats")
    async def test_mark_rejects_when_category_cap_reached(self, mock_stats):
        mock_stats.return_value = {"gold_approve": 10, "gold_reject": 5, "edge_case": 5, "total": 20}
        svc = ExemplarService()
        with pytest.raises(ValueError, match="cap reached"):
            await svc.mark_as_exemplar(_brand_id(), _ad_id(), "gold_approve")


class TestRemoveExemplar:
    """Test remove_exemplar soft delete."""

    @pytest.mark.asyncio
    async def test_deactivates_exemplar(self):
        svc = ExemplarService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

            await svc.remove_exemplar(uuid4(), "No longer representative")

            # Verify update was called with is_active=False
            update_call = client.table.return_value.update.call_args
            assert update_call[0][0]["is_active"] is False
            assert update_call[0][0]["deactivated_reason"] == "No longer representative"
            assert "deactivated_at" in update_call[0][0]


class TestDiverseSelection:
    """Test _select_diverse diversity constraints."""

    def test_selects_diverse_combos(self):
        svc = ExemplarService()

        candidates = [
            ("ad1", {"element_tags": {"template_category": "A"}, "canvas_size": "1080x1080", "color_mode": "warm"}, {}),
            ("ad2", {"element_tags": {"template_category": "A"}, "canvas_size": "1080x1080", "color_mode": "warm"}, {}),
            ("ad3", {"element_tags": {"template_category": "B"}, "canvas_size": "1080x1920", "color_mode": "cool"}, {}),
            ("ad4", {"element_tags": {"template_category": "C"}, "canvas_size": "1200x628", "color_mode": "brand"}, {}),
        ]

        selected = svc._select_diverse(candidates, 3)
        assert len(selected) == 3
        # Should pick ad1, ad3, ad4 (diverse combos first)
        selected_ids = [s[0] for s in selected]
        assert "ad1" in selected_ids
        assert "ad3" in selected_ids
        assert "ad4" in selected_ids

    def test_returns_all_when_under_max(self):
        svc = ExemplarService()
        candidates = [
            ("ad1", {"element_tags": {}}, {}),
            ("ad2", {"element_tags": {}}, {}),
        ]
        selected = svc._select_diverse(candidates, 5)
        assert len(selected) == 2

    def test_fills_remaining_slots(self):
        svc = ExemplarService()
        candidates = [
            ("ad1", {"element_tags": {"template_category": "A"}, "canvas_size": "1080", "color_mode": "warm"}, {}),
            ("ad2", {"element_tags": {"template_category": "A"}, "canvas_size": "1080", "color_mode": "warm"}, {}),
        ]
        selected = svc._select_diverse(candidates, 2)
        assert len(selected) == 2


class TestAutoSeedClassification:
    """Test classification rules for auto-seeding."""

    @pytest.mark.asyncio
    @patch("viraltracker.pipelines.ad_creation_v2.services.exemplar_service.ExemplarService.get_exemplar_stats")
    @patch("viraltracker.pipelines.ad_creation_v2.services.exemplar_service.ExemplarService.get_exemplars")
    async def test_auto_seed_returns_empty_when_no_overrides(self, mock_exemplars, mock_stats):
        mock_stats.return_value = {"gold_approve": 0, "gold_reject": 0, "edge_case": 0, "total": 0}
        mock_exemplars.return_value = []

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            # Chain: table().select().is_().eq().order().limit().execute()
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])
            client.table.return_value.select.return_value.is_.return_value.eq.return_value.order.return_value.limit.return_value = chain

            svc = ExemplarService()
            result = await svc.auto_seed_exemplars(_brand_id())

            assert result["seeded"] == 0


class TestBuildExemplarContext:
    """Test exemplar context formatting for review prompts."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_exemplars(self):
        svc = ExemplarService()
        with patch.object(svc, "find_similar_exemplars", new_callable=AsyncMock) as mock_find:
            mock_find.return_value = []
            result = await svc.build_exemplar_context(_brand_id(), [0.1] * 1536)
            assert result is None

    @pytest.mark.asyncio
    async def test_formats_exemplar_context(self):
        svc = ExemplarService()

        mock_exemplars = [
            {
                "category": "gold_approve",
                "hook_text": "Stop wasting money",
                "review_check_scores": {"V1": 9.0, "V2": 8.5, "V7": 9.0},
                "weighted_score": 8.8,
                "similarity": 0.92,
            },
            {
                "category": "gold_reject",
                "hook_text": "You won't believe",
                "review_check_scores": {"V1": 4.0, "V2": 3.0, "V7": 5.0},
                "weighted_score": 4.0,
                "similarity": 0.85,
            },
        ]

        async def mock_find(brand_id, embedding, category=None, limit=5):
            return [e for e in mock_exemplars if category is None or e["category"] == category]

        with patch.object(svc, "find_similar_exemplars", side_effect=mock_find):
            result = await svc.build_exemplar_context(_brand_id(), [0.1] * 1536)

            assert result is not None
            assert "Calibration Examples" in result
            assert "APPROVED" in result
            assert "REJECTED" in result
            assert "Stop wasting money" in result
