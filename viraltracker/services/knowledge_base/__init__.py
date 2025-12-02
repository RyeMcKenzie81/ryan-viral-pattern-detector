"""
Knowledge Base Service

Provides vector-based semantic search over domain knowledge documents.
Uses Supabase pgvector for storage and OpenAI for embeddings.
"""

from .models import Document, Chunk, SearchResult
from .service import DocService

__all__ = ["DocService", "Document", "Chunk", "SearchResult"]
