"""
Test script to run a full ad creation workflow with Yakety Pack.

This tests the secondary product image feature end-to-end:
1. Fetches Yakety Pack product
2. Gets box (hero) and cards (contents) images
3. Runs workflow with both images
4. Verifies prompt contains SECONDARY instructions
5. Generates actual ad

Run with: python3 test_yakety_pack_workflow.py
"""

import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Enable logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def find_yakety_pack():
    """Find Yakety Pack product and its images."""
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    # Find Yakety Pack product
    result = db.table("products").select("id, name, brand_id").ilike("name", "%yakety%").execute()

    if not result.data:
        print("❌ Yakety Pack product not found")
        return None, []

    product = result.data[0]
    print(f"✅ Found product: {product['name']} (ID: {product['id']})")

    # Get images for this product
    images = db.table("product_images").select(
        "id, storage_path, is_main, image_analysis"
    ).eq("product_id", product['id']).execute()

    image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
    image_list = [
        img for img in images.data
        if img['storage_path'].lower().endswith(image_extensions)
    ]

    print(f"✅ Found {len(image_list)} images:")
    for idx, img in enumerate(image_list):
        main_marker = " [MAIN]" if img.get('is_main') else ""
        print(f"   {idx+1}. {img['storage_path']}{main_marker}")

    return product, image_list


async def run_test_workflow(product, image_paths):
    """Run a minimal workflow test with 2 images."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.agent.agents.ad_creation_agent import (
        generate_nano_banana_prompt,
        execute_nano_banana
    )
    import base64

    print("\n" + "=" * 60)
    print("RUNNING WORKFLOW TEST WITH 2 IMAGES")
    print("=" * 60)

    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    # Get a reference ad from storage
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    ref_ads = db.storage.from_("reference-ads").list()

    if not ref_ads:
        print("❌ No reference ads found in storage")
        return False

    # Use first available reference ad
    ref_ad_name = ref_ads[0]['name']
    ref_ad_path = f"reference-ads/{ref_ad_name}"
    print(f"Using reference ad: {ref_ad_path}")

    # Mock data for testing
    selected_hook = {
        "hook_id": "test-hook",
        "text": "Finally, a game the whole family actually enjoys!",
        "adapted_text": "Finally, a game the whole family actually enjoys!",
        "category": "transformation"
    }

    product_dict = {
        "name": product['name'],
        "benefits": ["Fun for everyone", "No screens needed", "Easy to learn"],
        "target_audience": "Families looking for quality time together",
        "brand_id": product['brand_id']
    }

    ad_analysis = {
        "format_type": "product_showcase",
        "layout_structure": "product-center",
        "canvas_size": "1080x1080px",
        "color_palette": ["#FFFFFF", "#FF6B6B", "#4ECDC4"],
        "authenticity_markers": ["playful", "family-friendly"],
        "text_placement": {"headline": "top", "subheadline": "bottom"}
    }

    # Generate prompt with 2 images
    print(f"\nGenerating prompt with {len(image_paths)} images...")
    prompt = await generate_nano_banana_prompt(
        ctx=ctx,
        prompt_index=1,
        selected_hook=selected_hook,
        product=product_dict,
        ad_analysis=ad_analysis,
        ad_brief_instructions="Create engaging Facebook ads for families",
        reference_ad_path=ref_ad_path,
        product_image_paths=image_paths
    )

    # Verify prompt contains SECONDARY
    full_prompt = prompt['full_prompt']
    has_secondary = "SECONDARY" in full_prompt
    has_primary = "PRIMARY" in full_prompt

    print(f"\nPrompt verification:")
    print(f"  - Contains PRIMARY: {has_primary}")
    print(f"  - Contains SECONDARY: {has_secondary}")
    print(f"  - product_image_paths: {prompt['product_image_paths']}")

    if len(image_paths) == 2 and not has_secondary:
        print("❌ FAIL: 2 images provided but SECONDARY not in prompt")
        return False
    elif len(image_paths) == 2 and has_secondary:
        print("✅ PASS: SECONDARY instructions present in prompt")

    # Print excerpt of product image instructions
    print("\n--- Product Image Instructions Excerpt ---")
    if "Product Image Instructions" in full_prompt:
        start = full_prompt.find("**Product Image Instructions:**")
        end = full_prompt.find("**Critical Requirements:**")
        if start != -1 and end != -1:
            excerpt = full_prompt[start:end].strip()
            print(excerpt[:600])

    # Ask before running actual generation (costs money)
    print("\n" + "=" * 60)
    response = input("Run actual image generation? This will call Gemini API. (y/n): ")
    if response.lower() != 'y':
        print("Skipped image generation.")
        return True

    # Execute generation
    print("\nExecuting Nano Banana generation...")
    try:
        generated_ad = await execute_nano_banana(
            ctx=ctx,
            nano_banana_prompt=prompt
        )
        print(f"✅ Image generated successfully!")
        print(f"   - Model used: {generated_ad.get('model_used')}")
        print(f"   - Generation time: {generated_ad.get('generation_time_ms')}ms")
        print(f"   - Reference images used: {generated_ad.get('num_reference_images')}")

        # Save to file for inspection
        import base64
        output_path = "test_output_yakety_pack.png"
        with open(output_path, 'wb') as f:
            f.write(base64.b64decode(generated_ad['image_base64']))
        print(f"   - Saved to: {output_path}")

        return True

    except Exception as e:
        print(f"❌ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("YAKETY PACK SECONDARY IMAGE TEST")
    print("=" * 60)

    # Find product and images
    product, images = await find_yakety_pack()

    if not product:
        return False

    if len(images) < 2:
        print(f"❌ Need at least 2 images, found {len(images)}")
        return False

    # Use first 2 images (box + contents)
    image_paths = [img['storage_path'] for img in images[:2]]
    print(f"\nUsing images for test:")
    print(f"  Primary: {image_paths[0]}")
    print(f"  Secondary: {image_paths[1]}")

    # Run workflow test
    success = await run_test_workflow(product, image_paths)

    print("\n" + "=" * 60)
    if success:
        print("✅ TEST PASSED")
    else:
        print("❌ TEST FAILED")
    print("=" * 60)

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
