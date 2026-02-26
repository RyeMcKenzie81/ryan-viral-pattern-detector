"""Tests for content pattern extraction and QA status on LandingPageAnalysisService."""

from unittest.mock import MagicMock, patch

import pytest

from viraltracker.services.landing_page_analysis.analysis_service import (
    LandingPageAnalysisService,
)


class TestExtractContentPatterns:
    """Tests for _extract_content_patterns static method."""

    def test_listicle_dominant(self):
        """Dominant feature_list (3+ items) should tag as listicle."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "feature_list", "item_count": 7, "confidence": 0.95, "is_dominant": True}
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result["primary_pattern"] == "listicle"
        assert "listicle" in result["patterns"]
        assert result["listicle_item_count"] == 7

    def test_feature_showcase_secondary(self):
        """Non-dominant feature_list (<3 items) should tag as feature_showcase."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "feature_list", "item_count": 2, "confidence": 0.7, "is_dominant": False}
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result["primary_pattern"] == "feature_showcase"
        assert "feature_showcase" in result["patterns"]

    def test_faq_pattern(self):
        """FAQ list should tag correctly."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "faq_list", "item_count": 5, "confidence": 0.9}
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result["primary_pattern"] == "faq"
        assert "faq" in result["patterns"]

    def test_mixed_patterns(self):
        """Multiple patterns with no dominant one should be 'mixed'."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "feature_list", "item_count": 5, "confidence": 0.6, "is_dominant": True},
                    {"type": "testimonial_list", "item_count": 3, "confidence": 0.7},
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert "listicle" in result["patterns"]
        assert "testimonial_grid" in result["patterns"]
        # Neither dominates at 80%+
        assert result["primary_pattern"] == "mixed"

    def test_single_dominant_in_mixed(self):
        """Multiple patterns but one at 80%+ confidence should be primary."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "faq_list", "item_count": 8, "confidence": 0.95},
                    {"type": "stats_list", "item_count": 2, "confidence": 0.4},
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result["primary_pattern"] == "faq"

    def test_empty_patterns(self):
        """No content_patterns should return empty dict."""
        elements = {"element_detection": {"content_patterns": []}}
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result == {}

    def test_no_element_detection_key(self):
        """Missing content_patterns key should return empty dict."""
        elements = {"element_detection": {}}
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result == {}

    def test_string_pattern_items(self):
        """String items (not dicts) should be handled gracefully."""
        elements = {
            "element_detection": {
                "content_patterns": ["feature_list", "faq_list"]
            }
        }
        # String items have no is_dominant, so feature_list should go to
        # the special branch with is_dominant=False -> feature_showcase
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result  # Should produce something, not crash

    def test_unknown_pattern_type_skipped(self):
        """Unknown pattern types should be skipped."""
        elements = {
            "element_detection": {
                "content_patterns": [
                    {"type": "unknown_weird_type", "confidence": 0.9}
                ]
            }
        }
        result = LandingPageAnalysisService._extract_content_patterns(elements)
        assert result == {}


class TestAnalysisQAStatus:
    """Tests for update_qa_status on analysis_service."""

    @pytest.fixture
    def service(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": "test-id", "qa_status": "approved"}])
        )
        svc = LandingPageAnalysisService(mock_supabase)
        return svc

    def test_valid_status_approved(self, service):
        result = service.update_qa_status("test-id", "approved")
        assert result["qa_status"] == "approved"

    def test_valid_status_rejected(self, service):
        service.update_qa_status("test-id", "rejected")
        # Should not raise

    def test_valid_status_needs_revision(self, service):
        service.update_qa_status("test-id", "needs_revision")

    def test_valid_status_pending(self, service):
        service.update_qa_status("test-id", "pending")

    def test_invalid_status_raises(self, service):
        with pytest.raises(ValueError, match="qa_status must be one of"):
            service.update_qa_status("test-id", "invalid_status")

    def test_notes_passed_through(self, service):
        service.update_qa_status("test-id", "approved", qa_notes="Looks good")
        call_args = service.supabase.table.return_value.update.call_args
        update_dict = call_args[0][0]
        assert update_dict["qa_notes"] == "Looks good"

    def test_reviewed_by_passed(self, service):
        service.update_qa_status("test-id", "approved", reviewed_by="user-uuid")
        call_args = service.supabase.table.return_value.update.call_args
        update_dict = call_args[0][0]
        assert update_dict["qa_reviewed_by"] == "user-uuid"
