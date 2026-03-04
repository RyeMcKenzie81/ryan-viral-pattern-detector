"""Enhanced CSS extraction with css-inline cascade resolution + design token extraction.

Uses css-inline (Rust/Python, Mozilla Servo engine) to resolve the full CSS cascade
(specificity, !important, inheritance) onto every element as inline style="" attributes.
Then extracts component styles and frequency-weighted design tokens.

No LLM involved — pure deterministic extraction.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from .html_extractor import _split_top_level_blocks

logger = logging.getLogger(__name__)

# Size guards
_MAX_INPUT_HTML_SIZE = 1_000_000  # 1MB — skip css-inline if page_html exceeds this
_MAX_INLINED_HTML_SIZE = 2_000_000  # 2MB — discard inlined_html if output exceeds this
_CSS_INLINE_TIMEOUT = 5  # seconds — best-effort timeout for css-inline
_MAX_TOKENS_PER_CATEGORY = 50  # cap design token frequency maps

# Layout CSS properties to extract
LAYOUT_PROPERTIES = frozenset([
    'display', 'grid-template-columns', 'grid-template-rows', 'grid-gap',
    'gap', 'flex-direction', 'flex-wrap', 'justify-content', 'align-items',
    'flex', 'flex-grow', 'flex-shrink', 'flex-basis', 'order',
    'grid-column', 'grid-row', 'grid-area', 'grid-template-areas',
    'position', 'float', 'clear', 'columns', 'column-count', 'column-gap',
])

# Selector patterns for component classification
_BUTTON_SELECTORS = re.compile(r'\.btn|\.button|button|\.cta|input\[type.*submit', re.IGNORECASE)
_CARD_SELECTORS = re.compile(r'\.card|\.tile|\.panel|\.box', re.IGNORECASE)
_HEADING_SELECTORS = re.compile(r'^h[1-6]\b', re.IGNORECASE)
_CONTAINER_SELECTORS = re.compile(r'\.container|\.wrapper|\.content|\.main|\.page', re.IGNORECASE)

# Color regex (hex colors)
_HEX_COLOR_RE = re.compile(r'#(?:[0-9a-fA-F]{3}){1,2}\b')
# RGB/RGBA color
_RGB_COLOR_RE = re.compile(r'rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)')
# Font-family value
_FONT_FAMILY_RE = re.compile(r'font-family:\s*([^;]+)', re.IGNORECASE)
# Font-size value
_FONT_SIZE_RE = re.compile(r'font-size:\s*([^;]+)', re.IGNORECASE)
# Border-radius value
_BORDER_RADIUS_RE = re.compile(r'border-radius:\s*([^;]+)', re.IGNORECASE)
# Padding/margin value
_SPACING_RE = re.compile(r'(?:padding|margin)(?:-(?:top|right|bottom|left))?:\s*([^;]+)', re.IGNORECASE)


@dataclass
class ComponentStyles:
    """Extracted style profiles for common component types."""
    button: Dict[str, str] = field(default_factory=dict)
    card: Dict[str, str] = field(default_factory=dict)
    heading: Dict[str, str] = field(default_factory=dict)
    container: Dict[str, str] = field(default_factory=dict)


@dataclass
class DesignTokens:
    """Deterministic design system values extracted from CSS (augments Phase 0)."""
    colors: Dict[str, int] = field(default_factory=dict)       # hex → frequency count
    fonts: Dict[str, int] = field(default_factory=dict)         # font-family → frequency count
    font_sizes: Dict[str, int] = field(default_factory=dict)    # size → frequency count
    border_radii: Dict[str, int] = field(default_factory=dict)  # radius → frequency count
    spacings: Dict[str, int] = field(default_factory=dict)      # padding/margin values → frequency


@dataclass
class ExtractedCSS:
    """Enhanced CSS extraction result."""
    custom_properties: str = ""
    media_queries: str = ""
    font_faces: str = ""
    layout_rules: str = ""
    component_styles: ComponentStyles = field(default_factory=ComponentStyles)
    design_tokens: DesignTokens = field(default_factory=DesignTokens)
    inlined_html: str = ""


class CSSRulesExtractor:
    """Extract enhanced CSS rules, component styles, and design tokens.

    Uses css-inline to resolve the full CSS cascade, then extracts
    structured information from both the raw CSS and the inlined HTML.
    """

    @classmethod
    def extract(
        cls,
        original_html: str,
        extra_css: str = "",
        page_url: str = "",
    ) -> ExtractedCSS:
        """Extract CSS rules, component styles, and design tokens.

        Args:
            original_html: Full page HTML.
            extra_css: All pre-fetched CSS (inline <style> blocks + external sheets)
                       for css-inline cascade resolution. No network requests made.
            page_url: Original page URL (for reference only, no fetching).

        Returns:
            ExtractedCSS with all extracted data.
        """
        result = ExtractedCSS()

        if not original_html:
            return result

        try:
            # Step 1: Run css-inline for cascade resolution
            result.inlined_html = cls._run_css_inline(original_html, extra_css)

            # Step 2: Parse raw CSS for component classification and layout rules
            if extra_css:
                cls._extract_from_raw_css(extra_css, result)

            # Step 3: Extract design tokens from inlined HTML
            if result.inlined_html:
                cls._extract_design_tokens(result.inlined_html, result)

        except Exception as e:
            logger.warning(f"CSSRulesExtractor.extract failed: {e}")
            # Return whatever we have — partial results are fine

        return result

    @classmethod
    def _run_css_inline(cls, html: str, extra_css: str) -> str:
        """Run css-inline with safety guards.

        Returns inlined HTML string, or empty string on failure.
        """
        if len(html) > _MAX_INPUT_HTML_SIZE:
            logger.info(
                f"Skipping css-inline: input HTML too large ({len(html)} bytes)"
            )
            return ""

        try:
            import css_inline
        except ImportError:
            logger.warning("css-inline not installed, skipping cascade resolution")
            return ""

        # Prepare HTML: inject extra_css as <style> block if provided
        html_with_css = html
        if extra_css:
            style_tag = f"<style>{extra_css}</style>"
            # Insert before </head> or at start
            head_end = html.lower().find('</head>')
            if head_end >= 0:
                html_with_css = html[:head_end] + style_tag + html[head_end:]
            else:
                html_with_css = style_tag + html

        # SECURITY: load_remote_stylesheets=False prevents SSRF
        inliner = css_inline.CSSInliner(
            load_remote_stylesheets=False,
            keep_style_tags=True,
        )

        # Best-effort timeout via ThreadPoolExecutor
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(inliner.inline, html_with_css)
                inlined = future.result(timeout=_CSS_INLINE_TIMEOUT)
        except TimeoutError:
            logger.warning(
                f"css-inline timed out after {_CSS_INLINE_TIMEOUT}s, skipping"
            )
            return ""
        except Exception as e:
            logger.warning(f"css-inline failed: {e}")
            return ""

        # Size guard on output
        if len(inlined) > _MAX_INLINED_HTML_SIZE:
            logger.warning(
                f"css-inline output too large ({len(inlined)} bytes), discarding"
            )
            return ""

        return inlined

    @classmethod
    def _extract_from_raw_css(cls, raw_css: str, result: ExtractedCSS) -> None:
        """Extract layout rules and component styles from raw CSS text."""
        blocks = _split_top_level_blocks(raw_css)

        layout_parts: List[str] = []
        component_styles = ComponentStyles()

        for block_type, block_content in blocks:
            if block_type == "font-face":
                if not result.font_faces:
                    result.font_faces = block_content
                else:
                    result.font_faces += "\n" + block_content
            elif block_type == "media":
                if not result.media_queries:
                    result.media_queries = block_content
                else:
                    result.media_queries += "\n" + block_content
            elif block_type == "root":
                if not result.custom_properties:
                    result.custom_properties = block_content
                else:
                    result.custom_properties += "\n" + block_content
            elif block_type == "rule":
                # Extract selector for component classification
                brace_idx = block_content.find('{')
                if brace_idx < 0:
                    continue
                selector = block_content[:brace_idx].strip()
                declarations = block_content[brace_idx + 1:].rstrip('}').strip()

                # Check if this rule has layout properties
                has_layout = False
                for prop in LAYOUT_PROPERTIES:
                    if prop + ':' in declarations or prop + ' :' in declarations:
                        has_layout = True
                        break
                if has_layout:
                    layout_parts.append(block_content)

                # Classify into component types
                decl_dict = cls._parse_declarations(declarations)
                if _BUTTON_SELECTORS.search(selector):
                    component_styles.button.update(decl_dict)
                elif _CARD_SELECTORS.search(selector):
                    component_styles.card.update(decl_dict)
                elif _HEADING_SELECTORS.search(selector):
                    component_styles.heading.update(decl_dict)
                elif _CONTAINER_SELECTORS.search(selector):
                    component_styles.container.update(decl_dict)

        result.layout_rules = "\n".join(layout_parts)
        result.component_styles = component_styles

    @classmethod
    def _extract_design_tokens(cls, inlined_html: str, result: ExtractedCSS) -> None:
        """Extract frequency-weighted design tokens from inlined HTML."""
        tokens = DesignTokens()

        # Walk all inline style="" attributes
        style_re = re.compile(r'style="([^"]*)"', re.IGNORECASE)

        for style_match in style_re.finditer(inlined_html):
            style_value = style_match.group(1)

            # Colors (hex)
            for color_match in _HEX_COLOR_RE.finditer(style_value):
                color = color_match.group(0).lower()
                # Normalize 3-digit to 6-digit
                if len(color) == 4:
                    color = f"#{color[1]*2}{color[2]*2}{color[3]*2}"
                tokens.colors[color] = tokens.colors.get(color, 0) + 1

            # Colors (rgb/rgba) — convert to hex for consistency
            for rgb_match in _RGB_COLOR_RE.finditer(style_value):
                rgb_str = rgb_match.group(0)
                hex_color = cls._rgb_to_hex(rgb_str)
                if hex_color:
                    tokens.colors[hex_color] = tokens.colors.get(hex_color, 0) + 1

            # Font families
            for font_match in _FONT_FAMILY_RE.finditer(style_value):
                font = font_match.group(1).strip().strip('"').strip("'")
                # Take first font in stack
                first_font = font.split(',')[0].strip().strip('"').strip("'")
                if first_font:
                    tokens.fonts[first_font] = tokens.fonts.get(first_font, 0) + 1

            # Font sizes
            for size_match in _FONT_SIZE_RE.finditer(style_value):
                size = size_match.group(1).strip()
                tokens.font_sizes[size] = tokens.font_sizes.get(size, 0) + 1

            # Border radii
            for radius_match in _BORDER_RADIUS_RE.finditer(style_value):
                radius = radius_match.group(1).strip()
                tokens.border_radii[radius] = tokens.border_radii.get(radius, 0) + 1

            # Spacing (padding/margin)
            for spacing_match in _SPACING_RE.finditer(style_value):
                spacing = spacing_match.group(1).strip()
                tokens.spacings[spacing] = tokens.spacings.get(spacing, 0) + 1

        # Cap at top-N entries per category
        tokens.colors = cls._top_n(tokens.colors, _MAX_TOKENS_PER_CATEGORY)
        tokens.fonts = cls._top_n(tokens.fonts, _MAX_TOKENS_PER_CATEGORY)
        tokens.font_sizes = cls._top_n(tokens.font_sizes, _MAX_TOKENS_PER_CATEGORY)
        tokens.border_radii = cls._top_n(tokens.border_radii, _MAX_TOKENS_PER_CATEGORY)
        tokens.spacings = cls._top_n(tokens.spacings, _MAX_TOKENS_PER_CATEGORY)

        result.design_tokens = tokens

    @staticmethod
    def _parse_declarations(declarations: str) -> Dict[str, str]:
        """Parse CSS declarations into property → value dict."""
        result: Dict[str, str] = {}
        for decl in declarations.split(';'):
            decl = decl.strip()
            if ':' in decl:
                prop, _, value = decl.partition(':')
                prop = prop.strip().lower()
                value = value.strip()
                if prop and value:
                    result[prop] = value
        return result

    @staticmethod
    def _rgb_to_hex(rgb_str: str) -> Optional[str]:
        """Convert rgb(r, g, b) or rgba(r, g, b, a) to hex."""
        nums = re.findall(r'[\d.]+', rgb_str)
        if len(nums) >= 3:
            try:
                r, g, b = int(float(nums[0])), int(float(nums[1])), int(float(nums[2]))
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                return f"#{r:02x}{g:02x}{b:02x}"
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _top_n(freq_map: Dict[str, int], n: int) -> Dict[str, int]:
        """Return top-N entries by frequency."""
        if len(freq_map) <= n:
            return freq_map
        sorted_items = sorted(freq_map.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_items[:n])
