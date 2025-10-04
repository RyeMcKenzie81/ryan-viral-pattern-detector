"""
Brand management commands for ViralTracker CLI
"""

import click
from typing import Optional
from ..core.database import get_supabase_client


@click.group('brand')
def brand_group():
    """Manage brands"""
    pass


@brand_group.command('list')
def list_brands():
    """
    List all brands

    Examples:
        vt brand list
    """
    try:
        supabase = get_supabase_client()

        # Fetch all brands
        result = supabase.table('brands').select('*').order('name').execute()

        if not result.data:
            click.echo("No brands found.")
            click.echo("\nCreate your first brand with: vt brand create <name>")
            return

        # Display brands
        click.echo(f"\n{'='*60}")
        click.echo(f"📋 Brands ({len(result.data)})")
        click.echo(f"{'='*60}\n")

        for brand in result.data:
            click.echo(f"🏢 {brand['name']}")
            click.echo(f"   Slug: {brand['slug']}")
            if brand.get('description'):
                click.echo(f"   Description: {brand['description']}")
            if brand.get('website'):
                click.echo(f"   Website: {brand['website']}")
            click.echo(f"   Created: {brand['created_at'][:10]}")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@brand_group.command('show')
@click.argument('slug')
def show_brand(slug: str):
    """
    Show detailed information about a brand

    Examples:
        vt brand show yakety-pack
    """
    try:
        supabase = get_supabase_client()

        # Fetch brand
        brand_result = supabase.table('brands').select('*').eq('slug', slug).single().execute()

        if not brand_result.data:
            click.echo(f"❌ Brand '{slug}' not found", err=True)
            return

        brand = brand_result.data

        # Fetch products for this brand
        products_result = supabase.table('products').select('id, name, slug').eq('brand_id', brand['id']).execute()

        # Fetch projects for this brand
        projects_result = supabase.table('projects').select('id, name, slug').eq('brand_id', brand['id']).execute()

        # Display brand details
        click.echo(f"\n{'='*60}")
        click.echo(f"🏢 {brand['name']}")
        click.echo(f"{'='*60}\n")

        click.echo(f"Slug: {brand['slug']}")
        if brand.get('description'):
            click.echo(f"Description: {brand['description']}")
        if brand.get('website'):
            click.echo(f"Website: {brand['website']}")
        click.echo(f"Created: {brand['created_at']}")

        # Products
        click.echo(f"\n📦 Products ({len(products_result.data)}):")
        if products_result.data:
            for product in products_result.data:
                click.echo(f"   - {product['name']} ({product['slug']})")
        else:
            click.echo("   None")

        # Projects
        click.echo(f"\n📁 Projects ({len(projects_result.data)}):")
        if projects_result.data:
            for project in projects_result.data:
                click.echo(f"   - {project['name']} ({project['slug']})")
        else:
            click.echo("   None")

        click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@brand_group.command('create')
@click.argument('name')
@click.option('--slug', help='URL-friendly slug (auto-generated if not provided)')
@click.option('--description', '-d', help='Brand description')
@click.option('--website', '-w', help='Brand website URL')
def create_brand(name: str, slug: Optional[str], description: Optional[str], website: Optional[str]):
    """
    Create a new brand

    Examples:
        vt brand create "My Brand"
        vt brand create "Acme Corp" --slug acme --website https://acme.com
        vt brand create "My Brand" --description "A cool brand" --website https://mybrand.com
    """
    try:
        supabase = get_supabase_client()

        # Auto-generate slug if not provided
        if not slug:
            slug = name.lower().replace(' ', '-').replace('_', '-')
            # Remove special characters
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')

        # Prepare brand data
        brand_data = {
            'name': name,
            'slug': slug,
        }

        if description:
            brand_data['description'] = description

        if website:
            brand_data['website'] = website

        # Create brand
        click.echo(f"Creating brand: {name}")
        result = supabase.table('brands').insert(brand_data).execute()

        if result.data:
            brand = result.data[0]
            click.echo(f"✅ Brand created successfully!")
            click.echo(f"   Name: {brand['name']}")
            click.echo(f"   Slug: {brand['slug']}")
            click.echo(f"\nNext steps:")
            click.echo(f"  - Create a product: vt product create <name> --brand {brand['slug']}")
            click.echo(f"  - Create a project: vt project create <name> --brand {brand['slug']}")

    except Exception as e:
        if 'duplicate key' in str(e).lower():
            click.echo(f"❌ Error: Brand with slug '{slug}' already exists", err=True)
            click.echo(f"   Try a different slug with: --slug <unique-slug>", err=True)
        else:
            click.echo(f"❌ Error: {e}", err=True)
