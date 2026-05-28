-- Migration: Scheduler claim + recover RPC functions
-- Date: 2026-05-28
-- Purpose: PR 1 of 2 — scheduler worker upgrade. Atomic claim-and-decide for
--          concurrent workers, plus race-safe stuck-run recovery.
--
-- This migration depends on:
--   2026-05-28_job_concurrency_limits.sql (job_concurrency_limits, job_runtime_limits)
--   2026-05-28_scheduled_job_runs_worker_id.sql (worker_id column)
--
-- Architecture: see design doc
--   ~/.gstack/projects/.../scheduler-worker-upgrade-design-20260528-111848.md
--
-- The smoke test that proved this pattern works against Supabase REST:
--   /tmp/smoke_supabase_rpc_lock.py (run 2026-05-28, PASS)


-- ============================================================================
-- get_cap(scope_type, scope_key)
-- ============================================================================
-- Simple cap lookup. STABLE so the planner can call it multiple times per
-- transaction with the same args without re-evaluating. Python layer also
-- caches results for ~30s to avoid hot-path DB lookups under load.

CREATE OR REPLACE FUNCTION get_cap(p_scope_type TEXT, p_scope_key TEXT)
RETURNS INT
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT max_concurrent
    FROM job_concurrency_limits
    WHERE scope_type = p_scope_type
      AND scope_key = p_scope_key
      AND enabled = true
    LIMIT 1;
$$;

COMMENT ON FUNCTION get_cap(TEXT, TEXT) IS
    'Look up a concurrency cap. Returns NULL if not configured (caller falls back through scope hierarchy).';

GRANT EXECUTE ON FUNCTION get_cap(TEXT, TEXT) TO authenticated, service_role, anon;


-- ============================================================================
-- claim_next_job(worker_id_text)
-- ============================================================================
-- Atomic claim. Within one transaction:
--   1. Hold a coarse global advisory lock to serialize all admission decisions.
--      (Per-(brand, job_type) locks would still allow different pairs to race
--      on the global and job_type counts. The smoke test proved one advisory
--      lock per claim is fast enough: ~200 claims/sec ceiling at millisecond
--      claims, way above need.)
--   2. SELECT a candidate scheduled_jobs row that is active, due, and not
--      already running. SKIP LOCKED keeps workers from fighting over the row.
--   3. Count currently-running runs under each cap scope.
--   4. Look up caps with hierarchical fallback (brand_job_type → brand →
--      job_type → global). Reject if any cap is hit.
--   5. INSERT a new scheduled_job_runs row with status='running' AND clear
--      scheduled_jobs.next_run_at on the parent. Both happen atomically in
--      this transaction.
--   6. Return the new run row joined with parent job fields the worker needs.
--
-- Returns: zero or one row. Empty result means EITHER no work available OR a
-- cap was hit. The caller (Python) treats both as "wait and retry" — they
-- distinguish via timing/logs, not via the SQL result shape.

CREATE OR REPLACE FUNCTION claim_next_job(worker_id_text TEXT DEFAULT NULL)
RETURNS TABLE(
    run_id UUID,
    job_id UUID,
    job_name TEXT,
    job_type TEXT,
    brand_id UUID,
    product_id UUID,
    parameters JSONB,
    started_at TIMESTAMPTZ,
    attempt_number INT,
    -- Cap-decision tracing fields, useful for "why didn't my job run" debugging.
    -- Only populated on successful claim.
    counts_global INT,
    counts_job_type INT,
    counts_brand INT,
    counts_brand_jt INT,
    cap_global INT,
    cap_job_type INT,
    cap_brand INT,
    cap_brand_jt INT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_job_id UUID;
    v_brand_id UUID;
    v_product_id UUID;
    v_job_type TEXT;
    v_job_name TEXT;
    v_parameters JSONB;
    v_new_run_id UUID;
    v_started_at TIMESTAMPTZ;
    v_attempt_number INT;
    v_cnt_global INT;
    v_cnt_job_type INT;
    v_cnt_brand INT;
    v_cnt_brand_jt INT;
    v_cap_global INT;
    v_cap_job_type INT;
    v_cap_brand INT;
    v_cap_brand_jt INT;
BEGIN
    -- Step 1: coarse global advisory lock. Released at COMMIT/ROLLBACK.
    -- Convention: namespace prefix 'job-claim-global' to avoid collisions
    -- with any other code that uses pg_advisory_* locks in this DB.
    PERFORM pg_advisory_xact_lock(hashtextextended('job-claim-global', 0));

    -- Step 2: pick a candidate. Active lifecycle, due, no in-flight run.
    SELECT j.id, j.brand_id, j.product_id, j.job_type, j.name, j.parameters
      INTO v_job_id, v_brand_id, v_product_id, v_job_type, v_job_name, v_parameters
    FROM scheduled_jobs j
    WHERE j.status = 'active'
      AND j.next_run_at IS NOT NULL
      AND j.next_run_at <= now()
      AND NOT EXISTS (
          SELECT 1 FROM scheduled_job_runs r
          WHERE r.scheduled_job_id = j.id AND r.status = 'running'
      )
    ORDER BY j.next_run_at ASC
    LIMIT 1
    FOR UPDATE OF j SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Step 3: count current running runs, joined to scheduled_jobs for
    -- brand_id/job_type filters.
    SELECT COUNT(*)::INT INTO v_cnt_global
      FROM scheduled_job_runs WHERE status = 'running';

    SELECT COUNT(*)::INT INTO v_cnt_job_type
      FROM scheduled_job_runs r
      JOIN scheduled_jobs sj ON sj.id = r.scheduled_job_id
      WHERE r.status = 'running' AND sj.job_type = v_job_type;

    SELECT COUNT(*)::INT INTO v_cnt_brand
      FROM scheduled_job_runs r
      JOIN scheduled_jobs sj ON sj.id = r.scheduled_job_id
      WHERE r.status = 'running' AND sj.brand_id = v_brand_id;

    SELECT COUNT(*)::INT INTO v_cnt_brand_jt
      FROM scheduled_job_runs r
      JOIN scheduled_jobs sj ON sj.id = r.scheduled_job_id
      WHERE r.status = 'running'
        AND sj.brand_id = v_brand_id
        AND sj.job_type = v_job_type;

    -- Step 4: look up caps with hierarchical fallback. Anything unset
    -- defaults to a high ceiling (1000) so missing config doesn't block work.
    v_cap_global   := COALESCE(get_cap('global', '__default__'), 1000);
    v_cap_job_type := COALESCE(get_cap('job_type', v_job_type),
                               get_cap('job_type', '__default__'),
                               v_cap_global);
    v_cap_brand    := COALESCE(get_cap('brand', v_brand_id::text),
                               get_cap('brand', '__default__'),
                               v_cap_global);
    v_cap_brand_jt := COALESCE(get_cap('brand_job_type',
                                       v_brand_id::text || ':' || v_job_type),
                               v_cap_brand);

    IF    v_cnt_global   >= v_cap_global
       OR v_cnt_job_type >= v_cap_job_type
       OR v_cnt_brand    >= v_cap_brand
       OR v_cnt_brand_jt >= v_cap_brand_jt THEN
        -- Cap hit. Return empty; lock releases at function return / commit.
        RETURN;
    END IF;

    -- Step 5: determine attempt_number (mirrors the existing create_job_run
    -- helper at scheduler_worker.py:300 — increment on consecutive failures).
    SELECT COALESCE(
        (SELECT CASE WHEN r.status = 'failed'
                     THEN COALESCE(r.attempt_number, 1) + 1
                     ELSE 1 END
         FROM scheduled_job_runs r
         WHERE r.scheduled_job_id = v_job_id
         ORDER BY r.started_at DESC NULLS LAST
         LIMIT 1),
        1
    ) INTO v_attempt_number;

    v_started_at := now();

    -- Step 6: create the run row AND clear the parent's next_run_at. Atomic
    -- because we're inside the same transaction.
    INSERT INTO scheduled_job_runs (
        scheduled_job_id, status, started_at, attempt_number, worker_id
    ) VALUES (
        v_job_id, 'running', v_started_at, v_attempt_number, worker_id_text
    )
    RETURNING id INTO v_new_run_id;

    UPDATE scheduled_jobs
    SET next_run_at = NULL
    WHERE id = v_job_id;

    -- Step 7: return the claim payload.
    RETURN QUERY SELECT
        v_new_run_id,
        v_job_id,
        v_job_name,
        v_job_type,
        v_brand_id,
        v_product_id,
        v_parameters,
        v_started_at,
        v_attempt_number,
        v_cnt_global, v_cnt_job_type, v_cnt_brand, v_cnt_brand_jt,
        v_cap_global, v_cap_job_type, v_cap_brand, v_cap_brand_jt;
END;
$$;

COMMENT ON FUNCTION claim_next_job(TEXT) IS
    'Atomic claim with concurrency caps. Returns 0 or 1 row. Empty = no work OR cap hit. See scheduler-worker-upgrade design doc.';

GRANT EXECUTE ON FUNCTION claim_next_job(TEXT) TO authenticated, service_role;


-- ============================================================================
-- recover_stuck_runs_v2()
-- ============================================================================
-- Reset runs whose started_at is older than the per-job-type cutoff. Replaces
-- the hardcoded 30-minute threshold in the existing Python recover_stuck_runs
-- function, which has been silently killing legitimately-long template_scrape
-- runs. Uses SKIP LOCKED so multiple recovery callers don't race.
--
-- Note: named _v2 to avoid name conflict with any existing helper. The Python
-- recovery_loop calls THIS function; the legacy Python recover_stuck_runs at
-- scheduler_worker.py:485 stays in place for PR 1 (PR 2 retires it).

CREATE OR REPLACE FUNCTION recover_stuck_runs_v2(fallback_seconds INT DEFAULT 3600)
RETURNS TABLE(recovered_run_id UUID, recovered_job_id UUID, job_type TEXT, runtime_seconds NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    WITH stuck AS (
        SELECT
            r.id AS run_id,
            r.scheduled_job_id,
            sj.job_type AS jt,
            EXTRACT(EPOCH FROM (now() - r.started_at))::NUMERIC AS runtime_s,
            COALESCE(jrl.max_runtime_seconds, fallback_seconds) AS cutoff
        FROM scheduled_job_runs r
        JOIN scheduled_jobs sj ON sj.id = r.scheduled_job_id
        LEFT JOIN job_runtime_limits jrl ON jrl.job_type = sj.job_type
        WHERE r.status = 'running'
          AND r.started_at IS NOT NULL
          AND r.started_at < now() - (COALESCE(jrl.max_runtime_seconds, fallback_seconds) * INTERVAL '1 second')
        FOR UPDATE OF r SKIP LOCKED
    ),
    updated_runs AS (
        UPDATE scheduled_job_runs r
        SET status = 'failed',
            completed_at = now(),
            error_message = format(
                'recovered: started_at exceeded max_runtime_seconds (ran %s seconds, cutoff %s)',
                ROUND(stuck.runtime_s, 1), stuck.cutoff
            )
        FROM stuck
        WHERE r.id = stuck.run_id
        RETURNING stuck.run_id, stuck.scheduled_job_id, stuck.jt, stuck.runtime_s
    ),
    rearmed AS (
        -- Re-arm the parent jobs so they get picked up again next cycle.
        -- (The legacy _reschedule_after_failure path handles backoff/retries
        -- for failures; here we just re-queue immediately so the next claim
        -- can re-attempt.)
        UPDATE scheduled_jobs j
        SET next_run_at = now()
        FROM updated_runs ur
        WHERE j.id = ur.scheduled_job_id
        RETURNING j.id
    )
    SELECT ur.run_id, ur.scheduled_job_id, ur.jt, ur.runtime_s FROM updated_runs ur;
END;
$$;

COMMENT ON FUNCTION recover_stuck_runs_v2(INT) IS
    'Per-job-type stuck-run recovery. Returns one row per recovered run for logging. Race-safe via SKIP LOCKED.';

GRANT EXECUTE ON FUNCTION recover_stuck_runs_v2(INT) TO authenticated, service_role;
