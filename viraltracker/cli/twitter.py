"""
Twitter CLI Commands

Commands for scraping and analyzing Twitter content.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import click

from ..scrapers.twitter import TwitterScraper
from ..core.database import get_supabase_client
from ..core.config import load_finder_config
from ..core.embeddings import Embedder
from ..generation.tweet_fetcher import fetch_recent_tweets
from ..generation.comment_finder import score_tweet
from ..generation.comment_generator import CommentGenerator, save_suggestions_to_db


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# Rate limit tracking
RATE_LIMIT_FILE = Path.home() / ".viraltracker" / "twitter_last_run.txt"
RATE_LIMIT_SECONDS = 120  # 2 minutes between searches


def check_rate_limit():
    """
    Check if user is exceeding Twitter search rate limits

    Returns:
        (can_proceed, seconds_to_wait, last_run_time)
    """
    if not RATE_LIMIT_FILE.parent.exists():
        RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not RATE_LIMIT_FILE.exists():
        return (True, 0, None)

    try:
        with open(RATE_LIMIT_FILE, 'r') as f:
            last_run = float(f.read().strip())

        elapsed = time.time() - last_run

        if elapsed < RATE_LIMIT_SECONDS:
            seconds_to_wait = int(RATE_LIMIT_SECONDS - elapsed)
            return (False, seconds_to_wait, last_run)
        else:
            return (True, 0, last_run)
    except:
        return (True, 0, None)


def update_rate_limit():
    """Update last run timestamp"""
    if not RATE_LIMIT_FILE.parent.exists():
        RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(RATE_LIMIT_FILE, 'w') as f:
        f.write(str(time.time()))


@click.group(name="twitter")
def twitter_group():
    """Twitter scraping and analysis"""
    pass


@twitter_group.command(name="search")
@click.option('--terms', required=True, help='Search terms or raw query (e.g., "dog training" or "from:NASA filter:video")')
@click.option('--count', default=100, type=int, help='Max tweets to scrape (min 50, default: 100)')
@click.option('--min-likes', type=int, help='Minimum like count filter (optional)')
@click.option('--min-retweets', type=int, help='Minimum retweet count filter (optional)')
@click.option('--min-replies', type=int, help='Minimum reply count filter (optional)')
@click.option('--min-quotes', type=int, help='Minimum quote tweet count filter (optional)')
@click.option('--days-back', type=int, help='Only tweets from last N days (optional)')
@click.option('--only-video', is_flag=True, help='Only tweets with videos')
@click.option('--only-image', is_flag=True, help='Only tweets with images')
@click.option('--only-quote', is_flag=True, help='Only quote tweets')
@click.option('--only-verified', is_flag=True, help='Only verified accounts')
@click.option('--only-blue', is_flag=True, help='Only Twitter Blue accounts')
@click.option('--raw-query', is_flag=True, help='Use raw Twitter search syntax (advanced)')
@click.option('--sort', default='Latest', type=click.Choice(['Latest', 'Top']), help='Sort by (default: Latest)')
@click.option('--language', default='en', help='Language code (default: en)')
@click.option('--project', '-p', help='Project slug to link results to (optional)')
def twitter_search(
    terms: str,
    count: int,
    min_likes: Optional[int],
    min_retweets: Optional[int],
    min_replies: Optional[int],
    min_quotes: Optional[int],
    days_back: Optional[int],
    only_video: bool,
    only_image: bool,
    only_quote: bool,
    only_verified: bool,
    only_blue: bool,
    raw_query: bool,
    sort: str,
    language: str,
    project: Optional[str]
):
    """
    Search Twitter for tweets by keyword or raw query

    Enables keyword/hashtag discovery for Twitter content. Supports various
    filters including engagement metrics, content types, and account verification.

    Constraints:
        - Minimum 50 tweets per search (Apify actor requirement)
        - Max 5 search terms per batch (Apify actor limitation)

    Examples:
        # Basic search
        vt twitter search --terms "dog training" --count 100

        # With engagement filters
        vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7

        # Content filters (single or combined)
        vt twitter search --terms "puppy" --count 100 --only-video
        vt twitter search --terms "pets" --count 200 --only-video --only-image

        # Raw Twitter query syntax (advanced)
        vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query

        # Multiple search terms (batch search, max 5 queries)
        vt twitter search --terms "puppy,kitten,bunny" --count 100

        # Link to project
        vt twitter search --terms "golden retriever" --count 100 --project my-twitter-project
    """
    try:
        # Validate minimum count (Apify actor requirement)
        if count < 50:
            click.echo("\n❌ Error: Twitter search requires minimum 50 tweets", err=True)
            click.echo("   This is an Apify actor limitation", err=True)
            click.echo("\n💡 Try: --count 50 or higher\n", err=True)
            raise click.Abort()

        # Check rate limit
        can_proceed, seconds_to_wait, last_run = check_rate_limit()

        if not can_proceed:
            click.echo(f"\n⚠️  Rate Limit Warning", err=True)
            click.echo(f"   Last Twitter search was {RATE_LIMIT_SECONDS - seconds_to_wait}s ago", err=True)
            click.echo(f"   Recommended wait: {seconds_to_wait}s", err=True)
            click.echo(f"\n💡 Why? Apify actor limits:", err=True)
            click.echo(f"   - Only 1 concurrent run allowed", err=True)
            click.echo(f"   - Wait 2+ minutes between searches", err=True)
            click.echo(f"   - Prevents actor auto-ban\n", err=True)

            if click.confirm("Continue anyway?", default=False):
                click.echo("⚠️  Proceeding at your own risk...\n")
            else:
                click.echo(f"⏰ Please wait {seconds_to_wait}s and try again")
                raise click.Abort()

        # Parse search terms (for batching)
        search_terms = [t.strip() for t in terms.split(',')]

        # Validate batch size (max 5 queries)
        if len(search_terms) > 5:
            click.echo(f"\n❌ Error: Maximum 5 search terms allowed (you provided {len(search_terms)})", err=True)
            click.echo("   This is an Apify actor limitation", err=True)
            click.echo("\n💡 Try: Split into multiple searches\n", err=True)
            raise click.Abort()

        click.echo(f"\n{'='*60}")
        click.echo(f"🐦 Twitter Search")
        click.echo(f"{'='*60}\n")

        if raw_query:
            click.echo(f"Raw query: {terms}")
        else:
            click.echo(f"Search terms: {', '.join(search_terms)}")

        click.echo(f"Count: {count} tweets")

        # Display filters if any are set
        filters = []
        if min_likes:
            filters.append(f"{min_likes:,}+ likes")
        if min_retweets:
            filters.append(f"{min_retweets:,}+ retweets")
        if min_replies:
            filters.append(f"{min_replies:,}+ replies")
        if min_quotes:
            filters.append(f"{min_quotes:,}+ quotes")
        if days_back:
            filters.append(f"Last {days_back} days")
        if only_video:
            filters.append("Videos only")
        if only_image:
            filters.append("Images only")
        if only_quote:
            filters.append("Quote tweets only")
        if only_verified:
            filters.append("Verified accounts only")
        if only_blue:
            filters.append("Twitter Blue only")

        if filters:
            click.echo(f"Filters:")
            for f in filters:
                click.echo(f"  - {f}")

        click.echo(f"Sort by: {sort}")
        click.echo(f"Language: {language}")

        if project:
            click.echo(f"Project: {project}")

        if len(search_terms) > 1:
            click.echo(f"\n⚡ Batch mode: {len(search_terms)} queries in one actor run")

        click.echo()

        # Initialize scraper
        scraper = TwitterScraper()

        # Search
        click.echo("🔄 Starting Twitter search...")
        click.echo("   Note: This may take a couple minutes (Apify actor execution)")
        click.echo()

        terms_count, tweets_count = scraper.scrape_search(
            search_terms=search_terms,
            max_tweets=count,
            min_likes=min_likes,
            min_retweets=min_retweets,
            min_replies=min_replies,
            min_quotes=min_quotes,
            days_back=days_back,
            only_video=only_video,
            only_image=only_image,
            only_quote=only_quote,
            only_verified=only_verified,
            only_blue=only_blue,
            raw_query=raw_query,
            sort=sort,
            language=language,
            project_slug=project
        )

        # Update rate limit tracker
        update_rate_limit()

        # Display results
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Search Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Results:")
        click.echo(f"   Search terms: {terms_count}")
        click.echo(f"   Tweets scraped: {tweets_count}")

        if tweets_count == 0:
            click.echo("\n⚠️  No tweets found")
            click.echo("\n💡 Try:")
            click.echo("   - Lowering filters (--min-likes, --min-retweets)")
            click.echo("   - Expanding time range (--days-back)")
            click.echo("   - Different search terms")
        else:
            click.echo(f"\n✅ Saved {tweets_count} tweets to database")

            if project:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Score tweets: vt score --project {project}")
                click.echo(f"   - Analyze hooks: vt analyze hooks --project {project}")
            else:
                click.echo(f"\n💡 Next steps:")
                click.echo(f"   - Link to project: Use --project flag to organize results")
                click.echo(f"   - Or create project: vt project create")

        # Important notes
        click.echo(f"\n⚠️  Rate Limit Reminder:")
        click.echo(f"   - Wait 2 minutes before next search (automatically tracked)")
        click.echo(f"   - Only one Twitter search can run at a time")
        click.echo(f"   - Rate limit tracking: ~/.viraltracker/twitter_last_run.txt")

        click.echo(f"\n{'='*60}\n")

    except click.Abort:
        raise
    except Exception as e:
        click.echo(f"\n❌ Search failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


@twitter_group.command(name="generate-comments")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--hours-back', default=6, type=int, help='Look back N hours for tweets (default: 6)')
@click.option('--min-followers', default=1000, type=int, help='Minimum author followers (default: 1000)')
@click.option('--min-likes', default=0, type=int, help='Minimum tweet likes (default: 0)')
@click.option('--max-candidates', default=150, type=int, help='Max tweets to process (default: 150)')
@click.option('--use-gate', is_flag=True, default=True, help='Apply gate filtering (default: True)')
@click.option('--skip-low-scores', is_flag=True, default=True, help='Only generate for green/yellow (default: True)')
def generate_comments(
    project: str,
    hours_back: int,
    min_followers: int,
    min_likes: int,
    max_candidates: int,
    use_gate: bool,
    skip_low_scores: bool
):
    """
    Generate AI comment suggestions for recent tweets

    Scores fresh tweets and generates 3 reply suggestions for each:
    - add_value: Share insights or tips
    - ask_question: Ask thoughtful follow-ups
    - mirror_reframe: Acknowledge and reframe

    Examples:
        # Generate for last 6 hours
        vt twitter generate-comments --project my-project

        # Last 12 hours, min 5K followers
        vt twitter generate-comments -p my-project --hours-back 12 --min-followers 5000

        # Process all tweets (no gate)
        vt twitter generate-comments -p my-project --no-use-gate --no-skip-low-scores
    """
    try:
        click.echo(f"\n{'='*60}")
        click.echo(f"💬 Comment Opportunity Finder")
        click.echo(f"{'='*60}\n")

        click.echo(f"Project: {project}")
        click.echo(f"Time window: last {hours_back} hours")
        click.echo(f"Filters: {min_followers:,}+ followers, {min_likes:,}+ likes")
        click.echo(f"Max candidates: {max_candidates}")
        click.echo(f"Gate filtering: {'enabled' if use_gate else 'disabled'}")
        click.echo(f"Skip low scores: {'yes (green/yellow only)' if skip_low_scores else 'no (all)'}")
        click.echo()

        # Load config
        click.echo("📋 Loading finder config...")
        try:
            config = load_finder_config(project)
            click.echo(f"   ✓ Loaded config for '{project}'")
            click.echo(f"   - Taxonomy nodes: {len(config.taxonomy)}")
            click.echo(f"   - Voice: {config.voice.persona}")
        except FileNotFoundError:
            click.echo(f"\n❌ Error: No finder.yml found for project '{project}'", err=True)
            click.echo(f"   Create: projects/{project}/finder.yml", err=True)
            raise click.Abort()

        # Initialize embedder
        click.echo("\n🔢 Initializing embeddings...")
        embedder = Embedder()
        click.echo("   ✓ Embedder ready")

        # Compute taxonomy embeddings (with caching)
        click.echo(f"\n🏷️  Computing taxonomy embeddings...")
        from viraltracker.core.embeddings import load_taxonomy_embeddings, cache_taxonomy_embeddings

        # Try to load from cache
        taxonomy_embeddings = load_taxonomy_embeddings(project)

        if taxonomy_embeddings:
            click.echo(f"   ✓ Loaded {len(taxonomy_embeddings)} taxonomy embeddings from cache")
        else:
            click.echo(f"   Computing embeddings for {len(config.taxonomy)} taxonomy nodes...")
            taxonomy_embeddings = {}

            for node in config.taxonomy:
                # Embed description + exemplars
                texts_to_embed = [node.description] + node.exemplars[:3]
                combined_text = " ".join(texts_to_embed)

                embedding = embedder.embed_text(combined_text, task_type="RETRIEVAL_DOCUMENT")
                taxonomy_embeddings[node.label] = embedding

            # Cache for future runs
            cache_taxonomy_embeddings(project, taxonomy_embeddings)
            click.echo(f"   ✓ Computed and cached {len(taxonomy_embeddings)} embeddings")

        # Fetch recent tweets
        click.echo(f"\n🔍 Fetching recent tweets...")
        tweets = fetch_recent_tweets(
            project_slug=project,
            hours_back=hours_back,
            min_followers=min_followers,
            min_likes=min_likes,
            max_candidates=max_candidates,
            require_english=True
        )

        if not tweets:
            click.echo(f"\n⚠️  No tweets found matching criteria")
            click.echo(f"\n💡 Try:")
            click.echo(f"   - Increasing --hours-back")
            click.echo(f"   - Lowering --min-followers or --min-likes")
            click.echo(f"   - Running: vt twitter search to collect more data")
            return

        click.echo(f"   ✓ Found {len(tweets)} candidate tweets")

        # Embed tweets
        click.echo(f"\n🔢 Embedding tweets...")
        tweet_texts = [t.text for t in tweets]
        tweet_embeddings = embedder.embed_texts(tweet_texts, task_type="RETRIEVAL_DOCUMENT")
        click.echo(f"   ✓ Embedded {len(tweet_embeddings)} tweets")

        # Score tweets
        click.echo(f"\n📊 Scoring tweets...")
        scored_tweets = []

        for tweet, embedding in zip(tweets, tweet_embeddings):
            result = score_tweet(tweet, embedding, taxonomy_embeddings, config, use_gate=use_gate)
            scored_tweets.append((tweet, result))

        # Filter by gate
        if use_gate:
            passed_gate = [(t, r) for t, r in scored_tweets if r.passed_gate]
            click.echo(f"   ✓ Scored {len(scored_tweets)} tweets")
            click.echo(f"   - Passed gate: {len(passed_gate)}")
            click.echo(f"   - Blocked: {len(scored_tweets) - len(passed_gate)}")
            scored_tweets = passed_gate
        else:
            click.echo(f"   ✓ Scored {len(scored_tweets)} tweets (gate disabled)")

        if not scored_tweets:
            click.echo(f"\n⚠️  No tweets passed gate filtering")
            return

        # Filter by score if requested
        if skip_low_scores:
            high_quality = [(t, r) for t, r in scored_tweets if r.label in ['green', 'yellow']]
            click.echo(f"   - Green/Yellow: {len(high_quality)}")
            click.echo(f"   - Red (skipped): {len(scored_tweets) - len(high_quality)}")
            scored_tweets = high_quality

        if not scored_tweets:
            click.echo(f"\n⚠️  No high-quality tweets found")
            click.echo(f"\n💡 Try: --no-skip-low-scores to generate for all scores")
            return

        # Show score distribution
        green_count = sum(1 for _, r in scored_tweets if r.label == 'green')
        yellow_count = sum(1 for _, r in scored_tweets if r.label == 'yellow')
        red_count = sum(1 for _, r in scored_tweets if r.label == 'red')

        click.echo(f"\n   Score distribution:")
        click.echo(f"   - 🟢 Green ({green_count})")
        click.echo(f"   - 🟡 Yellow ({yellow_count})")
        if red_count > 0:
            click.echo(f"   - 🔴 Red ({red_count})")

        # Generate suggestions
        click.echo(f"\n🤖 Generating comment suggestions...")
        click.echo(f"   Processing {len(scored_tweets)} tweets with Gemini...")
        click.echo()

        generator = CommentGenerator()

        # Get project ID for DB save
        db = get_supabase_client()
        project_result = db.table('projects').select('id').eq('slug', project).single().execute()
        if not project_result.data:
            click.echo(f"\n❌ Error: Project '{project}' not found in database", err=True)
            raise click.Abort()

        project_id = project_result.data['id']

        success_count = 0
        safety_blocked_count = 0
        error_count = 0

        for i, (tweet, scoring_result) in enumerate(scored_tweets, 1):
            click.echo(f"   [{i}/{len(scored_tweets)}] Tweet {tweet.tweet_id[:12]}... ({scoring_result.label}, score={scoring_result.total_score:.2f})")

            # Generate suggestions
            gen_result = generator.generate_suggestions(tweet, scoring_result.best_topic, config)

            if gen_result.success:
                # Save to database
                comment_ids = save_suggestions_to_db(project_id, tweet.tweet_id, gen_result.suggestions, scoring_result)
                click.echo(f"      ✓ Generated 3 suggestions, saved to DB")
                success_count += 1
            elif gen_result.safety_blocked:
                click.echo(f"      ⚠ Blocked by safety filters (skipped)")
                safety_blocked_count += 1
            else:
                click.echo(f"      ✗ Generation failed: {gen_result.error[:50]}...")
                error_count += 1

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Generation Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Results:")
        click.echo(f"   Tweets processed: {len(scored_tweets)}")
        click.echo(f"   Successful: {success_count} ({success_count * 3} total suggestions)")
        if safety_blocked_count > 0:
            click.echo(f"   Safety blocked: {safety_blocked_count}")
        if error_count > 0:
            click.echo(f"   Errors: {error_count}")

        click.echo(f"\n💡 Next steps:")
        click.echo(f"   - Export to CSV: vt twitter export-comments --project {project}")
        click.echo(f"   - Review in DB: Check generated_comments table")

        click.echo(f"\n{'='*60}\n")

    except click.Abort:
        raise
    except Exception as e:
        click.echo(f"\n❌ Generation failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


@twitter_group.command(name="export-comments")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--out', '-o', required=True, help='Output CSV file path')
@click.option('--limit', default=200, type=int, help='Max suggestions to export (default: 200)')
@click.option('--label', type=click.Choice(['green', 'yellow', 'red']), help='Filter by label (optional)')
@click.option('--status', default='pending', help='Filter by status (default: pending)')
def export_comments(
    project: str,
    out: str,
    limit: int,
    label: Optional[str],
    status: str
):
    """
    Export comment suggestions to CSV

    Exports generated comment suggestions with scoring metadata
    to a CSV file for manual review and posting.

    CSV Columns:
      project, tweet_id, url, score_total, label, topic,
      suggestion_type, comment, why, rank

    Note: V1 exports core suggestion data. Tweet metadata (author, followers, etc.)
          will be added in V1.1 after FK relationships are established.

    Examples:
        # Export all pending suggestions
        vt twitter export-comments --project my-project --out comments.csv

        # Export top 50 green suggestions only
        vt twitter export-comments -p my-project -o top50.csv --limit 50 --label green

        # Export already exported (for review)
        vt twitter export-comments -p my-project -o review.csv --status exported
    """
    try:
        import csv
        from datetime import datetime

        click.echo(f"\n{'='*60}")
        click.echo(f"📤 Export Comment Suggestions")
        click.echo(f"{'='*60}\n")

        click.echo(f"Project: {project}")
        click.echo(f"Output: {out}")
        click.echo(f"Limit: {limit}")
        if label:
            click.echo(f"Label filter: {label}")
        click.echo(f"Status filter: {status}")
        click.echo()

        # Get project ID
        db = get_supabase_client()
        project_result = db.table('projects').select('id').eq('slug', project).single().execute()
        if not project_result.data:
            click.echo(f"\n❌ Error: Project '{project}' not found", err=True)
            raise click.Abort()

        project_id = project_result.data['id']

        # Query generated_comments (without tweet_snapshot for now - V1 limitation)
        click.echo("🔍 Querying database...")

        query = db.table('generated_comments')\
            .select('*')\
            .eq('project_id', project_id)\
            .eq('status', status)\
            .order('score_total', desc=True)\
            .limit(limit)

        if label:
            query = query.eq('label', label)

        result = query.execute()

        if not result.data:
            click.echo(f"\n⚠️  No suggestions found matching criteria")
            return

        click.echo(f"   ✓ Found {len(result.data)} suggestions")
        click.echo(f"   ℹ️  Note: Tweet metadata not included (FK relationship pending)")

        # Write CSV
        click.echo(f"\n📝 Writing CSV...")

        # Simplified fieldnames (without tweet metadata for V1)
        fieldnames = [
            'project', 'tweet_id', 'url', 'score_total', 'label', 'topic',
            'suggestion_type', 'comment', 'why', 'rank'
        ]

        rows_written = 0

        with open(out, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for suggestion in result.data:
                row = {
                    'project': project,
                    'tweet_id': suggestion['tweet_id'],
                    'url': f"https://twitter.com/i/status/{suggestion['tweet_id']}",
                    'score_total': round(suggestion['score_total'], 3),
                    'label': suggestion['label'],
                    'topic': suggestion.get('topic', ''),
                    'suggestion_type': suggestion['suggestion_type'],
                    'comment': suggestion['comment_text'],
                    'why': suggestion.get('why', ''),
                    'rank': suggestion.get('rank', 1)
                }

                writer.writerow(row)
                rows_written += 1

        click.echo(f"   ✓ Wrote {rows_written} rows to {out}")

        # Update status to 'exported'
        if status == 'pending':
            click.echo(f"\n🔄 Updating status to 'exported'...")
            comment_ids = [s['id'] for s in result.data]

            db.table('generated_comments')\
                .update({'status': 'exported'})\
                .in_('id', comment_ids)\
                .execute()

            click.echo(f"   ✓ Updated {len(comment_ids)} suggestions")

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Export Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Summary:")
        click.echo(f"   Exported: {rows_written} suggestions")
        click.echo(f"   File: {out}")

        # Show distribution
        if rows_written > 0:
            types_count = {}
            labels_count = {}

            for s in result.data[:rows_written]:
                t = s['suggestion_type']
                l = s['label']
                types_count[t] = types_count.get(t, 0) + 1
                labels_count[l] = labels_count.get(l, 0) + 1

            click.echo(f"\n   By type:")
            for t, count in sorted(types_count.items()):
                click.echo(f"   - {t}: {count}")

            click.echo(f"\n   By label:")
            for l, count in sorted(labels_count.items()):
                emoji = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(l, '')
                click.echo(f"   - {emoji} {l}: {count}")

        click.echo(f"\n💡 Next steps:")
        click.echo(f"   - Review CSV and select comments to post")
        click.echo(f"   - Post manually or use automation tool")
        click.echo(f"   - Mark as 'posted' in database when done")

        click.echo(f"\n{'='*60}\n")

    except click.Abort:
        raise
    except Exception as e:
        click.echo(f"\n❌ Export failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


# Export the command group
twitter = twitter_group
