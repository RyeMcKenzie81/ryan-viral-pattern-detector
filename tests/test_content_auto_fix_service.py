"""Tests for ContentAutoFixService."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from viraltracker.services.seo_pipeline.services.content_auto_fix_service import (
    ContentAutoFixService,
    FIXABLE_CHECKS,
)
from viraltracker.services.seo_pipeline.models import QACheck


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    return MagicMock()


@pytest.fixture
def service(mock_supabase):
    return ContentAutoFixService(supabase_client=mock_supabase)


def _make_article(**overrides):
    """Create a test article dict."""
    base = {
        "id": "test-article-id",
        "brand_id": "test-brand-id",
        "organization_id": "test-org-id",
        "keyword": "cooperative games for siblings",
        "seo_title": "This Is A Very Long SEO Title That Exceeds The Sixty Character Limit For Search Engines",
        "meta_description": "",
        "content_markdown": "## Introduction\n\nSiblings fight over toys all the time. Here are some cooperative games.\n\n## FAQ\n\n### What are cooperative games?\n\nGames where players work together.\n\n### Why do siblings fight?\n\nBecause sharing is hard.",
        "schema_markup": None,
        "phase_c_output": None,
        "phase_b_output": None,
        "content_html": "",
        "title": "Cooperative Games for Siblings",
    }
    base.update(overrides)
    return base


def _mock_qa_checks(failing_checks, kw_missing_from=None):
    """Create a list of QACheck objects with specified failures.

    Args:
        failing_checks: List of check names that should fail
        kw_missing_from: List of keyword_placement locations missing keyword
                         (e.g. ["title/h1", "first_paragraph"]). Only used
                         if "keyword_placement" is in failing_checks.
    """
    all_checks = [
        "word_count", "em_dashes", "title_length", "meta_description",
        "heading_structure", "readability", "keyword_placement",
        "internal_links", "images", "schema_markup",
    ]
    results = []
    for name in all_checks:
        if name in failing_checks:
            details = None
            if name == "keyword_placement" and kw_missing_from:
                details = {"missing": kw_missing_from}
            results.append(QACheck(
                name=name, passed=False, severity="warning",
                message=f"{name} failed",
                details=details,
            ))
        else:
            results.append(QACheck(
                name=name, passed=True,
                message=f"{name} passed",
            ))
    return results


# ============================================================================
# Tier 1: Em Dashes
# ============================================================================

class TestFixEmDashes:
    def test_replaces_em_dashes(self, service):
        content = "Hello \u2014 world \u2013 test"
        result = service._fix_em_dashes(content)
        assert result["success"]
        assert result["new_value"] == "Hello - world - test"
        assert result["fix"]["check"] == "em_dashes"

    def test_no_dashes_returns_failure(self, service):
        result = service._fix_em_dashes("Hello world")
        assert not result["success"]

    def test_mixed_dashes(self, service):
        content = "A\u2014B\u2014C\u2013D"
        result = service._fix_em_dashes(content)
        assert result["success"]
        assert result["new_value"] == "A-B-C-D"


# ============================================================================
# Tier 1: Schema Markup
# ============================================================================

class TestFixSchemaMarkup:
    def test_generates_faq_schema(self, service):
        content = "## FAQ\n\n### What is this?\n\nThis is a test.\n\n### How does it work?\n\nIt works great."
        result = service._fix_schema_markup(content)
        assert result["success"]
        schema = result["new_value"]
        assert schema["@type"] == "FAQPage"
        assert len(schema["mainEntity"]) == 2
        assert schema["mainEntity"][0]["name"] == "What is this?"

    def test_no_faq_falls_back_to_article_schema(self, service):
        content = "## Introduction\n\nJust some text."
        article = {"seo_title": "My Great Article", "meta_description": "A desc", "keyword": "test"}
        result = service._fix_schema_markup(content, article=article)
        assert result["success"]
        assert result["new_value"]["@type"] == "Article"
        assert result["new_value"]["headline"] == "My Great Article"

    def test_no_faq_no_title_fails(self, service):
        content = "## Introduction\n\nJust some text."
        result = service._fix_schema_markup(content, article=None)
        assert not result["success"]

    def test_faq_no_qa_pairs_falls_back_to_article(self, service):
        content = "## FAQ\n\nJust some text without questions."
        article = {"seo_title": "Title", "meta_description": "", "keyword": ""}
        result = service._fix_schema_markup(content, article=article)
        assert result["success"]
        assert result["new_value"]["@type"] == "Article"

    def test_bold_pattern_faq(self, service):
        content = "## FAQ\n\n**What is this?**\nA test.\n\n**How does it work?**\nGreat."
        result = service._fix_schema_markup(content)
        assert result["success"]
        assert len(result["new_value"]["mainEntity"]) == 2


# ============================================================================
# Tier 2: AI Validation
# ============================================================================

class TestValidation:
    def test_valid_title(self, service):
        result = service._validate_seo_title("Cooperative Games for Siblings Guide", "cooperative games")
        assert result["valid"]

    def test_title_too_short(self, service):
        result = service._validate_seo_title("Short", "games")
        assert not result["valid"]
        assert "too short" in result["reason"]

    def test_title_too_long(self, service):
        result = service._validate_seo_title("A" * 75, "games")
        assert not result["valid"]
        assert "too long" in result["reason"]

    def test_empty_title(self, service):
        result = service._validate_seo_title("", "games")
        assert not result["valid"]

    def test_valid_meta(self, service):
        result = service._validate_meta_description("A" * 155)
        assert result["valid"]

    def test_meta_too_short(self, service):
        result = service._validate_meta_description("Too short")
        assert not result["valid"]

    def test_meta_too_long(self, service):
        result = service._validate_meta_description("A" * 210)
        assert not result["valid"]


# ============================================================================
# First Paragraph Extraction
# ============================================================================

class TestExtractFirstParagraph:
    def test_basic_extraction(self, service):
        content = "## Heading\n\nFirst paragraph here.\n\nSecond paragraph."
        result = service._extract_first_paragraph(content)
        assert result == "First paragraph here."

    def test_skips_headings(self, service):
        content = "# Title\n\n## Section\n\nActual text."
        result = service._extract_first_paragraph(content)
        assert result == "Actual text."

    def test_skips_images(self, service):
        content = "![alt](url)\n\nReal text here."
        result = service._extract_first_paragraph(content)
        assert result == "Real text here."

    def test_skips_html_img_tags(self, service):
        content = '<img src="https://example.com/image.png" alt="test">\n\nReal text here.'
        result = service._extract_first_paragraph(content)
        assert result == "Real text here."

    def test_skips_figure_tags(self, service):
        content = '<figure><img src="url"></figure>\n\nActual paragraph.'
        result = service._extract_first_paragraph(content)
        assert result == "Actual paragraph."

    def test_strips_frontmatter(self, service):
        content = "---\ntitle: Test\n---\n\nFirst real paragraph."
        result = service._extract_first_paragraph(content)
        assert result == "First real paragraph."

    def test_empty_content(self, service):
        result = service._extract_first_paragraph("")
        assert result is None


# ============================================================================
# Full fix_article Flow
# ============================================================================

class TestFixArticle:
    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_no_fixes_needed(self, mock_anthropic, service, mock_supabase):
        article = _make_article(
            seo_title="Perfect Title for SEO Optimization Here",  # 50-60 chars
            meta_description="A" * 155,
            content_markdown="## Intro\n\nCooperative games for siblings are great.\n\n## FAQ\n\n### Q?\n\nA.",
            schema_markup={"@type": "FAQPage"},
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks([])  # all pass
            report = service.fix_article("test-id", "brand-id", "org-id")

        assert not report["fixed"]
        assert report["fixes_applied"] == []
        assert report["total_fixes"] == 0

    def test_article_not_found(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        report = service.fix_article("missing-id", "brand-id", "org-id")

        assert not report["fixed"]
        assert len(report["fixes_failed"]) == 1
        assert report["fixes_failed"][0]["check"] == "load_article"

    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_em_dash_fix_applied(self, mock_anthropic, service, mock_supabase):
        article = _make_article(
            content_markdown="Hello \u2014 world",
            seo_title="Perfect Title for SEO Optimization Here",
            meta_description="A" * 155,
            schema_markup={"@type": "FAQPage"},
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks(["em_dashes"])
            report = service.fix_article("test-id", "brand-id", "org-id")

        assert report["fixed"]
        assert report["total_fixes"] == 1
        assert report["fixes_applied"][0]["check"] == "em_dashes"

    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_ai_rewrite_success(self, mock_anthropic_prop, service, mock_supabase):
        article = _make_article()

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Mock Claude response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "seo_title": "Cooperative Games for Siblings: A Complete Guide",
            "meta_description": "Discover the best cooperative games for siblings that turn fighting into fun. Learn activities that teach teamwork and reduce conflicts between kids at home.",
        }))]
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 50
        mock_anthropic_prop.return_value.messages.create.return_value = mock_response

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks(["title_length", "meta_description"])
            report = service.fix_article("test-id", "brand-id", "org-id")

        assert report["fixed"]
        assert report["total_fixes"] == 2
        assert report["ai_cost_tokens"] == 250

        # Verify title and meta were applied
        check_names = [f["check"] for f in report["fixes_applied"]]
        assert "title_length" in check_names
        assert "meta_description" in check_names

    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_ai_failure_degrades_gracefully(self, mock_anthropic_prop, service, mock_supabase):
        article = _make_article(
            content_markdown="Hello \u2014 world",
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Mock Claude API failure
        mock_anthropic_prop.return_value.messages.create.side_effect = Exception("API error")

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks(["em_dashes", "title_length"])
            report = service.fix_article("test-id", "brand-id", "org-id")

        # Tier 1 fix should still succeed
        assert report["fixed"]
        em_fixes = [f for f in report["fixes_applied"] if f["check"] == "em_dashes"]
        assert len(em_fixes) == 1

        # Tier 2 fix should be in failures
        title_failures = [f for f in report["fixes_failed"] if f["check"] == "title_length"]
        assert len(title_failures) == 1

    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_keyword_placement_fixes_title(self, mock_anthropic_prop, service, mock_supabase):
        """When keyword is missing from title (but title length is OK), fix title for keyword."""
        article = _make_article(
            seo_title="Stop Gaming Fights Between Your Kids Today",  # Good length, missing keyword
            keyword="cooperative games for siblings",
            meta_description="A" * 155,
            content_markdown="## Intro\n\nCooperative games for siblings are great.",
            schema_markup={"@type": "Article"},
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "seo_title": "Cooperative Games for Siblings: End Gaming Fights",
        }))]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 30
        mock_anthropic_prop.return_value.messages.create.return_value = mock_response

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks(
                ["keyword_placement"], kw_missing_from=["title/h1"]
            )
            report = service.fix_article("test-id", "brand-id", "org-id")

        assert report["fixed"]
        check_names = [f["check"] for f in report["fixes_applied"]]
        assert "title_length" in check_names  # Title rewrite attributed to title_length

    @patch("viraltracker.services.seo_pipeline.services.content_auto_fix_service.ContentAutoFixService.anthropic", new_callable=PropertyMock)
    def test_ai_returns_invalid_title(self, mock_anthropic_prop, service, mock_supabase):
        article = _make_article()

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[article])
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Mock Claude returning a title that's still too long
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "seo_title": "A" * 80,  # Still too long
        }))]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 30
        mock_anthropic_prop.return_value.messages.create.return_value = mock_response

        with patch(
            "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
        ) as MockQA:
            MockQA.return_value.run_checks.return_value = _mock_qa_checks(["title_length"])
            report = service.fix_article("test-id", "brand-id", "org-id")

        # Should be in fixes_failed, not fixes_applied
        assert len(report["fixes_failed"]) == 1
        assert "too long" in report["fixes_failed"][0]["reason"]


# ============================================================================
# FIXABLE_CHECKS mapping
# ============================================================================

class TestFixableChecks:
    def test_all_tier1_checks_mapped(self):
        assert "em_dashes" in FIXABLE_CHECKS
        assert "schema_markup" in FIXABLE_CHECKS

    def test_all_tier2_checks_mapped(self):
        assert "title_length" in FIXABLE_CHECKS
        assert "meta_description" in FIXABLE_CHECKS
        assert "keyword_placement" in FIXABLE_CHECKS

    def test_unfixable_checks_not_mapped(self):
        assert "word_count" not in FIXABLE_CHECKS
        assert "readability" not in FIXABLE_CHECKS
        assert "internal_links" not in FIXABLE_CHECKS
