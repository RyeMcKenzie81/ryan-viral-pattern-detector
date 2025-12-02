"""
Knowledge Base Models

Pydantic models for the knowledge base system.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Document(BaseModel):
    """A knowledge document with metadata."""

    id: str
    title: str
    source: Optional[str] = None
    content: str
    tags: list[str] = []
    tool_usage: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Chunk(BaseModel):
    """A chunk of a document with its embedding."""

    id: str
    document_id: str
    content: str
    chunk_index: int

    class Config:
        from_attributes = True


class SearchResult(BaseModel):
    """A semantic search result."""

    chunk_id: str
    document_id: str
    title: str
    chunk_content: str
    tags: list[str]
    tool_usage: list[str]
    similarity: float

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    """Input model for creating a document."""

    title: str
    content: str
    source: Optional[str] = None
    tags: list[str] = []
    tool_usage: list[str] = []


class DocumentUpdate(BaseModel):
    """Input model for updating a document."""

    title: Optional[str] = None
    content: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[list[str]] = None
    tool_usage: Optional[list[str]] = None
