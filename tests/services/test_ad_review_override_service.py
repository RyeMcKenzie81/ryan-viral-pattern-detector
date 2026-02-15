"""
Tests for AdReviewOverrideService — Phase 4 human override operations.

Tests: validation, RPC delegation, latest-override lookup, stats aggregation.
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
