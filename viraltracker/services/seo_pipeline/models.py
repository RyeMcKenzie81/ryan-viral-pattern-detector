"""
SEO Pipeline Models - Enums and Pydantic models for the SEO content pipeline.

Defines data structures used across all pipeline services:
- Status/phase enums for keywords, articles, and links
- Pydantic models for structured data exchange between services
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class KeywordStatus(str, Enum):
    """Status of a keyword in the discovery/analysis pipeline."""
    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    SELECTED = "selected"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ArticleStatus(str, Enum):
    """Status of an article through its lifecycle."""
    DRAFT = "draft"
    OUTLINE_COMPLETE = "outline_complete"  # Phase A done
    DRAFT_COMPLETE = "draft_complete"      # Phase B done
    OPTIMIZED = "optimized"               # Phase C done
    QA_PENDING = "qa_pending"
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    DISCOVERED = "discovered"  # Auto-created from GSC, not for content generation


class ProjectStatus(str, Enum):
    """Status of an SEO project."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ArticlePhase(str, Enum):
    """The three content generation phases."""
    PHASE_A = "a"  # Research & outline
    PHASE_B = "b"  # Free-write
    PHASE_C = "c"  # SEO optimization


class SearchIntent(str, Enum):
    """Search intent classification for keywords."""
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


class LinkType(str, Enum):
    """Type of internal link."""
    SUGGESTED = "suggested"
    AUTO = "auto"
    BIDIRECTIONAL = "bidirectional"
    MANUAL = "manual"
    CLUSTER = "cluster"


class LinkStatus(str, Enum):
    """Status of an internal link suggestion."""
    PENDING = "pending"
    IMPLEMENTED = "implemented"
    REJECTED = "rejected"


class LinkPriority(str, Enum):
    """Priority of a link suggestion based on similarity."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LinkPlacement(str, Enum):
    """Where in the article a link should be placed."""
    MIDDLE = "middle"
    END = "end"


class ClusterStatus(str, Enum):
    """Lifecycle status of a topic cluster."""
    DRAFT = "draft"
    ACTIVE = "active"
    PUBLISHING = "publishing"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class ClusterIntent(str, Enum):
    """Search intent classification for a cluster."""
    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    NAVIGATIONAL = "navigational"
    TRANSACTIONAL = "transactional"


class SpokeRole(str, Enum):
    """Role of a keyword within a cluster."""
    PILLAR = "pillar"
    SPOKE = "spoke"


class SpokeStatus(str, Enum):
    """Lifecycle status of a spoke article."""
    PLANNED = "planned"
    WRITING = "writing"
    PUBLISHED = "published"
    SKIPPED = "skipped"


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class SEOKeyword(BaseModel):
    """A discovered keyword with metadata."""
    keyword: str
    word_count: int
    seed_keyword: str
    search_volume: Optional[int] = None
    keyword_difficulty: Optional[float] = None
    search_intent: Optional[SearchIntent] = None
    status: KeywordStatus = KeywordStatus.DISCOVERED
    cluster_id: Optional[UUID] = None
    found_in_seeds: int = 1  # Cross-seed frequency signal


class SEOAuthor(BaseModel):
    """An author for SEO articles."""
    id: Optional[UUID] = None
    brand_id: UUID
    organization_id: UUID
    name: str
    bio: Optional[str] = None
    image_url: Optional[str] = None
    job_title: Optional[str] = None
    author_url: Optional[str] = None
    persona_id: Optional[UUID] = None
    schema_data: Optional[Dict[str, Any]] = None
    is_default: bool = False


class CompetitorMetrics(BaseModel):
    """Extracted metrics from a competitor page."""
    url: str
    position: Optional[int] = None
    title: Optional[str] = None
    meta_description: Optional[str] = None
    word_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    h4_count: int = 0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0
    flesch_reading_ease: Optional[float] = None
    internal_link_count: int = 0
    external_link_count: int = 0
    image_count: int = 0
    images_with_alt: int = 0
    has_toc: bool = False
    has_faq: bool = False
    has_schema: bool = False
    has_author: bool = False
    has_breadcrumbs: bool = False
    schema_types: List[str] = Field(default_factory=list)
    cta_count: int = 0
    has_tables: bool = False
    table_count: int = 0
    video_embeds: int = 0
    raw_analysis: Optional[Dict[str, Any]] = None


class WinningFormula(BaseModel):
    """Aggregated competitor metrics (median/avg) as target specs."""
    avg_word_count: int = 0
    median_word_count: int = 0
    avg_h2_count: int = 0
    avg_h3_count: int = 0
    avg_paragraph_count: int = 0
    avg_flesch_score: float = 0.0
    avg_internal_links: int = 0
    avg_external_links: int = 0
    avg_image_count: int = 0
    avg_cta_count: int = 0
    pct_with_schema: float = 0.0
    pct_with_faq: float = 0.0
    pct_with_toc: float = 0.0
    pct_with_author: float = 0.0
    pct_with_breadcrumbs: float = 0.0
    target_word_count: int = 0  # avg * 1.12
    target_flesch: float = 65.0  # 60-70 range
    opportunities: List[Dict[str, Any]] = Field(default_factory=list)


class QACheck(BaseModel):
    """A single QA check result."""
    name: str
    passed: bool
    severity: str = "warning"  # "error" or "warning"
    message: str = ""
    details: Optional[Dict[str, Any]] = None


class QAResult(BaseModel):
    """Result of running all QA checks on an article."""
    article_id: UUID
    passed: bool
    total_checks: int = 0
    passed_checks: int = 0
    checks: List[QACheck] = Field(default_factory=list)
    failures: List[QACheck] = Field(default_factory=list)
    warnings: List[QACheck] = Field(default_factory=list)


class LinkSuggestion(BaseModel):
    """An internal link suggestion."""
    source_article_id: UUID
    target_article_id: UUID
    anchor_text: str
    similarity_score: float
    link_type: LinkType = LinkType.SUGGESTED
    status: LinkStatus = LinkStatus.PENDING
    placement: LinkPlacement = LinkPlacement.END
    priority: LinkPriority = LinkPriority.MEDIUM
    anchor_variations: List[str] = Field(default_factory=list)
