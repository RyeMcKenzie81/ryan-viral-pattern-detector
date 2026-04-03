"""
Tests for Custom Edit and Multi-Variable Auto-Improve in WinnerEvolutionService.

Covers:
- _evolve_custom_edit: happy path, temp clamping, empty child_ad_ids, lineage values
- _evolve_multi_variable: happy path, partial failure, all-fail, per-child lineage
- evolve_winner: custom_edit routing, missing prompt validation, per-child lineage recording

All pipeline/DB calls mocked — no real connections needed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from viraltracker.services.winner_evolution_service import (
    WinnerEvolutionService,
    EVOLUTION_MODES,
)


# ============================================================================
# Fixtures
# ============================================================================

BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")
PARENT_AD_ID = UUID("00000000-0000-0000-0000-000000000002")
PRODUCT_ID = "00000000-0000-0000-0000-000000000003"

PARENT_AD = {
    "id": str(PARENT_AD_ID),
    "brand_id": str(BRAND_ID),
    "hook_text": "Stop your kids from fighting",
    "canvas_size": "1080x1080px",
}

ELEMENT_TAGS = {
    "hook_type": "curiosity",
    "template_category": "ugc_testimonial",
    "color_mode": "original",
}


@pytest.fixture
def evolution_service():
    """Create a WinnerEvolutionService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        service = WinnerEvolutionService()
        service.supabase = MagicMock()
        yield service


# ============================================================================
# _evolve_custom_edit tests
# ============================================================================

class TestEvolveCustomEdit:
    @pytest.mark.asyncio
    async def test_happy_path(self, evolution_service):
        """Custom edit builds correct pipeline params and returns result."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["child_1", "child_2"], ["run_1"])
        )

        result = await evolution_service._evolve_custom_edit(
            parent=PARENT_AD,
            element_tags=ELEMENT_TAGS,
            parent_image_b64="base64data",
            product_id=PRODUCT_ID,
            brand_id=BRAND_ID,
            custom_prompt="Recreate for 25-34 male demographic",
            temperature=0.7,
        )

        assert result["child_ad_ids"] == ["child_1", "child_2"]
        assert result["ad_run_ids"] == ["run_1"]
        assert result["variable_changed"] == "custom_edit"
        assert result["custom_prompt"] == "Recreate for 25-34 male demographic"
        assert result["old_value"] == "original"
        assert "25-34 male" in result["new_value"]

        # Verify pipeline params
        call_args = evolution_service._run_v2_pipeline.call_args[0][0]
        assert call_args["content_source"] == "recreate_template"
        assert call_args["additional_instructions"] == "Recreate for 25-34 male demographic"
        assert call_args["generation_temperature"] == 0.7
        assert call_args["num_variations"] == 1
        assert len(call_args["pre_selected_hooks"]) == 1
        assert call_args["pre_selected_hooks"][0]["benefit"] == "custom_edit"

    @pytest.mark.asyncio
    async def test_temperature_clamped_low(self, evolution_service):
        """Temperature below 0.1 is clamped to 0.1."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["child_1"], ["run_1"])
        )

        await evolution_service._evolve_custom_edit(
            parent=PARENT_AD,
            element_tags=ELEMENT_TAGS,
            parent_image_b64="base64data",
            product_id=PRODUCT_ID,
            brand_id=BRAND_ID,
            custom_prompt="test",
            temperature=0.0,
        )

        call_args = evolution_service._run_v2_pipeline.call_args[0][0]
        assert call_args["generation_temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_temperature_clamped_high(self, evolution_service):
        """Temperature above 1.0 is clamped to 1.0."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["child_1"], ["run_1"])
        )

        await evolution_service._evolve_custom_edit(
            parent=PARENT_AD,
            element_tags=ELEMENT_TAGS,
            parent_image_b64="base64data",
            product_id=PRODUCT_ID,
            brand_id=BRAND_ID,
            custom_prompt="test",
            temperature=2.0,
        )

        call_args = evolution_service._run_v2_pipeline.call_args[0][0]
        assert call_args["generation_temperature"] == 1.0

    @pytest.mark.asyncio
    async def test_empty_child_ids_raises(self, evolution_service):
        """Raises ValueError when pipeline produces no ads."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(return_value=([], []))

        with pytest.raises(ValueError, match="produced no ads"):
            await evolution_service._evolve_custom_edit(
                parent=PARENT_AD,
                element_tags=ELEMENT_TAGS,
                parent_image_b64="base64data",
                product_id=PRODUCT_ID,
                brand_id=BRAND_ID,
                custom_prompt="test",
            )

    @pytest.mark.asyncio
    async def test_num_variations_passed(self, evolution_service):
        """num_variations is forwarded to pipeline params."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["c1"], ["r1"])
        )

        await evolution_service._evolve_custom_edit(
            parent=PARENT_AD,
            element_tags=ELEMENT_TAGS,
            parent_image_b64="base64data",
            product_id=PRODUCT_ID,
            brand_id=BRAND_ID,
            custom_prompt="test",
            num_variations=3,
        )

        call_args = evolution_service._run_v2_pipeline.call_args[0][0]
        assert call_args["num_variations"] == 3

    @pytest.mark.asyncio
    async def test_hook_preserved(self, evolution_service):
        """Parent hook text is preserved in pre_selected_hooks."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["c1"], ["r1"])
        )

        await evolution_service._evolve_custom_edit(
            parent=PARENT_AD,
            element_tags=ELEMENT_TAGS,
            parent_image_b64="base64data",
            product_id=PRODUCT_ID,
            brand_id=BRAND_ID,
            custom_prompt="test",
        )

        hook = evolution_service._run_v2_pipeline.call_args[0][0]["pre_selected_hooks"][0]
        assert hook["adapted_text"] == "Stop your kids from fighting"
        assert hook["persuasion_type"] == "curiosity"


# ============================================================================
# _evolve_multi_variable tests
# ============================================================================

class TestEvolveMultiVariable:
    def _make_selection(self, n_candidates=3):
        """Create a mock selection result with N candidates."""
        candidates = []
        variables = ["hook_type", "template_category", "color_mode"]
        for i in range(n_candidates):
            candidates.append({
                "variable": variables[i % len(variables)],
                "information_gain": 0.5 - (i * 0.1),
                "parent_value": f"value_{i}",
            })
        return {
            "variable": candidates[0]["variable"],
            "new_value": "new_hook",
            "all_candidates": candidates,
        }

    @pytest.mark.asyncio
    async def test_happy_path_three_variables(self, evolution_service):
        """Runs N pipelines, one per element, returns aggregated results."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._analyze_parent_narrative = AsyncMock(return_value="narrative")
        evolution_service._has_visual_conflict = MagicMock(return_value=False)
        evolution_service._build_evolution_instructions = MagicMock(return_value="instructions")

        # Each pipeline returns one child
        evolution_service._run_v2_pipeline = AsyncMock(
            side_effect=[
                (["child_1"], ["run_1"]),
                (["child_2"], ["run_2"]),
                (["child_3"], ["run_3"]),
            ]
        )

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            genome_instance = MockGenome.return_value
            genome_instance.sample_element_scores = MagicMock(
                side_effect=[
                    [{"value": "new_val_0"}],
                    [{"value": "new_val_1"}],
                    [{"value": "new_val_2"}],
                ]
            )

            evolution_service._select_catalog_alternative = MagicMock(return_value=None)

            result = await evolution_service._evolve_multi_variable(
                parent=PARENT_AD,
                element_tags=ELEMENT_TAGS,
                parent_image_b64="base64data",
                product_id=PRODUCT_ID,
                brand_id=BRAND_ID,
                selection=self._make_selection(3),
                num_variations=3,
            )

        assert result["child_ad_ids"] == ["child_1", "child_2", "child_3"]
        assert len(result["ad_run_ids"]) == 3
        assert "hook_type" in result["variable_changed"]
        assert result["per_child_lineage"] is not None
        assert len(result["per_child_lineage"]) == 3
        # Verify each child has specific variable info
        assert result["per_child_lineage"][0]["child_ad_id"] == "child_1"
        assert result["per_child_lineage"][0]["variable_changed"] == "hook_type"

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self, evolution_service):
        """If one pipeline fails, others still run."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._analyze_parent_narrative = AsyncMock(return_value="narrative")
        evolution_service._has_visual_conflict = MagicMock(return_value=False)
        evolution_service._build_evolution_instructions = MagicMock(return_value="instructions")

        # Second pipeline fails
        evolution_service._run_v2_pipeline = AsyncMock(
            side_effect=[
                (["child_1"], ["run_1"]),
                RuntimeError("Pipeline exploded"),
                (["child_3"], ["run_3"]),
            ]
        )

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            genome_instance = MockGenome.return_value
            genome_instance.sample_element_scores = MagicMock(
                return_value=[{"value": "new_val"}]
            )
            evolution_service._select_catalog_alternative = MagicMock(return_value=None)

            result = await evolution_service._evolve_multi_variable(
                parent=PARENT_AD,
                element_tags=ELEMENT_TAGS,
                parent_image_b64="base64data",
                product_id=PRODUCT_ID,
                brand_id=BRAND_ID,
                selection=self._make_selection(3),
                num_variations=3,
            )

        assert len(result["child_ad_ids"]) == 2
        assert len(result["per_child_lineage"]) == 2

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, evolution_service):
        """Raises ValueError when all pipelines fail."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._analyze_parent_narrative = AsyncMock(return_value="narrative")
        evolution_service._has_visual_conflict = MagicMock(return_value=False)
        evolution_service._build_evolution_instructions = MagicMock(return_value="instructions")

        evolution_service._run_v2_pipeline = AsyncMock(
            side_effect=RuntimeError("Pipeline exploded")
        )

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            genome_instance = MockGenome.return_value
            genome_instance.sample_element_scores = MagicMock(
                return_value=[{"value": "new_val"}]
            )
            evolution_service._select_catalog_alternative = MagicMock(return_value=None)

            with pytest.raises(ValueError, match="all .* pipelines failed"):
                await evolution_service._evolve_multi_variable(
                    parent=PARENT_AD,
                    element_tags=ELEMENT_TAGS,
                    parent_image_b64="base64data",
                    product_id=PRODUCT_ID,
                    brand_id=BRAND_ID,
                    selection=self._make_selection(3),
                    num_variations=3,
                )

    @pytest.mark.asyncio
    async def test_caps_at_available_candidates(self, evolution_service):
        """num_variations > candidates: caps at len(candidates)."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._analyze_parent_narrative = AsyncMock(return_value="narrative")
        evolution_service._has_visual_conflict = MagicMock(return_value=False)
        evolution_service._build_evolution_instructions = MagicMock(return_value="instructions")

        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["child_1"], ["run_1"])
        )

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            genome_instance = MockGenome.return_value
            genome_instance.sample_element_scores = MagicMock(
                return_value=[{"value": "new_val"}]
            )
            evolution_service._select_catalog_alternative = MagicMock(return_value=None)

            # Only 1 candidate but requesting 5
            result = await evolution_service._evolve_multi_variable(
                parent=PARENT_AD,
                element_tags=ELEMENT_TAGS,
                parent_image_b64="base64data",
                product_id=PRODUCT_ID,
                brand_id=BRAND_ID,
                selection=self._make_selection(1),
                num_variations=5,
            )

        # Only 1 pipeline should run
        assert evolution_service._run_v2_pipeline.call_count == 1
        assert len(result["child_ad_ids"]) == 1

    @pytest.mark.asyncio
    async def test_skip_variable_with_no_alternative(self, evolution_service):
        """Variables with no alternative value are skipped."""
        evolution_service._build_base_pipeline_params = MagicMock(return_value={})
        evolution_service._analyze_parent_narrative = AsyncMock(return_value="narrative")
        evolution_service._has_visual_conflict = MagicMock(return_value=False)
        evolution_service._build_evolution_instructions = MagicMock(return_value="instructions")

        evolution_service._run_v2_pipeline = AsyncMock(
            return_value=(["child_1"], ["run_1"])
        )

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService") as MockGenome:
            genome_instance = MockGenome.return_value
            # First candidate: no alternatives via sampling or catalog
            # Second candidate: has alternatives
            genome_instance.sample_element_scores = MagicMock(
                side_effect=[
                    [{"value": "value_0"}],  # same as parent, no alternative
                    [{"value": "new_val"}],  # different from parent
                ]
            )
            evolution_service._select_catalog_alternative = MagicMock(
                side_effect=[None, None]  # catalog also has nothing for first
            )

            result = await evolution_service._evolve_multi_variable(
                parent=PARENT_AD,
                element_tags=ELEMENT_TAGS,
                parent_image_b64="base64data",
                product_id=PRODUCT_ID,
                brand_id=BRAND_ID,
                selection=self._make_selection(2),
                num_variations=2,
            )

        # Only second pipeline should run (first skipped)
        assert evolution_service._run_v2_pipeline.call_count == 1


# ============================================================================
# evolve_winner routing tests
# ============================================================================

class TestEvolveWinnerRouting:
    @pytest.mark.asyncio
    async def test_custom_edit_requires_prompt(self, evolution_service):
        """custom_edit mode without prompt raises ValueError."""
        # Mock limit check
        evolution_service.check_iteration_limits = AsyncMock(return_value={
            "can_evolve": True,
            "iteration_count": 0,
            "ancestor_round": 0,
        })

        # Build per-table mock chains so each .table("X") returns appropriate data
        def table_side_effect(table_name):
            chain = MagicMock()
            if table_name == "generated_ads":
                chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{**PARENT_AD, "element_tags": ELEMENT_TAGS, "storage_path": "test.png",
                           "hook_id": None, "ad_run_id": "run1", "prompt_version": "v2",
                           "canvas_size": "1080x1080px", "color_mode": "original"}]
                )
            elif table_name == "ad_runs":
                chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"product_id": PRODUCT_ID}]
                )
            elif table_name == "products":
                chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"brand_id": str(BRAND_ID)}]
                )
            return chain

        evolution_service.supabase.table = MagicMock(side_effect=table_side_effect)
        evolution_service.get_ancestor = AsyncMock(return_value=PARENT_AD_ID)

        with patch("viraltracker.services.ad_creation_service.AdCreationService") as MockAdService:
            MockAdService.return_value.download_image = AsyncMock(return_value=b"fake_image")

            with pytest.raises(ValueError, match="requires a custom_prompt"):
                await evolution_service.evolve_winner(
                    parent_ad_id=PARENT_AD_ID,
                    mode="custom_edit",
                    skip_winner_check=True,
                )

    def test_custom_edit_in_evolution_modes(self):
        """custom_edit is a valid evolution mode."""
        assert "custom_edit" in EVOLUTION_MODES
