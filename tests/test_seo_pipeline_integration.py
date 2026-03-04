"""
SEO Pipeline Integration Tests — exercises real business logic per phase.

Unlike the unit tests (test_seo_pipeline_graph.py) which mock entire service classes,
these tests let real service code run and only mock true external dependencies:
Supabase, HTTP clients, Anthropic API.

Test structure:
  Phase 1: State round-trip (no mocks)
  Phase 2: Keyword Discovery — variations, filtering, dedup
  Phase 3: Competitor Analysis — HTML parsing, Flesch, winning formula
  Phase 4: Content Generation — prompt building with templates
  Phase 5a: QA Validation — all 10 checks
  Phase 5b: CMS Publisher — markdown→HTML, payload, slug generation
  Phase 6a: Interlinking — Jaccard, anchors, link insertion
  Phase 6b: Article Tracking — status transitions
  Phase 7: End-to-end pipeline graph run
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint
from viraltracker.services.seo_pipeline.models import ArticleStatus


# =============================================================================
# FIXED TEST DATA
# =============================================================================

FIXED_UUIDS = {
    "project": UUID("11111111-1111-1111-1111-111111111111"),
    "brand": UUID("22222222-2222-2222-2222-222222222222"),
    "org": UUID("33333333-3333-3333-3333-333333333333"),
    "keyword": UUID("44444444-4444-4444-4444-444444444444"),
    "author": UUID("55555555-5555-5555-5555-555555555555"),
    "article": UUID("66666666-6666-6666-6666-666666666666"),
    "persona": UUID("77777777-7777-7777-7777-777777777777"),
    "cms_article": UUID("88888888-8888-8888-8888-888888888888"),
}

COMPETITOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Best Gaming PCs 2026 - Ultimate Buyer's Guide</title>
  <meta name="description" content="Find the best gaming PC for your budget in 2026. Expert reviews and comparisons of top builds.">
  <script type="application/ld+json">
  {"@type": "Article", "headline": "Best Gaming PCs 2026", "author": {"@type": "Person", "name": "Jane Doe"}}
  </script>
</head>
<body>
<nav><a href="/">Home</a></nav>
<div class="table-of-contents">
  <a href="#intro">Introduction</a>
  <a href="#builds">Top Builds</a>
</div>
<div class="breadcrumb"><a href="/">Home</a> &gt; <a href="/gaming">Gaming</a></div>
<h1>Best Gaming PCs 2026</h1>
<p>Building a gaming PC in 2026 is easier than ever. This comprehensive guide covers everything from budget builds to ultra premium setups. Whether you are a casual gamer or an esports competitor, we have the right build for you. Gaming has evolved dramatically in recent years with new hardware and technologies.</p>
<h2>Budget Builds Under $1000</h2>
<p>The entry-level gaming market has exploded with options. Modern GPUs deliver incredible performance at reasonable prices, making gaming accessible to everyone.</p>
<p>Here are the top picks for budget conscious gamers who want solid performance without breaking the bank.</p>
<h2>Mid-Range Builds ($1000-$2000)</h2>
<p>For most gamers, the sweet spot is the mid-range category. These builds offer 1440p gaming at high frame rates.</p>
<h3>AMD vs Intel in 2026</h3>
<p>The CPU wars continue with AMD and Intel trading blows. Both offer compelling options for gaming builds.</p>
<h2 class="faq">Frequently Asked Questions</h2>
<div itemtype="https://schema.org/FAQPage">
<p><strong>Q: How much should I spend?</strong></p>
<p>A: For 1080p gaming, $800-1000. For 1440p, $1500-2000.</p>
</div>
<h2>Conclusion</h2>
<p>Choose the build that fits your budget and gaming goals. Happy building!</p>
<div class="author" itemprop="author">Written by <a href="/authors/jane" rel="author">Jane Doe</a></div>
<table><tr><th>Build</th><th>Price</th></tr><tr><td>Budget</td><td>$800</td></tr></table>
<img src="/images/gaming-pc.jpg" alt="Gaming PC Build">
<img src="/images/gpu.jpg" alt="Latest GPU">
<img src="/images/decorative.jpg">
<iframe src="https://youtube.com/embed/abc123"></iframe>
<a href="https://en.wikipedia.org/wiki/Gaming_PC">Wikipedia: Gaming PC</a>
<a href="https://reddit.com/r/buildapc">r/buildapc</a>
<a href="https://example.edu/research">Research paper</a>
<a href="/internal-link-1">Related guide</a>
<a href="/internal-link-2">Another article</a>
<a href="/internal-link-3">More reading</a>
<button>Subscribe</button>
<a href="/signup">Get Started Free</a>
<footer>Footer content</footer>
</body>
</html>"""

PASSING_ARTICLE_MD = """# Best Gaming PC Build Guide 2026

Looking for the best gaming pc build guide? This comprehensive resource covers everything you need to build the perfect gaming rig in 2026. We have put together all the latest recommendations and expert advice.

## Why Build Your Own Gaming PC

Building your own gaming PC saves money and gives you complete control over performance. Many gamers prefer custom builds because they can optimize for their specific needs and upgrade components individually over time. The satisfaction of assembling your own machine and seeing it boot for the first time is something every gamer should experience at least once.

The gaming PC market has evolved significantly, with better components available at every price point. Whether you are a casual gamer or competitive player, a custom build delivers the best value. Prebuilt systems often include cheaper components that manufacturers use to increase their profit margins, while custom builds let you allocate your budget where it matters most.

## Choosing the Right Components

Selecting components is the most important step. Start with your budget and work backwards from the GPU, which determines gaming performance more than any other part. A balanced build ensures no single component bottlenecks the rest of your system.

### GPU Selection

Modern GPUs from AMD and NVIDIA offer incredible performance at various price points. For 1080p gaming, a mid-range card delivers smooth framerates in all modern titles without breaking the bank. For 4K gaming, invest in a flagship model for the best experience with high refresh rates. Consider future game requirements when choosing your GPU, as newer titles continue to push hardware demands higher each year.

The current generation of graphics cards provides excellent ray tracing performance alongside traditional rasterization. Look for models with at least 8GB of VRAM for comfortable gaming at higher resolutions. Memory bandwidth and clock speeds also play important roles in overall performance.

### CPU and Motherboard

Match your CPU to your GPU tier to avoid bottlenecks. An overpowered CPU with a weak GPU wastes money and does not improve gaming performance. Both AMD Ryzen and Intel Core processors offer excellent gaming performance in 2026 with their latest architectures.

When selecting a motherboard, ensure it supports the features you need including the correct socket type, sufficient memory slots, and adequate expansion options. Future upgrade paths should factor into your motherboard decision since it determines which CPUs you can use.

### Memory and Storage

For gaming in 2026, 32GB of DDR5 RAM is the sweet spot. Games are increasingly memory hungry, and having extra RAM ensures smooth multitasking while gaming. Choose memory kits rated at your platform's optimal speed for the best performance.

Storage has become incredibly affordable. A 1TB NVMe SSD should be your primary drive for the operating system and frequently played games. Add a secondary 2TB drive for your game library and media files.

## Building Step by Step

Follow these steps for a smooth build process. Take your time and handle components carefully. Static electricity can damage sensitive electronics so ground yourself before handling any parts.

1. Install the CPU and cooler on the motherboard outside the case
2. Insert RAM into the correct slots following the manual's recommended configuration
3. Mount the motherboard in the case using all the provided standoffs
4. Install the GPU in the primary PCIe slot and secure it with screws
5. Connect all power cables from the PSU including the 24-pin motherboard and CPU power

## Performance Optimization

After building, optimize your system for the best gaming experience. Update all drivers to their latest versions and configure your BIOS settings for optimal performance. Enable XMP profiles for your memory to run at rated speeds.

![Gaming PC Setup](https://example.com/images/setup.jpg)

For more details, check our [GPU comparison guide](/articles/gpu-comparison-2026) and [cooling solutions article](/articles/best-cpu-coolers).

## Frequently Asked Questions

**How much should I spend on a gaming PC?**
Budget $800 to $1500 for a solid 1080p gaming build. Spend $2000 or more for 4K gaming at high refresh rates.

**Is it cheaper to build or buy?**
Building is almost always cheaper and gives you better components for the same price. You also get the knowledge to troubleshoot and upgrade later.

## Conclusion

Building a gaming PC in 2026 is rewarding and cost effective. Start with a clear budget, choose components wisely, and enjoy the process. The gaming community is always happy to help newcomers get started with their first build.
"""

FAILING_ARTICLE_MD = """Just a short article about gaming PCs. Not much to say really.

You should buy a good gaming PC \u2014 it makes a big difference \u2014 trust me.

Everyone knows gaming is fun and building is cool too."""

BRAND_CONTEXT = {
    "brand_basics": {
        "name": "TechGamer Pro",
        "description": "Premium gaming hardware and guides for serious gamers.",
    },
    "product": {
        "name": "TechGamer Build Kits",
        "target_audience": "PC gaming enthusiasts aged 18-35",
        "key_benefits": [
            "Pre-selected compatible components",
            "Step-by-step build guides",
            "Lifetime support",
        ],
    },
}


# =============================================================================
# HELPERS
# =============================================================================

def _make_full_state(**overrides) -> SEOPipelineState:
    """Factory for a fully-populated pipeline state."""
    defaults = dict(
        project_id=FIXED_UUIDS["project"],
        brand_id=FIXED_UUIDS["brand"],
        organization_id=FIXED_UUIDS["org"],
        seed_keywords=["gaming pc", "build gaming computer"],
        min_word_count=3,
        max_word_count=10,
        generation_mode="cli",
        discovered_keywords=[
            {"keyword": "best gaming pc 2026", "word_count": 4, "seed_keyword": "gaming pc", "found_in_seeds": 2},
            {"keyword": "how to build a gaming pc", "word_count": 6, "seed_keyword": "build gaming computer", "found_in_seeds": 1},
        ],
        selected_keyword_id=FIXED_UUIDS["keyword"],
        selected_keyword="best gaming pc build guide",
        competitor_urls=["https://example.com/1", "https://example.com/2"],
        competitor_results=[
            {"url": "https://example.com/1", "word_count": 2500, "h2_count": 5},
        ],
        winning_formula={"target_word_count": 2800, "avg_h2_count": 5},
        author_id=FIXED_UUIDS["author"],
        article_id=FIXED_UUIDS["article"],
        phase_a_output="# Outline\n## Section 1\n## Section 2",
        phase_b_output="Full draft text here...",
        phase_c_output="SEO-optimized article...",
        qa_result={"passed": True, "errors": 0},
        published_url="https://example.com/blog/best-gaming-pc",
        cms_article_id="shopify-12345",
        current_step="complete",
        current_checkpoint=None,
        awaiting_human=False,
        human_input=None,
        error=None,
        error_step=None,
        retry_count=0,
        max_retries=3,
        steps_completed=[
            "keyword_discovery", "keyword_selection", "competitor_analysis",
            "content_phase_a", "outline_review", "content_phase_b",
            "content_phase_c", "article_review", "qa_validation",
            "qa_approval", "publishing", "interlinking",
        ],
        started_at="2026-03-02T10:00:00+00:00",
        completed_at="2026-03-02T12:00:00+00:00",
    )
    defaults.update(overrides)
    return SEOPipelineState(**defaults)


def _make_mock_supabase():
    """Create a chainable mock Supabase client."""
    mock = MagicMock()

    # Make table().select().eq()...execute() chainable
    table_mock = MagicMock()
    mock.table.return_value = table_mock
    for method in ["select", "insert", "update", "delete", "eq", "neq", "order", "limit"]:
        getattr(table_mock, method).return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[])

    return mock


# =============================================================================
# PHASE 1: STATE ROUND-TRIP
# =============================================================================

class TestPhase1StateRoundtrip:
    """State serialization — no mocks needed, pure in-memory logic."""

    def test_full_state_to_dict_roundtrip(self):
        """All 25+ fields survive to_dict() → from_dict()."""
        state = _make_full_state()
        d = state.to_dict()
        restored = SEOPipelineState.from_dict(d)

        assert restored.project_id == state.project_id
        assert restored.brand_id == state.brand_id
        assert restored.organization_id == state.organization_id
        assert restored.seed_keywords == state.seed_keywords
        assert restored.selected_keyword == state.selected_keyword
        assert restored.selected_keyword_id == state.selected_keyword_id
        assert restored.competitor_urls == state.competitor_urls
        assert restored.winning_formula == state.winning_formula
        assert restored.author_id == state.author_id
        assert restored.article_id == state.article_id
        assert restored.phase_a_output == state.phase_a_output
        assert restored.phase_b_output == state.phase_b_output
        assert restored.phase_c_output == state.phase_c_output
        assert restored.qa_result == state.qa_result
        assert restored.published_url == state.published_url
        assert restored.cms_article_id == state.cms_article_id
        assert restored.steps_completed == state.steps_completed
        assert restored.started_at == state.started_at
        assert restored.completed_at == state.completed_at
        assert restored.error is None
        assert restored.generation_mode == "cli"

    def test_json_serialization_roundtrip(self):
        """State survives JSON encode → decode (simulating DB storage)."""
        state = _make_full_state(
            current_checkpoint=SEOHumanCheckpoint.OUTLINE_REVIEW,
            awaiting_human=True,
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored_dict = json.loads(json_str)
        restored = SEOPipelineState.from_dict(restored_dict)

        assert restored.project_id == FIXED_UUIDS["project"]
        assert restored.current_checkpoint == SEOHumanCheckpoint.OUTLINE_REVIEW
        assert restored.awaiting_human is True
        assert isinstance(restored.article_id, UUID)

    def test_checkpoint_enum_preserved(self):
        """SEOHumanCheckpoint enum values round-trip correctly."""
        for checkpoint in SEOHumanCheckpoint:
            state = _make_full_state(current_checkpoint=checkpoint)
            d = state.to_dict()
            restored = SEOPipelineState.from_dict(d)
            assert restored.current_checkpoint == checkpoint


# =============================================================================
# PHASE 2: KEYWORD DISCOVERY
# =============================================================================

class TestPhase2KeywordDiscovery:
    """Keyword discovery — mock httpx and asyncio.sleep, real variations/filtering."""

    def test_generate_variations_produces_150_plus(self):
        """16 modifiers × 10 suffixes minus dedup ≥ 150 unique queries per seed."""
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
        service = KeywordDiscoveryService()

        variations = service._generate_variations("gaming pc")
        assert len(variations) >= 150
        # All unique
        assert len(variations) == len(set(v.lower() for v in variations))
        # Contains the raw seed
        assert "gaming pc" in variations

    def test_filter_keyword_edge_cases(self):
        """Filter rejects invalid chars, too short/long, empty strings."""
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
        service = KeywordDiscoveryService()

        # Valid keywords
        assert service._filter_keyword("best gaming pc 2026", 3, 10) == "best gaming pc 2026"
        assert service._filter_keyword("how to build gaming pc", 3, 10) == "how to build gaming pc"
        assert service._filter_keyword("  UPPER Case  ", 2, 5) == "upper case"

        # Too few words
        assert service._filter_keyword("gaming", 3, 10) is None
        # Too many words
        assert service._filter_keyword("one two three four five six seven eight nine ten eleven", 3, 10) is None
        # Invalid characters
        assert service._filter_keyword("gaming pc $500", 3, 10) is None
        assert service._filter_keyword("gaming pc <script>", 3, 10) is None
        # Empty
        assert service._filter_keyword("", 3, 10) is None
        assert service._filter_keyword("   ", 3, 10) is None

    @pytest.mark.asyncio
    async def test_full_discover_with_mock_autocomplete(self):
        """discover_keywords with mock HTTP → real filtering → real dedup."""
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService

        mock_supabase = _make_mock_supabase()
        service = KeywordDiscoveryService(supabase_client=mock_supabase)

        # Mock the autocomplete to return different suggestions per query
        call_count = [0]
        async def mock_query(client, query):
            call_count[0] += 1
            q = query.lower()
            # Return relevant suggestions based on query
            if "gaming" in q:
                return [
                    "best gaming pc build guide",
                    "gaming pc under 1000 dollars",
                    "gaming",  # too short, should be filtered
                    "gaming pc $$$ deals",  # invalid chars
                ]
            return ["how to build a custom gaming computer"]

        with patch.object(service, "_query_autocomplete", side_effect=mock_query):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await service.discover_keywords(
                    project_id=str(FIXED_UUIDS["project"]),
                    seeds=["gaming pc"],
                    min_word_count=3,
                    max_word_count=10,
                )

        assert result["total_keywords"] > 0
        keywords = result["keywords"]
        # All keywords should pass filters
        for kw in keywords:
            assert kw["word_count"] >= 3
            assert kw["word_count"] <= 10

    @pytest.mark.asyncio
    async def test_cross_seed_frequency(self):
        """Same keyword from 2 seeds → found_in_seeds=2."""
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService

        mock_supabase = _make_mock_supabase()
        service = KeywordDiscoveryService(supabase_client=mock_supabase)

        # Both seeds return the same keyword
        async def mock_query(client, query):
            return ["best gaming pc build guide 2026"]

        with patch.object(service, "_query_autocomplete", side_effect=mock_query):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await service.discover_keywords(
                    project_id=str(FIXED_UUIDS["project"]),
                    seeds=["gaming pc", "build gaming computer"],
                    min_word_count=3,
                    max_word_count=10,
                )

        # The shared keyword should have found_in_seeds >= 2
        keywords = result["keywords"]
        shared = [k for k in keywords if k["keyword"] == "best gaming pc build guide 2026"]
        assert len(shared) == 1
        assert shared[0]["found_in_seeds"] >= 2


# =============================================================================
# PHASE 3: COMPETITOR ANALYSIS
# =============================================================================

class TestPhase3CompetitorAnalysis:
    """Competitor analysis — mock web scraping, real HTML parsing and formula."""

    def test_parse_html_metrics(self):
        """_parse_html_metrics extracts 20+ metrics from realistic HTML."""
        from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService
        service = CompetitorAnalysisService()

        metrics = service._parse_html_metrics(COMPETITOR_HTML, "https://example.com/article")

        assert metrics["title"] == "Best Gaming PCs 2026 - Ultimate Buyer's Guide"
        assert "best gaming PC" in metrics["meta_description"]
        assert metrics["h1_count"] == 1
        assert metrics["h2_count"] >= 4  # Budget, Mid-Range, FAQ, Conclusion
        assert metrics["h3_count"] >= 1  # AMD vs Intel
        assert metrics["word_count"] > 50
        assert metrics["paragraph_count"] >= 3
        assert metrics["has_toc"] is True
        assert metrics["has_faq"] is True
        assert metrics["has_schema"] is True
        assert metrics["has_author"] is True
        assert metrics["has_breadcrumbs"] is True
        assert "Article" in metrics["schema_types"]
        assert metrics["image_count"] >= 3
        assert metrics["images_with_alt"] >= 2  # 2 have alt, 1 doesn't
        assert metrics["internal_link_count"] >= 3
        assert metrics["external_link_count"] >= 3
        assert metrics["video_embeds"] >= 1
        assert metrics["cta_count"] >= 2  # button + "Get Started" link
        assert metrics["has_tables"] is True
        assert metrics["table_count"] >= 1

    def test_flesch_scoring(self):
        """Flesch scores at known readability levels."""
        from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService

        # Simple text (short sentences, simple words) → high score
        simple = "The cat sat. The dog ran. The bird flew. It was fun."
        simple_score = CompetitorAnalysisService._calculate_flesch(simple)
        assert simple_score > 70, f"Simple text should score >70, got {simple_score}"

        # Complex text (long sentences, complex words) → lower score
        complex_text = (
            "The implementation of sophisticated computational methodologies "
            "facilitates the comprehensive optimization of multifaceted algorithmic "
            "infrastructure throughout enterprise organizational hierarchies."
        )
        complex_score = CompetitorAnalysisService._calculate_flesch(complex_text)
        assert complex_score < 40, f"Complex text should score <40, got {complex_score}"

        # Empty text
        assert CompetitorAnalysisService._calculate_flesch("") == 0.0

    def test_calculate_winning_formula(self):
        """_calculate_winning_formula from 3 competitor dicts → verify stats & opportunities."""
        from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService
        service = CompetitorAnalysisService()

        results = [
            {
                "word_count": 2000, "h2_count": 5, "h3_count": 3,
                "paragraph_count": 15, "flesch_reading_ease": 65.0,
                "internal_link_count": 8, "external_link_count": 3,
                "image_count": 4, "cta_count": 2,
                "has_schema": True, "has_faq": True,
                "has_toc": True, "has_author": True, "has_breadcrumbs": True,
            },
            {
                "word_count": 2500, "h2_count": 6, "h3_count": 4,
                "paragraph_count": 20, "flesch_reading_ease": 60.0,
                "internal_link_count": 10, "external_link_count": 5,
                "image_count": 6, "cta_count": 3,
                "has_schema": False, "has_faq": False,
                "has_toc": False, "has_author": False, "has_breadcrumbs": False,
            },
            {
                "word_count": 3000, "h2_count": 7, "h3_count": 5,
                "paragraph_count": 25, "flesch_reading_ease": 55.0,
                "internal_link_count": 12, "external_link_count": 4,
                "image_count": 8, "cta_count": 4,
                "has_schema": True, "has_faq": True,
                "has_toc": True, "has_author": True, "has_breadcrumbs": True,
            },
        ]

        formula = service._calculate_winning_formula(results)

        assert formula["competitor_count"] == 3
        assert formula["avg_word_count"] == 2500
        assert formula["target_word_count"] == 2800  # 2500 * 1.12 = 2800
        assert formula["median_word_count"] == 2500
        assert formula["min_word_count"] == 2000
        assert formula["max_word_count"] == 3000
        assert formula["avg_flesch_score"] == 60.0
        assert formula["pct_with_schema"] == pytest.approx(66.7, abs=0.1)
        assert formula["pct_with_faq"] == pytest.approx(66.7, abs=0.1)
        assert formula["pct_with_toc"] == pytest.approx(66.7, abs=0.1)
        assert isinstance(formula["opportunities"], list)

    def test_full_analyze_urls(self):
        """Full analyze_urls with mock scraping → real parsing → real formula."""
        from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService

        mock_supabase = _make_mock_supabase()
        mock_scraper = MagicMock()

        # Mock scraping to return our realistic HTML
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.html = COMPETITOR_HTML
        mock_result.markdown = "Some markdown fallback"
        mock_scraper.scrape_url.return_value = mock_result

        service = CompetitorAnalysisService(
            supabase_client=mock_supabase,
            web_scraping_service=mock_scraper,
        )

        result = service.analyze_urls(
            keyword_id=str(FIXED_UUIDS["keyword"]),
            urls=["https://example.com/1", "https://example.com/2"],
        )

        assert result["analyzed_count"] == 2
        assert result["failed_count"] == 0
        assert len(result["results"]) == 2
        assert "winning_formula" in result
        assert result["winning_formula"]["competitor_count"] == 2
        # Both used same HTML so metrics should be identical
        for r in result["results"]:
            assert r["h1_count"] == 1
            assert r["has_schema"] is True


# =============================================================================
# PHASE 4: CONTENT GENERATION
# =============================================================================

class TestPhase4ContentGeneration:
    """Content generation — mock Supabase for author lookup, real template loading & prompt building."""

    def _make_service(self):
        """Create service with mocked external deps."""
        mock_supabase = _make_mock_supabase()
        # Author lookup returns a test author
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "name": "Jane Smith",
                "bio": "Gaming expert and writer.",
                "image_url": "https://example.com/jane.jpg",
                "job_title": "Senior Gaming Editor",
                "author_url": "https://example.com/authors/jane",
                "persona_id": None,
            }]
        )
        from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
        return ContentGenerationService(supabase_client=mock_supabase)

    def test_phase_a_prompt_contains_required_fields(self):
        """Phase A prompt includes keyword, competitor data, brand context, no unresolved placeholders."""
        service = self._make_service()

        prompt = service._build_phase_a_prompt(
            keyword="best gaming pc build guide",
            competitor_data={
                "results": [
                    {"url": "https://example.com/1", "word_count": 2500, "h2_count": 5,
                     "flesch_reading_ease": 65.0, "has_schema": True, "has_faq": True},
                ],
                "winning_formula": {"target_word_count": 2800},
            },
            brand_context=BRAND_CONTEXT,
            author_ctx={"name": "Jane Smith", "voice": "Conversational and expert tone."},
        )

        assert "best gaming pc build guide" in prompt
        assert "https://example.com/1" in prompt
        assert "TechGamer Pro" in prompt
        assert "Jane Smith" in prompt
        assert "Conversational and expert tone" in prompt
        # No unresolved template variables
        import re
        unresolved = re.findall(r'\{[A-Z_]+\}', prompt)
        assert unresolved == [], f"Unresolved template variables: {unresolved}"

    def test_phase_b_prompt_contains_phase_a_output(self):
        """Phase B prompt includes Phase A output, author voice, keyword."""
        service = self._make_service()

        prompt = service._build_phase_b_prompt(
            keyword="best gaming pc build guide",
            phase_a_output="## Section 1: Introduction\n## Section 2: Components",
            brand_context=BRAND_CONTEXT,
            author_ctx={"name": "Jane Smith", "voice": "Write casually."},
        )

        assert "Section 1: Introduction" in prompt
        assert "best gaming pc build guide" in prompt
        assert "Jane Smith" in prompt
        assert "TechGamer Pro" in prompt
        import re
        unresolved = re.findall(r'\{[A-Z_]+\}', prompt)
        assert unresolved == [], f"Unresolved template variables: {unresolved}"

    def test_phase_c_prompt_contains_competitor_stats_and_links(self):
        """Phase C prompt includes internal links, competitor stats, Phase B output."""
        service = self._make_service()

        prompt = service._build_phase_c_prompt(
            keyword="best gaming pc build guide",
            phase_b_output="The full article draft goes here with lots of content.",
            competitor_data={
                "winning_formula": {
                    "target_word_count": 2800,
                    "avg_h2_count": 5,
                    "avg_flesch_score": 65.0,
                    "pct_with_schema": 80.0,
                    "pct_with_faq": 60.0,
                },
            },
            existing_articles=[
                {"title": "GPU Comparison", "published_url": "https://example.com/gpu"},
                {"title": "Cooling Guide", "keyword": "cpu coolers"},
            ],
            brand_context=BRAND_CONTEXT,
            author_ctx={
                "name": "Jane Smith",
                "author_url": "https://example.com/authors/jane",
                "image_url": "https://example.com/jane.jpg",
                "job_title": "Senior Gaming Editor",
                "bio": "Gaming expert.",
            },
        )

        assert "full article draft" in prompt
        assert "best gaming pc build guide" in prompt
        assert "Target word count: 2800" in prompt
        assert "GPU Comparison" in prompt
        assert "https://example.com/gpu" in prompt
        assert "Jane Smith" in prompt
        import re
        unresolved = re.findall(r'\{[A-Z_]+\}', prompt)
        assert unresolved == [], f"Unresolved template variables: {unresolved}"

    def test_author_context_loading_with_defaults(self):
        """Author loading returns defaults when author_id is None."""
        from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
        service = ContentGenerationService(supabase_client=_make_mock_supabase())

        ctx = service._load_author_context(None)
        assert ctx["name"] == "Author"
        assert "voice" in ctx
        assert len(ctx["voice"]) > 10


# =============================================================================
# PHASE 5a: QA VALIDATION
# =============================================================================

class TestPhase5aQAValidation:
    """QA validation — no mocks for run_checks(), pure logic with all 10 checks."""

    def test_passing_article(self):
        """Well-structured article → 0 errors, passed=True."""
        from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
        service = QAValidationService()

        checks = service.run_checks(
            content_markdown=PASSING_ARTICLE_MD,
            keyword="best gaming pc build guide",
            seo_title="Best Gaming PC Build Guide 2026 - Complete Resource",  # 52 chars
            meta_description=(
                "Build the perfect gaming PC in 2026 with our comprehensive guide. "
                "Expert picks for components at every budget level plus step-by-step instructions."
            ),  # ~155 chars
            schema_markup={"@type": "Article", "headline": "Best Gaming PC Build Guide"},
        )

        errors = [c for c in checks if not c.passed and c.severity == "error"]
        assert len(errors) == 0, f"Expected 0 errors, got: {[c.message for c in errors]}"

        # Check that key checks passed
        check_names = {c.name: c.passed for c in checks}
        assert check_names.get("word_count") is True
        assert check_names.get("heading_structure") is True
        assert check_names.get("schema_markup") is True

    def test_failing_article(self):
        """Poorly structured article → multiple errors, passed=False."""
        from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
        service = QAValidationService()

        checks = service.run_checks(
            content_markdown=FAILING_ARTICLE_MD,
            keyword="best gaming pc build guide",
            seo_title="",  # No title
            meta_description="",  # No meta
            schema_markup=None,  # No schema
        )

        errors = [c for c in checks if not c.passed and c.severity == "error"]
        warnings = [c for c in checks if not c.passed and c.severity == "warning"]

        # Should have multiple failures
        assert len(errors) >= 3, f"Expected ≥3 errors, got {len(errors)}: {[c.name for c in errors]}"
        assert len(warnings) >= 1, f"Expected ≥1 warning, got: {len(warnings)}"

        failed_names = {c.name for c in errors}
        assert "word_count" in failed_names  # < 500 words
        assert "title_length" in failed_names  # empty title
        assert "meta_description" in failed_names  # empty meta

    def test_warning_vs_error_distinction(self):
        """Warnings (em dashes, no images) vs errors (no title) are distinguished."""
        from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
        service = QAValidationService()

        checks = service.run_checks(
            content_markdown=FAILING_ARTICLE_MD,
            keyword="best gaming pc build guide",
            seo_title="",
            meta_description="",
        )

        # em_dashes should be a warning (content has \u2014)
        em_check = next((c for c in checks if c.name == "em_dashes"), None)
        assert em_check is not None
        assert em_check.passed is False
        assert em_check.severity == "warning"

        # title_length should be an error (empty)
        title_check = next((c for c in checks if c.name == "title_length"), None)
        assert title_check is not None
        assert title_check.passed is False
        assert title_check.severity == "error"


# =============================================================================
# PHASE 5b: CMS PUBLISHER
# =============================================================================

class TestPhase5bCMSPublisher:
    """CMS publisher — no mocks needed, pure transformation logic."""

    def test_markdown_to_html(self):
        """_markdown_to_html strips frontmatter/schema, converts remainder."""
        from viraltracker.services.seo_pipeline.services.cms_publisher_service import ShopifyPublisher

        md = """---
title: Test Article
---

# My Article Title

Some paragraph text with **bold** and [a link](https://example.com).

## Section Two

More content here.

## Schema Markup
```json
{"@type": "Article"}
```

<!-- Internal comment -->
"""
        html = ShopifyPublisher._markdown_to_html(md)

        # Should contain converted headings and paragraphs
        assert "<h1>" in html
        assert "My Article Title" in html
        assert "<h2>" in html
        assert "Section Two" in html
        assert "<strong>bold</strong>" in html
        assert 'href="https://example.com"' in html

        # Should NOT contain frontmatter or schema sections
        assert "title: Test Article" not in html
        assert '"@type": "Article"' not in html
        assert "<!-- Internal comment -->" not in html

    def test_build_article_payload(self):
        """_build_article_payload produces correct Shopify structure + metafields."""
        from viraltracker.services.seo_pipeline.services.cms_publisher_service import ShopifyPublisher

        publisher = ShopifyPublisher(
            store_domain="test.myshopify.com",
            access_token="test-token",
            blog_id="12345",
        )

        article_data = {
            "title": "Best Gaming PCs 2026",
            "body_html": "<h1>Best Gaming PCs</h1><p>Content here.</p>",
            "author": "Jane Smith",
            "seo_title": "Best Gaming PCs 2026 - Expert Guide",
            "meta_description": "Expert guide to gaming PCs.",
            "keyword": "best gaming pc 2026",
            "schema_markup": {"@type": "Article"},
            "tags": "gaming, pc, build",
            "hero_image_url": "https://example.com/hero.jpg",
        }

        payload = publisher._build_article_payload(article_data, draft=True)

        article = payload["article"]
        assert article["title"] == "Best Gaming PCs 2026"
        assert article["author"] == "Jane Smith"
        assert article["handle"] == "best-gaming-pc-2026"
        assert article["published"] is False
        assert article["tags"] == "gaming, pc, build"
        assert article["image"]["src"] == "https://example.com/hero.jpg"
        assert "<h1>" in article["body_html"]

        # Check metafields
        metafields = article["metafields"]
        title_meta = next(m for m in metafields if m["key"] == "title_tag")
        assert title_meta["value"] == "Best Gaming PCs 2026 - Expert Guide"
        desc_meta = next(m for m in metafields if m["key"] == "description_tag")
        assert desc_meta["value"] == "Expert guide to gaming PCs."
        schema_meta = next(m for m in metafields if m["key"] == "schema_json")
        assert '"@type"' in schema_meta["value"]

    def test_generate_handle(self):
        """_generate_handle produces URL-safe slugs from various inputs."""
        from viraltracker.services.seo_pipeline.services.cms_publisher_service import ShopifyPublisher

        assert ShopifyPublisher._generate_handle("Best Gaming PCs 2026") == "best-gaming-pcs-2026"
        assert ShopifyPublisher._generate_handle("How to Build a PC!") == "how-to-build-a-pc"
        assert ShopifyPublisher._generate_handle("  Multiple   Spaces  ") == "multiple-spaces"
        assert ShopifyPublisher._generate_handle("Special $#@! Characters") == "special-characters"
        assert ShopifyPublisher._generate_handle("already-a-slug") == "already-a-slug"


# =============================================================================
# PHASE 6a: INTERLINKING
# =============================================================================

class TestPhase6aInterlinking:
    """Interlinking — mock Supabase for article lookups, real Jaccard/anchors/insertion."""

    def test_jaccard_similarity_ranking(self):
        """Jaccard similarity ranks 5 keywords correctly."""
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        source = "best gaming pc build guide"

        candidates = [
            "best gaming pc 2026",           # high overlap
            "gaming pc build tips",          # medium overlap
            "how to build a pc",             # lower overlap
            "laptop buying guide",           # minimal overlap
            "cooking recipes for beginners",  # no overlap
        ]

        scores = []
        for candidate in candidates:
            score = InterlinkingService._jaccard_similarity(source, candidate)
            scores.append((candidate, score))

        # Verify ordering (highest first)
        scores.sort(key=lambda x: x[1], reverse=True)
        assert scores[0][0] == "best gaming pc 2026"
        assert scores[-1][0] == "cooking recipes for beginners"
        assert scores[-1][1] == 0.0

    def test_generate_anchor_texts(self):
        """Anchor text generation produces variations, strips 'how to'."""
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        anchors = InterlinkingService._generate_anchor_texts("how to build gaming pc")
        assert "how to build gaming pc" in anchors
        assert "build gaming pc" in anchors  # "how to" stripped
        assert any("learn more" in a for a in anchors)
        assert all(len(a) > 3 for a in anchors)

        # Keyword without "how to"
        anchors2 = InterlinkingService._generate_anchor_texts("best gaming monitors 2026")
        assert "best gaming monitors 2026" in anchors2

    def test_insert_links_in_paragraphs(self):
        """_insert_links_in_paragraphs inserts <a> tags in <p> tags correctly."""
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        html = (
            "<h1>Article Title</h1>"
            "<p>Check out the best gaming pc builds for 2026 in this guide.</p>"
            "<p>This paragraph already has <a href='/other'>a link</a> so skip it.</p>"
            "<p>Another paragraph about gaming monitors and setups.</p>"
            "<h2>Related Articles</h2>"
            "<p>This is after related articles, should not be linked.</p>"
        )

        result = InterlinkingService._insert_links_in_paragraphs(
            html,
            patterns=["best gaming pc builds", "gaming monitors"],
            target_url="/articles/target",
        )

        assert result["count"] == 2  # First and third paragraphs
        assert '<a href="/articles/target">' in result["html"]
        # Second paragraph (with existing link) should be unchanged
        assert 'already has <a href=' in result["html"]

    def test_full_suggest_links(self):
        """Full suggest_links with mock DB → verify ordering by similarity."""
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

        mock_supabase = _make_mock_supabase()

        # Source article
        source_article = {
            "id": str(FIXED_UUIDS["article"]),
            "keyword": "best gaming pc build guide",
            "project_id": str(FIXED_UUIDS["project"]),
        }

        # Target articles
        target_articles = [
            {"id": "t1", "keyword": "best gaming pc 2026", "published_url": "https://example.com/1", "title": "A"},
            {"id": "t2", "keyword": "laptop buying guide", "published_url": "https://example.com/2", "title": "B"},
            {"id": "t3", "keyword": "gaming pc build tips", "published_url": "https://example.com/3", "title": "C"},
        ]

        # Configure mock returns
        call_count = [0]
        def mock_execute():
            call_count[0] += 1
            result = MagicMock()
            # First call: source article, second: project articles
            if call_count[0] == 1:
                result.data = [source_article]
            elif call_count[0] == 2:
                result.data = target_articles
            else:
                result.data = []
            return result

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute = mock_execute
        mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.execute = lambda: MagicMock(data=target_articles)

        service = InterlinkingService(supabase_client=mock_supabase)

        result = service.suggest_links(
            article_id=str(FIXED_UUIDS["article"]),
            min_similarity=0.1,
            max_suggestions=5,
            save=False,
        )

        assert result["suggestion_count"] >= 2  # "laptop" has low overlap, may be filtered
        # First suggestion should have highest similarity
        if result["suggestions"]:
            top = result["suggestions"][0]
            assert top["similarity"] >= result["suggestions"][-1]["similarity"]


# =============================================================================
# PHASE 6b: ARTICLE TRACKING
# =============================================================================

class TestPhase6bArticleTracking:
    """Article tracking — mock Supabase, real status transition validation."""

    def _make_service(self, current_status="draft"):
        """Create service with a mock article at given status."""
        from viraltracker.services.seo_pipeline.services.article_tracking_service import ArticleTrackingService

        mock_supabase = _make_mock_supabase()
        # get_article returns article with given status
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": str(FIXED_UUIDS["article"]), "status": current_status}]
        )
        # update returns updated article
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": str(FIXED_UUIDS["article"]), "status": "new_status"}]
        )

        return ArticleTrackingService(supabase_client=mock_supabase)

    def test_full_lifecycle(self):
        """Valid transitions through the complete article lifecycle."""
        from viraltracker.services.seo_pipeline.services.article_tracking_service import VALID_TRANSITIONS

        # Walk through the full happy path
        lifecycle = [
            "draft", "outline_complete", "draft_complete", "optimized",
            "qa_pending", "qa_passed", "publishing", "published", "archived",
        ]

        for i in range(len(lifecycle) - 1):
            current = lifecycle[i]
            target = lifecycle[i + 1]
            valid_targets = VALID_TRANSITIONS.get(current, [])
            assert target in valid_targets, (
                f"Transition {current} → {target} not in valid targets: {valid_targets}"
            )

    def test_invalid_transition_rejected(self):
        """Invalid transitions raise ValueError."""
        service = self._make_service(current_status="draft")

        with pytest.raises(ValueError, match="Invalid status transition"):
            service.update_status(str(FIXED_UUIDS["article"]), "published")

    def test_force_override(self):
        """Force=True bypasses transition validation."""
        service = self._make_service(current_status="draft")

        # This would normally fail: draft → published
        result = service.update_status(str(FIXED_UUIDS["article"]), "published", force=True)
        assert result is not None


# =============================================================================
# PHASE 7: END-TO-END PIPELINE
# =============================================================================

# Patch paths — services are imported inside run() from their source modules
KW_DISCOVERY_SVC = "viraltracker.services.seo_pipeline.services.keyword_discovery_service.KeywordDiscoveryService"
COMPETITOR_SVC = "viraltracker.services.seo_pipeline.services.competitor_analysis_service.CompetitorAnalysisService"
CONTENT_GEN_SVC = "viraltracker.services.seo_pipeline.services.content_generation_service.ContentGenerationService"
QA_SVC = "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
CMS_SVC = "viraltracker.services.seo_pipeline.services.cms_publisher_service.CMSPublisherService"
INTERLINK_SVC = "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"
PROJECT_SVC = "viraltracker.services.seo_pipeline.services.seo_project_service.SEOProjectService"


class TestEndToEndPipeline:
    """Full graph run with mocked services, real nodes and state mutations."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_checkpoints(self):
        """Run graph → KEYWORD_SELECTION → resume → OUTLINE_REVIEW → resume → ARTICLE_REVIEW → resume → QA_APPROVAL → resume → complete."""
        from viraltracker.services.seo_pipeline.orchestrator import (
            seo_pipeline_graph,
            CHECKPOINT_TO_NODE,
        )
        from viraltracker.services.seo_pipeline.nodes import (
            KeywordDiscoveryNode,
            KeywordSelectionNode,
        )

        # Create initial state
        state = SEOPipelineState(
            project_id=FIXED_UUIDS["project"],
            brand_id=FIXED_UUIDS["brand"],
            organization_id=FIXED_UUIDS["org"],
            seed_keywords=["gaming pc"],
            generation_mode="cli",
            started_at="2026-03-02T10:00:00+00:00",
        )

        # --- Mock all services ---
        with patch(KW_DISCOVERY_SVC) as MockKWD, \
             patch(COMPETITOR_SVC) as MockComp, \
             patch(CONTENT_GEN_SVC) as MockGen, \
             patch(QA_SVC) as MockQA, \
             patch(CMS_SVC) as MockCMS, \
             patch(INTERLINK_SVC) as MockLink:

            # Keyword Discovery
            kw_service = MockKWD.return_value
            kw_service.discover_keywords = AsyncMock(return_value={
                "total_keywords": 2,
                "keywords": [
                    {"keyword": "best gaming pc 2026", "word_count": 4, "seed_keyword": "gaming pc", "found_in_seeds": 1},
                ],
                "saved_count": 2,
            })

            # Competitor Analysis
            comp_service = MockComp.return_value
            comp_service.analyze_urls = MagicMock(return_value={
                "results": [{"url": "https://example.com/1", "word_count": 2500}],
                "winning_formula": {"target_word_count": 2800},
                "analyzed_count": 1,
                "failed_count": 0,
            })

            # Content Generation
            gen_service = MockGen.return_value
            gen_service.create_article = MagicMock(return_value={
                "id": str(FIXED_UUIDS["article"]),
            })
            gen_service.generate_phase_a = MagicMock(return_value={"content": "# Outline"})
            gen_service.generate_phase_b = MagicMock(return_value={"content": "Full draft"})
            gen_service.generate_phase_c = MagicMock(return_value={"content": "SEO article"})

            # QA
            qa_service = MockQA.return_value
            qa_service.validate_article = MagicMock(return_value={
                "passed": True, "errors": 0, "warnings": 1,
                "checks": [], "failures": [], "warnings": [],
            })

            # CMS Publisher
            cms_service = MockCMS.return_value
            cms_service.publish_article = MagicMock(return_value={
                "published_url": "https://store.example.com/blog/best-gaming-pc",
                "cms_article_id": "shopify-999",
            })

            # Interlinking
            link_service = MockLink.return_value
            link_service.suggest_links = MagicMock(return_value={"suggestion_count": 2})
            link_service.auto_link_article = MagicMock(return_value={"links_added": 1})

            # === RUN 1: Start → pauses at KEYWORD_SELECTION ===
            result1 = await seo_pipeline_graph.run(
                KeywordDiscoveryNode(),
                state=state,
            )
            assert state.current_step == "keyword_selection"
            assert state.awaiting_human is True
            assert state.current_checkpoint == SEOHumanCheckpoint.KEYWORD_SELECTION
            assert "keyword_discovery" in state.steps_completed

            # === RUN 2: Resume with keyword selection → pauses at OUTLINE_REVIEW ===
            state.human_input = {
                "action": "select",
                "keyword_id": str(FIXED_UUIDS["keyword"]),
                "keyword": "best gaming pc 2026",
                "competitor_urls": ["https://example.com/1"],
            }
            result2 = await seo_pipeline_graph.run(
                KeywordSelectionNode(),
                state=state,
            )
            assert state.selected_keyword == "best gaming pc 2026"
            assert state.current_checkpoint == SEOHumanCheckpoint.OUTLINE_REVIEW
            assert state.awaiting_human is True
            assert "competitor_analysis" in state.steps_completed
            assert "content_phase_a" in state.steps_completed

            # === RUN 3: Approve outline → runs Phase B + C → pauses at ARTICLE_REVIEW ===
            from viraltracker.services.seo_pipeline.nodes import OutlineReviewNode
            state.human_input = {"action": "approve"}
            result3 = await seo_pipeline_graph.run(
                OutlineReviewNode(),
                state=state,
            )
            assert state.current_checkpoint == SEOHumanCheckpoint.ARTICLE_REVIEW
            assert "content_phase_b" in state.steps_completed
            assert "content_phase_c" in state.steps_completed

            # === RUN 4: Approve article → QA passes → pauses at QA_APPROVAL ===
            from viraltracker.services.seo_pipeline.nodes import ArticleReviewNode
            state.human_input = {"action": "approve"}
            result4 = await seo_pipeline_graph.run(
                ArticleReviewNode(),
                state=state,
            )
            assert state.current_checkpoint == SEOHumanCheckpoint.QA_APPROVAL
            assert "qa_validation" in state.steps_completed

            # === RUN 5: Approve QA → publish → interlink → complete ===
            from viraltracker.services.seo_pipeline.nodes import QAApprovalNode
            state.human_input = {"action": "approve"}
            result5 = await seo_pipeline_graph.run(
                QAApprovalNode(),
                state=state,
            )

            # Verify final state
            assert state.current_step == "complete"
            assert state.published_url == "https://store.example.com/blog/best-gaming-pc"
            assert state.cms_article_id == "shopify-999"
            assert "publishing" in state.steps_completed
            assert "interlinking" in state.steps_completed
            assert state.completed_at is not None

            # Verify all 13 steps completed
            expected_steps = {
                "keyword_discovery", "keyword_selection", "competitor_analysis",
                "content_phase_a", "outline_review", "content_phase_b",
                "content_phase_c", "article_review", "qa_validation",
                "qa_approval", "image_generation", "publishing", "interlinking",
            }
            assert set(state.steps_completed) == expected_steps
