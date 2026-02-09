"""
ReconstructionBlueprintService — Orchestrates Skill 5: mapping analysis to brand-specific blueprint.

Pattern follows analysis_service.py: AI call with run_agent_with_tracking, JSON parsing, persistence.

Pipeline:
  1. Load stored analysis (Skills 1-4)
  2. Aggregate brand profile via BrandProfileService
  3. Run Skill 5 LLM call
  4. Save to landing_page_blueprints
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic_ai import Agent

from viraltracker.services.landing_page_analysis.utils import parse_llm_json as _parse_llm_json

logger = logging.getLogger(__name__)


class ReconstructionBlueprintService:
    """Orchestrates Skill 5: reconstruction blueprint generation.

    Usage:
        service = ReconstructionBlueprintService()
        service.set_tracking_context(tracker, user_id, org_id)

        result = await service.generate_blueprint(
            analysis_id=analysis_id,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,  # optional
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
    # Blueprint generation
    # ------------------------------------------------------------------

    async def generate_blueprint(
        self,
        analysis_id: str,
        brand_id: str,
        product_id: str,
        org_id: str,
        offer_variant_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a reconstruction blueprint from analysis + brand profile.

        Args:
            analysis_id: UUID of the source landing page analysis
            brand_id: UUID of the target brand
            product_id: UUID of the target product
            org_id: Organization ID for multi-tenancy
            offer_variant_id: Optional specific offer variant (defaults to product default)
            progress_callback: Called with (step_number, status_message)

        Returns:
            Dict with blueprint_id, blueprint data, gaps, and metadata
        """
        start_time = time.time()

        def _progress(step: int, msg: str):
            if progress_callback:
                try:
                    progress_callback(step, msg)
                except Exception:
                    pass

        # 1. Load stored analysis
        _progress(1, "Loading analysis results...")
        analysis = self._load_analysis(analysis_id)
        if not analysis:
            raise ValueError(f"Analysis {analysis_id} not found")

        if analysis.get("status") not in ("completed", "partial"):
            raise ValueError(
                f"Analysis {analysis_id} has status '{analysis.get('status')}' — "
                "only completed or partial analyses can be used for blueprints."
            )

        # 2. Aggregate brand profile
        _progress(2, "Aggregating brand profile...")
        from .brand_profile_service import BrandProfileService
        brand_service = BrandProfileService(self.supabase)
        brand_profile = brand_service.get_brand_profile(
            brand_id, product_id, offer_variant_id
        )

        # 3. Create blueprint record
        blueprint_id = self._create_blueprint_record(
            org_id=org_id,
            analysis_id=analysis_id,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            source_url=analysis.get("url", ""),
            brand_profile_snapshot=brand_profile,
        )

        try:
            # 4. Run Skill 5 LLM call
            _progress(3, "Generating reconstruction blueprint (Skill 5)...")
            blueprint_data = await self._run_reconstruction(
                analysis=analysis,
                brand_profile=brand_profile,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            # 5. Extract metadata and save
            rb = blueprint_data.get("reconstruction_blueprint", blueprint_data)
            metadata = rb.get("metadata", {})
            sections = rb.get("sections", [])
            bonus = rb.get("bonus_sections", [])
            content_needed = rb.get("content_needed_summary", [])

            sections_count = len(sections) + len(bonus)
            populated = sum(
                1 for s in sections + bonus
                if s.get("content_status") == "populated"
            )
            content_needed_count = sum(
                1 for s in sections + bonus
                if s.get("content_status") == "CONTENT_NEEDED"
            )

            self._finalize_blueprint(
                blueprint_id=blueprint_id,
                blueprint=blueprint_data,
                sections_count=sections_count,
                elements_mapped=populated,
                content_needed_count=content_needed_count,
                content_gaps=brand_profile.get("gaps", []),
                processing_time_ms=elapsed_ms,
                status="completed",
            )

            _progress(4, "Blueprint complete!")

            return {
                "blueprint_id": blueprint_id,
                "analysis_id": analysis_id,
                "brand_id": brand_id,
                "product_id": product_id,
                "source_url": analysis.get("url", ""),
                "blueprint": blueprint_data,
                "brand_profile_gaps": brand_profile.get("gaps", []),
                "sections_count": sections_count,
                "elements_mapped": populated,
                "content_needed_count": content_needed_count,
                "processing_time_ms": elapsed_ms,
                "status": "completed",
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Blueprint generation failed: {e}")
            self._finalize_blueprint(
                blueprint_id=blueprint_id,
                blueprint={},
                sections_count=0,
                elements_mapped=0,
                content_needed_count=0,
                content_gaps=brand_profile.get("gaps", []),
                processing_time_ms=elapsed_ms,
                status="failed",
                error_message=str(e),
            )
            raise

    # ------------------------------------------------------------------
    # Skill 5 runner
    # ------------------------------------------------------------------

    async def _run_reconstruction(
        self,
        analysis: Dict[str, Any],
        brand_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run Skill 5: Reconstruction Blueprint LLM call."""
        from .prompts.reconstruction import RECONSTRUCTION_SYSTEM_PROMPT
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_with_tracking

        # Build the user prompt with analysis + brand profile
        # Remove large fields from brand profile snapshot to keep under token limits
        profile_for_prompt = {k: v for k, v in brand_profile.items() if k != "gaps"}

        user_content = (
            "## COMPETITOR ANALYSIS RESULTS\n\n"
            f"### Page Classification (Skill 1)\n"
            f"{json.dumps(analysis.get('classification', {}), indent=2)}\n\n"
            f"### Element Detection (Skill 2)\n"
            f"{json.dumps(analysis.get('elements', {}), indent=2)}\n\n"
            f"### Gap Analysis (Skill 3)\n"
            f"{json.dumps(analysis.get('gap_analysis', {}), indent=2)}\n\n"
            f"### Copy Scores (Skill 4)\n"
            f"{json.dumps(analysis.get('copy_scores', {}), indent=2)}\n\n"
            f"## BRAND PROFILE\n\n"
            f"{json.dumps(profile_for_prompt, indent=2)}\n\n"
            f"Generate the reconstruction blueprint now."
        )

        from pydantic_ai.settings import ModelSettings

        model = Config.get_model("complex")
        agent = Agent(
            model=model,
            system_prompt=RECONSTRUCTION_SYSTEM_PROMPT,
            model_settings=ModelSettings(max_tokens=16384),
        )

        result = await run_agent_with_tracking(
            agent,
            user_content,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="landing_page_analysis",
            operation="reconstruction_blueprint",
        )

        return _parse_llm_json(result.output)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Load a stored analysis by ID."""
        try:
            result = (
                self.supabase.table("landing_page_analyses")
                .select("*")
                .eq("id", analysis_id)
                .single()
                .execute()
            )
            return result.data
        except Exception as e:
            logger.error(f"Failed to load analysis {analysis_id}: {e}")
            return None

    def _create_blueprint_record(
        self,
        org_id: str,
        analysis_id: str,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str],
        source_url: str,
        brand_profile_snapshot: Dict[str, Any],
    ) -> str:
        """Create initial blueprint record, return its ID."""
        record = {
            "organization_id": org_id,
            "analysis_id": analysis_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "source_url": source_url,
            "brand_profile_snapshot": brand_profile_snapshot,
            "status": "processing",
        }
        if offer_variant_id:
            record["offer_variant_id"] = offer_variant_id

        result = self.supabase.table("landing_page_blueprints").insert(record).execute()
        return result.data[0]["id"]

    def _finalize_blueprint(
        self,
        blueprint_id: str,
        blueprint: Dict[str, Any],
        sections_count: int,
        elements_mapped: int,
        content_needed_count: int,
        content_gaps: List[Dict[str, Any]],
        processing_time_ms: int,
        status: str,
        error_message: Optional[str] = None,
    ):
        """Final update with blueprint data and metadata."""
        update: Dict[str, Any] = {
            "blueprint": blueprint,
            "sections_count": sections_count,
            "elements_mapped": elements_mapped,
            "content_needed_count": content_needed_count,
            "content_gaps": content_gaps,
            "processing_time_ms": processing_time_ms,
            "status": status,
        }
        if error_message:
            update["error_message"] = error_message

        self.supabase.table("landing_page_blueprints").update(update).eq(
            "id", blueprint_id
        ).execute()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_blueprint(self, blueprint_id: str) -> Optional[Dict[str, Any]]:
        """Get a single blueprint by ID."""
        try:
            result = (
                self.supabase.table("landing_page_blueprints")
                .select("*")
                .eq("id", blueprint_id)
                .single()
                .execute()
            )
            return result.data
        except Exception as e:
            logger.error(f"Failed to load blueprint {blueprint_id}: {e}")
            return None

    def list_blueprints(
        self,
        org_id: str,
        analysis_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List blueprints for an organization, most recent first."""
        query = (
            self.supabase.table("landing_page_blueprints")
            .select(
                "id, analysis_id, brand_id, product_id, source_url, "
                "sections_count, elements_mapped, content_needed_count, "
                "status, processing_time_ms, created_at"
            )
        )
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        if analysis_id:
            query = query.eq("analysis_id", analysis_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []
