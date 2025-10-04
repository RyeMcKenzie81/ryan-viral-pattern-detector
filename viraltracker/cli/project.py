"""
Project management commands for ViralTracker CLI
"""

import click
from pathlib import Path
from typing import Optional
from ..core.database import get_supabase_client


@click.group('project')
def project_group():
    """Manage projects"""
    pass


@project_group.command('list')
@click.option('--brand', '-b', help='Filter by brand slug')
def list_projects(brand: Optional[str]):
    """
    List all projects

    Examples:
        vt project list
        vt project list --brand yakety-pack
    """
    try:
        supabase = get_supabase_client()

        # Build query
        query = supabase.table('projects').select('''
            *,
            brands!inner(name, slug),
            products(name, slug)
        ''')

        # Filter by brand if specified
        if brand:
            query = query.eq('brands.slug', brand)

        result = query.order('name').execute()

        if not result.data:
            if brand:
                click.echo(f"No projects found for brand '{brand}'.")
            else:
                click.echo("No projects found.")
            click.echo("\nCreate your first project with: vt project create <name> --brand <slug>")
            return

        # Display projects
        click.echo(f"\n{'='*60}")
        click.echo(f"📁 Projects ({len(result.data)})")
        click.echo(f"{'='*60}\n")

        for project in result.data:
            status = "✅" if project.get('is_active', True) else "⏸️ "
            click.echo(f"{status} {project['name']}")
            click.echo(f"   Slug: {project['slug']}")
            click.echo(f"   Brand: {project['brands']['name']} ({project['brands']['slug']})")
            if project.get('products'):
                click.echo(f"   Product: {project['products']['name']} ({project['products']['slug']})")
            if project.get('description'):
                click.echo(f"   Description: {project['description']}")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@project_group.command('show')
@click.argument('slug')
def show_project(slug: str):
    """
    Show detailed information about a project

    Examples:
        vt project show yakety-pack-instagram
    """
    try:
        supabase = get_supabase_client()

        # Fetch project with related data
        project_result = supabase.table('projects').select('''
            *,
            brands!inner(name, slug),
            products(name, slug)
        ''').eq('slug', slug).single().execute()

        if not project_result.data:
            click.echo(f"❌ Project '{slug}' not found", err=True)
            return

        project = project_result.data

        # Fetch accounts linked to this project
        accounts_result = supabase.table('project_accounts').select('''
            accounts!inner(handle, platform_username, platforms!inner(name, slug))
        ''').eq('project_id', project['id']).execute()

        # Fetch posts linked to this project (count only)
        posts_result = supabase.table('project_posts').select('id', count='exact').eq('project_id', project['id']).execute()
        posts_count = posts_result.count if posts_result.count else 0

        # Display project details
        click.echo(f"\n{'='*60}")
        status_icon = "✅" if project.get('is_active', True) else "⏸️ "
        click.echo(f"{status_icon} {project['name']}")
        click.echo(f"{'='*60}\n")

        click.echo(f"Slug: {project['slug']}")
        click.echo(f"Brand: {project['brands']['name']} ({project['brands']['slug']})")
        if project.get('products'):
            click.echo(f"Product: {project['products']['name']} ({project['products']['slug']})")
        if project.get('description'):
            click.echo(f"Description: {project['description']}")
        click.echo(f"Status: {'Active' if project.get('is_active', True) else 'Inactive'}")
        click.echo(f"Created: {project['created_at']}")

        # Accounts
        click.echo(f"\n👥 Accounts ({len(accounts_result.data)}):")
        if accounts_result.data:
            # Group by platform
            by_platform = {}
            for item in accounts_result.data:
                platform_name = item['accounts']['platforms']['name']
                username = item['accounts']['platform_username'] or item['accounts']['handle']
                if platform_name not in by_platform:
                    by_platform[platform_name] = []
                by_platform[platform_name].append(username)

            for platform, usernames in sorted(by_platform.items()):
                click.echo(f"   {platform}:")
                for username in usernames:
                    click.echo(f"      - @{username}")
        else:
            click.echo("   None")
            click.echo(f"   Add accounts with: vt project add-accounts {slug} <file>")

        # Posts
        click.echo(f"\n📊 Posts: {posts_count}")

        click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@project_group.command('create')
@click.argument('name')
@click.option('--brand', '-b', required=True, help='Brand slug (required)')
@click.option('--product', '-p', help='Product slug (optional)')
@click.option('--slug', help='URL-friendly slug (auto-generated if not provided)')
@click.option('--description', '-d', help='Project description')
def create_project(name: str, brand: str, product: Optional[str], slug: Optional[str], description: Optional[str]):
    """
    Create a new project

    Examples:
        vt project create "Instagram Campaign" --brand yakety-pack
        vt project create "TikTok Launch" --brand yakety-pack --product core-deck
        vt project create "Q4 Content" --brand acme --product premium --description "Q4 campaign content"
    """
    try:
        supabase = get_supabase_client()

        # Get brand ID
        brand_result = supabase.table('brands').select('id').eq('slug', brand).single().execute()
        if not brand_result.data:
            click.echo(f"❌ Brand '{brand}' not found", err=True)
            click.echo(f"\nList brands with: vt brand list", err=True)
            return

        brand_id = brand_result.data['id']

        # Get product ID if specified
        product_id = None
        if product:
            product_result = supabase.table('products').select('id').eq('slug', product).eq('brand_id', brand_id).single().execute()
            if not product_result.data:
                click.echo(f"❌ Product '{product}' not found for brand '{brand}'", err=True)
                click.echo(f"\nList products with: vt product list --brand {brand}", err=True)
                return
            product_id = product_result.data['id']

        # Auto-generate slug if not provided
        if not slug:
            slug = name.lower().replace(' ', '-').replace('_', '-')
            # Remove special characters
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')

        # Prepare project data
        project_data = {
            'brand_id': brand_id,
            'name': name,
            'slug': slug,
        }

        if product_id:
            project_data['product_id'] = product_id

        if description:
            project_data['description'] = description

        # Create project
        click.echo(f"Creating project: {name}")
        result = supabase.table('projects').insert(project_data).execute()

        if result.data:
            project = result.data[0]
            click.echo(f"✅ Project created successfully!")
            click.echo(f"   Name: {project['name']}")
            click.echo(f"   Slug: {project['slug']}")
            click.echo(f"   Brand: {brand}")
            if product:
                click.echo(f"   Product: {product}")
            click.echo(f"\nNext steps:")
            click.echo(f"  - View details: vt project show {project['slug']}")
            click.echo(f"  - Add accounts: vt project add-accounts {project['slug']} <file>")
            click.echo(f"  - Import URLs: vt import url <url> --project {project['slug']}")

    except Exception as e:
        if 'duplicate key' in str(e).lower():
            click.echo(f"❌ Error: Project with slug '{slug}' already exists", err=True)
            click.echo(f"   Try a different slug with: --slug <unique-slug>", err=True)
        else:
            click.echo(f"❌ Error: {e}", err=True)


@project_group.command('add-accounts')
@click.argument('project_slug')
@click.argument('file', type=click.Path(exists=True, path_type=Path))
@click.option('--platform', '-p', default='instagram', help='Platform (instagram, tiktok, youtube_shorts)')
@click.option('--priority', type=int, default=1, help='Account priority (1-10)')
def add_accounts(project_slug: str, file: Path, platform: str, priority: int):
    """
    Add accounts to a project from a file

    File format (one username per line):
        username1
        username2
        username3

    Examples:
        vt project add-accounts yakety-pack-instagram accounts.txt
        vt project add-accounts my-project usernames.txt --platform tiktok --priority 5
    """
    try:
        supabase = get_supabase_client()

        # Get project ID
        project_result = supabase.table('projects').select('id, name').eq('slug', project_slug).single().execute()
        if not project_result.data:
            click.echo(f"❌ Project '{project_slug}' not found", err=True)
            return
        project_id = project_result.data['id']
        project_name = project_result.data['name']

        # Get platform ID
        platform_result = supabase.table('platforms').select('id, name').eq('slug', platform).single().execute()
        if not platform_result.data:
            click.echo(f"❌ Platform '{platform}' not found", err=True)
            return
        platform_id = platform_result.data['id']
        platform_name = platform_result.data['name']

        # Read usernames from file
        with open(file, 'r') as f:
            usernames = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if not usernames:
            click.echo(f"❌ No usernames found in {file}", err=True)
            return

        click.echo(f"📋 Found {len(usernames)} usernames in {file.name}")
        click.echo(f"🎯 Adding to project: {project_name}")
        click.echo(f"📱 Platform: {platform_name}\n")

        added_count = 0
        existing_count = 0
        error_count = 0

        for username in usernames:
            try:
                # Check if account already exists
                account_result = supabase.table('accounts')\
                    .select('id')\
                    .eq('platform_id', platform_id)\
                    .eq('platform_username', username)\
                    .execute()

                if account_result.data:
                    account_id = account_result.data[0]['id']
                else:
                    # Create new account
                    new_account = {
                        'handle': username,  # Legacy field
                        'platform_id': platform_id,
                        'platform_username': username,
                    }
                    account_create_result = supabase.table('accounts').insert(new_account).execute()
                    account_id = account_create_result.data[0]['id']

                # Check if already linked to project
                link_check = supabase.table('project_accounts')\
                    .select('id')\
                    .eq('project_id', project_id)\
                    .eq('account_id', account_id)\
                    .execute()

                if link_check.data:
                    click.echo(f"  ℹ️  @{username} - already in project")
                    existing_count += 1
                else:
                    # Link account to project
                    link_data = {
                        'project_id': project_id,
                        'account_id': account_id,
                        'priority': priority,
                    }
                    supabase.table('project_accounts').insert(link_data).execute()
                    click.echo(f"  ✅ @{username} - added")
                    added_count += 1

            except Exception as e:
                click.echo(f"  ❌ @{username} - error: {e}")
                error_count += 1

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"📊 Summary:")
        click.echo(f"   ✅ Added: {added_count}")
        click.echo(f"   ℹ️  Already existed: {existing_count}")
        click.echo(f"   ❌ Errors: {error_count}")
        click.echo(f"   📋 Total: {len(usernames)}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
