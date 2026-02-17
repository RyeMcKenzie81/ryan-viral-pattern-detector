"""
Visual Clustering Service — DBSCAN clustering on visual embeddings.

Phase 8B: Clusters visual_embeddings per brand using DBSCAN on cosine distance,
correlates clusters with performance rewards, and provides diversity checks.

Tables:
    - visual_embeddings: Source embeddings from Phase 8A
    - visual_style_clusters: Cluster definitions (centroid, size, performance)
    - visual_style_cluster_members: Ad → cluster mapping
    - creative_element_rewards: Performance data for correlation
"""

import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)

# DBSCAN defaults
DEFAULT_EPS = 0.3
DEFAULT_MIN_SAMPLES = 3

# Diversity threshold
DEFAULT_DIVERSITY_THRESHOLD = 0.90


class VisualClusteringService:
    """DBSCAN visual style clustering on ad visual embeddings."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    async def cluster_brand_styles(
        self,
        brand_id: UUID,
        eps: float = DEFAULT_EPS,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> Dict[str, Any]:
        """Run DBSCAN clustering on visual embeddings for a brand.

        Args:
            brand_id: Brand UUID.
            eps: DBSCAN epsilon (max distance between points in cluster).
            min_samples: Minimum points to form a cluster.

        Returns:
            Summary dict with clusters_found, noise_count, total_embeddings.
        """
        # Load visual embeddings for this brand
        embeddings_result = self.supabase.table("visual_embeddings").select(
            "id, generated_ad_id, embedding, descriptors"
        ).eq("brand_id", str(brand_id)).execute()

        data = embeddings_result.data or []
        if len(data) < min_samples:
            return {
                "clusters_found": 0,
                "noise_count": len(data),
                "total_embeddings": len(data),
                "message": f"Insufficient embeddings ({len(data)}) for clustering",
            }

        # Parse embeddings into numpy array
        embedding_ids = []
        ad_ids = []
        descriptors_list = []
        vectors = []

        for row in data:
            emb = row.get("embedding")
            if not emb:
                continue
            # Handle both list and string representations
            if isinstance(emb, str):
                import json
                try:
                    emb = json.loads(emb)
                except (json.JSONDecodeError, ValueError):
                    continue
            if isinstance(emb, list) and len(emb) > 0:
                vectors.append(emb)
                embedding_ids.append(row["id"])
                ad_ids.append(row.get("generated_ad_id"))
                descriptors_list.append(row.get("descriptors") or {})

        if len(vectors) < min_samples:
            return {
                "clusters_found": 0,
                "noise_count": len(vectors),
                "total_embeddings": len(vectors),
            }

        X = np.array(vectors, dtype=np.float32)

        # Normalize for cosine distance
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X_norm = X / norms

        # Compute cosine distance matrix
        cos_sim = X_norm @ X_norm.T
        cos_dist = 1.0 - cos_sim
        np.fill_diagonal(cos_dist, 0.0)

        # Run DBSCAN
        labels = self._dbscan(cos_dist, eps=eps, min_samples=min_samples)

        # Build cluster info
        unique_labels = set(labels)
        clusters_found = sum(1 for l in unique_labels if l >= 0)
        noise_count = sum(1 for l in labels if l < 0)

        # Clear old clusters for this brand
        old_clusters = self.supabase.table("visual_style_clusters").select(
            "id"
        ).eq("brand_id", str(brand_id)).execute()
        for old in (old_clusters.data or []):
            self.supabase.table("visual_style_cluster_members").delete().eq(
                "cluster_id", old["id"]
            ).execute()
        self.supabase.table("visual_style_clusters").delete().eq(
            "brand_id", str(brand_id)
        ).execute()

        # Store new clusters
        now = datetime.now(timezone.utc).isoformat()
        for label in sorted(unique_labels):
            if label < 0:
                continue  # Skip noise

            member_indices = [i for i, l in enumerate(labels) if l == label]
            cluster_size = len(member_indices)

            # Compute centroid
            cluster_vectors = X[member_indices]
            centroid = np.mean(cluster_vectors, axis=0).tolist()

            # Aggregate descriptors for top features
            top_descriptors = self._aggregate_descriptors(
                [descriptors_list[i] for i in member_indices]
            )

            # Insert cluster
            cluster_result = self.supabase.table("visual_style_clusters").insert({
                "brand_id": str(brand_id),
                "cluster_label": int(label),
                "cluster_size": cluster_size,
                "centroid_embedding": centroid,
                "top_descriptors": top_descriptors,
                "computed_at": now,
            }).execute()

            if cluster_result.data:
                cluster_id = cluster_result.data[0]["id"]

                # Insert members
                members = []
                for idx in member_indices:
                    members.append({
                        "cluster_id": cluster_id,
                        "generated_ad_id": ad_ids[idx],
                        "visual_embedding_id": embedding_ids[idx],
                    })
                if members:
                    self.supabase.table("visual_style_cluster_members").insert(
                        members
                    ).execute()

        logger.info(
            f"Visual clustering for brand {brand_id}: "
            f"{clusters_found} clusters, {noise_count} noise, {len(vectors)} total"
        )

        return {
            "clusters_found": clusters_found,
            "noise_count": noise_count,
            "total_embeddings": len(vectors),
        }

    async def correlate_with_performance(self, brand_id: UUID) -> Dict[str, Any]:
        """Correlate visual clusters with ad performance rewards.

        Joins cluster members → creative_element_rewards to compute
        avg reward per cluster.

        Returns:
            Summary dict with clusters_updated.
        """
        clusters_result = self.supabase.table("visual_style_clusters").select(
            "id"
        ).eq("brand_id", str(brand_id)).execute()

        updated = 0
        for cluster in (clusters_result.data or []):
            cluster_id = cluster["id"]

            # Get member ad IDs
            members = self.supabase.table("visual_style_cluster_members").select(
                "generated_ad_id"
            ).eq("cluster_id", cluster_id).execute()

            ad_ids = [m["generated_ad_id"] for m in (members.data or []) if m.get("generated_ad_id")]
            if not ad_ids:
                continue

            # Get rewards for these ads
            # Join through generated_ads → ad_runs → creative_element_rewards
            rewards = []
            for ad_id in ad_ids:
                # Get ad_run_id from generated_ads
                ad_result = self.supabase.table("generated_ads").select(
                    "ad_run_id"
                ).eq("id", ad_id).execute()

                if ad_result.data:
                    ad_run_id = ad_result.data[0].get("ad_run_id")
                    if ad_run_id:
                        reward_result = self.supabase.table("creative_element_rewards").select(
                            "reward_score"
                        ).eq("ad_run_id", ad_run_id).execute()
                        for r in (reward_result.data or []):
                            if r.get("reward_score") is not None:
                                rewards.append(r["reward_score"])

            if rewards:
                avg_reward = sum(rewards) / len(rewards)
                self.supabase.table("visual_style_clusters").update({
                    "avg_reward_score": round(avg_reward, 4),
                }).eq("id", cluster_id).execute()
                updated += 1

        logger.info(f"Performance correlation for brand {brand_id}: {updated} clusters updated")
        return {"clusters_updated": updated}

    def get_cluster_summary(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """Get clusters ranked by performance with top descriptors.

        Args:
            brand_id: Brand UUID.

        Returns:
            List of cluster summary dicts ordered by avg_reward_score desc.
        """
        result = self.supabase.table("visual_style_clusters").select(
            "id, cluster_label, cluster_size, avg_reward_score, top_descriptors, computed_at"
        ).eq("brand_id", str(brand_id)).order(
            "avg_reward_score", desc=True
        ).execute()

        return result.data or []

    def get_diversity_check(
        self,
        brand_id: UUID,
        embedding: List[float],
        threshold: float = DEFAULT_DIVERSITY_THRESHOLD,
    ) -> Dict[str, Any]:
        """Check if a new ad embedding is too similar to existing cluster centroids.

        Args:
            brand_id: Brand UUID.
            embedding: New ad's visual embedding vector.
            threshold: Cosine similarity threshold for "too similar".

        Returns:
            Dict with is_diverse (bool), most_similar_cluster, similarity.
        """
        clusters_result = self.supabase.table("visual_style_clusters").select(
            "id, cluster_label, centroid_embedding"
        ).eq("brand_id", str(brand_id)).execute()

        if not clusters_result.data:
            return {"is_diverse": True, "most_similar_cluster": None, "similarity": 0.0}

        emb_arr = np.array(embedding, dtype=np.float32)
        emb_norm = emb_arr / (np.linalg.norm(emb_arr) or 1.0)

        max_sim = 0.0
        most_similar = None

        for cluster in clusters_result.data:
            centroid = cluster.get("centroid_embedding")
            if not centroid:
                continue
            if isinstance(centroid, str):
                import json
                try:
                    centroid = json.loads(centroid)
                except (json.JSONDecodeError, ValueError):
                    continue

            c_arr = np.array(centroid, dtype=np.float32)
            c_norm = c_arr / (np.linalg.norm(c_arr) or 1.0)

            sim = float(np.dot(emb_norm, c_norm))
            if sim > max_sim:
                max_sim = sim
                most_similar = cluster["cluster_label"]

        return {
            "is_diverse": max_sim < threshold,
            "most_similar_cluster": most_similar,
            "similarity": round(max_sim, 4),
        }

    # =========================================================================
    # Internal: DBSCAN implementation
    # =========================================================================

    @staticmethod
    def _dbscan(
        distance_matrix: np.ndarray,
        eps: float,
        min_samples: int,
    ) -> List[int]:
        """DBSCAN clustering on a precomputed distance matrix.

        Args:
            distance_matrix: N×N distance matrix.
            eps: Maximum distance for neighbors.
            min_samples: Minimum points for core point.

        Returns:
            List of cluster labels (-1 = noise).
        """
        n = distance_matrix.shape[0]
        labels = [-1] * n
        visited = [False] * n
        cluster_id = 0

        for i in range(n):
            if visited[i]:
                continue
            visited[i] = True

            # Find neighbors
            neighbors = [j for j in range(n) if distance_matrix[i, j] <= eps and j != i]

            if len(neighbors) < min_samples - 1:
                # Noise point
                continue

            # Start new cluster
            labels[i] = cluster_id
            seed_set = list(neighbors)
            idx = 0

            while idx < len(seed_set):
                q = seed_set[idx]
                if not visited[q]:
                    visited[q] = True
                    q_neighbors = [j for j in range(n) if distance_matrix[q, j] <= eps and j != q]
                    if len(q_neighbors) >= min_samples - 1:
                        seed_set.extend([j for j in q_neighbors if j not in seed_set])

                if labels[q] == -1:
                    labels[q] = cluster_id

                idx += 1

            cluster_id += 1

        return labels

    @staticmethod
    def _aggregate_descriptors(
        descriptors_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate visual descriptors across cluster members.

        Returns most common values for each descriptor key.
        """
        from collections import Counter

        if not descriptors_list:
            return {}

        key_values: Dict[str, List[str]] = {}
        for desc in descriptors_list:
            if not isinstance(desc, dict):
                continue
            for k, v in desc.items():
                if k not in key_values:
                    key_values[k] = []
                key_values[k].append(str(v))

        result = {}
        for k, values in key_values.items():
            counter = Counter(values)
            top = counter.most_common(3)
            result[k] = [v for v, _ in top]

        return result
