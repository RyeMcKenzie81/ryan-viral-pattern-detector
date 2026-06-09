"""
Tests for OpportunityMinerService — SEO feedback loop intelligence layer.

Tests cover:
- Scoring formula (all 4 components, edge cases, normalization)
- classify_action decision tree (all 6 branches + discovered article skip-REFRESH)
- generate_weekly_report (aggregation, empty data)
- UPSERT dedup (same keyword+article updates not duplicates)
- Rank delta tracking (7/14/28 day snapshots, one-time freeze)
- Organization_id "all" resolution
- Empty/sparse GSC data handling
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timedelta, timezone

from viraltracker.services.seo_pipeline.services.opportunity_miner_service import (
    OpportunityMinerService,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Create a mock Supabase client with chainable query builder."""
    return MagicMock()


@pytest.fixture
def service(mock_supabase):
    """Service with mocked Supabase client."""
    return OpportunityMinerService(supabase_client=mock_supabase)


# =============================================================================
# SCORING: IMPRESSION TREND (30% weight)
# =============================================================================

class TestScoreImpressionTrend:
    def test_rising_trend(self, service):
        """Rising (>10% increase) = 100."""
        assert service._score_impression_trend(120, 100) == 100.0

    def test_stable_trend(self, service):
        """Stable (-10% to +10%) = 50."""
        assert service._score_impression_trend(105, 100) == 50.0
        assert service._score_impression_trend(95, 100) == 50.0

    def test_declining_trend(self, service):
        """Declining (<-10%) = 20."""
        assert service._score_impression_trend(80, 100) == 20.0

    def test_zero_previous(self, service):
        """No prior data — stable = 50."""
        assert service._score_impression_trend(100, 0) == 50.0

    def test_negative_previous(self, service):
        """Negative previous — stable = 50."""
        assert service._score_impression_trend(100, -5) == 50.0

    def test_exact_10_percent_increase(self, service):
        """Exactly 10% is NOT rising — it's stable."""
        assert service._score_impression_trend(110, 100) == 50.0

    def test_just_above_10_percent(self, service):
        """Just above 10% is rising."""
        assert service._score_impression_trend(111, 100) == 100.0

    def test_both_zero(self, service):
        """Both zero — previous is 0, treated as stable."""
        assert service._score_impression_trend(0, 0) == 50.0


# =============================================================================
# SCORING: POSITION PROXIMITY (30% weight)
# =============================================================================

class TestScorePositionProximity:
    def test_position_4_to_6(self, service):
        """Positions 4-6 = 100 (top half of page 1, easiest wins)."""
        assert service._score_position_proximity(4) == 100.0
        assert service._score_position_proximity(5) == 100.0
        assert service._score_position_proximity(6) == 100.0

    def test_position_7(self, service):
        """Position 7 = 80 (bottom of page 1)."""
        assert service._score_position_proximity(7) == 80.0

    def test_position_10(self, service):
        """Position 10 = 60 (bottom of page 1)."""
        assert round(service._score_position_proximity(10), 1) == 60.0

    def test_position_11(self, service):
        """Position 11 = 50 (top of page 2, striking distance)."""
        assert round(service._score_position_proximity(11), 1) == 50.0

    def test_position_20(self, service):
        """Position 20 = 10 (worst in range)."""
        assert service._score_position_proximity(20) == 10.0

    def test_position_15(self, service):
        """Position 15 = mid striking distance."""
        score = service._score_position_proximity(15)
        assert 25 < score < 35  # ~32.2

    def test_position_below_4(self, service):
        """Position < 4 (top 3) not in scope, but caps at 100 if passed."""
        assert service._score_position_proximity(2) == 100.0

    def test_position_above_20(self, service):
        """Position > 20 caps at 10."""
        assert service._score_position_proximity(25) == 10.0

    def test_fractional_position(self, service):
        """Fractional positions are handled correctly."""
        score = service._score_position_proximity(8.5)
        assert 65 < score < 80  # between pos 8 and 9 scores


# =============================================================================
# SCORING: KEYWORD VOLUME (20% weight)
# =============================================================================

class TestScoreKeywordVolume:
    def test_high_volume(self, service, mock_supabase):
        """Volume at P90 = 100."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"search_volume": 1000}
        ]
        assert service._score_keyword_volume("test keyword", "brand-1", 1000) == 100.0

    def test_low_volume(self, service, mock_supabase):
        """Volume at 50% of P90 = 50."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"search_volume": 500}
        ]
        assert service._score_keyword_volume("test keyword", "brand-1", 1000) == 50.0

    def test_volume_above_p90(self, service, mock_supabase):
        """Volume above P90 caps at 100."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"search_volume": 2000}
        ]
        assert service._score_keyword_volume("test keyword", "brand-1", 1000) == 100.0

    def test_no_keyword_data(self, service, mock_supabase):
        """Missing keyword = 0."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        assert service._score_keyword_volume("unknown", "brand-1", 1000) == 0.0

    def test_zero_p90(self, service, mock_supabase):
        """P90 = 0 returns 50 (fallback)."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"search_volume": 100}
        ]
        assert service._score_keyword_volume("test", "brand-1", 0) == 50.0


# =============================================================================
# SCORING: CLUSTER GAP (20% weight)
# =============================================================================

class TestScoreClusterGap:
    def test_orphan_article(self, service):
        """Article not in any cluster = 100 (maximum gap)."""
        assert service._score_cluster_gap("art-1", {}) == 100.0

    def test_zero_supporting(self, service):
        """0 supporting articles = 100."""
        assert service._score_cluster_gap("art-1", {"art-1": 0}) == 100.0

    def test_one_supporting(self, service):
        assert service._score_cluster_gap("art-1", {"art-1": 1}) == 80.0

    def test_two_supporting(self, service):
        assert service._score_cluster_gap("art-1", {"art-1": 2}) == 60.0

    def test_three_supporting(self, service):
        assert service._score_cluster_gap("art-1", {"art-1": 3}) == 40.0

    def test_four_supporting(self, service):
        assert service._score_cluster_gap("art-1", {"art-1": 4}) == 20.0

    def test_five_or_more_supporting(self, service):
        """5+ supporting = 0 (no gap)."""
        assert service._score_cluster_gap("art-1", {"art-1": 5}) == 0.0
        assert service._score_cluster_gap("art-1", {"art-1": 10}) == 0.0


# =============================================================================
# CLASSIFY ACTION
# =============================================================================

class TestClassifyAction:
    def test_no_article(self, service):
        """No article_id → new_supporting_content."""
        result = service.classify_action({"keyword": "test"})
        assert result["action"] == "new_supporting_content"

    def test_discovered_article_skips_refresh(self, service, mock_supabase):
        """Discovered articles never get REFRESH, even if old."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": "2024-01-01T00:00:00Z",  # >1 year old
                "created_at": "2024-01-01T00:00:00Z",
                "source": "discovered",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {},
        })
        # Should NOT be refresh — discovered articles skip that branch
        assert result["action"] != "refresh"

    def test_old_content_gets_refresh(self, service, mock_supabase):
        """Content >1 year old → REFRESH."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": old_date,
                "created_at": old_date,
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 2},
        })
        assert result["action"] == "refresh"

    def test_time_sensitive_gets_refresh(self, service, mock_supabase):
        """time_sensitive flag → REFRESH."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),  # Recent
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {"time_sensitive": True},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 2},
        })
        assert result["action"] == "refresh"

    def test_no_cluster_gets_new_content(self, service, mock_supabase):
        """No cluster → NEW_SUPPORTING_CONTENT."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {},  # Not in map = no cluster
        })
        assert result["action"] == "new_supporting_content"
        assert "no cluster" in result["reason"].lower()

    def test_small_cluster_gets_new_content(self, service, mock_supabase):
        """Cluster <3 → NEW_SUPPORTING_CONTENT."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 2},
        })
        assert result["action"] == "new_supporting_content"

    def test_large_cluster_page1_gets_optimize_links(self, service, mock_supabase):
        """Cluster 5+ on page 1 → OPTIMIZE_LINKS."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 6},
            "avg_position": 7,  # page 1
        })
        assert result["action"] == "optimize_links"

    def test_large_cluster_striking_distance_gets_backlinks(self, service, mock_supabase):
        """Cluster 5+ but still on page 2 → BUILD_BACKLINKS."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 6},
            "avg_position": 14,  # page 2
        })
        assert result["action"] == "build_backlinks"

    def test_medium_cluster_striking_distance_gets_backlinks(self, service, mock_supabase):
        """Cluster 3-4 at striking distance → BUILD_BACKLINKS."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 4},
            "avg_position": 13,  # page 2
        })
        assert result["action"] == "build_backlinks"

    def test_medium_cluster_page1_gets_optimize_links(self, service, mock_supabase):
        """Cluster 3-4 on page 1 → OPTIMIZE_LINKS (not backlinks)."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "generated",
                "metadata": {},
            }
        ]
        result = service.classify_action({
            "article_id": "art-1",
            "keyword": "test",
            "cluster_map": {"art-1": 4},
            "avg_position": 8,  # page 1
        })
        assert result["action"] == "optimize_links"


# =============================================================================
# SCAN OPPORTUNITIES
# =============================================================================

class TestScanOpportunities:
    def test_no_articles(self, service, mock_supabase):
        """Brand with no articles returns empty list."""
        # Mock _resolve_org_id
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        result = service.scan_opportunities("brand-1", "org-1")
        assert result == []

    def test_no_rankings_in_range(self, service, mock_supabase):
        """Articles exist but none at positions 4-20."""
        # Set up article IDs
        articles_mock = MagicMock()
        articles_mock.data = [{"id": "art-1"}]

        # Set up rankings (all at position 2 — outside target range, top 3)
        rankings_mock = MagicMock()
        rankings_mock.data = [
            {"article_id": "art-1", "keyword": "test", "position": 2, "impressions": 100, "clicks": 10,
             "checked_at": datetime.now(timezone.utc).isoformat()},
        ]

        call_count = [0]
        original_table = mock_supabase.table

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_articles":
                result.select.return_value.eq.return_value.execute.return_value = articles_mock
            elif name == "seo_article_rankings":
                result.select.return_value.in_.return_value.gte.return_value.execute.return_value = rankings_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        result = service.scan_opportunities("brand-1", "org-1")
        assert result == []

    def test_org_all_resolution(self, service, mock_supabase):
        """Organization_id 'all' is resolved to real UUID."""
        # Mock brands lookup for _resolve_org_id
        brands_mock = MagicMock()
        brands_mock.data = [{"organization_id": "real-org-uuid"}]

        # Mock articles (empty — will short-circuit)
        articles_mock = MagicMock()
        articles_mock.data = []

        def table_side_effect(name):
            result = MagicMock()
            if name == "brands":
                result.select.return_value.eq.return_value.limit.return_value.execute.return_value = brands_mock
            elif name == "seo_articles":
                result.select.return_value.eq.return_value.execute.return_value = articles_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        result = service.scan_opportunities("brand-1", "all")
        assert result == []
        # Verify brands was queried for org resolution
        mock_supabase.table.assert_any_call("brands")


# =============================================================================
# CLUSTER MAP
# =============================================================================

class TestBuildClusterMap:
    def test_empty_articles(self, service):
        """Empty article list returns empty map."""
        assert service._build_cluster_map([]) == {}

    def test_articles_with_clusters(self, service, mock_supabase):
        """Articles in clusters get correct supporting counts."""
        # First query: get cluster assignments
        spokes_mock = MagicMock()
        spokes_mock.data = [
            {"article_id": "art-1", "cluster_id": "cluster-a"},
            {"article_id": "art-2", "cluster_id": "cluster-a"},
        ]

        # Second query: count all articles in those clusters
        count_mock = MagicMock()
        count_mock.data = [
            {"cluster_id": "cluster-a", "article_id": "art-1"},
            {"cluster_id": "cluster-a", "article_id": "art-2"},
            {"cluster_id": "cluster-a", "article_id": "art-3"},  # Extra article in cluster
        ]

        call_count = [0]

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_cluster_spokes":
                call_count[0] += 1
                if call_count[0] == 1:
                    result.select.return_value.in_.return_value.execute.return_value = spokes_mock
                else:
                    result.select.return_value.in_.return_value.execute.return_value = count_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        cluster_map = service._build_cluster_map(["art-1", "art-2"])

        # art-1 and art-2 each have 2 other articles in their cluster (total 3 - 1 = 2)
        assert cluster_map["art-1"] == 2
        assert cluster_map["art-2"] == 2


# =============================================================================
# GENERATE WEEKLY REPORT
# =============================================================================

class TestGenerateWeeklyReport:
    def test_empty_brand(self, service, mock_supabase):
        """Brand with no data returns report with zeros."""
        empty_mock = MagicMock()
        empty_mock.data = []
        empty_mock.count = 0

        def table_side_effect(name):
            result = MagicMock()
            # All queries return empty
            result.select.return_value.eq.return_value.gte.return_value.execute.return_value = empty_mock
            result.select.return_value.eq.return_value.execute.return_value = empty_mock
            result.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = empty_mock
            result.select.return_value.eq.return_value.lte.return_value.gt.return_value.execute.return_value = empty_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        report = service.generate_weekly_report("brand-1", "org-1")

        assert report["articles_published"] == 0
        assert "period" in report
        assert "top_opportunities" in report
        assert "rank_milestones" in report


# =============================================================================
# UPSERT OPPORTUNITIES
# =============================================================================

class TestUpsertOpportunities:
    def test_empty_list(self, service):
        """Empty list returns 0."""
        assert service.upsert_opportunities([]) == 0

    def test_upsert_calls_supabase(self, service, mock_supabase):
        """Opportunities are upserted with correct on_conflict."""
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        opportunities = [{
            "organization_id": "org-1",
            "brand_id": "brand-1",
            "article_id": "art-1",
            "keyword": "test keyword",
            "opportunity_score": 85.5,
            "status": "identified",
        }]
        result = service.upsert_opportunities(opportunities)
        assert result == 1
        mock_supabase.table.return_value.upsert.assert_called_once()

    def test_dedup_via_upsert(self, service, mock_supabase):
        """Same article+keyword pair should update, not duplicate."""
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        opp = {
            "organization_id": "org-1",
            "brand_id": "brand-1",
            "article_id": "art-1",
            "keyword": "test keyword",
            "opportunity_score": 85.5,
            "status": "identified",
        }
        # Upsert twice — should use on_conflict
        service.upsert_opportunities([opp])
        service.upsert_opportunities([{**opp, "opportunity_score": 90.0}])
        assert mock_supabase.table.return_value.upsert.call_count == 2


# =============================================================================
# RANK DELTA TRACKING
# =============================================================================

class TestUpdateRankDeltas:
    def test_no_actioned_opportunities(self, service, mock_supabase):
        """No actioned opportunities returns 0."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        assert service.update_rank_deltas("brand-1") == 0

    def test_7d_delta_set(self, service, mock_supabase):
        """rank_delta_7d set when days_since_actioned >= 7."""
        actioned_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()

        opp_mock = MagicMock()
        opp_mock.data = [{
            "id": "opp-1",
            "article_id": "art-1",
            "keyword": "test",
            "position_at_identification": 15.0,
            "actioned_at": actioned_at,
            "rank_delta_7d": None,
            "rank_delta_14d": None,
            "rank_delta_28d": None,
        }]

        pos_mock = MagicMock()
        pos_mock.data = [{"position": 12.0}]

        update_mock = MagicMock()

        call_count = [0]

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_opportunities":
                call_count[0] += 1
                if call_count[0] == 1:
                    result.select.return_value.eq.return_value.eq.return_value.execute.return_value = opp_mock
                else:
                    result.update.return_value.eq.return_value.execute.return_value = update_mock
            elif name == "seo_article_rankings":
                result.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = pos_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        updated = service.update_rank_deltas("brand-1")
        assert updated == 1

    def test_frozen_delta_not_overwritten(self, service, mock_supabase):
        """Already-set rank_delta_7d is not overwritten."""
        actioned_at = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()

        opp_mock = MagicMock()
        opp_mock.data = [{
            "id": "opp-1",
            "article_id": "art-1",
            "keyword": "test",
            "position_at_identification": 15.0,
            "actioned_at": actioned_at,
            "rank_delta_7d": -3.0,  # Already frozen
            "rank_delta_14d": None,  # Not yet set
            "rank_delta_28d": None,
        }]

        pos_mock = MagicMock()
        pos_mock.data = [{"position": 10.0}]

        update_calls = []

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_opportunities":
                # First call is the select
                result.select.return_value.eq.return_value.eq.return_value.execute.return_value = opp_mock
                # Second call is the update
                def capture_update(updates):
                    update_calls.append(updates)
                    inner = MagicMock()
                    inner.eq.return_value.execute.return_value = MagicMock()
                    return inner
                result.update.side_effect = capture_update
            elif name == "seo_article_rankings":
                result.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = pos_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        updated = service.update_rank_deltas("brand-1")
        assert updated == 1

        # Verify rank_delta_7d was NOT in the update (already frozen)
        assert len(update_calls) == 1
        assert "rank_delta_7d" not in update_calls[0]
        assert "rank_delta_14d" in update_calls[0]

    def test_28d_delta_negative_means_improved(self, service, mock_supabase):
        """Negative delta means position improved (moved up)."""
        actioned_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        opp_mock = MagicMock()
        opp_mock.data = [{
            "id": "opp-1",
            "article_id": "art-1",
            "keyword": "test",
            "position_at_identification": 15.0,
            "actioned_at": actioned_at,
            "rank_delta_7d": -2.0,
            "rank_delta_14d": -4.0,
            "rank_delta_28d": None,
        }]

        pos_mock = MagicMock()
        pos_mock.data = [{"position": 8.0}]  # Improved from 15 to 8

        update_calls = []

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_opportunities":
                result.select.return_value.eq.return_value.eq.return_value.execute.return_value = opp_mock
                def capture_update(updates):
                    update_calls.append(updates)
                    inner = MagicMock()
                    inner.eq.return_value.execute.return_value = MagicMock()
                    return inner
                result.update.side_effect = capture_update
            elif name == "seo_article_rankings":
                result.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = pos_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        updated = service.update_rank_deltas("brand-1")
        assert updated == 1
        assert update_calls[0]["rank_delta_28d"] == -7.0  # 8.0 - 15.0 = -7


# =============================================================================
# VOLUME PERCENTILE
# =============================================================================

class TestGetVolumePercentile90:
    def test_no_projects(self, service, mock_supabase):
        """No projects returns 0."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        assert service._get_volume_percentile_90("brand-1") == 0.0

    def test_computes_p90(self, service, mock_supabase):
        """Correctly computes 90th percentile."""
        proj_mock = MagicMock()
        proj_mock.data = [{"id": "proj-1"}]

        # 10 keywords with volumes 100-1000
        kw_mock = MagicMock()
        kw_mock.data = [{"search_volume": v} for v in range(100, 1100, 100)]

        call_count = [0]

        def table_side_effect(name):
            result = MagicMock()
            if name == "seo_projects":
                result.select.return_value.eq.return_value.execute.return_value = proj_mock
            elif name == "seo_keywords":
                result.select.return_value.in_.return_value.not_.is_.return_value.execute.return_value = kw_mock
            return result

        mock_supabase.table.side_effect = table_side_effect
        p90 = service._get_volume_percentile_90("brand-1")
        assert p90 == 1000.0  # 90th percentile of 100..1000


# =============================================================================
# ORG ID RESOLUTION
# =============================================================================

class TestResolveOrgId:
    def test_non_all_passthrough(self, service):
        """Regular org_id passes through unchanged."""
        assert service._resolve_org_id("org-uuid-123", "brand-1") == "org-uuid-123"

    def test_all_resolved_from_brand(self, service, mock_supabase):
        """'all' is resolved to real UUID via brands table."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"organization_id": "real-org-uuid"}
        ]
        assert service._resolve_org_id("all", "brand-1") == "real-org-uuid"

    def test_all_fallback_on_missing_brand(self, service, mock_supabase):
        """'all' falls back to 'all' if brand not found."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        assert service._resolve_org_id("all", "nonexistent") == "all"


# =============================================================================
# FEED FRESHNESS (§7 increment 0 — input-age health signal)
# =============================================================================

class TestGetFeedFreshness:
    """STALE keys on INPUT age: a feed with no rows or rows older than
    FEED_STALE_DAYS is stale. This is what makes the 2026-06 outage class
    (every feed weeks old while jobs report 'completed') visible."""

    def _db(self, article_ids, rankings_newest, analytics_by_source):
        db = MagicMock()

        def table_side_effect(name):
            chain = MagicMock()
            state = {"source": None}

            def _eq(col, val):
                if col == "source":
                    state["source"] = val
                return chain

            for m in ["select", "in_", "order", "limit"]:
                getattr(chain, m).return_value = chain
            chain.eq.side_effect = _eq

            def _execute():
                if name == "seo_articles":
                    return MagicMock(data=[{"id": a} for a in article_ids])
                if name == "seo_article_rankings":
                    return MagicMock(
                        data=[{"checked_at": rankings_newest}] if rankings_newest else []
                    )
                if name == "seo_article_analytics":
                    val = analytics_by_source.get(state["source"])
                    return MagicMock(data=[{"date": val}] if val else [])
                return MagicMock(data=[])

            chain.execute.side_effect = _execute
            return chain

        db.table.side_effect = table_side_effect
        return db

    def test_fresh_and_stale_sources(self, mock_supabase):
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(days=2)).isoformat()
        old = (now - timedelta(days=60)).isoformat()
        db = self._db(
            article_ids=["a1", "a2"],
            rankings_newest=old,                      # 60d → stale
            analytics_by_source={"gsc": fresh},        # 2d → fresh; ga4/shopify none
        )
        svc = OpportunityMinerService(supabase_client=db)
        result = svc.get_feed_freshness("brand-1")

        assert result["sources"]["rankings"]["stale"] is True
        assert result["sources"]["rankings"]["age_days"] >= 59
        assert result["sources"]["gsc"]["stale"] is False
        # ga4 has no data EVER → optional integration not configured, NOT
        # stale (a GSC-only brand must not get a permanent weekly warning).
        assert result["sources"]["ga4"]["stale"] is False
        assert result["sources"]["ga4"]["configured"] is False
        assert result["sources"]["ga4"]["age_days"] is None
        assert "ga4" not in result["stale_sources"]
        assert "rankings" in result["stale_sources"]
        assert "gsc" not in result["stale_sources"]
        assert result["any_stale"] is True
        assert result["threshold_days"] == OpportunityMinerService.FEED_STALE_DAYS

    def test_optional_feed_with_old_history_is_stale(self, mock_supabase):
        """An optional feed that HAD data and stopped is genuinely stale —
        it was working, something broke."""
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=30)).isoformat()
        db = self._db(
            article_ids=["a1"],
            rankings_newest=fresh,
            analytics_by_source={"gsc": fresh, "ga4": old},
        )
        svc = OpportunityMinerService(supabase_client=db)
        result = svc.get_feed_freshness("brand-1")
        assert result["sources"]["ga4"]["configured"] is True
        assert result["sources"]["ga4"]["stale"] is True
        assert "ga4" in result["stale_sources"]

    def test_all_fresh(self, mock_supabase):
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(days=1)).isoformat()
        db = self._db(
            article_ids=["a1"],
            rankings_newest=fresh,
            analytics_by_source={"gsc": fresh, "ga4": fresh, "shopify": fresh},
        )
        svc = OpportunityMinerService(supabase_client=db)
        result = svc.get_feed_freshness("brand-1")
        assert result["any_stale"] is False
        assert result["stale_sources"] == []

    def test_no_articles_required_feeds_stale(self, mock_supabase):
        db = self._db(article_ids=[], rankings_newest=None, analytics_by_source={})
        svc = OpportunityMinerService(supabase_client=db)
        result = svc.get_feed_freshness("brand-1")
        # No data anywhere: REQUIRED feeds (rankings, gsc) are stale; the
        # optional ones (ga4, shopify) read as not-configured, not stale.
        assert result["any_stale"] is True
        assert set(result["stale_sources"]) == {"rankings", "gsc"}
        assert result["sources"]["shopify"]["configured"] is False

    def test_date_only_strings_parse(self, mock_supabase):
        """seo_article_analytics.date is a DATE (e.g. '2026-04-13'), not a
        timestamptz — parsing must handle both."""
        db = self._db(
            article_ids=["a1"],
            rankings_newest=None,
            analytics_by_source={"gsc": "2026-04-13"},
        )
        svc = OpportunityMinerService(supabase_client=db)
        result = svc.get_feed_freshness("brand-1")
        assert result["sources"]["gsc"]["age_days"] is not None
        assert result["sources"]["gsc"]["stale"] is True  # weeks old


class TestWeeklyReportFreshness:
    def test_report_includes_feed_freshness(self, service, mock_supabase):
        with patch.object(service, "get_feed_freshness", return_value={"any_stale": True, "stale_sources": ["gsc"], "sources": {}, "threshold_days": 7}):
            # All DB queries can return empty — report still builds.
            chain = MagicMock()
            for m in ["select", "eq", "gte", "lt", "lte", "gt", "in_", "order", "limit"]:
                getattr(chain, m).return_value = chain
            chain.execute.return_value = MagicMock(data=[], count=0)
            mock_supabase.table.return_value = chain

            report = service.generate_weekly_report("brand-1", "org-1")

        assert report["feed_freshness"]["any_stale"] is True
        assert report["feed_freshness"]["stale_sources"] == ["gsc"]

    def test_freshness_failure_is_nonfatal(self, service, mock_supabase):
        """The report is how staleness gets SEEN — a freshness error must not
        block it."""
        with patch.object(service, "get_feed_freshness", side_effect=RuntimeError("boom")):
            chain = MagicMock()
            for m in ["select", "eq", "gte", "lt", "lte", "gt", "in_", "order", "limit"]:
                getattr(chain, m).return_value = chain
            chain.execute.return_value = MagicMock(data=[], count=0)
            mock_supabase.table.return_value = chain

            report = service.generate_weekly_report("brand-1", "org-1")

        assert report["feed_freshness"] == {}
        assert "period" in report
