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
