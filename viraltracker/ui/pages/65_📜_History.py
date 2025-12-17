"""
Conversation History - View and export your chat history.

This page provides:
- Current session conversation display
- Message-by-message breakdown
- Export full conversation as JSON/Markdown
- Statistics on your chat session

Note: History is session-based. To persist conversations long-term,
use the Database Browser to access stored data.
"""

import streamlit as st
import json
from datetime import datetime
from typing import List, Dict, Any

# Page config
st.set_page_config(
    page_title="History",
    page_icon="📜",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

st.title("📜 Conversation History")
st.markdown("**View and export your current chat session**")

# ============================================================================
# Helper Functions
# ============================================================================

def export_conversation_json(messages: List[Dict[str, Any]]) -> str:
    """Export conversation as pretty-printed JSON"""
    return json.dumps({
        "exported_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages
    }, indent=2)


def export_conversation_markdown(messages: List[Dict[str, Any]]) -> str:
    """Export conversation as Markdown"""
    md_lines = [
        "# Viraltracker Conversation",
        f"\nExported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\nMessages: {len(messages)}",
        "\n---\n"
    ]

    for idx, msg in enumerate(messages, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            md_lines.append(f"\n## Message {idx}: User\n")
            md_lines.append(f"{content}\n")
        elif role == "assistant":
            md_lines.append(f"\n## Message {idx}: Assistant\n")
            md_lines.append(f"{content}\n")

            # Add structured data if present
            if "structured_data" in msg:
                md_lines.append("\n**Structured Data:**\n")
                md_lines.append(f"```json\n{json.dumps(msg['structured_data'], indent=2)}\n```\n")

        md_lines.append("\n---\n")

    return "".join(md_lines)


def get_message_summary(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Get summary statistics for messages"""
    user_msgs = sum(1 for m in messages if m.get("role") == "user")
    assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
    structured_results = sum(1 for m in messages if "structured_data" in m)

    return {
        "total": len(messages),
        "user": user_msgs,
        "assistant": assistant_msgs,
        "structured_results": structured_results
    }


# ============================================================================
# Get Messages from Session State
# ============================================================================

if "messages" not in st.session_state or len(st.session_state.messages) == 0:
    st.info("No conversation history yet. Start chatting on the main page!")
    st.markdown("👈 Click **Chat** in the sidebar to begin")
    st.stop()

messages = st.session_state.messages

# ============================================================================
# Statistics Section
# ============================================================================

st.subheader("Session Statistics")

summary = get_message_summary(messages)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Messages", summary["total"])
with col2:
    st.metric("Your Messages", summary["user"])
with col3:
    st.metric("Agent Responses", summary["assistant"])
with col4:
    st.metric("Structured Results", summary["structured_results"])

st.divider()

# ============================================================================
# Export Section
# ============================================================================

st.subheader("Export Conversation")

col1, col2 = st.columns(2)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

with col1:
    # JSON Export
    json_data = export_conversation_json(messages)
    st.download_button(
        label="📥 Download as JSON",
        data=json_data,
        file_name=f"conversation_{timestamp}.json",
        mime="application/json",
        use_container_width=True
    )

with col2:
    # Markdown Export
    md_data = export_conversation_markdown(messages)
    st.download_button(
        label="📄 Download as Markdown",
        data=md_data,
        file_name=f"conversation_{timestamp}.md",
        mime="text/markdown",
        use_container_width=True
    )

st.divider()

# ============================================================================
# Message Display
# ============================================================================

st.subheader("Conversation Thread")

for idx, message in enumerate(messages, 1):
    role = message.get("role", "unknown")
    content = message.get("content", "")

    # Create expander for each message
    if role == "user":
        label = f"💬 Message {idx}: You"
        icon = "🙋"
    elif role == "assistant":
        label = f"🤖 Message {idx}: Agent"
        icon = "🤖"
    else:
        label = f"📝 Message {idx}: {role.title()}"
        icon = "📝"

    with st.expander(label, expanded=(idx == len(messages))):  # Auto-expand latest message
        # Display message content
        if role == "user":
            st.markdown(f"**Query:**\n\n{content}")
        else:
            st.markdown(content)

        # Show structured data if present
        if "structured_data" in message:
            st.divider()
            st.markdown("**Structured Data:**")
            st.json(message["structured_data"])

        # Show metadata
        st.divider()
        st.caption(f"Message ID: {idx} | Role: {role}")

# ============================================================================
# Clear History Button
# ============================================================================

st.divider()

if st.button("🗑️ Clear History", use_container_width=True, type="secondary"):
    st.warning("Are you sure? This will delete your current conversation.")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ Yes, Clear History", key="confirm_clear", use_container_width=True):
            st.session_state.messages = []
            st.success("Conversation history cleared!")
            st.rerun()

    with col2:
        if st.button("❌ Cancel", key="cancel_clear", use_container_width=True):
            st.info("Clear cancelled")

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption(f"**Session Messages:** {len(messages)} | History is temporary - export to save permanently")
