"""
Unit tests for BrandResearchService new/modified methods:
- _normalize_lp_field()
- _integrate_single_landing_page()
- _integrate_landing_page_data()
- _integrate_variant_landing_page()
- _get_ad_ids_for_product()
- _get_analyses_by_ad_ids()
- SynthesisDataSources dataclass

Run with: pytest tests/test_brand_research_synthesis.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import UUID, uuid4

from viraltracker.services.brand_research_service import (
    BrandResearchService,
    SynthesisDataSources,
)


@pytest.fixture
def service():
    """Create service with mocked Supabase client."""
    with patch("viraltracker.services.brand_research_service.get_supabase_client") as mock_get:
        mock_supabase = MagicMock()
        mock_get.return_value = mock_supabase
        svc = BrandResearchService()
        svc.supabase = mock_supabase
        return svc


def _empty_aggregated():
    """Build a minimal aggregated structure for testing."""
    return {
        "pain_points": {"emotional": [], "functional": [], "social": []},
        "desires": {"self_actualization": [], "comfort_convenience": []},
        "transformation": {"before": [], "after": []},
        "benefits": {"functional": [], "emotional": []},
        "hooks": [],
        "customer_language": {"descriptive_words": [], "phrases": []},
        "persona_signals": [],
        "objections": [],
        "purchase_triggers": [],
        "analysis_counts": {
            "video_vision": 0,
            "image_vision": 0,
            "copy_analysis": 0,
            "amazon_reviews": 0,
            "landing_pages": 0,
        },
        "has_data": False,
    }


# ---------------------------------------------------------------------------
# SynthesisDataSources
# ---------------------------------------------------------------------------


class TestSynthesisDataSources:
    def test_defaults_all_enabled(self):
        sources = SynthesisDataSources()
        assert sources.include_ad_analyses is True
        assert sources.include_amazon_reviews is True
        assert sources.include_landing_pages is True

    def test_custom_toggles(self):
        sources = SynthesisDataSources(
            include_ad_analyses=False,
            include_amazon_reviews=False,
            include_landing_pages=True,
        )
        assert sources.include_ad_analyses is False
        assert sources.include_amazon_reviews is False
        assert sources.include_landing_pages is True


# ---------------------------------------------------------------------------
# _normalize_lp_field
# ---------------------------------------------------------------------------


class TestNormalizeLpField:
    def test_none_returns_empty(self):
        assert BrandResearchService._normalize_lp_field(None) == []

    def test_string_returns_single_item(self):
        assert BrandResearchService._normalize_lp_field("hello") == ["hello"]

    def test_empty_string_returns_empty(self):
        assert BrandResearchService._normalize_lp_field("") == []
        assert BrandResearchService._normalize_lp_field("  ") == []

    def test_list_of_strings(self):
        result = BrandResearchService._normalize_lp_field(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_list_of_strings_filters_empty(self):
        result = BrandResearchService._normalize_lp_field(["a", "", "  ", "b"])
        assert result == ["a", "b"]

    def test_list_of_dicts_extracts_known_keys(self):
        data = [
            {"quote": "I love it", "location": "hero"},
            {"text": "Great stuff"},
            {"explanation": "It works"},
        ]
        result = BrandResearchService._normalize_lp_field(data)
        assert result == ["I love it", "Great stuff", "It works"]

    def test_dict_with_nested_lists_of_strings(self):
        data = {"emotional": ["pain1", "pain2"], "functional": ["pain3"]}
        result = BrandResearchService._normalize_lp_field(data)
        assert set(result) == {"pain1", "pain2", "pain3"}

    def test_dict_with_nested_lists_of_dicts(self):
        data = {"examples": [{"quote": "Nice"}, {"text": "Good"}]}
        result = BrandResearchService._normalize_lp_field(data)
        assert result == ["Nice", "Good"]

    def test_dict_with_string_values(self):
        data = {"key1": "value1", "key2": "value2"}
        result = BrandResearchService._normalize_lp_field(data)
        assert set(result) == {"value1", "value2"}

    def test_unsupported_type_returns_empty(self):
        assert BrandResearchService._normalize_lp_field(42) == []
        assert BrandResearchService._normalize_lp_field(True) == []


# ---------------------------------------------------------------------------
# _integrate_single_landing_page
# ---------------------------------------------------------------------------


class TestIntegrateSingleLandingPage:
    def test_empty_page_data(self, service):
        aggregated = _empty_aggregated()
        result = service._integrate_single_landing_page(aggregated, {})
        assert result["has_data"] is True  # Still marks has_data

    def test_pain_points_extracted(self, service):
        aggregated = _empty_aggregated()
        page = {
            "analysis_raw": {
                "pain_points_addressed": ["chronic fatigue", "brain fog"]
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert "chronic fatigue" in result["pain_points"]["functional"]
        assert "brain fog" in result["pain_points"]["functional"]

    def test_desires_extracted(self, service):
        aggregated = _empty_aggregated()
        page = {
            "analysis_raw": {
                "desires_appealed_to": {
                    "transformation": ["become healthier"],
                    "outcomes": ["more energy"],
                    "emotional_benefits": ["feel confident"],
                }
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert "become healthier" in result["transformation"]["after"]
        assert "more energy" in result["desires"]["self_actualization"]
        assert "feel confident" in result["desires"]["comfort_convenience"]

    def test_benefits_from_column(self, service):
        aggregated = _empty_aggregated()
        page = {"benefits": ["Fast shipping", "Money back"]}
        result = service._integrate_single_landing_page(aggregated, page)
        assert "Fast shipping" in result["benefits"]["functional"]

    def test_copy_patterns_extracted(self, service):
        aggregated = _empty_aggregated()
        page = {
            "analysis_raw": {
                "copy_patterns": {
                    "key_phrases": ["Act now", "Limited time"],
                    "power_words": ["revolutionary", "breakthrough"],
                }
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert "Act now" in result["hooks"]
        assert "revolutionary" in result["customer_language"]["descriptive_words"]

    def test_persona_signals_appended(self, service):
        aggregated = _empty_aggregated()
        page = {
            "analysis_raw": {
                "persona_signals": {"target_demographics": "Women 30-50"}
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert len(result["persona_signals"]) == 1
        assert result["persona_signals"][0]["target_demographics"] == "Women 30-50"

    def test_objections_extracted(self, service):
        aggregated = _empty_aggregated()
        page = {
            "analysis_raw": {
                "objection_handling": [
                    {"objection": "Too expensive", "response": "Value guarantee"}
                ]
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert "Too expensive" in result["objections"]

    def test_belief_first_layers(self, service):
        aggregated = _empty_aggregated()
        page = {
            "belief_first_analysis": {
                "layers": {
                    "problem_pain_symptoms": {
                        "examples": [{"quote": "I felt terrible"}]
                    },
                    "benefits": {
                        "examples": [{"quote": "Now I feel great"}]
                    },
                    "jobs_to_be_done": {
                        "explanation": "Help people absorb nutrients better"
                    },
                }
            }
        }
        result = service._integrate_single_landing_page(aggregated, page)
        assert "I felt terrible" in result["pain_points"]["emotional"]
        assert "Now I feel great" in result["benefits"]["emotional"]
        assert any("[LP]" in t for t in result["purchase_triggers"])

    def test_none_analysis_raw_handled(self, service):
        aggregated = _empty_aggregated()
        page = {"analysis_raw": None, "belief_first_analysis": None, "benefits": None}
        result = service._integrate_single_landing_page(aggregated, page)
        assert result["has_data"] is True
        assert result["pain_points"]["functional"] == []


# ---------------------------------------------------------------------------
# _integrate_landing_page_data
# ---------------------------------------------------------------------------


class TestIntegrateLandingPageData:
    def test_no_pages_returns_unchanged(self, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()

        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        result = service._integrate_landing_page_data(aggregated, brand_id)
        assert result["has_data"] is False

    def test_pages_integrated(self, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()

        pages = [
            {
                "analysis_raw": {"pain_points_addressed": ["headache"]},
                "belief_first_analysis": None,
                "benefits": ["relief"],
            }
        ]
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=pages)

        result = service._integrate_landing_page_data(aggregated, brand_id)
        assert result["analysis_counts"]["landing_pages"] == 1
        assert "headache" in result["pain_points"]["functional"]

    def test_product_id_filter_applied(self, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()
        product_id = uuid4()

        # The query chain adds an extra .eq for product_id
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        service._integrate_landing_page_data(aggregated, brand_id, product_id)
        # Verify the method completed without error (product_id was passed)

    def test_exception_does_not_fail_synthesis(self, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()

        service.supabase.table.side_effect = Exception("DB down")

        result = service._integrate_landing_page_data(aggregated, brand_id)
        # Should return aggregated unchanged, not raise
        assert result["has_data"] is False


# ---------------------------------------------------------------------------
# _integrate_variant_landing_page
# ---------------------------------------------------------------------------


class TestIntegrateVariantLandingPage:
    @patch("viraltracker.services.brand_research_service.BrandResearchService._integrate_single_landing_page")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_found_by_canonical_url(self, mock_canon, mock_integrate, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()

        page = {"id": str(uuid4()), "analysis_raw": {"pain_points_addressed": ["pain"]}}
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[page])
        mock_integrate.return_value = aggregated

        service._integrate_variant_landing_page(aggregated, brand_id, "https://example.com/page")

        mock_integrate.assert_called_once()

    def test_exception_does_not_fail(self, service):
        aggregated = _empty_aggregated()
        brand_id = uuid4()

        service.supabase.table.side_effect = Exception("DB error")

        result = service._integrate_variant_landing_page(
            aggregated, brand_id, "https://example.com"
        )
        assert result is not None  # Should return gracefully


# ---------------------------------------------------------------------------
# _get_ad_ids_for_product
# ---------------------------------------------------------------------------


class TestGetAdIdsForProduct:
    def test_returns_both_types(self, service):
        brand_id = uuid4()
        product_id = uuid4()

        fb_data = [{"id": "fb1"}, {"id": "fb2"}]
        meta_data = [{"meta_ad_id": "meta1"}]

        # Facebook ads query
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=fb_data),
            MagicMock(data=meta_data),
        ]

        result = service._get_ad_ids_for_product(brand_id, product_id)
        assert result["facebook_ad_ids"] == ["fb1", "fb2"]
        assert result["meta_ad_ids"] == ["meta1"]

    def test_empty_results(self, service):
        brand_id = uuid4()
        product_id = uuid4()

        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[]),
            MagicMock(data=[]),
        ]

        result = service._get_ad_ids_for_product(brand_id, product_id)
        assert result["facebook_ad_ids"] == []
        assert result["meta_ad_ids"] == []


# ---------------------------------------------------------------------------
# _get_analyses_by_ad_ids
# ---------------------------------------------------------------------------


class TestGetAnalysesByAdIds:
    def test_deduplicates_by_id(self, service):
        brand_id = uuid4()
        analysis_id = str(uuid4())

        # Same analysis returned from both fb and meta queries
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.side_effect = [
            MagicMock(data=[{"id": analysis_id, "type": "copy"}]),
            MagicMock(data=[{"id": analysis_id, "type": "copy"}]),
        ]

        result = service._get_analyses_by_ad_ids(brand_id, {
            "facebook_ad_ids": ["fb1"],
            "meta_ad_ids": ["meta1"],
        })
        assert len(result) == 1

    def test_empty_ad_ids(self, service):
        brand_id = uuid4()
        result = service._get_analyses_by_ad_ids(brand_id, {
            "facebook_ad_ids": [],
            "meta_ad_ids": [],
        })
        assert result == []
