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

_CSS_MAX_SIZE = 100_000  # 100KB cap for CSS blocks

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


def _sanitize_css_block(raw_css: str) -> str:
    """Sanitize CSS content from <style> blocks.

    Strips known attack vectors while preserving layout-critical CSS
    (media queries, keyframes, pseudo-selectors, gradients).

    Returns empty string if the block is fully rejected (breakout/HTML injection).
    """
    if not raw_css or not raw_css.strip():
        return ""

    # Cap size
    if len(raw_css) > _CSS_MAX_SIZE:
        logger.warning(
            f"CSS block exceeds {_CSS_MAX_SIZE} bytes ({len(raw_css)}), truncating"
        )
        raw_css = raw_css[:_CSS_MAX_SIZE]

    # REJECT entire block if contains </style breakout
    if _STYLE_BREAKOUT_RE.search(raw_css):
        logger.warning("CSS block rejected: contains </style breakout pattern")
        return ""

    # REJECT if contains <! (HTML comments/CDATA) or <tag...> patterns
    if _HTML_COMMENT_RE.search(raw_css):
        logger.warning("CSS block rejected: contains <! HTML pattern")
        return ""
    if _HTML_TAG_RE.search(raw_css):
        logger.warning("CSS block rejected: contains HTML tag pattern")
        return ""

    # STRIP dangerous at-rules
    css = _CSS_IMPORT_RE.sub('', raw_css)
    css = _CSS_CHARSET_RE.sub('', css)

    # STRIP url() values (run until stable to handle nested/repeated patterns)
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


def _strip_url_from_inline_styles(html: str) -> str:
    """Strip url() only within style attribute values.

    Uses parser-based style attribute rewriting to handle all quoting
    styles and edge cases. Does NOT alter visible text content.
    """
    if 'url(' not in html.lower():
        return html  # Fast path: no url() anywhere

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
    # Tables
    "table", "tr", "td", "th", "thead", "tbody",
    # Media (images only, no external loading)
    "img", "figure", "figcaption", "picture", "source",
    # Interactive (display only)
    "a", "button",
    # Forms (display only)
    "input", "label", "select", "option", "textarea", "form",
]

_ALLOWED_ATTRS = {
    "*": ["class", "id", "style", "data-slot", "data-section", "role", "aria-label"],
    "a": ["href", "target", "rel"],
    "img": ["src", "alt", "width", "height", "srcset", "sizes", "loading", "data-bg-image"],
    "source": ["srcset", "sizes", "media", "type"],
    "picture": [],
    "meta": ["charset", "name", "content"],
    "input": ["type", "placeholder", "value", "name"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
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


class MockupService:
    """Generates standalone HTML/CSS mockup files from analysis and blueprint data."""

    _jinja_env: Optional[jinja2.Environment] = None

    def __init__(self):
        self._usage_tracker = None
        self._user_id: Optional[str] = None
        self._organization_id: Optional[str] = None

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

            return self._wrap_mockup(html, classification, mode="analysis", page_css=sanitized_css)
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
    ) -> Optional[str]:
        """Generate blueprint mockup by rewriting analysis HTML with brand copy.

        Carries CSS from the analysis mockup through the rewrite pipeline.
        Returns None if no analysis HTML is available (V1 wireframe path is
        intentionally disabled to prevent leaking strategic instructions).
        """
        if analysis_mockup_html:
            # Extract CSS before stripping (re-sanitized for defense-in-depth)
            page_body, page_css = self._extract_page_css_and_strip(analysis_mockup_html)

            rewritten = None
            if brand_profile and page_body.strip():
                logger.info(
                    "Starting AI rewrite for blueprint mockup "
                    f"(brand={(brand_profile.get('brand_basics') or {}).get('name') or '?'}, "
                    f"html_len={len(page_body)})"
                )
                # Let exceptions propagate — UI will show the error
                rewritten = self._rewrite_html_for_brand(
                    page_body, blueprint, brand_profile
                )
                logger.info("AI rewrite completed for blueprint mockup")
            elif brand_profile:
                logger.warning("Stripped page body is empty — skipping AI rewrite")
            else:
                logger.info(
                    "No brand_profile provided — skipping AI rewrite, "
                    "using stripped analysis HTML as fallback"
                )

            if rewritten:
                inner = self._sanitize_html(rewritten)
            else:
                # Fallback: use analysis body as-is (STILL inject page_css)
                inner = self._sanitize_html(page_body)

            # page_css injected in ALL paths
            return self._wrap_mockup(inner, classification, mode="blueprint", page_css=page_css)
        else:
            # Do NOT fall back to V1 wireframe — _render_html() renders
            # brand_mapping fields that contain strategic instructions.
            logger.warning(
                "No analysis_mockup_html for blueprint mockup; "
                "skipping V1 fallback to prevent instruction leak."
            )
            return None

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
        cleaned = _strip_url_from_inline_styles(cleaned)
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
    # AI HTML Rewrite (Blueprint Copywriting)
    # ------------------------------------------------------------------

    _MAX_HTML_CHARS = 80_000

    def _rewrite_html_for_brand(
        self,
        page_body: str,
        blueprint: Dict[str, Any],
        brand_profile: Dict[str, Any],
    ) -> str:
        """Rewrite ALL visible text in the page body HTML for the brand.

        Args:
            page_body: Stripped div-level page content (no html/head/body wrapper).
            blueprint: Reconstruction blueprint with strategic directions.
            brand_profile: Full brand profile from BrandProfileService.

        Returns:
            Rewritten div-level HTML (no html/head/body wrapper).
        """
        from pydantic_ai import Agent
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_sync_with_tracking

        # Prompt size guardrail — truncate at tag boundary (Fix 3)
        html_input = page_body
        if len(html_input) > self._MAX_HTML_CHARS:
            logger.warning(
                f"Page body {len(html_input)} chars exceeds {self._MAX_HTML_CHARS}, truncating"
            )
            html_input = self._truncate_html_at_boundary(html_input, self._MAX_HTML_CHARS)

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

        lf.info(
            "Multipass pipeline returned {output_chars} chars",
            output_chars=len(raw),
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
            sanitized = _sanitize_css_block(content)
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
            page_css = _sanitize_css_block(page_css)

        # 3. Strip wrapper normally
        body = self._strip_mockup_wrapper(wrapped_html)

        return body, page_css

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

    def _template_swap(
        self,
        template_html: str,
        blueprint: Dict,
        brand_profile: Optional[Dict] = None,
    ) -> str:
        """Replace data-slot content using DOM-aware parsing.

        Uses HTMLParser to walk the HTML tree. When a data-slot element is found
        whose name matches a blueprint slot, all inner content (including nested
        tags) is discarded and replaced with the escaped brand_mapping value.
        """
        slot_content = self._build_slot_map(blueprint)
        if not slot_content:
            return template_html

        class _SlotReplacer(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.parts: list = []
                self._skip_depth: int = 0
                self._skip_tag: str = ""

            def handle_starttag(self, tag, attrs):
                if self._skip_depth > 0:
                    if tag == self._skip_tag:
                        self._skip_depth += 1
                    return

                attr_dict = dict(attrs)
                slot_name = attr_dict.get("data-slot")
                if slot_name and slot_name in slot_content:
                    self.parts.append(self.get_starttag_text())
                    self.parts.append(slot_content[slot_name])
                    self._skip_depth = 1
                    self._skip_tag = tag
                    return

                self.parts.append(self.get_starttag_text())

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
                self.parts.append(self.get_starttag_text())

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

        # Apply brand colors as inline styles
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
    ) -> str:
        """Wrap AI-generated or markdown HTML in the mockup shell (metadata bar + footer).

        Args:
            inner_html: Sanitized page body HTML.
            classification: Optional page classification data.
            mode: "analysis" or "blueprint".
            page_css: Optional sanitized CSS from AI-generated <style> blocks.
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
<body>
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
