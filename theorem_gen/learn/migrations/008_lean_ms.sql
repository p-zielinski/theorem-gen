-- Wall time of one Lean check. Older rows stay NULL.
-- Validations remain append-only; this column is set on insert.

ALTER TABLE validations ADD COLUMN lean_ms INTEGER;
