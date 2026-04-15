"""
Chainlit Agent Chat - Main entrypoint.

Standalone Chainlit app that connects to the existing ViralTracker orchestrator
(8 agents, 54 tools) with streaming text, extended thinking, and tool step
visualization.

Setup:
    1. Add CHAINLIT_AUTH_SECRET to your .env file:
       CHAINLIT_AUTH_SECRET=<any random secret string>
       (generate with: python -c "import secrets; print(secrets.token_hex(32))")

    2. Run from the project root:
       chainlit run viraltracker/chainlit_app/app.py -w
"""

import asyncio
import logging
import os
import traceback
from datetime import datetime
from typing import Optional

import chainlit as cl

# Initialize Logfire early, before viraltracker imports
from viraltracker.core.observability import setup_logfire

setup_logfire()

# Import orchestrator and dependencies (safe at module level - only reads env vars)
from viraltracker.agent.orchestrator import orchestrator
from viraltracker.agent.dependencies import AgentDependencies

from viraltracker.chainlit_app.auth import authenticate
from viraltracker.chainlit_app.notifications import start_job_notification_poller
from viraltracker.chainlit_app.streaming import stream_agent_run

logger = logging.getLogger(__name__)

# Increase socket.io ping_timeout so the client tolerates longer gaps between pings.
# Default is 20s; agent tool calls can block the event loop for 30s+.
# The server communicates this to the client during the initial handshake.
try:
    from chainlit.server import sio
    sio.eio.ping_timeout = 120
except Exception:
    pass


# ==========================================================================
# Conversation Context (ported from 00_Agent_Chat.py)
# ==========================================================================


def build_conversation_context(tool_results: list) -> str:
    """
    Build context string from recent tool results.

    Ported from viraltracker/ui/pages/00_Agent_Chat.py:254-283.
    Enables follow-up queries like "analyze those tweets' hooks".
    """
    if not tool_results:
        return ""

    recent_results = tool_results[-3:]
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


# ==========================================================================
# Authentication
# ==========================================================================


@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Delegate to Supabase auth adapter."""
    return await authenticate(username, password)


# ==========================================================================
# Session Initialization
# ==========================================================================


@cl.on_chat_start
async def on_chat_start():
    """Initialize session: create AgentDependencies and send welcome message."""
    user = cl.user_session.get("user")
    user_id = user.metadata.get("user_id") if user else None
    org_id = user.metadata.get("org_id") if user else None

    # Create AgentDependencies (initializes 27 services)
    try:
        project_name = os.getenv("PROJECT_NAME", "yakety-pack-instagram")
        deps = AgentDependencies.create(
            project_name=project_name,
            user_id=user_id,
            organization_id=org_id,
        )
        # Register Chainlit event handler factory for sub-agent streaming
        from viraltracker.chainlit_app.streaming import make_chainlit_event_handler
        deps.result_cache.custom["_make_event_handler"] = make_chainlit_event_handler

        cl.user_session.set("deps", deps)
        cl.user_session.set("message_history", [])
        cl.user_session.set("tool_results", [])

        # Start background job notification poller
        poller_task = asyncio.create_task(start_job_notification_poller(org_id))
        cl.user_session.set("_notification_poller", poller_task)

        logger.info(f"Chainlit session initialized for {user.identifier if user else 'unknown'}")

    except Exception as e:
        logger.error(f"Failed to initialize session: {e}")
        await cl.Message(
            content=(
                "**Failed to initialize services.** Please check that the following "
                "environment variables are set:\n"
                "- `SUPABASE_URL`\n"
                "- `SUPABASE_SERVICE_KEY`\n"
                "- `GEMINI_API_KEY`\n"
                "- `OPENAI_API_KEY`\n\n"
                f"Error: `{e}`"
            )
        ).send()
        return

    display_name = user.identifier if user else "there"
    await cl.Message(
        content=f"Welcome, **{display_name}**! I'm the ViralTracker Agent. "
        "Ask me about viral tweets, hooks, ad creation, competitor research, and more."
    ).send()


# ==========================================================================
# Message Handler
# ==========================================================================


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages with streaming orchestrator execution."""
    deps = cl.user_session.get("deps")
    if not deps:
        await cl.Message(
            content="Session not initialized. Please refresh the page."
        ).send()
        return

    message_history = cl.user_session.get("message_history") or []
    tool_results = cl.user_session.get("tool_results") or []

    # Build conversation context from recent tool results
    context = build_conversation_context(tool_results)
    full_prompt = f"{context}## Current Query:\n{message.content}" if context else message.content

    # Clear stale side-channel result before running
    deps.result_cache.custom.pop("ad_intelligence_result", None)

    try:
        final_text, updated_history = await stream_agent_run(
            orchestrator=orchestrator,
            user_prompt=full_prompt,
            deps=deps,
            message_history=message_history,
        )

        # Handle ad intelligence side-channel (same pattern as 00_Agent_Chat.py:465-471)
        ad_intel = deps.result_cache.custom.get("ad_intelligence_result")
        if ad_intel and ad_intel.get("rendered_markdown"):
            display_content = ad_intel["rendered_markdown"]
            # Send the side-channel markdown as a separate message
            await cl.Message(content=display_content).send()
        else:
            display_content = final_text

        # Store message history for conversation continuity
        cl.user_session.set("message_history", updated_history)

        # Store tool result for context building
        tool_results.append({
            "timestamp": datetime.now().isoformat(),
            "user_query": message.content,
            "agent_response": display_content,
        })
        # Keep only last 10 results
        cl.user_session.set("tool_results", tool_results[-10:])

    except Exception as e:
        logger.error(f"Agent run failed: {e}\n{traceback.format_exc()}")
        await cl.Message(
            content=(
                f"**Error:** {e}\n\n"
                "**Possible causes:**\n"
                "- Invalid API keys\n"
                "- Network connectivity issues\n"
                "- Database connection problems\n\n"
                "Try rephrasing your question or check the logs for details."
            )
        ).send()
