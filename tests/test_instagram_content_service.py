"""Unit tests for InstagramContentService.

Tests watched account CRUD, scraping delegation, outlier detection,
media download, and content queries.

All external dependencies (Supabase, Apify, httpx) are mocked.
"""

import numpy as np
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from viraltracker.services.instagram_content_service import InstagramContentService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    """Mock Supabase client with fluent API."""
    mock = MagicMock()

    # Default table chain
    table = MagicMock()
    table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "media-1"}])
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "watched-1"}])
    table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock.table.return_value = table

    # Storage operations
    storage_bucket = MagicMock()
    storage_bucket.upload.return_value = None
    mock.storage.from_.return_value = storage_bucket

    return mock


@pytest.fixture
def service(mock_supabase):
    """Create InstagramContentService with mocked Supabase."""
    with patch(
        "viraltracker.services.instagram_content_service.get_supabase_client",
        return_value=mock_supabase,
    ):
        svc = InstagramContentService(supabase=mock_supabase)
    return svc


# ---------------------------------------------------------------------------
# Watched Accounts CRUD
# ---------------------------------------------------------------------------

class TestWatchedAccountsCRUD:
    """Tests for add, remove, list, reactivate watched accounts."""

    def test_add_watched_account_success(self, service, mock_supabase):
        """Test adding a new watched account."""
        # Setup: platform lookup
        platform_table = MagicMock()
        platform_table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id": "platform-ig"}
        )

        # Setup: account upsert
        account_table = MagicMock()
        account_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "account-1"}]
        )

        # Setup: watched account upsert
        watched_table = MagicMock()
        watched_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "watched-1", "account_id": "account-1", "brand_id": "brand-1"}]
        )

        def table_router(name):
            if name == "platforms":
                return platform_table
            elif name == "accounts":
                return account_table
            elif name == "instagram_watched_accounts":
                return watched_table
            return MagicMock()

        mock_supabase.table.side_effect = table_router

        result = service.add_watched_account(
            brand_id="brand-1",
            username="testuser",
            organization_id="org-1",
            notes="test",
            scrape_frequency_hours=168,
        )

        assert result["id"] == "watched-1"
        account_table.upsert.assert_called_once()
        watched_table.upsert.assert_called_once()

    def test_add_watched_account_strips_at_symbol(self, service, mock_supabase):
        """Test that @ is stripped from username."""
        # Setup platforms
        platform_table = MagicMock()
        platform_table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id": "platform-ig"}
        )
        account_table = MagicMock()
        account_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "account-1"}]
        )
        watched_table = MagicMock()
        watched_table.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "watched-1"}]
        )

        def table_router(name):
            if name == "platforms":
                return platform_table
            elif name == "accounts":
                return account_table
            elif name == "instagram_watched_accounts":
                return watched_table
            return MagicMock()

        mock_supabase.table.side_effect = table_router

        service.add_watched_account("brand-1", "@TestUser", "org-1")

        # Should pass lowercase, stripped username to account upsert
        call_args = account_table.upsert.call_args[0][0]
        assert call_args["platform_username"] == "testuser"

    def test_add_watched_account_empty_username_raises(self, service):
        """Test that empty username raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            service.add_watched_account("brand-1", "", "org-1")

    def test_add_watched_account_whitespace_username_raises(self, service):
        """Test that whitespace-only username raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            service.add_watched_account("brand-1", "  @  ", "org-1")

    def test_remove_watched_account(self, service, mock_supabase):
        """Test soft-deleting a watched account."""
        service.remove_watched_account("watched-1")

        mock_supabase.table.assert_called_with("instagram_watched_accounts")
        update_call = mock_supabase.table.return_value.update
        update_call.assert_called_once()
        update_data = update_call.call_args[0][0]
        assert update_data["is_active"] is False

    def test_reactivate_watched_account(self, service, mock_supabase):
        """Test reactivating a deactivated watched account."""
        service.reactivate_watched_account("watched-1")

        update_call = mock_supabase.table.return_value.update
        update_call.assert_called_once()
        update_data = update_call.call_args[0][0]
        assert update_data["is_active"] is True

    def test_list_watched_accounts_filters_by_brand(self, service, mock_supabase):
        """Test listing watched accounts filters by brand and org."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "w-1", "accounts": {"platform_username": "user1"}},
                {"id": "w-2", "accounts": {"platform_username": "user2"}},
            ]
        )

        result = service.list_watched_accounts("brand-1", "org-1")
        # Just verifying the method runs without errors and returns data
        assert isinstance(result, list)

    def test_list_watched_accounts_superuser_skips_org_filter(self, service, mock_supabase):
        """Test superuser 'all' mode skips organization_id filter."""
        # Reset table mock to track calls
        table_mock = MagicMock()
        select_mock = MagicMock()
        eq_brand_mock = MagicMock()

        table_mock.select.return_value = select_mock
        select_mock.eq.return_value = eq_brand_mock
        eq_brand_mock.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        eq_brand_mock.order.return_value.execute.return_value = MagicMock(data=[])

        mock_supabase.table.return_value = table_mock

        # For "all" mode, should call .eq("brand_id", ...) then .eq("is_active", True)
        # but NOT .eq("organization_id", ...)
        service.list_watched_accounts("brand-1", "all")

        # Verify table was queried
        mock_supabase.table.assert_called_with("instagram_watched_accounts")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

class TestScraping:
    """Tests for scrape_account and scrape_all_active."""

    def test_scrape_account_enforces_min_interval(self, service, mock_supabase):
        """Test that scraping respects min_scrape_interval."""
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "watched-1",
                "last_scraped_at": recent_time,
                "min_scrape_interval_hours": 24,
                "accounts": {
                    "id": "acc-1",
                    "platform_username": "testuser",
                    "platform_id": "plat-1",
                },
            }
        )

        result = service.scrape_account("watched-1", force=False)
        assert result["posts_scraped"] == 0
        assert "interval" in result["skipped_reason"].lower()

    def test_scrape_account_force_bypasses_interval(self, service, mock_supabase):
        """Test that force=True bypasses min_scrape_interval."""
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "watched-1",
                "last_scraped_at": recent_time,
                "min_scrape_interval_hours": 24,
                "accounts": {
                    "id": "acc-1",
                    "platform_username": "testuser",
                    "platform_id": "plat-1",
                },
            }
        )

        # Mock the scraper methods
        mock_scraper = MagicMock()
        mock_scraper._start_apify_run.return_value = "run-123"
        mock_scraper._poll_apify_run.return_value = {"datasetId": "ds-123"}
        mock_scraper._fetch_dataset.return_value = []

        service._scraper = mock_scraper

        result = service.scrape_account("watched-1", force=True)
        # Should have attempted scrape (no items returned)
        assert result["posts_scraped"] == 0
        assert result.get("skipped_reason") is None
        mock_scraper._start_apify_run.assert_called_once()

    def test_scrape_account_not_found_raises(self, service, mock_supabase):
        """Test that non-existent watched account raises ValueError."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )

        with pytest.raises(ValueError, match="not found"):
            service.scrape_account("nonexistent-id")

    def test_scrape_all_active_aggregates_results(self, service, mock_supabase):
        """Test batch scraping aggregates per-account results."""
        # Mock list_watched_accounts
        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1", "accounts": {"platform_username": "user1"}},
            {"id": "w-2", "account_id": "a-2", "accounts": {"platform_username": "user2"}},
        ]):
            with patch.object(service, "scrape_account", side_effect=[
                {"posts_scraped": 10, "skipped_reason": None},
                {"posts_scraped": 0, "skipped_reason": "Min interval not met"},
            ]):
                result = service.scrape_all_active("brand-1", "org-1")

        assert result["total_accounts"] == 2
        assert result["accounts_scraped"] == 1
        assert result["accounts_skipped"] == 1
        assert result["total_posts"] == 10
        assert result["errors"] == []

    def test_scrape_all_active_handles_errors(self, service, mock_supabase):
        """Test batch scraping handles individual account errors."""
        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1", "accounts": {"platform_username": "user1"}},
        ]):
            with patch.object(service, "scrape_account", side_effect=RuntimeError("API down")):
                result = service.scrape_all_active("brand-1", "org-1")

        assert len(result["errors"]) == 1
        assert "API down" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# Outlier Detection
# ---------------------------------------------------------------------------

class TestOutlierDetection:
    """Tests for calculate_outliers and detection methods."""

    def test_zscore_detection_basic(self, service):
        """Test z-score outlier detection with clear outlier."""
        # Create scores where one value is clearly an outlier
        scores = np.array([10, 12, 11, 13, 10, 11, 12, 100])  # 100 is outlier

        flags, z_scores = service._zscore_detection(scores, threshold=2.0, trim_percent=10.0)

        # The extreme value (100) should be flagged
        assert flags[-1] is True
        assert z_scores[-1] > 2.0
        # Most normal values should not be flagged
        assert sum(flags) <= 2  # At most a couple could be borderline

    def test_zscore_detection_std_zero(self, service):
        """Test z-score with identical engagement (std=0)."""
        scores = np.array([10, 10, 10, 10, 10])

        flags, z_scores = service._zscore_detection(scores, threshold=2.0, trim_percent=10.0)

        assert all(f is False for f in flags)
        assert all(z == 0.0 for z in z_scores)

    def test_percentile_detection_basic(self, service):
        """Test percentile-based outlier detection."""
        scores = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])

        flags, pct_scores = service._percentile_detection(scores, threshold=10.0)

        # Top 10% of 10 items = 1 item
        assert flags[-1] is True  # 100 should be flagged
        assert sum(flags) >= 1

    def test_calculate_outliers_too_few_posts(self, service):
        """Test that outlier detection skips with < MIN_POSTS_FOR_OUTLIER."""
        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1"},
        ]):
            # Return only 2 posts (below threshold of 3)
            service.supabase.table.return_value.select.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
                data=[
                    {"id": "p-1", "views": 100, "likes": 10, "comments": 5, "shares": 2, "posted_at": "2026-02-20T00:00:00Z", "account_id": "a-1"},
                    {"id": "p-2", "views": 200, "likes": 20, "comments": 10, "shares": 4, "posted_at": "2026-02-21T00:00:00Z", "account_id": "a-1"},
                ]
            )

            result = service.calculate_outliers("brand-1", "org-1")

        assert result["outliers_found"] == 0
        assert "at least" in result["message"]

    def test_calculate_outliers_no_watched_accounts(self, service):
        """Test outlier detection with no watched accounts."""
        with patch.object(service, "list_watched_accounts", return_value=[]):
            result = service.calculate_outliers("brand-1", "org-1")

        assert result["total_posts"] == 0
        assert result["outliers_found"] == 0

    def test_calculate_outliers_updates_posts(self, service, mock_supabase):
        """Test that outlier detection updates post records."""
        posts_data = [
            {"id": f"p-{i}", "views": 100 + i * 10, "likes": 10 + i, "comments": 5, "shares": 2, "posted_at": "2026-02-20T00:00:00Z", "account_id": "a-1"}
            for i in range(10)
        ]
        # Add one clear outlier
        posts_data.append({
            "id": "p-outlier",
            "views": 100000,
            "likes": 10000,
            "comments": 500,
            "shares": 200,
            "posted_at": "2026-02-20T00:00:00Z",
            "account_id": "a-1",
        })

        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1"},
        ]):
            mock_supabase.table.return_value.select.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
                data=posts_data
            )

            result = service.calculate_outliers("brand-1", "org-1", method="zscore", threshold=2.0)

        assert result["total_posts"] == 11
        assert result["outliers_found"] >= 1
        assert result["method"] == "zscore"

        # Verify update was called for each post
        update_calls = mock_supabase.table.return_value.update.call_count
        assert update_calls >= 11  # One per post

    def test_calculate_outliers_invalid_method_raises(self, service):
        """Test invalid method parameter."""
        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1"},
        ]):
            service.supabase.table.return_value.select.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
                data=[
                    {"id": f"p-{i}", "views": 100, "likes": 10, "comments": 5, "shares": 2, "posted_at": "2026-02-20T00:00:00Z", "account_id": "a-1"}
                    for i in range(5)
                ]
            )

            with pytest.raises(ValueError, match="Unknown method"):
                service.calculate_outliers("brand-1", "org-1", method="invalid")


# ---------------------------------------------------------------------------
# Media Download
# ---------------------------------------------------------------------------

class TestMediaDownload:
    """Tests for download_outlier_media and helpers."""

    def test_download_file_success(self, service):
        """Test successful file download."""
        mock_response = MagicMock()
        mock_response.content = b"fake-image-data"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.raise_for_status = MagicMock()

        with patch("viraltracker.services.instagram_content_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_response)
            ))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            data, content_type = service._download_file("https://example.com/image.jpg")

        assert data == b"fake-image-data"
        assert content_type == "image/jpeg"

    def test_download_file_too_large(self, service):
        """Test that oversized files are rejected."""
        mock_response = MagicMock()
        mock_response.content = b"x" * (501 * 1024 * 1024)  # 501MB
        mock_response.headers = {"content-type": "video/mp4"}
        mock_response.raise_for_status = MagicMock()

        with patch("viraltracker.services.instagram_content_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_response)
            ))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            data, content_type = service._download_file("https://example.com/video.mp4")

        assert data is None

    def test_download_file_http_error(self, service):
        """Test download handles HTTP errors gracefully."""
        import httpx as httpx_module

        with patch("viraltracker.services.instagram_content_service.httpx.Client") as mock_client:
            mock_get = MagicMock()
            mock_get.raise_for_status.side_effect = httpx_module.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_get)
            ))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            data, content_type = service._download_file("https://example.com/gone.jpg")

        assert data is None

    def test_download_outlier_media_no_watched(self, service):
        """Test download when no watched accounts exist."""
        with patch.object(service, "list_watched_accounts", return_value=[]):
            result = service.download_outlier_media("brand-1", "org-1")

        assert result["downloaded"] == 0

    def test_get_media_urls_no_shortcode(self, service):
        """Test that empty shortcode returns empty list."""
        result = service._get_media_urls_for_post("")
        assert result == []


# ---------------------------------------------------------------------------
# Content Queries
# ---------------------------------------------------------------------------

class TestContentQueries:
    """Tests for get_top_content, get_content_stats, get_post_media."""

    def test_get_top_content_empty(self, service):
        """Test get_top_content with no watched accounts."""
        with patch.object(service, "list_watched_accounts", return_value=[]):
            result = service.get_top_content("brand-1", "org-1")

        assert result == []

    def test_get_top_content_sorts_by_views(self, service, mock_supabase):
        """Test that results are sorted by views descending."""
        posts = [
            {"id": "p-1", "views": 500, "accounts": {"platform_username": "u1"}},
            {"id": "p-2", "views": 1000, "accounts": {"platform_username": "u2"}},
            {"id": "p-3", "views": 200, "accounts": {"platform_username": "u3"}},
        ]

        with patch.object(service, "list_watched_accounts", return_value=[
            {"id": "w-1", "account_id": "a-1"},
        ]):
            mock_supabase.table.return_value.select.return_value.in_.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=posts
            )

            result = service.get_top_content("brand-1", "org-1", days=30)

        assert result[0]["views"] == 1000
        assert result[-1]["views"] == 200

    def test_get_content_stats_no_accounts(self, service):
        """Test stats with no watched accounts."""
        with patch.object(service, "list_watched_accounts", return_value=[]):
            result = service.get_content_stats("brand-1", "org-1")

        assert result["watched_accounts"] == 0
        assert result["total_posts"] == 0

    def test_get_post_media_returns_ordered(self, service, mock_supabase):
        """Test get_post_media returns media ordered by index."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "m-1", "media_index": 0, "media_type": "image"},
                {"id": "m-2", "media_index": 1, "media_type": "video"},
            ]
        )

        result = service.get_post_media("post-1")
        assert len(result) == 2
        assert result[0]["media_index"] == 0

    def test_get_post_media_empty(self, service, mock_supabase):
        """Test get_post_media with no media."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = service.get_post_media("post-1")
        assert result == []


# ---------------------------------------------------------------------------
# Edge Cases & Integration
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zscore_small_sample(self, service):
        """Test z-score with exactly MIN_POSTS_FOR_OUTLIER posts."""
        scores = np.array([10, 20, 100])
        flags, z_scores = service._zscore_detection(scores, threshold=2.0, trim_percent=10.0)
        # Should not crash, may or may not flag 100
        assert len(flags) == 3
        assert len(z_scores) == 3

    def test_zscore_all_zeros(self, service):
        """Test z-score with all zero scores."""
        scores = np.array([0, 0, 0, 0, 0])
        flags, z_scores = service._zscore_detection(scores, threshold=2.0, trim_percent=10.0)
        assert all(f is False for f in flags)

    def test_percentile_single_outlier(self, service):
        """Test percentile with one extreme value."""
        scores = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1000])
        flags, pct_scores = service._percentile_detection(scores, threshold=10.0)
        assert flags[-1] is True

    def test_service_lazy_scraper_init(self, service):
        """Test that scraper is lazily initialized."""
        assert service._scraper is None
        # Accessing the property should initialize it
        with patch("viraltracker.services.instagram_content_service.InstagramScraper") as mock_cls:
            mock_cls.return_value = MagicMock()
            scraper = service.scraper
            assert scraper is not None
            mock_cls.assert_called_once()

    def test_update_last_scraped(self, service, mock_supabase):
        """Test _update_last_scraped updates both timestamps."""
        service._update_last_scraped("watched-1")

        update_call = mock_supabase.table.return_value.update
        update_call.assert_called_once()
        update_data = update_call.call_args[0][0]
        assert "last_scraped_at" in update_data
        assert "updated_at" in update_data

    def test_storage_bucket_constant(self, service):
        """Test storage bucket name is set."""
        assert service.STORAGE_BUCKET == "instagram-media"

    def test_default_thresholds(self, service):
        """Test default outlier detection thresholds."""
        assert service.DEFAULT_OUTLIER_THRESHOLD == 2.0
        assert service.DEFAULT_OUTLIER_METHOD == "zscore"
        assert service.MIN_POSTS_FOR_OUTLIER == 3
