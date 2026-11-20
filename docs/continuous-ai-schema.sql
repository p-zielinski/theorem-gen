-- Continuous-learning store, schema version 1.
-- Mathematical outcomes are proved, refuted, unresolved, ill_formed.
-- quarantined is a system-defect hold: both a proof and a counterexample
-- certificate were accepted, so neither outcome is adopted. It is not a synonym
-- of the four outcomes.
-- attempts, validations, and events are append-only.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('created', 'running', 'paused', 'completed')),
  seed INTEGER NOT NULL,
  config_json TEXT NOT NULL,
  curriculum_level INTEGER NOT NULL CHECK (curriculum_level BETWEEN 1 AND 7),
  model_version TEXT,
  checkpoint_window INTEGER NOT NULL DEFAULT 0,
  promoted_in_window INTEGER NOT NULL DEFAULT 0 CHECK (promoted_in_window IN (0, 1)),
  advancement_frozen INTEGER NOT NULL DEFAULT 0 CHECK (advancement_frozen IN (0, 1)),
  held_out_baseline REAL,
  held_out_latest REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY,
  stable_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  canonical_ast_json TEXT NOT NULL,
  structural_hash TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('hypothesis', 'theorem', 'definition', 'expression')),
  provenance TEXT NOT NULL,
  current_status TEXT NOT NULL CHECK (
    current_status IN ('proved', 'refuted', 'unresolved', 'ill_formed', 'quarantined')
  ),
  curriculum_level INTEGER NOT NULL,
  ancestor_stable_id TEXT,
  family TEXT NOT NULL DEFAULT '',
  ast_size INTEGER NOT NULL DEFAULT 0,
  depth INTEGER NOT NULL DEFAULT 0,
  proof_method TEXT NOT NULL DEFAULT '',
  dependency_depth INTEGER NOT NULL DEFAULT 0,
  held_out INTEGER NOT NULL DEFAULT 0 CHECK (held_out IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_run_level ON candidates(run_id, curriculum_level, id);
CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(structural_hash);
CREATE INDEX IF NOT EXISTS idx_candidates_ancestor ON candidates(ancestor_stable_id);

CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  role TEXT NOT NULL,
  model_version TEXT,
  prompt_hash TEXT NOT NULL,
  raw_response TEXT NOT NULL,
  proof_artifact TEXT,
  critique_artifact TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  duration_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validations (
  id INTEGER PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  attempt_id INTEGER REFERENCES attempts(id),
  lean_version TEXT NOT NULL,
  toolchain_hash TEXT NOT NULL,
  validation_type TEXT NOT NULL CHECK (validation_type IN ('proof', 'counterexample', 'check')),
  result TEXT NOT NULL CHECK (result IN ('accepted', 'rejected', 'timeout', 'unavailable', 'ill_formed')),
  accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
  stdout TEXT NOT NULL,
  stderr TEXT NOT NULL,
  message TEXT NOT NULL,
  failure_class TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_validations_candidate ON validations(candidate_id);

CREATE TABLE IF NOT EXISTS counterexamples (
  id INTEGER PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  assignment_json TEXT NOT NULL,
  instantiated_prop TEXT NOT NULL,
  lean_certificate_id INTEGER REFERENCES validations(id),
  proposed_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dependencies (
  id INTEGER PRIMARY KEY,
  from_id INTEGER NOT NULL REFERENCES candidates(id),
  to_id INTEGER NOT NULL REFERENCES candidates(id),
  relation TEXT NOT NULL,
  UNIQUE (from_id, to_id, relation)
);

CREATE TABLE IF NOT EXISTS queue_jobs (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  job_type TEXT NOT NULL CHECK (job_type IN (
    'propose',
    'prove_primary',
    'prove_alternate_or_critique',
    'counterexample_search',
    'lean_validate'
  )),
  priority INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'done', 'failed')),
  payload_json TEXT NOT NULL,
  lease_owner TEXT,
  lease_expiry TEXT,
  heartbeat_at TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_ready ON queue_jobs(run_id, state, priority DESC, id);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (run_id, seq)
);

CREATE TABLE IF NOT EXISTS curriculum_progress (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  level INTEGER NOT NULL,
  window_index INTEGER NOT NULL,
  metrics_json TEXT NOT NULL,
  gate_status TEXT NOT NULL CHECK (gate_status IN ('open', 'passed', 'failed', 'frozen')),
  evaluated_count INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (run_id, level, window_index)
);

CREATE TABLE IF NOT EXISTS model_versions (
  version_id TEXT PRIMARY KEY,
  path TEXT,
  weight_hash TEXT,
  adapter_hash TEXT,
  eval_scores_json TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('champion', 'challenger', 'retired', 'baseline')),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL,
  event_cursor INTEGER NOT NULL,
  scheduler_state_json TEXT NOT NULL,
  rng_state TEXT NOT NULL,
  curriculum_state_json TEXT NOT NULL,
  artifact_hashes_json TEXT NOT NULL,
  known_good INTEGER NOT NULL CHECK (known_good IN (0, 1)),
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (run_id, seq)
);

CREATE TRIGGER IF NOT EXISTS attempts_no_update
BEFORE UPDATE ON attempts
BEGIN
  SELECT RAISE(ABORT, 'attempts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS attempts_no_delete
BEFORE DELETE ON attempts
BEGIN
  SELECT RAISE(ABORT, 'attempts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS validations_no_update
BEFORE UPDATE ON validations
BEGIN
  SELECT RAISE(ABORT, 'validations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS validations_no_delete
BEFORE DELETE ON validations
BEGIN
  SELECT RAISE(ABORT, 'validations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS counterexamples_evidence_immutable
BEFORE UPDATE ON counterexamples
FOR EACH ROW
WHEN OLD.lean_certificate_id IS NOT NULL
  OR NEW.candidate_id != OLD.candidate_id
  OR NEW.assignment_json != OLD.assignment_json
  OR NEW.instantiated_prop != OLD.instantiated_prop
  OR NEW.proposed_by != OLD.proposed_by
BEGIN
  SELECT RAISE(ABORT, 'counterexample evidence is immutable');
END;
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
-- Lean workers read nothing from SQLite. One writer keeps this file.
-- train_items is the stoppable queue of Lean-labeled rows.
-- online_weights is a small linear model, not a neural-net checkpoint.

CREATE TABLE IF NOT EXISTS train_items (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  label TEXT NOT NULL CHECK (label IN ('proved', 'refuted')),
  state TEXT NOT NULL CHECK (state IN ('queued', 'done')),
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_train_ready ON train_items(run_id, state, id);

CREATE TABLE IF NOT EXISTS online_weights (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  step INTEGER NOT NULL,
  vector_json TEXT NOT NULL,
  cursor_id INTEGER NOT NULL DEFAULT 0,
  lean_workers INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_run_id ON candidates(run_id, id);
-- One progress row for 7B QLoRA. The Lean text stays where it already is.
-- step is how many labeled examples have updated the adapter.
-- cursor_id is the last candidate id already considered.
-- Waiting is a count of later proved/refuted rows, not a second copy of them.

CREATE TABLE IF NOT EXISTS qlora_state (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  model_id TEXT NOT NULL,
  step INTEGER NOT NULL,
  cursor_id INTEGER NOT NULL DEFAULT 0,
  last_loss REAL,
  last_error TEXT,
  adapter_path TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
-- Drop the Qwen QLoRA progress row. The 50M transformer keeps one progress
-- row plus the short equations it actually sampled. The corpus stays in
-- candidates and queue_jobs.

DROP TABLE IF EXISTS qlora_state;

CREATE TABLE IF NOT EXISTS lm_state (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  step INTEGER NOT NULL,
  epoch INTEGER NOT NULL,
  cursor_id INTEGER NOT NULL DEFAULT 0,
  pass_cursor INTEGER NOT NULL DEFAULT 0,
  sequences INTEGER NOT NULL DEFAULT 0,
  last_loss REAL,
  hold INTEGER NOT NULL DEFAULT 0 CHECK (hold IN (0, 1)),
  weak_streak INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  weights_path TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_attempts (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  equation TEXT NOT NULL,
  equation_hash TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('model')),
  disposition TEXT NOT NULL CHECK (
    disposition IN ('duplicate', 'queued', 'proved', 'unresolved', 'ill_formed', 'refuted')
  ),
  candidate_id INTEGER REFERENCES candidates(id),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_attempts_run_hash
  ON model_attempts(run_id, equation_hash);
-- Wall time of one Lean check. Older rows stay NULL.
-- Validations remain append-only; this column is set on insert.

ALTER TABLE validations ADD COLUMN lean_ms INTEGER;
-- A proved sentence that does not fit in the model window, including the
-- role mark and the end mark. It stays here until a larger window can hold it.

CREATE TABLE IF NOT EXISTS context_blocks (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  token_length INTEGER NOT NULL,
  context_limit INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status = 'blocked by context limit'),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_context_blocks_ready
  ON context_blocks(run_id, token_length, candidate_id);
-- How many of the current 10 model equations are still owed, how many
-- training steps remain before another batch, and the last 10 losses.

ALTER TABLE lm_state ADD COLUMN burst_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN study_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN recent_losses TEXT NOT NULL DEFAULT '[]';
-- Where the repeat pass stopped. A resume continues after this candidate id.
-- 0 means the next pass starts at the beginning.

ALTER TABLE lm_state ADD COLUMN replay_id INTEGER NOT NULL DEFAULT 0;
-- The training step and loss at the moment the model wrote the equation.
-- Older rows stay empty. Disposition is updated later, these two are not.

ALTER TABLE model_attempts ADD COLUMN lm_step INTEGER;
ALTER TABLE model_attempts ADD COLUMN loss REAL;
-- Shape of the equation text at the moment of writing.
-- NULL means the text is not a statement of this fragment, not a depth of zero.
-- Disposition may change later. These three do not.

ALTER TABLE model_attempts ADD COLUMN expr_depth INTEGER;
ALTER TABLE model_attempts ADD COLUMN expr_operators INTEGER;
ALTER TABLE model_attempts ADD COLUMN expr_size INTEGER;
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
-- A repair run still draws formulas from <|propose|>. error_at is how many
-- characters of that formula Lean read before the first error. repair_ply 0
-- is an opening draw. 1 and 2 are endings continued from a kept prefix.

ALTER TABLE lm_state ADD COLUMN probe_task TEXT NOT NULL DEFAULT '';
ALTER TABLE lm_state ADD COLUMN repair_ply INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lm_state ADD COLUMN repair_prefix TEXT NOT NULL DEFAULT '';

ALTER TABLE model_attempts ADD COLUMN repair_ply INTEGER NOT NULL DEFAULT 0;
ALTER TABLE model_attempts ADD COLUMN error_at INTEGER;
-- A hole run still trains on generator sentences. Each cycle breaks one character
-- of a sentence proved with rfl. hole_from is the character that was there.
-- hole_char is the one character the model wrote back.

ALTER TABLE lm_state ADD COLUMN hole_from TEXT NOT NULL DEFAULT '';

ALTER TABLE model_attempts ADD COLUMN hole_index INTEGER;
ALTER TABLE model_attempts ADD COLUMN hole_char TEXT NOT NULL DEFAULT '';
ALTER TABLE model_attempts ADD COLUMN hole_from TEXT NOT NULL DEFAULT '';
ALTER TABLE model_attempts ADD COLUMN hole_broken TEXT NOT NULL DEFAULT '';
