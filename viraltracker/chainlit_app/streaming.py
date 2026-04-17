"""
Streaming + Step visualization for the Chainlit agent chat.

Encapsulates the orchestrator.iter() -> Chainlit rendering loop.
Handles text streaming, thinking blocks, and tool call Steps.
"""

import json
import logging
import time
from dataclasses import dataclass, field
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


@dataclass
class ToolCallRecord:
    """Structured record of a tool call + result captured during streaming."""
    tool_name: str
    args: dict = field(default_factory=dict)
    result_preview: str = ""  # First 500 chars of result


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


class ChainlitEventHandler:
    """Maps pydantic-ai AgentStreamEvents to Chainlit Steps.

    Compatible with pydantic-ai's event_stream_handler signature:
        async (RunContext, AsyncIterable[AgentStreamEvent]) -> None

    Used to visualize sub-agent execution (e.g. ad_intelligence_agent)
    in real-time within Chainlit, preventing websocket idle/disconnect
    during long-running sub-agent calls.
    """

    def __init__(self, agent_label: str = "Sub-Agent"):
        self.agent_label = agent_label
        self.active_steps: dict[str, cl.Step] = {}
        self.thinking_step: Optional[cl.Step] = None
        self.thinking_text: str = ""

    async def __call__(self, ctx, stream):
        """Called once per node (ModelRequestNode or CallToolsNode).

        CRITICAL: Must fully consume the AsyncIterable stream.
        If the stream is not fully consumed, the agent hangs.
        """
        try:
            async for event in stream:
                if isinstance(event, PartStartEvent):
                    if hasattr(event.part, 'part_kind') and event.part.part_kind == 'thinking':
                        self.thinking_step = cl.Step(name=f"{self.agent_label} Thinking", type="llm")
                        self.thinking_text = ""
                        await self.thinking_step.send()

                elif isinstance(event, PartDeltaEvent):
                    if isinstance(event.delta, ThinkingPartDelta):
                        if event.delta.content_delta and self.thinking_step:
                            self.thinking_text += event.delta.content_delta
                            await self.thinking_step.stream_token(event.delta.content_delta)

                elif isinstance(event, FunctionToolCallEvent):
                    call_id = event.part.tool_call_id or event.part.tool_name
                    step = cl.Step(name=event.part.tool_name, type="tool")
                    step.input = format_tool_args(event.part.args)
                    await step.send()
                    self.active_steps[call_id] = step

                elif isinstance(event, FunctionToolResultEvent):
                    call_id = getattr(event, 'tool_call_id', None)
                    if not call_id:
                        call_id = getattr(event.result, 'tool_call_id', None)
                    step = self.active_steps.get(call_id) if call_id else None
                    if step:
                        result_content = getattr(event.result, 'content', event.result)
                        step.output = truncate_output(str(result_content))
                        await step.update()

                # PartEndEvent, FinalResultEvent, BuiltinTool*Event — ignore gracefully

        except Exception as e:
            # Don't let UI rendering errors kill the sub-agent run
            logger.warning(f"ChainlitEventHandler error: {e}")

        # Finalize any open thinking step at end of this node's stream
        if self.thinking_step:
            try:
                self.thinking_step.output = self.thinking_text or "(complete)"
                await self.thinking_step.update()
            except Exception:
                pass
            self.thinking_step = None
            self.thinking_text = ""


def make_chainlit_event_handler(agent_label: str) -> ChainlitEventHandler:
    """Factory to create a fresh handler per sub-agent invocation."""
    return ChainlitEventHandler(agent_label)


async def stream_agent_run(
    orchestrator: Agent,
    user_prompt: str,
    deps: Any,
    message_history: list,
) -> tuple[str, list, list[ToolCallRecord]]:
    """
    Run the orchestrator with iter() and stream results to Chainlit.

    Handles:
    - Token-by-token text streaming
    - Extended thinking blocks (rendered as cl.Step)
    - Tool call visualization (rendered as cl.Step with args/results)
    - Structured tool call capture for session state updates

    Args:
        orchestrator: The pydantic-ai orchestrator Agent
        user_prompt: The user's message text
        deps: AgentDependencies instance
        message_history: Prior message history for conversation continuity

    Returns:
        Tuple of (final_response_text, updated_message_history, tool_call_log)
    """
    # Create the streaming message placeholder
    msg = cl.Message(content="")
    await msg.send()

    full_text = ""
    thinking_text = ""
    thinking_step: Optional[cl.Step] = None
    routed_agents: list[str] = []  # Track which agents handled the request
    tool_log: list[ToolCallRecord] = []  # Structured tool call records
    pending_calls: dict[str, ToolCallRecord] = {}  # tool_call_id -> record
    start_time = time.time()

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

                            # Track which specialist agent handled the request
                            if tool_name.startswith("route_to_"):
                                agent_label = tool_name.replace("route_to_", "").replace("_agent", "").replace("_", " ").title()
                                if agent_label not in routed_agents:
                                    routed_agents.append(agent_label)

                            # Capture structured tool call for session state
                            try:
                                args_dict = event.part.args_as_dict()
                            except Exception:
                                args_dict = {}
                            record = ToolCallRecord(tool_name=tool_name, args=args_dict)
                            pending_calls[call_id] = record

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
                                result_obj = event.result
                                call_id = getattr(result_obj, 'tool_call_id', None)

                            # Capture result preview for session state
                            result_content = getattr(event.result, 'content', event.result)
                            result_str = str(result_content)
                            if call_id and call_id in pending_calls:
                                pending_calls[call_id].result_preview = result_str[:500]
                                tool_log.append(pending_calls.pop(call_id))

                            step = active_steps.get(call_id) if call_id else None
                            if step:
                                step.output = truncate_output(result_str)
                                await step.update()

            elif Agent.is_end_node(node):
                break

    # Append provenance footer (agent + elapsed time)
    elapsed = time.time() - start_time
    if elapsed < 60:
        time_str = f"{elapsed:.1f}s"
    else:
        time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    if routed_agents:
        agents_str = ", ".join(routed_agents)
        footer = f"\n\n---\n*{agents_str} Agent · {time_str}*"
    else:
        footer = f"\n\n---\n*{time_str}*"

    full_text += footer
    await msg.stream_token(footer)

    # Finalize the streaming message
    await msg.update()

    # Get updated message history
    updated_history = run.result.all_messages() if run.result else message_history

    return full_text, updated_history, tool_log
