"""Pass S1: Section Segmentation (Deterministic).

Maps markdown sections to HTML DOM regions and adds
``data-section="sec_N"`` attributes. Uses a three-strategy cascade:

1. Heading anchor matching (highest confidence)
2. Visible text fuzzy matching (medium confidence)
3. Positional splitting (fallback)

Zero LLM calls.
"""

import logging
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Section-level container tags
_SECTION_CONTAINER_TAGS = frozenset([
    "section", "article", "header", "footer", "nav", "main", "aside",
])

# Tags that are direct children of <body> or <main> and act as section boundaries
_BLOCK_BOUNDARY_TAGS = frozenset([
    "section", "article", "header", "footer", "nav", "main", "aside",
    "div",
])

# Minimum word overlap for heading match
_HEADING_OVERLAP_THRESHOLD = 0.3

# Minimum text similarity for fuzzy matching
_TEXT_MATCH_THRESHOLD = 0.4


class SectionMapper:
    """Pass S1: Map markdown sections to HTML DOM regions."""

    def map_sections(
        self,
        html: str,
        sections: list,
    ) -> Tuple[str, dict]:
        """Add data-section attributes to HTML based on markdown sections.

        Args:
            html: Sanitized HTML from S0.
            sections: List of SegmenterSection from segmenter.

        Returns:
            (html_with_sections, stats)
        """
        if not sections:
            return html, {
                "sections_mapped": 0,
                "strategy_used": "none",
                "total_sections": 0,
            }

        total = len(sections)

        # Strategy 1: Heading anchor matching
        mapped, strategy = self._strategy_heading_match(html, sections)
        if mapped and len(mapped) >= total * 0.5:
            result_html = self._apply_section_attrs(html, mapped)
            return result_html, {
                "sections_mapped": len(mapped),
                "strategy_used": "heading_anchor",
                "total_sections": total,
                "match_details": {
                    sid: {"pos": pos, "tag": tag}
                    for sid, (pos, tag) in mapped.items()
                },
            }

        # Strategy 2: Visible text fuzzy matching
        mapped2, strategy2 = self._strategy_text_match(html, sections)
        # Merge: prefer heading matches, fill gaps with text matches
        merged = dict(mapped) if mapped else {}
        if mapped2:
            for sid, val in mapped2.items():
                if sid not in merged:
                    merged[sid] = val

        if merged and len(merged) >= total * 0.5:
            result_html = self._apply_section_attrs(html, merged)
            return result_html, {
                "sections_mapped": len(merged),
                "strategy_used": "heading+text",
                "total_sections": total,
            }

        # Strategy 3: Positional splitting
        mapped3 = self._strategy_positional(html, sections)
        result_html = self._apply_section_attrs(html, mapped3)
        return result_html, {
            "sections_mapped": len(mapped3),
            "strategy_used": "positional",
            "total_sections": total,
        }

    # ------------------------------------------------------------------
    # Strategy 1: Heading anchor matching
    # ------------------------------------------------------------------

    def _strategy_heading_match(
        self,
        html: str,
        sections: list,
    ) -> Tuple[Dict[str, Tuple[int, str]], str]:
        """Match sections by heading text in HTML.

        Returns:
            dict mapping section_id -> (tag_start_position, tag_name)
        """
        mapped: Dict[str, Tuple[int, str]] = {}

        # Extract headings from HTML with positions
        html_headings = self._find_headings(html)

        for section in sections:
            heading_text = self._extract_section_heading(section.markdown)
            if not heading_text:
                continue

            best_match = None
            best_score = 0.0

            for h_pos, h_tag, h_text, h_container_pos, h_container_tag in html_headings:
                score = _word_overlap(heading_text, h_text)

                # Substring containment for short headings
                if score < _HEADING_OVERLAP_THRESHOLD:
                    if (len(heading_text.split()) <= 2 and
                        heading_text.lower() in h_text.lower()):
                        score = _HEADING_OVERLAP_THRESHOLD + 0.1
                    elif (len(h_text.split()) <= 2 and
                          h_text.lower() in heading_text.lower()):
                        score = _HEADING_OVERLAP_THRESHOLD + 0.1

                if score >= _HEADING_OVERLAP_THRESHOLD and score > best_score:
                    # Check if this heading position is already claimed
                    if h_container_pos not in [v[0] for v in mapped.values()]:
                        best_score = score
                        best_match = (h_container_pos, h_container_tag)

            if best_match:
                mapped[section.section_id] = best_match

        return mapped, "heading_anchor"

    def _find_headings(
        self, html: str
    ) -> List[Tuple[int, str, str, int, str]]:
        """Find all headings in HTML with their positions and container info.

        Returns list of (heading_pos, heading_tag, heading_text,
                        container_pos, container_tag).
        """
        results = []
        heading_pattern = re.compile(
            r'<(h[1-6])\b[^>]*>(.*?)</\1\s*>',
            re.DOTALL | re.IGNORECASE,
        )

        for m in heading_pattern.finditer(html):
            h_pos = m.start()
            h_tag = m.group(1).lower()
            h_text = _strip_html_tags(m.group(2)).strip()

            # Walk up to find nearest section-level ancestor
            container_pos, container_tag = self._find_section_ancestor(
                html, h_pos
            )
            results.append((h_pos, h_tag, h_text, container_pos, container_tag))

        return results

    def _find_section_ancestor(
        self, html: str, heading_pos: int
    ) -> Tuple[int, str]:
        """Find the nearest section-level ancestor element.

        Walks backward from heading_pos to find the nearest opening tag
        of a section container.
        """
        # Search backward for section-level containers
        best_pos = -1
        best_tag = "div"

        # Find all opening tags before heading_pos
        tag_pattern = re.compile(
            r'<(section|article|header|footer|nav|main|aside|div)\b[^>]*>',
            re.IGNORECASE,
        )

        # Simple approach: find the last section-level tag before heading_pos
        # that isn't closed before heading_pos
        candidates = []
        for m in tag_pattern.finditer(html[:heading_pos]):
            tag_name = m.group(1).lower()
            candidates.append((m.start(), tag_name))

        # Walk backward through candidates and pick the nearest
        # section-level container (prefer <section> over <div>)
        for pos, tag in reversed(candidates):
            # Check if this tag is likely the direct container
            # (heuristic: within 500 chars before heading)
            if heading_pos - pos > 2000:
                break

            if tag in _SECTION_CONTAINER_TAGS:
                return pos, tag
            elif tag == "div" and best_pos < 0:
                best_pos = pos
                best_tag = tag

        if best_pos >= 0:
            return best_pos, best_tag

        # Fallback: use the heading position itself
        return heading_pos, "h1"

    def _extract_section_heading(self, markdown: str) -> str:
        """Extract the first heading text from section markdown."""
        match = re.search(r'^#{1,6}\s+(.+?)$', markdown, re.MULTILINE)
        if match:
            # Strip markdown formatting
            text = match.group(1).strip()
            text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            return text
        return ""

    # ------------------------------------------------------------------
    # Strategy 2: Visible text fuzzy matching
    # ------------------------------------------------------------------

    def _strategy_text_match(
        self,
        html: str,
        sections: list,
    ) -> Tuple[Dict[str, Tuple[int, str]], str]:
        """Match sections by visible text fuzzy matching."""
        mapped: Dict[str, Tuple[int, str]] = {}

        # Find top-level block elements
        blocks = self._find_top_level_blocks(html)
        if not blocks:
            return mapped, "text_match"

        for section in sections:
            section_text = _strip_markdown_formatting(section.markdown)
            if len(section_text) < 20:
                continue

            best_match = None
            best_score = 0.0

            for block_pos, block_tag, block_text in blocks:
                if not block_text or len(block_text) < 10:
                    continue

                # Use SequenceMatcher for fuzzy matching
                score = SequenceMatcher(
                    None,
                    section_text[:500].lower(),
                    block_text[:500].lower(),
                ).ratio()

                if score >= _TEXT_MATCH_THRESHOLD and score > best_score:
                    if block_pos not in [v[0] for v in mapped.values()]:
                        best_score = score
                        best_match = (block_pos, block_tag)

            if best_match:
                mapped[section.section_id] = best_match

        return mapped, "text_match"

    def _find_top_level_blocks(
        self, html: str
    ) -> List[Tuple[int, str, str]]:
        """Find top-level block elements and their visible text.

        Returns list of (position_in_full_html, tag_name, visible_text).
        """
        results = []

        # Find body content — track offset so positions are in full HTML
        body_match = re.search(
            r'<body[^>]*>(.*)</body>',
            html, flags=re.DOTALL | re.IGNORECASE,
        )
        if body_match:
            content = body_match.group(1)
            content_offset = body_match.start(1)
        else:
            content = html
            content_offset = 0

        # Find direct children block elements
        block_pattern = re.compile(
            r'<(section|article|header|footer|nav|main|aside|div)\b([^>]*)>',
            re.IGNORECASE,
        )

        depth = 0
        for m in block_pattern.finditer(content):
            # Count depth (simplified — look at context)
            prefix = content[:m.start()]
            tag = m.group(1).lower()

            # Only process top-level blocks (depth 0 or 1)
            open_count = len(re.findall(
                r'<(?:section|article|div)\b', prefix, re.IGNORECASE
            ))
            close_count = len(re.findall(
                r'</(?:section|article|div)\s*>', prefix, re.IGNORECASE
            ))
            depth = open_count - close_count

            if depth <= 1:
                # Extract text from this block
                block_end = _find_closing_tag(content, tag, m.end())
                block_content = content[m.end():block_end]
                visible_text = _strip_html_tags(block_content).strip()
                # Position in full HTML (not just body content)
                results.append((m.start() + content_offset, tag, visible_text[:1000]))

        return results

    # ------------------------------------------------------------------
    # Strategy 3: Positional splitting
    # ------------------------------------------------------------------

    def _strategy_positional(
        self,
        html: str,
        sections: list,
    ) -> Dict[str, Tuple[int, str]]:
        """Split HTML positionally based on section char ratios."""
        mapped: Dict[str, Tuple[int, str]] = {}

        # Find all top-level block boundaries
        blocks = self._find_top_level_blocks(html)
        if not blocks:
            return mapped

        # Distribute sections across blocks proportionally
        total_blocks = len(blocks)
        total_sections = len(sections)

        if total_blocks <= total_sections:
            # Fewer blocks than sections — assign 1:1
            for i, section in enumerate(sections):
                if i < total_blocks:
                    mapped[section.section_id] = (blocks[i][0], blocks[i][1])
        else:
            # More blocks than sections — distribute proportionally
            char_ratios = [s.char_ratio for s in sections]
            block_idx = 0
            for i, section in enumerate(sections):
                if block_idx < total_blocks:
                    mapped[section.section_id] = (
                        blocks[block_idx][0],
                        blocks[block_idx][1],
                    )
                    # Skip blocks proportional to char_ratio
                    skip = max(1, round(char_ratios[i] * total_blocks))
                    block_idx += skip

        return mapped

    # ------------------------------------------------------------------
    # Apply section attributes
    # ------------------------------------------------------------------

    def _apply_section_attrs(
        self,
        html: str,
        mapped: Dict[str, Tuple[int, str]],
    ) -> str:
        """Add data-section attributes at mapped positions."""
        # Sort by position (descending) to apply from end to start
        items = sorted(
            mapped.items(),
            key=lambda x: x[1][0],
            reverse=True,
        )

        for section_id, (pos, tag) in items:
            # Find the opening tag at this position
            tag_pattern = re.compile(
                rf'<{re.escape(tag)}\b([^>]*)>',
                re.IGNORECASE,
            )
            m = tag_pattern.search(html, pos)
            if m and m.start() == pos:
                # Add data-section attribute
                old_tag = m.group(0)
                if 'data-section=' not in old_tag:
                    new_tag = old_tag.replace(
                        f'<{tag}',
                        f'<{tag} data-section="{section_id}"',
                        1,
                    )
                    # Be case-insensitive about the tag replacement
                    actual_tag = re.match(rf'<({tag})\b', old_tag, re.IGNORECASE)
                    if actual_tag:
                        real_tag = actual_tag.group(1)
                        new_tag = old_tag.replace(
                            f'<{real_tag}',
                            f'<{real_tag} data-section="{section_id}"',
                            1,
                        )
                    html = html[:m.start()] + new_tag + html[m.end():]

        return html


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _word_overlap(a: str, b: str) -> float:
    """Word-level Jaccard overlap score."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union else 0.0


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags from text."""
    return re.sub(r'<[^>]+>', ' ', text)


def _strip_markdown_formatting(text: str) -> str:
    """Remove markdown formatting characters."""
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    return text


def _find_closing_tag(html: str, tag: str, start: int) -> int:
    """Find position of matching closing tag."""
    depth = 1
    pos = start
    open_re = re.compile(rf'<{tag}\b[^>]*>', re.IGNORECASE)
    close_re = re.compile(rf'</{tag}\s*>', re.IGNORECASE)

    while pos < len(html) and depth > 0:
        next_open = open_re.search(html, pos)
        next_close = close_re.search(html, pos)

        if next_close is None:
            return len(html)

        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
        else:
            depth -= 1
            if depth == 0:
                return next_close.start()
            pos = next_close.end()

    return len(html)
