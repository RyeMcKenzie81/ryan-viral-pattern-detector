"""
Exemplar Service — Few-shot exemplar library for review calibration.

Phase 8A: Curates 20-30 calibration ads per brand (gold_approve, gold_reject, edge_case).
Auto-seeds from ad_review_overrides history, supports manual curation, and provides
embedding-based similarity search for injecting exemplars into review prompts.
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Per-brand caps by category
EXEMPLAR_CAPS = {
    "gold_approve": 10,
    "gold_reject": 10,
    "edge_case": 10,
}
TOTAL_CAP = 30


class ExemplarService:
    """Few-shot exemplar library for review calibration."""

    # ========================================================================
    # Auto-seeding
    # ========================================================================

    async def auto_seed_exemplars(self, brand_id: UUID) -> Dict[str, Any]:
        """Auto-seed exemplars from override history.

        Target: ~10 gold_approve, ~10 gold_reject, ~5-10 edge_case.
        Enforces diversity (template_category, canvas_size, color_mode, persona).

        IMPORTANT: Filters to latest override per ad only (superseded_by IS NULL)
        to avoid seeding from stale/outdated override labels.

        Classification rules:
        - override_approve + superseded_by IS NULL -> gold_approve candidate
        - override_reject + superseded_by IS NULL -> gold_reject candidate
        - confirm + borderline weighted_score (5.0-7.0) + superseded_by IS NULL -> edge_case candidate

        Args:
            brand_id: Brand UUID.

        Returns:
            {seeded: int, gold_approve: int, gold_reject: int, edge_case: int}
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()

        # Get existing exemplar count
        existing = await self.get_exemplar_stats(brand_id)
        existing_ad_ids = set()
        existing_exemplars = await self.get_exemplars(brand_id)
        for ex in existing_exemplars:
            existing_ad_ids.add(ex.get("generated_ad_id"))

        counts = {"gold_approve": 0, "gold_reject": 0, "edge_case": 0}

        # Fetch latest overrides for this brand's ads (superseded_by IS NULL)
        result = db.table("ad_review_overrides").select(
            "id, generated_ad_id, override_action, check_overrides, reason, "
            "generated_ads!inner(id, brand_id, final_status, review_check_scores, "
            "element_tags, canvas_size, color_mode, storage_path, hook_text)"
        ).is_(
            "superseded_by", "null"
        ).eq(
            "generated_ads.brand_id", str(brand_id)
        ).order("created_at", desc=True).limit(200).execute()

        overrides = result.data or []
        if not overrides:
            logger.info(f"No overrides found for brand {brand_id}, skipping auto-seed")
            return {"seeded": 0, **counts}

        # Classify overrides into exemplar candidates
        candidates = {"gold_approve": [], "gold_reject": [], "edge_case": []}

        for override in overrides:
            ad_id = override.get("generated_ad_id")
            if ad_id in existing_ad_ids:
                continue

            action = override.get("override_action")
            ad_data = override.get("generated_ads", {})

            if action == "override_approve":
                candidates["gold_approve"].append((ad_id, ad_data, override))
            elif action == "override_reject":
                candidates["gold_reject"].append((ad_id, ad_data, override))
            elif action == "confirm":
                # Edge case: confirmed borderline ads (compute weighted from check scores)
                check_scores = ad_data.get("review_check_scores") or {}
                vals = [v for v in check_scores.values() if isinstance(v, (int, float))]
                weighted = sum(vals) / len(vals) if vals else None
                if weighted is not None and 5.0 <= float(weighted) <= 7.0:
                    candidates["edge_case"].append((ad_id, ad_data, override))

        # Seed with diversity constraints
        for category, cap in EXEMPLAR_CAPS.items():
            remaining = cap - existing.get(category, 0)
            if remaining <= 0:
                continue

            selected = self._select_diverse(candidates[category], remaining)
            for ad_id, ad_data, override in selected:
                try:
                    await self._insert_exemplar(
                        db, brand_id, UUID(ad_id), category,
                        source="auto",
                        source_reason=override.get("override_action"),
                        ad_data=ad_data,
                    )
                    counts[category] += 1
                    existing_ad_ids.add(ad_id)
                except Exception as e:
                    logger.warning(f"Failed to seed exemplar {ad_id}: {e}")

        total = sum(counts.values())
        logger.info(f"Auto-seeded {total} exemplars for brand {brand_id}: {counts}")
        return {"seeded": total, **counts}

    # ========================================================================
    # CRUD
    # ========================================================================

    async def mark_as_exemplar(
        self,
        brand_id: UUID,
        generated_ad_id: UUID,
        category: str,
        created_by: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Mark a generated ad as an exemplar. Enforces per-brand cap (30).

        Args:
            brand_id: Brand UUID.
            generated_ad_id: Generated ad UUID.
            category: gold_approve, gold_reject, or edge_case.
            created_by: User UUID who marked it.

        Returns:
            Exemplar row dict.
        """
        from viraltracker.core.database import get_supabase_client

        if category not in EXEMPLAR_CAPS:
            raise ValueError(f"Invalid category: {category}")

        db = get_supabase_client()

        # Check cap
        stats = await self.get_exemplar_stats(brand_id)
        total_active = sum(stats.get(c, 0) for c in EXEMPLAR_CAPS)
        if total_active >= TOTAL_CAP:
            raise ValueError(
                f"Brand {brand_id} has reached the exemplar cap ({TOTAL_CAP}). "
                f"Remove some exemplars before adding more."
            )

        category_count = stats.get(category, 0)
        if category_count >= EXEMPLAR_CAPS[category]:
            raise ValueError(
                f"Category '{category}' cap reached ({EXEMPLAR_CAPS[category]}). "
                f"Remove some before adding more."
            )

        # Get ad data for diversity attributes
        ad_result = db.table("generated_ads").select(
            "element_tags, canvas_size, color_mode"
        ).eq("id", str(generated_ad_id)).limit(1).execute()

        ad_data = ad_result.data[0] if ad_result.data else {}

        # Check for existing visual embedding
        ve_result = db.table("visual_embeddings").select(
            "id"
        ).eq("generated_ad_id", str(generated_ad_id)).limit(1).execute()

        ve_id = ve_result.data[0]["id"] if ve_result.data else None

        element_tags = ad_data.get("element_tags") or {}
        row = {
            "brand_id": str(brand_id),
            "generated_ad_id": str(generated_ad_id),
            "category": category,
            "source": "manual",
            "created_by": str(created_by) if created_by else None,
            "template_category": element_tags.get("template_category"),
            "canvas_size": ad_data.get("canvas_size"),
            "color_mode": ad_data.get("color_mode"),
            "persona_id": element_tags.get("persona_id"),
            "visual_embedding_id": ve_id,
        }

        result = db.table("exemplar_library").upsert(
            row, on_conflict="brand_id,generated_ad_id"
        ).execute()

        return result.data[0] if result.data else row

    async def remove_exemplar(self, exemplar_id: UUID, reason: str) -> None:
        """Deactivate an exemplar (soft delete).

        Args:
            exemplar_id: Exemplar UUID.
            reason: Deactivation reason.
        """
        from viraltracker.core.database import get_supabase_client
        from datetime import datetime, timezone

        db = get_supabase_client()
        db.table("exemplar_library").update({
            "is_active": False,
            "deactivated_at": datetime.now(timezone.utc).isoformat(),
            "deactivated_reason": reason,
        }).eq("id", str(exemplar_id)).execute()

        logger.info(f"Deactivated exemplar {exemplar_id}: {reason}")

    async def get_exemplars(
        self, brand_id: UUID, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List active exemplars for a brand.

        Args:
            brand_id: Brand UUID.
            category: Optional category filter.

        Returns:
            List of exemplar row dicts.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        query = db.table("exemplar_library").select(
            "*, generated_ads(id, hook_text, storage_path, final_status, "
            "review_check_scores, canvas_size, color_mode, element_tags)"
        ).eq(
            "brand_id", str(brand_id)
        ).eq("is_active", True).order("created_at", desc=True)

        if category:
            query = query.eq("category", category)

        result = query.execute()
        return result.data or []

    async def get_exemplar_stats(self, brand_id: UUID) -> Dict[str, int]:
        """Get counts by category for active exemplars.

        Args:
            brand_id: Brand UUID.

        Returns:
            Dict with category counts and total.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        result = db.table("exemplar_library").select(
            "category"
        ).eq("brand_id", str(brand_id)).eq("is_active", True).execute()

        counts = {"gold_approve": 0, "gold_reject": 0, "edge_case": 0}
        for row in (result.data or []):
            cat = row.get("category")
            if cat in counts:
                counts[cat] += 1

        counts["total"] = sum(counts.values())
        return counts

    # ========================================================================
    # Similarity Search
    # ========================================================================

    async def find_similar_exemplars(
        self,
        brand_id: UUID,
        ad_embedding: List[float],
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find most similar exemplars via pgvector cosine similarity.

        Args:
            brand_id: Brand UUID.
            ad_embedding: 1536-dim embedding of the ad being reviewed.
            category: Optional category filter.
            limit: Max results.

        Returns:
            List of exemplar dicts with similarity score.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        embedding_str = "[" + ",".join(str(v) for v in ad_embedding) + "]"

        category_clause = ""
        if category:
            category_clause = f"AND el.category = '{category}'"

        query = f"""
            SELECT
                el.id AS exemplar_id,
                el.generated_ad_id,
                el.category,
                el.source,
                el.template_category,
                el.canvas_size,
                el.color_mode,
                ga.hook_text,
                ga.final_status,
                ga.review_check_scores,
                ga.storage_path,
                1 - (ve.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM exemplar_library el
            JOIN visual_embeddings ve ON ve.id = el.visual_embedding_id
            JOIN generated_ads ga ON ga.id = el.generated_ad_id
            WHERE el.brand_id = '{brand_id}'
              AND el.is_active = TRUE
              AND ve.embedding IS NOT NULL
              {category_clause}
            ORDER BY ve.embedding <=> '{embedding_str}'::vector
            LIMIT {limit}
        """

        result = db.rpc("exec_sql", {"query": query}).execute()
        return result.data or []

    # ========================================================================
    # Review Prompt Injection
    # ========================================================================

    async def build_exemplar_context(
        self, brand_id: UUID, ad_embedding: List[float]
    ) -> Optional[str]:
        """Build few-shot exemplar context for review prompts.

        Returns formatted text with 3-5 exemplars (balanced: approve + reject + edge).
        Returns None if no exemplars with embeddings exist.

        Args:
            brand_id: Brand UUID.
            ad_embedding: 1536-dim embedding of the ad being reviewed.

        Returns:
            Formatted exemplar context string, or None.
        """
        # Get 2 gold_approve, 2 gold_reject, 1 edge_case (balanced)
        approves = await self.find_similar_exemplars(
            brand_id, ad_embedding, category="gold_approve", limit=2
        )
        rejects = await self.find_similar_exemplars(
            brand_id, ad_embedding, category="gold_reject", limit=2
        )
        edges = await self.find_similar_exemplars(
            brand_id, ad_embedding, category="edge_case", limit=1
        )

        all_exemplars = approves + rejects + edges
        if not all_exemplars:
            return None

        parts = [
            "\n## Calibration Examples (from this brand's exemplar library)\n"
            "Use these real examples to calibrate your scoring. "
            "They represent the brand's quality standards.\n"
        ]

        for i, ex in enumerate(all_exemplars, 1):
            category = ex.get("category", "unknown")
            hook = ex.get("hook_text", "N/A")
            scores = ex.get("review_check_scores") or {}
            # Compute weighted avg from check scores (weighted_score not stored on generated_ads)
            weighted = None
            if scores:
                vals = [v for v in scores.values() if isinstance(v, (int, float))]
                weighted = sum(vals) / len(vals) if vals else None

            if category == "gold_approve":
                label = "APPROVED — Gold Standard"
            elif category == "gold_reject":
                label = "REJECTED — Known Bad"
            else:
                label = "EDGE CASE — Borderline"

            # Format key scores
            score_items = []
            for check in ["V1", "V2", "V7", "V9", "C1", "G1"]:
                val = scores.get(check)
                if val is not None:
                    score_items.append(f"{check}={val}")

            score_str = ", ".join(score_items) if score_items else "N/A"
            weighted_str = f"{weighted:.1f}" if weighted is not None else "N/A"

            parts.append(f"### Example {i} [{label}]")
            parts.append(f"- Hook: \"{hook[:80]}\"")
            parts.append(f"- Key scores: {score_str} (weighted avg: {weighted_str})")
            parts.append(f"- Similarity to current ad: {ex.get('similarity', 0):.2f}")
            parts.append("")

        return "\n".join(parts)

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _select_diverse(
        self,
        candidates: List[tuple],
        max_count: int,
    ) -> List[tuple]:
        """Select diverse candidates ensuring variety in template/canvas/color.

        Greedy selection: pick candidates that maximize diversity of
        (template_category, canvas_size, color_mode) already selected.
        """
        if len(candidates) <= max_count:
            return candidates

        selected = []
        seen_combos = set()

        for ad_id, ad_data, override in candidates:
            if len(selected) >= max_count:
                break

            element_tags = ad_data.get("element_tags") or {}
            combo = (
                element_tags.get("template_category", ""),
                ad_data.get("canvas_size", ""),
                ad_data.get("color_mode", ""),
            )

            if combo not in seen_combos:
                selected.append((ad_id, ad_data, override))
                seen_combos.add(combo)

        # Fill remaining slots with any remaining candidates
        for ad_id, ad_data, override in candidates:
            if len(selected) >= max_count:
                break
            if (ad_id, ad_data, override) not in selected:
                selected.append((ad_id, ad_data, override))

        return selected

    async def _insert_exemplar(
        self,
        db,
        brand_id: UUID,
        generated_ad_id: UUID,
        category: str,
        source: str,
        source_reason: Optional[str],
        ad_data: Dict[str, Any],
    ) -> None:
        """Insert a single exemplar row."""
        element_tags = ad_data.get("element_tags") or {}

        # Check for existing visual embedding
        ve_result = db.table("visual_embeddings").select(
            "id"
        ).eq("generated_ad_id", str(generated_ad_id)).limit(1).execute()

        ve_id = ve_result.data[0]["id"] if ve_result.data else None

        db.table("exemplar_library").upsert(
            {
                "brand_id": str(brand_id),
                "generated_ad_id": str(generated_ad_id),
                "category": category,
                "source": source,
                "source_reason": source_reason,
                "template_category": element_tags.get("template_category"),
                "canvas_size": ad_data.get("canvas_size"),
                "color_mode": ad_data.get("color_mode"),
                "persona_id": element_tags.get("persona_id"),
                "visual_embedding_id": ve_id,
            },
            on_conflict="brand_id,generated_ad_id",
        ).execute()
