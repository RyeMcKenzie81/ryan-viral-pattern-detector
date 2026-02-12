"""
Tool Readiness Service.

Evaluates tool readiness for a brand using the declarative requirements
registry in viraltracker/ui/tool_readiness_requirements.py.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ToolReadinessService:
    """Evaluates tool readiness for a brand using the requirements registry."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        from viraltracker.services.dataset_freshness_service import DatasetFreshnessService

        self._db = get_supabase_client()
        self._freshness = DatasetFreshnessService()
        self._memo = {}

    def get_readiness_report(self, brand_id: str, session_org_id: str = None):
        """Build full readiness report for a brand.

        Args:
            brand_id: Brand UUID string.
            session_org_id: Organization ID from the user's session.
                Pass "all" for superusers to bypass feature gates.

        For each tool in the registry:
        1. Check if the tool's feature is enabled for the org (skip if not)
        2. Check applicability rules (e.g. competitors must exist)
        3. Evaluate hard requirements
        4. Evaluate soft requirements
        5. Evaluate freshness requirements
        6. Derive status: BLOCKED if any hard unmet, PARTIAL if any soft/freshness
           unmet, READY otherwise
        """
        from viraltracker.services.models import (
            ReadinessStatus, ToolReadiness, ToolReadinessReport,
        )
        from viraltracker.ui.tool_readiness_requirements import TOOL_REQUIREMENTS

        self._memo = {}

        try:
            brand_result = (
                self._db.table("brands")
                .select("name, organization_id")
                .eq("id", brand_id)
                .single()
                .execute()
            )
            brand_name = brand_result.data.get("name", "Unknown") if brand_result.data else "Unknown"
            brand_org_id = brand_result.data.get("organization_id") if brand_result.data else None
        except Exception as e:
            logger.warning(f"Failed to fetch brand {brand_id}: {e}")
            brand_name = "Unknown"
            brand_org_id = None

        all_freshness = {
            f["dataset_key"]: f for f in self._freshness.get_all_freshness(brand_id)
        }

        ready, partial, blocked, not_applicable = [], [], [], []

        from viraltracker.services.feature_service import FeatureService
        # Use session org for feature gating — superusers pass "all" which
        # bypasses all feature gates.  Fall back to the brand's org.
        feature_org_id = session_org_id or brand_org_id
        feature_service = FeatureService(self._db) if feature_org_id else None

        for tool_key, tool_config in TOOL_REQUIREMENTS.items():
            feature_key = tool_config.get("feature_key")
            if feature_key and feature_service and not feature_service.has_feature(feature_org_id, feature_key):
                continue

            applicability = tool_config.get("applicable_when")
            if applicability and not self._check_applicability(brand_id, applicability):
                not_applicable.append(ToolReadiness(
                    tool_key=tool_key,
                    tool_label=tool_config["label"],
                    icon=tool_config.get("icon", ""),
                    status=ReadinessStatus.NOT_APPLICABLE,
                    page_link=tool_config["page_link"],
                    summary=applicability.get("reason", "Not applicable for this brand"),
                ))
                continue

            try:
                tool_result = self._evaluate_tool(
                    brand_id, tool_key, tool_config, all_freshness
                )
            except Exception as e:
                logger.error(f"Failed to evaluate {tool_key} for brand {brand_id}: {e}")
                tool_result = ToolReadiness(
                    tool_key=tool_key,
                    tool_label=tool_config["label"],
                    icon=tool_config.get("icon", ""),
                    status=ReadinessStatus.BLOCKED,
                    page_link=tool_config["page_link"],
                    summary=f"Evaluation failed: {str(e)[:100]}",
                )

            if tool_result.status == ReadinessStatus.READY:
                ready.append(tool_result)
            elif tool_result.status == ReadinessStatus.PARTIAL:
                partial.append(tool_result)
            elif tool_result.status == ReadinessStatus.BLOCKED:
                blocked.append(tool_result)
            else:
                not_applicable.append(tool_result)

        # Compute unlocks_tools for non-ready tools
        non_ready_keys = {t.tool_key for t in partial + blocked}
        all_tools = ready + partial + blocked + not_applicable
        tool_label_map = {t.tool_key: t.tool_label for t in all_tools}

        for tool in partial + blocked:
            tool_config = TOOL_REQUIREMENTS.get(tool.tool_key, {})
            unlocks_keys = tool_config.get("unlocks", [])
            tool.unlocks_tools = [
                tool_label_map[k] for k in unlocks_keys
                if k in non_ready_keys and k != tool.tool_key
            ]

        total_tools = len(ready) + len(partial) + len(blocked)
        overall_pct = (len(ready) + 0.5 * len(partial)) / total_tools if total_tools > 0 else 0.0

        return ToolReadinessReport(
            brand_id=brand_id,
            brand_name=brand_name,
            ready=ready,
            partial=partial,
            blocked=blocked,
            not_applicable=not_applicable,
            overall_pct=overall_pct,
            generated_at=datetime.now(timezone.utc),
        )

    def _evaluate_tool(self, brand_id, tool_key, config, all_freshness):
        """Evaluate a single tool's readiness."""
        from viraltracker.services.models import (
            ReadinessStatus, RequirementType, ToolReadiness,
        )

        hard_results = [
            self._check_requirement(brand_id, req, RequirementType.HARD)
            for req in config.get("hard", [])
        ]
        soft_results = [
            self._check_requirement(brand_id, req, RequirementType.SOFT)
            for req in config.get("soft", [])
        ]
        freshness_results = [
            self._check_freshness(brand_id, req, all_freshness)
            for req in config.get("freshness", [])
        ]

        for group in config.get("any_of_groups", []):
            group_result = self._check_any_of_group(brand_id, group)
            if group.get("group_type") == "hard":
                hard_results.append(group_result)
            else:
                soft_results.append(group_result)

        hard_unmet = [r for r in hard_results if not r.met]
        soft_unmet = [r for r in soft_results if not r.met]
        fresh_unmet = [r for r in freshness_results if not r.met]

        if hard_unmet:
            status = ReadinessStatus.BLOCKED
        elif soft_unmet or fresh_unmet:
            status = ReadinessStatus.PARTIAL
        else:
            status = ReadinessStatus.READY

        unmet_labels = [r.label for r in hard_unmet + soft_unmet + fresh_unmet]
        summary = "Missing: " + ", ".join(unmet_labels) if unmet_labels else "All requirements met"

        return ToolReadiness(
            tool_key=tool_key,
            tool_label=config["label"],
            icon=config.get("icon", ""),
            status=status,
            page_link=config["page_link"],
            hard_results=hard_results,
            soft_results=soft_results,
            freshness_results=freshness_results,
            summary=summary,
        )

    def _check_any_of_group(self, brand_id, group):
        """Evaluate an any_of_group: pass if ANY sub-requirement is met."""
        from viraltracker.services.models import RequirementResult, RequirementType

        group_type = group.get("group_type", "soft")
        req_type = RequirementType.HARD if group_type == "hard" else RequirementType.SOFT

        sub_results = []
        for req in group.get("requirements", []):
            result = self._check_requirement(brand_id, req, req_type)
            sub_results.append(result)

        any_met = any(r.met for r in sub_results)

        if any_met:
            met_labels = [r.label for r in sub_results if r.met]
            detail = f"Satisfied by: {', '.join(met_labels)}"
        else:
            detail = "None configured (need at least one)"

        first_unmet = next((r for r in sub_results if not r.met), None)

        return RequirementResult(
            key=group["group_key"],
            label=group["group_label"],
            requirement_type=req_type,
            met=any_met,
            detail=detail,
            fix_action=first_unmet.fix_action if first_unmet and not any_met else None,
            fix_page_link=first_unmet.fix_page_link if first_unmet and not any_met else None,
        )

    def _check_requirement(self, brand_id, req, req_type):
        """Evaluate a hard or soft requirement."""
        from viraltracker.services.models import RequirementResult

        check_type = req.get("check")
        try:
            if check_type == "count_gt_zero":
                met, detail = self._check_count_gt_zero(brand_id, req)
            elif check_type == "count_via_products":
                met, detail = self._check_count_via_products(brand_id, req)
            elif check_type == "count_any_of":
                met, detail = self._check_count_any_of(brand_id, req)
            elif check_type == "field_not_null":
                met, detail = self._check_field_not_null(brand_id, req)
            elif check_type == "competitors_have_field":
                met, detail = self._check_competitors_have_field(brand_id, req)
            else:
                met, detail = False, f"Unknown check type: {check_type}"
        except Exception as e:
            logger.error(f"Requirement check {req['key']} failed: {e}")
            met, detail = False, f"Check failed: {str(e)[:100]}"

        return RequirementResult(
            key=req["key"],
            label=req["label"],
            requirement_type=req_type,
            met=met,
            detail=detail,
            fix_action=req.get("fix_action"),
            fix_page_link=req.get("fix_page_link"),
            fix_job_type=req.get("fix_job_type"),
        )

    def _check_freshness(self, brand_id, req, all_freshness):
        """Evaluate a freshness requirement using prefetched freshness data."""
        from viraltracker.services.models import RequirementResult, RequirementType

        dataset_key = req["dataset_key"]
        max_age_hours = req["max_age_hours"]

        freshness_data = all_freshness.get(dataset_key)

        is_fresh = False
        last_updated = None

        if freshness_data and freshness_data.get("last_success_at"):
            try:
                last_ts = freshness_data["last_success_at"].replace("Z", "+00:00")
                last_dt = datetime.fromisoformat(last_ts)
                if not last_dt.tzinfo:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last_dt
                is_fresh = age.total_seconds() < max_age_hours * 3600
                last_updated = last_dt
            except (ValueError, TypeError):
                is_fresh = False

        if is_fresh:
            detail = f"Fresh (last sync: {freshness_data['last_success_at']})"
        elif freshness_data and freshness_data.get("last_success_at"):
            detail = f"Stale (last sync: {freshness_data['last_success_at']})"
        else:
            detail = "Never synced"

        return RequirementResult(
            key=req["key"],
            label=req["label"],
            requirement_type=RequirementType.FRESHNESS,
            met=is_fresh,
            detail=detail,
            fix_action=req.get("fix_action"),
            fix_job_type=req.get("fix_job_type"),
            last_updated=last_updated,
        )

    def _check_applicability(self, brand_id, rule):
        """Check if a tool is applicable for this brand."""
        if rule.get("check") == "count_gt_zero":
            met, _ = self._check_count_gt_zero(brand_id, rule)
            return met
        return True

    def _check_count_gt_zero(self, brand_id, req):
        """Check if table has >= 1 row matching filters. Memoized."""
        table = req["table"]
        filters = {
            k: (v.replace("{brand_id}", brand_id) if isinstance(v, str) else v)
            for k, v in req.get("filter", {}).items()
        }

        memo_key = (table, tuple(sorted(filters.items())))
        if memo_key in self._memo:
            count = self._memo[memo_key]
            return count > 0, f"{count} found" if count > 0 else "None found"

        query = self._db.table(table).select("id", count="exact")
        for col, val in filters.items():
            query = query.eq(col, val)
        result = query.limit(1).execute()

        count = result.count or 0
        self._memo[memo_key] = count
        return count > 0, f"{count} found" if count > 0 else "None found"

    def _check_count_via_products(self, brand_id, req):
        """Check tables without brand_id by joining through products."""
        product_ids_key = ("_product_ids", brand_id)
        if product_ids_key not in self._memo:
            result = self._db.table("products").select("id").eq("brand_id", brand_id).execute()
            self._memo[product_ids_key] = [r["id"] for r in (result.data or [])]

        product_ids = self._memo[product_ids_key]
        if not product_ids:
            return False, "No products (prerequisite)"

        table = req["table"]
        join_key = req.get("join_key", "product_id")

        total = 0
        for i in range(0, len(product_ids), 500):
            batch = product_ids[i:i + 500]
            result = self._db.table(table).select("id", count="exact").in_(join_key, batch).execute()
            total += (result.count or 0)

        return total > 0, f"{total} found" if total > 0 else "None found"

    def _check_count_any_of(self, brand_id, req):
        """Check if any of multiple tables has >= 1 row."""
        tables = req.get("tables", [])
        for table in tables:
            try:
                result = self._db.table(table).select("id", count="exact").limit(1).execute()
                if (result.count or 0) > 0:
                    return True, f"Found in {table}"
            except Exception as e:
                logger.debug(f"Table {table} check failed (may not exist): {e}")
                continue
        return False, "None found in any source"

    def _check_field_not_null(self, brand_id, req):
        """Check if a specific field on a record is not null/empty."""
        table = req["table"]
        field = req["field"]
        filters = {
            k: (v.replace("{brand_id}", brand_id) if isinstance(v, str) else v)
            for k, v in req["filter"].items()
        }

        query = self._db.table(table).select(field)
        for col, val in filters.items():
            query = query.eq(col, val)
        result = query.limit(1).execute()

        if not result.data:
            return False, "Record not found"
        value = result.data[0].get(field)
        has_value = bool(value and str(value).strip())
        return has_value, "Configured" if has_value else "Not set"

    def _check_competitors_have_field(self, brand_id, req):
        """Check how many competitors have a non-null field."""
        field = req["field"]
        result = (
            self._db.table("competitors")
            .select(f"id, {field}")
            .eq("brand_id", brand_id)
            .execute()
        )

        competitors = result.data or []
        if not competitors:
            return False, "No competitors"

        with_field = sum(1 for c in competitors if c.get(field) and str(c[field]).strip())
        total = len(competitors)

        if with_field == total:
            return True, f"All {total} competitors configured"
        elif with_field > 0:
            return False, f"{with_field}/{total} competitors configured"
        else:
            return False, f"None of {total} competitors configured"
