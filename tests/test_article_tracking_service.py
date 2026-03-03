"""
Tests for ArticleTrackingService — article CRUD, status transitions, and dashboard aggregates.

Tests cover:
- Article retrieval (get_article)
- Article listing with filters
- Status transition validation (valid and invalid)
- Forced status overrides
- Status counts aggregation
- Project summary
"""

import pytest
from unittest.mock import MagicMock

from viraltracker.services.seo_pipeline.services.article_tracking_service import (
    ArticleTrackingService,
    VALID_TRANSITIONS,
)
from viraltracker.services.seo_pipeline.models import ArticleStatus


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def service():
    """Service with mocked Supabase client."""
    mock_supabase = MagicMock()
    return ArticleTrackingService(supabase_client=mock_supabase)


@pytest.fixture
def sample_article():
    return {
        "id": "art-001",
        "project_id": "proj-001",
        "organization_id": "org-001",
        "brand_id": "brand-001",
        "keyword": "best gaming pc",
        "title": "Best Gaming PC Guide",
        "status": "draft",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_articles():
    return [
        {
            "id": "art-001",
            "keyword": "best gaming pc",
            "status": "draft",
            "created_at": "2026-01-03T00:00:00Z",
        },
        {
            "id": "art-002",
            "keyword": "how to build pc",
            "status": "published",
            "created_at": "2026-01-02T00:00:00Z",
        },
        {
            "id": "art-003",
            "keyword": "gaming monitor guide",
            "status": "draft",
            "created_at": "2026-01-01T00:00:00Z",
        },
    ]


# =============================================================================
# GET ARTICLE
# =============================================================================

class TestGetArticle:
    def test_existing_article(self, service, sample_article):
        mock_exec = MagicMock()
        mock_exec.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.get_article("art-001")
        assert result["id"] == "art-001"
        assert result["keyword"] == "best gaming pc"

    def test_nonexistent_article(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.get_article("nonexistent")
        assert result is None


# =============================================================================
# LIST ARTICLES
# =============================================================================

class TestListArticles:
    def test_basic_list(self, service, sample_articles):
        mock_exec = MagicMock()
        mock_exec.data = sample_articles
        service._supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = mock_exec

        result = service.list_articles(organization_id="org-001")
        assert len(result) == 3

    def test_list_with_project_filter(self, service, sample_articles):
        # With project_id filter, there's an additional .eq() call
        mock_query = MagicMock()
        mock_exec = MagicMock()
        mock_exec.data = sample_articles[:1]

        service._supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = mock_exec

        result = service.list_articles(organization_id="org-001", project_id="proj-001")
        assert isinstance(result, list)

    def test_list_empty(self, service):
        mock_exec = MagicMock()
        mock_exec.data = None
        service._supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = mock_exec

        result = service.list_articles(organization_id="org-001")
        assert result == []

    def test_list_superuser_all(self, service, sample_articles):
        """Superuser with org_id='all' should not filter by organization."""
        mock_exec = MagicMock()
        mock_exec.data = sample_articles
        # With "all", no .eq("organization_id", ...) is called
        service._supabase.table.return_value.select.return_value.order.return_value.execute.return_value = mock_exec

        result = service.list_articles(organization_id="all")
        assert len(result) == 3


# =============================================================================
# STATUS TRANSITIONS
# =============================================================================

class TestUpdateStatus:
    def test_valid_transition(self, service, sample_article):
        """draft -> outline_complete should succeed."""
        mock_get = MagicMock()
        mock_get.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_get

        mock_update = MagicMock()
        mock_update.data = [{**sample_article, "status": "outline_complete"}]
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        result = service.update_status("art-001", "outline_complete")
        assert result["status"] == "outline_complete"

    def test_invalid_transition(self, service, sample_article):
        """draft -> published should fail (not a valid transition)."""
        mock_get = MagicMock()
        mock_get.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_get

        with pytest.raises(ValueError, match="Invalid status transition"):
            service.update_status("art-001", "published")

    def test_forced_transition(self, service, sample_article):
        """force=True should skip validation."""
        mock_get = MagicMock()
        mock_get.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_get

        mock_update = MagicMock()
        mock_update.data = [{**sample_article, "status": "published"}]
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        result = service.update_status("art-001", "published", force=True)
        assert result["status"] == "published"

    def test_article_not_found(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        with pytest.raises(ValueError, match="Article not found"):
            service.update_status("nonexistent", "published")

    def test_draft_to_archived(self, service, sample_article):
        """draft -> archived is a valid transition."""
        mock_get = MagicMock()
        mock_get.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_get

        mock_update = MagicMock()
        mock_update.data = [{**sample_article, "status": "archived"}]
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        result = service.update_status("art-001", "archived")
        assert result["status"] == "archived"


# =============================================================================
# VALID TRANSITIONS MAP
# =============================================================================

class TestValidTransitions:
    def test_all_statuses_have_transitions(self):
        """Every ArticleStatus value should appear in VALID_TRANSITIONS."""
        for status in ArticleStatus:
            assert status.value in VALID_TRANSITIONS, f"Missing transitions for {status.value}"

    def test_draft_transitions(self):
        assert ArticleStatus.OUTLINE_COMPLETE.value in VALID_TRANSITIONS[ArticleStatus.DRAFT.value]
        assert ArticleStatus.ARCHIVED.value in VALID_TRANSITIONS[ArticleStatus.DRAFT.value]

    def test_published_transitions(self):
        assert ArticleStatus.ARCHIVED.value in VALID_TRANSITIONS[ArticleStatus.PUBLISHED.value]

    def test_qa_pending_transitions(self):
        transitions = VALID_TRANSITIONS[ArticleStatus.QA_PENDING.value]
        assert ArticleStatus.QA_PASSED.value in transitions
        assert ArticleStatus.QA_FAILED.value in transitions

    def test_no_self_transitions(self):
        """No status should transition to itself."""
        for status, targets in VALID_TRANSITIONS.items():
            assert status not in targets, f"{status} can transition to itself"


# =============================================================================
# UPDATE ARTICLE
# =============================================================================

class TestUpdateArticle:
    def test_update_fields(self, service, sample_article):
        mock_exec = MagicMock()
        mock_exec.data = [{**sample_article, "title": "Updated Title"}]
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.update_article("art-001", title="Updated Title")
        assert result["title"] == "Updated Title"

    def test_no_updates(self, service, sample_article):
        """update_article with no kwargs should return the article unchanged."""
        mock_exec = MagicMock()
        mock_exec.data = [sample_article]
        service._supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.update_article("art-001")
        assert result["id"] == "art-001"

    def test_update_not_found(self, service):
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.update_article("nonexistent", title="Test")
        assert result is None


# =============================================================================
# DASHBOARD AGGREGATES
# =============================================================================

class TestGetStatusCounts:
    def test_basic_counts(self, service, sample_articles):
        service.list_articles = MagicMock(return_value=sample_articles)

        counts = service.get_status_counts("org-001", project_id="proj-001")
        assert counts["draft"] == 2
        assert counts["published"] == 1

    def test_empty_project(self, service):
        service.list_articles = MagicMock(return_value=[])

        counts = service.get_status_counts("org-001")
        assert counts == {}

    def test_with_brand_filter(self, service, sample_articles):
        service.list_articles = MagicMock(return_value=sample_articles)

        service.get_status_counts("org-001", brand_id="brand-001")
        service.list_articles.assert_called_once_with(
            organization_id="org-001",
            project_id=None,
            brand_id="brand-001",
        )


class TestGetProjectSummary:
    def test_basic_summary(self, service, sample_articles):
        service.list_articles = MagicMock(return_value=sample_articles)

        summary = service.get_project_summary("proj-001", "org-001")
        assert summary["project_id"] == "proj-001"
        assert summary["total_articles"] == 3
        assert summary["published_count"] == 1
        assert summary["status_counts"]["draft"] == 2
        assert summary["latest_article"]["id"] == "art-001"

    def test_empty_project(self, service):
        service.list_articles = MagicMock(return_value=[])

        summary = service.get_project_summary("proj-001", "org-001")
        assert summary["total_articles"] == 0
        assert summary["published_count"] == 0
        assert summary["latest_article"] is None
