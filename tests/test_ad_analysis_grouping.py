"""
Unit tests for AdAnalysisService new methods:
- group_meta_ads_by_destination()
- fetch_meta_analyses_for_group()
- synthesize_from_raw_copy()
- _empty_raw_synthesis()

Run with: pytest tests/test_ad_analysis_grouping.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from viraltracker.services.ad_analysis_service import AdAnalysisService


@pytest.fixture
def service():
    """Create service with mocked Supabase client."""
    with patch("viraltracker.services.ad_analysis_service.get_supabase_client") as mock_get:
        mock_supabase = MagicMock()
        mock_get.return_value = mock_supabase
        svc = AdAnalysisService()
        svc.supabase = mock_supabase
        return svc


# ---------------------------------------------------------------------------
# group_meta_ads_by_destination
# ---------------------------------------------------------------------------


class TestGroupMetaAdsByDestination:
    def test_empty_destinations_returns_empty(self, service):
        brand_id = str(uuid4())
        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        result = service.group_meta_ads_by_destination(brand_id)
        assert result == []

    @patch("viraltracker.services.url_canonicalizer.canonicalize_url")
    def test_deduplication_assigns_ad_to_first_url(self, mock_canonicalize, service):
        brand_id = str(uuid4())

        # Ad "ad1" appears in two URLs; should only be counted in first
        mock_canonicalize.side_effect = lambda url: url.split("//")[1] if "//" in url else url

        dest_data = [
            {"id": "1", "meta_ad_id": "ad1", "destination_url": "https://a.com", "canonical_url": "a.com"},
            {"id": "2", "meta_ad_id": "ad1", "destination_url": "https://b.com", "canonical_url": "b.com"},
            {"id": "3", "meta_ad_id": "ad2", "destination_url": "https://a.com", "canonical_url": "a.com"},
        ]

        # Destinations query
        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=dest_data)

        # Performance query (empty)
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(data=[])

        # Ad copy query (empty)
        service.supabase.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        # Analysis query (empty)
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        result = service.group_meta_ads_by_destination(brand_id)

        # ad1 assigned to a.com (first seen), ad2 also to a.com
        # b.com should have 0 ads (ad1 already assigned to a.com), filtered by min_ads=1
        a_group = next((g for g in result if g["canonical_url"] == "a.com"), None)
        assert a_group is not None
        assert a_group["ad_count"] == 2  # ad1 + ad2

    def test_min_ads_filter(self, service):
        brand_id = str(uuid4())

        dest_data = [
            {"id": "1", "meta_ad_id": "ad1", "destination_url": "https://a.com", "canonical_url": "a.com"},
        ]

        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=dest_data)
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        result = service.group_meta_ads_by_destination(brand_id, min_ads=2)
        assert result == []  # Only 1 ad, min is 2

    def test_sorted_by_spend_desc(self, service):
        brand_id = str(uuid4())

        dest_data = [
            {"id": "1", "meta_ad_id": "ad1", "destination_url": "https://a.com", "canonical_url": "a.com"},
            {"id": "2", "meta_ad_id": "ad2", "destination_url": "https://b.com", "canonical_url": "b.com"},
        ]

        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=dest_data)

        # Performance: ad2 has more spend
        perf_data = [
            {"meta_ad_id": "ad1", "spend": 10, "impressions": 100, "purchases": 1, "purchase_roas": 2.0},
            {"meta_ad_id": "ad2", "spend": 50, "impressions": 500, "purchases": 5, "purchase_roas": 3.0},
        ]
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(data=perf_data)

        service.supabase.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        result = service.group_meta_ads_by_destination(brand_id)
        assert len(result) == 2
        assert result[0]["total_spend"] >= result[1]["total_spend"]


# ---------------------------------------------------------------------------
# fetch_meta_analyses_for_group
# ---------------------------------------------------------------------------


class TestFetchMetaAnalysesForGroup:
    def test_structures_analyses_correctly(self, service):
        brand_id = str(uuid4())
        meta_ad_ids = ["meta1", "meta2"]

        analyses = [
            {"id": "a1", "meta_ad_id": "meta1", "analysis_type": "copy_analysis", "raw_response": {"hooks": ["buy now"]}},
            {"id": "a2", "meta_ad_id": "meta2", "analysis_type": "image_vision", "raw_response": {"visual": "bright"}},
        ]
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=analyses)

        result = service.fetch_meta_analyses_for_group(brand_id, meta_ad_ids)
        assert result["analyzed_ads"] == 2
        assert result["ad_count"] == 2
        assert len(result["analyses"]) == 2
        # First should have copy_analysis key
        assert "copy_analysis" in result["analyses"][0]
        # Second should have image_analysis key
        assert "image_analysis" in result["analyses"][1]

    def test_empty_analyses(self, service):
        brand_id = str(uuid4())
        service.supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])

        result = service.fetch_meta_analyses_for_group(brand_id, ["meta1"])
        assert result["analyzed_ads"] == 0
        assert result["analyses"] == []


# ---------------------------------------------------------------------------
# synthesize_from_raw_copy
# ---------------------------------------------------------------------------


class TestSynthesizeFromRawCopy:
    def test_extracts_hooks_from_first_lines(self, service):
        copies = [
            "Buy now and save 50%!\nMore details below.",
            "Limited time offer\nDon't miss out.",
        ]
        result = service.synthesize_from_raw_copy(copies, "https://example.com/sale")
        assert len(result["sample_hooks"]) == 2
        assert "Buy now and save 50%!" in result["sample_hooks"]
        assert "Limited time offer" in result["sample_hooks"]

    def test_empty_copies_returns_empty_synthesis(self, service):
        result = service.synthesize_from_raw_copy([], "https://example.com")
        assert result["_needs_full_analysis"] is True
        assert result["suggested_name"] == "Unnamed Variant"
        assert result["sample_hooks"] == []

    def test_name_from_url(self, service):
        result = service.synthesize_from_raw_copy(
            ["Some copy"], "https://example.com/my-cool-product"
        )
        assert "My Cool Product" in result["suggested_name"]

    def test_limits_hooks_to_five(self, service):
        copies = [f"Hook line {i}\nBody" for i in range(20)]
        result = service.synthesize_from_raw_copy(copies, "https://example.com")
        assert len(result["sample_hooks"]) <= 5

    def test_needs_full_analysis_flag(self, service):
        result = service.synthesize_from_raw_copy(["Copy"], "https://example.com")
        assert result["_needs_full_analysis"] is True


# ---------------------------------------------------------------------------
# _empty_raw_synthesis
# ---------------------------------------------------------------------------


class TestEmptyRawSynthesis:
    def test_has_expected_structure(self, service):
        result = service._empty_raw_synthesis("https://example.com/page")
        assert result["landing_page_url"] == "https://example.com/page"
        assert result["suggested_name"] == "Unnamed Variant"
        assert result["pain_points"] == []
        assert result["desires_goals"] == []
        assert result["benefits"] == []
        assert result["sample_hooks"] == []
        assert result["_needs_full_analysis"] is True
