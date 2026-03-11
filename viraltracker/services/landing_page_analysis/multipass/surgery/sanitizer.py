"""Pass S0: Sanitize & Resolve CSS (Deterministic).

Cleans raw FireCrawl HTML into a self-contained, renderable document.
Strips scripts, tracking, event handlers; resolves lazy images;
absolutizes relative URLs; strips dangerous SVG elements.

Zero LLM calls.
"""

import logging
import re
from html.parser import HTMLParser
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Max output size (10MB)
_MAX_SANITIZED_SIZE = 10 * 1024 * 1024

# Minimum visible text length to consider surgery viable
_MIN_VISIBLE_TEXT = 500

# Tags to strip entirely (including contents)
_STRIP_TAGS_WITH_CONTENT = frozenset([
    "script", "noscript", "template", "audio",
])

# Regex to convert <video> elements to poster/placeholder images.
# Shopify/Replo themes often use autoplay muted loop videos as hero visuals.
# Stripping them leaves empty containers; convert to <img> instead.
_VIDEO_RE = re.compile(
    r'<video\b([^>]*)>.*?</video\s*>|<video\b([^>]*)/\s*>',
    re.DOTALL | re.IGNORECASE,
)

# Regex to convert <iframe> elements to placeholder images.
# YouTube/Vimeo embeds are common on landing pages; stripping them entirely
# loses semantic information. Convert to thumbnail/placeholder instead.
_IFRAME_RE = re.compile(
    r'<iframe\b([^>]*)>.*?</iframe\s*>|<iframe\b([^>]*)/\s*>',
    re.DOTALL | re.IGNORECASE,
)

# Extract YouTube video ID from embed URL
_YOUTUBE_ID_RE = re.compile(
    r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    re.IGNORECASE,
)

# Link rel values to keep (stylesheets only)
_KEEP_LINK_RELS = frozenset(["stylesheet"])

# Popup/overlay class and id patterns
_POPUP_PATTERNS = re.compile(
    r'\b(popup|modal|overlay|cookie[-_]?banner|cookie[-_]?consent|'
    r'gdpr|newsletter[-_]?popup|exit[-_]?intent|lightbox|'
    r'shopify-pc__banner|consent[-_]?tracking|privacy[-_]?banner)\b',
    re.IGNORECASE,
)

# Navigation chrome: Shopify section IDs containing footer/mega-menu.
# We keep header sections for visual fidelity (announcement bar, nav).
# Safety net for elements that survive Playwright DOM removal (e.g. Firecrawl
# fallback path, or JS-injected elements after capture).
_SHOPIFY_CHROME_ID_PATTERN = re.compile(
    r'shopify-section[-_].*?(footer|mega[-_]?menu)',
    re.IGNORECASE,
)

# Anti-scraping overlay signature: extreme z-index + transparent text color
_ANTI_SCRAPE_STYLE_RE = re.compile(
    r'z-index:\s*\d{8,}.*?color:\s*transparent',
    re.IGNORECASE | re.DOTALL,
)

# Inline event handler attributes
_EVENT_HANDLER_RE = re.compile(
    r'\s+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
    re.IGNORECASE,
)

# Lazy-load attribute mappings
_LAZY_ATTRS = {
    "data-src": "src",
    "data-srcset": "srcset",
    "data-lazy-src": "src",
    "data-original": "src",
    "data-bg": "src",
    "data-image": "src",
    "data-thumb": "src",
    "data-full-src": "src",
    "data-hi-res-src": "src",
}

# Known tracker domains (1x1 pixel images)
_TRACKER_DOMAINS = frozenset([
    "www.facebook.com", "connect.facebook.net",
    "www.google-analytics.com", "google-analytics.com",
    "googleads.g.doubleclick.net", "px.ads.linkedin.com",
    "bat.bing.com", "ct.pinterest.com",
    "analytics.twitter.com", "t.co",
    "snap.licdn.com", "tr.snapchat.com",
])

# Dangerous SVG elements to strip from within <svg> subtrees
_DANGEROUS_SVG_ELEMENTS = frozenset([
    "script", "foreignObject", "foreignobject", "use",
    "animate", "animateMotion", "animatemotion",
    "animateTransform", "animatetransform", "set",
])

# Shopify custom element wrapper
_SHOPIFY_SECTION_RE = re.compile(
    r'<shopify-section[^>]*>(.*?)</shopify-section>',
    re.DOTALL | re.IGNORECASE,
)

# Form action attribute
_FORM_ACTION_RE = re.compile(
    r'(<form\b[^>]*?)\s+action\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
    re.IGNORECASE,
)

# Submit input to button conversion
_SUBMIT_INPUT_RE = re.compile(
    r'<input\s+([^>]*?)type\s*=\s*["\']submit["\']([^>]*?)/?\s*>',
    re.IGNORECASE,
)


class HTMLSanitizer:
    """Pass S0: Clean raw HTML into a self-contained, renderable document."""

    def sanitize(
        self,
        raw_html: str,
        page_url: str = "",
        detected_overlays: Optional[list] = None,
    ) -> Tuple[str, dict]:
        """Sanitize raw HTML for the surgery pipeline.

        Args:
            raw_html: Full page HTML from FireCrawl.
            page_url: Base URL for resolving relative URLs.
            detected_overlays: Optional overlay dicts from Phase 0.

        Returns:
            (sanitized_html, stats_dict) where stats contains counts
            of removed elements and visible text length.
        """
        if not raw_html or not raw_html.strip():
            return "", {"visible_text_len": 0, "viable": False}

        html = raw_html
        stats = {
            "input_size": len(html),
            "scripts_removed": 0,
            "trackers_removed": 0,
            "popups_removed": 0,
            "event_handlers_removed": 0,
            "lazy_images_resolved": 0,
            "urls_absolutized": 0,
            "svg_elements_stripped": 0,
        }

        # 0. Unwrap Alpine.js/carousel <template> tags BEFORE stripping.
        # Alpine x-if/x-for and Swiper lazy templates contain product
        # images that would be destroyed by _strip_tags_with_content.
        # Unwrap = keep children, remove the <template> wrapper.
        html, unwrapped = self._unwrap_content_templates(html)
        stats["templates_unwrapped"] = unwrapped

        # 1. Strip tags with content (script, noscript, template, audio)
        # Remaining <template> tags (framework scaffolding, not content)
        # are stripped here.
        html, count = self._strip_tags_with_content(html)
        stats["scripts_removed"] = count

        # 1b. Convert <video> elements to poster/placeholder images
        html, vid_count = self._convert_videos_to_posters(html)
        stats["videos_converted"] = vid_count

        # 1c. Convert <iframe> embeds to thumbnail/placeholder images
        html, iframe_count = self._convert_iframes_to_placeholders(html)
        stats["iframes_converted"] = iframe_count

        # 2. Strip non-stylesheet <link> tags
        html = self._strip_non_stylesheet_links(html)

        # 3. Remove tracking pixels (1x1 images, known tracker domains)
        html, count = self._strip_tracking_pixels(html)
        stats["trackers_removed"] = count

        # 4. Remove popup/overlay elements
        html, count = self._strip_popup_elements(html)
        stats["popups_removed"] = count

        # 4b. Also use PopupFilter for detected overlays
        if detected_overlays:
            from ..popup_filter import PopupFilter
            html = PopupFilter().filter(html, detected_overlays)

        # 4c. Strip navigation chrome (header, footer, mega-menu, anti-scraping overlays).
        # Safety net for elements that survived Playwright capture removal.
        html, count = self._strip_chrome_elements(html)
        stats["chrome_removed"] = count

        # 5. Resolve lazy-loaded images
        html, count = self._resolve_lazy_images(html)
        stats["lazy_images_resolved"] = count

        # 5b. Populate empty src from srcset (Shopify pattern)
        html, count = self._populate_src_from_srcset(html)
        stats["srcset_populated"] = count

        # 6. Remove inline event handlers
        html, count = self._strip_event_handlers(html)
        stats["event_handlers_removed"] = count

        # 7. Neuter forms
        html = self._neuter_forms(html)

        # 8. Unwrap Shopify custom elements
        html = self._unwrap_shopify_sections(html)

        # 9. Strip dangerous SVG elements
        html, count = self._strip_dangerous_svg(html)
        stats["svg_elements_stripped"] = count

        # 10. Absolutize all relative URLs
        if page_url:
            html, count = self._absolutize_urls(html, page_url)
            stats["urls_absolutized"] = count

        # 11. Fix JS-set broken inline styles (empty aspect-ratio, height:0px)
        html, count = self._fix_js_inline_styles(html)
        stats["js_styles_fixed"] = count

        # 12. Inject Swiper/carousel fallback CSS so renders are
        # self-contained even if the external swiper-bundle.css fails to load.
        # height:auto!important overrides swiper-bundle's height:100% on
        # .swiper-wrapper and .swiper-slide, which without JS causes
        # containers to inflate to viewport height (800px gap bug).
        if ".swiper" in html or "swiper-wrapper" in html:
            swiper_fallback = (
                '<style data-sanitizer="swiper-fallback">'
                '.swiper{overflow:hidden;position:relative}'
                '.swiper-wrapper{display:flex;box-sizing:content-box;'
                'transform:translate3d(0,0,0);height:auto!important}'
                '.swiper-slide{flex-shrink:0;box-sizing:border-box;'
                'max-width:100%;height:auto!important}'
                '</style>'
            )
            html = html.replace('</head>', swiper_fallback + '</head>', 1)

        # 13. Size guard
        if len(html) > _MAX_SANITIZED_SIZE:
            logger.warning(
                f"Sanitized HTML exceeds {_MAX_SANITIZED_SIZE} bytes "
                f"({len(html)}), truncating from bottom"
            )
            html = html[:_MAX_SANITIZED_SIZE]

        # Check viability
        visible_text = self._extract_visible_text(html)
        stats["visible_text_len"] = len(visible_text)
        stats["viable"] = len(visible_text) >= _MIN_VISIBLE_TEXT
        stats["output_size"] = len(html)

        return html, stats

    # ------------------------------------------------------------------
    # Stripping helpers
    # ------------------------------------------------------------------

    def _strip_tags_with_content(self, html: str) -> Tuple[str, int]:
        """Strip tags and their content for script, noscript, etc."""
        count = 0
        for tag in _STRIP_TAGS_WITH_CONTENT:
            pattern = re.compile(
                rf'<{tag}\b[^>]*>.*?</{tag}\s*>',
                re.DOTALL | re.IGNORECASE,
            )
            matches = pattern.findall(html)
            count += len(matches)
            html = pattern.sub("", html)
        return html, count

    def _convert_videos_to_posters(self, html: str) -> Tuple[str, int]:
        """Convert <video> elements to poster/placeholder images.

        Shopify/Replo themes use autoplay muted loop videos as hero visuals.
        Stripping them entirely leaves empty containers and hurts visual fidelity.
        Instead, convert to <img> using the poster attribute when available, or
        a styled placeholder div for videos without poster.
        """
        count = 0

        def _replace_video(match: re.Match) -> str:
            nonlocal count
            attrs = match.group(1) or match.group(2) or ""

            # Extract poster attribute
            poster_match = re.search(
                r'poster\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
            )

            # Extract style for dimensions
            style_match = re.search(
                r'style\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
            )
            style = style_match.group(1) if style_match else ""

            # Extract explicit width/height
            w_match = re.search(
                r'width\s*=\s*["\']?(\d+)', attrs, re.IGNORECASE
            )
            h_match = re.search(
                r'height\s*=\s*["\']?(\d+)', attrs, re.IGNORECASE
            )

            count += 1

            if poster_match:
                poster_url = poster_match.group(1)
                img_style = style if style else "width:100%;height:auto"
                w_attr = f' width="{w_match.group(1)}"' if w_match else ""
                h_attr = f' height="{h_match.group(1)}"' if h_match else ""
                return (
                    f'<img src="{poster_url}" style="{img_style}" '
                    f'data-was-video="true"{w_attr}{h_attr} loading="eager">'
                )

            # No poster — check for src to create a placeholder
            src_match = re.search(
                r'(?<!\w)src\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
            )
            # Use a placeholder div that preserves layout
            placeholder_style = style if style else "width:100%;aspect-ratio:16/9"
            if "background" not in placeholder_style:
                placeholder_style += ";background:#e5e7eb"
            src_note = ""
            if src_match:
                src_note = f' data-video-src="{src_match.group(1)}"'
            return (
                f'<div data-was-video="true"{src_note} '
                f'style="{placeholder_style}"></div>'
            )

        html = _VIDEO_RE.sub(_replace_video, html)
        return html, count

    def _convert_iframes_to_placeholders(self, html: str) -> Tuple[str, int]:
        """Convert <iframe> embeds to thumbnail/placeholder images.

        YouTube/Vimeo embeds are common on landing pages. Stripping them
        entirely loses semantic info about embedded content. Convert to
        a thumbnail <img> (for YouTube) or labeled placeholder.
        """
        count = 0

        def _replace_iframe(match: re.Match) -> str:
            nonlocal count
            attrs = match.group(1) or match.group(2) or ""

            # Extract src
            src_match = re.search(
                r'(?<!\w)src\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
            )
            src_url = src_match.group(1) if src_match else ""

            # Extract title
            title_match = re.search(
                r'title\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
            )
            title = title_match.group(1) if title_match else ""

            count += 1

            # YouTube embed — fill parent with thumbnail image.
            # The iframe's parent container already defines the space
            # (aspect-ratio via CSS), so we inherit sizing, not force our own.
            yt_match = _YOUTUBE_ID_RE.search(src_url)
            if yt_match:
                video_id = yt_match.group(1)
                thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                alt = title if title else f"YouTube video {video_id}"
                return (
                    f'<img src="{thumb_url}" alt="{alt}" '
                    f'data-was-iframe="youtube" data-video-id="{video_id}" '
                    f'style="width:100%;height:100%;object-fit:cover" '
                    f'loading="eager">'
                )

            # Other iframes — compact placeholder (avoid height:100%
            # which can inherit a huge parent height and create a
            # large black rectangle)
            label = title if title else "Embedded content"
            data_src = f' data-iframe-src="{src_url}"' if src_url else ""
            return (
                f'<div data-was-iframe="true"{data_src} '
                f'style="width:100%;min-height:60px;max-height:200px;'
                f'background:#1a1a1a;'
                f'display:flex;align-items:center;justify-content:center;'
                f'color:#888;font-size:14px">{label}</div>'
            )

        html = _IFRAME_RE.sub(_replace_iframe, html)
        return html, count

    def _strip_non_stylesheet_links(self, html: str) -> str:
        """Strip <link> tags that aren't stylesheets."""
        def _filter_link(match: re.Match) -> str:
            tag = match.group(0)
            rel_match = re.search(r'rel\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if rel_match:
                rel = rel_match.group(1).lower().strip()
                if rel in _KEEP_LINK_RELS:
                    return tag
            return ""

        return re.sub(
            r'<link\b[^>]*/?\s*>',
            _filter_link,
            html,
            flags=re.IGNORECASE,
        )

    def _strip_tracking_pixels(self, html: str) -> Tuple[str, int]:
        """Remove 1x1 tracking pixels and known tracker domain images."""
        count = 0

        def _check_img(match: re.Match) -> str:
            nonlocal count
            tag = match.group(0)
            # Check for 1x1 dimensions
            w_match = re.search(r'width\s*=\s*["\']?1["\']?', tag, re.IGNORECASE)
            h_match = re.search(r'height\s*=\s*["\']?1["\']?', tag, re.IGNORECASE)
            if w_match and h_match:
                count += 1
                return ""
            # Check for tracker domain
            src_match = re.search(r'src\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if src_match:
                try:
                    domain = urlparse(src_match.group(1)).hostname or ""
                    if domain in _TRACKER_DOMAINS:
                        count += 1
                        return ""
                except Exception:
                    pass
            return tag

        html = re.sub(r'<img\b[^>]*/?\s*>', _check_img, html, flags=re.IGNORECASE)
        return html, count

    def _strip_popup_elements(self, html: str) -> Tuple[str, int]:
        """Strip elements whose class or id matches popup/overlay patterns."""
        count = 0

        def _check_element(match: re.Match) -> str:
            nonlocal count
            tag_content = match.group(0)
            # Extract class and id values
            class_match = re.search(
                r'class\s*=\s*["\']([^"\']*)["\']', tag_content, re.IGNORECASE
            )
            id_match = re.search(
                r'id\s*=\s*["\']([^"\']*)["\']', tag_content, re.IGNORECASE
            )
            class_val = class_match.group(1) if class_match else ""
            id_val = id_match.group(1) if id_match else ""

            if _POPUP_PATTERNS.search(class_val) or _POPUP_PATTERNS.search(id_val):
                # Find the closing tag
                tag_name = match.group(1)
                # For self-closing or simple match, just remove the opening tag
                # We need to find the full element including closing tag
                count += 1
                return ""
            return tag_content

        # Match div/section/aside with popup class/id patterns
        # This is a simplified approach — find opening tags and mark for removal
        result = html
        for tag in ("div", "section", "aside", "span"):
            pattern = re.compile(
                rf'<{tag}\b([^>]*)>',
                re.IGNORECASE,
            )
            removals: List[Tuple[int, int]] = []
            for m in pattern.finditer(result):
                attrs = m.group(1)
                class_match = re.search(
                    r'class\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
                )
                id_match = re.search(
                    r'id\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
                )
                class_val = class_match.group(1) if class_match else ""
                id_val = id_match.group(1) if id_match else ""

                if _POPUP_PATTERNS.search(class_val) or _POPUP_PATTERNS.search(id_val):
                    end = self._find_matching_close(result, tag, m.end())
                    if end > m.start():
                        removals.append((m.start(), end))

            # Apply removals in reverse to preserve offsets
            for start, end in reversed(removals):
                result = result[:start] + result[end:]
                count += 1

        return result, count

    def _find_matching_close(self, html: str, tag: str, start: int) -> int:
        """Find the position after the matching closing tag."""
        depth = 1
        pos = start
        open_pattern = re.compile(
            rf'<{tag}\b[^>]*>', re.IGNORECASE
        )
        close_pattern = re.compile(
            rf'</{tag}\s*>', re.IGNORECASE
        )
        while pos < len(html) and depth > 0:
            next_open = open_pattern.search(html, pos)
            next_close = close_pattern.search(html, pos)

            if next_close is None:
                return len(html)

            if next_open and next_open.start() < next_close.start():
                depth += 1
                pos = next_open.end()
            else:
                depth -= 1
                pos = next_close.end()

        return pos

    def _strip_chrome_elements(self, html: str) -> Tuple[str, int]:
        """Strip navigation chrome and anti-scraping overlays from HTML.

        Catches Shopify theme elements that survived Playwright DOM removal:
        - Sections with IDs matching header/footer/mega-menu/announcement
        - Anti-scraping overlay divs (extreme z-index + transparent text)
        - Bare <header>, <nav>, <footer> semantic tags

        Uses the same _find_matching_close() pattern as _strip_popup_elements().
        """
        count = 0
        result = html

        # Pass 1: Remove elements by Shopify section ID pattern
        for tag in ("div", "section"):
            pattern = re.compile(
                rf'<{tag}\b([^>]*)>',
                re.IGNORECASE,
            )
            removals: List[Tuple[int, int]] = []
            for m in pattern.finditer(result):
                attrs = m.group(1)
                id_match = re.search(
                    r'id\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
                )
                id_val = id_match.group(1) if id_match else ""

                # Shopify chrome section IDs
                if id_val and _SHOPIFY_CHROME_ID_PATTERN.search(id_val):
                    end = self._find_matching_close(result, tag, m.end())
                    if end > m.start():
                        removals.append((m.start(), end))
                    continue

                # Anti-scraping overlay (inline style with huge z-index + transparent)
                style_match = re.search(
                    r'style\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE
                )
                if style_match and _ANTI_SCRAPE_STYLE_RE.search(style_match.group(1)):
                    end = self._find_matching_close(result, tag, m.end())
                    if end > m.start():
                        removals.append((m.start(), end))

            for start, end in reversed(removals):
                result = result[:start] + result[end:]
                count += 1

        # Pass 2: Remove bare semantic chrome tags (<footer> only).
        # We keep <header> and <nav> for visual fidelity (announcement bar,
        # navigation). Footer is still removed as it's rarely content.
        for tag in ("footer",):
            pattern = re.compile(rf'<{tag}\b[^>]*>', re.IGNORECASE)
            removals = []
            for m in pattern.finditer(result):
                end = self._find_matching_close(result, tag, m.end())
                if end > m.start():
                    removals.append((m.start(), end))
            for start, end in reversed(removals):
                result = result[:start] + result[end:]
                count += 1

        if count:
            logger.info(f"S0: stripped {count} navigation chrome element(s)")

        return result, count

    def _resolve_lazy_images(self, html: str) -> Tuple[str, int]:
        """Resolve lazy-loaded images: data-src → src, etc."""
        count = 0

        def _fix_img(match: re.Match) -> str:
            nonlocal count
            tag = match.group(0)
            modified = False
            for data_attr, real_attr in _LAZY_ATTRS.items():
                data_pattern = re.compile(
                    rf'{data_attr}\s*=\s*["\']([^"\']+)["\']',
                    re.IGNORECASE,
                )
                data_match = data_pattern.search(tag)
                if data_match:
                    value = data_match.group(1)
                    # Check if real attr is empty or placeholder
                    # Use negative lookbehind to avoid matching data-src when looking for src
                    real_pattern = re.compile(
                        rf'(?<![a-zA-Z-]){real_attr}\s*=\s*["\']([^"\']*)["\']',
                        re.IGNORECASE,
                    )
                    real_match = real_pattern.search(tag)
                    if real_match:
                        existing = real_match.group(1)
                        # Replace if empty, data URI placeholder, or transparent pixel
                        if (not existing or
                            existing.startswith("data:") or
                            "blank" in existing.lower() or
                            "placeholder" in existing.lower()):
                            tag = real_pattern.sub(
                                f'{real_attr}="{value}"', tag
                            )
                            modified = True
                    else:
                        # No real attr exists, add it
                        tag = tag.replace(
                            data_match.group(0),
                            f'{data_match.group(0)} {real_attr}="{value}"',
                        )
                        modified = True

            if modified:
                count += 1
            return tag

        html = re.sub(
            r'<img\b[^>]*/?\s*>',
            _fix_img,
            html,
            flags=re.IGNORECASE,
        )
        return html, count

    def _populate_src_from_srcset(self, html: str) -> Tuple[str, int]:
        """Populate empty/missing src from srcset on <img> tags.

        Shopify PDPs often use srcset as the primary image source with
        an empty src="". Extract the largest image URL from srcset and
        set it as the src for reliable rendering in static HTML.
        """
        count = 0

        def _fix_empty_src(match: re.Match) -> str:
            nonlocal count
            tag = match.group(0)

            # Check if src is empty or missing
            src_match = re.search(
                r'(?<![a-zA-Z-])src\s*=\s*["\']([^"\']*)["\']',
                tag, re.IGNORECASE,
            )
            has_real_src = (
                src_match and src_match.group(1) and
                not src_match.group(1).startswith("data:") and
                "blank" not in src_match.group(1).lower() and
                "placeholder" not in src_match.group(1).lower()
            )
            if has_real_src:
                return tag  # Already has a real src

            # Try to extract from srcset
            srcset_match = re.search(
                r'srcset\s*=\s*["\']([^"\']+)["\']',
                tag, re.IGNORECASE,
            )
            if not srcset_match:
                return tag

            # Parse srcset and pick the largest image
            srcset_val = srcset_match.group(1)
            best_url = ""
            best_width = 0
            for entry in srcset_val.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                tokens = entry.split()
                if not tokens:
                    continue
                url = tokens[0]
                width = 0
                if len(tokens) > 1:
                    w_match = re.match(r'(\d+)w', tokens[1])
                    if w_match:
                        width = int(w_match.group(1))
                if width > best_width or (not best_url and url):
                    best_url = url
                    best_width = width

            if best_url:
                count += 1
                if src_match:
                    # Replace empty src with best srcset URL
                    tag = tag[:src_match.start(1)] + best_url + tag[src_match.end(1):]
                else:
                    # Add src attribute
                    tag = tag.replace("<img", f'<img src="{best_url}"', 1)

            return tag

        html = re.sub(
            r'<img\b[^>]*/?\s*>',
            _fix_empty_src,
            html,
            flags=re.IGNORECASE,
        )
        return html, count

    def _strip_event_handlers(self, html: str) -> Tuple[str, int]:
        """Remove inline event handlers (onclick, onload, etc.)."""
        count = len(_EVENT_HANDLER_RE.findall(html))
        html = _EVENT_HANDLER_RE.sub("", html)
        return html, count

    def _neuter_forms(self, html: str) -> str:
        """Strip form action attributes and convert submit inputs to buttons."""
        html = _FORM_ACTION_RE.sub(r'\1', html)

        def _convert_submit(match: re.Match) -> str:
            attrs_before = match.group(1)
            attrs_after = match.group(2)
            # Extract value for button text
            value_match = re.search(
                r'value\s*=\s*["\']([^"\']*)["\']',
                attrs_before + attrs_after,
                re.IGNORECASE,
            )
            text = value_match.group(1) if value_match else "Submit"
            # Preserve class and style attrs
            preserved = []
            for attr in ("class", "style", "id"):
                attr_match = re.search(
                    rf'{attr}\s*=\s*["\']([^"\']*)["\']',
                    attrs_before + attrs_after,
                    re.IGNORECASE,
                )
                if attr_match:
                    preserved.append(f'{attr}="{attr_match.group(1)}"')
            attrs_str = " ".join(preserved)
            if attrs_str:
                attrs_str = " " + attrs_str
            return f'<button{attrs_str}>{text}</button>'

        html = _SUBMIT_INPUT_RE.sub(_convert_submit, html)
        return html

    def _unwrap_shopify_sections(self, html: str) -> str:
        """Unwrap <shopify-section> custom elements, keeping children."""
        return _SHOPIFY_SECTION_RE.sub(r'\1', html)

    # Templates that contain renderable content (Alpine.js, carousel lazy)
    # vs framework scaffolding.  Match <template> tags that either:
    # 1. Have Alpine directives (x-if, x-for, x-show)
    # 2. Are inside a swiper/carousel/gallery/product container
    _CONTENT_TEMPLATE_RE = re.compile(
        r'<template\b([^>]*?)>(.*?)</template\s*>',
        re.DOTALL | re.IGNORECASE,
    )
    _ALPINE_ATTR_RE = re.compile(r'x-(?:if|for|show)\s*=', re.IGNORECASE)
    _CAROUSEL_PARENT_RE = re.compile(
        r'(?:swiper|carousel|gallery|product-media|product__media)',
        re.IGNORECASE,
    )

    def _unwrap_content_templates(self, html: str) -> Tuple[str, int]:
        """Unwrap <template> tags that contain renderable content.

        Alpine.js x-if/x-for and Swiper lazy templates hold product
        images and content.  Unwrap them (keep inner HTML, drop the
        <template> wrapper) so the content survives the subsequent
        _strip_tags_with_content step.  Framework-scaffolding templates
        (no Alpine attrs, not inside a carousel) are left for stripping.
        """
        count = 0

        def _maybe_unwrap(m: re.Match) -> str:
            nonlocal count
            attrs = m.group(1)
            inner = m.group(2)

            # Always unwrap if Alpine directive present
            if self._ALPINE_ATTR_RE.search(attrs):
                count += 1
                return inner

            # Check if the template contains img/picture/video — likely
            # product content worth keeping
            if re.search(r'<(?:img|picture|video)\b', inner, re.IGNORECASE):
                count += 1
                return inner

            # Leave other templates for stripping
            return m.group(0)

        html = self._CONTENT_TEMPLATE_RE.sub(_maybe_unwrap, html)
        return html, count

    def _strip_dangerous_svg(self, html: str) -> Tuple[str, int]:
        """Strip dangerous elements from within <svg> subtrees."""
        count = 0
        for elem in _DANGEROUS_SVG_ELEMENTS:
            # Self-closing
            pattern_sc = re.compile(
                rf'<{elem}\b[^>]*/\s*>',
                re.IGNORECASE,
            )
            matches = pattern_sc.findall(html)
            count += len(matches)
            html = pattern_sc.sub("", html)

            # With content
            pattern_full = re.compile(
                rf'<{elem}\b[^>]*>.*?</{elem}\s*>',
                re.DOTALL | re.IGNORECASE,
            )
            matches = pattern_full.findall(html)
            count += len(matches)
            html = pattern_full.sub("", html)

        return html, count

    # Patterns for JS-set broken inline styles
    _EMPTY_ASPECT_RATIO_RE = re.compile(
        r'style="aspect-ratio:\s*"', re.IGNORECASE,
    )
    # Only strip height:0px on elements that look like JS-collapsed containers
    # (swiper wrappers, carousel containers, etc.) — NOT generic elements.
    _SWIPER_HEIGHT_0_RE = re.compile(
        r'(<[^>]*class="[^"]*(?:swiper|carousel|slider)[^"]*"[^>]*?)style="([^"]*?)height:\s*0px\s*;?\s*([^"]*?)"',
        re.IGNORECASE,
    )

    # Regex to strip specific CSS properties from inline style attributes
    # on elements whose class matches a pattern.  Groups:
    #   1 = tag prefix up to and including class="..."
    #   2 = style attribute value (the CSS text between quotes)
    @staticmethod
    def _strip_inline_props(html: str, class_kw: str,
                            props: list[str]) -> Tuple[str, int]:
        """Strip specific CSS properties from inline styles on elements
        whose class contains *class_kw*.

        General-purpose helper: works for any carousel/framework that
        sets JS-computed values as inline styles at runtime.
        """
        # Build pattern: opening tag with class containing keyword AND a style attr
        tag_re = re.compile(
            rf'(<[^>]*class="[^"]*{re.escape(class_kw)}[^"]*"[^>]*?)style="([^"]*)"',
            re.IGNORECASE,
        )
        # Build prop-stripping patterns
        prop_patterns = [
            re.compile(
                rf'{re.escape(p)}\s*:\s*[^;"]+(;|\s*(?="))',
                re.IGNORECASE,
            )
            for p in props
        ]
        count = 0

        def _clean(m: re.Match) -> str:
            nonlocal count
            prefix = m.group(1)
            style_val = m.group(2)
            for pp in prop_patterns:
                style_val, n = pp.subn('', style_val)
                count += n
            style_val = style_val.strip().rstrip(';').strip()
            if style_val:
                return f'{prefix}style="{style_val}"'
            return prefix.rstrip()

        return tag_re.sub(_clean, html), count

    def _fix_js_inline_styles(self, html: str) -> Tuple[str, int]:
        """Fix inline styles broken by JS frameworks.

        Handles:
        - Empty aspect-ratio from Shopify template hydration
        - Swiper JS runtime styles (transform, transition, margin, width)
          that break static rendering of carousels
        """
        count = 0

        # Remove empty aspect-ratio styles entirely
        html, n = self._EMPTY_ASPECT_RATIO_RE.subn('', html)
        count += n

        # Remove height:0px only from swiper/carousel/slider containers
        def _fix_swiper_height(m: re.Match) -> str:
            nonlocal count
            tag_before = m.group(1)
            style_before = m.group(2)
            style_after = m.group(3)
            remaining = (style_before + style_after).strip().rstrip(';').strip()
            count += 1
            if remaining:
                return f'{tag_before}style="{remaining}"'
            return tag_before.rstrip()

        html = self._SWIPER_HEIGHT_0_RE.sub(_fix_swiper_height, html)

        # Strip Swiper JS-set inline styles that break static rendering.
        # Swiper sets transform:translate3d() for slide position,
        # transition-duration for animations, and these are meaningless
        # (or harmful) in static HTML.
        html, n = self._strip_inline_props(
            html, class_kw='swiper-wrapper',
            props=['transform', 'transition-duration', 'transition-delay'],
        )
        count += n

        # NOTE: We intentionally keep width and margin-right on .swiper-slide.
        # These JS-computed values are correct (slidesPerView, spaceBetween)
        # and stripping them makes multi-slide carousels break catastrophically
        # (slides expand to 100% width). overflow:hidden on .swiper handles
        # any overflow from extra slides.

        # Clean up leftover empty style attributes
        html = re.sub(r'\s*style="\s*"', '', html)

        return html, count

    def _absolutize_urls(self, html: str, page_url: str) -> Tuple[str, int]:
        """Absolutize all relative URLs against page_url."""
        count = 0

        def _resolve_attr(match: re.Match) -> str:
            nonlocal count
            attr_name = match.group(1)
            quote = match.group(2)
            value = match.group(3)

            if not value or value.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
                return match.group(0)
            # Protocol-relative URLs (//domain.com/...) need https: prefix
            # to work in standalone HTML renders
            if value.startswith("//"):
                count += 1
                return f'{attr_name}={quote}https:{value}{quote}'
            if value.startswith(("http://", "https://")):
                return match.group(0)

            resolved = urljoin(page_url, value)
            count += 1
            return f'{attr_name}={quote}{resolved}{quote}'

        # Handle src, href, poster attributes
        for attr in ("src", "href", "poster", "data-src", "data-srcset", "data-lazy-src"):
            html = re.sub(
                rf'({attr})\s*=\s*(["\'])([^"\']*)\2',
                _resolve_attr,
                html,
                flags=re.IGNORECASE,
            )

        # Handle srcset (comma-separated values)
        def _resolve_srcset(match: re.Match) -> str:
            nonlocal count
            quote = match.group(1)
            value = match.group(2)

            parts = []
            for entry in value.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                tokens = entry.split()
                if tokens and tokens[0].startswith("//"):
                    tokens[0] = f"https:{tokens[0]}"
                    count += 1
                elif tokens and not tokens[0].startswith(("http://", "https://", "data:")):
                    tokens[0] = urljoin(page_url, tokens[0])
                    count += 1
                parts.append(" ".join(tokens))

            return f'srcset={quote}{", ".join(parts)}{quote}'

        html = re.sub(
            r'srcset\s*=\s*(["\'])([^"\']*)\1',
            _resolve_srcset,
            html,
            flags=re.IGNORECASE,
        )

        # Handle CSS url() values in <style> blocks and inline styles
        def _resolve_css_url(match: re.Match) -> str:
            nonlocal count
            url_val = match.group(1).strip().strip("'\"")
            if not url_val or url_val.startswith(
                ("#", "data:", "http://", "https://")
            ):
                return match.group(0)
            if url_val.startswith("//"):
                count += 1
                return f'url("https:{url_val}")'
            resolved = urljoin(page_url, url_val)
            count += 1
            return f'url("{resolved}")'

        html = re.sub(
            r'url\s*\(\s*([^)]+)\s*\)',
            _resolve_css_url,
            html,
        )

        return html, count

    def _extract_visible_text(self, html: str) -> str:
        """Extract visible text from HTML for viability check."""
        parser = _VisibleTextExtractor()
        try:
            parser.feed(html)
        except Exception:
            pass
        return parser.get_text()


class _VisibleTextExtractor(HTMLParser):
    """Extract visible text from HTML."""

    # Container tags whose content should be skipped (have closing tags)
    _INVISIBLE_CONTAINER_TAGS = frozenset([
        "style", "script", "head", "title",
    ])

    # Void/self-closing tags — no closing tag, so must NOT affect _skip_depth
    _INVISIBLE_VOID_TAGS = frozenset([
        "meta", "link",
    ])

    def __init__(self):
        super().__init__()
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in self._INVISIBLE_CONTAINER_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str):
        if tag.lower() in self._INVISIBLE_CONTAINER_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts)


# ---------------------------------------------------------------------------
# Image S3 proxy: download external images and rewrite to Supabase storage
# ---------------------------------------------------------------------------

# Max image download size (5MB per image)
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Image extensions we'll proxy
_IMAGE_EXTENSIONS = frozenset([
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif",
])

# Max number of images to proxy per page (avoid runaway costs)
_MAX_IMAGES_TO_PROXY = 100


def proxy_images_to_storage(
    html: str,
    supabase_client,
    storage_bucket: str = "lp-images",
    storage_prefix: str = "",
    timeout: float = 10.0,
) -> Tuple[str, dict]:
    """Download external images and upload to Supabase storage, rewriting URLs.

    Ensures images survive even if the original site blocks hotlinking
    or goes offline. Only proxies images with HTTPS URLs from external
    domains. Skips data: URIs, already-proxied URLs, and oversized images.

    Args:
        html: HTML document with external image URLs.
        supabase_client: Supabase client instance with storage access.
        storage_bucket: Storage bucket name for uploaded images.
        storage_prefix: Path prefix for stored images (e.g. "org_id/analysis_id/").
        timeout: HTTP timeout per image download in seconds.

    Returns:
        (html_with_proxied_urls, stats) where stats contains counts
        of proxied, skipped, and failed images.
    """
    import hashlib
    import httpx
    from urllib.parse import urlparse

    stats = {
        "total_images": 0,
        "proxied": 0,
        "skipped": 0,
        "failed": 0,
    }

    # Extract all image src URLs
    img_src_re = re.compile(
        r'(<img\b[^>]*?)(?<![a-zA-Z-])src\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )

    # Collect unique URLs to avoid downloading the same image twice
    url_to_storage: dict = {}
    urls_to_process: List[Tuple[str, str]] = []  # (original_url, hash_key)

    for match in img_src_re.finditer(html):
        url = match.group(2)
        if not url or not url.startswith("https://"):
            continue

        # Skip data URIs and already-proxied URLs
        parsed = urlparse(url)
        if parsed.hostname and "supabase" in parsed.hostname:
            continue

        # Check extension
        path_lower = parsed.path.lower()
        has_img_ext = any(path_lower.endswith(ext) or ext + "?" in path_lower
                         for ext in _IMAGE_EXTENSIONS)
        # Also accept Shopify CDN URLs without extension
        is_cdn = "cdn.shopify.com" in (parsed.hostname or "")
        if not has_img_ext and not is_cdn:
            continue

        # Create deterministic hash for filename
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        ext = ".webp"  # default
        for e in _IMAGE_EXTENSIONS:
            if e in path_lower:
                ext = e
                break

        if url not in url_to_storage:
            urls_to_process.append((url, f"{url_hash}{ext}"))
        stats["total_images"] += 1

    if not urls_to_process:
        return html, stats

    # Limit to prevent runaway
    if len(urls_to_process) > _MAX_IMAGES_TO_PROXY:
        logger.warning(
            f"Image proxy: capping at {_MAX_IMAGES_TO_PROXY} images "
            f"(found {len(urls_to_process)})"
        )
        urls_to_process = urls_to_process[:_MAX_IMAGES_TO_PROXY]

    # Download and upload images
    bucket = supabase_client.storage.from_(storage_bucket)
    client = httpx.Client(timeout=timeout, follow_redirects=True)

    try:
        for original_url, filename in urls_to_process:
            storage_path = f"{storage_prefix}{filename}"
            try:
                resp = client.get(original_url)
                if resp.status_code != 200:
                    stats["failed"] += 1
                    continue
                if len(resp.content) > _MAX_IMAGE_BYTES:
                    stats["skipped"] += 1
                    continue
                if len(resp.content) < 100:
                    stats["skipped"] += 1
                    continue

                content_type = resp.headers.get("content-type", "image/jpeg")
                if ";" in content_type:
                    content_type = content_type.split(";")[0].strip()

                bucket.upload(
                    storage_path,
                    resp.content,
                    {"content-type": content_type, "upsert": "true"},
                )

                # Get public URL
                public_url = bucket.get_public_url(storage_path)
                url_to_storage[original_url] = public_url
                stats["proxied"] += 1

            except Exception as e:
                logger.debug(f"Image proxy failed for {original_url}: {e}")
                stats["failed"] += 1
    finally:
        client.close()

    # Rewrite URLs in HTML
    if url_to_storage:
        for original_url, proxied_url in url_to_storage.items():
            html = html.replace(original_url, proxied_url)

    logger.info(
        f"Image proxy: {stats['proxied']} proxied, "
        f"{stats['failed']} failed, {stats['skipped']} skipped"
    )

    return html, stats
