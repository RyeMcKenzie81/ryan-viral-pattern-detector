# Product Setup Guide

This folder contains template scripts for adding new products to ViralTracker. Use these as a starting point when onboarding a new brand/product.

## Documentation

| Document | Purpose |
|----------|---------|
| [ONBOARDING_CHECKLIST.md](ONBOARDING_CHECKLIST.md) | Complete checklist with all data requirements |
| [templates/brand_data_template.py](templates/brand_data_template.py) | Data collection template (copy and fill in) |

## Quick Start

1. **Review the [Onboarding Checklist](ONBOARDING_CHECKLIST.md)** to understand all required data
2. **Copy [brand_data_template.py](templates/brand_data_template.py)** and fill in your brand/product info
3. **Copy and rename the scripts** for your new product
4. **Run in order**: setup → upload images → insert hooks

## Scripts Overview

| Script | Purpose | Run Order |
|--------|---------|-----------|
| `setup_savage_product.py` | Create brand, product, and project in database | 1st |
| `upload_savage_images.py` | Upload product images to Supabase storage | 2nd |
| `insert_savage_hooks.py` | Add persuasive hooks for ad generation | 3rd |

## Step-by-Step Instructions

### Step 1: Setup Product (`setup_savage_product.py`)

This script creates the brand, product, and project records in the database.

**What to customize:**

```python
# Brand data
brand_data = {
    "name": "Your Brand Name",
    "slug": "your-brand-slug",
    "description": "Brand description with archetype, persona, values...",
    "website": "https://yourbrand.com",
    "brand_colors": {
        "primary": "#HEX",
        "secondary": "#HEX",
        # ...
    },
    "brand_fonts": {
        "primary": "Font Name",
        # ...
    }
}

# Product data
product_data = {
    "name": "Product Name",
    "slug": "product-slug",
    "description": "Product description...",
    "target_audience": "Demographics and psychographics...",
    "product_url": "https://yourbrand.com/product",
    "product_dimensions": "Physical dimensions if applicable",
    "benefits": ["Benefit 1", "Benefit 2", ...],
    "unique_selling_points": ["USP 1", "USP 2", ...],
    "key_ingredients": ["Ingredient 1", ...],  # or features
    "brand_name": "Brand Name",
    "brand_voice_notes": "Voice and tone guidelines...",
    "context_prompt": "Detailed AI context for ad generation..."
}
```

**Run:**
```bash
python product_setup/setup_savage_product.py
```

**Output:** Brand ID, Product ID, Project ID

---

### Step 2: Upload Images (`upload_savage_images.py`)

Uploads product images to Supabase storage and creates `product_images` records.

**What to customize:**

```python
# Update the product ID from Step 1
PRODUCT_ID = "your-product-uuid-here"

# List your images
IMAGE_FILES = [
    ("path/to/image.jpg", "Display Name", True, 1, "Description/notes"),
    # (filepath, display_name, is_main, sort_order, notes)
]
```

**Prepare your images:**
- Place product images in a subfolder (e.g., `product_setup/your_product/`)
- Include: product shots, packaging, logos, lifestyle images
- Mark one as `is_main=True` for the primary product image

**Run:**
```bash
python product_setup/upload_savage_images.py
```

---

### Step 3: Insert Hooks (`insert_savage_hooks.py`)

Adds persuasive hooks that the ad generator uses to create compelling copy.

**What to customize:**

```python
# Update the product ID from Step 1
PRODUCT_ID = "your-product-uuid-here"

# Create hooks tailored to your product
HOOKS = [
    (
        "Hook text that grabs attention...",
        "category",           # e.g., competitive_comparison, transformation
        "Framework Name",     # e.g., Unique Mechanism, Before/After
        18,                   # impact_score (1-21)
        "High"               # emotional_score: Low, Medium, High, Very High
    ),
    # ... more hooks
]
```

**Hook Categories:**
- `competitive_comparison` - Why you're better than alternatives
- `skepticism_overcome` - Address doubts and objections
- `transformation` - Before/after stories
- `raw_honesty` - Authentic, direct messaging
- `product_superiority` - Features and quality
- `third_party_validation` - Studies, testimonials, certifications
- `failed_alternatives` - What they tried before
- `problem_solved` - Pain points addressed
- `discovery` - Revelation or insight hooks
- `fear_trigger` - Consequences of inaction
- `proactive_win` - Taking control narrative
- `product_feature` - Specific ingredient/feature callouts

**Run:**
```bash
python product_setup/insert_savage_hooks.py
```

---

## Example: Savage Product

The `savage/` folder contains example images for the Savage beef organ supplement:
- `savagefront.jpeg` - Package front (main image)
- `WhatsApp Image...` - Package back and combo shots
- `SAVAGE_Logo-*.png` - Various logo treatments

---

## Environment Requirements

Ensure these environment variables are set:
```bash
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_service_key
```

---

## After Setup

Once all three scripts have run:
1. Verify in **Brand Manager UI** that product appears correctly
2. Check **product images** are visible and properly ordered
3. Review **hooks** in the database
4. Test **ad generation** with the new product
5. Optionally set up **scheduled jobs** in Ad Scheduler
