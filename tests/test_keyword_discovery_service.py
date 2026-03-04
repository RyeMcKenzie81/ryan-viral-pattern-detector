"""
Unit tests for KeywordDiscoveryService.

Covers:
- _generate_variations(): modifier/suffix cross-product, dedup
- _filter_keyword(): word count, character validation, edge cases
- discover_keywords(): end-to-end with mocked autocomplete + DB
- _save_keyword(): dedup, upsert logic
- get_keywords() / update_keyword_status()

Run with: pytest tests/test_keyword_discovery_service.py -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

import httpx

from viraltracker.services.seo_pipeline.services.keyword_discovery_service import (
    KeywordDiscoveryService,
    MODIFIERS,
    SUFFIXES,
    AUTOCOMPLETE_URL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Service with mocked Supabase client."""
    mock_supabase = MagicMock()
    svc = KeywordDiscoveryService(supabase_client=mock_supabase)
    return svc


@pytest.fixture
def service_no_db():
    """Service without Supabase for pure-function tests."""
    return KeywordDiscoveryService(supabase_client=None)


# ---------------------------------------------------------------------------
# _generate_variations()
# ---------------------------------------------------------------------------


class TestGenerateVariations:
    def test_returns_list(self, service_no_db):
        result = service_no_db._generate_variations("minecraft parenting")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_includes_bare_seed(self, service_no_db):
        result = service_no_db._generate_variations("test keyword")
        assert "test keyword" in result

    def test_includes_modifier_prefix(self, service_no_db):
        result = service_no_db._generate_variations("test keyword")
        assert "how to test keyword" in result
        assert "best test keyword" in result

    def test_includes_suffix(self, service_no_db):
        result = service_no_db._generate_variations("test keyword")
        assert "test keyword guide" in result
        assert "test keyword tips" in result

    def test_includes_modifier_and_suffix(self, service_no_db):
        result = service_no_db._generate_variations("test keyword")
        assert "how to test keyword guide" in result

    def test_no_duplicates(self, service_no_db):
        result = service_no_db._generate_variations("test keyword")
        assert len(result) == len(set(r.lower() for r in result))

    def test_expected_count(self, service_no_db):
        """16 modifiers x 10 suffixes = 160 max, minus any dedup collisions."""
        result = service_no_db._generate_variations("test keyword")
        # Should be close to 160 (modifiers * suffixes)
        assert len(result) == len(MODIFIERS) * len(SUFFIXES)

    def test_empty_seed(self, service_no_db):
        result = service_no_db._generate_variations("")
        # Modifiers alone become the queries
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _filter_keyword()
# ---------------------------------------------------------------------------


class TestFilterKeyword:
    def test_valid_keyword(self, service_no_db):
        assert service_no_db._filter_keyword("minecraft parenting tips", 3, 10) == "minecraft parenting tips"

    def test_lowercased(self, service_no_db):
        assert service_no_db._filter_keyword("Minecraft Parenting Tips", 3, 10) == "minecraft parenting tips"

    def test_stripped(self, service_no_db):
        assert service_no_db._filter_keyword("  minecraft parenting tips  ", 3, 10) == "minecraft parenting tips"

    def test_too_few_words(self, service_no_db):
        assert service_no_db._filter_keyword("minecraft", 3, 10) is None
        assert service_no_db._filter_keyword("two words", 3, 10) is None

    def test_too_many_words(self, service_no_db):
        long_kw = " ".join(["word"] * 11)
        assert service_no_db._filter_keyword(long_kw, 3, 10) is None

    def test_exact_boundary_min(self, service_no_db):
        assert service_no_db._filter_keyword("one two three", 3, 10) == "one two three"

    def test_exact_boundary_max(self, service_no_db):
        kw = " ".join(["word"] * 10)
        assert service_no_db._filter_keyword(kw, 3, 10) == kw

    def test_special_chars_rejected(self, service_no_db):
        assert service_no_db._filter_keyword("minecraft parenting @tips", 3, 10) is None
        assert service_no_db._filter_keyword("test (with parens)", 3, 10) is None
        assert service_no_db._filter_keyword("test & more words", 3, 10) is None

    def test_allowed_special_chars(self, service_no_db):
        """Hyphens and apostrophes are allowed."""
        assert service_no_db._filter_keyword("kids' minecraft tips", 3, 10) == "kids' minecraft tips"
        assert service_no_db._filter_keyword("step-by-step parenting guide", 3, 10) == "step-by-step parenting guide"

    def test_empty_string(self, service_no_db):
        assert service_no_db._filter_keyword("", 3, 10) is None

    def test_whitespace_only(self, service_no_db):
        assert service_no_db._filter_keyword("   ", 3, 10) is None

    def test_numbers_allowed(self, service_no_db):
        assert service_no_db._filter_keyword("top 10 minecraft tips", 3, 10) == "top 10 minecraft tips"


# ---------------------------------------------------------------------------
# _query_autocomplete() — mocked HTTP
# ---------------------------------------------------------------------------


class TestQueryAutocomplete:
    @pytest.mark.asyncio
    async def test_successful_response(self, service_no_db):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            "minecraft parenting",
            ["minecraft parenting tips", "minecraft parenting guide", "minecraft parenting app"],
        ]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await service_no_db._query_autocomplete(mock_client, "minecraft parenting")
        assert result == ["minecraft parenting tips", "minecraft parenting guide", "minecraft parenting app"]

        mock_client.get.assert_called_once_with(
            AUTOCOMPLETE_URL,
            params={"client": "firefox", "q": "minecraft parenting"},
        )

    @pytest.mark.asyncio
    async def test_empty_response(self, service_no_db):
        mock_response = MagicMock()
        mock_response.json.return_value = ["query", []]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await service_no_db._query_autocomplete(mock_client, "zzz no results")
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_response(self, service_no_db):
        mock_response = MagicMock()
        mock_response.json.return_value = "not a list"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await service_no_db._query_autocomplete(mock_client, "test")
        assert result == []

    @pytest.mark.asyncio
    async def test_http_error(self, service_no_db):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection failed")

        result = await service_no_db._query_autocomplete(mock_client, "test")
        assert result == []

    @pytest.mark.asyncio
    async def test_http_status_error(self, service_no_db):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        result = await service_no_db._query_autocomplete(mock_client, "test")
        assert result == []


# ---------------------------------------------------------------------------
# _save_keyword() — mocked DB
# ---------------------------------------------------------------------------


class TestSaveKeyword:
    def test_saves_new_keyword(self, service):
        # Mock: no existing keyword
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value = mock_select

        # Mock: insert succeeds
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        service.supabase.table.return_value.insert.return_value = mock_insert

        result = service._save_keyword(
            str(uuid4()),
            {"keyword": "test keyword here", "word_count": 3, "seed_keyword": "test", "found_in_seeds": 1},
        )
        assert result is True

    def test_skips_duplicate(self, service):
        existing_id = str(uuid4())
        # Mock: keyword already exists
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[{"id": existing_id}])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value = mock_select

        # Mock: update for found_in_seeds
        mock_update = MagicMock()
        mock_update.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_update

        result = service._save_keyword(
            str(uuid4()),
            {"keyword": "existing keyword here", "word_count": 3, "seed_keyword": "test", "found_in_seeds": 2},
        )
        assert result is False

    def test_handles_db_error(self, service):
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = Exception("DB error")

        result = service._save_keyword(
            str(uuid4()),
            {"keyword": "error keyword here", "word_count": 3, "seed_keyword": "test", "found_in_seeds": 1},
        )
        assert result is False


# ---------------------------------------------------------------------------
# discover_keywords() — full flow with mocked HTTP + DB
# ---------------------------------------------------------------------------


class TestDiscoverKeywords:
    @pytest.mark.asyncio
    async def test_full_discovery_flow(self, service):
        """Test end-to-end discovery with mocked autocomplete and DB."""
        project_id = str(uuid4())

        # Mock: autocomplete returns some suggestions
        async def mock_get(url, params=None):
            query = params.get("q", "") if params else ""
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if "minecraft" in query:
                mock_resp.json.return_value = [
                    query,
                    [
                        "minecraft parenting tips for kids",
                        "minecraft parenting guide 2024",
                        "minecraft",  # too short, should be filtered
                    ],
                ]
            else:
                mock_resp.json.return_value = [query, []]
            return mock_resp

        # Mock: no existing keywords, inserts succeed
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value = mock_select

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        service.supabase.table.return_value.insert.return_value = mock_insert

        with patch("viraltracker.services.seo_pipeline.services.keyword_discovery_service.asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await service.discover_keywords(
                    project_id, ["minecraft parenting"], min_word_count=3, max_word_count=10
                )

        assert result["total_keywords"] >= 1
        assert isinstance(result["keywords"], list)
        # "minecraft" alone (1 word) should have been filtered out
        for kw in result["keywords"]:
            assert kw["word_count"] >= 3

    @pytest.mark.asyncio
    async def test_empty_seeds(self, service):
        """Empty/whitespace seeds should produce no results."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await service.discover_keywords(
                str(uuid4()), ["", "  "], min_word_count=3, max_word_count=10
            )

        assert result["total_keywords"] == 0
        assert result["keywords"] == []


# ---------------------------------------------------------------------------
# get_keywords() / update_keyword_status()
# ---------------------------------------------------------------------------


class TestGetKeywords:
    def test_returns_data(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[
            {"id": str(uuid4()), "keyword": "test", "status": "discovered"},
        ])
        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value = mock_query

        result = service.get_keywords(str(uuid4()))
        assert len(result) == 1

    def test_with_status_filter(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value = mock_query

        result = service.get_keywords(str(uuid4()), status="selected")
        assert result == []


class TestUpdateKeywordStatus:
    def test_updates_status(self, service):
        kw_id = str(uuid4())
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[{"id": kw_id, "status": "selected"}])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_query

        result = service.update_keyword_status(kw_id, "selected")
        assert result["status"] == "selected"

    def test_not_found_returns_none(self, service):
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[])
        service.supabase.table.return_value.update.return_value.eq.return_value = mock_query

        result = service.update_keyword_status(str(uuid4()), "selected")
        assert result is None
