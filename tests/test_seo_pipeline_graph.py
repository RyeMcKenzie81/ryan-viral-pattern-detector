"""
Tests for SEO Pipeline Graph — nodes, orchestrator, human checkpoints, and error handling.

Tests cover:
- Each node's happy-path behavior with mocked services
- Human checkpoint pause/resume logic (4 checkpoints)
- Error handling in nodes (service failure → End with error)
- Orchestrator entry/resume functions
- State persistence (save/load)
- Graph definition completeness
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from pydantic_graph import End

from viraltracker.services.seo_pipeline.state import SEOPipelineState, SEOHumanCheckpoint
from viraltracker.services.seo_pipeline.nodes import (
    KeywordDiscoveryNode,
    KeywordSelectionNode,
    CompetitorAnalysisNode,
    ContentPhaseANode,
    OutlineReviewNode,
    ContentPhaseBNode,
    ContentPhaseCNode,
    ArticleReviewNode,
    QAValidationNode,
    QAApprovalNode,
    ImageGenerationNode,
    PublishNode,
    InterlinkingNode,
)
from viraltracker.services.seo_pipeline.orchestrator import (
    seo_pipeline_graph,
    CHECKPOINT_TO_NODE,
    get_pipeline_status,
)

# Patch paths — services are imported inside run() from their source modules
KW_DISCOVERY_SVC = "viraltracker.services.seo_pipeline.services.keyword_discovery_service.KeywordDiscoveryService"
COMPETITOR_SVC = "viraltracker.services.seo_pipeline.services.competitor_analysis_service.CompetitorAnalysisService"
CONTENT_GEN_SVC = "viraltracker.services.seo_pipeline.services.content_generation_service.ContentGenerationService"
QA_SVC = "viraltracker.services.seo_pipeline.services.qa_validation_service.QAValidationService"
CMS_SVC = "viraltracker.services.seo_pipeline.services.cms_publisher_service.CMSPublisherService"
INTERLINK_SVC = "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def base_state():
    """Base pipeline state with required fields."""
    return SEOPipelineState(
        project_id=UUID("11111111-1111-1111-1111-111111111111"),
        brand_id=UUID("22222222-2222-2222-2222-222222222222"),
        organization_id=UUID("33333333-3333-3333-3333-333333333333"),
        seed_keywords=["gaming pc", "build gaming computer"],
    )


@pytest.fixture
def mock_ctx(base_state):
    """Mock GraphRunContext with state."""
    ctx = MagicMock()
    ctx.state = base_state
    return ctx


# =============================================================================
# GRAPH DEFINITION
# =============================================================================

class TestGraphDefinition:
    def test_graph_has_all_nodes(self):
        """Verify graph contains all 13 node types."""
        assert len(seo_pipeline_graph.node_defs) == 13

    def test_graph_name(self):
        assert seo_pipeline_graph.name == "seo_content_pipeline"

    def test_checkpoint_to_node_mapping(self):
        """All human checkpoints should map to a node."""
        for checkpoint in SEOHumanCheckpoint:
            assert checkpoint in CHECKPOINT_TO_NODE
            assert CHECKPOINT_TO_NODE[checkpoint] is not None

    def test_all_nodes_importable(self):
        """Ensure all nodes are importable from the package."""
        from viraltracker.services.seo_pipeline.nodes import (
            KeywordDiscoveryNode,
            KeywordSelectionNode,
            CompetitorAnalysisNode,
            ContentPhaseANode,
            OutlineReviewNode,
            ContentPhaseBNode,
            ContentPhaseCNode,
            ArticleReviewNode,
            QAValidationNode,
            QAApprovalNode,
            PublishNode,
            InterlinkingNode,
        )
        assert all(isinstance(cls, type) for cls in [
            KeywordDiscoveryNode, KeywordSelectionNode, CompetitorAnalysisNode,
            ContentPhaseANode, OutlineReviewNode, ContentPhaseBNode,
            ContentPhaseCNode, ArticleReviewNode, QAValidationNode,
            QAApprovalNode, PublishNode, InterlinkingNode,
        ])

    def test_graph_node_names(self):
        """Verify all expected node names are in the graph."""
        expected = {
            "KeywordDiscoveryNode", "KeywordSelectionNode", "CompetitorAnalysisNode",
            "ContentPhaseANode", "OutlineReviewNode", "ContentPhaseBNode",
            "ContentPhaseCNode", "ArticleReviewNode", "QAValidationNode",
            "QAApprovalNode", "ImageGenerationNode", "PublishNode", "InterlinkingNode",
        }
        actual = set(seo_pipeline_graph.node_defs.keys())
        assert actual == expected


# =============================================================================
# NODE METADATA
# =============================================================================

class TestNodeMetadata:
    def test_all_nodes_have_metadata(self):
        """Every node should define ClassVar metadata."""
        nodes = [
            KeywordDiscoveryNode, KeywordSelectionNode, CompetitorAnalysisNode,
            ContentPhaseANode, OutlineReviewNode, ContentPhaseBNode,
            ContentPhaseCNode, ArticleReviewNode, QAValidationNode,
            QAApprovalNode, PublishNode, InterlinkingNode,
        ]
        for node_cls in nodes:
            assert hasattr(node_cls, "metadata"), f"{node_cls.__name__} missing metadata"
            assert node_cls.metadata.inputs is not None
            assert node_cls.metadata.outputs is not None

    def test_llm_nodes_annotated(self):
        """Nodes using LLMs should have llm/llm_purpose metadata."""
        llm_nodes = [ContentPhaseANode, ContentPhaseBNode, ContentPhaseCNode]
        for node_cls in llm_nodes:
            assert node_cls.metadata.llm is not None, f"{node_cls.__name__} missing llm"
            assert node_cls.metadata.llm_purpose is not None, f"{node_cls.__name__} missing llm_purpose"


# =============================================================================
# KEYWORD DISCOVERY NODE
# =============================================================================

class TestKeywordDiscoveryNode:
    @pytest.mark.asyncio
    async def test_successful_discovery(self, mock_ctx):
        node = KeywordDiscoveryNode()

        with patch(KW_DISCOVERY_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.discover_keywords = AsyncMock(return_value=[
                {"id": "kw-1", "keyword": "best gaming pc 2026", "word_count": 4},
                {"id": "kw-2", "keyword": "how to build gaming pc", "word_count": 5},
            ])

            result = await node.run(mock_ctx)

        assert not isinstance(result, End)
        assert isinstance(result, KeywordSelectionNode)
        assert len(mock_ctx.state.discovered_keywords) == 2
        assert "keyword_discovery" in mock_ctx.state.steps_completed

    @pytest.mark.asyncio
    async def test_discovery_failure(self, mock_ctx):
        node = KeywordDiscoveryNode()

        with patch(KW_DISCOVERY_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.discover_keywords = AsyncMock(side_effect=Exception("API error"))

            result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.error == "API error"
        assert mock_ctx.state.error_step == "keyword_discovery"


# =============================================================================
# KEYWORD SELECTION NODE (HUMAN CHECKPOINT)
# =============================================================================

class TestKeywordSelectionNode:
    @pytest.mark.asyncio
    async def test_pause_for_selection(self, mock_ctx):
        mock_ctx.state.discovered_keywords = [{"id": "kw-1", "keyword": "test"}]
        mock_ctx.state.human_input = None
        node = KeywordSelectionNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.awaiting_human is True
        assert mock_ctx.state.current_checkpoint == SEOHumanCheckpoint.KEYWORD_SELECTION

    @pytest.mark.asyncio
    async def test_resume_with_selection(self, mock_ctx):
        mock_ctx.state.discovered_keywords = [
            {"id": "kw-1", "keyword": "best gaming pc 2026"},
        ]
        mock_ctx.state.human_input = {
            "action": "select",
            "keyword_id": "kw-1",
            "keyword": "best gaming pc 2026",
        }
        node = KeywordSelectionNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, CompetitorAnalysisNode)
        assert mock_ctx.state.selected_keyword == "best gaming pc 2026"
        assert mock_ctx.state.awaiting_human is False

    @pytest.mark.asyncio
    async def test_resume_with_competitor_urls(self, mock_ctx):
        mock_ctx.state.discovered_keywords = [{"id": "kw-1", "keyword": "test"}]
        mock_ctx.state.human_input = {
            "action": "select",
            "keyword_id": "kw-1",
            "keyword": "test",
            "competitor_urls": ["https://example.com/article1"],
        }
        node = KeywordSelectionNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, CompetitorAnalysisNode)
        assert mock_ctx.state.competitor_urls == ["https://example.com/article1"]

    @pytest.mark.asyncio
    async def test_rediscover_action(self, mock_ctx):
        mock_ctx.state.human_input = {
            "action": "rediscover",
            "seed_keywords": ["new seed"],
        }
        node = KeywordSelectionNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, KeywordDiscoveryNode)
        assert mock_ctx.state.seed_keywords == ["new seed"]

    @pytest.mark.asyncio
    async def test_invalid_action(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "invalid_action"}
        node = KeywordSelectionNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)


# =============================================================================
# COMPETITOR ANALYSIS NODE
# =============================================================================

class TestCompetitorAnalysisNode:
    @pytest.mark.asyncio
    async def test_successful_analysis(self, mock_ctx):
        mock_ctx.state.selected_keyword = "best gaming pc"
        mock_ctx.state.selected_keyword_id = UUID("55555555-5555-5555-5555-555555555555")
        mock_ctx.state.competitor_urls = ["https://example.com/1", "https://example.com/2"]
        node = CompetitorAnalysisNode()

        with patch(COMPETITOR_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.analyze_urls = MagicMock(return_value={
                "results": [
                    {"url": "https://example.com/1", "word_count": 2000},
                    {"url": "https://example.com/2", "word_count": 1800},
                ],
                "winning_formula": {"target_word_count": 2500},
                "analyzed_count": 2,
                "failed_count": 0,
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseANode)
        assert len(mock_ctx.state.competitor_results) == 2
        assert mock_ctx.state.winning_formula is not None
        mock_service.analyze_urls.assert_called_once_with(
            keyword_id="55555555-5555-5555-5555-555555555555",
            urls=["https://example.com/1", "https://example.com/2"],
        )

    @pytest.mark.asyncio
    async def test_partial_failure(self, mock_ctx):
        mock_ctx.state.selected_keyword = "test"
        mock_ctx.state.selected_keyword_id = UUID("55555555-5555-5555-5555-555555555555")
        mock_ctx.state.competitor_urls = ["https://good.com", "https://bad.com"]
        node = CompetitorAnalysisNode()

        with patch(COMPETITOR_SVC) as MockService:
            mock_service = MockService.return_value
            # analyze_urls handles partial failures internally
            mock_service.analyze_urls = MagicMock(return_value={
                "results": [{"url": "https://good.com", "word_count": 2000}],
                "winning_formula": {},
                "analyzed_count": 1,
                "failed_count": 1,
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseANode)
        assert len(mock_ctx.state.competitor_results) == 1

    @pytest.mark.asyncio
    async def test_no_competitor_urls(self, mock_ctx):
        mock_ctx.state.selected_keyword = "test"
        mock_ctx.state.selected_keyword_id = None
        mock_ctx.state.competitor_urls = []
        node = CompetitorAnalysisNode()

        with patch(COMPETITOR_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.analyze_urls = MagicMock(return_value={
                "results": [],
                "winning_formula": {},
                "analyzed_count": 0,
                "failed_count": 0,
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseANode)
        assert mock_ctx.state.competitor_results == []


# =============================================================================
# CONTENT GENERATION NODES
# =============================================================================

class TestContentPhaseANode:
    @pytest.mark.asyncio
    async def test_creates_article_and_runs(self, mock_ctx):
        mock_ctx.state.selected_keyword = "test keyword"
        mock_ctx.state.article_id = None
        node = ContentPhaseANode()

        with patch(CONTENT_GEN_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.create_article = MagicMock(return_value={
                "id": "44444444-4444-4444-4444-444444444444"
            })
            mock_service.generate_phase_a = MagicMock(return_value={"content": "# Outline here"})

            result = await node.run(mock_ctx)

        assert isinstance(result, OutlineReviewNode)
        assert mock_ctx.state.article_id is not None
        assert mock_ctx.state.phase_a_output == "# Outline here"

    @pytest.mark.asyncio
    async def test_uses_existing_article(self, mock_ctx):
        mock_ctx.state.selected_keyword = "test"
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = ContentPhaseANode()

        with patch(CONTENT_GEN_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.generate_phase_a = MagicMock(return_value={"content": "outline"})

            result = await node.run(mock_ctx)

        mock_service.create_article.assert_not_called()
        assert isinstance(result, OutlineReviewNode)

    @pytest.mark.asyncio
    async def test_phase_a_failure(self, mock_ctx):
        mock_ctx.state.selected_keyword = "test"
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = ContentPhaseANode()

        with patch(CONTENT_GEN_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.generate_phase_a = MagicMock(side_effect=Exception("LLM timeout"))

            result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.error == "LLM timeout"


class TestOutlineReviewNode:
    @pytest.mark.asyncio
    async def test_pause_for_review(self, mock_ctx):
        mock_ctx.state.phase_a_output = "# Outline"
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        mock_ctx.state.human_input = None
        node = OutlineReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.awaiting_human is True
        assert mock_ctx.state.current_checkpoint == SEOHumanCheckpoint.OUTLINE_REVIEW

    @pytest.mark.asyncio
    async def test_approve(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "approve"}
        node = OutlineReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseBNode)
        assert mock_ctx.state.awaiting_human is False

    @pytest.mark.asyncio
    async def test_regenerate(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "regenerate"}
        node = OutlineReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseANode)


class TestContentPhaseBNode:
    @pytest.mark.asyncio
    async def test_runs_phase_b(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = ContentPhaseBNode()

        with patch(CONTENT_GEN_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.generate_phase_b = MagicMock(return_value={"content": "Full article draft"})

            result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseCNode)
        assert mock_ctx.state.phase_b_output == "Full article draft"


class TestContentPhaseCNode:
    @pytest.mark.asyncio
    async def test_runs_phase_c(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = ContentPhaseCNode()

        with patch(CONTENT_GEN_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.generate_phase_c = MagicMock(return_value={"content": "SEO-optimized article"})

            result = await node.run(mock_ctx)

        assert isinstance(result, ArticleReviewNode)
        assert mock_ctx.state.phase_c_output == "SEO-optimized article"


# =============================================================================
# ARTICLE REVIEW NODE (HUMAN CHECKPOINT)
# =============================================================================

class TestArticleReviewNode:
    @pytest.mark.asyncio
    async def test_pause_for_review(self, mock_ctx):
        mock_ctx.state.phase_c_output = "# Optimized article"
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        mock_ctx.state.human_input = None
        node = ArticleReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.awaiting_human is True
        assert mock_ctx.state.current_checkpoint == SEOHumanCheckpoint.ARTICLE_REVIEW

    @pytest.mark.asyncio
    async def test_approve(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "approve"}
        node = ArticleReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, QAValidationNode)

    @pytest.mark.asyncio
    async def test_regenerate(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "regenerate"}
        node = ArticleReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseCNode)

    @pytest.mark.asyncio
    async def test_restart(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "restart"}
        node = ArticleReviewNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseANode)


# =============================================================================
# QA VALIDATION NODE
# =============================================================================

class TestQAValidationNode:
    @pytest.mark.asyncio
    async def test_successful_qa(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = QAValidationNode()

        with patch(QA_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.validate_article = MagicMock(return_value={
                "passed": True, "checks": [], "errors": 0, "warnings": 0,
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, QAApprovalNode)
        assert mock_ctx.state.qa_result["passed"] is True

    @pytest.mark.asyncio
    async def test_qa_failure(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = QAValidationNode()

        with patch(QA_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.validate_article = MagicMock(return_value={
                "passed": False, "errors": 2, "warnings": 1,
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, QAApprovalNode)
        assert mock_ctx.state.qa_result["passed"] is False


# =============================================================================
# QA APPROVAL NODE (HUMAN CHECKPOINT)
# =============================================================================

class TestQAApprovalNode:
    @pytest.mark.asyncio
    async def test_pause_for_approval(self, mock_ctx):
        mock_ctx.state.qa_result = {"passed": True, "errors": 0}
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        mock_ctx.state.human_input = None
        node = QAApprovalNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.awaiting_human is True
        assert mock_ctx.state.current_checkpoint == SEOHumanCheckpoint.QA_APPROVAL

    @pytest.mark.asyncio
    async def test_approve_passed_qa(self, mock_ctx):
        mock_ctx.state.qa_result = {"passed": True, "errors": 0}
        mock_ctx.state.human_input = {"action": "approve"}
        node = QAApprovalNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ImageGenerationNode)

    @pytest.mark.asyncio
    async def test_approve_failed_qa_blocked(self, mock_ctx):
        mock_ctx.state.qa_result = {"passed": False, "errors": 2}
        mock_ctx.state.human_input = {"action": "approve"}
        node = QAApprovalNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, End)

    @pytest.mark.asyncio
    async def test_override_failed_qa(self, mock_ctx):
        mock_ctx.state.qa_result = {"passed": False, "errors": 2}
        mock_ctx.state.human_input = {"action": "override"}
        node = QAApprovalNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ImageGenerationNode)

    @pytest.mark.asyncio
    async def test_fix_action(self, mock_ctx):
        mock_ctx.state.human_input = {"action": "fix"}
        node = QAApprovalNode()

        result = await node.run(mock_ctx)

        assert isinstance(result, ContentPhaseCNode)


# =============================================================================
# PUBLISH NODE
# =============================================================================

class TestPublishNode:
    @pytest.mark.asyncio
    async def test_successful_publish(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = PublishNode()

        with patch(CMS_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.publish_article = MagicMock(return_value={
                "published_url": "https://example.com/articles/test",
                "cms_article_id": "shopify-789",
            })

            result = await node.run(mock_ctx)

        assert isinstance(result, InterlinkingNode)
        assert mock_ctx.state.published_url == "https://example.com/articles/test"
        assert mock_ctx.state.cms_article_id == "shopify-789"

    @pytest.mark.asyncio
    async def test_publish_failure(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        node = PublishNode()

        with patch(CMS_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.publish_article = MagicMock(side_effect=Exception("CMS unavailable"))

            result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.error == "CMS unavailable"


# =============================================================================
# INTERLINKING NODE
# =============================================================================

class TestInterlinkingNode:
    @pytest.mark.asyncio
    async def test_successful_interlinking(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        mock_ctx.state.cms_article_id = "shopify-789"
        mock_ctx.state.published_url = "https://example.com/test"
        node = InterlinkingNode()

        with patch(INTERLINK_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.suggest_links = MagicMock(return_value={"suggestion_count": 3})
            mock_service.auto_link_article = MagicMock(return_value={"links_added": 2})

            result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert "interlinking" in mock_ctx.state.steps_completed
        assert mock_ctx.state.current_step == "complete"

    @pytest.mark.asyncio
    async def test_interlinking_failure_nonfatal(self, mock_ctx):
        mock_ctx.state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        mock_ctx.state.published_url = "https://example.com/test"
        mock_ctx.state.cms_article_id = ""
        node = InterlinkingNode()

        with patch(INTERLINK_SVC) as MockService:
            mock_service = MockService.return_value
            mock_service.suggest_links = MagicMock(side_effect=Exception("DB error"))

            result = await node.run(mock_ctx)

        assert isinstance(result, End)
        assert mock_ctx.state.current_step == "complete"
        assert "interlinking" in mock_ctx.state.steps_completed


# =============================================================================
# ORCHESTRATOR HELPERS
# =============================================================================

class TestGetPipelineStatus:
    def test_not_started(self):
        with patch(
            "viraltracker.services.seo_pipeline.orchestrator._load_pipeline_state",
            return_value=None,
        ):
            status = get_pipeline_status("proj-1", "org-1")
            assert status["status"] == "not_started"

    def test_at_checkpoint(self, base_state):
        base_state.current_step = "keyword_selection"
        base_state.current_checkpoint = SEOHumanCheckpoint.KEYWORD_SELECTION
        base_state.awaiting_human = True
        base_state.steps_completed = ["keyword_discovery"]

        with patch(
            "viraltracker.services.seo_pipeline.orchestrator._load_pipeline_state",
            return_value=base_state,
        ):
            status = get_pipeline_status("proj-1", "org-1")
            assert status["status"] == "keyword_selection"
            assert status["checkpoint"] == "keyword_selection"
            assert status["awaiting_human"] is True
            assert "keyword_discovery" in status["steps_completed"]

    def test_completed(self, base_state):
        base_state.current_step = "complete"
        base_state.published_url = "https://example.com/test"
        base_state.article_id = UUID("44444444-4444-4444-4444-444444444444")
        base_state.completed_at = "2026-03-02T12:00:00Z"

        with patch(
            "viraltracker.services.seo_pipeline.orchestrator._load_pipeline_state",
            return_value=base_state,
        ):
            status = get_pipeline_status("proj-1", "org-1")
            assert status["status"] == "complete"
            assert status["published_url"] == "https://example.com/test"

    def test_error_state(self, base_state):
        base_state.current_step = "content_phase_b"
        base_state.error = "API timeout"
        base_state.error_step = "content_phase_b"

        with patch(
            "viraltracker.services.seo_pipeline.orchestrator._load_pipeline_state",
            return_value=base_state,
        ):
            status = get_pipeline_status("proj-1", "org-1")
            assert status["error"] == "API timeout"
            assert status["error_step"] == "content_phase_b"


# =============================================================================
# IMAGE GENERATION NODE UNIT TESTS
# =============================================================================

IMAGE_SVC = "viraltracker.services.seo_pipeline.services.seo_image_service.SEOImageService"


class TestImageGenerationNode:
    """Dedicated unit tests for ImageGenerationNode."""

    @pytest.mark.asyncio
    async def test_happy_path_updates_state(self, base_state, mock_ctx):
        """On success, node sets hero_image_url, image_results, updates markdown."""
        base_state.phase_c_output = "# Article\n[IMAGE: hero]\nContent"
        base_state.selected_keyword = "gaming pc"
        base_state.article_id = uuid4()

        mock_result = {
            "hero_image_url": "https://cdn.example.com/hero.png",
            "stats": {"total": 1, "success": 1, "failed": 0},
            "updated_markdown": "# Article\n<img src='...' />\nContent",
        }

        with patch(IMAGE_SVC) as MockSvc:
            MockSvc.return_value.generate_article_images = AsyncMock(return_value=mock_result)
            node = ImageGenerationNode()
            result = await node.run(mock_ctx)

        assert isinstance(result, PublishNode)
        assert base_state.hero_image_url == "https://cdn.example.com/hero.png"
        assert base_state.image_results == {"total": 1, "success": 1, "failed": 0}
        assert "image_generation" in base_state.steps_completed

    @pytest.mark.asyncio
    async def test_no_markdown_skips(self, base_state, mock_ctx):
        """When no Phase C output, node skips and proceeds to PublishNode."""
        base_state.phase_c_output = None

        node = ImageGenerationNode()
        result = await node.run(mock_ctx)

        assert isinstance(result, PublishNode)
        assert "image_generation" in base_state.steps_completed
        assert base_state.hero_image_url is None

    @pytest.mark.asyncio
    async def test_exception_non_fatal(self, base_state, mock_ctx):
        """On service exception, node logs warning and proceeds (non-fatal)."""
        base_state.phase_c_output = "# Article with images"
        base_state.selected_keyword = "test"
        base_state.article_id = uuid4()

        with patch(IMAGE_SVC) as MockSvc:
            MockSvc.return_value.generate_article_images = AsyncMock(
                side_effect=Exception("Gemini API down")
            )
            node = ImageGenerationNode()
            result = await node.run(mock_ctx)

        assert isinstance(result, PublishNode)
        assert "image_generation" in base_state.steps_completed
        assert base_state.hero_image_url is None
