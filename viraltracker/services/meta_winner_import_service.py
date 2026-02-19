"""
Meta Winner Import Service — Import winning Meta ads into the generated_ads system.

Imports high-performing ads from Meta (created manually or by agencies) into the
generated_ads system as synthetic records, enabling them for:
- Winner evolution (Thompson Sampling variable selection, anti-fatigue refresh)
- Exemplar marking (few-shot review calibration)
- Creative Genome scoring (weighted Thompson updates)
- Offer variant grouping and best-winner-per-variant auto-suggest

Key design decisions:
- D1: Synthetic ad_runs use status='complete' (valid CHECK constraint value),
  provenance via parameters.source='meta_import'
- D2: element_tags use content_source='recreate_template' (valid pipeline enum),
  provenance via import_source='meta_import'
- D3: URL matching: exact first, canonical fallback, manual pick on ambiguity
- D4: One synthetic ad_run per imported ad, batch_id for grouping
- D5: Imported ads downweighted in Thompson Sampling (0.3 vs 1.0)
- D6: Multi-campaign ads use campaign with highest total spend
"""

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class MetaWinnerImportService:
    """Import winning Meta ads into the generated_ads system."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # Discovery
    # =========================================================================

    async def find_import_candidates(
        self,
        brand_id: UUID,
        min_impressions: int = 1000,
        min_spend: float = 50.0,
        days_back: int = 90,
    ) -> List[Dict[str, Any]]:
        """Find high-performing Meta ads not yet imported.

        Aggregates meta_ads_performance by meta_ad_id, computes reward scores,
        excludes already-imported (generated_ads.meta_ad_id lookup) and
        pipeline-generated (meta_ad_mapping.generated_ad_id exists).
        Auto-matches offer variants via URL matching.

        Args:
            brand_id: Brand UUID.
            min_impressions: Minimum total impressions threshold.
            min_spend: Minimum total spend threshold.
            days_back: How many days back to look.

        Returns:
            List of candidate dicts sorted by reward_score descending.
        """
        from viraltracker.services.creative_genome_service import CreativeGenomeService

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days_back)
        ).strftime("%Y-%m-%d")

        # Get all performance data for this brand
        perf_result = self.supabase.table("meta_ads_performance").select(
            "meta_ad_id, meta_ad_account_id, meta_campaign_id, "
            "impressions, spend, link_ctr, conversion_rate, roas, "
            "campaign_objective, is_video, thumbnail_url, ad_name"
        ).eq(
            "brand_id", str(brand_id)
        ).gte("date", cutoff).execute()

        if not perf_result.data:
            return []

        # Aggregate by meta_ad_id
        ad_agg: Dict[str, Dict] = {}
        for row in perf_result.data:
            mid = row["meta_ad_id"]
            if mid not in ad_agg:
                ad_agg[mid] = {
                    "meta_ad_id": mid,
                    "meta_ad_account_id": row.get("meta_ad_account_id"),
                    "rows": [],
                    "is_video": row.get("is_video", False),
                    "thumbnail_url": row.get("thumbnail_url"),
                    "ad_name": row.get("ad_name"),
                }
            ad_agg[mid]["rows"].append(row)

        # Exclude video ads (image pipeline only)
        ad_agg = {k: v for k, v in ad_agg.items() if not v.get("is_video")}

        # Exclude already-imported ads
        imported = self.supabase.table("generated_ads").select(
            "meta_ad_id"
        ).eq("is_imported", True).not_.is_(
            "meta_ad_id", "null"
        ).execute()
        imported_ids = {r["meta_ad_id"] for r in (imported.data or [])}

        # Exclude pipeline-generated ads (already have meta_ad_mapping)
        mapped = self.supabase.table("meta_ad_mapping").select(
            "meta_ad_id"
        ).execute()
        mapped_ids = {r["meta_ad_id"] for r in (mapped.data or [])}

        # Load baselines for reward computation
        genome = CreativeGenomeService()
        baselines = genome._load_baselines(brand_id)

        candidates = []
        for mid, agg in ad_agg.items():
            if mid in imported_ids or mid in mapped_ids:
                continue

            rows = agg["rows"]
            total_impressions = sum(r.get("impressions") or 0 for r in rows)
            total_spend = sum(r.get("spend") or 0 for r in rows)

            if total_impressions < min_impressions or total_spend < min_spend:
                continue

            # Compute aggregated metrics
            perf_row = self._aggregate_rows(rows)
            objective = perf_row.get("campaign_objective", "DEFAULT")

            # Compute reward score
            reward_score, components = genome._compute_composite_reward(
                perf_row, baselines, objective
            )

            # Auto-match offer variant
            variant_matches = await self.match_offer_variant(brand_id, mid)

            candidates.append({
                "meta_ad_id": mid,
                "meta_ad_account_id": agg["meta_ad_account_id"],
                "ad_name": agg.get("ad_name"),
                "thumbnail_url": agg.get("thumbnail_url"),
                "total_impressions": total_impressions,
                "total_spend": total_spend,
                "avg_ctr": perf_row.get("avg_ctr"),
                "avg_roas": perf_row.get("avg_roas"),
                "avg_conversion_rate": perf_row.get("avg_conversion_rate"),
                "campaign_objective": objective,
                "reward_score": reward_score,
                "reward_components": components,
                "variant_matches": variant_matches,
            })

        # Sort by reward score descending
        candidates.sort(key=lambda x: x.get("reward_score", 0), reverse=True)
        return candidates

    # =========================================================================
    # URL Matching
    # =========================================================================

    async def match_offer_variant(
        self,
        brand_id: UUID,
        meta_ad_id: str,
    ) -> List[Dict[str, Any]]:
        """Match Meta ad -> product_offer_variant(s) via canonical URL.

        1. Look up meta_ad_destinations.canonical_url for this meta_ad_id
        2. Canonicalize all product_offer_variants.landing_page_url for brand's products
        3. Find matches (exact first, then canonical)

        Args:
            brand_id: Brand UUID.
            meta_ad_id: Meta ad ID.

        Returns:
            List of matches, each: {offer_variant_id, product_id, variant_name,
            match_type}. match_type is "exact" or "canonical".
            Empty list = no match. Single-element = auto-select.
            Multi-element = UI shows disambiguation picker.
        """
        from viraltracker.services.url_canonicalizer import canonicalize_url

        # Get destination URLs for this meta ad
        dest_result = self.supabase.table("meta_ad_destinations").select(
            "destination_url, canonical_url"
        ).eq("meta_ad_id", meta_ad_id).execute()

        if not dest_result.data:
            return []

        # Collect all canonical URLs from destinations
        dest_canonical_urls = set()
        dest_original_urls = set()
        for dest in dest_result.data:
            if dest.get("canonical_url"):
                dest_canonical_urls.add(dest["canonical_url"])
            if dest.get("destination_url"):
                dest_original_urls.add(dest["destination_url"])

        if not dest_canonical_urls and not dest_original_urls:
            return []

        # Get all products for this brand
        products = self.supabase.table("products").select(
            "id"
        ).eq("brand_id", str(brand_id)).execute()

        if not products.data:
            return []

        product_ids = [p["id"] for p in products.data]

        # Get all offer variants for these products
        variants = self.supabase.table("product_offer_variants").select(
            "id, product_id, name, landing_page_url"
        ).in_("product_id", product_ids).not_.is_(
            "landing_page_url", "null"
        ).execute()

        if not variants.data:
            return []

        matches = []
        for variant in variants.data:
            variant_url = variant.get("landing_page_url", "")
            if not variant_url:
                continue

            variant_canonical = canonicalize_url(variant_url)

            # Check exact match first (original URL in destinations)
            match_type = None
            if variant_url in dest_original_urls:
                match_type = "exact"
            elif variant_canonical in dest_canonical_urls:
                match_type = "canonical"

            if match_type:
                matches.append({
                    "offer_variant_id": variant["id"],
                    "product_id": variant["product_id"],
                    "variant_name": variant.get("name"),
                    "match_type": match_type,
                })

        # Sort: exact matches first, then canonical
        matches.sort(key=lambda m: 0 if m["match_type"] == "exact" else 1)
        return matches

    # =========================================================================
    # Import (core)
    # =========================================================================

    async def import_meta_winner(
        self,
        brand_id: UUID,
        meta_ad_id: str,
        product_id: UUID,
        meta_ad_account_id: str,
        offer_variant_id: Optional[UUID] = None,
        extract_element_tags: bool = True,
        mark_as_exemplar: bool = False,
        exemplar_category: str = "gold_approve",
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import a single Meta ad as a synthetic generated_ad.

        Idempotent-by-stage: each step checks if already done before executing.

        Steps:
        1. Check idempotency (generated_ads.meta_ad_id unique index)
        2. Ensure image stored (meta_ad_assets or download via MetaAdsService)
        3. Create synthetic ad_run (status='complete', parameters.source='meta_import')
        4. Create generated_ad (is_imported=True, final_status='approved')
        5. Create meta_ad_mapping entry
        6. Compute reward_score from meta_ads_performance -> creative_element_rewards
        7. Extract element_tags via Gemini Flash (if requested)
        8. [best-effort] Generate visual embedding
        9. [best-effort] Mark as exemplar

        Args:
            brand_id: Brand UUID.
            meta_ad_id: Meta ad ID string.
            product_id: Product UUID to associate.
            meta_ad_account_id: Required for meta_ad_mapping.
            offer_variant_id: Optional offer variant UUID.
            extract_element_tags: Whether to extract tags via AI.
            mark_as_exemplar: Whether to mark as exemplar.
            exemplar_category: Exemplar category (gold_approve|gold_reject|edge_case).
            batch_id: Optional batch grouping ID.

        Returns:
            Dict with status, generated_ad_id, warnings list.
        """
        warnings = []

        # 1. Check idempotency
        existing = self.supabase.table("generated_ads").select(
            "id"
        ).eq("meta_ad_id", meta_ad_id).eq("is_imported", True).execute()

        if existing.data:
            return {
                "status": "already_imported",
                "generated_ad_id": existing.data[0]["id"],
            }

        # 2. Ensure image is stored
        image_info = await self._ensure_image_stored(meta_ad_id, brand_id)
        if not image_info or not image_info.get("storage_path"):
            return {"status": "no_image", "meta_ad_id": meta_ad_id}

        storage_path = image_info["storage_path"]

        # Detect canvas size from image dimensions
        canvas_size = await self._detect_canvas_size(storage_path)

        # Get ad copy from meta_ads_performance.ad_copy if available
        ad_copy = await self._get_ad_copy(meta_ad_id)

        # Get destination URL
        dest_url = await self._get_destination_url(meta_ad_id)

        # 3. Create synthetic ad_run
        ad_run_id = self._create_synthetic_ad_run(
            product_id=product_id,
            storage_path=storage_path,
            batch_id=batch_id,
        )

        # 4. Create synthetic generated_ad
        generated_ad_id = self._create_synthetic_generated_ad(
            ad_run_id=ad_run_id,
            meta_ad_id=meta_ad_id,
            storage_path=storage_path,
            canvas_size=canvas_size,
            hook_text=ad_copy,
            offer_variant_id=offer_variant_id,
            destination_url=dest_url,
        )

        # 5. Aggregate performance and create meta_ad_mapping
        perf = await self._aggregate_performance(brand_id, meta_ad_id)
        meta_campaign_id = perf.get("meta_campaign_id", "unknown")

        self._create_meta_ad_mapping(
            generated_ad_id=generated_ad_id,
            meta_ad_id=meta_ad_id,
            meta_ad_account_id=meta_ad_account_id,
            meta_campaign_id=meta_campaign_id,
        )

        # 6. Compute reward score
        reward_info = await self.compute_reward(brand_id, meta_ad_id, generated_ad_id)

        # 7. Extract element tags via Gemini Flash
        element_tags = None
        if extract_element_tags:
            try:
                image_data = await self._download_image_bytes(storage_path)
                if image_data:
                    element_tags = await self.extract_element_tags(
                        image_data, ad_copy
                    )
                    # Add canvas_size from detection
                    if canvas_size:
                        element_tags["canvas_size"] = canvas_size

                    # Update generated_ad with tags
                    self.supabase.table("generated_ads").update({
                        "element_tags": element_tags,
                    }).eq("id", generated_ad_id).execute()
            except Exception as e:
                logger.warning(f"Element tag extraction failed for {meta_ad_id}: {e}")
                warnings.append(f"tag_extraction_failed: {e}")

        # 8. [best-effort] Visual embedding
        try:
            from viraltracker.pipelines.ad_creation_v2.services.visual_descriptor_service import (
                VisualDescriptorService,
            )

            image_data = await self._download_image_bytes(storage_path)
            if image_data:
                vds = VisualDescriptorService()
                await vds.extract_and_store(
                    generated_ad_id=UUID(generated_ad_id),
                    brand_id=brand_id,
                    image_data=image_data,
                )
        except Exception as e:
            logger.warning(f"Visual embedding failed for {meta_ad_id}: {e}")
            warnings.append(f"embedding_failed: {e}")

        # 9. [best-effort] Exemplar marking
        if mark_as_exemplar:
            try:
                from viraltracker.pipelines.ad_creation_v2.services.exemplar_service import (
                    ExemplarService,
                )

                es = ExemplarService()
                await es.mark_as_exemplar(
                    brand_id=brand_id,
                    generated_ad_id=UUID(generated_ad_id),
                    category=exemplar_category,
                )
            except Exception as e:
                logger.warning(f"Exemplar marking failed for {meta_ad_id}: {e}")
                warnings.append(f"exemplar_failed: {e}")

        return {
            "status": "imported",
            "generated_ad_id": generated_ad_id,
            "ad_run_id": ad_run_id,
            "reward_score": reward_info.get("reward_score"),
            "element_tags": element_tags,
            "canvas_size": canvas_size,
            "warnings": warnings,
        }

    # =========================================================================
    # Element Tag Extraction
    # =========================================================================

    async def extract_element_tags(
        self,
        image_data: bytes,
        ad_copy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Use Gemini Flash to extract approximate element_tags from ad image + copy.

        Args:
            image_data: Raw image bytes.
            ad_copy: Optional ad copy text.

        Returns:
            Dict with hook_type, template_category, awareness_stage, visual_style,
            canvas_size, color_mode, content_source, import_source, extraction_method.
        """
        from viraltracker.services.gemini_service import GeminiService

        gemini = GeminiService(model="gemini-2.5-flash")

        copy_context = ""
        if ad_copy:
            copy_context = f"\n\nAd copy text:\n{ad_copy}"

        prompt = f"""Analyze this ad image and classify it into the following creative elements.
Return a JSON object with these fields:

1. "hook_type": The persuasive hook type used. One of: curiosity_gap, social_proof, authority, urgency, scarcity, fear_of_missing_out, transformation, before_after, problem_solution, testimonial, statistic, question, bold_claim, story, direct_benefit
2. "template_category": The visual layout category. One of: Testimonial, Problem-Solution, Before-After, Lifestyle, Product-Focus, Comparison, Educational, Infographic, Minimal-Text, UGC-Style, Professional, Collage
3. "awareness_stage": The target awareness stage from the copy tone. One of: unaware, problem_aware, solution_aware, product_aware, most_aware
4. "visual_style": Brief description of the visual style (2-3 words)
{copy_context}

Return ONLY valid JSON, no markdown formatting."""

        try:
            # Use analyze_image which handles base64 encoding
            response = await gemini.analyze_image(image_data, prompt)

            # Parse JSON from response
            tags = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response text
            import re
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                tags = json.loads(json_match.group())
            else:
                tags = {}
        except Exception as e:
            logger.warning(f"Gemini element tag extraction failed: {e}")
            tags = {}

        # Ensure required keys with defaults
        result = {
            "hook_type": tags.get("hook_type", "direct_benefit"),
            "template_category": tags.get("template_category", "Product-Focus"),
            "awareness_stage": tags.get("awareness_stage", "solution_aware"),
            "visual_style": tags.get("visual_style"),
            "color_mode": "original",
            "content_source": "recreate_template",  # D2: valid pipeline enum
            "import_source": "meta_import",  # D2: provenance key
            "extraction_method": "ai_import",
        }
        return result

    # =========================================================================
    # Reward Computation
    # =========================================================================

    async def compute_reward(
        self,
        brand_id: UUID,
        meta_ad_id: str,
        generated_ad_id: str,
    ) -> Dict[str, Any]:
        """Compute reward_score from meta_ads_performance.

        Aggregates performance -> builds perf_row -> calls
        CreativeGenomeService._compute_composite_reward() with brand baselines.
        Inserts into creative_element_rewards.

        Args:
            brand_id: Brand UUID.
            meta_ad_id: Meta ad ID.
            generated_ad_id: Generated ad UUID string.

        Returns:
            Dict with reward_score and components.
        """
        from viraltracker.services.creative_genome_service import CreativeGenomeService

        genome = CreativeGenomeService()
        baselines = genome._load_baselines(brand_id)

        perf = await self._aggregate_performance(brand_id, meta_ad_id)
        objective = perf.get("campaign_objective", "DEFAULT")

        reward_score, components = genome._compute_composite_reward(
            perf, baselines, objective
        )

        # Insert into creative_element_rewards (idempotent via UNIQUE on generated_ad_id)
        try:
            self.supabase.table("creative_element_rewards").insert({
                "generated_ad_id": generated_ad_id,
                "brand_id": str(brand_id),
                "reward_score": reward_score,
                "reward_components": components,
                "campaign_objective": objective,
                "matured_at": datetime.now(timezone.utc).isoformat(),
                "impressions_at_maturity": perf.get("total_impressions", 0),
            }).execute()
        except Exception as e:
            if "23505" in str(e):
                logger.info(f"Reward already exists for {generated_ad_id}")
            else:
                raise

        return {
            "reward_score": reward_score,
            "reward_components": components,
            "campaign_objective": objective,
        }

    # =========================================================================
    # Grouping Queries
    # =========================================================================

    async def get_winners_by_variant(
        self,
        brand_id: UUID,
        product_id: Optional[UUID] = None,
        min_reward: float = 0.65,
    ) -> Dict[str, List[Dict]]:
        """All winners (imported + native) grouped by offer_variant_id.

        Args:
            brand_id: Brand UUID.
            product_id: Optional product filter.
            min_reward: Minimum reward score.

        Returns:
            Dict mapping offer_variant_id (or "unassigned") -> list of winner dicts.
        """
        # Get rewarded ads for this brand
        rewards = self.supabase.table("creative_element_rewards").select(
            "generated_ad_id, reward_score, reward_components"
        ).eq("brand_id", str(brand_id)).gte(
            "reward_score", min_reward
        ).execute()

        if not rewards.data:
            return {}

        reward_map = {r["generated_ad_id"]: r for r in rewards.data}
        ad_ids = list(reward_map.keys())

        # Fetch generated ads with variant info
        query = self.supabase.table("generated_ads").select(
            "id, storage_path, hook_text, final_status, offer_variant_id, "
            "canvas_size, is_imported, meta_ad_id, element_tags"
        ).in_("id", ad_ids)

        if product_id:
            # Filter by product via ad_runs
            runs = self.supabase.table("ad_runs").select(
                "id"
            ).eq("product_id", str(product_id)).execute()
            run_ids = [r["id"] for r in (runs.data or [])]
            if run_ids:
                query = query.in_("ad_run_id", run_ids)
            else:
                return {}

        ads_result = query.execute()

        # Group by offer_variant_id
        grouped: Dict[str, List[Dict]] = {}
        for ad in (ads_result.data or []):
            variant_key = ad.get("offer_variant_id") or "unassigned"
            reward_data = reward_map.get(ad["id"], {})

            entry = {
                "generated_ad_id": ad["id"],
                "storage_path": ad.get("storage_path"),
                "hook_text": ad.get("hook_text"),
                "final_status": ad.get("final_status"),
                "canvas_size": ad.get("canvas_size"),
                "is_imported": ad.get("is_imported", False),
                "meta_ad_id": ad.get("meta_ad_id"),
                "reward_score": reward_data.get("reward_score", 0),
                "offer_variant_id": ad.get("offer_variant_id"),
            }

            if variant_key not in grouped:
                grouped[variant_key] = []
            grouped[variant_key].append(entry)

        # Sort each group by reward_score descending
        for key in grouped:
            grouped[key].sort(key=lambda x: x["reward_score"], reverse=True)

        return grouped

    async def get_top_winner_per_variant(
        self,
        brand_id: UUID,
        product_id: Optional[UUID] = None,
    ) -> Dict[str, Dict]:
        """Auto-suggest: top winner per offer variant by reward_score.

        Args:
            brand_id: Brand UUID.
            product_id: Optional product filter.

        Returns:
            Dict mapping offer_variant_id -> top winner dict.
        """
        grouped = await self.get_winners_by_variant(brand_id, product_id)
        return {k: v[0] for k, v in grouped.items() if v}

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _ensure_image_stored(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Check meta_ad_assets for stored image; download if missing.

        Returns:
            Dict with storage_path, or None if unavailable.
        """
        # Check existing assets
        asset = self.supabase.table("meta_ad_assets").select(
            "storage_path, status"
        ).eq("meta_ad_id", meta_ad_id).eq(
            "asset_type", "image"
        ).execute()

        if asset.data and asset.data[0].get("storage_path"):
            path = asset.data[0]["storage_path"]
            if asset.data[0].get("status") != "failed" and path:
                return {"storage_path": path}

        # Try to download via MetaAdsService
        try:
            from viraltracker.services.meta_ads_service import MetaAdsService

            # Get thumbnail URL from performance data
            perf = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url"
            ).eq("meta_ad_id", meta_ad_id).not_.is_(
                "thumbnail_url", "null"
            ).limit(1).execute()

            if not perf.data or not perf.data[0].get("thumbnail_url"):
                return None

            image_url = perf.data[0]["thumbnail_url"]
            meta_service = MetaAdsService()
            result = await meta_service.download_and_store_image(
                meta_ad_id=meta_ad_id,
                image_url=image_url,
                brand_id=brand_id,
            )

            if result.status == "downloaded" and result.storage_path:
                return {"storage_path": result.storage_path}
        except Exception as e:
            logger.error(f"Failed to download image for {meta_ad_id}: {e}")

        return None

    def _create_synthetic_ad_run(
        self,
        product_id: UUID,
        storage_path: str,
        batch_id: Optional[str] = None,
    ) -> str:
        """Create a synthetic ad_run with status='complete'.

        D1: Uses status='complete' (valid CHECK constraint value).
        D4: One ad_run per imported ad for reliability.

        Returns:
            ad_run UUID string.
        """
        params = {"source": "meta_import"}
        if batch_id:
            params["batch_id"] = batch_id

        result = self.supabase.table("ad_runs").insert({
            "product_id": str(product_id),
            "reference_ad_storage_path": storage_path,
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "parameters": params,
        }).execute()

        return result.data[0]["id"]

    def _create_synthetic_generated_ad(
        self,
        ad_run_id: str,
        meta_ad_id: str,
        storage_path: str,
        canvas_size: Optional[str] = None,
        hook_text: Optional[str] = None,
        offer_variant_id: Optional[UUID] = None,
        destination_url: Optional[str] = None,
    ) -> str:
        """Create a synthetic generated_ad with is_imported=True.

        Sets top-level fields (canvas_size, color_mode, offer_variant_id) that
        ExemplarService reads at exemplar_service.py:173.

        Returns:
            generated_ad UUID string.
        """
        row = {
            "ad_run_id": ad_run_id,
            "prompt_index": 1,
            "prompt_text": "[imported from Meta]",
            "prompt_spec": {"source": "meta_import"},
            "storage_path": storage_path,
            "final_status": "approved",
            "is_imported": True,
            "meta_ad_id": meta_ad_id,
            "canvas_size": canvas_size,
            "color_mode": "original",
        }

        if hook_text:
            row["hook_text"] = hook_text[:500]  # Truncate to reasonable length

        if offer_variant_id:
            row["offer_variant_id"] = str(offer_variant_id)

        if destination_url:
            row["destination_url"] = destination_url

        result = self.supabase.table("generated_ads").insert(row).execute()
        return result.data[0]["id"]

    def _create_meta_ad_mapping(
        self,
        generated_ad_id: str,
        meta_ad_id: str,
        meta_ad_account_id: str,
        meta_campaign_id: str,
    ) -> None:
        """Create meta_ad_mapping entry for the imported ad."""
        try:
            self.supabase.table("meta_ad_mapping").insert({
                "generated_ad_id": generated_ad_id,
                "meta_ad_id": meta_ad_id,
                "meta_ad_account_id": meta_ad_account_id,
                "meta_campaign_id": meta_campaign_id,
                "linked_by": "import",
            }).execute()
        except Exception as e:
            if "23505" in str(e):
                logger.info(f"Mapping already exists for {meta_ad_id} -> {generated_ad_id}")
            else:
                raise

    async def _aggregate_performance(
        self,
        brand_id: UUID,
        meta_ad_id: str,
    ) -> Dict[str, Any]:
        """Aggregate meta_ads_performance rows for a single meta_ad_id.

        D6: When multiple campaigns exist, selects by highest total spend.

        Returns:
            Dict with avg_ctr, avg_roas, avg_conversion_rate, total_impressions,
            total_spend, campaign_objective, meta_campaign_id.
        """
        perf = self.supabase.table("meta_ads_performance").select(
            "impressions, spend, link_ctr, conversion_rate, roas, "
            "campaign_objective, meta_campaign_id"
        ).eq("meta_ad_id", meta_ad_id).execute()

        if not perf.data:
            return {
                "avg_ctr": None,
                "avg_roas": None,
                "avg_conversion_rate": None,
                "total_impressions": 0,
                "total_spend": 0,
                "campaign_objective": "DEFAULT",
                "meta_campaign_id": "unknown",
            }

        rows = perf.data

        # D6: Select campaign with highest total spend
        campaign_spend: Dict[str, float] = {}
        for row in rows:
            cid = row.get("meta_campaign_id", "unknown")
            campaign_spend[cid] = campaign_spend.get(cid, 0) + (row.get("spend") or 0)

        best_campaign = max(campaign_spend, key=campaign_spend.get)

        # Get objective from best campaign's rows
        best_rows = [r for r in rows if r.get("meta_campaign_id") == best_campaign]
        objective = best_rows[-1].get("campaign_objective") or "DEFAULT" if best_rows else "DEFAULT"

        return self._aggregate_rows(rows, objective, best_campaign)

    def _aggregate_rows(
        self,
        rows: List[Dict],
        objective: Optional[str] = None,
        meta_campaign_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate performance rows into summary metrics."""
        total_impressions = sum(r.get("impressions") or 0 for r in rows)
        total_spend = sum(r.get("spend") or 0 for r in rows)

        # Weighted average by impressions
        avg_ctr = self._weighted_avg(rows, "link_ctr", "impressions")
        avg_roas = self._weighted_avg(rows, "roas", "impressions")
        avg_conv = self._weighted_avg(rows, "conversion_rate", "impressions")

        if not objective:
            objective = rows[-1].get("campaign_objective") or "DEFAULT" if rows else "DEFAULT"

        return {
            "avg_ctr": avg_ctr,
            "avg_roas": avg_roas,
            "avg_conversion_rate": avg_conv,
            "total_impressions": total_impressions,
            "total_spend": total_spend,
            "campaign_objective": objective,
            "meta_campaign_id": meta_campaign_id or "unknown",
        }

    def _weighted_avg(
        self,
        rows: List[Dict],
        metric_key: str,
        weight_key: str,
    ) -> Optional[float]:
        """Compute weighted average of a metric across rows."""
        total_weight = 0
        weighted_sum = 0.0
        for row in rows:
            val = row.get(metric_key)
            weight = row.get(weight_key) or 0
            if val is not None and weight > 0:
                weighted_sum += val * weight
                total_weight += weight
        if total_weight == 0:
            return None
        return weighted_sum / total_weight

    async def _detect_canvas_size(self, storage_path: str) -> Optional[str]:
        """Infer canvas size from image dimensions.

        Returns:
            Canvas size string (e.g., "1080x1080px") or None.
        """
        try:
            image_data = await self._download_image_bytes(storage_path)
            if not image_data:
                return None

            from PIL import Image
            from io import BytesIO

            img = Image.open(BytesIO(image_data))
            width, height = img.size

            # Map common dimensions to canvas sizes
            size_map = {
                (1080, 1080): "1080x1080px",
                (1080, 1350): "1080x1350px",
                (1080, 1920): "1080x1920px",
                (1200, 628): "1200x628px",
            }

            # Check exact match first
            exact = size_map.get((width, height))
            if exact:
                return exact

            # Check aspect ratio (within 5% tolerance)
            ratio = width / height if height > 0 else 0
            if 0.95 <= ratio <= 1.05:
                return "1080x1080px"
            elif 0.76 <= ratio <= 0.84:
                return "1080x1350px"
            elif 0.53 <= ratio <= 0.59:
                return "1080x1920px"
            elif 1.85 <= ratio <= 1.95:
                return "1200x628px"

            return f"{width}x{height}px"
        except Exception as e:
            logger.warning(f"Failed to detect canvas size for {storage_path}: {e}")
            return None

    async def _download_image_bytes(self, storage_path: str) -> Optional[bytes]:
        """Download image bytes from Supabase storage.

        Parses bucket/path from storage_path (e.g., "meta-ad-assets/brand/file.png").

        Returns:
            Image bytes, or None on failure.
        """
        try:
            KNOWN_BUCKETS = {"generated-ads", "meta-ad-assets", "reference-ads"}
            parts = storage_path.split("/", 1)
            if len(parts) == 2 and parts[0] in KNOWN_BUCKETS:
                bucket, path = parts
            else:
                bucket = "generated-ads"
                path = storage_path

            response = self.supabase.storage.from_(bucket).download(path)
            return response
        except Exception as e:
            logger.error(f"Failed to download image from {storage_path}: {e}")
            return None

    async def _get_ad_copy(self, meta_ad_id: str) -> Optional[str]:
        """Get ad copy text for a Meta ad from meta_ads_performance.ad_copy."""
        try:
            result = self.supabase.table("meta_ads_performance").select(
                "ad_copy"
            ).eq("meta_ad_id", meta_ad_id).not_.is_(
                "ad_copy", "null"
            ).limit(1).execute()

            if not result.data:
                return None

            return result.data[0].get("ad_copy")
        except Exception as e:
            logger.debug(f"No ad copy found for {meta_ad_id}: {e}")
            return None

    async def _get_destination_url(self, meta_ad_id: str) -> Optional[str]:
        """Get destination URL for a Meta ad."""
        try:
            result = self.supabase.table("meta_ad_destinations").select(
                "destination_url"
            ).eq("meta_ad_id", meta_ad_id).limit(1).execute()

            if result.data:
                return result.data[0].get("destination_url")
        except Exception as e:
            logger.debug(f"No destination URL for {meta_ad_id}: {e}")
        return None
