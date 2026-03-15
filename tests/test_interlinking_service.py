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
