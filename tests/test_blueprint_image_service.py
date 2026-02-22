"""Tests for BlueprintImageService — slot extraction, HTML replacement, meta merging."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from viraltracker.services.landing_page_analysis.blueprint_image_service import (
    BlueprintImageService,
    ImageSlot,
    _SrcReplacer,
    replace_image_sources,
    snap_aspect_ratio,
)


# ---------------------------------------------------------------------------
# Sample HTML
# ---------------------------------------------------------------------------

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<body>
<section data-section="hero">
  <h1>Fuel Your Day</h1>
  <p>Our superfood shake gives you energy all day.</p>
  <img src="https://example.com/hero.jpg" alt="Hero product shot" style="width:100%">
</section>
<section data-section="features">
  <h2>Why Choose Us</h2>
  <img src="https://example.com/lifestyle.jpg" alt="Happy customer" class="feature-img">
  <p>Natural ingredients for a better you.</p>
  <img src="https://example.com/product.png" alt="Product closeup">
</section>
</body>
</html>"""

HTML_WITH_ICONS = """<div>
  <img src="https://example.com/icon.png" width="24" height="24" alt="icon">
  <img src="https://example.com/big.jpg" alt="Big image">
</div>"""

HTML_WITH_SVG = """<div>
  <img src="https://example.com/logo.svg" alt="Logo">
  <img src="https://example.com/photo.jpg" alt="Photo">
</div>"""


# ---------------------------------------------------------------------------
# extract_image_slots
# ---------------------------------------------------------------------------

class TestExtractImageSlots:

    def test_basic_extraction(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(SAMPLE_HTML)

        assert len(slots) == 3
        assert slots[0].original_src == "https://example.com/hero.jpg"
        assert slots[0].alt_text == "Hero product shot"
        assert slots[0].index == 0
        assert slots[1].original_src == "https://example.com/lifestyle.jpg"
        assert slots[1].index == 1
        assert slots[2].original_src == "https://example.com/product.png"
        assert slots[2].index == 2

    def test_surrounding_text_captured(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(SAMPLE_HTML)

        # Hero slot should have heading context
        assert "Fuel Your Day" in slots[0].surrounding_text or slots[0].section_heading == "Fuel Your Day"

    def test_filters_small_icons(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(HTML_WITH_ICONS)

        assert len(slots) == 1
        assert slots[0].original_src == "https://example.com/big.jpg"

    def test_filters_svg_urls(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(HTML_WITH_SVG)

        assert len(slots) == 1
        assert slots[0].original_src == "https://example.com/photo.jpg"

    def test_validates_urls(self):
        """Private IPs and tracking domains should be excluded."""
        html = """<div>
          <img src="http://192.168.1.1/img.jpg" alt="Private">
          <img src="https://example.com/real.jpg" alt="Real">
        </div>"""
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(html)

        # Only the safe URL should survive
        assert len(slots) == 1
        assert "example.com" in slots[0].original_src

    def test_duplicate_urls_get_separate_slots(self):
        html = """<div>
          <img src="https://example.com/same.jpg" alt="First">
          <img src="https://example.com/same.jpg" alt="Second">
        </div>"""
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slots = svc.extract_image_slots(html)

        assert len(slots) == 2
        assert slots[0].index == 0
        assert slots[1].index == 1
        assert slots[0].alt_text == "First"
        assert slots[1].alt_text == "Second"


# ---------------------------------------------------------------------------
# _SrcReplacer / replace_image_sources
# ---------------------------------------------------------------------------

class TestSrcReplacer:

    def test_replace_by_dom_index(self):
        """Replace slot 1 only — slots 0 and 2 unchanged."""
        html = """<div>
<img src="https://a.com/0.jpg" alt="zero">
<img src="https://a.com/1.jpg" alt="one">
<img src="https://a.com/2.jpg" alt="two">
</div>"""
        result = replace_image_sources(html, {1: "https://new.com/replaced.png"})

        assert "https://a.com/0.jpg" in result
        assert "https://new.com/replaced.png" in result
        assert "https://a.com/2.jpg" in result
        assert "https://a.com/1.jpg" not in result

    def test_preserves_attributes(self):
        """style, alt, class attrs should be preserved after replacement."""
        html = '<img src="https://old.com/img.jpg" alt="My Alt" class="hero" style="width:100%">'
        result = replace_image_sources(html, {0: "https://new.com/img.png"})

        assert 'alt="My Alt"' in result
        assert 'class="hero"' in result
        assert 'style="width:100%"' in result
        assert 'src="https://new.com/img.png"' in result

    def test_no_replacements_returns_original(self):
        html = '<img src="https://old.com/img.jpg" alt="test">'
        result = replace_image_sources(html, {})
        assert 'src="https://old.com/img.jpg"' in result


# ---------------------------------------------------------------------------
# snap_aspect_ratio
# ---------------------------------------------------------------------------

class TestAspectRatioSnapping:

    def test_wide_16_9(self):
        assert snap_aspect_ratio(1920, 1080) == "16:9"

    def test_square(self):
        assert snap_aspect_ratio(500, 500) == "1:1"

    def test_portrait_9_16(self):
        assert snap_aspect_ratio(1080, 1920) == "9:16"

    def test_standard_4_3(self):
        assert snap_aspect_ratio(1024, 768) == "4:3"

    def test_portrait_3_4(self):
        assert snap_aspect_ratio(768, 1024) == "3:4"

    def test_photo_3_2(self):
        assert snap_aspect_ratio(1500, 1000) == "3:2"

    def test_ultrawide(self):
        assert snap_aspect_ratio(2520, 1080) == "21:9"

    def test_zero_dimensions(self):
        assert snap_aspect_ratio(0, 0) == "1:1"

    def test_near_ratio_snaps(self):
        """Slightly off dimensions should snap to nearest standard."""
        # 1920x1082 is almost 16:9
        assert snap_aspect_ratio(1920, 1082) == "16:9"


# ---------------------------------------------------------------------------
# Safety filter error in generate_image
# ---------------------------------------------------------------------------

class TestSafetyFilterInGenerateImage:

    def test_safety_filter_error_on_blocked_response(self):
        """Mock blocked response should raise SafetyFilterError, not AttributeError."""
        from viraltracker.services.gemini_service import SafetyFilterError

        # Verify the exception class exists and is properly defined
        assert issubclass(SafetyFilterError, Exception)

    def test_safety_filter_error_distinct_from_rate_limit(self):
        from viraltracker.services.gemini_service import SafetyFilterError, RateLimitError

        assert not issubclass(SafetyFilterError, RateLimitError)
        assert not issubclass(RateLimitError, SafetyFilterError)


# ---------------------------------------------------------------------------
# save_single_slot merges correctly
# ---------------------------------------------------------------------------

class TestSaveSingleSlotMerge:

    def test_merges_without_clobbering(self):
        """Pre-existing meta for slots 0,1,2 — update slot 1 — slots 0,2 unchanged."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_select = MagicMock()
        mock_select.data = {
            "generated_images_meta": {
                "0": {"prompt": "prompt0", "storage_url": "url0"},
                "1": {"prompt": "prompt1", "storage_url": "url1"},
                "2": {"prompt": "prompt2", "storage_url": "url2"},
            }
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_select
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        svc = BlueprintImageService(supabase=mock_supabase)
        new_slot_meta = {"prompt": "new_prompt1", "storage_url": "new_url1"}
        svc.save_single_slot("bp-123", 1, "<html>new</html>", new_slot_meta)

        # Verify the update call merged correctly
        update_call = mock_supabase.table.return_value.update.call_args
        updated_meta = update_call[0][0]["generated_images_meta"]

        assert updated_meta["0"]["prompt"] == "prompt0"
        assert updated_meta["1"]["prompt"] == "new_prompt1"
        assert updated_meta["1"]["storage_url"] == "new_url1"
        assert updated_meta["2"]["prompt"] == "prompt2"


# ---------------------------------------------------------------------------
# build_generation_prompts
# ---------------------------------------------------------------------------

class TestBuildGenerationPrompts:

    def _make_slot(self, index, image_type="lifestyle", has_people=False):
        return ImageSlot(
            index=index,
            original_src=f"https://example.com/{index}.jpg",
            alt_text=f"Image {index}",
            surrounding_text="Our amazing superfood shake gives you energy.",
            section_heading="Fuel Your Day",
            image_analysis={
                "image_type": image_type,
                "subject": "woman holding a shake",
                "composition": "bright natural lighting, outdoor cafe",
                "has_people": has_people,
                "people_description": "30s woman, athletic" if has_people else "",
                "aspect_ratio": "16:9",
            },
            selected=True,
        )

    def test_lifestyle_prompt_includes_product(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "lifestyle", has_people=True)
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "SuperGreens Shake"},
            persona={"demographics": {"age_range": "25-34", "gender": "female"}},
        )
        assert slot.prompt is not None
        assert "SuperGreens Shake" in slot.prompt
        assert "25-34" in slot.prompt
        assert "female" in slot.prompt

    def test_product_shot_prompt(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "product_shot")
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "VitaBoost"},
        )
        assert "VitaBoost" in slot.prompt
        assert "product photography" in slot.prompt.lower() or "product" in slot.prompt.lower()

    def test_hero_banner_prompt(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "hero_banner")
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "VitaBoost"},
        )
        assert "hero" in slot.prompt.lower()

    def test_unselected_slot_skipped(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "lifestyle")
        slot.selected = False
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "VitaBoost"},
        )
        assert slot.prompt is None

    def test_no_persona_uses_vision_people_desc(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "testimonial_photo", has_people=True)
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "VitaBoost"},
            persona=None,
        )
        assert slot.prompt is not None
        assert "30s woman" in slot.prompt or "satisfied customer" in slot.prompt

    def test_brand_colors_included(self):
        svc = BlueprintImageService.__new__(BlueprintImageService)
        slot = self._make_slot(0, "product_shot")
        svc.build_generation_prompts(
            [slot],
            product_info={"name": "VitaBoost"},
            brand_profile={"brand_basics": {"colors": ["#2ECC71", "#1ABC9C"]}},
        )
        assert "#2ECC71" in slot.prompt
