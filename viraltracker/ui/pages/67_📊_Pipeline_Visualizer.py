"""
Pipeline Visualizer - Visual documentation for Pydantic-Graph workflows.

This page displays:
- Overview of all pipeline graphs with node counts
- Interactive Mermaid diagrams for each pipeline
- Node-by-node breakdown with descriptions
- Logfire integration info for runtime observability
"""

import streamlit as st

# Page config
st.set_page_config(
    page_title="Pipeline Visualizer",
    page_icon="📊",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# ============================================================================
# Helper Functions
# ============================================================================

def get_graph_viz():
    """Lazy import graph visualization utilities."""
    from viraltracker.utils.graph_viz import (
        get_all_graphs_info,
        get_graph_mermaid_code,
        get_graph_image_bytes,
        get_node_details,
    )
    return get_all_graphs_info, get_graph_mermaid_code, get_graph_image_bytes, get_node_details


def get_logfire_status():
    """Check if Logfire is configured."""
    import os
    token = os.environ.get("LOGFIRE_TOKEN")
    return bool(token)


# ============================================================================
# Page Content
# ============================================================================

st.title("📊 Pipeline Visualizer")
st.markdown("**Pydantic-Graph workflows with Mermaid diagrams and Logfire tracing**")

st.divider()

# Load graph info
try:
    get_all_graphs_info, get_graph_mermaid_code, get_graph_image_bytes, get_node_details = get_graph_viz()
    graphs_info = get_all_graphs_info()
except Exception as e:
    st.error(f"Failed to load graph information: {e}")
    st.stop()

# ============================================================================
# Metrics Row
# ============================================================================

total_nodes = sum(g["node_count"] for g in graphs_info)
logfire_status = get_logfire_status()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Pipelines", len(graphs_info), help="Total pydantic-graph workflows")
with col2:
    st.metric("Total Nodes", total_nodes, help="Sum of all nodes across pipelines")
with col3:
    st.metric(
        "Largest Pipeline",
        max(g["node_count"] for g in graphs_info),
        help="Most nodes in a single pipeline"
    )
with col4:
    st.metric(
        "Logfire Status",
        "Connected" if logfire_status else "Not Configured",
        help="Runtime observability status"
    )

st.divider()

# ============================================================================
# Tabs
# ============================================================================

tab1, tab2, tab3 = st.tabs(["Overview", "Pipeline Details", "Logfire Integration"])

# ----------------------------------------------------------------------------
# Tab 1: Overview
# ----------------------------------------------------------------------------
with tab1:
    st.subheader("Pipeline Overview")

    st.markdown("""
    These are the pydantic-graph workflows in ViralTracker. Each pipeline is a
    directed acyclic graph (DAG) of nodes that execute sequentially, with state
    passed between nodes.
    """)

    for graph in graphs_info:
        with st.container():
            col1, col2 = st.columns([1, 3])

            with col1:
                st.markdown(f"### {graph['name'].replace('_', ' ').title()}")
                st.metric("Nodes", graph["node_count"])

            with col2:
                st.markdown(f"**{graph['description']}**")
                st.markdown(f"`Start:` {graph['start_node']}")

                # Show node flow
                node_flow = " → ".join(graph["nodes"])
                st.code(node_flow, language=None)

            st.divider()

# ----------------------------------------------------------------------------
# Tab 2: Pipeline Details
# ----------------------------------------------------------------------------
with tab2:
    st.subheader("Pipeline Details")

    # Pipeline selector
    pipeline_options = {g["name"]: g["name"].replace("_", " ").title() for g in graphs_info}
    selected_pipeline = st.selectbox(
        "Select Pipeline",
        options=list(pipeline_options.keys()),
        format_func=lambda x: pipeline_options[x],
    )

    if selected_pipeline:
        # Get graph info
        graph_info = next((g for g in graphs_info if g["name"] == selected_pipeline), None)

        if graph_info:
            st.markdown(f"### {pipeline_options[selected_pipeline]}")
            st.markdown(f"*{graph_info['description']}*")

            # Layout options
            col1, col2 = st.columns([3, 1])
            with col2:
                direction = st.radio(
                    "Layout Direction",
                    options=["LR", "TB"],
                    format_func=lambda x: "Left to Right" if x == "LR" else "Top to Bottom",
                    horizontal=True,
                )

            st.divider()

            # Show Mermaid diagram
            st.markdown("#### Workflow Diagram")

            try:
                # Try to get image bytes for display
                image_bytes = get_graph_image_bytes(selected_pipeline, format="png", direction=direction)
                st.image(image_bytes, caption=f"{pipeline_options[selected_pipeline]} Workflow")
            except Exception as e:
                # Fallback to Mermaid code
                st.warning(f"Could not render image (mermaid.ink may be unavailable): {e}")
                st.markdown("**Mermaid Code** (paste into [mermaid.live](https://mermaid.live) to visualize):")
                mermaid_code = get_graph_mermaid_code(selected_pipeline, direction=direction)
                st.code(mermaid_code, language="mermaid")

            st.divider()

            # Node details
            st.markdown("#### Node Breakdown")

            nodes = graph_info["nodes"]
            for i, node in enumerate(nodes):
                is_start = i == 0
                is_end = i == len(nodes) - 1

                with st.expander(f"**{i+1}. {node}**" + (" (Start)" if is_start else "") + (" (End)" if is_end else "")):
                    st.markdown(f"**Position:** Step {i+1} of {len(nodes)}")

                    if is_start:
                        st.info("This is the entry point for the pipeline.")
                    if is_end:
                        st.success("This is the final step before completion.")

                    # Show what comes next
                    if not is_end:
                        st.markdown(f"**Next:** {nodes[i+1]}")

            st.divider()

            # Export options
            st.markdown("#### Export Options")
            col1, col2 = st.columns(2)

            with col1:
                if st.button("Copy Mermaid Code", key="copy_mermaid"):
                    mermaid_code = get_graph_mermaid_code(selected_pipeline, direction=direction)
                    st.code(mermaid_code, language="mermaid")
                    st.info("Copy the code above and paste into mermaid.live")

            with col2:
                st.markdown("**CLI Export:**")
                st.code(f"python -m viraltracker.utils.graph_viz -g {selected_pipeline} -o ./diagrams", language="bash")

# ----------------------------------------------------------------------------
# Tab 3: Logfire Integration
# ----------------------------------------------------------------------------
with tab3:
    st.subheader("Logfire Integration")

    if logfire_status:
        st.success("Logfire is configured and ready for tracing.")
    else:
        st.warning("Logfire is not configured. Set LOGFIRE_TOKEN to enable tracing.")

    st.markdown("""
    ### What Logfire Captures

    With `logfire.instrument_pydantic_ai()` enabled, you can see:

    | Data | Description |
    |------|-------------|
    | **LLM Prompts** | Exact prompts sent to Claude, GPT, Gemini |
    | **LLM Responses** | Full model outputs |
    | **Token Usage** | Input/output tokens per call |
    | **Costs** | Estimated cost per request |
    | **Tool Calls** | Agent tool invocations with inputs/outputs |
    | **Timing** | Latency for each operation |
    | **Traces** | Hierarchical view of execution flow |
    """)

    st.divider()

    st.markdown("### How to Use")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Static Visualization (Mermaid)")
        st.markdown("""
        Use the **Pipeline Details** tab to see workflow structure:
        - Node sequence and connections
        - Entry and exit points
        - Export diagrams for documentation
        """)

    with col2:
        st.markdown("#### Runtime Observability (Logfire)")
        st.markdown("""
        Use Logfire dashboard to see actual execution:
        - Real prompts and responses
        - Performance bottlenecks
        - Cost analysis per pipeline
        - Error traces
        """)

    st.divider()

    st.markdown("### Quick Links")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("[Logfire Dashboard](https://logfire.pydantic.dev/)")
        st.caption("View traces and metrics")

    with col2:
        st.markdown("[Mermaid Live Editor](https://mermaid.live/)")
        st.caption("Paste diagram code to visualize")

    with col3:
        st.markdown("[Pydantic AI Docs](https://ai.pydantic.dev/graph/)")
        st.caption("Graph workflow documentation")

    st.divider()

    st.markdown("### CLI Commands")

    st.code("""
# List all pipelines
python -m viraltracker.utils.graph_viz --list

# Export all graphs as PNGs
python -m viraltracker.utils.graph_viz --all --output ./diagrams

# Get Mermaid code for a specific pipeline
python -m viraltracker.utils.graph_viz -g brand_onboarding --code

# Export single pipeline as SVG
python -m viraltracker.utils.graph_viz -g reddit_sentiment -f svg -o ./diagrams
    """, language="bash")
