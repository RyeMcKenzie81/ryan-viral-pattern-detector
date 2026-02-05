"""ChatRenderer: Converts structured Pydantic results to markdown for chat display.

Adapter layer between typed service responses and the chat UI.
All methods are static — no state, no DB access.
"""

from __future__ import annotations

from typing import List

from .models import (
    AccountAnalysisResult,
    CongruenceCheckResult,
    CoverageGapResult,
    FatigueCheckResult,
    Recommendation,
    RecommendationCategory,
)


class ChatRenderer:
    """Converts structured Pydantic results to markdown for chat display."""

    @staticmethod
    def render_account_analysis(result: AccountAnalysisResult) -> str:
        """Render full account analysis as markdown.

        Args:
            result: AccountAnalysisResult from full_analysis().

        Returns:
            Formatted markdown string.
        """
        lines = [
            f"## Account Analysis: {result.brand_name}",
            f"**Run**: `{str(result.run_id)[:8]}` | "
            f"**Period**: {result.date_range} | "
            f"**Active Ads**: {result.active_ads} | "
            f"**Total Spend**: ${result.total_spend:,.2f}",
            "",
        ]

        # Awareness distribution with baseline and aggregate metrics
        if result.awareness_distribution:
            lines.append("### Awareness Distribution")
            has_baselines = bool(result.awareness_baselines)
            has_aggregates = bool(result.awareness_aggregates)

            # Build header based on available data
            if has_baselines or has_aggregates:
                header = "| Level | Ads | % |"
                separator = "|-------|-----|---|"
                if has_aggregates:
                    header += " Spend | Purchases | Clicks | Conv % |"
                    separator += "-------|-----------|--------|--------|"
                if has_baselines:
                    header += " Med CPM | Med CTR | Med CPA |"
                    separator += "---------|---------|---------|"
                lines.append(header)
                lines.append(separator)
            else:
                lines.append("| Level | Ads | % |")
                lines.append("|-------|-----|---|")

            total = sum(result.awareness_distribution.values()) or 1
            for level, count in sorted(result.awareness_distribution.items()):
                pct = (count / total) * 100
                label = level.replace("_", " ").title()

                if has_baselines or has_aggregates:
                    row = f"| {label} | {count} | {pct:.0f}% |"

                    # Add aggregate metrics
                    if has_aggregates:
                        agg = result.awareness_aggregates.get(level, {})
                        spend = f"${agg.get('spend'):,.0f}" if agg.get('spend') is not None else "-"
                        purchases = str(int(agg.get('purchases', 0))) if agg.get('purchases') is not None else "-"
                        clicks = str(int(agg.get('clicks', 0))) if agg.get('clicks') is not None else "-"
                        conv = f"{agg.get('conversion_rate'):.1f}%" if agg.get('conversion_rate') is not None else "-"
                        row += f" {spend} | {purchases} | {clicks} | {conv} |"

                    # Add baseline metrics
                    if has_baselines:
                        bl = result.awareness_baselines.get(level, {})
                        cpm = f"${bl.get('cpm'):.2f}" if bl.get('cpm') is not None else "-"
                        ctr = f"{bl.get('ctr'):.2f}%" if bl.get('ctr') is not None else "-"
                        cpa = f"${bl.get('cpa'):.2f}" if bl.get('cpa') is not None else "-"
                        row += f" {cpm} | {ctr} | {cpa} |"

                    lines.append(row)
                else:
                    lines.append(f"| {label} | {count} | {pct:.0f}% |")
            lines.append("")

        # Format distribution
        if result.format_distribution:
            lines.append("### Format Distribution")
            lines.append("| Format | Count |")
            lines.append("|--------|-------|")
            for fmt, count in sorted(
                result.format_distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                label = fmt.replace("_", " ").title()
                lines.append(f"| {label} | {count} |")
            lines.append("")

        # Health summary
        if result.health_distribution:
            healthy = result.health_distribution.get("healthy", 0)
            warning = result.health_distribution.get("warning", 0)
            critical = result.health_distribution.get("critical", 0)
            insufficient = result.health_distribution.get("insufficient_data", 0)
            lines.append("### Health Summary")
            lines.append(
                f"- Healthy: **{healthy}** | "
                f"Warning: **{warning}** | "
                f"Critical: **{critical}** | "
                f"Insufficient Data: **{insufficient}**"
            )
            if result.healthy_ad_ids:
                ad_list = ", ".join(f"`{aid}`" for aid in result.healthy_ad_ids)
                lines.append(f"- Healthy ads: {ad_list}")
            lines.append("")

        # Top issues
        if result.top_issues:
            lines.append("### Top Issues")
            for i, rule in enumerate(result.top_issues[:5], 1):
                severity_icon = _severity_icon(rule.severity)
                ad_count = len(rule.affected_ad_ids) if rule.affected_ad_ids else 0
                count_str = f" ({ad_count} ads)" if ad_count > 0 else ""
                lines.append(
                    f"{i}. {severity_icon} **{rule.rule_name}**{count_str} — {rule.explanation}"
                )
                # Show affected ad IDs (truncate to first 5)
                if rule.affected_ad_ids:
                    shown = rule.affected_ad_ids[:5]
                    ad_list = ", ".join(f"`{aid}`" for aid in shown)
                    if len(rule.affected_ad_ids) > 5:
                        ad_list += f" +{len(rule.affected_ad_ids) - 5} more"
                    lines.append(f"   Ads: {ad_list}")
            lines.append("")

        # Recommendations detail
        if result.recommendations:
            lines.append(
                f"### Recommendations ({len(result.recommendations)} total: "
                f"{result.critical_recommendations} critical, "
                f"{result.pending_recommendations} pending)"
            )
            lines.append("")

            for rec in result.recommendations:
                priority_icon = _priority_icon(rec.priority)
                short_id = str(rec.id)[:8] if rec.id else "---"
                cat_label = rec.category.value if hasattr(rec.category, "value") else rec.category
                lines.append(f"**{priority_icon} [{short_id}]** {cat_label.upper()}: {rec.title}")
                lines.append(f"  {rec.summary}")

                if rec.evidence:
                    for ev in rec.evidence[:2]:
                        lines.append(f"  - {ev.metric}: {ev.observation}")

                lines.append(f"  **Action**: {rec.action_description}")

                if rec.affected_ad_ids:
                    shown = rec.affected_ad_ids[:5]
                    ad_list = ", ".join(f"`{aid}`" for aid in shown)
                    if len(rec.affected_ad_ids) > 5:
                        ad_list += f" +{len(rec.affected_ad_ids) - 5} more"
                    lines.append(f"  Affects: {ad_list}")

                lines.append(
                    f"  > `/rec_done {short_id}` | "
                    f"`/rec_ignore {short_id}` | "
                    f"`/rec_note {short_id} \"text\"`"
                )
                lines.append("")
        else:
            lines.append(
                f"### Recommendations: "
                f"{result.critical_recommendations} critical, "
                f"{result.pending_recommendations} pending"
            )
            lines.append("Use `/recommend` for full inbox.")

        return "\n".join(lines)

    @staticmethod
    def render_recommendations(recs: List[Recommendation]) -> str:
        """Render recommendation inbox as markdown.

        Groups by priority (critical → low). Each rec shows ID, title,
        summary, evidence, and action links.

        Args:
            recs: List of Recommendation models.

        Returns:
            Formatted markdown string.
        """
        if not recs:
            return "No recommendations found."

        lines = [f"## Recommendation Inbox ({len(recs)} items)", ""]

        # Group by priority
        priority_order = ["critical", "high", "medium", "low"]
        grouped = {p: [] for p in priority_order}
        for rec in recs:
            grouped.get(rec.priority, grouped["medium"]).append(rec)

        for priority in priority_order:
            group = grouped[priority]
            if not group:
                continue

            priority_icon = _priority_icon(priority)
            lines.append(f"### {priority_icon} {priority.title()} ({len(group)})")
            lines.append("")

            for rec in group:
                short_id = str(rec.id)[:8] if rec.id else "---"
                cat_label = rec.category.value if isinstance(rec.category, RecommendationCategory) else rec.category
                lines.append(f"**[{short_id}]** {cat_label.upper()}: {rec.title}")
                lines.append(f"  {rec.summary}")

                if rec.evidence:
                    for ev in rec.evidence[:3]:
                        lines.append(f"  - {ev.metric}: {ev.observation}")

                lines.append(f"  **Action**: {rec.action_description}")

                if rec.affected_ads:
                    ad_names = [a.ad_name or a.ad_id for a in rec.affected_ads[:3]]
                    lines.append(f"  Affects: {', '.join(ad_names)}")

                lines.append(
                    f"  > `/rec_done {short_id}` | "
                    f"`/rec_ignore {short_id}` | "
                    f"`/rec_note {short_id} \"text\"`"
                )
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def render_fatigue_check(result: FatigueCheckResult) -> str:
        """Render fatigue check results as markdown.

        Shows fatigued ads, at-risk ads, and healthy count.

        Args:
            result: FatigueCheckResult model.

        Returns:
            Formatted markdown string.
        """
        lines = [
            f"## Fatigue Check: {result.brand_name}",
            f"{result.summary}",
            "",
        ]

        if result.fatigued_ads:
            lines.append(f"### Fatigued Ads ({len(result.fatigued_ads)})")
            lines.append("| Ad | Frequency | CTR Trend | Days Running |")
            lines.append("|-----|-----------|-----------|--------------|")
            for ad in result.fatigued_ads:
                name = ad.get("ad_name", ad.get("meta_ad_id", "Unknown"))[:30]
                freq = ad.get("frequency", "N/A")
                ctr_trend = ad.get("ctr_trend", "N/A")
                days = ad.get("days_running", "N/A")
                lines.append(f"| {name} | {freq} | {ctr_trend} | {days} |")
            lines.append("")

        if result.at_risk_ads:
            lines.append(f"### At-Risk Ads ({len(result.at_risk_ads)})")
            lines.append("| Ad | Frequency | CTR Trend |")
            lines.append("|-----|-----------|-----------|")
            for ad in result.at_risk_ads:
                name = ad.get("ad_name", ad.get("meta_ad_id", "Unknown"))[:30]
                freq = ad.get("frequency", "N/A")
                ctr_trend = ad.get("ctr_trend", "N/A")
                lines.append(f"| {name} | {freq} | {ctr_trend} |")
            lines.append("")

        lines.append(f"Healthy ads: **{result.healthy_ads_count}**")

        return "\n".join(lines)

    @staticmethod
    def render_coverage_gaps(result: CoverageGapResult) -> str:
        """Render coverage gap analysis as markdown.

        Shows awareness × format matrix and gap list.

        Args:
            result: CoverageGapResult model.

        Returns:
            Formatted markdown string.
        """
        lines = [f"## Coverage Gaps: {result.brand_name}", ""]

        # Coverage matrix
        if result.coverage_matrix:
            formats = set()
            for level_data in result.coverage_matrix.values():
                formats.update(level_data.keys())
            formats_list = sorted(formats)

            if formats_list:
                header = "| Awareness | " + " | ".join(
                    f.replace("_", " ").title()[:15] for f in formats_list
                ) + " |"
                separator = "|" + "|".join(["---"] * (len(formats_list) + 1)) + "|"
                lines.append("### Coverage Matrix")
                lines.append(header)
                lines.append(separator)

                for level in [
                    "unaware", "problem_aware", "solution_aware",
                    "product_aware", "most_aware"
                ]:
                    level_data = result.coverage_matrix.get(level, {})
                    label = level.replace("_", " ").title()
                    row = f"| {label} | " + " | ".join(
                        str(level_data.get(f, 0)) for f in formats_list
                    ) + " |"
                    lines.append(row)
                lines.append("")

        # Gaps
        if result.gaps:
            lines.append(f"### Identified Gaps ({len(result.gaps)})")
            for gap in result.gaps:
                severity = gap.get("severity", "info")
                icon = _severity_icon(severity)
                desc = gap.get("description", "")
                lines.append(f"- {icon} {desc}")
            lines.append("")

        # Recommendations
        if result.recommendations:
            lines.append("### Suggested Actions")
            for rec in result.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)

    @staticmethod
    def render_congruence_check(result: CongruenceCheckResult) -> str:
        """Render congruence check results as markdown.

        Shows misaligned ads with awareness levels and scores,
        plus per-dimension breakdown for ads with deep analysis.

        Args:
            result: CongruenceCheckResult model.

        Returns:
            Formatted markdown string.
        """
        lines = [
            f"## Congruence Check: {result.brand_name}",
            f"Checked **{result.checked_ads}** ads | "
            f"Average congruence: **{result.average_congruence:.2f}**",
            "",
        ]

        if result.misaligned_ads:
            lines.append(f"### Misaligned Ads ({len(result.misaligned_ads)})")
            lines.append("| Ad | Creative | Copy | LP | Score |")
            lines.append("|----|----------|------|----|-------|")
            for ad in result.misaligned_ads:
                name = ad.get("ad_name", ad.get("meta_ad_id", "Unknown"))[:25]
                creative = ad.get("creative_level", "N/A")
                copy = ad.get("copy_level", "N/A")
                lp = ad.get("lp_level", "N/A")
                score = ad.get("congruence_score", 0)
                lines.append(
                    f"| {name} | {creative} | {copy} | {lp} | {score:.2f} |"
                )
            lines.append("")
        else:
            lines.append("All ads are well-aligned.")
            lines.append("")

        # Deep Analysis section for ads with congruence_components
        if result.deep_analysis_ads:
            count = len(result.deep_analysis_ads)
            lines.append(f"### Deep Analysis Available ({count} ad{'s' if count > 1 else ''})")
            lines.append("")

            for ad in result.deep_analysis_ads:
                ad_id = ad.get("meta_ad_id", "Unknown")
                score = ad.get("congruence_score", 0)
                components = ad.get("congruence_components", [])

                lines.append(f"**Ad {ad_id}** (score: {score:.2f}):")

                if components:
                    for comp in components:
                        dimension = comp.get("dimension", "unknown")
                        assessment = comp.get("assessment", "unevaluated")
                        explanation = comp.get("explanation", "")
                        suggestion = comp.get("suggestion")

                        # Choose icon based on assessment
                        if assessment == "aligned":
                            icon = "[OK]"
                        elif assessment == "weak":
                            icon = "[!]"
                        elif assessment == "missing":
                            icon = "[X]"
                        else:
                            icon = "[?]"

                        # Format dimension name for display
                        dim_display = dimension.replace("_", " ").title()

                        # Build the line
                        if explanation:
                            lines.append(f"  {icon} {dim_display}: {assessment} - {explanation}")
                        else:
                            lines.append(f"  {icon} {dim_display}: {assessment}")

                        # Add suggestion if present
                        if suggestion and assessment in ("weak", "missing"):
                            lines.append(f"      -> {suggestion}")
                else:
                    lines.append("  No dimension data available")

                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def render_status_update(rec: Recommendation) -> str:
        """Render recommendation status update confirmation.

        Args:
            rec: Updated Recommendation model.

        Returns:
            Formatted markdown string.
        """
        short_id = str(rec.id)[:8] if rec.id else "---"
        status_val = rec.status.value if hasattr(rec.status, "value") else rec.status
        lines = [
            f"Recommendation **[{short_id}]** updated to **{status_val}**.",
        ]
        if rec.user_note:
            lines.append(f"Note: _{rec.user_note}_")
        return "\n".join(lines)


# =============================================================================
# Helpers
# =============================================================================

def _severity_icon(severity: str) -> str:
    """Map severity to a text indicator."""
    return {
        "critical": "[CRITICAL]",
        "warning": "[WARNING]",
        "info": "[INFO]",
    }.get(severity, "[INFO]")


def _priority_icon(priority: str) -> str:
    """Map priority to a text indicator."""
    return {
        "critical": "[!!!]",
        "high": "[!!]",
        "medium": "[!]",
        "low": "[-]",
    }.get(priority, "[-]")
