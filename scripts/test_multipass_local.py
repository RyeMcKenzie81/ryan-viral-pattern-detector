#!/usr/bin/env python3
"""Quick local test for the multipass pipeline.

Grabs the most recent analyzed page from the DB and runs multipass on it,
printing phase-by-phase progress to the terminal.

Usage:
    python scripts/test_multipass_local.py [--page-id ID]
"""

import argparse
import base64
import logging
import os
import sys
import time

# Load .env before any imports that need it
from pathlib import Path
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def progress_callback(phase: str, detail: str = ""):
    """Print phase progress to terminal."""
    logger.info(f"[PROGRESS] {phase}: {detail}")


def main():
    parser = argparse.ArgumentParser(description="Test multipass pipeline locally")
    parser.add_argument("--page-id", help="Specific analysis ID to test")
    parser.add_argument("--url", help="Find most recent analysis for this URL")
    parser.add_argument("--single-pass", action="store_true", help="Also run single-pass for comparison")
    args = parser.parse_args()

    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.landing_page_analysis.mockup_service import MockupService
    from viraltracker.services.landing_page_analysis.analysis_service import LandingPageAnalysisService

    supabase = get_supabase_client()
    analysis_svc = LandingPageAnalysisService(supabase)
    mockup_svc = MockupService()

    # Find a page to test
    if args.page_id:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, screenshot_storage_path"
        ).eq("id", args.page_id).single().execute()
        analysis = result.data
    elif args.url:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, screenshot_storage_path"
        ).like("url", f"%{args.url}%").not_.is_(
            "screenshot_storage_path", "null"
        ).order("created_at", desc=True).limit(1).execute()
        if not result.data:
            logger.error(f"No analyses found for URL matching: {args.url}")
            sys.exit(1)
        analysis = result.data[0]
    else:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, screenshot_storage_path"
        ).not_.is_(
            "screenshot_storage_path", "null"
        ).not_.is_(
            "page_markdown", "null"
        ).order("created_at", desc=True).limit(1).execute()
        if not result.data:
            logger.error("No analyses with screenshots found in DB")
            sys.exit(1)
        analysis = result.data[0]

    page_id = analysis["id"]
    url = analysis.get("url", "unknown")
    markdown = analysis.get("page_markdown", "")
    screenshot_path = analysis.get("screenshot_storage_path")

    logger.info(f"Testing page: {url}")
    logger.info(f"Analysis ID: {page_id}")
    logger.info(f"Markdown length: {len(markdown)} chars")

    # Load screenshot
    screenshot_bytes = analysis_svc._load_screenshot(screenshot_path)
    if not screenshot_bytes:
        logger.error("Failed to load screenshot")
        sys.exit(1)
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
    logger.info(f"Screenshot loaded: {len(screenshot_bytes)} bytes")

    # Run single-pass first if requested
    if args.single_pass:
        logger.info("=" * 60)
        logger.info("RUNNING SINGLE-PASS")
        logger.info("=" * 60)
        start = time.time()
        single_html = mockup_svc.generate_analysis_mockup(
            screenshot_b64=screenshot_b64,
            page_markdown=markdown,
            page_url=url,
            use_multipass=False,
        )
        single_time = time.time() - start
        single_slots = single_html.count('data-slot=')
        logger.info(f"Single-pass done: {len(single_html)} chars, {single_slots} slots, {single_time:.1f}s")

    # Run multipass
    logger.info("=" * 60)
    logger.info("RUNNING MULTIPASS")
    logger.info("=" * 60)
    start = time.time()
    multi_html = mockup_svc.generate_analysis_mockup(
        screenshot_b64=screenshot_b64,
        page_markdown=markdown,
        page_url=url,
        use_multipass=True,
        progress_callback=progress_callback,
    )
    multi_time = time.time() - start

    # Count results
    multi_slots = multi_html.count('data-slot=')
    section_count = multi_html.count('data-section=')
    html_len = len(multi_html)

    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    logger.info(f"Output HTML: {html_len} chars")
    logger.info(f"Sections:    {section_count}")
    logger.info(f"Slots:       {multi_slots}")
    logger.info(f"Latency:     {multi_time:.1f}s")

    if args.single_pass:
        logger.info(f"Single-pass: {single_slots} slots, {single_time:.1f}s")
        if single_slots > 0:
            logger.info(f"Retention:   {multi_slots / single_slots:.0%}")

    # Write output HTML for inspection
    out_path = Path(__file__).resolve().parent.parent / "test_multipass_output.html"
    out_path.write_text(multi_html)
    logger.info(f"Output saved to: {out_path}")

    # Save all phase snapshots to individual files
    snapshots_dir = Path(__file__).resolve().parent.parent / "test_multipass_snapshots"
    snapshots_dir.mkdir(exist_ok=True)

    pipeline = getattr(mockup_svc, '_last_pipeline', None)
    if pipeline and hasattr(pipeline, 'phase_snapshots'):
        snapshots = pipeline.phase_snapshots
        if snapshots:
            logger.info(f"Saving {len(snapshots)} phase snapshots to {snapshots_dir}")
            for key, html in snapshots.items():
                snap_path = snapshots_dir / f"{key}.html"
                snap_path.write_text(html)
                logger.info(f"  {key}: {len(html)} chars -> {snap_path.name}")
        else:
            logger.info("No phase snapshots available")
    else:
        logger.info("Pipeline not available for snapshot extraction")


if __name__ == "__main__":
    main()
