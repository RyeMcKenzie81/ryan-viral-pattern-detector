-- ============================================
-- Seed: Copy Scaffolds for Phase 1-2 Belief Testing
-- Date: 2025-12-16
-- Purpose: Load default headline and primary text scaffolds
-- ============================================

-- Clear existing scaffolds (for re-seeding)
-- DELETE FROM copy_scaffolds;

-- ============================================
-- HEADLINE SCAFFOLDS (max 40 chars each)
-- ============================================

-- H1 - Observation-Led (Problem-Aware Entry)
INSERT INTO copy_scaffolds (scope, name, template_text, max_chars, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('headline', 'H1-Observation-1', 'Noticing {SYMPTOM_1}? It''s not just age.', 40, 1, 2,
 ARRAY['problem-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["SYMPTOM_1"]}'),

('headline', 'H1-Observation-2', '{SYMPTOM_1} is often the first sign.', 40, 1, 2,
 ARRAY['problem-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["SYMPTOM_1"]}'),

('headline', 'H1-Observation-3', 'Most people miss {SYMPTOM_1} early.', 40, 1, 2,
 ARRAY['problem-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["SYMPTOM_1"]}');

-- H2 - Reframe-Led (Angle, Compressed)
INSERT INTO copy_scaffolds (scope, name, template_text, max_chars, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('headline', 'H2-Reframe-1', 'It''s not {COMMON_BELIEF}. It''s {ANGLE_CLAIM}.', 40, 1, 2,
 ARRAY['problem-aware', 'early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["COMMON_BELIEF", "ANGLE_CLAIM"]}'),

('headline', 'H2-Reframe-2', 'Why {SYMPTOM_1} happens: {ANGLE_CLAIM}', 40, 1, 2,
 ARRAY['problem-aware', 'early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["SYMPTOM_1", "ANGLE_CLAIM"]}'),

('headline', 'H2-Reframe-3', 'The real reason behind {SYMPTOM_1}', 40, 1, 2,
 ARRAY['problem-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["SYMPTOM_1"]}');

-- H3 - Outcome-Led (Soft, Non-Offer)
INSERT INTO copy_scaffolds (scope, name, template_text, max_chars, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('headline', 'H3-Outcome-1', 'Help them move comfortably again.', 40, 1, 2,
 ARRAY['early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{}'),

('headline', 'H3-Outcome-2', 'Support mobility without complexity.', 40, 1, 2,
 ARRAY['early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{}'),

('headline', 'H3-Outcome-3', 'Keep the good days going longer.', 40, 1, 2,
 ARRAY['early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{}');

-- H4 - Persona Callout (Generic Only for Phase 1-2)
INSERT INTO copy_scaffolds (scope, name, template_text, max_chars, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('headline', 'H4-Persona-1', 'For {PERSONA_LABEL}s who act early.', 40, 1, 2,
 ARRAY['problem-aware', 'early-solution-aware'], '{"no_discount": true, "no_medical_claims": true, "no_hyper_specific_callout": true}', '{"required_tokens": ["PERSONA_LABEL"]}'),

('headline', 'H4-Persona-2', 'If you''re trying to {JTBD}...', 40, 1, 2,
 ARRAY['problem-aware', 'early-solution-aware'], '{"no_discount": true, "no_medical_claims": true}', '{"required_tokens": ["JTBD"]}');

-- ============================================
-- PRIMARY TEXT SCAFFOLDS
-- ============================================

-- P1 - Observation -> Reframe -> Soft Outcome
INSERT INTO copy_scaffolds (scope, name, template_text, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('primary_text', 'P1-Observation-Reframe-Outcome',
'If you''ve noticed {SYMPTOM_1} (or {SYMPTOM_2})...

Many people think it''s {COMMON_BELIEF}. Often it''s {ANGLE_CLAIM}.

That''s why we built {PRODUCT_NAME} to support {BENEFIT_1}—without turning life into a treatment plan.',
1, 2, ARRAY['problem-aware', 'early-solution-aware'],
'{"no_discount": true, "no_medical_claims": true, "no_guarantees": true}',
'{"required_tokens": ["SYMPTOM_1", "SYMPTOM_2", "COMMON_BELIEF", "ANGLE_CLAIM", "PRODUCT_NAME", "BENEFIT_1"]}');

-- P2 - Diagnosis-Lite -> Mechanism-Lite -> Outcome
INSERT INTO copy_scaffolds (scope, name, template_text, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('primary_text', 'P2-Diagnosis-Mechanism-Outcome',
'{SYMPTOM_1} often shows up before people take it seriously.

{MECHANISM_PHRASE} supports the body where mobility starts.

The goal isn''t miracles—just {BENEFIT_1} and more comfortable movement.',
1, 2, ARRAY['problem-aware', 'early-solution-aware'],
'{"no_discount": true, "no_medical_claims": true, "no_guarantees": true}',
'{"required_tokens": ["SYMPTOM_1", "MECHANISM_PHRASE", "BENEFIT_1"]}');

-- P3 - Myth -> Truth -> Next Step
INSERT INTO copy_scaffolds (scope, name, template_text, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('primary_text', 'P3-Myth-Truth-NextStep',
'Myth: {COMMON_BELIEF}.

Truth: {ANGLE_CLAIM}.

If you''re trying to {JTBD}, {PRODUCT_NAME} is a simple daily step toward {BENEFIT_1}.',
1, 2, ARRAY['problem-aware', 'early-solution-aware'],
'{"no_discount": true, "no_medical_claims": true, "no_guarantees": true}',
'{"required_tokens": ["COMMON_BELIEF", "ANGLE_CLAIM", "JTBD", "PRODUCT_NAME", "BENEFIT_1"]}');

-- P4 - Tight Version (Image-Heavy Templates)
INSERT INTO copy_scaffolds (scope, name, template_text, phase_min, phase_max, awareness_targets, guardrails, template_requirements) VALUES
('primary_text', 'P4-Tight-ImageHeavy',
'Noticing {SYMPTOM_1}? Often it''s {ANGLE_CLAIM}. {PRODUCT_NAME} supports {BENEFIT_1} with {MECHANISM_PHRASE}.',
1, 2, ARRAY['problem-aware', 'early-solution-aware'],
'{"no_discount": true, "no_medical_claims": true, "no_guarantees": true}',
'{"required_tokens": ["SYMPTOM_1", "ANGLE_CLAIM", "PRODUCT_NAME", "BENEFIT_1", "MECHANISM_PHRASE"]}');

-- ============================================
-- DONE - 12 headline scaffolds + 4 primary text scaffolds
-- ============================================
