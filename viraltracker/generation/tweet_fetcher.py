"""
Tweet Fetcher for Comment Finder

Queries recent tweets from the posts table and returns them as TweetMetrics objects
ready for scoring.
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from uuid import UUID

from viraltracker.core.database import get_supabase_client
from viraltracker.generation.comment_finder import TweetMetrics

logger = logging.getLogger(__name__)


def fetch_recent_tweets(
    project_slug: str,
    hours_back: int = 6,
    min_followers: int = 0,
    min_likes: int = 0,
    max_candidates: int = 500,
    require_english: bool = True
) -> List[TweetMetrics]:
    """
    Fetch recent tweets for comment opportunity detection.

    Queries the posts table for tweets from the last N hours, filtered by:
    - Project linkage
    - Time window
    - Minimum follower count
    - Minimum likes
    - Language (English by default)

    Args:
        project_slug: Project slug to filter tweets
        hours_back: Only fetch tweets from last N hours
        min_followers: Minimum author follower count
        min_likes: Minimum like count
        max_candidates: Maximum tweets to return
        require_english: Only return English tweets

    Returns:
        List of TweetMetrics objects
    """
    db = get_supabase_client()

    # Get project ID
    project_result = db.table('projects').select('id').eq('slug', project_slug).single().execute()
    if not project_result.data:
        raise ValueError(f"Project not found: {project_slug}")

    project_id = project_result.data['id']

    # Get Twitter platform ID
    platform_result = db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
    if not platform_result.data:
        raise ValueError("Twitter platform not found in database")

    platform_id = platform_result.data['id']

    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    logger.info(f"Fetching tweets for project '{project_slug}' from last {hours_back} hours")
    logger.info(f"Filters: min_followers={min_followers}, min_likes={min_likes}, max={max_candidates}")

    # Query tweets with joins to get account data
    # Note: Supabase uses foreign key relationships for joins
    query = db.table('posts')\
        .select('id, post_id, caption, posted_at, likes, comments, shares, accounts(platform_username, follower_count), project_posts!inner(project_id)')\
        .eq('platform_id', platform_id)\
        .eq('project_posts.project_id', project_id)\
        .gte('posted_at', cutoff_time.isoformat())\
        .gte('likes', min_likes)\
        .order('posted_at', desc=True)\
        .limit(max_candidates)

    result = query.execute()

    if not result.data:
        logger.warning("No tweets found matching criteria")
        return []

    logger.info(f"Found {len(result.data)} candidate tweets")

    # Convert to TweetMetrics objects
    tweet_metrics = []

    for row in result.data:
        try:
            # Extract account data
            account = row.get('accounts')
            if not account:
                logger.warning(f"Tweet {row['post_id']} has no account data, skipping")
                continue

            follower_count = account.get('follower_count', 0) or 0

            # Apply follower filter
            if follower_count < min_followers:
                continue

            # Parse timestamp
            posted_at = datetime.fromisoformat(row['posted_at'].replace('Z', '+00:00'))

            # Create TweetMetrics
            metrics = TweetMetrics(
                tweet_id=row['post_id'],
                text=row.get('caption', ''),
                author_handle=account.get('platform_username', ''),
                author_followers=follower_count,
                tweeted_at=posted_at,
                likes=row.get('likes', 0) or 0,
                replies=row.get('comments', 0) or 0,
                retweets=row.get('shares', 0) or 0,
                lang='en'  # Default to English (we don't store lang in posts table yet)
            )

            # Language filter (placeholder for now since we don't store it)
            if require_english and not metrics.text:
                # Skip empty tweets
                continue

            tweet_metrics.append(metrics)

        except Exception as e:
            logger.warning(f"Error processing tweet row: {e}")
            continue

    logger.info(f"Converted {len(tweet_metrics)} tweets to TweetMetrics objects")

    return tweet_metrics


def fetch_tweets_by_ids(
    tweet_ids: List[str],
    platform_id: Optional[str] = None
) -> List[TweetMetrics]:
    """
    Fetch specific tweets by their IDs.

    Args:
        tweet_ids: List of tweet IDs (post_id field)
        platform_id: Optional platform ID (defaults to Twitter)

    Returns:
        List of TweetMetrics objects
    """
    db = get_supabase_client()

    # Get Twitter platform ID if not provided
    if not platform_id:
        platform_result = db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
        if not platform_result.data:
            raise ValueError("Twitter platform not found in database")
        platform_id = platform_result.data['id']

    logger.info(f"Fetching {len(tweet_ids)} specific tweets")

    # Query by post_id list
    query = db.table('posts')\
        .select('id, post_id, caption, posted_at, likes, comments, shares, accounts(platform_username, follower_count)')\
        .eq('platform_id', platform_id)\
        .in_('post_id', tweet_ids)

    result = query.execute()

    if not result.data:
        logger.warning("No tweets found with provided IDs")
        return []

    logger.info(f"Found {len(result.data)} tweets")

    # Convert to TweetMetrics
    tweet_metrics = []

    for row in result.data:
        try:
            account = row.get('accounts')
            if not account:
                logger.warning(f"Tweet {row['post_id']} has no account data, skipping")
                continue

            posted_at = datetime.fromisoformat(row['posted_at'].replace('Z', '+00:00'))

            metrics = TweetMetrics(
                tweet_id=row['post_id'],
                text=row.get('caption', ''),
                author_handle=account.get('platform_username', ''),
                author_followers=account.get('follower_count', 0) or 0,
                tweeted_at=posted_at,
                likes=row.get('likes', 0) or 0,
                replies=row.get('comments', 0) or 0,
                retweets=row.get('shares', 0) or 0,
                lang='en'
            )

            tweet_metrics.append(metrics)

        except Exception as e:
            logger.warning(f"Error processing tweet row: {e}")
            continue

    return tweet_metrics
