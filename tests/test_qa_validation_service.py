"""
Unit tests for QAValidationService.

Covers:
- Individual QA checks (word count, em dashes, title, meta, headings,
  readability, keyword placement, links, images, schema)
- run_checks() aggregate behavior
- validate_article() with mocked DB
- _extract_plain_text() markdown stripping
- _calculate_flesch() readability scoring
- Edge cases (empty content, missing fields, no keyword)

Run with: pytest tests/test_qa_validation_service.py -v
"""

import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from viraltracker.services.seo_pipeline.services.qa_validation_service import (
    QAValidationService,
)
from viraltracker.services.seo_pipeline.models import ArticleStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Service with mocked Supabase."""
    mock_supabase = MagicMock()
    return QAValidationService(supabase_client=mock_supabase)


@pytest.fixture
def good_article_md():
    """Markdown article that should pass all checks."""
    return """# Best Minecraft Tips for Parents

Minecraft tips for parents are essential when your kids start gaming. This guide
covers everything you need to know about managing your child's gaming experience.
Let us explore the best strategies for keeping your family connected while gaming.
This article provides practical advice backed by research and personal experience.

## Why Minecraft Matters for Families

Minecraft has become one of the most popular games in the world. It teaches creativity,
problem solving, and collaboration. Parents who understand the game can better connect
with their children and use it as a bonding tool. The educational value is well documented.

## Setting Healthy Boundaries

Setting healthy boundaries is important for any gaming activity. Start by establishing
clear time limits and expectations. Make gaming a shared activity rather than an isolated
one. Create rules together as a family so everyone feels heard and respected.

## Playing Together as a Family

One of the best strategies is to play Minecraft together. Join your child's world and
ask them to teach you the basics. This reversal of the teacher-student dynamic can be
incredibly powerful for building trust and communication between parents and children.

## Tips for Getting Started

Start with creative mode where there is no pressure. Learn the basic controls together.
Build a family project like a house or a castle. Take screenshots of your creations.
Share your gaming sessions on family movie night for extra fun and laughter together.

## Managing Screen Time

Screen time management does not have to be a battle. Use timers, create schedules, and
offer alternatives. The key is consistency and making sure gaming time is balanced with
outdoor activities, homework, and family time. Communication is the secret ingredient.

## Building Communication Skills

Gaming can actually improve communication skills when done right. Discuss strategies,
plan builds together, and problem solve as a team. These skills transfer directly to
real world situations and can strengthen the parent-child relationship significantly.

[Learn more about gaming safety](/blog/gaming-safety)
[Screen time guidelines](/blog/screen-time)
[Family activities guide](/blog/family-activities)

![Family playing Minecraft together](https://example.com/family-minecraft.jpg)
"""


@pytest.fixture
def bad_article_md():
    """Markdown article that should fail several checks."""
    return """Short article.

This is too short — and has em dashes — everywhere.
"""


# ---------------------------------------------------------------------------
# Word Count
# ---------------------------------------------------------------------------


class TestWordCount:
    def test_passes_above_minimum(self, service):
        text = " ".join(["word"] * 600)
        check = service._check_word_count(text)
        assert check.passed is True
        assert check.details["word_count"] == 600

    def test_fails_below_minimum(self, service):
        text = " ".join(["word"] * 100)
        check = service._check_word_count(text)
        assert check.passed is False
        assert check.severity == "error"
        assert check.details["word_count"] == 100

    def test_passes_at_exactly_minimum(self, service):
        text = " ".join(["word"] * 500)
        check = service._check_word_count(text)
        assert check.passed is True

    def test_empty_text(self, service):
        check = service._check_word_count("")
        assert check.passed is False
        assert check.details["word_count"] == 0


# ---------------------------------------------------------------------------
# Em Dashes
# ---------------------------------------------------------------------------


class TestEmDashes:
    def test_no_dashes(self, service):
        check = service._check_em_dashes("This is clean text with no dashes.")
        assert check.passed is True

    def test_em_dash_detected(self, service):
        check = service._check_em_dashes("This is\u2014a test with em dash.")
        assert check.passed is False
        assert check.details["em_dashes"] == 1

    def test_en_dash_detected(self, service):
        check = service._check_em_dashes("Pages 10\u201320 have content.")
        assert check.passed is False
        assert check.details["en_dashes"] == 1

    def test_multiple_dashes(self, service):
        check = service._check_em_dashes("This\u2014has\u2014multiple\u2013dashes")
        assert check.passed is False
        assert check.details["em_dashes"] == 2
        assert check.details["en_dashes"] == 1


# ---------------------------------------------------------------------------
# Title Length
# ---------------------------------------------------------------------------


class TestTitleLength:
    def test_ideal_length(self, service):
        title = "Best Minecraft Tips for Parents - A Complete Guide"  # 50 chars
        check = service._check_title_length(title)
        assert check.passed is True

    def test_too_short(self, service):
        title = "Tips"
        check = service._check_title_length(title)
        assert check.passed is False

    def test_too_long(self, service):
        title = "A" * 80
        check = service._check_title_length(title)
        assert check.passed is False

    def test_empty_title(self, service):
        check = service._check_title_length("")
        assert check.passed is False
        assert check.severity == "error"

    def test_exact_boundaries(self, service):
        title_50 = "A" * 50
        check = service._check_title_length(title_50)
        assert check.passed is True

        title_60 = "A" * 60
        check = service._check_title_length(title_60)
        assert check.passed is True


# ---------------------------------------------------------------------------
# Meta Description
# ---------------------------------------------------------------------------


class TestMetaDescription:
    def test_ideal_length(self, service):
        desc = "A" * 155
        check = service._check_meta_description(desc)
        assert check.passed is True

    def test_too_short(self, service):
        desc = "Short meta."
        check = service._check_meta_description(desc)
        assert check.passed is False

    def test_empty(self, service):
        check = service._check_meta_description("")
        assert check.passed is False
        assert check.severity == "error"

    def test_boundaries(self, service):
        check = service._check_meta_description("A" * 150)
        assert check.passed is True
        check = service._check_meta_description("A" * 160)
        assert check.passed is True


# ---------------------------------------------------------------------------
# Heading Structure
# ---------------------------------------------------------------------------


class TestHeadingStructure:
    def test_good_structure(self, service):
        from bs4 import BeautifulSoup
        md = "# Main Title\n\n## Section One\n\n## Section Two\n\n### Subsection\n"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_heading_structure(soup, md)
        assert check.passed is True
        assert check.details["h1"] == 1
        assert check.details["h2"] == 2

    def test_no_h1(self, service):
        from bs4 import BeautifulSoup
        md = "## Only H2 headings\n\n## Another H2\n"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_heading_structure(soup, md)
        assert check.passed is False
        assert check.severity == "error"

    def test_multiple_h1(self, service):
        from bs4 import BeautifulSoup
        md = "# First H1\n\n# Second H1\n\n## Section\n"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_heading_structure(soup, md)
        assert check.passed is False

    def test_no_h2(self, service):
        from bs4 import BeautifulSoup
        md = "# Title Only\n\nJust paragraphs with no sections.\n"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_heading_structure(soup, md)
        assert check.passed is False

    def test_html_headings_detected(self, service):
        from bs4 import BeautifulSoup
        html = "<h1>Title</h1><h2>Section</h2><h2>Section 2</h2>"
        soup = BeautifulSoup(html, "html.parser")
        check = service._check_heading_structure(soup, "")
        assert check.passed is True


# ---------------------------------------------------------------------------
# Readability (Flesch)
# ---------------------------------------------------------------------------


class TestReadability:
    def test_calculate_flesch_simple_text(self, service):
        text = "The cat sat on the mat. It was a good day. The sun was out."
        score = service._calculate_flesch(text)
        assert 60 <= score <= 100

    def test_calculate_flesch_complex_text(self, service):
        text = (
            "The pharmacological implications of administered benzodiazepines "
            "necessitate comprehensive physiological monitoring protocols. "
            "Neurotransmitter receptor antagonists demonstrate significant "
            "therapeutic efficacy."
        )
        score = service._calculate_flesch(text)
        assert score < 40

    def test_calculate_flesch_empty(self, service):
        score = service._calculate_flesch("")
        assert score == 0.0

    def test_readability_check_in_range(self, service):
        # Build text that hits ~65 Flesch
        text = (
            "Parents need to understand gaming. Kids love to play games. "
            "This is normal and healthy behavior. You should play with them. "
            "Set time limits and be consistent. Talk about what they enjoy. "
        ) * 10
        check = service._check_readability(text)
        assert check.details["flesch_score"] > 0

    def test_count_syllables(self, service):
        assert service._count_syllables("cat") == 1
        assert service._count_syllables("water") == 2
        assert service._count_syllables("beautiful") == 3
        assert service._count_syllables("the") == 1


# ---------------------------------------------------------------------------
# Keyword Placement
# ---------------------------------------------------------------------------


class TestKeywordPlacement:
    def test_all_placements_found(self, service):
        from bs4 import BeautifulSoup
        md = "# Minecraft Tips for Parents\n\nMinecraft tips for parents are essential for families.\n"
        soup = BeautifulSoup("<h1>Minecraft Tips for Parents</h1>", "html.parser")
        check = service._check_keyword_placement(
            keyword="minecraft tips for parents",
            seo_title="Minecraft Tips for Parents - Complete Guide",
            meta_description="Learn the best minecraft tips for parents in this guide.",
            content_md=md,
            soup=soup,
        )
        assert check.passed is True

    def test_missing_from_title(self, service):
        from bs4 import BeautifulSoup
        md = "# Minecraft Tips for Parents\n\nMinecraft tips for parents are essential.\n"
        soup = BeautifulSoup("<h1>Minecraft Tips for Parents</h1>", "html.parser")
        check = service._check_keyword_placement(
            keyword="minecraft tips for parents",
            seo_title="Gaming Guide for Families",
            meta_description="Learn minecraft tips for parents.",
            content_md=md,
            soup=soup,
        )
        assert check.passed is False
        assert "title" in check.details["missing"]

    def test_no_keyword_skips(self, service):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("", "html.parser")
        check = service._check_keyword_placement("", "", "", "", soup)
        assert check.passed is True

    def test_keyword_in_markdown_h1(self, service):
        from bs4 import BeautifulSoup
        md = "# Best Minecraft Tips\n\nBest minecraft tips help parents connect.\n"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_keyword_placement(
            keyword="best minecraft tips",
            seo_title="Best Minecraft Tips for Parents",
            meta_description="Best minecraft tips for your family.",
            content_md=md,
            soup=soup,
        )
        assert check.details["placements"]["h1"] is True


# ---------------------------------------------------------------------------
# Internal Links
# ---------------------------------------------------------------------------


class TestInternalLinks:
    def test_enough_links(self, service):
        from bs4 import BeautifulSoup
        md = "[Link 1](/page1) and [Link 2](/page2) and [Link 3](/page3)"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_internal_links(soup, md)
        assert check.passed is True
        assert check.details["link_count"] == 3

    def test_too_few_links(self, service):
        from bs4 import BeautifulSoup
        md = "[Only one link](/page1)"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_internal_links(soup, md)
        assert check.passed is False

    def test_html_links_counted(self, service):
        from bs4 import BeautifulSoup
        html = '<a href="/p1">L1</a><a href="/p2">L2</a><a href="/p3">L3</a>'
        soup = BeautifulSoup(html, "html.parser")
        check = service._check_internal_links(soup, "")
        assert check.passed is True

    def test_no_links(self, service):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("", "html.parser")
        check = service._check_internal_links(soup, "Just plain text.")
        assert check.passed is False


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class TestImages:
    def test_images_with_alt(self, service):
        from bs4 import BeautifulSoup
        md = "![Family gaming](https://example.com/img.jpg)"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_images(soup, md)
        assert check.passed is True
        assert check.details["with_alt"] == 1

    def test_no_images(self, service):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("", "html.parser")
        check = service._check_images(soup, "No images here.")
        assert check.passed is False

    def test_images_missing_alt(self, service):
        from bs4 import BeautifulSoup
        md = "![](https://example.com/img.jpg)"
        soup = BeautifulSoup("", "html.parser")
        check = service._check_images(soup, md)
        assert check.passed is False
        assert check.details["missing_alt"] == 1

    def test_html_images(self, service):
        from bs4 import BeautifulSoup
        html = '<img src="test.jpg" alt="Test image"><img src="test2.jpg" alt="">'
        soup = BeautifulSoup(html, "html.parser")
        check = service._check_images(soup, "")
        assert check.passed is False
        assert check.details["image_count"] == 2


# ---------------------------------------------------------------------------
# Schema Markup
# ---------------------------------------------------------------------------


class TestSchemaMarkup:
    def test_schema_present(self, service):
        schema = {"@type": "Article", "headline": "Test Article"}
        check = service._check_schema_markup(schema)
        assert check.passed is True

    def test_no_schema(self, service):
        check = service._check_schema_markup(None)
        assert check.passed is False

    def test_empty_schema(self, service):
        check = service._check_schema_markup({})
        # Empty dict evaluates to falsy in the `if schema_markup and isinstance(...)` check
        assert check.passed is False


# ---------------------------------------------------------------------------
# Extract Plain Text
# ---------------------------------------------------------------------------


class TestExtractPlainText:
    def test_strips_markdown(self, service):
        md = "# Heading\n\n**Bold** and *italic* text.\n\n- List item\n- Another"
        text = service._extract_plain_text(md)
        assert "# " not in text
        assert "**" not in text
        assert "*" not in text
        assert "Heading" in text
        assert "Bold" in text

    def test_strips_links(self, service):
        md = "Check [this link](https://example.com) out."
        text = service._extract_plain_text(md)
        assert "this link" in text
        assert "https://example.com" not in text

    def test_strips_images(self, service):
        md = "Look at this ![alt text](https://example.com/img.jpg) image."
        text = service._extract_plain_text(md)
        assert "https://example.com/img.jpg" not in text

    def test_strips_code_blocks(self, service):
        md = "Text before\n```python\nprint('hello')\n```\nText after"
        text = service._extract_plain_text(md)
        assert "print" not in text
        assert "Text before" in text
        assert "Text after" in text


# ---------------------------------------------------------------------------
# Aggregate run_checks
# ---------------------------------------------------------------------------


class TestRunChecks:
    def test_good_article_has_checks(self, service, good_article_md):
        checks = service.run_checks(
            content_markdown=good_article_md,
            keyword="minecraft tips for parents",
            seo_title="Best Minecraft Tips for Parents - Complete Guide 2026",
            meta_description="Learn the best minecraft tips for parents in this comprehensive guide to gaming with your children and building connections.",
            schema_markup={"@type": "Article", "headline": "Test"},
        )
        assert len(checks) == 10
        names = [c.name for c in checks]
        assert "word_count" in names
        assert "em_dashes" in names
        assert "readability" in names
        assert "keyword_placement" in names

    def test_bad_article_has_failures(self, service, bad_article_md):
        checks = service.run_checks(
            content_markdown=bad_article_md,
            keyword="minecraft tips",
            seo_title="Short",
            meta_description="",
        )
        failed = [c for c in checks if not c.passed]
        assert len(failed) >= 3  # word count, em dashes, meta desc at minimum


# ---------------------------------------------------------------------------
# validate_article (DB integration)
# ---------------------------------------------------------------------------


class TestValidateArticle:
    def test_article_not_found(self, service):
        service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with pytest.raises(ValueError, match="Article not found"):
            service.validate_article("nonexistent-id")

    def test_validate_saves_report(self, service, good_article_md):
        article_id = str(uuid4())
        article_data = {
            "id": article_id,
            "keyword": "minecraft tips",
            "seo_title": "Best Minecraft Tips for Parents - Complete Guide 2026",
            "meta_description": "Learn the best minecraft tips for parents in this comprehensive guide to gaming with children and building connections.",
            "phase_c_output": good_article_md,
            "content_html": "",
            "schema_markup": {"@type": "Article"},
        }

        # Mock get article
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[article_data])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_select

        # Mock update
        mock_update = MagicMock()
        mock_update.eq.return_value.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value = mock_update

        result = service.validate_article(article_id)

        assert "passed" in result
        assert "total_checks" in result
        assert result["total_checks"] == 10
        assert "checks" in result

        # Verify update was called to save report
        service.supabase.table.return_value.update.assert_called()


# ---------------------------------------------------------------------------
# Build Result
# ---------------------------------------------------------------------------


class TestBuildResult:
    def test_pass_with_only_warnings(self, service):
        from viraltracker.services.seo_pipeline.models import QACheck
        checks = [
            QACheck(name="test1", passed=True, message="OK"),
            QACheck(name="test2", passed=False, severity="warning", message="Minor issue"),
        ]
        result = service._build_result("test-id", checks)
        assert result["passed"] is True  # Warnings don't fail

    def test_fail_with_errors(self, service):
        from viraltracker.services.seo_pipeline.models import QACheck
        checks = [
            QACheck(name="test1", passed=True, message="OK"),
            QACheck(name="test2", passed=False, severity="error", message="Critical"),
        ]
        result = service._build_result("test-id", checks)
        assert result["passed"] is False
        assert result["error_count"] == 1
