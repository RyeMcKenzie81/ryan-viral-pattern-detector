"""
Insert hooks for Savage product.

Based on:
- THE SAVAGE FREEZE PROTOCOL™ unique mechanism
- "Because Testosterone is a Feature Not a Flaw" tagline
- The Outlaw archetype brand voice
- Target audience: Men 28-45, skeptical of mainstream, value straight talk
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

# Savage product ID
PRODUCT_ID = "3c85266c-cc62-4c95-9383-a6b7e7b6155e"

# Hooks with (text, category, framework, impact_score, emotional_score)
HOOKS = [
    # COMPETITIVE COMPARISON - "Not beef jerky dust"
    (
        "Every other organ supplement is beef jerky dust in a capsule. We freeze ours at -40°F. There's a difference.",
        "competitive_comparison",
        "Unique Mechanism",
        18,
        "High"
    ),
    (
        "They cook their organs at 160°F. We freeze ours at -40°F. One gives you dead powder. The other gives you results.",
        "competitive_comparison",
        "Process Comparison",
        19,
        "High"
    ),
    (
        "6 capsules of beef jerky powder vs 3 capsules of suspended animation. Choose your fighter.",
        "competitive_comparison",
        "Dosage Comparison",
        17,
        "Medium"
    ),
    (
        "Most organ supplements start with good intentions and end with ground-up beef jerky. We took a different path.",
        "competitive_comparison",
        "Industry Callout",
        16,
        "Medium"
    ),

    # SKEPTICISM OVERCOME
    (
        "I was skeptical too. Another supplement? But then I read how they freeze organs at -40°F within 3 hours of harvest. That's not marketing. That's science.",
        "skepticism_overcome",
        "Process Skeptic",
        18,
        "High"
    ),
    (
        "I don't trust supplement companies. But I trust the process: flash-frozen, not cooked. Living nutrition, not dead powder.",
        "skepticism_overcome",
        "Trust Through Process",
        17,
        "High"
    ),
    (
        "You've been lied to by every supplement company. They cook organs until they're useless and call it 'natural.' We don't play that game.",
        "skepticism_overcome",
        "Industry Distrust",
        19,
        "Very High"
    ),

    # TRANSFORMATION
    (
        "Week 1: More energy. Week 4: Better recovery. Week 8: My wife noticed the difference. That's what real organ nutrition does.",
        "transformation",
        "Progressive Timeline",
        17,
        "High"
    ),
    (
        "8 weeks ago I was dragging through afternoons. Now I'm outworking guys half my age. The difference? Living nutrition, not dead supplements.",
        "transformation",
        "Energy Transformation",
        18,
        "High"
    ),
    (
        "My bloodwork doesn't lie. B12 optimized. Iron markers improved. That's not a testimonial - that's data.",
        "transformation",
        "Biomarker Results",
        19,
        "High"
    ),

    # RAW HONESTY - The Outlaw voice
    (
        "Testosterone isn't toxic. It's what built civilizations. We made a supplement for men who refuse to apologize for being men.",
        "raw_honesty",
        "Unapologetic Masculine",
        20,
        "Very High"
    ),
    (
        "No fluff. No fillers. No corporate BS. Just 6 organs, frozen at -40°F, and the raw power your body was designed to run on.",
        "raw_honesty",
        "Direct Value Prop",
        18,
        "High"
    ),
    (
        "Because testosterone is a feature, not a flaw. If that offends you, this isn't your supplement.",
        "raw_honesty",
        "Tagline Hook",
        21,
        "Very High"
    ),
    (
        "They want you weak, tired, and apologetic. We want you savage.",
        "raw_honesty",
        "Defiant Positioning",
        20,
        "Very High"
    ),
    (
        "The world doesn't need more soft men. It needs men who refuse to bow down. This is fuel for that fight.",
        "raw_honesty",
        "Mission Statement",
        19,
        "Very High"
    ),

    # PRODUCT SUPERIORITY
    (
        "Pituitary. Testicle. Prostate. Liver. Heart. Kidney. Six organs working together. That's not a supplement - that's a system.",
        "product_superiority",
        "Complete System",
        18,
        "High"
    ),
    (
        "Water activity locked at 0.29. No preservatives needed. No bacteria can grow. Just pure, shelf-stable organ nutrition.",
        "product_superiority",
        "Technical Superiority",
        16,
        "Medium"
    ),
    (
        "3 capsules. 30 days. That's it. No complicated protocols. No 6-pill-a-day routines. Just results.",
        "product_superiority",
        "Simplicity",
        17,
        "Medium"
    ),

    # THIRD PARTY VALIDATION
    (
        "47% more muscle protein synthesis from beef vs plant protein. That's not us talking - that's Church et al., 2024.",
        "third_party_validation",
        "Scientific Citation",
        18,
        "High"
    ),
    (
        "Beef protein improved testosterone:cortisol ratio by 37% in elite athletes. Valenzuela et al., 2021. We just made it easier to get.",
        "third_party_validation",
        "Research Validation",
        19,
        "High"
    ),
    (
        "Freeze-drying preserves enzyme activity. Heat kills it. That's not opinion - that's peer-reviewed research.",
        "third_party_validation",
        "Process Science",
        17,
        "High"
    ),

    # FAILED ALTERNATIVES
    (
        "I tried testosterone clinics. I tried every supplement on Amazon. Then I discovered what happens when you actually preserve the enzymes instead of cooking them.",
        "failed_alternatives",
        "Journey Hook",
        18,
        "High"
    ),
    (
        "Synthetic vitamins didn't work. Protein powders didn't work. Turns out my body was waiting for something it actually recognized.",
        "failed_alternatives",
        "Recognition Hook",
        17,
        "High"
    ),
    (
        "I spent thousands on supplements that did nothing. The difference? They were selling me cooked, dead powder. This is different.",
        "failed_alternatives",
        "Cost Waste",
        18,
        "High"
    ),

    # PROBLEM SOLVED
    (
        "Low energy at 35 isn't normal. It's a sign your body isn't getting what it needs. We fixed that.",
        "problem_solved",
        "Age-Related Energy",
        17,
        "High"
    ),
    (
        "Brain fog. Afternoon crashes. Poor recovery. These aren't symptoms of aging - they're symptoms of deficiency.",
        "problem_solved",
        "Symptom Reframe",
        18,
        "High"
    ),
    (
        "Your grandfather didn't have low testosterone because he ate the whole animal. We brought that wisdom back in capsule form.",
        "problem_solved",
        "Ancestral Wisdom",
        19,
        "Very High"
    ),

    # DISCOVERY
    (
        "The secret isn't what's in the capsule. It's what they didn't do to it. No heat. No cooking. No destruction.",
        "discovery",
        "Process Secret",
        17,
        "High"
    ),
    (
        "I discovered why my $200/month supplement stack wasn't working. They cooked all the good stuff out of it.",
        "discovery",
        "Revelation Hook",
        18,
        "High"
    ),

    # FEAR TRIGGER
    (
        "Your testosterone drops 1% every year after 30. Are you just going to watch it happen?",
        "fear_trigger",
        "Decline Fear",
        16,
        "High"
    ),
    (
        "Most men accept feeling tired and weak as 'just getting older.' They're wrong. And they don't have to accept it.",
        "fear_trigger",
        "Aging Myth",
        17,
        "High"
    ),

    # PROACTIVE WIN
    (
        "I'm not waiting to feel old. I'm taking control now. That's what Savage is for.",
        "proactive_win",
        "Control Narrative",
        16,
        "High"
    ),
    (
        "The best time to optimize your hormones was 10 years ago. The second best time is today.",
        "proactive_win",
        "Urgency",
        17,
        "High"
    ),

    # UNIQUE MECHANISM DEEP DIVE
    (
        "STAGE 1: Flash-freeze at -40°F within 3 hours. STAGE 2: Lock water activity at 0.29. STAGE 3: Your body recognizes real food and responds. That's the Savage Freeze Protocol.",
        "product_superiority",
        "Protocol Breakdown",
        19,
        "High"
    ),
    (
        "The difference between jerky powder and biological resurrection. The difference between staying weak and becoming savage.",
        "product_superiority",
        "Binary Choice",
        20,
        "Very High"
    ),

    # INGREDIENT SPECIFIC
    (
        "Bovine testicle contains the complete steroidogenic enzyme cascade. That's your body's testosterone production line - in a capsule.",
        "product_feature",
        "Ingredient Science",
        17,
        "Medium"
    ),
    (
        "110μg/g of CoQ10 from beef heart. That's cellular energy your body actually recognizes. Not synthetic garbage.",
        "product_feature",
        "CoQ10 Callout",
        16,
        "Medium"
    ),
    (
        "Pituitary. The master gland. The one that tells everything else what to do. We put it in the stack for a reason.",
        "product_feature",
        "Pituitary Hook",
        17,
        "Medium"
    ),
]


def insert_hooks():
    """Insert hooks for Savage product"""

    print(f"Inserting {len(HOOKS)} hooks for Savage product...")
    print(f"Product ID: {PRODUCT_ID}")
    print()

    # Verify product exists
    product_check = db.table("products").select("name").eq("id", PRODUCT_ID).execute()
    if not product_check.data:
        print(f"Product {PRODUCT_ID} not found!")
        return

    print(f"Product: {product_check.data[0]['name']}")
    print()

    # Check for existing hooks
    existing = db.table("hooks").select("id").eq("product_id", PRODUCT_ID).execute()
    if existing.data:
        print(f"Found {len(existing.data)} existing hooks. Deleting...")
        db.table("hooks").delete().eq("product_id", PRODUCT_ID).execute()
        print("Deleted existing hooks.")
        print()

    # Insert new hooks
    inserted = 0
    for text, category, framework, impact_score, emotional_score in HOOKS:
        try:
            hook_record = {
                "product_id": PRODUCT_ID,
                "text": text,
                "category": category,
                "framework": framework,
                "impact_score": impact_score,
                "emotional_score": emotional_score,
                "active": True
            }
            db.table("hooks").insert(hook_record).execute()
            inserted += 1
            print(f"  [{category}] {text[:60]}...")
        except Exception as e:
            print(f"  Error inserting hook: {e}")

    print()
    print("=" * 50)
    print(f"HOOKS INSERTED: {inserted}/{len(HOOKS)}")
    print("=" * 50)

    # Summary by category
    print("\nHooks by category:")
    categories = {}
    for _, category, _, _, _ in HOOKS:
        categories[category] = categories.get(category, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    insert_hooks()
