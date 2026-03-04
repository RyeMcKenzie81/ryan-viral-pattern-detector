"""Tests for analysis public share link functionality."""

from unittest.mock import MagicMock

import pytest

from viraltracker.services.landing_page_analysis.analysis_service import (
    LandingPageAnalysisService,
)


class TestAnalysisShareLinks:
    """Tests for generate_share_link, disable_share_link, get_analysis_by_share_token."""

    @pytest.fixture
    def service(self):
        mock_supabase = MagicMock()
        return LandingPageAnalysisService(mock_supabase)

    def test_generate_new_token(self, service):
        """Should generate a new 128-bit token when none exists."""
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": None, "public_share_enabled": False})
        )
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )

        token = service.generate_share_link("analysis-id")
        assert isinstance(token, str)
        assert len(token) == 22  # secrets.token_urlsafe(16) produces 22 chars

    def test_reenable_disabled_token(self, service):
        """Should return existing token and re-enable if disabled."""
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": "existing_token_value!", "public_share_enabled": False})
        )
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )

        token = service.generate_share_link("analysis-id")
        assert token == "existing_token_value!"
        # Should have called update to re-enable
        service.supabase.table.return_value.update.assert_called()

    def test_reuse_already_enabled(self, service):
        """Should return existing token without update if already enabled."""
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": "active_token_abc", "public_share_enabled": True})
        )

        token = service.generate_share_link("analysis-id")
        assert token == "active_token_abc"

    def test_disable_share_link(self, service):
        """Should set public_share_enabled to False."""
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )
        service.disable_share_link("analysis-id")
        call_args = service.supabase.table.return_value.update.call_args
        assert call_args[0][0]["public_share_enabled"] is False

    def test_get_by_token_found(self, service):
        """Should return HTML for valid enabled token."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "analysis-id",
                "analysis_mockup_html": "<div>Analysis Preview</div>",
                "url": "https://example.com",
            }])
        )
        result = service.get_analysis_by_share_token("valid_token")
        assert result is not None
        assert result["html"] == "<div>Analysis Preview</div>"
        assert result["id"] == "analysis-id"
        assert result["source_url"] == "https://example.com"

    def test_get_by_token_not_found(self, service):
        """Should return None for missing token."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[])
        )
        result = service.get_analysis_by_share_token("bad_token")
        assert result is None

    def test_get_by_token_no_html(self, service):
        """Should return None if token exists but no HTML stored."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "analysis-id",
                "analysis_mockup_html": None,
                "url": "https://example.com",
            }])
        )
        result = service.get_analysis_by_share_token("tok")
        assert result is None
