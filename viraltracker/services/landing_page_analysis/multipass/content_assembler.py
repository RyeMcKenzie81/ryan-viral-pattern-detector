"""Deterministic Phase 2 replacement for multipass pipeline v4.

Replaces the ~54s LLM call with ~10ms of deterministic string processing.
Converts per-section markdown to HTML, injects images with dimensions,
assigns data-slots, and fills skeleton placeholders.
"""

import logging
import re
from typing import Dict, List, Optional

from markdown_it import MarkdownIt

from .html_extractor import ImageRegistry, PageImage

logger = logging.getLogger(__name__)


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
                        for key, rendered_html in sub_values.items():
                            # Enhance images in each sub-value
                            if image_registry:
                                rendered_html = _enhance_images(
                                    rendered_html, sec_id, image_registry
                                )
                            placeholder = "{{" + key + "}}"
                            html = html.replace(placeholder, rendered_html, 1)

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
                        # Fallback: replace entire section with generic template
                        section_html = md.render(section.markdown)
                        if image_registry:
                            section_html = _enhance_images(section_html, sec_id, image_registry)
                            section_html = _inject_background_images(section_html, sec_id, image_registry)
                        section_html, heading_counter, body_counter, cta_counter, found_h1, found_h2 = (
                            _assign_data_slots(section_html, heading_counter, body_counter, cta_counter, found_h1, found_h2)
                        )
                        fallback_html = _build_generic_fallback(sec_id, section_html)
                        html = _replace_entire_section(html, sec_id, fallback_html)
                        used_structured = True  # We handled this section

            except Exception as e:
                logger.warning(f"Structured assembly failed for {sec_id}: {e}")
                used_structured = False

        if not used_structured:
            # EXISTING PATH: Linear content dump (unchanged)
            placeholder = "{{" + sec_id + "}}"

            if placeholder not in html:
                logger.debug(f"Placeholder {placeholder} not in skeleton, skipping")
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

            # Step 4: Replace placeholder (only first occurrence)
            html = html.replace(placeholder, section_html, 1)

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
            return f'<{tag}{attrs} data-slot="{slot_name}"{rest}'
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
