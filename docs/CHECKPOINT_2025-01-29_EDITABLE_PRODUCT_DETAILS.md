# Checkpoint: Editable Product Details & Compliance in Brand Manager

**Date:** 2025-01-29
**Branch:** `feat/veo-avatar-tool`
**Commit:** `0911b77`

## Problem

The ad creation agent reads ~25 product fields when generating ads, but the Brand Manager UI only exposed 4 of them for editing (product_code + 3 social proof fields). Critical fields like `current_offer`, `target_audience`, `benefits`, and `prohibited_claims` were displayed read-only or not shown at all, requiring direct database changes to update them.

## Changes

**Single file modified:** `viraltracker/ui/pages/02_🏢_Brand_Manager.py` (+204 lines)

### 1. `save_product_details()` helper

Generic helper that takes a product ID and a dict of column updates, following the `save_product_social_proof()` pattern. Reused by both the Details and Compliance forms.

### 2. Editable Details section (Details tab)

The read-only product details now include two previously invisible fields (**Brand Voice Notes**, **Key Ingredients**) in the display. Below the read-only view, an "Edit Details" toggle opens a form with:

| Field | DB Column | Input Type |
|-------|-----------|-----------|
| Current Offer | `current_offer` | `text_input` |
| Target Audience | `target_audience` | `text_area` |
| Benefits | `benefits` | `text_area` (one per line -> list) |
| USPs | `unique_selling_points` | `text_area` (one per line -> list) |
| Key Ingredients | `key_ingredients` | `text_area` (one per line -> list) |
| Founders | `founders` | `text_input` |
| Brand Voice Notes | `brand_voice_notes` | `text_area` |

### 3. Compliance section (after Social Proof)

New section for legal/safety fields that were previously invisible in the UI:

| Field | DB Column | Input Type |
|-------|-----------|-----------|
| Prohibited Claims | `prohibited_claims` | `text_area` (one per line -> list) |
| Required Disclaimers | `required_disclaimers` | `text_area` (free text) |
| Banned Terms | `banned_terms` | `text_area` (one per line -> list) |

### UI Pattern

Both sections follow the existing "Edit Social Proof" toggle pattern:
1. Read-only display with `st.caption()` values
2. Toggle button to show/hide an `st.form()`
3. Form with Save/Cancel buttons
4. On save, calls `save_product_details()` and reruns

## What stayed the same

- Product Code input (already editable)
- Social Proof section (already editable)
- All other tabs (Offer Variants, Discover Variants, Amazon Insights, Variants, Images, Stats)
- No new files, services, or database migrations
