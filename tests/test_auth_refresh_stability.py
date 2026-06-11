"""Regression: ViralTracker login should not 'expire fairly quickly'.

Root cause was the auth client running supabase-py's default background
auto-refresher on a shared singleton: it rotated the refresh token out of band
(invalidating the cookie's copy -> reuse-detection logout) and let one browser
session clobber another's session state. The fix:
  1. Auth clients disable auto_refresh_token + persist_session (no background
     rotation; refresh is driven explicitly from the cookie).
  2. create_auth_client() returns a FRESH client per auth op (no shared mutable
     session across browser sessions).
  3. _refresh_session() clears the cookie only on a definitively-dead refresh
     token (so we present a clean login instead of bouncing on a doomed retry),
     and keeps it on transient errors so a later rerun can retry.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def auth():
    import viraltracker.ui.auth as auth_mod
    return auth_mod


class TestAuthClientOptions:
    def test_create_auth_client_is_fresh_each_call(self):
        import viraltracker.core.database as db
        with patch.object(db, "create_client", side_effect=lambda *a, **k: MagicMock()) as mock_create, \
             patch.object(db.Config, "SUPABASE_ANON_KEY", "anon-key"), \
             patch.object(db.Config, "SUPABASE_URL", "https://x.supabase.co"):
            c1 = db.create_auth_client()
            c2 = db.create_auth_client()
            assert c1 is not c2, "auth client must be a fresh instance per call"

    def test_create_auth_client_disables_background_refresher(self):
        import viraltracker.core.database as db
        with patch.object(db, "create_client", side_effect=lambda *a, **k: MagicMock()) as mock_create, \
             patch.object(db.Config, "SUPABASE_ANON_KEY", "anon-key"), \
             patch.object(db.Config, "SUPABASE_URL", "https://x.supabase.co"):
            db.create_auth_client()
            opts = mock_create.call_args.kwargs["options"]
            assert opts.auto_refresh_token is False
            assert opts.persist_session is False

    def test_anon_singleton_also_disables_background_refresher(self):
        import viraltracker.core.database as db
        db.reset_supabase_client()
        with patch.object(db, "create_client", side_effect=lambda *a, **k: MagicMock()) as mock_create, \
             patch.object(db.Config, "SUPABASE_ANON_KEY", "anon-key"), \
             patch.object(db.Config, "SUPABASE_URL", "https://x.supabase.co"):
            db.get_anon_client()
            opts = mock_create.call_args.kwargs["options"]
            assert opts.auto_refresh_token is False
            assert opts.persist_session is False
        db.reset_supabase_client()

    def test_no_anon_key_fallback_still_disables_refresher(self):
        # The service-key fallback must NOT return the default-options singleton
        # (that would reintroduce the background refresher / shared session).
        import viraltracker.core.database as db
        with patch.object(db, "create_client", side_effect=lambda *a, **k: MagicMock()) as mock_create, \
             patch.object(db.Config, "SUPABASE_ANON_KEY", ""), \
             patch.object(db.Config, "SUPABASE_SERVICE_KEY", "service-key"), \
             patch.object(db.Config, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db.Config, "validate"):
            db.create_auth_client()
            opts = mock_create.call_args.kwargs["options"]
            assert opts.auto_refresh_token is False
            assert opts.persist_session is False


class TestFatalRefreshClassification:
    @pytest.mark.parametrize("message", [
        "Invalid Refresh Token: Already Used",
        "Invalid Refresh Token: Refresh Token Not Found",
        "refresh_token_not_found",
        "AuthApiError: refresh_token_already_used",
        "Refresh token has been revoked",
        "Session not found",
        "Session expired",
    ])
    def test_fatal_messages(self, auth, message):
        assert auth._is_fatal_refresh_error(Exception(message)) is True

    @pytest.mark.parametrize("message", [
        "Connection timed out",
        "Server error (500)",
        "temporarily unavailable",
        "Read timed out",
        "Name or service not known",
    ])
    def test_transient_messages(self, auth, message):
        assert auth._is_fatal_refresh_error(Exception(message)) is False

    def test_fatal_via_structured_code(self, auth):
        # AuthApiError carries a structured .code; honor it even if the message
        # text is opaque (Codex example: "Session not found" / session_not_found).
        err = type("FakeAuthApiError", (Exception,), {})("opaque text")
        err.code = "session_not_found"
        assert auth._is_fatal_refresh_error(err) is True

    def test_transient_via_structured_code(self, auth):
        err = type("FakeAuthApiError", (Exception,), {})("rate limited")
        err.code = "over_request_rate_limit"
        assert auth._is_fatal_refresh_error(err) is False


class TestRefreshSessionCookieHandling:
    def test_clears_cookie_on_fatal(self, auth):
        client = MagicMock()
        client.auth.refresh_session.side_effect = Exception(
            "Invalid Refresh Token: Already Used"
        )
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_clear_session_cookie") as mock_clear:
            mst.session_state = {}
            assert auth._refresh_session("dead-token") is False
            mock_clear.assert_called_once()

    def test_keeps_cookie_on_transient(self, auth):
        client = MagicMock()
        client.auth.refresh_session.side_effect = Exception("Connection reset by peer")
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_clear_session_cookie") as mock_clear:
            mst.session_state = {}
            assert auth._refresh_session("maybe-ok-token") is False
            mock_clear.assert_not_called()

    def test_success_saves_rotated_tokens_to_cookie(self, auth):
        session = MagicMock(
            access_token="new-a", refresh_token="new-r", expires_at=9999999999
        )
        response = MagicMock(session=session, user=MagicMock(email="u@x.com"))
        client = MagicMock()
        client.auth.refresh_session.return_value = response
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_save_session_to_cookie") as mock_save, \
             patch.object(auth, "_clear_session_cookie") as mock_clear:
            mst.session_state = {}
            assert auth._refresh_session("good-token") is True
            mock_save.assert_called_once()
            mock_clear.assert_not_called()
            saved = mock_save.call_args.args[0]
            assert saved["refresh_token"] == "new-r"


class TestSignOutServerSideRevocation:
    """Fresh auth client starts empty; sign_out must load the session first so
    Supabase revokes THIS user's refresh token server-side, not silently skip it."""

    def test_loads_in_memory_session_then_revokes(self, auth):
        client = MagicMock()
        session = MagicMock(access_token="a-tok", refresh_token="r-tok")
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_clear_session_cookie"):
            mst.session_state = {auth.SESSION_KEY: session}
            auth.sign_out()
            client.auth.set_session.assert_called_once_with("a-tok", "r-tok")
            client.auth.sign_out.assert_called_once()

    def test_falls_back_to_cookie_tokens(self, auth):
        client = MagicMock()
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_get_session_from_cookie",
                          return_value={"access_token": "ca", "refresh_token": "cr"}), \
             patch.object(auth, "_clear_session_cookie"):
            mst.session_state = {}
            auth.sign_out()
            client.auth.set_session.assert_called_once_with("ca", "cr")
            client.auth.sign_out.assert_called_once()

    def test_clears_local_state_when_no_tokens(self, auth):
        client = MagicMock()
        with patch.object(auth, "st") as mst, \
             patch.object(auth, "_get_auth_client", return_value=client), \
             patch.object(auth, "_get_session_from_cookie", return_value=None), \
             patch.object(auth, "_clear_session_cookie") as mock_clear:
            mst.session_state = {}
            auth.sign_out()
            client.auth.set_session.assert_not_called()
            client.auth.sign_out.assert_called_once()
            mock_clear.assert_called_once()
