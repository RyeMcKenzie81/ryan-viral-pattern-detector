"""
CompileResultsNode V2 - Compile final results and update ad_run status.

V2 changes from V1:
- Includes pipeline_version: "v2" in result dict
- Includes prompt_version in result dict
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Dict, Any
from uuid import UUID

from pydantic_graph import BaseNode, End, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class CompileResultsNode(BaseNode[AdCreationPipelineState]):
    """
    Step 8: Compile final results and mark workflow complete.

    Counts approved/rejected/flagged ads, builds summary, updates ad_run status.
    V2: Includes pipeline_version and prompt_version in output.

    Reads: reviewed_ads, product_dict, ad_analysis, content_source, template_angle,
           selected_hooks, reference_ad_path, ad_run_id, angle_data, num_variations,
           pipeline_version, prompt_version
    Writes: (none - returns End with result dict)
    Services: AdCreationService.update_ad_run()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["reviewed_ads", "product_dict", "ad_run_id", "content_source",
                "pipeline_version", "prompt_version"],
        outputs=[],
        services=["ad_creation.update_ad_run"],
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> End[Dict[str, Any]]:
        logger.info("Step 8: Compiling final results (V2)...")
        ctx.state.current_step = "compile_results"

        reviewed_ads = ctx.state.reviewed_ads

        # Count statuses
        approved_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'approved')
        rejected_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'rejected')
        flagged_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'flagged')
        generation_failed_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'generation_failed')
        review_failed_count = sum(1 for ad in reviewed_ads if ad['final_status'] == 'review_failed')

        # Build summary
        content_source_labels = {
            "hooks": "hooks",
            "recreate_template": "template recreation (benefits/USPs)",
            "belief_first": f"belief-first angle: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
            "plan": f"belief plan: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
            "angles": f"direct angles: {ctx.state.angle_data.get('name', 'Unknown') if ctx.state.angle_data else 'Unknown'}",
        }
        content_source_label = content_source_labels.get(
            ctx.state.content_source, ctx.state.content_source
        )

        total_requested = (ctx.state.num_variations
                          * len(ctx.state.canvas_sizes)
                          * len(ctx.state.color_modes))

        summary_parts = [
            f"Ad creation V2 workflow completed for {ctx.state.product_dict.get('name')}.",
            "",
            f"**Pipeline Version:** {ctx.state.pipeline_version}",
            f"**Prompt Version:** {ctx.state.prompt_version}",
            f"**Content Source:** {content_source_label}",
            f"**Canvas Sizes:** {', '.join(ctx.state.canvas_sizes)}",
            f"**Color Modes:** {', '.join(ctx.state.color_modes)}",
            "",
            "**Results:**",
            f"- Total ads requested: {ctx.state.num_variations} variations x "
            f"{len(ctx.state.canvas_sizes)} size(s) x {len(ctx.state.color_modes)} color(s) "
            f"= {total_requested}",
            f"- Approved (production-ready): {approved_count}",
            f"- Rejected (both reviewers): {rejected_count}",
            f"- Flagged (reviewer disagreement): {flagged_count}",
            f"- Generation failed: {generation_failed_count}",
            f"- Review failed: {review_failed_count}",
            "",
            "**Next Steps:**",
        ]

        if approved_count > 0:
            summary_parts.append(f"- {approved_count} ads ready for immediate use")
        if (flagged_count + review_failed_count) > 0:
            summary_parts.append(f"- {flagged_count + review_failed_count} ads require human review")
        if (rejected_count + generation_failed_count) > 0:
            summary_parts.append(f"- {rejected_count + generation_failed_count} ads should be regenerated")

        summary = "\n".join(summary_parts)

        # Phase 8A: Track element combo usage for fatigue scoring
        await self._record_combo_usage(ctx, reviewed_ads)

        # Phase 8B: Record selection weight snapshot (for scorer weight learning)
        await self._record_selection_snapshot(ctx)

        # Phase 8B: Record generation experiment outcome
        await self._record_experiment_outcome(ctx, reviewed_ads)

        # Mark workflow complete
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ctx.state.ad_run_id),
            status="complete"
        )

        result = {
            "ad_run_id": ctx.state.ad_run_id,
            "product": ctx.state.product_dict,
            "reference_ad_path": ctx.state.reference_ad_path,
            "ad_analysis": ctx.state.ad_analysis,
            "content_source": ctx.state.content_source,
            "template_angle": ctx.state.template_angle,
            "selected_hooks": ctx.state.selected_hooks,
            "generated_ads": reviewed_ads,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "flagged_count": flagged_count,
            "summary": summary,
            "created_at": datetime.now().isoformat(),
            "pipeline_version": ctx.state.pipeline_version,
            "prompt_version": ctx.state.prompt_version,
        }

        ctx.state.mark_step_complete("compile_results")
        logger.info(f"=== V2 WORKFLOW COMPLETE: {approved_count} approved, "
                    f"{rejected_count} rejected, {flagged_count} flagged ===")

        return End(result)

    async def _record_selection_snapshot(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies],
    ) -> None:
        """Record selection-time weights and scores for scorer weight learning (Phase 8B)."""
        if not ctx.state.selection_weights_used or not ctx.state.selection_scorer_breakdown:
            return

        try:
            from viraltracker.services.scorer_weight_learning_service import ScorerWeightLearningService
            brand_id = str(ctx.state.product_dict.get("brand_id", ""))
            if not brand_id or not ctx.state.ad_run_id:
                return

            learning_service = ScorerWeightLearningService()
            learning_service.record_selection_snapshot(
                brand_id=UUID(brand_id),
                ad_run_id=ctx.state.ad_run_id,
                template_id=ctx.state.template_id,
                weights_used=ctx.state.selection_weights_used,
                scorer_breakdown=ctx.state.selection_scorer_breakdown,
                composite_score=ctx.state.selection_composite_score,
                selection_mode=ctx.state.selection_mode,
            )
            logger.info(f"Recorded selection snapshot for run {ctx.state.ad_run_id}")
        except Exception as e:
            logger.warning(f"Failed to record selection snapshot: {e}")

    async def _record_experiment_outcome(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies],
        reviewed_ads: list,
    ) -> None:
        """Record generation experiment outcome (Phase 8B)."""
        if not ctx.state.generation_experiment_id or not ctx.state.ad_run_id:
            return

        try:
            from viraltracker.services.generation_experiment_service import GenerationExperimentService

            approved = sum(1 for ad in reviewed_ads if ad.get('final_status') == 'approved')
            rejected = sum(1 for ad in reviewed_ads if ad.get('final_status') == 'rejected')
            flagged = sum(1 for ad in reviewed_ads if ad.get('final_status') == 'flagged')
            gen_failed = sum(1 for ad in reviewed_ads if ad.get('final_status') == 'generation_failed')
            total_generated = len(reviewed_ads) - gen_failed

            # Compute defects from defect scan results
            defects = sum(
                len(ad.get("defects", []))
                for ad in reviewed_ads
                if ad.get("defects")
            )

            # Compute avg review score
            review_scores = [
                ad.get("review_score", 0)
                for ad in reviewed_ads
                if ad.get("review_score") is not None and ad.get("final_status") != "generation_failed"
            ]
            avg_score = sum(review_scores) / len(review_scores) if review_scores else None

            gen_exp_service = GenerationExperimentService()
            gen_exp_service.record_outcome(
                experiment_id=ctx.state.generation_experiment_id,
                arm=ctx.state.generation_experiment_arm,
                ad_run_id=ctx.state.ad_run_id,
                metrics={
                    "ads_generated": total_generated,
                    "ads_approved": approved,
                    "ads_rejected": rejected,
                    "ads_flagged": flagged,
                    "defects_found": defects,
                    "avg_review_score": avg_score,
                },
            )
            logger.info(
                f"Recorded experiment outcome: {ctx.state.generation_experiment_arm} arm "
                f"for experiment {ctx.state.generation_experiment_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to record experiment outcome: {e}")

    async def _record_combo_usage(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies],
        reviewed_ads: list,
    ) -> None:
        """Record element combo usage for fatigue scoring (Phase 8A).

        Uses idempotent upsert with last_ad_run_id dedup to prevent
        double-counting on retries.
        """
        from viraltracker.core.database import get_supabase_client

        try:
            db = get_supabase_client()
            ad_run_id = ctx.state.ad_run_id
            brand_id = str(ctx.state.product_dict.get("brand_id", ""))
            product_id = str(ctx.state.product_dict.get("id", ""))
            now = datetime.now().isoformat()

            if not brand_id:
                return

            combo_count = 0
            for ad in reviewed_ads:
                if ad.get("final_status") == "generation_failed":
                    continue

                # Extract element tags from the ad
                prompt = ad.get("prompt") or {}
                element_tags = prompt.get("element_tags") or ad.get("element_tags") or {}

                # Build combo parts from tracked elements
                combo_parts = {}
                for elem in ["hook_type", "color_mode", "template_category", "awareness_stage"]:
                    val = element_tags.get(elem) or ad.get(elem)
                    if val:
                        combo_parts[elem] = str(val)

                if not combo_parts:
                    continue

                # Build canonical combo key (sorted)
                combo_key = "|".join(
                    f"{k}={v}" for k, v in sorted(combo_parts.items())
                )

                # Idempotent upsert with last_ad_run_id dedup
                db.rpc("exec_sql", {"query": f"""
                    INSERT INTO element_combo_usage (
                        brand_id, product_id, combo_key, hook_type,
                        color_mode, template_category, awareness_stage,
                        last_used_at, times_used, last_ad_run_id
                    )
                    VALUES (
                        {_sql_val(brand_id)}, {_sql_val(product_id)}, {_sql_val(combo_key)},
                        {_sql_val(combo_parts.get('hook_type'))},
                        {_sql_val(combo_parts.get('color_mode'))},
                        {_sql_val(combo_parts.get('template_category'))},
                        {_sql_val(combo_parts.get('awareness_stage'))},
                        {_sql_val(now)}, 1, {_sql_val(ad_run_id)}
                    )
                    ON CONFLICT (brand_id, (COALESCE(product_id, '00000000-0000-0000-0000-000000000000'::uuid)), combo_key) DO UPDATE SET
                        last_used_at = GREATEST(element_combo_usage.last_used_at, EXCLUDED.last_used_at),
                        times_used = CASE
                            WHEN element_combo_usage.last_ad_run_id IS DISTINCT FROM EXCLUDED.last_ad_run_id
                            THEN element_combo_usage.times_used + 1
                            ELSE element_combo_usage.times_used
                        END,
                        last_ad_run_id = EXCLUDED.last_ad_run_id
                """}).execute()
                combo_count += 1

            if combo_count > 0:
                logger.info(f"Recorded {combo_count} element combo usages for run {ad_run_id}")

        except Exception as e:
            # Non-fatal: combo tracking failure shouldn't block pipeline
            logger.warning(f"Failed to record combo usage: {e}")


def _sql_val(val: str | None) -> str:
    """Format a value for SQL insertion, handling None as NULL."""
    if val is None:
        return "NULL"
    # Escape single quotes for SQL safety
    escaped = val.replace("'", "''")
    return f"'{escaped}'"
