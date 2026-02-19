"""
Tests for MockupService — mapping coverage, normalization, and rendering.
"""

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

        html = service.generate_analysis_mockup(elements, classification)

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
        html = service.generate_analysis_mockup(elements, {})

        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<style>" in html
        # No external CSS dependencies (except optional Google Fonts)
        assert "bootstrap" not in html.lower()
