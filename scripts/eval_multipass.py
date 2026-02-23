#!/usr/bin/env python3
"""CLI benchmark runner for multipass eval harness.

Runs multipass pipeline against 5+ stored benchmark pages and evaluates
quality metrics against go-live thresholds.

Usage:
    python scripts/eval_multipass.py [--pages PAGE_IDS] [--verbose] [--skip-visual]

Requires:
    - Stored benchmark pages in the database (with screenshots + markdown)
    - playwright + scikit-image for visual fidelity (optional, skipped with --skip-visual)
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_BASE = PROJECT_ROOT / "test_multipass_snapshots"


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


def _create_run_dir(prefix: str = "bench") -> Path:
    """Create a timestamped run directory under SNAPSHOTS_BASE.

    Returns the path to the new directory.
    """
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
            score_visual_fidelity,
        )
        from viraltracker.services.landing_page_analysis.mockup_service import MockupService
        from viraltracker.services.landing_page_analysis.analysis_service import LandingPageAnalysisService
        from viraltracker.core.database import get_supabase_client
    except ImportError as e:
        logger.error(f"Import failed: {e}")
        logger.error("Make sure you're in the viraltracker project directory")
        sys.exit(1)

    # Lazy import for visual scoring
    render_html_to_png = None
    if not args.skip_visual:
        try:
            from viraltracker.services.landing_page_analysis.multipass.html_renderer import (
                render_html_to_png as _render,
            )
            render_html_to_png = _render
        except ImportError:
            logger.warning("html_renderer not available, skipping visual scoring")

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

    # Create run-scoped output directory
    run_dir = _create_run_dir("bench")
    logger.info(f"Output directory: {run_dir}")

    # Run-level metadata
    run_metadata = {
        "run_id": run_dir.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _get_commit_sha(),
        "args": {
            "skip_visual": args.skip_visual,
            "verbose": args.verbose,
            "pages": args.pages,
        },
        "pipeline_version": "template_v4",
        "page_ids": page_ids,
    }
    (run_dir / "metadata.json").write_text(json.dumps(run_metadata, indent=2))

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

            # Create page subdirectory
            page_dir = run_dir / f"page_{page_id[:8]}"
            page_dir.mkdir(exist_ok=True)
            (page_dir / "metadata.json").write_text(json.dumps({
                "page_id": page_id,
                "url": url,
            }, indent=2))

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

            # Visual scoring
            multipass_screenshot = None
            single_pass_screenshot = None

            if render_html_to_png and not args.skip_visual:
                logger.info("    Rendering screenshots for visual scoring...")
                multipass_screenshot = render_html_to_png(multi_html)
                single_pass_screenshot = render_html_to_png(single_html)

                # Save rendered PNGs
                if multipass_screenshot:
                    (page_dir / "multipass_render.png").write_bytes(multipass_screenshot)
                if single_pass_screenshot:
                    (page_dir / "single_pass_render.png").write_bytes(single_pass_screenshot)

            # Use cleaned markdown for fidelity if available (extract mode)
            eval_snapshots = mockup_svc.get_phase_snapshots()
            eval_cleaned_md = eval_snapshots.pop("_cleaned_markdown", None) or markdown

            # Evaluate
            score = evaluate_page(
                page_url=url,
                multipass_html=multi_html,
                single_pass_html=single_html,
                source_markdown=eval_cleaned_md,
                latency_seconds=multi_time,
                mockup_service=mockup_svc,
                original_screenshot=screenshot_bytes,
                multipass_screenshot=multipass_screenshot,
                single_pass_screenshot=single_pass_screenshot,
            )

            # Per-phase SSIM trajectory
            phase_visual_scores = {}
            if render_html_to_png and not args.skip_visual and screenshot_bytes:
                snapshots = mockup_svc.get_phase_snapshots()
                if snapshots:
                    phase_order = [
                        "phase_1_skeleton",
                        "phase_2_content",
                        "phase_3_refined",
                        "phase_4_final",
                    ]
                    for phase_key in phase_order:
                        phase_html = snapshots.get(phase_key)
                        if not phase_html:
                            continue
                        # Save phase HTML
                        (page_dir / f"{phase_key}.html").write_text(phase_html)
                        rendered_png = render_html_to_png(phase_html)
                        if rendered_png:
                            (page_dir / f"{phase_key}_render.png").write_bytes(rendered_png)
                            try:
                                ssim = score_visual_fidelity(screenshot_bytes, rendered_png)
                                phase_visual_scores[phase_key] = ssim
                            except Exception as e:
                                logger.warning(f"    SSIM failed for {phase_key}: {e}")

                    if phase_visual_scores:
                        logger.info("    SSIM trajectory:")
                        for pk, sv in sorted(phase_visual_scores.items()):
                            logger.info(f"      {pk}: {sv:.4f}")

            # Save page diagnostic report
            page_report = {
                "page_id": page_id,
                "url": url,
                "score": {
                    "slot_count": score.slot_count,
                    "single_pass_slot_count": score.single_pass_slot_count,
                    "slot_retention": score.slot_retention,
                    "text_fidelity": score.text_fidelity,
                    "visual_ssim": score.visual_ssim,
                    "single_pass_ssim": score.single_pass_ssim,
                    "blueprint_round_trip": score.blueprint_round_trip,
                    "latency_seconds": score.latency_seconds,
                    "issues": score.issues,
                },
                "phase_visual_scores": phase_visual_scores,
            }
            (page_dir / "diagnostic_report.json").write_text(
                json.dumps(page_report, indent=2)
            )

            page_scores.append(score)

            if args.verbose:
                logger.info(f"    Slots: {score.slot_count} (vs {score.single_pass_slot_count} single-pass)")
                logger.info(f"    Retention: {score.slot_retention:.0%}")
                logger.info(f"    Text fidelity: {score.text_fidelity:.3f}")
                if score.visual_ssim is not None:
                    logger.info(f"    Visual SSIM: {score.visual_ssim:.4f}")
                if score.single_pass_ssim is not None:
                    logger.info(f"    Single-pass SSIM: {score.single_pass_ssim:.4f}")
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
    print(f"Output: {run_dir}")
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

    # Visual summary
    ssim_scores = [s for s in page_scores if s.visual_ssim is not None]
    if ssim_scores:
        avg_ssim = sum(s.visual_ssim for s in ssim_scores) / len(ssim_scores)
        print(f"Avg SSIM:      {avg_ssim:.4f}")

    print("=" * 60)

    # Save benchmark summary
    summary = {
        "verdict": "PASS" if result.passed else "FAIL",
        "pages_evaluated": len(page_scores),
        "failures": result.failures,
        "averages": {
            "slots": avg_slots,
            "retention": avg_retention,
            "text_fidelity": avg_fidelity,
            "latency_seconds": avg_latency,
        },
    }
    if ssim_scores:
        summary["averages"]["visual_ssim"] = sum(s.visual_ssim for s in ssim_scores) / len(ssim_scores)

    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2))

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
