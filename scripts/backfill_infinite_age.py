#!/usr/bin/env python3
"""
Backfill script for Infinite Age onboarding data.

This script fixes data gaps from the Infinite Age client onboarding by:
1. Updating the brands record with ad_library_url and facebook_page_id
2. Importing scraped Facebook ads to facebook_ads table
3. Importing competitor ads to competitor_ads table

Run this once after deploying the updated import logic.

Usage:
    python scripts/backfill_infinite_age.py
"""

import logging
from uuid import UUID

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    """Run the backfill."""
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.client_onboarding_service import ClientOnboardingService

    db = get_supabase_client()
    service = ClientOnboardingService()

    # Find Infinite Age session
    sessions_result = db.table("client_onboarding_sessions").select(
        "id, session_name, brand_id, facebook_meta, competitors"
    ).ilike("session_name", "%infinite%age%").execute()

    if not sessions_result.data:
        # Try looking by brand name
        brand_result = db.table("brands").select("id, name").ilike(
            "name", "%infinite%age%"
        ).execute()
        if brand_result.data:
            brand_id = brand_result.data[0]["id"]
            sessions_result = db.table("client_onboarding_sessions").select(
                "id, session_name, brand_id, facebook_meta, competitors"
            ).eq("brand_id", brand_id).execute()

    if not sessions_result.data:
        logger.error("No Infinite Age session found")
        return

    session = sessions_result.data[0]
    session_id = UUID(session["id"])
    brand_id = session.get("brand_id")

    logger.info(f"Found session: {session['session_name']} (ID: {session_id})")
    logger.info(f"Linked brand_id: {brand_id}")

    if not brand_id:
        logger.error("Session has no linked brand_id - was it imported?")
        return

    brand_id = UUID(brand_id)

    # 1. Update brands with facebook_meta fields
    facebook_meta = session.get("facebook_meta") or {}
    if facebook_meta:
        update_data = {}

        if facebook_meta.get("ad_library_url"):
            update_data["ad_library_url"] = facebook_meta["ad_library_url"]

        if facebook_meta.get("page_id"):
            update_data["facebook_page_id"] = facebook_meta["page_id"]
        elif facebook_meta.get("ad_library_url"):
            # Extract from URL
            page_id = service._extract_facebook_page_id(facebook_meta["ad_library_url"])
            if page_id:
                update_data["facebook_page_id"] = page_id

        if update_data:
            db.table("brands").update(update_data).eq("id", str(brand_id)).execute()
            logger.info(f"Updated brands with: {update_data}")
        else:
            logger.info("No facebook_meta fields to update")

        # 2. Import brand Facebook ads
        url_groups = facebook_meta.get("url_groups") or []
        total_ads = sum(len(g.get("ads", [])) for g in url_groups)
        analyzed_groups = sum(1 for g in url_groups if g.get("analysis_data"))
        logger.info(f"Found {total_ads} ads in {len(url_groups)} URL groups ({analyzed_groups} analyzed)")

        if url_groups:
            ads_imported = service._import_brand_facebook_ads(brand_id, facebook_meta)
            logger.info(f"Imported {ads_imported} brand Facebook ads")

            # 2b. Import landing pages with analysis data
            lp_imported = service._import_brand_landing_pages(brand_id, facebook_meta)
            logger.info(f"Imported {lp_imported} brand landing pages")
    else:
        logger.info("No facebook_meta in session")

    # 3. Import competitor ads
    competitors = session.get("competitors") or []
    logger.info(f"Found {len(competitors)} competitors")

    total_competitor_ads = 0
    for comp in competitors:
        comp_name = comp.get("name", "Unknown")
        url_groups = comp.get("url_groups") or []

        if not url_groups:
            logger.info(f"  {comp_name}: No URL groups")
            continue

        total_ads = sum(len(g.get("ads", [])) for g in url_groups)
        logger.info(f"  {comp_name}: {total_ads} ads in {len(url_groups)} URL groups")

        # Find the competitor record
        comp_result = db.table("competitors").select("id").eq(
            "brand_id", str(brand_id)
        ).eq("name", comp_name).execute()

        if not comp_result.data:
            logger.warning(f"  Competitor '{comp_name}' not found in database")
            continue

        competitor_id = UUID(comp_result.data[0]["id"])

        ads_imported = service._import_competitor_ads(
            competitor_id=competitor_id,
            brand_id=brand_id,
            competitor_data=comp
        )
        total_competitor_ads += ads_imported
        logger.info(f"  Imported {ads_imported} ads for {comp_name}")

    logger.info(f"\n=== BACKFILL COMPLETE ===")
    logger.info(f"Total competitor ads imported: {total_competitor_ads}")


if __name__ == "__main__":
    main()
