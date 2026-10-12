-- How many of the current 10 model equations are still owed, how many
-- training steps remain before another batch, and the last 10 losses.

ALTER TABLE lm_state ADD COLUMN burst_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN study_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN recent_losses TEXT NOT NULL DEFAULT '[]';
