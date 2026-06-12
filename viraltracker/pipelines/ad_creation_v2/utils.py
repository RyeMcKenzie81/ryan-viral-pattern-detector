"""Shared utilities for Ad Creation V2 pipeline nodes."""

import asyncio
import os
from typing import Any, Awaitable, Callable, List, Sequence
from uuid import UUID

# Per-job parallelism for the per-ad pipeline loops (generate / defect-scan /
# review). Default 1 = the historical strictly-sequential behavior; raise via
# the AD_PIPELINE_MAX_CONCURRENCY env var on the worker (mirrors
# CLASSIFIER_MAX_CONCURRENCY).
#
# Rate metering: generate + defect-scan share the pipeline's ctx.deps.gemini
# instance (one reservation limiter). The review stage's conditional Stage-3
# Gemini call and visual-descriptor extraction still construct their own
# clients (pre-existing; see the analyze_image kwarg follow-up) — size N with
# that in mind. Sizing note: each in-flight image generation occupies a thread
# in asyncio's default executor (min(32, cpus+4) threads, shared with storage
# I/O), so worker job-pool x N should stay comfortably below that cap.
AD_PIPELINE_CONCURRENCY_ENV = "AD_PIPELINE_MAX_CONCURRENCY"


def pipeline_concurrency() -> int:
    """Per-ad concurrency for V2 pipeline loops (>=1; garbage env -> 1)."""
    try:
        return max(1, int(os.getenv(AD_PIPELINE_CONCURRENCY_ENV, "1")))
    except ValueError:
        return 1


async def bounded_gather(
    items: Sequence[Any],
    worker: Callable[[Any], Awaitable[Any]],
    concurrency: int,
) -> List[Any]:
    """Run ``worker(item)`` for every item with at most ``concurrency`` in flight.

    Results come back in ITEM order regardless of completion order, so callers
    keep stable prompt_index ordering. At concurrency<=1 this is a plain
    sequential loop — byte-identical behavior (and side-effect ordering) to the
    historical code path.

    Workers are expected to catch their own per-item exceptions and return a
    failure record (the V2 loops already do). If one does raise, the exception
    is re-raised AFTER all other workers finish, so no task is orphaned mid-write.
    """
    if concurrency <= 1:
        return [await worker(item) for item in items]
    sem = asyncio.Semaphore(concurrency)

    async def _run(item: Any) -> Any:
        async with sem:
            return await worker(item)

    results = await asyncio.gather(*(_run(item) for item in items), return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return list(results)


def stringify_uuids(obj: Any) -> Any:
    """Recursively convert UUID values to strings in dicts/lists."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: stringify_uuids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_uuids(v) for v in obj]
    return obj
