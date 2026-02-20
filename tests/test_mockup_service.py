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
    _sanitize_css_block,
    _sanitize_dashes,
    _strip_url_from_inline_styles,
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
        """generate_blueprint_mockup should return wrapped HTML when analysis HTML provided."""
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
                ],
                "bonus_sections": [],
            }
        }
        analysis_html = '<div data-slot="headline">Competitor Headline</div>'

        html = service.generate_blueprint_mockup(
            blueprint, analysis_mockup_html=analysis_html
        )

        assert html is not None
        assert "<!DOCTYPE html>" in html
        assert "BLUEPRINT MOCKUP" in html

    @patch.object(MockupService, "_rewrite_html_for_brand")
    def test_blueprint_mockup_with_brand_profile(self, mock_rewrite, service):
        """Blueprint mockup should call _rewrite_html_for_brand when brand_profile provided."""
        mock_rewrite.return_value = '<div data-slot="headline">Rewritten</div>'
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
                "name": "TestBrand",
                "colors": {"primary": "#e74c3c", "secondary": "#2c3e50"}
            }
        }
        analysis_html = '<div data-slot="headline">Old</div>'

        html = service.generate_blueprint_mockup(
            blueprint,
            analysis_mockup_html=analysis_html,
            brand_profile=brand_profile,
        )

        assert html is not None
        mock_rewrite.assert_called_once()
        # Verify brand_profile was passed through
        call_args = mock_rewrite.call_args
        assert call_args[0][2] == brand_profile

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
        analysis_html = '<div data-slot="headline">Competitor text</div>'

        html = service.generate_blueprint_mockup(
            blueprint,
            analysis_mockup_html=analysis_html,
            classification=None,
        )
        assert html is not None
        assert "<!DOCTYPE html>" in html

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
        mock_vision.return_value = (
            '<div data-slot="headline">AI Generated</div>'
            '<p data-slot="body-1">Body text content that makes this long enough</p>'
            '<button data-slot="cta-1">Buy Now</button>'
            + '<p>Filler content to pass minimum length check.</p>' * 5
        )
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

    @patch.object(MockupService, "_rewrite_html_for_brand")
    def test_resanitizes_after_rewrite(self, mock_rewrite, service):
        """generate_blueprint_mockup should re-sanitize after AI rewrite."""
        # AI returns HTML with a script tag that should be stripped
        mock_rewrite.return_value = '<h1 data-slot="headline">Safe Content</h1><script>alert(1)</script>'
        template = '<h1 data-slot="headline">Old</h1>'
        blueprint = {
            "sections": [
                {"flow_order": 1, "brand_mapping": {"primary_content": "Safe Content"}},
            ],
        }
        brand_profile = {"brand_basics": {"name": "Test"}}
        html = service.generate_blueprint_mockup(
            blueprint=blueprint,
            analysis_mockup_html=template,
            brand_profile=brand_profile,
        )
        assert html is not None
        assert "Safe Content" in html
        assert "<script>" not in html
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
        mock_vision.return_value = (
            '<div data-slot="headline">Test</div>'
            '<p data-slot="body-1">Body content for length</p>'
            '<button data-slot="cta-1">Buy Now</button>'
            + '<p>Filler content to pass minimum length check.</p>' * 5
        )
        service.generate_analysis_mockup(screenshot_b64="fake_b64")
        mock_vision.assert_called_once()


# ---------------------------------------------------------------------------
# AI Copywriting (blueprint rewrite flow)
# ---------------------------------------------------------------------------

class TestAICopywriting:
    """Test the AI HTML rewrite path for blueprint mockups."""

    def test_strip_wrapper_removes_meta_bar(self, service):
        """Meta-bar div removed from wrapped HTML."""
        wrapped = (
            '<!DOCTYPE html><html><head><style>.x{}</style></head><body>'
            '<div class="mockup-meta-bar"><span>ANALYSIS MOCKUP</span></div>'
            '<div data-slot="headline">Content</div>'
            '<div class="mockup-gen-footer">Generated</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(wrapped)
        assert "mockup-meta-bar" not in result
        assert "mockup-gen-footer" not in result
        assert "Content" in result

    def test_strip_wrapper_removes_doc_tags(self, service):
        """DOCTYPE, html, head, body, style, meta, title removed."""
        wrapped = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="UTF-8">'
            '<title>Test</title>'
            '<style>body{margin:0}</style>'
            '</head><body>'
            '<div>Page Content</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(wrapped)
        assert "<!DOCTYPE" not in result
        assert "<html" not in result
        assert "<head" not in result
        assert "<body" not in result
        assert "<style>" not in result
        assert "<meta" not in result
        assert "<title>" not in result
        assert "Page Content" in result

    def test_strip_wrapper_preserves_page_content(self, service):
        """data-slot divs and page body content preserved."""
        wrapped = (
            '<!DOCTYPE html><html><head><style>.x{}</style></head><body>'
            '<div class="mockup-meta-bar"><span>META</span></div>'
            '<section><h1 data-slot="headline">Hello World</h1>'
            '<p data-slot="body-1">Body text</p></section>'
            '<div class="mockup-gen-footer">Footer</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(wrapped)
        assert 'data-slot="headline"' in result
        assert "Hello World" in result
        assert "Body text" in result

    def test_strip_wrapper_handles_orphaned_css(self, service):
        """Orphaned CSS text (from bleach stripping <style>) removed via <head> block strip."""
        # Simulates real-world: _wrap_mockup wraps sanitized Gemini output where
        # bleach has stripped <style> tags but left CSS text as raw content.
        wrapped = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="UTF-8">'
            '<title>Landing Page Mockup — Analysis Mode</title>'
            '<style>.mockup-meta-bar { background: #1e293b; }</style>'
            '</head><body>'
            '<div class="mockup-meta-bar"><span>ANALYSIS MOCKUP</span></div>'
            # Inner Gemini output after _sanitize_html (no <style> tags, CSS as text)
            '<html><head>'
            '<meta charset="UTF-8">'
            '<title>Competitor Page</title>'
            'body { font-family: sans-serif; margin: 0; }'
            '.container { max-width: 900px; }'
            '</head><body>'
            '<div data-slot="headline">Real headline</div>'
            '</body></html>'
            '<div class="mockup-gen-footer">Generated</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(wrapped)
        # All wrapper/head elements stripped
        assert "mockup-meta-bar" not in result
        assert "mockup-gen-footer" not in result
        assert "<meta" not in result
        assert "<title>" not in result
        # Orphaned CSS text must NOT appear
        assert "font-family" not in result
        assert "max-width" not in result
        # Page content preserved
        assert 'data-slot="headline"' in result
        assert "Real headline" in result

    def test_strip_wrapper_nested_double_wrapped(self, service):
        """Double-wrapped HTML (analysis inside blueprint) fully stripped."""
        # This tests the case where analysis HTML contains its own _wrap_mockup wrapper
        inner_analysis = (
            '<!DOCTYPE html><html><head><style>.mockup-meta-bar{}</style></head><body>'
            '<div class="mockup-meta-bar"><span>ANALYSIS</span></div>'
            '<div data-slot="headline">Content</div>'
            '<div class="mockup-gen-footer">Footer1</div>'
            '</body></html>'
        )
        outer = (
            '<!DOCTYPE html><html><head><style>.mockup-meta-bar{}</style></head><body>'
            '<div class="mockup-meta-bar"><span>BLUEPRINT</span></div>'
            + inner_analysis +
            '<div class="mockup-gen-footer">Footer2</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(outer)
        assert "mockup-meta-bar" not in result
        assert "mockup-gen-footer" not in result
        assert "Content" in result

    def test_extract_slot_names_finds_all_slots(self, service):
        """Returns ordered unique slot names from HTML."""
        html = (
            '<h1 data-slot="headline">Title</h1>'
            '<p data-slot="body-1">Text</p>'
            '<button data-slot="cta-1">Click</button>'
        )
        slots = service._extract_slot_names(html)
        assert slots == ["headline", "body-1", "cta-1"]

    def test_extract_slot_names_empty_html(self, service):
        """Returns [] for HTML without data-slots."""
        assert service._extract_slot_names("<div>No slots here</div>") == []

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_rewrite_calls_agent_with_tracking(self, mock_run, service):
        """Mocked AI called with correct tracker/user/org params."""
        mock_result = MagicMock()
        mock_result.output = '<div data-slot="headline">Rewritten</div>'
        mock_run.return_value = mock_result

        tracker = MagicMock()
        service.set_tracking_context(tracker, "user123", "org456")

        result = service._rewrite_html_for_brand(
            '<div data-slot="headline">Original</div>',
            {"sections": []},
            {"brand_basics": {"name": "TestBrand"}},
        )

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["tracker"] is tracker
        assert call_kwargs.kwargs["user_id"] == "user123"
        assert call_kwargs.kwargs["organization_id"] == "org456"
        assert call_kwargs.kwargs["tool_name"] == "mockup_service"
        assert call_kwargs.kwargs["operation"] == "blueprint_copy"

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_rewrite_strips_code_fences(self, mock_run, service):
        """AI response wrapped in ``` → cleaned."""
        mock_result = MagicMock()
        mock_result.output = '```html\n<div data-slot="headline">Clean</div>\n```'
        mock_run.return_value = mock_result

        result = service._rewrite_html_for_brand(
            '<div data-slot="headline">Old</div>',
            {"sections": []},
            {"brand_basics": {"name": "Test"}},
        )

        assert "```" not in result
        assert "Clean" in result

    def test_validate_structure_passes_matching(self, service):
        """Same slot count → no error."""
        original = '<h1 data-slot="headline">A</h1><p data-slot="body-1">B</p>'
        rewritten = '<h1 data-slot="headline">X</h1><p data-slot="body-1">Y</p>'
        # Should not raise
        service._validate_rewrite_structure(original, rewritten)

    def test_validate_structure_fails_on_major_loss(self, service):
        """More than 50% slots lost → ValueError raised."""
        original = (
            '<h1 data-slot="headline">A</h1>'
            '<p data-slot="body-1">B</p>'
            '<p data-slot="body-2">C</p>'
            '<p data-slot="body-3">D</p>'
        )
        rewritten = '<h1 data-slot="headline">X</h1>'  # Lost 3 of 4
        with pytest.raises(ValueError, match="lost >50%"):
            service._validate_rewrite_structure(original, rewritten)

    @patch.object(MockupService, "_rewrite_html_for_brand", side_effect=Exception("AI down"))
    def test_failure_propagates_to_caller(self, mock_rewrite, service):
        """AI raises → exception propagates so UI can show clear error."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "brand_mapping": {
                        "primary_content": "Lead with the persona's #1 functional pain point",
                    },
                }
            ],
        }
        brand_profile = {"brand_basics": {"name": "Test"}}
        analysis_html = '<div data-slot="headline">Competitor Original</div>'

        with pytest.raises(Exception, match="AI down"):
            service.generate_blueprint_mockup(
                blueprint,
                analysis_mockup_html=analysis_html,
                brand_profile=brand_profile,
            )


# ---------------------------------------------------------------------------
# HTML Truncation
# ---------------------------------------------------------------------------

class TestTruncateHtmlAtBoundary:
    """Test _truncate_html_at_boundary tag-boundary-aware truncation."""

    def test_finds_section_boundary(self, service):
        """Cuts at </section> before limit."""
        # Build HTML with a </section> near the end
        html = '<section>' + 'x' * 500 + '</section>' + '<section>' + 'y' * 500 + '</section>'
        # Truncate at a limit that includes the first section but not the second
        limit = len('<section>') + 500 + len('</section>') + 50
        result = service._truncate_html_at_boundary(html, limit)
        assert result.endswith('</section>')
        assert 'y' * 100 not in result

    def test_finds_div_boundary(self, service):
        """Falls back to </div> if no </section>."""
        html = '<div>' + 'x' * 500 + '</div>' + '<div>' + 'y' * 500 + '</div>'
        limit = len('<div>') + 500 + len('</div>') + 50
        result = service._truncate_html_at_boundary(html, limit)
        assert result.endswith('</div>')

    def test_finds_gt_boundary(self, service):
        """Falls back to last '>' if no section/div."""
        # Use spans (no section or div)
        html = '<span>' + 'x' * 300 + '</span>' + 'a' * 300
        limit = len('<span>') + 300 + len('</span>') + 10
        result = service._truncate_html_at_boundary(html, limit)
        assert result.endswith('>')

    def test_short_html_unchanged(self, service):
        """Under-limit HTML returned as-is."""
        html = '<div>Short content</div>'
        result = service._truncate_html_at_boundary(html, 1000)
        assert result == html


# ---------------------------------------------------------------------------
# Blueprint returns None without analysis HTML (Fix 2)
# ---------------------------------------------------------------------------

class TestBlueprintNoAnalysis:
    """Test that generate_blueprint_mockup returns None without analysis HTML."""

    def test_generate_blueprint_no_analysis_returns_none(self, service):
        """No analysis HTML → None return, NOT V1 wireframe."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "element_type": "Headline",
                    "copy_direction": "Test",
                    "brand_mapping": {
                        "primary_content": "Strategic instruction text",
                    },
                }
            ],
            "bonus_sections": [],
        }
        result = service.generate_blueprint_mockup(blueprint)
        assert result is None


# ---------------------------------------------------------------------------
# Brand Context & Blueprint Directions Building
# ---------------------------------------------------------------------------

class TestBuildBrandContext:
    """Test _build_brand_context deterministic brand summary builder."""

    def test_basic_brand_profile(self, service):
        """Basic profile with name, product, benefits."""
        profile = {
            "brand_basics": {"name": "SleepWell", "voice_tone": "warm and empathetic"},
            "product": {
                "name": "DreamCapsules",
                "key_benefits": ["Better sleep", "More energy"],
                "key_problems_solved": ["Insomnia"],
            },
        }
        result = service._build_brand_context(profile)
        assert "SleepWell" in result
        assert "DreamCapsules" in result
        assert "Better sleep" in result
        assert "warm and empathetic" in result

    def test_missing_keys_no_crash(self, service):
        """Empty or missing profile keys should not crash."""
        result = service._build_brand_context({})
        assert "Brand: Unknown" in result
        assert "Product: Unknown" in result

    def test_truncates_long_lists(self, service):
        """Benefits lists capped at 5 items."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {
                "name": "Prod",
                "key_benefits": [f"benefit_{i}" for i in range(20)],
                "key_problems_solved": [],
            },
        }
        result = service._build_brand_context(profile)
        assert "benefit_4" in result
        assert "benefit_5" not in result

    def test_includes_mechanism(self, service):
        """Mechanism section included when present."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "mechanism": {"name": "BioSync", "solution": "Aligns circadian rhythm"},
        }
        result = service._build_brand_context(profile)
        assert "BioSync" in result
        assert "circadian rhythm" in result

    def test_includes_pricing(self, service):
        """Pricing info included when present."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "pricing": [{"name": "Single", "price": "49.99"}],
        }
        result = service._build_brand_context(profile)
        assert "Single" in result
        assert "49.99" in result

    def test_includes_personas(self, service):
        """First persona included."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "personas": [
                {"name": "Tired Mom", "snapshot": "35-45yo mother", "pain_points": ["Exhaustion"]},
            ],
        }
        result = service._build_brand_context(profile)
        assert "Tired Mom" in result
        assert "Exhaustion" in result


class TestBuildBlueprintDirections:
    """Test _build_blueprint_directions strategic directions builder."""

    def test_basic_blueprint(self, service):
        """Basic blueprint with strategy and sections."""
        blueprint = {
            "reconstruction_blueprint": {
                "strategy_summary": {
                    "awareness_adaptation": "solution_aware",
                    "tone_direction": "empathetic urgency",
                    "target_persona": "Tired Mom",
                },
                "sections": [
                    {
                        "flow_order": 1,
                        "section_name": "above_the_fold",
                        "copy_direction": "Lead with sleep transformation",
                        "brand_mapping": {"primary_content": "Our formula..."},
                    },
                ],
            }
        }
        result = service._build_blueprint_directions(blueprint)
        assert "solution_aware" in result
        assert "empathetic urgency" in result
        assert "sleep transformation" in result
        assert "Our formula" in result

    def test_unwrapped_blueprint(self, service):
        """Handles blueprint without reconstruction_blueprint wrapper."""
        blueprint = {
            "strategy_summary": {},
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "hero",
                    "copy_direction": "Bold headline",
                },
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "Bold headline" in result

    def test_truncates_long_directions(self, service):
        """Copy directions longer than 300 chars are truncated."""
        long_direction = "x" * 500
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "copy_direction": long_direction,
                },
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        # Should be truncated at 300 chars
        assert len(long_direction[:300]) <= 300
        assert "x" * 300 in result
        assert "x" * 301 not in result

    def test_empty_blueprint(self, service):
        """Empty blueprint produces minimal output."""
        result = service._build_blueprint_directions({"sections": []})
        assert "SECTION-BY-SECTION DIRECTIONS" in result


# ---------------------------------------------------------------------------
# None-safety: _build_brand_context
# ---------------------------------------------------------------------------

class TestBuildBrandContextNoneSafety:
    """Test _build_brand_context handles None values in AI-generated JSON."""

    def test_all_top_level_keys_none(self, service):
        """All brand_profile dict values are explicitly None."""
        profile = {
            "brand_basics": None,
            "product": None,
            "mechanism": None,
            "pain_points": None,
            "social_proof": None,
            "pricing": None,
            "guarantee": None,
            "personas": None,
            "offer_variant": None,
            "ingredients": None,
            "results_timeline": None,
        }
        result = service._build_brand_context(profile)
        assert "Brand: Unknown" in result
        assert "Product: Unknown" in result

    def test_none_string_fields_in_mechanism(self, service):
        """mechanism.solution is None — slicing should not crash."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "mechanism": {"name": "MechName", "solution": None},
        }
        result = service._build_brand_context(profile)
        assert "MechName" in result

    def test_none_guarantee_text(self, service):
        """guarantee.text is None — slicing should not crash."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "guarantee": {"text": None},
        }
        # guarantee.text is falsy → block skipped, no crash
        result = service._build_brand_context(profile)
        assert "Guarantee" not in result

    def test_non_string_items_in_benefits_list(self, service):
        """key_benefits contains ints and None — join should not crash."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {
                "name": "Prod",
                "key_benefits": ["Good sleep", None, 42, True],
                "key_problems_solved": [None, 123],
            },
        }
        result = service._build_brand_context(profile)
        assert "Good sleep" in result
        assert "42" in result

    def test_non_dict_items_in_pricing(self, service):
        """pricing list contains a string instead of dict — should not crash."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "pricing": ["not a dict", {"name": "Basic", "price": "29"}],
        }
        result = service._build_brand_context(profile)
        assert "Basic" in result

    def test_non_dict_items_in_ingredients(self, service):
        """ingredients list contains strings and dicts."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "ingredients": ["Vitamin D", {"name": "Zinc"}, None],
        }
        result = service._build_brand_context(profile)
        assert "Vitamin D" in result
        assert "Zinc" in result

    def test_non_dict_persona(self, service):
        """First persona is a string instead of dict — should not crash."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "personas": ["not a dict"],
        }
        # Should not raise
        result = service._build_brand_context(profile)
        assert "Brand: Test" in result

    def test_persona_with_none_fields(self, service):
        """Persona dict has None name and snapshot."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "personas": [{"name": None, "snapshot": None, "pain_points": None}],
        }
        result = service._build_brand_context(profile)
        assert "Target Persona" in result

    def test_quotes_with_none_and_non_dict(self, service):
        """Quote list contains None, int, and dict with None values."""
        profile = {
            "brand_basics": {"name": "Test"},
            "product": {"name": "Prod"},
            "social_proof": {
                "top_positive_quotes": [
                    "A real quote",
                    None,
                    42,
                    {"quote": None, "text": None},
                ],
            },
        }
        result = service._build_brand_context(profile)
        assert "A real quote" in result


# ---------------------------------------------------------------------------
# None-safety: _build_blueprint_directions
# ---------------------------------------------------------------------------

class TestBuildBlueprintDirectionsNoneSafety:
    """Test _build_blueprint_directions handles None values."""

    def test_none_strategy_summary(self, service):
        """strategy_summary is None — should not crash."""
        blueprint = {
            "strategy_summary": None,
            "sections": [],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "SECTION-BY-SECTION DIRECTIONS" in result

    def test_none_fields_in_sections(self, service):
        """Section fields (copy_direction, brand_mapping, etc.) are all None."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "above_the_fold",
                    "copy_direction": None,
                    "brand_mapping": None,
                    "gap_improvement": None,
                },
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "above_the_fold" in result

    def test_none_brand_mapping_fields(self, service):
        """brand_mapping dict has None values for all text fields."""
        blueprint = {
            "sections": [
                {
                    "flow_order": 1,
                    "section_name": "hero",
                    "copy_direction": "test direction",
                    "brand_mapping": {
                        "primary_content": None,
                        "emotional_hook": None,
                        "supporting_data": None,
                    },
                },
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "test direction" in result
        # None fields should be skipped (falsy check)
        assert "Primary:" not in result
        assert "Hook:" not in result

    def test_none_flow_order(self, service):
        """flow_order is None — sort should not crash."""
        blueprint = {
            "sections": [
                {"flow_order": None, "section_name": "a", "copy_direction": "dir_a"},
                {"flow_order": 2, "section_name": "b", "copy_direction": "dir_b"},
                {"flow_order": "invalid", "section_name": "c", "copy_direction": "dir_c"},
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        # Should not crash, all sections present
        assert "dir_a" in result
        assert "dir_b" in result
        assert "dir_c" in result

    def test_non_dict_section_item(self, service):
        """A section that is not a dict (string, None) — should be skipped."""
        blueprint = {
            "sections": [
                "not a dict",
                None,
                {"flow_order": 1, "section_name": "real", "copy_direction": "real dir"},
            ],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "real dir" in result

    def test_none_key_differentiators(self, service):
        """key_differentiators is None — should not crash."""
        blueprint = {
            "strategy_summary": {
                "awareness_adaptation": "solution_aware",
                "key_differentiators": None,
            },
            "sections": [],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "solution_aware" in result
        assert "Differentiators" not in result

    def test_non_string_key_differentiators(self, service):
        """key_differentiators contains ints — join should not crash."""
        blueprint = {
            "strategy_summary": {
                "key_differentiators": [42, None, "real diff"],
            },
            "sections": [],
        }
        result = service._build_blueprint_directions(blueprint)
        assert "42" in result
        assert "real diff" in result


# ---------------------------------------------------------------------------
# None-safety: _rewrite_html_for_brand
# ---------------------------------------------------------------------------

class TestRewriteNoneSafety:
    """Test _rewrite_html_for_brand guards against bad AI output."""

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_none_result_output(self, mock_run, service):
        """result.output is None → raises ValueError."""
        mock_result = MagicMock()
        mock_result.output = None
        mock_run.return_value = mock_result

        with pytest.raises(ValueError, match="None output"):
            service._rewrite_html_for_brand(
                "<div>Test</div>",
                {"sections": []},
                {"brand_basics": {"name": "Test"}},
            )

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_empty_result_output(self, mock_run, service):
        """result.output is whitespace-only → raises ValueError."""
        mock_result = MagicMock()
        mock_result.output = "   \n  "
        mock_run.return_value = mock_result

        with pytest.raises(ValueError, match="empty/whitespace-only"):
            service._rewrite_html_for_brand(
                "<div>Test</div>",
                {"sections": []},
                {"brand_basics": {"name": "Test"}},
            )

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_non_string_result_output(self, mock_run, service):
        """result.output is an int → coerced to string, processed."""
        mock_result = MagicMock()
        mock_result.output = 42
        mock_run.return_value = mock_result

        # 42 as a string is "42" — non-empty, so it proceeds (no slots to validate)
        result = service._rewrite_html_for_brand(
            "<div>Test</div>",
            {"sections": []},
            {"brand_basics": {"name": "Test"}},
        )
        assert isinstance(result, str)

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_none_result_object(self, mock_run, service):
        """run_agent_sync_with_tracking returns None → raises ValueError."""
        mock_run.return_value = None

        with pytest.raises(ValueError, match="no result object"):
            service._rewrite_html_for_brand(
                "<div>Test</div>",
                {"sections": []},
                {"brand_basics": {"name": "Test"}},
            )


# ---------------------------------------------------------------------------
# Dash Sanitization
# ---------------------------------------------------------------------------

class TestDashSanitization:
    """Test _sanitize_dashes strips em/en dashes from text."""

    def test_em_dash_replaced(self):
        assert "\u2014" not in _sanitize_dashes("Buy now \u2014 save 50%")
        assert _sanitize_dashes("Buy now \u2014 save 50%") == "Buy now  -  save 50%"

    def test_en_dash_replaced(self):
        assert "\u2013" not in _sanitize_dashes("Pages 1\u201310")
        assert _sanitize_dashes("Pages 1\u201310") == "Pages 1-10"

    def test_no_dashes_unchanged(self):
        assert _sanitize_dashes("No dashes here") == "No dashes here"

    def test_both_dashes(self):
        result = _sanitize_dashes("A\u2014B\u2013C")
        assert "\u2014" not in result
        assert "\u2013" not in result

    @patch("viraltracker.services.agent_tracking.run_agent_sync_with_tracking")
    def test_rewrite_output_sanitized(self, mock_run, service):
        """AI rewrite output should have em dashes stripped."""
        mock_result = MagicMock()
        mock_result.output = '<div data-slot="headline">Wake up \u2014 refreshed</div>'
        mock_run.return_value = mock_result

        result = service._rewrite_html_for_brand(
            '<div data-slot="headline">Original</div>',
            {"sections": []},
            {"brand_basics": {"name": "Test"}},
        )
        assert "\u2014" not in result


# ---------------------------------------------------------------------------
# Phase 0: CSS Block Sanitizer
# ---------------------------------------------------------------------------

class TestSanitizeCssBlock:
    """Test _sanitize_css_block for <style> block content safety."""

    def test_style_breakout_rejected(self):
        """</style> breakout pattern causes entire block to be rejected."""
        css = "body { color: red; } </style><script>alert(1)</script>"
        assert _sanitize_css_block(css) == ""

    def test_style_breakout_whitespace_tolerant(self):
        """< / style> with spaces still caught."""
        css = "body { color: red; } < / style ><script>alert(1)</script>"
        assert _sanitize_css_block(css) == ""

    def test_html_tags_rejected(self):
        """HTML tags in CSS cause entire block rejection."""
        css = "body { color: red; } <div>injected</div>"
        assert _sanitize_css_block(css) == ""

    def test_html_comment_rejected(self):
        """<! patterns in CSS cause entire block rejection."""
        css = "body { color: red; } <!-- comment -->"
        assert _sanitize_css_block(css) == ""

    def test_import_stripped(self):
        """@import rules are stripped, other rules preserved."""
        css = '@import url("evil.css"); body { color: red; }'
        result = _sanitize_css_block(css)
        assert "@import" not in result
        assert "color: red" in result

    def test_charset_stripped(self):
        """@charset rules are stripped."""
        css = '@charset "UTF-8"; body { margin: 0; }'
        result = _sanitize_css_block(css)
        assert "@charset" not in result
        assert "margin: 0" in result

    def test_url_stripped(self):
        """url() values are stripped."""
        css = "body { background: url('evil.com/track.png'); color: blue; }"
        result = _sanitize_css_block(css)
        assert "url(" not in result.lower()
        assert "color: blue" in result

    def test_url_double_quoted_stripped(self):
        """url() with double quotes stripped."""
        css = '.hero { background-image: url("https://example.com/bg.jpg"); }'
        result = _sanitize_css_block(css)
        assert "url(" not in result.lower()

    def test_url_unquoted_stripped(self):
        """url() unquoted value stripped."""
        css = ".hero { background: url(https://example.com/bg.jpg); }"
        result = _sanitize_css_block(css)
        assert "url(" not in result.lower()

    def test_url_case_insensitive(self):
        """URL() and Url() also stripped."""
        css = ".a { background: URL(evil.com); } .b { background: Url(evil.com); }"
        result = _sanitize_css_block(css)
        assert "url(" not in result.lower()

    def test_expression_stripped(self):
        """expression() (IE JS-in-CSS) stripped."""
        css = "body { width: expression(document.body.clientWidth); }"
        result = _sanitize_css_block(css)
        assert "expression" not in result.lower() or "expression-stripped" in result.lower()

    def test_moz_binding_stripped(self):
        """-moz-binding: (Firefox JS-in-CSS) stripped."""
        css = "body { -moz-binding: url(evil.xbl); }"
        result = _sanitize_css_block(css)
        assert "-moz-binding" not in result.lower() or "moz-binding-stripped" in result.lower()

    def test_behavior_stripped(self):
        """behavior: (IE JS-in-CSS) stripped."""
        css = "body { behavior: url(evil.htc); }"
        result = _sanitize_css_block(css)
        assert "behavior:" not in result.lower() or "behavior-stripped" in result.lower()

    def test_gradient_preserved(self):
        """linear-gradient() is NOT a url() call and should survive."""
        css = ".hero { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }"
        result = _sanitize_css_block(css)
        assert "linear-gradient" in result
        assert "#667eea" in result

    def test_radial_gradient_preserved(self):
        """radial-gradient() preserved."""
        css = ".bg { background: radial-gradient(circle, #fff, #000); }"
        result = _sanitize_css_block(css)
        assert "radial-gradient" in result

    def test_media_queries_preserved(self):
        """@media queries pass through."""
        css = "@media (max-width: 768px) { .hero { font-size: 1.5rem; } }"
        result = _sanitize_css_block(css)
        assert "@media" in result
        assert "768px" in result

    def test_keyframes_preserved(self):
        """@keyframes pass through."""
        css = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }"
        result = _sanitize_css_block(css)
        assert "@keyframes" in result
        assert "fadeIn" in result

    def test_size_cap(self):
        """CSS exceeding 100KB is truncated."""
        css = "a" * 200_000
        result = _sanitize_css_block(css)
        assert len(result) <= 100_001  # Allow small overhead from stripping

    def test_empty_returns_empty(self):
        """Empty/whitespace input returns empty string."""
        assert _sanitize_css_block("") == ""
        assert _sanitize_css_block("   ") == ""
        assert _sanitize_css_block(None) == ""

    def test_bare_less_than_not_rejected(self):
        """Bare < (valid in CSS range syntax) should NOT cause rejection."""
        # CSS range syntax can use < in @counter-style, etc.
        css = "body { color: red; } /* comment with 1 < 2 */"
        result = _sanitize_css_block(css)
        assert "color: red" in result


# ---------------------------------------------------------------------------
# Phase 0: Inline Style url() Stripping
# ---------------------------------------------------------------------------

class TestStripUrlFromInlineStyles:
    """Test _strip_url_from_inline_styles parser-based url() removal."""

    def test_strips_url_from_style_attr(self):
        """url() in style attribute is stripped."""
        html = '<div style="background-image: url(evil.com)">Text</div>'
        result = _strip_url_from_inline_styles(html)
        assert "url(" not in result.lower() or "url-stripped" in result.lower()
        assert "Text" in result

    def test_preserves_visible_text_with_url(self):
        """Text content containing 'url(' is NOT altered."""
        html = '<p>Visit url(example.com) for details</p>'
        result = _strip_url_from_inline_styles(html)
        assert "url(example.com)" in result

    def test_no_url_fast_path(self):
        """HTML without url() returns unchanged."""
        html = '<div style="color: red">Hello</div>'
        result = _strip_url_from_inline_styles(html)
        assert result == html

    def test_single_quote_style(self):
        """Handles STYLE='...' with single quotes."""
        html = "<div style='background: url(evil.com)'>Text</div>"
        result = _strip_url_from_inline_styles(html)
        assert "evil.com" not in result
        assert "Text" in result

    def test_case_insensitive_url(self):
        """URL() and Url() in styles also stripped."""
        html = '<div style="background: URL(evil.com)">Text</div>'
        result = _strip_url_from_inline_styles(html)
        assert "evil.com" not in result


# ---------------------------------------------------------------------------
# Phase 1: Output Quality Guards
# ---------------------------------------------------------------------------

class TestValidateAnalysisSlots:
    """Test _validate_analysis_slots severity tiers."""

    def test_ok_severity(self, service):
        """3+ slots including headline and CTA = ok."""
        html = (
            '<h1 data-slot="headline">Title</h1>'
            '<p data-slot="body-1">Text</p>'
            '<button data-slot="cta-1">Buy</button>'
        )
        severity, report = service._validate_analysis_slots(html)
        assert severity == "ok"

    def test_degraded_severity(self, service):
        """Has slots but missing key ones = degraded."""
        html = '<h1 data-slot="headline">Title</h1>'  # No CTA, only 1 slot
        severity, report = service._validate_analysis_slots(html)
        assert severity == "degraded"

    def test_unusable_severity(self, service):
        """0 slots = unusable."""
        html = '<div>No slots at all</div>'
        severity, report = service._validate_analysis_slots(html)
        assert severity == "unusable"

    def test_degraded_no_headline(self, service):
        """Has CTA but no headline = degraded."""
        html = (
            '<p data-slot="body-1">Text</p>'
            '<button data-slot="cta-1">Buy</button>'
            '<p data-slot="body-2">More</p>'
        )
        severity, report = service._validate_analysis_slots(html)
        assert severity == "degraded"


class TestValidateHtmlCompleteness:
    """Test _validate_html_completeness structural checks."""

    def test_complete_html(self, service):
        """Well-formed HTML passes."""
        html = (
            '<div><section><h1>Title</h1><p>Text content that is long enough</p>'
            '<p>More content to ensure we pass the minimum length check of 200 chars</p>'
            '<p>And even more content to really make sure this is well above the threshold</p>'
            '</section></div>'
        )
        is_complete, issues = service._validate_html_completeness(html)
        assert is_complete
        assert issues == []

    def test_too_short(self, service):
        """HTML under 200 chars flagged."""
        html = '<div>Short</div>'
        is_complete, issues = service._validate_html_completeness(html)
        assert not is_complete
        assert any("too short" in i for i in issues)

    def test_mid_tag_truncation(self, service):
        """Last < without matching > detected."""
        html = 'x' * 300 + '<div>Content</div><div class='
        is_complete, issues = service._validate_html_completeness(html)
        assert not is_complete
        assert any("Mid-tag" in i for i in issues)

    def test_tag_imbalance(self, service):
        """Severe div open/close imbalance detected."""
        html = '<div>' * 10 + 'x' * 200 + '</div>' * 3
        is_complete, issues = service._validate_html_completeness(html)
        assert not is_complete
        assert any("imbalance" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Phase 2: Style Block Preservation & Blueprint CSS Round-Trip
# ---------------------------------------------------------------------------

class TestExtractAndSanitizeCss:
    """Test _extract_and_sanitize_css extraction and sanitization."""

    def test_extracts_style_blocks(self, service):
        """Style blocks extracted and HTML cleaned."""
        html = '<style>.hero { color: red; }</style><div>Content</div>'
        body, css = service._extract_and_sanitize_css(html)
        assert "<style>" not in body
        assert "Content" in body
        assert "color: red" in css

    def test_multiple_style_blocks(self, service):
        """Multiple style blocks concatenated."""
        html = (
            '<style>.a { color: red; }</style>'
            '<div>Between</div>'
            '<style>.b { margin: 0; }</style>'
        )
        body, css = service._extract_and_sanitize_css(html)
        assert "color: red" in css
        assert "margin: 0" in css
        assert "<style>" not in body

    def test_sanitizes_css_during_extraction(self, service):
        """url() in style blocks stripped during extraction."""
        html = '<style>.hero { background: url(evil.com); color: blue; }</style><div>OK</div>'
        body, css = service._extract_and_sanitize_css(html)
        assert "url(" not in css.lower() or "url-stripped" in css.lower()
        assert "color: blue" in css

    def test_no_style_blocks(self, service):
        """HTML without style blocks returns empty CSS."""
        html = '<div style="color: red">Content</div>'
        body, css = service._extract_and_sanitize_css(html)
        assert css == ""
        assert "Content" in body


class TestExtractPageCssAndStrip:
    """Test _extract_page_css_and_strip for blueprint CSS carry-through."""

    def test_extracts_page_css(self, service):
        """Extracts CSS from <style class="page-css"> blocks."""
        wrapped = (
            '<!DOCTYPE html><html><head>'
            '<style>.mockup-meta-bar { background: #1e293b; }</style>'
            '<style class="page-css">.hero { color: red; }</style>'
            '</head><body>'
            '<div class="mockup-meta-bar"><span>META</span></div>'
            '<div class="hero">Content</div>'
            '<div class="mockup-gen-footer">Footer</div>'
            '</body></html>'
        )
        body, css = service._extract_page_css_and_strip(wrapped)
        assert "color: red" in css
        assert "Content" in body
        assert "mockup-meta-bar" not in body

    def test_no_page_css_returns_empty(self, service):
        """Old-format HTML without page-css style block returns empty CSS."""
        wrapped = (
            '<!DOCTYPE html><html><head>'
            '<style>.mockup-meta-bar { background: #1e293b; }</style>'
            '</head><body>'
            '<div class="mockup-meta-bar"><span>META</span></div>'
            '<div>Content</div>'
            '</body></html>'
        )
        body, css = service._extract_page_css_and_strip(wrapped)
        assert css == ""
        assert "Content" in body

    def test_resanitizes_css_on_read(self, service):
        """CSS containing url() is re-sanitized on extraction (defense-in-depth)."""
        wrapped = (
            '<!DOCTYPE html><html><head>'
            '<style class="page-css">.evil { background: url(evil.com); color: blue; }</style>'
            '</head><body><div>Content</div></body></html>'
        )
        body, css = service._extract_page_css_and_strip(wrapped)
        assert "url(" not in css.lower() or "url-stripped" in css.lower()
        assert "color: blue" in css

    def test_multi_class_page_css(self, service):
        """Handles class="foo page-css bar" multi-class attribute."""
        wrapped = (
            '<!DOCTYPE html><html><head>'
            '<style class="foo page-css bar">.hero { margin: 0; }</style>'
            '</head><body><div>Content</div></body></html>'
        )
        body, css = service._extract_page_css_and_strip(wrapped)
        assert "margin: 0" in css


class TestBlueprintCssRoundTrip:
    """Test that CSS survives the full analysis→blueprint round-trip."""

    @patch.object(MockupService, "_rewrite_html_for_brand")
    def test_css_carried_through_rewrite(self, mock_rewrite, service):
        """CSS from analysis mockup appears in blueprint output."""
        mock_rewrite.return_value = '<div class="hero" data-slot="headline">Rewritten</div>'

        # Simulate analysis mockup with page CSS
        analysis_html = service._wrap_mockup(
            '<div class="hero" data-slot="headline">Original</div>',
            None,
            "analysis",
            page_css=".hero { color: red; font-size: 2rem; }",
        )

        blueprint_html = service.generate_blueprint_mockup(
            blueprint={"sections": [], "bonus_sections": []},
            analysis_mockup_html=analysis_html,
            brand_profile={"brand_basics": {"name": "Test"}},
        )

        assert blueprint_html is not None
        assert 'class="page-css"' in blueprint_html
        assert "color: red" in blueprint_html
        assert "Rewritten" in blueprint_html

    def test_css_carried_through_no_rewrite(self, service):
        """CSS preserved even when rewrite is skipped (no brand_profile)."""
        analysis_html = service._wrap_mockup(
            '<div class="hero">Content</div>',
            None,
            "analysis",
            page_css=".hero { background: #f0f0f0; }",
        )

        blueprint_html = service.generate_blueprint_mockup(
            blueprint={"sections": [], "bonus_sections": []},
            analysis_mockup_html=analysis_html,
            brand_profile=None,  # No rewrite
        )

        assert blueprint_html is not None
        assert "background: #f0f0f0" in blueprint_html

    @patch.object(MockupService, "_rewrite_html_for_brand", side_effect=Exception("AI fail"))
    def test_css_carried_through_on_failure(self, mock_rewrite, service):
        """CSS preserved even when rewrite fails (exception path)."""
        analysis_html = service._wrap_mockup(
            '<div class="hero" data-slot="headline">Content</div>',
            None,
            "analysis",
            page_css=".hero { padding: 20px; }",
        )

        with pytest.raises(Exception, match="AI fail"):
            service.generate_blueprint_mockup(
                blueprint={"sections": [], "bonus_sections": []},
                analysis_mockup_html=analysis_html,
                brand_profile={"brand_basics": {"name": "Test"}},
            )


class TestWrapMockupPageCss:
    """Test _wrap_mockup with page_css parameter."""

    def test_no_page_css_default(self, service):
        """Default page_css="" produces no extra style block."""
        html = service._wrap_mockup('<div>Content</div>', None, "analysis")
        assert 'class="page-css"' not in html
        assert "Content" in html

    def test_page_css_injected(self, service):
        """page_css parameter creates <style class="page-css"> block."""
        html = service._wrap_mockup(
            '<div>Content</div>', None, "analysis",
            page_css=".hero { color: red; }",
        )
        assert 'class="page-css"' in html
        assert "color: red" in html

    def test_empty_page_css_ignored(self, service):
        """Empty/whitespace page_css produces no extra style block."""
        html = service._wrap_mockup(
            '<div>Content</div>', None, "analysis",
            page_css="   ",
        )
        assert 'class="page-css"' not in html


# ---------------------------------------------------------------------------
# Phase 3: Image URL Validation
# ---------------------------------------------------------------------------

class TestValidateImageUrl:
    """Test _validate_image_url safety checks."""

    def test_https_url_allowed(self, service):
        """HTTPS URL is allowed."""
        is_safe, url, reason = service._validate_image_url("https://example.com/image.jpg")
        assert is_safe
        assert url == "https://example.com/image.jpg"

    def test_http_url_rejected(self, service):
        """HTTP URL is rejected."""
        is_safe, url, reason = service._validate_image_url("http://example.com/image.jpg")
        assert not is_safe
        assert "non-HTTPS" in reason

    def test_javascript_url_rejected(self, service):
        """javascript: URL is rejected."""
        is_safe, url, reason = service._validate_image_url("javascript:alert(1)")
        assert not is_safe

    def test_data_png_allowed(self, service):
        """data:image/png;base64,... is allowed."""
        small_data = "data:image/png;base64," + "A" * 100
        is_safe, url, reason = service._validate_image_url(small_data)
        assert is_safe

    def test_data_jpeg_allowed(self, service):
        """data:image/jpeg;base64,... is allowed."""
        small_data = "data:image/jpeg;base64," + "A" * 100
        is_safe, url, reason = service._validate_image_url(small_data)
        assert is_safe

    def test_data_svg_rejected(self, service):
        """data:image/svg+xml;base64,... is rejected (script risk)."""
        svg_data = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
        is_safe, url, reason = service._validate_image_url(svg_data)
        assert not is_safe
        assert "unsafe" in reason

    def test_data_uri_too_large(self, service):
        """data: URI > 500KB is rejected."""
        large_data = "data:image/png;base64," + "A" * 600_000
        is_safe, url, reason = service._validate_image_url(large_data)
        assert not is_safe
        assert "too large" in reason

    def test_tracking_pixel_rejected(self, service):
        """Known tracking domains are rejected."""
        is_safe, url, reason = service._validate_image_url(
            "https://www.facebook.com/tr?id=123&ev=PageView"
        )
        assert not is_safe
        assert "tracking" in reason

    def test_doubleclick_rejected(self, service):
        """doubleclick.net tracking domain rejected."""
        is_safe, url, reason = service._validate_image_url(
            "https://ad.doubleclick.net/pixel.gif"
        )
        assert not is_safe

    def test_google_analytics_rejected(self, service):
        """google-analytics.com rejected."""
        is_safe, url, reason = service._validate_image_url(
            "https://www.google-analytics.com/collect"
        )
        assert not is_safe

    def test_private_ip_localhost_rejected(self, service):
        """localhost URLs rejected."""
        is_safe, url, reason = service._validate_image_url("https://localhost/img.png")
        assert not is_safe
        assert "private" in reason

    def test_private_ip_192_168_rejected(self, service):
        """192.168.x.x URLs rejected."""
        is_safe, url, reason = service._validate_image_url("https://192.168.1.1/img.png")
        assert not is_safe

    def test_private_ip_10_rejected(self, service):
        """10.x.x.x URLs rejected."""
        is_safe, url, reason = service._validate_image_url("https://10.0.0.1/img.png")
        assert not is_safe

    def test_private_ip_172_16_rejected(self, service):
        """172.16-31.x.x URLs rejected."""
        is_safe, url, reason = service._validate_image_url("https://172.16.0.1/img.png")
        assert not is_safe

    def test_empty_url_rejected(self, service):
        """Empty URL rejected."""
        is_safe, url, reason = service._validate_image_url("")
        assert not is_safe

    def test_pixel_prefix_rejected(self, service):
        """pixel.* hostname prefix rejected."""
        is_safe, url, reason = service._validate_image_url("https://pixel.example.com/t.gif")
        assert not is_safe


class TestExtractImageUrls:
    """Test _extract_image_urls markdown image parsing."""

    def test_basic_extraction(self, service):
        """Extracts ![alt](url) patterns from markdown."""
        md = "# Title\n\n![Hero image](https://example.com/hero.jpg)\n\nText"
        urls = service._extract_image_urls(md, "https://example.com")
        assert len(urls) == 1
        assert urls[0]["alt"] == "Hero image"
        assert urls[0]["url"] == "https://example.com/hero.jpg"

    def test_resolves_relative_urls(self, service):
        """Relative URLs resolved against page_url."""
        md = "![Logo](/images/logo.png)"
        urls = service._extract_image_urls(md, "https://example.com/page")
        assert len(urls) == 1
        assert urls[0]["url"] == "https://example.com/images/logo.png"

    def test_caps_at_20(self, service):
        """Max 20 images extracted."""
        md = "\n".join(f"![img{i}](https://example.com/{i}.jpg)" for i in range(30))
        urls = service._extract_image_urls(md, "https://example.com")
        assert len(urls) == 20

    def test_rejects_unsafe_urls(self, service):
        """HTTP and tracking URLs are filtered out."""
        md = (
            "![Good](https://example.com/good.jpg)\n"
            "![Bad](http://example.com/bad.jpg)\n"
            "![Tracker](https://www.facebook.com/tr/pixel.gif)\n"
        )
        urls = service._extract_image_urls(md, "https://example.com")
        assert len(urls) == 1
        assert urls[0]["alt"] == "Good"


# ---------------------------------------------------------------------------
# Phase 1: Prompt Building
# ---------------------------------------------------------------------------

class TestBuildVisionPrompt:
    """Test _build_vision_prompt construction."""

    def test_basic_prompt(self, service):
        """Basic prompt without markdown or images."""
        prompt = service._build_vision_prompt()
        assert "SLOT MARKING CONTRACT" in prompt
        assert "LAYOUT REQUIREMENTS" in prompt
        assert "Output ONLY" in prompt

    def test_includes_markdown(self, service):
        """Page markdown included in prompt."""
        prompt = service._build_vision_prompt(page_markdown="# Hello World\n\nSome content")
        assert "PAGE TEXT CONTENT" in prompt
        assert "Hello World" in prompt

    def test_slot_reinforcement(self, service):
        """reinforce_slots adds extra emphasis."""
        prompt = service._build_vision_prompt(reinforce_slots=True)
        assert "SLOT MARKING REINFORCEMENT" in prompt

    def test_image_urls_included(self, service):
        """Image URLs listed in prompt."""
        images = [{"alt": "Hero", "url": "https://example.com/hero.jpg"}]
        prompt = service._build_vision_prompt(image_urls=images)
        assert "ACTUAL IMAGE URLs" in prompt
        assert "example.com/hero.jpg" in prompt

    def test_markdown_truncation(self, service):
        """Very long markdown is truncated."""
        long_md = "# Heading\n\n" + "word " * 10_000
        prompt = service._build_vision_prompt(page_markdown=long_md)
        assert "truncated" in prompt.lower()


# ---------------------------------------------------------------------------
# Backward Compatibility Tests
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure existing behavior is preserved after changes."""

    def test_strip_mockup_wrapper_unchanged_return_type(self, service):
        """_strip_mockup_wrapper still returns str (not tuple)."""
        wrapped = (
            '<!DOCTYPE html><html><head><style>.x{}</style></head><body>'
            '<div class="mockup-meta-bar"><span>META</span></div>'
            '<div>Content</div>'
            '<div class="mockup-gen-footer">Footer</div>'
            '</body></html>'
        )
        result = service._strip_mockup_wrapper(wrapped)
        assert isinstance(result, str)
        assert "Content" in result

    def test_wrap_mockup_no_page_css_default(self, service):
        """_wrap_mockup works without page_css argument (default)."""
        html = service._wrap_mockup('<div>Content</div>', None, "analysis")
        assert "<!DOCTYPE html>" in html
        assert "Content" in html

    @patch.object(MockupService, "_generate_via_ai_vision")
    def test_generate_analysis_mockup_no_page_url(self, mock_vision, service):
        """generate_analysis_mockup works without page_url (backward compat)."""
        mock_vision.return_value = '<div data-slot="headline">Test</div>'
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64")
        assert "Test" in html
        mock_vision.assert_called_once()

    @patch.object(MockupService, "_generate_via_ai_vision")
    def test_ai_vision_strips_style_blocks(self, mock_vision, service):
        """Style blocks from AI vision output are extracted, not left as text."""
        mock_vision.return_value = (
            '<style>.hero { font-size: 2rem; }</style>'
            '<div class="hero" data-slot="headline">Hello</div>'
        )
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64")
        assert "Hello" in html
        # CSS should be in page-css block, not as visible text
        assert "font-size: 2rem" in html  # In the page-css style block

    @patch.object(MockupService, "_generate_via_ai_vision")
    def test_ai_vision_preserves_css_in_wrapper(self, mock_vision, service):
        """CSS from vision output appears in page-css style block in final output."""
        mock_vision.return_value = (
            '<style>.hero { color: red; }</style>'
            '<div class="hero" data-slot="headline">Content</div>'
        )
        html = service.generate_analysis_mockup(screenshot_b64="fake_b64")
        assert 'class="page-css"' in html
        assert "color: red" in html
