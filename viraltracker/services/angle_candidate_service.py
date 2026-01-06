"""
AngleCandidateService - Unified Angle Pipeline.

This service handles:
- CRUD for angle candidates and evidence
- Similarity detection for deduplication
- Frequency score calculation
- Promotion workflow to belief_angles
- Candidate merging

Architecture:
    5 Input Sources → angle_candidates → Research Insights UI → belief_angles

Input Sources:
    - Belief Reverse Engineer pipeline
    - Reddit Research
    - Ad Performance Analysis
    - Competitor Research
    - Brand/Consumer Research
"""

import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from supabase import Client

from ..core.database import get_supabase_client
from .models import (
    AngleCandidate,
    AngleCandidateEvidence,
    BeliefAngle,
    CandidateConfidence,
    CandidateStatus,
)

logger = logging.getLogger(__name__)


class AngleCandidateService:
    """Service for managing angle candidates in the unified pipeline."""

    def __init__(self):
        """Initialize AngleCandidateService."""
        self.supabase: Client = get_supabase_client()
        logger.info("AngleCandidateService initialized")

    # ============================================
    # CANDIDATE CRUD
    # ============================================

    def create_candidate(
        self,
        product_id: UUID,
        name: str,
        belief_statement: str,
        source_type: str,
        candidate_type: str,
        brand_id: Optional[UUID] = None,
        explanation: Optional[str] = None,
        source_run_id: Optional[UUID] = None,
        competitor_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
    ) -> AngleCandidate:
        """
        Create a new angle candidate.

        Args:
            product_id: Product UUID
            name: Short descriptive name
            belief_statement: The core belief/insight
            source_type: Source system (belief_reverse_engineer, reddit_research, etc.)
            candidate_type: Type (pain_signal, pattern, jtbd, ad_hypothesis, quote, ump, ums)
            brand_id: Optional brand UUID
            explanation: Optional additional context
            source_run_id: Optional run ID from source system
            competitor_id: Optional competitor ID if from competitor research
            tags: Optional tags for categorization

        Returns:
            Created AngleCandidate
        """
        data = {
            "product_id": str(product_id),
            "name": name,
            "belief_statement": belief_statement,
            "source_type": source_type,
            "candidate_type": candidate_type,
            "frequency_score": 1,
            "confidence": CandidateConfidence.LOW.value,
            "status": CandidateStatus.CANDIDATE.value,
        }

        if brand_id:
            data["brand_id"] = str(brand_id)
        if explanation:
            data["explanation"] = explanation
        if source_run_id:
            data["source_run_id"] = str(source_run_id)
        if competitor_id:
            data["competitor_id"] = str(competitor_id)
        if tags:
            data["tags"] = tags

        result = self.supabase.table("angle_candidates").insert(data).execute()
        logger.info(f"Created angle candidate: {name}")
        return AngleCandidate(**result.data[0])

    def get_candidate(self, candidate_id: UUID) -> Optional[AngleCandidate]:
        """
        Get a candidate by ID with evidence.

        Args:
            candidate_id: Candidate UUID

        Returns:
            AngleCandidate with evidence list populated, or None
        """
        try:
            result = self.supabase.table("angle_candidates").select("*").eq(
                "id", str(candidate_id)
            ).execute()

            if not result.data:
                return None

            candidate = AngleCandidate(**result.data[0])

            # Fetch evidence
            evidence_result = self.supabase.table("angle_candidate_evidence").select(
                "*"
            ).eq("candidate_id", str(candidate_id)).order(
                "created_at", desc=True
            ).execute()

            candidate.evidence = [
                AngleCandidateEvidence(**row) for row in evidence_result.data or []
            ]

            return candidate
        except Exception as e:
            logger.error(f"Failed to get candidate {candidate_id}: {e}")
            return None

    def get_candidates_for_product(
        self,
        product_id: UUID,
        status: Optional[str] = "candidate",
        limit: int = 50,
        offset: int = 0,
        source_type: Optional[str] = None,
    ) -> List[AngleCandidate]:
        """
        Fetch candidates for a product.

        Args:
            product_id: Product UUID
            status: Filter by status (None for all)
            limit: Max results
            offset: Pagination offset
            source_type: Optional filter by source type

        Returns:
            List of AngleCandidate (sorted by frequency_score DESC)
        """
        try:
            query = self.supabase.table("angle_candidates").select("*").eq(
                "product_id", str(product_id)
            )

            if status:
                query = query.eq("status", status)
            if source_type:
                query = query.eq("source_type", source_type)

            result = query.order(
                "frequency_score", desc=True
            ).range(offset, offset + limit - 1).execute()

            return [AngleCandidate(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to fetch candidates for product {product_id}: {e}")
            return []

    def update_candidate(
        self,
        candidate_id: UUID,
        **updates
    ) -> Optional[AngleCandidate]:
        """
        Update a candidate.

        Args:
            candidate_id: Candidate UUID
            **updates: Fields to update

        Returns:
            Updated AngleCandidate or None
        """
        try:
            # Convert UUIDs to strings
            for key, value in updates.items():
                if isinstance(value, UUID):
                    updates[key] = str(value)

            result = self.supabase.table("angle_candidates").update(
                updates
            ).eq("id", str(candidate_id)).execute()

            if result.data:
                return AngleCandidate(**result.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to update candidate {candidate_id}: {e}")
            return None

    def delete_candidate(self, candidate_id: UUID) -> bool:
        """
        Delete a candidate (cascades to evidence).

        Args:
            candidate_id: Candidate UUID

        Returns:
            True if successful
        """
        try:
            self.supabase.table("angle_candidates").delete().eq(
                "id", str(candidate_id)
            ).execute()
            logger.info(f"Deleted candidate {candidate_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete candidate {candidate_id}: {e}")
            return False

    # ============================================
    # EVIDENCE CRUD
    # ============================================

    def add_evidence(
        self,
        candidate_id: UUID,
        evidence_type: str,
        evidence_text: str,
        source_type: str,
        source_run_id: Optional[UUID] = None,
        source_post_id: Optional[str] = None,
        source_url: Optional[str] = None,
        engagement_score: Optional[int] = None,
        confidence_score: Optional[float] = None,
    ) -> AngleCandidateEvidence:
        """
        Add evidence to a candidate and update frequency score.

        Args:
            candidate_id: Candidate UUID
            evidence_type: Type (pain_signal, quote, pattern, solution, hypothesis)
            evidence_text: The evidence text
            source_type: Source system
            source_run_id: Optional run ID
            source_post_id: Optional original post ID
            source_url: Optional source URL
            engagement_score: Optional engagement (upvotes, etc.)
            confidence_score: Optional LLM confidence 0-1

        Returns:
            Created AngleCandidateEvidence
        """
        data = {
            "candidate_id": str(candidate_id),
            "evidence_type": evidence_type,
            "evidence_text": evidence_text,
            "source_type": source_type,
        }

        if source_run_id:
            data["source_run_id"] = str(source_run_id)
        if source_post_id:
            data["source_post_id"] = source_post_id
        if source_url:
            data["source_url"] = source_url
        if engagement_score is not None:
            data["engagement_score"] = engagement_score
        if confidence_score is not None:
            data["confidence_score"] = confidence_score

        result = self.supabase.table("angle_candidate_evidence").insert(data).execute()
        evidence = AngleCandidateEvidence(**result.data[0])

        # Update frequency score after adding evidence
        self.update_frequency_score(candidate_id)

        logger.info(f"Added evidence to candidate {candidate_id}")
        return evidence

    def get_evidence_for_candidate(
        self,
        candidate_id: UUID
    ) -> List[AngleCandidateEvidence]:
        """
        Get all evidence for a candidate.

        Args:
            candidate_id: Candidate UUID

        Returns:
            List of AngleCandidateEvidence
        """
        try:
            result = self.supabase.table("angle_candidate_evidence").select("*").eq(
                "candidate_id", str(candidate_id)
            ).order("created_at", desc=True).execute()

            return [AngleCandidateEvidence(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to get evidence for candidate {candidate_id}: {e}")
            return []

    # ============================================
    # SIMILARITY & MERGING
    # ============================================

    def find_similar_candidate(
        self,
        product_id: UUID,
        belief_statement: str,
        threshold: float = 0.8,
        exclude_id: Optional[UUID] = None
    ) -> Optional[AngleCandidate]:
        """
        Find a similar existing candidate for deduplication.

        This is a simple text-matching implementation. Phase 9 will add
        embedding-based similarity with LLM verification.

        Args:
            product_id: Product UUID
            belief_statement: Belief statement to compare
            threshold: Similarity threshold (not used in simple version)
            exclude_id: Candidate ID to exclude from search

        Returns:
            Similar AngleCandidate or None
        """
        try:
            # Get recent candidates for the product
            query = self.supabase.table("angle_candidates").select(
                "id, name, belief_statement"
            ).eq("product_id", str(product_id)).eq(
                "status", CandidateStatus.CANDIDATE.value
            ).limit(100)

            if exclude_id:
                query = query.neq("id", str(exclude_id))

            result = query.execute()

            if not result.data:
                return None

            # Simple substring matching for MVP
            # TODO: Phase 9 will add embedding similarity + Haiku verification
            belief_lower = belief_statement.lower().strip()

            for row in result.data:
                existing_belief = row.get("belief_statement", "").lower().strip()

                # Check for exact match or high substring overlap
                if belief_lower == existing_belief:
                    return self.get_candidate(UUID(row["id"]))

                # Check if one is a substring of the other
                if len(belief_lower) > 20 and len(existing_belief) > 20:
                    if belief_lower in existing_belief or existing_belief in belief_lower:
                        return self.get_candidate(UUID(row["id"]))

            return None
        except Exception as e:
            logger.error(f"Failed to find similar candidate: {e}")
            return None

    def merge_candidates(
        self,
        keep_id: UUID,
        merge_ids: List[UUID]
    ) -> Optional[AngleCandidate]:
        """
        Merge multiple candidates into one.

        Evidence from merged candidates is moved to the kept candidate.
        Merged candidates are marked with status='merged'.

        Args:
            keep_id: Candidate ID to keep
            merge_ids: List of candidate IDs to merge into keep_id

        Returns:
            Updated kept candidate or None
        """
        try:
            # Move evidence from merged candidates to kept candidate
            for merge_id in merge_ids:
                self.supabase.table("angle_candidate_evidence").update({
                    "candidate_id": str(keep_id)
                }).eq("candidate_id", str(merge_id)).execute()

                # Mark merged candidate as merged
                self.supabase.table("angle_candidates").update({
                    "status": CandidateStatus.MERGED.value
                }).eq("id", str(merge_id)).execute()

                logger.info(f"Merged candidate {merge_id} into {keep_id}")

            # Update frequency score for kept candidate
            self.update_frequency_score(keep_id)

            return self.get_candidate(keep_id)
        except Exception as e:
            logger.error(f"Failed to merge candidates: {e}")
            return None

    # ============================================
    # FREQUENCY & CONFIDENCE
    # ============================================

    def update_frequency_score(self, candidate_id: UUID) -> int:
        """
        Recalculate frequency score from evidence count.

        Args:
            candidate_id: Candidate UUID

        Returns:
            New frequency score
        """
        try:
            # Count evidence
            result = self.supabase.table("angle_candidate_evidence").select(
                "id", count="exact"
            ).eq("candidate_id", str(candidate_id)).execute()

            evidence_count = result.count or 0
            # Frequency score is at least 1 (the candidate itself counts)
            frequency_score = max(1, evidence_count)

            # Calculate confidence
            confidence = AngleCandidate.calculate_confidence(frequency_score)

            # Update candidate
            self.supabase.table("angle_candidates").update({
                "frequency_score": frequency_score,
                "confidence": confidence,
            }).eq("id", str(candidate_id)).execute()

            logger.debug(f"Updated candidate {candidate_id}: freq={frequency_score}, conf={confidence}")
            return frequency_score
        except Exception as e:
            logger.error(f"Failed to update frequency score for {candidate_id}: {e}")
            return 1

    # ============================================
    # WORKFLOW: PROMOTION & REJECTION
    # ============================================

    def promote_to_angle(
        self,
        candidate_id: UUID,
        jtbd_framed_id: UUID,
        created_by: Optional[UUID] = None
    ) -> Optional[BeliefAngle]:
        """
        Promote a candidate to a belief_angle.

        Args:
            candidate_id: Candidate UUID
            jtbd_framed_id: JTBD to associate the angle with
            created_by: Optional user UUID

        Returns:
            Created BeliefAngle or None
        """
        try:
            # Get the candidate
            candidate = self.get_candidate(candidate_id)
            if not candidate:
                logger.error(f"Candidate {candidate_id} not found")
                return None

            if candidate.status != CandidateStatus.CANDIDATE.value:
                logger.warning(f"Cannot promote candidate with status {candidate.status}")
                return None

            # Create the belief_angle
            angle_data = {
                "jtbd_framed_id": str(jtbd_framed_id),
                "name": candidate.name,
                "belief_statement": candidate.belief_statement,
                "explanation": candidate.explanation,
                "status": "untested",
            }
            if created_by:
                angle_data["created_by"] = str(created_by)

            result = self.supabase.table("belief_angles").insert(angle_data).execute()
            angle = BeliefAngle(**result.data[0])

            # Update candidate status
            self.supabase.table("angle_candidates").update({
                "status": CandidateStatus.APPROVED.value,
                "promoted_angle_id": str(angle.id),
                "reviewed_at": datetime.utcnow().isoformat(),
                "reviewed_by": str(created_by) if created_by else None,
            }).eq("id", str(candidate_id)).execute()

            logger.info(f"Promoted candidate {candidate_id} to angle {angle.id}")
            return angle
        except Exception as e:
            logger.error(f"Failed to promote candidate {candidate_id}: {e}")
            return None

    def reject_candidate(
        self,
        candidate_id: UUID,
        reason: Optional[str] = None,
        reviewed_by: Optional[UUID] = None
    ) -> bool:
        """
        Reject a candidate.

        Args:
            candidate_id: Candidate UUID
            reason: Optional rejection reason (stored in explanation)
            reviewed_by: Optional user UUID

        Returns:
            True if successful
        """
        try:
            updates: Dict[str, Any] = {
                "status": CandidateStatus.REJECTED.value,
                "reviewed_at": datetime.utcnow().isoformat(),
            }
            if reason:
                updates["explanation"] = reason
            if reviewed_by:
                updates["reviewed_by"] = str(reviewed_by)

            self.supabase.table("angle_candidates").update(updates).eq(
                "id", str(candidate_id)
            ).execute()

            logger.info(f"Rejected candidate {candidate_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reject candidate {candidate_id}: {e}")
            return False

    # ============================================
    # BULK OPERATIONS
    # ============================================

    def create_candidate_with_evidence(
        self,
        product_id: UUID,
        name: str,
        belief_statement: str,
        source_type: str,
        candidate_type: str,
        evidence_items: List[Dict[str, Any]],
        brand_id: Optional[UUID] = None,
        explanation: Optional[str] = None,
        source_run_id: Optional[UUID] = None,
        competitor_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
    ) -> AngleCandidate:
        """
        Create a candidate with multiple evidence items in one call.

        Args:
            product_id: Product UUID
            name: Short descriptive name
            belief_statement: The core belief/insight
            source_type: Source system
            candidate_type: Type
            evidence_items: List of evidence dicts with keys:
                - evidence_type (required)
                - evidence_text (required)
                - source_type (defaults to candidate source_type)
                - source_run_id, source_post_id, source_url, engagement_score, confidence_score (optional)
            brand_id: Optional brand UUID
            explanation: Optional additional context
            source_run_id: Optional run ID
            competitor_id: Optional competitor ID
            tags: Optional tags

        Returns:
            Created AngleCandidate with evidence
        """
        # Create candidate
        candidate = self.create_candidate(
            product_id=product_id,
            name=name,
            belief_statement=belief_statement,
            source_type=source_type,
            candidate_type=candidate_type,
            brand_id=brand_id,
            explanation=explanation,
            source_run_id=source_run_id,
            competitor_id=competitor_id,
            tags=tags,
        )

        # Add evidence items
        for item in evidence_items:
            self.add_evidence(
                candidate_id=candidate.id,
                evidence_type=item.get("evidence_type"),
                evidence_text=item.get("evidence_text"),
                source_type=item.get("source_type", source_type),
                source_run_id=item.get("source_run_id") or source_run_id,
                source_post_id=item.get("source_post_id"),
                source_url=item.get("source_url"),
                engagement_score=item.get("engagement_score"),
                confidence_score=item.get("confidence_score"),
            )

        # Refresh to get updated frequency score
        return self.get_candidate(candidate.id)

    def _extract_belief_text_from_layer(
        self,
        item: Any,
        layer_key: str
    ) -> Optional[str]:
        """
        Extract belief statement text from belief-first analysis layer data.

        The belief-first analysis returns structured objects like:
        - pain_signal: {"pain": "...", "status": "...", "context": "..."}
        - benefits: {"status": "...", "context": "...", "examples": [...]}
        - jtbd: {"status": "...", "context": "...", "examples": [...]}
        - angle: {"status": "...", "context": "...", "examples": [...]}

        This extracts the most meaningful text for the belief statement.
        """
        # If it's already a string, return it
        if isinstance(item, str):
            return item

        # If it's not a dict, convert to string
        if not isinstance(item, dict):
            return str(item) if item else None

        # For pain signals, extract the 'pain' field
        if layer_key == "problem_pain_symptoms":
            pain_text = item.get("pain")
            if pain_text:
                return pain_text

        # For other layers, try to extract meaningful text
        # Priority: examples > context > summary

        # Try to get examples first (more concrete)
        examples = item.get("examples", [])
        if examples and isinstance(examples, list):
            # Get the first example's quote
            for ex in examples:
                if isinstance(ex, dict) and ex.get("quote"):
                    return ex["quote"]
                elif isinstance(ex, str):
                    return ex

        # Fall back to context (the explanation)
        context = item.get("context")
        if context and len(context) > 20:
            # Truncate context if too long and return first sentence
            if len(context) > 200:
                # Find first sentence
                for end in [". ", "! ", "? "]:
                    idx = context.find(end)
                    if idx > 0:
                        return context[:idx + 1]
                return context[:200]
            return context

        # Last resort: any string value in the dict
        for key in ["summary", "description", "text", "statement"]:
            if item.get(key):
                return item[key]

        return None

    def get_or_create_candidate(
        self,
        product_id: UUID,
        belief_statement: str,
        name: str,
        source_type: str,
        candidate_type: str,
        **kwargs
    ) -> tuple[AngleCandidate, bool]:
        """
        Get existing similar candidate or create new one.

        Used for deduplication during extraction.

        Args:
            product_id: Product UUID
            belief_statement: Belief statement
            name: Candidate name (used if creating new)
            source_type: Source type
            candidate_type: Candidate type
            **kwargs: Additional args passed to create_candidate

        Returns:
            Tuple of (candidate, was_created)
        """
        # Check for existing similar candidate
        existing = self.find_similar_candidate(product_id, belief_statement)

        if existing:
            logger.debug(f"Found existing similar candidate: {existing.id}")
            return existing, False

        # Create new candidate
        candidate = self.create_candidate(
            product_id=product_id,
            name=name,
            belief_statement=belief_statement,
            source_type=source_type,
            candidate_type=candidate_type,
            **kwargs
        )
        return candidate, True

    # ============================================
    # STATISTICS
    # ============================================

    def get_candidate_stats(self, product_id: UUID) -> Dict[str, Any]:
        """
        Get statistics about candidates for a product.

        Args:
            product_id: Product UUID

        Returns:
            Dict with statistics:
                - total: Total candidates
                - by_status: Count by status
                - by_source: Count by source type
                - by_confidence: Count by confidence level
        """
        try:
            result = self.supabase.table("angle_candidates").select(
                "status, source_type, confidence"
            ).eq("product_id", str(product_id)).execute()

            stats = {
                "total": len(result.data or []),
                "by_status": {},
                "by_source": {},
                "by_confidence": {},
            }

            for row in result.data or []:
                status = row.get("status", "unknown")
                source = row.get("source_type", "unknown")
                confidence = row.get("confidence", "unknown")

                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
                stats["by_confidence"][confidence] = stats["by_confidence"].get(confidence, 0) + 1

            return stats
        except Exception as e:
            logger.error(f"Failed to get candidate stats for product {product_id}: {e}")
            return {"total": 0, "by_status": {}, "by_source": {}, "by_confidence": {}}

    # ============================================
    # SOURCE EXTRACTION METHODS
    # ============================================

    def extract_from_reddit_quotes(
        self,
        run_id: UUID,
        product_id: UUID,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from reddit_sentiment_quotes.

        Creates candidates from PAIN_POINT and DESIRED_OUTCOME quotes.

        Args:
            run_id: Reddit scrape run UUID
            product_id: Product UUID
            brand_id: Optional brand UUID

        Returns:
            Dict with {created: int, updated: int, errors: int}
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        try:
            # Fetch quotes from the run
            result = self.supabase.table("reddit_sentiment_quotes").select(
                "id, quote_text, sentiment_category, sentiment_subtype, "
                "confidence_score, extraction_reasoning, source_type"
            ).eq("run_id", str(run_id)).execute()

            if not result.data:
                logger.info(f"No quotes found for run {run_id}")
                return stats

            # Filter to relevant categories
            relevant_categories = ["PAIN_POINT", "DESIRED_OUTCOME", "BUYING_OBJECTION", "FAILED_SOLUTION"]

            for quote in result.data:
                category = quote.get("sentiment_category")
                if category not in relevant_categories:
                    continue

                try:
                    quote_text = quote.get("quote_text", "")
                    if not quote_text or len(quote_text) < 10:
                        continue

                    # Map sentiment category to candidate type
                    type_map = {
                        "PAIN_POINT": "pain_signal",
                        "DESIRED_OUTCOME": "jtbd",
                        "BUYING_OBJECTION": "pattern",
                        "FAILED_SOLUTION": "ump",
                    }
                    candidate_type = type_map.get(category, "quote")

                    # Create candidate name from quote
                    name = quote_text[:50] + "..." if len(quote_text) > 50 else quote_text

                    # Check for existing similar candidate
                    candidate, created = self.get_or_create_candidate(
                        product_id=product_id,
                        belief_statement=quote_text,
                        name=name,
                        source_type="reddit_research",
                        candidate_type=candidate_type,
                        brand_id=brand_id,
                        source_run_id=run_id,
                        tags=["reddit_research", category.lower()],
                    )

                    if created:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                    # Add evidence
                    self.add_evidence(
                        candidate_id=candidate.id,
                        evidence_type="quote",
                        evidence_text=quote_text,
                        source_type="reddit_research",
                        source_run_id=run_id,
                        source_post_id=str(quote.get("id", "")),
                        confidence_score=quote.get("confidence_score"),
                    )

                except Exception as e:
                    logger.error(f"Failed to extract candidate from quote: {e}")
                    stats["errors"] += 1

            logger.info(f"Reddit extraction: created={stats['created']}, updated={stats['updated']}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from reddit quotes: {e}")
            stats["errors"] += 1
            return stats

    def extract_from_ad_analysis(
        self,
        product_id: UUID,
        angle: str,
        belief: str,
        hooks: Optional[List[Dict]] = None,
        source_ad_id: Optional[str] = None,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidate from ad performance analysis.

        Args:
            product_id: Product UUID
            angle: Advertising angle from analysis
            belief: Belief statement from analysis
            hooks: Optional list of hooks
            source_ad_id: Optional Meta ad ID
            brand_id: Optional brand UUID

        Returns:
            Dict with {created: int, updated: int, candidate_id: str}
        """
        stats = {"created": 0, "updated": 0, "candidate_id": None}

        try:
            if not belief or len(belief) < 10:
                logger.warning("No valid belief statement for ad analysis extraction")
                return stats

            # Create candidate name from angle or belief
            name = angle if angle and angle not in ["None", "Unknown"] else belief[:50]

            # Check for existing similar candidate
            candidate, created = self.get_or_create_candidate(
                product_id=product_id,
                belief_statement=belief,
                name=name,
                source_type="ad_performance",
                candidate_type="ad_hypothesis",
                brand_id=brand_id,
                tags=["ad_performance", "high_performer"] if angle else ["ad_performance"],
            )

            if created:
                stats["created"] = 1
            else:
                stats["updated"] = 1

            stats["candidate_id"] = str(candidate.id)

            # Add evidence from the analysis
            evidence_text = f"Angle: {angle}\nBelief: {belief}"
            if hooks:
                hook_texts = [h.get("text", str(h)) for h in hooks[:3] if h]
                if hook_texts:
                    evidence_text += f"\nHooks: {'; '.join(hook_texts)}"

            self.add_evidence(
                candidate_id=candidate.id,
                evidence_type="hypothesis",
                evidence_text=evidence_text,
                source_type="ad_performance",
                source_post_id=source_ad_id,
            )

            logger.info(f"Ad analysis extraction: {'created' if created else 'updated'} candidate {candidate.id}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from ad analysis: {e}")
            return stats

    def extract_from_competitor_amazon_reviews(
        self,
        competitor_id: UUID,
        product_id: UUID,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from competitor Amazon review analysis.

        Args:
            competitor_id: Competitor UUID
            product_id: Product UUID to link candidates to
            brand_id: Optional brand UUID

        Returns:
            Dict with {created: int, updated: int, errors: int}
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        try:
            # Fetch competitor Amazon analysis
            result = self.supabase.table("competitor_amazon_review_analysis").select(
                "id, pain_points, desires, objections, transformation"
            ).eq("competitor_id", str(competitor_id)).execute()

            if not result.data:
                logger.info(f"No Amazon analysis for competitor {competitor_id}")
                return stats

            for analysis in result.data:
                analysis_id = analysis.get("id")

                # Extract pain point themes
                pain_data = analysis.get("pain_points", {})
                if isinstance(pain_data, dict):
                    themes = pain_data.get("themes", [])
                    for theme in themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="competitor_research",
                            candidate_type="pain_signal",
                            competitor_id=competitor_id,
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

                    # Also extract JTBD themes if present
                    jtbd_themes = pain_data.get("jobs_to_be_done", [])
                    for theme in jtbd_themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="competitor_research",
                            candidate_type="jtbd",
                            competitor_id=competitor_id,
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

                # Extract desire themes
                desires_data = analysis.get("desires", {})
                if isinstance(desires_data, dict):
                    themes = desires_data.get("themes", [])
                    for theme in themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="competitor_research",
                            candidate_type="jtbd",
                            competitor_id=competitor_id,
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

                # Extract failed solution themes
                transformation_data = analysis.get("transformation", {})
                if isinstance(transformation_data, dict):
                    themes = transformation_data.get("themes", [])
                    for theme in themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="competitor_research",
                            candidate_type="ump",
                            competitor_id=competitor_id,
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

            logger.info(f"Competitor Amazon extraction: created={stats['created']}, updated={stats['updated']}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from competitor Amazon reviews: {e}")
            stats["errors"] += 1
            return stats

    def extract_from_competitor_landing_pages(
        self,
        competitor_id: UUID,
        product_id: UUID,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from competitor landing page belief-first analysis.

        Args:
            competitor_id: Competitor UUID
            product_id: Product UUID
            brand_id: Optional brand UUID

        Returns:
            Dict with {created: int, updated: int, errors: int}
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        try:
            # Fetch landing pages with belief-first analysis
            result = self.supabase.table("competitor_landing_pages").select(
                "id, url, belief_first_analysis"
            ).eq("competitor_id", str(competitor_id)).not_.is_(
                "belief_first_analysis", "null"
            ).execute()

            if not result.data:
                logger.info(f"No belief-first analysis for competitor {competitor_id}")
                return stats

            for page in result.data:
                bf_analysis = page.get("belief_first_analysis", {})
                if not bf_analysis:
                    continue

                page_url = page.get("url", "")
                layers = bf_analysis.get("layers", {})

                # Extract from various layers
                layer_mappings = [
                    ("problem_pain_symptoms", "pain_signal"),
                    ("jobs_to_be_done", "jtbd"),
                    ("angle", "ad_hypothesis"),
                    ("benefits", "pattern"),
                ]

                for layer_key, candidate_type in layer_mappings:
                    layer_data = layers.get(layer_key)
                    if not layer_data:
                        continue

                    # Handle both list and dict values
                    items = layer_data if isinstance(layer_data, list) else [layer_data]

                    for item in items:
                        if not item:
                            continue

                        # Extract belief statement from structured data
                        belief_text = self._extract_belief_text_from_layer(item, layer_key)
                        if not belief_text or len(belief_text) < 10:
                            continue

                        name = belief_text[:50] + "..." if len(belief_text) > 50 else belief_text

                        # Get context for evidence
                        context = ""
                        if isinstance(item, dict):
                            context = item.get("context", "")

                        try:
                            candidate, created = self.get_or_create_candidate(
                                product_id=product_id,
                                belief_statement=belief_text,
                                name=name,
                                source_type="competitor_research",
                                candidate_type=candidate_type,
                                competitor_id=competitor_id,
                                brand_id=brand_id,
                                tags=["competitor_landing_page", layer_key],
                            )

                            if created:
                                stats["created"] += 1
                            else:
                                stats["updated"] += 1

                            # Build evidence text with context
                            evidence_text = f"From {layer_key}: {belief_text}"
                            if context:
                                evidence_text += f"\n\nContext: {context}"

                            self.add_evidence(
                                candidate_id=candidate.id,
                                evidence_type="pattern",
                                evidence_text=evidence_text,
                                source_type="competitor_research",
                                source_url=page_url,
                            )

                        except Exception as e:
                            logger.error(f"Failed to extract from landing page layer: {e}")
                            stats["errors"] += 1

            logger.info(f"Competitor landing page extraction: created={stats['created']}, updated={stats['updated']}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from competitor landing pages: {e}")
            stats["errors"] += 1
            return stats

    def extract_from_brand_amazon_reviews(
        self,
        product_id: UUID,
        brand_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from brand's own Amazon review analysis.

        Args:
            product_id: Product UUID
            brand_id: Optional brand UUID

        Returns:
            Dict with {created: int, updated: int, errors: int}
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        try:
            # Fetch brand Amazon analysis
            query = self.supabase.table("amazon_review_analysis").select(
                "id, pain_points, desires, objections, transformation"
            )

            if product_id:
                query = query.eq("product_id", str(product_id))
            elif brand_id:
                query = query.eq("brand_id", str(brand_id))

            result = query.execute()

            if not result.data:
                logger.info(f"No Amazon analysis for product {product_id}")
                return stats

            for analysis in result.data:
                analysis_id = analysis.get("id")

                # Extract pain point themes
                pain_data = analysis.get("pain_points", {})
                if isinstance(pain_data, dict):
                    themes = pain_data.get("themes", [])
                    for theme in themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="brand_research",
                            candidate_type="pain_signal",
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

                    # Also extract JTBD themes
                    jtbd_themes = pain_data.get("jobs_to_be_done", [])
                    for theme in jtbd_themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="brand_research",
                            candidate_type="jtbd",
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

                # Extract desire themes
                desires_data = analysis.get("desires", {})
                if isinstance(desires_data, dict):
                    themes = desires_data.get("themes", [])
                    for theme in themes:
                        extracted = self._extract_theme_to_candidate(
                            theme=theme,
                            product_id=product_id,
                            source_type="brand_research",
                            candidate_type="jtbd",
                            brand_id=brand_id,
                            source_run_id=UUID(analysis_id) if analysis_id else None,
                        )
                        stats["created"] += extracted.get("created", 0)
                        stats["updated"] += extracted.get("updated", 0)

            logger.info(f"Brand Amazon extraction: created={stats['created']}, updated={stats['updated']}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from brand Amazon reviews: {e}")
            stats["errors"] += 1
            return stats

    def extract_from_brand_landing_pages(
        self,
        brand_id: UUID,
        product_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from brand landing page belief-first analysis.

        Args:
            brand_id: Brand UUID
            product_id: Optional product UUID

        Returns:
            Dict with {created: int, updated: int, errors: int}
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        try:
            # Fetch landing pages with belief-first analysis
            query = self.supabase.table("brand_landing_pages").select(
                "id, url, belief_first_analysis, product_id"
            ).eq("brand_id", str(brand_id)).not_.is_(
                "belief_first_analysis", "null"
            )

            if product_id:
                query = query.eq("product_id", str(product_id))

            result = query.execute()

            if not result.data:
                logger.info(f"No belief-first analysis for brand {brand_id}")
                return stats

            for page in result.data:
                bf_analysis = page.get("belief_first_analysis", {})
                if not bf_analysis:
                    continue

                page_url = page.get("url", "")
                page_product_id = page.get("product_id") or product_id
                layers = bf_analysis.get("layers", {})

                # Extract from various layers
                layer_mappings = [
                    ("problem_pain_symptoms", "pain_signal"),
                    ("jobs_to_be_done", "jtbd"),
                    ("angle", "ad_hypothesis"),
                    ("benefits", "pattern"),
                ]

                for layer_key, candidate_type in layer_mappings:
                    layer_data = layers.get(layer_key)
                    if not layer_data:
                        continue

                    items = layer_data if isinstance(layer_data, list) else [layer_data]

                    for item in items:
                        if not item or len(str(item)) < 10:
                            continue

                        item_str = str(item)
                        name = item_str[:50] + "..." if len(item_str) > 50 else item_str

                        # Need a product_id - if not available, skip
                        if not page_product_id:
                            continue

                        try:
                            candidate, created = self.get_or_create_candidate(
                                product_id=UUID(page_product_id) if isinstance(page_product_id, str) else page_product_id,
                                belief_statement=item_str,
                                name=name,
                                source_type="brand_research",
                                candidate_type=candidate_type,
                                brand_id=brand_id,
                                tags=["brand_landing_page", layer_key],
                            )

                            if created:
                                stats["created"] += 1
                            else:
                                stats["updated"] += 1

                            self.add_evidence(
                                candidate_id=candidate.id,
                                evidence_type="pattern",
                                evidence_text=f"From {layer_key}: {item_str}",
                                source_type="brand_research",
                                source_url=page_url,
                            )

                        except Exception as e:
                            logger.error(f"Failed to extract from brand landing page: {e}")
                            stats["errors"] += 1

            logger.info(f"Brand landing page extraction: created={stats['created']}, updated={stats['updated']}")
            return stats

        except Exception as e:
            logger.error(f"Failed to extract from brand landing pages: {e}")
            stats["errors"] += 1
            return stats

    def _extract_theme_to_candidate(
        self,
        theme: Dict[str, Any],
        product_id: UUID,
        source_type: str,
        candidate_type: str,
        competitor_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
        source_run_id: Optional[UUID] = None,
    ) -> Dict[str, int]:
        """
        Helper to extract a single theme to a candidate.

        Args:
            theme: Theme dict with 'theme', 'quotes', 'score' etc.
            product_id: Product UUID
            source_type: Source type string
            candidate_type: Candidate type string
            competitor_id: Optional competitor UUID
            brand_id: Optional brand UUID
            source_run_id: Optional source run UUID

        Returns:
            Dict with {created: int, updated: int}
        """
        stats = {"created": 0, "updated": 0}

        try:
            theme_text = theme.get("theme", "")
            if not theme_text or len(theme_text) < 5:
                return stats

            name = theme_text[:50] + "..." if len(theme_text) > 50 else theme_text

            candidate, created = self.get_or_create_candidate(
                product_id=product_id,
                belief_statement=theme_text,
                name=name,
                source_type=source_type,
                candidate_type=candidate_type,
                competitor_id=competitor_id,
                brand_id=brand_id,
                source_run_id=source_run_id,
                tags=[source_type, candidate_type],
            )

            if created:
                stats["created"] = 1
            else:
                stats["updated"] = 1

            # Add quotes as evidence
            quotes = theme.get("quotes", [])
            for quote in quotes[:5]:  # Limit to 5 quotes per theme
                quote_text = quote.get("quote", "") if isinstance(quote, dict) else str(quote)
                if quote_text:
                    self.add_evidence(
                        candidate_id=candidate.id,
                        evidence_type="quote",
                        evidence_text=quote_text,
                        source_type=source_type,
                        source_run_id=source_run_id,
                    )

            return stats

        except Exception as e:
            logger.error(f"Failed to extract theme to candidate: {e}")
            return stats
