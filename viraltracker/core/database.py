"""
Database client and utilities
"""

from typing import Optional
from supabase import create_client, Client
from .config import Config


_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client (singleton pattern)

    Returns:
        Supabase client instance
    """
    global _supabase_client

    if _supabase_client is None:
        Config.validate()
        _supabase_client = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_SERVICE_KEY
        )

    return _supabase_client


def reset_supabase_client():
    """Reset the Supabase client (useful for testing)"""
    global _supabase_client
    _supabase_client = None
