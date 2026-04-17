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
# Session State (replaces old context builders)
# ==========================================================================

_UUID_RE = None  # lazy-compiled regex


def _is_uuid(val: str) -> bool:
    """Check if a string looks like a UUID."""
    global _UUID_RE
    if _UUID_RE is None:
        import re
        _UUID_RE = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
        )
    return bool(_UUID_RE.match(str(val)))


def _parse_product_resolution(state: dict, result_preview: str):
    """Extract product info from resolve_product_name result preview."""
    import json
    try:
        data = json.loads(result_preview)
        if data.get("success") and data.get("products"):
            first = data["products"][0]
            state["product_id"] = first.get("id")
            state["product_name"] = first.get("name")
            if first.get("brand_id"):
                state["brand_id"] = first["brand_id"]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass


def _extract_names_from_response(state: dict, response_text: str):
    """Regex fallback to extract entity names from response text."""
    import re

    # Brand ID
    brand_match = re.search(
        r'brand[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?',
        response_text, re.I
    )
    if brand_match:
        state["brand_id"] = brand_match.group(1)

    # Brand name from **Bold** patterns
    brand_name_match = re.search(r'(?:for|brand[:\s]*)\s*\*\*([^*]+)\*\*', response_text, re.I)
    if brand_name_match:
        name = brand_name_match.group(1).strip()
        if len(name) < 50:
            state["brand_name"] = name

    # Product ID
    product_match = re.search(
        r'product[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?',
        response_text, re.I
    )
    if product_match:
        state["product_id"] = product_match.group(1)

    # Competitor ID
    comp_match = re.search(
        r'competitor[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?',
        response_text, re.I
    )
    if comp_match:
        state["competitor_id"] = comp_match.group(1)

    # Persona ID
    persona_match = re.search(
        r'persona[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?',
        response_text, re.I
    )
    if persona_match:
        state["persona_id"] = persona_match.group(1)


def update_session_state(state: dict, tool_log: list, response_text: str):
    """Update session state from structured tool data + response text.

    Primary source: tool args/results (structured, reliable).
    Fallback: regex on response text for names not in tool args.
    """
    for record in tool_log:
        # Track which agent handled the request
        if record.tool_name.startswith("route_to_"):
            state["last_agent"] = record.tool_name.replace("route_to_", "").replace("_agent", "")

        # Extract entity IDs from tool args (structured, reliable)
        args = record.args
        for key in ("brand_id", "product_id", "competitor_id", "persona_id", "project_id"):
            if key in args and _is_uuid(args[key]):
                state[key] = args[key]

        # Extract from resolve_product_name results
        if record.tool_name == "resolve_product_name" and record.result_preview:
            _parse_product_resolution(state, record.result_preview)

    # Regex fallback on response text for names and IDs not in tool args
    _extract_names_from_response(state, response_text)


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

        # Initialize session state in result_cache so @orchestrator.instructions can read it
        deps.result_cache.custom["session_state"] = {}

        cl.user_session.set("deps", deps)
        cl.user_session.set("message_history", [])

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
    """Handle incoming user messages with streaming orchestrator execution.

    Context is managed by PydanticAI's built-in mechanisms:
    - message_history: full conversation (trimmed by history_processors)
    - @orchestrator.instructions: dynamic session state injected each turn
    - tool_log: structured tool call capture for session state updates
    """
    deps = cl.user_session.get("deps")
    if not deps:
        await cl.Message(
            content="Session not initialized. Please refresh the page."
        ).send()
        return

    message_history = cl.user_session.get("message_history") or []

    # Clear stale side-channel result before running
    deps.result_cache.custom.pop("ad_intelligence_result", None)

    try:
        final_text, updated_history, tool_log = await stream_agent_run(
            orchestrator=orchestrator,
            user_prompt=message.content,  # Clean user message — no context wrappers
            deps=deps,
            message_history=message_history,
        )

        # Handle ad intelligence side-channel (rendered markdown bypass)
        ad_intel = deps.result_cache.custom.get("ad_intelligence_result")
        if ad_intel and ad_intel.get("rendered_markdown"):
            display_content = ad_intel["rendered_markdown"]
            await cl.Message(content=display_content).send()
        else:
            display_content = final_text

        # Store message history for conversation continuity
        cl.user_session.set("message_history", updated_history)

        # Update session state from structured tool data
        state = deps.result_cache.custom.setdefault("session_state", {})
        update_session_state(state, tool_log, display_content)

    except Exception as e:
        logger.error(f"Agent run failed: {e}\n{traceback.format_exc()}")
        error_str = str(e)
        if ":" in error_str and len(error_str) > 200:
            error_str = error_str.split("\n")[0]
        await cl.Message(
            content=f"**Error:** {error_str}\n\nTry rephrasing your question or check the logs for details."
        ).send()
