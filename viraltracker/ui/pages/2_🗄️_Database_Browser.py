"""
Database Browser - Browse and export data from all Supabase tables.

This page provides:
- Table selection for all major database tables
- Filters for project, date range, and engagement metrics
- Interactive dataframe display with sorting/filtering
- CSV/JSON download capabilities
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from viraltracker.core.database import get_supabase_client

# Page config
st.set_page_config(
    page_title="Database Browser",
    page_icon="🗄️",
    layout="wide"
)

st.title("🗄️ Database Browser")
st.markdown("**Browse and export data from all database tables**")

# ============================================================================
# Helper Functions
# ============================================================================

def get_projects() -> List[Dict[str, Any]]:
    """Fetch all projects from database"""
    try:
        supabase = get_supabase_client()
        response = supabase.table("projects").select("id, name, slug").execute()
        return response.data
    except Exception as e:
        st.error(f"Failed to load projects: {e}")
        return []


def query_table(
    table_name: str,
    project_id: Optional[str] = None,
    date_column: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    min_views: Optional[int] = None,
    min_likes: Optional[int] = None,
    limit: int = 1000
) -> pd.DataFrame:
    """
    Query a table with filters

    Args:
        table_name: Name of the table to query
        project_id: Optional project ID filter
        date_column: Column name for date filtering
        start_date: Start date for filtering
        end_date: End date for filtering
        min_views: Minimum views filter
        min_likes: Minimum likes filter
        limit: Maximum rows to return

    Returns:
        DataFrame with query results
    """
    try:
        supabase = get_supabase_client()
        query = supabase.table(table_name).select("*")

        # Apply project filter if table has project_id column
        if project_id and table_name in ["posts", "project_posts", "project_accounts",
                                          "project_facebook_ads", "generated_comments",
                                          "tweet_snapshot", "acceptance_log"]:
            query = query.eq("project_id", project_id)

        # Apply date filters
        if date_column and start_date:
            query = query.gte(date_column, start_date.isoformat())
        if date_column and end_date:
            query = query.lte(date_column, end_date.isoformat())

        # Apply engagement filters
        if min_views is not None and table_name in ["posts", "tweet_snapshot"]:
            query = query.gte("views", min_views)
        if min_likes is not None and table_name in ["posts", "tweet_snapshot"]:
            query = query.gte("likes", min_likes)

        # Limit results
        query = query.limit(limit)

        # Execute query
        response = query.execute()

        if response.data:
            return pd.DataFrame(response.data)
        else:
            return pd.DataFrame()

    except Exception as e:
        st.error(f"Query failed: {e}")
        return pd.DataFrame()


def download_csv(df: pd.DataFrame, filename: str):
    """Generate CSV download button"""
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
        key=f"csv_{filename}"
    )


def download_json(df: pd.DataFrame, filename: str):
    """Generate JSON download button"""
    json_str = df.to_json(orient="records", indent=2, date_format="iso")
    st.download_button(
        label="📥 Download JSON",
        data=json_str,
        file_name=filename,
        mime="application/json",
        key=f"json_{filename}"
    )


# ============================================================================
# Table Definitions
# ============================================================================

TABLES = {
    # Core tables
    "brands": {
        "name": "Brands",
        "description": "Brand management and configuration",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "products": {
        "name": "Products",
        "description": "Product catalog with features and benefits",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "platforms": {
        "name": "Platforms",
        "description": "Social media platforms (Twitter, TikTok, YouTube, Facebook)",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "projects": {
        "name": "Projects",
        "description": "Active projects and campaigns",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },

    # Content tables
    "accounts": {
        "name": "Accounts",
        "description": "Social media accounts across all platforms",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "posts": {
        "name": "Posts",
        "description": "All social media posts (Instagram, TikTok, YouTube, etc.)",
        "date_column": "posted_at",
        "has_project_filter": False,  # Posts don't have direct project_id
        "has_engagement_filters": True,
    },
    "video_analysis": {
        "name": "Video Analysis",
        "description": "AI-generated video analysis with hooks and viral factors",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "product_adaptations": {
        "name": "Product Adaptations",
        "description": "Product-specific adaptations of viral content",
        "date_column": "created_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },

    # Twitter-specific
    "tweet_snapshot": {
        "name": "Tweet Snapshots",
        "description": "Historical tweet data for comment generation",
        "date_column": "tweeted_at",
        "has_project_filter": True,
        "has_engagement_filters": True,
    },
    "generated_comments": {
        "name": "Generated Comments",
        "description": "AI-generated comment suggestions for Twitter",
        "date_column": "created_at",
        "has_project_filter": True,
        "has_engagement_filters": False,
    },
    "author_stats": {
        "name": "Author Stats",
        "description": "Twitter author engagement patterns",
        "date_column": "updated_at",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },
    "acceptance_log": {
        "name": "Acceptance Log",
        "description": "Processed tweets for duplicate detection",
        "date_column": "accepted_at",
        "has_project_filter": True,
        "has_engagement_filters": False,
    },

    # Facebook
    "facebook_ads": {
        "name": "Facebook Ads",
        "description": "Facebook Ad Library data with spend and reach",
        "date_column": "start_date",
        "has_project_filter": False,
        "has_engagement_filters": False,
    },

    # Linking tables
    "project_accounts": {
        "name": "Project Accounts",
        "description": "Links projects to monitored accounts",
        "date_column": "added_at",
        "has_project_filter": True,
        "has_engagement_filters": False,
    },
    "project_posts": {
        "name": "Project Posts",
        "description": "Links projects to posts",
        "date_column": "added_at",
        "has_project_filter": True,
        "has_engagement_filters": False,
    },
    "project_facebook_ads": {
        "name": "Project Facebook Ads",
        "description": "Links projects to Facebook ads",
        "date_column": "created_at",
        "has_project_filter": True,
        "has_engagement_filters": False,
    },
}

# ============================================================================
# UI Components
# ============================================================================

# Table selector
selected_table_key = st.selectbox(
    "Select Table",
    options=list(TABLES.keys()),
    format_func=lambda x: f"{TABLES[x]['name']} - {TABLES[x]['description']}",
    key="table_selector"
)

selected_table = TABLES[selected_table_key]

st.divider()

# Filter section
st.subheader("Filters")

col1, col2, col3 = st.columns(3)

# Project filter
selected_project = None
if selected_table["has_project_filter"]:
    with col1:
        projects = get_projects()
        project_options = [{"name": "All Projects", "id": None}] + projects
        selected_project_obj = st.selectbox(
            "Project",
            options=project_options,
            format_func=lambda x: x["name"],
            key="project_filter"
        )
        selected_project = selected_project_obj["id"] if selected_project_obj["id"] else None

# Date range filter
start_date = None
end_date = None
if selected_table["date_column"]:
    with col2:
        date_range = st.selectbox(
            "Date Range",
            options=["All Time", "Last 24 Hours", "Last 7 Days", "Last 30 Days", "Last 90 Days", "Custom"],
            key="date_range"
        )

        if date_range == "Last 24 Hours":
            start_date = datetime.now() - timedelta(days=1)
        elif date_range == "Last 7 Days":
            start_date = datetime.now() - timedelta(days=7)
        elif date_range == "Last 30 Days":
            start_date = datetime.now() - timedelta(days=30)
        elif date_range == "Last 90 Days":
            start_date = datetime.now() - timedelta(days=90)
        elif date_range == "Custom":
            start_date = st.date_input("Start Date", key="start_date")
            end_date = st.date_input("End Date", key="end_date")
            if isinstance(start_date, datetime):
                start_date = start_date
            if isinstance(end_date, datetime):
                end_date = end_date

# Engagement filters
min_views = None
min_likes = None
if selected_table["has_engagement_filters"]:
    with col3:
        min_views = st.number_input("Min Views", min_value=0, value=0, step=1000, key="min_views")
        if min_views == 0:
            min_views = None

        min_likes = st.number_input("Min Likes", min_value=0, value=0, step=100, key="min_likes")
        if min_likes == 0:
            min_likes = None

# Row limit
row_limit = st.slider("Max Rows", min_value=100, max_value=10000, value=1000, step=100, key="row_limit")

st.divider()

# Query button
if st.button("🔍 Query Table", type="primary", use_container_width=True):
    with st.spinner("Querying database..."):
        df = query_table(
            table_name=selected_table_key,
            project_id=selected_project,
            date_column=selected_table["date_column"],
            start_date=start_date,
            end_date=end_date,
            min_views=min_views,
            min_likes=min_likes,
            limit=row_limit
        )

        # Store in session state
        st.session_state.query_result = df
        st.session_state.table_name = selected_table["name"]

# Display results
if "query_result" in st.session_state and not st.session_state.query_result.empty:
    df = st.session_state.query_result
    table_name = st.session_state.table_name

    st.subheader(f"Results: {table_name}")
    st.markdown(f"**{len(df)} rows** | **{len(df.columns)} columns**")

    # Display dataframe
    st.dataframe(
        df,
        use_container_width=True,
        height=600,
        hide_index=True
    )

    st.divider()

    # Download buttons
    st.subheader("Download Data")
    col1, col2 = st.columns(2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_base = f"{selected_table_key}_{timestamp}"

    with col1:
        download_csv(df, f"{filename_base}.csv")

    with col2:
        download_json(df, f"{filename_base}.json")

    # Summary statistics
    st.divider()
    st.subheader("Summary Statistics")

    # Show numeric column statistics
    numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns
    if len(numeric_cols) > 0:
        st.dataframe(df[numeric_cols].describe(), use_container_width=True)
    else:
        st.info("No numeric columns to summarize")

elif "query_result" in st.session_state and st.session_state.query_result.empty:
    st.warning("No results found. Try adjusting your filters.")

else:
    st.info("Select a table and filters above, then click 'Query Table' to browse data.")

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"**Total Tables:** {len(TABLES)} | Query results are limited to {row_limit} rows for performance")
