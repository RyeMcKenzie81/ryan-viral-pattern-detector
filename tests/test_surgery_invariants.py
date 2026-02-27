"""Regression tests for cross-section slot bug fix.

Tests the 3-layer defense-in-depth:
  1. Validation: validate_slot_nesting / strip_violating_slots
  2. Prevention: ElementClassifier._strip_cross_section_slots
  3. Defense: _SlotReplacer rollback guard in _template_swap
"""

import pytest

# Load invariants module directly from file to avoid __init__.py import chain
# that triggers unrelated Config errors in the multipass pipeline module.
import importlib.util
import os
_inv_path = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "viraltracker", "services", "landing_page_analysis", "multipass",
    "invariants.py",
)
_spec = importlib.util.spec_from_file_location("_invariants", _inv_path)
_invariants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_invariants)
validate_slot_nesting = _invariants.validate_slot_nesting
strip_violating_slots = _invariants.strip_violating_slots


# --------------------------------------------------------------------------
# Layer 1: validate_slot_nesting
# --------------------------------------------------------------------------


class TestValidateSlotNesting:
    """Tests for the validate_slot_nesting validator."""

    def test_slot_spans_single_section(self):
        """<a data-slot> wrapping a single <section> → ERROR."""
        html = (
            '<a data-slot="cta-1">'
            '<section data-section="s1"><p>Content</p></section>'
            '</a>'
        )
        report = validate_slot_nesting(html)
        assert not report.passed
        errors = [v for v in report.violations if v.severity == "ERROR"]
        assert len(errors) >= 1
        assert errors[0].violation_type == "SLOT_SPANS_SECTIONS"
        assert errors[0].slot_name == "cta-1"

    def test_slot_spans_four_sections(self):
        """<a data-slot> wrapping 4 sections (exact bug scenario) → ERROR."""
        sections = "".join(
            f'<section data-section="sec_{i}"><p>Section {i}</p></section>'
            for i in range(1, 5)
        )
        html = f'<a data-slot="cta-1">{sections}</a>'
        report = validate_slot_nesting(html)
        assert not report.passed
        section_violations = [
            v for v in report.violations
            if v.violation_type == "SLOT_SPANS_SECTIONS"
        ]
        # At least one SLOT_SPANS_SECTIONS error for cta-1
        assert len(section_violations) >= 1
        assert all(v.slot_name == "cta-1" for v in section_violations)

    def test_legitimate_inline_cta(self):
        """Normal inline <a data-slot> with just text → PASS."""
        html = (
            '<div data-section="s1">'
            '<p>Hello</p>'
            '<a data-slot="cta-1" href="/buy">Buy Now</a>'
            '</div>'
        )
        report = validate_slot_nesting(html)
        assert report.passed
        errors = [v for v in report.violations if v.severity == "ERROR"]
        assert len(errors) == 0

    def test_button_wrapping_block(self):
        """<button data-slot> wrapping a <div> — no sections, should pass."""
        html = (
            '<button data-slot="cta-2">'
            '<div class="btn-inner"><span>Click</span></div>'
            '</button>'
        )
        report = validate_slot_nesting(html)
        assert report.passed

    def test_nested_anchors_no_crash(self):
        """Nested <a> tags — parser should not crash."""
        html = (
            '<a data-slot="cta-1" href="/outer">'
            '<a data-slot="cta-2" href="/inner">Inner</a>'
            '</a>'
        )
        report = validate_slot_nesting(html)
        # Should detect NESTED_SLOTS
        nested = [
            v for v in report.violations
            if v.violation_type == "NESTED_SLOTS"
        ]
        assert len(nested) >= 1

    def test_child_slot_inside_parent_slot(self):
        """Nested data-slot elements → NESTED_SLOTS ERROR."""
        html = (
            '<a data-slot="cta-1" href="/buy">'
            '<h3 data-slot="heading-1">Title</h3>'
            '<span>Description</span>'
            '</a>'
        )
        report = validate_slot_nesting(html)
        assert not report.passed
        nested = [
            v for v in report.violations
            if v.violation_type == "NESTED_SLOTS"
        ]
        assert len(nested) >= 1
        assert nested[0].slot_name == "cta-1"

    def test_duplicate_slot_names(self):
        """Same slot name on two elements → WARNING."""
        html = (
            '<a data-slot="cta-1" href="/buy1">Buy</a>'
            '<a data-slot="cta-1" href="/buy2">Also Buy</a>'
        )
        report = validate_slot_nesting(html)
        # Duplicates are warnings, not errors, so passed should be True
        assert report.passed
        duplicates = [
            v for v in report.violations
            if v.violation_type == "DUPLICATE_SLOT"
        ]
        assert len(duplicates) >= 1

    def test_clean_html_no_violations(self):
        """Normal page with proper slots → PASS, no violations."""
        html = (
            '<div data-section="s1">'
            '<h1 data-slot="headline">Welcome</h1>'
            '<p data-slot="body-1">Description here</p>'
            '<a data-slot="cta-1" href="/buy">Buy Now</a>'
            '</div>'
            '<div data-section="s2">'
            '<h2 data-slot="heading-1">Features</h2>'
            '<p data-slot="body-2">Feature details</p>'
            '</div>'
        )
        report = validate_slot_nesting(html)
        assert report.passed
        assert len(report.violations) == 0


# --------------------------------------------------------------------------
# Layer 1: strip_violating_slots
# --------------------------------------------------------------------------


class TestStripViolatingSlots:
    """Tests for strip_violating_slots."""

    def test_strips_cross_section_slot_attr(self):
        """Violating data-slot attribute is removed, sections preserved."""
        html = (
            '<a data-slot="cta-1" href="/buy">'
            '<section data-section="s1"><p>Section 1</p></section>'
            '<section data-section="s2"><p>Section 2</p></section>'
            '</a>'
        )
        report = validate_slot_nesting(html)
        assert not report.passed

        cleaned = strip_violating_slots(html, report)

        # Slot attribute should be removed
        assert 'data-slot="cta-1"' not in cleaned
        # <a> tag should still exist (just without slot attr)
        assert '<a' in cleaned
        # Sections must survive
        assert 'data-section="s1"' in cleaned
        assert 'data-section="s2"' in cleaned
        assert "Section 1" in cleaned
        assert "Section 2" in cleaned

        # Re-validate: should pass now
        report2 = validate_slot_nesting(cleaned)
        assert report2.passed


# --------------------------------------------------------------------------
# Layer 3: _SlotReplacer rollback guard
# --------------------------------------------------------------------------


class TestSlotReplacerGuard:
    """Tests for the _SlotReplacer cross-section rollback guard."""

    def test_slot_replacer_preserves_sections_on_cross_section_slot(self):
        """When _template_swap encounters a slot spanning sections,
        the rollback guard should preserve all section content."""
        from viraltracker.services.landing_page_analysis.mockup_service import (
            MockupService,
        )

        template_html = (
            '<html><body>'
            '<a data-slot="cta-1" href="/buy">'
            '<section data-section="s1">'
            '<h1>Welcome</h1><p>Content 1</p>'
            '</section>'
            '<section data-section="s2">'
            '<h2>Features</h2><p>Content 2</p>'
            '</section>'
            '</a>'
            '</body></html>'
        )
        slot_map = {"cta-1": "REPLACED TEXT"}

        svc = MockupService()
        result = svc._template_swap(
            template_html=template_html,
            blueprint={},
            brand_profile=None,
            slot_map=slot_map,
        )

        # Sections MUST survive (not be replaced by "REPLACED TEXT")
        assert "data-section" in result
        assert "Welcome" in result
        assert "Content 1" in result
        assert "Features" in result
        assert "Content 2" in result
        # The replacement text should NOT appear (rollback aborted it)
        assert "REPLACED TEXT" not in result


# --------------------------------------------------------------------------
# Layer 4: Visibility filtering (hidden elements should not get slots)
# --------------------------------------------------------------------------

# Load element_classifier module via importlib to avoid __init__.py chain
_ec_path = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "viraltracker", "services", "landing_page_analysis", "multipass",
    "surgery", "element_classifier.py",
)
_ec_spec = importlib.util.spec_from_file_location("_element_classifier", _ec_path)
_element_classifier = importlib.util.module_from_spec(_ec_spec)
_ec_spec.loader.exec_module(_element_classifier)
_is_visually_hidden = _element_classifier._is_visually_hidden
ElementClassifier = _element_classifier.ElementClassifier


class TestVisibilityFiltering:
    """Tests that hidden elements are NOT assigned data-slot attributes."""

    def test_display_none_skipped(self):
        """Element with style='display:none' should not get a data-slot."""
        classifier = ElementClassifier()
        html = '<h1 style="display:none">Hidden Heading</h1><h1>Visible</h1>'
        result, stats = classifier._deterministic_classify(html)
        # The hidden h1 should NOT have a data-slot
        assert 'style="display:none" data-slot' not in result
        # The visible h1 SHOULD have a slot
        assert 'data-slot="headline"' in result

    def test_aria_hidden_skipped(self):
        """Element with aria-hidden='true' should not get a data-slot."""
        classifier = ElementClassifier()
        html = '<p aria-hidden="true">Screen-reader only</p><p>Visible text</p>'
        result, stats = classifier._deterministic_classify(html)
        # The aria-hidden paragraph should NOT have a data-slot
        assert 'aria-hidden="true" data-slot' not in result
        # The visible paragraph SHOULD have a slot
        assert 'data-slot="body-1"' in result

    def test_hidden_attribute_skipped(self):
        """Element with the 'hidden' boolean attribute should not get a data-slot."""
        classifier = ElementClassifier()
        html = '<h2 hidden>Hidden subhead</h2><h2>Visible subhead</h2>'
        result, stats = classifier._deterministic_classify(html)
        # The hidden h2 should NOT have a data-slot
        assert 'hidden data-slot' not in result
        assert 'hidden>Hidden subhead' in result or 'hidden >Hidden subhead' in result

    def test_visible_element_gets_slot(self):
        """Normal visible element should get a data-slot as usual."""
        classifier = ElementClassifier()
        html = '<h1 class="hero-title">Welcome</h1>'
        result, stats = classifier._deterministic_classify(html)
        assert 'data-slot="headline"' in result

    def test_hidden_class_not_false_positive(self):
        """class='hidden' inside a quoted attribute should NOT trigger hidden check."""
        # _is_visually_hidden strips quoted values before checking for bare 'hidden'
        assert not _is_visually_hidden('class="hidden-on-mobile"')
        # But bare hidden attribute should match
        assert _is_visually_hidden(' hidden ')

    def test_visibility_hidden_inline_style(self):
        """visibility:hidden in inline style should be detected."""
        assert _is_visually_hidden('style="visibility: hidden; color: red"')
        assert not _is_visually_hidden('style="color: red"')
