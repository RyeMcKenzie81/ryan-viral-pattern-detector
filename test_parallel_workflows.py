"""
Test script to run ad creation V2 pipeline with a template.
Uses run_ad_creation_v2 directly (replaces old complete_ad_workflow tests).
"""

import asyncio
import base64
from pathlib import Path

from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2
from viraltracker.agent.dependencies import AgentDependencies


# Test product ID for Wonder Paws
TEST_PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Test template
TEMPLATES = [
    "ad3-example.jpg"
]


async def run_workflow_for_template(template_name: str, index: int):
    """Run ad creation V2 workflow for a single template."""
    print(f"\n{'='*80}")
    print(f"[Workflow {index+1}] Starting V2 workflow for: {template_name}")
    print(f"{'='*80}\n")

    # Load template image
    template_path = Path(__file__).parent / "test_images" / "reference_ads" / template_name

    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}")
        return None

    # Read and encode image
    with open(template_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')

    # Create dependencies
    deps = AgentDependencies.create(project_name="default")

    try:
        result = await run_ad_creation_v2(
            product_id=TEST_PRODUCT_ID,
            reference_ad_base64=image_data,
            canvas_sizes=["1080x1080px"],
            color_modes=["original"],
            num_variations=5,
            content_source="recreate_template",
            auto_retry_rejected=True,
            deps=deps,
        )

        print(f"\n{'='*80}")
        print(f"[Workflow {index+1}] COMPLETED: {template_name}")
        print(f"  - Result: {result}")
        print(f"{'='*80}\n")

        return result

    except Exception as e:
        print(f"\n{'='*80}")
        print(f"[Workflow {index+1}] FAILED: {template_name}")
        print(f"  Error: {str(e)}")
        print(f"{'='*80}\n")
        return None


async def main():
    """Run the ad3 workflow to test V2 pipeline."""
    print(f"\n{'#'*80}")
    print(f"# AD CREATION V2 PIPELINE TEST")
    print(f"# Testing ad3-example.jpg template via run_ad_creation_v2")
    print(f"{'#'*80}\n")

    tasks = [
        run_workflow_for_template(template, i)
        for i, template in enumerate(TEMPLATES)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    print(f"\n{'#'*80}")
    print(f"# SUMMARY")
    print(f"{'#'*80}")

    for i, (template, result) in enumerate(zip(TEMPLATES, results)):
        if isinstance(result, Exception):
            print(f"  [{i+1}] {template}: FAILED - {str(result)}")
        elif result is None:
            print(f"  [{i+1}] {template}: FAILED")
        else:
            print(f"  [{i+1}] {template}: SUCCESS")

    print(f"{'#'*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
