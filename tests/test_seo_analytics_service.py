"""
Tests for SEOAnalyticsService — ranking tracking and project dashboard analytics.

Tests cover:
- Recording rankings
- Retrieving ranking history
- Getting latest rankings per project
- Project dashboard aggregation
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from viraltracker.services.seo_pipeline.services.seo_analytics_service import (
    SEOAnalyticsService,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def service():
    """Service with mocked Supabase client."""
    mock_supabase = MagicMock()
    return SEOAnalyticsService(supabase_client=mock_supabase)


@pytest.fixture
def sample_rankings():
    return [
        {
            "id": "rank-001",
            "article_id": "art-001",
            "keyword": "best gaming pc",
            "position": 5,
            "checked_at": "2026-03-01T12:00:00Z",
        },
        {
            "id": "rank-002",
            "article_id": "art-001",
            "keyword": "best gaming pc",
            "position": 8,
            "checked_at": "2026-02-28T12:00:00Z",
        },
        {
            "id": "rank-003",
            "article_id": "art-001",
            "keyword": "gaming pc guide",
            "position": 12,
            "checked_at": "2026-02-27T12:00:00Z",
        },
    ]


@pytest.fixture
def sample_articles():
    return [
        {
            "id": "art-001",
            "keyword": "best gaming pc",
            "status": "published",
            "published_url": "https://example.com/best-gaming-pc",
            "cms_article_id": "shopify-123",
        },
        {
            "id": "art-002",
            "keyword": "gaming monitor guide",
            "status": "draft",
            "published_url": None,
            "cms_article_id": None,
        },
        {
            "id": "art-003",
            "keyword": "build pc budget",
            "status": "published",
            "published_url": "https://example.com/build-pc-budget",
            "cms_article_id": "shopify-456",
        },
    ]


@pytest.fixture
def sample_keywords():
    return [
        {"id": "kw-001", "status": "selected"},
        {"id": "kw-002", "status": "selected"},
        {"id": "kw-003", "status": "discovered"},
        {"id": "kw-004", "status": "rejected"},
    ]


# =============================================================================
# RECORD RANKING
# =============================================================================

class TestRecordRanking:
    def test_basic_record(self, service):
        mock_exec = MagicMock()
        mock_exec.data = [{
            "id": "rank-new",
            "article_id": "art-001",
            "keyword": "best gaming pc",
            "position": 5,
        }]
        service._supabase.table.return_value.insert.return_value.execute.return_value = mock_exec

        result = service.record_ranking("art-001", "best gaming pc", 5)
        assert result["article_id"] == "art-001"
        assert result["position"] == 5

    def test_record_with_timestamp(self, service):
        mock_exec = MagicMock()
        mock_exec.data = [{
            "id": "rank-new",
            "article_id": "art-001",
            "keyword": "best gaming pc",
            "position": 3,
            "checked_at": "2026-03-01T10:00:00Z",
        }]
        service._supabase.table.return_value.insert.return_value.execute.return_value = mock_exec

        result = service.record_ranking("art-001", "best gaming pc", 3, "2026-03-01T10:00:00Z")
        assert result["checked_at"] == "2026-03-01T10:00:00Z"

    def test_record_empty_result(self, service):
        """If insert returns no data, should return the input data."""
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.insert.return_value.execute.return_value = mock_exec

        result = service.record_ranking("art-001", "gaming pc", 10)
        assert result["article_id"] == "art-001"
        assert result["keyword"] == "gaming pc"
        assert result["position"] == 10


# =============================================================================
# RANKING HISTORY
# =============================================================================

class TestGetRankingHistory:
    def test_basic_history(self, service, sample_rankings):
        mock_exec = MagicMock()
        mock_exec.data = sample_rankings
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .order.return_value
            .execute
        ).return_value = mock_exec

        result = service.get_ranking_history("art-001")
        assert len(result) == 3

    def test_history_with_keyword_filter(self, service, sample_rankings):
        filtered = [r for r in sample_rankings if r["keyword"] == "best gaming pc"]
        mock_exec = MagicMock()
        mock_exec.data = filtered
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .eq.return_value
            .order.return_value
            .execute
        ).return_value = mock_exec

        result = service.get_ranking_history("art-001", keyword="best gaming pc")
        assert len(result) == 2
        for r in result:
            assert r["keyword"] == "best gaming pc"

    def test_empty_history(self, service):
        mock_exec = MagicMock()
        mock_exec.data = None
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .order.return_value
            .execute
        ).return_value = mock_exec

        result = service.get_ranking_history("art-001")
        assert result == []


# =============================================================================
# LATEST RANKINGS
# =============================================================================

class TestGetLatestRankings:
    def test_basic_latest(self, service):
        # First query: get articles
        articles = [
            {"id": "art-001", "keyword": "best gaming pc"},
            {"id": "art-002", "keyword": "gaming monitor"},
        ]
        mock_articles = MagicMock()
        mock_articles.data = articles
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute
        ).return_value = mock_articles

        # Mock get_ranking_history
        service.get_ranking_history = MagicMock(side_effect=[
            [{"position": 5, "keyword": "best gaming pc", "checked_at": "2026-03-01T12:00:00Z"}],
            [],  # No rankings for art-002
        ])

        result = service.get_latest_rankings("proj-001", "org-001")
        assert len(result) == 1
        assert result[0]["article_id"] == "art-001"
        assert result[0]["position"] == 5

    def test_no_articles(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute
        ).return_value = mock_exec

        result = service.get_latest_rankings("proj-001", "org-001")
        assert result == []

    def test_superuser_all_org(self, service):
        """With org_id='all', should not filter by organization_id."""
        articles = [{"id": "art-001", "keyword": "test"}]
        mock_exec = MagicMock()
        mock_exec.data = articles
        # With "all", only one .eq() for project_id
        (
            service._supabase.table.return_value
            .select.return_value
            .eq.return_value
            .execute
        ).return_value = mock_exec

        service.get_ranking_history = MagicMock(return_value=[])

        result = service.get_latest_rankings("proj-001", "all")
        assert isinstance(result, list)


# =============================================================================
# PROJECT DASHBOARD
# =============================================================================

class TestGetProjectDashboard:
    def _setup_dashboard_mocks(self, service, articles, keywords, links_per_article=None):
        """Helper to set up multiple Supabase query mocks."""
        call_count = [0]
        links_per_article = links_per_article or {}

        def table_side_effect(table_name):
            mock_table = MagicMock()

            if table_name == "seo_articles":
                mock_exec = MagicMock()
                mock_exec.data = articles
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec

            elif table_name == "seo_keywords":
                mock_exec = MagicMock()
                mock_exec.data = keywords
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_exec

            elif table_name == "seo_internal_links":
                aid_key = f"art-{call_count[0]}"
                call_count[0] += 1
                links = links_per_article.get(aid_key, [])
                mock_exec = MagicMock()
                mock_exec.data = links
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_exec

            return mock_table

        service._supabase.table.side_effect = table_side_effect

    def test_basic_dashboard(self, service, sample_articles, sample_keywords):
        self._setup_dashboard_mocks(service, sample_articles, sample_keywords)

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["project_id"] == "proj-001"
        assert result["articles"]["total"] == 3
        assert result["articles"]["published"] == 2  # two have published_url
        assert result["keywords"]["total"] == 4

    def test_dashboard_status_counts(self, service, sample_articles, sample_keywords):
        self._setup_dashboard_mocks(service, sample_articles, sample_keywords)

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["articles"]["status_counts"]["published"] == 2
        assert result["articles"]["status_counts"]["draft"] == 1

    def test_dashboard_keyword_status(self, service, sample_articles, sample_keywords):
        self._setup_dashboard_mocks(service, sample_articles, sample_keywords)

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["keywords"]["status_counts"]["selected"] == 2
        assert result["keywords"]["status_counts"]["discovered"] == 1
        assert result["keywords"]["status_counts"]["rejected"] == 1

    def test_empty_project_dashboard(self, service):
        self._setup_dashboard_mocks(service, [], [])

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["articles"]["total"] == 0
        assert result["articles"]["published"] == 0
        assert result["keywords"]["total"] == 0
        assert result["links"]["total"] == 0

    def test_dashboard_link_stats(self, service, sample_keywords):
        articles = [
            {
                "id": "art-001",
                "keyword": "test",
                "status": "published",
                "published_url": "https://example.com/test",
                "cms_article_id": "123",
            }
        ]
        links = [
            {"id": "link-1", "status": "implemented", "link_type": "auto"},
            {"id": "link-2", "status": "pending", "link_type": "suggested"},
            {"id": "link-3", "status": "implemented", "link_type": "bidirectional"},
        ]

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "seo_articles":
                mock_exec = MagicMock()
                mock_exec.data = articles
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_keywords":
                mock_exec = MagicMock()
                mock_exec.data = sample_keywords
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_internal_links":
                mock_exec = MagicMock()
                mock_exec.data = links
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_exec
            return mock_table

        service._supabase.table.side_effect = table_side_effect

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["links"]["total"] == 3
        assert result["links"]["implemented"] == 2
        assert result["links"]["suggested"] == 1
