# Brand & Product Onboarding Checklist

This checklist covers all data needed to onboard a new brand and product into ViralTracker for AI-powered ad generation.

---

## Overview

Onboarding follows a **3-step process** with optional automated research:

**Phase 0: Brand Research (Optional but Recommended)**
> Scrape the brand's existing Facebook ads, analyze with AI, and auto-extract benefits, USPs, hooks, and brand voice. This dramatically speeds up manual data gathering.

1. **Setup Brand & Product** - Create database records with brand/product info
2. **Upload Images** - Upload product images to Supabase storage
3. **Insert Hooks** - Add persuasive hooks for ad generation

---

## Phase 0: Brand Research (Optional)

Use this phase to automatically extract brand insights from existing Facebook ads. This helps populate benefits, USPs, hooks, and brand voice automatically.

### Option A: Use Streamlit UI

1. Navigate to **Template Queue** page in the Streamlit app
2. Go to the **Ingest New** tab
3. Paste a Facebook Ad Library URL for the brand
4. Set max ads (recommended: 20-50)
5. Click "Start Ingestion"
6. Review scraped templates in the **Pending Review** tab
7. Approve useful templates for your template library

### Option B: Use Python Script

```python
import asyncio
from viraltracker.pipelines import run_brand_onboarding

async def research_brand():
    result = await run_brand_onboarding(
        ad_library_url="https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&view_all_page_id=YOUR_PAGE_ID",
        max_ads=30,
        analyze_videos=True
    )

    if result["status"] == "success":
        # Use extracted data to populate product fields
        product_data = result["product_data"]
        print(f"Benefits: {product_data['benefits']}")
        print(f"USPs: {product_data['unique_selling_points']}")
        print(f"Target Audience: {product_data['target_audience']}")
        print(f"Brand Voice: {product_data['brand_voice_notes']}")
        print(f"Hooks: {product_data['hooks']}")

asyncio.run(research_brand())
```

### Getting Facebook Ad Library URLs

1. Go to [Facebook Ad Library](https://www.facebook.com/ads/library)
2. Search for the brand name
3. Filter by country (e.g., US)
4. Copy the full URL from your browser

**Example URL:**
```
https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&is_targeted_country=false&media_type=all&search_type=page&view_all_page_id=470900729771745
```

### What Gets Extracted

| Data Type | Description |
|-----------|-------------|
| **Benefits** | Product benefits mentioned in ads |
| **USPs** | Unique selling propositions |
| **Hooks** | Attention-grabbing opening lines |
| **Persona Signals** | Target audience characteristics |
| **Brand Voice** | Tone, style, and personality |
| **Visual Styles** | Common ad formats and layouts |

---

## Phase 1: Gather Brand Information

### Required Brand Data

| Field | Description | Example (Savage) |
|-------|-------------|------------------|
| **name** | Official brand name | "Savage Supplements" |
| **slug** | URL-friendly identifier | "savage-supplements" |
| **brand_code** | 2-4 char code for ad filenames | "SV" |
| **description** | Brand overview with archetype, persona, values | See below |
| **website** | Brand website URL | "https://fuelthesavage.com" |

### Brand Colors (JSONB)

```json
{
  "primary": "#1C1B1C",
  "primary_name": "Gun Metal Black",
  "secondary": "#DC3436",
  "secondary_name": "Blood Red",
  "background": "#DEC3A0",
  "background_name": "Sand",
  "all": ["#1C1B1C", "#DC3436", "#DEC3A0", "#533E2D"],
  "usage_notes": "Primary colors for main elements, secondary for accents..."
}
```

**Collect:**
- [ ] Primary color (hex + name)
- [ ] Secondary color (hex + name)
- [ ] Background color (hex + name)
- [ ] Additional palette colors
- [ ] Usage notes from brand guidelines

### Brand Fonts (JSONB)

```json
{
  "primary": "EDO SZ",
  "primary_weights": ["Regular"],
  "primary_usage": "Headers, Subheaders, Callout Text",
  "secondary": "Averia Serif",
  "secondary_weights": ["Light", "Regular", "Bold", "Italic"],
  "secondary_usage": "Headers, SubHeaders, Paragraph Text",
  "style_notes": "Bold font for impact, serif for readability"
}
```

**Collect:**
- [ ] Primary font name and weights
- [ ] Primary font usage guidelines
- [ ] Secondary font name and weights
- [ ] Secondary font usage guidelines
- [ ] Style notes

### Brand Guidelines (TEXT)

Describe the brand personality, archetype, voice:
- [ ] Brand archetype (e.g., The Outlaw, The Hero, The Caregiver)
- [ ] Brand persona description
- [ ] Core values
- [ ] Personality traits (masculine, friendly, bold, etc.)
- [ ] Tagline/positioning statement

---

## Phase 2: Gather Product Information

### Required Product Data

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| **name** | text | Product name | "Savage" |
| **slug** | text | URL-friendly identifier | "savage" |
| **product_code** | varchar(4) | Code for ad filenames | "SV" |
| **description** | text | Full product description | "SAVAGE - Primal Fuel For Men..." |
| **product_url** | text | Product page URL | "https://fuelthesavage.com" |
| **product_dimensions** | text | Physical size if applicable | "239mm x 140mm x 10mm (pouch)" |

### Target Audience (TEXT)

Include both demographics and psychographics:

```
DEMOGRAPHICS:
- Ages: 28-45
- Gender: Men
- Income: $80k - $100k
- Education: High-School, College, Trades
- Location: U.S.A & Canada

PSYCHOGRAPHICS:
- Values traditional values
- Skeptical of mainstream media
- Self-reliant and pragmatic
- Appreciates straight talk
```

**Collect:**
- [ ] Age range
- [ ] Gender breakdown
- [ ] Income level
- [ ] Education level
- [ ] Geographic focus
- [ ] Key psychographic traits

### Benefits (TEXT[])

Array of product benefits:

```python
benefits = [
    "Optimized B12 Status - Supporting energy metabolism",
    "Improved Iron Markers - Enhanced oxygen transport",
    "Athletic Performance - Protein synthesis support",
    "Only 3 capsules vs 6+ for competitors"
]
```

**Collect:**
- [ ] 5-10 key benefits with descriptions

### Unique Selling Points (TEXT[])

Array of differentiators:

```python
unique_selling_points = [
    "The Only Organ Supplement That Isn't Beef Jerky Dust",
    "THE SAVAGE FREEZE PROTOCOL™ - Flash-frozen at -40°F",
    "Complete 6-organ system targeting male hormonal optimization"
]
```

**Collect:**
- [ ] 3-6 unique selling points

### Key Ingredients/Features (TEXT[])

```python
key_ingredients = [
    "Freeze-Dried Bovine Liver - Vitamin B12, A, folate powerhouse",
    "Bovine Heart - 110μg/g CoQ10 for cellular energy",
    "Bovine Kidney - Source of DAO and detox support"
]
```

**Collect:**
- [ ] All key ingredients/features with benefits

### Brand Voice Notes (TEXT)

```
THE OUTLAW ARCHETYPE - Bold, Defiant, Raw, Unapologetically authentic.

VOICE CHARACTERISTICS:
- Direct and confrontational, never soft
- Challenges mainstream health narratives
- Uses powerful, action-oriented language
- No fluff, no corporate speak

TONE: Masculine, Irreverent, Provocative, Confident

TAGLINE: "Because Testosterone is a Feature Not a Flaw"
```

**Collect:**
- [ ] Voice archetype
- [ ] Key voice characteristics
- [ ] Tone descriptors
- [ ] Tagline

### Context Prompt (TEXT)

Full AI context for ad generation - the most important field for AI understanding:

**Include:**
- [ ] Unique mechanism explanation
- [ ] The "brutal truth" / problem statement
- [ ] Process/protocol stages
- [ ] Comparison to competitors
- [ ] Scientific validation (key studies)
- [ ] Key messaging points

### Social Proof Fields

| Field | Type | Description |
|-------|------|-------------|
| **current_offer** | text | Active promotional offer |
| **founders** | text | Founder names for testimonials |
| **review_platforms** | jsonb | `{"trustpilot": {"rating": 4.5, "count": 1200}}` |
| **media_features** | jsonb | `["Forbes", "Today Show"]` |
| **awards_certifications** | jsonb | `["#1 Best Seller", "Vet Recommended"]` |

**Collect:**
- [ ] Current offer/discount
- [ ] Founder names
- [ ] Review platform ratings and counts
- [ ] Media features list
- [ ] Awards and certifications

### Compliance Fields

| Field | Type | Description |
|-------|------|-------------|
| **prohibited_claims** | text[] | Claims that MUST NOT appear in ads |
| **required_disclaimers** | text | Legal disclaimers required |

**Collect:**
- [ ] List of prohibited claims (cure, FDA approved, etc.)
- [ ] Required disclaimer text

---

## Phase 3: Gather Product Images

### Image Requirements

| Image Type | Required? | Notes |
|------------|-----------|-------|
| **Package Front** | Yes (main) | Primary product shot |
| **Package Back** | Recommended | Supplement facts, details |
| **Logo (Black)** | Yes | For dark backgrounds |
| **Logo (White)** | Yes | For light backgrounds |
| **Logo (Color)** | Optional | Full color version |
| **Logo with Tagline** | Optional | Logo + brand tagline |
| **Wordmark** | Optional | Text-only version |
| **Lifestyle Images** | Optional | Product in use |

### Image Metadata

For each image, collect:
- [ ] Display name (e.g., "Package Front")
- [ ] Whether it's the main image (is_main)
- [ ] Sort order (1 = first)
- [ ] Description/notes

### Image Upload Format

```python
IMAGE_FILES = [
    ("path/to/image.jpg", "Display Name", True, 1, "Description/notes"),
    # (filepath, display_name, is_main, sort_order, notes)
]
```

---

## Phase 4: Create Hooks

### Hook Categories

| Category | Description | Example |
|----------|-------------|---------|
| `competitive_comparison` | Why you're better than alternatives | "Every other organ supplement is beef jerky dust..." |
| `skepticism_overcome` | Address doubts and objections | "I was skeptical too. Another supplement?..." |
| `transformation` | Before/after stories | "Week 1: More energy. Week 4: Better recovery..." |
| `raw_honesty` | Authentic, direct messaging | "No fluff. No fillers. No corporate BS..." |
| `product_superiority` | Features and quality | "6 organs working together. That's a system." |
| `third_party_validation` | Studies, testimonials, certs | "47% more muscle protein synthesis... (Church 2024)" |
| `failed_alternatives` | What they tried before | "I tried testosterone clinics. I tried Amazon..." |
| `problem_solved` | Pain points addressed | "Low energy at 35 isn't normal..." |
| `discovery` | Revelation or insight hooks | "The secret isn't what's in the capsule..." |
| `fear_trigger` | Consequences of inaction | "Your testosterone drops 1% every year after 30..." |
| `proactive_win` | Taking control narrative | "I'm not waiting to feel old..." |
| `product_feature` | Specific ingredient callouts | "Bovine testicle contains the complete enzyme cascade..." |

### Hook Format

```python
HOOKS = [
    (
        "Hook text that grabs attention...",
        "category",           # e.g., competitive_comparison
        "Framework Name",     # e.g., Unique Mechanism
        18,                   # impact_score (1-21)
        "High"               # emotional_score: Low, Medium, High, Very High
    ),
]
```

**Create:**
- [ ] 5+ competitive_comparison hooks
- [ ] 3+ skepticism_overcome hooks
- [ ] 3+ transformation hooks
- [ ] 3+ raw_honesty hooks
- [ ] 3+ product_superiority hooks
- [ ] 3+ third_party_validation hooks
- [ ] 2+ failed_alternatives hooks
- [ ] 2+ problem_solved hooks
- [ ] 2+ discovery hooks
- [ ] 2+ fear_trigger hooks
- [ ] 2+ proactive_win hooks
- [ ] 2+ product_feature hooks

**Target: 30-40 hooks total**

---

## Phase 5: Run Setup Scripts

### Step 1: Create Setup Script

Copy `setup_savage_product.py` as template:
```bash
cp product_setup/setup_savage_product.py product_setup/setup_NEWBRAND_product.py
```

Update with collected brand/product data.

### Step 2: Create Image Upload Script

Copy `upload_savage_images.py` as template:
```bash
cp product_setup/upload_savage_images.py product_setup/upload_NEWBRAND_images.py
```

Update with:
- Product ID from Step 1
- Image file list

### Step 3: Create Hooks Script

Copy `insert_savage_hooks.py` as template:
```bash
cp product_setup/insert_savage_hooks.py product_setup/insert_NEWBRAND_hooks.py
```

Update with:
- Product ID from Step 1
- Hooks data

### Step 4: Run Scripts in Order

```bash
# 1. Create brand, product, project
python product_setup/setup_NEWBRAND_product.py

# 2. Upload product images
python product_setup/upload_NEWBRAND_images.py

# 3. Insert hooks
python product_setup/insert_NEWBRAND_hooks.py
```

---

## Phase 6: Verification

### Database Verification

- [ ] Brand appears in Brand Manager UI
- [ ] Brand has correct colors/fonts
- [ ] Product linked to brand
- [ ] Product has all fields populated
- [ ] Product images visible and properly ordered
- [ ] Main image correctly marked
- [ ] Hooks count matches expected
- [ ] Hooks have diverse categories

### Functional Verification

- [ ] Product selectable in Ad Creator
- [ ] Product images load correctly
- [ ] Hooks retrieved for ad generation
- [ ] Test ad generation with new product
- [ ] Generated ads use correct branding

---

## Assets Folder Structure

Organize brand assets in `product_setup/`:

```
product_setup/
├── BRAND_NAME/
│   ├── brand_guide.pdf        # Original brand guidelines
│   ├── product_front.jpg      # Main product image
│   ├── product_back.jpg       # Back of product
│   ├── logo_black.png         # Logo variants
│   ├── logo_white.png
│   ├── logo_color.png
│   ├── wordmark.png
│   └── evidence_canvas.html   # Research/claims doc (optional)
├── setup_BRAND_product.py
├── upload_BRAND_images.py
└── insert_BRAND_hooks.py
```

---

## Quick Reference: Database Schema

### brands table
```sql
id, name, slug, brand_code, description, website,
brand_colors (jsonb), brand_fonts (jsonb), brand_guidelines (text),
created_at, updated_at
```

### products table
```sql
id, brand_id, name, slug, product_code, description,
target_audience, product_url, product_dimensions,
benefits (text[]), unique_selling_points (text[]), key_ingredients (text[]),
brand_name, brand_voice_notes, context_prompt,
current_offer, founders, review_platforms (jsonb),
media_features (jsonb), awards_certifications (jsonb),
prohibited_claims (text[]), required_disclaimers,
is_active, created_at, updated_at
```

### product_images table
```sql
id, product_id, storage_path, filename,
is_main, sort_order, notes,
image_analysis (jsonb), analyzed_at, analysis_model,
created_at, updated_at
```

### hooks table
```sql
id, product_id, text, category, framework,
impact_score (0-21), emotional_score (Low/Medium/High/Very High),
active, created_at, updated_at
```
