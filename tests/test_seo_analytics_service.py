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
from datetime import datetime, timedelta, timezone

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

    def test_dashboard_link_stats_batch(self, service, sample_keywords):
        """Link stats now use batch .in_() query instead of N+1 loop."""
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
            {"id": "link-1", "status": "implemented"},
            {"id": "link-2", "status": "pending"},
            {"id": "link-3", "status": "implemented"},
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
                # batch uses .in_() instead of .eq()
                mock_table.select.return_value.in_.return_value.execute.return_value = mock_exec
            return mock_table

        service._supabase.table.side_effect = table_side_effect

        result = service.get_project_dashboard("proj-001", "org-001")

        assert result["links"]["total"] == 3
        assert result["links"]["implemented"] == 2
        assert result["links"]["suggested"] == 1


# =============================================================================
# BRAND DASHBOARD
# =============================================================================

class TestGetBrandDashboard:
    def test_zero_projects(self, service):
        """No projects should return zero-state dict, never error."""
        mock_exec = MagicMock()
        mock_exec.data = []
        service._supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec

        result = service.get_brand_dashboard("brand-001", "org-001")

        assert result["articles"]["total"] == 0
        assert result["keywords"]["total"] == 0
        assert result["projects"]["total"] == 0

    def test_multiple_projects(self, service):
        """Aggregates across multiple projects for a brand."""
        projects = [
            {"id": "proj-001", "status": "active"},
            {"id": "proj-002", "status": "active"},
        ]
        articles = [
            {"id": "art-001", "keyword": "kw1", "status": "published", "published_url": "https://x.com/1"},
            {"id": "art-002", "keyword": "kw2", "status": "draft", "published_url": None},
            {"id": "art-003", "keyword": "kw3", "status": "published", "published_url": "https://x.com/3"},
        ]
        keywords = [
            {"id": "kw-001", "status": "selected"},
            {"id": "kw-002", "status": "discovered"},
        ]

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "seo_projects":
                mock_exec = MagicMock()
                mock_exec.data = projects
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_articles":
                mock_exec = MagicMock()
                mock_exec.data = articles
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_keywords":
                mock_exec = MagicMock()
                mock_exec.data = keywords
                mock_table.select.return_value.in_.return_value.execute.return_value = mock_exec
            elif table_name == "seo_internal_links":
                mock_exec = MagicMock()
                mock_exec.data = []
                mock_table.select.return_value.in_.return_value.execute.return_value = mock_exec
            return mock_table

        service._supabase.table.side_effect = table_side_effect

        result = service.get_brand_dashboard("brand-001", "org-001")

        assert result["projects"]["total"] == 2
        assert result["projects"]["active"] == 2
        assert result["articles"]["total"] == 3
        assert result["articles"]["published"] == 2
        assert result["keywords"]["total"] == 2

    def test_brand_dashboard_with_archived_project(self, service):
        """Archived projects count in total but not in active."""
        projects = [
            {"id": "proj-001", "status": "active"},
            {"id": "proj-002", "status": "archived"},
        ]

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "seo_projects":
                mock_exec = MagicMock()
                mock_exec.data = projects
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_articles":
                mock_exec = MagicMock()
                mock_exec.data = []
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exec
            elif table_name == "seo_keywords":
                mock_exec = MagicMock()
                mock_exec.data = []
                mock_table.select.return_value.in_.return_value.execute.return_value = mock_exec
            elif table_name == "seo_internal_links":
                mock_exec = MagicMock()
                mock_exec.data = []
                mock_table.select.return_value.in_.return_value.execute.return_value = mock_exec
            return mock_table

        service._supabase.table.side_effect = table_side_effect

        result = service.get_brand_dashboard("brand-001", "org-001")

        assert result["projects"]["total"] == 2
        assert result["projects"]["active"] == 1


class TestGetBrandOrphans:
    """Brand-wide orphan report: published articles with 0 inbound links."""

    def _setup_articles(self, service, rows):
        chain = MagicMock()
        for m in ["select", "eq", "neq", "in_", "is_", "order"]:
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        service.supabase.table.return_value = chain

    def test_identifies_orphans(self, service):
        rows = [
            {"id": "a1", "keyword": "Has inbound", "published_url": "https://x/1", "project_id": "p1"},
            {"id": "a2", "keyword": "Orphan", "published_url": "https://x/2", "project_id": "p1"},
            {"id": "a3", "keyword": "Draft", "published_url": None, "project_id": "p1"},  # excluded
        ]
        self._setup_articles(service, rows)
        with patch(
            "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"
        ) as MockIL:
            MockIL.return_value.count_inbound_links.return_value = {"a1": 3}
            result = service.get_brand_orphans("brand-1", "org-1")

        assert result["published_count"] == 2  # a3 (no published_url) excluded
        assert result["orphan_count"] == 1
        assert result["orphan_pct"] == 50.0
        assert [o["article_id"] for o in result["orphans"]] == ["a2"]

    def test_no_published_returns_zero_state(self, service):
        self._setup_articles(service, [{"id": "a3", "published_url": None}])
        result = service.get_brand_orphans("brand-1", "org-1")
        assert result == {
            "published_count": 0, "orphan_count": 0, "orphan_pct": 0.0,
            "exempt_count": 0, "orphans": [],
        }

    def test_exempt_articles_not_orphans(self, service):
        """interlink_exempt articles (intentional standalones) are excluded
        from orphan counts and the published denominator, reported separately."""
        rows = [
            {"id": "a1", "keyword": "Linked", "published_url": "https://x/1", "project_id": "p1"},
            {"id": "a2", "keyword": "Standalone", "published_url": "https://x/2", "project_id": "p1", "interlink_exempt": True},
            {"id": "a3", "keyword": "Real orphan", "published_url": "https://x/3", "project_id": "p1"},
        ]
        self._setup_articles(service, rows)
        with patch(
            "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"
        ) as MockIL:
            MockIL.return_value.count_inbound_links.return_value = {"a1": 2}
            result = service.get_brand_orphans("brand-1", "org-1")

        assert result["exempt_count"] == 1
        assert result["published_count"] == 2          # exempt excluded from denominator
        assert [o["article_id"] for o in result["orphans"]] == ["a3"]  # a2 not an orphan
        assert result["orphan_pct"] == 50.0

    def test_all_linked_superuser_all_org(self, service):
        rows = [{"id": "a1", "keyword": "k", "published_url": "https://x/1", "project_id": "p1"}]
        self._setup_articles(service, rows)
        with patch(
            "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"
        ) as MockIL:
            MockIL.return_value.count_inbound_links.return_value = {"a1": 1}
            result = service.get_brand_orphans("brand-1", "all")  # 'all' must not break

        assert result["orphan_count"] == 0
        assert result["published_count"] == 1


# =============================================================================
# LINK IMPACT (§7 increment 2 — R7)
# =============================================================================

def _impact_db(articles, analytics, snapshots, auto_links):
    """Router for get_link_impact's four queries."""
    db = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        for m in ["select", "eq", "neq", "in_", "gte", "lt", "order", "limit"]:
            getattr(chain, m).return_value = chain
        data = {
            "seo_articles": articles,
            "seo_article_analytics": analytics,
            "seo_link_coverage_snapshots": snapshots,
            "seo_internal_links": auto_links,
        }.get(name, [])
        chain.execute.return_value = MagicMock(data=data)
        return chain

    db.table.side_effect = table_side_effect
    return db


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def _pos_series(aid, start_days_ago, end_days_ago, start_pos, end_pos):
    """Daily GSC rows sliding linearly from start_pos to end_pos."""
    rows = []
    total = start_days_ago - end_days_ago
    for i in range(total + 1):
        frac = i / total if total else 0
        rows.append({
            "article_id": aid,
            "date": _days_ago(start_days_ago - i),
            "average_position": start_pos + (end_pos - start_pos) * frac,
        })
    return rows


class TestGetLinkImpact:
    def _live(self, *ids):
        return [
            {"id": a, "keyword": f"kw-{a}", "status": "published",
             "published_url": f"https://x/{a}"}
            for a in ids
        ]

    def test_approximate_provenance_and_buckets(self, service):
        """No snapshots yet (cold start): link history reconstructed from AUTO
        created_at; gained-links article improved, no-gain article flat."""
        analytics = (
            _pos_series("a1", 80, 1, 18.0, 12.0)   # improved 6 positions
            + _pos_series("a2", 80, 1, 20.0, 20.0)  # flat
            + _pos_series("a3", 80, 1, 15.0, 15.5)  # slight decline
        )
        # a1 gained 2 AUTO links mid-window; a2/a3 none in-window.
        mid = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        auto = [
            {"source_article_id": "a2", "target_article_id": "a1", "created_at": mid},
            {"source_article_id": "a3", "target_article_id": "a1", "created_at": mid},
        ]
        db = _impact_db(self._live("a1", "a2", "a3"), analytics, [], auto)
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")

        assert result["stale"] is False
        assert result["insufficient_data"] is False
        by_id = {a["article_id"]: a for a in result["articles"]}
        assert by_id["a1"]["link_gain"] == 2
        assert by_id["a1"]["provenance"] == "approximate"
        assert by_id["a1"]["position_delta"] < 0          # improved
        assert by_id["a2"]["link_gain"] == 0
        assert result["buckets"]["gained_links"]["count"] == 1
        assert result["buckets"]["no_gain"]["count"] == 2
        assert result["buckets"]["gained_links"]["median_position_delta"] < 0
        assert result["measured_since"] is None

    def test_measured_provenance_when_snapshots_cover_window(self, service):
        analytics = _pos_series("a1", 80, 1, 18.0, 12.0) + _pos_series("a2", 80, 1, 20.0, 20.0) + _pos_series("a3", 80, 1, 15.0, 15.0)
        snaps = []
        for aid, start_in, end_in in [("a1", 1, 4), ("a2", 2, 2), ("a3", 1, 1)]:
            snaps.append({"article_id": aid, "captured_on": _days_ago(85), "inbound_count": start_in})
            snaps.append({"article_id": aid, "captured_on": _days_ago(2), "inbound_count": end_in})
        db = _impact_db(self._live("a1", "a2", "a3"), analytics, snaps, [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")

        by_id = {a["article_id"]: a for a in result["articles"]}
        assert by_id["a1"]["provenance"] == "measured"
        assert by_id["a1"]["link_gain"] == 3
        assert result["measured_since"] == _days_ago(85)
        assert result["data_as_of"]["snapshots"] == _days_ago(2)

    def test_mixed_provenance_snapshot_mid_window(self, service):
        """Snapshot exists only recently (began mid-window): end is measured,
        start reconstructed — provenance 'mixed'."""
        analytics = _pos_series("a1", 80, 1, 18.0, 12.0) + _pos_series("a2", 80, 1, 20.0, 20.0) + _pos_series("a3", 80, 1, 15.0, 15.0)
        snaps = [{"article_id": "a1", "captured_on": _days_ago(2), "inbound_count": 5}]
        db = _impact_db(self._live("a1", "a2", "a3"), analytics, snaps, [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")
        by_id = {a["article_id"]: a for a in result["articles"]}
        assert by_id["a1"]["provenance"] == "mixed"
        assert by_id["a1"]["links_now"] == 5

    def test_stale_gsc_gates_card(self, service):
        analytics = _pos_series("a1", 80, 30, 18.0, 12.0)  # newest row 30d old
        db = _impact_db(self._live("a1"), analytics, [], [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")
        assert result["stale"] is True

    def test_insufficient_data_under_three_articles(self, service):
        analytics = _pos_series("a1", 80, 1, 18.0, 12.0)
        db = _impact_db(self._live("a1", "a2"), analytics, [], [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")
        assert result["insufficient_data"] is True   # only a1 has position data

    def test_sparse_position_data_skipped(self, service):
        """Articles with fewer than 8 distinct GSC days can't produce an honest
        delta — excluded."""
        analytics = _pos_series("a1", 5, 1, 18.0, 12.0)  # only 5 days
        db = _impact_db(self._live("a1"), analytics, [], [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")
        assert result["articles"] == []

    def test_stale_mid_window_snapshot_not_treated_as_measured_end(self, service):
        """A snapshot last captured 30d ago can't serve as the window-END count
        (recent link gains would be silently missed) — falls back to approximate."""
        analytics = _pos_series("a1", 80, 1, 18.0, 12.0) + _pos_series("a2", 80, 1, 20.0, 20.0) + _pos_series("a3", 80, 1, 15.0, 15.0)
        snaps = [{"article_id": "a1", "captured_on": _days_ago(30), "inbound_count": 9}]
        db = _impact_db(self._live("a1", "a2", "a3"), analytics, snaps, [])
        svc = SEOAnalyticsService(supabase_client=db)
        result = svc.get_link_impact("b1", "o1")
        by_id = {a["article_id"]: a for a in result["articles"]}
        assert by_id["a1"]["provenance"] == "approximate"  # stale end rejected
        assert by_id["a1"]["links_now"] == 0               # approx, not the stale 9
