"""
Unit tests for ContentGapFillerService extract methods:
- extract_from_raw_content()
- extract_from_amazon_analysis()

These test the method logic with mocked LLM calls (no real AI or DB needed).

Run with: pytest tests/test_extract_methods.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.services.landing_page_analysis.content_gap_filler_service import (
    ContentGapFillerService,
    GAP_FIELD_REGISTRY,
)


@pytest.fixture
def service():
    """Create a service with a mocked Supabase client."""
    mock_supabase = MagicMock()
    svc = ContentGapFillerService(supabase=mock_supabase)
    svc._user_id = "test-user-id"
    svc._org_id = "test-org-id"
    return svc


# ---------------------------------------------------------------------------
# extract_from_raw_content
# ---------------------------------------------------------------------------

class TestExtractFromRawContent:
    @pytest.mark.asyncio
    async def test_empty_target_fields_returns_empty(self, service):
        """No valid target fields → empty result, no LLM call."""
        result = await service.extract_from_raw_content(
            raw_content="# Page\nSome content here.",
            target_fields=[],
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_target_fields_returns_empty(self, service):
        """All invalid field keys → empty result."""
        result = await service.extract_from_raw_content(
            raw_content="# Page\nSome content here.",
            target_fields=["nonexistent.field", "also.invalid"],
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_extracts_guarantee_from_content(self, service):
        """Mocked LLM returns a guarantee suggestion → extracted correctly."""
        raw = (
            "# Amazing Product\n\n"
            "The best product ever made.\n\n"
            "## Our Guarantee\n\n"
            "We offer a 365-day money-back guarantee. No questions asked.\n\n"
            "## FAQ\n\n"
            "Q: How long does shipping take?\n"
            "A: 3-5 business days.\n"
        )

        mock_llm_result = [
            {
                "field": "product.guarantee",
                "value": "365-day money-back guarantee",
                "confidence": "high",
                "evidence": [],
                "reasoning": "Explicitly stated in Guarantee section.",
            }
        ]

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee"],
            )

        assert "product.guarantee" in result
        assert result["product.guarantee"]["value"] == "365-day money-back guarantee"
        assert result["product.guarantee"]["confidence"] == "high"
        # Verify LLM was called
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyword_warning_when_product_not_found(self, service):
        """If product_name not in content, keyword_warning is set."""
        raw = "# Generic Page\nThis page has no brand references."

        mock_llm_result = [
            {"field": "product.guarantee", "value": "30-day refund", "confidence": "low"}
        ]

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee"],
                product_name="SuperWidget",
                brand_name="AcmeCorp",
            )

        assert "product.guarantee" in result
        assert "keyword_warning" in result["product.guarantee"]
        assert "SuperWidget" in result["product.guarantee"]["keyword_warning"]

    @pytest.mark.asyncio
    async def test_no_keyword_warning_when_product_found(self, service):
        """If product_name IS in content, no keyword_warning."""
        raw = "# SuperWidget Pro\nThe best SuperWidget in the market."

        mock_llm_result = [
            {"field": "product.guarantee", "value": "90-day guarantee", "confidence": "medium"}
        ]

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee"],
                product_name="SuperWidget",
            )

        assert "product.guarantee" in result
        assert "keyword_warning" not in result["product.guarantee"]

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self, service):
        """If LLM raises, extract_from_raw_content returns empty dict."""
        raw = "# Some Page\nContent here."

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM API down")
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee"],
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_fields_extracted(self, service):
        """Multiple target fields → multiple suggestions in result."""
        raw = (
            "# Product X\n\n"
            "## Ingredients\n\nVitamin D, Omega-3, Zinc\n\n"
            "## Guarantee\n\n60-day money-back guarantee.\n\n"
            "## How It Works\n\nOur patented technology.\n"
        )

        mock_llm_result = [
            {"field": "product.guarantee", "value": "60-day money-back guarantee", "confidence": "high"},
            {"field": "product.ingredients", "value": [{"name": "Vitamin D"}], "confidence": "high"},
            {"field": "offer_variant.mechanism.name", "value": "Patented technology", "confidence": "medium"},
        ]

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee", "product.ingredients", "offer_variant.mechanism.name"],
            )

        assert len(result) == 3
        assert "product.guarantee" in result
        assert "product.ingredients" in result
        assert "offer_variant.mechanism.name" in result

    @pytest.mark.asyncio
    async def test_llm_returns_single_dict_not_list(self, service):
        """If LLM returns a single dict instead of list, it's normalized."""
        raw = "# Page\n## Guarantee\n90-day refund."

        single_result = {
            "field": "product.guarantee",
            "value": "90-day refund",
            "confidence": "high",
        }

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = single_result
            result = await service.extract_from_raw_content(
                raw_content=raw,
                target_fields=["product.guarantee"],
            )

        assert "product.guarantee" in result

    @pytest.mark.asyncio
    async def test_chunks_are_used_in_prompt(self, service):
        """Verify that _build_extraction_prompt is called with chunked data."""
        raw = (
            "# Hero Section\nGreat product intro.\n\n"
            "## FAQ\nQ: How does it work?\nA: Science!\n"
        )

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            with patch.object(service, "_build_extraction_prompt", wraps=service._build_extraction_prompt) as mock_prompt:
                await service.extract_from_raw_content(
                    raw_content=raw,
                    target_fields=["product.faq_items"],
                )
                # Verify prompt was built with source_data containing chunks
                mock_prompt.assert_called_once()
                call_args = mock_prompt.call_args
                source_data = call_args[0][1]
                # source_data should have a key with "chunks" inside
                source_key = list(source_data.keys())[0]
                assert "chunks" in source_data[source_key]


# ---------------------------------------------------------------------------
# extract_from_amazon_analysis
# ---------------------------------------------------------------------------

class TestExtractFromAmazonAnalysis:
    @pytest.mark.asyncio
    async def test_empty_target_fields_returns_empty(self, service):
        result = await service.extract_from_amazon_analysis(
            amazon_analysis={"messaging": {"pain_points": ["back pain"]}},
            target_fields=[],
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_extracts_pain_points_from_amazon(self, service):
        amazon = {
            "messaging": {
                "pain_points": ["chronic back pain", "poor sleep quality"],
                "desires_goals": ["better mobility", "restful sleep"],
                "customer_language": ["game changer", "life saver"],
                "transformation_language": ["I can finally walk again"],
            }
        }

        mock_llm_result = [
            {
                "field": "offer_variant.pain_points",
                "value": ["Chronic back pain", "Poor sleep quality"],
                "confidence": "high",
                "reasoning": "Directly stated in customer reviews.",
            }
        ]

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await service.extract_from_amazon_analysis(
                amazon_analysis=amazon,
                target_fields=["offer_variant.pain_points"],
            )

        assert "offer_variant.pain_points" in result
        assert result["offer_variant.pain_points"]["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self, service):
        amazon = {"messaging": {"pain_points": ["back pain"]}}

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM down")
            result = await service.extract_from_amazon_analysis(
                amazon_analysis=amazon,
                target_fields=["offer_variant.pain_points"],
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_source_data_format(self, service):
        """Verify source_data is structured as amazon_review_analysis."""
        amazon = {
            "messaging": {
                "pain_points": ["headaches"],
                "desires_goals": ["clarity"],
                "customer_language": ["amazing"],
                "transformation_language": ["total transformation"],
            }
        }

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            with patch.object(service, "_build_extraction_prompt", wraps=service._build_extraction_prompt) as mock_prompt:
                await service.extract_from_amazon_analysis(
                    amazon_analysis=amazon,
                    target_fields=["offer_variant.pain_points"],
                )
                mock_prompt.assert_called_once()
                call_args = mock_prompt.call_args
                source_data = call_args[0][1]
                assert "amazon_review_analysis" in source_data
                assert source_data["amazon_review_analysis"]["pain_points"] == ["headaches"]
                assert source_data["amazon_review_analysis"]["desires"] == ["clarity"]

    @pytest.mark.asyncio
    async def test_missing_messaging_key_handled(self, service):
        """If amazon_analysis has no messaging key, fields are None."""
        amazon = {}

        with patch.object(service, "_run_extraction_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            result = await service.extract_from_amazon_analysis(
                amazon_analysis=amazon,
                target_fields=["offer_variant.pain_points"],
            )

        assert result == {}
