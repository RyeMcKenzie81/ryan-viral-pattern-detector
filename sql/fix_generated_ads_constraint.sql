-- Fix generated_ads_prompt_index_check constraint
-- The existing constraint likely limits prompt_index to a small number (e.g. 20), causing batch failures.

ALTER TABLE generated_ads DROP CONSTRAINT IF EXISTS generated_ads_prompt_index_check;

-- Optional: Re-add with a higher limit if desired, or leave unconstrained.
-- ALTER TABLE generated_ads ADD CONSTRAINT generated_ads_prompt_index_check CHECK (prompt_index > 0 AND prompt_index <= 1000);
