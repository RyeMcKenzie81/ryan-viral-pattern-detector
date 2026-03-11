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
from supabase import create_client, Client
from .config import Config


_thread_local = threading.local()
_anon_client: Optional[Client] = None


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
            Config.SUPABASE_ANON_KEY
        )

    return _anon_client


def reset_supabase_client():
    """Reset the Supabase clients (useful for testing)"""
    global _anon_client
    _thread_local.client = None
    _anon_client = None
