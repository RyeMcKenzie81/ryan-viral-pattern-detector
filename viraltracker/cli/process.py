"""
Video Processing CLI Commands

Commands for downloading and processing videos.
"""

import logging
from typing import Optional

import click
from tqdm import tqdm

from ..core.database import get_supabase_client
from ..utils.video_downloader import VideoDownloader


logger = logging.getLogger(__name__)


@click.group(name="process")
def process_group():
    """Download and process videos"""
    pass


@process_group.command(name="videos")
@click.option('--project', required=True, help='Project slug or ID')
@click.option('--unprocessed-outliers', is_flag=True, help='Only process unprocessed outliers')
@click.option('--limit', type=int, help='Maximum number of videos to process')
@click.option('--storage-bucket', default='videos', help='Supabase storage bucket')
def process_videos(project: str, unprocessed_outliers: bool, limit: Optional[int], storage_bucket: str):
    """
    Download videos for a project.

    Examples:
        vt process videos --project yakety-pack-instagram --unprocessed-outliers
        vt process videos --project yakety-pack-instagram --limit 10
    """
    click.echo("=" * 60)
    click.echo("🎬 Video Processor")
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
    project_slug = project_data['slug']
    project_name = project_data['name']

    click.echo(f"Project: {project_name}")
    click.echo(f"Mode: {'Unprocessed outliers only' if unprocessed_outliers else 'All unprocessed'}")
    if limit:
        click.echo(f"Limit: {limit} videos")
    click.echo()

    # Initialize downloader
    downloader = VideoDownloader(supabase, storage_bucket=storage_bucket)

    # Get posts to process
    if unprocessed_outliers:
        # Get outliers without video processing
        posts_query = """
            SELECT p.id, p.post_url, p.post_id, p.caption, p.views
            FROM posts p
            INNER JOIN project_posts pp ON p.id = pp.post_id
            INNER JOIN post_review pr ON p.id = pr.post_id
            WHERE pp.project_id = :project_id
                AND pr.outlier = true
                AND p.id NOT IN (
                    SELECT post_id FROM video_processing_log WHERE status = 'completed'
                )
        """
        # Use RPC or direct query - for now, use simpler approach
        # Get all project posts
        project_posts_result = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
        project_post_ids = [row["post_id"] for row in project_posts_result.data]

        # Get outliers from post_review
        outliers_result = supabase.table("post_review").select("post_id").eq("outlier", True).execute()
        outlier_post_ids = {row["post_id"] for row in outliers_result.data}

        # Get processed post IDs
        processed_result = supabase.table("video_processing_log").select("post_id").eq("status", "completed").execute()
        processed_post_ids = {row["post_id"] for row in processed_result.data}

        # Filter to get unprocessed outliers in this project
        target_post_ids = [
            pid for pid in project_post_ids
            if pid in outlier_post_ids and pid not in processed_post_ids
        ]

        if not target_post_ids:
            click.echo("✅ No unprocessed outliers found")
            return

        # Get post details
        posts_result = supabase.table("posts").select("id, post_url, post_id, caption, views").in_("id", target_post_ids).execute()
        posts = posts_result.data

    else:
        # Get all unprocessed posts for this project
        project_posts_result = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
        project_post_ids = [row["post_id"] for row in project_posts_result.data]

        # Get processed post IDs
        processed_result = supabase.table("video_processing_log").select("post_id").eq("status", "completed").execute()
        processed_post_ids = {row["post_id"] for row in processed_result.data}

        # Filter to unprocessed
        target_post_ids = [pid for pid in project_post_ids if pid not in processed_post_ids]

        if not target_post_ids:
            click.echo("✅ No unprocessed posts found")
            return

        # Get post details
        posts_result = supabase.table("posts").select("id, post_url, post_id, caption, views").in_("id", target_post_ids).execute()
        posts = posts_result.data

    # Apply limit
    if limit:
        posts = posts[:limit]

    click.echo(f"Found {len(posts)} posts to process\n")

    # Process posts
    results = {"completed": 0, "failed": 0}

    for post in tqdm(posts, desc="Downloading videos"):
        try:
            result = downloader.process_post(
                post_url=post['post_url'],
                post_db_id=post['id'],
                project_slug=project_slug,
                post_id=post['post_id']
            )

            if result['status'] == 'completed':
                results['completed'] += 1
            else:
                results['failed'] += 1
                logger.warning(f"Failed to process {post['post_url']}: {result.get('error')}")

        except Exception as e:
            results['failed'] += 1
            logger.error(f"Error processing {post.get('post_url', 'unknown')}: {e}")

    # Clean up temp files
    downloader.cleanup_temp_files()

    # Summary
    click.echo()
    click.echo("=" * 60)
    click.echo("✅ Processing Complete!")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"📊 Summary:")
    click.echo(f"   Total posts: {len(posts)}")
    click.echo(f"   Successfully processed: {results['completed']}")
    click.echo(f"   Failed: {results['failed']}")
    click.echo()

    if results['completed'] > 0:
        click.echo("💡 Next steps:")
        click.echo(f"   - Analyze videos: vt analyze videos --project {project_slug} --product <product-slug>")
