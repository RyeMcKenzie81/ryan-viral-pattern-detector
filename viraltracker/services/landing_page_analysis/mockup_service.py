"""
Mockup Service — Generates standalone HTML/CSS mockup files from
landing page analysis and blueprint data.

Two modes:
- Analysis Mockup (Phase 1): Renders detected page structure with filler content
- Blueprint Mockup (Phase 2): Renders blueprint copy_direction + brand_mapping content
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import jinja2

logger = logging.getLogger(__name__)

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_analysis_mockup(
        self,
        element_detection: Dict[str, Any],
        classification: Dict[str, Any],
    ) -> str:
        """Phase 1: Render page structure from element detection with filler content.

        Args:
            element_detection: Skill 2 output (element_detection dict, wrapped or unwrapped)
            classification: Skill 1 output (page_classifier dict, wrapped or unwrapped)

        Returns:
            Standalone HTML string
        """
        sections = self._normalize_elements(element_detection)
        return self._render_html(
            sections=sections,
            classification=classification,
            mode="analysis",
        )

    def generate_blueprint_mockup(
        self,
        blueprint: Dict[str, Any],
        classification: Optional[Dict[str, Any]] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Phase 2: Render page with blueprint copy_direction and brand content.

        Args:
            blueprint: Skill 5 output (reconstruction_blueprint dict, wrapped or unwrapped)
            classification: Optional Skill 1 output for metadata bar
            brand_profile: Optional brand profile for color overrides

        Returns:
            Standalone HTML string
        """
        sections = self._normalize_blueprint_sections(blueprint)
        brand_style = self._extract_brand_style(brand_profile)
        return self._render_html(
            sections=sections,
            classification=classification,
            mode="blueprint",
            brand_style=brand_style,
        )

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
    # Rendering
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
