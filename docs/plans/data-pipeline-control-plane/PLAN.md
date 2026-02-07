# Data Pipeline Control Plane — Implementation Plan

## Context

The ChatGPT plan proposed building a parallel ingestion system with new tables (`connector_types`, `brand_connectors`, `ingestion_jobs`, `ingestion_runs`), a new worker, a Celery phase, and a generic "connector" abstraction. After thorough analysis of our actual codebase, **most of this was unnecessary and would create duplicate infrastructure**.

We already have:
- A working scheduler worker (`viraltracker/worker/scheduler_worker.py`, 2400 lines) with 8 job types
- `scheduled_jobs` + `scheduled_job_runs` tables that handle scheduling, execution tracking, and logs
- An Ad Scheduler UI that configures jobs
- A Scheduled Tasks dashboard that shows job status

What was actually missing (the real gaps from tech debt item #13):
1. **No dataset freshness tracking** — nobody knows when data was last refreshed per brand
2. **No readiness gates** — pages don't warn users about stale data
3. **No retries** — failed jobs just schedule the next regular occurrence
4. **No stuck-run recovery** — if the worker crashes mid-run, the run stays "running" forever
5. **No centralized health view** — sync status is scattered across pages
6. **Manual syncs block the UI** — Ad Performance page runs Meta sync in-process
7. **No brand-scoped scheduling dashboard** — must hop to Ad Scheduler to configure jobs

This plan extends the existing infrastructure rather than replacing it.

## Implementation Status

| Phase | Status | Checkpoint |
|-------|--------|------------|
| Phase 1: Dataset Freshness + Banner | **COMPLETE** | CHECKPOINT_001 |
| Phase 2: Queue Manual Meta Sync | **COMPLETE** | CHECKPOINT_001 |
| Phase 3: Pipeline Manager UI | **COMPLETE** | CHECKPOINT_001 |
| Phase 4: Retry + Stuck Recovery | **COMPLETE** | CHECKPOINT_001 |
| Phase 5: FastAPI Endpoint | DEFERRED | — |

## What We Explicitly Did NOT Build

| ChatGPT Proposed | Why We Skipped It |
|---|---|
| `connector_types` table | Over-abstraction — our 8 job types are concrete and well-known |
| `brand_connectors` table | No value — brands already have ad accounts, job configs live in `scheduled_jobs.parameters` |
| `ingestion_jobs` table | Already have `scheduled_jobs` |
| `ingestion_runs` table | Already have `scheduled_job_runs` |
| New worker process | Existing worker handles all job types fine |
| `FOR UPDATE SKIP LOCKED` | PostgREST doesn't support it natively; single-worker model doesn't need it |
| `POST /internal/ingestion/tick` | Worker self-polls; an HTTP trigger adds a failure mode with no benefit |
| Celery (Phase 2) | Adds Redis/RabbitMQ ops complexity not justified by current scale |

## Key Design Decisions

1. **Separate `last_success_at` from `last_attempt_at`** — freshness always uses last_success_at; a failed run never makes data look "fresh"
2. **Step-level freshness in meta_sync** — if thumbnails fail but performance data succeeds, performance is still marked fresh
3. **Non-fatal steps** — steps 3-5 of meta_sync record their own dataset_status independently; overall job still "completed" if step 1-2 succeed
4. **Archive, don't delete** — completed one-time manual jobs get `status='archived'` for audit trail
5. **Retry with exponential backoff** — 5m, 10m, 20m (capped 60m), then fall back to regular cron schedule
6. **Recovery sweep first** — stuck run detection runs at the start of every poll cycle

## Remaining Work

### Completed (Checkpoint 003)
- ~~Wire freshness into remaining 7 job handlers~~ — 6 of 7 done (template_approval skipped: cross-brand, no brand_id)
- ~~Add freshness banners to more pages~~ — hook_analysis + congruence_insights done; template_queue + template_evaluation deferred (no brand selector)

### Completed (Checkpoint 004)
- ~~Template Queue manual scrape → `queue_one_time_job('template_scrape')`~~ — brand selector added to Ingest New tab, legacy toggle included

### Deferred
- **template_approval freshness** — cross-brand job, needs admin-level tracking or per-item brand derivation
- **template_queue / template_evaluation banners** — Ingest New tab now has brand selector; freshness banner can be added in future

### Future Page Migrations
| Priority | Page | What Changes |
|---|---|---|
| ~~1~~ | ~~Template Queue~~ | ~~Manual scrape → `queue_one_time_job('template_scrape')`~~ **DONE (Checkpoint 004)** |
| 2 | Brand Research | Asset downloads → `queue_one_time_job('asset_download')` |
| 3 | Competitor Research | Competitor scrape → queued job (new job type needed) |
| 4 | Reddit Research | Reddit pipeline → queued job (new job type needed) |
| 5 | Amazon Reviews | Review ingestion → queued job (new `amazon_review_scrape` job type needed) |

## Files

See CHECKPOINT_001.md for complete file listing and change details.
