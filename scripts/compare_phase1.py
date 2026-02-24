#!/usr/bin/env python3
"""A/B comparison between template and v2 Phase 1 skeletons.

Runs both pipelines on the same page and compares:
- Skeleton HTML size and structure
- Placeholder coverage
- Layout classification consistency
- Sub-step timings (v2 only)

Usage:
    PYTHONPATH=. python scripts/compare_phase1.py --url "https://example.com/landing"
    PYTHONPATH=. python scripts/compare_phase1.py --page-id <uuid>
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
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


def _count_placeholders(html: str) -> int:
    return len(re.findall(r'\{\{sec_\d+[^}]*\}\}', html))


def _count_sections(html: str) -> int:
    return len(re.findall(r'data-section="sec_\d+"', html))


def _css_size(html: str) -> int:
    total = 0
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.DOTALL):
        total += len(m.group(1))
    return total


def _analyze_skeleton(html: str, label: str) -> dict:
    """Analyze a skeleton HTML and return metrics."""
    return {
        "label": label,
        "html_size": len(html),
        "section_count": _count_sections(html),
        "placeholder_count": _count_placeholders(html),
        "css_size": _css_size(html),
        "has_style": "<style" in html.lower(),
        "has_mp_classes": ".mp-container" in html or ".mp-grid" in html,
    }


async def run_comparison(analysis: dict) -> dict:
    """Run both template and v2 pipelines and compare."""
    from viraltracker.services.gemini_service import GeminiService
    from viraltracker.services.landing_page_analysis.multipass.pipeline import (
        MultiPassPipeline,
    )

    gemini = GeminiService()
    screenshot_b64 = analysis["screenshot_b64"]
    page_markdown = analysis["page_markdown"]
    page_html = analysis.get("page_html", "")
    page_url = analysis.get("url", "")

    results = {}

    for mode in ("template", "v2"):
        logger.info(f"\n{'='*60}\nRunning Phase 1 mode: {mode}\n{'='*60}")
        os.environ["MULTIPASS_PHASE1_MODE"] = mode

        # Re-import to pick up env var (module-level constant)
        import importlib
        import viraltracker.services.landing_page_analysis.multipass.pipeline as pipe_mod
        importlib.reload(pipe_mod)

        pipeline = pipe_mod.MultiPassPipeline(gemini)
        t0 = time.time()

        try:
            html = await pipeline.generate(
                screenshot_b64=screenshot_b64,
                page_markdown=page_markdown,
                page_url=page_url,
                page_html=page_html,
            )
            elapsed = time.time() - t0

            skeleton = pipeline.phase_snapshots.get("phase_1_skeleton", "")
            metrics = _analyze_skeleton(skeleton, mode)
            metrics["total_time"] = elapsed
            metrics["api_calls"] = pipeline._limiter.call_count

            # v2-specific telemetry
            if mode == "v2":
                v2_tel = pipeline.phase_snapshots.get("phase_1_v2_telemetry", "")
                if v2_tel:
                    try:
                        code_match = re.search(r'<code>(.*?)</code>', v2_tel, re.DOTALL)
                        if code_match:
                            metrics["v2_telemetry"] = json.loads(code_match.group(1))
                    except Exception:
                        pass

            # Layout map snapshot
            layout_snap = pipeline.phase_snapshots.get("phase_1_layout_map", "")
            if layout_snap:
                try:
                    code_match = re.search(r'<code>(.*?)</code>', layout_snap, re.DOTALL)
                    if code_match:
                        metrics["layout_map"] = json.loads(code_match.group(1))
                except Exception:
                    pass

            results[mode] = metrics
            logger.info(f"{mode} completed in {elapsed:.1f}s, {metrics['section_count']} sections")

        except Exception as e:
            logger.error(f"{mode} failed: {e}")
            results[mode] = {"label": mode, "error": str(e)}

    return results


def print_comparison(results: dict, url: str):
    """Print side-by-side comparison."""
    print(f"\n{'='*70}")
    print(f"Phase 1 A/B Comparison: {url}")
    print(f"{'='*70}\n")

    header = f"{'Metric':<30s} {'template':>15s} {'v2':>15s} {'delta':>10s}"
    print(header)
    print("-" * 70)

    fields = [
        ("HTML size (chars)", "html_size"),
        ("Section count", "section_count"),
        ("Placeholder count", "placeholder_count"),
        ("CSS size (chars)", "css_size"),
        ("Has mp-* classes", "has_mp_classes"),
        ("API calls", "api_calls"),
        ("Total time (s)", "total_time"),
    ]

    for label, key in fields:
        t_val = results.get("template", {}).get(key, "N/A")
        v2_val = results.get("v2", {}).get(key, "N/A")

        if isinstance(t_val, float):
            t_str = f"{t_val:.1f}"
            v2_str = f"{v2_val:.1f}" if isinstance(v2_val, (int, float)) else str(v2_val)
            delta = f"{v2_val - t_val:+.1f}" if isinstance(v2_val, (int, float)) else ""
        elif isinstance(t_val, bool):
            t_str = str(t_val)
            v2_str = str(v2_val)
            delta = ""
        elif isinstance(t_val, int):
            t_str = str(t_val)
            v2_str = str(v2_val)
            delta = f"{v2_val - t_val:+d}" if isinstance(v2_val, int) else ""
        else:
            t_str = str(t_val)
            v2_str = str(v2_val)
            delta = ""

        print(f"{label:<30s} {t_str:>15s} {v2_str:>15s} {delta:>10s}")

    # v2 telemetry
    v2_tel = results.get("v2", {}).get("v2_telemetry")
    if v2_tel:
        print(f"\n{'v2 Sub-step Timings':}")
        print("-" * 40)
        for step, elapsed in v2_tel.get("step_timings", {}).items():
            print(f"  {step:<30s} {elapsed:.2f}s")
        print(f"  {'fallback_level':<30s} {v2_tel.get('fallback_level', '?')}")

    # Layout classifications comparison
    for mode in ("template", "v2"):
        lm = results.get(mode, {}).get("layout_map")
        if lm:
            print(f"\n{mode} Layout Classifications:")
            for sec_id in sorted(lm.keys()):
                info = lm[sec_id]
                lt = info.get("layout_type", "?")
                cols = info.get("column_count", "?")
                print(f"  {sec_id}: {lt} (cols={cols})")

    print()


def main():
    parser = argparse.ArgumentParser(description="A/B compare Phase 1 modes")
    parser.add_argument("--page-id", help="Specific analysis ID")
    parser.add_argument("--url", help="Find most recent analysis for this URL")
    args = parser.parse_args()

    from viraltracker.core.database import get_supabase_client

    supabase = get_supabase_client()

    if args.page_id:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, page_html, screenshot_storage_path"
        ).eq("id", args.page_id).single().execute()
        analysis = result.data
    elif args.url:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, page_html, screenshot_storage_path"
        ).eq("url", args.url).order(
            "created_at", desc=True
        ).limit(1).execute()
        if not result.data:
            logger.error(f"No analysis found for URL: {args.url}")
            sys.exit(1)
        analysis = result.data[0]
    else:
        result = supabase.table("landing_page_analyses").select(
            "id, url, page_markdown, page_html, screenshot_storage_path"
        ).order("created_at", desc=True).limit(1).execute()
        if not result.data:
            logger.error("No analyses found")
            sys.exit(1)
        analysis = result.data[0]

    logger.info(f"Testing page: {analysis['url']} (ID: {analysis['id']})")

    # Get screenshot
    storage_path = analysis.get("screenshot_storage_path")
    if not storage_path:
        logger.error("No screenshot available for this analysis")
        sys.exit(1)

    try:
        screenshot_bytes = supabase.storage.from_("screenshots").download(storage_path)
        analysis["screenshot_b64"] = base64.b64encode(screenshot_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to download screenshot: {e}")
        sys.exit(1)

    results = asyncio.run(run_comparison(analysis))
    print_comparison(results, analysis["url"])


if __name__ == "__main__":
    main()
