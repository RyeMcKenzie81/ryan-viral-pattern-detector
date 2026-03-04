-- Migration: Ad Creator V2 Phase 4 — apply_ad_override RPC function
-- Date: 2026-02-14
-- Purpose: Atomic 3-step override: insert override, update generated_ads, supersede previous

CREATE OR REPLACE FUNCTION apply_ad_override(
    p_generated_ad_id UUID,
    p_org_id UUID,
    p_user_id UUID,
    p_action TEXT,
    p_reason TEXT DEFAULT NULL,
    p_check_overrides JSONB DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_previous_status TEXT;
    v_new_final_status TEXT;
    v_new_override_status TEXT;
    v_override_id UUID;
BEGIN
    -- Validate action
    IF p_action NOT IN ('override_approve', 'override_reject', 'confirm') THEN
        RAISE EXCEPTION 'Invalid override action: %', p_action;
    END IF;

    -- Map action to statuses
    CASE p_action
        WHEN 'override_approve' THEN
            v_new_final_status := 'approved';
            v_new_override_status := 'override_approved';
        WHEN 'override_reject' THEN
            v_new_final_status := 'rejected';
            v_new_override_status := 'override_rejected';
        WHEN 'confirm' THEN
            v_new_override_status := 'confirmed';
            -- For confirm, keep current final_status
            SELECT final_status INTO v_new_final_status
            FROM generated_ads WHERE id = p_generated_ad_id;
    END CASE;

    -- Get previous status
    SELECT final_status INTO v_previous_status
    FROM generated_ads WHERE id = p_generated_ad_id;

    IF v_previous_status IS NULL THEN
        RAISE EXCEPTION 'Generated ad not found: %', p_generated_ad_id;
    END IF;

    -- Step 1: Insert override record
    INSERT INTO ad_review_overrides (
        generated_ad_id, organization_id, user_id,
        override_action, previous_status, check_overrides, reason
    )
    VALUES (
        p_generated_ad_id, p_org_id, p_user_id,
        p_action, v_previous_status, p_check_overrides, p_reason
    )
    RETURNING id INTO v_override_id;

    -- Step 2: Update generated_ads
    UPDATE generated_ads
    SET final_status = v_new_final_status,
        override_status = v_new_override_status
    WHERE id = p_generated_ad_id;

    -- Step 3: Supersede previous overrides for this ad
    UPDATE ad_review_overrides
    SET superseded_by = v_override_id
    WHERE generated_ad_id = p_generated_ad_id
      AND id != v_override_id
      AND superseded_by IS NULL;

    -- Return the new override record
    RETURN jsonb_build_object(
        'id', v_override_id,
        'generated_ad_id', p_generated_ad_id,
        'override_action', p_action,
        'previous_status', v_previous_status,
        'new_final_status', v_new_final_status,
        'new_override_status', v_new_override_status
    );
END;
$$;
