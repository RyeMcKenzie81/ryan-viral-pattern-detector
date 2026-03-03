"""
Mockup Service — Generates standalone HTML/CSS mockup files from
landing page analysis and blueprint data.

Three generation modes (fallback chain):
1. AI Vision: Screenshot → Gemini → faithful HTML recreation with data-slot markers
2. Markdown: Page markdown → markdown-it → sanitized HTML
3. V1 Wireframe: Element detection → section-by-section pattern rendering

Two output modes:
- Analysis Mockup: Renders competitor page structure (from screenshot or elements)
- Blueprint Mockup: Swaps data-slot content with brand_mapping values
"""

import html as _html_module
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import bleach
from bleach.css_sanitizer import CSSSanitizer
import jinja2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS block sanitizer (for <style> block content — distinct from bleach inline)
# ---------------------------------------------------------------------------

_CSS_MAX_SIZE = 100_000  # 100KB cap for CSS blocks (AI-generated)
_CSS_MAX_SIZE_SURGERY = 2_500_000  # 2.5MB cap for surgery pipeline (preserves original page CSS)

# Safety-net CSS appended in blueprint generation for surgery-pipeline pages.
# Prevents catastrophic layout blow-up if CSS is partially truncated.
_SURGERY_CRITICAL_CSS = """
/* Surgery pipeline layout safety net */
html, body { max-width: 100vw !important; overflow-x: hidden !important; }
img, video, iframe { max-width: 100% !important; }
"""

# Patterns for dangerous CSS constructs
_STYLE_BREAKOUT_RE = re.compile(r'<\s*/\s*style\b', re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r'<!')
_HTML_TAG_RE = re.compile(r'<[a-zA-Z][^>]*>')
_CSS_IMPORT_RE = re.compile(r'@import\b[^;]*;?', re.IGNORECASE)
_CSS_CHARSET_RE = re.compile(r'@charset\b[^;]*;?', re.IGNORECASE)
_CSS_URL_RE = re.compile(
    r'\burl\s*\('
    r'(?:'
    r'"[^"]*"'       # double-quoted
    r"|'[^']*'"      # single-quoted
    r'|[^)]*'        # unquoted
    r')\)',
    re.IGNORECASE,
)
_CSS_EXPRESSION_RE = re.compile(r'\bexpression\s*\(', re.IGNORECASE)
_CSS_MOZ_BINDING_RE = re.compile(r'-moz-binding\s*:', re.IGNORECASE)
_CSS_BEHAVIOR_RE = re.compile(r'\bbehavior\s*:', re.IGNORECASE)


def _sanitize_css_block(raw_css: str, is_surgery_mode: bool = False) -> str:
    """Sanitize CSS content from <style> blocks.

    Strips known attack vectors while preserving layout-critical CSS
    (media queries, keyframes, pseudo-selectors, gradients).

    Args:
        raw_css: Raw CSS text.
        is_surgery_mode: When True, preserve url() values with https:// scheme
            (surgery pipeline preserves original page CSS with background images
            and font references that must be kept).

    Returns empty string if the block is fully rejected (breakout/HTML injection).
    """
    if not raw_css or not raw_css.strip():
        return ""

    # Cap size — surgery pipeline preserves original page CSS which can be
    # very large (1-2MB for Shopify/Replo pages); use a higher limit since
    # the surgery pipeline already sanitizes CSS in S3.
    max_size = _CSS_MAX_SIZE_SURGERY if is_surgery_mode else _CSS_MAX_SIZE
    if len(raw_css) > max_size:
        logger.warning(
            f"CSS block exceeds {max_size} bytes ({len(raw_css)}), truncating"
        )
        raw_css = raw_css[:max_size]

    # REJECT entire block if contains </style breakout
    if _STYLE_BREAKOUT_RE.search(raw_css):
        logger.warning("CSS block rejected: contains </style breakout pattern")
        return ""

    # REJECT if contains <! (HTML comments/CDATA) or <tag...> patterns
    # Skip for surgery mode: real-world CSS can legitimately contain tag-like
    # patterns (e.g. `content: "<br>"`, SVG data URIs). The surgery pipeline's
    # S3 already sanitizes CSS; these checks guard against AI-generated CSS.
    if not is_surgery_mode:
        if _HTML_COMMENT_RE.search(raw_css):
            logger.warning("CSS block rejected: contains <! HTML pattern")
            return ""
        if _HTML_TAG_RE.search(raw_css):
            logger.warning("CSS block rejected: contains HTML tag pattern")
            return ""

    # STRIP dangerous at-rules
    css = _CSS_IMPORT_RE.sub('', raw_css)
    css = _CSS_CHARSET_RE.sub('', css)

    # STRIP url() values — in surgery mode, preserve safe HTTPS urls
    if is_surgery_mode:
        css = _strip_unsafe_css_urls(css)
    else:
        for _ in range(10):
            new_css = _CSS_URL_RE.sub('/* url-stripped */', css)
            if new_css == css:
                break
            css = new_css

    # STRIP legacy JS vectors
    css = _CSS_EXPRESSION_RE.sub('/* expression-stripped */ (', css)
    css = _CSS_MOZ_BINDING_RE.sub('/* moz-binding-stripped */:', css)
    css = _CSS_BEHAVIOR_RE.sub('/* behavior-stripped */:', css)

    return css


# Regex to extract url value from url() for surgery-mode filtering
_CSS_URL_VALUE_RE = re.compile(
    r'\burl\s*\(\s*'
    r'(?:"([^"]*)"|\'([^\']*)\'|([^)]*?))'
    r'\s*\)',
    re.IGNORECASE,
)


def _strip_unsafe_css_urls(css: str) -> str:
    """Strip only unsafe url() values — keep HTTPS URLs.

    Surgery pipeline preserves original page CSS. Allow all https:// URLs
    (including CDNs). Block javascript:, data: > 1KB, and http:// schemes.
    """
    def _filter_url(match: re.Match) -> str:
        url_val = match.group(1) or match.group(2) or match.group(3) or ""
        url_val = url_val.strip()

        # Allow https:// URLs
        if url_val.startswith("https://"):
            return match.group(0)

        # Allow small data: URIs (inline SVG icons, etc.)
        if url_val.startswith("data:") and len(url_val) < 1024:
            return match.group(0)

        # Block everything else
        return "/* url-stripped */"

    return _CSS_URL_VALUE_RE.sub(_filter_url, css)


# ---------------------------------------------------------------------------
# url() post-sanitization for inline styles (parser-based)
# ---------------------------------------------------------------------------

# Reuse _CSS_URL_RE from above for inline style url() stripping

class _InlineStyleUrlStripper(HTMLParser):
    """HTMLParser that rewrites style attributes to strip url() values.

    Handles both style="..." and style='...' quoting, as well as
    case variations like STYLE=. Only modifies style attribute values,
    never touches visible text content.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts: list = []

    def _strip_url_from_style(self, style_value: str) -> str:
        """Strip url() from a style attribute value (run until stable)."""
        result = style_value
        for _ in range(10):
            new_result = _CSS_URL_RE.sub('/* url-stripped */', result)
            if new_result == result:
                break
            result = new_result
        return result

    def _rebuild_attrs(self, attrs: list) -> str:
        """Rebuild attribute string, stripping url() from style values."""
        parts = []
        for name, value in attrs:
            if value is None:
                parts.append(f' {name}')
            elif name.lower() == 'style':
                cleaned = self._strip_url_from_style(value)
                parts.append(f' {name}="{_html_module.escape(cleaned, quote=True)}"')
            else:
                parts.append(f' {name}="{_html_module.escape(value, quote=True)}"')
        return ''.join(parts)

    def handle_starttag(self, tag, attrs):
        self.parts.append(f'<{tag}{self._rebuild_attrs(attrs)}>')

    def handle_endtag(self, tag):
        self.parts.append(f'</{tag}>')

    def handle_startendtag(self, tag, attrs):
        self.parts.append(f'<{tag}{self._rebuild_attrs(attrs)} />')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f'&{name};')

    def handle_charref(self, name):
        self.parts.append(f'&#{name};')

    def handle_comment(self, data):
        self.parts.append(f'<!--{data}-->')

    def handle_decl(self, decl):
        self.parts.append(f'<!{decl}>')

    def unknown_decl(self, data):
        self.parts.append(f'<!{data}>')

    def get_result(self) -> str:
        return ''.join(self.parts)


class _SurgeryInlineStyleUrlStripper(_InlineStyleUrlStripper):
    """Like _InlineStyleUrlStripper but only strips unsafe URLs (http, javascript, large data).

    Preserves HTTPS and small data: URIs for surgery pipeline output.
    """

    def _strip_url_from_style(self, style_value: str) -> str:
        return _strip_unsafe_css_urls(style_value)


def _strip_url_from_inline_styles(html: str, is_surgery_mode: bool = False) -> str:
    """Strip url() only within style attribute values.

    Uses parser-based style attribute rewriting to handle all quoting
    styles and edge cases. Does NOT alter visible text content.

    Args:
        html: HTML string.
        is_surgery_mode: When True, preserve HTTPS url() values in inline styles.
    """
    if 'url(' not in html.lower():
        return html  # Fast path: no url() anywhere

    if is_surgery_mode:
        # Apply safe URL filtering (keep HTTPS, block http/javascript/large data)
        stripper = _SurgeryInlineStyleUrlStripper()
        try:
            stripper.feed(html)
            return stripper.get_result()
        except Exception:
            logger.warning("HTMLParser failed in surgery inline style filter, returning as-is")
            return html

    stripper = _InlineStyleUrlStripper()
    try:
        stripper.feed(html)
        return stripper.get_result()
    except Exception:
        # Parser failure — fall back to returning html as-is
        logger.warning("HTMLParser failed in _strip_url_from_inline_styles, returning as-is")
        return html

# ---------------------------------------------------------------------------
# HTML sanitization allowlists
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = [
    # Structure
    "html", "head", "body", "title", "meta",
    # Layout
    "div", "span", "section", "header", "footer", "nav", "main", "article", "aside",
    # Text
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "u", "small", "sup", "sub",
    "br", "hr", "blockquote", "pre", "code",
    # Lists
    "ul", "ol", "li",
    # Definition lists
    "dl", "dt", "dd",
    # Tables
    "table", "tr", "td", "th", "thead", "tbody",
    # Media (images only, no external loading)
    "img", "figure", "figcaption", "picture", "source",
    # SVG (safe subset — dangerous elements stripped in S0 sanitizer)
    "svg", "path", "g", "circle", "rect", "line", "polyline", "polygon",
    "ellipse", "text", "tspan", "defs", "clipPath", "clippath", "mask",
    "symbol", "title",
    # Interactive / Disclosure
    "a", "button", "details", "summary",
    # Forms (display only)
    "input", "label", "select", "option", "textarea", "form",
    # External resources (font CDN links preserved by surgery pipeline)
    "link",
]

_ALLOWED_ATTRS = {
    "*": ["class", "id", "style", "data-slot", "data-section", "data-pipeline",
          "data-listicle-prefix", "data-listicle-start", "data-listicle-count", "data-listicle-style",
          "role", "aria-label"],
    "a": ["href", "target", "rel"],
    "link": ["href", "rel", "type", "crossorigin"],
    "img": [
        "src", "alt", "width", "height", "srcset", "sizes", "loading", "data-bg-image",
        "data-src", "data-srcset", "data-lazy-src",
    ],
    "source": ["srcset", "sizes", "media", "type"],
    "picture": [],
    "meta": ["charset", "name", "content"],
    "input": ["type", "placeholder", "value", "name"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    # SVG attributes
    "svg": ["viewBox", "viewbox", "xmlns", "width", "height", "fill", "stroke"],
    "path": ["d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"],
    "g": ["transform", "fill", "stroke"],
    "circle": ["cx", "cy", "r", "fill", "stroke"],
    "rect": ["x", "y", "width", "height", "rx", "ry", "fill", "stroke"],
    "line": ["x1", "y1", "x2", "y2", "stroke"],
    "polyline": ["points", "fill", "stroke"],
    "polygon": ["points", "fill", "stroke"],
    "ellipse": ["cx", "cy", "rx", "ry", "fill", "stroke"],
    "clipPath": ["id"],
    "clippath": ["id"],
    "symbol": ["id", "viewBox", "viewbox"],
}

_ALLOWED_CSS_PROPERTIES = [
    # Text
    "color", "font-size", "font-weight", "font-family", "font-style",
    "text-align", "text-decoration", "text-transform", "line-height",
    "letter-spacing", "word-spacing", "white-space",
    # Background
    "background", "background-color", "background-image", "background-size",
    "background-position", "background-repeat",
    # Box model
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "border", "border-radius", "border-color", "border-width", "border-style",
    "border-top", "border-bottom", "border-left", "border-right",
    "box-sizing",
    # Sizing
    "width", "max-width", "min-width", "height", "max-height", "min-height",
    # Flexbox
    "display", "flex-direction", "justify-content", "align-items", "gap",
    "flex-wrap", "flex", "flex-grow", "flex-shrink", "flex-basis",
    "align-self", "order",
    # Grid
    "grid-template-columns", "grid-template-rows", "grid-gap",
    "grid-column", "grid-row",
    # Position & layout
    "position", "top", "bottom", "left", "right", "z-index",
    "float", "clear", "vertical-align",
    # Visual
    "overflow", "opacity", "box-shadow", "transform",
    "object-fit", "object-position",
    "aspect-ratio", "text-shadow", "cursor",
    # Lists
    "list-style", "list-style-type",
    # Grid extras
    "row-gap", "column-gap",
]

_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=_ALLOWED_CSS_PROPERTIES)

# ---------------------------------------------------------------------------
# Element Name → Visual Pattern mapping (34 elements → 12 patterns)
# ---------------------------------------------------------------------------

# Hero elements that get consumed into the composite hero_banner in above_the_fold
_HERO_ELEMENTS = frozenset([
    "headline",
    "subheadline",
    "hero image / video",
    "primary cta (above fold)",
])

ELEMENT_VISUAL_MAP: Dict[str, str] = {
    # Section 1: Above the Fold
    "navigation bar & logo": "nav_bar",
    "attention bar / banner": "announcement_bar",
    "headline": "hero_banner",
    "subheadline": "hero_banner",
    "hero image / video": "hero_banner",
    "core benefits callout": "icon_grid",
    "initial trust indicators": "icon_grid",
    "primary cta (above fold)": "hero_banner",

    # Section 2: Education & Persuasion
    "pre-lead / authority section": "text_block",
    "problem amplification": "text_block",
    "bridge section": "text_block",
    "mechanism explanation": "text_block",
    "avatar callout": "text_block",

    # Section 3: Product Reveal & Features
    "product introduction / reveal": "text_block",
    "ingredient / feature breakdown": "feature_grid",
    "competitive differentiation": "comparison_table",
    "how it works / usage instructions": "feature_grid",
    "results timeline": "text_block",
    "secondary benefits / use cases": "text_block",

    # Section 4: Social Proof
    "text testimonials": "testimonial_block",
    "video testimonials": "testimonial_block",
    "usage statistics": "testimonial_block",
    "founder / brand story": "text_block",

    # Section 5: Conversion & Offer
    "value stack / offer presentation": "pricing_block",
    "pricing / package options": "pricing_block",
    "risk reversal / guarantee": "pricing_block",
    "urgency & scarcity": "pricing_block",
    "payment security indicators (near pricing)": "icon_grid",
    "repeated offer stack": "pricing_block",

    # Section 6: Closing & Trust
    "faq / objection handling": "text_block",
    "final cta section": "final_cta_block",
    "about the brand (bottom)": "text_block",
    "footer / legal & compliance": "footer_legal_block",
    "email capture / newsletter": "email_capture_block",
}

# Canonical section → accent color
SECTION_ACCENT_COLORS: Dict[str, str] = {
    "above_the_fold": "#3b82f6",
    "education_and_persuasion": "#8b5cf6",
    "product_reveal_and_features": "#10b981",
    "social_proof": "#f59e0b",
    "conversion_and_offer": "#ef4444",
    "closing_and_trust": "#6366f1",
}
_DEFAULT_ACCENT = "#94a3b8"

# Regex for validating CSS color values
_CSS_COLOR_RE = re.compile(
    r"^("
    r"#[0-9a-fA-F]{3,8}"
    r"|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)"
    r"|rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)"
    r"|hsl\(\s*\d{1,3}\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*\)"
    r"|[a-zA-Z]{3,20}"
    r")$"
)


def _sanitize_dashes(text: str) -> str:
    """Replace em dashes and en dashes with regular dashes/commas."""
    text = text.replace("\u2014", " - ")   # em dash
    text = text.replace("\u2013", "-")     # en dash
    return text


@dataclass
class _SlotRewriteConfig:
    """Configuration for a slot rewrite pipeline run."""
    strategy: str                          # "slot_constrained" or "section_guided"
    system_prompt: str                     # composed base + addendum
    regen_prompt: str                      # strategy-specific regen prompt
    sections: List[Dict]                   # ordered section groups with slots
    page_strategy: Dict                    # awareness_adaptation, tone_direction, primary_angle
    brand_data: Dict                       # name, voice_tone, benefits, etc.
    slot_specs_lookup: Dict[str, Dict]     # slot_name -> {max_words, type, ...}
    slot_contents: Dict[str, str] = field(default_factory=dict)  # for fallback fills
    listicle_data: Dict = field(default_factory=dict)  # listicle detection: {slot_name: prefix, ...}


class MockupService:
    """Generates standalone HTML/CSS mockup files from analysis and blueprint data."""

    _jinja_env: Optional[jinja2.Environment] = None

    def __init__(self):
        self._usage_tracker = None
        self._user_id: Optional[str] = None
        self._organization_id: Optional[str] = None
        #: When True, preserve HTTPS url() values in CSS sanitization
        #: (surgery pipeline output has original page CSS that should keep
        #: background images and font references).
        self.is_surgery_mode: bool = False

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def set_tracking_context(self, usage_tracker, user_id: str, organization_id: str):
        """Set usage tracking context for AI calls."""
        self._usage_tracker = usage_tracker
        self._user_id = user_id
        self._organization_id = organization_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def regenerate_selected_slots(
        self,
        current_mockup_html: str,
        slots_to_regenerate: List[str],
        blueprint: Dict,
        brand_profile: Dict,
        rewrite_strategy: str = "slot_constrained",
    ) -> str:
        """Selectively regenerate specific slots while preserving all others.

        Splits slots into frozen (read-only context) and regenerate groups,
        then runs the AI with both groups for coherent partial rewriting.
        Operates on the full mockup HTML (no strip-and-rewrap) to preserve
        the wrapper, CSS, and metadata bar.

        Args:
            current_mockup_html: Full mockup HTML including wrapper/CSS.
            slots_to_regenerate: List of slot names to rewrite.
            blueprint: Reconstruction blueprint dict.
            brand_profile: Full brand profile dict.
            rewrite_strategy: "slot_constrained" (default).

        Returns:
            Updated full mockup HTML with only the selected slots rewritten.
        """
        if not slots_to_regenerate:
            return current_mockup_html

        # 1. Extract slot content from stripped body (for AI payload)
        body, _ = self._extract_page_css_and_strip(current_mockup_html)
        all_slot_contents = self._extract_slots_with_content(body)

        if not all_slot_contents:
            logger.warning("No slots found in mockup HTML for selective regen")
            return current_mockup_html

        # 2. Validate requested slots exist
        valid_regen = [s for s in slots_to_regenerate if s in all_slot_contents]
        if not valid_regen:
            logger.warning(
                f"None of the requested slots exist: {slots_to_regenerate[:5]}"
            )
            return current_mockup_html

        regen_set = set(valid_regen)
        frozen_names = [s for s in all_slot_contents if s not in regen_set]

        logger.info(
            f"Selective regen: {len(valid_regen)} slots to regenerate, "
            f"{len(frozen_names)} frozen"
        )

        # 3. Map slots to sections
        slot_sections = self._map_slots_to_sections(body, blueprint)

        # 4. Build brand context
        brand_data, page_strategy = self._build_shared_brand_context(
            blueprint, brand_profile
        )

        # 5. Build frozen slot data (read-only context for AI)
        frozen_slots: List[Dict] = []
        for name in frozen_names:
            ctx = slot_sections.get(name, {})
            frozen_slots.append({
                "name": name,
                "section_name": ctx.get("section_name", "global"),
                "type": ctx.get("slot_type", self._infer_slot_type(name)),
                "content": all_slot_contents[name],
            })

        # 6. Build regenerate section groups (matching existing pattern)
        section_groups: Dict[str, dict] = {}
        for slot_name in valid_regen:
            content = all_slot_contents[slot_name]
            ctx = slot_sections.get(slot_name, {})
            sec_key = ctx.get("section_name", "global")
            flow = ctx.get("flow_order", 999)
            group_key = f"{flow:04d}_{sec_key}"

            if group_key not in section_groups:
                section_groups[group_key] = {
                    "section_name": sec_key,
                    "copy_direction": ctx.get("copy_direction", ""),
                    "brand_data": ctx.get("brand_mapping", {}),
                    "slots": [],
                }

            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            word_count = len(content.split()) if content else 0
            char_count = len(content)
            length_spec = self._compute_slot_length_spec(
                slot_type, word_count, char_count
            )

            section_groups[group_key]["slots"].append({
                "name": slot_name,
                "type": slot_type,
                "current": content,
                "max_words": length_spec["max_words"],
                "original_words": length_spec["original_words"],
                "original_chars": length_spec["original_chars"],
                "length_note": length_spec["length_note"],
            })

        ordered_sections = [section_groups[k] for k in sorted(section_groups.keys())]

        # 7. Handle listicle prefixes
        listicle_data = self._detect_listicle_structure(
            all_slot_contents, slot_sections
        )
        listicle_prefixes = listicle_data.get("prefixes", {})
        if listicle_prefixes:
            for g in ordered_sections:
                for s in g["slots"]:
                    if s["name"] in listicle_prefixes:
                        s["prefix"] = listicle_prefixes[s["name"]]

        # 8. Build slot_specs_lookup for regen validation
        slot_specs_lookup: Dict[str, Dict] = {}
        for g in ordered_sections:
            for s in g["slots"]:
                spec = {
                    "max_words": s["max_words"],
                    "type": s["type"],
                    "original_words": s.get("original_words", 0),
                    "length_note": s.get("length_note", ""),
                }
                if s["name"] in listicle_prefixes:
                    spec["prefix"] = listicle_prefixes[s["name"]]
                slot_specs_lookup[s["name"]] = spec

        # 9. Run selective regen AI call
        regen_result = self._execute_selective_regen(
            frozen_slots=frozen_slots,
            regenerate_sections=ordered_sections,
            brand_data=brand_data,
            page_strategy=page_strategy,
            slot_specs_lookup=slot_specs_lookup,
            slot_contents=all_slot_contents,
            listicle_data=listicle_data,
        )

        # 10. Apply regen results on FULL mockup HTML (no strip-and-rewrap)
        # _template_swap only replaces slots present in slot_map, so frozen
        # slots are naturally preserved.
        updated_html = self._template_swap(
            current_mockup_html,
            blueprint,
            brand_profile=None,
            slot_map=regen_result,
            apply_brand_colors=False,
        )

        logger.info(
            f"Selective regen complete: replaced {len(regen_result)} slots "
            f"in mockup HTML ({len(current_mockup_html)} -> {len(updated_html)} chars)"
        )
        return updated_html

    def generate_analysis_mockup(
        self,
        screenshot_b64: Optional[str] = None,
        element_detection: Optional[Dict[str, Any]] = None,
        classification: Optional[Dict[str, Any]] = None,
        page_markdown: Optional[str] = None,
        page_url: Optional[str] = None,
        use_multipass: bool = False,
        progress_callback: Optional[Any] = None,
        page_html: Optional[str] = None,
    ) -> str:
        """Generate a faithful HTML recreation of the analyzed page.

        Fallback chain: screenshot→AI vision > page_markdown→HTML > V1 wireframe.

        Args:
            screenshot_b64: Optional base64 screenshot for AI vision recreation
            element_detection: Skill 2 output (element_detection dict, wrapped or unwrapped)
            classification: Skill 1 output (page_classifier dict, wrapped or unwrapped)
            page_markdown: Optional page markdown for fallback rendering
            page_url: Optional page URL for resolving relative image URLs
            use_multipass: If True, use 5-phase multipass pipeline (~60s, higher fidelity)
            progress_callback: Optional callable(phase: int, message: str) for progress
            page_html: Optional full page HTML for multipass v4 image/CSS extraction

        Returns:
            Standalone HTML string
        """
        # Reset surgery mode flag (set by _generate_via_multipass if surgery runs)
        self.is_surgery_mode = False

        if screenshot_b64 and use_multipass:
            raw_html = self._generate_via_multipass(
                screenshot_b64,
                page_markdown=page_markdown,
                page_url=page_url,
                element_detection=element_detection,
                progress_callback=progress_callback,
                page_html=page_html,
            )
        elif screenshot_b64:
            raw_html = self._generate_via_ai_vision(
                screenshot_b64,
                page_markdown=page_markdown,
                page_url=page_url,
            )
        else:
            raw_html = None

        if raw_html is not None:
            # SINGLE post-processing pipeline for BOTH paths
            body_html, sanitized_css = self._extract_and_sanitize_css(raw_html)
            html = self._sanitize_html(body_html)

            # Validate HTML completeness
            is_complete, issues = self._validate_html_completeness(html)
            if not is_complete:
                logger.warning(f"HTML completeness issues: {issues}")
                if page_markdown:
                    logger.warning(
                        "Truncation fallback to markdown - "
                        "blueprint slot targeting unavailable"
                    )
                    fallback_html = self._markdown_to_html(page_markdown)
                    html = self._sanitize_html(fallback_html)
                    sanitized_css = ""  # Markdown fallback has no CSS

            # Validate slot coverage (retry once if unusable, single-pass only)
            severity, report = self._validate_analysis_slots(html)

            # CATASTROPHIC ESCAPE (multipass only)
            if use_multipass and (severity == "unusable" or not is_complete):
                from viraltracker.core.observability import get_logfire
                _lf = get_logfire()
                _lf.warning(
                    "Multipass CATASTROPHIC ESCAPE: severity={severity}, complete={is_complete}, "
                    "falling back to single-pass",
                    severity=severity,
                    is_complete=is_complete,
                )
                logger.warning(
                    "Multipass produced unusable artifact (severity=%s, complete=%s), "
                    "falling back to single-pass", severity, is_complete
                )
                self.is_surgery_mode = False  # Reset: AI vision fallback is not surgery
                raw_html = self._generate_via_ai_vision(
                    screenshot_b64,
                    page_markdown=page_markdown,
                    page_url=page_url,
                )
                body_html, sanitized_css = self._extract_and_sanitize_css(raw_html)
                html = self._sanitize_html(body_html)
                is_complete, issues = self._validate_html_completeness(html)
                severity, report = self._validate_analysis_slots(html)

            if not use_multipass and severity == "unusable" and not getattr(self, '_slot_retry_used', False):
                logger.info(f"Slot validation unusable, retrying with reinforced prompt")
                self._slot_retry_used = True
                try:
                    retry_html = self._generate_via_ai_vision(
                        screenshot_b64,
                        page_markdown=page_markdown,
                        reinforce_slots=True,
                        page_url=page_url,
                    )
                    retry_body, retry_css = self._extract_and_sanitize_css(retry_html)
                    retry_sanitized = self._sanitize_html(retry_body)
                    retry_severity, retry_report = self._validate_analysis_slots(retry_sanitized)
                    if retry_severity != "unusable":
                        html = retry_sanitized
                        sanitized_css = retry_css
                        logger.info(f"Slot retry improved: {retry_report}")
                    else:
                        logger.warning(f"Slot retry still unusable, using original")
                except Exception as e:
                    logger.warning(f"Slot retry failed: {e}, using original")
                finally:
                    self._slot_retry_used = False
            elif severity == "unusable":
                logger.warning(f"Slot validation: {report}")

            # Content fidelity check (logs warnings, does not block)
            if page_markdown:
                self._verify_content_fidelity(html, page_markdown)

            return self._wrap_mockup(html, classification, mode="analysis", page_css=sanitized_css,
                                    is_surgery=self.is_surgery_mode)
        elif page_markdown:
            raw_html = self._markdown_to_html(page_markdown)
            html = self._sanitize_html(raw_html)
            return self._wrap_mockup(html, classification, mode="analysis")
        else:
            # V1 fallback: wireframe from element_detection
            sections = self._normalize_elements(element_detection or {})
            return self._render_html(
                sections=sections,
                classification=classification,
                mode="analysis",
            )

    def generate_blueprint_mockup(
        self,
        blueprint: Dict[str, Any],
        analysis_mockup_html: Optional[str] = None,
        classification: Optional[Dict[str, Any]] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
        source_url: Optional[str] = None,
        rewrite_strategy: str = "slot_constrained",
    ) -> Optional[str]:
        """Generate blueprint mockup by rewriting analysis HTML with brand copy.

        Uses a slot-based pipeline: extract slot text, send structured JSON to AI,
        then programmatically inject rewritten text into the untouched template HTML.
        Also replaces competitor brand name in non-slot text.

        Args:
            blueprint: Reconstruction blueprint with strategic directions.
            analysis_mockup_html: Full analysis mockup HTML (with data-slot markers).
            classification: Page classification data.
            brand_profile: Full brand profile from BrandProfileService.
            source_url: URL of the competitor page (for competitor name extraction).
            rewrite_strategy: "slot_constrained" (default, runtime length enforcement)
                or "section_guided" (blueprint-level space budget).

        Returns None if no analysis HTML is available.
        """
        if not analysis_mockup_html:
            logger.warning(
                "No analysis_mockup_html for blueprint mockup; "
                "skipping V1 fallback to prevent instruction leak."
            )
            return None

        self.is_surgery_mode = 'data-pipeline="surgery"' in analysis_mockup_html
        page_body, page_css = self._extract_page_css_and_strip(analysis_mockup_html)

        # Append safety-net overflow rules for surgery pages (defense-in-depth)
        if self.is_surgery_mode and page_css:
            page_css = page_css + "\n" + _SURGERY_CRITICAL_CSS

        # Strip Shopify theme chrome (header, footer, nav, mega menu, overlay)
        # that survives surgery pipeline but renders as unstyled junk
        page_body = self._strip_shopify_chrome(page_body)

        rewritten_body = page_body
        if brand_profile and page_body.strip():
            try:
                brand_name_str = (brand_profile.get("brand_basics") or {}).get("name", "")
                logger.info(
                    f"Starting slot-based rewrite for blueprint mockup "
                    f"(brand={brand_name_str or '?'}, html_len={len(page_body)})"
                )

                # 1. Extract slot names + current text content
                slot_contents = self._extract_slots_with_content(page_body)
                logger.info(f"Extracted {len(slot_contents)} slots with content")

                # 1b. Compute length metadata from extracted text
                slot_metadata = {
                    k: {"word_count": len(v.split()) if v else 0, "char_count": len(v)}
                    for k, v in slot_contents.items()
                }

                # 2. Strip competitor brand name AND product name from template
                competitor_name, competitor_product = self._extract_competitor_name(
                    blueprint, source_url=source_url, html=analysis_mockup_html,
                    classification=classification,
                )

                rewritten_body = page_body
                if competitor_name and brand_name_str:
                    logger.info(f"Replacing competitor brand '{competitor_name}' with '{brand_name_str}'")
                    rewritten_body = self._replace_competitor_brand(
                        rewritten_body, competitor_name, brand_name_str
                    )

                # 2b. Replace product name if different from brand name
                if (competitor_product
                        and competitor_product.lower() != (competitor_name or "").lower()
                        and brand_name_str):
                    brand_product = (brand_profile.get("brand_basics") or {}).get(
                        "product_name", brand_name_str
                    )
                    logger.info(f"Replacing competitor product '{competitor_product}' with '{brand_product}'")
                    rewritten_body = self._replace_competitor_brand(
                        rewritten_body, competitor_product, brand_product
                    )

                # 2c. Scan for recurring abbreviations of the competitor name
                if competitor_name or competitor_product:
                    ref_name = competitor_product or competitor_name
                    brand_initials = ''.join(w[0].upper() for w in ref_name.split() if w)
                    if len(brand_initials) >= 2:
                        visible_text = re.sub(r'<[^>]+>', ' ', rewritten_body)
                        abbrev_count = len(re.findall(r'\b' + re.escape(brand_initials) + r'\b', visible_text))
                        if abbrev_count >= 3:
                            brand_abbrev = ''.join(w[0].upper() for w in brand_name_str.split() if w) or brand_name_str
                            logger.info(f"Replacing abbreviation '{brand_initials}' ({abbrev_count}x) with '{brand_abbrev}'")
                            rewritten_body = self._replace_competitor_brand(
                                rewritten_body, brand_initials, brand_abbrev
                            )

                if slot_contents:
                    # 3. Map slots to blueprint sections
                    slot_sections = self._map_slots_to_sections(page_body, blueprint)

                    # 3b. Extract pre-computed listicle data from surgery HTML
                    listicle_from_html = (
                        self._extract_listicle_from_html(rewritten_body)
                        if self.is_surgery_mode else {}
                    )

                    # 4. AI rewrite: JSON in, JSON out (no HTML sent to AI)
                    rewritten_map = self._rewrite_slots_for_brand(
                        slot_contents, slot_sections, blueprint, brand_profile,
                        slot_metadata=slot_metadata,
                        rewrite_strategy=rewrite_strategy,
                        listicle_from_html=listicle_from_html,
                    )

                    # 5. Programmatic slot injection (deterministic, no AI risk)
                    rewritten_body = self._template_swap(
                        rewritten_body, blueprint, brand_profile, slot_map=rewritten_map
                    )
                    logger.info("Slot-based rewrite completed successfully")
                else:
                    logger.warning("No data-slot elements found — brand name replace only")

            except Exception as e:
                logger.error(f"Slot-based rewrite failed: {e}, using analysis HTML as fallback")
                rewritten_body = page_body
        elif brand_profile:
            logger.warning("Stripped page body is empty — skipping rewrite")
        else:
            logger.info(
                "No brand_profile provided — skipping rewrite, "
                "using stripped analysis HTML as fallback"
            )

        inner = self._sanitize_html(rewritten_body)
        return self._wrap_mockup(inner, classification, mode="blueprint", page_css=page_css)

    # ------------------------------------------------------------------
    # Normalization — Element Detection (Phase 1)
    # ------------------------------------------------------------------

    def _normalize_elements(self, element_detection: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Transform Skill 2 output into a flat list of mockup sections.

        Handles wrapped/unwrapped input, hero grouping, and unknown element fallback.
        """
        # Unwrap if needed
        ed = element_detection
        if "element_detection" in ed:
            ed = ed["element_detection"]

        raw_sections = ed.get("sections", {})
        cta_inventory = ed.get("cta_inventory", [])

        result = []
        section_order = [
            "above_the_fold",
            "education_and_persuasion",
            "product_reveal_and_features",
            "social_proof",
            "conversion_and_offer",
            "closing_and_trust",
        ]

        for section_name in section_order:
            section_data = raw_sections.get(section_name, {})

            # Handle both list and dict shapes
            if isinstance(section_data, list):
                elements_found = section_data
            else:
                elements_found = section_data.get("elements_found", [])

            if not elements_found:
                continue

            accent_color = SECTION_ACCENT_COLORS.get(section_name, _DEFAULT_ACCENT)

            # Process elements for this section
            mockup_elements = []
            hero_parts = {}  # Collect hero elements for grouping

            for elem in elements_found:
                el_name = self._canonicalize_element_name(
                    elem.get("element_name", "")
                )
                el_type = elem.get("element_type", "")
                content_summary = elem.get("content_summary", "")
                quality_notes = elem.get("quality_notes", "")

                visual_pattern = self._assign_visual_pattern(el_name, el_type)

                element_data = {
                    "element_name": elem.get("element_name", el_name),
                    "element_name_canonical": el_name,
                    "element_type": el_type,
                    "visual_pattern": visual_pattern,
                    "content_summary": content_summary,
                    "quality_notes": quality_notes,
                    "mode": "analysis",
                }

                # In above_the_fold, group hero elements into a composite
                if section_name == "above_the_fold" and el_name in _HERO_ELEMENTS:
                    hero_parts[el_name] = element_data
                else:
                    mockup_elements.append(element_data)

            # Build composite hero_banner from collected parts
            if hero_parts:
                hero_element = self._build_hero_composite(hero_parts, cta_inventory)
                # Insert hero at the beginning (after nav/announcement if present)
                insert_idx = 0
                for i, el in enumerate(mockup_elements):
                    if el["visual_pattern"] in ("nav_bar", "announcement_bar"):
                        insert_idx = i + 1
                mockup_elements.insert(insert_idx, hero_element)

            if mockup_elements:
                result.append({
                    "section_name": section_name,
                    "accent_color": accent_color,
                    "elements": mockup_elements,
                })

        return result

    def _build_hero_composite(
        self,
        hero_parts: Dict[str, Dict],
        cta_inventory: List[Dict],
    ) -> Dict[str, Any]:
        """Build a composite hero_banner element from individual hero parts."""
        headline = hero_parts.get("headline", {})
        subheadline = hero_parts.get("subheadline", {})
        hero_image = hero_parts.get("hero image / video", {})
        primary_cta = hero_parts.get("primary cta (above fold)", {})

        # Find the first CTA button text from inventory
        cta_text = ""
        if primary_cta.get("content_summary"):
            cta_text = primary_cta["content_summary"]
        elif cta_inventory:
            cta_text = cta_inventory[0].get("button_text", "Shop Now")

        return {
            "element_name": "Hero Section",
            "element_name_canonical": "hero_banner",
            "element_type": hero_image.get("element_type", "product_hero_shot"),
            "visual_pattern": "hero_banner",
            "content_summary": headline.get("content_summary", ""),
            "quality_notes": "",
            "mode": "analysis",
            "hero_headline": headline.get("content_summary", "Your Headline Here"),
            "hero_subheadline": subheadline.get("content_summary", ""),
            "hero_image_type": hero_image.get("element_type", "product_hero_shot"),
            "hero_cta_text": cta_text or "Shop Now",
        }

    # ------------------------------------------------------------------
    # Normalization — Blueprint (Phase 2)
    # ------------------------------------------------------------------

    def _normalize_blueprint_sections(self, blueprint: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Transform Skill 5 output into a flat list of mockup sections.

        Handles wrapped/unwrapped input, bonus sections, ordering by flow_order.
        """
        # Unwrap if needed
        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]

        raw_sections = rb.get("sections", [])
        bonus_sections = rb.get("bonus_sections", [])
        strategy = rb.get("strategy_summary", {})

        # Merge sections + bonus with section_name defaults for bonus
        all_sections = []

        for s in raw_sections:
            all_sections.append(s)

        for i, s in enumerate(bonus_sections):
            if not s.get("section_name"):
                s["section_name"] = f"bonus_{s.get('flow_order', i + 100)}"
            s["_is_bonus"] = True
            all_sections.append(s)

        # Sort by flow_order (int parse with fallback)
        def sort_key(s):
            fo = s.get("flow_order", 999)
            try:
                return int(fo)
            except (TypeError, ValueError):
                return 999

        all_sections.sort(key=sort_key)

        # Group by section_name for accent colors
        result = []
        current_section_name = None
        current_elements = []

        for s in all_sections:
            section_name = s.get("section_name", "unknown")
            accent_color = SECTION_ACCENT_COLORS.get(section_name, _DEFAULT_ACCENT)

            content_status = s.get("content_status", "populated")
            brand_mapping = s.get("brand_mapping", {})
            copy_direction = s.get("copy_direction", "")
            element_type = s.get("element_type", "Unknown")
            action_items = s.get("action_items", [])
            is_bonus = s.get("_is_bonus", False)

            # Determine visual pattern from element_type
            el_name_canonical = self._canonicalize_element_name(element_type)
            visual_pattern = self._assign_visual_pattern(el_name_canonical, element_type)

            element_data = {
                "element_name": element_type,
                "element_name_canonical": el_name_canonical,
                "element_type": s.get("competitor_subtype", element_type),
                "visual_pattern": visual_pattern,
                "content_summary": copy_direction,
                "mode": "blueprint",
                "content_status": content_status,
                "brand_mapping": brand_mapping,
                "copy_direction": copy_direction,
                "action_items": action_items,
                "is_bonus": is_bonus,
                "competitor_approach": s.get("competitor_approach", ""),
                "gap_note": s.get("gap_note", ""),
                "flow_order": s.get("flow_order", ""),
            }

            # Each blueprint section becomes its own section in the mockup
            result.append({
                "section_name": section_name,
                "accent_color": accent_color,
                "elements": [element_data],
                "is_bonus": is_bonus,
            })

        return result

    # ------------------------------------------------------------------
    # Brand Style Extraction
    # ------------------------------------------------------------------

    def _extract_brand_style(self, brand_profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        """Extract and validate brand colors from profile.

        Returns dict with validated CSS color values, or None if no valid colors found.
        """
        if not brand_profile:
            return None

        brand_basics = brand_profile.get("brand_basics", {})
        colors = brand_basics.get("colors", {})

        if not colors or not isinstance(colors, dict):
            return None

        validated = {}
        for key, value in colors.items():
            if isinstance(value, str) and _CSS_COLOR_RE.match(value.strip()):
                validated[key] = value.strip()

        return validated if validated else None

    # ------------------------------------------------------------------
    # Visual Pattern Assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _canonicalize_element_name(name: str) -> str:
        """Normalize element name for mapping lookup.

        Lowercases, strips whitespace, collapses multiple spaces,
        strips trailing punctuation.
        """
        if not name:
            return ""
        name = name.lower().strip()
        name = re.sub(r"\s+", " ", name)
        name = re.sub(r"[.,:;!?]+$", "", name)
        # Normalize slash spacing: "hero image/video" → "hero image / video"
        name = re.sub(r"\s*/\s*", " / ", name)
        return name

    def _assign_visual_pattern(self, element_name: str, element_type: str) -> str:
        """Look up visual pattern for an element name, falling back to text_block."""
        canonical = self._canonicalize_element_name(element_name)
        return ELEMENT_VISUAL_MAP.get(canonical, "text_block")

    # ------------------------------------------------------------------
    # HTML Sanitization
    # ------------------------------------------------------------------

    def _sanitize_html(self, raw_html: str) -> str:
        """Sanitize AI-generated HTML. Strips scripts, iframes, event handlers, dangerous CSS.

        Uses bleach with tag/attr allowlist + CSSSanitizer for inline style filtering.
        After bleach, strips url() from inline style attributes and validates img src.
        """
        cleaned = bleach.clean(
            raw_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            css_sanitizer=_CSS_SANITIZER,
            strip=True,
        )
        # Strip url() from inline style attrs only (not from visible text)
        cleaned = _strip_url_from_inline_styles(cleaned, self.is_surgery_mode)
        # Validate img src attributes (safety check for URLs)
        cleaned = self._sanitize_img_src(cleaned)
        return cleaned

    # ------------------------------------------------------------------
    # Wrapper Stripping (for nested HTML from _wrap_mockup)
    # ------------------------------------------------------------------

    # Patterns to remove document-level wrapper elements from cached mockup HTML.
    # Order matters: strip <head> blocks first (to capture orphaned CSS text inside),
    # then meta-bar/footer divs, then remaining document-level tags.
    _WRAPPER_STRIP_PATTERNS = [
        # 1. Entire <head>...</head> blocks (captures orphaned CSS text left when
        #    bleach stripped <style> tags but preserved the text content)
        (r'<head[^>]*>.*?</head>', re.IGNORECASE | re.DOTALL),
        # 2. <style> blocks that may exist outside <head>
        (r'<style[^>]*>.*?</style>', re.IGNORECASE | re.DOTALL),
        # 3. Meta-bar and footer divs from _wrap_mockup
        (r'<div[^>]*class="mockup-meta-bar"[^>]*>.*?</div>', re.DOTALL),
        (r'<div[^>]*class="mockup-gen-footer"[^>]*>.*?</div>', re.DOTALL),
        # 4. Document-level tags (tags only, not content)
        (r'<!DOCTYPE[^>]*>', re.IGNORECASE),
        (r'</?html[^>]*>', re.IGNORECASE),
        (r'</?head[^>]*>', re.IGNORECASE),
        (r'</?body[^>]*>', re.IGNORECASE),
        # 5. Stray head-level elements (if <head> block match failed)
        (r'<title[^>]*>.*?</title>', re.IGNORECASE | re.DOTALL),
        (r'<meta[^>]*/?>', re.IGNORECASE),
    ]

    def _strip_mockup_wrapper(self, wrapped_html: str) -> str:
        """Strip document-level wrapper leaving only div-level page content.

        Removes: _wrap_mockup shell (meta-bar, footer, DOCTYPE, html/head/body),
        plus any nested html/head/body/style/meta/title tags from the AI vision output.
        Also removes orphaned CSS text that bleach left behind when stripping <style> tags.
        """
        content = wrapped_html
        for pattern, flags in self._WRAPPER_STRIP_PATTERNS:
            content = re.sub(pattern, '', content, flags=flags)
        return content.strip()

    # ------------------------------------------------------------------
    # Brand Context Building (for AI rewrite prompt)
    # ------------------------------------------------------------------

    def _build_brand_context(self, brand_profile: Dict[str, Any]) -> str:
        """Build compact brand summary for AI prompt. Truncates long fields."""
        bb = brand_profile.get("brand_basics") or {}
        prod = brand_profile.get("product") or {}
        mech = brand_profile.get("mechanism") or {}
        pp = brand_profile.get("pain_points") or {}
        sp = brand_profile.get("social_proof") or {}
        pricing = brand_profile.get("pricing") or []
        guarantee = brand_profile.get("guarantee") or {}
        personas = brand_profile.get("personas") or []
        ov = brand_profile.get("offer_variant") or {}
        ingredients = brand_profile.get("ingredients") or []
        timeline = brand_profile.get("results_timeline") or []

        lines = [
            f"Brand: {bb.get('name') or 'Unknown'}",
            f"Voice/Tone: {bb.get('voice_tone') or 'professional'}",
            f"Product: {prod.get('name') or 'Unknown'}",
            f"Key Benefits: {', '.join(str(b) for b in (prod.get('key_benefits') or [])[:5])}",
            f"Key Problems Solved: {', '.join(str(p) for p in (prod.get('key_problems_solved') or [])[:5])}",
        ]
        if mech.get("name"):
            lines.append(f"Mechanism: {mech['name']} - {(mech.get('solution') or '')[:200]}")
        if pp.get("pain_points"):
            lines.append(f"Pain Points: {', '.join(str(p) for p in (pp.get('pain_points') or [])[:5])}")
        if pp.get("desires_goals"):
            lines.append(f"Desires: {', '.join(str(d) for d in (pp.get('desires_goals') or [])[:5])}")
        if guarantee.get("text"):
            lines.append(f"Guarantee: {(guarantee.get('text') or '')[:200]}")
        if pricing:
            price_strs = []
            for p in pricing[:3]:
                if not isinstance(p, dict):
                    continue
                price_strs.append(f"{p.get('name') or ''}: ${p.get('price') or ''}")
            if price_strs:
                lines.append(f"Pricing: {', '.join(price_strs)}")
        if ingredients:
            ing_names = [
                (i.get("name") or str(i))[:50] if isinstance(i, dict) else str(i)[:50]
                for i in ingredients[:8]
            ]
            lines.append(f"Ingredients: {', '.join(ing_names)}")
        if timeline:
            for t in timeline[:4]:
                if isinstance(t, dict):
                    lines.append(f"  Results ({t.get('timeframe') or '?'}): {(t.get('outcome') or '')[:100]}")
                else:
                    lines.append(f"  Results: {str(t)[:100]}")
        quotes = (sp.get("top_positive_quotes") or sp.get("transformation_quotes") or [])[:3]
        if quotes:
            lines.append("Customer Quotes:")
            for q in quotes:
                if isinstance(q, str):
                    text = q
                elif isinstance(q, dict):
                    text = (q.get("quote") or q.get("text") or str(q))
                else:
                    text = str(q)
                lines.append(f'  - "{(text or "")[:200]}"')
        if personas:
            p0 = personas[0]
            if isinstance(p0, dict):
                lines.append(f"Target Persona: {p0.get('name') or ''} - {(p0.get('snapshot') or '')[:200]}")
                if p0.get("pain_points"):
                    pts = p0["pain_points"][:3] if isinstance(p0["pain_points"], list) else []
                    if pts:
                        lines.append(f"  Persona Pains: {', '.join(str(p)[:80] for p in pts)}")
        if ov.get("name"):
            lines.append(f"Offer Variant: {ov['name']}")
            if ov.get("pain_points"):
                lines.append(f"  OV Pain Points: {', '.join(str(p)[:80] for p in (ov.get('pain_points') or [])[:3])}")
            if ov.get("desires_goals"):
                lines.append(f"  OV Desires: {', '.join(str(d)[:80] for d in (ov.get('desires_goals') or [])[:3])}")

        return "\n".join(lines)

    def _build_blueprint_directions(self, blueprint: Dict[str, Any]) -> str:
        """Extract strategic directions from blueprint for AI prompt."""
        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]

        lines = []
        ss = rb.get("strategy_summary") or {}
        if ss:
            lines.append("## PAGE STRATEGY")
            for key in ("awareness_adaptation", "tone_direction", "target_persona"):
                if ss.get(key):
                    lines.append(f"{key}: {str(ss[key] or '')}")
            kd = (ss.get("key_differentiators") or [])[:3]
            if kd:
                lines.append(f"Differentiators: {', '.join(str(d) for d in kd)}")
            lines.append("")

        def _safe_order(s):
            if not isinstance(s, dict):
                return 999
            try:
                return int(s.get("flow_order", 999))
            except (TypeError, ValueError):
                return 999

        sections = sorted(rb.get("sections") or [], key=_safe_order)
        lines.append("## SECTION-BY-SECTION DIRECTIONS")
        for section in sections:
            if not isinstance(section, dict):
                continue
            lines.append(f"\n### {section.get('section_name', 'unknown')} (order: {section.get('flow_order')})")
            if section.get("copy_direction"):
                lines.append(f"Direction: {(section.get('copy_direction') or '')[:300]}")
            bm = section.get("brand_mapping") or {}
            if bm.get("primary_content"):
                lines.append(f"Primary: {(bm.get('primary_content') or '')[:300]}")
            if bm.get("emotional_hook"):
                lines.append(f"Hook: {(bm.get('emotional_hook') or '')[:200]}")
            if bm.get("supporting_data"):
                lines.append(f"Support: {(bm.get('supporting_data') or '')[:200]}")
            if section.get("gap_improvement"):
                lines.append(f"Improve: {(section.get('gap_improvement') or '')[:200]}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Slot Extraction & Validation
    # ------------------------------------------------------------------

    def _extract_slot_names(self, html: str) -> List[str]:
        """Parse HTML and collect all data-slot attribute values in document order."""
        class _SlotCollector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.slots: list = []
                self._seen: set = set()
            def handle_starttag(self, tag, attrs):
                for name, value in attrs:
                    if name == "data-slot" and value and value not in self._seen:
                        self.slots.append(value)
                        self._seen.add(value)
        collector = _SlotCollector()
        collector.feed(html)
        return collector.slots

    _VOID_ELEMENTS = frozenset([
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    ])

    def _extract_slots_with_content(self, html: str) -> Dict[str, str]:
        """Extract {slot_name: visible_text_content} from all data-slot elements.

        Returns dict preserving document order. Deduplicates: first occurrence wins.
        Skips void elements (input, img, br, etc.) since they have no text content.
        """
        void_elems = self._VOID_ELEMENTS

        class _SlotContentExtractor(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.slots: Dict[str, str] = {}
                self._seen: set = set()
                self._capturing: bool = False
                self._capture_tag: str = ""
                self._capture_depth: int = 0
                self._capture_slot: str = ""
                self._text_buf: list = []

            def handle_starttag(self, tag, attrs):
                if self._capturing:
                    # Track depth of same-tag nesting inside captured slot
                    if tag == self._capture_tag:
                        self._capture_depth += 1
                    return

                attr_dict = dict(attrs)
                slot_name = attr_dict.get("data-slot")
                if slot_name and slot_name not in self._seen:
                    self._seen.add(slot_name)
                    if tag.lower() in void_elems:
                        # Void elements have no inner content — record empty
                        return
                    self._capturing = True
                    self._capture_tag = tag
                    self._capture_depth = 1
                    self._capture_slot = slot_name
                    self._text_buf = []
                elif slot_name and slot_name in self._seen:
                    logger.warning(f"Duplicate data-slot '{slot_name}' — skipping")

            def handle_endtag(self, tag):
                if not self._capturing:
                    return
                if tag == self._capture_tag:
                    self._capture_depth -= 1
                    if self._capture_depth == 0:
                        text = " ".join("".join(self._text_buf).split()).strip()
                        self.slots[self._capture_slot] = text
                        self._capturing = False
                        self._capture_tag = ""
                        self._capture_slot = ""
                        self._text_buf = []

            def handle_data(self, data):
                if self._capturing:
                    self._text_buf.append(data)

        extractor = _SlotContentExtractor()
        extractor.feed(html)
        # If parser ended mid-capture (malformed HTML), save what we have
        if extractor._capturing and extractor._capture_slot:
            text = " ".join("".join(extractor._text_buf).split()).strip()
            extractor.slots[extractor._capture_slot] = text
        return extractor.slots

    def _validate_rewrite_structure(self, original_html: str, rewritten_html: str) -> None:
        """Validate that the rewritten HTML preserved the data-slot structure."""
        original_slots = set(self._extract_slot_names(original_html))
        rewritten_slots = set(self._extract_slot_names(rewritten_html))

        missing = original_slots - rewritten_slots
        if missing:
            logger.warning(f"AI rewrite lost {len(missing)} data-slots: {missing}")

        if original_slots and len(missing) > len(original_slots) * 0.5:
            raise ValueError(
                f"AI rewrite lost >50% of data-slots ({len(missing)}/{len(original_slots)})"
            )

    # ------------------------------------------------------------------
    # Output Quality Guards
    # ------------------------------------------------------------------

    def _validate_analysis_slots(self, html: str) -> Tuple[str, str]:
        """Validate data-slot coverage in generated HTML.

        Returns:
            (severity, report) where severity is "ok", "degraded", or "unusable".
        """
        slots = self._extract_slot_names(html)
        slot_set = set(slots)

        has_headline = "headline" in slot_set
        has_cta = any(s.startswith("cta-") for s in slot_set)
        total = len(slots)

        if total >= 3 and has_headline and has_cta:
            return "ok", f"Slot validation OK: {total} slots, headline={has_headline}, cta={has_cta}"
        elif total > 0:
            report = (
                f"Slot validation DEGRADED: {total} slots, "
                f"headline={has_headline}, cta={has_cta}"
            )
            logger.warning(report)
            return "degraded", report
        else:
            report = "Slot validation UNUSABLE: 0 data-slot attributes found"
            logger.warning(report)
            return "unusable", report

    def _validate_html_completeness(self, html: str) -> Tuple[bool, List[str]]:
        """Check for truncation/structural issues in generated HTML.

        Returns:
            (is_complete, list_of_issues). is_complete=True means HTML looks structurally OK.
        """
        issues = []

        # Minimum length check
        if len(html) < 200:
            issues.append(f"HTML too short ({len(html)} chars)")

        # Mid-tag truncation: last '<' has no matching '>'
        last_lt = html.rfind('<')
        last_gt = html.rfind('>')
        if last_lt > last_gt:
            issues.append("Mid-tag truncation detected (unclosed < at end)")

        # Structural tag imbalance
        for tag in ('div', 'section', 'body'):
            opens = len(re.findall(rf'<{tag}[\s>]', html, re.IGNORECASE))
            closes = len(re.findall(rf'</{tag}>', html, re.IGNORECASE))
            if opens > 0 and closes < opens - 2:
                issues.append(f"Tag imbalance: <{tag}> opened {opens}x, closed {closes}x")

        return (len(issues) == 0, issues)

    # ------------------------------------------------------------------
    # Content Fidelity Verification
    # ------------------------------------------------------------------

    class _TextExtractor(HTMLParser):
        """Extract visible text content from HTML, ignoring tags and attributes."""

        # Tags whose text content is not visible
        _SKIP_TAGS = frozenset(['style', 'script', 'meta', 'title', 'head'])

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.texts: list = []
            self._skip_depth: int = 0

        def handle_starttag(self, tag, attrs):
            if tag.lower() in self._SKIP_TAGS:
                self._skip_depth += 1

        def handle_endtag(self, tag):
            if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
                self._skip_depth -= 1

        def handle_data(self, data):
            if self._skip_depth == 0:
                text = data.strip()
                if text:
                    self.texts.append(text)

    @staticmethod
    def _extract_visible_text(html: str) -> List[str]:
        """Extract all visible text nodes from HTML."""
        extractor = MockupService._TextExtractor()
        try:
            extractor.feed(html)
        except Exception:
            logger.warning("HTMLParser failed in _extract_visible_text")
            return []
        return extractor.texts

    @staticmethod
    def _normalize_for_comparison(text: str) -> str:
        """Normalize text for fuzzy comparison: lowercase, collapse whitespace, strip punctuation."""
        import unicodedata
        text = unicodedata.normalize('NFKD', text)
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _verify_content_fidelity(
        self,
        generated_html: str,
        page_markdown: Optional[str],
    ) -> Tuple[List[str], List[str]]:
        """Compare generated HTML text against page markdown to detect hallucinations.

        Returns:
            (matched_texts, suspect_texts) where suspect_texts are text chunks
            in the generated HTML that have no close match in the page markdown.
        """
        if not page_markdown:
            return [], []

        # Extract text from generated HTML
        html_texts = self._extract_visible_text(generated_html)
        if not html_texts:
            return [], []

        # Build normalized reference text from markdown
        # Strip markdown formatting to get plain text
        ref_text = re.sub(r'[#*_`\[\]()!|>~]', '', page_markdown)
        ref_normalized = self._normalize_for_comparison(ref_text)

        matched = []
        suspect = []

        for text_chunk in html_texts:
            # Skip very short text (likely labels, buttons, nav items)
            if len(text_chunk) < 20:
                matched.append(text_chunk)
                continue

            # Skip common UI/structural text
            chunk_lower = text_chunk.lower()
            if any(skip in chunk_lower for skip in (
                'image placeholder', 'placeholder', '[image',
                'generated by', 'viraltracker',
            )):
                matched.append(text_chunk)
                continue

            # Normalize and check if chunk text exists in reference
            chunk_normalized = self._normalize_for_comparison(text_chunk)
            if not chunk_normalized or len(chunk_normalized) < 15:
                matched.append(text_chunk)
                continue

            # Check for substantial overlap using sliding window
            # Take a representative substring (first 40 chars normalized)
            probe = chunk_normalized[:40]
            if probe in ref_normalized:
                matched.append(text_chunk)
            else:
                # Try a shorter probe (first 25 chars) for partial matches
                short_probe = chunk_normalized[:25]
                if short_probe in ref_normalized:
                    matched.append(text_chunk)
                else:
                    suspect.append(text_chunk)

        if suspect:
            logger.warning(
                f"Content fidelity: {len(suspect)} suspect text chunks "
                f"(potential hallucinations) out of {len(html_texts)} total. "
                f"First suspect: {suspect[0][:100]!r}"
            )
        else:
            logger.info(
                f"Content fidelity: all {len(html_texts)} text chunks matched reference"
            )

        return matched, suspect

    # ------------------------------------------------------------------
    # HTML Truncation
    # ------------------------------------------------------------------

    def _truncate_html_at_boundary(self, html: str, max_chars: int) -> str:
        """Truncate HTML at the last closing </section> or </div> before max_chars.

        Falls back to the last '>' character if no section/div boundary found.
        Prevents cutting mid-tag which would produce invalid HTML.
        """
        if len(html) <= max_chars:
            return html

        search_start = max(0, max_chars - 2000)
        search_region = html[search_start:max_chars]

        # Prefer </section>, then </div> — major structural boundaries
        for pattern in (r'</section>', r'</div>'):
            matches = list(re.finditer(pattern, search_region, re.IGNORECASE))
            if matches:
                cut_point = search_start + matches[-1].end()
                logger.info(f"Truncated HTML at char {cut_point} ({pattern} boundary)")
                return html[:cut_point]

        # Fallback: last '>' before limit
        last_gt = html.rfind('>', max(0, max_chars - 500), max_chars)
        if last_gt > 0:
            return html[:last_gt + 1]

        # Ultimate fallback: hard cut
        logger.warning("No safe tag boundary found, hard-truncating HTML")
        return html[:max_chars]

    # ------------------------------------------------------------------
    # Competitor Brand Replacement
    # ------------------------------------------------------------------

    def _extract_competitor_name(
        self, blueprint: Dict, source_url: Optional[str] = None, html: str = "",
        classification: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract competitor brand name AND product name from available sources.

        Priority: source_url domain (refined via HTML text) > blueprint metadata > <title> tag.

        Returns:
            Tuple of (brand_name, product_name). product_name may differ from brand_name
            (e.g., brand="Hike Footwear", product="HF Stride"). Either may be None.
        """
        # Extract product name from classification (page classifier LLM output).
        # Must be at top — this method has 5 early-return paths that need product_name defined.
        product_name = None
        if classification:
            pc = classification.get("page_classifier") or classification
            raw = (pc.get("product_name") or "").strip()
            # Reject generic/short names that would mangle page content
            if raw and (len(raw) >= 6 or (len(raw.split()) >= 2 and len(raw) >= 4)):
                product_name = raw

        # 1. source_url parameter (most reliable — actual URL from analysis record)
        if source_url:
            domain_name = self._domain_to_brand_name(source_url)
            if domain_name:
                # Try to find a better-formatted version in the HTML text
                # e.g., domain "bobanutrition" → find "Boba Nutrition" in text
                refined = self._refine_name_from_html(domain_name, html)
                if refined:
                    return (refined, product_name)
                return (domain_name, product_name)

        # 2. Blueprint metadata competitor_url (may be free-text, not always a URL)
        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]
        meta = rb.get("metadata", rb.get("strategy_summary", {}))
        comp_url = meta.get("competitor_url", meta.get("source_url", ""))
        name = self._domain_to_brand_name(comp_url)
        if name:
            refined = self._refine_name_from_html(name, html)
            return (refined or name, product_name)

        # 3. <title> tag in the HTML
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title_text = title_match.group(1).strip()
            # Strip common suffixes
            for suffix_pattern in [
                r'\s*[\|\-\u2013\u2014]\s*Official\s*Site.*$',
                r'\s*[\|\-\u2013\u2014]\s*Shop\s*Now.*$',
                r'\s*[\|\-\u2013\u2014]\s*Home.*$',
                r'\s*[\|\-\u2013\u2014]\s*#\d+.*$',
                r'\s*[\|\-\u2013\u2014]\s*[^|]{0,30}$',
            ]:
                title_text = re.sub(suffix_pattern, '', title_text, flags=re.IGNORECASE).strip()
            if 3 <= len(title_text) <= 40:
                return (title_text, product_name)

        return (None, product_name)

    def _refine_name_from_html(self, domain_name: str, html: str) -> Optional[str]:
        """Search HTML text for a properly-formatted version of a domain-derived name.

        E.g., domain_name="Bobanutrition" → find "Boba Nutrition" in visible text.
        Returns the properly-spaced/cased version, or None if not found.
        """
        if not html or not domain_name:
            return None

        # Build a pattern that allows optional spaces/hyphens between characters
        # "Bobanutrition" → "B.o.b.a.?.n.u.t.r.i.t.i.o.n" won't work well
        # Better: search for the domain chars with optional word breaks
        clean = domain_name.replace(' ', '').replace('-', '').lower()
        if len(clean) < 4:
            return None

        # Try to find word-broken version: insert optional space/hyphen between each char group
        # Look for 2-word patterns like "Boba Nutrition", "Martin Clinic"
        # Strategy: find all 2-3 word title-case phrases in text that contain the domain letters
        # Simple approach: search for the domain's letters allowing a single space
        for split_pos in range(3, len(clean) - 2):
            left = re.escape(clean[:split_pos])
            right = re.escape(clean[split_pos:])
            pattern = left + r'[\s\-]' + right
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                found = match.group(0).strip()
                # Title-case normalize
                if found[0].islower():
                    found = found.title()
                if len(found) >= 4:
                    return found

        return None

    def _domain_to_brand_name(self, url: str) -> Optional[str]:
        """Convert a URL to a likely brand name from the domain."""
        if not url:
            return None
        url = url.strip()
        # Reject strings that don't look like URLs (contain spaces, parentheses, etc.)
        if ' ' in url or '(' in url or ')' in url:
            return None
        try:
            parsed = urlparse(url if '://' in url else f'https://{url}')
            domain = parsed.hostname or ""
        except Exception:
            return None

        # Strip www and TLD
        domain = re.sub(r'^www\.', '', domain)
        domain = re.sub(r'\.(com|co|io|org|net|store|shop|health|life|us|ca|uk|au)(\.[a-z]{2})?$', '', domain)

        if not domain or len(domain) < 3:
            return None

        # Split on hyphens
        parts = domain.split('-')
        # Split camelCase within parts
        expanded = []
        for part in parts:
            # Insert space before uppercase letters (camelCase)
            split_camel = re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
            expanded.append(split_camel)
        name = ' '.join(expanded)
        # Title case
        name = name.title()
        if len(name) < 3:
            return None
        return name

    def _replace_competitor_brand(self, html: str, competitor_name: str, brand_name: str) -> str:
        """Replace competitor brand in text nodes and safe attributes (alt, title, aria-label).

        Uses HTMLParser to walk the DOM. NEVER replaces in class, id, href, src,
        data-*, style attributes, or <style>/<script> blocks.
        """
        if not competitor_name or len(competitor_name) < 3:
            return html

        # Build replacement variants
        variants = set()
        variants.add(competitor_name)
        variants.add(competitor_name.lower())
        variants.add(competitor_name.upper())
        # No-space variant
        no_space = competitor_name.replace(' ', '')
        variants.add(no_space)
        variants.add(no_space.lower())
        # Hyphenated variant
        hyphenated = competitor_name.replace(' ', '-')
        variants.add(hyphenated)
        variants.add(hyphenated.lower())

        # Build case-insensitive regex with word boundaries
        escaped_variants = [re.escape(v) for v in sorted(variants, key=len, reverse=True)]
        pattern = re.compile(r'\b(' + '|'.join(escaped_variants) + r')\b', re.IGNORECASE)

        _SAFE_ATTRS = frozenset(['alt', 'title', 'aria-label'])

        class _BrandReplacer(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.parts: list = []
                self._in_style = False
                self._in_script = False

            def _replace_text(self, text: str) -> str:
                """Case-preserving replacement."""
                def _repl(m):
                    matched = m.group(0)
                    if matched.isupper():
                        return brand_name.upper()
                    if matched.istitle() or matched[0].isupper():
                        return brand_name
                    return brand_name.lower()
                return pattern.sub(_repl, text)

            def handle_starttag(self, tag, attrs):
                if tag in ('style',):
                    self._in_style = True
                if tag in ('script',):
                    self._in_script = True

                # Rebuild tag, replacing only safe attribute values
                new_attrs = []
                for name, value in attrs:
                    if value and name.lower() in _SAFE_ATTRS:
                        new_attrs.append((name, self._replace_text(value)))
                    else:
                        new_attrs.append((name, value))

                # Reconstruct the start tag
                parts = [f'<{tag}']
                for name, value in new_attrs:
                    if value is None:
                        parts.append(f' {name}')
                    else:
                        parts.append(f' {name}="{_html_module.escape(value, quote=True)}"')
                parts.append('>')
                self.parts.append(''.join(parts))

            def handle_endtag(self, tag):
                if tag in ('style',):
                    self._in_style = False
                if tag in ('script',):
                    self._in_script = False
                self.parts.append(f'</{tag}>')

            def handle_startendtag(self, tag, attrs):
                # Self-closing tags — same safe-attr logic
                new_attrs = []
                for name, value in attrs:
                    if value and name.lower() in _SAFE_ATTRS:
                        new_attrs.append((name, self._replace_text(value)))
                    else:
                        new_attrs.append((name, value))
                parts = [f'<{tag}']
                for name, value in new_attrs:
                    if value is None:
                        parts.append(f' {name}')
                    else:
                        parts.append(f' {name}="{_html_module.escape(value, quote=True)}"')
                parts.append(' />')
                self.parts.append(''.join(parts))

            def handle_data(self, data):
                if self._in_style or self._in_script:
                    self.parts.append(data)
                else:
                    self.parts.append(self._replace_text(data))

            def handle_entityref(self, name):
                self.parts.append(f'&{name};')

            def handle_charref(self, name):
                self.parts.append(f'&#{name};')

            def handle_comment(self, data):
                self.parts.append(f'<!--{data}-->')

            def handle_decl(self, decl):
                self.parts.append(f'<!{decl}>')

            def unknown_decl(self, data):
                self.parts.append(f'<!{data}>')

            def get_result(self) -> str:
                return ''.join(self.parts)

        replacer = _BrandReplacer()
        try:
            replacer.feed(html)
            return replacer.get_result()
        except Exception:
            logger.warning("HTMLParser failed in _replace_competitor_brand, returning as-is")
            return html

    # ------------------------------------------------------------------
    # AI HTML Rewrite (Blueprint Copywriting)
    # ------------------------------------------------------------------

    _MAX_HTML_CHARS = 80_000
    _MAX_HTML_CHARS_SURGERY = 500_000  # Raised for surgery output (large Shopify/Replo pages)

    def _rewrite_html_for_brand(
        self,
        page_body: str,
        blueprint: Dict[str, Any],
        brand_profile: Dict[str, Any],
    ) -> str:
        """DEPRECATED: Use _rewrite_slots_for_brand() + _template_swap() instead.

        Kept for backward compatibility. The new slot-based pipeline in
        generate_blueprint_mockup() no longer calls this method.

        Rewrites ALL visible text in the page body HTML for the brand.
        """
        from pydantic_ai import Agent
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_sync_with_tracking

        # Prompt size guardrail — truncate at tag boundary (Fix 3)
        max_chars = self._MAX_HTML_CHARS_SURGERY if self.is_surgery_mode else self._MAX_HTML_CHARS
        html_input = page_body
        if len(html_input) > max_chars:
            logger.warning(
                f"Page body {len(html_input)} chars exceeds {max_chars}, truncating"
            )
            html_input = self._truncate_html_at_boundary(html_input, max_chars)

        brand_context = self._build_brand_context(brand_profile)
        directions = self._build_blueprint_directions(blueprint)

        prompt = f"""## ORIGINAL PAGE HTML
{html_input}

## BLUEPRINT DIRECTIONS
{directions}

## BRAND DATA
{brand_context}

## REWRITE RULES
1. Keep the EXACT same HTML tags, attributes, classes, and inline styles
2. Replace ALL visible text content with brand-appropriate copy
3. For elements with data-slot attributes, follow the blueprint directions closely
4. For elements WITHOUT data-slot, replace competitor content with brand equivalents:
   - Competitor brand/product names → brand name/product name
   - Competitor testimonials → brand's customer quotes (use real quotes from Brand Data)
   - Competitor statistics → brand's actual statistics if available
   - Competitor ingredients/features → brand's ingredients/features
   - Urgency/scarcity text → adapt for brand's offer style
5. Maintain page congruence: every element supports one cohesive argument
6. Use the brand's voice/tone throughout
7. DO NOT add, remove, or reorder HTML elements
8. DO NOT modify CSS styles, classes, or attributes (except text content)
8b. Preserve ALL class names exactly as they appear (e.g., class="hero-section") - their styling definitions are maintained separately
9. Keep data-slot attributes exactly as they are
10. Image placeholder labels: update to describe brand-relevant images
11. NEVER use em dashes (\u2014). Use commas, periods, colons, or semicolons instead.

OUTPUT: Return ONLY the rewritten HTML. No explanations, no code fences, no wrapping <html>/<body> tags."""

        agent = Agent(
            model=Config.get_model("creative"),
            system_prompt=(
                "You are an expert direct-response copywriter rewriting a competitor "
                "landing page for a different brand. Rewrite ALL visible text for the "
                "brand while keeping the EXACT same HTML structure. Return ONLY the "
                "rewritten HTML fragment. No explanations, no outer html/body tags."
            ),
        )

        result = run_agent_sync_with_tracking(
            agent, prompt,
            tracker=self._usage_tracker,
            user_id=self._user_id,
            organization_id=self._organization_id,
            tool_name="mockup_service",
            operation="blueprint_copy",
        )

        # Guard result object
        if result is None:
            raise ValueError("AI rewrite returned no result object")

        raw = result.output

        # Guard output is non-None, is a string, and has content
        if raw is None:
            raise ValueError("AI rewrite returned None output")
        if not isinstance(raw, str):
            raw = str(raw)
        if not raw.strip():
            raise ValueError("AI rewrite returned empty/whitespace-only output")

        # Strip code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        # Strip any html/body wrapper the AI may have added
        raw = self._strip_mockup_wrapper(raw)

        # Sanitize em/en dashes from AI-generated copy
        raw = _sanitize_dashes(raw)

        # Validate structure
        self._validate_rewrite_structure(page_body, raw)

        return raw

    # ------------------------------------------------------------------
    # Slot-Based AI Rewrite (Blueprint Copywriting v2)
    # ------------------------------------------------------------------

    _SLOT_REWRITE_PROMPT_BASE = (
        "You are an expert direct-response copywriter. You receive a structured JSON "
        "payload describing a landing page's text slots grouped by section, along with "
        "comprehensive brand data, product details, and strategic directions.\n\n"
        "## Your Mission\n"
        "You are creating NEW landing page copy for the target brand. The `current` text "
        "in each slot comes from a COMPETITOR page and serves only as a structural template "
        "showing the slot's role and approximate length. Do NOT paraphrase the competitor copy. "
        "Instead, write ORIGINAL content using the brand's actual product data, mechanism, "
        "benefits, pain points, and testimonials provided in the payload.\n\n"
        "## Content Sources (USE THESE)\n"
        "- `brand.product` / `brand.benefits` / `brand.features`: the target product's real benefits and features\n"
        "- `brand.mechanism`: how the product works (name, problem it solves, solution)\n"
        "- `brand.ingredients`: real ingredients to reference\n"
        "- `brand.pain_points` / `brand.desires`: audience pain points and goals\n"
        "- `brand.testimonials` / `brand.transformation_quotes`: real customer quotes\n"
        "- `brand.guarantee` / `brand.pricing` / `brand.results_timeline`: real offer details\n"
        "- Each section's `copy_direction`: strategic guidance for that section\n"
        "- Each section's `brand_data`: section-specific content mapping from the blueprint\n\n"
        "## Rules\n"
        "- Return ONLY the rewrites dict mapping slot_name -> new plain text.\n"
        "- EVERY input slot name MUST appear in your output. Missing slots = failure.\n"
        "- Values MUST be plain text only. NO HTML tags. NO markdown formatting.\n"
        "- NEVER use em dashes (\u2014) or en dashes (\u2013). Use commas, periods, colons, or semicolons.\n"
        "- Match the brand's voice and tone throughout.\n"
        "- Use REAL data from the brand profile: real benefits, real ingredients, real mechanism.\n"
        "- Maintain congruence: every slot supports one cohesive argument across all sections.\n"
        "- Never repeat a benefit, statistic, or emotional hook across sections.\n"
        "- The competitor's `current` text shows the ROLE of each slot (headline, body, CTA), "
        "not the content to keep. Write fresh copy that fills the same role.\n\n"
        "## Slot Type Guidelines\n"
        "- headline: punchy and benefit-driven, use brand's actual key benefit\n"
        "- subheadline: expands on headline promise with brand-specific detail\n"
        "- heading: section-specific benefit or transition using brand data\n"
        "- body: persuasive copy using brand's mechanism, ingredients, or pain points\n"
        "- cta: action verb first (e.g., 'Get Your Free Sample')\n"
        "- testimonial: use REAL customer quotes from brand.testimonials or brand.transformation_quotes\n"
        "- feature: specific benefit or ingredient from brand.features or brand.ingredients\n"
        "- list: concise list item drawing from brand's real benefits or features\n"
        "- badge/price/guarantee: use brand.guarantee, brand.pricing, brand.results_timeline\n\n"
        "## Numbered Prefix Preservation (Listicle Pages)\n"
        "When a slot includes a `prefix` field:\n"
        "- Start your rewrite with EXACTLY the value of `prefix`, followed by a space, then your new copy.\n"
        "- Do NOT alter the prefix format. If prefix is \"3.\" your output starts with \"3. \".\n"
        "- Do NOT renumber. The prefix is assigned upstream and reflects the item's position in the full page.\n"
        "- The word count constraint applies to the ENTIRE output including the prefix.\n\n"
    )

    _SLOT_REWRITE_ADDENDUM_RUNTIME = (
        "## LENGTH MATCHING (CRITICAL)\n"
        "Each slot includes `max_words` - the hard upper limit reflecting the visual space "
        "in the page layout. Your rewrite MUST NOT exceed this word count.\n"
        "- `original_words` / `original_chars` show the source text dimensions.\n"
        "- `length_note` explains the specific constraint.\n"
        "- Aim to match the original length closely. Shorter is better than longer.\n"
        "- If you cannot fit the message, cut adjectives and filler first.\n"
    )

    _SLOT_REWRITE_ADDENDUM_BLUEPRINT = (
        "## LENGTH AND SPACE (CREATIVE CONSTRAINT)\n"
        "Each section includes a `space_budget` describing the visual space available.\n"
        "Compose each slot to use 90-100% of its target range.\n"
        "- PLAN FIRST: count how many sentences you need, then write to that count.\n"
        "- The space is fixed like a print layout: your words must earn their place.\n"
        "- When the budget is tight (e.g., 6-10 word headline), every word must carry weight.\n"
        "- When the budget is generous (e.g., 55-70 word body), develop the argument fully.\n"
        "- Undershooting by 30%+ wastes valuable layout space.\n"
        "- Overshooting the target range is NOT acceptable. Plan your sentence count to land within range.\n"
        "- Your copy should surprise and persuade, not merely inform.\n"
        "- HEADLINES must be complete thoughts. Never end a headline mid-sentence.\n"
    )

    # Backward-compatible computed prompt (runtime mode)
    _SLOT_REWRITE_SYSTEM_PROMPT = _SLOT_REWRITE_PROMPT_BASE + _SLOT_REWRITE_ADDENDUM_RUNTIME

    _REGEN_PROMPT_RUNTIME = (
        "You are an expert direct-response copywriter editing for length.\n"
        "You receive slots whose text exceeds the layout's word limit.\n"
        "Rewrite each one to fit within max_words. You are NOT condensing; "
        "you are writing a tighter version that preserves persuasive power.\n\n"
        "## Rules\n"
        "- Return ONLY a JSON dict mapping slot_name -> rewritten plain text.\n"
        "- EVERY input slot name MUST appear in your output.\n"
        "- Values MUST be plain text only. NO HTML tags. NO markdown.\n"
        "- NEVER use em dashes or en dashes. Use commas, periods, colons, or semicolons.\n"
        "- Cut setup language and filler qualifiers first. Keep key benefits and action verbs.\n"
        "- max_words is a HARD ceiling. Aim for 90-100% of it.\n"
        "- HEADLINES must be complete thoughts. Never produce a headline that ends mid-sentence.\n"
        "- CTA slots must start with an action verb.\n"
        "- If a slot has a `prefix` field, your rewrite MUST start with that exact prefix followed by a space.\n"
    )

    _REGEN_PROMPT_BLUEPRINT = (
        "You are an expert direct-response copywriter editing for length.\n"
        "You receive slots that ran over their target word count.\n"
        "Rewrite each one to fit the target. You are NOT condensing; you are writing a tighter version "
        "that maintains persuasive power and brand voice.\n\n"
        "## Rules\n"
        "- Return ONLY a JSON dict mapping slot_name -> rewritten plain text.\n"
        "- EVERY input slot name MUST appear in your output.\n"
        "- Keep the core persuasive argument. Cut setup language and filler qualifiers.\n"
        "- If copy_direction is provided, ensure the rewrite still fulfills it.\n"
        "- target_words is the ceiling. Aim for 90-100% of it.\n"
        "- NEVER use em dashes or en dashes. Use commas, periods, colons, or semicolons.\n"
        "- HEADLINES must be complete thoughts. Never produce a headline that ends mid-sentence.\n"
        "- CTA slots must start with an action verb.\n"
        "- If a slot has a `prefix` field, your rewrite MUST start with that exact prefix followed by a space.\n"
    )

    _SELECTIVE_REGEN_SYSTEM_PROMPT = (
        "You are an expert direct-response copywriter performing a SELECTIVE rewrite "
        "of specific landing page text slots. You receive two groups of slots:\n\n"
        "1. `frozen_slots` — READ-ONLY context. These slots are finalized and must NOT be rewritten.\n"
        "   Use them ONLY to understand the page's narrative flow, tone, and claims already made.\n"
        "2. `regenerate_slots` — These are the slots you MUST rewrite with fresh copy.\n\n"
        "## Your Mission\n"
        "Rewrite ONLY the `regenerate_slots` using the brand data, page strategy, "
        "and copy directions provided. Your output must maintain coherence with the "
        "frozen slots while delivering original, persuasive content.\n\n"
        "## Coherence Rules (CRITICAL)\n"
        "- NEVER repeat a benefit, statistic, hook, or emotional phrase that already appears "
        "in a frozen slot. The frozen slots are final — you must complement, not duplicate.\n"
        "- NEVER contradict a claim or promise in a frozen slot.\n"
        "- Maintain the same voice and tone as the frozen slots.\n"
        "- Respect the narrative arc: if frozen slots establish a problem, your regenerated "
        "slot should continue the argument (not restart it).\n\n"
        "## Content Sources (USE THESE)\n"
        "- `brand.product` / `brand.benefits` / `brand.features`: real product benefits\n"
        "- `brand.mechanism`: how the product works\n"
        "- `brand.ingredients`: real ingredients to reference\n"
        "- `brand.pain_points` / `brand.desires`: audience pain points and goals\n"
        "- `brand.testimonials` / `brand.transformation_quotes`: real customer quotes\n"
        "- `brand.guarantee` / `brand.pricing` / `brand.results_timeline`: offer details\n"
        "- Each section's `copy_direction`: strategic guidance\n\n"
        "## Rules\n"
        "- Return ONLY a JSON dict mapping slot_name -> rewritten plain text.\n"
        "- Output ONLY the regenerated slot names. Do NOT include frozen slots.\n"
        "- EVERY regenerate_slot name MUST appear in your output.\n"
        "- Values MUST be plain text only. NO HTML tags. NO markdown.\n"
        "- NEVER use em dashes (\u2014) or en dashes (\u2013). Use commas, periods, colons, or semicolons.\n"
        "- Match the brand's voice and tone throughout.\n\n"
        "## Length Matching\n"
        "Each regenerate_slot includes `max_words` — the hard upper limit for the slot's "
        "visual space. Your rewrite MUST NOT exceed this count.\n"
        "- Aim for 90-100% of max_words. Shorter is better than longer.\n"
        "- HEADLINES must be complete thoughts. Never end mid-sentence.\n"
        "- CTA slots must start with an action verb.\n\n"
        "## Numbered Prefix Preservation (Listicle Pages)\n"
        "When a slot includes a `prefix` field, start your rewrite with EXACTLY that prefix "
        "followed by a space, then your new copy. Do NOT alter or renumber the prefix.\n"
    )

    _SELECTIVE_REGEN_PROMPT = (
        "You are an expert direct-response copywriter editing for length.\n"
        "You receive slots that ran over their target word count.\n"
        "Rewrite each one to fit the target while maintaining coherence with frozen context.\n\n"
        "## Rules\n"
        "- Return ONLY a JSON dict mapping slot_name -> rewritten plain text.\n"
        "- EVERY input slot name MUST appear in your output.\n"
        "- NEVER use em dashes or en dashes. Use commas, periods, colons, or semicolons.\n"
        "- max_words is a HARD ceiling. Aim for 90-100% of it.\n"
        "- HEADLINES must be complete thoughts. Never produce a headline that ends mid-sentence.\n"
        "- CTA slots must start with an action verb.\n"
        "- If a slot has a `prefix` field, your rewrite MUST start with that exact prefix followed by a space.\n"
    )

    _MAX_SLOTS_PER_BATCH = 80

    def _rewrite_slots_for_brand(
        self,
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
        blueprint: Dict,
        brand_profile: Dict,
        slot_metadata: Optional[Dict[str, Dict]] = None,
        rewrite_strategy: str = "slot_constrained",
        listicle_from_html: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """AI rewrites slot text via structured JSON. Returns {slot_name: new_text}.

        Delegates to strategy-specific config builder, then runs the shared pipeline.

        Args:
            slot_contents: {slot_name: text} from _extract_slots_with_content.
            slot_sections: {slot_name: context} from _map_slots_to_sections.
            blueprint: Reconstruction blueprint.
            brand_profile: Full brand profile.
            slot_metadata: Optional {slot_name: {word_count, char_count}}.
            rewrite_strategy: "slot_constrained" (runtime) or "section_guided" (blueprint).
            listicle_from_html: Pre-computed listicle data from S2 HTML attributes.

        All returned values are plain text, HTML-escaped, and dash-sanitized.
        """
        assert rewrite_strategy in ("slot_constrained", "section_guided"), (
            f"Invalid rewrite_strategy: {rewrite_strategy}"
        )

        if rewrite_strategy == "section_guided":
            config = self._build_blueprint_rewrite_config(
                slot_contents, slot_sections, blueprint, brand_profile, slot_metadata,
                listicle_from_html=listicle_from_html,
            )
        else:
            config = self._build_runtime_rewrite_config(
                slot_contents, slot_sections, blueprint, brand_profile, slot_metadata,
                listicle_from_html=listicle_from_html,
            )
        return self._execute_slot_rewrite_pipeline(config)

    def _build_shared_brand_context(
        self, blueprint: Dict, brand_profile: Dict
    ) -> Tuple[Dict, Dict]:
        """Extract brand_data and page_strategy from profile and blueprint.

        Returns (brand_data, page_strategy) tuple.
        """
        bb = brand_profile.get("brand_basics") or {}
        prod = brand_profile.get("product") or {}
        mech = brand_profile.get("mechanism") or {}
        sp = brand_profile.get("social_proof") or {}
        pp = brand_profile.get("pain_points") or {}
        ov = brand_profile.get("offer_variant") or {}
        brand_data = {
            "name": bb.get("name", ""),
            "voice_tone": bb.get("voice_tone", bb.get("tone", "")),
            "description": bb.get("description", ""),
            "product": prod.get("name", bb.get("product_name", "")),
            "target_audience": prod.get("target_audience", ""),
            "benefits": prod.get("key_benefits") or [],
            "problems_solved": prod.get("key_problems_solved") or [],
            "features": prod.get("features") or [],
            "ingredients": brand_profile.get("ingredients") or [],
            "mechanism": {
                "name": mech.get("name", ""),
                "problem": mech.get("problem", ""),
                "solution": mech.get("solution", ""),
            } if mech.get("name") else {},
            "pain_points": pp.get("pain_points") or ov.get("pain_points") or [],
            "desires": ov.get("desires_goals") or [],
            "testimonials": sp.get("top_positive_quotes") or [],
            "transformation_quotes": sp.get("transformation_quotes") or [],
            "guarantee": (brand_profile.get("guarantee") or {}).get("text", ""),
            "results_timeline": brand_profile.get("results_timeline") or [],
            "pricing": brand_profile.get("pricing") or {},
        }

        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]
        strategy = rb.get("strategy_summary", {})
        page_strategy = {
            "awareness_adaptation": strategy.get("awareness_adaptation", ""),
            "tone_direction": strategy.get("tone_direction", strategy.get("brand_voice_recommendation", "")),
            "primary_angle": strategy.get("primary_angle", strategy.get("core_argument", "")),
        }
        return brand_data, page_strategy

    def _build_runtime_rewrite_config(
        self,
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
        blueprint: Dict,
        brand_profile: Dict,
        slot_metadata: Optional[Dict[str, Dict]] = None,
        listicle_from_html: Optional[Dict] = None,
    ) -> "_SlotRewriteConfig":
        """Build config for runtime (slot_constrained) rewrite strategy.

        Computes adaptive max_words per slot via _compute_slot_length_spec.
        Slot objects include max_words, original_words, original_chars, length_note.
        """
        brand_data, page_strategy = self._build_shared_brand_context(blueprint, brand_profile)

        section_groups: Dict[str, dict] = {}
        for slot_name, content in slot_contents.items():
            ctx = slot_sections.get(slot_name, {})
            sec_key = ctx.get("section_name", "global")
            flow = ctx.get("flow_order", 999)
            group_key = f"{flow:04d}_{sec_key}"
            if group_key not in section_groups:
                section_groups[group_key] = {
                    "section_name": sec_key,
                    "copy_direction": ctx.get("copy_direction", ""),
                    "brand_data": ctx.get("brand_mapping", {}),
                    "slots": [],
                }
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            meta = (slot_metadata or {}).get(slot_name)
            if meta and meta.get("word_count", 0) > 0:
                length_spec = self._compute_slot_length_spec(
                    slot_type, meta["word_count"], meta["char_count"]
                )
            else:
                length_spec = self._compute_slot_length_spec(slot_type, 0, 0)
            section_groups[group_key]["slots"].append({
                "name": slot_name,
                "type": slot_type,
                "current": content,
                "max_words": length_spec["max_words"],
                "original_words": length_spec["original_words"],
                "original_chars": length_spec["original_chars"],
                "length_note": length_spec["length_note"],
            })

        ordered_sections = [section_groups[k] for k in sorted(section_groups.keys())]

        # Prefer pre-computed listicle data from S2 HTML; fall back to runtime detection
        listicle_data = listicle_from_html or self._detect_listicle_structure(slot_contents, slot_sections)
        listicle_prefixes = listicle_data.get("prefixes", {})
        if listicle_prefixes:
            for g in ordered_sections:
                for s in g["slots"]:
                    if s["name"] in listicle_prefixes:
                        s["prefix"] = listicle_prefixes[s["name"]]

        # Build slot_specs_lookup for regen/truncation enforcement
        slot_specs_lookup: Dict[str, Dict] = {}
        for g in ordered_sections:
            for s in g["slots"]:
                spec = {
                    "max_words": s["max_words"],
                    "type": s["type"],
                    "original_words": s.get("original_words", 0),
                    "length_note": s.get("length_note", ""),
                }
                if s["name"] in listicle_prefixes:
                    spec["prefix"] = listicle_prefixes[s["name"]]
                slot_specs_lookup[s["name"]] = spec

        return _SlotRewriteConfig(
            strategy="slot_constrained",
            system_prompt=self._SLOT_REWRITE_SYSTEM_PROMPT,
            regen_prompt=self._REGEN_PROMPT_RUNTIME,
            sections=ordered_sections,
            page_strategy=page_strategy,
            brand_data=brand_data,
            slot_specs_lookup=slot_specs_lookup,
            slot_contents=slot_contents,
            listicle_data=listicle_data,
        )

    def _build_blueprint_rewrite_config(
        self,
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
        blueprint: Dict,
        brand_profile: Dict,
        slot_metadata: Optional[Dict[str, Dict]] = None,
        listicle_from_html: Optional[Dict] = None,
    ) -> "_SlotRewriteConfig":
        """Build config for blueprint (section_guided) rewrite strategy.

        Computes section-level space_budget and injects it into section groups.
        Slot objects include target_range instead of max_words (AI-facing).
        slot_specs_lookup still has numeric max_words for internal regen/truncation.
        """
        brand_data, page_strategy = self._build_shared_brand_context(blueprint, brand_profile)

        # Compute section metrics and space budgets
        section_metrics = self._aggregate_section_metrics(slot_contents, slot_sections)
        space_budgets = self._format_section_space_budget(
            section_metrics, slot_contents, slot_sections
        )

        # Build section groups (same flow-ordering as runtime)
        section_groups: Dict[str, dict] = {}
        for slot_name, content in slot_contents.items():
            ctx = slot_sections.get(slot_name, {})
            sec_key = ctx.get("section_name", "global")
            flow = ctx.get("flow_order", 999)
            group_key = f"{flow:04d}_{sec_key}"
            if group_key not in section_groups:
                section_groups[group_key] = {
                    "section_name": sec_key,
                    "copy_direction": ctx.get("copy_direction", ""),
                    "brand_data": ctx.get("brand_mapping", {}),
                    "slots": [],
                }
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            meta = (slot_metadata or {}).get(slot_name)
            word_count = meta["word_count"] if meta and meta.get("word_count", 0) > 0 else 0
            char_count = meta["char_count"] if meta and meta.get("char_count", 0) > 0 else 0

            # Compute target_range for AI-facing slot object
            if word_count > 0:
                min_words = max(1, round(word_count * 0.85))
                max_words = max(min_words + 1, round(word_count * 1.10))
            else:
                default = self._SLOT_TYPE_DEFAULT_MAX_WORDS.get(slot_type, 80)
                min_words = max(1, round(default * 0.7))
                max_words = default

            # Blueprint slots: target_range instead of max_words
            section_groups[group_key]["slots"].append({
                "name": slot_name,
                "type": slot_type,
                "current": content,
                "target_range": [min_words, max_words],
            })

        ordered_sections = [section_groups[k] for k in sorted(section_groups.keys())]

        # Inject space_budget into section groups (not mutating originals)
        for group in ordered_sections:
            sec_name = group["section_name"]
            if sec_name in space_budgets:
                group["space_budget"] = space_budgets[sec_name]

        # Prefer pre-computed listicle data from S2 HTML; fall back to runtime detection
        listicle_data = listicle_from_html or self._detect_listicle_structure(slot_contents, slot_sections)
        listicle_prefixes = listicle_data.get("prefixes", {})
        if listicle_prefixes:
            for g in ordered_sections:
                for s in g["slots"]:
                    if s["name"] in listicle_prefixes:
                        s["prefix"] = listicle_prefixes[s["name"]]

        # Build slot_specs_lookup for internal regen/truncation (uses max_words)
        slot_specs_lookup: Dict[str, Dict] = {}
        for g in ordered_sections:
            for s in g["slots"]:
                slot_type = s["type"]
                slot_name = s["name"]
                # Use _compute_slot_length_spec for internal enforcement
                meta = (slot_metadata or {}).get(slot_name)
                if meta and meta.get("word_count", 0) > 0:
                    length_spec = self._compute_slot_length_spec(
                        slot_type, meta["word_count"], meta["char_count"]
                    )
                else:
                    length_spec = self._compute_slot_length_spec(slot_type, 0, 0)
                ctx = slot_sections.get(slot_name, {})
                spec = {
                    "max_words": length_spec["max_words"],
                    "type": slot_type,
                    "original_words": length_spec.get("original_words", 0),
                    "length_note": length_spec.get("length_note", ""),
                    "copy_direction": ctx.get("copy_direction", ""),
                    "section_name": ctx.get("section_name", "global"),
                }
                if slot_name in listicle_prefixes:
                    spec["prefix"] = listicle_prefixes[slot_name]
                slot_specs_lookup[slot_name] = spec

        return _SlotRewriteConfig(
            strategy="section_guided",
            system_prompt=self._SLOT_REWRITE_PROMPT_BASE + self._SLOT_REWRITE_ADDENDUM_BLUEPRINT,
            regen_prompt=self._REGEN_PROMPT_BLUEPRINT,
            sections=ordered_sections,
            page_strategy=page_strategy,
            brand_data=brand_data,
            slot_specs_lookup=slot_specs_lookup,
            slot_contents=slot_contents,
            listicle_data=listicle_data,
        )

    # ------------------------------------------------------------------
    # Listicle Detection & Numbering Enforcement
    # ------------------------------------------------------------------

    def _extract_listicle_from_html(self, html: str) -> Dict:
        """Extract pre-computed listicle data from surgery HTML data-listicle-* attributes.

        Reads data-listicle-prefix attributes injected by S2 element_classifier
        and returns the same dict format as _detect_listicle_structure():
            {"prefixes": {"heading-5": "1.", ...}, "total_count": N, "prefix_style": "numeric_dot"}

        Returns {} if no data-listicle-* attributes found (non-surgery HTML).
        """
        from html.parser import HTMLParser as _HTMLParser

        class _ListicleAttrReader(_HTMLParser):
            def __init__(self):
                super().__init__()
                self.prefixes: Dict[str, str] = {}
                self.prefix_style: Optional[str] = None

            def handle_starttag(self, tag, attrs):
                attr_dict = dict(attrs)
                slot_name = attr_dict.get("data-slot", "")
                listicle_prefix = attr_dict.get("data-listicle-prefix")
                if slot_name and listicle_prefix:
                    self.prefixes[slot_name] = listicle_prefix
                listicle_style = attr_dict.get("data-listicle-style")
                if listicle_style and self.prefix_style is None:
                    self.prefix_style = listicle_style

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

        reader = _ListicleAttrReader()
        try:
            reader.feed(html)
        except Exception:
            return {}

        if not reader.prefixes:
            return {}

        return {
            "prefixes": reader.prefixes,
            "total_count": len(reader.prefixes),
            "prefix_style": reader.prefix_style or "numeric_dot",
        }

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

    # Strips any leading ordinal pattern from AI output for re-prefixing
    _LEADING_ORDINAL_RE = re.compile(
        r'^(?:\d{1,2}[\.\)\:]\s*'
        r'|#\d{1,2}\s*'
        r'|(?:Reason|Step|Tip|Way|Thing|Secret|Benefit|Fact|Sign|Mistake)\s+\d{1,2}[\.\)\:]\s*)',
        re.IGNORECASE,
    )

    # Extracts total count from headline text: "7 Reasons...", "Top 10 Tips..."
    _LISTICLE_COUNT_RE = re.compile(
        r'(?:^|\s)(\d{1,2})\s+(?:Reason|Step|Tip|Way|Thing|Secret|Benefit|Fact|Sign|Mistake)s?\b',
        re.IGNORECASE,
    )

    def _detect_listicle_structure(
        self,
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
    ) -> Dict:
        """Detect if page has listicle structure and extract prefix mapping.

        Groups numbered headings by section to avoid interleaving when a page
        has multiple independent listicle sequences (e.g., sections A has items
        1-5 and section B has items 1-8). Each section is numbered independently
        and the sequences are concatenated in flow_order.

        Returns dict with:
            prefixes: {slot_name: "3." } mapping for heading slots
            total_count: int or None (extracted from headline)
            prefix_style: str ("numeric_dot", "numeric_paren", "hash", "word_prefix")
        Returns empty dict if not a listicle.
        """
        heading_types = {"heading", "subheadline"}

        # Group numbered headings by section
        section_matches: Dict[str, list] = {}
        section_flow_order: Dict[str, int] = {}
        all_heading_count = 0

        for slot_name, content in slot_contents.items():
            ctx = slot_sections.get(slot_name, {})
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            if slot_type not in heading_types:
                continue
            all_heading_count += 1

            text = content.strip()
            if self._LISTICLE_FALSE_POSITIVE_RE.match(text):
                continue
            m = self._LISTICLE_PREFIX_RE.match(text)
            if not m:
                continue
            prefix_str = m.group(0).rstrip()
            ordinal_m = self._LISTICLE_ORDINAL_RE.search(prefix_str)
            if not ordinal_m:
                continue
            ordinal = int(ordinal_m.group(1))
            if ordinal > 20:
                continue

            sec_key = ctx.get("section_name", "global")
            flow = ctx.get("flow_order", 999)
            if sec_key not in section_matches:
                section_matches[sec_key] = []
                section_flow_order[sec_key] = flow
            section_matches[sec_key].append({
                "slot_name": slot_name,
                "prefix": prefix_str,
                "ordinal": ordinal,
                "content": text,
            })

        # Flatten all matches for threshold check
        all_matches = [m for group in section_matches.values() for m in group]
        min_matches = 2 if all_heading_count <= 3 else 3
        if len(all_matches) < min_matches:
            return {}

        # Detect prefix style from the first match
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

        # Number each section independently, then concatenate in flow_order
        ordered_sections = sorted(section_matches.keys(),
                                  key=lambda s: section_flow_order[s])
        prefixes = {}
        running_ordinal = 0
        for sec_key in ordered_sections:
            group = section_matches[sec_key]
            group.sort(key=lambda x: x["ordinal"])
            for match in group:
                running_ordinal += 1
                correct_ordinal = str(running_ordinal)
                old_prefix = match["prefix"]
                if prefix_style == "hash":
                    prefixes[match["slot_name"]] = f"#{correct_ordinal}"
                elif prefix_style == "word_prefix":
                    word_m = re.match(r'([A-Za-z]+)', old_prefix)
                    word = word_m.group(1) if word_m else "Reason"
                    sep_m = re.search(r'[\.\)\:]', old_prefix)
                    sep = sep_m.group(0) if sep_m else "."
                    prefixes[match["slot_name"]] = f"{word} {correct_ordinal}{sep}"
                elif prefix_style == "numeric_paren":
                    prefixes[match["slot_name"]] = f"{correct_ordinal})"
                elif prefix_style == "numeric_colon":
                    prefixes[match["slot_name"]] = f"{correct_ordinal}:"
                else:
                    prefixes[match["slot_name"]] = f"{correct_ordinal}."

        # Try to extract total count from headline/subheadline
        total_count = None
        for slot_name, content in slot_contents.items():
            ctx = slot_sections.get(slot_name, {})
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            if slot_type in ("headline", "subheadline"):
                count_m = self._LISTICLE_COUNT_RE.search(content)
                if count_m:
                    total_count = int(count_m.group(1))
                    break

        logger.info(
            f"Listicle detected: {len(prefixes)} items across "
            f"{len(ordered_sections)} sections, "
            f"style={prefix_style}, total_count={total_count}"
        )
        return {
            "prefixes": prefixes,
            "total_count": total_count,
            "prefix_style": prefix_style,
        }

    def _enforce_listicle_numbering(
        self,
        all_rewrites: Dict[str, str],
        listicle_data: Dict,
    ) -> Dict[str, str]:
        """Post-processing: enforce correct listicle numbering on heading slots.

        Strips any leading ordinal from AI output and prepends the correct prefix.
        This is a deterministic safety net for when the AI ignores prefix instructions.
        """
        prefixes = listicle_data.get("prefixes", {})
        if not prefixes:
            return all_rewrites

        corrections = 0
        for slot_name, correct_prefix in prefixes.items():
            if slot_name not in all_rewrites:
                continue
            text = all_rewrites[slot_name]
            # Unescape for processing (will re-escape after)
            text_raw = _html_module.unescape(text)

            # Check if already correctly prefixed
            if text_raw.startswith(correct_prefix + " ") or text_raw.startswith(correct_prefix + "&"):
                continue

            # Strip any existing leading ordinal pattern
            stripped = self._LEADING_ORDINAL_RE.sub("", text_raw).lstrip()
            if not stripped:
                stripped = text_raw  # Don't lose content if regex ate everything

            # Prepend the correct prefix
            new_text = f"{correct_prefix} {stripped}"
            new_text_escaped = _html_module.escape(new_text)

            if new_text_escaped != text:
                logger.info(
                    f"Listicle fix '{slot_name}': '{text[:40]}...' -> '{new_text_escaped[:40]}...'"
                )
                all_rewrites[slot_name] = new_text_escaped
                corrections += 1

        if corrections:
            logger.info(f"Listicle numbering: {corrections} corrections applied")
        return all_rewrites

    # Common nav link words (nouns that appear in navigation menus)
    _NAV_LINK_WORDS = frozenset({
        'shop', 'store', 'cart', 'login', 'logout', 'signin', 'signup',
        'account', 'menu', 'home', 'about', 'contact', 'blog', 'faq',
        'help', 'search', 'podcast', 'story', 'our', 'my', 'your',
        'wishlist', 'checkout', 'orders', 'returns', 'shipping',
        'collections', 'products', 'catalog', 'newsletter', 'subscribe',
        'privacy', 'policy', 'terms', 'sitemap', 'reviews',
    })

    @staticmethod
    def _detect_nav_junk(text: str) -> bool:
        """Detect if text looks like navigation junk (e.g. 'Shop Our Story Podcast Login Cart').

        Heuristic: text is a sequence of navigation-style words with no sentence structure.
        Must match 50%+ nav link words and have no punctuation or articles/prepositions
        that would indicate real copy.
        """
        words = text.strip().split()
        if len(words) < 4:
            return False
        # Real sentences have punctuation
        has_punct = any(c in text for c in '.!?,;:')
        if has_punct:
            return False
        # Count how many words match nav link vocabulary
        nav_hits = sum(
            1 for w in words if w.lower().strip("'\"") in MockupService._NAV_LINK_WORDS
        )
        # Nav junk: 50%+ of words are nav links and at least 3 nav words
        if nav_hits >= 3 and nav_hits / len(words) >= 0.5:
            return True
        return False

    @staticmethod
    def _detect_incomplete_sentence(text: str, slot_type: str) -> bool:
        """Detect if a headline/subheadline/heading ends mid-sentence.

        Only checks headline-family slot types where incomplete thoughts are unacceptable.
        """
        if slot_type not in ("headline", "subheadline", "heading"):
            return False
        text = text.strip()
        if not text:
            return False
        # Ends with a preposition, article, conjunction, or "are/is/was/were" — mid-sentence
        last_word = text.split()[-1].lower().rstrip('.')
        mid_sentence_endings = {
            'the', 'a', 'an', 'and', 'or', 'but', 'for', 'to', 'in', 'on',
            'at', 'by', 'with', 'from', 'of', 'is', 'are', 'was', 'were',
            'finally', 'actually', 'really', 'their', 'your',
            'our', 'its', 'who', 'which', 'when', 'where', 'how', 'why',
        }
        if last_word in mid_sentence_endings:
            return True
        return False

    def _execute_slot_rewrite_pipeline(self, config: "_SlotRewriteConfig") -> Dict[str, str]:
        """Shared rewrite pipeline: batching, AI calls, validation, regen, original fallback.

        Args:
            config: Strategy-specific configuration from _build_*_rewrite_config().

        Returns {slot_name: rewritten_text} (plain text, HTML-escaped, dash-sanitized).
        """
        import json
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_sync_with_tracking

        strategy = config.strategy

        class SlotRewriteResult(BaseModel):
            rewrites: Dict[str, str] = Field(
                description="Map of slot_name to rewritten plain text content. "
                "Keys MUST exactly match the input slot names. "
                "Values MUST be plain text only - no HTML tags, no markdown."
            )

        # Batch by slot count
        batches: list = []
        current_batch: list = []
        current_count = 0
        for group in config.sections:
            group_size = len(group["slots"])
            if current_count + group_size > self._MAX_SLOTS_PER_BATCH and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_count = 0
            current_batch.append(group)
            current_count += group_size
        if current_batch:
            batches.append(current_batch)

        all_rewrites: Dict[str, str] = {}
        tone_summary = ""
        first_pass_over_length = 0
        quality_gate_failures = 0

        for batch_idx, batch_sections in enumerate(batches):
            payload = {
                "page_strategy": config.page_strategy,
                "brand": config.brand_data,
                "sections": [],
            }
            for g in batch_sections:
                section_payload = {
                    "section_name": g["section_name"],
                    "copy_direction": g["copy_direction"],
                    "brand_data": g["brand_data"],
                    "slots": g["slots"],
                }
                if "space_budget" in g:
                    section_payload["space_budget"] = g["space_budget"]
                payload["sections"].append(section_payload)

            if batch_idx > 0 and tone_summary:
                payload["prior_batch_tone"] = tone_summary

            batch_slot_names = set()
            for g in batch_sections:
                for s in g["slots"]:
                    batch_slot_names.add(s["name"])

            agent = Agent(
                model=Config.get_model("creative"),
                output_type=SlotRewriteResult,
                system_prompt=config.system_prompt,
                retries=2,
                output_retries=3,
            )

            try:
                result = run_agent_sync_with_tracking(
                    agent, json.dumps(payload, ensure_ascii=False),
                    tracker=self._usage_tracker,
                    user_id=self._user_id,
                    organization_id=self._organization_id,
                    tool_name="mockup_service",
                    operation=f"slot_rewrite_batch_{strategy}",
                    model_settings=ModelSettings(max_tokens=16384),
                )

                if result is None or result.output is None:
                    raise ValueError("AI slot rewrite returned no result")

                batch_rewrites = result.output.rewrites
                if not batch_rewrites:
                    raise ValueError("AI returned empty rewrites dict")

                # Post-validation pipeline
                validated: Dict[str, str] = {}
                for name, value in batch_rewrites.items():
                    if name not in batch_slot_names:
                        logger.warning(f"AI hallucinated slot '{name}' - stripping")
                        continue
                    clean = re.sub(r'<[^>]+>', '', str(value))
                    clean = _sanitize_dashes(clean)
                    clean = _html_module.escape(clean)
                    spec = config.slot_specs_lookup.get(name)
                    slot_type = spec["type"] if spec else "body"
                    # Quality gate: nav junk detection
                    if self._detect_nav_junk(clean):
                        logger.warning(
                            f"Quality gate: slot '{name}' looks like nav junk: "
                            f"'{clean[:60]}...' — falling back to original"
                        )
                        clean = _html_module.escape(config.slot_contents.get(name, ""))
                        quality_gate_failures += 1
                    # Quality gate: incomplete headline detection
                    elif self._detect_incomplete_sentence(clean, slot_type):
                        logger.warning(
                            f"Quality gate: slot '{name}' ({slot_type}) ends mid-sentence: "
                            f"'{clean[:60]}...' — marking for regen"
                        )
                        first_pass_over_length += 1  # will be picked up by regen
                    # Log over-length slots (enforcement in regen loop)
                    if spec:
                        word_count = len(clean.split())
                        if word_count > spec["max_words"]:
                            first_pass_over_length += 1
                            logger.info(
                                f"Slot '{name}' over-length (strategy={strategy}): "
                                f"{word_count} words (max {spec['max_words']}, type={spec['type']})"
                            )
                    validated[name] = clean

                # Inline listicle prefix enforcement per batch
                listicle_prefixes = config.listicle_data.get("prefixes", {})
                if listicle_prefixes:
                    for name, clean in validated.items():
                        prefix = config.slot_specs_lookup.get(name, {}).get("prefix")
                        if not prefix:
                            continue
                        clean_raw = _html_module.unescape(clean)
                        if not clean_raw.startswith(prefix + " "):
                            stripped = self._LEADING_ORDINAL_RE.sub("", clean_raw).lstrip()
                            if stripped:
                                fixed = _html_module.escape(f"{prefix} {stripped}")
                                validated[name] = fixed

                # Fill missing slots with original text
                missing = batch_slot_names - set(validated.keys())
                if missing:
                    logger.warning(
                        f"AI missed {len(missing)} slots in batch {batch_idx} "
                        f"(strategy={strategy}): "
                        f"{sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}"
                    )
                    for name in missing:
                        validated[name] = _html_module.escape(config.slot_contents.get(name, ""))

                all_rewrites.update(validated)

                # Build tone summary for subsequent batches
                if batch_idx == 0 and len(batches) > 1:
                    headline_val = validated.get("headline", "")
                    listicle_ctx = ""
                    if config.listicle_data:
                        total = config.listicle_data.get("total_count") or len(listicle_prefixes)
                        prior = [p for sn, p in listicle_prefixes.items() if sn in validated]
                        listicle_ctx = (
                            f" Page is a {total}-item listicle."
                            f" Items written so far: {', '.join(prior)}."
                        )
                    tone_summary = (
                        f"Brand: {config.brand_data['name']}. "
                        f"Voice: {config.brand_data['voice_tone']}. "
                        f"Headline written: {headline_val[:100]}. "
                        f"Primary angle: {config.page_strategy.get('primary_angle', '')}."
                        f"{listicle_ctx}"
                    )

            except Exception as e:
                logger.error(f"Slot rewrite batch {batch_idx} failed (strategy={strategy}): {e}")
                for name in batch_slot_names:
                    if name not in all_rewrites:
                        all_rewrites[name] = _html_module.escape(
                            config.slot_contents.get(name, "")
                        )

        if not all_rewrites:
            logger.error("All slot rewrite batches failed - falling back to _build_slot_map")
            return self._build_slot_map({})

        # ── Re-generation loop for over-length slots (batched) ────
        MAX_REGEN_ROUNDS = 3
        MAX_REGEN_BATCH_SIZE = 12
        regen_count = 0

        for regen_round in range(MAX_REGEN_ROUNDS):
            # Collect violations: over-length OR incomplete headlines
            violations: Dict[str, Dict] = {}
            for name, text in all_rewrites.items():
                spec = config.slot_specs_lookup.get(name)
                if not spec:
                    continue
                word_count = len(text.split())
                slot_type = spec["type"]
                is_over_length = word_count > spec["max_words"]
                is_incomplete = self._detect_incomplete_sentence(text, slot_type)
                if is_over_length or is_incomplete:
                    violations[name] = {
                        "current_text": text,
                        "current_words": word_count,
                        "max_words": spec["max_words"],
                        "type": slot_type,
                        "length_note": spec.get("length_note", ""),
                        "reason": "over_length" if is_over_length else "incomplete_sentence",
                    }

            if not violations:
                logger.info(
                    f"All slots within spec after round {regen_round} "
                    f"(strategy={strategy})"
                )
                break

            logger.info(
                f"Regen round {regen_round + 1}/{MAX_REGEN_ROUNDS} "
                f"(strategy={strategy}): {len(violations)} slots need regen "
                f"({sum(1 for v in violations.values() if v['reason'] == 'over_length')} over-length, "
                f"{sum(1 for v in violations.values() if v['reason'] == 'incomplete_sentence')} incomplete)"
            )

            # Batch violations into groups of MAX_REGEN_BATCH_SIZE with section affinity
            violation_items = list(violations.items())
            # Sort by section for affinity (same-section slots stay together)
            violation_items.sort(
                key=lambda x: config.slot_specs_lookup.get(x[0], {}).get("section_name", "")
            )
            regen_batches = [
                violation_items[i:i + MAX_REGEN_BATCH_SIZE]
                for i in range(0, len(violation_items), MAX_REGEN_BATCH_SIZE)
            ]

            round_success = 0
            for rb_idx, regen_batch in enumerate(regen_batches):
                batch_violations = dict(regen_batch)
                logger.info(
                    f"Regen batch {rb_idx + 1}/{len(regen_batches)} "
                    f"(round {regen_round + 1}, {len(batch_violations)} slots)"
                )

                # Build regen payload — blueprint mode includes copy_direction/section_name
                listicle_prefixes = config.listicle_data.get("prefixes", {})
                if strategy == "section_guided":
                    regen_slots = []
                    for name, v in batch_violations.items():
                        slot_entry = {
                            "name": name,
                            "current_text": v["current_text"],
                            "current_words": v["current_words"],
                            "target_words": v["max_words"],
                            "type": v["type"],
                            "reason": v["reason"],
                            "copy_direction": config.slot_specs_lookup.get(name, {}).get(
                                "copy_direction", ""
                            ),
                            "section_name": config.slot_specs_lookup.get(name, {}).get(
                                "section_name", ""
                            ),
                        }
                        if name in listicle_prefixes:
                            slot_entry["prefix"] = listicle_prefixes[name]
                        regen_slots.append(slot_entry)
                    regen_payload = {
                        "task": "Rewrite these slots to fit within target_words while maintaining persuasive power.",
                        "slots": regen_slots,
                    }
                else:
                    regen_slots = []
                    for name, v in batch_violations.items():
                        slot_entry = {
                            "name": name,
                            "current_text": v["current_text"],
                            "current_words": v["current_words"],
                            "max_words": v["max_words"],
                            "type": v["type"],
                            "reason": v["reason"],
                            "length_note": v["length_note"],
                        }
                        if name in listicle_prefixes:
                            slot_entry["prefix"] = listicle_prefixes[name]
                        regen_slots.append(slot_entry)
                    regen_payload = {
                        "task": "Rewrite these slots to fit within max_words while maintaining persuasive power.",
                        "slots": regen_slots,
                    }

                try:
                    regen_agent = Agent(
                        model=Config.get_model("creative"),
                        output_type=SlotRewriteResult,
                        system_prompt=config.regen_prompt,
                        retries=1,
                        output_retries=2,
                    )
                    regen_result = run_agent_sync_with_tracking(
                        regen_agent, json.dumps(regen_payload, ensure_ascii=False),
                        tracker=self._usage_tracker,
                        user_id=self._user_id,
                        organization_id=self._organization_id,
                        tool_name="mockup_service",
                        operation=f"slot_regen_{strategy}_b{rb_idx}",
                        model_settings=ModelSettings(max_tokens=4096),
                    )
                    if regen_result and regen_result.output and regen_result.output.rewrites:
                        for name, value in regen_result.output.rewrites.items():
                            if name not in batch_violations:
                                continue
                            clean = re.sub(r'<[^>]+>', '', str(value))
                            clean = _sanitize_dashes(clean)
                            clean = _html_module.escape(clean)
                            # Quality gate on regen output too
                            slot_type = batch_violations[name]["type"]
                            if self._detect_nav_junk(clean):
                                logger.warning(
                                    f"Regen quality gate: '{name}' still nav junk, keeping original"
                                )
                                continue
                            all_rewrites[name] = clean
                            regen_count += 1
                            round_success += 1
                            new_wc = len(clean.split())
                            logger.info(
                                f"Regen slot '{name}' (strategy={strategy}): "
                                f"{batch_violations[name]['current_words']} -> {new_wc} words "
                                f"(max {batch_violations[name]['max_words']})"
                            )
                except Exception as e:
                    logger.warning(
                        f"Regen batch {rb_idx + 1} round {regen_round + 1} failed "
                        f"(strategy={strategy}): {e}"
                    )

            if round_success == 0:
                logger.warning(
                    f"Regen round {regen_round + 1} produced no improvements, stopping"
                )
                break

        # ── Listicle numbering enforcement (deterministic safety net) ──
        if config.listicle_data:
            all_rewrites = self._enforce_listicle_numbering(all_rewrites, config.listicle_data)

        # ── Original text fallback (NO truncation) ────────────────
        # Any remaining over-length slots get their original text preserved
        # rather than being truncated (which destroys meaning).
        kept_original_count = 0
        for name, text in list(all_rewrites.items()):
            spec = config.slot_specs_lookup.get(name)
            if not spec:
                continue
            word_count = len(text.split())
            slot_type = spec["type"]
            is_over_length = word_count > spec["max_words"]
            is_incomplete = self._detect_incomplete_sentence(text, slot_type)
            is_nav_junk = self._detect_nav_junk(text)
            if is_nav_junk or is_incomplete:
                original = _html_module.escape(config.slot_contents.get(name, ""))
                if original.strip():
                    logger.info(
                        f"Falling back to original for '{name}' "
                        f"(strategy={strategy}, reason={'nav_junk' if is_nav_junk else 'incomplete'}): "
                        f"'{text[:50]}...' -> original"
                    )
                    all_rewrites[name] = original
                    kept_original_count += 1
            elif is_over_length:
                logger.info(
                    f"Keeping over-length rewrite for '{name}' (strategy={strategy}): "
                    f"{word_count} words (max {spec['max_words']}), regen exhausted"
                )

        # ── Compliance stats ──────────────────────────────────────
        total_slots = len(all_rewrites)
        first_pass_ok = total_slots - first_pass_over_length
        logger.info(
            f"Slot rewrite complete (strategy={strategy}): "
            f"{first_pass_ok}/{total_slots} within spec first-pass, "
            f"{regen_count} regen'd, {kept_original_count} kept original, "
            f"{quality_gate_failures} quality gate failures"
        )

        return all_rewrites

    # ------------------------------------------------------------------
    # Selective Slot Regeneration (partial rewrite)
    # ------------------------------------------------------------------

    def _execute_selective_regen(
        self,
        frozen_slots: List[Dict],
        regenerate_sections: List[Dict],
        brand_data: Dict,
        page_strategy: Dict,
        slot_specs_lookup: Dict[str, Dict],
        slot_contents: Dict[str, str],
        listicle_data: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """Run AI selective regen for a subset of slots with frozen context.

        Args:
            frozen_slots: [{name, section_name, type, content}] — read-only context.
            regenerate_sections: Ordered section groups with slots to rewrite.
            brand_data: Brand context from _build_shared_brand_context.
            page_strategy: Page strategy from _build_shared_brand_context.
            slot_specs_lookup: {slot_name: {max_words, type, ...}} for regen slots.
            slot_contents: Original {slot_name: text} for fallback.
            listicle_data: Optional listicle prefix data.

        Returns {slot_name: rewritten_text} for regenerated slots only.
        """
        import json
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_sync_with_tracking

        class SlotRewriteResult(BaseModel):
            rewrites: Dict[str, str] = Field(
                description="Map of slot_name to rewritten plain text content. "
                "Keys MUST exactly match the regenerate_slot names. "
                "Values MUST be plain text only - no HTML tags, no markdown."
            )

        # Collect all regen slot names
        regen_slot_names: set = set()
        for g in regenerate_sections:
            for s in g["slots"]:
                regen_slot_names.add(s["name"])

        payload = {
            "page_strategy": page_strategy,
            "brand": brand_data,
            "frozen_slots": frozen_slots,
            "regenerate_sections": regenerate_sections,
        }

        agent = Agent(
            model=Config.get_model("creative"),
            output_type=SlotRewriteResult,
            system_prompt=self._SELECTIVE_REGEN_SYSTEM_PROMPT,
            retries=2,
            output_retries=3,
        )

        try:
            result = run_agent_sync_with_tracking(
                agent, json.dumps(payload, ensure_ascii=False),
                tracker=self._usage_tracker,
                user_id=self._user_id,
                organization_id=self._organization_id,
                tool_name="mockup_service",
                operation="selective_slot_regen",
                model_settings=ModelSettings(max_tokens=16384),
            )

            if result is None or result.output is None:
                raise ValueError("AI selective regen returned no result")

            batch_rewrites = result.output.rewrites
            if not batch_rewrites:
                raise ValueError("AI returned empty rewrites dict")

            # Post-validation
            validated: Dict[str, str] = {}
            listicle_prefixes = (listicle_data or {}).get("prefixes", {})
            for name, value in batch_rewrites.items():
                if name not in regen_slot_names:
                    logger.warning(f"AI hallucinated slot '{name}' in selective regen - stripping")
                    continue
                clean = re.sub(r'<[^>]+>', '', str(value))
                clean = _sanitize_dashes(clean)
                clean = _html_module.escape(clean)
                spec = slot_specs_lookup.get(name)
                slot_type = spec["type"] if spec else "body"

                # Quality gate: nav junk
                if self._detect_nav_junk(clean):
                    logger.warning(f"Quality gate: selective regen slot '{name}' is nav junk — falling back")
                    clean = _html_module.escape(slot_contents.get(name, ""))
                # Quality gate: incomplete sentence (mark for regen loop)
                elif self._detect_incomplete_sentence(clean, slot_type):
                    logger.warning(f"Quality gate: selective regen slot '{name}' incomplete — marking for regen")

                validated[name] = clean

            # Listicle prefix enforcement
            if listicle_prefixes:
                for name, clean in validated.items():
                    prefix = slot_specs_lookup.get(name, {}).get("prefix")
                    if not prefix:
                        continue
                    clean_raw = _html_module.unescape(clean)
                    if not clean_raw.startswith(prefix + " "):
                        stripped = self._LEADING_ORDINAL_RE.sub("", clean_raw).lstrip()
                        if stripped:
                            validated[name] = _html_module.escape(f"{prefix} {stripped}")

            # Fill missing regen slots with original text
            missing = regen_slot_names - set(validated.keys())
            if missing:
                logger.warning(f"AI missed {len(missing)} selective regen slots: {sorted(missing)[:10]}")
                for name in missing:
                    validated[name] = _html_module.escape(slot_contents.get(name, ""))

        except Exception as e:
            logger.error(f"Selective slot regen failed: {e}")
            # Fallback: return original text for all requested slots
            validated = {}
            for name in regen_slot_names:
                validated[name] = _html_module.escape(slot_contents.get(name, ""))

        # ── Regen loop for over-length slots ──
        MAX_REGEN_ROUNDS = 2
        for regen_round in range(MAX_REGEN_ROUNDS):
            violations: Dict[str, Dict] = {}
            for name, text in validated.items():
                spec = slot_specs_lookup.get(name)
                if not spec:
                    continue
                word_count = len(text.split())
                slot_type = spec["type"]
                is_over = word_count > spec["max_words"]
                is_incomplete = self._detect_incomplete_sentence(text, slot_type)
                if is_over or is_incomplete:
                    violations[name] = {
                        "current_text": text,
                        "current_words": word_count,
                        "max_words": spec["max_words"],
                        "type": slot_type,
                        "reason": "over_length" if is_over else "incomplete_sentence",
                    }

            if not violations:
                break

            logger.info(f"Selective regen round {regen_round + 1}: {len(violations)} slots need regen")

            regen_slots = []
            for name, v in violations.items():
                slot_entry = {
                    "name": name,
                    "current_text": v["current_text"],
                    "current_words": v["current_words"],
                    "max_words": v["max_words"],
                    "type": v["type"],
                    "reason": v["reason"],
                }
                if name in (listicle_data or {}).get("prefixes", {}):
                    slot_entry["prefix"] = listicle_data["prefixes"][name]
                regen_slots.append(slot_entry)

            regen_payload = {
                "task": "Rewrite these slots to fit within max_words while maintaining persuasive power.",
                "slots": regen_slots,
            }

            try:
                regen_agent = Agent(
                    model=Config.get_model("creative"),
                    output_type=SlotRewriteResult,
                    system_prompt=self._SELECTIVE_REGEN_PROMPT,
                    retries=1,
                    output_retries=2,
                )
                regen_result = run_agent_sync_with_tracking(
                    regen_agent, json.dumps(regen_payload, ensure_ascii=False),
                    tracker=self._usage_tracker,
                    user_id=self._user_id,
                    organization_id=self._organization_id,
                    tool_name="mockup_service",
                    operation=f"selective_regen_fix_r{regen_round}",
                    model_settings=ModelSettings(max_tokens=4096),
                )
                if regen_result and regen_result.output and regen_result.output.rewrites:
                    improved = 0
                    for name, value in regen_result.output.rewrites.items():
                        if name not in violations:
                            continue
                        clean = re.sub(r'<[^>]+>', '', str(value))
                        clean = _sanitize_dashes(clean)
                        clean = _html_module.escape(clean)
                        if not self._detect_nav_junk(clean):
                            validated[name] = clean
                            improved += 1
                    if improved == 0:
                        break
            except Exception as e:
                logger.warning(f"Selective regen fix round {regen_round + 1} failed: {e}")
                break

        # Final fallback: keep original for nav junk / incomplete
        for name, text in list(validated.items()):
            spec = slot_specs_lookup.get(name)
            if not spec:
                continue
            slot_type = spec["type"]
            if self._detect_nav_junk(text) or self._detect_incomplete_sentence(text, slot_type):
                original = _html_module.escape(slot_contents.get(name, ""))
                if original.strip():
                    validated[name] = original

        logger.info(f"Selective regen complete: {len(validated)} slots rewritten")
        return validated

    # ------------------------------------------------------------------
    # AI Vision Generation
    # ------------------------------------------------------------------

    _MARKDOWN_TEXT_BUDGET = 30_000  # Max chars for page markdown in prompt
    _PROMPT_TEXT_BUDGET = 40_000   # Total text budget before image

    def _truncate_markdown_for_prompt(self, markdown: str, max_chars: int) -> str:
        """Truncate markdown at a heading boundary to preserve complete sections."""
        if len(markdown) <= max_chars:
            return markdown
        # Find last heading boundary before max_chars
        search_region = markdown[:max_chars]
        for pattern in (r'\n## ', r'\n### ', r'\n# '):
            matches = list(re.finditer(pattern, search_region))
            if matches:
                cut_point = matches[-1].start()
                if cut_point > max_chars // 2:  # Don't cut too early
                    return markdown[:cut_point] + "\n\n[... content truncated ...]"
        # Fallback: cut at last paragraph break
        last_break = search_region.rfind('\n\n')
        if last_break > max_chars // 2:
            return markdown[:last_break] + "\n\n[... content truncated ...]"
        return markdown[:max_chars] + "\n\n[... content truncated ...]"

    def _build_vision_prompt(
        self,
        page_markdown: Optional[str] = None,
        reinforce_slots: bool = False,
        image_urls: Optional[List[Dict]] = None,
    ) -> str:
        """Build the prompt for Gemini vision HTML generation.

        Args:
            page_markdown: Optional scraped page text to include as reference.
            reinforce_slots: If True, add extra emphasis on slot marking (retry mode).
            image_urls: Optional validated image URLs from page markdown.
        """
        parts = []

        # Core instructions (never truncated)
        parts.append(
            "Analyze this landing page screenshot and generate a faithful HTML/CSS recreation.\n\n"
            "## LAYOUT REQUIREMENTS\n"
            "- Use semantic HTML: <section>, <header>, <nav>, <footer>, <article>\n"
            "- Add data-section attributes to top-level sections (e.g., data-section=\"hero\")\n"
            "- Center content with max-width: 1200px; margin: 0 auto on main containers\n"
            "- Use flexbox for row layouts (display: flex; gap: ...; align-items: center)\n"
            "- Use CSS grid for card/feature grids (grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)))\n"
            "- Assume a desktop viewport width of 1440px\n"
            "- Match section HEIGHT proportions from the screenshot: compact sections stay compact, tall sections stay tall\n"
            "- Side-by-side layouts in the screenshot MUST remain side-by-side (use flexbox or grid, do NOT stack vertically)\n"
            "- Do NOT expand or compress sections beyond their visual proportions in the screenshot\n\n"
            "## TYPOGRAPHY\n"
            "- Use system font stack: font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif\n"
            "- h1: font-size 2.5-3.5rem, font-weight 700-800\n"
            "- h2: font-size 1.8-2.2rem, font-weight 600-700\n"
            "- h3: font-size 1.3-1.6rem, font-weight 600\n"
            "- Body text: font-size 1-1.1rem, line-height 1.6-1.8\n"
            "- Extract EXACT hex colors from the screenshot for text, backgrounds, and accents\n\n"
            "## SPACING & VISUAL\n"
            "- Consistent section padding: 60-80px vertical, 20-40px horizontal\n"
            "- Element margins: 16-24px between paragraphs, 32-48px between groups\n"
            "- Reproduce button styles precisely: padding, border-radius, background color, hover states\n"
            "- Reproduce background colors/gradients for each section\n\n"
            "## IMAGE SIZING (CRITICAL)\n"
            "- Match image sizes to their ACTUAL proportions visible in the screenshot.\n"
            "- Small circular images (avatars, author photos): use explicit width/height (48-80px) with border-radius: 50%.\n"
            "- Thumbnail images: constrain with width/max-width appropriate to their visual size in the screenshot.\n"
            "- Hero/banner images: width: 100% of their container.\n"
            "- Product images in grids: consistent sizing within their grid cell.\n"
            "- ALL images: include max-width: 100% to prevent overflow.\n"
            "- Do NOT render small images as full-width. If an image is small in the screenshot, it must be small in the HTML.\n\n"
            "## CSS APPROACH\n"
            "- Use a <style> block in <head> for shared/repeated styles (classes, section styles)\n"
            "- Use inline style= for one-off overrides (specific colors, unique spacing)\n"
            "- Prefer class-based CSS for maintainability\n\n"
            "## TEXT CONTENT (CRITICAL - NO HALLUCINATION)\n"
            "- Reproduce ONLY text that is VISIBLE in the screenshot. Do NOT add, summarize, or rephrase.\n"
            "- If text is hard to read in the screenshot, check the PAGE TEXT CONTENT section below.\n"
            "- If text does NOT appear in EITHER the screenshot OR the PAGE TEXT CONTENT section, DO NOT include it.\n"
            "- NEVER add introductory paragraphs, summaries, transitions, or any text not on the original page.\n"
            "- When in doubt, OMIT the text rather than invent it.\n\n"
        )

        # Slot marking contract (never truncated)
        parts.append(
            "## SLOT MARKING CONTRACT (CRITICAL)\n"
            "Mark each replaceable text element with a data-slot attribute using "
            "this EXACT naming convention (numbered sequentially top-to-bottom):\n"
            '- data-slot="headline" on the main hero headline\n'
            '- data-slot="subheadline" on the hero subheadline\n'
            '- data-slot="cta-1", "cta-2", etc. on call-to-action buttons\n'
            '- data-slot="heading-1", "heading-2", etc. on section headings\n'
            '- data-slot="body-1", "body-2", etc. on section body text\n'
            '- data-slot="testimonial-1", etc. on testimonial quotes\n'
            '- data-slot="feature-1", etc. on feature descriptions\n'
            '- data-slot="price" on pricing text\n'
            '- data-slot="guarantee" on guarantee/risk-reversal text\n\n'
        )

        # Slot reinforcement (retry mode)
        if reinforce_slots:
            parts.append(
                "## IMPORTANT: SLOT MARKING REINFORCEMENT\n"
                "Your previous output was missing data-slot attributes. This is CRITICAL.\n"
                "EVERY piece of replaceable text MUST have a data-slot attribute.\n"
                "At minimum, include: headline, subheadline, at least one cta, "
                "and body text slots.\n\n"
            )

        # Image URLs section
        if image_urls:
            parts.append("## ACTUAL IMAGE URLs\n")
            parts.append(
                "Use actual <img> tags with these validated URLs where they match "
                "content visible in the screenshot. For images without a matching URL, "
                "use colored placeholder divs with descriptive labels.\n"
                "IMPORTANT: Set width/height on each <img> to match the image's "
                "apparent size in the screenshot. Do NOT make all images full-width.\n\n"
            )
            for img in image_urls[:20]:
                alt = img.get("alt", "")[:80]
                url = img.get("url", "")
                parts.append(f'- {alt}: {url}\n')
            parts.append("\n")
        else:
            parts.append(
                "## IMAGES\n"
                "Use colored placeholder divs with descriptive labels for all images.\n\n"
            )

        # Page markdown (truncated to budget)
        if page_markdown and page_markdown.strip():
            truncated = self._truncate_markdown_for_prompt(
                page_markdown, self._MARKDOWN_TEXT_BUDGET
            )
            parts.append(
                "## PAGE TEXT CONTENT (source of truth for text)\n"
                "This is the EXACT text content scraped from the original page. Rules:\n"
                "1. The screenshot determines LAYOUT and VISUAL DESIGN (colors, spacing, structure).\n"
                "2. This text section determines WHAT TEXT to include.\n"
                "3. Do NOT include any text that does not appear in this section "
                "(unless clearly visible in the screenshot and missing from the scrape).\n"
                "4. Do NOT rephrase, summarize, or add transitions between sections.\n"
                "5. Copy text VERBATIM - preserve exact wording, capitalization, and punctuation.\n\n"
                f"{truncated}\n\n"
            )

        parts.append("Output ONLY the complete HTML document, no explanation or code fences.")

        return ''.join(parts)

    def get_phase_snapshots(self) -> Dict[str, str]:
        """Return phase snapshots from the last multipass run.

        Keys: phase_1_skeleton, phase_2_content, phase_3_refined, phase_4_final.
        Each value is raw HTML at that pipeline stage.
        """
        return getattr(self, '_last_phase_snapshots', {})

    def _generate_via_multipass(
        self,
        screenshot_b64: str,
        page_markdown: Optional[str] = None,
        page_url: Optional[str] = None,
        element_detection: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Any] = None,
        page_html: Optional[str] = None,
    ) -> str:
        """Run the 5-phase multipass pipeline via ThreadPoolExecutor + asyncio.run().

        Returns raw HTML only -- no sanitization, no validation, no wrapping.
        All post-processing is owned by generate_analysis_mockup().
        """
        import asyncio
        import concurrent.futures
        from viraltracker.core.observability import get_logfire
        from viraltracker.services.gemini_service import GeminiService
        from .multipass.pipeline import MultiPassPipeline

        lf = get_logfire()
        lf.info("Starting multipass pipeline", page_url=page_url or "unknown")

        # Capture OpenTelemetry context from the main thread so spans
        # created in the child thread are parented correctly in Logfire
        try:
            from opentelemetry import context as otel_context
            parent_ctx = otel_context.get_current()
        except ImportError:
            parent_ctx = None

        gemini = GeminiService()
        if self._usage_tracker:
            gemini.set_tracking_context(
                self._usage_tracker, self._user_id, self._organization_id
            )

        pipeline = MultiPassPipeline(
            gemini_service=gemini,
            progress_callback=progress_callback,
        )

        async def _run():
            # Attach parent OTel context in child thread so logfire spans
            # are parented to the main trace
            if parent_ctx is not None:
                otel_context.attach(parent_ctx)
            return await pipeline.generate(
                screenshot_b64=screenshot_b64,
                page_markdown=page_markdown or "",
                page_url=page_url,
                element_detection=element_detection,
                page_html=page_html,
            )

        # Sync wrapper -- same pattern as _generate_via_ai_vision
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                raw = pool.submit(asyncio.run, _run()).result()
        else:
            raw = asyncio.run(_run())

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        # Expose phase snapshots for debugging/evaluation
        self._last_phase_snapshots = dict(pipeline.phase_snapshots)
        # Detect surgery pipeline — set flag for CSS sanitization
        self.is_surgery_mode = "phase_s0_sanitized" in self._last_phase_snapshots
        snapshot_summary = {
            k: len(v) for k, v in self._last_phase_snapshots.items()
        }

        lf.info(
            "Multipass pipeline returned {output_chars} chars, "
            "snapshots: {snapshot_summary}",
            output_chars=len(raw),
            snapshot_summary=snapshot_summary,
        )
        return raw

    def _generate_via_ai_vision(
        self,
        screenshot_b64: str,
        page_markdown: Optional[str] = None,
        reinforce_slots: bool = False,
        page_url: Optional[str] = None,
    ) -> str:
        """Send screenshot (+optional markdown) to Gemini, get back HTML.

        Args:
            screenshot_b64: Base64-encoded screenshot.
            page_markdown: Optional scraped page text for multi-modal input.
            reinforce_slots: If True, add extra slot emphasis (retry mode).
            page_url: Optional page URL for resolving relative image URLs.
        """
        import asyncio
        from viraltracker.services.gemini_service import GeminiService

        gemini = GeminiService()
        if self._usage_tracker:
            gemini.set_tracking_context(
                self._usage_tracker, self._user_id, self._organization_id
            )

        # Extract and validate image URLs from markdown
        image_urls = None
        if page_markdown and page_url:
            image_urls = self._extract_image_urls(page_markdown, page_url)

        prompt = self._build_vision_prompt(
            page_markdown=page_markdown,
            reinforce_slots=reinforce_slots,
            image_urls=image_urls,
        )

        # Sync wrapper — handles both running and non-running event loops
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                raw = pool.submit(asyncio.run, gemini.analyze_image(screenshot_b64, prompt)).result()
        else:
            raw = asyncio.run(gemini.analyze_image(screenshot_b64, prompt))

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        return raw

    # ------------------------------------------------------------------
    # Markdown Fallback
    # ------------------------------------------------------------------

    def _markdown_to_html(self, markdown_text: str) -> str:
        """Convert page markdown to HTML. Raw HTML passthrough is disabled for safety."""
        from markdown_it import MarkdownIt
        md = MarkdownIt().disable("html_block").disable("html_inline")
        return md.render(markdown_text)

    # ------------------------------------------------------------------
    # CSS Extraction & Style Block Handling
    # ------------------------------------------------------------------

    def _extract_and_sanitize_css(self, raw_html: str) -> Tuple[str, str]:
        """Extract <style> blocks from HTML, sanitize them, and return both.

        Returns (html_without_styles, sanitized_css). This is the single source
        of both extraction AND removal, ensuring atomicity.
        """
        # Extract all <style> block contents
        style_contents = re.findall(
            r'<style[^>]*>(.*?)</style>',
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Sanitize each block
        sanitized_parts = []
        for content in style_contents:
            sanitized = _sanitize_css_block(content, self.is_surgery_mode)
            if sanitized.strip():
                sanitized_parts.append(sanitized)
        sanitized_css = '\n'.join(sanitized_parts)

        # Strip all <style> blocks from HTML (atomically with extraction)
        html_without_styles = re.sub(
            r'<style[^>]*>.*?</style>', '', raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        return html_without_styles, sanitized_css

    def _extract_page_css_and_strip(self, wrapped_html: str) -> Tuple[str, str]:
        """Extract page CSS and strip wrapper. Returns (body, sanitized_css).

        Unlike _strip_mockup_wrapper() which returns str, this method
        returns a tuple for use in blueprint generation where CSS
        must be carried through.
        """
        # 1. Extract <style class="page-css"> content
        css_matches = re.findall(
            r'<style[^>]*class=["\'][^"\']*\bpage-css\b[^"\']*["\'][^>]*>(.*?)</style>',
            wrapped_html, flags=re.IGNORECASE | re.DOTALL,
        )
        page_css = '\n'.join(css_matches) if css_matches else ""

        # 2. Re-sanitize CSS (defense-in-depth: DB rows may be old/pre-sanitization)
        if page_css:
            page_css = _sanitize_css_block(page_css, self.is_surgery_mode)

        # 3. Strip wrapper normally
        body = self._strip_mockup_wrapper(wrapped_html)

        return body, page_css

    # Regex matching Shopify chrome section IDs (header, footer, mega menu)
    _SHOPIFY_CHROME_ID_RE = re.compile(
        r'(header|footer|mega[_-]?menu)', re.IGNORECASE
    )

    # Anti-scraping overlay: position:absolute with huge z-index and transparent text
    _ANTI_SCRAPE_OVERLAY_RE = re.compile(
        r'z-index:\s*\d{8,}.*?color:\s*transparent', re.IGNORECASE
    )

    def _strip_shopify_chrome(self, html: str) -> str:
        """Remove Shopify theme chrome (header, footer, nav, mega menu) from surgery HTML.

        Surgery pipeline captures the full Shopify page DOM including theme sections
        that are normally hidden by JS or positioned off-screen. These become visible
        junk when rendered without the Shopify theme JS.

        Also strips anti-scraping overlay divs (position:absolute, huge z-index, transparent).

        Only meaningful in surgery mode. Returns html unchanged for non-surgery output.
        """
        if not self.is_surgery_mode:
            return html

        class _ChromeStripper(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.parts: list = []
                self._skip_depth: int = 0
                self._skip_tag: str = ""
                self._chrome_id_re = MockupService._SHOPIFY_CHROME_ID_RE
                self._anti_scrape_re = MockupService._ANTI_SCRAPE_OVERLAY_RE
                self._stripped_count: int = 0

            def _should_strip(self, tag: str, attrs: list) -> bool:
                """Check if this element is Shopify chrome or an anti-scraping overlay."""
                attr_dict = dict(attrs)

                # Shopify section chrome: id contains header/footer/mega_menu
                elem_id = attr_dict.get("id", "")
                if elem_id.startswith("shopify-section") and self._chrome_id_re.search(elem_id):
                    return True

                # Anti-scraping overlay: huge z-index + transparent text
                style = attr_dict.get("style", "")
                if style and self._anti_scrape_re.search(style):
                    return True

                return False

            def handle_starttag(self, tag, attrs):
                if self._skip_depth > 0:
                    if tag == self._skip_tag:
                        self._skip_depth += 1
                    return

                if self._should_strip(tag, attrs):
                    self._skip_depth = 1
                    self._skip_tag = tag
                    self._stripped_count += 1
                    return

                attr_str = ""
                for name, value in attrs:
                    if value is None:
                        attr_str += f" {name}"
                    else:
                        attr_str += f' {name}="{_html_module.escape(value, quote=True)}"'
                self.parts.append(f"<{tag}{attr_str}>")

            def handle_endtag(self, tag):
                if self._skip_depth > 0:
                    if tag == self._skip_tag:
                        self._skip_depth -= 1
                    return
                self.parts.append(f"</{tag}>")

            def handle_data(self, data):
                if self._skip_depth == 0:
                    self.parts.append(data)

            def handle_entityref(self, name):
                if self._skip_depth == 0:
                    self.parts.append(f"&{name};")

            def handle_charref(self, name):
                if self._skip_depth == 0:
                    self.parts.append(f"&#{name};")

            def handle_comment(self, data):
                if self._skip_depth == 0:
                    self.parts.append(f"<!--{data}-->")

            def handle_decl(self, decl):
                if self._skip_depth == 0:
                    self.parts.append(f"<!{decl}>")

            def get_result(self) -> str:
                return "".join(self.parts)

        stripper = _ChromeStripper()
        try:
            stripper.feed(html)
            result = stripper.get_result()
            if stripper._stripped_count > 0:
                logger.info(
                    f"Stripped {stripper._stripped_count} Shopify chrome elements "
                    f"(header/footer/nav/overlay)"
                )
            return result
        except Exception as e:
            logger.warning(f"Shopify chrome stripping failed: {e}, returning as-is")
            return html

    # ------------------------------------------------------------------
    # Image URL Extraction & Validation
    # ------------------------------------------------------------------

    # Known tracking pixel domains
    _TRACKING_DOMAINS = frozenset([
        'doubleclick.net', 'facebook.com', 'google-analytics.com',
        'googleadservices.com', 'googlesyndication.com',
    ])
    _TRACKING_PREFIXES = ('pixel.', 'beacon.', 'track.')

    # Safe data URI image types (NO svg — script risk)
    _SAFE_DATA_IMAGE_TYPES = frozenset([
        'image/png', 'image/jpeg', 'image/gif', 'image/webp',
    ])
    _DATA_URI_MAX_SIZE = 500_000  # 500KB

    _MARKDOWN_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

    def _extract_image_urls(
        self, page_markdown: str, page_url: str
    ) -> List[Dict[str, str]]:
        """Parse ![alt](url) patterns from markdown, resolve relative URLs.

        Returns list of dicts with 'alt' and 'url' keys, capped at 20 images.
        """
        results = []
        for match in self._MARKDOWN_IMAGE_RE.finditer(page_markdown):
            if len(results) >= 20:
                break
            alt = match.group(1).strip()
            raw_url = match.group(2).strip()

            # Resolve relative URLs
            if page_url and not raw_url.startswith(('http://', 'https://', 'data:')):
                resolved = urljoin(page_url, raw_url)
            else:
                resolved = raw_url

            # Validate
            is_safe, safe_url, reason = self._validate_image_url(resolved)
            if is_safe:
                results.append({"alt": alt or "image", "url": safe_url})
            else:
                logger.debug(f"Image URL rejected: {reason} — {raw_url[:100]}")

        return results

    def _validate_image_url(self, url: str) -> Tuple[bool, str, str]:
        """Validate an image URL for safety.

        Returns (is_safe, url, reason).
        """
        if not url:
            return False, "", "empty URL"

        # Handle data: URIs
        if url.startswith('data:'):
            return self._validate_data_uri(url)

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "", "invalid URL format"

        # HTTPS only
        if parsed.scheme not in ('https',):
            return False, "", f"non-HTTPS scheme: {parsed.scheme}"

        hostname = (parsed.hostname or "").lower()

        # Block private/internal IPs
        if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
            return False, "", "private IP: localhost"
        if hostname.startswith(('192.168.', '10.', '169.254.')):
            return False, "", f"private IP: {hostname}"
        # 172.16.0.0 - 172.31.255.255
        if hostname.startswith('172.'):
            parts = hostname.split('.')
            if len(parts) >= 2:
                try:
                    second = int(parts[1])
                    if 16 <= second <= 31:
                        return False, "", f"private IP: {hostname}"
                except ValueError:
                    pass

        # Block tracking pixels
        for domain in self._TRACKING_DOMAINS:
            if hostname == domain or hostname.endswith('.' + domain):
                return False, "", f"tracking domain: {hostname}"
        for prefix in self._TRACKING_PREFIXES:
            if hostname.startswith(prefix):
                return False, "", f"tracking prefix: {hostname}"

        return True, url, "OK"

    def _validate_data_uri(self, uri: str) -> Tuple[bool, str, str]:
        """Validate a data: URI for safe image content."""
        # Parse: data:[<mediatype>][;base64],<data>
        if not uri.startswith('data:'):
            return False, "", "not a data URI"

        # Extract media type
        header_end = uri.find(',')
        if header_end < 0:
            return False, "", "malformed data URI (no comma)"

        header = uri[5:header_end].lower()  # Strip "data:" prefix

        # Check media type against safe list
        media_type = header.split(';')[0].strip()
        if media_type not in self._SAFE_DATA_IMAGE_TYPES:
            return False, "", f"unsafe data URI type: {media_type}"

        # Size check (approximate: base64 is ~4/3 of binary)
        data_part = uri[header_end + 1:]
        if len(data_part) > self._DATA_URI_MAX_SIZE:
            return False, "", f"data URI too large: {len(data_part)} bytes"

        return True, uri, "OK"

    # ------------------------------------------------------------------
    # Post-Sanitization for <img src> (parser-based)
    # ------------------------------------------------------------------

    class _SrcSanitizer(HTMLParser):
        """Parse HTML and validate/rewrite img[src] and source[srcset] attributes.

        Validates each src/srcset against _validate_image_url() and clears unsafe ones.
        Also handles data: URI preservation through bleach (which strips non-HTTPS).
        """

        _SRCSET_TAGS = {'img', 'source'}  # Tags whose srcset URLs must be validated

        def __init__(self, validator):
            super().__init__(convert_charrefs=False)
            self.parts: list = []
            self._validator = validator

        def _process_attrs(self, tag, attrs):
            """Validate src and srcset attributes on img/source tags."""
            if tag.lower() not in self._SRCSET_TAGS:
                return attrs
            new_attrs = []
            for name, value in attrs:
                if name.lower() == 'src' and value:
                    is_safe, safe_url, reason = self._validator(value)
                    if is_safe:
                        new_attrs.append((name, safe_url))
                    else:
                        logger.debug(f"img src stripped: {reason}")
                        new_attrs.append((name, ""))
                elif name.lower() == 'srcset' and value:
                    # Validate each URL in srcset
                    from .multipass.html_extractor import _parse_srcset
                    safe_parts = []
                    for url, descriptor in _parse_srcset(value):
                        if url.startswith('data:'):
                            continue  # data: URIs not valid in srcset
                        is_safe, safe_url, _ = self._validator(url)
                        if is_safe:
                            safe_parts.append(f"{safe_url} {descriptor}".strip())
                    if safe_parts:
                        new_attrs.append((name, ", ".join(safe_parts)))
                    # If NO parts are safe, drop the entire srcset attr
                else:
                    new_attrs.append((name, value))
            return new_attrs

        def _build_attrs(self, attrs):
            parts = []
            for name, value in attrs:
                if value is None:
                    parts.append(f' {name}')
                else:
                    parts.append(f' {name}="{_html_module.escape(value, quote=True)}"')
            return ''.join(parts)

        def handle_starttag(self, tag, attrs):
            processed = self._process_attrs(tag, attrs)
            self.parts.append(f'<{tag}{self._build_attrs(processed)}>')

        def handle_endtag(self, tag):
            self.parts.append(f'</{tag}>')

        def handle_startendtag(self, tag, attrs):
            processed = self._process_attrs(tag, attrs)
            self.parts.append(f'<{tag}{self._build_attrs(processed)} />')

        def handle_data(self, data):
            self.parts.append(data)

        def handle_entityref(self, name):
            self.parts.append(f'&{name};')

        def handle_charref(self, name):
            self.parts.append(f'&#{name};')

        def handle_comment(self, data):
            self.parts.append(f'<!--{data}-->')

        def handle_decl(self, decl):
            self.parts.append(f'<!{decl}>')

        def unknown_decl(self, data):
            self.parts.append(f'<!{data}>')

        def get_result(self) -> str:
            return ''.join(self.parts)

    def _sanitize_img_src(self, html: str) -> str:
        """Validate all <img src> attributes using parser-based rewriting."""
        if '<img' not in html.lower():
            return html  # Fast path

        sanitizer = self._SrcSanitizer(self._validate_image_url)
        try:
            sanitizer.feed(html)
            return sanitizer.get_result()
        except Exception:
            logger.warning("HTMLParser failed in _sanitize_img_src, returning as-is")
            return html

    # ------------------------------------------------------------------
    # Template Swap (Blueprint mode)
    # ------------------------------------------------------------------

    def _build_slot_map(self, blueprint: Dict) -> Dict[str, str]:
        """Build slot_name→escaped_content map from blueprint sections."""
        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]

        slot_content: Dict[str, str] = {}
        sections = sorted(
            rb.get("sections", []),
            key=lambda s: int(s.get("flow_order", 999))
        )

        for i, section in enumerate(sections):
            bm = section.get("brand_mapping", {})
            primary = bm.get("primary_content", "")
            supporting = bm.get("supporting_data", "")
            hook = bm.get("emotional_hook", "")

            if i == 0:
                if primary:
                    slot_content["headline"] = _html_module.escape(primary)
                if hook:
                    slot_content["subheadline"] = _html_module.escape(hook)
            else:
                if primary:
                    slot_content[f"heading-{i}"] = _html_module.escape(primary)
                if supporting:
                    slot_content[f"body-{i}"] = _html_module.escape(supporting)

        return slot_content

    def _infer_slot_type(self, slot_name: str) -> str:
        """Infer semantic type from slot name convention."""
        name = slot_name.lower()
        if name == "headline":
            return "headline"
        if name == "subheadline":
            return "subheadline"
        if name.startswith("heading"):
            return "heading"
        if name.startswith("body"):
            return "body"
        if name.startswith("list"):
            return "list"
        if name.startswith("cta"):
            return "cta"
        if name.startswith("testimonial"):
            return "testimonial"
        if name.startswith("feature"):
            return "feature"
        if name.startswith("price"):
            return "price"
        if name.startswith("guarantee"):
            return "guarantee"
        if name.startswith("badge"):
            return "badge"
        return "body"  # safe default

    # Hardcoded fallback limits (used when original word count is unknown)
    _SLOT_TYPE_DEFAULT_MAX_WORDS = {
        "headline": 15, "subheadline": 25, "heading": 15,
        "cta": 5, "badge": 8, "price": 8, "guarantee": 15,
        "feature": 20, "list": 25, "testimonial": 60, "body": 80,
    }

    def _compute_slot_length_spec(
        self,
        slot_type: str,
        original_words: int,
        original_chars: int,
    ) -> Dict[str, Any]:
        """Compute adaptive max_words based on original text length and slot type.

        Returns dict with max_words, original_words, original_chars, length_note.
        When original_words is 0 (unknown), falls back to hardcoded defaults.
        """
        if original_words <= 0:
            default = self._SLOT_TYPE_DEFAULT_MAX_WORDS.get(slot_type, 80)
            return {
                "max_words": default,
                "original_words": 0,
                "original_chars": 0,
                "length_note": f"No original text; using default {default}-word limit for {slot_type}.",
            }

        # Type-dependent tolerance bands
        # (tolerance_pct, min_extra_words, cap_extra_words or None)
        tolerance_config = {
            "cta":         (0.40, 1, 2),
            "headline":    (0.20, 1, 3),
            "subheadline": (0.25, 2, None),
            "heading":     (0.20, 1, None),
            "badge":       (0.20, 1, None),
            "price":       (0.20, 1, None),
            "guarantee":   (0.20, 1, None),
            "feature":     (0.25, 2, None),
            "list":        (0.25, 2, None),
        }
        # Default for body, testimonial, and anything else
        pct, min_extra, cap_extra = tolerance_config.get(slot_type, (0.30, 3, None))

        extra = max(min_extra, round(original_words * pct))
        if cap_extra is not None:
            extra = min(extra, cap_extra)
        max_words = original_words + extra

        note = (
            f"Original is {original_words} words / {original_chars} chars. "
            f"Max {max_words} words ({slot_type}, +{extra} tolerance)."
        )
        return {
            "max_words": max_words,
            "original_words": original_words,
            "original_chars": original_chars,
            "length_note": note,
        }

    def _aggregate_section_metrics(
        self,
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
    ) -> Dict[str, Dict]:
        """Aggregate word counts and slot-type breakdowns per section.

        Iterates slot_contents.keys() (not slot_sections.keys()) because
        void-element slots exist in slot_sections but have no text content.

        Args:
            slot_contents: {slot_name: text} from _extract_slots_with_content.
            slot_sections: {slot_name: {section_name, slot_type, ...}} from _map_slots_to_sections.

        Returns:
            {section_name: {total_words, slot_count, breakdown: {type: {count, total_words}}}}
        """
        metrics: Dict[str, Dict] = {}

        for slot_name in slot_contents:
            ctx = slot_sections.get(slot_name, {})
            section_name = ctx.get("section_name", "global")
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            word_count = len(slot_contents[slot_name].split()) if slot_contents[slot_name] else 0

            if section_name not in metrics:
                metrics[section_name] = {
                    "total_words": 0,
                    "slot_count": 0,
                    "breakdown": {},
                }

            sec = metrics[section_name]
            sec["total_words"] += word_count
            sec["slot_count"] += 1

            if slot_type not in sec["breakdown"]:
                sec["breakdown"][slot_type] = {"count": 0, "total_words": 0}
            sec["breakdown"][slot_type]["count"] += 1
            sec["breakdown"][slot_type]["total_words"] += word_count

        return metrics

    def _format_section_space_budget(
        self,
        section_metrics: Dict[str, Dict],
        slot_contents: Dict[str, str],
        slot_sections: Dict[str, Dict],
    ) -> Dict[str, Dict]:
        """Convert section metrics into structured space_budget dicts.

        Guards:
        - Skip sections named "global" (orphan slots — meaningless aggregate)
        - Skip sections with only 1 slot (per-slot constraint is sufficient)
        - For sections with >15 slots: emit simplified budget
        - Exclude slot types with ≤3 words from the breakdown

        Args:
            section_metrics: Output from _aggregate_section_metrics.
            slot_contents: {slot_name: text} for word count lookups.
            slot_sections: {slot_name: {section_name, slot_type, ...}} for slot context.

        Returns:
            {section_name: {total_words, breakdown: [...], note: str}}
        """
        budgets: Dict[str, Dict] = {}

        for section_name, metrics in section_metrics.items():
            # Skip orphan sections
            if section_name == "global":
                continue
            # Skip single-slot sections (per-slot constraint suffices)
            if metrics["slot_count"] <= 1:
                continue

            # Large sections get simplified budget
            if metrics["slot_count"] > 15:
                budgets[section_name] = {
                    "total_words": metrics["total_words"],
                    "breakdown": [],
                    "note": "Large section; follow individual slot targets.",
                }
                continue

            # Build breakdown entries with word ranges
            breakdown = []
            for slot_name in slot_contents:
                ctx = slot_sections.get(slot_name, {})
                if ctx.get("section_name") != section_name:
                    continue
                slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
                word_count = len(slot_contents[slot_name].split()) if slot_contents[slot_name] else 0

                # Exclude tiny slots (nav items, prices, badges ≤3 words)
                if word_count <= 3:
                    continue

                # Compute word range: ~85-110% of original
                min_words = max(1, round(word_count * 0.85))
                max_words = max(min_words + 1, round(word_count * 1.10))
                breakdown.append({
                    "role": slot_type,
                    "target_range": [min_words, max_words],
                    "slots": [slot_name],
                })

            budgets[section_name] = {
                "total_words": metrics["total_words"],
                "breakdown": breakdown,
                "note": "Use 85-100% of each target range. Underusing space wastes layout real estate.",
            }

        return budgets

    def _map_slots_to_sections(self, html: str, blueprint: Dict) -> Dict[str, Dict]:
        """Map slot_name -> {section_name, copy_direction, brand_mapping, flow_order, slot_type}.

        Uses DOM-based data-section ancestry + named heuristic fallback for orphan slots.
        """
        # 1. Walk HTML to find slot -> data-section mapping
        class _SlotSectionMapper(HTMLParser):
            def __init__(self):
                super().__init__()
                self._section_stack: list = []  # stack of (section_id, tag, depth)
                self.slot_to_section: Dict[str, Optional[str]] = {}

            def handle_starttag(self, tag, attrs):
                attr_dict = dict(attrs)
                section_id = attr_dict.get("data-section")
                if section_id:
                    self._section_stack.append((section_id, tag, 1))
                elif self._section_stack:
                    sid, stag, depth = self._section_stack[-1]
                    if tag == stag:
                        self._section_stack[-1] = (sid, stag, depth + 1)

                slot_name = attr_dict.get("data-slot")
                if slot_name:
                    if self._section_stack:
                        self.slot_to_section[slot_name] = self._section_stack[-1][0]
                    else:
                        self.slot_to_section[slot_name] = None  # orphan

            def handle_endtag(self, tag):
                if self._section_stack:
                    sid, stag, depth = self._section_stack[-1]
                    if tag == stag:
                        if depth <= 1:
                            self._section_stack.pop()
                        else:
                            self._section_stack[-1] = (sid, stag, depth - 1)

        mapper = _SlotSectionMapper()
        mapper.feed(html)

        # 2. Sort blueprint sections by flow_order
        rb = blueprint
        if "reconstruction_blueprint" in rb:
            rb = rb["reconstruction_blueprint"]

        def _safe_order(s):
            try:
                return int(s.get("flow_order", 999))
            except (TypeError, ValueError):
                return 999

        bp_sections = sorted(rb.get("sections", []), key=_safe_order)

        # 3. Build section_id -> blueprint_section mapping (positional)
        unique_section_ids = []
        seen_sections = set()
        for slot_name, sec_id in mapper.slot_to_section.items():
            if sec_id and sec_id not in seen_sections:
                unique_section_ids.append(sec_id)
                seen_sections.add(sec_id)

        sec_id_to_bp: Dict[str, Dict] = {}
        for idx, sec_id in enumerate(unique_section_ids):
            if idx < len(bp_sections):
                sec_id_to_bp[sec_id] = bp_sections[idx]

        # 4. Build per-slot context
        result: Dict[str, Dict] = {}
        for slot_name, sec_id in mapper.slot_to_section.items():
            slot_type = self._infer_slot_type(slot_name)
            bp_sec = sec_id_to_bp.get(sec_id) if sec_id else None

            if bp_sec:
                result[slot_name] = {
                    "section_name": bp_sec.get("section_name", "unknown"),
                    "copy_direction": bp_sec.get("copy_direction", ""),
                    "brand_mapping": bp_sec.get("brand_mapping", {}),
                    "flow_order": bp_sec.get("flow_order", 999),
                    "slot_type": slot_type,
                }
            else:
                # Orphan slot — use heuristic fallback
                fallback_section = self._resolve_orphan_slot(slot_name, bp_sections)
                result[slot_name] = {
                    "section_name": fallback_section.get("section_name", "global"),
                    "copy_direction": fallback_section.get("copy_direction",
                        "Replace competitor text with brand equivalent. Match the brand's voice and tone."),
                    "brand_mapping": fallback_section.get("brand_mapping", {}),
                    "flow_order": fallback_section.get("flow_order", 999),
                    "slot_type": slot_type,
                }

        return result

    def _resolve_orphan_slot(self, slot_name: str, bp_sections: List[Dict]) -> Dict:
        """Resolve an orphan slot (not inside data-section) to a blueprint section."""
        if not bp_sections:
            return {}
        name = slot_name.lower()
        if name in ("headline", "subheadline"):
            return bp_sections[0]
        # heading-N / body-N → section N
        import re as _re
        m = _re.search(r'-(\d+)', name)
        if m:
            idx = int(m.group(1))
            idx = min(idx, len(bp_sections) - 1)
            return bp_sections[idx]
        # cta → last section (conversion)
        if name.startswith("cta"):
            return bp_sections[-1]
        # Default → first section
        return bp_sections[0]

    def extract_slots_grouped_by_section(
        self,
        mockup_html: str,
        blueprint: Optional[Dict] = None,
    ) -> Dict[str, List[Dict[str, str]]]:
        """Group all text slots by their blueprint section for UI rendering.

        Returns {section_name: [{name, type, content, section}]} ordered by flow_order.
        Sections with no slots are omitted.

        Args:
            mockup_html: Full mockup HTML (wrapped or unwrapped).
            blueprint: Blueprint dict for section mapping. If None, all slots
                are placed under a single "Page Content" section.
        """
        body, _ = self._extract_page_css_and_strip(mockup_html)
        slot_contents = self._extract_slots_with_content(body)
        if not slot_contents:
            return {}

        if blueprint:
            slot_sections = self._map_slots_to_sections(body, blueprint)
        else:
            slot_sections = {}

        # Group by section_name, preserving flow_order
        groups: Dict[str, Dict] = {}  # group_key -> {section_name, flow_order, slots}
        for slot_name, content in slot_contents.items():
            ctx = slot_sections.get(slot_name, {})
            sec_name = ctx.get("section_name", "Page Content")
            flow = ctx.get("flow_order", 999)
            slot_type = ctx.get("slot_type", self._infer_slot_type(slot_name))
            group_key = f"{flow:04d}_{sec_name}"

            if group_key not in groups:
                groups[group_key] = {
                    "section_name": sec_name,
                    "flow_order": flow,
                    "slots": [],
                }
            groups[group_key]["slots"].append({
                "name": slot_name,
                "type": slot_type,
                "content": content,
                "section": sec_name,
            })

        # Build ordered result
        result: Dict[str, List[Dict[str, str]]] = {}
        for key in sorted(groups.keys()):
            g = groups[key]
            result[g["section_name"]] = g["slots"]
        return result

    def _template_swap(
        self,
        template_html: str,
        blueprint: Dict,
        brand_profile: Optional[Dict] = None,
        slot_map: Optional[Dict[str, str]] = None,
        apply_brand_colors: bool = True,
    ) -> str:
        """Replace data-slot content using DOM-aware parsing.

        Uses HTMLParser to walk the HTML tree. When a data-slot element is found
        whose name matches a slot in the content map, all inner content (including
        nested tags) is discarded and replaced with the escaped value.

        Args:
            template_html: HTML template with data-slot attributes.
            blueprint: Reconstruction blueprint (used for _build_slot_map fallback).
            brand_profile: Brand profile for color injection.
            slot_map: Pre-built {slot_name: escaped_text} map (from AI rewrite).
                If None, falls back to _build_slot_map(blueprint).
            apply_brand_colors: When True, inject brand primary color as body
                background. Set to False for selective regen to avoid
                double-applying colors on already-styled HTML.
        """
        if slot_map is not None:
            slot_content = slot_map
        else:
            slot_content = self._build_slot_map(blueprint)
        if not slot_content:
            return template_html

        void_elems = self._VOID_ELEMENTS

        class _SlotReplacer(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.parts: list = []
                self._skip_depth: int = 0
                self._skip_tag: str = ""
                self._checkpoint_idx: int = -1
                self._checkpoint_tag_text: str = ""

            def handle_starttag(self, tag, attrs):
                if self._skip_depth > 0:
                    # Guard: if skipped content contains a data-section,
                    # abort the slot replacement and roll back
                    attr_dict_skip = dict(attrs)
                    if "data-section" in attr_dict_skip:
                        # ABORT: slot spans sections — roll back replacement
                        self.parts = self.parts[:self._checkpoint_idx]
                        self.parts.append(self._checkpoint_tag_text)
                        self._skip_depth = 0
                        self._skip_tag = ""
                        # Emit the current tag (the data-section one) normally
                        self.parts.append(self.get_starttag_text() or "")
                        return
                    if tag == self._skip_tag:
                        self._skip_depth += 1
                    return

                attr_dict = dict(attrs)
                slot_name = attr_dict.get("data-slot")
                if slot_name and slot_name in slot_content:
                    self._checkpoint_idx = len(self.parts)
                    self._checkpoint_tag_text = self.get_starttag_text() or ""
                    self.parts.append(self._checkpoint_tag_text)
                    if tag.lower() not in void_elems:
                        self.parts.append(slot_content[slot_name])
                        self._skip_depth = 1
                        self._skip_tag = tag
                    # Void elements: emit the tag only, no content replacement
                    return

                self.parts.append(self.get_starttag_text() or "")

            def handle_endtag(self, tag):
                if self._skip_depth > 0:
                    if tag == self._skip_tag:
                        self._skip_depth -= 1
                    if self._skip_depth == 0:
                        self.parts.append(f"</{tag}>")
                        self._skip_tag = ""
                    return
                self.parts.append(f"</{tag}>")

            def handle_startendtag(self, tag, attrs):
                if self._skip_depth > 0:
                    return
                self.parts.append(self.get_starttag_text() or "")

            def handle_data(self, data):
                if self._skip_depth == 0:
                    self.parts.append(data)

            def handle_entityref(self, name):
                if self._skip_depth == 0:
                    self.parts.append(f"&{name};")

            def handle_charref(self, name):
                if self._skip_depth == 0:
                    self.parts.append(f"&#{name};")

            def handle_comment(self, data):
                if self._skip_depth == 0:
                    self.parts.append(f"<!--{data}-->")

            def handle_decl(self, decl):
                self.parts.append(f"<!{decl}>")

            def unknown_decl(self, data):
                self.parts.append(f"<!{data}>")

            def get_result(self) -> str:
                return "".join(self.parts)

        replacer = _SlotReplacer()
        replacer.feed(template_html)
        result = replacer.get_result()

        # Apply brand colors as inline styles (skip for selective regen)
        if not apply_brand_colors:
            return result
        brand_style = self._extract_brand_style(brand_profile)
        if brand_style:
            primary = brand_style.get("primary", "")
            if primary and _CSS_COLOR_RE.match(primary):
                if 'style="' in result.split("<body", 1)[-1].split(">", 1)[0] if "<body" in result else False:
                    # Merge with existing style attribute on body
                    result = re.sub(
                        r'(<body[^>]*style=")',
                        rf'\1background-color:{primary};',
                        result,
                        count=1,
                    )
                else:
                    result = result.replace(
                        "<body", f'<body style="background-color:{primary}"', 1
                    )

        return result

    # ------------------------------------------------------------------
    # Mockup Wrapping (for AI vision / markdown output)
    # ------------------------------------------------------------------

    def _wrap_mockup(
        self,
        inner_html: str,
        classification: Optional[Dict[str, Any]],
        mode: str,
        page_css: str = "",
        is_surgery: bool = False,
    ) -> str:
        """Wrap AI-generated or markdown HTML in the mockup shell (metadata bar + footer).

        Args:
            inner_html: Sanitized page body HTML.
            classification: Optional page classification data.
            mode: "analysis" or "blueprint".
            page_css: Optional sanitized CSS from AI-generated <style> blocks.
            is_surgery: When True, emit ``data-pipeline="surgery"`` on the
                ``<body>`` tag so downstream consumers (e.g.
                ``generate_blueprint_mockup``) can detect surgery-pipeline
                output and use the higher CSS size limit.  This is distinct
                from ``self.is_surgery_mode`` which controls CSS sanitization
                limits during the current generation pass.
        """
        cls_data = classification or {}
        if "page_classifier" in cls_data:
            cls_data = cls_data["page_classifier"]

        al = ""
        pa = ""
        if cls_data:
            al_raw = cls_data.get("awareness_level", "")
            if isinstance(al_raw, dict):
                al = al_raw.get("primary", "")
            else:
                al = al_raw
            pa_raw = cls_data.get("page_architecture", "")
            if isinstance(pa_raw, dict):
                pa = pa_raw.get("type", "")
            else:
                pa = pa_raw

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        mode_upper = mode.upper()
        mode_class = mode.lower()

        # Build awareness/architecture display strings
        awareness_html = ""
        if al:
            al_display = _html_module.escape(al.replace("_", " ").title())
            awareness_html = f'<span><strong>Awareness:</strong> {al_display}</span>'
        arch_html = ""
        if pa:
            pa_display = _html_module.escape(pa.replace("_", " ").title())
            arch_html = f'<span><strong>Architecture:</strong> {pa_display}</span>'

        # Build page CSS block if present
        page_css_block = ""
        if page_css and page_css.strip():
            page_css_block = f"""<style class="page-css">
{page_css}
</style>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Landing Page Mockup — {_html_module.escape(mode.title())} Mode</title>
<style>
.mockup-meta-bar {{
  background: #1e293b; color: #e2e8f0; padding: 12px 24px;
  font-size: 13px; display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
}}
.mockup-meta-bar strong {{ color: #f8fafc; }}
.mockup-meta-badge {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
}}
.mockup-meta-badge.analysis {{ background: #3b82f6; color: white; }}
.mockup-meta-badge.blueprint {{ background: #10b981; color: white; }}
.mockup-gen-footer {{
  text-align: center; padding: 16px; font-size: 11px;
  color: #94a3b8; border-top: 1px solid #e2e8f0;
}}
</style>
{page_css_block}
</head>
<body{' data-pipeline="surgery"' if is_surgery else ''}>
<div class="mockup-meta-bar">
  <span class="mockup-meta-badge {mode_class}">{mode_upper} MOCKUP</span>
  {awareness_html}
  {arch_html}
  <span style="margin-left: auto;"><strong>Generated:</strong> {generated_at}</span>
</div>

{inner_html}

<div class="mockup-gen-footer">
  Generated by ViralTracker Landing Page Analyzer &middot; {generated_at}
</div>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Rendering (V1 wireframe fallback)
    # ------------------------------------------------------------------

    def _get_jinja_env(self) -> jinja2.Environment:
        """Get or create the Jinja2 environment with template loader."""
        if MockupService._jinja_env is None:
            template_dir = os.path.join(
                os.path.dirname(__file__), "templates", "mockup"
            )
            MockupService._jinja_env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(template_dir),
                autoescape=True,
            )
        return MockupService._jinja_env

    def _render_html(
        self,
        sections: List[Dict[str, Any]],
        classification: Optional[Dict[str, Any]],
        mode: str,
        brand_style: Optional[Dict[str, str]] = None,
    ) -> str:
        """Render the final HTML mockup.

        Args:
            sections: Normalized section list
            classification: Optional page classification data
            mode: "analysis" or "blueprint"
            brand_style: Optional validated CSS color overrides
        """
        env = self._get_jinja_env()
        template = env.get_template("base.html")

        # Unwrap classification if needed
        cls_data = classification or {}
        if "page_classifier" in cls_data:
            cls_data = cls_data["page_classifier"]

        return template.render(
            sections=sections,
            classification=cls_data,
            mode=mode,
            brand_style=brand_style,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            section_colors=SECTION_ACCENT_COLORS,
            default_accent=_DEFAULT_ACCENT,
        )
