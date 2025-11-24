"""
Agent Catalog - Comprehensive documentation for the PydanticAI agent architecture.

This page documents the orchestrator pattern with:
- 1 Orchestrator Agent with 5 routing tools
- 5 Specialized Agents (Twitter, TikTok, YouTube, Facebook, Analysis)
- Total: 19 underlying tools + 5 routing tools = 24 tools
- All agents use claude-sonnet-4-5-20250929
"""

import streamlit as st

# Page config
st.set_page_config(
    page_title="Agent Catalog",
    page_icon="🤖",
    layout="wide"
)

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
│   - 5 routing tools                             │
└──────────────────┬──────────────────────────────┘
                   │
       ┌───────────┼───────────┬─────────┬────────┐
       │           │           │         │        │
       ▼           ▼           ▼         ▼        ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐ ┌─────────┐
   │Twitter │ │TikTok  │ │YouTube │ │ FB   │ │Analysis │
   │8 tools │ │5 tools │ │1 tool  │ │2 tool│ │3 tools  │
   └────────┘ └────────┘ └────────┘ └──────┘ └─────────┘
    """, language=None)

st.divider()

# ============================================================================
# Metrics
# ============================================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Agents", "6", help="1 Orchestrator + 5 Specialized")
with col2:
    st.metric("Routing Tools", "5", help="Orchestrator routing tools")
with col3:
    st.metric("Platform Tools", "19", help="Specialized agent tools")
with col4:
    st.metric("Total Tools", "24", help="Routing + Platform tools")

st.divider()

# ============================================================================
# Agent Details
# ============================================================================

st.subheader("Agent Details")

# Create tabs for each agent
tabs = st.tabs([
    "Orchestrator",
    "Twitter Agent",
    "TikTok Agent",
    "YouTube Agent",
    "Facebook Agent",
    "Analysis Agent"
])

# Orchestrator Agent
with tabs[0]:
    st.markdown("### Orchestrator Agent")
    st.markdown("**Role:** Intelligent request routing and coordination")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.orchestrator`")

    st.divider()

    st.markdown("""
    The orchestrator is the main entry point for all agent requests. It analyzes user queries
    and routes them to the appropriate specialized agent.

    **Responsibilities:**
    - Understand user intent from natural language
    - Identify platform and task requirements
    - Route to the most appropriate specialized agent
    - Pass relevant context and parameters
    - Coordinate multi-step workflows
    - Summarize results from specialized agents

    **Routing Logic:**
    - Keywords: "Twitter", "tweet", "X" → Twitter Agent
    - Keywords: "TikTok", "video", "hashtag" → TikTok Agent
    - Keywords: "YouTube", "shorts" → YouTube Agent
    - Keywords: "Facebook", "ad", "Meta" → Facebook Agent
    - Keywords: "analyze", "outliers", "statistics" → Analysis Agent
    """)

    st.divider()

    st.markdown("#### Routing Tools (5)")

    tools = [
        {
            "name": "route_to_twitter_agent",
            "description": "Route request to Twitter Agent for Twitter/X operations",
            "parameters": "query: str",
            "returns": "str (result from Twitter Agent)"
        },
        {
            "name": "route_to_tiktok_agent",
            "description": "Route request to TikTok Agent for TikTok operations",
            "parameters": "query: str",
            "returns": "str (result from TikTok Agent)"
        },
        {
            "name": "route_to_youtube_agent",
            "description": "Route request to YouTube Agent for YouTube operations",
            "parameters": "query: str",
            "returns": "str (result from YouTube Agent)"
        },
        {
            "name": "route_to_facebook_agent",
            "description": "Route request to Facebook Agent for Facebook Ad Library operations",
            "parameters": "query: str",
            "returns": "str (result from Facebook Agent)"
        },
        {
            "name": "route_to_analysis_agent",
            "description": "Route request to Analysis Agent for statistical and AI analysis",
            "parameters": "query: str",
            "returns": "str (result from Analysis Agent)"
        }
    ]

    for tool in tools:
        with st.expander(f"📌 `{tool['name']}`", expanded=False):
            st.markdown(f"**Description:** {tool['description']}")
            st.markdown(f"**Parameters:** `{tool['parameters']}`")
            st.markdown(f"**Returns:** `{tool['returns']}`")

# Twitter Agent
with tabs[1]:
    st.markdown("### Twitter Agent")
    st.markdown("**Role:** Twitter/X platform specialist")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.agents.twitter_agent`")

    st.divider()

    st.markdown("""
    Handles all Twitter/X data operations including searching, scraping, analysis, and content generation.

    **Capabilities:**
    - Search and scrape tweets by keyword
    - Find viral tweets with high engagement
    - Identify comment opportunities
    - Analyze search term performance
    - Generate content from viral hooks
    - Export data to various formats

    **Services Used:**
    - `TwitterService` - Database queries
    - `ScrapingService` - Apify scraping
    - `GeminiService` - AI analysis
    - `StatsService` - Engagement calculations
    """)

    st.divider()

    st.markdown("#### Tools (8)")

    twitter_tools = [
        ("search_twitter_tool", "Search and scrape tweets by keyword using Apify"),
        ("get_top_tweets_tool", "Get top tweets from database by engagement metrics"),
        ("export_tweets_tool", "Export tweets to CSV/JSON format"),
        ("find_comment_opportunities_tool", "Find viral tweets suitable for commenting"),
        ("export_comments_tool", "Export comment opportunities to file"),
        ("analyze_search_term_tool", "Analyze keyword performance and trends"),
        ("generate_content_tool", "Generate content from viral hooks using AI"),
        ("verify_scrape_tool", "Verify scraping results and data quality")
    ]

    for tool_name, description in twitter_tools:
        with st.expander(f"🔧 `{tool_name}`", expanded=False):
            st.markdown(f"**Description:** {description}")
            st.markdown(f"**Platform:** Twitter/X")

# TikTok Agent
with tabs[2]:
    st.markdown("### TikTok Agent")
    st.markdown("**Role:** TikTok platform specialist")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.agents.tiktok_agent`")

    st.divider()

    st.markdown("""
    Handles TikTok video discovery, analysis, and user research.

    **Capabilities:**
    - Search TikTok by keyword or hashtag
    - Scrape user accounts and profiles
    - Analyze individual videos
    - Batch analyze multiple videos
    - Track trending content
    """)

    st.divider()

    st.markdown("#### Tools (5)")

    tiktok_tools = [
        ("search_tiktok_tool", "Search TikTok videos by keyword or hashtag"),
        ("scrape_user_tool", "Scrape TikTok user account and videos"),
        ("analyze_video_tool", "Analyze single TikTok video"),
        ("batch_analyze_videos_tool", "Analyze multiple videos in batch"),
        ("export_tiktok_tool", "Export TikTok data to file")
    ]

    for tool_name, description in tiktok_tools:
        with st.expander(f"🔧 `{tool_name}`", expanded=False):
            st.markdown(f"**Description:** {description}")
            st.markdown(f"**Platform:** TikTok")

# YouTube Agent
with tabs[3]:
    st.markdown("### YouTube Agent")
    st.markdown("**Role:** YouTube platform specialist")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.agents.youtube_agent`")

    st.divider()

    st.markdown("""
    Handles YouTube video search and discovery, including Shorts.

    **Capabilities:**
    - Search YouTube videos by keyword
    - Find trending Shorts
    - Video metadata extraction
    """)

    st.divider()

    st.markdown("#### Tools (1)")

    youtube_tools = [
        ("search_youtube_tool", "Search YouTube videos and Shorts by keyword")
    ]

    for tool_name, description in youtube_tools:
        with st.expander(f"🔧 `{tool_name}`", expanded=False):
            st.markdown(f"**Description:** {description}")
            st.markdown(f"**Platform:** YouTube")

# Facebook Agent
with tabs[4]:
    st.markdown("### Facebook Agent")
    st.markdown("**Role:** Facebook Ad Library specialist")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.agents.facebook_agent`")

    st.divider()

    st.markdown("""
    Handles Facebook Ad Library operations for competitive research.

    **Capabilities:**
    - Search ads by URL
    - Scrape ads from specific pages
    - Track ad creative and copy
    - Monitor competitor advertising
    """)

    st.divider()

    st.markdown("#### Tools (2)")

    facebook_tools = [
        ("search_ads_tool", "Search Facebook Ad Library by URL"),
        ("scrape_page_ads_tool", "Scrape all ads from a specific Facebook page")
    ]

    for tool_name, description in facebook_tools:
        with st.expander(f"🔧 `{tool_name}`", expanded=False):
            st.markdown(f"**Description:** {description}")
            st.markdown(f"**Platform:** Facebook")

# Analysis Agent
with tabs[5]:
    st.markdown("### Analysis Agent")
    st.markdown("**Role:** Advanced analytics and AI-powered insights")
    st.markdown("**Model:** `claude-sonnet-4-5-20250929`")
    st.markdown("**Module:** `viraltracker.agent.agents.analysis_agent`")

    st.divider()

    st.markdown("""
    Handles cross-platform analysis, statistical outlier detection, and AI-powered insights.

    **Capabilities:**
    - Find viral outliers using statistical methods
    - Analyze tweet hooks with AI
    - Export comprehensive analysis reports
    - Cross-platform trend analysis

    **Services Used:**
    - `StatsService` - Z-score and percentile calculations
    - `GeminiService` - AI hook analysis
    - `TwitterService` - Data retrieval
    """)

    st.divider()

    st.markdown("#### Tools (3)")

    analysis_tools = [
        ("find_outliers_tool", "Find viral outliers using Z-score or percentile methods"),
        ("analyze_hooks_tool", "AI-powered analysis of viral hooks and content patterns"),
        ("export_analysis_tool", "Export analysis results to JSON/CSV with full metadata")
    ]

    for tool_name, description in analysis_tools:
        with st.expander(f"🔧 `{tool_name}`", expanded=False):
            st.markdown(f"**Description:** {description}")
            st.markdown(f"**Platform:** Cross-platform")

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
    **Example 3: Outlier Detection**

    ```
    User: "Find viral outliers from last week"

    Flow:
    1. Orchestrator receives query
    2. Identifies "outliers" → routes to Analysis Agent
    3. Analysis Agent calls find_outliers_tool
    4. Returns statistical outliers with Z-scores
    ```
    """)

    st.markdown("""
    **Example 4: Multi-Platform Research**

    ```
    User: "Find content about Bitcoin on Twitter and TikTok"

    Flow:
    1. Orchestrator receives query
    2. Routes to Twitter Agent for tweets
    3. Routes to TikTok Agent for videos
    4. Coordinates results from both agents
    5. Returns unified insights
    ```
    """)

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption("""
**Architecture Benefits:**
- Clear separation of concerns (1 orchestrator, 5 specialists)
- Automatic intelligent routing based on intent
- Scalable pattern - easy to add new agents
- Consistent model across all agents (Claude Sonnet 4.5)
- Inter-agent communication via ResultCache

**Total Capability:** 24 tools across 6 agents covering Twitter, TikTok, YouTube, Facebook, and cross-platform analysis.
""")
