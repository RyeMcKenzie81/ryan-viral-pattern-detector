"""
Export utilities — session-based export list + ZIP creation.

Functions copied from Ad History (22_Ad_History.py) for reuse;
originals left in place to avoid regression risk.
"""

import io
import logging
import re
import zipfile

import requests
import streamlit as st

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def get_export_list() -> list:
    """Return the current export list from session state."""
    return st.session_state.get("export_ads", [])


def get_export_count() -> int:
    """Return number of items in the export list."""
    return len(get_export_list())


# ---------------------------------------------------------------------------
# Filename helpers (copied from Ad History)
# ---------------------------------------------------------------------------

def get_signed_url(storage_path: str, expiry: int = 3600) -> str:
    """Get a signed URL for a Supabase storage path."""
    if not storage_path:
        return ""
    try:
        from viraltracker.core.database import get_supabase_client
        db = get_supabase_client()
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "generated-ads"
            path = storage_path
        result = db.storage.from_(bucket).create_signed_url(path, expiry)
        return result.get('signedURL', '')
    except Exception:
        return ""


def get_format_code_from_spec(prompt_spec: dict) -> str:
    """Determine format code from prompt_spec canvas dimensions."""
    if not prompt_spec:
        return "SQ"

    canvas = prompt_spec.get("canvas", {})
    dimensions = canvas.get("dimensions", "")

    match = re.search(r'(\d+)\s*x\s*(\d+)', dimensions.lower())
    if not match:
        return "SQ"

    width = int(match.group(1))
    height = int(match.group(2))
    ratio = width / height if height > 0 else 1

    if 0.95 <= ratio <= 1.05:
        return "SQ"
    elif ratio < 0.7:
        if ratio < 0.65:
            return "ST"  # Story (9:16)
        else:
            return "PT"  # Portrait (4:5)
    else:
        return "LS"


def generate_structured_filename(brand_code: str, product_code: str, run_id: str,
                                  ad_id: str, format_code: str, ext: str = "png",
                                  language: str | None = None) -> str:
    """Generate structured filename like WP-C3-a1b2c3-d4e5f6-SQ.png
    Non-English ads get a language suffix: WP-C3-a1b2c3-d4e5f6-SQ-ES.png"""
    run_short = run_id.replace("-", "")[:6]
    ad_short = ad_id.replace("-", "")[:6]
    bc = (brand_code or "XX").upper()
    pc = (product_code or "XX").upper()
    lang_suffix = ""
    if language and language.lower() not in ("en", "english"):
        lang_suffix = f"-{language.split('-')[0].upper()}"
    return f"{bc}-{pc}-{run_short}-{ad_short}-{format_code}{lang_suffix}.{ext}"


# ---------------------------------------------------------------------------
# ZIP creation from export list
# ---------------------------------------------------------------------------

def create_zip_from_export_list(items: list, zip_name: str = "export") -> bytes:
    """
    Create a ZIP file from export list items.

    Each item is a dict with keys:
        storage_path, brand_code, product_code, run_id, ad_id,
        format_code, ext (all strings)

    Returns ZIP file bytes.
    """
    zip_buffer = io.BytesIO()
    seen_filenames = {}

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            storage_path = item.get("storage_path", "")
            if not storage_path:
                continue

            url = get_signed_url(storage_path)
            if not url:
                continue

            try:
                response = requests.get(url, timeout=30)
                if response.status_code != 200:
                    continue

                # Detect extension from content-type
                ct = response.headers.get('content-type', '')
                ext = item.get("ext", "png")
                if "jpeg" in ct:
                    ext = "jpg"
                elif "webp" in ct:
                    ext = "webp"

                filename = generate_structured_filename(
                    brand_code=item.get("brand_code", "XX"),
                    product_code=item.get("product_code", "XX"),
                    run_id=item.get("run_id", "000000"),
                    ad_id=item.get("ad_id", "000000"),
                    format_code=item.get("format_code", "SQ"),
                    ext=ext,
                )

                # Deduplicate filenames
                if filename in seen_filenames:
                    seen_filenames[filename] += 1
                    base, dot_ext = filename.rsplit(".", 1)
                    filename = f"{base}_{seen_filenames[filename]}.{dot_ext}"
                else:
                    seen_filenames[filename] = 0

                zf.writestr(filename, response.content)
            except Exception:
                continue

    zip_buffer.seek(0)
    return zip_buffer.getvalue()
