"""
Brand Manager - Central hub for managing brands, products, and images.

This page allows users to:
- View and edit brand settings (colors, fonts, guidelines)
- Manage products under each brand
- View product images with analysis status
- Trigger image analysis for smart auto-selection
- Quick access to hooks and ad history
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID

# Apply nest_asyncio for Streamlit compatibility (allows nested event loops)
import nest_asyncio
nest_asyncio.apply()

# Page config
st.set_page_config(
    page_title="Brand Manager",
    page_icon="🏢",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'expanded_product_id' not in st.session_state:
    st.session_state.expanded_product_id = None
if 'analyzing_image' not in st.session_state:
    st.session_state.analyzing_image = None
if 'scraping_ads' not in st.session_state:
    st.session_state.scraping_ads = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("*").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch all products for a brand with images and variants from product_images table."""
    try:
        db = get_supabase_client()
        result = db.table("products").select(
            "*, product_images(id, storage_path, image_analysis, analyzed_at, notes, is_main), product_variants(id, name, slug, variant_type, description, is_default, is_active, display_order)"
        ).eq("brand_id", brand_id).order("name").execute()

        # Supported image formats for Vision AI analysis
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

        # Add file type info to images
        for product in result.data:
            images = list(product.get('product_images') or [])

            # Sort: main image first, then by storage_path
            images.sort(key=lambda x: (not x.get('is_main', False), x.get('storage_path', '')))

            for img in images:
                path = img.get('storage_path', '').lower()
                img['is_image'] = path.endswith(image_extensions)
                img['is_pdf'] = path.endswith('.pdf')
                img['file_type'] = 'pdf' if img['is_pdf'] else 'image' if img['is_image'] else 'other'

            product['product_images'] = images

            # Sort variants by display_order, then name
            variants = list(product.get('product_variants') or [])
            variants.sort(key=lambda x: (x.get('display_order', 0), x.get('name', '')))
            product['product_variants'] = variants

        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_variants_for_product(product_id: str):
    """Fetch all variants for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_variants").select("*").eq(
            "product_id", product_id
        ).order("display_order").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch variants: {e}")
        return []


def create_variant(product_id: str, name: str, variant_type: str = "flavor",
                   description: str = None, is_default: bool = False) -> bool:
    """Create a new product variant."""
    try:
        db = get_supabase_client()
        slug = name.lower().replace(" ", "-").replace("'", "")

        # Get current max display_order
        existing = db.table("product_variants").select("display_order").eq(
            "product_id", product_id
        ).order("display_order", desc=True).limit(1).execute()

        next_order = (existing.data[0]['display_order'] + 1) if existing.data else 0

        db.table("product_variants").insert({
            "product_id": product_id,
            "name": name,
            "slug": slug,
            "variant_type": variant_type,
            "description": description,
            "is_default": is_default,
            "is_active": True,
            "display_order": next_order
        }).execute()
        return True
    except Exception as e:
        st.error(f"Failed to create variant: {e}")
        return False


def update_variant(variant_id: str, updates: dict) -> bool:
    """Update a product variant."""
    try:
        db = get_supabase_client()
        db.table("product_variants").update(updates).eq("id", variant_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to update variant: {e}")
        return False


def delete_variant(variant_id: str) -> bool:
    """Delete a product variant."""
    try:
        db = get_supabase_client()
        db.table("product_variants").delete().eq("id", variant_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to delete variant: {e}")
        return False


def get_hooks_count(product_id: str) -> int:
    """Get count of hooks for a product."""
    try:
        db = get_supabase_client()
        result = db.table("hooks").select("id", count="exact").eq("product_id", product_id).execute()
        return result.count or 0
    except:
        return 0


def get_ad_runs_stats(product_id: str) -> dict:
    """Get ad run statistics for a product."""
    try:
        db = get_supabase_client()
        runs = db.table("ad_runs").select("id").eq("product_id", product_id).execute()
        run_count = len(runs.data)

        if run_count == 0:
            return {"runs": 0, "ads": 0, "approved": 0}

        run_ids = [r['id'] for r in runs.data]
        ads = db.table("generated_ads").select("id, final_status").in_("ad_run_id", run_ids).execute()

        total_ads = len(ads.data)
        approved = len([a for a in ads.data if a.get('final_status') == 'approved'])

        return {"runs": run_count, "ads": total_ads, "approved": approved}
    except:
        return {"runs": 0, "ads": 0, "approved": 0}


def get_offer_variants_for_product(product_id: str) -> list:
    """Get offer variants (landing page angles) for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_offer_variants").select("*").eq(
            "product_id", product_id
        ).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch offer variants: {e}")
        return []


def sync_url_to_landing_pages(brand_id: str, url: str, product_id: str = None) -> bool:
    """Sync a URL to brand_landing_pages for scraping/analysis.

    Auto-syncs offer variant URLs so they appear in Brand Research landing pages.
    Uses upsert to avoid duplicates.
    """
    try:
        db = get_supabase_client()
        record = {
            "brand_id": brand_id,
            "url": url,
            "product_id": product_id,
            "scrape_status": "pending"
        }
        # Upsert to avoid duplicates (url + brand_id should be unique)
        db.table("brand_landing_pages").upsert(
            record,
            on_conflict="brand_id,url"
        ).execute()
        return True
    except Exception as e:
        # Log but don't fail - this is a background sync
        import logging
        logging.warning(f"Failed to sync URL to landing pages: {e}")
        return False


def get_offer_variant_images(offer_variant_id: str) -> list:
    """Get images associated with an offer variant via junction table."""
    try:
        db = get_supabase_client()
        # Join offer_variant_images with product_images
        result = db.table("offer_variant_images").select(
            "*, product_images(*)"
        ).eq("offer_variant_id", offer_variant_id).order("display_order").execute()
        return result.data or []
    except Exception:
        return []


def scrape_and_save_offer_variant_images(product_id: str, offer_variant_id: str, url: str) -> dict:
    """Scrape images from landing page and associate with offer variant.

    Returns dict with 'success', 'new_count', 'total_count', 'error'.
    """
    import requests
    import hashlib
    from viraltracker.services.web_scraping_service import WebScrapingService

    try:
        db = get_supabase_client()

        # 1. Scrape image URLs from landing page
        scraper = WebScrapingService()
        image_urls = scraper.extract_product_images(url, max_images=15)

        if not image_urls:
            return {"success": False, "error": "No images found on landing page", "new_count": 0, "total_count": 0}

        new_count = 0
        for idx, img_url in enumerate(image_urls):
            try:
                # 2. Download image
                resp = requests.get(img_url, timeout=15)
                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get('content-type', 'image/jpeg')
                if 'png' in content_type:
                    ext = 'png'
                elif 'webp' in content_type:
                    ext = 'webp'
                else:
                    ext = 'jpg'

                # Generate unique filename based on URL hash
                url_hash = hashlib.md5(img_url.encode()).hexdigest()[:12]
                filename = f"ov_{offer_variant_id[:8]}_{url_hash}.{ext}"
                storage_path = f"{product_id}/{filename}"
                full_storage_path = f"product-images/{storage_path}"

                # 3. Check if image already exists (by storage_path)
                existing = db.table("product_images").select("id").eq(
                    "storage_path", full_storage_path
                ).execute()

                if existing.data:
                    # Image exists, just create junction if not exists
                    image_id = existing.data[0]['id']
                else:
                    # Upload to storage
                    db.storage.from_("product-images").upload(
                        storage_path,
                        resp.content,
                        {"content-type": content_type, "upsert": "true"}
                    )

                    # Create product_images record
                    img_record = db.table("product_images").insert({
                        "product_id": product_id,
                        "storage_path": full_storage_path,
                        "filename": filename,
                        "is_main": False,
                        "sort_order": idx
                    }).execute()
                    image_id = img_record.data[0]['id']
                    new_count += 1

                # 4. Create junction record (upsert to handle duplicates)
                db.table("offer_variant_images").upsert({
                    "offer_variant_id": offer_variant_id,
                    "product_image_id": image_id,
                    "display_order": idx
                }, on_conflict="offer_variant_id,product_image_id").execute()

            except Exception as e:
                # Skip individual image errors, continue with others
                continue

        return {
            "success": True,
            "new_count": new_count,
            "total_count": len(image_urls),
            "error": None
        }

    except Exception as e:
        return {"success": False, "error": str(e), "new_count": 0, "total_count": 0}


def get_amazon_analysis_for_product(product_id: str) -> dict:
    """Get Amazon review analysis for a product."""
    try:
        db = get_supabase_client()
        result = db.table("amazon_review_analysis").select("*").eq(
            "product_id", product_id
        ).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        st.error(f"Failed to fetch Amazon analysis: {e}")
        return {}


def get_signed_url(storage_path: str, expiry: int = 3600) -> str:
    """Get signed URL for storage path."""
    if not storage_path:
        return ""
    try:
        db = get_supabase_client()
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            return ""
        result = db.storage.from_(bucket).create_signed_url(path, expiry)
        return result.get('signedURL', '')
    except:
        return ""


async def analyze_image(image_path: str) -> dict:
    """Run image analysis using the agent tool."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.ad_creation_agent import analyze_product_image
    from viraltracker.agent.dependencies import AgentDependencies

    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    return await analyze_product_image(ctx=ctx, image_storage_path=image_path)


def save_product_social_proof(product_id: str, review_platforms: dict, media_features: list, awards_certifications: list):
    """Save social proof data for a product."""
    try:
        db = get_supabase_client()
        db.table("products").update({
            "review_platforms": review_platforms,
            "media_features": media_features,
            "awards_certifications": awards_certifications
        }).eq("id", product_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save social proof: {e}")
        return False


def save_image_analysis(image_id: str, analysis: dict):
    """Save analysis to product_images table."""
    try:
        db = get_supabase_client()
        db.table("product_images").update({
            "image_analysis": analysis,
            "analyzed_at": datetime.utcnow().isoformat(),
            "analysis_model": analysis.get("analysis_model"),
            "analysis_version": analysis.get("analysis_version")
        }).eq("id", image_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save analysis: {e}")
        return False


def save_image_notes(image_id: str, notes: str):
    """Save notes for an image."""
    try:
        db = get_supabase_client()
        db.table("product_images").update({
            "notes": notes
        }).eq("id", image_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save notes: {e}")
        return False


def save_brand_code(brand_id: str, brand_code: str) -> bool:
    """Save brand_code for a brand (used in ad filenames)."""
    try:
        db = get_supabase_client()
        # Validate: max 4 chars, uppercase
        code = brand_code.strip().upper()[:4] if brand_code else None
        db.table("brands").update({"brand_code": code}).eq("id", brand_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save brand code: {e}")
        return False


def save_product_code(product_id: str, product_code: str) -> bool:
    """Save product_code for a product (used in ad filenames)."""
    try:
        db = get_supabase_client()
        # Validate: max 4 chars, uppercase
        code = product_code.strip().upper()[:4] if product_code else None
        db.table("products").update({"product_code": code}).eq("id", product_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save product code: {e}")
        return False


def get_brand_ads_for_grouping(brand_id: str) -> list:
    """Fetch brand's scraped ads for URL grouping."""
    db = get_supabase_client()
    result = db.table("brand_facebook_ads").select(
        "facebook_ads(id, ad_archive_id, snapshot)"
    ).eq("brand_id", brand_id).execute()

    ads = []
    for r in (result.data or []):
        if r.get('facebook_ads'):
            ads.append(r['facebook_ads'])
    return ads


def render_offer_variant_discovery(brand_id: str, product_id: str, product_name: str):
    """Render offer variant discovery UI for a product."""
    import json
    import asyncio

    st.markdown("#### Discover Offer Variants from Ads")
    st.caption("Analyze your scraped Facebook ads to auto-discover landing pages and extract messaging.")

    # Check for ads
    ads = get_brand_ads_for_grouping(brand_id)
    if not ads:
        st.info("No ads scraped yet. Use 'Scrape Ads' in the Facebook Ad Library section above.")
        return

    st.success(f"Found {len(ads)} scraped ads")

    # Session state for URL groups
    session_key = f"brand_url_groups_{brand_id}"

    # Group ads button
    if st.button("Group Ads by Landing Page", key=f"group_ads_{product_id}"):
        from viraltracker.services.ad_analysis_service import AdAnalysisService
        ad_service = AdAnalysisService()

        # Convert to format expected by group_ads_by_url
        ads_list = []
        for ad in ads:
            snapshot = ad.get('snapshot', {})
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            ads_list.append({
                'id': ad['id'],
                'ad_archive_id': ad.get('ad_archive_id'),
                'snapshot': snapshot
            })

        url_groups = ad_service.group_ads_by_url(ads_list)
        st.session_state[session_key] = [
            {
                "normalized_url": g.normalized_url,
                "display_url": g.display_url,
                "ad_count": g.ad_count,
                "preview_text": g.preview_text,
                "preview_image_url": g.preview_image_url,
                "ads": g.ads,
                "status": "pending"
            }
            for g in url_groups
        ]
        st.rerun()

    # Display URL groups
    url_groups = st.session_state.get(session_key, [])
    if url_groups:
        render_url_groups_for_brand(url_groups, product_id, brand_id, session_key)


def render_url_groups_for_brand(url_groups: list, product_id: str, brand_id: str, session_key: str):
    """Display URL groups with checkboxes and merge capability."""
    import json
    import asyncio
    import time

    # Selection state key for this brand+product combo
    selection_key = f"selected_brand_groups_{brand_id}_{product_id}"
    if selection_key not in st.session_state:
        st.session_state[selection_key] = set()

    # Get pending vs done/merged groups
    pending_indices = [i for i, g in enumerate(url_groups) if g.get('status') == 'pending']
    done_count = len([g for g in url_groups if g.get('status') == 'done'])
    merged_count = len([g for g in url_groups if g.get('status') == 'merged'])

    st.markdown(f"### Discovered Landing Pages ({len(url_groups)} total)")
    st.caption("Analyze each landing page individually, or **select multiple to merge into one variant.**")

    if done_count > 0:
        st.success(f"✅ {done_count} variant(s) created")
    if merged_count > 0:
        st.info(f"🔀 {merged_count} group(s) merged")

    # Sync checkbox states to selection set BEFORE checking for merge button
    for idx in pending_indices:
        checkbox_key = f"select_brand_group_{brand_id}_{product_id}_{idx}"
        if checkbox_key in st.session_state:
            if st.session_state[checkbox_key]:
                st.session_state[selection_key].add(idx)
            else:
                st.session_state[selection_key].discard(idx)

    # Show merge button if 2+ pending groups are selected
    selected = st.session_state[selection_key]
    selected_pending = [i for i in selected if i in pending_indices]

    if len(selected_pending) >= 2:
        total_ads = sum(url_groups[i]["ad_count"] for i in selected_pending)
        merge_col1, merge_col2 = st.columns([2, 1])
        with merge_col1:
            if st.button(
                f"🔀 Merge & Analyze Selected ({len(selected_pending)} groups, {total_ads} ads)",
                type="primary",
                key=f"merge_brand_{brand_id}_{product_id}"
            ):
                _analyze_merged_groups_for_brand(
                    url_groups, list(selected_pending), product_id, brand_id, session_key, selection_key
                )
        with merge_col2:
            if st.button("Clear Selection", key=f"clear_brand_sel_{brand_id}_{product_id}"):
                st.session_state[selection_key] = set()
                for idx in pending_indices:
                    checkbox_key = f"select_brand_group_{brand_id}_{product_id}_{idx}"
                    if checkbox_key in st.session_state:
                        st.session_state[checkbox_key] = False
                st.rerun()
        st.markdown("---")

    # Render each group
    for i, group in enumerate(url_groups):
        status = group.get('status', 'pending')
        status_icon = {"pending": "⏳", "done": "✅", "merged": "🔀"}.get(status, "⏳")
        display_url = group['display_url'] or group['normalized_url']

        with st.expander(
            f"{status_icon} {display_url[:60]}{'...' if len(display_url) > 60 else ''} ({group['ad_count']} ads)",
            expanded=(status == "pending")
        ):
            if status == "pending":
                # Checkbox row for pending items
                check_col, content_col = st.columns([0.5, 5.5])
                with check_col:
                    checkbox_key = f"select_brand_group_{brand_id}_{product_id}_{i}"
                    if checkbox_key not in st.session_state:
                        st.session_state[checkbox_key] = i in st.session_state[selection_key]
                    st.checkbox("", key=checkbox_key, label_visibility="collapsed")

                with content_col:
                    if group.get('preview_text'):
                        st.caption(f"*{group['preview_text'][:200]}{'...' if len(group.get('preview_text', '')) > 200 else ''}*")
                    if group.get('preview_image_url'):
                        try:
                            st.image(group['preview_image_url'], width=200)
                        except:
                            pass

                # Action buttons
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("🔬 Analyze & Create Variant", key=f"analyze_{product_id}_{i}", type="primary"):
                        with st.spinner("Analyzing ads... This may take a minute."):
                            try:
                                from viraltracker.services.ad_analysis_service import AdAnalysisService, AdGroup
                                ad_service = AdAnalysisService()

                                ad_group = AdGroup(
                                    normalized_url=group['normalized_url'],
                                    display_url=group['display_url'],
                                    ad_count=group['ad_count'],
                                    ads=group['ads'],
                                    preview_text=group.get('preview_text'),
                                    preview_image_url=group.get('preview_image_url')
                                )

                                analyses = asyncio.run(ad_service.analyze_ad_group(ad_group, max_ads=10))
                                synthesis = ad_service.synthesize_messaging(analyses)

                                db = get_supabase_client()
                                suggested_name = synthesis.get("suggested_name", f"Variant from {display_url[:30]}")
                                variant_data = {
                                    "product_id": product_id,
                                    "name": suggested_name,
                                    "slug": suggested_name.lower().replace(" ", "-").replace("/", "-")[:50],
                                    "landing_page_url": display_url,
                                    "pain_points": synthesis.get("pain_points", []),
                                    "desires_goals": synthesis.get("desires_goals", []),
                                    "benefits": synthesis.get("benefits", []),
                                    "mechanism_name": synthesis.get("mechanism_name"),
                                    "mechanism_problem": synthesis.get("mechanism_problem"),
                                    "mechanism_solution": synthesis.get("mechanism_solution"),
                                    "sample_hooks": synthesis.get("sample_hooks", []),
                                    "source_metadata": {
                                        "source": "ad_analysis",
                                        "ad_count": synthesis.get("analyzed_count", 0),
                                        "source_ad_ids": synthesis.get("source_ad_ids", [])
                                    }
                                }
                                # Use upsert to update existing variant if URL already exists
                                db.table("product_offer_variants").upsert(
                                    variant_data,
                                    on_conflict="product_id,landing_page_url"
                                ).execute()

                                # Auto-sync URL to landing pages for Brand Research
                                sync_url_to_landing_pages(brand_id, display_url, product_id)

                                st.session_state[session_key][i]['status'] = 'done'
                                st.session_state[session_key][i]['variant_name'] = suggested_name
                                st.success(f"✅ Created offer variant: **{suggested_name}**")
                                st.rerun()

                            except Exception as e:
                                st.error(f"Analysis failed: {e}")

                with btn_col2:
                    if st.button("⏭️ Skip", key=f"skip_{product_id}_{i}"):
                        st.session_state[session_key][i]['status'] = 'done'
                        st.rerun()

            elif status == "done":
                st.success("✅ Variant created")
                if group.get('variant_name'):
                    st.caption(f"Variant: {group['variant_name']}")

            elif status == "merged":
                merged_into = group.get("merged_into_variant", "Unknown")
                merge_col1, merge_col2 = st.columns([4, 1])
                with merge_col1:
                    st.info(f"🔀 Merged into variant: **{merged_into}**")
                with merge_col2:
                    if st.button("🔄 Reset", key=f"reset_brand_merged_{product_id}_{i}"):
                        st.session_state[session_key][i]['status'] = 'pending'
                        st.session_state[session_key][i].pop('merged_into_variant', None)
                        st.rerun()


def _analyze_merged_groups_for_brand(
    url_groups: list,
    group_indices: list,
    product_id: str,
    brand_id: str,
    session_key: str,
    selection_key: str
):
    """Analyze multiple URL groups together and create a single merged variant."""
    import asyncio
    import time
    from viraltracker.services.ad_analysis_service import AdAnalysisService, AdGroup

    # Combine all ads from selected groups
    all_ads = []
    all_urls = []
    total_ad_count = 0

    for idx in group_indices:
        group_data = url_groups[idx]
        all_ads.extend(group_data.get("ads", []))
        all_urls.append(group_data["display_url"] or group_data["normalized_url"])
        total_ad_count += group_data["ad_count"]

    # Use URL with most ads as primary
    primary_idx = max(group_indices, key=lambda i: url_groups[i]["ad_count"])
    primary_group = url_groups[primary_idx]
    primary_url = primary_group["display_url"] or primary_group["normalized_url"]

    merged_group = AdGroup(
        normalized_url=primary_group["normalized_url"],
        display_url=primary_url,
        ad_count=total_ad_count,
        ads=all_ads,
        preview_text=primary_group.get("preview_text"),
        preview_image_url=primary_group.get("preview_image_url"),
    )

    max_ads_to_analyze = min(100, total_ad_count)

    st.info(f"🔄 Analyzing up to {max_ads_to_analyze} ads from {len(group_indices)} URL groups...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        ad_service = AdAnalysisService()

        def progress_callback(current: int, total: int, status: str):
            progress = current / total if total > 0 else 0
            progress_bar.progress(progress)
            status_text.text(f"📊 {status} ({current}/{total})")

        synthesis = asyncio.run(
            ad_service.analyze_and_synthesize(
                merged_group,
                max_ads=max_ads_to_analyze,
                progress_callback=progress_callback,
            )
        )

        progress_bar.progress(1.0)
        status_text.text(f"✅ Analysis complete! Processed {synthesis.get('analyzed_count', 0)} ads.")

        # Infer variant name
        variant_name = _infer_merged_variant_name_brand(all_urls, synthesis)

        # Mark all selected groups as merged
        for idx in group_indices:
            st.session_state[session_key][idx]["status"] = "merged"
            st.session_state[session_key][idx]["merged_into_variant"] = variant_name

        # Create offer variant in database
        db = get_supabase_client()
        variant_data = {
            "product_id": product_id,
            "name": variant_name,
            "slug": variant_name.lower().replace(" ", "-").replace("/", "-")[:50],
            "landing_page_url": primary_url,
            "pain_points": synthesis.get("pain_points", []),
            "desires_goals": synthesis.get("desires_goals", []),
            "benefits": synthesis.get("benefits", []),
            "mechanism_name": synthesis.get("mechanism_name"),
            "mechanism_problem": synthesis.get("mechanism_problem"),
            "mechanism_solution": synthesis.get("mechanism_solution"),
            "sample_hooks": synthesis.get("sample_hooks", []),
            "source_metadata": {
                "source": "ad_analysis_merged",
                "ad_count": synthesis.get("analyzed_count", 0),
                "source_urls": all_urls,
                "source_ad_ids": synthesis.get("source_ad_ids", [])
            }
        }
        db.table("product_offer_variants").insert(variant_data).execute()

        # Auto-sync all URLs to landing pages for Brand Research
        for url in all_urls:
            sync_url_to_landing_pages(brand_id, url, product_id)

        # Clear selection
        st.session_state[selection_key] = set()

        st.success(f"✅ Created merged variant: **{variant_name}** from {len(group_indices)} landing pages")
        time.sleep(1)
        st.rerun()

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Merged analysis failed: {e}")


def _infer_merged_variant_name_brand(urls: list, synthesis: dict) -> str:
    """Infer variant name from merged URLs."""
    url_parts = [url.lower().split("/")[-1].replace("-", " ") for url in urls]

    if url_parts:
        first_words = set(url_parts[0].split())
        for url_part in url_parts[1:]:
            first_words &= set(url_part.split())

        generic = {"pages", "page", "com", "www", "https", "http", "support", "for", "the", "a", "an"}
        common_terms = [w for w in first_words if w not in generic and len(w) > 2]

        if common_terms:
            name_base = " ".join(sorted(common_terms, key=len, reverse=True)[:3])
            return f"{name_base.title()} Angle"

    if synthesis.get("suggested_name"):
        return synthesis["suggested_name"]
    if synthesis.get("benefits"):
        return f"{synthesis['benefits'][0][:30]} Angle"

    return "Merged Ad Analysis Variant"


def format_color_swatch(hex_color: str, name: str = None) -> str:
    """Create HTML for a color swatch."""
    label = f" {name}" if name else ""
    return f'<span style="display:inline-block;width:20px;height:20px;background:{hex_color};border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin-right:5px;"></span><code>{hex_color}</code>{label}'


def scrape_facebook_ads(ad_library_url: str, brand_id: str, max_ads: int = 100) -> dict:
    """
    Scrape ads from Facebook Ad Library and save to database.

    Args:
        ad_library_url: Facebook Ad Library URL to scrape
        brand_id: Brand UUID to link ads to
        max_ads: Maximum number of ads to scrape

    Returns:
        Dict with results: {"success": bool, "count": int, "message": str}
    """
    try:
        from viraltracker.scrapers.facebook_ads import FacebookAdsScraper

        scraper = FacebookAdsScraper()

        # Scrape ads from Ad Library
        df = scraper.search_ad_library(
            search_url=ad_library_url,
            count=max_ads,
            scrape_details=False,
            timeout=900  # 15 min timeout for large scrapes
        )

        if len(df) == 0:
            return {"success": True, "count": 0, "message": "No ads found at this URL"}

        # Save to database linked to brand
        saved_ids = scraper.save_ads_to_db(df, brand_id=brand_id)

        return {
            "success": True,
            "count": len(saved_ids),
            "message": f"Successfully scraped and saved {len(saved_ids)} ads"
        }

    except Exception as e:
        return {"success": False, "count": 0, "message": str(e)}


# ============================================================================
# MAIN UI
# ============================================================================

st.title("🏢 Brand Manager")
st.markdown("Manage brands, products, images, and hooks in one place.")

st.divider()

# Brand selector (uses shared utility for cross-page persistence)
from viraltracker.ui.utils import render_brand_selector

col_brand, col_spacer = st.columns([2, 3])
with col_brand:
    selected_brand_id = render_brand_selector(key="brand_manager_brand_selector")

if not selected_brand_id:
    st.stop()

# Get selected brand data
brands = get_brands()
selected_brand = next((b for b in brands if b['id'] == selected_brand_id), None)

if not selected_brand:
    st.error("Brand not found")
    st.stop()

# ============================================================================
# BRAND SETTINGS SECTION
# ============================================================================

st.subheader("Brand Settings")

with st.container():
    # Brand Code (for ad filenames)
    col_code, col_code_spacer = st.columns([1, 3])
    with col_code:
        current_brand_code = selected_brand.get('brand_code') or ''
        new_brand_code = st.text_input(
            "Brand Code",
            value=current_brand_code,
            max_chars=4,
            placeholder="e.g., WP",
            help="2-4 character code used in ad filenames (e.g., WP for WonderPaws)"
        )
        if new_brand_code.upper() != current_brand_code.upper():
            if st.button("Save Code", key="save_brand_code", type="primary"):
                if save_brand_code(selected_brand_id, new_brand_code):
                    st.success("Brand code saved!")
                    st.rerun()

    st.markdown("")  # Spacer

    col1, col2 = st.columns(2)

    with col1:
        # Brand Colors
        st.markdown("**Colors**")
        brand_colors = selected_brand.get('brand_colors') or {}

        if brand_colors:
            colors_html = ""
            if brand_colors.get('primary'):
                colors_html += format_color_swatch(
                    brand_colors['primary'],
                    brand_colors.get('primary_name', 'Primary')
                ) + "<br>"
            if brand_colors.get('secondary'):
                colors_html += format_color_swatch(
                    brand_colors['secondary'],
                    brand_colors.get('secondary_name', 'Secondary')
                ) + "<br>"
            if brand_colors.get('background'):
                colors_html += format_color_swatch(
                    brand_colors['background'],
                    brand_colors.get('background_name', 'Background')
                )

            st.markdown(colors_html, unsafe_allow_html=True)
        else:
            st.caption("No brand colors configured")

    with col2:
        # Brand Fonts
        st.markdown("**Fonts**")
        brand_fonts = selected_brand.get('brand_fonts') or {}

        if brand_fonts:
            if brand_fonts.get('primary'):
                weights = brand_fonts.get('primary_weights', [])
                weight_str = f" ({', '.join(weights)})" if weights else ""
                st.markdown(f"Primary: **{brand_fonts['primary']}**{weight_str}")
            if brand_fonts.get('secondary'):
                st.markdown(f"Secondary: **{brand_fonts['secondary']}**")
        else:
            st.caption("No brand fonts configured")

    # Brand Guidelines
    if selected_brand.get('brand_guidelines'):
        with st.expander("Brand Guidelines"):
            st.markdown(selected_brand['brand_guidelines'])

    # Ad Creation Notes Section
    st.markdown("")  # Spacer
    st.markdown("**Ad Creation Notes**")
    st.caption("Default instructions for ad generation (e.g., 'white backdrops work best', 'always show product in use')")

    current_ad_creation_notes = selected_brand.get('ad_creation_notes') or ""
    new_ad_creation_notes = st.text_area(
        "Ad Creation Notes",
        value=current_ad_creation_notes,
        placeholder="Enter default instructions for ad generation...\n\nExamples:\n- White backdrops work best for this brand\n- Always feature the product prominently\n- Use lifestyle imagery when possible",
        height=120,
        key="brand_ad_creation_notes",
        label_visibility="collapsed"
    )

    if new_ad_creation_notes != current_ad_creation_notes:
        if st.button("Save Ad Creation Notes", key="save_ad_creation_notes", type="secondary"):
            try:
                db = get_supabase_client()
                db.table("brands").update({
                    "ad_creation_notes": new_ad_creation_notes
                }).eq("id", selected_brand_id).execute()
                st.success("Ad creation notes saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

    # Facebook Ad Library Section
    st.markdown("")  # Spacer
    st.markdown("**Facebook Ad Library**")

    current_ad_library_url = selected_brand.get('ad_library_url') or ""
    current_page_id = selected_brand.get('facebook_page_id') or ""

    new_ad_library_url = st.text_input(
        "Ad Library URL",
        value=current_ad_library_url,
        placeholder="https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=YOUR_PAGE_ID",
        help="Full Facebook Ad Library URL for scraping your brand's ads",
        key="brand_ad_library_url"
    )

    col_save, col_media, col_count, col_scrape = st.columns([1, 1, 1, 1])

    with col_save:
        if new_ad_library_url != current_ad_library_url:
            if st.button("Save URL", key="save_ad_library_url", type="secondary"):
                try:
                    db = get_supabase_client()
                    db.table("brands").update({
                        "ad_library_url": new_ad_library_url
                    }).eq("id", selected_brand_id).execute()
                    st.success("Saved!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

    with col_media:
        media_type = st.selectbox(
            "Media type",
            options=["all", "video", "image"],
            format_func=lambda x: {"all": "All", "video": "Video only", "image": "Image only"}[x],
            key="scrape_media_type",
            help="Filter ads by media type"
        )

    with col_count:
        scrape_count = st.number_input("Max ads", min_value=50, max_value=3000, value=100, step=50, key="scrape_count")

    with col_scrape:
        scrape_url = new_ad_library_url or current_ad_library_url
        if scrape_url:
            if st.button("Scrape Ads", key="scrape_brand_ads", type="primary"):
                # Apply media type filter to URL
                final_url = scrape_url
                if media_type != "all":
                    # Add or replace media_type parameter
                    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                    parsed = urlparse(scrape_url)
                    params = parse_qs(parsed.query)
                    params['media_type'] = [media_type]
                    new_query = urlencode(params, doseq=True)
                    final_url = urlunparse(parsed._replace(query=new_query))

                with st.spinner(f"Scraping up to {scrape_count} {media_type} ads from Facebook Ad Library... This may take several minutes."):
                    result = scrape_facebook_ads(
                        ad_library_url=final_url,
                        brand_id=selected_brand_id,
                        max_ads=scrape_count
                    )

                if result["success"]:
                    if result["count"] > 0:
                        st.success(f"✅ {result['message']}")
                    else:
                        st.warning(result["message"])
                else:
                    st.error(f"❌ Scraping failed: {result['message']}")
        else:
            st.button("Scrape Ads", key="scrape_brand_ads_disabled", disabled=True)

    if current_ad_library_url:
        st.caption(f"[Open in Facebook Ad Library ↗]({current_ad_library_url})")

st.divider()

# ============================================================================
# PRODUCTS SECTION
# ============================================================================

st.subheader("Products")

products = get_products_for_brand(selected_brand_id)

if not products:
    st.info("No products found for this brand.")
else:
    st.markdown(f"**{len(products)} product(s)**")

    for product in products:
        product_id = product['id']
        product_name = product.get('name', 'Unnamed Product')
        is_expanded = st.session_state.expanded_product_id == product_id

        # Product header row
        col_expand, col_name, col_actions = st.columns([0.5, 3, 1.5])

        with col_expand:
            btn_label = "▼" if is_expanded else "▶"
            if st.button(btn_label, key=f"expand_prod_{product_id}"):
                if is_expanded:
                    st.session_state.expanded_product_id = None
                else:
                    st.session_state.expanded_product_id = product_id
                st.rerun()

        with col_name:
            images = product.get('product_images', [])
            analyzed_count = len([i for i in images if i.get('analyzed_at')])
            st.markdown(f"**{product_name}** | {len(images)} images ({analyzed_count} analyzed)")

        with col_actions:
            if st.button("Create Ads", key=f"create_ads_{product_id}", type="primary"):
                # Navigate to Ad Creator with product pre-selected
                st.switch_page("pages/5_🎨_Ad_Creator.py")

        # Expanded product details
        if is_expanded:
            with st.container():
                st.markdown("---")

                # Details tab
                tab_details, tab_offers, tab_discover, tab_amazon, tab_variants, tab_images, tab_stats = st.tabs([
                    "Details", "Offer Variants", "Discover Variants", "Amazon Insights", "Variants", "Images", "Stats"
                ])

                with tab_details:
                    # Product Code (for ad filenames)
                    col_pc, col_pc_spacer = st.columns([1, 3])
                    with col_pc:
                        current_product_code = product.get('product_code') or ''
                        new_product_code = st.text_input(
                            "Product Code",
                            value=current_product_code,
                            max_chars=4,
                            placeholder="e.g., C3",
                            help="2-4 character code used in ad filenames (e.g., C3 for Collagen 3x)",
                            key=f"product_code_{product_id}"
                        )
                        if new_product_code.upper() != current_product_code.upper():
                            if st.button("Save Code", key=f"save_pc_{product_id}", type="primary"):
                                if save_product_code(product_id, new_product_code):
                                    st.success("Product code saved!")
                                    st.rerun()

                    st.markdown("")  # Spacer

                    col_d1, col_d2 = st.columns(2)

                    with col_d1:
                        st.markdown("**Target Audience**")
                        st.caption(product.get('target_audience', 'Not specified'))

                        st.markdown("**Benefits**")
                        benefits = product.get('benefits', [])
                        if benefits:
                            for b in benefits[:5]:
                                st.caption(f"• {b}")
                        else:
                            st.caption("None configured")

                    with col_d2:
                        st.markdown("**USPs**")
                        usps = product.get('unique_selling_points', [])
                        if usps:
                            for u in usps[:5]:
                                st.caption(f"• {u}")
                        else:
                            st.caption("None configured")

                        st.markdown("**Current Offer**")
                        st.caption(product.get('current_offer', 'None'))

                        st.markdown("**Founders**")
                        st.caption(product.get('founders', 'Not specified'))

                    # Social Proof section (full width)
                    st.markdown("---")
                    st.markdown("**📊 Verified Social Proof** (used in ad generation)")

                    col_sp1, col_sp2, col_sp3 = st.columns(3)

                    with col_sp1:
                        st.markdown("**Review Platforms**")
                        review_platforms = product.get('review_platforms', {})
                        if review_platforms:
                            for platform, data in review_platforms.items():
                                rating = data.get('rating', 'N/A')
                                count = data.get('count', 'N/A')
                                st.caption(f"• {platform}: {rating}★ ({count} reviews)")
                        else:
                            st.caption("None configured")

                    with col_sp2:
                        st.markdown("**Media Features**")
                        media_features = product.get('media_features', [])
                        if media_features:
                            for media in media_features[:5]:
                                st.caption(f"• {media}")
                        else:
                            st.caption("None configured")

                    with col_sp3:
                        st.markdown("**Awards & Certifications**")
                        awards = product.get('awards_certifications', [])
                        if awards:
                            for award in awards[:5]:
                                st.caption(f"• {award}")
                        else:
                            st.caption("None configured")

                    # Edit Social Proof button
                    edit_key = f"edit_sp_{product_id}"
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = False

                    if st.button("✏️ Edit Social Proof", key=f"btn_edit_sp_{product_id}"):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()

                    if st.session_state[edit_key]:
                        with st.form(key=f"form_sp_{product_id}"):
                            st.markdown("#### Edit Social Proof")

                            # Review Platforms
                            st.markdown("**Review Platforms** (JSON format)")
                            st.caption("Example: {\"trustpilot\": {\"rating\": 4.5, \"count\": 1200}, \"amazon\": {\"rating\": 4.7, \"count\": 3500}}")
                            current_reviews = product.get('review_platforms', {}) or {}
                            reviews_str = st.text_area(
                                "Review Platforms JSON",
                                value=json.dumps(current_reviews, indent=2) if current_reviews else "{}",
                                height=100,
                                key=f"reviews_{product_id}"
                            )

                            # Media Features
                            st.markdown("**Media Features** (one per line)")
                            st.caption("Example: Forbes, Good Morning America, Today Show")
                            current_media = product.get('media_features', []) or []
                            media_str = st.text_area(
                                "Media Features",
                                value="\n".join(current_media) if current_media else "",
                                height=80,
                                key=f"media_{product_id}"
                            )

                            # Awards & Certifications
                            st.markdown("**Awards & Certifications** (one per line)")
                            st.caption("Example: #1 Best Seller, Vet Recommended, NASC Certified")
                            current_awards = product.get('awards_certifications', []) or []
                            awards_str = st.text_area(
                                "Awards & Certifications",
                                value="\n".join(current_awards) if current_awards else "",
                                height=80,
                                key=f"awards_{product_id}"
                            )

                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                submitted = st.form_submit_button("💾 Save", type="primary")
                            with col_cancel:
                                cancelled = st.form_submit_button("Cancel")

                            if submitted:
                                try:
                                    # Parse JSON for review platforms
                                    review_data = json.loads(reviews_str) if reviews_str.strip() else {}

                                    # Parse newline-separated lists
                                    media_list = [m.strip() for m in media_str.split("\n") if m.strip()]
                                    awards_list = [a.strip() for a in awards_str.split("\n") if a.strip()]

                                    if save_product_social_proof(product_id, review_data, media_list, awards_list):
                                        st.success("Social proof saved!")
                                        st.session_state[edit_key] = False
                                        st.rerun()
                                except json.JSONDecodeError as e:
                                    st.error(f"Invalid JSON in Review Platforms: {e}")

                            if cancelled:
                                st.session_state[edit_key] = False
                                st.rerun()

                with tab_offers:
                    # Offer Variants = Landing page angles with pain points/benefits
                    offer_variants = get_offer_variants_for_product(product_id)

                    if not offer_variants:
                        st.info("No offer variants imported. These are created during brand onboarding from Amazon analysis or ad library scraping.")
                    else:
                        st.markdown(f"**{len(offer_variants)} offer variant(s)** (landing page angles)")

                        for ov in offer_variants:
                            with st.expander(f"**{ov.get('name', 'Unnamed')}**", expanded=False):
                                ov_id = ov.get('id')

                                # Landing page URL
                                landing_url = ov.get('landing_page_url', '')
                                if landing_url:
                                    st.markdown(f"🔗 [{landing_url[:50]}...]({landing_url})" if len(landing_url) > 50 else f"🔗 [{landing_url}]({landing_url})")

                                # Editable Target Audience with Synthesize button
                                ta_state_key = f"ta_state_{ov_id}"
                                db_ta = ov.get('target_audience', '') or ''

                                # Initialize state from DB if needed
                                if ta_state_key not in st.session_state:
                                    st.session_state[ta_state_key] = db_ta

                                ta_col1, ta_col2 = st.columns([3, 1])
                                with ta_col1:
                                    st.markdown("**Target Audience**")
                                with ta_col2:
                                    synth_btn_key = f"synth_ta_{ov_id}"
                                    if landing_url and st.button("🔮 Synthesize", key=synth_btn_key, help="Extract target audience from landing page using AI"):
                                        with st.spinner("Analyzing landing page..."):
                                            from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
                                            ov_service = ProductOfferVariantService()
                                            result = ov_service.analyze_landing_page(landing_url)
                                            if result.get('success') and result.get('target_audience'):
                                                st.session_state[ta_state_key] = result['target_audience']
                                                st.rerun()
                                            else:
                                                st.error("Could not extract target audience from landing page")

                                # Use unique key per render to avoid state conflicts
                                widget_key = f"ta_widget_{ov_id}_{hash(st.session_state.get(ta_state_key, ''))}"
                                new_ta = st.text_area(
                                    "Target audience for this offer variant",
                                    value=st.session_state[ta_state_key],
                                    key=widget_key,
                                    height=100,
                                    help="Define who this offer variant targets. This will be used in ad generation prompts.",
                                    label_visibility="collapsed"
                                )
                                # Update our state if user edited
                                st.session_state[ta_state_key] = new_ta

                                # Save button if changed
                                original_ta = ov.get('target_audience', '') or ''
                                if new_ta != original_ta:
                                    if st.button("💾 Save Target Audience", key=f"save_ta_{ov_id}"):
                                        from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
                                        ov_service = ProductOfferVariantService()
                                        success = ov_service.update_offer_variant(
                                            UUID(ov_id),
                                            {'target_audience': new_ta}
                                        )
                                        if success:
                                            st.success("Target audience saved!")
                                            st.rerun()
                                        else:
                                            st.error("Failed to save target audience")

                                # Images from Landing Page section
                                st.markdown("")
                                img_col1, img_col2 = st.columns([3, 1])
                                with img_col1:
                                    st.markdown("**Images from Landing Page**")
                                with img_col2:
                                    scrape_key = f"scrape_imgs_{ov_id}"
                                    if landing_url and st.button("📷 Scrape Images", key=scrape_key, help="Extract product images from landing page"):
                                        with st.spinner("Scraping images from landing page..."):
                                            result = scrape_and_save_offer_variant_images(
                                                product_id, ov_id, landing_url
                                            )
                                            if result['success']:
                                                st.success(f"Found {result['total_count']} images, added {result['new_count']} new")
                                                st.rerun()
                                            else:
                                                st.error(f"Failed: {result.get('error', 'Unknown error')}")

                                # Display existing images for this offer variant
                                ov_images = get_offer_variant_images(ov_id)
                                if ov_images:
                                    # Create image grid (4 columns)
                                    img_cols = st.columns(4)
                                    for idx, ovi in enumerate(ov_images[:8]):
                                        pi = ovi.get('product_images', {})
                                        if pi and pi.get('storage_path'):
                                            with img_cols[idx % 4]:
                                                try:
                                                    db = get_supabase_client()
                                                    # storage_path includes bucket prefix, strip it for get_public_url
                                                    sp = pi['storage_path']
                                                    if sp.startswith("product-images/"):
                                                        sp = sp[len("product-images/"):]
                                                    url = db.storage.from_("product-images").get_public_url(sp)
                                                    st.image(url, width=100)
                                                except:
                                                    st.caption("📷")
                                    if len(ov_images) > 8:
                                        st.caption(f"*...and {len(ov_images) - 8} more images*")
                                else:
                                    if not landing_url:
                                        st.caption("No landing page URL set")
                                    else:
                                        st.caption("No images scraped yet. Click 'Scrape Images' to extract from landing page.")

                                st.markdown("---")

                                col_ov1, col_ov2 = st.columns(2)

                                with col_ov1:
                                    # Pain Points
                                    st.markdown("**Pain Points**")
                                    pain_points = ov.get('pain_points') or []
                                    if pain_points:
                                        for pp in pain_points[:8]:
                                            st.caption(f"• {pp}")
                                        if len(pain_points) > 8:
                                            st.caption(f"*...and {len(pain_points) - 8} more*")
                                    else:
                                        st.caption("None")

                                with col_ov2:
                                    # Benefits
                                    st.markdown("**Benefits**")
                                    benefits = ov.get('benefits') or []
                                    if benefits:
                                        for b in benefits[:8]:
                                            st.caption(f"• {b}")
                                        if len(benefits) > 8:
                                            st.caption(f"*...and {len(benefits) - 8} more*")
                                    else:
                                        st.caption("None")

                                # Mechanism fields if present
                                mechanism_name = ov.get('mechanism_name')
                                if mechanism_name:
                                    st.markdown("---")
                                    st.markdown("**Mechanism (UM/UMP/UMS)**")
                                    st.caption(f"**Name:** {mechanism_name}")
                                    if ov.get('mechanism_problem'):
                                        st.caption(f"**Problem:** {ov['mechanism_problem']}")
                                    if ov.get('mechanism_solution'):
                                        st.caption(f"**Solution:** {ov['mechanism_solution']}")

                                # Sample hooks if present
                                sample_hooks = ov.get('sample_hooks') or []
                                if sample_hooks:
                                    st.markdown("---")
                                    st.markdown("**Sample Hooks**")
                                    for hook in sample_hooks[:3]:
                                        st.caption(f"• {hook}")

                                # Source info
                                source = ov.get('source')
                                if source:
                                    st.markdown("---")
                                    st.caption(f"*Source: {source}*")

                with tab_discover:
                    render_offer_variant_discovery(selected_brand_id, product_id, product['name'])

                with tab_amazon:
                    # Amazon Review Analysis
                    amazon_data = get_amazon_analysis_for_product(product_id)

                    if not amazon_data:
                        st.info("No Amazon analysis imported. Run Amazon analysis during brand onboarding to populate this data.")
                    else:
                        col_am1, col_am2 = st.columns(2)

                        with col_am1:
                            # Pain Points
                            st.markdown("**Pain Points from Reviews**")
                            pain_points = amazon_data.get('pain_points') or []
                            if pain_points:
                                for pp in pain_points:
                                    st.caption(f"• {pp}")
                            else:
                                st.caption("None extracted")

                            # Desires/Goals
                            st.markdown("")
                            st.markdown("**Desires & Goals**")
                            desires = amazon_data.get('desires_goals') or []
                            if desires:
                                for d in desires:
                                    st.caption(f"• {d}")
                            else:
                                st.caption("None extracted")

                        with col_am2:
                            # Benefits
                            st.markdown("**Benefits Mentioned**")
                            benefits = amazon_data.get('benefits') or []
                            if benefits:
                                for b in benefits:
                                    st.caption(f"• {b}")
                            else:
                                st.caption("None extracted")

                            # Jobs to be Done
                            st.markdown("")
                            st.markdown("**Jobs to be Done**")
                            jtbd = amazon_data.get('jobs_to_be_done') or []
                            if jtbd:
                                for j in jtbd:
                                    st.caption(f"• {j}")
                            else:
                                st.caption("None extracted")

                        # Quotes section (full width)
                        st.markdown("---")
                        st.markdown("**Customer Quotes**")
                        quotes = amazon_data.get('quotes') or []
                        if quotes:
                            for q in quotes[:5]:
                                st.markdown(f"> *\"{q}\"*")
                            if len(quotes) > 5:
                                st.caption(f"*...and {len(quotes) - 5} more quotes*")
                        else:
                            st.caption("No quotes extracted")

                        # Metadata
                        st.markdown("---")
                        created_at = amazon_data.get('created_at', '')
                        if created_at:
                            st.caption(f"*Analysis created: {created_at[:10]}*")

                with tab_variants:
                    variants = product.get('product_variants', [])
                    active_variants = [v for v in variants if v.get('is_active', True)]

                    st.markdown(f"**{len(active_variants)} variant(s)**")

                    # Add new variant form
                    add_variant_key = f"add_variant_{product_id}"
                    if add_variant_key not in st.session_state:
                        st.session_state[add_variant_key] = False

                    col_add, col_spacer = st.columns([1, 3])
                    with col_add:
                        if st.button("➕ Add Variant", key=f"btn_add_var_{product_id}"):
                            st.session_state[add_variant_key] = not st.session_state[add_variant_key]
                            st.rerun()

                    if st.session_state[add_variant_key]:
                        with st.form(key=f"form_add_var_{product_id}"):
                            st.markdown("#### Add New Variant")

                            new_var_name = st.text_input(
                                "Variant Name",
                                placeholder="e.g., Strawberry, Chocolate, Large",
                                key=f"new_var_name_{product_id}"
                            )

                            new_var_type = st.selectbox(
                                "Variant Type",
                                options=["flavor", "size", "color", "bundle", "other"],
                                key=f"new_var_type_{product_id}"
                            )

                            new_var_desc = st.text_area(
                                "Description (optional)",
                                placeholder="What makes this variant unique?",
                                height=80,
                                key=f"new_var_desc_{product_id}"
                            )

                            new_var_default = st.checkbox(
                                "Set as default variant",
                                key=f"new_var_default_{product_id}"
                            )

                            col_submit, col_cancel = st.columns(2)
                            with col_submit:
                                submitted = st.form_submit_button("💾 Save", type="primary")
                            with col_cancel:
                                cancelled = st.form_submit_button("Cancel")

                            if submitted and new_var_name:
                                if create_variant(
                                    product_id=product_id,
                                    name=new_var_name,
                                    variant_type=new_var_type,
                                    description=new_var_desc if new_var_desc else None,
                                    is_default=new_var_default
                                ):
                                    st.success(f"Variant '{new_var_name}' created!")
                                    st.session_state[add_variant_key] = False
                                    st.rerun()

                            if cancelled:
                                st.session_state[add_variant_key] = False
                                st.rerun()

                    # Display existing variants
                    if variants:
                        st.markdown("---")
                        for var in variants:
                            var_id = var['id']
                            var_name = var.get('name', 'Unnamed')
                            var_type = var.get('variant_type', 'flavor')
                            is_default = var.get('is_default', False)
                            is_active = var.get('is_active', True)

                            col_var_name, col_var_type, col_var_actions = st.columns([2, 1, 1])

                            with col_var_name:
                                status_icon = "⭐" if is_default else ""
                                active_style = "" if is_active else " *(inactive)*"
                                st.markdown(f"**{var_name}** {status_icon}{active_style}")
                                if var.get('description'):
                                    st.caption(var['description'])

                            with col_var_type:
                                st.caption(f"Type: {var_type}")

                            with col_var_actions:
                                col_default, col_toggle, col_delete = st.columns(3)

                                with col_default:
                                    if not is_default:
                                        if st.button("⭐", key=f"set_default_{var_id}", help="Set as default"):
                                            # Clear other defaults first
                                            for v in variants:
                                                if v.get('is_default'):
                                                    update_variant(v['id'], {"is_default": False})
                                            update_variant(var_id, {"is_default": True})
                                            st.rerun()

                                with col_toggle:
                                    toggle_label = "🔴" if is_active else "🟢"
                                    toggle_help = "Deactivate" if is_active else "Activate"
                                    if st.button(toggle_label, key=f"toggle_{var_id}", help=toggle_help):
                                        update_variant(var_id, {"is_active": not is_active})
                                        st.rerun()

                                with col_delete:
                                    if st.button("🗑️", key=f"del_var_{var_id}", help="Delete"):
                                        if delete_variant(var_id):
                                            st.rerun()
                    else:
                        st.info("No variants configured. Add variants for different flavors, sizes, or options.")

                with tab_images:
                    images = product.get('product_images', [])

                    if not images:
                        st.info("No images uploaded for this product.")
                    else:
                        # Analyze All button - only for images (not PDFs)
                        analyzable_images = [i for i in images if i.get('is_image', True) and not i.get('is_pdf')]
                        unanalyzed = [i for i in analyzable_images if not i.get('analyzed_at')]
                        if unanalyzed:
                            if st.button(f"🔍 Analyze All ({len(unanalyzed)} unanalyzed)", key=f"analyze_all_{product_id}"):
                                st.info("Analyzing images... This may take a minute.")
                                for img in unanalyzed:
                                    try:
                                        analysis = asyncio.run(analyze_image(img['storage_path']))
                                        save_image_analysis(img['id'], analysis)
                                    except Exception as e:
                                        st.error(f"Failed to analyze {img['storage_path']}: {e}")
                                st.success("Analysis complete!")
                                st.rerun()

                        # Image/file grid
                        cols = st.columns(4)
                        for idx, img in enumerate(images):
                            with cols[idx % 4]:
                                is_pdf = img.get('is_pdf', False)
                                is_image = img.get('is_image', True)

                                # Display thumbnail or PDF badge
                                if is_pdf:
                                    # PDF badge
                                    st.markdown(
                                        "<div style='height:100px;background:#2d2d2d;border-radius:8px;"
                                        "display:flex;align-items:center;justify-content:center;"
                                        "font-size:2em;'>📄</div>",
                                        unsafe_allow_html=True
                                    )
                                    filename = img['storage_path'].split('/')[-1]
                                    st.caption(f"**PDF:** {filename[:20]}...")
                                else:
                                    # Regular image thumbnail
                                    img_url = get_signed_url(img['storage_path'])
                                    if img_url:
                                        st.image(img_url, use_container_width=True)
                                    else:
                                        st.markdown("<div style='height:100px;background:#333;'></div>", unsafe_allow_html=True)

                                # Analysis status (only for images)
                                if is_image and not is_pdf:
                                    analysis = img.get('image_analysis')
                                    if analysis:
                                        quality = analysis.get('quality_score', 0)
                                        stars = "⭐" * int(quality * 5)
                                        use_cases = analysis.get('best_use_cases', [])[:2]
                                        st.caption(f"{stars} {quality:.2f}")
                                        st.caption(f"{', '.join(use_cases)}")
                                    else:
                                        st.caption("❓ Not analyzed")
                                        if st.button("Analyze", key=f"analyze_{img['id']}", type="secondary"):
                                            with st.spinner("Analyzing..."):
                                                try:
                                                    result = asyncio.run(analyze_image(img['storage_path']))
                                                    save_image_analysis(img['id'], result)
                                                    st.success("Done!")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")
                                elif is_pdf:
                                    st.caption("📋 PDF - Gemini analysis coming soon")

                                # Notes input (for all file types)
                                current_notes = img.get('notes', '') or ''
                                with st.expander("📝 Notes", expanded=bool(current_notes)):
                                    new_notes = st.text_area(
                                        "Add context",
                                        value=current_notes,
                                        key=f"notes_{img['id']}",
                                        placeholder="e.g., Product packaging front view, Card examples...",
                                        height=80
                                    )
                                    if new_notes != current_notes:
                                        if st.button("Save", key=f"save_notes_{img['id']}", type="primary"):
                                            save_image_notes(img['id'], new_notes)
                                            st.success("Saved!")
                                            st.rerun()

                with tab_stats:
                    # Hooks count
                    hooks_count = get_hooks_count(product_id)
                    st.metric("Hooks", hooks_count)

                    # Ad runs stats
                    stats = get_ad_runs_stats(product_id)
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        st.metric("Ad Runs", stats['runs'])
                    with col_s2:
                        st.metric("Ads Generated", stats['ads'])
                    with col_s3:
                        approval_rate = int(stats['approved'] / stats['ads'] * 100) if stats['ads'] > 0 else 0
                        st.metric("Approval Rate", f"{approval_rate}%")

                st.markdown("---")

# Footer
st.divider()
st.caption("Use Ad Creator to generate new ads, or Ad History to review past runs.")
