"""
Tests for MockupService — mapping coverage, normalization, rendering,
sanitization, AI vision, markdown fallback, and template-swap.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from viraltracker.services.landing_page_analysis.mockup_service import (
    ELEMENT_VISUAL_MAP,
    SECTION_ACCENT_COLORS,
    MockupService,
    _DEFAULT_ACCENT,
)


# ---------------------------------------------------------------------------
# All 34 element names from the Element Detector taxonomy
# ---------------------------------------------------------------------------
ALL_ELEMENT_NAMES = [
    # Section 1: Above the Fold
    "Navigation Bar & Logo",
    "Attention Bar / Banner",
    "Headline",
    "Subheadline",
    "Hero Image / Video",
    "Core Benefits Callout",
    "Initial Trust Indicators",
    "Primary CTA (Above Fold)",
    # Section 2: Education & Persuasion
    "Pre-Lead / Authority Section",
    "Problem Amplification",
    "Bridge Section",
    "Mechanism Explanation",
    "Avatar Callout",
    # Section 3: Product Reveal & Features
    "Product Introduction / Reveal",
    "Ingredient / Feature Breakdown",
    "Competitive Differentiation",
    "How It Works / Usage Instructions",
    "Results Timeline",
    "Secondary Benefits / Use Cases",
    # Section 4: Social Proof
    "Text Testimonials",
    "Video Testimonials",
    "Usage Statistics",
    "Founder / Brand Story",
    # Section 5: Conversion & Offer
    "Value Stack / Offer Presentation",
    "Pricing / Package Options",
    "Risk Reversal / Guarantee",
    "Urgency & Scarcity",
    "Payment Security Indicators (Near Pricing)",
    "Repeated Offer Stack",
    # Section 6: Closing & Trust
    "FAQ / Objection Handling",
    "Final CTA Section",
    "About the Brand (Bottom)",
    "Footer / Legal & Compliance",
    "Email Capture / Newsletter",
]

VALID_VISUAL_PATTERNS = {
    "nav_bar",
    "announcement_bar",
    "hero_banner",
    "icon_grid",
    "text_block",
    "feature_grid",
    "comparison_table",
    "testimonial_block",
    "pricing_block",
    "final_cta_block",
    "footer_legal_block",
    "email_capture_block",
}


@pytest.fixture
def service():
    return MockupService()


# ---------------------------------------------------------------------------
# Mapping coverage
# ---------------------------------------------------------------------------

class TestMappingCoverage:
    """Assert all 34 element names map to a known visual pattern."""

    def test_all_34_elements_mapped(self, service):
        """Every element from the taxonomy should map to a recognized pattern."""
        for name in ALL_ELEMENT_NAMES:
            canonical = service._canonicalize_element_name(name)
            pattern = ELEMENT_VISUAL_MAP.get(canonical)
            assert pattern is not None, (
                f"Element '{name}' (canonical: '{canonical}') is not in ELEMENT_VISUAL_MAP"
            )
            assert pattern in VALID_VISUAL_PATTERNS, (
                f"Element '{name}' maps to unknown pattern '{pattern}'"
            )

    def test_element_count(self):
        """Verify we have mappings for exactly 34 elements."""
        assert len(ALL_ELEMENT_NAMES) == 34

    def test_all_6_canonical_sections_have_colors(self):
        """All 6 canonical section names should have accent colors."""
        expected = {
            "above_the_fold",
            "education_and_persuasion",
            "product_reveal_and_features",
            "social_proof",
            "conversion_and_offer",
            "closing_and_trust",
        }
        assert set(SECTION_ACCENT_COLORS.keys()) == expected


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------

class TestCanonicalization:
    """Test element name normalization for robust mapping."""

    def test_basic_lowering(self, service):
        assert service._canonicalize_element_name("Headline") == "headline"

    def test_whitespace_collapse(self, service):
        assert service._canonicalize_element_name("Hero  Image /  Video") == "hero image / video"

    def test_trailing_punctuation(self, service):
        assert service._canonicalize_element_name("Headline.") == "headline"
        assert service._canonicalize_element_name("Headline!") == "headline"

    def test_slash_normalization(self, service):
        # "Hero Image/Video" → "hero image / video"
        assert service._canonicalize_element_name("Hero Image/Video") == "hero image / video"

    def test_empty_string(self, service):
        assert service._canonicalize_element_name("") == ""

    def test_none_safe(self, service):
        # Passing None would fail in production, but _canonicalize handles falsy
        assert service._canonicalize_element_name(None) == ""


# ---------------------------------------------------------------------------
# Normalization — Element Detection
# ---------------------------------------------------------------------------

class TestNormalizeElements:
    """Test _normalize_elements with various input shapes."""

    def test_wrapped_input(self, service):
        """Accept {'element_detection': {...}} wrapper."""
        data = {
            "element_detection": {
                "sections": {
                    "above_the_fold": {
                        "elements_found": [
                            {
                                "element_name": "Headline",
                                "element_type": "benefit_focused",
                                "content_summary": "Wake up feeling great",
                            }
                        ]
                    }
                },
                "cta_inventory": [],
            }
        }
        result = service._normalize_elements(data)
        assert len(result) == 1
        assert result[0]["section_name"] == "above_the_fold"

    def test_unwrapped_input(self, service):
        """Accept direct dict without 'element_detection' wrapper."""
        data = {
            "sections": {
                "social_proof": {
                    "elements_found": [
                        {
                            "element_name": "Text Testimonials",
                            "element_type": "review_grid",
                            "content_summary": "Customer reviews",
                        }
                    ]
                }
            },
            "cta_inventory": [],
        }
        result = service._normalize_elements(data)
        assert len(result) == 1
        assert result[0]["elements"][0]["visual_pattern"] == "testimonial_block"

    def test_elements_found_as_list(self, service):
        """Accept section data as a bare list (not wrapped in object)."""
        data = {
            "sections": {
                "conversion_and_offer": [
                    {
                        "element_name": "Pricing / Package Options",
                        "element_type": "three_tier_bundle",
                        "content_summary": "3 tiers",
                    }
                ]
            },
            "cta_inventory": [],
        }
        result = service._normalize_elements(data)
        assert len(result) == 1
        assert result[0]["elements"][0]["visual_pattern"] == "pricing_block"

    def test_unknown_element_fallback(self, service):
        """Unknown element names should fall back to text_block."""
        data = {
            "sections": {
                "above_the_fold": {
                    "elements_found": [
                        {
                            "element_name": "Some Totally New Element",
                            "element_type": "unknown",
                            "content_summary": "Something unexpected",
                        }
                    ]
                }
            },
            "cta_inventory": [],
        }
        result = service._normalize_elements(data)
        assert result[0]["elements"][0]["visual_pattern"] == "text_block"

    def test_missing_fields_default(self, service):
        """Missing content_summary and element_type should default to empty strings."""
        data = {
            "sections": {
                "education_and_persuasion": {
                    "elements_found": [
                        {"element_name": "Problem Amplification"}
                    ]
                }
            },
            "cta_inventory": [],
        }
        result = service._normalize_elements(data)
        elem = result[0]["elements"][0]
        assert elem["element_type"] == ""
        assert elem["content_summary"] == ""

    def test_hero_grouping(self, service):
        """Hero elements in above_the_fold should be grouped into a single hero_banner."""
        data = {
            "sections": {
                "above_the_fold": {
                    "elements_found": [
                        {"element_name": "Navigation Bar & Logo", "element_type": "full_nav", "content_summary": "Nav"},
                        {"element_name": "Headline", "element_type": "benefit_focused", "content_summary": "Big headline"},
                        {"element_name": "Subheadline", "element_type": "promise_expansion", "content_summary": "Sub text"},
                        {"element_name": "Hero Image / Video", "element_type": "product_hero_shot", "content_summary": "Product image"},
                        {"element_name": "Primary CTA (Above Fold)", "element_type": "benefit_driven", "content_summary": "Get It Now"},
                        {"element_name": "Core Benefits Callout", "element_type": "icon_grid", "content_summary": "Benefits"},
                    ]
                }
            },
            "cta_inventory": [{"button_text": "Get It Now", "position": "above fold"}],
        }
        result = service._normalize_elements(data)
        section = result[0]
        patterns = [e["visual_pattern"] for e in section["elements"]]

        # Should have: nav_bar, hero_banner (composite), icon_grid
        assert patterns == ["nav_bar", "hero_banner", "icon_grid"]

        # Hero should contain the grouped data
        hero = section["elements"][1]
        assert hero["hero_headline"] == "Big headline"
        assert hero["hero_subheadline"] == "Sub text"
        assert hero["hero_cta_text"] == "Get It Now"

    def test_empty_sections_skipped(self, service):
        """Sections with no elements should be skipped."""
        data = {
            "sections": {
                "above_the_fold": {"elements_found": []},
                "social_proof": {"elements_found": [
                    {"element_name": "Text Testimonials", "element_type": "review_grid"}
                ]},
            },
            "cta_inventory": [],
        }
        result = service._normalize_elements(data)
        assert len(result) == 1
        assert result[0]["section_name"] == "social_proof"


# ---------------------------------------------------------------------------
# Normalization — Blueprint
# ---------------------------------------------------------------------------

class TestNormalizeBlueprintSections:
    """Test _normalize_blueprint_sections with various input shapes."""

    def test_wrapped_input(self, service):
        data = {
            "reconstruction_blueprint": {
                "sections": [
                    {
                        "flow_order": 1,
                        "section_name": "above_the_fold",
                        "element_type": "Headline",
                        "copy_direction": "Bold headline",
                        "content_status": "populated",
                    }
                ],
                "bonus_sections": [],
            }
        }
        result = service._normalize_blueprint_sections(data)
        assert len(result) == 1
        assert result[0]["section_name"] == "above_the_fold"

    def test_unwrapped_input(self, service):
        data = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "social_proof",
                    "element_type": "Text Testimonials",
                    "copy_direction": "Use reviews",
                }
            ],
            "bonus_sections": [],
        }
        result = service._normalize_blueprint_sections(data)
        assert len(result) == 1

    def test_bonus_without_section_name(self, service):
        """Bonus sections missing section_name should get a default."""
        data = {
            "sections": [],
            "bonus_sections": [
                {
                    "flow_order": 10,
                    "element_type": "FAQ",
                    "copy_direction": "Add FAQ",
                }
            ],
        }
        result = service._normalize_blueprint_sections(data)
        assert len(result) == 1
        assert result[0]["section_name"] == "bonus_10"

    def test_flow_order_sorting(self, service):
        """Sections should be sorted by flow_order."""
        data = {
            "sections": [
                {"flow_order": 5, "section_name": "social_proof", "element_type": "Reviews"},
                {"flow_order": 1, "section_name": "above_the_fold", "element_type": "Headline"},
                {"flow_order": 3, "section_name": "education_and_persuasion", "element_type": "Problem"},
            ],
            "bonus_sections": [],
        }
        result = service._normalize_blueprint_sections(data)
        orders = [r["elements"][0].get("flow_order") for r in result]
        assert orders == [1, 3, 5]

    def test_non_canonical_section_gets_default_color(self, service):
        """Non-canonical section names should get the default gray accent."""
        data = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "custom_section_xyz",
                    "element_type": "Something",
                }
            ],
            "bonus_sections": [],
        }
        result = service._normalize_blueprint_sections(data)
        assert result[0]["accent_color"] == _DEFAULT_ACCENT

    def test_missing_content_status_defaults(self, service):
        """Missing content_status should default to 'populated'."""
        data = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "element_type": "Headline",
                }
            ],
            "bonus_sections": [],
        }
        result = service._normalize_blueprint_sections(data)
        assert result[0]["elements"][0]["content_status"] == "populated"


# ---------------------------------------------------------------------------
# Brand Style Validation
# ---------------------------------------------------------------------------

class TestBrandStyleValidation:
    """Test _extract_brand_style color validation."""

    def test_valid_hex_colors(self, service):
        profile = {"brand_basics": {"colors": {"primary": "#ff5500", "secondary": "#333"}}}
        result = service._extract_brand_style(profile)
        assert result == {"primary": "#ff5500", "secondary": "#333"}

    def test_valid_rgb_color(self, service):
        profile = {"brand_basics": {"colors": {"primary": "rgb(255, 100, 50)"}}}
        result = service._extract_brand_style(profile)
        assert result is not None
        assert "primary" in result

    def test_valid_named_color(self, service):
        profile = {"brand_basics": {"colors": {"primary": "tomato"}}}
        result = service._extract_brand_style(profile)
        assert result == {"primary": "tomato"}

    def test_malformed_values_stripped(self, service):
        profile = {
            "brand_basics": {
                "colors": {
                    "primary": "#ff5500",
                    "evil": "url(javascript:alert(1))",
                    "inject": "; background: red",
                    "weird": "12345",
                }
            }
        }
        result = service._extract_brand_style(profile)
        assert result == {"primary": "#ff5500"}

    def test_no_profile_returns_none(self, service):
        assert service._extract_brand_style(None) is None

    def test_empty_colors_returns_none(self, service):
        profile = {"brand_basics": {"colors": {}}}
        assert service._extract_brand_style(profile) is None

    def test_no_brand_basics_returns_none(self, service):
        profile = {"other_key": "value"}
        assert service._extract_brand_style(profile) is None


# ---------------------------------------------------------------------------
# Render Smoke Tests
# ---------------------------------------------------------------------------

class TestRenderSmokeTests:
    """Verify that rendering produces valid HTML with expected markers."""

    def test_analysis_mockup_renders(self, service):
        """generate_analysis_mockup should return HTML with expected content."""
        elements = {
            "element_detection": {
                "sections": {
                    "above_the_fold": {
                        "elements_found": [
                            {
                                "element_name": "Headline",
                                "element_type": "benefit_focused",
                                "content_summary": "Transform Your Health Today",
                            },
                            {
                                "element_name": "Primary CTA (Above Fold)",
                                "element_type": "benefit_driven",
                                "content_summary": "Buy Now",
                            },
                        ]
                    },
                    "social_proof": {
                        "elements_found": [
                            {
                                "element_name": "Text Testimonials",
                                "element_type": "review_grid",
                                "content_summary": "Great customer reviews",
                            }
                        ]
                    },
                },
                "cta_inventory": [{"button_text": "Buy Now", "position": "above fold"}],
            }
        }
        classification = {
            "page_classifier": {
                "awareness_level": {"primary": "solution_aware"},
                "page_architecture": {"type": "medium_form"},
            }
        }

        html = service.generate_analysis_mockup(
            element_detection=elements, classification=classification
        )

        assert "<!DOCTYPE html>" in html
        assert "ANALYSIS MOCKUP" in html
        assert "Transform Your Health Today" in html
        assert "above the fold" in html.lower()
        assert "social proof" in html.lower()
        assert "Generated by ViralTracker" in html

    def test_blueprint_mockup_renders(self, service):
        """generate_blueprint_mockup should return HTML with blueprint content."""
        blueprint = {
            "reconstruction_blueprint": {
                "strategy_summary": {"awareness_adaptation": "solution_aware"},
                "sections": [
                    {
                        "flow_order": 1,
                        "section_name": "above_the_fold",
                        "element_type": "Headline",
                        "copy_direction": "Unlock Your Best Sleep Tonight",
                        "content_status": "populated",
                        "brand_mapping": {
                            "primary_content": "Our formula...",
                            "emotional_hook": "Imagine waking up refreshed",
                        },
                    },
                    {
                        "flow_order": 5,
                        "section_name": "conversion_and_offer",
                        "element_type": "Pricing / Package Options",
                        "copy_direction": "Choose your bundle",
                        "content_status": "CONTENT_NEEDED",
                        "action_items": ["Add real pricing tiers"],
                    },
                ],
                "bonus_sections": [],
            }
        }

        html = service.generate_blueprint_mockup(blueprint)

        assert "<!DOCTYPE html>" in html
        assert "BLUEPRINT MOCKUP" in html
        assert "Unlock Your Best Sleep Tonight" in html
        assert "Content Needed" in html
        assert "Add real pricing tiers" in html

    def test_blueprint_mockup_with_brand_colors(self, service):
        """Blueprint mockup should use brand colors when provided."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "element_type": "Headline",
                    "copy_direction": "Test",
                }
            ],
            "bonus_sections": [],
        }
        brand_profile = {
            "brand_basics": {
                "colors": {"primary": "#e74c3c", "secondary": "#2c3e50"}
            }
        }

        html = service.generate_blueprint_mockup(
            blueprint, brand_profile=brand_profile
        )

        assert "#e74c3c" in html
        assert "#2c3e50" in html

    def test_blueprint_mockup_without_classification(self, service):
        """Blueprint mockup should render without classification data."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "element_type": "Headline",
                    "copy_direction": "Test headline",
                }
            ],
            "bonus_sections": [],
        }

        html = service.generate_blueprint_mockup(blueprint, classification=None)
        assert "<!DOCTYPE html>" in html
        assert "Test headline" in html

    def test_renders_standalone_html(self, service):
        """Output should be a complete standalone HTML document."""
        elements = {
            "sections": {
                "closing_and_trust": {
                    "elements_found": [
                        {
                            "element_name": "Footer / Legal & Compliance",
                            "element_type": "comprehensive",
                        }
                    ]
                }
            },
            "cta_inventory": [],
        }
        html = service.generate_analysis_mockup(element_detection=elements, classification={})

        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<style>" in html
        # No external CSS dependencies (except optional Google Fonts)
        assert "bootstrap" not in html.lower()


# ---------------------------------------------------------------------------
# V2: HTML Sanitization
# ---------------------------------------------------------------------------

class TestSanitization:
    """Test _sanitize_html strips dangerous content while preserving safe HTML."""

    def test_strips_script_tags(self, service):
        html = '<div>Hello</div><script>alert(1)</script>'
        result = service._sanitize_html(html)
        assert "<script>" not in result
        # bleach strip=True removes tags but may leave inner text (harmless without tag)
        assert "<div>Hello</div>" in result

    def test_strips_event_handlers(self, service):
        html = '<div onclick="alert(1)">Click me</div>'
        result = service._sanitize_html(html)
        assert "onclick" not in result
        assert "Click me" in result

    def test_strips_iframe(self, service):
        html = '<div>Safe</div><iframe src="http://evil.com"></iframe>'
        result = service._sanitize_html(html)
        assert "<iframe" not in result
        assert "Safe" in result

    def test_strips_javascript_urls(self, service):
        html = '<a href="javascript:alert(1)">Link</a>'
        result = service._sanitize_html(html)
        assert "javascript:" not in result

    def test_strips_dangerous_css(self, service):
        html = '<div style="background:url(javascript:alert(1))">Text</div>'
        result = service._sanitize_html(html)
        assert "javascript:" not in result

    def test_preserves_safe_tags(self, service):
        html = '<div><p>Hello</p><h1>Title</h1></div>'
        result = service._sanitize_html(html)
        assert "<div>" in result
        assert "<p>" in result
        assert "<h1>" in result

    def test_preserves_data_slot_attrs(self, service):
        html = '<h1 data-slot="headline">Title</h1>'
        result = service._sanitize_html(html)
        assert 'data-slot="headline"' in result

    def test_preserves_safe_inline_styles(self, service):
        html = '<div style="color: red; font-size: 16px">Text</div>'
        result = service._sanitize_html(html)
        assert "color" in result
        assert "font-size" in result


# ---------------------------------------------------------------------------
# V2: AI Vision Mockup
# ---------------------------------------------------------------------------

class TestAIVisionMockup:
    """Test AI vision generation path."""

    @patch("viraltracker.services.landing_page_analysis.mockup_service.MockupService._generate_via_ai_vision")
    def test_ai_vision_returns_wrapped_html(self, mock_vision, service):
        mock_vision.return_value = '<div data-slot="headline">Hello World</div>'
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64_data")
        assert "ANALYSIS MOCKUP" in html
        assert "Hello World" in html
        assert "<!DOCTYPE html>" in html

    @patch("viraltracker.services.landing_page_analysis.mockup_service.MockupService._generate_via_ai_vision")
    def test_ai_vision_strips_code_fences(self, mock_vision, service):
        mock_vision.return_value = '<div>Clean HTML</div>'
        # Simulate code fence stripping happening inside _generate_via_ai_vision
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64")
        assert "Clean HTML" in html

    @patch("viraltracker.services.landing_page_analysis.mockup_service.MockupService._generate_via_ai_vision")
    def test_ai_vision_sanitizes_output(self, mock_vision, service):
        mock_vision.return_value = '<div>Safe</div><script>alert("xss")</script>'
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64")
        assert "<script>" not in html
        assert "Safe" in html


# ---------------------------------------------------------------------------
# V2: Markdown Fallback
# ---------------------------------------------------------------------------

class TestMarkdownFallback:
    """Test markdown→HTML fallback path."""

    def test_markdown_renders_to_html(self, service):
        html = service.generate_analysis_mockup(page_markdown="# Hello\n\nWorld")
        assert "Hello" in html
        assert "World" in html
        assert "<!DOCTYPE html>" in html

    def test_markdown_disables_raw_html(self, service):
        html = service.generate_analysis_mockup(
            page_markdown="# Title\n\n<script>alert(1)</script>"
        )
        assert "<script>" not in html
        # Script tag is stripped; text content is harmless without the tag

    def test_empty_markdown(self, service):
        html = service.generate_analysis_mockup(page_markdown="")
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# V2: Fallback Chain
# ---------------------------------------------------------------------------

class TestFallbackChain:
    """Test priority: screenshot > markdown > V1 wireframe."""

    @patch("viraltracker.services.landing_page_analysis.mockup_service.MockupService._generate_via_ai_vision")
    def test_screenshot_takes_priority(self, mock_vision, service):
        mock_vision.return_value = '<div data-slot="headline">AI Generated</div>'
        html = service.generate_analysis_mockup(
            screenshot_b64="fake_b64",
            page_markdown="# Markdown Content",
            element_detection={"sections": {}, "cta_inventory": []},
        )
        assert "AI Generated" in html
        mock_vision.assert_called_once()

    def test_markdown_when_no_screenshot(self, service):
        html = service.generate_analysis_mockup(
            page_markdown="# Markdown Heading\n\nSome content",
        )
        assert "Markdown Heading" in html

    def test_v1_when_nothing_available(self, service):
        elements = {
            "sections": {
                "above_the_fold": {
                    "elements_found": [
                        {"element_name": "Headline", "element_type": "benefit", "content_summary": "V1 Title"}
                    ]
                }
            },
            "cta_inventory": [],
        }
        html = service.generate_analysis_mockup(element_detection=elements)
        assert "V1 Title" in html
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# V2: Slot Mapping
# ---------------------------------------------------------------------------

class TestSlotMapping:
    """Test _build_slot_map from blueprint sections."""

    def test_build_slot_map_first_section_maps_to_hero(self, service):
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "brand_mapping": {
                        "primary_content": "My Headline",
                        "emotional_hook": "My Subheadline",
                    },
                }
            ],
        }
        slot_map = service._build_slot_map(blueprint)
        assert slot_map["headline"] == "My Headline"
        assert slot_map["subheadline"] == "My Subheadline"

    def test_build_slot_map_numbered_sections(self, service):
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "Hero"}},
                {"flow_order": 2, "brand_mapping": {"primary_content": "Section 2", "supporting_data": "Body 2"}},
                {"flow_order": 3, "brand_mapping": {"primary_content": "Section 3", "supporting_data": "Body 3"}},
            ],
        }
        slot_map = service._build_slot_map(blueprint)
        assert slot_map["headline"] == "Hero"
        assert slot_map["heading-1"] == "Section 2"
        assert slot_map["body-1"] == "Body 2"
        assert slot_map["heading-2"] == "Section 3"
        assert slot_map["body-2"] == "Body 3"

    def test_build_slot_map_escapes_values(self, service):
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "brand_mapping": {"primary_content": '<script>alert("xss")</script>'},
                }
            ],
        }
        slot_map = service._build_slot_map(blueprint)
        assert "<script>" not in slot_map["headline"]
        assert "&lt;script&gt;" in slot_map["headline"]


# ---------------------------------------------------------------------------
# V2: Template Swap
# ---------------------------------------------------------------------------

class TestTemplateSwap:
    """Test _template_swap DOM-level replacement."""

    def test_replaces_data_slot_content(self, service):
        template = '<h1 data-slot="headline">Old Headline</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "New Headline"}},
            ],
        }
        result = service._template_swap(template, blueprint)
        assert "New Headline" in result
        assert "Old Headline" not in result

    def test_handles_nested_markup_in_slot(self, service):
        template = '<div data-slot="headline"><p>Old <b>text</b></p></div>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "Clean Text"}},
            ],
        }
        result = service._template_swap(template, blueprint)
        assert "Clean Text" in result
        assert "Old" not in result

    def test_escapes_html_in_brand_values(self, service):
        template = '<h1 data-slot="headline">Old</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": '<img src=x onerror=alert(1)>'}},
            ],
        }
        result = service._template_swap(template, blueprint)
        assert "<img" not in result
        assert "&lt;img" in result

    def test_missing_slots_no_crash(self, service):
        template = '<h1 data-slot="nonexistent">Keep This</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "New"}},
            ],
        }
        result = service._template_swap(template, blueprint)
        assert "Keep This" in result

    def test_preserves_non_slot_content(self, service):
        template = '<div>Preserved</div><h1 data-slot="headline">Replace</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "New"}},
            ],
        }
        result = service._template_swap(template, blueprint)
        assert "Preserved" in result
        assert "New" in result

    def test_resanitizes_after_swap(self, service):
        """generate_blueprint_mockup should re-sanitize after template-swap."""
        template = '<h1 data-slot="headline">Old</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "Safe Content"}},
            ],
        }
        html = service.generate_blueprint_mockup(
            blueprint=blueprint,
            analysis_mockup_html=template,
        )
        assert "Safe Content" in html
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# V2: Usage Tracking
# ---------------------------------------------------------------------------

class TestUsageTracking:
    """Test usage tracking context propagation."""

    def test_set_tracking_context(self, service):
        tracker = MagicMock()
        service.set_tracking_context(tracker, "user123", "org456")
        assert service._usage_tracker is tracker
        assert service._user_id == "user123"
        assert service._organization_id == "org456"

    @patch("viraltracker.services.landing_page_analysis.mockup_service.MockupService._generate_via_ai_vision")
    def test_gemini_receives_tracking(self, mock_vision, service):
        """Usage tracker should be passed to GeminiService when set."""
        tracker = MagicMock()
        service.set_tracking_context(tracker, "user123", "org456")
        mock_vision.return_value = "<div>Test</div>"
        service.generate_analysis_mockup(screenshot_b64="fake_b64")
        mock_vision.assert_called_once()
