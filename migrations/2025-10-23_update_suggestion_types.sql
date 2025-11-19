-- Update suggestion_type constraint to support 5 comment types
-- V1.3: Added funny, debate, relate types

-- Drop the old constraint
ALTER TABLE generated_comments
DROP CONSTRAINT IF EXISTS generated_comments_suggestion_type_check;

-- Add new constraint with 5 types
ALTER TABLE generated_comments
ADD CONSTRAINT generated_comments_suggestion_type_check
CHECK (suggestion_type IN ('add_value', 'ask_question', 'funny', 'debate', 'relate'));

-- Update comment
COMMENT ON COLUMN generated_comments.suggestion_type IS 'Type of comment suggestion: add_value (insights), ask_question (follow-ups), funny (jokes/wit), debate (contrarian views), relate (personal stories)';
