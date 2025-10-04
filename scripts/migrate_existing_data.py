#!/usr/bin/env python3
"""
Migrate Existing Data to Multi-Brand Schema

This script migrates existing Yakety Pack data to the new multi-brand,
multi-platform schema.

It performs the following:
1. Creates "Yakety Pack" brand
2. Creates "Core Deck" product with existing context
3. Creates default project "Yakety Pack Instagram"
4. Updates all existing accounts with Instagram platform_id
5. Updates all existing posts with Instagram platform_id and import_source='scrape'
6. Links all accounts to default project via project_accounts
7. Creates project_posts entries for all existing posts

Usage:
    python scripts/migrate_existing_data.py [--dry-run]

Options:
    --dry-run    Show what would be done without making changes
"""

import os
import sys
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_KEY')
)

# Yakety Pack context (from existing yakety_pack_evaluator.py)
YAKETY_PACK_CONTEXT = """PRODUCT: Yakety Pack - Conversation Cards for Gaming Families

TARGET AUDIENCE: Parents with children aged 6-15 who play video games

KEY PROBLEMS SOLVED:
- Screen time arguments and battles
- Communication gap between parents and gaming kids
- Parents feeling disconnected from their child's gaming interests
- Difficulty having meaningful conversations about games
- Kids who won't talk about their day but will talk about Minecraft

PRODUCT FEATURES:
- 86 conversation cards (66 prompts + 20 design-your-own)
- Color-coded for different emotional depths
- Gaming-specific questions (Minecraft, Roblox, Fortnite, etc.)
- Transforms screen time into quality family time
- Research-backed by child psychology

PRICE: $39 core deck, $59 with expansion

KEY BENEFITS:
- Better parent-child communication
- Understanding your child's gaming world
- Reducing screen time conflicts
- Building emotional intelligence through gaming discussions

EVALUATION CRITERIA:
Rate videos on a scale of 1-10 for adaptation potential based on:
1. HOOK RELEVANCE: Does the hook relate to parenting, kids, gaming, screen time, communication, family dynamics, or child development?
2. AUDIENCE MATCH: Is the content creator's audience likely to have gaming kids aged 6-15?
3. TRANSITION EASE: How naturally could this hook/problem lead into discussing Yakety Pack as a solution?
4. VIRAL PATTERN REPLICABILITY: Could we create a similar hook that's equally engaging but transitions to Yakety Pack?
"""


def log(message: str, level: str = "INFO"):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {level}: {message}")


def get_platform_id(slug: str) -> Optional[str]:
    """Get platform ID by slug"""
    result = supabase.table('platforms').select('id').eq('slug', slug).single().execute()
    if result.data:
        return result.data['id']
    return None


def create_brand() -> str:
    """Create Yakety Pack brand"""
    log("Creating Yakety Pack brand...")

    # Check if already exists
    result = supabase.table('brands').select('id').eq('slug', 'yakety-pack').execute()
    if result.data:
        log("Brand 'yakety-pack' already exists", "INFO")
        return result.data[0]['id']

    # Create brand
    brand_data = {
        'name': 'Yakety Pack',
        'slug': 'yakety-pack',
        'description': 'Conversation Cards for Gaming Families',
        'website': 'https://yaketypack.com'  # Update with actual website if different
    }

    result = supabase.table('brands').insert(brand_data).execute()
    brand_id = result.data[0]['id']
    log(f"✓ Created brand 'Yakety Pack' (ID: {brand_id})")
    return brand_id


def create_product(brand_id: str) -> str:
    """Create Core Deck product"""
    log("Creating Core Deck product...")

    # Check if already exists
    result = supabase.table('products').select('id').eq('slug', 'core-deck').execute()
    if result.data:
        log("Product 'core-deck' already exists", "INFO")
        return result.data[0]['id']

    # Create product
    product_data = {
        'brand_id': brand_id,
        'name': 'Core Deck',
        'slug': 'core-deck',
        'description': '86 conversation cards for connecting with gaming kids',
        'target_audience': 'Parents with gaming kids aged 6-15',
        'price_range': '$39 core deck, $59 with expansion',
        'key_problems_solved': [
            'Screen time arguments and battles',
            'Communication gap between parents and gaming kids',
            'Parents feeling disconnected from their child\'s gaming interests',
            'Difficulty having meaningful conversations about games'
        ],
        'key_benefits': [
            'Better parent-child communication',
            'Understanding your child\'s gaming world',
            'Reducing screen time conflicts',
            'Building emotional intelligence through gaming discussions'
        ],
        'features': [
            '86 conversation cards (66 prompts + 20 design-your-own)',
            'Color-coded for different emotional depths',
            'Gaming-specific questions (Minecraft, Roblox, Fortnite, etc.)',
            'Transforms screen time into quality family time',
            'Research-backed by child psychology'
        ],
        'context_prompt': YAKETY_PACK_CONTEXT,
        'is_active': True
    }

    result = supabase.table('products').insert(product_data).execute()
    product_id = result.data[0]['id']
    log(f"✓ Created product 'Core Deck' (ID: {product_id})")
    return product_id


def create_project(brand_id: str, product_id: str) -> str:
    """Create default project"""
    log("Creating default project 'Yakety Pack Instagram'...")

    # Check if already exists
    result = supabase.table('projects').select('id').eq('slug', 'yakety-pack-instagram').execute()
    if result.data:
        log("Project 'yakety-pack-instagram' already exists", "INFO")
        return result.data[0]['id']

    # Create project
    project_data = {
        'brand_id': brand_id,
        'product_id': product_id,
        'name': 'Yakety Pack Instagram',
        'slug': 'yakety-pack-instagram',
        'description': 'Instagram viral content analysis for Yakety Pack',
        'is_active': True
    }

    result = supabase.table('projects').insert(project_data).execute()
    project_id = result.data[0]['id']
    log(f"✓ Created project 'Yakety Pack Instagram' (ID: {project_id})")
    return project_id


def migrate_accounts(platform_id: str, project_id: str, dry_run: bool = False):
    """Update accounts with platform_id and link to project"""
    log("Migrating accounts...")

    # Get all accounts
    result = supabase.table('accounts').select('id, handle, platform_id, platform_username').execute()
    accounts = result.data

    if not accounts:
        log("No accounts found to migrate", "WARNING")
        return

    log(f"Found {len(accounts)} accounts to migrate")

    migrated = 0
    skipped = 0

    for account in accounts:
        account_id = account['id']
        handle = account['handle']

        # Check if already migrated
        if account.get('platform_id'):
            skipped += 1
            continue

        if dry_run:
            log(f"  [DRY RUN] Would update account '{handle}' with platform_id and link to project")
            migrated += 1
            continue

        # Update account with platform info
        update_data = {
            'platform_id': platform_id,
            'platform_username': handle  # For Instagram, username = handle
        }

        supabase.table('accounts').update(update_data).eq('id', account_id).execute()

        # Link account to project via project_accounts
        project_account_data = {
            'project_id': project_id,
            'account_id': account_id,
            'priority': 1,
            'notes': 'Migrated from original setup'
        }

        # Check if already linked
        existing = supabase.table('project_accounts')\
            .select('id')\
            .eq('project_id', project_id)\
            .eq('account_id', account_id)\
            .execute()

        if not existing.data:
            supabase.table('project_accounts').insert(project_account_data).execute()

        migrated += 1

    log(f"✓ Migrated {migrated} accounts, skipped {skipped} (already migrated)")


def migrate_posts(platform_id: str, project_id: str, dry_run: bool = False):
    """Update posts with platform_id, import_source, and link to project"""
    log("Migrating posts...")

    # Get all posts
    result = supabase.table('posts').select('id, post_url, platform_id, import_source').execute()
    posts = result.data

    if not posts:
        log("No posts found to migrate", "WARNING")
        return

    log(f"Found {len(posts)} posts to migrate")

    migrated = 0
    skipped = 0

    for post in posts:
        post_id = post['id']

        # Check if already migrated
        if post.get('platform_id') and post.get('import_source'):
            skipped += 1
            continue

        if dry_run:
            log(f"  [DRY RUN] Would update post {post_id} with platform_id and import_source")
            migrated += 1
            continue

        # Update post with platform info
        update_data = {
            'platform_id': platform_id,
            'import_source': 'scrape',
            'is_own_content': False  # Existing data is all competitor content
        }

        supabase.table('posts').update(update_data).eq('id', post_id).execute()

        # Link post to project via project_posts
        project_post_data = {
            'project_id': project_id,
            'post_id': post_id,
            'import_method': 'scrape',
            'is_own_content': False,
            'notes': 'Migrated from original setup'
        }

        # Check if already linked
        existing = supabase.table('project_posts')\
            .select('id')\
            .eq('project_id', project_id)\
            .eq('post_id', post_id)\
            .execute()

        if not existing.data:
            supabase.table('project_posts').insert(project_post_data).execute()

        migrated += 1

    log(f"✓ Migrated {migrated} posts, skipped {skipped} (already migrated)")


def migrate_video_analyses(platform_id: str, dry_run: bool = False):
    """Update video analyses with platform_id"""
    log("Migrating video analyses...")

    # Get all video analyses
    result = supabase.table('video_analysis').select('id, platform_id').execute()
    analyses = result.data

    if not analyses:
        log("No video analyses found to migrate", "INFO")
        return

    log(f"Found {len(analyses)} video analyses to migrate")

    migrated = 0
    skipped = 0

    for analysis in analyses:
        analysis_id = analysis['id']

        # Check if already migrated
        if analysis.get('platform_id'):
            skipped += 1
            continue

        if dry_run:
            log(f"  [DRY RUN] Would update video analysis {analysis_id} with platform_id")
            migrated += 1
            continue

        # Update with platform info
        update_data = {
            'platform_id': platform_id,
            'platform_specific_metrics': {
                'instagram': {
                    'note': 'Migrated from original setup - specific metrics not available'
                }
            }
        }

        supabase.table('video_analysis').update(update_data).eq('id', analysis_id).execute()
        migrated += 1

    log(f"✓ Migrated {migrated} video analyses, skipped {skipped} (already migrated)")


def verify_migration():
    """Verify migration completed successfully"""
    log("\n" + "="*60)
    log("VERIFICATION")
    log("="*60)

    # Check brands
    brands = supabase.table('brands').select('*').execute()
    log(f"Brands: {len(brands.data)}")
    for brand in brands.data:
        log(f"  - {brand['name']} ({brand['slug']})")

    # Check products
    products = supabase.table('products').select('*').execute()
    log(f"\nProducts: {len(products.data)}")
    for product in products.data:
        log(f"  - {product['name']} ({product['slug']})")

    # Check projects
    projects = supabase.table('projects').select('*').execute()
    log(f"\nProjects: {len(projects.data)}")
    for project in projects.data:
        log(f"  - {project['name']} ({project['slug']})")

    # Check platforms
    platforms = supabase.table('platforms').select('*').execute()
    log(f"\nPlatforms: {len(platforms.data)}")
    for platform in platforms.data:
        log(f"  - {platform['name']} ({platform['slug']})")

    # Check accounts
    accounts_with_platform = supabase.table('accounts')\
        .select('id')\
        .not_.is_('platform_id', 'null')\
        .execute()
    accounts_total = supabase.table('accounts').select('id').execute()
    log(f"\nAccounts with platform_id: {len(accounts_with_platform.data)}/{len(accounts_total.data)}")

    # Check posts
    posts_with_platform = supabase.table('posts')\
        .select('id')\
        .not_.is_('platform_id', 'null')\
        .execute()
    posts_total = supabase.table('posts').select('id').execute()
    log(f"Posts with platform_id: {len(posts_with_platform.data)}/{len(posts_total.data)}")

    # Check import sources
    import_sources = supabase.table('posts')\
        .select('import_source')\
        .not_.is_('import_source', 'null')\
        .execute()
    log(f"\nPosts by import source:")
    from collections import Counter
    source_counts = Counter([p['import_source'] for p in import_sources.data])
    for source, count in source_counts.items():
        log(f"  - {source}: {count}")

    # Check project_accounts
    project_accounts = supabase.table('project_accounts').select('id').execute()
    log(f"\nProject-Account links: {len(project_accounts.data)}")

    # Check project_posts
    project_posts = supabase.table('project_posts').select('id').execute()
    log(f"Project-Post links: {len(project_posts.data)}")

    log("\n" + "="*60)
    log("✓ Migration verification complete!")
    log("="*60)


def main():
    """Main migration function"""
    import argparse

    parser = argparse.ArgumentParser(description='Migrate existing data to multi-brand schema')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    if args.dry_run:
        log("="*60)
        log("DRY RUN MODE - No changes will be made")
        log("="*60 + "\n")

    try:
        log("Starting migration...")
        log("="*60 + "\n")

        # Get Instagram platform ID
        instagram_platform_id = get_platform_id('instagram')
        if not instagram_platform_id:
            log("ERROR: Instagram platform not found. Run SQL migration first.", "ERROR")
            sys.exit(1)

        log(f"Using Instagram platform ID: {instagram_platform_id}\n")

        # Step 1: Create brand
        if not args.dry_run:
            brand_id = create_brand()
        else:
            log("[DRY RUN] Would create Yakety Pack brand")
            brand_id = "dry-run-brand-id"

        # Step 2: Create product
        if not args.dry_run:
            product_id = create_product(brand_id)
        else:
            log("[DRY RUN] Would create Core Deck product")
            product_id = "dry-run-product-id"

        # Step 3: Create project
        if not args.dry_run:
            project_id = create_project(brand_id, product_id)
        else:
            log("[DRY RUN] Would create Yakety Pack Instagram project")
            project_id = "dry-run-project-id"

        log("")

        # Step 4: Migrate accounts
        migrate_accounts(instagram_platform_id, project_id, dry_run=args.dry_run)

        # Step 5: Migrate posts
        migrate_posts(instagram_platform_id, project_id, dry_run=args.dry_run)

        # Step 6: Migrate video analyses
        migrate_video_analyses(instagram_platform_id, dry_run=args.dry_run)

        # Step 7: Verify
        if not args.dry_run:
            verify_migration()
        else:
            log("\n[DRY RUN] Migration complete (no changes made)")
            log("Run without --dry-run to apply changes")

    except Exception as e:
        log(f"Migration failed: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
