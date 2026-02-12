"""
Unit tests for ProductOfferVariantService new/modified methods:
- _normalize_to_string_list()
- create_offer_variant() slug collision retry
- create_or_update_offer_variant()
- extract_variant_from_landing_page()

Run with: pytest tests/test_product_offer_variant_service.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from postgrest.exceptions import APIError

from viraltracker.services.product_offer_variant_service import ProductOfferVariantService


@pytest.fixture
def service():
    """Create service with mocked Supabase client."""
    with patch("viraltracker.services.product_offer_variant_service.get_supabase_client") as mock_get:
        mock_supabase = MagicMock()
        mock_get.return_value = mock_supabase
        svc = ProductOfferVariantService()
        svc.supabase = mock_supabase
        return svc


# ---------------------------------------------------------------------------
# _normalize_to_string_list
# ---------------------------------------------------------------------------


class TestNormalizeToStringList:
    def test_none_returns_empty(self):
        assert ProductOfferVariantService._normalize_to_string_list(None) == []

    def test_empty_string_returns_empty(self):
        assert ProductOfferVariantService._normalize_to_string_list("") == []
        assert ProductOfferVariantService._normalize_to_string_list("   ") == []

    def test_string_returns_single_item(self):
        assert ProductOfferVariantService._normalize_to_string_list("hello") == ["hello"]

    def test_list_of_strings(self):
        result = ProductOfferVariantService._normalize_to_string_list(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_list_of_strings_filters_empty(self):
        result = ProductOfferVariantService._normalize_to_string_list(["a", "", "  ", "b"])
        assert result == ["a", "b"]

    def test_list_of_dicts_extracts_known_keys(self):
        data = [
            {"quote": "I love it", "author": "Jane"},
            {"text": "Great product"},
            {"explanation": "It works", "detail": "well"},
        ]
        result = ProductOfferVariantService._normalize_to_string_list(data)
        assert result == ["I love it", "Great product", "It works"]

    def test_list_of_dicts_fallback_to_str(self):
        data = [{"unknown_key": "value"}]
        result = ProductOfferVariantService._normalize_to_string_list(data)
        assert len(result) == 1
        assert "unknown_key" in result[0]

    def test_dict_with_nested_lists(self):
        data = {"emotional": ["pain1", "pain2"], "functional": ["pain3"]}
        result = ProductOfferVariantService._normalize_to_string_list(data)
        assert set(result) == {"pain1", "pain2", "pain3"}

    def test_dict_with_string_values(self):
        data = {"key1": "value1", "key2": "value2"}
        result = ProductOfferVariantService._normalize_to_string_list(data)
        assert set(result) == {"value1", "value2"}

    def test_max_items_limit(self):
        data = [f"item_{i}" for i in range(20)]
        result = ProductOfferVariantService._normalize_to_string_list(data, max_items=5)
        assert len(result) == 5

    def test_mixed_list(self):
        data = ["string", 42, {"quote": "quoted"}]
        result = ProductOfferVariantService._normalize_to_string_list(data)
        assert result == ["string", "42", "quoted"]


# ---------------------------------------------------------------------------
# create_offer_variant - slug collision retry
# ---------------------------------------------------------------------------


class TestCreateOfferVariantSlugRetry:
    def test_successful_first_attempt(self, service):
        product_id = uuid4()
        variant_id = str(uuid4())

        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": variant_id}])

        result = service.create_offer_variant(
            product_id=product_id,
            name="Test Variant",
            landing_page_url="https://example.com",
        )
        assert result == UUID(variant_id)

    def test_slug_collision_retries(self, service):
        product_id = uuid4()
        variant_id = str(uuid4())

        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        # First attempt fails with slug collision, second succeeds
        collision_error = APIError({"message": "duplicate key value violates unique constraint \"product_offer_variants_product_id_slug_key\""})
        success_result = MagicMock(data=[{"id": variant_id}])

        service.supabase.table.return_value.insert.return_value.execute.side_effect = [
            collision_error,
            success_result,
        ]

        result = service.create_offer_variant(
            product_id=product_id,
            name="Test Variant",
            landing_page_url="https://example.com",
        )
        assert result == UUID(variant_id)

    def test_non_slug_error_propagates(self, service):
        product_id = uuid4()

        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        other_error = APIError({"message": "some other database error"})
        service.supabase.table.return_value.insert.return_value.execute.side_effect = other_error

        with pytest.raises(APIError):
            service.create_offer_variant(
                product_id=product_id,
                name="Test",
                landing_page_url="https://example.com",
            )

    def test_new_params_included_in_data(self, service):
        product_id = uuid4()
        variant_id = str(uuid4())

        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": variant_id}])

        service.create_offer_variant(
            product_id=product_id,
            name="Test",
            landing_page_url="https://example.com",
            mechanism_name="Magic Enzyme",
            mechanism_problem="Root cause X",
            mechanism_solution="Solution Y",
            sample_hooks=["Hook 1", "Hook 2"],
            source="landing_page_analysis",
            source_metadata={"lp_id": "123"},
        )

        insert_call = service.supabase.table.return_value.insert
        assert insert_call.called
        data = insert_call.call_args[0][0]
        assert data["mechanism_name"] == "Magic Enzyme"
        assert data["mechanism_problem"] == "Root cause X"
        assert data["mechanism_solution"] == "Solution Y"
        assert data["sample_hooks"] == ["Hook 1", "Hook 2"]
        assert data["source"] == "landing_page_analysis"
        assert data["source_metadata"] == {"lp_id": "123"}


# ---------------------------------------------------------------------------
# create_or_update_offer_variant
# ---------------------------------------------------------------------------


class TestCreateOrUpdateOfferVariant:
    def test_creates_when_no_existing(self, service):
        product_id = uuid4()
        variant_id = str(uuid4())

        # No existing variant for URL
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        # create_offer_variant will be called — mock the chain
        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": variant_id}])

        result_id, was_created = service.create_or_update_offer_variant(
            product_id=product_id,
            landing_page_url="https://example.com/page",
            name="New Variant",
            pain_points=["pain1"],
        )
        assert was_created is True

    def test_updates_when_existing(self, service):
        product_id = uuid4()
        existing_id = str(uuid4())

        # Existing variant found
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": existing_id, "name": "Old Name"}]
        )
        # update path
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result_id, was_created = service.create_or_update_offer_variant(
            product_id=product_id,
            landing_page_url="https://example.com/page",
            name="Updated Name",
            pain_points=["new_pain"],
        )
        assert result_id == UUID(existing_id)
        assert was_created is False


# ---------------------------------------------------------------------------
# extract_variant_from_landing_page
# ---------------------------------------------------------------------------


class TestExtractVariantFromLandingPage:
    def test_not_found_returns_error(self, service):
        lp_id = uuid4()
        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        result = service.extract_variant_from_landing_page(lp_id)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_pending_page_returns_error(self, service):
        lp_id = uuid4()
        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": str(lp_id), "scrape_status": "pending", "url": "https://example.com"}]
        )

        result = service.extract_variant_from_landing_page(lp_id)
        assert result["success"] is False
        assert "not yet analyzed" in result["error"]

    def test_analyzed_page_extracts_fields(self, service):
        lp_id = uuid4()
        product_id = str(uuid4())

        page_data = {
            "id": str(lp_id),
            "scrape_status": "analyzed",
            "url": "https://example.com/offer",
            "page_title": "Amazing Offer",
            "product_id": product_id,
            "benefits": ["benefit1", "benefit2"],
            "analysis_raw": {
                "pain_points_addressed": ["pain1", "pain2"],
                "desires_appealed_to": {"transformation": ["become healthier"]},
                "persona_signals": {
                    "target_demographics": "Adults 40+",
                    "psychographics": "Health-conscious",
                },
                "copy_patterns": {
                    "key_phrases": ["Get started today", "Limited time"],
                },
                "objection_handling": [
                    {"objection": "Too expensive", "response": "Value guarantee"},
                ],
            },
            "belief_first_analysis": {
                "layers": {
                    "unique_mechanism": {
                        "explanation": "Nano-absorption technology",
                        "examples": [{"quote": "Works 3x faster"}],
                    },
                    "problem_pain_symptoms": {
                        "problem": "Poor nutrient absorption",
                        "examples": [{"quote": "Felt tired all the time"}],
                    },
                }
            },
        }

        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[page_data])

        result = service.extract_variant_from_landing_page(lp_id)

        assert result["success"] is True
        assert result["name"] == "Amazing Offer"
        assert result["landing_page_url"] == "https://example.com/offer"
        assert result["product_id"] == product_id
        assert "pain1" in result["pain_points"]
        assert result["benefits"] == ["benefit1", "benefit2"]
        assert result["mechanism_name"] == "Nano-absorption technology"
        assert result["mechanism_problem"] == "Poor nutrient absorption"
        assert result["mechanism_solution"] == "Works 3x faster"
        assert "Get started today" in result["sample_hooks"]
        assert result["source"] == "landing_page_analysis"
        # All fields should be strings or lists of strings
        assert isinstance(result["pain_points"], list)
        assert isinstance(result["benefits"], list)
        assert isinstance(result["target_audience"], str)
        assert isinstance(result["mechanism_name"], str)

    def test_minimal_page_extracts_available_data(self, service):
        lp_id = uuid4()

        page_data = {
            "id": str(lp_id),
            "scrape_status": "analyzed",
            "url": "https://example.com/simple",
            "page_title": None,
            "product_id": None,
            "benefits": None,
            "analysis_raw": None,
            "belief_first_analysis": None,
        }

        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[page_data])

        result = service.extract_variant_from_landing_page(lp_id)

        assert result["success"] is True
        assert result["product_id"] is None
        assert result["pain_points"] == []
        assert result["benefits"] == []
        assert result["mechanism_name"] == ""
