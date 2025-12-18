"""
Streamlit UI - ChatGPT-style web interface for Viraltracker AI agent.

Provides an interactive chat interface for analyzing viral content using
a PydanticAI orchestrator pattern with 1 orchestrator + 5 specialized agents:
- Orchestrator Agent: Routes queries to appropriate specialized agents
- Twitter Agent: 8 Twitter-specific tools (tweets, outliers, hooks, etc.)
- TikTok Agent: 5 TikTok tools (videos, hashtags, analytics)
- YouTube Agent: 1 YouTube tool (video search)
- Facebook Agent: 2 Facebook Ads tools (ad analysis)
- Analysis Agent: 3 advanced analytics tools (cross-platform insights)

Total: 19 underlying tools accessible through intelligent routing.

Run with:
    streamlit run viraltracker/ui/app.py

Environment variables required:
    OPENAI_API_KEY: OpenAI API key for agent
    SUPABASE_URL: Supabase database URL
    SUPABASE_KEY: Supabase API key
    GEMINI_API_KEY: Google Gemini API key for hook analysis
    DB_PATH: (optional) Path to database, defaults to viraltracker.db
    PROJECT_NAME: (optional) Project name, defaults to yakety-pack-instagram
"""

import asyncio
import base64
import json
import os
import traceback
from datetime import datetime
from typing import Dict, List, Optional

import logging
import pandas as pd
import streamlit as st

from viraltracker.agent import agent, AgentDependencies
from viraltracker.services.models import OutlierResult, HookAnalysisResult, TweetExportResult, AdCreationResult
from viraltracker.core.database import get_supabase_client


@st.cache_resource
def init_observability():
    """Initialize Logfire at runtime, once per process (Streamlit-compatible)."""
    import os
    token = os.environ.get("LOGFIRE_TOKEN")
    if not token:
        logging.error("[LOGFIRE] LOGFIRE_TOKEN not set, skipping")  # Use error level for Railway visibility
        return False

    try:
        import logfire

        # Configure logfire
        project = os.environ.get("LOGFIRE_PROJECT_NAME", "viraltracker")
        env = os.environ.get("LOGFIRE_ENVIRONMENT", "production")

        logfire.configure(
            token=token,
            project_name=project,
            service_name="viraltracker",
            environment=env,
            send_to_logfire=True,
            console=False,  # Don't duplicate to console
        )

        # Wire up stdlib logging to logfire
        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                logfire.LogfireLoggingHandler(),
                logging.StreamHandler(),
            ],
            force=True,
        )

        logfire.instrument_pydantic()
        logging.error("[LOGFIRE] Initialized successfully at runtime")  # Use error level for Railway visibility
        return True

    except Exception as e:
        logging.error(f"[LOGFIRE] Failed to configure: {e}")
        return False


# Initialize observability (runs once per process)
init_observability()


# ============================================================================
# Download Format Converters
# ============================================================================

def result_to_csv(result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult) -> str:
    """
    Convert OutlierResult, HookAnalysisResult, TweetExportResult, or AdCreationResult to CSV format.

    Args:
        result: The result model to convert

    Returns:
        CSV string
    """
    if isinstance(result, AdCreationResult):
        # Convert generated ads to DataFrame
        data = []
        for ad in result.generated_ads:
            data.append({
                'Variation': ad.prompt_index,
                'Status': ad.final_status.upper(),
                'Hook': ad.prompt.hook.adapted_text,
                'Hook Category': ad.prompt.hook.category,
                'Claude Status': ad.claude_review.status,
                'Claude Score': round(ad.claude_review.overall_quality, 2),
                'Gemini Status': ad.gemini_review.status,
                'Gemini Score': round(ad.gemini_review.overall_quality, 2),
                'Storage Path': ad.storage_path,
                'Created At': ad.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)
    elif isinstance(result, OutlierResult):
        # Convert outlier tweets to DataFrame
        data = []
        for outlier in result.outliers:
            t = outlier.tweet
            data.append({
                'Rank': outlier.rank,
                'Z-Score': round(outlier.zscore, 2),
                'Percentile': round(outlier.percentile, 1),
                'Username': f"@{t.author_username}",
                'Followers': t.author_followers,
                'Views': t.view_count,
                'Likes': t.like_count,
                'Replies': t.reply_count,
                'Retweets': t.retweet_count,
                'Engagement Rate': round(t.engagement_rate * 100, 2),
                'Created At': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Tweet Text': t.text,
                'URL': t.url
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

    elif isinstance(result, HookAnalysisResult):
        # Convert hook analyses to DataFrame
        data = []
        for analysis in result.analyses:
            data.append({
                'Tweet ID': analysis.tweet_id,
                'Hook Type': analysis.hook_type,
                'Hook Confidence': round(analysis.hook_type_confidence, 2),
                'Emotional Trigger': analysis.emotional_trigger,
                'Emotion Confidence': round(analysis.emotional_trigger_confidence, 2),
                'Content Pattern': analysis.content_pattern,
                'Pattern Confidence': round(analysis.content_pattern_confidence, 2),
                'Word Count': analysis.word_count,
                'Has Emoji': analysis.has_emoji,
                'Has Hashtags': analysis.has_hashtags,
                'Has Question': analysis.has_question_mark,
                'Explanation': analysis.hook_explanation,
                'Adaptation Notes': analysis.adaptation_notes,
                'Tweet Text': analysis.tweet_text
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

    elif isinstance(result, TweetExportResult):
        # Convert exported tweets to DataFrame
        data = []
        for tweet in result.tweets:
            data.append({
                'Username': f"@{tweet.author_username}",
                'Followers': tweet.author_followers,
                'Views': tweet.view_count,
                'Likes': tweet.like_count,
                'Replies': tweet.reply_count,
                'Retweets': tweet.retweet_count,
                'Engagement Rate': round(tweet.engagement_rate * 100, 2),
                'Engagement Score': round(tweet.engagement_score, 2),
                'Created At': tweet.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Tweet Text': tweet.text,
                'URL': tweet.url
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

    return ""


def result_to_json(result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult) -> str:
    """
    Convert OutlierResult, HookAnalysisResult, TweetExportResult, or AdCreationResult to JSON format.

    Args:
        result: The result model to convert

    Returns:
        Pretty-printed JSON string
    """
    return result.model_dump_json(indent=2)


def render_download_buttons(result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult, message_index: int):
    """
    Render download buttons for structured results.

    Args:
        result: The structured result to export
        message_index: Index of the message (for unique keys)
    """
    # Determine filename prefix based on result type
    if isinstance(result, AdCreationResult):
        prefix = f"ad_creation_{result.created_at.strftime('%Y%m%d_%H%M%S')}"
    elif isinstance(result, OutlierResult):
        prefix = f"outliers_{result.generated_at.strftime('%Y%m%d_%H%M%S')}"
    elif isinstance(result, HookAnalysisResult):
        prefix = f"hook_analysis_{result.generated_at.strftime('%Y%m%d_%H%M%S')}"
    elif isinstance(result, TweetExportResult):
        prefix = f"tweets_{result.generated_at.strftime('%Y%m%d_%H%M%S')}"
    else:
        return

    # Create three columns for download buttons
    col1, col2, col3 = st.columns(3)

    with col1:
        # JSON download
        json_data = result_to_json(result)
        st.download_button(
            label="📥 Download JSON",
            data=json_data,
            file_name=f"{prefix}.json",
            mime="application/json",
            key=f"json_{message_index}",
            use_container_width=True
        )

    with col2:
        # CSV download
        csv_data = result_to_csv(result)
        st.download_button(
            label="📊 Download CSV",
            data=csv_data,
            file_name=f"{prefix}.csv",
            mime="text/csv",
            key=f"csv_{message_index}",
            use_container_width=True
        )

    with col3:
        # Markdown download
        md_data = result.to_markdown()
        st.download_button(
            label="📝 Download Markdown",
            data=md_data,
            file_name=f"{prefix}.md",
            mime="text/markdown",
            key=f"md_{message_index}",
            use_container_width=True
        )


def render_ad_creation_results(result: AdCreationResult, message_index: int):
    """
    Render ad creation results as rich image cards with status badges.

    Args:
        result: AdCreationResult with generated ads
        message_index: Index for unique keys
    """
    st.subheader(f"🎨 Generated Ads for {result.product.name}")

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Ads", len(result.generated_ads))
    with col2:
        st.metric("✅ Approved", result.approved_count)
    with col3:
        st.metric("❌ Rejected", result.rejected_count)
    with col4:
        st.metric("⚠️ Flagged", result.flagged_count)

    st.divider()

    # Display each ad as an expandable card
    for i, ad in enumerate(result.generated_ads):
        status_emoji = {
            'approved': '✅',
            'rejected': '❌',
            'flagged': '⚠️'
        }.get(ad.final_status, '❓')

        # Expand approved ads by default
        with st.expander(
            f"{status_emoji} Variation {ad.prompt_index} - {ad.final_status.upper()}",
            expanded=(ad.final_status == 'approved')
        ):
            # Hook information
            st.markdown(f"**Hook**: {ad.prompt.hook.adapted_text}")
            st.markdown(f"**Category**: {ad.prompt.hook.category}")

            st.divider()

            # Review scores in two columns
            col_claude, col_gemini = st.columns(2)

            with col_claude:
                st.markdown("**Claude Review**")
                claude_score = ad.claude_review.overall_quality
                st.progress(claude_score, text=f"Quality: {claude_score:.2f}")
                st.caption(f"Status: {ad.claude_review.status}")
                if ad.claude_review.product_issues:
                    st.warning(f"Issues: {', '.join(ad.claude_review.product_issues)}")

            with col_gemini:
                st.markdown("**Gemini Review**")
                gemini_score = ad.gemini_review.overall_quality
                st.progress(gemini_score, text=f"Quality: {gemini_score:.2f}")
                st.caption(f"Status: {ad.gemini_review.status}")
                if ad.gemini_review.product_issues:
                    st.warning(f"Issues: {', '.join(ad.gemini_review.product_issues)}")

            # Storage info and actions
            st.divider()
            st.caption(f"Storage: `{ad.storage_path}`")
            st.caption(f"Created: {ad.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

            # Note: Image display would require fetching from Supabase Storage
            # This is placeholder for future implementation
            st.info("💡 Image preview and download will be available in future update")


# ============================================================================
# Project Management Helpers
# ============================================================================

@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_available_projects() -> List[Dict[str, str]]:
    """
    Fetch available projects from database.

    Returns:
        List of dicts with 'slug' and 'name' keys, ordered by name

    Note:
        Cached for 5 minutes to reduce database queries.
        Returns empty list if database query fails.
    """
    try:
        client = get_supabase_client()
        result = client.table('projects').select('slug, name').order('name').execute()
        return result.data if hasattr(result, 'data') else []
    except Exception as e:
        logger.error(f"Failed to fetch projects: {e}")
        return []


# ============================================================================
# Conversation Context Helpers
# ============================================================================

def build_conversation_context() -> str:
    """
    Build context string from recent tool results.

    Returns a formatted string with the last 3 interactions to provide
    context for multi-turn conversations.
    """
    if 'tool_results' not in st.session_state or not st.session_state.tool_results:
        return ""

    # Get last 3 results
    recent_results = st.session_state.tool_results[-3:]

    if not recent_results:
        return ""

    context = "## Recent Context:\n\n"
    context += "You have access to the results of these recent queries:\n\n"

    for i, result in enumerate(recent_results, 1):
        context += f"{i}. **User asked:** \"{result['user_query']}\"\n"
        # Show more of the response (up to 800 characters) to include usernames/tweet content
        response_preview = result['agent_response'][:800]
        if len(result['agent_response']) > 800:
            response_preview += "..."
        context += f"   **Result:** {response_preview}\n\n"

    context += "**IMPORTANT:** When the user refers to \"those tweets\", \"their hooks\", \"them\", \"these\", etc., "
    context += "they are referring to the tweets/results shown above. To analyze the SAME tweets:\n"
    context += "- Extract usernames (e.g., @username) from the context above\n"
    context += "- OR use the SAME tool parameters (hours_back, limit, etc.) to retrieve the same data\n"
    context += "- For hook analysis: if the user says 'analyze their hooks' or 'analyze those hooks', "
    context += "use analyze_hooks_tool with the SAME time range from the previous find_outliers call\n\n"
    context += "---\n\n"

    return context


def store_tool_result(user_query: str, agent_response: str):
    """
    Store the result of a tool execution for future context.

    Args:
        user_query: The user's query that triggered this tool call
        agent_response: The agent's response text
    """
    if 'tool_results' not in st.session_state:
        st.session_state.tool_results = []

    # Create result entry
    result_entry = {
        'timestamp': datetime.now().isoformat(),
        'user_query': user_query,
        'agent_response': agent_response,
        'message_count': len(st.session_state.messages)
    }

    # Add to results
    st.session_state.tool_results.append(result_entry)

    # Keep only last 10 results to prevent unbounded growth
    st.session_state.tool_results = st.session_state.tool_results[-10:]


# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="Viraltracker Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Authentication - must be after page config
from viraltracker.ui.auth import require_auth
require_auth()


# ============================================================================
# Session State Initialization
# ============================================================================

def initialize_session_state():
    """Initialize session state variables on first load."""

    # Initialize agent dependencies if not already created
    if 'deps' not in st.session_state:
        try:
            db_path = os.getenv('DB_PATH', 'viraltracker.db')
            project_name = os.getenv('PROJECT_NAME', 'yakety-pack-instagram')

            st.session_state.deps = AgentDependencies.create(
                project_name=project_name
            )
            st.session_state.db_path = db_path
            st.session_state.project_name = project_name
            st.session_state.initialization_error = None

        except Exception as e:
            st.session_state.initialization_error = str(e)
            st.session_state.deps = None

    # Initialize message history if not already created
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    # Initialize tool results storage for conversation context
    if 'tool_results' not in st.session_state:
        st.session_state.tool_results = []

    # Initialize structured results storage for downloads
    if 'structured_results' not in st.session_state:
        st.session_state.structured_results = {}


def update_project_name(new_project_name: str):
    """Update project name and reinitialize dependencies."""
    try:
        db_path = st.session_state.get('db_path', 'viraltracker.db')
        st.session_state.deps = AgentDependencies.create(
            project_name=new_project_name
        )
        st.session_state.project_name = new_project_name
        st.session_state.initialization_error = None
        st.success(f"Switched to project: {new_project_name}")
    except Exception as e:
        st.error(f"Failed to update project: {e}")


# ============================================================================
# Sidebar
# ============================================================================

def render_sidebar():
    """Render sidebar with project settings and quick actions."""

    with st.sidebar:
        st.title("⚙️ Settings")

        # Project configuration
        st.subheader("Project")

        # Fetch available projects
        projects = get_available_projects()

        if not projects:
            st.warning("No projects found. Using default project.")
            current_project = st.session_state.get('project_name', 'yakety-pack-instagram')
        else:
            # Create mapping of display names to slugs
            project_options = {f"{p['name']}": p['slug'] for p in projects}

            # Get current project and find its display name
            current_project_slug = st.session_state.get('project_name', 'yakety-pack-instagram')

            # Find display name for current project
            current_display_name = None
            for display_name, slug in project_options.items():
                if slug == current_project_slug:
                    current_display_name = display_name
                    break

            # If current project not found in database, use first available
            if current_display_name is None and project_options:
                current_display_name = list(project_options.keys())[0]
                current_project_slug = project_options[current_display_name]

            # Render selectbox
            selected_display_name = st.selectbox(
                "Select Project",
                options=list(project_options.keys()),
                index=list(project_options.keys()).index(current_display_name) if current_display_name else 0,
                help="Choose a project to analyze"
            )

            # Get selected project slug
            new_project = project_options[selected_display_name]

            # Update project if changed
            if new_project != current_project_slug:
                update_project_name(new_project)

        st.divider()

        # Quick Actions
        st.subheader("⚡ Quick Actions")

        if st.button("📊 Find Viral Tweets (24h)", use_container_width=True):
            add_quick_action_message("Show me viral tweets from the last 24 hours")

        if st.button("🎣 Analyze Hooks", use_container_width=True):
            add_quick_action_message("Analyze the hooks for viral tweets from today")

        if st.button("📄 Full Report (48h)", use_container_width=True):
            add_quick_action_message("Give me a full report for the last 48 hours with hooks")

        st.divider()

        # Chat management
        st.subheader("💬 Chat")

        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.tool_results = []
            st.rerun()

        st.divider()

        # Footer information
        st.subheader("ℹ️ Info")
        st.caption(f"**Project:** {st.session_state.get('project_name', 'N/A')}")
        st.caption(f"**Database:** {st.session_state.get('db_path', 'N/A')}")
        st.caption(f"**Messages:** {len(st.session_state.get('messages', []))}")


def add_quick_action_message(prompt: str):
    """Add a quick action message to chat and trigger agent response."""
    # Add user message
    st.session_state.messages.append({
        'role': 'user',
        'content': prompt
    })

    # Get agent response
    with st.spinner("Agent is processing..."):
        try:
            # Build context from recent results
            context = build_conversation_context()

            # Prepend context to user prompt
            full_prompt = f"{context}## Current Query:\n{prompt}"

            # Call agent with context
            result = asyncio.run(agent.run(full_prompt, deps=st.session_state.deps))
            response = result.output

            # Add agent response
            st.session_state.messages.append({
                'role': 'assistant',
                'content': response
            })

            # Extract structured results from tool returns in message history
            message_idx = len(st.session_state.messages) - 1
            structured_result = None

            # Look through all messages for ToolReturnPart containing our result models
            if hasattr(result, 'all_messages'):
                for msg in result.all_messages():
                    # Check message parts for ToolReturnPart
                    if hasattr(msg, 'parts'):
                        for part in msg.parts:
                            # ToolReturnPart has a 'content' attribute with the structured result
                            if part.__class__.__name__ == 'ToolReturnPart' and hasattr(part, 'content'):
                                if isinstance(part.content, (OutlierResult, HookAnalysisResult, TweetExportResult, AdCreationResult)):
                                    structured_result = part.content
                                    break
                    if structured_result:
                        break

            # Store if we found a structured result
            if structured_result:
                st.session_state.structured_results[message_idx] = structured_result

            # Store result for future context
            store_tool_result(prompt, response)

        except Exception as e:
            error_msg = f"Error: {str(e)}\n\nPlease check your API keys and try again."
            st.session_state.messages.append({
                'role': 'assistant',
                'content': error_msg
            })

    # Force rerun to display new messages
    st.rerun()


# ============================================================================
# Chat Interface
# ============================================================================

def render_chat_interface():
    """Render main chat interface."""

    st.title("🎯 Viraltracker Agent")
    st.caption("AI-powered viral content analysis assistant")

    # Show initialization error if any
    if st.session_state.get('initialization_error'):
        st.error(
            f"❌ **Initialization Error:** {st.session_state.initialization_error}\n\n"
            "Please check that the following environment variables are set:\n"
            "- `OPENAI_API_KEY`\n"
            "- `SUPABASE_URL`\n"
            "- `SUPABASE_KEY`\n"
            "- `GEMINI_API_KEY`"
        )
        return

    # Display chat messages
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message['role']):
            st.markdown(message['content'])

            # Show download buttons and special displays for structured results
            if message['role'] == 'assistant' and idx in st.session_state.structured_results:
                result = st.session_state.structured_results[idx]
                st.divider()
                if isinstance(result, AdCreationResult):
                    render_ad_creation_results(result, idx)
                    st.divider()
                    render_download_buttons(result, idx)
                elif isinstance(result, (OutlierResult, HookAnalysisResult, TweetExportResult)):
                    render_download_buttons(result, idx)

    # File uploader for ad creation (optional)
    uploaded_file = st.file_uploader(
        "📎 Upload Reference Ad (Optional - for Facebook ad creation)",
        type=['png', 'jpg', 'jpeg', 'webp'],
        help="Upload a reference ad image to generate similar Facebook ads",
        key="reference_ad_uploader"
    )

    # Store uploaded file in session state as base64
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        file_base64 = base64.b64encode(file_bytes).decode('utf-8')

        st.session_state.reference_ad_base64 = file_base64
        st.session_state.reference_ad_filename = uploaded_file.name

        # Show preview
        st.image(file_bytes, caption=f"📎 {uploaded_file.name}", width=200)
        st.success(f"✅ Reference ad uploaded: {uploaded_file.name}")
    elif 'reference_ad_base64' in st.session_state:
        # Show currently uploaded file
        st.info(f"📎 Reference ad ready: {st.session_state.reference_ad_filename}")

    # Chat input
    if prompt := st.chat_input("Ask about viral tweets, hooks, ad creation, or request a report..."):
        # Add user message to chat
        st.session_state.messages.append({
            'role': 'user',
            'content': prompt
        })

        # Display user message
        with st.chat_message('user'):
            st.markdown(prompt)

        # Get agent response with streaming
        with st.chat_message('assistant'):
            message_placeholder = st.empty()
            full_response = ""

            try:
                # Build context from recent results
                context = build_conversation_context()

                # Prepend context to user prompt
                full_prompt = f"{context}## Current Query:\n{prompt}"

                # Get agent response (non-streaming for now - streaming has Streamlit rendering issues)
                with st.spinner("Agent is thinking..."):
                    result = asyncio.run(agent.run(full_prompt, deps=st.session_state.deps))
                    full_response = result.output

                # Display response
                message_placeholder.markdown(full_response)

                # Add to message history
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': full_response
                })

                # Extract structured results from tool returns in message history
                message_idx = len(st.session_state.messages) - 1
                structured_result = None

                # Look through all messages for ToolReturnPart containing our result models
                if hasattr(result, 'all_messages'):
                    for msg in result.all_messages():
                        # Check message parts for ToolReturnPart
                        if hasattr(msg, 'parts'):
                            for part in msg.parts:
                                # ToolReturnPart has a 'content' attribute with the structured result
                                if part.__class__.__name__ == 'ToolReturnPart' and hasattr(part, 'content'):
                                    if isinstance(part.content, (OutlierResult, HookAnalysisResult, TweetExportResult, AdCreationResult)):
                                        structured_result = part.content
                                        break
                        if structured_result:
                            break

                # Store and display if we found a structured result
                if structured_result:
                    st.session_state.structured_results[message_idx] = structured_result
                    st.divider()
                    if isinstance(structured_result, AdCreationResult):
                        render_ad_creation_results(structured_result, message_idx)
                        st.divider()
                        render_download_buttons(structured_result, message_idx)
                    else:
                        render_download_buttons(structured_result, message_idx)

                # Store result for future context
                store_tool_result(prompt, full_response)

            except Exception as e:
                # Handle errors gracefully
                error_msg = (
                    f"❌ **Error:** {str(e)}\n\n"
                    "**Possible causes:**\n"
                    "- Invalid API keys\n"
                    "- Network connectivity issues\n"
                    "- Database connection problems\n\n"
                    "**Troubleshooting:**\n"
                    "- Check your environment variables\n"
                    "- Verify your database is accessible\n"
                    "- Try rephrasing your question\n\n"
                    f"**Debug info:**\n```\n{traceback.format_exc()}\n```"
                )

                st.markdown(error_msg)

                # Add error to message history
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': error_msg
                })


# ============================================================================
# Footer
# ============================================================================

def render_footer():
    """Render footer with session information."""

    st.divider()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.caption(f"📁 Project: **{st.session_state.get('project_name', 'N/A')}**")

    with col2:
        st.caption(f"💾 Database: **{st.session_state.get('db_path', 'N/A')}**")

    with col3:
        message_count = len(st.session_state.get('messages', []))
        st.caption(f"💬 Messages: **{message_count}**")


# ============================================================================
# Main Application
# ============================================================================

def main():
    """Main application entry point."""

    # Initialize session state
    initialize_session_state()

    # Render sidebar
    render_sidebar()

    # Render chat interface
    render_chat_interface()

    # Render footer
    render_footer()


if __name__ == '__main__':
    main()
