"""
Outlier Detector for Twitter Content

Identifies high-performing tweets using statistical analysis to find viral/outlier content
that can be analyzed and adapted for long-form content generation.

Methods:
- Z-score: Tweets N standard deviations above the trimmed mean
- Percentile: Top N% of tweets by engagement metrics

Usage:
    detector = OutlierDetector(project_slug="my-project")
    outliers = detector.find_outliers(
        days_back=30,
        min_views=1000,
        method="zscore",
        threshold=2.0
    )
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import numpy as np
from scipy import stats

from ..core.database import get_supabase_client


logger = logging.getLogger(__name__)


@dataclass
class TweetMetrics:
    """Metrics for a single tweet"""
    tweet_id: str
    text: str
    author_handle: str
    author_followers: int
    posted_at: datetime
    views: int
    likes: int
    replies: int
    retweets: int

    # Computed metrics
    engagement_rate: float = 0.0  # (likes + replies + retweets) / views
    engagement_score: float = 0.0  # Composite engagement metric

    def compute_metrics(self):
        """Compute derived metrics"""
        # Engagement rate
        if self.views > 0:
            self.engagement_rate = (self.likes + self.replies + self.retweets) / self.views
        else:
            self.engagement_rate = 0.0

        # Engagement score: weighted combination
        # Higher weight on likes, moderate on retweets, lower on replies
        self.engagement_score = (
            self.likes * 1.0 +
            self.retweets * 0.8 +
            self.replies * 0.5
        )


@dataclass
class OutlierResult:
    """Result of outlier detection for a single tweet"""
    tweet: TweetMetrics

    # Statistical metrics
    z_score: float  # How many SDs above mean
    percentile: float  # 0-100
    is_outlier: bool

    # Relative metrics
    rank: int  # 1 = highest engagement
    rank_percentile: float  # 0-100


class OutlierDetector:
    """
    Detects outlier tweets using statistical methods

    Supports two methods:
    1. Z-score: Tweets N standard deviations above trimmed mean
    2. Percentile: Top N% of tweets by engagement
    """

    def __init__(self, project_slug: str):
        """
        Initialize detector for a project

        Args:
            project_slug: Project slug in database
        """
        self.project_slug = project_slug
        self.db = get_supabase_client()

        # Get project ID
        project_result = self.db.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not project_result.data:
            raise ValueError(f"Project '{project_slug}' not found")

        self.project_id = project_result.data['id']

    def find_outliers(
        self,
        days_back: int = 30,
        min_views: int = 100,
        min_likes: int = 0,
        method: str = "zscore",
        threshold: float = 2.0,
        trim_percent: float = 10.0,
        time_decay: bool = False,
        decay_halflife_days: int = 7,
        text_only: bool = False
    ) -> List[OutlierResult]:
        """
        Find outlier tweets using statistical methods

        Args:
            days_back: Look back N days
            min_views: Minimum view count filter
            min_likes: Minimum like count filter
            method: "zscore" or "percentile"
            threshold: Z-score threshold (e.g., 2.0) or percentile threshold (e.g., 5.0 for top 5%)
            trim_percent: Percent to trim from each end before computing mean/std (default: 10%)
            time_decay: Apply time decay weighting (recent tweets weighted higher)
            decay_halflife_days: Half-life for time decay in days
            text_only: Exclude video and image posts (text-only tweets)

        Returns:
            List of OutlierResult objects, sorted by engagement score
        """
        # Fetch tweets
        logger.info(f"Fetching tweets for project '{self.project_slug}' (last {days_back} days)")
        tweets = self._fetch_tweets(days_back, min_views, min_likes, text_only)

        if not tweets:
            logger.warning("No tweets found matching criteria")
            return []

        logger.info(f"Found {len(tweets)} tweets matching criteria")

        # Compute engagement metrics
        for tweet in tweets:
            tweet.compute_metrics()

        # Apply time decay if requested
        if time_decay:
            tweets = self._apply_time_decay(tweets, decay_halflife_days)

        # Extract engagement scores
        scores = np.array([t.engagement_score for t in tweets])

        # Detect outliers based on method
        if method == "zscore":
            outlier_results = self._detect_zscore(tweets, scores, threshold, trim_percent)
        elif method == "percentile":
            outlier_results = self._detect_percentile(tweets, scores, threshold)
        else:
            raise ValueError(f"Unknown method: {method}. Use 'zscore' or 'percentile'")

        # Sort by engagement score (descending)
        outlier_results.sort(key=lambda r: r.tweet.engagement_score, reverse=True)

        # Assign ranks
        for i, result in enumerate(outlier_results, 1):
            result.rank = i
            result.rank_percentile = (1 - (i - 1) / len(tweets)) * 100

        logger.info(f"Detected {len(outlier_results)} outliers using {method} method")

        return outlier_results

    def _fetch_tweets(
        self,
        days_back: int,
        min_views: int,
        min_likes: int,
        text_only: bool = False
    ) -> List[TweetMetrics]:
        """
        Fetch tweets from database

        Args:
            days_back: Look back N days
            min_views: Minimum view count
            min_likes: Minimum like count
            text_only: Exclude video and image posts

        Returns:
            List of TweetMetrics
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        # Query posts linked to this project
        query = self.db.table('posts') \
            .select('*, accounts!inner(platform_username, follower_count), project_posts!inner(project_id)') \
            .eq('project_posts.project_id', self.project_id) \
            .gte('posted_at', cutoff.isoformat()) \
            .gte('views', min_views) \
            .gte('likes', min_likes)

        # Filter for text-only if requested
        if text_only:
            query = query.eq('media_type', 'text')

        result = query.order('posted_at', desc=True).execute()

        if not result.data:
            return []

        # Convert to TweetMetrics
        tweets = []
        for row in result.data:
            account_data = row.get('accounts')
            if not account_data:
                continue

            # Parse posted_at
            posted_at = row['posted_at']
            if isinstance(posted_at, str):
                posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))

            tweet = TweetMetrics(
                tweet_id=row['post_id'],
                text=row['caption'] or '',
                author_handle=account_data.get('platform_username', 'unknown'),
                author_followers=account_data.get('follower_count', 0),
                posted_at=posted_at,
                views=row.get('views', 0) or 0,
                likes=row.get('likes', 0) or 0,
                replies=row.get('comments', 0) or 0,
                retweets=row.get('shares', 0) or 0
            )
            tweets.append(tweet)

        return tweets

    def _apply_time_decay(
        self,
        tweets: List[TweetMetrics],
        halflife_days: int
    ) -> List[TweetMetrics]:
        """
        Apply time decay weighting to engagement scores

        Recent tweets are weighted higher than older tweets using exponential decay.

        Args:
            tweets: List of TweetMetrics
            halflife_days: Half-life for decay in days

        Returns:
            List of TweetMetrics with adjusted engagement scores
        """
        now = datetime.now(timezone.utc)

        for tweet in tweets:
            # Calculate age in days
            age_days = (now - tweet.posted_at).total_seconds() / 86400

            # Apply exponential decay: score * 2^(-age / halflife)
            decay_factor = 2 ** (-age_days / halflife_days)
            tweet.engagement_score *= decay_factor

        return tweets

    def _detect_zscore(
        self,
        tweets: List[TweetMetrics],
        scores: np.ndarray,
        threshold: float,
        trim_percent: float
    ) -> List[OutlierResult]:
        """
        Detect outliers using z-score method

        Args:
            tweets: List of TweetMetrics
            scores: Array of engagement scores
            threshold: Z-score threshold (e.g., 2.0 = 2 SDs above mean)
            trim_percent: Percent to trim from each end

        Returns:
            List of OutlierResult for outliers
        """
        # Compute trimmed mean and std
        trim_fraction = trim_percent / 100.0
        trimmed_mean = stats.trim_mean(scores, trim_fraction)

        # For trimmed std, we need to manually trim
        sorted_scores = np.sort(scores)
        n = len(sorted_scores)
        lower_cut = int(n * trim_fraction)
        upper_cut = n - lower_cut
        trimmed_scores = sorted_scores[lower_cut:upper_cut]
        trimmed_std = np.std(trimmed_scores, ddof=1)

        logger.info(f"Trimmed mean: {trimmed_mean:.1f}, Trimmed std: {trimmed_std:.1f}")

        # Compute z-scores
        if trimmed_std == 0:
            logger.warning("Standard deviation is 0, cannot compute z-scores")
            return []

        z_scores = (scores - trimmed_mean) / trimmed_std

        # Find outliers
        outlier_results = []
        for i, (tweet, z_score) in enumerate(zip(tweets, z_scores)):
            is_outlier = z_score >= threshold

            # Compute percentile
            percentile = (np.sum(scores <= tweet.engagement_score) / len(scores)) * 100

            if is_outlier:
                result = OutlierResult(
                    tweet=tweet,
                    z_score=float(z_score),
                    percentile=float(percentile),
                    is_outlier=True,
                    rank=0,  # Will be set later
                    rank_percentile=0.0  # Will be set later
                )
                outlier_results.append(result)

        return outlier_results

    def _detect_percentile(
        self,
        tweets: List[TweetMetrics],
        scores: np.ndarray,
        threshold: float
    ) -> List[OutlierResult]:
        """
        Detect outliers using percentile method

        Args:
            tweets: List of TweetMetrics
            scores: Array of engagement scores
            threshold: Percentile threshold (e.g., 5.0 for top 5%)

        Returns:
            List of OutlierResult for outliers
        """
        # Compute percentile cutoff
        percentile_cutoff = np.percentile(scores, 100 - threshold)

        logger.info(f"Percentile cutoff (top {threshold}%): {percentile_cutoff:.1f}")

        # Find outliers
        outlier_results = []
        for tweet, score in zip(tweets, scores):
            is_outlier = score >= percentile_cutoff

            # Compute percentile
            percentile = (np.sum(scores <= score) / len(scores)) * 100

            # Compute z-score for reference
            mean = np.mean(scores)
            std = np.std(scores, ddof=1)
            z_score = (score - mean) / std if std > 0 else 0.0

            if is_outlier:
                result = OutlierResult(
                    tweet=tweet,
                    z_score=float(z_score),
                    percentile=float(percentile),
                    is_outlier=True,
                    rank=0,  # Will be set later
                    rank_percentile=0.0  # Will be set later
                )
                outlier_results.append(result)

        return outlier_results

    def export_report(
        self,
        outliers: List[OutlierResult],
        output_path: str
    ) -> Dict:
        """
        Export outlier report to JSON

        Args:
            outliers: List of OutlierResult
            output_path: Path to save JSON file

        Returns:
            Report dictionary
        """
        import json

        # Build report
        report = {
            "project": self.project_slug,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_outliers": len(outliers),
            "outliers": []
        }

        for result in outliers:
            tweet = result.tweet
            outlier_data = {
                "rank": result.rank,
                "tweet_id": tweet.tweet_id,
                "url": f"https://twitter.com/i/status/{tweet.tweet_id}",
                "text": tweet.text,
                "author": tweet.author_handle,
                "author_followers": tweet.author_followers,
                "posted_at": tweet.posted_at.isoformat(),
                "metrics": {
                    "views": tweet.views,
                    "likes": tweet.likes,
                    "replies": tweet.replies,
                    "retweets": tweet.retweets,
                    "engagement_rate": round(tweet.engagement_rate, 4),
                    "engagement_score": round(tweet.engagement_score, 2)
                },
                "outlier_metrics": {
                    "z_score": round(result.z_score, 2),
                    "percentile": round(result.percentile, 1),
                    "rank_percentile": round(result.rank_percentile, 1)
                }
            }
            report["outliers"].append(outlier_data)

        # Save to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Report saved to {output_path}")

        return report
