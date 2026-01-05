"""
RedditSentimentService - Scrape and analyze Reddit for domain sentiment.

This service handles:
1. Reddit scraping via Apify (fatihtahta/reddit-scraper-search-fast)
2. Engagement filtering (upvotes, comments thresholds)
3. LLM-based relevance scoring (Claude Sonnet)
4. LLM-based signal filtering (noise removal, Claude Sonnet)
5. LLM-based intent/sophistication scoring (Claude Sonnet)
6. Sentiment categorization into 6 buckets (Claude Opus 4.5)
7. Quote extraction (Claude Opus 4.5)
8. Optional sync to persona/planning fields

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import os
import json
import logging
from typing import List, Dict, Optional, Any, Tuple
from uuid import UUID
from datetime import datetime

from ..core.config import Config
from pydantic_ai import Agent
import asyncio
from supabase import Client

from ..core.database import get_supabase_client
from .apify_service import ApifyService
from .models import (
    RedditPost,
    RedditComment,
    RedditSentimentQuote,
    RedditScrapeConfig,
    RedditScrapeRunResult,
    SentimentCategory,
    DomainSentiment,
)

logger = logging.getLogger(__name__)

# Apify actor ID for Reddit scraping
REDDIT_SCRAPER_ACTOR = "fatihtahta/reddit-scraper-search-fast"

# Model choices per user requirements
FAST_MODEL = "claude-sonnet-4-20250514"  # For filtering (relevance, signal, intent)
DEEP_MODEL = "claude-opus-4-5-20251101"  # For extraction (categorization, quotes)

# Cost estimates per 1M tokens (approximate)
SONNET_INPUT_COST = 3.0  # $3/1M input
SONNET_OUTPUT_COST = 15.0  # $15/1M output
OPUS_INPUT_COST = 15.0  # $15/1M input
OPUS_OUTPUT_COST = 75.0  # $75/1M output


class RedditSentimentService:
    """
    Service for Reddit domain sentiment analysis.

    Scrapes Reddit, filters posts, scores with LLMs, extracts quotes,
    and optionally syncs to persona fields.

    Example usage:
        service = RedditSentimentService()
        config = RedditScrapeConfig(search_queries=["dog food allergies"])
        posts = service.scrape_reddit(config)
        filtered = service.filter_by_engagement(posts)
        scored = await service.score_relevance(filtered, persona_context="dog owners")
    """

    def __init__(
        self,
        apify_service: Optional[ApifyService] = None,
        anthropic_api_key: Optional[str] = None
    ):
        """
        Initialize RedditSentimentService.

        Args:
            apify_service: Optional ApifyService instance. Created if not provided.
            anthropic_api_key: Optional API key. Uses ANTHROPIC_API_KEY env var if not provided.
        """
        self.apify = apify_service or ApifyService()
        self.supabase: Client = get_supabase_client()
        logger.info("RedditSentimentService initialized")

        logger.info("RedditSentimentService initialized")

    # =========================================================================
    # SCRAPING
    # =========================================================================

    def scrape_reddit(
        self,
        config: RedditScrapeConfig,
        timeout: int = 600
    ) -> Tuple[List[RedditPost], List[RedditComment]]:
        """
        Scrape Reddit posts via Apify.

        Uses fatihtahta/reddit-scraper-search-fast actor.

        Args:
            config: Scrape configuration (queries, subreddits, filters)
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (posts, comments)
        """
        if config.search_queries:
            logger.info(f"Scraping Reddit with queries: {config.search_queries}")
        if config.subreddits:
            logger.info(f"Scraping subreddits: {config.subreddits}")

        run_input = {
            "maxPosts": config.max_posts,
            "sort": config.sort_by,
            "timeframe": config.timeframe,
            "includeNsfw": config.include_nsfw,
            "scrapeComments": config.scrape_comments,
            "maxComments": config.max_comments_per_post,
        }

        # Add queries if provided
        if config.search_queries:
            run_input["queries"] = config.search_queries

        # Add subreddit filtering/scraping
        if config.subreddits:
            run_input["subredditName"] = config.subreddits[0]
            if len(config.subreddits) > 1:
                run_input["subredditKeywords"] = config.subreddits[1:]
            # For subreddit-only mode (no queries), use subreddit names as queries
            if not config.search_queries:
                run_input["queries"] = config.subreddits

        result = self.apify.run_actor(
            actor_id=REDDIT_SCRAPER_ACTOR,
            run_input=run_input,
            timeout=timeout
        )

        posts = []
        comments = []

        for item in result.items:
            if item.get("kind") == "post":
                # Parse created_utc - handle both timestamp and ISO string
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                posts.append(RedditPost(
                    reddit_id=item.get("id", ""),
                    subreddit=item.get("subreddit", ""),
                    title=item.get("title", ""),
                    body=item.get("body") or item.get("selftext"),
                    author=item.get("author"),
                    url=item.get("url"),
                    score=item.get("score", 0),
                    upvote_ratio=item.get("upvote_ratio", 0.0),
                    num_comments=item.get("num_comments", 0),
                    created_utc=created_utc,
                ))
            elif item.get("kind") == "comment":
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                comments.append(RedditComment(
                    reddit_id=item.get("id", ""),
                    parent_id=item.get("postId"),
                    body=item.get("body", ""),
                    author=item.get("author"),
                    score=item.get("score", 0),
                    created_utc=created_utc,
                ))

        logger.info(f"Scraped {len(posts)} posts and {len(comments)} comments")
        return posts, comments

    def recover_from_apify_run(
        self,
        apify_run_id: str
    ) -> Tuple[List[RedditPost], List[RedditComment]]:
        """
        Recover data from an existing Apify run.

        Useful when pipeline fails after scraping - avoids re-running the expensive scrape.

        Args:
            apify_run_id: The Apify run ID (e.g., "FWOdh8fceEdMrRMBs")

        Returns:
            Tuple of (posts, comments)
        """
        logger.info(f"Recovering data from Apify run: {apify_run_id}")

        result = self.apify.get_run_results(apify_run_id)

        posts = []
        comments = []

        for item in result.items:
            if item.get("kind") == "post":
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                posts.append(RedditPost(
                    reddit_id=item.get("id", ""),
                    subreddit=item.get("subreddit", ""),
                    title=item.get("title", ""),
                    body=item.get("body") or item.get("selftext"),
                    author=item.get("author"),
                    url=item.get("url"),
                    score=item.get("score", 0),
                    upvote_ratio=item.get("upvote_ratio", 0.0),
                    num_comments=item.get("num_comments", 0),
                    created_utc=created_utc,
                ))
            elif item.get("kind") == "comment":
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                comments.append(RedditComment(
                    reddit_id=item.get("id", ""),
                    parent_id=item.get("postId"),
                    body=item.get("body", ""),
                    author=item.get("author"),
                    score=item.get("score", 0),
                    created_utc=created_utc,
                ))

        logger.info(f"Recovered {len(posts)} posts and {len(comments)} comments from Apify run {apify_run_id}")
        return posts, comments

    def scrape_by_urls(
        self,
        urls: List[str],
        scrape_comments: bool = True,
        max_comments_per_post: int = 50,
        timeout: int = 600
    ) -> Tuple[List[RedditPost], List[RedditComment]]:
        """
        Scrape specific Reddit posts by URL.

        Uses the Apify actor's URL mode to fetch posts and optionally their comments.
        This is more efficient for two-pass scraping where we've already filtered posts.

        Args:
            urls: List of Reddit post URLs to scrape
            scrape_comments: Whether to scrape comments (default True)
            max_comments_per_post: Max comments per post (default 50)
            timeout: Apify timeout in seconds

        Returns:
            Tuple of (posts, comments)

        Example:
            >>> urls = ["https://reddit.com/r/nutrition/comments/xyz123/..."]
            >>> posts, comments = service.scrape_by_urls(urls, scrape_comments=True)
        """
        if not urls:
            logger.warning("No URLs provided for scraping")
            return [], []

        logger.info(f"Scraping {len(urls)} Reddit URLs with comments={scrape_comments}")

        run_input = {
            "urls": urls,
            "scrapeComments": scrape_comments,
            "maxComments": max_comments_per_post,
        }

        result = self.apify.run_actor(
            actor_id=REDDIT_SCRAPER_ACTOR,
            run_input=run_input,
            timeout=timeout
        )

        posts = []
        comments = []

        for item in result.items:
            if item.get("kind") == "post":
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                posts.append(RedditPost(
                    reddit_id=item.get("id", ""),
                    subreddit=item.get("subreddit", ""),
                    title=item.get("title", ""),
                    body=item.get("body") or item.get("selftext"),
                    author=item.get("author"),
                    url=item.get("url"),
                    score=item.get("score", 0),
                    upvote_ratio=item.get("upvote_ratio", 0.0),
                    num_comments=item.get("num_comments", 0),
                    created_utc=created_utc,
                ))
            elif item.get("kind") == "comment":
                created_utc = None
                if item.get("created_utc"):
                    if isinstance(item["created_utc"], str):
                        created_utc = datetime.fromisoformat(
                            item["created_utc"].replace("Z", "+00:00")
                        )
                    else:
                        created_utc = datetime.fromtimestamp(item["created_utc"])

                comments.append(RedditComment(
                    reddit_id=item.get("id", ""),
                    parent_id=item.get("postId"),
                    body=item.get("body", ""),
                    author=item.get("author"),
                    score=item.get("score", 0),
                    created_utc=created_utc,
                ))

        logger.info(f"Scraped {len(posts)} posts and {len(comments)} comments from {len(urls)} URLs")
        return posts, comments

    # =========================================================================
    # FILTERING (Deterministic)
    # =========================================================================

    def filter_by_engagement(
        self,
        posts: List[RedditPost],
        min_upvotes: int = 20,
        min_comments: int = 5
    ) -> List[RedditPost]:
        """
        Filter posts by engagement thresholds.

        Args:
            posts: List of posts to filter
            min_upvotes: Minimum score (upvotes)
            min_comments: Minimum number of comments

        Returns:
            Filtered list of posts
        """
        filtered = [
            p for p in posts
            if p.score >= min_upvotes and p.num_comments >= min_comments
        ]
        logger.info(
            f"Engagement filter: {len(posts)} -> {len(filtered)} posts "
            f"(min upvotes={min_upvotes}, min comments={min_comments})"
        )
        return filtered

    # =========================================================================
    # LLM SCORING (Claude Sonnet)
    # =========================================================================

    async def score_relevance(
        self,
        posts: List[RedditPost],
        persona_context: Optional[str] = None,
        topic_context: Optional[str] = None,
        threshold: float = 0.6
    ) -> List[RedditPost]:
        """
        Score posts for relevance using Claude Sonnet.

        Args:
            posts: Posts to score
            persona_context: Description of target persona (optional)
            topic_context: Description of topic/domain (optional)
            threshold: Minimum score to keep (0.0-1.0)

        Returns:
            Posts with relevance scores above threshold
        """
        if not posts:
            return []

        logger.info(f"Scoring relevance for {len(posts)} posts")
        results = []

        # Pydantic AI Agent (Reddit/Basic)
        agent = Agent(
            model=Config.get_model("reddit"),
            system_prompt="You are an expert content filter."
        )

        # Process in batches of 10 for efficiency
        for batch in self._batch(posts, 10):
            prompt = self._build_relevance_prompt(batch, persona_context, topic_context)

            result = agent.run_sync(prompt)

            scores = self._parse_batch_scores(result.output, len(batch))

            for post, score_data in zip(batch, scores):
                score = score_data.get("score", 0.0)
                reasoning = score_data.get("reasoning", "")

                post.relevance_score = score
                post.relevance_reasoning = reasoning

                if score >= threshold:
                    results.append(post)

        logger.info(f"Relevance filter: {len(posts)} -> {len(results)} posts (threshold={threshold})")
        return results

    async def filter_signal_from_noise(
        self,
        posts: List[RedditPost],
        threshold: float = 0.5
    ) -> List[RedditPost]:
        """
        Filter signal from noise using Claude Sonnet.

        Removes:
        - Pure humor/memes without substance
        - Off-topic tangents
        - Spam/self-promotion
        - Low-effort posts

        Args:
            posts: Posts to filter
            threshold: Minimum signal score to keep (0.0-1.0)

        Returns:
            High-signal posts only
        """
        if not posts:
            return []

        logger.info(f"Filtering signal for {len(posts)} posts")
        results = []

        # Pydantic AI Agent (Reddit/Basic)
        agent = Agent(
            model=Config.get_model("reddit"),
            system_prompt="You are an expert content filter."
        )

        for batch in self._batch(posts, 10):
            prompt = self._build_signal_prompt(batch)

            result = await agent.run(prompt)
            
            # Using result.output instead of response.content
            scores = self._parse_batch_scores(result.output, len(batch))

            for post, score_data in zip(batch, scores):
                score = score_data.get("score", 0.0)
                reasoning = score_data.get("reasoning", "")

                post.signal_score = score
                post.signal_reasoning = reasoning

                if score >= threshold:
                    results.append(post)

        logger.info(f"Signal filter: {len(posts)} -> {len(results)} posts (threshold={threshold})")
        return results

    async def score_buyer_intent(
        self,
        posts: List[RedditPost]
    ) -> List[RedditPost]:
        """
        Score buyer intent/sophistication using Claude Sonnet.

        Higher scores for:
        - Comparison shopping language
        - Specific feature requirements
        - Budget discussions
        - Purchase timeline mentions
        - Past purchase experiences

        Args:
            posts: Posts to score

        Returns:
            All posts with intent scores added
        """
        if not posts:
            return []

        logger.info(f"Scoring buyer intent for {len(posts)} posts")

        # Pydantic AI Agent (Reddit/Basic)
        agent = Agent(
            model=Config.get_model("reddit"),
            system_prompt="You are an expert intent analyst."
        )

        for batch in self._batch(posts, 10):
            prompt = self._build_intent_prompt(batch)

            result = await agent.run(prompt)
            scores = self._parse_batch_scores(result.output, len(batch))

            for post, score_data in zip(batch, scores):
                post.intent_score = score_data.get("score", 0.0)
                post.intent_reasoning = score_data.get("reasoning", "")

        return posts

    def select_top_percentile(
        self,
        posts: List[RedditPost],
        percentile: float = 0.20
    ) -> List[RedditPost]:
        """
        Select top X% of posts by combined score.

        Args:
            posts: Posts with scores
            percentile: Top percentage to keep (0.01-1.0)

        Returns:
            Top posts by combined score
        """
        if not posts:
            return []

        # Calculate combined score (weighted average)
        for post in posts:
            scores = []
            if post.relevance_score is not None:
                scores.append(post.relevance_score * 0.4)  # 40% weight
            if post.signal_score is not None:
                scores.append(post.signal_score * 0.3)  # 30% weight
            if post.intent_score is not None:
                scores.append(post.intent_score * 0.3)  # 30% weight

            if scores:
                post.combined_score = sum(scores) / (0.4 + 0.3 + 0.3)
            else:
                post.combined_score = 0.0

        # Sort by combined score
        sorted_posts = sorted(posts, key=lambda p: p.combined_score or 0, reverse=True)

        # Select top percentile
        top_count = max(1, int(len(sorted_posts) * percentile))
        top_posts = sorted_posts[:top_count]

        logger.info(f"Top selection: {len(posts)} -> {top_count} posts (top {percentile*100:.0f}%)")
        return top_posts

    # =========================================================================
    # CATEGORIZATION & EXTRACTION (Claude Opus 4.5)
    # =========================================================================

    async def categorize_and_extract_quotes(
        self,
        posts: List[RedditPost],
        brand_context: Optional[str] = None,
        product_context: Optional[str] = None
    ) -> Dict[SentimentCategory, List[RedditSentimentQuote]]:
        """
        Categorize posts into 6 sentiment buckets and extract quotes.

        Uses Claude Opus 4.5 for deep extraction.

        Args:
            posts: Posts to analyze
            brand_context: Optional brand description for context
            product_context: Optional product/category description

        Returns:
            Dict mapping category to list of extracted quotes
        """
        if not posts:
            return {cat: [] for cat in SentimentCategory}

        logger.info(f"Categorizing and extracting quotes from {len(posts)} posts")

        all_quotes: Dict[SentimentCategory, List[RedditSentimentQuote]] = {
            cat: [] for cat in SentimentCategory
        }

        # Pydantic AI Agent (Complex/Opus)
        agent = Agent(
            model=Config.get_model("complex"),
            system_prompt="You are an expert sentiment analyst. Return ONLY valid JSON."
        )

        # Process in smaller batches for deeper analysis
        for batch in self._batch(posts, 5):
            prompt = self._build_extraction_prompt(batch, brand_context, product_context)

            result = await agent.run(prompt)

            extracted = self._parse_extraction_response(result.output, batch)

            for category, quotes in extracted.items():
                all_quotes[category].extend(quotes)

        total_quotes = sum(len(q) for q in all_quotes.values())
        logger.info(f"Extracted {total_quotes} quotes across {len(SentimentCategory)} categories")

        return all_quotes

    # =========================================================================
    # PERSONA SYNC
    # =========================================================================

    def sync_quotes_to_persona(
        self,
        quotes: Dict[SentimentCategory, List[RedditSentimentQuote]],
        persona_id: UUID
    ) -> Dict[str, int]:
        """
        Sync extracted quotes to persona's sentiment fields.

        Category mapping:
        - PAIN_POINT -> pain_points (DomainSentiment)
        - DESIRED_OUTCOME -> outcomes_jtbd (DomainSentiment)
        - BUYING_OBJECTION -> buying_objections (DomainSentiment)
        - FAILED_SOLUTION -> failed_solutions (List)
        - DESIRED_FEATURE -> desired_features (List)
        - FAMILIAR_SOLUTION -> familiar_promises (List)

        Args:
            quotes: Dict of quotes by category
            persona_id: Target persona UUID

        Returns:
            Dict of {field_name: quotes_added_count}
        """
        logger.info(f"Syncing quotes to persona {persona_id}")

        # Get current persona data
        result = self.supabase.table("personas_4d").select(
            "pain_points, outcomes_jtbd, buying_objections, "
            "failed_solutions, desired_features, familiar_promises"
        ).eq("id", str(persona_id)).execute()

        if not result.data:
            raise ValueError(f"Persona not found: {persona_id}")

        persona = result.data[0]
        updates = {}
        counts = {}

        # Map categories to persona fields
        # (field_name, is_domain_sentiment)
        mapping = {
            SentimentCategory.PAIN_POINT: ("pain_points", True),
            SentimentCategory.DESIRED_OUTCOME: ("outcomes_jtbd", True),
            SentimentCategory.BUYING_OBJECTION: ("buying_objections", True),
            SentimentCategory.FAILED_SOLUTION: ("failed_solutions", False),
            SentimentCategory.DESIRED_FEATURE: ("desired_features", False),
            SentimentCategory.FAMILIAR_SOLUTION: ("familiar_promises", False),
        }

        for category, category_quotes in quotes.items():
            if not category_quotes:
                continue

            field_name, is_domain_sentiment = mapping[category]
            current = persona.get(field_name) or {}

            # Parse if stored as string
            if isinstance(current, str):
                try:
                    current = json.loads(current)
                except json.JSONDecodeError:
                    current = {} if is_domain_sentiment else []

            if is_domain_sentiment:
                # DomainSentiment structure: {emotional: [], social: [], functional: []}
                current = current or {"emotional": [], "social": [], "functional": []}

                for quote in category_quotes:
                    subtype = quote.sentiment_subtype or "functional"
                    if subtype not in current:
                        current[subtype] = []
                    if quote.quote_text not in current[subtype]:
                        current[subtype].append(quote.quote_text)
            else:
                # Simple list
                current = current if isinstance(current, list) else []

                for quote in category_quotes:
                    if quote.quote_text not in current:
                        current.append(quote.quote_text)

            updates[field_name] = current
            counts[field_name] = len(category_quotes)

        # Update persona
        if updates:
            self.supabase.table("personas_4d").update(updates).eq(
                "id", str(persona_id)
            ).execute()
            logger.info(f"Updated persona fields: {list(updates.keys())}")

        return counts

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def create_run(
        self,
        config: RedditScrapeConfig,
        brand_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        persona_id: Optional[UUID] = None,
        persona_context: Optional[str] = None,
        topic_context: Optional[str] = None,
        brand_context: Optional[str] = None,
        product_context: Optional[str] = None
    ) -> UUID:
        """
        Create a new scrape run record.

        Args:
            config: Scrape configuration
            brand_id: Optional brand association
            product_id: Optional product association
            persona_id: Optional persona association
            *_context: Context strings for LLM prompts

        Returns:
            UUID of created run
        """
        data = {
            "search_queries": config.search_queries,
            "subreddits": config.subreddits,
            "timeframe": config.timeframe,
            "sort_by": config.sort_by,
            "max_posts": config.max_posts,
            "min_upvotes": config.min_upvotes,
            "min_comments": config.min_comments,
            "status": "pending",
            "current_step": "created",
        }

        if brand_id:
            data["brand_id"] = str(brand_id)
        if product_id:
            data["product_id"] = str(product_id)
        if persona_id:
            data["persona_id"] = str(persona_id)
        if persona_context:
            data["persona_context"] = persona_context
        if topic_context:
            data["topic_context"] = topic_context
        if brand_context:
            data["brand_context"] = brand_context
        if product_context:
            data["product_context"] = product_context

        result = self.supabase.table("reddit_scrape_runs").insert(data).execute()
        run_id = UUID(result.data[0]["id"])
        logger.info(f"Created scrape run: {run_id}")
        return run_id

    def update_run_status(
        self,
        run_id: UUID,
        status: str,
        current_step: Optional[str] = None,
        error: Optional[str] = None,
        **metrics
    ):
        """Update run status and metrics."""
        data = {"status": status}
        if current_step:
            data["current_step"] = current_step
        if error:
            data["error"] = error
        data.update(metrics)

        if status == "completed":
            data["completed_at"] = datetime.utcnow().isoformat()

        self.supabase.table("reddit_scrape_runs").update(data).eq(
            "id", str(run_id)
        ).execute()

    def save_posts(
        self,
        run_id: UUID,
        posts: List[RedditPost],
        brand_id: Optional[UUID] = None
    ) -> List[UUID]:
        """Save posts to database and return their UUIDs."""
        if not posts:
            return []

        saved_ids = []
        for post in posts:
            data = {
                "run_id": str(run_id),
                "reddit_id": post.reddit_id,
                "subreddit": post.subreddit,
                "title": post.title,
                "body": post.body,
                "author": post.author,
                "url": post.url,
                "score": post.score,
                "upvote_ratio": post.upvote_ratio,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc.isoformat() if post.created_utc else None,
                "relevance_score": post.relevance_score,
                "relevance_reasoning": post.relevance_reasoning,
                "signal_score": post.signal_score,
                "signal_reasoning": post.signal_reasoning,
                "intent_score": post.intent_score,
                "intent_reasoning": post.intent_reasoning,
                "combined_score": post.combined_score,
            }

            if brand_id:
                data["brand_id"] = str(brand_id)

            result = self.supabase.table("reddit_posts").upsert(
                data, on_conflict="run_id,reddit_id"
            ).execute()

            if result.data:
                post.id = UUID(result.data[0]["id"])
                saved_ids.append(post.id)

        logger.info(f"Saved {len(saved_ids)} posts to database")
        return saved_ids

    def save_quotes(
        self,
        run_id: UUID,
        quotes: Dict[SentimentCategory, List[RedditSentimentQuote]],
        brand_id: Optional[UUID] = None
    ) -> int:
        """Save quotes to database."""
        total_saved = 0

        for category, category_quotes in quotes.items():
            for quote in category_quotes:
                data = {
                    "run_id": str(run_id),
                    "post_id": str(quote.post_id) if quote.post_id else None,
                    "comment_id": str(quote.comment_id) if quote.comment_id else None,
                    "quote_text": quote.quote_text,
                    "source_type": quote.source_type,
                    "sentiment_category": category.value,
                    "sentiment_subtype": quote.sentiment_subtype,
                    "confidence_score": quote.confidence_score,
                    "extraction_reasoning": quote.extraction_reasoning,
                }

                if brand_id:
                    data["brand_id"] = str(brand_id)

                self.supabase.table("reddit_sentiment_quotes").insert(data).execute()
                total_saved += 1

        logger.info(f"Saved {total_saved} quotes to database")
        return total_saved

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _batch(self, items: List, size: int):
        """Yield batches of items."""
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _build_relevance_prompt(
        self,
        posts: List[RedditPost],
        persona_context: Optional[str],
        topic_context: Optional[str]
    ) -> str:
        """Build the relevance scoring prompt."""
        posts_json = [
            {"index": i, "title": p.title, "body": p.body[:500] if p.body else None}
            for i, p in enumerate(posts)
        ]

        return f"""You are a content relevance scorer for market research.

CONTEXT:
- Target Persona: {persona_context or "General consumer"}
- Topic/Domain: {topic_context or "General product research"}

TASK:
Score each post's relevance to the persona and topic on a scale of 0.0 to 1.0.

POSTS TO SCORE:
{json.dumps(posts_json, indent=2)}

RETURN JSON ARRAY (one object per post, in order):
[
  {{"index": 0, "score": 0.85, "reasoning": "Directly discusses target audience pain point..."}},
  ...
]

Be strict - only high scores (0.7+) for clear relevance to BOTH persona AND topic."""

    def _build_signal_prompt(self, posts: List[RedditPost]) -> str:
        """Build the signal vs noise filtering prompt."""
        posts_json = [
            {"index": i, "title": p.title, "body": p.body[:500] if p.body else None}
            for i, p in enumerate(posts)
        ]

        return f"""You are a signal vs noise classifier for market research.

HIGH SIGNAL content contains:
- Personal experiences with products/problems
- Genuine frustrations or pain points
- Product recommendations or warnings
- Detailed descriptions of what worked/didn't work
- Comparison shopping discussions

NOISE includes:
- Jokes, memes, off-topic tangents
- Promotional/spam content
- Generic questions without context
- Low-effort responses
- Pure entertainment without insight

POSTS TO CLASSIFY:
{json.dumps(posts_json, indent=2)}

RETURN JSON ARRAY (one object per post, in order):
[
  {{"index": 0, "score": 0.9, "reasoning": "Detailed first-hand experience with product..."}},
  ...
]

Score 0.0-1.0 where 1.0 is pure signal, 0.0 is pure noise."""

    def _build_intent_prompt(self, posts: List[RedditPost]) -> str:
        """Build the buyer intent scoring prompt."""
        posts_json = [
            {"index": i, "title": p.title, "body": p.body[:500] if p.body else None}
            for i, p in enumerate(posts)
        ]

        return f"""You are a buyer intent analyst for market research.

Score each post for buyer sophistication/intent indicators:

HIGH INTENT signals (score 0.7+):
- Has purchased products in this category
- Compared multiple brands/options
- Mentions specific features they need
- Discusses budget/price considerations
- Has timeline for purchase decision
- Tried DIY solutions or workarounds

LOW INTENT signals (score 0.3-):
- Just browsing/curious
- No indication of purchase consideration
- Purely academic interest

POSTS TO SCORE:
{json.dumps(posts_json, indent=2)}

RETURN JSON ARRAY (one object per post, in order):
[
  {{"index": 0, "score": 0.8, "reasoning": "Mentions trying 3 brands, asking for recommendations..."}},
  ...
]"""

    def _build_extraction_prompt(
        self,
        posts: List[RedditPost],
        brand_context: Optional[str],
        product_context: Optional[str]
    ) -> str:
        """Build the quote extraction prompt."""
        posts_json = [
            {
                "index": i,
                "reddit_id": p.reddit_id,
                "title": p.title,
                "body": p.body[:1500] if p.body else None,
                "subreddit": p.subreddit
            }
            for i, p in enumerate(posts)
        ]

        return f"""You are an expert at extracting customer insights from Reddit discussions.

CONTEXT:
{f"Brand: {brand_context}" if brand_context else "General market research"}
{f"Product Category: {product_context}" if product_context else ""}

TASK:
Analyze these Reddit posts and extract VERBATIM quotes that fit into these 6 categories:

1. PAIN_POINT - Problems, frustrations, struggles they're experiencing
   - Sub-types: emotional (feelings), social (relationships/status), functional (practical issues)

2. DESIRED_OUTCOME - What success/resolution looks like to them
   - Sub-types: emotional, social, functional

3. BUYING_OBJECTION - Reasons they hesitate to buy/try solutions
   - Sub-types: emotional, social, functional

4. FAILED_SOLUTION - Products/methods they've tried that didn't work

5. DESIRED_FEATURE - Specific features/capabilities they want

6. FAMILIAR_SOLUTION - Solutions/brands they already know about

POSTS TO ANALYZE:
{json.dumps(posts_json, indent=2)}

RETURN JSON (extract 2-5 quotes per category where applicable):
{{
  "PAIN_POINT": [
    {{
      "quote": "exact verbatim quote from post",
      "post_index": 0,
      "source_type": "post_body",
      "subtype": "emotional",
      "confidence": 0.9,
      "reasoning": "why this fits the category"
    }}
  ],
  "DESIRED_OUTCOME": [...],
  "BUYING_OBJECTION": [...],
  "FAILED_SOLUTION": [...],
  "DESIRED_FEATURE": [...],
  "FAMILIAR_SOLUTION": [...]
}}

Extract only genuine, insightful quotes - quality over quantity."""

    def _parse_batch_scores(
        self,
        response_text: str,
        expected_count: int
    ) -> List[Dict[str, Any]]:
        """Parse JSON array of scores from LLM response."""
        try:
            # Try to extract JSON from response
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            scores = json.loads(text)

            if isinstance(scores, list) and len(scores) >= expected_count:
                return scores[:expected_count]

            # Pad with zeros if needed
            while len(scores) < expected_count:
                scores.append({"score": 0.0, "reasoning": "Parse error"})

            return scores

        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse scores: {e}")
            return [{"score": 0.0, "reasoning": "Parse error"} for _ in range(expected_count)]

    def _parse_extraction_response(
        self,
        response_text: str,
        posts: List[RedditPost]
    ) -> Dict[SentimentCategory, List[RedditSentimentQuote]]:
        """Parse extraction response into quotes by category."""
        result: Dict[SentimentCategory, List[RedditSentimentQuote]] = {
            cat: [] for cat in SentimentCategory
        }

        try:
            # Try to extract JSON from response
            text = response_text.strip()

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text)

            for category in SentimentCategory:
                category_key = category.value
                if category_key in data:
                    for item in data[category_key]:
                        # Get post ID from index
                        post_index = item.get("post_index", 0)
                        post_id = None
                        if 0 <= post_index < len(posts):
                            post_id = posts[post_index].id

                        quote = RedditSentimentQuote(
                            post_id=post_id,
                            quote_text=item.get("quote", ""),
                            source_type=item.get("source_type", "post_body"),
                            sentiment_category=category,
                            sentiment_subtype=item.get("subtype"),
                            confidence_score=item.get("confidence", 0.8),
                            extraction_reasoning=item.get("reasoning"),
                        )
                        result[category].append(quote)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse extraction response: {e}")

        return result

    def estimate_cost(
        self,
        posts_count: int,
        apify_cost_per_1000: float = 1.50
    ) -> Tuple[float, float]:
        """
        Estimate costs for a run.

        Args:
            posts_count: Number of posts to process
            apify_cost_per_1000: Apify cost per 1000 items

        Returns:
            Tuple of (apify_cost, llm_cost_estimate)
        """
        # Apify cost
        apify_cost = (posts_count / 1000) * apify_cost_per_1000

        # LLM cost estimate (rough)
        # Assume ~500 tokens per post for input, ~100 tokens output per batch
        # 3 Sonnet passes + 1 Opus pass
        input_tokens = posts_count * 500
        output_tokens = (posts_count / 10) * 100  # batches of 10

        sonnet_cost = (input_tokens * 3 / 1_000_000) * SONNET_INPUT_COST
        sonnet_cost += (output_tokens * 3 / 1_000_000) * SONNET_OUTPUT_COST

        opus_cost = (input_tokens / 1_000_000) * OPUS_INPUT_COST
        opus_cost += (output_tokens * 4 / 1_000_000) * OPUS_OUTPUT_COST  # More output for extraction

        llm_cost = sonnet_cost + opus_cost

        return apify_cost, llm_cost

    # =========================================================================
    # BELIEF EXTRACTION METHODS
    # =========================================================================

    async def extract_belief_signals(
        self,
        posts: List[RedditPost],
        signal_types: Optional[List[str]] = None,
        topic_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract belief-relevant signals from Reddit posts for the belief pipeline.

        This is specifically designed for the belief_first_reverse_engineer pipeline
        to populate Research Canvas sections 1-9.

        Args:
            posts: List of RedditPost objects to analyze
            signal_types: Types of signals to extract:
                - "pain": Pain points and symptoms
                - "solutions": Solutions attempted and outcomes
                - "patterns": Pattern detection (triggers, improves, etc.)
                - "language": Customer terminology
                - "jtbd": JTBD candidates
            topic_context: Context about the topic/product

        Returns:
            Dict with extracted signals structured for RedditResearchBundle:
            {
                "posts_analyzed_count": int,
                "comments_analyzed_count": int,
                "extracted_pain": [...],
                "extracted_solutions_attempted": [...],
                "pattern_detection": {...},
                "extracted_language_bank": {...},
                "jtbd_candidates": {...},
                "hypothesis_support_scores": [...]
            }
        """
        if signal_types is None:
            signal_types = ["pain", "solutions", "patterns", "language", "jtbd"]

        result = {
            "posts_analyzed_count": len(posts),
            "comments_analyzed_count": 0,
            "extracted_pain": [],
            "extracted_solutions_attempted": [],
            "pattern_detection": {
                "triggers": [],
                "worsens": [],
                "improves": [],
                "helps": [],
                "fails": [],
            },
            "extracted_language_bank": {},
            "jtbd_candidates": {
                "functional": [],
                "emotional": [],
                "identity": [],
            },
            "hypothesis_support_scores": [],
        }

        if not posts:
            return result

        # Process in batches
        batch_size = 5
        for batch in self._batch(posts, batch_size):
            try:
                batch_result = await self._extract_belief_signals_batch(
                    batch, signal_types, topic_context
                )
                self._merge_belief_signals(result, batch_result)
            except Exception as e:
                logger.warning(f"Failed to extract belief signals from batch: {e}")

        return result

    async def _extract_belief_signals_batch(
        self,
        posts: List[RedditPost],
        signal_types: List[str],
        topic_context: Optional[str],
    ) -> Dict[str, Any]:
        """Extract belief signals from a batch of posts using LLM."""
        prompt = self._build_belief_extraction_prompt(posts, signal_types, topic_context)

        # Use Opus for deep extraction
        agent = Agent(
            DEEP_MODEL,
            system_prompt="You are an expert at extracting belief-relevant signals from Reddit discussions for marketing research."
        )

        response = await agent.run(prompt)

        # Parse the response
        return self._parse_belief_extraction_response(response.data)

    def _build_belief_extraction_prompt(
        self,
        posts: List[RedditPost],
        signal_types: List[str],
        topic_context: Optional[str],
    ) -> str:
        """Build prompt for belief signal extraction."""
        posts_json = [
            {
                "index": i,
                "title": p.title,
                "body": p.body[:1500] if p.body else None,
                "subreddit": p.subreddit,
            }
            for i, p in enumerate(posts)
        ]

        signal_instructions = []

        if "pain" in signal_types:
            signal_instructions.append("""
1. **Pain Signals**: Extract specific symptoms, frustrations, complaints
   - Physical symptoms with specificity ("every morning I wake up with...")
   - Emotional frustrations ("I'm so tired of...")
   - Behavioral workarounds ("I have to...")""")

        if "solutions" in signal_types:
            signal_instructions.append("""
2. **Solutions Attempted**: What they've tried and outcomes
   - What worked briefly ("X helped at first but...")
   - What stopped working ("used to work, now...")
   - What never worked ("tried X, complete waste")
   - Why they think it failed ("I think it didn't work because...")""")

        if "patterns" in signal_types:
            signal_instructions.append("""
3. **Pattern Signals**: Recurring sequences and correlations
   - Triggers: What makes it worse ("every time I...", "whenever...")
   - Improvers: What helps temporarily ("the only thing that helps...")
   - Timing patterns ("worse in the morning", "after eating...")""")

        if "language" in signal_types:
            signal_instructions.append("""
4. **Language Bank**: Customer terminology
   - How they describe the problem (their exact words)
   - Metaphors they use ("feels like...", "it's like...")
   - Emotional intensity words""")

        if "jtbd" in signal_types:
            signal_instructions.append("""
5. **JTBD Candidates**: Desired progress
   - Functional: What they want to accomplish ("I just want to...")
   - Emotional: How they want to feel ("I want to feel...")
   - Identity: Who they want to become ("I want to be someone who...")""")

        return f"""CONTEXT:
{f"Topic: {topic_context}" if topic_context else "General market research"}

TASK:
Analyze these Reddit posts and extract belief-relevant signals for marketing research.

WHAT TO EXTRACT:
{''.join(signal_instructions)}

POSTS TO ANALYZE:
{json.dumps(posts_json, indent=2)}

RETURN JSON:
{{
    "extracted_pain": [
        {{"signal": "exact quote or paraphrase", "signal_type": "physical|emotional|behavioral", "post_index": 0, "confidence": 0.9}}
    ],
    "extracted_solutions_attempted": [
        {{"signal": "what they tried", "outcome": "worked_briefly|stopped_working|never_worked", "why_failed": "their explanation", "post_index": 0}}
    ],
    "pattern_detection": {{
        "triggers": ["trigger 1", "trigger 2"],
        "worsens": ["factor 1"],
        "improves": ["factor 1"],
        "helps": ["thing 1"],
        "fails": ["thing 1"]
    }},
    "extracted_language_bank": {{
        "symptom_name": ["phrase 1", "phrase 2"]
    }},
    "jtbd_candidates": {{
        "functional": ["want 1"],
        "emotional": ["feeling 1"],
        "identity": ["become 1"]
    }}
}}

Focus on SPECIFIC, ACTIONABLE insights - not generic observations."""

    def _parse_belief_extraction_response(
        self,
        response_text: str
    ) -> Dict[str, Any]:
        """Parse belief extraction LLM response."""
        try:
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            return json.loads(text)

        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse belief extraction response: {e}")
            return {
                "extracted_pain": [],
                "extracted_solutions_attempted": [],
                "pattern_detection": {},
                "extracted_language_bank": {},
                "jtbd_candidates": {},
            }

    def _merge_belief_signals(
        self,
        result: Dict[str, Any],
        batch_result: Dict[str, Any]
    ) -> None:
        """Merge batch results into main result dict."""
        # Merge pain signals
        result["extracted_pain"].extend(
            batch_result.get("extracted_pain", [])
        )

        # Merge solutions
        result["extracted_solutions_attempted"].extend(
            batch_result.get("extracted_solutions_attempted", [])
        )

        # Merge patterns
        batch_patterns = batch_result.get("pattern_detection", {})
        for key in ["triggers", "worsens", "improves", "helps", "fails"]:
            result["pattern_detection"][key].extend(
                batch_patterns.get(key, [])
            )

        # Merge language bank
        batch_language = batch_result.get("extracted_language_bank", {})
        for symptom, phrases in batch_language.items():
            if symptom not in result["extracted_language_bank"]:
                result["extracted_language_bank"][symptom] = []
            result["extracted_language_bank"][symptom].extend(phrases)

        # Merge JTBD
        batch_jtbd = batch_result.get("jtbd_candidates", {})
        for category in ["functional", "emotional", "identity"]:
            result["jtbd_candidates"][category].extend(
                batch_jtbd.get(category, [])
            )

    async def search_for_belief_signals(
        self,
        subreddits: List[str],
        search_queries: List[str],
        signal_types: Optional[List[str]] = None,
        limit: int = 50,
        topic_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Combined scrape + extract method for belief pipeline.

        Convenience method that:
        1. Scrapes Reddit using provided queries/subreddits
        2. Filters by engagement
        3. Extracts belief signals

        Args:
            subreddits: List of subreddits to search
            search_queries: Search terms
            signal_types: Types of signals to extract
            limit: Max posts to analyze
            topic_context: Context about the topic

        Returns:
            RedditResearchBundle-compatible dict with all signals
        """
        # Build scrape config
        config = RedditScrapeConfig(
            search_queries=search_queries,
            subreddits=subreddits,
            max_posts=limit * 2,  # Get extra, filter down
            timeframe="year",
            min_upvotes=5,
            min_comments=2,
            scrape_comments=False,  # Just posts for speed
        )

        # Scrape
        posts, _ = self.scrape_reddit(config)
        logger.info(f"Scraped {len(posts)} posts from Reddit")

        # Filter by engagement
        filtered = self.filter_by_engagement(posts, min_upvotes=5, min_comments=2)
        logger.info(f"Filtered to {len(filtered)} posts by engagement")

        # Limit
        if len(filtered) > limit:
            filtered = filtered[:limit]

        # Extract belief signals
        result = await self.extract_belief_signals(
            filtered,
            signal_types=signal_types,
            topic_context=topic_context,
        )

        # Add query metadata
        result["queries_run"] = [
            {"subreddit": sub, "search_term": query}
            for sub in subreddits
            for query in search_queries
        ]

        return result
