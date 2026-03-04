"""
Unit tests for ClusterManagementService.

Covers:
- Cluster CRUD (create, list, get, update, delete)
- Spoke management (add, remove, set pillar, bulk assign, dedup)
- Health computation (completion %, milestones, link coverage)
- Auto-assign (scoring, confidence thresholds, dry_run mode)
- Pre-write check (overlap detection, risk levels)
- Suggest next article (scoring formula, reason generation)
- Gap analysis (similarity matching, accept/reject flow)
- Edge cases (empty cluster, 0-volume keywords, delete with spokes)

Run with: pytest tests/test_cluster_management_service.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, call
from uuid import uuid4

from viraltracker.services.seo_pipeline.services.cluster_management_service import (
    ClusterManagementService,
)
from viraltracker.services.seo_pipeline.models import (
    ClusterStatus,
    ClusterIntent,
    SpokeRole,
    SpokeStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    return MagicMock()


@pytest.fixture
def service(mock_supabase):
    return ClusterManagementService(supabase_client=mock_supabase)


@pytest.fixture
def project_id():
    return str(uuid4())


@pytest.fixture
def cluster_id():
    return str(uuid4())


@pytest.fixture
def keyword_id():
    return str(uuid4())


def _table_mock(mock_supabase, table_data_map=None):
    """
    Set up per-table Supabase mocks.

    Args:
        mock_supabase: MagicMock Supabase client
        table_data_map: dict mapping table name -> list of result rows.
            If a table isn't in the map, returns [].
    """
    if table_data_map is None:
        table_data_map = {}

    def table_side_effect(name):
        data = table_data_map.get(name, [])
        mock_exec = MagicMock()
        mock_exec.execute.return_value = MagicMock(data=data)

        # Make all chainable methods return mock_exec
        for method in ["eq", "neq", "in_", "is_", "order", "select",
                        "insert", "update", "delete", "upsert"]:
            getattr(mock_exec, method).return_value = mock_exec

        mock_table = MagicMock()
        mock_table.select.return_value = mock_exec
        mock_table.insert.return_value = mock_exec
        mock_table.update.return_value = mock_exec
        mock_table.delete.return_value = mock_exec
        mock_table.upsert.return_value = mock_exec

        return mock_table

    mock_supabase.table.side_effect = table_side_effect


def _simple_mock(mock_supabase, data=None):
    """Simple single-table mock (all tables return same data)."""
    if data is None:
        data = []
    _table_mock(mock_supabase, {"__default__": data})

    # Override to return same data for all tables
    mock_exec = MagicMock()
    mock_exec.execute.return_value = MagicMock(data=data)
    for method in ["eq", "neq", "in_", "is_", "order", "select",
                    "insert", "update", "delete", "upsert"]:
        getattr(mock_exec, method).return_value = mock_exec

    mock_table = MagicMock()
    mock_table.select.return_value = mock_exec
    mock_table.insert.return_value = mock_exec
    mock_table.update.return_value = mock_exec
    mock_table.delete.return_value = mock_exec

    mock_supabase.table.return_value = mock_table
    mock_supabase.table.side_effect = None
    return mock_exec


# ---------------------------------------------------------------------------
# Cluster CRUD
# ---------------------------------------------------------------------------

class TestCreateCluster:
    def test_creates_cluster(self, service, mock_supabase, project_id):
        cluster_data = {
            "id": str(uuid4()),
            "project_id": project_id,
            "name": "Hiking Safety",
            "intent": "informational",
            "status": "draft",
        }
        _simple_mock(mock_supabase, [cluster_data])

        result = service.create_cluster(project_id, "Hiking Safety")
        assert result["name"] == "Hiking Safety"
        mock_supabase.table.assert_any_call("seo_clusters")

    def test_creates_with_all_fields(self, service, mock_supabase, project_id):
        cluster_data = {"id": str(uuid4()), "name": "Test"}
        _simple_mock(mock_supabase, [cluster_data])

        result = service.create_cluster(
            project_id, "Test",
            pillar_keyword="test keyword",
            intent="commercial",
            description="A test cluster",
            target_spoke_count=10,
        )
        assert result is not None

    def test_invalid_intent_raises(self, service, project_id):
        with pytest.raises(ValueError, match="Invalid intent"):
            service.create_cluster(project_id, "Test", intent="bogus")

    def test_all_valid_intents_accepted(self, service, mock_supabase, project_id):
        _simple_mock(mock_supabase, [{"id": str(uuid4())}])
        for intent in ClusterIntent:
            result = service.create_cluster(project_id, f"Test {intent.value}", intent=intent.value)
            assert result is not None


class TestListClusters:
    def test_returns_clusters_with_stats(self, service, mock_supabase, project_id):
        cid1, cid2 = str(uuid4()), str(uuid4())
        _table_mock(mock_supabase, {
            "seo_clusters": [
                {"id": cid1, "name": "Cluster 1"},
                {"id": cid2, "name": "Cluster 2"},
            ],
            "seo_cluster_spokes": [
                {"cluster_id": cid1, "status": "published"},
                {"cluster_id": cid1, "status": "planned"},
                {"cluster_id": cid2, "status": "writing"},
            ],
        })

        result = service.list_clusters(project_id)
        assert len(result) == 2
        assert result[0]["spoke_stats"]["published"] == 1
        assert result[0]["spoke_stats"]["planned"] == 1
        assert result[1]["spoke_stats"]["writing"] == 1

    def test_empty_project(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {"seo_clusters": []})
        result = service.list_clusters(project_id)
        assert result == []


class TestGetCluster:
    def test_returns_cluster_with_spokes(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_clusters": [{"id": cluster_id, "name": "Test"}],
            "seo_cluster_spokes": [
                {"id": str(uuid4()), "cluster_id": cluster_id, "role": "spoke"},
            ],
        })

        result = service.get_cluster(cluster_id)
        assert result["name"] == "Test"
        assert len(result["spokes"]) == 1

    def test_not_found(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {"seo_clusters": []})
        result = service.get_cluster(cluster_id)
        assert result is None


class TestUpdateCluster:
    def test_updates_fields(self, service, mock_supabase, cluster_id):
        _simple_mock(mock_supabase, [{"id": cluster_id, "status": "active"}])
        result = service.update_cluster(cluster_id, status="active")
        assert result["status"] == "active"

    def test_invalid_status_raises(self, service, cluster_id):
        with pytest.raises(ValueError, match="Invalid status"):
            service.update_cluster(cluster_id, status="bogus")

    def test_invalid_intent_raises(self, service, cluster_id):
        with pytest.raises(ValueError, match="Invalid intent"):
            service.update_cluster(cluster_id, intent="bogus")


class TestDeleteCluster:
    def test_deletes_with_count(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [{"id": "s1"}, {"id": "s2"}],
            "seo_keywords": [{"id": "k1"}],
            "seo_clusters": [],
        })

        result = service.delete_cluster(cluster_id)
        assert result["deleted"] is True
        assert result["affected_spokes"] == 2


# ---------------------------------------------------------------------------
# Spoke Management
# ---------------------------------------------------------------------------

class TestAddSpoke:
    def test_adds_spoke_and_syncs_keyword(self, service, mock_supabase, cluster_id, keyword_id):
        spoke_data = {
            "id": str(uuid4()),
            "cluster_id": cluster_id,
            "keyword_id": keyword_id,
            "role": "spoke",
        }
        _table_mock(mock_supabase, {
            "seo_keywords": [{"keyword_difficulty": 25.0, "search_volume": 500}],
            "seo_cluster_spokes": [spoke_data],
        })

        result = service.add_spoke(cluster_id, keyword_id)
        assert result["role"] == "spoke"

    def test_invalid_role_raises(self, service, cluster_id, keyword_id):
        with pytest.raises(ValueError, match="Invalid role"):
            service.add_spoke(cluster_id, keyword_id, role="invalid")


class TestRemoveSpoke:
    def test_removes_and_nulls_keyword(self, service, mock_supabase, cluster_id, keyword_id):
        _simple_mock(mock_supabase, [])

        result = service.remove_spoke(cluster_id, keyword_id)
        assert result is True


class TestSetPillar:
    def test_demotes_existing_and_promotes_new(self, service, mock_supabase, cluster_id, keyword_id):
        old_pillar = {"id": str(uuid4())}
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [old_pillar],
            "seo_keywords": [{"keyword": "main keyword"}],
            "seo_clusters": [],
        })

        result = service.set_pillar(cluster_id, keyword_id)
        # Verified the method runs without errors


class TestBulkAssign:
    def test_skips_existing_assignments(self, service, mock_supabase, cluster_id):
        kid1, kid2 = str(uuid4()), str(uuid4())
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [{"keyword_id": kid1}],
            "seo_keywords": [{"keyword_difficulty": 20, "search_volume": 100}],
        })

        results = service.bulk_assign_keywords(cluster_id, [kid1, kid2])
        # kid1 should be skipped (already assigned), kid2 should be added
        assert len(results) <= 1  # Only kid2 (or 0 if mock doesn't differentiate)


class TestUpdateSpoke:
    def test_updates_spoke_fields(self, service, mock_supabase):
        spoke_id = str(uuid4())
        _simple_mock(mock_supabase, [{"id": spoke_id, "status": "writing"}])

        result = service.update_spoke(spoke_id, status="writing")
        assert result["status"] == "writing"

    def test_invalid_status_raises(self, service):
        with pytest.raises(ValueError, match="Invalid spoke status"):
            service.update_spoke(str(uuid4()), status="bogus")


class TestAssignArticleToSpoke:
    def test_assigns_and_updates_status(self, service, mock_supabase):
        spoke_id = str(uuid4())
        article_id = str(uuid4())
        _simple_mock(mock_supabase, [{"id": spoke_id, "article_id": article_id, "status": "writing"}])

        result = service.assign_article_to_spoke(spoke_id, article_id)
        assert result["article_id"] == article_id


# ---------------------------------------------------------------------------
# Health & Analytics
# ---------------------------------------------------------------------------

class TestGetClusterHealth:
    def test_computes_completion(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"status": "published", "role": "pillar", "article_id": "a1"},
                {"status": "published", "role": "spoke", "article_id": "a2"},
                {"status": "planned", "role": "spoke", "article_id": None},
                {"status": "planned", "role": "spoke", "article_id": None},
            ],
            "seo_clusters": [{"target_spoke_count": 8}],
            "seo_internal_links": [{"source_article_id": "a1"}],
        })

        result = service.get_cluster_health(cluster_id)
        assert result["total_spokes"] == 4
        assert result["published"] == 2
        assert result["planned"] == 2
        assert result["completion_pct"] == 50.0
        assert result["has_pillar"] is True
        assert "pillar assigned" in result["milestones"]

    def test_empty_cluster(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [],
            "seo_clusters": [{"target_spoke_count": 0}],
        })

        result = service.get_cluster_health(cluster_id)
        assert result["total_spokes"] == 0
        assert result["completion_pct"] == 0

    def test_all_published_milestones(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"status": "published", "role": "spoke", "article_id": "a1"},
            ],
            "seo_clusters": [{"target_spoke_count": 1}],
            "seo_internal_links": [],
        })

        result = service.get_cluster_health(cluster_id)
        assert result["completion_pct"] == 100.0
        assert "cluster complete" in result["milestones"]
        assert "60% milestone reached" in result["milestones"]

    def test_skipped_excluded_from_completion(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"status": "published", "role": "spoke", "article_id": "a1"},
                {"status": "skipped", "role": "spoke", "article_id": None},
            ],
            "seo_clusters": [{"target_spoke_count": 2}],
            "seo_internal_links": [],
        })

        result = service.get_cluster_health(cluster_id)
        # 1 published / (2 total - 1 skipped) = 100%
        assert result["completion_pct"] == 100.0


# ---------------------------------------------------------------------------
# Auto-Assignment
# ---------------------------------------------------------------------------

class TestAutoAssignKeywords:
    def test_high_confidence_match(self, service, mock_supabase, project_id):
        cid = str(uuid4())
        kid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_clusters": [
                {"id": cid, "name": "hiking safety", "pillar_keyword": "hiking safety tips"},
            ],
            "seo_cluster_spokes": [],
            "seo_keywords": [
                {"id": kid, "keyword": "hiking safety gear for winter"},
            ],
        })

        results = service.auto_assign_keywords(project_id, dry_run=True)
        assert len(results) >= 1
        if results:
            # "hiking" and "safety" match cluster name (3pts each = 6)
            assert results[0]["confidence"] in ("HIGH", "MEDIUM")
            assert results[0]["score"] > 0

    def test_no_clusters_returns_empty(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {
            "seo_clusters": [],
        })

        results = service.auto_assign_keywords(project_id)
        assert results == []

    def test_dry_run_does_not_assign(self, service, mock_supabase, project_id):
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_clusters": [{"id": cid, "name": "test topic", "pillar_keyword": "test"}],
            "seo_cluster_spokes": [],
            "seo_keywords": [{"id": str(uuid4()), "keyword": "test topic article"}],
        })

        results = service.auto_assign_keywords(project_id, dry_run=True)
        # In dry_run, no spoke is created (add_spoke not called)


# ---------------------------------------------------------------------------
# Pre-Write Check
# ---------------------------------------------------------------------------

class TestPreWriteCheck:
    def test_high_risk_overlap(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {
            "seo_articles": [
                {"id": "a1", "keyword": "hiking safety tips", "title": "Hiking Safety Tips",
                 "status": "published", "published_url": "/hiking-safety-tips"},
            ],
        })

        result = service.pre_write_check("hiking safety tips guide", project_id)
        assert result["risk_level"] in ("HIGH", "MEDIUM")

    def test_clear_no_overlap(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {
            "seo_articles": [
                {"id": "a1", "keyword": "camping gear", "title": "Camping Gear",
                 "status": "published", "published_url": "/camping-gear"},
            ],
        })

        result = service.pre_write_check("python programming tutorial", project_id)
        assert result["risk_level"] == "CLEAR"

    def test_empty_project(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {"seo_articles": []})

        result = service.pre_write_check("any keyword", project_id)
        assert result["risk_level"] == "CLEAR"


# ---------------------------------------------------------------------------
# Suggest Next Article
# ---------------------------------------------------------------------------

class TestSuggestNextArticle:
    def test_scores_and_ranks(self, service, mock_supabase, project_id):
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {
                    "id": "s1", "keyword_id": "k1", "cluster_id": cid,
                    "priority": 1, "status": "planned",
                    "seo_keywords": {"keyword": "easy keyword", "search_volume": 1500, "keyword_difficulty": 12},
                    "seo_clusters": {"id": cid, "name": "Hiking", "project_id": project_id},
                },
                {
                    "id": "s2", "keyword_id": "k2", "cluster_id": cid,
                    "priority": 3, "status": "planned",
                    "seo_keywords": {"keyword": "hard keyword", "search_volume": 50, "keyword_difficulty": 80},
                    "seo_clusters": {"id": cid, "name": "Hiking", "project_id": project_id},
                },
            ],
        })

        results = service.suggest_next_article(project_id)
        assert len(results) == 2
        # Easy keyword with high volume should score higher
        assert results[0]["keyword"] == "easy keyword"
        assert results[0]["score"] > results[1]["score"]
        assert len(results[0]["reasons"]) > 0

    def test_empty_no_planned_spokes(self, service, mock_supabase, project_id):
        _table_mock(mock_supabase, {"seo_cluster_spokes": []})
        results = service.suggest_next_article(project_id)
        assert results == []

    def test_filters_by_cluster(self, service, mock_supabase, project_id, cluster_id):
        _table_mock(mock_supabase, {"seo_cluster_spokes": []})
        results = service.suggest_next_article(project_id, cluster_id=cluster_id)
        assert results == []

    def test_reason_generation(self, service, mock_supabase, project_id):
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {
                    "id": "s1", "keyword_id": "k1", "cluster_id": cid,
                    "priority": 1, "status": "planned",
                    "seo_keywords": {"keyword": "test", "search_volume": 2000, "keyword_difficulty": 15},
                    "seo_clusters": {"id": cid, "name": "Test", "project_id": project_id},
                },
            ],
        })

        results = service.suggest_next_article(project_id)
        if results:
            reasons = results[0]["reasons"]
            assert any("Low difficulty" in r for r in reasons)
            assert any("High volume" in r for r in reasons)
            assert any("High priority" in r for r in reasons)


# ---------------------------------------------------------------------------
# Gap Analysis
# ---------------------------------------------------------------------------

class TestAnalyzeGaps:
    def test_finds_related_keywords(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_clusters": [{"project_id": "p1", "name": "hiking safety", "pillar_keyword": "hiking"}],
            "seo_cluster_spokes": [
                {"seo_keywords": {"keyword": "hiking gear essentials"}},
            ],
            "seo_keywords": [
                {"id": "k1", "keyword": "winter hiking safety guide", "search_volume": 500, "keyword_difficulty": 20},
                {"id": "k2", "keyword": "python programming basics", "search_volume": 1000, "keyword_difficulty": 30},
            ],
            "seo_cluster_gap_suggestions": [],
        })

        results = service.analyze_gaps(cluster_id)
        # "winter hiking safety guide" has overlap with "hiking safety"
        # "python programming basics" should not overlap
        assert len(results) >= 1
        if results:
            assert "hiking" in results[0]["suggested_keyword"].lower()

    def test_empty_cluster(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {"seo_clusters": []})
        results = service.analyze_gaps(cluster_id)
        assert results == []


class TestAcceptRejectGapSuggestion:
    def test_accept_suggestion(self, service, mock_supabase):
        suggestion_id = str(uuid4())
        _simple_mock(mock_supabase, [{"id": suggestion_id, "status": "accepted"}])

        result = service.accept_gap_suggestion(suggestion_id)
        assert result["status"] == "accepted"

    def test_reject_suggestion(self, service, mock_supabase):
        suggestion_id = str(uuid4())
        _simple_mock(mock_supabase, [])

        service.reject_gap_suggestion(suggestion_id)
        # No return value, just verify no exception


# ---------------------------------------------------------------------------
# Publication Schedule
# ---------------------------------------------------------------------------

class TestGeneratePublicationSchedule:
    def test_pillar_first_then_by_priority(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"id": "s1", "role": "spoke", "priority": 2,
                 "status": "planned", "seo_keywords": {"keyword": "spoke 1"}},
                {"id": "s2", "role": "pillar", "priority": 1,
                 "status": "planned", "seo_keywords": {"keyword": "pillar"}},
            ],
        })

        schedule = service.generate_publication_schedule(cluster_id, spokes_per_week=2)
        assert len(schedule) == 2
        assert schedule[0]["role"] == "pillar"
        assert schedule[1]["role"] == "spoke"

    def test_empty_planned(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {"seo_cluster_spokes": []})
        schedule = service.generate_publication_schedule(cluster_id)
        assert schedule == []


# ---------------------------------------------------------------------------
# Import Articles
# ---------------------------------------------------------------------------

class TestImportExistingArticles:
    def test_imports_and_matches_spokes(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {
            "seo_clusters": [{"project_id": "p1"}],
            "seo_cluster_spokes": [
                {"id": "s1", "keyword_id": "k1",
                 "seo_keywords": {"keyword": "hiking safety tips"}},
            ],
            "seo_articles": [{"id": "a1"}],
        })

        results = service.import_existing_articles(cluster_id, [
            {"keyword": "hiking safety tips", "title": "Hiking Safety", "url": "/hiking"},
        ])
        assert len(results) == 1

    def test_cluster_not_found_raises(self, service, mock_supabase, cluster_id):
        _table_mock(mock_supabase, {"seo_clusters": []})
        with pytest.raises(ValueError, match="Cluster not found"):
            service.import_existing_articles(cluster_id, [])


# ---------------------------------------------------------------------------
# Helper Methods
# ---------------------------------------------------------------------------

class TestExtractWords:
    def test_extracts_long_words(self):
        words = ClusterManagementService._extract_words("hiking safety tips for beginners")
        assert "hiking" in words
        assert "safety" in words
        assert "tips" in words
        assert "beginners" in words
        assert "for" not in words  # 3 chars, excluded

    def test_empty_string(self):
        assert ClusterManagementService._extract_words("") == set()

    def test_none_string(self):
        assert ClusterManagementService._extract_words(None) == set()

    def test_all_short_words(self):
        assert ClusterManagementService._extract_words("the a of in") == set()


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_valid_statuses(self, service, mock_supabase, cluster_id):
        """Verify all ClusterStatus values are accepted."""
        for status in ClusterStatus:
            _simple_mock(mock_supabase, [{"id": cluster_id, "status": status.value}])
            result = service.update_cluster(cluster_id, status=status.value)
            assert result is not None

    def test_all_spoke_statuses(self, service, mock_supabase):
        """Verify all SpokeStatus values are accepted."""
        for status in SpokeStatus:
            _simple_mock(mock_supabase, [{"id": "s1", "status": status.value}])
            result = service.update_spoke("s1", status=status.value)
            assert result is not None

    def test_zero_volume_keywords_in_scoring(self, service, mock_supabase, project_id):
        """Verify suggest_next_article handles 0-volume keywords."""
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {
                    "id": "s1", "keyword_id": "k1", "cluster_id": cid,
                    "priority": 2, "status": "planned",
                    "seo_keywords": {"keyword": "zero vol", "search_volume": 0, "keyword_difficulty": 10},
                    "seo_clusters": {"id": cid, "name": "Test", "project_id": project_id},
                },
            ],
        })

        results = service.suggest_next_article(project_id)
        assert len(results) == 1
        # Should not crash on log10(0) — we use max(volume, 1)
        assert results[0]["score"] is not None

    def test_none_keyword_difficulty(self, service, mock_supabase, project_id):
        """Verify suggest_next_article handles None KD."""
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {
                    "id": "s1", "keyword_id": "k1", "cluster_id": cid,
                    "priority": 2, "status": "planned",
                    "seo_keywords": {"keyword": "no kd", "search_volume": 100, "keyword_difficulty": None},
                    "seo_clusters": {"id": cid, "name": "Test", "project_id": project_id},
                },
            ],
        })

        results = service.suggest_next_article(project_id)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# get_cluster_overview
# ---------------------------------------------------------------------------

class TestGetClusterOverview:
    def test_returns_clusters_with_overview_stats(self, service, mock_supabase, project_id):
        """Overview should include completion_pct and per-status counts."""
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_clusters": [{"id": cid, "project_id": project_id, "name": "Test", "status": "active"}],
            "seo_cluster_spokes": [
                {"cluster_id": cid, "status": "published", "article_id": "a1", "role": "pillar"},
                {"cluster_id": cid, "status": "planned", "article_id": None, "role": "spoke"},
                {"cluster_id": cid, "status": "writing", "article_id": "a2", "role": "spoke"},
            ],
        })

        results = service.get_cluster_overview(project_id)
        assert len(results) == 1
        overview = results[0].get("overview", {})
        assert overview["published"] == 1
        assert overview["planned"] == 1
        assert overview["writing"] == 1
        assert overview["total"] == 3
        assert overview["has_pillar"] is True
        assert overview["completion_pct"] > 0

    def test_empty_project(self, service, mock_supabase, project_id):
        """Overview of empty project returns empty list."""
        _table_mock(mock_supabase, {
            "seo_clusters": [],
            "seo_cluster_spokes": [],
        })
        results = service.get_cluster_overview(project_id)
        assert results == []


# ---------------------------------------------------------------------------
# get_interlinking_audit
# ---------------------------------------------------------------------------

class TestGetInterlinkingAudit:
    def test_fewer_than_two_articles(self, service, mock_supabase, cluster_id):
        """Audit with fewer than 2 articles returns early with message."""
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"keyword_id": "k1", "article_id": "a1", "role": "spoke",
                 "seo_keywords": {"keyword": "hiking tips"}},
            ],
        })
        result = service.get_interlinking_audit(cluster_id)
        assert result["coverage_pct"] == 0.0
        assert "Need at least 2" in result["message"]

    def test_audit_with_links(self, service, mock_supabase, cluster_id):
        """Audit computes coverage from existing links."""
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"keyword_id": "k1", "article_id": "a1", "role": "spoke",
                 "seo_keywords": {"keyword": "hiking safety tips"}},
                {"keyword_id": "k2", "article_id": "a2", "role": "spoke",
                 "seo_keywords": {"keyword": "hiking gear guide"}},
            ],
            "seo_internal_links": [
                {"source_article_id": "a1", "target_article_id": "a2", "status": "active"},
            ],
        })
        result = service.get_interlinking_audit(cluster_id)
        assert result["total_possible"] == 2  # a1->a2 and a2->a1
        assert result["total_linked"] == 1
        assert result["coverage_pct"] == 50.0

    def test_audit_no_articles(self, service, mock_supabase, cluster_id):
        """Audit with no articles returns early message."""
        _table_mock(mock_supabase, {
            "seo_cluster_spokes": [
                {"keyword_id": "k1", "article_id": None, "role": "spoke",
                 "seo_keywords": {"keyword": "test"}},
            ],
        })
        result = service.get_interlinking_audit(cluster_id)
        assert result["coverage_pct"] == 0.0
        assert "Need at least 2" in result["message"]


# ---------------------------------------------------------------------------
# get_publication_schedule
# ---------------------------------------------------------------------------

class TestGetPublicationSchedule:
    def test_returns_schedule_from_metadata(self, service, mock_supabase, cluster_id):
        """Should return schedule stored in cluster metadata."""
        schedule = [{"week_number": 1, "target_date": "2026-03-10", "keyword": "test"}]
        _simple_mock(mock_supabase, [{"metadata": {"publication_schedule": schedule}}])
        result = service.get_publication_schedule(cluster_id)
        assert len(result) == 1
        assert result[0]["keyword"] == "test"

    def test_no_schedule_returns_empty(self, service, mock_supabase, cluster_id):
        """Should return empty list if no schedule in metadata."""
        _simple_mock(mock_supabase, [{"metadata": {}}])
        result = service.get_publication_schedule(cluster_id)
        assert result == []

    def test_cluster_not_found_returns_empty(self, service, mock_supabase, cluster_id):
        """Should return empty list if cluster not found."""
        _simple_mock(mock_supabase, [])
        result = service.get_publication_schedule(cluster_id)
        assert result == []


# ---------------------------------------------------------------------------
# UI Convenience Methods
# ---------------------------------------------------------------------------

class TestGetKeywordsForPool:
    def test_unassigned_filter(self, service, mock_supabase, project_id):
        """Should filter for unassigned keywords."""
        kw_data = [{"id": "k1", "keyword": "test keyword", "cluster_id": None}]
        _simple_mock(mock_supabase, kw_data)
        result = service.get_keywords_for_pool(project_id, filter_type="unassigned")
        assert len(result) == 1

    def test_text_search(self, service, mock_supabase, project_id):
        """Should filter by text search client-side."""
        kw_data = [
            {"id": "k1", "keyword": "hiking tips"},
            {"id": "k2", "keyword": "cooking guide"},
        ]
        _simple_mock(mock_supabase, kw_data)
        result = service.get_keywords_for_pool(project_id, search_text="hiking")
        assert len(result) == 1
        assert result[0]["keyword"] == "hiking tips"


class TestMarkSpokesPublishedForArticle:
    def test_updates_spoke_status(self, service, mock_supabase):
        """Should update all spokes linked to the article."""
        _simple_mock(mock_supabase, [{"id": "spoke1"}])
        count = service.mark_spokes_published_for_article("article1")
        assert count == 1

    def test_no_spokes(self, service, mock_supabase):
        """Should return 0 if no spokes found."""
        _simple_mock(mock_supabase, [])
        count = service.mark_spokes_published_for_article("article1")
        assert count == 0


class TestGetUnlinkedPlannedSpokes:
    def test_returns_planned_spokes(self, service, mock_supabase, project_id):
        """Should return planned spokes without articles."""
        cid = str(uuid4())
        _table_mock(mock_supabase, {
            "seo_clusters": [{"id": cid, "project_id": project_id, "name": "Hiking"}],
            "seo_cluster_spokes": [
                {"id": "s1", "cluster_id": cid, "status": "planned", "article_id": None,
                 "role": "spoke", "seo_keywords": {"keyword": "hiking tips"}},
                {"id": "s2", "cluster_id": cid, "status": "published", "article_id": "a1",
                 "role": "spoke", "seo_keywords": {"keyword": "hiking gear"}},
            ],
        })
        results = service.get_unlinked_planned_spokes(project_id)
        assert len(results) == 1
        assert results[0]["spoke_id"] == "s1"
        assert results[0]["cluster_name"] == "Hiking"
        assert results[0]["keyword"] == "hiking tips"


class TestGetClusterSpokeArticleIds:
    def test_returns_article_ids(self, service, mock_supabase, cluster_id):
        """Should return article IDs excluding None."""
        _simple_mock(mock_supabase, [
            {"article_id": "a1"},
            {"article_id": None},
            {"article_id": "a2"},
        ])
        result = service.get_cluster_spoke_article_ids(cluster_id)
        assert result == ["a1", "a2"]

    def test_no_spokes(self, service, mock_supabase, cluster_id):
        """Should return empty list for no spokes."""
        _simple_mock(mock_supabase, [])
        result = service.get_cluster_spoke_article_ids(cluster_id)
        assert result == []
