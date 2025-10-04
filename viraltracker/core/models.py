"""
Pydantic models for database tables
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, UUID4
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class ImportSource(str, Enum):
    """How a post was imported into the system"""
    SCRAPE = "scrape"
    DIRECT_URL = "direct_url"
    CSV_IMPORT = "csv_import"


class ImportMethod(str, Enum):
    """How a post was added to a project"""
    SCRAPE = "scrape"
    DIRECT_URL = "direct_url"
    CSV_BATCH = "csv_batch"


class PlatformSlug(str, Enum):
    """Platform identifiers"""
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE_SHORTS = "youtube_shorts"


# ============================================================================
# Base Models
# ============================================================================

class Brand(BaseModel):
    """Brand model"""
    id: UUID4
    name: str
    slug: str
    description: Optional[str] = None
    website: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Product(BaseModel):
    """Product model"""
    id: UUID4
    brand_id: UUID4
    name: str
    slug: str
    description: Optional[str] = None
    target_audience: Optional[str] = None
    price_range: Optional[str] = None
    key_problems_solved: Optional[List[str]] = None
    key_benefits: Optional[List[str]] = None
    features: Optional[List[str]] = None
    context_prompt: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class Platform(BaseModel):
    """Platform model"""
    id: UUID4
    name: str
    slug: PlatformSlug
    scraper_type: Optional[str] = None
    scraper_config: Optional[Dict[str, Any]] = None
    max_video_length_sec: Optional[int] = None
    typical_video_length_sec: Optional[int] = None
    aspect_ratio: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Project(BaseModel):
    """Project model"""
    id: UUID4
    brand_id: UUID4
    product_id: Optional[UUID4] = None
    name: str
    slug: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class Account(BaseModel):
    """Account model"""
    id: UUID4
    handle: str  # Legacy field, kept for backwards compatibility
    platform_id: Optional[UUID4] = None
    platform_username: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime


class Post(BaseModel):
    """Post model"""
    id: UUID4
    account_id: Optional[UUID4] = None
    platform_id: Optional[UUID4] = None
    post_url: str
    post_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    caption: Optional[str] = None
    length_sec: Optional[int] = None
    import_source: Optional[ImportSource] = None
    is_own_content: bool = False
    created_at: datetime
    updated_at: datetime


class VideoAnalysis(BaseModel):
    """Video analysis model"""
    id: UUID4
    post_id: UUID4
    platform_id: Optional[UUID4] = None

    # Hook analysis
    hook_transcript: Optional[str] = None
    hook_visual_storyboard: Optional[Dict[str, Any]] = None
    hook_type: Optional[str] = None
    hook_timestamp: Optional[float] = None

    # Content extraction
    transcript: Optional[Dict[str, Any]] = None
    text_overlays: Optional[Dict[str, Any]] = None
    storyboard: Optional[Dict[str, Any]] = None
    key_moments: Optional[Dict[str, Any]] = None

    # Analysis
    viral_factors: Optional[Dict[str, Any]] = None
    viral_explanation: Optional[str] = None
    improvement_suggestions: Optional[str] = None

    # Platform-specific
    platform_specific_metrics: Optional[Dict[str, Any]] = None

    # Metadata
    analysis_model: str = "gemini-2.5-flash"
    analysis_tokens_used: Optional[int] = None
    processing_time_sec: Optional[float] = None
    created_at: datetime


class ProductAdaptation(BaseModel):
    """Product adaptation model"""
    id: UUID4
    post_id: UUID4
    product_id: UUID4
    video_analysis_id: Optional[UUID4] = None

    # Scoring
    hook_relevance_score: Optional[float] = Field(None, ge=1, le=10)
    audience_match_score: Optional[float] = Field(None, ge=1, le=10)
    transition_ease_score: Optional[float] = Field(None, ge=1, le=10)
    viral_replicability_score: Optional[float] = Field(None, ge=1, le=10)
    overall_score: Optional[float] = Field(None, ge=1, le=10)

    # Adaptation content
    adapted_hook: Optional[str] = None
    adapted_script: Optional[str] = None
    storyboard: Optional[Dict[str, Any]] = None
    text_overlays: Optional[Dict[str, Any]] = None
    transition_strategy: Optional[str] = None
    best_use_case: Optional[str] = None
    production_notes: Optional[str] = None

    # Metadata
    ai_model: str = "gemini-2.5-flash"
    ai_tokens_used: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ProjectAccount(BaseModel):
    """Project-Account link model"""
    id: UUID4
    project_id: UUID4
    account_id: UUID4
    priority: int = 1
    notes: Optional[str] = None
    added_at: datetime


class ProjectPost(BaseModel):
    """Project-Post link model"""
    id: UUID4
    project_id: UUID4
    post_id: UUID4
    import_method: ImportMethod
    is_own_content: bool = False
    notes: Optional[str] = None
    added_at: datetime


# ============================================================================
# Create/Update DTOs (Data Transfer Objects)
# ============================================================================

class PostCreate(BaseModel):
    """Data for creating a new post"""
    account_id: Optional[UUID4] = None
    platform_id: UUID4
    post_url: str
    post_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    caption: Optional[str] = None
    length_sec: Optional[int] = None
    import_source: ImportSource = ImportSource.SCRAPE
    is_own_content: bool = False


class ProjectPostCreate(BaseModel):
    """Data for creating a project-post link"""
    project_id: UUID4
    post_id: UUID4
    import_method: ImportMethod = ImportMethod.DIRECT_URL
    is_own_content: bool = False
    notes: Optional[str] = None
