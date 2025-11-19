"""
YouTube CLI Commands

Commands for scraping and analyzing YouTube content (Shorts and videos).
"""

import logging
from typing import Optional

import click

from ..scrapers.youtube_search import YouTubeSearchScraper
from ..core.database import get_supabase_client


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


@click.group(name="youtube")
def youtube_group():
    """YouTube scraping and analysis"""
    pass


@youtube_group.command(name="search")
@click.option('--terms', required=True, help='Comma-separated search terms (e.g., "dog training,puppy tricks")')
@click.option('--max-shorts', default=100, type=int, help='Max Shorts per term (default: 100)')
@click.option('--max-videos', default=0, type=int, help='Max regular videos per term (default: 0)')
@click.option('--max-streams', default=0, type=int, help='Max live streams per term (default: 0)')
@click.option('--days-back', type=int, help='Only videos from last N days (optional)')
@click.option('--min-views', type=int, help='Minimum view count filter (optional)')
@click.option('--min-subscribers', type=int, help='Minimum channel subscriber count (optional)')
@click.option('--max-subscribers', type=int, help='Maximum channel subscriber count (optional)')
@click.option('--sort-by', default='views', type=click.Choice(['views', 'date', 'relevance', 'rating']), help='Sort by (default: views)')
@click.option('--project', '-p', help='Project slug to link results to (optional)')
def youtube_search(
    terms: str,
    max_shorts: int,
    max_videos: int,
    max_streams: int,
    days_back: Optional[int],
    min_views: Optional[int],
    min_subscribers: Optional[int],
    max_subscribers: Optional[int],
    sort_by: str,
    project: Optional[str]
):
    """
    Search YouTube for videos/Shorts by keyword

    Enables keyword/hashtag discovery for YouTube content. Separate limits
    for Shorts, regular videos, and live streams. Results are automatically
    classified by video_type for proper analysis.

    Examples:
        # Shorts only (default)
        vt youtube search --terms "dog training" --max-shorts 50

        # With filters
        vt youtube search --terms "viral dogs" --max-shorts 100 --days-back 7 --min-views 100000

        # Find viral content from micro-influencers
        vt youtube search --terms "dog training" --max-shorts 100 --min-views 100000 --max-subscribers 50000

        # Link to project
        vt youtube search --terms "golden retriever" --max-shorts 50 --project wonder-paws-tiktok

        # Mixed content (Shorts + videos)
        vt youtube search --terms "puppy guide" --max-shorts 20 --max-videos 30
    """
    try:
        # Parse search terms
        search_terms = [t.strip() for t in terms.split(',')]

        click.echo(f"\n{'='*60}")
        click.echo(f"🔍 YouTube Search")
        click.echo(f"{'='*60}\n")

        click.echo(f"Search terms: {', '.join(search_terms)}")
        click.echo(f"Limits:")
        click.echo(f"  - Shorts: {max_shorts}")
        click.echo(f"  - Videos: {max_videos}")
        click.echo(f"  - Streams: {max_streams}")

        # Display filters if any are set
        filters = []
        if days_back:
            filters.append(f"Last {days_back} days")
        if min_views:
            filters.append(f"{min_views:,}+ views")
        if min_subscribers:
            filters.append(f"{min_subscribers:,}+ subscribers")
        if max_subscribers:
            filters.append(f"<{max_subscribers:,} subscribers")

        if filters:
            click.echo(f"Filters:")
            for f in filters:
                click.echo(f"  - {f}")

        click.echo(f"Sort by: {sort_by}")

        if project:
            click.echo(f"Project: {project}")
        click.echo()

        # Initialize scraper
        scraper = YouTubeSearchScraper()

        # Search
        click.echo("🔄 Starting YouTube search...")
        terms_count, videos_count = scraper.scrape_search(
            search_terms=search_terms,
            max_shorts=max_shorts,
            max_videos=max_videos,
            max_streams=max_streams,
            days_back=days_back,
            min_views=min_views,
            min_subscribers=min_subscribers,
            max_subscribers=max_subscribers,
            sort_by=sort_by,
            project_slug=project
        )

        # Display results
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Search Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Results:")
        click.echo(f"   Search terms: {terms_count}")
        click.echo(f"   Videos scraped: {videos_count}")

        if videos_count == 0:
            click.echo("\n⚠️  No videos found")
            click.echo("\n💡 Try:")
            click.echo("   - Lowering filters (--min-views)")
            click.echo("   - Increasing limits (--max-shorts, --max-videos)")
            click.echo("   - Expanding time range (--days-back)")
        else:
            click.echo(f"\n✅ Saved {videos_count} videos to database")

            if project:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Download videos: vt process videos --project {project}")
                click.echo(f"   - Analyze videos: vt analyze videos --project {project}")
            else:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Link to project: Use --project flag to organize results")
                click.echo(f"   - Or create project: vt projects create")

        click.echo(f"\n{'='*60}\n")

    except Exception as e:
        click.echo(f"\n❌ Search failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


# Export the command group
youtube = youtube_group
