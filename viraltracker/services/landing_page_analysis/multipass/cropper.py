"""Section cropping with bounding box normalization.

Primary: Phase 1 model-produced bounding boxes, normalized.
Fallback: Char-ratio from segmenter.
Both: PIL img.crop() with 5% overlap padding, 2MB per-crop size cap.
"""

import io
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

OVERLAP_PADDING = 0.05  # 5% overlap on each side
MAX_CROP_BYTES = 2 * 1024 * 1024  # 2MB per crop


@dataclass
class NormalizedBox:
    """A normalized bounding box for a section."""
    section_id: str
    name: str
    y_start_pct: float  # 0.0 - 1.0
    y_end_pct: float    # 0.0 - 1.0


def normalize_bounding_boxes(
    boxes: List[Dict],
) -> Optional[List[NormalizedBox]]:
    """Deterministic normalization of model-produced bounding boxes.

    Guarantees valid, sorted, non-overlapping, full-coverage boxes.

    Args:
        boxes: List of dicts with 'section_id', 'name', 'y_start_pct', 'y_end_pct'.

    Returns:
        List of NormalizedBox, or None if boxes are too broken (< 2 valid
        boxes or < 80% coverage), signaling char-ratio fallback.
    """
    if not boxes:
        return None

    # Step 1: Clamp all values to [0.0, 1.0]
    for box in boxes:
        box['y_start_pct'] = max(0.0, min(1.0, float(box.get('y_start_pct', 0))))
        box['y_end_pct'] = max(0.0, min(1.0, float(box.get('y_end_pct', 0))))

    # Step 2: Enforce y_start < y_end (swap if inverted, discard if equal)
    valid = []
    for b in boxes:
        if b['y_start_pct'] > b['y_end_pct']:
            b['y_start_pct'], b['y_end_pct'] = b['y_end_pct'], b['y_start_pct']
        if b['y_start_pct'] < b['y_end_pct']:
            valid.append(b)

    if not valid:
        return None

    # Step 3: Sort by y_start ascending
    valid.sort(key=lambda b: b['y_start_pct'])

    # Step 4: Clip overlapping boundaries (preserve section identity)
    clipped = []
    for box in valid:
        if clipped and box['y_start_pct'] < clipped[-1]['y_end_pct']:
            clipped[-1]['y_end_pct'] = box['y_start_pct']
            if clipped[-1]['y_end_pct'] <= clipped[-1]['y_start_pct']:
                clipped.pop()
        clipped.append(dict(box))

    if not clipped:
        return None

    # Step 5: Fill coverage gaps
    if clipped[0]['y_start_pct'] > 0.02:
        clipped[0]['y_start_pct'] = 0.0
    if clipped[-1]['y_end_pct'] < 0.98:
        clipped[-1]['y_end_pct'] = 1.0
    for i in range(len(clipped) - 1):
        gap = clipped[i + 1]['y_start_pct'] - clipped[i]['y_end_pct']
        if gap > 0.01:
            clipped[i]['y_end_pct'] = clipped[i + 1]['y_start_pct']

    # Step 6: Validate
    total_coverage = sum(b['y_end_pct'] - b['y_start_pct'] for b in clipped)
    if len(clipped) < 2 or total_coverage < 0.8:
        return None

    return [
        NormalizedBox(
            section_id=b.get('section_id', f'sec_{i}'),
            name=b.get('name', 'section'),
            y_start_pct=b['y_start_pct'],
            y_end_pct=b['y_end_pct'],
        )
        for i, b in enumerate(clipped)
    ]


def boxes_from_char_ratios(
    sections: List,  # List[SegmenterSection]
) -> List[NormalizedBox]:
    """Build bounding boxes from segmenter char ratios (fallback).

    Args:
        sections: List of SegmenterSection with section_id, name, char_ratio.

    Returns:
        List of NormalizedBox covering 0.0 to 1.0.
    """
    boxes = []
    y_cursor = 0.0
    for sec in sections:
        height = sec.char_ratio
        boxes.append(NormalizedBox(
            section_id=sec.section_id,
            name=sec.name,
            y_start_pct=y_cursor,
            y_end_pct=y_cursor + height,
        ))
        y_cursor += height

    # Ensure last box extends to 1.0
    if boxes:
        boxes[-1].y_end_pct = 1.0

    return boxes


def crop_section(
    image_bytes: bytes,
    box: NormalizedBox,
    add_overlap: bool = True,
) -> bytes:
    """Crop a section from the full-page screenshot.

    Args:
        image_bytes: Full screenshot as bytes (PNG/JPEG).
        box: Normalized bounding box for this section.
        add_overlap: Whether to add 5% overlap padding on each side.

    Returns:
        Cropped image as PNG bytes, capped at MAX_CROP_BYTES.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size

    y_start = box.y_start_pct
    y_end = box.y_end_pct

    if add_overlap:
        y_start = max(0.0, y_start - OVERLAP_PADDING)
        y_end = min(1.0, y_end + OVERLAP_PADDING)

    top = int(y_start * height)
    bottom = int(y_end * height)

    # Ensure minimum crop height of 10px
    if bottom - top < 10:
        bottom = min(height, top + 10)

    cropped = img.crop((0, top, width, bottom))

    # Convert to PNG bytes
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    # Size cap: reduce quality if too large
    if len(png_bytes) > MAX_CROP_BYTES:
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=75)
        png_bytes = buf.getvalue()

    if len(png_bytes) > MAX_CROP_BYTES:
        # Last resort: resize
        scale = (MAX_CROP_BYTES / len(png_bytes)) ** 0.5
        new_size = (int(cropped.width * scale), int(cropped.height * scale))
        cropped = cropped.resize(new_size)
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=70)
        png_bytes = buf.getvalue()

    return png_bytes
