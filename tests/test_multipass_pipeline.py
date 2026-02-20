"""Tests for the multipass mockup generation pipeline.

~45 tests covering:
- PatchApplier (7 tests)
- Bounding box normalization (6 tests)
- Per-section invariants (7 tests)
- Segmenter + Reconciliation (7 tests)
- Cropper (4 tests)
- PopupFilter (4 tests)
- Pipeline integration (9 tests, mocked Gemini)
- Eval harness (5 tests)
"""

import asyncio
import base64
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# PatchApplier tests
# ---------------------------------------------------------------------------


class TestPatchApplierSelector:
    """Test restricted selector grammar parsing."""

    def test_attr_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector("[data-section='sec_0']")
        assert s.attr_name == "data-section"
        assert s.attr_value == "sec_0"
        assert s.tag is None

    def test_class_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector(".feature-grid")
        assert s.class_name == "feature-grid"
        assert s.tag is None

    def test_id_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector("#sec-0-heading")
        assert s.id == "sec-0-heading"

    def test_tag_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector("section")
        assert s.tag == "section"

    def test_tag_class_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector("div.trust-logos")
        assert s.tag == "div"
        assert s.class_name == "trust-logos"

    def test_tag_attr_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        s = parse_selector("section[data-section='sec_2']")
        assert s.tag == "section"
        assert s.attr_name == "data-section"
        assert s.attr_value == "sec_2"

    def test_unsupported_selector_raises(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            parse_selector,
        )

        with pytest.raises(ValueError, match="Unsupported selector"):
            parse_selector("div > span")

        with pytest.raises(ValueError, match="Unsupported selector"):
            parse_selector(":hover")

        with pytest.raises(ValueError, match="Unsupported selector"):
            parse_selector("div span.foo")


class TestPatchApplierApplication:
    """Test patch application behavior."""

    def test_css_fix_applies_style(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<section data-section="sec_0"><p>Hello</p></section>'
        patches = [
            {
                "type": "css_fix",
                "selector": "[data-section='sec_0']",
                "value": "background-color: red;",
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert 'background-color: red' in result

    def test_add_element_inserts(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<section data-section="sec_0"><p>Hello</p></section>'
        patches = [
            {
                "type": "add_element",
                "selector": "[data-section='sec_0']",
                "value": '<div style="height: 2px; background: #ddd;"></div>',
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert '<div style="height: 2px; background: #ddd;">' in result

    def test_add_element_rejects_visible_text(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<section data-section="sec_0"><p>Hello</p></section>'
        patches = [
            {
                "type": "add_element",
                "selector": "[data-section='sec_0']",
                "value": "<p>Injected text!</p>",
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert "Injected text" not in result

    def test_remove_element_removes(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<div><div class="overlay-popup">popup content</div><p>real</p></div>'
        patches = [
            {
                "type": "remove_element",
                "selector": ".overlay-popup",
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert "overlay-popup" not in result
        assert "real" in result

    def test_skip_non_matching_selector(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<section data-section="sec_0"><p>Hello</p></section>'
        patches = [
            {
                "type": "css_fix",
                "selector": ".nonexistent",
                "value": "color: red;",
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert result == html  # Unchanged

    def test_never_modifies_data_slot(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<p data-slot="headline" class="title">Hello</p>'
        patches = [
            {
                "type": "css_fix",
                "selector": ".title",
                "value": "color: red;",
            }
        ]
        result = PatchApplier().apply_patches(html, patches)
        assert 'data-slot="headline"' in result
        assert 'color: red' in result


# ---------------------------------------------------------------------------
# Bounding box normalization tests
# ---------------------------------------------------------------------------


class TestBoundingBoxNormalization:
    """Test bounding box normalization."""

    def test_clamp_values(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        boxes = [
            {"section_id": "sec_0", "name": "a", "y_start_pct": -0.1, "y_end_pct": 0.5},
            {"section_id": "sec_1", "name": "b", "y_start_pct": 0.5, "y_end_pct": 1.2},
        ]
        result = normalize_bounding_boxes(boxes)
        assert result is not None
        assert result[0].y_start_pct == 0.0
        assert result[-1].y_end_pct == 1.0

    def test_sort_by_y_start(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        boxes = [
            {"section_id": "sec_1", "name": "b", "y_start_pct": 0.5, "y_end_pct": 1.0},
            {"section_id": "sec_0", "name": "a", "y_start_pct": 0.0, "y_end_pct": 0.5},
        ]
        result = normalize_bounding_boxes(boxes)
        assert result is not None
        assert result[0].y_start_pct <= result[1].y_start_pct

    def test_swap_inverted_pairs(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        boxes = [
            {"section_id": "sec_0", "name": "a", "y_start_pct": 0.5, "y_end_pct": 0.0},
            {"section_id": "sec_1", "name": "b", "y_start_pct": 0.5, "y_end_pct": 1.0},
        ]
        result = normalize_bounding_boxes(boxes)
        assert result is not None
        assert all(b.y_start_pct < b.y_end_pct for b in result)

    def test_clip_overlapping_boundaries(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        boxes = [
            {"section_id": "sec_0", "name": "a", "y_start_pct": 0.0, "y_end_pct": 0.6},
            {"section_id": "sec_1", "name": "b", "y_start_pct": 0.4, "y_end_pct": 1.0},
        ]
        result = normalize_bounding_boxes(boxes)
        assert result is not None
        # No overlap: first box ends where second begins
        assert result[0].y_end_pct <= result[1].y_start_pct + 0.001

    def test_return_none_for_less_than_2_boxes(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        boxes = [
            {"section_id": "sec_0", "name": "a", "y_start_pct": 0.0, "y_end_pct": 0.1},
        ]
        result = normalize_bounding_boxes(boxes)
        assert result is None

    def test_handle_empty_input(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            normalize_bounding_boxes,
        )

        assert normalize_bounding_boxes([]) is None
        assert normalize_bounding_boxes(None) is None


# ---------------------------------------------------------------------------
# Per-section invariant tests
# ---------------------------------------------------------------------------


class TestInvariants:
    """Test per-section and global invariant checks."""

    SAMPLE_HTML = """
    <section data-section="sec_0">
        <h1 data-slot="headline">Welcome to Our Product</h1>
        <p data-slot="body-1">This is the hero section body text.</p>
    </section>
    <section data-section="sec_1">
        <h2 data-slot="heading-1">Features</h2>
        <p data-slot="body-2">Feature description text here.</p>
    </section>
    """

    def test_capture_per_section_slots(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)
        assert "sec_0" in inv.sections
        assert "headline" in inv.sections["sec_0"].slot_set
        assert "body-1" in inv.sections["sec_0"].slot_set

    def test_capture_global_slots(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)
        assert "headline" in inv.global_slot_set
        assert "heading-1" in inv.global_slot_set

    def test_detect_removed_slot(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)

        # Remove a slot
        modified = '<h1>Welcome to Our Product</h1><p data-slot="body-1">This is the hero section body text.</p>'
        report = check_section_invariant(modified, "sec_0", inv)
        assert not report.passed
        assert "headline" in report.slot_loss

    def test_detect_text_drift(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)

        # Significantly change text
        modified = '<h1 data-slot="headline">Completely different text here that was hallucinated by the model</h1><p data-slot="body-1">Totally new body content that is very different from original text</p>'
        report = check_section_invariant(modified, "sec_0", inv)
        assert report.text_similarity < 0.85

    def test_pass_when_unchanged(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)
        original = '<h1 data-slot="headline">Welcome to Our Product</h1><p data-slot="body-1">This is the hero section body text.</p>'
        report = check_section_invariant(original, "sec_0", inv)
        assert report.passed

    def test_section_with_no_slots(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )

        html = '<section data-section="sec_0"><p>Just text, no slots</p></section>'
        inv = capture_pipeline_invariants(html)
        assert inv.sections["sec_0"].slot_set == frozenset()

        report = check_section_invariant("<p>Just text, no slots</p>", "sec_0", inv)
        assert report.passed

    def test_global_check_aggregates(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_global_invariants,
        )

        inv = capture_pipeline_invariants(self.SAMPLE_HTML)
        report = check_global_invariants(self.SAMPLE_HTML, inv)
        assert report.passed
        assert report.text_similarity >= 0.85

    def test_whitespace_normalization(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )

        html = '<section data-section="sec_0"><p data-slot="body-1">Hello   world</p></section>'
        inv = capture_pipeline_invariants(html)

        # Same text with different whitespace
        modified = '<p data-slot="body-1">Hello world</p>'
        report = check_section_invariant(modified, "sec_0", inv)
        assert report.passed


# ---------------------------------------------------------------------------
# Segmenter tests
# ---------------------------------------------------------------------------


class TestSegmenter:
    """Test markdown segmentation."""

    def test_heading_splitting(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        md = "# Hero\nSome intro text.\n\n## Features\nFeature list.\n\n## Pricing\nPricing info."
        sections = segment_markdown(md)
        assert len(sections) >= 2

    def test_tiny_merge(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        # Tiny section should be merged
        md = "# Hero\nHello world\n\n## Tiny\nHi\n\n## Features\n" + "Feature text. " * 50
        sections = segment_markdown(md)
        # The tiny "Hi" section should be merged into a neighbor
        for sec in sections:
            assert len(sec.markdown) >= 10 or sec == sections[-1]

    def test_cap_at_8(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        # Create 12 sections
        md = "\n\n".join(f"## Section {i}\n" + "Content. " * 100 for i in range(12))
        sections = segment_markdown(md)
        assert len(sections) <= 8

    def test_char_ratios_sum_to_one(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        md = "# Hero\nHero text.\n\n## Features\nFeature text."
        sections = segment_markdown(md)
        total = sum(s.char_ratio for s in sections)
        assert abs(total - 1.0) < 0.01

    def test_stable_section_ids(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        md = "# Hero\nHero text.\n\n## Features\nFeatures."
        sections = segment_markdown(md)
        for i, sec in enumerate(sections):
            assert sec.section_id == f"sec_{i}"

    def test_empty_markdown(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        sections = segment_markdown("")
        assert len(sections) == 1
        assert sections[0].section_id == "sec_0"

    def test_works_without_element_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            segment_markdown,
        )

        md = "# Hello\nWorld."
        sections = segment_markdown(md, element_detection=None)
        assert len(sections) >= 1


class TestReconciliation:
    """Test section reconciliation between Phase 1 and segmenter."""

    def test_reconcile_equal_counts(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_sections,
        )
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            SegmenterSection,
        )

        segs = [
            SegmenterSection("sec_0", "hero", "Hero text", 0.5),
            SegmenterSection("sec_1", "features", "Feature text", 0.5),
        ]
        p1 = [
            {"name": "hero", "y_start_pct": 0.0, "y_end_pct": 0.5},
            {"name": "features", "y_start_pct": 0.5, "y_end_pct": 1.0},
        ]
        skeleton = '<section data-section="sec_0">{{sec_0}}</section><section data-section="sec_1">{{sec_1}}</section>'

        section_map, rewritten = _reconcile_sections(segs, p1, skeleton)
        assert "sec_0" in section_map
        assert "sec_1" in section_map

    def test_discard_when_diff_gt_2(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_sections,
        )
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            SegmenterSection,
        )

        segs = [
            SegmenterSection("sec_0", "hero", "Hero text", 0.5),
            SegmenterSection("sec_1", "features", "Feature text", 0.5),
        ]
        # 5 sections from Phase 1 (diff = 3 > 2)
        p1 = [{"name": f"s{i}", "y_start_pct": i * 0.2, "y_end_pct": (i + 1) * 0.2} for i in range(5)]
        skeleton = '<section data-section="sec_0">{{sec_0}}</section>'

        section_map, rewritten = _reconcile_sections(segs, p1, skeleton)
        # Should use char-ratio fallback, producing exactly 2 sections
        assert len(section_map) == 2


# ---------------------------------------------------------------------------
# Cropper tests
# ---------------------------------------------------------------------------


class TestCropper:
    """Test image cropping."""

    def _make_test_image(self, width=100, height=400):
        """Create a simple test image as PNG bytes."""
        from PIL import Image

        img = Image.new("RGB", (width, height), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_model_bounding_box_crop(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            NormalizedBox,
            crop_section,
        )

        img_bytes = self._make_test_image()
        box = NormalizedBox("sec_0", "hero", 0.0, 0.5)
        cropped = crop_section(img_bytes, box, add_overlap=False)
        assert len(cropped) > 0

        from PIL import Image
        img = Image.open(io.BytesIO(cropped))
        assert img.height == 200  # 50% of 400

    def test_char_ratio_fallback(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            boxes_from_char_ratios,
        )
        from viraltracker.services.landing_page_analysis.multipass.segmenter import (
            SegmenterSection,
        )

        sections = [
            SegmenterSection("sec_0", "hero", "Hero text", 0.3),
            SegmenterSection("sec_1", "features", "Feature text", 0.7),
        ]
        boxes = boxes_from_char_ratios(sections)
        assert len(boxes) == 2
        assert boxes[-1].y_end_pct == 1.0

    def test_overlap_padding(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            NormalizedBox,
            crop_section,
        )

        img_bytes = self._make_test_image()
        box = NormalizedBox("sec_0", "mid", 0.3, 0.6)
        cropped = crop_section(img_bytes, box, add_overlap=True)

        from PIL import Image
        img = Image.open(io.BytesIO(cropped))
        # With overlap: (0.3-0.05) to (0.6+0.05) = 0.25 to 0.65 = 40% of 400 = 160px
        assert img.height == 160

    def test_size_cap(self):
        from viraltracker.services.landing_page_analysis.multipass.cropper import (
            MAX_CROP_BYTES,
            NormalizedBox,
            crop_section,
        )

        # Large image
        img_bytes = self._make_test_image(width=4000, height=8000)
        box = NormalizedBox("sec_0", "all", 0.0, 1.0)
        cropped = crop_section(img_bytes, box, add_overlap=False)
        assert len(cropped) <= MAX_CROP_BYTES


# ---------------------------------------------------------------------------
# PopupFilter tests
# ---------------------------------------------------------------------------


class TestPopupFilter:
    """Test popup/overlay removal."""

    def test_removes_detected_overlay(self):
        from viraltracker.services.landing_page_analysis.multipass.popup_filter import (
            PopupFilter,
        )

        html = '<div><div class="cookie-popup">Accept cookies</div><p>Content</p></div>'
        overlays = [{"type": "cookie", "css_hint": ".cookie-popup", "description": "Cookie banner"}]
        result = PopupFilter().filter(html, overlays)
        assert "cookie-popup" not in result
        assert "Content" in result

    def test_preserves_whitelisted_elements(self):
        from viraltracker.services.landing_page_analysis.multipass.popup_filter import (
            PopupFilter,
        )

        html = '<div><nav class="cookie-popup">Nav content</nav><p>Body</p></div>'
        overlays = [{"type": "popup", "css_hint": ".cookie-popup", "description": "Nav popup"}]
        result = PopupFilter().filter(html, overlays)
        # Nav is whitelisted -- should NOT be removed
        assert "Nav content" in result

    def test_does_nothing_without_overlays(self):
        from viraltracker.services.landing_page_analysis.multipass.popup_filter import (
            PopupFilter,
        )

        html = '<div><p>Content</p></div>'
        result = PopupFilter().filter(html, None)
        assert result == html
        result = PopupFilter().filter(html, [])
        assert result == html

    def test_preserves_data_slot_elements(self):
        from viraltracker.services.landing_page_analysis.multipass.popup_filter import (
            PopupFilter,
        )

        html = '<div><div class="modal-overlay" data-slot="headline">Important</div></div>'
        overlays = [{"type": "modal", "css_hint": ".modal-overlay", "description": "Modal"}]
        result = PopupFilter().filter(html, overlays)
        assert 'data-slot="headline"' in result


# ---------------------------------------------------------------------------
# Pipeline utility function tests
# ---------------------------------------------------------------------------


class TestEnsureMinimumSlots:
    """Test the deterministic slotizer."""

    def test_adds_slots_when_below_threshold(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_minimum_slots,
        )

        html = '<h1>Welcome</h1><p>Body text here.</p><a href="#">Click</a>'
        result = _ensure_minimum_slots(html)
        assert 'data-slot="headline"' in result
        assert 'data-slot="body-1"' in result
        assert 'data-slot="cta-1"' in result

    def test_noop_when_sufficient_slots(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_minimum_slots,
        )

        html = '<h1 data-slot="headline">Hi</h1><p data-slot="body-1">Text</p><a data-slot="cta-1">Go</a>'
        result = _ensure_minimum_slots(html)
        assert result == html

    def test_slot_naming_convention(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_minimum_slots,
        )

        html = '<h1>Main</h1><h2>Sub</h2><h3>Section</h3><p>Para 1</p><p>Para 2</p>'
        result = _ensure_minimum_slots(html)
        assert 'data-slot="headline"' in result
        assert 'data-slot="subheadline"' in result
        assert 'data-slot="heading-1"' in result
        assert 'data-slot="body-1"' in result
        assert 'data-slot="body-2"' in result


class TestTruncateMarkdown:
    """Test markdown truncation."""

    def test_noop_when_under_limit(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _truncate_markdown,
        )

        md = "# Hello\nShort text."
        assert _truncate_markdown(md, max_chars=1000) == md

    def test_cuts_at_heading_boundary(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _truncate_markdown,
        )

        md = "# Section 1\n" + "A " * 500 + "\n## Section 2\n" + "B " * 500
        result = _truncate_markdown(md, max_chars=600)
        assert "Section 1" in result
        assert "[... content truncated ...]" in result

    def test_cuts_at_paragraph_boundary(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _truncate_markdown,
        )

        # No headings, but has paragraph breaks
        md = "First paragraph. " * 20 + "\n\n" + "Second paragraph. " * 20
        result = _truncate_markdown(md, max_chars=200)
        assert "[... content truncated ...]" in result

    def test_hard_cut_when_no_boundaries(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _truncate_markdown,
        )

        md = "x" * 2000
        result = _truncate_markdown(md, max_chars=500)
        assert len(result) < 600  # 500 + truncation message


class TestPhase2Fallback:
    """Test the Phase 2 markdown fallback."""

    def test_replaces_placeholder_with_html(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = MagicMock()
        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        md = "# Hello\nWorld."
        result = pipeline._phase_2_fallback(skeleton, md)
        assert "Hello" in result
        assert "World" in result
        # Placeholder should be replaced
        assert "{{sec_0}}" not in result


# ---------------------------------------------------------------------------
# Pipeline integration tests (mocked Gemini)
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Integration tests with mocked Gemini calls."""

    def _make_test_image_b64(self, width=100, height=400):
        """Create test image as base64."""
        from PIL import Image

        img = Image.new("RGB", (width, height), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _make_mock_gemini(self):
        """Create a mock GeminiService with async methods."""
        mock = MagicMock()
        mock.analyze_image_async = AsyncMock()
        mock.analyze_text_async = AsyncMock()
        mock.set_tracking_context = MagicMock()
        mock._usage_tracker = None
        return mock

    def _phase_0_response(self):
        return json.dumps({
            "colors": {"primary": "#333", "secondary": "#666", "accent": "#00f",
                       "background": "#fff", "surface": "#f5f5f5",
                       "text_primary": "#1a1a1a", "text_secondary": "#666",
                       "border": "#e0e0e0", "cta": "#00f"},
            "typography": {"heading_font": "sans-serif", "body_font": "sans-serif",
                          "h1_size": "3rem", "h2_size": "2rem", "h3_size": "1.5rem",
                          "body_size": "1rem", "line_height": "1.7"},
            "spacing": {"section_padding_v": "70px", "section_padding_h": "30px",
                       "element_gap": "20px", "group_gap": "40px"},
            "overlays": [],
        })

    def _phase_1_response(self):
        return json.dumps({
            "sections": [
                {"name": "hero", "y_start_pct": 0.0, "y_end_pct": 0.5},
                {"name": "features", "y_start_pct": 0.5, "y_end_pct": 1.0},
            ],
            "skeleton_html": (
                '<style>body{margin:0}</style>'
                '<section data-section="sec_0" class="section">'
                '<div class="container">{{sec_0}}</div></section>'
                '<section data-section="sec_1" class="section">'
                '<div class="container">{{sec_1}}</div></section>'
            ),
        })

    def _phase_2_response(self):
        return (
            '<style>body{margin:0}</style>'
            '<section data-section="sec_0" class="section">'
            '<div class="container">'
            '<h1 data-slot="headline">Welcome</h1>'
            '<p data-slot="body-1">Hero body text.</p>'
            '<a data-slot="cta-1">Get Started</a>'
            '</div></section>'
            '<section data-section="sec_1" class="section">'
            '<div class="container">'
            '<h2 data-slot="heading-1">Features</h2>'
            '<p data-slot="body-2">Feature description.</p>'
            '</div></section>'
        )

    def _phase_3_response(self, sec_id):
        if sec_id == "sec_0":
            return (
                '<section data-section="sec_0" class="section" style="background:#f0f0f0">'
                '<div class="container">'
                '<h1 data-slot="headline">Welcome</h1>'
                '<p data-slot="body-1">Hero body text.</p>'
                '<a data-slot="cta-1">Get Started</a>'
                '</div></section>'
            )
        return (
            '<section data-section="sec_1" class="section" style="background:#fff">'
            '<div class="container">'
            '<h2 data-slot="heading-1">Features</h2>'
            '<p data-slot="body-2">Feature description.</p>'
            '</div></section>'
        )

    def _phase_4_response(self):
        return json.dumps([
            {
                "type": "css_fix",
                "selector": "[data-section='sec_0']",
                "value": "padding: 80px 20px;",
            }
        ])

    @pytest.mark.asyncio
    async def test_happy_path(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()
        call_count = 0

        async def mock_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._phase_0_response()
            elif call_count == 2:
                return self._phase_1_response()
            elif call_count in (3, 4):
                sec_id = "sec_0" if call_count == 3 else "sec_1"
                return self._phase_3_response(sec_id)
            elif call_count == 5:
                return self._phase_4_response()
            return "{}"

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=mock_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        result = await pipeline.generate(
            screenshot_b64=self._make_test_image_b64(),
            page_markdown="# Welcome\nHero body text.\n\n## Features\nFeature description.",
        )

        assert "data-slot" in result
        assert "headline" in result
        assert "sec_0" in result

    @pytest.mark.asyncio
    async def test_phase_0_failure_uses_defaults(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()
        call_count = 0

        async def mock_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Phase 0 failed")
            if call_count == 3:
                return self._phase_1_response()
            return self._phase_3_response("sec_0")

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=mock_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        result = await pipeline.generate(
            screenshot_b64=self._make_test_image_b64(),
            page_markdown="# Test\nContent.",
        )

        # Should still produce output using default design system
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_phase_3_invariant_rejects_section(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()
        call_count = 0

        async def mock_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._phase_0_response()
            elif call_count == 2:
                return self._phase_1_response()
            elif call_count in (3, 4, 5, 6):
                # Return completely different text (will fail invariant check)
                return (
                    '<section data-section="sec_0">'
                    '<h1 data-slot="headline">COMPLETELY DIFFERENT TEXT</h1>'
                    '<p data-slot="body-1">This is totally hallucinated content that differs greatly.</p>'
                    '</section>'
                )
            elif call_count == 7:
                return self._phase_4_response()
            return "[]"

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=mock_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        result = await pipeline.generate(
            screenshot_b64=self._make_test_image_b64(),
            page_markdown="# Welcome\nHero body text.\n\n## Features\nFeature description.",
        )

        # Original Phase 2 content should be preserved for rejected sections
        assert "Hero body text" in result or "Welcome" in result

    @pytest.mark.asyncio
    async def test_phase_4_invariant_reverts_patches(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()
        call_count = 0

        async def mock_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._phase_0_response()
            elif call_count == 2:
                return self._phase_1_response()
            elif call_count in (3, 4):
                sec_id = "sec_0" if call_count == 3 else "sec_1"
                return self._phase_3_response(sec_id)
            elif call_count == 5:
                # Patches that would remove slots (should be reverted)
                return json.dumps([
                    {"type": "remove_element", "selector": "[data-slot='headline']"},
                ])
            return "[]"

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=mock_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        result = await pipeline.generate(
            screenshot_b64=self._make_test_image_b64(),
            page_markdown="# Welcome\nHero body text.\n\n## Features\nFeature description.",
        )

        # headline slot should still be there (patches reverted)
        assert 'data-slot="headline"' in result

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()
        call_count = 0

        async def mock_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._phase_0_response()
            elif call_count == 2:
                return self._phase_1_response()
            elif call_count in (3, 4):
                sec_id = "sec_0" if call_count == 3 else "sec_1"
                return self._phase_3_response(sec_id)
            return self._phase_4_response()

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=mock_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        progress_calls = []

        def progress_cb(phase, message):
            progress_calls.append((phase, message))

        pipeline = MultiPassPipeline(gemini_service=mock_gemini, progress_callback=progress_cb)
        await pipeline.generate(
            screenshot_b64=self._make_test_image_b64(),
            page_markdown="# Welcome\nHero body text.\n\n## Features\nFeature description.",
        )

        # Should have progress calls for phases 0-5
        phases_reported = [p for p, _ in progress_calls]
        assert 0 in phases_reported
        assert 1 in phases_reported
        assert 2 in phases_reported

    @pytest.mark.asyncio
    async def test_rate_limiter_backs_off_on_429(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            PipelineRateLimiter,
        )

        limiter = PipelineRateLimiter(initial_rpm=15, max_concurrent=3)
        initial_rpm = limiter._current_rpm

        await limiter.acquire()
        limiter.release(rate_limited=True)
        assert limiter._current_rpm < initial_rpm

    @pytest.mark.asyncio
    async def test_rate_limiter_ramps_up_on_success(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            PipelineRateLimiter,
        )

        limiter = PipelineRateLimiter(initial_rpm=15, max_concurrent=10)

        for _ in range(5):
            await limiter.acquire()
            limiter.release(success=True)

        assert limiter._current_rpm > 15

    @pytest.mark.asyncio
    async def test_budget_timeout_returns_partial(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        mock_gemini = self._make_mock_gemini()

        async def slow_vision(image_data, prompt, model=None, skip_internal_rate_limit=False):
            # Simulate slow API
            await asyncio.sleep(0.01)
            return self._phase_0_response()

        async def mock_text(text, prompt, model=None, skip_internal_rate_limit=False):
            return self._phase_2_response()

        mock_gemini.analyze_image_async = AsyncMock(side_effect=slow_vision)
        mock_gemini.analyze_text_async = AsyncMock(side_effect=mock_text)

        pipeline = MultiPassPipeline(gemini_service=mock_gemini)
        # Override timeout for test speed
        import viraltracker.services.landing_page_analysis.multipass.pipeline as pipe_mod
        original_timeout = pipe_mod.MAX_WALL_CLOCK
        pipe_mod.MAX_WALL_CLOCK = 0.001  # Extremely short timeout

        try:
            result = await pipeline.generate(
                screenshot_b64=self._make_test_image_b64(),
                page_markdown="# Test\nContent.",
            )
            # Should return something (even if partial)
            assert isinstance(result, str)
        finally:
            pipe_mod.MAX_WALL_CLOCK = original_timeout


# ---------------------------------------------------------------------------
# Eval harness tests
# ---------------------------------------------------------------------------


class TestEvalHarness:
    """Test eval harness scoring functions."""

    SAMPLE_HTML = """
    <h1 data-slot="headline">Welcome</h1>
    <p data-slot="body-1">Body text</p>
    <p data-slot="body-2">More text</p>
    <a data-slot="cta-1">Click</a>
    <h2 data-slot="heading-1">Features</h2>
    <p data-slot="body-3">Feature text</p>
    """

    def test_slot_count(self):
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            count_slots,
        )

        count, slots = count_slots(self.SAMPLE_HTML)
        assert count == 6
        assert "headline" in slots
        assert "cta-1" in slots

    def test_text_fidelity(self):
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            score_text_fidelity,
        )

        md = "Welcome Body text More text Click Features Feature text"
        score = score_text_fidelity(self.SAMPLE_HTML, md)
        assert score > 0.5

    def test_blueprint_round_trip_basic(self):
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            check_blueprint_round_trip,
        )

        # Without service, just checks slot count >= 5
        assert check_blueprint_round_trip(self.SAMPLE_HTML) is True

    def test_evaluate_page(self):
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            evaluate_page,
        )

        score = evaluate_page(
            page_url="https://example.com",
            multipass_html=self.SAMPLE_HTML,
            single_pass_html=self.SAMPLE_HTML,
            source_markdown="Welcome Body text More text Click Features Feature text",
            latency_seconds=30.0,
        )
        assert score.slot_count == 6
        assert score.slot_retention == 1.0

    def test_benchmark_pass_fail(self):
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            PageScore,
            evaluate_benchmark,
        )

        good_scores = [
            PageScore(
                page_url=f"https://example.com/{i}",
                slot_count=8,
                single_pass_slot_count=8,
                slot_retention=1.0,
                text_fidelity=0.92,
                blueprint_round_trip=True,
                escape_hatch_triggered=False,
                latency_seconds=45.0,
            )
            for i in range(5)
        ]
        result = evaluate_benchmark(good_scores)
        assert result.passed is True

        # Add a failing page
        bad_score = PageScore(
            page_url="https://example.com/bad",
            slot_count=2,  # Below threshold
            single_pass_slot_count=8,
            slot_retention=0.25,
            text_fidelity=0.5,
            blueprint_round_trip=False,
            escape_hatch_triggered=True,
            latency_seconds=100.0,
        )
        result = evaluate_benchmark(good_scores + [bad_score])
        assert result.passed is False
        assert len(result.failures) > 0
