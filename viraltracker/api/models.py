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
    timestamp: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Invalid API key",
                "detail": "The provided API key is invalid or expired",
                "timestamp": "2025-01-18T12:00:00Z"
            }
        }
