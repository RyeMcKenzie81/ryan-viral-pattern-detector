"""
Brand Seed Generator Service.

AI-powered seed keyword generation from brand data. Two-step flow:
1. discover_topics() — gathers brand context, calls Claude to suggest content topics
2. generate_seeds_for_topics() — for selected topics, generates long-tail search phrases
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class BrandContext:
    """All available brand data for topic/seed generation."""

    brand_name: str
    brand_description: str
    # Tier 1: Products
    products: List[Dict] = field(default_factory=list)
    offer_variants: List[Dict] = field(default_factory=list)
    # Tier 2: Research
    angle_candidates: List[Dict] = field(default_factory=list)
    patterns: List[Dict] = field(default_factory=list)
    persona_insights: List[Dict] = field(default_factory=list)
    # Tier 3: Performance
    gsc_opportunities: List[Dict] = field(default_factory=list)
    existing_keywords: List[str] = field(default_factory=list)
    # Tier 4: Config
    content_style_guide: str = ""
    available_tags: List[str] = field(default_factory=list)
    # Metadata
    tiers_available: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class DiscoveredTopic:
    """A topic suggested by the AI."""

    topic: str
    rationale: str
    sources: List[str] = field(default_factory=list)
    estimated_articles: int = 3
    gap: bool = False


@dataclass
class TopicDiscoveryResult:
    """Result of topic discovery."""

    topics: List[DiscoveredTopic] = field(default_factory=list)
    brand_context_summary: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class GeneratedSeed:
    """A single generated seed keyword."""

    keyword: str
    topic: str
    intent: str = "informational"
    rationale: str = ""


@dataclass
class SeedGenerationResult:
    """Result of seed generation."""

    seeds_by_topic: Dict[str, List[GeneratedSeed]] = field(default_factory=dict)
    total_seeds: int = 0
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# SERVICE
# =============================================================================


class BrandSeedGeneratorService:
    """Generates seed keywords from brand data using Claude."""

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, supabase_client=None, anthropic_client=None):
        self._supabase = supabase_client
        self._anthropic = anthropic_client
        self.last_brand_context: Optional[BrandContext] = None

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client

            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def anthropic_client(self):
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic

            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def discover_topics(
        self, brand_id: str, organization_id: str
    ) -> TopicDiscoveryResult:
        """Discover content topics from brand data using Claude.

        Args:
            brand_id: Brand to analyze.
            organization_id: For usage tracking.

        Returns:
            TopicDiscoveryResult with suggested topics.
        """
        brand_ctx = self._gather_brand_context(brand_id)
        self.last_brand_context = brand_ctx
        prompt = self._build_topic_discovery_prompt(brand_ctx)

        start_time = time.time()
        try:
            response = self.anthropic_client.messages.create(
                model=self.MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            duration_ms = int((time.time() - start_time) * 1000)

            self._track_usage(
                organization_id=organization_id,
                operation="topic_discovery",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
            )

            topics = self._parse_topics(text, brand_ctx.existing_keywords)
            tiers_str = ", ".join(f"Tier {t}" for t in brand_ctx.tiers_available)
            return TopicDiscoveryResult(
                topics=topics,
                brand_context_summary=f"Data from {tiers_str}",
                warnings=brand_ctx.warnings,
            )

        except Exception as e:
            logger.error(f"Topic discovery failed: {e}")
            return TopicDiscoveryResult(
                warnings=[f"Topic discovery failed: {e}"] + brand_ctx.warnings,
            )

    def generate_seeds_for_topics(
        self,
        topics: List[str],
        brand_context: BrandContext,
        organization_id: str,
    ) -> SeedGenerationResult:
        """Generate long-tail seed phrases for selected topics.

        Args:
            topics: Selected topic labels.
            brand_context: Previously gathered brand context.
            organization_id: For usage tracking.

        Returns:
            SeedGenerationResult with seeds grouped by topic.
        """
        prompt = self._build_seed_generation_prompt(topics, brand_context)

        start_time = time.time()
        try:
            response = self.anthropic_client.messages.create(
                model=self.MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            duration_ms = int((time.time() - start_time) * 1000)

            self._track_usage(
                organization_id=organization_id,
                operation="seed_generation",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
            )

            seeds_by_topic = self._parse_seeds(text, topics)
            seeds_by_topic = self._deduplicate_seeds(
                seeds_by_topic, brand_context.existing_keywords
            )
            total = sum(len(v) for v in seeds_by_topic.values())
            return SeedGenerationResult(
                seeds_by_topic=seeds_by_topic, total_seeds=total
            )

        except Exception as e:
            logger.error(f"Seed generation failed: {e}")
            return SeedGenerationResult(
                warnings=[f"Seed generation failed: {e}"],
            )

    # -------------------------------------------------------------------------
    # BRAND CONTEXT EXTRACTION
    # -------------------------------------------------------------------------

    def _gather_brand_context(self, brand_id: str) -> BrandContext:
        """Extract all available brand data across 4 tiers."""
        ctx = BrandContext(brand_name="", brand_description="")
        tiers: List[int] = []

        # Tier 4 (base): Brand info
        try:
            row = (
                self.supabase.table("brands")
                .select("name, description")
                .eq("id", brand_id)
                .limit(1)
                .execute()
            )
            if row.data:
                ctx.brand_name = row.data[0].get("name", "")
                ctx.brand_description = row.data[0].get("description", "") or ""
                tiers.append(4)
        except Exception as e:
            logger.warning(f"Failed to load brand: {e}")
            ctx.warnings.append("Could not load brand info")

        # Brand config (style guide, tags)
        try:
            cfg = (
                self.supabase.table("seo_brand_config")
                .select("content_style_guide, available_tags")
                .eq("brand_id", brand_id)
                .limit(1)
                .execute()
            )
            if cfg.data:
                ctx.content_style_guide = cfg.data[0].get("content_style_guide", "") or ""
                tags_raw = cfg.data[0].get("available_tags") or []
                ctx.available_tags = [
                    t["name"] for t in tags_raw if isinstance(t, dict) and "name" in t
                ]
        except Exception as e:
            logger.warning(f"Failed to load brand config: {e}")

        # Tier 1: Products + offer variants
        try:
            products = (
                self.supabase.table("products")
                .select(
                    "id, name, description, target_audience, "
                    "key_benefits, key_problems_solved, ingredients, faq_items, features"
                )
                .eq("brand_id", brand_id)
                .limit(20)
                .execute()
            )
            if products.data:
                ctx.products = products.data
                tiers.append(1)

                # Offer variants per product
                for prod in products.data:
                    try:
                        variants = (
                            self.supabase.table("product_offer_variants")
                            .select(
                                "pain_points, desires_goals, benefits, "
                                "mechanism_name, mechanism_problem, mechanism_solution, "
                                "sample_hooks"
                            )
                            .eq("product_id", prod["id"])
                            .execute()
                        )
                        if variants.data:
                            ctx.offer_variants.extend(variants.data)
                    except Exception as e:
                        logger.warning(f"Failed to load offer variants for {prod['id']}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load products: {e}")
            ctx.warnings.append("Could not load products")

        # Tier 2: Research intelligence
        try:
            candidates = (
                self.supabase.table("angle_candidates")
                .select(
                    "name, belief_statement, candidate_type, frequency_score, confidence, product_id"
                )
                .eq("brand_id", brand_id)
                .in_("status", ["candidate", "approved"])
                .gte("frequency_score", 2)
                .order("frequency_score", desc=True)
                .limit(30)
                .execute()
            )
            if candidates.data:
                ctx.angle_candidates = candidates.data
                tiers.append(2)
        except Exception as e:
            logger.warning(f"Failed to load angle candidates: {e}")

        try:
            patterns = (
                self.supabase.table("discovered_patterns")
                .select(
                    "name, theme_description, confidence_score, novelty_score, pattern_type, product_id"
                )
                .eq("brand_id", brand_id)
                .gte("confidence_score", 0.5)
                .order("novelty_score", desc=True)
                .limit(20)
                .execute()
            )
            if patterns.data:
                ctx.patterns = patterns.data
        except Exception as e:
            logger.warning(f"Failed to load patterns: {e}")

        try:
            personas = (
                self.supabase.table("personas_4d")
                .select(
                    "pain_points, outcomes_jtbd, transformation_map, "
                    "desired_features, failed_solutions, activation_events, name"
                )
                .eq("brand_id", brand_id)
                .limit(10)
                .execute()
            )
            if personas.data:
                ctx.persona_insights = personas.data
        except Exception as e:
            logger.warning(f"Failed to load personas: {e}")

        # Tier 3: Performance data
        try:
            articles = (
                self.supabase.table("seo_articles")
                .select("id, keyword")
                .eq("brand_id", brand_id)
                .neq("status", "discovered")
                .limit(200)
                .execute()
            )
            if articles.data:
                article_ids = [a["id"] for a in articles.data]
                ctx.existing_keywords = [
                    a["keyword"] for a in articles.data if a.get("keyword")
                ]
                tiers.append(3)

                # GSC opportunities: page 2-3 keywords
                if article_ids:
                    try:
                        rankings = (
                            self.supabase.table("seo_article_rankings")
                            .select("keyword, position, impressions")
                            .in_("article_id", article_ids)
                            .gte("position", 11)
                            .lte("position", 50)
                            .gte("impressions", 50)
                            .order("impressions", desc=True)
                            .limit(50)
                            .execute()
                        )
                        if rankings.data:
                            ctx.gsc_opportunities = rankings.data
                    except Exception as e:
                        logger.warning(f"Failed to load GSC rankings: {e}")
                        ctx.warnings.append("Could not load GSC ranking data")
        except Exception as e:
            logger.warning(f"Failed to load articles: {e}")
            ctx.warnings.append("Could not load existing articles")

        if not ctx.brand_name:
            ctx.brand_name = brand_id
            ctx.warnings.append("Brand name not found — using ID as fallback")

        ctx.tiers_available = sorted(set(tiers))
        return ctx

    # -------------------------------------------------------------------------
    # PROMPT BUILDERS
    # -------------------------------------------------------------------------

    def _build_topic_discovery_prompt(self, ctx: BrandContext) -> str:
        """Build the topic discovery prompt from brand context."""
        sections = [
            "You are an SEO content strategist analyzing a brand to identify high-value content topics.",
            f"\nBRAND: {ctx.brand_name}",
            f"DESCRIPTION: {ctx.brand_description or '(not available)'}",
        ]

        # Products
        if ctx.products:
            lines = ["\nPRODUCTS:"]
            for p in ctx.products:
                parts = [f"- {p.get('name', 'Unknown')}"]
                if p.get("key_benefits"):
                    benefits = p["key_benefits"]
                    if isinstance(benefits, list):
                        parts.append(f"  Benefits: {', '.join(str(b) for b in benefits[:5])}")
                    elif isinstance(benefits, dict):
                        parts.append(f"  Benefits: {json.dumps(benefits)[:200]}")
                if p.get("key_problems_solved"):
                    problems = p["key_problems_solved"]
                    if isinstance(problems, list):
                        parts.append(f"  Problems solved: {', '.join(str(pr) for pr in problems[:5])}")
                if p.get("ingredients"):
                    ings = p["ingredients"]
                    if isinstance(ings, list):
                        names = [i.get("name", str(i)) if isinstance(i, dict) else str(i) for i in ings[:5]]
                        parts.append(f"  Key ingredients: {', '.join(names)}")
                lines.append("\n".join(parts))
            sections.append("\n".join(lines))

        # Customer voice
        voice_parts = []
        if ctx.angle_candidates:
            hi_conf = [
                a for a in ctx.angle_candidates if a.get("confidence") in ("HIGH", "MEDIUM")
            ]
            if hi_conf:
                stmts = [f'- "{a["belief_statement"]}"' for a in hi_conf[:10]]
                voice_parts.append("Angle candidates (validated research):\n" + "\n".join(stmts))

        if ctx.persona_insights:
            for persona in ctx.persona_insights[:3]:
                name = persona.get("name", "Persona")
                pp = persona.get("pain_points")
                if isinstance(pp, dict):
                    all_pains = []
                    for cat in ("emotional", "social", "functional"):
                        all_pains.extend(pp.get(cat, []))
                    if all_pains:
                        voice_parts.append(
                            f"{name} pain points: {', '.join(str(p) for p in all_pains[:8])}"
                        )
                jtbd = persona.get("outcomes_jtbd")
                if isinstance(jtbd, dict):
                    all_jtbd = []
                    for cat in ("emotional", "social", "functional"):
                        all_jtbd.extend(jtbd.get(cat, []))
                    if all_jtbd:
                        voice_parts.append(
                            f"{name} desired outcomes: {', '.join(str(j) for j in all_jtbd[:8])}"
                        )

        if ctx.patterns:
            pat_lines = [
                f'- {p["name"]}: {p.get("theme_description", "")}'
                for p in ctx.patterns[:8]
            ]
            voice_parts.append("Discovered patterns:\n" + "\n".join(pat_lines))

        if voice_parts:
            sections.append("\nCUSTOMER VOICE (from validated research):\n" + "\n\n".join(voice_parts))

        # Offer angles
        if ctx.offer_variants:
            ov_lines = ["\nPRODUCT OFFER ANGLES:"]
            for ov in ctx.offer_variants[:5]:
                parts = []
                if ov.get("pain_points"):
                    parts.append(f"  Pain points: {', '.join(ov['pain_points'][:5])}")
                if ov.get("desires_goals"):
                    parts.append(f"  Desires: {', '.join(ov['desires_goals'][:5])}")
                if ov.get("mechanism_name"):
                    parts.append(
                        f"  Mechanism: {ov['mechanism_name']} — "
                        f"{ov.get('mechanism_problem', '')} → {ov.get('mechanism_solution', '')}"
                    )
                if parts:
                    ov_lines.append("\n".join(parts))
            sections.append("\n".join(ov_lines))

        # Existing content
        if ctx.existing_keywords:
            sections.append(
                f"\nEXISTING CONTENT (avoid cannibalization):\n"
                + ", ".join(ctx.existing_keywords[:30])
            )

        # GSC gaps
        if ctx.gsc_opportunities:
            gap_lines = ["\nCONTENT GAPS (GSC keywords at position 11-50 with impressions):"]
            for g in ctx.gsc_opportunities[:15]:
                gap_lines.append(
                    f"- {g['keyword']} (pos {g.get('position', '?')}, {g.get('impressions', 0)} imp)"
                )
            sections.append("\n".join(gap_lines))

        # Instructions
        sections.append(
            "\nSuggest 5-8 content topic areas. For each, return JSON:\n"
            "[\n"
            '  {"topic": "3-8 word topic label", '
            '"rationale": "Why this is valuable (1-2 sentences)", '
            '"sources": ["which data sections above informed this"], '
            '"estimated_articles": 5, '
            '"gap": true}\n'
            "]\n\n"
            "Focus on:\n"
            "- Customer language patterns that reveal real search demand\n"
            "- Gaps between customer questions and published content\n"
            "- Long-tail niches where the brand has authority but no content\n\n"
            "Return ONLY the JSON array, no other text."
        )

        return "\n".join(sections)

    def _build_seed_generation_prompt(
        self, topics: List[str], ctx: BrandContext
    ) -> str:
        """Build the seed generation prompt."""
        sections = [
            "You are an SEO keyword researcher generating long-tail search phrases "
            "real people type into Google.",
            f"\nBRAND: {ctx.brand_name} — {ctx.brand_description or '(no description)'}",
        ]

        # Customer language patterns
        lang_parts = []
        if ctx.persona_insights:
            for persona in ctx.persona_insights[:3]:
                pp = persona.get("pain_points")
                if isinstance(pp, dict):
                    all_pains = []
                    for cat in ("emotional", "social", "functional"):
                        all_pains.extend(pp.get(cat, []))
                    if all_pains:
                        lang_parts.append(f"Pain points: {', '.join(str(p) for p in all_pains[:8])}")

        if ctx.angle_candidates:
            stmts = [a["belief_statement"] for a in ctx.angle_candidates[:8]]
            lang_parts.append("Belief statements: " + " | ".join(stmts))

        # FAQ questions
        for prod in ctx.products[:3]:
            faq = prod.get("faq_items")
            if isinstance(faq, list) and faq:
                questions = [
                    f.get("question", str(f)) if isinstance(f, dict) else str(f)
                    for f in faq[:5]
                ]
                lang_parts.append(f"FAQ ({prod.get('name', 'product')}): {' | '.join(questions)}")

        # Offer variant language
        if ctx.offer_variants:
            for ov in ctx.offer_variants[:3]:
                if ov.get("pain_points"):
                    lang_parts.append(f"Customer pain: {', '.join(ov['pain_points'][:5])}")
                if ov.get("sample_hooks"):
                    lang_parts.append(f"Hooks: {', '.join(ov['sample_hooks'][:3])}")

        if lang_parts:
            sections.append("\nCUSTOMER LANGUAGE PATTERNS:\n" + "\n".join(lang_parts))

        # Topics
        topics_block = "\n".join(f"- {t}" for t in topics)
        sections.append(f"\nTOPICS TO GENERATE SEEDS FOR:\n{topics_block}")

        # Existing articles
        if ctx.existing_keywords:
            sections.append(
                f"\nEXISTING ARTICLES (avoid overlap):\n"
                + ", ".join(ctx.existing_keywords[:30])
            )

        # Instructions
        sections.append(
            "\nFor each topic, generate 8-12 long-tail keyword phrases (4-8 words).\n\n"
            "Rules:\n"
            "- Use the customer's language, not marketing speak\n"
            "- Mix intent types: informational, commercial, comparison\n"
            "- Each phrase = something a real person would type into Google\n"
            "- Avoid phrases that overlap with existing articles\n"
            "- Prioritize specific intent over generic queries\n\n"
            'Return ONLY JSON:\n{"seeds_by_topic": {"topic1": [{"keyword": "...", '
            '"intent": "informational|commercial|comparison", "rationale": "..."}], ...}}'
        )

        return "\n".join(sections)

    # -------------------------------------------------------------------------
    # RESPONSE PARSERS
    # -------------------------------------------------------------------------

    def _parse_topics(
        self, text: str, existing_keywords: List[str]
    ) -> List[DiscoveredTopic]:
        """Parse Claude's topic discovery response."""
        # Try array first, then object
        json_match = re.search(r"\[[\s\S]*\]", text)
        if not json_match:
            json_match = re.search(r"\{[\s\S]*\}", text)

        if not json_match:
            logger.error("No JSON found in topic discovery response")
            return []

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse topic JSON: {e}")
            return []

        # Normalize: could be a list or {"topics": [...]}
        if isinstance(data, dict):
            data = data.get("topics", [])

        existing_lower = {k.lower() for k in existing_keywords}

        topics = []
        for item in data:
            if not isinstance(item, dict):
                continue
            topic_label = item.get("topic", "").strip()
            if not topic_label:
                continue

            # Check gap status: any existing keyword overlaps with this topic?
            topic_words = set(topic_label.lower().split())
            has_coverage = any(
                len(topic_words & set(kw.split())) >= 2 for kw in existing_lower
            )

            topics.append(
                DiscoveredTopic(
                    topic=topic_label,
                    rationale=item.get("rationale", ""),
                    sources=item.get("sources", []),
                    estimated_articles=item.get("estimated_articles", 3),
                    gap=item.get("gap", not has_coverage),
                )
            )

        return topics

    def _parse_seeds(
        self, text: str, topics: List[str]
    ) -> Dict[str, List[GeneratedSeed]]:
        """Parse Claude's seed generation response."""
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            logger.error("No JSON found in seed generation response")
            return {}

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse seed JSON: {e}")
            return {}

        raw = data.get("seeds_by_topic", data)
        result: Dict[str, List[GeneratedSeed]] = {}

        for topic in topics:
            seeds_data = raw.get(topic, [])
            seeds = []
            for item in seeds_data:
                if isinstance(item, str):
                    seeds.append(GeneratedSeed(keyword=item, topic=topic))
                elif isinstance(item, dict):
                    seeds.append(
                        GeneratedSeed(
                            keyword=item.get("keyword", ""),
                            topic=topic,
                            intent=item.get("intent", "informational"),
                            rationale=item.get("rationale", ""),
                        )
                    )
            result[topic] = [s for s in seeds if s.keyword.strip()]

        return result

    # -------------------------------------------------------------------------
    # DEDUP
    # -------------------------------------------------------------------------

    @staticmethod
    def _simple_stem(word: str) -> str:
        """Strip common English suffixes for dedup comparison."""
        if len(word) <= 4:
            return word
        for suffix in ("tion", "sion", "ment", "ness", "ing", "ies", "ied", "ers", "est", "ful", "ous", "ive", "ize", "ise", "ble", "ally", "ely", "ly", "ed", "er", "es", "al", "en", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
        return word

    _STOPWORDS = frozenset(
        "a an the is are was were be been being have has had do does did "
        "will would shall should may might can could of in to for on with "
        "at by from as into through during before after above below between "
        "and or but not no nor so yet both either neither each every all "
        "any few more most other some such than too very how what which who "
        "whom this that these those i me my we our you your he him his she "
        "her it its they them their".split()
    )

    @classmethod
    def _stemmed_words(cls, phrase: str) -> set:
        """Get stemmed word set for a phrase."""
        words = re.sub(r"[^a-z0-9\s]", "", phrase.lower()).split()
        return {cls._simple_stem(w) for w in words if w not in cls._STOPWORDS}

    @classmethod
    def _jaccard(cls, a: set, b: set) -> float:
        """Jaccard similarity between two sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _deduplicate_seeds(
        self,
        seeds_by_topic: Dict[str, List[GeneratedSeed]],
        existing_keywords: List[str],
    ) -> Dict[str, List[GeneratedSeed]]:
        """
        Remove near-duplicate seeds within and across topics.

        Uses semantic cosine similarity (>= 0.82) when embeddings are available,
        falls back to stemmed Jaccard (> 0.6) otherwise.
        """
        existing_stems = [self._stemmed_words(k) for k in existing_keywords]

        # Intent priority: commercial > comparison > informational
        intent_rank = {"commercial": 2, "comparison": 1, "informational": 0}

        # Try batch embedding all seeds + existing keywords for semantic dedup
        all_seed_texts = []
        for seeds in seeds_by_topic.values():
            for s in seeds:
                all_seed_texts.append(s.keyword)

        embeddings_map: Dict[str, List[float]] = {}
        try:
            from viraltracker.core.embeddings import create_seo_embedder
            embedder = create_seo_embedder()
            all_texts = existing_keywords + all_seed_texts
            if all_texts:
                all_vecs = embedder.embed_texts(all_texts, task_type="CLUSTERING")
                for text, vec in zip(all_texts, all_vecs):
                    embeddings_map[text.lower()] = vec
        except Exception as e:
            logger.warning(f"Seed dedup embedding failed, using Jaccard: {e}")

        use_embedding = bool(embeddings_map)

        kept: Dict[str, List[GeneratedSeed]] = {}
        seen_stems: List[tuple] = []  # (stemmed_set, seed)
        seen_embeddings: List[tuple] = []  # (embedding, seed)

        for topic, seeds in seeds_by_topic.items():
            sorted_seeds = sorted(
                seeds, key=lambda s: intent_rank.get(s.intent, 0), reverse=True
            )
            topic_kept = []

            for seed in sorted_seeds:
                stems = self._stemmed_words(seed.keyword)
                if not stems:
                    continue

                seed_emb = embeddings_map.get(seed.keyword.lower())
                is_dup = False

                if use_embedding and seed_emb:
                    from viraltracker.core.embeddings import cosine_similarity as _cosine
                    # Check against existing keywords
                    for ex_kw in existing_keywords:
                        ex_emb = embeddings_map.get(ex_kw.lower())
                        if ex_emb and _cosine(seed_emb, ex_emb) > 0.82:
                            is_dup = True
                            break
                    # Check against already-kept seeds
                    if not is_dup:
                        for kept_emb, _ in seen_embeddings:
                            if _cosine(seed_emb, kept_emb) > 0.82:
                                is_dup = True
                                break
                else:
                    # Jaccard fallback
                    if any(self._jaccard(stems, ex) > 0.6 for ex in existing_stems):
                        is_dup = True
                    if not is_dup and any(self._jaccard(stems, s) > 0.6 for s, _ in seen_stems):
                        is_dup = True

                if is_dup:
                    continue

                seen_stems.append((stems, seed))
                if seed_emb:
                    seen_embeddings.append((seed_emb, seed))
                topic_kept.append(seed)

            kept[topic] = topic_kept

        return kept

    # -------------------------------------------------------------------------
    # USAGE TRACKING
    # -------------------------------------------------------------------------

    def _track_usage(
        self,
        organization_id: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
    ) -> None:
        """Track API usage via UsageTracker."""
        try:
            from viraltracker.services.usage_tracker import UsageRecord, UsageTracker

            tracker = UsageTracker(self.supabase)
            record = UsageRecord(
                provider="anthropic",
                model=self.MODEL,
                tool_name="seo_pipeline",
                operation=f"brand_seed_{operation}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
            tracker.track(
                user_id=None,
                organization_id=organization_id,
                record=record,
            )
        except Exception as e:
            logger.warning(f"Failed to track usage: {e}")
