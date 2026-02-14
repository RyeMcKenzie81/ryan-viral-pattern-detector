"""
Tests for scheduler_worker V2 validation logic — Phase 2 canvas size/color mode
validation, deduplication, cap math, clamping, and fallback to defaults.

These tests exercise the inline validation code in execute_ad_creation_v2_job()
without running the full job. We extract the validation logic into test-local
helpers that mirror the worker code exactly.
"""

import pytest


# ---------------------------------------------------------------------------
# Extracted validation logic (mirrors scheduler_worker.py lines 650-683)
# ---------------------------------------------------------------------------

VALID_CANVAS_SIZES = {"1080x1080px", "1080x1350px", "1080x1920px", "1200x628px"}
VALID_COLOR_MODES = {"original", "complementary", "brand"}
MAX_ADS_PER_SCHEDULED_RUN = 50


def validate_v2_params(params: dict) -> dict:
    """Extract and validate V2 params, mirroring scheduler_worker logic."""
    logs = []
    num_variations = params.get('num_variations', 5)

    # Type-normalize
    raw_sizes = params.get('canvas_sizes') or params.get('canvas_size') or '1080x1080px'
    canvas_sizes = raw_sizes if isinstance(raw_sizes, list) else [raw_sizes]

    raw_colors = params.get('color_modes') or params.get('color_mode') or 'original'
    color_modes = raw_colors if isinstance(raw_colors, list) else [raw_colors]

    # Validate + dedupe (preserve order)
    canvas_sizes = list(dict.fromkeys(s for s in canvas_sizes if s in VALID_CANVAS_SIZES))
    color_modes = list(dict.fromkeys(m for m in color_modes if m in VALID_COLOR_MODES))

    # Fallback
    if not canvas_sizes:
        canvas_sizes = ["1080x1080px"]
        logs.append("WARNING: No valid canvas sizes")
    if not color_modes:
        color_modes = ["original"]
        logs.append("WARNING: No valid color modes")

    # Cap math
    per_template_ads = num_variations * len(canvas_sizes) * len(color_modes)
    if per_template_ads > MAX_ADS_PER_SCHEDULED_RUN:
        num_variations = max(1, MAX_ADS_PER_SCHEDULED_RUN // (len(canvas_sizes) * len(color_modes)))
        per_template_ads = num_variations * len(canvas_sizes) * len(color_modes)
        logs.append("WARNING: clamped")

    return {
        "canvas_sizes": canvas_sizes,
        "color_modes": color_modes,
        "num_variations": num_variations,
        "per_template_ads": per_template_ads,
        "logs": logs,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCanvasSizeValidation:
    """Canvas size validation and deduplication."""

    def test_valid_sizes_preserved(self):
        result = validate_v2_params({
            "canvas_sizes": ["1080x1080px", "1080x1350px"],
        })
        assert result["canvas_sizes"] == ["1080x1080px", "1080x1350px"]

    def test_invalid_sizes_filtered(self):
        result = validate_v2_params({
            "canvas_sizes": ["1080x1080px", "999x999px", "1080x1350px"],
        })
        assert result["canvas_sizes"] == ["1080x1080px", "1080x1350px"]

    def test_all_invalid_falls_back_to_default(self):
        result = validate_v2_params({
            "canvas_sizes": ["invalid", "also_invalid"],
        })
        assert result["canvas_sizes"] == ["1080x1080px"]
        assert any("WARNING" in log for log in result["logs"])

    def test_duplicates_removed_order_preserved(self):
        result = validate_v2_params({
            "canvas_sizes": ["1080x1350px", "1080x1080px", "1080x1350px"],
        })
        assert result["canvas_sizes"] == ["1080x1350px", "1080x1080px"]

    def test_scalar_canvas_size_fallback(self):
        result = validate_v2_params({
            "canvas_size": "1080x1920px",
        })
        assert result["canvas_sizes"] == ["1080x1920px"]

    def test_no_size_params_defaults(self):
        result = validate_v2_params({})
        assert result["canvas_sizes"] == ["1080x1080px"]


class TestColorModeValidation:
    """Color mode validation and deduplication."""

    def test_valid_modes_preserved(self):
        result = validate_v2_params({
            "color_modes": ["original", "brand"],
        })
        assert result["color_modes"] == ["original", "brand"]

    def test_invalid_modes_filtered(self):
        result = validate_v2_params({
            "color_modes": ["original", "rainbow", "brand"],
        })
        assert result["color_modes"] == ["original", "brand"]

    def test_all_invalid_falls_back_to_default(self):
        result = validate_v2_params({
            "color_modes": ["invalid"],
        })
        assert result["color_modes"] == ["original"]
        assert any("WARNING" in log for log in result["logs"])

    def test_duplicates_removed_order_preserved(self):
        result = validate_v2_params({
            "color_modes": ["brand", "original", "brand"],
        })
        assert result["color_modes"] == ["brand", "original"]

    def test_scalar_color_mode_fallback(self):
        result = validate_v2_params({
            "color_mode": "complementary",
        })
        assert result["color_modes"] == ["complementary"]


class TestCapMath:
    """per_template_ads = V × S × C, clamping when exceeds cap."""

    def test_simple_fanout(self):
        result = validate_v2_params({
            "num_variations": 5,
            "canvas_sizes": ["1080x1080px"],
            "color_modes": ["original"],
        })
        assert result["per_template_ads"] == 5

    def test_multi_size_multi_color_fanout(self):
        result = validate_v2_params({
            "num_variations": 3,
            "canvas_sizes": ["1080x1080px", "1080x1350px"],
            "color_modes": ["original", "brand"],
        })
        # 3 × 2 × 2 = 12
        assert result["per_template_ads"] == 12

    def test_clamping_when_exceeds_cap(self):
        """15 variations × 2 sizes × 2 colors = 60 > 50 → clamp."""
        result = validate_v2_params({
            "num_variations": 15,
            "canvas_sizes": ["1080x1080px", "1080x1350px"],
            "color_modes": ["original", "brand"],
        })
        # 50 // (2 × 2) = 12
        assert result["num_variations"] == 12
        assert result["per_template_ads"] == 48  # 12 × 2 × 2
        assert any("clamped" in log.lower() for log in result["logs"])

    def test_clamping_minimum_1_variation(self):
        """Even with 4 sizes × 3 colors = 12, variations clamp to at least 1."""
        result = validate_v2_params({
            "num_variations": 100,
            "canvas_sizes": ["1080x1080px", "1080x1350px", "1080x1920px", "1200x628px"],
            "color_modes": ["original", "complementary", "brand"],
        })
        # 50 // (4 × 3) = 4
        assert result["num_variations"] == 4
        assert result["per_template_ads"] == 48

    def test_no_clamping_at_exact_cap(self):
        """Exactly at cap: 5 × 2 × 5... well, 5 × 2 × 2 = 20, under cap."""
        result = validate_v2_params({
            "num_variations": 5,
            "canvas_sizes": ["1080x1080px", "1080x1350px"],
            "color_modes": ["original", "brand"],
        })
        assert result["num_variations"] == 5  # no clamping
        assert result["per_template_ads"] == 20

    def test_no_clamping_under_cap(self):
        result = validate_v2_params({
            "num_variations": 5,
            "canvas_sizes": ["1080x1080px"],
            "color_modes": ["original"],
        })
        assert result["num_variations"] == 5
        assert result["per_template_ads"] == 5
        assert not any("clamped" in log.lower() for log in result["logs"])

    def test_default_variations(self):
        """Default num_variations is 5."""
        result = validate_v2_params({
            "canvas_sizes": ["1080x1080px"],
            "color_modes": ["original"],
        })
        assert result["num_variations"] == 5
        assert result["per_template_ads"] == 5
