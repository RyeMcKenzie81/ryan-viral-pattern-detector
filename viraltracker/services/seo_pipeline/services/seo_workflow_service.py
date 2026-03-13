"""
SEO Workflow Service — async pipeline orchestration for one-off and cluster batch content.

Execution model:
- Background threading.Thread with its own asyncio.run() event loop
- Streamlit UI polls seo_workflow_jobs for progress
- Each background thread creates FRESH service instances (thread safety)
- Sync service calls wrapped in asyncio.to_thread()
- Max 3 concurrent jobs via threading.Semaphore(3)
"""

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_job_semaphore = threading.Semaphore(3)

# Pipeline step definitions
ONE_OFF_STEPS = [
    "validate", "create_keyword", "create_article", "pre_write_check",
    "competitor_analysis", "phase_a", "phase_b", "phase_c",
    "image_generation", "pre_publish_checklist", "publish",
    "build_schema", "interlinking", "complete",
]

STEP_LABELS = {
    "validate": "Validating inputs",
    "create_keyword": "Creating keyword record",
    "create_article": "Creating article",
    "pre_write_check": "Checking for cannibalization",
    "competitor_analysis": "Analyzing competitors",
    "phase_a": "Phase A — Research & Outline",
    "phase_b": "Phase B — Writing",
    "phase_c": "Phase C — SEO Optimization",
    "image_generation": "Generating images",
    "pre_publish_checklist": "Running pre-publish checks",
    "publish": "Publishing to Shopify",
    "build_schema": "Building schema markup",
    "interlinking": "Adding internal links",
    "complete": "Complete",
}

# Steps where step-through mode pauses
PAUSE_POINTS = {"phase_a", "phase_b", "pre_publish_checklist"}


class SEOWorkflowService:
    """Async pipeline orchestration for SEO content workflows."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def _resolve_org_id(self, organization_id: str, brand_id: str) -> str:
        """Resolve real UUID org_id from brand when superuser passes 'all'."""
        if organization_id != "all":
            return organization_id
        row = self.supabase.table("brands").select("organization_id").eq("id", brand_id).limit(1).execute()
        if row.data:
            return row.data[0]["organization_id"]
        return organization_id

    # =========================================================================
    # ONE-OFF PIPELINE
    # =========================================================================

    def start_one_off(
        self,
        keyword: str,
        brand_id: str,
        organization_id: str,
        project_id: Optional[str] = None,
        author_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        step_through: bool = False,
        competitor_urls: Optional[List[str]] = None,
        cluster_context: Optional[str] = None,
        content_fingerprints: Optional[str] = None,
        article_role: Optional[str] = None,
    ) -> str:
        """
        Validate, create job record, spawn background thread. Returns job_id.

        Raises ValueError for validation failures (duplicate job, bad keyword).
        """
        # Resolve real org_id for superuser mode
        organization_id = self._resolve_org_id(organization_id, brand_id)

        # Validate keyword
        keyword = keyword.strip()
        keyword = re.sub(r"<[^>]+>", "", keyword)  # Strip HTML
        if not keyword or len(keyword) < 2 or len(keyword) > 200:
            raise ValueError("Keyword must be 2-200 characters")

        # Create job record (DB partial unique index handles dedup race condition)
        config = {
            "keyword": keyword,
            "brand_id": brand_id,
            "project_id": project_id,
            "author_id": author_id,
            "tags": tags,
            "step_through": step_through,
            "competitor_urls": competitor_urls,
            "cluster_context": cluster_context,
            "content_fingerprints": content_fingerprints,
            "article_role": article_role,
        }

        try:
            result = self.supabase.table("seo_workflow_jobs").insert({
                "brand_id": brand_id,
                "organization_id": organization_id,
                "job_type": "one_off",
                "status": "pending",
                "config": config,
                "progress": {
                    "current_step": "validate",
                    "current_step_label": "Pending",
                    "total_steps": len(ONE_OFF_STEPS),
                    "steps_completed": [],
                    "percent": 0,
                },
            }).execute()
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                raise ValueError(f"A job for '{keyword}' is already running for this brand")
            raise

        job_id = result.data[0]["id"]
        logger.info(f"Created one-off job {job_id} for keyword '{keyword}'")

        # Spawn background thread
        t = threading.Thread(
            target=self._run_one_off_thread,
            args=(job_id,),
            daemon=True,
            name=f"seo-workflow-{job_id[:8]}",
        )
        t.start()
        return job_id

    def _run_one_off_thread(self, job_id: str) -> None:
        """Background thread entry point — acquire semaphore then run async pipeline."""
        acquired = _job_semaphore.acquire(timeout=300)
        if not acquired:
            self._update_job(job_id, status="failed", error="Server busy — max concurrent jobs reached")
            return
        try:
            asyncio.run(self._execute_one_off(job_id))
        except Exception as e:
            logger.error(f"Job {job_id} thread crashed: {e}", exc_info=True)
            try:
                self._update_job(job_id, status="failed", error=str(e)[:1000])
            except Exception:
                pass
        finally:
            _job_semaphore.release()

    async def _execute_one_off(self, job_id: str) -> None:
        """Run the full one-off pipeline with progress tracking."""
        # Load job
        job = self._load_job(job_id)
        if not job:
            return
        config = job.get("config", {})
        brand_id = config["brand_id"]
        org_id = job["organization_id"]
        keyword = config["keyword"]
        step_through = config.get("step_through", False)

        self._update_job(job_id, status="running")

        # Fresh service instances for thread safety
        from viraltracker.core.database import get_supabase_client
        sb = get_supabase_client()

        from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
        from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
        from viraltracker.services.seo_pipeline.services.article_tracking_service import ArticleTrackingService
        from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
        from viraltracker.services.seo_pipeline.services.pre_publish_checklist_service import PrePublishChecklistService

        brand_config_svc = SEOBrandConfigService(supabase_client=sb)
        content_svc = ContentGenerationService(supabase_client=sb)
        keyword_svc = KeywordDiscoveryService(supabase_client=sb)
        tracking_svc = ArticleTrackingService(supabase_client=sb)
        cluster_svc = ClusterManagementService(supabase_client=sb)
        checklist_svc = PrePublishChecklistService(supabase_client=sb)

        try:
            # 0. Load brand config + brand context
            self._advance_step(job_id, "validate")
            if self._is_cancelled(job_id):
                return

            brand_config = brand_config_svc.get_config(brand_id)

            # Load brand name (positioning comes from brand_config style guide)
            brand_row = sb.table("brands").select("name, description").eq("id", brand_id).limit(1).execute()
            brand_ctx = {}
            if brand_row.data:
                brand_ctx = {
                    "brand_name": brand_row.data[0].get("name", ""),
                    "brand_positioning": brand_row.data[0].get("description", ""),
                }

            # Resolve project_id
            project_id = config.get("project_id")
            if not project_id:
                project_id = self._resolve_project(brand_id, org_id)

            # Resolve author_id
            author_id = config.get("author_id") or brand_config.get("default_author_id")

            # 1. Create keyword record
            self._advance_step(job_id, "create_keyword")
            if self._is_cancelled(job_id):
                return

            kw_record = await asyncio.to_thread(
                keyword_svc.create_keyword, project_id, keyword
            )
            keyword_id = kw_record["id"]

            # 2. Create article record
            self._advance_step(job_id, "create_article")
            if self._is_cancelled(job_id):
                return

            article_data = {
                "project_id": project_id,
                "brand_id": brand_id,
                "organization_id": org_id,
                "keyword": keyword,
                "keyword_id": keyword_id,
                "status": "draft",
                "phase": "a",
            }
            if author_id:
                article_data["author_id"] = author_id

            article_result = sb.table("seo_articles").insert(article_data).execute()
            article_id = article_result.data[0]["id"]

            # Store article_id in job config for later reference
            self._update_job_config(job_id, {"article_id": article_id, "keyword_id": keyword_id, "project_id": project_id})

            # 3. Pre-write check
            self._advance_step(job_id, "pre_write_check")
            if self._is_cancelled(job_id):
                return

            pre_check = await asyncio.to_thread(
                cluster_svc.pre_write_check, keyword, brand_id=brand_id
            )
            if pre_check.get("risk_level") == "HIGH":
                logger.warning(f"High cannibalization risk for '{keyword}': {pre_check.get('recommendation')}")
                # Continue anyway — just log the warning

            # 4. Competitor analysis (skip if no URLs)
            self._advance_step(job_id, "competitor_analysis")
            if self._is_cancelled(job_id):
                return

            competitor_data = None
            competitor_urls = config.get("competitor_urls")
            if competitor_urls:
                try:
                    from viraltracker.services.seo_pipeline.services.competitor_analysis_service import CompetitorAnalysisService
                    comp_svc = CompetitorAnalysisService(supabase_client=sb)
                    competitor_data = await asyncio.to_thread(
                        comp_svc.analyze_urls, keyword_id, competitor_urls
                    )
                except Exception as e:
                    logger.warning(f"Competitor analysis failed (non-fatal): {e}")

            # 5. Phase A — Research & Outline
            self._advance_step(job_id, "phase_a")
            if self._is_cancelled(job_id):
                return

            # Load author context
            author_ctx = await asyncio.to_thread(content_svc._load_author_context, author_id)

            phase_a_result = await asyncio.to_thread(
                content_svc.generate_phase_a,
                article_id,
                keyword_id=keyword_id,
                author_id=author_id,
                brand_config=brand_config,
                cluster_context=config.get("cluster_context"),
            )

            if step_through and "phase_a" in PAUSE_POINTS:
                self._pause_job(job_id, "phase_a", {"outline": phase_a_result.get("content", "")[:5000]})
                return

            # 6. Phase B — Write
            self._advance_step(job_id, "phase_b")
            if self._is_cancelled(job_id):
                return

            phase_b_result = await asyncio.to_thread(
                content_svc.generate_phase_b,
                article_id,
                author_id=author_id,
                brand_config=brand_config,
                cluster_context=config.get("cluster_context"),
                content_fingerprints=config.get("content_fingerprints"),
                article_role=config.get("article_role"),
            )

            if step_through and "phase_b" in PAUSE_POINTS:
                self._pause_job(job_id, "phase_b", {"draft": phase_b_result.get("content", "")[:5000]})
                return

            # 7. Phase C — Optimize + Parse Frontmatter
            self._advance_step(job_id, "phase_c")
            if self._is_cancelled(job_id):
                return

            phase_c_result = await asyncio.to_thread(
                content_svc.generate_phase_c,
                article_id,
                author_id=author_id,
                brand_config=brand_config,
            )

            # Parse YAML frontmatter from Phase C output
            phase_c_output = phase_c_result.get("content", "")
            parsed = self._parse_frontmatter(phase_c_output)
            if parsed:
                update_fields = {}
                if parsed.get("title"):
                    update_fields["seo_title"] = parsed["title"][:200]
                if parsed.get("description"):
                    update_fields["meta_description"] = parsed["description"][:500]
                if parsed.get("tags"):
                    # Match against brand config tags
                    valid_slugs = {t["slug"] for t in (brand_config.get("available_tags") or [])}
                    matched_tags = [t for t in parsed["tags"] if t in valid_slugs] if valid_slugs else parsed["tags"]
                    if matched_tags:
                        update_fields["tags"] = matched_tags
                if update_fields:
                    sb.table("seo_articles").update(update_fields).eq("id", article_id).execute()

            # Update article status to optimized
            await asyncio.to_thread(tracking_svc.update_status, article_id, "optimized", True)

            # 8. Image generation
            self._advance_step(job_id, "image_generation")
            if self._is_cancelled(job_id):
                return

            try:
                from viraltracker.services.seo_pipeline.services.seo_image_service import SEOImageService
                image_svc = SEOImageService(supabase_client=sb)
                article_fresh = sb.table("seo_articles").select("phase_c_output, content_markdown").eq("id", article_id).limit(1).execute()
                markdown = ""
                if article_fresh.data:
                    markdown = article_fresh.data[0].get("phase_c_output") or article_fresh.data[0].get("content_markdown") or ""

                if markdown:
                    await image_svc.generate_article_images(
                        article_id=article_id,
                        markdown=markdown,
                        brand_id=brand_id,
                        organization_id=org_id,
                        keyword=keyword,
                        image_style=brand_config.get("image_style"),
                    )
            except Exception as e:
                logger.warning(f"Image generation failed (non-fatal): {e}")

            # 9. Pre-publish checklist
            self._advance_step(job_id, "pre_publish_checklist")
            if self._is_cancelled(job_id):
                return

            checklist_result = await asyncio.to_thread(
                checklist_svc.run_checklist, article_id, brand_config
            )

            if step_through and "pre_publish_checklist" in PAUSE_POINTS:
                self._pause_job(job_id, "pre_publish_checklist", {"checklist": checklist_result})
                return

            # 10. Publish to Shopify as draft
            self._advance_step(job_id, "publish")
            if self._is_cancelled(job_id):
                return

            publish_result = None
            try:
                from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                cms_svc = CMSPublisherService(supabase_client=sb)
                publish_result = await asyncio.to_thread(
                    cms_svc.publish_article, article_id, brand_id, org_id, draft=True
                )
            except Exception as e:
                logger.error(f"Shopify publish failed: {e}")
                self._update_job(job_id, status="failed", error=f"Shopify publish failed: {e}",
                                 progress_update={"failed_at_step": "publish"})
                return

            # 10b. Build schema markup programmatically
            self._advance_step(job_id, "build_schema")
            if self._is_cancelled(job_id):
                return

            published_url = ""
            admin_url = ""
            if publish_result:
                published_url = publish_result.get("published_url", "")
                admin_url = publish_result.get("admin_url", "")

            schema = self._build_schema_markup(
                article_id=article_id,
                published_url=published_url,
                author_ctx=author_ctx,
                brand_config=brand_config,
                brand_ctx=brand_ctx,
                sb=sb,
            )
            if schema:
                sb.table("seo_articles").update({"schema_markup": schema}).eq("id", article_id).execute()

            # Update status to publishing
            await asyncio.to_thread(tracking_svc.update_status, article_id, "publishing", True)

            # 11. Interlinking
            self._advance_step(job_id, "interlinking")
            if self._is_cancelled(job_id):
                return

            try:
                from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
                link_svc = InterlinkingService(supabase_client=sb)
                await asyncio.to_thread(link_svc.auto_link_article, article_id)
            except Exception as e:
                logger.warning(f"Interlinking failed (non-fatal): {e}")

            # 12. Complete
            self._advance_step(job_id, "complete")
            self._update_job(
                job_id,
                status="completed",
                result={
                    "article_id": article_id,
                    "keyword": keyword,
                    "published_url": admin_url or published_url,
                    "checklist": checklist_result,
                },
            )
            logger.info(f"Job {job_id} completed: article={article_id}, url={published_url}")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            self._update_job(
                job_id,
                status="failed",
                error=str(e)[:1000],
                progress_update={"failed_at_step": job.get("progress", {}).get("current_step", "unknown")},
            )

    # =========================================================================
    # RESUME / RETRY / CANCEL
    # =========================================================================

    def resume_job(self, job_id: str, action: str = "approve") -> None:
        """
        Resume a paused step-through job. Spawns a new background thread.

        Args:
            job_id: Job UUID
            action: "approve" to continue, "cancel" to cancel
        """
        if action == "cancel":
            self.cancel_job(job_id)
            return

        job = self._load_job(job_id)
        if not job or job.get("status") != "paused":
            raise ValueError(f"Job {job_id} is not paused")

        # Mark as running and clear paused_at
        self.supabase.table("seo_workflow_jobs").update({
            "status": "running",
            "paused_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

        # Spawn new thread to continue from next step
        t = threading.Thread(
            target=self._run_one_off_thread,
            args=(job_id,),
            daemon=True,
            name=f"seo-workflow-resume-{job_id[:8]}",
        )
        t.start()

    def retry_job(self, job_id: str, from_step: Optional[str] = None) -> None:
        """Retry a failed job from the failed step."""
        job = self._load_job(job_id)
        if not job or job.get("status") not in ("failed", "cancelled"):
            raise ValueError(f"Job {job_id} is not in a retryable state")

        progress = job.get("progress", {})
        retry_step = from_step or progress.get("failed_at_step", "validate")

        # Reset status and update progress
        self.supabase.table("seo_workflow_jobs").update({
            "status": "pending",
            "error": None,
            "progress": {**progress, "current_step": retry_step, "failed_at_step": None},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

        t = threading.Thread(
            target=self._run_one_off_thread,
            args=(job_id,),
            daemon=True,
            name=f"seo-workflow-retry-{job_id[:8]}",
        )
        t.start()

    def cancel_job(self, job_id: str) -> None:
        """Set cancelled flag. Pipeline checks between steps."""
        self._update_job(job_id, status="cancelled")
        logger.info(f"Cancelled job {job_id}")

    def regenerate_images(self, article_id: str, brand_id: str, organization_id: str) -> Dict[str, Any]:
        """
        Re-run image generation for an existing article.

        Handles the case where markers have already been replaced with <img> tags
        by reconstructing markers from stored image_metadata descriptions.

        Returns:
            Dict with hero_image_url, stats, image_metadata.
        """
        import asyncio
        import concurrent.futures
        organization_id = self._resolve_org_id(organization_id, brand_id)

        # Load article and brand config from main thread (read-only, safe)
        sb = self.supabase
        brand_config_data = None
        from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
        brand_config_data = SEOBrandConfigService(supabase_client=sb).get_config(brand_id)

        article = sb.table("seo_articles").select(
            "keyword, content_markdown, phase_c_output, phase_b_output, image_metadata"
        ).eq("id", article_id).limit(1).execute()
        if not article.data:
            raise ValueError(f"Article not found: {article_id}")

        row = article.data[0]
        keyword = row.get("keyword", "")

        # Try to find content with [IMAGE: ...] markers still intact
        markdown = row.get("content_markdown") or ""

        # If no markdown with markers, check if we can reconstruct markers
        # from image_metadata (stored descriptions from previous generation)
        from viraltracker.services.seo_pipeline.services.seo_image_service import SEOImageService
        test_svc = SEOImageService()
        if not test_svc.extract_image_markers(markdown):
            # No markers in content_markdown. Try phase_c_output.
            phase_c = row.get("phase_c_output") or ""
            if test_svc.extract_image_markers(phase_c):
                markdown = phase_c
            else:
                # Markers already replaced. Reconstruct from image_metadata.
                existing_meta = row.get("image_metadata") or []
                if existing_meta:
                    # Rebuild markdown with [IMAGE: ...] markers from stored descriptions
                    base_content = phase_c or row.get("phase_b_output") or ""
                    if not base_content:
                        raise ValueError("Article has no content to generate images for")

                    # Strip existing <img> tags and re-insert markers
                    import re
                    base_content = re.sub(
                        r'<img[^>]*alt="([^"]*)"[^>]*/?>',
                        lambda m: f'[IMAGE: {m.group(1)}]',
                        base_content,
                    )
                    # If no <img> tags were found, append markers at end
                    if not test_svc.extract_image_markers(base_content):
                        marker_lines = []
                        for i, meta in enumerate(existing_meta):
                            desc = meta.get("description") or meta.get("prompt") or f"Image {i+1}"
                            img_type = meta.get("type", "inline")
                            prefix = "HERO IMAGE" if img_type == "hero" else "IMAGE"
                            marker_lines.append(f"[{prefix}: {desc}]")
                        base_content = base_content + "\n\n" + "\n\n".join(marker_lines)
                    markdown = base_content
                else:
                    # No markers AND no metadata — generate fresh markers from content
                    base_content = phase_c or row.get("phase_b_output") or ""
                    if not base_content:
                        raise ValueError("Article has no content to generate images for")
                    markdown = self._inject_image_markers(base_content, keyword)

        if not markdown:
            raise ValueError("Article has no content to generate images for")

        # Run in child thread with its own event loop and Supabase client
        # (httpx.Client is not thread-safe, so child thread needs its own)
        _article_id = article_id
        _markdown = markdown
        _brand_id = brand_id
        _org_id = organization_id
        _keyword = keyword
        _image_style = brand_config_data.get("image_style")

        def _run():
            from viraltracker.core.database import get_supabase_client
            child_sb = get_supabase_client()  # thread-local, gets fresh client
            child_image_svc = SEOImageService(supabase_client=child_sb)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    child_image_svc.generate_article_images(
                        article_id=_article_id,
                        markdown=_markdown,
                        brand_id=_brand_id,
                        organization_id=_org_id,
                        keyword=_keyword,
                        image_style=_image_style,
                    )
                )
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            result = future.result(timeout=600)  # 10 min timeout for many images
        return result or {}

    def regenerate_single_image(
        self,
        article_id: str,
        image_index: int,
        brand_id: str,
        organization_id: str,
        custom_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Re-generate a single image by index for an existing article.

        Uses a child thread with its own event loop and Supabase client
        for Streamlit thread safety (same pattern as regenerate_images).

        Args:
            article_id: Article UUID
            image_index: Index in image_metadata array
            brand_id: Brand UUID
            organization_id: Org UUID (resolves 'all' for superusers)
            custom_prompt: Optional custom prompt (overrides original description)

        Returns:
            Updated image metadata entry dict
        """
        import concurrent.futures
        organization_id = self._resolve_org_id(organization_id, brand_id)

        # Load brand config from main thread (read-only, safe)
        sb = self.supabase
        from viraltracker.services.seo_pipeline.services.seo_brand_config_service import SEOBrandConfigService
        brand_config_data = SEOBrandConfigService(supabase_client=sb).get_config(brand_id)
        image_style = brand_config_data.get("image_style")

        # Capture for closure
        _article_id = article_id
        _image_index = image_index
        _brand_id = brand_id
        _org_id = organization_id
        _custom_prompt = custom_prompt
        _image_style = image_style

        def _run():
            from viraltracker.core.database import get_supabase_client
            child_sb = get_supabase_client()
            from viraltracker.services.seo_pipeline.services.seo_image_service import SEOImageService
            child_image_svc = SEOImageService(supabase_client=child_sb)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    child_image_svc.regenerate_image(
                        article_id=_article_id,
                        image_index=_image_index,
                        brand_id=_brand_id,
                        organization_id=_org_id,
                        custom_prompt=_custom_prompt,
                        image_style=_image_style,
                    )
                )
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            result = future.result(timeout=120)
        return result or {}

    def get_article_images(self, article_id: str) -> Dict[str, Any]:
        """
        Load image data for an article from the DB.

        Returns:
            Dict with image_metadata, hero_image_url, keyword
        """
        result = (
            self.supabase.table("seo_articles")
            .select("image_metadata, hero_image_url, keyword")
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return {"image_metadata": [], "hero_image_url": None, "keyword": ""}
        row = result.data[0]
        return {
            "image_metadata": row.get("image_metadata") or [],
            "hero_image_url": row.get("hero_image_url"),
            "keyword": row.get("keyword", ""),
        }

    @staticmethod
    def _inject_image_markers(content: str, keyword: str) -> str:
        """
        Generate image markers from article content when none exist.

        Scales image count with article length:
        - <1500 words: hero + 2 inline
        - 1500-3000 words: hero + 4 inline
        - 3000+ words: hero + up to 7 inline (one per ~500 words)

        Distributes evenly across H2 headings. If more H2s than desired
        images, selects evenly spaced headings.

        Returns content with markers inserted.
        """
        lines = content.split("\n")
        word_count = len(content.split())

        # Scale inline image count with article length
        if word_count < 1500:
            max_inline = 2
        elif word_count < 3000:
            max_inline = 4
        else:
            max_inline = min(7, max(4, word_count // 500))

        # Collect all H2 positions
        h2_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("## "):
                h2_indices.append(i)

        # Select evenly spaced H2s if we have more than we need
        if len(h2_indices) > max_inline:
            selected = []
            for j in range(max_inline):
                idx = round(j * (len(h2_indices) - 1) / (max_inline - 1))
                selected.append(h2_indices[idx])
            h2_set = set(selected)
        else:
            h2_set = set(h2_indices)

        # Build output with hero at top and inline after selected H2s
        result_lines = [f"[HERO IMAGE: {keyword} - featured image]", ""]

        for i, line in enumerate(lines):
            result_lines.append(line)

            if i in h2_set:
                heading_text = re.sub(r'^#+\s*', '', line.strip()).strip() or keyword
                result_lines.append("")
                result_lines.append(f"[IMAGE: {heading_text} - {keyword}]")
                result_lines.append("")

        return "\n".join(result_lines)

    # =========================================================================
    # CLUSTER RESEARCH
    # =========================================================================

    async def start_cluster_research(
        self,
        brand_id: str,
        organization_id: str,
        seed_keywords: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        research_mode: str = "deep",
    ) -> Dict[str, Any]:
        """
        Run cluster research. Returns structured research report.

        Args:
            brand_id: Brand UUID
            organization_id: Org UUID
            seed_keywords: Starting keywords
            sources: Research source names (default: all)
            research_mode: "quick" (algorithmic) or "deep" (AI analysis)

        Returns:
            Research report with cluster recommendations
        """
        # Resolve real org_id for superuser mode
        organization_id = self._resolve_org_id(organization_id, brand_id)

        from viraltracker.services.seo_pipeline.services.cluster_research_registry import ClusterResearchRegistry

        registry = ClusterResearchRegistry(supabase_client=self.supabase)
        seeds = seed_keywords or []

        # Gather keywords from sources
        source_results = registry.fetch_all(brand_id, organization_id, seeds, sources)

        # Merge all keywords
        all_keywords = list(seeds)
        for kws in source_results.values():
            all_keywords.extend(kws)
        # Deduplicate
        seen = set()
        unique_keywords = []
        for kw in all_keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique_keywords.append(kw)

        if research_mode == "quick":
            return self._quick_cluster(unique_keywords, source_results)

        return await self._deep_cluster_research(
            unique_keywords, brand_id, organization_id, source_results
        )

    def _quick_cluster(
        self,
        keywords: List[str],
        source_results: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Algorithmic clustering using word overlap (Jaccard similarity)."""
        from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
        link_svc = InterlinkingService()

        clusters = []
        assigned = set()

        for i, kw in enumerate(keywords):
            if kw in assigned:
                continue
            cluster = [kw]
            assigned.add(kw)

            for other in keywords[i + 1:]:
                if other in assigned:
                    continue
                sim = link_svc._jaccard_similarity(kw, other)
                if sim > 0.3:
                    cluster.append(other)
                    assigned.add(other)

            if len(cluster) >= 2:
                clusters.append({
                    "pillar_keyword": cluster[0],
                    "topic_summary": f"Cluster around '{cluster[0]}'",
                    "opportunity_score": min(len(cluster) / 10, 1.0),
                    "spokes": [{"keyword": kw, "angle": "", "priority": i + 1}
                               for i, kw in enumerate(cluster[1:])],
                })

        return {
            "mode": "quick",
            "total_keywords": len(keywords),
            "clusters": clusters,
            "sources": {k: len(v) for k, v in source_results.items()},
        }

    async def _deep_cluster_research(
        self,
        keywords: List[str],
        brand_id: str,
        organization_id: str,
        source_results: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """AI-powered cluster analysis using Claude."""
        from viraltracker.core.database import get_supabase_client
        sb = get_supabase_client()

        # Load brand context
        brand_row = sb.table("brands").select("name, description").eq("id", brand_id).limit(1).execute()
        brand_name = brand_row.data[0].get("name", "") if brand_row.data else ""
        brand_positioning = brand_row.data[0].get("description", "") if brand_row.data else ""

        # Load existing articles to avoid cannibalization
        existing = sb.table("seo_articles").select("keyword").eq("brand_id", brand_id).neq("status", "discovered").limit(100).execute()
        existing_keywords = [a.get("keyword", "") for a in (existing.data or [])]

        prompt = (
            f"You are an SEO strategist. Analyze these keywords and group them into topic clusters.\n\n"
            f"Brand: {brand_name}\n"
            f"Positioning: {brand_positioning}\n\n"
            f"Keywords to cluster:\n"
            + "\n".join(f"- {kw}" for kw in keywords[:100])
            + "\n\nExisting articles (avoid cannibalization):\n"
            + "\n".join(f"- {kw}" for kw in existing_keywords[:50])
            + "\n\nFor each cluster, identify:\n"
            "1. A pillar keyword (broad topic)\n"
            "2. Spoke keywords (specific subtopics)\n"
            "3. Unique angle for each spoke\n"
            "4. Opportunity score (0-1) based on specificity and brand relevance\n"
            "5. Recommended generation order\n\n"
            "Exclude keywords that would cannibalize existing articles.\n\n"
            "Return as JSON:\n"
            '{"clusters": [{"pillar_keyword": "...", "topic_summary": "...", '
            '"opportunity_score": 0.8, "reasoning": "...", '
            '"spokes": [{"keyword": "...", "angle": "...", "priority": 1, '
            '"estimated_difficulty": "low|medium|high"}]}]}'
        )

        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text

            # Extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                result = json.loads(json_match.group())
                result["mode"] = "deep"
                result["total_keywords"] = len(keywords)
                result["sources"] = {k: len(v) for k, v in source_results.items()}
                return result
        except Exception as e:
            logger.error(f"Deep cluster research failed: {e}")

        # Fallback to quick mode
        return self._quick_cluster(keywords, source_results)

    # =========================================================================
    # CLUSTER BATCH PIPELINE
    # =========================================================================

    def save_cluster_from_research(
        self,
        cluster_data: Dict[str, Any],
        brand_id: str,
        organization_id: str,
    ) -> str:
        """
        Persist a cluster from a research report to the database.

        Creates keyword records, a cluster, and spokes so the cluster
        can be used with start_cluster_batch().

        Args:
            cluster_data: Single cluster from research report
                (pillar_keyword, spokes, topic_summary, etc.)
            brand_id: Brand UUID
            organization_id: Organization UUID

        Returns:
            Created cluster ID
        """
        organization_id = self._resolve_org_id(organization_id, brand_id)
        project_id = self._resolve_project(brand_id, organization_id)

        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
        from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
        from viraltracker.core.database import get_supabase_client

        sb = get_supabase_client()
        kw_svc = KeywordDiscoveryService(supabase_client=sb)
        cluster_svc = ClusterManagementService(supabase_client=sb)

        pillar_keyword = cluster_data.get("pillar_keyword", "")
        spokes = cluster_data.get("spokes", [])

        # Create cluster record
        cluster = cluster_svc.create_cluster(
            project_id=project_id,
            name=pillar_keyword,
            pillar_keyword=pillar_keyword,
            intent=cluster_data.get("intent", "informational"),
            description=cluster_data.get("topic_summary", ""),
            target_spoke_count=len(spokes),
        )
        cluster_id = cluster["id"]

        # Create pillar keyword + spoke
        pillar_kw_record = kw_svc.create_keyword(project_id, pillar_keyword)
        cluster_svc.add_spoke(
            cluster_id=cluster_id,
            keyword_id=pillar_kw_record["id"],
            role="pillar",
            priority=1,
        )

        # Create spoke keywords + spokes
        for i, spoke in enumerate(spokes):
            spoke_keyword = spoke.get("keyword", "")
            if not spoke_keyword:
                continue
            spoke_kw_record = kw_svc.create_keyword(project_id, spoke_keyword)
            cluster_svc.add_spoke(
                cluster_id=cluster_id,
                keyword_id=spoke_kw_record["id"],
                role="spoke",
                priority=spoke.get("priority", i + 2),
            )

        logger.info(
            f"Saved cluster '{pillar_keyword}' with {len(spokes)} spokes "
            f"(cluster_id={cluster_id})"
        )
        return cluster_id

    def start_cluster_batch(
        self,
        cluster_id: str,
        brand_id: str,
        organization_id: str,
    ) -> str:
        """Create batch job and process all spokes. Returns job_id."""
        # Resolve real org_id for superuser mode
        organization_id = self._resolve_org_id(organization_id, brand_id)

        # Load cluster
        cluster = (
            self.supabase.table("seo_clusters")
            .select("*")
            .eq("id", cluster_id)
            .limit(1)
            .execute()
        )
        if not cluster.data:
            raise ValueError(f"Cluster not found: {cluster_id}")

        cluster_data = cluster.data[0]

        # Load spokes with keyword text via join
        spokes = (
            self.supabase.table("seo_cluster_spokes")
            .select("*, seo_keywords(keyword)")
            .eq("cluster_id", cluster_id)
            .order("priority")
            .execute()
        ).data or []

        # Filter out the pillar spoke (generated separately)
        spoke_only = [
            s for s in spokes
            if s.get("role") != "pillar"
        ]

        config = {
            "cluster_id": cluster_id,
            "brand_id": brand_id,
            "pillar_keyword": cluster_data.get("pillar_keyword", ""),
            "spokes": [
                {
                    "keyword": (s.get("seo_keywords") or {}).get("keyword", ""),
                    "id": s.get("id"),
                }
                for s in spoke_only
            ],
        }

        try:
            result = self.supabase.table("seo_workflow_jobs").insert({
                "brand_id": brand_id,
                "organization_id": organization_id,
                "job_type": "cluster_batch",
                "status": "pending",
                "config": config,
                "progress": {
                    "current_step": "validate",
                    "current_step_label": "Starting batch...",
                    "total_steps": 2 + len(spoke_only),  # pillar + spokes + linking
                    "current_article_index": 0,
                    "total_articles": 1 + len(spoke_only),
                    "per_article_results": [],
                    "percent": 0,
                },
            }).execute()
        except Exception as e:
            if "duplicate" in str(e).lower():
                raise ValueError(f"A batch job for this cluster is already running")
            raise

        job_id = result.data[0]["id"]

        t = threading.Thread(
            target=self._run_batch_thread,
            args=(job_id,),
            daemon=True,
            name=f"seo-batch-{job_id[:8]}",
        )
        t.start()
        return job_id

    def _run_batch_thread(self, job_id: str) -> None:
        """Background thread for cluster batch pipeline."""
        acquired = _job_semaphore.acquire(timeout=300)
        if not acquired:
            self._update_job(job_id, status="failed", error="Server busy")
            return
        try:
            asyncio.run(self._execute_cluster_batch(job_id))
        except Exception as e:
            logger.error(f"Batch job {job_id} crashed: {e}", exc_info=True)
            try:
                self._update_job(job_id, status="failed", error=str(e)[:1000])
            except Exception:
                pass
        finally:
            _job_semaphore.release()

    async def _execute_cluster_batch(self, job_id: str) -> None:
        """Execute batch pipeline: pillar first, then spokes, then interlinking."""
        job = self._load_job(job_id)
        if not job:
            return
        config = job.get("config", {})
        brand_id = config["brand_id"]
        org_id = job["organization_id"]
        pillar_keyword = config.get("pillar_keyword", "")
        spokes = config.get("spokes", [])

        self._update_job(job_id, status="running")

        # 1. Generate pillar article
        pillar_result = None
        try:
            self._update_batch_progress(
                job_id, 0, 1 + len(spokes), [],
                label=f"Generating pillar: {pillar_keyword}",
            )
            pillar_job_id = self.start_one_off(
                keyword=pillar_keyword,
                brand_id=brand_id,
                organization_id=org_id,
                article_role="pillar",
            )
            # Wait for pillar to complete
            pillar_result = await self._wait_for_job(pillar_job_id, timeout=600)
            if not pillar_result or pillar_result.get("status") != "completed":
                self._update_job(job_id, status="failed",
                                 error="Pillar article generation failed — aborting batch")
                return
        except Exception as e:
            self._update_job(job_id, status="failed", error=f"Pillar failed: {e}")
            return

        pillar_article_id = (pillar_result.get("result") or {}).get("article_id", "")
        pillar_url = (pillar_result.get("result") or {}).get("published_url", "")
        per_article_results = [{
            "keyword": pillar_keyword,
            "article_id": pillar_article_id,
            "published_url": pillar_url,
            "role": "pillar",
            "status": "completed",
        }]

        # 2. Generate spokes
        all_article_ids = [pillar_article_id] if pillar_article_id else []
        content_fingerprints_parts = []

        for i, spoke in enumerate(spokes):
            if self._is_cancelled(job_id):
                return

            spoke_kw = spoke.get("keyword", "")
            self._update_batch_progress(
                job_id, i + 1, len(spokes) + 1, per_article_results,
                label=f"Generating spoke {i + 1}/{len(spokes)}: {spoke_kw}",
            )

            cluster_ctx = (
                f"This is part of a topic cluster. Pillar article: '{pillar_keyword}'. "
                f"Other spokes: {', '.join(s['keyword'] for s in spokes if s['keyword'] != spoke_kw)}. "
                f"Your unique angle for this spoke: {spoke_kw}"
            )
            fingerprints = "\n".join(content_fingerprints_parts[-5:]) if content_fingerprints_parts else ""

            try:
                spoke_job_id = self.start_one_off(
                    keyword=spoke_kw,
                    brand_id=brand_id,
                    organization_id=org_id,
                    article_role="spoke",
                    cluster_context=cluster_ctx,
                    content_fingerprints=fingerprints,
                )
                spoke_result = await self._wait_for_job(spoke_job_id, timeout=600)
                spoke_article_id = (spoke_result.get("result") or {}).get("article_id", "")
                spoke_url = (spoke_result.get("result") or {}).get("published_url", "")

                if spoke_result and spoke_result.get("status") == "completed":
                    per_article_results.append({
                        "keyword": spoke_kw,
                        "article_id": spoke_article_id,
                        "published_url": spoke_url,
                        "role": "spoke",
                        "status": "completed",
                    })
                    if spoke_article_id:
                        all_article_ids.append(spoke_article_id)
                    content_fingerprints_parts.append(f"Spoke '{spoke_kw}' has been written.")
                else:
                    per_article_results.append({
                        "keyword": spoke_kw,
                        "role": "spoke",
                        "status": "failed",
                        "error": (spoke_result or {}).get("error", "Unknown"),
                    })
            except Exception as e:
                logger.warning(f"Spoke '{spoke_kw}' failed: {e}")
                per_article_results.append({
                    "keyword": spoke_kw, "role": "spoke", "status": "failed", "error": str(e)[:200],
                })

        # 3. Cross-cluster interlinking
        self._update_batch_progress(
            job_id, len(spokes) + 1, len(spokes) + 1, per_article_results,
            label="Cross-linking articles...",
        )
        try:
            from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService
            from viraltracker.core.database import get_supabase_client
            link_svc = InterlinkingService(supabase_client=get_supabase_client())
            for aid in all_article_ids:
                await asyncio.to_thread(link_svc.auto_link_article, aid)
        except Exception as e:
            logger.warning(f"Cross-cluster interlinking failed (non-fatal): {e}")

        # 4. Complete
        completed_count = sum(1 for r in per_article_results if r.get("status") == "completed")
        final_status = "completed" if completed_count >= 2 else "failed"

        self._update_job(
            job_id,
            status=final_status,
            result={
                "per_article_results": per_article_results,
                "total": len(per_article_results),
                "completed": completed_count,
                "failed": len(per_article_results) - completed_count,
            },
        )

    # =========================================================================
    # JOB QUERY METHODS
    # =========================================================================

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress for UI polling."""
        result = (
            self.supabase.table("seo_workflow_jobs")
            .select("id, status, progress, result, error, config, created_at, updated_at, paused_at")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_active_jobs(self, brand_id: str) -> List[Dict[str, Any]]:
        """Get all running/paused/pending jobs for a brand."""
        result = (
            self.supabase.table("seo_workflow_jobs")
            .select("id, status, progress, config, created_at, updated_at, paused_at")
            .eq("brand_id", brand_id)
            .in_("status", ["pending", "running", "paused"])
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    def get_recent_jobs(self, brand_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Job history for the UI."""
        result = (
            self.supabase.table("seo_workflow_jobs")
            .select("id, status, progress, config, result, error, created_at, updated_at, job_type")
            .eq("brand_id", brand_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def cleanup_stale_jobs(self) -> int:
        """Cancel jobs paused >24 hours or running with no update for >30 minutes."""
        now = datetime.now(timezone.utc)
        cleaned = 0

        # Paused jobs > 24 hours
        cutoff_paused = (now - timedelta(hours=24)).isoformat()
        stale_paused = (
            self.supabase.table("seo_workflow_jobs")
            .select("id")
            .eq("status", "paused")
            .lt("paused_at", cutoff_paused)
            .execute()
        ).data or []

        for job in stale_paused:
            self._update_job(job["id"], status="cancelled", error="Auto-cancelled: paused >24 hours")
            cleaned += 1

        # Running jobs with no progress update > 30 minutes
        cutoff_running = (now - timedelta(minutes=30)).isoformat()
        stale_running = (
            self.supabase.table("seo_workflow_jobs")
            .select("id")
            .eq("status", "running")
            .lt("updated_at", cutoff_running)
            .execute()
        ).data or []

        for job in stale_running:
            self._update_job(job["id"], status="failed", error="Auto-failed: no progress for >30 minutes")
            cleaned += 1

        if cleaned:
            logger.info(f"Cleaned up {cleaned} stale workflow jobs")
        return cleaned

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        result = (
            self.supabase.table("seo_workflow_jobs")
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        error: Optional[str] = None,
        result: Optional[Dict] = None,
        progress_update: Optional[Dict] = None,
    ) -> None:
        """Update job fields."""
        data = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if status:
            data["status"] = status
        if error is not None:
            data["error"] = error
        if result is not None:
            data["result"] = result
        if progress_update:
            # Merge into existing progress
            job = self._load_job(job_id)
            if job:
                progress = job.get("progress", {})
                progress.update(progress_update)
                data["progress"] = progress

        self.supabase.table("seo_workflow_jobs").update(data).eq("id", job_id).execute()

    def _update_job_config(self, job_id: str, extra: Dict[str, Any]) -> None:
        """Merge extra keys into job config."""
        job = self._load_job(job_id)
        if job:
            config = job.get("config", {})
            config.update(extra)
            self.supabase.table("seo_workflow_jobs").update({
                "config": config,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).execute()

    def _advance_step(self, job_id: str, step: str) -> None:
        """Advance pipeline to a new step."""
        job = self._load_job(job_id)
        if not job:
            return
        progress = job.get("progress", {})
        completed = progress.get("steps_completed", [])

        current = progress.get("current_step")
        if current and current not in completed and current != step:
            completed.append(current)

        step_idx = ONE_OFF_STEPS.index(step) if step in ONE_OFF_STEPS else len(completed)
        pct = int(step_idx / len(ONE_OFF_STEPS) * 100)

        progress.update({
            "current_step": step,
            "current_step_label": STEP_LABELS.get(step, step),
            "steps_completed": completed,
            "percent": pct,
        })

        self.supabase.table("seo_workflow_jobs").update({
            "progress": progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    def _is_cancelled(self, job_id: str) -> bool:
        """Check if job has been cancelled."""
        job = self._load_job(job_id)
        if not job or job.get("status") == "cancelled":
            if job and job.get("status") != "cancelled":
                self._update_job(job_id, status="cancelled")
            return True
        return False

    def _pause_job(self, job_id: str, step: str, data: Dict[str, Any]) -> None:
        """Pause job for step-through review."""
        now = datetime.now(timezone.utc).isoformat()
        job = self._load_job(job_id)
        progress = job.get("progress", {}) if job else {}
        progress["paused_data"] = data

        self.supabase.table("seo_workflow_jobs").update({
            "status": "paused",
            "paused_at": now,
            "progress": progress,
            "updated_at": now,
        }).eq("id", job_id).execute()
        logger.info(f"Job {job_id} paused at step '{step}'")

    def _resolve_project(self, brand_id: str, organization_id: str) -> str:
        """Get or create 'Quick Write' project for this brand."""
        result = (
            self.supabase.table("seo_projects")
            .select("id")
            .eq("brand_id", brand_id)
            .eq("name", "Quick Write")
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["id"]

        new = self.supabase.table("seo_projects").insert({
            "brand_id": brand_id,
            "organization_id": organization_id,
            "name": "Quick Write",
            "status": "active",
        }).execute()
        return new.data[0]["id"]

    def _update_batch_progress(
        self,
        job_id: str,
        current_index: int,
        total: int,
        per_article_results: List[Dict],
        label: str = "",
    ) -> None:
        """Update batch progress."""
        pct = int(current_index / total * 100) if total else 0
        update = {
            "current_article_index": current_index,
            "per_article_results": per_article_results,
            "percent": pct,
        }
        if label:
            update["current_step_label"] = label
        self._update_job(job_id, progress_update=update)

    async def _wait_for_job(self, child_job_id: str, timeout: int = 600) -> Optional[Dict]:
        """Wait for a child job to complete (for batch pipeline)."""
        start = time.time()
        while time.time() - start < timeout:
            job = self._load_job(child_job_id)
            if job and job.get("status") in ("completed", "failed", "cancelled"):
                return job
            await asyncio.sleep(5)
        return None

    @staticmethod
    def _parse_frontmatter(text: str) -> Optional[Dict[str, Any]]:
        """Parse YAML frontmatter from Phase C output."""
        match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not match:
            return None

        frontmatter = {}
        for line in match.group(1).split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().strip('"').strip("'")
                value = value.strip().strip('"').strip("'")
                if key == "tags":
                    # Parse tags: [slug1, slug2] or slug1, slug2
                    value = value.strip("[]")
                    frontmatter["tags"] = [t.strip().strip('"').strip("'") for t in value.split(",") if t.strip()]
                elif key in ("title", "description", "keyword", "author"):
                    frontmatter[key] = value

        return frontmatter if frontmatter else None

    @staticmethod
    def _build_schema_markup(
        article_id: str,
        published_url: str,
        author_ctx: Dict[str, Any],
        brand_config: Dict[str, Any],
        brand_ctx: Dict[str, Any],
        sb,
    ) -> Optional[Dict[str, Any]]:
        """Build Article schema JSON-LD programmatically."""
        article = sb.table("seo_articles").select(
            "seo_title, title, keyword, meta_description, hero_image_url, created_at"
        ).eq("id", article_id).limit(1).execute()
        if not article.data:
            return None

        a = article.data[0]
        headline = a.get("seo_title") or a.get("title") or a.get("keyword", "")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        publisher = brand_config.get("schema_publisher") or {}
        brand_name = brand_ctx.get("brand_name", "")

        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": headline,
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": published_url or "",
            },
            "author": {
                "@type": "Person",
                "name": author_ctx.get("name", ""),
            },
            "datePublished": a.get("created_at", now)[:10],
            "dateModified": now,
            "publisher": {
                "@type": "Organization",
                "name": publisher.get("name") or brand_name,
            },
        }

        if a.get("hero_image_url"):
            schema["image"] = a["hero_image_url"]
        if a.get("meta_description"):
            schema["description"] = a["meta_description"]
        if author_ctx.get("author_url"):
            schema["author"]["url"] = author_ctx["author_url"]
        if publisher.get("logo_url"):
            schema["publisher"]["logo"] = {
                "@type": "ImageObject",
                "url": publisher["logo_url"],
            }

        return schema
