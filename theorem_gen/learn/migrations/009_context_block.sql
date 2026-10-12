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
