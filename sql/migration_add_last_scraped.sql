-- Add last_scraped_at column to accounts table
-- Run this migration if you have an existing database

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_scraped_at timestamptz;
