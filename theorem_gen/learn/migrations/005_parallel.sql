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
