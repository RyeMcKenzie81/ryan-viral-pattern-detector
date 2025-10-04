"""
Core module - Database, configuration, and data models
"""

from .database import get_supabase_client
from .config import Config

__all__ = ['get_supabase_client', 'Config']
