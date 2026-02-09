"""
LandingPageAnalysisService — Orchestrates the 4-skill landing page analysis pipeline.

Pattern follows belief_analysis_service.py: sequential AI calls with run_agent_with_tracking.

Pipeline:
  Skill 1 (Page Classifier) → Skill 2 (Element Detector) → [parallel] Skill 3 (Gap Analyzer) + Skill 4 (Copy Scorer)

Supports partial failure: each skill result is saved as it completes.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic_ai import Agent

from viraltracker.services.landing_page_analysis.utils import parse_llm_json as _parse_llm_json

logger = logging.getLogger(__name__)


class LandingPageAnalysisService:
    """Orchestrates the landing page analysis pipeline (Skills 1-4).

    Usage:
        service = LandingPageAnalysisService()
        service.set_tracking_context(tracker, user_id, org_id)

        # Option A: Scrape a URL
        page_data = service.scrape_landing_page(url)

        # Option B: Load from existing record
        page_data = service.load_from_competitor_lp(competitor_lp_id)

        # Run full analysis
        result = await service.run_full_analysis(
            page_content=page_data["markdown"],
            page_url=page_data["url"],
            screenshot_b64=page_data.get("screenshot"),
            org_id=org_id,
            progress_callback=lambda step, msg: ...,
        )
    """

    def __init__(self, supabase=None):
        from viraltracker.core.database import get_supabase_client
        self.supabase = supabase or get_supabase_client()
        self._tracker = None
        self._user_id: Optional[str] = None
        self._org_id: Optional[str] = None

    def set_tracking_context(self, tracker, user_id: Optional[str], org_id: str):
        """Set usage tracking context for billing."""
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # ------------------------------------------------------------------
    # Input methods
    # ------------------------------------------------------------------

    def scrape_landing_page(self, url: str) -> Dict[str, Any]:
        """Scrape a URL via FireCrawl, returning markdown + screenshot (base64)."""
        import base64
        import httpx
        from firecrawl.v2.types import ScreenshotFormat
        from viraltracker.services.web_scraping_service import WebScrapingService

        scraper = WebScrapingService()
        result = scraper.scrape_url(
            url,
            formats=["markdown", ScreenshotFormat(full_page=True)],
        )

        if not result.success:
            raise ValueError(f"Failed to scrape {url}: {result.error}")

        # FireCrawl v4 returns a URL for screenshots — download and convert to base64
        screenshot_b64 = None
        if result.screenshot and result.screenshot.startswith("http"):
            try:
                resp = httpx.get(result.screenshot, timeout=30)
                resp.raise_for_status()
                screenshot_b64 = base64.b64encode(resp.content).decode("utf-8")
            except Exception as e:
                logger.warning(f"Failed to download screenshot: {e}")
        elif result.screenshot:
            screenshot_b64 = result.screenshot

        return {
            "url": url,
            "markdown": result.markdown or "",
            "screenshot": screenshot_b64,
            "source_type": "url",
            "source_id": None,
        }

    def load_from_competitor_lp(self, competitor_lp_id: str) -> Dict[str, Any]:
        """Load content from an existing competitor_landing_pages record."""
        result = (
            self.supabase.table("competitor_landing_pages")
            .select("id, url, raw_markdown, scraped_content")
            .eq("id", competitor_lp_id)
            .single()
            .execute()
        )
        data = result.data
        markdown = data.get("raw_markdown") or data.get("scraped_content") or ""

        return {
            "url": data.get("url", ""),
            "markdown": markdown,
            "screenshot": None,
            "source_type": "competitor_lp",
            "source_id": competitor_lp_id,
        }

    def load_from_brand_lp(self, brand_lp_id: str) -> Dict[str, Any]:
        """Load content from an existing brand_landing_pages record."""
        result = (
            self.supabase.table("brand_landing_pages")
            .select("id, url, raw_markdown")
            .eq("id", brand_lp_id)
            .single()
            .execute()
        )
        data = result.data
        return {
            "url": data.get("url", ""),
            "markdown": data.get("raw_markdown") or "",
            "screenshot": None,
            "source_type": "brand_lp",
            "source_id": brand_lp_id,
        }

    # ------------------------------------------------------------------
    # Analysis pipeline
    # ------------------------------------------------------------------

    async def run_full_analysis(
        self,
        page_content: str,
        page_url: str,
        org_id: str,
        screenshot_b64: Optional[str] = None,
        source_type: str = "url",
        source_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run the full 4-skill analysis pipeline.

        Args:
            page_content: Page markdown text
            page_url: Original URL
            org_id: Organization ID for multi-tenancy
            screenshot_b64: Optional base64 screenshot for multimodal analysis
            source_type: 'url', 'competitor_lp', or 'brand_lp'
            source_id: FK to source table if applicable
            progress_callback: Called with (step_number, status_message)

        Returns:
            Dict with analysis_id and all skill results
        """
        start_time = time.time()

        def _progress(step: int, msg: str):
            if progress_callback:
                try:
                    progress_callback(step, msg)
                except Exception:
                    pass

        # Create initial record
        analysis_id = self._create_analysis_record(
            org_id=org_id,
            url=page_url,
            source_type=source_type,
            source_id=source_id,
            page_markdown=page_content,
            screenshot_storage_path=None,
        )

        try:
            # --- Skill 1: Page Classifier ---
            _progress(1, "Classifying page (awareness, sophistication, architecture)...")
            classification = await self._run_page_classifier(page_content, screenshot_b64)
            self._save_partial(analysis_id, classification=classification, status="processing")

            # --- Skill 2: Element Detector ---
            _progress(2, "Detecting elements (34 elements across 6 sections)...")
            elements = await self._run_element_detector(page_content, classification, screenshot_b64)
            self._save_partial(analysis_id, elements=elements)

            # --- Skills 3 + 4 in parallel ---
            _progress(3, "Analyzing gaps and scoring copy...")
            gap_result, score_result = await asyncio.gather(
                self._run_gap_analyzer(elements, classification),
                self._run_copy_scorer(page_content, elements, classification),
                return_exceptions=True,
            )

            # Save whatever succeeded
            final_status = "completed"
            error_parts = []

            if isinstance(gap_result, Exception):
                logger.error(f"Gap analyzer failed: {gap_result}")
                error_parts.append(f"Gap analysis failed: {gap_result}")
                gap_result = None
                final_status = "partial"
            else:
                self._save_partial(analysis_id, gap_analysis=gap_result)

            if isinstance(score_result, Exception):
                logger.error(f"Copy scorer failed: {score_result}")
                error_parts.append(f"Copy scorer failed: {score_result}")
                score_result = None
                final_status = "partial"
            else:
                self._save_partial(analysis_id, copy_scores=score_result)

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Final update with denormalized fields
            self._finalize_analysis(
                analysis_id,
                classification=classification,
                elements=elements,
                gap_analysis=gap_result,
                copy_scores=score_result,
                status=final_status,
                error_message="; ".join(error_parts) if error_parts else None,
                processing_time_ms=elapsed_ms,
            )

            _progress(4, "Analysis complete!")

            return {
                "analysis_id": analysis_id,
                "url": page_url,
                "status": final_status,
                "classification": classification,
                "elements": elements,
                "gap_analysis": gap_result,
                "copy_scores": score_result,
                "processing_time_ms": elapsed_ms,
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Analysis pipeline failed: {e}")
            self._save_partial(
                analysis_id,
                status="failed",
                error_message=str(e),
                processing_time_ms=elapsed_ms,
            )
            raise

    # ------------------------------------------------------------------
    # Individual skill runners
    # ------------------------------------------------------------------

    async def _run_page_classifier(
        self, content: str, screenshot_b64: Optional[str] = None
    ) -> Dict[str, Any]:
        """Skill 1: Classify page awareness, sophistication, architecture."""
        from .prompts.page_classifier import PAGE_CLASSIFIER_SYSTEM_PROMPT

        if screenshot_b64:
            return await self._run_gemini_multimodal(
                PAGE_CLASSIFIER_SYSTEM_PROMPT,
                content,
                screenshot_b64,
                operation="page_classifier",
            )

        return await self._run_text_agent(
            PAGE_CLASSIFIER_SYSTEM_PROMPT,
            content,
            model_key="complex",
            operation="page_classifier",
        )

    async def _run_element_detector(
        self,
        content: str,
        classification: Dict[str, Any],
        screenshot_b64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Skill 2: Detect all elements on the page."""
        from .prompts.element_detector import ELEMENT_DETECTOR_SYSTEM_PROMPT

        context = (
            f"Page Classification Context:\n"
            f"{json.dumps(classification, indent=2)}\n\n"
            f"Page Content:\n{content}"
        )

        if screenshot_b64:
            return await self._run_gemini_multimodal(
                ELEMENT_DETECTOR_SYSTEM_PROMPT,
                context,
                screenshot_b64,
                operation="element_detector",
            )

        return await self._run_text_agent(
            ELEMENT_DETECTOR_SYSTEM_PROMPT,
            context,
            model_key="complex",
            operation="element_detector",
        )

    async def _run_gap_analyzer(
        self, elements: Dict[str, Any], classification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Skill 3: Identify gaps vs ideal element set."""
        from .prompts.gap_analyzer import GAP_ANALYZER_SYSTEM_PROMPT

        context = (
            f"Page Classification:\n{json.dumps(classification, indent=2)}\n\n"
            f"Detected Elements:\n{json.dumps(elements, indent=2)}"
        )

        return await self._run_text_agent(
            GAP_ANALYZER_SYSTEM_PROMPT,
            context,
            model_key="fast",
            operation="gap_analyzer",
        )

    async def _run_copy_scorer(
        self,
        content: str,
        elements: Dict[str, Any],
        classification: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Skill 4: Score copy quality for each element."""
        from .prompts.copy_scorer import COPY_SCORER_SYSTEM_PROMPT

        context = (
            f"Page Classification:\n{json.dumps(classification, indent=2)}\n\n"
            f"Detected Elements:\n{json.dumps(elements, indent=2)}\n\n"
            f"Raw Page Content (use this to find and score actual copy text):\n{content}"
        )

        return await self._run_text_agent(
            COPY_SCORER_SYSTEM_PROMPT,
            context,
            model_key="complex",
            operation="copy_scorer",
        )

    # ------------------------------------------------------------------
    # LLM execution helpers
    # ------------------------------------------------------------------

    async def _run_text_agent(
        self,
        system_prompt: str,
        user_content: str,
        model_key: str = "complex",
        operation: str = "analysis",
        max_tokens: int = 16384,
    ) -> Dict[str, Any]:
        """Run a PydanticAI text agent with tracking."""
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_with_tracking

        model = Config.get_model(model_key)
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            model_settings=ModelSettings(max_tokens=max_tokens),
        )

        result = await run_agent_with_tracking(
            agent,
            user_content,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="landing_page_analysis",
            operation=operation,
        )

        return _parse_llm_json(result.output)

    async def _run_gemini_multimodal(
        self,
        system_prompt: str,
        text_content: str,
        screenshot_b64: str,
        operation: str = "analysis",
    ) -> Dict[str, Any]:
        """Run Gemini multimodal analysis (text + screenshot)."""
        from viraltracker.services.gemini_service import GeminiService

        gemini = GeminiService()
        if self._tracker:
            gemini.set_tracking_context(
                self._tracker, self._user_id, self._org_id
            )

        prompt = f"{system_prompt}\n\nPage content:\n{text_content}"
        response = await gemini.analyze_image(screenshot_b64, prompt)
        return _parse_llm_json(response)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _create_analysis_record(
        self,
        org_id: str,
        url: str,
        source_type: str,
        source_id: Optional[str],
        page_markdown: Optional[str],
        screenshot_storage_path: Optional[str],
    ) -> str:
        """Create initial analysis record, return its ID."""
        record = {
            "organization_id": org_id,
            "url": url,
            "source_type": source_type,
            "page_markdown": page_markdown,
            "screenshot_storage_path": screenshot_storage_path,
            "status": "processing",
        }
        if source_id:
            record["source_id"] = source_id

        result = self.supabase.table("landing_page_analyses").insert(record).execute()
        return result.data[0]["id"]

    def _save_partial(self, analysis_id: str, **fields):
        """Update specific fields on the analysis record."""
        update = {}
        for key, value in fields.items():
            if key in ("classification", "elements", "gap_analysis", "copy_scores"):
                update[key] = value if isinstance(value, dict) else json.loads(json.dumps(value))
            else:
                update[key] = value

        if update:
            self.supabase.table("landing_page_analyses").update(update).eq("id", analysis_id).execute()

    def _finalize_analysis(
        self,
        analysis_id: str,
        classification: Optional[Dict],
        elements: Optional[Dict],
        gap_analysis: Optional[Dict],
        copy_scores: Optional[Dict],
        status: str,
        error_message: Optional[str],
        processing_time_ms: int,
    ):
        """Final update with denormalized fields for filtering."""
        update: Dict[str, Any] = {
            "status": status,
            "processing_time_ms": processing_time_ms,
        }
        if error_message:
            update["error_message"] = error_message

        # Denormalize classification fields
        if classification:
            pc = classification.get("page_classifier", classification)
            al = pc.get("awareness_level", {})
            ms = pc.get("market_sophistication", {})
            pa = pc.get("page_architecture", {})
            update["awareness_level"] = al.get("primary") if isinstance(al, dict) else al
            update["market_sophistication"] = ms.get("level") if isinstance(ms, dict) else ms
            update["architecture_type"] = pa.get("type") if isinstance(pa, dict) else pa

        # Denormalize element count
        if elements:
            ed = elements.get("element_detection", elements)
            update["element_count"] = ed.get("total_elements_detected", 0)

        # Denormalize gap score
        if gap_analysis:
            ga = gap_analysis.get("gap_analysis", gap_analysis)
            update["completeness_score"] = ga.get("overall_completeness_score", 0)

        # Denormalize copy scores
        if copy_scores:
            cs = copy_scores.get("copy_score", copy_scores)
            update["overall_score"] = cs.get("overall_score", 0)
            update["overall_grade"] = cs.get("overall_grade", "")

        self.supabase.table("landing_page_analyses").update(update).eq("id", analysis_id).execute()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Get a single analysis by ID."""
        result = (
            self.supabase.table("landing_page_analyses")
            .select("*")
            .eq("id", analysis_id)
            .single()
            .execute()
        )
        return result.data

    def list_analyses(
        self,
        org_id: str,
        brand_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List analyses for an organization, most recent first."""
        query = (
            self.supabase.table("landing_page_analyses")
            .select(
                "id, url, source_type, awareness_level, architecture_type, "
                "element_count, completeness_score, overall_score, overall_grade, "
                "status, processing_time_ms, created_at"
            )
        )
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def get_competitor_lps(self, brand_id: str) -> List[Dict[str, Any]]:
        """Get competitor landing pages for dropdown selection."""
        result = (
            self.supabase.table("competitor_landing_pages")
            .select("id, url, page_title, competitor_id, competitors(name)")
            .eq("brand_id", brand_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    def get_brand_lps(self, brand_id: str) -> List[Dict[str, Any]]:
        """Get brand landing pages for dropdown selection."""
        result = (
            self.supabase.table("brand_landing_pages")
            .select("id, url, page_title")
            .eq("brand_id", brand_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
