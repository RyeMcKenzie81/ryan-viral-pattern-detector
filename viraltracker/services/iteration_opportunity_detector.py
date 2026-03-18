"""
Iteration Opportunity Detector — Finds ads with exploitable mixed signals.

Detects ads that are strong in one performance dimension but weak in another,
indicating a specific iteration strategy (visual, messaging, pacing, etc.)
could unlock significant improvement.

Usage:
    from viraltracker.services.iteration_opportunity_detector import IterationOpportunityDetector

    detector = IterationOpportunityDetector(supabase_client)
    opps = await detector.detect_opportunities(brand_id, org_id)
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

PATTERNS = {
    "high_converter_low_stopper": {
        "label": "Strong ROAS, Weak CTR",
        "strong": {"metric": "roas", "threshold": "p50", "direction": "above"},
        "weak": {"metric": "ctr", "threshold": "p25", "direction": "below"},
        "strategy_category": "visual",
        "strategy": "Strengthen visual impact \u2014 higher contrast, bolder text, face close-ups",
        "evolution_mode": "winner_iteration",
        "min_impressions": 1000,
        "min_spend": 50,
        "min_days": 7,
    },
    "good_hook_bad_close": {
        "label": "Strong CTR, Weak ROAS",
        "strong": {"metric": "ctr", "threshold": "p50", "direction": "above"},
        "weak": {"metric": "roas", "threshold": "p25", "direction": "below"},
        "strategy_category": "messaging",
        "strategy": "Improve conversion path \u2014 CTA clarity, offer alignment, LP congruence",
        "evolution_mode": "winner_iteration",
        "min_impressions": 1000,
        "min_spend": 50,
        "min_days": 7,
    },
    "thumb_stopper_quick_dropper": {
        "label": "Strong Hook Rate, Weak Hold Rate",
        "strong": {"metric": "hook_rate", "threshold": "p50", "direction": "above"},
        "weak": {"metric": "hold_rate", "threshold": "p50_below", "direction": "below"},
        "strategy_category": "pacing",
        "strategy": "Improve mid-video retention \u2014 storytelling, value reveal timing",
        "evolution_mode": "winner_iteration",
        "min_impressions": 1000,
        "min_spend": 50,
        "min_days": 7,
    },
    "high_cvr_low_ctr": {
        "label": "High Conversion Rate, Weak CTR",
        "strong": {"metric": "conversion_rate", "threshold": "p50", "direction": "above"},
        "weak": {"metric": "ctr", "threshold": "p25", "direction": "below"},
        "strategy_category": "visual",
        "strategy": "Right message, wrong wrapper — boost visual stopping power with higher contrast, bolder imagery, face close-ups",
        "evolution_mode": "winner_iteration",
        "min_impressions": 1000,
        "min_spend": 50,
        "min_days": 7,
    },
    "efficient_but_starved": {
        "label": "Profitable but Under-Scaled",
        "strong": {"metric": "roas", "threshold": "p50", "direction": "above"},
        "weak": {"metric": "impressions", "threshold": 5000, "direction": "below_absolute"},
        "strategy_category": "budget",
        "strategy": "Budget/audience expansion \u2014 increase daily budget, broaden targeting",
        "evolution_mode": None,
        "min_impressions": 500,
        "min_spend": 20,
        "min_days": 5,
    },
}

# Size-limited and fatiguing patterns handled by specialized detectors


@dataclass
class IterationOpportunity:
    """A detected iteration opportunity for an ad."""

    id: str
    meta_ad_id: str
    brand_id: str
    pattern_type: str
    pattern_label: str
    confidence: float

    strong_metric: str
    strong_value: float
    strong_percentile: str

    weak_metric: str
    weak_value: float
    weak_percentile: str

    strategy_category: str
    strategy_description: str
    strategy_actions: list

    evolution_mode: Optional[str]
    status: str = "detected"

    # Populated from ad data
    ad_name: str = ""
    creative_format: str = ""
    thumbnail_url: str = ""
    spend: float = 0.0
    impressions: int = 0

    # Data-driven explanations (added by _build_explanation)
    explanation_headline: str = ""
    explanation_projection: str = ""
    projected_roas: float = 0.0


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _get_baseline_value(baseline, metric: str, percentile: str) -> Optional[float]:
    """Get a baseline value by metric name and percentile level.

    Args:
        baseline: BaselineSnapshot object.
        metric: Performance metric name (ctr, roas, cpc, etc.).
        percentile: One of 'p25', 'p50', 'p75'.
    """
    # Map metric names to baseline field names
    metric_map = {
        "ctr": "ctr",
        "roas": "roas",
        "cpc": "cpc",
        "cpm": "cpm",
        "conversion_rate": "conversion_rate",
        "hook_rate": "hook_rate",
        "hold_rate": "hold_rate",
    }
    base = metric_map.get(metric, metric)

    if percentile == "p50":
        return getattr(baseline, f"median_{base}", None)
    elif percentile == "p25":
        return getattr(baseline, f"p25_{base}", None)
    elif percentile == "p75":
        return getattr(baseline, f"p75_{base}", None)
    # For video metrics with only median, p50_below = below median
    elif percentile == "p50_below":
        return getattr(baseline, f"median_{base}", None)
    return None


def _compute_percentile_label(value: float, baseline, metric: str) -> str:
    """Compute approximate percentile label for display."""
    p25 = _get_baseline_value(baseline, metric, "p25")
    p50 = _get_baseline_value(baseline, metric, "p50")
    p75 = _get_baseline_value(baseline, metric, "p75")

    if p25 is None or p50 is None:
        return "n/a"

    if value <= p25:
        # Roughly estimate within 0-25 range
        return f"p{int(25 * (value / p25)) if p25 > 0 else 0}"
    elif value <= p50:
        pct = 25 + int(25 * ((value - p25) / (p50 - p25))) if (p50 - p25) > 0 else 25
        return f"p{pct}"
    elif p75 and value <= p75:
        pct = 50 + int(25 * ((value - p50) / (p75 - p50))) if (p75 - p50) > 0 else 50
        return f"p{pct}"
    else:
        return "p75+"


def _compute_confidence(
    strong_val: float,
    strong_threshold: float,
    weak_val: float,
    weak_threshold: float,
    impressions: int,
    days_active: int,
) -> float:
    """Compute opportunity confidence based on signal strength and data volume.

    Higher confidence when:
    - Strong metric is well above threshold (excess strength)
    - Weak metric is well below threshold (clear gap)
    - More impressions (statistical reliability)
    - More days (not a one-day fluke)
    """
    # Signal strength: how far above/below thresholds
    if strong_threshold > 0:
        strong_excess = (strong_val / strong_threshold) - 1.0
    else:
        strong_excess = 0.5
    strong_excess = min(strong_excess, 2.0)  # Cap at 3x threshold

    if weak_threshold > 0:
        weak_gap = 1.0 - (weak_val / weak_threshold)
    else:
        weak_gap = 0.5
    weak_gap = max(weak_gap, 0.0)
    weak_gap = min(weak_gap, 1.0)

    signal_score = (strong_excess + weak_gap) / 2.0  # 0-1.5 range

    # Data volume score
    impression_score = min(impressions / 5000, 1.0)
    day_score = min(days_active / 14, 1.0)
    volume_score = (impression_score * 0.7 + day_score * 0.3)

    # Combined: 60% signal, 40% volume
    confidence = (signal_score * 0.6 + volume_score * 0.4)
    return round(max(0.1, min(1.0, confidence)), 2)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class IterationOpportunityDetector:
    """Detects iteration opportunities from mixed-signal ad performance."""

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def detect_opportunities(
        self,
        brand_id: str,
        org_id: str,
        days_back: int = 30,
        min_confidence: float = 0.3,
        product_id: Optional[str] = None,
    ) -> List[IterationOpportunity]:
        """Find all iteration opportunities for a brand.

        Args:
            brand_id: Brand UUID string.
            org_id: Organization UUID (or "all").
            days_back: Days of performance data to consider.
            min_confidence: Minimum confidence threshold.
            product_id: Optional product UUID to filter ads by.

        Returns:
            List of IterationOpportunity sorted by confidence desc.
        """
        # 1. Load active ads with aggregated performance
        ads = self._load_ads_with_performance(brand_id, days_back, product_id=product_id)
        if not ads:
            logger.info(f"No ads with performance data for brand {brand_id}")
            return []

        # 2. Load classifications for cohort matching
        classifications = self._load_classifications(brand_id)

        # 3. Load baselines
        from viraltracker.services.ad_intelligence.baseline_service import BaselineService
        baseline_service = BaselineService(self.supabase)

        opportunities = []

        for ad in ads:
            meta_ad_id = ad["meta_ad_id"]

            # Get baseline for this ad
            try:
                baseline = await baseline_service.get_baseline_for_ad(
                    meta_ad_id=meta_ad_id,
                    brand_id=UUID(brand_id),
                )
            except Exception as e:
                logger.warning(f"Failed to get baseline for {meta_ad_id}: {e}")
                baseline = None

            if not baseline:
                continue

            # Get classification for format detection
            classification = classifications.get(meta_ad_id, {})

            # 4. Evaluate each standard pattern
            for pattern_type, pattern_def in PATTERNS.items():
                opp = self._evaluate_pattern(
                    ad, baseline, pattern_type, pattern_def, classification
                )
                if opp and opp.confidence >= min_confidence:
                    opportunities.append(opp)

            # 5. Specialized detectors
            size_opp = self._detect_size_limited(ad, brand_id, classification)
            if size_opp and size_opp.confidence >= min_confidence:
                opportunities.append(size_opp)

            fatigue_opp = self._detect_fatiguing(ad, brand_id, baseline)
            if fatigue_opp and fatigue_opp.confidence >= min_confidence:
                opportunities.append(fatigue_opp)

            proven_opp = self._detect_proven_winner(ad, brand_id, baseline)
            if proven_opp and proven_opp.confidence >= min_confidence:
                opportunities.append(proven_opp)

        # 6. Sort by confidence desc
        opportunities.sort(key=lambda o: o.confidence, reverse=True)

        # 7. Store in DB
        real_org_id = self._resolve_org_id(org_id, brand_id)
        self._store_opportunities(opportunities, real_org_id)

        logger.info(f"Detected {len(opportunities)} opportunities for brand {brand_id}")
        return opportunities

    def get_opportunities(
        self,
        brand_id: str,
        org_id: str,
        status: str = "detected",
        pattern_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load stored opportunities from DB.

        Args:
            brand_id: Brand UUID string.
            org_id: Organization UUID.
            status: Filter by status.
            pattern_filter: Optional pattern_type filter.

        Returns:
            List of opportunity dicts.
        """
        try:
            query = (
                self.supabase.table("iteration_opportunities")
                .select("*")
                .eq("brand_id", str(brand_id))
                .eq("status", status)
                .order("confidence", desc=True)
            )
            if org_id != "all":
                query = query.eq("organization_id", org_id)
            if pattern_filter:
                query = query.eq("pattern_type", pattern_filter)

            result = query.execute()
            opps = result.data or []

            # Enrich with ad_name, thumbnail_url, creative_format from source tables
            if opps:
                ad_ids = list({o["meta_ad_id"] for o in opps if o.get("meta_ad_id")})
                self._enrich_opportunities(opps, ad_ids, brand_id)

            return opps
        except Exception as e:
            logger.error(f"Failed to load opportunities: {e}")
            return []

    def _enrich_opportunities(
        self, opps: List[Dict], ad_ids: List[str], brand_id: str
    ) -> None:
        """Enrich stored opportunities with display fields from source tables."""
        # Fetch ad_name, thumbnail_url, and aggregate spend from meta_ads_performance
        perf_map: Dict[str, Dict] = {}
        try:
            for i in range(0, len(ad_ids), 50):
                batch = ad_ids[i:i + 50]
                res = (
                    self.supabase.table("meta_ads_performance")
                    .select("meta_ad_id, ad_name, thumbnail_url, spend")
                    .in_("meta_ad_id", batch)
                    .eq("brand_id", brand_id)
                    .order("date", desc=True)
                    .execute()
                )
                for r in (res.data or []):
                    aid = r["meta_ad_id"]
                    if aid not in perf_map:
                        perf_map[aid] = {
                            "ad_name": r.get("ad_name", ""),
                            "thumbnail_url": r.get("thumbnail_url", ""),
                            "spend": 0,
                        }
                    perf_map[aid]["spend"] += float(r.get("spend") or 0)
        except Exception as e:
            logger.debug(f"Failed to fetch perf data for enrichment: {e}")

        # Fetch creative_format and awareness_level from classifications
        cls_map: Dict[str, Dict] = {}
        try:
            res = (
                self.supabase.table("ad_creative_classifications")
                .select("meta_ad_id, creative_format, creative_awareness_level")
                .eq("brand_id", brand_id)
                .in_("meta_ad_id", ad_ids)
                .order("classified_at", desc=True)
                .execute()
            )
            for c in (res.data or []):
                aid = c.get("meta_ad_id")
                if aid and aid not in cls_map:
                    cls_map[aid] = {
                        "creative_format": c.get("creative_format", ""),
                        "awareness_level": c.get("creative_awareness_level", ""),
                    }
        except Exception as e:
            logger.debug(f"Failed to fetch classifications for enrichment: {e}")

        # Merge into opportunities
        for o in opps:
            aid = o.get("meta_ad_id")
            perf = perf_map.get(aid, {})
            cls = cls_map.get(aid, {})
            o.setdefault("ad_name", perf.get("ad_name", ""))
            o.setdefault("thumbnail_url", perf.get("thumbnail_url", ""))
            o.setdefault("spend", float(perf.get("spend") or 0))
            o.setdefault("creative_format", cls.get("creative_format", ""))
            o.setdefault("awareness_level", cls.get("awareness_level", ""))

    def dismiss_opportunity(self, opportunity_id: str) -> bool:
        """Mark an opportunity as dismissed."""
        try:
            self.supabase.table("iteration_opportunities").update(
                {"status": "dismissed"}
            ).eq("id", opportunity_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to dismiss opportunity {opportunity_id}: {e}")
            return False

    def restore_opportunity(self, opportunity_id: str) -> bool:
        """Restore a dismissed opportunity."""
        try:
            self.supabase.table("iteration_opportunities").update(
                {"status": "detected"}
            ).eq("id", opportunity_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to restore opportunity {opportunity_id}: {e}")
            return False

    async def action_opportunity(
        self,
        opportunity_id: str,
        brand_id: str,
        product_id: str,
        org_id: str,
    ) -> Dict[str, Any]:
        """Execute an iteration on an opportunity.

        Handles both generated and non-generated ads via auto-import.

        Args:
            opportunity_id: Opportunity UUID.
            brand_id: Brand UUID string.
            product_id: Product UUID string.
            org_id: Organization UUID.

        Returns:
            Dict with evolution result or error.
        """
        # Load opportunity
        opp = self._get_opportunity(opportunity_id)
        if not opp:
            return {"success": False, "error": "Opportunity not found"}

        meta_ad_id = opp["meta_ad_id"]
        evolution_mode = opp.get("evolution_mode")

        if not evolution_mode:
            return {"success": False, "error": "This opportunity type has no automated action (budget recommendation)"}

        # Step 1: Find or import generated_ad
        generated_ad_id = self._find_generated_ad(meta_ad_id, brand_id)

        if not generated_ad_id:
            # Auto-import via MetaWinnerImportService
            try:
                from viraltracker.services.meta_winner_import_service import MetaWinnerImportService
                import_service = MetaWinnerImportService()

                meta_ad_account_id = self._get_account_id(meta_ad_id)
                if not meta_ad_account_id:
                    return {"success": False, "error": "Could not determine Meta ad account ID"}

                import_result = await import_service.import_meta_winner(
                    brand_id=UUID(brand_id),
                    meta_ad_id=meta_ad_id,
                    product_id=UUID(product_id),
                    meta_ad_account_id=meta_ad_account_id,
                    extract_element_tags=True,
                )
                generated_ad_id = import_result.get("generated_ad_id")
                if not generated_ad_id:
                    return {"success": False, "error": f"Import failed: {import_result.get('status')}"}
            except Exception as e:
                logger.error(f"Auto-import failed for {meta_ad_id}: {e}")
                return {"success": False, "error": f"Auto-import failed: {e}"}

        # Step 2: Build additional_instructions from opportunity analysis
        instructions = self._build_iteration_instructions(opp)

        # Step 3: Evolve via WinnerEvolutionService
        try:
            from viraltracker.services.winner_evolution_service import WinnerEvolutionService
            evolution_service = WinnerEvolutionService()

            result = await evolution_service.evolve_winner(
                parent_ad_id=UUID(generated_ad_id),
                mode=evolution_mode,
                variable_override=None,
                skip_winner_check=True,
            )
        except Exception as e:
            logger.error(f"Evolution failed for {meta_ad_id}: {e}")
            return {"success": False, "error": f"Evolution failed: {e}"}

        # Step 4: Update opportunity status
        child_ad_id = None
        if result.get("child_ad_ids"):
            child_ad_id = result["child_ad_ids"][0]

        self._mark_actioned(opportunity_id, child_ad_id)

        return {
            "success": True,
            "meta_ad_id": meta_ad_id,
            "generated_ad_id": generated_ad_id,
            "evolution_result": result,
            "child_ad_id": child_ad_id,
        }

    async def batch_queue_iterations(
        self,
        opportunity_ids: List[str],
        brand_id: str,
        product_id: str,
        org_id: str,
        strategy_overrides: Optional[Dict[str, Dict]] = None,
        num_variations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue multiple iteration jobs via scheduled_jobs (non-blocking).

        For each opportunity: imports ad if needed, creates a winner_evolution
        scheduled_job. Jobs are picked up by the worker within ~1 minute.

        Args:
            opportunity_ids: List of opportunity UUIDs.
            brand_id: Brand UUID string.
            product_id: Product UUID string.
            org_id: Organization UUID.
            strategy_overrides: Optional per-opportunity overrides.
                Format: {opp_id: {"evolution_mode": "...", "variable_override": "..."}}

        Returns:
            Dict with queued, imported, skipped counts and errors list.
        """
        from viraltracker.services.meta_winner_import_service import MetaWinnerImportService

        MAX_BATCH = 20
        if len(opportunity_ids) > MAX_BATCH:
            opportunity_ids = opportunity_ids[:MAX_BATCH]

        strategy_overrides = strategy_overrides or {}
        import_service = MetaWinnerImportService()

        queued = 0
        imported = 0
        skipped = 0
        errors = []

        for opp_id in opportunity_ids:
            try:
                opp = self._get_opportunity(opp_id)
                if not opp:
                    errors.append(f"Opportunity {opp_id[:8]} not found")
                    continue

                # Only queue opportunities with status "detected"
                if opp.get("status") != "detected":
                    skipped += 1
                    continue

                meta_ad_id = opp["meta_ad_id"]
                evolution_mode = opp.get("evolution_mode")
                if not evolution_mode:
                    skipped += 1
                    continue

                # Find or import generated_ad
                generated_ad_id = self._find_generated_ad(meta_ad_id, brand_id)
                if not generated_ad_id:
                    meta_ad_account_id = self._get_account_id(meta_ad_id)
                    if not meta_ad_account_id:
                        errors.append(f"No account ID for {meta_ad_id}")
                        continue

                    import_result = await import_service.import_meta_winner(
                        brand_id=UUID(brand_id),
                        meta_ad_id=meta_ad_id,
                        product_id=UUID(product_id),
                        meta_ad_account_id=meta_ad_account_id,
                        extract_element_tags=True,
                    )
                    generated_ad_id = import_result.get("generated_ad_id")
                    if not generated_ad_id:
                        errors.append(f"Import failed for {meta_ad_id}: {import_result.get('status')}")
                        continue
                    imported += 1

                # Resolve strategy
                override = strategy_overrides.get(opp_id, {})
                mode = override.get("evolution_mode", evolution_mode)
                variable_override = override.get("variable_override")

                # Only pass num_variations for strategies that support it
                # Auto-Improve (no variable_override) and cross_size always use 1
                job_variations = None
                if num_variations and num_variations > 1:
                    if mode == "anti_fatigue_refresh" or variable_override:
                        job_variations = num_variations

                # Create scheduled_job
                now = datetime.utcnow()
                ad_name = opp.get("ad_name") or opp.get("meta_ad_id", "")
                job_row = {
                    "job_type": "winner_evolution",
                    "brand_id": str(brand_id),
                    "product_id": str(product_id),
                    "name": f"Batch iterate: {ad_name[:40]}",
                    "status": "active",
                    "schedule_type": "one_time",
                    "next_run_at": (now + timedelta(minutes=1)).isoformat(),
                    "trigger_source": "manual",
                    "parameters": {
                        "parent_ad_id": str(generated_ad_id),
                        "evolution_mode": mode,
                        "variable_override": variable_override,
                        "skip_winner_check": True,
                        **({"num_variations": job_variations} if job_variations else {}),
                    },
                }
                self.supabase.table("scheduled_jobs").insert(job_row).execute()

                # Mark opportunity as queued (not actioned — evolved_ad_id unknown)
                self.supabase.table("iteration_opportunities").update({
                    "status": "queued",
                    "actioned_at": now.isoformat(),
                }).eq("id", opp_id).execute()

                queued += 1

            except Exception as e:
                logger.error(f"Batch queue error for {opp_id}: {e}")
                errors.append(f"Error for {opp_id[:8]}: {str(e)[:80]}")

        return {
            "queued": queued,
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }

    # ---------------------------------------------------------------------------
    # Pattern evaluation
    # ---------------------------------------------------------------------------

    def _evaluate_pattern(
        self,
        ad: dict,
        baseline,
        pattern_type: str,
        pattern_def: dict,
        classification: dict,
    ) -> Optional[IterationOpportunity]:
        """Evaluate a single pattern against an ad's performance."""
        # Check minimum data requirements
        if ad.get("impressions", 0) < pattern_def.get("min_impressions", 1000):
            return None
        if ad.get("spend", 0) < pattern_def.get("min_spend", 50):
            return None
        if ad.get("days_active", 0) < pattern_def.get("min_days", 7):
            return None

        strong_cfg = pattern_def["strong"]
        weak_cfg = pattern_def["weak"]

        strong_metric = strong_cfg["metric"]
        weak_metric = weak_cfg["metric"]

        # Get ad metric values
        strong_value = ad.get(strong_metric)
        weak_value = ad.get(weak_metric)

        if strong_value is None or weak_value is None:
            return None

        # Get baseline thresholds
        strong_threshold = _get_baseline_value(baseline, strong_metric, strong_cfg["threshold"])
        if strong_threshold is None:
            return None

        # Check strong condition: must be ABOVE threshold
        if strong_cfg["direction"] == "above" and strong_value <= strong_threshold:
            return None

        # Get weak threshold
        if weak_cfg["direction"] == "below_absolute":
            # Absolute threshold (e.g., impressions < 5000)
            weak_threshold = weak_cfg["threshold"]
            if weak_value >= weak_threshold:
                return None
        else:
            weak_threshold_key = weak_cfg["threshold"]
            weak_threshold = _get_baseline_value(baseline, weak_metric, weak_threshold_key)
            if weak_threshold is None:
                return None
            if weak_cfg["direction"] == "below" and weak_value >= weak_threshold:
                return None

        # Build strategy actions
        strategy_actions = self._build_strategy_actions(
            pattern_type, ad, baseline, classification
        )

        # Compute confidence
        confidence = _compute_confidence(
            strong_value, strong_threshold,
            weak_value, weak_threshold if isinstance(weak_threshold, (int, float)) else 0,
            ad.get("impressions", 0),
            ad.get("days_active", 0),
        )

        strong_pct = _compute_percentile_label(strong_value, baseline, strong_metric)
        weak_pct = _compute_percentile_label(weak_value, baseline, weak_metric)

        # Build data-driven explanation
        headline, projection, projected_roas = self._build_explanation(
            pattern_type, ad, baseline
        )

        return IterationOpportunity(
            id=str(uuid4()),
            meta_ad_id=ad["meta_ad_id"],
            brand_id=ad.get("brand_id", ""),
            pattern_type=pattern_type,
            pattern_label=pattern_def["label"],
            confidence=confidence,
            strong_metric=strong_metric,
            strong_value=round(strong_value, 4),
            strong_percentile=strong_pct,
            weak_metric=weak_metric,
            weak_value=round(weak_value, 4),
            weak_percentile=weak_pct,
            strategy_category=pattern_def["strategy_category"],
            strategy_description=pattern_def["strategy"],
            strategy_actions=strategy_actions,
            evolution_mode=pattern_def.get("evolution_mode"),
            ad_name=ad.get("ad_name", ""),
            creative_format=classification.get("creative_format", ""),
            thumbnail_url=ad.get("thumbnail_url", ""),
            spend=ad.get("spend", 0),
            impressions=ad.get("impressions", 0),
            explanation_headline=headline,
            explanation_projection=projection,
            projected_roas=projected_roas,
        )

    def _detect_size_limited(
        self, ad: dict, brand_id: str, classification: dict
    ) -> Optional[IterationOpportunity]:
        """Check if a winning ad has only been tested in one canvas size."""
        if ad.get("impressions", 0) < 1000 or ad.get("spend", 0) < 50 or ad.get("days_active", 0) < 7:
            return None

        # Need a good reward to qualify as "winner"
        meta_ad_id = ad["meta_ad_id"]
        generated_ad_id = self._find_generated_ad(meta_ad_id, brand_id)
        if not generated_ad_id:
            return None

        # Check how many canvas sizes this ad has been tested in
        try:
            result = (
                self.supabase.table("generated_ads")
                .select("element_tags")
                .eq("id", generated_ad_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None

            element_tags = result.data[0].get("element_tags") or {}
            canvas_size = element_tags.get("canvas_size", "")

            # Check if other sizes exist for same ancestor
            lineage = (
                self.supabase.table("ad_lineage")
                .select("child_ad_id, variable_changed")
                .eq("ancestor_ad_id", generated_ad_id)
                .eq("evolution_mode", "cross_size_expansion")
                .execute()
            )
            if lineage.data:
                return None  # Already has cross-size variants

            # Check reward score
            reward_result = (
                self.supabase.table("creative_element_rewards")
                .select("reward_score")
                .eq("generated_ad_id", generated_ad_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            reward = 0
            if reward_result.data:
                reward = reward_result.data[0].get("reward_score", 0)

            if reward < 0.5:
                return None

        except Exception as e:
            logger.warning(f"Size-limited check failed for {meta_ad_id}: {e}")
            return None

        confidence = min(0.3 + reward * 0.5, 0.9)

        return IterationOpportunity(
            id=str(uuid4()),
            meta_ad_id=meta_ad_id,
            brand_id=brand_id,
            pattern_type="size_limited_winner",
            pattern_label="Winner in Only One Format",
            confidence=round(confidence, 2),
            strong_metric="reward_score",
            strong_value=round(reward, 3),
            strong_percentile="n/a",
            weak_metric="canvas_sizes_tested",
            weak_value=1,
            weak_percentile="n/a",
            strategy_category="cross_size",
            strategy_description="Cross-size expansion \u2014 generate in untested canvas sizes",
            strategy_actions=[
                f"Current size: {canvas_size}",
                "Generate variants in 1080x1080px, 1080x1350px, 1080x1920px",
                "Same creative DNA, different aspect ratios",
            ],
            evolution_mode="cross_size_expansion",
            ad_name=ad.get("ad_name", ""),
            creative_format=classification.get("creative_format", ""),
            thumbnail_url=ad.get("thumbnail_url", ""),
            spend=ad.get("spend", 0),
            impressions=ad.get("impressions", 0),
        )

    def _detect_fatiguing(
        self, ad: dict, brand_id: str, baseline
    ) -> Optional[IterationOpportunity]:
        """Check if a historically strong ad has declining CTR (fatigue)."""
        if ad.get("impressions", 0) < 1000 or ad.get("spend", 0) < 50 or ad.get("days_active", 0) < 10:
            return None

        meta_ad_id = ad["meta_ad_id"]

        # Need daily series to detect trend
        try:
            daily_result = (
                self.supabase.table("meta_ads_performance")
                .select("date, link_ctr, impressions")
                .eq("meta_ad_id", meta_ad_id)
                .eq("brand_id", brand_id)
                .order("date")
                .execute()
            )
            if not daily_result.data or len(daily_result.data) < 10:
                return None

            rows = daily_result.data
            midpoint = len(rows) // 2
            first_half = rows[:midpoint]
            second_half = rows[midpoint:]

            # Compute CTR averages (weighted by impressions)
            def weighted_ctr(rows):
                total_imps = sum(r.get("impressions", 0) or 0 for r in rows)
                if total_imps == 0:
                    return 0
                weighted = sum(
                    (r.get("link_ctr", 0) or 0) * (r.get("impressions", 0) or 0)
                    for r in rows
                )
                return weighted / total_imps

            first_ctr = weighted_ctr(first_half)
            second_ctr = weighted_ctr(second_half)

            if first_ctr <= 0:
                return None

            decline_pct = (first_ctr - second_ctr) / first_ctr

            # Must have been strong (above median) and declining >15%
            median_ctr = _get_baseline_value(baseline, "ctr", "p50") if baseline else None
            if median_ctr and first_ctr < median_ctr:
                return None
            if decline_pct < 0.15:
                return None

        except Exception as e:
            logger.warning(f"Fatigue check failed for {meta_ad_id}: {e}")
            return None

        confidence = min(0.4 + decline_pct, 0.95)

        return IterationOpportunity(
            id=str(uuid4()),
            meta_ad_id=meta_ad_id,
            brand_id=brand_id,
            pattern_type="fatiguing_winner",
            pattern_label="Declining Performance (Fatigue)",
            confidence=round(confidence, 2),
            strong_metric="first_half_ctr",
            strong_value=round(first_ctr, 4),
            strong_percentile="n/a",
            weak_metric="ctr_decline_pct",
            weak_value=round(decline_pct, 3),
            weak_percentile=f"-{int(decline_pct * 100)}%",
            strategy_category="anti_fatigue",
            strategy_description="Anti-fatigue refresh \u2014 same psychology, fresh visual execution",
            strategy_actions=[
                f"CTR declined {int(decline_pct * 100)}% from first to second half of run",
                "Keep the same hook type and messaging angle",
                "Fresh visual execution: new image, different color treatment",
                "Consider new headline variation with same core promise",
            ],
            evolution_mode="anti_fatigue_refresh",
            ad_name=ad.get("ad_name", ""),
            creative_format="",
            thumbnail_url=ad.get("thumbnail_url", ""),
            spend=ad.get("spend", 0),
            impressions=ad.get("impressions", 0),
        )

    def _detect_proven_winner(
        self, ad: dict, brand_id: str, baseline
    ) -> Optional[IterationOpportunity]:
        """Detect ads performing well across all metrics — scale candidates.

        Proven winners have no exploitable weakness — they're strong across the board.
        These should be scaled via new sizes, fresh creative, or variable iteration.

        Requirements (all must be met):
        - ROAS above median (p50)
        - CTR above p25
        - Spend > $100
        - Impressions > 5000
        - Days active > 7
        """
        if not baseline:
            return None
        if ad.get("impressions", 0) < 5000:
            return None
        if ad.get("spend", 0) < 100:
            return None
        if ad.get("days_active", 0) < 7:
            return None

        roas = ad.get("roas", 0)
        ctr = ad.get("ctr", 0)

        median_roas = _get_baseline_value(baseline, "roas", "p50")
        p25_ctr = _get_baseline_value(baseline, "ctr", "p25")

        if median_roas is None or p25_ctr is None:
            return None
        if roas <= median_roas:
            return None
        if ctr <= p25_ctr:
            return None

        # Compute confidence from how far above thresholds
        roas_excess = min((roas / median_roas) - 1.0, 2.0) if median_roas > 0 else 0.5
        ctr_excess = min((ctr / p25_ctr) - 1.0, 2.0) if p25_ctr > 0 else 0.5
        volume_score = min(ad.get("impressions", 0) / 20000, 1.0)
        confidence = round(min(0.4 + (roas_excess + ctr_excess) * 0.15 + volume_score * 0.2, 0.95), 2)

        # Auto-recommend strategy based on profile
        strategy_actions = [
            f"ROAS {roas:.1f}x (above {median_roas:.1f}x median) on ${ad.get('spend', 0):,.0f} spend",
            "Generate in additional canvas sizes (1080x1080, 1350, 1920)",
            "Create fresh creative variants with same messaging angle",
            "Test hook variations to find even stronger stopping power",
        ]

        roas_pct = _compute_percentile_label(roas, baseline, "roas")
        ctr_pct = _compute_percentile_label(ctr, baseline, "ctr")

        return IterationOpportunity(
            id=str(uuid4()),
            meta_ad_id=ad["meta_ad_id"],
            brand_id=brand_id,
            pattern_type="proven_winner",
            pattern_label="Proven Winner",
            confidence=confidence,
            strong_metric="roas",
            strong_value=round(roas, 4),
            strong_percentile=roas_pct,
            weak_metric="ctr",
            weak_value=round(ctr, 4),
            weak_percentile=ctr_pct,
            strategy_category="scale",
            strategy_description="This ad performs well across all metrics — scale via new sizes, fresh creative, or variable iteration",
            strategy_actions=strategy_actions,
            evolution_mode="winner_iteration",
            ad_name=ad.get("ad_name", ""),
            creative_format="",
            thumbnail_url=ad.get("thumbnail_url", ""),
            spend=ad.get("spend", 0),
            impressions=ad.get("impressions", 0),
            explanation_headline=(
                f"This ad has {roas:.1f}x ROAS and {ctr*100:.1f}% CTR — strong across the board. "
                f"It's a proven winner ready to be scaled."
            ),
            explanation_projection=(
                "Expanding to new sizes and creating fresh variants can capture "
                "additional audiences without diminishing returns."
            ),
            projected_roas=roas,
        )

    # ---------------------------------------------------------------------------
    # Strategy building
    # ---------------------------------------------------------------------------

    def _build_strategy_actions(
        self,
        pattern_type: str,
        ad: dict,
        baseline,
        classification: dict,
    ) -> list:
        """Build specific strategy action items for a pattern."""
        actions = []

        if pattern_type == "high_converter_low_stopper":
            actions = [
                "Increase visual contrast (scroll-stopping power)",
                "Add bold short headline (3-5 words max)",
                "Try face with eye contact if not present",
                "Use warm, high-contrast color palette",
            ]
        elif pattern_type == "good_hook_bad_close":
            actions = [
                "Strengthen CTA clarity and urgency",
                "Align offer promise with landing page",
                "Check price/value perception in ad copy",
                "Consider more direct benefit messaging",
            ]
        elif pattern_type == "thumb_stopper_quick_dropper":
            actions = [
                "Improve mid-video value delivery timing",
                "Add visual variety / scene changes after hook",
                "Shorten time to main benefit reveal",
                "Add text overlays to reinforce key points",
            ]
        elif pattern_type == "efficient_but_starved":
            roas = ad.get("roas", 0)
            spend = ad.get("spend", 0)
            actions = [
                f"Current ROAS: {roas:.1f}x on ${spend:.0f} spend",
                "Increase daily budget 20-50%",
                "Consider broadening audience targeting",
                "Test in additional ad sets / campaigns",
            ]

        return actions

    def _build_explanation(
        self,
        pattern_type: str,
        ad: dict,
        baseline,
    ) -> tuple:
        """Build data-driven explanation headline and projection.

        Returns:
            Tuple of (headline, projection, projected_roas).
        """
        ctr = ad.get("ctr", 0)
        roas = ad.get("roas", 0)
        cvr = ad.get("conversion_rate", 0)
        spend = ad.get("spend", 0)
        impressions = ad.get("impressions", 0)

        median_ctr = _get_baseline_value(baseline, "ctr", "p50") or 0
        median_roas = _get_baseline_value(baseline, "roas", "p50") or 0

        headline = ""
        projection = ""
        projected_roas = 0.0

        if pattern_type == "high_converter_low_stopper":
            headline = (
                f"This ad converts at {cvr*100:.1f}% — your messaging clearly resonates with buyers. "
                f"But CTR is only {ctr*100:.1f}%, meaning most people scroll past."
            )
            if ctr > 0 and median_ctr > 0:
                projected_roas = roas * (median_ctr / ctr)
                projection = (
                    f"If visual stopping power improved CTR to the median ({median_ctr*100:.1f}%), "
                    f"ROAS could go from {roas:.1f}x to ~{projected_roas:.1f}x "
                    f"(assumes constant conversion rate)."
                )

        elif pattern_type == "high_cvr_low_ctr":
            median_cvr = _get_baseline_value(baseline, "conversion_rate", "p50") or 0
            headline = (
                f"This ad converts {cvr*100:.1f}% of clickers into buyers — well above the {median_cvr*100:.1f}% median. "
                f"But CTR is only {ctr*100:.1f}%, so most people never see the message."
            )
            if ctr > 0 and median_ctr > 0:
                projected_roas = roas * (median_ctr / ctr)
                projection = (
                    f"The messaging resonates, but the creative doesn't stop the scroll. "
                    f"Lifting CTR to the median ({median_ctr*100:.1f}%) could push ROAS from {roas:.1f}x to ~{projected_roas:.1f}x "
                    f"(assumes constant conversion rate)."
                )

        elif pattern_type == "good_hook_bad_close":
            headline = (
                f"This ad gets clicked at {ctr*100:.1f}% (above median) but ROAS is only {roas:.1f}x. "
                f"People are interested but not converting."
            )
            projection = (
                f"Your brand's median ROAS is {median_roas:.1f}x. "
                f"Improving offer alignment or landing page congruence could close the gap."
            )
            projected_roas = median_roas

        elif pattern_type == "thumb_stopper_quick_dropper":
            hook_rate = ad.get("hook_rate", 0)
            hold_rate = ad.get("hold_rate", 0)
            headline = (
                f"Hook rate is {hook_rate*100:.1f}% (strong) but hold rate drops to {hold_rate*100:.1f}%. "
                f"Viewers lose interest after the first few seconds."
            )
            projection = (
                "Improving mid-video retention (pacing, value reveal timing) "
                "would increase completed views and conversions."
            )

        elif pattern_type == "efficient_but_starved":
            headline = (
                f"ROAS is {roas:.1f}x on only ${spend:,.0f} spend and {impressions:,} impressions. "
                f"This ad is profitable but under-scaled."
            )
            projection = (
                "Increasing budget 20-50% while monitoring ROAS could capture "
                "additional conversions without diminishing returns."
            )
            projected_roas = roas  # Maintain current

        elif pattern_type == "fatiguing_winner":
            decline = ad.get("ctr_decline_pct", 0)
            headline = (
                f"CTR has declined {abs(decline)*100:.0f}% from early to late performance. "
                f"This was a strong ad showing fatigue."
            )
            projection = (
                "Refresh the creative with the same messaging angle but new visuals "
                "to recapture initial performance."
            )

        return headline, projection, projected_roas

    def _build_iteration_instructions(self, opp: dict) -> str:
        """Build additional_instructions for WinnerEvolutionService."""
        pattern = opp.get("pattern_type", "")
        strong = opp.get("strong_metric", "")
        strong_val = opp.get("strong_value", 0)
        weak = opp.get("weak_metric", "")
        weak_val = opp.get("weak_value", 0)
        category = opp.get("strategy_category", "")
        actions = opp.get("strategy_actions") or []

        action_text = " ".join(f"({i+1}) {a}" for i, a in enumerate(actions[:4]))

        return (
            f"ITERATION DIRECTIVE ({category.upper()}): "
            f"This ad has strong {strong} ({strong_val}) but weak {weak} ({weak_val}). "
            f"Strategy: {action_text}"
        )

    # ---------------------------------------------------------------------------
    # Data loading
    # ---------------------------------------------------------------------------

    def _load_ads_with_performance(
        self, brand_id: str, days_back: int, product_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load ads with aggregated performance metrics."""
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()

        try:
            # Paginate — 90 days of data can exceed Supabase's 1000-row default
            all_rows: List[Dict] = []
            page_size = 1000
            offset = 0
            while True:
                result = (
                    self.supabase.table("meta_ads_performance")
                    .select(
                        "meta_ad_id, ad_name, thumbnail_url, date, spend, impressions, "
                        "link_clicks, link_ctr, link_cpc, "
                        "purchases, purchase_value, roas, "
                        "video_p25_watched, video_thruplay"
                    )
                    .eq("brand_id", brand_id)
                    .gte("date", cutoff)
                    .order("date", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                if not result.data:
                    break
                all_rows.extend(result.data)
                if len(result.data) < page_size:
                    break
                offset += page_size

            if not all_rows:
                return []

            logger.info(f"Loaded {len(all_rows)} performance rows for brand {brand_id} ({days_back} days)")

        except Exception as e:
            logger.error(f"Failed to load performance data: {e}")
            return []

        # Aggregate per ad
        ad_map: Dict[str, Dict[str, Any]] = {}
        for row in all_rows:
            ad_id = row["meta_ad_id"]
            if ad_id not in ad_map:
                ad_map[ad_id] = {
                    "meta_ad_id": ad_id,
                    "ad_name": row.get("ad_name", ""),
                    "thumbnail_url": row.get("thumbnail_url", ""),
                    "brand_id": brand_id,
                    "spend": 0,
                    "impressions": 0,
                    "link_clicks": 0,
                    "purchases": 0,
                    "purchase_value": 0,
                    "dates": set(),
                    # Video metrics
                    "video_p25_watched": 0,
                    "video_thruplay": 0,
                }
            # Keep the most recent non-empty thumbnail
            if row.get("thumbnail_url") and not ad_map[ad_id].get("thumbnail_url"):
                ad_map[ad_id]["thumbnail_url"] = row["thumbnail_url"]
            agg = ad_map[ad_id]
            agg["spend"] += float(row.get("spend") or 0)
            agg["impressions"] += int(row.get("impressions") or 0)
            agg["link_clicks"] += int(row.get("link_clicks") or 0)
            agg["purchases"] += int(row.get("purchases") or 0)
            agg["purchase_value"] += float(row.get("purchase_value") or 0)
            agg["video_p25_watched"] += int(row.get("video_p25_watched") or 0)
            agg["video_thruplay"] += int(row.get("video_thruplay") or 0)
            if row.get("date"):
                agg["dates"].add(row["date"])

        # Compute derived metrics
        ads = []
        for ad_id, agg in ad_map.items():
            imps = agg["impressions"]
            clicks = agg["link_clicks"]
            days_active = len(agg["dates"])

            ad = {
                "meta_ad_id": ad_id,
                "ad_name": agg["ad_name"],
                "thumbnail_url": agg.get("thumbnail_url", ""),
                "brand_id": brand_id,
                "spend": agg["spend"],
                "impressions": imps,
                "days_active": days_active,
                "ctr": (clicks / imps) if imps > 0 else 0,  # Decimal, matches baseline
                "cpc": (agg["spend"] / clicks) if clicks > 0 else 0,
                "roas": (agg["purchase_value"] / agg["spend"]) if agg["spend"] > 0 else 0,
                "conversion_rate": (agg["purchases"] / clicks) if clicks > 0 else 0,  # Decimal
            }

            # Video metrics (only if video data exists)
            if agg["video_p25_watched"] > 0 and imps > 0:
                ad["hook_rate"] = agg["video_p25_watched"] / imps
            if agg["video_thruplay"] > 0 and agg["video_p25_watched"] > 0:
                ad["hold_rate"] = agg["video_thruplay"] / agg["video_p25_watched"]

            ads.append(ad)

        # Product filter
        if product_id and ads:
            from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
            perf_service = AdPerformanceQueryService(self.supabase)
            all_ad_ids = [a["meta_ad_id"] for a in ads]
            product_ad_ids = perf_service._resolve_product_ad_ids(brand_id, product_id, all_ad_ids)
            ads = [a for a in ads if a["meta_ad_id"] in product_ad_ids]

        return ads

    def _load_classifications(self, brand_id: str) -> Dict[str, Dict]:
        """Load classifications keyed by meta_ad_id."""
        try:
            result = (
                self.supabase.table("ad_creative_classifications")
                .select("meta_ad_id, creative_format, creative_awareness_level, hook_type")
                .eq("brand_id", brand_id)
                .execute()
            )
            return {r["meta_ad_id"]: r for r in (result.data or [])}
        except Exception as e:
            logger.warning(f"Failed to load classifications: {e}")
            return {}

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _get_opportunity(self, opportunity_id: str) -> Optional[Dict]:
        """Load a single opportunity by ID."""
        try:
            result = (
                self.supabase.table("iteration_opportunities")
                .select("*")
                .eq("id", opportunity_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get opportunity {opportunity_id}: {e}")
            return None

    def _find_generated_ad(self, meta_ad_id: str, brand_id: str) -> Optional[str]:
        """Check if a meta ad has a corresponding generated_ad."""
        try:
            result = (
                self.supabase.table("meta_ad_mapping")
                .select("generated_ad_id")
                .eq("meta_ad_id", meta_ad_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["generated_ad_id"]
        except Exception as e:
            logger.warning(f"Failed to find generated_ad for {meta_ad_id}: {e}")
        return None

    def _get_account_id(self, meta_ad_id: str) -> Optional[str]:
        """Get the Meta ad account ID for a given ad."""
        try:
            result = (
                self.supabase.table("meta_ads_performance")
                .select("meta_ad_account_id")
                .eq("meta_ad_id", meta_ad_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["meta_ad_account_id"]
        except Exception as e:
            logger.warning(f"Failed to get account ID for {meta_ad_id}: {e}")
        return None

    def _mark_actioned(self, opportunity_id: str, child_ad_id: Optional[str]) -> None:
        """Mark opportunity as actioned."""
        try:
            self.supabase.table("iteration_opportunities").update({
                "status": "actioned",
                "actioned_at": datetime.utcnow().isoformat(),
                "evolved_ad_id": child_ad_id,
            }).eq("id", opportunity_id).execute()
        except Exception as e:
            logger.error(f"Failed to mark actioned {opportunity_id}: {e}")

    def _store_opportunities(
        self, opportunities: List[IterationOpportunity], org_id: str
    ) -> None:
        """Store detected opportunities in DB."""
        import json

        for opp in opportunities:
            try:
                row = {
                    "id": opp.id,
                    "organization_id": org_id,
                    "brand_id": opp.brand_id,
                    "meta_ad_id": opp.meta_ad_id,
                    "pattern_type": opp.pattern_type,
                    "pattern_label": opp.pattern_label,
                    "confidence": opp.confidence,
                    "strong_metric": opp.strong_metric,
                    "strong_value": opp.strong_value,
                    "strong_percentile": opp.strong_percentile,
                    "weak_metric": opp.weak_metric,
                    "weak_value": opp.weak_value,
                    "weak_percentile": opp.weak_percentile,
                    "strategy_category": opp.strategy_category,
                    "strategy_description": opp.strategy_description,
                    "strategy_actions": json.dumps(opp.strategy_actions),
                    "evolution_mode": opp.evolution_mode,
                    "status": opp.status,
                }
                self.supabase.table("iteration_opportunities").insert(row).execute()
            except Exception as e:
                # Likely duplicate — skip silently
                logger.debug(f"Failed to store opportunity {opp.meta_ad_id}/{opp.pattern_type}: {e}")

    def _resolve_org_id(self, org_id: str, brand_id: str) -> str:
        """Resolve 'all' org_id to real UUID."""
        if org_id != "all":
            return org_id
        try:
            row = (
                self.supabase.table("brands")
                .select("organization_id")
                .eq("id", str(brand_id))
                .limit(1)
                .execute()
            )
            if row.data:
                return row.data[0]["organization_id"]
        except Exception as e:
            logger.warning(f"Failed to resolve org_id for brand {brand_id}: {e}")
        return org_id

    def get_iteration_track_record(
        self, brand_id: str, org_id: str, min_days: int = 7
    ) -> Dict[str, Any]:
        """Get track record of past iterations (actioned opportunities).

        Returns summary: total iterations, how many outperformed, avg improvement.
        """
        try:
            result = (
                self.supabase.table("iteration_opportunities")
                .select("id, meta_ad_id, evolved_ad_id, actioned_at, pattern_type")
                .eq("brand_id", brand_id)
                .eq("status", "actioned")
                .execute()
            )
            if not result.data:
                return {"total": 0, "matured": 0, "outperformed": 0, "avg_improvement": 0}

            actioned = result.data
            matured = []

            for opp in actioned:
                evolved_id = opp.get("evolved_ad_id")
                if not evolved_id:
                    continue

                # Check if child has matured performance data
                lineage_result = (
                    self.supabase.table("ad_lineage")
                    .select("outperformed_parent, child_reward_score, parent_reward_score")
                    .eq("child_ad_id", evolved_id)
                    .limit(1)
                    .execute()
                )
                if lineage_result.data:
                    entry = lineage_result.data[0]
                    if entry.get("child_reward_score") is not None:
                        matured.append(entry)

            outperformed = sum(1 for m in matured if m.get("outperformed_parent"))
            improvements = []
            for m in matured:
                parent = m.get("parent_reward_score", 0) or 0
                child = m.get("child_reward_score", 0) or 0
                if parent > 0:
                    improvements.append((child - parent) / parent)

            avg_improvement = sum(improvements) / len(improvements) if improvements else 0

            return {
                "total": len(actioned),
                "matured": len(matured),
                "outperformed": outperformed,
                "avg_improvement": round(avg_improvement, 3),
            }

        except Exception as e:
            logger.error(f"Failed to get track record: {e}")
            return {"total": 0, "matured": 0, "outperformed": 0, "avg_improvement": 0}
