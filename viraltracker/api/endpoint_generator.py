"""
Automatic API Endpoint Generator for Pydantic AI Agent Tools.

This module scans a Pydantic AI agent's registered tools and automatically
generates FastAPI endpoints for each tool, eliminating the need for manual
endpoint definitions.

The agent remains the single source of truth - tools are defined once with
@agent.tool() and endpoints are auto-generated from the tool signatures.

Usage:
    from viraltracker.agent.agent import agent
    from viraltracker.api.endpoint_generator import generate_tool_endpoints

    router = generate_tool_endpoints(agent, limiter, verify_api_key)
    app.include_router(router)

This creates POST /tools/{tool-name} endpoints for all registered agent tools.
"""

import logging
import inspect
from typing import Any, Dict, Callable, Optional
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, create_model, Field
from pydantic_ai import Agent, RunContext
from slowapi import Limiter
from typing import get_type_hints

from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================

def tool_name_to_path(tool_name: str) -> str:
    """
    Convert tool function name to API path.

    Examples:
        find_outliers_tool → find-outliers
        search_twitter_tool → search-twitter
        analyze_tiktok_video_tool → analyze-tiktok-video

    Args:
        tool_name: Tool function name (e.g., "find_outliers_tool")

    Returns:
        API path segment (e.g., "find-outliers")
    """
    # Remove _tool suffix if present
    name = tool_name.replace('_tool', '')
    # Convert snake_case to kebab-case
    path = name.replace('_', '-')
    return path


def create_request_model(tool_name: str, tool_function: Callable) -> type[BaseModel]:
    """
    Auto-generate Pydantic request model from tool function signature.

    Extracts parameters from the tool function (excluding 'ctx') and creates
    a Pydantic model with appropriate types and defaults. Adds project_name
    as a standard field for all tools.

    Args:
        tool_name: Name of the tool (for model naming)
        tool_function: The tool function to inspect

    Returns:
        Dynamically created Pydantic model class
    """
    sig = inspect.signature(tool_function)
    hints = get_type_hints(tool_function)

    fields = {}

    # Extract all parameters except ctx (RunContext)
    for param_name, param in sig.parameters.items():
        if param_name == 'ctx':
            continue  # Skip RunContext parameter

        # Get type hint, default to Any if not specified
        param_type = hints.get(param_name, Any)

        # Get default value, or use ... for required fields
        if param.default != inspect.Parameter.empty:
            default = param.default
        else:
            default = ...  # Required field

        fields[param_name] = (param_type, default)

    # Add project_name as standard field (all tools need this)
    fields['project_name'] = (str, 'yakety-pack-instagram')

    # Generate model name (e.g., FindOutliersRequest)
    model_name = ''.join(
        word.capitalize()
        for word in tool_name.replace('_tool', '').split('_')
    ) + 'Request'

    # Create and return dynamic Pydantic model
    return create_model(model_name, **fields)


def create_tool_endpoint(
    tool_name: str,
    tool_function: Callable,
    request_model: type[BaseModel],
    auth_dependency: Callable
) -> Callable:
    """
    Create FastAPI endpoint handler for a tool.

    The endpoint:
    1. Validates request with auto-generated Pydantic model
    2. Creates AgentDependencies from project_name
    3. Calls the tool function with parameters
    4. Returns standardized ToolResponse

    Args:
        tool_name: Name of the tool (for logging)
        tool_function: The tool function to call
        request_model: Pydantic model for request validation
        auth_dependency: FastAPI dependency for authentication

    Returns:
        Async endpoint handler function
    """
    async def endpoint(
        request: Request,
        tool_request: request_model,
        authenticated: bool = Depends(auth_dependency)
    ):
        """
        Auto-generated endpoint for {tool_name}.

        Executes the tool with provided parameters and returns results.
        """
        try:
            logger.info(f"Tool execution started: {tool_name}")

            # Extract parameters from request
            params = tool_request.model_dump()
            project_name = params.pop('project_name', 'yakety-pack-instagram')

            # Create agent dependencies
            deps = AgentDependencies.create(project_name=project_name)
            ctx = RunContext(deps=deps, retry=0, messages=[])

            # Call tool function
            result = await tool_function(ctx=ctx, **params)

            logger.info(f"Tool execution completed: {tool_name}")

            # Return standardized response
            return {
                "success": True,
                "data": result.model_dump() if hasattr(result, 'model_dump') else result,
                "error": None,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}", exc_info=True)
            return {
                "success": False,
                "data": {},
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    # Set endpoint metadata
    endpoint.__name__ = f"{tool_name}_endpoint"
    endpoint.__doc__ = f"Auto-generated endpoint for {tool_name}."

    return endpoint


# ============================================================================
# Main Generator Function
# ============================================================================

def generate_tool_endpoints(
    agent: Agent,
    limiter: Limiter,
    auth_dependency: Callable,
    rate_limit: str = "20/minute"
) -> APIRouter:
    """
    Generate FastAPI router with endpoints for all agent tools.

    Scans the agent's registered tools and creates POST endpoints for each:
    - Path: /tools/{tool-name}
    - Method: POST
    - Request: Auto-generated Pydantic model from function signature
    - Response: Standardized ToolResponse
    - Auth: Via provided auth_dependency
    - Rate limit: Configurable (default: 20/minute)

    Args:
        agent: Pydantic AI Agent with registered tools
        limiter: SlowAPI rate limiter instance
        auth_dependency: FastAPI auth dependency function
        rate_limit: Rate limit string (default: "20/minute")

    Returns:
        APIRouter with all auto-generated tool endpoints

    Example:
        >>> from viraltracker.agent.agent import agent
        >>> from slowapi import Limiter
        >>> from slowapi.util import get_remote_address
        >>>
        >>> limiter = Limiter(key_func=get_remote_address)
        >>> router = generate_tool_endpoints(agent, limiter, verify_api_key)
        >>> app.include_router(router)
    """
    router = APIRouter(tags=["Tools"])

    logger.info("="*60)
    logger.info("Auto-scanning agent for registered tools...")

    # Access agent's function toolset
    toolset = agent._function_toolset
    tools = toolset.tools

    logger.info(f"Found {len(tools)} tools in agent")

    # Generate endpoint for each tool
    for tool_name, tool in tools.items():
        # Get tool function and create request model
        tool_function = tool.function
        request_model = create_request_model(tool_name, tool_function)

        # Create endpoint path
        path = f"/tools/{tool_name_to_path(tool_name)}"

        # Create endpoint handler
        endpoint_handler = create_tool_endpoint(
            tool_name,
            tool_function,
            request_model,
            auth_dependency
        )

        # Add endpoint to router with rate limiting
        decorated_handler = limiter.limit(rate_limit)(endpoint_handler)

        router.add_api_route(
            path,
            decorated_handler,
            methods=["POST"],
            summary=f"Execute {tool_name.replace('_', ' ').title()}",
            description=tool.description or f"Direct access to {tool_name} tool.",
            response_description="Tool execution result"
        )

        logger.info(f"Generated endpoint: POST {path}")

    logger.info(f"Total auto-generated endpoints: {len(tools)}")
    logger.info("="*60)

    return router


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'generate_tool_endpoints',
    'tool_name_to_path',
    'create_request_model',
    'create_tool_endpoint'
]
