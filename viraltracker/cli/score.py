"""
Score CLI Commands

Commands for scoring analyzed TikTok videos using the TypeScript scoring engine.
"""

import json
import logging
import subprocess
import csv
from pathlib import Path
from typing import Optional, Dict, List
from statistics import mean, median, stdev

import click
from tqdm import tqdm

from ..core.database import get_supabase_client
from ..scoring.data_adapter import prepare_scorer_input


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# Path to TypeScript scorer
SCORER_PATH = Path(__file__).parent.parent.parent / "scorer"


@click.group()
def score_group():
    """Score analyzed videos using the TikTok scoring engine."""
    pass


@score_group.command(name="videos")
@click.option("--project", required=True, help="Project slug (e.g., wonder-paws-tiktok)")
@click.option("--limit", type=int, help="Maximum number of videos to score")
@click.option("--rescore", is_flag=True, help="Re-score videos that already have scores")
@click.option("--verbose", is_flag=True, help="Show detailed scoring output")
def score_videos(project: str, limit: Optional[int], rescore: bool, verbose: bool):
    """
    Score analyzed videos in a project.

    Fetches video analysis data, converts to scorer input format,
    calls the TypeScript scorer, and saves results to the database.

    Example:
        vt score videos --project wonder-paws-tiktok --limit 5
    """
    supabase = get_supabase_client()

    # Get project
    click.echo(f"🔍 Looking up project: {project}")
    project_result = supabase.table("projects").select("id, name").eq("slug", project).execute()

    if not project_result.data:
        click.echo(f"❌ Project not found: {project}", err=True)
        return

    project_data = project_result.data[0]
    project_id = project_data['id']
    project_name = project_data['name']

    click.echo(f"✅ Found project: {project_name}")

    # Get analyzed videos in project
    click.echo(f"📊 Fetching analyzed videos...")

    # First get all post IDs in project
    project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
    post_ids = [row['post_id'] for row in project_posts.data]

    if not post_ids:
        click.echo(f"❌ No posts found in project", err=True)
        return

    # Get video analyses for these posts
    analyses = supabase.table("video_analysis").select("post_id").in_("post_id", post_ids).execute()
    analyzed_post_ids = [row['post_id'] for row in analyses.data]

    if not analyzed_post_ids:
        click.echo(f"❌ No analyzed videos found in project", err=True)
        return

    # Filter out already-scored unless --rescore
    if not rescore:
        scored = supabase.table("video_scores").select("post_id").in_("post_id", analyzed_post_ids).execute()
        scored_post_ids = {row['post_id'] for row in scored.data}
        to_score = [pid for pid in analyzed_post_ids if pid not in scored_post_ids]
    else:
        to_score = analyzed_post_ids

    if not to_score:
        click.echo(f"✅ All videos already scored (use --rescore to re-score)")
        return

    # Apply limit
    if limit:
        to_score = to_score[:limit]

    click.echo(f"📈 Found {len(to_score)} video(s) to score")

    # Check scorer is built
    scorer_cli = SCORER_PATH / "dist" / "cli.js"
    if not scorer_cli.exists():
        click.echo(f"❌ Scorer not built. Run: cd scorer && npm run build", err=True)
        return

    # Score each video
    results = {"completed": 0, "failed": 0, "errors": []}

    with tqdm(total=len(to_score), desc="Scoring videos") as pbar:
        for post_id in to_score:
            try:
                # Prepare scorer input
                scorer_input = prepare_scorer_input(post_id, supabase)

                if verbose:
                    click.echo(f"\n📝 Scorer input for {post_id}:")
                    click.echo(json.dumps(scorer_input, indent=2)[:500] + "...")

                # Call scorer via subprocess
                result = subprocess.run(
                    ["node", "dist/cli.js"],
                    input=json.dumps(scorer_input),
                    capture_output=True,
                    text=True,
                    cwd=SCORER_PATH
                )

                if result.returncode != 0:
                    error_msg = f"Scorer failed for {post_id}: {result.stderr}"
                    logger.error(error_msg)
                    results["errors"].append({"post_id": post_id, "error": result.stderr})
                    results["failed"] += 1
                    pbar.update(1)
                    continue

                # Parse output
                scores = json.loads(result.stdout)

                if verbose:
                    click.echo(f"✅ Score: {scores['overall']:.1f}/100")

                # Save to database
                save_scores(supabase, post_id, scores)

                results["completed"] += 1

            except Exception as e:
                error_msg = f"Error scoring {post_id}: {str(e)}"
                logger.error(error_msg)
                results["errors"].append({"post_id": post_id, "error": str(e)})
                results["failed"] += 1

            pbar.update(1)

    # Show summary
    click.echo(f"\n{'='*60}")
    click.echo(f"📊 SCORING SUMMARY")
    click.echo(f"{'='*60}")
    click.echo(f"✅ Completed: {results['completed']}")
    click.echo(f"❌ Failed: {results['failed']}")
    click.echo(f"📈 Total: {len(to_score)}")

    if results['errors'] and verbose:
        click.echo(f"\n⚠️  ERRORS:")
        for err in results['errors']:
            click.echo(f"  - {err['post_id']}: {err['error'][:100]}")

    if results['completed'] > 0:
        click.echo(f"\n✨ Scores saved to video_scores table")
        click.echo(f"💡 Query: SELECT * FROM scored_videos_full WHERE project_id = '{project_id}';")


def save_scores(supabase, post_id: str, scores: Dict) -> None:
    """
    Save scores to video_scores table.

    Args:
        supabase: Supabase client
        post_id: Post UUID
        scores: Scorer output JSON
    """
    record = {
        "post_id": post_id,
        "scorer_version": scores["version"],
        "hook_score": scores["subscores"]["hook"],
        "story_score": scores["subscores"]["story"],
        "relatability_score": scores["subscores"]["relatability"],
        "visuals_score": scores["subscores"]["visuals"],
        "audio_score": scores["subscores"]["audio"],
        "watchtime_score": scores["subscores"]["watchtime"],
        "engagement_score": scores["subscores"]["engagement"],
        "shareability_score": scores["subscores"]["shareability"],
        "algo_score": scores["subscores"]["algo"],
        "penalties_score": scores["penalties"],
        "overall_score": scores["overall"],
        "score_details": scores  # Full JSON for reference
    }

    # Upsert (insert or update if exists)
    supabase.table("video_scores").upsert(
        record,
        on_conflict="post_id,scorer_version"
    ).execute()

    logger.info(f"Saved scores for {post_id}: {scores['overall']:.1f}/100")


@score_group.command(name="show")
@click.argument("post_id")
def show_score(post_id: str):
    """
    Show detailed scoring breakdown for a video.

    Args:
        post_id: Post UUID
    """
    supabase = get_supabase_client()

    # Get score
    result = supabase.table("video_scores").select("*").eq("post_id", post_id).execute()

    if not result.data:
        click.echo(f"❌ No score found for post: {post_id}", err=True)
        return

    score = result.data[0]

    # Get post details
    post_result = supabase.table("posts").select(
        "post_url, caption, views, accounts(platform_username)"
    ).eq("id", post_id).execute()

    post = post_result.data[0] if post_result.data else {}

    # Display
    click.echo(f"\n{'='*60}")
    click.echo(f"📊 VIDEO SCORE BREAKDOWN")
    click.echo(f"{'='*60}\n")

    if post:
        username = post.get('accounts', {}).get('platform_username', 'unknown')
        click.echo(f"@{username}")
        click.echo(f"URL: {post.get('post_url', 'N/A')}")
        click.echo(f"Views: {post.get('views', 0):,}")
        click.echo(f"Caption: {post.get('caption', '')[:100]}...")
        click.echo()

    click.echo(f"OVERALL SCORE: {score['overall_score']:.1f}/100")
    click.echo(f"Version: {score['scorer_version']}")
    click.echo(f"Scored: {score['scored_at']}")
    click.echo()

    click.echo("SUBSCORES:")
    click.echo("-" * 60)
    click.echo(f"  Hook:         {score['hook_score']:.1f}/100")
    click.echo(f"  Story:        {score['story_score']:.1f}/100")
    click.echo(f"  Relatability: {score['relatability_score']:.1f}/100")
    click.echo(f"  Visuals:      {score['visuals_score']:.1f}/100")
    click.echo(f"  Audio:        {score['audio_score']:.1f}/100")
    click.echo(f"  Watchtime:    {score['watchtime_score']:.1f}/100")
    click.echo(f"  Engagement:   {score['engagement_score']:.1f}/100")
    click.echo(f"  Shareability: {score['shareability_score']:.1f}/100")
    click.echo(f"  Algorithm:    {score['algo_score']:.1f}/100")
    click.echo()

    if score.get('penalties_score', 0) > 0:
        click.echo(f"⚠️  PENALTIES: -{score['penalties_score']:.1f}")
        click.echo()

    # Show diagnostics if available
    details = score.get('score_details', {})
    if details.get('diagnostics'):
        diagnostics = details['diagnostics']
        click.echo("DIAGNOSTICS:")
        click.echo("-" * 60)
        click.echo(f"  Confidence: {diagnostics.get('overall_confidence', 1.0):.0%}")
        if diagnostics.get('missing'):
            click.echo(f"  Missing data: {', '.join(diagnostics['missing'])}")


@score_group.command(name="export")
@click.option("--project", required=True, help="Project slug")
@click.option("--output", default="scores.csv", help="Output CSV file path")
def export_scores(project: str, output: str):
    """
    Export scores to CSV file.

    Example:
        vt score export --project wonder-paws-tiktok --output scores.csv
    """
    supabase = get_supabase_client()

    # Get project
    project_result = supabase.table("projects").select("id, name").eq("slug", project).execute()

    if not project_result.data:
        click.echo(f"❌ Project not found: {project}", err=True)
        return

    project_data = project_result.data[0]
    project_id = project_data['id']

    click.echo(f"📊 Exporting scores for: {project_data['name']}")

    # Get all scored videos with post details
    project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
    post_ids = [row['post_id'] for row in project_posts.data]

    # Get scores with post details
    scores = supabase.table("video_scores").select(
        "*, posts(post_url, caption, views, likes, comments, accounts(platform_username))"
    ).in_("post_id", post_ids).execute()

    if not scores.data:
        click.echo(f"❌ No scores found", err=True)
        return

    # Write CSV
    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'post_id', 'username', 'url', 'views', 'likes', 'comments',
            'caption', 'overall_score', 'hook_score', 'story_score',
            'relatability_score', 'visuals_score', 'audio_score',
            'watchtime_score', 'engagement_score', 'shareability_score',
            'algo_score', 'penalties_score', 'scored_at'
        ])

        writer.writeheader()

        for score in scores.data:
            post = score.get('posts', {})
            account = post.get('accounts', {})

            writer.writerow({
                'post_id': score['post_id'],
                'username': account.get('platform_username', 'N/A'),
                'url': post.get('post_url', 'N/A'),
                'views': post.get('views', 0),
                'likes': post.get('likes', 0),
                'comments': post.get('comments', 0),
                'caption': (post.get('caption', '') or '')[:200],  # Truncate for CSV
                'overall_score': score['overall_score'],
                'hook_score': score['hook_score'],
                'story_score': score['story_score'],
                'relatability_score': score['relatability_score'],
                'visuals_score': score['visuals_score'],
                'audio_score': score['audio_score'],
                'watchtime_score': score['watchtime_score'],
                'engagement_score': score['engagement_score'],
                'shareability_score': score['shareability_score'],
                'algo_score': score['algo_score'],
                'penalties_score': score['penalties_score'],
                'scored_at': score['scored_at']
            })

    click.echo(f"✅ Exported {len(scores.data)} scores to {output}")


@score_group.command(name="analyze")
@click.option("--project", required=True, help="Project slug")
def analyze_scores(project: str):
    """
    Analyze score distribution and patterns.

    Example:
        vt score analyze --project wonder-paws-tiktok
    """
    supabase = get_supabase_client()

    # Get project
    project_result = supabase.table("projects").select("id, name").eq("slug", project).execute()

    if not project_result.data:
        click.echo(f"❌ Project not found: {project}", err=True)
        return

    project_data = project_result.data[0]
    project_id = project_data['id']

    # Get all scored videos with post details
    project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
    post_ids = [row['post_id'] for row in project_posts.data]

    scores = supabase.table("video_scores").select(
        "*, posts(post_url, caption, views, accounts(platform_username))"
    ).in_("post_id", post_ids).execute()

    if not scores.data or len(scores.data) == 0:
        click.echo(f"❌ No scores found", err=True)
        return

    data = scores.data

    # Calculate statistics
    overall_scores = [s['overall_score'] for s in data]
    hook_scores = [s['hook_score'] for s in data]
    story_scores = [s['story_score'] for s in data]
    relatability_scores = [s['relatability_score'] for s in data]
    visuals_scores = [s['visuals_score'] for s in data]
    audio_scores = [s['audio_score'] for s in data]
    watchtime_scores = [s['watchtime_score'] for s in data]
    engagement_scores = [s['engagement_score'] for s in data]
    shareability_scores = [s['shareability_score'] for s in data]
    algo_scores = [s['algo_score'] for s in data]

    click.echo(f"\n{'='*60}")
    click.echo(f"📊 SCORE ANALYSIS: {project_data['name']}")
    click.echo(f"{'='*60}\n")

    click.echo(f"Sample Size: {len(data)} videos\n")

    # Overall statistics
    click.echo("OVERALL SCORES")
    click.echo("-" * 60)
    click.echo(f"  Mean:     {mean(overall_scores):.1f}")
    click.echo(f"  Median:   {median(overall_scores):.1f}")
    click.echo(f"  Std Dev:  {stdev(overall_scores):.1f}" if len(overall_scores) > 1 else "  Std Dev:  N/A")
    click.echo(f"  Min:      {min(overall_scores):.1f}")
    click.echo(f"  Max:      {max(overall_scores):.1f}")
    click.echo()

    # Subscore averages
    click.echo("SUBSCORE AVERAGES")
    click.echo("-" * 60)
    click.echo(f"  Hook:         {mean(hook_scores):.1f}")
    click.echo(f"  Story:        {mean(story_scores):.1f}")
    click.echo(f"  Relatability: {mean(relatability_scores):.1f}")
    click.echo(f"  Visuals:      {mean(visuals_scores):.1f}")
    click.echo(f"  Audio:        {mean(audio_scores):.1f}")
    click.echo(f"  Watchtime:    {mean(watchtime_scores):.1f}")
    click.echo(f"  Engagement:   {mean(engagement_scores):.1f}")
    click.echo(f"  Shareability: {mean(shareability_scores):.1f}")
    click.echo(f"  Algorithm:    {mean(algo_scores):.1f}")
    click.echo()

    # Top performers
    click.echo("TOP 5 HIGHEST SCORING VIDEOS")
    click.echo("-" * 60)
    top_5 = sorted(data, key=lambda x: x['overall_score'], reverse=True)[:5]
    for i, score in enumerate(top_5, 1):
        post = score.get('posts', {})
        username = post.get('accounts', {}).get('platform_username', 'N/A')
        views = post.get('views', 0)
        click.echo(f"  {i}. {score['overall_score']:.1f} - @{username} ({views:,} views)")

    click.echo()

    # Bottom performers
    click.echo("LOWEST 5 SCORING VIDEOS")
    click.echo("-" * 60)
    bottom_5 = sorted(data, key=lambda x: x['overall_score'])[:5]
    for i, score in enumerate(bottom_5, 1):
        post = score.get('posts', {})
        username = post.get('accounts', {}).get('platform_username', 'N/A')
        views = post.get('views', 0)
        click.echo(f"  {i}. {score['overall_score']:.1f} - @{username} ({views:,} views)")

    click.echo()

    # Score distribution
    click.echo("SCORE DISTRIBUTION")
    click.echo("-" * 60)
    ranges = {
        '90-100': [s for s in overall_scores if s >= 90],
        '80-89': [s for s in overall_scores if 80 <= s < 90],
        '70-79': [s for s in overall_scores if 70 <= s < 80],
        '60-69': [s for s in overall_scores if 60 <= s < 70],
        '0-59': [s for s in overall_scores if s < 60],
    }

    for range_label, range_scores in ranges.items():
        count = len(range_scores)
        pct = (count / len(overall_scores)) * 100 if overall_scores else 0
        bar = '█' * int(pct / 5)  # Each █ = 5%
        click.echo(f"  {range_label}: {count:2d} ({pct:5.1f}%) {bar}")

    click.echo()


# Register commands
score = score_group
