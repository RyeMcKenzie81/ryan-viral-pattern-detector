"""
Test script to run 5 parallel ad creation workflows with different templates.
Each workflow generates 5 ads from a different reference template.
"""

import asyncio
import base64
from pathlib import Path
from pydantic_ai import RunContext
from pydantic_ai.usage import RunUsage

from viraltracker.agent.agents.ad_creation_agent import complete_ad_workflow
from viraltracker.agent.dependencies import AgentDependencies


# Test product ID for Wonder Paws
TEST_PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Test only ad3-example.jpg for social proof feature validation
TEMPLATES = [
    "ad3-example.jpg"
]


async def run_workflow_for_template(template_name: str, index: int):
    """Run ad creation workflow for a single template."""
    print(f"\n{'='*80}")
    print(f"[Workflow {index+1}/5] Starting workflow for: {template_name}")
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

    # Create RunContext
    ctx = RunContext(
        deps=deps,
        model=None,
        usage=RunUsage()
    )

    try:
        # Run the workflow
        result = await complete_ad_workflow(
            ctx=ctx,
            product_id=TEST_PRODUCT_ID,
            reference_ad_base64=image_data,
            reference_ad_filename=template_name,
            project_id=""
        )

        print(f"\n{'='*80}")
        print(f"[Workflow {index+1}/5] COMPLETED: {template_name}")
        print(f"  - Ad Run ID: {result.get('ad_run_id')}")
        print(f"  - Generated Ads: {len(result.get('generated_ads', []))}")
        print(f"  - Approved: {result.get('approved_count', 0)}")
        print(f"  - Rejected: {result.get('rejected_count', 0)}")
        print(f"  - Flagged: {result.get('flagged_count', 0)}")
        print(f"{'='*80}\n")

        return result

    except Exception as e:
        print(f"\n{'='*80}")
        print(f"[Workflow {index+1}/5] FAILED: {template_name}")
        print(f"  Error: {str(e)}")
        print(f"{'='*80}\n")
        return None


async def main():
    """Run the ad3 workflow to test social proof feature."""
    print(f"\n{'#'*80}")
    print(f"# AD3 SOCIAL PROOF TEST")
    print(f"# Testing ad3-example.jpg template with social proof feature")
    print(f"# Expected: Template should detect social proof and include it in ads")
    print(f"{'#'*80}\n")

    # Create tasks for all workflows
    tasks = [
        run_workflow_for_template(template, i)
        for i, template in enumerate(TEMPLATES)
    ]

    # Run all workflows in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Print summary
    print(f"\n{'#'*80}")
    print(f"# SUMMARY")
    print(f"{'#'*80}")

    successful = 0
    failed = 0
    total_ads = 0
    total_approved = 0

    for i, (template, result) in enumerate(zip(TEMPLATES, results)):
        if isinstance(result, Exception):
            print(f"  [{i+1}] {template}: FAILED - {str(result)}")
            failed += 1
        elif result is None:
            print(f"  [{i+1}] {template}: FAILED")
            failed += 1
        else:
            print(f"  [{i+1}] {template}: SUCCESS - {len(result.get('generated_ads', []))} ads, {result.get('approved_count', 0)} approved")
            successful += 1
            total_ads += len(result.get('generated_ads', []))
            total_approved += result.get('approved_count', 0)

    print(f"\n  Total Successful: {successful}/{len(TEMPLATES)}")
    print(f"  Total Failed: {failed}/{len(TEMPLATES)}")
    print(f"  Total Ads Generated: {total_ads}")
    print(f"  Total Ads Approved: {total_approved}")
    print(f"{'#'*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
