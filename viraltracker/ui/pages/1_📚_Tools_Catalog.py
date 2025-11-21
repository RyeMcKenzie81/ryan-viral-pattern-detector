"""
Tools Catalog - Auto-generated documentation for agent tools.

This page automatically extracts all registered tools from the tool_registry
and displays them organized by the data pipeline taxonomy:
- Ingestion → Filtration → Discovery → Analysis → Generation → Export

Benefits:
- Zero-maintenance documentation (auto-updates when tools are registered)
- Single source of truth (tool_registry)
- No hardcoded data - everything extracted from registry
"""

import streamlit as st
from viraltracker.agent.tool_registry import tool_registry

# Page config
st.set_page_config(
    page_title="Tools Catalog",
    page_icon="📚",
    layout="wide"
)

st.title("📚 Agent Tools Catalog")
st.markdown("**Explore all available agent tools organized by data pipeline stage**")

st.divider()

# ============================================================================
# Pipeline Overview
# ============================================================================

st.subheader("Data Pipeline Stages")

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("""
    **Pipeline Taxonomy:**
    1. **Ingestion** - Collect data from external sources
    2. **Filtration** - Remove unwanted content (spam, off-topic)
    3. **Discovery** - Find interesting patterns (outliers, trends)
    4. **Analysis** - Deep analysis with AI and statistics
    5. **Generation** - Create new content from insights
    6. **Export** - Save and share results
    """)

with col2:
    st.code("""
┌──────────────────────────────────────────────┐
│          DATA PIPELINE FLOW                  │
│                                              │
│  Ingestion → Filtration → Discovery →       │
│  Analysis → Generation → Export              │
│                                              │
│  Examples:                                   │
│  • Scrape tweets (Ingestion)                │
│  • Filter spam/politics (Filtration)        │
│  • Find outliers (Discovery)                │
│  • Analyze hooks (Analysis)                 │
│  • Generate content (Generation)            │
│  • Export reports (Export)                  │
└──────────────────────────────────────────────┘
    """, language=None)

st.divider()

# ============================================================================
# Get Tools from Registry
# ============================================================================

# Fetch all registered tools
all_tools = tool_registry.get_all_tools()

if not all_tools:
    st.warning("No tools registered yet. Register tools using @tool_registry.register() decorator.")
    st.stop()

# Organize tools by category
categories = ["Ingestion", "Filtration", "Discovery", "Analysis", "Generation", "Export"]
tools_by_category = {cat: [] for cat in categories}

for tool_name, tool_meta in all_tools.items():
    category = tool_meta.category
    if category not in tools_by_category:
        tools_by_category[category] = []
    tools_by_category[category].append(tool_meta)

# Display statistics
total_tools = len(all_tools)
categories_with_tools = len([cat for cat, tools in tools_by_category.items() if tools])

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Tools", total_tools)
with col2:
    st.metric("Pipeline Stages", categories_with_tools)
with col3:
    st.metric("Platforms", len(set(tool.platform for tool in all_tools.values())))

st.divider()

# ============================================================================
# Display Tools by Category
# ============================================================================

st.subheader("Tools by Pipeline Stage")

# Create tabs for each category that has tools
tabs_to_create = [cat for cat in categories if tools_by_category[cat]]

if not tabs_to_create:
    st.info("No tools available yet.")
    st.stop()

tabs = st.tabs(tabs_to_create)

for tab, category in zip(tabs, tabs_to_create):
    with tab:
        tools = tools_by_category[category]

        # Category header
        st.markdown(f"### {category} Tools")

        if category == "Ingestion":
            st.markdown("*Collect data from external sources (Twitter, TikTok, YouTube, etc.)*")
        elif category == "Filtration":
            st.markdown("*Remove unwanted content (spam, harmful, off-topic)*")
        elif category == "Discovery":
            st.markdown("*Find interesting patterns, outliers, and opportunities*")
        elif category == "Analysis":
            st.markdown("*Deep analysis with AI, statistics, and pattern recognition*")
        elif category == "Generation":
            st.markdown("*Generate new content, reports, and insights*")
        elif category == "Export":
            st.markdown("*Save and share results in various formats*")

        st.divider()

        # Display each tool
        for tool in tools:
            # Tool name and description
            tool_display_name = tool.name.replace('_tool', '').replace('_', ' ').title()

            with st.expander(f"🔧 **{tool_display_name}**", expanded=False):
                # Platform badge
                st.markdown(f"**Platform:** `{tool.platform}`")

                # Description
                st.markdown(f"**Description:** {tool.description}")

                # API path
                st.markdown(f"**API Endpoint:** `POST {tool.api_path}`")

                # Rate limit
                st.markdown(f"**Rate Limit:** `{tool.rate_limit}`")

                st.divider()

                # Use cases
                if tool.use_cases:
                    st.markdown("**Use Cases:**")
                    for use_case in tool.use_cases:
                        st.markdown(f"- {use_case}")
                    st.divider()

                # Example queries
                if tool.examples:
                    st.markdown("**Example Queries:**")
                    for example in tool.examples:
                        st.markdown(f"> \"{example}\"")
                    st.divider()

                # Function signature (if available)
                st.markdown("**Implementation:**")
                st.code(f"Function: {tool.name}()", language="python")

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"""
**Auto-Generated Catalog**
This page automatically extracts tool information from the `tool_registry`.
When new tools are registered with `@tool_registry.register()`, they appear here automatically.

**Total Tools:** {total_tools} | **Last Updated:** On page load
""")
