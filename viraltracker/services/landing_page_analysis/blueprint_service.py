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
            # 4-5. Run Skill 5 LLM calls (chunked — steps 3 & 4 via callback)
            blueprint_data = await self._run_reconstruction(
                analysis=analysis,
                brand_profile=brand_profile,
                progress_callback=_progress,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            # 6. Extract metadata and save
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

            # Determine status: partial if chunk 2 failed
            bp_status = "completed"
            if metadata.get("partial"):
                bp_status = "partial"

            self._finalize_blueprint(
                blueprint_id=blueprint_id,
                blueprint=blueprint_data,
                sections_count=sections_count,
                elements_mapped=populated,
                content_needed_count=content_needed_count,
                content_gaps=brand_profile.get("gaps", []),
                processing_time_ms=elapsed_ms,
                status=bp_status,
            )

            _progress(5, "Blueprint complete!")

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
                "status": bp_status,
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
    # Skill 5 runner (chunked: 2 sequential LLM calls)
    # ------------------------------------------------------------------

    # Sections assigned to each chunk
    _CHUNK_1_SECTIONS = frozenset([
        "above_the_fold",
        "education_and_persuasion",
        "product_reveal_and_features",
    ])
    _CHUNK_2_SECTIONS = frozenset([
        "social_proof",
        "conversion_and_offer",
        "closing_and_trust",
    ])

    async def _run_reconstruction(
        self,
        analysis: Dict[str, Any],
        brand_profile: Dict[str, Any],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run Skill 5: Reconstruction Blueprint via 2 chunked LLM calls.

        Call 1 generates strategy_summary + top-of-funnel sections.
        Call 2 receives Call 1's strategy_summary for tone consistency
        and generates bottom-of-funnel sections + bonus_sections +
        content_needed_summary + metadata.
        Results are merged into the final blueprint structure.
        """
        def _progress(step: int, msg: str):
            if progress_callback:
                try:
                    progress_callback(step, msg)
                except Exception:
                    pass

        # Shared context for both chunks
        profile_for_prompt = {k: v for k, v in brand_profile.items() if k != "gaps"}
        elements = analysis.get("elements", {})

        chunk1_elements, chunk2_elements = self._split_elements_into_chunks(elements)
        logger.info(
            f"Blueprint chunking: {len(chunk1_elements)} elements in chunk 1, "
            f"{len(chunk2_elements)} elements in chunk 2"
        )

        # --- Call 1: top-of-funnel ---
        _progress(3, "Blueprint Part 1 (strategy + top sections)...")
        chunk1_prompt = self._build_chunk_user_prompt(
            analysis=analysis,
            profile_for_prompt=profile_for_prompt,
            chunk_elements=chunk1_elements,
            chunk_number=1,
            strategy_summary=None,
        )
        chunk1_data = await self._run_blueprint_chunk(
            user_content=chunk1_prompt,
            operation_suffix="chunk_1",
        )

        rb1 = chunk1_data.get("reconstruction_blueprint", chunk1_data)
        strategy_summary = rb1.get("strategy_summary", {})

        # --- Call 2: bottom-of-funnel ---
        _progress(4, "Blueprint Part 2 (remaining + summary)...")
        chunk2_prompt = self._build_chunk_user_prompt(
            analysis=analysis,
            profile_for_prompt=profile_for_prompt,
            chunk_elements=chunk2_elements,
            chunk_number=2,
            strategy_summary=strategy_summary,
        )

        try:
            chunk2_data = await self._run_blueprint_chunk(
                user_content=chunk2_prompt,
                operation_suffix="chunk_2",
            )
        except Exception as e:
            logger.error(f"Blueprint chunk 2 failed: {e} — returning partial from chunk 1")
            # Return chunk 1 as partial blueprint
            rb1.setdefault("bonus_sections", [])
            rb1.setdefault("content_needed_summary", [])
            rb1.setdefault("metadata", {})
            rb1["metadata"]["partial"] = True
            rb1["metadata"]["error"] = f"Chunk 2 failed: {e}"
            return chunk1_data

        return self._merge_blueprint_chunks(chunk1_data, chunk2_data)

    def _split_elements_into_chunks(
        self, elements: Dict[str, Any]
    ) -> tuple:
        """Split Skill 2 detected elements into 2 groups by section name.

        Returns:
            (chunk1_elements, chunk2_elements) — each is a dict of
            section_name → section_data for the sections in that chunk.
        """
        ed = elements.get("element_detection", elements) if elements else {}
        sections = ed.get("sections", {})

        chunk1: Dict[str, Any] = {}
        chunk2: Dict[str, Any] = {}

        for section_name, section_data in sections.items():
            normalised = section_name.lower().strip()
            if normalised in self._CHUNK_1_SECTIONS:
                chunk1[section_name] = section_data
            elif normalised in self._CHUNK_2_SECTIONS:
                chunk2[section_name] = section_data
            else:
                # Unknown section — put in whichever chunk is smaller
                if len(chunk1) <= len(chunk2):
                    chunk1[section_name] = section_data
                else:
                    chunk2[section_name] = section_data

        return chunk1, chunk2

    def _build_chunk_user_prompt(
        self,
        analysis: Dict[str, Any],
        profile_for_prompt: Dict[str, Any],
        chunk_elements: Dict[str, Any],
        chunk_number: int,
        strategy_summary: Optional[Dict[str, Any]],
    ) -> str:
        """Build the user prompt for a single blueprint chunk.

        Chunk 1 asks for strategy_summary + sections for its elements.
        Chunk 2 receives strategy_summary for tone consistency and asks for
        remaining sections + bonus_sections + content_needed_summary + metadata.
        """
        parts: List[str] = []

        # Shared analysis context (classification, gaps, copy scores always included)
        parts.append("## COMPETITOR ANALYSIS RESULTS\n")
        parts.append(f"### Page Classification (Skill 1)\n{json.dumps(analysis.get('classification', {}), indent=2)}\n")
        parts.append(f"### Element Detection (Skill 2) — THIS CHUNK ONLY\n{json.dumps(chunk_elements, indent=2)}\n")
        parts.append(f"### Gap Analysis (Skill 3)\n{json.dumps(analysis.get('gap_analysis', {}), indent=2)}\n")
        parts.append(f"### Copy Scores (Skill 4)\n{json.dumps(analysis.get('copy_scores', {}), indent=2)}\n")
        parts.append(f"## BRAND PROFILE\n\n{json.dumps(profile_for_prompt, indent=2)}\n")

        if chunk_number == 1:
            parts.append(
                "## INSTRUCTIONS — CHUNK 1 of 2\n\n"
                "Generate the `strategy_summary` and the `sections` array "
                "for ONLY the elements listed above (above_the_fold, "
                "education_and_persuasion, product_reveal_and_features). "
                "Do NOT generate bonus_sections, content_needed_summary, or metadata yet.\n\n"
                "Output valid JSON matching the reconstruction_blueprint schema, "
                "but include only `strategy_summary` and `sections`.\n"
            )
        else:
            parts.append(
                "## STRATEGY SUMMARY FROM PART 1 (use for tone consistency)\n\n"
                f"{json.dumps(strategy_summary or {}, indent=2)}\n\n"
            )
            parts.append(
                "## INSTRUCTIONS — CHUNK 2 of 2\n\n"
                "Generate the `sections` array for ONLY the elements listed above "
                "(social_proof, conversion_and_offer, closing_and_trust). "
                "Continue the flow_order numbering from Part 1.\n\n"
                "Also generate:\n"
                "- `bonus_sections` — for critical gaps from the Gap Analysis\n"
                "- `content_needed_summary` — aggregated across ALL sections (both parts)\n"
                "- `metadata` — counts across ALL sections (both parts); you may estimate Part 1 counts\n\n"
                "Do NOT regenerate `strategy_summary` (it was produced in Part 1).\n\n"
                "Output valid JSON matching the reconstruction_blueprint schema, "
                "but omit the `strategy_summary` key.\n"
            )

        parts.append("Generate the reconstruction blueprint chunk now.")
        return "\n".join(parts)

    async def _run_blueprint_chunk(
        self,
        user_content: str,
        operation_suffix: str,
    ) -> Dict[str, Any]:
        """Execute a single blueprint LLM call with max_tokens=16384.

        Args:
            user_content: The fully-built user prompt for this chunk.
            operation_suffix: Label for tracking, e.g. 'chunk_1' or 'chunk_2'.

        Returns:
            Parsed JSON dict from the LLM response.
        """
        from .prompts.reconstruction import RECONSTRUCTION_SYSTEM_PROMPT
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_stream_with_tracking
        from pydantic_ai.settings import ModelSettings

        model_settings = ModelSettings(max_tokens=16384, timeout=600)
        model = Config.get_model("complex")
        agent = Agent(
            model=model,
            system_prompt=RECONSTRUCTION_SYSTEM_PROMPT,
            model_settings=model_settings,
        )

        result = await run_agent_stream_with_tracking(
            agent,
            user_content,
            model_settings=model_settings,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="landing_page_analysis",
            operation=f"reconstruction_blueprint_{operation_suffix}",
        )

        raw = result.output
        logger.info(
            f"Blueprint {operation_suffix} response: {len(raw)} chars, "
            f"usage={result.usage()}, "
            f"first_100={raw[:100]!r}, last_100={raw[-100:]!r}"
        )
        return _parse_llm_json(raw)

    def _merge_blueprint_chunks(
        self,
        chunk1_data: Dict[str, Any],
        chunk2_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge 2 chunk results into the final reconstruction_blueprint structure.

        Takes strategy_summary + sections from chunk 1, sections + bonus_sections +
        content_needed_summary from chunk 2. Recomputes metadata from actual data.
        """
        rb1 = chunk1_data.get("reconstruction_blueprint", chunk1_data)
        rb2 = chunk2_data.get("reconstruction_blueprint", chunk2_data)

        sections_1 = rb1.get("sections", [])
        sections_2 = rb2.get("sections", [])
        all_sections = sections_1 + sections_2

        bonus = rb2.get("bonus_sections", [])
        content_needed = rb2.get("content_needed_summary", [])

        # Recompute metadata from actual merged data (don't trust LLM counts)
        all_items = all_sections + bonus
        populated = sum(1 for s in all_items if s.get("content_status") == "populated")
        partial = sum(1 for s in all_items if s.get("content_status") == "partial")
        content_needed_count = sum(1 for s in all_items if s.get("content_status") == "CONTENT_NEEDED")

        # Preserve any LLM metadata fields (brand_name, product_name, etc.)
        llm_metadata = rb2.get("metadata", {})
        metadata = {
            **llm_metadata,
            "total_sections": len(all_items),
            "populated_count": populated,
            "partial_count": partial,
            "content_needed_count": content_needed_count,
            "bonus_sections_added": len(bonus),
        }

        merged = {
            "reconstruction_blueprint": {
                "strategy_summary": rb1.get("strategy_summary", {}),
                "sections": all_sections,
                "bonus_sections": bonus,
                "content_needed_summary": content_needed,
                "metadata": metadata,
            }
        }

        logger.info(
            f"Blueprint merged: {len(all_sections)} sections + {len(bonus)} bonus, "
            f"{populated} populated, {partial} partial, {content_needed_count} need content"
        )
        return merged

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
