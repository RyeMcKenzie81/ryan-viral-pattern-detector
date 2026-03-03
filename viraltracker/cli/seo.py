"""
SEO Pipeline CLI Commands

Commands for managing SEO projects, keyword discovery, content generation,
publishing, and interlinking.
"""

import logging

import click

from ..core.database import get_supabase_client


logger = logging.getLogger(__name__)


@click.group(name="seo")
def seo_group():
    """Manage SEO pipeline projects and content."""
    pass


# =========================================================================
# PROJECT MANAGEMENT
# =========================================================================

@seo_group.command(name="projects")
@click.option("--brand", "brand_slug", help="Brand slug to filter by")
@click.option("--org-id", help="Organization ID (defaults to env)")
def list_projects(brand_slug: str, org_id: str):
    """List SEO projects."""
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService

    supabase = get_supabase_client()
    service = SEOProjectService(supabase)

    org_id = org_id or "all"
    brand_id = None

    if brand_slug:
        brand_result = supabase.table("brands").select("id").eq("slug", brand_slug).execute()
        if not brand_result.data:
            click.echo(f"Brand '{brand_slug}' not found")
            return
        brand_id = brand_result.data[0]["id"]

    projects = service.list_projects(org_id, brand_id=brand_id)

    if not projects:
        click.echo("No SEO projects found.")
        return

    click.echo(f"\nFound {len(projects)} SEO project(s):\n")
    for p in projects:
        status = p.get("status", "unknown")
        click.echo(f"  [{status}] {p['name']} (id: {p['id'][:8]}...)")


# =========================================================================
# KEYWORD DISCOVERY (Phase 2 - stub)
# =========================================================================

@seo_group.command(name="discover")
@click.option("--brand", "brand_slug", required=True, help="Brand slug")
@click.option("--seeds", required=True, help="Comma-separated seed keywords")
@click.option("--min-words", default=3, help="Minimum word count (default: 3)")
@click.option("--max-words", default=10, help="Maximum word count (default: 10)")
@click.option("--project-id", help="Existing project ID (creates new if omitted)")
@click.option("--org-id", help="Organization ID (defaults to env)")
def discover_keywords(brand_slug: str, seeds: str, min_words: int, max_words: int, project_id: str, org_id: str):
    """Discover long-tail keywords via Google Autocomplete."""
    import asyncio
    from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService

    supabase = get_supabase_client()
    org_id = org_id or "all"

    # Resolve brand
    brand_result = supabase.table("brands").select("id, name").eq("slug", brand_slug).execute()
    if not brand_result.data:
        click.echo(f"Brand '{brand_slug}' not found")
        return
    brand = brand_result.data[0]
    brand_id = brand["id"]

    # Get or create project
    if not project_id:
        project_service = SEOProjectService(supabase)
        project = project_service.create_project(
            brand_id=brand_id,
            organization_id=org_id if org_id != "all" else brand.get("organization_id", org_id),
            name=f"SEO Discovery - {brand['name']}",
        )
        project_id = project["id"]
        click.echo(f"Created project: {project_id}")

    # Run discovery
    seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
    click.echo(f"\nDiscovering keywords for {len(seed_list)} seed(s): {', '.join(seed_list)}")
    click.echo(f"Word count filter: {min_words}-{max_words} words\n")

    service = KeywordDiscoveryService(supabase)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            service.discover_keywords(project_id, seed_list, min_words, max_words)
        )
    finally:
        loop.close()

    click.echo(f"\nResults:")
    click.echo(f"  Total unique keywords: {result['total_keywords']}")
    click.echo(f"  New keywords saved: {result['saved_count']}")

    if result["keywords"]:
        click.echo(f"\nTop 20 keywords (by cross-seed frequency):")
        for i, kw in enumerate(result["keywords"][:20], 1):
            click.echo(
                f"  {i:2d}. [{kw['found_in_seeds']}x] {kw['keyword']} "
                f"({kw['word_count']} words)"
            )


# =========================================================================
# COMPETITOR ANALYSIS (Phase 3 - stub)
# =========================================================================

@seo_group.command(name="analyze")
@click.argument("keyword")
@click.option("--urls", multiple=True, help="Competitor URLs to analyze")
@click.option("--keyword-id", help="Keyword UUID (if already in DB)")
def analyze_competitors(keyword: str, urls: tuple, keyword_id: str):
    """Analyze competitor pages for a keyword."""
    from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService

    if not urls:
        click.echo("No URLs provided. Use --urls <url1> --urls <url2> ...")
        return

    url_list = list(urls)
    click.echo(f"\nAnalyzing {len(url_list)} competitor pages for '{keyword}'...\n")

    service = CompetitorAnalysisService()

    # Use keyword_id if provided, otherwise use a placeholder for CLI-only mode
    kid = keyword_id or "00000000-0000-0000-0000-000000000000"
    result = service.analyze_urls(kid, url_list)

    click.echo(f"\nResults: {result['analyzed_count']} analyzed, {result['failed_count']} failed")

    if result.get("failed_urls"):
        click.echo(f"Failed URLs: {', '.join(result['failed_urls'])}")

    if result.get("winning_formula"):
        wf = result["winning_formula"]
        click.echo(f"\nWinning Formula ({wf.get('competitor_count', 0)} competitors):")
        click.echo(f"  Target word count: {wf.get('target_word_count', 0)}")
        click.echo(f"  Avg H2 count: {wf.get('avg_h2_count', 0)}")
        click.echo(f"  Avg images: {wf.get('avg_image_count', 0)}")
        click.echo(f"  Avg Flesch score: {wf.get('avg_flesch_score', 0)}")
        click.echo(f"  Schema: {wf.get('pct_with_schema', 0)}% | FAQ: {wf.get('pct_with_faq', 0)}%")

        if wf.get("opportunities"):
            click.echo(f"\nOpportunities:")
            for opp in wf["opportunities"]:
                click.echo(f"  [{opp['severity']}] {opp['detail']}")


# =========================================================================
# CONTENT GENERATION (Phase 4 - stub)
# =========================================================================

@seo_group.command(name="generate")
@click.argument("keyword")
@click.option("--phase", type=click.Choice(["a", "b", "c", "all"]), default="all", help="Generation phase")
@click.option("--mode", type=click.Choice(["api", "cli"]), default="api", help="Execution mode")
@click.option("--author", help="Author name")
@click.option("--article-id", help="Existing article ID (creates new if omitted)")
@click.option("--project-id", help="Project ID (required for new articles)")
@click.option("--brand", "brand_slug", help="Brand slug (required for new articles)")
@click.option("--model", default="claude-opus-4-20250514", help="Model for API mode")
def generate_content(keyword: str, phase: str, mode: str, author: str,
                     article_id: str, project_id: str, brand_slug: str, model: str):
    """Generate article content for a keyword."""
    from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService

    supabase = get_supabase_client()
    service = ContentGenerationService(supabase_client=supabase)

    # Resolve author ID if name provided
    author_id = None
    if author:
        author_result = (
            supabase.table("seo_authors")
            .select("id")
            .ilike("name", f"%{author}%")
            .execute()
        )
        if author_result.data:
            author_id = author_result.data[0]["id"]
            click.echo(f"Using author: {author} ({author_id[:8]}...)")
        else:
            click.echo(f"Author '{author}' not found, using default voice.")

    # Get or create article
    if not article_id:
        if not project_id or not brand_slug:
            click.echo("For new articles, provide --project-id and --brand.")
            return

        brand_result = supabase.table("brands").select("id").eq("slug", brand_slug).execute()
        if not brand_result.data:
            click.echo(f"Brand '{brand_slug}' not found.")
            return
        brand_id = brand_result.data[0]["id"]

        article = service.create_article(
            project_id=project_id,
            brand_id=brand_id,
            organization_id="all",
            keyword=keyword,
            author_id=author_id,
        )
        article_id = article["id"]
        click.echo(f"Created article: {article_id}")

    # Run phases
    phases_to_run = ["a", "b", "c"] if phase == "all" else [phase]

    for p in phases_to_run:
        click.echo(f"\nRunning Phase {p.upper()} ({mode} mode)...")

        if p == "a":
            result = service.generate_phase_a(
                article_id=article_id,
                keyword=keyword,
                mode=mode,
                author_id=author_id,
                model=model,
            )
        elif p == "b":
            article = service.get_article(article_id)
            phase_a_out = article.get("phase_a_output", "") if article else ""
            if not phase_a_out and mode == "api":
                click.echo("No Phase A output found. Run Phase A first.")
                return
            result = service.generate_phase_b(
                article_id=article_id,
                keyword=keyword,
                phase_a_output=phase_a_out,
                mode=mode,
                author_id=author_id,
                model=model,
            )
        elif p == "c":
            article = service.get_article(article_id)
            phase_b_out = article.get("phase_b_output", "") if article else ""
            if not phase_b_out and mode == "api":
                click.echo("No Phase B output found. Run Phase B first.")
                return
            result = service.generate_phase_c(
                article_id=article_id,
                keyword=keyword,
                phase_b_output=phase_b_out,
                mode=mode,
                author_id=author_id,
                model=model,
            )

        if result.get("mode") == "cli":
            click.echo(f"Prompt file: {result['prompt_file']}")
            click.echo(result["instructions"])
        else:
            click.echo(
                f"Phase {p.upper()} complete: "
                f"{result.get('input_tokens', 0)} in / {result.get('output_tokens', 0)} out tokens, "
                f"{result.get('duration_ms', 0)}ms"
            )


@seo_group.command(name="ingest-result")
@click.option("--article-id", required=True, help="Article UUID")
@click.option("--phase", required=True, type=click.Choice(["a", "b", "c"]), help="Phase to ingest")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Result file path")
def ingest_result(article_id: str, phase: str, file_path: str):
    """Ingest CLI-mode generation result back into the pipeline."""
    from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
    from pathlib import Path

    content = Path(file_path).read_text(encoding="utf-8")
    if not content.strip():
        click.echo("File is empty.")
        return

    service = ContentGenerationService()
    result = service.ingest_cli_result(article_id, phase, content)
    click.echo(f"Ingested Phase {phase.upper()} for article {result['article_id']}")


# =========================================================================
# QA & PUBLISHING (Phase 5 - stub)
# =========================================================================

@seo_group.command(name="validate")
@click.argument("article_id")
def validate_article(article_id: str):
    """Run QA validation on an article."""
    from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService

    supabase = get_supabase_client()
    service = QAValidationService(supabase)

    try:
        result = service.validate_article(article_id)
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    status = "PASS" if result["passed"] else "FAIL"
    click.echo(f"\nQA Validation: {status}")
    click.echo(f"  Checks: {result['passed_checks']}/{result['total_checks']} passed")
    click.echo(f"  Errors: {result['error_count']} | Warnings: {result['warning_count']}")

    if result["failures"]:
        click.echo(f"\nErrors:")
        for check in result["failures"]:
            click.echo(f"  [ERROR] {check['name']}: {check['message']}")

    if result["warnings"]:
        click.echo(f"\nWarnings:")
        for check in result["warnings"]:
            click.echo(f"  [WARN]  {check['name']}: {check['message']}")

    if result["passed"]:
        click.echo(f"\nArticle is ready for publishing.")
    else:
        click.echo(f"\nFix errors before publishing.")


@seo_group.command(name="publish")
@click.argument("article_id")
@click.option("--draft/--published", default=True, help="Publish as draft or live")
@click.option("--brand", "brand_slug", help="Brand slug (auto-detected from article if omitted)")
@click.option("--org-id", help="Organization ID (defaults to env)")
def publish_article(article_id: str, draft: bool, brand_slug: str, org_id: str):
    """Publish an article to the configured CMS."""
    from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService

    supabase = get_supabase_client()
    service = CMSPublisherService(supabase)
    org_id = org_id or "all"

    # Get article to resolve brand_id
    article = supabase.table("seo_articles").select("brand_id").eq("id", article_id).execute()
    if not article.data:
        click.echo(f"Article not found: {article_id}")
        return
    brand_id = article.data[0]["brand_id"]

    mode = "draft" if draft else "published"
    click.echo(f"\nPublishing article {article_id[:8]}... as {mode}...")

    try:
        result = service.publish_article(
            article_id=article_id,
            brand_id=brand_id,
            organization_id=org_id,
            draft=draft,
        )
    except ValueError as e:
        click.echo(f"Error: {e}")
        return
    except Exception as e:
        click.echo(f"Publishing failed: {e}")
        return

    click.echo(f"\nPublished successfully!")
    click.echo(f"  CMS ID: {result.get('cms_article_id')}")
    click.echo(f"  Status: {result.get('status')}")
    if result.get("published_url"):
        click.echo(f"  URL: {result['published_url']}")
    if result.get("admin_url"):
        click.echo(f"  Admin: {result['admin_url']}")


# =========================================================================
# INTERLINKING (Phase 6 - stub)
# =========================================================================

@seo_group.command(name="suggest-links")
@click.argument("article_id")
@click.option("--min-similarity", default=0.2, help="Minimum Jaccard similarity (default: 0.2)")
@click.option("--max-suggestions", default=5, help="Max suggestions (default: 5)")
def suggest_links(article_id: str, min_similarity: float, max_suggestions: int):
    """Suggest internal links for an article."""
    from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

    supabase = get_supabase_client()
    service = InterlinkingService(supabase)

    try:
        result = service.suggest_links(article_id, min_similarity, max_suggestions)
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    click.echo(f"\nLink suggestions for '{result['keyword']}':")
    click.echo(f"Found {result['suggestion_count']} suggestion(s):\n")

    for i, s in enumerate(result["suggestions"], 1):
        priority = "HIGH" if s["priority"] == "high" else "MEDIUM"
        click.echo(
            f"  {i}. [{priority}] {s['target_keyword']} "
            f"(similarity: {s['similarity']:.0%}, placement: {s['placement']})"
        )
        if s["anchor_texts"]:
            click.echo(f"     Anchor: \"{s['anchor_texts'][0]}\"")


@seo_group.command(name="auto-link")
@click.argument("article_id")
def auto_link(article_id: str):
    """Auto-insert internal links into article HTML."""
    from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

    supabase = get_supabase_client()
    service = InterlinkingService(supabase)

    try:
        result = service.auto_link_article(article_id)
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    if result.get("message"):
        click.echo(result["message"])
        return

    click.echo(f"\nAuto-linking complete: {result['links_added']} link(s) added")
    for linked in result.get("linked_articles", []):
        click.echo(f"  -> {linked['keyword']} ({linked['links_added']} links)")


@seo_group.command(name="add-related")
@click.argument("article_id")
@click.option("--related", required=True, help="Comma-separated related article IDs")
def add_related(article_id: str, related: str):
    """Add Related Articles section to an article."""
    from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

    supabase = get_supabase_client()
    service = InterlinkingService(supabase)

    related_ids = [r.strip() for r in related.split(",") if r.strip()]
    if not related_ids:
        click.echo("No related article IDs provided.")
        return

    try:
        result = service.add_related_section(article_id, related_ids)
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    if result.get("message"):
        click.echo(result["message"])
        return

    click.echo(f"\nAdded Related Articles section ({result['placement']})")
    click.echo(f"Linked {result['articles_linked']} article(s):")
    for title in result.get("related_articles", []):
        click.echo(f"  -> {title}")


# =========================================================================
# STATUS & ANALYTICS (Phase 6)
# =========================================================================

@seo_group.command(name="status")
@click.option("--brand", "brand_slug", help="Brand slug")
@click.option("--project-id", help="Project ID")
@click.option("--org-id", help="Organization ID (defaults to env)")
def show_status(brand_slug: str, project_id: str, org_id: str):
    """Show SEO pipeline status and dashboard summary."""
    from viraltracker.services.seo_pipeline.services.seo_analytics_service import SEOAnalyticsService
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService

    supabase = get_supabase_client()
    org_id = org_id or "all"

    # Resolve project
    if not project_id and brand_slug:
        brand_result = supabase.table("brands").select("id").eq("slug", brand_slug).execute()
        if not brand_result.data:
            click.echo(f"Brand '{brand_slug}' not found")
            return
        brand_id = brand_result.data[0]["id"]
        project_service = SEOProjectService(supabase)
        projects = project_service.list_projects(org_id, brand_id=brand_id)
        if not projects:
            click.echo(f"No SEO projects for brand '{brand_slug}'")
            return
        project_id = projects[0]["id"]
        click.echo(f"Project: {projects[0]['name']}")
    elif not project_id:
        click.echo("Provide --brand or --project-id")
        return

    analytics = SEOAnalyticsService(supabase)
    dashboard = analytics.get_project_dashboard(project_id, org_id)

    articles = dashboard["articles"]
    keywords = dashboard["keywords"]
    links = dashboard["links"]

    click.echo(f"\nSEO Dashboard:")
    click.echo(f"  Articles: {articles['total']} total, {articles['published']} published")
    if articles["status_counts"]:
        for status, count in sorted(articles["status_counts"].items()):
            click.echo(f"    [{status}]: {count}")

    click.echo(f"\n  Keywords: {keywords['total']} total")
    if keywords["status_counts"]:
        for status, count in sorted(keywords["status_counts"].items()):
            click.echo(f"    [{status}]: {count}")

    click.echo(f"\n  Internal Links: {links['total']} total")
    click.echo(f"    Suggested: {links['suggested']} | Implemented: {links['implemented']}")
