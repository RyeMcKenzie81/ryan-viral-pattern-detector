"""
Integration tests for ClusterManagementService against real Supabase.

Creates temporary test data (project, keywords, clusters, spokes) and cleans up
after each test. Tests the full lifecycle: create → assign → health → suggest → delete.

Run with: pytest tests/test_cluster_management_integration.py -v -s
Requires: SUPABASE_URL and SUPABASE_SERVICE_KEY in .env
"""

import os
import sys
import pytest
from uuid import uuid4

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Skip if no Supabase credentials
# ---------------------------------------------------------------------------

def _has_supabase():
    try:
        from viraltracker.core.config import Config
        return bool(Config.SUPABASE_URL and Config.SUPABASE_SERVICE_KEY)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_supabase(),
    reason="Requires SUPABASE_URL and SUPABASE_SERVICE_KEY",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def supabase():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


@pytest.fixture
def cluster_service():
    from viraltracker.services.seo_pipeline.services.cluster_management_service import (
        ClusterManagementService,
    )
    return ClusterManagementService()


@pytest.fixture
def test_org_id(supabase):
    """Look up first real organization from database."""
    override = os.getenv("TEST_ORG_ID")
    if override:
        return override
    orgs = supabase.table("organizations").select("id").limit(1).execute()
    assert orgs.data, "No organizations in database — create one first"
    return orgs.data[0]["id"]


@pytest.fixture
def test_brand_id(supabase):
    """Look up first real brand from database."""
    override = os.getenv("TEST_BRAND_ID")
    if override:
        return override
    brands = supabase.table("brands").select("id").limit(1).execute()
    assert brands.data, "No brands in database — create one first"
    return brands.data[0]["id"]


@pytest.fixture
def test_project(supabase, test_org_id, test_brand_id):
    """Create a temporary SEO project and clean up after test."""
    project_data = {
        "name": f"_test_cluster_integration_{uuid4().hex[:8]}",
        "organization_id": test_org_id,
        "brand_id": test_brand_id,
        "status": "active",
    }
    result = supabase.table("seo_projects").insert(project_data).execute()
    project = result.data[0]

    yield project

    # Cleanup: delete project (cascades to clusters via FK)
    supabase.table("seo_projects").delete().eq("id", project["id"]).execute()


@pytest.fixture
def test_keywords(supabase, test_project):
    """Create 5 test keywords and clean up after test."""
    project_id = test_project["id"]
    keywords_data = [
        {"project_id": project_id, "keyword": "hiking safety tips for beginners",
         "search_volume": 1200, "keyword_difficulty": 15, "status": "discovered"},
        {"project_id": project_id, "keyword": "best hiking boots waterproof",
         "search_volume": 800, "keyword_difficulty": 25, "status": "discovered"},
        {"project_id": project_id, "keyword": "hiking trail snacks healthy",
         "search_volume": 500, "keyword_difficulty": 10, "status": "discovered"},
        {"project_id": project_id, "keyword": "camping gear checklist",
         "search_volume": 2000, "keyword_difficulty": 30, "status": "discovered"},
        {"project_id": project_id, "keyword": "rock climbing for beginners",
         "search_volume": 900, "keyword_difficulty": 20, "status": "discovered"},
    ]
    result = supabase.table("seo_keywords").insert(keywords_data).execute()
    keywords = result.data

    yield keywords

    # Cleanup
    for kw in keywords:
        supabase.table("seo_keywords").delete().eq("id", kw["id"]).execute()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClusterLifecycle:
    """Full create → populate → query → delete lifecycle."""

    def test_create_and_get_cluster(self, cluster_service, test_project):
        """Create a cluster and verify it can be retrieved."""
        project_id = test_project["id"]

        cluster = cluster_service.create_cluster(
            project_id,
            name="Hiking Safety",
            pillar_keyword="hiking safety tips",
            intent="informational",
            description="All about hiking safety",
            target_spoke_count=5,
        )

        assert cluster["id"] is not None
        assert cluster["name"] == "Hiking Safety"
        assert cluster["intent"] == "informational"
        assert cluster["status"] == "draft"
        assert cluster["target_spoke_count"] == 5

        # Retrieve it
        fetched = cluster_service.get_cluster(cluster["id"])
        assert fetched is not None
        assert fetched["name"] == "Hiking Safety"
        assert fetched["description"] == "All about hiking safety"

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_list_clusters(self, cluster_service, test_project):
        """Create multiple clusters and verify list returns them."""
        project_id = test_project["id"]

        c1 = cluster_service.create_cluster(project_id, "Cluster A")
        c2 = cluster_service.create_cluster(project_id, "Cluster B")

        clusters = cluster_service.list_clusters(project_id)
        names = [c["name"] for c in clusters]
        assert "Cluster A" in names
        assert "Cluster B" in names

        # Each cluster should have spoke_stats
        for c in clusters:
            assert "spoke_stats" in c
            assert c["spoke_stats"]["total"] == 0

        # Cleanup
        cluster_service.delete_cluster(c1["id"])
        cluster_service.delete_cluster(c2["id"])

    def test_update_cluster(self, cluster_service, test_project):
        """Update cluster fields."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Update Me")

        updated = cluster_service.update_cluster(
            cluster["id"],
            status="active",
            intent="commercial",
            description="Updated description",
        )

        assert updated["status"] == "active"
        assert updated["intent"] == "commercial"
        assert updated["description"] == "Updated description"

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_delete_cluster_returns_affected_count(self, cluster_service, test_project, test_keywords):
        """Delete cluster reports affected spoke count."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Delete Me")

        # Add 2 spokes
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])
        cluster_service.add_spoke(cluster["id"], test_keywords[1]["id"])

        result = cluster_service.delete_cluster(cluster["id"])
        assert result["deleted"] is True
        assert result["affected_spokes"] == 2

        # Verify it's gone
        fetched = cluster_service.get_cluster(cluster["id"])
        assert fetched is None


class TestSpokeManagement:
    """Add, remove, bulk assign, and set pillar."""

    def test_add_and_remove_spoke(self, cluster_service, test_project, test_keywords):
        """Add a spoke, verify it exists, then remove it."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Spoke Test")
        kw = test_keywords[0]

        # Add
        spoke = cluster_service.add_spoke(cluster["id"], kw["id"], priority=1)
        assert spoke["cluster_id"] == cluster["id"]
        assert spoke["keyword_id"] == kw["id"]
        assert spoke["priority"] == 1
        assert spoke["status"] == "planned"

        # Verify in cluster
        full = cluster_service.get_cluster(cluster["id"])
        assert len(full["spokes"]) == 1

        # Remove
        cluster_service.remove_spoke(cluster["id"], kw["id"])
        full = cluster_service.get_cluster(cluster["id"])
        assert len(full.get("spokes", [])) == 0

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_bulk_assign(self, cluster_service, test_project, test_keywords):
        """Bulk assign keywords, verify dedup on re-assign."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Bulk Test")
        kw_ids = [kw["id"] for kw in test_keywords[:3]]

        # First assign
        results = cluster_service.bulk_assign_keywords(cluster["id"], kw_ids)
        assert len(results) == 3

        # Re-assign same keywords — should skip existing
        results2 = cluster_service.bulk_assign_keywords(cluster["id"], kw_ids)
        # Should not create duplicates
        full = cluster_service.get_cluster(cluster["id"])
        assert len(full["spokes"]) == 3

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_set_pillar(self, cluster_service, test_project, test_keywords):
        """Set a keyword as pillar, verify it's reflected."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Pillar Test")

        kw1 = test_keywords[0]
        kw2 = test_keywords[1]

        cluster_service.add_spoke(cluster["id"], kw1["id"])
        cluster_service.add_spoke(cluster["id"], kw2["id"])

        # Set kw1 as pillar
        cluster_service.set_pillar(cluster["id"], kw1["id"])

        full = cluster_service.get_cluster(cluster["id"])
        pillar_spokes = [s for s in full["spokes"] if s["role"] == "pillar"]
        assert len(pillar_spokes) == 1
        assert pillar_spokes[0]["keyword_id"] == kw1["id"]

        # Switch pillar to kw2
        cluster_service.set_pillar(cluster["id"], kw2["id"])
        full = cluster_service.get_cluster(cluster["id"])
        pillar_spokes = [s for s in full["spokes"] if s["role"] == "pillar"]
        assert len(pillar_spokes) == 1
        assert pillar_spokes[0]["keyword_id"] == kw2["id"]

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])


class TestHealthAndAnalytics:
    """Health metrics, overview, and interlinking audit."""

    def test_cluster_health(self, cluster_service, test_project, test_keywords):
        """Health should reflect spoke statuses."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(
            project_id, "Health Test", target_spoke_count=5,
        )

        # Add 3 spokes with different statuses
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])
        cluster_service.add_spoke(cluster["id"], test_keywords[1]["id"])
        cluster_service.add_spoke(cluster["id"], test_keywords[2]["id"])

        # Update statuses
        full = cluster_service.get_cluster(cluster["id"])
        spokes = full["spokes"]
        cluster_service.update_spoke(spokes[0]["id"], status="published")
        cluster_service.update_spoke(spokes[1]["id"], status="writing")
        # spokes[2] stays "planned"

        health = cluster_service.get_cluster_health(cluster["id"])
        assert health["total_spokes"] == 3
        assert health["published"] == 1
        assert health["writing"] == 1
        assert health["planned"] == 1
        assert health["completion_pct"] > 0  # 1/3 = 33.3%
        assert health["target_spoke_count"] == 5
        assert "3/5" in health["target_progress"]

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_cluster_overview(self, cluster_service, test_project, test_keywords):
        """Overview should return all clusters with aggregated stats."""
        project_id = test_project["id"]

        c1 = cluster_service.create_cluster(project_id, "Overview A")
        c2 = cluster_service.create_cluster(project_id, "Overview B")

        cluster_service.add_spoke(c1["id"], test_keywords[0]["id"])
        cluster_service.add_spoke(c2["id"], test_keywords[1]["id"])
        cluster_service.add_spoke(c2["id"], test_keywords[2]["id"])

        overview = cluster_service.get_cluster_overview(project_id)
        assert len(overview) >= 2

        for c in overview:
            if c["id"] == c1["id"]:
                assert c["spoke_stats"]["total"] == 1
            elif c["id"] == c2["id"]:
                assert c["spoke_stats"]["total"] == 2

        # Cleanup
        cluster_service.delete_cluster(c1["id"])
        cluster_service.delete_cluster(c2["id"])


class TestAutoAssign:
    """Auto-assignment scoring and dry_run mode."""

    def test_auto_assign_dry_run(self, cluster_service, test_project, test_keywords):
        """Dry run should suggest matches without assigning."""
        project_id = test_project["id"]

        # Create a cluster named "hiking" — should match hiking keywords
        cluster = cluster_service.create_cluster(
            project_id, "Hiking Safety",
            pillar_keyword="hiking safety tips",
        )

        results = cluster_service.auto_assign_keywords(project_id, dry_run=True)

        # Should find matches for hiking-related keywords
        matched_keywords = [r["keyword"] for r in results if r["confidence"] in ("HIGH", "MEDIUM")]
        assert len(matched_keywords) > 0, f"Expected hiking matches, got: {results}"

        # Verify nothing was actually assigned (dry run)
        for kw in test_keywords:
            from viraltracker.core.database import get_supabase_client
            sb = get_supabase_client()
            check = (
                sb.table("seo_cluster_spokes")
                .select("id")
                .eq("keyword_id", kw["id"])
                .eq("cluster_id", cluster["id"])
                .execute()
            )
            assert len(check.data) == 0, f"Keyword {kw['keyword']} was assigned during dry_run!"

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])


class TestPreWriteCheck:
    """Pre-write overlap detection."""

    def test_pre_write_check_detects_overlap(self, cluster_service, test_project, test_keywords, supabase):
        """Should detect overlap with existing articles."""
        project_id = test_project["id"]

        # Create an article for one of the keywords
        article = supabase.table("seo_articles").insert({
            "project_id": project_id,
            "keyword": "hiking safety tips for beginners",
            "status": "published",
            "brand_id": test_project["brand_id"],
            "organization_id": test_project["organization_id"],
        }).execute().data[0]

        # Check a very similar keyword
        result = cluster_service.pre_write_check(
            "hiking safety tips guide beginners",
            project_id,
        )

        assert result["risk_level"] in ("HIGH", "MEDIUM"), (
            f"Expected overlap detected, got: {result['risk_level']}"
        )
        assert len(result["overlapping_articles"]) > 0 or len(result["link_candidates"]) > 0

        # Check a completely different keyword
        clear_result = cluster_service.pre_write_check(
            "python programming tutorial advanced",
            project_id,
        )
        assert clear_result["risk_level"] == "CLEAR"

        # Cleanup
        supabase.table("seo_articles").delete().eq("id", article["id"]).execute()


class TestSuggestNextArticle:
    """Next article suggestion scoring."""

    def test_suggests_planned_spokes(self, cluster_service, test_project, test_keywords):
        """Should suggest planned spokes ranked by score."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Suggest Test")

        # Add 3 spokes
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"], priority=1)
        cluster_service.add_spoke(cluster["id"], test_keywords[1]["id"], priority=2)
        cluster_service.add_spoke(cluster["id"], test_keywords[2]["id"], priority=3)

        suggestions = cluster_service.suggest_next_article(
            project_id, cluster_id=cluster["id"],
        )

        assert len(suggestions) > 0
        # Should be ranked by score (descending)
        scores = [s["score"] for s in suggestions]
        assert scores == sorted(scores, reverse=True), "Suggestions should be ranked by score"

        # Each suggestion should have reasons
        for s in suggestions:
            assert len(s["reasons"]) > 0
            assert s["keyword"] is not None
            assert s["score"] > 0

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])


class TestConvenienceMethods:
    """New UI convenience methods."""

    def test_get_keywords_for_pool(self, cluster_service, test_project, test_keywords):
        """Should fetch and filter keywords."""
        project_id = test_project["id"]

        # All keywords should be unassigned initially
        pool = cluster_service.get_keywords_for_pool(project_id, filter_type="unassigned")
        assert len(pool) >= 5

        # Text search
        hiking = cluster_service.get_keywords_for_pool(
            project_id, search_text="hiking",
        )
        assert all("hiking" in k["keyword"] for k in hiking)

        # Assign one, then check assigned filter
        cluster = cluster_service.create_cluster(project_id, "Pool Test")
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])

        assigned = cluster_service.get_keywords_for_pool(project_id, filter_type="assigned")
        assert any(k["id"] == test_keywords[0]["id"] for k in assigned)

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_get_unlinked_planned_spokes(self, cluster_service, test_project, test_keywords):
        """Should return planned spokes without linked articles."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Unlinked Test")

        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])
        cluster_service.add_spoke(cluster["id"], test_keywords[1]["id"])

        spokes = cluster_service.get_unlinked_planned_spokes(project_id)
        assert len(spokes) >= 2
        for s in spokes:
            assert "spoke_id" in s
            assert "cluster_name" in s
            assert "keyword" in s

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])

    def test_get_cluster_spoke_article_ids(self, cluster_service, test_project, test_keywords, supabase):
        """Should return article IDs for cluster spokes."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Article IDs Test")

        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])

        # No articles linked yet
        ids = cluster_service.get_cluster_spoke_article_ids(cluster["id"])
        assert ids == []

        # Create and link an article
        article = supabase.table("seo_articles").insert({
            "project_id": project_id,
            "keyword": "test",
            "status": "draft",
            "brand_id": test_project["brand_id"],
            "organization_id": test_project["organization_id"],
        }).execute().data[0]

        full = cluster_service.get_cluster(cluster["id"])
        spoke_id = full["spokes"][0]["id"]
        cluster_service.assign_article_to_spoke(spoke_id, article["id"])

        ids = cluster_service.get_cluster_spoke_article_ids(cluster["id"])
        assert article["id"] in ids

        # Cleanup
        supabase.table("seo_articles").delete().eq("id", article["id"]).execute()
        cluster_service.delete_cluster(cluster["id"])

    def test_mark_spokes_published_for_article(self, cluster_service, test_project, test_keywords, supabase):
        """Should mark spokes as published when article is published."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Publish Test")

        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])

        # Create and link article
        article = supabase.table("seo_articles").insert({
            "project_id": project_id,
            "keyword": "test publish",
            "status": "published",
            "brand_id": test_project["brand_id"],
            "organization_id": test_project["organization_id"],
        }).execute().data[0]

        full = cluster_service.get_cluster(cluster["id"])
        spoke_id = full["spokes"][0]["id"]
        cluster_service.assign_article_to_spoke(spoke_id, article["id"])

        # Mark published
        count = cluster_service.mark_spokes_published_for_article(article["id"])
        assert count == 1

        # Verify status changed
        full = cluster_service.get_cluster(cluster["id"])
        assert full["spokes"][0]["status"] == "published"

        # Cleanup
        supabase.table("seo_articles").delete().eq("id", article["id"]).execute()
        cluster_service.delete_cluster(cluster["id"])


class TestPublicationSchedule:
    """Schedule generation and retrieval."""

    def test_generate_and_get_schedule(self, cluster_service, test_project, test_keywords):
        """Generate a schedule and verify it's retrievable."""
        project_id = test_project["id"]
        cluster = cluster_service.create_cluster(project_id, "Schedule Test")

        # Add spokes
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"], priority=1)
        cluster_service.add_spoke(cluster["id"], test_keywords[1]["id"], priority=2)
        cluster_service.add_spoke(cluster["id"], test_keywords[2]["id"], priority=3)

        # Generate schedule
        schedule = cluster_service.generate_publication_schedule(
            cluster["id"], spokes_per_week=2,
        )
        assert len(schedule) == 3  # 3 planned spokes

        # Verify ordering: priority 1 first
        assert schedule[0]["keyword"] is not None
        for item in schedule:
            assert "week_number" in item
            assert "target_date" in item
            assert "keyword" in item

        # Verify it's stored and retrievable
        stored = cluster_service.get_publication_schedule(cluster["id"])
        assert len(stored) == 3

        # Cleanup
        cluster_service.delete_cluster(cluster["id"])


class TestValidationEnforcement:
    """Verify enum validation catches bad values."""

    def test_invalid_intent_rejected(self, cluster_service, test_project):
        """Invalid intent should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid intent"):
            cluster_service.create_cluster(
                test_project["id"], "Bad Intent", intent="bogus",
            )

    def test_invalid_status_rejected(self, cluster_service, test_project):
        """Invalid status should raise ValueError."""
        cluster = cluster_service.create_cluster(test_project["id"], "Bad Status")
        with pytest.raises(ValueError, match="Invalid status"):
            cluster_service.update_cluster(cluster["id"], status="bogus")
        cluster_service.delete_cluster(cluster["id"])

    def test_invalid_spoke_role_rejected(self, cluster_service, test_project, test_keywords):
        """Invalid spoke role should raise ValueError."""
        cluster = cluster_service.create_cluster(test_project["id"], "Bad Role")
        with pytest.raises(ValueError, match="Invalid role"):
            cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"], role="bogus")
        cluster_service.delete_cluster(cluster["id"])

    def test_invalid_spoke_status_rejected(self, cluster_service, test_project, test_keywords):
        """Invalid spoke status should raise ValueError."""
        cluster = cluster_service.create_cluster(test_project["id"], "Bad Spoke Status")
        cluster_service.add_spoke(cluster["id"], test_keywords[0]["id"])
        full = cluster_service.get_cluster(cluster["id"])
        spoke_id = full["spokes"][0]["id"]
        with pytest.raises(ValueError, match="Invalid spoke status"):
            cluster_service.update_spoke(spoke_id, status="bogus")
        cluster_service.delete_cluster(cluster["id"])
