"""
CommentService - Business logic layer for comment generation and opportunities.

Provides async interface for:
- Generating AI comment suggestions (full workflow)
- Fetching saved comment opportunities from database
- Managing semantic deduplication
"""

import logging
import numpy as np
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from ..core.database import get_supabase_client
from ..core.config import FinderConfig, load_finder_config
from ..core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from ..generation.tweet_fetcher import fetch_recent_tweets
from ..generation.comment_finder import (
    TweetMetrics,
    ScoringResult,
    score_tweet as score_tweet_util
)
from ..generation.async_comment_generator import generate_comments_async
from .models import CommentCandidate, Tweet

logger = logging.getLogger(__name__)

# Similarity threshold for semantic deduplication
SIMILARITY_THRESHOLD = 0.95


@dataclass
class CommentOpportunity:
    """A scored comment opportunity ready for AI generation"""
    tweet: TweetMetrics
    score: ScoringResult
    embedding: Optional[List[float]] = None


class CommentService:
    """
    Business logic service for comment generation and opportunities.

    Provides clean interface for:
    - Finding and scoring comment opportunities (full generation workflow)
    - Fetching saved opportunities from database
    - Managing semantic deduplication
    """

    def __init__(self):
        """Initialize comment service with Supabase client"""
        self.db = get_supabase_client()
        logger.info("CommentService initialized")

    # ========================================================================
    # GENERATION WORKFLOW METHODS (NEW - Task 2.8)
    # ========================================================================

    async def find_comment_opportunities(
        self,
        project_slug: str,
        hours_back: int = 6,
        min_followers: int = 1000,
        min_likes: int = 0,
        min_views: int = 0,
        max_candidates: int = 150,
        use_gate: bool = True,
        skip_low_scores: bool = True,
        greens_only: bool = False
    ) -> Tuple[List[CommentOpportunity], FinderConfig]:
        """
        Find high-quality comment opportunities from recent tweets.

        Full workflow:
        1. Load project config and taxonomy
        2. Fetch recent tweets
        3. Compute embeddings
        4. Check semantic duplicates
        5. Score tweets
        6. Filter by gate and score thresholds

        Args:
            project_slug: Project slug (e.g., 'yakety-pack-instagram')
            hours_back: Hours of data to fetch
            min_followers: Minimum author follower count
            min_likes: Minimum tweet likes
            min_views: Minimum tweet views
            max_candidates: Maximum tweets to process
            use_gate: Apply gate filtering
            skip_low_scores: Only return green/yellow scores
            greens_only: Only return green scores (overrides skip_low_scores)

        Returns:
            Tuple of (opportunities, config)
        """
        logger.info(f"Finding comment opportunities for {project_slug}")
        logger.info(f"Filters: hours_back={hours_back}, min_followers={min_followers}, "
                   f"min_likes={min_likes}, min_views={min_views}, max={max_candidates}")

        # Load config
        config = load_finder_config(project_slug)
        logger.info(f"Loaded config with {len(config.taxonomy)} taxonomy nodes")

        # Initialize embedder
        embedder = Embedder()

        # Load taxonomy embeddings (with incremental caching)
        taxonomy_embeddings = load_taxonomy_embeddings_incremental(
            project_slug,
            config.taxonomy,
            embedder
        )
        logger.info(f"Loaded {len(taxonomy_embeddings)} taxonomy embeddings")

        # Fetch recent tweets
        tweets = fetch_recent_tweets(
            project_slug=project_slug,
            hours_back=hours_back,
            min_followers=min_followers,
            min_likes=min_likes,
            min_views=min_views,
            max_candidates=max_candidates,
            require_english=True
        )

        if not tweets:
            logger.warning("No tweets found matching criteria")
            return ([], config)

        logger.info(f"Found {len(tweets)} candidate tweets")

        # Embed tweets
        tweet_texts = [t.text for t in tweets]
        tweet_embeddings = embedder.embed_texts(tweet_texts, task_type="RETRIEVAL_DOCUMENT")
        logger.info(f"Embedded {len(tweet_embeddings)} tweets")

        # Get project ID for duplicate checking
        project_result = self.db.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not project_result.data:
            raise ValueError(f"Project not found: {project_slug}")

        project_id = project_result.data['id']

        # Check for semantic duplicates
        is_duplicate = self._check_semantic_duplicates(project_id, tweet_embeddings)
        duplicate_count = sum(is_duplicate)
        logger.info(f"Found {duplicate_count} semantic duplicates (threshold={SIMILARITY_THRESHOLD})")

        # Filter out duplicates
        tweets_filtered = [
            (tweet, emb) for tweet, emb, is_dup in zip(tweets, tweet_embeddings, is_duplicate)
            if not is_dup
        ]

        if not tweets_filtered:
            logger.warning("All tweets are duplicates")
            return ([], config)

        logger.info(f"Processing {len(tweets_filtered)} unique tweets")

        # Unpack filtered tweets and embeddings
        tweets = [t for t, _ in tweets_filtered]
        tweet_embeddings = [e for _, e in tweets_filtered]

        # Score tweets
        scored_tweets = []
        for tweet, embedding in zip(tweets, tweet_embeddings):
            result = score_tweet_util(tweet, embedding, taxonomy_embeddings, config, use_gate=use_gate)
            scored_tweets.append((tweet, result, embedding))

        logger.info(f"Scored {len(scored_tweets)} tweets")

        # Filter by gate
        if use_gate:
            passed_gate = [(t, r, e) for t, r, e in scored_tweets if r.passed_gate]
            logger.info(f"Gate filtering: {len(passed_gate)}/{len(scored_tweets)} passed")
            scored_tweets = passed_gate

        if not scored_tweets:
            logger.warning("No tweets passed gate filtering")
            return ([], config)

        # Filter by score label
        if greens_only:
            scored_tweets = [(t, r, e) for t, r, e in scored_tweets if r.label == 'green']
            logger.info(f"Green-only filter: {len(scored_tweets)} greens")
        elif skip_low_scores:
            scored_tweets = [(t, r, e) for t, r, e in scored_tweets if r.label in ['green', 'yellow']]
            logger.info(f"Skip low scores: {len(scored_tweets)} green/yellow")

        if not scored_tweets:
            logger.warning("No high-quality tweets found after score filtering")
            return ([], config)

        # Build opportunities
        opportunities = [
            CommentOpportunity(tweet=tweet, score=score, embedding=emb)
            for tweet, score, emb in scored_tweets
        ]

        logger.info(f"Found {len(opportunities)} comment opportunities")
        return (opportunities, config)

    async def find_saved_comment_opportunities(
        self,
        project_slug: str,
        hours_back: int = 48,
        min_views: int = 0,
        max_candidates: int = 150
    ) -> Tuple[List[CommentOpportunity], FinderConfig]:
        """
        Find comment opportunities from saved scores in database.

        This is the V1.7 workflow that skips re-scoring and uses existing
        green scores from the generated_comments table.

        Args:
            project_slug: Project slug
            hours_back: Hours to look back
            min_views: Minimum tweet views filter
            max_candidates: Maximum opportunities to return

        Returns:
            Tuple of (opportunities, config)
        """
        logger.info(f"Finding saved comment opportunities for {project_slug}")
        logger.info(f"Filters: hours_back={hours_back}, min_views={min_views}, max={max_candidates}")

        # Load config
        config = load_finder_config(project_slug)

        # Get project ID
        project_result = self.db.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not project_result.data:
            raise ValueError(f"Project not found: {project_slug}")

        project_id = project_result.data['id']

        # Query for saved green scores
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        result = self.db.table('generated_comments') \
            .select('*, posts!inner(*)') \
            .eq('project_id', project_id) \
            .eq('label', 'green') \
            .eq('comment_text', '') \
            .gte('created_at', cutoff.isoformat()) \
            .limit(max_candidates) \
            .execute()

        if not result.data:
            logger.warning(f"No saved green scores found in last {hours_back} hours")
            return ([], config)

        logger.info(f"Found {len(result.data)} saved green scores")

        # Convert database records to CommentOpportunity objects
        opportunities = []
        for record in result.data:
            post_data = record['posts']

            # Parse posted_at
            posted_at = post_data['posted_at']
            if isinstance(posted_at, str):
                posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))

            # Create TweetMetrics
            tweet = TweetMetrics(
                tweet_id=post_data['post_id'],
                text=post_data['caption'],
                author_handle=post_data.get('author_username', 'unknown'),
                author_followers=post_data.get('follower_count', 0),
                tweeted_at=posted_at,
                likes=post_data.get('likes', 0),
                replies=post_data.get('replies', 0),
                retweets=post_data.get('retweets', 0),
                views=post_data.get('views', 0)
            )

            # Filter by min_views
            if min_views > 0 and tweet.views < min_views:
                continue

            # Create ScoringResult from saved data
            score = ScoringResult(
                tweet_id=tweet.tweet_id,
                velocity=record.get('velocity_score', 0.0),
                relevance=record.get('relevance_score', 0.0),
                openness=record.get('openness_score', 0.0),
                author_quality=record.get('author_quality_score', 0.0),
                total_score=record.get('tweet_score', 0.5),
                label=record['label'],
                best_topic=record.get('best_topic_name', 'Unknown'),
                best_topic_similarity=record.get('best_topic_similarity', 0.0),
                passed_gate=True,
                gate_reason=None
            )

            opportunities.append(CommentOpportunity(tweet=tweet, score=score, embedding=None))

        logger.info(f"Found {len(opportunities)} saved opportunities (after min_views filter)")
        return (opportunities, config)

    async def generate_comment_suggestions(
        self,
        project_id: str,
        opportunities: List[CommentOpportunity],
        config: FinderConfig,
        batch_size: int = 5,
        max_requests_per_minute: int = 15,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Generate AI comment suggestions for opportunities.

        Uses async batch processing for efficient API usage.
        Stores embeddings for successful generations.

        Args:
            project_id: Project UUID
            opportunities: List of comment opportunities
            config: Finder configuration
            batch_size: Number of concurrent requests
            max_requests_per_minute: Rate limit for API
            progress_callback: Optional callback for progress updates

        Returns:
            Statistics dict with generated/failed counts and total cost
        """
        logger.info(f"Generating comments for {len(opportunities)} opportunities")
        logger.info(f"Batch size: {batch_size}, Rate limit: {max_requests_per_minute}/min")

        # Convert opportunities to (tweet, score) tuples for async generator
        tweets_with_scores = [(opp.tweet, opp.score) for opp in opportunities]

        # Run async batch generation
        stats = await generate_comments_async(
            project_id=project_id,
            tweets_with_scores=tweets_with_scores,
            config=config,
            batch_size=batch_size,
            max_requests_per_minute=max_requests_per_minute,
            progress_callback=progress_callback
        )

        # Store embeddings for successful tweets
        stored_count = 0
        for opp in opportunities:
            if opp.embedding:
                self._store_tweet_embedding(project_id, opp.tweet.tweet_id, opp.embedding)
                stored_count += 1

        logger.info(f"Stored {stored_count} tweet embeddings for deduplication")
        logger.info(f"Generation complete: {stats['generated']} suggestions generated, "
                   f"{stats['failed']} failed, cost=${stats.get('total_cost_usd', 0.0):.4f}")

        return stats

    def _check_semantic_duplicates(
        self,
        project_id: str,
        tweet_embeddings: List[List[float]],
        threshold: float = SIMILARITY_THRESHOLD
    ) -> List[bool]:
        """
        Check for semantic duplicates using pgvector cosine similarity.

        Args:
            project_id: Project UUID
            tweet_embeddings: List of tweet embedding vectors
            threshold: Cosine similarity threshold

        Returns:
            List of booleans indicating if each tweet is a duplicate
        """
        # Fetch existing embeddings for this project
        result = self.db.table('acceptance_log') \
            .select('foreign_id, embedding') \
            .eq('project_id', project_id) \
            .eq('source', 'twitter') \
            .execute()

        if not result.data:
            # No existing embeddings - all tweets are unique
            return [False] * len(tweet_embeddings)

        # Extract existing embeddings
        existing_embeddings = [
            np.array(record['embedding']) for record in result.data
            if record.get('embedding')
        ]

        if not existing_embeddings:
            return [False] * len(tweet_embeddings)

        # Check each tweet against existing embeddings
        is_duplicate = []
        for tweet_emb in tweet_embeddings:
            tweet_vec = np.array(tweet_emb)

            # Compute cosine similarities with all existing embeddings
            max_similarity = 0.0
            for existing_emb in existing_embeddings:
                # Cosine similarity
                similarity = np.dot(tweet_vec, existing_emb) / (
                    np.linalg.norm(tweet_vec) * np.linalg.norm(existing_emb)
                )
                max_similarity = max(max_similarity, similarity)

            is_duplicate.append(max_similarity >= threshold)

        return is_duplicate

    def _store_tweet_embedding(
        self,
        project_id: str,
        tweet_id: str,
        embedding: List[float]
    ):
        """
        Store tweet embedding in acceptance_log for future deduplication.

        Args:
            project_id: Project UUID
            tweet_id: Tweet ID
            embedding: Tweet embedding vector (768-dim)
        """
        self.db.table('acceptance_log').upsert({
            'project_id': project_id,
            'source': 'twitter',
            'foreign_id': tweet_id,
            'embedding': embedding,
            'created_at': datetime.now(timezone.utc).isoformat()
        }).execute()

    # ========================================================================
    # DATA ACCESS METHODS (EXISTING)
    # ========================================================================

    async def get_comment_opportunities(
        self,
        project: str,
        hours_back: int = 48,
        min_green_flags: int = 3,
        max_candidates: int = 100,
        label_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch comment opportunities from database.

        Args:
            project: Project slug (e.g., 'yakety-pack-instagram')
            hours_back: Hours to look back (default: 48)
            min_green_flags: Minimum green flag score (default: 3)
            max_candidates: Maximum candidates to return (default: 100)
            label_filter: Optional label filter ('green', 'yellow', 'red')

        Returns:
            List of comment opportunity dicts with tweet data and scores

        Note:
            This queries the 'comment_suggestions' table which is populated
            by the CLI command: twitter generate-comments
        """
        logger.info(
            f"Fetching comment opportunities for project '{project}' "
            f"(hours_back: {hours_back}, min_green_flags: {min_green_flags})"
        )

        try:
            # Get project ID
            project_result = self.db.table('projects').select('id').eq('slug', project).single().execute()
            if not project_result.data:
                raise ValueError(f"Project '{project}' not found in database")

            project_id = project_result.data['id']

            # Calculate cutoff time
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            # Build query for comment suggestions
            query = self.db.table('comment_suggestions') \
                .select('*, posts!inner(*)') \
                .eq('project_id', project_id) \
                .gte('created_at', cutoff.isoformat()) \
                .order('score_total', desc=True) \
                .limit(max_candidates)

            # Apply label filter if specified
            if label_filter:
                query = query.eq('label', label_filter)

            result = query.execute()

            if not result.data:
                logger.warning(f"No comment opportunities found for project '{project}'")
                return []

            logger.info(f"Found {len(result.data)} comment opportunities")
            return result.data

        except Exception as e:
            logger.error(f"Error fetching comment opportunities: {e}", exc_info=True)
            return []

    async def export_comment_opportunities(
        self,
        project: str,
        hours_back: int = 48,
        format: str = "json",
        label_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Export comment opportunities in specified format.

        Args:
            project: Project slug
            hours_back: Hours to look back (default: 48)
            format: Export format ('json', 'csv', 'markdown')
            label_filter: Optional label filter ('green', 'yellow', 'red')
            limit: Optional limit on number of results

        Returns:
            List of comment opportunity dicts ready for export
        """
        logger.info(f"Exporting comment opportunities for project '{project}' (format: {format})")

        opportunities = await self.get_comment_opportunities(
            project=project,
            hours_back=hours_back,
            label_filter=label_filter,
            max_candidates=limit or 1000
        )

        # Format data based on export format
        if format == "json":
            return opportunities
        elif format == "csv":
            # Convert to CSV-friendly format
            csv_data = []
            for opp in opportunities:
                csv_data.append({
                    "tweet_id": opp.get("tweet_id"),
                    "tweet_url": opp.get("tweet_url"),
                    "tweet_text": opp.get("tweet_text"),
                    "score": opp.get("score_total"),
                    "label": opp.get("label"),
                    "suggested_comment": opp.get("suggested_response")
                })
            return csv_data
        elif format == "markdown":
            return opportunities

        return opportunities

    # ====================================================================
    # EXPORT METHODS - Export comment suggestions to various formats
    # ====================================================================

    async def export_comments_to_csv(
        self,
        project_slug: str,
        output_filepath: str,
        limit: Optional[int] = None,
        hours_back: Optional[int] = None,
        label_filter: Optional[str] = None,
        status_filter: str = 'pending',
        sort_by: str = 'balanced'
    ) -> Dict[str, Any]:
        """
        Export comment suggestions to CSV file with full tweet metadata.

        This method handles the complete export workflow:
        1. Query database for comment suggestions with filters
        2. Join with tweet/account metadata
        3. Group suggestions by tweet (5 suggestions per tweet)
        4. Sort tweets by priority (score, views, or balanced)
        5. Format as CSV with primary + 4 alternatives
        6. Update status to 'exported' if originally 'pending'

        Args:
            project_slug: Project slug to export comments for
            output_filepath: Path to output CSV file
            limit: Maximum number of tweets to export (None = all)
            hours_back: Only export from last N hours (None = all time)
            label_filter: Filter by label: 'green', 'yellow', or 'red' (None = all)
            status_filter: Filter by status (default: 'pending')
            sort_by: Sort method - 'score' (quality), 'views' (reach), or 'balanced' (score×√views)

        Returns:
            Dict with export statistics:
                - tweets_exported: Number of tweets written to CSV
                - suggestions_exported: Total suggestion count (tweets × 5)
                - status_updated: Number of suggestions updated to 'exported'
                - label_distribution: Dict mapping labels to counts
                - output_file: Path to output CSV file

        Raises:
            ValueError: If project not found or no suggestions match criteria
        """
        import csv
        import math
        from collections import defaultdict

        logger.info(f"Exporting comments for project '{project_slug}' to {output_filepath}")

        # Get project ID
        db = get_supabase_client()
        project_result = db.table('projects').select('id').eq('slug', project_slug).single().execute()

        if not project_result.data:
            raise ValueError(f"Project '{project_slug}' not found")

        project_id = project_result.data['id']

        # Query generated_comments with tweet metadata (using JOIN)
        query = db.table('generated_comments')\
            .select('*, posts(post_id, caption, posted_at, views, accounts(platform_username, follower_count))')\
            .eq('project_id', project_id)\
            .eq('status', status_filter)\
            .order('score_total', desc=True)

        if label_filter:
            query = query.eq('label', label_filter)

        # Filter by time range if specified
        if hours_back:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            query = query.gte('created_at', cutoff.isoformat())

        result = query.execute()

        if not result.data:
            raise ValueError(f"No suggestions found matching criteria")

        logger.info(f"Found {len(result.data)} suggestions from database")

        # Group by tweet_id (each tweet has 5 suggestions in V1.3)
        tweets_map = defaultdict(list)
        for suggestion in result.data:
            tweets_map[suggestion['tweet_id']].append(suggestion)

        # Sort tweets based on sort_by parameter
        if sort_by == 'score':
            # Sort by score only (quality)
            sorted_tweets = sorted(
                tweets_map.items(),
                key=lambda x: max(s['score_total'] for s in x[1]),
                reverse=True
            )
        elif sort_by == 'views':
            # Sort by views only (reach)
            def get_views(item):
                suggestions = item[1]
                for s in suggestions:
                    post_data = s.get('posts')
                    if post_data:
                        return post_data.get('views', 0) or 0
                return 0
            sorted_tweets = sorted(tweets_map.items(), key=get_views, reverse=True)
        else:  # balanced (default)
            # Sort by score × √views (balanced quality + reach)
            def get_priority(item):
                suggestions = item[1]
                score = max(s['score_total'] for s in suggestions)
                for s in suggestions:
                    post_data = s.get('posts')
                    if post_data:
                        views = post_data.get('views', 0) or 0
                        return score * math.sqrt(views)
                return score  # Fallback if no views data
            sorted_tweets = sorted(tweets_map.items(), key=get_priority, reverse=True)

        # Apply limit if specified
        if limit is not None:
            sorted_tweets = sorted_tweets[:limit]

        logger.info(f"Grouped into {len(sorted_tweets)} tweets (after limit)")

        # Write CSV
        fieldnames = [
            'rank', 'priority_score',  # Prioritization columns
            'project', 'tweet_id', 'url', 'author', 'followers', 'views', 'tweet_text', 'posted_at',
            'score_total', 'label', 'topic', 'why',
            'suggested_response', 'suggested_type',
            'alternative_1', 'alt_1_type',
            'alternative_2', 'alt_2_type',
            'alternative_3', 'alt_3_type',
            'alternative_4', 'alt_4_type'
        ]

        rows_written = 0
        all_comment_ids = []

        with open(output_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for rank_num, (tweet_id, suggestions) in enumerate(sorted_tweets, 1):
                # Sort by rank (1=primary, 2-5=alternatives)
                suggestions_sorted = sorted(suggestions, key=lambda s: s.get('rank', 1))

                # Primary suggestion (rank=1)
                primary = suggestions_sorted[0]
                alts = suggestions_sorted[1:5]  # Get all 4 alternatives

                # Collect comment IDs for status update
                all_comment_ids.extend([s['id'] for s in suggestions])

                # Extract tweet metadata from joined posts/accounts data
                post_data = primary.get('posts')
                tweet_text = ''
                author = ''
                followers = 0
                views = 0
                posted_at = ''

                if post_data:
                    tweet_text = post_data.get('caption', '')
                    posted_at = post_data.get('posted_at', '')
                    views = post_data.get('views', 0) or 0
                    account_data = post_data.get('accounts')
                    if account_data:
                        author = account_data.get('platform_username', '')
                        followers = account_data.get('follower_count', 0) or 0

                # Calculate priority_score based on sort method
                score = primary['score_total']
                if sort_by == 'views':
                    priority_score = views
                elif sort_by == 'balanced':
                    priority_score = score * math.sqrt(views)
                else:  # score
                    priority_score = score

                row = {
                    'rank': rank_num,
                    'priority_score': round(priority_score, 2),
                    'project': project_slug,
                    'tweet_id': tweet_id,
                    'url': f"https://twitter.com/i/status/{tweet_id}",
                    'author': author,
                    'followers': followers,
                    'views': views,
                    'tweet_text': tweet_text,
                    'posted_at': posted_at,
                    'score_total': round(primary['score_total'], 3),
                    'label': primary['label'],
                    'topic': primary.get('topic', ''),
                    'why': primary.get('why', ''),
                    'suggested_response': primary['comment_text'],
                    'suggested_type': primary['suggestion_type'],
                    'alternative_1': alts[0]['comment_text'] if len(alts) > 0 else '',
                    'alt_1_type': alts[0]['suggestion_type'] if len(alts) > 0 else '',
                    'alternative_2': alts[1]['comment_text'] if len(alts) > 1 else '',
                    'alt_2_type': alts[1]['suggestion_type'] if len(alts) > 1 else '',
                    'alternative_3': alts[2]['comment_text'] if len(alts) > 2 else '',
                    'alt_3_type': alts[2]['suggestion_type'] if len(alts) > 2 else '',
                    'alternative_4': alts[3]['comment_text'] if len(alts) > 3 else '',
                    'alt_4_type': alts[3]['suggestion_type'] if len(alts) > 3 else '',
                }

                writer.writerow(row)
                rows_written += 1

        logger.info(f"Wrote {rows_written} tweets to {output_filepath}")

        # Update status to 'exported' if originally 'pending'
        status_updated = 0
        if status_filter == 'pending' and all_comment_ids:
            # Batch update to avoid URL length limits (100 IDs per batch)
            batch_size = 100
            for i in range(0, len(all_comment_ids), batch_size):
                batch = all_comment_ids[i:i + batch_size]
                db.table('generated_comments')\
                    .update({'status': 'exported'})\
                    .in_('id', batch)\
                    .execute()
                status_updated += len(batch)

            logger.info(f"Updated {status_updated} suggestions to 'exported' status")

        # Calculate label distribution
        label_distribution = {}
        for tweet_id, suggestions in sorted_tweets:
            label = suggestions[0]['label']  # All suggestions for a tweet have same label
            label_distribution[label] = label_distribution.get(label, 0) + 1

        return {
            'tweets_exported': rows_written,
            'suggestions_exported': rows_written * 5,  # 5 suggestions per tweet
            'status_updated': status_updated,
            'label_distribution': label_distribution,
            'output_file': output_filepath
        }

    async def get_comment_stats(
        self,
        project: str,
        hours_back: int = 48
    ) -> Dict[str, Any]:
        """
        Get statistics about comment opportunities.

        Args:
            project: Project slug
            hours_back: Hours to look back (default: 48)

        Returns:
            Dict with statistics (total, greens, yellows, reds, avg_score)
        """
        opportunities = await self.get_comment_opportunities(
            project=project,
            hours_back=hours_back,
            max_candidates=10000
        )

        if not opportunities:
            return {
                "total": 0,
                "greens": 0,
                "yellows": 0,
                "reds": 0,
                "avg_score": 0.0
            }

        # Count by label
        labels = [opp.get("label", "unknown") for opp in opportunities]
        greens = labels.count("green")
        yellows = labels.count("yellow")
        reds = labels.count("red")

        # Calculate average score
        scores = [opp.get("score_total", 0.0) for opp in opportunities]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return {
            "total": len(opportunities),
            "greens": greens,
            "yellows": yellows,
            "reds": reds,
            "avg_score": avg_score
        }
