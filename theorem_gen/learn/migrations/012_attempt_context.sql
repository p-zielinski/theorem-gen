-- The training step and loss at the moment the model wrote the equation.
-- Older rows stay empty. Disposition is updated later, these two are not.

ALTER TABLE model_attempts ADD COLUMN lm_step INTEGER;
ALTER TABLE model_attempts ADD COLUMN loss REAL;
