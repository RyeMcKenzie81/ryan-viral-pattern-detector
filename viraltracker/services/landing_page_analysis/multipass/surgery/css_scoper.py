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

        # 3. Scope CSS rules
        from ..html_extractor import _scope_css_under_class
        scoped_css = _scope_css_under_class(all_css, ".lp-mockup")

        # 4. Rewrite body/html selectors that scope_css_under_class
        #    would have turned into `.lp-mockup body` (matches nothing)
        scoped_css = self._fix_body_html_selectors(scoped_css)

        # 5. Strip animation/transition properties
        scoped_css = _ANIMATION_PROPS_RE.sub("", scoped_css)

        # 6. Add containment CSS
        final_css = _CONTAINMENT_CSS + "\n" + scoped_css

        stats["css_total_chars"] = len(final_css)

        # 7. Extract body content
        body_content = self._extract_body_content(html_no_styles)

        # 8. Wrap in .lp-mockup
        wrapped = f'<div class="lp-mockup">\n{body_content}\n</div>'
        stats["body_wrapped"] = True

        # 9. Build final HTML fragment with single <style> block
        result = f"<style>\n{final_css}\n</style>\n{wrapped}"

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

    def _extract_body_content(self, html: str) -> str:
        """Extract content between <body> and </body>, or return as-is."""
        # Try to find <body> content
        body_match = re.search(
            r'<body[^>]*>(.*)</body>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if body_match:
            return body_match.group(1).strip()

        # No <body> tag — strip <html>/<head> wrappers if present
        result = html
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
