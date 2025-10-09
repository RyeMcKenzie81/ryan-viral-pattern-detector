"""
Score CLI Commands

Commands for scoring analyzed TikTok videos using the TypeScript scoring engine.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

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


# Register commands
score = score_group
