"""
Tests for the Chainlit agent chat app.

Tests cover:
- streaming.py: format_tool_args, truncate_output
- app.py: build_conversation_context
- auth.py: authenticate (with mocked Supabase)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from viraltracker.chainlit_app.streaming import format_tool_args, truncate_output
from viraltracker.chainlit_app.app import build_conversation_context


# ==========================================================================
# format_tool_args tests
# ==========================================================================


class TestFormatToolArgs:
    def test_none_returns_empty(self):
        assert format_tool_args(None) == ""

    def test_dict_pretty_prints(self):
        result = format_tool_args({"query": "test", "limit": 10})
        parsed = json.loads(result)
        assert parsed == {"query": "test", "limit": 10}

    def test_json_string_pretty_prints(self):
        raw = '{"query":"test","limit":10}'
        result = format_tool_args(raw)
        parsed = json.loads(result)
        assert parsed == {"query": "test", "limit": 10}

    def test_plain_string_returned_as_is(self):
        assert format_tool_args("not json") == "not json"

    def test_dict_with_non_serializable_uses_str(self):
        from datetime import datetime

        result = format_tool_args({"ts": datetime(2026, 1, 1)})
        assert "2026" in result

    def test_integer_returns_str(self):
        assert format_tool_args(42) == "42"


# ==========================================================================
# truncate_output tests
# ==========================================================================


class TestTruncateOutput:
    def test_empty_string(self):
        assert truncate_output("") == ""

    def test_none_returns_empty(self):
        assert truncate_output(None) == ""

    def test_short_text_unchanged(self):
        assert truncate_output("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "x" * 2000
        assert truncate_output(text) == text

    def test_over_limit_truncated(self):
        text = "x" * 3000
        result = truncate_output(text, max_len=100)
        assert len(result) < 3000
        assert "truncated" in result
        assert "3000" in result

    def test_custom_max_len(self):
        text = "x" * 500
        result = truncate_output(text, max_len=200)
        assert "truncated" in result

    def test_non_string_converted(self):
        result = truncate_output(12345)
        assert result == "12345"


# ==========================================================================
# build_conversation_context tests
# ==========================================================================


class TestBuildConversationContext:
    def test_empty_list_returns_empty(self):
        assert build_conversation_context([]) == ""

    def test_single_result(self):
        results = [
            {"user_query": "find viral tweets", "agent_response": "Found 10 tweets..."}
        ]
        context = build_conversation_context(results)
        assert "find viral tweets" in context
        assert "Found 10 tweets" in context
        assert "Recent Context" in context

    def test_truncates_long_responses(self):
        results = [
            {"user_query": "test", "agent_response": "x" * 1000}
        ]
        context = build_conversation_context(results)
        assert "..." in context

    def test_only_last_3_results(self):
        results = [
            {"user_query": f"query {i}", "agent_response": f"response {i}"}
            for i in range(5)
        ]
        context = build_conversation_context(results)
        assert "query 2" in context
        assert "query 3" in context
        assert "query 4" in context
        # First two should not appear (only last 3)
        assert "query 0" not in context
        assert "query 1" not in context

    def test_includes_important_instructions(self):
        results = [
            {"user_query": "test", "agent_response": "result"}
        ]
        context = build_conversation_context(results)
        assert "IMPORTANT" in context
        assert "those tweets" in context


# ==========================================================================
# authenticate tests (mocked Supabase)
# ==========================================================================


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_successful_auth(self):
        """Test successful authentication returns cl.User with metadata."""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_response.session = mock_session

        mock_anon_client = MagicMock()
        mock_anon_client.auth.sign_in_with_password.return_value = mock_response

        mock_service_client = MagicMock()
        mock_org_result = MagicMock()
        mock_org_result.data = [{"organization_id": "org-456"}]
        mock_service_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_org_result

        # Patch at the source module since auth.py uses lazy imports
        with patch("viraltracker.core.database.get_anon_client", return_value=mock_anon_client), \
             patch("viraltracker.core.database.get_supabase_client", return_value=mock_service_client):
            from viraltracker.chainlit_app.auth import authenticate
            result = await authenticate("test@example.com", "password123")

        assert result is not None
        assert result.identifier == "test@example.com"
        assert result.metadata["user_id"] == "user-123"
        assert result.metadata["org_id"] == "org-456"

    @pytest.mark.asyncio
    async def test_failed_auth_returns_none(self):
        """Test failed authentication returns None."""
        mock_anon_client = MagicMock()
        mock_anon_client.auth.sign_in_with_password.side_effect = Exception(
            "Invalid login credentials"
        )

        with patch("viraltracker.core.database.get_anon_client", return_value=mock_anon_client):
            from viraltracker.chainlit_app.auth import authenticate
            result = await authenticate("bad@example.com", "wrong")

        assert result is None

    @pytest.mark.asyncio
    async def test_auth_no_org(self):
        """Test auth succeeds even if user has no organization."""
        mock_user = MagicMock()
        mock_user.id = "user-789"
        mock_user.email = "noorg@example.com"

        mock_response = MagicMock()
        mock_response.user = mock_user

        mock_anon_client = MagicMock()
        mock_anon_client.auth.sign_in_with_password.return_value = mock_response

        mock_service_client = MagicMock()
        mock_org_result = MagicMock()
        mock_org_result.data = []
        mock_service_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_org_result

        with patch("viraltracker.core.database.get_anon_client", return_value=mock_anon_client), \
             patch("viraltracker.core.database.get_supabase_client", return_value=mock_service_client):
            from viraltracker.chainlit_app.auth import authenticate
            result = await authenticate("noorg@example.com", "password")

        assert result is not None
        assert result.metadata["org_id"] is None
