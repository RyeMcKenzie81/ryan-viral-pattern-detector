"""Content pattern detection for multipass pipeline.

Analyzes per-section markdown to detect structural content patterns
(feature lists, testimonials, FAQ, stats, etc.) and splits content
into sub-placeholders for template injection.

All detection is deterministic — regex/heuristic, no LLM.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .section_templates import PLACEHOLDER_SUFFIXES

# Import feature flag from content_assembler (avoid circular by reading env directly)
_PHASE2_OVERFLOW = os.environ.get("PHASE2_OVERFLOW", "true").lower() == "true"

logger = logging.getLogger(__name__)

# Minimum items to detect a structured pattern
_MIN_FEATURE_ITEMS = 2
_MIN_TESTIMONIAL_ITEMS = 1
_MIN_FAQ_ITEMS = 2
_MIN_STAT_ITEMS = 2


@dataclass
class ContentPattern:
    """Detected content pattern for a section."""
    pattern_type: str   # "feature_list", "testimonial_list", "faq_list",
                        # "stats_list", "logo_list", "prose"
    items: List[Dict] = field(default_factory=list)
    header_markdown: str = ""
    footer_markdown: str = ""


# ---------------------------------------------------------------------------
# Detection heuristics
# ---------------------------------------------------------------------------

# Feature list: ### Heading\nParagraph blocks
_FEATURE_BLOCK_RE = re.compile(
    r'^###\s+(.+)\n((?:(?!^#{1,3}\s)(?!\n###).+\n?)*)',
    re.MULTILINE,
)

# Testimonials: > quote + attribution
_QUOTE_RE = re.compile(
    r'^>\s*(.+(?:\n>\s*.+)*)\n+(?:[-—–]\s*(.+))?',
    re.MULTILINE,
)

# FAQ: ### Question?\nAnswer
_FAQ_RE = re.compile(
    r'^###?\s+(.+\?)\s*\n((?:(?!^#{1,3}\s).+\n?)*)',
    re.MULTILINE,
)

# Stats: lines with prominent numbers
_STAT_LINE_RE = re.compile(
    r'(?:^|\n)\s*(\d[\d,.]*[KkMmBb]?[+%]?)\s*[-–—:|\n]\s*(.+?)(?:\n|$)',
)

# Alternative stat detection: **number** label pattern
_STAT_BOLD_RE = re.compile(
    r'\*\*(\d[\d,.]*[KkMmBb]?[+%]?)\*\*\s*(.+?)(?:\n|$)',
)

# Image references: ![alt](url)
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# Heading (any level) at start of content
_SECTION_HEADING_RE = re.compile(r'^(#{1,3})\s+(.+?)$', re.MULTILINE)


def _remove_spans(text: str, spans: list) -> str:
    """Remove matched regex spans from text, returning remaining unmatched text.

    Used by detection functions to compute what text was NOT captured
    by structured pattern matching (stats, features, etc.).
    """
    if not spans:
        return text
    sorted_spans = sorted(spans, key=lambda s: s[0])
    parts = []
    prev_end = 0
    for start, end in sorted_spans:
        if start > prev_end:
            parts.append(text[prev_end:start])
        prev_end = max(prev_end, end)
    if prev_end < len(text):
        parts.append(text[prev_end:])
    return '\n'.join(p.strip() for p in parts if p.strip())


def detect_content_pattern(
    section: Any,
    layout_hint: Any,
) -> ContentPattern:
    """Detect content pattern from section markdown.

    Layout hint biases detection: e.g., if layout is feature_grid,
    look harder for repeated heading+text blocks.

    Args:
        section: SegmenterSection with .markdown and .section_id.
        layout_hint: LayoutHint with .layout_type.

    Returns:
        ContentPattern with detected items.
    """
    md = section.markdown
    layout_type = ""
    if layout_hint and hasattr(layout_hint, 'layout_type'):
        layout_type = layout_hint.layout_type

    # Extract section header (first heading before items)
    header_md, body_md = _split_header(md)

    # Try detection in priority order, biased by layout_type
    if layout_type == "faq_list":
        result = _detect_faq(body_md)
        if result:
            result.header_markdown = header_md
            return result

    if layout_type == "testimonial_cards":
        result = _detect_testimonials(body_md)
        if result:
            result.header_markdown = header_md
            return result

    if layout_type == "stats_row":
        result = _detect_stats(body_md)
        if result:
            result.header_markdown = header_md
            return result

    if layout_type == "logo_bar":
        result = _detect_logos(body_md)
        if result:
            result.header_markdown = header_md
            return result

    # Generic detection order (no layout bias)
    result = _detect_faq(body_md)
    if result:
        result.header_markdown = header_md
        return result

    result = _detect_testimonials(body_md)
    if result:
        result.header_markdown = header_md
        return result

    result = _detect_stats(body_md)
    if result:
        result.header_markdown = header_md
        return result

    result = _detect_features(body_md)
    if result:
        result.header_markdown = header_md
        return result

    result = _detect_logos(body_md)
    if result:
        result.header_markdown = header_md
        return result

    # Default: prose
    return ContentPattern(
        pattern_type="prose",
        header_markdown=header_md,
        footer_markdown=body_md,
    )


def _split_header(md: str) -> tuple:
    """Split markdown into header (first heading) and body (rest)."""
    match = _SECTION_HEADING_RE.match(md.strip())
    if match:
        header_end = match.end()
        header = md[:header_end].strip()
        body = md[header_end:].strip()
        return header, body
    return "", md


def _detect_features(md: str) -> Optional[ContentPattern]:
    """Detect feature list: 2+ consecutive ### Heading + paragraph blocks."""
    items = []
    matched_spans = []
    for match in _FEATURE_BLOCK_RE.finditer(md):
        heading = match.group(1).strip()
        body = match.group(2).strip()
        if heading:
            item = {"heading": heading, "body": body}
            # Check for image in the body
            img_match = _IMAGE_RE.search(body)
            if img_match:
                item["image_alt"] = img_match.group(1)
                item["image_url"] = img_match.group(2)
            items.append(item)
            matched_spans.append((match.start(), match.end()))

    if len(items) >= _MIN_FEATURE_ITEMS:
        remaining = _remove_spans(md, matched_spans)
        return ContentPattern(pattern_type="feature_list", items=items, footer_markdown=remaining)
    return None


def _detect_testimonials(md: str) -> Optional[ContentPattern]:
    """Detect testimonials: blockquotes with optional attribution."""
    items = []
    matched_spans = []
    for match in _QUOTE_RE.finditer(md):
        quote_text = match.group(1).strip()
        # Strip leading > from each line
        quote_text = re.sub(r'^>\s*', '', quote_text, flags=re.MULTILINE).strip()
        attribution = (match.group(2) or "").strip()

        if quote_text:
            item = {"quote": quote_text}
            # Parse attribution: "Name, Title" or "Name"
            if attribution:
                parts = attribution.split(',', 1)
                item["author"] = parts[0].strip()
                if len(parts) > 1:
                    item["title"] = parts[1].strip()
            items.append(item)
            matched_spans.append((match.start(), match.end()))

    if len(items) >= _MIN_TESTIMONIAL_ITEMS:
        remaining = _remove_spans(md, matched_spans)
        return ContentPattern(pattern_type="testimonial_list", items=items, footer_markdown=remaining)
    return None


def _detect_faq(md: str) -> Optional[ContentPattern]:
    """Detect FAQ: ### Question? + answer blocks."""
    items = []
    matched_spans = []
    for match in _FAQ_RE.finditer(md):
        question = match.group(1).strip()
        answer = match.group(2).strip()
        if question and answer:
            items.append({"question": question, "answer": answer})
            matched_spans.append((match.start(), match.end()))

    if len(items) >= _MIN_FAQ_ITEMS:
        remaining = _remove_spans(md, matched_spans)
        return ContentPattern(pattern_type="faq_list", items=items, footer_markdown=remaining)
    return None


def _detect_stats(md: str) -> Optional[ContentPattern]:
    """Detect stats: prominent numbers with labels."""
    items = []
    seen_numbers = set()
    matched_spans = []

    for regex in (_STAT_BOLD_RE, _STAT_LINE_RE):
        for match in regex.finditer(md):
            number = match.group(1).strip()
            label = match.group(2).strip()
            if number and label and number not in seen_numbers:
                items.append({"number": number, "label": label})
                seen_numbers.add(number)
                matched_spans.append((match.start(), match.end()))

    if len(items) >= _MIN_STAT_ITEMS:
        remaining = _remove_spans(md, matched_spans)
        return ContentPattern(pattern_type="stats_list", items=items, footer_markdown=remaining)
    return None


def _detect_logos(md: str) -> Optional[ContentPattern]:
    """Detect logo/image list: section dominated by image references."""
    images = _IMAGE_RE.findall(md)
    # Strip images from markdown to check text ratio
    text_only = _IMAGE_RE.sub('', md).strip()

    if len(images) >= 3 and len(text_only) < len(md) * 0.3:
        items = [{"alt": alt, "url": url} for alt, url in images]
        return ContentPattern(pattern_type="logo_list", items=items)
    return None


# ---------------------------------------------------------------------------
# Content rendering for templates
# ---------------------------------------------------------------------------


def split_content_for_template(
    pattern: ContentPattern,
    layout: Any,
    section: Any,
    image_registry: Optional[Any] = None,
) -> Dict[str, str]:
    """Render content pattern into sub-placeholder HTML.

    Returns dict of placeholder_key → rendered HTML.
    NO data-slot assignment here — _assign_data_slots() handles it.

    Args:
        pattern: Detected ContentPattern.
        layout: LayoutHint for this section.
        section: SegmenterSection.
        image_registry: Optional ImageRegistry for image enhancement.

    Returns:
        Dict mapping placeholder keys (e.g., "sec_0_header", "sec_0_items")
        to rendered HTML strings.
    """
    from markdown_it import MarkdownIt
    md_renderer = MarkdownIt().disable("html_block").disable("html_inline")

    sec_id = section.section_id
    result: Dict[str, str] = {}

    # Render header if present
    header_key = sec_id + PLACEHOLDER_SUFFIXES["header"]
    if pattern.header_markdown:
        result[header_key] = md_renderer.render(pattern.header_markdown)

    # Render items based on pattern type
    items_key = sec_id + PLACEHOLDER_SUFFIXES["items"]

    if pattern.pattern_type == "feature_list":
        items_html = []
        for item in pattern.items:
            heading = item.get("heading", "")
            body = item.get("body", "")
            img_html = ""
            if item.get("image_url"):
                img_html = f'<img src="{item["image_url"]}" alt="{item.get("image_alt", "")}">'
            items_html.append(
                f'<div class="mp-feature-card">'
                f'{img_html}'
                f'<h3>{heading}</h3>'
                f'<p>{body}</p>'
                f'</div>'
            )
        result[items_key] = "\n".join(items_html)

    elif pattern.pattern_type == "testimonial_list":
        items_html = []
        for item in pattern.items:
            quote = item.get("quote", "")
            author = item.get("author", "")
            title = item.get("title", "")
            cite_parts = []
            if author:
                cite_parts.append(author)
            if title:
                cite_parts.append(title)
            cite_html = f'<cite>{", ".join(cite_parts)}</cite>' if cite_parts else ""
            items_html.append(
                f'<div class="mp-testimonial-card">'
                f'<blockquote>{quote}</blockquote>'
                f'{cite_html}'
                f'</div>'
            )
        result[items_key] = "\n".join(items_html)

    elif pattern.pattern_type == "faq_list":
        items_html = []
        for item in pattern.items:
            q = item.get("question", "")
            a = item.get("answer", "")
            items_html.append(
                f'<div class="mp-faq-item">'
                f'<h3>{q}</h3>'
                f'<p>{a}</p>'
                f'</div>'
            )
        result[items_key] = "\n".join(items_html)

    elif pattern.pattern_type == "stats_list":
        items_html = []
        for item in pattern.items:
            number = item.get("number", "")
            label = item.get("label", "")
            items_html.append(
                f'<div class="mp-stat">'
                f'<span class="mp-stat-number">{number}</span>'
                f'<span class="mp-stat-label">{label}</span>'
                f'</div>'
            )
        result[items_key] = "\n".join(items_html)

    elif pattern.pattern_type == "logo_list":
        items_html = []
        for item in pattern.items:
            alt = item.get("alt", "logo")
            url = item.get("url", "")
            items_html.append(f'<img src="{url}" alt="{alt}">')
        result[items_key] = "\n".join(items_html)

    elif pattern.pattern_type == "prose":
        # Prose: render full body as single block
        single_key = sec_id + PLACEHOLDER_SUFFIXES["single"]
        body = pattern.footer_markdown or ""
        full_md = ""
        if pattern.header_markdown:
            full_md = pattern.header_markdown + "\n\n"
        full_md += body
        result[single_key] = md_renderer.render(full_md)
        return result

    # --- Overflow: preserve remaining text alongside structured items ---
    # When pattern detection captured items (stats, features, etc.) but
    # significant text remains uncaptured, render it as an overflow block.
    # Gated by PHASE2_OVERFLOW flag for A/B comparison.
    if _PHASE2_OVERFLOW and pattern.footer_markdown and pattern.footer_markdown.strip():
        source_text = normalize_markdown_to_text(section.markdown)
        overflow_text = normalize_markdown_to_text(pattern.footer_markdown)
        # Only add overflow if remaining text is > 40% of total section text
        if source_text and len(overflow_text) > 0.4 * len(source_text):
            overflow_html = md_renderer.render(pattern.footer_markdown)
            overflow_block = f'<div class="mp-overflow">{overflow_html}</div>'
            if items_key in result:
                result[items_key] = result[items_key] + '\n' + overflow_block
            logger.info(
                f"Overflow: {sec_id} — {len(overflow_text)}/{len(source_text)} chars "
                f"({len(overflow_text) * 100 // len(source_text)}%) preserved"
            )

    # For hero_split, handle text/image split
    layout_type = ""
    if layout and hasattr(layout, 'layout_type'):
        layout_type = layout.layout_type

    if layout_type == "hero_split":
        text_key = sec_id + PLACEHOLDER_SUFFIXES["text"]
        image_key = sec_id + PLACEHOLDER_SUFFIXES["image"]
        # Render header + remaining text as text column
        full_md = ""
        if pattern.header_markdown:
            full_md = pattern.header_markdown + "\n\n"
        if pattern.footer_markdown:
            full_md += pattern.footer_markdown
        text_html = md_renderer.render(full_md)
        # For non-prose patterns, include rendered items in text column
        if items_key in result and pattern.pattern_type != "prose":
            text_html = result.pop(items_key) + '\n' + text_html
        result[text_key] = text_html
        # Image placeholder — try to find an image in the content
        img_match = _IMAGE_RE.search(section.markdown)
        if img_match:
            result[image_key] = f'<img src="{img_match.group(2)}" alt="{img_match.group(1)}" style="max-width: 100%; height: auto;">'
        else:
            result[image_key] = '<div style="min-height: 200px; background: #e0e0e0; border-radius: 8px;"></div>'
        return result

    return result


def normalize_markdown_to_text(md: str) -> str:
    """Strip markdown syntax to get plain text for coverage comparison."""
    text = md
    # Images: ![alt](url) → alt
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # Links: [text](url) → text
    text = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # Headings: ### heading → heading
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Emphasis, code, quotes
    text = re.sub(r'[*_~`>]+', '', text)
    # List markers
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    return text.strip()
