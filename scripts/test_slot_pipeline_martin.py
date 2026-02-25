"""
Local test: Run the new slot-based blueprint pipeline against the most recent
Martin Clinic blueprint data from the database.

Usage:
    python scripts/test_slot_pipeline_martin.py

This pulls real data from Supabase, runs each pipeline step locally,
and reports results without making AI calls (dry-run mode by default).
Pass --live to actually call the AI.
"""
import json
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_slot_pipeline")

from viraltracker.core.database import get_supabase_client
from viraltracker.services.landing_page_analysis.mockup_service import MockupService


def fetch_martin_clinic_data():
    """Fetch the most recent Martin Clinic blueprint + analysis HTML from Supabase."""
    client = get_supabase_client()

    # Find the most recent Martin Clinic blueprint
    resp = (
        client.table("landing_page_blueprints")
        .select("id, analysis_id, blueprint, source_url, brand_profile_snapshot, status")
        .or_("source_url.ilike.%martin%,blueprint->>metadata.ilike.%martin%")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )

    if not resp.data:
        # Try via brand name in snapshot
        resp = (
            client.table("landing_page_blueprints")
            .select("id, analysis_id, blueprint, source_url, brand_profile_snapshot, status")
            .ilike("brand_profile_snapshot->>brand_basics", "%Martin%")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )

    if not resp.data:
        logger.error("No Martin Clinic blueprints found in database")
        return None, None, None, None

    bp_record = resp.data[0]
    logger.info(f"Found blueprint {bp_record['id']}, analysis_id={bp_record['analysis_id']}, source_url={bp_record.get('source_url')}")

    # Fetch the linked analysis record for the mockup HTML
    analysis_id = bp_record["analysis_id"]
    analysis_resp = (
        client.table("landing_page_analyses")
        .select("id, url, analysis_mockup_html, classification")
        .eq("id", analysis_id)
        .single()
        .execute()
    )

    if not analysis_resp.data:
        logger.error(f"No analysis record found for id={analysis_id}")
        return bp_record, None, None, None

    analysis = analysis_resp.data
    logger.info(f"Found analysis {analysis['id']}, url={analysis.get('url')}")

    return bp_record, analysis, bp_record.get("blueprint"), bp_record.get("brand_profile_snapshot")


def test_pipeline_steps(bp_record, analysis, blueprint, brand_profile):
    """Run each step of the slot pipeline and report results."""
    svc = MockupService()

    analysis_html = analysis.get("analysis_mockup_html", "")
    source_url = analysis.get("url", "") or bp_record.get("source_url", "")
    classification = analysis.get("classification", {})

    if not analysis_html:
        logger.error("No analysis_mockup_html found — cannot test pipeline")
        return False

    logger.info(f"Analysis HTML length: {len(analysis_html)} chars")

    # Detect surgery mode
    is_surgery = 'data-pipeline="surgery"' in analysis_html
    svc.is_surgery_mode = is_surgery
    logger.info(f"Surgery mode: {is_surgery}")

    # Step 1: Extract page body and CSS
    page_body, page_css = svc._extract_page_css_and_strip(analysis_html)
    logger.info(f"Page body: {len(page_body)} chars, Page CSS: {len(page_css)} chars")

    # Step 2: Extract slots with content
    slot_contents = svc._extract_slots_with_content(page_body)
    logger.info(f"Extracted {len(slot_contents)} slots with content")

    if not slot_contents:
        logger.warning("No data-slot elements found!")
        return False

    # Show first 10 slots
    for i, (name, text) in enumerate(slot_contents.items()):
        if i >= 15:
            logger.info(f"  ... and {len(slot_contents) - 15} more slots")
            break
        preview = text[:80] + "..." if len(text) > 80 else text
        logger.info(f"  [{name}] ({len(text)} chars): {preview}")

    # Slot type distribution
    from collections import Counter
    type_counts = Counter(svc._infer_slot_type(name) for name in slot_contents)
    logger.info(f"Slot type distribution: {dict(type_counts)}")

    # Step 3: Extract competitor name
    competitor_name = svc._extract_competitor_name(blueprint, source_url=source_url, html=analysis_html)
    brand_name = (brand_profile.get("brand_basics") or {}).get("name", "?")
    logger.info(f"Competitor name: {competitor_name}")
    logger.info(f"Brand name: {brand_name}")

    # Step 4: Replace competitor brand (dry run — just check it works)
    if competitor_name and brand_name:
        replaced = svc._replace_competitor_brand(page_body, competitor_name, brand_name)
        diff_chars = len(page_body) - len(replaced)
        # Count replacements
        import re
        original_count = len(re.findall(re.escape(competitor_name), page_body, re.IGNORECASE))
        replaced_count = len(re.findall(re.escape(brand_name), replaced, re.IGNORECASE))
        original_brand_count = len(re.findall(re.escape(brand_name), page_body, re.IGNORECASE))
        new_brand_count = replaced_count - original_brand_count
        logger.info(f"Brand replacement: found {original_count} competitor mentions, injected {new_brand_count} brand mentions, length delta={diff_chars}")
    else:
        logger.warning("Skipping brand replacement — no competitor or brand name")
        replaced = page_body

    # Step 5: Map slots to sections
    slot_sections = svc._map_slots_to_sections(page_body, blueprint)
    logger.info(f"Mapped {len(slot_sections)} slots to sections")

    # Section distribution
    section_counts = Counter(v.get("section_name", "?") for v in slot_sections.values())
    for sec, count in section_counts.most_common():
        logger.info(f"  Section '{sec}': {count} slots")

    # Check for orphan slots (no section mapping)
    orphan_count = sum(1 for v in slot_sections.values() if v.get("section_name") == "global")
    if orphan_count:
        logger.warning(f"{orphan_count} orphan slots mapped to 'global'")

    # Step 6: Build AI payload (dry run — show structure without calling AI)
    import json as _json
    rb = blueprint
    if "reconstruction_blueprint" in rb:
        rb = rb["reconstruction_blueprint"]

    strategy = rb.get("strategy_summary", {})
    bp_sections = rb.get("sections", [])
    logger.info(f"Blueprint has {len(bp_sections)} sections, strategy: {list(strategy.keys())}")

    # Estimate batching
    total_slots = len(slot_contents)
    max_per_batch = 80
    num_batches = (total_slots + max_per_batch - 1) // max_per_batch
    logger.info(f"Slot count: {total_slots}, estimated batches: {num_batches}")

    # Step 7: Test _template_swap with a mock slot_map (use original text as values)
    mock_slot_map = {name: f"[REWRITTEN: {name}]" for name in slot_contents}
    swapped = svc._template_swap(replaced, blueprint, brand_profile, slot_map=mock_slot_map)
    logger.info(f"Template swap result: {len(swapped)} chars")

    # Verify all slots were replaced
    replaced_count = sum(1 for name in slot_contents if f"[REWRITTEN: {name}]" in swapped)
    logger.info(f"Slots replaced in swap: {replaced_count}/{len(slot_contents)}")

    if replaced_count < len(slot_contents):
        missing = [name for name in slot_contents if f"[REWRITTEN: {name}]" not in swapped]
        logger.warning(f"Missing slots after swap: {missing[:20]}")

    # Step 8: Sanitize and wrap
    inner = svc._sanitize_html(swapped)
    final = svc._wrap_mockup(inner, classification, mode="blueprint", page_css=page_css)
    logger.info(f"Final output: {len(final)} chars")

    # Verify markers
    assert "BLUEPRINT MOCKUP" in final, "Missing BLUEPRINT MOCKUP marker"
    assert "<!DOCTYPE html>" in final, "Missing DOCTYPE"
    logger.info("Output validation passed")

    return True


def test_live_pipeline(bp_record, analysis, blueprint, brand_profile):
    """Run the FULL pipeline with actual AI calls."""
    svc = MockupService()

    # Set up tracking context (optional)
    try:
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        svc.set_tracking_context(tracker, None, None)
    except Exception:
        pass

    analysis_html = analysis.get("analysis_mockup_html", "")
    source_url = analysis.get("url", "") or bp_record.get("source_url", "")
    classification = analysis.get("classification", {})

    logger.info("=" * 60)
    logger.info("LIVE TEST — calling AI for slot rewrites")
    logger.info("=" * 60)

    result = svc.generate_blueprint_mockup(
        blueprint,
        analysis_mockup_html=analysis_html,
        classification=classification,
        brand_profile=brand_profile,
        source_url=source_url,
    )

    if result:
        logger.info(f"SUCCESS — generated {len(result)} chars of blueprint mockup HTML")
        # Save to file for inspection
        output_path = "test_martin_clinic_blueprint_output.html"
        with open(output_path, "w") as f:
            f.write(result)
        logger.info(f"Saved output to {output_path}")

        # Check for slot markers in output
        from viraltracker.services.landing_page_analysis.mockup_service import MockupService as MS
        final_svc = MS()
        final_slots = final_svc._extract_slot_names(result)
        logger.info(f"Final output has {len(final_slots)} data-slot markers")
    else:
        logger.error("FAILED — generate_blueprint_mockup returned None")
        return False

    return True


if __name__ == "__main__":
    live_mode = "--live" in sys.argv

    logger.info("Fetching Martin Clinic data from Supabase...")
    bp_record, analysis, blueprint, brand_profile = fetch_martin_clinic_data()

    if not bp_record or not analysis:
        logger.error("Could not fetch required data")
        sys.exit(1)

    if not blueprint:
        logger.error("Blueprint JSON is empty")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("DRY RUN — testing pipeline steps without AI calls")
    logger.info("=" * 60)

    success = test_pipeline_steps(bp_record, analysis, blueprint, brand_profile)
    if not success:
        logger.error("Dry run FAILED")
        sys.exit(1)
    logger.info("Dry run PASSED")

    if live_mode:
        success = test_live_pipeline(bp_record, analysis, blueprint, brand_profile)
        if not success:
            sys.exit(1)
    else:
        logger.info("\nPass --live to run the full pipeline with AI calls")
