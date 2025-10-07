"""
TikTok CLI Commands

Commands for scraping and analyzing TikTok content.
"""

import logging
from typing import Optional

import click
import pandas as pd

from ..scrapers.tiktok import TikTokScraper
from ..core.database import get_supabase_client


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


@click.group(name="tiktok")
def tiktok_group():
    """TikTok scraping and analysis"""
    pass


@tiktok_group.command(name="search")
@click.argument('keyword')
@click.option('--count', '-c', default=50, type=int, help='Number of posts to fetch (default: 50)')
@click.option('--min-views', default=100000, type=int, help='Minimum views (default: 100K)')
@click.option('--max-days', default=10, type=int, help='Maximum age in days (default: 10)')
@click.option('--max-followers', default=50000, type=int, help='Maximum creator follower count (default: 50K)')
@click.option('--project', '-p', help='Project slug to link posts to (optional)')
@click.option('--save/--no-save', default=True, help='Save results to database (default: True)')
@click.option('--sort', default=0, type=int, help='Sort: 0=Relevance, 1=Most Liked, 3=Date (default: 0)')
def search_keyword(
    keyword: str,
    count: int,
    min_views: int,
    max_days: int,
    max_followers: int,
    project: Optional[str],
    save: bool,
    sort: int
):
    """
    Search TikTok by keyword with viral filtering

    Finds viral content from micro-influencers (<50K followers)
    that got significant engagement (>100K views) recently (<10 days).

    Examples:
        vt tiktok search "productivity apps"
        vt tiktok search "time management" --count 100
        vt tiktok search "notion tips" --project yakety-pack --save
        vt tiktok search "app reviews" --min-views 50000 --max-followers 100000
    """
    try:
        click.echo(f"\n{'='*60}")
        click.echo(f"🔍 TikTok Keyword Search")
        click.echo(f"{'='*60}\n")

        click.echo(f"Keyword: \"{keyword}\"")
        click.echo(f"Count: {count}")
        click.echo(f"Filters:")
        click.echo(f"  - Views: {min_views:,}+")
        click.echo(f"  - Age: <{max_days} days")
        click.echo(f"  - Creator followers: <{max_followers:,}")
        if project:
            click.echo(f"Project: {project}")
        click.echo()

        # Initialize scraper
        scraper = TikTokScraper()

        # Search
        df, total_scraped = scraper.search_by_keyword(
            keyword=keyword,
            count=count,
            min_views=min_views,
            max_days_old=max_days,
            max_follower_count=max_followers,
            sort_type=sort
        )

        if len(df) == 0:
            click.echo("❌ No posts found matching criteria")
            click.echo("\n💡 Try:")
            click.echo("   - Lowering filters (--min-views, --max-followers)")
            click.echo("   - Increasing count (--count)")
            click.echo("   - Expanding time range (--max-days)")
            return

        # Display results
        click.echo(f"\n📊 Results:")
        click.echo(f"   Total scraped: {total_scraped}")
        click.echo(f"   After filtering: {len(df)}")
        click.echo()

        # Show top results
        click.echo("Top 5 Results:")
        for idx, row in df.head(5).iterrows():
            click.echo(f"\n  {idx + 1}. @{row['username']} ({row['follower_count']:,} followers)")
            click.echo(f"     Views: {row['views']:,} | Likes: {row['likes']:,} | Comments: {row['comments']:,}")
            click.echo(f"     Caption: {row['caption'][:80]}...")
            click.echo(f"     URL: {row['post_url']}")

        # Save to database if requested
        if save:
            click.echo(f"\n💾 Saving to database...")

            # Get project ID if specified
            project_id = None
            if project:
                supabase = get_supabase_client()
                project_result = supabase.table("projects").select("id").eq("slug", project).execute()
                if project_result.data:
                    project_id = project_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Warning: Project '{project}' not found. Posts will be saved without project link.")

            # Save posts
            post_ids = scraper.save_posts_to_db(df, project_id=project_id, import_source="scrape")

            click.echo(f"✅ Saved {len(post_ids)} posts to database")

            if project_id:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Download videos: vt process videos --project {project}")
                click.echo(f"   - Analyze videos: vt analyze videos --project {project}")
        else:
            click.echo(f"\n💡 Results not saved (use --save to save to database)")

        click.echo()

    except Exception as e:
        click.echo(f"\n❌ Search failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


@tiktok_group.command(name="hashtag")
@click.argument('hashtag')
@click.option('--count', '-c', default=50, type=int, help='Number of posts to fetch (default: 50)')
@click.option('--min-views', default=100000, type=int, help='Minimum views (default: 100K)')
@click.option('--max-days', default=10, type=int, help='Maximum age in days (default: 10)')
@click.option('--max-followers', default=50000, type=int, help='Maximum creator follower count (default: 50K)')
@click.option('--project', '-p', help='Project slug to link posts to (optional)')
@click.option('--save/--no-save', default=True, help='Save results to database (default: True)')
def search_hashtag(
    hashtag: str,
    count: int,
    min_views: int,
    max_days: int,
    max_followers: int,
    project: Optional[str],
    save: bool
):
    """
    Search TikTok by hashtag with viral filtering

    Tracks specific hashtags to find viral content from micro-influencers.

    Examples:
        vt tiktok hashtag productivityhack
        vt tiktok hashtag appreviews --count 100
        vt tiktok hashtag studytok --project yakety-pack --save
    """
    try:
        # Remove # if user included it
        hashtag = hashtag.lstrip('#')

        click.echo(f"\n{'='*60}")
        click.echo(f"#️⃣ TikTok Hashtag Search")
        click.echo(f"{'='*60}\n")

        click.echo(f"Hashtag: #{hashtag}")
        click.echo(f"Count: {count}")
        click.echo(f"Filters:")
        click.echo(f"  - Views: {min_views:,}+")
        click.echo(f"  - Age: <{max_days} days")
        click.echo(f"  - Creator followers: <{max_followers:,}")
        if project:
            click.echo(f"Project: {project}")
        click.echo()

        # Initialize scraper
        scraper = TikTokScraper()

        # Search
        df, total_scraped = scraper.search_by_hashtag(
            hashtag=hashtag,
            count=count,
            min_views=min_views,
            max_days_old=max_days,
            max_follower_count=max_followers
        )

        if len(df) == 0:
            click.echo("❌ No posts found matching criteria")
            click.echo("\n💡 Try:")
            click.echo("   - Lowering filters (--min-views, --max-followers)")
            click.echo("   - Increasing count (--count)")
            click.echo("   - Expanding time range (--max-days)")
            return

        # Display results
        click.echo(f"\n📊 Results:")
        click.echo(f"   Total scraped: {total_scraped}")
        click.echo(f"   After filtering: {len(df)}")
        click.echo()

        # Show top results
        click.echo("Top 5 Results:")
        for idx, row in df.head(5).iterrows():
            click.echo(f"\n  {idx + 1}. @{row['username']} ({row['follower_count']:,} followers)")
            click.echo(f"     Views: {row['views']:,} | Likes: {row['likes']:,} | Comments: {row['comments']:,}")
            click.echo(f"     Caption: {row['caption'][:80]}...")
            click.echo(f"     URL: {row['post_url']}")

        # Save to database if requested
        if save:
            click.echo(f"\n💾 Saving to database...")

            # Get project ID if specified
            project_id = None
            if project:
                supabase = get_supabase_client()
                project_result = supabase.table("projects").select("id").eq("slug", project).execute()
                if project_result.data:
                    project_id = project_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Warning: Project '{project}' not found. Posts will be saved without project link.")

            # Save posts
            post_ids = scraper.save_posts_to_db(df, project_id=project_id, import_source="scrape")

            click.echo(f"✅ Saved {len(post_ids)} posts to database")

            if project_id:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Download videos: vt process videos --project {project}")
                click.echo(f"   - Analyze videos: vt analyze videos --project {project}")
        else:
            click.echo(f"\n💡 Results not saved (use --save to save to database)")

        click.echo()

    except Exception as e:
        click.echo(f"\n❌ Hashtag search failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


@tiktok_group.command(name="user")
@click.argument('username')
@click.option('--count', '-c', default=50, type=int, help='Number of posts to fetch (default: 50)')
@click.option('--project', '-p', help='Project slug to link posts to (optional)')
@click.option('--save/--no-save', default=True, help='Save results to database (default: True)')
@click.option('--analyze-outliers/--no-analyze-outliers', default=False, help='Run outlier detection after scraping')
def scrape_user(
    username: str,
    count: int,
    project: Optional[str],
    save: bool,
    analyze_outliers: bool
):
    """
    Scrape posts from a TikTok user/creator

    For per-user outlier detection (3 SD from user's trimmed mean).
    No filtering applied - fetches all posts to calculate baseline.

    Examples:
        vt tiktok user mrbeast
        vt tiktok user alexhormozi --count 100
        vt tiktok user productivityguru --project yakety-pack --save
        vt tiktok user creator123 --analyze-outliers
    """
    try:
        # Remove @ if user included it
        username = username.lstrip('@')

        click.echo(f"\n{'='*60}")
        click.echo(f"👤 TikTok User Scraper")
        click.echo(f"{'='*60}\n")

        click.echo(f"Username: @{username}")
        click.echo(f"Count: {count}")
        if project:
            click.echo(f"Project: {project}")
        click.echo()

        # Initialize scraper
        scraper = TikTokScraper()

        # Scrape user
        df = scraper.scrape_user(
            username=username,
            count=count
        )

        if len(df) == 0:
            click.echo(f"❌ No posts found for @{username}")
            click.echo("\n💡 Check:")
            click.echo("   - Username is correct")
            click.echo("   - Account is public")
            click.echo("   - Account has posts")
            return

        # Display results
        click.echo(f"\n📊 Results:")
        click.echo(f"   Posts scraped: {len(df)}")
        click.echo()

        # Show statistics
        click.echo("Account Statistics:")
        click.echo(f"  Follower count: {df.iloc[0]['follower_count']:,}")
        click.echo(f"  Total views: {df['views'].sum():,}")
        click.echo(f"  Avg views: {df['views'].mean():,.0f}")
        click.echo(f"  Median views: {df['views'].median():,.0f}")
        click.echo(f"  Max views: {df['views'].max():,}")
        click.echo()

        # Show top 5 posts by views
        click.echo("Top 5 Posts by Views:")
        for idx, row in df.nlargest(5, 'views').iterrows():
            click.echo(f"\n  {idx + 1}. {row['views']:,} views")
            click.echo(f"     Likes: {row['likes']:,} | Comments: {row['comments']:,}")
            click.echo(f"     Caption: {row['caption'][:80]}...")
            click.echo(f"     URL: {row['post_url']}")

        # Save to database if requested
        if save:
            click.echo(f"\n💾 Saving to database...")

            # Get project ID if specified
            project_id = None
            if project:
                supabase = get_supabase_client()
                project_result = supabase.table("projects").select("id").eq("slug", project).execute()
                if project_result.data:
                    project_id = project_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Warning: Project '{project}' not found. Posts will be saved without project link.")

            # Save posts
            post_ids = scraper.save_posts_to_db(df, project_id=project_id, import_source="scrape")

            click.echo(f"✅ Saved {len(post_ids)} posts to database")

            # Run outlier detection if requested
            if analyze_outliers and project_id:
                click.echo(f"\n📊 Running outlier detection...")
                # Import here to avoid circular dependency
                from .analyze import analyze_outliers
                ctx = click.get_current_context()
                ctx.invoke(analyze_outliers, project=project, sd_threshold=3.0)

            if project_id:
                click.echo(f"\n💡 Next steps:")
                if not analyze_outliers:
                    click.echo(f"   - Detect outliers: vt analyze outliers --project {project}")
                click.echo(f"   - Download videos: vt process videos --project {project}")
                click.echo(f"   - Analyze videos: vt analyze videos --project {project}")
        else:
            click.echo(f"\n💡 Results not saved (use --save to save to database)")

        click.echo()

    except Exception as e:
        click.echo(f"\n❌ User scraping failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()
