"""Which queue may run. A low-loss burst may write, then study takes over.

Freedom is the latest block of 20 judged equations, not a high-water mark.
The baseline is 40 equations and 40 study steps. A block that does not clear
one half, including an average one, stays there, so a model that is still
missing gets many tries and a short gap. A Wilson lower bound above one half
takes 80 equations and 20 study steps. Above three quarters, 160 and 10.
Clearly deep accepted equations can add one step on the wider turn. They do
not hold a turn the share has given back.
"""

from __future__ import annotations

import math
from typing import Optional

WEAK_LIMIT = 8
LOSS_LIMIT = 0.45
LOSS_STREAK = 10
# Two adjacent blocks of forward-step losses. A level curve opens a turn
# when ten losses under LOSS_LIMIT never arrive. Replay steps are not in this list.
PLATEAU_WINDOW = 40
PLATEAU_BAND = 0.05
PLATEAU_CEILING = 1.0
LOSS_HISTORY = PLATEAU_WINDOW * 2
SAMPLE_BURST = 40
STUDY_STEPS = 40
BLOCK_SIZE = 20
# Lower Wilson bound of the latest block. At or below one half is the baseline.
STRONG_LOW = 0.5
EXCELLENT_LOW = 0.75
# Turn length, study steps, weak tries in a row. A low share still writes
# as much as it studies. A higher share writes more and studies less.
FREEDOM = (
    (40, 40, 8),
    (80, 20, 12),
    (160, 10, 16),
)


def loss_is_level(losses) -> bool:
    """True when the last 80 losses form two blocks of 40 with means within 0.05.

    The later mean also has to sit under 1. A curve that is still falling, or
    that has just jumped, is not level. A flat curve near 0.6 is.
    """
    recent = [float(loss) for loss in list(losses or [])[-LOSS_HISTORY:]]
    if len(recent) < LOSS_HISTORY:
        return False
    older = recent[:PLATEAU_WINDOW]
    newer = recent[PLATEAU_WINDOW:]
    older_mean = sum(older) / PLATEAU_WINDOW
    newer_mean = sum(newer) / PLATEAU_WINDOW
    if newer_mean >= PLATEAU_CEILING:
        return False
    return abs(newer_mean - older_mean) <= PLATEAU_BAND


def loss_gate(losses) -> str:
    """Return `low`, `level`, or an empty string."""
    recent = list(losses or [])[-LOSS_STREAK:]
    if len(recent) >= LOSS_STREAK and all(float(loss) < LOSS_LIMIT for loss in recent):
        return "low"
    if loss_is_level(losses):
        return "level"
    return ""


def loss_is_ready(losses) -> bool:
    """True when ten losses are under 0.45, or the curve over 80 losses is level."""
    return loss_gate(losses) != ""


def loss_streak(losses) -> int:
    """How many losses at the end of the list are under 0.45, up to 10."""
    streak = 0
    for loss in reversed(list(losses or [])):
        if float(loss) >= LOSS_LIMIT:
            break
        streak += 1
        if streak == LOSS_STREAK:
            break
    return streak


def write_card(
    *,
    hold: bool,
    burst_left: int,
    study_left: int,
    streak: int,
    model_backlog: int,
    high_water: int = 128,
    last_loss: float | None = None,
    burst: int = SAMPLE_BURST,
    study: int = STUDY_STEPS,
    weak: int = WEAK_LIMIT,
    gate: str = "",
) -> tuple:
    """Short label and one sentence for the current writing state."""
    if hold:
        return (
            "No",
            f"{weak} weak tries in a row. It reads proved sentences again before it may write.",
        )
    if burst_left > 0 and model_backlog >= high_water:
        return (
            "Waiting",
            "It may write, but its Lean lane is full"
            f" ({model_backlog} unfinished). This turn of {burst_left} equations waits and is not spent.",
        )
    if burst_left > 0:
        if gate == "level":
            reason = "The loss curve is level."
        else:
            reason = f"Loss stayed under {LOSS_LIMIT} for {LOSS_STREAK} updates."
        return (
            "Yes",
            f"{reason} {burst_left} of {burst} equations are still to add."
            f" Then it studies for {study} steps.",
        )
    if study_left > 0:
        return (
            "Studying",
            f"{study_left} study steps left after its last equations."
            f" Another turn starts after {LOSS_STREAK} updates under {LOSS_LIMIT},"
            f" or when the curve is level again.",
        )
    if gate == "level":
        return (
            "Ready",
            f"The last {LOSS_HISTORY} updates sit level."
            f" The next step adds {burst} equations, then studies for {study} steps.",
        )
    if last_loss is not None and streak == 0:
        shown = f"{float(last_loss):.3f}"
        return (
            f"0/{LOSS_STREAK}",
            f"The last update was {shown}."
            f" {LOSS_STREAK} updates in a row under {LOSS_LIMIT} open a turn at once."
            f" A level curve over {LOSS_HISTORY} updates opens one too."
            f" Then {burst} equations and {study} study steps.",
        )
    return (
        f"{streak}/{LOSS_STREAK}",
        f"{streak} updates in a row are under {LOSS_LIMIT}."
        f" At {LOSS_STREAK} it adds {burst} equations, then studies for {study} steps.",
    )


def remember_loss(losses, loss: float) -> list:
    recent = list(losses)
    recent.append(float(loss))
    return recent[-LOSS_HISTORY:]


def open_burst(burst_left: int, study_left: int, ready: bool, burst: int = SAMPLE_BURST) -> tuple:
    """Start a turn only when loss is ready and the last turn is finished."""
    if burst_left > 0 or study_left > 0 or not ready:
        return burst_left, study_left
    return burst, study_left


def after_sample(
    burst_left: int,
    study_left: int,
    disposition: str,
    study: int = STUDY_STEPS,
) -> tuple:
    """Every try spends one place in the turn. Then study resumes.

    A repeat and a sentence Lean will not accept count. The turn ends either
    way, so the next block of judged equations can move the share.
    """
    if burst_left <= 0 or not disposition:
        return burst_left, study_left
    burst_left -= 1
    if burst_left == 0:
        study_left = study
    return burst_left, study_left


def fit_study(study_left: int, study: int) -> int:
    """Cut a stored study gap down to the current budget.

    A gap that is already shorter stays. The open burst is not lengthened.
    """
    if study_left > study:
        return study
    return study_left


def after_train(study_left: int, trained: bool, *, waiting: bool = False) -> int:
    """One real training step shortens the study gap. Waiting on Lean keeps it."""
    if study_left <= 0:
        return 0
    if waiting:
        return study_left
    if not trained:
        return 0
    return study_left - 1


def choose_action(
    *,
    untrained: int,
    epoch: int,
    hold: bool,
    lean_backlog: int,
    high_water: int,
    loss_ready: bool,
    burst_left: int,
) -> str:
    """Return train, sample, or wait.

    `sample` is one model equation during an open burst, and only when Lean
    still has room. Otherwise the proved pile is read. A weak try does not
    switch the process into a second pass over the corpus.
    """
    del hold
    if lean_backlog >= high_water:
        return "wait"
    if loss_ready and burst_left > 0:
        return "sample"
    return "train"


def observe(disposition: str, streak: int, limit: int = WEAK_LIMIT) -> tuple:
    """A proved equation clears the streak. Anything else is one more weak try.

    The streak is a count for the page. It does not stop the turn. The share
    of accepted equations in the latest block is what changes the next turn.
    """
    del limit
    if disposition == "proved":
        return 0, False
    return streak + 1, False


def depth_credit(depth: int) -> float:
    """Three bands a full block of 20 accepted equations can tell apart.

    Depth 1 is a bare comparison, and a large numeral stays there. Depth 2 is
    one extra nesting. Depth 3 and above share the top band, because a further
    band would sit inside the margin of a block that already reaches 1.
    """
    if depth <= 1:
        return 0.15
    if depth == 2:
        return 0.60
    return 1.0


def wilson_interval(accepted: float, n: int, z: float = 2.0) -> tuple:
    """Share and the Wilson interval. At 0 and at n the plain margin would be 0."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    phat = accepted / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n)) / denom
    return center, max(0.0, center - half), min(1.0, center + half)


def _judgment(item) -> tuple:
    if isinstance(item, str):
        return item, None
    return item[0], item[1]


def _depth_band(chunk) -> Optional[dict]:
    credits = []
    for item in chunk:
        disposition, depth = _judgment(item)
        if disposition != "proved":
            continue
        if depth is None:
            return None
        credits.append(depth_credit(int(depth)))
    if not credits:
        return None
    center, low, high = wilson_interval(sum(credits), len(credits))
    return {"p": center, "low": low, "high": high, "n": len(credits)}


def _reward_level(block: dict) -> int:
    """Step for one finished block. Earlier blocks are not remembered."""
    if block["low"] <= STRONG_LOW:
        return 0
    level = 2 if block["low"] > EXCELLENT_LOW else 1
    deep = block["depth_low"] is not None and block["depth_low"] > EXCELLENT_LOW
    if deep and level < len(FREEDOM) - 1:
        level += 1
    return level


def freedom_plan(dispositions) -> dict:
    """Budget taken from the latest block of 20 judged equations.

    A string entry is a disposition with no depth. A pair is
    `(disposition, depth)`. No finished block stays on the baseline. The
    latest block's lower Wilson bound decides: at or below one half is the
    baseline, above one half is the wider turn, above three quarters is the
    widest. A deep block can add one step only while the share is already
    above one half. The next block replaces this choice. It does not add to it.
    """
    judged = [item for item in dispositions if _judgment(item)[0] != "queued"]
    blocks = []
    complete = len(judged) // BLOCK_SIZE
    for index in range(complete):
        chunk = judged[index * BLOCK_SIZE : (index + 1) * BLOCK_SIZE]
        accepted = sum(1 for item in chunk if _judgment(item)[0] == "proved")
        center, low, high = wilson_interval(accepted, BLOCK_SIZE)
        depth = _depth_band(chunk)
        blocks.append(
            {
                "n": (index + 1) * BLOCK_SIZE,
                "accepted": accepted,
                "p": center,
                "low": low,
                "high": high,
                "depth_p": None if depth is None else depth["p"],
                "depth_low": None if depth is None else depth["low"],
                "depth_high": None if depth is None else depth["high"],
                "depth_n": 0 if depth is None else depth["n"],
            }
        )
    level = _reward_level(blocks[-1]) if blocks else 0
    burst, study, weak = FREEDOM[level]
    remainder = len(judged) % BLOCK_SIZE
    return {
        "level": level,
        "burst": burst,
        "study": study,
        "weak": weak,
        "judged": len(judged),
        "next_in": BLOCK_SIZE - remainder if remainder else BLOCK_SIZE,
        "blocks": blocks,
    }
