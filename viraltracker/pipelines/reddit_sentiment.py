"""
Reddit Sentiment Analysis Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeReddit → EngagementFilter → RelevanceFilter →
          SignalFilter → IntentScore → TopSelection →
          Categorize → Save

This pipeline:
1. Scrapes Reddit posts via Apify
2. Filters by engagement (upvotes, comments)
3. Scores relevance using Claude Sonnet
4. Filters signal from noise using Claude Sonnet
5. Scores buyer intent/sophistication
6. Selects top 20% of posts
7. Categorizes into 6 sentiment buckets using Claude Opus 4.5
8. Extracts quotes and saves to DB, optionally syncs to persona

Part of the Market Research Pipeline.
"""

import logging
from dataclasses import dataclass
from typing import List, Union
from uuid import UUID
from datetime import datetime

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import RedditSentimentState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeRedditNode(BaseNode[RedditSentimentState]):
    """
    Step 1: Scrape Reddit posts via Apify.

    Uses RedditSentimentService to scrape posts from Reddit
    using the fatihtahta/reddit-scraper-search-fast actor.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "EngagementFilterNode":
        logger.info(f"Step 1: Scraping Reddit for queries: {ctx.state.search_queries}")
        ctx.state.current_step = "scraping"

        try:
            from ..services.models import RedditScrapeConfig

            # Create scrape configuration
            config = RedditScrapeConfig(
                search_queries=ctx.state.search_queries,
                subreddits=ctx.state.subreddits,
                timeframe=ctx.state.timeframe,
                sort_by=ctx.state.sort_by,
                max_posts=ctx.state.max_posts,
                scrape_comments=ctx.state.scrape_comments,
                min_upvotes=ctx.state.min_upvotes,
                min_comments=ctx.state.min_comments,
            )

            # Create run record
            ctx.state.run_id = ctx.deps.reddit_sentiment.create_run(
                config=config,
                brand_id=ctx.state.brand_id,
                product_id=ctx.state.product_id,
                persona_id=ctx.state.persona_id,
                persona_context=ctx.state.persona_context,
                topic_context=ctx.state.topic_context,
                brand_context=ctx.state.brand_context,
                product_context=ctx.state.product_context,
            )

            # Update run status
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running", current_step="ScrapeRedditNode"
            )

            # Scrape Reddit
            posts, comments = ctx.deps.reddit_sentiment.scrape_reddit(config)

            # Store as dicts in state
            ctx.state.scraped_posts = [p.model_dump() for p in posts]
            ctx.state.scraped_comments = [c.model_dump() for c in comments]
            ctx.state.posts_scraped = len(posts)

            # Estimate costs
            apify_cost, llm_cost = ctx.deps.reddit_sentiment.estimate_cost(len(posts))
            ctx.state.apify_cost = apify_cost
            ctx.state.llm_cost_estimate = llm_cost

            logger.info(f"Scraped {len(posts)} posts, {len(comments)} comments")

            if not posts:
                ctx.state.current_step = "complete"
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "completed",
                    posts_scraped=0
                )
                return End({
                    "status": "no_posts",
                    "message": "No posts found for the search queries",
                    "run_id": str(ctx.state.run_id)
                })

            return EngagementFilterNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Scrape failed: {e}")
            if ctx.state.run_id:
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "failed", error=str(e)
                )
            return End({"status": "error", "error": str(e), "step": "scrape"})


@dataclass
class EngagementFilterNode(BaseNode[RedditSentimentState]):
    """
    Step 2: Filter posts by engagement thresholds.

    Deterministic filter based on upvotes and comment count.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "RelevanceFilterNode":
        logger.info(f"Step 2: Filtering {len(ctx.state.scraped_posts)} posts by engagement")
        ctx.state.current_step = "engagement_filter"

        try:
            from ..services.models import RedditPost

            # Convert dicts back to models
            posts = [RedditPost(**p) for p in ctx.state.scraped_posts]

            # Filter by engagement
            filtered = ctx.deps.reddit_sentiment.filter_by_engagement(
                posts,
                min_upvotes=ctx.state.min_upvotes,
                min_comments=ctx.state.min_comments
            )

            ctx.state.engagement_filtered = [p.model_dump() for p in filtered]
            ctx.state.posts_after_engagement = len(filtered)

            # Update run status
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="EngagementFilterNode",
                posts_scraped=ctx.state.posts_scraped,
                posts_after_engagement=len(filtered)
            )

            logger.info(f"After engagement filter: {len(filtered)} posts")

            if not filtered:
                ctx.state.current_step = "complete"
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "completed",
                    posts_after_engagement=0
                )
                return End({
                    "status": "no_posts_after_filter",
                    "message": "No posts passed engagement filter",
                    "run_id": str(ctx.state.run_id)
                })

            return RelevanceFilterNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Engagement filter failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "engagement_filter"})


@dataclass
class RelevanceFilterNode(BaseNode[RedditSentimentState]):
    """
    Step 3: Score and filter by relevance using Claude Sonnet.

    LLM-based scoring for persona and topic relevance.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "SignalFilterNode":
        logger.info(f"Step 3: Scoring relevance for {len(ctx.state.engagement_filtered)} posts")
        ctx.state.current_step = "relevance_filter"

        try:
            from ..services.models import RedditPost

            posts = [RedditPost(**p) for p in ctx.state.engagement_filtered]

            # Score relevance
            filtered = await ctx.deps.reddit_sentiment.score_relevance(
                posts,
                persona_context=ctx.state.persona_context,
                topic_context=ctx.state.topic_context,
                threshold=ctx.state.relevance_threshold
            )

            ctx.state.relevance_filtered = [p.model_dump() for p in filtered]
            ctx.state.posts_after_relevance = len(filtered)

            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="RelevanceFilterNode",
                posts_after_relevance=len(filtered)
            )

            logger.info(f"After relevance filter: {len(filtered)} posts")

            if not filtered:
                ctx.state.current_step = "complete"
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "completed",
                    posts_after_relevance=0
                )
                return End({
                    "status": "no_posts_after_filter",
                    "message": "No posts passed relevance filter",
                    "run_id": str(ctx.state.run_id)
                })

            return SignalFilterNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Relevance filter failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "relevance_filter"})


@dataclass
class SignalFilterNode(BaseNode[RedditSentimentState]):
    """
    Step 4: Filter signal from noise using Claude Sonnet.

    Removes jokes, spam, off-topic tangents, and low-effort posts.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "IntentScoreNode":
        logger.info(f"Step 4: Filtering signal for {len(ctx.state.relevance_filtered)} posts")
        ctx.state.current_step = "signal_filter"

        try:
            from ..services.models import RedditPost

            posts = [RedditPost(**p) for p in ctx.state.relevance_filtered]

            # Filter signal from noise
            filtered = await ctx.deps.reddit_sentiment.filter_signal_from_noise(
                posts,
                threshold=ctx.state.signal_threshold
            )

            ctx.state.signal_filtered = [p.model_dump() for p in filtered]
            ctx.state.posts_after_signal = len(filtered)

            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="SignalFilterNode",
                posts_after_signal=len(filtered)
            )

            logger.info(f"After signal filter: {len(filtered)} posts")

            if not filtered:
                ctx.state.current_step = "complete"
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "completed",
                    posts_after_signal=0
                )
                return End({
                    "status": "no_posts_after_filter",
                    "message": "No posts passed signal filter",
                    "run_id": str(ctx.state.run_id)
                })

            return IntentScoreNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Signal filter failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "signal_filter"})


@dataclass
class IntentScoreNode(BaseNode[RedditSentimentState]):
    """
    Step 5: Score buyer intent/sophistication using Claude Sonnet.

    Scores based on purchase history, brand comparisons, etc.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "TopSelectionNode":
        logger.info(f"Step 5: Scoring intent for {len(ctx.state.signal_filtered)} posts")
        ctx.state.current_step = "intent_scoring"

        try:
            from ..services.models import RedditPost

            posts = [RedditPost(**p) for p in ctx.state.signal_filtered]

            # Score buyer intent
            scored = await ctx.deps.reddit_sentiment.score_buyer_intent(posts)

            ctx.state.intent_scored = [p.model_dump() for p in scored]

            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="IntentScoreNode"
            )

            logger.info(f"Scored intent for {len(scored)} posts")
            return TopSelectionNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Intent scoring failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "intent_scoring"})


@dataclass
class TopSelectionNode(BaseNode[RedditSentimentState]):
    """
    Step 6: Select top percentile of posts by combined score.

    Deterministic selection based on weighted score.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "CategorizeNode":
        logger.info(f"Step 6: Selecting top {ctx.state.top_percentile*100:.0f}%")
        ctx.state.current_step = "top_selection"

        try:
            from ..services.models import RedditPost

            posts = [RedditPost(**p) for p in ctx.state.intent_scored]

            # Select top percentile
            top_posts = ctx.deps.reddit_sentiment.select_top_percentile(
                posts,
                percentile=ctx.state.top_percentile
            )

            ctx.state.top_selected = [p.model_dump() for p in top_posts]
            ctx.state.posts_top_selected = len(top_posts)

            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="TopSelectionNode",
                posts_top_selected=len(top_posts)
            )

            logger.info(f"Selected top {len(top_posts)} posts")

            if not top_posts:
                ctx.state.current_step = "complete"
                ctx.deps.reddit_sentiment.update_run_status(
                    ctx.state.run_id, "completed",
                    posts_top_selected=0
                )
                return End({
                    "status": "no_posts_selected",
                    "message": "No posts selected in top percentile",
                    "run_id": str(ctx.state.run_id)
                })

            return CategorizeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Top selection failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "top_selection"})


@dataclass
class CategorizeNode(BaseNode[RedditSentimentState]):
    """
    Step 7: Categorize into 6 sentiment buckets and extract quotes.

    Uses Claude Opus 4.5 for deep extraction and categorization.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> "SaveNode":
        logger.info(f"Step 7: Categorizing {len(ctx.state.top_selected)} posts")
        ctx.state.current_step = "running"

        try:
            from ..services.models import RedditPost

            posts = [RedditPost(**p) for p in ctx.state.top_selected]

            # Save posts to DB first to get UUIDs
            ctx.deps.reddit_sentiment.save_posts(
                ctx.state.run_id,
                posts,
                brand_id=ctx.state.brand_id
            )

            # Categorize and extract quotes
            categorized = await ctx.deps.reddit_sentiment.categorize_and_extract_quotes(
                posts,
                brand_context=ctx.state.brand_context,
                product_context=ctx.state.product_context
            )

            # Convert to dicts for state storage
            ctx.state.categorized_quotes = {
                cat.value: [q.model_dump() for q in quotes]
                for cat, quotes in categorized.items()
            }
            ctx.state.quotes_extracted = sum(
                len(quotes) for quotes in categorized.values()
            )

            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "running",
                current_step="CategorizeNode",
                quotes_extracted=ctx.state.quotes_extracted
            )

            logger.info(f"Extracted {ctx.state.quotes_extracted} quotes")
            return SaveNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Categorization failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "categorize"})


@dataclass
class SaveNode(BaseNode[RedditSentimentState]):
    """
    Step 8: Save quotes to DB and optionally sync to persona.

    Final step - persists results and optionally updates persona fields.
    """

    async def run(
        self,
        ctx: GraphRunContext[RedditSentimentState, AgentDependencies]
    ) -> End:
        logger.info("Step 8: Saving results")
        ctx.state.current_step = "saving"

        try:
            from ..services.models import SentimentCategory, RedditSentimentQuote

            # Reconstruct quotes from state
            quotes = {
                SentimentCategory(cat): [
                    RedditSentimentQuote(**q) for q in q_list
                ]
                for cat, q_list in ctx.state.categorized_quotes.items()
            }

            # Save quotes to database
            ctx.deps.reddit_sentiment.save_quotes(
                ctx.state.run_id,
                quotes,
                brand_id=ctx.state.brand_id
            )

            # Optionally sync to persona
            if ctx.state.auto_sync_to_persona and ctx.state.persona_id:
                sync_counts = ctx.deps.reddit_sentiment.sync_quotes_to_persona(
                    quotes,
                    ctx.state.persona_id
                )
                ctx.state.quotes_synced = sum(sync_counts.values())
                logger.info(f"Synced {ctx.state.quotes_synced} quotes to persona")

            # Update final run status
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "completed",
                current_step="SaveNode",
                quotes_extracted=ctx.state.quotes_extracted,
                quotes_synced=ctx.state.quotes_synced,
                apify_cost_estimate=ctx.state.apify_cost,
                llm_cost_estimate=ctx.state.llm_cost_estimate
            )

            ctx.state.current_step = "complete"

            # Build result summary
            quotes_by_category = {
                cat: len(q_list)
                for cat, q_list in ctx.state.categorized_quotes.items()
            }

            return End({
                "status": "success",
                "run_id": str(ctx.state.run_id),
                "posts_scraped": ctx.state.posts_scraped,
                "posts_after_engagement": ctx.state.posts_after_engagement,
                "posts_after_relevance": ctx.state.posts_after_relevance,
                "posts_after_signal": ctx.state.posts_after_signal,
                "posts_top_selected": ctx.state.posts_top_selected,
                "quotes_extracted": ctx.state.quotes_extracted,
                "quotes_by_category": quotes_by_category,
                "quotes_synced": ctx.state.quotes_synced,
                "apify_cost": ctx.state.apify_cost,
                "llm_cost_estimate": ctx.state.llm_cost_estimate,
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Save failed: {e}")
            ctx.deps.reddit_sentiment.update_run_status(
                ctx.state.run_id, "failed", error=str(e)
            )
            return End({"status": "error", "error": str(e), "step": "save"})


# Build the graph
reddit_sentiment_graph = Graph(
    nodes=(
        ScrapeRedditNode,
        EngagementFilterNode,
        RelevanceFilterNode,
        SignalFilterNode,
        IntentScoreNode,
        TopSelectionNode,
        CategorizeNode,
        SaveNode,
    ),
    name="reddit_sentiment"
)


# Convenience function
async def run_reddit_sentiment(
    search_queries: List[str],
    brand_id: UUID = None,
    product_id: UUID = None,
    persona_id: UUID = None,
    subreddits: List[str] = None,
    timeframe: str = "month",
    max_posts: int = 500,
    min_upvotes: int = 20,
    min_comments: int = 5,
    relevance_threshold: float = 0.6,
    signal_threshold: float = 0.5,
    top_percentile: float = 0.20,
    auto_sync_to_persona: bool = True,
    persona_context: str = None,
    topic_context: str = None,
    brand_context: str = None,
    product_context: str = None,
) -> dict:
    """
    Run the Reddit sentiment analysis pipeline.

    Args:
        search_queries: List of search terms to use
        brand_id: Optional brand UUID for association
        product_id: Optional product UUID
        persona_id: Optional persona UUID for auto-sync
        subreddits: Optional list of subreddits to search
        timeframe: Time range (hour, day, week, month, year, all)
        max_posts: Maximum posts to scrape
        min_upvotes: Minimum upvotes for engagement filter
        min_comments: Minimum comments for engagement filter
        relevance_threshold: Minimum relevance score (0-1)
        signal_threshold: Minimum signal score (0-1)
        top_percentile: Top percentage to keep (0.01-1.0)
        auto_sync_to_persona: Whether to sync quotes to persona
        persona_context: Description of target persona
        topic_context: Description of topic/domain
        brand_context: Brand description for extraction
        product_context: Product category description

    Returns:
        Dict with run results and statistics
    """
    from ..agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    state = RedditSentimentState(
        search_queries=search_queries,
        brand_id=brand_id,
        product_id=product_id,
        persona_id=persona_id,
        subreddits=subreddits,
        timeframe=timeframe,
        max_posts=max_posts,
        min_upvotes=min_upvotes,
        min_comments=min_comments,
        relevance_threshold=relevance_threshold,
        signal_threshold=signal_threshold,
        top_percentile=top_percentile,
        auto_sync_to_persona=auto_sync_to_persona,
        persona_context=persona_context,
        topic_context=topic_context,
        brand_context=brand_context,
        product_context=product_context,
    )

    result = await reddit_sentiment_graph.run(
        ScrapeRedditNode(),
        state=state,
        deps=deps
    )

    return result.output


async def run_reddit_sentiment_from_apify(
    apify_run_id: str,
    brand_id: UUID = None,
    product_id: UUID = None,
    persona_id: UUID = None,
    min_upvotes: int = 20,
    min_comments: int = 5,
    relevance_threshold: float = 0.6,
    signal_threshold: float = 0.5,
    top_percentile: float = 0.20,
    auto_sync_to_persona: bool = True,
    persona_context: str = None,
    topic_context: str = None,
    brand_context: str = None,
    product_context: str = None,
) -> dict:
    """
    Run Reddit sentiment analysis using data from an existing Apify run.

    Useful for recovering from a failed pipeline run without re-scraping.

    Args:
        apify_run_id: The Apify run ID to recover data from (e.g., "FWOdh8fceEdMrRMBs")
        brand_id: Optional brand UUID for association
        product_id: Optional product UUID
        persona_id: Optional persona UUID for auto-sync
        min_upvotes: Minimum upvotes for engagement filter
        min_comments: Minimum comments for engagement filter
        relevance_threshold: Minimum relevance score (0-1)
        signal_threshold: Minimum signal score (0-1)
        top_percentile: Top percentage to keep (0.01-1.0)
        auto_sync_to_persona: Whether to sync quotes to persona
        persona_context: Description of target persona
        topic_context: Description of topic/domain
        brand_context: Brand description for extraction
        product_context: Product category description

    Returns:
        Dict with run results and statistics
    """
    from ..agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    from ..services.models import RedditScrapeConfig

    # Recover data from existing Apify run
    logger.info(f"Recovering data from Apify run: {apify_run_id}")
    posts, comments = deps.reddit_sentiment.recover_from_apify_run(apify_run_id)

    # Create config for run record
    config = RedditScrapeConfig(
        search_queries=[f"recovered_from:{apify_run_id}"],
        subreddits=None,
        timeframe="all",
        sort_by="relevance",
        max_posts=len(posts),
        min_upvotes=min_upvotes,
        min_comments=min_comments,
    )

    # Create run record
    run_id = deps.reddit_sentiment.create_run(
        config=config,
        brand_id=brand_id,
        product_id=product_id,
        persona_id=persona_id,
        persona_context=persona_context,
        topic_context=topic_context,
        brand_context=brand_context,
        product_context=product_context,
    )

    # Create state with pre-loaded data
    state = RedditSentimentState(
        search_queries=[f"recovered_from:{apify_run_id}"],
        brand_id=brand_id,
        product_id=product_id,
        persona_id=persona_id,
        min_upvotes=min_upvotes,
        min_comments=min_comments,
        relevance_threshold=relevance_threshold,
        signal_threshold=signal_threshold,
        top_percentile=top_percentile,
        auto_sync_to_persona=auto_sync_to_persona,
        persona_context=persona_context,
        topic_context=topic_context,
        brand_context=brand_context,
        product_context=product_context,
        # Pre-populate with recovered data
        run_id=run_id,
        scraped_posts=[p.model_dump() for p in posts],
        scraped_comments=[c.model_dump() for c in comments],
        posts_scraped=len(posts),
    )

    # Start from EngagementFilterNode (skip scraping)
    result = await reddit_sentiment_graph.run(
        EngagementFilterNode(),
        state=state,
        deps=deps
    )

    return result.output
