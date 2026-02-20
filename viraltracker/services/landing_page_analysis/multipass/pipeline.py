"""Multi-pass pipeline orchestrator.

Orchestrates 5 phases of HTML generation with invariant checks,
adaptive rate control, and phase-local degradation.
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from viraltracker.core.config import Config
from viraltracker.core.observability import get_logfire
from viraltracker.services.gemini_service import GeminiService, RateLimitError

from .cropper import (
    NormalizedBox,
    boxes_from_char_ratios,
    crop_section,
    normalize_bounding_boxes,
)
from .invariants import (
    PipelineInvariants,
    capture_pipeline_invariants,
    check_global_invariants,
    check_section_invariant,
)
from .patch_applier import PatchApplier
from .popup_filter import PopupFilter
from .prompts import (
    PROMPT_VERSIONS,
    build_phase_0_prompt,
    build_phase_1_prompt,
    build_phase_2_prompt,
    build_phase_3_prompt,
    build_phase_4_prompt,
)
from .segmenter import SegmenterSection, segment_markdown

logger = logging.getLogger(__name__)

# Models (from Config constants)
_VISION_MODEL = Config.GEMINI_IMAGE_MODEL
_TEXT_MODEL = Config.GEMINI_TEXT_MODEL

PHASE_MODELS = {
    0: _VISION_MODEL,
    1: _VISION_MODEL,
    2: _TEXT_MODEL,
    3: _VISION_MODEL,
    4: _VISION_MODEL,
}

# Hard limits
MAX_WALL_CLOCK = 120  # seconds
MAX_SECTIONS = 8
MARKDOWN_BUDGET = 30_000

# Default design system (Phase 0 fallback)
DEFAULT_DESIGN_SYSTEM = {
    "colors": {
        "primary": "#333333",
        "secondary": "#666666",
        "accent": "#0066cc",
        "background": "#ffffff",
        "surface": "#f5f5f5",
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "border": "#e0e0e0",
        "cta": "#0066cc",
    },
    "typography": {
        "heading_font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        "body_font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        "h1_size": "3rem",
        "h2_size": "2rem",
        "h3_size": "1.5rem",
        "body_size": "1rem",
        "line_height": "1.7",
    },
    "spacing": {
        "section_padding_v": "70px",
        "section_padding_h": "30px",
        "element_gap": "20px",
        "group_gap": "40px",
    },
    "overlays": [],
}


class PipelineRateLimiter:
    """Single rate controller for all pipeline API calls.

    Manages both concurrency (max in-flight) and pacing (min delay between calls).
    """

    def __init__(
        self,
        initial_rpm: int = 15,
        max_rpm: int = 30,
        min_rpm: int = 5,
        max_concurrent: int = 3,
    ):
        self._current_rpm = initial_rpm
        self._max_rpm = max_rpm
        self._min_rpm = min_rpm
        self._sem = asyncio.Semaphore(max_concurrent)
        self._last_call_time = 0.0
        self._lock = asyncio.Lock()
        self._call_count = 0
        self._consecutive_successes = 0

    async def acquire(self):
        """Acquire concurrency slot, then pace before dispatch."""
        await self._sem.acquire()
        async with self._lock:
            now = asyncio.get_event_loop().time()
            min_delay = 60.0 / self._current_rpm
            elapsed = now - self._last_call_time
            if elapsed < min_delay:
                await asyncio.sleep(min_delay - elapsed)
            self._last_call_time = asyncio.get_event_loop().time()
            self._call_count += 1

    def release(self, success: bool = True, rate_limited: bool = False):
        """Release concurrency slot and update adaptive pacing."""
        self._sem.release()
        if rate_limited:
            self._consecutive_successes = 0
            self._current_rpm = max(self._current_rpm - 5, self._min_rpm)
            logger.info(f"Rate limiter: backed off to {self._current_rpm} RPM")
        elif success:
            self._consecutive_successes += 1
            if self._consecutive_successes >= 5:
                self._current_rpm = min(self._current_rpm + 5, self._max_rpm)
                self._consecutive_successes = 0
                logger.debug(f"Rate limiter: ramped up to {self._current_rpm} RPM")

    @property
    def call_count(self) -> int:
        return self._call_count


@dataclass
class PipelineResult:
    """Result from the multipass pipeline."""
    html: str
    phase_reached: int = 4
    api_calls: int = 0
    wall_clock_seconds: float = 0.0
    sections_refined: int = 0
    sections_rejected: int = 0
    patches_applied: int = 0
    overlays_removed: int = 0


def compute_cache_key(
    phase: int,
    screenshot_b64: str,
    page_markdown: str,
    model: str,
    prompt_version: str,
    section_id: Optional[str] = None,
    section_bbox: Optional[Tuple[float, float]] = None,
    section_html_hash: Optional[str] = None,
) -> str:
    """Deterministic, collision-resistant cache key."""
    h = hashlib.sha256()
    h.update(f"phase={phase}".encode())
    h.update(f"model={model}".encode())
    h.update(f"prompt_v={prompt_version}".encode())
    h.update(hashlib.sha256(screenshot_b64.encode()).digest())
    h.update(hashlib.sha256(page_markdown.encode()).digest())
    if section_id is not None:
        h.update(f"section={section_id}".encode())
    if section_bbox is not None:
        h.update(f"bbox={section_bbox[0]:.4f},{section_bbox[1]:.4f}".encode())
    if section_html_hash is not None:
        h.update(f"html={section_html_hash}".encode())
    return h.hexdigest()[:32]


def _truncate_markdown(markdown: str, max_chars: int = MARKDOWN_BUDGET) -> str:
    """Truncate markdown at a heading boundary."""
    if len(markdown) <= max_chars:
        return markdown
    search_region = markdown[:max_chars]
    for pattern in (r'\n## ', r'\n### ', r'\n# '):
        matches = list(re.finditer(pattern, search_region))
        if matches:
            cut_point = matches[-1].start()
            if cut_point > max_chars // 2:
                return markdown[:cut_point] + "\n\n[... content truncated ...]"
    last_break = search_region.rfind('\n\n')
    if last_break > max_chars // 2:
        return markdown[:last_break] + "\n\n[... content truncated ...]"
    return markdown[:max_chars] + "\n\n[... content truncated ...]"


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from model output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```html"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_json_response(text: str) -> Any:
    """Parse JSON from model response, stripping code fences."""
    return json.loads(_strip_code_fences(text))


def _ensure_minimum_slots(html: str) -> str:
    """Deterministic slotizer: add data-slot attributes if < 3 present.

    Uses the canonical slot naming convention:
    - First <h1>: headline
    - First <h2>: subheadline
    - Subsequent headings: heading-1, heading-2, ...
    - Paragraphs: body-1, body-2, ...
    - Buttons/links with CTA-like text: cta-1, cta-2, ...
    """
    from .invariants import _extract_slots
    existing = _extract_slots(html)
    if len(existing) >= 3:
        return html

    logger.info(f"Slotizer: only {len(existing)} slots, adding deterministic slots")

    heading_counter = 0
    body_counter = 0
    cta_counter = 0
    found_h1 = False
    found_h2 = False

    def _add_slot(match: re.Match) -> str:
        nonlocal heading_counter, body_counter, cta_counter, found_h1, found_h2
        tag = match.group(1)
        attrs = match.group(2) or ""
        rest = match.group(3)

        if "data-slot=" in attrs:
            return match.group(0)

        slot_name = None
        if tag == "h1" and not found_h1:
            slot_name = "headline"
            found_h1 = True
        elif tag == "h2" and not found_h2:
            slot_name = "subheadline"
            found_h2 = True
        elif tag in ("h1", "h2", "h3", "h4"):
            heading_counter += 1
            slot_name = f"heading-{heading_counter}"
        elif tag == "p":
            body_counter += 1
            slot_name = f"body-{body_counter}"
        elif tag in ("a", "button"):
            cta_counter += 1
            slot_name = f"cta-{cta_counter}"

        if slot_name:
            return f'<{tag}{attrs} data-slot="{slot_name}"{rest}'
        return match.group(0)

    # Match opening tags for slottable elements
    pattern = re.compile(
        r'<(h[1-4]|p|a|button)((?:\s+[^>]*)?)(\s*/?)>',
        re.IGNORECASE,
    )
    result = pattern.sub(_add_slot, html)
    return result


def _reconcile_sections(
    segmenter_sections: List[SegmenterSection],
    phase1_sections: List[Dict],
    skeleton_html: str,
) -> Tuple[Dict[str, NormalizedBox], str]:
    """Reconcile Phase 1 sections with segmenter sections.

    Returns:
        (section_map, rewritten_skeleton_html)
        section_map: Dict[str, NormalizedBox] keyed by sec_N IDs
        rewritten_skeleton_html: Skeleton with matching sec_N IDs
    """
    seg_count = len(segmenter_sections)
    p1_count = len(phase1_sections)

    # Build normalized boxes from Phase 1 output
    raw_boxes = [
        {
            "section_id": f"sec_{i}",
            "name": sec.get("name", "section"),
            "y_start_pct": sec.get("y_start_pct", 0),
            "y_end_pct": sec.get("y_end_pct", 0),
        }
        for i, sec in enumerate(phase1_sections)
    ]

    # If Phase 1 count differs by > 2, discard bounding boxes entirely
    if abs(p1_count - seg_count) > 2:
        logger.warning(
            f"Phase 1 section count ({p1_count}) differs from segmenter ({seg_count}) "
            f"by > 2, using char-ratio fallback"
        )
        return _char_ratio_fallback(segmenter_sections, skeleton_html)

    normalized = normalize_bounding_boxes(raw_boxes)
    if normalized is None:
        logger.warning("Bounding box normalization failed, using char-ratio fallback")
        return _char_ratio_fallback(segmenter_sections, skeleton_html)

    # Reconcile counts
    if p1_count == seg_count:
        # 1:1 mapping by position
        final_boxes = normalized[:seg_count]
    elif p1_count > seg_count:
        # Merge adjacent Phase 1 sections (smallest-pair-first) until counts match
        boxes_list = list(normalized)
        while len(boxes_list) > seg_count and len(boxes_list) > 1:
            min_combined = float("inf")
            min_idx = 0
            for i in range(len(boxes_list) - 1):
                height_i = boxes_list[i].y_end_pct - boxes_list[i].y_start_pct
                height_j = boxes_list[i + 1].y_end_pct - boxes_list[i + 1].y_start_pct
                combined = height_i + height_j
                if combined < min_combined:
                    min_combined = combined
                    min_idx = i
            merged = NormalizedBox(
                section_id=boxes_list[min_idx].section_id,
                name=boxes_list[min_idx].name,
                y_start_pct=boxes_list[min_idx].y_start_pct,
                y_end_pct=boxes_list[min_idx + 1].y_end_pct,
            )
            boxes_list = boxes_list[:min_idx] + [merged] + boxes_list[min_idx + 2:]
        final_boxes = boxes_list
    else:
        # Phase 1 has fewer: split largest segmenter section proportionally
        boxes_list = list(normalized)
        while len(boxes_list) < seg_count:
            # Find largest box
            max_height = 0
            max_idx = 0
            for i, box in enumerate(boxes_list):
                height = box.y_end_pct - box.y_start_pct
                if height > max_height:
                    max_height = height
                    max_idx = i
            # Split in half
            box = boxes_list[max_idx]
            mid = (box.y_start_pct + box.y_end_pct) / 2
            top_half = NormalizedBox(
                section_id=box.section_id,
                name=box.name,
                y_start_pct=box.y_start_pct,
                y_end_pct=mid,
            )
            bottom_half = NormalizedBox(
                section_id=f"sec_{len(boxes_list)}",
                name="section",
                y_start_pct=mid,
                y_end_pct=box.y_end_pct,
            )
            boxes_list = boxes_list[:max_idx] + [top_half, bottom_half] + boxes_list[max_idx + 1:]
        final_boxes = boxes_list

    # Renumber all sections deterministically as sec_0..sec_k
    section_map = {}
    for i, box in enumerate(final_boxes):
        new_id = f"sec_{i}"
        section_map[new_id] = NormalizedBox(
            section_id=new_id,
            name=box.name,
            y_start_pct=box.y_start_pct,
            y_end_pct=box.y_end_pct,
        )

    # Rewrite skeleton HTML to match reconciled IDs
    rewritten = _rewrite_skeleton(skeleton_html, len(final_boxes))

    return section_map, rewritten


def _char_ratio_fallback(
    segmenter_sections: List[SegmenterSection],
    skeleton_html: str,
) -> Tuple[Dict[str, NormalizedBox], str]:
    """Build section_map from char ratios and rewrite skeleton."""
    boxes = boxes_from_char_ratios(segmenter_sections)
    section_map = {box.section_id: box for box in boxes}
    rewritten = _rewrite_skeleton(skeleton_html, len(boxes))
    return section_map, rewritten


def _rewrite_skeleton(skeleton_html: str, section_count: int) -> str:
    """Rewrite skeleton HTML to have exactly sec_0..sec_{n-1} IDs and placeholders."""
    # Remove all existing section markers and placeholders
    html = skeleton_html

    # Replace any data-section="..." with sequential IDs
    existing_sections = re.findall(r'data-section="([^"]*)"', html)

    for i, old_id in enumerate(existing_sections):
        if i < section_count:
            new_id = f"sec_{i}"
            html = html.replace(f'data-section="{old_id}"', f'data-section="{new_id}"', 1)
            # Also replace placeholder patterns
            html = html.replace(f'{{{{{old_id}}}}}', f'{{{{{new_id}}}}}')

    # Replace any remaining {{section-*}} or {{sec_*}} patterns
    html = re.sub(
        r'\{\{(?:section-?\d+|sec_\d+)\}\}',
        lambda m: m.group(0),  # Keep as-is for now
        html,
    )

    return html


def _build_fallback_skeleton(sections: List[SegmenterSection]) -> str:
    """Build a basic skeleton HTML from segmenter sections."""
    parts = [
        '<style>',
        '  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, '
        "'Segoe UI', Roboto, sans-serif; }",
        '  .section { padding: 70px 30px; }',
        '  .container { max-width: 1200px; margin: 0 auto; }',
        '</style>',
    ]

    for sec in sections:
        parts.append(
            f'<section data-section="{sec.section_id}" class="section">'
            f'<div class="container">{{{{{sec.section_id}}}}}</div>'
            f'</section>'
        )

    return '\n'.join(parts)


class MultiPassPipeline:
    """Orchestrates the 5-phase multipass HTML generation pipeline."""

    def __init__(
        self,
        gemini_service: GeminiService,
        progress_callback: Optional[Callable] = None,
    ):
        self._gemini = gemini_service
        self._progress = progress_callback
        self._limiter = PipelineRateLimiter()
        self._start_time = 0.0
        self._cache: Dict[str, str] = {}
        # Lazily resolve logfire at runtime, not import time,
        # to ensure it's configured before we use it
        self._lf = get_logfire()

    def _report_progress(self, phase: int, message: str):
        """Report progress via callback if available."""
        if self._progress:
            try:
                self._progress(phase, message)
            except Exception:
                pass

    def _time_remaining(self) -> float:
        """Seconds remaining before wall-clock timeout."""
        return MAX_WALL_CLOCK - (time.time() - self._start_time)

    def _budget_exceeded(self, max_calls: int) -> bool:
        """Check if API call budget or wall clock is exceeded."""
        if self._limiter.call_count >= max_calls:
            logger.warning(f"API call budget exhausted ({max_calls})")
            return True
        if self._time_remaining() <= 0:
            logger.warning("Wall clock timeout exceeded")
            return True
        return False

    async def generate(
        self,
        screenshot_b64: str,
        page_markdown: str,
        page_url: Optional[str] = None,
        element_detection: Optional[Dict] = None,
    ) -> str:
        """Run the full 5-phase multipass pipeline.

        Args:
            screenshot_b64: Base64-encoded full-page screenshot.
            page_markdown: Full page markdown text.
            page_url: Optional page URL for image resolution.
            element_detection: Optional element detection for section hints.

        Returns:
            Complete HTML string (raw, no post-processing).
        """
        self._start_time = time.time()

        # Segment markdown
        sections = segment_markdown(page_markdown, element_detection)
        section_count = len(sections)

        with self._lf.span(
            "multipass_pipeline",
            page_url=page_url or "unknown",
            section_count=section_count,
        ):
            # Compute API call budget
            phase_budgets = {
                0: 2,
                1: 2,
                2: 2,
                3: section_count + 2,
                4: 2,
            }
            max_api_calls = sum(phase_budgets.values())
            self._lf.info(
                "Pipeline started: {section_count} sections, budget={max_api_calls}",
                section_count=section_count,
                max_api_calls=max_api_calls,
            )

            # Decode screenshot for cropping
            screenshot_bytes = base64.b64decode(screenshot_b64)

            # Truncate markdown for prompts
            truncated_md = _truncate_markdown(page_markdown)

            # -----------------------------------------------------------
            # Phase 0: Design System Extraction
            # -----------------------------------------------------------
            self._report_progress(0, "Extracting design system...")
            design_system = await self._run_phase_0(screenshot_b64, truncated_md)
            if self._budget_exceeded(max_api_calls):
                self._lf.warning("Budget exceeded after Phase 0, returning fallback skeleton")
                return _build_fallback_skeleton(sections)

            # -----------------------------------------------------------
            # Phase 1: Layout Skeleton + Bounding Boxes
            # -----------------------------------------------------------
            self._report_progress(1, "Building layout skeleton...")
            skeleton_html, section_map = await self._run_phase_1(
                screenshot_b64, design_system, sections
            )
            if self._budget_exceeded(max_api_calls):
                self._lf.warning("Budget exceeded after Phase 1, returning skeleton")
                return skeleton_html

            # -----------------------------------------------------------
            # Phase 2: Content Injection + Slot Creation
            # -----------------------------------------------------------
            self._report_progress(2, "Injecting content and slots...")
            content_html = await self._run_phase_2(skeleton_html, truncated_md)

            # Ensure minimum slots
            content_html = _ensure_minimum_slots(content_html)

            # Capture invariant baselines
            baseline = capture_pipeline_invariants(content_html)

            if self._budget_exceeded(max_api_calls):
                self._lf.warning("Budget exceeded after Phase 2, returning content HTML")
                return content_html

            # -----------------------------------------------------------
            # Phase 3: Per-Section Visual Refinement
            # -----------------------------------------------------------
            self._report_progress(3, "Refining sections visually...")
            refined_html, stats = await self._run_phase_3(
                content_html,
                screenshot_bytes,
                screenshot_b64,
                section_map,
                sections,
                design_system,
                baseline,
                page_url,
                page_markdown,
            )

            if self._budget_exceeded(max_api_calls):
                self._lf.warning("Budget exceeded after Phase 3, returning refined HTML")
                return refined_html

            # -----------------------------------------------------------
            # Phase 4: Targeted Patch Pass
            # -----------------------------------------------------------
            self._report_progress(4, "Applying visual patches...")
            patched_html = await self._run_phase_4(
                refined_html,
                screenshot_b64,
                section_map,
                baseline,
            )

            # -----------------------------------------------------------
            # Popup Filter
            # -----------------------------------------------------------
            popup_filter = PopupFilter()
            final_html = popup_filter.filter(
                patched_html,
                detected_overlays=design_system.get("overlays", []),
            )

            elapsed = time.time() - self._start_time
            self._lf.info(
                "MultiPass pipeline complete: phases=0-4, "
                "api_calls={api_calls}, wall_clock={elapsed:.1f}s, "
                "output_chars={output_chars}",
                api_calls=self._limiter.call_count,
                elapsed=elapsed,
                output_chars=len(final_html),
            )
            logger.info(
                f"MultiPass pipeline complete: "
                f"phases=0-4, api_calls={self._limiter.call_count}, "
                f"wall_clock={elapsed:.1f}s"
            )
            self._report_progress(5, "Complete!")

            return final_html

    # -------------------------------------------------------------------
    # Phase implementations
    # -------------------------------------------------------------------

    async def _run_phase_0(
        self,
        screenshot_b64: str,
        markdown_preview: str,
    ) -> Dict:
        """Phase 0: Design System Extraction."""
        prompt = build_phase_0_prompt(markdown_preview)

        with self._lf.span("multipass_phase_0", phase="design_system_extraction"):
            try:
                response = await self._call_gemini_vision(
                    PHASE_MODELS[0], screenshot_b64, prompt
                )
                design_system = _parse_json_response(response)
                colors_found = len(design_system.get("colors", {}))
                overlays_found = len(design_system.get("overlays", []))
                self._lf.info(
                    "Phase 0 OK: {colors_found} colors, {overlays_found} overlays detected",
                    colors_found=colors_found,
                    overlays_found=overlays_found,
                )
                return design_system
            except RateLimitError:
                self._lf.warning("Phase 0: rate limited, retrying with 3s backoff")
                try:
                    await asyncio.sleep(3)
                    response = await self._call_gemini_vision(
                        PHASE_MODELS[0], screenshot_b64, prompt
                    )
                    return _parse_json_response(response)
                except Exception as e:
                    self._lf.warning("Phase 0 retry failed: {error}, using defaults", error=str(e))
                    return dict(DEFAULT_DESIGN_SYSTEM)
            except Exception as e:
                self._lf.warning("Phase 0 failed: {error}, using defaults", error=str(e))
                return dict(DEFAULT_DESIGN_SYSTEM)

    async def _run_phase_1(
        self,
        screenshot_b64: str,
        design_system: Dict,
        sections: List[SegmenterSection],
    ) -> Tuple[str, Dict[str, NormalizedBox]]:
        """Phase 1: Layout Skeleton + Bounding Boxes.

        Returns:
            (skeleton_html, section_map)
        """
        section_names = [s.name for s in sections]
        prompt = build_phase_1_prompt(
            json.dumps(design_system, indent=2),
            section_names,
            len(sections),
        )

        with self._lf.span(
            "multipass_phase_1",
            phase="layout_skeleton",
            segmenter_section_count=len(sections),
        ):
            try:
                response = await self._call_gemini_vision(
                    PHASE_MODELS[1], screenshot_b64, prompt
                )
                result = _parse_json_response(response)

                phase1_sections = result.get("sections", [])
                raw_skeleton = result.get("skeleton_html", "")

                if not raw_skeleton:
                    raise ValueError("No skeleton_html in Phase 1 response")

                raw_skeleton = _strip_code_fences(raw_skeleton)

                section_map, rewritten_skeleton = _reconcile_sections(
                    sections, phase1_sections, raw_skeleton
                )

                self._lf.info(
                    "Phase 1 OK: {section_count} sections, "
                    "skeleton_chars={skeleton_chars}, "
                    "model_sections={model_sections}, reconciled={reconciled}",
                    section_count=len(section_map),
                    skeleton_chars=len(rewritten_skeleton),
                    model_sections=len(phase1_sections),
                    reconciled=len(phase1_sections) != len(sections),
                )
                return rewritten_skeleton, section_map

            except RateLimitError:
                self._lf.warning("Phase 1: rate limited, retrying with 3s backoff")
                try:
                    await asyncio.sleep(3)
                    response = await self._call_gemini_vision(
                        PHASE_MODELS[1], screenshot_b64, prompt
                    )
                    result = _parse_json_response(response)
                    phase1_sections = result.get("sections", [])
                    raw_skeleton = _strip_code_fences(result.get("skeleton_html", ""))
                    if raw_skeleton:
                        section_map, rewritten = _reconcile_sections(
                            sections, phase1_sections, raw_skeleton
                        )
                        return rewritten, section_map
                except Exception as e:
                    logger.warning(f"Phase 1 retry failed: {e}")

                self._lf.warning("Phase 1 using fallback skeleton (char-ratio)")
                return self._phase_1_fallback(sections)
            except Exception as e:
                self._lf.warning("Phase 1 failed: {error}, using fallback", error=str(e))
                return self._phase_1_fallback(sections)

    def _phase_1_fallback(
        self, sections: List[SegmenterSection]
    ) -> Tuple[str, Dict[str, NormalizedBox]]:
        """Fallback: build skeleton from segmenter sections with char-ratio boxes."""
        skeleton = _build_fallback_skeleton(sections)
        boxes = boxes_from_char_ratios(sections)
        section_map = {box.section_id: box for box in boxes}
        return skeleton, section_map

    async def _run_phase_2(
        self,
        skeleton_html: str,
        page_markdown: str,
    ) -> str:
        """Phase 2: Content Injection + Slot Creation."""
        prompt = build_phase_2_prompt(skeleton_html, page_markdown)

        with self._lf.span("multipass_phase_2", phase="content_injection"):
            try:
                response = await self._call_gemini_text(PHASE_MODELS[2], prompt)
                html = _strip_code_fences(response)
                from .invariants import _extract_slots
                slot_count = len(_extract_slots(html))
                self._lf.info(
                    "Phase 2 OK: {output_chars} chars, {slot_count} slots",
                    output_chars=len(html),
                    slot_count=slot_count,
                )
                return html
            except RateLimitError:
                self._lf.warning("Phase 2: rate limited, retrying with 3s backoff")
                try:
                    await asyncio.sleep(3)
                    response = await self._call_gemini_text(PHASE_MODELS[2], prompt)
                    return _strip_code_fences(response)
                except Exception as e:
                    self._lf.warning("Phase 2 retry failed: {error}, using markdown fallback", error=str(e))
                    return self._phase_2_fallback(skeleton_html, page_markdown)
            except Exception as e:
                self._lf.warning("Phase 2 failed: {error}, using markdown fallback", error=str(e))
                return self._phase_2_fallback(skeleton_html, page_markdown)

    def _phase_2_fallback(self, skeleton_html: str, page_markdown: str) -> str:
        """Fallback: inject markdown as HTML into skeleton placeholders."""
        from markdown_it import MarkdownIt
        md = MarkdownIt().disable("html_block").disable("html_inline")

        html = skeleton_html
        # Find all {{sec_N}} placeholders and replace with markdown content
        placeholder_re = re.compile(r'\{\{(sec_\d+)\}\}')

        for match in placeholder_re.finditer(skeleton_html):
            placeholder = match.group(0)
            # Use the full markdown as fallback (no per-section split available)
            md_html = md.render(page_markdown)
            html = html.replace(placeholder, md_html, 1)
            break  # Only replace once for fallback

        return html

    async def _run_phase_3(
        self,
        content_html: str,
        screenshot_bytes: bytes,
        screenshot_b64: str,
        section_map: Dict[str, NormalizedBox],
        sections: List[SegmenterSection],
        design_system: Dict,
        baseline: PipelineInvariants,
        page_url: Optional[str],
        page_markdown: str,
    ) -> Tuple[str, Dict]:
        """Phase 3: Per-Section Visual Refinement.

        Returns:
            (refined_html, stats_dict)
        """
        with self._lf.span(
            "multipass_phase_3",
            phase="section_refinement",
            total_sections=len(section_map),
        ):
            # Extract per-section HTML from content_html
            from .invariants import _SectionParser
            parser = _SectionParser()
            parser.feed(content_html)
            section_htmls = parser.sections

            # Compact design system for per-section prompts
            compact_ds = json.dumps({
                "colors": design_system.get("colors", {}),
                "typography": design_system.get("typography", {}),
            })

            # Extract image URLs if available
            image_urls = None
            if page_url and page_markdown:
                try:
                    from ..mockup_service import MockupService
                    svc = MockupService()
                    image_urls = svc._extract_image_urls(page_markdown, page_url)
                except Exception as e:
                    logger.debug(f"Image URL extraction failed (non-fatal): {e}")

            # Build tasks for parallel execution
            tasks = []
            section_ids = sorted(section_map.keys(), key=lambda x: int(x.split("_")[1]))

            for sec_id in section_ids:
                if sec_id not in section_htmls:
                    self._lf.info("Phase 3: section {sec_id} not in parsed HTML, skipping", sec_id=sec_id)
                    continue

                box = section_map[sec_id]

                # Crop screenshot for this section
                try:
                    cropped_bytes = crop_section(screenshot_bytes, box)
                    cropped_b64 = base64.b64encode(cropped_bytes).decode('utf-8')
                except Exception as e:
                    self._lf.warning("Phase 3: failed to crop {sec_id}: {error}", sec_id=sec_id, error=str(e))
                    continue

                section_html = (
                    f'<section data-section="{sec_id}">'
                    f'{section_htmls[sec_id]}'
                    f'</section>'
                )

                prompt = build_phase_3_prompt(
                    sec_id,
                    section_html,
                    compact_ds,
                    image_urls,
                )

                tasks.append({
                    "section_id": sec_id,
                    "cropped_b64": cropped_b64,
                    "prompt": prompt,
                    "original_html": section_html,
                })

            self._lf.info(
                "Phase 3: dispatching {task_count} section refinement calls",
                task_count=len(tasks),
            )

            # Execute all sections in parallel with rate limiting
            refined_sections = {}
            rejected = 0

            # Capture self._lf for use in nested function
            _lf = self._lf

            async def refine_section(task: Dict) -> Tuple[str, str]:
                """Refine a single section. Returns (section_id, refined_html)."""
                sec_id = task["section_id"]
                with _lf.span("multipass_phase_3_section", section_id=sec_id):
                    try:
                        response = await self._call_gemini_vision(
                            PHASE_MODELS[3], task["cropped_b64"], task["prompt"]
                        )
                        refined = _strip_code_fences(response)

                        # Per-section invariant check
                        report = check_section_invariant(refined, sec_id, baseline)
                        if not report.passed:
                            _lf.warning(
                                "Phase 3 section {sec_id} REJECTED: {issues}",
                                sec_id=sec_id,
                                issues=str(report.issues),
                            )
                            return sec_id, task["original_html"]

                        _lf.info(
                            "Phase 3 section {sec_id} refined OK ({chars} chars)",
                            sec_id=sec_id,
                            chars=len(refined),
                        )
                        return sec_id, refined
                    except Exception as e:
                        _lf.warning(
                            "Phase 3 section {sec_id} FAILED: {error}",
                            sec_id=sec_id,
                            error=str(e),
                        )
                        return sec_id, task["original_html"]

            # Gather all section refinements
            if tasks:
                results = await asyncio.gather(
                    *[refine_section(t) for t in tasks],
                    return_exceptions=True,
                )

                # Shared retry pool: 2 retries for any failed sections
                retry_pool = 2
                failed_tasks = []

                for result in results:
                    if isinstance(result, Exception):
                        logger.warning(f"Phase 3 task exception: {result}")
                        continue
                    sec_id, html = result
                    refined_sections[sec_id] = html
                    if html == next(
                        (t["original_html"] for t in tasks if t["section_id"] == sec_id),
                        None,
                    ):
                        failed_tasks.append(sec_id)

                # Retry failed sections from shared pool
                for sec_id in failed_tasks:
                    if retry_pool <= 0:
                        break
                    task = next((t for t in tasks if t["section_id"] == sec_id), None)
                    if task:
                        retry_pool -= 1
                        self._lf.info("Phase 3: retrying {sec_id} from shared pool", sec_id=sec_id)
                        sec_id_result, html = await refine_section(task)
                        if html != task["original_html"]:
                            refined_sections[sec_id_result] = html
                            rejected -= 1  # Un-reject

            # Reassemble HTML
            assembled = content_html
            for sec_id, refined in refined_sections.items():
                # Replace the entire section in the assembled HTML
                section_re = re.compile(
                    rf'<section\s+data-section="{re.escape(sec_id)}"[^>]*>.*?</section>',
                    re.DOTALL,
                )
                assembled = section_re.sub(refined, assembled, count=1)

            stats = {
                "sections_refined": len(refined_sections),
                "sections_rejected": rejected,
            }
            self._lf.info(
                "Phase 3 complete: {refined} refined, {rejected} rejected, {failed} failed",
                refined=stats["sections_refined"],
                rejected=stats["sections_rejected"],
                failed=len(failed_tasks) if tasks else 0,
            )
            return assembled, stats

    async def _run_phase_4(
        self,
        assembled_html: str,
        screenshot_b64: str,
        section_map: Dict[str, NormalizedBox],
        baseline: PipelineInvariants,
    ) -> str:
        """Phase 4: Targeted Patch Pass."""
        section_ids = sorted(section_map.keys(), key=lambda x: int(x.split("_")[1]))
        prompt = build_phase_4_prompt(assembled_html, section_ids)

        with self._lf.span("multipass_phase_4", phase="patch_pass"):
            try:
                response = await self._call_gemini_vision(
                    PHASE_MODELS[4], screenshot_b64, prompt
                )
                patches = _parse_json_response(response)

                if not isinstance(patches, list):
                    self._lf.warning("Phase 4: response is not a list, skipping patches")
                    return assembled_html

                # Cap at 15 patches
                patches = patches[:15]
                self._lf.info("Phase 4: applying {patch_count} patches", patch_count=len(patches))

                # Apply patches
                applier = PatchApplier()
                patched = applier.apply_patches(assembled_html, patches)

                # Global invariant check
                report = check_global_invariants(patched, baseline)
                if not report.passed:
                    self._lf.warning(
                        "Phase 4 global invariant FAILED, reverting all patches: {issues}",
                        issues=str(report.issues),
                    )
                    return assembled_html

                self._lf.info("Phase 4 OK: {patch_count} patches applied", patch_count=len(patches))
                return patched

            except RateLimitError:
                self._lf.warning("Phase 4: rate limited, retrying with 3s backoff")
                try:
                    await asyncio.sleep(3)
                    response = await self._call_gemini_vision(
                        PHASE_MODELS[4], screenshot_b64, prompt
                    )
                    patches = _parse_json_response(response)
                    if isinstance(patches, list):
                        patches = patches[:15]
                        applier = PatchApplier()
                        patched = applier.apply_patches(assembled_html, patches)
                        report = check_global_invariants(patched, baseline)
                        if report.passed:
                            return patched
                    return assembled_html
                except Exception as e:
                    self._lf.warning("Phase 4 retry failed: {error}, skipping patches", error=str(e))
                    return assembled_html
            except Exception as e:
                self._lf.warning("Phase 4 failed: {error}, skipping patches", error=str(e))
                return assembled_html

    # -------------------------------------------------------------------
    # Gemini call helpers
    # -------------------------------------------------------------------

    async def _call_gemini_vision(
        self, model: str, image_b64: str, prompt: str
    ) -> str:
        """Call Gemini vision API with rate limiting."""
        await self._limiter.acquire()
        with self._lf.span(
            "multipass_gemini_call",
            call_type="vision",
            model=model,
            call_number=self._limiter.call_count,
        ):
            try:
                result = await self._gemini.analyze_image_async(
                    image_b64, prompt,
                    model=model,
                    skip_internal_rate_limit=True,
                )
                self._limiter.release(success=True)
                self._lf.info(
                    "Gemini vision call #{call_number} OK: {response_chars} chars",
                    call_number=self._limiter.call_count,
                    response_chars=len(result),
                )
                return result
            except RateLimitError:
                self._limiter.release(rate_limited=True)
                self._lf.warning(
                    "Gemini vision call #{call_number} RATE LIMITED (RPM now {rpm})",
                    call_number=self._limiter.call_count,
                    rpm=self._limiter._current_rpm,
                )
                raise
            except Exception as e:
                self._limiter.release(success=False)
                self._lf.error(
                    "Gemini vision call #{call_number} FAILED: {error}",
                    call_number=self._limiter.call_count,
                    error=str(e),
                )
                raise

    async def _call_gemini_text(self, model: str, prompt: str) -> str:
        """Call Gemini text API with rate limiting."""
        await self._limiter.acquire()
        with self._lf.span(
            "multipass_gemini_call",
            call_type="text",
            model=model,
            call_number=self._limiter.call_count,
        ):
            try:
                result = await self._gemini.analyze_text_async(
                    "", prompt,
                    model=model,
                    skip_internal_rate_limit=True,
                )
                self._limiter.release(success=True)
                self._lf.info(
                    "Gemini text call #{call_number} OK: {response_chars} chars",
                    call_number=self._limiter.call_count,
                    response_chars=len(result),
                )
                return result
            except RateLimitError:
                self._limiter.release(rate_limited=True)
                self._lf.warning(
                    "Gemini text call #{call_number} RATE LIMITED (RPM now {rpm})",
                    call_number=self._limiter.call_count,
                    rpm=self._limiter._current_rpm,
                )
                raise
            except Exception as e:
                self._limiter.release(success=False)
                self._lf.error(
                    "Gemini text call #{call_number} FAILED: {error}",
                    call_number=self._limiter.call_count,
                    error=str(e),
                )
                raise
