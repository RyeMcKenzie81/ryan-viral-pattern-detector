"""
Content Pipeline Orchestrator - Pydantic Graph workflow definition.

This module defines the content pipeline graph using pydantic-graph.
The pipeline has 29 steps across shared, video, and comic paths.

Graph Flow:
- Shared (1-6): Topic Discovery → Evaluation → Selection → Script → Review → Approval
- Video (7-15): ELS → Audio → Assets → SEO → Thumbnails → Handoff
- Comic (16-29): Condense → Eval → Image → Audio → Video → SEO → Thumbnails

Human Checkpoints (9 total):
1. Topic Selection (Step 3) - Quick Approve if score > 90
2. Script Approval (Step 6) - Quick Approve if 100% checklist
3. Audio Production (Step 8)
4. Asset Review (Step 12)
5. Metadata Selection (Step 14) - Quick Approve if rank 1 > 90
6. Comic Script Approval (Step 18) - Quick Approve if all > 85
7. Comic Image Review (Step 21) - Quick Approve if eval > 90%
8. Comic Video (Step 25)
9. Comic Thumbnail Selection (Step 29)

Part of the Trash Panda Content Pipeline.
"""

import logging
from dataclasses import dataclass
from typing import Union, Dict, Any
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .state import ContentPipelineState, WorkflowPath, HumanCheckpoint
from ...agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


# =============================================================================
# SHARED PATH NODES (Steps 1-6)
# =============================================================================

@dataclass
class TopicDiscoveryNode(BaseNode[ContentPipelineState]):
    """
    Step 1: Discover trending topics using ChatGPT 5.1 extended thinking.

    Generates a batch of 10-20 topic suggestions based on:
    - Brand bible context
    - Optional focus areas
    - Past performance data (if available)

    Thin wrapper - delegates to TopicDiscoveryService.
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> "TopicEvaluationNode":
        logger.info(f"Step 1: Discovering {ctx.state.topic_batch_size} topics")
        ctx.state.current_step = "topic_discovery"

        try:
            # Delegate to service
            topics = await ctx.deps.content_pipeline.topic_service.discover_topics(
                brand_id=ctx.state.brand_id,
                num_topics=ctx.state.topic_batch_size,
                focus_areas=ctx.state.topic_focus_areas
            )

            ctx.state.topic_suggestions = topics
            ctx.state.mark_step_complete("topic_discovery")

            logger.info(f"Discovered {len(topics)} topics")
            return TopicEvaluationNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "topic_discovery"
            logger.error(f"Topic discovery failed: {e}")
            return End({"status": "error", "error": str(e), "step": "topic_discovery"})


@dataclass
class TopicEvaluationNode(BaseNode[ContentPipelineState]):
    """
    Step 2: Evaluate and score discovered topics.

    Uses ChatGPT 5.1 to score and rank topics with reasoning.
    Marks topics as Quick Approve eligible if score >= 90.

    Thin wrapper - delegates to TopicDiscoveryService.
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> "TopicSelectionNode":
        logger.info(f"Step 2: Evaluating {len(ctx.state.topic_suggestions)} topics")
        ctx.state.current_step = "topic_evaluation"

        try:
            # Delegate to service
            evaluated_topics = await ctx.deps.content_pipeline.topic_service.evaluate_topics(
                topics=ctx.state.topic_suggestions,
                brand_id=ctx.state.brand_id
            )

            # Sort by score descending
            evaluated_topics.sort(key=lambda x: x.get('score', 0), reverse=True)

            # Mark Quick Approve eligibility
            for topic in evaluated_topics:
                topic['quick_approve_eligible'] = (
                    topic.get('score', 0) >= ctx.state.topic_score_threshold
                )

            ctx.state.topic_suggestions = evaluated_topics
            ctx.state.mark_step_complete("topic_evaluation")

            logger.info(f"Evaluated topics, top score: {evaluated_topics[0].get('score', 0) if evaluated_topics else 0}")
            return TopicSelectionNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "topic_evaluation"
            logger.error(f"Topic evaluation failed: {e}")
            return End({"status": "error", "error": str(e), "step": "topic_evaluation"})


@dataclass
class TopicSelectionNode(BaseNode[ContentPipelineState]):
    """
    Step 3: HUMAN CHECKPOINT - Select topic from evaluated list.

    Pauses workflow for human selection. Quick Approve auto-selects
    top topic if its score >= 90 and quick_approve_enabled is True.

    Human can:
    - Select a topic to proceed
    - Request more topics (loops back to TopicDiscoveryNode)
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> Union["ScriptGenerationNode", "TopicDiscoveryNode", End]:
        logger.info("Step 3: Topic Selection (Human Checkpoint)")
        ctx.state.current_step = "topic_selection"
        ctx.state.current_checkpoint = HumanCheckpoint.TOPIC_SELECTION

        # Check for Quick Approve
        if ctx.state.topic_suggestions:
            top_topic = ctx.state.topic_suggestions[0]
            top_score = top_topic.get('score', 0)

            if ctx.state.is_quick_approve_eligible(HumanCheckpoint.TOPIC_SELECTION, top_score):
                logger.info(f"Quick Approve: Auto-selecting topic with score {top_score}")
                ctx.state.selected_topic = top_topic
                ctx.state.selected_topic_id = top_topic.get('id')
                ctx.state.awaiting_human = False
                ctx.state.mark_step_complete("topic_selection")
                return ScriptGenerationNode()

        # Otherwise, pause for human input
        if not ctx.state.human_input:
            ctx.state.awaiting_human = True
            return End({
                "status": "awaiting_human",
                "checkpoint": "topic_selection",
                "topics": ctx.state.topic_suggestions,
                "message": "Please select a topic or request more options"
            })

        # Process human input
        human_input = ctx.state.human_input
        ctx.state.human_input = None  # Clear for next checkpoint

        if human_input.get("action") == "request_more":
            logger.info("Human requested more topics")
            ctx.state.topic_focus_areas = human_input.get("focus_areas")
            return TopicDiscoveryNode()

        if human_input.get("action") == "select":
            selected_id = human_input.get("topic_id")
            for topic in ctx.state.topic_suggestions:
                if str(topic.get('id')) == str(selected_id):
                    ctx.state.selected_topic = topic
                    ctx.state.selected_topic_id = UUID(str(selected_id))
                    break

            if not ctx.state.selected_topic:
                ctx.state.error = f"Topic {selected_id} not found"
                return End({"status": "error", "error": ctx.state.error})

            ctx.state.awaiting_human = False
            ctx.state.mark_step_complete("topic_selection")
            logger.info(f"Topic selected: {ctx.state.selected_topic.get('title')}")
            return ScriptGenerationNode()

        return End({"status": "error", "error": "Invalid human input"})


@dataclass
class ScriptGenerationNode(BaseNode[ContentPipelineState]):
    """
    Step 4: Generate full script using Claude Opus 4.5.

    Creates script content and storyboard based on:
    - Selected topic
    - Brand bible context
    - YouTube best practices from KB

    Thin wrapper - delegates to ScriptGenerationService.
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> "ScriptReviewNode":
        logger.info(f"Step 4: Generating script for '{ctx.state.selected_topic.get('title')}'")
        ctx.state.current_step = "script_generation"

        try:
            # Delegate to service
            script_version = await ctx.deps.content_pipeline.script_service.generate_script(
                project_id=ctx.state.project_id,
                topic=ctx.state.selected_topic,
                revision_notes=ctx.state.script_revision_notes
            )

            ctx.state.script_version_ids.append(script_version['id'])
            ctx.state.current_script_version_id = script_version['id']
            ctx.state.script_revision_notes = None  # Clear after use
            ctx.state.mark_step_complete("script_generation")

            logger.info(f"Generated script version {script_version.get('version_number')}")
            return ScriptReviewNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "script_generation"
            logger.error(f"Script generation failed: {e}")
            return End({"status": "error", "error": str(e), "step": "script_generation"})


@dataclass
class ScriptReviewNode(BaseNode[ContentPipelineState]):
    """
    Step 5: Review script against bible checklist.

    Uses Claude Opus 4.5 to check script against brand bible
    checklist items. Returns pass/fail for each item.

    Thin wrapper - delegates to ScriptGenerationService.
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> "ScriptApprovalNode":
        logger.info("Step 5: Reviewing script against bible checklist")
        ctx.state.current_step = "script_review"

        try:
            # Delegate to service
            review_result = await ctx.deps.content_pipeline.script_service.review_script(
                script_version_id=ctx.state.current_script_version_id
            )

            ctx.state.bible_checklist_results = review_result
            ctx.state.mark_step_complete("script_review")

            pass_rate = review_result.get('pass_rate', 0)
            logger.info(f"Script review complete: {pass_rate}% checklist pass rate")
            return ScriptApprovalNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "script_review"
            logger.error(f"Script review failed: {e}")
            return End({"status": "error", "error": str(e), "step": "script_review"})


@dataclass
class ScriptApprovalNode(BaseNode[ContentPipelineState]):
    """
    Step 6: HUMAN CHECKPOINT - Approve script or request revisions.

    Pauses workflow for human approval. Quick Approve auto-approves
    if checklist pass rate is 100% and quick_approve_enabled is True.

    Human can:
    - Approve script (proceeds to ELS conversion)
    - Request revisions with notes (loops back to ScriptGenerationNode)
    """

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> Union["ELSConversionNode", "ScriptGenerationNode", End]:
        logger.info("Step 6: Script Approval (Human Checkpoint)")
        ctx.state.current_step = "script_approval"
        ctx.state.current_checkpoint = HumanCheckpoint.SCRIPT_APPROVAL

        # Check for Quick Approve
        pass_rate = ctx.state.bible_checklist_results.get('pass_rate', 0) if ctx.state.bible_checklist_results else 0
        if ctx.state.is_quick_approve_eligible(HumanCheckpoint.SCRIPT_APPROVAL, pass_rate):
            logger.info(f"Quick Approve: Auto-approving script with {pass_rate}% pass rate")
            ctx.state.awaiting_human = False
            ctx.state.mark_step_complete("script_approval")
            return ELSConversionNode()

        # Otherwise, pause for human input
        if not ctx.state.human_input:
            ctx.state.awaiting_human = True
            return End({
                "status": "awaiting_human",
                "checkpoint": "script_approval",
                "script_version_id": str(ctx.state.current_script_version_id),
                "checklist_results": ctx.state.bible_checklist_results,
                "message": "Please review and approve the script or request revisions"
            })

        # Process human input
        human_input = ctx.state.human_input
        ctx.state.human_input = None

        if human_input.get("action") == "approve":
            ctx.state.awaiting_human = False
            ctx.state.mark_step_complete("script_approval")
            logger.info("Script approved by human")
            return ELSConversionNode()

        if human_input.get("action") == "revise":
            ctx.state.script_revision_notes = human_input.get("notes", "")
            logger.info("Revision requested, looping back to script generation")
            return ScriptGenerationNode()

        return End({"status": "error", "error": "Invalid human input"})


# =============================================================================
# VIDEO PATH NODES (Steps 7-15)
# Placeholder implementations - will be built in later MVPs
# =============================================================================

@dataclass
class ELSConversionNode(BaseNode[ContentPipelineState]):
    """Step 7: Convert script to ELS format."""

    async def run(
        self,
        ctx: GraphRunContext[ContentPipelineState, AgentDependencies]
    ) -> End:
        logger.info("Step 7: ELS Conversion (Not yet implemented)")
        ctx.state.current_step = "els_conversion"

        # TODO: Implement in MVP 3
        return End({
            "status": "awaiting_implementation",
            "step": "els_conversion",
            "message": "ELS conversion not yet implemented. Video path continues in MVP 3."
        })


# =============================================================================
# BUILD THE GRAPH
# =============================================================================

# MVP 1: Topic Discovery only
content_pipeline_graph_mvp1 = Graph(
    nodes=(
        TopicDiscoveryNode,
        TopicEvaluationNode,
        TopicSelectionNode,
    ),
    name="content_pipeline_mvp1"
)

# MVP 2: Through Script Approval
content_pipeline_graph_mvp2 = Graph(
    nodes=(
        TopicDiscoveryNode,
        TopicEvaluationNode,
        TopicSelectionNode,
        ScriptGenerationNode,
        ScriptReviewNode,
        ScriptApprovalNode,
        ELSConversionNode,
    ),
    name="content_pipeline_mvp2"
)

# Full graph will be added in later phases
content_pipeline_graph = content_pipeline_graph_mvp2


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def run_topic_discovery(
    brand_id: UUID,
    num_topics: int = 10,
    focus_areas: list = None,
    quick_approve_enabled: bool = True
) -> Dict[str, Any]:
    """
    Run topic discovery pipeline (MVP 1).

    This runs Steps 1-3 (discovery, evaluation, selection).
    If quick_approve_enabled and top topic scores >= 90,
    it auto-selects and returns immediately.

    Args:
        brand_id: Brand UUID
        num_topics: Number of topics to discover (default 10)
        focus_areas: Optional focus areas for discovery
        quick_approve_enabled: Whether to auto-approve high scores

    Returns:
        Pipeline result with topics and selection status
    """
    from ...agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    result = await content_pipeline_graph_mvp1.run(
        TopicDiscoveryNode(),
        state=ContentPipelineState(
            brand_id=brand_id,
            topic_batch_size=num_topics,
            topic_focus_areas=focus_areas,
            quick_approve_enabled=quick_approve_enabled
        ),
        deps=deps
    )

    return result.output


async def resume_pipeline(
    project_id: UUID,
    human_input: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Resume pipeline from human checkpoint.

    Loads state from database, applies human input,
    and continues execution from the current checkpoint.

    Args:
        project_id: Content project UUID
        human_input: Human decision at checkpoint

    Returns:
        Pipeline result
    """
    from ...agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    # Load state from database
    state_dict = await deps.content_pipeline.load_project_state(project_id)
    state = ContentPipelineState.from_dict(state_dict)
    state.human_input = human_input

    # Determine which node to resume from
    checkpoint_to_node = {
        HumanCheckpoint.TOPIC_SELECTION: TopicSelectionNode,
        HumanCheckpoint.SCRIPT_APPROVAL: ScriptApprovalNode,
        # More mappings added as nodes are implemented
    }

    resume_node_class = checkpoint_to_node.get(state.current_checkpoint)
    if not resume_node_class:
        return {"status": "error", "error": f"Unknown checkpoint: {state.current_checkpoint}"}

    result = await content_pipeline_graph.run(
        resume_node_class(),
        state=state,
        deps=deps
    )

    # Save updated state to database
    await deps.content_pipeline.save_project_state(project_id, state.to_dict())

    return result.output
