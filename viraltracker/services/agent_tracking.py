"""
PydanticAI agent usage tracking wrapper.

Provides a centralized way to run PydanticAI agents while
automatically tracking token usage to the billing system.
"""

import logging
from typing import Optional, Any, TypeVar

from pydantic_ai import Agent
from pydantic_ai.result import RunResult

from .usage_tracker import UsageTracker, UsageRecord

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def run_agent_with_tracking(
    agent: Agent[Any, T],
    prompt: str,
    *,
    tracker: Optional[UsageTracker] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    tool_name: str = "pydantic_agent",
    operation: str = "run",
    **run_kwargs
) -> RunResult[T]:
    """
    Run a PydanticAI agent and track usage.

    Args:
        agent: The PydanticAI Agent to run
        prompt: The prompt to send
        tracker: UsageTracker instance (if None, tracking is skipped)
        user_id: User ID for billing
        organization_id: Organization ID for billing
        tool_name: Name of the tool/service for reporting
        operation: Specific operation name
        **run_kwargs: Additional args passed to agent.run()

    Returns:
        The agent run result (same as agent.run())
    """
    # Run the agent
    result = await agent.run(prompt, **run_kwargs)

    # Track usage (fire-and-forget)
    if tracker and organization_id and organization_id != "all":
        try:
            _track_agent_usage(
                result=result,
                agent=agent,
                tracker=tracker,
                user_id=user_id,
                organization_id=organization_id,
                tool_name=tool_name,
                operation=operation,
            )
        except Exception as e:
            logger.warning(f"Agent usage tracking failed (non-fatal): {e}")

    return result


def run_agent_sync_with_tracking(
    agent: Agent[Any, T],
    prompt: str,
    *,
    tracker: Optional[UsageTracker] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    tool_name: str = "pydantic_agent",
    operation: str = "run",
    **run_kwargs
) -> RunResult[T]:
    """
    Synchronous version of run_agent_with_tracking.

    Args:
        agent: The PydanticAI Agent to run
        prompt: The prompt to send
        tracker: UsageTracker instance (if None, tracking is skipped)
        user_id: User ID for billing
        organization_id: Organization ID for billing
        tool_name: Name of the tool/service for reporting
        operation: Specific operation name
        **run_kwargs: Additional args passed to agent.run_sync()

    Returns:
        The agent run result (same as agent.run_sync())
    """
    result = agent.run_sync(prompt, **run_kwargs)

    if tracker and organization_id and organization_id != "all":
        try:
            _track_agent_usage(
                result=result,
                agent=agent,
                tracker=tracker,
                user_id=user_id,
                organization_id=organization_id,
                tool_name=tool_name,
                operation=operation,
            )
        except Exception as e:
            logger.warning(f"Agent usage tracking failed (non-fatal): {e}")

    return result


def _track_agent_usage(
    result: RunResult,
    agent: Agent,
    tracker: UsageTracker,
    user_id: Optional[str],
    organization_id: str,
    tool_name: str,
    operation: str,
) -> None:
    """Extract usage from result and track it."""
    usage = result.usage()

    # Determine provider from model name
    model_name = str(agent.model) if agent.model else "unknown"
    provider = _get_provider_from_model(model_name)

    # PydanticAI Usage object has: request_tokens, response_tokens, total_tokens
    record = UsageRecord(
        provider=provider,
        model=model_name,
        tool_name=tool_name,
        operation=operation,
        input_tokens=usage.request_tokens or 0,
        output_tokens=usage.response_tokens or 0,
    )

    tracker.track(user_id, organization_id, record)
    logger.debug(f"Tracked {tool_name}/{operation}: {usage.request_tokens}+{usage.response_tokens} tokens")


def _get_provider_from_model(model_name: str) -> str:
    """Determine provider from model name."""
    model_lower = model_name.lower()
    if "claude" in model_lower or "anthropic" in model_lower:
        return "anthropic"
    elif "gpt" in model_lower or "openai" in model_lower:
        return "openai"
    elif "gemini" in model_lower or "google" in model_lower:
        return "google"
    return "unknown"
