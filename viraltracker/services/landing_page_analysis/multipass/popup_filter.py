"""Conservative model-guided overlay removal.

Removes ONLY elements matching Phase 0 detected overlays.
Whitelists nav/header/footer tags, CTA-related classes, and data-slot elements.
If Phase 0 detected no overlays, filter does nothing.
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Whitelisted tags -- never remove
_WHITELISTED_TAGS = frozenset(['nav', 'header', 'footer'])

# Whitelisted class substrings -- never remove elements with these classes
_WHITELISTED_CLASS_PATTERNS = frozenset([
    'cta', 'buy', 'order', 'cart', 'checkout', 'nav', 'header', 'footer',
])


class PopupFilter:
    """Remove popup/overlay elements from HTML based on Phase 0 detection."""

    def filter(
        self,
        html: str,
        detected_overlays: Optional[List[Dict]] = None,
    ) -> str:
        """Remove detected overlay elements from HTML.

        Args:
            html: Input HTML.
            detected_overlays: List of overlay dicts from Phase 0 with keys:
                - type: 'modal', 'banner', 'popup', 'cookie', 'overlay'
                - css_hint: Optional CSS class/id hint for removal
                - description: Human-readable description

        Returns:
            HTML with detected overlays removed. Unchanged if no overlays detected.
        """
        if not detected_overlays:
            return html

        result = html
        removed = 0

        for overlay in detected_overlays:
            css_hint = overlay.get('css_hint', '')
            overlay_type = overlay.get('type', '')

            if not css_hint:
                continue

            # Try to find and remove the matching element
            new_result = self._remove_overlay(result, css_hint, overlay_type)
            if new_result != result:
                removed += 1
                result = new_result

        if removed:
            logger.info(f"PopupFilter removed {removed} overlay(s)")

        return result

    def _remove_overlay(self, html: str, css_hint: str, overlay_type: str) -> str:
        """Attempt to remove a single overlay element by CSS hint."""
        # Try as class name
        pattern = self._build_removal_pattern(css_hint)
        if not pattern:
            return html

        # Find the element
        match = pattern.search(html)
        if not match:
            return html

        # Check tag against whitelist
        tag = match.group(1)
        if tag in _WHITELISTED_TAGS:
            logger.debug(f"Overlay removal blocked: tag '{tag}' is whitelisted")
            return html

        # Check class against whitelist
        attr_str = match.group(2) or ''
        if self._has_whitelisted_class(attr_str):
            logger.debug(f"Overlay removal blocked: has whitelisted class")
            return html

        # Check for data-slot attribute
        if 'data-slot=' in attr_str:
            logger.debug(f"Overlay removal blocked: has data-slot attribute")
            return html

        # Find element bounds and remove
        start = match.start()
        end = self._find_element_end(html, tag, match.end())

        return html[:start] + html[end:]

    def _build_removal_pattern(self, css_hint: str) -> Optional[re.Pattern]:
        """Build a regex pattern to find an element by CSS hint."""
        css_hint = css_hint.strip()

        if css_hint.startswith('.'):
            # Class-based
            class_name = re.escape(css_hint[1:])
            return re.compile(
                rf'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?class="[^"]*\b{class_name}\b[^"]*"[^>]*)>',
                re.DOTALL | re.IGNORECASE,
            )
        elif css_hint.startswith('#'):
            # ID-based
            id_name = re.escape(css_hint[1:])
            return re.compile(
                rf'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?id="{id_name}"[^>]*)>',
                re.DOTALL | re.IGNORECASE,
            )
        elif re.match(r'^[a-zA-Z]', css_hint):
            # Could be a class name without the dot
            class_name = re.escape(css_hint)
            return re.compile(
                rf'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?class="[^"]*\b{class_name}\b[^"]*"[^>]*)>',
                re.DOTALL | re.IGNORECASE,
            )

        return None

    @staticmethod
    def _has_whitelisted_class(attr_str: str) -> bool:
        """Check if attribute string contains any whitelisted class patterns."""
        class_match = re.search(r'class="([^"]*)"', attr_str, re.IGNORECASE)
        if not class_match:
            return False

        class_str = class_match.group(1).lower()
        return any(p in class_str for p in _WHITELISTED_CLASS_PATTERNS)

    @staticmethod
    def _find_element_end(html: str, tag: str, start_after: int) -> int:
        """Find the end of an element (after closing tag)."""
        void_elements = frozenset([
            'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr',
        ])

        if tag in void_elements:
            return start_after

        depth = 1
        open_re = re.compile(rf'<{tag}(?:\s[^>]*)?>|</{tag}\s*>', re.IGNORECASE)

        for m in open_re.finditer(html, start_after):
            if m.group().startswith(f'</{tag}'):
                depth -= 1
                if depth == 0:
                    return m.end()
            elif not m.group().endswith('/>'):
                depth += 1

        return len(html)
