"""
Agent Catalog - Auto-generated documentation for the PydanticAI agent architecture.

This page automatically extracts all agents and displays them with their tools.
The orchestrator pattern routes queries to specialized platform agents.

Benefits:
- Zero-maintenance documentation (auto-updates when agents are added)
- Single source of truth (agent definitions)
- No hardcoded data - everything extracted from agents
"""

import streamlit as st

# Page config
st.set_page_config(
    page_title="Agent Catalog",
    page_icon="🤖",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

st.title("🤖 Agent Catalog")
st.markdown("**Intelligent orchestrator pattern with specialized platform agents**")

st.divider()

# ============================================================================
# Architecture Overview
# ============================================================================

st.subheader("Orchestrator Pattern Architecture")

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("""
    **Pattern:** Orchestrator + Specialized Agents

    The orchestrator analyzes user queries and routes them to specialized agents based on:
    - Platform (Twitter, TikTok, YouTube, Facebook)
    - Task type (scraping, analysis, generation)
    - Context and intent

    **Benefits:**
    - Clear separation of concerns
    - Specialized expertise per platform
    - Automatic intelligent routing
    - Scalable architecture
    """)

with col2:
    st.code("""
┌─────────────────────────────────────────────────┐
│            USER QUERY                           │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│      ORCHESTRATOR AGENT                         │
│   - Analyzes intent                             │
│   - Routes to specialized agent                 │
│   - Coordinates multi-step workflows            │
└──────────────────┬──────────────────────────────┘
                   │
       ┌───────────┼───────────┬─────────┬────────┐
       │           │           │         │        │
       ▼           ▼           ▼         ▼        ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐ ┌─────────┐
   │Twitter │ │TikTok  │ │YouTube │ │ FB   │ │Analysis │
   │ Agent  │ │ Agent  │ │ Agent  │ │Agent │ │  Agent  │
   └────────┘ └────────┘ └────────┘ └──────┘ └─────────┘
    """, language=None)

st.divider()

# ============================================================================
# Get Agents from Collector
# ============================================================================

try:
    from viraltracker.agent.agent_collector import (
        get_all_agents,
        get_agent_stats
    )

    # Get agents and stats
    all_agents = get_all_agents()
    stats = get_agent_stats()

except Exception as e:
    st.error(f"Error loading agents: {e}")
    st.info("Agents could not be loaded. This may be due to import errors.")
    st.stop()

if not all_agents:
    st.warning("No agents found.")
    st.stop()

# ============================================================================
# Metrics
# ============================================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Agents", stats['total_agents'], help="1 Orchestrator + Specialists")
with col2:
    st.metric("Routing Tools", stats['routing_tools'], help="Orchestrator routing tools")
with col3:
    st.metric("Platform Tools", stats['platform_tools'], help="Specialized agent tools")
with col4:
    st.metric("Total Tools", stats['total_tools'], help="Routing + Platform tools")

st.divider()

# ============================================================================
# Helper Functions
# ============================================================================

def render_tool_list(tools, expanded=False):
    """Render a list of tools as expandable items."""
    for tool in tools:
        with st.expander(f"🔧 `{tool.name}`", expanded=expanded):
            st.markdown(f"**Description:** {tool.description}")
            st.markdown(f"**Category:** `{tool.category}`")


def render_agent(agent_info):
    """Render an agent with all its details."""
    # Header
    st.markdown(f"### {agent_info.display_name}")
    st.markdown(f"**Role:** {agent_info.role}")
    st.markdown(f"**Model:** `{agent_info.model}`")
    st.markdown(f"**Module:** `{agent_info.module_path}`")

    st.divider()

    # Description from system prompt
    if agent_info.system_prompt:
        # Extract key sections from system prompt
        prompt_lines = agent_info.system_prompt.split('\n')
        summary_lines = []
        in_section = False

        for line in prompt_lines[:30]:  # First 30 lines max
            line = line.strip()
            if line.startswith('**') or line.startswith('Your role') or line.startswith('This agent'):
                in_section = True
            if in_section and line:
                summary_lines.append(line)
            if len(summary_lines) > 10:
                break

        if summary_lines:
            st.markdown('\n'.join(summary_lines[:10]))
    else:
        st.markdown(agent_info.description)

    st.divider()

    # Tools section
    st.markdown(f"#### Tools ({agent_info.tool_count})")

    if agent_info.tools:
        render_tool_list(agent_info.tools)
    else:
        st.info("No tools registered for this agent")


# ============================================================================
# Agent Details
# ============================================================================

st.subheader("Agent Details")

# Create tabs for each agent
# Order: Orchestrator first, then specialists alphabetically
agent_order = ['orchestrator'] + sorted(
    [name for name in all_agents.keys() if name != 'orchestrator']
)

# Create tab names
tab_names = []
for agent_name in agent_order:
    if agent_name in all_agents:
        agent = all_agents[agent_name]
        tab_names.append(agent.display_name)

if not tab_names:
    st.info("No agents available.")
    st.stop()

tabs = st.tabs(tab_names)

for tab, agent_name in zip(tabs, agent_order):
    if agent_name in all_agents:
        with tab:
            render_agent(all_agents[agent_name])

# ============================================================================
# Workflow Examples
# ============================================================================

st.divider()

st.subheader("Example Workflows")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    **Example 1: Find Viral Tweets**

    ```
    User: "Find 100 tweets about AI"

    Flow:
    1. Orchestrator receives query
    2. Identifies "tweets" → routes to Twitter Agent
    3. Twitter Agent calls search_twitter_tool
    4. Returns results with engagement metrics
    ```
    """)

    st.markdown("""
    **Example 2: TikTok Trend Analysis**

    ```
    User: "Analyze trending TikToks for #fitness"

    Flow:
    1. Orchestrator receives query
    2. Identifies "TikTok" → routes to TikTok Agent
    3. TikTok Agent calls search_tiktok_tool
    4. Calls batch_analyze_videos_tool
    5. Returns trend insights
    ```
    """)

with col2:
    st.markdown("""
    **Example 3: Create Facebook Ads**

    ```
    User: "Create 5 ads for Wonder Paws"

    Flow:
    1. Orchestrator receives query
    2. Routes to Ad Creation Agent
    3. Agent analyzes reference ad (Claude vision)
    4. Selects hooks and product images
    5. Generates 5 ad variations (Gemini)
    6. Dual AI review (Claude + Gemini)
    7. Returns approved ads
    ```
    """)

    st.markdown("""
    **Example 4: Generate Audio**

    ```
    User: "Generate audio from this ELS script"

    Flow:
    1. Orchestrator receives query
    2. Routes to Audio Production Agent
    3. Validates ELS script format
    4. Parses into structured beats
    5. Generates audio via ElevenLabs
    6. Adds pauses via FFmpeg
    7. Exports final audio
    ```
    """)

# ============================================================================
# Agent Summary Table
# ============================================================================

st.divider()

st.subheader("Agent Summary")

# Create summary table
summary_data = []
for agent_name in agent_order:
    if agent_name in all_agents:
        agent = all_agents[agent_name]
        summary_data.append({
            'Agent': agent.display_name,
            'Role': agent.role,
            'Tools': agent.tool_count,
            'Model': agent.model.split('/')[-1] if '/' in agent.model else agent.model
        })

if summary_data:
    import pandas as pd
    df = pd.DataFrame(summary_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"""
**Auto-Generated Catalog**
This page automatically extracts agent information from definitions.
When new agents are added, they appear here automatically.

**Architecture Benefits:**
- Clear separation of concerns (1 orchestrator, {stats['specialist_count']} specialists)
- Automatic intelligent routing based on intent
- Scalable pattern - easy to add new agents
- Inter-agent communication via ResultCache

**Total Capability:** {stats['total_tools']} tools across {stats['total_agents']} agents
""")
