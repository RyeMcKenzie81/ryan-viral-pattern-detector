"""
Ad Creator V2 Readiness Service.

Pre-flight checklist for the (brand, product, offer_variant) selection in
Ad Creator V2. Surfaces silent configuration gaps that quietly degrade ad
quality — most importantly the missing-asset-tags case that collapses the
effective template pool from 3,134 to ~432.

See `docs/plans/ad-creator-readiness/PLAN.md` for context and check rationale.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Set
from uuid import UUID

from viraltracker.core.database import get_supabase_client
from viraltracker.services.models import (
    AdCreatorReadinessCheck,
    AdCreatorReadinessReport,
    ReadinessStatus,
)

logger = logging.getLogger(__name__)


# Status precedence for rollup. BLOCKED > PARTIAL > READY > NOT_APPLICABLE.
_STATUS_RANK = {
    ReadinessStatus.BLOCKED: 3,
    ReadinessStatus.PARTIAL: 2,
    ReadinessStatus.READY: 1,
    ReadinessStatus.NOT_APPLICABLE: 0,
}


class AdCreatorReadinessService:
    """Compute readiness checks for an Ad Creator V2 selection."""

    def __init__(self):
        self._db = get_supabase_client()

    def check(
        self,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> AdCreatorReadinessReport:
        """Run all readiness checks and roll up to an overall status.

        Each check returns a single AdCreatorReadinessCheck. Checks are
        independent — a failure in one does not skip others.
        """
        checks: List[AdCreatorReadinessCheck] = [
            self._check_product_images(product_id),
            self._check_asset_tags(product_id),
            self._check_persona(product_id),
            self._check_offer_variant_mechanism(offer_variant_id),
            self._check_brand_voice(brand_id),
            self._check_recent_template_diversity(product_id),
        ]

        # Roll up: worst-case status across checks, ignoring NOT_APPLICABLE.
        considered = [c for c in checks if c.status != ReadinessStatus.NOT_APPLICABLE]
        if not considered:
            overall = ReadinessStatus.NOT_APPLICABLE
        else:
            overall = max(considered, key=lambda c: _STATUS_RANK[c.status]).status

        return AdCreatorReadinessReport(
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            overall=overall,
            checks=checks,
            generated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_product_images(self, product_id: str) -> AdCreatorReadinessCheck:
        count = self._db.table("product_images").select(
            "id", count="exact", head=True
        ).eq("product_id", product_id).execute().count or 0

        if count == 0:
            return AdCreatorReadinessCheck(
                key="product_images",
                label="Product images",
                status=ReadinessStatus.BLOCKED,
                summary="0 images uploaded",
                fix_hint="Upload at least one product image (5+ recommended).",
                fix_page="pages/02_🏢_Brand_Manager.py",
            )
        if count < 5:
            return AdCreatorReadinessCheck(
                key="product_images",
                label="Product images",
                status=ReadinessStatus.PARTIAL,
                summary=f"{count} image(s) — fewer than 5 limits visual variety",
                fix_hint="Upload more product images for richer reference selection.",
                fix_page="pages/02_🏢_Brand_Manager.py",
            )
        return AdCreatorReadinessCheck(
            key="product_images",
            label="Product images",
            status=ReadinessStatus.READY,
            summary=f"{count} images uploaded",
        )

    def _check_asset_tags(self, product_id: str) -> AdCreatorReadinessCheck:
        product_tags = asyncio.run(_prefetch_product_asset_tags(product_id))

        # Compute effective pool — how many active templates does this product
        # fully match on required_assets?
        total_active, fully_matched, no_req = _compute_asset_pool(self._db, product_tags)

        if total_active == 0:
            # Highly unlikely in practice; treat as not applicable.
            return AdCreatorReadinessCheck(
                key="asset_tags",
                label="Asset tag coverage",
                status=ReadinessStatus.NOT_APPLICABLE,
                summary="No active templates in pool",
            )

        # Without product asset_tags, only the no-req pool is reachable on
        # asset_match=1.0. With tags, the matched pool grows.
        pct = 100 * fully_matched / total_active

        if not product_tags:
            return AdCreatorReadinessCheck(
                key="asset_tags",
                label="Asset tag coverage",
                status=ReadinessStatus.PARTIAL,
                summary=(
                    f"No asset tags — effective pool {no_req}/{total_active} "
                    f"templates ({100 * no_req / total_active:.0f}%)"
                ),
                fix_hint=(
                    "Tag product images with the right asset tags "
                    "(e.g., product:bottle, product:capsules) to unlock more templates."
                ),
                fix_page="pages/02_🏢_Brand_Manager.py",
            )

        if pct < 25:
            return AdCreatorReadinessCheck(
                key="asset_tags",
                label="Asset tag coverage",
                status=ReadinessStatus.PARTIAL,
                summary=(
                    f"{fully_matched}/{total_active} templates fully match assets "
                    f"({pct:.0f}%) — tag set may be too narrow"
                ),
                fix_hint=(
                    "Add more asset tag variants matching the product's actual form factor "
                    "(jar, pouch, gummies, etc.)."
                ),
                fix_page="pages/02_🏢_Brand_Manager.py",
            )

        return AdCreatorReadinessCheck(
            key="asset_tags",
            label="Asset tag coverage",
            status=ReadinessStatus.READY,
            summary=f"{fully_matched}/{total_active} templates fully match assets ({pct:.0f}%)",
        )

    def _check_persona(self, product_id: str) -> AdCreatorReadinessCheck:
        # Walk product_personas → personas_4d.demographics
        links = self._db.table("product_personas").select(
            "persona_id, is_primary"
        ).eq("product_id", product_id).execute().data or []

        if not links:
            return AdCreatorReadinessCheck(
                key="persona",
                label="Persona attached",
                status=ReadinessStatus.PARTIAL,
                summary="No persona linked to this product",
                fix_hint=(
                    "Attach a 4D persona so audience and awareness scorers "
                    "produce real signal instead of neutral 0.5."
                ),
                fix_page="pages/03_👥_Product_Personas.py",
            )

        # Prefer the primary persona, else first one
        primary = next((l for l in links if l.get("is_primary")), links[0])
        persona_id = primary.get("persona_id")
        if not persona_id:
            return AdCreatorReadinessCheck(
                key="persona",
                label="Persona attached",
                status=ReadinessStatus.PARTIAL,
                summary="Persona link present but missing persona_id",
                fix_hint="Re-attach the persona in Product Personas.",
                fix_page="pages/03_👥_Product_Personas.py",
            )

        p = self._db.table("personas_4d").select(
            "id, name, demographics"
        ).eq("id", persona_id).limit(1).execute().data or []
        if not p:
            return AdCreatorReadinessCheck(
                key="persona",
                label="Persona attached",
                status=ReadinessStatus.PARTIAL,
                summary="Linked persona row not found",
                fix_hint="The linked persona was deleted. Attach a current one.",
                fix_page="pages/03_👥_Product_Personas.py",
            )

        demographics = p[0].get("demographics") or {}
        if not isinstance(demographics, dict) or not demographics:
            return AdCreatorReadinessCheck(
                key="persona",
                label="Persona attached",
                status=ReadinessStatus.PARTIAL,
                summary=f"Persona '{p[0].get('name','?')}' has no demographics filled in",
                fix_hint="Fill in demographics (gender, age, etc.) on the persona.",
                fix_page="pages/03_👥_Product_Personas.py",
            )

        return AdCreatorReadinessCheck(
            key="persona",
            label="Persona attached",
            status=ReadinessStatus.READY,
            summary=f"Persona '{p[0].get('name','?')}' with demographics",
        )

    def _check_offer_variant_mechanism(
        self, offer_variant_id: Optional[str]
    ) -> AdCreatorReadinessCheck:
        if not offer_variant_id:
            return AdCreatorReadinessCheck(
                key="offer_variant_mechanism",
                label="Offer variant — mechanism & hooks",
                status=ReadinessStatus.NOT_APPLICABLE,
                summary="No offer variant selected",
            )

        rows = self._db.table("product_offer_variants").select(
            "name, mechanism_name, mechanism_problem, mechanism_solution, sample_hooks"
        ).eq("id", offer_variant_id).limit(1).execute().data or []
        if not rows:
            return AdCreatorReadinessCheck(
                key="offer_variant_mechanism",
                label="Offer variant — mechanism & hooks",
                status=ReadinessStatus.PARTIAL,
                summary="Selected variant row not found",
                fix_hint="Re-select a current offer variant.",
                fix_page="pages/02_🏢_Brand_Manager.py",
            )

        row = rows[0]
        hooks = row.get("sample_hooks") or []
        if not isinstance(hooks, list):
            hooks = []
        filled = sum(
            1 for v in (row.get("mechanism_name"), row.get("mechanism_problem"), row.get("mechanism_solution"))
            if v and str(v).strip()
        )
        if filled >= 3 and len(hooks) >= 2:
            return AdCreatorReadinessCheck(
                key="offer_variant_mechanism",
                label="Offer variant — mechanism & hooks",
                status=ReadinessStatus.READY,
                summary=(
                    f"Variant '{row.get('name','?')}': UMP/UMS + {len(hooks)} sample hook(s)"
                ),
            )

        missing = []
        if filled < 3:
            missing.append(f"{3 - filled} of mechanism_name/UMP/UMS empty")
        if len(hooks) < 2:
            missing.append(f"only {len(hooks)} sample hook(s)")
        return AdCreatorReadinessCheck(
            key="offer_variant_mechanism",
            label="Offer variant — mechanism & hooks",
            status=ReadinessStatus.PARTIAL,
            summary=f"Variant '{row.get('name','?')}': " + ", ".join(missing),
            fix_hint=(
                "Open the offer variant editor and re-run 'Analyze Landing Page', "
                "or fill the mechanism fields manually."
            ),
            fix_page="pages/02_🏢_Brand_Manager.py",
        )

    def _check_brand_voice(self, brand_id: str) -> AdCreatorReadinessCheck:
        rows = self._db.table("brands").select(
            "brand_voice_tone"
        ).eq("id", brand_id).limit(1).execute().data or []
        voice = (rows[0].get("brand_voice_tone") if rows else "") or ""
        if voice.strip():
            return AdCreatorReadinessCheck(
                key="brand_voice",
                label="Brand voice",
                status=ReadinessStatus.READY,
                summary=f"Brand voice tone set ({len(voice)} chars)",
            )
        return AdCreatorReadinessCheck(
            key="brand_voice",
            label="Brand voice",
            status=ReadinessStatus.PARTIAL,
            summary="brand_voice_tone is empty",
            fix_hint="Set a brand voice/tone description to keep generated copy on-brand.",
            fix_page="pages/02_🏢_Brand_Manager.py",
        )

    def _check_recent_template_diversity(self, product_id: str) -> AdCreatorReadinessCheck:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        runs = self._db.table("ad_runs").select(
            "source_scraped_template_id"
        ).eq("product_id", product_id).gte("created_at", cutoff).execute().data or []
        total = len(runs)
        if total == 0:
            return AdCreatorReadinessCheck(
                key="recent_template_diversity",
                label="Recent template diversity (14d)",
                status=ReadinessStatus.NOT_APPLICABLE,
                summary="No runs in the last 14 days",
            )
        unique = len({r["source_scraped_template_id"] for r in runs if r.get("source_scraped_template_id")})
        ratio = unique / total if total else 0.0
        if ratio < 0.5:
            return AdCreatorReadinessCheck(
                key="recent_template_diversity",
                label="Recent template diversity (14d)",
                status=ReadinessStatus.PARTIAL,
                summary=f"{unique} unique / {total} runs ({ratio:.0%}) — high repetition",
                fix_hint=(
                    "Often caused by missing asset tags. Check the 'Asset tag coverage' "
                    "row above and tag product images to widen the effective pool."
                ),
                fix_page="pages/02_🏢_Brand_Manager.py",
            )
        return AdCreatorReadinessCheck(
            key="recent_template_diversity",
            label="Recent template diversity (14d)",
            status=ReadinessStatus.READY,
            summary=f"{unique} unique / {total} runs ({ratio:.0%}) — good rotation",
        )


# ----------------------------------------------------------------------
# Helpers (sync wrappers / pure functions for testability)
# ----------------------------------------------------------------------

async def _prefetch_product_asset_tags(product_id: str) -> Set[str]:
    # Thin wrapper over the existing async function so test patches stay local.
    from viraltracker.services.template_scoring_service import prefetch_product_asset_tags
    return await prefetch_product_asset_tags(product_id)


def _compute_asset_pool(db, product_tags: Set[str]) -> tuple[int, int, int]:
    """Return (total_active, fully_matched, no_requirement).

    Iterates all active scraped_templates once and applies the same set
    intersection AssetMatchScorer uses. Pagination matches the supabase-py
    1000-row default cap.
    """
    total = 0
    fully = 0
    no_req = 0
    offset = 0
    while True:
        batch = db.table("scraped_templates").select(
            "template_elements"
        ).eq("is_active", True).range(offset, offset + 999).execute().data or []
        if not batch:
            break
        for t in batch:
            total += 1
            el = t.get("template_elements") or {}
            if not isinstance(el, dict):
                no_req += 1
                fully += 1
                continue
            req = el.get("required_assets") or []
            if not isinstance(req, list) or not req:
                no_req += 1
                fully += 1
                continue
            req_set = set(str(r) for r in req)
            if req_set.issubset(product_tags):
                fully += 1
        if len(batch) < 1000:
            break
        offset += 1000
    return total, fully, no_req
