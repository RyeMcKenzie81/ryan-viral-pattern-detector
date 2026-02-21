"""HTML extraction for multipass pipeline v4.

Parses original page HTML to extract:
- ImageRegistry: per-section image mapping with dimensions
- CSSExtractor: responsive CSS (custom properties, media queries, font-faces)
- restore_background_images(): display-boundary conversion for bg markers

No LLM involved — pure deterministic extraction.
"""

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from ._url_validator import _MARKDOWN_IMAGE_RE, validate_image_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageImage:
    """An image extracted from the original page HTML."""

    url: str
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    srcset: Optional[str] = None
    is_background: bool = False
    is_icon: bool = False
    section_ids: List[str] = field(default_factory=list)


class ImageRegistry:
    """Deduplicated image registry with per-section mapping."""

    def __init__(self) -> None:
        self.images: Dict[str, PageImage] = {}  # url -> PageImage
        self.section_map: Dict[str, List[str]] = {}  # sec_N -> [urls]

    @classmethod
    def build(
        cls,
        original_html: str,
        sections: list,  # List[SegmenterSection]
        page_url: str = "",
    ) -> "ImageRegistry":
        """Build registry from original HTML + segmenter sections.

        Args:
            original_html: Full page HTML (may be empty for fallback).
            sections: SegmenterSection list with .section_id and .markdown.
            page_url: Base URL for resolving relative image URLs.
        """
        registry = cls()

        # Step 1: Parse HTML for <img> tags with dimensions
        html_images: Dict[str, PageImage] = {}
        if original_html:
            parser = _ImageHTMLParser(page_url)
            try:
                parser.feed(original_html)
            except Exception as e:
                logger.warning(f"HTML image parsing failed: {e}")
            html_images = {img.url: img for img in parser.images if img.url}

        # Step 2: Parse each section's markdown for ![alt](url)
        for section in sections:
            sec_id = section.section_id
            registry.section_map[sec_id] = []

            for match in _MARKDOWN_IMAGE_RE.finditer(section.markdown):
                alt = match.group(1).strip()
                raw_url = match.group(2).strip()

                # Resolve relative URLs
                if page_url and not raw_url.startswith(('http://', 'https://', 'data:')):
                    resolved = urljoin(page_url, raw_url)
                else:
                    resolved = raw_url

                # Validate
                is_safe, safe_url, _ = validate_image_url(resolved)
                if not is_safe:
                    continue

                # Merge with HTML data if available
                if safe_url in html_images:
                    img = html_images[safe_url]
                    if alt and not img.alt:
                        img.alt = alt
                    if sec_id not in img.section_ids:
                        img.section_ids.append(sec_id)
                else:
                    img = PageImage(url=safe_url, alt=alt or "image")
                    img.section_ids.append(sec_id)

                registry.images[safe_url] = img
                if safe_url not in registry.section_map[sec_id]:
                    registry.section_map[sec_id].append(safe_url)

        # Step 3: Add HTML-only images (not found in any section markdown)
        # Use text-proximity mapping for these
        if original_html and sections:
            section_headings = _extract_section_headings(sections)
            html_headings = _extract_html_heading_positions(original_html)

            for url, img in html_images.items():
                if url in registry.images:
                    continue  # Already mapped via markdown

                is_safe, safe_url, _ = validate_image_url(url)
                if not is_safe:
                    continue

                # Try text-proximity mapping
                best_section = _proximity_map_image(
                    img, html_headings, section_headings
                )
                if best_section:
                    img.section_ids.append(best_section)
                    registry.section_map.setdefault(best_section, [])
                    if safe_url not in registry.section_map[best_section]:
                        registry.section_map[best_section].append(safe_url)
                # else: unassigned — will NOT be injected

                registry.images[safe_url] = img

        return registry

    def get_section_images(self, sec_id: str) -> List[PageImage]:
        """Get only images assigned to this section."""
        urls = self.section_map.get(sec_id, [])
        return [self.images[url] for url in urls if url in self.images]


# ---------------------------------------------------------------------------
# CSS extraction
# ---------------------------------------------------------------------------


@dataclass
class ResponsiveCSS:
    """Extracted responsive CSS from original page."""

    custom_properties: str = ""  # :root { --color-primary: ... }
    media_queries: str = ""  # @media (...) { ... }
    font_faces: str = ""  # @font-face { ... }

    def to_css_block(self) -> str:
        """Combine all CSS parts into a single block."""
        parts = []
        if self.font_faces:
            parts.append(self.font_faces)
        if self.custom_properties:
            parts.append(self.custom_properties)
        if self.media_queries:
            parts.append(self.media_queries)
        return "\n\n".join(parts)


MAX_CSS_TOTAL_SIZE = 50 * 1024  # 50KB cap
MAX_CSS_RESPONSE_BYTES = 500 * 1024  # 500KB per external stylesheet
_MAX_EXTERNAL_CSS_FETCHES = 3

# CDN domains to skip (not page-specific)
_CDN_DOMAINS = frozenset([
    'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com',
    'fonts.googleapis.com', 'fonts.gstatic.com',
    'stackpath.bootstrapcdn.com', 'maxcdn.bootstrapcdn.com',
    'cdn.tailwindcss.com', 'use.fontawesome.com',
    'kit.fontawesome.com', 'ajax.googleapis.com',
])


class CSSExtractor:
    """Extract responsive CSS from original page HTML."""

    @classmethod
    def extract(cls, original_html: str, page_url: str = "") -> ResponsiveCSS:
        """Extract custom properties, media queries, and font-faces from HTML.

        Sources:
        1. Inline <style> blocks (always available)
        2. External first-party <link rel="stylesheet"> (best-effort fetch)
        """
        if not original_html:
            return ResponsiveCSS()

        css_parts: List[str] = []

        # Source 1: Inline <style> blocks
        for match in re.finditer(
            r'<style[^>]*>(.*?)</style>', original_html, re.DOTALL | re.IGNORECASE
        ):
            css_parts.append(match.group(1))

        # Source 2: External first-party stylesheets
        page_hostname = urlparse(page_url).hostname or "" if page_url else ""
        if page_hostname:
            link_urls = _extract_stylesheet_urls(original_html, page_url)
            fetched = 0
            for css_url in link_urls:
                if fetched >= _MAX_EXTERNAL_CSS_FETCHES:
                    break
                parsed = urlparse(css_url)
                css_host = parsed.hostname or ""
                if not _is_first_party(css_host, page_hostname):
                    continue
                try:
                    css_text = _safe_fetch_css(css_url, page_hostname)
                    if css_text:
                        css_parts.append(css_text)
                        fetched += 1
                except Exception as e:
                    logger.debug(f"External CSS fetch failed: {e}")

        # Parse all collected CSS
        all_css = "\n".join(css_parts)
        return cls._parse_css(all_css)

    @classmethod
    def _parse_css(cls, raw_css: str) -> ResponsiveCSS:
        """Parse raw CSS text into structured ResponsiveCSS."""
        result = ResponsiveCSS()
        if not raw_css:
            return result

        custom_props: List[str] = []
        media_queries: List[str] = []
        font_faces: List[str] = []

        # Extract top-level blocks using brace-depth tracking
        blocks = _split_top_level_blocks(raw_css)

        for block_type, block_content in blocks:
            if block_type == "font-face":
                # Keep font-family/font-weight/font-display, strip src: urls
                cleaned = _clean_font_face(block_content)
                if cleaned:
                    font_faces.append(cleaned)
            elif block_type == "media":
                media_queries.append(block_content)
            elif block_type == "root":
                custom_props.append(block_content)

        result.custom_properties = "\n".join(custom_props)
        result.media_queries = "\n".join(media_queries)
        result.font_faces = "\n".join(font_faces)

        # Cap total size
        total = result.to_css_block()
        if len(total) > MAX_CSS_TOTAL_SIZE:
            logger.warning(
                f"Extracted CSS too large ({len(total)} bytes), truncating"
            )
            # Prioritize: custom_properties > media_queries > font_faces
            result.font_faces = result.font_faces[: MAX_CSS_TOTAL_SIZE // 3]
            result.media_queries = result.media_queries[: MAX_CSS_TOTAL_SIZE // 3]
            result.custom_properties = result.custom_properties[
                : MAX_CSS_TOTAL_SIZE // 3
            ]

        return result


# ---------------------------------------------------------------------------
# CSS scoping under .lp-mockup
# ---------------------------------------------------------------------------

# CSS timing/easing keywords that are NOT animation names
_CSS_ANIMATION_KEYWORDS = frozenset([
    'ease', 'linear', 'ease-in', 'ease-out', 'ease-in-out',
    'step-start', 'step-end', 'infinite', 'alternate', 'reverse',
    'forwards', 'backwards', 'both', 'paused', 'running',
    'normal', 'none', 'initial', 'inherit', 'unset',
])


def _scope_css_under_class(css: str, scope_class: str) -> str:
    """Scope CSS rules under a class selector.

    Handles at-rules correctly:
    - Regular selectors: prepend scope_class
    - :root vars: rewrite to scope_class
    - @media: scope inner rules only
    - @font-face: do NOT scope (global by spec)
    - @keyframes: do NOT scope, prefix name with 'lp-'
    - @supports: recurse into inner rules
    """
    if not css or not css.strip():
        return css

    blocks = _split_top_level_blocks(css)
    scoped_parts: List[str] = []
    keyframe_rename_map: Dict[str, str] = {}

    # First pass: collect keyframe renames
    for block_type, block_content in blocks:
        if block_type == "keyframes":
            name = _extract_keyframe_name(block_content)
            if name and not name.startswith("lp-"):
                keyframe_rename_map[name] = f"lp-{name}"

    # Second pass: scope and rename
    for block_type, block_content in blocks:
        if block_type == "font-face":
            # Emit as-is (global by spec)
            scoped_parts.append(block_content)
        elif block_type == "keyframes":
            # Rename keyframe
            renamed = _rename_keyframe(block_content, keyframe_rename_map)
            scoped_parts.append(renamed)
        elif block_type == "media":
            # Scope inner rules
            inner_scoped = _scope_at_rule_inner(
                block_content, scope_class, keyframe_rename_map
            )
            scoped_parts.append(inner_scoped)
        elif block_type == "supports":
            inner_scoped = _scope_at_rule_inner(
                block_content, scope_class, keyframe_rename_map
            )
            scoped_parts.append(inner_scoped)
        elif block_type == "root":
            # Rewrite :root { ... } to .scope_class { ... }
            rewritten = re.sub(
                r':root\s*\{', f'{scope_class} {{', block_content, count=1
            )
            scoped_parts.append(rewritten)
        else:
            # Regular selector block
            scoped = _scope_selector_block(
                block_content, scope_class, keyframe_rename_map
            )
            scoped_parts.append(scoped)

    return "\n".join(scoped_parts)


def _scope_selector_block(
    block: str, scope_class: str, rename_map: Dict[str, str]
) -> str:
    """Scope a regular CSS rule block: prepend scope_class to selector."""
    # Split into selector { declarations }
    brace_idx = block.find("{")
    if brace_idx < 0:
        return block

    selector = block[:brace_idx].strip()
    rest = block[brace_idx:]

    # Scope each comma-separated selector part
    parts = _split_selector_list(selector)
    scoped_parts = []
    for part in parts:
        part = part.strip()
        if part:
            scoped_parts.append(f"{scope_class} {part}")

    scoped_selector = ", ".join(scoped_parts)
    declarations = rest

    # Rename animation references in declarations
    if rename_map:
        declarations = _rename_animation_refs(declarations, rename_map)

    return f"{scoped_selector} {declarations}"


def _scope_at_rule_inner(
    block: str, scope_class: str, rename_map: Dict[str, str]
) -> str:
    """Scope the inner rules of an @media or @supports block."""
    # Find the opening brace of the at-rule
    first_brace = block.find("{")
    if first_brace < 0:
        return block

    at_rule_header = block[: first_brace + 1]

    # Find the matching closing brace
    last_brace = block.rfind("}")
    if last_brace <= first_brace:
        return block

    inner_css = block[first_brace + 1 : last_brace]

    # Recursively scope inner content
    inner_blocks = _split_top_level_blocks(inner_css)
    scoped_inner: List[str] = []
    for inner_type, inner_content in inner_blocks:
        if inner_type in ("media", "supports"):
            # Nested at-rule — recurse
            scoped_inner.append(
                _scope_at_rule_inner(inner_content, scope_class, rename_map)
            )
        elif inner_type in ("font-face", "keyframes"):
            scoped_inner.append(inner_content)
        elif inner_type == "root":
            rewritten = re.sub(
                r':root\s*\{', f'{scope_class} {{', inner_content, count=1
            )
            scoped_inner.append(rewritten)
        else:
            scoped_inner.append(
                _scope_selector_block(inner_content, scope_class, rename_map)
            )

    return f"{at_rule_header}\n{''.join(scoped_inner)}\n}}"


def _split_selector_list(selector: str) -> List[str]:
    """Split comma-separated selectors, respecting brackets/parens."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []

    for ch in selector:
        if ch in ("(", "["):
            depth += 1
            current.append(ch)
        elif ch in (")", "]"):
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current))

    return parts


def _extract_keyframe_name(block: str) -> Optional[str]:
    """Extract the name from @keyframes name { ... }."""
    m = re.match(r'@keyframes\s+(\S+)', block.strip())
    return m.group(1) if m else None


def _rename_keyframe(block: str, rename_map: Dict[str, str]) -> str:
    """Rename the keyframe definition name."""
    for old_name, new_name in rename_map.items():
        # Only rename in the @keyframes declaration
        block = re.sub(
            rf'@keyframes\s+{re.escape(old_name)}\b',
            f'@keyframes {new_name}',
            block,
            count=1,
        )
    return block


def _rename_animation_refs(declarations: str, rename_map: Dict[str, str]) -> str:
    """Rename animation name references in CSS declarations."""
    for old_name, new_name in rename_map.items():
        # animation-name: oldName
        declarations = re.sub(
            rf'(animation-name\s*:\s*){re.escape(old_name)}\b',
            rf'\g<1>{new_name}',
            declarations,
        )
        # animation shorthand: find the animation name token
        # The name is the token that's not a known CSS keyword or time value
        declarations = re.sub(
            rf'(animation\s*:[^;]*?)\b{re.escape(old_name)}\b',
            rf'\g<1>{new_name}',
            declarations,
        )
    return declarations


# ---------------------------------------------------------------------------
# Background image restoration (display boundary)
# ---------------------------------------------------------------------------

_BG_MARKER_RE = re.compile(
    r'<img\b([^>]*?)data-bg-image="true"([^>]*?)(?:/)?>',
    re.IGNORECASE,
)

_BG_RENDERED_CHECK = re.compile(r'data-bg-image-rendered="true"', re.IGNORECASE)


def restore_background_images(html: str) -> str:
    """Convert data-bg-image <img> markers to background-image divs.

    Call ONLY at the display boundary (UI rendering).
    The <img> marker form is the storage/transport representation.
    This function is idempotent — safe to call multiple times.
    """
    if not html or "data-bg-image" not in html:
        return html

    def _replace_marker(match: re.Match) -> str:
        full_tag = match.group(0)

        # Already rendered? Skip (idempotent)
        if _BG_RENDERED_CHECK.search(full_tag):
            return full_tag

        # Extract src, width, height
        src_match = re.search(r'src="([^"]*)"', full_tag)
        width_match = re.search(r'width="([^"]*)"', full_tag)
        height_match = re.search(r'height="([^"]*)"', full_tag)

        if not src_match:
            return full_tag  # No src — leave as-is

        src = src_match.group(1)

        # Re-validate URL before converting (defense-in-depth)
        is_safe, safe_url, _ = validate_image_url(src)
        if not is_safe:
            return full_tag  # Invalid URL — leave as marker

        # Build dimensions
        style_parts = [
            f"background-image: url({safe_url})",
            "background-size: cover",
            "background-position: center",
            "width: 100%",
        ]
        if height_match:
            style_parts.append(f"min-height: {height_match.group(1)}px")
        else:
            style_parts.append("min-height: 300px")

        style = "; ".join(style_parts)
        return (
            f'<div style="{style}" '
            f'data-bg-image-rendered="true"></div>'
        )

    return _BG_MARKER_RE.sub(_replace_marker, html)


# ---------------------------------------------------------------------------
# Internal helpers — HTML image parser
# ---------------------------------------------------------------------------


class _ImageHTMLParser(HTMLParser):
    """Extract images from HTML with dimensions and srcset."""

    def __init__(self, page_url: str = "") -> None:
        super().__init__(convert_charrefs=False)
        self.images: List[PageImage] = []
        self._page_url = page_url
        self._in_picture = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag_lower = tag.lower()

        if tag_lower == "picture":
            self._in_picture = True

        if tag_lower == "img":
            self._handle_img(attrs)
        elif tag_lower == "source" and self._in_picture:
            self._handle_source(attrs)
        elif tag_lower in ("div", "section", "span"):
            self._handle_bg_image(tag_lower, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "picture":
            self._in_picture = False

    def _handle_img(self, attrs: list) -> None:
        attr_dict = dict(attrs)
        src = attr_dict.get("src", "") or attr_dict.get("data-src", "")
        if not src:
            return

        # Resolve relative URLs
        if self._page_url and not src.startswith(('http://', 'https://', 'data:')):
            src = urljoin(self._page_url, src)

        width = _parse_int(attr_dict.get("width"))
        height = _parse_int(attr_dict.get("height"))

        img = PageImage(
            url=src,
            alt=attr_dict.get("alt", ""),
            width=width,
            height=height,
            srcset=attr_dict.get("srcset"),
            is_background=False,
            is_icon=_is_icon(width, height, attr_dict.get("alt", "")),
        )
        self.images.append(img)

    def _handle_source(self, attrs: list) -> None:
        attr_dict = dict(attrs)
        srcset = attr_dict.get("srcset", "")
        if not srcset:
            return
        # Extract first URL from srcset
        first_url = srcset.split(",")[0].strip().split()[0]
        if self._page_url and not first_url.startswith(
            ('http://', 'https://', 'data:')
        ):
            first_url = urljoin(self._page_url, first_url)

        img = PageImage(
            url=first_url,
            alt="",
            srcset=srcset,
            is_background=False,
        )
        self.images.append(img)

    def _handle_bg_image(self, tag: str, attrs: list) -> None:
        attr_dict = dict(attrs)
        style = attr_dict.get("style", "")
        if not style:
            return

        # Extract background-image: url(...)
        bg_match = re.search(
            r"background(?:-image)?\s*:[^;]*url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)",
            style,
        )
        if not bg_match:
            return

        url = bg_match.group(1)
        if self._page_url and not url.startswith(('http://', 'https://', 'data:')):
            url = urljoin(self._page_url, url)

        img = PageImage(
            url=url,
            alt="background",
            is_background=True,
        )
        self.images.append(img)


# ---------------------------------------------------------------------------
# Internal helpers — CSS extraction
# ---------------------------------------------------------------------------


def _split_top_level_blocks(css: str) -> List[Tuple[str, str]]:
    """Split CSS into top-level blocks using brace-depth tracking.

    Returns list of (block_type, block_content) tuples.
    block_type is one of: 'font-face', 'keyframes', 'media', 'supports', 'root', 'rule'
    """
    results: List[Tuple[str, str]] = []
    i = 0
    n = len(css)

    while i < n:
        # Skip whitespace
        while i < n and css[i] in (' ', '\t', '\n', '\r'):
            i += 1
        if i >= n:
            break

        # Check for at-rules
        if css[i] == '@':
            # Find the at-rule type
            at_start = i
            j = i + 1
            while j < n and css[j] not in (' ', '\t', '\n', '{'):
                j += 1
            at_rule = css[i:j].lower()

            # Find the complete block (matching braces)
            brace_start = css.find('{', j)
            if brace_start < 0:
                # Malformed — skip to end
                break

            block_end = _find_matching_brace(css, brace_start)
            if block_end < 0:
                break

            block = css[at_start : block_end + 1]

            if at_rule == "@font-face":
                results.append(("font-face", block))
            elif at_rule == "@keyframes" or at_rule == "@-webkit-keyframes":
                results.append(("keyframes", block))
            elif at_rule == "@media":
                results.append(("media", block))
            elif at_rule == "@supports":
                results.append(("supports", block))
            else:
                # Unknown at-rule — skip
                pass

            i = block_end + 1

        elif css[i] == '/' and i + 1 < n and css[i + 1] == '*':
            # Skip CSS comments
            end = css.find('*/', i + 2)
            i = end + 2 if end >= 0 else n

        else:
            # Regular rule or :root
            brace_start = css.find('{', i)
            if brace_start < 0:
                break

            selector = css[i:brace_start].strip()
            block_end = _find_matching_brace(css, brace_start)
            if block_end < 0:
                break

            block = css[i : block_end + 1]

            if selector.startswith(':root'):
                results.append(("root", block))
            elif selector:
                results.append(("rule", block))

            i = block_end + 1

    return results


def _find_matching_brace(css: str, open_pos: int) -> int:
    """Find the matching closing brace for an opening brace."""
    depth = 0
    i = open_pos
    n = len(css)
    while i < n:
        if css[i] == '{':
            depth += 1
        elif css[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        elif css[i] == '/' and i + 1 < n and css[i + 1] == '*':
            # Skip comments
            end = css.find('*/', i + 2)
            i = end + 1 if end >= 0 else n - 1
        i += 1
    return -1


def _clean_font_face(block: str) -> str:
    """Clean @font-face: keep font-family/font-weight/font-display, strip src."""
    # Remove src: url(...) lines for safety
    cleaned = re.sub(r'src\s*:[^;]+;', '/* src stripped */', block)
    return cleaned


def _extract_stylesheet_urls(html: str, page_url: str) -> List[str]:
    """Extract <link rel="stylesheet"> href URLs from HTML."""
    urls: List[str] = []
    for match in re.finditer(
        r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>', html, re.IGNORECASE
    ):
        href_match = re.search(r'href=["\']([^"\']+)["\']', match.group(0))
        if href_match:
            href = href_match.group(1)
            if page_url and not href.startswith(('http://', 'https://')):
                href = urljoin(page_url, href)
            urls.append(href)
    return urls


def _is_first_party(css_hostname: str, page_hostname: str) -> bool:
    """Check if CSS hostname is first-party (same domain or subdomain)."""
    if not css_hostname or not page_hostname:
        return False

    css_hostname = css_hostname.lower()
    page_hostname = page_hostname.lower()

    # Exact match
    if css_hostname == page_hostname:
        return True

    # Subdomain match
    if css_hostname.endswith('.' + page_hostname):
        return True
    if page_hostname.endswith('.' + css_hostname):
        return True

    # Skip known CDNs
    if css_hostname in _CDN_DOMAINS:
        return False

    return False


def _is_safe_css_url(url: str) -> bool:
    """Validate URL is safe to fetch server-side. Prevents SSRF."""
    parsed = urlparse(url)
    # Must be HTTPS
    if parsed.scheme != 'https':
        return False
    host = parsed.hostname
    if not host:
        return False
    # Block localhost and loopback
    if host in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        return False
    # Block private/internal IP ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass  # Not an IP — it's a hostname, which is fine
    # Block common internal hostnames
    if host.endswith(('.local', '.internal', '.corp', '.lan')):
        return False
    return True


def _safe_fetch_css(
    url: str, page_hostname: str, max_redirects: int = 3
) -> Optional[str]:
    """Fetch CSS with per-hop SSRF + first-party protection."""
    import httpx

    for hop in range(max_redirects + 1):
        if not _is_safe_css_url(url):
            return None

        parsed = urlparse(url)
        if not _is_first_party(parsed.hostname, page_hostname):
            logger.warning(
                f"CSS redirect left first-party domain: {parsed.hostname}"
            )
            return None

        # DNS resolution check BEFORE connecting
        try:
            port = parsed.port or 443
            resolved_ips = socket.getaddrinfo(
                parsed.hostname, port, type=socket.SOCK_STREAM
            )
            for family, _, _, _, sockaddr in resolved_ips:
                ip = ipaddress.ip_address(sockaddr[0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                ):
                    logger.warning(
                        f"CSS fetch blocked: {parsed.hostname} "
                        f"resolves to private IP {ip}"
                    )
                    return None
        except socket.gaierror:
            return None

        try:
            with httpx.stream(
                "GET", url, follow_redirects=False, timeout=5.0
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if not location:
                        return None
                    url = urljoin(str(resp.url), location)
                    continue

                if resp.status_code != 200:
                    return None

                # Check content-length header (early reject)
                content_length = resp.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_CSS_RESPONSE_BYTES:
                            logger.warning(
                                f"CSS response too large "
                                f"({content_length} bytes), skipping"
                            )
                            return None
                    except ValueError:
                        pass

                # Stream-read with hard byte cap
                chunks: List[bytes] = []
                total = 0
                for chunk in resp.iter_bytes(chunk_size=8192):
                    total += len(chunk)
                    if total > MAX_CSS_RESPONSE_BYTES:
                        remaining = MAX_CSS_RESPONSE_BYTES - (total - len(chunk))
                        chunks.append(chunk[:remaining])
                        logger.warning(
                            f"CSS stream exceeded {MAX_CSS_RESPONSE_BYTES} "
                            f"bytes, truncating"
                        )
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except httpx.TimeoutException:
            logger.debug(f"CSS fetch timeout: {url}")
            return None
        except Exception as e:
            logger.debug(f"CSS fetch error: {e}")
            return None

    return None  # Exhausted redirect hops


# ---------------------------------------------------------------------------
# Internal helpers — image proximity mapping
# ---------------------------------------------------------------------------


def _extract_section_headings(
    sections: list,
) -> Dict[str, List[str]]:
    """Extract heading texts from each section's markdown."""
    heading_re = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)
    result: Dict[str, List[str]] = {}
    for section in sections:
        headings = heading_re.findall(section.markdown)
        result[section.section_id] = [h.strip().lower() for h in headings]
    return result


def _extract_html_heading_positions(html: str) -> List[Tuple[int, str]]:
    """Extract heading positions (char offset, text) from HTML."""
    results: List[Tuple[int, str]] = []
    for match in re.finditer(
        r'<h[1-6][^>]*>(.*?)</h[1-6]>', html, re.IGNORECASE | re.DOTALL
    ):
        text = re.sub(r'<[^>]+>', '', match.group(1)).strip().lower()
        if text:
            results.append((match.start(), text))
    return results


def _proximity_map_image(
    img: PageImage,
    html_headings: List[Tuple[int, str]],
    section_headings: Dict[str, List[str]],
) -> Optional[str]:
    """Map an HTML-only image to a section using text proximity.

    Finds the nearest heading to the image's position in HTML,
    then matches that heading to a section.
    Returns section_id or None if no confident match.
    """
    if not html_headings or not section_headings:
        return None

    # We don't have the img's exact position in HTML (would need parser offset),
    # so fall back to alt-text matching against section headings
    alt_lower = img.alt.lower() if img.alt else ""
    if not alt_lower:
        return None

    best_score = 0.0
    best_section = None

    for sec_id, headings in section_headings.items():
        for heading in headings:
            score = _word_jaccard(alt_lower, heading)
            if score > best_score:
                best_score = score
                best_section = sec_id

    return best_section if best_score > 0.5 else None


def _word_jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union else 0.0


def _extract_heading_texts(html: str, max_headings: int = 5) -> List[str]:
    """Extract heading texts from HTML."""
    results: List[str] = []
    for match in re.finditer(
        r'<h[1-6][^>]*>(.*?)</h[1-6]>', html, re.IGNORECASE | re.DOTALL
    ):
        text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if text:
            results.append(text)
            if len(results) >= max_headings:
                break
    return results


def _extract_heading_texts_from_md(markdown: str, max_headings: int = 5) -> List[str]:
    """Extract heading texts from markdown."""
    results: List[str] = []
    for match in re.finditer(r'^#{1,6}\s+(.+)$', markdown, re.MULTILINE):
        text = match.group(1).strip()
        if text:
            results.append(text)
            if len(results) >= max_headings:
                break
    return results


def _extract_title(html: str) -> Optional[str]:
    """Extract <title> text from HTML."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_first_heading(markdown: str) -> Optional[str]:
    """Extract first heading from markdown."""
    match = re.search(r'^#{1,6}\s+(.+)$', markdown, re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_first_n_image_urls(html: str, n: int) -> List[str]:
    """Extract first N image URLs from HTML."""
    results: List[str] = []
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        url = match.group(1).strip()
        if url and not url.startswith('data:'):
            results.append(url)
            if len(results) >= n:
                break
    return results


def _extract_first_n_image_urls_from_md(markdown: str, n: int) -> List[str]:
    """Extract first N image URLs from markdown."""
    results: List[str] = []
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        url = match.group(2).strip()
        if url and not url.startswith('data:'):
            results.append(url)
            if len(results) >= n:
                break
    return results


# ---------------------------------------------------------------------------
# Dual-scrape consistency check
# ---------------------------------------------------------------------------


def check_scrape_consistency(page_html: str, markdown: str, scrape_url: str) -> bool:
    """Return True if HTML and markdown appear to come from the same page state.

    Uses multi-signal checking: requires at least 2 of 3 signals to match.
    """
    signals = 0
    total_checks = 0

    # Signal 1: Title overlap
    html_title = _extract_title(page_html)
    md_heading = _extract_first_heading(markdown)
    if html_title and md_heading:
        total_checks += 1
        if _word_jaccard(html_title.lower(), md_heading.lower()) >= 0.4:
            signals += 1

    # Signal 2: Top image overlap
    html_images = _extract_first_n_image_urls(page_html, 5)
    md_images = _extract_first_n_image_urls_from_md(markdown, 5)
    if html_images and md_images:
        total_checks += 1
        overlap = len(set(html_images) & set(md_images))
        if overlap >= 1:
            signals += 1

    # Signal 3: Heading tokens overlap
    html_headings = _extract_heading_texts(page_html, max_headings=5)
    md_headings = _extract_heading_texts_from_md(markdown, max_headings=5)
    if html_headings and md_headings:
        total_checks += 1
        html_tokens = set(" ".join(html_headings).lower().split())
        md_tokens = set(" ".join(md_headings).lower().split())
        if html_tokens and md_tokens:
            token_overlap = len(html_tokens & md_tokens) / max(
                len(html_tokens), len(md_tokens)
            )
            if token_overlap >= 0.5:
                signals += 1

    # Zero checkable signals with non-empty markdown = suspicious HTML
    if total_checks == 0:
        if markdown and markdown.strip():
            logger.warning(
                "No consistency signals available despite non-empty markdown"
            )
            return False
        else:
            return True

    required = min(2, total_checks)
    return signals >= required


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Parse an integer from a string, returning None on failure."""
    if not value:
        return None
    try:
        # Handle "100px" or "100%" by stripping non-digits
        digits = re.match(r'(\d+)', value.strip())
        return int(digits.group(1)) if digits else None
    except (ValueError, AttributeError):
        return None


def _is_icon(
    width: Optional[int], height: Optional[int], alt: str
) -> bool:
    """Detect if an image is likely an icon based on dimensions or alt text."""
    if width and height and max(width, height) <= 80:
        return True
    alt_lower = alt.lower() if alt else ""
    icon_keywords = ('icon', 'logo', 'favicon', 'badge', 'arrow', 'chevron')
    return any(kw in alt_lower for kw in icon_keywords)


def _parse_srcset(srcset_value: str) -> List[Tuple[str, str]]:
    """Parse srcset attribute value into (url, descriptor) pairs.

    Follows HTML spec: srcset entries are comma-separated, but URLs
    themselves never contain unescaped commas (per URL spec). The
    descriptor is the optional width (e.g., '300w') or pixel density
    (e.g., '2x') that follows the URL.

    Returns list of (url, descriptor) tuples. descriptor may be "".
    """
    results: List[Tuple[str, str]] = []
    i = 0
    s = srcset_value.strip()
    n = len(s)

    while i < n:
        # Skip leading whitespace and commas
        while i < n and s[i] in (' ', '\t', '\n', ','):
            i += 1
        if i >= n:
            break
        # Collect URL (run of non-whitespace)
        url_start = i
        while i < n and s[i] not in (' ', '\t', '\n', ','):
            i += 1
        url = s[url_start:i]
        # Skip whitespace between URL and descriptor
        while i < n and s[i] in (' ', '\t', '\n'):
            i += 1
        # Collect descriptor (e.g., "300w", "2x") — ends at comma or end
        descriptor = ""
        if i < n and s[i] != ',':
            desc_start = i
            while i < n and s[i] != ',':
                i += 1
            descriptor = s[desc_start:i].strip()
        if url:
            results.append((url, descriptor))

    return results


def _extract_head_section(page_html: str) -> Optional[str]:
    """Extract <head>...</head> from HTML. Returns None if not found."""
    head_start = page_html.lower().find('<head')
    if head_start < 0:
        return None
    head_end = page_html.lower().find('</head>', head_start)
    if head_end < 0:
        return None
    return page_html[head_start : head_end + len('</head>')]
