"""
Script Management CLI Commands

Commands for managing product scripts (creation, versioning, export).
"""

import json
import logging
from datetime import datetime
from typing import Optional

import click

from ..core.database import get_supabase_client


logger = logging.getLogger(__name__)


@click.group(name="script")
def script_group():
    """Manage product scripts"""
    pass


@script_group.command(name="create")
@click.option('--analysis', required=True, help='Video analysis ID to create script from')
@click.option('--title', required=True, help='Script title')
@click.option('--description', help='Script description')
@click.option('--status', default='draft', type=click.Choice(['draft', 'review', 'approved', 'in_production', 'produced', 'published']), help='Initial status')
def create_script(analysis: str, title: str, description: Optional[str], status: str):
    """
    Create a script from a video analysis.

    Examples:
        vt script create --analysis <uuid> --title "Screen Time Standoff Adaptation"
        vt script create --analysis <uuid> --title "My Script" --status review
    """
    click.echo("=" * 60)
    click.echo("📝 Creating Product Script")
    click.echo("=" * 60)
    click.echo()

    supabase = get_supabase_client()

    # Get the video analysis
    analysis_result = supabase.table('video_analysis').select(
        '*, posts(id, post_url, caption, account_id)'
    ).eq('id', analysis).execute()

    if not analysis_result.data:
        click.echo(f"❌ Error: Video analysis '{analysis}' not found", err=True)
        return

    analysis_data = analysis_result.data[0]

    # Check if it has a product_id
    if not analysis_data.get('product_id'):
        click.echo("❌ Error: This analysis has no product association", err=True)
        click.echo("💡 Re-run analysis with --product flag to generate product adaptations")
        return

    # Get product and brand info
    product_result = supabase.table('products').select('*, brands(id, name)').eq('id', analysis_data['product_id']).execute()

    if not product_result.data:
        click.echo("❌ Error: Product not found", err=True)
        return

    product_data = product_result.data[0]
    brand_id = product_data['brands']['id']

    # Parse the product adaptation
    if not analysis_data.get('product_adaptation'):
        click.echo("❌ Error: This analysis has no product adaptation", err=True)
        return

    product_adaptation = json.loads(analysis_data['product_adaptation'])

    # Extract script content
    script_content = product_adaptation.get('script_outline', '')

    if not script_content:
        click.echo("⚠️  Warning: No script outline found in product adaptation")
        script_content = "# Script Content\n\n(To be written)"

    # Build script structure
    script_structure = {
        'adaptation_ideas': product_adaptation.get('adaptation_ideas', []),
        'how_style_applies': product_adaptation.get('how_this_video_style_applies', ''),
        'key_differences': product_adaptation.get('key_differences', ''),
        'target_audience_fit': product_adaptation.get('target_audience_fit', ''),
        'source_viral_factors': analysis_data.get('viral_factors')
    }

    # Extract viral patterns for tracking
    viral_factors = json.loads(analysis_data['viral_factors']) if analysis_data.get('viral_factors') else {}
    source_viral_patterns = [
        {
            'pattern': 'hook_strength',
            'score': viral_factors.get('hook_strength', 0)
        },
        {
            'pattern': 'emotional_impact',
            'score': viral_factors.get('emotional_impact', 0)
        },
        {
            'pattern': 'relatability',
            'score': viral_factors.get('relatability', 0)
        }
    ]

    # Create script record
    script_record = {
        'product_id': analysis_data['product_id'],
        'brand_id': brand_id,
        'source_video_id': analysis_data['post_id'],
        'video_analysis_id': analysis,
        'title': title,
        'description': description,
        'script_type': 'adaptation',
        'status': status,
        'script_content': script_content,
        'script_structure': script_structure,
        'generated_by_ai': True,
        'ai_model': analysis_data.get('analysis_model'),
        'source_viral_patterns': source_viral_patterns,
        'target_viral_score': viral_factors.get('overall_score', 0),
        'version_number': 1,
        'is_current_version': True
    }

    # Insert script
    result = supabase.table('product_scripts').insert(script_record).execute()

    if result.data:
        script = result.data[0]
        click.echo(f"✅ Script created successfully!")
        click.echo()
        click.echo(f"   ID: {script['id']}")
        click.echo(f"   Title: {script['title']}")
        click.echo(f"   Product: {product_data['name']}")
        click.echo(f"   Brand: {product_data['brands']['name']}")
        click.echo(f"   Status: {script['status']}")
        click.echo(f"   Version: {script['version_number']}")
        click.echo()
        click.echo("💡 Next steps:")
        click.echo(f"   - View script: vt script show {script['id']}")
        click.echo(f"   - Update script: vt script update {script['id']}")
        click.echo(f"   - Export script: vt script export {script['id']}")
    else:
        click.echo("❌ Error: Failed to create script", err=True)


@script_group.command(name="list")
@click.option('--product', help='Filter by product slug')
@click.option('--brand', help='Filter by brand slug')
@click.option('--status', type=click.Choice(['draft', 'review', 'approved', 'in_production', 'produced', 'published', 'archived']), help='Filter by status')
@click.option('--limit', type=int, default=20, help='Maximum number of scripts to show')
def list_scripts(product: Optional[str], brand: Optional[str], status: Optional[str], limit: int):
    """
    List product scripts.

    Examples:
        vt script list
        vt script list --product core-deck
        vt script list --brand yakety-pack --status draft
        vt script list --status approved --limit 10
    """
    supabase = get_supabase_client()

    # Build query
    query = supabase.table('product_scripts').select(
        '*, products(name, slug), brands(name, slug)'
    ).order('created_at', desc=True).limit(limit)

    # Apply filters
    if product:
        # Get product ID from slug
        product_result = supabase.table('products').select('id').eq('slug', product).execute()
        if product_result.data:
            query = query.eq('product_id', product_result.data[0]['id'])
        else:
            click.echo(f"❌ Error: Product '{product}' not found", err=True)
            return

    if brand:
        # Get brand ID from slug
        brand_result = supabase.table('brands').select('id').eq('slug', brand).execute()
        if brand_result.data:
            query = query.eq('brand_id', brand_result.data[0]['id'])
        else:
            click.echo(f"❌ Error: Brand '{brand}' not found", err=True)
            return

    if status:
        query = query.eq('status', status)

    # Execute query
    result = query.execute()

    if not result.data:
        click.echo("📝 No scripts found")
        if product or brand or status:
            click.echo("\n💡 Try adjusting your filters")
        return

    # Display results
    click.echo("=" * 80)
    click.echo(f"📝 Product Scripts ({len(result.data)} found)")
    click.echo("=" * 80)
    click.echo()

    for script in result.data:
        status_emoji = {
            'draft': '📝',
            'review': '👀',
            'approved': '✅',
            'in_production': '🎬',
            'produced': '🎥',
            'published': '🚀',
            'archived': '📦'
        }.get(script['status'], '📄')

        click.echo(f"{status_emoji} {script['title']}")
        click.echo(f"   ID: {script['id']}")
        click.echo(f"   Product: {script['products']['name']} ({script['products']['slug']})")
        click.echo(f"   Brand: {script['brands']['name']}")
        click.echo(f"   Status: {script['status']}")
        click.echo(f"   Version: {script['version_number']}" + (" (current)" if script['is_current_version'] else ""))
        click.echo(f"   Created: {script['created_at'][:10]}")

        if script.get('target_viral_score'):
            click.echo(f"   Target Viral Score: {script['target_viral_score']}/10")

        click.echo()

    click.echo("💡 View details: vt script show <id>")


@script_group.command(name="show")
@click.argument('script_id')
@click.option('--format', type=click.Choice(['summary', 'full', 'json']), default='summary', help='Display format')
def show_script(script_id: str, format: str):
    """
    Display script details.

    Examples:
        vt script show <uuid>
        vt script show <uuid> --format full
        vt script show <uuid> --format json
    """
    supabase = get_supabase_client()

    # Get script with relationships
    result = supabase.table('product_scripts').select(
        '*, products(name, slug), brands(name, slug)'
    ).eq('id', script_id).execute()

    if not result.data:
        click.echo(f"❌ Error: Script '{script_id}' not found", err=True)
        return

    script = result.data[0]

    if format == 'json':
        click.echo(json.dumps(script, indent=2))
        return

    # Summary or full format
    click.echo("=" * 80)
    click.echo(f"📝 {script['title']}")
    click.echo("=" * 80)
    click.echo()

    click.echo(f"📦 Product: {script['products']['name']} ({script['products']['slug']})")
    click.echo(f"🏢 Brand: {script['brands']['name']}")
    click.echo(f"📊 Status: {script['status']}")
    click.echo(f"🔢 Version: {script['version_number']}" + (" (current)" if script['is_current_version'] else ""))
    click.echo(f"🤖 AI Generated: {'Yes' if script.get('generated_by_ai') else 'No'}")

    if script.get('ai_model'):
        click.echo(f"   Model: {script['ai_model']}")

    if script.get('description'):
        click.echo(f"\n📄 Description: {script['description']}")

    click.echo()
    click.echo("─" * 80)
    click.echo("📝 SCRIPT CONTENT:")
    click.echo("─" * 80)
    click.echo()
    click.echo(script['script_content'])
    click.echo()

    if format == 'full':
        if script.get('script_structure'):
            structure = script['script_structure']

            if structure.get('adaptation_ideas'):
                click.echo("─" * 80)
                click.echo("💡 ADAPTATION IDEAS:")
                click.echo("─" * 80)
                for i, idea in enumerate(structure['adaptation_ideas'], 1):
                    click.echo(f"{i}. {idea}")
                click.echo()

            if structure.get('how_style_applies'):
                click.echo("─" * 80)
                click.echo("🎨 HOW STYLE APPLIES:")
                click.echo("─" * 80)
                click.echo(structure['how_style_applies'])
                click.echo()

            if structure.get('target_audience_fit'):
                click.echo("─" * 80)
                click.echo("🎯 TARGET AUDIENCE FIT:")
                click.echo("─" * 80)
                click.echo(structure['target_audience_fit'])
                click.echo()

        if script.get('source_viral_patterns'):
            click.echo("─" * 80)
            click.echo("📊 VIRAL PATTERNS:")
            click.echo("─" * 80)
            for pattern in script['source_viral_patterns']:
                if isinstance(pattern, dict):
                    click.echo(f"   {pattern.get('pattern', 'Unknown')}: {pattern.get('score', 0)}/10")
            click.echo()

        if script.get('target_viral_score'):
            click.echo(f"🎯 Target Viral Score: {script['target_viral_score']}/10")
            click.echo()

    click.echo("─" * 80)
    click.echo(f"📅 Created: {script['created_at']}")
    click.echo(f"📅 Updated: {script['updated_at']}")
    click.echo()
    click.echo("💡 Next steps:")
    click.echo(f"   - Update: vt script update {script_id}")
    click.echo(f"   - Create version: vt script version {script_id}")
    click.echo(f"   - Change status: vt script status {script_id} --status <status>")
    click.echo(f"   - Export: vt script export {script_id}")


@script_group.command(name="update")
@click.argument('script_id')
@click.option('--title', help='New title')
@click.option('--description', help='New description')
@click.option('--content', help='New script content')
@click.option('--content-file', type=click.Path(exists=True), help='Read content from file')
def update_script(script_id: str, title: Optional[str], description: Optional[str], content: Optional[str], content_file: Optional[str]):
    """
    Update script details.

    Examples:
        vt script update <uuid> --title "New Title"
        vt script update <uuid> --description "Updated description"
        vt script update <uuid> --content "New script content..."
        vt script update <uuid> --content-file script.txt
    """
    supabase = get_supabase_client()

    # Verify script exists
    result = supabase.table('product_scripts').select('id, title').eq('id', script_id).execute()

    if not result.data:
        click.echo(f"❌ Error: Script '{script_id}' not found", err=True)
        return

    # Build update dict
    updates = {}

    if title:
        updates['title'] = title

    if description is not None:  # Allow empty string
        updates['description'] = description

    if content_file:
        with open(content_file, 'r') as f:
            updates['script_content'] = f.read()
    elif content:
        updates['script_content'] = content

    if not updates:
        click.echo("❌ Error: No updates specified", err=True)
        click.echo("💡 Use --title, --description, --content, or --content-file")
        return

    # Update script
    update_result = supabase.table('product_scripts').update(updates).eq('id', script_id).execute()

    if update_result.data:
        click.echo(f"✅ Script updated successfully!")
        click.echo()
        for key, value in updates.items():
            if key == 'script_content':
                click.echo(f"   Updated {key}: {len(value)} characters")
            else:
                click.echo(f"   Updated {key}: {value}")
        click.echo()
        click.echo(f"💡 View changes: vt script show {script_id}")
    else:
        click.echo("❌ Error: Failed to update script", err=True)


@script_group.command(name="version")
@click.argument('script_id')
@click.option('--notes', help='Version notes (what changed)')
@click.option('--content', help='New script content for this version')
@click.option('--content-file', type=click.Path(exists=True), help='Read content from file')
def create_version(script_id: str, notes: Optional[str], content: Optional[str], content_file: Optional[str]):
    """
    Create a new version of a script.

    Examples:
        vt script version <uuid> --notes "Updated hook timing"
        vt script version <uuid> --content "New content..." --notes "Revised based on feedback"
        vt script version <uuid> --content-file revised.txt --notes "Major revision"
    """
    supabase = get_supabase_client()

    # Get current script
    result = supabase.table('product_scripts').select('*').eq('id', script_id).execute()

    if not result.data:
        click.echo(f"❌ Error: Script '{script_id}' not found", err=True)
        return

    current_script = result.data[0]

    # Mark current version as not current
    supabase.table('product_scripts').update({
        'is_current_version': False
    }).eq('id', script_id).execute()

    # Prepare new version
    new_version = {
        'product_id': current_script['product_id'],
        'brand_id': current_script['brand_id'],
        'source_video_id': current_script['source_video_id'],
        'video_analysis_id': current_script['video_analysis_id'],
        'parent_script_id': script_id,
        'title': current_script['title'],
        'description': current_script['description'],
        'script_type': current_script['script_type'],
        'status': current_script['status'],
        'script_structure': current_script['script_structure'],
        'estimated_duration_sec': current_script.get('estimated_duration_sec'),
        'production_difficulty': current_script.get('production_difficulty'),
        'required_props': current_script.get('required_props'),
        'required_locations': current_script.get('required_locations'),
        'talent_requirements': current_script.get('talent_requirements'),
        'generated_by_ai': current_script.get('generated_by_ai'),
        'ai_model': current_script.get('ai_model'),
        'source_viral_patterns': current_script.get('source_viral_patterns'),
        'target_viral_score': current_script.get('target_viral_score'),
        'version_number': current_script['version_number'] + 1,
        'version_notes': notes,
        'is_current_version': True
    }

    # Handle content update
    if content_file:
        with open(content_file, 'r') as f:
            new_version['script_content'] = f.read()
    elif content:
        new_version['script_content'] = content
    else:
        new_version['script_content'] = current_script['script_content']

    # Create new version
    version_result = supabase.table('product_scripts').insert(new_version).execute()

    if version_result.data:
        new_script = version_result.data[0]
        click.echo(f"✅ New version created successfully!")
        click.echo()
        click.echo(f"   Previous version: v{current_script['version_number']}")
        click.echo(f"   New version: v{new_script['version_number']} (current)")
        click.echo(f"   New ID: {new_script['id']}")
        if notes:
            click.echo(f"   Notes: {notes}")
        click.echo()
        click.echo("💡 Next steps:")
        click.echo(f"   - View new version: vt script show {new_script['id']}")
        click.echo(f"   - View old version: vt script show {script_id}")
    else:
        click.echo("❌ Error: Failed to create new version", err=True)


@script_group.command(name="status")
@click.argument('script_id')
@click.option('--status', required=True, type=click.Choice(['draft', 'review', 'approved', 'in_production', 'produced', 'published', 'archived']), help='New status')
def update_status(script_id: str, status: str):
    """
    Update script status.

    Status workflow: draft → review → approved → in_production → produced → published

    Examples:
        vt script status <uuid> --status review
        vt script status <uuid> --status approved
        vt script status <uuid> --status produced
    """
    supabase = get_supabase_client()

    # Get current status
    result = supabase.table('product_scripts').select('id, title, status').eq('id', script_id).execute()

    if not result.data:
        click.echo(f"❌ Error: Script '{script_id}' not found", err=True)
        return

    current = result.data[0]
    old_status = current['status']

    # Update status
    update_result = supabase.table('product_scripts').update({
        'status': status
    }).eq('id', script_id).execute()

    if update_result.data:
        click.echo(f"✅ Status updated successfully!")
        click.echo()
        click.echo(f"   Script: {current['title']}")
        click.echo(f"   {old_status} → {status}")
        click.echo()

        # Suggest next steps based on status
        if status == 'review':
            click.echo("💡 Next steps:")
            click.echo("   - Review and edit: vt script update <id>")
            click.echo("   - Approve: vt script status <id> --status approved")
        elif status == 'approved':
            click.echo("💡 Next steps:")
            click.echo("   - Move to production: vt script status <id> --status in_production")
            click.echo("   - Export for team: vt script export <id>")
        elif status == 'in_production':
            click.echo("💡 Next steps:")
            click.echo("   - Mark as produced: vt script status <id> --status produced")
        elif status == 'produced':
            click.echo("💡 Next steps:")
            click.echo("   - Publish: vt script status <id> --status published")
    else:
        click.echo("❌ Error: Failed to update status", err=True)


@script_group.command(name="export")
@click.argument('script_id')
@click.option('--format', type=click.Choice(['markdown', 'txt', 'json']), default='markdown', help='Export format')
@click.option('--output', type=click.Path(), help='Output file path')
def export_script(script_id: str, format: str, output: Optional[str]):
    """
    Export script to file.

    Examples:
        vt script export <uuid>
        vt script export <uuid> --format markdown --output script.md
        vt script export <uuid> --format json --output script.json
    """
    supabase = get_supabase_client()

    # Get script with relationships
    result = supabase.table('product_scripts').select(
        '*, products(name, slug), brands(name, slug)'
    ).eq('id', script_id).execute()

    if not result.data:
        click.echo(f"❌ Error: Script '{script_id}' not found", err=True)
        return

    script = result.data[0]

    # Generate export content based on format
    if format == 'json':
        content = json.dumps(script, indent=2)
        extension = 'json'
    elif format == 'txt':
        content = f"{script['title']}\n"
        content += "=" * len(script['title']) + "\n\n"
        content += f"Product: {script['products']['name']}\n"
        content += f"Brand: {script['brands']['name']}\n"
        content += f"Status: {script['status']}\n"
        content += f"Version: {script['version_number']}\n\n"
        content += "SCRIPT:\n"
        content += "-" * 40 + "\n\n"
        content += script['script_content']
        extension = 'txt'
    else:  # markdown
        content = f"# {script['title']}\n\n"
        content += f"**Product:** {script['products']['name']} ({script['products']['slug']})  \n"
        content += f"**Brand:** {script['brands']['name']}  \n"
        content += f"**Status:** {script['status']}  \n"
        content += f"**Version:** {script['version_number']}"
        if script['is_current_version']:
            content += " (current)"
        content += "  \n\n"

        if script.get('description'):
            content += f"**Description:** {script['description']}\n\n"

        content += "---\n\n"
        content += "## Script\n\n"
        content += script['script_content'] + "\n\n"

        if script.get('script_structure'):
            structure = script['script_structure']

            if structure.get('adaptation_ideas'):
                content += "---\n\n## Adaptation Ideas\n\n"
                for i, idea in enumerate(structure['adaptation_ideas'], 1):
                    content += f"{i}. {idea}\n"
                content += "\n"

            if structure.get('how_style_applies'):
                content += "---\n\n## How This Style Applies\n\n"
                content += structure['how_style_applies'] + "\n\n"

            if structure.get('target_audience_fit'):
                content += "---\n\n## Target Audience Fit\n\n"
                content += structure['target_audience_fit'] + "\n\n"

        if script.get('target_viral_score'):
            content += "---\n\n"
            content += f"**Target Viral Score:** {script['target_viral_score']}/10\n\n"

        content += "---\n\n"
        content += f"*Created: {script['created_at']}*  \n"
        content += f"*Updated: {script['updated_at']}*\n"

        extension = 'md'

    # Determine output path
    if not output:
        # Generate filename from script title
        filename = script['title'].lower().replace(' ', '-')
        filename = ''.join(c for c in filename if c.isalnum() or c == '-')
        output = f"{filename}.{extension}"

    # Write to file
    try:
        with open(output, 'w') as f:
            f.write(content)

        click.echo(f"✅ Script exported successfully!")
        click.echo()
        click.echo(f"   File: {output}")
        click.echo(f"   Format: {format}")
        click.echo(f"   Size: {len(content)} bytes")
    except Exception as e:
        click.echo(f"❌ Error: Failed to write file: {e}", err=True)
