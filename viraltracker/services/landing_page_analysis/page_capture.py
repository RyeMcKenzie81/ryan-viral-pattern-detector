"""Capture post-JS rendered DOM via Playwright headless Chromium.

Sync Playwright pattern matching html_renderer.py — function-local import
for dev-only graceful degradation. Returns None on any failure (caller
falls back to Firecrawl).

Used by analysis_service.py Stage 2 to get hydrated DOM instead of
Firecrawl's pre-JS HTML (which contains template placeholders on
Shopify pages).
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    """Result of a Playwright DOM capture."""

    dom_html: str  # page.content() — post-JS DOM, scripts stripped
    screenshot_bytes: Optional[bytes]  # full-page PNG (optional)
    final_url: str  # after redirects
    capture_time_ms: int
    visible_text_len: int  # body.innerText length (quality check)


class PlaywrightNotInstalledError(Exception):
    """Raised when Playwright is not installed."""


class CaptureTimeoutError(Exception):
    """Raised when page capture times out."""


# Selectors for overlay/popup elements to remove before capture
_OVERLAY_SELECTORS = (
    '[class*="popup"], [class*="modal"], [class*="overlay"], '
    '[id*="cookie"], [class*="consent"], [class*="newsletter-popup"], '
    '[class*="exit-intent"]'
)

# Selectors for navigation chrome to remove (nav bars, headers, footers, cart drawers).
# These match what Firecrawl's only_main_content=True strips from markdown,
# and what Shopify/Replo themes hide via display:none on landing pages.
# IMPORTANT: Keep selectors conservative — Replo content can live inside
# Shopify section wrappers, so avoid broad class-based selectors like
# [class*='primary-logo'] which can catch visible content.
_CHROME_SELECTORS = (
    # NOTE: We intentionally keep <header>, <nav>, and announcement bars.
    # These are visually important for page fidelity. Only remove elements
    # that are overlays, drawers, or non-visual chrome.
    "footer, "
    "[id*='shopify-section-footer'], "
    "[class*='cart-drawer'], [class*='cart-sidebar'], [class*='CartDrawer'], "
    "[class*='drawer'][class*='cart'], [class*='ajax-cart'], [class*='theme-ajax-cart'], "
    "[class*='mini__cart'], [class*='mini-cart'], [class*='minicart'], "
    "[class*='site-footer'], "
    # Mega menus (Shopify theme dropdown navigation panels)
    "[id*='mega-menu'], [id*='mega_menu'], [class*='mega-menu'], [class*='megamenu'], "
    "[id*='shopify-section-mega'], "
    # Mobile menu drawers and icon sprite containers
    "[class*='mobile-menu'], [class*='mobile-nav'], [class*='menu-drawer'], "
    "[class*='icon-reference'], svg[aria-hidden='true'][class*='icon'], "
    "[class*='mobile-logo'], "
    # Accessibility skip-nav links (visually hidden, becomes visible when CSS stripped)
    "[class*='skip-to-content'], [class*='visually-hidden'], "
    # Shopify app custom elements and third-party widgets
    "inbox-online-store-chat, shopify-chat, shop-cart-sync, "
    "[id='ShopifyChat'], "
    # Monster Upsells cart drawer (mu-* classes)
    "[id='monster-cart-wrapper'], [id='monster-upsell-cart'], [class*='monster_upsell'], "
    # Shopify app blocks (third-party app containers: social widgets, loyalty,
    # popups, etc.). Replo content uses data-rid attributes, not shopify-app-block.
    "[class~='shopify-app-block'], "
    # Third-party app widgets (Alia popups, free shipping bars, etc.)
    "[id^='alia-root'], [id^='fsb_'], "
    # Shopify infrastructure elements (analytics, CSS lockdown, pixel sandbox)
    "[id='web-pixels-manager-sandbox-container'], [id*='polaris-css'], "
    # Modal dialogs (catches generic popups/overlays including Alia)
    "[aria-modal='true']"
)

# JS snippet to remove hidden elements, SVG sprites, fixed widgets, and
# zero-size elements that render as junk when CSS is stripped by the
# surgery pipeline.
_REMOVE_HIDDEN_AND_SPRITES_JS = """(() => {
    let removed = 0;

    // 1. Remove SVG containers that only hold <symbol> definitions (icon sprites)
    document.querySelectorAll('svg').forEach(svg => {
        if (svg.querySelector('symbol') && !svg.querySelector('text, image, foreignObject')) {
            svg.remove();
            removed++;
        }
    });

    // 2. Remove aria-hidden SVGs that are decorative icon references
    document.querySelectorAll('svg[aria-hidden="true"]').forEach(svg => {
        const rect = svg.getBoundingClientRect();
        if (rect.width <= 30 && rect.height <= 30) {
            svg.remove();
            removed++;
        }
    });

    // 3. Remove unconstrained Shopify theme icon SVGs (viewBox but no width/height).
    //    These are icon defs (cart, email, avatar, etc.) that expand to full
    //    container width when their parent's display:none CSS is stripped.
    document.querySelectorAll('svg[viewBox]').forEach(svg => {
        if (!svg.hasAttribute('width') && !svg.hasAttribute('height')) {
            const g = svg.querySelector('g[id]');
            if (g) {
                svg.remove();
                removed++;
            }
        }
    });

    // 4. Remove top-level body children that are hidden (display:none only).
    //    These are Shopify theme sections hidden by page builders like Replo.
    //    Only check direct body children to avoid removing animation targets.
    document.querySelectorAll('body > *').forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.display === 'none') {
            el.remove();
            removed++;
        }
    });

    return removed;
})()"""

# JS snippet to force-show JS-hidden content for static capture.
# JS frameworks (Alpine.js x-show, React, Vue v-show) hide product
# galleries, variant selectors, tabs etc. by default. We force these
# visible so the static HTML snapshot captures the actual content.
# ONLY targets elements inside the main content area — avoids showing
# drawers, modals, cart sidebars, and off-canvas navigation.
_FORCE_SHOW_JS_HIDDEN_JS = """(() => {
    let shown = 0;

    // Selectors for containers that should STAY hidden (not product content)
    const KEEP_HIDDEN_PATTERNS = [
        'cart', 'drawer', 'sidebar', 'modal', 'popup', 'overlay',
        'menu', 'dropdown', 'mega-menu', 'off-canvas', 'offcanvas',
        'tooltip', 'toast', 'notification',
        'cookie', 'consent', 'newsletter', 'exit-intent',
        'search-modal', 'quick-view', 'mini-cart',
    ];

    function shouldKeepHidden(el) {
        const id = (el.id || '').toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        // Check if element or any ancestor is a drawer/modal/cart
        let check = el;
        for (let i = 0; i < 5 && check && check !== document.body; i++) {
            const cId = (check.id || '').toLowerCase();
            const cCls = (check.className || '').toString().toLowerCase();
            const cRole = (check.getAttribute('role') || '').toLowerCase();
            if (cRole === 'dialog' || cRole === 'alertdialog') return true;
            if (check.tagName === 'DIALOG') return true;
            for (const pat of KEEP_HIDDEN_PATTERNS) {
                if (cId.includes(pat) || cCls.includes(pat)) return true;
            }
            check = check.parentElement;
        }
        return false;
    }

    // 1. Force-show elements hidden by JS frameworks inside main content.
    //    ONLY force-show elements that contain product media (images, video,
    //    galleries, carousels). Skip UI toggles like tabs, accordions,
    //    pricing switches — these create duplicate/zombie content.
    function hasProductMedia(el) {
        return el.querySelector(
            'img, picture, video, [data-src], ' +
            '.swiper, .splide, .glide, .slick, ' +
            '[class*="gallery"], [class*="carousel"], [class*="slider"]'
        );
    }

    // Patterns indicating UI toggle elements (not product content)
    function isUIToggle(el) {
        const xShow = (el.getAttribute('x-show') || '').toLowerCase();
        // x-show expressions referencing state toggles: tab, accordion, plan, faq
        if (/\\b(tab|accordion|faq|activeplan|showmore|expanded|open)\\b/i.test(xShow)) {
            return true;
        }
        const attrs = el.getAttributeNames();
        if (attrs.some(a => a.startsWith('x-collapse'))) return true;
        const style = window.getComputedStyle(el);
        if (style.height === '0px' && style.overflow === 'hidden') return true;
        return false;
    }

    const jsAttrSelectors = [
        '[x-show]', '[x-bind\\\\:class]', '[\\\\:class]',
        '[v-show]', '[v-if]',
        '[data-state]', '[data-active]', '[data-visible]',
    ].join(',');

    document.querySelectorAll(jsAttrSelectors).forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' && !shouldKeepHidden(el)) {
            // Skip UI toggle elements (tabs, accordions, pricing)
            if (isUIToggle(el)) return;
            // Only force-show if element contains product media content
            if (!hasProductMedia(el)) return;

            el.style.setProperty('display', '', 'important');
            // If still hidden after removing display, force block
            const recheck = window.getComputedStyle(el);
            if (recheck.display === 'none') {
                el.style.setProperty('display', 'block', 'important');
            }
            shown++;
        }
    });

    // 2. Force-show Tailwind 'hidden' class elements inside main/product areas.
    //    The 'hidden' class is often toggled by Alpine.js x-show.
    //    IMPORTANT: Skip responsive duplicates — elements hidden for desktop
    //    viewports (e.g., mobile gallery alongside desktop gallery). Showing
    //    these breaks grid/flex layouts by adding unexpected children.
    document.querySelectorAll('.hidden').forEach(el => {
        // Only force-show if it has meaningful content (images, swiper, gallery)
        const hasImages = el.querySelector('img, picture, video, [data-src]');
        const hasSwiper = el.querySelector('.swiper, .splide, .glide, .slick');
        const hasProduct = el.querySelector(
            '[class*="product"], [class*="gallery"], [class*="carousel"], ' +
            '[class*="media"], [class*="variant"], [class*="option"]'
        );
        if ((hasImages || hasSwiper || hasProduct) && !shouldKeepHidden(el)) {
            // Responsive duplicate check: skip if a visible sibling of
            // this element (or any ancestor up to 3 levels) already has
            // the same type of media content. This prevents showing
            // mobile/desktop gallery variants simultaneously.
            let skip = false;
            let check = el;
            for (let depth = 0; depth < 3 && check.parentElement; depth++) {
                const par = check.parentElement;
                const hasSiblingMedia = Array.from(par.children).some(sib => {
                    if (sib === check) return false;
                    if (window.getComputedStyle(sib).display === 'none') return false;
                    return sib.querySelector(
                        'img, picture, video, .swiper, .splide, .glide, .slick'
                    );
                });
                if (hasSiblingMedia) { skip = true; break; }
                check = par;
            }
            if (skip) return;  // skip responsive duplicate
            el.classList.remove('hidden');
            el.style.setProperty('display', '', 'important');
            shown++;
        }
    });

    // 3. Force-show elements with visibility:hidden that contain product content
    document.querySelectorAll('[class*="product"], [class*="gallery"], [class*="media"]').forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' && !shouldKeepHidden(el)) {
            el.style.setProperty('visibility', 'visible', 'important');
            shown++;
        }
    });

    return shown;
})()"""

# JS snippet to remove anti-scraping overlay divs.
# These are full-page overlays with extreme z-index and transparent text,
# injected by Shopify themes to block content scrapers. They render as
# invisible text junk when the page is captured as static HTML.
_REMOVE_ANTI_SCRAPE_OVERLAYS_JS = """(() => {
    let removed = 0;
    document.querySelectorAll('div').forEach(el => {
        const style = window.getComputedStyle(el);
        const zIndex = parseInt(style.zIndex, 10);
        // Anti-scraping overlays use z-index > 10^8 with transparent/invisible text
        if (zIndex > 99999999 && (
            style.color === 'transparent' ||
            style.color === 'rgba(0, 0, 0, 0)' ||
            style.opacity === '0'
        )) {
            el.remove();
            removed++;
        }
    });
    return removed;
})()"""

# Regex to strip <script> tag contents while preserving the tags
_SCRIPT_CONTENT_RE = re.compile(
    r"(<script\b[^>]*>)(.*?)(</script>)",
    re.DOTALL | re.IGNORECASE,
)

# Regex to convert loading="lazy" to loading="eager" on images.
# Ensures all images load immediately when surgery output HTML is rendered,
# rather than requiring scroll-into-view (which the screenshot renderer
# may not trigger for below-the-fold images).
_LAZY_TO_EAGER_RE = re.compile(
    r'loading\s*=\s*["\']lazy["\']',
    re.IGNORECASE,
)


def _strip_script_content(html: str) -> str:
    """Strip content from <script> tags, keeping the tags for structure."""
    return _SCRIPT_CONTENT_RE.sub(r"\1\3", html)


def _convert_lazy_to_eager(html: str) -> str:
    """Convert loading='lazy' to loading='eager' on all elements."""
    return _LAZY_TO_EAGER_RE.sub('loading="eager"', html)


def capture_rendered_page(
    url: str,
    viewport_width: int = 1440,
    viewport_height: int = 900,
    capture_screenshot: bool = False,
    scroll_to_load: bool = True,
    timeout_ms: int = 30000,
) -> Optional[CaptureResult]:
    """Capture post-JS DOM via sync Playwright.

    Navigates to the URL, waits for JS hydration, scrolls to trigger lazy
    loading, removes overlays, and returns the rendered DOM HTML with
    script content stripped.

    Returns None on any failure (caller falls back to Firecrawl).

    Args:
        url: Page URL to capture.
        viewport_width: Browser viewport width (default 1440). Uses 1440 to
            clear custom Tailwind xl breakpoints (some themes set xl=1440px).
        viewport_height: Browser viewport height (default 900).
        capture_screenshot: Whether to capture a full-page PNG screenshot.
        scroll_to_load: Whether to auto-scroll to trigger lazy loading.
        timeout_ms: Navigation timeout in milliseconds.
    """
    start = time.time()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PlaywrightNotInstalledError(
            "Playwright is not installed. Install with: pip install playwright && playwright install chromium"
        )

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": viewport_width, "height": viewport_height}
        )

        # Navigate — use domcontentloaded then wait, since networkidle
        # can hang on pages with persistent connections (analytics, etc.)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Wait for CSS to fully load before any DOM manipulation.
        # domcontentloaded fires when HTML is parsed but external CSS
        # may still be loading. Without CSS, getComputedStyle() returns
        # wrong values (e.g., display:none for elements that should be
        # visible at the xl breakpoint).
        try:
            page.wait_for_load_state("load", timeout=8000)
        except Exception:
            logger.debug("Timed out waiting for full load, proceeding with domcontentloaded")

        page.wait_for_timeout(3000)  # allow JS hydration + Swiper init

        # Freeze animations AFTER hydration. Must come after the wait so
        # that CSS transitions (e.g., announcement bar opacity fade-in)
        # have time to complete before we freeze them.
        page.add_style_tag(
            content="* { animation: none !important; transition: none !important; }"
        )

        # Remove overlay/popup elements via DOM removal (deterministic)
        page.evaluate(
            "(sels) => document.querySelectorAll(sels).forEach(el => el.remove())",
            _OVERLAY_SELECTORS,
        )

        # Remove non-visual chrome (footer, cart drawers, mega menus)
        chrome_removed = page.evaluate(
            "(sels) => { const els = document.querySelectorAll(sels); els.forEach(el => el.remove()); return els.length; }",
            _CHROME_SELECTORS,
        )
        if chrome_removed:
            logger.info(f"Removed {chrome_removed} navigation chrome elements")

        # Force-show JS-hidden product content (Alpine.js x-show, Tailwind
        # 'hidden' class, Vue v-show, etc.) BEFORE removing hidden elements.
        # This ensures product galleries, variant selectors, and carousels
        # that are hidden by default JS state become visible for capture.
        js_shown = page.evaluate(_FORCE_SHOW_JS_HIDDEN_JS)
        if js_shown:
            logger.info(f"Force-showed {js_shown} JS-hidden content element(s)")

        # Remove SVG sprites and elements hidden via computed style
        hidden_removed = page.evaluate(_REMOVE_HIDDEN_AND_SPRITES_JS)
        if hidden_removed:
            logger.info(f"Removed {hidden_removed} hidden/sprite elements")

        # Remove anti-scraping overlay divs (huge z-index + transparent text)
        anti_scrape_removed = page.evaluate(_REMOVE_ANTI_SCRAPE_OVERLAYS_JS)
        if anti_scrape_removed:
            logger.info(f"Removed {anti_scrape_removed} anti-scraping overlay(s)")

        # Auto-scroll to trigger lazy loading
        if scroll_to_load:
            for _ in range(15):
                page.evaluate("window.scrollBy(0, 400)")
                page.wait_for_timeout(300)
            # Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

        # Cycle through Swiper slides to force lazy-loaded images to render.
        # Swiper only populates slide content when slides become active.
        swiper_slides_loaded = page.evaluate("""(() => {
            let loaded = 0;
            // Find all Swiper instances on the page
            document.querySelectorAll('.swiper').forEach(container => {
                const swiper = container.swiper;
                if (!swiper || !swiper.slides || swiper.slides.length <= 1) return;
                const original = swiper.activeIndex;
                // Click through each slide to trigger lazy loading
                for (let i = 0; i < swiper.slides.length; i++) {
                    try { swiper.slideTo(i, 0); } catch(e) {}
                }
                // Return to original slide
                try { swiper.slideTo(original, 0); } catch(e) {}
                loaded += swiper.slides.length;
            });
            return loaded;
        })()""")
        if swiper_slides_loaded:
            logger.info(f"Cycled through {swiper_slides_loaded} Swiper slides for lazy loading")
            page.wait_for_timeout(1000)  # allow images to load

        # Second cleanup pass — catch elements injected by scripts triggered
        # during scrolling (e.g. Alia popups, late-loaded cart widgets)
        late_chrome = page.evaluate(
            "(sels) => { const els = document.querySelectorAll(sels); els.forEach(el => el.remove()); return els.length; }",
            _CHROME_SELECTORS,
        )
        late_overlays = page.evaluate(
            "(sels) => { const els = document.querySelectorAll(sels); els.forEach(el => el.remove()); return els.length; }",
            _OVERLAY_SELECTORS,
        )
        # Force-show any newly-rendered JS-hidden content (scrolling may
        # have triggered lazy component initialization)
        page.evaluate(_FORCE_SHOW_JS_HIDDEN_JS)
        late_hidden = page.evaluate(_REMOVE_HIDDEN_AND_SPRITES_JS)
        late_anti_scrape = page.evaluate(_REMOVE_ANTI_SCRAPE_OVERLAYS_JS)
        if late_chrome or late_overlays or late_hidden or late_anti_scrape:
            logger.info(
                f"Second pass removed {late_chrome} chrome, "
                f"{late_overlays} overlays, {late_hidden} hidden, "
                f"{late_anti_scrape} anti-scrape"
            )

        # Restore header/nav visibility after scroll. Scroll-triggered JS
        # can hide announcement bars (opacity:0) and collapse sticky headers
        # (height:0) when scrolling down. Even after scrolling back to top,
        # these JS handlers may not restore the original state.
        header_restored = page.evaluate("""(() => {
            let fixed = 0;
            const sels = 'header, nav, [id*="announcement"], [id*="header"], [class*="announcement"], [class*="promo-bar"]';
            document.querySelectorAll(sels).forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.opacity === '0') {
                    el.style.setProperty('opacity', '1', 'important');
                    fixed++;
                }
                if (style.height === '0px' && el.scrollHeight > 0) {
                    el.style.setProperty('height', 'auto', 'important');
                    el.style.setProperty('overflow', 'visible', 'important');
                    fixed++;
                }
            });
            return fixed;
        })()""")
        if header_restored:
            logger.info(f"Restored {header_restored} header/nav element(s) hidden by scroll")

        # Quality check: visible text length
        visible_text_len = page.evaluate("document.body.innerText.length")
        if visible_text_len < 200:
            logger.warning(
                f"Playwright capture quality check failed: only {visible_text_len} "
                f"visible chars (CAPTCHA, blank page, or bot detection)"
            )
            return None

        # Unwrap <template> tags so their content survives the sanitizer's
        # template-stripping step.  Two patterns:
        # 1. Templates inside carousel/gallery slides (Shopify Swiper lazy content)
        # 2. Alpine.js x-if/x-for templates (conditionally rendered product content)
        # For Alpine templates, template.content may be empty — fall back to
        # reading innerHTML directly.
        templates_unwrapped = page.evaluate("""(() => {
            let count = 0;

            // Carousel templates (broad selectors)
            const carouselSels = '.swiper-slide template, .carousel-slide template, '
                + '.gallery template, .product-gallery template, .product-media template, '
                + '.product__media template';

            // Alpine.js conditional templates
            const alpineSels = 'template[x-if], template[x-for]';

            const all = new Set([
                ...document.querySelectorAll(carouselSels),
                ...document.querySelectorAll(alpineSels),
            ]);

            all.forEach(t => {
                // Try standard template.content first
                const frag = t.content.cloneNode(true);
                if (frag.childNodes.length > 0) {
                    t.parentNode.replaceChild(frag, t);
                    count++;
                } else if (t.innerHTML.trim()) {
                    // Alpine x-if: content lives in innerHTML, not .content
                    const div = document.createElement('div');
                    div.innerHTML = t.innerHTML;
                    while (div.firstChild) t.parentNode.insertBefore(div.firstChild, t);
                    t.remove();
                    count++;
                }
            });
            return count;
        })()""")
        if templates_unwrapped:
            logger.info(f"Unwrapped {templates_unwrapped} <template> tags in carousel/Alpine slides")

        # Capture DOM
        dom_html = page.content()

        # Strip <script> content to reduce size and noise
        dom_html = _strip_script_content(dom_html)

        # Convert lazy-loaded images to eager so they render in static HTML
        dom_html = _convert_lazy_to_eager(dom_html)

        # Capture final URL (after redirects)
        final_url = page.url

        # Optional screenshot
        screenshot_bytes = None
        if capture_screenshot:
            screenshot_bytes = page.screenshot(full_page=True, timeout=15000)

        elapsed_ms = int((time.time() - start) * 1000)

        return CaptureResult(
            dom_html=dom_html,
            screenshot_bytes=screenshot_bytes,
            final_url=final_url,
            capture_time_ms=elapsed_ms,
            visible_text_len=visible_text_len,
        )

    except PlaywrightNotInstalledError:
        raise
    except Exception as e:
        logger.warning(f"Playwright capture failed for {url}: {e}")
        return None
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
