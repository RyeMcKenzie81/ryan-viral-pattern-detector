"""Pass S3: CSS Isolation & Scoping (Deterministic).

Scopes all CSS under ``.lp-mockup`` so the page can be embedded
without style conflicts. Wraps body content in a mockup div.

Zero LLM calls.
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# CSS containment rules for .lp-mockup wrapper
_CONTAINMENT_CSS = """\
.lp-mockup { display: block; position: relative; overflow: hidden; contain: layout style paint; }
.lp-mockup * { box-sizing: border-box; }
"""

# Animation/transition property patterns to strip
_ANIMATION_PROPS_RE = re.compile(
    r'(?:animation|transition)(?:-[a-z-]+)?\s*:[^;]*;',
    re.IGNORECASE,
)

# Match @import statements (handles URLs with semicolons inside quotes/parens)
# Patterns:  @import url("...");  @import url('...');  @import url(...);
#            @import "...";       @import '...';
# Trailing semicolon is optional (some pages omit it).
_IMPORT_RE = re.compile(
    r'@import\s+'
    r'(?:'
    r'url\(\s*(?:"[^"]*"|\'[^\']*\'|[^)]*)\s*\)'  # url("...") or url('...') or url(...)
    r'|"[^"]*"'                                       # "..."
    r"|'[^']*'"                                       # '...'
    r')'
    r'[^;\n]*;?',                                      # optional media query + optional semicolon
    re.IGNORECASE,
)


class CSSScoper:
    """Pass S3: Scope CSS under .lp-mockup and wrap body content."""

    def scope(
        self,
        html: str,
        external_css: str = "",
    ) -> Tuple[str, dict]:
        """Scope CSS and wrap HTML for embedding.

        Args:
            html: Sanitized HTML (may be full document or fragment).
            external_css: Additional CSS from CSSExtractor (media queries,
                custom properties, font-faces).

        Returns:
            (scoped_html, stats) where scoped_html is an embeddable fragment
            with a single <style> block and .lp-mockup wrapper.
        """
        stats = {
            "style_blocks_extracted": 0,
            "css_total_chars": 0,
            "body_wrapped": False,
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

        # 2. Combine all CSS (inline + external)
        all_css_parts = style_parts[:]
        if external_css:
            all_css_parts.append(external_css)

        all_css = "\n".join(all_css_parts)

        # 2b. Extract @import statements BEFORE scoping (they can't be scoped
        #     and must appear before all other rules per CSS spec).
        #     _scope_css_under_class silently drops @import, so we preserve them.
        import_statements = _IMPORT_RE.findall(all_css)
        css_no_imports = _IMPORT_RE.sub("", all_css)

        if import_statements:
            stats["import_statements_preserved"] = len(import_statements)
            logger.debug(
                f"S3: Preserved {len(import_statements)} @import statements"
            )

        # 3. Scope CSS rules (on CSS without @import)
        from ..html_extractor import _scope_css_under_class
        scoped_css = _scope_css_under_class(css_no_imports, ".lp-mockup")

        # 4. Rewrite body/html selectors that scope_css_under_class
        #    would have turned into `.lp-mockup body` (matches nothing)
        scoped_css = self._fix_body_html_selectors(scoped_css)

        # 5. Strip animation/transition properties
        scoped_css = _ANIMATION_PROPS_RE.sub("", scoped_css)

        # 6. Add containment CSS
        final_css = _CONTAINMENT_CSS + "\n" + scoped_css

        stats["css_total_chars"] = len(final_css)

        # 7. Extract body classes and content
        body_classes = self._extract_body_classes(html_no_styles)
        body_content = self._extract_body_content(html_no_styles)

        # 8. Wrap in .lp-mockup (transfer body classes so CSS rules match)
        if body_classes:
            class_attr = f'lp-mockup {body_classes}'
            stats["body_classes_transferred"] = body_classes
        else:
            class_attr = "lp-mockup"
        wrapped = f'<div class="{class_attr}">\n{body_content}\n</div>'
        stats["body_wrapped"] = True

        # 9. Build final HTML fragment
        # @import must appear before all other rules, so they go in a
        # separate <style> block to guarantee ordering.
        parts = []
        if import_statements:
            imports_css = "\n".join(import_statements)
            parts.append(f"<style>\n{imports_css}\n</style>")
        parts.append(f"<style>\n{final_css}\n</style>")
        parts.append(wrapped)
        result = "\n".join(parts)

        return result, stats

    def _fix_body_html_selectors(self, css: str) -> str:
        """Fix body/html selectors that would scope to nothing.

        _scope_css_under_class turns ``body { font: ... }`` into
        ``.lp-mockup body { font: ... }`` which matches nothing since
        there's no <body> inside .lp-mockup.

        Rewrite these to target .lp-mockup itself.
        """
        # Match `.lp-mockup body` or `.lp-mockup html` (with optional
        # combinators after) and replace just the body/html part
        css = re.sub(
            r'\.lp-mockup\s+body\b',
            '.lp-mockup',
            css,
            flags=re.IGNORECASE,
        )
        css = re.sub(
            r'\.lp-mockup\s+html\b',
            '.lp-mockup',
            css,
            flags=re.IGNORECASE,
        )
        return css

    def _extract_body_classes(self, html: str) -> str:
        """Extract CSS classes from the <body> tag.

        These classes are transferred to the .lp-mockup wrapper so CSS
        rules targeting body.class-name (scoped as .lp-mockup.class-name)
        continue to work.
        """
        body_tag = re.search(r'<body\s[^>]*>', html, flags=re.IGNORECASE)
        if not body_tag:
            return ""
        class_match = re.search(
            r'class="([^"]*)"', body_tag.group(0), flags=re.IGNORECASE
        )
        if class_match:
            return class_match.group(1).strip()
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
        # Try to find <body>...</body> (with closing tag)
        body_match = re.search(
            r'<body[^>]*>(.*)</body>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if body_match:
            return body_match.group(1).strip()

        # Handle <body> without </body> (common in Playwright captures):
        # extract everything after the <body...> opening tag
        body_open = re.search(r'<body[^>]*>', html, flags=re.IGNORECASE)
        if body_open:
            content = html[body_open.end():]
            # Strip any trailing </html> if present
            content = re.sub(
                r'</html\s*>\s*$', '', content, flags=re.IGNORECASE
            )
            return content.strip()

        # No <body> tag at all — strip document wrappers
        result = html
        result = re.sub(
            r'<!DOCTYPE[^>]*>', '', result, flags=re.IGNORECASE
        )
        result = re.sub(
            r'<html[^>]*>', '', result, flags=re.IGNORECASE
        )
        result = re.sub(
            r'</html\s*>', '', result, flags=re.IGNORECASE
        )
        result = re.sub(
            r'<head[^>]*>.*?</head\s*>',
            '',
            result,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return result.strip()
