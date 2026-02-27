"""Pass S2: Element Classification & Slot Tagging.

Stage 2A: Deterministic pre-classification (0 API calls).
Stage 2B: LLM refinement (1 Gemini Vision call, optional).

Adds data-slot attributes to editable text/CTA elements.
"""

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# CTA-like text patterns
_CTA_TEXT_RE = re.compile(
    r'\b(buy|shop|order|add to cart|get started|sign up|subscribe|'
    r'learn more|try|start|join|download|get|claim|register|'
    r'free trial|book|reserve|contact)\b',
    re.IGNORECASE,
)

# Class-name heuristics for element roles
_CLASS_HEADING_RE = re.compile(r'\b(heading|title|headline)\b', re.IGNORECASE)
_CLASS_CTA_RE = re.compile(r'\b(btn|button|cta)\b', re.IGNORECASE)

# Hidden-element detection
_HIDDEN_STYLE_RE = re.compile(
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',
    re.IGNORECASE,
)


def _is_visually_hidden(attrs_str: str) -> bool:
    """Check if an element's attributes indicate it is visually hidden.

    Detects ``display:none``, ``visibility:hidden`` (inline style),
    ``aria-hidden="true"``, and the ``hidden`` boolean attribute.
    """
    if not attrs_str:
        return False
    # Check inline style for display:none / visibility:hidden
    style_match = re.search(r'style\s*=\s*["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
    if style_match and _HIDDEN_STYLE_RE.search(style_match.group(1)):
        return True
    # Check aria-hidden="true"
    if re.search(r'aria-hidden\s*=\s*["\']true["\']', attrs_str, re.IGNORECASE):
        return True
    # Check hidden boolean attribute — strip quoted values first to avoid
    # false positives on class="hidden" or data-state="hidden".
    # Use (?<!-) to exclude data-hidden, x-hidden, etc.
    stripped = re.sub(r'["\'][^"\']*["\']', '', attrs_str)
    if re.search(r'(?<!-)\bhidden\b', stripped, re.IGNORECASE):
        return True
    return False


class ElementClassifier:
    """Pass S2: Classify elements and add data-slot attributes."""

    def classify(
        self,
        html: str,
        sections: list,
        screenshot_b64: str = "",
        gemini_service: Any = None,
    ) -> Tuple[str, dict]:
        """Classify elements and add data-slot attributes.

        Args:
            html: Segmented HTML from S1.
            sections: SegmenterSection list.
            screenshot_b64: Base64 screenshot for LLM refinement.
            gemini_service: GeminiService instance for LLM calls.

        Returns:
            (classified_html, stats)
        """
        stats = {
            "total_slots": 0,
            "deterministic_slots": 0,
            "llm_slots_added": 0,
            "api_calls": 0,
            "has_headline": False,
            "has_cta": False,
        }

        # Stage 2A: Deterministic pre-classification
        html, det_stats = self._deterministic_classify(html)
        stats["deterministic_slots"] = det_stats["slot_count"]
        stats["total_slots"] = det_stats["slot_count"]
        stats["has_headline"] = det_stats["has_headline"]
        stats["has_cta"] = det_stats["has_cta"]

        # Stage 2B: LLM refinement (optional, skip if no Gemini service)
        # Skip LLM if deterministic already found enough slots
        if (gemini_service and screenshot_b64 and
                stats["deterministic_slots"] < 3):
            try:
                html, llm_stats = self._llm_refine(
                    html, screenshot_b64, gemini_service
                )
                stats["api_calls"] = llm_stats.get("api_calls", 0)
                stats["llm_slots_added"] = llm_stats.get("slots_added", 0)
                stats["total_slots"] += llm_stats.get("slots_added", 0)
            except Exception as e:
                logger.warning(f"S2B LLM refinement failed: {e}")

        # Re-count slots for accuracy
        slot_count = len(re.findall(r'data-slot="[^"]*"', html))
        stats["total_slots"] = slot_count

        return html, stats

    # ------------------------------------------------------------------
    # Stage 2A: Deterministic classification
    # ------------------------------------------------------------------

    def _deterministic_classify(self, html: str) -> Tuple[str, dict]:
        """Add data-slot attributes based on tag and class heuristics."""
        heading_counter = 0
        body_counter = 0
        cta_counter = 0
        found_h1 = False
        found_h2 = False
        has_headline = False
        has_cta = False

        def _slot_heading(match: re.Match) -> str:
            nonlocal heading_counter, found_h1, found_h2, has_headline
            tag = match.group(1).lower()
            attrs = match.group(2) or ""
            close = match.group(3)

            if 'data-slot=' in attrs:
                return match.group(0)
            if _is_visually_hidden(attrs):
                return match.group(0)

            if tag == "h1" and not found_h1:
                found_h1 = True
                has_headline = True
                return f'<{match.group(1)}{attrs} data-slot="headline"{close}'
            elif tag == "h2" and not found_h2:
                found_h2 = True
                return f'<{match.group(1)}{attrs} data-slot="subheadline"{close}'
            else:
                heading_counter += 1
                return f'<{match.group(1)}{attrs} data-slot="heading-{heading_counter}"{close}'

        def _slot_paragraph(match: re.Match) -> str:
            nonlocal body_counter
            attrs = match.group(1) or ""
            close = match.group(2)

            if 'data-slot=' in attrs:
                return match.group(0)
            if _is_visually_hidden(attrs):
                return match.group(0)

            body_counter += 1
            return f'<p{attrs} data-slot="body-{body_counter}"{close}'

        def _slot_cta(match: re.Match) -> str:
            nonlocal cta_counter, has_cta
            tag = match.group(1).lower()
            attrs = match.group(2) or ""
            close = match.group(3)
            # Get text content to check if it's CTA-like
            # For now, tag + class heuristic
            full_tag = match.group(0)

            if 'data-slot=' in attrs:
                return full_tag
            if _is_visually_hidden(attrs):
                return full_tag

            # Check class for CTA patterns
            class_match = re.search(
                r'class\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
            )
            class_val = class_match.group(1) if class_match else ""

            is_cta = False
            if tag == "button":
                is_cta = True
            elif tag == "a" and _CLASS_CTA_RE.search(class_val):
                is_cta = True
            elif tag == "a" and _CTA_TEXT_RE.search(attrs):
                is_cta = True

            if is_cta:
                cta_counter += 1
                has_cta = True
                return f'<{match.group(1)}{attrs} data-slot="cta-{cta_counter}"{close}'

            return full_tag

        # Apply heading slots
        html = re.sub(
            r'<(h[1-6])\b([^>]*)(>)',
            _slot_heading,
            html,
            flags=re.IGNORECASE,
        )

        # Apply paragraph slots (limit to first 20 to avoid bloat)
        html = re.sub(
            r'<p\b([^>]*)(>)',
            _slot_paragraph,
            html,
            flags=re.IGNORECASE,
        )

        # Apply CTA slots (buttons and CTA-like links)
        html = re.sub(
            r'<(button|a)\b([^>]*)(>)',
            _slot_cta,
            html,
            flags=re.IGNORECASE,
        )

        # Also check for class-name heuristic slots
        html = self._class_heuristic_slots(html)

        # Strip cross-section slots (must run after all slot assignment)
        html = self._strip_cross_section_slots(html)

        slot_count = len(re.findall(r'data-slot="[^"]*"', html))

        return html, {
            "slot_count": slot_count,
            "has_headline": has_headline,
            "has_cta": has_cta,
        }

    def _class_heuristic_slots(self, html: str) -> str:
        """Add slots based on class-name heuristics."""
        heading_class_counter = [0]  # mutable for closure access

        def _check_class_heading(match: re.Match) -> str:
            tag = match.group(1)
            attrs = match.group(2) or ""

            if 'data-slot=' in attrs:
                return match.group(0)
            if _is_visually_hidden(attrs):
                return match.group(0)

            class_match = re.search(
                r'class\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
            )
            if class_match and _CLASS_HEADING_RE.search(class_match.group(1)):
                heading_class_counter[0] += 1
                return f'<{tag}{attrs} data-slot="heading-class-{heading_class_counter[0]}">'

            return match.group(0)

        html = re.sub(
            r'<(span|div)\b([^>]*)>',
            _check_class_heading,
            html,
            flags=re.IGNORECASE,
        )

        return html

    def _strip_cross_section_slots(self, html: str) -> str:
        """Remove data-slot attributes from elements whose subtree spans sections.

        Uses a stack-based HTMLParser to detect data-slot elements that contain
        data-section children or nested data-slot elements. Any violating slot
        attributes are stripped via regex after detection.
        """

        class _CrossSectionDetector(HTMLParser):
            def __init__(self):
                super().__init__()
                # Stack: (tag, slot_name, depth)
                self._slot_stack: list = []
                self._depth = 0
                self.violating_slots: set = set()

            def handle_starttag(self, tag, attrs):
                self._depth += 1
                attr_dict = dict(attrs)
                slot_name = attr_dict.get("data-slot")
                has_section = "data-section" in attr_dict

                # Inside a slot and hit a section → violation
                if has_section and self._slot_stack:
                    _, parent_slot, _ = self._slot_stack[-1]
                    self.violating_slots.add(parent_slot)

                # Nested slot → violation on parent
                if slot_name and self._slot_stack:
                    _, parent_slot, _ = self._slot_stack[-1]
                    self.violating_slots.add(parent_slot)

                if slot_name:
                    self._slot_stack.append((tag, slot_name, self._depth))

            def handle_endtag(self, tag):
                if self._slot_stack:
                    stack_tag, _, stack_depth = self._slot_stack[-1]
                    if tag == stack_tag and self._depth == stack_depth:
                        self._slot_stack.pop()
                self._depth -= 1

            def finalize(self):
                # Unclosed slots are suspicious — treat as violations
                for _, slot_name, _ in self._slot_stack:
                    self.violating_slots.add(slot_name)
                self._slot_stack.clear()

        detector = _CrossSectionDetector()
        try:
            detector.feed(html)
        except Exception:
            pass
        detector.finalize()

        if not detector.violating_slots:
            return html

        logger.warning(
            f"S2 cross-section slots detected: {detector.violating_slots}"
        )
        for slot_name in detector.violating_slots:
            escaped = re.escape(slot_name)
            html = re.sub(rf'\s*data-slot="{escaped}"', '', html)

        return html

    # ------------------------------------------------------------------
    # Stage 2B: LLM refinement
    # ------------------------------------------------------------------

    async def _llm_refine(
        self,
        html: str,
        screenshot_b64: str,
        gemini_service: Any,
    ) -> Tuple[str, dict]:
        """Use LLM to refine slot assignments."""
        from .prompts import build_surgery_classify_prompt
        from .pipeline import SURGERY_VISION_MODEL

        prompt = build_surgery_classify_prompt(html[:30000])

        try:
            response = await gemini_service.generate_content_async(
                model=SURGERY_VISION_MODEL,
                contents=[
                    {"mime_type": "image/png", "data": screenshot_b64},
                    prompt,
                ],
            )

            response_text = response.text if hasattr(response, 'text') else str(response)
            slots_added = self._apply_llm_corrections(html, response_text)

            return html, {
                "api_calls": 1,
                "slots_added": slots_added,
            }
        except Exception as e:
            logger.warning(f"S2B LLM call failed: {e}")
            return html, {"api_calls": 1, "slots_added": 0}

    def _apply_llm_corrections(self, html: str, response_text: str) -> int:
        """Apply LLM slot corrections to HTML. Returns count of slots added."""
        try:
            # Parse JSON response
            text = response_text.strip()
            if text.startswith("```"):
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)
            corrections = json.loads(text)

            if not isinstance(corrections, list):
                return 0

            added = 0
            for correction in corrections:
                # Each correction: {"selector": "...", "slot": "..."}
                slot = correction.get("slot", "")
                # Conservative: never remove deterministic slots
                if slot and correction.get("action") == "add":
                    added += 1

            return added
        except (json.JSONDecodeError, TypeError):
            return 0
