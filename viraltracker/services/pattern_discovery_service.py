"""
PatternDiscoveryService - Automatic pattern discovery from angle candidates.

This service:
- Generates embeddings for angle candidates using OpenAI text-embedding-3-small
- Clusters similar candidates to discover recurring patterns
- Calculates novelty scores against existing belief angles
- Manages discovered pattern lifecycle (discover -> review -> promote/dismiss)

Architecture:
    Research Insights UI -> PatternDiscoveryService -> OpenAI API + Supabase
"""

import os
import json
import logging
from typing import List, Dict, Optional, Any, Tuple
from uuid import UUID
from datetime import datetime

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Clustering parameters
MIN_CANDIDATES_FOR_DISCOVERY = 10  # Minimum candidates needed
CLUSTER_EPS = 0.3  # DBSCAN epsilon (max distance between samples)
CLUSTER_MIN_SAMPLES = 2  # Minimum samples per cluster

# Novelty scoring thresholds
NOVELTY_THRESHOLD_SIMILAR = 0.85  # Cosine sim > this = duplicate
NOVELTY_THRESHOLD_RELATED = 0.70  # Cosine sim > this = related


class PatternDiscoveryService:
    """Service for discovering patterns in angle candidates."""

    def __init__(self):
        """Initialize the service."""
        self.supabase = get_supabase_client()
        self._openai_client = None
        logger.info("PatternDiscoveryService initialized")

    @property
    def openai_client(self):
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            try:
                import openai
                self._openai_client = openai.OpenAI()
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                raise
        return self._openai_client

    # =========================================================================
    # Embedding Generation
    # =========================================================================

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text using OpenAI.

        Args:
            text: Text to embed

        Returns:
            List of floats (1536 dimensions) or None if failed
        """
        try:
            response = self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def generate_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 100
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per API call

        Returns:
            List of embeddings (same order as input)
        """
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                response = self.openai_client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=batch
                )
                batch_embeddings = [d.embedding for d in response.data]
                embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.error(f"Failed to generate batch embeddings: {e}")
                # Fill with None for failed batch
                embeddings.extend([None] * len(batch))

        return embeddings

    def update_candidate_embedding(
        self,
        candidate_id: UUID,
        embedding: List[float]
    ) -> bool:
        """
        Store embedding for a candidate.

        Args:
            candidate_id: Candidate UUID
            embedding: Embedding vector

        Returns:
            True if successful
        """
        try:
            self.supabase.table("angle_candidates").update({
                "embedding": embedding
            }).eq("id", str(candidate_id)).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to update candidate embedding: {e}")
            return False

    def ensure_candidate_embeddings(
        self,
        product_id: UUID,
        force_refresh: bool = False
    ) -> int:
        """
        Ensure all candidates for a product have embeddings.

        Args:
            product_id: Product UUID
            force_refresh: Regenerate all embeddings

        Returns:
            Number of embeddings generated
        """
        # Get candidates without embeddings (or all if force_refresh)
        query = self.supabase.table("angle_candidates").select(
            "id, belief_statement"
        ).eq("product_id", str(product_id))

        if not force_refresh:
            query = query.is_("embedding", "null")

        result = query.execute()
        candidates = result.data or []

        if not candidates:
            logger.info(f"All candidates for product {product_id} have embeddings")
            return 0

        logger.info(f"Generating embeddings for {len(candidates)} candidates")

        # Generate embeddings in batch
        texts = [c["belief_statement"] for c in candidates]
        embeddings = self.generate_embeddings_batch(texts)

        # Update candidates with embeddings
        count = 0
        for candidate, embedding in zip(candidates, embeddings):
            if embedding:
                if self.update_candidate_embedding(UUID(candidate["id"]), embedding):
                    count += 1

        logger.info(f"Generated {count} embeddings for product {product_id}")
        return count

    # =========================================================================
    # Clustering
    # =========================================================================

    def cluster_candidates(
        self,
        product_id: UUID,
        eps: float = CLUSTER_EPS,
        min_samples: int = CLUSTER_MIN_SAMPLES
    ) -> List[Dict[str, Any]]:
        """
        Cluster candidates by embedding similarity using DBSCAN.

        Args:
            product_id: Product UUID
            eps: DBSCAN epsilon (max distance)
            min_samples: Minimum samples per cluster

        Returns:
            List of cluster dicts with candidate_ids and centroid
        """
        # Ensure embeddings exist
        self.ensure_candidate_embeddings(product_id)

        # Fetch candidates with embeddings
        result = self.supabase.table("angle_candidates").select(
            "id, name, belief_statement, candidate_type, source_type, embedding"
        ).eq("product_id", str(product_id)).not_.is_("embedding", "null").execute()

        candidates = result.data or []

        if len(candidates) < MIN_CANDIDATES_FOR_DISCOVERY:
            logger.warning(
                f"Only {len(candidates)} candidates with embeddings. "
                f"Need {MIN_CANDIDATES_FOR_DISCOVERY} for pattern discovery."
            )
            return []

        # Extract embeddings matrix
        embeddings = np.array([c["embedding"] for c in candidates])

        # Calculate distance matrix (1 - cosine similarity)
        similarity_matrix = cosine_similarity(embeddings)
        distance_matrix = 1 - similarity_matrix

        # Run DBSCAN clustering
        clustering = DBSCAN(
            eps=eps,
            min_samples=min_samples,
            metric="precomputed"
        ).fit(distance_matrix)

        labels = clustering.labels_

        # Group candidates by cluster
        clusters = []
        unique_labels = set(labels)

        for label in unique_labels:
            if label == -1:
                # Noise points (unclustered)
                continue

            cluster_indices = np.where(labels == label)[0]
            cluster_candidates = [candidates[i] for i in cluster_indices]
            cluster_embeddings = embeddings[cluster_indices]

            # Calculate centroid
            centroid = np.mean(cluster_embeddings, axis=0).tolist()

            # Calculate average distance from centroid
            centroid_array = np.array(centroid).reshape(1, -1)
            distances = 1 - cosine_similarity(cluster_embeddings, centroid_array)
            avg_radius = float(np.mean(distances))

            # Analyze cluster composition
            source_breakdown = {}
            type_breakdown = {}
            for c in cluster_candidates:
                source = c.get("source_type", "unknown")
                ctype = c.get("candidate_type", "unknown")
                source_breakdown[source] = source_breakdown.get(source, 0) + 1
                type_breakdown[ctype] = type_breakdown.get(ctype, 0) + 1

            clusters.append({
                "candidate_ids": [c["id"] for c in cluster_candidates],
                "candidates": cluster_candidates,
                "centroid": centroid,
                "radius": avg_radius,
                "size": len(cluster_candidates),
                "source_breakdown": source_breakdown,
                "type_breakdown": type_breakdown
            })

        # Sort by cluster size descending
        clusters.sort(key=lambda x: x["size"], reverse=True)

        logger.info(f"Found {len(clusters)} clusters from {len(candidates)} candidates")
        return clusters

    # =========================================================================
    # Novelty Scoring
    # =========================================================================

    def calculate_novelty_score(
        self,
        embedding: List[float],
        product_id: UUID
    ) -> Tuple[float, Optional[Dict]]:
        """
        Calculate how novel an embedding is compared to existing angles.

        Args:
            embedding: Embedding vector to check
            product_id: Product UUID

        Returns:
            Tuple of (novelty_score 0-1, most_similar_angle or None)
        """
        # Get existing belief angles for this product
        # First get JTBDs for the product
        jtbd_result = self.supabase.table("belief_jtbd_framed").select(
            "id"
        ).eq("product_id", str(product_id)).execute()

        jtbd_ids = [j["id"] for j in (jtbd_result.data or [])]

        if not jtbd_ids:
            # No existing angles, everything is novel
            return 1.0, None

        # Get angles for these JTBDs
        angles_result = self.supabase.table("belief_angles").select(
            "id, name, belief_statement"
        ).in_("jtbd_framed_id", jtbd_ids).execute()

        angles = angles_result.data or []

        if not angles:
            return 1.0, None

        # Generate embeddings for existing angles (if not cached, just compute)
        angle_texts = [a["belief_statement"] for a in angles]
        angle_embeddings = self.generate_embeddings_batch(angle_texts)

        # Filter out None embeddings
        valid_angles = []
        valid_embeddings = []
        for angle, emb in zip(angles, angle_embeddings):
            if emb:
                valid_angles.append(angle)
                valid_embeddings.append(emb)

        if not valid_embeddings:
            return 1.0, None

        # Calculate similarity to each existing angle
        embedding_array = np.array(embedding).reshape(1, -1)
        angles_array = np.array(valid_embeddings)
        similarities = cosine_similarity(embedding_array, angles_array)[0]

        max_similarity = float(np.max(similarities))
        most_similar_idx = int(np.argmax(similarities))
        most_similar_angle = valid_angles[most_similar_idx]

        # Convert similarity to novelty (1 - similarity)
        novelty_score = 1.0 - max_similarity

        return novelty_score, {
            "angle_id": most_similar_angle["id"],
            "angle_name": most_similar_angle["name"],
            "similarity": max_similarity
        }

    # =========================================================================
    # Pattern Discovery
    # =========================================================================

    def discover_patterns(
        self,
        product_id: UUID,
        min_cluster_size: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Run pattern discovery for a product.

        Args:
            product_id: Product UUID
            min_cluster_size: Minimum candidates per pattern

        Returns:
            List of discovered patterns (not yet saved)
        """
        # Run clustering
        clusters = self.cluster_candidates(product_id)

        if not clusters:
            return []

        # Get brand_id for the product
        product_result = self.supabase.table("products").select(
            "brand_id"
        ).eq("id", str(product_id)).execute()

        brand_id = None
        if product_result.data:
            brand_id = product_result.data[0].get("brand_id")

        # Process each cluster into a pattern
        patterns = []
        for cluster in clusters:
            if cluster["size"] < min_cluster_size:
                continue

            # Generate pattern name and description using candidates
            candidates = cluster["candidates"]
            sample_beliefs = [c["belief_statement"][:100] for c in candidates[:3]]

            # Determine pattern type based on dominant candidate type
            type_breakdown = cluster["type_breakdown"]
            dominant_type = max(type_breakdown.keys(), key=lambda k: type_breakdown[k])
            pattern_type = self._map_candidate_type_to_pattern_type(dominant_type)

            # Calculate novelty score for the centroid
            novelty_score, similar_angle = self.calculate_novelty_score(
                cluster["centroid"],
                product_id
            )

            # Calculate confidence based on evidence count and source diversity
            source_count = len(cluster["source_breakdown"])
            confidence_score = min(1.0, (cluster["size"] / 10) * (source_count / 3))

            # Generate a name for the pattern
            pattern_name = self._generate_pattern_name(candidates, dominant_type)

            # Count total evidence across candidates
            evidence_count = sum(
                self._get_evidence_count(UUID(c["id"])) for c in candidates
            )

            pattern = {
                "product_id": str(product_id),
                "brand_id": str(brand_id) if brand_id else None,
                "name": pattern_name,
                "theme_description": f"Cluster of {cluster['size']} related insights: {'; '.join(sample_beliefs)}",
                "pattern_type": pattern_type,
                "candidate_count": cluster["size"],
                "evidence_count": evidence_count,
                "source_breakdown": cluster["source_breakdown"],
                "confidence_score": confidence_score,
                "novelty_score": novelty_score,
                "centroid_embedding": cluster["centroid"],
                "cluster_radius": cluster["radius"],
                "candidate_ids": cluster["candidate_ids"],
                "similar_angle": similar_angle
            }
            patterns.append(pattern)

        # Sort by confidence * novelty (prioritize confident + novel)
        patterns.sort(
            key=lambda p: (p["confidence_score"] * p["novelty_score"]),
            reverse=True
        )

        logger.info(f"Discovered {len(patterns)} patterns for product {product_id}")
        return patterns

    def _map_candidate_type_to_pattern_type(self, candidate_type: str) -> str:
        """Map candidate type to pattern type."""
        mapping = {
            "pain_signal": "pain_cluster",
            "jtbd": "jtbd_cluster",
            "quote": "quote_cluster",
            "pattern": "emerging_topic",
            "ad_hypothesis": "emerging_topic",
            "ump": "pain_cluster",
            "ums": "jtbd_cluster"
        }
        return mapping.get(candidate_type, "emerging_topic")

    def _generate_pattern_name(
        self,
        candidates: List[Dict],
        dominant_type: str
    ) -> str:
        """Generate a descriptive name for the pattern."""
        # Extract key words from candidate names
        names = [c.get("name", "") for c in candidates[:5]]
        words = " ".join(names).split()

        # Find most common meaningful words
        from collections import Counter
        word_counts = Counter(w.lower() for w in words if len(w) > 3)

        if word_counts:
            top_words = [w for w, _ in word_counts.most_common(3)]
            base_name = " ".join(top_words).title()
        else:
            base_name = f"Pattern {candidates[0].get('name', 'Unknown')[:20]}"

        type_prefix = {
            "pain_signal": "Pain:",
            "jtbd": "Need:",
            "quote": "Voice:",
            "pattern": "Trend:",
            "ad_hypothesis": "Hypothesis:"
        }.get(dominant_type, "Theme:")

        return f"{type_prefix} {base_name}"

    def _get_evidence_count(self, candidate_id: UUID) -> int:
        """Get evidence count for a candidate."""
        try:
            result = self.supabase.table("angle_candidate_evidence").select(
                "id", count="exact"
            ).eq("candidate_id", str(candidate_id)).execute()
            return result.count or 0
        except Exception:
            return 0

    # =========================================================================
    # Pattern CRUD
    # =========================================================================

    def save_discovered_pattern(self, pattern: Dict[str, Any]) -> Optional[str]:
        """
        Save a discovered pattern to the database.

        Args:
            pattern: Pattern dict from discover_patterns()

        Returns:
            Pattern ID if successful
        """
        try:
            # Remove fields not in table
            pattern_data = {k: v for k, v in pattern.items() if k not in ["similar_angle", "candidates"]}

            result = self.supabase.table("discovered_patterns").insert(
                pattern_data
            ).execute()

            if result.data:
                pattern_id = result.data[0]["id"]
                logger.info(f"Saved pattern: {pattern['name']} (ID: {pattern_id})")
                return pattern_id
            return None
        except Exception as e:
            logger.error(f"Failed to save pattern: {e}")
            return None

    def get_patterns_for_product(
        self,
        product_id: UUID,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get discovered patterns for a product.

        Args:
            product_id: Product UUID
            status: Optional status filter
            limit: Max results

        Returns:
            List of pattern dicts
        """
        try:
            query = self.supabase.table("discovered_patterns").select(
                "*"
            ).eq("product_id", str(product_id))

            if status:
                query = query.eq("status", status)

            result = query.order(
                "confidence_score", desc=True
            ).limit(limit).execute()

            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get patterns: {e}")
            return []

    def update_pattern_status(
        self,
        pattern_id: UUID,
        status: str,
        reviewed_by: Optional[UUID] = None
    ) -> bool:
        """
        Update pattern status.

        Args:
            pattern_id: Pattern UUID
            status: New status
            reviewed_by: User UUID

        Returns:
            True if successful
        """
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now().isoformat()
            }

            if reviewed_by:
                update_data["reviewed_by"] = str(reviewed_by)
                update_data["reviewed_at"] = datetime.now().isoformat()

            self.supabase.table("discovered_patterns").update(
                update_data
            ).eq("id", str(pattern_id)).execute()

            logger.info(f"Updated pattern {pattern_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to update pattern status: {e}")
            return False

    def promote_pattern_to_angle(
        self,
        pattern_id: UUID,
        jtbd_framed_id: UUID,
        created_by: Optional[UUID] = None
    ) -> Optional[str]:
        """
        Promote a pattern to a belief angle.

        Args:
            pattern_id: Pattern UUID
            jtbd_framed_id: Target JTBD UUID
            created_by: User UUID

        Returns:
            New angle ID if successful
        """
        try:
            # Get pattern
            result = self.supabase.table("discovered_patterns").select(
                "*"
            ).eq("id", str(pattern_id)).execute()

            if not result.data:
                logger.error(f"Pattern not found: {pattern_id}")
                return None

            pattern = result.data[0]

            # Create belief angle
            angle_data = {
                "jtbd_framed_id": str(jtbd_framed_id),
                "name": pattern["name"].replace("Pain:", "").replace("Need:", "").replace("Theme:", "").strip(),
                "belief_statement": pattern["theme_description"],
                "explanation": f"Discovered from {pattern['candidate_count']} candidates across {len(pattern.get('source_breakdown', {}))} sources",
                "status": "untested"
            }

            if created_by:
                angle_data["created_by"] = str(created_by)

            angle_result = self.supabase.table("belief_angles").insert(
                angle_data
            ).execute()

            if not angle_result.data:
                return None

            angle_id = angle_result.data[0]["id"]

            # Update pattern as promoted
            self.supabase.table("discovered_patterns").update({
                "status": "promoted",
                "promoted_angle_id": angle_id,
                "updated_at": datetime.now().isoformat()
            }).eq("id", str(pattern_id)).execute()

            logger.info(f"Promoted pattern {pattern_id} to angle {angle_id}")
            return angle_id

        except Exception as e:
            logger.error(f"Failed to promote pattern: {e}")
            return None

    # =========================================================================
    # Discovery Status
    # =========================================================================

    def get_discovery_status(self, product_id: UUID) -> Dict[str, Any]:
        """
        Get pattern discovery status for a product.

        Args:
            product_id: Product UUID

        Returns:
            Status dict with counts and readiness
        """
        try:
            # Count candidates
            candidates_result = self.supabase.table("angle_candidates").select(
                "id", count="exact"
            ).eq("product_id", str(product_id)).execute()

            total_candidates = candidates_result.count or 0

            # Count candidates with embeddings
            embedded_result = self.supabase.table("angle_candidates").select(
                "id", count="exact"
            ).eq("product_id", str(product_id)).not_.is_("embedding", "null").execute()

            embedded_candidates = embedded_result.count or 0

            # Count discovered patterns
            patterns_result = self.supabase.table("discovered_patterns").select(
                "id", count="exact"
            ).eq("product_id", str(product_id)).execute()

            total_patterns = patterns_result.count or 0

            # Patterns by status
            status_result = self.supabase.table("discovered_patterns").select(
                "status"
            ).eq("product_id", str(product_id)).execute()

            status_counts = {}
            for p in (status_result.data or []):
                s = p.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1

            ready_for_discovery = total_candidates >= MIN_CANDIDATES_FOR_DISCOVERY

            return {
                "total_candidates": total_candidates,
                "embedded_candidates": embedded_candidates,
                "total_patterns": total_patterns,
                "status_counts": status_counts,
                "ready_for_discovery": ready_for_discovery,
                "min_required": MIN_CANDIDATES_FOR_DISCOVERY,
                "needs_more": max(0, MIN_CANDIDATES_FOR_DISCOVERY - total_candidates)
            }
        except Exception as e:
            logger.error(f"Failed to get discovery status: {e}")
            return {
                "total_candidates": 0,
                "ready_for_discovery": False,
                "error": str(e)
            }
