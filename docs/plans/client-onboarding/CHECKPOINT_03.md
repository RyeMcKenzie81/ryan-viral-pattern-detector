# Client Onboarding Pipeline - Checkpoint 3

**Date**: 2026-01-06
**Status**: Product Offer Variants Complete
**Feature**: Multi-landing page support with messaging context

---

## Summary

Implemented Product Offer Variants feature to handle products with multiple landing pages targeting different pain points (e.g., Sea Moss with Blood Pressure, Hair Loss, Skincare angles).

**Key Achievement**: When scheduling ads, users MUST select an offer variant for products that have them, ensuring ads target the correct landing page with matching messaging.

---

## Files Created

| File | Purpose |
|------|---------|
| `migrations/2026-01-07_product_offer_variants.sql` | New table with landing_page_url, pain_points[], desires_goals[], benefits[] |
| `viraltracker/services/product_offer_variant_service.py` | CRUD, validation, default management |

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/client_onboarding_service.py` | Import creates offer variants from onboarding session |
| `viraltracker/ui/pages/06_Client_Onboarding.py` | Per-product offer variant UI in Products tab |
| `viraltracker/ui/pages/24_Ad_Scheduler.py` | Required offer variant selector, params stored |
| `viraltracker/worker/scheduler_worker.py` | Context injection from offer variant into ad generation |

---

## Database Schema

```sql
CREATE TABLE product_offer_variants (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES products(id),
    name TEXT NOT NULL,                    -- "Blood Pressure Angle"
    slug TEXT NOT NULL,
    landing_page_url TEXT NOT NULL,        -- Required destination
    pain_points TEXT[],                    -- ["high BP", "cholesterol"]
    desires_goals TEXT[],                  -- ["heart health"]
    benefits TEXT[],                       -- ["supports healthy BP"]
    target_audience TEXT,
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    display_order INT DEFAULT 0,
    UNIQUE(product_id, slug)
);

-- Partial unique index ensures single default per product
CREATE UNIQUE INDEX idx_pov_single_default
    ON product_offer_variants(product_id)
    WHERE is_default = true;

-- Extended generated_ads table
ALTER TABLE generated_ads ADD COLUMN destination_url TEXT;
ALTER TABLE generated_ads ADD COLUMN offer_variant_id UUID;
```

---

## Feature Flow

### 1. Client Onboarding (Setup)
```
Products Tab → Add Product → Add Offer Variants
├── Blood Pressure Angle
│   ├── URL: infiniteage.com/bp
│   ├── Pain: high blood pressure, cholesterol
│   └── Desires: heart health, better energy
├── Hair Loss Angle
│   ├── URL: infiniteage.com/hair
│   └── Pain: thinning hair, bald spots
└── Skincare Angle
    ├── URL: infiniteage.com/skin
    └── Pain: acne, aging skin
```

### 2. Ad Scheduler (Selection Required)
```
Select Product → (if has offer variants) → MUST select one
├── Dropdown shows all active variants with URL preview
├── Selected variant displays:
│   ├── Landing page URL
│   ├── Pain points
│   └── Desires/goals
└── Validation blocks creation if not selected
```

### 3. Worker Execution (Context Injection)
```
Job runs → Fetches offer variant → Builds context:
=== OFFER VARIANT CONTEXT ===
Landing Page: infiniteage.com/bp
Target Pain Points: high blood pressure, cholesterol
Target Desires: heart health, better energy
Key Benefits: supports healthy BP
=== END OFFER CONTEXT ===

Context passed to ad generation as additional_instructions
```

---

## Service Layer API

```python
class ProductOfferVariantService:
    # CRUD
    def create_offer_variant(product_id, name, landing_page_url, ...) -> UUID
    def get_offer_variants(product_id, active_only=True) -> List[Dict]
    def get_offer_variant(variant_id) -> Optional[Dict]
    def get_default_offer_variant(product_id) -> Optional[Dict]
    def update_offer_variant(variant_id, updates) -> bool
    def set_as_default(variant_id) -> bool
    def delete_offer_variant(variant_id) -> bool  # Cannot delete last one

    # Validation (for ad scheduler)
    def validate_offer_variant_selection(product_id, offer_variant_id)
        -> Tuple[bool, error_msg, variant_data]
    def has_offer_variants(product_id) -> bool

    # Bulk (for import)
    def create_offer_variants_from_list(product_id, variants) -> List[UUID]
```

---

## Scheduler Parameters

```python
# In scheduled_jobs.parameters JSONB
{
    "offer_variant_id": "uuid",      # Required if product has variants
    "destination_url": "https://...", # Landing page from variant
    # ... other params
}
```

---

## Testing Checklist

- [x] Migration SQL syntax valid
- [x] Service compiles without errors
- [x] Onboarding UI compiles without errors
- [x] Scheduler UI compiles without errors
- [x] Worker compiles without errors
- [ ] Run migration in Supabase
- [ ] Manual test: Add offer variants in onboarding
- [ ] Manual test: Import creates offer variants
- [ ] Manual test: Scheduler requires selection
- [ ] Manual test: Worker injects context

---

## Backward Compatibility

- Products WITHOUT offer variants work as before
- Scheduler does not require selection for these products
- Uses `product.product_url` as destination
- No migration of existing products needed

---

## Next Steps

1. Run migration `2026-01-07_product_offer_variants.sql`
2. Test with Infinite Age Sea Moss product
3. Add Brand Manager UI for editing variants after import (optional)
4. Verify ad generation uses context correctly
