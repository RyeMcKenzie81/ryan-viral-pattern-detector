"""
Ad Creation commands for ViralTracker CLI

Execute the Facebook Ad Creation Agent workflow from the command line.
"""

import click
import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime


@click.group('ad-creation')
def ad_creation_group():
    """Facebook Ad Creation Agent - Generate ads with AI"""
    pass


@ad_creation_group.command('create')
@click.option('--product-id', required=True, help='Product UUID')
@click.option('--reference-ad', required=True, type=click.Path(exists=True), help='Path to reference ad image')
@click.option('--project-id', default=None, help='Optional project UUID')
@click.option('--output-json', type=click.Path(), help='Export results to JSON file')
def create_ads(product_id: str, reference_ad: str, project_id: Optional[str], output_json: Optional[str]):
    """
    Execute complete Facebook ad creation workflow.

    Generates 5 ad variations with dual AI review (Claude + Gemini).
    Uses OR logic: either reviewer approving = approved.

    Examples:
        viraltracker ad-creation create --product-id abc-123 --reference-ad ./ref.png
        viraltracker ad-creation create --product-id abc-123 --reference-ad ./ref.png --output-json results.json
    """
    try:
        # Validate image file
        ref_path = Path(reference_ad)
        if not ref_path.is_file():
            click.echo(f"❌ Reference ad file not found: {reference_ad}", err=True)
            return

        # Check file extension
        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        if ref_path.suffix.lower() not in valid_extensions:
            click.echo(f"❌ Invalid image format. Supported: {', '.join(valid_extensions)}", err=True)
            return

        # Read and encode image
        try:
            with open(ref_path, 'rb') as f:
                image_data = f.read()
                reference_ad_base64 = base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            click.echo(f"❌ Failed to read image file: {e}", err=True)
            return

        # Run async workflow
        result = asyncio.run(_execute_workflow(
            product_id=product_id,
            reference_ad_base64=reference_ad_base64,
            reference_ad_filename=ref_path.name,
            project_id=project_id
        ))

        # Display results
        _display_results(result)

        # Export JSON if requested
        if output_json:
            with open(output_json, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            click.echo(f"\n📄 Results exported to: {output_json}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()


async def _execute_workflow(
    product_id: str,
    reference_ad_base64: str,
    reference_ad_filename: str,
    project_id: Optional[str]
):
    """Execute the ad creation workflow asynchronously"""
    from pydantic_ai import Agent
    from ..agent.dependencies import AgentDependencies
    from ..agent.agents.ad_creation_agent import ad_creation_agent

    click.echo("\n" + "="*60)
    click.echo("🎨 Starting Facebook Ad Creation Workflow...")
    click.echo("="*60 + "\n")

    # Initialize dependencies
    deps = AgentDependencies.create()

    # Execute workflow
    click.echo("⏳ Initializing agent...")

    result = await ad_creation_agent.run(
        'complete_ad_workflow',
        deps=deps,
        message_history=[],
        model_settings={
            'temperature': 0.7,
            'max_tokens': 4000
        }
    )

    # Extract result data
    if hasattr(result, 'data'):
        return result.data
    else:
        return result


def _display_results(result: dict):
    """Display workflow results in terminal-friendly format"""

    click.echo("\n" + "="*60)
    click.echo("📊 Workflow Results")
    click.echo("="*60 + "\n")

    # Product info
    if 'product' in result:
        product = result['product']
        click.echo(f"📦 Product: {product.get('name', 'Unknown')}")
        if 'brand' in product:
            click.echo(f"   Brand: {product['brand'].get('name', 'Unknown')}")

    click.echo(f"\n🆔 Ad Run ID: {result.get('ad_run_id', 'N/A')}")

    # Reference ad analysis
    if 'ad_analysis' in result:
        analysis = result['ad_analysis']
        click.echo(f"\n🔍 Reference Ad Analysis:")
        click.echo(f"   Format: {analysis.get('format', 'N/A')}")
        click.echo(f"   Layout: {analysis.get('layout', 'N/A')}")
        if 'color_palette' in analysis and analysis['color_palette']:
            colors = ', '.join(analysis['color_palette'][:3])
            click.echo(f"   Colors: {colors}")

    # Selected hooks
    if 'selected_hooks' in result:
        hooks = result['selected_hooks']
        click.echo(f"\n🎯 Selected Hooks ({len(hooks)}):")
        for i, hook in enumerate(hooks, 1):
            click.echo(f"   {i}. {hook.get('category', 'unknown')} (diversity: {hook.get('diversity_score', 0)})")

    # Generated ads
    if 'generated_ads' in result:
        ads = result['generated_ads']
        click.echo(f"\n🎨 Generated Ads ({len(ads)}):")
        click.echo("   " + "-"*56)

        for ad in ads:
            idx = ad.get('prompt_index', '?')
            status = ad.get('final_status', 'unknown')

            # Status symbol
            if status == 'approved':
                symbol = '✓'
                status_text = click.style('APPROVED', fg='green', bold=True)
            elif status == 'rejected':
                symbol = '✗'
                status_text = click.style('REJECTED', fg='red', bold=True)
            elif status == 'flagged':
                symbol = '⚠'
                status_text = click.style('FLAGGED', fg='yellow', bold=True)
            else:
                symbol = '?'
                status_text = status.upper()

            click.echo(f"   {symbol} Ad {idx}/5: {status_text}")

            # Review scores
            claude_review = ad.get('claude_review', {})
            gemini_review = ad.get('gemini_review', {})

            claude_decision = claude_review.get('decision', 'unknown')
            gemini_decision = gemini_review.get('decision', 'unknown')

            claude_score = claude_review.get('confidence_score', 0)
            gemini_score = gemini_review.get('confidence_score', 0)

            click.echo(f"      Claude: {claude_decision} ({claude_score:.2f})")
            click.echo(f"      Gemini: {gemini_decision} ({gemini_score:.2f})")

            # Storage path
            if 'storage_path' in ad:
                click.echo(f"      Path: {ad['storage_path']}")

            click.echo()

    # Summary counts
    click.echo("="*60)
    click.echo("📈 Summary")
    click.echo("="*60 + "\n")

    approved = result.get('approved_count', 0)
    rejected = result.get('rejected_count', 0)
    flagged = result.get('flagged_count', 0)

    click.echo(f"   ✓ Approved: {approved} ads")
    click.echo(f"   ✗ Rejected: {rejected} ads")
    click.echo(f"   ⚠ Flagged:  {flagged} ads (needs human review)")

    # Timestamp
    if 'created_at' in result:
        click.echo(f"\n   ⏰ Completed: {result['created_at']}")

    # Summary message
    if 'summary' in result:
        click.echo(f"\n💬 {result['summary']}")

    click.echo()


@ad_creation_group.command('list-runs')
@click.option('--product-id', help='Filter by product UUID')
@click.option('--limit', default=10, help='Number of runs to display')
def list_runs(product_id: Optional[str], limit: int):
    """
    List recent ad creation runs

    Examples:
        viraltracker ad-creation list-runs
        viraltracker ad-creation list-runs --product-id abc-123
        viraltracker ad-creation list-runs --limit 20
    """
    try:
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Build query
        query = supabase.table('ad_runs')\
            .select('*, products!inner(name, slug), generated_ads(id, final_status)')\
            .order('created_at', desc=True)\
            .limit(limit)

        if product_id:
            query = query.eq('product_id', product_id)

        result = query.execute()

        if not result.data:
            click.echo("No ad runs found.")
            return

        # Display runs
        click.echo(f"\n{'='*80}")
        click.echo(f"🎨 Ad Creation Runs ({len(result.data)})")
        click.echo(f"{'='*80}\n")

        for run in result.data:
            click.echo(f"🆔 {run['id']}")
            click.echo(f"   Product: {run['products']['name']}")
            click.echo(f"   Status: {run.get('status', 'unknown')}")

            # Count ad statuses
            ads = run.get('generated_ads', [])
            if ads:
                approved = sum(1 for ad in ads if ad.get('final_status') == 'approved')
                rejected = sum(1 for ad in ads if ad.get('final_status') == 'rejected')
                flagged = sum(1 for ad in ads if ad.get('final_status') == 'flagged')

                click.echo(f"   Ads: ✓{approved} ✗{rejected} ⚠{flagged}")

            click.echo(f"   Created: {run['created_at']}")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


@ad_creation_group.command('show-run')
@click.argument('run_id')
@click.option('--export-json', type=click.Path(), help='Export to JSON file')
def show_run(run_id: str, export_json: Optional[str]):
    """
    Show detailed information about a specific ad run

    Examples:
        viraltracker ad-creation show-run abc-123
        viraltracker ad-creation show-run abc-123 --export-json run.json
    """
    try:
        from ..core.database import get_supabase_client

        supabase = get_supabase_client()

        # Fetch run with all related data
        result = supabase.table('ad_runs')\
            .select('''
                *,
                products!inner(name, slug, brand_id, brands!inner(name, slug)),
                generated_ads(
                    id,
                    prompt_index,
                    storage_path,
                    final_status,
                    claude_review,
                    gemini_review,
                    created_at
                )
            ''')\
            .eq('id', run_id)\
            .single()\
            .execute()

        if not result.data:
            click.echo(f"❌ Ad run '{run_id}' not found", err=True)
            return

        run = result.data

        # Display detailed information
        _display_results(run)

        # Export if requested
        if export_json:
            with open(export_json, 'w') as f:
                json.dump(run, f, indent=2, default=str)
            click.echo(f"\n📄 Run data exported to: {export_json}")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
