"""
Shared auto-fill suggestion UI for Brand Manager.

Renders Accept/Skip/Undo UI for ContentGapFillerService suggestions,
writing directly to production DB tables (not session JSONB like Onboarding).
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

import streamlit as st

logger = logging.getLogger(__name__)

# All LP fields (includes offer_variant fields — use only when OV exists)
BM_LP_AUTOFILL_FIELDS = [
    "product.guarantee",
    "product.ingredients",
    "product.faq_items",
    "product.results_timeline",
    "offer_variant.mechanism.name",
    "offer_variant.mechanism.root_cause",
    "offer_variant.pain_points",
    "brand.voice_tone",
]

# Product/brand-only fields (safe when no offer_variant_id exists)
BM_PRODUCT_AUTOFILL_FIELDS = [
    "product.guarantee",
    "product.ingredients",
    "product.faq_items",
    "product.results_timeline",
    "brand.voice_tone",
]

# Better display names with entity context
_DISPLAY_NAMES = {
    "product.guarantee": "Product > Guarantee",
    "product.ingredients": "Product > Ingredients",
    "product.faq_items": "Product > FAQ Items",
    "product.results_timeline": "Product > Results Timeline",
    "offer_variant.mechanism.name": "Variant > Mechanism Name",
    "offer_variant.mechanism.root_cause": "Variant > Mechanism Root Cause",
    "offer_variant.pain_points": "Variant > Pain Points",
    "brand.voice_tone": "Brand > Voice/Tone",
}

_CONF_ICONS = {"high": "🟢", "medium": "🟡", "low": "🟠"}


def _get_gap_filler_service():
    """Get ContentGapFillerService instance with tracking."""
    from viraltracker.services.landing_page_analysis.content_gap_filler_service import (
        ContentGapFillerService,
    )
    from viraltracker.core.database import get_supabase_client
    from viraltracker.ui.utils import setup_tracking_context

    supabase = get_supabase_client()
    svc = ContentGapFillerService(supabase=supabase)
    setup_tracking_context(svc)
    return svc


def scrape_and_extract(
    url: str,
    product_name: Optional[str] = None,
    brand_name: Optional[str] = None,
    target_fields: Optional[list] = None,
) -> Tuple[Dict, Optional[str]]:
    """Scrape a URL and extract auto-fill suggestions.

    Args:
        url: Landing page URL to scrape.
        product_name: Product name for keyword relevance check.
        brand_name: Brand name for keyword relevance check.
        target_fields: Fields to extract (defaults to BM_LP_AUTOFILL_FIELDS).

    Returns:
        Tuple of (suggestions dict, optional warning message).
    """
    from viraltracker.services.web_scraping_service import WebScrapingService

    web_service = WebScrapingService()
    result = web_service.scrape_url(url, formats=["markdown"])

    if not result.success or not result.markdown:
        raise ValueError(f"Scrape failed: {result.error or 'No content returned'}")

    raw_markdown = result.markdown
    warning = None
    if len(raw_markdown) < 2000:
        warning = (
            f"Very short content ({len(raw_markdown)} chars) — "
            "page may not have loaded fully. Try re-running."
        )

    gap_filler = _get_gap_filler_service()
    suggestions = asyncio.run(
        gap_filler.extract_from_raw_content(
            raw_content=raw_markdown,
            target_fields=target_fields or BM_LP_AUTOFILL_FIELDS,
            content_source="fresh_scrape",
            source_url=url,
            product_name=product_name,
            brand_name=brand_name,
        )
    )
    return suggestions, warning


def _extract_colors_from_html(html: str) -> Dict:
    """Extract brand colors from CSS in HTML (deterministic, no LLM)."""
    import re
    from collections import Counter
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')

    # Collect all CSS content
    css_text = ""
    for style_tag in soup.find_all('style'):
        css_text += (style_tag.string or "")
    for elem in soup.find_all(style=True):
        css_text += elem['style']

    # Find hex colors
    hex_colors = re.findall(r'#([0-9a-fA-F]{3,6})\b', css_text)

    # Normalize to 6-digit uppercase hex
    normalized = []
    for h in hex_colors:
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        elif len(h) != 6:
            continue
        normalized.append(f"#{h.upper()}")

    # Filter common neutrals
    neutrals = {
        "#000000", "#FFFFFF", "#CCCCCC", "#333333", "#666666", "#999999",
        "#F5F5F5", "#EEEEEE", "#DDDDDD", "#AAAAAA", "#888888", "#FAFAFA",
        "#F0F0F0", "#E0E0E0", "#111111", "#222222", "#444444", "#555555",
        "#777777", "#BBBBBB", "#F8F8F8", "#FEFEFE", "#F9F9F9",
    }

    counter = Counter(normalized)
    brand_colors = [(c, n) for c, n in counter.most_common(20) if c not in neutrals]

    result = {}
    if brand_colors:
        result["primary"] = brand_colors[0][0]
        if len(brand_colors) > 1:
            result["accent"] = brand_colors[1][0]
        if len(brand_colors) > 2:
            result["secondary"] = [c for c, _ in brand_colors[2:5]]

    return result


def _extract_fonts_from_html(html: str) -> Dict:
    """Extract brand fonts from CSS and Google Fonts links (deterministic, no LLM)."""
    import re
    from collections import Counter
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')

    # Collect CSS text from <style> tags and inline styles
    css_text = ""
    for style_tag in soup.find_all('style'):
        css_text += (style_tag.string or "")
    for elem in soup.find_all(style=True):
        css_text += elem['style']

    # Check <link> tags for Google Fonts
    google_fonts = []
    for link in soup.find_all('link', href=True):
        href = link['href']
        if 'fonts.googleapis.com' in href:
            family_matches = re.findall(r'family=([^&:]+)', href)
            for fam in family_matches:
                font_name = fam.replace('+', ' ')
                google_fonts.append(font_name)

    # Find font-family declarations in CSS
    font_declarations = re.findall(r'font-family:\s*([^;}"]+)', css_text, re.IGNORECASE)

    generic_families = {
        "serif", "sans-serif", "monospace", "cursive", "fantasy",
        "system-ui", "-apple-system", "blinkmacsystemfont", "segoe ui",
        "inherit", "initial", "unset",
    }

    fonts = []
    for decl in font_declarations:
        parts = [f.strip().strip("'\"") for f in decl.split(",")]
        for p in parts:
            if p.lower() not in generic_families and p:
                fonts.append(p)
                break

    counter = Counter(fonts)

    # Prefer Google Fonts if found (they're intentional choices)
    if google_fonts:
        result = {"primary": google_fonts[0]}
        if len(google_fonts) > 1:
            result["secondary"] = google_fonts[1]
        return result

    result = {}
    if counter:
        top = counter.most_common(2)
        result["primary"] = top[0][0]
        if len(top) > 1:
            result["secondary"] = top[1][0]

    return result


def extract_brand_identity(
    url: str,
    brand_name: Optional[str] = None,
) -> Dict:
    """Scrape a website and extract brand voice, colors, and fonts.

    Args:
        url: Brand website URL.
        brand_name: Brand name for context.

    Returns:
        Dict with keys: voice (str|None), colors (dict), fonts (dict), warning (str|None).
    """
    from viraltracker.services.web_scraping_service import WebScrapingService

    web_service = WebScrapingService()
    result = web_service.scrape_url(url, formats=["markdown", "html"], only_main_content=False)

    if not result.success:
        raise ValueError(f"Scrape failed: {result.error or 'No content returned'}")

    warning = None
    voice = None
    colors = {}
    fonts = {}

    # Extract colors and fonts from HTML (deterministic)
    if result.html:
        colors = _extract_colors_from_html(result.html)
        fonts = _extract_fonts_from_html(result.html)

    # Extract brand voice from markdown (LLM)
    if result.markdown:
        if len(result.markdown) < 2000:
            warning = (
                f"Very short content ({len(result.markdown)} chars) — "
                "page may not have loaded fully. Try re-running."
            )
        try:
            gap_filler = _get_gap_filler_service()
            suggestions = asyncio.run(
                gap_filler.extract_from_raw_content(
                    raw_content=result.markdown,
                    target_fields=["brand.voice_tone"],
                    content_source="fresh_scrape",
                    source_url=url,
                    brand_name=brand_name,
                )
            )
            voice_suggestion = suggestions.get("brand.voice_tone")
            if voice_suggestion and voice_suggestion.get("value"):
                voice = voice_suggestion["value"]
        except Exception as e:
            logger.warning(f"Voice extraction failed: {e}")

    return {"voice": voice, "colors": colors, "fonts": fonts, "warning": warning}


def extract_from_reviews(
    amazon_analysis: Dict,
    target_fields: List[str],
) -> Dict:
    """Extract auto-fill suggestions from Amazon review analysis data.

    Args:
        amazon_analysis: Amazon review analysis dict (from DB).
        target_fields: Fields to extract.

    Returns:
        Suggestions dict keyed by gap_key.
    """
    gap_filler = _get_gap_filler_service()
    return asyncio.run(
        gap_filler.extract_from_amazon_analysis(
            amazon_analysis=amazon_analysis,
            target_fields=target_fields,
        )
    )


def _apply_single(
    gap_key: str,
    value,
    brand_id: str,
    product_id: str,
    offer_variant_id: Optional[str],
    source_url: Optional[str] = None,
    source_type: str = "fresh_scrape",
):
    """Apply a single suggestion via ContentGapFillerService.apply_value().

    Returns the ApplyResult.
    """
    gap_filler = _get_gap_filler_service()
    source_detail = {"source_url": source_url} if source_url else {}
    return gap_filler.apply_value(
        gap_key=gap_key,
        value=value,
        brand_id=brand_id,
        product_id=product_id,
        offer_variant_id=offer_variant_id,
        source_type=source_type,
        source_detail=source_detail,
        force_overwrite=True,  # User explicitly accepted
    )


def _apply_batch(
    items: Dict,
    brand_id: str,
    product_id: str,
    offer_variant_id: Optional[str],
    source_url: Optional[str],
    source_type: str = "fresh_scrape",
) -> Tuple[List[dict], List[str]]:
    """Apply multiple suggestions, collecting undo stack and failures.

    Returns (undo_stack, failed_display_names).
    """
    undo_stack = []
    failed = []
    for gap_key, suggestion in items.items():
        value = suggestion.get("value")
        if value is None:
            continue
        display = _DISPLAY_NAMES.get(gap_key, gap_key)
        try:
            result = _apply_single(
                gap_key, value, brand_id, product_id,
                offer_variant_id, source_url, source_type,
            )
            if result.success:
                undo_stack.append({
                    "gap_key": gap_key,
                    "old_value": result.old_value,
                })
            else:
                failed.append(display)
        except Exception as e:
            logger.error(f"apply_value failed for {gap_key}: {e}")
            failed.append(display)
    return undo_stack, failed


def render_autofill_suggestions(
    suggestions: Dict,
    brand_id: str,
    product_id: str,
    offer_variant_id: Optional[str] = None,
    source_label: str = "LP",
    widget_prefix: str = "bm_af",
    source_url: Optional[str] = None,
    source_type: str = "fresh_scrape",
):
    """Render the auto-fill suggestion review UI for Brand Manager.

    Args:
        suggestions: Dict keyed by gap_key with suggestion dicts.
        brand_id: Brand UUID string.
        product_id: Product UUID string.
        offer_variant_id: Optional offer variant UUID string.
        source_label: "LP" or "Reviews" for display.
        widget_prefix: Unique prefix for widget keys.
        source_url: Source URL for provenance tracking.
        source_type: Provenance source type (default "fresh_scrape").
    """
    if not suggestions:
        st.info("No suggestions found.")
        return

    # Filter out skipped suggestions
    skipped_key = f"{widget_prefix}_skipped"
    skipped = st.session_state.get(skipped_key, set())
    visible = {k: v for k, v in suggestions.items() if k not in skipped}

    if not visible:
        st.info("All suggestions reviewed.")
        if st.button("Show again", key=f"{widget_prefix}_reset_skipped"):
            st.session_state.pop(skipped_key, None)
            st.rerun()
        return

    # Header with dismiss
    hdr_col, dismiss_col = st.columns([4, 1])
    with hdr_col:
        st.markdown(f"#### Auto-fill Suggestions ({source_label})")
    with dismiss_col:
        if st.button("Dismiss", key=f"{widget_prefix}_dismiss"):
            st.session_state.pop(f"{widget_prefix}_suggestions", None)
            st.session_state.pop(skipped_key, None)
            st.rerun()

    undo_key = f"{widget_prefix}_undo"

    # Accept All High+Medium button
    high_medium = {
        k: v for k, v in visible.items()
        if v.get("confidence") in ("high", "medium")
    }
    if len(high_medium) > 1:
        if st.button(
            f"Accept All High+Medium ({len(high_medium)})",
            key=f"{widget_prefix}_accept_all_{source_label.lower()}",
            type="primary",
        ):
            undo_stack, failed = _apply_batch(
                high_medium, brand_id, product_id,
                offer_variant_id, source_url, source_type,
            )
            st.session_state[undo_key] = undo_stack
            # Clear suggestions after bulk accept
            st.session_state.pop(f"{widget_prefix}_suggestions", None)
            st.session_state.pop(skipped_key, None)
            if failed:
                st.session_state[f"{widget_prefix}_error"] = (
                    f"Applied {len(undo_stack)}, failed: {', '.join(failed)}"
                )
            st.rerun()

    # Per-suggestion rows
    for gap_key, suggestion in visible.items():
        confidence = suggestion.get("confidence", "low")
        icon = _CONF_ICONS.get(confidence, "")
        value = suggestion.get("value")
        display_name = _DISPLAY_NAMES.get(gap_key, gap_key)

        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"{icon} **{display_name}** ({confidence})")
            if isinstance(value, list):
                for item in value[:8]:
                    if isinstance(item, dict):
                        parts = [str(v) for v in item.values() if v]
                        st.caption(f"- {' -- '.join(parts[:2])}")
                    else:
                        st.caption(f"- {str(item)[:120]}")
                if len(value) > 8:
                    st.caption(f"_...and {len(value) - 8} more_")
            elif isinstance(value, str) and len(value) > 120:
                st.caption(value[:120] + "...")
            else:
                st.caption(str(value) if value else "_empty_")
            if suggestion.get("keyword_warning"):
                st.warning(suggestion["keyword_warning"])
        with col2:
            if st.button("Accept", key=f"{widget_prefix}_accept_{gap_key}_{source_label.lower()}"):
                if value is not None:
                    try:
                        result = _apply_single(
                            gap_key, value, brand_id, product_id,
                            offer_variant_id, source_url, source_type,
                        )
                        if result.success:
                            st.session_state[undo_key] = [{
                                "gap_key": gap_key,
                                "old_value": result.old_value,
                            }]
                            # Remove accepted from visible
                            skipped_set = st.session_state.setdefault(skipped_key, set())
                            skipped_set.add(gap_key)
                            st.rerun()
                        else:
                            st.error(f"Failed: {result.action}")
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col3:
            if st.button("Skip", key=f"{widget_prefix}_skip_{gap_key}_{source_label.lower()}"):
                skipped_set = st.session_state.setdefault(skipped_key, set())
                skipped_set.add(gap_key)
                st.rerun()

    # Undo button
    if undo_key in st.session_state and st.session_state[undo_key]:
        if st.button("Undo last accept", key=f"{widget_prefix}_undo_btn_{source_label.lower()}"):
            for entry in st.session_state[undo_key]:
                try:
                    _apply_single(
                        entry["gap_key"],
                        entry["old_value"],
                        brand_id,
                        product_id,
                        offer_variant_id,
                        source_url,
                        source_type,
                    )
                except Exception as e:
                    logger.error(f"Undo failed for {entry['gap_key']}: {e}")
            st.session_state.pop(undo_key, None)
            st.success("Undone!")
            st.rerun()
