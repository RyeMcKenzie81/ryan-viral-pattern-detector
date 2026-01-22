"""
Services Catalog - Auto-generated documentation for the service layer.

This page automatically extracts all services from viraltracker/services/
and displays them organized by category.

Benefits:
- Zero-maintenance documentation (auto-updates when services are added)
- Single source of truth (service class definitions)
- No hardcoded data - everything extracted via introspection
"""

import streamlit as st
import inspect
from typing import get_type_hints

# Page config
st.set_page_config(
    page_title="Services Catalog",
    page_icon="⚙️",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

st.title("⚙️ Services Catalog")
st.markdown("**Explore all services organized by functional category**")

st.divider()

# ============================================================================
# Architecture Overview
# ============================================================================

st.subheader("Service Layer Architecture")

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("""
    **Architecture Pattern:**

    The service layer provides reusable business logic
    accessible from all interfaces:
    - Agent tools (thin wrappers)
    - Streamlit UI pages
    - CLI commands
    - FastAPI endpoints

    **Key Principles:**
    - Services contain business logic
    - Tools are thin orchestration wrappers
    - Services are stateless (DB via Supabase)
    - Async methods for I/O operations
    """)

with col2:
    st.code("""
┌─────────────────────────────────────────────────┐
│          AGENT LAYER (PydanticAI)               │
│   Orchestrator → Specialized Agents → Tools     │
└──────────────────┬──────────────────────────────┘
                   │  (thin wrappers)
┌──────────────────▼──────────────────────────────┐
│          SERVICE LAYER (Core)                   │
│   Platform | AI/LLM | Content | Research | ...  │
│                                                 │
│   - Business logic implementation               │
│   - Database operations                         │
│   - External API integrations                   │
│   - Reusable across all interfaces              │
└──────────────────┬──────────────────────────────┘
                   │
       ┌───────────┼───────────┬──────────────┐
       │           │           │              │
       ▼           ▼           ▼              ▼
    ┌──────┐  ┌───────┐  ┌─────────┐  ┌────────────┐
    │ CLI  │  │ Agent │  │Streamlit│  │ FastAPI    │
    └──────┘  └───────┘  └─────────┘  └────────────┘
    """, language=None)

st.divider()

# ============================================================================
# Get Services from Collector
# ============================================================================

try:
    from viraltracker.agent.service_collector import (
        get_services_by_category,
        get_service_stats
    )

    # Get services and stats
    services_by_category = get_services_by_category()
    stats = get_service_stats()

except Exception as e:
    st.error(f"Error loading services: {e}")
    st.info("Services could not be loaded. This may be due to import errors in service files.")
    st.stop()

if not services_by_category:
    st.warning("No services found.")
    st.stop()

# ============================================================================
# Metrics
# ============================================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Services", stats['total_services'], help="Service classes discovered")
with col2:
    st.metric("Total Methods", stats['total_methods'], help="Public methods across all services")
with col3:
    st.metric("Categories", stats['categories'], help="Functional categories")
with col4:
    st.metric("Avg Methods/Service", stats['avg_methods_per_service'], help="Average methods per service")

st.divider()

# ============================================================================
# Helper Functions
# ============================================================================

def render_method(method_info):
    """Render a single method with its details."""
    # Method header
    async_badge = "🔄 " if method_info.is_async else ""
    with st.expander(f"📌 `{async_badge}{method_info.name}()`", expanded=False):
        # Docstring
        doc_lines = method_info.docstring.split('\n\n')
        summary = doc_lines[0] if doc_lines else "No documentation"
        st.markdown(f"**{summary}**")

        if len(doc_lines) > 1:
            st.divider()
            for section in doc_lines[1:]:
                st.markdown(section)

        st.divider()

        # Signature
        st.markdown("**Signature:**")
        async_prefix = "async " if method_info.is_async else ""
        st.code(f"{async_prefix}def {method_info.name}{method_info.signature}", language="python")

        # Parameters
        if method_info.parameters:
            st.markdown("**Parameters:**")
            for param in method_info.parameters:
                required_badge = " *(required)*" if param.required else f" = `{param.default}`"
                st.markdown(f"- **`{param.name}`** (`{param.type_str}`){required_badge}")

        # Return type
        st.markdown(f"**Returns:** `{method_info.return_type}`")


def render_service(service_info):
    """Render a service with all its methods."""
    with st.expander(f"🔧 **{service_info.name}** ({service_info.method_count} methods)", expanded=False):
        # Description
        st.markdown(f"**Description:** {service_info.description}")
        st.markdown(f"**Module:** `{service_info.module_path}`")

        # Full docstring if different from description
        if service_info.full_docstring and service_info.full_docstring != service_info.description:
            if len(service_info.full_docstring) > len(service_info.description) + 10:
                st.divider()
                st.markdown("**Details:**")
                st.markdown(service_info.full_docstring)

        st.divider()

        # Methods
        if service_info.methods:
            st.markdown("**Methods:**")
            for method_info in service_info.methods:
                render_method(method_info)
        else:
            st.info("No public methods found")

# ============================================================================
# Category Descriptions
# ============================================================================

CATEGORY_DESCRIPTIONS = {
    'Platform': 'Platform-specific integrations (Twitter, TikTok, YouTube, Facebook, Meta Ads)',
    'AI/LLM': 'AI model integrations (Gemini, Veo, ElevenLabs)',
    'Content Creation': 'Content generation and creative workflows',
    'Research & Analysis': 'Research tools and analytical services',
    'Business Logic': 'Core business logic and workflow management',
    'Utility': 'Utility services (FFmpeg, statistics, comparisons)',
    'Integration': 'External integrations (Apify, Slack, email, scraping)',
    'Comic Video': 'Comic video production pipeline services',
    'Content Pipeline': 'Content pipeline orchestration and node services',
    'Knowledge Base': 'RAG knowledge base and document services',
    'Models': 'Pydantic model definitions',
    'Other': 'Uncategorized services'
}

# Define preferred category order
CATEGORY_ORDER = [
    'Platform',
    'AI/LLM',
    'Content Creation',
    'Research & Analysis',
    'Business Logic',
    'Utility',
    'Integration',
    'Comic Video',
    'Content Pipeline',
    'Knowledge Base',
    'Models',
    'Other'
]

# ============================================================================
# Display Services by Category
# ============================================================================

st.subheader("Services by Category")

# Create tabs for categories (in preferred order)
ordered_categories = [cat for cat in CATEGORY_ORDER if cat in services_by_category]
# Add any categories not in our order list
for cat in services_by_category:
    if cat not in ordered_categories:
        ordered_categories.append(cat)

if not ordered_categories:
    st.info("No services available.")
    st.stop()

tabs = st.tabs(ordered_categories)

for tab, category in zip(tabs, ordered_categories):
    with tab:
        services = services_by_category.get(category, [])

        # Category description
        description = CATEGORY_DESCRIPTIONS.get(category, '')
        if description:
            st.markdown(f"*{description}*")

        st.markdown(f"**{len(services)} service(s) in this category**")

        st.divider()

        # Display each service
        for service_info in services:
            render_service(service_info)

# ============================================================================
# Category Breakdown
# ============================================================================

st.divider()
st.subheader("Category Breakdown")

# Show category distribution
col1, col2 = st.columns(2)

with col1:
    st.markdown("**Services per Category:**")
    for category in ordered_categories:
        count = len(services_by_category.get(category, []))
        st.markdown(f"- **{category}**: {count} services")

with col2:
    st.markdown("**Method Statistics:**")
    st.markdown(f"- **Total Methods:** {stats['total_methods']}")
    st.markdown(f"- **Async Methods:** {stats['async_methods']} ({round(stats['async_methods']/stats['total_methods']*100, 1)}%)")
    st.markdown(f"- **Sync Methods:** {stats['sync_methods']}")
    st.markdown(f"- **Average per Service:** {stats['avg_methods_per_service']}")

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"""
**Auto-Generated Catalog**
This page automatically extracts service information from class definitions.
When new services are added to `viraltracker/services/`, they appear here automatically.

**Total Services:** {stats['total_services']} | **Total Methods:** {stats['total_methods']} | **Last Updated:** On page load
""")
