"""
Scrape command for ViralTracker CLI
"""

import click
import logging
from ..scrapers.instagram import InstagramScraper


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


@click.command('scrape')
@click.option('--project', '-p', required=True, help='Project slug (required)')
@click.option('--days-back', '-d', default=120, type=int, help='Days to scrape back (default: 120)')
@click.option('--post-type', '-t', default='reels',
              type=click.Choice(['reels', 'posts', 'tagged']),
              help='Post type to scrape (default: reels)')
@click.option('--timeout', default=300, type=int, help='Apify timeout in seconds (default: 300)')
def scrape_command(project: str, days_back: int, post_type: str, timeout: int):
    """
    Scrape Instagram accounts linked to a project

    This command:
    1. Queries accounts linked to the project
    2. Scrapes their Instagram posts using Apify
    3. Saves posts with metadata and links them to the project
    4. Populates metadata for previously imported URLs

    Examples:
        vt scrape --project yakety-pack-instagram
        vt scrape --project my-project --days-back 30
        vt scrape --project my-project --post-type posts --timeout 600
    """
    try:
        click.echo(f"\n{'='*60}")
        click.echo(f"🔍 Instagram Scraper")
        click.echo(f"{'='*60}\n")

        click.echo(f"Project: {project}")
        click.echo(f"Days back: {days_back}")
        click.echo(f"Post type: {post_type}")
        click.echo(f"Timeout: {timeout}s\n")

        # Initialize scraper
        scraper = InstagramScraper()

        # Scrape project
        accounts_scraped, posts_scraped = scraper.scrape_project(
            project_slug=project,
            days_back=days_back,
            post_type=post_type,
            timeout=timeout
        )

        # Display summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Scraping Complete!")
        click.echo(f"{'='*60}\n")
        click.echo(f"📊 Summary:")
        click.echo(f"   Accounts scraped: {accounts_scraped}")
        click.echo(f"   Posts scraped: {posts_scraped}")
        click.echo(f"\n💡 Next steps:")
        click.echo(f"   - View posts: vt project show {project}")
        click.echo(f"   - Import more URLs: vt import url <url> --project {project}")
        click.echo()

    except ValueError as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        click.echo(f"\n💡 Tips:", err=True)
        click.echo(f"   - Check project exists: vt project show {project}", err=True)
        click.echo(f"   - List projects: vt project list", err=True)
        click.echo(f"   - Add accounts to project: vt project add-accounts {project} <file>", err=True)
        click.echo()
        raise click.Abort()

    except Exception as e:
        click.echo(f"\n❌ Scraping failed: {e}", err=True)
        click.echo()
        raise click.Abort()
