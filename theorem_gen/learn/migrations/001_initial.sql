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
