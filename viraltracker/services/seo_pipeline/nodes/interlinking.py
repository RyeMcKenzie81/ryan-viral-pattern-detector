"""
Interlinking Node — Suggests and auto-links internal links after publishing.

Reads: article_id, brand_id, organization_id
Writes: (link records saved to DB)
"""

import logging
from dataclasses import dataclass
from typing import ClassVar
from datetime import datetime, timezone

from pydantic_graph import BaseNode, End, GraphRunContext

from viraltracker.pipelines.metadata import NodeMetadata
from viraltracker.services.seo_pipeline.state import SEOPipelineState

logger = logging.getLogger(__name__)


@dataclass
class InterlinkingNode(BaseNode[SEOPipelineState]):
    """
    Step 12: Suggest and auto-link internal links.

    Runs link suggestions and auto-linking for the newly published article.
    This is the final step in the pipeline.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["article_id"],
        outputs=[],
        services=[
            "interlinking.suggest_links",
            "interlinking.auto_link_article",
        ],
    )

    async def run(
        self,
        ctx: GraphRunContext[SEOPipelineState],
    ) -> End:
        logger.info("Step 12: Running interlinking...")
        ctx.state.current_step = "interlinking"

        try:
            from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
            service = InterlinkingService()

            article_id = str(ctx.state.article_id)
            brand_id = str(ctx.state.brand_id)
            organization_id = str(ctx.state.organization_id)
            has_cms = bool(ctx.state.cms_article_id)

            # Suggest links
            suggestions = service.suggest_links(
                article_id,
                min_similarity=0.2,
                max_suggestions=10,
            )
            suggestion_count = suggestions.get("suggestion_count", 0)

            # Auto-link
            auto_result = service.auto_link_article(
                article_id,
                push_to_cms=has_cms,
                brand_id=brand_id,
                organization_id=organization_id,
            )
            links_added = auto_result.get("links_added", 0)

            # Add Related Articles section from top suggestions
            related_count = 0
            if suggestions.get("suggestions"):
                try:
                    top_ids = [s["target_article_id"] for s in suggestions["suggestions"][:5]]
                    related_result = service.add_related_section(
                        article_id, top_ids,
                        push_to_cms=has_cms,
                        brand_id=brand_id,
                        organization_id=organization_id,
                    )
                    related_count = related_result.get("articles_linked", 0)
                except Exception as e:
                    logger.warning(f"Related section failed (non-fatal): {e}")

            # Cluster-aware interlinking
            cluster_result = {}
            try:
                from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
                cluster_svc = ClusterManagementService()
                clusters = cluster_svc.find_clusters_for_article(article_id)

                if clusters:
                    for cluster_info in clusters:
                        cluster_result = service.interlink_cluster(
                            cluster_id=cluster_info["cluster_id"],
                            trigger_article_id=article_id,
                            push_to_cms=has_cms,
                            brand_id=brand_id,
                            organization_id=organization_id,
                        )
                        logger.info(
                            f"Cluster interlinking for {cluster_info['cluster_name']}: "
                            f"{cluster_result.get('links_added', 0)} links added"
                        )
            except Exception as e:
                logger.warning(f"Cluster interlinking failed (non-fatal): {e}")

            ctx.state.mark_step_complete("interlinking")
            ctx.state.current_step = "complete"
            ctx.state.completed_at = datetime.now(timezone.utc).isoformat()

            logger.info(f"Interlinking complete: {suggestion_count} suggested, {links_added} auto-linked, {related_count} related")

            return End({
                "status": "complete",
                "article_id": article_id,
                "published_url": ctx.state.published_url,
                "cms_article_id": ctx.state.cms_article_id,
                "suggestions": suggestion_count,
                "auto_links": links_added,
                "related_articles": related_count,
                "cluster_links": cluster_result.get("links_added", 0),
                "steps_completed": ctx.state.steps_completed,
            })

        except Exception as e:
            # Interlinking failure is non-fatal — article is already published
            logger.warning(f"Interlinking failed (non-fatal): {e}")
            ctx.state.mark_step_complete("interlinking")
            ctx.state.current_step = "complete"
            ctx.state.completed_at = datetime.now(timezone.utc).isoformat()

            return End({
                "status": "complete_with_warnings",
                "article_id": str(ctx.state.article_id),
                "published_url": ctx.state.published_url,
                "cms_article_id": ctx.state.cms_article_id,
                "warning": f"Interlinking failed: {e}",
                "steps_completed": ctx.state.steps_completed,
            })
