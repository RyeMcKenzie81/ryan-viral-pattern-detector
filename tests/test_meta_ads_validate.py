"""
Unit tests for MetaAdsService.validate_ad_account() — format validation only.

Tests the format checking logic without requiring the Meta SDK or API access.
SDK/API interactions are mocked.

Run with: pytest tests/test_meta_ads_validate.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from viraltracker.services.meta_ads_service import MetaAdsService


@pytest.fixture
def service():
    """Create a MetaAdsService with no real config."""
    svc = MetaAdsService(
        access_token="fake_token",
        ad_account_id="act_000000000",
    )
    return svc


# ---------------------------------------------------------------------------
# Format validation (no API calls needed)
# ---------------------------------------------------------------------------

class TestFormatValidation:
    def test_valid_act_prefix(self, service):
        """act_123456789 → valid_format=True, normalized correctly."""
        # Mock _ensure_sdk to prevent real SDK init, and raise to stop after format check
        with patch.object(service, "_ensure_sdk", side_effect=ImportError("no SDK")):
            result = service.validate_ad_account("act_123456789")

        assert result["valid_format"] is True
        assert result["meta_ad_account_id"] == "act_123456789"
        assert result["reason_code"] == "sdk_error"  # Stopped at SDK init

    def test_valid_numeric_only(self, service):
        """Plain numeric → normalized to act_ prefix."""
        with patch.object(service, "_ensure_sdk", side_effect=ImportError("no SDK")):
            result = service.validate_ad_account("123456789")

        assert result["valid_format"] is True
        assert result["meta_ad_account_id"] == "act_123456789"

    def test_invalid_format_letters(self, service):
        """Letters in ID → invalid_format, no API call."""
        result = service.validate_ad_account("act_abc123")
        assert result["valid_format"] is False
        assert result["reason_code"] == "invalid_format"
        assert "Invalid" in result["error"]

    def test_invalid_format_empty(self, service):
        """Empty string → invalid_format."""
        result = service.validate_ad_account("")
        assert result["valid_format"] is False
        assert result["reason_code"] == "invalid_format"

    def test_invalid_format_special_chars(self, service):
        """Special characters → invalid_format."""
        result = service.validate_ad_account("act_12-34")
        assert result["valid_format"] is False
        assert result["reason_code"] == "invalid_format"

    def test_whitespace_trimmed(self, service):
        """Leading/trailing whitespace is trimmed."""
        with patch.object(service, "_ensure_sdk", side_effect=ImportError("no SDK")):
            result = service.validate_ad_account("  act_999  ")

        assert result["valid_format"] is True
        assert result["meta_ad_account_id"] == "act_999"

    def test_act_prefix_only(self, service):
        """Just 'act_' with no number → invalid_format."""
        result = service.validate_ad_account("act_")
        assert result["valid_format"] is False
        assert result["reason_code"] == "invalid_format"


# ---------------------------------------------------------------------------
# Mocked API interaction tests
# ---------------------------------------------------------------------------

class TestAPIValidation:
    def _mock_facebook_error(self, error_code=100, error_subcode=0, message="Error"):
        """Create a mock FacebookRequestError."""
        error = MagicMock()
        error.api_error_code = error_code
        error.api_error_subcode = error_subcode
        error.api_error_message = MagicMock(return_value=message)
        # Make it raise-able
        error.__class__ = type("FacebookRequestError", (Exception,), {})
        return error

    def test_account_exists_with_access(self, service):
        """Account exists and ads are readable → reason_code=ok."""
        mock_ad_account = MagicMock()
        mock_ad_account.api_get.return_value = {"name": "Test Account", "account_status": 1}
        mock_ad_account.get_ads.return_value = iter([{"id": "123"}])

        with patch.object(service, "_ensure_sdk"):
            with patch("viraltracker.services.meta_ads_service.MetaAdsService.validate_ad_account") as original:
                # Instead of patching deeply, let's test the full flow with mocked imports
                pass

        # Simpler approach: test via direct mocking of the facebook_business module
        with patch.object(service, "_ensure_sdk"):
            with patch.dict("sys.modules", {
                "facebook_business": MagicMock(),
                "facebook_business.adobjects": MagicMock(),
                "facebook_business.adobjects.adaccount": MagicMock(),
                "facebook_business.exceptions": MagicMock(),
            }):
                import sys
                mock_adaccount_cls = MagicMock()
                mock_instance = MagicMock()
                mock_instance.api_get.return_value = {"name": "My Ad Account", "account_status": 1}
                mock_instance.get_ads.return_value = [{"id": "12345"}]
                mock_adaccount_cls.return_value = mock_instance
                sys.modules["facebook_business.adobjects.adaccount"].AdAccount = mock_adaccount_cls
                sys.modules["facebook_business.exceptions"].FacebookRequestError = type(
                    "FacebookRequestError", (Exception,), {}
                )

                result = service.validate_ad_account("act_111222333")

        assert result["valid_format"] is True
        assert result["exists"] is True
        assert result["can_read_ads"] is True
        assert result["has_access"] is True
        assert result["reason_code"] == "ok"
        assert result["name"] == "My Ad Account"

    def test_account_not_found(self, service):
        """Account doesn't exist → reason_code=not_found."""
        with patch.object(service, "_ensure_sdk"):
            with patch.dict("sys.modules", {
                "facebook_business": MagicMock(),
                "facebook_business.adobjects": MagicMock(),
                "facebook_business.adobjects.adaccount": MagicMock(),
                "facebook_business.exceptions": MagicMock(),
            }):
                import sys
                # Create a proper exception class
                FBError = type("FacebookRequestError", (Exception,), {})
                sys.modules["facebook_business.exceptions"].FacebookRequestError = FBError

                err = FBError("Not found")
                err.api_error_code = 100
                err.api_error_subcode = 33
                err.api_error_message = lambda: "Object does not exist"

                mock_adaccount_cls = MagicMock()
                mock_instance = MagicMock()
                mock_instance.api_get.side_effect = err
                mock_adaccount_cls.return_value = mock_instance
                sys.modules["facebook_business.adobjects.adaccount"].AdAccount = mock_adaccount_cls

                result = service.validate_ad_account("act_999888777")

        assert result["valid_format"] is True
        assert result["exists"] is False
        assert result["reason_code"] == "not_found"

    def test_rate_limited(self, service):
        """Rate limit error → reason_code=rate_limited."""
        with patch.object(service, "_ensure_sdk"):
            with patch.dict("sys.modules", {
                "facebook_business": MagicMock(),
                "facebook_business.adobjects": MagicMock(),
                "facebook_business.adobjects.adaccount": MagicMock(),
                "facebook_business.exceptions": MagicMock(),
            }):
                import sys
                FBError = type("FacebookRequestError", (Exception,), {})
                sys.modules["facebook_business.exceptions"].FacebookRequestError = FBError

                err = FBError("Too many calls")
                err.api_error_code = 4
                err.api_error_subcode = 0
                err.api_error_message = lambda: "Too many calls"

                mock_adaccount_cls = MagicMock()
                mock_instance = MagicMock()
                mock_instance.api_get.side_effect = err
                mock_adaccount_cls.return_value = mock_instance
                sys.modules["facebook_business.adobjects.adaccount"].AdAccount = mock_adaccount_cls

                result = service.validate_ad_account("act_111222333")

        assert result["valid_format"] is True
        assert result["reason_code"] == "rate_limited"

    def test_no_access_account_exists(self, service):
        """Account exists but no read access → reason_code=no_access."""
        with patch.object(service, "_ensure_sdk"):
            with patch.dict("sys.modules", {
                "facebook_business": MagicMock(),
                "facebook_business.adobjects": MagicMock(),
                "facebook_business.adobjects.adaccount": MagicMock(),
                "facebook_business.exceptions": MagicMock(),
            }):
                import sys
                FBError = type("FacebookRequestError", (Exception,), {})
                sys.modules["facebook_business.exceptions"].FacebookRequestError = FBError

                # api_get succeeds (account exists)
                mock_adaccount_cls = MagicMock()
                mock_instance = MagicMock()
                mock_instance.api_get.return_value = {"name": "Restricted Account", "account_status": 1}

                # get_ads fails with permission error
                ads_err = FBError("No permission")
                ads_err.api_error_code = 10
                ads_err.api_error_subcode = 0
                ads_err.api_error_message = lambda: "Permission denied"
                mock_instance.get_ads.side_effect = ads_err

                # get_insights also fails
                insights_err = FBError("No permission")
                insights_err.api_error_code = 200
                insights_err.api_error_subcode = 0
                insights_err.api_error_message = lambda: "Permission denied"
                mock_instance.get_insights.side_effect = insights_err

                mock_adaccount_cls.return_value = mock_instance
                sys.modules["facebook_business.adobjects.adaccount"].AdAccount = mock_adaccount_cls

                result = service.validate_ad_account("act_555666777")

        assert result["valid_format"] is True
        assert result["exists"] is True
        assert result["can_read_ads"] is False
        assert result["can_read_insights"] is False
        assert result["has_access"] is False
        assert result["reason_code"] == "no_access"
