# Backup: Ad Generation Prompt Structure

**Date**: 2025-12-09
**Purpose**: Backup of markdown-based prompt structure before JSON refactor

---

## Current Prompt Components Checklist

The current `generate_nano_banana_prompt()` function includes these elements:

### 1. Ad Brief Instructions
- `{ad_brief_instructions}` - Brand guidelines from ad brief template

### 2. Special Instructions (Highest Priority)
- `{special_instructions_section}` - Combined brand defaults + run-specific instructions
- Only included if `product.get('combined_instructions')` exists

### 3. Style Guide
- Format: `{ad_analysis.get('format_type')}`
- Layout: `{ad_analysis.get('layout_structure')}`
- Colors: `{color_instructions}` - varies by color_mode (original/complementary/brand)
- Authenticity: `{ad_analysis.get('authenticity_markers', [])}`

### 4. Hook (Main Headline)
- `{selected_hook.get('adapted_text')}`

### 5. Product Info
- Name: `{product.get('name')}`
- Primary Benefit (matched to hook): `{matched_benefit}`
- Target: `{product.get('target_audience', 'general audience')}`

### 6. Conditional Sections (only if data exists)

| Section | Condition | Content |
|---------|-----------|---------|
| `offer_section` | `product.get('current_offer')` | Current offer text |
| `usp_section` | `product.get('unique_selling_points')` | USP list |
| `brand_voice_section` | `product.get('brand_voice_notes')` | Brand voice guidelines |
| `dimensions_section` | `product.get('product_dimensions')` or default | Scale guidance |
| `lighting_section` | Always included | Lighting integration rules |
| `social_proof_section` | Currently empty | Reserved for future |
| `founders_section` | Template has founder elements | Founder name handling |
| `prohibited_section` | `product.get('prohibited_claims')` | Claims to avoid |
| `disclaimer_section` | `product.get('required_disclaimers')` | Required legal text |

### 7. Product Image Instructions
- Single image: Basic preservation rules + text/logo preservation warning
- Multiple images: Primary/secondary image handling + text/logo preservation

### 8. Critical Requirements
- Use product image(s) EXACTLY
- Match reference ad layout and style
- Maintain brand voice
- Use EXACT offer wording
- Avoid prohibited claims

### 9. Offer/Callout Warning
- Don't copy template offers
- Use only provided offer
- Don't stack multiple offers
- Max one offer callout

### 10. Technical Specifications (spec object)
```python
spec = {
    "canvas": "{canvas_size}, background {background_color}",
    "product_images": product_image_paths,
    "product_image_instructions": product_image_instructions,
    "text_elements": {
        "headline": selected_hook.get('adapted_text'),
        "subheadline": matched_benefit,
        "layout": ad_analysis.get('text_placement', {})
    },
    "colors": colors_for_spec,
    "color_mode": color_mode,
    "authenticity_markers": ad_analysis.get('authenticity_markers', [])
}
```

### 11. Reference Images
- Template path
- Product image path(s) (1 or 2)

### 12. Detailed Description
- `{ad_analysis.get('detailed_description', '')}`

---

## Full Prompt Template (Markdown Format)

```
{ad_brief_instructions}

Create Facebook ad variation {prompt_index} for {product.get('name')}.

**⚠️ SPECIAL INSTRUCTIONS - HIGHEST PRIORITY:**
{product.get('combined_instructions')}
---

**Style Guide:**
- Format: {ad_analysis.get('format_type')}
- Layout: {ad_analysis.get('layout_structure')}
- Colors: {color_instructions}
- Authenticity: {authenticity_markers}

**Hook (Main Headline):**
"{selected_hook.get('adapted_text')}"

**Product:**
- Name: {product.get('name')}
- Primary Benefit (matched to hook): {matched_benefit}
- Target: {product.get('target_audience')}

**Current Offer (USE EXACTLY AS WRITTEN):**
"{product.get('current_offer')}"

**Unique Selling Points:**
{unique_selling_points}

**Brand Voice & Tone:**
{brand_voice_notes}

**Product Dimensions & Scale (CRITICAL FOR REALISTIC SIZING):**
{product_dimensions or default scale guidance}

**LIGHTING & PRODUCT INTEGRATION (CRITICAL):**
- Analyze lighting direction, intensity, color temperature
- Apply MATCHING lighting to product
- Shadows must match scene
- Match color temperature
- Add ambient occlusion
- Product should look "in" scene, not "pasted on"

**FOUNDERS / PERSONAL SIGNATURE:**
{founders_section - conditional based on template analysis}

**PROHIBITED CLAIMS (DO NOT USE):**
{prohibited_claims}

**Required Disclaimer (MUST INCLUDE):**
{required_disclaimers}

**Product Image Instructions:**
{product_image_instructions with text/logo preservation warning}

**Critical Requirements:**
- Use product image(s) EXACTLY as provided (no hallucination)
- Match reference ad layout and style
- Maintain brand voice from ad brief
- If offer is provided, use EXACT wording
- Do NOT use any prohibited claims

**⚠️ OFFER/CALLOUT WARNING - CRITICAL:**
- DO NOT copy offer elements from reference template
- ONLY use provided offer text
- If NO offer, don't add any
- DO NOT stack multiple offers - use ONE only

**Technical Specifications:**
{spec}

**Reference Images:**
- Template (Image 1): {reference_ad_path}
- Product (Image 2): {product_image_paths[0]}
- Secondary Product (Image 3): {product_image_paths[1]} (if exists)

{ad_analysis.get('detailed_description', '')}
```

---

## Return Object Structure

```python
prompt_dict = {
    "prompt_index": prompt_index,
    "hook": selected_hook,
    "instruction_text": instruction_text,
    "spec": spec,
    "full_prompt": full_prompt,
    "template_reference_path": reference_ad_path,
    "product_image_paths": product_image_paths
}
```

---

## Data Sources

| Data | Source |
|------|--------|
| `ad_brief_instructions` | `get_ad_brief_template()` tool |
| `ad_analysis` | Vision AI analysis of reference template |
| `product` | `get_product_with_images()` tool |
| `selected_hook` | Hook selection from database |
| `matched_benefit` | `match_benefit_to_hook()` function |
| `brand_colors` | Passed from UI when color_mode="brand" |
| `combined_instructions` | Brand defaults + run-specific merged in workflow |

---

## Color Mode Handling

| Mode | Colors Used | Instructions |
|------|-------------|--------------|
| `original` | Template colors from ad_analysis | "Use exact colors from reference" |
| `complementary` | AI generates | "Generate fresh complementary colors" |
| `brand` | From brand_colors param | "Use official brand colors: {names and hex}" |
