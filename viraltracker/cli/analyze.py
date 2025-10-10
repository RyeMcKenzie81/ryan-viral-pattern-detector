"""
Video Analysis CLI Commands

Commands for analyzing videos with Gemini AI.
"""

import logging
from typing import Optional

import click

from ..core.database import get_supabase_client
from ..core.config import Config
from ..analysis.video_analyzer import VideoAnalyzer


logger = logging.getLogger(__name__)


@click.group(name="analyze")
def analyze_group():
    """Analyze videos with AI"""
    pass


@analyze_group.command(name="videos")
@click.option('--project', required=True, help='Project slug or ID')
@click.option('--product', help='Product slug or ID for adaptations (optional)')
@click.option('--limit', type=int, help='Maximum number of videos to analyze')
@click.option('--gemini-model', default=Config.GEMINI_VIDEO_MODEL, help='Gemini model to use (default: Gemini 2.5 Pro)')
def analyze_videos(project: str, product: Optional[str], limit: Optional[int], gemini_model: str):
    """
    Analyze videos using Gemini AI.

    Examples:
        vt analyze videos --project yakety-pack-instagram --product core-deck
        vt analyze videos --project yakety-pack-instagram --limit 5
        vt analyze videos --project yakety-pack-instagram --product core-deck --gemini-model models/gemini-1.5-pro-latest
    """
    click.echo("=" * 60)
    click.echo("🤖 Video Analyzer (Gemini AI)")
    click.echo("=" * 60)
    click.echo()

    supabase = get_supabase_client()

    # Get project (try slug first, then UUID)
    project_result = supabase.table("projects").select("id, name, slug").eq("slug", project).execute()
    if not project_result.data:
        try:
            project_result = supabase.table("projects").select("id, name, slug").eq("id", project).execute()
        except:
            pass

    if not project_result.data:
        click.echo(f"❌ Error: Project '{project}' not found", err=True)
        return

    project_data = project_result.data[0]
    project_id = project_data['id']
    project_name = project_data['name']

    click.echo(f"Project: {project_name}")
    click.echo(f"Model: {gemini_model}")

    # Get product if specified
    product_id = None
    product_name = None

    if product:
        product_result = supabase.table("products").select("id, name, slug").eq("slug", product).execute()
        if not product_result.data:
            try:
                product_result = supabase.table("products").select("id, name, slug").eq("id", product).execute()
            except:
                pass

        if not product_result.data:
            click.echo(f"❌ Error: Product '{product}' not found", err=True)
            return

        product_data = product_result.data[0]
        product_id = product_data['id']
        product_name = product_data['name']

        click.echo(f"Product: {product_name} (adaptations will be generated)")
    else:
        click.echo("Product: None (no adaptations will be generated)")

    if limit:
        click.echo(f"Limit: {limit} videos")

    click.echo()

    # Initialize analyzer
    try:
        analyzer = VideoAnalyzer(supabase, gemini_model=gemini_model)
    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        click.echo("\n💡 Make sure GEMINI_API_KEY is set in your environment")
        return

    # Get unanalyzed videos for this project
    videos = analyzer.get_unanalyzed_videos(project_id=project_id, limit=limit)

    if not videos:
        click.echo("✅ No unanalyzed videos found")
        click.echo("\n💡 Process videos first:")
        click.echo(f"   vt process videos --project {project_data['slug']}")
        return

    click.echo(f"Found {len(videos)} videos to analyze")
    click.echo()

    # Confirm before proceeding (Gemini costs money)
    if not click.confirm(f"⚠️  This will use Gemini API credits. Analyze {len(videos)} videos?"):
        click.echo("Cancelled")
        return

    click.echo()

    # Process videos
    results = analyzer.process_batch(
        project_id=project_id,
        product_id=product_id,
        limit=limit,
        show_progress=True
    )

    # Summary
    click.echo()
    click.echo("=" * 60)
    click.echo("✅ Analysis Complete!")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"📊 Summary:")
    click.echo(f"   Total videos: {results['total']}")
    click.echo(f"   Successfully analyzed: {results['completed']}")
    click.echo(f"   Failed: {results['failed']}")
    click.echo()

    if results['completed'] > 0:
        click.echo("💡 Next steps:")
        click.echo("   - View analysis: Query video_analysis table in Supabase")
        if product_id:
            click.echo("   - Review adaptations: Check product_adaptation field")


@analyze_group.command(name="outliers")
@click.option('--project', required=True, help='Project slug or ID')
@click.option('--sd-threshold', default=3.0, type=float, help='Standard deviation threshold')
def analyze_outliers(project: str, sd_threshold: float):
    """
    Compute statistical outliers for a project.

    This performs the statistical analysis to identify viral posts
    based on view counts relative to each account's baseline.

    Examples:
        vt analyze outliers --project yakety-pack-instagram
        vt analyze outliers --project yakety-pack-instagram --sd-threshold 2.5
    """
    click.echo("=" * 60)
    click.echo("📊 Statistical Outlier Analysis")
    click.echo("=" * 60)
    click.echo()

    supabase = get_supabase_client()

    # Get project (try slug first, then UUID)
    project_result = supabase.table("projects").select("id, name, slug").eq("slug", project).execute()
    if not project_result.data:
        try:
            project_result = supabase.table("projects").select("id, name, slug").eq("id", project).execute()
        except:
            pass

    if not project_result.data:
        click.echo(f"❌ Error: Project '{project}' not found", err=True)
        return

    project_data = project_result.data[0]
    project_id = project_data['id']
    project_name = project_data['name']

    click.echo(f"Project: {project_name}")
    click.echo(f"SD Threshold: {sd_threshold}")
    click.echo()

    # Get posts for this project
    click.echo("Fetching project posts...")
    project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
    post_ids = [row["post_id"] for row in project_posts.data]

    if not post_ids:
        click.echo("❌ No posts found for this project")
        return

    # Get posts with account IDs (batch to avoid URL too long error)
    posts = []
    batch_size = 100

    for i in range(0, len(post_ids), batch_size):
        batch = post_ids[i:i + batch_size]
        batch_result = supabase.table("posts").select("id, account_id, views").in_("id", batch).gt("views", 0).execute()
        posts.extend(batch_result.data)

    click.echo(f"Found {len(posts)} posts with views > 0")
    click.echo()

    # Group by account
    import pandas as pd
    df = pd.DataFrame(posts)

    if len(df) == 0:
        click.echo("❌ No posts with views found")
        return

    # Compute summaries per account
    click.echo("Computing account summaries...")
    summaries = []

    for account_id in df['account_id'].unique():
        account_posts = df[df['account_id'] == account_id]['views']

        if len(account_posts) < 3:
            continue

        # Calculate percentiles
        p10 = float(account_posts.quantile(0.1))
        p90 = float(account_posts.quantile(0.9))

        # Trim data
        trimmed_views = account_posts[(account_posts >= p10) & (account_posts <= p90)]

        if len(trimmed_views) < 2:
            continue

        # Calculate trimmed statistics
        trimmed_mean = float(trimmed_views.mean())
        trimmed_sd = float(trimmed_views.std(ddof=0))

        summaries.append({
            "account_id": account_id,
            "n_posts": len(account_posts),
            "p10_views": p10,
            "p90_views": p90,
            "trimmed_mean_views": trimmed_mean,
            "trimmed_sd_views": trimmed_sd
        })

    if summaries:
        supabase.table("account_summaries").upsert(summaries, on_conflict="account_id").execute()
        click.echo(f"✅ Computed summaries for {len(summaries)} accounts")
    else:
        click.echo("❌ Not enough data to compute summaries")
        return

    # Flag outliers
    click.echo()
    click.echo(f"Flagging outliers (threshold: {sd_threshold} SD)...")

    summaries_map = {s["account_id"]: s for s in summaries}
    outlier_posts = []

    for post in posts:
        account_id = post["account_id"]
        views = post["views"]

        if account_id not in summaries_map:
            continue

        summary = summaries_map[account_id]
        mean_views = float(summary["trimmed_mean_views"])
        sd_views = float(summary["trimmed_sd_views"])

        if sd_views <= 0:
            continue

        # Calculate outlier threshold
        outlier_threshold = mean_views + (sd_threshold * sd_views)
        is_outlier = views > outlier_threshold

        if is_outlier:
            outlier_posts.append(post["id"])

    if outlier_posts:
        # Update post_review table
        click.echo(f"Marking {len(outlier_posts)} posts as outliers...")

        for post_id in outlier_posts:
            supabase.table("post_review").upsert({
                "post_id": post_id,
                "outlier": True
            }, on_conflict="post_id").execute()

        click.echo(f"✅ Flagged {len(outlier_posts)} outliers")
    else:
        click.echo("✅ No outliers found")

    # Summary
    click.echo()
    click.echo("=" * 60)
    click.echo("✅ Analysis Complete!")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"📊 Summary:")
    click.echo(f"   Total posts analyzed: {len(posts)}")
    click.echo(f"   Accounts with summaries: {len(summaries)}")
    click.echo(f"   Outliers flagged: {len(outlier_posts)}")
    click.echo()

    if outlier_posts:
        click.echo("💡 Next steps:")
        click.echo(f"   - Download videos: vt process videos --project {project_data['slug']} --unprocessed-outliers")
