"""Automated visual fidelity check: compare original screenshot to output screenshot.

Usage:
    python scripts/visual_fidelity_check.py \
        --original screenshot.png \
        --output output.html \
        --section-map section_boxes.json \
        --page-height 4000

Args:
    --original: Full-page screenshot from FireCrawl scrape
    --output: Generated HTML file to render and compare
    --section-map: JSON file with section bounding boxes from Phase 1
                   Format (fractional, matching NormalizedBox):
                   {"sec_0": {"top": 0.0, "left": 0.0, "width": 1.0, "height": 0.15}, ...}
    --page-height: Original page height in pixels (from screenshot dimensions)
"""

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

THRESHOLDS = {
    "full_page_ssim": 0.60,
    "section_ssim_min": 0.45,
    "section_ssim_avg": 0.55,
}

VIEWPORT_WIDTH = 1280


def load_and_render(html_path: str) -> np.ndarray:
    """Render HTML file to screenshot using Playwright."""
    from playwright.sync_api import sync_playwright

    # Restore background images before rendering
    html_content = Path(html_path).read_text(encoding="utf-8")
    try:
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            restore_background_images,
        )
        html_content = restore_background_images(html_content)
    except ImportError:
        pass

    # Write display-ready HTML to temp file
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False, encoding="utf-8") as f:
        f.write(html_content)
        temp_path = f.name

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": VIEWPORT_WIDTH, "height": 800})
        page.goto(f"file://{temp_path}")
        page.wait_for_load_state("networkidle")

        screenshot_bytes = page.screenshot(full_page=True)
        browser.close()

    Path(temp_path).unlink(missing_ok=True)

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(screenshot_bytes))
    return np.array(img.convert("RGB"))


def load_image(path: str) -> np.ndarray:
    """Load image file as numpy array."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    return np.array(img)


def compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Compute SSIM between two images, resizing to match dimensions."""
    from skimage.metrics import structural_similarity
    from PIL import Image

    # Resize img2 to match img1 dimensions
    if img1.shape != img2.shape:
        pil_img2 = Image.fromarray(img2)
        pil_img2 = pil_img2.resize((img1.shape[1], img1.shape[0]), Image.Resampling.LANCZOS)
        img2 = np.array(pil_img2)

    return structural_similarity(img1, img2, channel_axis=2)


def crop_region(img: np.ndarray, box: dict, page_height: int) -> np.ndarray:
    """Crop an image using fractional bounding box."""
    top = int(box["top"] * page_height)
    left = int(box["left"] * VIEWPORT_WIDTH)
    width = int(box["width"] * VIEWPORT_WIDTH)
    height = int(box["height"] * page_height)

    # Clamp to image bounds
    img_h, img_w = img.shape[:2]
    top = min(top, img_h - 1)
    left = min(left, img_w - 1)
    bottom = min(top + height, img_h)
    right = min(left + width, img_w)

    if bottom <= top or right <= left:
        return img[0:1, 0:1]  # Return tiny crop to avoid errors

    return img[top:bottom, left:right]


def main():
    parser = argparse.ArgumentParser(description="Visual fidelity check")
    parser.add_argument("--original", required=True, help="Original screenshot path")
    parser.add_argument("--output", required=True, help="Generated HTML file path")
    parser.add_argument("--section-map", help="Section bounding boxes JSON path")
    parser.add_argument("--page-height", type=int, help="Original page height in pixels")
    args = parser.parse_args()

    print("Loading original screenshot...")
    original = load_image(args.original)
    page_height = args.page_height or original.shape[0]

    print("Rendering output HTML...")
    rendered = load_and_render(args.output)

    # Full-page SSIM
    print("Computing full-page SSIM...")
    full_ssim = compute_ssim(original, rendered)
    full_pass = full_ssim >= THRESHOLDS["full_page_ssim"]
    print(f"Full-page SSIM: {full_ssim:.4f} (threshold: {THRESHOLDS['full_page_ssim']}) {'PASS' if full_pass else 'FAIL'}")

    # Per-section SSIM
    section_pass = True
    avg_pass = True
    if args.section_map:
        print("\nComputing per-section SSIM...")
        with open(args.section_map) as f:
            section_map = json.load(f)

        section_ssims = {}
        for sec_id, box in sorted(section_map.items()):
            orig_crop = crop_region(original, box, page_height)
            rend_crop = crop_region(rendered, box, page_height)
            ssim = compute_ssim(orig_crop, rend_crop)
            section_ssims[sec_id] = ssim
            status = "PASS" if ssim >= THRESHOLDS["section_ssim_min"] else "FAIL"
            print(f"  {sec_id}: {ssim:.4f} {status}")

        if section_ssims:
            avg_ssim = sum(section_ssims.values()) / len(section_ssims)
            min_ssim = min(section_ssims.values())
            min_section = min(section_ssims, key=section_ssims.get)

            avg_pass = avg_ssim >= THRESHOLDS["section_ssim_avg"]
            min_pass = min_ssim >= THRESHOLDS["section_ssim_min"]
            section_pass = avg_pass and min_pass

            print(f"\n  Average: {avg_ssim:.4f} (threshold: {THRESHOLDS['section_ssim_avg']}) {'PASS' if avg_pass else 'FAIL'}")
            print(f"  Min ({min_section}): {min_ssim:.4f} (threshold: {THRESHOLDS['section_ssim_min']}) {'PASS' if min_pass else 'FAIL'}")

    # Verdict
    overall_pass = full_pass and section_pass
    print(f"\nVERDICT: {'PASS' if overall_pass else 'FAIL'}")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
