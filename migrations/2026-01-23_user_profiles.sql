-- Migration: User Profiles with Superuser Flag
-- Date: 2026-01-23
-- Purpose: Add user_profiles table for superuser support and future user settings
-- Phase: 5 of Multi-Tenant Auth Plan

-- ============================================================================
-- 1. Create user_profiles table
-- ============================================================================

CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    is_superuser BOOLEAN DEFAULT false,
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE user_profiles IS 'Extended user profile data including superuser flag';
COMMENT ON COLUMN user_profiles.is_superuser IS 'If true, user can see all organizations data';
COMMENT ON COLUMN user_profiles.display_name IS 'Optional display name for the user';

-- Index for quick superuser lookups
CREATE INDEX idx_user_profiles_superuser ON user_profiles(is_superuser) WHERE is_superuser = true;

-- ============================================================================
-- 2. Make existing admin user a superuser
-- ============================================================================

INSERT INTO user_profiles (user_id, is_superuser)
VALUES ('54093883-c9de-40a3-b940-86cc52825365', true);
