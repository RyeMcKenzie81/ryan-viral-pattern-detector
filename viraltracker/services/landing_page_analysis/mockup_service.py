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
from typing import Any, Dict, List, Optional

import bleach
from bleach.css_sanitizer import CSSSanitizer
import jinja2

logger = logging.getLogger(__name__)

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
    "img", "figure", "figcaption",
    # Interactive (display only)
    "a", "button",
    # Forms (display only)
    "input", "label", "select", "option", "textarea", "form",
]

_ALLOWED_ATTRS = {
    "*": ["class", "id", "style", "data-slot", "data-section", "role", "aria-label"],
    "a": ["href", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    "meta": ["charset", "name", "content"],
    "input": ["type", "placeholder", "value", "name"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

_ALLOWED_CSS_PROPERTIES = [
    "color", "background-color", "background", "font-size", "font-weight",
    "font-family", "text-align", "text-decoration", "line-height",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "border", "border-radius", "border-color", "border-width", "border-style",
    "width", "max-width", "min-width", "height", "max-height", "min-height",
    "display", "flex-direction", "justify-content", "align-items", "gap", "flex-wrap", "flex",
    "grid-template-columns", "grid-gap",
    "position", "top", "bottom", "left", "right",
    "overflow", "opacity", "box-shadow", "letter-spacing",
    "list-style", "list-style-type",
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
    ) -> str:
        """Generate a faithful HTML recreation of the analyzed page.

        Fallback chain: screenshot→AI vision > page_markdown→HTML > V1 wireframe.

        Args:
            screenshot_b64: Optional base64 screenshot for AI vision recreation
            element_detection: Skill 2 output (element_detection dict, wrapped or unwrapped)
            classification: Skill 1 output (page_classifier dict, wrapped or unwrapped)
            page_markdown: Optional page markdown for fallback rendering

        Returns:
            Standalone HTML string
        """
        if screenshot_b64:
            raw_html = self._generate_via_ai_vision(screenshot_b64)
            # Strip <style> blocks BEFORE sanitization — bleach strips <style>
            # tags (not in allowlist) but leaves CSS text content as visible text.
            raw_html = re.sub(
                r'<style[^>]*>.*?</style>', '', raw_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            html = self._sanitize_html(raw_html)
            return self._wrap_mockup(html, classification, mode="analysis")
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

        Returns None if no analysis HTML is available (V1 wireframe path is
        intentionally disabled to prevent leaking strategic instructions).
        """
        if analysis_mockup_html:
            rewritten = None
            if brand_profile:
                page_body = self._strip_mockup_wrapper(analysis_mockup_html)
                if page_body.strip():
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
                else:
                    logger.warning("Stripped page body is empty — skipping AI rewrite")
            else:
                logger.info(
                    "No brand_profile provided — skipping AI rewrite, "
                    "using stripped analysis HTML as fallback"
                )

            if rewritten:
                inner = self._sanitize_html(rewritten)
            else:
                # Fallback: show analysis page content as-is (no instructions leak)
                inner = self._sanitize_html(
                    self._strip_mockup_wrapper(analysis_mockup_html)
                )
            return self._wrap_mockup(inner, classification, mode="blueprint")
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
        """
        return bleach.clean(
            raw_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            css_sanitizer=_CSS_SANITIZER,
            strip=True,
        )

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
            lines.append(f"Mechanism: {mech['name']} — {(mech.get('solution') or '')[:200]}")
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
                lines.append(f"Target Persona: {p0.get('name') or ''} — {(p0.get('snapshot') or '')[:200]}")
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
5. Maintain page congruence — every element supports one cohesive argument
6. Use the brand's voice/tone throughout
7. DO NOT add, remove, or reorder HTML elements
8. DO NOT modify CSS styles, classes, or attributes (except text content)
9. Keep data-slot attributes exactly as they are
10. Image placeholder labels: update to describe brand-relevant images

OUTPUT: Return ONLY the rewritten HTML. No explanations, no code fences, no wrapping <html>/<body> tags."""

        agent = Agent(
            model=Config.get_model("creative"),
            system_prompt=(
                "You are an expert direct-response copywriter rewriting a competitor "
                "landing page for a different brand. Rewrite ALL visible text for the "
                "brand while keeping the EXACT same HTML structure. Return ONLY the "
                "rewritten HTML fragment — no explanations, no outer html/body tags."
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

        # Validate structure
        self._validate_rewrite_structure(page_body, raw)

        return raw

    # ------------------------------------------------------------------
    # AI Vision Generation
    # ------------------------------------------------------------------

    def _generate_via_ai_vision(self, screenshot_b64: str) -> str:
        """Send screenshot to Gemini, get back HTML. Sync wrapper around async."""
        import asyncio
        from viraltracker.services.gemini_service import GeminiService

        gemini = GeminiService()
        if self._usage_tracker:
            gemini.set_tracking_context(
                self._usage_tracker, self._user_id, self._organization_id
            )

        prompt = (
            "Analyze this landing page screenshot and generate a standalone HTML document "
            "with inline CSS that faithfully recreates:\n"
            "- The visual layout and section structure\n"
            "- Typography (font sizes, weights, colors) using inline styles\n"
            "- Color scheme and backgrounds\n"
            "- Content placement and spacing\n"
            "- All visible text content (verbatim)\n\n"
            "Use colored placeholder divs with labels for images.\n\n"
            "IMPORTANT — Slot Marking Contract:\n"
            "Mark each replaceable text element with a data-slot attribute using "
            "this EXACT naming convention (numbered sequentially top-to-bottom):\n"
            '- data-slot="headline" — the main hero headline\n'
            '- data-slot="subheadline" — the hero subheadline\n'
            '- data-slot="cta-1", "cta-2", etc. — call-to-action buttons\n'
            '- data-slot="heading-1", "heading-2", etc. — section headings\n'
            '- data-slot="body-1", "body-2", etc. — section body text\n'
            '- data-slot="testimonial-1", etc. — testimonial quotes\n'
            '- data-slot="feature-1", etc. — feature descriptions\n'
            '- data-slot="price" — pricing text\n'
            '- data-slot="guarantee" — guarantee/risk-reversal text\n\n'
            "Output ONLY the complete HTML document, no explanation."
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
    ) -> str:
        """Wrap AI-generated or markdown HTML in the mockup shell (metadata bar + footer)."""
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
