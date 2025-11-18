"""
Tools Catalog - Comprehensive reference for all Pydantic AI agent tools.

This page provides:
- Tool descriptions and use cases
- Parameter documentation with types and defaults
- Copy-paste example queries
- Platform organization (Twitter, TikTok, YouTube, Facebook)
"""

import streamlit as st

# Page config
st.set_page_config(
    page_title="Tools Catalog",
    page_icon="📚",
    layout="wide"
)

st.title("📚 Agent Tools Catalog")
st.markdown("**16 specialized tools across 4 platforms for viral content analysis**")

# ============================================================================
# Platform Filter
# ============================================================================

platform_filter = st.selectbox(
    "Filter by Platform",
    ["All Platforms", "Twitter", "TikTok", "YouTube", "Facebook"]
)

st.divider()

# ============================================================================
# Tool Data Structure
# ============================================================================

TOOLS = [
    # Phase 1 - Core Analysis
    {
        "name": "find_outliers_tool",
        "platform": "Twitter",
        "phase": "Phase 1 - Core Analysis",
        "description": "Find statistically viral tweets using Z-score analysis",
        "use_cases": ["See viral tweets", "Find outliers", "Identify top performers"],
        "parameters": [
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range to analyze"},
            {"name": "threshold", "type": "float", "default": "2.0", "desc": "Z-score threshold for virality"},
            {"name": "method", "type": "str", "default": "zscore", "desc": "Analysis method (zscore/percentile)"},
            {"name": "min_views", "type": "int", "default": "None", "desc": "Minimum view count filter"},
            {"name": "text_only", "type": "bool", "default": "False", "desc": "Text-only tweets (no media)"},
            {"name": "limit", "type": "int", "default": "20", "desc": "Max results to return"},
        ],
        "returns": "OutlierResult with viral tweets, statistics, and engagement metrics",
        "examples": [
            "Show me viral tweets from today",
            "Find top performers from last 48 hours with threshold 1.5",
            "Get outliers from last week",
        ],
    },
    {
        "name": "analyze_hooks_tool",
        "platform": "Twitter",
        "phase": "Phase 1 - Core Analysis",
        "description": "Analyze what makes tweets go viral using AI classification",
        "use_cases": ["Understand why tweets went viral", "Find hook patterns", "Study emotional triggers"],
        "parameters": [
            {"name": "tweet_ids", "type": "list[str]", "default": "None", "desc": "Specific tweets to analyze"},
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range to analyze"},
            {"name": "limit", "type": "int", "default": "20", "desc": "Max tweets to analyze"},
            {"name": "min_views", "type": "int", "default": "None", "desc": "Minimum view count filter"},
        ],
        "returns": "HookAnalysisResult with hook types, emotional triggers, and patterns",
        "examples": [
            "Why did those tweets go viral?",
            "Analyze hooks from top performers",
            "What emotional triggers work best?",
        ],
    },
    {
        "name": "export_results_tool",
        "platform": "Twitter",
        "phase": "Phase 1 - Core Analysis",
        "description": "Export comprehensive analysis report combining outliers and hooks",
        "use_cases": ["Download analysis", "Export data", "Save report"],
        "parameters": [
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range to analyze"},
            {"name": "threshold", "type": "float", "default": "2.0", "desc": "Z-score threshold"},
            {"name": "include_hooks", "type": "bool", "default": "True", "desc": "Include hook analysis"},
            {"name": "format", "type": "str", "default": "markdown", "desc": "Export format"},
        ],
        "returns": "Full markdown report with combined analysis",
        "examples": [
            "Give me a full report for the last 48 hours",
            "Export analysis from today",
        ],
    },

    # Phase 1.5 - Complete Twitter Coverage
    {
        "name": "search_twitter_tool",
        "platform": "Twitter",
        "phase": "Phase 1.5 - Complete Coverage",
        "description": "Search/scrape Twitter by keyword and save to database",
        "use_cases": ["Find tweets about X", "Search for keyword", "Scrape topic"],
        "parameters": [
            {"name": "keyword", "type": "str", "default": "required", "desc": "Search keyword"},
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range"},
            {"name": "max_results", "type": "int", "default": "100", "desc": "Max tweets to scrape"},
        ],
        "returns": "Summary of scraped tweets with top performers",
        "examples": [
            "Find tweets about AI",
            "Search for 'productivity hacks'",
        ],
    },
    {
        "name": "find_comment_opportunities_tool",
        "platform": "Twitter",
        "phase": "Phase 1.5 - Complete Coverage",
        "description": "Find high-quality comment opportunities for engagement",
        "use_cases": ["Comment opportunities", "Tweets to engage with", "Growth strategy"],
        "parameters": [
            {"name": "hours_back", "type": "int", "default": "48", "desc": "Time range"},
            {"name": "min_green_flags", "type": "int", "default": "3", "desc": "Min quality score"},
            {"name": "max_candidates", "type": "int", "default": "100", "desc": "Max to analyze"},
        ],
        "returns": "Ranked list with scores and comment suggestions",
        "examples": [
            "Find comment opportunities",
            "Show me tweets to comment on",
        ],
    },
    {
        "name": "export_comments_tool",
        "platform": "Twitter",
        "phase": "Phase 1.5 - Complete Coverage",
        "description": "Export comment opportunities to file (JSON/CSV/Markdown)",
        "use_cases": ["Export comments", "Download opportunities", "Save for later"],
        "parameters": [
            {"name": "hours_back", "type": "int", "default": "48", "desc": "Time range"},
            {"name": "format", "type": "str", "default": "json", "desc": "Format (json/csv/markdown)"},
            {"name": "label_filter", "type": "str", "default": "None", "desc": "Filter by label"},
        ],
        "returns": "Exported data with preview",
        "examples": [
            "Export comment opportunities as CSV",
            "Download opportunities from today",
        ],
    },
    {
        "name": "analyze_search_term_tool",
        "platform": "Twitter",
        "phase": "Phase 1.5 - Complete Coverage",
        "description": "Analyze keyword engagement patterns and performance",
        "use_cases": ["Analyze keyword", "Understand topic performance", "Track trends"],
        "parameters": [
            {"name": "keyword", "type": "str", "default": "required", "desc": "Keyword to analyze"},
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range"},
        ],
        "returns": "Engagement statistics and insights for keyword",
        "examples": [
            "Analyze keyword 'AI tools'",
            "How is 'startup' performing?",
        ],
    },
    {
        "name": "generate_content_tool",
        "platform": "Twitter",
        "phase": "Phase 1.5 - Complete Coverage",
        "description": "Generate long-form content from viral hooks (threads/articles)",
        "use_cases": ["Create thread", "Generate article", "Turn hooks into content"],
        "parameters": [
            {"name": "hours_back", "type": "int", "default": "24", "desc": "Time range for hooks"},
            {"name": "content_type", "type": "str", "default": "thread", "desc": "Type (thread/article)"},
            {"name": "limit", "type": "int", "default": "10", "desc": "Max hooks to use"},
        ],
        "returns": "Generated long-form content based on viral patterns",
        "examples": [
            "Create a thread from today's viral hooks",
            "Generate an article about top performers",
        ],
    },

    # Phase 1.6 - TikTok Platform
    {
        "name": "search_tiktok_tool",
        "platform": "TikTok",
        "phase": "Phase 1.6 - TikTok Support",
        "description": "Search viral TikTok videos by keyword",
        "use_cases": ["Find TikTok videos", "Discover TikTok content", "Track trends"],
        "parameters": [
            {"name": "keyword", "type": "str", "default": "required", "desc": "Search keyword"},
            {"name": "count", "type": "int", "default": "50", "desc": "Max videos"},
            {"name": "min_views", "type": "int", "default": "100000", "desc": "Min view count"},
            {"name": "max_days", "type": "int", "default": "10", "desc": "Max age"},
            {"name": "max_followers", "type": "int", "default": "50000", "desc": "Max creator followers"},
        ],
        "returns": "Summary of viral TikTok videos with top performers",
        "examples": [
            "Find TikTok videos about productivity",
            "Search TikTok for 'morning routine'",
        ],
    },
    {
        "name": "search_tiktok_hashtag_tool",
        "platform": "TikTok",
        "phase": "Phase 1.6 - TikTok Support",
        "description": "Search TikTok by hashtag and analyze performance",
        "use_cases": ["Track hashtag", "Monitor hashtag performance", "Find viral hashtags"],
        "parameters": [
            {"name": "hashtag", "type": "str", "default": "required", "desc": "Hashtag to search"},
            {"name": "count", "type": "int", "default": "50", "desc": "Max videos"},
            {"name": "min_views", "type": "int", "default": "100000", "desc": "Min view count"},
            {"name": "max_days", "type": "int", "default": "10", "desc": "Max age"},
            {"name": "max_followers", "type": "int", "default": "50000", "desc": "Max creator followers"},
        ],
        "returns": "Hashtag performance analysis with top videos",
        "examples": [
            "Track #productivity hashtag",
            "Find videos with #entrepreneur",
        ],
    },
    {
        "name": "scrape_tiktok_user_tool",
        "platform": "TikTok",
        "phase": "Phase 1.6 - TikTok Support",
        "description": "Scrape all posts from a TikTok creator/user",
        "use_cases": ["Analyze creator", "Study TikTok account", "Track competitor"],
        "parameters": [
            {"name": "username", "type": "str", "default": "required", "desc": "TikTok username"},
            {"name": "count", "type": "int", "default": "50", "desc": "Max videos to scrape"},
        ],
        "returns": "Account statistics and top performing videos",
        "examples": [
            "Analyze TikTok creator @username",
            "Study @competitor's TikTok",
        ],
    },
    {
        "name": "analyze_tiktok_video_tool",
        "platform": "TikTok",
        "phase": "Phase 1.6 - TikTok Support",
        "description": "Analyze a single TikTok video by URL",
        "use_cases": ["Analyze this TikTok", "Study viral video", "Get video insights"],
        "parameters": [
            {"name": "url", "type": "str", "default": "required", "desc": "TikTok video URL"},
        ],
        "returns": "Detailed video analysis with engagement metrics",
        "examples": [
            "Analyze this TikTok: [URL]",
            "Study this viral video",
        ],
    },
    {
        "name": "analyze_tiktok_batch_tool",
        "platform": "TikTok",
        "phase": "Phase 1.6 - TikTok Support",
        "description": "Batch analyze multiple TikTok videos from URLs",
        "use_cases": ["Analyze multiple TikToks", "Bulk import videos", "Compare videos"],
        "parameters": [
            {"name": "urls", "type": "list[str]", "default": "required", "desc": "List of TikTok URLs"},
        ],
        "returns": "Batch analysis summary with aggregate metrics",
        "examples": [
            "Analyze these TikToks: [URL1, URL2, URL3]",
            "Compare these viral videos",
        ],
    },

    # Phase 1.7 - YouTube & Facebook
    {
        "name": "search_youtube_tool",
        "platform": "YouTube",
        "phase": "Phase 1.7 - Multi-Platform",
        "description": "Search YouTube for viral videos/Shorts by keyword",
        "use_cases": ["Find YouTube videos", "Discover viral Shorts", "Track YouTube trends"],
        "parameters": [
            {"name": "keywords", "type": "str", "default": "required", "desc": "Comma-separated keywords"},
            {"name": "max_shorts", "type": "int", "default": "100", "desc": "Max Shorts to find"},
            {"name": "max_videos", "type": "int", "default": "0", "desc": "Max regular videos"},
            {"name": "days_back", "type": "int", "default": "None", "desc": "Max age in days"},
            {"name": "min_views", "type": "int", "default": "100000", "desc": "Min view count"},
            {"name": "max_subscribers", "type": "int", "default": "50000", "desc": "Max creator subs"},
        ],
        "returns": "Summary of viral YouTube videos with top performers",
        "examples": [
            "Find YouTube Shorts about cooking",
            "Search YouTube for 'productivity tips'",
        ],
    },
    {
        "name": "search_facebook_ads_tool",
        "platform": "Facebook",
        "phase": "Phase 1.7 - Multi-Platform",
        "description": "Search Facebook Ad Library by URL",
        "use_cases": ["Find Facebook ads", "Research competitor ads", "Monitor ad spend"],
        "parameters": [
            {"name": "search_url", "type": "str", "default": "required", "desc": "Ad Library URL"},
            {"name": "count", "type": "int", "default": "50", "desc": "Max ads to fetch"},
            {"name": "period", "type": "str", "default": "last30d", "desc": "Time period"},
        ],
        "returns": "Ad performance summary with spend and reach data",
        "examples": [
            "Find Facebook ads for [topic]",
            "Research competitor ads",
        ],
    },
    {
        "name": "scrape_facebook_page_ads_tool",
        "platform": "Facebook",
        "phase": "Phase 1.7 - Multi-Platform",
        "description": "Scrape all ads from a specific Facebook page",
        "use_cases": ["Analyze page ads", "Study brand campaigns", "Track competitor advertising"],
        "parameters": [
            {"name": "page_url", "type": "str", "default": "required", "desc": "Facebook page URL"},
            {"name": "count", "type": "int", "default": "50", "desc": "Max ads to scrape"},
            {"name": "active_status", "type": "str", "default": "all", "desc": "Filter (all/active/inactive)"},
        ],
        "returns": "Page advertising strategy summary with campaign insights",
        "examples": [
            "Analyze ads from [brand] Facebook page",
            "Study [competitor]'s ad strategy",
        ],
    },
]

# ============================================================================
# Tool Display Function
# ============================================================================

def render_tool(tool):
    """Render a single tool card."""
    with st.expander(f"**{tool['name']}** - {tool['description']}", expanded=False):
        # Platform and Phase
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Platform:** {tool['platform']}")
        with col2:
            st.markdown(f"**Phase:** {tool['phase']}")

        st.divider()

        # Use Cases
        st.markdown("**Use Cases:**")
        for use_case in tool['use_cases']:
            st.markdown(f"- {use_case}")

        st.divider()

        # Parameters
        st.markdown("**Parameters:**")
        for param in tool['parameters']:
            default = f" (default: `{param['default']}`)" if param['default'] != "required" else " (required)"
            st.markdown(f"- `{param['name']}` (`{param['type']}`){default}: {param['desc']}")

        st.divider()

        # Returns
        st.markdown(f"**Returns:** {tool['returns']}")

        st.divider()

        # Example Queries
        st.markdown("**Example Queries:**")
        for example in tool['examples']:
            st.code(example, language=None)

# ============================================================================
# Display Tools by Platform
# ============================================================================

# Filter tools
if platform_filter == "All Platforms":
    filtered_tools = TOOLS
else:
    filtered_tools = [t for t in TOOLS if t['platform'] == platform_filter]

# Group by phase
phases = {}
for tool in filtered_tools:
    phase = tool['phase']
    if phase not in phases:
        phases[phase] = []
    phases[phase].append(tool)

# Display each phase
for phase, tools in sorted(phases.items()):
    st.header(phase)
    st.markdown(f"*{len(tools)} tools*")

    for tool in tools:
        render_tool(tool)

    st.divider()

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"**Total Tools:** {len(filtered_tools)} | Use these tools in the Chat interface to analyze viral content")
