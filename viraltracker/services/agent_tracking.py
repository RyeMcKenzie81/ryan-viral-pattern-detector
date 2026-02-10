"""
PydanticAI agent usage tracking wrapper.

Provides a centralized way to run PydanticAI agents while
automatically tracking token usage to the billing system.
"""

from __future__ import annotations

import logging
from typing import Optional, Any, TypeVar

from pydantic_ai import Agent

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
):
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
    # Enforce usage limit before running (fail open)
    if organization_id and organization_id != "all":
        try:
            from .usage_limit_service import UsageLimitService
            from ..core.database import get_supabase_client
            limit_svc = UsageLimitService(get_supabase_client())
            limit_svc.enforce_limit(organization_id, "monthly_cost")
        except ImportError:
            pass
        except Exception as e:
            from .usage_limit_service import UsageLimitExceeded
            if isinstance(e, UsageLimitExceeded):
                raise
            logger.warning(f"Usage limit check failed (non-fatal): {e}")

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
):
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
    # Enforce usage limit before running (fail open)
    if organization_id and organization_id != "all":
        try:
            from .usage_limit_service import UsageLimitService
            from ..core.database import get_supabase_client
            limit_svc = UsageLimitService(get_supabase_client())
            limit_svc.enforce_limit(organization_id, "monthly_cost")
        except ImportError:
            pass
        except Exception as e:
            from .usage_limit_service import UsageLimitExceeded
            if isinstance(e, UsageLimitExceeded):
                raise
            logger.warning(f"Usage limit check failed (non-fatal): {e}")

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


async def run_agent_stream_with_tracking(
    agent: Agent[Any, T],
    prompt: str,
    *,
    tracker: Optional[UsageTracker] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    tool_name: str = "pydantic_agent",
    operation: str = "run",
    **run_kwargs
):
    """
    Run a PydanticAI agent with streaming to avoid Anthropic's non-streaming timeout.

    Uses agent.run_stream() internally, consumes the full stream, then returns
    a result-like object with .output and .usage() matching run_agent_with_tracking.

    Use this for long-running generations (e.g. blueprint chunks) that would
    exceed Anthropic's 10-minute non-streaming request limit.
    """
    # Enforce usage limit before running (fail open)
    if organization_id and organization_id != "all":
        try:
            from .usage_limit_service import UsageLimitService
            from ..core.database import get_supabase_client
            limit_svc = UsageLimitService(get_supabase_client())
            limit_svc.enforce_limit(organization_id, "monthly_cost")
        except ImportError:
            pass
        except Exception as e:
            from .usage_limit_service import UsageLimitExceeded
            if isinstance(e, UsageLimitExceeded):
                raise
            logger.warning(f"Usage limit check failed (non-fatal): {e}")

    # Run with streaming to keep the connection alive.
    # StreamedRunResult has get_output() (not .output), so we capture
    # both output and usage inside the context and return a wrapper
    # that matches AgentRunResult's interface (.output / .usage()).
    async with agent.run_stream(prompt, **run_kwargs) as stream_result:
        output = await stream_result.get_output()
        usage_data = stream_result.usage()

    # Track usage (fire-and-forget)
    if tracker and organization_id and organization_id != "all":
        try:
            _track_stream_usage(
                usage=usage_data,
                agent=agent,
                tracker=tracker,
                user_id=user_id,
                organization_id=organization_id,
                tool_name=tool_name,
                operation=operation,
            )
        except Exception as e:
            logger.warning(f"Agent usage tracking failed (non-fatal): {e}")

    return _StreamResultCompat(output=output, _usage=usage_data)


def _track_agent_usage(
    result,
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


class _StreamResultCompat:
    """Lightweight wrapper so streamed results match AgentRunResult's interface."""

    def __init__(self, output, _usage):
        self.output = output
        self._usage = _usage

    def usage(self):
        return self._usage


def _track_stream_usage(
    usage,
    agent: Agent,
    tracker: UsageTracker,
    user_id: Optional[str],
    organization_id: str,
    tool_name: str,
    operation: str,
) -> None:
    """Track usage from a pre-extracted Usage object (streaming variant)."""
    model_name = str(agent.model) if agent.model else "unknown"
    provider = _get_provider_from_model(model_name)

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
