"""
Viraltracker FastAPI Application - WITH AUTO-GENERATED TOOL ENDPOINTS.

This version demonstrates how to use the tool_registry to automatically
generate API endpoints for all registered tools.

Key differences from manual endpoint creation:
1. Import tools_registered (not tools) to trigger decorator registration
2. Call tool_registry.create_api_router() to generate all endpoints
3. Include the router in the main app

Benefits:
- Add new tool = automatic API endpoint
- Consistent parameter validation
- Type-safe requests/responses
- Single source of truth
"""

import logging
import os
import time
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .models import (
    AgentRequest,
    AgentResponse,
    HealthResponse,
    ErrorResponse
)
from ..agent.agent import agent
from ..agent.dependencies import AgentDependencies

# IMPORTANT: Import tools_registered to trigger decorator registration
# This must happen before create_api_router() is called
from ..agent import tools_registered  # noqa: F401

# Import tool registry
from ..agent.tool_registry import tool_registry

# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="Viraltracker API",
    description="REST API for viral content analysis with Pydantic AI and auto-generated tool endpoints",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ============================================================================
# CORS Configuration
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Rate Limiting
# ============================================================================

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================================
# API Key Authentication
# ============================================================================

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)):
    """
    Verify API key from request header.

    Checks against environment variable VIRALTRACKER_API_KEY.
    If not set, allows all requests (development mode).
    """
    expected_key = os.getenv("VIRALTRACKER_API_KEY")

    # Development mode - no API key required
    if not expected_key:
        logger.warning("VIRALTRACKER_API_KEY not set - running in development mode (no auth)")
        return True

    # Production mode - verify API key
    if not api_key:
        logger.warning("API key missing from request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide via X-API-Key header."
        )

    if api_key != expected_key:
        logger.warning(f"Invalid API key attempt: {api_key[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    logger.info("API key verified successfully")
    return True


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check endpoint"
)
async def health_check():
    """Check API health and service status."""
    services = {}

    # Check database connection
    try:
        from ..services.twitter_service import TwitterService
        twitter = TwitterService()
        services["database"] = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        services["database"] = "error"

    # Check Gemini AI
    try:
        from ..services.gemini_service import GeminiService
        gemini = GeminiService()
        services["gemini_ai"] = "available"
    except Exception as e:
        logger.error(f"Gemini AI health check failed: {e}")
        services["gemini_ai"] = "error"

    # Check Pydantic AI
    services["pydantic_ai"] = "available"

    # Determine overall status
    overall_status = "healthy" if all(
        s != "error" for s in services.values()
    ) else "degraded"

    return HealthResponse(
        status=overall_status,
        version="1.0.0",
        timestamp=datetime.now(),
        services=services
    )


# ============================================================================
# Agent Execution Endpoint
# ============================================================================

@app.post(
    "/agent/run",
    response_model=AgentResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid API key"},
        429: {"model": ErrorResponse, "description": "Too many requests"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    tags=["Agent"],
    summary="Execute Pydantic AI agent"
)
@limiter.limit("10/minute")
async def run_agent(
    request: Request,
    agent_request: AgentRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Execute Pydantic AI agent with natural language prompt.

    This endpoint allows you to interact with the Viraltracker agent
    using natural language. The agent has access to all registered tools.
    """
    start_time = time.time()

    try:
        logger.info(f"Agent execution started - Project: {agent_request.project_name}, Model: {agent_request.model}")
        logger.info(f"Prompt: {agent_request.prompt[:100]}...")

        # Initialize agent dependencies
        deps = AgentDependencies.create(
            project_name=agent_request.project_name
        )

        # Run agent with prompt
        result = await agent.run(
            agent_request.prompt,
            deps=deps,
            model=agent_request.model
        )

        execution_time = time.time() - start_time

        logger.info(f"Agent execution completed in {execution_time:.2f}s")

        # Return response
        return AgentResponse(
            success=True,
            result=result.data,
            metadata={
                "model": agent_request.model,
                "project_name": agent_request.project_name,
                "execution_time_seconds": round(execution_time, 2),
                "prompt_length": len(agent_request.prompt),
                "response_length": len(result.data)
            },
            error=None,
            timestamp=datetime.now()
        )

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Agent execution failed after {execution_time:.2f}s: {e}", exc_info=True)

        return AgentResponse(
            success=False,
            result="",
            metadata={
                "model": agent_request.model,
                "project_name": agent_request.project_name,
                "execution_time_seconds": round(execution_time, 2)
            },
            error=str(e),
            timestamp=datetime.now()
        )


# ============================================================================
# AUTO-GENERATED TOOL ENDPOINTS
# ============================================================================

# Create router with all tool endpoints
tool_router = tool_registry.create_api_router(
    prefix="",  # No prefix, endpoints will be /tools/*
    tags=["Auto-Generated Tools"],
    limiter=limiter,
    auth_dependency=verify_api_key
)

# Include the router in the main app
app.include_router(tool_router)

logger.info(f"Registered {len(tool_registry.get_all_tools())} auto-generated tool endpoints")


# ============================================================================
# Tool Registry Info Endpoint
# ============================================================================

@app.get(
    "/tools",
    tags=["System"],
    summary="List all registered tools"
)
async def list_tools():
    """
    Get information about all registered tools and their endpoints.

    Returns:
        Dictionary of tools with their metadata
    """
    tools = tool_registry.get_all_tools()

    return {
        "total_tools": len(tools),
        "tools": {
            name: {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "api_path": tool.api_path,
                "rate_limit": tool.rate_limit,
                "requires_auth": tool.requires_auth
            }
            for name, tool in tools.items()
        },
        "categories": list(set(tool.category for tool in tools.values()))
    }


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent error format."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            detail=str(exc),
            timestamp=datetime.now()
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            timestamp=datetime.now()
        ).model_dump()
    )


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Log startup information."""
    logger.info("="*60)
    logger.info("Viraltracker API Starting...")
    logger.info(f"API Version: 1.0.0")
    logger.info(f"Docs available at: /docs")
    logger.info(f"Auth mode: {'Production (API key required)' if os.getenv('VIRALTRACKER_API_KEY') else 'Development (no auth)'}")
    logger.info(f"Auto-generated tool endpoints: {len(tool_registry.get_all_tools())}")
    logger.info("="*60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown information."""
    logger.info("Viraltracker API Shutting down...")


# ============================================================================
# Root Endpoint
# ============================================================================

@app.get("/", tags=["System"])
async def root():
    """
    API root endpoint with basic information.
    """
    tools = tool_registry.get_all_tools()

    return {
        "name": "Viraltracker API",
        "version": "1.0.0",
        "description": "REST API for viral content analysis with auto-generated tool endpoints",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "agent_execution": "/agent/run",
            "list_tools": "/tools"
        },
        "auto_generated_tools": len(tools),
        "tool_categories": list(set(tool.category for tool in tools.values()))
    }
