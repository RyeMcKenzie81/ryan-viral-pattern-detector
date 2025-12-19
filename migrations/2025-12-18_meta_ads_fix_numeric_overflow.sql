-- Migration: Fix numeric field overflow for Meta Ads Performance
-- Date: 2025-12-18
-- Purpose: Increase precision for CTR and percentage fields that can exceed 99.9999
--
-- Issue: NUMERIC(6, 4) can only store values up to 99.9999
-- Meta can return CTR > 100% for high-performing ads

ALTER TABLE meta_ads_performance
    ALTER COLUMN link_ctr TYPE NUMERIC(10, 4),
    ALTER COLUMN conversion_rate TYPE NUMERIC(10, 4),
    ALTER COLUMN frequency TYPE NUMERIC(10, 3);

COMMENT ON COLUMN meta_ads_performance.link_ctr IS 'Outbound clicks CTR - increased precision to handle values > 100%';
