"""
Unit tests for ContentGenerationService.

Covers:
- Prompt template loading and variable injection
- Phase A/B/C prompt building (no unresolved template variables)
- Author context loading (with/without persona)
- Brand context extraction helpers
- API mode execution (mocked Anthropic)
- CLI mode execution (prompt file writing)
- ingest_cli_result() DB updates
- create_article() / list_articles() / get_article()

Run with: pytest tests/test_content_generation_service.py -v
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from viraltracker.services.seo_pipeline.services.content_generation_service import (
    ContentGenerationService,
    PROMPTS_DIR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Service with mocked dependencies."""
    mock_supabase = MagicMock()
    mock_usage = MagicMock()
    mock_anthropic = MagicMock()
    return ContentGenerationService(
        supabase_client=mock_supabase,
        usage_tracker=mock_usage,
        anthropic_client=mock_anthropic,
    )


@pytest.fixture
def brand_context():
    """Sample brand context from BrandProfileService."""
    return {
        "brand_basics": {
            "name": "TestBrand",
            "description": "We help families connect through shared activities.",
            "voice_tone": "Warm, conversational",
        },
        "product": {
            "name": "TestProduct",
            "target_audience": "Parents with kids aged 6-14",
            "key_benefits": ["Better communication", "Family bonding", "Fun activities"],
        },
    }


@pytest.fixture
def competitor_data():
    """Sample competitor analysis results."""
    return {
        "results": [
            {
                "url": "https://example.com/article-1",
                "word_count": 2000,
                "h2_count": 5,
                "flesch_reading_ease": 65.0,
                "has_schema": True,
                "has_faq": True,
            },
            {
                "url": "https://example.com/article-2",
                "word_count": 1500,
                "h2_count": 3,
                "flesch_reading_ease": 70.0,
                "has_schema": False,
                "has_faq": False,
            },
        ],
        "winning_formula": {
            "target_word_count": 1960,
            "avg_h2_count": 4,
            "avg_flesch_score": 67.5,
            "pct_with_schema": 50.0,
            "pct_with_faq": 50.0,
        },
    }


# ---------------------------------------------------------------------------
# Template Loading
# ---------------------------------------------------------------------------


class TestTemplateLoading:
    def test_prompts_dir_exists(self):
        assert PROMPTS_DIR.exists(), f"Prompts dir missing: {PROMPTS_DIR}"

    def test_phase_a_template_exists(self):
        assert (PROMPTS_DIR / "phase_a_research.txt").exists()

    def test_phase_b_template_exists(self):
        assert (PROMPTS_DIR / "phase_b_write.txt").exists()

    def test_phase_c_template_exists(self):
        assert (PROMPTS_DIR / "phase_c_optimize.txt").exists()

    def test_load_template(self, service):
        template = service._load_template("phase_a_research.txt")
        assert len(template) > 100
        assert "{KEYWORD}" in template

    def test_load_nonexistent_template(self, service):
        with pytest.raises(FileNotFoundError):
            service._load_template("nonexistent.txt")


# ---------------------------------------------------------------------------
# Prompt Building
# ---------------------------------------------------------------------------


class TestBuildPhaseAPrompt:
    def test_no_unresolved_variables(self, service, brand_context, competitor_data):
        author_ctx = {"name": "Test Author", "voice": "Conversational tone."}
        prompt = service._build_phase_a_prompt("test keyword", competitor_data, brand_context, author_ctx)

        assert "{KEYWORD}" not in prompt
        assert "{AUTHOR_NAME}" not in prompt
        assert "{BRAND_NAME}" not in prompt
        assert "{SEARCH_INTENT}" not in prompt
        assert "{BRAND_POSITIONING}" not in prompt
        assert "{AUTHOR_VOICE}" not in prompt
        assert "{COMPETITOR_DATA}" not in prompt

    def test_contains_keyword(self, service, brand_context):
        author_ctx = {"name": "Author", "voice": "tone"}
        prompt = service._build_phase_a_prompt("minecraft parenting", None, brand_context, author_ctx)
        assert "minecraft parenting" in prompt

    def test_contains_brand_name(self, service, brand_context):
        author_ctx = {"name": "Author", "voice": "tone"}
        prompt = service._build_phase_a_prompt("test kw", None, brand_context, author_ctx)
        assert "TestBrand" in prompt

    def test_contains_competitor_data(self, service, brand_context, competitor_data):
        author_ctx = {"name": "Author", "voice": "tone"}
        prompt = service._build_phase_a_prompt("test kw", competitor_data, brand_context, author_ctx)
        assert "example.com/article-1" in prompt

    def test_no_competitor_data(self, service, brand_context):
        author_ctx = {"name": "Author", "voice": "tone"}
        prompt = service._build_phase_a_prompt("test kw", None, brand_context, author_ctx)
        assert "No competitor data" in prompt


class TestBuildPhaseBPrompt:
    def test_no_unresolved_variables(self, service, brand_context):
        author_ctx = {"name": "Test Author", "voice": "Casual and funny."}
        prompt = service._build_phase_b_prompt("test keyword", "Phase A outline text", brand_context, author_ctx)

        assert "{KEYWORD}" not in prompt
        assert "{AUTHOR_NAME}" not in prompt
        assert "{BRAND_NAME}" not in prompt
        assert "{PHASE_A_OUTPUT}" not in prompt
        assert "{PRODUCT_MENTIONS}" not in prompt

    def test_contains_phase_a_output(self, service, brand_context):
        author_ctx = {"name": "Author", "voice": "tone"}
        prompt = service._build_phase_b_prompt("kw", "MY_UNIQUE_OUTLINE_CONTENT", brand_context, author_ctx)
        assert "MY_UNIQUE_OUTLINE_CONTENT" in prompt


class TestBuildPhaseCPrompt:
    def test_no_unresolved_variables(self, service, brand_context, competitor_data):
        author_ctx = {
            "name": "Test Author",
            "bio": "A test author bio.",
            "image_url": "https://example.com/photo.jpg",
            "job_title": "Writer",
            "author_url": "https://example.com/about",
        }
        prompt = service._build_phase_c_prompt(
            "test keyword", "Phase B article text", competitor_data,
            [{"title": "Related Article", "published_url": "https://example.com/related"}],
            brand_context, author_ctx
        )

        assert "{KEYWORD}" not in prompt
        assert "{PHASE_B_OUTPUT}" not in prompt
        assert "{AUTHOR_NAME}" not in prompt
        assert "{AUTHOR_BIO}" not in prompt
        assert "{BRAND_NAME}" not in prompt
        assert "{INTERNAL_LINKS_CONTEXT}" not in prompt

    def test_contains_article_text(self, service, brand_context):
        author_ctx = {"name": "Author", "bio": "Bio", "image_url": "", "job_title": "", "author_url": ""}
        prompt = service._build_phase_c_prompt("kw", "MY_ARTICLE_CONTENT", None, None, brand_context, author_ctx)
        assert "MY_ARTICLE_CONTENT" in prompt

    def test_contains_competitor_stats(self, service, brand_context, competitor_data):
        author_ctx = {"name": "Author", "bio": "Bio", "image_url": "", "job_title": "", "author_url": ""}
        prompt = service._build_phase_c_prompt("kw", "text", competitor_data, None, brand_context, author_ctx)
        assert "1960" in prompt  # target_word_count

    def test_contains_internal_links(self, service, brand_context):
        author_ctx = {"name": "Author", "bio": "Bio", "image_url": "", "job_title": "", "author_url": ""}
        articles = [{"title": "Great Article", "published_url": "https://blog.example.com/great"}]
        prompt = service._build_phase_c_prompt("kw", "text", None, articles, brand_context, author_ctx)
        assert "Great Article" in prompt
        assert "blog.example.com/great" in prompt


# ---------------------------------------------------------------------------
# Brand Context Helpers
# ---------------------------------------------------------------------------


class TestBrandContextHelpers:
    def test_get_brand_name(self, service, brand_context):
        assert service._get_brand_name(brand_context) == "TestBrand"

    def test_get_brand_name_none(self, service):
        assert service._get_brand_name(None) == "Our Brand"

    def test_get_brand_positioning(self, service, brand_context):
        pos = service._get_brand_positioning(brand_context)
        assert "families connect" in pos
        assert "Parents with kids" in pos

    def test_get_brand_positioning_none(self, service):
        pos = service._get_brand_positioning(None)
        assert "practical" in pos.lower()

    def test_get_product_mentions(self, service, brand_context):
        mentions = service._get_product_mentions(brand_context)
        assert "TestProduct" in mentions

    def test_get_product_mentions_none(self, service):
        mentions = service._get_product_mentions(None)
        assert "naturally" in mentions.lower()


# ---------------------------------------------------------------------------
# Author Context Loading
# ---------------------------------------------------------------------------


class TestLoadAuthorContext:
    def test_no_author_id(self, service):
        ctx = service._load_author_context(None)
        assert ctx["name"] == "Author"
        assert "voice" in ctx

    def test_author_found(self, service):
        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(data=[{
            "id": str(uuid4()),
            "name": "Kevin Hinton",
            "bio": "Dad and co-founder",
            "image_url": "https://example.com/kevin.jpg",
            "job_title": "Co-Founder",
            "author_url": "https://example.com/about",
            "persona_id": None,
        }])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_exec

        ctx = service._load_author_context(str(uuid4()))
        assert ctx["name"] == "Kevin Hinton"
        assert ctx["bio"] == "Dad and co-founder"

    def test_author_not_found(self, service):
        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_exec

        ctx = service._load_author_context(str(uuid4()))
        assert ctx["name"] == "Author"

    def test_author_with_persona(self, service):
        persona_id = str(uuid4())

        # First call: seo_authors returns author with persona
        author_exec = MagicMock()
        author_exec.execute.return_value = MagicMock(data=[{
            "id": str(uuid4()),
            "name": "Kevin",
            "bio": "Bio",
            "image_url": "",
            "job_title": "",
            "author_url": "",
            "persona_id": persona_id,
        }])

        # Second call: personas_4d returns persona voice
        persona_exec = MagicMock()
        persona_exec.execute.return_value = MagicMock(data=[{
            "voice_and_tone": "Warm and conversational, uses humor.",
            "brand_voice_summary": "Speaks like a friend, not a teacher.",
        }])

        # Set up chain: table() -> select() -> eq() -> execute()
        calls = [author_exec, persona_exec]
        call_idx = [0]

        def side_effect(*args, **kwargs):
            result = calls[call_idx[0]]
            call_idx[0] = min(call_idx[0] + 1, len(calls) - 1)
            return result

        service.supabase.table.return_value.select.return_value.eq.side_effect = side_effect

        ctx = service._load_author_context(str(uuid4()))
        assert ctx["name"] == "Kevin"
        assert "conversational" in ctx["voice"].lower()


# ---------------------------------------------------------------------------
# API Mode
# ---------------------------------------------------------------------------


class TestAPIMode:
    def test_phase_a_api_mode(self, service, brand_context):
        article_id = str(uuid4())

        # Mock Anthropic response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="# Phase A Output\n\n## Outline...")]
        mock_response.usage.input_tokens = 5000
        mock_response.usage.output_tokens = 2000
        service.anthropic_client.messages.create.return_value = mock_response

        # Mock DB update
        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        # Mock author lookup (no author)
        mock_author = MagicMock()
        mock_author.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_author

        result = service.generate_phase_a(
            article_id=article_id,
            keyword="test keyword",
            brand_context=brand_context,
            mode="api",
            organization_id="org-123",
        )

        assert result["mode"] == "api"
        assert result["phase"] == "a"
        assert result["input_tokens"] == 5000
        assert result["output_tokens"] == 2000
        assert "Phase A Output" in result["content"]
        assert result["duration_ms"] >= 0

    def test_api_mode_calls_anthropic(self, service):
        article_id = str(uuid4())

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="output")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        service.anthropic_client.messages.create.return_value = mock_response

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        service.generate_phase_a(
            article_id=article_id,
            keyword="test",
            mode="api",
        )

        service.anthropic_client.messages.create.assert_called_once()
        call_args = service.anthropic_client.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-opus-4-7"
        assert call_args.kwargs["max_tokens"] == 8192

    def test_api_mode_tracks_usage(self, service):
        article_id = str(uuid4())

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="output")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        service.anthropic_client.messages.create.return_value = mock_response

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        service.generate_phase_a(
            article_id=article_id,
            keyword="test",
            mode="api",
            organization_id="org-123",
        )

        service.usage_tracker.track.assert_called_once()

    def test_api_mode_saves_to_db(self, service):
        article_id = str(uuid4())

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="output content")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        service.anthropic_client.messages.create.return_value = mock_response

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        service.generate_phase_a(
            article_id=article_id,
            keyword="test",
            mode="api",
        )

        service.supabase.table.assert_called_with("seo_articles")


# ---------------------------------------------------------------------------
# CLI Mode
# ---------------------------------------------------------------------------


class TestCLIMode:
    def test_cli_mode_writes_file(self, service, tmp_path):
        article_id = str(uuid4())

        with patch.object(Path, "write_text") as mock_write:
            result = service.generate_phase_a(
                article_id=article_id,
                keyword="test keyword",
                mode="cli",
            )

        assert result["mode"] == "cli"
        assert result["phase"] == "a"
        assert "prompt_file" in result
        assert "instructions" in result
        assert article_id[:8] in result["prompt_file"]

    def test_cli_mode_does_not_call_anthropic(self, service):
        with patch.object(Path, "write_text"):
            service.generate_phase_a(
                article_id=str(uuid4()),
                keyword="test",
                mode="cli",
            )

        service.anthropic_client.messages.create.assert_not_called()

    def test_cli_mode_instructions_contain_ingest_command(self, service):
        article_id = str(uuid4())

        with patch.object(Path, "write_text"):
            result = service.generate_phase_a(
                article_id=article_id,
                keyword="test",
                mode="cli",
            )

        assert "ingest-result" in result["instructions"]
        assert article_id in result["instructions"]


# ---------------------------------------------------------------------------
# Ingest CLI Result
# ---------------------------------------------------------------------------


class TestIngestCliResult:
    def test_ingest_phase_a(self, service):
        article_id = str(uuid4())

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        result = service.ingest_cli_result(article_id, "a", "# Outline content")
        assert result["phase"] == "a"
        assert result["status"] == "ingested"

        service.supabase.table.assert_called_with("seo_articles")

    def test_ingest_phase_b(self, service):
        article_id = str(uuid4())

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        result = service.ingest_cli_result(article_id, "b", "# Article content")
        assert result["phase"] == "b"

    def test_ingest_phase_c(self, service):
        article_id = str(uuid4())

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        result = service.ingest_cli_result(article_id, "c", "# Optimized content")
        assert result["phase"] == "c"

    def test_ingest_invalid_phase(self, service):
        with pytest.raises(ValueError, match="Invalid phase"):
            service.ingest_cli_result(str(uuid4()), "x", "content")

    def test_ingest_uppercase_phase(self, service):
        """Phase letter should be normalized to lowercase."""
        article_id = str(uuid4())

        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        result = service.ingest_cli_result(article_id, "A", "content")
        assert result["phase"] == "a"


# ---------------------------------------------------------------------------
# Article CRUD
# ---------------------------------------------------------------------------


class TestArticleCRUD:
    def test_create_article(self, service):
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{
            "id": str(uuid4()),
            "keyword": "test keyword",
            "status": "draft",
        }])
        service.supabase.table.return_value.insert.return_value = mock_insert

        result = service.create_article(
            project_id=str(uuid4()),
            brand_id=str(uuid4()),
            organization_id=str(uuid4()),
            keyword="test keyword",
        )
        assert result["keyword"] == "test keyword"
        assert result["status"] == "draft"

    def test_create_article_with_author(self, service):
        author_id = str(uuid4())
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        service.supabase.table.return_value.insert.return_value = mock_insert

        service.create_article(
            project_id=str(uuid4()),
            brand_id=str(uuid4()),
            organization_id=str(uuid4()),
            keyword="test",
            author_id=author_id,
        )

        insert_call = service.supabase.table.return_value.insert.call_args
        assert insert_call[0][0]["author_id"] == author_id

    def test_get_article_found(self, service):
        article_id = str(uuid4())
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[{
            "id": article_id, "keyword": "test"
        }])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_query

        result = service.get_article(article_id)
        assert result["keyword"] == "test"

    def test_get_article_not_found(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value = mock_query

        result = service.get_article(str(uuid4()))
        assert result is None

    def test_list_articles(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[
            {"id": "a1", "keyword": "kw1"},
            {"id": "a2", "keyword": "kw2"},
        ])
        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value = mock_query

        result = service.list_articles(str(uuid4()))
        assert len(result) == 2

    def test_list_articles_with_status(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value = mock_query

        result = service.list_articles(str(uuid4()), status="draft")
        assert result == []

    def test_list_articles_invalid_status(self, service):
        with pytest.raises(ValueError, match="Invalid article status"):
            service.list_articles(str(uuid4()), status="bogus_status")

    def test_list_articles_all_valid_statuses(self, service):
        """Every ArticleStatus value should be accepted."""
        from viraltracker.services.seo_pipeline.models import ArticleStatus

        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value = mock_query

        for status in ArticleStatus:
            result = service.list_articles(str(uuid4()), status=status.value)
            assert result == []
