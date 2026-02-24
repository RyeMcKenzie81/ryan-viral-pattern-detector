"""Pass S2: Element Classification & Slot Tagging.

Stage 2A: Deterministic pre-classification (0 API calls).
Stage 2B: LLM refinement (1 Gemini Vision call, optional).

Adds data-slot attributes to editable text/CTA elements.
"""

import json
import logging
import re
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

        slot_count = len(re.findall(r'data-slot="[^"]*"', html))

        return html, {
            "slot_count": slot_count,
            "has_headline": has_headline,
            "has_cta": has_cta,
        }

    def _class_heuristic_slots(self, html: str) -> str:
        """Add slots based on class-name heuristics."""
        # Elements with heading/title classes that weren't h1-h6
        def _check_class_heading(match: re.Match) -> str:
            tag = match.group(1)
            attrs = match.group(2) or ""

            if 'data-slot=' in attrs:
                return match.group(0)

            class_match = re.search(
                r'class\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
            )
            if class_match and _CLASS_HEADING_RE.search(class_match.group(1)):
                return f'<{tag}{attrs} data-slot="heading-class">'

            return match.group(0)

        html = re.sub(
            r'<(span|div)\b([^>]*)>',
            _check_class_heading,
            html,
            flags=re.IGNORECASE,
        )

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
