-- Where the repeat pass stopped. A resume continues after this candidate id.
-- 0 means the next pass starts at the beginning.

ALTER TABLE lm_state ADD COLUMN replay_id INTEGER NOT NULL DEFAULT 0;
