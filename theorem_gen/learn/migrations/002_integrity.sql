-- Integrity rules that keep proved/refuted tied to a consistent validation row.
-- candidates.start unresolved. current_status may change only to the value
-- derived from validations. accepted=1 is only an accepted proof or counterexample.

CREATE TRIGGER IF NOT EXISTS candidates_start_unresolved
BEFORE INSERT ON candidates
FOR EACH ROW
WHEN NEW.current_status != 'unresolved'
BEGIN
  SELECT RAISE(ABORT, 'candidates start unresolved');
END;

CREATE TRIGGER IF NOT EXISTS candidates_status_matches_validations
BEFORE UPDATE OF current_status ON candidates
FOR EACH ROW
WHEN NEW.current_status != (
  CASE
    WHEN EXISTS (
      SELECT 1 FROM validations
      WHERE candidate_id = NEW.id
        AND accepted = 1
        AND result = 'accepted'
        AND validation_type = 'proof'
    ) AND EXISTS (
      SELECT 1 FROM validations
      WHERE candidate_id = NEW.id
        AND accepted = 1
        AND result = 'accepted'
        AND validation_type = 'counterexample'
    ) THEN 'quarantined'
    WHEN EXISTS (
      SELECT 1 FROM validations
      WHERE candidate_id = NEW.id
        AND accepted = 1
        AND result = 'accepted'
        AND validation_type = 'proof'
    ) THEN 'proved'
    WHEN EXISTS (
      SELECT 1 FROM validations
      WHERE candidate_id = NEW.id
        AND accepted = 1
        AND result = 'accepted'
        AND validation_type = 'counterexample'
    ) THEN 'refuted'
    WHEN EXISTS (
      SELECT 1 FROM validations
      WHERE candidate_id = NEW.id
        AND (
          result = 'ill_formed'
          OR failure_class = 'syntax'
          OR failure_class = 'typing'
          OR failure_class = 'rejected'
        )
    ) THEN 'ill_formed'
    ELSE 'unresolved'
  END
)
BEGIN
  SELECT RAISE(ABORT, 'current_status must be derived from validations');
END;

CREATE TRIGGER IF NOT EXISTS validations_consistent
BEFORE INSERT ON validations
FOR EACH ROW
WHEN (NEW.accepted = 1 AND (
        NEW.result != 'accepted'
        OR NEW.validation_type NOT IN ('proof', 'counterexample')
      ))
  OR (NEW.result = 'accepted' AND NEW.accepted != 1)
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

CREATE TRIGGER IF NOT EXISTS counterexamples_certificate_same_candidate
BEFORE UPDATE OF lean_certificate_id ON counterexamples
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
