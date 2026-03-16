"""
Tests for AdPerformanceQueryService._aggregate_by_ad — thumbnail_url passthrough.
"""

import pytest
from unittest.mock import MagicMock

from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService


@pytest.fixture
def service():
    """Create service with a mocked Supabase client."""
    mock_supabase = MagicMock()
    return AdPerformanceQueryService(mock_supabase)


def _make_row(
    meta_ad_id: str = "ad-1",
    ad_name: str = "Test Ad",
    spend: float = 10.0,
    impressions: int = 100,
    link_clicks: int = 5,
    thumbnail_url: str = "",
    **overrides,
) -> dict:
    """Build a daily performance row dict with sensible defaults."""
    row = {
        "meta_ad_id": meta_ad_id,
        "ad_name": ad_name,
        "ad_status": "ACTIVE",
        "adset_name": "Adset 1",
        "campaign_name": "Campaign 1",
        "meta_adset_id": "adset-1",
        "meta_campaign_id": "campaign-1",
        "thumbnail_url": thumbnail_url,
        "spend": spend,
        "impressions": impressions,
        "link_clicks": link_clicks,
        "add_to_carts": 0,
        "purchases": 0,
        "purchase_value": 0,
        "reach": impressions,
    }
    row.update(overrides)
    return row


class TestAggregateByAdThumbnailPassthrough:
    """Tests that _aggregate_by_ad correctly passes through thumbnail_url."""

    def test_thumbnail_from_first_non_empty_row(self, service):
        """When multiple daily rows exist for the same ad, the first non-empty
        thumbnail_url should be kept (rows are ordered date-desc so the most
        recent comes first)."""
        rows = [
            _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/thumb_recent.jpg"),
            _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/thumb_older.jpg"),
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
        ]

        result = service._aggregate_by_ad(rows)

        assert len(result) == 1
        assert result[0]["thumbnail_url"] == "https://cdn.example.com/thumb_recent.jpg"

    def test_thumbnail_skips_empty_rows_before_populated(self, service):
        """If the first row has no thumbnail but a later row does, the first
        non-empty value is used."""
        rows = [
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
            _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/thumb_found.jpg"),
        ]

        result = service._aggregate_by_ad(rows)

        assert len(result) == 1
        assert result[0]["thumbnail_url"] == "https://cdn.example.com/thumb_found.jpg"

    def test_no_thumbnail_yields_empty_string(self, service):
        """An ad where no row has a thumbnail_url should get an empty string."""
        rows = [
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
        ]

        result = service._aggregate_by_ad(rows)

        assert len(result) == 1
        assert result[0]["thumbnail_url"] == ""

    def test_thumbnail_none_treated_as_empty(self, service):
        """Rows with thumbnail_url=None should be skipped just like empty strings."""
        rows = [
            _make_row(meta_ad_id="ad-1", thumbnail_url=None),
            _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/thumb.jpg"),
        ]

        result = service._aggregate_by_ad(rows)

        assert len(result) == 1
        assert result[0]["thumbnail_url"] == "https://cdn.example.com/thumb.jpg"

    def test_multiple_ads_each_get_own_thumbnail(self, service):
        """Two different ads should each independently resolve their thumbnail."""
        rows = [
            _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/thumb_a.jpg"),
            _make_row(meta_ad_id="ad-1", thumbnail_url=""),
            _make_row(meta_ad_id="ad-2", ad_name="Ad Two", thumbnail_url=""),
            _make_row(meta_ad_id="ad-2", ad_name="Ad Two", thumbnail_url="https://cdn.example.com/thumb_b.jpg"),
        ]

        result = service._aggregate_by_ad(rows)

        by_id = {r["meta_ad_id"]: r for r in result}
        assert by_id["ad-1"]["thumbnail_url"] == "https://cdn.example.com/thumb_a.jpg"
        assert by_id["ad-2"]["thumbnail_url"] == "https://cdn.example.com/thumb_b.jpg"

    def test_thumbnail_missing_key_treated_as_empty(self, service):
        """Rows that lack the thumbnail_url key entirely should not break aggregation."""
        row_without_key = {
            "meta_ad_id": "ad-1",
            "ad_name": "Test Ad",
            "ad_status": "ACTIVE",
            "adset_name": "Adset 1",
            "campaign_name": "Campaign 1",
            "meta_adset_id": "adset-1",
            "meta_campaign_id": "campaign-1",
            "spend": 10.0,
            "impressions": 100,
            "link_clicks": 5,
            "add_to_carts": 0,
            "purchases": 0,
            "purchase_value": 0,
            "reach": 100,
            # thumbnail_url intentionally omitted
        }
        row_with_url = _make_row(meta_ad_id="ad-1", thumbnail_url="https://cdn.example.com/found.jpg")

        result = service._aggregate_by_ad([row_without_key, row_with_url])

        assert len(result) == 1
        assert result[0]["thumbnail_url"] == "https://cdn.example.com/found.jpg"
