"""
Twitter CLI Commands

Commands for scraping and analyzing Twitter content.
"""

import logging
from typing import Optional

import click

from ..scrapers.twitter import TwitterScraper
from ..core.database import get_supabase_client


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


@click.group(name="twitter")
def twitter_group():
    """Twitter scraping and analysis"""
    pass


@twitter_group.command(name="search")
@click.option('--terms', required=True, help='Search terms or raw query (e.g., "dog training" or "from:NASA filter:video")')
@click.option('--count', default=100, type=int, help='Max tweets to scrape (min 50, default: 100)')
@click.option('--min-likes', type=int, help='Minimum like count filter (optional)')
@click.option('--min-retweets', type=int, help='Minimum retweet count filter (optional)')
@click.option('--min-replies', type=int, help='Minimum reply count filter (optional)')
@click.option('--min-quotes', type=int, help='Minimum quote tweet count filter (optional)')
@click.option('--days-back', type=int, help='Only tweets from last N days (optional)')
@click.option('--only-video', is_flag=True, help='Only tweets with videos')
@click.option('--only-image', is_flag=True, help='Only tweets with images')
@click.option('--only-quote', is_flag=True, help='Only quote tweets')
@click.option('--only-verified', is_flag=True, help='Only verified accounts')
@click.option('--only-blue', is_flag=True, help='Only Twitter Blue accounts')
@click.option('--raw-query', is_flag=True, help='Use raw Twitter search syntax (advanced)')
@click.option('--sort', default='Latest', type=click.Choice(['Latest', 'Top']), help='Sort by (default: Latest)')
@click.option('--language', default='en', help='Language code (default: en)')
@click.option('--project', '-p', help='Project slug to link results to (optional)')
def twitter_search(
    terms: str,
    count: int,
    min_likes: Optional[int],
    min_retweets: Optional[int],
    min_replies: Optional[int],
    min_quotes: Optional[int],
    days_back: Optional[int],
    only_video: bool,
    only_image: bool,
    only_quote: bool,
    only_verified: bool,
    only_blue: bool,
    raw_query: bool,
    sort: str,
    language: str,
    project: Optional[str]
):
    """
    Search Twitter for tweets by keyword or raw query

    Enables keyword/hashtag discovery for Twitter content. Supports various
    filters including engagement metrics, content types, and account verification.

    Constraints:
        - Minimum 50 tweets per search (Apify actor requirement)
        - Max 5 search terms per batch (Apify actor limitation)

    Examples:
        # Basic search
        vt twitter search --terms "dog training" --count 100

        # With engagement filters
        vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7

        # Content filters (single or combined)
        vt twitter search --terms "puppy" --count 100 --only-video
        vt twitter search --terms "pets" --count 200 --only-video --only-image

        # Raw Twitter query syntax (advanced)
        vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query

        # Multiple search terms (batch search, max 5 queries)
        vt twitter search --terms "puppy,kitten,bunny" --count 100

        # Link to project
        vt twitter search --terms "golden retriever" --count 100 --project my-twitter-project
    """
    try:
        # Validate minimum count (Apify actor requirement)
        if count < 50:
            click.echo("\n❌ Error: Twitter search requires minimum 50 tweets", err=True)
            click.echo("   This is an Apify actor limitation", err=True)
            click.echo("\n💡 Try: --count 50 or higher\n", err=True)
            raise click.Abort()

        # Parse search terms (for batching)
        search_terms = [t.strip() for t in terms.split(',')]

        # Validate batch size (max 5 queries)
        if len(search_terms) > 5:
            click.echo(f"\n❌ Error: Maximum 5 search terms allowed (you provided {len(search_terms)})", err=True)
            click.echo("   This is an Apify actor limitation", err=True)
            click.echo("\n💡 Try: Split into multiple searches\n", err=True)
            raise click.Abort()

        click.echo(f"\n{'='*60}")
        click.echo(f"🐦 Twitter Search")
        click.echo(f"{'='*60}\n")

        if raw_query:
            click.echo(f"Raw query: {terms}")
        else:
            click.echo(f"Search terms: {', '.join(search_terms)}")

        click.echo(f"Count: {count} tweets")

        # Display filters if any are set
        filters = []
        if min_likes:
            filters.append(f"{min_likes:,}+ likes")
        if min_retweets:
            filters.append(f"{min_retweets:,}+ retweets")
        if min_replies:
            filters.append(f"{min_replies:,}+ replies")
        if min_quotes:
            filters.append(f"{min_quotes:,}+ quotes")
        if days_back:
            filters.append(f"Last {days_back} days")
        if only_video:
            filters.append("Videos only")
        if only_image:
            filters.append("Images only")
        if only_quote:
            filters.append("Quote tweets only")
        if only_verified:
            filters.append("Verified accounts only")
        if only_blue:
            filters.append("Twitter Blue only")

        if filters:
            click.echo(f"Filters:")
            for f in filters:
                click.echo(f"  - {f}")

        click.echo(f"Sort by: {sort}")
        click.echo(f"Language: {language}")

        if project:
            click.echo(f"Project: {project}")

        if len(search_terms) > 1:
            click.echo(f"\n⚡ Batch mode: {len(search_terms)} queries in one actor run")

        click.echo()

        # Initialize scraper
        scraper = TwitterScraper()

        # Search
        click.echo("🔄 Starting Twitter search...")
        click.echo("   Note: This may take a couple minutes (Apify actor execution)")
        click.echo()

        terms_count, tweets_count = scraper.scrape_search(
            search_terms=search_terms,
            max_tweets=count,
            min_likes=min_likes,
            min_retweets=min_retweets,
            min_replies=min_replies,
            min_quotes=min_quotes,
            days_back=days_back,
            only_video=only_video,
            only_image=only_image,
            only_quote=only_quote,
            only_verified=only_verified,
            only_blue=only_blue,
            raw_query=raw_query,
            sort=sort,
            language=language,
            project_slug=project
        )

        # Display results
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Search Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Results:")
        click.echo(f"   Search terms: {terms_count}")
        click.echo(f"   Tweets scraped: {tweets_count}")

        if tweets_count == 0:
            click.echo("\n⚠️  No tweets found")
            click.echo("\n💡 Try:")
            click.echo("   - Lowering filters (--min-likes, --min-retweets)")
            click.echo("   - Expanding time range (--days-back)")
            click.echo("   - Different search terms")
        else:
            click.echo(f"\n✅ Saved {tweets_count} tweets to database")

            if project:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Score tweets: vt score --project {project}")
                click.echo(f"   - Analyze hooks: vt analyze hooks --project {project}")
            else:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Link to project: Use --project flag to organize results")
                click.echo(f"   - Or create project: vt project create")

        # Important notes
        click.echo(f"\n⚠️  Actor Usage Notes:")
        click.echo(f"   - Wait a couple minutes before next Twitter search")
        click.echo(f"   - Only one Twitter search can run at a time")
        click.echo(f"   - These are Apify actor limitations")

        click.echo(f"\n{'='*60}\n")

    except click.Abort:
        raise
    except Exception as e:
        click.echo(f"\n❌ Search failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


# Export the command group
twitter = twitter_group
