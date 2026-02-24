"""Per-phase quality diagnostics for the multipass pipeline.

Measures each phase's contribution objectively with PASS/FAIL verdicts
and actionable next steps. Designed as an observability tool — never
crashes, never gates the pipeline.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PhaseMetrics:
    """Metrics for a single pipeline phase."""

    phase_name: str
    html_size: int
    slot_count: int
    slot_names: FrozenSet[str]
    section_count: int
    image_count: int
    css_chars: int
    # Text quality
    text_fidelity_vs_source: Optional[float] = None
    # Delta vs previous phase
    slots_added: Optional[FrozenSet[str]] = None
    slots_lost: Optional[FrozenSet[str]] = None
    text_similarity_vs_prev: Optional[float] = None
    css_chars_delta: Optional[int] = None
    section_count_delta: Optional[int] = None
    # Phase-specific extras
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseVerdict:
    """PASS/FAIL/WARN verdict with actionable next step."""

    phase_name: str
    passed: bool
    issues: List[str] = field(default_factory=list)        # FAIL-level
    warnings: List[str] = field(default_factory=list)      # WARN-level (never cause FAIL)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class DiagnosticThresholds:
    """Tunable pass/fail thresholds."""

    min_slots: int = 5
    min_text_fidelity_phase2: float = 0.70
    min_text_fidelity_final: float = 0.85
    min_slot_retention: float = 0.95
    min_text_similarity: float = 0.90
    min_placeholder_pct: float = 0.70


@dataclass
class PhaseDiagnosticReport:
    """Complete pipeline diagnostic."""

    phases: List[PhaseMetrics]
    verdicts: List[PhaseVerdict]
    overall_passed: bool
    source_token_count: int = 0
    visual_scores: Optional[Dict[str, float]] = None      # phase_name -> SSIM score
    visual_trajectory: Optional[str] = None                # "improving" / "regressing" / "flat"

    def format(self, verbose: bool = False) -> str:
        """Render as human-readable text."""
        lines = [
            "=" * 64,
            "PIPELINE PHASE DIAGNOSTIC REPORT",
            "=" * 64,
            "",
        ]

        for metrics, verdict in zip(self.phases, self.verdicts):
            status = "PASS" if verdict.passed else "FAIL"
            lines.append(
                f"{metrics.phase_name:<50s}{status:>6s}"
            )

            detail_parts = []
            extras = metrics.extras

            if metrics.phase_name == "Phase 0 — Design System":
                detail_parts.append(
                    f"Colors: {extras.get('color_count', '?')}  |  "
                    f"Typography: {extras.get('typography_entries', '?')}  |  "
                    f"Defaults: {'yes' if extras.get('used_defaults') else 'no'}"
                )
            elif metrics.phase_name == "Phase 1 — Layout Skeleton":
                detail_parts.append(
                    f"CSS: {metrics.css_chars:,} chars (incl. responsive)  |  "
                    f"Placeholders: {extras.get('placeholder_count', '?')}"
                    f"/{extras.get('expected_sections', '?')}"
                )
                detail_parts.append(
                    f"Sections: {metrics.section_count}  |  "
                    f"Skeleton: {metrics.html_size:,} chars"
                )
                # v2 sub-step timings
                v2_telemetry = extras.get("v2_telemetry")
                if v2_telemetry:
                    fb = v2_telemetry.get("fallback_level", "?")
                    timings = v2_telemetry.get("step_timings", {})
                    t_parts = [f"{k}={v:.1f}s" for k, v in timings.items()]
                    detail_parts.append(
                        f"v2 mode: fallback_level={fb}  |  "
                        + "  ".join(t_parts)
                    )
            elif metrics.phase_name == "Phase 2 — Content Assembly":
                detail_parts.append(
                    f"Slots: {metrics.slot_count}  |  "
                    f"Unresolved: {extras.get('unresolved_placeholders', '?')}  |  "
                    f"Overflow sections: {extras.get('overflow_section_count', 0)}"
                )
                fidelity = metrics.text_fidelity_vs_source
                fid_str = f"{fidelity:.2f}" if fidelity is not None else "N/A"
                detail_parts.append(
                    f"Text fidelity: {fid_str} (vs source)  |  "
                    f"Images: {metrics.image_count}"
                )
            elif metrics.phase_name in (
                "Phase 3 — Visual Refinement",
                "Phase 4 — Patch Pass",
            ):
                if metrics.slots_lost is not None and metrics.slots_added is not None:
                    prev_count = (
                        metrics.slot_count
                        + len(metrics.slots_lost)
                        - len(metrics.slots_added)
                    )
                    retention = (
                        metrics.slot_count / prev_count if prev_count > 0 else 1.0
                    )
                else:
                    retention = 1.0
                slot_info = f"Slots: {metrics.slot_count} (retention: {retention:.2f})"
                if metrics.slots_lost:
                    slot_info += f"  |  Lost: {', '.join(sorted(metrics.slots_lost))}"
                detail_parts.append(slot_info)

                sim = metrics.text_similarity_vs_prev
                sim_str = f"{sim:.2f}" if sim is not None else "skipped"
                prev_label = (
                    "Phase 2" if "3" in metrics.phase_name else "Phase 3"
                )
                css_delta = metrics.css_chars_delta
                css_str = (
                    f"+{css_delta}" if css_delta is not None and css_delta >= 0
                    else str(css_delta) if css_delta is not None
                    else "?"
                )
                detail_parts.append(
                    f"Text sim: {sim_str} (vs {prev_label})  |  "
                    f"CSS: {css_str} chars  |  Images: {metrics.image_count}"
                )
                if "3" in metrics.phase_name:
                    uc = extras.get("unchanged_section_count")
                    total = metrics.section_count
                    if uc is not None:
                        detail_parts.append(
                            f"Unchanged sections: {uc}/{total} (rejected or no-op)"
                        )
            elif metrics.phase_name == "Final Output":
                fidelity = metrics.text_fidelity_vs_source
                fid_str = f"{fidelity:.2f}" if fidelity is not None else "N/A"
                wrapper = extras.get("has_lp_mockup_wrapper")
                wrapper_str = "present" if wrapper else "MISSING"
                detail_parts.append(
                    f"Slots: {metrics.slot_count}  |  "
                    f"Text fidelity: {fid_str} (vs source)"
                )
                detail_parts.append(
                    f"Images: {metrics.image_count}  |  "
                    f".lp-mockup: {wrapper_str}"
                )

            for dp in detail_parts:
                lines.append(f"  {dp}")

            for issue in verdict.issues:
                lines.append(f"  !! {issue}")
            for warning in verdict.warnings:
                lines.append(f"  WARN: {warning}")
            for ns in verdict.next_steps:
                lines.append(f"  -> {ns}")
            lines.append("")

        # Visual scores section
        if self.visual_scores:
            lines.append("-" * 64)
            lines.append("VISUAL FIDELITY (SSIM vs original)")
            lines.append("-" * 64)
            for phase_key, ssim in sorted(self.visual_scores.items()):
                lines.append(f"  {phase_key:<40s}{ssim:.4f}")
            if self.visual_trajectory:
                lines.append(f"  Trajectory: {self.visual_trajectory}")
            lines.append("")

        lines.append("=" * 64)
        if self.overall_passed:
            lines.append("VERDICT: PASS")
        else:
            fail_phases = [
                v.phase_name for v in self.verdicts if not v.passed
            ]
            fail_summary = "; ".join(
                f"{v.phase_name}: {v.issues[0]}"
                for v in self.verdicts
                if not v.passed and v.issues
            )
            lines.append(f"VERDICT: FAIL — {fail_summary}")
        lines.append("=" * 64)

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict for cross-run comparison."""
        return {
            "overall_passed": self.overall_passed,
            "source_token_count": self.source_token_count,
            "phases": [
                {
                    "phase_name": m.phase_name,
                    "html_size": m.html_size,
                    "slot_count": m.slot_count,
                    "slot_names": sorted(m.slot_names),
                    "section_count": m.section_count,
                    "image_count": m.image_count,
                    "css_chars": m.css_chars,
                    "text_fidelity_vs_source": m.text_fidelity_vs_source,
                    "slots_added": sorted(m.slots_added) if m.slots_added is not None else None,
                    "slots_lost": sorted(m.slots_lost) if m.slots_lost is not None else None,
                    "text_similarity_vs_prev": m.text_similarity_vs_prev,
                    "css_chars_delta": m.css_chars_delta,
                    "section_count_delta": m.section_count_delta,
                    "extras": m.extras,
                }
                for m in self.phases
            ],
            "verdicts": [
                {
                    "phase_name": v.phase_name,
                    "passed": v.passed,
                    "issues": v.issues,
                    "warnings": v.warnings,
                    "next_steps": v.next_steps,
                }
                for v in self.verdicts
            ],
            "visual_scores": self.visual_scores,
            "visual_trajectory": self.visual_trajectory,
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _count_css_chars(html: str) -> int:
    """Sum characters inside all <style> blocks. Uses re.DOTALL for multi-line."""
    return sum(
        len(m.group(1))
        for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
    )


def _count_placeholders(html: str) -> int:
    """Count unresolved {{sec_N...}} patterns."""
    return len(re.findall(r'\{\{sec_\d+[^}]*\}\}', html))


def _count_images(html: str) -> int:
    """Count <img> tags in HTML."""
    return len(re.findall(r'<img\b', html, re.IGNORECASE))


def _has_lp_mockup_wrapper(html: str) -> bool:
    """Check for .lp-mockup wrapper div."""
    return 'class="lp-mockup"' in html or "class='lp-mockup'" in html


def _unwrap_json_snapshot(html: str) -> dict:
    """Extract JSON from _wrap_json_as_html() format. Returns {} on failure."""
    try:
        match = re.search(r'<code>(.*?)</code>', html, re.DOTALL)
        return json.loads(match.group(1)) if match else {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def _count_sections(html: str) -> int:
    """Count elements with data-section attributes."""
    return len(re.findall(r'data-section=', html))


def _check_unclosed_tags(html: str) -> List[str]:
    """Quick check for obviously unclosed block-level tags.

    Returns list of tag names that appear unclosed. Not a full parser —
    just a heuristic for the most common structural issues.
    """
    unclosed = []
    for tag in ("section", "div", "main", "article"):
        opens = len(re.findall(rf'<{tag}[\s>]', html, re.IGNORECASE))
        closes = len(re.findall(rf'</{tag}>', html, re.IGNORECASE))
        if opens > closes:
            unclosed.append(f"<{tag}> ({opens} open, {closes} close)")
    return unclosed


def _count_unchanged_sections(phase2_html: str, phase3_html: str) -> int:
    """Count sections where Phase 3 output == Phase 2 output (rejected or no-op)."""
    from .invariants import parse_sections

    p2_sections = parse_sections(phase2_html)
    p3_sections = parse_sections(phase3_html)

    unchanged = 0
    for sec_id, p2_content in p2_sections.items():
        p3_content = p3_sections.get(sec_id)
        if p3_content is not None and p2_content.strip() == p3_content.strip():
            unchanged += 1
    return unchanged


def _compute_phase_metrics(
    phase_name: str,
    html: str,
    source_markdown: str,
    prev_metrics: Optional[PhaseMetrics],
    compute_fidelity: bool = False,
    is_surgery: bool = False,
) -> PhaseMetrics:
    """Compute base metrics for a phase snapshot."""
    from .invariants import extract_slots, tokenize_visible_text, text_similarity

    slot_set = extract_slots(html)
    tokens = tokenize_visible_text(html)
    section_count = _count_sections(html)

    # Text fidelity vs source
    # Surgery mode uses precision (doesn't penalize extra nav/footer text)
    text_fidelity = None
    if compute_fidelity and source_markdown:
        if is_surgery:
            from .eval_harness import score_text_fidelity_precision
            text_fidelity = score_text_fidelity_precision(html, source_markdown)
        else:
            from .eval_harness import score_text_fidelity
            text_fidelity = score_text_fidelity(html, source_markdown)

    # Delta vs previous phase
    slots_added = None
    slots_lost = None
    text_sim = None
    css_delta = None
    section_delta = None

    if prev_metrics is not None:
        slots_added = slot_set - prev_metrics.slot_names
        slots_lost = prev_metrics.slot_names - slot_set
        css_delta = _count_css_chars(html) - prev_metrics.css_chars
        section_delta = section_count - prev_metrics.section_count

        # Text similarity with short-text guard
        prev_tokens = tokenize_visible_text(prev_metrics._raw_html)
        if len(tokens) >= 10 or len(prev_tokens) >= 10:
            text_sim = text_similarity(prev_tokens, tokens)
        # else: leave as None (short-text guard)

    return PhaseMetrics(
        phase_name=phase_name,
        html_size=len(html),
        slot_count=len(slot_set),
        slot_names=slot_set,
        section_count=section_count,
        image_count=_count_images(html),
        css_chars=_count_css_chars(html),
        text_fidelity_vs_source=text_fidelity,
        slots_added=slots_added,
        slots_lost=slots_lost,
        text_similarity_vs_prev=text_sim,
        css_chars_delta=css_delta,
        section_count_delta=section_delta,
    )


# We need to stash raw HTML for inter-phase text comparison.
# Use a private attribute on PhaseMetrics to avoid polluting the public API.
# This is set in _compute_phase_metrics and used only internally.


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def _verdict_phase0(metrics: PhaseMetrics, thresholds: DiagnosticThresholds) -> PhaseVerdict:
    """Phase 0 — Design System verdict."""
    issues = []
    next_steps = []

    if metrics.extras.get("used_defaults"):
        issues.append(
            "Design system extraction failed, using defaults. "
            "ALL downstream phases inherit wrong colors/fonts."
        )
    color_count = metrics.extras.get("color_count", 0)
    if color_count < 2:
        issues.append(f"Only {color_count} colors — check screenshot quality")

    if issues:
        next_steps.append(
            "Check screenshot is non-blank. Inspect raw Phase 0 LLM response. "
            "Open phase_0_design_system.html to see extracted tokens."
        )

    return PhaseVerdict(
        phase_name=metrics.phase_name,
        passed=not any(
            "extraction failed" in i for i in issues
        ) and color_count >= 2,
        issues=issues,
        next_steps=next_steps,
    )


def _verdict_phase1(
    metrics: PhaseMetrics, thresholds: DiagnosticThresholds
) -> PhaseVerdict:
    """Phase 1 — Layout Skeleton verdict."""
    issues = []
    warnings = []
    next_steps = []

    placeholder_count = metrics.extras.get("placeholder_count", 0)
    expected = metrics.extras.get("expected_sections")

    if expected and expected > 0:
        pct = placeholder_count / expected
        if pct < thresholds.min_placeholder_pct:
            issues.append(
                f"Only {placeholder_count}/{expected} section placeholders "
                f"({pct:.0%} < {thresholds.min_placeholder_pct:.0%})"
            )

    if metrics.css_chars == 0:
        # Informational only — not a hard fail
        pass

    # WARN: Check for malformed placeholders
    raw_html = getattr(metrics, "_raw_html", "")
    if raw_html:
        malformed = re.findall(r'\{\{[^}]*(?:\}\}[^}]|\}(?!\}))', raw_html)
        # Also check for unclosed {{ without matching }}
        open_count = raw_html.count("{{")
        close_count = raw_html.count("}}")
        if open_count != close_count:
            warnings.append(
                f"Malformed placeholders: {open_count} opening vs {close_count} closing braces"
            )

    if issues:
        next_steps.append(
            "Open phase_1_skeleton.html in browser. If layout looks acceptable "
            "with inline styles, this is fine. If empty/broken, check Phase 1 prompt."
        )

    return PhaseVerdict(
        phase_name=metrics.phase_name,
        passed=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        next_steps=next_steps,
    )


def _verdict_phase2(metrics: PhaseMetrics, thresholds: DiagnosticThresholds) -> PhaseVerdict:
    """Phase 2 — Content Assembly verdict."""
    issues = []
    next_steps = []

    if metrics.slot_count < thresholds.min_slots:
        issues.append(f"Only {metrics.slot_count} slots (min: {thresholds.min_slots})")

    unresolved = metrics.extras.get("unresolved_placeholders", 0)
    if unresolved > 0:
        issues.append(f"{unresolved} placeholders unfilled")

    fidelity = metrics.text_fidelity_vs_source
    if fidelity is not None and fidelity < thresholds.min_text_fidelity_phase2:
        issues.append(
            f"Text fidelity {fidelity:.2f} (threshold: {thresholds.min_text_fidelity_phase2})"
        )

    if issues:
        next_steps.append(
            "This is deterministic code. Open phase_2_content.html and compare "
            "against source markdown. Check content_patterns.py detection."
        )

    return PhaseVerdict(
        phase_name=metrics.phase_name,
        passed=len(issues) == 0,
        issues=issues,
        next_steps=next_steps,
    )


def _verdict_refinement(
    metrics: PhaseMetrics,
    thresholds: DiagnosticThresholds,
    prev_label: str,
) -> PhaseVerdict:
    """Phase 3/4 — refinement verdict (deltas vs previous phase)."""
    issues = []
    warnings = []
    next_steps = []

    # Slot retention
    if metrics.slots_lost is not None and metrics.slot_names is not None:
        prev_count = (
            metrics.slot_count
            + len(metrics.slots_lost)
            - len(metrics.slots_added or frozenset())
        )
        if prev_count > 0:
            retention = metrics.slot_count / prev_count
            if retention < thresholds.min_slot_retention:
                lost_names = ", ".join(sorted(metrics.slots_lost))
                issues.append(
                    f"Lost {len(metrics.slots_lost)} slots during refinement "
                    f"(retention: {retention:.2f}, threshold: {thresholds.min_slot_retention}): "
                    f"{lost_names}"
                )

    # Text similarity
    sim = metrics.text_similarity_vs_prev
    if sim is not None and sim < thresholds.min_text_similarity:
        issues.append(
            f"Text sim {sim:.2f} — "
            f"{metrics.phase_name} is rewriting text "
            f"(threshold: {thresholds.min_text_similarity})"
        )

    # WARN: Phase 3 text preservation below 0.80 (softer threshold)
    if sim is not None and "3" in metrics.phase_name and sim < 0.80:
        pct_rewritten = (1.0 - sim) * 100
        warnings.append(f"Phase 3 rewrote {pct_rewritten:.0f}% of text (sim={sim:.2f})")

    # Section count
    if metrics.section_count_delta is not None and metrics.section_count_delta < 0:
        issues.append(f"Lost {abs(metrics.section_count_delta)} sections")

    if issues:
        if "3" in metrics.phase_name:
            next_steps.append(
                "Diff phase_2_content.html vs phase_3_refined.html. "
                "If text was rewritten, tighten Phase 3 prompt. "
                "If sections rejected, check screenshot crops."
            )
        else:
            next_steps.append(
                "Diff phase_3_refined.html vs phase_4_final.html. "
                "Check which patches were applied."
            )

    return PhaseVerdict(
        phase_name=metrics.phase_name,
        passed=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        next_steps=next_steps,
    )


def _verdict_final(
    metrics: PhaseMetrics,
    thresholds: DiagnosticThresholds,
    phase2_slot_count: Optional[int] = None,
) -> PhaseVerdict:
    """Final Output verdict."""
    issues = []
    warnings = []
    next_steps = []

    if metrics.slot_count < thresholds.min_slots:
        issues.append(
            f"Final output has only {metrics.slot_count} slots "
            f"(min: {thresholds.min_slots})"
        )

    fidelity = metrics.text_fidelity_vs_source
    if fidelity is not None and fidelity < thresholds.min_text_fidelity_final:
        issues.append(f"Text fidelity {fidelity:.2f} (threshold: {thresholds.min_text_fidelity_final})")

    if not metrics.extras.get("has_lp_mockup_wrapper"):
        issues.append(".lp-mockup wrapper missing — all scoped CSS is broken")

    # WARN: HTML well-formedness — check for unclosed tags
    raw_html = getattr(metrics, "_raw_html", "")
    if raw_html:
        unclosed = _check_unclosed_tags(raw_html)
        if unclosed:
            warnings.append(f"Malformed HTML: unclosed tags {unclosed[:3]}")

    # WARN: Slot retention vs Phase 2
    if phase2_slot_count is not None and phase2_slot_count > 0:
        retention = metrics.slot_count / phase2_slot_count
        if retention < 0.80:
            lost = phase2_slot_count - metrics.slot_count
            warnings.append(
                f"Lost {lost} slots between Phase 2 and final "
                f"(retention: {retention:.0%})"
            )

    if issues:
        next_steps.append("Inspect final output HTML for missing content or broken structure.")

    return PhaseVerdict(
        phase_name=metrics.phase_name,
        passed=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        next_steps=next_steps,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diagnose_phases(
    snapshots: Dict[str, str],
    source_markdown: str = "",
    thresholds: Optional[DiagnosticThresholds] = None,
    expected_section_count: Optional[int] = None,
) -> PhaseDiagnosticReport:
    """Compute per-phase quality metrics from pipeline snapshots.

    Handles missing snapshots gracefully. Each phase is computed independently
    in a try/except — if one fails, the rest still run.

    Args:
        snapshots: Dict of snapshot_key -> HTML string.
        source_markdown: Original page markdown (None-safe).
        thresholds: Optional custom thresholds (defaults used if None).
        expected_section_count: From segmenter, not markdown heading count.
    """
    from .invariants import tokenize_visible_text

    source_markdown = source_markdown or ""
    thresholds = thresholds or DiagnosticThresholds()

    source_tokens = tokenize_visible_text(
        f"<p>{source_markdown}</p>"
    ) if source_markdown else []

    all_metrics: List[PhaseMetrics] = []
    all_verdicts: List[PhaseVerdict] = []

    prev_metrics: Optional[PhaseMetrics] = None

    # Phase 0 — Design System
    phase0_key = "phase_0_design_system"
    if phase0_key in snapshots:
        try:
            html = snapshots[phase0_key]
            ds = _unwrap_json_snapshot(html)

            colors = ds.get("colors", {})
            typography = ds.get("typography", {})

            from .pipeline import DEFAULT_DESIGN_SYSTEM
            used_defaults = ds == DEFAULT_DESIGN_SYSTEM

            metrics = PhaseMetrics(
                phase_name="Phase 0 — Design System",
                html_size=len(html),
                slot_count=0,
                slot_names=frozenset(),
                section_count=0,
                image_count=0,
                css_chars=0,
                extras={
                    "color_count": len(colors),
                    "typography_entries": len(typography),
                    "used_defaults": used_defaults,
                },
            )
            # Stash raw HTML for potential inter-phase comparison
            metrics._raw_html = html
            all_metrics.append(metrics)
            all_verdicts.append(_verdict_phase0(metrics, thresholds))
        except Exception as e:
            logger.error(f"Phase 0 diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Phase 0 — Design System",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Phase 0 — Design System",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    # Phase 1 — Layout Skeleton
    phase1_key = "phase_1_skeleton"
    if phase1_key in snapshots:
        try:
            html = snapshots[phase1_key]
            metrics = _compute_phase_metrics(
                "Phase 1 — Layout Skeleton", html, source_markdown, None
            )
            metrics.extras["placeholder_count"] = _count_placeholders(html)
            metrics.extras["expected_sections"] = expected_section_count
            # Capture v2 sub-step telemetry if present
            v2_telemetry_key = "phase_1_v2_telemetry"
            if v2_telemetry_key in snapshots:
                try:
                    import json as _json
                    v2_raw = snapshots[v2_telemetry_key]
                    # Parse from the HTML wrapper
                    code_match = re.search(r'<code>(.*?)</code>', v2_raw, re.DOTALL)
                    if code_match:
                        metrics.extras["v2_telemetry"] = _json.loads(code_match.group(1))
                except Exception:
                    pass
            metrics._raw_html = html
            all_metrics.append(metrics)
            all_verdicts.append(_verdict_phase1(metrics, thresholds))
            prev_metrics = metrics
        except Exception as e:
            logger.error(f"Phase 1 diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Phase 1 — Layout Skeleton",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Phase 1 — Layout Skeleton",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    # Phase 2 — Content Assembly
    phase2_key = "phase_2_content"
    phase2_html = ""
    phase2_slot_count = None
    if phase2_key in snapshots:
        try:
            html = snapshots[phase2_key]
            phase2_html = html
            metrics = _compute_phase_metrics(
                "Phase 2 — Content Assembly", html, source_markdown,
                prev_metrics, compute_fidelity=True,
            )
            metrics.extras["unresolved_placeholders"] = _count_placeholders(html)
            metrics.extras["generic_fallback_count"] = len(
                re.findall(r'mp-generic', html)
            )
            metrics.extras["overflow_section_count"] = len(
                re.findall(r'mp-overflow', html)
            )
            metrics._raw_html = html
            all_metrics.append(metrics)
            all_verdicts.append(_verdict_phase2(metrics, thresholds))
            phase2_slot_count = metrics.slot_count
            prev_metrics = metrics
        except Exception as e:
            logger.error(f"Phase 2 diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Phase 2 — Content Assembly",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Phase 2 — Content Assembly",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    # Phase 3 — Visual Refinement
    phase3_key = "phase_3_refined"
    if phase3_key in snapshots:
        try:
            html = snapshots[phase3_key]
            metrics = _compute_phase_metrics(
                "Phase 3 — Visual Refinement", html, source_markdown,
                prev_metrics,
            )
            # Count unchanged sections (rejected or no-op)
            if phase2_html:
                metrics.extras["unchanged_section_count"] = _count_unchanged_sections(
                    phase2_html, html
                )
            metrics.extras["has_lp_mockup_wrapper"] = _has_lp_mockup_wrapper(html)
            metrics._raw_html = html
            all_metrics.append(metrics)
            all_verdicts.append(
                _verdict_refinement(metrics, thresholds, "Phase 2")
            )
            prev_metrics = metrics
        except Exception as e:
            logger.error(f"Phase 3 diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Phase 3 — Visual Refinement",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Phase 3 — Visual Refinement",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    # Phase 4 — Patch Pass
    phase4_key = "phase_4_final"
    if phase4_key in snapshots:
        try:
            html = snapshots[phase4_key]
            metrics = _compute_phase_metrics(
                "Phase 4 — Patch Pass", html, source_markdown,
                prev_metrics,
            )
            metrics._raw_html = html
            all_metrics.append(metrics)
            all_verdicts.append(
                _verdict_refinement(metrics, thresholds, "Phase 3")
            )
            prev_metrics = metrics
        except Exception as e:
            logger.error(f"Phase 4 diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Phase 4 — Patch Pass",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Phase 4 — Patch Pass",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    # --- Surgery pipeline mode ---
    # Auto-detect from snapshot keys and add surgery-specific diagnostics
    is_surgery = "phase_s0_sanitized" in snapshots

    if is_surgery:
        _SURGERY_PHASES = [
            ("phase_s0_sanitized", "S0 — Sanitize"),
            ("phase_s1_segmented", "S1 — Section Mapping"),
            ("phase_s2_classified", "S2 — Element Classification"),
            ("phase_s3_scoped", "S3 — CSS Scoping"),
            ("phase_s4_final", "S4 — Visual QA"),
        ]
        for phase_key, phase_label in _SURGERY_PHASES:
            if phase_key not in snapshots:
                continue
            try:
                html = snapshots[phase_key]
                metrics = _compute_phase_metrics(
                    phase_label, html, source_markdown,
                    prev_metrics,
                    compute_fidelity=(phase_key == "phase_s4_final"),
                    is_surgery=True,
                )
                metrics._raw_html = html
                all_metrics.append(metrics)

                # Surgery phases always pass if they have output
                verdict = PhaseVerdict(
                    phase_name=phase_label,
                    passed=bool(html and len(html) > 100),
                    issues=[] if html else ["Empty output"],
                )
                if phase_key == "phase_s4_final":
                    # Final surgery check: need at least 1 slot
                    if metrics.slot_count < 1:
                        verdict.passed = False
                        verdict.issues.append("0 data-slot attributes in final output")
                all_verdicts.append(verdict)
                prev_metrics = metrics
            except Exception as e:
                logger.error(f"{phase_label} diagnostic failed: {e}")
                m = PhaseMetrics(
                    phase_name=phase_label,
                    html_size=0, slot_count=0, slot_names=frozenset(),
                    section_count=0, image_count=0, css_chars=0,
                )
                m._raw_html = ""
                all_metrics.append(m)
                all_verdicts.append(PhaseVerdict(
                    phase_name=phase_label, passed=False,
                    issues=[f"Diagnostic error: {e}"],
                ))

    # Final Output — use the last available phase snapshot
    final_html = ""
    final_candidates = (
        ["phase_s4_final", "phase_s3_scoped", "phase_s2_classified"]
        if is_surgery else
        ["phase_4_final", "phase_3_refined", "phase_2_content"]
    )
    for key in final_candidates:
        if key in snapshots:
            final_html = snapshots[key]
            break

    if final_html:
        try:
            metrics = _compute_phase_metrics(
                "Final Output", final_html, source_markdown,
                None, compute_fidelity=True,
                is_surgery=is_surgery,
            )
            metrics.extras["has_lp_mockup_wrapper"] = _has_lp_mockup_wrapper(final_html)
            metrics.extras["pipeline_mode"] = "surgery" if is_surgery else "reconstruct"
            metrics._raw_html = final_html
            all_metrics.append(metrics)
            all_verdicts.append(_verdict_final(metrics, thresholds, phase2_slot_count))
        except Exception as e:
            logger.error(f"Final output diagnostic failed: {e}")
            m = PhaseMetrics(
                phase_name="Final Output",
                html_size=0, slot_count=0, slot_names=frozenset(),
                section_count=0, image_count=0, css_chars=0,
            )
            m._raw_html = ""
            all_metrics.append(m)
            all_verdicts.append(PhaseVerdict(
                phase_name="Final Output",
                passed=False,
                issues=[f"Diagnostic error: {e}"],
            ))

    overall_passed = all(v.passed for v in all_verdicts) if all_verdicts else False

    return PhaseDiagnosticReport(
        phases=all_metrics,
        verdicts=all_verdicts,
        overall_passed=overall_passed,
        source_token_count=len(source_tokens),
    )


def print_diagnostic_report(
    report: PhaseDiagnosticReport, verbose: bool = False
) -> None:
    """Print terminal-friendly diagnostic report."""
    print(report.format(verbose=verbose))
