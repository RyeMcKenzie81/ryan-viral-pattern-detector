"""
Tests for WinnerEvolutionService — winner detection, variable selection,
iteration limits, lineage recording.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import UUID, uuid4

from viraltracker.services.winner_evolution_service import (
    WinnerEvolutionService,
    WINNER_MIN_REWARD_SCORE,
    WINNER_MIN_IMPRESSIONS,
    MAX_ITERATIONS_PER_WINNER,
    MAX_ROUNDS_ON_ANCESTOR,
    EVOLUTION_MODES,
    ALL_CANVAS_SIZES,
    VARIABLE_PRIORITY_WEIGHTS,
    ITERABLE_ELEMENTS,
    _safe_avg,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def evo_service():
    """Create a WinnerEvolutionService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = WinnerEvolutionService()
        service.supabase = MagicMock()
        yield service


BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")
AD_ID = UUID("00000000-0000-0000-0000-000000000010")
CHILD_ID = UUID("00000000-0000-0000-0000-000000000020")
ANCESTOR_ID = UUID("00000000-0000-0000-0000-000000000030")


def _mock_table(service, table_name):
    """Get the mock table chain for a table name."""
    return service.supabase.table(table_name)


def _make_execute_result(data=None, count=None):
    """Create a mock execute() result."""
    result = MagicMock()
    result.data = data or []
    result.count = count
    return result


# ============================================================================
# Constants
# ============================================================================

class TestConstants:
    def test_winner_min_reward_score(self):
        assert WINNER_MIN_REWARD_SCORE == 0.65

    def test_winner_min_impressions(self):
        assert WINNER_MIN_IMPRESSIONS == 1000

    def test_max_iterations(self):
        assert MAX_ITERATIONS_PER_WINNER == 5

    def test_max_rounds(self):
        assert MAX_ROUNDS_ON_ANCESTOR == 3

    def test_evolution_modes(self):
        assert "winner_iteration" in EVOLUTION_MODES
        assert "anti_fatigue_refresh" in EVOLUTION_MODES
        assert "cross_size_expansion" in EVOLUTION_MODES

    def test_all_canvas_sizes(self):
        assert "1080x1080px" in ALL_CANVAS_SIZES
        assert "1080x1350px" in ALL_CANVAS_SIZES
        assert "1080x1920px" in ALL_CANVAS_SIZES

    def test_variable_priorities_ordering(self):
        assert VARIABLE_PRIORITY_WEIGHTS["hook_type"] > VARIABLE_PRIORITY_WEIGHTS["color_mode"]
        assert VARIABLE_PRIORITY_WEIGHTS["awareness_stage"] > VARIABLE_PRIORITY_WEIGHTS["template_category"]

    def test_iterable_elements_match_priorities(self):
        for elem in ITERABLE_ELEMENTS:
            assert elem in VARIABLE_PRIORITY_WEIGHTS


# ============================================================================
# _safe_avg tests
# ============================================================================

class TestSafeAvg:
    def test_normal_values(self):
        assert _safe_avg([1.0, 2.0, 3.0]) == 2.0

    def test_with_none_values(self):
        assert _safe_avg([1.0, None, 3.0]) == 2.0

    def test_all_none(self):
        assert _safe_avg([None, None]) is None

    def test_empty_list(self):
        assert _safe_avg([]) is None

    def test_single_value(self):
        assert _safe_avg([5.0]) == 5.0


# ============================================================================
# check_winner_criteria tests
# ============================================================================

class TestWinnerCriteria:
    @pytest.mark.asyncio
    async def test_winner_with_high_reward(self, evo_service):
        """Ad with reward >= 0.65 and sufficient impressions is a winner."""
        chain = _mock_table(evo_service, "creative_element_rewards")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{
                "reward_score": 0.75,
                "impressions_at_maturity": 2000,
                "matured_at": "2026-02-01T00:00:00+00:00",
                "campaign_objective": "CONVERSIONS",
            }])
        )

        result = await evo_service.check_winner_criteria(AD_ID)
        assert result["is_winner"] is True
        assert result["reward_score"] == 0.75
        assert "Reward score" in result["reason"]

    @pytest.mark.asyncio
    async def test_not_winner_low_reward(self, evo_service):
        """Ad with low reward and not top quartile is not a winner."""
        # Mock reward lookup
        chain = _mock_table(evo_service, "creative_element_rewards")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{
                "reward_score": 0.40,
                "impressions_at_maturity": 2000,
                "matured_at": "2026-02-01T00:00:00+00:00",
                "campaign_objective": "CONVERSIONS",
            }])
        )

        # Mock top quartile check (not in top quartile)
        with patch.object(evo_service, "_check_top_quartile", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = {"in_top_quartile": False}

            result = await evo_service.check_winner_criteria(AD_ID)
            assert result["is_winner"] is False

    @pytest.mark.asyncio
    async def test_not_winner_no_data(self, evo_service):
        """Ad with no reward data is not a winner."""
        chain = _mock_table(evo_service, "creative_element_rewards")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([])
        )

        result = await evo_service.check_winner_criteria(AD_ID)
        assert result["is_winner"] is False
        assert "not yet matured" in result["reason"]

    @pytest.mark.asyncio
    async def test_not_winner_low_impressions(self, evo_service):
        """Ad with insufficient impressions is not a winner."""
        chain = _mock_table(evo_service, "creative_element_rewards")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{
                "reward_score": 0.80,
                "impressions_at_maturity": 500,
                "matured_at": "2026-02-01T00:00:00+00:00",
                "campaign_objective": "CONVERSIONS",
            }])
        )

        result = await evo_service.check_winner_criteria(AD_ID)
        assert result["is_winner"] is False
        assert "impressions" in result["reason"].lower()


# ============================================================================
# check_iteration_limits tests
# ============================================================================

class TestIterationLimits:
    @pytest.mark.asyncio
    async def test_can_evolve_fresh_ad(self, evo_service):
        """Fresh ad with no lineage can be evolved."""
        # Direct iterations count
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.eq.return_value.execute.return_value = (
            _make_execute_result([], count=0)
        )

        # Ancestor lookup (no lineage = self)
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = AD_ID

            # Ancestor round query
            chain2 = _mock_table(evo_service, "ad_lineage")
            chain2.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
                _make_execute_result([])
            )

            result = await evo_service.check_iteration_limits(AD_ID)
            assert result["can_evolve"] is True
            assert result["iteration_count"] == 0

    @pytest.mark.asyncio
    async def test_cannot_evolve_max_iterations(self, evo_service):
        """Ad at max iterations cannot be evolved."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.eq.return_value.execute.return_value = (
            _make_execute_result([], count=MAX_ITERATIONS_PER_WINNER)
        )

        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = ANCESTOR_ID

            chain2 = _mock_table(evo_service, "ad_lineage")
            chain2.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
                _make_execute_result([{"iteration_round": 1}])
            )

            result = await evo_service.check_iteration_limits(AD_ID)
            assert result["can_evolve"] is False
            assert "Max iterations" in result["reason"]

    @pytest.mark.asyncio
    async def test_cannot_evolve_max_rounds(self, evo_service):
        """Ad at max ancestor rounds cannot be evolved."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.eq.return_value.execute.return_value = (
            _make_execute_result([], count=1)
        )

        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = ANCESTOR_ID

            chain2 = _mock_table(evo_service, "ad_lineage")
            chain2.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
                _make_execute_result([{"iteration_round": MAX_ROUNDS_ON_ANCESTOR}])
            )

            result = await evo_service.check_iteration_limits(AD_ID)
            assert result["can_evolve"] is False
            assert "ancestor rounds" in result["reason"]


# ============================================================================
# get_ancestor tests
# ============================================================================

class TestGetAncestor:
    @pytest.mark.asyncio
    async def test_no_lineage_returns_self(self, evo_service):
        """Ad with no lineage is its own ancestor."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([])
        )

        result = await evo_service.get_ancestor(AD_ID)
        assert result == AD_ID

    @pytest.mark.asyncio
    async def test_with_lineage_returns_ancestor(self, evo_service):
        """Ad with lineage returns the stored ancestor."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{"ancestor_ad_id": str(ANCESTOR_ID)}])
        )

        result = await evo_service.get_ancestor(AD_ID)
        assert result == ANCESTOR_ID


# ============================================================================
# _get_untested_sizes tests
# ============================================================================

class TestGetUntestedSizes:
    @pytest.mark.asyncio
    async def test_all_sizes_untested(self, evo_service):
        """If ad is only in 1080x1080px, other sizes are untested."""
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = AD_ID

            chain = _mock_table(evo_service, "ad_lineage")
            chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
                _make_execute_result([])
            )

            result = await evo_service._get_untested_sizes(AD_ID, "1080x1080px")
            assert "1080x1350px" in result
            assert "1080x1920px" in result
            assert "1080x1080px" not in result

    @pytest.mark.asyncio
    async def test_some_sizes_tested(self, evo_service):
        """If a cross-size child exists, that size is excluded."""
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = AD_ID

            chain = _mock_table(evo_service, "ad_lineage")
            chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
                _make_execute_result([
                    {"child_ad_id": str(CHILD_ID), "variable_new_value": "1080x1350px"},
                ])
            )

            result = await evo_service._get_untested_sizes(AD_ID, "1080x1080px")
            assert "1080x1350px" not in result
            assert "1080x1920px" in result

    @pytest.mark.asyncio
    async def test_all_sizes_tested(self, evo_service):
        """If all sizes tested, returns empty list."""
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = AD_ID

            chain = _mock_table(evo_service, "ad_lineage")
            chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
                _make_execute_result([
                    {"child_ad_id": str(uuid4()), "variable_new_value": "1080x1350px"},
                    {"child_ad_id": str(uuid4()), "variable_new_value": "1080x1920px"},
                ])
            )

            result = await evo_service._get_untested_sizes(AD_ID, "1080x1080px")
            assert result == []


# ============================================================================
# select_evolution_variable tests
# ============================================================================

class TestVariableSelection:
    @pytest.mark.asyncio
    async def test_selects_highest_information_gain(self, evo_service):
        """Variable with highest uncertainty × priority is selected."""
        parent_tags = {
            "hook_type": "curiosity_gap",
            "color_mode": "original",
            "template_category": "before_after",
            "awareness_stage": "problem_aware",
        }

        # Mock: hook_type has 3 values with high variance
        # color_mode has 2 values with low variance
        def mock_select_side_effect(table_name):
            chain = MagicMock()
            if table_name == "creative_element_scores":
                def select_fn(*args, **kwargs):
                    select_chain = MagicMock()

                    def eq_brand(field, value):
                        eq_chain = MagicMock()

                        def eq_element(field2, value2):
                            exec_mock = MagicMock()
                            if value2 == "hook_type":
                                exec_mock.execute.return_value = _make_execute_result([
                                    {"element_value": "curiosity_gap", "alpha": 2.0, "beta": 8.0, "total_observations": 10},
                                    {"element_value": "fear_of_missing_out", "alpha": 5.0, "beta": 5.0, "total_observations": 10},
                                    {"element_value": "social_proof", "alpha": 8.0, "beta": 2.0, "total_observations": 10},
                                ])
                            elif value2 == "color_mode":
                                exec_mock.execute.return_value = _make_execute_result([
                                    {"element_value": "original", "alpha": 50.0, "beta": 50.0, "total_observations": 100},
                                    {"element_value": "complementary", "alpha": 48.0, "beta": 52.0, "total_observations": 100},
                                ])
                            elif value2 == "template_category":
                                exec_mock.execute.return_value = _make_execute_result([
                                    {"element_value": "before_after", "alpha": 10.0, "beta": 10.0, "total_observations": 20},
                                    {"element_value": "testimonial", "alpha": 8.0, "beta": 12.0, "total_observations": 20},
                                ])
                            elif value2 == "awareness_stage":
                                exec_mock.execute.return_value = _make_execute_result([
                                    {"element_value": "problem_aware", "alpha": 3.0, "beta": 7.0, "total_observations": 10},
                                    {"element_value": "solution_aware", "alpha": 7.0, "beta": 3.0, "total_observations": 10},
                                ])
                            else:
                                exec_mock.execute.return_value = _make_execute_result([])
                            return exec_mock
                        eq_chain.eq = eq_element
                        return eq_chain
                    select_chain.eq = eq_brand
                    return select_chain
                chain.select = select_fn
            return chain

        evo_service.supabase.table = mock_select_side_effect

        # Mock genome service for Thompson Sampling
        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            mock_genome = MagicMock()
            MockGenome.return_value = mock_genome
            mock_genome.sample_element_scores.return_value = [
                {"value": "fear_of_missing_out", "sample": 0.7},
                {"value": "social_proof", "sample": 0.6},
                {"value": "curiosity_gap", "sample": 0.3},
            ]

            result = await evo_service.select_evolution_variable(BRAND_ID, parent_tags)

            assert result["variable"] in ITERABLE_ELEMENTS
            assert result["new_value"] is not None
            assert result["new_value"] != parent_tags.get(result["variable"])
            assert len(result["all_candidates"]) > 0

    @pytest.mark.asyncio
    async def test_fallback_when_no_scores(self, evo_service):
        """Falls back to random element when no element scores exist."""
        parent_tags = {"hook_type": "curiosity_gap", "color_mode": "original"}

        # All queries return empty (fewer than 2 values)
        chain = _mock_table(evo_service, "creative_element_scores")
        chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_execute_result([])
        )

        result = await evo_service.select_evolution_variable(BRAND_ID, parent_tags)
        assert result.get("fallback") is True
        assert result["variable"] in ITERABLE_ELEMENTS


# ============================================================================
# record_lineage tests
# ============================================================================

class TestRecordLineage:
    @pytest.mark.asyncio
    async def test_records_single_child(self, evo_service):
        """Records lineage for a single evolved ad."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.insert.return_value.execute.return_value = _make_execute_result()

        count = await evo_service.record_lineage(
            parent_ad_id=AD_ID,
            child_ad_ids=[CHILD_ID],
            ancestor_ad_id=ANCESTOR_ID,
            mode="winner_iteration",
            variable_changed="hook_type",
            old_value="curiosity_gap",
            new_value="fear_of_missing_out",
            iteration_round=1,
            parent_reward=0.72,
        )

        assert count == 1
        chain.insert.assert_called_once()
        inserted = chain.insert.call_args[0][0]
        assert inserted["parent_ad_id"] == str(AD_ID)
        assert inserted["child_ad_id"] == str(CHILD_ID)
        assert inserted["ancestor_ad_id"] == str(ANCESTOR_ID)
        assert inserted["evolution_mode"] == "winner_iteration"
        assert inserted["variable_changed"] == "hook_type"
        assert inserted["iteration_round"] == 1

    @pytest.mark.asyncio
    async def test_records_multiple_children(self, evo_service):
        """Records lineage for multiple evolved ads."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.insert.return_value.execute.return_value = _make_execute_result()

        child_ids = [uuid4(), uuid4(), uuid4()]
        count = await evo_service.record_lineage(
            parent_ad_id=AD_ID,
            child_ad_ids=child_ids,
            ancestor_ad_id=ANCESTOR_ID,
            mode="anti_fatigue_refresh",
            variable_changed="visual_execution",
            old_value="original",
            new_value="complementary",
            iteration_round=2,
            parent_reward=0.68,
        )

        assert count == 3
        assert chain.insert.call_count == 3

    @pytest.mark.asyncio
    async def test_records_with_job_id(self, evo_service):
        """Records lineage with evolution_job_id."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.insert.return_value.execute.return_value = _make_execute_result()

        job_id = uuid4()
        await evo_service.record_lineage(
            parent_ad_id=AD_ID,
            child_ad_ids=[CHILD_ID],
            ancestor_ad_id=ANCESTOR_ID,
            mode="cross_size_expansion",
            variable_changed="canvas_size",
            old_value="1080x1080px",
            new_value="1080x1350px",
            iteration_round=1,
            parent_reward=0.80,
            job_id=job_id,
        )

        inserted = chain.insert.call_args[0][0]
        assert inserted["evolution_job_id"] == str(job_id)


# ============================================================================
# get_lineage_tree tests
# ============================================================================

class TestLineageTree:
    @pytest.mark.asyncio
    async def test_tree_with_entries(self, evo_service):
        """Gets lineage tree with ancestor and descendants."""
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = ANCESTOR_ID

            chain = _mock_table(evo_service, "ad_lineage")
            chain.select.return_value.eq.return_value.order.return_value.execute.return_value = (
                _make_execute_result([
                    {"parent_ad_id": str(ANCESTOR_ID), "child_ad_id": str(AD_ID),
                     "evolution_mode": "winner_iteration", "iteration_round": 1},
                    {"parent_ad_id": str(AD_ID), "child_ad_id": str(CHILD_ID),
                     "evolution_mode": "cross_size_expansion", "iteration_round": 2},
                ])
            )

            result = await evo_service.get_lineage_tree(AD_ID)
            assert result["ancestor_id"] == str(ANCESTOR_ID)
            assert result["total_descendants"] == 2

    @pytest.mark.asyncio
    async def test_tree_no_entries(self, evo_service):
        """Gets empty tree for ad with no lineage."""
        with patch.object(evo_service, "get_ancestor", new_callable=AsyncMock) as mock_anc:
            mock_anc.return_value = AD_ID

            chain = _mock_table(evo_service, "ad_lineage")
            chain.select.return_value.eq.return_value.order.return_value.execute.return_value = (
                _make_execute_result([])
            )

            result = await evo_service.get_lineage_tree(AD_ID)
            assert result["total_descendants"] == 0


# ============================================================================
# update_evolution_outcomes tests
# ============================================================================

class TestUpdateOutcomes:
    @pytest.mark.asyncio
    async def test_updates_outperformed(self, evo_service):
        """Marks child as outperforming parent when child reward > parent reward."""
        # Pending lineage entries
        chain_lineage = _mock_table(evo_service, "ad_lineage")
        chain_lineage.select.return_value.is_.return_value.execute.return_value = (
            _make_execute_result([{
                "id": str(uuid4()),
                "child_ad_id": str(CHILD_ID),
                "parent_reward_score": 0.65,
            }])
        )

        # Child has matured with higher reward
        chain_reward = _mock_table(evo_service, "creative_element_rewards")
        chain_reward.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{"reward_score": 0.80}])
        )

        # Update mock
        chain_lineage.update.return_value.eq.return_value.execute.return_value = _make_execute_result()

        result = await evo_service.update_evolution_outcomes(BRAND_ID)
        assert result["updated"] == 1
        assert result["outperformed"] == 1
        assert result["underperformed"] == 0

    @pytest.mark.asyncio
    async def test_updates_underperformed(self, evo_service):
        """Marks child as underperforming when child reward <= parent reward."""
        chain_lineage = _mock_table(evo_service, "ad_lineage")
        chain_lineage.select.return_value.is_.return_value.execute.return_value = (
            _make_execute_result([{
                "id": str(uuid4()),
                "child_ad_id": str(CHILD_ID),
                "parent_reward_score": 0.80,
            }])
        )

        chain_reward = _mock_table(evo_service, "creative_element_rewards")
        chain_reward.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_execute_result([{"reward_score": 0.55}])
        )

        chain_lineage.update.return_value.eq.return_value.execute.return_value = _make_execute_result()

        result = await evo_service.update_evolution_outcomes(BRAND_ID)
        assert result["updated"] == 1
        assert result["outperformed"] == 0
        assert result["underperformed"] == 1

    @pytest.mark.asyncio
    async def test_no_pending_entries(self, evo_service):
        """No updates when no pending lineage entries."""
        chain = _mock_table(evo_service, "ad_lineage")
        chain.select.return_value.is_.return_value.execute.return_value = (
            _make_execute_result([])
        )

        result = await evo_service.update_evolution_outcomes(BRAND_ID)
        assert result["updated"] == 0


# ============================================================================
# _build_base_pipeline_params tests
# ============================================================================

class TestBuildBasePipelineParams:
    def test_builds_params_from_parent(self, evo_service):
        """Builds correct V2 pipeline params from parent ad data."""
        parent = {
            "id": str(AD_ID),
            "canvas_size": "1080x1080px",
            "color_mode": "original",
        }
        element_tags = {
            "template_id": str(uuid4()),
            "canvas_size": "1080x1080px",
            "color_mode": "original",
            "content_source": "hooks",
            "persona_id": str(uuid4()),
        }
        parent_image_b64 = "base64data"
        product_id = str(uuid4())

        result = evo_service._build_base_pipeline_params(
            parent, element_tags, parent_image_b64, product_id
        )

        assert result["product_id"] == product_id
        assert result["reference_ad_base64"] == parent_image_b64
        assert result["template_id"] == element_tags["template_id"]
        assert result["canvas_sizes"] == ["1080x1080px"]
        assert result["color_modes"] == ["original"]
        assert result["content_source"] == "hooks"
        assert result["persona_id"] == element_tags["persona_id"]
        assert result["auto_retry_rejected"] is False


# ============================================================================
# evolve_winner validation tests
# ============================================================================

class TestEvolveWinnerValidation:
    @pytest.mark.asyncio
    async def test_invalid_mode_raises(self, evo_service):
        """Invalid evolution mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid evolution mode"):
            await evo_service.evolve_winner(AD_ID, "invalid_mode")

    @pytest.mark.asyncio
    async def test_non_winner_raises(self, evo_service):
        """Non-winner ad raises ValueError."""
        with patch.object(evo_service, "check_winner_criteria", new_callable=AsyncMock) as mock_w:
            mock_w.return_value = {"is_winner": False, "reason": "Low reward"}
            with pytest.raises(ValueError, match="does not meet winner criteria"):
                await evo_service.evolve_winner(AD_ID, "winner_iteration")

    @pytest.mark.asyncio
    async def test_limit_exceeded_raises(self, evo_service):
        """Exceeded iteration limit raises ValueError."""
        with patch.object(evo_service, "check_winner_criteria", new_callable=AsyncMock) as mock_w:
            mock_w.return_value = {"is_winner": True, "reward_score": 0.75}
            with patch.object(evo_service, "check_iteration_limits", new_callable=AsyncMock) as mock_l:
                mock_l.return_value = {"can_evolve": False, "reason": "Max iterations"}
                with pytest.raises(ValueError, match="Evolution limit reached"):
                    await evo_service.evolve_winner(AD_ID, "winner_iteration")
