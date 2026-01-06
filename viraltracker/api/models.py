"""
API Request and Response Models.

Pydantic models for FastAPI request/response validation and
automatic OpenAPI documentation generation.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


# ============================================================================
# Agent Request/Response Models
# ============================================================================

class AgentRequest(BaseModel):
    """
    Request model for agent execution.

    Used for webhook-based agent execution from n8n/Zapier/Make.
    """
    prompt: str = Field(
        ...,
        description="User prompt/question for the agent",
        examples=["Find viral tweets from the last 24 hours"]
    )
    project_name: str = Field(
        default="yakety-pack-instagram",
        description="Project name for data filtering"
    )
    model: Optional[str] = Field(
        default="openai:gpt-4o",
        description="AI model to use (e.g., 'openai:gpt-4o', 'gemini-1.5-pro')"
    )
    max_tokens: Optional[int] = Field(
        default=4000,
        description="Maximum tokens for agent response",
        ge=100,
        le=10000
    )

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "Find viral tweets from yesterday and analyze their hooks",
                "project_name": "yakety-pack-instagram",
                "model": "openai:gpt-4o",
                "max_tokens": 4000
            }
        }


class AgentResponse(BaseModel):
    """
    Response model for agent execution.

    Returns agent results with metadata for tracking and debugging.
    """
    success: bool = Field(..., description="Whether execution succeeded")
    result: str = Field(..., description="Agent response text (markdown formatted)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (model, tokens, execution time, etc.)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if execution failed"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Response timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "result": "# Viral Tweets Analysis\n\nFound 5 viral tweets...",
                "metadata": {
                    "model": "openai:gpt-4o",
                    "tokens_used": 1250,
                    "execution_time_seconds": 3.45,
                    "project_name": "yakety-pack-instagram"
                },
                "error": None,
                "timestamp": "2025-01-18T12:00:00Z"
            }
        }


# ============================================================================
# Tool Execution Models
# ============================================================================

class FindOutliersRequest(BaseModel):
    """Request model for find_outliers tool."""
    project_name: str = Field(default="yakety-pack-instagram")
    hours_back: int = Field(default=24, ge=1, le=720)
    threshold: float = Field(default=2.0, ge=0.5, le=5.0)
    method: str = Field(default="zscore", pattern="^(zscore|percentile)$")
    min_views: int = Field(default=100, ge=0)
    text_only: bool = Field(default=True)
    limit: int = Field(default=10, ge=1, le=100)


class AnalyzeHooksRequest(BaseModel):
    """Request model for analyze_hooks tool."""
    project_name: str = Field(default="yakety-pack-instagram")
    tweet_ids: Optional[List[str]] = Field(None, description="Specific tweet IDs to analyze")
    hours_back: int = Field(default=24, ge=1, le=720)
    limit: int = Field(default=20, ge=1, le=100)
    min_views: int = Field(default=100, ge=0)


class SearchTwitterRequest(BaseModel):
    """Request model for search_twitter tool."""
    project_name: str = Field(default="yakety-pack-instagram")
    keyword: str = Field(..., description="Keyword to search for")
    hours_back: int = Field(default=24, ge=1, le=720)
    max_results: int = Field(default=100, ge=1, le=1000)


class FindCommentOpportunitiesRequest(BaseModel):
    """Request model for find_comment_opportunities tool."""
    project_name: str = Field(default="yakety-pack-instagram")
    hours_back: int = Field(default=48, ge=1, le=720)
    min_green_flags: int = Field(default=3, ge=0, le=10)
    max_candidates: int = Field(default=100, ge=1, le=10000)


class ToolResponse(BaseModel):
    """Generic response model for tool execution."""
    success: bool = Field(..., description="Whether execution succeeded")
    data: Dict[str, Any] = Field(..., description="Tool response data")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# Health Check Models
# ============================================================================

class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, str] = Field(
        default_factory=dict,
        description="Status of dependent services (database, AI models, etc.)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": "2025-01-18T12:00:00Z",
                "services": {
                    "database": "connected",
                    "gemini_ai": "available",
                    "openai": "available"
                }
            }
        }


# ============================================================================
# Error Models
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Invalid API key",
                "detail": "The provided API key is invalid or expired",
                "timestamp": "2025-01-18T12:00:00Z"
            }
        }


# ============================================================================
# Ad Creation Models
# ============================================================================

class AdCreationRequest(BaseModel):
    """
    Request model for ad creation workflow.

    Used to generate Facebook ad variations with dual AI review.
    """
    product_id: str = Field(
        ...,
        description="UUID of product for ad generation"
    )
    reference_ad_base64: str = Field(
        ...,
        description="Base64-encoded reference ad image"
    )
    reference_ad_filename: str = Field(
        default="reference.png",
        description="Filename for reference ad (default: reference.png)"
    )
    project_id: Optional[str] = Field(
        None,
        description="Optional UUID of project"
    )
    num_variations: int = Field(
        default=5,
        description="Number of ad variations to generate (1-15)",
        ge=1,
        le=15
    )
    content_source: str = Field(
        default="hooks",
        description="Source for ad content: 'hooks' (use hooks from database), 'recreate_template' (extract template angle and use product benefits), 'belief_first' (use belief angle from Ad Planning), 'plan' (use belief plan), or 'angles' (use selected angles directly)",
        pattern="^(hooks|recreate_template|belief_first|plan|angles)$"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "product_id": "550e8400-e29b-41d4-a716-446655440000",
                "reference_ad_base64": "iVBORw0KGgoAAAANS...",
                "reference_ad_filename": "reference.png",
                "project_id": None,
                "num_variations": 5,
                "content_source": "hooks"
            }
        }


class AdCreationResponse(BaseModel):
    """
    Response model for ad creation workflow.

    Returns complete workflow results with approval status for all 5 ads.
    """
    success: bool = Field(..., description="Whether workflow succeeded")
    ad_run_id: Optional[str] = Field(None, description="UUID of ad run")
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="Complete workflow results with generated ads and reviews"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if workflow failed"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Response timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "ad_run_id": "550e8400-e29b-41d4-a716-446655440000",
                "data": {
                    "ad_run_id": "550e8400-e29b-41d4-a716-446655440000",
                    "product": {"name": "Wonder Paws", "...": "..."},
                    "reference_ad_path": "reference-ads/...",
                    "generated_ads": [
                        {
                            "prompt_index": 1,
                            "storage_path": "generated-ads/...",
                            "final_status": "approved",
                            "claude_review": {"status": "approved", "...": "..."},
                            "gemini_review": {"status": "approved", "...": "..."}
                        }
                    ],
                    "approved_count": 3,
                    "rejected_count": 1,
                    "flagged_count": 1,
                    "summary": "Ad creation workflow completed..."
                },
                "error": None,
                "timestamp": "2025-01-18T12:00:00Z"
            }
        }
