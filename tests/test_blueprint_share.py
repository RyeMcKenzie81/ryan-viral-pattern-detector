"""Tests for blueprint QA status and public share link functionality."""

from unittest.mock import MagicMock, patch

import pytest

from viraltracker.services.landing_page_analysis.blueprint_service import (
    ReconstructionBlueprintService,
)


class TestBlueprintQAStatus:
    """Tests for update_qa_status on blueprint_service."""

    @pytest.fixture
    def service(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": "bp-id", "qa_status": "approved"}])
        )
        return ReconstructionBlueprintService(mock_supabase)

    def test_valid_status_approved(self, service):
        result = service.update_qa_status("bp-id", "approved")
        assert result["qa_status"] == "approved"

    def test_invalid_status_raises(self, service):
        with pytest.raises(ValueError, match="qa_status must be one of"):
            service.update_qa_status("bp-id", "not_valid")

    def test_needs_revision(self, service):
        service.update_qa_status("bp-id", "needs_revision")
        call_args = service.supabase.table.return_value.update.call_args
        update_dict = call_args[0][0]
        assert update_dict["qa_status"] == "needs_revision"
        assert "qa_reviewed_at" in update_dict


class TestShareLinks:
    """Tests for generate_share_link, disable_share_link, get_blueprint_by_share_token."""

    @pytest.fixture
    def service(self):
        mock_supabase = MagicMock()
        return ReconstructionBlueprintService(mock_supabase)

    def test_generate_new_token(self, service):
        """Should generate a new token when none exists."""
        # Mock: no existing token
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": None, "public_share_enabled": False})
        )
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )

        token = service.generate_share_link("bp-id")
        assert isinstance(token, str)
        assert len(token) == 12  # secrets.token_urlsafe(9) produces 12 chars

    def test_reuse_existing_token(self, service):
        """Should return existing token and re-enable if disabled."""
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": "existing_tok!", "public_share_enabled": False})
        )
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )

        token = service.generate_share_link("bp-id")
        assert token == "existing_tok!"
        # Should have called update to re-enable
        service.supabase.table.return_value.update.assert_called()

    def test_reuse_already_enabled(self, service):
        """Should return existing token without update if already enabled."""
        service.supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data={"public_share_token": "active_token", "public_share_enabled": True})
        )

        token = service.generate_share_link("bp-id")
        assert token == "active_token"

    def test_disable_share_link(self, service):
        """Should set public_share_enabled to False."""
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{}])
        )
        service.disable_share_link("bp-id")
        call_args = service.supabase.table.return_value.update.call_args
        assert call_args[0][0]["public_share_enabled"] is False

    def test_get_by_token_found(self, service):
        """Should return HTML for valid enabled token."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "bp-id",
                "blueprint_mockup_html_with_images": "<div>Preview</div>",
                "blueprint_mockup_html": "<div>Fallback</div>",
                "source_url": "https://example.com",
            }])
        )
        result = service.get_blueprint_by_share_token("valid_token")
        assert result is not None
        assert result["html"] == "<div>Preview</div>"
        assert result["id"] == "bp-id"

    def test_get_by_token_prefers_images_version(self, service):
        """Should prefer blueprint_mockup_html_with_images over plain."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "bp-id",
                "blueprint_mockup_html_with_images": "<div>With Images</div>",
                "blueprint_mockup_html": "<div>Plain</div>",
                "source_url": "",
            }])
        )
        result = service.get_blueprint_by_share_token("tok")
        assert result["html"] == "<div>With Images</div>"

    def test_get_by_token_falls_back_to_plain(self, service):
        """Should fall back to blueprint_mockup_html if images version is None."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "bp-id",
                "blueprint_mockup_html_with_images": None,
                "blueprint_mockup_html": "<div>Plain</div>",
                "source_url": "",
            }])
        )
        result = service.get_blueprint_by_share_token("tok")
        assert result["html"] == "<div>Plain</div>"

    def test_get_by_token_not_found(self, service):
        """Should return None for missing token."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[])
        )
        result = service.get_blueprint_by_share_token("bad_token")
        assert result is None

    def test_get_by_token_no_html(self, service):
        """Should return None if token exists but no HTML stored."""
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{
                "id": "bp-id",
                "blueprint_mockup_html_with_images": None,
                "blueprint_mockup_html": None,
                "source_url": "",
            }])
        )
        result = service.get_blueprint_by_share_token("tok")
        assert result is None
