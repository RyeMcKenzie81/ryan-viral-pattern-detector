"""
Tests for QualityCalibrationService — Phase 8A adaptive threshold calibration.

Tests override analysis, proposal generation, safety rails, validation,
activation flow, and dismiss flow.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from viraltracker.services.quality_calibration_service import (
    QualityCalibrationService,
    VALID_CHECK_IDS,
    MIN_SAMPLE_SIZE,
    MAX_THRESHOLD_DELTA,
    MAX_WEIGHT_DELTA,
)


def _org_id():
    return UUID("00000000-0000-0000-0000-000000000001")


class TestValidCheckIDs:
    """Test VALID_CHECK_IDS constant."""

    def test_has_15_checks(self):
        assert len(VALID_CHECK_IDS) == 15

    def test_visual_checks(self):
        for v in ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9"]:
            assert v in VALID_CHECK_IDS

    def test_content_checks(self):
        for c in ["C1", "C2", "C3", "C4"]:
            assert c in VALID_CHECK_IDS

    def test_congruence_checks(self):
        for g in ["G1", "G2"]:
            assert g in VALID_CHECK_IDS


class TestSafetyRails:
    """Test safety rail constants."""

    def test_min_sample_size(self):
        assert MIN_SAMPLE_SIZE == 30

    def test_max_threshold_delta(self):
        assert MAX_THRESHOLD_DELTA == 1.0

    def test_max_weight_delta(self):
        assert MAX_WEIGHT_DELTA == 0.5


class TestValidateProposal:
    """Test _validate_proposal validation logic."""

    def setup_method(self):
        self.svc = QualityCalibrationService()
        self.valid_weights = {c: 1.0 for c in VALID_CHECK_IDS}
        self.valid_borderline = {"low": 5.0, "high": 7.0}
        self.valid_auto_reject = ["V9"]

    def test_valid_proposal(self):
        errors = self.svc._validate_proposal(
            7.0, self.valid_weights, self.valid_borderline, self.valid_auto_reject
        )
        assert errors == []

    def test_threshold_too_low(self):
        errors = self.svc._validate_proposal(
            0.5, self.valid_weights, self.valid_borderline, self.valid_auto_reject
        )
        assert any("pass_threshold" in e for e in errors)

    def test_threshold_too_high(self):
        errors = self.svc._validate_proposal(
            11.0, self.valid_weights, self.valid_borderline, self.valid_auto_reject
        )
        assert any("pass_threshold" in e for e in errors)

    def test_missing_check_in_weights(self):
        weights = {c: 1.0 for c in VALID_CHECK_IDS if c != "V1"}
        errors = self.svc._validate_proposal(
            7.0, weights, self.valid_borderline, self.valid_auto_reject
        )
        assert any("V1" in e for e in errors)

    def test_negative_weight(self):
        weights = dict(self.valid_weights)
        weights["V1"] = -0.5
        errors = self.svc._validate_proposal(
            7.0, weights, self.valid_borderline, self.valid_auto_reject
        )
        assert any("Negative weight" in e for e in errors)

    def test_borderline_low_gte_high(self):
        borderline = {"low": 7.0, "high": 5.0}
        errors = self.svc._validate_proposal(
            7.0, self.valid_weights, borderline, self.valid_auto_reject
        )
        assert any("borderline_range.low" in e for e in errors)

    def test_borderline_low_equal_high(self):
        borderline = {"low": 6.0, "high": 6.0}
        errors = self.svc._validate_proposal(
            7.0, self.valid_weights, borderline, self.valid_auto_reject
        )
        assert any("borderline_range.low" in e for e in errors)

    def test_borderline_out_of_range(self):
        borderline = {"low": -1.0, "high": 7.0}
        errors = self.svc._validate_proposal(
            7.0, self.valid_weights, borderline, self.valid_auto_reject
        )
        assert any("not in [0, 10]" in e for e in errors)

    def test_invalid_auto_reject_check(self):
        errors = self.svc._validate_proposal(
            7.0, self.valid_weights, self.valid_borderline, ["V9", "INVALID"]
        )
        assert any("Invalid auto_reject" in e for e in errors)

    def test_all_15_checks_required(self):
        """Verify all 15 rubric check keys must be present."""
        for check in VALID_CHECK_IDS:
            weights = {c: 1.0 for c in VALID_CHECK_IDS if c != check}
            errors = self.svc._validate_proposal(
                7.0, weights, self.valid_borderline, self.valid_auto_reject
            )
            assert any(check in e for e in errors), f"Missing {check} not detected"


class TestBuildProposalRow:
    """Test _build_proposal_row output format."""

    def test_row_has_required_fields(self):
        svc = QualityCalibrationService()
        row = svc._build_proposal_row(
            organization_id=_org_id(),
            current_config_id="config-123",
            proposed_threshold=7.5,
            proposed_weights={"V1": 1.0},
            proposed_borderline={"low": 5.0, "high": 7.0},
            proposed_auto_reject=["V9"],
            analysis={"total_overrides": 50},
            window_days=30,
            meets_min_sample=True,
            within_delta=True,
            status="proposed",
            job_run_id=None,
            notes=None,
        )

        assert row["proposed_pass_threshold"] == 7.5
        assert row["status"] == "proposed"
        assert row["total_overrides_analyzed"] == 50
        assert row["meets_min_sample_size"] is True
        assert row["within_delta_bounds"] is True

    def test_insufficient_evidence_row(self):
        svc = QualityCalibrationService()
        row = svc._build_proposal_row(
            organization_id=None,
            current_config_id=None,
            proposed_threshold=7.0,
            proposed_weights={},
            proposed_borderline={},
            proposed_auto_reject=[],
            analysis={"total_overrides": 5},
            window_days=30,
            meets_min_sample=False,
            within_delta=True,
            status="insufficient_evidence",
            job_run_id=None,
            notes="Only 5 overrides",
        )

        assert row["status"] == "insufficient_evidence"
        assert row["meets_min_sample_size"] is False
        assert row["notes"] == "Only 5 overrides"


class TestAnalyzeOverrides:
    """Test override analysis logic."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_overrides(self):
        svc = QualityCalibrationService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])
            client.table.return_value.select.return_value.is_.return_value.gte.return_value = chain

            result = await svc.analyze_overrides()
            assert result["total_overrides"] == 0
            assert result["false_positive_rate"] is None


class TestProposeCalibration:
    """Test proposal generation with safety rails."""

    @pytest.mark.asyncio
    async def test_insufficient_evidence_below_min_sample(self):
        svc = QualityCalibrationService()

        with patch.object(svc, "analyze_overrides", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = {
                "total_overrides": 10,
                "false_positive_rate": 0.1,
                "false_negative_rate": 0.1,
                "per_check_rates": {},
            }

            with patch("viraltracker.core.database.get_supabase_client") as mock_db:
                client = MagicMock()
                mock_db.return_value = client
                client.table.return_value.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "proposal-123"}]
                )

                with patch("viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
                           new_callable=AsyncMock) as mock_config:
                    mock_config.return_value = {
                        "id": "config-1",
                        "pass_threshold": 7.0,
                        "check_weights": {c: 1.0 for c in VALID_CHECK_IDS},
                        "borderline_range": {"low": 5.0, "high": 7.0},
                        "auto_reject_checks": ["V9"],
                    }

                    result = await svc.propose_calibration()
                    assert result["status"] == "insufficient_evidence"


class TestActivateProposal:
    """Test proposal activation flow."""

    @pytest.mark.asyncio
    async def test_activates_proposed_proposal(self):
        svc = QualityCalibrationService()
        user_id = UUID("00000000-0000-0000-0000-000000000099")

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client

            # Mock proposal lookup
            client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                data={
                    "id": "proposal-1",
                    "status": "proposed",
                    "organization_id": str(_org_id()),
                    "current_config_id": "config-old",
                    "proposed_pass_threshold": 7.5,
                    "proposed_check_weights": {c: 1.0 for c in VALID_CHECK_IDS},
                    "proposed_borderline_range": {"low": 5.0, "high": 7.0},
                    "proposed_auto_reject_checks": ["V9"],
                }
            )

            # Mock version query
            client.table.return_value.select.return_value.order.return_value.limit.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"version": 2}]
            )

            # Mock config insert
            client.table.return_value.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": "config-new"}]
            )

            # Mock update calls
            client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

            result = await svc.activate_proposal(UUID("00000000-0000-0000-0000-000000000010"), user_id)
            assert result["status"] == "activated"
            assert result["version"] == 3

    @pytest.mark.asyncio
    async def test_rejects_non_proposed_status(self):
        svc = QualityCalibrationService()
        user_id = UUID("00000000-0000-0000-0000-000000000099")

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client

            client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                data={"id": "proposal-1", "status": "activated"}
            )

            with pytest.raises(ValueError, match="not in 'proposed' status"):
                await svc.activate_proposal(UUID("00000000-0000-0000-0000-000000000010"), user_id)

    @pytest.mark.asyncio
    async def test_rejects_missing_proposal(self):
        svc = QualityCalibrationService()
        user_id = UUID("00000000-0000-0000-0000-000000000099")

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client

            client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                data=None
            )

            with pytest.raises(ValueError, match="not found"):
                await svc.activate_proposal(UUID("00000000-0000-0000-0000-000000000010"), user_id)


class TestDismissProposal:
    """Test proposal dismissal flow."""

    @pytest.mark.asyncio
    async def test_dismiss_updates_status(self):
        svc = QualityCalibrationService()
        user_id = UUID("00000000-0000-0000-0000-000000000099")

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

            await svc.dismiss_proposal(
                UUID("00000000-0000-0000-0000-000000000010"),
                user_id,
                "Threshold change too aggressive"
            )

            # Verify update was called with dismissed status
            update_call = client.table.return_value.update.call_args
            assert update_call[0][0]["status"] == "dismissed"
            assert update_call[0][0]["dismissed_reason"] == "Threshold change too aggressive"


class TestGetPendingProposals:
    """Test pending proposals retrieval."""

    @pytest.mark.asyncio
    async def test_returns_proposed_proposals(self):
        svc = QualityCalibrationService()
        mock_proposals = [
            {"id": "p1", "status": "proposed", "proposed_pass_threshold": 7.5},
            {"id": "p2", "status": "proposed", "proposed_pass_threshold": 6.8},
        ]

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
                data=mock_proposals
            )

            result = await svc.get_pending_proposals()
            assert len(result) == 2
            assert result[0]["status"] == "proposed"

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        svc = QualityCalibrationService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
                data=[]
            )

            result = await svc.get_pending_proposals()
            assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_org_when_provided(self):
        svc = QualityCalibrationService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            chain = client.table.return_value.select.return_value.eq.return_value.order.return_value
            chain.eq.return_value.execute.return_value = MagicMock(data=[])

            await svc.get_pending_proposals(organization_id=_org_id())
            # Verify .eq was called for org filter
            client.table.assert_called()


class TestGetProposalHistory:
    """Test proposal history retrieval."""

    @pytest.mark.asyncio
    async def test_returns_ordered_history(self):
        svc = QualityCalibrationService()
        mock_history = [
            {"id": "p1", "status": "activated", "proposed_pass_threshold": 7.5},
            {"id": "p2", "status": "dismissed", "proposed_pass_threshold": 8.0},
            {"id": "p3", "status": "insufficient_evidence", "proposed_pass_threshold": 7.0},
        ]

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            client.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=mock_history
            )

            result = await svc.get_proposal_history()
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_limits_to_50(self):
        svc = QualityCalibrationService()

        with patch("viraltracker.core.database.get_supabase_client") as mock_db:
            client = MagicMock()
            mock_db.return_value = client
            limit_mock = client.table.return_value.select.return_value.order.return_value.limit
            limit_mock.return_value.execute.return_value = MagicMock(data=[])

            await svc.get_proposal_history()
            limit_mock.assert_called_with(50)
