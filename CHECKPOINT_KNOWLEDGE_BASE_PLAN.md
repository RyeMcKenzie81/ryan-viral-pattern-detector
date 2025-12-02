# Checkpoint: Knowledge Base System Plan

**Date:** 2025-12-02
**Branch:** main
**Status:** Ready to implement

## Summary

Documented plan for building a vector-based knowledge base (RAG) system using:
- Supabase pgvector for embedding storage
- OpenAI text-embedding-3-small for embeddings
- PydanticAI FunctionToolset for cross-agent sharing
- Streamlit UI for document management

## Plan Document

See: `docs/KNOWLEDGE_BASE_IMPLEMENTATION_PLAN.md`

## Key Decisions

1. **Vector-based RAG** over simple text injection for scalability
2. **FunctionToolset pattern** for reusable tools across agents
3. **OpenAI embeddings** (cheap, high quality) even though we use Claude/Gemini for generation
4. **Supabase pgvector** since already using Supabase
5. **Streamlit UI** for document upload/management with tool usage tracking

## Architecture Overview

```
Streamlit UI → DocService → Supabase pgvector
                    ↓
            knowledge_toolset
                    ↓
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
Ad Creation    Hook Selector    Future Agents
```

## New Files to Create

```
viraltracker/
├── services/knowledge_base/
│   ├── __init__.py
│   ├── models.py
│   └── service.py
├── agent/toolsets/
│   ├── __init__.py
│   └── knowledge_toolset.py
└── ui/pages/
    └── 11_📚_Knowledge_Base.py

sql/
└── create_knowledge_base.sql
```

## New Environment Variable

```
OPENAI_API_KEY=sk-...  # For embeddings only
```

## Implementation Phases

1. Database Setup (SQL migration)
2. Core Service (DocService)
3. Toolset (search_knowledge, get_knowledge_by_category)
4. Agent Integration (add toolset to ad_creation_agent)
5. Streamlit UI (document management)
6. Initial Content (ingest user's docs)

## Next Steps

1. Apply SQL migration to Supabase
2. Build DocService class
3. Create knowledge_toolset
4. Build Streamlit UI
5. Test with sample documents
