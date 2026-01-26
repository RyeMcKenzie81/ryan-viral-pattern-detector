"""
Knowledge Base UI

Manage domain knowledge documents for AI-powered ad creation.
- Browse and search documents
- Upload new documents
- View which tools use each document
- Test semantic search
"""

import streamlit as st
from typing import Optional, List, Dict, Any
from datetime import datetime
import os

# Page config (must be first)
st.set_page_config(
    page_title="Knowledge Base",
    page_icon="📚",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Organization selector for usage tracking
from viraltracker.ui.utils import render_organization_selector
org_id = render_organization_selector(key="knowledge_base_org_selector")
if not org_id:
    st.warning("Please select a workspace to continue.")
    st.stop()

# Initialize session state
if 'kb_view' not in st.session_state:
    st.session_state.kb_view = "browse"  # browse, upload, search
if 'kb_selected_doc' not in st.session_state:
    st.session_state.kb_selected_doc = None


def get_doc_service():
    """Get DocService instance with usage tracking."""
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.knowledge_base import DocService
    from viraltracker.services.usage_tracker import UsageTracker
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    db = get_supabase_client()
    service = DocService(supabase=db, openai_api_key=api_key)

    # Set up usage tracking if org context available
    org_id = get_current_organization_id()
    if org_id and org_id != "all":
        tracker = UsageTracker(db)
        service.set_tracking_context(tracker, get_current_user_id(), org_id)

    return service


# ============================================================================
# Check Configuration
# ============================================================================

doc_service = get_doc_service()

if not doc_service:
    st.title("Knowledge Base")
    st.error("Knowledge base is not configured.")
    st.markdown("""
    ### Setup Required

    To enable the knowledge base, you need:

    1. **OpenAI API Key** - For generating embeddings

       Add to your environment or Railway:
       ```
       OPENAI_API_KEY=sk-...
       ```

    2. **Database Tables** - Run the SQL migration

       Execute `sql/create_knowledge_base.sql` in Supabase SQL Editor.
    """)
    st.stop()


# ============================================================================
# Styles
# ============================================================================

st.markdown("""
<style>
.doc-card {
    background: #1e1e1e;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    border: 1px solid #333;
}
.doc-card:hover {
    border-color: #666;
}
.doc-title {
    font-size: 18px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 8px;
}
.doc-meta {
    font-size: 13px;
    color: #888;
    margin-bottom: 8px;
}
.tag-chip {
    display: inline-block;
    background: #2d4a3e;
    color: #4ade80;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 12px;
    margin-right: 4px;
    margin-bottom: 4px;
}
.tool-chip {
    display: inline-block;
    background: #2d3a4a;
    color: #60a5fa;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 12px;
    margin-right: 4px;
    margin-bottom: 4px;
}
.stats-card {
    background: #262626;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}
.stats-value {
    font-size: 28px;
    font-weight: 700;
    color: #fff;
}
.stats-label {
    font-size: 13px;
    color: #888;
}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Header
# ============================================================================

st.title("Knowledge Base")
st.markdown("Manage domain knowledge for AI-powered ad creation")

# Navigation tabs
col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("Browse", use_container_width=True,
                 type="primary" if st.session_state.kb_view == "browse" else "secondary"):
        st.session_state.kb_view = "browse"
        st.session_state.kb_selected_doc = None
        st.rerun()
with col2:
    if st.button("Upload", use_container_width=True,
                 type="primary" if st.session_state.kb_view == "upload" else "secondary"):
        st.session_state.kb_view = "upload"
        st.rerun()
with col3:
    if st.button("Search Test", use_container_width=True,
                 type="primary" if st.session_state.kb_view == "search" else "secondary"):
        st.session_state.kb_view = "search"
        st.rerun()
with col4:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()


# ============================================================================
# Statistics
# ============================================================================

@st.cache_data(ttl=60)
def get_stats():
    return doc_service.get_stats()


stats = get_stats()

stat_cols = st.columns(4)
with stat_cols[0]:
    st.markdown(f"""
    <div class="stats-card">
        <div class="stats-value">{stats['document_count']}</div>
        <div class="stats-label">Documents</div>
    </div>
    """, unsafe_allow_html=True)
with stat_cols[1]:
    st.markdown(f"""
    <div class="stats-card">
        <div class="stats-value">{stats['chunk_count']}</div>
        <div class="stats-label">Chunks</div>
    </div>
    """, unsafe_allow_html=True)
with stat_cols[2]:
    st.markdown(f"""
    <div class="stats-card">
        <div class="stats-value">{len(stats['tags'])}</div>
        <div class="stats-label">Categories</div>
    </div>
    """, unsafe_allow_html=True)
with stat_cols[3]:
    st.markdown(f"""
    <div class="stats-card">
        <div class="stats-value">{len(stats['tool_usages'])}</div>
        <div class="stats-label">Tool Integrations</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")


# ============================================================================
# Browse View
# ============================================================================

def render_browse_view():
    """Render the document browser."""

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        tag_filter = st.selectbox(
            "Filter by Tag",
            ["All"] + stats['tags'],
            key="tag_filter"
        )
    with col2:
        tool_filter = st.selectbox(
            "Filter by Tool",
            ["All"] + stats['tool_usages'],
            key="tool_filter"
        )

    # Get documents
    @st.cache_data(ttl=30)
    def get_documents():
        return doc_service.list_documents()

    documents = get_documents()

    # Apply filters
    if tag_filter != "All":
        documents = [d for d in documents if tag_filter in d.tags]
    if tool_filter != "All":
        documents = [d for d in documents if tool_filter in d.tool_usage]

    if not documents:
        st.info("No documents found. Upload some knowledge documents to get started!")
        return

    st.markdown(f"**{len(documents)} documents**")

    # Document list
    for doc in documents:
        with st.container():
            col1, col2 = st.columns([4, 1])

            with col1:
                # Format date
                date_str = doc.updated_at.strftime("%b %d, %Y")

                # Get chunk count
                chunk_count = doc_service.get_chunk_count(doc.id)

                # Build tags HTML
                tags_parts = [f'<span class="tag-chip">{tag}</span>' for tag in doc.tags]
                tags_html = "".join(tags_parts)

                # Build tools HTML
                tools_parts = [f'<span class="tool-chip">{tool}</span>' for tool in doc.tool_usage]
                tools_html = "".join(tools_parts)

                # Source text
                source_text = f" | Source: {doc.source}" if doc.source else ""

                # Build complete card HTML
                card_html = f'''<div class="doc-card">
<div class="doc-title">{doc.title}</div>
<div class="doc-meta">{chunk_count} chunks | Updated: {date_str}{source_text}</div>
<div>{tags_html}</div>
<div style="margin-top: 4px">{tools_html}</div>
</div>'''

                st.markdown(card_html, unsafe_allow_html=True)

            with col2:
                st.write("")  # Spacing
                if st.button("View", key=f"view_{doc.id}"):
                    st.session_state.kb_selected_doc = doc.id
                    st.rerun()

                if st.button("Delete", key=f"delete_{doc.id}"):
                    doc_service.delete_document(doc.id)
                    st.cache_data.clear()
                    st.success(f"Deleted: {doc.title}")
                    st.rerun()

    # Document detail modal
    if st.session_state.kb_selected_doc:
        doc = doc_service.get_document(st.session_state.kb_selected_doc)
        if doc:
            st.markdown("---")
            st.subheader(f"📄 {doc.title}")

            if st.button("Close"):
                st.session_state.kb_selected_doc = None
                st.rerun()

            st.markdown(f"**Source:** {doc.source or 'Not specified'}")
            st.markdown(f"**Tags:** {', '.join(doc.tags) or 'None'}")
            st.markdown(f"**Used by tools:** {', '.join(doc.tool_usage) or 'None'}")

            st.markdown("**Content:**")
            st.text_area(
                "Document content",
                doc.content,
                height=400,
                disabled=True,
                label_visibility="collapsed"
            )


# ============================================================================
# Upload View
# ============================================================================

def render_upload_view():
    """Render the document upload form."""
    st.subheader("Upload New Document")

    with st.form("upload_form"):
        title = st.text_input(
            "Document Title *",
            placeholder="e.g., Hook Formulas Cheat Sheet"
        )

        content = st.text_area(
            "Content *",
            height=300,
            placeholder="Paste your document content here...\n\nThis can be copywriting guides, hook formulas, brand guidelines, etc."
        )

        col1, col2 = st.columns(2)
        with col1:
            source = st.text_input(
                "Source (optional)",
                placeholder="URL, file path, or description"
            )

        with col2:
            # Predefined tags
            available_tags = ["copywriting", "hooks", "brand", "templates", "products", "competitors"]
            tags = st.multiselect(
                "Tags",
                available_tags,
                default=[]
            )

        # Tool usage
        available_tools = ["hook_selector", "ad_review", "ad_creation"]
        tool_usage = st.multiselect(
            "Used by Tools",
            available_tools,
            default=["hook_selector"],
            help="Which agent tools should use this knowledge"
        )

        # Advanced options
        with st.expander("Advanced Options"):
            chunk_size = st.slider(
                "Chunk Size (words)",
                min_value=100,
                max_value=1000,
                value=500,
                step=50,
                help="How many words per chunk for embedding"
            )
            chunk_overlap = st.slider(
                "Chunk Overlap (words)",
                min_value=0,
                max_value=100,
                value=50,
                step=10,
                help="Words to overlap between chunks"
            )

        submitted = st.form_submit_button("Upload Document", type="primary")

        if submitted:
            if not title or not content:
                st.error("Title and content are required")
            else:
                with st.spinner("Processing document..."):
                    try:
                        doc = doc_service.ingest(
                            title=title,
                            content=content,
                            tags=tags,
                            tool_usage=tool_usage,
                            source=source,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap
                        )
                        st.cache_data.clear()
                        st.success(f"Document uploaded: {doc.title}")
                        st.info(f"Created {doc_service.get_chunk_count(doc.id)} searchable chunks")
                    except Exception as e:
                        st.error(f"Upload failed: {str(e)}")


# ============================================================================
# Search Test View
# ============================================================================

def render_search_view():
    """Render the search testing interface."""
    st.subheader("Test Semantic Search")
    st.markdown("Test how the knowledge base responds to search queries.")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Search Query",
            placeholder="e.g., hook formulas for urgency"
        )
    with col2:
        limit = st.number_input("Results", min_value=1, max_value=20, value=5)

    # Optional tag filter
    tag_filter = st.multiselect(
        "Filter by Tags (optional)",
        stats['tags']
    )

    if st.button("Search", type="primary"):
        if not query:
            st.warning("Enter a search query")
        else:
            with st.spinner("Searching..."):
                results = doc_service.search(
                    query=query,
                    limit=limit,
                    tags=tag_filter if tag_filter else None
                )

            if not results:
                st.info("No results found")
            else:
                st.success(f"Found {len(results)} results")

                for i, result in enumerate(results, 1):
                    similarity_pct = f"{result.similarity:.0%}"
                    with st.expander(f"**{i}. {result.title}** (Relevance: {similarity_pct})"):
                        st.markdown(f"**Tags:** {', '.join(result.tags)}")
                        st.markdown(f"**Tools:** {', '.join(result.tool_usage)}")
                        st.markdown("---")
                        st.markdown(result.chunk_content)


# ============================================================================
# Main Render
# ============================================================================

if st.session_state.kb_view == "browse":
    render_browse_view()
elif st.session_state.kb_view == "upload":
    render_upload_view()
elif st.session_state.kb_view == "search":
    render_search_view()
