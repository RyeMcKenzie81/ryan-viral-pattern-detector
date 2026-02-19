"""
Tests for LandingPageAnalysisService screenshot storage methods.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from viraltracker.services.landing_page_analysis.analysis_service import (
    LandingPageAnalysisService,
)


@pytest.fixture
def mock_supabase():
    """Create a mock Supabase client."""
    client = MagicMock()
    # Chain: .storage.from_(bucket).upload(...)
    client.storage.from_.return_value.upload.return_value = None
    client.storage.from_.return_value.download.return_value = b"fake_image_bytes"
    # Chain: .table(name).update(data).eq(col, val).execute()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return client


@pytest.fixture
def service(mock_supabase):
    """Create service with mocked Supabase."""
    return LandingPageAnalysisService(supabase=mock_supabase)


def _make_small_png() -> str:
    """Create a small valid PNG as base64."""
    import base64
    from PIL import Image

    img = Image.new("RGB", (100, 50), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _make_large_image(width: int = 2400, height: int = 6000) -> str:
    """Create a large image that exceeds 4MB when saved as PNG."""
    import base64
    from PIL import Image
    import random

    # Create image with random noise to prevent compression from shrinking it
    img = Image.new("RGB", (width, height))
    # Fill with semi-random data to make it large
    pixels = img.load()
    for y in range(0, height, 10):
        for x in range(0, width, 10):
            r, g, b = (x * 7 + y) % 256, (x * 3 + y * 5) % 256, (x + y * 11) % 256
            for dy in range(min(10, height - y)):
                for dx in range(min(10, width - x)):
                    pixels[x + dx, y + dy] = (r, g, b)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Store screenshot tests
# ---------------------------------------------------------------------------

class TestStoreScreenshot:

    def test_store_screenshot_uploads_to_bucket(self, service, mock_supabase):
        """Verify upload is called with correct content-type."""
        b64 = _make_small_png()
        service._store_screenshot("analysis_123", "org_456", b64)

        mock_supabase.storage.from_.assert_called_with("landing-page-screenshots")
        upload_call = mock_supabase.storage.from_.return_value.upload
        assert upload_call.called
        args = upload_call.call_args
        path = args[0][0]
        assert path.startswith("org_456/analysis_123.")
        content_opts = args[0][2]
        assert content_opts["content-type"] in ("image/png", "image/jpeg")

    def test_store_screenshot_updates_db_record(self, service, mock_supabase):
        """Verify DB update is called with the storage path."""
        b64 = _make_small_png()
        result_path = service._store_screenshot("analysis_123", "org_456", b64)

        mock_supabase.table.assert_called_with("landing_page_analyses")
        update_call = mock_supabase.table.return_value.update
        assert update_call.called
        update_data = update_call.call_args[0][0]
        assert "screenshot_storage_path" in update_data
        assert result_path == update_data["screenshot_storage_path"]

    def test_store_screenshot_small_image_stays_png(self, service, mock_supabase):
        """Small PNG should remain PNG format."""
        b64 = _make_small_png()
        result_path = service._store_screenshot("analysis_123", "org_456", b64)

        assert result_path.endswith(".png")
        upload_call = mock_supabase.storage.from_.return_value.upload
        content_opts = upload_call.call_args[0][2]
        assert content_opts["content-type"] == "image/png"


# ---------------------------------------------------------------------------
# Prepare screenshot tests
# ---------------------------------------------------------------------------

class TestPrepareScreenshot:

    def test_small_png_stays_png(self, service):
        """Small PNG below threshold should remain PNG format."""
        from PIL import Image

        img = Image.new("RGB", (100, 50), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original = buf.getvalue()

        result_bytes, result_fmt = service._prepare_screenshot(original, max_bytes=4_000_000)
        assert result_fmt == "PNG"
        assert len(result_bytes) <= 4_000_000
        # Verify it's still a valid PNG
        result_img = Image.open(io.BytesIO(result_bytes))
        assert result_img.width == 100
        assert result_img.height == 50

    def test_wide_image_gets_resized(self, service):
        """Image wider than 1200px should be resized."""
        from PIL import Image

        img = Image.new("RGB", (2400, 1200), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original = buf.getvalue()

        result_bytes, result_fmt = service._prepare_screenshot(original, max_bytes=10_000_000)

        # Verify it was resized by opening the result
        result_img = Image.open(io.BytesIO(result_bytes))
        assert result_img.width <= 1200

    def test_jpeg_fallback_for_very_large(self, service):
        """Very large images should fall back to JPEG."""
        from PIL import Image

        # Create a large image that won't fit in PNG under a small limit
        img = Image.new("RGB", (1000, 1000), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original = buf.getvalue()

        # Set an artificially low limit to force JPEG fallback
        result_bytes, result_fmt = service._prepare_screenshot(original, max_bytes=100)
        assert result_fmt == "JPEG"


# ---------------------------------------------------------------------------
# Load screenshot tests
# ---------------------------------------------------------------------------

class TestLoadScreenshot:

    def test_load_screenshot_downloads_bytes(self, service, mock_supabase):
        """Verify download is called and bytes are returned."""
        result = service._load_screenshot("org_456/analysis_123.png")

        mock_supabase.storage.from_.assert_called_with("landing-page-screenshots")
        mock_supabase.storage.from_.return_value.download.assert_called_with(
            "org_456/analysis_123.png"
        )
        assert result == b"fake_image_bytes"

    def test_load_screenshot_returns_none_on_error(self, service, mock_supabase):
        """Download failure should return None, not raise."""
        mock_supabase.storage.from_.return_value.download.side_effect = Exception("Not found")
        result = service._load_screenshot("org_456/missing.png")
        assert result is None

    def test_store_screenshot_non_blocking_on_error(self, mock_supabase):
        """Upload failure in run_full_analysis should not block analysis."""
        mock_supabase.storage.from_.return_value.upload.side_effect = Exception("Upload failed")
        svc = LandingPageAnalysisService(supabase=mock_supabase)

        # _store_screenshot should raise, but run_full_analysis catches it
        b64 = _make_small_png()
        with pytest.raises(Exception, match="Upload failed"):
            svc._store_screenshot("analysis_123", "org_456", b64)
