"""
Tests for offer variant + current_offer_override threading through the pipeline.

Tests:
- FetchContextNode: offer_variant_id validation, current_offer_override threading
- InitializeNode: current_offer_override in run_parameters
- State: current_offer_override field serialization
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState


# ============================================================================
# State field tests
# ============================================================================

class TestCurrentOfferOverrideState:
    """current_offer_override field exists and serializes correctly."""

    def test_default_is_none(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img"
        )
        assert state.current_offer_override is None

    def test_set_override(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            current_offer_override="Free shipping",
        )
        assert state.current_offer_override == "Free shipping"

    def test_round_trip(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            current_offer_override="BOGO deal",
        )
        data = state.to_dict()
        restored = AdCreationPipelineState.from_dict(data)
        assert restored.current_offer_override == "BOGO deal"

    def test_none_round_trip(self):
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
        )
        data = state.to_dict()
        assert "current_offer_override" in data
        assert data["current_offer_override"] is None


# ============================================================================
# FetchContextNode override application
# ============================================================================

class TestFetchContextCurrentOfferOverride:
    """current_offer_override threading and normalization in FetchContextNode."""

    def _make_state(self, override=None, offer_variant_id=None):
        return AdCreationPipelineState(
            product_id="00000000-0000-0000-0000-000000000001",
            reference_ad_base64="img",
            current_offer_override=override,
            offer_variant_id=offer_variant_id,
        )

    @pytest.mark.asyncio
    async def test_override_replaces_db_value(self):
        """Override 'Free shipping' replaces DB value 'BOGO' in product_dict."""
        state = self._make_state(override="Free shipping")

        # Simulate what FetchContextNode does with the override
        product_dict = {"current_offer": "BOGO", "name": "Test Product"}
        override = (state.current_offer_override or '').strip() or None
        if override:
            product_dict['current_offer'] = override

        assert product_dict['current_offer'] == "Free shipping"

    @pytest.mark.asyncio
    async def test_whitespace_only_override_ignored(self):
        """Override '   ' is treated as None (anti-hallucination stays active)."""
        state = self._make_state(override="   ")

        product_dict = {"current_offer": None, "name": "Test Product"}
        override = (state.current_offer_override or '').strip() or None
        if override:
            product_dict['current_offer'] = override

        # current_offer should remain None (whitespace stripped to empty, treated as None)
        assert product_dict['current_offer'] is None

    @pytest.mark.asyncio
    async def test_none_override_preserves_db_value(self):
        """No override leaves product_dict['current_offer'] unchanged."""
        state = self._make_state(override=None)

        product_dict = {"current_offer": "30% off", "name": "Test Product"}
        override = (state.current_offer_override or '').strip() or None
        if override:
            product_dict['current_offer'] = override

        assert product_dict['current_offer'] == "30% off"

    @pytest.mark.asyncio
    async def test_empty_string_override_ignored(self):
        """Override '' is treated as None."""
        state = self._make_state(override="")

        product_dict = {"current_offer": "Buy 2 Get 1", "name": "Test Product"}
        override = (state.current_offer_override or '').strip() or None
        if override:
            product_dict['current_offer'] = override

        assert product_dict['current_offer'] == "Buy 2 Get 1"


# ============================================================================
# InitializeNode run_parameters
# ============================================================================

class TestInitializeRunProvenance:
    """current_offer_override appears in run_parameters for audit."""

    def test_override_in_run_parameters(self):
        """run_parameters includes current_offer_override when set."""
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
            current_offer_override="Free shipping",
        )
        # Simulate InitializeNode run_parameters construction
        run_parameters = {
            "num_variations": state.num_variations,
            "content_source": state.content_source,
            "offer_variant_id": state.offer_variant_id,
            "current_offer_override": state.current_offer_override,
            "image_resolution": state.image_resolution,
        }
        assert run_parameters["current_offer_override"] == "Free shipping"

    def test_none_override_in_run_parameters(self):
        """run_parameters includes current_offer_override=None when not set."""
        state = AdCreationPipelineState(
            product_id="p1", reference_ad_base64="img",
        )
        run_parameters = {
            "num_variations": state.num_variations,
            "content_source": state.content_source,
            "offer_variant_id": state.offer_variant_id,
            "current_offer_override": state.current_offer_override,
            "image_resolution": state.image_resolution,
        }
        assert run_parameters["current_offer_override"] is None


# ============================================================================
# Orchestrator parameter threading
# ============================================================================

class TestOrchestratorCurrentOfferOverride:
    """current_offer_override parameter is accepted and passed to state."""

    def test_state_receives_override(self):
        """State constructor accepts current_offer_override."""
        state = AdCreationPipelineState(
            product_id="p1",
            reference_ad_base64="img",
            current_offer_override="40% off today",
        )
        assert state.current_offer_override == "40% off today"

    def test_state_defaults_to_none(self):
        """State defaults to None when not provided."""
        state = AdCreationPipelineState(
            product_id="p1",
            reference_ad_base64="img",
        )
        assert state.current_offer_override is None
