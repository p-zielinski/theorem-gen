-- A Lean-accepted check (definition or expression) is stored with accepted=0.
-- accepted=1 stays a proof or a counterexample certificate only.
-- A certificate cannot be inserted against another candidate's validation.

DROP TRIGGER IF EXISTS validations_consistent;

CREATE TRIGGER validations_consistent
BEFORE INSERT ON validations
FOR EACH ROW
WHEN (NEW.accepted = 1 AND (
        NEW.result != 'accepted'
        OR NEW.validation_type NOT IN ('proof', 'counterexample')
      ))
  OR (
    NEW.result = 'accepted'
    AND NEW.accepted != 1
    AND NEW.validation_type != 'check'
  )
  OR (NEW.validation_type = 'check' AND NEW.accepted != 0)
  OR (
    NEW.attempt_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM attempts
      WHERE id = NEW.attempt_id AND candidate_id = NEW.candidate_id
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'validation contradicts its accepted flag or attempt');
END;

CREATE TRIGGER IF NOT EXISTS counterexamples_insert_certificate
BEFORE INSERT ON counterexamples
FOR EACH ROW
WHEN NEW.lean_certificate_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM validations
    WHERE id = NEW.lean_certificate_id
      AND candidate_id = NEW.candidate_id
      AND validation_type = 'counterexample'
      AND accepted = 1
      AND result = 'accepted'
  )
BEGIN
  SELECT RAISE(ABORT, 'certificate must be an accepted counterexample of the same candidate');
END;
