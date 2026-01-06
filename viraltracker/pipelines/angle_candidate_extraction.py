"""
Angle Candidate Extraction Pipeline - Pydantic Graph for Logfire Visibility.

This pipeline provides structured extraction of angle candidates with full
Logfire tracing for debugging and monitoring.

Use cases:
- Batch extraction from multiple sources
- Re-extraction with updated prompts
- Monitoring extraction quality via Logfire traces

Architecture:
    UI/CLI -> AngleCandidateExtractionGraph -> AngleCandidateService
                                            -> BeliefAnalysisService
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext, Graph

logger = logging.getLogger(__name__)


# ============================================================================
# State
# ============================================================================

@dataclass
class ExtractionState:
    """State for angle candidate extraction pipeline."""
    # Input parameters
    product_id: UUID
    source_type: str  # 'belief_reverse_engineer', 'reddit', 'competitor', 'brand', 'ad_performance'
    source_data: Dict[str, Any] = field(default_factory=dict)

    # Optional context
    source_run_id: Optional[UUID] = None
    competitor_id: Optional[UUID] = None

    # Populated during extraction
    extracted_candidates: List[Dict[str, Any]] = field(default_factory=list)
    similarity_results: List[Dict[str, Any]] = field(default_factory=list)
    saved_candidates: List[Dict[str, Any]] = field(default_factory=list)
    merged_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None
    stats: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# Nodes
# ============================================================================

@dataclass
class ExtractFromSourceNode(BaseNode[ExtractionState]):
    """
    Extract candidate insights from source data.

    This node analyzes the source data and extracts potential angle candidates
    based on the source type (BRE analysis, Reddit posts, competitor data, etc.)
    """

    async def run(
        self,
        ctx: GraphRunContext[ExtractionState, Any]
    ) -> Union["SimilarityCheckNode", End[Dict[str, Any]]]:
        """Extract candidates from source data."""
        ctx.state.current_step = "extracting"
        logger.info(f"Extracting candidates from {ctx.state.source_type}")

        try:
            from viraltracker.services.angle_candidate_service import AngleCandidateService
            service = AngleCandidateService()

            source_data = ctx.state.source_data
            source_type = ctx.state.source_type
            extracted = []

            # Extract based on source type
            if source_type == "belief_reverse_engineer":
                # Extract from BRE analysis results
                extracted = self._extract_from_bre(source_data)

            elif source_type == "reddit_research":
                # Extract from Reddit posts/analysis
                extracted = self._extract_from_reddit(source_data)

            elif source_type == "competitor_research":
                # Extract from competitor analysis
                extracted = self._extract_from_competitor(source_data)

            elif source_type == "brand_research":
                # Extract from brand/consumer research
                extracted = self._extract_from_brand(source_data)

            elif source_type == "ad_performance":
                # Extract from ad performance analysis
                extracted = self._extract_from_ad_performance(source_data)

            else:
                logger.warning(f"Unknown source type: {source_type}")
                extracted = []

            ctx.state.extracted_candidates = extracted
            ctx.state.stats["extracted"] = len(extracted)

            logger.info(f"Extracted {len(extracted)} candidates from {source_type}")

            if not extracted:
                return End({
                    "status": "no_candidates",
                    "message": "No candidates extracted from source data",
                    "stats": ctx.state.stats
                })

            return SimilarityCheckNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Extraction failed: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "stats": ctx.state.stats
            })

    def _extract_from_bre(self, data: Dict) -> List[Dict]:
        """Extract candidates from Belief Reverse Engineer results."""
        candidates = []

        # Extract pain signals
        for pain in data.get("pain_signals", []):
            candidates.append({
                "name": pain.get("signal", "")[:50],
                "belief_statement": pain.get("signal", ""),
                "candidate_type": "pain_signal",
                "explanation": pain.get("explanation", "")
            })

        # Extract JTBDs
        for jtbd in data.get("jtbds", []):
            candidates.append({
                "name": jtbd.get("name", "")[:50],
                "belief_statement": jtbd.get("progress_statement", jtbd.get("name", "")),
                "candidate_type": "jtbd",
                "explanation": jtbd.get("explanation", "")
            })

        # Extract hypotheses
        for hyp in data.get("hypotheses", []):
            candidates.append({
                "name": hyp.get("name", "")[:50],
                "belief_statement": hyp.get("hypothesis", ""),
                "candidate_type": "ad_hypothesis",
                "explanation": hyp.get("rationale", "")
            })

        return candidates

    def _extract_from_reddit(self, data: Dict) -> List[Dict]:
        """Extract candidates from Reddit research."""
        candidates = []

        # Extract from posts with high engagement
        for post in data.get("posts", []):
            if post.get("score", 0) > 10:  # Minimum engagement threshold
                candidates.append({
                    "name": post.get("title", "")[:50],
                    "belief_statement": post.get("title", ""),
                    "candidate_type": "quote",
                    "explanation": f"From r/{post.get('subreddit', 'unknown')}",
                    "engagement_score": post.get("score", 0),
                    "source_url": post.get("url", ""),
                    "source_post_id": post.get("id", "")
                })

        # Extract from patterns identified
        for pattern in data.get("patterns", []):
            candidates.append({
                "name": pattern.get("name", "")[:50],
                "belief_statement": pattern.get("description", ""),
                "candidate_type": "pattern",
                "explanation": pattern.get("evidence", "")
            })

        return candidates

    def _extract_from_competitor(self, data: Dict) -> List[Dict]:
        """Extract candidates from competitor research."""
        candidates = []

        # Extract UMPs (Unique Mechanism Problems)
        for ump in data.get("umps", []):
            candidates.append({
                "name": ump.get("name", "")[:50],
                "belief_statement": ump.get("problem_statement", ""),
                "candidate_type": "ump",
                "explanation": ump.get("how_addressed", "")
            })

        # Extract UMSs (Unique Mechanism Solutions)
        for ums in data.get("umss", []):
            candidates.append({
                "name": ums.get("name", "")[:50],
                "belief_statement": ums.get("solution_statement", ""),
                "candidate_type": "ums",
                "explanation": ums.get("differentiation", "")
            })

        # Extract from competitor ad angles
        for angle in data.get("angles", []):
            candidates.append({
                "name": angle.get("name", "")[:50],
                "belief_statement": angle.get("angle", ""),
                "candidate_type": "ad_hypothesis",
                "explanation": f"From competitor: {data.get('competitor_name', 'unknown')}"
            })

        return candidates

    def _extract_from_brand(self, data: Dict) -> List[Dict]:
        """Extract candidates from brand/consumer research."""
        candidates = []

        # Extract customer voice quotes
        for quote in data.get("quotes", []):
            candidates.append({
                "name": quote.get("theme", "Customer Voice")[:50],
                "belief_statement": quote.get("text", ""),
                "candidate_type": "quote",
                "explanation": quote.get("context", "")
            })

        # Extract identified patterns
        for pattern in data.get("patterns", []):
            candidates.append({
                "name": pattern.get("name", "")[:50],
                "belief_statement": pattern.get("description", ""),
                "candidate_type": "pattern",
                "explanation": pattern.get("evidence", "")
            })

        return candidates

    def _extract_from_ad_performance(self, data: Dict) -> List[Dict]:
        """Extract candidates from ad performance analysis."""
        candidates = []

        # Extract winning hooks
        for hook in data.get("winning_hooks", []):
            candidates.append({
                "name": hook.get("hook_text", "")[:50],
                "belief_statement": hook.get("hook_text", ""),
                "candidate_type": "ad_hypothesis",
                "explanation": f"CTR: {hook.get('ctr', 'N/A')}, ROAS: {hook.get('roas', 'N/A')}"
            })

        # Extract hypotheses from analysis
        for hyp in data.get("hypotheses", []):
            candidates.append({
                "name": hyp.get("name", "")[:50],
                "belief_statement": hyp.get("hypothesis", ""),
                "candidate_type": "ad_hypothesis",
                "explanation": hyp.get("evidence", "")
            })

        return candidates


@dataclass
class SimilarityCheckNode(BaseNode[ExtractionState]):
    """
    Check extracted candidates for similarity to existing candidates.

    This node deduplicates candidates by finding similar existing ones
    and either merging evidence or creating new candidates.
    """

    async def run(
        self,
        ctx: GraphRunContext[ExtractionState, Any]
    ) -> "SaveCandidatesNode":
        """Check similarity and prepare for saving."""
        ctx.state.current_step = "checking_similarity"
        logger.info(f"Checking similarity for {len(ctx.state.extracted_candidates)} candidates")

        try:
            from viraltracker.services.angle_candidate_service import AngleCandidateService
            service = AngleCandidateService()

            similarity_results = []

            for candidate in ctx.state.extracted_candidates:
                # Check for similar existing candidate
                similar = service.find_similar_candidate(
                    product_id=ctx.state.product_id,
                    belief_statement=candidate["belief_statement"]
                )

                similarity_results.append({
                    "candidate": candidate,
                    "similar_existing": similar.model_dump() if similar else None,
                    "action": "merge" if similar else "create"
                })

            ctx.state.similarity_results = similarity_results

            # Count actions
            merge_count = sum(1 for r in similarity_results if r["action"] == "merge")
            create_count = sum(1 for r in similarity_results if r["action"] == "create")

            ctx.state.stats["to_merge"] = merge_count
            ctx.state.stats["to_create"] = create_count

            logger.info(f"Similarity check: {create_count} new, {merge_count} to merge")

            return SaveCandidatesNode()

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Similarity check failed: {e}")
            # Continue to save even if similarity check fails
            ctx.state.similarity_results = [
                {"candidate": c, "similar_existing": None, "action": "create"}
                for c in ctx.state.extracted_candidates
            ]
            return SaveCandidatesNode()


@dataclass
class SaveCandidatesNode(BaseNode[ExtractionState]):
    """
    Save candidates to the database.

    Creates new candidates or adds evidence to existing similar ones.
    """

    async def run(
        self,
        ctx: GraphRunContext[ExtractionState, Any]
    ) -> End[Dict[str, Any]]:
        """Save candidates to database."""
        ctx.state.current_step = "saving"
        logger.info("Saving candidates to database")

        try:
            from viraltracker.services.angle_candidate_service import AngleCandidateService
            service = AngleCandidateService()

            saved = []
            merged = []

            for result in ctx.state.similarity_results:
                candidate_data = result["candidate"]
                similar_existing = result["similar_existing"]
                action = result["action"]

                if action == "merge" and similar_existing:
                    # Add evidence to existing candidate
                    try:
                        service.add_evidence(
                            candidate_id=UUID(similar_existing["id"]),
                            evidence_type=candidate_data.get("candidate_type", "pattern"),
                            evidence_text=candidate_data["belief_statement"],
                            source_type=ctx.state.source_type,
                            source_run_id=ctx.state.source_run_id,
                            engagement_score=candidate_data.get("engagement_score"),
                            source_url=candidate_data.get("source_url"),
                            source_post_id=candidate_data.get("source_post_id")
                        )
                        merged.append({
                            "merged_into": similar_existing["id"],
                            "belief_statement": candidate_data["belief_statement"]
                        })
                    except Exception as e:
                        logger.warning(f"Failed to merge evidence: {e}")

                else:
                    # Create new candidate
                    try:
                        new_candidate = service.create_candidate(
                            product_id=ctx.state.product_id,
                            name=candidate_data["name"],
                            belief_statement=candidate_data["belief_statement"],
                            candidate_type=candidate_data.get("candidate_type", "pattern"),
                            source_type=ctx.state.source_type,
                            source_run_id=ctx.state.source_run_id,
                            competitor_id=ctx.state.competitor_id,
                            explanation=candidate_data.get("explanation")
                        )

                        # Add initial evidence
                        if new_candidate:
                            service.add_evidence(
                                candidate_id=new_candidate.id,
                                evidence_type=candidate_data.get("candidate_type", "pattern"),
                                evidence_text=candidate_data["belief_statement"],
                                source_type=ctx.state.source_type,
                                source_run_id=ctx.state.source_run_id,
                                engagement_score=candidate_data.get("engagement_score"),
                                source_url=candidate_data.get("source_url"),
                                source_post_id=candidate_data.get("source_post_id")
                            )

                            saved.append({
                                "id": str(new_candidate.id),
                                "name": new_candidate.name
                            })
                    except Exception as e:
                        logger.warning(f"Failed to create candidate: {e}")

            ctx.state.saved_candidates = saved
            ctx.state.merged_candidates = merged
            ctx.state.stats["saved"] = len(saved)
            ctx.state.stats["merged"] = len(merged)
            ctx.state.current_step = "completed"

            logger.info(f"Saved {len(saved)} new candidates, merged {len(merged)} into existing")

            return End({
                "status": "success",
                "saved_count": len(saved),
                "merged_count": len(merged),
                "saved_candidates": saved,
                "merged_candidates": merged,
                "stats": ctx.state.stats
            })

        except Exception as e:
            ctx.state.error = str(e)
            logger.error(f"Save failed: {e}")
            return End({
                "status": "error",
                "error": str(e),
                "stats": ctx.state.stats
            })


# ============================================================================
# Graph Definition
# ============================================================================

# Define the extraction graph
angle_candidate_extraction_graph = Graph(
    nodes=[
        ExtractFromSourceNode,
        SimilarityCheckNode,
        SaveCandidatesNode
    ],
    state_type=ExtractionState
)


# ============================================================================
# Helper Functions
# ============================================================================

async def extract_candidates(
    product_id: UUID,
    source_type: str,
    source_data: Dict[str, Any],
    source_run_id: Optional[UUID] = None,
    competitor_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Run the extraction pipeline.

    Args:
        product_id: Product UUID
        source_type: Source type (belief_reverse_engineer, reddit, etc.)
        source_data: Data from the source to extract from
        source_run_id: Optional run ID for tracking
        competitor_id: Optional competitor ID for competitor research

    Returns:
        Result dict with saved/merged counts and candidates
    """
    initial_state = ExtractionState(
        product_id=product_id,
        source_type=source_type,
        source_data=source_data,
        source_run_id=source_run_id,
        competitor_id=competitor_id
    )

    result = await angle_candidate_extraction_graph.run(
        ExtractFromSourceNode(),
        state=initial_state
    )

    return result.output
