"""Read-only local page for one learn run. It never writes the database."""

from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from theorem_gen.learn.balance import LOSS_LIMIT, loss_is_ready, loss_streak, write_card
from theorem_gen.learn.effort import effort_level, lean_time_band
from theorem_gen.learn.minilm import BATCH_CANDIDATES
from theorem_gen.learn.prefix import unread_in_prefix

_WINDOW_S = 600
_ATTEMPT_NAMES = ("duplicate", "queued", "proved", "unresolved", "ill_formed", "refuted")
_FINISHED = ("duplicate", "proved", "unresolved", "ill_formed", "refuted")


def reading_eta(unread: int, earlier_unread: int, elapsed_s: float):
    """Seconds until the unread pile hits zero, from how fast it shrank.

    None when no time has passed or the pile is not shrinking. A new proved
    sentence raises `unread`, so that arrival is already inside the rate.
    """
    if elapsed_s <= 0:
        return None
    net = (earlier_unread - unread) / elapsed_s
    if net <= 0:
        return None
    return unread / net


def attempt_trend(attempts: dict) -> dict:
    """Compare new accepted equations in the last 10 minutes with the 10 before.

    Tries still waiting for Lean stay out of both rates.
    """

    def proved(window: str) -> int:
        return int(attempts["proved"][window])

    def done(window: str) -> int:
        return sum(int(attempts[name][window]) for name in _FINISHED)

    recent_done = done("recent")
    previous_done = done("previous")
    if recent_done == 0 and previous_done == 0:
        direction = "waiting" if int(attempts["queued"]["recent"]) else "none"
    elif recent_done == 0:
        direction = "quiet"
    elif previous_done == 0:
        direction = "first"
    else:
        recent_rate = proved("recent") / recent_done
        previous_rate = proved("previous") / previous_done
        if recent_rate > previous_rate:
            direction = "better"
        elif recent_rate < previous_rate:
            direction = "weaker"
        else:
            direction = "same"
    return {
        "direction": direction,
        "recent_proved": proved("recent"),
        "recent_done": recent_done,
        "previous_proved": proved("previous"),
        "previous_done": previous_done,
        "all_proved": proved("all"),
        "all_done": done("all"),
    }


def snapshot(db_path: Path, run_id: str, *, now: Optional[float] = None) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=8)
    conn.row_factory = sqlite3.Row
    try:
        if now is None:
            import time

            now = time.time()
        run = conn.execute(
            "SELECT status, curriculum_level, model_version FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        statuses = {
            row["current_status"]: row["n"]
            for row in conn.execute(
                """
                SELECT current_status, COUNT(*) AS n
                FROM candidates WHERE run_id=? GROUP BY current_status
                """,
                (run_id,),
            )
        }
        jobs = [
            {"job_type": row["job_type"], "state": row["state"], "n": row["n"]}
            for row in conn.execute(
                """
                SELECT job_type, state, COUNT(*) AS n
                FROM queue_jobs WHERE run_id=?
                GROUP BY job_type, state
                ORDER BY job_type, state
                """,
                (run_id,),
            )
        ]
        recent_candidates = conn.execute(
            """
            SELECT COUNT(*) AS n FROM candidates
            WHERE run_id=? AND CAST(created_at AS REAL) > ?
            """,
            (run_id, now - _WINDOW_S),
        ).fetchone()["n"]
        recent_validations = conn.execute(
            """
            SELECT COUNT(*) AS n FROM validations
            JOIN candidates ON candidates.id = validations.candidate_id
            WHERE candidates.run_id=? AND CAST(validations.created_at AS REAL) > ?
            """,
            (run_id, now - _WINDOW_S),
        ).fetchone()["n"]
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(validations)")
        }
        lean_bands = {}
        if "lean_ms" in columns:
            for row in conn.execute(
                """
                SELECT validations.lean_ms AS lean_ms, validations.result AS result
                FROM validations
                JOIN candidates ON candidates.id = validations.candidate_id
                WHERE candidates.run_id=? AND validations.lean_ms IS NOT NULL
                """,
                (run_id,),
            ):
                band = lean_time_band(int(row["lean_ms"]))
                lean_bands[band] = lean_bands.get(band, 0) + 1
        effort = {}
        origins = {"generator": 0, "model": 0}
        for row in conn.execute(
            """
            SELECT proof_method, ast_size, depth, provenance, current_status
            FROM candidates WHERE run_id=?
            """,
            (run_id,),
        ):
            origin = "model" if '"origin": "model"' in (row["provenance"] or "") else "generator"
            origins[origin] = origins.get(origin, 0) + 1
            level = effort_level(row["proof_method"], int(row["ast_size"]), int(row["depth"]))
            key = "none" if level is None else str(level)
            bucket = effort.setdefault(origin, {})
            cell = bucket.setdefault(key, {"n": 0, "proved": 0})
            cell["n"] += 1
            if row["current_status"] == "proved":
                cell["proved"] += 1
        cursor_id = 0
        lm = None
        if _table(conn, "lm_state"):
            row = conn.execute("SELECT * FROM lm_state WHERE run_id=?", (run_id,)).fetchone()
            if row is not None:
                cursor_id = int(row["cursor_id"])
                names = set(row.keys())
                raw_losses = row["recent_losses"] if "recent_losses" in names else "[]"
                try:
                    losses = json.loads(raw_losses or "[]")
                except (TypeError, json.JSONDecodeError):
                    losses = []
                lm = {
                    "step": row["step"],
                    "epoch": row["epoch"],
                    "cursor_id": cursor_id,
                    "last_loss": row["last_loss"],
                    "hold": bool(row["hold"]),
                    "weak_streak": row["weak_streak"],
                    "burst_left": int(row["burst_left"]) if "burst_left" in names else 0,
                    "study_left": int(row["study_left"]) if "study_left" in names else 0,
                    "loss_ready": loss_is_ready(losses),
                    "loss_limit": LOSS_LIMIT,
                    "loss_streak": loss_streak(losses),
                }
        study = conn.execute(
            """
            SELECT SUM(CASE WHEN held_out=0 THEN 1 ELSE 0 END) AS study_total
            FROM candidates
            WHERE run_id=? AND current_status='proved'
            """,
            (run_id,),
        ).fetchone()
        unread = unread_in_prefix(conn, run_id, cursor_id)
        study_total = int(study["study_total"] or 0)
        lean_lanes = _lean_lanes(conn, run_id)
        if lm is not None:
            model_lane = lean_lanes["model"]
            label, hint = write_card(
                hold=bool(lm["hold"]),
                burst_left=int(lm["burst_left"]),
                study_left=int(lm["study_left"]),
                streak=int(lm["loss_streak"]),
                model_backlog=int(model_lane["queued"]) + int(model_lane["leased"]),
                last_loss=lm["last_loss"],
            )
            lm["write_label"] = label
            lm["write_hint"] = hint
        attempts = {
            name: {"all": 0, "recent": 0, "previous": 0} for name in _ATTEMPT_NAMES
        }
        if _table(conn, "model_attempts"):
            recent_after = now - _WINDOW_S
            previous_after = now - (2 * _WINDOW_S)
            for row in conn.execute(
                """
                SELECT disposition,
                       COUNT(*) AS all_n,
                       SUM(CASE WHEN CAST(created_at AS REAL) > ? THEN 1 ELSE 0 END) AS recent_n,
                       SUM(CASE WHEN CAST(created_at AS REAL) > ?
                                 AND CAST(created_at AS REAL) <= ? THEN 1 ELSE 0 END) AS previous_n
                FROM model_attempts WHERE run_id=?
                GROUP BY disposition
                """,
                (recent_after, previous_after, recent_after, run_id),
            ):
                if row["disposition"] not in attempts:
                    continue
                attempts[row["disposition"]] = {
                    "all": int(row["all_n"]),
                    "recent": int(row["recent_n"]),
                    "previous": int(row["previous_n"]),
                }
        return {
            "run_id": run_id,
            "status": None if run is None else run["status"],
            "curriculum_level": None if run is None else run["curriculum_level"],
            "model_version": None if run is None else run["model_version"],
            "statuses": statuses,
            "jobs": jobs,
            "recent_candidates": recent_candidates,
            "recent_validations": recent_validations,
            "window_s": _WINDOW_S,
            "origins": origins,
            "effort": effort,
            "lean_bands": lean_bands,
            "lm": lm,
            "unread": unread,
            "study_total": study_total,
            "updates_left": (unread + BATCH_CANDIDATES - 1) // BATCH_CANDIDATES,
            "attempts": attempts,
            "attempt_trend": attempt_trend(attempts),
            "context_blocked": _context_blocked(conn, run_id),
            "lean_lanes": lean_lanes,
        }
    finally:
        conn.close()


def _lean_lanes(conn, run_id: str) -> dict:
    lanes = {
        "generator": {"queued": 0, "leased": 0, "done": 0, "failed": 0},
        "model": {"queued": 0, "leased": 0, "done": 0, "failed": 0},
    }
    if not _table(conn, "queue_jobs"):
        return lanes
    for row in conn.execute(
        """
        SELECT
          CASE
            WHEN instr(payload_json, '"origin": "model"') > 0 THEN 'model'
            ELSE 'generator'
          END AS lane,
          state,
          COUNT(*) AS n
        FROM queue_jobs
        WHERE run_id=? AND job_type='lean_validate'
        GROUP BY lane, state
        """,
        (run_id,),
    ):
        lane = row["lane"]
        if lane in lanes and row["state"] in lanes[lane]:
            lanes[lane][row["state"]] = int(row["n"])
    return lanes


def _context_blocked(conn, run_id: str) -> int:
    if not _table(conn, "context_blocks"):
        return 0
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM context_blocks WHERE run_id=?",
            (run_id,),
        ).fetchone()["n"]
    )


def _table(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def serve(db_path: Path, run_id: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    path = Path(db_path)
    page = _PAGE.replace("__RUN__", run_id)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/summary"):
                body = json.dumps(snapshot(path, run_id)).encode("utf-8")
                self._send(200, "application/json", body)
                return
            if self.path in {"/", "/index.html"}:
                self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
                return
            self._send(404, "text/plain", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"dashboard: http://{host}:{port}/", flush=True)
    server.serve_forever()


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__RUN__</title>
<style>
  body { font: 16px/1.45 Georgia, serif; margin: 28px auto; max-width: 980px; color: #1c1917; background: #fafaf9; }
  h1 { font-size: 28px; margin: 0; }
  h2 { font-size: 18px; margin: 28px 0 6px; }
  p { margin: 6px 0 0; color: #44403c; }
  table { width: 100%; border-collapse: collapse; background: white; margin-top: 8px; }
  th, td { border-bottom: 1px solid #e7e5e4; padding: 8px 10px; text-align: left; font-variant-numeric: tabular-nums; }
  th { color: #57534e; font-weight: 600; font-family: sans-serif; font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 18px; }
  .card { background: white; border: 1px solid #e7e5e4; border-radius: 8px; padding: 14px 16px; min-height: 108px; }
  .card span { display: block; color: #57534e; font: 13px/1.3 sans-serif; }
  .card b { display: block; font-size: 28px; margin: 4px 0; font-variant-numeric: tabular-nums; }
  .card em { display: block; font-style: normal; color: #78716c; font: 13px/1.35 sans-serif; min-height: 34px; }
  #eta { font-size: 22px; }
</style>
</head>
<body>
<h1>Run __RUN__</h1>
<p id="meta">Loading…</p>
<div class="grid">
  <div class="card"><span>Proved by Lean</span><b id="proved">—</b><em>Lean accepted the proof. This is the pile the model studies.</em></div>
  <div class="card"><span>Still open</span><b id="open">—</b><em>Checked, but not proved and not rejected as nonsense.</em></div>
  <div class="card"><span>New sentences, last 10 min</span><b id="recent">—</b><em id="recent-hint">How fast the generator is adding work.</em></div>
  <div class="card"><span>Training step</span><b id="step">—</b><em>One small update of the model weights. Each update reads 4 proved sentences.</em></div>
  <div class="card"><span>Still to read</span><b id="unread">—</b><em id="unread-hint">Proved sentences past the read position.</em></div>
  <div class="card"><span>Time to finish this read</span><b id="eta">—</b><em>A rough clock for the first read, from how fast the unread pile shrank over the last minute. The model may write earlier, once loss stays low.</em></div>
  <div class="card"><span>Epoch</span><b id="epoch">—</b><em>How many times the model has read every proved sentence. 0 means the first read is not finished.</em></div>
  <div class="card"><span>Loss</span><b id="loss">—</b><em>How surprised the model is by the next word. Lower is better. It began near 8.</em></div>
  <div class="card"><span>Read position</span><b id="cursor">—</b><em>How far the first read has walked. New proved sentences sit past this number.</em></div>
  <div class="card"><span>Model may write</span><b id="hold">—</b><em id="hold-hint">Low losses in a row, out of 10. At 10 it adds 10 equations, then studies for 200 steps.</em></div>
  <div class="card"><span>Weak tries in a row</span><b id="weak">—</b><em>Repeats and failed equations. At 8 the model stops writing and studies again.</em></div>
  <div class="card"><span>Waiting on the window</span><b id="context-blocked">—</b><em>Blocked by context limit. The start and end marks count. These proved sentences stay here until the window can hold the whole sentence.</em></div>
</div>
<h2>Queues</h2>
<p>Waiting is work not started. Checking is work happening now. Finished is done. Failed is given up. Lean checks for the generator and the model each have room for 128 unfinished items. One full lane does not close the other. The training cursor still waits at the first sentence that has no verdict yet, so a faster machine does not skip ahead.</p>
<table>
  <tr><th>Queue</th><th>Waiting</th><th>Checking</th><th>Finished</th><th>Failed</th></tr>
  <tr><td>Lean checks, generator</td><td id="lean-gen-queued">0</td><td id="lean-gen-leased">0</td><td id="lean-gen-done">0</td><td id="lean-gen-failed">0</td></tr>
  <tr><td>Lean checks, model</td><td id="lean-model-queued">0</td><td id="lean-model-leased">0</td><td id="lean-model-done">0</td><td id="lean-model-failed">0</td></tr>
  <tr><td>Generator ideas</td><td id="propose-queued">0</td><td id="propose-leased">0</td><td id="propose-done">0</td><td id="propose-failed">0</td></tr>
  <tr><td>Proof attempts</td><td id="prove-queued">0</td><td id="prove-leased">0</td><td id="prove-done">0</td><td id="prove-failed">0</td></tr>
  <tr><td>Second opinion</td><td id="alt-queued">0</td><td id="alt-leased">0</td><td id="alt-done">0</td><td id="alt-failed">0</td></tr>
  <tr><td>Counterexamples</td><td id="cex-queued">0</td><td id="cex-leased">0</td><td id="cex-done">0</td><td id="cex-failed">0</td></tr>
</table>
<h2>Proof shape</h2>
<p>These columns are the kind of proof. They are separate from the curriculum lesson at the top, which runs from 1 to 7 and says which generator abilities are on. A bigger number written inside an equation does not move the sentence to a higher column. A deeper formula can sit one column above its usual method. Each cell is proved / all.</p>
<p>1 decide is a comparison such as 0 &lt;= 5. 2 rfl means both sides compute to the same value, such as (7 + 6) + (5 + 2) = 20. 3 lemma points at a library fact, such as a + 0 = a. 4 rewrite uses a library step and then an assumption, such as a = b implies a + 0 = b. Not graded means we have no syntax tree for that row, which is how sentences from the model are stored.</p>
<table>
  <tr><th>Who wrote it</th><th>1 decide</th><th>2 rfl</th><th>3 lemma</th><th>4 rewrite</th><th>Not graded</th></tr>
  <tr><td>Generator</td><td id="g1">0 / 0</td><td id="g2">0 / 0</td><td id="g3">0 / 0</td><td id="g4">0 / 0</td><td id="gn">0 / 0</td></tr>
  <tr><td>Model</td><td id="m1">0 / 0</td><td id="m2">0 / 0</td><td id="m3">0 / 0</td><td id="m4">0 / 0</td><td id="mn">0 / 0</td></tr>
</table>
<h2>How long Lean took</h2>
<p id="lean-note">Only checks saved after timing was turned on. Older rows have no time.</p>
<table>
  <tr><th>Speed</th><th>Count</th></tr>
  <tr><td>Under 0.1 seconds</td><td id="lean-fast">0</td></tr>
  <tr><td>0.1 to 0.5 seconds</td><td id="lean-normal">0</td></tr>
  <tr><td>0.5 to 2 seconds</td><td id="lean-slow">0</td></tr>
  <tr><td>Over 2 seconds</td><td id="lean-heavy">0</td></tr>
</table>
<h2>Equations the model tried</h2>
<p>A repeat is skipped. A new one is checked by Lean. A good one is taught back to the model. Times are counted from the moment the model wrote the equation. Waiting for Lean is left out of the comparison. Better means a larger share of new accepted equations in the last 10 minutes than in the 10 minutes before.</p>
<p id="attempt-trend">No finished tries in the last 20 minutes, so there is no trend yet.</p>
<table>
  <tr><th>What happened</th><th>All time</th><th>Last 10 min</th><th>Previous 10 min</th></tr>
  <tr><td>Repeated something we already had</td><td id="att-duplicate-all">0</td><td id="att-duplicate-recent">0</td><td id="att-duplicate-previous">0</td></tr>
  <tr><td>Waiting for Lean</td><td id="att-queued-all">0</td><td id="att-queued-recent">0</td><td id="att-queued-previous">0</td></tr>
  <tr><td>Lean accepted it</td><td id="att-proved-all">0</td><td id="att-proved-recent">0</td><td id="att-proved-previous">0</td></tr>
  <tr><td>Lean could not prove it</td><td id="att-unresolved-all">0</td><td id="att-unresolved-recent">0</td><td id="att-unresolved-previous">0</td></tr>
  <tr><td>Not a valid formula</td><td id="att-ill_formed-all">0</td><td id="att-ill_formed-recent">0</td><td id="att-ill_formed-previous">0</td></tr>
  <tr><td>Lean refuted it</td><td id="att-refuted-all">0</td><td id="att-refuted-recent">0</td><td id="att-refuted-previous">0</td></tr>
</table>
<script>
function text(id, value) { document.getElementById(id).textContent = value; }
function job(rows, type, state) {
  const hit = (rows || []).find(r => r.job_type === type && r.state === state);
  return hit ? hit.n : 0;
}
function cell(block, key) {
  const item = (block || {})[key] || {n: 0, proved: 0};
  return item.proved + " / " + item.n;
}
async function refresh() {
  const data = await (await fetch("/api/summary")).json();
  const statuses = data.statuses || {};
  const lesson = data.curriculum_level == null ? "—" : data.curriculum_level;
  text("meta", "State: " + data.status + ". Curriculum lesson " + lesson + " of 7. Champion: " + data.model_version + ".");
  text("proved", statuses.proved || 0);
  text("open", statuses.unresolved || 0);
  text("recent", data.recent_candidates);
  text("recent-hint", data.recent_validations + " of those were checked by Lean in the same 10 minutes.");
  const lm = data.lm || {};
  text("step", lm.step ?? "—");
  const unread = data.unread ?? 0;
  text("unread", unread);
  text("unread-hint", unreadHint(lm, unread, data.study_total || 0, data.updates_left || 0));
  text("eta", readingClock(unread));
  text("epoch", lm.epoch ?? "—");
  text("loss", lm.last_loss == null ? "—" : Number(lm.last_loss).toFixed(3));
  text("cursor", lm.cursor_id ?? "—");
  text("hold", lm.write_label || "—");
  text("hold-hint", lm.write_hint || "");
  text("weak", lm.weak_streak ?? 0);
  text("context-blocked", data.context_blocked ?? 0);
  const jobs = data.jobs || [];
  const lanes = data.lean_lanes || {};
  for (const lane of ["generator", "model"]) {
    const block = lanes[lane] || {};
    const prefix = lane === "model" ? "lean-model" : "lean-gen";
    for (const state of ["queued", "leased", "done", "failed"]) text(prefix + "-" + state, block[state] || 0);
  }
  for (const [prefix, type] of [["propose","propose"],["prove","prove_primary"],["alt","prove_alternate_or_critique"],["cex","counterexample_search"]]) {
    for (const state of ["queued","leased","done","failed"]) text(prefix + "-" + state, job(jobs, type, state));
  }
  for (const [prefix, origin] of [["g","generator"],["m","model"]]) {
    const block = (data.effort || {})[origin] || {};
    text(prefix + "1", cell(block, "1"));
    text(prefix + "2", cell(block, "2"));
    text(prefix + "3", cell(block, "3"));
    text(prefix + "4", cell(block, "4"));
    text(prefix + "n", cell(block, "none"));
  }
  const bands = data.lean_bands || {};
  text("lean-fast", bands.fast || 0);
  text("lean-normal", bands.normal || 0);
  text("lean-slow", bands.slow || 0);
  text("lean-heavy", bands.heavy || 0);
  const attempts = data.attempts || {};
  for (const name of ["duplicate","queued","proved","unresolved","ill_formed","refuted"]) {
    const row = attempts[name] || {};
    text("att-" + name + "-all", row.all || 0);
    text("att-" + name + "-recent", row.recent || 0);
    text("att-" + name + "-previous", row.previous || 0);
  }
  text("attempt-trend", trendText(data.attempt_trend || {}));
}
const paceSamples = [];
function readingClock(unread) {
  if (unread === 0) return "Now";
  const now = Date.now();
  paceSamples.push({t: now, unread: unread});
  const horizon = now - 90000;
  while (paceSamples.length > 1 && paceSamples[0].t < horizon) paceSamples.shift();
  const span = (now - paceSamples[0].t) / 1000;
  if (span < 20) return "Measuring…";
  const net = (paceSamples[0].unread - unread) / span;
  if (net <= 0) return "Not shrinking";
  return formatDuration(unread / net);
}
function formatDuration(seconds) {
  const minutes = Math.round(seconds / 60);
  if (minutes < 2) return "about " + Math.max(1, Math.round(seconds)) + " seconds";
  if (minutes < 90) return "about " + minutes + " minutes";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (rest < 5) return "about " + hours + (hours === 1 ? " hour" : " hours");
  return "about " + hours + (hours === 1 ? " hour " : " hours ") + rest + " minutes";
}
function unreadHint(lm, unread, studyTotal, updatesLeft) {
  if (unread === 0) {
    return "Nothing unread in this pass. A newly proved sentence raises this again.";
  }
  return studyTotal + " proved sentences are in this pass. About " + updatesLeft
    + " weight updates left if no new sentence arrives. New proved sentences raise it again.";
}
function trendText(trend) {
  const recentProved = trend.recent_proved || 0;
  const recentDone = trend.recent_done || 0;
  const previousProved = trend.previous_proved || 0;
  const previousDone = trend.previous_done || 0;
  const allProved = trend.all_proved || 0;
  const allDone = trend.all_done || 0;
  const allTime = allDone
    ? " All time, " + allProved + " of " + allDone + " finished tries were new and accepted."
    : "";
  if (trend.direction === "waiting") {
    return "Tries from the last 10 minutes are still waiting for Lean, so there is no trend yet.";
  }
  if (trend.direction === "quiet") {
    return "Nothing finished in the last 10 minutes. The 10 minutes before that had "
      + previousDone + " finished tries." + allTime;
  }
  if (trend.direction === "first") {
    return recentProved + " of " + recentDone
      + " finished tries in the last 10 minutes were new and accepted. The 10 minutes before that had none.";
  }
  if (trend.direction === "better" || trend.direction === "weaker" || trend.direction === "same") {
    const lead = trend.direction === "better"
      ? "Better than the previous 10 minutes."
      : trend.direction === "weaker"
        ? "Weaker than the previous 10 minutes."
        : "Same share as the previous 10 minutes.";
    return lead + " Last 10 minutes: " + recentProved + " of " + recentDone
      + " new and accepted. Previous 10 minutes: " + previousProved + " of " + previousDone + ".";
  }
  return "No finished tries in the last 20 minutes, so there is no trend yet." + allTime;
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
