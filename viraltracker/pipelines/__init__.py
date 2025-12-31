"""
Pydantic Graph Pipelines for ViralTracker.

This package contains state-driven DAG workflows using pydantic-graph:
- brand_onboarding: Scrape ads, analyze with AI, extract brand insights
- template_ingestion: Scrape ads, queue for human review, create templates
- belief_plan_execution: Execute Phase 1-2 belief testing plans
- reddit_sentiment: Scrape Reddit, analyze sentiment, extract quotes
- content_pipeline: Topic discovery and content generation workflow
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

# Content Pipeline imports
from ..services.content_pipeline.orchestrator import (
    content_pipeline_graph_mvp1,
    content_pipeline_graph_mvp2,
    content_pipeline_graph,
    TopicDiscoveryNode,
    TopicEvaluationNode,
    TopicSelectionNode,
    ScriptGenerationNode,
    ScriptReviewNode,
    ScriptApprovalNode,
    ELSConversionNode,
    run_topic_discovery,
)

# =============================================================================
# GRAPH REGISTRY - Auto-discovery for visualization
# =============================================================================
# Add new pipelines here and they'll automatically appear in the visualizer.

GRAPH_REGISTRY = {
    "brand_onboarding": {
        "graph": brand_onboarding_graph,
        "start_node": ScrapeAdsNode,
        "run_function": "run_brand_onboarding",
        "description": "Scrape ads, analyze with AI, extract brand insights",
        "nodes": ["ScrapeAdsNode", "DownloadAssetsNode", "AnalyzeImagesNode",
                  "AnalyzeVideosNode", "SynthesizeNode"],
        "node_classes": [ScrapeAdsNode, DownloadAssetsNode, AnalyzeImagesNode,
                         AnalyzeVideosNode, SynthesizeNode],
        "callers": [],  # Not currently called from UI
    },
    "template_ingestion": {
        "graph": template_ingestion_graph,
        "start_node": TemplateScrapeAdsNode,
        "run_function": "run_template_ingestion",
        "description": "Scrape ads, queue for human review, create templates",
        "nodes": ["ScrapeAdsNode", "DownloadAssetsNode", "QueueForReviewNode"],
        "node_classes": [TemplateScrapeAdsNode, TemplateDownloadAssetsNode, QueueForReviewNode],
        "callers": [{"type": "ui", "page": "28_📋_Template_Queue.py"}],
    },
    "belief_plan_execution": {
        "graph": belief_plan_execution_graph,
        "start_node": LoadPlanNode,
        "run_function": "run_belief_plan_execution",
        "description": "Execute Phase 1-2 belief testing plans",
        "nodes": ["LoadPlanNode", "BuildPromptsNode", "GenerateImagesNode", "ReviewAdsNode"],
        "node_classes": [LoadPlanNode, BuildPromptsNode, GenerateImagesNode, ReviewAdsNode],
        "callers": [{"type": "ui", "page": "27_🎯_Plan_Executor.py"}],
    },
    "reddit_sentiment": {
        "graph": reddit_sentiment_graph,
        "start_node": ScrapeRedditNode,
        "run_function": "run_reddit_sentiment",
        "description": "Scrape Reddit, analyze sentiment, extract quotes",
        "nodes": ["ScrapeRedditNode", "EngagementFilterNode", "RelevanceFilterNode",
                  "SignalFilterNode", "IntentScoreNode", "TopSelectionNode",
                  "CategorizeNode", "SaveNode"],
        "node_classes": [ScrapeRedditNode, EngagementFilterNode, RelevanceFilterNode,
                         SignalFilterNode, IntentScoreNode, TopSelectionNode,
                         CategorizeNode, SaveNode],
        "callers": [{"type": "ui", "page": "15_🔍_Reddit_Research.py"}],
    },
    "content_pipeline_mvp1": {
        "graph": content_pipeline_graph_mvp1,
        "start_node": TopicDiscoveryNode,
        "run_function": "run_topic_discovery",
        "description": "Topic discovery pipeline (MVP 1)",
        "nodes": ["TopicDiscoveryNode", "TopicEvaluationNode", "TopicSelectionNode"],
        "node_classes": [TopicDiscoveryNode, TopicEvaluationNode, TopicSelectionNode],
        "callers": [{"type": "ui", "page": "41_📝_Content_Pipeline.py"}],
    },
    "content_pipeline_mvp2": {
        "graph": content_pipeline_graph_mvp2,
        "start_node": TopicDiscoveryNode,
        "run_function": "run_topic_discovery",
        "description": "Content pipeline through script approval (MVP 2)",
        "nodes": ["TopicDiscoveryNode", "TopicEvaluationNode", "TopicSelectionNode",
                  "ScriptGenerationNode", "ScriptReviewNode", "ScriptApprovalNode",
                  "ELSConversionNode"],
        "node_classes": [TopicDiscoveryNode, TopicEvaluationNode, TopicSelectionNode,
                         ScriptGenerationNode, ScriptReviewNode, ScriptApprovalNode,
                         ELSConversionNode],
        "callers": [{"type": "ui", "page": "41_📝_Content_Pipeline.py"}],
    },
}

__all__ = [
    # Registry
    "GRAPH_REGISTRY",
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
    # Content Pipeline
    "content_pipeline_graph_mvp1",
    "content_pipeline_graph_mvp2",
    "content_pipeline_graph",
    "TopicDiscoveryNode",
    "TopicEvaluationNode",
    "TopicSelectionNode",
    "ScriptGenerationNode",
    "ScriptReviewNode",
    "ScriptApprovalNode",
    "ELSConversionNode",
    "run_topic_discovery",
]
