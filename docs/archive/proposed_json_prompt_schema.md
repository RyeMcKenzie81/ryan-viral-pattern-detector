# Proposed JSON Prompt Schema

**Date**: 2025-12-09
**Purpose**: JSON-based prompt structure to replace markdown format

---

## Complete JSON Schema

```json
{
  "task": {
    "action": "create_facebook_ad",
    "variation_index": 1,
    "total_variations": 5
  },

  "special_instructions": {
    "priority": "highest",
    "brand_defaults": "White backdrops work best",
    "run_specific": "Feature Brown Sugar flavor prominently",
    "combined": "White backdrops work best\n\nRun-specific:\nFeature Brown Sugar flavor prominently"
  },

  "product": {
    "id": "d4f2355d-df08-473d-b4f2-f94355a23300",
    "name": "All-in-One Superfood Shake",
    "display_name": "All-in-One Superfood Shake - Brown Sugar",
    "target_audience": "Busy professionals 25-45 wanting default nutrition habit",
    "benefits": ["Simplifies daily nutrition", "Makes consistency easier"],
    "unique_selling_points": ["41 fruit and vegetable blend", "Digestive enzymes"],
    "current_offer": "Save up to 30%",
    "brand_voice_notes": "Use 'we' and 'you', avoid wellness clichés",
    "prohibited_claims": ["miracle", "revolutionary", "toxins"],
    "required_disclaimers": null,
    "founders": null,
    "product_dimensions": null,
    "variant": {
      "id": "xxx",
      "name": "Brown Sugar",
      "type": "flavor",
      "description": "Rich brown sugar flavor"
    }
  },

  "content": {
    "headline": {
      "text": "Finally, a superfood shake that actually tastes good",
      "source": "hook",
      "hook_id": "xxx",
      "persuasion_type": "curiosity"
    },
    "subheadline": {
      "text": "Tastes like a drink, not a supplement",
      "source": "matched_benefit"
    }
  },

  "style": {
    "format_type": "single_image_lifestyle",
    "layout_structure": "product_centered_text_overlay",
    "canvas_size": "1080x1080px",
    "color_mode": "brand",
    "colors": {
      "palette": ["#593590", "#439E4A", "#FFE4CA"],
      "primary": {"hex": "#593590", "name": "Taro Purple"},
      "secondary": {"hex": "#439E4A", "name": "Matcha Green"},
      "background": {"hex": "#FFE4CA", "name": "Brown Sugar Cream"}
    },
    "color_instructions": "Use official brand colors consistently",
    "fonts": {
      "heading": {
        "family": "Stinger Variable",
        "weight": "Fit Bold",
        "style_notes": "always lowercase"
      },
      "body": {
        "family": "Roc Grotesk",
        "weight": "Regular",
        "style_notes": null
      }
    },
    "authenticity_markers": ["real_ingredients", "lifestyle_context"]
  },

  "images": {
    "template": {
      "path": "reference-ads/xxx/template.png",
      "role": "style_reference"
    },
    "product": [
      {
        "path": "products/infi/brown-sugar-front.png",
        "role": "primary",
        "description": "Main product packaging"
      }
    ]
  },

  "template_analysis": {
    "format_type": "single_image_lifestyle",
    "layout_structure": "product_centered_text_overlay",
    "text_placement": {
      "headline": "top_center",
      "subheadline": "below_headline",
      "offer": "bottom_banner"
    },
    "has_founder_signature": false,
    "has_founder_mention": false,
    "detailed_description": "Clean lifestyle ad with product centered..."
  },

  "rules": {
    "product_image": {
      "preserve_exactly": true,
      "no_modifications": true,
      "text_preservation": {
        "critical": true,
        "instructions": "ALL text on packaging MUST be pixel-perfect legible",
        "method": "composite_not_regenerate"
      }
    },
    "offers": {
      "use_only_provided": true,
      "do_not_copy_from_template": true,
      "max_count": 1,
      "prohibited_template_offers": ["Free gift", "Buy 1 Get 1", "Bundle and save", "Autoship"]
    },
    "lighting": {
      "match_scene": true,
      "shadow_direction": "match_scene_elements",
      "color_temperature": "match_scene",
      "ambient_occlusion": true
    },
    "scale": {
      "realistic_sizing": true,
      "relative_to": ["hands", "countertops", "furniture"],
      "product_dimensions": null
    },
    "founders": {
      "template_has_signature": false,
      "template_has_mention": false,
      "product_founders": null,
      "action": "omit"
    },
    "prohibited_claims": ["miracle", "revolutionary", "toxins"],
    "required_disclaimers": null
  },

  "ad_brief": {
    "brand_guidelines": "Infi brand guidelines...",
    "instructions": "Full ad brief instructions text..."
  }
}
```

---

## Comparison: Old vs New

| Old Markdown Section | New JSON Location |
|---------------------|-------------------|
| `ad_brief_instructions` | `ad_brief.instructions` |
| `special_instructions_section` | `special_instructions.combined` |
| Style Guide - Format | `style.format_type` |
| Style Guide - Layout | `style.layout_structure` |
| Style Guide - Colors | `style.colors.*` + `style.color_instructions` |
| Style Guide - Fonts | `style.fonts.*` **(NEW - was missing!)** |
| Style Guide - Authenticity | `style.authenticity_markers` |
| Hook (Main Headline) | `content.headline.text` |
| Product - Name | `product.name` / `product.display_name` |
| Product - Primary Benefit | `content.subheadline.text` |
| Product - Target | `product.target_audience` |
| Current Offer | `product.current_offer` |
| Unique Selling Points | `product.unique_selling_points` |
| Brand Voice & Tone | `product.brand_voice_notes` |
| Product Dimensions | `product.product_dimensions` + `rules.scale` |
| Lighting section | `rules.lighting.*` |
| Founders section | `rules.founders.*` |
| Prohibited Claims | `rules.prohibited_claims` |
| Required Disclaimers | `rules.required_disclaimers` |
| Product Image Instructions | `rules.product_image.*` |
| Critical Requirements | Distributed across `rules.*` |
| Offer/Callout Warning | `rules.offers.*` |
| Technical Specifications | `style.*` + `images.*` |
| Reference Images | `images.template` + `images.product` |
| Detailed Description | `template_analysis.detailed_description` |

---

## Benefits of JSON Format

1. **Structured** - Clear hierarchy, no ambiguous formatting
2. **Parseable** - AI can reference `rules.offers.max_count` directly
3. **Validatable** - Can validate schema before sending
4. **Extensible** - Easy to add new fields
5. **Consistent** - Same structure every time
6. **Debuggable** - Easy to log and inspect

---

## Migration Notes

- All existing fields are preserved
- Some fields reorganized for better grouping
- Rules consolidated into single `rules` object
- Images have explicit `role` field
- Colors have both palette array and named colors
