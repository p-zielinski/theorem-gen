"""One generator step, then a hundred draws, then one argmax line.

The hundred is the measurement. The argmax line is stored apart so a single
mode is visible next to the sample. Temperature 0 is argmax, which is what
the tests use.

A repair run draws twenty formulas instead. After Lean judges them, the same
model writes four endings from the formula it read furthest into. A second
four opens only when one of those endings gets further. No other model writes.
"""

from __future__ import annotations

import math
import re

DRAW_COUNT = 100
FORMULA_DRAW = 20
REPAIR_WIDTH = 4
REPAIR_PLIES = 2
CYCLE_LIMIT = 200
TEMPERATURE = 1.0
TOP_P = 0.9

_LEAN_LOCUS = re.compile(r"\.lean:(\d+):(\d+):")


def pick_token(scores: list, temperature: float, top_p: float, draw: float) -> int:
    """Index of the next character. Temperature 0 ignores `draw` and takes the max."""
    if not scores:
        raise ValueError("scores are empty")
    if temperature <= 0:
        best = 0
        for index, score in enumerate(scores):
            if score > scores[best]:
                best = index
        return best
    scaled = [float(score) / float(temperature) for score in scores]
    order = sorted(range(len(scaled)), key=lambda index: scaled[index], reverse=True)
    peak = scaled[order[0]]
    weights = [math.exp(scaled[index] - peak) for index in order]
    total = sum(weights)
    kept = []
    mass = []
    covered = 0.0
    for index, weight in zip(order, weights):
        kept.append(index)
        mass.append(weight)
        covered += weight / total
        if covered >= top_p:
            break
    target = min(max(float(draw), 0.0), 0.999999)
    cursor = 0.0
    normal = sum(mass)
    for index, weight in zip(kept, mass):
        cursor += weight / normal
        if target < cursor:
            return index
    return kept[-1]


def next_draw(draw_left: int, greedy_left: int) -> tuple:
    """The next text in an open cycle, and what remains after it is drawn.

    Samples go first. One argmax follows the hundred. An empty decoder means
    the cycle has nothing left to draw.
    """
    if draw_left > 0:
        return "sample", draw_left - 1, greedy_left
    if greedy_left > 0:
        return "argmax", 0, 0
    return "", 0, 0


def lean_error_at(message: str, source: str) -> int | None:
    """Character offset of the first Lean locus in `source`."""
    if not message or not source:
        return None
    match = _LEAN_LOCUS.search(message)
    if match is None:
        return None
    line = int(match.group(1))
    column = int(match.group(2))
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return None
    offset = sum(len(lines[index]) + 1 for index in range(line - 1))
    offset += max(column, 1) - 1
    if offset < 0 or offset > len(source):
        return None
    return offset


def formula_span(source: str, body: str) -> int | None:
    """Index of `body` inside the Lean file. The wrapper and the proof are outside."""
    if not body:
        return None
    wrapped = f"theorem model_eq : {body} := "
    at = source.find(wrapped)
    if at >= 0:
        return at + len("theorem model_eq : ")
    needle = f": {body} := "
    at = source.find(needle)
    if at >= 0:
        return at + len(": ")
    return None


def formula_progress(source: str, body: str, error_at: int | None) -> int | None:
    """How many formula characters Lean read before the error.

    None when the error sits in the wrapper or in the proof. The count is the
    length of the prefix worth continuing.
    """
    if error_at is None:
        return None
    start = formula_span(source, body)
    if start is None:
        return None
    end = start + len(body)
    if error_at <= start or error_at >= end:
        return None
    return error_at - start


def open_repairs(
    finished: int,
    parent_at: int,
    child_ats: list,
    *,
    width: int = REPAIR_WIDTH,
    plies: int = REPAIR_PLIES,
) -> int:
    """How many endings to draw.

    The first round needs a non-empty prefix. The next round opens only when
    a child got strictly further. A third round does not open.
    """
    if finished >= plies or finished < 0:
        return 0
    if finished == 0:
        return width if parent_at > 0 else 0
    best = max(child_ats) if child_ats else 0
    if best <= parent_at:
        return 0
    return width
