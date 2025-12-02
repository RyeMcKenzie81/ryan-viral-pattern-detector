# Knowledge Base Implementation

**Date:** 2025-12-02
**Status:** ✅ Implemented
**Branch:** main

## Overview

Build a vector-based knowledge base (RAG) system that allows domain-specific knowledge to be shared across multiple PydanticAI agents and tools. Uses Supabase pgvector for embeddings storage and OpenAI for embedding generation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit UI                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Upload Docs  │  │ Browse Docs  │  │ View Tool Usage      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DocService                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ ingest()     │  │ search()     │  │ get_by_tag()         │   │
│  │ embed()      │  │ delete()     │  │ list_documents()     │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│ OpenAI Embeddings│ │ Supabase     │ │ docs_toolset             │
│ text-embedding-  │ │ pgvector     │ │ (FunctionToolset)        │
│ 3-small          │ │              │ │ - search_knowledge()     │
└──────────────────┘ └──────────────┘ │ - get_knowledge_by_tag() │
                                      └──────────────────────────┘
                                                  │
                              ┌───────────────────┼───────────────┐
                              ▼                   ▼               ▼
                    ┌──────────────┐    ┌──────────────┐  ┌──────────────┐
                    │ Ad Creation  │    │ Hook         │  │ Future       │
                    │ Agent        │    │ Selector     │  │ Agents...    │
                    └──────────────┘    └──────────────┘  └──────────────┘
```

## Database Schema

### Table: `knowledge_documents`

Main document metadata table.

```sql
CREATE TABLE knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    source TEXT,                    -- URL, file path, or description of origin
    content TEXT NOT NULL,          -- Full document content
    tags TEXT[] DEFAULT '{}',       -- Categories: ['copywriting', 'hooks', 'brand']
    tool_usage TEXT[] DEFAULT '{}', -- Which tools use this: ['hook_selector', 'ad_review']
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Table: `knowledge_chunks`

Chunked content with embeddings for semantic search.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding vector(1536),         -- OpenAI text-embedding-3-small dimension
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector similarity search index (HNSW - works for any dataset size)
CREATE INDEX ON knowledge_chunks
USING hnsw (embedding vector_cosine_ops);
```

### Function: `match_knowledge`

Semantic search function.

```sql
CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(1536),
    match_count INT DEFAULT 8,
    filter_tags TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    title TEXT,
    content TEXT,
    tags TEXT[],
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        kc.id as chunk_id,
        kd.id as document_id,
        kd.title,
        kc.content,
        kd.tags,
        1 - (kc.embedding <=> query_embedding) as similarity
    FROM knowledge_chunks kc
    JOIN knowledge_documents kd ON kc.document_id = kd.id
    WHERE (filter_tags IS NULL OR kd.tags && filter_tags)
    ORDER BY kc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

## Python Implementation

### 1. Pydantic Models

```python
# viraltracker/services/knowledge_base/models.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Document(BaseModel):
    id: str
    title: str
    source: Optional[str] = None
    content: str
    tags: list[str] = []
    tool_usage: list[str] = []
    created_at: datetime
    updated_at: datetime

class Chunk(BaseModel):
    id: str
    document_id: str
    content: str
    chunk_index: int

class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    content: str
    tags: list[str]
    similarity: float
```

### 2. DocService

```python
# viraltracker/services/knowledge_base/service.py

class DocService:
    """Knowledge base service for document storage and semantic search."""

    def __init__(self, supabase: SupabaseClient, openai_api_key: str):
        self.supabase = supabase
        self.openai = AsyncOpenAI(api_key=openai_api_key)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        response = await self.openai.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    async def ingest(
        self,
        title: str,
        content: str,
        tags: list[str] = [],
        tool_usage: list[str] = [],
        source: str = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ) -> Document:
        """Ingest a document: chunk it, embed chunks, store in DB."""
        # 1. Create document record
        # 2. Chunk content
        # 3. Embed each chunk
        # 4. Store chunks with embeddings
        ...

    async def search(
        self,
        query: str,
        limit: int = 8,
        tags: list[str] = None
    ) -> list[SearchResult]:
        """Semantic search over knowledge base."""
        embedding = await self.embed(query)
        result = self.supabase.rpc(
            "match_knowledge",
            {
                "query_embedding": embedding,
                "match_count": limit,
                "filter_tags": tags
            }
        ).execute()
        return [SearchResult(**r) for r in result.data]

    async def get_by_tags(self, tags: list[str]) -> list[Document]:
        """Get all documents with specific tags."""
        ...

    async def list_documents(self) -> list[Document]:
        """List all documents."""
        ...

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks."""
        ...
```

### 3. FunctionToolset

```python
# viraltracker/agent/toolsets/knowledge_toolset.py

from pydantic_ai import FunctionToolset, RunContext
from ..dependencies import AgentDependencies

knowledge_toolset = FunctionToolset()

@knowledge_toolset.tool
async def search_knowledge(
    ctx: RunContext[AgentDependencies],
    query: str,
    tags: list[str] = None,
    limit: int = 5
) -> str:
    """
    Search the knowledge base for relevant information.

    Use this to find copywriting best practices, hook formulas,
    brand guidelines, or other domain knowledge.

    Args:
        query: What to search for (natural language)
        tags: Optional filter by category ['copywriting', 'hooks', 'brand']
        limit: Max results to return (default 5)

    Returns:
        Relevant knowledge passages with sources
    """
    results = await ctx.deps.docs.search(query, limit=limit, tags=tags)

    if not results:
        return "No relevant knowledge found."

    # Format results for LLM consumption
    formatted = []
    for r in results:
        formatted.append(f"## {r.title}\n{r.content}\n")

    return "\n---\n".join(formatted)


@knowledge_toolset.tool
async def get_knowledge_by_category(
    ctx: RunContext[AgentDependencies],
    category: str
) -> str:
    """
    Get all knowledge documents in a specific category.

    Categories: copywriting, hooks, brand, products, competitors

    Args:
        category: The category to retrieve

    Returns:
        All documents in that category
    """
    docs = await ctx.deps.docs.get_by_tags([category])

    if not docs:
        return f"No documents found in category: {category}"

    formatted = []
    for doc in docs:
        formatted.append(f"## {doc.title}\n{doc.content}\n")

    return "\n---\n".join(formatted)
```

### 4. Integration with AgentDependencies

```python
# viraltracker/agent/dependencies.py (modified)

from viraltracker.services.knowledge_base import DocService

@dataclass
class AgentDependencies:
    supabase: SupabaseClient
    gemini: GeminiService
    docs: DocService  # NEW
    # ... other services
```

### 5. Attach to Agents

```python
# viraltracker/agent/agents/ad_creation_agent.py (modified)

from ..toolsets.knowledge_toolset import knowledge_toolset

ad_creation_agent = Agent(
    "claude-opus-4-5-20251101",
    deps_type=AgentDependencies,
    toolsets=[knowledge_toolset],  # Add toolset
    system_prompt="""
    You are an expert ad creation agent.

    Use search_knowledge() to find relevant copywriting best practices,
    hook formulas, and brand guidelines when crafting ad copy.
    """
)
```

## Streamlit UI

### Page: Knowledge Base (11_📚_Knowledge_Base.py)

Features:
1. **Document List** - Browse all documents with tags and tool usage
2. **Search** - Test semantic search
3. **Upload** - Add new documents (text paste, file upload, URL)
4. **Edit/Delete** - Manage existing documents
5. **Tool Usage** - See which tools reference each document

```
┌─────────────────────────────────────────────────────────────────┐
│  📚 Knowledge Base                                               │
├─────────────────────────────────────────────────────────────────┤
│  [Upload New Document]  [Test Search]                           │
│                                                                  │
│  Filter: [All Tags ▼]  [All Tools ▼]                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 📄 Copywriting Power Words Guide                           │ │
│  │ Tags: copywriting, hooks                                   │ │
│  │ Used by: hook_selector, ad_review                          │ │
│  │ Chunks: 12 | Updated: Dec 2, 2025                          │ │
│  │ [View] [Edit] [Delete]                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 📄 Hook Formulas & Templates                               │ │
│  │ Tags: hooks, templates                                     │ │
│  │ Used by: hook_selector                                     │ │
│  │ Chunks: 8 | Updated: Dec 2, 2025                           │ │
│  │ [View] [Edit] [Delete]                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Status

### Phase 1: Database Setup ✅
1. Created SQL migration `sql/create_knowledge_base.sql`
2. Applied to Supabase with pgvector 0.8.0
3. **Note:** Changed from IVFFlat to HNSW index (IVFFlat requires minimum ~100 documents to work properly)

### Phase 2: Core Service ✅
1. Created `viraltracker/services/knowledge_base/` module
2. Implemented Pydantic models in `models.py`
3. Implemented DocService class in `service.py`
4. Added DocService to AgentDependencies

### Phase 3: Toolset ✅
1. Created `viraltracker/agent/toolsets/knowledge_toolset.py`
2. Implemented search_knowledge tool
3. Implemented get_knowledge_by_category tool
4. Implemented list_knowledge_categories tool

### Phase 4: Agent Integration ✅
1. Integrated with `select_hooks()` - queries knowledge base for hook writing techniques
2. Integrated with `generate_benefit_variations()` - queries for copywriting best practices when using "Recreate Template"
3. Both functions include knowledge context in prompts when available

### Phase 5: Streamlit UI ✅
1. Created Knowledge Base page at `pages/07_📚_Knowledge_Base.py`
2. Browse view - list documents with metadata
3. Upload view - add new documents with tags
4. Search Test view - test semantic search with relevance scores

### Phase 6: Initial Content ✅
1. User uploaded "Hook Writing Best Practices for Direct-Response Advertising" document
2. Search verified working with 40-65% relevance scores for hook-related queries

## Environment Variables

New variables needed:

```
OPENAI_API_KEY=sk-...  # For embeddings only
```

## File Structure

```
viraltracker/
├── services/
│   └── knowledge_base/
│       ├── __init__.py
│       ├── models.py          # Pydantic models
│       └── service.py         # DocService class
├── agent/
│   ├── toolsets/
│   │   ├── __init__.py
│   │   └── knowledge_toolset.py
│   └── dependencies.py        # Modified
└── ui/
    └── pages/
        └── 07_📚_Knowledge_Base.py
```

## Success Criteria ✅

1. ✅ Documents can be uploaded via Streamlit UI
2. ✅ Semantic search returns relevant chunks
3. ✅ Hook selector uses knowledge base for better copy
4. ✅ Multiple agents can share the same knowledge
5. ✅ Tool usage tracking shows which tools use which docs

## Ad Creation Workflow Integration

The knowledge base is integrated into two key functions in `ad_creation_agent.py`:

### 1. `select_hooks()` (line ~2080)
When selecting hooks for an ad, queries the knowledge base with:
```python
f"hook writing techniques {target_audience} advertising"
```
Tags: `["hooks", "copywriting"]`

### 2. `generate_benefit_variations()` (line ~2504)
When using "Recreate Template" to generate headline variations, queries with:
```python
f"hook writing {angle_type} {target_audience} direct response advertising"
```
Tags: `["hooks", "copywriting"]`

Both integrations:
- Check if `ctx.deps.docs` is available
- Query for up to 3 relevant knowledge chunks
- Format results as markdown sections
- Include in the generation prompt under "COPYWRITING BEST PRACTICES FROM KNOWLEDGE BASE"
- Fail gracefully if knowledge base is unavailable
