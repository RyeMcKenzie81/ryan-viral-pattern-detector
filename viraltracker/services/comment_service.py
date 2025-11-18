"""
CommentService - Data access layer for comment opportunity detection.

Provides async interface to comment opportunities stored in the database.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from ..core.database import get_supabase_client
from .models import CommentCandidate, Tweet

logger = logging.getLogger(__name__)


class CommentService:
    """
    Data access service for comment opportunities.

    Provides clean interface to fetch, rank, and export comment
    opportunities from the database.
    """

    def __init__(self):
        """Initialize comment service with Supabase client"""
        self.db = get_supabase_client()
        logger.info("CommentService initialized")

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
