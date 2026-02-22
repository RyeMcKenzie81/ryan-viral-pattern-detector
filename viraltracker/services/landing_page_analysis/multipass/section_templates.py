"""Section template library for multipass pipeline.

13 deterministic section templates that generate skeleton HTML from
layout classifications + design system + extracted CSS.

Each template uses CSS classes (mp-* prefix) for layout properties
to preserve responsive behavior. Inline styles are used only for
non-responsive properties (colors, font-size, non-breakpoint padding).

All templates work under the .lp-mockup wrapper div.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared placeholder naming contract
# ---------------------------------------------------------------------------

PLACEHOLDER_SUFFIXES = {
    "single": "",           # {{sec_N}} — used by generic, hero_centered, cta_banner, etc.
    "header": "_header",    # {{sec_N_header}} — section heading area
    "items": "_items",      # {{sec_N_items}} — repeated content items
    "text": "_text",        # {{sec_N_text}} — text column in split layouts
    "image": "_image",      # {{sec_N_image}} — image column in split layouts
}


def _ph(sec_id: str, suffix_key: str = "single") -> str:
    """Build placeholder string for a section."""
    suffix = PLACEHOLDER_SUFFIXES.get(suffix_key, "")
    return "{{" + sec_id + suffix + "}}"


# ---------------------------------------------------------------------------
# Template functions
# ---------------------------------------------------------------------------


def _tpl_nav_bar(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    border = ds.get("colors", {}).get("border", "#e0e0e0")
    return (
        f'<section data-section="{sec_id}" class="mp-nav-bar"'
        f' style="background: {bg}; border-bottom: 1px solid {border};">'
        f'<div class="mp-container">{_ph(sec_id)}</div>'
        f'</section>'
    )


def _tpl_hero_centered(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-hero-centered"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container mp-text-center">{_ph(sec_id)}</div>'
        f'</section>'
    )


def _tpl_hero_split(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-hero-split"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container mp-grid-2">'
        f'<div class="mp-col">{_ph(sec_id, "text")}</div>'
        f'<div class="mp-col">{_ph(sec_id, "image")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_feature_grid(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("surface", "#f5f5f5")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    col_count = css_overrides.get("column_count", 3)
    grid_class = f"mp-grid-{min(col_count, 4)}"
    return (
        f'<section data-section="{sec_id}" class="mp-feature-grid"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="{grid_class}">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_testimonial_cards(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    col_count = css_overrides.get("column_count", 3)
    grid_class = f"mp-grid-{min(col_count, 4)}"
    return (
        f'<section data-section="{sec_id}" class="mp-testimonial-cards"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="{grid_class}">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_cta_banner(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("accent", "#0066cc")
    text_color = "#ffffff"
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-cta-banner"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container mp-text-center">{_ph(sec_id)}</div>'
        f'</section>'
    )


def _tpl_faq_list(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-faq-list"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="mp-faq-items">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_pricing_table(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("surface", "#f5f5f5")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    col_count = css_overrides.get("column_count", 3)
    grid_class = f"mp-grid-{min(col_count, 4)}"
    return (
        f'<section data-section="{sec_id}" class="mp-pricing-table"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="{grid_class}">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_logo_bar(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("surface", "#f5f5f5")
    text_color = ds.get("colors", {}).get("text_secondary", "#666666")
    return (
        f'<section data-section="{sec_id}" class="mp-logo-bar"'
        f' style="background: {bg}; color: {text_color}; padding: 40px 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="mp-flex-row mp-flex-center">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_stats_row(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    col_count = css_overrides.get("column_count", 4)
    grid_class = f"mp-grid-{min(col_count, 4)}"
    return (
        f'<section data-section="{sec_id}" class="mp-stats-row"'
        f' style="background: {bg}; color: {text_color}; padding: 50px 30px;">'
        f'<div class="mp-container">'
        f'<div class="mp-section-header">{_ph(sec_id, "header")}</div>'
        f'<div class="{grid_class} mp-text-center">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_content_block(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-content-block"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">{_ph(sec_id)}</div>'
        f'</section>'
    )


def _tpl_footer_columns(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    text_color = ds.get("colors", {}).get("background", "#ffffff")
    col_count = css_overrides.get("column_count", 4)
    grid_class = f"mp-grid-{min(col_count, 4)}"
    return (
        f'<section data-section="{sec_id}" class="mp-footer-columns"'
        f' style="background: {bg}; color: {text_color}; padding: 50px 30px;">'
        f'<div class="mp-container">'
        f'<div class="{grid_class}">{_ph(sec_id, "items")}</div>'
        f'</div>'
        f'</section>'
    )


def _tpl_generic(sec_id: str, ds: Dict, css_overrides: Dict) -> str:
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-generic"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">{_ph(sec_id)}</div>'
        f'</section>'
    )


# Template registry
_TEMPLATES = {
    "nav_bar": _tpl_nav_bar,
    "hero_centered": _tpl_hero_centered,
    "hero_split": _tpl_hero_split,
    "feature_grid": _tpl_feature_grid,
    "testimonial_cards": _tpl_testimonial_cards,
    "cta_banner": _tpl_cta_banner,
    "faq_list": _tpl_faq_list,
    "pricing_table": _tpl_pricing_table,
    "logo_bar": _tpl_logo_bar,
    "stats_row": _tpl_stats_row,
    "content_block": _tpl_content_block,
    "footer_columns": _tpl_footer_columns,
    "generic": _tpl_generic,
}


# ---------------------------------------------------------------------------
# Shared layout CSS (responsive)
# ---------------------------------------------------------------------------


def _build_shared_css(ds: Dict) -> str:
    """Build shared CSS classes for all templates.

    Uses mp-* prefix to avoid conflicts with original page CSS.
    Includes responsive breakpoint at 768px to stack columns on mobile.
    """
    gap = ds.get("spacing", {}).get("element_gap", "20px")
    group_gap = ds.get("spacing", {}).get("group_gap", "40px")
    heading_font = ds.get("typography", {}).get(
        "heading_font",
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    )
    body_font = ds.get("typography", {}).get(
        "body_font",
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    )
    h1_size = ds.get("typography", {}).get("h1_size", "3rem")
    h2_size = ds.get("typography", {}).get("h2_size", "2rem")
    h3_size = ds.get("typography", {}).get("h3_size", "1.5rem")
    body_size = ds.get("typography", {}).get("body_size", "1rem")
    line_height = ds.get("typography", {}).get("line_height", "1.7")
    accent = ds.get("colors", {}).get("accent", "#0066cc")
    cta = ds.get("colors", {}).get("cta", "#0066cc")
    border = ds.get("colors", {}).get("border", "#e0e0e0")

    return f"""<style>
/* Multipass template layout classes */
.mp-container {{ max-width: 1200px; margin: 0 auto; }}
.mp-text-center {{ text-align: center; }}
.mp-section-header {{ margin-bottom: {group_gap}; }}

/* Grid layouts */
.mp-grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: {gap}; }}
.mp-grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: {gap}; }}
.mp-grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: {gap}; }}

/* Flex layouts */
.mp-flex-row {{ display: flex; flex-wrap: wrap; gap: {gap}; }}
.mp-flex-center {{ justify-content: center; align-items: center; }}
.mp-col {{ min-width: 0; }}

/* Nav bar */
.mp-nav-bar {{ padding: 15px 30px; }}
.mp-nav-bar .mp-container {{ display: flex; align-items: center; justify-content: space-between; }}

/* Hero split */
.mp-hero-split .mp-grid-2 {{ align-items: center; }}

/* FAQ items */
.mp-faq-items {{ max-width: 800px; margin: 0 auto; }}
.mp-faq-item {{ padding: {gap} 0; border-bottom: 1px solid {border}; }}
.mp-faq-item h3 {{ margin: 0 0 8px 0; }}
.mp-faq-item p {{ margin: 0; }}

/* Cards */
.mp-feature-card, .mp-testimonial-card, .mp-pricing-card {{
    padding: {gap};
    border-radius: 8px;
    border: 1px solid {border};
}}
.mp-testimonial-card blockquote {{
    margin: 0 0 12px 0;
    font-style: italic;
}}
.mp-testimonial-card cite {{
    font-style: normal;
    font-weight: 600;
}}

/* Stats */
.mp-stat {{ padding: {gap}; }}
.mp-stat-number {{ font-size: 2.5rem; font-weight: 700; color: {accent}; display: block; }}
.mp-stat-label {{ font-size: 0.9rem; opacity: 0.8; display: block; }}

/* Logo bar */
.mp-logo-bar img {{ max-height: 48px; object-fit: contain; }}

/* Typography */
.mp-container h1 {{ font-family: {heading_font}; font-size: {h1_size}; line-height: 1.2; margin: 0 0 16px 0; }}
.mp-container h2 {{ font-family: {heading_font}; font-size: {h2_size}; line-height: 1.3; margin: 0 0 12px 0; }}
.mp-container h3 {{ font-family: {heading_font}; font-size: {h3_size}; line-height: 1.4; margin: 0 0 8px 0; }}
.mp-container p {{ font-family: {body_font}; font-size: {body_size}; line-height: {line_height}; margin: 0 0 12px 0; }}

/* CTA buttons */
.mp-container a, .mp-container button {{
    font-family: {body_font};
}}
.mp-cta-banner a, .mp-cta-banner button {{
    display: inline-block;
    padding: 12px 32px;
    background: #ffffff;
    color: {cta};
    border-radius: 6px;
    text-decoration: none;
    font-weight: 600;
}}

/* Footer */
.mp-footer-columns a {{ color: inherit; text-decoration: none; opacity: 0.8; }}
.mp-footer-columns a:hover {{ opacity: 1; }}

/* Responsive: stack columns on mobile */
@media (max-width: 768px) {{
    .mp-grid-2, .mp-grid-3, .mp-grid-4 {{
        grid-template-columns: 1fr;
    }}
    .mp-hero-split .mp-grid-2 {{
        grid-template-columns: 1fr;
    }}
    .mp-nav-bar .mp-container {{
        flex-direction: column;
        gap: 10px;
    }}
}}
</style>"""


# ---------------------------------------------------------------------------
# Skeleton builder
# ---------------------------------------------------------------------------


def build_skeleton_from_templates(
    sections: list,
    layout_map: Dict[str, Any],
    design_system: Dict,
    extracted_css: Optional[Any] = None,
) -> str:
    """Build complete skeleton HTML from per-section layout classifications.

    Args:
        sections: List of SegmenterSection objects.
        layout_map: Dict of sec_id -> LayoutHint (or dict with layout_type, etc.)
        design_system: Design system dict from Phase 0.
        extracted_css: Optional ExtractedCSS for component style overrides.

    Returns:
        Complete skeleton HTML string with mp-* layout classes and
        per-section sub-placeholders.
    """
    parts: List[str] = []

    # Add shared CSS block
    parts.append(_build_shared_css(design_system))

    # Build each section from its template
    for section in sections:
        sec_id = section.section_id
        hint = layout_map.get(sec_id)

        # Extract layout_type and css_overrides from hint
        if hint is None:
            layout_type = "generic"
            css_overrides = {}
        elif hasattr(hint, 'layout_type'):
            # LayoutHint dataclass
            layout_type = hint.layout_type
            css_overrides = {
                "column_count": hint.column_count if hasattr(hint, 'column_count') else 1,
                "text_position": hint.text_position if hasattr(hint, 'text_position') else "left",
            }
            if hasattr(hint, 'css_overrides') and hint.css_overrides:
                css_overrides.update(hint.css_overrides)
        elif isinstance(hint, dict):
            layout_type = hint.get("layout_type", "generic")
            css_overrides = hint.get("css_overrides", {})
            if "column_count" in hint:
                css_overrides["column_count"] = hint["column_count"]
            if "text_position" in hint:
                css_overrides["text_position"] = hint["text_position"]
        else:
            layout_type = "generic"
            css_overrides = {}

        # Validate layout_type
        if layout_type not in _TEMPLATES:
            logger.warning(f"Unknown layout_type '{layout_type}' for {sec_id}, using generic")
            layout_type = "generic"

        # Apply component style overrides from extracted CSS
        if extracted_css and hasattr(extracted_css, 'component_styles'):
            comp = extracted_css.component_styles
            if comp.button.get('border-radius'):
                css_overrides.setdefault('button_border_radius', comp.button['border-radius'])
            if comp.card.get('box-shadow'):
                css_overrides.setdefault('card_shadow', comp.card['box-shadow'])

        # Build section HTML
        template_fn = _TEMPLATES[layout_type]
        section_html = template_fn(sec_id, design_system, css_overrides)
        parts.append(section_html)

    return "\n".join(parts)


def build_generic_section(sec_id: str, content_html: str, ds: Optional[Dict] = None) -> str:
    """Build a generic section with content already injected.

    Used by content_assembler.py for coverage-check fallback.
    """
    if ds is None:
        ds = {}
    bg = ds.get("colors", {}).get("background", "#ffffff")
    text_color = ds.get("colors", {}).get("text_primary", "#1a1a1a")
    pad = ds.get("spacing", {}).get("section_padding_v", "70px")
    return (
        f'<section data-section="{sec_id}" class="mp-generic"'
        f' style="background: {bg}; color: {text_color}; padding: {pad} 30px;">'
        f'<div class="mp-container">{content_html}</div>'
        f'</section>'
    )
