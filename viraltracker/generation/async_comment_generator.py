"""
Async Comment Generator - Batch Processing for 5x Speed Improvement

Wraps the synchronous CommentGenerator with async/await for concurrent batch processing.
Uses ThreadPoolExecutor to handle I/O-bound API calls efficiently.

V1.2 Feature 3.1: Async Batch Generation
"""

import asyncio
import time
import logging
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from viraltracker.generation.comment_generator import (
    CommentGenerator,
    GenerationResult,
    save_suggestions_to_db
)
from viraltracker.generation.cost_tracking import format_cost_summary
from viraltracker.generation.comment_finder import TweetMetrics, ScoringResult
from viraltracker.core.config import FinderConfig

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """
    Async-compatible rate limiter with sliding window tracking.

    Enforces max_per_minute limit across concurrent async tasks.
    """

    def __init__(self, max_per_minute: int = 15):
        """
        Initialize async rate limiter.

        Args:
            max_per_minute: Maximum API calls allowed per minute
        """
        self.max_rpm = max_per_minute
        self.call_times: List[float] = []
        self.lock = asyncio.Lock()

    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded"""
        async with self.lock:
            now = time.time()

            # Remove calls older than 1 minute
            self.call_times = [t for t in self.call_times if now - t < 60]

            # If at limit, wait until oldest call expires
            if len(self.call_times) >= self.max_rpm:
                sleep_time = 60 - (now - self.call_times[0]) + 0.1  # Small buffer
                if sleep_time > 0:
                    logger.info(f"Rate limit reached ({self.max_rpm} req/min). Waiting {sleep_time:.1f}s...")
                    await asyncio.sleep(sleep_time)
                    # Clean up after waiting
                    now = time.time()
                    self.call_times = [t for t in self.call_times if now - t < 60]

    async def record_call(self) -> None:
        """Record an API call"""
        async with self.lock:
            self.call_times.append(time.time())

    def get_current_rate(self) -> int:
        """Get current calls per minute"""
        now = time.time()
        return sum(1 for t in self.call_times if now - t <= 60)


class AsyncCommentGenerator:
    """
    Async wrapper for CommentGenerator enabling concurrent batch processing.

    Uses ThreadPoolExecutor to run sync API calls concurrently while respecting
    rate limits and maintaining backward compatibility.

    Example:
        generator = AsyncCommentGenerator(batch_size=5)
        results = await generator.generate_batch_async(tweets, topics, config)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_requests_per_minute: int = 15,
        batch_size: int = 5,
        max_workers: int = 10
    ):
        """
        Initialize async comment generator.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            max_requests_per_minute: Rate limit for API calls (default: 15)
            batch_size: Number of concurrent requests (default: 5)
            max_workers: Max thread pool workers (default: 10)
        """
        # Initialize sync generator
        self.sync_generator = CommentGenerator(api_key, max_requests_per_minute)

        # Async rate limiting
        self.rate_limiter = AsyncRateLimiter(max_requests_per_minute)

        # Concurrency control
        self.batch_size = batch_size
        self.semaphore = asyncio.Semaphore(batch_size)

        # Thread pool for running sync API calls
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        logger.info(f"AsyncCommentGenerator initialized: batch_size={batch_size}, rate_limit={max_requests_per_minute}/min")

    async def generate_suggestions_async(
        self,
        tweet: TweetMetrics,
        topic: str,
        config: FinderConfig
    ) -> GenerationResult:
        """
        Generate comment suggestions asynchronously.

        Args:
            tweet: Tweet to generate comments for
            topic: Best-match taxonomy topic label
            config: Finder configuration

        Returns:
            GenerationResult with suggestions or error
        """
        async with self.semaphore:
            # Wait for rate limit
            await self.rate_limiter.wait_if_needed()

            # Run sync call in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self.sync_generator.generate_suggestions,
                tweet,
                topic,
                config
            )

            # Record call for rate tracking
            await self.rate_limiter.record_call()

            return result

    async def generate_batch_async(
        self,
        tweets: List[TweetMetrics],
        topics: List[str],
        config: FinderConfig
    ) -> List[GenerationResult]:
        """
        Generate suggestions for multiple tweets concurrently.

        Processes tweets in parallel up to batch_size limit, while respecting
        rate limits. Continues processing even if some tweets fail.

        Args:
            tweets: List of tweets to process
            topics: List of topic labels (must match len(tweets))
            config: Finder configuration

        Returns:
            List of GenerationResult objects (may include errors)
        """
        if len(tweets) != len(topics):
            raise ValueError(f"Tweets and topics length mismatch: {len(tweets)} != {len(topics)}")

        logger.info(f"Starting batch generation: {len(tweets)} tweets, batch_size={self.batch_size}")

        # Create tasks for all tweets
        tasks = [
            self.generate_suggestions_async(tweet, topic, config)
            for tweet, topic in zip(tweets, topics)
        ]

        # Run all tasks concurrently (semaphore limits actual concurrency)
        # return_exceptions=True means failures don't stop other tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to GenerationResult objects
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to process tweet {tweets[i].tweet_id}: {result}")
                processed_results.append(GenerationResult(
                    tweet_id=tweets[i].tweet_id,
                    suggestions=[],
                    success=False,
                    error=str(result)
                ))
            else:
                processed_results.append(result)

        # Log summary
        successful = sum(1 for r in processed_results if r.success)
        failed = len(processed_results) - successful
        logger.info(f"Batch complete: {successful} succeeded, {failed} failed")

        return processed_results

    async def generate_and_save_batch_async(
        self,
        project_id: str,
        tweets_with_scores: List[Tuple[TweetMetrics, ScoringResult]],
        config: FinderConfig,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, int]:
        """
        Generate suggestions and save to database in batches.

        High-level method that handles the full pipeline:
        - Batch generation
        - Quality filtering
        - Database storage
        - Progress tracking

        Args:
            project_id: Project UUID
            tweets_with_scores: List of (tweet, scoring_result) tuples
            config: Finder configuration
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Dict with statistics:
            - generated: Total suggestions generated
            - saved: Total suggestions saved to DB
            - failed: Total tweets that failed
        """
        total = len(tweets_with_scores)
        logger.info(f"Processing {total} tweets with batch generation (batch_size={self.batch_size})")

        stats = {
            'generated': 0,
            'saved': 0,
            'failed': 0,
            'total_cost_usd': 0.0  # V1.2: Track total API cost
        }

        # Process all tweets
        tweets = [t for t, _ in tweets_with_scores]
        scoring_results = [s for _, s in tweets_with_scores]
        topics = [s.best_topic for s in scoring_results]

        # Generate in batches
        results = await self.generate_batch_async(tweets, topics, config)

        # Save results to database
        for i, result in enumerate(results):
            tweet = tweets[i]
            scoring_result = scoring_results[i]

            if result.success and len(result.suggestions) > 0:
                # Save to database (V1.2: include cost)
                try:
                    save_suggestions_to_db(
                        project_id=project_id,
                        tweet_id=tweet.tweet_id,
                        suggestions=result.suggestions,
                        scoring_result=scoring_result,
                        tweet=tweet,
                        api_cost_usd=result.api_cost_usd  # V1.2: Pass cost
                    )
                    stats['generated'] += len(result.suggestions)
                    stats['saved'] += len(result.suggestions)

                    # V1.2: Track total cost
                    if result.api_cost_usd is not None:
                        stats['total_cost_usd'] += result.api_cost_usd

                except Exception as e:
                    logger.error(f"Failed to save suggestions for tweet {tweet.tweet_id}: {e}")
                    stats['failed'] += 1
            else:
                stats['failed'] += 1

            # Progress callback
            if progress_callback:
                progress_callback(i + 1, total)

        logger.info(f"Batch processing complete: {stats}")
        return stats

    def cleanup(self):
        """Shutdown thread pool executor"""
        self.executor.shutdown(wait=True)
        logger.info("AsyncCommentGenerator cleaned up")

    def __del__(self):
        """Cleanup on deletion"""
        try:
            self.cleanup()
        except:
            pass


# Convenience function for CLI
async def generate_comments_async(
    project_id: str,
    tweets_with_scores: List[Tuple[TweetMetrics, ScoringResult]],
    config: FinderConfig,
    batch_size: int = 5,
    max_requests_per_minute: int = 15,
    progress_callback: Optional[callable] = None
) -> Dict[str, int]:
    """
    Generate comment suggestions for tweets using async batch processing.

    Convenience function for CLI that handles generator lifecycle.

    Args:
        project_id: Project UUID
        tweets_with_scores: List of (tweet, scoring_result) tuples
        config: Finder configuration
        batch_size: Number of concurrent requests (default: 5)
        max_requests_per_minute: Rate limit (default: 15)
        progress_callback: Optional callback(current, total) for progress

    Returns:
        Dict with statistics (generated, saved, failed)
    """
    generator = AsyncCommentGenerator(
        batch_size=batch_size,
        max_requests_per_minute=max_requests_per_minute
    )

    try:
        stats = await generator.generate_and_save_batch_async(
            project_id=project_id,
            tweets_with_scores=tweets_with_scores,
            config=config,
            progress_callback=progress_callback
        )
        return stats
    finally:
        generator.cleanup()
