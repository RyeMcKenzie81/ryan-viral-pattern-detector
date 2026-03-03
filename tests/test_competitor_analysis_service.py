"""
Unit tests for CompetitorAnalysisService.

Covers:
- _calculate_flesch(): Flesch Reading Ease formula
- _count_syllables(): vowel-group heuristic
- _classify_external_link(): domain classification
- _parse_html_metrics(): HTML parsing and metric extraction
- _calculate_winning_formula(): aggregate stats and opportunities
- analyze_urls(): end-to-end with mocked scraping + DB

Run with: pytest tests/test_competitor_analysis_service.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from viraltracker.services.seo_pipeline.services.competitor_analysis_service import (
    CompetitorAnalysisService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Service with mocked dependencies."""
    mock_supabase = MagicMock()
    mock_web_scraping = MagicMock()
    return CompetitorAnalysisService(
        supabase_client=mock_supabase,
        web_scraping_service=mock_web_scraping,
    )


SAMPLE_HTML = """
<html>
<head>
    <title>Minecraft Parenting Tips for Busy Parents</title>
    <meta name="description" content="Learn the best minecraft parenting tips.">
</head>
<body>
    <h1>Minecraft Parenting Tips</h1>
    <p>This is the introduction paragraph with enough words to count as a real paragraph for metric extraction purposes.</p>
    <h2>Why Minecraft Matters</h2>
    <p>Minecraft is educational and fun for kids of all ages and parents should understand its value for development.</p>
    <h2>Top Tips for Parents</h2>
    <p>Here are the top tips for parents who want to engage with their children through Minecraft gaming.</p>
    <h3>Tip 1: Play Together</h3>
    <p>Playing together builds connection and creates lasting memories with your children through shared gaming experiences.</p>
    <h3>Tip 2: Set Boundaries</h3>
    <p>Setting boundaries helps children develop healthy gaming habits and time management skills for the long term.</p>
    <h2>Frequently Asked Questions</h2>
    <h3>Is Minecraft good for kids?</h3>
    <p>Yes, it teaches creativity and problem-solving skills that translate well to real world applications for children.</p>
    <a href="/about">About Us</a>
    <a href="https://wikipedia.org/minecraft">Wikipedia</a>
    <a href="https://harvard.edu/study">Study</a>
    <img src="hero.jpg" alt="Family playing Minecraft">
    <img src="screenshot.png" alt="">
    <img src="logo.png">
    <table><tr><td>Data</td></tr></table>
    <script type="application/ld+json">{"@type": "Article", "name": "Test"}</script>
    <button>Subscribe</button>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _count_syllables()
# ---------------------------------------------------------------------------


class TestCountSyllables:
    def test_one_syllable(self):
        assert CompetitorAnalysisService._count_syllables("the") == 1
        assert CompetitorAnalysisService._count_syllables("cat") == 1
        assert CompetitorAnalysisService._count_syllables("a") == 1

    def test_two_syllables(self):
        assert CompetitorAnalysisService._count_syllables("hello") == 2
        assert CompetitorAnalysisService._count_syllables("parent") == 2

    def test_three_syllables(self):
        assert CompetitorAnalysisService._count_syllables("parenting") == 3
        assert CompetitorAnalysisService._count_syllables("minecraft") == 3  # mi-ne-craft (vowel-group heuristic)

    def test_silent_e(self):
        # "game" has vowel groups a, e -> 2, minus 1 for trailing e = 1
        assert CompetitorAnalysisService._count_syllables("game") == 1
        assert CompetitorAnalysisService._count_syllables("time") == 1

    def test_minimum_one(self):
        assert CompetitorAnalysisService._count_syllables("x") >= 1
        assert CompetitorAnalysisService._count_syllables("q") >= 1


# ---------------------------------------------------------------------------
# _calculate_flesch()
# ---------------------------------------------------------------------------


class TestCalculateFlesch:
    def test_simple_text(self):
        text = "The cat sat on the mat. It was good."
        score = CompetitorAnalysisService._calculate_flesch(text)
        assert 50 < score <= 100

    def test_complex_text(self):
        text = (
            "The implementation of sophisticated pedagogical methodologies "
            "necessitates comprehensive understanding of developmental psychology. "
            "Furthermore, the integration of technological infrastructure requires "
            "substantial institutional investment."
        )
        score = CompetitorAnalysisService._calculate_flesch(text)
        assert score < 50

    def test_empty_text(self):
        assert CompetitorAnalysisService._calculate_flesch("") == 0.0

    def test_single_word(self):
        # Edge case: no sentence-ending punctuation
        score = CompetitorAnalysisService._calculate_flesch("hello")
        assert isinstance(score, float)

    def test_clamped_to_range(self):
        score = CompetitorAnalysisService._calculate_flesch("A. B. C. D. E.")
        assert 0 <= score <= 100

    def test_returns_float(self):
        score = CompetitorAnalysisService._calculate_flesch("This is a test sentence.")
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# _classify_external_link()
# ---------------------------------------------------------------------------


class TestClassifyExternalLink:
    def test_wikipedia(self):
        assert CompetitorAnalysisService._classify_external_link("en.wikipedia.org") == "wikipedia"
        assert CompetitorAnalysisService._classify_external_link("wikipedia.org") == "wikipedia"

    def test_educational(self):
        assert CompetitorAnalysisService._classify_external_link("harvard.edu") == "educational"
        assert CompetitorAnalysisService._classify_external_link("mit.edu") == "educational"

    def test_government(self):
        assert CompetitorAnalysisService._classify_external_link("cdc.gov") == "government"
        assert CompetitorAnalysisService._classify_external_link("nih.gov") == "government"

    def test_forum(self):
        assert CompetitorAnalysisService._classify_external_link("reddit.com") == "forum"
        assert CompetitorAnalysisService._classify_external_link("quora.com") == "forum"

    def test_video(self):
        assert CompetitorAnalysisService._classify_external_link("youtube.com") == "video"
        assert CompetitorAnalysisService._classify_external_link("vimeo.com") == "video"

    def test_general(self):
        assert CompetitorAnalysisService._classify_external_link("example.com") == "general"
        assert CompetitorAnalysisService._classify_external_link("blog.com") == "general"


# ---------------------------------------------------------------------------
# _parse_html_metrics()
# ---------------------------------------------------------------------------


class TestParseHtmlMetrics:
    def test_extracts_title(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["title"] == "Minecraft Parenting Tips for Busy Parents"

    def test_extracts_meta_description(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert "minecraft parenting tips" in metrics["meta_description"]

    def test_counts_headings(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["h1_count"] == 1
        assert metrics["h2_count"] == 3  # Why Minecraft, Top Tips, FAQ
        assert metrics["h3_count"] == 3  # Tip 1, Tip 2, FAQ question

    def test_counts_images(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["image_count"] == 3
        assert metrics["images_with_alt"] == 1  # Only hero.jpg has non-empty alt

    def test_counts_links(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["internal_link_count"] == 1  # /about
        assert metrics["external_link_count"] == 2  # wikipedia + harvard

    def test_detects_schema(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["has_schema"] is True
        assert "Article" in metrics["schema_types"]

    def test_detects_faq(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["has_faq"] is True

    def test_detects_tables(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["has_tables"] is True
        assert metrics["table_count"] == 1

    def test_counts_ctas(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["cta_count"] >= 1  # Subscribe button

    def test_word_count_positive(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert metrics["word_count"] > 0

    def test_body_text_extracted(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(SAMPLE_HTML, "https://example.com")
        assert "_body_text" in metrics
        assert len(metrics["_body_text"]) > 0

    def test_empty_html(self):
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics("", "https://example.com")
        assert metrics["h1_count"] == 0
        assert metrics["word_count"] == 0

    def test_minimal_html(self):
        html = "<html><body><p>Hello world test.</p></body></html>"
        service = CompetitorAnalysisService()
        metrics = service._parse_html_metrics(html, "https://example.com")
        assert metrics["word_count"] > 0


# ---------------------------------------------------------------------------
# _calculate_winning_formula()
# ---------------------------------------------------------------------------


class TestCalculateWinningFormula:
    def _make_result(self, **overrides):
        base = {
            "word_count": 2000, "h2_count": 5, "h3_count": 3,
            "paragraph_count": 20, "flesch_reading_ease": 65.0,
            "internal_link_count": 5, "external_link_count": 3,
            "image_count": 8, "cta_count": 2,
            "has_schema": True, "has_faq": True, "has_author": True,
            "has_toc": False, "has_breadcrumbs": True,
        }
        base.update(overrides)
        return base

    def test_single_result(self):
        service = CompetitorAnalysisService()
        results = [self._make_result(word_count=2000)]
        wf = service._calculate_winning_formula(results)
        assert wf["competitor_count"] == 1
        assert wf["avg_word_count"] == 2000
        assert wf["target_word_count"] == round(2000 * 1.12)

    def test_multiple_results(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(word_count=2000),
            self._make_result(word_count=3000),
        ]
        wf = service._calculate_winning_formula(results)
        assert wf["competitor_count"] == 2
        assert wf["avg_word_count"] == 2500
        assert wf["target_word_count"] == round(2500 * 1.12)

    def test_empty_results(self):
        service = CompetitorAnalysisService()
        wf = service._calculate_winning_formula([])
        assert wf == {}

    def test_opportunity_schema_low(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(has_schema=False),
            self._make_result(has_schema=False),
            self._make_result(has_schema=True),
        ]
        wf = service._calculate_winning_formula(results)
        assert wf["pct_with_schema"] < 50
        schema_opps = [o for o in wf["opportunities"] if o["feature"] == "schema_markup"]
        assert len(schema_opps) == 1
        assert schema_opps[0]["severity"] == "HIGH"

    def test_opportunity_faq_low(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(has_faq=False),
            self._make_result(has_faq=False),
            self._make_result(has_faq=True),
        ]
        wf = service._calculate_winning_formula(results)
        faq_opps = [o for o in wf["opportunities"] if o["feature"] == "faq_section"]
        assert len(faq_opps) == 1

    def test_no_opportunities_when_all_have_features(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(has_schema=True, has_faq=True, has_author=True, has_toc=True),
            self._make_result(has_schema=True, has_faq=True, has_author=True, has_toc=True),
        ]
        wf = service._calculate_winning_formula(results)
        assert wf["opportunities"] == []

    def test_flesch_average(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(flesch_reading_ease=60.0),
            self._make_result(flesch_reading_ease=70.0),
        ]
        wf = service._calculate_winning_formula(results)
        assert wf["avg_flesch_score"] == 65.0

    def test_flesch_with_none_values(self):
        service = CompetitorAnalysisService()
        results = [
            self._make_result(flesch_reading_ease=60.0),
            self._make_result(flesch_reading_ease=None),
        ]
        wf = service._calculate_winning_formula(results)
        assert wf["avg_flesch_score"] == 60.0


# ---------------------------------------------------------------------------
# analyze_urls() — mocked scraping + DB
# ---------------------------------------------------------------------------


class TestAnalyzeUrls:
    def test_successful_analysis(self, service):
        """Full flow: scrape succeeds, metrics extracted, saved to DB."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.html = SAMPLE_HTML
        mock_result.markdown = "# Test\n\nSome markdown content here."
        service.web_scraping.scrape_url.return_value = mock_result

        # Mock DB insert
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.insert.return_value = mock_insert

        result = service.analyze_urls(str(uuid4()), ["https://example.com/article"])
        assert result["analyzed_count"] == 1
        assert result["failed_count"] == 0
        assert len(result["results"]) == 1
        assert result["winning_formula"]["competitor_count"] == 1

    def test_scrape_failure(self, service):
        """Scrape fails gracefully."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Timeout"
        service.web_scraping.scrape_url.return_value = mock_result

        result = service.analyze_urls(str(uuid4()), ["https://example.com"])
        assert result["analyzed_count"] == 0
        assert result["failed_count"] == 1
        assert "https://example.com" in result["failed_urls"]

    def test_mixed_results(self, service):
        """Some URLs succeed, some fail."""
        success_result = MagicMock()
        success_result.success = True
        success_result.html = SAMPLE_HTML
        success_result.markdown = "content"

        fail_result = MagicMock()
        fail_result.success = False
        fail_result.error = "blocked"

        service.web_scraping.scrape_url.side_effect = [success_result, fail_result]

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.insert.return_value = mock_insert

        result = service.analyze_urls(
            str(uuid4()),
            ["https://good.com", "https://bad.com"],
        )
        assert result["analyzed_count"] == 1
        assert result["failed_count"] == 1

    def test_empty_urls(self, service):
        result = service.analyze_urls(str(uuid4()), [])
        assert result["analyzed_count"] == 0
        assert result["winning_formula"] == {}

    def test_exception_in_scrape(self, service):
        """Exception during scrape is caught, not raised."""
        service.web_scraping.scrape_url.side_effect = Exception("network error")

        result = service.analyze_urls(str(uuid4()), ["https://error.com"])
        assert result["analyzed_count"] == 0
        assert result["failed_count"] == 1
