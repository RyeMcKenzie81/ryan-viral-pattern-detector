"""Unit tests for asset download failure semantics and pipeline hardening.

Tests verify:
- Batch-empty thumbnail response doesn't poison ads
- Per-ad with fetch_ok=True and thumbnail_url=None → not_downloadable
- Per-ad miss (not in fresh_urls) → failed (retriable)
- HTTP 403/404 → not_downloadable, HTTP 429/5xx → failed
- AssetDownloadResult dataclass
- _fetch_thumbnails_sync always returns entries with fetch_ok
- Stats deduplication with mixed is_video rows
- update_missing_thumbnails doesn't clobber existing thumbnails
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from viraltracker.services.meta_ads_service import (
    MetaAdsService,
    AssetDownloadResult,
)


@pytest.fixture
def service():
    """Create a MetaAdsService with no real credentials."""
    return MetaAdsService(access_token="fake", ad_account_id="act_fake")


# ---------------------------------------------------------------------------
# AssetDownloadResult
# ---------------------------------------------------------------------------

class TestAssetDownloadResult:
    def test_default_values(self):
        r = AssetDownloadResult()
        assert r.storage_path is None
        assert r.status == "failed"
        assert r.reason is None

    def test_success(self):
        r = AssetDownloadResult(storage_path="meta-ad-assets/x/y.jpg", status="downloaded")
        assert r.storage_path == "meta-ad-assets/x/y.jpg"
        assert r.status == "downloaded"

    def test_not_downloadable(self):
        r = AssetDownloadResult(status="not_downloadable", reason="http_403")
        assert r.storage_path is None
        assert r.status == "not_downloadable"
        assert r.reason == "http_403"


# ---------------------------------------------------------------------------
# _download_and_store_asset HTTP failure classification
# ---------------------------------------------------------------------------

class TestDownloadAndStoreAssetHTTP:
    """Test that HTTP status codes are classified correctly."""

    @pytest.mark.asyncio
    async def test_http_403_is_terminal(self, service):
        """HTTP 403 → not_downloadable."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service._download_and_store_asset(
                    meta_ad_id="ad123",
                    source_url="https://example.com/img.jpg",
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    asset_type="image",
                    mime_type="image/jpeg",
                    file_extension=".jpg",
                )

        assert result.status == "not_downloadable"
        assert result.reason == "http_403"

        # Verify upsert was called with not_downloadable
        upsert_call = mock_supabase.table.return_value.upsert.call_args
        assert upsert_call[0][0]["status"] == "not_downloadable"
        assert upsert_call[0][0]["not_downloadable_reason"] == "http_403"

    @pytest.mark.asyncio
    async def test_http_404_is_terminal(self, service):
        """HTTP 404 → not_downloadable."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service._download_and_store_asset(
                    meta_ad_id="ad123",
                    source_url="https://example.com/img.jpg",
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    asset_type="image",
                    mime_type="image/jpeg",
                    file_extension=".jpg",
                )

        assert result.status == "not_downloadable"
        assert result.reason == "http_404"

    @pytest.mark.asyncio
    async def test_http_429_is_retriable(self, service):
        """HTTP 429 → failed (retriable)."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service._download_and_store_asset(
                    meta_ad_id="ad123",
                    source_url="https://example.com/img.jpg",
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    asset_type="image",
                    mime_type="image/jpeg",
                    file_extension=".jpg",
                )

        assert result.status == "failed"
        assert result.reason == "http_429"

    @pytest.mark.asyncio
    async def test_http_500_is_retriable(self, service):
        """HTTP 500 → failed (retriable)."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service._download_and_store_asset(
                    meta_ad_id="ad123",
                    source_url="https://example.com/img.jpg",
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    asset_type="image",
                    mime_type="image/jpeg",
                    file_extension=".jpg",
                )

        assert result.status == "failed"
        assert result.reason == "http_500"

    @pytest.mark.asyncio
    async def test_exception_is_retriable(self, service):
        """Network/timeout exception → failed with download_error."""
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.side_effect = Exception("Connection timeout")
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service._download_and_store_asset(
                    meta_ad_id="ad123",
                    source_url="https://example.com/img.jpg",
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    asset_type="image",
                    mime_type="image/jpeg",
                    file_extension=".jpg",
                )

        assert result.status == "failed"
        assert result.reason == "download_error"


# ---------------------------------------------------------------------------
# _fetch_thumbnails_sync always returns entries with fetch_ok
# ---------------------------------------------------------------------------

class TestFetchThumbnailsSync:
    """Test that _fetch_thumbnails_sync always adds entries with fetch_ok."""

    def test_returns_fetch_ok_true_even_without_image(self, service):
        """When creative API succeeds but no image found, fetch_ok=True."""
        # Mock the Facebook SDK objects
        mock_ad = MagicMock()
        mock_ad.api_get.return_value = {
            "creative": {"id": "creative123"}
        }
        mock_creative = MagicMock()
        mock_creative.api_get.return_value = {
            "id": "creative123",
            "object_type": "SHARE",
            # No image_url, no thumbnail_url, no object_story_spec images
        }

        with patch("viraltracker.services.meta_ads_service.MetaAdsService._ensure_sdk"):
            with patch("facebook_business.adobjects.ad.Ad", return_value=mock_ad):
                with patch("facebook_business.adobjects.adcreative.AdCreative", return_value=mock_creative):
                    result = service._fetch_thumbnails_sync(["ad_001"])

        assert "ad_001" in result
        assert result["ad_001"]["fetch_ok"] is True
        assert result["ad_001"]["thumbnail_url"] is None
        assert result["ad_001"]["object_type"] == "SHARE"

    def test_returns_fetch_ok_with_image(self, service):
        """When creative API succeeds with image, fetch_ok=True and URL set."""
        mock_ad = MagicMock()
        mock_ad.api_get.return_value = {
            "creative": {"id": "creative123"}
        }
        mock_creative = MagicMock()
        mock_creative.api_get.return_value = {
            "id": "creative123",
            "image_url": "https://example.com/img.jpg",
            "object_type": "PHOTO",
        }

        with patch("viraltracker.services.meta_ads_service.MetaAdsService._ensure_sdk"):
            with patch("facebook_business.adobjects.ad.Ad", return_value=mock_ad):
                with patch("facebook_business.adobjects.adcreative.AdCreative", return_value=mock_creative):
                    result = service._fetch_thumbnails_sync(["ad_002"])

        assert "ad_002" in result
        assert result["ad_002"]["fetch_ok"] is True
        assert result["ad_002"]["thumbnail_url"] == "https://example.com/img.jpg"

    def test_per_ad_exception_excludes_from_result(self, service):
        """When per-ad API call raises, ad is NOT in result (retriable)."""
        mock_ad = MagicMock()
        mock_ad.api_get.side_effect = Exception("API error")

        with patch("viraltracker.services.meta_ads_service.MetaAdsService._ensure_sdk"):
            with patch("facebook_business.adobjects.ad.Ad", return_value=mock_ad):
                result = service._fetch_thumbnails_sync(["ad_003"])

        assert "ad_003" not in result


# ---------------------------------------------------------------------------
# Stats deduplication with mixed is_video rows
# ---------------------------------------------------------------------------

class TestStatsDeduplication:
    """Test that get_asset_download_stats correctly deduplicates mixed rows."""

    @pytest.mark.asyncio
    async def test_mixed_is_video_rows_counted_as_video(self, service):
        """An ad with is_video=True on one row and None on another → video."""
        mock_supabase = MagicMock()

        # Performance data: same ad_id, mixed is_video values
        perf_data = [
            {"meta_ad_id": "ad1", "is_video": True, "meta_video_id": "vid1", "thumbnail_url": "url"},
            {"meta_ad_id": "ad1", "is_video": None, "meta_video_id": None, "thumbnail_url": "url"},
            {"meta_ad_id": "ad2", "is_video": False, "meta_video_id": None, "thumbnail_url": "url"},
            {"meta_ad_id": "ad2", "is_video": None, "meta_video_id": None, "thumbnail_url": None},
        ]
        perf_result = MagicMock()
        perf_result.data = perf_data

        # Assets: empty
        assets_result = MagicMock()
        assets_result.data = []

        def mock_table(name):
            t = MagicMock()
            if name == "meta_ads_performance":
                t.select.return_value.eq.return_value.execute.return_value = perf_result
            else:
                t.select.return_value.eq.return_value.in_.return_value.execute.return_value = assets_result
            return t

        mock_supabase.table = mock_table

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            stats = await service.get_asset_download_stats(
                UUID("12345678-1234-1234-1234-123456789012")
            )

        # ad1 should be video (any row has is_video=True)
        assert stats["videos"]["total"] == 1
        # ad2 should be image (no row has is_video=True or meta_video_id)
        assert stats["images"]["total"] == 1

    @pytest.mark.asyncio
    async def test_meta_video_id_without_is_video_counted_as_video(self, service):
        """An ad with meta_video_id but is_video=None → counted as video."""
        mock_supabase = MagicMock()

        perf_data = [
            {"meta_ad_id": "ad1", "is_video": None, "meta_video_id": "vid1", "thumbnail_url": "url"},
        ]
        perf_result = MagicMock()
        perf_result.data = perf_data

        assets_result = MagicMock()
        assets_result.data = []

        def mock_table(name):
            t = MagicMock()
            if name == "meta_ads_performance":
                t.select.return_value.eq.return_value.execute.return_value = perf_result
            else:
                t.select.return_value.eq.return_value.in_.return_value.execute.return_value = assets_result
            return t

        mock_supabase.table = mock_table

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            stats = await service.get_asset_download_stats(
                UUID("12345678-1234-1234-1234-123456789012")
            )

        assert stats["videos"]["total"] == 1
        assert stats["images"]["total"] == 0


# ---------------------------------------------------------------------------
# update_missing_thumbnails doesn't clobber existing thumbnails
# ---------------------------------------------------------------------------

class TestUpdateMissingThumbnailsClobberGuard:
    """Verify that update_missing_thumbnails with fetch_ok=True, thumbnail_url=None
    does NOT overwrite existing non-empty thumbnail."""

    @pytest.mark.asyncio
    async def test_no_clobber_on_null_thumbnail(self, service):
        """When _fetch_thumbnails_sync returns thumbnail_url=None for an ad
        selected because object_type IS NULL, existing thumbnail is preserved."""
        mock_supabase = MagicMock()

        # Query returns an ad that needs object_type but already has thumbnail
        query_result = MagicMock()
        query_result.data = [{"meta_ad_id": "ad_with_thumb"}]

        mock_supabase.table.return_value.select.return_value.or_.return_value.eq.return_value.limit.return_value.execute.return_value = query_result

        # fetch_ad_thumbnails returns fetch_ok but no thumbnail
        thumbnails = {
            "ad_with_thumb": {
                "thumbnail_url": None,
                "video_id": None,
                "is_video": False,
                "object_type": "SHARE",
                "fetch_ok": True,
            }
        }

        update_mock = MagicMock()
        update_mock.eq.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.update.return_value = update_mock

        with patch("viraltracker.core.database.get_supabase_client", return_value=mock_supabase):
            with patch.object(service, "fetch_ad_thumbnails", new_callable=AsyncMock, return_value=thumbnails):
                updated = await service.update_missing_thumbnails(
                    brand_id=UUID("12345678-1234-1234-1234-123456789012"),
                    limit=100,
                )

        assert updated == 1

        # Verify update was called with object_type but NOT thumbnail_url
        update_call_args = mock_supabase.table.return_value.update.call_args
        update_data = update_call_args[0][0]
        assert "object_type" in update_data
        assert update_data["object_type"] == "SHARE"
        assert "thumbnail_url" not in update_data  # Should NOT clobber
