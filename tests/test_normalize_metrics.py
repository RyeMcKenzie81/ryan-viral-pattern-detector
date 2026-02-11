"""Unit tests for MetaAdsService.normalize_metrics() and related extractors.

Tests use Meta-shaped payloads with string values, missing keys, empty arrays,
float costs, and zero-value rates to verify correct extraction.
"""

import pytest


@pytest.fixture
def service():
    """Create a MetaAdsService with no real credentials (extractors are pure)."""
    from viraltracker.services.meta_ads_service import MetaAdsService
    return MetaAdsService(access_token="fake", ad_account_id="act_fake")


# ---------------------------------------------------------------------------
# Existing action extractions
# ---------------------------------------------------------------------------

class TestExtractAction:
    def test_extract_from_actions_array(self, service):
        insight = {"actions": [{"action_type": "add_to_cart", "value": "5"}]}
        assert service._extract_action(insight, "add_to_cart") == 5

    def test_missing_action_type(self, service):
        insight = {"actions": [{"action_type": "purchase", "value": "2"}]}
        assert service._extract_action(insight, "add_to_cart") is None

    def test_empty_actions(self, service):
        insight = {"actions": []}
        assert service._extract_action(insight, "add_to_cart") is None

    def test_missing_actions_key(self, service):
        insight = {}
        assert service._extract_action(insight, "add_to_cart") is None

    def test_actions_not_list(self, service):
        insight = {"actions": "not_a_list"}
        assert service._extract_action(insight, "add_to_cart") is None


class TestExtractVideoMetric:
    def test_extract_video_metric(self, service):
        insight = {"video_p25_watched_actions": [{"action_type": "video_view", "value": "100"}]}
        assert service._extract_video_metric(insight, "video_p25_watched_actions") == 100

    def test_empty_array(self, service):
        insight = {"video_p25_watched_actions": []}
        assert service._extract_video_metric(insight, "video_p25_watched_actions") is None

    def test_missing_key(self, service):
        assert service._extract_video_metric({}, "video_p25_watched_actions") is None


class TestExtractCost:
    def test_extract_cost(self, service):
        insight = {"cost_per_action_type": [{"action_type": "add_to_cart", "value": "3.14"}]}
        result = service._extract_cost(insight, "add_to_cart")
        assert result == pytest.approx(3.14)

    def test_missing_cost(self, service):
        insight = {"cost_per_action_type": [{"action_type": "purchase", "value": "10.0"}]}
        assert service._extract_cost(insight, "add_to_cart") is None

    def test_empty_costs(self, service):
        insight = {"cost_per_action_type": []}
        assert service._extract_cost(insight, "add_to_cart") is None

    def test_costs_not_list(self, service):
        insight = {"cost_per_action_type": "bad"}
        assert service._extract_cost(insight, "add_to_cart") is None


# ---------------------------------------------------------------------------
# New action extractions (B2)
# ---------------------------------------------------------------------------

class TestNewActionExtractions:
    def test_initiate_checkouts(self, service):
        insight = {"actions": [{"action_type": "initiate_checkout", "value": "12"}]}
        result = service.normalize_metrics(insight)
        assert result["initiate_checkouts"] == 12

    def test_landing_page_views(self, service):
        insight = {"actions": [{"action_type": "landing_page_view", "value": "45"}]}
        result = service.normalize_metrics(insight)
        assert result["landing_page_views"] == 45

    def test_content_views(self, service):
        insight = {"actions": [{"action_type": "view_content", "value": "200"}]}
        result = service.normalize_metrics(insight)
        assert result["content_views"] == 200

    def test_cost_per_initiate_checkout(self, service):
        insight = {"cost_per_action_type": [{"action_type": "initiate_checkout", "value": "5.25"}]}
        result = service.normalize_metrics(insight)
        assert result["cost_per_initiate_checkout"] == pytest.approx(5.25)

    def test_all_new_actions_missing(self, service):
        """When no relevant actions exist, all new fields should be None."""
        insight = {"actions": [{"action_type": "purchase", "value": "1"}]}
        result = service.normalize_metrics(insight)
        assert result["initiate_checkouts"] is None
        assert result["landing_page_views"] is None
        assert result["content_views"] is None
        assert result["cost_per_initiate_checkout"] is None


# ---------------------------------------------------------------------------
# New video metrics (B2)
# ---------------------------------------------------------------------------

class TestNewVideoMetrics:
    def test_video_thruplay(self, service):
        insight = {"video_thruplay_watched_actions": [{"action_type": "video_view", "value": "50"}]}
        result = service.normalize_metrics(insight)
        assert result["video_thruplay"] == 50

    def test_video_p95(self, service):
        insight = {"video_p95_watched_actions": [{"action_type": "video_view", "value": "30"}]}
        result = service.normalize_metrics(insight)
        assert result["video_p95_watched"] == 30

    def test_video_metrics_missing(self, service):
        result = service.normalize_metrics({})
        assert result["video_thruplay"] is None
        assert result["video_p95_watched"] is None


# ---------------------------------------------------------------------------
# Derived metrics (B3)
# ---------------------------------------------------------------------------

class TestDerivedMetrics:
    def test_hold_rate(self, service):
        """hold_rate = thruplay / video_views (3-sec views)."""
        insight = {
            "actions": [{"action_type": "video_view", "value": "100"}],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "40"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hold_rate"] == pytest.approx(0.4)

    def test_hold_rate_zero_thruplay(self, service):
        """0 thruplay / N views = 0.0, not None."""
        insight = {
            "actions": [{"action_type": "video_view", "value": "100"}],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "0"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hold_rate"] == 0.0

    def test_hold_rate_no_video_views(self, service):
        """No video views → hold_rate is None (avoid division by zero)."""
        insight = {
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "50"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hold_rate"] is None

    def test_hold_rate_zero_video_views(self, service):
        """Zero video views → hold_rate is None."""
        insight = {
            "actions": [{"action_type": "video_view", "value": "0"}],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "50"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hold_rate"] is None

    def test_hook_rate(self, service):
        """hook_rate = video_views / impressions."""
        insight = {
            "impressions": "1000",
            "actions": [{"action_type": "video_view", "value": "150"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hook_rate"] == pytest.approx(0.15)

    def test_hook_rate_zero_impressions(self, service):
        """Zero impressions → hook_rate is None."""
        insight = {
            "impressions": "0",
            "actions": [{"action_type": "video_view", "value": "10"}],
        }
        result = service.normalize_metrics(insight)
        assert result["hook_rate"] is None

    def test_hook_rate_no_video_views(self, service):
        """No video views → hook_rate is None."""
        insight = {"impressions": "1000"}
        result = service.normalize_metrics(insight)
        assert result["hook_rate"] is None

    def test_conversion_rate_zero_purchases(self, service):
        """0 purchases with clicks → conversion_rate = 0.0, not None."""
        insight = {
            "actions": [
                {"action_type": "omni_purchase", "value": "0"},
            ],
            "outbound_clicks": [{"action_type": "outbound_click", "value": "50"}],
        }
        result = service.normalize_metrics(insight)
        assert result["conversion_rate"] == 0.0

    def test_conversion_rate_no_clicks(self, service):
        """No clicks → conversion_rate is None."""
        insight = {
            "actions": [{"action_type": "purchase", "value": "5"}],
        }
        result = service.normalize_metrics(insight)
        assert result["conversion_rate"] is None


# ---------------------------------------------------------------------------
# Full Meta-shaped payload
# ---------------------------------------------------------------------------

class TestFullPayload:
    def test_realistic_meta_payload(self, service):
        """Simulate a realistic Meta API insight response with all fields."""
        insight = {
            "ad_id": "123456789",
            "ad_name": "TestAd-001",
            "adset_id": "987654321",
            "adset_name": "TestAdSet",
            "campaign_id": "111222333",
            "campaign_name": "TestCampaign",
            "date_start": "2026-02-10",
            "spend": "25.50",
            "impressions": "5000",
            "reach": "4000",
            "frequency": "1.25",
            "cpm": "5.10",
            "outbound_clicks": [{"action_type": "outbound_click", "value": "100"}],
            "outbound_clicks_ctr": [{"value": "2.0"}],
            "cost_per_outbound_click": [{"value": "0.255"}],
            "purchase_roas": [{"value": "3.5"}],
            "actions": [
                {"action_type": "add_to_cart", "value": "20"},
                {"action_type": "omni_purchase", "value": "5"},
                {"action_type": "video_view", "value": "3000"},
                {"action_type": "initiate_checkout", "value": "10"},
                {"action_type": "landing_page_view", "value": "80"},
                {"action_type": "view_content", "value": "150"},
            ],
            "action_values": [
                {"action_type": "omni_purchase", "value": "89.25"},
            ],
            "cost_per_action_type": [
                {"action_type": "add_to_cart", "value": "1.275"},
                {"action_type": "initiate_checkout", "value": "2.55"},
            ],
            "video_play_actions": [{"action_type": "video_view", "value": "4500"}],
            "video_avg_time_watched_actions": [{"action_type": "video_view", "value": "8"}],
            "video_p25_watched_actions": [{"action_type": "video_view", "value": "2500"}],
            "video_p50_watched_actions": [{"action_type": "video_view", "value": "2000"}],
            "video_p75_watched_actions": [{"action_type": "video_view", "value": "1500"}],
            "video_p100_watched_actions": [{"action_type": "video_view", "value": "800"}],
            "video_p95_watched_actions": [{"action_type": "video_view", "value": "900"}],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "1200"}],
        }

        result = service.normalize_metrics(insight)

        # Basic fields
        assert result["meta_ad_id"] == "123456789"
        assert result["spend"] == pytest.approx(25.50)
        assert result["impressions"] == 5000
        assert result["reach"] == 4000
        assert result["frequency"] == pytest.approx(1.25)

        # Actions
        assert result["add_to_carts"] == 20
        assert result["purchases"] == 5
        assert result["purchase_value"] == pytest.approx(89.25)
        assert result["link_clicks"] == 100
        assert result["roas"] == pytest.approx(3.5)

        # New actions
        assert result["initiate_checkouts"] == 10
        assert result["landing_page_views"] == 80
        assert result["content_views"] == 150
        assert result["cost_per_initiate_checkout"] == pytest.approx(2.55)

        # Video
        assert result["video_views"] == 3000
        assert result["video_p95_watched"] == 900
        assert result["video_thruplay"] == 1200

        # Derived
        assert result["hold_rate"] == pytest.approx(1200 / 3000, abs=1e-4)
        assert result["hook_rate"] == pytest.approx(3000 / 5000, abs=1e-4)
        assert result["conversion_rate"] == pytest.approx(5.0)

    def test_empty_payload(self, service):
        """Empty insight should return all None values without errors."""
        result = service.normalize_metrics({})
        assert result["meta_ad_id"] is None
        assert result["spend"] is None
        assert result["impressions"] is None
        assert result["purchases"] is None
        assert result["video_thruplay"] is None
        assert result["hold_rate"] is None
        assert result["hook_rate"] is None
        assert result["initiate_checkouts"] is None
        assert result["conversion_rate"] is None
