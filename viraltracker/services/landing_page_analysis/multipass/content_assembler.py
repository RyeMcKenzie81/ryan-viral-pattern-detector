"""Deterministic Phase 2 replacement for multipass pipeline v4.

Replaces the ~54s LLM call with ~10ms of deterministic string processing.
Converts per-section markdown to HTML, injects images with dimensions,
assigns data-slots, and fills skeleton placeholders.
"""

import json
import logging
import os
import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from markdown_it import MarkdownIt

from .html_extractor import ImageRegistry, PageImage

logger = logging.getLogger(__name__)

# Feature flag: controls overflow rendering + smart fallback in Phase 2.
# True = new behavior (preserve remaining text, keep template styling on fallback)
# False = old behavior (drop remaining text, generic fallback)
PHASE2_OVERFLOW = os.environ.get("PHASE2_OVERFLOW", "true").lower() == "true"

# Artifact labels that indicate scraped SEO/invisible content
_ARTIFACT_LABELS = re.compile(
    r'^\*{0,2}(Summary|Key Points|Overview|Description)\s*:\*{0,2}',
    re.IGNORECASE,
)


def _extract_ghost_texts(page_html: str) -> List[str]:
    """Extract text fragments from SEO/invisible HTML elements.

    Extracts from:
    - <meta name="description" content="...">
    - <meta property="og:description" content="...">
    - <script type="application/ld+json"> → description fields
    """
    fragments = []

    # Meta description
    for m in re.finditer(
        r'<meta\s[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
        page_html, re.IGNORECASE,
    ):
        fragments.append(m.group(1))

    # Also match content before name (attribute order varies)
    for m in re.finditer(
        r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
        page_html, re.IGNORECASE,
    ):
        fragments.append(m.group(1))

    # OG description
    for m in re.finditer(
        r'<meta\s[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
        page_html, re.IGNORECASE,
    ):
        fragments.append(m.group(1))

    for m in re.finditer(
        r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']',
        page_html, re.IGNORECASE,
    ):
        fragments.append(m.group(1))

    # JSON-LD descriptions
    for m in re.finditer(
        r'<script\s[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and 'description' in data:
                fragments.append(data['description'])
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'description' in item:
                        fragments.append(item['description'])
        except (json.JSONDecodeError, TypeError):
            pass

    return fragments


def _normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for comparison."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def filter_seo_ghost_text(sections: list, page_html: str) -> list:
    """Filter ghost text artifacts from section markdown.

    Ghost text = invisible SEO content (meta descriptions, JSON-LD)
    that Firecrawl scrapes and includes in the page markdown.

    Uses a dual-gate approach:
    1. Paragraph must fuzzy-match an SEO metadata fragment (ratio >= 0.8)
    2. Paragraph must start with an artifact label (Summary:, Key Points:, etc.)

    When page_html is empty, applies conservative fallback on sec_0 only:
    strips paragraphs starting with **Summary:** that are >= 200 chars.

    Args:
        sections: List of SegmenterSection objects.
        page_html: Raw HTML of the page (for SEO metadata extraction).

    Returns:
        New list of sections with filtered markdown (originals not mutated).
    """
    if not sections:
        return sections

    # No page_html → conservative fallback on sec_0 only
    if not page_html.strip():
        result = []
        for section in sections:
            if section.section_id == "sec_0":
                paragraphs = section.markdown.split('\n\n')
                filtered = []
                removed = 0
                for para in paragraphs:
                    stripped = para.strip()
                    if (
                        _ARTIFACT_LABELS.match(stripped)
                        and len(stripped) >= 200
                    ):
                        removed += 1
                        continue
                    filtered.append(para)
                if removed:
                    logger.info(
                        f"Ghost text filter (fallback): stripped {removed} "
                        f"paragraphs from {section.section_id}"
                    )
                    new_section = deepcopy(section)
                    new_section.markdown = '\n\n'.join(filtered)
                    result.append(new_section)
                else:
                    result.append(section)
            else:
                result.append(section)
        return result

    # Full path: extract ghost-text fragments from page_html
    ghost_fragments = _extract_ghost_texts(page_html)
    if not ghost_fragments:
        return sections

    normalized_ghosts = [_normalize_text(f) for f in ghost_fragments if f.strip()]
    if not normalized_ghosts:
        return sections

    result = []
    for section in sections:
        paragraphs = section.markdown.split('\n\n')
        filtered = []
        removed = 0

        for para in paragraphs:
            stripped = para.strip()
            if not stripped:
                filtered.append(para)
                continue

            # Gate 1: Must start with an artifact label
            if not _ARTIFACT_LABELS.match(stripped):
                filtered.append(para)
                continue

            # Gate 2: Must fuzzy-match an SEO metadata fragment
            norm_para = _normalize_text(stripped)
            is_ghost = False
            for ghost in normalized_ghosts:
                ratio = SequenceMatcher(None, norm_para, ghost).ratio()
                if ratio >= 0.8:
                    is_ghost = True
                    break

            if is_ghost:
                removed += 1
            else:
                filtered.append(para)

        if removed:
            logger.info(
                f"Ghost text filter: stripped {removed} paragraphs "
                f"from {section.section_id}"
            )
            new_section = deepcopy(section)
            new_section.markdown = '\n\n'.join(filtered)
            result.append(new_section)
        else:
            result.append(section)

    return result


def assemble_content(
    skeleton_html: str,
    sections: list,  # List[SegmenterSection]
    section_map: Dict,  # Dict[str, NormalizedBox]
    image_registry: Optional[ImageRegistry] = None,
    layout_map: Optional[Dict] = None,
    extracted_css: Optional[object] = None,
) -> str:
    """Deterministic Phase 2: convert per-section markdown -> HTML,
    inject images with dimensions, assign data-slots, fill skeleton.

    When layout_map is provided, uses structured content assembly for
    non-generic sections (feature grids, testimonial cards, FAQ lists, etc.).
    Falls back to linear dump for generic sections or when coverage is low.

    Args:
        skeleton_html: Phase 1 output with {{sec_N}} or sub-placeholders.
        sections: SegmenterSection list.
        section_map: Dict of section_id -> NormalizedBox from Phase 1.
        image_registry: Optional ImageRegistry for image enhancement.
        layout_map: Optional Dict of sec_id -> LayoutHint for structured assembly.
        extracted_css: Optional ExtractedCSS (unused directly, reserved for future).

    Returns:
        Complete HTML with all placeholders replaced.
    """
    md = MarkdownIt().disable("html_block").disable("html_inline")

    html = skeleton_html

    # Global counters for slot naming across sections
    heading_counter = 0
    body_counter = 0
    cta_counter = 0
    found_h1 = False
    found_h2 = False

    for section in sections:
        sec_id = section.section_id
        layout = layout_map.get(sec_id) if layout_map else None
        layout_type = ""
        if layout and hasattr(layout, 'layout_type'):
            layout_type = layout.layout_type

        used_structured = False

        if layout and layout_type and layout_type != "generic":
            # NEW PATH: Structured content assembly for non-generic layouts
            try:
                from .content_patterns import (
                    detect_content_pattern,
                    normalize_markdown_to_text,
                    split_content_for_template,
                )

                pattern = detect_content_pattern(section, layout)
                sub_values = split_content_for_template(
                    pattern, layout, section, image_registry
                )

                if sub_values:
                    # Coverage check: compare rendered text vs source text
                    rendered_text_only = re.sub(
                        r'<[^>]+>', '', "".join(sub_values.values())
                    )
                    source_text_only = normalize_markdown_to_text(section.markdown)

                    if (
                        len(rendered_text_only.strip()) >= 0.6 * len(source_text_only.strip())
                        or not source_text_only.strip()
                    ):
                        # Coverage OK — inject sub-values into template placeholders
                        all_content = []
                        any_replaced = False
                        for key, rendered_html in sub_values.items():
                            # Enhance images in each sub-value
                            if image_registry:
                                rendered_html = _enhance_images(
                                    rendered_html, sec_id, image_registry
                                )
                            placeholder = "{{" + key + "}}"
                            if placeholder in html:
                                html = html.replace(placeholder, rendered_html, 1)
                                any_replaced = True
                            all_content.append(rendered_html)

                        # If none of the sub_value keys matched skeleton
                        # placeholders, fall back to filling sub-placeholders
                        if not any_replaced and all_content:
                            combined = "\n".join(all_content)
                            html = _replace_section_placeholders(
                                html, sec_id, combined
                            )

                        # Inject background images for this section
                        if image_registry:
                            # Find the section tag and inject after it
                            section_tag_re = re.compile(
                                rf'(<(?:section|footer|header|nav|article|aside|main)\s[^>]*data-section="{re.escape(sec_id)}"[^>]*>)',
                                re.IGNORECASE,
                            )
                            tag_match = section_tag_re.search(html)
                            if tag_match:
                                bg_html = _build_bg_images_html(sec_id, image_registry)
                                if bg_html:
                                    insert_pos = tag_match.end()
                                    html = html[:insert_pos] + bg_html + html[insert_pos:]

                        # Assign data-slots on this section's rendered fragment
                        section_rendered = _extract_section_html(html, sec_id)
                        if section_rendered:
                            slotted, heading_counter, body_counter, cta_counter, found_h1, found_h2 = (
                                _assign_data_slots(
                                    section_rendered,
                                    heading_counter,
                                    body_counter,
                                    cta_counter,
                                    found_h1,
                                    found_h2,
                                )
                            )
                            html = html.replace(section_rendered, slotted, 1)
                        used_structured = True
                    else:
                        logger.info(
                            f"Coverage check failed for {sec_id} "
                            f"({len(rendered_text_only)}/{len(source_text_only)} chars), "
                            f"falling back to linear dump"
                        )
                        # Fallback: render full markdown as HTML
                        section_html = md.render(section.markdown)
                        if image_registry:
                            section_html = _enhance_images(section_html, sec_id, image_registry)
                            section_html = _inject_background_images(section_html, sec_id, image_registry)
                        section_html, heading_counter, body_counter, cta_counter, found_h1, found_h2 = (
                            _assign_data_slots(section_html, heading_counter, body_counter, cta_counter, found_h1, found_h2)
                        )
                        if PHASE2_OVERFLOW:
                            # Smart fallback: keep template styling, replace sub-placeholders
                            html = _replace_section_placeholders(html, sec_id, section_html)
                        else:
                            # Old fallback: replace entire section with bland generic wrapper
                            fallback_html = _build_generic_fallback(sec_id, section_html)
                            html = _replace_entire_section(html, sec_id, fallback_html)
                        used_structured = True  # We handled this section

            except Exception as e:
                logger.warning(f"Structured assembly failed for {sec_id}: {e}")
                used_structured = False

        if not used_structured:
            # EXISTING PATH: Linear content dump
            placeholder = "{{" + sec_id + "}}"

            # Check if single placeholder exists; if not, try sub-placeholder
            # fallback (Claude may generate {{sec_N_header}}+{{sec_N_items}}
            # even when layout says content_block/generic)
            has_single = placeholder in html
            has_sub = not has_single and (
                "{{" + sec_id + "_" in html
            )

            if not has_single and not has_sub:
                logger.debug(f"No placeholder for {sec_id} in skeleton, skipping")
                continue

            # Step 1: Convert markdown to HTML
            section_html = md.render(section.markdown)

            # Step 2: Enhance images with dimensions from registry
            if image_registry:
                section_html = _enhance_images(section_html, sec_id, image_registry)
                section_html = _inject_background_images(
                    section_html, sec_id, image_registry
                )

            # Step 3: Assign data-slots
            section_html, heading_counter, body_counter, cta_counter, found_h1, found_h2 = (
                _assign_data_slots(
                    section_html,
                    heading_counter,
                    body_counter,
                    cta_counter,
                    found_h1,
                    found_h2,
                )
            )

            # Step 4: Replace placeholder(s)
            if has_single:
                html = html.replace(placeholder, section_html, 1)
            else:
                # Sub-placeholder fallback: fill first sub-placeholder,
                # clear the rest (keeps template styling)
                html = _replace_section_placeholders(html, sec_id, section_html)

    return html


def phase_2_fallback(
    skeleton_html: str,
    sections: list,  # List[SegmenterSection]
) -> str:
    """Fallback: inject per-section markdown as HTML into all skeleton placeholders.

    Fixed version: iterates ALL sections (not just the first).
    """
    md = MarkdownIt().disable("html_block").disable("html_inline")

    html = skeleton_html
    for section in sections:
        placeholder = f"{{{{{section.section_id}}}}}"
        section_html = md.render(section.markdown)
        html = html.replace(placeholder, section_html, 1)
    return html


# ---------------------------------------------------------------------------
# Image enhancement
# ---------------------------------------------------------------------------


def _enhance_images(
    section_html: str,
    sec_id: str,
    registry: ImageRegistry,
) -> str:
    """Add width/height/srcset to <img> tags from ImageRegistry."""
    section_images = registry.get_section_images(sec_id)
    if not section_images:
        return section_html

    # Build lookup by URL
    img_lookup: Dict[str, PageImage] = {img.url: img for img in section_images}

    def _enhance_match(match: re.Match) -> str:
        tag = match.group(0)
        src_match = re.search(r'src="([^"]*)"', tag)
        if not src_match:
            return tag

        src = src_match.group(1)
        img = img_lookup.get(src)
        if not img:
            return tag

        # Add width/height if not present and available
        if img.width and 'width=' not in tag:
            tag = tag.replace('/>', f' width="{img.width}"/>')
            tag = tag.replace('>', f' width="{img.width}">', 1)
        if img.height and 'height=' not in tag:
            tag = tag.replace('/>', f' height="{img.height}"/>')
            tag = tag.replace('>', f' height="{img.height}">', 1)

        # Add srcset if available
        if img.srcset and 'srcset=' not in tag:
            tag = tag.replace('/>', f' srcset="{img.srcset}"/>')
            tag = tag.replace('>', f' srcset="{img.srcset}">', 1)

        return tag

    return re.sub(r'<img\b[^>]*/?>', _enhance_match, section_html)


def _inject_background_images(
    section_html: str,
    sec_id: str,
    registry: ImageRegistry,
) -> str:
    """Inject background images as <img data-bg-image="true"> at section start."""
    section_images = registry.get_section_images(sec_id)
    bg_images = [img for img in section_images if img.is_background]

    if not bg_images:
        return section_html

    bg_tags: List[str] = []
    for img in bg_images:
        attrs = [
            f'src="{img.url}"',
            'alt="background"',
            'data-bg-image="true"',
            'style="width: 100%; height: auto; object-fit: cover; display: block;"',
        ]
        if img.width:
            attrs.append(f'width="{img.width}"')
        if img.height:
            attrs.append(f'height="{img.height}"')
        bg_tags.append(f'<img {" ".join(attrs)}>')

    return "\n".join(bg_tags) + "\n" + section_html


# ---------------------------------------------------------------------------
# Data-slot assignment
# ---------------------------------------------------------------------------


def _assign_data_slots(
    html: str,
    heading_counter: int,
    body_counter: int,
    cta_counter: int,
    found_h1: bool,
    found_h2: bool,
) -> tuple:
    """Add data-slot attributes to elements using canonical naming.

    Returns (html, heading_counter, body_counter, cta_counter, found_h1, found_h2).
    """

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
            return f'<{tag}{attrs} data-slot="{slot_name}"{rest}>'
        return match.group(0)

    pattern = re.compile(
        r'<(h[1-4]|p|a|button)((?:\s+[^>]*)?)(\s*/?)>',
        re.IGNORECASE,
    )
    result = pattern.sub(_add_slot, html)

    return result, heading_counter, body_counter, cta_counter, found_h1, found_h2


# ---------------------------------------------------------------------------
# Layout-aware assembly helpers
# ---------------------------------------------------------------------------


def _extract_section_html(html: str, sec_id: str) -> Optional[str]:
    """Extract the inner HTML of a section by data-section attribute."""
    # Match the section and its content
    pattern = re.compile(
        rf'(<(?:section|footer|header|nav|article|aside|main)\s[^>]*data-section="{re.escape(sec_id)}"[^>]*>)(.*?)(</(?:section|footer|header|nav|article|aside|main)>)',
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        return match.group(2)
    return None


def _replace_entire_section(html: str, sec_id: str, replacement: str) -> str:
    """Replace the entire <section data-section="sec_N">...</section> block."""
    pattern = re.compile(
        rf'<(?:section|footer|header|nav|article|aside|main)\s[^>]*data-section="{re.escape(sec_id)}"[^>]*>.*?</(?:section|footer|header|nav|article|aside|main)>',
        re.DOTALL | re.IGNORECASE,
    )
    return pattern.sub(replacement, html, count=1)


def _build_generic_fallback(sec_id: str, content_html: str) -> str:
    """Build a generic section wrapper for coverage-check fallback."""
    return (
        f'<section data-section="{sec_id}" class="mp-generic"'
        f' style="padding: 70px 30px;">'
        f'<div class="mp-container">{content_html}</div>'
        f'</section>'
    )


def _replace_section_placeholders(html: str, sec_id: str, content_html: str) -> str:
    """Replace all sub-placeholders for a section, preserving template styling.

    Smart fallback: instead of replacing the entire section with a bland
    mp-generic wrapper, this keeps the original template section tag (with
    its CSS classes: mp-hero-split, mp-stats-row, etc.) and fills the first
    sub-placeholder with the content dump, clearing the rest.
    """
    placeholder_re = re.compile(r'\{\{' + re.escape(sec_id) + r'(?:_\w+)?\}\}')
    first_replaced = False

    def _replace(match):
        nonlocal first_replaced
        if not first_replaced:
            first_replaced = True
            return content_html
        return ''

    return placeholder_re.sub(_replace, html)


def _build_bg_images_html(sec_id: str, registry: ImageRegistry) -> str:
    """Build background image HTML for injection after section opening tag."""
    section_images = registry.get_section_images(sec_id)
    bg_images = [img for img in section_images if img.is_background]

    if not bg_images:
        return ""

    bg_tags: List[str] = []
    for img in bg_images:
        attrs = [
            f'src="{img.url}"',
            'alt="background"',
            'data-bg-image="true"',
            'style="width: 100%; height: auto; object-fit: cover; display: block;"',
        ]
        if img.width:
            attrs.append(f'width="{img.width}"')
        if img.height:
            attrs.append(f'height="{img.height}"')
        bg_tags.append(f'<img {" ".join(attrs)}>')

    return "\n".join(bg_tags) + "\n"
