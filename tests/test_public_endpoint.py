"""Tests for the public blueprint preview endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from viraltracker.api.app import app
    return TestClient(app)


class TestPublicBlueprintPreview:
    """Tests for GET /api/public/blueprint/{share_token}."""

    @patch("viraltracker.services.landing_page_analysis.ReconstructionBlueprintService")
    def test_valid_token_returns_html(self, mock_service_cls, client):
        """Valid token should return 200 with HTML content."""
        mock_instance = MagicMock()
        mock_instance.get_blueprint_by_share_token.return_value = {
            "id": "bp-id",
            "html": "<div>Blueprint Preview Content</div>",
            "source_url": "https://example.com",
        }
        mock_service_cls.return_value = mock_instance

        response = client.get("/api/public/blueprint/valid_token_12")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Blueprint Preview Content" in response.text
        assert "<!DOCTYPE html>" in response.text
        assert '<meta name="viewport"' in response.text

    @patch("viraltracker.services.landing_page_analysis.ReconstructionBlueprintService")
    def test_invalid_token_returns_404(self, mock_service_cls, client):
        """Invalid token should return 404."""
        mock_instance = MagicMock()
        mock_instance.get_blueprint_by_share_token.return_value = None
        mock_service_cls.return_value = mock_instance

        response = client.get("/api/public/blueprint/bad_token_xxx")
        assert response.status_code == 404

    @patch("viraltracker.services.landing_page_analysis.ReconstructionBlueprintService")
    def test_disabled_token_returns_404(self, mock_service_cls, client):
        """Disabled share link should return 404."""
        mock_instance = MagicMock()
        mock_instance.get_blueprint_by_share_token.return_value = None
        mock_service_cls.return_value = mock_instance

        response = client.get("/api/public/blueprint/disabled_tok")
        assert response.status_code == 404
