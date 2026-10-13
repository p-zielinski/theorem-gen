-- A probe run draws a fixed hundred, then one argmax line, and records which
-- decoder wrote the row. NULL decoder is an older greedy row.
-- taught marks an accepted equation that has already had its extra step.

ALTER TABLE lm_state ADD COLUMN probe INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN probe_phase TEXT NOT NULL DEFAULT 'train';
ALTER TABLE lm_state ADD COLUMN probe_cycle INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN probe_cycles INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN probe_draw_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN probe_greedy_left INTEGER NOT NULL DEFAULT 0;

ALTER TABLE model_attempts ADD COLUMN decoder TEXT;
ALTER TABLE model_attempts ADD COLUMN cycle INTEGER;
ALTER TABLE model_attempts ADD COLUMN taught INTEGER NOT NULL DEFAULT 0;
