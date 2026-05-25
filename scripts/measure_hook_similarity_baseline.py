#!/usr/bin/env python3
"""
Measure hook similarity baseline for current AC2 output.

Calibrates INTRA_ANGLE_THRESHOLD for the angle-driven-ad-creator V1.
We need to know how similar AC2's hooks currently cluster within a single
ad_run before we can set a threshold that distinguishes "improved by angle
diversification" from "no different than before."

Process:
  1. Pull generated_ads.hook_text from the last 30 days, grouped by ad_run_id.
  2. For each ad_run with >= 3 hooks, embed hooks via OpenAI text-embedding-3-small.
  3. Compute mean pairwise cosine similarity within each ad_run.
  4. Aggregate: overall mean + p25/p50/p75 distribution.
  5. Write CSV per ad_run + summary line to stdout.

Output CSV columns:
  ad_run_id, product_id, created_at, n_hooks, mean_pairwise_similarity

Output file:
  docs/plans/angle-driven-ad-creator/BASELINE_SIMILARITY.csv (default)

Usage:
    python scripts/measure_hook_similarity_baseline.py [--days 30] [--min-hooks 3] [--output PATH] [--dry-run]

Reads OPENAI_API_KEY from env (via openai.OpenAI() default behavior).
Reads Supabase credentials via viraltracker.core.database.get_supabase_client().
"""

import argparse
import csv
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = "docs/plans/angle-driven-ad-creator/BASELINE_SIMILARITY.csv"
EMBEDDING_BATCH_SIZE = 100  # OpenAI batch size; pattern_discovery_service uses 100


def fetch_hook_groups(supabase, days: int, min_hooks: int):
    """
    Fetch generated_ads.hook_text grouped by ad_run from the last `days` days,
    keeping only ad_runs with >= min_hooks rows.

    Returns:
        List of dicts: {ad_run_id, product_id, created_at, hooks: [str, ...]}
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Pull recent ad_runs with their product_id
    runs = (
        supabase.table("ad_runs")
        .select("id, product_id, created_at")
        .gte("created_at", since)
        .execute()
        .data
        or []
    )
    logger.info(f"Found {len(runs)} ad_runs in the last {days} days")

    groups = []
    for run in runs:
        ads = (
            supabase.table("generated_ads")
            .select("hook_text")
            .eq("ad_run_id", run["id"])
            .not_.is_("hook_text", "null")
            .execute()
            .data
            or []
        )
        hooks = [a["hook_text"].strip() for a in ads if a.get("hook_text") and a["hook_text"].strip()]
        if len(hooks) >= min_hooks:
            groups.append(
                {
                    "ad_run_id": run["id"],
                    "product_id": run.get("product_id"),
                    "created_at": run.get("created_at"),
                    "hooks": hooks,
                }
            )

    logger.info(
        f"Kept {len(groups)} ad_runs with >= {min_hooks} hooks "
        f"(out of {len(runs)} total)"
    )
    return groups


def embed_hooks(openai_client, hooks: list, batch_size: int = EMBEDDING_BATCH_SIZE):
    """
    Embed a list of hook strings via OpenAI text-embedding-3-small in batches.

    Mirrors the pattern in viraltracker/services/pattern_discovery_service.py
    so we're consistent with how angle_candidates / discovered_patterns are
    embedded today.

    Returns:
        List of embedding vectors (List[float]). Failed embeddings raise.
    """
    embeddings = []
    for i in range(0, len(hooks), batch_size):
        batch = hooks[i:i + batch_size]
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=batch,
        )
        embeddings.extend([d.embedding for d in response.data])
    return embeddings


def mean_pairwise_cosine(vectors: list) -> float:
    """
    Compute the mean of pairwise cosine similarities across `vectors`.

    For N vectors, this is mean of N*(N-1)/2 pairs.
    Returns NaN if fewer than 2 vectors provided.
    """
    if len(vectors) < 2:
        return float("nan")

    mat = np.array(vectors, dtype=np.float32)
    # Normalize once (cosine = dot product of normalized vectors)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    normalized = mat / np.where(norms == 0, 1, norms)

    # Pairwise cosine = normalized @ normalized.T; we want the upper triangle excluding diagonal
    sim_matrix = normalized @ normalized.T
    iu = np.triu_indices_from(sim_matrix, k=1)
    return float(np.mean(sim_matrix[iu]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="Look back window in days (default: 30)")
    parser.add_argument(
        "--min-hooks",
        type=int,
        default=3,
        help="Minimum hooks per ad_run to include (default: 3 — pairwise is meaningless below this)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report counts but do not embed or write output",
    )
    args = parser.parse_args()

    # Lazy imports so --help works without env vars set
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()

    groups = fetch_hook_groups(supabase, days=args.days, min_hooks=args.min_hooks)
    if not groups:
        logger.info("No qualifying ad_runs found. Exiting.")
        return 0

    total_hooks = sum(len(g["hooks"]) for g in groups)
    logger.info(f"Total hooks to embed: {total_hooks}")

    if args.dry_run:
        logger.info(
            "Dry run — would embed %d hooks across %d ad_runs",
            total_hooks,
            len(groups),
        )
        return 0

    import openai
    openai_client = openai.OpenAI()

    # Embed all hooks (one big batched call across all groups for efficiency)
    flat_hooks = []
    group_slices = []  # (start, end) per group
    for g in groups:
        start = len(flat_hooks)
        flat_hooks.extend(g["hooks"])
        group_slices.append((start, len(flat_hooks)))

    logger.info(f"Embedding {len(flat_hooks)} hooks in batches of {EMBEDDING_BATCH_SIZE}...")
    try:
        all_embeddings = embed_hooks(openai_client, flat_hooks, batch_size=EMBEDDING_BATCH_SIZE)
    except Exception as e:
        logger.error(f"Embedding API call failed: {e}")
        return 1

    if len(all_embeddings) != len(flat_hooks):
        logger.error(
            f"Embedding count mismatch: got {len(all_embeddings)}, expected {len(flat_hooks)}"
        )
        return 1

    # Compute mean pairwise similarity per group
    rows = []
    for g, (start, end) in zip(groups, group_slices):
        vectors = all_embeddings[start:end]
        sim = mean_pairwise_cosine(vectors)
        rows.append(
            {
                "ad_run_id": g["ad_run_id"],
                "product_id": g["product_id"],
                "created_at": g["created_at"],
                "n_hooks": len(g["hooks"]),
                "mean_pairwise_similarity": round(sim, 4),
            }
        )

    # Write CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ad_run_id", "product_id", "created_at", "n_hooks", "mean_pairwise_similarity"],
        )
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Wrote {len(rows)} rows to {output_path}")

    # Summary stats
    sims = [r["mean_pairwise_similarity"] for r in rows]
    sims_sorted = sorted(sims)
    n = len(sims_sorted)
    p25 = sims_sorted[int(n * 0.25)] if n else float("nan")
    p50 = sims_sorted[int(n * 0.50)] if n else float("nan")
    p75 = sims_sorted[int(n * 0.75)] if n else float("nan")
    overall_mean = mean(sims) if sims else float("nan")

    logger.info("=" * 60)
    logger.info("SUMMARY (current AC2 baseline)")
    logger.info(f"  ad_runs analyzed:           {len(rows)}")
    logger.info(f"  total hooks embedded:       {total_hooks}")
    logger.info(f"  mean intra-run similarity:  {overall_mean:.4f}")
    logger.info(f"  p25:                        {p25:.4f}")
    logger.info(f"  p50 (median):               {p50:.4f}")
    logger.info(f"  p75:                        {p75:.4f}")
    logger.info("=" * 60)
    logger.info(
        "INTRA_ANGLE_THRESHOLD calibration: set the default ~0.05 below the median "
        "(or ~0.10 below if you want tighter rejection). Update "
        "system_settings.angle_pipeline.intra_angle_threshold accordingly before V1 launch."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
