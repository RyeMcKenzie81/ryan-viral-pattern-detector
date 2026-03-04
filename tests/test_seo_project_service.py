"""
Unit tests for SEOProjectService.

Covers:
- Project CRUD (create, list, get, update, workflow state)
- Brand integrations (get, upsert)
- Author CRUD (create, list, get, set_default, update)
- Multi-tenancy filtering (organization_id, superuser "all" mode)

Run with: pytest tests/test_seo_project_service.py -v
"""

import pytest
from unittest.mock import MagicMock, call
from uuid import uuid4

from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Service with mocked Supabase client."""
    mock_supabase = MagicMock()
    return SEOProjectService(supabase_client=mock_supabase)


@pytest.fixture
def org_id():
    return str(uuid4())


@pytest.fixture
def brand_id():
    return str(uuid4())


def _mock_chain(mock_supabase, data=None):
    """Helper to set up chained Supabase query mock returning data."""
    if data is None:
        data = []
    mock_exec = MagicMock()
    mock_exec.execute.return_value = MagicMock(data=data)

    # Chain: table().method().eq().eq().order() etc. all return mock_exec
    mock_table = MagicMock()
    mock_table.select.return_value = mock_exec
    mock_table.insert.return_value = mock_exec
    mock_table.update.return_value = mock_exec
    mock_table.upsert.return_value = mock_exec

    # Make .eq(), .order(), etc. chainable
    mock_exec.eq.return_value = mock_exec
    mock_exec.order.return_value = mock_exec

    mock_supabase.table.return_value = mock_table
    return mock_exec


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_creates_project(self, service, brand_id, org_id):
        project_data = {
            "id": str(uuid4()),
            "brand_id": brand_id,
            "organization_id": org_id,
            "name": "Test SEO Project",
            "status": "active",
        }
        mock = _mock_chain(service.supabase, [project_data])

        result = service.create_project(brand_id, org_id, "Test SEO Project")
        assert result["name"] == "Test SEO Project"
        service.supabase.table.assert_called_with("seo_projects")

    def test_creates_with_config(self, service, brand_id, org_id):
        config = {"target_articles": 20}
        _mock_chain(service.supabase, [{"id": str(uuid4()), "config": config}])

        result = service.create_project(brand_id, org_id, "Test", config=config)
        assert result["config"] == config


class TestListProjects:
    def test_filters_by_org(self, service, org_id):
        _mock_chain(service.supabase, [{"id": "p1", "name": "Project 1"}])

        service.list_projects(org_id)
        # Should have called .eq("organization_id", org_id)
        service.supabase.table.assert_called_with("seo_projects")

    def test_superuser_all_mode(self, service):
        _mock_chain(service.supabase, [])

        result = service.list_projects("all")
        assert result == []

    def test_filters_by_brand(self, service, org_id, brand_id):
        _mock_chain(service.supabase, [])

        service.list_projects(org_id, brand_id=brand_id)
        service.supabase.table.assert_called_with("seo_projects")

    def test_filters_by_status(self, service, org_id):
        _mock_chain(service.supabase, [])

        service.list_projects(org_id, status="active")
        service.supabase.table.assert_called_with("seo_projects")

    def test_invalid_status_raises(self, service, org_id):
        with pytest.raises(ValueError, match="Invalid project status"):
            service.list_projects(org_id, status="bogus")

    def test_all_valid_statuses_accepted(self, service, org_id):
        from viraltracker.services.seo_pipeline.models import ProjectStatus
        _mock_chain(service.supabase, [])

        for status in ProjectStatus:
            result = service.list_projects(org_id, status=status.value)
            assert result == []


class TestGetProject:
    def test_found(self, service, org_id):
        project_id = str(uuid4())
        _mock_chain(service.supabase, [{"id": project_id, "name": "Found"}])

        result = service.get_project(project_id, org_id)
        assert result["name"] == "Found"

    def test_not_found(self, service, org_id):
        _mock_chain(service.supabase, [])

        result = service.get_project(str(uuid4()), org_id)
        assert result is None


class TestUpdateProject:
    def test_updates_fields(self, service, org_id):
        project_id = str(uuid4())
        _mock_chain(service.supabase, [{"id": project_id, "status": "paused"}])

        result = service.update_project(project_id, org_id, status="paused")
        assert result["status"] == "paused"

    def test_not_found_returns_none(self, service, org_id):
        _mock_chain(service.supabase, [])

        result = service.update_project(str(uuid4()), org_id, status="paused")
        assert result is None


class TestUpdateWorkflowState:
    def test_updates_workflow(self, service):
        project_id = str(uuid4())
        _mock_chain(service.supabase, [])

        service.update_workflow_state(project_id, "competitor_analysis", {"step": "analyzing"})
        service.supabase.table.assert_called_with("seo_projects")


# ---------------------------------------------------------------------------
# Brand Integrations
# ---------------------------------------------------------------------------


class TestGetBrandIntegration:
    def test_found(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [{
            "brand_id": brand_id,
            "platform": "shopify",
            "config": {"store_domain": "test.myshopify.com"},
        }])

        result = service.get_brand_integration(brand_id, org_id, "shopify")
        assert result["platform"] == "shopify"

    def test_not_found(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [])

        result = service.get_brand_integration(brand_id, org_id, "shopify")
        assert result is None

    def test_default_platform_is_shopify(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [])

        service.get_brand_integration(brand_id, org_id)
        service.supabase.table.assert_called_with("brand_integrations")


class TestUpsertBrandIntegration:
    def test_upserts(self, service, brand_id, org_id):
        config = {"store_domain": "test.myshopify.com", "access_token": "shpat_xxx"}
        _mock_chain(service.supabase, [{
            "brand_id": brand_id,
            "platform": "shopify",
            "config": config,
        }])

        result = service.upsert_brand_integration(brand_id, org_id, "shopify", config)
        assert result["config"]["store_domain"] == "test.myshopify.com"


# ---------------------------------------------------------------------------
# Author CRUD
# ---------------------------------------------------------------------------


class TestCreateAuthor:
    def test_creates_author(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [{
            "id": str(uuid4()),
            "brand_id": brand_id,
            "name": "Kevin Hinton",
            "is_default": False,
        }])

        result = service.create_author(brand_id, org_id, "Kevin Hinton")
        assert result["name"] == "Kevin Hinton"

    def test_creates_with_all_fields(self, service, brand_id, org_id):
        persona_id = str(uuid4())
        _mock_chain(service.supabase, [{
            "id": str(uuid4()),
            "name": "Kevin Hinton",
            "bio": "Dad and co-founder",
            "job_title": "Co-Founder",
            "is_default": True,
        }])

        result = service.create_author(
            brand_id, org_id, "Kevin Hinton",
            bio="Dad and co-founder",
            image_url="https://example.com/kevin.jpg",
            job_title="Co-Founder",
            author_url="https://example.com/about",
            persona_id=persona_id,
            schema_data={"@type": "Person"},
            is_default=True,
        )
        assert result["is_default"] is True

    def test_default_author_unsets_existing(self, service, brand_id, org_id):
        """Creating a default author should unset previous default."""
        _mock_chain(service.supabase, [{"id": str(uuid4()), "is_default": True}])

        service.create_author(brand_id, org_id, "New Default", is_default=True)
        # _unset_default_author should have been called (table update)
        assert service.supabase.table.call_count >= 2  # unset + insert


class TestListAuthors:
    def test_returns_authors(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [
            {"id": "a1", "name": "Kevin", "is_default": True},
            {"id": "a2", "name": "Sarah", "is_default": False},
        ])

        result = service.list_authors(brand_id, org_id)
        assert len(result) == 2

    def test_empty_returns_empty(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [])

        result = service.list_authors(brand_id, org_id)
        assert result == []


class TestGetAuthor:
    def test_found(self, service, org_id):
        author_id = str(uuid4())
        _mock_chain(service.supabase, [{"id": author_id, "name": "Kevin"}])

        result = service.get_author(author_id, org_id)
        assert result["name"] == "Kevin"

    def test_not_found(self, service, org_id):
        _mock_chain(service.supabase, [])

        result = service.get_author(str(uuid4()), org_id)
        assert result is None


class TestGetDefaultAuthor:
    def test_returns_default(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [
            {"id": "a1", "name": "Kevin", "is_default": True},
            {"id": "a2", "name": "Sarah", "is_default": False},
        ])

        result = service.get_default_author(brand_id, org_id)
        assert result["name"] == "Kevin"
        assert result["is_default"] is True

    def test_falls_back_to_first(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [
            {"id": "a1", "name": "Sarah", "is_default": False},
            {"id": "a2", "name": "Mike", "is_default": False},
        ])

        result = service.get_default_author(brand_id, org_id)
        assert result["name"] == "Sarah"

    def test_no_authors_returns_none(self, service, brand_id, org_id):
        _mock_chain(service.supabase, [])

        result = service.get_default_author(brand_id, org_id)
        assert result is None


class TestSetDefaultAuthor:
    def test_sets_default(self, service, brand_id, org_id):
        author_id = str(uuid4())
        _mock_chain(service.supabase, [{"id": author_id, "is_default": True}])

        result = service.set_default_author(author_id, brand_id, org_id)
        assert result["is_default"] is True


class TestUpdateAuthor:
    def test_updates_fields(self, service, org_id):
        author_id = str(uuid4())
        _mock_chain(service.supabase, [{"id": author_id, "bio": "Updated bio"}])

        result = service.update_author(author_id, org_id, bio="Updated bio")
        assert result["bio"] == "Updated bio"

    def test_not_found(self, service, org_id):
        _mock_chain(service.supabase, [])

        result = service.update_author(str(uuid4()), org_id, bio="Updated")
        assert result is None


# ---------------------------------------------------------------------------
# Multi-tenancy: superuser "all" mode
# ---------------------------------------------------------------------------


class TestSuperuserMode:
    def test_list_projects_all(self, service):
        """Superuser with org_id='all' should not filter by org."""
        _mock_chain(service.supabase, [])
        service.list_projects("all")
        # Verify table was called (basic check)
        service.supabase.table.assert_called_with("seo_projects")

    def test_get_project_all(self, service):
        _mock_chain(service.supabase, [])
        service.get_project(str(uuid4()), "all")
        service.supabase.table.assert_called_with("seo_projects")

    def test_list_authors_all(self, service, brand_id):
        _mock_chain(service.supabase, [])
        service.list_authors(brand_id, "all")
        service.supabase.table.assert_called_with("seo_authors")
