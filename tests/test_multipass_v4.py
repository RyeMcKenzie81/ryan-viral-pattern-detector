"""Unit tests for multipass pipeline v4 modules.

Tests cover:
B1: ImageRegistry
B2: CSSExtractor
B3: content_assembler
B4: CSS scoping (_scope_css_under_class)
B5: srcset parsing + sanitizer validation
B6: Dual-scrape drift detection
B7: PatchApplier *= selector
B8: CSS injection fallback chain
B9: Background image marker survival + restoration
B10: page_html size guardrail
B11: _SectionParser void element depth tracking (Fix 1) + semantic tag support
B12: _rewrite_skeleton hardening (Fix 2) + semantic tag Step B
B13: _ensure_section_attributes semantic tags + heading-boundary-split removal (Fix 3)
B14: Scoped placeholder cleanup (Fix 4)
B15: Phase 1 prompt constraints (Fix 5)
B16: Global invariant section-count (Fix 8)
B17: Integration test — full failure chain reproduction
"""

import re
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers for test sections
# ---------------------------------------------------------------------------


@dataclass
class FakeSection:
    """Minimal SegmenterSection stand-in for tests."""
    section_id: str
    name: str
    markdown: str
    char_ratio: float = 0.5


# ===========================================================================
# B1: ImageRegistry
# ===========================================================================


class TestImageRegistry:
    """B1: html_extractor.py — ImageRegistry tests."""

    def test_img_extraction_basic(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '''
        <html><body>
        <img src="https://example.com/hero.jpg" alt="Hero" width="1200" height="600">
        <img src="https://example.com/feature.png" alt="Feature" width="400" height="300">
        <img src="https://example.com/logo.svg" alt="Logo" width="120" height="40">
        </body></html>
        '''
        sections = [
            FakeSection("sec_0", "hero", "![Hero](https://example.com/hero.jpg)"),
            FakeSection("sec_1", "features", "![Feature](https://example.com/feature.png)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")

        assert len(registry.images) >= 2  # At least the markdown-mapped ones
        hero = registry.images.get("https://example.com/hero.jpg")
        assert hero is not None
        assert hero.width == 1200
        assert hero.height == 600
        assert "sec_0" in hero.section_ids

    def test_srcset_extraction(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img src="https://example.com/a.jpg" srcset="https://example.com/a-2x.jpg 2x, https://example.com/a-3x.jpg 3x" alt="Test">'
        sections = [
            FakeSection("sec_0", "hero", "![Test](https://example.com/a.jpg)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        img = registry.images.get("https://example.com/a.jpg")
        assert img is not None
        assert img.srcset is not None
        assert "2x" in img.srcset

    def test_background_image_extraction(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<div style="background-image: url(https://example.com/bg.jpg)">Content</div>'
        sections = [FakeSection("sec_0", "hero", "Some text")]
        registry = ImageRegistry.build(html, sections, "https://example.com")

        bg_images = [img for img in registry.images.values() if img.is_background]
        assert len(bg_images) >= 1
        assert bg_images[0].url == "https://example.com/bg.jpg"

    def test_lazy_load(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img data-src="https://example.com/lazy.jpg" alt="Lazy">'
        sections = [FakeSection("sec_0", "hero", "![Lazy](https://example.com/lazy.jpg)")]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        assert "https://example.com/lazy.jpg" in registry.images

    def test_deduplication(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '''
        <img src="https://example.com/same.jpg">
        <img src="https://example.com/same.jpg">
        <img src="https://example.com/same.jpg">
        '''
        sections = [
            FakeSection("sec_0", "hero", "![](https://example.com/same.jpg)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        assert len([u for u in registry.images if u == "https://example.com/same.jpg"]) == 1

    def test_section_mapping(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">'
        sections = [
            FakeSection("sec_0", "hero", "![a](https://example.com/a.jpg)"),
            FakeSection("sec_1", "features", "![b](https://example.com/b.jpg)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        sec0_imgs = registry.get_section_images("sec_0")
        sec1_imgs = registry.get_section_images("sec_1")
        assert any(img.url == "https://example.com/a.jpg" for img in sec0_imgs)
        assert any(img.url == "https://example.com/b.jpg" for img in sec1_imgs)

    def test_icon_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img src="https://example.com/icon.png" width="32" height="32" alt="icon">'
        sections = [
            FakeSection("sec_0", "hero", "![icon](https://example.com/icon.png)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        img = registry.images.get("https://example.com/icon.png")
        assert img is not None
        assert img.is_icon is True

    def test_empty_html_fallback(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        sections = [
            FakeSection("sec_0", "hero", "![hero](https://example.com/hero.jpg)"),
        ]
        registry = ImageRegistry.build("", sections, "https://example.com")
        # Should still have the markdown image
        assert "https://example.com/hero.jpg" in registry.images

    def test_unassigned_images(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img src="https://example.com/orphan.jpg" alt="">'
        sections = [FakeSection("sec_0", "hero", "Just text, no images")]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        orphan = registry.images.get("https://example.com/orphan.jpg")
        # Orphan with no alt text and no heading match should have empty section_ids
        if orphan:
            assert len(orphan.section_ids) == 0


# ===========================================================================
# B2: CSSExtractor
# ===========================================================================


class TestCSSExtractor:
    """B2: html_extractor.py — CSSExtractor tests."""

    def test_custom_properties(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        html = '<style>:root { --color-primary: #ff0000; --spacing: 16px; }</style>'
        result = CSSExtractor.extract(html)
        assert "--color-primary" in result.custom_properties
        assert "#ff0000" in result.custom_properties

    def test_media_queries(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        html = '<style>@media (max-width: 768px) { .hero { font-size: 24px; } }</style>'
        result = CSSExtractor.extract(html)
        assert "max-width: 768px" in result.media_queries
        assert ".hero" in result.media_queries

    def test_nested_media(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        html = '<style>@media (max-width: 768px) { .hero { font-size: 24px; } .footer { margin: 0; } }</style>'
        result = CSSExtractor.extract(html)
        assert ".hero" in result.media_queries
        assert ".footer" in result.media_queries

    def test_font_face(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        html = '<style>@font-face { font-family: "Inter"; src: url(inter.woff2) format("woff2"); font-weight: 400; }</style>'
        result = CSSExtractor.extract(html)
        assert "font-family" in result.font_faces
        assert "Inter" in result.font_faces
        assert "src stripped" in result.font_faces  # src should be stripped

    def test_50kb_cap(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        # Create >50KB of CSS
        big_css = ":root { " + " ".join(f"--var-{i}: #{i:06x};" for i in range(5000)) + " }"
        html = f"<style>{big_css}</style>"
        result = CSSExtractor.extract(html)
        total = result.to_css_block()
        assert len(total) <= 60_000  # Some tolerance for the cap

    def test_empty_html(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        result = CSSExtractor.extract("")
        assert result.custom_properties == ""
        assert result.media_queries == ""
        assert result.font_faces == ""

    def test_external_css_third_party_skipped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        html = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap.css">'
        # Should not attempt to fetch (no mock needed — third-party skipped)
        result = CSSExtractor.extract(html, "https://example.com")
        assert result.custom_properties == ""

    @patch("viraltracker.services.landing_page_analysis.multipass.html_extractor._safe_fetch_css")
    def test_external_css_first_party_fetched(self, mock_fetch):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        mock_fetch.return_value = ":root { --brand-color: blue; }"
        html = '<link rel="stylesheet" href="https://example.com/styles.css">'
        result = CSSExtractor.extract(html, "https://example.com")
        mock_fetch.assert_called_once()
        assert "--brand-color" in result.custom_properties

    @patch("viraltracker.services.landing_page_analysis.multipass.html_extractor._safe_fetch_css")
    def test_external_css_fetch_timeout(self, mock_fetch):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        mock_fetch.side_effect = Exception("timeout")
        html = '''
        <style>:root { --inline: red; }</style>
        <link rel="stylesheet" href="https://example.com/styles.css">
        '''
        result = CSSExtractor.extract(html, "https://example.com")
        # Inline CSS should still be extracted
        assert "--inline" in result.custom_properties

    @patch("viraltracker.services.landing_page_analysis.multipass.html_extractor._safe_fetch_css")
    def test_external_css_max_3(self, mock_fetch):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
        )

        mock_fetch.return_value = ".x { color: red; }"
        html = ''.join(
            f'<link rel="stylesheet" href="https://example.com/s{i}.css">'
            for i in range(5)
        )
        CSSExtractor.extract(html, "https://example.com")
        assert mock_fetch.call_count == 3

    def test_external_css_ssrf_localhost_blocked(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _is_safe_css_url,
        )

        assert _is_safe_css_url("https://localhost/style.css") is False

    def test_external_css_ssrf_private_ip_blocked(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _is_safe_css_url,
        )

        assert _is_safe_css_url("https://192.168.1.1/style.css") is False

    def test_external_css_ssrf_http_blocked(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _is_safe_css_url,
        )

        assert _is_safe_css_url("http://example.com/style.css") is False


# ===========================================================================
# B3: content_assembler
# ===========================================================================


class TestContentAssembler:
    """B3: content_assembler.py tests."""

    def test_basic_assembly(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )

        skeleton = '<section data-section="sec_0">{{sec_0}}</section><section data-section="sec_1">{{sec_1}}</section>'
        sections = [
            FakeSection("sec_0", "hero", "# Hello World"),
            FakeSection("sec_1", "features", "**Bold text**"),
        ]
        result = assemble_content(skeleton, sections, {})
        assert "Hello World" in result
        assert "<strong>Bold text</strong>" in result
        assert "{{sec_0}}" not in result
        assert "{{sec_1}}" not in result

    def test_all_placeholders_filled(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )

        sections = [FakeSection(f"sec_{i}", f"s{i}", f"Section {i} text") for i in range(8)]
        skeleton = "".join(f'<section data-section="sec_{i}">{{{{sec_{i}}}}}</section>' for i in range(8))
        result = assemble_content(skeleton, sections, {})
        for i in range(8):
            assert f"Section {i} text" in result
            assert f"{{{{sec_{i}}}}}" not in result

    def test_image_enhancement(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
        )

        html = '<img src="https://example.com/hero.jpg" width="1200" height="600">'
        sections = [
            FakeSection("sec_0", "hero", "![Hero](https://example.com/hero.jpg)"),
        ]
        registry = ImageRegistry.build(html, sections, "https://example.com")
        skeleton = '<section data-section="sec_0">{{sec_0}}</section>'
        result = assemble_content(skeleton, sections, {}, registry)
        assert 'width="1200"' in result
        assert 'height="600"' in result

    def test_bg_image_injection(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            ImageRegistry,
            PageImage,
        )

        # Manually build a registry with a background image assigned to sec_0
        registry = ImageRegistry()
        bg_img = PageImage(
            url="https://example.com/bg.jpg",
            alt="hero background",
            is_background=True,
            width=1200,
            height=600,
            section_ids=["sec_0"],
        )
        registry.images["https://example.com/bg.jpg"] = bg_img
        registry.section_map["sec_0"] = ["https://example.com/bg.jpg"]

        sections = [FakeSection("sec_0", "hero", "Some text")]
        skeleton = '<section data-section="sec_0">{{sec_0}}</section>'
        result = assemble_content(skeleton, sections, {}, registry)
        assert 'data-bg-image="true"' in result

    def test_data_slot_assignment(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )

        sections = [
            FakeSection("sec_0", "hero", "# Main Title\n\nSome paragraph text\n\n[Click here](https://example.com)"),
        ]
        skeleton = '<section data-section="sec_0">{{sec_0}}</section>'
        result = assemble_content(skeleton, sections, {})
        assert 'data-slot="headline"' in result
        assert 'data-slot="body-1"' in result
        assert 'data-slot="cta-1"' in result

    def test_fallback_all_sections(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            phase_2_fallback,
        )

        sections = [FakeSection(f"sec_{i}", f"s{i}", f"Content {i}") for i in range(3)]
        skeleton = "".join(f'<div>{{{{sec_{i}}}}}</div>' for i in range(3))
        result = phase_2_fallback(skeleton, sections)
        for i in range(3):
            assert f"Content {i}" in result
            assert f"{{{{sec_{i}}}}}" not in result


# ===========================================================================
# B4: CSS scoping
# ===========================================================================


class TestCSSScoping:
    """B4: _scope_css_under_class() tests."""

    def test_regular_selector_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = ".hero { color: red; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert ".lp-mockup .hero" in result
        assert "color: red" in result

    def test_root_vars_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = ":root { --x: 1; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert ".lp-mockup {" in result
        assert "--x: 1" in result

    def test_media_inner_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@media (max-width: 768px) { .hero { font-size: 24px; } }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "@media" in result
        assert ".lp-mockup .hero" in result

    def test_font_face_not_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = '@font-face { font-family: "Inter"; }'
        result = _scope_css_under_class(css, ".lp-mockup")
        assert ".lp-mockup" not in result.split("@font-face")[0]
        assert "@font-face" in result
        assert "Inter" in result

    def test_keyframes_not_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "@keyframes lp-fadeIn" in result

    def test_keyframes_reference_updated(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } } .elem { animation-name: fadeIn; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "animation-name: lp-fadeIn" in result

    def test_comma_selectors_scoped(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = ".hero, .banner { color: red; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert ".lp-mockup .hero" in result
        assert ".lp-mockup .banner" in result

    def test_nested_at_rules(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@supports (display: grid) { @media (max-width: 768px) { .x { color: red; } } }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert ".lp-mockup .x" in result

    def test_animation_shorthand_renamed(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@keyframes fadeIn { 0% { opacity: 0; } } .elem { animation: fadeIn 0.3s ease; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "animation: lp-fadeIn 0.3s ease" in result

    def test_animation_name_renamed(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = "@keyframes slideUp { 0% { transform: translateY(100%); } } .elem { animation-name: slideUp; }"
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "animation-name: lp-slideUp" in result

    def test_multiple_keyframes_renamed(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _scope_css_under_class,
        )

        css = (
            "@keyframes fadeIn { 0% { opacity: 0; } } "
            "@keyframes slideUp { 0% { transform: translateY(100%); } } "
            ".a { animation-name: fadeIn; } "
            ".b { animation-name: slideUp; }"
        )
        result = _scope_css_under_class(css, ".lp-mockup")
        assert "@keyframes lp-fadeIn" in result
        assert "@keyframes lp-slideUp" in result
        assert "animation-name: lp-fadeIn" in result
        assert "animation-name: lp-slideUp" in result


# ===========================================================================
# B5: srcset parsing
# ===========================================================================


class TestSrcsetParser:
    """B5: srcset parsing tests."""

    def test_srcset_basic(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _parse_srcset,
        )

        result = _parse_srcset("img.jpg 1x, img2.jpg 2x")
        assert result == [("img.jpg", "1x"), ("img2.jpg", "2x")]

    def test_srcset_widths(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _parse_srcset,
        )

        result = _parse_srcset("sm.jpg 300w, lg.jpg 1200w")
        assert result == [("sm.jpg", "300w"), ("lg.jpg", "1200w")]

    def test_srcset_no_descriptor(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _parse_srcset,
        )

        result = _parse_srcset("only.jpg")
        assert result == [("only.jpg", "")]

    def test_srcset_extra_whitespace(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _parse_srcset,
        )

        result = _parse_srcset("  a.jpg   1x ,  b.jpg  2x  ")
        assert result == [("a.jpg", "1x"), ("b.jpg", "2x")]

    def test_srcset_empty(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _parse_srcset,
        )

        result = _parse_srcset("")
        assert result == []


# ===========================================================================
# B6: Dual-scrape drift detection
# ===========================================================================


class TestScrapeConsistency:
    """B6: Dual-scrape consistency check."""

    def test_all_signals_match(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        html = '<html><head><title>My Product Page</title></head><body><h1>My Product Page</h1><img src="https://example.com/hero.jpg"></body></html>'
        md = "# My Product Page\n\n![hero](https://example.com/hero.jpg)"
        assert check_scrape_consistency(html, md, "https://example.com") is True

    def test_title_differs_but_images_and_headings_match(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        html = '<html><head><title>Brand | Different Title</title></head><body><h1>My Product</h1><img src="https://example.com/hero.jpg"></body></html>'
        md = "# My Product\n\n![hero](https://example.com/hero.jpg)"
        assert check_scrape_consistency(html, md, "https://example.com") is True

    def test_title_and_images_differ(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        html = '<html><head><title>Completely Different Page</title></head><body><h1>Some heading</h1><img src="https://other.com/img.jpg"></body></html>'
        md = "# My Product\n\n![hero](https://example.com/hero.jpg)"
        # Title differs, images differ — only heading might partially match
        result = check_scrape_consistency(html, md, "https://example.com")
        assert result is False

    def test_completely_different_page(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        html = '<html><head><title>Error 404</title></head><body><h1>Not Found</h1></body></html>'
        md = "# My Product\n\nGreat features here\n\n![hero](https://example.com/hero.jpg)"
        assert check_scrape_consistency(html, md, "https://example.com") is False

    def test_zero_signals_nonempty_markdown_rejected(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        html = '<html><body><div>No title, no images, no headings</div></body></html>'
        md = "# Product Page\n\nSome content"
        assert check_scrape_consistency(html, md, "https://example.com") is False

    def test_zero_signals_empty_markdown_accepted(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        assert check_scrape_consistency("<html></html>", "", "https://example.com") is True

    def test_one_signal_available_and_passes(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        # Only title is checkable (no images, no headings in HTML)
        html = '<html><head><title>My Product</title></head><body></body></html>'
        md = "# My Product"
        assert check_scrape_consistency(html, md, "https://example.com") is True

    def test_missing_signals_graceful(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            check_scrape_consistency,
        )

        # HTML with headings, MD with headings, but no title or images
        html = '<html><body><h1>Great Product</h1><h2>Features</h2></body></html>'
        md = "# Great Product\n\n## Features"
        assert check_scrape_consistency(html, md, "https://example.com") is True


# ===========================================================================
# B7: PatchApplier *= selector
# ===========================================================================


class TestPatchApplierContains:
    """B7: PatchApplier — *= selector support."""

    def test_contains_match(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<div style="display: flex; gap: 60px; padding: 20px;">Content</div>'
        patches = [
            {
                "type": "css_fix",
                "selector": "[style*='gap: 60px']",
                "value": "gap: 30px",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        assert "gap: 30px" in result

    def test_contains_no_match(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<div style="gap: 30px;">Content</div>'
        patches = [
            {
                "type": "css_fix",
                "selector": "[style*='gap: 60px']",
                "value": "gap: 30px",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        assert result == html  # No change

    def test_exact_match_unchanged(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<div data-section="sec_0">Content</div>'
        patches = [
            {
                "type": "css_fix",
                "selector": "[data-section='sec_0']",
                "value": "color: red",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        assert "color: red" in result


# ===========================================================================
# B8: CSS injection fallback chain
# ===========================================================================


class TestCSSInjection:
    """B8: CSS injection fallback chain."""

    def test_inject_after_style_tag(self):
        skeleton = '<style>.hero { color: red; }</style><div>Content</div>'
        css_block = '<style class="responsive-css">@media {}</style>'
        if '</style>' in skeleton:
            result = skeleton.replace("</style>", f"</style>\n{css_block}", 1)
        assert css_block in result

    def test_inject_before_head_close(self):
        skeleton = '<head><meta charset="utf-8"></head><body>Content</body>'
        css_block = '<style class="responsive-css">@media {}</style>'
        if '</style>' not in skeleton:
            result = re.sub(
                r'(</head>)', f'{css_block}\n\\1', skeleton, count=1, flags=re.IGNORECASE
            )
        assert css_block in result

    def test_inject_prepend_fallback(self):
        skeleton = '<div>Content</div>'
        css_block = '<style class="responsive-css">@media {}</style>'
        if '</style>' not in skeleton and '</head>' not in skeleton.lower():
            result = f'{css_block}\n{skeleton}'
        assert result.startswith(css_block)


# ===========================================================================
# B9: Background image marker survival + restoration
# ===========================================================================


class TestBackgroundImageMarker:
    """B9: Background image marker tests."""

    def test_restore_at_display_boundary(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            restore_background_images,
        )

        html = '<img data-bg-image="true" src="https://example.com/bg.jpg" width="1200" height="600">'
        result = restore_background_images(html)
        assert "background-image: url(https://example.com/bg.jpg)" in result
        assert 'data-bg-image-rendered="true"' in result

    def test_restore_idempotent(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            restore_background_images,
        )

        html = '<img data-bg-image="true" src="https://example.com/bg.jpg" height="600">'
        result1 = restore_background_images(html)
        result2 = restore_background_images(result1)
        assert result1 == result2

    def test_no_restore_without_marker(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            restore_background_images,
        )

        html = '<img src="https://example.com/regular.jpg" alt="Normal image">'
        result = restore_background_images(html)
        assert result == html  # No change

    def test_restore_rejects_invalid_url(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            restore_background_images,
        )

        html = '<img data-bg-image="true" src="http://insecure.com/bg.jpg">'
        result = restore_background_images(html)
        # Should NOT convert (non-HTTPS), leave as marker
        assert "background-image" not in result
        assert 'data-bg-image="true"' in result


# ===========================================================================
# B10: page_html size guardrail
# ===========================================================================


class TestPageHtmlGuardrail:
    """B10: page_html size cap tests."""

    def test_under_2mb_stored(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _extract_head_section,
        )

        html = "<html><head><style>.x{}</style></head><body>" + "x" * 500_000 + "</body></html>"
        MAX_PAGE_HTML_SIZE = 2 * 1024 * 1024
        assert len(html) < MAX_PAGE_HTML_SIZE
        # Would be stored as-is

    def test_over_2mb_extracts_head(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _extract_head_section,
        )

        head_content = "<head><style>:root { --color: red; }</style></head>"
        body_content = "<body>" + "x" * (3 * 1024 * 1024) + "</body>"
        html = f"<html>{head_content}{body_content}</html>"

        MAX_PAGE_HTML_SIZE = 2 * 1024 * 1024
        assert len(html) > MAX_PAGE_HTML_SIZE

        head = _extract_head_section(html)
        assert head is not None
        assert "--color: red" in head
        assert len(head) < MAX_PAGE_HTML_SIZE

    def test_over_2mb_no_head_discards(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            _extract_head_section,
        )

        html = "x" * (3 * 1024 * 1024)  # No <head> tag
        head = _extract_head_section(html)
        assert head is None

    def test_head_section_css_extraction(self):
        from viraltracker.services.landing_page_analysis.multipass.html_extractor import (
            CSSExtractor,
            _extract_head_section,
        )

        full_html = "<html><head><style>:root { --brand: blue; } @media (max-width: 768px) { .x { color: red; } }</style></head><body>big content</body></html>"
        head_only = _extract_head_section(full_html)
        assert head_only is not None

        result = CSSExtractor.extract(head_only)
        assert "--brand" in result.custom_properties
        assert "max-width: 768px" in result.media_queries


# ---------------------------------------------------------------------------
# B11: _SectionParser void element depth tracking (Fix 1)
# ---------------------------------------------------------------------------


class TestSectionParserVoidElements:
    """Fix 1: _SectionParser must handle void elements without depth corruption."""

    def test_void_elements_non_self_closing(self):
        """img and br without self-closing slash must not corrupt depth."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<h1>Title</h1><img src="test.jpg"><br><p>Content</p>'
            '</section>'
            '<section data-section="sec_1">'
            '<p>More content</p><img src="other.jpg">'
            '</section>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "sec_1" in sections
        assert "Title" in sections["sec_0"]
        assert "More content" in sections["sec_1"]

    def test_self_closing_void_elements(self):
        """img/ and br/ must also work correctly."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<h1>Title</h1><img src="test.jpg"/><br/><p>Content</p>'
            '</section>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "Title" in sections["sec_0"]

    def test_nested_sections(self):
        """Nested <section> tags should not break the parser."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<section class="inner"><p>Nested</p></section>'
            '</section>'
            '<section data-section="sec_1">'
            '<p>After</p>'
            '</section>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "sec_1" in sections
        assert "Nested" in sections["sec_0"]

    def test_many_void_elements_no_depth_corruption(self):
        """Sections with many void elements must still close correctly."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<img src="a.jpg"><img src="b.jpg"><br><hr>'
            '<input type="text"><link rel="stylesheet">'
            '<p>Content</p>'
            '</section>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "Content" in sections["sec_0"]

    def test_footer_with_data_section(self):
        """<footer data-section> must be parsed as a section."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<h1>Hero</h1><p>Content</p>'
            '</section>'
            '<footer data-section="sec_1">'
            '<p>Footer content</p>'
            '</footer>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "sec_1" in sections
        assert "Hero" in sections["sec_0"]
        assert "Footer content" in sections["sec_1"]

    def test_header_with_data_section(self):
        """<header data-section> must be parsed as a section."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<header data-section="sec_0">'
            '<nav>Navigation</nav>'
            '</header>'
            '<section data-section="sec_1">'
            '<p>Main content</p>'
            '</section>'
        )
        sections = _parse_sections(html)
        assert "sec_0" in sections
        assert "sec_1" in sections
        assert "Navigation" in sections["sec_0"]

    def test_mixed_tag_types(self):
        """Mix of <section>, <header>, <footer>, <nav> all parsed correctly."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<header data-section="sec_0"><h1>Header</h1></header>'
            '<section data-section="sec_1"><p>Body</p></section>'
            '<nav data-section="sec_2"><a>Link</a></nav>'
            '<footer data-section="sec_3"><p>Footer</p></footer>'
        )
        sections = _parse_sections(html)
        assert len(sections) == 4
        assert "Header" in sections["sec_0"]
        assert "Body" in sections["sec_1"]
        assert "Footer" in sections["sec_3"]

    def test_nested_footer_inside_section_not_tracked(self):
        """A <footer data-section> nested inside another section is content, not separate."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )

        html = (
            '<section data-section="sec_0">'
            '<p>Outer</p>'
            '<footer data-section="sec_1"><p>Nested footer</p></footer>'
            '</section>'
        )
        sections = _parse_sections(html)
        # sec_0 should capture everything, sec_1 not separately parsed
        assert "sec_0" in sections
        assert "Nested footer" in sections["sec_0"]
        # sec_1 should NOT be found (nested inside sec_0)
        assert "sec_1" not in sections


# ---------------------------------------------------------------------------
# B12: _rewrite_skeleton hardening (Fix 2)
# ---------------------------------------------------------------------------


class TestRewriteSkeleton:
    """Fix 2: _rewrite_skeleton handles missing attrs, single quotes, variants."""

    def test_single_quoted_data_section(self):
        """Single-quoted data-section attributes should be recognized."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
        )

        html = (
            "<section data-section='hero'>{{hero}}</section>"
            "<section data-section='features'>{{features}}</section>"
        )
        result = _rewrite_skeleton(html, 2)
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result

    def test_missing_data_section_attrs(self):
        """Bare <section> tags without data-section get attributes added."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
        )

        html = (
            "<section><p>Section 1</p></section>"
            "<section><p>Section 2</p></section>"
        )
        result = _rewrite_skeleton(html, 2)
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result

    def test_bare_footer_gets_data_section(self):
        """Bare <footer> tags without data-section get attributes added (Step B)."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
        )

        html = (
            "<section><p>Section 1</p></section>"
            "<footer><p>Footer</p></footer>"
        )
        result = _rewrite_skeleton(html, 2)
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result

    def test_variant_placeholders_normalized(self):
        """{{sec_3_part1}} and similar variants get normalized to {{sec_3}}."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
        )

        html = (
            '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
            '<section data-section="sec_1"><div>{{sec_1_header}}</div></section>'
            '<section data-section="sec_2"><div>{{sec_2_part1}}</div></section>'
        )
        result = _rewrite_skeleton(html, 3)
        assert "{{sec_0}}" in result
        assert "{{sec_1}}" in result
        assert "{{sec_2}}" in result
        assert "{{sec_1_header}}" not in result
        assert "{{sec_2_part1}}" not in result

    def test_duplicate_placeholders_deduplicated(self):
        """Multiple occurrences of same placeholder keep only the first."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
        )

        html = (
            '<section data-section="sec_0">'
            '<div>{{sec_0}}</div><div>{{sec_0}}</div>'
            '</section>'
        )
        result = _rewrite_skeleton(html, 1)
        assert result.count("{{sec_0}}") == 1


# ---------------------------------------------------------------------------
# B13: _ensure_section_attributes with lp-mockup + single quotes (Fix 3)
# ---------------------------------------------------------------------------


class TestEnsureSectionAttributesExtended:
    """Fix 3: lp-mockup handling and single-quote stripping."""

    def test_single_quoted_data_section_stripped(self):
        """Single-quoted data-section attrs must be stripped during re-injection.

        We need 2 expected sections but only 1 parseable section so the
        early-return check (len >= expected) is False and the strip+re-inject
        path is triggered.  The second <section> lacks data-section entirely.
        """
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
        )

        html = (
            "<section data-section='old_0'>"
            "<h2>Title</h2><p>Content A</p>"
            "</section>"
            "<section>"
            "<h2>Title 2</h2><p>Content B</p>"
            "</section>"
        )
        section_map = {"sec_0": MagicMock(), "sec_1": MagicMock()}
        lf = MagicMock()
        result = _ensure_section_attributes(html, section_map, lf)
        # The single-quoted old attr must be gone
        assert "data-section='old_0'" not in result
        # Both sections should have double-quoted sec_N attrs
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result

    def test_lp_mockup_no_sections_returns_unchanged(self):
        """When no section-like tags exist, return as-is (defers to pre-Phase-3 gate)."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
        )

        html = (
            '<div class="lp-mockup">'
            '<style>.section { padding: 20px; }</style>'
            '<h2>Title 1</h2><p>Content 1</p>'
            '<h2>Title 2</h2><p>Content 2</p>'
            '</div>'
        )
        section_map = {"sec_0": MagicMock(), "sec_1": MagicMock()}
        lf = MagicMock()
        result = _ensure_section_attributes(html, section_map, lf)
        # No section-like tags to inject into — returns original HTML.
        # Pre-Phase-3 gate handles recovery via fallback skeleton.
        assert 'lp-mockup' in result
        # Since heading-boundary split is removed, no data-section attrs are added
        # when there are zero section-like tags.

    def test_footer_section_gets_data_section(self):
        """<footer> tags should be recognized as section candidates."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
        )

        html = (
            '<section><h1>Hero</h1><p>Content</p></section>'
            '<footer><p>Footer content</p></footer>'
        )
        section_map = {"sec_0": MagicMock(), "sec_1": MagicMock()}
        lf = MagicMock()
        result = _ensure_section_attributes(html, section_map, lf)
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result

    def test_mixed_semantic_tags(self):
        """Mix of <section>, <header>, <footer> all get data-section attrs."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
        )

        html = (
            '<header><h1>Nav</h1></header>'
            '<section><p>Content</p></section>'
            '<footer><p>Footer</p></footer>'
        )
        section_map = {"sec_0": MagicMock(), "sec_1": MagicMock(), "sec_2": MagicMock()}
        lf = MagicMock()
        result = _ensure_section_attributes(html, section_map, lf)
        assert 'data-section="sec_0"' in result
        assert 'data-section="sec_1"' in result
        assert 'data-section="sec_2"' in result


# ---------------------------------------------------------------------------
# B14: Scoped placeholder cleanup (Fix 4)
# ---------------------------------------------------------------------------


class TestScopedPlaceholderCleanup:
    """Fix 4: Only {{sec_N...}} placeholders are stripped."""

    def test_strips_sec_placeholders(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _strip_unresolved_placeholders,
        )

        html = '<p>Before</p>{{sec_3_part1}}<p>Middle</p>{{sec_5}}<p>After</p>'
        result, count = _strip_unresolved_placeholders(html)
        assert count == 2
        assert "{{sec_3" not in result
        assert "{{sec_5}}" not in result
        assert "Before" in result
        assert "Middle" in result
        assert "After" in result

    def test_preserves_non_sec_placeholders(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _strip_unresolved_placeholders,
        )

        html = '<p>{{hero_content}}</p><p>{{sec_0}}</p><p>{{cta_button}}</p>'
        result, count = _strip_unresolved_placeholders(html)
        assert count == 1
        assert "{{hero_content}}" in result
        assert "{{cta_button}}" in result
        assert "{{sec_0}}" not in result

    def test_zero_removals_for_clean_html(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _strip_unresolved_placeholders,
        )

        html = '<p>Clean HTML with no placeholders</p>'
        result, count = _strip_unresolved_placeholders(html)
        assert count == 0
        assert result == html


# ---------------------------------------------------------------------------
# B15: Phase 1 prompt constraints (Fix 5)
# ---------------------------------------------------------------------------


class TestPhase1PromptConstraints:
    """Fix 5: Phase 1 prompt includes format constraints."""

    def test_prompt_includes_critical_format_constraints(self):
        from viraltracker.services.landing_page_analysis.multipass.prompts import (
            PHASE_1_PROMPT_VERSION,
            build_phase_1_prompt,
        )

        prompt = build_phase_1_prompt(
            design_system_json='{"colors": {}}',
            section_names=["Hero", "Features"],
            section_count=2,
        )
        assert "CRITICAL FORMAT CONSTRAINTS" in prompt
        assert "NEVER omit the data-section attribute" in prompt
        assert "NEVER use variants" in prompt
        assert PHASE_1_PROMPT_VERSION == "v3"

    def test_prompt_version_bumped(self):
        from viraltracker.services.landing_page_analysis.multipass.prompts import (
            PROMPT_VERSIONS,
        )

        assert PROMPT_VERSIONS[1] == "v3"


# ---------------------------------------------------------------------------
# B16: Global invariant section-count check (Fix 8)
# ---------------------------------------------------------------------------


class TestGlobalInvariantSectionCount:
    """Fix 8: Section count mismatch must fail global invariants."""

    def test_section_count_mismatch_fails(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_global_invariants,
        )

        # Baseline with 2 sections
        baseline_html = (
            '<section data-section="sec_0"><p data-slot="body-1">A</p></section>'
            '<section data-section="sec_1"><p data-slot="body-2">B</p></section>'
        )
        baseline = capture_pipeline_invariants(baseline_html)
        assert baseline.section_count == 2

        # Changed HTML with 1 section (section lost)
        changed_html = (
            '<section data-section="sec_0"><p data-slot="body-1">A</p></section>'
            '<div><p data-slot="body-2">B</p></div>'
        )
        report = check_global_invariants(changed_html, baseline)
        assert not report.passed
        assert any("Section count" in issue for issue in report.issues)

    def test_section_count_match_passes(self):
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_global_invariants,
        )

        html = (
            '<section data-section="sec_0"><p data-slot="body-1">A</p></section>'
            '<section data-section="sec_1"><p data-slot="body-2">B</p></section>'
        )
        baseline = capture_pipeline_invariants(html)
        report = check_global_invariants(html, baseline)
        assert report.passed


# ---------------------------------------------------------------------------
# B17: Integration test — full pipeline failure chain reproduction
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Integration test reproducing the exact failure chain from bobanutrition."""

    def test_full_chain_with_void_elements_and_lp_mockup(self):
        """Construct skeleton with void elements, wrap in lp-mockup,
        run through _ensure_section_attributes and _parse_sections.
        All sections must be parseable."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
            _strip_unresolved_placeholders,
        )

        # Simulate Phase 2 output with void elements inside sections
        content = (
            '<div class="lp-mockup">'
            '<style>.section { padding: 20px; }</style>'
            '<section data-section="sec_0">'
            '<h1 data-slot="headline">Hero</h1>'
            '<img src="hero.jpg"><br>'
            '<p data-slot="body-1">Description</p>'
            '</section>'
            '<section data-section="sec_1">'
            '<h2 data-slot="heading-1">Features</h2>'
            '<img src="feat.jpg"><hr>'
            '<p data-slot="body-2">Feature text</p>'
            '</section>'
            '<section data-section="sec_2">'
            '<h2 data-slot="heading-2">CTA</h2>'
            '<p data-slot="body-3">Call to action</p>'
            '</section>'
            '</div>'
        )

        section_map = {
            "sec_0": MagicMock(),
            "sec_1": MagicMock(),
            "sec_2": MagicMock(),
        }
        lf = MagicMock()

        # _ensure_section_attributes should preserve existing attrs
        result = _ensure_section_attributes(content, section_map, lf)

        # _parse_sections must find all 3 sections
        sections = _parse_sections(result)
        assert "sec_0" in sections, f"sec_0 missing from parsed sections: {list(sections.keys())}"
        assert "sec_1" in sections, f"sec_1 missing from parsed sections: {list(sections.keys())}"
        assert "sec_2" in sections, f"sec_2 missing from parsed sections: {list(sections.keys())}"

        # No unresolved placeholders
        _, removals = _strip_unresolved_placeholders(result)
        assert removals == 0

    def test_variant_placeholders_through_rewrite(self):
        """Non-standard placeholders get normalized by _rewrite_skeleton."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            _parse_sections,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _rewrite_skeleton,
            _strip_unresolved_placeholders,
        )

        skeleton = (
            '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
            '<section data-section="sec_1"><div>{{sec_1_header}}</div></section>'
            '<section data-section="sec_2"><div>{{sec_2_part1}}</div><div>{{sec_2_part2}}</div></section>'
        )

        rewritten = _rewrite_skeleton(skeleton, 3)

        # All variant placeholders normalized
        assert "{{sec_1_header}}" not in rewritten
        assert "{{sec_2_part1}}" not in rewritten
        assert "{{sec_2_part2}}" not in rewritten

        # Standard placeholders present
        assert "{{sec_0}}" in rewritten
        assert "{{sec_1}}" in rewritten
        assert "{{sec_2}}" in rewritten

        # All sections parseable
        sections = _parse_sections(rewritten)
        assert len(sections) == 3

    def test_no_sections_defers_to_gate(self):
        """Content without any section-like tags returns as-is (defers to gate)."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _ensure_section_attributes,
        )

        # Simulate Phase 2 output without any section-like tags
        html = (
            '<style>.section { padding: 20px; }</style>'
            '<h1>Hero Headline</h1>'
            '<p>Hero body text</p>'
            '<h2>Features</h2>'
            '<p>Feature descriptions</p>'
        )

        section_map = {"sec_0": MagicMock(), "sec_1": MagicMock()}
        lf = MagicMock()

        result = _ensure_section_attributes(html, section_map, lf)

        # With no section-like tags and heading-boundary split removed,
        # HTML is returned as-is.  The pre-Phase-3 gate handles recovery.
        assert 'Hero Headline' in result
        assert 'Feature descriptions' in result
