-- A repair run still draws formulas from <|propose|>. error_at is how many
-- characters of that formula Lean read before the first error. repair_ply 0
-- is an opening draw. 1 and 2 are endings continued from a kept prefix.

ALTER TABLE lm_state ADD COLUMN probe_task TEXT NOT NULL DEFAULT '';
ALTER TABLE lm_state ADD COLUMN repair_ply INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_prefix TEXT NOT NULL DEFAULT '';

ALTER TABLE model_attempts ADD COLUMN repair_ply INTEGER NOT NULL DEFAULT 0;
ALTER TABLE model_attempts ADD COLUMN error_at INTEGER;
