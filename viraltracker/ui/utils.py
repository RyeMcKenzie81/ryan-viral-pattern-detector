"""Shared UI utilities for Streamlit pages."""

import streamlit as st
from typing import Optional, Tuple


def get_brands():
    """Fetch brands from database."""
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("brands").select("id, name").order("name").execute()
    return result.data or []


def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("products").select("id, name").eq(
        "brand_id", brand_id
    ).order("name").execute()
    return result.data or []


def render_brand_selector(
    key: str = "brand_selector",
    show_label: bool = True,
    label: str = "Select Brand",
    include_product: bool = False,
    product_label: str = "Filter by Product (optional)",
    product_key: str = "product_selector"
) -> Optional[str] | Tuple[Optional[str], Optional[str]]:
    """
    Render a brand selector that persists across pages.

    Uses st.session_state.selected_brand_id to maintain selection
    when switching between pages in the same browser session.

    Args:
        key: Unique key for the brand selectbox widget
        show_label: Whether to show the label
        label: Label text for the selectbox
        include_product: If True, also render product selector and return tuple
        product_label: Label for product selector
        product_key: Unique key for product selectbox widget

    Returns:
        If include_product=False: Selected brand ID as string, or None
        If include_product=True: Tuple of (brand_id, product_id) or (None, None)
    """
    brands = get_brands()

    if not brands:
        st.warning("No brands found. Create a brand first.")
        if include_product:
            return None, None
        return None

    # Build options
    brand_options = {b['name']: b['id'] for b in brands}
    brand_names = list(brand_options.keys())

    # Find current index based on session state
    current_index = 0
    if st.session_state.get('selected_brand_id'):
        current_id = st.session_state.selected_brand_id
        for i, name in enumerate(brand_names):
            if brand_options[name] == current_id:
                current_index = i
                break

    # Render brand selector (with optional product in columns)
    if include_product:
        col1, col2 = st.columns(2)
        with col1:
            selected_name = st.selectbox(
                label if show_label else "",
                options=brand_names,
                index=current_index,
                key=key,
                label_visibility="visible" if show_label else "collapsed"
            )
    else:
        selected_name = st.selectbox(
            label if show_label else "",
            options=brand_names,
            index=current_index,
            key=key,
            label_visibility="visible" if show_label else "collapsed"
        )

    # Update session state
    selected_id = brand_options[selected_name]
    st.session_state.selected_brand_id = selected_id

    if not include_product:
        return selected_id

    # Product selector
    with col2:
        products = get_products_for_brand(selected_id)
        if products:
            product_options = {"All Products (Brand-level)": None}
            product_options.update({p["name"]: p["id"] for p in products})

            # Find current product index
            product_index = 0
            if st.session_state.get('selected_product_id'):
                current_prod = st.session_state.selected_product_id
                for i, (name, pid) in enumerate(product_options.items()):
                    if pid == current_prod:
                        product_index = i
                        break

            selected_product_name = st.selectbox(
                product_label,
                options=list(product_options.keys()),
                index=product_index,
                key=product_key,
                help="Select a product to filter analyses"
            )
            selected_product_id = product_options[selected_product_name]
            st.session_state.selected_product_id = selected_product_id
        else:
            st.info("No products defined yet")
            selected_product_id = None
            st.session_state.selected_product_id = None

    return selected_id, selected_product_id
