-- The statement under a proof is part of the result. Status may change.
-- The identity of the candidate may not.

CREATE TRIGGER IF NOT EXISTS candidates_identity_immutable
BEFORE UPDATE ON candidates
FOR EACH ROW
WHEN NEW.stable_id != OLD.stable_id
  OR NEW.run_id != OLD.run_id
  OR NEW.canonical_ast_json != OLD.canonical_ast_json
  OR NEW.structural_hash != OLD.structural_hash
  OR NEW.kind != OLD.kind
  OR NEW.provenance != OLD.provenance
  OR NEW.curriculum_level != OLD.curriculum_level
  OR NEW.ancestor_stable_id IS NOT OLD.ancestor_stable_id
  OR NEW.family != OLD.family
  OR NEW.ast_size != OLD.ast_size
  OR NEW.depth != OLD.depth
  OR NEW.proof_method != OLD.proof_method
  OR NEW.dependency_depth != OLD.dependency_depth
  OR NEW.held_out != OLD.held_out
  OR NEW.created_at != OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'candidate identity is immutable');
END;
