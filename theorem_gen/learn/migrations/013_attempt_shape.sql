-- Shape of the equation text at the moment of writing.
-- NULL means the text is not a statement of this fragment, not a depth of zero.
-- Disposition may change later. These three do not.

ALTER TABLE model_attempts ADD COLUMN expr_depth INTEGER;
ALTER TABLE model_attempts ADD COLUMN expr_operators INTEGER;
ALTER TABLE model_attempts ADD COLUMN expr_size INTEGER;
