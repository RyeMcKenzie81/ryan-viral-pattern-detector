"""
Pydantic Graph Pipelines for ViralTracker.

This package contains state-driven DAG workflows using pydantic-graph:
- brand_onboarding: Scrape ads, analyze with AI, extract brand insights
- template_ingestion: Scrape ads, queue for human review, create templates
"""

from .states import BrandOnboardingState, TemplateIngestionState
from .brand_onboarding import (
    brand_onboarding_graph,
    run_brand_onboarding,
    ScrapeAdsNode,
    DownloadAssetsNode,
    AnalyzeImagesNode,
    AnalyzeVideosNode,
    SynthesizeNode,
)

__all__ = [
    # States
    "BrandOnboardingState",
    "TemplateIngestionState",
    # Brand Onboarding
    "brand_onboarding_graph",
    "run_brand_onboarding",
    "ScrapeAdsNode",
    "DownloadAssetsNode",
    "AnalyzeImagesNode",
    "AnalyzeVideosNode",
    "SynthesizeNode",
]
