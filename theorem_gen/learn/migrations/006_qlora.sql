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
