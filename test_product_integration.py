#!/usr/bin/env python3
"""Integration test for --product flag."""

from viraltracker.core.database import get_supabase_client

def test_product_lookup():
    """Test that we can look up products correctly."""
    print("Testing product lookup...")

    supabase = get_supabase_client()

    # Test valid product
    product_result = supabase.table("products").select("id, name, slug").eq("slug", "collagen-3x-drops").execute()

    if product_result.data:
        product = product_result.data[0]
        print(f"✅ Found product: {product['name']} (slug: {product['slug']})")
        print(f"   ID: {product['id']}")
    else:
        print("❌ Could not find product 'collagen-3x-drops'")
        return False

    # Test invalid product
    invalid_result = supabase.table("products").select("id, name").eq("slug", "invalid-product").execute()

    if not invalid_result.data:
        print("✅ Invalid product correctly returns empty")
    else:
        print("❌ Invalid product should not exist")
        return False

    return True

def test_project_lookup():
    """Test that we can look up projects with brand/product info."""
    print("\nTesting project lookup...")

    supabase = get_supabase_client()

    project_result = supabase.table("projects").select(
        "id, name, brand_id, product_id, brands(id, name, products(id, name))"
    ).eq("slug", "wonder-paws-tiktok").execute()

    if project_result.data:
        project = project_result.data[0]
        print(f"✅ Found project: {project['name']}")
        print(f"   Brand: {project['brands']['name']}")
        products = project['brands'].get('products', [])
        if products:
            print(f"   Products: {', '.join([p['name'] for p in products])}")
        else:
            print("   Products: None")
    else:
        print("❌ Could not find project 'wonder-paws-tiktok'")
        return False

    return True

if __name__ == "__main__":
    print("="*60)
    print("TESTING PRODUCT FLAG INTEGRATION")
    print("="*60)

    success = True

    if not test_project_lookup():
        success = False

    if not test_product_lookup():
        success = False

    print("\n" + "="*60)
    if success:
        print("✅ ALL TESTS PASSED")
        print("="*60)
    else:
        print("❌ SOME TESTS FAILED")
        print("="*60)
        exit(1)
