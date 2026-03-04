"""
Tests for AdContentService - dash sanitization helper.
"""

from viraltracker.pipelines.ad_creation_v2.services.content_service import _sanitize_dashes


class TestSanitizeDashes:
    """Test _sanitize_dashes replaces em/en dashes."""

    def test_em_dash(self):
        assert _sanitize_dashes("This \u2014 works") == "This  -  works"

    def test_en_dash(self):
        assert _sanitize_dashes("Pages 1\u201310") == "Pages 1-10"

    def test_no_dashes(self):
        assert _sanitize_dashes("No dashes here") == "No dashes here"

    def test_both_dashes(self):
        result = _sanitize_dashes("A\u2014B\u2013C")
        assert "\u2014" not in result
        assert "\u2013" not in result
        assert result == "A - B-C"

    def test_empty_string(self):
        assert _sanitize_dashes("") == ""

    def test_multiple_em_dashes(self):
        result = _sanitize_dashes("first\u2014second\u2014third")
        assert result == "first - second - third"
