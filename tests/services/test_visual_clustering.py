"""
Tests for VisualClusteringService — DBSCAN visual style clustering.

All database calls are mocked — no real DB or API connections needed.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from viraltracker.pipelines.ad_creation_v2.services.visual_clustering_service import (
    VisualClusteringService,
    DEFAULT_EPS,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_DIVERSITY_THRESHOLD,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def vc_service():
    """Create a VisualClusteringService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = VisualClusteringService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")


# ============================================================================
# DBSCAN implementation tests
# ============================================================================

class TestDBSCAN:
    def test_two_clear_clusters(self):
        """Two well-separated groups should form two clusters."""
        # Create distance matrix for 6 points: 3 near each other, 3 near each other
        # Group A: points 0,1,2 near each other (dist ~0.1)
        # Group B: points 3,4,5 near each other (dist ~0.1)
        # Between groups: dist ~0.8
        dist = np.array([
            [0.0, 0.1, 0.1, 0.8, 0.8, 0.8],
            [0.1, 0.0, 0.1, 0.8, 0.8, 0.8],
            [0.1, 0.1, 0.0, 0.8, 0.8, 0.8],
            [0.8, 0.8, 0.8, 0.0, 0.1, 0.1],
            [0.8, 0.8, 0.8, 0.1, 0.0, 0.1],
            [0.8, 0.8, 0.8, 0.1, 0.1, 0.0],
        ])

        labels = VisualClusteringService._dbscan(dist, eps=0.3, min_samples=3)

        # Should have exactly 2 clusters
        unique_labels = set(l for l in labels if l >= 0)
        assert len(unique_labels) == 2

        # Points 0,1,2 should be in same cluster
        assert labels[0] == labels[1] == labels[2]
        # Points 3,4,5 should be in same cluster
        assert labels[3] == labels[4] == labels[5]
        # Different clusters
        assert labels[0] != labels[3]

    def test_noise_detection(self):
        """Isolated points should be labeled as noise (-1)."""
        # 3 points near each other + 1 far away
        dist = np.array([
            [0.0, 0.1, 0.1, 0.9],
            [0.1, 0.0, 0.1, 0.9],
            [0.1, 0.1, 0.0, 0.9],
            [0.9, 0.9, 0.9, 0.0],
        ])

        labels = VisualClusteringService._dbscan(dist, eps=0.3, min_samples=3)

        # Points 0,1,2 form a cluster
        assert labels[0] == labels[1] == labels[2]
        assert labels[0] >= 0

        # Point 3 is noise
        assert labels[3] == -1

    def test_all_noise_when_too_spread(self):
        """All points far apart should all be noise."""
        dist = np.array([
            [0.0, 0.9, 0.9],
            [0.9, 0.0, 0.9],
            [0.9, 0.9, 0.0],
        ])

        labels = VisualClusteringService._dbscan(dist, eps=0.3, min_samples=3)
        assert all(l == -1 for l in labels)

    def test_single_cluster(self):
        """All points close together should form one cluster."""
        dist = np.array([
            [0.0, 0.1, 0.2],
            [0.1, 0.0, 0.1],
            [0.2, 0.1, 0.0],
        ])

        labels = VisualClusteringService._dbscan(dist, eps=0.3, min_samples=3)
        assert labels[0] == labels[1] == labels[2]
        assert labels[0] >= 0


# ============================================================================
# Descriptor aggregation tests
# ============================================================================

class TestDescriptorAggregation:
    def test_empty_descriptors(self):
        """Empty list should return empty dict."""
        result = VisualClusteringService._aggregate_descriptors([])
        assert result == {}

    def test_most_common_values(self):
        """Should return most common values per key."""
        descriptors = [
            {"style": "modern", "color": "blue"},
            {"style": "modern", "color": "red"},
            {"style": "vintage", "color": "blue"},
        ]

        result = VisualClusteringService._aggregate_descriptors(descriptors)
        assert "style" in result
        assert "color" in result
        # "modern" appears 2x, "vintage" 1x → modern first
        assert result["style"][0] == "modern"


# ============================================================================
# Diversity check tests
# ============================================================================

class TestDiversityCheck:
    def test_diverse_when_no_clusters(self, vc_service):
        """When no clusters exist, should report as diverse."""
        vc_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        result = vc_service.get_diversity_check(
            BRAND_ID,
            embedding=[0.1] * 10,
        )
        assert result["is_diverse"] is True

    def test_similar_to_centroid_not_diverse(self, vc_service):
        """Embedding very similar to a centroid should not be diverse."""
        centroid = [0.5] * 10
        vc_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "cluster-1",
            "cluster_label": 0,
            "centroid_embedding": centroid,
        }])

        # Same vector as centroid
        result = vc_service.get_diversity_check(
            BRAND_ID,
            embedding=centroid,
            threshold=0.90,
        )
        assert result["is_diverse"] is False
        assert result["similarity"] > 0.90

    def test_different_from_centroid_is_diverse(self, vc_service):
        """Embedding very different from centroid should be diverse."""
        vc_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "cluster-1",
            "cluster_label": 0,
            "centroid_embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }])

        # Orthogonal vector
        result = vc_service.get_diversity_check(
            BRAND_ID,
            embedding=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            threshold=0.90,
        )
        assert result["is_diverse"] is True
        assert result["similarity"] < 0.1


# ============================================================================
# Cluster summary tests
# ============================================================================

class TestClusterSummary:
    def test_returns_clusters_by_reward(self, vc_service):
        """Should return clusters ordered by avg_reward_score desc."""
        mock_data = [
            {"id": "c1", "cluster_label": 0, "cluster_size": 10, "avg_reward_score": 0.8, "top_descriptors": {}, "computed_at": "2026-02-16T00:00:00"},
            {"id": "c2", "cluster_label": 1, "cluster_size": 5, "avg_reward_score": 0.3, "top_descriptors": {}, "computed_at": "2026-02-16T00:00:00"},
        ]
        vc_service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=mock_data)

        result = vc_service.get_cluster_summary(BRAND_ID)
        assert len(result) == 2
        assert result[0]["avg_reward_score"] == 0.8


# ============================================================================
# Clustering pipeline tests
# ============================================================================

class TestClusteringPipeline:
    @pytest.mark.asyncio
    async def test_insufficient_embeddings(self, vc_service):
        """Too few embeddings should return without clustering."""
        vc_service.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[
            {"id": "e1", "generated_ad_id": "a1", "embedding": [0.1, 0.2], "descriptors": {}},
        ])

        result = await vc_service.cluster_brand_styles(BRAND_ID, min_samples=3)
        assert result["clusters_found"] == 0
