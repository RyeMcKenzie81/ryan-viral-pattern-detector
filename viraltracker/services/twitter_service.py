"""
TwitterService - Data access layer for Twitter/social data.

Handles all database operations for tweets, hook analyses, and outlier detection.
Pure data access - no business logic.
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from ..core.database import get_supabase_client
from .models import Tweet, HookAnalysis

logger = logging.getLogger(__name__)


class TwitterService:
    """
    Data access service for Twitter data.

    Provides clean interface to fetch tweets, save analyses,
    and manage outlier data from Supabase.
    """

    def __init__(self):
        """Initialize Twitter service with Supabase client"""
        self.db = get_supabase_client()
        logger.info("TwitterService initialized")

    async def get_tweets(
        self,
        project: str,
        hours_back: int,
        min_views: int = 0,
        min_likes: int = 0,
        text_only: bool = False,
        limit: Optional[int] = None
    ) -> List[Tweet]:
        """
        Fetch tweets from database for a project.

        Args:
            project: Project slug (e.g., 'yakety-pack-instagram')
            hours_back: Hours of data to fetch
            min_views: Minimum view count filter
            min_likes: Minimum like count filter
            text_only: Only return text tweets (no media)
            limit: Optional limit on number of tweets

        Returns:
            List of Tweet models

        Raises:
            ValueError: If project not found
        """
        # Get project ID
        project_result = self.db.table('projects').select('id').eq('slug', project).single().execute()
        if not project_result.data:
            raise ValueError(f"Project '{project}' not found in database")

        project_id = project_result.data['id']
        logger.info(f"Found project '{project}' with ID: {project_id}")

        # Calculate cutoff time
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        # Build query
        query = self.db.table('posts') \
            .select('*, accounts!inner(platform_username, follower_count, is_verified), project_posts!inner(project_id)') \
            .eq('project_posts.project_id', project_id) \
            .gte('posted_at', cutoff.isoformat()) \
            .gte('views', min_views) \
            .gte('likes', min_likes)

        # Filter for text-only if requested
        if text_only:
            query = query.eq('media_type', 'text')

        # Apply limit if specified
        if limit:
            query = query.limit(limit)

        # Execute query
        result = query.order('posted_at', desc=True).execute()

        if not result.data:
            logger.warning(f"No tweets found for project '{project}' in last {hours_back} hours")
            return []

        # Convert to Tweet models
        tweets = []
        for row in result.data:
            account_data = row.get('accounts')
            if not account_data:
                continue

            # Parse posted_at
            posted_at = row['posted_at']
            if isinstance(posted_at, str):
                posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))

            tweet = Tweet(
                id=row['post_id'],
                text=row['caption'] or '',
                view_count=row.get('views', 0) or 0,
                like_count=row.get('likes', 0) or 0,
                reply_count=row.get('comments', 0) or 0,
                retweet_count=row.get('shares', 0) or 0,
                created_at=posted_at,
                author_username=account_data.get('platform_username', 'unknown'),
                author_followers=account_data.get('follower_count', 0),
                url=row.get('post_url', f"https://twitter.com/i/status/{row['post_id']}"),
                media_type=row.get('media_type'),
                is_verified=account_data.get('is_verified', False)
            )
            tweets.append(tweet)

        logger.info(f"Fetched {len(tweets)} tweets for project '{project}'")
        return tweets

    async def get_tweets_by_ids(
        self,
        tweet_ids: List[str],
        project: Optional[str] = None
    ) -> List[Tweet]:
        """
        Fetch specific tweets by IDs.

        Args:
            tweet_ids: List of tweet IDs to fetch
            project: Optional project slug to filter by

        Returns:
            List of Tweet models
        """
        if not tweet_ids:
            return []

        # Build query
        query = self.db.table('posts') \
            .select('*, accounts!inner(platform_username, follower_count, is_verified)') \
            .in_('post_id', tweet_ids)

        # Filter by project if specified
        if project:
            project_result = self.db.table('projects').select('id').eq('slug', project).single().execute()
            if not project_result.data:
                raise ValueError(f"Project '{project}' not found")
            project_id = project_result.data['id']
            query = query.eq('project_posts.project_id', project_id)

        result = query.execute()

        if not result.data:
            logger.warning(f"No tweets found for IDs: {tweet_ids}")
            return []

        # Convert to Tweet models
        tweets = []
        for row in result.data:
            account_data = row.get('accounts')
            if not account_data:
                continue

            # Parse posted_at
            posted_at = row['posted_at']
            if isinstance(posted_at, str):
                posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))

            tweet = Tweet(
                id=row['post_id'],
                text=row['caption'] or '',
                view_count=row.get('views', 0) or 0,
                like_count=row.get('likes', 0) or 0,
                reply_count=row.get('comments', 0) or 0,
                retweet_count=row.get('shares', 0) or 0,
                created_at=posted_at,
                author_username=account_data.get('platform_username', 'unknown'),
                author_followers=account_data.get('follower_count', 0),
                url=row.get('post_url', f"https://twitter.com/i/status/{row['post_id']}"),
                media_type=row.get('media_type'),
                is_verified=account_data.get('is_verified', False)
            )
            tweets.append(tweet)

        logger.info(f"Fetched {len(tweets)} tweets by IDs")
        return tweets

    async def save_hook_analysis(
        self,
        analysis: HookAnalysis,
        project: Optional[str] = None
    ) -> None:
        """
        Save hook analysis to database.

        Args:
            analysis: HookAnalysis model to save
            project: Optional project slug

        Note:
            Currently stores in a 'hook_analyses' table.
            You may need to create this table in Supabase if it doesn't exist.
        """
        data = {
            "tweet_id": analysis.tweet_id,
            "tweet_text": analysis.tweet_text,
            "hook_type": analysis.hook_type,
            "hook_type_confidence": analysis.hook_type_confidence,
            "emotional_trigger": analysis.emotional_trigger,
            "emotional_trigger_confidence": analysis.emotional_trigger_confidence,
            "content_pattern": analysis.content_pattern,
            "content_pattern_confidence": analysis.content_pattern_confidence,
            "hook_explanation": analysis.hook_explanation,
            "adaptation_notes": analysis.adaptation_notes,
            "has_emoji": analysis.has_emoji,
            "has_hashtags": analysis.has_hashtags,
            "has_question_mark": analysis.has_question_mark,
            "word_count": analysis.word_count,
            "analyzed_at": analysis.analyzed_at.isoformat()
        }

        try:
            # Insert or update hook analysis
            result = self.db.table('hook_analyses').upsert(data, on_conflict='tweet_id').execute()
            logger.info(f"Saved hook analysis for tweet {analysis.tweet_id}")
        except Exception as e:
            logger.error(f"Error saving hook analysis for tweet {analysis.tweet_id}: {e}")
            # Don't raise - allow processing to continue
            # You may want to create the hook_analyses table:
            # CREATE TABLE hook_analyses (
            #     id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            #     tweet_id TEXT UNIQUE NOT NULL,
            #     tweet_text TEXT,
            #     hook_type TEXT,
            #     hook_type_confidence FLOAT,
            #     emotional_trigger TEXT,
            #     emotional_trigger_confidence FLOAT,
            #     content_pattern TEXT,
            #     content_pattern_confidence FLOAT,
            #     hook_explanation TEXT,
            #     adaptation_notes TEXT,
            #     has_emoji BOOLEAN,
            #     has_hashtags BOOLEAN,
            #     has_question_mark BOOLEAN,
            #     word_count INTEGER,
            #     analyzed_at TIMESTAMP WITH TIME ZONE,
            #     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            # );

    async def get_hook_analyses(
        self,
        project: str,
        hours_back: Optional[int] = None,
        hook_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[HookAnalysis]:
        """
        Fetch hook analyses with filters.

        Args:
            project: Project slug
            hours_back: Optional hours of data to fetch
            hook_type: Optional filter by hook type
            limit: Optional limit on number of results

        Returns:
            List of HookAnalysis models
        """
        query = self.db.table('hook_analyses').select('*')

        # Filter by time if specified
        if hours_back:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            query = query.gte('analyzed_at', cutoff.isoformat())

        # Filter by hook type if specified
        if hook_type:
            query = query.eq('hook_type', hook_type)

        # Apply limit if specified
        if limit:
            query = query.limit(limit)

        result = query.order('analyzed_at', desc=True).execute()

        if not result.data:
            logger.warning("No hook analyses found")
            return []

        # Convert to HookAnalysis models
        analyses = []
        for row in result.data:
            analyzed_at = row['analyzed_at']
            if isinstance(analyzed_at, str):
                analyzed_at = datetime.fromisoformat(analyzed_at.replace('Z', '+00:00'))

            analysis = HookAnalysis(
                tweet_id=row['tweet_id'],
                tweet_text=row['tweet_text'],
                hook_type=row['hook_type'],
                hook_type_confidence=row['hook_type_confidence'],
                emotional_trigger=row['emotional_trigger'],
                emotional_trigger_confidence=row['emotional_trigger_confidence'],
                content_pattern=row.get('content_pattern', 'statement'),
                content_pattern_confidence=row.get('content_pattern_confidence', 0.5),
                hook_explanation=row['hook_explanation'],
                adaptation_notes=row['adaptation_notes'],
                has_emoji=row.get('has_emoji', False),
                has_hashtags=row.get('has_hashtags', False),
                has_question_mark=row.get('has_question_mark', False),
                word_count=row.get('word_count', 0),
                analyzed_at=analyzed_at
            )
            analyses.append(analysis)

        logger.info(f"Fetched {len(analyses)} hook analyses")
        return analyses

    async def mark_as_outlier(
        self,
        tweet_id: str,
        zscore: float,
        threshold: float,
        method: str = "zscore"
    ) -> None:
        """
        Mark a tweet as a viral outlier.

        Args:
            tweet_id: Tweet ID
            zscore: Z-score value
            threshold: Threshold used
            method: Detection method ('zscore' or 'percentile')

        Note:
            Stores in 'outliers' table. Create if needed:
            CREATE TABLE outliers (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tweet_id TEXT UNIQUE NOT NULL,
                zscore FLOAT,
                threshold FLOAT,
                method TEXT,
                detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """
        data = {
            "tweet_id": tweet_id,
            "zscore": zscore,
            "threshold": threshold,
            "method": method,
            "detected_at": datetime.now(timezone.utc).isoformat()
        }

        try:
            result = self.db.table('outliers').upsert(data, on_conflict='tweet_id').execute()
            logger.debug(f"Marked tweet {tweet_id} as outlier (z-score: {zscore:.2f})")
        except Exception as e:
            logger.error(f"Error marking tweet {tweet_id} as outlier: {e}")
            # Don't raise - allow processing to continue
