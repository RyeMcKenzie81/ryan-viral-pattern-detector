"""
Test script to verify secondary product image feature.

Run with: python3 test_secondary_image.py

Tests:
1. Prompt construction (1 image vs 2 images)
2. Verify "SECONDARY" keyword appears only when 2 images provided
3. Check that product_image_paths is correctly set in prompt dict
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_prompt_construction():
    """Test that prompts are correctly constructed for 1 and 2 images."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.agent.agents.ad_creation_agent import generate_nano_banana_prompt

    print("\n" + "=" * 60)
    print("TEST: Prompt Construction for Secondary Product Image")
    print("=" * 60)

    # Create dependencies and context
    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    # Mock data for testing
    selected_hook = {
        "hook_id": "test-hook-id",
        "text": "Test hook text",
        "adapted_text": "This product changed my life!",
        "category": "skepticism_overcome"
    }
    product = {
        "name": "Yakety Pack",
        "benefits": ["Fun for the whole family", "Great conversation starter"],
        "target_audience": "Parents looking for screen-free entertainment",
        "brand_id": "test-brand"
    }
    ad_analysis = {
        "format_type": "testimonial",
        "layout_structure": "product-left, text-right",
        "canvas_size": "1080x1080px",
        "color_palette": ["#FFFFFF", "#000000", "#FF6B6B"],
        "authenticity_markers": ["user-generated style", "casual tone"]
    }

    # =====================================================
    # TEST 1: Single Image
    # =====================================================
    print("\n--- TEST 1: Single Product Image ---")
    try:
        prompt_1 = await generate_nano_banana_prompt(
            ctx=ctx,
            prompt_index=1,
            selected_hook=selected_hook,
            product=product,
            ad_analysis=ad_analysis,
            ad_brief_instructions="Create engaging Facebook ads",
            reference_ad_path="reference-ads/test-template.png",
            product_image_paths=["products/yakety-pack/box.png"]  # Single image
        )

        # Verify return structure
        assert "product_image_paths" in prompt_1, "Missing 'product_image_paths' key"
        assert len(prompt_1["product_image_paths"]) == 1, "Expected 1 image path"

        # Verify prompt content
        full_prompt = prompt_1["full_prompt"]
        has_secondary = "SECONDARY" in full_prompt

        print(f"  product_image_paths: {prompt_1['product_image_paths']}")
        print(f"  Prompt contains 'SECONDARY': {has_secondary}")

        if has_secondary:
            print("  ❌ FAIL: Single image should NOT have SECONDARY in prompt")
            return False
        else:
            print("  ✅ PASS: Single image prompt correct - no SECONDARY instructions")

    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    # =====================================================
    # TEST 2: Two Images
    # =====================================================
    print("\n--- TEST 2: Two Product Images ---")
    try:
        prompt_2 = await generate_nano_banana_prompt(
            ctx=ctx,
            prompt_index=1,
            selected_hook=selected_hook,
            product=product,
            ad_analysis=ad_analysis,
            ad_brief_instructions="Create engaging Facebook ads",
            reference_ad_path="reference-ads/test-template.png",
            product_image_paths=[
                "products/yakety-pack/box.png",
                "products/yakety-pack/cards.png"
            ]  # Two images
        )

        # Verify return structure
        assert "product_image_paths" in prompt_2, "Missing 'product_image_paths' key"
        assert len(prompt_2["product_image_paths"]) == 2, "Expected 2 image paths"

        # Verify prompt content
        full_prompt = prompt_2["full_prompt"]
        has_secondary = "SECONDARY" in full_prompt
        has_primary = "PRIMARY" in full_prompt

        print(f"  product_image_paths: {prompt_2['product_image_paths']}")
        print(f"  Prompt contains 'PRIMARY': {has_primary}")
        print(f"  Prompt contains 'SECONDARY': {has_secondary}")

        if not has_secondary:
            print("  ❌ FAIL: Two images SHOULD have SECONDARY in prompt")
            return False
        elif not has_primary:
            print("  ❌ FAIL: Two images SHOULD have PRIMARY in prompt")
            return False
        else:
            print("  ✅ PASS: Two image prompt correct - includes PRIMARY and SECONDARY instructions")

    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    # =====================================================
    # TEST 3: Print prompt excerpt for verification
    # =====================================================
    print("\n--- PROMPT EXCERPT (Two Images) ---")
    full_prompt = prompt_2["full_prompt"]

    # Find the product image instructions section
    if "Product Image Instructions" in full_prompt:
        start = full_prompt.find("**Product Image Instructions:**")
        end = full_prompt.find("**Critical Requirements:**")
        if start != -1 and end != -1:
            excerpt = full_prompt[start:end].strip()
            print(excerpt[:800] + "..." if len(excerpt) > 800 else excerpt)

    # =====================================================
    # TEST 4: Verify Reference Images section
    # =====================================================
    print("\n--- TEST 4: Reference Images Section ---")
    if "Reference Images:" in full_prompt:
        start = full_prompt.find("**Reference Images:**")
        end = full_prompt.find("\n\n", start + 20)
        if start != -1:
            ref_section = full_prompt[start:end if end != -1 else start + 300].strip()
            print(ref_section)

            # Verify both product images are listed
            if "Primary Product (Image 2)" in ref_section and "Secondary Product (Image 3)" in ref_section:
                print("  ✅ PASS: Both product images correctly labeled in Reference Images")
            else:
                print("  ❌ FAIL: Product images not correctly labeled")
                return False

    return True


async def test_empty_image_list():
    """Test that empty image list raises ValueError."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.agent.agents.ad_creation_agent import generate_nano_banana_prompt

    print("\n--- TEST 5: Empty Image List Validation ---")

    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    try:
        await generate_nano_banana_prompt(
            ctx=ctx,
            prompt_index=1,
            selected_hook={"adapted_text": "Test"},
            product={"name": "Test"},
            ad_analysis={"format_type": "test"},
            ad_brief_instructions="Test",
            reference_ad_path="test.png",
            product_image_paths=[]  # Empty list - should fail
        )
        print("  ❌ FAIL: Should have raised ValueError for empty image list")
        return False
    except ValueError as e:
        if "empty" in str(e).lower():
            print(f"  ✅ PASS: Correctly raised ValueError: {e}")
            return True
        else:
            print(f"  ❌ FAIL: Wrong error message: {e}")
            return False
    except Exception as e:
        print(f"  ❌ FAIL: Wrong exception type: {type(e).__name__}: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("SECONDARY PRODUCT IMAGE - TEST SUITE")
    print("=" * 60)

    all_passed = True

    # Test 1-4: Prompt construction
    if not await test_prompt_construction():
        all_passed = False

    # Test 5: Validation
    if not await test_empty_image_list():
        all_passed = False

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
