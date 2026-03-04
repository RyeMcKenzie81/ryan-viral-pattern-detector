"""Deterministic HTML patch application with restricted selector grammar.

Phase 4 outputs JSON patches that are applied here -- no LLM involvement.

For css_fix patches on full HTML documents (containing </head>), patches are
injected as a <style> block before </head> with !important to override inline
styles. This allows any valid CSS selector to work because the browser handles
matching natively.

For css_fix on HTML fragments (no </head>) and for add_element/remove_element,
only a restricted selector grammar is supported; anything else is rejected.
"""

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Restricted selector patterns
_ATTR_SELECTOR_RE = re.compile(
    r'^\[([a-zA-Z_-]+)=[\'"]([^"\']+)[\'"]\]$'
)
_ATTR_CONTAINS_RE = re.compile(
    r'^\[([a-zA-Z_-]+)\*=[\'"]([^"\']+)[\'"]\]$'
)
_CLASS_SELECTOR_RE = re.compile(r'^\.([a-zA-Z_-][a-zA-Z0-9_-]*)$')
_ID_SELECTOR_RE = re.compile(r'^#([a-zA-Z_-][a-zA-Z0-9_-]*)$')
_TAG_SELECTOR_RE = re.compile(r'^([a-zA-Z][a-zA-Z0-9]*)$')
_TAG_CLASS_RE = re.compile(
    r'^([a-zA-Z][a-zA-Z0-9]*)\.([a-zA-Z_-][a-zA-Z0-9_-]*)$'
)
_TAG_ATTR_RE = re.compile(
    r'^([a-zA-Z][a-zA-Z0-9]*)\[([a-zA-Z_-]+)=[\'"]([^"\']+)[\'"]\]$'
)
_TAG_ATTR_CONTAINS_RE = re.compile(
    r'^([a-zA-Z][a-zA-Z0-9]*)\[([a-zA-Z_-]+)\*=[\'"]([^"\']+)[\'"]\]$'
)

# Max elements a *= selector can match before being skipped
_CONTAINS_MATCH_CAP = 5

# Protected attributes that patches must never modify
_PROTECTED_ATTRS = frozenset(['data-slot', 'data-section'])

# Patterns that indicate CSS injection attempts
_CSS_INJECTION_PATTERNS = ("</style", "javascript:", "expression(", "@import")


def _css_contains_injection(value: str) -> bool:
    """Check if a CSS value/selector could break out of a style block."""
    lower = value.lower()
    return any(x in lower for x in _CSS_INJECTION_PATTERNS)


# Patterns that destroy page layout when injected by S4 QA patches
_S4_DESTRUCTIVE_DECL_RE = re.compile(
    r'(?:^|\s|;)'
    r'(?:'
    r'margin-left\s*:\s*auto'
    r'|margin-right\s*:\s*auto'
    r'|margin\s*:\s*(?:0\s+)?auto'
    r'|float\s*:\s*(?:left|right)'
    r'|position\s*:\s*(?:fixed|sticky)'
    r')',
    re.IGNORECASE,
)


def _strip_destructive_declarations(css_value: str) -> str:
    """Remove layout-destructive declarations from a CSS value string.

    Only used for S4 QA patches to prevent Gemini from inventing
    layout constraints (centering, floats, fixed positioning) that
    destroy the page structure established by S3 CSS scoping.
    """
    parts = [p.strip() for p in css_value.split(";") if p.strip()]
    kept = []
    for part in parts:
        if _S4_DESTRUCTIVE_DECL_RE.search(part):
            logger.info(f"S4 patch: stripped destructive declaration: {part}")
            continue
        kept.append(part)
    return "; ".join(kept)


_MARKDOWN_FENCE_PA_RE = re.compile(r'```(?:css|scss|less|text)?\s*\n?', re.IGNORECASE)


def _add_important(css_value: str) -> str:
    """Add !important to each CSS property declaration."""
    # Strip markdown fences that LLMs sometimes leak into CSS values
    css_value = _MARKDOWN_FENCE_PA_RE.sub('', css_value).strip()
    parts = [p.strip() for p in css_value.split(";") if p.strip()]
    result = []
    for part in parts:
        if "!important" not in part:
            result.append(f"{part} !important")
        else:
            result.append(part)
    return "; ".join(result) + ";"


@dataclass
class ParsedSelector:
    """A parsed restricted selector."""
    tag: Optional[str] = None
    id: Optional[str] = None
    class_name: Optional[str] = None
    attr_name: Optional[str] = None
    attr_value: Optional[str] = None
    match_mode: str = "exact"  # "exact" or "contains"


def parse_selector(selector: str) -> ParsedSelector:
    """Parse a restricted selector grammar string.

    Supported patterns:
    - [attr='value']     - Exact attribute match
    - .classname         - Class in element's class list
    - #id                - Exact id match
    - tag                - Tag name match
    - tag.classname      - Tag + class match
    - tag[attr='value']  - Tag + attribute match

    Raises:
        ValueError: For unsupported selector patterns.
    """
    selector = selector.strip()
    if not selector:
        raise ValueError("Empty selector")

    # [attr*='value'] (contains match)
    m = _ATTR_CONTAINS_RE.match(selector)
    if m:
        return ParsedSelector(
            attr_name=m.group(1), attr_value=m.group(2), match_mode="contains"
        )

    # [attr='value'] (exact match)
    m = _ATTR_SELECTOR_RE.match(selector)
    if m:
        return ParsedSelector(attr_name=m.group(1), attr_value=m.group(2))

    # .classname
    m = _CLASS_SELECTOR_RE.match(selector)
    if m:
        return ParsedSelector(class_name=m.group(1))

    # #id
    m = _ID_SELECTOR_RE.match(selector)
    if m:
        return ParsedSelector(id=m.group(1))

    # tag.classname
    m = _TAG_CLASS_RE.match(selector)
    if m:
        return ParsedSelector(tag=m.group(1), class_name=m.group(2))

    # tag[attr*='value'] (contains match)
    m = _TAG_ATTR_CONTAINS_RE.match(selector)
    if m:
        return ParsedSelector(
            tag=m.group(1), attr_name=m.group(2), attr_value=m.group(3),
            match_mode="contains"
        )

    # tag[attr='value'] (exact match)
    m = _TAG_ATTR_RE.match(selector)
    if m:
        return ParsedSelector(tag=m.group(1), attr_name=m.group(2), attr_value=m.group(3))

    # tag (must be last -- most permissive)
    m = _TAG_SELECTOR_RE.match(selector)
    if m:
        return ParsedSelector(tag=m.group(1))

    raise ValueError(f"Unsupported selector: {selector}")


def _element_matches(
    tag: str,
    attrs: List[Tuple[str, Optional[str]]],
    selector: ParsedSelector,
) -> bool:
    """Check if an HTML element matches a parsed selector."""
    attrs_dict = {k: v for k, v in attrs}

    if selector.tag and tag != selector.tag:
        return False

    if selector.id and attrs_dict.get('id') != selector.id:
        return False

    if selector.class_name:
        class_list = (attrs_dict.get('class') or '').split()
        if selector.class_name not in class_list:
            return False

    if selector.attr_name:
        actual_value = attrs_dict.get(selector.attr_name)
        if actual_value is None:
            return False
        if selector.match_mode == "contains":
            if selector.attr_value not in actual_value:
                return False
        else:
            if actual_value != selector.attr_value:
                return False

    return True


def _has_visible_text(html: str) -> bool:
    """Check if HTML fragment contains any visible text (non-whitespace text nodes)."""
    class TextChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.has_text = False
            self._in_hidden = False

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'):
                self._in_hidden = True

        def handle_endtag(self, tag):
            if tag in ('script', 'style'):
                self._in_hidden = False

        def handle_data(self, data):
            if not self._in_hidden and data.strip():
                self.has_text = True

    checker = TextChecker()
    try:
        checker.feed(html)
    except Exception:
        pass
    return checker.has_text


def _has_protected_attrs(html: str) -> bool:
    """Check if HTML fragment contains data-slot or data-section attributes."""
    return 'data-slot=' in html or 'data-section=' in html


class PatchApplier:
    """Walk HTML, apply patches at matching elements.

    Match modes per patch type:
    - css_fix:        match_mode='all'           - apply to all matching elements
    - add_element:    match_mode='first'          - insert after first match only
    - remove_element: match_mode='required_one'   - MUST match exactly 1 element

    Invariants:
    - Never modify text content between tags
    - Never modify data-slot or data-section attributes
    - add_element payloads stripped of visible text and protected attrs
    """

    def apply_patches(
        self, html: str, patches: List[Dict], strip_destructive: bool = False,
    ) -> str:
        """Apply patches deterministically. Returns modified HTML.

        For css_fix patches on full HTML documents (containing </head>),
        patches are injected as a <style> block. This supports any valid
        CSS selector. For fragments, falls back to inline style modification
        with restricted selector grammar.

        add_element/remove_element always use restricted grammar regardless.

        Args:
            html: Input HTML to patch.
            patches: List of patch dicts with keys:
                - type: 'css_fix', 'add_element', or 'remove_element'
                - selector: CSS selector string
                - value: For css_fix: CSS property string. For add_element: HTML to insert.
            strip_destructive: If True, remove layout-destructive CSS
                declarations from css_fix patches (S4 QA only).

        Returns:
            Modified HTML string.
        """
        if not patches:
            return html

        is_full_document = "</head>" in html.lower()

        # Separate css_fix patches for full documents (style-block path)
        css_fix_patches = []
        other_patches = []
        for patch in patches:
            if patch.get("type") == "css_fix" and is_full_document:
                css_fix_patches.append(patch)
            else:
                other_patches.append(patch)

        result = html
        applied = 0
        skipped = 0

        # Apply css_fix patches as a single style block (full doc only)
        if css_fix_patches:
            result = self._apply_css_fix_via_style_block(
                result, css_fix_patches, strip_destructive=strip_destructive,
            )
            applied += len(css_fix_patches)

        # Apply remaining patches via existing per-patch logic
        for patch in other_patches:
            try:
                patch_type = patch.get('type', '')
                selector_str = patch.get('selector', '')
                value = patch.get('value', '')

                if not selector_str or not patch_type:
                    logger.warning(f"Patch missing type or selector, skipping: {patch}")
                    skipped += 1
                    continue

                # Split comma-separated selectors into individual sub-selectors
                sub_selectors = [s.strip() for s in selector_str.split(',')]
                sub_selectors = [s for s in sub_selectors if s]

                if not sub_selectors:
                    logger.warning(f"Selector resolved to empty after split: '{selector_str}', skipping")
                    skipped += 1
                    continue

                sub_applied = False
                for sub_sel_str in sub_selectors:
                    try:
                        selector = parse_selector(sub_sel_str)
                    except ValueError as e:
                        logger.warning(f"Unsupported selector '{sub_sel_str}': {e}, skipping sub-selector")
                        continue

                    if patch_type == 'css_fix':
                        result = self._apply_css_fix(result, selector, value)
                        sub_applied = True
                    elif patch_type == 'add_element':
                        result = self._apply_add_element(result, selector, value)
                        sub_applied = True
                    elif patch_type == 'remove_element':
                        result = self._apply_remove_element(result, selector)
                        sub_applied = True
                    else:
                        logger.warning(f"Unknown patch type '{patch_type}', skipping")

                if sub_applied:
                    applied += 1
                else:
                    skipped += 1

            except Exception as e:
                logger.warning(f"Patch application failed: {e}, skipping")
                skipped += 1

        logger.info(f"PatchApplier: applied={applied}, skipped={skipped}")
        return result

    def _apply_css_fix_via_style_block(
        self, html: str, patches: List[Dict], strip_destructive: bool = False,
    ) -> str:
        """Inject css_fix patches as a <style> block before </head>.

        Adds !important to each property to override inline styles.
        Sanitizes selectors/values to prevent injection.

        Args:
            html: HTML document string.
            patches: List of css_fix patch dicts.
            strip_destructive: If True, remove layout-destructive
                declarations before applying (S4 QA only).
        """
        rules = []
        for patch in patches:
            selector = patch.get("selector", "").strip()
            css_value = patch.get("value", "").strip()
            if not selector or not css_value:
                continue
            # Sanitize: reject anything that could break out of <style>
            if _css_contains_injection(selector) or _css_contains_injection(css_value):
                logger.warning("CSS injection attempt blocked in selector or value, skipping")
                continue
            # Strip destructive declarations for S4 patches
            if strip_destructive:
                css_value = _strip_destructive_declarations(css_value)
                if not css_value:
                    logger.info("S4 patch: all declarations stripped, skipping patch")
                    continue
            # Add !important to each property
            important_css = _add_important(css_value)
            rules.append(f"  {selector} {{ {important_css} }}")

        if not rules:
            return html

        style_block = "\n<style data-patch-applier>\n" + "\n".join(rules) + "\n</style>\n"
        # Insert before </head> (case-insensitive find, preserve original case)
        head_close_idx = html.lower().find("</head>")
        if head_close_idx == -1:
            return html
        return html[:head_close_idx] + style_block + html[head_close_idx:]

    def _apply_css_fix(self, html: str, selector: ParsedSelector, css_value: str) -> str:
        """Apply CSS style fix to all matching elements."""
        # Guard: cap *= selector matches at 5 to prevent mass-modification
        if selector.match_mode == "contains":
            matches = self._find_matches(html, selector)
            if len(matches) > _CONTAINS_MATCH_CAP:
                logger.warning(
                    f"*= selector too broad: matched {len(matches)} elements "
                    f"(cap={_CONTAINS_MATCH_CAP}), skipping patch"
                )
                return html
        return self._modify_elements(html, selector, 'all', 'style', css_value)

    def _apply_add_element(self, html: str, selector: ParsedSelector, payload: str) -> str:
        """Insert element after first matching element."""
        # Block content elements — add_element is for structural decorations only
        if re.search(r'<img\b', payload, re.IGNORECASE):
            logger.warning("add_element payload contains <img> tag, skipping")
            return html
        # Validate payload: no visible text, no protected attrs
        if _has_visible_text(payload):
            logger.warning("add_element payload contains visible text, skipping")
            return html
        if _has_protected_attrs(payload):
            logger.warning("add_element payload contains protected attributes, skipping")
            return html

        return self._insert_after(html, selector, payload)

    def _apply_remove_element(self, html: str, selector: ParsedSelector) -> str:
        """Remove exactly one matching element."""
        matches = self._find_matches(html, selector)
        if len(matches) != 1:
            logger.warning(
                f"remove_element: expected 1 match, found {len(matches)}, skipping"
            )
            return html

        start, end = matches[0]
        return html[:start] + html[end:]

    def _find_matches(
        self, html: str, selector: ParsedSelector
    ) -> List[Tuple[int, int]]:
        """Find all element positions matching the selector.

        Returns list of (start_offset, end_offset) tuples.
        """
        matches = []
        tag_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?)>', re.DOTALL)

        for m in tag_pattern.finditer(html):
            tag = m.group(1)
            attr_str = m.group(2)
            attrs = self._parse_attrs(attr_str)

            if _element_matches(tag, attrs, selector):
                start = m.start()
                # Find the closing tag
                end = self._find_element_end(html, tag, m.end())
                matches.append((start, end))

        return matches

    def _find_element_end(self, html: str, tag: str, start_after: int) -> int:
        """Find the end position of an element (after its closing tag).

        Handles void elements and nested same-tag elements.
        """
        void_elements = frozenset([
            'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr',
        ])

        if tag in void_elements:
            return start_after

        depth = 1
        pos = start_after
        open_re = re.compile(rf'<{tag}(?:\s[^>]*)?>|</{tag}\s*>', re.IGNORECASE)

        for m in open_re.finditer(html, pos):
            if m.group().startswith(f'</{tag}'):
                depth -= 1
                if depth == 0:
                    return m.end()
            elif not m.group().endswith('/>'):
                depth += 1

        # No closing tag found, return end of string
        return len(html)

    def _modify_elements(
        self,
        html: str,
        selector: ParsedSelector,
        match_mode: str,
        attr_to_modify: str,
        value: str,
    ) -> str:
        """Modify an attribute on matching elements."""
        tag_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?)(/?)>', re.DOTALL)
        offset = 0
        result = html
        applied = False

        for m in tag_pattern.finditer(html):
            tag = m.group(1)
            attr_str = m.group(2)
            self_close = m.group(3)
            attrs = self._parse_attrs(attr_str)

            if not _element_matches(tag, attrs, selector):
                continue

            if match_mode == 'first' and applied:
                break

            # Build new attribute string, adding/updating the target attr
            # For css_fix, we merge with existing style
            existing_style = dict(attrs).get('style', '')
            if existing_style:
                new_style = f"{existing_style}; {value}"
            else:
                new_style = value

            new_attrs = []
            style_added = False
            for name, val in attrs:
                if name in _PROTECTED_ATTRS:
                    # Never modify protected attrs
                    new_attrs.append((name, val))
                elif name == 'style' and attr_to_modify == 'style':
                    new_attrs.append(('style', new_style))
                    style_added = True
                else:
                    new_attrs.append((name, val))

            if not style_added and attr_to_modify == 'style':
                new_attrs.append(('style', new_style))

            # Reconstruct tag
            attr_parts = []
            for name, val in new_attrs:
                if val is not None:
                    attr_parts.append(f'{name}="{val}"')
                else:
                    attr_parts.append(name)

            new_attr_str = ' '.join(attr_parts)
            if new_attr_str:
                new_attr_str = ' ' + new_attr_str

            new_tag = f'<{tag}{new_attr_str}{self_close}>'
            old_tag = m.group(0)

            # Apply replacement with offset tracking
            start = m.start() + offset
            end = m.end() + offset
            result = result[:start] + new_tag + result[end:]
            offset += len(new_tag) - len(old_tag)
            applied = True

        return result

    def _insert_after(self, html: str, selector: ParsedSelector, payload: str) -> str:
        """Insert payload after the first matching element's closing tag."""
        matches = self._find_matches(html, selector)
        if not matches:
            logger.warning("add_element: no matches found, skipping")
            return html

        # Insert after first match
        _, end = matches[0]
        return html[:end] + payload + html[end:]

    @staticmethod
    def _parse_attrs(attr_str: str) -> List[Tuple[str, Optional[str]]]:
        """Parse HTML attribute string into list of (name, value) tuples."""
        attrs = []
        if not attr_str:
            return attrs

        attr_re = re.compile(
            r'([a-zA-Z_:][a-zA-Z0-9_.:-]*)'
            r'(?:\s*=\s*'
            r'(?:"([^"]*)"'
            r"|'([^']*)'"
            r'|(\S+))'
            r')?'
        )

        for m in attr_re.finditer(attr_str):
            name = m.group(1)
            value = m.group(2) or m.group(3) or m.group(4)
            attrs.append((name, value))

        return attrs
