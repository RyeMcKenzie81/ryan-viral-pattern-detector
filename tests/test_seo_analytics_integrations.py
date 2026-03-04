"""
Tests for SEO Pipeline Analytics Integrations (Phase 3).

Covers:
- normalize_url_path() edge cases
- BaseAnalyticsService: URL matching, batch upserts
- GSCService: OAuth state encoding/decoding, sync_to_db
- GA4Service: sync_to_db
- ShopifyAnalyticsService: sync_to_db, graceful degradation
"""

import pytest
from unittest.mock import MagicMock, patch

from viraltracker.services.seo_pipeline.utils import normalize_url_path
from viraltracker.services.seo_pipeline.services.base_analytics_service import (
    BaseAnalyticsService,
    UPSERT_BATCH_SIZE,
)
from viraltracker.services.seo_pipeline.services.gsc_service import GSCService
from viraltracker.services.seo_pipeline.services.ga4_service import GA4Service
from viraltracker.services.seo_pipeline.services.shopify_analytics_service import (
    ShopifyAnalyticsService,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_supabase():
    return MagicMock()


@pytest.fixture
def base_service(mock_supabase):
    return BaseAnalyticsService(supabase_client=mock_supabase)


@pytest.fixture
def gsc_service(mock_supabase):
    return GSCService(supabase_client=mock_supabase)


@pytest.fixture
def ga4_service(mock_supabase):
    return GA4Service(supabase_client=mock_supabase)


@pytest.fixture
def shopify_service(mock_supabase):
    return ShopifyAnalyticsService(supabase_client=mock_supabase)


# =============================================================================
# normalize_url_path TESTS
# =============================================================================

class TestNormalizeUrlPath:
    """Test URL normalization utility."""

    def test_full_url_strips_domain_and_params(self):
        assert normalize_url_path("https://example.com/blogs/news/my-article?ref=fb") == "/blogs/news/my-article"

    def test_strips_trailing_slash(self):
        assert normalize_url_path("https://example.com/blogs/news/my-article/") == "/blogs/news/my-article"

    def test_lowercases(self):
        assert normalize_url_path("https://EXAMPLE.COM/Blogs/News/My-Article") == "/blogs/news/my-article"

    def test_url_decodes(self):
        assert normalize_url_path("/blogs/news/my%20article") == "/blogs/news/my article"

    def test_strips_fragment(self):
        assert normalize_url_path("https://example.com/blogs/news/article#section") == "/blogs/news/article"

    def test_preserves_root_slash(self):
        assert normalize_url_path("/") == "/"

    def test_empty_string(self):
        assert normalize_url_path("") == ""

    def test_path_only(self):
        assert normalize_url_path("/blogs/news/article") == "/blogs/news/article"

    def test_www_prefix_stripped(self):
        assert normalize_url_path("https://www.example.com/blogs/news/article") == "/blogs/news/article"

    def test_multiple_trailing_slashes(self):
        assert normalize_url_path("/blogs/news/article///") == "/blogs/news/article"

    def test_encoded_slash(self):
        assert normalize_url_path("/blogs/news/my%2Farticle") == "/blogs/news/my/article"


# =============================================================================
# BaseAnalyticsService TESTS
# =============================================================================

class TestBaseAnalyticsServiceConfig:
    """Test integration config loading."""

    def test_load_integration_config_found(self, base_service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"config": {"site_url": "https://example.com", "access_token": "tok"}}
        ]
        result = base_service._load_integration_config("brand-1", "org-1", "gsc")
        assert result == {"site_url": "https://example.com", "access_token": "tok"}

    def test_load_integration_config_not_found(self, base_service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = base_service._load_integration_config("brand-1", "org-1", "gsc")
        assert result is None


class TestBaseAnalyticsServiceUrlMatching:
    """Test URL matching against articles."""

    def test_matches_urls_to_articles(self, base_service, mock_supabase):
        # Mock articles
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "art-1", "published_url": "https://example.com/blogs/news/article-1", "keyword": "kw1"},
            {"id": "art-2", "published_url": "https://example.com/blogs/news/article-2", "keyword": "kw2"},
        ]

        url_pairs = [
            ("https://example.com/blogs/news/article-1", {"date": "2026-03-01", "clicks": 10}),
            ("https://example.com/blogs/news/unknown", {"date": "2026-03-01", "clicks": 5}),
        ]

        matched = base_service._match_urls_to_articles("brand-1", url_pairs)
        assert len(matched) == 1
        assert matched[0]["article_id"] == "art-1"
        assert matched[0]["clicks"] == 10

    def test_matches_path_only_to_full_url(self, base_service, mock_supabase):
        """GA4 sends paths, articles have full URLs — should still match."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "art-1", "published_url": "https://example.com/blogs/news/article-1", "keyword": "kw1"},
        ]

        url_pairs = [
            ("/blogs/news/article-1", {"date": "2026-03-01", "sessions": 50}),
        ]

        matched = base_service._match_urls_to_articles("brand-1", url_pairs)
        assert len(matched) == 1
        assert matched[0]["article_id"] == "art-1"

    def test_empty_pairs_returns_empty(self, base_service):
        result = base_service._match_urls_to_articles("brand-1", [])
        assert result == []


class TestBaseAnalyticsServiceBatchUpserts:
    """Test batch upsert operations."""

    def test_batch_upsert_analytics(self, base_service, mock_supabase):
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        rows = [
            {"article_id": "art-1", "organization_id": "org-1", "date": "2026-03-01", "clicks": 10},
            {"article_id": "art-2", "organization_id": "org-1", "date": "2026-03-01", "clicks": 20},
        ]

        count = base_service._batch_upsert_analytics(rows, "gsc")
        assert count == 2
        assert rows[0]["source"] == "gsc"
        assert rows[1]["source"] == "gsc"

    def test_batch_upsert_empty_returns_zero(self, base_service):
        assert base_service._batch_upsert_analytics([], "gsc") == 0

    def test_batch_upsert_rankings(self, base_service, mock_supabase):
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

        rows = [
            {"article_id": "art-1", "keyword": "test", "position": 5, "checked_at": "2026-03-01T00:00:00Z"},
        ]

        count = base_service._batch_upsert_rankings(rows, "gsc")
        assert count == 1
        assert rows[0]["source"] == "gsc"

    def test_batch_upsert_analytics_handles_error(self, base_service, mock_supabase):
        mock_supabase.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")

        rows = [{"article_id": "art-1", "organization_id": "org-1", "date": "2026-03-01"}]
        count = base_service._batch_upsert_analytics(rows, "gsc")
        assert count == 0


# =============================================================================
# GSCService TESTS
# =============================================================================

class TestGSCOAuthState:
    """Test OAuth state encoding/decoding."""

    def test_encode_decode_roundtrip(self):
        state = GSCService.encode_oauth_state("brand-1", "org-1", "nonce-abc")
        decoded = GSCService.decode_oauth_state(state)
        assert decoded["brand_id"] == "brand-1"
        assert decoded["org_id"] == "org-1"
        assert decoded["nonce"] == "nonce-abc"

    def test_state_is_base64(self):
        state = GSCService.encode_oauth_state("brand-1", "org-1", "nonce-abc")
        # Should be valid base64 (no exceptions)
        import base64
        decoded_bytes = base64.urlsafe_b64decode(state.encode())
        assert b"brand-1" in decoded_bytes


class TestGSCTokenRefresh:
    """Test token refresh logic."""

    def test_valid_token_not_refreshed(self, gsc_service):
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        config = {"access_token": "valid", "token_expiry": future}

        result = gsc_service._get_credentials(config)
        assert result == config  # Returns unchanged

    def test_expired_token_refreshes(self, gsc_service):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        config = {
            "access_token": "expired",
            "refresh_token": "refresh-tok",
            "token_expiry": past,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new-tok", "expires_in": 3600}

        with patch.dict("os.environ", {"GOOGLE_OAUTH_CLIENT_ID": "cid", "GOOGLE_OAUTH_CLIENT_SECRET": "csec"}):
            with patch("httpx.Client") as mock_client:
                mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
                mock_client.return_value.__exit__ = MagicMock(return_value=False)

                result = gsc_service._get_credentials(config)
                assert result["access_token"] == "new-tok"

    def test_no_refresh_token_returns_none(self, gsc_service):
        past = "2020-01-01T00:00:00+00:00"
        config = {"access_token": "expired", "token_expiry": past}

        result = gsc_service._get_credentials(config)
        assert result is None


class TestGSCSyncToDb:
    """Test GSC sync_to_db aggregation logic."""

    def test_sync_empty_data(self, gsc_service):
        with patch.object(gsc_service, "fetch_search_performance", return_value=[]):
            result = gsc_service.sync_to_db("brand-1", "org-1")
            assert result == {"analytics_rows": 0, "ranking_rows": 0}

    def test_sync_aggregates_by_page_date(self, gsc_service):
        raw_rows = [
            {"keys": ["https://example.com/blog/a", "keyword1", "2026-03-01"], "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 3.5},
            {"keys": ["https://example.com/blog/a", "keyword2", "2026-03-01"], "clicks": 3, "impressions": 50, "ctr": 0.06, "position": 7.0},
        ]

        with patch.object(gsc_service, "fetch_search_performance", return_value=raw_rows):
            with patch.object(gsc_service, "_match_urls_to_articles", return_value=[]) as mock_match:
                with patch.object(gsc_service, "_batch_upsert_analytics", return_value=0):
                    with patch.object(gsc_service, "_batch_upsert_rankings", return_value=0):
                        gsc_service.sync_to_db("brand-1", "org-1")

                        # Check analytics pairs: should be 1 aggregated row for same page+date
                        analytics_call = mock_match.call_args_list[0]
                        analytics_pairs = analytics_call[0][1]
                        assert len(analytics_pairs) == 1
                        _, data = analytics_pairs[0]
                        assert data["clicks"] == 8  # 5 + 3
                        assert data["impressions"] == 150  # 100 + 50
                        # average_position should be weighted avg: (3.5 + 7.0) / 2 = 5.25 → 5.2
                        assert data["average_position"] == 5.2

                        # Check ranking pairs: should be 2 individual rows
                        ranking_call = mock_match.call_args_list[1]
                        ranking_pairs = ranking_call[0][1]
                        assert len(ranking_pairs) == 2


# =============================================================================
# GA4Service TESTS
# =============================================================================

class TestGA4SyncToDb:
    """Test GA4 sync_to_db logic."""

    def test_sync_empty_data(self, ga4_service):
        with patch.object(ga4_service, "fetch_page_analytics", return_value=[]):
            result = ga4_service.sync_to_db("brand-1", "org-1")
            assert result == {"analytics_rows": 0}

    def test_sync_maps_ga4_fields(self, ga4_service):
        ga4_rows = [
            {"page_path": "/blogs/news/article-1", "date": "2026-03-01", "sessions": 100, "pageviews": 150, "avg_time_on_page": 45.5, "bounce_rate": 0.35},
        ]

        with patch.object(ga4_service, "fetch_page_analytics", return_value=ga4_rows):
            with patch.object(ga4_service, "_match_urls_to_articles", return_value=[]) as mock_match:
                with patch.object(ga4_service, "_batch_upsert_analytics", return_value=0):
                    ga4_service.sync_to_db("brand-1", "org-1")

                    url_pairs = mock_match.call_args[0][1]
                    assert len(url_pairs) == 1
                    url, data = url_pairs[0]
                    assert url == "/blogs/news/article-1"
                    assert data["sessions"] == 100
                    assert data["pageviews"] == 150
                    assert data["bounce_rate"] == 0.35


# =============================================================================
# ShopifyAnalyticsService TESTS
# =============================================================================

class TestShopifySyncToDb:
    """Test Shopify sync_to_db logic."""

    def test_sync_graceful_degradation(self, shopify_service):
        """When Shopify analytics unavailable, returns zero count."""
        with patch.object(shopify_service, "fetch_blog_conversions", side_effect=Exception("Not configured")):
            result = shopify_service.sync_to_db("brand-1", "org-1")
            assert result == {"analytics_rows": 0}

    def test_sync_empty_conversions(self, shopify_service):
        with patch.object(shopify_service, "fetch_blog_conversions", return_value=[]):
            result = shopify_service.sync_to_db("brand-1", "org-1")
            assert result == {"analytics_rows": 0}

    def test_sync_maps_conversion_fields(self, shopify_service):
        conversion_rows = [
            {"page_path": "/blogs/news/article-1", "date": "2026-03-01", "conversions": 3, "revenue": 149.97},
        ]

        with patch.object(shopify_service, "fetch_blog_conversions", return_value=conversion_rows):
            with patch.object(shopify_service, "_match_urls_to_articles", return_value=[]) as mock_match:
                with patch.object(shopify_service, "_batch_upsert_analytics", return_value=0):
                    shopify_service.sync_to_db("brand-1", "org-1")

                    url_pairs = mock_match.call_args[0][1]
                    assert len(url_pairs) == 1
                    url, data = url_pairs[0]
                    assert url == "/blogs/news/article-1"
                    assert data["conversions"] == 3
                    assert data["revenue"] == 149.97


class TestShopifyFetchConversions:
    """Test Shopify blog conversion fetching."""

    def test_filters_blog_landing_pages(self, shopify_service, mock_supabase):
        """Only orders with /blogs/ in landing page are counted."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"config": {"store_domain": "test.myshopify.com", "access_token": "tok"}}
        ]

        graphql_response = {
            "data": {
                "orders": {
                    "edges": [
                        {
                            "cursor": "c1",
                            "node": {
                                "id": "order-1",
                                "name": "#1001",
                                "createdAt": "2026-03-01T10:00:00Z",
                                "totalPriceSet": {"shopMoney": {"amount": "49.99", "currencyCode": "USD"}},
                                "customerJourneySummary": {
                                    "firstVisit": {"landingPage": "/blogs/news/article-1"},
                                    "lastVisit": {"landingPage": "/products/widget"},
                                },
                            },
                        },
                        {
                            "cursor": "c2",
                            "node": {
                                "id": "order-2",
                                "name": "#1002",
                                "createdAt": "2026-03-01T11:00:00Z",
                                "totalPriceSet": {"shopMoney": {"amount": "29.99", "currencyCode": "USD"}},
                                "customerJourneySummary": {
                                    "firstVisit": {"landingPage": "/products/another"},
                                    "lastVisit": {"landingPage": "/products/cart"},
                                },
                            },
                        },
                    ],
                    "pageInfo": {"hasNextPage": False},
                },
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = graphql_response

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_response))
            )
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            results = shopify_service.fetch_blog_conversions("brand-1", "org-1")

        # Only order-1 has a blog landing page
        assert len(results) == 1
        assert results[0]["page_path"] == "/blogs/news/article-1"
        assert results[0]["revenue"] == 49.99
        assert results[0]["conversions"] == 1


# =============================================================================
# LAZY-LOAD PATTERN TEST
# =============================================================================

class TestLazyLoadPattern:
    """Test that services correctly lazy-load supabase."""

    def test_base_service_lazy_loads(self):
        service = BaseAnalyticsService()
        assert service._supabase is None
        # The import happens inside the property, so mock at the source module
        mock_db_module = MagicMock()
        mock_db_module.get_supabase_client.return_value = "mock_client"
        with patch.dict("sys.modules", {"viraltracker.core.database": mock_db_module}):
            client = service.supabase
            assert client == "mock_client"

    def test_injected_client_used(self, mock_supabase):
        service = BaseAnalyticsService(supabase_client=mock_supabase)
        assert service.supabase is mock_supabase
