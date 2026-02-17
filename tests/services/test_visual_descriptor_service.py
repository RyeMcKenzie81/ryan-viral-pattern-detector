"""
Tests for VisualDescriptorService — Phase 8A visual embedding extraction.

Tests descriptor extraction parsing, embedding call, store/retrieve, and
text conversion for embedding.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from viraltracker.pipelines.ad_creation_v2.services.visual_descriptor_service import (
    VisualDescriptorService,
    DESCRIPTOR_FIELDS,
)


def _brand_id():
    return UUID("00000000-0000-0000-0000-000000000001")


def _ad_id():
    return UUID("00000000-0000-0000-0000-000000000002")


SAMPLE_DESCRIPTORS = {
    "layout_type": "hero",
    "color_palette": ["#FF5733", "#33FF57"],
    "dominant_colors": ["warm_red", "cool_green"],
    "visual_style": "lifestyle",
    "composition": "rule_of_thirds",
    "text_placement": "top",
    "text_density": "moderate",
    "has_person": True,
    "has_product": True,
    "mood": "energetic",
    "background_type": "photo",
}


class TestParseDescriptors:
    """Test _parse_descriptors JSON parsing."""

    def test_valid_json(self):
        import json
        svc = VisualDescriptorService()
        result = svc._parse_descriptors(json.dumps(SAMPLE_DESCRIPTORS))
        assert result["layout_type"] == "hero"
        assert result["visual_style"] == "lifestyle"
        assert result["has_person"] is True

    def test_markdown_wrapped_json(self):
        import json
        svc = VisualDescriptorService()
        text = f"```json\n{json.dumps(SAMPLE_DESCRIPTORS)}\n```"
        result = svc._parse_descriptors(text)
        assert result["layout_type"] == "hero"

    def test_invalid_json_returns_defaults(self):
        svc = VisualDescriptorService()
        result = svc._parse_descriptors("not json at all")
        assert result["layout_type"] == "unknown"
        assert result["has_person"] is False

    def test_partial_json_fills_missing(self):
        import json
        svc = VisualDescriptorService()
        partial = {"layout_type": "grid", "mood": "calm"}
        result = svc._parse_descriptors(json.dumps(partial))
        assert result["layout_type"] == "grid"
        assert result["mood"] == "calm"
        assert result["composition"] is None  # Missing fields are None


class TestDescriptorsToText:
    """Test _descriptors_to_text embedding text construction."""

    def test_includes_all_fields(self):
        svc = VisualDescriptorService()
        text = svc._descriptors_to_text(SAMPLE_DESCRIPTORS)

        assert "Layout: hero" in text
        assert "Style: lifestyle" in text
        assert "Composition: rule_of_thirds" in text
        assert "Mood: energetic" in text
        assert "Background: photo" in text
        assert "Person: yes" in text
        assert "Product: yes" in text
        assert "warm_red" in text

    def test_handles_empty_lists(self):
        svc = VisualDescriptorService()
        desc = dict(SAMPLE_DESCRIPTORS)
        desc["color_palette"] = []
        desc["dominant_colors"] = []
        text = svc._descriptors_to_text(desc)
        assert "Layout: hero" in text
        # Should not crash with empty lists

    def test_handles_missing_keys(self):
        svc = VisualDescriptorService()
        text = svc._descriptors_to_text({})
        assert "Layout: unknown" in text
        assert "Person: no" in text


class TestDefaultDescriptors:
    """Test _default_descriptors fallback."""

    def test_all_fields_present(self):
        svc = VisualDescriptorService()
        defaults = svc._default_descriptors()
        for field in DESCRIPTOR_FIELDS:
            assert field in defaults

    def test_unknown_values(self):
        svc = VisualDescriptorService()
        defaults = svc._default_descriptors()
        assert defaults["layout_type"] == "unknown"
        assert defaults["has_person"] is False


class TestDescriptorFields:
    """Test DESCRIPTOR_FIELDS constant."""

    def test_has_11_fields(self):
        assert len(DESCRIPTOR_FIELDS) == 11

    def test_expected_fields(self):
        assert "layout_type" in DESCRIPTOR_FIELDS
        assert "color_palette" in DESCRIPTOR_FIELDS
        assert "mood" in DESCRIPTOR_FIELDS
        assert "background_type" in DESCRIPTOR_FIELDS


class TestExtractDescriptors:
    """Test extract_descriptors with mocked Gemini."""

    @pytest.mark.asyncio
    async def test_calls_gemini_service(self):
        svc = VisualDescriptorService()
        import json

        mock_gemini = MagicMock()
        mock_gemini.analyze_image = AsyncMock(
            return_value=json.dumps(SAMPLE_DESCRIPTORS)
        )

        with patch("viraltracker.services.gemini_service.GeminiService", return_value=mock_gemini):
            result = await svc.extract_descriptors(b"fake_image_data")
            assert result["layout_type"] == "hero"
            mock_gemini.analyze_image.assert_called_once()


class TestEmbedDescriptors:
    """Test embed_descriptors with mocked OpenAI."""

    @pytest.mark.asyncio
    async def test_calls_openai_embeddings(self):
        svc = VisualDescriptorService()

        mock_embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=mock_embedding)]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            result = await svc.embed_descriptors(SAMPLE_DESCRIPTORS)
            assert len(result) == 1536
            assert result[0] == 0.1


class TestExtractAndStore:
    """Test extract_and_store full pipeline with mocks."""

    @pytest.mark.asyncio
    async def test_stores_embedding_in_db(self):
        svc = VisualDescriptorService()

        with patch.object(svc, "extract_descriptors", new_callable=AsyncMock) as mock_extract, \
             patch.object(svc, "embed_descriptors", new_callable=AsyncMock) as mock_embed, \
             patch("viraltracker.core.database.get_supabase_client") as mock_db:

            mock_extract.return_value = SAMPLE_DESCRIPTORS
            mock_embed.return_value = [0.1] * 1536

            client = MagicMock()
            mock_db.return_value = client
            ve_uuid = "00000000-0000-0000-0000-000000000099"
            client.table.return_value.upsert.return_value.execute.return_value = MagicMock(
                data=[{"id": ve_uuid}]
            )

            result = await svc.extract_and_store(_ad_id(), _brand_id(), b"fake_image")
            assert result == UUID(ve_uuid)
            mock_extract.assert_called_once()
            mock_embed.assert_called_once()
            client.table.assert_called_with("visual_embeddings")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self):
        svc = VisualDescriptorService()

        with patch.object(svc, "extract_descriptors", new_callable=AsyncMock) as mock_extract, \
             patch.object(svc, "embed_descriptors", new_callable=AsyncMock) as mock_embed, \
             patch("viraltracker.core.database.get_supabase_client") as mock_db:

            mock_extract.return_value = SAMPLE_DESCRIPTORS
            mock_embed.return_value = [0.1] * 1536

            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.extract_and_store(_ad_id(), _brand_id(), b"fake_image")
            assert result is None


class TestGetEmbedding:
    """Test get_embedding DB lookup."""

    @pytest.mark.asyncio
    async def test_returns_embedding_when_found(self):
        svc = VisualDescriptorService()
        mock_embedding = [0.2] * 1536

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"embedding": mock_embedding}]
            )

            result = await svc.get_embedding(_ad_id())
            assert result == mock_embedding

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        svc = VisualDescriptorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )

            result = await svc.get_embedding(_ad_id())
            assert result is None


class TestGetVisualEmbeddingRow:
    """Test get_visual_embedding_row DB lookup."""

    @pytest.mark.asyncio
    async def test_returns_row_when_found(self):
        svc = VisualDescriptorService()
        mock_row = {"id": "ve-1", "generated_ad_id": str(_ad_id()), "visual_descriptors": SAMPLE_DESCRIPTORS}

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[mock_row]
            )

            result = await svc.get_visual_embedding_row(_ad_id())
            assert result["id"] == "ve-1"
            assert result["visual_descriptors"] == SAMPLE_DESCRIPTORS

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        svc = VisualDescriptorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )

            result = await svc.get_visual_embedding_row(_ad_id())
            assert result is None


class TestFindSimilarAds:
    """Test find_similar_ads pgvector query."""

    @pytest.mark.asyncio
    async def test_returns_similar_ads(self):
        svc = VisualDescriptorService()
        mock_results = [
            {"id": "ve-1", "generated_ad_id": "ad-1", "similarity": 0.95},
            {"id": "ve-2", "generated_ad_id": "ad-2", "similarity": 0.88},
        ]

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.rpc.return_value.execute.return_value = MagicMock(data=mock_results)

            result = await svc.find_similar_ads(_brand_id(), [0.1] * 1536, limit=5)
            assert len(result) == 2
            assert result[0]["similarity"] == 0.95

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_matches(self):
        svc = VisualDescriptorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.rpc.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.find_similar_ads(_brand_id(), [0.1] * 1536)
            assert result == []

    @pytest.mark.asyncio
    async def test_exclude_ad_id_included_in_query(self):
        svc = VisualDescriptorService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.rpc.return_value.execute.return_value = MagicMock(data=[])

            await svc.find_similar_ads(_brand_id(), [0.1] * 1536, exclude_ad_id=_ad_id())
            # Verify exec_sql was called with the exclude clause
            call_args = client.rpc.call_args
            assert "exec_sql" in str(call_args)
            query = call_args[1]["params"]["query"] if "params" in call_args[1] else call_args[0][1]["query"]
            assert str(_ad_id()) in query
