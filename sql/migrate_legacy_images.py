"""
Migration script to consolidate legacy product image columns into product_images table.

This script:
1. Reads all products with legacy image columns (main_image_storage_path, reference_image_storage_paths)
2. Inserts rows into product_images table for any paths not already there
3. Marks main images with is_main=True
4. Includes PDFs (they can be filtered in UI)

Run this script once to migrate existing data, then update code to use only product_images table.
"""

import sys
sys.path.insert(0, '/Users/ryemckenzie/projects/viraltracker')

from viraltracker.core.database import get_supabase_client


def migrate_legacy_images():
    db = get_supabase_client()

    # Get all products with legacy image columns
    products = db.table('products').select(
        'id, name, main_image_storage_path, reference_image_storage_paths'
    ).execute()

    print(f"Found {len(products.data)} products to check")

    migrated_count = 0
    skipped_count = 0

    for product in products.data:
        product_id = product['id']
        product_name = product['name']
        main_path = product.get('main_image_storage_path')
        ref_paths = product.get('reference_image_storage_paths') or []

        # Get existing paths in product_images for this product
        existing = db.table('product_images').select('storage_path').eq(
            'product_id', product_id
        ).execute()
        existing_paths = {row['storage_path'] for row in existing.data}

        # Migrate main image
        if main_path and main_path not in existing_paths:
            db.table('product_images').insert({
                'product_id': product_id,
                'storage_path': main_path,
                'is_main': True,
                'sort_order': 0
            }).execute()
            print(f"  + {product_name}: main image migrated")
            migrated_count += 1
            existing_paths.add(main_path)
        elif main_path:
            # Update existing to mark as main if not already
            db.table('product_images').update({
                'is_main': True
            }).eq('product_id', product_id).eq('storage_path', main_path).execute()

        # Migrate reference images
        for idx, ref_path in enumerate(ref_paths):
            if ref_path and ref_path not in existing_paths:
                db.table('product_images').insert({
                    'product_id': product_id,
                    'storage_path': ref_path,
                    'is_main': False,
                    'sort_order': idx + 1
                }).execute()
                print(f"  + {product_name}: ref image migrated ({ref_path.split('/')[-1]})")
                migrated_count += 1
                existing_paths.add(ref_path)
            elif ref_path:
                skipped_count += 1

    print()
    print(f"Migration complete!")
    print(f"  Migrated: {migrated_count} images")
    print(f"  Skipped (already exist): {skipped_count} images")

    # Verify final state
    total = db.table('product_images').select('id', count='exact').execute()
    print(f"  Total rows in product_images: {total.count}")


if __name__ == '__main__':
    print("=" * 60)
    print("Legacy Image Migration Script")
    print("=" * 60)
    print()

    confirm = input("This will migrate legacy images to product_images table. Continue? [y/N]: ")
    if confirm.lower() == 'y':
        migrate_legacy_images()
    else:
        print("Migration cancelled.")
