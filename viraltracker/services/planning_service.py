"""
PlanningService - Belief-First Advertising Planning.

This service handles:
- CRUD for planning entities (offers, JTBDs, angles, plans)
- Plan compilation into deterministic payloads
- Phase validation with warnings
- AI-powered suggestions (Claude Opus 4.5)

Uses DIRECT SERVICE CALLS (not pydantic-graph) because:
- User-driven wizard workflow
- Interactive with user review/editing
- Linear step progression

Architecture:
    Streamlit UI (Wizard) → PlanningService → Supabase
                          → Anthropic API (for suggestions)
"""

import os
import json
import logging
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from ..core.config import Config
from pydantic_ai import Agent
import asyncio
from supabase import Client

from ..core.database import get_supabase_client
from .agent_tracking import run_agent_with_tracking
from .usage_tracker import UsageTracker
from .models import (
    BeliefOffer,
    BeliefSubLayer,
    BeliefJTBDFramed,
    BeliefAngle,
    BeliefPlan,
    BeliefPlanRun,
    CompiledPlanPayload,
)

logger = logging.getLogger(__name__)

# Default model for AI suggestions
DEFAULT_MODEL = "claude-opus-4-5-20251101"


class PlanningService:
    """Service for belief-first advertising planning operations."""

    def __init__(
        self,
        # Kept for backward compatibility but unused
        anthropic_api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize PlanningService.
        """
        self.supabase: Client = get_supabase_client()
        # Usage tracking context
        self._tracker: Optional[UsageTracker] = None
        self._user_id: Optional[str] = None
        self._org_id: Optional[str] = None
        logger.info("PlanningService initialized")

    def set_tracking_context(
        self,
        tracker: UsageTracker,
        user_id: Optional[str],
        org_id: str
    ) -> None:
        """
        Set the tracking context for usage billing.

        Args:
            tracker: UsageTracker instance
            user_id: User ID for billing
            org_id: Organization ID for billing
        """
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # ============================================
    # STORAGE HELPERS
    # ============================================

    def _get_storage_public_url(self, storage_path: str) -> Optional[str]:
        """
        Get public URL for a storage path.

        Args:
            storage_path: Path in format "bucket/path/to/file" or just "path/to/file"

        Returns:
            Public URL or None if failed
        """
        try:
            # Default bucket for scraped assets
            default_bucket = "scraped-assets"

            # Check if path includes bucket
            if "/" in storage_path:
                parts = storage_path.split("/", 1)
                # If first part looks like a bucket name (no extension), use it
                if "." not in parts[0]:
                    bucket = parts[0]
                    path = parts[1]
                else:
                    bucket = default_bucket
                    path = storage_path
            else:
                bucket = default_bucket
                path = storage_path

            return self.supabase.storage.from_(bucket).get_public_url(path)
        except Exception as e:
            logger.warning(f"Failed to get public URL for {storage_path}: {e}")
            return None

    # ============================================
    # BRAND & PRODUCT HELPERS
    # ============================================

    def get_brands(self) -> List[Dict[str, Any]]:
        """
        Fetch all brands for dropdown selection.

        Returns:
            List of brands with id, name
        """
        try:
            result = self.supabase.table("brands").select(
                "id, name"
            ).order("name").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch brands: {e}")
            return []

    def get_products_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch products for a brand.

        Args:
            brand_id: Brand UUID

        Returns:
            List of products with id, name, target_audience, current_offer
        """
        try:
            result = self.supabase.table("products").select(
                "id, name, target_audience, current_offer, benefits, unique_selling_points"
            ).eq("brand_id", str(brand_id)).order("name").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch products for brand {brand_id}: {e}")
            return []

    def get_product(self, product_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetch a single product with full details.

        Args:
            product_id: Product UUID

        Returns:
            Product dict or None
        """
        try:
            result = self.supabase.table("products").select(
                "*, brands(id, name)"
            ).eq("id", str(product_id)).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch product {product_id}: {e}")
            return None

    # ============================================
    # PERSONA HELPERS
    # ============================================

    def get_personas_for_product(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch personas linked to a product.

        Checks both:
        1. Direct product_id on personas_4d table
        2. product_personas junction table

        Args:
            product_id: Product UUID

        Returns:
            List of personas with id, name, snapshot, is_primary
        """
        try:
            personas = []
            seen_ids = set()

            # Method 1: Direct product_id on personas_4d
            direct_result = self.supabase.table("personas_4d").select(
                "id, name, snapshot, persona_type, is_primary"
            ).eq("product_id", str(product_id)).execute()

            for row in direct_result.data or []:
                if row.get("id") and row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    personas.append({
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "snapshot": row.get("snapshot", ""),
                        "persona_type": row.get("persona_type"),
                        "is_primary": row.get("is_primary", False)
                    })

            # Method 2: Junction table (product_personas)
            junction_result = self.supabase.table("product_personas").select(
                "persona_id, is_primary, personas_4d(id, name, snapshot, persona_type)"
            ).eq("product_id", str(product_id)).execute()

            for row in junction_result.data or []:
                persona_data = row.get("personas_4d", {})
                if persona_data and persona_data.get("id") and persona_data["id"] not in seen_ids:
                    seen_ids.add(persona_data["id"])
                    personas.append({
                        "id": persona_data.get("id"),
                        "name": persona_data.get("name"),
                        "snapshot": persona_data.get("snapshot", ""),
                        "persona_type": persona_data.get("persona_type"),
                        "is_primary": row.get("is_primary", False)
                    })

            # Sort: primary first, then by name
            personas.sort(key=lambda p: (not p.get("is_primary", False), p.get("name", "")))
            return personas
        except Exception as e:
            logger.error(f"Failed to get personas for product {product_id}: {e}")
            return []

    def get_persona(self, persona_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetch a single persona with full details.

        Args:
            persona_id: Persona UUID

        Returns:
            Persona dict or None
        """
        try:
            result = self.supabase.table("personas_4d").select("*").eq(
                "id", str(persona_id)
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch persona {persona_id}: {e}")
            return None

    # ============================================
    # OFFER CRUD
    # ============================================

    def create_offer(
        self,
        product_id: UUID,
        name: str,
        description: Optional[str] = None,
        urgency_drivers: Optional[List[str]] = None,
        created_by: Optional[UUID] = None
    ) -> BeliefOffer:
        """
        Create a new offer for a product.

        Args:
            product_id: Product UUID
            name: Offer name
            description: Offer description
            urgency_drivers: List of urgency drivers
            created_by: User UUID

        Returns:
            Created BeliefOffer
        """
        data = {
            "product_id": str(product_id),
            "name": name,
            "description": description,
            "urgency_drivers": urgency_drivers or [],
            "active": True,
        }
        if created_by:
            data["created_by"] = str(created_by)

        result = self.supabase.table("belief_offers").insert(data).execute()
        logger.info(f"Created offer: {name} for product {product_id}")
        return BeliefOffer(**result.data[0])

    def get_offers_for_product(self, product_id: UUID, active_only: bool = True) -> List[BeliefOffer]:
        """
        Fetch offers for a product.

        Args:
            product_id: Product UUID
            active_only: Only return active offers

        Returns:
            List of BeliefOffer
        """
        try:
            query = self.supabase.table("belief_offers").select("*").eq(
                "product_id", str(product_id)
            )
            if active_only:
                query = query.eq("active", True)
            result = query.order("created_at", desc=True).execute()
            return [BeliefOffer(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to fetch offers for product {product_id}: {e}")
            return []

    # ============================================
    # JTBD FRAMED CRUD
    # ============================================

    def create_jtbd_framed(
        self,
        persona_id: UUID,
        product_id: UUID,
        name: str,
        description: Optional[str] = None,
        progress_statement: Optional[str] = None,
        source: str = "manual",
        created_by: Optional[UUID] = None
    ) -> BeliefJTBDFramed:
        """
        Create a persona-framed JTBD.

        Args:
            persona_id: Persona UUID
            product_id: Product UUID
            name: JTBD name
            description: JTBD description
            progress_statement: "When I..., I want to..., so I can..."
            source: How created (manual, extracted_from_persona, ai_generated)
            created_by: User UUID

        Returns:
            Created BeliefJTBDFramed
        """
        data = {
            "persona_id": str(persona_id),
            "product_id": str(product_id),
            "name": name,
            "description": description,
            "progress_statement": progress_statement,
            "source": source,
        }
        if created_by:
            data["created_by"] = str(created_by)

        result = self.supabase.table("belief_jtbd_framed").insert(data).execute()
        logger.info(f"Created JTBD framed: {name}")
        return BeliefJTBDFramed(**result.data[0])

    def get_jtbd_for_persona_product(
        self,
        persona_id: UUID,
        product_id: UUID
    ) -> List[BeliefJTBDFramed]:
        """
        Fetch JTBDs for a persona-product combination.

        Args:
            persona_id: Persona UUID
            product_id: Product UUID

        Returns:
            List of BeliefJTBDFramed
        """
        try:
            result = self.supabase.table("belief_jtbd_framed").select("*").eq(
                "persona_id", str(persona_id)
            ).eq("product_id", str(product_id)).order("created_at", desc=True).execute()
            return [BeliefJTBDFramed(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to fetch JTBDs: {e}")
            return []

    def extract_jtbd_from_persona(self, persona_id: UUID) -> List[str]:
        """
        Extract JTBDs from persona's outcomes_jtbd field.

        The outcomes_jtbd is a DomainSentiment with emotional, social, functional arrays.

        Args:
            persona_id: Persona UUID

        Returns:
            List of JTBD strings from persona data
        """
        try:
            persona = self.get_persona(persona_id)
            if not persona:
                return []

            # outcomes_jtbd is a top-level field, not inside domain_sentiment
            outcomes_jtbd = persona.get("outcomes_jtbd", {})
            if isinstance(outcomes_jtbd, str):
                outcomes_jtbd = json.loads(outcomes_jtbd)

            # Flatten emotional, social, functional into single list
            jtbds = []
            if isinstance(outcomes_jtbd, dict):
                for category in ["emotional", "social", "functional"]:
                    items = outcomes_jtbd.get(category, [])
                    if isinstance(items, list):
                        jtbds.extend(items)
            elif isinstance(outcomes_jtbd, list):
                jtbds = outcomes_jtbd

            return jtbds
        except Exception as e:
            logger.error(f"Failed to extract JTBDs from persona {persona_id}: {e}")
            return []

    # ============================================
    # ANGLE CRUD
    # ============================================

    def create_angle(
        self,
        jtbd_framed_id: UUID,
        name: str,
        belief_statement: str,
        explanation: Optional[str] = None,
        created_by: Optional[UUID] = None
    ) -> BeliefAngle:
        """
        Create an angle for a JTBD.

        Args:
            jtbd_framed_id: JTBD UUID
            name: Angle name
            belief_statement: The core belief/explanation
            explanation: Why this angle works
            created_by: User UUID

        Returns:
            Created BeliefAngle
        """
        data = {
            "jtbd_framed_id": str(jtbd_framed_id),
            "name": name,
            "belief_statement": belief_statement,
            "explanation": explanation,
            "status": "untested",
        }
        if created_by:
            data["created_by"] = str(created_by)

        result = self.supabase.table("belief_angles").insert(data).execute()
        logger.info(f"Created angle: {name}")
        return BeliefAngle(**result.data[0])

    def get_angles_for_jtbd(self, jtbd_framed_id: UUID) -> List[BeliefAngle]:
        """
        Fetch angles for a JTBD.

        Args:
            jtbd_framed_id: JTBD UUID

        Returns:
            List of BeliefAngle
        """
        try:
            result = self.supabase.table("belief_angles").select("*").eq(
                "jtbd_framed_id", str(jtbd_framed_id)
            ).order("created_at", desc=True).execute()
            return [BeliefAngle(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to fetch angles for JTBD {jtbd_framed_id}: {e}")
            return []

    def update_angle_status(self, angle_id: UUID, status: str) -> bool:
        """
        Update angle testing status.

        Args:
            angle_id: Angle UUID
            status: New status (untested, testing, winner, loser)

        Returns:
            True if successful
        """
        try:
            self.supabase.table("belief_angles").update(
                {"status": status}
            ).eq("id", str(angle_id)).execute()
            logger.info(f"Updated angle {angle_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to update angle status: {e}")
            return False

    # ============================================
    # TEMPLATE HELPERS
    # ============================================

    def get_templates_for_brand(self, brand_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """
        Fetch templates for a brand from both sources:
        1. ad_brief_templates - manually created templates
        2. scraped_templates - templates from scraped competitor ads

        Args:
            brand_id: Brand UUID (None for global)

        Returns:
            List of template dicts with 'source' field indicating origin
        """
        try:
            templates = []

            # 1. Get manual templates (ad_brief_templates)
            if brand_id:
                result = self.supabase.table("ad_brief_templates").select("*").eq(
                    "brand_id", str(brand_id)
                ).eq("active", True).execute()
                for t in result.data or []:
                    t["source"] = "manual"
                    templates.append(t)

            # Also get global manual templates
            result = self.supabase.table("ad_brief_templates").select("*").is_(
                "brand_id", "null"
            ).eq("active", True).execute()
            for t in result.data or []:
                t["source"] = "manual"
                templates.append(t)

            # 2. Get scraped templates (scraped_templates) with asset info for images
            result = self.supabase.table("scraped_templates").select(
                "*, scraped_ad_assets(storage_path, original_url, asset_type)"
            ).eq("is_active", True).execute()
            for t in result.data or []:
                t["source"] = "scraped"
                # Map scraped_templates fields to common format
                if not t.get("instructions"):
                    t["instructions"] = t.get("description", "")
                # Extract asset info for display
                asset = t.get("scraped_ad_assets", {})
                if asset:
                    storage_path = asset.get("storage_path")
                    t["asset_storage_path"] = storage_path
                    t["asset_original_url"] = asset.get("original_url")
                    t["asset_type"] = asset.get("asset_type")
                    # Get public URL for the asset
                    if storage_path:
                        t["asset_public_url"] = self._get_storage_public_url(storage_path)
                templates.append(t)

            return templates
        except Exception as e:
            logger.error(f"Failed to fetch templates: {e}")
            return []

    # ============================================
    # PLAN CRUD
    # ============================================

    def create_plan(
        self,
        name: str,
        brand_id: UUID,
        product_id: UUID,
        persona_id: UUID,
        jtbd_framed_id: UUID,
        angle_ids: List[UUID],
        template_ids: List[Dict[str, Any]],  # List of {"id": UUID, "source": "ad_brief_templates"|"scraped_templates"}
        offer_id: Optional[UUID] = None,
        phase_id: int = 1,
        template_strategy: str = "fixed",
        ads_per_angle: int = 3,
        created_by: Optional[UUID] = None
    ) -> BeliefPlan:
        """
        Create a new plan with angles and templates.

        Args:
            name: Plan name
            brand_id: Brand UUID
            product_id: Product UUID
            persona_id: Persona UUID
            jtbd_framed_id: JTBD UUID
            angle_ids: List of angle UUIDs
            template_ids: List of dicts with 'id' and 'source' keys
            offer_id: Optional offer UUID
            phase_id: Phase 1-6
            template_strategy: fixed or random
            ads_per_angle: Ads to generate per angle
            created_by: User UUID

        Returns:
            Created BeliefPlan
        """
        # Create the plan
        plan_data = {
            "name": name,
            "brand_id": str(brand_id),
            "product_id": str(product_id),
            "persona_id": str(persona_id),
            "jtbd_framed_id": str(jtbd_framed_id),
            "phase_id": phase_id,
            "template_strategy": template_strategy,
            "ads_per_angle": ads_per_angle,
            "status": "draft",
        }
        if offer_id:
            plan_data["offer_id"] = str(offer_id)
        if created_by:
            plan_data["created_by"] = str(created_by)

        result = self.supabase.table("belief_plans").insert(plan_data).execute()
        plan = BeliefPlan(**result.data[0])
        plan_id = plan.id

        # Link angles
        for i, angle_id in enumerate(angle_ids):
            self.supabase.table("belief_plan_angles").insert({
                "plan_id": str(plan_id),
                "angle_id": str(angle_id),
                "display_order": i
            }).execute()

        # Link templates (with source tracking)
        for i, template_info in enumerate(template_ids):
            template_id = template_info.get("id") if isinstance(template_info, dict) else template_info
            template_source = template_info.get("source", "ad_brief_templates") if isinstance(template_info, dict) else "ad_brief_templates"
            self.supabase.table("belief_plan_templates").insert({
                "plan_id": str(plan_id),
                "template_id": str(template_id),
                "template_source": template_source,
                "display_order": i
            }).execute()

        logger.info(f"Created plan: {name} with {len(angle_ids)} angles and {len(template_ids)} templates")
        return plan

    def get_plan(self, plan_id: UUID) -> Optional[BeliefPlan]:
        """
        Fetch a plan with its angles and templates.

        Args:
            plan_id: Plan UUID

        Returns:
            BeliefPlan with populated angles and templates
        """
        try:
            # Get plan
            result = self.supabase.table("belief_plans").select("*").eq(
                "id", str(plan_id)
            ).execute()
            if not result.data:
                return None

            plan = BeliefPlan(**result.data[0])

            # Get angles
            angles_result = self.supabase.table("belief_plan_angles").select(
                "angle_id, display_order, belief_angles(*)"
            ).eq("plan_id", str(plan_id)).order("display_order").execute()

            plan.angles = [
                BeliefAngle(**row["belief_angles"])
                for row in angles_result.data or []
                if row.get("belief_angles")
            ]

            # Get templates (handle both sources)
            # Note: belief_plan_templates only has (plan_id, template_id, display_order)
            templates_result = self.supabase.table("belief_plan_templates").select(
                "template_id, display_order"
            ).eq("plan_id", str(plan_id)).order("display_order").execute()

            plan.templates = []
            for row in templates_result.data or []:
                template_id = row.get("template_id")

                # Try scraped_templates first
                t_result = self.supabase.table("scraped_templates").select(
                    "id, name, description"
                ).eq("id", template_id).execute()

                if t_result.data:
                    template = t_result.data[0]
                    template["source"] = "scraped"
                    plan.templates.append(template)
                else:
                    # Try ad_brief_templates
                    t_result = self.supabase.table("ad_brief_templates").select(
                        "id, name, instructions"
                    ).eq("id", template_id).execute()
                    if t_result.data:
                        template = t_result.data[0]
                        template["source"] = "manual"
                        plan.templates.append(template)

            return plan
        except Exception as e:
            logger.error(f"Failed to fetch plan {plan_id}: {e}")
            return None

    def list_plans(
        self,
        brand_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[BeliefPlan]:
        """
        List plans with optional filters.

        Args:
            brand_id: Filter by brand
            status: Filter by status
            limit: Max results

        Returns:
            List of BeliefPlan
        """
        try:
            query = self.supabase.table("belief_plans").select("*")

            if brand_id:
                query = query.eq("brand_id", str(brand_id))
            if status:
                query = query.eq("status", status)

            result = query.order("created_at", desc=True).limit(limit).execute()
            return [BeliefPlan(**row) for row in result.data or []]
        except Exception as e:
            logger.error(f"Failed to list plans: {e}")
            return []

    def update_plan_status(self, plan_id: UUID, status: str) -> bool:
        """
        Update plan status.

        Args:
            plan_id: Plan UUID
            status: New status (draft, ready, running, completed)

        Returns:
            True if successful
        """
        try:
            self.supabase.table("belief_plans").update(
                {"status": status}
            ).eq("id", str(plan_id)).execute()
            logger.info(f"Updated plan {plan_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to update plan status: {e}")
            return False

    # ============================================
    # PLAN COMPILATION
    # ============================================

    def compile_plan(self, plan_id: UUID) -> CompiledPlanPayload:
        """
        Compile a plan into a deterministic payload for ad creator.

        Args:
            plan_id: Plan UUID

        Returns:
            CompiledPlanPayload ready for ad generator

        Raises:
            ValueError: If plan not found or incomplete
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")

        if not plan.angles:
            raise ValueError("Plan has no angles")

        if not plan.templates:
            raise ValueError("Plan has no templates")

        # Build compiled payload
        compiled = CompiledPlanPayload(
            plan_id=plan.id,
            brand_id=plan.brand_id,
            product_id=plan.product_id,
            offer_id=plan.offer_id,
            persona_id=plan.persona_id,
            jtbd_framed_id=plan.jtbd_framed_id,
            phase_id=plan.phase_id,
            angles=[
                {
                    "angle_id": str(a.id),
                    "name": a.name,
                    "belief_statement": a.belief_statement
                }
                for a in plan.angles
            ],
            templates=[
                {
                    "template_id": t.get("id"),
                    "name": t.get("name"),
                    "source": t.get("source", "manual")
                }
                for t in plan.templates
            ],
            template_strategy=plan.template_strategy,
            ads_per_angle=plan.ads_per_angle,
            locked_fields=["brand_id", "product_id", "persona_id", "jtbd_framed_id"],
            allowed_variations=["angle_id", "template_id"],
            compiled_at=datetime.now(),
            status="ready"
        )

        # Store compiled payload in plan
        self.supabase.table("belief_plans").update({
            "compiled_payload": compiled.model_dump(mode="json"),
            "compiled_at": datetime.now().isoformat(),
            "status": "ready"
        }).eq("id", str(plan_id)).execute()

        logger.info(f"Compiled plan {plan_id}")
        return compiled

    def get_compiled_plan(self, plan_id: UUID) -> Optional[CompiledPlanPayload]:
        """
        Get the compiled payload for a plan.

        Args:
            plan_id: Plan UUID

        Returns:
            CompiledPlanPayload or None if not compiled
        """
        try:
            result = self.supabase.table("belief_plans").select(
                "compiled_payload"
            ).eq("id", str(plan_id)).execute()

            if not result.data or not result.data[0].get("compiled_payload"):
                return None

            return CompiledPlanPayload(**result.data[0]["compiled_payload"])
        except Exception as e:
            logger.error(f"Failed to get compiled plan {plan_id}: {e}")
            return None

    # ============================================
    # PHASE VALIDATION
    # ============================================

    def validate_phase(self, plan_id: UUID) -> List[str]:
        """
        Validate phase sequencing and return warnings.

        Args:
            plan_id: Plan UUID

        Returns:
            List of warning messages (empty if valid)
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return ["Plan not found"]

        warnings = []

        # Check if skipping phases
        if plan.phase_id > 1:
            # Check if previous phase was run
            runs = self.supabase.table("belief_plan_runs").select("*").eq(
                "plan_id", str(plan_id)
            ).eq("phase_id", plan.phase_id - 1).eq("status", "completed").execute()

            if not runs.data:
                warnings.append(
                    f"Warning: Phase {plan.phase_id - 1} has not been completed. "
                    f"Results may be unreliable."
                )

        # Check angle count for Phase 1
        if plan.phase_id == 1:
            if len(plan.angles) < 5:
                warnings.append(
                    f"Warning: Phase 1 recommends 5-7 angles. You have {len(plan.angles)}."
                )
            elif len(plan.angles) > 7:
                warnings.append(
                    f"Warning: Phase 1 recommends 5-7 angles. You have {len(plan.angles)}."
                )

        return warnings

    # ============================================
    # AI SUGGESTIONS (Claude Opus 4.5)
    # ============================================

    async def suggest_offers(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        AI-generate offer suggestions for a product.

        Args:
            product_id: Product UUID

        Returns:
            List of suggested offers
        """
        product = self.get_product(product_id)
        if not product:
            return []

        prompt = f"""You are an expert direct response marketer. Generate 3 offer suggestions for this product.

PRODUCT:
- Name: {product.get('name')}
- Benefits: {product.get('benefits', [])}
- Target Audience: {product.get('target_audience', 'Not specified')}
- Current Offer: {product.get('current_offer', 'None')}

Generate 3 different offer types that would create urgency and drive purchases.
Focus on value, not just discounts.

Return JSON array:
[
  {{
    "name": "Offer name",
    "description": "What the offer includes",
    "urgency_drivers": ["Driver 1", "Driver 2"]
  }}
]

Return ONLY the JSON array, no other text."""

        # Pydantic AI Agent (Planning/Complex)
        agent = Agent(
            model=Config.get_model("planning"),
            system_prompt="You are an expert marketer. Return ONLY valid JSON."
        )

        try:
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="planning_service",
                operation="suggest_offers"
            )
            content = result.output.strip()

            # Clean markdown if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to generate offer suggestions: {e}")
            return []

    async def suggest_jtbd(
        self,
        persona_id: UUID,
        product_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        AI-generate JTBD suggestions for a persona-product combination.

        Args:
            persona_id: Persona UUID
            product_id: Product UUID

        Returns:
            List of suggested JTBDs
        """
        persona = self.get_persona(persona_id)
        product = self.get_product(product_id)
        if not persona or not product:
            return []

        prompt = f"""You are an expert at Jobs-to-be-Done theory. Generate 3 persona-framed JTBDs.

PERSONA:
- Name: {persona.get('name')}
- Snapshot: {persona.get('snapshot', 'Not specified')}

PRODUCT:
- Name: {product.get('name')}
- Benefits: {product.get('benefits', [])}
- Target Audience: {product.get('target_audience', 'Not specified')}

Generate 3 JTBDs that this persona would hire this product to do.
Use the format: "When I [situation], I want to [motivation], so I can [outcome]."

Return JSON array:
[
  {{
    "name": "Short JTBD name",
    "description": "Detailed description",
    "progress_statement": "When I..., I want to..., so I can..."
  }}
]

Return ONLY the JSON array, no other text."""

        # Pydantic AI Agent (Planning/Complex)
        agent = Agent(
            model=Config.get_model("planning"),
            system_prompt="You are an expert strategist. Return ONLY valid JSON."
        )

        try:
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="planning_service",
                operation="suggest_jtbd"
            )
            content = result.output.strip()

            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to generate JTBD suggestions: {e}")
            return []

    async def suggest_angles(
        self,
        jtbd_framed_id: UUID,
        count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        AI-generate angle suggestions for a JTBD.

        Args:
            jtbd_framed_id: JTBD UUID
            count: Number of angles to suggest (default 5)

        Returns:
            List of suggested angles
        """
        # Get JTBD with persona and product context
        jtbd_result = self.supabase.table("belief_jtbd_framed").select(
            "*, personas_4d(name, snapshot), products(name, benefits, target_audience)"
        ).eq("id", str(jtbd_framed_id)).execute()

        if not jtbd_result.data:
            return []

        jtbd = jtbd_result.data[0]
        persona = jtbd.get("personas_4d", {})
        product = jtbd.get("products", {})

        prompt = f"""You are an expert direct response copywriter. Generate {count} unique angles for this JTBD.

JTBD:
- Name: {jtbd.get('name')}
- Progress Statement: {jtbd.get('progress_statement', 'Not specified')}
- Description: {jtbd.get('description', 'Not specified')}

PERSONA:
- Name: {persona.get('name', 'Not specified')}
- Snapshot: {persona.get('snapshot', 'Not specified')}

PRODUCT:
- Name: {product.get('name', 'Not specified')}
- Benefits: {product.get('benefits', [])}

An ANGLE is a belief or explanation for:
1. Why the job exists (the problem/situation)
2. Why this solution works (the mechanism)

Each angle should be DIFFERENT - competing explanations that we will test.

Return JSON array:
[
  {{
    "name": "Short angle name",
    "belief_statement": "The core belief this angle represents (1-2 sentences)",
    "explanation": "Why this angle might resonate (1-2 sentences)"
  }}
]

Return ONLY the JSON array, no other text."""

        # Pydantic AI Agent (Planning/Complex)
        agent = Agent(
            model=Config.get_model("planning"),
            system_prompt="You are an expert copywriter. Return ONLY valid JSON."
        )

        try:
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="planning_service",
                operation="suggest_angles"
            )
            content = result.output.strip()

            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to generate angle suggestions: {e}")
            return []

    # ============================================
    # COPY SCAFFOLDS & TEMPLATE EVALUATION
    # ============================================

    def get_phase_eligible_templates(
        self,
        brand_id: Optional[UUID] = None,
        phase_id: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Get templates that are eligible for a specific phase.

        Uses the TemplateEvaluationService to filter templates by eligibility.

        Args:
            brand_id: Optional brand filter
            phase_id: Phase to filter for (default 1)

        Returns:
            List of eligible templates with their evaluation data
        """
        from .template_evaluation_service import TemplateEvaluationService
        eval_service = TemplateEvaluationService()
        return eval_service.get_phase_eligible_templates(brand_id, phase_id)

    def get_all_templates_with_eligibility(
        self,
        brand_id: Optional[UUID] = None,
        phase_id: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Get all templates with their eligibility status.

        Args:
            brand_id: Optional brand filter
            phase_id: Phase to check eligibility for

        Returns:
            List of all templates with eligibility info
        """
        from .template_evaluation_service import TemplateEvaluationService
        eval_service = TemplateEvaluationService()
        return eval_service.get_all_templates_with_eligibility(brand_id, phase_id)

    def generate_copy_sets_for_plan(self, plan_id: UUID) -> List[Dict[str, Any]]:
        """
        Generate copy sets for all angles in a plan.

        Args:
            plan_id: Plan UUID

        Returns:
            List of generated copy sets
        """
        from .copy_scaffold_service import CopyScaffoldService
        copy_service = CopyScaffoldService()

        plan = self.get_plan(plan_id)
        if not plan:
            logger.error(f"Plan not found: {plan_id}")
            return []

        copy_sets = []
        for angle in plan.angles:
            copy_set = copy_service.generate_copy_set(
                angle_id=angle.id,
                phase_id=plan.phase_id,
                product_id=plan.product_id,
                persona_id=plan.persona_id,
                jtbd_id=plan.jtbd_framed_id,
                offer_id=plan.offer_id,
                brand_id=plan.brand_id
            )
            if copy_set:
                copy_sets.append({
                    "angle_id": str(angle.id),
                    "angle_name": angle.name,
                    "headline_variants": copy_set.headline_variants,
                    "primary_text_variants": copy_set.primary_text_variants,
                    "token_context": copy_set.token_context,
                    "guardrails_validated": copy_set.guardrails_validated
                })

        logger.info(f"Generated {len(copy_sets)} copy sets for plan {plan_id}")
        return copy_sets

    def get_copy_sets_for_plan(self, plan_id: UUID) -> List[Dict[str, Any]]:
        """
        Get existing copy sets for all angles in a plan.

        Args:
            plan_id: Plan UUID

        Returns:
            List of copy sets for the plan's angles
        """
        from .copy_scaffold_service import CopyScaffoldService
        copy_service = CopyScaffoldService()
        copy_sets = copy_service.get_copy_sets_for_plan(plan_id)

        return [
            {
                "angle_id": str(cs.angle_id),
                "headline_variants": cs.headline_variants,
                "primary_text_variants": cs.primary_text_variants,
                "token_context": cs.token_context,
                "guardrails_validated": cs.guardrails_validated
            }
            for cs in copy_sets
        ]

    def compile_plan_with_copy(self, plan_id: UUID) -> CompiledPlanPayload:
        """
        Compile a plan with copy sets attached to angles.

        This is an enhanced version of compile_plan that includes copy variants.

        Args:
            plan_id: Plan UUID

        Returns:
            CompiledPlanPayload with copy variants per angle

        Raises:
            ValueError: If plan not found or incomplete
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")

        if not plan.angles:
            raise ValueError("Plan has no angles")

        if not plan.templates:
            raise ValueError("Plan has no templates")

        # Get copy sets for all angles
        from .copy_scaffold_service import CopyScaffoldService
        copy_service = CopyScaffoldService()

        # Build compiled payload with copy
        angles_with_copy = []
        for a in plan.angles:
            angle_data = {
                "angle_id": str(a.id),
                "name": a.name,
                "belief_statement": a.belief_statement
            }

            # Get copy set for this angle
            copy_set = copy_service.get_copy_set_for_angle(a.id, plan.phase_id)
            if copy_set:
                angle_data["headline_variants"] = copy_set.headline_variants
                angle_data["primary_text_variants"] = copy_set.primary_text_variants
                angle_data["token_context"] = copy_set.token_context
                angle_data["guardrails_validated"] = copy_set.guardrails_validated
            else:
                angle_data["headline_variants"] = []
                angle_data["primary_text_variants"] = []
                angle_data["token_context"] = {}
                angle_data["guardrails_validated"] = False

            angles_with_copy.append(angle_data)

        compiled = CompiledPlanPayload(
            plan_id=plan.id,
            brand_id=plan.brand_id,
            product_id=plan.product_id,
            offer_id=plan.offer_id,
            persona_id=plan.persona_id,
            jtbd_framed_id=plan.jtbd_framed_id,
            phase_id=plan.phase_id,
            angles=angles_with_copy,
            templates=[
                {
                    "template_id": t.get("id"),
                    "name": t.get("name"),
                    "source": t.get("source", "manual")
                }
                for t in plan.templates
            ],
            template_strategy=plan.template_strategy,
            ads_per_angle=plan.ads_per_angle,
            locked_fields=["brand_id", "product_id", "persona_id", "jtbd_framed_id"],
            allowed_variations=["angle_id", "template_id"],
            compiled_at=datetime.now(),
            status="ready"
        )

        # Store compiled payload in plan
        self.supabase.table("belief_plans").update({
            "compiled_payload": compiled.model_dump(mode="json"),
            "compiled_at": datetime.now().isoformat(),
            "status": "ready"
        }).eq("id", str(plan_id)).execute()

        logger.info(f"Compiled plan {plan_id} with copy")
        return compiled

    def get_copy_scaffolds(
        self,
        phase_id: int = 1,
        scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get copy scaffolds for a phase.

        Args:
            phase_id: Phase to get scaffolds for
            scope: Filter by 'headline' or 'primary_text' (None = both)

        Returns:
            List of scaffolds
        """
        from .copy_scaffold_service import CopyScaffoldService
        copy_service = CopyScaffoldService()
        scaffolds = copy_service.get_scaffolds_for_phase(phase_id, scope)
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "scope": s.scope,
                "template_text": s.template_text,
                "max_chars": s.max_chars,
                "guardrails": s.guardrails,
                "required_tokens": copy_service.get_required_tokens(s)
            }
            for s in scaffolds
        ]
