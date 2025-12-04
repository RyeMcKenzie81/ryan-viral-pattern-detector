"""
Brand & Product Data Collection Template

Copy this file and fill in all fields for your new brand/product.
Then use this data to populate the setup scripts.

Usage:
    1. Copy this file: cp brand_data_template.py my_brand_data.py
    2. Fill in all fields below
    3. Run setup scripts using this data
"""

# ============================================================================
# BRAND DATA
# ============================================================================

BRAND = {
    # Required fields
    "name": "",                          # e.g., "Savage Supplements"
    "slug": "",                          # e.g., "savage-supplements" (URL-friendly)
    "brand_code": "",                    # e.g., "SV" (2-4 chars for ad filenames)
    "website": "",                       # e.g., "https://fuelthesavage.com"

    # Description (include archetype, persona, values)
    "description": """
    [Brand archetype and positioning]

    ARCHETYPE: [e.g., THE OUTLAW, THE HERO, THE CAREGIVER]

    BRAND PERSONA:
    [Detailed description of brand personality and voice]

    CORE VALUES: [e.g., Freedom, rebellion, authenticity]

    PERSONALITY: [e.g., Masculine, Defiant, Bold, Authentic]
    """,

    # Brand colors
    "brand_colors": {
        "primary": "",                   # e.g., "#1C1B1C"
        "primary_name": "",              # e.g., "Gun Metal Black"
        "secondary": "",                 # e.g., "#DC3436"
        "secondary_name": "",            # e.g., "Blood Red"
        "background": "",                # e.g., "#DEC3A0"
        "background_name": "",           # e.g., "Sand"
        "all": [],                       # e.g., ["#1C1B1C", "#DC3436", "#DEC3A0"]
        "usage_notes": ""                # How to use the colors
    },

    # Brand fonts
    "brand_fonts": {
        "primary": "",                   # e.g., "EDO SZ"
        "primary_weights": [],           # e.g., ["Regular", "Bold"]
        "primary_usage": "",             # e.g., "Headers, Callout Text"
        "secondary": "",                 # e.g., "Averia Serif"
        "secondary_weights": [],         # e.g., ["Light", "Regular", "Bold"]
        "secondary_usage": "",           # e.g., "Body copy, Paragraph Text"
        "style_notes": ""                # Additional style notes
    },

    # Additional brand guidelines
    "brand_guidelines": ""               # Additional voice/style notes
}

# ============================================================================
# PRODUCT DATA
# ============================================================================

PRODUCT = {
    # Required fields
    "name": "",                          # e.g., "Savage"
    "slug": "",                          # e.g., "savage" (URL-friendly)
    "product_code": "",                  # e.g., "SV" (2-4 chars for ad filenames)
    "description": "",                   # Full product description
    "product_url": "",                   # e.g., "https://fuelthesavage.com"
    "product_dimensions": "",            # e.g., "239mm x 140mm x 10mm (pouch)"

    # Target audience
    "target_audience": """
    DEMOGRAPHICS:
    - Ages:
    - Gender:
    - Income:
    - Education:
    - Location:

    PSYCHOGRAPHICS:
    - [Key trait 1]
    - [Key trait 2]
    - [Key trait 3]
    """,

    # Product benefits (array)
    "benefits": [
        # "Benefit 1 - Brief description",
        # "Benefit 2 - Brief description",
    ],

    # Unique selling points (array)
    "unique_selling_points": [
        # "USP 1",
        # "USP 2",
    ],

    # Key ingredients or features (array)
    "key_ingredients": [
        # "Ingredient 1 - What it does",
        # "Ingredient 2 - What it does",
    ],

    # Brand name (for display in ads)
    "brand_name": "",                    # e.g., "Savage"

    # Brand voice notes
    "brand_voice_notes": """
    [ARCHETYPE] - [Key traits]

    VOICE CHARACTERISTICS:
    - [Characteristic 1]
    - [Characteristic 2]

    TONE: [Tone descriptors]

    TAGLINE: "[Your tagline]"
    """,

    # Full AI context prompt (CRITICAL for good ad generation)
    "context_prompt": """
    UNIQUE MECHANISM: [Name of your unique approach]

    THE PROBLEM:
    [What problem does this product solve? What are competitors doing wrong?]

    THE SOLUTION:
    [How does your product solve it differently?]

    KEY STAGES/PROCESS:
    STAGE 1: [Description]
    STAGE 2: [Description]
    STAGE 3: [Description]

    COMPARISON:
    THEIR APPROACH: [What competitors do]
    OUR APPROACH: [What you do differently]

    THE BOTTOM LINE:
    [Summary of key differentiator]

    SCIENTIFIC VALIDATION:
    - [Study 1: Citation and finding]
    - [Study 2: Citation and finding]
    """,

    # Social proof
    "current_offer": None,               # e.g., "Up to 35% off subscription"
    "founders": "",                      # e.g., "John and Jane Smith"
    "review_platforms": {
        # "trustpilot": {"rating": 4.5, "count": 1200},
        # "amazon": {"rating": 4.3, "count": 500}
    },
    "media_features": [
        # "Forbes", "Today Show", "Good Morning America"
    ],
    "awards_certifications": [
        # "#1 Best Seller", "Vet Recommended"
    ],

    # Compliance
    "prohibited_claims": [
        # "cure", "FDA approved", "treat disease"
    ],
    "required_disclaimers": "",          # FDA disclaimer text

    "is_active": True
}

# ============================================================================
# PRODUCT IMAGES
# ============================================================================

# Product ID will be set after running setup script
PRODUCT_ID = ""  # Fill in after running setup_product.py

# Images to upload
# Format: (filepath, display_name, is_main, sort_order, notes)
IMAGES = [
    # ("path/to/product_front.jpg", "Package Front", True, 1, "Main product shot"),
    # ("path/to/product_back.jpg", "Package Back", False, 2, "Supplement facts visible"),
    # ("path/to/logo_black.png", "Logo Black", False, 10, "Logo for dark backgrounds"),
    # ("path/to/logo_white.png", "Logo White", False, 11, "Logo for light backgrounds"),
]

# ============================================================================
# HOOKS
# ============================================================================

# Hook categories:
# - competitive_comparison: Why you're better than alternatives
# - skepticism_overcome: Address doubts and objections
# - transformation: Before/after stories
# - raw_honesty: Authentic, direct messaging
# - product_superiority: Features and quality
# - third_party_validation: Studies, testimonials, certifications
# - failed_alternatives: What they tried before
# - problem_solved: Pain points addressed
# - discovery: Revelation or insight hooks
# - fear_trigger: Consequences of inaction
# - proactive_win: Taking control narrative
# - product_feature: Specific ingredient/feature callouts

# Emotional scores: "Low", "Medium", "High", "Very High"
# Impact scores: 1-21

# Format: (text, category, framework, impact_score, emotional_score)
HOOKS = [
    # COMPETITIVE COMPARISON
    # (
    #     "Hook text...",
    #     "competitive_comparison",
    #     "Framework Name",
    #     18,
    #     "High"
    # ),

    # SKEPTICISM OVERCOME
    # (
    #     "Hook text...",
    #     "skepticism_overcome",
    #     "Framework Name",
    #     17,
    #     "High"
    # ),

    # TRANSFORMATION
    # (
    #     "Hook text...",
    #     "transformation",
    #     "Framework Name",
    #     17,
    #     "High"
    # ),

    # Add more hooks for each category...
]

# ============================================================================
# PROJECT DATA (Optional)
# ============================================================================

PROJECT = {
    "name": "",                          # e.g., "Savage Ads"
    "slug": "",                          # e.g., "savage-ads"
    "description": ""                    # e.g., "Ad creation project for Savage"
}
