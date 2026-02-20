#!/usr/bin/env python3
"""CLI benchmark runner for multipass eval harness.

Runs multipass pipeline against 5+ stored benchmark pages and evaluates
quality metrics against go-live thresholds.

Usage:
    python scripts/eval_multipass.py [--pages PAGE_IDS] [--verbose]

Requires:
    - Stored benchmark pages in the database (with screenshots + markdown)
    - playwright + scikit-image for visual fidelity (optional)
"""

import argparse
import json
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run multipass pipeline benchmark")
    parser.add_argument(
        "--pages",
        nargs="+",
        help="Specific page/analysis IDs to benchmark (default: latest 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output with per-page details",
    )
    parser.add_argument(
        "--skip-visual",
        action="store_true",
        help="Skip visual fidelity scoring (no Playwright needed)",
    )
    args = parser.parse_args()

    try:
        from viraltracker.services.landing_page_analysis.multipass.eval_harness import (
            evaluate_benchmark,
            evaluate_page,
        )
        from viraltracker.services.landing_page_analysis.mockup_service import MockupService
        from viraltracker.services.landing_page_analysis.analysis_service import LandingPageAnalysisService
        from viraltracker.core.database import get_supabase_client
    except ImportError as e:
        logger.error(f"Import failed: {e}")
        logger.error("Make sure you're in the viraltracker project directory")
        sys.exit(1)

    # Get benchmark pages
    supabase = get_supabase_client()
    analysis_svc = LandingPageAnalysisService(supabase)
    mockup_svc = MockupService()

    if args.pages:
        page_ids = args.pages
    else:
        # Get latest 5 analyses with screenshots
        try:
            result = supabase.table("landing_page_analyses").select(
                "id, url, page_markdown, screenshot_storage_path"
            ).not_.is_("screenshot_storage_path", "null").order(
                "created_at", desc=True
            ).limit(5).execute()
            page_ids = [r["id"] for r in result.data]
        except Exception as e:
            logger.error(f"Failed to fetch benchmark pages: {e}")
            sys.exit(1)

    if not page_ids:
        logger.error("No benchmark pages found. Analyze some pages first.")
        sys.exit(1)

    logger.info(f"Benchmarking {len(page_ids)} pages...")

    page_scores = []
    for page_id in page_ids:
        try:
            # Fetch analysis
            result = supabase.table("landing_page_analyses").select("*").eq("id", page_id).single().execute()
            analysis = result.data

            url = analysis.get("url", "unknown")
            markdown = analysis.get("page_markdown", "")
            screenshot_path = analysis.get("screenshot_storage_path")

            logger.info(f"  [{page_id[:8]}] {url}")

            # Load screenshot
            screenshot_b64 = None
            screenshot_bytes = None
            if screenshot_path:
                screenshot_bytes = analysis_svc._load_screenshot(screenshot_path)
                if screenshot_bytes:
                    import base64
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

            if not screenshot_b64:
                logger.warning(f"    No screenshot, skipping")
                continue

            # Run single-pass
            logger.info("    Running single-pass...")
            start = time.time()
            single_html = mockup_svc.generate_analysis_mockup(
                screenshot_b64=screenshot_b64,
                page_markdown=markdown,
                page_url=url,
                use_multipass=False,
            )
            single_time = time.time() - start

            # Run multi-pass
            logger.info("    Running multi-pass...")
            start = time.time()
            multi_html = mockup_svc.generate_analysis_mockup(
                screenshot_b64=screenshot_b64,
                page_markdown=markdown,
                page_url=url,
                use_multipass=True,
            )
            multi_time = time.time() - start

            # Evaluate
            score = evaluate_page(
                page_url=url,
                multipass_html=multi_html,
                single_pass_html=single_html,
                source_markdown=markdown,
                latency_seconds=multi_time,
                mockup_service=mockup_svc,
            )

            page_scores.append(score)

            if args.verbose:
                logger.info(f"    Slots: {score.slot_count} (vs {score.single_pass_slot_count} single-pass)")
                logger.info(f"    Retention: {score.slot_retention:.0%}")
                logger.info(f"    Text fidelity: {score.text_fidelity:.3f}")
                logger.info(f"    Latency: {multi_time:.1f}s (single: {single_time:.1f}s)")
                if score.issues:
                    for issue in score.issues:
                        logger.warning(f"    ISSUE: {issue}")

        except Exception as e:
            logger.error(f"  Failed to evaluate {page_id}: {e}")

    # Aggregate results
    if not page_scores:
        logger.error("No pages were successfully evaluated")
        sys.exit(1)

    result = evaluate_benchmark(page_scores)

    # Print summary
    print("\n" + "=" * 60)
    print("MULTIPASS BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Pages evaluated: {len(page_scores)}")
    print(f"Verdict: {'PASS' if result.passed else 'FAIL'}")

    if result.failures:
        print("\nFailures:")
        for f in result.failures:
            print(f"  - {f}")

    print()
    avg_slots = sum(s.slot_count for s in page_scores) / len(page_scores)
    avg_retention = sum(s.slot_retention for s in page_scores) / len(page_scores)
    avg_fidelity = sum(s.text_fidelity for s in page_scores) / len(page_scores)
    avg_latency = sum(s.latency_seconds for s in page_scores) / len(page_scores)

    print(f"Avg slots:     {avg_slots:.1f}")
    print(f"Avg retention: {avg_retention:.0%}")
    print(f"Avg text fid:  {avg_fidelity:.3f}")
    print(f"Avg latency:   {avg_latency:.1f}s")
    print("=" * 60)

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
