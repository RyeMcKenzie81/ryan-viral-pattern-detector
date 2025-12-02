"""
Setup Savage product in ViralTracker database.

Brand: Savage Supplements
Product: Savage (Beef organ stack supplement for men)
Website: https://fuelthesavage.com
Tagline: "Because Testosterone is a Feature Not a Flaw"
Archetype: The Outlaw
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

db = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# 1. Create Brand
# ============================================

brand_data = {
    "name": "Savage Supplements",
    "slug": "savage-supplements",
    "description": """Men's health supplements focused on testosterone and vitality.

ARCHETYPE: THE OUTLAW - Bold, defiant, raw, anti-establishment, unapologetically authentic.

BRAND PERSONA:
We're not here to play nice with modern health trends. SAVAGE was built for those who see through the lies of a weakened, over-processed, gender-neutral world. We believe men and women are biologically different—and that's something to be harnessed, not hidden. Our beef organ fuel is rooted in ancestral wisdom and designed to reignite real strength, hormone balance, and primal vitality.

No fluff. No fillers. Just raw power for those who refuse to bow down.

CORE VALUES: Freedom, rebellion, breaking the rules. Liberation from the fake, weak, or oppressive.
PERSONALITY: Masculine, Defiant, Unapologetic, Fearless, Bold, Authentic, Provocative, Confident, Direct""",
    "website": "https://fuelthesavage.com",
    "brand_colors": {
        "primary": "#1C1B1C",
        "primary_name": "Gun Metal Black",
        "secondary": "#DC3436",
        "secondary_name": "Blood Red",
        "background": "#DEC3A0",
        "background_name": "Sand",
        "all": ["#1C1B1C", "#DC3436", "#DEC3A0", "#533E2D"],
        "usage_notes": "Primary 'War Paint' colors: Gun Metal Black + Blood Red. Secondary 'Ritual Ink' colors: Sand + Mud (#533E2D). Use brush stroke textures for raw, primal feel."
    },
    "brand_fonts": {
        "primary": "EDO SZ",
        "primary_weights": ["Regular"],
        "primary_usage": "Headers, Subheaders, Callout Text - rough, bold, hand-drawn style",
        "secondary": "Averia Serif",
        "secondary_weights": ["Light", "Regular", "Bold", "Italic"],
        "secondary_usage": "Headers, SubHeaders, Paragraph Text",
        "style_notes": "EDO SZ for bold impact headlines, Averia Serif for readable body copy. Raw, masculine aesthetic."
    }
}

print("Creating brand: Savage Supplements...")

# Check if brand already exists
existing = db.table("brands").select("id").eq("slug", "savage-supplements").execute()
if existing.data:
    brand_id = existing.data[0]['id']
    print(f"  Brand already exists with ID: {brand_id}")
else:
    result = db.table("brands").insert(brand_data).execute()
    brand_id = result.data[0]['id']
    print(f"  Created brand with ID: {brand_id}")

# ============================================
# 2. Create Product
# ============================================

product_data = {
    "brand_id": brand_id,
    "name": "Savage",
    "slug": "savage",
    "description": "SAVAGE - Primal Fuel For Men. The Only Organ Supplement That Isn't Beef Jerky Dust. Premium 6-organ stack (90 capsules, 30-day supply) using THE SAVAGE FREEZE PROTOCOL™ - flash-frozen at -40°F to preserve living nutrition. No fluff. No fillers. Just raw power for those who refuse to bow down.",
    "target_audience": """DEMOGRAPHICS:
- Ages: 28-45
- Gender: 100% Men Only
- Income: $80k - $100k
- Education: High-School, College (not University), Trades
- Location: U.S.A & Canada
- Generational: Gen X, Millennial, Gen Z (Late)

PSYCHOGRAPHICS:
- Loyal to traditional values
- Skeptical of mainstream media and institutions
- Values freedom of speech and personal liberty
- Self-reliant and pragmatic
- Wants action, not fluff
- Appreciates straight talk and honesty
- Pride in national identity and heritage""",
    "product_url": "https://fuelthesavage.com",

    # Package dimensions: Height 239mm x Width 140mm x Depth 10mm (gusset)
    "product_dimensions": "Resealable pouch/gusset bag, 239mm tall x 140mm wide x 10mm deep (approximately 9.4\" x 5.5\" x 0.4\"). Flat, flexible packaging that stands on shelf. Pills/capsules inside.",

    # Benefits (What 8-12 Weeks Delivers)
    "benefits": [
        "Optimized B12 Status - Supporting energy metabolism and methylation",
        "Improved Iron Markers - Enhanced oxygen transport via heme iron",
        "Superior Vitamin A Delivery - Better absorption than synthetic supplements",
        "Athletic Performance - Protein synthesis and favorable anabolic environment",
        "Preserved Enzyme Activity - DAO, SOD, catalase remain functional",
        "Hormone balance support via pituitary and testicle organs",
        "Only 3 capsules vs 6+ for competitors"
    ],

    # Unique selling points
    "unique_selling_points": [
        "The Only Organ Supplement That Isn't Beef Jerky Dust",
        "THE SAVAGE FREEZE PROTOCOL™ - Flash-frozen at -40°F within 3 hours",
        "SAVAGE-LOCK™ Process - Water activity 0.29, no preservatives needed",
        "Living nutrition in suspended animation, not dead jerky powder",
        "Complete 6-organ system targeting male hormonal optimization",
        "Only 3 capsules vs 6+ for competitors"
    ],

    # Key ingredients - SAVAGE PROPRIETARY BLEND (500mg per serving)
    # From packaging: Freeze-Dried Bovine Liver, Bovine Heart, Bovine Kidney,
    # Bovine Orchic (Testicles), Bovine Prostate, Bovine Pituitary
    "key_ingredients": [
        "Freeze-Dried Bovine Liver - Vitamin B12, A, folate, and heme iron powerhouse",
        "Bovine Heart - 110μg/g CoQ10 for cellular energy",
        "Bovine Kidney - Source of DAO and detox support",
        "Bovine Orchic (Testicles) - Contains full steroidogenic enzyme cascade",
        "Bovine Prostate - Exceptionally zinc-rich tissue",
        "Bovine Pituitary - Master gland orchestrating hormonal balance"
    ],

    # Brand name for ad generation
    "brand_name": "Savage",

    # Brand voice - The Outlaw archetype
    "brand_voice_notes": """THE OUTLAW ARCHETYPE - Bold, Defiant, Raw, Anti-establishment, Unapologetically authentic.

VOICE CHARACTERISTICS:
- Direct and confrontational, never soft or apologetic
- Challenges mainstream health narratives (competitors sell "beef jerky dust")
- Speaks to men who see through modern BS
- Uses powerful, action-oriented language
- No fluff, no corporate speak, no virtue signaling
- Honest to a fault

TONE: Masculine, Irreverent, Provocative, Confident, No-nonsense

TAGLINE: "Because Testosterone is a Feature Not a Flaw"

PROMISE: Liberation from the fake, weak, or oppressive

KEY MESSAGING:
- "They give you 6+ capsules of beef jerky dust. We give you 3 capsules of suspended animation."
- "The difference between jerky powder and biological resurrection."
- "The difference between staying weak and becoming savage."
""",

    # Full AI context for product adaptations
    "context_prompt": """UNIQUE MECHANISM: THE SAVAGE FREEZE PROTOCOL™

THE BRUTAL TRUTH:
They're feeding you expensive beef jerky powder. We're feeding you suspended animation.
Every other organ supplement starts with good intentions and ends with beef jerky. They cook it at 160°F+. Dry it. Grind it. Stuff it into 6+ capsules. You're literally swallowing ground-up beef jerky dust and wondering why you don't feel different.

Savage is different. We freeze organs at -40°F in suspended animation. No heat. No jerky. No death. Just pure, concentrated biological power that your body recognizes and responds to.

THREE STAGES:
STAGE 1: FLASH-FREEZE CAPTURE - Organs frozen within 3 hours of harvest at -40°F
STAGE 2: SAVAGE-LOCK™ PROCESS - Locks water activity at 0.29 (below 0.60 microbial threshold)
STAGE 3: COMMAND CENTER ACTIVATION™ - The Complete Six-Organ System

THE CHAIN REACTION:
THEIR BROKEN CHAIN: Cook organs → Destroy enzymes → Grind into jerky dust → Dead powder → No recognition → Expensive waste
OUR COMPLETE CHAIN: Freeze organs → Preserve enzymes → Concentrate power → Body recognizes → Nutrients absorb → Systems activate → Biological multiplication

THE BOTTOM LINE:
They give you: 6+ capsules of beef jerky dust. Cooked. Dead. Useless.
We give you: 3 capsules of suspended animation. Frozen. Preserved. Powerful.

SCIENTIFIC VALIDATION (Key Studies):
- Church et al., 2024: 4oz beef stimulates 47% more muscle protein synthesis than plant protein
- Valenzuela et al., 2021: Beef protein improved testosterone:cortisol ratio by ~37% in elite athletes
- Piskin et al., 2022: Heme iron bioavailability 15-35% vs 2-10% non-heme
- van Vliet et al., 2001: Liver delivers higher plasma retinoic acid than supplements
- Bhatta et al., 2020: Lyophilization retains bioactives vs heat drying
- Rockinger et al., 2021: Freeze-drying preserves protein integrity and enzyme activity
""",

    # Tagline/positioning
    "current_offer": None,  # Add when there's an offer

    "is_active": True
}

print(f"\nCreating product: Savage...")

# Check if product already exists
existing_product = db.table("products").select("id").eq("brand_id", brand_id).eq("slug", "savage").execute()
if existing_product.data:
    product_id = existing_product.data[0]['id']
    print(f"  Product already exists with ID: {product_id}")
    # Update with new data
    db.table("products").update(product_data).eq("id", product_id).execute()
    print(f"  Updated existing product")
else:
    result = db.table("products").insert(product_data).execute()
    product_id = result.data[0]['id']
    print(f"  Created product with ID: {product_id}")

# ============================================
# 3. Create Project (optional - for tracking)
# ============================================

project_data = {
    "brand_id": brand_id,
    "product_id": product_id,
    "name": "Savage Ads",
    "slug": "savage-ads",
    "description": "Ad creation project for Savage beef organ supplement",
    "is_active": True
}

print(f"\nCreating project: Savage Ads...")

existing_project = db.table("projects").select("id").eq("slug", "savage-ads").execute()
if existing_project.data:
    project_id = existing_project.data[0]['id']
    print(f"  Project already exists with ID: {project_id}")
else:
    result = db.table("projects").insert(project_data).execute()
    project_id = result.data[0]['id']
    print(f"  Created project with ID: {project_id}")

# ============================================
# Summary
# ============================================

print("\n" + "=" * 50)
print("SETUP COMPLETE")
print("=" * 50)
print(f"\nBrand ID: {brand_id}")
print(f"Product ID: {product_id}")
print(f"Project ID: {project_id}")
print(f"\nProduct: Savage")
print(f"Tagline: \"Because Testosterone is a Feature Not a Flaw\"")
print(f"Target: Men interested in testosterone/health optimization")
print(f"Dimensions: 239mm x 140mm x 10mm (pouch)")
print("\nNext steps:")
print("1. Upload product images via Brand Manager UI")
print("2. Add hooks for the product")
print("3. Start creating ads!")
