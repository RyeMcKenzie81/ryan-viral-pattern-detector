"""
Facebook Ads CLI Commands

Commands for scraping Facebook ads from Ad Library.
"""

import logging
from typing import Optional

import click

from ..scrapers.facebook_ads import FacebookAdsScraper
from ..core.database import get_supabase_client


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


@click.group()
def facebook():
    """Facebook ads scraping commands"""
    pass


@facebook.command()
@click.argument('url')
@click.option('--count', type=int, default=None, help='Max number of ads to scrape')
@click.option('--details', is_flag=True, help='Scrape EU transparency details')
@click.option('--period', type=click.Choice(['last24h', 'last7d', 'last14d', 'last30d', '']), default='', help='Date range filter')
@click.option('--project', '-p', help='Project slug to link ads to')
@click.option('--brand', '-b', help='Brand slug to link ads to')
@click.option('--save', is_flag=True, help='Save ads to database')
def search(url: str, count: Optional[int], details: bool, period: str, project: Optional[str], brand: Optional[str], save: bool):
    """
    Search Facebook Ad Library by URL

    Example:
        facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=marketing" --count 100 --save --project my-project
    """
    try:
        scraper = FacebookAdsScraper()

        click.echo(f"Searching Facebook Ad Library...")
        click.echo(f"URL: {url}")
        if count:
            click.echo(f"Max ads: {count}")
        if period:
            click.echo(f"Period: {period}")
        click.echo()

        # Scrape ads
        df = scraper.search_ad_library(
            search_url=url,
            count=count,
            scrape_details=details,
            period=period
        )

        if len(df) == 0:
            click.echo("No ads found")
            return

        click.echo(f"✅ Scraped {len(df)} ads from {df['page_name'].nunique()} pages")
        click.echo()

        # Show preview
        click.echo("Preview (first 5 ads):")
        click.echo("-" * 80)
        for i, row in df.head().iterrows():
            click.echo(f"{i+1}. {row['page_name']}")
            click.echo(f"   Ad ID: {row['ad_archive_id']}")
            click.echo(f"   Active: {row['is_active']}")
            click.echo(f"   Start: {row['start_date']}")
            if row.get('spend'):
                click.echo(f"   Spend: {row['currency']} {row['spend']}")
            click.echo()

        # Save to database if requested
        if save:
            click.echo("Saving to database...")

            # Resolve project/brand IDs
            project_id = None
            brand_id = None

            supabase = get_supabase_client()

            if project:
                proj_result = supabase.table('projects').select('id').eq('slug', project).execute()
                if proj_result.data:
                    project_id = proj_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Project '{project}' not found")

            if brand:
                brand_result = supabase.table('brands').select('id').eq('slug', brand).execute()
                if brand_result.data:
                    brand_id = brand_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Brand '{brand}' not found")

            # Save
            ad_ids = scraper.save_ads_to_db(df, project_id=project_id, brand_id=brand_id)

            click.echo(f"✅ Saved {len(ad_ids)} ads to database")
            if project_id:
                click.echo(f"✅ Linked to project: {project}")
            if brand_id:
                click.echo(f"✅ Linked to brand: {brand}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise


@facebook.command()
@click.argument('page_url')
@click.option('--count', type=int, default=None, help='Max number of ads to scrape')
@click.option('--status', type=click.Choice(['all', 'active', 'inactive']), default='all', help='Filter by active status')
@click.option('--country', default='ALL', help='2-letter country code or ALL')
@click.option('--details', is_flag=True, help='Scrape EU transparency details')
@click.option('--project', '-p', help='Project slug to link ads to')
@click.option('--brand', '-b', help='Brand slug to link ads to')
@click.option('--save', is_flag=True, help='Save ads to database')
def page(page_url: str, count: Optional[int], status: str, country: str, details: bool, project: Optional[str], brand: Optional[str], save: bool):
    """
    Scrape all ads run by a Facebook page

    Example:
        facebook page "https://www.facebook.com/Nike" --count 50 --save --project nike-ads
    """
    try:
        scraper = FacebookAdsScraper()

        click.echo(f"Scraping ads from Facebook page...")
        click.echo(f"Page: {page_url}")
        if count:
            click.echo(f"Max ads: {count}")
        click.echo(f"Status: {status}")
        click.echo(f"Country: {country}")
        click.echo()

        # Scrape ads
        df = scraper.scrape_page_ads(
            page_url=page_url,
            count=count,
            active_status=status,
            country_code=country,
            scrape_details=details
        )

        if len(df) == 0:
            click.echo("No ads found for this page")
            return

        click.echo(f"✅ Scraped {len(df)} ads")
        click.echo()

        # Show preview
        click.echo("Preview (first 5 ads):")
        click.echo("-" * 80)
        for i, row in df.head().iterrows():
            click.echo(f"{i+1}. Ad ID: {row['ad_archive_id']}")
            click.echo(f"   Active: {row['is_active']}")
            click.echo(f"   Start: {row['start_date']}")
            if row.get('end_date'):
                click.echo(f"   End: {row['end_date']}")
            if row.get('spend'):
                click.echo(f"   Spend: {row['currency']} {row['spend']}")
            click.echo()

        # Save to database if requested
        if save:
            click.echo("Saving to database...")

            # Resolve project/brand IDs
            project_id = None
            brand_id = None

            supabase = get_supabase_client()

            if project:
                proj_result = supabase.table('projects').select('id').eq('slug', project).execute()
                if proj_result.data:
                    project_id = proj_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Project '{project}' not found")

            if brand:
                brand_result = supabase.table('brands').select('id').eq('slug', brand).execute()
                if brand_result.data:
                    brand_id = brand_result.data[0]['id']
                else:
                    click.echo(f"⚠️  Brand '{brand}' not found")

            # Save
            ad_ids = scraper.save_ads_to_db(df, project_id=project_id, brand_id=brand_id)

            click.echo(f"✅ Saved {len(ad_ids)} ads to database")
            if project_id:
                click.echo(f"✅ Linked to project: {project}")
            if brand_id:
                click.echo(f"✅ Linked to brand: {brand}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise
