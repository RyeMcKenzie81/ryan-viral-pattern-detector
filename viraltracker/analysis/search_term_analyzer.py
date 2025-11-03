"""
Search Term Analyzer - Find optimal Twitter search terms

Analyzes search terms across multiple dimensions:
- Score quality (green/yellow/red ratio)
- Conversation volume (freshness)
- Virality potential (views)
- Cost efficiency
- Topic distribution

This analyzer is project-specific and taxonomy-driven. A "green" tweet means
it semantically matches the project's taxonomy topics.
"""

import json
import logging
import statistics
import asyncio
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

from ..core.database import get_supabase_client
from ..core.config import load_finder_config
from ..core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from ..scrapers.twitter import TwitterScraper
from ..generation.comment_finder import score_tweet, TweetMetrics
from ..generation.async_comment_generator import generate_comments_async
from ..generation.comment_generator import save_scores_only_to_db


logger = logging.getLogger(__name__)


@dataclass
class SearchTermMetrics:
    """Metrics for a search term analysis"""
    project: str
    search_term: str
    analyzed_at: str
    tweets_analyzed: int

    # Tracking IDs
    analysis_run_id: str  # UUID from analysis_runs table
    apify_run_id: Optional[str]  # Apify actor run ID
    apify_dataset_id: Optional[str]  # Apify dataset ID

    # Score distribution
    green_count: int
    green_percentage: float
    green_avg_score: float
    yellow_count: int
    yellow_percentage: float
    yellow_avg_score: float
    red_count: int
    red_percentage: float
    red_avg_score: float

    # Freshness
    last_48h_count: int
    last_48h_percentage: float
    conversations_per_day: float
    tweets_per_24h: float  # Average tweets per 24 hours

    # Virality
    avg_views: float
    median_views: float
    top_10_percent_avg_views: float
    tweets_with_10k_plus_views: int

    # Relevance-only scores (semantic similarity, not composite)
    avg_relevance_score: float
    green_avg_relevance: float
    yellow_avg_relevance: float
    red_avg_relevance: float

    # Topic distribution
    topic_distribution: Dict[str, int]

    # Cost efficiency
    total_cost_usd: float
    cost_per_green: float
    greens_per_dollar: float

    # Recommendation
    recommendation: str
    confidence: str
    reasoning: str


class SearchTermAnalyzer:
    """
    Analyze Twitter search terms for engagement potential.

    This tool helps find optimal search terms by:
    1. Scraping tweets for the search term
    2. Scoring tweets against project taxonomy
    3. Calculating quality, volume, and cost metrics
    4. Generating recommendations
    """

    def __init__(self, project_slug: str):
        """
        Initialize analyzer for a project.

        Args:
            project_slug: Project identifier (e.g., 'yakety-pack-instagram')
        """
        self.project_slug = project_slug
        self.db = get_supabase_client()

        # Load project config
        self.config = load_finder_config(project_slug)

        # Get project ID
        project_result = self.db.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not project_result.data:
            raise ValueError(f"Project '{project_slug}' not found in database")

        self.project_id = project_result.data['id']

        # Initialize embedder
        self.embedder = Embedder()

        # Load taxonomy embeddings
        self.taxonomy_embeddings = load_taxonomy_embeddings_incremental(
            project_slug,
            self.config.taxonomy,
            self.embedder
        )

    def analyze(
        self,
        search_term: str,
        count: int = 1000,
        min_likes: int = 10,
        days_back: int = 7,
        batch_size: int = 10,
        skip_comments: bool = False,
        progress_callback: Optional[callable] = None
    ) -> SearchTermMetrics:
        """
        Run complete analysis on a search term.

        Args:
            search_term: Twitter search term to analyze
            count: Number of tweets to analyze (default: 1000)
            min_likes: Minimum likes filter (default: 10)
            days_back: Time window in days (default: 7)
            batch_size: Concurrent requests for comment generation (default: 10)
            skip_comments: Skip comment generation for faster analysis (default: False)
            progress_callback: Optional callback for progress updates

        Returns:
            SearchTermMetrics with complete analysis
        """
        logger.info(f"Starting analysis for search term: '{search_term}'")

        # Step 0: Create analysis run record
        run_id = str(uuid.uuid4())
        started_at = datetime.now()

        self.db.table('analysis_runs').insert({
            'id': run_id,
            'project_id': self.project_id,
            'search_term': search_term,
            'tweets_requested': count,
            'min_likes': min_likes,
            'days_back': days_back,
            'started_at': started_at.isoformat(),
            'status': 'running'
        }).execute()

        logger.info(f"Created analysis run: {run_id}")

        try:
            # Step 1: Scrape tweets
            if progress_callback:
                progress_callback("scraping", 0, count)

            tweets, apify_run_id, apify_dataset_id = self._scrape_tweets(search_term, count, min_likes, days_back)

            if not tweets:
                raise ValueError(f"No tweets found for search term '{search_term}'")

            logger.info(f"Scraped {len(tweets)} tweets")

            # Update run record with Apify IDs
            self.db.table('analysis_runs').update({
                'apify_run_id': apify_run_id,
                'apify_dataset_id': apify_dataset_id,
                'tweets_analyzed': len(tweets)
            }).eq('id', run_id).execute()

            # Step 2: Embed tweets
            if progress_callback:
                progress_callback("embedding", len(tweets), count)

            tweet_embeddings = self._embed_tweets(tweets)

            # Step 3: Score tweets
            if progress_callback:
                progress_callback("scoring", len(tweets), count)

            scored_tweets = self._score_tweets(tweets, tweet_embeddings)

            # Step 4: Generate comments (includes API cost tracking)
            if skip_comments:
                generation_stats = {'total_cost': 0.0}
                logger.info("Skipping comment generation (--skip-comments flag)")
                # Save scores to database for later comment generation
                if progress_callback:
                    progress_callback("saving_scores", 0, len(scored_tweets))
                self._save_scores_only(scored_tweets)
            else:
                if progress_callback:
                    progress_callback("generating", 0, len(scored_tweets))

                generation_stats = self._generate_comments(scored_tweets, batch_size, progress_callback)

            # Step 5: Calculate metrics
            if progress_callback:
                progress_callback("analyzing", len(scored_tweets), len(scored_tweets))

            metrics = self._calculate_metrics(
                search_term,
                tweets,
                scored_tweets,
                generation_stats,
                run_id,
                apify_run_id,
                apify_dataset_id
            )

            # Step 6: Add recommendation
            metrics = self._add_recommendation(metrics)

            # Step 7: Update run record with completion status
            self.db.table('analysis_runs').update({
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'green_count': metrics.green_count,
                'yellow_count': metrics.yellow_count,
                'red_count': metrics.red_count,
                'total_cost_usd': metrics.total_cost_usd
            }).eq('id', run_id).execute()

            logger.info(f"Analysis complete: {metrics.green_percentage:.1f}% green, recommendation: {metrics.recommendation}")

            return metrics

        except Exception as e:
            # Update run record with error status
            self.db.table('analysis_runs').update({
                'status': 'failed',
                'completed_at': datetime.now().isoformat(),
                'error_message': str(e)
            }).eq('id', run_id).execute()

            logger.error(f"Analysis failed: {e}")
            raise

    def _scrape_tweets(
        self,
        search_term: str,
        count: int,
        min_likes: int,
        days_back: int
    ) -> tuple[List[TweetMetrics], Optional[str], Optional[str]]:
        """
        Scrape tweets using existing Twitter scraper.

        Args:
            search_term: Search term
            count: Number of tweets
            min_likes: Minimum likes filter
            days_back: Time window

        Returns:
            Tuple of (tweets, apify_run_id, apify_dataset_id)
        """
        scraper = TwitterScraper()

        # Scrape search (this saves to DB)
        scrape_start_time = datetime.now()
        scrape_result = scraper.scrape_search(
            search_terms=[search_term],
            max_tweets=count,
            min_likes=min_likes,
            days_back=days_back,
            sort='Latest',
            language='en',
            project_slug=self.project_slug
        )

        # Extract Apify IDs from result
        apify_run_id = scrape_result.get('apify_run_id')
        apify_dataset_id = scrape_result.get('apify_dataset_id')

        # Fetch tweets from database
        # BUG FIX: Only query tweets from THIS scrape by filtering on updated_at timestamp
        # Tweets are upserted with updated_at set to current time, so we can grab only
        # tweets that were just saved (last 5 minutes)
        # This ensures each analysis uses only tweets from its specific search term
        cutoff_date = scrape_start_time - timedelta(minutes=1)

        # Get Twitter platform ID
        platform_result = self.db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
        if not platform_result.data:
            raise ValueError("Twitter platform not found in database")

        platform_id = platform_result.data['id']

        # Query tweets with proper join to project
        # Use updated_at to get only freshly scraped tweets
        result = self.db.table('posts')\
            .select('post_id, caption, posted_at, views, likes, comments, shares, accounts(platform_username, follower_count), project_posts!inner(project_id), updated_at')\
            .eq('platform_id', platform_id)\
            .eq('project_posts.project_id', self.project_id)\
            .gte('updated_at', cutoff_date.isoformat())\
            .order('updated_at', desc=True)\
            .limit(count)\
            .execute()

        if not result.data:
            return [], apify_run_id, apify_dataset_id

        # Convert to TweetMetrics objects
        tweets = []
        for row in result.data:
            account_data = row.get('accounts', {})

            tweet = TweetMetrics(
                tweet_id=row['post_id'],
                text=row['caption'] or '',
                author_handle=account_data.get('platform_username', 'unknown'),
                author_followers=account_data.get('follower_count', 0) or 0,
                tweeted_at=datetime.fromisoformat(row['posted_at'].replace('Z', '+00:00')),
                likes=row.get('likes', 0) or 0,
                replies=row.get('comments', 0) or 0,
                retweets=row.get('shares', 0) or 0,
                views=row.get('views', 0) or 0,
                lang='en'
            )
            tweets.append(tweet)

        return tweets, apify_run_id, apify_dataset_id

    def _embed_tweets(self, tweets: List[TweetMetrics]) -> List[List[float]]:
        """
        Generate embeddings for tweets.

        Args:
            tweets: List of tweets

        Returns:
            List of embedding vectors
        """
        tweet_texts = [t.text for t in tweets]
        embeddings = self.embedder.embed_texts(tweet_texts, task_type="RETRIEVAL_DOCUMENT")
        return embeddings

    def _score_tweets(
        self,
        tweets: List[TweetMetrics],
        embeddings: List[List[float]]
    ) -> List[tuple]:
        """
        Score tweets against project taxonomy.

        Args:
            tweets: List of tweets
            embeddings: List of tweet embeddings

        Returns:
            List of (tweet, embedding, scoring_result) tuples
        """
        scored = []

        for tweet, embedding in zip(tweets, embeddings):
            scoring_result = score_tweet(
                tweet,
                embedding,
                self.taxonomy_embeddings,
                self.config,
                use_gate=True
            )
            scored.append((tweet, embedding, scoring_result))

        return scored

    def _generate_comments(
        self,
        scored_tweets: List[tuple],
        batch_size: int,
        progress_callback: Optional[callable]
    ) -> Dict:
        """
        Generate comments for scored tweets using async batch processing.

        Args:
            scored_tweets: List of (tweet, embedding, scoring_result) tuples
            batch_size: Concurrent requests
            progress_callback: Optional progress callback

        Returns:
            Generation statistics dict with cost tracking
        """
        # Filter to only green/yellow tweets for comment generation
        high_quality = [
            (tweet, scoring_result)
            for tweet, embedding, scoring_result in scored_tweets
            if scoring_result.label in ['green', 'yellow'] and scoring_result.passed_gate
        ]

        if not high_quality:
            return {
                'generated': 0,
                'failed': 0,
                'total_cost_usd': 0.0
            }

        # Progress callback wrapper for async generation
        def async_progress_callback(current, total):
            if progress_callback:
                progress_callback("generating", current, total)

        # Run async batch generation
        stats = asyncio.run(generate_comments_async(
            project_id=self.project_id,
            tweets_with_scores=high_quality,
            config=self.config,
            batch_size=batch_size,
            max_requests_per_minute=15,
            progress_callback=async_progress_callback
        ))

        return stats

    def _save_scores_only(
        self,
        scored_tweets: List[tuple]
    ) -> int:
        """
        Save tweet scores to database without generating comments.

        This is called when --skip-comments flag is used. It saves scores
        for ALL tweets (green, yellow, red) so they can be queried later
        by generate-comments command with --greens-only filter.

        Args:
            scored_tweets: List of (tweet, embedding, scoring_result) tuples

        Returns:
            Number of tweets with scores saved
        """
        saved_count = 0

        for tweet, embedding, scoring_result in scored_tweets:
            try:
                save_scores_only_to_db(
                    project_id=self.project_id,
                    tweet_id=tweet.tweet_id,
                    scoring_result=scoring_result,
                    tweet=tweet
                )
                saved_count += 1
            except Exception as e:
                logger.warning(f"Failed to save scores for tweet {tweet.tweet_id}: {e}")

        logger.info(f"Saved scores for {saved_count}/{len(scored_tweets)} tweets to database")
        return saved_count

    def _calculate_metrics(
        self,
        search_term: str,
        tweets: List[TweetMetrics],
        scored_tweets: List[tuple],
        generation_stats: Dict,
        analysis_run_id: str,
        apify_run_id: Optional[str],
        apify_dataset_id: Optional[str]
    ) -> SearchTermMetrics:
        """
        Calculate all metrics from analysis results.

        Args:
            search_term: Search term analyzed
            tweets: Original tweets
            scored_tweets: Scored tweets with results
            generation_stats: Stats from comment generation
            analysis_run_id: UUID from analysis_runs table
            apify_run_id: Apify actor run ID
            apify_dataset_id: Apify dataset ID

        Returns:
            SearchTermMetrics object
        """
        # Extract scoring results
        results = [scoring_result for _, _, scoring_result in scored_tweets]

        # Score distribution
        green = [r for r in results if r.label == 'green']
        yellow = [r for r in results if r.label == 'yellow']
        red = [r for r in results if r.label == 'red']

        total = len(results)

        green_count = len(green)
        yellow_count = len(yellow)
        red_count = len(red)

        green_pct = (green_count / total * 100) if total > 0 else 0
        yellow_pct = (yellow_count / total * 100) if total > 0 else 0
        red_pct = (red_count / total * 100) if total > 0 else 0

        green_avg = statistics.mean([r.total_score for r in green]) if green else 0
        yellow_avg = statistics.mean([r.total_score for r in yellow]) if yellow else 0
        red_avg = statistics.mean([r.total_score for r in red]) if red else 0

        # Relevance-only scores (semantic similarity, not composite)
        avg_relevance = statistics.mean([r.relevance for r in results]) if results else 0
        green_avg_relevance = statistics.mean([r.relevance for r in green]) if green else 0
        yellow_avg_relevance = statistics.mean([r.relevance for r in yellow]) if yellow else 0
        red_avg_relevance = statistics.mean([r.relevance for r in red]) if red else 0

        # Freshness (last 48h)
        cutoff = datetime.now() - timedelta(hours=48)
        recent = [t for t in tweets if t.tweeted_at.replace(tzinfo=None) >= cutoff]

        recent_count = len(recent)
        recent_pct = (recent_count / len(tweets) * 100) if tweets else 0
        conversations_per_day = recent_count / 2  # 48h = 2 days

        # Calculate tweets per 24h based on actual time range
        if tweets:
            # Remove timezone info for comparison
            tweet_times = [t.tweeted_at.replace(tzinfo=None) for t in tweets]
            oldest_tweet = min(tweet_times)
            newest_tweet = max(tweet_times)
            time_range_hours = (newest_tweet - oldest_tweet).total_seconds() / 3600

            # Avoid division by zero - if all tweets in same hour, assume 24h range
            if time_range_hours < 1:
                time_range_hours = 24

            tweets_per_24h = len(tweets) / (time_range_hours / 24)
        else:
            tweets_per_24h = 0

        # Virality (views)
        # Note: Twitter API may not always return view counts
        tweets_with_views = [t for t in tweets if hasattr(t, 'views') and getattr(t, 'views', 0) > 0]

        if tweets_with_views:
            views = [getattr(t, 'views', 0) for t in tweets_with_views]
            avg_views = statistics.mean(views)
            median_views = statistics.median(views)

            # Top 10% average
            top_10_count = max(1, len(views) // 10)
            sorted_views = sorted(views, reverse=True)
            top_10_avg = statistics.mean(sorted_views[:top_10_count])

            # Count tweets with 10k+ views
            tweets_10k_plus = sum(1 for v in views if v >= 10000)
        else:
            # No view data available
            avg_views = 0
            median_views = 0
            top_10_avg = 0
            tweets_10k_plus = 0

        # Topic distribution
        topics = defaultdict(int)
        for r in results:
            topics[r.best_topic] += 1

        # Cost efficiency
        total_cost = generation_stats.get('total_cost_usd', 0.0)
        cost_per_green = (total_cost / green_count) if green_count > 0 else 0
        greens_per_dollar = (green_count / total_cost) if total_cost > 0 else 0

        return SearchTermMetrics(
            project=self.project_slug,
            search_term=search_term,
            analyzed_at=datetime.now().isoformat(),
            tweets_analyzed=total,

            analysis_run_id=analysis_run_id,
            apify_run_id=apify_run_id,
            apify_dataset_id=apify_dataset_id,

            green_count=green_count,
            green_percentage=green_pct,
            green_avg_score=green_avg,
            yellow_count=yellow_count,
            yellow_percentage=yellow_pct,
            yellow_avg_score=yellow_avg,
            red_count=red_count,
            red_percentage=red_pct,
            red_avg_score=red_avg,

            last_48h_count=recent_count,
            last_48h_percentage=recent_pct,
            conversations_per_day=conversations_per_day,
            tweets_per_24h=tweets_per_24h,

            avg_views=avg_views,
            median_views=median_views,
            top_10_percent_avg_views=top_10_avg,
            tweets_with_10k_plus_views=tweets_10k_plus,

            avg_relevance_score=avg_relevance,
            green_avg_relevance=green_avg_relevance,
            yellow_avg_relevance=yellow_avg_relevance,
            red_avg_relevance=red_avg_relevance,

            topic_distribution=dict(topics),

            total_cost_usd=total_cost,
            cost_per_green=cost_per_green,
            greens_per_dollar=greens_per_dollar,

            recommendation="",  # Set in _add_recommendation
            confidence="",
            reasoning=""
        )

    def _add_recommendation(self, metrics: SearchTermMetrics) -> SearchTermMetrics:
        """
        Add recommendation based on metric thresholds.

        Args:
            metrics: Metrics to analyze

        Returns:
            Updated metrics with recommendation
        """
        green_pct = metrics.green_percentage
        freshness_pct = metrics.last_48h_percentage

        # Thresholds from plan
        green_excellent = green_pct >= 15
        green_good = green_pct >= 8
        green_okay = green_pct >= 5

        freshness_high = freshness_pct >= 30
        freshness_medium = freshness_pct >= 20

        # Generate recommendation
        if green_excellent and freshness_high:
            metrics.recommendation = "Excellent"
            metrics.confidence = "High"
            metrics.reasoning = (
                f"{green_pct:.1f}% green (target: 15%+). "
                f"High volume ({freshness_pct:.1f}% in 48h). "
                f"Use this term regularly."
            )
        elif green_good and freshness_high:
            metrics.recommendation = "Good"
            metrics.confidence = "High"
            metrics.reasoning = (
                f"{green_pct:.1f}% green (target: 8%+). "
                f"Active conversation ({freshness_pct:.1f}% in 48h). "
                f"Consider using."
            )
        elif green_good and freshness_medium:
            metrics.recommendation = "Good"
            metrics.confidence = "Medium"
            metrics.reasoning = (
                f"{green_pct:.1f}% green (target: 8%+). "
                f"Moderate volume ({freshness_pct:.1f}% in 48h). "
                f"Worth using."
            )
        elif green_okay:
            metrics.recommendation = "Okay"
            metrics.confidence = "Medium"
            metrics.reasoning = (
                f"{green_pct:.1f}% green but below target. "
                f"Low volume ({freshness_pct:.1f}% in 48h). "
                f"Use occasionally."
            )
        else:
            metrics.recommendation = "Poor"
            metrics.confidence = "High"
            metrics.reasoning = (
                f"Only {green_pct:.1f}% green (target: 8%+). "
                f"Consider other terms."
            )

        return metrics

    def export_json(self, metrics: SearchTermMetrics, filepath: str):
        """
        Export metrics to JSON file.

        Args:
            metrics: Metrics to export
            filepath: Output file path
        """
        # Convert to dict
        data = asdict(metrics)

        # Format for better readability
        formatted = {
            "project": data["project"],
            "search_term": data["search_term"],
            "analyzed_at": data["analyzed_at"],
            "tweets_analyzed": data["tweets_analyzed"],
            "tracking": {
                "analysis_run_id": data["analysis_run_id"],
                "apify_run_id": data["apify_run_id"],
                "apify_dataset_id": data["apify_dataset_id"]
            },
            "metrics": {
                "score_distribution": {
                    "green": {
                        "count": data["green_count"],
                        "percentage": round(data["green_percentage"], 1),
                        "avg_score": round(data["green_avg_score"], 3)
                    },
                    "yellow": {
                        "count": data["yellow_count"],
                        "percentage": round(data["yellow_percentage"], 1),
                        "avg_score": round(data["yellow_avg_score"], 3)
                    },
                    "red": {
                        "count": data["red_count"],
                        "percentage": round(data["red_percentage"], 1),
                        "avg_score": round(data["red_avg_score"], 3)
                    }
                },
                "freshness": {
                    "last_48h_count": data["last_48h_count"],
                    "last_48h_percentage": round(data["last_48h_percentage"], 1),
                    "conversations_per_day": round(data["conversations_per_day"], 1),
                    "tweets_per_24h": round(data["tweets_per_24h"], 1)
                },
                "virality": {
                    "avg_views": round(data["avg_views"], 0),
                    "median_views": round(data["median_views"], 0),
                    "top_10_percent_avg_views": round(data["top_10_percent_avg_views"], 0),
                    "tweets_with_10k_plus_views": data["tweets_with_10k_plus_views"]
                },
                "relevance_only": {
                    "avg_relevance_score": round(data["avg_relevance_score"], 3),
                    "green_avg_relevance": round(data["green_avg_relevance"], 3),
                    "yellow_avg_relevance": round(data["yellow_avg_relevance"], 3),
                    "red_avg_relevance": round(data["red_avg_relevance"], 3)
                },
                "topic_distribution": data["topic_distribution"],
                "cost_efficiency": {
                    "total_cost_usd": round(data["total_cost_usd"], 3),
                    "cost_per_green_tweet": round(data["cost_per_green"], 5),
                    "greens_per_dollar": round(data["greens_per_dollar"], 0)
                }
            },
            "recommendation": {
                "rating": data["recommendation"],
                "confidence": data["confidence"],
                "reasoning": data["reasoning"]
            }
        }

        # Write to file
        with open(filepath, 'w') as f:
            json.dump(formatted, f, indent=2)

        logger.info(f"Exported metrics to {filepath}")
