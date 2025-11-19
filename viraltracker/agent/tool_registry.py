"""
Tool Registry - Automatically register agent tools and generate API endpoints.

This module provides a centralized registry for all Pydantic AI tools,
automatically generating FastAPI endpoints for each registered tool.

Benefits:
- Single source of truth for tool definitions
- Automatic API endpoint generation
- Consistent tool metadata across agent and API
- Easy to add new tools (just decorate the function)
- Type-safe tool parameters with Pydantic models
"""

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type, get_type_hints

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, create_model
from pydantic_ai import RunContext

from .dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# ============================================================================
# Tool Metadata
# ============================================================================

@dataclass
class ToolMetadata:
    """
    Metadata for a registered tool.

    Attributes:
        name: Unique tool name (e.g., "find_outliers")
        function: The async function implementing the tool
        description: Human-readable description
        category: Tool category (e.g., "Twitter", "TikTok", "YouTube")
        rate_limit: Requests per minute for API endpoint
        api_path: Auto-generated API path (e.g., "/tools/find-outliers")
        request_model: Pydantic model for API request body
        response_model: Pydantic model for API response
        requires_auth: Whether API endpoint requires authentication
    """
    name: str
    function: Callable
    description: str
    category: str = "General"
    rate_limit: str = "20/minute"
    api_path: str = ""
    request_model: Optional[Type[BaseModel]] = None
    response_model: Optional[Type[BaseModel]] = None
    requires_auth: bool = True

    def __post_init__(self):
        """Generate API path from tool name."""
        if not self.api_path:
            # Convert snake_case to kebab-case
            self.api_path = f"/tools/{self.name.replace('_tool', '').replace('_', '-')}"


# ============================================================================
# Tool Registry
# ============================================================================

class ToolRegistry:
    """
    Central registry for all agent tools.

    Provides:
    - Tool registration via decorator
    - Automatic API endpoint generation
    - Tool metadata access
    - FastAPI router creation
    """

    def __init__(self):
        self._tools: Dict[str, ToolMetadata] = {}
        self._router: Optional[APIRouter] = None

    def register(
        self,
        name: str,
        description: str,
        category: str = "General",
        rate_limit: str = "20/minute",
        requires_auth: bool = True,
        request_model: Optional[Type[BaseModel]] = None,
        response_model: Optional[Type[BaseModel]] = None,
    ) -> Callable:
        """
        Decorator to register a tool function.

        Usage:
            @tool_registry.register(
                name="find_outliers_tool",
                description="Find viral outlier tweets",
                category="Twitter",
                rate_limit="20/minute",
                request_model=FindOutliersRequest,
                response_model=ToolResponse
            )
            async def find_outliers_tool(ctx: RunContext[AgentDependencies], ...):
                ...

        Args:
            name: Unique tool name
            description: Human-readable description
            category: Tool category for organization
            rate_limit: Rate limit string (e.g., "20/minute")
            requires_auth: Whether API endpoint requires authentication
            request_model: Pydantic model for request body (optional, auto-generated if None)
            response_model: Pydantic model for response (optional)

        Returns:
            Decorator function
        """
        def decorator(func: Callable) -> Callable:
            # Create request model if not provided
            if request_model is None:
                req_model = self._create_request_model(func, name)
            else:
                req_model = request_model

            # Create metadata
            metadata = ToolMetadata(
                name=name,
                function=func,
                description=description,
                category=category,
                rate_limit=rate_limit,
                request_model=req_model,
                response_model=response_model,
                requires_auth=requires_auth
            )

            # Register tool
            self._tools[name] = metadata
            logger.info(f"Registered tool: {name} -> {metadata.api_path}")

            return func

        return decorator

    def _create_request_model(self, func: Callable, name: str) -> Type[BaseModel]:
        """
        Auto-generate Pydantic request model from function signature.

        Args:
            func: The tool function
            name: Tool name for model naming

        Returns:
            Pydantic model class
        """
        # Get function signature
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        # Build field definitions (skip ctx parameter)
        fields = {}
        for param_name, param in sig.parameters.items():
            if param_name == 'ctx':
                continue

            # Get type annotation
            param_type = type_hints.get(param_name, Any)

            # Get default value
            default = param.default if param.default != inspect.Parameter.empty else ...

            # Add to fields
            fields[param_name] = (param_type, default)

        # Add project_name field (always required for tool execution)
        fields['project_name'] = (str, 'yakety-pack-instagram')

        # Create model
        model_name = f"{name.replace('_tool', '').title().replace('_', '')}Request"
        return create_model(model_name, **fields)

    def get_tool(self, name: str) -> Optional[ToolMetadata]:
        """Get tool metadata by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> Dict[str, ToolMetadata]:
        """Get all registered tools."""
        return self._tools.copy()

    def get_tools_by_category(self, category: str) -> List[ToolMetadata]:
        """Get tools filtered by category."""
        return [
            tool for tool in self._tools.values()
            if tool.category == category
        ]

    def create_api_router(
        self,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        limiter: Optional[Any] = None,
        auth_dependency: Optional[Callable] = None
    ) -> APIRouter:
        """
        Generate FastAPI router with all tool endpoints.

        Args:
            prefix: URL prefix for router (e.g., "/api/v1")
            tags: OpenAPI tags for endpoints
            limiter: SlowAPI limiter instance
            auth_dependency: FastAPI dependency for authentication

        Returns:
            Configured FastAPI router
        """
        router = APIRouter(prefix=prefix, tags=tags or ["Tools"])

        # Generate endpoint for each tool
        for tool in self._tools.values():
            self._add_endpoint_to_router(
                router=router,
                tool=tool,
                limiter=limiter,
                auth_dependency=auth_dependency
            )

        self._router = router
        logger.info(f"Created API router with {len(self._tools)} tool endpoints")
        return router

    def _add_endpoint_to_router(
        self,
        router: APIRouter,
        tool: ToolMetadata,
        limiter: Optional[Any],
        auth_dependency: Optional[Callable]
    ):
        """
        Add a single tool endpoint to the router.

        Args:
            router: FastAPI router
            tool: Tool metadata
            limiter: SlowAPI limiter
            auth_dependency: Auth dependency function
        """
        # Create endpoint handler
        async def endpoint_handler(
            request: Request,
            tool_request: tool.request_model,
            authenticated: bool = Depends(auth_dependency) if auth_dependency and tool.requires_auth else None
        ):
            """Auto-generated endpoint for tool execution."""
            try:
                # Extract project_name from request
                request_dict = tool_request.model_dump()
                project_name = request_dict.pop('project_name', 'yakety-pack-instagram')

                # Create dependencies
                deps = AgentDependencies.create(project_name=project_name)
                ctx = RunContext(deps=deps, retry=0, messages=[])

                # Call tool function
                result = await tool.function(ctx=ctx, **request_dict)

                # Return response
                from datetime import datetime
                return {
                    "success": True,
                    "data": result.model_dump() if hasattr(result, 'model_dump') else result,
                    "error": None,
                    "timestamp": datetime.now()
                }

            except Exception as e:
                logger.error(f"{tool.name} failed: {e}", exc_info=True)
                from datetime import datetime
                return {
                    "success": False,
                    "data": {},
                    "error": str(e),
                    "timestamp": datetime.now()
                }

        # Apply rate limiting if available
        if limiter:
            endpoint_handler = limiter.limit(tool.rate_limit)(endpoint_handler)

        # Add route to router
        router.add_api_route(
            path=tool.api_path,
            endpoint=endpoint_handler,
            methods=["POST"],
            summary=tool.description,
            description=f"Direct access to {tool.name}. Category: {tool.category}",
            response_model=tool.response_model,
            tags=[tool.category] if tool.category != "General" else None
        )

        logger.info(f"Added endpoint: POST {tool.api_path} ({tool.category})")


# ============================================================================
# Global Registry Instance
# ============================================================================

# Create global registry instance
tool_registry = ToolRegistry()


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'ToolRegistry',
    'ToolMetadata',
    'tool_registry'
]
