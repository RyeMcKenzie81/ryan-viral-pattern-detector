"""
SEO Pipeline Nodes Package.

Thin node wrappers for pydantic-graph.
Each node delegates to a service in ../services/.

Pipeline flow:
    KeywordDiscoveryNode
    → KeywordSelectionNode (HUMAN)
    → CompetitorAnalysisNode
    → ContentPhaseANode
    → OutlineReviewNode (HUMAN)
    → ContentPhaseBNode
    → ContentPhaseCNode
    → ArticleReviewNode (HUMAN)
    → QAValidationNode
    → QAApprovalNode (HUMAN)
    → ImageGenerationNode
    → PublishNode
    → InterlinkingNode
    → End
"""

from .keyword_discovery import KeywordDiscoveryNode
from .keyword_selection import KeywordSelectionNode
from .competitor_analysis import CompetitorAnalysisNode
from .content_generation import (
    ContentPhaseANode,
    OutlineReviewNode,
    ContentPhaseBNode,
    ContentPhaseCNode,
)
from .article_review import ArticleReviewNode
from .qa_publish import QAValidationNode, QAApprovalNode, PublishNode
from .image_generation import ImageGenerationNode
from .interlinking import InterlinkingNode

__all__ = [
    "KeywordDiscoveryNode",
    "KeywordSelectionNode",
    "CompetitorAnalysisNode",
    "ContentPhaseANode",
    "OutlineReviewNode",
    "ContentPhaseBNode",
    "ContentPhaseCNode",
    "ArticleReviewNode",
    "QAValidationNode",
    "QAApprovalNode",
    "ImageGenerationNode",
    "PublishNode",
    "InterlinkingNode",
]
