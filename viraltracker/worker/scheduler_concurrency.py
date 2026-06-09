"""
Scheduler concurrency primitives.

PR 1 of 2 (scheduler worker upgrade) — these are the building blocks for the
worker pool. They are DORMANT in PR 1: nothing in scheduler_worker.py calls
into this module yet. PR 2 flips run_scheduler() to use claim_next_job() and
worker_loop() instead of the legacy get_due_jobs() + execute_job() path.

Architecture / decisions:
  ~/.gstack/projects/RyeMcKenzie81-ryan-viral-pattern-detector/
    ryemckenzie-RyeMcKenzie81-scheduler-worker-upgrade-design-20260528-111848.md

Smoke tests (run 2026-05-28, both PASS):
  /tmp/smoke_asyncio_to_thread.py
  /tmp/smoke_supabase_rpc_lock.py

Two-table model (do NOT conflate):
  scheduled_jobs       — lifecycle: active/paused/completed (read by UI)
  scheduled_job_runs   — execution: pending/running/completed/failed (claim lives here)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Constants / config
# ============================================================================

# PR 2 default: 2 workers. User chose 2 as a conservative initial bump from 1;
# can be raised via env var without redeploy. Setting to 1 restores
# single-worker behavior identical to pre-upgrade.
DEFAULT_POOL_SIZE = int(os.environ.get("SCHEDULER_POOL_SIZE", "2"))

# How long the no-work / cap-hit backoff is. Lower = lower latency, higher
# DB load when the queue is empty. 2s is a sane idle cadence.
IDLE_BACKOFF_SECONDS = 2.0
CAP_HIT_BACKOFF_SECONDS = 0.5

# Recovery cadence + jitter. Jitter prevents multiple containers from firing
# recovery at the same instant after a deploy.
RECOVERY_INTERVAL_SECONDS = 60.0
RECOVERY_JITTER_MAX_SECONDS = 30.0

# get_caps in-process cache TTL. Cap changes via UI are visible within this
# window. Trading admin-tool freshness for hot-path DB load.
CAP_CACHE_TTL_SECONDS = 30.0

# How long a saturated (brand, job_type) pair is skipped before re-evaluation.
# This is the LRU starvation guard from the design doc.
SATURATED_TTL_SECONDS = 5.0


# ============================================================================
# Exceptions + signals
# ============================================================================

class CapHit(Exception):
    """Raised by claim_next_job when admission is denied by a cap.

    PR 1 note: the RPC returns an empty result for BOTH no-work and cap-hit.
    The Python wrapper distinguishes via a heuristic (was a candidate visible
    in the queue?) only when worth doing. For now CapHit is reserved for
    explicit cap-hit signals from future SQL revisions; the worker_loop in
    this module treats no-rows as "wait and retry" regardless.
    """


# Module-scope shutdown event. Set by SIGTERM handler in PR 2; in PR 1 nothing
# sets it because nothing uses it yet. Kept separate from the legacy bool
# `shutdown_requested` in scheduler_worker.py (which is bool, not Event) so
# the two systems don't accidentally bind. PR 2 unifies them.
shutdown_requested: asyncio.Event = asyncio.Event()


# ============================================================================
# Worker ID
# ============================================================================

# Per-process boot ID, generated once at module import. Format `{hex}:{slot}`
# means worker IDs don't collide across restarts (boot_id changes each start)
# and we can see which slot inside which boot took which run.
_BOOT_ID = secrets.token_hex(4)  # e.g. "a1b2c3d4"


def make_worker_id(slot: int) -> str:
    """Build a per-slot worker_id, e.g. 'a1b2c3d4:0'."""
    return f"{_BOOT_ID}:{slot}"


def boot_id() -> str:
    """Expose the boot_id for tests and logging."""
    return _BOOT_ID


# ============================================================================
# JOB_HANDLERS registry
# ============================================================================
#
# Replaces the giant elif chain in execute_job(). Registration via decorator
# fails loudly on duplicate job_type, so adding a new handler without wiring it
# becomes a clear error at import instead of a silent "Unknown job_type" at
# runtime.
#
# In PR 1 the legacy elif dispatcher at scheduler_worker.py:935 stays as the
# active path. The decorators populate this dict additively; nothing breaks if
# the dict is read but execute_job_sync is never called.

JOB_HANDLERS: Dict[str, Callable[..., Any]] = {}


def register_job_handler(job_type: str):
    """Decorator that registers a handler for a job_type.

    Usage:
        @register_job_handler('meta_sync')
        async def execute_meta_sync_job(job: Dict) -> Dict: ...

    Raises RuntimeError at import time if two handlers register the same
    job_type. That's exactly the bug class the registry is meant to catch.
    """
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        existing = JOB_HANDLERS.get(job_type)
        if existing is not None and existing is not fn:
            raise RuntimeError(
                f"Duplicate handler registered for job_type={job_type!r}: "
                f"existing={existing.__module__}.{existing.__qualname__}, "
                f"new={fn.__module__}.{fn.__qualname__}"
            )
        JOB_HANDLERS[job_type] = fn
        return fn
    return deco


def dispatch_job(job_type: str) -> Callable[..., Any]:
    """Look up a handler by job_type. Raises a clear KeyError if missing.

    Not yet called in PR 1 — the legacy execute_job() elif chain is still
    the active dispatcher. PR 2 calls this.
    """
    handler = JOB_HANDLERS.get(job_type)
    if handler is None:
        raise KeyError(
            f"Unknown job_type={job_type!r}. "
            f"Registered: {sorted(JOB_HANDLERS.keys())}"
        )
    return handler


# ============================================================================
# Saturated-pair LRU (starvation guard)
# ============================================================================
#
# When the only ready job is for a saturated (brand, job_type), all workers
# would hot-loop on it: pick, hit cap, rollback, retry. The LRU lets each
# worker remember "this pair was just denied" and skip it for a short TTL.
# Process-wide, shared across all worker tasks; protected by an asyncio.Lock.
# Used by PR 2's worker_loop.

@dataclass
class _SaturatedRegistry:
    """Process-wide map of (brand_id, job_type) → unlock-at timestamp."""
    pairs: Dict[Tuple[str, str], float] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def mark(self, brand_id: str, job_type: str, ttl: float = SATURATED_TTL_SECONDS) -> None:
        async with self.lock:
            self.pairs[(brand_id, job_type)] = time.monotonic() + ttl

    async def is_saturated(self, brand_id: str, job_type: str) -> bool:
        async with self.lock:
            unlock_at = self.pairs.get((brand_id, job_type))
            if unlock_at is None:
                return False
            if time.monotonic() >= unlock_at:
                self.pairs.pop((brand_id, job_type), None)
                return False
            return True

    async def prune(self) -> int:
        """Drop expired entries. Returns count pruned. Useful for tests."""
        async with self.lock:
            now = time.monotonic()
            expired = [k for k, t in self.pairs.items() if now >= t]
            for k in expired:
                self.pairs.pop(k, None)
            return len(expired)


_SATURATED = _SaturatedRegistry()


# ============================================================================
# Cap cache
# ============================================================================
#
# Tiny in-process cache of the cap-decision fields the RPC returns. Caps
# change rarely. Without caching we'd hit job_concurrency_limits N times per
# second under load.

@dataclass
class _CapCache:
    """One-entry cache of the most recent global cap. Per-(brand, job_type)
    caps are cached embedded in the claim result itself, so this is mostly
    for "did caps change in the UI?" sanity reads."""
    last_fetched: float = 0.0
    last_global_cap: Optional[int] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_global_cap(self, fetch_fn: Callable[[], int]) -> int:
        async with self.lock:
            if time.monotonic() - self.last_fetched < CAP_CACHE_TTL_SECONDS and self.last_global_cap is not None:
                return self.last_global_cap
            cap = fetch_fn()
            self.last_global_cap = cap
            self.last_fetched = time.monotonic()
            return cap


_CAP_CACHE = _CapCache()


# ============================================================================
# claim_next_job (async wrapper around the RPC)
# ============================================================================

async def claim_next_job(db: Any, worker_id_text: str) -> Optional[Dict[str, Any]]:
    """Call the claim_next_job RPC. Returns the joined run+job dict or None.

    The supabase-py client is synchronous; we wrap the call in asyncio.to_thread
    so the event loop can continue running other workers (the smoke test
    /tmp/smoke_asyncio_to_thread.py proved this works correctly).

    PR 1 note: nothing in scheduler_worker.py calls this yet. PR 2's run_scheduler
    will.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: db.rpc("claim_next_job", {"worker_id_text": worker_id_text}).execute(),
        )
    except Exception as e:
        logger.exception(f"claim_next_job RPC failed: {e}")
        return None

    rows = getattr(result, "data", None) or []
    if not rows:
        return None
    return rows[0]


# ============================================================================
# Worker loop (skeleton)
# ============================================================================

async def worker_loop(
    db: Any,
    slot: int,
    *,
    execute_fn: Callable[[Dict[str, Any]], Awaitable[Any]],
    poll_idle_seconds: float = IDLE_BACKOFF_SECONDS,
    poll_caphit_seconds: float = CAP_HIT_BACKOFF_SECONDS,
) -> None:
    """One worker task: claim → dispatch → repeat until shutdown_requested.

    Args:
        db: supabase client.
        slot: integer slot index, used to build worker_id.
        execute_fn: async callable `(claimed_row: Dict) -> Awaitable`. The
                    claimed row is the dict returned by the claim_next_job RPC.
                    Called via plain `await` — the caller is responsible for
                    threading sync DB calls (if any) off the event loop. PR 2
                    handlers stay async; sync portions inside block briefly
                    but explicit awaits release the loop for other workers.

    PR 2 callsite: viraltracker/worker/scheduler_worker.py::run_scheduler().
    """
    worker_id_text = make_worker_id(slot)
    logger.info(f"worker_loop start worker_id={worker_id_text}")

    while not shutdown_requested.is_set():
        try:
            claimed = await claim_next_job(db, worker_id_text)
            if claimed is None:
                # Either no work or a cap was hit. Either way: sleep + retry.
                # Use wait_for so a SIGTERM during idle exits promptly instead
                # of waiting the full backoff.
                try:
                    await asyncio.wait_for(
                        shutdown_requested.wait(), timeout=poll_idle_seconds
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            logger.info(
                f"worker {worker_id_text} claimed run_id={claimed.get('run_id')} "
                f"job_id={claimed.get('job_id')} job_type={claimed.get('job_type')} "
                f"brand={claimed.get('brand_id')} "
                f"counts(g/jt/b/bjt)="
                f"{claimed.get('counts_global')}/{claimed.get('counts_job_type')}/"
                f"{claimed.get('counts_brand')}/{claimed.get('counts_brand_jt')} "
                f"caps={claimed.get('cap_global')}/{claimed.get('cap_job_type')}/"
                f"{claimed.get('cap_brand')}/{claimed.get('cap_brand_jt')}"
            )

            await execute_fn(claimed)

        except CapHit:
            await asyncio.sleep(poll_caphit_seconds)
        except Exception:
            logger.exception(f"worker {worker_id_text} loop error")
            await asyncio.sleep(1.0)

    logger.info(f"worker_loop stop worker_id={worker_id_text}")


# ============================================================================
# Recovery loop
# ============================================================================

async def recovery_loop(
    db: Any,
    *,
    interval_seconds: float = RECOVERY_INTERVAL_SECONDS,
    jitter_max_seconds: float = RECOVERY_JITTER_MAX_SECONDS,
    fallback_runtime_seconds: int = 3600,
    extra_sweep: Optional[Callable[[], Any]] = None,
) -> None:
    """Single owner. Runs recover_stuck_runs_v2 every ~interval_seconds.

    Initial sleep is randomized in [0, jitter_max_seconds] so multiple
    containers (or a fast restart) don't fire at the same instant.

    extra_sweep: optional sync callable run (in the executor) after the stuck-
    run RPC each tick — the worker injects heal_orphaned_recurring_jobs here
    (defined in scheduler_worker; passed in to avoid a circular import). Any
    exception is contained: the sweep must never take the recovery loop down.

    Dormant in PR 1.
    """
    await asyncio.sleep(random.uniform(0, jitter_max_seconds))
    while not shutdown_requested.is_set():
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: db.rpc(
                    "recover_stuck_runs_v2",
                    {"fallback_seconds": fallback_runtime_seconds},
                ).execute(),
            )
            rows = getattr(result, "data", None) or []
            if rows:
                logger.warning(
                    f"recovery_loop reset {len(rows)} stuck run(s): "
                    f"{[(r.get('job_type'), r.get('runtime_seconds')) for r in rows]}"
                )
        except Exception:
            logger.exception("recovery_loop error")
        if extra_sweep is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, extra_sweep)
            except Exception:
                logger.exception("recovery_loop extra_sweep error")
        # Use wait_for on shutdown so a graceful stop doesn't wait the full
        # interval before exiting.
        try:
            await asyncio.wait_for(shutdown_requested.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


# ============================================================================
# Reset helpers (test-only)
# ============================================================================

def _reset_for_tests() -> None:
    """Drop in-process state. Tests call this between cases to avoid bleed.
    Not part of the public API.

    Note on shutdown_requested: we REBIND it to a fresh asyncio.Event instead
    of clearing the existing one. asyncio.Event binds to its loop on first
    use, and pytest-asyncio creates a new loop per test — reusing a single
    Event across tests trips "bound to a different event loop" on the second
    test. Rebinding at the module level is safe because the worker_loop and
    recovery_loop functions look up `shutdown_requested` dynamically in the
    module namespace each call, not via a closed-over reference."""
    import sys
    JOB_HANDLERS.clear()
    _SATURATED.pairs.clear()
    _CAP_CACHE.last_fetched = 0.0
    _CAP_CACHE.last_global_cap = None
    sys.modules[__name__].shutdown_requested = asyncio.Event()
