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


def _extract_ids(text: str) -> dict:
    """Extract UUIDs and key identifiers from response text for follow-up context."""
    import re
    ids = {}

    # Extract UUIDs with their labels
    uuid_pattern = r'(?:ID|id|Id)[:\s]*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?'
    uuid_matches = re.findall(uuid_pattern, text, re.I)
    if uuid_matches:
        ids["referenced_ids"] = list(dict.fromkeys(uuid_matches))[:10]  # Dedup, keep order

    # Extract persona IDs specifically
    persona_match = re.search(r'persona[_\s]*(?:id|ID)?[:\s]*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?', text, re.I)
    if persona_match:
        ids["persona_id"] = persona_match.group(1)

    # Extract project IDs
    project_match = re.search(r'project[_\s]*(?:id|ID)?[:\s]*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?', text, re.I)
    if project_match:
        ids["project_id"] = project_match.group(1)

    # Extract ad IDs
    ad_match = re.search(r'ad[_\s]*(?:id|ID)?[:\s]*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?', text, re.I)
    if ad_match:
        ids["ad_id"] = ad_match.group(1)

    # Extract competitor IDs
    comp_match = re.search(r'competitor[_\s]*(?:id|ID)?[:\s]*`?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`?', text, re.I)
    if comp_match:
        ids["competitor_id"] = comp_match.group(1)

    return ids


def build_conversation_context(tool_results: list) -> str:
    """
    Build context string from recent tool results.

    Provides the orchestrator with recent query results and extracted IDs
    so users can make follow-up queries like "analyze those", "edit that ad",
    "export that persona as a copy brief", etc.
    """
    if not tool_results:
        return ""

    recent_results = tool_results[-5:]
    if not recent_results:
        return ""

    context = "## Recent Context:\n\n"
    context += "You have access to the results of these recent queries:\n\n"

    # Collect all referenced IDs across results for quick access
    all_ids = {}

    for i, result in enumerate(recent_results, 1):
        context += f"{i}. **User asked:** \"{result['user_query']}\"\n"
        response_preview = result["agent_response"][:1500]
        if len(result["agent_response"]) > 1500:
            response_preview += "..."
        context += f"   **Result:** {response_preview}\n\n"

        # Merge extracted IDs
        result_ids = result.get("extracted_ids", {})
        for key, val in result_ids.items():
            if key == "referenced_ids":
                all_ids.setdefault("referenced_ids", []).extend(val)
            else:
                all_ids[key] = val  # Later results override earlier

    # Add extracted IDs section for easy follow-up
    if all_ids:
        context += "**Extracted IDs from recent results:**\n"
        for key, val in all_ids.items():
            if key == "referenced_ids":
                continue  # Too noisy
            context += f"- {key}: `{val}`\n"
        context += "\n"

    context += (
        '**IMPORTANT:** When the user refers to "those", "that", "them", "these", '
        '"it", etc., they are referring to items from the results above.\n'
        "- Use the extracted IDs above when the user wants to act on previous results\n"
        "- Reuse the same tool parameters (search terms, filters, etc.) when the user "
        "wants to re-analyze the same data\n"
        "- If the user says 'edit that ad', 'export that persona', 'check that project', etc. "
        "— look up the relevant ID from the context above\n\n"
        "---\n\n"
    )
    return context


def _build_active_context_prefix(active_ctx: dict) -> str:
    """Build a prompt prefix from active session context."""
    if not active_ctx:
        return ""
    parts = []
    if active_ctx.get("brand_name"):
        parts.append(f"Brand: **{active_ctx['brand_name']}** (ID: {active_ctx.get('brand_id', 'unknown')})")
    if active_ctx.get("product_name"):
        parts.append(f"Product: **{active_ctx['product_name']}** (ID: {active_ctx.get('product_id', 'unknown')})")
    if not parts:
        return ""
    return "## Active Context:\n" + "\n".join(parts) + "\n\n"


def _update_active_context(user_query: str, response: str, ctx: dict):
    """Extract brand/product references from the conversation and persist them.

    Looks for common patterns in the response text:
    - Brand IDs and names from tool results
    - Product IDs and names from tool results
    """
    import re

    # Look for brand references in the response
    # Pattern: **Brand Name** or "Brand: Name" or brand_id UUID after brand resolution
    brand_match = re.search(r'brand[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?', response, re.I)
    if brand_match:
        ctx["brand_id"] = brand_match.group(1)

    # Try to extract brand name from common patterns
    brand_name_match = re.search(r'(?:for|brand[:\s]*)\s*\*\*([^*]+)\*\*', response, re.I)
    if brand_name_match:
        name = brand_name_match.group(1).strip()
        if len(name) < 50:  # Sanity check
            ctx["brand_name"] = name

    # Look for product references
    product_match = re.search(r'product[_\s]*(?:id|ID)?[:\s]*[`"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`"]?', response, re.I)
    if product_match:
        ctx["product_id"] = product_match.group(1)

    product_name_match = re.search(r'(?:product|for)\s*\*\*([^*]+)\*\*', response, re.I)
    if product_name_match:
        name = product_name_match.group(1).strip()
        if len(name) < 50:
            ctx["product_name"] = name


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
        cl.user_session.set("active_context", {})  # {brand_id, brand_name, product_id, product_name}

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
    active_ctx = cl.user_session.get("active_context") or {}

    # Build conversation context from recent tool results + active context
    context = build_conversation_context(tool_results)
    active_prefix = _build_active_context_prefix(active_ctx)
    parts = [p for p in [active_prefix, context] if p]
    if parts:
        full_prompt = "".join(parts) + f"## Current Query:\n{message.content}"
    else:
        full_prompt = message.content

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

        # Extract and persist active brand/product context
        _update_active_context(message.content, display_content, active_ctx)
        cl.user_session.set("active_context", active_ctx)

        # Store tool result for context building (with extracted IDs)
        tool_results.append({
            "timestamp": datetime.now().isoformat(),
            "user_query": message.content,
            "agent_response": display_content,
            "extracted_ids": _extract_ids(display_content),
        })
        # Keep only last 10 results
        cl.user_session.set("tool_results", tool_results[-10:])

    except Exception as e:
        logger.error(f"Agent run failed: {e}\n{traceback.format_exc()}")
        error_str = str(e)
        # Extract the root cause from common wrapper patterns
        if ":" in error_str and len(error_str) > 200:
            # Long errors — show first line only
            error_str = error_str.split("\n")[0]
        await cl.Message(
            content=f"**Error:** {error_str}\n\nTry rephrasing your question or check the logs for details."
        ).send()
