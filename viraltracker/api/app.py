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

# Load environment variables FIRST before any other imports
from dotenv import load_dotenv
load_dotenv()

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

from pydantic_ai.result import FinalResult

from .models import (
    AgentRequest,
    AgentResponse,
    HealthResponse,
    ErrorResponse,
    AdCreationRequest,
    AdCreationResponse
)
from .endpoint_generator import generate_tool_endpoints
from ..agent.agent import agent  # Keep for backwards compatibility in /agent/run
from ..agent.orchestrator import orchestrator
from ..agent.agents.twitter_agent import twitter_agent
from ..agent.agents.tiktok_agent import tiktok_agent
from ..agent.agents.youtube_agent import youtube_agent
from ..agent.agents.facebook_agent import facebook_agent
from ..agent.agents.analysis_agent import analysis_agent
from ..agent.agents.ad_creation_agent import ad_creation_agent
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

        # Run agent with prompt - PydanticAI returns FinalResult with .output attribute
        result: FinalResult = await agent.run(
            agent_request.prompt,
            deps=deps,
            model=agent_request.model
        )

        execution_time = time.time() - start_time

        logger.info(f"Agent execution completed in {execution_time:.2f}s")

        # Extract result data - PydanticAI FinalResult has .output attribute
        result_data = str(result.output)

        # Return response
        return AgentResponse(
            success=True,
            result=result_data,
            metadata={
                "model": agent_request.model,
                "project_name": agent_request.project_name,
                "execution_time_seconds": round(execution_time, 2),
                "prompt_length": len(agent_request.prompt),
                "response_length": len(result_data)
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
            timestamp=datetime.now().isoformat()
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
            timestamp=datetime.now().isoformat()
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
# Auto-Generated Tool Endpoints
# ============================================================================

# Generate and include routers for ALL agents (orchestrator + 5 specialists)
logger.info("Generating auto-endpoints for all agent tools...")

# Generate router for each agent
orchestrator_router = generate_tool_endpoints(orchestrator, limiter, verify_api_key)
twitter_router = generate_tool_endpoints(twitter_agent, limiter, verify_api_key)
tiktok_router = generate_tool_endpoints(tiktok_agent, limiter, verify_api_key)
youtube_router = generate_tool_endpoints(youtube_agent, limiter, verify_api_key)
facebook_router = generate_tool_endpoints(facebook_agent, limiter, verify_api_key)
analysis_router = generate_tool_endpoints(analysis_agent, limiter, verify_api_key)

# Include all routers with platform-specific prefixes and tags
app.include_router(orchestrator_router, prefix="/api/v1/orchestrator", tags=["Orchestrator"])
app.include_router(twitter_router, prefix="/api/v1/twitter", tags=["Twitter"])
app.include_router(tiktok_router, prefix="/api/v1/tiktok", tags=["TikTok"])
app.include_router(youtube_router, prefix="/api/v1/youtube", tags=["YouTube"])
app.include_router(facebook_router, prefix="/api/v1/facebook", tags=["Facebook"])
app.include_router(analysis_router, prefix="/api/v1/analysis", tags=["Analysis"])

# Legacy: Include orchestrator router at /tools/* for backwards compatibility
app.include_router(orchestrator_router, prefix="/tools", tags=["Tools (Legacy)"])

logger.info("Auto-generated tool endpoints registered successfully")
logger.info(f"  - Orchestrator: {len(orchestrator._function_toolset.tools)} tools")
logger.info(f"  - Twitter: {len(twitter_agent._function_toolset.tools)} tools")
logger.info(f"  - TikTok: {len(tiktok_agent._function_toolset.tools)} tools")
logger.info(f"  - YouTube: {len(youtube_agent._function_toolset.tools)} tools")
logger.info(f"  - Facebook: {len(facebook_agent._function_toolset.tools)} tools")
logger.info(f"  - Analysis: {len(analysis_agent._function_toolset.tools)} tools")


# ============================================================================
# Ad Creation Endpoint
# ============================================================================

@app.post(
    "/api/ad-creation/create",
    response_model=AdCreationResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid API key"},
        429: {"model": ErrorResponse, "description": "Too many requests"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    tags=["Ad Creation"],
    summary="Generate 5 Facebook ad variations with AI review"
)
@limiter.limit("5/hour")  # Rate limit: 5 requests per hour (image generation is expensive)
async def create_ads(
    request: Request,
    ad_request: AdCreationRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Execute complete Facebook ad creation workflow.

    This endpoint generates 5 ad variations using the Ad Creation Agent:
    1. Analyzes reference ad using Vision AI
    2. Selects 5 diverse persuasive hooks
    3. Generates 5 ad variations using Gemini Nano Banana Pro 3
    4. Dual AI review (Claude + Gemini) with OR logic
    5. Returns complete results with approval status

    **Workflow Steps:**
    - Upload reference ad to storage
    - Fetch product data and hooks from database
    - Analyze reference ad format and style (Vision AI)
    - Select 5 diverse hooks with AI
    - Generate 5 ads ONE AT A TIME (resilience)
    - Dual review: Either Claude OR Gemini approving = approved
    - Flag disagreements for human review

    **Rate Limits:**
    - 5 requests per hour per IP (image generation is expensive)
    - Each request generates 5 ads with dual AI review

    **Authentication:**
    - Requires X-API-Key header (set VIRALTRACKER_API_KEY env var)
    - Development mode: No auth required if VIRALTRACKER_API_KEY not set

    **Request Body:**
    ```json
    {
        "product_id": "uuid-string",
        "reference_ad_base64": "base64-encoded-image-data",
        "reference_ad_filename": "reference.png",
        "project_id": "optional-uuid-string"
    }
    ```

    **Response Body:**
    ```json
    {
        "success": true,
        "ad_run_id": "uuid",
        "data": {
            "product": {...},
            "reference_ad_path": "storage-path",
            "ad_analysis": {...},
            "selected_hooks": [...],
            "generated_ads": [
                {
                    "prompt_index": 1,
                    "storage_path": "...",
                    "final_status": "approved",
                    "claude_review": {...},
                    "gemini_review": {...},
                    "reviewers_agree": true
                }
            ],
            "approved_count": 3,
            "rejected_count": 1,
            "flagged_count": 1,
            "summary": "Ad creation workflow completed..."
        }
    }
    ```
    """
    start_time = time.time()

    try:
        logger.info(f"Ad creation workflow started - Product: {ad_request.product_id}")

        # Initialize agent dependencies
        deps = AgentDependencies.create(
            project_name="default"  # Project context optional for ad creation
        )

        # Call the complete_ad_workflow tool via agent
        result = await ad_creation_agent.run(
            f"""Execute the complete ad creation workflow for this request:

Product ID: {ad_request.product_id}
Reference Ad: (base64 image provided)
Filename: {ad_request.reference_ad_filename}
Project ID: {ad_request.project_id or 'None'}

Use the complete_ad_workflow tool to:
1. Create ad run in database
2. Upload reference ad to storage
3. Fetch product data and hooks
4. Analyze reference ad with Vision AI
5. Select 5 diverse hooks
6. Generate 5 ad variations (ONE AT A TIME)
7. Dual AI review (Claude + Gemini) with OR logic
8. Return complete results

Call complete_ad_workflow with these parameters:
- product_id: "{ad_request.product_id}"
- reference_ad_base64: "{ad_request.reference_ad_base64}"
- reference_ad_filename: "{ad_request.reference_ad_filename}"
- project_id: "{ad_request.project_id or ''}"
""",
            deps=deps,
            model="claude-sonnet-4-5-20250929"
        )

        execution_time = time.time() - start_time

        logger.info(f"Ad creation workflow completed in {execution_time:.2f}s")

        # Extract workflow result
        workflow_data = result.output if hasattr(result, 'output') else result

        # Return successful response
        return AdCreationResponse(
            success=True,
            ad_run_id=workflow_data.get('ad_run_id') if isinstance(workflow_data, dict) else None,
            data=workflow_data if isinstance(workflow_data, dict) else {"result": str(workflow_data)},
            error=None,
            timestamp=datetime.now()
        )

    except ValueError as e:
        # Handle validation errors (invalid product_id, image data, etc.)
        execution_time = time.time() - start_time
        logger.error(f"Validation error after {execution_time:.2f}s: {e}")

        return AdCreationResponse(
            success=False,
            ad_run_id=None,
            data=None,
            error=f"Validation error: {str(e)}",
            timestamp=datetime.now()
        )

    except Exception as e:
        # Handle unexpected errors
        execution_time = time.time() - start_time
        logger.error(f"Ad creation workflow failed after {execution_time:.2f}s: {e}", exc_info=True)

        return AdCreationResponse(
            success=False,
            ad_run_id=None,
            data=None,
            error=f"Workflow failed: {str(e)}",
            timestamp=datetime.now()
        )


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
            "ad_creation": "/api/ad-creation/create",
            "auto_generated_tools": "/tools/* (see /docs for all 16 auto-generated endpoints)"
        }
    }
