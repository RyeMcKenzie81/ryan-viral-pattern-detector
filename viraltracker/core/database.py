"""
Database client and utilities

Two client types:
- Service client (get_supabase_client): Uses service key, bypasses RLS. For workers/agents.
- Anon client (get_anon_client): Uses anon key, RLS enforced. For UI auth operations.

Thread safety: get_supabase_client() is thread-local so background workflow threads
get their own client instance (httpx.Client is not thread-safe).
"""

import threading
from typing import Optional
from supabase import create_client, Client, ClientOptions
from .config import Config


_thread_local = threading.local()
_anon_client: Optional[Client] = None

# Auth clients must NOT run the background auto-refresher or persist a single
# global session. In a multi-session Streamlit/server process the supabase-py
# defaults (auto_refresh_token=True, persist_session=True) cause two failures:
#   1. A background timer rotates the in-memory session's refresh token out of
#      band, without writing it back to the user's cookie. The cookie then holds
#      an already-rotated token; the next page load refreshes with it, Supabase's
#      reuse detection fires, and the whole token family is revoked -> logout.
#   2. The session is mutable shared state: one browser session's set_session()
#      clobbers another's on the shared singleton client.
# We drive refresh explicitly from the cookie instead (see ui/auth.py), so the
# client only ever holds a session for the duration of one request.
_AUTH_CLIENT_OPTIONS = ClientOptions(
    auto_refresh_token=False,
    persist_session=False,
)


def get_supabase_client() -> Client:
    """
    Get or create Supabase client with SERVICE KEY (thread-local).

    Uses service key which bypasses RLS - use for workers and backend operations.
    Each thread gets its own client instance for thread safety.

    Returns:
        Supabase client instance with service key
    """
    if not hasattr(_thread_local, 'client') or _thread_local.client is None:
        Config.validate()
        _thread_local.client = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_SERVICE_KEY
        )

    return _thread_local.client


def get_anon_client() -> Client:
    """
    Get or create Supabase client with ANON KEY (singleton pattern).

    Uses anon key which respects RLS - use for UI auth operations.
    Falls back to service key if anon key not configured.

    Returns:
        Supabase client instance with anon key
    """
    global _anon_client

    if _anon_client is None:
        # Check if anon key is configured
        if not Config.SUPABASE_ANON_KEY:
            # Fall back to service client if anon key not set
            import logging
            logging.getLogger(__name__).warning(
                "SUPABASE_ANON_KEY not set, falling back to service key for auth"
            )
            return get_supabase_client()

        _anon_client = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_ANON_KEY,
            options=_AUTH_CLIENT_OPTIONS,
        )

    return _anon_client


def create_auth_client() -> Client:
    """Create a FRESH anon client for a single auth operation.

    Unlike get_anon_client()'s process-wide singleton, this returns a new client
    instance on every call so one browser session's set_session()/refresh_session()
    cannot clobber another's session on shared mutable state. Auto-refresh and
    session persistence are disabled (see _AUTH_CLIENT_OPTIONS) so refresh is
    driven explicitly from the cookie, not a background timer.

    Falls back to the service client if the anon key is not configured (mirrors
    get_anon_client()).
    """
    if not Config.SUPABASE_ANON_KEY:
        # No anon key: fall back to the service key, but still a FRESH client with
        # the auth-safe options (not the shared get_supabase_client() singleton,
        # whose default options would reintroduce the background refresher /
        # shared-session bug this function exists to avoid). Service key bypasses
        # RLS — only reached when the anon key is unconfigured.
        import logging
        logging.getLogger(__name__).warning(
            "SUPABASE_ANON_KEY not set, falling back to service key for auth"
        )
        Config.validate()
        return create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_SERVICE_KEY,
            options=_AUTH_CLIENT_OPTIONS,
        )

    return create_client(
        Config.SUPABASE_URL,
        Config.SUPABASE_ANON_KEY,
        options=_AUTH_CLIENT_OPTIONS,
    )


def reset_supabase_client():
    """Reset the Supabase clients (useful for testing)"""
    global _anon_client
    _thread_local.client = None
    _anon_client = None
