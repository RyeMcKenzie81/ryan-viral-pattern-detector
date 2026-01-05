"""
Belief-First Reverse Engineer Pipeline.

This pipeline reverse-engineers messaging into the Belief-First Master Canvas:
- draft_mode: Fill canvas from message inference + product DB (fast)
- research_mode: Run Reddit research, then revise canvas with observed evidence

Pipeline Nodes (11 total):
Draft Mode (1-4):
  FetchProductContext → ParseMessages → LayerClassifier → DraftCanvasAssembler

Research Mode (5-8, optional):
  → RedditResearchPlan → RedditScrape → ResearchExtractor → UMP_UMS_Updater

Final (9-11):
  → ClaimRiskAndBoundary → IntegrityCheck → Renderer
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union, List, Dict, Optional
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .metadata import NodeMetadata
from .states import BeliefReverseEngineerState
from ..agent.dependencies import AgentDependencies
from ..services.models import (
    EvidenceStatus,
    ProductContext,
    MessageClassification,
    BeliefFirstMasterCanvas,
    TraceItem,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DRAFT MODE NODES (1-4)
# =============================================================================


@dataclass
class FetchProductContextNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 1: Fetch product context from database.

    Retrieves comprehensive product information including:
    - Basic product info (name, category, format)
    - Ingredients with purpose and notes
    - Allowed/disallowed claims
    - Pre-built mechanisms
    - Proof assets
    - Contraindications

    All data comes with evidence_status=OBSERVED since it's from verified DB.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["product_id"],
        outputs=["product_context"],
        services=["product_context.get_product_context"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "ParseMessagesNode":
        logger.info(f"Node 1: Fetching product context for {ctx.state.product_id}")
        ctx.state.current_step = "fetching_product_context"

        try:
            # Fetch product context from database
            product_context = ctx.deps.product_context.get_product_context(
                ctx.state.product_id
            )

            if not product_context:
                ctx.state.error = f"Product {ctx.state.product_id} not found"
                ctx.state.current_step = "failed"
                return End({
                    "status": "error",
                    "error": ctx.state.error,
                    "step": "fetch_product_context"
                })

            # Store as dict for state compatibility
            ctx.state.product_context = product_context.model_dump()

            # Add trace item
            ctx.state.trace_map.append({
                "field_path": "product_context",
                "source": "product_db",
                "source_detail": f"products table + related tables for {ctx.state.product_id}",
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

            ctx.state.current_step = "product_context_fetched"
            logger.info(f"Fetched product context: {product_context.name}")
            return ParseMessagesNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to fetch product context: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "fetch_product_context"
            })


@dataclass
class ParseMessagesNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 2: Parse and analyze input messages.

    Uses LLM to extract from each message:
    - Topics detected (e.g., "sugar", "GLP-1", "bloating")
    - Implied audience
    - Implied outcomes/benefits
    - Language cues and tone
    - Emotional triggers

    This prepares messages for layer classification.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["messages", "product_context"],
        outputs=["parsed_messages"],
        services=["belief_analysis.parse_messages"],
        llm="Claude Sonnet",
        llm_purpose="Extract topics, audience, outcomes, and language cues from messages",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "LayerClassifierNode":
        logger.info(f"Node 2: Parsing {len(ctx.state.messages)} messages")
        ctx.state.current_step = "parsing_messages"

        try:
            if not ctx.state.messages:
                ctx.state.error = "No messages provided to parse"
                ctx.state.current_step = "failed"
                return End({
                    "status": "error",
                    "error": ctx.state.error,
                    "step": "parse_messages"
                })

            # Build context for parsing
            product_context = ctx.state.product_context or {}
            product_name = product_context.get("name", "Unknown Product")
            product_category = product_context.get("category", "Unknown Category")

            # Parse messages using belief analysis service
            parsed = await ctx.deps.belief_analysis.parse_messages(
                messages=ctx.state.messages,
                product_name=product_name,
                product_category=product_category,
                format_hint=ctx.state.format_hint,
                persona_hint=ctx.state.persona_hint,
            )

            ctx.state.parsed_messages = parsed

            # Add trace items for parsed messages
            for i, msg in enumerate(ctx.state.messages):
                ctx.state.trace_map.append({
                    "field_path": f"parsed_messages[{i}]",
                    "source": "message",
                    "source_detail": msg[:50] + "..." if len(msg) > 50 else msg,
                    "evidence_status": EvidenceStatus.INFERRED.value,
                })

            ctx.state.current_step = "messages_parsed"
            logger.info(f"Parsed {len(parsed)} messages")
            return LayerClassifierNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to parse messages: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "parse_messages"
            })


@dataclass
class LayerClassifierNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 3: Classify messages into belief-first layers.

    Uses LLM to classify each message into one of:
    - EXPRESSION: Final ad copy / hooks
    - UMP_SEED: Hints at unique mechanism problem
    - UMS_SEED: Hints at unique mechanism solution
    - PERSONA_FILTER: Audience targeting / identity
    - BENEFIT: Outcome/result claims
    - PROOF: Evidence, testimonials, data

    Also detects if message triggers compliance mode
    (medical claims, drug references, etc.)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["parsed_messages", "product_context"],
        outputs=["message_classifications"],
        services=["belief_analysis.classify_message_layer"],
        llm="Claude Sonnet",
        llm_purpose="Classify messages into belief-first canvas layers",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "DraftCanvasAssemblerNode":
        logger.info(f"Node 3: Classifying {len(ctx.state.parsed_messages or [])} messages")
        ctx.state.current_step = "classifying_layers"

        try:
            parsed = ctx.state.parsed_messages or []
            if not parsed:
                ctx.state.error = "No parsed messages to classify"
                ctx.state.current_step = "failed"
                return End({
                    "status": "error",
                    "error": ctx.state.error,
                    "step": "classify_layers"
                })

            product_context = ctx.state.product_context or {}
            product_category = product_context.get("category", "")
            disallowed_claims = product_context.get("disallowed_claims", [])

            # Classify each message
            classifications = []
            for parsed_msg in parsed:
                classification = await ctx.deps.belief_analysis.classify_message_layer(
                    parsed_message=parsed_msg,
                    product_category=product_category,
                    disallowed_claims=disallowed_claims,
                )
                classifications.append(classification)

            # Store as list of dicts for state compatibility
            ctx.state.message_classifications = [
                c.model_dump() if hasattr(c, 'model_dump') else c
                for c in classifications
            ]

            # Log any compliance triggers
            compliance_triggers = []
            for c in classifications:
                if isinstance(c, dict):
                    if c.get("triggers_compliance_mode"):
                        compliance_triggers.append(c)
                elif hasattr(c, 'triggers_compliance_mode') and c.triggers_compliance_mode:
                    compliance_triggers.append(c)
            if compliance_triggers:
                logger.warning(
                    f"{len(compliance_triggers)} messages triggered compliance mode"
                )

            ctx.state.current_step = "layers_classified"
            logger.info(f"Classified {len(classifications)} messages")
            return DraftCanvasAssemblerNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to classify layers: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "classify_layers"
            })


@dataclass
class DraftCanvasAssemblerNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 4: Assemble draft Belief-First Master Canvas.

    Uses LLM (Opus) to synthesize:
    - Message classifications → Belief sections (10-15)
    - Product context → Observed data with evidence trail
    - Gaps → "Research needed" plan for sections 1-9

    For draft_mode, sections 1-9 are marked as HYPOTHESIS.
    For research_mode, these will be updated with OBSERVED data later.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["message_classifications", "product_context", "format_hint", "persona_hint"],
        outputs=["draft_canvas", "research_needed", "proof_needed"],
        services=["belief_analysis.assemble_draft_canvas"],
        llm="Claude Opus",
        llm_purpose="Synthesize messages + product context into Belief-First Canvas",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> Union["RedditResearchPlanNode", "ClaimRiskAndBoundaryNode"]:
        logger.info("Node 4: Assembling draft canvas")
        ctx.state.current_step = "assembling_canvas"

        try:
            classifications = ctx.state.message_classifications or []
            product_context = ctx.state.product_context or {}

            if not classifications:
                ctx.state.error = "No message classifications to assemble"
                ctx.state.current_step = "failed"
                return End({
                    "status": "error",
                    "error": ctx.state.error,
                    "step": "assemble_canvas"
                })

            # Assemble draft canvas
            result = await ctx.deps.belief_analysis.assemble_draft_canvas(
                classifications=classifications,
                product_context=product_context,
                format_hint=ctx.state.format_hint,
                persona_hint=ctx.state.persona_hint,
            )

            ctx.state.draft_canvas = result.get("canvas", {})
            ctx.state.research_needed = result.get("research_needed", [])
            ctx.state.proof_needed = result.get("proof_needed", [])

            # Add trace items for canvas sections
            if ctx.state.draft_canvas:
                # Trace belief sections (10-15) as inferred from messages
                ctx.state.trace_map.append({
                    "field_path": "draft_canvas.belief_canvas",
                    "source": "message",
                    "source_detail": "Synthesized from message classifications",
                    "evidence_status": EvidenceStatus.INFERRED.value,
                })

                # Trace research sections (1-9) as hypothesis
                ctx.state.trace_map.append({
                    "field_path": "draft_canvas.research_canvas",
                    "source": "inferred",
                    "source_detail": "Hypothesized from messages (needs validation)",
                    "evidence_status": EvidenceStatus.HYPOTHESIS.value,
                })

            ctx.state.current_step = "canvas_assembled"
            logger.info(
                f"Assembled draft canvas with {len(ctx.state.research_needed)} "
                f"research gaps and {len(ctx.state.proof_needed)} proof gaps"
            )

            # Decide next step based on mode
            if ctx.state.research_mode:
                return RedditResearchPlanNode()
            else:
                # Draft mode - skip research, go to risk checking
                return ClaimRiskAndBoundaryNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to assemble canvas: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "assemble_canvas"
            })


# =============================================================================
# RESEARCH MODE NODES (5-8) - Placeholder declarations
# These will be implemented in the next phase
# =============================================================================


@dataclass
class RedditResearchPlanNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 5: Plan Reddit research based on canvas gaps.

    Validates user-provided subreddits/search_terms OR suggests
    defaults based on topic + persona. Creates research plan.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["research_needed", "subreddits", "search_terms", "persona_hint"],
        outputs=["research_plan"],
        services=["belief_analysis.create_research_plan"],
        llm="Claude Sonnet",
        llm_purpose="Plan Reddit research to fill canvas gaps",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "RedditScrapeNode":
        logger.info("Node 5: Planning Reddit research")
        ctx.state.current_step = "planning_research"

        try:
            # Validate that subreddits and search terms are provided
            if not ctx.state.subreddits and not ctx.state.search_terms:
                ctx.state.error = "Research mode requires subreddits and search_terms"
                ctx.state.current_step = "failed"
                return End({
                    "status": "error",
                    "error": ctx.state.error,
                    "step": "plan_research"
                })

            # Get detected topics from parsed messages for context
            detected_topics = []
            for parsed_msg in (ctx.state.parsed_messages or []):
                if isinstance(parsed_msg, dict):
                    detected_topics.extend(parsed_msg.get("detected_topics", []))

            # Get product context for category info
            product_context = ctx.state.product_context or {}
            product_category = product_context.get("category", "")
            product_name = product_context.get("name", "")

            # Build research plan
            ctx.state.research_plan = {
                "subreddits": ctx.state.subreddits,
                "search_terms": ctx.state.search_terms,
                "detected_topics": list(set(detected_topics)),
                "product_context": {
                    "name": product_name,
                    "category": product_category,
                },
                "persona_hint": ctx.state.persona_hint,
                "research_gaps": ctx.state.research_needed,
                "config": ctx.state.scrape_config or {
                    "max_posts_per_query": 25,
                    "max_comments_per_post": 50,
                    "min_score_threshold": 5,
                    "time_window_days": 365,
                    "include_top_level_comments_only": True,
                    "dedupe": True,
                },
                "signal_types": ["pain", "solutions", "patterns", "language", "jtbd"],
                "status": "planned",
            }

            # Add trace item
            ctx.state.trace_map.append({
                "field_path": "research_plan",
                "source": "user_input",
                "source_detail": f"subreddits: {ctx.state.subreddits}, terms: {ctx.state.search_terms}",
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

            ctx.state.current_step = "research_planned"
            logger.info(
                f"Research plan created: {len(ctx.state.subreddits)} subreddits, "
                f"{len(ctx.state.search_terms)} search terms"
            )
            return RedditScrapeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to plan research: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "plan_research"
            })


@dataclass
class RedditScrapeNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 6: Scrape Reddit based on research plan.

    Uses TWO-PASS scraping for cost efficiency:
    1. First pass: Scrape posts only (no comments) - cheap
    2. Filter posts locally by engagement and relevance
    3. Second pass: Scrape comments only for filtered posts - targeted

    This approach saves significant Apify costs by avoiding comment
    scraping for posts that will be filtered out anyway.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["research_plan", "scrape_config"],
        outputs=["reddit_raw", "posts_analyzed", "comments_analyzed"],
        services=["reddit_sentiment.scrape_reddit", "reddit_sentiment.scrape_by_urls"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "ResearchExtractorNode":
        logger.info("Node 6: Scraping Reddit (two-pass mode)")
        ctx.state.current_step = "scraping_reddit"

        try:
            research_plan = ctx.state.research_plan or {}
            subreddits = research_plan.get("subreddits", [])
            search_terms = research_plan.get("search_terms", [])
            config = research_plan.get("config", {})

            if not subreddits and not search_terms:
                logger.warning("No subreddits or search terms in research plan")
                ctx.state.reddit_raw = []
                return ResearchExtractorNode()

            # Build topic context for filtering
            product_context = research_plan.get("product_context", {})
            detected_topics = research_plan.get("detected_topics", [])

            # Apply guardrails
            max_total_posts = config.get("max_total_posts", 100)
            max_api_calls = config.get("max_api_calls", 10)
            posts_per_query = min(config.get("max_posts_per_query", 25), 50)  # Hard cap at 50
            max_comments_per_post = config.get("max_comments_per_post", 50)

            # Quality filters
            min_upvotes = config.get("min_upvotes", 10)
            min_comments = config.get("min_comments", 3)
            relevance_threshold = config.get("relevance_threshold", 0.5)
            top_percentile = config.get("top_percentile", 0.30)

            # =====================================================================
            # PASS 1: Scrape posts only (no comments) - CHEAP
            # =====================================================================
            logger.info("=== PASS 1: Scraping posts only (no comments) ===")

            from ..services.models import RedditPost, RedditScrapeConfig

            all_posts = []
            api_calls_made = 0
            hit_limit = False

            for subreddit in subreddits:
                if hit_limit:
                    break
                for term in search_terms:
                    # Check guardrails
                    if api_calls_made >= max_api_calls - 1:  # Reserve 1 call for pass 2
                        logger.warning(f"Reserving last API call for pass 2, stopping pass 1")
                        hit_limit = True
                        break
                    if len(all_posts) >= max_total_posts:
                        logger.warning(f"Hit max total posts limit ({max_total_posts})")
                        hit_limit = True
                        break

                    try:
                        # Create config for posts-only scrape
                        scrape_config = RedditScrapeConfig(
                            search_queries=[term],
                            subreddits=[subreddit],
                            max_posts=posts_per_query,
                            sort_by="relevance",
                            timeframe="year",
                            scrape_comments=False,  # KEY: No comments in pass 1
                            max_comments_per_post=0,
                        )
                        posts, _ = ctx.deps.reddit_sentiment.scrape_reddit(scrape_config)
                        all_posts.extend(posts)
                        api_calls_made += 1
                        logger.info(
                            f"Pass 1: Scraped {len(posts)} posts from r/{subreddit} "
                            f"for '{term}' (call {api_calls_made}/{max_api_calls})"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to scrape r/{subreddit} for '{term}': {e}")
                        continue

            # Dedupe by post ID
            if config.get("dedupe", True):
                seen_ids = set()
                unique_posts = []
                for post in all_posts:
                    post_id = post.reddit_id if hasattr(post, 'reddit_id') else post.get("reddit_id")
                    if post_id and post_id not in seen_ids:
                        seen_ids.add(post_id)
                        unique_posts.append(post)
                all_posts = unique_posts

            logger.info(f"Pass 1 complete: {len(all_posts)} unique posts (0 comments)")

            # =====================================================================
            # FILTER: Apply quality filters BEFORE scraping comments
            # =====================================================================
            logger.info("=== FILTERING: Applying quality filters ===")

            filtered_posts = all_posts

            if filtered_posts:
                # Step 1: Engagement filter
                filtered_posts = ctx.deps.reddit_sentiment.filter_by_engagement(
                    filtered_posts,
                    min_upvotes=min_upvotes,
                    min_comments=min_comments
                )
                logger.info(f"After engagement filter: {len(filtered_posts)} posts")

                # Step 2: Relevance scoring (if enabled)
                if filtered_posts and relevance_threshold > 0:
                    product_ctx = ctx.state.product_context or {}
                    persona_ctx = f"People interested in {product_ctx.get('name', 'this product')} "
                    persona_ctx += f"in the {product_ctx.get('category', 'health')} category"
                    topic_ctx = f"{product_ctx.get('name', '')} {' '.join(detected_topics)}"

                    try:
                        filtered_posts = await ctx.deps.reddit_sentiment.score_relevance(
                            filtered_posts,
                            persona_context=persona_ctx,
                            topic_context=topic_ctx,
                            threshold=relevance_threshold
                        )
                        logger.info(f"After relevance filter: {len(filtered_posts)} posts")
                    except Exception as e:
                        logger.warning(f"Relevance scoring failed, skipping: {e}")

                # Step 3: Top percentile selection
                if filtered_posts and top_percentile < 1.0:
                    try:
                        filtered_posts = ctx.deps.reddit_sentiment.select_top_percentile(
                            filtered_posts,
                            percentile=top_percentile
                        )
                        logger.info(f"After top {int(top_percentile*100)}% selection: {len(filtered_posts)} posts")
                    except Exception as e:
                        logger.warning(f"Top percentile selection failed, skipping: {e}")

            # =====================================================================
            # PASS 2: Scrape comments only for filtered posts - TARGETED
            # =====================================================================
            logger.info("=== PASS 2: Scraping comments for filtered posts ===")

            final_posts = []
            total_comments = 0

            if filtered_posts:
                # Collect URLs of filtered posts
                filtered_urls = []
                for post in filtered_posts:
                    url = post.url if hasattr(post, 'url') else post.get("url")
                    if url:
                        filtered_urls.append(url)

                if filtered_urls:
                    logger.info(f"Pass 2: Scraping comments for {len(filtered_urls)} filtered posts")
                    api_calls_made += 1

                    try:
                        # Scrape comments for filtered posts by URL
                        posts_with_comments, comments = ctx.deps.reddit_sentiment.scrape_by_urls(
                            urls=filtered_urls,
                            scrape_comments=True,
                            max_comments_per_post=max_comments_per_post,
                        )

                        # Match comments back to posts
                        # The API returns posts and comments separately, need to attach
                        comment_by_parent = {}
                        for comment in comments:
                            parent_id = comment.parent_id if hasattr(comment, 'parent_id') else comment.get("parent_id")
                            if parent_id:
                                if parent_id not in comment_by_parent:
                                    comment_by_parent[parent_id] = []
                                comment_by_parent[parent_id].append(
                                    comment.model_dump() if hasattr(comment, 'model_dump') else comment
                                )

                        for post in posts_with_comments:
                            post_dict = post.model_dump() if hasattr(post, 'model_dump') else post
                            post_id = post_dict.get("reddit_id") or post_dict.get("id")
                            post_dict["comments"] = comment_by_parent.get(post_id, [])
                            total_comments += len(post_dict["comments"])
                            final_posts.append(post_dict)

                        logger.info(
                            f"Pass 2 complete: {len(final_posts)} posts with "
                            f"{total_comments} total comments"
                        )
                    except Exception as e:
                        logger.warning(f"Pass 2 failed, using posts without comments: {e}")
                        # Fallback: use filtered posts without comments
                        for post in filtered_posts:
                            post_dict = post.model_dump() if hasattr(post, 'model_dump') else post
                            post_dict["comments"] = []
                            final_posts.append(post_dict)
                else:
                    logger.warning("No valid URLs found for pass 2")
                    for post in filtered_posts:
                        post_dict = post.model_dump() if hasattr(post, 'model_dump') else post
                        post_dict["comments"] = []
                        final_posts.append(post_dict)

            # Store results
            ctx.state.reddit_raw = final_posts
            ctx.state.posts_analyzed = len(final_posts)
            ctx.state.comments_analyzed = total_comments

            # Add trace item
            ctx.state.trace_map.append({
                "field_path": "reddit_raw",
                "source": "reddit_research",
                "source_detail": (
                    f"Two-pass scrape: {len(subreddits)} subreddits, "
                    f"{len(search_terms)} terms, {api_calls_made} API calls, "
                    f"{len(all_posts)} posts found -> {len(final_posts)} filtered"
                ),
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

            ctx.state.current_step = "reddit_scraped"
            logger.info(
                f"Reddit scrape complete: {ctx.state.posts_analyzed} posts with "
                f"{ctx.state.comments_analyzed} comments "
                f"(saved ~{len(all_posts) - len(final_posts)} comment scrapes)"
            )
            return ResearchExtractorNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to scrape Reddit: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "scrape_reddit"
            })


@dataclass
class ResearchExtractorNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 7: Extract belief signals from Reddit data.

    Uses LLM to extract:
    - Pain/symptoms with specificity
    - Solutions attempted and why they failed
    - Patterns (triggers, worsens, improves)
    - Customer language for the problem
    - JTBD candidates
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reddit_raw", "research_plan"],
        outputs=["reddit_bundle"],
        services=["reddit_sentiment.extract_belief_signals"],
        llm="Claude Sonnet",
        llm_purpose="Extract belief signals from Reddit posts and comments",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "UMPUMSUpdaterNode":
        logger.info("Node 7: Extracting belief signals from Reddit")
        ctx.state.current_step = "extracting_signals"

        try:
            reddit_raw = ctx.state.reddit_raw or []
            research_plan = ctx.state.research_plan or {}

            if not reddit_raw:
                logger.warning("No Reddit data to extract signals from")
                ctx.state.reddit_bundle = {
                    "queries_run": [],
                    "posts_analyzed_count": 0,
                    "comments_analyzed_count": 0,
                    "extracted_pain": [],
                    "extracted_solutions_attempted": [],
                    "extracted_language_bank": {},
                    "pattern_detection": {},
                    "jtbd_candidates": {},
                }
                return UMPUMSUpdaterNode()

            # Build topic context from research plan
            product_context = research_plan.get("product_context", {})
            detected_topics = research_plan.get("detected_topics", [])
            topic_context = f"Product: {product_context.get('name', 'Unknown')}. "
            topic_context += f"Category: {product_context.get('category', 'Unknown')}. "
            topic_context += f"Topics of interest: {', '.join(detected_topics)}."

            if research_plan.get("persona_hint"):
                topic_context += f" Target persona: {research_plan['persona_hint']}."

            # Extract belief signals using the sentiment service
            signal_types = research_plan.get(
                "signal_types",
                ["pain", "solutions", "patterns", "language", "jtbd"]
            )

            bundle = await ctx.deps.reddit_sentiment.extract_belief_signals(
                posts=reddit_raw,
                signal_types=signal_types,
                topic_context=topic_context,
            )

            # Store the bundle
            if hasattr(bundle, 'model_dump'):
                ctx.state.reddit_bundle = bundle.model_dump()
            else:
                ctx.state.reddit_bundle = bundle

            # Add trace items for extracted signals
            for signal_type in signal_types:
                field_name = f"extracted_{signal_type}" if signal_type != "jtbd" else "jtbd_candidates"
                if ctx.state.reddit_bundle.get(field_name):
                    ctx.state.trace_map.append({
                        "field_path": f"reddit_bundle.{field_name}",
                        "source": "reddit_research",
                        "source_detail": f"Extracted from {ctx.state.posts_analyzed} posts via LLM",
                        "evidence_status": EvidenceStatus.OBSERVED.value,
                    })

            ctx.state.current_step = "signals_extracted"
            logger.info(
                f"Extracted signals: {len(ctx.state.reddit_bundle.get('extracted_pain', []))} pain points, "
                f"{len(ctx.state.reddit_bundle.get('extracted_solutions_attempted', []))} solutions"
            )
            return UMPUMSUpdaterNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to extract signals: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "extract_signals"
            })


@dataclass
class UMPUMSUpdaterNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 8: Update canvas with research findings.

    Uses LLM (Opus) to:
    - Update sections 3-9 with OBSERVED evidence
    - Strengthen section 12 UMP with real customer language
    - Promote hypothesis → observed where evidence supports
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["draft_canvas", "reddit_bundle", "product_context"],
        outputs=["updated_canvas"],
        services=["belief_analysis.update_canvas_with_research"],
        llm="Claude Opus",
        llm_purpose="Update canvas sections with Reddit research evidence",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "ClaimRiskAndBoundaryNode":
        logger.info("Node 8: Updating canvas with research findings")
        ctx.state.current_step = "updating_canvas"

        try:
            draft_canvas = ctx.state.draft_canvas or {}
            reddit_bundle = ctx.state.reddit_bundle or {}
            product_context = ctx.state.product_context or {}

            if not reddit_bundle or not reddit_bundle.get("extracted_pain"):
                logger.warning("No research signals to update canvas with")
                ctx.state.updated_canvas = draft_canvas
                return ClaimRiskAndBoundaryNode()

            # Update canvas with research findings using belief analysis service
            updated = await ctx.deps.belief_analysis.update_canvas_with_research(
                draft_canvas=draft_canvas,
                reddit_bundle=reddit_bundle,
                product_context=product_context,
            )

            ctx.state.updated_canvas = updated

            # Add trace items for updated sections
            updated_sections = []

            # Research sections (1-9) that may have been updated
            research_sections = [
                ("observed_pain", "Section 3: Observed Pain"),
                ("pattern_detection", "Section 4: Pattern Detection"),
                ("then_vs_now", "Section 5: Then vs Now"),
                ("solutions_attempted", "Section 6: Solutions Attempted"),
                ("desired_progress", "Section 7: Desired Progress"),
                ("knowledge_gaps", "Section 8: Knowledge Gaps"),
                ("candidate_root_causes", "Section 9: Root Causes"),
            ]

            for field, section_name in research_sections:
                research_canvas = updated.get("research_canvas", {})
                if research_canvas.get(field):
                    updated_sections.append(section_name)
                    ctx.state.trace_map.append({
                        "field_path": f"updated_canvas.research_canvas.{field}",
                        "source": "reddit_research",
                        "source_detail": f"Updated from {ctx.state.posts_analyzed} Reddit posts",
                        "evidence_status": EvidenceStatus.OBSERVED.value,
                    })

            # UMP section (12) that may have been strengthened
            belief_canvas = updated.get("belief_canvas", {})
            unique_mechanism = belief_canvas.get("unique_mechanism", {})
            if unique_mechanism.get("ump"):
                ctx.state.trace_map.append({
                    "field_path": "updated_canvas.belief_canvas.unique_mechanism.ump",
                    "source": "reddit_research",
                    "source_detail": "Strengthened with customer language from Reddit",
                    "evidence_status": EvidenceStatus.OBSERVED.value,
                })
                updated_sections.append("Section 12: UMP")

            ctx.state.current_step = "canvas_updated"
            logger.info(f"Updated canvas sections: {', '.join(updated_sections) or 'none'}")
            return ClaimRiskAndBoundaryNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to update canvas: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "update_canvas"
            })


# =============================================================================
# FINAL NODES (9-11)
# =============================================================================


@dataclass
class ClaimRiskAndBoundaryNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 9: Detect claim risks and boundary violations.

    Scans canvas for:
    - Drug references / medical claims
    - Promise boundary violations
    - Overpromises
    - Contradictions
    - Ambiguous claims

    Rewrites unsafe fields while preserving meaning.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["draft_canvas", "updated_canvas", "product_context", "message_classifications"],
        outputs=["risk_flags"],
        services=["belief_analysis.detect_risks"],
        llm="Claude Sonnet",
        llm_purpose="Detect claim risks and compliance issues",
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "IntegrityCheckNode":
        logger.info("Node 9: Checking claim risks")
        ctx.state.current_step = "checking_risks"

        try:
            # Use updated canvas if available (research mode), else draft
            canvas = ctx.state.updated_canvas or ctx.state.draft_canvas or {}
            product_context = ctx.state.product_context or {}

            # Detect risks
            risk_flags = await ctx.deps.belief_analysis.detect_risks(
                canvas=canvas,
                product_context=product_context,
                message_classifications=ctx.state.message_classifications or [],
            )

            ctx.state.risk_flags = [
                r.model_dump() if hasattr(r, 'model_dump') else r
                for r in risk_flags
            ]

            # Log risk summary
            high_risks = [r for r in ctx.state.risk_flags if r.get("severity") == "high"]
            if high_risks:
                logger.warning(f"Found {len(high_risks)} high-severity risk flags")

            ctx.state.current_step = "risks_checked"
            logger.info(f"Detected {len(ctx.state.risk_flags)} risk flags")
            return IntegrityCheckNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to check risks: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "check_risks"
            })


@dataclass
class IntegrityCheckNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 10: Validate canvas integrity.

    Rule-based checks:
    - Research precedes framing (allow draft_mode exception but flag)
    - UMP explains failure before success
    - Features appear only after benefits (section 13)
    - Proof reinforces belief, never introduces
    - Constraints respected (section 11)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["draft_canvas", "updated_canvas", "draft_mode"],
        outputs=["integrity_results"],
        services=["belief_analysis.run_integrity_checks"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> "RendererNode":
        logger.info("Node 10: Running integrity checks")
        ctx.state.current_step = "checking_integrity"

        try:
            # Use updated canvas if available (research mode), else draft
            canvas = ctx.state.updated_canvas or ctx.state.draft_canvas or {}

            # Run integrity checks
            results = ctx.deps.belief_analysis.run_integrity_checks(
                canvas=canvas,
                draft_mode=ctx.state.draft_mode,
            )

            ctx.state.integrity_results = results

            # Log failures
            failures = [r for r in results if not r.get("passed", True)]
            if failures:
                logger.warning(f"{len(failures)} integrity checks failed")
                for f in failures:
                    logger.warning(f"  - {f.get('check')}: {f.get('notes')}")

            ctx.state.current_step = "integrity_checked"
            return RendererNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed integrity checks: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "integrity_check"
            })


@dataclass
class RendererNode(BaseNode[BeliefReverseEngineerState]):
    """
    Node 11: Render final canvas output.

    Produces:
    - Markdown rendering of complete canvas
    - JSON structure for UI rendering
    - Complete trace map
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["draft_canvas", "updated_canvas", "risk_flags", "integrity_results", "trace_map"],
        outputs=["final_canvas", "rendered_markdown"],
        services=["belief_analysis.render_markdown_canvas"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BeliefReverseEngineerState, AgentDependencies]
    ) -> End[dict]:
        logger.info("Node 11: Rendering final canvas")
        ctx.state.current_step = "rendering"

        try:
            # Use updated canvas if available (research mode), else draft
            canvas = ctx.state.updated_canvas or ctx.state.draft_canvas or {}
            product_context = ctx.state.product_context or {}

            # Store final canvas
            ctx.state.final_canvas = canvas

            # Render markdown
            ctx.state.rendered_markdown = ctx.deps.belief_analysis.render_markdown_canvas(
                canvas=canvas,
                product_name=product_context.get("name", "Unknown Product"),
            )

            ctx.state.current_step = "complete"

            # Calculate completeness score
            completeness = _calculate_completeness(canvas)
            ctx.state.canvas_completeness_score = completeness

            logger.info(f"Canvas complete. Completeness: {completeness:.1%}")

            return End({
                "status": "success",
                "canvas": ctx.state.final_canvas,
                "rendered_markdown": ctx.state.rendered_markdown,
                "risk_flags": ctx.state.risk_flags,
                "integrity_results": ctx.state.integrity_results,
                "trace_map": ctx.state.trace_map,
                "gaps": {
                    "research_needed": ctx.state.research_needed,
                    "proof_needed": ctx.state.proof_needed,
                },
                "metrics": {
                    "completeness_score": completeness,
                    "messages_processed": len(ctx.state.messages),
                    "posts_analyzed": ctx.state.posts_analyzed,
                    "comments_analyzed": ctx.state.comments_analyzed,
                },
                "mode": "research" if ctx.state.research_mode else "draft",
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Failed to render canvas: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "step": "render"
            })


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _calculate_completeness(canvas: dict) -> float:
    """
    Calculate canvas completeness score (0.0 to 1.0).

    Weights:
    - Research sections (1-9): 40%
    - Belief sections (10-15): 60%
    """
    if not canvas:
        return 0.0

    research_canvas = canvas.get("research_canvas", {})
    belief_canvas = canvas.get("belief_canvas", {})

    # Count filled research sections
    research_sections = [
        "market_context", "persona_context", "observed_pain",
        "pattern_detection", "then_vs_now", "solutions_attempted",
        "desired_progress", "knowledge_gaps", "candidate_root_causes"
    ]
    research_filled = sum(
        1 for s in research_sections
        if research_canvas.get(s)
    )
    research_score = research_filled / len(research_sections) if research_sections else 0

    # Count filled belief sections
    belief_sections = [
        "belief_context", "persona_filter", "unique_mechanism",
        "progress_justification", "proof_stack", "expression"
    ]
    belief_filled = sum(
        1 for s in belief_sections
        if belief_canvas.get(s)
    )
    belief_score = belief_filled / len(belief_sections) if belief_sections else 0

    # Weighted average
    return (research_score * 0.4) + (belief_score * 0.6)


# =============================================================================
# GRAPH DEFINITION
# =============================================================================


belief_reverse_engineer_graph = Graph(
    nodes=(
        FetchProductContextNode,
        ParseMessagesNode,
        LayerClassifierNode,
        DraftCanvasAssemblerNode,
        RedditResearchPlanNode,
        RedditScrapeNode,
        ResearchExtractorNode,
        UMPUMSUpdaterNode,
        ClaimRiskAndBoundaryNode,
        IntegrityCheckNode,
        RendererNode,
    ),
    name="belief_reverse_engineer"
)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


async def run_belief_reverse_engineer(
    product_id: UUID,
    messages: List[str],
    draft_mode: bool = True,
    research_mode: bool = False,
    format_hint: Optional[str] = None,
    persona_hint: Optional[str] = None,
    subreddits: Optional[List[str]] = None,
    search_terms: Optional[List[str]] = None,
    scrape_config: Optional[Dict] = None,
) -> dict:
    """
    Run the belief reverse engineer pipeline.

    This is a convenience function that creates dependencies
    and runs the full pipeline.

    Args:
        product_id: UUID of the product to build context from
        messages: List of rough messaging hooks/claims to analyze
        draft_mode: If True, skip Reddit research (default)
        research_mode: If True, run Reddit research pack
        format_hint: Optional format context (ad, landing_page, video, email)
        persona_hint: Optional persona context (e.g., "GLP-1 user", "busy parent")
        subreddits: List of subreddits to search (required if research_mode)
        search_terms: List of search terms (required if research_mode)
        scrape_config: Optional Reddit scrape configuration

    Returns:
        Pipeline result with canvas, risk flags, gaps, and metrics

    Example:
        >>> result = await run_belief_reverse_engineer(
        ...     product_id=UUID("..."),
        ...     messages=["Boba without the sugar crash", "Protein that tastes like dessert"],
        ...     draft_mode=True,
        ... )
        >>> print(result["status"])  # "success"
        >>> print(result["canvas"])  # Full Belief-First Canvas
    """
    from ..agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    # Build initial state
    state = BeliefReverseEngineerState(
        product_id=product_id,
        messages=messages,
        draft_mode=draft_mode,
        research_mode=research_mode,
        format_hint=format_hint,
        persona_hint=persona_hint,
        subreddits=subreddits or [],
        search_terms=search_terms or [],
        scrape_config=scrape_config or {},
    )

    result = await belief_reverse_engineer_graph.run(
        FetchProductContextNode(),
        state=state,
        deps=deps
    )

    return result.output
