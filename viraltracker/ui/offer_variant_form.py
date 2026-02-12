"""
Shared Offer Variant Form - Reusable UI for creating/updating offer variants.

Used by:
- Brand Manager (manual creation + Discover Variants)
- Brand Research (Create Variant from landing page)
- URL Mapping (Create Variant from assigned URLs)

Also contains sync_url_to_landing_pages() with safe INSERT-only semantics.
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

import streamlit as st

from viraltracker.core.database import get_supabase_client
from viraltracker.services.product_offer_variant_service import ProductOfferVariantService

logger = logging.getLogger(__name__)


def sync_url_to_landing_pages(brand_id: str, url: str, product_id: str = None) -> bool:
    """Ensure a URL exists in brand_landing_pages for scraping/analysis.

    INSERT-only semantics for scrape_status: only set 'pending' on new rows.
    Never overwrites product_id with NULL. Populates canonical_url on write.
    """
    from viraltracker.services.url_canonicalizer import canonicalize_url

    try:
        db = get_supabase_client()
        canonical = canonicalize_url(url)

        existing = db.table("brand_landing_pages").select(
            "id, product_id, scrape_status, canonical_url"
        ).eq("brand_id", brand_id).eq("url", url).limit(1).execute()

        if existing.data:
            row = existing.data[0]
            updates = {}
            if product_id and not row.get("product_id"):
                updates["product_id"] = product_id
            if not row.get("canonical_url"):
                updates["canonical_url"] = canonical
            if updates:
                db.table("brand_landing_pages").update(updates).eq("id", row["id"]).execute()
            return True
        else:
            record = {
                "brand_id": brand_id,
                "url": url,
                "canonical_url": canonical,
                "scrape_status": "pending",
            }
            if product_id:
                record["product_id"] = product_id
            db.table("brand_landing_pages").insert(record).execute()
            return True

    except Exception as e:
        logger.error(f"Failed to sync URL to landing pages: {e}")
        return False


def render_offer_variant_review_form(
    extracted_data: Dict[str, Any],
    product_id: Optional[str],
    brand_id: str,
    form_key: str,
    products: Optional[List[Dict]] = None,
    show_product_selector: bool = False,
    mode: str = "create_or_update",
) -> Optional[Dict[str, Any]]:
    """Render review/edit form for creating/updating an offer variant.

    Args:
        extracted_data: Pre-populated field values (from extraction/analysis)
        product_id: Product UUID string, or None if unknown
        brand_id: Brand UUID string
        form_key: Unique key for Streamlit widgets
        products: List of product dicts for selector (needed if show_product_selector)
        show_product_selector: Whether to show product dropdown
        mode: "create_or_update" checks for existing variant by URL, "create_only" always creates

    Returns:
        {variant_id: str, was_created: bool} if saved, None if not yet submitted.
    """
    resolved_product_id = product_id

    # Product selector if needed
    if show_product_selector and products:
        product_options = {p["name"]: p["id"] for p in products}
        if not product_options:
            st.warning("No products found. Create a product first.")
            return None
        selected_name = st.selectbox(
            "Select Product",
            options=list(product_options.keys()),
            key=f"{form_key}_product",
        )
        resolved_product_id = product_options.get(selected_name)

    if not resolved_product_id:
        st.warning("A product must be selected to create an offer variant.")
        return None

    st.markdown("**Review & Edit Extracted Data**")

    # Variant name
    variant_name = st.text_input(
        "Variant Name",
        value=extracted_data.get("name", ""),
        key=f"{form_key}_name",
        help="Short name for this offer angle",
    )

    # Target audience
    target_audience = st.text_area(
        "Target Audience",
        value=extracted_data.get("target_audience", ""),
        key=f"{form_key}_target",
        height=80,
    )

    # Two-column layout for lists
    col_left, col_right = st.columns(2)

    with col_left:
        pain_text = st.text_area(
            "Pain Points (one per line)",
            value="\n".join(extracted_data.get("pain_points", [])),
            key=f"{form_key}_pain",
            height=120,
        )
        benefits_text = st.text_area(
            "Benefits (one per line)",
            value="\n".join(extracted_data.get("benefits", [])),
            key=f"{form_key}_benefits",
            height=120,
        )

    with col_right:
        desires_text = st.text_area(
            "Desires / Goals (one per line)",
            value="\n".join(extracted_data.get("desires_goals", [])),
            key=f"{form_key}_desires",
            height=120,
        )
        disallowed_text = st.text_area(
            "Disallowed Claims (one per line)",
            value="\n".join(extracted_data.get("disallowed_claims", [])),
            key=f"{form_key}_disallowed",
            height=120,
        )

    # Collapsible mechanism section
    with st.expander("Mechanism & Hooks", expanded=False):
        mechanism_name = st.text_input(
            "Mechanism Name",
            value=extracted_data.get("mechanism_name", ""),
            key=f"{form_key}_mech_name",
        )
        mechanism_problem = st.text_input(
            "Problem (UMP)",
            value=extracted_data.get("mechanism_problem", ""),
            key=f"{form_key}_mech_problem",
        )
        mechanism_solution = st.text_input(
            "Solution (UMS)",
            value=extracted_data.get("mechanism_solution", ""),
            key=f"{form_key}_mech_solution",
        )
        hooks_text = st.text_area(
            "Sample Hooks (one per line)",
            value="\n".join(extracted_data.get("sample_hooks", [])),
            key=f"{form_key}_hooks",
            height=100,
        )
        disclaimers = st.text_area(
            "Required Disclaimers",
            value=extracted_data.get("required_disclaimers", ""),
            key=f"{form_key}_disclaimers",
            height=60,
        )

    is_default = st.checkbox(
        "Set as default variant",
        value=False,
        key=f"{form_key}_default",
    )

    # Check for existing variant to set button label
    landing_page_url = extracted_data.get("landing_page_url", "")
    button_label = "Save Offer Variant"
    if mode == "create_or_update" and landing_page_url and resolved_product_id:
        try:
            db = get_supabase_client()
            existing = db.table("product_offer_variants").select("id").eq(
                "product_id", resolved_product_id
            ).eq("landing_page_url", landing_page_url).limit(1).execute()
            if existing.data:
                button_label = "Update Offer Variant"
        except Exception:
            pass

    if st.button(f"✅ {button_label}", key=f"{form_key}_save", type="primary"):
        if not variant_name:
            st.error("Please enter a variant name.")
            return None

        # Parse text areas into lists
        pain_list = [p.strip() for p in pain_text.split("\n") if p.strip()]
        benefits_list = [b.strip() for b in benefits_text.split("\n") if b.strip()]
        desires_list = [d.strip() for d in desires_text.split("\n") if d.strip()]
        disallowed_list = [c.strip() for c in disallowed_text.split("\n") if c.strip()]
        hooks_list = [h.strip() for h in hooks_text.split("\n") if h.strip()]

        with st.spinner("Saving offer variant..."):
            try:
                ov_service = ProductOfferVariantService()
                kwargs = dict(
                    name=variant_name,
                    pain_points=pain_list,
                    desires_goals=desires_list,
                    benefits=benefits_list,
                    target_audience=target_audience if target_audience else None,
                    disallowed_claims=disallowed_list if disallowed_list else None,
                    required_disclaimers=disclaimers if disclaimers else None,
                    is_default=is_default,
                    mechanism_name=mechanism_name if mechanism_name else None,
                    mechanism_problem=mechanism_problem if mechanism_problem else None,
                    mechanism_solution=mechanism_solution if mechanism_solution else None,
                    sample_hooks=hooks_list if hooks_list else None,
                    source=extracted_data.get("source"),
                    source_metadata=extracted_data.get("source_metadata"),
                )

                if mode == "create_or_update" and landing_page_url:
                    variant_id, was_created = ov_service.create_or_update_offer_variant(
                        product_id=UUID(resolved_product_id),
                        landing_page_url=landing_page_url,
                        **kwargs,
                    )
                else:
                    variant_id = ov_service.create_offer_variant(
                        product_id=UUID(resolved_product_id),
                        landing_page_url=landing_page_url,
                        **kwargs,
                    )
                    was_created = True

                # Sync URL to landing pages (safe version)
                if landing_page_url:
                    sync_url_to_landing_pages(brand_id, landing_page_url, resolved_product_id)

                action = "Created" if was_created else "Updated"
                st.success(f"{action} offer variant: **{variant_name}**")
                return {"variant_id": str(variant_id), "was_created": was_created}

            except Exception as e:
                st.error(f"Failed to save offer variant: {e}")
                logger.error(f"Failed to save offer variant: {e}")
                return None

    return None
