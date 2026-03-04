"""
Tests for InterlinkingService — link suggestion, auto-linking, and bidirectional links.

Tests cover:
- Jaccard similarity calculation
- Anchor text generation
- Placement suggestion logic
- Pattern generation for auto-linking
- Paragraph link insertion
- suggest_links() with mocked DB
- auto_link_article() with mocked DB
- add_related_section() with mocked DB
"""

import pytest
from unittest.mock import MagicMock, patch, call

from viraltracker.services.seo_pipeline.services.interlinking_service import (
    InterlinkingService,
    GENERIC_WORDS,
)
from viraltracker.services.seo_pipeline.models import (
    LinkType,
    LinkStatus,
    LinkPriority,
    LinkPlacement,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def service():
    """Service with mocked Supabase client."""
    mock_supabase = MagicMock()
    return InterlinkingService(supabase_client=mock_supabase)


@pytest.fixture
def source_article():
    return {
        "id": "art-source-001",
        "project_id": "proj-001",
        "keyword": "how to build a gaming pc",
        "title": "How to Build a Gaming PC - Complete Guide",
        "published_url": "https://example.com/blogs/articles/how-to-build-a-gaming-pc",
        "content_html": "<h1>Gaming PC Guide</h1>\n<p>Building a gaming PC is exciting and rewarding.</p>\n<p>First choose your gaming monitor carefully.</p>\n<p>You need the best graphics card for gaming.</p>",
        "status": "published",
    }


@pytest.fixture
def target_articles():
    return [
        {
            "id": "art-target-001",
            "project_id": "proj-001",
            "keyword": "best gaming monitor for pc",
            "title": "Best Gaming Monitor for PC",
            "published_url": "https://example.com/blogs/articles/best-gaming-monitor",
            "content_html": "<p>Monitor content here.</p>",
            "status": "published",
        },
        {
            "id": "art-target-002",
            "project_id": "proj-001",
            "keyword": "best graphics card for gaming",
            "title": "Best Graphics Card for Gaming",
            "published_url": "https://example.com/blogs/articles/best-graphics-card",
            "content_html": "<p>GPU content here.</p>",
            "status": "published",
        },
        {
            "id": "art-target-003",
            "project_id": "proj-001",
            "keyword": "cooking recipes for beginners",
            "title": "Cooking Recipes for Beginners",
            "published_url": "",
            "content_html": "<p>Unrelated article.</p>",
            "status": "published",
        },
    ]


# =============================================================================
# JACCARD SIMILARITY
# =============================================================================

class TestJaccardSimilarity:
    def test_identical_keywords(self):
        result = InterlinkingService._jaccard_similarity("gaming pc build", "gaming pc build")
        assert result == 1.0

    def test_no_overlap(self):
        result = InterlinkingService._jaccard_similarity("gaming pc", "cooking recipes")
        assert result == 0.0

    def test_partial_overlap(self):
        # "gaming pc build" & "gaming monitor build" -> intersection={gaming, build}, union={gaming, pc, build, monitor}
        result = InterlinkingService._jaccard_similarity("gaming pc build", "gaming monitor build")
        assert result == pytest.approx(0.5, abs=0.01)

    def test_empty_keyword1(self):
        result = InterlinkingService._jaccard_similarity("", "gaming pc")
        assert result == 0.0

    def test_empty_keyword2(self):
        result = InterlinkingService._jaccard_similarity("gaming pc", "")
        assert result == 0.0

    def test_both_empty(self):
        result = InterlinkingService._jaccard_similarity("", "")
        assert result == 0.0

    def test_case_insensitive(self):
        result = InterlinkingService._jaccard_similarity("Gaming PC", "gaming pc")
        assert result == 1.0

    def test_single_word_overlap(self):
        # "how to build a gaming pc" & "best gaming monitor for pc"
        # words1={how,to,build,a,gaming,pc}, words2={best,gaming,monitor,for,pc}
        # intersection={gaming,pc}, union={how,to,build,a,gaming,pc,best,monitor,for}
        result = InterlinkingService._jaccard_similarity(
            "how to build a gaming pc", "best gaming monitor for pc"
        )
        assert 0.2 <= result <= 0.3  # 2/9 = 0.222


# =============================================================================
# ANCHOR TEXT GENERATION
# =============================================================================

class TestGenerateAnchorTexts:
    def test_basic_keyword(self):
        anchors = InterlinkingService._generate_anchor_texts("gaming pc setup")
        assert "gaming pc setup" in anchors
        assert any("learn more about" in a for a in anchors)
        assert any("guide to" in a for a in anchors)

    def test_how_to_keyword(self):
        anchors = InterlinkingService._generate_anchor_texts("how to build a gaming pc")
        assert "how to build a gaming pc" in anchors
        assert "build a gaming pc" in anchors

    def test_generic_words_stripped(self):
        anchors = InterlinkingService._generate_anchor_texts("best gaming pc guide")
        # Should have a version without "best" and "guide"
        assert any("gaming pc" == a for a in anchors)

    def test_capitalized_variation(self):
        anchors = InterlinkingService._generate_anchor_texts("gaming pc setup")
        assert "Gaming pc setup" in anchors

    def test_empty_keyword(self):
        anchors = InterlinkingService._generate_anchor_texts("")
        assert anchors == []

    def test_short_results_filtered(self):
        anchors = InterlinkingService._generate_anchor_texts("pc")
        # All very short anchors should be filtered to >3 chars
        for a in anchors:
            assert len(a) > 3

    def test_no_duplicates(self):
        anchors = InterlinkingService._generate_anchor_texts("gaming pc build")
        assert len(anchors) == len(set(anchors))


# =============================================================================
# PLACEMENT SUGGESTION
# =============================================================================

class TestSuggestPlacement:
    def test_common_substantive_words_middle(self):
        result = InterlinkingService._suggest_placement(
            "how to build a gaming pc", "best gaming setup"
        )
        assert result == LinkPlacement.MIDDLE

    def test_no_common_words_end(self):
        result = InterlinkingService._suggest_placement(
            "cooking recipes", "gaming pc build"
        )
        assert result == LinkPlacement.END

    def test_common_short_words_end(self):
        # "a", "to", "the" are <=3 chars, should be ignored
        result = InterlinkingService._suggest_placement(
            "how to cook a meal", "how to fly a kite"
        )
        assert result == LinkPlacement.END

    def test_common_long_word_middle(self):
        result = InterlinkingService._suggest_placement(
            "minecraft building tips", "minecraft farming guide"
        )
        assert result == LinkPlacement.MIDDLE


# =============================================================================
# PATTERN GENERATION
# =============================================================================

class TestGenerateMatchPatterns:
    def test_basic_article(self):
        article = {"title": "Best Gaming Monitor for PC", "keyword": "best gaming monitor for pc"}
        patterns = InterlinkingService._generate_match_patterns(article)
        assert "best gaming monitor for pc" in patterns
        assert len(patterns) >= 1

    def test_how_to_keyword(self):
        article = {"title": "How to Build a Gaming PC", "keyword": "how to build a gaming pc"}
        patterns = InterlinkingService._generate_match_patterns(article)
        assert "how to build a gaming pc" in patterns
        assert "build a gaming pc" in patterns

    def test_title_with_parenthetical(self):
        article = {"title": "Gaming PC Setup (Beginner Guide)", "keyword": "gaming pc setup"}
        patterns = InterlinkingService._generate_match_patterns(article)
        # Should include title without parenthetical
        assert "gaming pc setup" in patterns

    def test_ngrams_generated(self):
        article = {"title": "", "keyword": "how to build a gaming pc"}
        patterns = InterlinkingService._generate_match_patterns(article)
        # 3-word n-grams
        three_word = [p for p in patterns if len(p.split()) == 3]
        assert len(three_word) > 0

    def test_min_length_filter(self):
        article = {"title": "Short", "keyword": "tiny"}
        patterns = InterlinkingService._generate_match_patterns(article)
        for p in patterns:
            assert len(p) >= 10

    def test_no_title_no_keyword(self):
        article = {"title": "", "keyword": ""}
        patterns = InterlinkingService._generate_match_patterns(article)
        assert patterns == []


# =============================================================================
# PARAGRAPH LINK INSERTION
# =============================================================================

class TestInsertLinksInParagraphs:
    def test_basic_insertion(self):
        html = "<p>Check out the best gaming monitor for your setup.</p>"
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 1
        assert '<a href="https://example.com/monitor">' in result["html"]

    def test_skip_paragraph_with_existing_link(self):
        html = '<p>Already has <a href="https://other.com">a link</a> and best gaming monitor.</p>'
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 0

    def test_skip_after_related_articles(self):
        html = (
            "<p>Content with best gaming monitor here.</p>"
            "<h2>Related Articles</h2>"
            "<p>This also has best gaming monitor but should be skipped.</p>"
        )
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 1
        # Only first paragraph should be linked

    def test_case_insensitive_matching(self):
        html = "<p>Learn about Best Gaming Monitor choices.</p>"
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 1

    def test_word_boundary_matching(self):
        html = "<p>The hypermonitoring tool is useful.</p>"
        patterns = ["monitoring"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitoring"
        )
        # "monitoring" is inside "hypermonitoring" — word boundary should prevent match
        assert result["count"] == 0

    def test_one_link_per_paragraph(self):
        html = "<p>The best gaming monitor and best gaming monitor again.</p>"
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 1
        assert result["html"].count("<a href=") == 1

    def test_no_match(self):
        html = "<p>Nothing related here at all.</p>"
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert result["count"] == 0
        assert result["html"] == html

    def test_multiple_paragraphs(self):
        html = (
            "<p>First paragraph about gaming monitors here.</p>"
            "<p>Second paragraph about gaming monitors here.</p>"
        )
        patterns = ["gaming monitors"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitors"
        )
        assert result["count"] == 2

    def test_preserves_original_case(self):
        html = "<p>The Best Gaming Monitor is great.</p>"
        patterns = ["best gaming monitor"]
        result = InterlinkingService._insert_links_in_paragraphs(
            html, patterns, "https://example.com/monitor"
        )
        assert "Best Gaming Monitor" in result["html"]
        assert '<a href="https://example.com/monitor">Best Gaming Monitor</a>' in result["html"]


# =============================================================================
# SUGGEST LINKS (FULL FLOW WITH MOCKED DB)
# =============================================================================

class TestSuggestLinks:
    def test_basic_suggestions(self, service, source_article, target_articles):
        """Test that suggest_links returns matching articles above threshold."""
        mock_exec = MagicMock()

        # _get_article returns source
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        # _get_project_articles returns targets
        service._get_project_articles = MagicMock(return_value=target_articles)

        # Don't save to DB
        result = service.suggest_links("art-source-001", min_similarity=0.1, save=False)

        assert result["article_id"] == "art-source-001"
        assert result["suggestion_count"] >= 1
        # The gaming-related articles should match, cooking should not
        target_keywords = [s["target_keyword"] for s in result["suggestions"]]
        assert "cooking recipes for beginners" not in target_keywords

    def test_no_suggestions_below_threshold(self, service, source_article, target_articles):
        """High threshold should yield zero suggestions."""
        mock_exec = MagicMock()
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)

        result = service.suggest_links("art-source-001", min_similarity=0.9, save=False)
        assert result["suggestion_count"] == 0

    def test_max_suggestions_limit(self, service, source_article, target_articles):
        mock_exec = MagicMock()
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)

        result = service.suggest_links("art-source-001", min_similarity=0.01, max_suggestions=1, save=False)
        assert result["suggestion_count"] <= 1

    def test_article_not_found(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        with pytest.raises(ValueError, match="Article not found"):
            service.suggest_links("nonexistent-id")

    def test_suggestions_sorted_by_similarity(self, service, source_article, target_articles):
        mock_exec = MagicMock()
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)

        result = service.suggest_links("art-source-001", min_similarity=0.01, save=False)
        similarities = [s["similarity"] for s in result["suggestions"]]
        assert similarities == sorted(similarities, reverse=True)

    def test_priority_assignment(self, service, source_article, target_articles):
        mock_exec = MagicMock()
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)

        result = service.suggest_links("art-source-001", min_similarity=0.01, save=False)
        for s in result["suggestions"]:
            if s["similarity"] > 0.4:
                assert s["priority"] == LinkPriority.HIGH.value
            else:
                assert s["priority"] == LinkPriority.MEDIUM.value


# =============================================================================
# AUTO-LINK ARTICLE (FULL FLOW WITH MOCKED DB)
# =============================================================================

class TestAutoLinkArticle:
    def test_basic_auto_link(self, service, source_article, target_articles):
        mock_exec = MagicMock()
        mock_exec.data = [source_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.auto_link_article("art-source-001")

        assert result["article_id"] == "art-source-001"
        assert result["links_added"] >= 1
        assert len(result["linked_articles"]) >= 1

    def test_no_content_html(self, service):
        article = {"id": "art-001", "content_html": "", "project_id": "proj-001"}
        mock_exec = MagicMock()
        mock_exec.data = [article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.auto_link_article("art-001")
        assert result["links_added"] == 0
        assert "message" in result

    def test_article_not_found(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        with pytest.raises(ValueError, match="Article not found"):
            service.auto_link_article("nonexistent-id")

    def test_skip_existing_links(self, service, target_articles):
        """Articles whose URL is already in HTML should be skipped."""
        article = {
            "id": "art-source-001",
            "project_id": "proj-001",
            "keyword": "how to build a gaming pc",
            "content_html": '<p>See <a href="https://example.com/blogs/articles/best-gaming-monitor">monitor</a>.</p>',
        }
        mock_exec = MagicMock()
        mock_exec.data = [article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=target_articles)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.auto_link_article("art-source-001")
        # The first target's URL is already in HTML, should be skipped
        linked_ids = [la["article_id"] for la in result.get("linked_articles", [])]
        assert "art-target-001" not in linked_ids

    def test_fallback_url_from_keyword(self, service):
        """Target without published_url should get a handle-based URL."""
        article = {
            "id": "art-source-001",
            "project_id": "proj-001",
            "keyword": "gaming pc",
            "content_html": "<p>You need the best cooking recipes for beginners guide.</p>",
        }
        target = {
            "id": "art-target-003",
            "project_id": "proj-001",
            "keyword": "cooking recipes for beginners",
            "title": "Cooking Recipes for Beginners",
            "published_url": "",
        }
        mock_exec = MagicMock()
        mock_exec.data = [article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec
        service._get_project_articles = MagicMock(return_value=[target])
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.auto_link_article("art-source-001")
        if result["links_added"] > 0:
            # Check the link uses the handle-based URL
            call_args = service._update_article_html.call_args
            updated_html = call_args[0][1]
            assert "/blogs/articles/cooking-recipes-for-beginners" in updated_html


# =============================================================================
# ADD RELATED SECTION (FULL FLOW WITH MOCKED DB)
# =============================================================================

class TestAddRelatedSection:
    def _mock_get_article(self, service, articles_map):
        """Helper to set up _get_article to return based on ID."""
        def mock_get(article_id):
            return articles_map.get(article_id)
        service._get_article = MagicMock(side_effect=mock_get)

    def test_basic_related_section(self, service, source_article, target_articles):
        articles_map = {
            "art-source-001": source_article,
            "art-target-001": target_articles[0],
            "art-target-002": target_articles[1],
        }
        self._mock_get_article(service, articles_map)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.add_related_section(
            "art-source-001",
            ["art-target-001", "art-target-002"],
        )

        assert result["articles_linked"] == 2
        assert result["placement"] == "end"
        assert len(result["related_articles"]) == 2

    def test_no_content_html(self, service):
        article = {"id": "art-001", "content_html": "", "project_id": "proj-001"}
        service._get_article = MagicMock(return_value=article)

        result = service.add_related_section("art-001", ["art-002"])
        assert result["articles_linked"] == 0
        assert "message" in result

    def test_existing_related_section(self, service):
        article = {
            "id": "art-001",
            "content_html": "<p>Content</p><h2>Related Articles</h2><ul><li>Existing</li></ul>",
        }
        service._get_article = MagicMock(return_value=article)

        result = service.add_related_section("art-001", ["art-002"])
        assert result["articles_linked"] == 0
        assert "already exists" in result["message"]

    def test_placement_before_faq(self, service, target_articles):
        article = {
            "id": "art-source-001",
            "content_html": "<p>Content</p>\n<h2>FAQ</h2>\n<p>Q&A here</p>",
            "project_id": "proj-001",
        }
        articles_map = {
            "art-source-001": article,
            "art-target-001": target_articles[0],
        }
        self._mock_get_article(service, articles_map)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.add_related_section("art-source-001", ["art-target-001"])
        assert result["placement"] == "before_faq"

    def test_placement_before_author_bio(self, service, target_articles):
        article = {
            "id": "art-source-001",
            "content_html": '<p>Content</p>\n<div style="background: #f8f9fa">Author bio</div>',
            "project_id": "proj-001",
        }
        articles_map = {
            "art-source-001": article,
            "art-target-001": target_articles[0],
        }
        self._mock_get_article(service, articles_map)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.add_related_section("art-source-001", ["art-target-001"])
        assert result["placement"] == "before_author_bio"

    def test_article_not_found(self, service):
        service._get_article = MagicMock(return_value=None)

        with pytest.raises(ValueError, match="Article not found"):
            service.add_related_section("nonexistent-id", ["art-002"])

    def test_no_valid_related_articles(self, service):
        article = {
            "id": "art-001",
            "content_html": "<p>Content here</p>",
        }
        # Source returns, but related articles don't exist
        def mock_get(article_id):
            return article if article_id == "art-001" else None
        service._get_article = MagicMock(side_effect=mock_get)

        result = service.add_related_section("art-001", ["nonexistent-001", "nonexistent-002"])
        assert result["articles_linked"] == 0
        assert "No valid related articles" in result["message"]

    def test_related_section_html_structure(self, service, target_articles):
        article = {
            "id": "art-source-001",
            "content_html": "<p>Content</p>",
            "project_id": "proj-001",
        }
        articles_map = {
            "art-source-001": article,
            "art-target-001": target_articles[0],
        }
        self._mock_get_article(service, articles_map)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        service.add_related_section("art-source-001", ["art-target-001"])

        updated_html = service._update_article_html.call_args[0][1]
        assert "<h2>Related Articles</h2>" in updated_html
        assert "Looking for more?" in updated_html
        assert "<ul>" in updated_html
        assert '<a href="' in updated_html

    def test_saves_link_records(self, service, target_articles):
        article = {
            "id": "art-source-001",
            "content_html": "<p>Content</p>",
            "project_id": "proj-001",
        }
        articles_map = {
            "art-source-001": article,
            "art-target-001": target_articles[0],
            "art-target-002": target_articles[1],
        }
        self._mock_get_article(service, articles_map)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        service.add_related_section(
            "art-source-001", ["art-target-001", "art-target-002"]
        )

        assert service._save_link_record.call_count == 2
        # Verify link type
        for c in service._save_link_record.call_args_list:
            assert c.kwargs["link_type"] == LinkType.BIDIRECTIONAL
            assert c.kwargs["status"] == LinkStatus.IMPLEMENTED
