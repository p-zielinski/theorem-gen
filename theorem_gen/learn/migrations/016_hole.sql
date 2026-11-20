-- A hole run still trains on generator sentences. Each cycle breaks one character
-- of a sentence proved with rfl. hole_from is the character that was there.
-- hole_char is the one character the model wrote back.

ALTER TABLE lm_state ADD COLUMN hole_from TEXT NOT NULL DEFAULT '';

ALTER TABLE model_attempts ADD COLUMN hole_index INTEGER;
ALTER TABLE model_attempts ADD COLUMN hole_char TEXT NOT NULL DEFAULT '';
ALTER TABLE model_attempts ADD COLUMN hole_from TEXT NOT NULL DEFAULT '';
ALTER TABLE model_attempts ADD COLUMN hole_broken TEXT NOT NULL DEFAULT '';
