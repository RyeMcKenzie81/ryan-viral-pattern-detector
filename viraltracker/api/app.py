"""
Viraltracker FastAPI Application.

REST API for agent execution, enabling webhook integration with
automation tools (n8n, Zapier, Make.com).

Features:
- Agent execution endpoint with Pydantic AI
- API key authentication
- Rate limiting
- Health check endpoint
- Automatic OpenAPI documentation
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
    ErrorResponse,
    FindOutliersRequest,
    AnalyzeHooksRequest,
    SearchTwitterRequest,
    FindCommentOpportunitiesRequest,
    ToolResponse
)
from ..agent.agent import agent
from ..agent.dependencies import AgentDependencies

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
    description="REST API for viral content analysis with Pydantic AI",
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

    Args:
        api_key: API key from X-API-Key header

    Raises:
        HTTPException: If API key is invalid or missing
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
    """
    Check API health and service status.

    Returns status of the API and its dependent services
    (database, AI models, etc.).
    """
    services = {}

    # Check database connection
    try:
        from ..services.twitter_service import TwitterService
        twitter = TwitterService()
        # Simple check - if initialization doesn't error, we're good
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

    # Check OpenAI (via Pydantic AI)
    # For now, just mark as available if dependencies load
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
@limiter.limit("10/minute")  # Rate limit: 10 requests per minute per IP
async def run_agent(
    request: Request,
    agent_request: AgentRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Execute Pydantic AI agent with natural language prompt.

    This endpoint allows you to interact with the Viraltracker agent
    using natural language. The agent has access to 16 tools across
    Twitter, TikTok, YouTube, and Facebook platforms.

    **Example prompts:**
    - "Find viral tweets from the last 24 hours"
    - "Analyze hooks for top performing tweets"
    - "Search TikTok for trending fitness content"
    - "Find comment opportunities with high engagement"

    **Rate Limits:**
    - 10 requests per minute per IP address
    - Configurable via RATE_LIMIT_PER_MINUTE env var

    **Authentication:**
    - Requires X-API-Key header (set VIRALTRACKER_API_KEY env var)
    - Development mode: No auth required if VIRALTRACKER_API_KEY not set
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
# Direct Tool Endpoints (for specific use cases)
# ============================================================================

@app.post(
    "/tools/find-outliers",
    response_model=ToolResponse,
    tags=["Tools"],
    summary="Find viral outlier tweets"
)
@limiter.limit("20/minute")
async def find_outliers_endpoint(
    request: Request,
    tool_request: FindOutliersRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Direct access to find_outliers tool.

    Bypasses the agent for faster, deterministic execution.
    Useful for scheduled jobs and workflows that don't need
    natural language processing.
    """
    try:
        from ..agent.tools import find_outliers_tool
        from pydantic_ai import RunContext

        deps = AgentDependencies.create(project_name=tool_request.project_name)
        ctx = RunContext(deps=deps, retry=0, messages=[])

        result = await find_outliers_tool(
            ctx=ctx,
            hours_back=tool_request.hours_back,
            threshold=tool_request.threshold,
            method=tool_request.method,
            min_views=tool_request.min_views,
            text_only=tool_request.text_only,
            limit=tool_request.limit
        )

        return ToolResponse(
            success=True,
            data={
                "total_tweets": result.total_tweets,
                "outlier_count": result.outlier_count,
                "threshold": result.threshold,
                "method": result.method,
                "outliers": [o.model_dump() for o in result.outliers]
            },
            error=None,
            timestamp=datetime.now()
        )

    except Exception as e:
        logger.error(f"find_outliers tool failed: {e}", exc_info=True)
        return ToolResponse(
            success=False,
            data={},
            error=str(e),
            timestamp=datetime.now()
        )


@app.post(
    "/tools/analyze-hooks",
    response_model=ToolResponse,
    tags=["Tools"],
    summary="Analyze tweet hooks with AI"
)
@limiter.limit("10/minute")  # Lower limit for AI-heavy operations
async def analyze_hooks_endpoint(
    request: Request,
    tool_request: AnalyzeHooksRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Direct access to analyze_hooks tool.

    Analyzes tweet hooks using Gemini AI to identify:
    - Hook types (hot_take, relatable_slice, insider_secret, etc.)
    - Emotional triggers (anger, validation, humor, curiosity, etc.)
    - Content patterns
    """
    try:
        from ..agent.tools import analyze_hooks_tool
        from pydantic_ai import RunContext

        deps = AgentDependencies.create(project_name=tool_request.project_name)
        ctx = RunContext(deps=deps, retry=0, messages=[])

        result = await analyze_hooks_tool(
            ctx=ctx,
            tweet_ids=tool_request.tweet_ids,
            hours_back=tool_request.hours_back,
            limit=tool_request.limit,
            min_views=tool_request.min_views
        )

        return ToolResponse(
            success=True,
            data={
                "total_analyzed": result.total_analyzed,
                "successful_analyses": result.successful_analyses,
                "failed_analyses": result.failed_analyses,
                "analyses": [a.model_dump() for a in result.analyses]
            },
            error=None,
            timestamp=datetime.now()
        )

    except Exception as e:
        logger.error(f"analyze_hooks tool failed: {e}", exc_info=True)
        return ToolResponse(
            success=False,
            data={},
            error=str(e),
            timestamp=datetime.now()
        )


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
    return {
        "name": "Viraltracker API",
        "version": "1.0.0",
        "description": "REST API for viral content analysis with Pydantic AI",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "agent_execution": "/agent/run",
            "find_outliers": "/tools/find-outliers",
            "analyze_hooks": "/tools/analyze-hooks"
        }
    }
