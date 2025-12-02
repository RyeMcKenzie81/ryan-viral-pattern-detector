"""
Knowledge Base Service

Provides document ingestion, embedding, and semantic search capabilities.
Uses Supabase pgvector for storage and OpenAI for embeddings.
"""

import os
import re
import logging
from typing import Optional
from datetime import datetime

from openai import OpenAI
from supabase import Client as SupabaseClient

from .models import Document, Chunk, SearchResult, DocumentCreate, DocumentUpdate

logger = logging.getLogger(__name__)


class DocService:
    """
    Knowledge base service for document storage and semantic search.

    Uses OpenAI text-embedding-3-small for embeddings and Supabase pgvector
    for vector storage and similarity search.
    """

    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS = 1536
    DEFAULT_CHUNK_SIZE = 500  # words
    DEFAULT_CHUNK_OVERLAP = 50  # words

    def __init__(
        self,
        supabase: SupabaseClient,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize the DocService.

        Args:
            supabase: Supabase client instance
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.supabase = supabase
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        if not api_key:
            logger.warning("OPENAI_API_KEY not set - embedding functions will fail")
            self.openai = None
        else:
            self.openai = OpenAI(api_key=api_key)

    def _ensure_openai(self):
        """Raise error if OpenAI client not configured."""
        if not self.openai:
            raise ValueError(
                "OpenAI client not configured. Set OPENAI_API_KEY environment variable."
            )

    # =========================================================================
    # Embedding
    # =========================================================================

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding for text using OpenAI.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector
        """
        self._ensure_openai()

        response = self.openai.embeddings.create(
            input=text,
            model=self.EMBEDDING_MODEL
        )
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in a single API call.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        self._ensure_openai()

        response = self.openai.embeddings.create(
            input=texts,
            model=self.EMBEDDING_MODEL
        )
        return [item.embedding for item in response.data]

    # =========================================================================
    # Chunking
    # =========================================================================

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    ) -> list[str]:
        """
        Split text into overlapping chunks by word count.

        Args:
            text: Text to chunk
            chunk_size: Target words per chunk
            chunk_overlap: Words to overlap between chunks

        Returns:
            List of text chunks
        """
        # Clean and split into words
        words = text.split()

        if len(words) <= chunk_size:
            return [text.strip()]

        chunks = []
        start = 0

        while start < len(words):
            end = start + chunk_size
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text.strip())

            # Move start forward, accounting for overlap
            start = end - chunk_overlap

            # Avoid infinite loop if overlap >= chunk_size
            if start >= len(words) - chunk_overlap:
                break

        return chunks

    # =========================================================================
    # Document Operations
    # =========================================================================

    def ingest(
        self,
        title: str,
        content: str,
        tags: list[str] = None,
        tool_usage: list[str] = None,
        source: str = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    ) -> Document:
        """
        Ingest a document: create record, chunk content, embed chunks, store.

        Args:
            title: Document title
            content: Full document content
            tags: Categories (e.g., ['copywriting', 'hooks'])
            tool_usage: Tools that use this doc (e.g., ['hook_selector'])
            source: Origin URL, path, or description
            chunk_size: Words per chunk
            chunk_overlap: Words to overlap between chunks

        Returns:
            Created Document object
        """
        self._ensure_openai()

        tags = tags or []
        tool_usage = tool_usage or []

        logger.info(f"Ingesting document: {title}")

        # 1. Create document record
        doc_result = self.supabase.table("knowledge_documents").insert({
            "title": title,
            "content": content,
            "tags": tags,
            "tool_usage": tool_usage,
            "source": source
        }).execute()

        if not doc_result.data:
            raise ValueError("Failed to create document record")

        doc_data = doc_result.data[0]
        doc_id = doc_data["id"]

        logger.info(f"Created document {doc_id}, chunking content...")

        # 2. Chunk the content
        chunks = self._chunk_text(content, chunk_size, chunk_overlap)
        logger.info(f"Created {len(chunks)} chunks")

        # 3. Embed all chunks in batch
        embeddings = self.embed_batch(chunks)
        logger.info(f"Generated {len(embeddings)} embeddings")

        # 4. Store chunks with embeddings
        chunk_records = [
            {
                "document_id": doc_id,
                "content": chunk_text,
                "chunk_index": i,
                "embedding": embedding
            }
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
        ]

        self.supabase.table("knowledge_chunks").insert(chunk_records).execute()
        logger.info(f"Stored {len(chunk_records)} chunks")

        return Document(
            id=doc_id,
            title=doc_data["title"],
            content=doc_data["content"],
            tags=doc_data["tags"],
            tool_usage=doc_data["tool_usage"],
            source=doc_data.get("source"),
            created_at=datetime.fromisoformat(doc_data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(doc_data["updated_at"].replace("Z", "+00:00"))
        )

    def search(
        self,
        query: str,
        limit: int = 8,
        tags: list[str] = None
    ) -> list[SearchResult]:
        """
        Semantic search over knowledge base.

        Args:
            query: Natural language search query
            limit: Maximum results to return
            tags: Optional tag filter (documents must have at least one matching tag)

        Returns:
            List of SearchResult objects ordered by similarity
        """
        self._ensure_openai()

        # Generate query embedding
        query_embedding = self.embed(query)

        # Call the match_knowledge function
        result = self.supabase.rpc(
            "match_knowledge",
            {
                "query_embedding": query_embedding,
                "match_count": limit,
                "filter_tags": tags
            }
        ).execute()

        return [SearchResult(**r) for r in result.data]

    def get_document(self, document_id: str) -> Optional[Document]:
        """
        Get a document by ID.

        Args:
            document_id: UUID of the document

        Returns:
            Document object or None if not found
        """
        result = self.supabase.table("knowledge_documents").select("*").eq(
            "id", document_id
        ).execute()

        if not result.data:
            return None

        data = result.data[0]
        return Document(
            id=data["id"],
            title=data["title"],
            content=data["content"],
            tags=data["tags"],
            tool_usage=data["tool_usage"],
            source=data.get("source"),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        )

    def get_by_tags(self, tags: list[str]) -> list[Document]:
        """
        Get all documents matching any of the given tags.

        Args:
            tags: List of tags to match

        Returns:
            List of matching Document objects
        """
        result = self.supabase.table("knowledge_documents").select("*").overlaps(
            "tags", tags
        ).order("updated_at", desc=True).execute()

        return [
            Document(
                id=d["id"],
                title=d["title"],
                content=d["content"],
                tags=d["tags"],
                tool_usage=d["tool_usage"],
                source=d.get("source"),
                created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
                updated_at=datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00"))
            )
            for d in result.data
        ]

    def get_by_tool(self, tool_name: str) -> list[Document]:
        """
        Get all documents used by a specific tool.

        Args:
            tool_name: Name of the tool (e.g., 'hook_selector')

        Returns:
            List of matching Document objects
        """
        result = self.supabase.table("knowledge_documents").select("*").contains(
            "tool_usage", [tool_name]
        ).order("updated_at", desc=True).execute()

        return [
            Document(
                id=d["id"],
                title=d["title"],
                content=d["content"],
                tags=d["tags"],
                tool_usage=d["tool_usage"],
                source=d.get("source"),
                created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
                updated_at=datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00"))
            )
            for d in result.data
        ]

    def list_documents(self) -> list[Document]:
        """
        List all documents in the knowledge base.

        Returns:
            List of all Document objects, newest first
        """
        result = self.supabase.table("knowledge_documents").select("*").order(
            "updated_at", desc=True
        ).execute()

        return [
            Document(
                id=d["id"],
                title=d["title"],
                content=d["content"],
                tags=d["tags"],
                tool_usage=d["tool_usage"],
                source=d.get("source"),
                created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
                updated_at=datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00"))
            )
            for d in result.data
        ]

    def update_document(
        self,
        document_id: str,
        update: DocumentUpdate
    ) -> Optional[Document]:
        """
        Update a document's metadata. Does NOT re-chunk/re-embed content.

        For content updates, delete and re-ingest the document.

        Args:
            document_id: UUID of the document
            update: Fields to update

        Returns:
            Updated Document or None if not found
        """
        update_data = update.model_dump(exclude_none=True)

        if not update_data:
            return self.get_document(document_id)

        # If content is being updated, we need to re-chunk and re-embed
        if "content" in update_data:
            # Delete old chunks
            self.supabase.table("knowledge_chunks").delete().eq(
                "document_id", document_id
            ).execute()

            # Update document
            result = self.supabase.table("knowledge_documents").update(
                update_data
            ).eq("id", document_id).execute()

            if not result.data:
                return None

            # Re-chunk and re-embed
            doc_data = result.data[0]
            chunks = self._chunk_text(update_data["content"])
            embeddings = self.embed_batch(chunks)

            chunk_records = [
                {
                    "document_id": document_id,
                    "content": chunk_text,
                    "chunk_index": i,
                    "embedding": embedding
                }
                for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
            ]

            self.supabase.table("knowledge_chunks").insert(chunk_records).execute()
        else:
            result = self.supabase.table("knowledge_documents").update(
                update_data
            ).eq("id", document_id).execute()

            if not result.data:
                return None

            doc_data = result.data[0]

        return Document(
            id=doc_data["id"],
            title=doc_data["title"],
            content=doc_data["content"],
            tags=doc_data["tags"],
            tool_usage=doc_data["tool_usage"],
            source=doc_data.get("source"),
            created_at=datetime.fromisoformat(doc_data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(doc_data["updated_at"].replace("Z", "+00:00"))
        )

    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document and all its chunks.

        Args:
            document_id: UUID of the document to delete

        Returns:
            True if deleted, False if not found
        """
        # Chunks are deleted automatically via CASCADE
        result = self.supabase.table("knowledge_documents").delete().eq(
            "id", document_id
        ).execute()

        return len(result.data) > 0

    def get_chunk_count(self, document_id: str) -> int:
        """
        Get the number of chunks for a document.

        Args:
            document_id: UUID of the document

        Returns:
            Number of chunks
        """
        result = self.supabase.table("knowledge_chunks").select(
            "id", count="exact"
        ).eq("document_id", document_id).execute()

        return result.count or 0

    def get_stats(self) -> dict:
        """
        Get knowledge base statistics.

        Returns:
            Dict with document_count, chunk_count, tags, tool_usages
        """
        # Count documents
        doc_result = self.supabase.table("knowledge_documents").select(
            "id", count="exact"
        ).execute()

        # Count chunks
        chunk_result = self.supabase.table("knowledge_chunks").select(
            "id", count="exact"
        ).execute()

        # Get unique tags and tool_usages
        docs = self.list_documents()
        all_tags = set()
        all_tools = set()
        for doc in docs:
            all_tags.update(doc.tags)
            all_tools.update(doc.tool_usage)

        return {
            "document_count": doc_result.count or 0,
            "chunk_count": chunk_result.count or 0,
            "tags": sorted(list(all_tags)),
            "tool_usages": sorted(list(all_tools))
        }
