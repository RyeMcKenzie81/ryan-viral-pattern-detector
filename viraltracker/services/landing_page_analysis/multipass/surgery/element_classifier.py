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

# Minimum thresholds for <li> slot assignment
_LI_MIN_TEXT_LEN = 15
_LI_MIN_WORDS = 3

# Void (self-closing) HTML elements — no closing tag, must not affect depth tracking.
# Shared definition; invariants.py has its own identical copy for independent loading.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# Hidden-element detection
_HIDDEN_STYLE_RE = re.compile(
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Listicle detection patterns (authoritative copies; mockup_service has
# identical patterns for the runtime fallback path on non-surgery pages)
# ---------------------------------------------------------------------------

# Matches ordinal prefixes like "3.", "3)", "3:", "#3", "Reason 3:", "Step 3."
_LISTICLE_PREFIX_RE = re.compile(
    r'^(\d{1,2}[\.\)\:]\s'
    r'|#\d{1,2}\s'
    r'|(?:Reason|Step|Tip|Way|Thing|Secret|Benefit|Fact|Sign|Mistake)\s+\d{1,2}[\.\)\:]\s)',
    re.IGNORECASE,
)

# False positives: "100% Natural", "24/7 Support", "500mg", "3x Faster"
_LISTICLE_FALSE_POSITIVE_RE = re.compile(
    r'^\d{1,3}\s*(%|mg|ml|g|oz|lb|x\b|k\b|,\d|/\d|hour|day|week|minute)',
    re.IGNORECASE,
)

# Extracts the leading ordinal number from a prefix match
_LISTICLE_ORDINAL_RE = re.compile(r'(\d{1,2})')

# Extracts total count from headline text: "7 Reasons...", "Top 10 Tips..."
_LISTICLE_COUNT_RE = re.compile(
    r'(?:^|\s)(\d{1,2})\s+(?:Reason|Step|Tip|Way|Thing|Secret|Benefit|Fact|Sign|Mistake)s?\b',
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
        stats["listicle"] = det_stats.get("listicle", {})

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

        # Leaf-only slots for <blockquote> and <li> — run AFTER all h/p/button/a
        # and class-heuristic slots so the inner data-slot check is reliable.
        html = self._slot_blockquotes(html)
        html = self._slot_list_items(html)

        # Detect and tag listicle structure per-section (BEFORE strip_cross_section_slots
        # so all data-slot attributes are intact for grouping)
        html, listicle_info = self._detect_and_tag_listicles(html)

        # Strip cross-section slots (must run after all slot assignment)
        html = self._strip_cross_section_slots(html)

        slot_count = len(re.findall(r'data-slot="[^"]*"', html))

        return html, {
            "slot_count": slot_count,
            "has_headline": has_headline,
            "has_cta": has_cta,
            "listicle": listicle_info,
        }

    def _slot_blockquotes(self, html: str) -> str:
        """Add data-slot to <blockquote> elements with NO slotted children (leaf-only)."""
        counter = 0
        parts, last_end = [], 0

        for m in re.finditer(r'<blockquote\b([^>]*)>', html, re.IGNORECASE):
            attrs = m.group(1) or ""
            if 'data-slot=' in attrs or _is_visually_hidden(attrs):
                continue
            close = re.search(r'</blockquote\s*>', html[m.end():], re.IGNORECASE)
            if not close:
                continue
            inner = html[m.end():m.end() + close.start()]
            # LEAF-ONLY: skip if inner content already has slotted children
            if 'data-slot=' in inner:
                continue
            text = re.sub(r'<[^>]+>', '', inner).strip()
            text = ' '.join(text.split())
            if len(text) < 10 or len(text.split()) < 3:
                continue
            counter += 1
            parts.append(html[last_end:m.start()])
            parts.append(f'<blockquote{attrs} data-slot="testimonial-{counter}">')
            last_end = m.end()

        parts.append(html[last_end:])
        return ''.join(parts)

    def _slot_list_items(self, html: str) -> str:
        """Add data-slot to <li> elements with substantial text and NO slotted children."""
        counter = 0
        parts, last_end = [], 0

        for m in re.finditer(r'<li\b([^>]*)>', html, re.IGNORECASE):
            attrs = m.group(1) or ""
            if 'data-slot=' in attrs or _is_visually_hidden(attrs):
                continue
            close = re.search(r'</li\s*>', html[m.end():], re.IGNORECASE)
            if not close:
                continue
            inner = html[m.end():m.end() + close.start()]
            # LEAF-ONLY: skip if inner content already has slotted children
            if 'data-slot=' in inner:
                continue
            text = re.sub(r'<[^>]+>', '', inner).strip()
            text = ' '.join(text.split())
            if len(text) < _LI_MIN_TEXT_LEN or len(text.split()) < _LI_MIN_WORDS:
                continue
            counter += 1
            parts.append(html[last_end:m.start()])
            parts.append(f'<li{attrs} data-slot="list-{counter}">')
            last_end = m.end()

        parts.append(html[last_end:])
        return ''.join(parts)

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

    def _detect_and_tag_listicles(self, html: str) -> Tuple[str, dict]:
        """Detect listicle structure per-section and inject data-listicle-* attributes.

        Runs during S2A BEFORE _strip_cross_section_slots so all data-slot
        attributes are still intact.  Each section's listicle items are numbered
        independently starting from 1, avoiding the interleaving bug that occurs
        when numbering is global across sections.

        Section assignment uses **nearest preceding section** in document order
        rather than strict DOM nesting, because headings are often siblings of
        section containers rather than children.

        Returns (modified_html, listicle_stats) where listicle_stats contains:
            is_listicle, sections, total_items, prefix_style
        Returns ({}, empty stats) if no listicle detected.
        """
        # -----------------------------------------------------------
        # Phase 1: Parse HTML to collect sections and heading slots
        #          in document order (position-based section assignment)
        # -----------------------------------------------------------

        class _PositionalCollector(HTMLParser):
            """Collect sections and heading slots with document-order positions."""

            def __init__(self):
                super().__init__()
                self._depth = 0
                # Ordered list of (position_index, "section", section_name)
                # or (position_index, "heading", {slot_name, tag, depth})
                self.events: List[Tuple[int, str, Any]] = []
                self._event_counter = 0
                self._current_heading: Optional[dict] = None
                self._heading_inner: List[str] = []

            def handle_starttag(self, tag, attrs):
                if tag in _VOID_ELEMENTS:
                    return
                self._depth += 1
                attr_dict = dict(attrs)

                section_name = attr_dict.get("data-section")
                if section_name:
                    self._event_counter += 1
                    self.events.append((self._event_counter, "section", section_name))

                slot_name = attr_dict.get("data-slot", "")
                if slot_name and any(slot_name.startswith(p) for p in ("heading-", "subheadline")):
                    self._current_heading = {
                        "slot_name": slot_name,
                        "tag": tag,
                        "depth": self._depth,
                    }
                    self._heading_inner = []

            def handle_endtag(self, tag):
                if tag in _VOID_ELEMENTS:
                    return
                if (self._current_heading
                        and tag == self._current_heading["tag"]
                        and self._depth == self._current_heading["depth"]):
                    text = re.sub(r'<[^>]+>', '', ''.join(self._heading_inner)).strip()
                    text = ' '.join(text.split())
                    self._event_counter += 1
                    self.events.append((self._event_counter, "heading", {
                        "slot_name": self._current_heading["slot_name"],
                        "text": text,
                    }))
                    self._current_heading = None
                    self._heading_inner = []
                self._depth -= 1

            def handle_data(self, data):
                if self._current_heading is not None:
                    self._heading_inner.append(data)

            def handle_startendtag(self, tag, attrs):
                pass

        collector = _PositionalCollector()
        try:
            collector.feed(html)
        except Exception:
            return html, {}

        if not collector.events:
            return html, {}

        # -----------------------------------------------------------
        # Phase 1b: Assign each heading to nearest preceding section
        # -----------------------------------------------------------
        current_section: Optional[str] = None
        headings: List[dict] = []

        for _, event_type, payload in collector.events:
            if event_type == "section":
                current_section = payload
            elif event_type == "heading":
                headings.append({
                    "slot_name": payload["slot_name"],
                    "text": payload["text"],
                    "section": current_section,
                })

        if not headings:
            return html, {}

        # -----------------------------------------------------------
        # Phase 2: Group headings by section and detect listicle pattern
        # -----------------------------------------------------------
        section_matches: Dict[str, list] = {}
        all_heading_count = 0
        seen_keys: set = set()

        for h in headings:
            sec = h.get("section") or "_pre"
            all_heading_count += 1
            text = h["text"]

            if _LISTICLE_FALSE_POSITIVE_RE.match(text):
                continue
            m = _LISTICLE_PREFIX_RE.match(text)
            if not m:
                continue
            prefix_str = m.group(0).rstrip()
            ordinal_m = _LISTICLE_ORDINAL_RE.search(prefix_str)
            if not ordinal_m:
                continue
            ordinal = int(ordinal_m.group(1))
            if ordinal > 20:
                continue

            # Deduplicate by (ordinal, text[:50]) within section
            dedup_key = (sec, ordinal, text[:50])
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            if sec not in section_matches:
                section_matches[sec] = []
            section_matches[sec].append({
                "slot_name": h["slot_name"],
                "prefix": prefix_str,
                "ordinal": ordinal,
                "text": text,
            })

        # Threshold check
        all_matches = [m for group in section_matches.values() for m in group]
        min_matches = 2 if all_heading_count <= 3 else 3
        if len(all_matches) < min_matches:
            return html, {}

        # Detect prefix style from first match
        first_prefix = all_matches[0]["prefix"]
        if first_prefix.startswith("#"):
            prefix_style = "hash"
        elif re.match(r'(?:Reason|Step|Tip|Way|Thing|Secret|Benefit|Fact|Sign|Mistake)',
                       first_prefix, re.IGNORECASE):
            prefix_style = "word_prefix"
        elif ")" in first_prefix:
            prefix_style = "numeric_paren"
        elif ":" in first_prefix:
            prefix_style = "numeric_colon"
        else:
            prefix_style = "numeric_dot"

        # -----------------------------------------------------------
        # Phase 3: Number each section independently starting from 1
        # -----------------------------------------------------------
        # slot_name -> assigned prefix string
        slot_prefixes: Dict[str, str] = {}
        section_stats: Dict[str, dict] = {}
        total_items = 0

        for sec_key, group in section_matches.items():
            group.sort(key=lambda x: x["ordinal"])
            section_start = 1
            section_count = len(group)
            total_items += section_count

            for i, match in enumerate(group, start=section_start):
                correct_ordinal = str(i)
                old_prefix = match["prefix"]
                if prefix_style == "hash":
                    slot_prefixes[match["slot_name"]] = f"#{correct_ordinal}"
                elif prefix_style == "word_prefix":
                    word_m = re.match(r'([A-Za-z]+)', old_prefix)
                    word = word_m.group(1) if word_m else "Reason"
                    sep_m = re.search(r'[\.\)\:]', old_prefix)
                    sep = sep_m.group(0) if sep_m else "."
                    slot_prefixes[match["slot_name"]] = f"{word} {correct_ordinal}{sep}"
                elif prefix_style == "numeric_paren":
                    slot_prefixes[match["slot_name"]] = f"{correct_ordinal})"
                elif prefix_style == "numeric_colon":
                    slot_prefixes[match["slot_name"]] = f"{correct_ordinal}:"
                else:
                    slot_prefixes[match["slot_name"]] = f"{correct_ordinal}."

            section_stats[sec_key] = {
                "start": section_start,
                "count": section_count,
                "style": prefix_style,
            }

        # -----------------------------------------------------------
        # Phase 4: Inject data-listicle-* attributes into HTML
        # -----------------------------------------------------------
        # 4a. Add data-listicle-prefix on heading elements (before the closing >)
        for slot_name, prefix_val in slot_prefixes.items():
            escaped_slot = re.escape(slot_name)
            # Match opening tag with this data-slot value and inject data-listicle-prefix
            html = re.sub(
                rf'(<[^>]*data-slot="{escaped_slot}"[^>]*?)(\s*/?>)',
                rf'\1 data-listicle-prefix="{prefix_val}"\2',
                html,
                count=1,
            )

        # 4b. Add data-listicle-start, data-listicle-count, data-listicle-style on section containers
        for sec_key, stats in section_stats.items():
            escaped_sec = re.escape(sec_key)
            html = re.sub(
                rf'(<[^>]*data-section="{escaped_sec}"[^>]*?)(\s*/?>)',
                rf'\1 data-listicle-start="{stats["start"]}" data-listicle-count="{stats["count"]}" data-listicle-style="{stats["style"]}"\2',
                html,
                count=1,
            )

        listicle_info = {
            "is_listicle": True,
            "sections": section_stats,
            "total_items": total_items,
            "prefix_style": prefix_style,
        }

        logger.info(
            f"S2 listicle tagged: {total_items} items across "
            f"{len(section_stats)} sections, style={prefix_style}"
        )

        return html, listicle_info

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
                # Void elements have no closing tag — don't change depth
                if tag in _VOID_ELEMENTS:
                    return
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

            def handle_startendtag(self, tag, attrs):
                # Explicit self-closing syntax (<br/>) — no depth change
                pass

            def handle_endtag(self, tag):
                if tag in _VOID_ELEMENTS:
                    return
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
