-- Migration: Activity Feed Phase 2
-- Date: 2026-03-31
-- Purpose: Add acknowledgment column for event triage + retention automation

-- 1. Add acknowledged_at column for event acknowledgment/dismissal
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;

COMMENT ON COLUMN activity_events.acknowledged_at IS 'When event was acknowledged/dismissed by a user. NULL = unacknowledged.';

-- 2. Index for efficient attention strip query (unacknowledged errors)
CREATE INDEX IF NOT EXISTS idx_activity_events_unacknowledged
    ON activity_events (severity, created_at DESC)
    WHERE acknowledged_at IS NULL;

-- 3. Event retention: delete events older than 90 days
-- Run this manually or via pg_cron: SELECT cron.schedule('activity-event-retention', '0 3 * * *', $$DELETE FROM activity_events WHERE created_at < now() - interval '90 days'$$);
-- For now, a one-time cleanup of anything older than 90 days:
DELETE FROM activity_events WHERE created_at < now() - interval '90 days';
