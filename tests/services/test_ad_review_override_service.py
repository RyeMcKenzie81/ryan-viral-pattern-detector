"""
Tests for AdReviewOverrideService — Phase 4 human override operations.

Tests: validation, RPC delegation, latest-override lookup, stats aggregation,
filtered ad queries, summary stats, and bulk override.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from viraltracker.services.ad_review_override_service import (
    AdReviewOverrideService,
    VALID_ACTIONS,
)


@pytest.fixture
def mock_db():
    """Create a mock Supabase client."""
    return MagicMock()


@pytest.fixture
def service(mock_db):
    """Create service with mocked DB."""
    with patch(
        "viraltracker.services.ad_review_override_service.get_supabase_client",
        return_value=mock_db,
    ):
        svc = AdReviewOverrideService()
    return svc


# ============================================================================
# VALID_ACTIONS constant
# ============================================================================

class TestValidActions:
    def test_has_three_actions(self):
        assert len(VALID_ACTIONS) == 3

    def test_contains_expected_actions(self):
        assert "override_approve" in VALID_ACTIONS
        assert "override_reject" in VALID_ACTIONS
        assert "confirm" in VALID_ACTIONS


# ============================================================================
# create_override
# ============================================================================

class TestCreateOverride:
    def test_invalid_action_raises(self, service):
        with pytest.raises(ValueError, match="Invalid action"):
            service.create_override(
                generated_ad_id="ad-1",
                org_id="org-1",
                user_id="user-1",
                action="invalid_action",
            )

    def test_calls_rpc_with_correct_params(self, service, mock_db):
        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data={"id": "override-1"})
        mock_db.rpc.return_value = mock_rpc

        result = service.create_override(
            generated_ad_id="ad-1",
            org_id="org-1",
            user_id="user-1",
            action="override_approve",
            reason="Looks good to me",
            check_overrides={"V1": {"ai_score": 6.0, "human_override": "pass"}},
        )

        mock_db.rpc.assert_called_once_with(
            "apply_ad_override",
            {
                "p_generated_ad_id": "ad-1",
                "p_org_id": "org-1",
                "p_user_id": "user-1",
                "p_action": "override_approve",
                "p_reason": "Looks good to me",
                "p_check_overrides": {"V1": {"ai_score": 6.0, "human_override": "pass"}},
            },
        )
        assert result == {"id": "override-1"}

    def test_override_reject(self, service, mock_db):
        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data={"id": "override-2"})
        mock_db.rpc.return_value = mock_rpc

        result = service.create_override(
            generated_ad_id="ad-1",
            org_id="org-1",
            user_id="user-1",
            action="override_reject",
        )
        assert mock_db.rpc.call_args[0][1]["p_action"] == "override_reject"

    def test_confirm_action(self, service, mock_db):
        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data={"id": "override-3"})
        mock_db.rpc.return_value = mock_rpc

        result = service.create_override(
            generated_ad_id="ad-1",
            org_id="org-1",
            user_id="user-1",
            action="confirm",
        )
        assert mock_db.rpc.call_args[0][1]["p_action"] == "confirm"

    def test_none_reason_passed_through(self, service, mock_db):
        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data={})
        mock_db.rpc.return_value = mock_rpc

        service.create_override(
            generated_ad_id="ad-1",
            org_id="org-1",
            user_id="user-1",
            action="confirm",
        )
        assert mock_db.rpc.call_args[0][1]["p_reason"] is None
        assert mock_db.rpc.call_args[0][1]["p_check_overrides"] is None


# ============================================================================
# get_latest_override
# ============================================================================

class TestGetLatestOverride:
    def test_returns_override_when_exists(self, service, mock_db):
        override_row = {
            "id": "ov-1",
            "generated_ad_id": "ad-1",
            "override_action": "override_approve",
            "previous_status": "rejected",
            "superseded_by": None,
        }
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[override_row])
        mock_db.table.return_value = mock_chain

        result = service.get_latest_override("ad-1")
        assert result == override_row

    def test_returns_none_when_no_override(self, service, mock_db):
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value = mock_chain

        result = service.get_latest_override("ad-nonexistent")
        assert result is None

    def test_filters_by_superseded_null(self, service, mock_db):
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value = mock_chain

        service.get_latest_override("ad-1")
        mock_chain.is_.assert_called_once_with("superseded_by", "null")


# ============================================================================
# get_override_stats
# ============================================================================

class TestGetOverrideStats:
    def test_empty_stats(self, service, mock_db):
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.gte.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value = mock_chain

        stats = service.get_override_stats("org-1")
        assert stats == {"total": 0, "override_approve": 0, "override_reject": 0, "confirm": 0}

    def test_counts_actions_correctly(self, service, mock_db):
        rows = [
            {"override_action": "override_approve"},
            {"override_action": "override_approve"},
            {"override_action": "override_reject"},
            {"override_action": "confirm"},
            {"override_action": "confirm"},
            {"override_action": "confirm"},
        ]
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.gte.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=rows)
        mock_db.table.return_value = mock_chain

        stats = service.get_override_stats("org-1")
        assert stats["total"] == 6
        assert stats["override_approve"] == 2
        assert stats["override_reject"] == 1
        assert stats["confirm"] == 3

    def test_custom_days_window(self, service, mock_db):
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.gte.return_value = mock_chain
        mock_chain.is_.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value = mock_chain

        service.get_override_stats("org-1", days=7)
        # Verify gte was called (date filter applied)
        mock_chain.gte.assert_called_once()


# ============================================================================
# get_ads_for_run
# ============================================================================

class TestGetAdsForRun:
    def test_returns_ads_list(self, service, mock_db):
        ads = [
            {"id": "ad-1", "prompt_index": 1, "final_status": "approved"},
            {"id": "ad-2", "prompt_index": 2, "final_status": "rejected"},
        ]
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=ads)
        mock_db.table.return_value = mock_chain

        result = service.get_ads_for_run("run-1")
        assert len(result) == 2
        assert result[0]["prompt_index"] == 1

    def test_returns_empty_list_when_no_ads(self, service, mock_db):
        mock_chain = MagicMock()
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_chain.execute.return_value = MagicMock(data=None)
        mock_db.table.return_value = mock_chain

        result = service.get_ads_for_run("run-empty")
        assert result == []


# ============================================================================
# get_ads_filtered
# ============================================================================

class TestGetAdsFiltered:
    def _mock_chain(self, mock_db, data=None):
        """Set up a fluent chain mock for get_ads_filtered."""
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=data or [])
        mock_db.table.return_value = chain
        return chain

    def test_returns_ads_list(self, service, mock_db):
        ads = [
            {"id": "ad-1", "final_status": "approved", "ad_runs": {"template_id": "t1"}},
            {"id": "ad-2", "final_status": "rejected", "ad_runs": {"template_id": "t1"}},
        ]
        self._mock_chain(mock_db, data=ads)

        result = service.get_ads_filtered("org-1")
        assert len(result) == 2

    def test_status_filter_applied(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered("org-1", status_filter=["approved", "flagged"])
        chain.in_.assert_called_once_with("final_status", ["approved", "flagged"])

    def test_date_range_applied(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered(
            "org-1",
            date_from="2026-02-01",
            date_to="2026-02-14",
        )
        chain.gte.assert_called_once_with("created_at", "2026-02-01")
        chain.lte.assert_called_once_with("created_at", "2026-02-14")

    def test_sort_newest(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered("org-1", sort_by="newest")
        chain.order.assert_called_once_with("created_at", desc=True)

    def test_sort_oldest(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered("org-1", sort_by="oldest")
        chain.order.assert_called_once_with("created_at", desc=False)

    def test_pagination(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered("org-1", limit=20, offset=40)
        chain.range.assert_called_once_with(40, 59)

    def test_returns_empty_when_no_data(self, service, mock_db):
        self._mock_chain(mock_db, data=None)

        result = service.get_ads_filtered("org-1")
        assert result == []

    def test_ad_run_id_filter(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_ads_filtered("org-1", ad_run_id="run-123")
        # eq called for both org_id and ad_run_id
        eq_calls = [call[0] for call in chain.eq.call_args_list]
        assert ("ad_run_id", "run-123") in eq_calls


# ============================================================================
# get_summary_stats
# ============================================================================

class TestGetSummaryStats:
    def _mock_chain(self, mock_db, data=None):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.execute.return_value = MagicMock(data=data or [])
        mock_db.table.return_value = chain
        return chain

    def test_empty_stats(self, service, mock_db):
        self._mock_chain(mock_db, data=[])

        result = service.get_summary_stats("org-1")
        assert result["total"] == 0
        assert result["approved"] == 0
        assert result["override_rate"] == 0.0

    def test_counts_statuses(self, service, mock_db):
        rows = [
            {"final_status": "approved", "override_status": None, "ad_runs": {}},
            {"final_status": "approved", "override_status": None, "ad_runs": {}},
            {"final_status": "rejected", "override_status": None, "ad_runs": {}},
            {"final_status": "flagged", "override_status": "override_approved", "ad_runs": {}},
            {"final_status": "review_failed", "override_status": None, "ad_runs": {}},
        ]
        self._mock_chain(mock_db, data=rows)

        result = service.get_summary_stats("org-1")
        assert result["total"] == 5
        assert result["approved"] == 2
        assert result["rejected"] == 1
        assert result["flagged"] == 1
        assert result["review_failed"] == 1
        assert result["overridden"] == 1
        assert result["override_rate"] == 20.0

    def test_product_filter(self, service, mock_db):
        chain = self._mock_chain(mock_db)

        service.get_summary_stats("org-1", product_id="prod-1")
        eq_calls = [call[0] for call in chain.eq.call_args_list]
        assert ("ad_runs.product_id", "prod-1") in eq_calls


# ============================================================================
# bulk_override
# ============================================================================

class TestBulkOverride:
    def test_invalid_action_raises(self, service):
        with pytest.raises(ValueError, match="Invalid action"):
            service.bulk_override(
                generated_ad_ids=["ad-1"],
                org_id="org-1",
                user_id="user-1",
                action="invalid",
            )

    def test_empty_list_returns_zero(self, service):
        result = service.bulk_override(
            generated_ad_ids=[],
            org_id="org-1",
            user_id="user-1",
            action="override_approve",
        )
        assert result == {"success": 0, "failed": 0}

    def test_applies_to_all_ads(self, service, mock_db):
        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data={"id": "ov-1"})
        mock_db.rpc.return_value = mock_rpc

        result = service.bulk_override(
            generated_ad_ids=["ad-1", "ad-2", "ad-3"],
            org_id="org-1",
            user_id="user-1",
            action="override_approve",
            reason="Bulk approve",
        )
        assert result["success"] == 3
        assert result["failed"] == 0
        assert mock_db.rpc.call_count == 3

    def test_counts_failures(self, service, mock_db):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("RPC failed")
            mock_result = MagicMock()
            mock_result.execute.return_value = MagicMock(data={})
            return mock_result

        mock_db.rpc.side_effect = side_effect

        result = service.bulk_override(
            generated_ad_ids=["ad-1", "ad-2", "ad-3"],
            org_id="org-1",
            user_id="user-1",
            action="override_reject",
        )
        assert result["success"] == 2
        assert result["failed"] == 1
