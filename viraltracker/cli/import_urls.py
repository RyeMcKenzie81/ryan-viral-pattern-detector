"""
URL import commands for ViralTracker CLI
"""

import asyncio
import click
from pathlib import Path
from typing import Optional

from ..core.database import get_supabase_client
from ..importers import InstagramURLImporter
from ..importers.twitter import TwitterURLImporter


@click.group('import')
def import_url_group():
    """Import content from URLs"""
    pass


@import_url_group.command('url')
@click.argument('url')
@click.option('--project', '-p', required=True, help='Project slug (e.g., yakety-pack-instagram)')
@click.option('--platform', default='instagram', help='Platform (instagram, twitter, tiktok, youtube_shorts)')
@click.option('--own/--competitor', default=False, help='Mark as own content vs competitor')
@click.option('--notes', '-n', help='Optional notes about this import')
def import_single_url(url: str, project: str, platform: str, own: bool, notes: Optional[str]):
    """
    Import a single URL into a project

    The URL is validated and saved to the database.
    Metadata (views, likes, comments) will be populated by the next Apify scrape.

    Examples:
        vt import url https://www.instagram.com/reel/ABC123/ --project yakety-pack-instagram
        vt import url https://www.instagram.com/p/XYZ789/ --project my-project --own --notes "Our best video"
        vt import url https://twitter.com/username/status/1234567890 --project my-twitter --platform twitter
    """
    asyncio.run(_import_url(url, project, platform, own, notes))


async def _import_url(url: str, project_slug: str, platform_slug: str, is_own: bool, notes: Optional[str]):
    """Async implementation of URL import"""
    try:
        # Get database client
        supabase = get_supabase_client()

        # Get platform ID
        click.echo(f"🔍 Looking up platform: {platform_slug}")
        platform_result = supabase.table('platforms').select('id').eq('slug', platform_slug).single().execute()
        if not platform_result.data:
            click.echo(f"❌ Error: Platform '{platform_slug}' not found", err=True)
            return
        platform_id = platform_result.data['id']

        # Get project ID
        click.echo(f"🔍 Looking up project: {project_slug}")
        try:
            project_result = supabase.table('projects').select('id').eq('slug', project_slug).single().execute()
            if not project_result.data:
                click.echo(f"❌ Error: Project '{project_slug}' not found", err=True)
                click.echo(f"\nTip: List available projects with: vt project list", err=True)
                return
            project_id = project_result.data['id']
        except Exception as e:
            click.echo(f"❌ Error: Project '{project_slug}' not found", err=True)
            click.echo(f"\nTip: List available projects with: vt project list", err=True)
            return

        # Initialize importer
        if platform_slug == 'instagram':
            importer = InstagramURLImporter(platform_id)
        elif platform_slug == 'twitter':
            importer = TwitterURLImporter(platform_id)
        else:
            click.echo(f"❌ Error: Platform '{platform_slug}' not yet supported", err=True)
            click.echo(f"Supported platforms: instagram, twitter", err=True)
            return

        # Import URL
        click.echo(f"📥 Importing: {url}")
        result = await importer.import_url(
            url=url,
            project_id=project_id,
            is_own_content=is_own,
            notes=notes
        )

        # Display results
        if result['status'] == 'imported':
            click.echo(f"✅ Successfully imported!")
            click.echo(f"   Post ID: {result['post_id']}")
            click.echo(f"   Note: Metadata (views, likes, etc.) will be populated by next Apify scrape")
        elif result['status'] == 'already_exists':
            click.echo(f"ℹ️  Post already exists, linked to project")
            click.echo(f"   Post ID: {result['post_id']}")

        click.echo(f"\n🎯 Added to project: {project_slug}")

    except ValueError as e:
        click.echo(f"❌ Validation error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@import_url_group.command('urls')
@click.argument('file', type=click.Path(exists=True, path_type=Path))
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--platform', default='instagram', help='Platform (instagram, twitter, tiktok, youtube_shorts)')
@click.option('--own/--competitor', default=False, help='Mark all as own content vs competitor')
def import_urls_from_file(file: Path, project: str, platform: str, own: bool):
    """
    Import multiple URLs from a file (one URL per line)

    The URLs are validated and saved to the database.
    Metadata (views, likes, comments) will be populated by the next Apify scrape.

    Examples:
        vt import urls urls.txt --project yakety-pack-instagram
        vt import urls competitor_urls.txt --project my-project --competitor

    File format:
        https://www.instagram.com/reel/ABC123/
        https://www.instagram.com/p/XYZ789/
        https://www.instagram.com/reel/DEF456/
    """
    asyncio.run(_import_urls_from_file(file, project, platform, own))


async def _import_urls_from_file(file: Path, project_slug: str, platform_slug: str, is_own: bool):
    """Async implementation of batch URL import"""
    try:
        # Read URLs from file
        with open(file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if not urls:
            click.echo(f"❌ No URLs found in {file}", err=True)
            return

        click.echo(f"📋 Found {len(urls)} URLs in {file.name}")

        # Get database client
        supabase = get_supabase_client()

        # Get platform ID
        platform_result = supabase.table('platforms').select('id').eq('slug', platform_slug).single().execute()
        if not platform_result.data:
            click.echo(f"❌ Error: Platform '{platform_slug}' not found", err=True)
            return
        platform_id = platform_result.data['id']

        # Get project ID
        project_result = supabase.table('projects').select('id').eq('slug', project_slug).single().execute()
        if not project_result.data:
            click.echo(f"❌ Error: Project '{project_slug}' not found", err=True)
            return
        project_id = project_result.data['id']

        # Initialize importer
        if platform_slug == 'instagram':
            importer = InstagramURLImporter(platform_id)
        elif platform_slug == 'twitter':
            importer = TwitterURLImporter(platform_id)
        else:
            click.echo(f"❌ Error: Platform '{platform_slug}' not yet supported", err=True)
            click.echo(f"Supported platforms: instagram, twitter", err=True)
            return

        # Import each URL
        success_count = 0
        error_count = 0
        exists_count = 0

        click.echo(f"\n📥 Starting import...")
        for i, url in enumerate(urls, 1):
            try:
                click.echo(f"\n[{i}/{len(urls)}] {url}")
                result = await importer.import_url(
                    url=url,
                    project_id=project_id,
                    is_own_content=is_own,
                    notes=f'Batch import from {file.name}'
                )

                if result['status'] == 'imported':
                    click.echo(f"  ✅ Imported (ID: {result['post_id']})")
                    success_count += 1
                elif result['status'] == 'already_exists':
                    click.echo(f"  ℹ️  Already exists (ID: {result['post_id']})")
                    exists_count += 1

            except Exception as e:
                click.echo(f"  ❌ Error: {e}")
                error_count += 1

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"📊 Import Summary:")
        click.echo(f"   ✅ Imported: {success_count}")
        click.echo(f"   ℹ️  Already existed: {exists_count}")
        click.echo(f"   ❌ Errors: {error_count}")
        click.echo(f"   📋 Total: {len(urls)}")
        click.echo(f"\nNote: Metadata (views, likes, etc.) will be populated by next Apify scrape")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
