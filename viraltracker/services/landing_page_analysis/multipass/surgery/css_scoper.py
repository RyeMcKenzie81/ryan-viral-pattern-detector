"""Pass S3: CSS Consolidation (Deterministic).

Consolidates all CSS (inline + external) into a standalone HTML document.
No CSS scoping or selector rewriting — CSS stays exactly as authored.
The output is a complete ``<!DOCTYPE html>`` document that can be served
at its own URL or rendered in an iframe.

Zero LLM calls.
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Animation/transition property patterns to strip.
# [^;{}]* prevents matching across rule boundaries (} or {).
# ;? makes the trailing semicolon optional (last property in a rule may omit it).
_ANIMATION_PROPS_RE = re.compile(
    r'(?:animation|transition)(?:-[a-z-]+)?\s*:[^;{}]*;?',
    re.IGNORECASE,
)

# Override appended to end of CSS to ensure standalone documents scroll.
# Third-party CSS (Klaviyo, etc.) often sets body{overflow:hidden} for widget
# contexts. Stripping via regex is fragile on minified CSS, so we just override.
_SCROLL_OVERRIDE_CSS = "\nhtml,body{overflow:auto !important;height:auto !important;}\n"

# Match @import statements (handles URLs with semicolons inside quotes/parens)
_IMPORT_RE = re.compile(
    r'@import\s+'
    r'(?:'
    r'url\(\s*(?:"[^"]*"|\'[^\']*\'|[^)]*)\s*\)'
    r'|"[^"]*"'
    r"|'[^']*'"
    r')'
    r'[^;\n]*;?',
    re.IGNORECASE,
)

# Font-only CDN domains whose <link> tags should be preserved
_FONT_LINK_DOMAINS = frozenset([
    'fonts.googleapis.com', 'fonts.gstatic.com',
])


class CSSScoper:
    """Pass S3: Consolidate CSS into a standalone HTML document."""

    def scope(
        self,
        html: str,
        external_css: str = "",
    ) -> Tuple[str, dict]:
        """Consolidate CSS and produce a standalone HTML document.

        Args:
            html: Classified HTML (full document or fragment from S2).
            external_css: Additional CSS from CSSExtractor (fetched external
                stylesheets — media queries, custom properties, etc.).

        Returns:
            (standalone_html, stats) where standalone_html is a complete
            ``<!DOCTYPE html>`` document with all CSS inlined in ``<head>``.
        """
        stats = {
            "style_blocks_extracted": 0,
            "css_total_chars": 0,
            "body_wrapped": False,
            "link_tags_removed": 0,
            "link_tags_preserved": 0,
        }

        # 1. Extract all <style> blocks from the HTML
        style_parts: List[str] = []

        def _capture_style(match: re.Match) -> str:
            style_parts.append(match.group(1))
            stats["style_blocks_extracted"] += 1
            return ""

        html_no_styles = re.sub(
            r'<style[^>]*>(.*?)</style>',
            _capture_style,
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # 2. Remove external <link rel="stylesheet"> tags (CSS is now inlined)
        #    Preserve font-only CDN links (Google Fonts) for browser loading.
        html_no_styles = self._remove_css_link_tags(html_no_styles, stats)

        # 3. Collect CSS segments: external FIRST, then inline overrides.
        #    Each segment is kept separate so it can be emitted in its own
        #    <style> block.  This prevents brace errors in one third-party
        #    stylesheet (e.g. Okendo's unclosed @media blocks) from
        #    cascading into and breaking subsequent CSS (e.g. Shopify
        #    product layout rules).
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _CSS_FILE_BOUNDARY,
        )

        css_segments: List[str] = []
        if external_css:
            # Split on file boundary markers injected by fetch_raw_external_css
            for segment in external_css.split(_CSS_FILE_BOUNDARY):
                segment = segment.strip()
                if segment:
                    css_segments.append(segment)
        css_segments.extend(style_parts)

        # 4. Process each segment: extract @imports, strip animations,
        #    add scroll override, and escape for XSS.
        import_statements: List[str] = []
        processed_segments: List[str] = []
        total_css_chars = 0

        for seg in css_segments:
            # Extract @import statements (will be emitted first)
            seg_imports = _IMPORT_RE.findall(seg)
            if seg_imports:
                import_statements.extend(seg_imports)
            seg = _IMPORT_RE.sub("", seg)

            # Strip animation/transition properties
            seg = _ANIMATION_PROPS_RE.sub("", seg)

            # Escape </ sequences (XSS defense)
            seg = seg.replace('</', '<\\/')

            seg = seg.strip()
            if seg:
                processed_segments.append(seg)
                total_css_chars += len(seg)

        if import_statements:
            stats["import_statements_preserved"] = len(import_statements)

        # Append scroll override to the last segment
        if processed_segments:
            processed_segments[-1] += _SCROLL_OVERRIDE_CSS
        else:
            processed_segments.append(_SCROLL_OVERRIDE_CSS)

        stats["css_total_chars"] = total_css_chars
        stats["css_segments"] = len(processed_segments)

        # 5. Extract body classes, content, and <head> extras
        body_classes = self._extract_body_classes(html_no_styles)
        body_content = self._extract_body_content(html_no_styles)
        head_extras = self._extract_head_extras(html_no_styles)

        # 6. Build complete standalone HTML document with per-file <style> blocks
        result = self._build_document(
            body_content=body_content,
            body_classes=body_classes,
            head_extras=head_extras,
            import_statements=import_statements,
            css_segments=processed_segments,
        )

        stats["body_wrapped"] = True

        return result, stats

    def _remove_css_link_tags(self, html: str, stats: dict) -> str:
        """Remove <link rel="stylesheet"> tags, preserving font CDN links."""

        def _check_link(match: re.Match) -> str:
            tag = match.group(0)
            href_match = re.search(r'href=["\']([^"\']+)["\']', tag)
            if href_match:
                from urllib.parse import urlparse
                href = href_match.group(1)
                parsed = urlparse(href)
                hostname = (parsed.hostname or "").lower()
                if hostname in _FONT_LINK_DOMAINS:
                    stats["link_tags_preserved"] += 1
                    return tag  # Keep font links
            stats["link_tags_removed"] += 1
            return ""

        return re.sub(
            r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*/?>',
            _check_link,
            html,
            flags=re.IGNORECASE,
        )

    def _build_document(
        self,
        body_content: str,
        body_classes: str,
        head_extras: str,
        import_statements: List[str],
        css_segments: List[str],
    ) -> str:
        """Build a complete HTML document with per-file CSS isolation.

        Each CSS segment is emitted in its own ``<style>`` block so the
        browser parses them independently.  This prevents brace errors in
        one stylesheet from cascading into subsequent stylesheets.
        """
        parts = ['<!DOCTYPE html>', '<html>', '<head>',
                 '<meta charset="utf-8">',
                 '<meta name="viewport" content="width=device-width, initial-scale=1">']

        if head_extras:
            parts.append(head_extras)

        # @import must appear before all other rules
        if import_statements:
            imports_css = "\n".join(import_statements)
            parts.append(f"<style>\n{imports_css}\n</style>")

        for seg in css_segments:
            parts.append(f"<style>\n{seg}\n</style>")

        parts.append('</head>')

        # data-pipeline="surgery" goes on <body> for detection downstream
        if body_classes:
            parts.append(f'<body class="{body_classes}" data-pipeline="surgery">')
        else:
            parts.append('<body data-pipeline="surgery">')

        parts.append(body_content)
        parts.append('</body>')
        parts.append('</html>')

        return "\n".join(parts)

    def _extract_head_extras(self, html: str) -> str:
        """Extract useful <head> content: <title>, <meta>, font <link> tags.

        Strips <style> and non-font <link> tags (already handled separately).
        """
        head_match = re.search(
            r'<head[^>]*>(.*?)</head>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not head_match:
            return ""

        head_content = head_match.group(1)

        # Extract useful tags: <title>, <meta>, preserved font <link> tags
        useful_tags: List[str] = []
        for tag_match in re.finditer(
            r'<(title|meta|link)\b[^>]*/?>(?:[^<]*</\1>)?',
            head_content,
            flags=re.IGNORECASE,
        ):
            tag = tag_match.group(0)
            tag_name = tag_match.group(1).lower()
            # Skip non-font link tags (already removed by _remove_css_link_tags,
            # but head content is extracted from original HTML)
            if tag_name == "link":
                href_match = re.search(r'href=["\']([^"\']+)["\']', tag)
                if href_match:
                    from urllib.parse import urlparse
                    hostname = (urlparse(href_match.group(1)).hostname or "").lower()
                    if hostname not in _FONT_LINK_DOMAINS:
                        continue
            # Skip charset/viewport meta (we add our own)
            if tag_name == "meta":
                if 'charset' in tag.lower() or 'viewport' in tag.lower():
                    continue
            useful_tags.append(tag)

        return "\n".join(useful_tags)

    # Classes that block scrolling when set on <body> by third-party scripts
    _SCROLL_BLOCKING_CLASSES = frozenset([
        "klaviyo-prevent-body-scrolling",
        "no-scroll",
        "modal-open",
        "overflow-hidden",
    ])

    def _extract_body_classes(self, html: str) -> str:
        """Extract CSS classes from the <body> tag, stripping scroll-blockers."""
        body_tag = re.search(r'<body\s[^>]*>', html, flags=re.IGNORECASE)
        if not body_tag:
            return ""
        class_match = re.search(
            r'class="([^"]*)"', body_tag.group(0), flags=re.IGNORECASE
        )
        if class_match:
            classes = class_match.group(1).strip()
            # Strip classes that block scrolling on standalone documents
            filtered = " ".join(
                c for c in classes.split()
                if c not in self._SCROLL_BLOCKING_CLASSES
            )
            return filtered
        class_match_single = re.search(
            r"class='([^']*)'", body_tag.group(0), flags=re.IGNORECASE
        )
        if class_match_single:
            return class_match_single.group(1).strip()
        return ""

    def _extract_body_content(self, html: str) -> str:
        """Extract content between <body> and </body>, or return as-is.

        Handles Playwright-captured DOMs which often lack </body> closing tags.
        """
        body_match = re.search(
            r'<body[^>]*>(.*)</body>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if body_match:
            return body_match.group(1).strip()

        body_open = re.search(r'<body[^>]*>', html, flags=re.IGNORECASE)
        if body_open:
            content = html[body_open.end():]
            content = re.sub(
                r'</html\s*>\s*$', '', content, flags=re.IGNORECASE
            )
            return content.strip()

        # No <body> tag — strip document wrappers
        result = html
        result = re.sub(r'<!DOCTYPE[^>]*>', '', result, flags=re.IGNORECASE)
        result = re.sub(r'<html[^>]*>', '', result, flags=re.IGNORECASE)
        result = re.sub(r'</html\s*>', '', result, flags=re.IGNORECASE)
        result = re.sub(
            r'<head[^>]*>.*?</head\s*>',
            '',
            result,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return result.strip()
