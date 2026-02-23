"""
Streaming + Step visualization for the Chainlit agent chat.

Encapsulates the orchestrator.iter() -> Chainlit rendering loop.
Handles text streaming, thinking blocks, and tool call Steps.
"""

import json
import logging
from typing import Any, Optional

import chainlit as cl
from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
)

logger = logging.getLogger(__name__)


def format_tool_args(args: Any) -> str:
    """Pretty-print tool arguments for Step input display."""
    if args is None:
        return ""
    if isinstance(args, dict):
        try:
            return json.dumps(args, indent=2, default=str)
        except (TypeError, ValueError):
            return str(args)
    if isinstance(args, str):
        # Try parsing as JSON for pretty-printing
        try:
            parsed = json.loads(args)
            return json.dumps(parsed, indent=2, default=str)
        except (json.JSONDecodeError, TypeError):
            return args
    return str(args)


def truncate_output(text: str, max_len: int = 2000) -> str:
    """Truncate text to keep Step output readable."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n... (truncated, {len(text)} chars total)"


async def stream_agent_run(
    orchestrator: Agent,
    user_prompt: str,
    deps: Any,
    message_history: list,
) -> tuple[str, list]:
    """
    Run the orchestrator with iter() and stream results to Chainlit.

    Handles:
    - Token-by-token text streaming
    - Extended thinking blocks (rendered as cl.Step)
    - Tool call visualization (rendered as cl.Step with args/results)

    Args:
        orchestrator: The pydantic-ai orchestrator Agent
        user_prompt: The user's message text
        deps: AgentDependencies instance
        message_history: Prior message history for conversation continuity

    Returns:
        Tuple of (final_response_text, updated_message_history)
    """
    # Create the streaming message placeholder
    msg = cl.Message(content="")
    await msg.send()

    full_text = ""
    thinking_text = ""
    thinking_step: Optional[cl.Step] = None

    async with orchestrator.iter(
        user_prompt,
        deps=deps,
        message_history=message_history,
    ) as run:
        async for node in run:
            if Agent.is_user_prompt_node(node):
                # Nothing to render for user prompt setup
                continue

            elif Agent.is_model_request_node(node):
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartStartEvent):
                            # Check if a thinking part is starting
                            if hasattr(event.part, 'part_kind') and event.part.part_kind == 'thinking':
                                thinking_step = cl.Step(
                                    name="Thinking",
                                    type="llm",
                                )
                                thinking_step.input = ""
                                thinking_text = ""
                                await thinking_step.send()

                        elif isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, TextPartDelta):
                                delta = event.delta.content_delta
                                full_text += delta
                                await msg.stream_token(delta)

                            elif isinstance(event.delta, ThinkingPartDelta):
                                if event.delta.content_delta:
                                    thinking_text += event.delta.content_delta
                                    if thinking_step:
                                        await thinking_step.stream_token(
                                            event.delta.content_delta
                                        )

                # Finalize thinking step if we had one
                if thinking_step:
                    thinking_step.output = thinking_text or "(thinking complete)"
                    await thinking_step.update()
                    thinking_step = None
                    thinking_text = ""

            elif Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as handle_stream:
                    # Track active tool steps by tool_call_id
                    active_steps: dict[str, cl.Step] = {}

                    async for event in handle_stream:
                        if isinstance(event, FunctionToolCallEvent):
                            tool_name = event.part.tool_name
                            call_id = event.part.tool_call_id or tool_name

                            step = cl.Step(
                                name=tool_name,
                                type="tool",
                            )
                            step.input = format_tool_args(event.part.args)
                            await step.send()
                            active_steps[call_id] = step

                        elif isinstance(event, FunctionToolResultEvent):
                            call_id = getattr(event, 'tool_call_id', None)
                            if not call_id:
                                # Try to get from result
                                result_obj = event.result
                                call_id = getattr(result_obj, 'tool_call_id', None)

                            step = active_steps.get(call_id) if call_id else None
                            if step:
                                result_content = getattr(event.result, 'content', event.result)
                                step.output = truncate_output(str(result_content))
                                await step.update()

            elif Agent.is_end_node(node):
                break

    # Finalize the streaming message
    await msg.update()

    # Get updated message history
    updated_history = run.result.all_messages() if run.result else message_history

    return full_text, updated_history
