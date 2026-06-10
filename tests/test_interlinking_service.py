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


# =============================================================================
# REMOVE RELATED SECTION
# =============================================================================

class TestRemoveRelatedSection:
    def test_removes_h2_related_section(self, service):
        """Removes <h2>Related Articles</h2> section from HTML."""
        html_with_related = (
            "<p>Great content here.</p>\n"
            "<h2>Related Articles</h2>\n"
            "<p>Looking for more? Check out these related articles:</p>\n"
            "<ul>\n"
            '<li><a href="/blogs/articles/foo">Foo</a></li>\n'
            "</ul>\n"
        )
        article = {
            "id": "art-001",
            "content_html": html_with_related,
        }
        service._get_article = MagicMock(return_value=article)
        service._update_article_html = MagicMock()

        result = service._remove_related_section("art-001")

        assert "<h2>Related Articles</h2>" not in result
        assert "Looking for more?" not in result
        assert "<ul>" not in result
        assert "<p>Great content here.</p>" in result
        service._update_article_html.assert_called_once()

    def test_removes_h3_variant(self, service):
        """Removes <h3>Related Articles</h3> variant from HTML."""
        html_with_related = (
            "<p>Content.</p>\n"
            "<h3>Related Articles</h3>\n"
            "<ul>\n"
            '<li><a href="/blogs/articles/bar">Bar</a></li>\n'
            "</ul>\n"
        )
        article = {
            "id": "art-002",
            "content_html": html_with_related,
        }
        service._get_article = MagicMock(return_value=article)
        service._update_article_html = MagicMock()

        result = service._remove_related_section("art-002")

        assert "<h3>Related Articles</h3>" not in result
        assert "<p>Content.</p>" in result

    def test_deletes_bidirectional_link_records(self, service):
        """Deletes BIDIRECTIONAL link records from DB when section is removed."""
        html_with_related = (
            "<p>Content.</p>\n"
            "<h2>Related Articles</h2>\n"
            "<ul>\n"
            '<li><a href="/foo">Foo</a></li>\n'
            "</ul>\n"
        )
        article = {
            "id": "art-003",
            "content_html": html_with_related,
        }
        service._get_article = MagicMock(return_value=article)
        service._update_article_html = MagicMock()

        # Set up mock chain for delete
        mock_delete_chain = MagicMock()
        service._supabase.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute = MagicMock()
        service._supabase.table.return_value.delete.return_value = mock_delete_chain
        mock_delete_chain.eq.return_value.eq.return_value.execute = MagicMock()

        service._remove_related_section("art-003")

        # Verify delete was called on seo_internal_links table
        service._supabase.table.assert_called_with("seo_internal_links")

    def test_noop_when_no_related_section(self, service):
        """No DB update when no Related section exists."""
        article = {
            "id": "art-004",
            "content_html": "<p>Just plain content.</p>",
        }
        service._get_article = MagicMock(return_value=article)
        service._update_article_html = MagicMock()

        result = service._remove_related_section("art-004")

        assert result == "<p>Just plain content.</p>"
        service._update_article_html.assert_not_called()

    def test_returns_empty_string_when_article_not_found(self, service):
        """Returns empty string when article doesn't exist."""
        service._get_article = MagicMock(return_value=None)

        result = service._remove_related_section("nonexistent-id")

        assert result == ""


# =============================================================================
# BATCH COUNT INBOUND LINKS
# =============================================================================

class TestBatchCountInboundLinks:
    def test_counts_correctly_with_multiple_targets(self, service):
        """Counts inbound links per target article correctly."""
        mock_result = MagicMock()
        mock_result.data = [
            {"target_article_id": "art-001"},
            {"target_article_id": "art-001"},
            {"target_article_id": "art-001"},
            {"target_article_id": "art-002"},
        ]
        service._supabase.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value = mock_result

        counts = service._batch_count_inbound_links(["art-001", "art-002", "art-003"])

        assert counts["art-001"] == 3
        assert counts["art-002"] == 1
        assert counts.get("art-003", 0) == 0

    def test_empty_list_returns_empty_dict(self, service):
        """Empty input list returns empty dict without DB call."""
        result = service._batch_count_inbound_links([])

        assert result == {}
        service._supabase.table.assert_not_called()

    def test_handles_db_errors_gracefully(self, service):
        """Returns empty dict on DB error instead of raising."""
        service._supabase.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.side_effect = Exception("DB connection lost")

        result = service._batch_count_inbound_links(["art-001"])

        assert result == {}


# =============================================================================
# VARIED ANCHOR
# =============================================================================

class TestVariedAnchor:
    def test_returns_auto_for_empty_keyword(self):
        """Returns '(auto)' for empty keyword."""
        result = InterlinkingService._varied_anchor("")
        assert result == "(auto)"

    def test_returns_auto_for_none_like_empty(self):
        """Returns '(auto)' for falsy keyword."""
        result = InterlinkingService._varied_anchor("")
        assert result == "(auto)"

    def test_always_returns_nonempty_for_valid_keyword(self):
        """Always returns a non-empty string for valid keyword across many runs."""
        for _ in range(50):
            result = InterlinkingService._varied_anchor("best gaming monitor")
            assert result
            assert len(result) > 0

    def test_returned_value_is_string(self):
        """Return type is always a string."""
        result = InterlinkingService._varied_anchor("how to build a pc")
        assert isinstance(result, str)


# =============================================================================
# INTERLINK CLUSTER
# =============================================================================

class TestInterlinkCluster:
    def _make_cluster_svc(self, cluster_return, spoke_ids_return):
        """Create a mock ClusterManagementService."""
        mock_cluster_svc = MagicMock()
        mock_cluster_svc.get_cluster.return_value = cluster_return
        mock_cluster_svc.get_cluster_spoke_article_ids.return_value = spoke_ids_return
        return mock_cluster_svc

    @staticmethod
    def _cms_patch():
        return patch(
            "viraltracker.services.seo_pipeline.services.cluster_management_service.ClusterManagementService"
        )

    def test_raises_when_cluster_not_found(self, service):
        """Raises ValueError when cluster doesn't exist."""
        mock_svc = self._make_cluster_svc(None, [])
        with self._cms_patch() as MockCMS:
            MockCMS.return_value = mock_svc
            with pytest.raises(ValueError, match="Cluster not found"):
                service.interlink_cluster("nonexistent-cluster-id")

    def test_returns_early_when_no_article_ids(self, service):
        """Returns zeros when cluster has no article IDs."""
        mock_svc = self._make_cluster_svc({"id": "cluster-001", "spokes": []}, [])
        with self._cms_patch() as MockCMS:
            MockCMS.return_value = mock_svc
            result = service.interlink_cluster("cluster-001")

            assert result["articles_processed"] == 0
            assert result["links_added"] == 0
            assert result["related_sections_added"] == 0

    def test_returns_early_when_less_than_2_published(self, service):
        """Returns early with error message when < 2 published articles."""
        mock_svc = self._make_cluster_svc(
            {"id": "cluster-001", "spokes": []}, ["art-001", "art-002"]
        )
        with self._cms_patch() as MockCMS:
            MockCMS.return_value = mock_svc

            # Only one article has a published_url
            def mock_get(article_id):
                if article_id == "art-001":
                    return {"id": "art-001", "published_url": "https://example.com/a1", "content_html": "<p>Content</p>"}
                return {"id": "art-002", "published_url": "", "content_html": "<p>Content</p>"}

            service._get_article = MagicMock(side_effect=mock_get)

            result = service.interlink_cluster("cluster-001")

            assert result["articles_processed"] == 0
            assert result["errors"][0]["message"] == "Need at least 2 published articles to interlink"

    def test_processes_articles_adds_links_rebuilds_related(self, service):
        """Full flow: processes articles, auto-links, removes/rebuilds related sections."""
        mock_svc = self._make_cluster_svc(
            {
                "id": "cluster-001",
                "spokes": [
                    {"role": "pillar", "article_id": "art-001"},
                    {"role": "spoke", "article_id": "art-002"},
                    {"role": "spoke", "article_id": "art-003"},
                ],
            },
            ["art-001", "art-002", "art-003"],
        )
        with self._cms_patch() as MockCMS:
            MockCMS.return_value = mock_svc
            mock_cluster_svc = MagicMock()
            mock_cluster_svc.get_cluster.return_value = {
                "id": "cluster-001",
                "spokes": [
                    {"role": "pillar", "article_id": "art-001"},
                    {"role": "spoke", "article_id": "art-002"},
                    {"role": "spoke", "article_id": "art-003"},
                ],
            }
            mock_cluster_svc.get_cluster_spoke_article_ids.return_value = ["art-001", "art-002", "art-003"]
            MockCMS.return_value = mock_cluster_svc

            articles = {
                "art-001": {"id": "art-001", "keyword": "gaming pc guide", "published_url": "https://example.com/a1", "content_html": "<p>Pillar content.</p>", "project_id": "proj-001"},
                "art-002": {"id": "art-002", "keyword": "best gaming monitor", "published_url": "https://example.com/a2", "content_html": "<p>Spoke 1 content.</p>", "project_id": "proj-001"},
                "art-003": {"id": "art-003", "keyword": "best graphics card", "published_url": "https://example.com/a3", "content_html": "<p>Spoke 2 content.</p>", "project_id": "proj-001"},
            }
            service._get_article = MagicMock(side_effect=lambda aid: articles.get(aid))

            # Mock auto_link_article to return some links
            service.auto_link_article = MagicMock(return_value={"links_added": 1, "linked_articles": []})
            # Mock _remove_related_section
            service._remove_related_section = MagicMock(return_value="<p>cleaned</p>")
            # Mock add_related_section
            service.add_related_section = MagicMock(return_value={"articles_linked": 2, "placement": "end", "related_articles": []})
            # Mock _save_link_record
            service._save_link_record = MagicMock()

            result = service.interlink_cluster("cluster-001")

            assert result["articles_processed"] == 3
            assert result["links_added"] == 3  # 1 link per article × 3 articles
            assert result["related_sections_added"] == 3
            assert result["errors"] == []

            # Verify auto_link was called for each article
            assert service.auto_link_article.call_count == 3

            # Verify related section was removed then rebuilt for each
            assert service._remove_related_section.call_count == 3
            assert service.add_related_section.call_count == 3

            # Verify cluster link records were saved (pillar→spoke + spoke→pillar)
            assert service._save_link_record.call_count > 0


# =============================================================================
# FIND LINKING OPPORTUNITIES
# =============================================================================

class TestFindLinkingOpportunities:
    def test_returns_empty_when_no_articles(self, service):
        """Returns empty opportunities when no articles exist for brand."""
        mock_result = MagicMock()
        mock_result.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.not_.return_value.is_.return_value.execute.return_value = mock_result

        result = service.find_linking_opportunities("brand-001", "org-001")

        assert result["opportunities"] == []
        assert result["total_scanned"] == 0

    def test_filters_by_position_range(self, service):
        """Only articles in position range are returned as opportunities."""
        articles = [
            {"id": "art-001", "keyword": "gaming pc", "title": "Gaming PC", "published_url": "https://example.com/a1", "project_id": "proj-001"},
            {"id": "art-002", "keyword": "cooking tips", "title": "Cooking Tips", "published_url": "https://example.com/a2", "project_id": "proj-001"},
        ]
        mock_articles_result = MagicMock()
        mock_articles_result.data = articles

        # art-001: position 15 (in range 8-30), 100 impressions, growing
        # art-002: position 3 (out of range), 100 impressions, not growing
        recent_data = [
            {"article_id": "art-001", "impressions": 100, "average_position": 15.0},
            {"article_id": "art-002", "impressions": 100, "average_position": 3.0},
        ]
        mock_recent_result = MagicMock()
        mock_recent_result.data = recent_data

        prior_data = [
            {"article_id": "art-001", "impressions": 80},
            {"article_id": "art-002", "impressions": 100},
        ]
        mock_prior_result = MagicMock()
        mock_prior_result.data = prior_data

        # Set up the chain of calls — use side_effect for sequential calls on table()
        mock_table = MagicMock()

        call_count = {"n": 0}
        def table_side_effect(name):
            call_count["n"] += 1
            mock_chain = MagicMock()
            if name == "seo_articles":
                mock_chain.select.return_value.eq.return_value.not_.return_value.is_.return_value.execute.return_value = mock_articles_result
                return mock_chain
            elif name == "seo_article_analytics":
                # First call = recent analytics, second = prior analytics, third = last sync
                if call_count["n"] <= 3:
                    # Recent
                    mock_chain.select.return_value.in_.return_value.eq.return_value.gte.return_value.execute.return_value = mock_recent_result
                elif call_count["n"] <= 4:
                    # Prior
                    mock_chain.select.return_value.in_.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_prior_result
                else:
                    # Last sync
                    mock_chain.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
                return mock_chain
            elif name == "seo_internal_links":
                mock_chain.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                mock_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                return mock_chain
            return mock_chain

        service._supabase.table = MagicMock(side_effect=table_side_effect)
        service._get_project_articles = MagicMock(return_value=[])

        result = service.find_linking_opportunities("brand-001", "org-001")

        # Only art-001 should be in opportunities (position 15 is in range, 100 impressions >= 50 floor)
        opp_ids = [o["article_id"] for o in result["opportunities"]]
        assert "art-001" in opp_ids
        # art-002 position 3 is out of range 8-30, and wow_growth=0 < 0.1 min, so filtered out
        assert "art-002" not in opp_ids

    def test_opportunities_sorted_by_score(self, service):
        """Opportunities are sorted by composite score descending."""
        articles = [
            {"id": "art-001", "keyword": "gaming pc", "title": "Gaming PC", "published_url": "https://example.com/a1", "project_id": "proj-001"},
            {"id": "art-002", "keyword": "monitor guide", "title": "Monitor Guide", "published_url": "https://example.com/a2", "project_id": "proj-001"},
        ]
        mock_articles_result = MagicMock()
        mock_articles_result.data = articles

        # art-001: position 10, 200 impressions (higher score)
        # art-002: position 20, 100 impressions (lower score)
        recent_data = [
            {"article_id": "art-001", "impressions": 200, "average_position": 10.0},
            {"article_id": "art-002", "impressions": 100, "average_position": 20.0},
        ]
        mock_recent_result = MagicMock()
        mock_recent_result.data = recent_data

        prior_data = [
            {"article_id": "art-001", "impressions": 100},
            {"article_id": "art-002", "impressions": 50},
        ]
        mock_prior_result = MagicMock()
        mock_prior_result.data = prior_data

        call_count = {"n": 0}
        def table_side_effect(name):
            call_count["n"] += 1
            mock_chain = MagicMock()
            if name == "seo_articles":
                mock_chain.select.return_value.eq.return_value.not_.return_value.is_.return_value.execute.return_value = mock_articles_result
                return mock_chain
            elif name == "seo_article_analytics":
                if call_count["n"] <= 3:
                    mock_chain.select.return_value.in_.return_value.eq.return_value.gte.return_value.execute.return_value = mock_recent_result
                elif call_count["n"] <= 4:
                    mock_chain.select.return_value.in_.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_prior_result
                else:
                    mock_chain.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
                return mock_chain
            elif name == "seo_internal_links":
                mock_chain.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                mock_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                return mock_chain
            return mock_chain

        service._supabase.table = MagicMock(side_effect=table_side_effect)
        service._get_project_articles = MagicMock(return_value=[])

        result = service.find_linking_opportunities("brand-001", "org-001")

        if len(result["opportunities"]) >= 2:
            scores = [o["score"] for o in result["opportunities"]]
            assert scores == sorted(scores, reverse=True)


# =============================================================================
# §6 interlinking workstream — D1/D3/D5 behaviors
# =============================================================================

class TestSaveLinkRecordIdempotent:
    """D5.2: re-running interlinking must not accumulate duplicate link rows."""

    def _chain(self, existing_data):
        from unittest.mock import MagicMock
        sel = MagicMock()
        sel.select.return_value = sel
        sel.eq.return_value = sel
        sel.limit.return_value = sel
        sel.execute.return_value = MagicMock(data=existing_data)
        sel.update.return_value = sel
        sel.insert.return_value = sel
        return sel

    def test_updates_when_record_exists(self, service):
        from viraltracker.services.seo_pipeline.models import LinkType, LinkStatus
        chain = self._chain([{"id": "link-1"}])
        service._supabase.table = MagicMock(return_value=chain)
        service._save_link_record("a", "b", LinkType.CLUSTER, LinkStatus.IMPLEMENTED)
        assert chain.update.called
        assert not chain.insert.called

    def test_inserts_when_record_absent(self, service):
        from viraltracker.services.seo_pipeline.models import LinkType, LinkStatus
        chain = self._chain([])
        service._supabase.table = MagicMock(return_value=chain)
        service._save_link_record("a", "b", LinkType.CLUSTER, LinkStatus.IMPLEMENTED)
        assert chain.insert.called
        assert not chain.update.called


class TestAutoLinkScopingAndCap:
    """D5.3 (cluster scope) + D1 (link cap) on auto_link_article."""

    def test_restricts_to_candidate_articles(self, service, source_article, target_articles):
        service._get_article = MagicMock(return_value=source_article)
        service._get_project_articles = MagicMock(return_value=target_articles)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        # Only target-001 is a candidate; target-002 must NOT be linked even
        # though its phrase appears in the body.
        only = [target_articles[0]]
        result = service.auto_link_article("art-source-001", candidate_articles=only)

        linked_ids = {l["article_id"] for l in result["linked_articles"]}
        assert linked_ids <= {"art-target-001"}
        # project-wide fallback must not have been used
        service._get_project_articles.assert_not_called()

    def test_respects_max_links_cap(self, service, source_article, target_articles):
        service._get_article = MagicMock(return_value=source_article)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.auto_link_article(
            "art-source-001", candidate_articles=target_articles, max_links=1,
        )
        assert result["links_added"] <= 1

    def test_cap_is_cumulative_counts_existing_links(self, service, target_articles):
        # Body already has 1 internal blog link; with a cap of 1, no NEW link is
        # added even though a matchable phrase is present (Codex review #1 — the
        # cap must be cumulative, not per-run).
        article = {
            "id": "art-source-001",
            "project_id": "proj-001",
            "keyword": "gaming pc",
            "content_html": (
                '<p>See <a href="/blogs/articles/x">this</a>.</p>'
                "<p>Your gaming monitor matters a lot here.</p>"
            ),
            "status": "published",
        }
        service._get_article = MagicMock(return_value=article)
        service._update_article_html = MagicMock()
        service._save_link_record = MagicMock()

        result = service.auto_link_article(
            "art-source-001", candidate_articles=target_articles, max_links=1,
        )
        assert result["links_added"] == 0


class TestInterlinkDispatcher:
    """D3: one canonical entry point routes to cluster/article."""

    def test_cluster_scope_routes_to_interlink_cluster(self, service):
        service.interlink_cluster = MagicMock(return_value={"links_added": 3, "related_sections_added": 2, "errors": []})
        out = service.interlink(scope="cluster", cluster_id="c-1", brand_id="b", organization_id="o")
        service.interlink_cluster.assert_called_once()
        assert out["links_added"] == 3

    def test_cluster_scope_requires_cluster_id(self, service):
        with pytest.raises(ValueError, match="cluster_id"):
            service.interlink(scope="cluster")

    def test_unknown_scope_raises(self, service):
        with pytest.raises(ValueError, match="scope"):
            service.interlink(scope="bogus", article_id="a")


class TestContentLockInterlink:
    """content_locked must skip interlink writes/pushes on a human-owned body."""

    def test_auto_link_skips_when_locked(self, service):
        service._get_article = MagicMock(return_value={"id": "a1", "content_locked": True})
        result = service.auto_link_article("a1")
        assert result.get("skipped") == "content_locked"
        assert result["links_added"] == 0

    def test_add_related_section_skips_when_locked(self, service):
        service._get_article = MagicMock(return_value={"id": "a1", "content_locked": True})
        result = service.add_related_section("a1", ["a2", "a3"])
        assert result.get("skipped") == "content_locked"

    def test_push_to_cms_skips_when_locked(self, service):
        service._publisher_service = MagicMock()
        service._get_article = MagicMock(return_value={"id": "a1", "content_locked": True, "cms_article_id": "9"})
        assert service._push_html_to_cms("a1", "b", "o", "<p>x</p>") is False
        service._publisher_service.get_publisher.assert_not_called()

    def test_remove_related_section_leaves_locked_body_untouched(self, service):
        # This chokepoint also protects interlink(scope="article") and
        # rerun_interlinking, which strip the Related block before the
        # lock-aware add_related_section runs.
        html = (
            "<p>Body</p><h2>Related Articles</h2><ul><li>x</li></ul>"
        )
        service._get_article = MagicMock(
            return_value={"id": "a1", "content_locked": True, "content_html": html}
        )
        service._update_article_html = MagicMock()
        service._supabase = MagicMock()

        result = service._remove_related_section("a1")

        assert result == html  # returned unchanged
        service._update_article_html.assert_not_called()
        service._supabase.table.assert_not_called()  # no link-record deletes

    def test_remove_related_section_strips_when_unlocked(self, service):
        html = "<p>Body</p><h2>Related Articles</h2><ul><li>x</li></ul>"
        service._get_article = MagicMock(
            return_value={"id": "a1", "content_locked": False, "content_html": html}
        )
        service._update_article_html = MagicMock()
        service._supabase = MagicMock()

        result = service._remove_related_section("a1")

        assert "Related Articles" not in result
        service._update_article_html.assert_called_once()


class TestBuildRelatedIds:
    """Pillar=hub (links to all spokes, no orphans); spoke=pillar+capped."""

    def _members(self, n):
        return [{"id": f"a{i}"} for i in range(n)]

    def test_pillar_links_to_all_spokes_uncapped(self, service):
        members = self._members(10)
        related = service._build_related_ids("a0", "a0", members)
        assert set(related) == {f"a{i}" for i in range(1, 10)}  # all 9 others
        assert "a0" not in related

    def test_spoke_links_pillar_first_then_capped(self, service):
        members = self._members(10)
        related = service._build_related_ids("a5", "a0", members)
        assert related[0] == "a0"  # pillar first
        assert len(related) <= service.MAX_RELATED_LINKS
        assert "a5" not in related

    def test_no_pillar_falls_back_to_capped(self, service):
        members = self._members(10)
        related = service._build_related_ids("a3", None, members)
        assert len(related) <= service.MAX_RELATED_LINKS
        assert "a3" not in related


class TestCountInboundLinks:
    """Public canonical primitive for orphan detection — chunking + source scope."""

    def _links_return(self, service, rows):
        chain = MagicMock()
        for m in ["select", "in_", "eq"]:
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        service._supabase.table.return_value = chain
        return chain

    def test_counts_all_when_unscoped(self, service):
        self._links_return(service, [
            {"source_article_id": "a", "target_article_id": "t1"},
            {"source_article_id": "b", "target_article_id": "t1"},
        ])
        assert service.count_inbound_links(["t1"]) == {"t1": 2}

    def test_source_scoping_excludes_out_of_scope_sources(self, service):
        self._links_return(service, [
            {"source_article_id": "live1", "target_article_id": "t1"},
            {"source_article_id": "ghost", "target_article_id": "t1"},  # not in scope
            {"source_article_id": "live1", "target_article_id": "t2"},
        ])
        result = service.count_inbound_links(["t1", "t2"], source_ids=["live1"])
        assert result == {"t1": 1, "t2": 1}  # ghost source dropped

    def test_chunks_targets_at_100(self, service):
        chain = self._links_return(service, [])
        service.count_inbound_links([f"a{i}" for i in range(250)])
        assert chain.execute.call_count == 3  # 100 + 100 + 50

    def test_empty_makes_no_query(self, service):
        chain = self._links_return(service, [])
        assert service.count_inbound_links([]) == {}
        chain.execute.assert_not_called()


# =============================================================================
# INTERLINK HEALTH (§7 increment 1 — R4/R6/R8)
# =============================================================================

def _articles_db(rows_by_table):
    """Chainable mock supabase: table name -> execute().data rows. Captures
    upserts/inserts/updates per table in the returned dict."""
    db = MagicMock()
    writes = {"upserts": [], "inserts": [], "updates": []}

    def table_side_effect(name):
        chain = MagicMock()
        for m in ["select", "eq", "neq", "in_", "is_", "lt", "order", "limit"]:
            getattr(chain, m).return_value = chain
        chain.not_ = chain
        data = rows_by_table.get(name, [])
        result = MagicMock(data=data)
        result.count = len(data)
        chain.execute.return_value = result

        def _upsert(payload, **kwargs):
            writes["upserts"].append((name, payload, kwargs))
            u = MagicMock(); u.execute.return_value = MagicMock(data=payload)
            return u

        def _insert(payload):
            writes["inserts"].append((name, payload))
            u = MagicMock(); u.execute.return_value = MagicMock(data=[payload])
            return u

        def _update(payload):
            writes["updates"].append((name, payload))
            u = MagicMock()
            u.eq.return_value = u
            u.neq.return_value = u
            u.is_.return_value = u
            u.execute.return_value = MagicMock(data=[{"id": "x"}])
            return u

        chain.upsert.side_effect = _upsert
        chain.insert.side_effect = _insert
        chain.update.side_effect = _update
        return chain

    db.table.side_effect = table_side_effect
    return db, writes


class TestCaptureCoverageSnapshots:
    def test_captures_live_set_with_scoped_counts(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        db, writes = _articles_db({
            "seo_articles": [
                {"id": "a1", "keyword": "K1", "status": "published", "published_url": "https://x/1", "published_at": old},
                {"id": "a2", "keyword": "K2", "status": "published", "published_url": "https://x/2", "published_at": old, "interlink_exempt": True},
                {"id": "d1", "keyword": "Draft", "status": "published", "published_url": "", "published_at": None},
            ],
            # inbound query (count_inbound_links) + outbound query both hit
            # seo_internal_links; rows serve both (a1 links to a2).
            "seo_internal_links": [
                {"source_article_id": "a1", "target_article_id": "a2"},
            ],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.capture_coverage_snapshots("brand-1")

        by_id = {a["article_id"]: a for a in result["articles"]}
        assert set(by_id) == {"a1", "a2"}            # d1 (no url) excluded
        assert by_id["a1"]["is_orphan"] is True      # nothing links to a1
        assert by_id["a2"]["is_orphan"] is False     # a1 -> a2
        assert by_id["a2"]["interlink_exempt"] is True  # raw fact captured
        # Snapshot upsert is idempotent on (article_id, captured_on)
        assert writes["upserts"], "snapshot upsert never happened"
        _, payload, kwargs = writes["upserts"][0]
        assert kwargs.get("on_conflict") == "article_id,captured_on"
        assert {r["article_id"] for r in payload} == {"a1", "a2"}

    def test_snapshot_write_failure_is_nonfatal(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        db, writes = _articles_db({
            "seo_articles": [
                {"id": "a1", "keyword": "K1", "status": "published", "published_url": "https://x/1", "published_at": old},
            ],
            "seo_internal_links": [],
        })
        # Make upserts raise (migration not applied)
        orig = db.table.side_effect

        def raising(name):
            chain = orig(name)
            if name == "seo_link_coverage_snapshots":
                chain.upsert.side_effect = RuntimeError("relation does not exist")
            return chain

        db.table.side_effect = raising
        svc = InterlinkingService(supabase_client=db)
        result = svc.capture_coverage_snapshots("brand-1")  # must not raise
        assert result["articles"]                  # health data still usable
        assert result["captured"] == 0


class TestProcessOrphanAlerts:
    def _article(self, aid, days_old, orphan=True, exempt=False):
        from datetime import datetime, timedelta, timezone
        return {
            "article_id": aid,
            "keyword": f"kw-{aid}",
            "is_orphan": orphan,
            "interlink_exempt": exempt,
            "published_at": (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(),
        }

    def test_new_orphan_past_threshold_alarms(self):
        db, writes = _articles_db({"seo_orphan_alerts": []})
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("b1", [self._article("a1", days_old=10)])
        assert [a["article_id"] for a in result["new_alarms"]] == ["a1"]
        assert writes["inserts"] and writes["inserts"][0][0] == "seo_orphan_alerts"

    def test_young_orphan_does_not_alarm(self):
        db, writes = _articles_db({"seo_orphan_alerts": []})
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("b1", [self._article("a1", days_old=2)])
        assert result["new_alarms"] == []
        assert writes["inserts"] == []

    def test_open_alert_refreshes_without_realarm(self):
        db, writes = _articles_db({
            "seo_orphan_alerts": [{"id": "al1", "article_id": "a1", "status": "identified"}],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("b1", [self._article("a1", days_old=10)])
        assert result["new_alarms"] == []          # no re-alarm
        assert result["refreshed"] == 1
        assert writes["updates"]                   # last_seen_at touched

    def test_healthy_article_resolves_open_alert(self):
        db, writes = _articles_db({
            "seo_orphan_alerts": [{"id": "al1", "article_id": "a1", "status": "identified"}],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("b1", [self._article("a1", days_old=10, orphan=False)])
        assert result["resolved"] == 1
        resolved_payloads = [p for (t, p) in writes["updates"] if p.get("status") == "resolved"]
        assert resolved_payloads

    def test_exempt_article_never_alarms_and_resolves(self):
        db, writes = _articles_db({
            "seo_orphan_alerts": [{"id": "al1", "article_id": "a1", "status": "identified"}],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts(
            "b1", [self._article("a1", days_old=10, orphan=True, exempt=True)]
        )
        assert result["new_alarms"] == []
        assert result["resolved"] == 1

    def test_acknowledged_does_not_realarm(self):
        db, writes = _articles_db({
            "seo_orphan_alerts": [{"id": "al1", "article_id": "a1", "status": "acknowledged"}],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("b1", [self._article("a1", days_old=10)])
        assert result["new_alarms"] == []
        assert result["refreshed"] == 1


class TestPublishTimeSelfCheck:
    def test_alarm_when_cluster_pass_left_zero_inbound(self, service):
        service._get_article = MagicMock(return_value={
            "id": "a1", "keyword": "K", "published_url": "https://x/1",
        })
        service.count_inbound_links = MagicMock(return_value={})  # 0 inbound
        service.process_orphan_alerts = MagicMock(
            return_value={"new_alarms": [{"article_id": "a1"}]}
        )
        alarm = service.check_article_inbound_after_interlink("a1", "b1", cluster_published_count=4)
        assert alarm is not None
        assert alarm["article_id"] == "a1"
        assert "0 inbound" in alarm["reason"]

    def test_no_alarm_below_two_members(self, service):
        # First article in a cluster is EXPECTED to be linkless — not noise.
        assert service.check_article_inbound_after_interlink("a1", "b1", cluster_published_count=1) is None

    def test_no_alarm_when_inbound_exists(self, service):
        service._get_article = MagicMock(return_value={
            "id": "a1", "keyword": "K", "published_url": "https://x/1",
        })
        service.count_inbound_links = MagicMock(return_value={"a1": 2})
        assert service.check_article_inbound_after_interlink("a1", "b1", cluster_published_count=4) is None

    def test_no_alarm_for_exempt(self, service):
        service._get_article = MagicMock(return_value={
            "id": "a1", "keyword": "K", "published_url": "https://x/1", "interlink_exempt": True,
        })
        assert service.check_article_inbound_after_interlink("a1", "b1", cluster_published_count=4) is None

    def test_never_raises(self, service):
        service._get_article = MagicMock(side_effect=RuntimeError("db down"))
        assert service.check_article_inbound_after_interlink("a1", "b1", cluster_published_count=4) is None


class TestBuildInterlinkHealth:
    def test_health_block_counts_and_burn_down(self):
        db, _ = _articles_db({
            # burn-down lookup: previous capture day exists with 5 orphans
            "seo_link_coverage_snapshots": [{"captured_on": "2026-06-02"}] * 5,
        })
        svc = InterlinkingService(supabase_client=db)
        snap = {"articles": [
            {"article_id": "a1", "is_orphan": False, "interlink_exempt": False},
            {"article_id": "a2", "is_orphan": True, "interlink_exempt": False},
            {"article_id": "a3", "is_orphan": True, "interlink_exempt": True},  # exempt
        ]}
        alerts = {"new_alarms": [{"article_id": "a2"}], "open_total": 3, "resolved": 1}
        health = svc.build_interlink_health("b1", snap, alerts)

        assert health["published_count"] == 2     # exempt excluded
        assert health["orphan_count"] == 1        # a2 only (a3 exempt)
        assert health["exempt_count"] == 1
        assert health["coverage_pct"] == 50.0
        assert health["previous_orphan_count"] == 5
        assert health["new_alarm_count"] == 1
        assert health["open_alert_count"] == 3
        assert health["resolved_count"] == 1


class TestInterlinkExemptGuards:
    def test_auto_link_skips_exempt(self, service):
        service._get_article = MagicMock(return_value={"id": "a1", "interlink_exempt": True})
        result = service.auto_link_article("a1")
        assert result.get("skipped") == "interlink_exempt"

    def test_add_related_skips_exempt(self, service):
        service._get_article = MagicMock(return_value={"id": "a1", "interlink_exempt": True})
        result = service.add_related_section("a1", ["a2"])
        assert result.get("skipped") == "interlink_exempt"

    def test_set_interlink_exempt_resolves_open_alerts(self):
        db, writes = _articles_db({})
        svc = InterlinkingService(supabase_client=db)
        assert svc.set_interlink_exempt("a1", True) is True
        tables = [t for (t, p) in writes["updates"]]
        assert "seo_articles" in tables
        assert "seo_orphan_alerts" in tables


class TestCodexFixesInc1:
    """Regression tests for the codex review findings on increment 1."""

    def test_hubless_ring_leaves_no_orphans(self, service):
        """No published pillar (missing/unpublished/exempt): the cyclic-ring
        fallback must give EVERY member at least one inbound related link —
        the old first-N fallback orphaned members 6+ in large clusters."""
        members = [{"id": f"a{i}"} for i in range(9)]
        inbound = {m["id"]: 0 for m in members}
        for m in members:
            for target in service._build_related_ids(m["id"], None, members):
                inbound[target] += 1
            own = service._build_related_ids(m["id"], None, members)
            assert m["id"] not in own
            assert len(own) <= service.MAX_RELATED_LINKS
        assert all(ct >= 1 for ct in inbound.values()), f"orphans in ring: {inbound}"

    def test_r5_subset_does_not_resolve_other_alerts(self):
        """full_set=False (publish-time single-article check) must NOT resolve
        open alerts for articles absent from the subset."""
        db, writes = _articles_db({
            "seo_orphan_alerts": [
                {"id": "al-b", "article_id": "b1", "status": "identified"},
                {"id": "al-c", "article_id": "c1", "status": "identified"},
            ],
        })
        svc = InterlinkingService(supabase_client=db)
        from datetime import datetime, timedelta, timezone
        result = svc.process_orphan_alerts("brand-1", [{
            "article_id": "a1", "keyword": "A", "is_orphan": True,
            "interlink_exempt": False,
            "published_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        }], full_set=False)

        assert result["resolved"] == 0  # b1/c1 untouched
        resolved_payloads = [p for (t, p) in writes["updates"] if p.get("status") == "resolved"]
        assert resolved_payloads == []
        assert [a["article_id"] for a in result["new_alarms"]] == ["a1"]

    def test_full_set_resolves_departed_articles(self):
        """full_set=True: an open alert for an article gone from the live set
        IS resolved (unpublished/deleted articles stop alerting)."""
        db, writes = _articles_db({
            "seo_orphan_alerts": [{"id": "al-b", "article_id": "gone1", "status": "identified"}],
        })
        svc = InterlinkingService(supabase_client=db)
        result = svc.process_orphan_alerts("brand-1", [], full_set=True)
        assert result["resolved"] == 1

    def test_insert_race_downgrades_to_refresh(self):
        """Losing the partial-unique-index race (concurrent weekly scan + R5)
        must downgrade to a refresh — no duplicate alarm, pass continues."""
        db, writes = _articles_db({"seo_orphan_alerts": []})
        orig = db.table.side_effect

        def racing(name):
            chain = orig(name)
            if name == "seo_orphan_alerts":
                def _insert(payload):
                    raise RuntimeError("duplicate key value violates unique constraint")
                chain.insert.side_effect = _insert
            return chain

        db.table.side_effect = racing
        svc = InterlinkingService(supabase_client=db)
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        result = svc.process_orphan_alerts("brand-1", [
            {"article_id": "a1", "keyword": "A", "is_orphan": True, "interlink_exempt": False, "published_at": old},
            {"article_id": "a2", "keyword": "B", "is_orphan": True, "interlink_exempt": False, "published_at": old},
        ])
        assert result["new_alarms"] == []      # nobody double-alarms
        assert result["refreshed"] == 2        # both downgraded, pass completed

    def test_scope_article_skips_exempt_before_stripping(self, service):
        service._get_article = MagicMock(return_value={"id": "a1", "interlink_exempt": True})
        service.suggest_links = MagicMock()
        service._remove_related_section = MagicMock()
        result = service.interlink(scope="article", article_id="a1")
        assert result.get("skipped") == "interlink_exempt"
        service.suggest_links.assert_not_called()          # no saved suggestions
        service._remove_related_section.assert_not_called()  # Related block intact

    def test_remove_related_leaves_exempt_untouched(self, service):
        html = "<p>Body</p><h2>Related Articles</h2><ul><li>x</li></ul>"
        service._get_article = MagicMock(
            return_value={"id": "a1", "interlink_exempt": True, "content_html": html}
        )
        service._update_article_html = MagicMock()
        service._supabase = MagicMock()
        assert service._remove_related_section("a1") == html
        service._update_article_html.assert_not_called()

    def test_project_articles_exclude_exempt_targets(self, service):
        chain = MagicMock()
        for m in ["select", "eq", "neq", "is_", "not_", "order", "limit"]:
            getattr(chain, m, MagicMock()).return_value = chain
        chain.not_ = chain
        chain.execute.return_value = MagicMock(data=[
            {"id": "a1", "published_url": "https://x/1"},
            {"id": "a2", "published_url": "https://x/2", "interlink_exempt": True},
        ])
        service._supabase = MagicMock()
        service._supabase.table.return_value = chain
        result = service._get_project_articles("p1")
        assert [a["id"] for a in result] == ["a1"]


class TestVerifyLiveLinks:
    """R9: verified-vs-recorded — recorded implemented links checked against
    the live Shopify body, fetched by cms_article_id."""

    PUB_PATH = "viraltracker.services.seo_pipeline.services.cms_publisher_service.CMSPublisherService"

    def _db(self, articles, links):
        db = MagicMock()

        def table_side_effect(name):
            chain = MagicMock()
            for m in ["select", "eq", "neq", "in_", "order", "limit"]:
                getattr(chain, m).return_value = chain
            data = {"seo_articles": articles, "seo_internal_links": links}.get(name, [])
            chain.execute.return_value = MagicMock(data=data)
            return chain

        db.table.side_effect = table_side_effect
        return db

    def _arts(self):
        return [
            {"id": "s1", "keyword": "Source", "status": "published",
             "published_url": "https://shop.x/blogs/news/source", "cms_article_id": "901"},
            {"id": "t1", "keyword": "Target", "status": "published",
             "published_url": "https://shop.x/blogs/news/target-post", "cms_article_id": "902"},
        ]

    def _links(self):
        return [{"source_article_id": "s1", "target_article_id": "t1",
                 "created_at": "2026-06-09T00:00:00Z"}]

    def test_verified_when_path_in_live_body(self):
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {
            "body_html": '<p><a href="https://shop.x/blogs/news/target-post">t</a></p>'
        }
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["verified"] == 1
        assert result["missing"] == []
        assert result["articles_checked"] == 1

    def test_missing_link_flagged(self):
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {"body_html": "<p>no links here</p>"}
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["verified"] == 0
        assert len(result["missing"]) == 1
        assert result["missing"][0]["target_url"].endswith("target-post")

    def test_fetch_error_is_error_not_missing(self):
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.side_effect = RuntimeError("network down")
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["errors"] == 1
        assert result["missing"] == []      # error ≠ missing

    def test_locked_body_flag_not_fail(self):
        arts = self._arts()
        arts[0]["content_locked"] = True
        db = self._db(arts, self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {"body_html": "<p>human rewrote this</p>"}
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["locked_flags"] == 1
        assert result["missing"] == []      # locked = flagged, not failed

    def test_sample_cap_respected(self):
        arts = [
            {"id": f"s{i}", "keyword": f"S{i}", "status": "published",
             "published_url": f"https://shop.x/blogs/news/s{i}", "cms_article_id": str(900 + i)}
            for i in range(6)
        ]
        links = [
            {"source_article_id": f"s{i}", "target_article_id": f"s{(i + 1) % 6}",
             "created_at": f"2026-06-0{(i % 8) + 1}T00:00:00Z"}
            for i in range(6)
        ]
        db = self._db(arts, links)
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {"body_html": "<p>x</p>"}
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", sample_size=2, delay_seconds=0)
        assert result["articles_checked"] == 2  # cap held

    def test_no_publisher_skips(self):
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = None
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["skipped"] == "no CMS publisher configured"

    def test_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("db down")
        svc = InterlinkingService(supabase_client=db)
        result = svc.verify_live_links("b1", "o1", delay_seconds=0)  # must not raise
        assert result["errors"] == 1

    def test_prefix_path_does_not_false_verify(self):
        """/blogs/news/target-post must NOT verify against an href to
        /blogs/news/target-post-extended (exact path equality, not substring)."""
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {
            "body_html": '<a href="https://shop.x/blogs/news/target-post-extended">x</a>'
        }
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["verified"] == 0
        assert len(result["missing"]) == 1

    def test_plain_text_mention_does_not_verify(self):
        """The path appearing as TEXT (not an href) is not a link."""
        db = self._db(self._arts(), self._links())
        svc = InterlinkingService(supabase_client=db)
        publisher = MagicMock()
        publisher.get_article.return_value = {
            "body_html": "<p>see /blogs/news/target-post for more</p>"
        }
        with patch(self.PUB_PATH) as MockPub:
            MockPub.return_value.get_publisher.return_value = publisher
            result = svc.verify_live_links("b1", "o1", delay_seconds=0)
        assert result["verified"] == 0
        assert len(result["missing"]) == 1


class TestInterlinkManualEditGuard:
    """§10 inc 2: the interlink body-only push (Source B) must also detect a
    manual Shopify edit, auto-lock, and skip — not just the publish path."""

    def test_push_detects_manual_edit_and_locks(self, service):
        pub = MagicMock()
        pubsvc = MagicMock()
        pubsvc.get_publisher.return_value = pub
        pubsvc.detect_manual_edit.return_value = True
        service._publisher_service = pubsvc
        service._get_article = MagicMock(return_value={
            "id": "a1", "content_locked": False, "cms_article_id": "999",
        })
        ok = service._push_html_to_cms("a1", "b", "o", "<p>links</p>")
        assert ok is False
        pubsvc.set_content_locked.assert_called_once_with("a1", True)
        pub.update.assert_not_called()  # the overwrite was prevented

    def test_push_records_baseline_on_success(self, service):
        push_result = {
            "cms_updated_at": "2026-06-11T10:00:00-07:00",
            "cms_body_html": "<p>stored</p>",
        }
        pub = MagicMock()
        pub.update.return_value = push_result
        pubsvc = MagicMock()
        pubsvc.get_publisher.return_value = pub
        pubsvc.detect_manual_edit.return_value = False
        service._publisher_service = pubsvc
        service._get_article = MagicMock(return_value={
            "id": "a1", "content_locked": False, "cms_article_id": "999",
        })

        ok = service._push_html_to_cms("a1", "b", "o", "<p>links</p>")

        assert ok is True
        pub.update.assert_called_once()
        # baseline refreshed via the shared helper so our own write isn't read
        # as an edit next time.
        pubsvc.record_push_baseline.assert_called_once_with("a1", push_result)
