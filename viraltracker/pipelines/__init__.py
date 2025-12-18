"""
Pydantic Graph Pipelines for ViralTracker.

This package contains state-driven DAG workflows using pydantic-graph:
- brand_onboarding: Scrape ads, analyze with AI, extract brand insights
- template_ingestion: Scrape ads, queue for human review, create templates
- belief_plan_execution: Execute Phase 1-2 belief testing plans
- reddit_sentiment: Scrape Reddit, analyze sentiment, extract quotes
"""

from .states import (
    BrandOnboardingState,
    TemplateIngestionState,
    BeliefPlanExecutionState,
    RedditSentimentState,
)
from .brand_onboarding import (
    brand_onboarding_graph,
    run_brand_onboarding,
    ScrapeAdsNode,
    DownloadAssetsNode,
    AnalyzeImagesNode,
    AnalyzeVideosNode,
    SynthesizeNode,
)
from .template_ingestion import (
    template_ingestion_graph,
    run_template_ingestion,
    ScrapeAdsNode as TemplateScrapeAdsNode,
    DownloadAssetsNode as TemplateDownloadAssetsNode,
    QueueForReviewNode,
)
from .belief_plan_execution import (
    belief_plan_execution_graph,
    run_belief_plan_execution,
    LoadPlanNode,
    BuildPromptsNode,
    GenerateImagesNode,
    ReviewAdsNode,
)
from .reddit_sentiment import (
    reddit_sentiment_graph,
    run_reddit_sentiment,
    run_reddit_sentiment_from_apify,
    ScrapeRedditNode,
    EngagementFilterNode,
    RelevanceFilterNode,
    SignalFilterNode,
    IntentScoreNode,
    TopSelectionNode,
    CategorizeNode,
    SaveNode,
)

__all__ = [
    # States
    "BrandOnboardingState",
    "TemplateIngestionState",
    "BeliefPlanExecutionState",
    "RedditSentimentState",
    # Brand Onboarding
    "brand_onboarding_graph",
    "run_brand_onboarding",
    "ScrapeAdsNode",
    "DownloadAssetsNode",
    "AnalyzeImagesNode",
    "AnalyzeVideosNode",
    "SynthesizeNode",
    # Template Ingestion
    "template_ingestion_graph",
    "run_template_ingestion",
    "TemplateScrapeAdsNode",
    "TemplateDownloadAssetsNode",
    "QueueForReviewNode",
    # Belief Plan Execution
    "belief_plan_execution_graph",
    "run_belief_plan_execution",
    "LoadPlanNode",
    "BuildPromptsNode",
    "GenerateImagesNode",
    "ReviewAdsNode",
    # Reddit Sentiment
    "reddit_sentiment_graph",
    "run_reddit_sentiment",
    "run_reddit_sentiment_from_apify",
    "ScrapeRedditNode",
    "EngagementFilterNode",
    "RelevanceFilterNode",
    "SignalFilterNode",
    "IntentScoreNode",
    "TopSelectionNode",
    "CategorizeNode",
    "SaveNode",
]
