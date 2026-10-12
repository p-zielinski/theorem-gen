"""Read-only local page for one learn run. It never writes the database."""

from __future__ import annotations

import json
import math
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from theorem_gen.learn.balance import LOSS_LIMIT, freedom_plan, loss_is_ready, loss_streak, write_card
from theorem_gen.learn.effort import effort_level, lean_time_band, statement_depth, statement_measures
from theorem_gen.learn.prefix import unread_in_prefix

_WINDOW_S = 600
_ATTEMPT_NAMES = ("duplicate", "queued", "proved", "unresolved", "ill_formed", "refuted")
_FINISHED = ("duplicate", "proved", "unresolved", "ill_formed", "refuted")


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


def own_equation_summary(attempts: dict) -> dict:
    """Accepted own equations, and how many Lean has already judged.

    A repeat is judged and is not accepted. A row still waiting is neither.
    """
    accepted = int(attempts.get("proved", {}).get("all", 0))
    waiting = int(attempts.get("queued", {}).get("all", 0))
    finished = sum(int(attempts.get(name, {}).get("all", 0)) for name in _FINISHED)
    return {"accepted": accepted, "finished": finished, "waiting": waiting}


def acceptance_series(rows, window: int = 10) -> list:
    """One point per judged equation, in time order.

    `recent` is the accepted share of the last `window` judged equations.
    `overall` is the accepted share from the first judged equation through this one.
    A waiting row is left out. A later fall in `recent` is a stretch Lean did not accept.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("window must be a positive int")
    judged = []
    accepted = 0
    points = []
    for created_at, disposition in rows:
        if disposition == "queued":
            continue
        ok = disposition == "proved"
        judged.append(ok)
        if ok:
            accepted += 1
        start = max(0, len(judged) - window)
        recent = judged[start:]
        points.append(
            {
                "t": float(created_at),
                "n": len(judged),
                "recent": sum(recent) / len(recent),
                "overall": accepted / len(judged),
            }
        )
    return points


# Two-sided 95% Student t critical value at 19 degrees of freedom.
# Used only for a block of 20 accepted equations.
_T_95_DF_19 = 2.093024054408263
_SHAPE_BLOCK = 20


def complexity_series(rows, window: int = 10) -> dict:
    """Mean shape of equations Lean accepted, in the order they were written.

    Each row is `(created_at, disposition, depth, operators, size)`. A waiting
    row is left out. A proved row with a missing measure is counted in
    `unmeasured` and is not entered as zero. `recent` is the mean depth of the
    last `window` accepted equations. `overall` is the mean from the first.
    Each finished block of 20 carries the 95% interval of its mean.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("window must be a positive int")
    accepted = []
    unmeasured = 0
    for created_at, disposition, depth, operators, size in rows:
        if disposition != "proved":
            continue
        if depth is None or operators is None or size is None:
            unmeasured += 1
            continue
        accepted.append((float(created_at), int(depth), int(operators), int(size)))
    points = []
    totals = [0, 0, 0]
    for index, item in enumerate(accepted):
        totals[0] += item[1]
        totals[1] += item[2]
        totals[2] += item[3]
        window_rows = accepted[max(0, index + 1 - window) : index + 1]
        count = index + 1
        points.append(
            {
                "t": item[0],
                "n": count,
                "depth": item[1],
                "operators": item[2],
                "size": item[3],
                "recent": _mean(row[1] for row in window_rows),
                "overall": totals[0] / count,
                "recent_operators": _mean(row[2] for row in window_rows),
                "overall_operators": totals[1] / count,
                "recent_size": _mean(row[3] for row in window_rows),
                "overall_size": totals[2] / count,
            }
        )
    return {
        "accepted": len(accepted),
        "unmeasured": unmeasured,
        "points": points,
        "depth_blocks": _mean_blocks(accepted, 1),
        "operator_blocks": _mean_blocks(accepted, 2),
        "size_blocks": _mean_blocks(accepted, 3),
    }


def _mean(values) -> float:
    found = list(values)
    return sum(found) / len(found)


def _mean_blocks(accepted, column: int) -> list:
    blocks = []
    complete = len(accepted) // _SHAPE_BLOCK
    for index in range(complete):
        values = [
            item[column]
            for item in accepted[index * _SHAPE_BLOCK : (index + 1) * _SHAPE_BLOCK]
        ]
        mean = sum(values) / _SHAPE_BLOCK
        variance = sum((item - mean) ** 2 for item in values) / (_SHAPE_BLOCK - 1)
        spread = math.sqrt(variance)
        half = _T_95_DF_19 * spread / math.sqrt(_SHAPE_BLOCK)
        blocks.append(
            {
                "n": (index + 1) * _SHAPE_BLOCK,
                "mean": mean,
                "sd": spread,
                "low": mean - half,
                "high": mean + half,
            }
        )
    return blocks


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
                    "replay_id": int(row["replay_id"]) if "replay_id" in names else 0,
                    "last_loss": row["last_loss"],
                    "hold": bool(row["hold"]),
                    "weak_streak": row["weak_streak"],
                    "burst_left": int(row["burst_left"]) if "burst_left" in names else 0,
                    "study_left": int(row["study_left"]) if "study_left" in names else 0,
                    "loss_ready": loss_is_ready(losses),
                    "loss_limit": LOSS_LIMIT,
                    "loss_streak": loss_streak(losses),
                }
        unread = unread_in_prefix(conn, run_id, cursor_id)
        plan = freedom_plan(_judged_dispositions(conn, run_id))
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
                burst=plan["burst"],
                study=plan["study"],
                weak=plan["weak"],
            )
            lm["write_label"] = label
            lm["write_hint"] = hint
        attempts = {
            name: {"all": 0, "recent": 0, "previous": 0} for name in _ATTEMPT_NAMES
        }
        recent_attempts = []
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
            recent_attempts = _recent_attempts(conn, run_id)
        series = _acceptance_series(conn, run_id)
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
            "attempts": attempts,
            "attempt_trend": attempt_trend(attempts),
            "own": own_equation_summary(attempts),
            "own_series": series,
            "freedom": _freedom_with_times(plan, series),
            "complexity": _complexity(conn, run_id),
            "recent_attempts": recent_attempts,
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


def _recent_attempts(conn, run_id: str) -> list:
    """Newest own equations, with the step and loss stored at the time of writing."""
    names = {row[1] for row in conn.execute("PRAGMA table_info(model_attempts)")}
    step = "lm_step" if "lm_step" in names else "NULL AS lm_step"
    loss = "loss" if "loss" in names else "NULL AS loss"
    depth = "expr_depth" if "expr_depth" in names else "NULL AS expr_depth"
    operators = "expr_operators" if "expr_operators" in names else "NULL AS expr_operators"
    size = "expr_size" if "expr_size" in names else "NULL AS expr_size"
    rows = conn.execute(
        f"""
        SELECT equation, disposition, {step}, {loss}, {depth}, {operators}, {size}
        FROM model_attempts
        WHERE run_id=?
        ORDER BY id DESC
        LIMIT 8
        """,
        (run_id,),
    ).fetchall()
    found = []
    for row in rows:
        shape = _shape_of(row)
        found.append(
            {
                "equation": row["equation"],
                "disposition": row["disposition"],
                "lm_step": None if row["lm_step"] is None else int(row["lm_step"]),
                "loss": None if row["loss"] is None else float(row["loss"]),
                "expr_depth": None if shape is None else shape["depth"],
                "expr_operators": None if shape is None else shape["operators"],
                "expr_size": None if shape is None else shape["size"],
            }
        )
    return found


def _judged_dispositions(conn, run_id: str) -> list:
    if not _table(conn, "model_attempts"):
        return []
    rows = conn.execute(
        """
        SELECT disposition, equation FROM model_attempts
        WHERE run_id=? AND disposition != 'queued'
        ORDER BY CAST(created_at AS REAL), id
        """,
        (run_id,),
    ).fetchall()
    return [
        (row["disposition"], statement_depth(row["equation"] or ""))
        for row in rows
    ]


def _freedom_with_times(plan: dict, series: list) -> dict:
    times = {point["n"]: point["t"] for point in series}
    blocks = []
    for block in plan["blocks"]:
        marked = dict(block)
        if block["n"] in times:
            marked["t"] = times[block["n"]]
        blocks.append(marked)
    marked_plan = dict(plan)
    marked_plan["blocks"] = blocks
    return marked_plan


def _complexity(conn, run_id: str) -> dict:
    if not _table(conn, "model_attempts"):
        return complexity_series(())
    names = {row[1] for row in conn.execute("PRAGMA table_info(model_attempts)")}
    depth = "expr_depth" if "expr_depth" in names else "NULL AS expr_depth"
    operators = "expr_operators" if "expr_operators" in names else "NULL AS expr_operators"
    size = "expr_size" if "expr_size" in names else "NULL AS expr_size"
    rows = conn.execute(
        f"""
        SELECT created_at, disposition, equation, {depth}, {operators}, {size}
        FROM model_attempts
        WHERE run_id=?
        ORDER BY CAST(created_at AS REAL), id
        """,
        (run_id,),
    ).fetchall()
    shaped = []
    for row in rows:
        measures = _shape_of(row)
        shaped.append(
            (
                row["created_at"],
                row["disposition"],
                None if measures is None else measures["depth"],
                None if measures is None else measures["operators"],
                None if measures is None else measures["size"],
            )
        )
    return complexity_series(shaped)


def _shape_of(row) -> Optional[dict]:
    """Stored shape, or the shape of the equation text when the columns are empty."""
    keys = row.keys()
    if "expr_depth" in keys and row["expr_depth"] is not None:
        return {
            "depth": int(row["expr_depth"]),
            "operators": int(row["expr_operators"]),
            "size": int(row["expr_size"]),
        }
    if "equation" not in keys:
        return None
    return statement_measures(row["equation"] or "")


def _acceptance_series(conn, run_id: str) -> list:
    if not _table(conn, "model_attempts"):
        return []
    rows = conn.execute(
        """
        SELECT created_at, disposition FROM model_attempts
        WHERE run_id=? AND disposition != 'queued'
        ORDER BY CAST(created_at AS REAL), id
        """,
        (run_id,),
    ).fetchall()
    return acceptance_series((row["created_at"], row["disposition"]) for row in rows)


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
  ul { margin: 8px 0 0; padding-left: 18px; }
  #own-chart { background: white; border: 1px solid #e7e5e4; border-radius: 8px; margin-top: 10px; }
  #own-chart svg { display: block; width: 100%; height: auto; }
  .legend { font: 13px/1.4 sans-serif; color: #57534e; margin-top: 6px; }
  .swatch { display: inline-block; width: 18px; height: 3px; margin: 0 6px 2px 0; vertical-align: middle; }
  table { width: 100%; border-collapse: collapse; background: white; margin-top: 8px; }
  th, td { border-bottom: 1px solid #e7e5e4; padding: 8px 10px; text-align: left; font-variant-numeric: tabular-nums; }
  th { color: #57534e; font-weight: 600; font-family: sans-serif; font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 18px; }
  .card { background: white; border: 1px solid #e7e5e4; border-radius: 8px; padding: 14px 16px; min-height: 108px; }
  .card span { display: block; color: #57534e; font: 13px/1.3 sans-serif; }
  .card b { display: block; font-size: 28px; margin: 4px 0; font-variant-numeric: tabular-nums; }
  .card em { display: block; font-style: normal; color: #78716c; font: 13px/1.35 sans-serif; min-height: 34px; }
</style>
</head>
<body>
<h1>Run __RUN__</h1>
<p id="meta">Loading…</p>
<div class="grid">
  <div class="card"><span>Own equations accepted</span><b id="own-accepted">—</b><em id="own-accepted-hint">New equations the model wrote that Lean accepted. A repeat of a known sentence is not counted.</em></div>
  <div class="card"><span>Accepted share</span><b id="own-share">—</b><em>Of the own equations Lean has already judged. Ones still waiting are left out. This is not a grade of difficulty.</em></div>
  <div class="card"><span>Freedom</span><b id="freedom">—</b><em id="freedom-hint">Baseline is 10 equations in a turn, then 200 study steps. The latest block of 20 sets it. An average block comes back here.</em></div>
  <div class="card"><span>Proved by Lean</span><b id="proved">—</b><em>Lean accepted the proof. This is the pile the model studies.</em></div>
  <div class="card"><span>Still open</span><b id="open">—</b><em>Checked, but not proved and not rejected as nonsense.</em></div>
  <div class="card"><span>New sentences, last 10 min</span><b id="recent">—</b><em id="recent-hint">How fast the generator is adding work.</em></div>
  <div class="card"><span>Training step</span><b id="step">—</b><em>One small update of the model weights. Each update reads 4 proved sentences.</em></div>
  <div class="card"><span>New material</span><b id="unread">—</b><em id="unread-hint">Proved sentences the first read has not reached. Replay of sentences already behind the cursor is not included.</em></div>
  <div class="card"><span>Epoch</span><b id="epoch">—</b><em>How many times the model has read every proved sentence. 0 means the first read is not finished.</em></div>
  <div class="card"><span>Loss</span><b id="loss">—</b><em>How surprised the model is by the next word. Lower is better. It began near 8.</em></div>
  <div class="card"><span>Read position</span><b id="cursor">—</b><em>How far the first read has walked. New proved sentences sit past this number.</em></div>
  <div class="card"><span>Replay position</span><b id="replay">—</b><em>Last id of the repeat pass over sentences already read, from the generator and the model. A resume continues after this number. 0 means the next pass starts at the beginning.</em></div>
  <div class="card"><span>Model may write</span><b id="hold">—</b><em id="hold-hint">Low losses in a row, out of 10. At 10 it adds 10 equations, then studies for 200 steps.</em></div>
  <div class="card"><span>Weak tries in a row</span><b id="weak">—</b><em>Repeats and failed equations. At 8 the model stops writing and studies again.</em></div>
  <div class="card"><span>Waiting on the window</span><b id="context-blocked">—</b><em>Blocked by context limit. The start and end marks count. These proved sentences stay here until the window can hold the whole sentence.</em></div>
</div>
<h2>Accepted share over time</h2>
<p>Each point is one equation Lean has already judged, in the order it was written. The dark line is the share of the last 10. The pale line is the share from the first judged equation up to that moment. A rust bar is one block of 20 and its margin. Freedom looks only at the latest of those bars. Above one half, with the margin, the turn widens. An average bar returns it to the baseline. Waiting equations are not on the chart.</p>
<div id="own-chart"></div>
<p class="legend"><span class="swatch" style="background:#1c1917"></span>Last 10 judged <span class="swatch" style="background:#a8a29e;margin-left:16px"></span>From the start <span class="swatch" style="background:#9a3412;margin-left:16px"></span>Block of 20, with margin</p>
<h2>Depth of accepted equations</h2>
<p>These are new equations the model wrote that Lean accepted. Depth, the number of operators, and the number of nodes are the same three counts as the generator's syntax tree. A numeral of any size is one leaf. A comparison such as 0 = 0 has depth 1 and no operator. Each + or * counts as one operator. Text that is not a statement of this fragment is left out, not entered as zero. The dark line is the mean depth of the last 10 accepted equations. The pale line is the mean from the first. A bar on every 20 is the 95% interval of that block's mean. The freedom rule above uses a coarser version of this depth. This chart is the measurement.</p>
<div id="depth-chart"></div>
<p class="legend"><span class="swatch" style="background:#1c1917"></span>Mean of the last 10 <span class="swatch" style="background:#a8a29e;margin-left:16px"></span>Mean from the start <span class="swatch" style="background:#1e3a8a;margin-left:16px"></span>95% interval of 20</p>
<p id="shape-summary">No accepted equation with a measured shape yet.</p>
<h2>Operators in accepted equations</h2>
<p>The same accepted equations. A comparison by itself stays at zero. A chain of additions raises the count by one per +.</p>
<div id="operator-chart"></div>
<p id="operator-summary"></p>
<h2>Latest own equations</h2>
<p>Newest first. Accepted means Lean took a sentence that was not already in the run. The step and loss are the ones at the moment of writing. Depth is the nesting of that sentence. It is not a grade against the generator, and a longer number is not a deeper sentence.</p>
<ul id="own-list"><li>None yet.</li></ul>
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
  const own = data.own || {};
  text("own-accepted", own.accepted ?? 0);
  text("own-accepted-hint", ownHint(own));
  text("own-share", own.finished ? (own.accepted + " / " + own.finished) : "—");
  const plan = data.freedom || {};
  text("freedom", (plan.level || 0) === 0 ? "Baseline" : ((plan.burst || 10) + " / " + (plan.study || 200)));
  text("freedom-hint", freedomHint(plan));
  ownList(data.recent_attempts || []);
  drawShare(data.own_series || [], plan.blocks || []);
  drawShape(data.complexity || {});
  text("proved", statuses.proved || 0);
  text("open", statuses.unresolved || 0);
  text("recent", data.recent_candidates);
  text("recent-hint", data.recent_validations + " of those were checked by Lean in the same 10 minutes.");
  const lm = data.lm || {};
  text("step", lm.step ?? "—");
  const unread = data.unread ?? 0;
  text("unread", unread);
  text("unread-hint", unreadHint(unread));
  text("epoch", lm.epoch ?? "—");
  text("loss", lm.last_loss == null ? "—" : Number(lm.last_loss).toFixed(3));
  text("cursor", lm.cursor_id ?? "—");
  text("replay", lm.replay_id ?? "—");
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
function freedomHint(plan) {
  const burst = plan.burst || 10;
  const study = plan.study || 200;
  const weak = plan.weak || 8;
  const name = (plan.level || 0) === 0 ? "Baseline" : ((plan.level || 0) === 1 ? "Wider" : "Widest");
  return name + ". " + burst + " equations, then " + study + " study steps. Stop after " + weak + " weak tries in a row. An average block of 20 returns to the baseline. " + (plan.next_in || 20) + " judged equations until the next block.";
}
function drawShare(points, blocks) {
  const host = document.getElementById("own-chart");
  host.replaceChildren();
  const w = 920, h = 220, left = 40, right = 16, top = 16, bottom = 32;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + w + " " + h);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Accepted share of the model's own equations over time");
  function add(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const key of Object.keys(attrs)) node.setAttribute(key, attrs[key]);
    svg.appendChild(node);
    return node;
  }
  if (!points.length) {
    add("text", {x: left, y: h / 2, fill: "#78716c", "font-size": "14", "font-family": "sans-serif"}).textContent = "No judged equations yet.";
    host.appendChild(svg);
    return;
  }
  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const span = t1 - t0;
  function xAt(point, index) {
    const along = span === 0
      ? (points.length === 1 ? 0.5 : index / (points.length - 1))
      : (point.t - t0) / span;
    return left + along * (w - left - right);
  }
  function yAt(share) {
    return top + (1 - share) * (h - top - bottom);
  }
  for (const share of [0, 0.5, 1]) {
    const y = yAt(share);
    add("line", {x1: left, y1: y, x2: w - right, y2: y, stroke: "#e7e5e4"});
    add("text", {x: 4, y: y + 4, fill: "#78716c", "font-size": "11", "font-family": "sans-serif"}).textContent = Math.round(share * 100) + "%";
  }
  function line(key, color) {
    const d = points.map((point, index) => (index ? "L" : "M") + xAt(point, index).toFixed(1) + " " + yAt(point[key]).toFixed(1)).join(" ");
    add("path", {d: d, fill: "none", stroke: color, "stroke-width": "2"});
  }
  line("overall", "#a8a29e");
  line("recent", "#1c1917");
  for (const block of blocks || []) {
    const index = points.findIndex((point) => point.n === block.n);
    if (index < 0) continue;
    const x = xAt(points[index], index);
    add("line", {x1: x, y1: yAt(block.low), x2: x, y2: yAt(block.high), stroke: "#9a3412", "stroke-width": "3"});
    add("circle", {cx: x, cy: yAt(block.p), r: "2.5", fill: "#9a3412"});
  }
  if (points.length === 1) {
    add("circle", {cx: xAt(points[0], 0), cy: yAt(points[0].recent), r: "3", fill: "#1c1917"});
  }
  add("text", {x: left, y: h - 8, fill: "#78716c", "font-size": "11", "font-family": "sans-serif"}).textContent = clockLabel(t0);
  const end = add("text", {x: w - right, y: h - 8, fill: "#78716c", "font-size": "11", "font-family": "sans-serif", "text-anchor": "end"});
  end.textContent = span === 0 ? "same moment" : clockLabel(t1);
  host.appendChild(svg);
}
function drawShape(complexity) {
  const points = complexity.points || [];
  drawMeasure("depth-chart", points, complexity.depth_blocks || [], "depth", "recent", "overall", "Mean depth of accepted equations");
  drawMeasure("operator-chart", points, complexity.operator_blocks || [], "operators", "recent_operators", "overall_operators", "Mean operator count of accepted equations");
  const summary = document.getElementById("shape-summary");
  const operators = document.getElementById("operator-summary");
  if (!points.length) {
    const skipped = complexity.unmeasured ? " " + complexity.unmeasured + " accepted equations had no measurable shape." : "";
    summary.textContent = "No accepted equation with a measured shape yet." + skipped;
    operators.textContent = "";
    return;
  }
  const last = points[points.length - 1];
  const skipped = complexity.unmeasured ? " Left out: " + complexity.unmeasured + "." : "";
  summary.textContent = "Last 10: depth " + last.recent.toFixed(2) + ". From the start: depth " + last.overall.toFixed(2) + ". Nodes, from the start: " + last.overall_size.toFixed(2) + "." + skipped;
  operators.textContent = "Last 10: " + last.recent_operators.toFixed(2) + " operators. From the start: " + last.overall_operators.toFixed(2) + ".";
}
function drawMeasure(hostId, points, blocks, key, recentKey, overallKey, label) {
  const host = document.getElementById(hostId);
  host.replaceChildren();
  const w = 920, h = 220, left = 40, right = 16, top = 16, bottom = 32;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + w + " " + h);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", label);
  function add(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const keyName of Object.keys(attrs)) node.setAttribute(keyName, attrs[keyName]);
    svg.appendChild(node);
    return node;
  }
  if (!points.length) {
    add("text", {x: left, y: h / 2, fill: "#78716c", "font-size": "14", "font-family": "sans-serif"}).textContent = "No accepted equation with a measured shape yet.";
    host.appendChild(svg);
    return;
  }
  const ys = [];
  for (const point of points) ys.push(point[key], point[recentKey], point[overallKey]);
  for (const block of blocks) ys.push(block.low, block.high, block.mean);
  const yMax = Math.max(1, ...ys.map((value) => Math.max(0, value)));
  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const span = t1 - t0;
  function xAt(point, index) {
    const along = span === 0
      ? (points.length === 1 ? 0.5 : index / (points.length - 1))
      : (point.t - t0) / span;
    return left + along * (w - left - right);
  }
  function yAt(value) {
    return top + (1 - Math.max(0, value) / yMax) * (h - top - bottom);
  }
  for (const mark of [0, yMax / 2, yMax]) {
    const y = yAt(mark);
    add("line", {x1: left, y1: y, x2: w - right, y2: y, stroke: "#e7e5e4"});
    add("text", {x: 4, y: y + 4, fill: "#78716c", "font-size": "11", "font-family": "sans-serif"}).textContent = mark.toFixed(mark >= 10 ? 0 : 1);
  }
  function line(field, color) {
    const d = points.map((point, index) => (index ? "L" : "M") + xAt(point, index).toFixed(1) + " " + yAt(point[field]).toFixed(1)).join(" ");
    add("path", {d: d, fill: "none", stroke: color, "stroke-width": "2"});
  }
  for (const point of points) {
    const index = points.indexOf(point);
    add("circle", {cx: xAt(point, index), cy: yAt(point[key]), r: "2", fill: "#78716c"});
  }
  line(overallKey, "#a8a29e");
  line(recentKey, "#1c1917");
  for (const block of blocks) {
    const index = points.findIndex((point) => point.n === block.n);
    if (index < 0) continue;
    const x = xAt(points[index], index);
    add("line", {x1: x, y1: yAt(block.low), x2: x, y2: yAt(block.high), stroke: "#1e3a8a", "stroke-width": "3"});
    add("circle", {cx: x, cy: yAt(block.mean), r: "2.5", fill: "#1e3a8a"});
  }
  add("text", {x: left, y: h - 8, fill: "#78716c", "font-size": "11", "font-family": "sans-serif"}).textContent = clockLabel(t0);
  const end = add("text", {x: w - right, y: h - 8, fill: "#78716c", "font-size": "11", "font-family": "sans-serif", "text-anchor": "end"});
  end.textContent = span === 0 ? "same moment" : clockLabel(t1);
  host.appendChild(svg);
}
function clockLabel(seconds) {
  const when = new Date(seconds * 1000);
  return when.toLocaleString(undefined, {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}
function ownHint(own) {
  if (!own.finished && !own.waiting) {
    return "None yet. Writing starts after 10 losses in a row under 0.45. A repeat of a known sentence is not counted.";
  }
  if (!own.accepted) {
    return "Lean has judged " + own.finished + ". None were a new accepted equation. Still waiting: " + (own.waiting || 0) + ".";
  }
  return "New equations the model wrote that Lean accepted. Repeats are not counted. Still waiting: " + (own.waiting || 0) + ".";
}
function verdictLabel(name) {
  return {
    duplicate: "Repeat",
    queued: "Waiting for Lean",
    proved: "Accepted",
    unresolved: "Not proved",
    ill_formed: "Not a formula",
    refuted: "Refuted"
  }[name] || name;
}
function ownList(rows) {
  const list = document.getElementById("own-list");
  list.replaceChildren();
  if (!rows.length) {
    const item = document.createElement("li");
    item.textContent = "None yet. Writing starts after 10 losses in a row under 0.45.";
    list.appendChild(item);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const where = [];
    if (row.lm_step != null) where.push("step " + row.lm_step);
    if (row.loss != null) where.push("loss " + Number(row.loss).toFixed(3));
    if (row.expr_depth != null) where.push("depth " + row.expr_depth + ", " + row.expr_operators + " operators, " + row.expr_size + " nodes");
    const tail = where.length ? " (" + where.join(", ") + ")" : "";
    item.textContent = verdictLabel(row.disposition) + ". " + row.equation + tail;
    list.appendChild(item);
  }
}
function unreadHint(unread) {
  if (unread === 0) {
    return "The first read has caught up. Replay continues over sentences already read. A newly proved sentence raises this again.";
  }
  return "Proved sentences the first read has not reached. The replay walks sentences already behind the cursor and is not in this number.";
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
