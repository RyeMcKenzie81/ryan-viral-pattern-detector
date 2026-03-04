"""Section segmentation for multipass pipeline.

Wraps existing chunk_markdown() and adds:
- Stable section IDs (sec_0, sec_1, ...)
- Tiny-section merging (<200 chars)
- Cap at 8 sections
- Char-ratio height percentages as fallback
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..chunk_markdown import chunk_markdown

logger = logging.getLogger(__name__)

MAX_SECTIONS = 8
TINY_SECTION_THRESHOLD = 200


@dataclass
class SegmenterSection:
    """A section identified by the segmenter."""
    section_id: str      # Immutable: "sec_0", "sec_1", ... (positional)
    name: str            # Human-readable, may duplicate (e.g., "testimonials")
    markdown: str        # Section content
    char_ratio: float    # Fraction of total chars (fallback height estimate)


def segment_markdown(
    raw_markdown: str,
    element_detection: Optional[Dict] = None,
) -> List[SegmenterSection]:
    """Segment page markdown into sections for multipass processing.

    Args:
        raw_markdown: Full page markdown text.
        element_detection: Optional element detection output for section naming hints.

    Returns:
        List of SegmenterSection, ordered top-to-bottom, capped at MAX_SECTIONS.
    """
    if not raw_markdown or not raw_markdown.strip():
        return [SegmenterSection(
            section_id="sec_0",
            name="full_page",
            markdown=raw_markdown or "",
            char_ratio=1.0,
        )]

    chunks = chunk_markdown(raw_markdown)
    if not chunks:
        return [SegmenterSection(
            section_id="sec_0",
            name="full_page",
            markdown=raw_markdown,
            char_ratio=1.0,
        )]

    # Build initial section list from chunks
    sections = []
    for chunk in chunks:
        name = _derive_section_name(chunk.heading_path, chunk.heading_level, element_detection)
        sections.append({
            "name": name,
            "markdown": chunk.text,
            "char_count": len(chunk.text),
        })

    # Merge tiny sections (<200 chars) into adjacent sections
    sections = _merge_tiny_sections(sections)

    # Cap at MAX_SECTIONS by merging smallest adjacent pairs
    while len(sections) > MAX_SECTIONS:
        sections = _merge_smallest_pair(sections)

    # Compute char ratios
    total_chars = sum(s["char_count"] for s in sections)
    if total_chars == 0:
        total_chars = 1

    result = []
    for i, sec in enumerate(sections):
        result.append(SegmenterSection(
            section_id=f"sec_{i}",
            name=sec["name"],
            markdown=sec["markdown"],
            char_ratio=sec["char_count"] / total_chars,
        ))

    logger.info(
        f"Segmented markdown into {len(result)} sections: "
        f"{[s.section_id for s in result]}"
    )
    return result


def _derive_section_name(
    heading_path: List[str],
    heading_level: int,
    element_detection: Optional[Dict],
) -> str:
    """Derive a human-readable section name from heading path."""
    if heading_level == 0:
        return "hero"

    if heading_path:
        # Use the last heading in the path, cleaned up
        name = heading_path[-1].strip().lower()
        # Simplify common patterns
        name = name.replace(" ", "_")[:30]
        # Remove non-alphanumeric except underscore
        name = "".join(c for c in name if c.isalnum() or c == "_")
        if name:
            return name

    return "section"


def _merge_tiny_sections(sections: List[Dict]) -> List[Dict]:
    """Merge sections smaller than TINY_SECTION_THRESHOLD into neighbors."""
    if len(sections) <= 1:
        return sections

    merged = []
    i = 0
    while i < len(sections):
        sec = sections[i]
        if sec["char_count"] < TINY_SECTION_THRESHOLD and merged:
            # Merge into previous section
            merged[-1]["markdown"] += "\n\n" + sec["markdown"]
            merged[-1]["char_count"] += sec["char_count"]
        elif sec["char_count"] < TINY_SECTION_THRESHOLD and i + 1 < len(sections):
            # Merge into next section
            sections[i + 1]["markdown"] = sec["markdown"] + "\n\n" + sections[i + 1]["markdown"]
            sections[i + 1]["char_count"] += sec["char_count"]
        else:
            merged.append(dict(sec))
        i += 1

    return merged if merged else sections


def _merge_smallest_pair(sections: List[Dict]) -> List[Dict]:
    """Merge the smallest adjacent pair of sections."""
    if len(sections) <= 1:
        return sections

    # Find the pair with smallest combined char count
    min_combined = float("inf")
    min_idx = 0
    for i in range(len(sections) - 1):
        combined = sections[i]["char_count"] + sections[i + 1]["char_count"]
        if combined < min_combined:
            min_combined = combined
            min_idx = i

    # Merge at min_idx
    result = []
    for i in range(len(sections)):
        if i == min_idx:
            merged = {
                "name": sections[i]["name"],
                "markdown": sections[i]["markdown"] + "\n\n" + sections[i + 1]["markdown"],
                "char_count": sections[i]["char_count"] + sections[i + 1]["char_count"],
            }
            result.append(merged)
        elif i == min_idx + 1:
            continue  # Already merged
        else:
            result.append(dict(sections[i]))

    return result
