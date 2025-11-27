"""
Populate Wonder Paws Collagen 3x product with 50 hooks for testing.

Run with:
    python populate_wonder_paws_hooks.py
"""
import asyncio
from uuid import UUID
from viraltracker.core.database import get_supabase_client

# Test product ID
PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# 50 Wonder Paws Collagen hooks with scores and categories
HOOKS = [
    # Top 10 Highest Impact (21-11)
    {
        "text": "I don't believe in miracle products. But my dog stopped scratching in 2 weeks.",
        "category": "skepticism_overcome",
        "framework": "Skepticism Overcome",
        "impact_score": 21,
        "emotional_score": 20,
        "active": True
    },
    {
        "text": "After one week, my chocolate Bully's itchy belly got a little better. Week 3? Completely gone.",
        "category": "progressive_timeline",
        "framework": "Progressive Timeline",
        "impact_score": 20,
        "emotional_score": 18,
        "active": True
    },
    {
        "text": "Week 1: Less shedding. Week 2: Softer coat. Week 3: My groomer was shocked.",
        "category": "progressive_results",
        "framework": "Progressive Results",
        "impact_score": 19,
        "emotional_score": 17,
        "active": True
    },
    {
        "text": "My vet wanted $150/month for joint supplements. Then I discovered this liquid collagen.",
        "category": "cost_comparison",
        "framework": "Cost Comparison",
        "impact_score": 15,
        "emotional_score": 14,
        "active": True
    },
    {
        "text": "My dog scratched for 4 years straight. Day 10 on this: silence.",
        "category": "chronic_problem_solved",
        "framework": "Chronic Problem Solved",
        "impact_score": 15,
        "emotional_score": 16,
        "active": True
    },
    {
        "text": "7-year-old Italian Greyhound. Zero shedding in under 2 months.",
        "category": "breed_specific_results",
        "framework": "Breed-Specific Results",
        "impact_score": 14,
        "emotional_score": 12,
        "active": True
    },
    {
        "text": "2 months on collagen: My Italian Mastiff moves like he's half his age.",
        "category": "age_reversal",
        "framework": "Age Reversal",
        "impact_score": 12,
        "emotional_score": 13,
        "active": True
    },
    {
        "text": "140-pound Cane Corso. 2 days of drops. Already seeing improvement.",
        "category": "quick_results",
        "framework": "Quick Results",
        "impact_score": 12,
        "emotional_score": 11,
        "active": True
    },
    {
        "text": "These drops saved my dog's mobility. (She's 12 and runs like she's 5.)",
        "category": "dramatic_save",
        "framework": "Dramatic Save",
        "impact_score": 11,
        "emotional_score": 14,
        "active": True
    },
    {
        "text": "I'm skeptical of supplements. But my vet noticed the difference before I told him.",
        "category": "third_party_validation",
        "framework": "Third-Party Validation",
        "impact_score": 11,
        "emotional_score": 13,
        "active": True
    },

    # High-Value Hooks (11-20)
    {
        "text": "No longer scratching on the rug! - Real review after 2 weeks",
        "category": "timeline_specific",
        "framework": "Timeline Specific",
        "impact_score": 11,
        "emotional_score": 10,
        "active": True
    },
    {
        "text": "I bought this for my dog's joints. Now her coat shines and nails are stronger.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 10,
        "emotional_score": 11,
        "active": True
    },
    {
        "text": "Originally for coat health. Now it's solved the scratching AND shedding.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 10,
        "emotional_score": 10,
        "active": True
    },
    {
        "text": "Was about to try $200 prescription food for itching. These drops worked instead.",
        "category": "cost_comparison",
        "framework": "Cost Comparison",
        "impact_score": 8,
        "emotional_score": 9,
        "active": True
    },
    {
        "text": "The vet asked what I'm doing differently - 5-star review",
        "category": "professional_validation",
        "framework": "Professional Validation",
        "impact_score": 7,
        "emotional_score": 8,
        "active": True
    },
    {
        "text": "8-year-old Max was slowing down. Few weeks later? Different dog.",
        "category": "age_reversal",
        "framework": "Age Reversal",
        "impact_score": 7,
        "emotional_score": 9,
        "active": True
    },
    {
        "text": "My strict vet approved it. That never happens.",
        "category": "professional_validation",
        "framework": "Professional Validation",
        "impact_score": 7,
        "emotional_score": 8,
        "active": True
    },
    {
        "text": "Got it for joints. The ear infections stopped.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 7,
        "emotional_score": 7,
        "active": True
    },
    {
        "text": "This saved my carpets. (And my sanity from the constant scratching.)",
        "category": "problem_solved",
        "framework": "Problem Solved",
        "impact_score": 6,
        "emotional_score": 7,
        "active": True
    },
    {
        "text": "This saved my white furniture from constant shedding.",
        "category": "problem_solved",
        "framework": "Problem Solved",
        "impact_score": 6,
        "emotional_score": 6,
        "active": True
    },

    # Solid Performers (21-35)
    {
        "text": "Didn't think collagen was for dogs. But that dull coat is now Instagram-worthy.",
        "category": "skepticism_overcome",
        "framework": "Skepticism Overcome",
        "impact_score": 6,
        "emotional_score": 7,
        "active": True
    },
    {
        "text": "Finally found my answer for dry, itchy skin",
        "category": "problem_solved",
        "framework": "Problem Solved",
        "impact_score": 6,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "Three different people at the dog park asked about my dog's coat.",
        "category": "social_proof",
        "framework": "Social Proof",
        "impact_score": 6,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "Bought it for shedding. Fixed the nail splitting too.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 6,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "Started for coat health. Energy levels went through the roof.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 6,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "I was about to spend $300 on allergy medication. Then I found these collagen drops.",
        "category": "cost_comparison",
        "framework": "Cost Comparison",
        "impact_score": 5,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "I almost paid $500 for skin treatments. Then this orange bottle changed everything.",
        "category": "cost_comparison",
        "framework": "Cost Comparison",
        "impact_score": 5,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "The groomer asked if I changed his diet. I showed her this bottle.",
        "category": "professional_validation",
        "framework": "Professional Validation",
        "impact_score": 5,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "Oatmeal baths failed. Special shampoos failed. Prescription food failed. This worked.",
        "category": "failed_alternatives",
        "framework": "Failed Alternatives",
        "impact_score": 5,
        "emotional_score": 7,
        "active": True
    },
    {
        "text": "Tried 6 products before this. Should have started here.",
        "category": "failed_alternatives",
        "framework": "Failed Alternatives",
        "impact_score": 4,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "Nearly spent thousands on different supplements. This one bottle replaced them all.",
        "category": "cost_comparison",
        "framework": "Cost Comparison",
        "impact_score": 3,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "Got it for the itching. Now my dog's fur is softer than a puppy's.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 3,
        "emotional_score": 4,
        "active": True
    },
    {
        "text": "This liquid saved me from trying product #7. (Finally, one that works.)",
        "category": "failed_alternatives",
        "framework": "Failed Alternatives",
        "impact_score": 3,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "These drops saved our morning walks. (No more limping after 10 minutes.)",
        "category": "dramatic_save",
        "framework": "Dramatic Save",
        "impact_score": 3,
        "emotional_score": 5,
        "active": True
    },
    {
        "text": "Never trusted liquid supplements. But my picky eater begs for this.",
        "category": "skepticism_overcome",
        "framework": "Skepticism Overcome",
        "impact_score": 3,
        "emotional_score": 4,
        "active": True
    },

    # Supporting Hooks (36-50)
    {
        "text": "I don't do reviews. But when your 12-year-old dog starts jumping again...",
        "category": "skepticism_overcome",
        "framework": "Skepticism Overcome",
        "impact_score": 3,
        "emotional_score": 6,
        "active": True
    },
    {
        "text": "My dog's nails were brittle. Now they're strong. - Actual customer",
        "category": "transformation",
        "framework": "Transformation",
        "impact_score": 3,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "White furniture, white dog, no more white hair everywhere",
        "category": "problem_solved",
        "framework": "Problem Solved",
        "impact_score": 3,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "Even my skeptical husband noticed the difference.",
        "category": "third_party_validation",
        "framework": "Third-Party Validation",
        "impact_score": 3,
        "emotional_score": 4,
        "active": True
    },
    {
        "text": "Doggy daycare asked what we're doing differently.",
        "category": "professional_validation",
        "framework": "Professional Validation",
        "impact_score": 3,
        "emotional_score": 4,
        "active": True
    },
    {
        "text": "Spent a fortune on supplements that didn't work. Should've started here.",
        "category": "failed_alternatives",
        "framework": "Failed Alternatives",
        "impact_score": 3,
        "emotional_score": 4,
        "active": True
    },
    {
        "text": "Used it for allergies. Dental health improved as bonus.",
        "category": "unexpected_benefits",
        "framework": "Unexpected Benefits",
        "impact_score": 3,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "Started for hip support. Now all three of my dogs get it daily.",
        "category": "multi_pet",
        "framework": "Multi-Pet Household",
        "impact_score": 0,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "Bought for my senior dog. Now my puppy takes it preventatively.",
        "category": "multi_pet",
        "framework": "Multi-Pet Household",
        "impact_score": 0,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "My picky dogs actually love the taste",
        "category": "product_feature",
        "framework": "Product Feature",
        "impact_score": 0,
        "emotional_score": 2,
        "active": True
    },
    {
        "text": "Fishy smell? Can only smell it if you put your nose to it.",
        "category": "objection_handling",
        "framework": "Objection Handling",
        "impact_score": 0,
        "emotional_score": 1,
        "active": True
    },
    {
        "text": "We tried collagen chews before. My dog spit them out. He begs for these drops.",
        "category": "product_superiority",
        "framework": "Product Superiority",
        "impact_score": 0,
        "emotional_score": 3,
        "active": True
    },
    {
        "text": "Pills hidden in peanut butter? Rejected. These drops in water? Drinks it all.",
        "category": "product_feature",
        "framework": "Product Feature",
        "impact_score": 0,
        "emotional_score": 2,
        "active": True
    },
    {
        "text": "Other collagen made him sick. This one made him better.",
        "category": "product_superiority",
        "framework": "Product Superiority",
        "impact_score": 0,
        "emotional_score": 4,
        "active": True
    },
    {
        "text": "Ordered for one dog. Now all three dogs and the cat take it.",
        "category": "multi_pet",
        "framework": "Multi-Pet Household",
        "impact_score": 0,
        "emotional_score": 3,
        "active": True
    },
]


async def populate_hooks():
    """Populate Wonder Paws product with 50 hooks"""
    supabase = get_supabase_client()

    print(f"Populating {len(HOOKS)} hooks for product {PRODUCT_ID}...")

    # First, check if product exists
    product_check = supabase.table("products").select("*").eq("id", PRODUCT_ID).execute()
    if not product_check.data:
        print(f"❌ Product {PRODUCT_ID} not found in database!")
        return

    print(f"✅ Product found: {product_check.data[0].get('name')}")

    # Delete existing hooks for this product (if any)
    print("Deleting existing hooks...")
    supabase.table("hooks").delete().eq("product_id", PRODUCT_ID).execute()

    # Insert all hooks
    hooks_to_insert = []
    for hook in HOOKS:
        # Cap impact_score based on database constraints
        # NOTE: emotional_score must be NULL (omitted) - database constraint rejects any numeric value
        impact_score = min(hook.get('impact_score', 5), 10)

        hook_data = {
            "product_id": PRODUCT_ID,
            **{k: v for k, v in hook.items() if k not in ['impact_score', 'emotional_score']},
            "impact_score": impact_score
            # emotional_score intentionally omitted - must be NULL per database constraint
        }
        hooks_to_insert.append(hook_data)

    # Batch insert
    result = supabase.table("hooks").insert(hooks_to_insert).execute()

    print(f"✅ Successfully inserted {len(result.data)} hooks!")
    print("\nHook Distribution by Category:")

    # Count by category
    from collections import Counter
    categories = Counter([h['category'] for h in HOOKS])
    for category, count in categories.most_common():
        print(f"  - {category}: {count}")

    print("\nImpact Score Distribution:")
    scores = Counter([h['impact_score'] for h in HOOKS])
    for score in sorted(scores.keys(), reverse=True):
        print(f"  - Score {score}: {scores[score]} hooks")

    print(f"\n🎯 Top 5 Hooks by Impact Score:")
    sorted_hooks = sorted(HOOKS, key=lambda x: x['impact_score'], reverse=True)
    for i, hook in enumerate(sorted_hooks[:5], 1):
        print(f"  {i}. [{hook['impact_score']}] {hook['text'][:60]}...")


if __name__ == "__main__":
    asyncio.run(populate_hooks())
