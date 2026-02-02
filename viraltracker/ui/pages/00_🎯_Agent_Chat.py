"""
Agent Chat page — ChatGPT-style interface for Viraltracker AI agent.

Extracted from app.py for use as a page under st.navigation().
Keeps require_auth() as defense-in-depth backup.
"""

import asyncio
import base64
import os
import traceback
from datetime import datetime
from typing import Dict, List, Optional

import logging
import pandas as pd
import streamlit as st

from viraltracker.agent import agent, AgentDependencies
from viraltracker.services.models import (
    OutlierResult,
    HookAnalysisResult,
    TweetExportResult,
    AdCreationResult,
)

logger = logging.getLogger(__name__)

# Defense-in-depth: require auth even though nav already gates access
from viraltracker.ui.auth import require_auth

require_auth()


# ============================================================================
# Download Format Converters
# ============================================================================


def result_to_csv(
    result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult,
) -> str:
    """Convert a structured result to CSV format."""
    if isinstance(result, AdCreationResult):
        data = []
        for ad in result.generated_ads:
            data.append(
                {
                    "Variation": ad.prompt_index,
                    "Status": ad.final_status.upper(),
                    "Hook": ad.prompt.hook.adapted_text,
                    "Hook Category": ad.prompt.hook.category,
                    "Claude Status": ad.claude_review.status,
                    "Claude Score": round(ad.claude_review.overall_quality, 2),
                    "Gemini Status": ad.gemini_review.status,
                    "Gemini Score": round(ad.gemini_review.overall_quality, 2),
                    "Storage Path": ad.storage_path,
                    "Created At": ad.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return pd.DataFrame(data).to_csv(index=False)

    elif isinstance(result, OutlierResult):
        data = []
        for outlier in result.outliers:
            t = outlier.tweet
            data.append(
                {
                    "Rank": outlier.rank,
                    "Z-Score": round(outlier.zscore, 2),
                    "Percentile": round(outlier.percentile, 1),
                    "Username": f"@{t.author_username}",
                    "Followers": t.author_followers,
                    "Views": t.view_count,
                    "Likes": t.like_count,
                    "Replies": t.reply_count,
                    "Retweets": t.retweet_count,
                    "Engagement Rate": round(t.engagement_rate * 100, 2),
                    "Created At": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Tweet Text": t.text,
                    "URL": t.url,
                }
            )
        return pd.DataFrame(data).to_csv(index=False)

    elif isinstance(result, HookAnalysisResult):
        data = []
        for analysis in result.analyses:
            data.append(
                {
                    "Tweet ID": analysis.tweet_id,
                    "Hook Type": analysis.hook_type,
                    "Hook Confidence": round(analysis.hook_type_confidence, 2),
                    "Emotional Trigger": analysis.emotional_trigger,
                    "Emotion Confidence": round(
                        analysis.emotional_trigger_confidence, 2
                    ),
                    "Content Pattern": analysis.content_pattern,
                    "Pattern Confidence": round(
                        analysis.content_pattern_confidence, 2
                    ),
                    "Word Count": analysis.word_count,
                    "Has Emoji": analysis.has_emoji,
                    "Has Hashtags": analysis.has_hashtags,
                    "Has Question": analysis.has_question_mark,
                    "Explanation": analysis.hook_explanation,
                    "Adaptation Notes": analysis.adaptation_notes,
                    "Tweet Text": analysis.tweet_text,
                }
            )
        return pd.DataFrame(data).to_csv(index=False)

    elif isinstance(result, TweetExportResult):
        data = []
        for tweet in result.tweets:
            data.append(
                {
                    "Username": f"@{tweet.author_username}",
                    "Followers": tweet.author_followers,
                    "Views": tweet.view_count,
                    "Likes": tweet.like_count,
                    "Replies": tweet.reply_count,
                    "Retweets": tweet.retweet_count,
                    "Engagement Rate": round(tweet.engagement_rate * 100, 2),
                    "Engagement Score": round(tweet.engagement_score, 2),
                    "Created At": tweet.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Tweet Text": tweet.text,
                    "URL": tweet.url,
                }
            )
        return pd.DataFrame(data).to_csv(index=False)

    return ""


def result_to_json(
    result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult,
) -> str:
    """Convert a structured result to JSON format."""
    return result.model_dump_json(indent=2)


def render_download_buttons(
    result: OutlierResult | HookAnalysisResult | TweetExportResult | AdCreationResult,
    message_index: int,
):
    """Render download buttons for structured results."""
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

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            label="📥 Download JSON",
            data=result_to_json(result),
            file_name=f"{prefix}.json",
            mime="application/json",
            key=f"json_{message_index}",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            label="📊 Download CSV",
            data=result_to_csv(result),
            file_name=f"{prefix}.csv",
            mime="text/csv",
            key=f"csv_{message_index}",
            use_container_width=True,
        )
    with col3:
        st.download_button(
            label="📝 Download Markdown",
            data=result.to_markdown(),
            file_name=f"{prefix}.md",
            mime="text/markdown",
            key=f"md_{message_index}",
            use_container_width=True,
        )


def render_ad_creation_results(result: AdCreationResult, message_index: int):
    """Render ad creation results as rich image cards with status badges."""
    st.subheader(f"🎨 Generated Ads for {result.product.name}")

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

    for i, ad in enumerate(result.generated_ads):
        status_emoji = {"approved": "✅", "rejected": "❌", "flagged": "⚠️"}.get(
            ad.final_status, "❓"
        )
        with st.expander(
            f"{status_emoji} Variation {ad.prompt_index} - {ad.final_status.upper()}",
            expanded=(ad.final_status == "approved"),
        ):
            st.markdown(f"**Hook**: {ad.prompt.hook.adapted_text}")
            st.markdown(f"**Category**: {ad.prompt.hook.category}")
            st.divider()

            col_claude, col_gemini = st.columns(2)
            with col_claude:
                st.markdown("**Claude Review**")
                st.progress(
                    ad.claude_review.overall_quality,
                    text=f"Quality: {ad.claude_review.overall_quality:.2f}",
                )
                st.caption(f"Status: {ad.claude_review.status}")
                if ad.claude_review.product_issues:
                    st.warning(
                        f"Issues: {', '.join(ad.claude_review.product_issues)}"
                    )
            with col_gemini:
                st.markdown("**Gemini Review**")
                st.progress(
                    ad.gemini_review.overall_quality,
                    text=f"Quality: {ad.gemini_review.overall_quality:.2f}",
                )
                st.caption(f"Status: {ad.gemini_review.status}")
                if ad.gemini_review.product_issues:
                    st.warning(
                        f"Issues: {', '.join(ad.gemini_review.product_issues)}"
                    )

            st.divider()
            st.caption(f"Storage: `{ad.storage_path}`")
            st.caption(f"Created: {ad.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            st.info(
                "💡 Image preview and download will be available in future update"
            )


# ============================================================================
# Conversation Context
# ============================================================================


def build_conversation_context() -> str:
    """Build context string from recent tool results."""
    if "tool_results" not in st.session_state or not st.session_state.tool_results:
        return ""

    recent_results = st.session_state.tool_results[-3:]
    if not recent_results:
        return ""

    context = "## Recent Context:\n\n"
    context += "You have access to the results of these recent queries:\n\n"

    for i, result in enumerate(recent_results, 1):
        context += f"{i}. **User asked:** \"{result['user_query']}\"\n"
        response_preview = result["agent_response"][:800]
        if len(result["agent_response"]) > 800:
            response_preview += "..."
        context += f"   **Result:** {response_preview}\n\n"

    context += (
        '**IMPORTANT:** When the user refers to "those tweets", "their hooks", '
        '"them", "these", etc., they are referring to the tweets/results shown above. '
        "To analyze the SAME tweets:\n"
        "- Extract usernames (e.g., @username) from the context above\n"
        "- OR use the SAME tool parameters (hours_back, limit, etc.) to retrieve the same data\n"
        "- For hook analysis: if the user says 'analyze their hooks' or 'analyze those hooks', "
        "use analyze_hooks_tool with the SAME time range from the previous find_outliers call\n\n"
        "---\n\n"
    )
    return context


def store_tool_result(user_query: str, agent_response: str):
    """Store a tool execution result for future context."""
    if "tool_results" not in st.session_state:
        st.session_state.tool_results = []
    st.session_state.tool_results.append(
        {
            "timestamp": datetime.now().isoformat(),
            "user_query": user_query,
            "agent_response": agent_response,
            "message_count": len(st.session_state.messages),
        }
    )
    st.session_state.tool_results = st.session_state.tool_results[-10:]


# ============================================================================
# Session State
# ============================================================================


def initialize_session_state():
    """Initialize session state variables on first load."""
    if "deps" not in st.session_state:
        try:
            db_path = os.getenv("DB_PATH", "viraltracker.db")
            project_name = os.getenv("PROJECT_NAME", "yakety-pack-instagram")
            st.session_state.deps = AgentDependencies.create(
                project_name=project_name
            )
            st.session_state.db_path = db_path
            st.session_state.project_name = project_name
            st.session_state.initialization_error = None
        except Exception as e:
            st.session_state.initialization_error = str(e)
            st.session_state.deps = None

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "tool_results" not in st.session_state:
        st.session_state.tool_results = []
    if "structured_results" not in st.session_state:
        st.session_state.structured_results = {}



# ============================================================================
# Sidebar
# ============================================================================


def render_sidebar():
    """Render sidebar with chat management."""
    with st.sidebar:
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.tool_results = []
            st.rerun()



def _extract_structured_result(result_or_messages):
    """Extract structured result models from agent run result or message list.

    Args:
        result_or_messages: Either an AgentRunResult (with all_messages()),
            or a raw list of ModelMessage objects from streaming.
    """
    if isinstance(result_or_messages, list):
        messages = result_or_messages
    elif hasattr(result_or_messages, "all_messages"):
        messages = result_or_messages.all_messages()
    else:
        return None
    for msg in messages:
        if not hasattr(msg, "parts"):
            continue
        for part in msg.parts:
            if (
                part.__class__.__name__ == "ToolReturnPart"
                and hasattr(part, "content")
                and isinstance(
                    part.content,
                    (
                        OutlierResult,
                        HookAnalysisResult,
                        TweetExportResult,
                        AdCreationResult,
                    ),
                )
            ):
                return part.content
    return None


async def _run_agent_streaming(full_prompt, deps, placeholder):
    """Run the orchestrator agent with streaming text output.

    Streams the LLM's text response token-by-token into the placeholder.
    During tool execution (sub-agent calls), no text streams — the placeholder
    shows the "Thinking..." indicator until the final response begins.

    Args:
        full_prompt: The full prompt with conversation context.
        deps: AgentDependencies instance.
        placeholder: Streamlit empty placeholder for progressive rendering.

    Returns:
        Tuple of (final_output_text, all_messages_list).
    """
    async with agent.run_stream(full_prompt, deps=deps) as stream_result:
        async for text in stream_result.stream_text(
            delta=False, debounce_by=0.1
        ):
            placeholder.markdown(text + "▌")

        final_output = await stream_result.get_output()
        all_messages = stream_result.all_messages()

    return final_output, all_messages


# ============================================================================
# Chat Interface
# ============================================================================


def render_chat_interface():
    """Render main chat interface."""
    st.title("🎯 Viraltracker Agent")
    st.caption("AI-powered viral content analysis assistant")

    if st.session_state.get("initialization_error"):
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
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if (
                message["role"] == "assistant"
                and idx in st.session_state.structured_results
            ):
                result = st.session_state.structured_results[idx]
                st.divider()
                if isinstance(result, AdCreationResult):
                    render_ad_creation_results(result, idx)
                    st.divider()
                    render_download_buttons(result, idx)
                elif isinstance(
                    result,
                    (OutlierResult, HookAnalysisResult, TweetExportResult),
                ):
                    render_download_buttons(result, idx)

    # File uploader
    uploaded_file = st.file_uploader(
        "📎 Upload Reference Ad (Optional - for Facebook ad creation)",
        type=["png", "jpg", "jpeg", "webp"],
        help="Upload a reference ad image to generate similar Facebook ads",
        key="reference_ad_uploader",
    )
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        st.session_state.reference_ad_base64 = base64.b64encode(
            file_bytes
        ).decode("utf-8")
        st.session_state.reference_ad_filename = uploaded_file.name
        st.image(file_bytes, caption=f"📎 {uploaded_file.name}", width=200)
        st.success(f"✅ Reference ad uploaded: {uploaded_file.name}")
    elif "reference_ad_base64" in st.session_state:
        st.info(
            f"📎 Reference ad ready: {st.session_state.reference_ad_filename}"
        )

    # Chat input
    if prompt := st.chat_input(
        "Ask about viral tweets, hooks, ad creation, or request a report..."
    ):
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("*Thinking...*")

            try:
                context = build_conversation_context()
                full_prompt = f"{context}## Current Query:\n{prompt}"

                # Clear stale side-channel result before running
                if st.session_state.deps:
                    st.session_state.deps.result_cache.custom.pop(
                        "ad_intelligence_result", None
                    )

                full_response, all_messages = asyncio.run(
                    _run_agent_streaming(
                        full_prompt,
                        st.session_state.deps,
                        message_placeholder,
                    )
                )

                # Side-channel: replace LLM paraphrase with exact
                # ChatRenderer markdown for ad intelligence results
                ad_intel = st.session_state.deps.result_cache.custom.get(
                    "ad_intelligence_result"
                )
                if ad_intel and ad_intel.get("rendered_markdown"):
                    display_content = ad_intel["rendered_markdown"]
                else:
                    display_content = full_response

                message_placeholder.markdown(display_content)
                st.session_state.messages.append(
                    {"role": "assistant", "content": display_content}
                )

                message_idx = len(st.session_state.messages) - 1
                structured_result = _extract_structured_result(all_messages)
                if structured_result:
                    st.session_state.structured_results[message_idx] = (
                        structured_result
                    )
                    st.divider()
                    if isinstance(structured_result, AdCreationResult):
                        render_ad_creation_results(
                            structured_result, message_idx
                        )
                        st.divider()
                        render_download_buttons(structured_result, message_idx)
                    else:
                        render_download_buttons(structured_result, message_idx)

                store_tool_result(prompt, display_content)

            except Exception as e:
                error_msg = (
                    f"❌ **Error:** {e}\n\n"
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
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_msg}
                )


# ============================================================================
# Footer
# ============================================================================


def render_footer():
    """Render footer with session information."""
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(
            f"📁 Project: **{st.session_state.get('project_name', 'N/A')}**"
        )
    with col2:
        st.caption(
            f"💾 Database: **{st.session_state.get('db_path', 'N/A')}**"
        )
    with col3:
        st.caption(
            f"💬 Messages: **{len(st.session_state.get('messages', []))}**"
        )


# ============================================================================
# Main
# ============================================================================

initialize_session_state()
render_sidebar()
render_chat_interface()
render_footer()
