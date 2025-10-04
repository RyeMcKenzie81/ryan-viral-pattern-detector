"""
Product management commands for ViralTracker CLI
"""

import click
from typing import Optional
from ..core.database import get_supabase_client


@click.group('product')
def product_group():
    """Manage products"""
    pass


@product_group.command('list')
@click.option('--brand', '-b', help='Filter by brand slug')
def list_products(brand: Optional[str]):
    """
    List all products

    Examples:
        vt product list
        vt product list --brand yakety-pack
    """
    try:
        supabase = get_supabase_client()

        # Build query
        query = supabase.table('products').select('*, brands!inner(name, slug)')

        # Filter by brand if specified
        if brand:
            query = query.eq('brands.slug', brand)

        result = query.order('name').execute()

        if not result.data:
            if brand:
                click.echo(f"No products found for brand '{brand}'.")
            else:
                click.echo("No products found.")
            click.echo("\nCreate your first product with: vt product create <name> --brand <slug>")
            return

        # Display products
        click.echo(f"\n{'='*60}")
        click.echo(f"📦 Products ({len(result.data)})")
        click.echo(f"{'='*60}\n")

        for product in result.data:
            click.echo(f"📦 {product['name']}")
            click.echo(f"   Slug: {product['slug']}")
            click.echo(f"   Brand: {product['brands']['name']} ({product['brands']['slug']})")
            if product.get('description'):
                click.echo(f"   Description: {product['description']}")
            click.echo(f"   Active: {'Yes' if product.get('is_active', True) else 'No'}")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@product_group.command('show')
@click.argument('slug')
def show_product(slug: str):
    """
    Show detailed information about a product

    Examples:
        vt product show core-deck
    """
    try:
        supabase = get_supabase_client()

        # Fetch product with brand info
        product_result = supabase.table('products')\
            .select('*, brands!inner(name, slug)')\
            .eq('slug', slug)\
            .single()\
            .execute()

        if not product_result.data:
            click.echo(f"❌ Product '{slug}' not found", err=True)
            return

        product = product_result.data

        # Fetch projects using this product
        projects_result = supabase.table('projects')\
            .select('id, name, slug')\
            .eq('product_id', product['id'])\
            .execute()

        # Display product details
        click.echo(f"\n{'='*60}")
        click.echo(f"📦 {product['name']}")
        click.echo(f"{'='*60}\n")

        click.echo(f"Slug: {product['slug']}")
        click.echo(f"Brand: {product['brands']['name']} ({product['brands']['slug']})")
        if product.get('description'):
            click.echo(f"Description: {product['description']}")
        if product.get('target_audience'):
            click.echo(f"Target Audience: {product['target_audience']}")
        if product.get('price_range'):
            click.echo(f"Price Range: {product['price_range']}")
        click.echo(f"Active: {'Yes' if product.get('is_active', True) else 'No'}")
        click.echo(f"Created: {product['created_at']}")

        # Display structured fields if present
        if product.get('key_problems_solved'):
            click.echo(f"\n🎯 Key Problems Solved:")
            for problem in product['key_problems_solved']:
                click.echo(f"   - {problem}")

        if product.get('key_benefits'):
            click.echo(f"\n✨ Key Benefits:")
            for benefit in product['key_benefits']:
                click.echo(f"   - {benefit}")

        if product.get('features'):
            click.echo(f"\n⚙️  Features:")
            for feature in product['features']:
                click.echo(f"   - {feature}")

        if product.get('context_prompt'):
            click.echo(f"\n📝 AI Context Prompt:")
            context = product['context_prompt']
            # Truncate if very long
            if len(context) > 200:
                click.echo(f"   {context[:200]}...")
                click.echo(f"   ({len(context)} characters total)")
            else:
                click.echo(f"   {context}")

        # Projects
        click.echo(f"\n📁 Projects Using This Product ({len(projects_result.data)}):")
        if projects_result.data:
            for project in projects_result.data:
                click.echo(f"   - {project['name']} ({project['slug']})")
        else:
            click.echo("   None")

        click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@product_group.command('create')
@click.argument('name')
@click.option('--brand', '-b', required=True, help='Brand slug (required)')
@click.option('--slug', help='URL-friendly slug (auto-generated if not provided)')
@click.option('--description', '-d', help='Product description')
@click.option('--audience', '-a', help='Target audience')
@click.option('--price', '-p', help='Price range (e.g., "$39", "$10-$50")')
def create_product(name: str, brand: str, slug: Optional[str], description: Optional[str],
                   audience: Optional[str], price: Optional[str]):
    """
    Create a new product

    Examples:
        vt product create "Core Deck" --brand yakety-pack
        vt product create "Premium Cards" --brand yakety-pack --price "$59" --audience "Families"
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

        # Auto-generate slug if not provided
        if not slug:
            slug = name.lower().replace(' ', '-').replace('_', '-')
            # Remove special characters
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')

        # Prepare product data
        product_data = {
            'brand_id': brand_id,
            'name': name,
            'slug': slug,
        }

        if description:
            product_data['description'] = description

        if audience:
            product_data['target_audience'] = audience

        if price:
            product_data['price_range'] = price

        # Create product
        click.echo(f"Creating product: {name}")
        result = supabase.table('products').insert(product_data).execute()

        if result.data:
            product = result.data[0]
            click.echo(f"✅ Product created successfully!")
            click.echo(f"   Name: {product['name']}")
            click.echo(f"   Slug: {product['slug']}")
            click.echo(f"   Brand: {brand}")
            click.echo(f"\nNext steps:")
            click.echo(f"  - View details: vt product show {product['slug']}")
            click.echo(f"  - Create a project: vt project create <name> --brand {brand} --product {product['slug']}")

    except Exception as e:
        if 'duplicate key' in str(e).lower():
            click.echo(f"❌ Error: Product with slug '{slug}' already exists for this brand", err=True)
            click.echo(f"   Try a different slug with: --slug <unique-slug>", err=True)
        else:
            click.echo(f"❌ Error: {e}", err=True)
