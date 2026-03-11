"""Render HTML strings to PNG screenshots via Playwright headless Chromium.

Thin wrapper with canonical settings for deterministic SSIM comparisons.
Playwright imports are function-local (dev-only dependency).
Never crashes — returns None on any failure.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Canonical render settings — shared with eval_multipass.py and visual_fidelity_check.py
RENDER_VIEWPORT_WIDTH = 1440
RENDER_VIEWPORT_HEIGHT = 900
FREEZE_ANIMATIONS_CSS = (
    "<style>* { animation: none !important; transition: none !important; }</style>"
)


def render_html_to_png(
    html: str,
    viewport_width: int = RENDER_VIEWPORT_WIDTH,
    viewport_height: int = RENDER_VIEWPORT_HEIGHT,
) -> Optional[bytes]:
    """Render HTML string to PNG bytes using Playwright headless Chromium (sync).

    Returns PNG bytes, or None if rendering fails (missing Playwright, timeout, etc).

    Args:
        html: Full HTML document string.
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.
    """
    if not html or not html.strip():
        return None

    temp_path = None
    try:
        # Step 1: Restore background images if extractor is available
        try:
            from .html_extractor import restore_background_images
            html = restore_background_images(html)
        except ImportError:
            pass

        # Step 2: Freeze animations for deterministic rendering
        html = FREEZE_ANIMATIONS_CSS + html

        # Step 3: Write prepared HTML to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(html)
            temp_path = f.name

        # Step 4: Render with Playwright (function-local import)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": viewport_width, "height": viewport_height}
                )
                page.goto(f"file://{temp_path}")
                page.wait_for_load_state("networkidle")
                png_bytes = page.screenshot(full_page=True)
                return png_bytes
            finally:
                browser.close()

    except ImportError:
        logger.debug("Playwright not installed — skipping HTML rendering")
        return None
    except Exception as e:
        logger.warning(f"HTML rendering failed: {e}")
        return None
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


async def render_html_to_png_async(
    html: str,
    viewport_width: int = RENDER_VIEWPORT_WIDTH,
    viewport_height: int = RENDER_VIEWPORT_HEIGHT,
) -> Optional[bytes]:
    """Async wrapper — runs sync Playwright in a thread pool.

    Use this from async contexts (e.g. SurgeryPipeline.generate) to avoid
    the "Playwright Sync API inside asyncio loop" error.
    """
    import asyncio

    return await asyncio.to_thread(
        render_html_to_png, html, viewport_width, viewport_height
    )
