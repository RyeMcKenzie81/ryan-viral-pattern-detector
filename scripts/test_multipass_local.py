#!/usr/bin/env python3
"""Quick local test for the multipass pipeline.

Grabs the most recent analyzed page from the DB and runs multipass on it,
printing phase-by-phase progress to the terminal.

Usage:
    python scripts/test_multipass_local.py [--page-id ID] [--url URL] [--visual]
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env before any imports that need it
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_BASE = PROJECT_ROOT / "test_multipass_snapshots"


def progress_callback(phase: str, detail: str = ""):
    """Print phase progress to terminal."""
    logger.info(f"[PROGRESS] {phase}: {detail}")


def _get_commit_sha() -> str:
    """Get current git commit SHA (short)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _create_run_dir(prefix: str = "run") -> Path:
    """Create a timestamped run directory under SNAPSHOTS_BASE."""
    SNAPSHOTS_BASE.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    short_hash = hashlib.sha256(ts.encode()).hexdigest()[:6]
    run_id = f"{prefix}_{ts}_{short_hash}"
    run_dir = SNAPSHOTS_BASE / run_id
    run_dir.mkdir(parents=True)

    # Update 'latest' symlink
    latest = SNAPSHOTS_BASE / "latest"
    latest.unlink(missing_ok=True)
    try:
        latest.symlink_to(run_dir.name)
    except OSError:
        pass

    return run_dir


def main():
    parser = argparse.ArgumentParser(description="Test multipass pipeline locally")
    parser.add_argument("--page-id", help="Specific analysis ID to test")
    parser.add_argument("--url", help="Find most recent analysis for this URL")
    parser.add_argument("--single-pass", action="store_true", help="Also run single-pass for comparison")
    parser.add_argument("--rescrape", action="store_true", help="Re-fetch page_html if missing from DB (uses FireCrawl)")
    parser.add_argument("--visual", action="store_true", help="Render phase screenshots and compute SSIM scores")
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
            "id, url, page_markdown, page_html, screenshot_storage_path"
        ).eq("id", args.page_id).single().execute()
        analysis = result.data
    elif args.url:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, page_html, screenshot_storage_path"
        ).like("url", f"%{args.url}%").not_.is_(
            "screenshot_storage_path", "null"
        ).order("created_at", desc=True).limit(1).execute()
        if not result.data:
            logger.error(f"No analyses found for URL matching: {args.url}")
            sys.exit(1)
        analysis = result.data[0]
    else:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, page_html, screenshot_storage_path"
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
    page_html = analysis.get("page_html") or None
    screenshot_path = analysis.get("screenshot_storage_path")

    logger.info(f"Testing page: {url}")
    logger.info(f"Analysis ID: {page_id}")
    logger.info(f"Markdown length: {len(markdown)} chars")
    logger.info(f"page_html: {'yes' if page_html else 'no'} ({len(page_html) if page_html else 0} chars)")

    # Re-fetch page_html if missing and --rescrape requested
    if not page_html and args.rescrape and url and url.startswith("http"):
        logger.info("page_html missing — re-scraping HTML from URL...")
        try:
            from viraltracker.services.web_scraping_service import WebScrapingService
            scraper = WebScrapingService()
            html_result = scraper.scrape_url(
                url, formats=["html"], only_main_content=False, wait_for=2000,
            )
            page_html = html_result.html or None
            if page_html:
                logger.info(f"Re-scraped page_html: {len(page_html)} chars")
                # Update DB so future runs don't need --rescrape
                supabase.table("landing_page_analyses").update(
                    {"page_html": page_html}
                ).eq("id", page_id).execute()
                logger.info("Updated DB with fresh page_html")
            else:
                logger.warning("Re-scrape returned empty HTML")
        except Exception as e:
            logger.warning(f"Re-scrape failed: {e}")

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
            page_html=page_html,
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
        page_html=page_html,
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

    # Create run-scoped output directory
    run_dir = _create_run_dir("run")
    logger.info(f"Output directory: {run_dir}")

    # Save run metadata
    run_metadata = {
        "run_id": run_dir.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _get_commit_sha(),
        "args": {
            "page_id": args.page_id,
            "url": args.url,
            "visual": args.visual,
            "single_pass": args.single_pass,
            "rescrape": args.rescrape,
        },
        "pipeline_version": "template_v4",
        "page_url": url,
        "analysis_id": page_id,
    }
    (run_dir / "metadata.json").write_text(json.dumps(run_metadata, indent=2))

    # Write output HTML
    out_path = run_dir / "final_output.html"
    out_path.write_text(multi_html)
    logger.info(f"Output saved to: {out_path}")

    # Also write to legacy location for backward compat
    legacy_path = PROJECT_ROOT / "test_multipass_output.html"
    legacy_path.write_text(multi_html)

    # Save all phase snapshots
    snapshots = mockup_svc.get_phase_snapshots()
    if snapshots:
        logger.info(f"Saving {len(snapshots)} phase snapshots to {run_dir}")
        for key, html in snapshots.items():
            snap_path = run_dir / f"{key}.html"
            snap_path.write_text(html)
            logger.info(f"  {key}: {len(html)} chars -> {snap_path.name}")

        # Visual scoring (--visual flag)
        visual_scores = {}
        if args.visual:
            logger.info("")
            logger.info("=" * 60)
            logger.info("VISUAL FIDELITY (SSIM)")
            logger.info("=" * 60)
            try:
                from viraltracker.services.landing_page_analysis.multipass.html_renderer import (
                    render_html_to_png,
                )
                from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
                    score_visual_fidelity,
                )

                phase_order = [
                    "phase_1_skeleton",
                    "phase_2_content",
                    "phase_3_refined",
                    "phase_4_final",
                ]
                prev_ssim = None
                for phase_key in phase_order:
                    phase_html = snapshots.get(phase_key)
                    if not phase_html:
                        continue
                    rendered_png = render_html_to_png(phase_html)
                    if rendered_png and screenshot_bytes:
                        # Save rendered PNG
                        (run_dir / f"{phase_key}_render.png").write_bytes(rendered_png)
                        ssim = score_visual_fidelity(screenshot_bytes, rendered_png)
                        visual_scores[phase_key] = ssim
                        delta_str = ""
                        if prev_ssim is not None:
                            delta = ssim - prev_ssim
                            delta_str = f"  (delta: {delta:+.4f})"
                        logger.info(f"  {phase_key}: {ssim:.4f}{delta_str}")
                        prev_ssim = ssim
                    elif not rendered_png:
                        logger.warning(f"  {phase_key}: rendering failed")

                # Determine trajectory
                if len(visual_scores) >= 2:
                    values = list(visual_scores.values())
                    improving = sum(1 for i in range(1, len(values)) if values[i] > values[i-1])
                    regressing = sum(1 for i in range(1, len(values)) if values[i] < values[i-1])
                    if improving > regressing:
                        trajectory = "improving"
                    elif regressing > improving:
                        trajectory = "regressing"
                    else:
                        trajectory = "flat"
                    logger.info(f"  Trajectory: {trajectory}")
                else:
                    trajectory = None

            except ImportError as e:
                logger.warning(f"Visual scoring unavailable: {e}")
                trajectory = None
            except Exception as e:
                logger.error(f"Visual scoring failed: {e}")
                trajectory = None

        # Run phase diagnostics
        from viraltracker.services.landing_page_analysis.multipass.phase_diagnostics import (
            diagnose_phases,
            print_diagnostic_report,
        )

        report = diagnose_phases(
            snapshots,
            source_markdown=markdown or "",
            expected_section_count=section_count,
        )

        # Attach visual scores to report
        if visual_scores:
            report.visual_scores = visual_scores
            report.visual_trajectory = trajectory if args.visual else None

        print()
        print_diagnostic_report(report)

        # Save diagnostic report as JSON
        report_path = run_dir / "diagnostic_report.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))
        logger.info(f"Diagnostic report saved to: {report_path}")
    else:
        logger.info("No phase snapshots available")


if __name__ == "__main__":
    main()
