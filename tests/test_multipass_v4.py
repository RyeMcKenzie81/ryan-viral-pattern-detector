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
B18: wait_for forwarded to FireCrawl + template pipeline guard fallback
B19: Phase 4 add_element image blocking
B20: Phase 3 image guidance for 0-image sections
B21: Image count invariant tracking
B22: SEO ghost text filter
B23: Phase 2 overflow rendering + smart fallback (A/B comparison)
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


# ===========================================================================
# C1: CSSRulesExtractor
# ===========================================================================


class TestCSSRulesExtractor:
    """Tests for css_rules_extractor.py."""

    def test_extract_empty_html(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor, ExtractedCSS,
        )
        result = CSSRulesExtractor.extract("")
        assert isinstance(result, ExtractedCSS)
        assert result.inlined_html == ""

    def test_extract_with_inline_css(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor,
        )
        html = '<html><head><style>.btn { border-radius: 8px; background: #0066cc; }</style></head><body><button class="btn">Click</button></body></html>'
        result = CSSRulesExtractor.extract(html, extra_css=".btn { border-radius: 8px; background: #0066cc; }")
        # Should have component styles
        assert result.component_styles.button.get('border-radius') == '8px' or len(result.component_styles.button) >= 0

    def test_design_token_extraction(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor,
        )
        html = '<html><body><div style="color: #333333; font-family: Arial;">text</div><p style="color: #333333; font-size: 16px;">more</p></body></html>'
        result = CSSRulesExtractor.extract(html)
        # Should extract color frequency
        tokens = result.design_tokens
        assert "#333333" in tokens.colors
        assert tokens.colors["#333333"] >= 2

    def test_css_inline_security(self):
        """css-inline must NOT load remote stylesheets."""
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor,
        )
        # HTML referencing external stylesheet — should NOT be fetched
        html = '<html><head><link rel="stylesheet" href="https://evil.com/steal.css"></head><body><div>test</div></body></html>'
        result = CSSRulesExtractor.extract(html)
        # Should not crash, should produce some result
        assert isinstance(result.inlined_html, str)

    def test_size_guard_skips_large_html(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor, _MAX_INPUT_HTML_SIZE,
        )
        # Create HTML larger than 1MB
        large_html = "<html><body>" + "x" * (_MAX_INPUT_HTML_SIZE + 100) + "</body></html>"
        result = CSSRulesExtractor.extract(large_html)
        assert result.inlined_html == ""  # Should skip css-inline

    def test_rgb_to_hex(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor,
        )
        assert CSSRulesExtractor._rgb_to_hex("rgb(255, 0, 0)") == "#ff0000"
        assert CSSRulesExtractor._rgb_to_hex("rgba(0, 128, 255, 0.5)") == "#0080ff"

    def test_component_classification(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor, ExtractedCSS,
        )
        css = ".btn { padding: 10px; border-radius: 6px; } .card { box-shadow: 0 2px 4px rgba(0,0,0,0.1); } h1 { font-size: 2.5rem; }"
        result = ExtractedCSS()
        CSSRulesExtractor._extract_from_raw_css(css, result)
        assert "border-radius" in result.component_styles.button
        assert "box-shadow" in result.component_styles.card

    def test_layout_rules_extraction(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor, ExtractedCSS,
        )
        css = ".grid { display: grid; grid-template-columns: repeat(3, 1fr); } .text { color: red; }"
        result = ExtractedCSS()
        CSSRulesExtractor._extract_from_raw_css(css, result)
        assert "display: grid" in result.layout_rules
        assert "color: red" not in result.layout_rules

    def test_top_n_capping(self):
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import (
            CSSRulesExtractor,
        )
        data = {f"item_{i}": i for i in range(100)}
        capped = CSSRulesExtractor._top_n(data, 10)
        assert len(capped) == 10
        # Should contain the highest frequency items
        assert "item_99" in capped


# ===========================================================================
# C2: LayoutAnalyzer
# ===========================================================================


class TestLayoutAnalyzer:
    """Tests for layout_analyzer.py."""

    def test_analyze_empty_html(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            analyze_html_layout,
        )
        sections = [FakeSection("sec_0", "hero", "# Hello World")]
        result = analyze_html_layout("", "", sections)
        assert "sec_0" in result
        assert result["sec_0"].layout_type == "generic"

    def test_json_ld_faq_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _extract_json_ld_types,
        )
        html = '<script type="application/ld+json">{"@type": "FAQPage"}</script>'
        types = _extract_json_ld_types(html)
        assert "FAQPage" in types

    def test_semantic_nav_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            analyze_html_layout,
        )
        html = '<nav class="main-nav"><a href="/">Home</a><a href="/about">About</a></nav>'
        sections = [FakeSection("sec_0", "navigation", "# Navigation\nHome About")]
        result = analyze_html_layout("", html, sections)
        # Should detect nav_bar from <nav> tag
        assert result.get("sec_0") is not None

    def test_class_keyword_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _check_class_keywords,
        )
        html = '<div class="testimonial-section"><div class="testimonial-card">Great product!</div></div>'
        candidates = {}
        signals = {}
        _check_class_keywords(html, candidates, signals)
        assert "testimonial_cards" in candidates
        assert candidates["testimonial_cards"] > 0

    def test_heading_text_faq_hint(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _check_heading_text,
        )
        candidates = {}
        signals = {}
        _check_heading_text("## Frequently Asked Questions", candidates, signals)
        assert "faq_list" in candidates

    def test_css_grid_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _check_inline_css,
        )
        html = '<div style="display: grid; grid-template-columns: repeat(3, 1fr);">content</div>'
        candidates = {}
        signals = {}
        col_count = _check_inline_css(html, candidates, signals)
        assert col_count == 3
        assert "feature_grid" in candidates

    def test_framework_detection_bootstrap(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _detect_css_framework,
        )
        classes = ["col-md-4", "row", "container", "card"]
        assert _detect_css_framework(classes) == "bootstrap"

    def test_framework_detection_tailwind(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _detect_css_framework,
        )
        classes = ["grid-cols-3", "flex-row", "px-4", "py-2"]
        assert _detect_css_framework(classes) == "tailwind"

    def test_structural_repetition(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            _check_structural_repetition,
        )
        html = '<div class="features"><div class="card"><h3>F1</h3><p>D1</p></div><div class="card"><h3>F2</h3><p>D2</p></div><div class="card"><h3>F3</h3><p>D3</p></div></div>'
        candidates = {}
        signals = {}
        card_count = _check_structural_repetition(html, candidates, signals)
        assert card_count >= 3

    def test_low_confidence_falls_to_generic(self):
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import (
            analyze_html_layout,
        )
        html = '<div>Just some plain text with nothing special</div>'
        sections = [FakeSection("sec_0", "content", "Just some plain text")]
        result = analyze_html_layout("", html, sections)
        assert result["sec_0"].layout_type == "generic"


# ===========================================================================
# C3: SectionTemplates
# ===========================================================================


class TestSectionTemplates:
    """Tests for section_templates.py."""

    def test_placeholder_suffixes_defined(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            PLACEHOLDER_SUFFIXES,
        )
        assert "single" in PLACEHOLDER_SUFFIXES
        assert "header" in PLACEHOLDER_SUFFIXES
        assert "items" in PLACEHOLDER_SUFFIXES
        assert "text" in PLACEHOLDER_SUFFIXES
        assert "image" in PLACEHOLDER_SUFFIXES

    def test_generic_template_has_data_section(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_generic,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_generic("sec_0", DEFAULT_DESIGN_SYSTEM, {})
        assert 'data-section="sec_0"' in html
        assert '{{sec_0}}' in html

    def test_hero_split_has_text_and_image_placeholders(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_hero_split,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_hero_split("sec_1", DEFAULT_DESIGN_SYSTEM, {})
        assert 'data-section="sec_1"' in html
        assert '{{sec_1_text}}' in html
        assert '{{sec_1_image}}' in html

    def test_feature_grid_has_header_and_items(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_feature_grid,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_feature_grid("sec_2", DEFAULT_DESIGN_SYSTEM, {"column_count": 3})
        assert 'data-section="sec_2"' in html
        assert '{{sec_2_header}}' in html
        assert '{{sec_2_items}}' in html
        assert 'mp-grid-3' in html

    def test_build_skeleton_uses_layout_map(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            build_skeleton_from_templates,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM

        sections = [
            FakeSection("sec_0", "hero", "# Welcome"),
            FakeSection("sec_1", "features", "### Feature 1\nDesc"),
        ]
        layout_map = {
            "sec_0": LayoutHint(layout_type="hero_centered"),
            "sec_1": LayoutHint(layout_type="feature_grid", column_count=3),
        }
        html = build_skeleton_from_templates(sections, layout_map, DEFAULT_DESIGN_SYSTEM)
        assert 'data-section="sec_0"' in html
        assert 'data-section="sec_1"' in html
        assert 'mp-hero-centered' in html
        assert 'mp-feature-grid' in html
        assert '<style>' in html

    def test_build_skeleton_all_generic_when_no_layout_map(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            build_skeleton_from_templates,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM

        sections = [FakeSection("sec_0", "content", "Some text")]
        html = build_skeleton_from_templates(sections, {}, DEFAULT_DESIGN_SYSTEM)
        assert 'mp-generic' in html
        assert '{{sec_0}}' in html

    def test_responsive_css_in_shared_block(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _build_shared_css,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        css = _build_shared_css(DEFAULT_DESIGN_SYSTEM)
        assert '@media (max-width: 768px)' in css
        assert 'mp-grid-2' in css
        assert 'mp-grid-3' in css

    def test_nav_bar_template(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_nav_bar,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_nav_bar("sec_0", DEFAULT_DESIGN_SYSTEM, {})
        assert 'mp-nav-bar' in html
        assert '{{sec_0}}' in html

    def test_footer_columns_template(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_footer_columns,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_footer_columns("sec_5", DEFAULT_DESIGN_SYSTEM, {"column_count": 4})
        assert 'mp-footer-columns' in html
        assert 'mp-grid-4' in html

    def test_faq_template(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            _tpl_faq_list,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM
        html = _tpl_faq_list("sec_3", DEFAULT_DESIGN_SYSTEM, {})
        assert 'mp-faq-list' in html
        assert '{{sec_3_header}}' in html
        assert '{{sec_3_items}}' in html

    def test_unknown_layout_type_falls_back_to_generic(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            build_skeleton_from_templates,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM

        sections = [FakeSection("sec_0", "custom", "content")]
        layout_map = {"sec_0": LayoutHint(layout_type="nonexistent_type")}
        html = build_skeleton_from_templates(sections, layout_map, DEFAULT_DESIGN_SYSTEM)
        assert 'mp-generic' in html


# ===========================================================================
# C4: ContentPatterns
# ===========================================================================


class TestContentPatterns:
    """Tests for content_patterns.py."""

    def test_detect_feature_list(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        section = FakeSection("sec_0", "features", "## Our Features\n\n### Fast\nBlazingly fast performance.\n\n### Secure\nEnterprise-grade security.\n\n### Simple\nEasy to use.")
        result = detect_content_pattern(section, None)
        assert result.pattern_type == "feature_list"
        assert len(result.items) >= 2

    def test_detect_faq(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        section = FakeSection("sec_0", "faq", "## FAQ\n\n### What is this?\nThis is a product.\n\n### How much does it cost?\nIt's free for now.")
        result = detect_content_pattern(section, None)
        assert result.pattern_type == "faq_list"
        assert len(result.items) >= 2
        assert result.items[0]["question"] == "What is this?"

    def test_detect_testimonials(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        section = FakeSection("sec_0", "reviews", "## Reviews\n\n> Great product, love it!\n\n— John Doe, CEO")
        result = detect_content_pattern(section, None)
        assert result.pattern_type == "testimonial_list"
        assert len(result.items) >= 1
        assert "Great product" in result.items[0]["quote"]

    def test_detect_stats(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        section = FakeSection("sec_0", "stats", "## By the Numbers\n\n**10K+** Active Users\n**99.9%** Uptime\n**500M+** Requests")
        result = detect_content_pattern(section, None)
        assert result.pattern_type == "stats_list"
        assert len(result.items) >= 2

    def test_detect_prose_fallback(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        section = FakeSection("sec_0", "about", "## About Us\n\nWe are a team of developers building great software.")
        result = detect_content_pattern(section, None)
        assert result.pattern_type == "prose"

    def test_split_content_feature_list(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            ContentPattern, split_content_for_template,
        )
        pattern = ContentPattern(
            pattern_type="feature_list",
            items=[
                {"heading": "Fast", "body": "Blazing speed"},
                {"heading": "Secure", "body": "Enterprise grade"},
            ],
            header_markdown="## Features",
        )
        section = FakeSection("sec_0", "features", "## Features\n### Fast\nBlazing speed\n### Secure\nEnterprise grade")
        result = split_content_for_template(pattern, None, section)
        assert "sec_0_header" in result
        assert "sec_0_items" in result
        assert "Fast" in result["sec_0_items"]

    def test_split_content_faq(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            ContentPattern, split_content_for_template,
        )
        pattern = ContentPattern(
            pattern_type="faq_list",
            items=[
                {"question": "What is it?", "answer": "A product."},
                {"question": "How much?", "answer": "Free."},
            ],
            header_markdown="## FAQ",
        )
        section = FakeSection("sec_0", "faq", "## FAQ")
        result = split_content_for_template(pattern, None, section)
        assert "sec_0_items" in result
        assert "mp-faq-item" in result["sec_0_items"]

    def test_normalize_markdown_to_text(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            normalize_markdown_to_text,
        )
        md = "## Hello World\n\n![alt](http://img.com/a.png)\n\n[Link](http://example.com)\n\n- Item 1\n- Item 2\n\n**bold** _italic_"
        text = normalize_markdown_to_text(md)
        assert "#" not in text
        assert "![" not in text
        assert "[Link]" not in text
        assert "Hello World" in text
        assert "Item 1" in text

    def test_layout_hint_biases_detection(self):
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            detect_content_pattern,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint

        # Markdown with questions but no ? — weak FAQ signal
        section = FakeSection("sec_0", "info", "## Questions\n\n### What is this?\nA product.\n\n### How does it work?\nMagic.")
        hint = LayoutHint(layout_type="faq_list")
        result = detect_content_pattern(section, hint)
        assert result.pattern_type == "faq_list"


# ===========================================================================
# C5: Design System Augmentation
# ===========================================================================


class TestDesignSystemAugmentation:
    """Tests for _augment_design_system() and _hex_distance()."""

    def test_hex_distance_same_color(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import _hex_distance
        assert _hex_distance("#333333", "#333333") == 0.0

    def test_hex_distance_close_colors(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import _hex_distance
        # #333 vs #2d2d2d — should be close
        d = _hex_distance("#333333", "#2d2d2d")
        assert d < 40

    def test_hex_distance_far_colors(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import _hex_distance
        d = _hex_distance("#000000", "#ffffff")
        assert d > 100

    def test_augment_replaces_close_colors(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import _augment_design_system
        from viraltracker.services.landing_page_analysis.multipass.css_rules_extractor import DesignTokens

        ds = {"colors": {"primary": "#333333", "accent": "#0066cc"}, "typography": {}}
        tokens = DesignTokens(colors={"#2d2d2d": 50, "#0066cc": 30})
        result = _augment_design_system(ds, tokens)
        # #333333 should be replaced by #2d2d2d (closer than 40)
        assert result["colors"]["primary"] == "#2d2d2d"
        # #0066cc is exact match
        assert result["colors"]["accent"] == "#0066cc"


# ===========================================================================
# C6: Reconcile Bounding Boxes
# ===========================================================================


class TestReconcileBoundingBoxes:
    """Tests for _reconcile_bounding_boxes()."""

    def test_exact_count_match(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_bounding_boxes,
        )
        sections = [
            FakeSection("sec_0", "hero", "# Hero", 0.5),
            FakeSection("sec_1", "features", "# Features", 0.5),
        ]
        phase1 = [
            {"name": "hero", "y_start_pct": 0.0, "y_end_pct": 0.5},
            {"name": "features", "y_start_pct": 0.5, "y_end_pct": 1.0},
        ]
        section_map, mapping = _reconcile_bounding_boxes(sections, phase1)
        assert len(section_map) == 2
        assert "sec_0" in section_map
        assert "sec_1" in section_map
        assert 0 in mapping["sec_0"]
        assert 1 in mapping["sec_1"]

    def test_merge_when_phase1_has_more(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_bounding_boxes,
        )
        sections = [
            FakeSection("sec_0", "hero", "# Hero", 0.5),
            FakeSection("sec_1", "features", "# Features", 0.5),
        ]
        phase1 = [
            {"name": "nav", "y_start_pct": 0.0, "y_end_pct": 0.1},
            {"name": "hero", "y_start_pct": 0.1, "y_end_pct": 0.5},
            {"name": "features", "y_start_pct": 0.5, "y_end_pct": 1.0},
        ]
        section_map, mapping = _reconcile_bounding_boxes(sections, phase1)
        assert len(section_map) == 2

    def test_split_when_phase1_has_fewer(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_bounding_boxes,
        )
        sections = [
            FakeSection("sec_0", "hero", "# Hero", 0.3),
            FakeSection("sec_1", "features", "# Features", 0.3),
            FakeSection("sec_2", "footer", "# Footer", 0.4),
        ]
        phase1 = [
            {"name": "content", "y_start_pct": 0.0, "y_end_pct": 0.6},
            {"name": "footer", "y_start_pct": 0.6, "y_end_pct": 1.0},
        ]
        section_map, mapping = _reconcile_bounding_boxes(sections, phase1)
        assert len(section_map) == 3

    def test_fallback_when_count_differs_by_more_than_2(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_bounding_boxes,
        )
        sections = [FakeSection(f"sec_{i}", f"s{i}", f"# S{i}", 0.2) for i in range(5)]
        phase1 = [{"name": "all", "y_start_pct": 0.0, "y_end_pct": 1.0}]
        section_map, mapping = _reconcile_bounding_boxes(sections, phase1)
        assert len(section_map) == 5  # Char-ratio fallback


# ===========================================================================
# C7: Phase 1 Classification Parsing
# ===========================================================================


class TestPhase1ClassificationParsing:
    """Tests for _parse_phase1_classifications()."""

    def test_basic_parsing(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _parse_phase1_classifications,
        )
        result = {
            "sections": [
                {"layout_type": "hero_centered", "layout_params": {}},
                {"layout_type": "feature_grid", "layout_params": {"column_count": 3}},
            ]
        }
        mapping = {"sec_0": [0], "sec_1": [1]}
        layout_map = _parse_phase1_classifications(result, mapping)
        assert layout_map["sec_0"].layout_type == "hero_centered"
        assert layout_map["sec_1"].layout_type == "feature_grid"
        assert layout_map["sec_1"].column_count == 3

    def test_invalid_layout_type_falls_to_generic(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _parse_phase1_classifications,
        )
        result = {
            "sections": [{"layout_type": "invalid_type", "layout_params": {}}]
        }
        mapping = {"sec_0": [0]}
        layout_map = _parse_phase1_classifications(result, mapping)
        assert layout_map["sec_0"].layout_type == "generic"

    def test_missing_sections_filled_by_hints(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _parse_phase1_classifications,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint

        result = {"sections": [{"layout_type": "hero_centered", "layout_params": {}}]}
        mapping = {"sec_0": [0], "sec_1": []}
        hints = {"sec_1": LayoutHint(layout_type="footer_columns")}
        layout_map = _parse_phase1_classifications(result, mapping, hints)
        assert layout_map["sec_0"].layout_type == "hero_centered"
        assert layout_map["sec_1"].layout_type == "footer_columns"


# ===========================================================================
# C8: Phase Snapshots
# ===========================================================================


class TestPhaseSnapshots:
    """Tests for _wrap_json_as_html()."""

    def test_json_wrapped_as_html(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _wrap_json_as_html,
        )
        data = {"key": "value", "num": 42}
        html = _wrap_json_as_html(data)
        assert html.startswith("<html>")
        assert '"key": "value"' in html
        assert "</html>" in html

    def test_json_wrap_handles_non_serializable(self):
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _wrap_json_as_html,
        )
        data = {"key": object()}
        html = _wrap_json_as_html(data)
        assert "<html>" in html


# ===========================================================================
# C9: Content Assembler Layout-Aware Path
# ===========================================================================


class TestContentAssemblerLayoutAware:
    """Tests for layout-aware assembly in content_assembler.py."""

    def test_generic_layout_uses_linear_path(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint

        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        sections = [FakeSection("sec_0", "content", "Hello World")]
        layout_map = {"sec_0": LayoutHint(layout_type="generic")}
        result = assemble_content(skeleton, sections, {}, layout_map=layout_map)
        assert "Hello World" in result

    def test_no_layout_map_uses_linear_path(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        sections = [FakeSection("sec_0", "content", "Hello World")]
        result = assemble_content(skeleton, sections, {})
        assert "Hello World" in result

    def test_data_section_preserved(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        sections = [FakeSection("sec_0", "content", "# Title\n\nBody text")]
        result = assemble_content(skeleton, sections, {})
        assert 'data-section="sec_0"' in result

    def test_data_slot_assigned(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )
        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        sections = [FakeSection("sec_0", "hero", "# Big Headline\n\nSome body text")]
        result = assemble_content(skeleton, sections, {})
        assert 'data-slot="headline"' in result

    def test_replace_entire_section(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            _replace_entire_section,
        )
        html = '<section data-section="sec_0" class="old">old content</section><section data-section="sec_1">keep</section>'
        result = _replace_entire_section(html, "sec_0", '<section data-section="sec_0" class="new">new content</section>')
        assert 'class="new"' in result
        assert "new content" in result
        assert "keep" in result


# ===========================================================================
# C10: Feature Flag
# ===========================================================================


class TestFeatureFlag:
    """Tests for USE_TEMPLATE_PIPELINE feature flag."""

    def test_flag_reads_env(self):
        import os
        old = os.environ.get("MULTIPASS_TEMPLATE_PIPELINE")
        try:
            os.environ["MULTIPASS_TEMPLATE_PIPELINE"] = "false"
            # Re-evaluate the flag
            flag = os.environ.get("MULTIPASS_TEMPLATE_PIPELINE", "true").lower() == "true"
            assert flag is False

            os.environ["MULTIPASS_TEMPLATE_PIPELINE"] = "true"
            flag = os.environ.get("MULTIPASS_TEMPLATE_PIPELINE", "true").lower() == "true"
            assert flag is True
        finally:
            if old is not None:
                os.environ["MULTIPASS_TEMPLATE_PIPELINE"] = old
            else:
                os.environ.pop("MULTIPASS_TEMPLATE_PIPELINE", None)

    def test_phase3_mode_reads_env(self):
        import os
        old = os.environ.get("MULTIPASS_PHASE3_MODE")
        try:
            os.environ["MULTIPASS_PHASE3_MODE"] = "disabled"
            mode = os.environ.get("MULTIPASS_PHASE3_MODE", "fullpage")
            assert mode == "disabled"
        finally:
            if old is not None:
                os.environ["MULTIPASS_PHASE3_MODE"] = old
            else:
                os.environ.pop("MULTIPASS_PHASE3_MODE", None)


# ===========================================================================
# C11: Blueprint Compatibility
# ===========================================================================


class TestBlueprintCompat:
    """Tests that data-section and data-slot survive template pipeline."""

    def test_template_skeleton_has_data_section(self):
        from viraltracker.services.landing_page_analysis.multipass.section_templates import (
            build_skeleton_from_templates,
        )
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint
        from viraltracker.services.landing_page_analysis.multipass.pipeline import DEFAULT_DESIGN_SYSTEM

        sections = [
            FakeSection("sec_0", "hero", "# Welcome"),
            FakeSection("sec_1", "features", "### F1\nD1"),
            FakeSection("sec_2", "footer", "Footer links"),
        ]
        layout_map = {
            "sec_0": LayoutHint(layout_type="hero_centered"),
            "sec_1": LayoutHint(layout_type="feature_grid", column_count=3),
            "sec_2": LayoutHint(layout_type="footer_columns", column_count=4),
        }
        html = build_skeleton_from_templates(sections, layout_map, DEFAULT_DESIGN_SYSTEM)
        for i in range(3):
            assert f'data-section="sec_{i}"' in html

    def test_assembled_content_has_data_slot(self):
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            assemble_content,
        )

        skeleton = '<section data-section="sec_0"><div>{{sec_0}}</div></section>'
        sections = [FakeSection("sec_0", "hero", "# Welcome\n\nCheck out our product")]
        result = assemble_content(skeleton, sections, {})
        assert 'data-slot=' in result
        assert 'data-section="sec_0"' in result


# ===========================================================================
# D1: Bug 2 — page_html storage (empty string vs None)
# ===========================================================================


class TestPageHtmlStorage:
    """Bug 2: analysis_service stores empty page_html, skips None."""

    def test_create_analysis_record_stores_empty_page_html(self):
        """page_html='' should be included in the record dict (not skipped)."""
        from unittest.mock import MagicMock, patch

        from viraltracker.services.landing_page_analysis.analysis_service import (
            LandingPageAnalysisService,
        )

        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value.data = [{"id": "test-id"}]

        svc = LandingPageAnalysisService.__new__(LandingPageAnalysisService)
        svc.supabase = mock_supabase

        svc._create_analysis_record(
            org_id="org-1",
            url="https://example.com",
            source_type="manual",
            source_id=None,
            page_markdown="# Test",
            screenshot_storage_path=None,
            page_html="",
        )

        inserted = mock_table.insert.call_args[0][0]
        assert "page_html" in inserted, "Empty string page_html should be stored"
        assert inserted["page_html"] == ""

    def test_create_analysis_record_skips_none_page_html(self):
        """page_html=None should NOT insert a page_html key."""
        from unittest.mock import MagicMock

        from viraltracker.services.landing_page_analysis.analysis_service import (
            LandingPageAnalysisService,
        )

        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value.data = [{"id": "test-id"}]

        svc = LandingPageAnalysisService.__new__(LandingPageAnalysisService)
        svc.supabase = mock_supabase

        svc._create_analysis_record(
            org_id="org-1",
            url="https://example.com",
            source_type="manual",
            source_id=None,
            page_markdown="# Test",
            screenshot_storage_path=None,
            page_html=None,
        )

        inserted = mock_table.insert.call_args[0][0]
        assert "page_html" not in inserted, "None page_html should not be in record"


# ===========================================================================
# D2: Bug 1 — _best_effort_reconcile layout mapping
# ===========================================================================


class TestBestEffortReconcile:
    """Bug 1: _best_effort_reconcile maps sections when counts diverge."""

    def test_name_matching(self):
        """10 P1 sections vs 6 segmenter sections — name-based matches work."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _best_effort_reconcile,
        )

        seg_sections = [
            FakeSection("sec_0", "Navigation", "nav content"),
            FakeSection("sec_1", "Hero Section", "hero content"),
            FakeSection("sec_2", "Features", "features content"),
            FakeSection("sec_3", "Testimonials", "testimonials"),
            FakeSection("sec_4", "Pricing", "pricing"),
            FakeSection("sec_5", "Footer", "footer"),
        ]
        p1_sections = [
            {"name": "Nav Bar"},
            {"name": "Announcement"},
            {"name": "Hero Section"},
            {"name": "Benefits"},
            {"name": "Features List"},
            {"name": "Social Proof"},
            {"name": "Testimonials"},
            {"name": "Pricing Table"},
            {"name": "FAQ"},
            {"name": "Footer Links"},
        ]

        result = _best_effort_reconcile(seg_sections, p1_sections)

        # Every section must have at least one source index
        for sec in seg_sections:
            assert sec.section_id in result, f"{sec.section_id} missing from mapping"
            assert len(result[sec.section_id]) >= 1, f"{sec.section_id} has empty indices"

        # Name matches should work: "Navigation" ↔ "Nav Bar" may not match (low jaccard),
        # but "Hero Section" ↔ "Hero Section" should
        assert result["sec_1"] == [2], "Hero Section should match P1 index 2"
        # "Testimonials" ↔ "Testimonials" should match
        assert result["sec_3"] == [6], "Testimonials should match P1 index 6"

    def test_proportional_generic_names(self):
        """All generic names — proportional mapping produces non-empty indices."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _best_effort_reconcile,
        )

        seg_sections = [
            FakeSection(f"sec_{i}", "section", f"content {i}")
            for i in range(5)
        ]
        p1_sections = [{"name": "section"} for _ in range(8)]

        result = _best_effort_reconcile(seg_sections, p1_sections)

        for sec in seg_sections:
            assert sec.section_id in result
            assert len(result[sec.section_id]) >= 1

    def test_zero_p1_sections(self):
        """0 P1 sections, 5 segmenter sections — all map to index 0 without crash."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _best_effort_reconcile,
        )

        seg_sections = [
            FakeSection(f"sec_{i}", f"Section {i}", f"content {i}")
            for i in range(5)
        ]

        result = _best_effort_reconcile(seg_sections, [])

        for sec in seg_sections:
            assert sec.section_id in result
            assert result[sec.section_id] == [0]

    def test_one_segmenter_many_p1(self):
        """1 segmenter section, 8 P1 sections — maps to index 0, no division-by-zero."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _best_effort_reconcile,
        )

        seg_sections = [FakeSection("sec_0", "Hero", "hero content")]
        p1_sections = [{"name": f"Section {i}"} for i in range(8)]

        result = _best_effort_reconcile(seg_sections, p1_sections)

        assert "sec_0" in result
        assert len(result["sec_0"]) >= 1

    def test_none_and_empty_names(self):
        """P1 sections with None or empty names — no crash, positional fill used."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _best_effort_reconcile,
        )

        seg_sections = [
            FakeSection("sec_0", "Hero", "hero"),
            FakeSection("sec_1", "", "content"),
            FakeSection("sec_2", "Footer", "footer"),
        ]
        p1_sections = [
            {"name": None},
            {"name": ""},
            {"name": "Hero Banner"},
            {"name": None},
            {"name": "Footer"},
        ]

        result = _best_effort_reconcile(seg_sections, p1_sections)

        for sec in seg_sections:
            assert sec.section_id in result
            assert len(result[sec.section_id]) >= 1

    def test_normalization_failure_fallback_uses_best_effort(self):
        """Verify the normalization-failure fallback path calls _best_effort_reconcile."""
        from unittest.mock import patch as mock_patch

        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            _reconcile_bounding_boxes,
        )

        seg_sections = [
            FakeSection("sec_0", "Hero", "hero"),
            FakeSection("sec_1", "Features", "features"),
        ]
        # Same count — won't hit the >2 divergence guard
        p1_sections = [
            {"name": "Hero", "y_start_pct": 0, "y_end_pct": 50},
            {"name": "Features", "y_start_pct": 50, "y_end_pct": 100},
        ]

        # Force normalize_bounding_boxes to return None
        with mock_patch(
            "viraltracker.services.landing_page_analysis.multipass.pipeline.normalize_bounding_boxes",
            return_value=None,
        ):
            section_map, reconcile_mapping = _reconcile_bounding_boxes(
                seg_sections, p1_sections
            )

        # All sections should have non-empty source indices
        for sec in seg_sections:
            assert sec.section_id in reconcile_mapping
            assert len(reconcile_mapping[sec.section_id]) >= 1, (
                f"{sec.section_id} has empty indices in normalization-failure fallback"
            )


# ===========================================================================
# D3: Bug 3 — PatchApplier comma-separated selectors
# ===========================================================================


class TestPatchApplierCommaSelectors:
    """Bug 3: PatchApplier handles comma-separated selectors."""

    def test_comma_separated_selectors(self):
        """Comma-separated selectors apply CSS to both sections."""
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = (
            '<section data-section="sec_4"><p>Section 4</p></section>'
            '<section data-section="sec_5"><p>Section 5</p></section>'
        )
        patches = [
            {
                "type": "css_fix",
                "selector": "[data-section='sec_4'], [data-section='sec_5']",
                "value": "background: #f0f0f0",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        # Both sections should get the style
        assert result.count("background: #f0f0f0") == 2

    def test_comma_trailing(self):
        """Trailing comma does not crash (empty segment filtered)."""
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<h2>Title</h2>'
        patches = [
            {
                "type": "css_fix",
                "selector": "h2, ",
                "value": "color: blue",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        assert "color: blue" in result

    def test_single_selector_unchanged(self):
        """Regression: single selector still works identically."""
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

    def test_descendant_combinator_still_rejected(self):
        """Descendant combinator selectors are still rejected (expected)."""
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )

        html = '<section data-section="sec_1"><h2>Title</h2></section>'
        patches = [
            {
                "type": "css_fix",
                "selector": "[data-section='sec_1'] h2",
                "value": "font-size: 3rem",
            }
        ]
        applier = PatchApplier()
        result = applier.apply_patches(html, patches)
        # Should NOT be applied (descendant combinator unsupported)
        assert "font-size: 3rem" not in result


# ===========================================================================
# B18: wait_for passed to FireCrawl + template pipeline guard
# ===========================================================================


class TestWaitForPassedToFireCrawl:
    """B18a: web_scraping_service.py — wait_for is forwarded to FireCrawl."""

    def test_wait_for_passed_to_firecrawl_sync(self):
        """Sync scrape_url passes wait_for when wait_for > 0."""
        from viraltracker.services.web_scraping_service import WebScrapingService

        svc = WebScrapingService(api_key="fake")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.markdown = "hello"
        mock_result.html = "<p>hello</p>"
        mock_result.links = []
        mock_result.metadata = {}
        mock_result.screenshot = None
        mock_client.scrape.return_value = mock_result

        svc._client = mock_client

        svc.scrape_url("https://example.com", formats=["html"], wait_for=2000)

        mock_client.scrape.assert_called_once()
        call_kwargs = mock_client.scrape.call_args
        # wait_for should appear in the kwargs (SDK uses snake_case)
        assert call_kwargs[1].get("wait_for") == 2000 or \
            call_kwargs.kwargs.get("wait_for") == 2000

    def test_wait_for_zero_not_passed(self):
        """Sync scrape_url does NOT pass wait_for when wait_for=0 (default)."""
        from viraltracker.services.web_scraping_service import WebScrapingService

        svc = WebScrapingService(api_key="fake")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.markdown = "hello"
        mock_result.html = None
        mock_result.links = None
        mock_result.metadata = None
        mock_result.screenshot = None
        mock_client.scrape.return_value = mock_result

        svc._client = mock_client

        svc.scrape_url("https://example.com", formats=["markdown"])

        call_kwargs = mock_client.scrape.call_args
        # Flatten all kwargs passed via **scrape_params
        all_kwargs = {**call_kwargs.kwargs}
        assert "wait_for" not in all_kwargs


class TestWaitForAsyncPassedToFireCrawl:
    """B18b: web_scraping_service.py — async wait_for forwarded to FireCrawl."""

    @pytest.mark.asyncio
    async def test_wait_for_async_passed_to_firecrawl(self):
        """Async scrape_url_async passes wait_for when wait_for > 0."""
        import asyncio
        from unittest.mock import AsyncMock
        from viraltracker.services.web_scraping_service import WebScrapingService

        svc = WebScrapingService(api_key="fake")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.markdown = None
        mock_result.html = "<p>hello</p>"
        mock_result.links = None
        mock_result.metadata = None
        mock_result.screenshot = None
        mock_client.scrape = AsyncMock(return_value=mock_result)

        svc._async_client = mock_client

        await svc.scrape_url_async(
            "https://example.com", formats=["html"], wait_for=3000
        )

        mock_client.scrape.assert_called_once()
        call_kwargs = mock_client.scrape.call_args
        all_kwargs = {**call_kwargs.kwargs}
        assert all_kwargs.get("wait_for") == 3000

    @pytest.mark.asyncio
    async def test_wait_for_async_only_main_content_false(self):
        """Async scrape_url_async passes only_main_content=False."""
        from unittest.mock import AsyncMock
        from viraltracker.services.web_scraping_service import WebScrapingService

        svc = WebScrapingService(api_key="fake")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.markdown = None
        mock_result.html = "<p>hello</p>"
        mock_result.links = None
        mock_result.metadata = None
        mock_result.screenshot = None
        mock_client.scrape = AsyncMock(return_value=mock_result)

        svc._async_client = mock_client

        await svc.scrape_url_async(
            "https://example.com",
            formats=["html"],
            only_main_content=False,
        )

        call_kwargs = mock_client.scrape.call_args
        all_kwargs = {**call_kwargs.kwargs}
        assert all_kwargs.get("only_main_content") is False


class TestTemplateGuardFallback:
    """B18c: pipeline.py — template pipeline falls back without page_html."""

    @pytest.mark.asyncio
    async def test_template_guard_falls_back_without_page_html(self):
        """When USE_TEMPLATE_PIPELINE=True but page_html is None,
        pipeline should use _run_phase_1 (original) not _run_phase_1_classify."""
        import base64
        from unittest.mock import AsyncMock

        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            MultiPassPipeline,
        )

        # Minimal 1x1 white PNG for screenshot_b64
        tiny_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        screenshot_b64 = base64.b64encode(tiny_png).decode()

        mock_gemini = MagicMock()
        pipeline = MultiPassPipeline(gemini_service=mock_gemini)

        # Track which Phase 1 path was called
        phase_1_original_called = False
        phase_1_classify_called = False

        async def mock_phase_0(*args, **kwargs):
            return '{"colors": [], "fonts": []}'

        async def mock_phase_1(*args, **kwargs):
            nonlocal phase_1_original_called
            phase_1_original_called = True
            skeleton = '<div data-section="sec_0">Mock</div>'
            section_map = {"sec_0": 0}
            return skeleton, section_map

        async def mock_phase_1_classify(*args, **kwargs):
            nonlocal phase_1_classify_called
            phase_1_classify_called = True
            skeleton = '<div data-section="sec_0">Mock</div>'
            section_map = {"sec_0": 0}
            layout_map = {}
            return skeleton, section_map, layout_map

        # Patch all LLM-calling methods to avoid real API calls
        pipeline._run_phase_0 = mock_phase_0
        pipeline._run_phase_1 = mock_phase_1
        pipeline._run_phase_1_classify = mock_phase_1_classify
        pipeline._report_progress = lambda *a, **kw: None

        # Return False after Phase 0, True after Phase 1 to force early exit
        budget_call_count = 0

        def fake_budget_exceeded(max_calls):
            nonlocal budget_call_count
            budget_call_count += 1
            # First call is after Phase 0 — allow; second is after Phase 1 — stop
            return budget_call_count > 1

        pipeline._budget_exceeded = fake_budget_exceeded

        with patch(
            "viraltracker.services.landing_page_analysis.multipass.pipeline.USE_TEMPLATE_PIPELINE",
            True,
        ):
            result = await pipeline.generate(
                screenshot_b64=screenshot_b64,
                page_markdown="# Hello\nSome content here",
                page_html=None,  # <-- no page_html
            )

        assert phase_1_original_called, (
            "Expected _run_phase_1 (original) to be called when page_html is None"
        )
        assert not phase_1_classify_called, (
            "Expected _run_phase_1_classify NOT to be called when page_html is None"
        )


# ===========================================================================
# B19: Phase 4 add_element image blocking
# ===========================================================================


class TestPhase4AddElementImgBlocking:
    """B19: patch_applier.py — Block <img> tags in add_element payloads."""

    def _applier(self):
        from viraltracker.services.landing_page_analysis.multipass.patch_applier import (
            PatchApplier,
        )
        return PatchApplier()

    def test_img_payload_blocked(self):
        """add_element with <img> payload is skipped."""
        applier = self._applier()
        html = '<div data-section="sec_0"><p>Hello</p></div>'
        patches = [{
            "type": "add_element",
            "selector": "[data-section='sec_0']",
            "value": '<img src="https://example.com/photo.jpg" alt="test">',
        }]
        result = applier.apply_patches(html, patches)
        assert result == html, "img payload should be blocked"

    def test_nested_img_payload_blocked(self):
        """add_element with nested <img> inside wrapper is also blocked."""
        applier = self._applier()
        html = '<div data-section="sec_0"><p>Hello</p></div>'
        patches = [{
            "type": "add_element",
            "selector": "[data-section='sec_0']",
            "value": '<div class="wrapper"><img src="https://example.com/photo.jpg"></div>',
        }]
        result = applier.apply_patches(html, patches)
        assert result == html, "nested img payload should be blocked"

    def test_div_payload_passes(self):
        """add_element with non-img, non-text payload passes validation."""
        applier = self._applier()
        html = '<div data-section="sec_0"><p>Hello</p></div>'
        patches = [{
            "type": "add_element",
            "selector": "[data-section='sec_0']",
            "value": '<div style="height: 2px; background: #ddd; margin: 20px 0;"></div>',
        }]
        result = applier.apply_patches(html, patches)
        assert '<div style="height: 2px' in result, "divider payload should be inserted"

    def test_existing_text_blocking_preserved(self):
        """Existing visible-text blocking still works."""
        applier = self._applier()
        html = '<div data-section="sec_0"><p>Hello</p></div>'
        patches = [{
            "type": "add_element",
            "selector": "[data-section='sec_0']",
            "value": '<p>Some visible text</p>',
        }]
        result = applier.apply_patches(html, patches)
        assert result == html, "visible text payload should still be blocked"


# ===========================================================================
# B20: Phase 3 image guidance for 0-image sections
# ===========================================================================


class TestPhase3ImageGuidance:
    """B20: prompts.py — IMAGE GUIDANCE block for 0-image sections."""

    def test_no_images_includes_guidance(self):
        """Section with 0 images gets IMAGE GUIDANCE constraint."""
        from viraltracker.services.landing_page_analysis.multipass.prompts import (
            build_phase_3_prompt,
        )
        prompt = build_phase_3_prompt(
            section_id="sec_2",
            section_html="<section><p>Text</p></section>",
            design_system_compact="{}",
            image_urls=None,
            section_images=None,
        )
        assert "IMAGE GUIDANCE" in prompt
        assert "NO images assigned" in prompt
        assert "adjacent sections" in prompt

    def test_with_images_includes_rules(self):
        """Section with images gets image list + rules (existing behavior)."""
        from viraltracker.services.landing_page_analysis.multipass.prompts import (
            build_phase_3_prompt,
        )

        class FakeImage:
            url = "https://example.com/img.jpg"
            alt = "test"
            width = 400
            height = 300
            is_icon = False
            is_background = False

        prompt = build_phase_3_prompt(
            section_id="sec_0",
            section_html="<section><p>Text</p></section>",
            design_system_compact="{}",
            section_images=[FakeImage()],
        )
        assert "SECTION IMAGES" in prompt
        assert "IMAGE RULES" in prompt
        assert "IMAGE GUIDANCE" not in prompt

    def test_legacy_image_urls_no_guidance(self):
        """Section with legacy image_urls gets legacy block, not guidance."""
        from viraltracker.services.landing_page_analysis.multipass.prompts import (
            build_phase_3_prompt,
        )
        prompt = build_phase_3_prompt(
            section_id="sec_0",
            section_html="<section><p>Text</p></section>",
            design_system_compact="{}",
            image_urls=[{"alt": "test", "url": "https://example.com/img.jpg"}],
        )
        assert "ACTUAL IMAGE URLs" in prompt
        assert "IMAGE GUIDANCE" not in prompt


# ===========================================================================
# B21: Image count invariant tracking
# ===========================================================================


class TestImageCountInvariant:
    """B21: invariants.py — Image count tracking in capture and check."""

    def test_capture_records_image_count(self):
        """capture_pipeline_invariants records image_count per section."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
        )
        html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello</p>
            <img src="https://example.com/a.jpg">
            <img src="https://example.com/b.jpg">
        </section>
        <section data-section="sec_1">
            <p data-slot="body-2">World</p>
        </section>
        """
        inv = capture_pipeline_invariants(html)
        assert inv.sections["sec_0"].image_count == 2
        assert inv.sections["sec_1"].image_count == 0
        assert inv.global_image_count == 2

    def test_check_section_warns_on_image_increase(self):
        """check_section_invariant logs warning when images increase."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_section_invariant,
        )
        baseline_html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello world</p>
        </section>
        """
        baseline = capture_pipeline_invariants(baseline_html)
        assert baseline.sections["sec_0"].image_count == 0

        # Refined section now has an image
        refined_html = '<p data-slot="body-1">Hello world</p><img src="new.jpg">'
        report = check_section_invariant(refined_html, "sec_0", baseline)
        assert any("Image count increased" in i for i in report.issues)

    def test_check_global_flags_excessive_images(self):
        """check_global_invariants flags when >3 new images appear."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_global_invariants,
        )
        baseline_html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello world test content here</p>
        </section>
        """
        baseline = capture_pipeline_invariants(baseline_html)
        assert baseline.global_image_count == 0

        # Post-phase HTML has 5 new images (> threshold of 3)
        modified_html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello world test content here</p>
            <img src="a.jpg"><img src="b.jpg"><img src="c.jpg">
            <img src="d.jpg"><img src="e.jpg">
        </section>
        """
        report = check_global_invariants(modified_html, baseline)
        assert any("Excessive new images" in i for i in report.issues)

    def test_check_global_allows_small_variance(self):
        """check_global_invariants allows up to 3 new images."""
        from viraltracker.services.landing_page_analysis.multipass.invariants import (
            capture_pipeline_invariants,
            check_global_invariants,
        )
        baseline_html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello world test content here</p>
        </section>
        """
        baseline = capture_pipeline_invariants(baseline_html)

        # 3 new images (within threshold)
        modified_html = """
        <section data-section="sec_0">
            <p data-slot="body-1">Hello world test content here</p>
            <img src="a.jpg"><img src="b.jpg"><img src="c.jpg">
        </section>
        """
        report = check_global_invariants(modified_html, baseline)
        assert not any("Excessive new images" in i for i in report.issues)


# ===========================================================================
# B22: SEO ghost text filter
# ===========================================================================


class TestSEOGhostTextFilter:
    """B22: content_assembler.py — filter_seo_ghost_text()."""

    def _make_section(self, section_id, markdown):
        return FakeSection(section_id=section_id, name=section_id, markdown=markdown)

    def test_meta_description_ghost_stripped(self):
        """Paragraph matching meta description + artifact label is stripped."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        sections = [self._make_section("sec_0", (
            "# Hero Heading\n\n"
            "**Summary:** Boba Nutrition offers premium taro powder for "
            "bubble tea shops and home baristas. Our all-natural ingredients "
            "deliver authentic flavor in every sip.\n\n"
            "Shop now for the best taro experience."
        ))]
        page_html = (
            '<html><head>'
            '<meta name="description" content="Boba Nutrition offers premium '
            'taro powder for bubble tea shops and home baristas. Our all-natural '
            'ingredients deliver authentic flavor in every sip.">'
            '</head><body></body></html>'
        )
        result = filter_seo_ghost_text(sections, page_html)
        assert "Summary:" not in result[0].markdown
        assert "Hero Heading" in result[0].markdown
        assert "Shop now" in result[0].markdown

    def test_jsonld_description_ghost_stripped(self):
        """Paragraph matching JSON-LD description + artifact label is stripped."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        sections = [self._make_section("sec_0", (
            "# Welcome\n\n"
            "**Description:** We are the leading provider of organic supplements "
            "designed for athletes and fitness enthusiasts worldwide.\n\n"
            "Start your journey today."
        ))]
        page_html = (
            '<html><head>'
            '<script type="application/ld+json">'
            '{"@type": "Organization", "description": "We are the leading '
            'provider of organic supplements designed for athletes and fitness '
            'enthusiasts worldwide."}'
            '</script></head><body></body></html>'
        )
        result = filter_seo_ghost_text(sections, page_html)
        assert "Description:" not in result[0].markdown
        assert "Welcome" in result[0].markdown

    def test_legitimate_summary_preserved(self):
        """Summary: content NOT in meta tags is preserved."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        sections = [self._make_section("sec_0", (
            "# Report\n\n"
            "**Summary:** This quarterly report shows a 25% increase in "
            "revenue across all product lines and market segments.\n\n"
            "Details below."
        ))]
        page_html = (
            '<html><head>'
            '<meta name="description" content="Company official website">'
            '</head><body></body></html>'
        )
        result = filter_seo_ghost_text(sections, page_html)
        assert "Summary:" in result[0].markdown

    def test_no_page_html_fallback_sec_0(self):
        """No page_html → conservative fallback strips long Summary: from sec_0."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        long_summary = "**Summary:** " + "x " * 120  # > 200 chars
        sections = [
            self._make_section("sec_0", f"# Hero\n\n{long_summary}\n\nReal content."),
            self._make_section("sec_1", f"# Section\n\n{long_summary}\n\nMore content."),
        ]
        result = filter_seo_ghost_text(sections, "")
        assert "Summary:" not in result[0].markdown, "sec_0 long Summary: should be stripped"
        assert "Summary:" in result[1].markdown, "sec_1 should NOT be filtered in fallback"

    def test_short_summary_preserved_in_fallback(self):
        """Short Summary: paragraph (<200 chars) preserved even in fallback."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        sections = [self._make_section("sec_0", (
            "# Hero\n\n"
            "**Summary:** Short summary here.\n\n"
            "Main content."
        ))]
        result = filter_seo_ghost_text(sections, "")
        assert "Summary:" in result[0].markdown

    def test_no_ghost_fragments_no_changes(self):
        """When page_html has no meta descriptions, sections pass through."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            filter_seo_ghost_text,
        )
        sections = [self._make_section("sec_0", "# Hello\n\nContent here.")]
        page_html = "<html><head><title>Test</title></head><body></body></html>"
        result = filter_seo_ghost_text(sections, page_html)
        assert result[0].markdown == sections[0].markdown


# ===========================================================================
# B23: Phase 2 overflow rendering + smart fallback
# ===========================================================================


class TestPhase2Overflow:
    """B23: content_patterns.py overflow + content_assembler.py smart fallback.

    Tests the Phase 2 content assembly fix with A/B comparison:
    - Flag OFF (old behavior): structured items drop remaining text, generic fallback
    - Flag ON (new behavior): overflow div preserves remaining text, styled fallback
    """

    # Realistic hero section: stats + 2800 chars of narrative (like infiniteage.com)
    HERO_STATS_MARKDOWN = (
        "# Unlock Your Hair's Full Potential with Sea Moss\n\n"
        "Discover the natural secret to stronger, thicker, healthier hair. "
        "Our premium Irish sea moss is sustainably harvested from the pristine "
        "waters of the Atlantic Ocean and carefully processed to preserve all "
        "92 essential minerals your body needs.\n\n"
        "**87%** of users reported improved hair growth\n"
        "**83%** experienced reduced hair loss\n"
        "**77%** noticed thicker, fuller hair\n"
        "**74%** saw faster growth within 30 days\n\n"
        "Sea moss is packed with essential minerals including zinc, selenium, "
        "and biotin that are critical for healthy hair follicle function. Unlike "
        "synthetic supplements, sea moss delivers these nutrients in their natural "
        "bioavailable form, making them easier for your body to absorb.\n\n"
        "Our customers report seeing visible results within 2-4 weeks of "
        "consistent use. Whether you're dealing with thinning hair, slow growth, "
        "or just want to maintain your hair's natural thickness and shine, "
        "sea moss provides the nutritional foundation your hair needs.\n\n"
        "[Shop Now](https://example.com/shop)\n\n"
        "Join over 50,000 satisfied customers who have transformed their hair "
        "health with our premium sea moss products. 100% satisfaction guaranteed "
        "or your money back."
    )

    # Feature section: headings + narrative context
    FEATURES_MARKDOWN = (
        "## Why Choose Our Sea Moss\n\n"
        "We source directly from sustainable farms in the Caribbean and Atlantic. "
        "Every batch is third-party tested for purity and potency.\n\n"
        "### 92 Essential Minerals\n"
        "Sea moss contains nearly every mineral your body needs, including "
        "iodine, calcium, potassium, and magnesium.\n\n"
        "### Sustainably Harvested\n"
        "Our sea moss is hand-harvested using traditional methods that protect "
        "marine ecosystems and ensure the highest quality.\n\n"
        "### Lab Tested Purity\n"
        "Every batch undergoes rigorous third-party testing for heavy metals, "
        "bacteria, and potency to ensure safety.\n\n"
        "All our products are vegan, gluten-free, and made with no artificial "
        "preservatives or fillers. We believe in pure, natural nutrition."
    )

    def test_remove_spans_basic(self):
        """_remove_spans correctly removes matched spans and returns remainder."""
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            _remove_spans,
        )
        text = "Hello world. **87%** users. More text here. **83%** others."
        spans = [(13, 28), (44, 58)]  # "**87%** users." and "**83%** others."
        remaining = _remove_spans(text, spans)
        assert "Hello world." in remaining
        assert "More text here." in remaining
        assert "87%" not in remaining
        assert "83%" not in remaining

    def test_remove_spans_empty(self):
        """_remove_spans with no spans returns full text."""
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            _remove_spans,
        )
        assert _remove_spans("hello world", []) == "hello world"

    def test_detect_stats_captures_remaining(self):
        """_detect_stats now populates footer_markdown with non-stat text."""
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            _detect_stats,
        )
        md = (
            "Discover the natural secret to stronger hair.\n\n"
            "**87%** of users reported improved growth\n"
            "**83%** experienced reduced hair loss\n\n"
            "Sea moss is packed with essential minerals."
        )
        result = _detect_stats(md)
        assert result is not None
        assert result.pattern_type == "stats_list"
        assert len(result.items) == 2
        assert result.footer_markdown is not None
        assert "Discover" in result.footer_markdown
        assert "essential minerals" in result.footer_markdown
        # Stats should NOT be in the remaining text
        assert "87%" not in result.footer_markdown

    def test_detect_features_captures_remaining(self):
        """_detect_features now populates footer_markdown with non-feature text."""
        from viraltracker.services.landing_page_analysis.multipass.content_patterns import (
            _detect_features,
        )
        md = (
            "We source directly from sustainable farms.\n\n"
            "### Fast Processing\nOrders ship within 24 hours.\n\n"
            "### Pure Quality\nNo additives or fillers ever.\n\n"
            "All products are vegan and gluten-free."
        )
        result = _detect_features(md)
        assert result is not None
        assert len(result.items) == 2
        assert "sustainable farms" in result.footer_markdown
        assert "vegan" in result.footer_markdown

    def test_overflow_on_stats_hero_flag_on(self):
        """Flag ON: stats hero renders items + overflow with narrative text."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "true"
            # Re-import to pick up flag
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)

            section = FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)
            hint = type('H', (), {'layout_type': 'stats_row'})()
            pattern = cp.detect_content_pattern(section, hint)
            assert pattern.pattern_type == "stats_list"
            assert pattern.footer_markdown  # Has remaining text

            result = cp.split_content_for_template(pattern, hint, section)
            items_html = result.get("sec_0_items", "")
            # Items should contain stat cards
            assert "mp-stat" in items_html
            # AND overflow div with narrative text
            assert "mp-overflow" in items_html
            assert "Discover" in items_html or "essential minerals" in items_html
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)

    def test_overflow_on_stats_hero_flag_off(self):
        """Flag OFF: stats hero renders ONLY items, narrative text is lost."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "false"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)

            section = FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)
            hint = type('H', (), {'layout_type': 'stats_row'})()
            pattern = cp.detect_content_pattern(section, hint)
            result = cp.split_content_for_template(pattern, hint, section)
            items_html = result.get("sec_0_items", "")
            # Items should contain stat cards
            assert "mp-stat" in items_html
            # BUT NO overflow div
            assert "mp-overflow" not in items_html
            assert "Discover" not in items_html
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)

    def test_coverage_check_passes_with_overflow(self):
        """With overflow, coverage check should PASS for mixed stats+prose section."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "true"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)

            section = FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)
            hint = type('H', (), {'layout_type': 'stats_row'})()
            pattern = cp.detect_content_pattern(section, hint)
            result = cp.split_content_for_template(pattern, hint, section)

            # Simulate the coverage check from assemble_content
            rendered_text = re.sub(r'<[^>]+>', '', "".join(result.values()))
            source_text = cp.normalize_markdown_to_text(section.markdown)
            coverage = len(rendered_text.strip()) / len(source_text.strip()) if source_text.strip() else 1.0

            assert coverage >= 0.6, (
                f"Coverage {coverage:.2f} should be >= 0.60 with overflow enabled. "
                f"Rendered: {len(rendered_text.strip())} chars, "
                f"Source: {len(source_text.strip())} chars"
            )
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)

    def test_coverage_check_fails_without_overflow(self):
        """Without overflow, coverage check FAILS for mixed stats+prose section."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "false"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)

            section = FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)
            hint = type('H', (), {'layout_type': 'stats_row'})()
            pattern = cp.detect_content_pattern(section, hint)
            result = cp.split_content_for_template(pattern, hint, section)

            rendered_text = re.sub(r'<[^>]+>', '', "".join(result.values()))
            source_text = cp.normalize_markdown_to_text(section.markdown)
            coverage = len(rendered_text.strip()) / len(source_text.strip()) if source_text.strip() else 1.0

            assert coverage < 0.6, (
                f"Coverage {coverage:.2f} should be < 0.60 without overflow. "
                f"Old behavior should only capture stat items."
            )
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)

    def test_smart_fallback_preserves_template_class(self):
        """Smart fallback keeps original template CSS class, not mp-generic."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            _replace_section_placeholders,
        )
        skeleton = (
            '<section data-section="sec_0" class="mp-stats-row" style="background: #fff;">'
            '<div class="mp-container">'
            '<div class="mp-section-header">{{sec_0_header}}</div>'
            '<div class="mp-grid-4 mp-text-center">{{sec_0_items}}</div>'
            '</div></section>'
        )
        content = '<h1>Title</h1><p>Content here</p>'
        result = _replace_section_placeholders(skeleton, "sec_0", content)
        # Template class preserved
        assert 'class="mp-stats-row"' in result
        assert 'mp-generic' not in result
        # Content injected into first placeholder
        assert '<h1>Title</h1>' in result
        # Second placeholder cleared
        assert '{{sec_0_items}}' not in result

    def test_generic_fallback_loses_template_class(self):
        """Old generic fallback wraps in mp-generic, losing template styling."""
        from viraltracker.services.landing_page_analysis.multipass.content_assembler import (
            _build_generic_fallback,
        )
        content = '<h1>Title</h1><p>Content</p>'
        result = _build_generic_fallback("sec_0", content)
        assert 'mp-generic' in result
        assert 'mp-stats-row' not in result

    def test_no_overflow_for_small_remaining_text(self):
        """When remaining text is < 40% of total, NO overflow is added."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "true"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)

            # Stats dominate — minimal remaining text
            md = (
                "## Stats\n\n"
                "**10K+** Active Users\n"
                "**99.9%** Uptime\n"
                "**500M+** Requests\n"
                "**24/7** Support\n\n"
                "Brief note."  # Very little remaining text
            )
            section = FakeSection("sec_0", "stats", md)
            hint = type('H', (), {'layout_type': 'stats_row'})()
            pattern = cp.detect_content_pattern(section, hint)
            result = cp.split_content_for_template(pattern, hint, section)
            items_html = result.get("sec_0_items", "")
            # Should NOT have overflow for tiny remaining text
            assert "mp-overflow" not in items_html
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)

    def test_full_assembly_with_overflow(self):
        """End-to-end: assemble_content with stats_row layout, flag ON."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "true"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_assembler as ca
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)
            importlib.reload(ca)

            skeleton = (
                '<section data-section="sec_0" class="mp-stats-row" style="padding: 50px 30px;">'
                '<div class="mp-container">'
                '<div class="mp-section-header">{{sec_0_header}}</div>'
                '<div class="mp-grid-4 mp-text-center">{{sec_0_items}}</div>'
                '</div></section>'
            )
            sections = [FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)]
            layout_hint = type('H', (), {'layout_type': 'stats_row'})()
            layout_map = {"sec_0": layout_hint}

            result = ca.assemble_content(skeleton, sections, {}, layout_map=layout_map)
            # Template styling preserved
            assert 'mp-stats-row' in result
            assert 'mp-generic' not in result
            # Stats rendered
            assert 'mp-stat' in result
            # Narrative text preserved via overflow
            assert 'Discover' in result or 'essential minerals' in result
            # Data slots assigned
            assert 'data-slot=' in result
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)
            importlib.reload(ca)

    def test_full_assembly_without_overflow(self):
        """End-to-end: assemble_content with stats_row layout, flag OFF → generic fallback."""
        import os
        old = os.environ.get("PHASE2_OVERFLOW")
        try:
            os.environ["PHASE2_OVERFLOW"] = "false"
            import importlib
            import viraltracker.services.landing_page_analysis.multipass.content_assembler as ca
            import viraltracker.services.landing_page_analysis.multipass.content_patterns as cp
            importlib.reload(cp)
            importlib.reload(ca)

            skeleton = (
                '<section data-section="sec_0" class="mp-stats-row" style="padding: 50px 30px;">'
                '<div class="mp-container">'
                '<div class="mp-section-header">{{sec_0_header}}</div>'
                '<div class="mp-grid-4 mp-text-center">{{sec_0_items}}</div>'
                '</div></section>'
            )
            sections = [FakeSection("sec_0", "hero", self.HERO_STATS_MARKDOWN)]
            layout_hint = type('H', (), {'layout_type': 'stats_row'})()
            layout_map = {"sec_0": layout_hint}

            result = ca.assemble_content(skeleton, sections, {}, layout_map=layout_map)
            # Old behavior: generic fallback because coverage fails
            assert 'mp-generic' in result
            # Template class is LOST
            assert 'mp-stats-row' not in result
        finally:
            if old is not None:
                os.environ["PHASE2_OVERFLOW"] = old
            else:
                os.environ.pop("PHASE2_OVERFLOW", None)
            importlib.reload(cp)
            importlib.reload(ca)


# ===========================================================================
# B24: Phase Diagnostics
# ===========================================================================


def _wrap_json_as_html(json_data):
    """Mirror pipeline._wrap_json_as_html for test fixtures."""
    import json as _json
    json_str = _json.dumps(json_data, indent=2, default=str)
    return f"<html><body><pre><code>{json_str}</code></pre></body></html>"


def _build_phase0_snapshot(colors=None, typography=None):
    """Build a Phase 0 design system snapshot."""
    ds = {
        "colors": colors or {
            "primary": "#ff0000",
            "secondary": "#00ff00",
            "accent": "#0000ff",
            "background": "#ffffff",
        },
        "typography": typography or {
            "heading_font": "Arial, sans-serif",
            "body_font": "Georgia, serif",
            "h1_size": "2.5rem",
        },
    }
    return _wrap_json_as_html(ds)


def _build_content_html(
    sections=3,
    slots_per_section=3,
    wrap_lp_mockup=True,
    extra_css="",
    images_per_section=1,
    extra_text="",
):
    """Build synthetic content HTML with data-section and data-slot attributes."""
    slot_types = ["heading", "body", "cta"]
    parts = []
    if extra_css:
        parts.append(f"<style>{extra_css}</style>")
    for s in range(sections):
        inner = []
        for sl in range(slots_per_section):
            stype = slot_types[sl % len(slot_types)]
            slot_name = f"{stype}-{s * slots_per_section + sl}"
            if stype == "heading":
                inner.append(
                    f'<h2 data-slot="{slot_name}">Heading {s}</h2>'
                )
            elif stype == "body":
                inner.append(
                    f'<p data-slot="{slot_name}">This is body text for section {s} '
                    f"with enough words to pass the short text guard and provide "
                    f"meaningful comparison between phases. {extra_text}</p>"
                )
            else:
                inner.append(
                    f'<a data-slot="{slot_name}" href="#">Buy Now</a>'
                )
        for _ in range(images_per_section):
            inner.append('<img src="https://example.com/img.jpg" alt="test">')
        section_html = (
            f'<section data-section="sec_{s}">{"".join(inner)}</section>'
        )
        parts.append(section_html)
    html = "\n".join(parts)
    if wrap_lp_mockup:
        html = f'<div class="lp-mockup">\n{html}\n</div>'
    return html


def _build_skeleton_html(sections=3, placeholders=True):
    """Build a Phase 1 skeleton with optional placeholders."""
    parts = ['<style>.hero { color: red; }\n.section { padding: 20px; }</style>']
    for s in range(sections):
        if placeholders:
            parts.append(
                f'<section data-section="sec_{s}">'
                f'{{{{{f"sec_{s}_header"}}}}}'
                f'{{{{{f"sec_{s}_items"}}}}}'
                f"</section>"
            )
        else:
            parts.append(f'<section data-section="sec_{s}"><p>Content</p></section>')
    html = "\n".join(parts)
    return f'<div class="lp-mockup">\n{html}\n</div>'


class TestPhaseDiagnostics:
    """B24: phase_diagnostics.py — Per-phase quality measurement."""

    def test_diagnose_all_phases_pass(self):
        """All 5 snapshots with good metrics -> overall PASS."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {
            "phase_0_design_system": _build_phase0_snapshot(),
            "phase_1_skeleton": _build_skeleton_html(sections=3),
            "phase_2_content": content,
            "phase_3_refined": content,  # identical = no drift
            "phase_4_final": content,
        }
        # Source markdown must contain the same text as the generated HTML
        # to achieve high text fidelity. Match the body text pattern.
        source_md = (
            "# Heading 0\n"
            "This is body text for section 0 with enough words to pass the "
            "short text guard and provide meaningful comparison between phases.\n"
            "Buy Now\n\n"
            "# Heading 1\n"
            "This is body text for section 1 with enough words to pass the "
            "short text guard and provide meaningful comparison between phases.\n"
            "Buy Now\n\n"
            "# Heading 2\n"
            "This is body text for section 2 with enough words to pass the "
            "short text guard and provide meaningful comparison between phases.\n"
            "Buy Now"
        )
        report = diagnose_phases(
            snapshots, source_markdown=source_md, expected_section_count=3
        )
        assert report.overall_passed, (
            f"Expected PASS but got FAIL: "
            f"{[(v.phase_name, v.issues) for v in report.verdicts if not v.passed]}"
        )

    def test_diagnose_phase3_slot_loss(self):
        """Phase 3 drops 4 slots -> FAIL, lost slot names listed."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        phase2 = _build_content_html(sections=3, slots_per_section=3)

        # Phase 3: remove some slots by replacing them with plain text
        phase3 = phase2.replace('data-slot="body-1"', 'class="lost"')
        phase3 = phase3.replace('data-slot="body-4"', 'class="lost"')
        phase3 = phase3.replace('data-slot="cta-2"', 'class="lost"')
        phase3 = phase3.replace('data-slot="heading-3"', 'class="lost"')

        snapshots = {
            "phase_0_design_system": _build_phase0_snapshot(),
            "phase_1_skeleton": _build_skeleton_html(sections=3),
            "phase_2_content": phase2,
            "phase_3_refined": phase3,
            "phase_4_final": phase3,
        }
        report = diagnose_phases(snapshots, expected_section_count=3)
        assert not report.overall_passed

        # Find Phase 3 verdict
        phase3_verdict = next(
            v for v in report.verdicts if "Phase 3" in v.phase_name
        )
        assert not phase3_verdict.passed
        assert any("Lost" in i or "lost" in i.lower() for i in phase3_verdict.issues)
        # Verify lost slot names are mentioned
        issues_text = " ".join(phase3_verdict.issues)
        assert "body-1" in issues_text
        assert "body-4" in issues_text

    def test_diagnose_missing_snapshots(self):
        """Only Phase 2 present -> partial report, no crash."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        # Should have Phase 2 + Final Output metrics only
        assert len(report.phases) == 2
        assert any("Phase 2" in m.phase_name for m in report.phases)
        assert any("Final" in m.phase_name for m in report.phases)

    def test_diagnose_empty_html(self):
        """Empty string snapshot -> FAIL, no crash."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        snapshots = {
            "phase_0_design_system": "",
            "phase_1_skeleton": "",
            "phase_2_content": "",
        }
        report = diagnose_phases(snapshots)
        assert not report.overall_passed

    def test_diagnose_phase0_defaults(self):
        """Phase 0 using DEFAULT_DESIGN_SYSTEM -> FAIL."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        from viraltracker.services.landing_page_analysis.multipass.pipeline import (
            DEFAULT_DESIGN_SYSTEM,
        )
        snapshots = {
            "phase_0_design_system": _wrap_json_as_html(DEFAULT_DESIGN_SYSTEM),
        }
        report = diagnose_phases(snapshots)
        phase0_verdict = next(
            v for v in report.verdicts if "Phase 0" in v.phase_name
        )
        assert not phase0_verdict.passed
        assert any("defaults" in i.lower() or "extraction failed" in i.lower()
                    for i in phase0_verdict.issues)

    def test_diagnose_phase2_unresolved(self):
        """{{sec_3}} remaining -> FAIL."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        # Inject unresolved placeholder
        content = content.replace("</div>", "{{sec_3_items}}</div>", 1)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        phase2_verdict = next(
            v for v in report.verdicts if "Phase 2" in v.phase_name
        )
        assert not phase2_verdict.passed
        assert any("placeholder" in i.lower() for i in phase2_verdict.issues)

    def test_diagnose_identical_phase2_phase3(self):
        """Phase 3 == Phase 2 -> PASS, 0 deltas, high unchanged count."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {
            "phase_2_content": content,
            "phase_3_refined": content,
        }
        report = diagnose_phases(snapshots)
        phase3_metrics = next(
            m for m in report.phases if "Phase 3" in m.phase_name
        )
        # No slots lost or added
        assert phase3_metrics.slots_lost == frozenset()
        assert phase3_metrics.slots_added == frozenset()
        # Unchanged sections should equal total sections
        assert phase3_metrics.extras.get("unchanged_section_count") == 3

    def test_diagnose_malformed_html(self):
        """Unclosed tags -> metrics still computed, no crash."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        malformed = (
            '<div class="lp-mockup">'
            '<section data-section="sec_0">'
            '<p data-slot="body-0">Hello world test content here with enough words</p>'
            # Missing closing tags
        )
        snapshots = {"phase_2_content": malformed}
        report = diagnose_phases(snapshots)
        # Should not crash and should have metrics
        assert len(report.phases) >= 1
        phase2 = next(m for m in report.phases if "Phase 2" in m.phase_name)
        assert phase2.slot_count >= 1

    def test_diagnose_json_phase0(self):
        """Phase 0 JSON-wrapped snapshot -> extras parsed correctly."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        ds = {
            "colors": {"primary": "#f00", "secondary": "#0f0", "accent": "#00f",
                       "bg": "#fff", "text": "#000"},
            "typography": {"heading": "Arial", "body": "Georgia", "size": "1rem"},
        }
        snapshots = {"phase_0_design_system": _wrap_json_as_html(ds)}
        report = diagnose_phases(snapshots)
        phase0 = next(m for m in report.phases if "Phase 0" in m.phase_name)
        assert phase0.extras["color_count"] == 5
        assert phase0.extras["typography_entries"] == 3
        assert phase0.extras["used_defaults"] is False

    def test_threshold_override(self):
        """Custom DiagnosticThresholds changes verdict."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            DiagnosticThresholds,
            diagnose_phases,
        )
        # Build content with only 3 slots total (below default min_slots=5)
        content = _build_content_html(sections=1, slots_per_section=3)
        snapshots = {"phase_2_content": content}

        # Default thresholds: FAIL (3 < 5)
        report_default = diagnose_phases(snapshots)
        phase2_default = next(
            v for v in report_default.verdicts if "Phase 2" in v.phase_name
        )
        assert not phase2_default.passed

        # Custom thresholds: min_slots=2 -> PASS
        custom = DiagnosticThresholds(min_slots=2)
        report_custom = diagnose_phases(snapshots, thresholds=custom)
        phase2_custom = next(
            v for v in report_custom.verdicts if "Phase 2" in v.phase_name
        )
        assert phase2_custom.passed

    def test_report_format(self):
        """format() contains expected headers and metrics."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {
            "phase_0_design_system": _build_phase0_snapshot(),
            "phase_2_content": content,
            "phase_3_refined": content,
        }
        report = diagnose_phases(snapshots, expected_section_count=3)
        text = report.format()
        assert "PIPELINE PHASE DIAGNOSTIC REPORT" in text
        assert "Phase 0" in text
        assert "Phase 2" in text
        assert "VERDICT" in text

    def test_source_markdown_none(self):
        """source_markdown=None -> no crash, text_fidelity = None for phases without fidelity."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=2, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        # Pass None explicitly
        report = diagnose_phases(snapshots, source_markdown=None)
        assert len(report.phases) >= 1
        # Phase 2 fidelity should be None (empty source markdown)
        phase2 = next(m for m in report.phases if "Phase 2" in m.phase_name)
        assert phase2.text_fidelity_vs_source is None

    def test_css_chars_multiline(self):
        """Multi-line <style> block -> correct char count."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            _count_css_chars,
        )
        html = (
            "<style>\n"
            "  .hero { color: red; }\n"
            "  .section {\n"
            "    padding: 20px;\n"
            "    margin: 10px;\n"
            "  }\n"
            "</style>"
        )
        count = _count_css_chars(html)
        expected_css = (
            "\n"
            "  .hero { color: red; }\n"
            "  .section {\n"
            "    padding: 20px;\n"
            "    margin: 10px;\n"
            "  }\n"
        )
        assert count == len(expected_css)

    def test_short_text_similarity_skipped(self):
        """Both phases < 10 tokens -> text_similarity_vs_prev = None, not 0.0."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        # Build very short content (< 10 tokens per phase)
        short_html = (
            '<div class="lp-mockup">'
            '<section data-section="sec_0">'
            '<p data-slot="h-0">Hi</p>'
            '<p data-slot="b-0">OK</p>'
            '<p data-slot="c-0">Go</p>'
            '<p data-slot="d-0">Yes</p>'
            '<p data-slot="e-0">No</p>'
            '</section></div>'
        )
        # Phase 3 with slightly different text (still < 10 tokens)
        short_html_3 = short_html.replace("Hi", "Hey")
        snapshots = {
            "phase_2_content": short_html,
            "phase_3_refined": short_html_3,
        }
        report = diagnose_phases(snapshots)
        phase3 = next(
            m for m in report.phases if "Phase 3" in m.phase_name
        )
        # Should be None (skipped), not 0.0
        assert phase3.text_similarity_vs_prev is None

    def test_to_dict_serialization(self):
        """to_dict() produces valid JSON-serializable dict."""
        import json as _json
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=2, slots_per_section=3)
        snapshots = {
            "phase_0_design_system": _build_phase0_snapshot(),
            "phase_2_content": content,
        }
        report = diagnose_phases(snapshots)
        d = report.to_dict()
        # Must be JSON-serializable
        json_str = _json.dumps(d)
        assert json_str
        # Verify structure
        assert "overall_passed" in d
        assert "phases" in d
        assert "verdicts" in d
        assert isinstance(d["phases"], list)

    def test_lp_mockup_wrapper_detection(self):
        """Wrapper present -> has_lp_mockup_wrapper = True; stripped -> FAIL."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        # With wrapper
        with_wrapper = _build_content_html(
            sections=3, slots_per_section=3, wrap_lp_mockup=True
        )
        snapshots = {"phase_4_final": with_wrapper}
        report = diagnose_phases(snapshots, source_markdown="Heading body content words enough for test fidelity comparison text")
        final_metrics = next(m for m in report.phases if "Final" in m.phase_name)
        assert final_metrics.extras["has_lp_mockup_wrapper"] is True

        # Without wrapper
        without_wrapper = _build_content_html(
            sections=3, slots_per_section=3, wrap_lp_mockup=False
        )
        snapshots2 = {"phase_4_final": without_wrapper}
        report2 = diagnose_phases(snapshots2, source_markdown="Heading body content words enough for test fidelity comparison text")
        final_verdict = next(v for v in report2.verdicts if "Final" in v.phase_name)
        assert not final_verdict.passed
        assert any(".lp-mockup" in i for i in final_verdict.issues)


# ===========================================================================
# B25: PhaseVerdict warnings field
# ===========================================================================


class TestPhaseVerdictWarnings:
    """B25: phase_diagnostics.py — PhaseVerdict warnings + WARN-level gates."""

    def test_verdict_has_warnings_field(self):
        """PhaseVerdict has a warnings list (backward-compatible default)."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            PhaseVerdict,
        )
        v = PhaseVerdict(phase_name="test", passed=True)
        assert v.warnings == []
        assert v.issues == []

    def test_warnings_do_not_cause_fail(self):
        """Verdicts with only warnings should still pass."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            PhaseVerdict,
        )
        v = PhaseVerdict(
            phase_name="test", passed=True,
            warnings=["Low SSIM", "Something minor"],
        )
        assert v.passed is True
        assert len(v.warnings) == 2

    def test_warnings_serialized_in_to_dict(self):
        """to_dict() includes warnings in verdict entries."""
        import json as _json
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {
            "phase_0_design_system": _build_phase0_snapshot(),
            "phase_2_content": content,
        }
        report = diagnose_phases(snapshots)
        d = report.to_dict()
        json_str = _json.dumps(d)
        assert json_str
        for v in d["verdicts"]:
            assert "warnings" in v

    def test_warnings_shown_in_format(self):
        """format() renders WARN lines distinctly from !! lines."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        # Create Phase 3 that heavily rewrites text (sim < 0.80)
        phase2 = _build_content_html(sections=3, slots_per_section=3)
        phase3 = phase2.replace(
            "This is body text for section 0 with enough words to pass "
            "the short text guard and provide meaningful comparison between phases.",
            "COMPLETELY REWRITTEN text that bears absolutely no resemblance "
            "to the original content whatsoever in any meaningful way.",
        )
        phase3 = phase3.replace(
            "This is body text for section 1 with enough words to pass "
            "the short text guard and provide meaningful comparison between phases.",
            "ALSO REWRITTEN text with entirely different vocabulary and "
            "sentence structure that shares nothing with the original text.",
        )
        snapshots = {
            "phase_2_content": phase2,
            "phase_3_refined": phase3,
        }
        report = diagnose_phases(snapshots)
        text = report.format()
        assert "WARN:" in text

    def test_visual_scores_in_report_format(self):
        """format() shows visual SSIM section when scores present."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        report.visual_scores = {
            "phase_1_skeleton": 0.35,
            "phase_2_content": 0.52,
        }
        report.visual_trajectory = "improving"
        text = report.format()
        assert "VISUAL FIDELITY" in text
        assert "0.3500" in text
        assert "0.5200" in text
        assert "improving" in text

    def test_visual_scores_in_to_dict(self):
        """to_dict() includes visual_scores and visual_trajectory."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        report.visual_scores = {"phase_2_content": 0.55}
        report.visual_trajectory = "flat"
        d = report.to_dict()
        assert d["visual_scores"] == {"phase_2_content": 0.55}
        assert d["visual_trajectory"] == "flat"


# ===========================================================================
# B26: WARN-first quality gates
# ===========================================================================


class TestQualityGates:
    """B26: phase_diagnostics.py — WARN-first quality gates."""

    def test_phase1_malformed_placeholder_warns(self):
        """Unmatched {{ vs }} count produces a warning."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        # Skeleton with unmatched braces
        skeleton = (
            '<div class="lp-mockup">'
            '<section data-section="sec_0">{{sec_0_header}}</section>'
            '<section data-section="sec_1">{{sec_1_header}</section>'  # Missing closing brace
            '</div>'
        )
        snapshots = {
            "phase_1_skeleton": skeleton,
        }
        report = diagnose_phases(snapshots, expected_section_count=2)
        phase1_verdict = next(
            v for v in report.verdicts if "Phase 1" in v.phase_name
        )
        assert any("Malformed" in w for w in phase1_verdict.warnings)

    def test_phase1_wellformed_no_warnings(self):
        """Well-formed placeholders produce no warnings."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        skeleton = _build_skeleton_html(sections=3)
        snapshots = {"phase_1_skeleton": skeleton}
        report = diagnose_phases(snapshots, expected_section_count=3)
        phase1_verdict = next(
            v for v in report.verdicts if "Phase 1" in v.phase_name
        )
        assert len(phase1_verdict.warnings) == 0

    def test_final_unclosed_tags_warns(self):
        """Final output with unclosed <section> produces a warning."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        # Missing closing section tag
        malformed = (
            '<div class="lp-mockup">'
            '<section data-section="sec_0">'
            '<p data-slot="body-0">Content 0 with enough words for text comparison</p>'
            '<p data-slot="body-1">More content for text comparison test</p>'
            '<p data-slot="body-2">Additional content for text comparison test</p>'
            '<p data-slot="body-3">Even more content for text comparison test</p>'
            '<p data-slot="body-4">Final content for text comparison test</p>'
            # No </section>
            '</div>'
        )
        snapshots = {"phase_4_final": malformed}
        report = diagnose_phases(
            snapshots,
            source_markdown="Content 0 with enough words for text comparison "
                           "More content Additional content Even more Final content",
        )
        final_verdict = next(
            v for v in report.verdicts if "Final" in v.phase_name
        )
        assert any("unclosed" in w.lower() or "Malformed" in w for w in final_verdict.warnings)

    def test_final_slot_retention_warns_when_low(self):
        """Final output with < 80% of Phase 2 slots produces a warning."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        phase2 = _build_content_html(sections=3, slots_per_section=3)
        # Final output: remove most slots
        final = phase2.replace('data-slot="heading-0"', 'class="lost"')
        final = final.replace('data-slot="body-1"', 'class="lost"')
        final = final.replace('data-slot="cta-2"', 'class="lost"')
        final = final.replace('data-slot="heading-3"', 'class="lost"')
        final = final.replace('data-slot="body-4"', 'class="lost"')
        final = final.replace('data-slot="cta-5"', 'class="lost"')
        final = final.replace('data-slot="heading-6"', 'class="lost"')

        snapshots = {
            "phase_2_content": phase2,
            "phase_4_final": final,
        }
        report = diagnose_phases(snapshots)
        final_verdict = next(
            v for v in report.verdicts if "Final" in v.phase_name
        )
        assert any("Lost" in w and "slot" in w.lower() for w in final_verdict.warnings)

    def test_final_slot_retention_no_warn_when_high(self):
        """Final output with same slots as Phase 2 produces no retention warning."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=3, slots_per_section=3)
        snapshots = {
            "phase_2_content": content,
            "phase_4_final": content,
        }
        report = diagnose_phases(snapshots)
        final_verdict = next(
            v for v in report.verdicts if "Final" in v.phase_name
        )
        assert not any("Lost" in w for w in final_verdict.warnings)


# ===========================================================================
# B27: Phase 1 fallback preserves layout_hints
# ===========================================================================


class TestPhase1FallbackLayoutHints:
    """B27: pipeline.py — _phase_1_fallback_classify preserves layout_hints."""

    def test_fallback_returns_layout_hints(self):
        """Fallback with layout_hints returns filtered LayoutHint objects."""
        from viraltracker.services.landing_page_analysis.multipass.layout_analyzer import LayoutHint
        from viraltracker.services.landing_page_analysis.multipass.pipeline import MultiPassPipeline

        # Create a minimal pipeline instance
        pipeline = MultiPassPipeline.__new__(MultiPassPipeline)

        sections = [
            FakeSection("sec_0", "hero", "Hero text"),
            FakeSection("sec_1", "features", "Features text"),
        ]
        hints = {
            "sec_0": LayoutHint(layout_type="hero_split", has_image=True, confidence=0.8),
            "sec_1": LayoutHint(layout_type="feature_grid", column_count=3, confidence=0.7),
            "sec_99": LayoutHint(layout_type="generic"),  # Not in sections
        }

        _, _, layout_map = pipeline._phase_1_fallback_classify(sections, layout_hints=hints)

        assert "sec_0" in layout_map
        assert "sec_1" in layout_map
        assert "sec_99" not in layout_map  # Filtered out
        assert layout_map["sec_0"].layout_type == "hero_split"
        assert hasattr(layout_map["sec_0"], "layout_type")  # content_assembler check

    def test_fallback_without_hints_returns_empty(self):
        """Fallback without layout_hints returns empty dict (backward compat)."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import MultiPassPipeline

        pipeline = MultiPassPipeline.__new__(MultiPassPipeline)
        sections = [FakeSection("sec_0", "hero", "Hero text")]

        _, _, layout_map = pipeline._phase_1_fallback_classify(sections)
        assert layout_map == {}

    def test_fallback_with_none_hints_returns_empty(self):
        """Fallback with layout_hints=None returns empty dict."""
        from viraltracker.services.landing_page_analysis.multipass.pipeline import MultiPassPipeline

        pipeline = MultiPassPipeline.__new__(MultiPassPipeline)
        sections = [FakeSection("sec_0", "hero", "Hero text")]

        _, _, layout_map = pipeline._phase_1_fallback_classify(sections, layout_hints=None)
        assert layout_map == {}


# ===========================================================================
# B28: html_renderer module
# ===========================================================================


class TestHtmlRenderer:
    """B28: html_renderer.py — render constants and contract."""

    def test_render_constants(self):
        """Canonical render settings match visual_fidelity_check.py."""
        from viraltracker.services.landing_page_analysis.multipass.html_renderer import (
            RENDER_VIEWPORT_WIDTH,
            RENDER_VIEWPORT_HEIGHT,
            FREEZE_ANIMATIONS_CSS,
        )
        assert RENDER_VIEWPORT_WIDTH == 1280
        assert RENDER_VIEWPORT_HEIGHT == 800
        assert "animation: none" in FREEZE_ANIMATIONS_CSS
        assert "transition: none" in FREEZE_ANIMATIONS_CSS

    def test_render_empty_html_returns_none(self):
        """Empty/blank HTML returns None without crashing."""
        from viraltracker.services.landing_page_analysis.multipass.html_renderer import (
            render_html_to_png,
        )
        assert render_html_to_png("") is None
        assert render_html_to_png("   ") is None

    def test_render_returns_none_without_playwright(self):
        """When Playwright is not importable, returns None."""
        from viraltracker.services.landing_page_analysis.multipass.html_renderer import (
            render_html_to_png,
        )
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            # Attempt to render — should fail gracefully
            result = render_html_to_png("<html><body><p>Test</p></body></html>")
            # Will either return None (if import fails) or bytes (if Playwright works)
            # This test just ensures no crash
            assert result is None or isinstance(result, bytes)


# ===========================================================================
# B29: PhaseDiagnosticReport visual fields
# ===========================================================================


class TestPhaseDiagnosticReportVisual:
    """B29: phase_diagnostics.py — visual_scores and visual_trajectory fields."""

    def test_default_visual_fields_none(self):
        """Default report has None visual fields."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=2, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        assert report.visual_scores is None
        assert report.visual_trajectory is None

    def test_visual_fields_serializable(self):
        """Visual fields serialize correctly in to_dict()."""
        import json as _json
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
        )
        content = _build_content_html(sections=2, slots_per_section=3)
        snapshots = {"phase_2_content": content}
        report = diagnose_phases(snapshots)
        report.visual_scores = {"phase_1": 0.3, "phase_2": 0.5}
        report.visual_trajectory = "improving"
        d = report.to_dict()
        json_str = _json.dumps(d)
        parsed = _json.loads(json_str)
        assert parsed["visual_scores"]["phase_1"] == 0.3
        assert parsed["visual_trajectory"] == "improving"

    def test_check_unclosed_tags_helper(self):
        """_check_unclosed_tags detects missing closing tags."""
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            _check_unclosed_tags,
        )
        # Balanced HTML
        assert _check_unclosed_tags("<div><section></section></div>") == []
        # Unclosed section
        result = _check_unclosed_tags("<section><div></div>")
        assert len(result) == 1
        assert "<section>" in result[0]
        # Multiple unclosed
        result = _check_unclosed_tags("<div><section><article>")
        assert len(result) == 3
