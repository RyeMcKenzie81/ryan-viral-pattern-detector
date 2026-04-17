"""
Content Generation Service - 3-phase article generation with dual mode support.

Phase A: Research & Outline — deep competitive analysis, unique angle discovery
Phase B: Write (Freedom Mode) — creative article writing with author voice
Phase C: SEO Optimization — layer SEO packaging without changing voice

Supports two execution modes:
- API mode: Direct Anthropic SDK calls, tracks usage via UsageTracker
- CLI mode: Writes assembled prompt to file, user runs externally

Ported from seo-pipeline/generator/ (Node.js).
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from viraltracker.services.seo_pipeline.models import ArticleStatus

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _escape_for_format(text: str) -> str:
    """Escape braces in user-provided text so str.format() doesn't interpret them."""
    if not text:
        return ""
    return text.replace("{", "{{").replace("}", "}}")


class ContentGenerationService:
    """Service for 3-phase SEO article generation."""

    def __init__(
        self,
        supabase_client=None,
        usage_tracker=None,
        anthropic_client=None,
    ):
        self._supabase = supabase_client
        self._usage_tracker = usage_tracker
        self._anthropic = anthropic_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def usage_tracker(self):
        """Lazy-load UsageTracker."""
        if self._usage_tracker is None:
            from viraltracker.services.usage_tracker import UsageTracker
            self._usage_tracker = UsageTracker(self.supabase)
        return self._usage_tracker

    @property
    def anthropic_client(self):
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def generate_phase_a(
        self,
        article_id: str,
        keyword: str = "",
        competitor_data: Optional[Dict[str, Any]] = None,
        brand_context: Optional[Dict[str, Any]] = None,
        author_id: Optional[str] = None,
        mode: str = "api",
        organization_id: Optional[str] = None,
        model: str = "claude-opus-4-7",
        brand_config: Optional[Dict[str, Any]] = None,
        cluster_context: Optional[str] = None,
        keyword_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run Phase A: Research & Outline.

        Args:
            article_id: Article UUID
            keyword: Target keyword
            competitor_data: Winning formula / competitor analysis results
            brand_context: Brand profile dict (from BrandProfileService)
            author_id: Author UUID (loads context from seo_authors)
            mode: "api" or "cli"
            organization_id: Org ID for usage tracking
            model: Anthropic model to use

        Returns:
            Dict with phase output, mode info, and metadata
        """
        # Auto-load keyword from article if not provided
        if not keyword:
            article = self.supabase.table("seo_articles").select("keyword").eq("id", article_id).limit(1).execute()
            keyword = article.data[0].get("keyword", "") if article.data else ""

        author_ctx = self._load_author_context(author_id)
        prompt = self._build_phase_a_prompt(
            keyword, competitor_data, brand_context, author_ctx,
            brand_config=brand_config, cluster_context=cluster_context,
        )

        if mode == "cli":
            return self._handle_cli_mode(article_id, "a", prompt, keyword)

        return self._handle_api_mode(
            article_id, "a", prompt, keyword, organization_id, model
        )

    def generate_phase_b(
        self,
        article_id: str,
        keyword: str = "",
        phase_a_output: str = "",
        brand_context: Optional[Dict[str, Any]] = None,
        author_id: Optional[str] = None,
        mode: str = "api",
        organization_id: Optional[str] = None,
        model: str = "claude-opus-4-7",
        brand_config: Optional[Dict[str, Any]] = None,
        cluster_context: Optional[str] = None,
        content_fingerprints: Optional[str] = None,
        article_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run Phase B: Write (Freedom Mode).

        Args:
            article_id: Article UUID
            keyword: Target keyword
            phase_a_output: Output from Phase A (outline)
            brand_context: Brand profile dict
            author_id: Author UUID
            mode: "api" or "cli"
            organization_id: Org ID for usage tracking
            model: Anthropic model to use

        Returns:
            Dict with phase output, mode info, and metadata
        """
        # Auto-load keyword and phase_a_output from article if not provided
        if not keyword or not phase_a_output:
            article = self.supabase.table("seo_articles").select("keyword, phase_a_output").eq("id", article_id).limit(1).execute()
            if article.data:
                keyword = keyword or article.data[0].get("keyword", "")
                phase_a_output = phase_a_output or article.data[0].get("phase_a_output", "")

        author_ctx = self._load_author_context(author_id)
        prompt = self._build_phase_b_prompt(
            keyword, phase_a_output, brand_context, author_ctx,
            brand_config=brand_config, cluster_context=cluster_context,
            content_fingerprints=content_fingerprints, article_role=article_role,
        )

        if mode == "cli":
            return self._handle_cli_mode(article_id, "b", prompt, keyword)

        return self._handle_api_mode(
            article_id, "b", prompt, keyword, organization_id, model
        )

    def generate_phase_c(
        self,
        article_id: str,
        keyword: str = "",
        phase_b_output: str = "",
        competitor_data: Optional[Dict[str, Any]] = None,
        existing_articles: Optional[List[Dict[str, Any]]] = None,
        brand_context: Optional[Dict[str, Any]] = None,
        author_id: Optional[str] = None,
        mode: str = "api",
        organization_id: Optional[str] = None,
        model: str = "claude-opus-4-7",
        brand_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run Phase C: SEO Optimization.

        Args:
            article_id: Article UUID
            keyword: Target keyword
            phase_b_output: Raw article from Phase B
            competitor_data: Winning formula stats
            existing_articles: Published articles for internal linking
            brand_context: Brand profile dict
            author_id: Author UUID
            mode: "api" or "cli"
            organization_id: Org ID for usage tracking
            model: Anthropic model to use

        Returns:
            Dict with phase output, mode info, and metadata
        """
        # Auto-load keyword and phase_b_output from article if not provided
        if not keyword or not phase_b_output:
            article = self.supabase.table("seo_articles").select("keyword, phase_b_output").eq("id", article_id).limit(1).execute()
            if article.data:
                keyword = keyword or article.data[0].get("keyword", "")
                phase_b_output = phase_b_output or article.data[0].get("phase_b_output", "")

        author_ctx = self._load_author_context(author_id)
        prompt = self._build_phase_c_prompt(
            keyword, phase_b_output, competitor_data, existing_articles,
            brand_context, author_ctx, brand_config=brand_config,
        )

        if mode == "cli":
            return self._handle_cli_mode(article_id, "c", prompt, keyword)

        return self._handle_api_mode(
            article_id, "c", prompt, keyword, organization_id, model
        )

    def ingest_cli_result(
        self,
        article_id: str,
        phase: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Ingest CLI-mode generation result back into the pipeline.

        Args:
            article_id: Article UUID
            phase: Phase letter (a, b, c)
            content: Result content from CLI execution

        Returns:
            Dict with article_id and phase
        """
        phase = phase.lower()
        if phase not in ("a", "b", "c"):
            raise ValueError(f"Invalid phase: {phase}. Must be a, b, or c.")

        column = f"phase_{phase}_output"
        phase_status = {
            "a": ArticleStatus.OUTLINE_COMPLETE.value,
            "b": ArticleStatus.DRAFT_COMPLETE.value,
            "c": ArticleStatus.OPTIMIZED.value,
        }

        try:
            self.supabase.table("seo_articles").update({
                column: content,
                "phase": phase,
                "status": phase_status[phase],
            }).eq("id", article_id).execute()

            logger.info(f"Ingested Phase {phase.upper()} result for article {article_id}")
        except Exception as e:
            logger.error(f"Failed to ingest Phase {phase.upper()} for {article_id}: {e}")
            raise

        return {"article_id": article_id, "phase": phase, "status": "ingested"}

    def get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get an article by ID."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def create_article(
        self,
        project_id: str,
        brand_id: str,
        organization_id: str,
        keyword: str,
        author_id: Optional[str] = None,
        keyword_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new article record.

        Args:
            project_id: SEO project UUID
            brand_id: Brand UUID
            organization_id: Organization UUID
            keyword: Target keyword
            author_id: Author UUID (optional)
            keyword_id: Keyword UUID from discovery (optional)

        Returns:
            Created article record
        """
        data = {
            "project_id": project_id,
            "brand_id": brand_id,
            "organization_id": organization_id,
            "keyword": keyword,
            "status": ArticleStatus.DRAFT.value,
            "phase": "pending",
        }
        if author_id:
            data["author_id"] = author_id
        if keyword_id:
            data["keyword_id"] = keyword_id

        result = self.supabase.table("seo_articles").insert(data).execute()
        return result.data[0] if result.data else data

    def list_articles(
        self,
        project_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List articles for a project, optionally filtered by status.

        Args:
            project_id: SEO project UUID
            status: Filter by ArticleStatus value (optional)

        Raises:
            ValueError: If status is not a valid ArticleStatus value
        """
        if status:
            valid = {s.value for s in ArticleStatus}
            if status not in valid:
                raise ValueError(
                    f"Invalid article status: '{status}'. "
                    f"Valid values: {sorted(valid)}"
                )

        query = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("project_id", project_id)
            .neq("status", "discovered")
        )
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).execute()
        return result.data

    # =========================================================================
    # PROMPT BUILDERS
    # =========================================================================

    def _build_phase_a_prompt(
        self,
        keyword: str,
        competitor_data: Optional[Dict[str, Any]],
        brand_context: Optional[Dict[str, Any]],
        author_ctx: Dict[str, Any],
        brand_config: Optional[Dict[str, Any]] = None,
        cluster_context: Optional[str] = None,
    ) -> str:
        """Build Phase A prompt from template."""
        template = self._load_template("phase_a_research.txt")
        brand_config = brand_config or {}

        # Format competitor data
        comp_text = "No competitor data available."
        if competitor_data:
            if "results" in competitor_data:
                lines = []
                for r in competitor_data["results"]:
                    lines.append(
                        f"- {r.get('url', 'Unknown')}: {r.get('word_count', 0)} words, "
                        f"{r.get('h2_count', 0)} H2s, Flesch {r.get('flesch_reading_ease', '-')}, "
                        f"Schema: {'Yes' if r.get('has_schema') else 'No'}, "
                        f"FAQ: {'Yes' if r.get('has_faq') else 'No'}"
                    )
                comp_text = "\n".join(lines)
            elif "winning_formula" in competitor_data:
                comp_text = json.dumps(competitor_data["winning_formula"], indent=2)

        return template.format(
            AUTHOR_NAME=author_ctx.get("name", "Author"),
            BRAND_NAME=self._get_brand_name(brand_context),
            KEYWORD=keyword,
            SEARCH_INTENT=self._infer_search_intent(keyword),
            BRAND_POSITIONING=self._get_brand_positioning(brand_context),
            AUTHOR_VOICE=author_ctx.get("voice", "Write in a conversational, authentic tone."),
            COMPETITOR_DATA=comp_text,
            CONTENT_STYLE_GUIDE=_escape_for_format(brand_config.get("content_style_guide", "")),
            PRODUCT_MENTION_RULES=_escape_for_format(brand_config.get("product_mention_rules", "")),
            CLUSTER_CONTEXT=_escape_for_format(cluster_context or ""),
        )

    def _build_phase_b_prompt(
        self,
        keyword: str,
        phase_a_output: str,
        brand_context: Optional[Dict[str, Any]],
        author_ctx: Dict[str, Any],
        brand_config: Optional[Dict[str, Any]] = None,
        cluster_context: Optional[str] = None,
        content_fingerprints: Optional[str] = None,
        article_role: Optional[str] = None,
    ) -> str:
        """Build Phase B prompt from template."""
        template = self._load_template("phase_b_write.txt")
        brand_config = brand_config or {}

        # Role-based length guidance
        if article_role == "pillar":
            length_guidance = "This is a PILLAR article — write a broad, comprehensive overview (2000+ words)."
            role_text = "This is a PILLAR article: broad overview that serves as the topical anchor for related articles."
        elif article_role == "spoke":
            length_guidance = "This is a SPOKE article — write a focused deep-dive (800-1500 words)."
            role_text = "This is a SPOKE article: focused deep-dive on one specific aspect of a broader topic."
        else:
            length_guidance = "Write until the topic is fully covered. Could be 800 words. Could be 2000. Quality > hitting a number."
            role_text = ""

        return template.format(
            AUTHOR_NAME=author_ctx.get("name", "Author"),
            BRAND_NAME=self._get_brand_name(brand_context),
            KEYWORD=keyword,
            BRAND_POSITIONING=self._get_brand_positioning(brand_context),
            AUTHOR_VOICE=author_ctx.get("voice", "Write in a conversational, authentic tone."),
            PHASE_A_OUTPUT=phase_a_output,
            PRODUCT_MENTIONS=self._get_product_mentions(brand_context),
            CONTENT_STYLE_GUIDE=_escape_for_format(brand_config.get("content_style_guide", "")),
            CLUSTER_CONTEXT=_escape_for_format(cluster_context or ""),
            CONTENT_FINGERPRINTS=_escape_for_format(content_fingerprints or ""),
            ARTICLE_ROLE=_escape_for_format(role_text),
            LENGTH_GUIDANCE=length_guidance,
        )

    def _build_phase_c_prompt(
        self,
        keyword: str,
        phase_b_output: str,
        competitor_data: Optional[Dict[str, Any]],
        existing_articles: Optional[List[Dict[str, Any]]],
        brand_context: Optional[Dict[str, Any]],
        author_ctx: Dict[str, Any],
        brand_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build Phase C prompt from template."""
        template = self._load_template("phase_c_optimize.txt")
        brand_config = brand_config or {}

        # Format competitor stats
        comp_stats = "No competitor data available."
        if competitor_data and "winning_formula" in competitor_data:
            wf = competitor_data["winning_formula"]
            comp_stats = (
                f"Target word count: {wf.get('target_word_count', 'N/A')}\n"
                f"Avg H2 count: {wf.get('avg_h2_count', 'N/A')}\n"
                f"Avg Flesch score: {wf.get('avg_flesch_score', 'N/A')}\n"
                f"Schema usage: {wf.get('pct_with_schema', 'N/A')}%\n"
                f"FAQ usage: {wf.get('pct_with_faq', 'N/A')}%"
            )

        # Format internal links context
        links_ctx = "No published articles available for internal linking."
        if existing_articles:
            lines = []
            for art in existing_articles[:10]:
                title = art.get("title") or art.get("keyword", "Untitled")
                url = art.get("published_url", "")
                if url:
                    lines.append(f"- [{title}]({url})")
                else:
                    lines.append(f"- {title} (not yet published)")
            links_ctx = "Published articles available for internal linking:\n" + "\n".join(lines)

        # Format available tags for prompt
        tags = brand_config.get("available_tags") or []
        if tags:
            tag_lines = [f"- {t['slug']}: {t.get('name', '')} — {t.get('description', '')}" for t in tags]
            tags_text = "\n".join(tag_lines)
        else:
            tags_text = "[auto-select appropriate tags]"

        tag_rules = (
            "Select ONE primary tag and optionally ONE secondary tag "
            "(if article substantially covers another category, >30% of content). "
            "Include in frontmatter as `tags: [slug1, slug2]`"
        )

        # Image style
        image_style = brand_config.get("image_style", "")
        if image_style:
            image_style_text = f"Photography style: {image_style}"
        else:
            image_style_text = ""

        return template.format(
            KEYWORD=keyword,
            PHASE_B_OUTPUT=phase_b_output,
            COMPETITOR_STATS=comp_stats,
            AUTHOR_NAME=author_ctx.get("name", "Author"),
            AUTHOR_BIO=author_ctx.get("bio", f"Written by {author_ctx.get('name', 'Author')}."),
            BRAND_NAME=self._get_brand_name(brand_context),
            INTERNAL_LINKS_CONTEXT=links_ctx,
            CONTENT_STYLE_GUIDE=_escape_for_format(brand_config.get("content_style_guide", "")),
            AVAILABLE_TAGS=_escape_for_format(tags_text),
            TAG_SELECTION_RULES=tag_rules,
            IMAGE_STYLE=_escape_for_format(image_style_text),
        )

    # =========================================================================
    # EXECUTION MODES
    # =========================================================================

    def _handle_api_mode(
        self,
        article_id: str,
        phase: str,
        prompt: str,
        keyword: str,
        organization_id: Optional[str],
        model: str,
    ) -> Dict[str, Any]:
        """Execute phase via Anthropic API."""
        logger.info(f"Phase {phase.upper()} API mode: {keyword} (model: {model})")

        start_time = time.time()

        # Retry on transient connection errors (HTTP/2 drops, timeouts)
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.anthropic_client.messages.create(
                    model=model,
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except Exception as e:
                last_error = e
                err_name = type(e).__name__
                if attempt < max_retries - 1 and err_name in (
                    "ConnectionTerminated", "RemoteProtocolError",
                    "ConnectError", "ReadTimeout", "APIConnectionError",
                ):
                    wait = (attempt + 1) * 10
                    logger.warning(
                        f"Phase {phase.upper()} attempt {attempt + 1} failed ({err_name}), "
                        f"retrying in {wait}s..."
                    )
                    time.sleep(wait)
                    # Force new HTTP connection on retry
                    self._anthropic = None
                else:
                    raise
        else:
            raise last_error

        duration_ms = int((time.time() - start_time) * 1000)
        content = response.content[0].text

        # Track usage
        if organization_id:
            self._track_usage(
                organization_id=organization_id,
                model=model,
                phase=phase,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
            )

        # Save to DB
        column = f"phase_{phase}_output"
        phase_status = {
            "a": ArticleStatus.OUTLINE_COMPLETE.value,
            "b": ArticleStatus.DRAFT_COMPLETE.value,
            "c": ArticleStatus.OPTIMIZED.value,
        }

        try:
            self.supabase.table("seo_articles").update({
                column: content,
                "phase": phase,
                "status": phase_status.get(phase, ArticleStatus.DRAFT.value),
            }).eq("id", article_id).execute()
        except Exception as e:
            logger.error(f"Failed to save Phase {phase.upper()} output: {e}")

        return {
            "article_id": article_id,
            "phase": phase,
            "mode": "api",
            "content": content,
            "model": model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "duration_ms": duration_ms,
        }

    def _handle_cli_mode(
        self,
        article_id: str,
        phase: str,
        prompt: str,
        keyword: str,
    ) -> Dict[str, Any]:
        """Write prompt to file for CLI execution."""
        slug = keyword.lower().replace(" ", "-")[:40]
        filename = f"seo-pipeline-{article_id[:8]}-phase-{phase}-{slug}.md"
        filepath = Path("/tmp") / filename

        filepath.write_text(prompt, encoding="utf-8")

        logger.info(f"Phase {phase.upper()} CLI mode: prompt written to {filepath}")

        return {
            "article_id": article_id,
            "phase": phase,
            "mode": "cli",
            "prompt_file": str(filepath),
            "instructions": (
                f"Prompt written to {filepath}\n\n"
                f"Run this prompt through Claude Code or another LLM, then ingest the result:\n"
                f"  vt seo ingest-result --article-id {article_id} --phase {phase} --file <result-file>"
            ),
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _infer_search_intent(keyword: str) -> str:
        """Infer search intent from keyword modifiers."""
        kw = keyword.lower().strip()
        if any(kw.startswith(p) for p in ("how to ", "how do ", "ways to ", "steps to ", "guide to ")):
            return f"Users searching for '{keyword}' want step-by-step, actionable instructions."
        if any(kw.startswith(p) for p in ("best ", "top ", "vs ", "compare ")):
            return f"Users searching for '{keyword}' are comparing options and want recommendations."
        if any(kw.startswith(p) for p in ("what is ", "what are ", "why ", "when ", "who ")):
            return f"Users searching for '{keyword}' want clear, educational explanations."
        if any(kw.startswith(p) for p in ("buy ", "price ", "cost ", "cheap ", "deal ")):
            return f"Users searching for '{keyword}' are ready to purchase and want pricing/availability."
        if any(kw.startswith(p) for p in ("review ", "reviews ")):
            return f"Users searching for '{keyword}' want honest opinions and real experiences."
        return f"Users searching for '{keyword}' want practical, actionable information."

    def _load_template(self, filename: str) -> str:
        """Load a prompt template file."""
        path = PROMPTS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _load_author_context(self, author_id: Optional[str]) -> Dict[str, Any]:
        """
        Load author context from seo_authors table.

        If author has a linked persona_id, loads voice/style from that persona.
        """
        default_ctx = {
            "name": "Author",
            "bio": "",
            "image_url": "",
            "job_title": "",
            "author_url": "",
            "voice": "Write in a conversational, authentic, and knowledgeable tone.",
        }

        if not author_id:
            return default_ctx

        try:
            result = (
                self.supabase.table("seo_authors")
                .select("*")
                .eq("id", author_id)
                .execute()
            )
            if not result.data:
                return default_ctx

            author = result.data[0]
            ctx = {
                "name": author.get("name", "Author"),
                "bio": author.get("bio", ""),
                "image_url": author.get("image_url", ""),
                "job_title": author.get("job_title", ""),
                "author_url": author.get("author_url", ""),
                "voice": "Write in a conversational, authentic, and knowledgeable tone.",
            }

            # If author links to a persona, use persona voice
            persona_id = author.get("persona_id")
            if persona_id:
                try:
                    persona_result = (
                        self.supabase.table("personas_4d")
                        .select("voice_and_tone, brand_voice_summary")
                        .eq("id", persona_id)
                        .execute()
                    )
                    if persona_result.data:
                        persona = persona_result.data[0]
                        voice_parts = []
                        if persona.get("voice_and_tone"):
                            voice_parts.append(persona["voice_and_tone"])
                        if persona.get("brand_voice_summary"):
                            voice_parts.append(persona["brand_voice_summary"])
                        if voice_parts:
                            ctx["voice"] = "\n".join(voice_parts)
                except Exception as e:
                    logger.warning(f"Failed to load persona {persona_id}: {e}")

            return ctx
        except Exception as e:
            logger.warning(f"Failed to load author {author_id}: {e}")
            return default_ctx

    def _get_brand_name(self, brand_context: Optional[Dict[str, Any]]) -> str:
        """Extract brand name from brand context."""
        if not brand_context:
            return "Our Brand"
        basics = brand_context.get("brand_basics", {})
        return basics.get("name", "Our Brand")

    def _get_brand_positioning(self, brand_context: Optional[Dict[str, Any]]) -> str:
        """Build brand positioning text from brand context."""
        if not brand_context:
            return "We help our customers with practical, actionable solutions."

        basics = brand_context.get("brand_basics", {})
        product = brand_context.get("product", {})

        parts = []
        if basics.get("description"):
            parts.append(basics["description"])
        if product.get("target_audience"):
            parts.append(f"Target audience: {product['target_audience']}")
        if product.get("key_benefits"):
            benefits = product["key_benefits"][:5]
            parts.append("Key benefits:\n" + "\n".join(f"- {b}" for b in benefits))

        return "\n\n".join(parts) if parts else "We help our customers with practical solutions."

    def _get_product_mentions(self, brand_context: Optional[Dict[str, Any]]) -> str:
        """Build product mention guidance from brand context."""
        if not brand_context:
            return "Mention products naturally where they genuinely help solve the reader's problem."

        product = brand_context.get("product", {})
        brand_name = self._get_brand_name(brand_context)

        if not product.get("name"):
            return f"Mention {brand_name} naturally where it genuinely helps solve the reader's problem."

        return (
            f"When mentioning {product['name']}:\n"
            f"- Mention it where it genuinely helps solve the problem\n"
            f"- Keep it natural - don't force product placement\n"
            f"- Focus on how it helps the reader, not on selling"
        )

    def _track_usage(
        self,
        organization_id: str,
        model: str,
        phase: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
    ) -> None:
        """Track API usage via UsageTracker."""
        try:
            from viraltracker.services.usage_tracker import UsageRecord
            record = UsageRecord(
                provider="anthropic",
                model=model,
                tool_name="seo_pipeline",
                operation=f"content_generation_phase_{phase}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
            self.usage_tracker.track(
                user_id=None,
                organization_id=organization_id,
                record=record,
            )
        except Exception as e:
            logger.warning(f"Failed to track usage: {e}")
