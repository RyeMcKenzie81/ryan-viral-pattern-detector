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
from ..generation.async_comment_generator import generate_comments_async
from ..generation.cost_tracking import format_cost_summary


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

# Semantic deduplication threshold (V1.1)
SIMILARITY_THRESHOLD = 0.95  # Cosine similarity threshold for duplicate detection


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


def check_semantic_duplicates(project_id: str, tweet_embeddings: list, threshold: float = SIMILARITY_THRESHOLD):
    """
    Check for semantic duplicates using pgvector cosine similarity.

    Args:
        project_id: Project UUID
        tweet_embeddings: List of tweet embedding vectors
        threshold: Cosine similarity threshold (default: 0.95)

    Returns:
        List of booleans indicating if each tweet is a duplicate
    """
    import numpy as np

    db = get_supabase_client()

    # Fetch existing embeddings for this project
    result = db.table('acceptance_log')\
        .select('foreign_id, embedding')\
        .eq('project_id', project_id)\
        .eq('source', 'twitter')\
        .execute()

    if not result.data:
        # No existing embeddings, all tweets are new
        return [False] * len(tweet_embeddings)

    # Extract existing embeddings
    existing_embeddings = []
    for row in result.data:
        if row.get('embedding'):
            # pgvector stores embeddings as strings like "[0.1, 0.2, ...]"
            embedding_str = row['embedding']
            # Parse the embedding string to a numpy array
            if isinstance(embedding_str, str):
                # Remove brackets and parse
                embedding_list = [float(x) for x in embedding_str.strip('[]').split(',')]
                existing_embeddings.append(np.array(embedding_list))
            elif isinstance(embedding_str, list):
                existing_embeddings.append(np.array(embedding_str))

    if not existing_embeddings:
        return [False] * len(tweet_embeddings)

    # Check each candidate tweet against all existing embeddings
    is_duplicate = []

    for tweet_emb in tweet_embeddings:
        tweet_vec = np.array(tweet_emb)
        max_similarity = 0.0

        for existing_emb in existing_embeddings:
            # Compute cosine similarity
            similarity = np.dot(tweet_vec, existing_emb) / (
                np.linalg.norm(tweet_vec) * np.linalg.norm(existing_emb)
            )
            max_similarity = max(max_similarity, similarity)

        is_duplicate.append(max_similarity >= threshold)

    return is_duplicate


def store_tweet_embedding(project_id: str, tweet_id: str, embedding: list):
    """
    Store tweet embedding in acceptance_log for future deduplication.

    Args:
        project_id: Project UUID
        tweet_id: Tweet ID
        embedding: Tweet embedding vector (768-dim)
    """
    db = get_supabase_client()

    # Upsert to acceptance_log
    db.table('acceptance_log').upsert({
        'project_id': project_id,
        'source': 'twitter',
        'foreign_id': tweet_id,
        'embedding': embedding  # pgvector will handle the conversion
    }, on_conflict='project_id,source,foreign_id').execute()


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
@click.option('--use-gate/--no-use-gate', default=True, help='Apply gate filtering (default: True)')
@click.option('--skip-low-scores/--no-skip-low-scores', default=True, help='Only generate for green/yellow (default: True)')
@click.option('--greens-only', is_flag=True, help='Only generate for greens (overrides --skip-low-scores)')
@click.option('--batch-size', default=5, type=int, help='Number of concurrent requests (default: 5, V1.2)')
@click.option('--no-batch', is_flag=True, help='Disable batch processing (use sequential, V1.2)')
def generate_comments(
    project: str,
    hours_back: int,
    min_followers: int,
    min_likes: int,
    max_candidates: int,
    use_gate: bool,
    skip_low_scores: bool,
    greens_only: bool,
    batch_size: int,
    no_batch: bool
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

        if greens_only:
            click.echo(f"Skip low scores: yes (greens only)")
        elif skip_low_scores:
            click.echo(f"Skip low scores: yes (green/yellow only)")
        else:
            click.echo(f"Skip low scores: no (all)")

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

        # Compute taxonomy embeddings (V1.1: with incremental caching)
        click.echo(f"\n🏷️  Computing taxonomy embeddings...")
        from viraltracker.core.embeddings import load_taxonomy_embeddings_incremental

        # Use incremental loading - only recomputes changed nodes
        taxonomy_embeddings = load_taxonomy_embeddings_incremental(
            project,
            config.taxonomy,
            embedder
        )

        click.echo(f"   ✓ Ready with {len(taxonomy_embeddings)} taxonomy embeddings")

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

        # Get project ID (needed for semantic dedup - V1.1)
        db = get_supabase_client()
        project_result = db.table('projects').select('id').eq('slug', project).single().execute()
        if not project_result.data:
            click.echo(f"\n❌ Error: Project '{project}' not found in database", err=True)
            raise click.Abort()

        project_id = project_result.data['id']

        # Embed tweets
        click.echo(f"\n🔢 Embedding tweets...")
        tweet_texts = [t.text for t in tweets]
        tweet_embeddings = embedder.embed_texts(tweet_texts, task_type="RETRIEVAL_DOCUMENT")
        click.echo(f"   ✓ Embedded {len(tweet_embeddings)} tweets")

        # V1.1: Check for semantic duplicates
        click.echo(f"\n🔍 Checking for semantic duplicates...")
        is_duplicate = check_semantic_duplicates(project_id, tweet_embeddings)
        duplicate_count = sum(is_duplicate)

        if duplicate_count > 0:
            click.echo(f"   ✓ Found {duplicate_count} duplicates (similarity > {SIMILARITY_THRESHOLD})")
            click.echo(f"   - Will skip {duplicate_count} tweets to save API costs")
        else:
            click.echo(f"   ✓ No duplicates found")

        # Filter out duplicates
        tweets_filtered = [(tweet, emb) for tweet, emb, is_dup in zip(tweets, tweet_embeddings, is_duplicate) if not is_dup]

        if not tweets_filtered:
            click.echo(f"\n⚠️  All tweets are duplicates - nothing to process")
            return

        if duplicate_count > 0:
            click.echo(f"   - Processing {len(tweets_filtered)} unique tweets")

        # Unpack filtered tweets and embeddings
        tweets = [t for t, _ in tweets_filtered]
        tweet_embeddings = [e for _, e in tweets_filtered]

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
        if greens_only:
            greens = [(t, r) for t, r in scored_tweets if r.label == 'green']
            click.echo(f"   - Greens: {len(greens)}")
            click.echo(f"   - Yellow/Red (skipped): {len(scored_tweets) - len(greens)}")
            scored_tweets = greens
        elif skip_low_scores:
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

        # V1.2: Check if batch processing should be used
        use_batch = not no_batch and len(scored_tweets) > 1

        if use_batch:
            click.echo(f"   ⚡ Batch mode: Processing {len(scored_tweets)} tweets with {batch_size} concurrent requests")
        else:
            click.echo(f"   Processing {len(scored_tweets)} tweets sequentially...")

        click.echo()

        # Create a map of tweet to embedding for storage after generation
        tweet_embedding_map = {tweet.tweet_id: emb for tweet, emb in zip(tweets, tweet_embeddings)}

        success_count = 0
        safety_blocked_count = 0
        error_count = 0
        total_cost_usd = 0.0  # V1.2: Track API costs

        if use_batch:
            # V1.2: Use async batch processing
            import asyncio

            # Progress callback for async generation
            def progress_callback(current, total):
                progress_pct = int((current / total) * 100)
                click.echo(f"   [{current}/{total}] Progress: {progress_pct}%")

            # Run async batch generation
            stats = asyncio.run(generate_comments_async(
                project_id=project_id,
                tweets_with_scores=scored_tweets,
                config=config,
                batch_size=batch_size,
                max_requests_per_minute=15,
                progress_callback=progress_callback
            ))

            # Store embeddings for all successful tweets (V1.1: semantic dedup)
            for tweet, _ in scored_tweets:
                tweet_emb = tweet_embedding_map.get(tweet.tweet_id)
                if tweet_emb:
                    store_tweet_embedding(project_id, tweet.tweet_id, tweet_emb)

            success_count = stats['generated'] // 3  # 3 suggestions per tweet
            error_count = stats['failed']
            safety_blocked_count = 0  # Not tracked separately in async mode
            total_cost_usd = stats.get('total_cost_usd', 0.0)  # V1.2: Extract cost

        else:
            # V1/V1.1: Sequential processing
            generator = CommentGenerator()

            for i, (tweet, scoring_result) in enumerate(scored_tweets, 1):
                click.echo(f"   [{i}/{len(scored_tweets)}] Tweet {tweet.tweet_id[:12]}... ({scoring_result.label}, score={scoring_result.total_score:.2f})")

                # Generate suggestions
                gen_result = generator.generate_suggestions(tweet, scoring_result.best_topic, config)

                if gen_result.success:
                    # Save to database (V1.1: pass tweet for enhanced rationale, V1.2: pass cost)
                    comment_ids = save_suggestions_to_db(project_id, tweet.tweet_id, gen_result.suggestions, scoring_result, tweet, gen_result.api_cost_usd)

                    # V1.1: Store embedding in acceptance_log for future deduplication
                    tweet_emb = tweet_embedding_map.get(tweet.tweet_id)
                    if tweet_emb:
                        store_tweet_embedding(project_id, tweet.tweet_id, tweet_emb)

                    click.echo(f"      ✓ Generated {len(gen_result.suggestions)} suggestions, saved to DB")
                    success_count += 1

                    # V1.2: Track cost
                    if gen_result.api_cost_usd is not None:
                        total_cost_usd += gen_result.api_cost_usd
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

        # V1.2: Display API cost
        if total_cost_usd > 0 and success_count > 0:
            cost_summary = format_cost_summary(total_cost_usd, success_count)
            click.echo(f"\n{cost_summary}")

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
@click.option('--sort-by', type=click.Choice(['score', 'views', 'balanced']), default='balanced', help='Sort method: score (quality), views (reach), balanced (score×√views) [default: balanced]')
def export_comments(
    project: str,
    out: str,
    limit: int,
    label: Optional[str],
    status: str,
    sort_by: str
):
    """
    Export comment suggestions to CSV

    Exports generated comment suggestions with full tweet metadata and scoring data
    to a CSV file for manual review and posting.

    CSV Format (one row per tweet):
      - project, tweet_id, url
      - author, followers, views, tweet_text, posted_at (V1.1: tweet metadata)
      - score_total, label, topic, why
      - suggested_response, suggested_type (primary suggestion, rank=1)
      - alternative_1, alt_1_type (2nd option)
      - alternative_2, alt_2_type (3rd option)
      - alternative_3, alt_3_type (4th option - V1.3)
      - alternative_4, alt_4_type (5th option - V1.3)

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
        click.echo(f"Sort by: {sort_by}")
        click.echo()

        # Get project ID
        db = get_supabase_client()
        project_result = db.table('projects').select('id').eq('slug', project).single().execute()
        if not project_result.data:
            click.echo(f"\n❌ Error: Project '{project}' not found", err=True)
            raise click.Abort()

        project_id = project_result.data['id']

        # Query generated_comments with tweet metadata (V1.1)
        click.echo("🔍 Querying database...")

        # Get all suggestions with JOIN to posts and accounts for metadata
        query = db.table('generated_comments')\
            .select('*, posts(post_id, caption, posted_at, views, accounts(platform_username, follower_count))')\
            .eq('project_id', project_id)\
            .eq('status', status)\
            .order('score_total', desc=True)

        if label:
            query = query.eq('label', label)

        result = query.execute()

        if not result.data:
            click.echo(f"\n⚠️  No suggestions found matching criteria")
            return

        click.echo(f"   ✓ Found {len(result.data)} suggestions")

        # Group by tweet_id (each tweet has 5 suggestions in V1.3)
        from collections import defaultdict
        import math
        tweets_map = defaultdict(list)

        for suggestion in result.data:
            tweets_map[suggestion['tweet_id']].append(suggestion)

        # Sort tweets based on sort_by parameter
        if sort_by == 'score':
            # Sort by score only (quality)
            sorted_tweets = sorted(tweets_map.items(),
                                  key=lambda x: max(s['score_total'] for s in x[1]),
                                  reverse=True)[:limit]
        elif sort_by == 'views':
            # Sort by views only (reach)
            def get_views(item):
                suggestions = item[1]
                for s in suggestions:
                    post_data = s.get('posts')
                    if post_data:
                        return post_data.get('views', 0) or 0
                return 0
            sorted_tweets = sorted(tweets_map.items(),
                                  key=get_views,
                                  reverse=True)[:limit]
        else:  # balanced (default)
            # Sort by score × √views (balanced quality + reach)
            def get_priority(item):
                suggestions = item[1]
                score = max(s['score_total'] for s in suggestions)
                for s in suggestions:
                    post_data = s.get('posts')
                    if post_data:
                        views = post_data.get('views', 0) or 0
                        return score * math.sqrt(views)
                return score  # Fallback if no views data
            sorted_tweets = sorted(tweets_map.items(),
                                  key=get_priority,
                                  reverse=True)[:limit]

        click.echo(f"   ✓ Grouped into {len(sorted_tweets)} tweets with metadata")

        # Write CSV
        click.echo(f"\n📝 Writing CSV...")

        # One row per tweet with tweet metadata + suggested response + alternatives (V1.3: 5 types)
        fieldnames = [
            'rank', 'priority_score',  # Prioritization columns (V1.4)
            'project', 'tweet_id', 'url', 'author', 'followers', 'views', 'tweet_text', 'posted_at',
            'score_total', 'label', 'topic', 'why',
            'suggested_response', 'suggested_type',
            'alternative_1', 'alt_1_type',
            'alternative_2', 'alt_2_type',
            'alternative_3', 'alt_3_type',
            'alternative_4', 'alt_4_type'
        ]

        rows_written = 0

        with open(out, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for rank_num, (tweet_id, suggestions) in enumerate(sorted_tweets, 1):
                # Sort by rank (1=primary, 2-5=alternatives)
                suggestions_sorted = sorted(suggestions, key=lambda s: s.get('rank', 1))

                # Primary suggestion (rank=1)
                primary = suggestions_sorted[0]
                alts = suggestions_sorted[1:5]  # V1.3: Get all 4 alternatives

                # Extract tweet metadata from joined posts/accounts data
                post_data = primary.get('posts')
                tweet_text = ''
                author = ''
                followers = 0
                views = 0
                posted_at = ''

                if post_data:
                    tweet_text = post_data.get('caption', '')
                    posted_at = post_data.get('posted_at', '')
                    views = post_data.get('views', 0) or 0
                    account_data = post_data.get('accounts')
                    if account_data:
                        author = account_data.get('platform_username', '')
                        followers = account_data.get('follower_count', 0) or 0

                # Calculate priority_score based on sort method
                score = primary['score_total']
                if sort_by == 'views':
                    priority_score = views
                elif sort_by == 'balanced':
                    priority_score = score * math.sqrt(views)
                else:  # score
                    priority_score = score

                row = {
                    'rank': rank_num,
                    'priority_score': round(priority_score, 2),
                    'project': project,
                    'tweet_id': tweet_id,
                    'url': f"https://twitter.com/i/status/{tweet_id}",
                    'author': author,
                    'followers': followers,
                    'views': views,
                    'tweet_text': tweet_text,
                    'posted_at': posted_at,
                    'score_total': round(primary['score_total'], 3),
                    'label': primary['label'],
                    'topic': primary.get('topic', ''),
                    'why': primary.get('why', ''),
                    'suggested_response': primary['comment_text'],
                    'suggested_type': primary['suggestion_type'],
                    'alternative_1': alts[0]['comment_text'] if len(alts) > 0 else '',
                    'alt_1_type': alts[0]['suggestion_type'] if len(alts) > 0 else '',
                    'alternative_2': alts[1]['comment_text'] if len(alts) > 1 else '',
                    'alt_2_type': alts[1]['suggestion_type'] if len(alts) > 1 else '',
                    'alternative_3': alts[2]['comment_text'] if len(alts) > 2 else '',
                    'alt_3_type': alts[2]['suggestion_type'] if len(alts) > 2 else '',
                    'alternative_4': alts[3]['comment_text'] if len(alts) > 3 else '',
                    'alt_4_type': alts[3]['suggestion_type'] if len(alts) > 3 else '',
                }

                writer.writerow(row)
                rows_written += 1

        click.echo(f"   ✓ Wrote {rows_written} tweets to {out}")

        # Update status to 'exported'
        if status == 'pending':
            click.echo(f"\n🔄 Updating status to 'exported'...")

            # Get all comment IDs from the exported tweets
            comment_ids = []
            for tweet_id, suggestions in sorted_tweets:
                comment_ids.extend([s['id'] for s in suggestions])

            # Batch update to avoid URL length limits (100 IDs per batch)
            batch_size = 100
            total_updated = 0
            for i in range(0, len(comment_ids), batch_size):
                batch = comment_ids[i:i + batch_size]
                db.table('generated_comments')\
                    .update({'status': 'exported'})\
                    .in_('id', batch)\
                    .execute()
                total_updated += len(batch)

            click.echo(f"   ✓ Updated {total_updated} suggestions ({rows_written} tweets)")

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✅ Export Complete")
        click.echo(f"{'='*60}\n")

        click.echo(f"📊 Summary:")
        click.echo(f"   Exported: {rows_written} tweets ({rows_written * 5} total suggestions)")
        click.echo(f"   File: {out}")

        # Show distribution by label
        if rows_written > 0:
            labels_count = {}

            for tweet_id, suggestions in sorted_tweets:
                # Use label from first suggestion (they all have same label)
                l = suggestions[0]['label']
                labels_count[l] = labels_count.get(l, 0) + 1

            click.echo(f"\n   By label:")
            for l, count in sorted(labels_count.items()):
                emoji = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(l, '')
                click.echo(f"   - {emoji} {l}: {count} tweets")

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


@twitter_group.command(name="analyze-search-term")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--term', required=True, help='Search term to analyze')
@click.option('--count', default=1000, type=int, help='Tweets to analyze (default: 1000)')
@click.option('--min-likes', default=0, type=int, help='Minimum likes (default: 0)')
@click.option('--days-back', default=7, type=int, help='Days to look back (default: 7)')
@click.option('--batch-size', default=10, type=int, help='Comment generation batch size (default: 10)')
@click.option('--skip-comments', is_flag=True, help='Skip comment generation (faster, cheaper)')
@click.option('--report-file', help='Output JSON report path (optional)')
def analyze_search_term(
    project: str,
    term: str,
    count: int,
    min_likes: int,
    days_back: int,
    batch_size: int,
    skip_comments: bool,
    report_file: Optional[str]
):
    """
    Analyze a search term to find engagement opportunities

    Tests a search term by scraping tweets, scoring them against the project's
    taxonomy, and analyzing multiple dimensions: quality (green ratio), volume
    (freshness), virality (views), and cost efficiency.

    Use this to find the best search terms for your project before committing
    to regular scraping.

    Examples:
        # Quick test
        vt twitter analyze-search-term -p my-project --term "screen time kids"

        # Full analysis with 1000 tweets
        vt twitter analyze-search-term -p my-project --term "parenting tips" \\
          --count 1000 --min-likes 20 --report-file ~/Downloads/report.json
    """
    try:
        from ..analysis.search_term_analyzer import SearchTermAnalyzer

        click.echo(f"\n{'='*60}")
        click.echo(f"🔍 Search Term Analysis")
        click.echo(f"{'='*60}\n")

        click.echo(f"Project: {project}")
        click.echo(f"Search term: \"{term}\"")
        click.echo(f"Analyzing {count} tweets...")
        click.echo()

        # Initialize analyzer
        try:
            analyzer = SearchTermAnalyzer(project)
        except ValueError as e:
            click.echo(f"\n❌ Error: {e}", err=True)
            raise click.Abort()
        except FileNotFoundError:
            click.echo(f"\n❌ Error: No finder.yml found for project '{project}'", err=True)
            click.echo(f"   Create: projects/{project}/finder.yml", err=True)
            raise click.Abort()

        # Progress tracking
        current_phase = [""]
        phase_emoji = {
            "scraping": "🔍",
            "embedding": "🔢",
            "scoring": "📊",
            "generating": "🤖",
            "analyzing": "📈"
        }

        def progress_callback(phase, current, total):
            if phase != current_phase[0]:
                current_phase[0] = phase
                emoji = phase_emoji.get(phase, "⏳")
                click.echo(f"{emoji} {phase.title()}...")

        # Run analysis
        click.echo("Starting analysis...\n")

        try:
            metrics = analyzer.analyze(
                term,
                count,
                min_likes,
                days_back,
                batch_size,
                skip_comments=skip_comments,
                progress_callback=progress_callback
            )
        except ValueError as e:
            click.echo(f"\n❌ Error: {e}", err=True)
            click.echo("\n💡 Try:")
            click.echo("   - Different search term")
            click.echo("   - Lowering --min-likes")
            click.echo("   - Increasing --days-back")
            raise click.Abort()

        # Display results
        click.echo(f"\n{'='*60}")
        click.echo(f"📊 Analysis Results")
        click.echo(f"{'='*60}\n")

        click.echo(f"Tweets analyzed: {metrics.tweets_analyzed}")
        click.echo()

        click.echo(f"Score Distribution:")
        click.echo(f"  🟢 Green:  {metrics.green_count:4d} ({metrics.green_percentage:5.1f}%) - avg score: {metrics.green_avg_score:.3f}")
        click.echo(f"  🟡 Yellow: {metrics.yellow_count:4d} ({metrics.yellow_percentage:5.1f}%) - avg score: {metrics.yellow_avg_score:.3f}")
        click.echo(f"  🔴 Red:    {metrics.red_count:4d} ({metrics.red_percentage:5.1f}%) - avg score: {metrics.red_avg_score:.3f}")
        click.echo()

        click.echo(f"Freshness:")
        click.echo(f"  Last 48h: {metrics.last_48h_count} tweets ({metrics.last_48h_percentage:.1f}%)")
        click.echo(f"  ~{metrics.conversations_per_day:.0f} tweets/day")
        click.echo()

        click.echo(f"Virality:")
        if metrics.avg_views > 0:
            click.echo(f"  Avg views:    {metrics.avg_views:,.0f}")
            click.echo(f"  Median views: {metrics.median_views:,.0f}")
            click.echo(f"  Top 10% avg:  {metrics.top_10_percent_avg_views:,.0f}")
            click.echo(f"  10k+ views:   {metrics.tweets_with_10k_plus_views} tweets")
        else:
            click.echo(f"  (View data not available)")
        click.echo()

        click.echo(f"Topic Distribution:")
        for topic, count in sorted(metrics.topic_distribution.items(), key=lambda x: x[1], reverse=True):
            pct = (count / metrics.tweets_analyzed * 100) if metrics.tweets_analyzed > 0 else 0
            click.echo(f"  - {topic}: {count} ({pct:.1f}%)")
        click.echo()

        click.echo(f"Cost Efficiency:")
        click.echo(f"  Total cost:        ${metrics.total_cost_usd:.3f}")
        if metrics.cost_per_green > 0:
            click.echo(f"  Cost per green:    ${metrics.cost_per_green:.5f}")
            click.echo(f"  Greens per dollar: {metrics.greens_per_dollar:.0f}")
        click.echo()

        click.echo(f"{'='*60}")
        click.echo(f"💡 Recommendation: {metrics.recommendation} ({metrics.confidence} confidence)")
        click.echo(f"{'='*60}")
        click.echo(f"{metrics.reasoning}")
        click.echo()

        # Export if requested
        if report_file:
            analyzer.export_json(metrics, report_file)
            click.echo(f"✅ Report saved to: {report_file}\n")

        click.echo(f"{'='*60}\n")

    except click.Abort:
        raise
    except Exception as e:
        click.echo(f"\n❌ Analysis failed: {e}", err=True)
        logger.exception(e)
        raise click.Abort()


# Export the command group
twitter = twitter_group
