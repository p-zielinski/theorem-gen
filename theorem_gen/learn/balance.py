"""Which queue may run. A low-loss burst may write, then study takes over."""

from __future__ import annotations

WEAK_LIMIT = 8
LOSS_LIMIT = 0.45
LOSS_STREAK = 10
SAMPLE_BURST = 10
STUDY_STEPS = 200


def loss_is_ready(losses) -> bool:
    """True when the last 10 training losses are all under 0.45."""
    recent = list(losses)[-LOSS_STREAK:]
    if len(recent) < LOSS_STREAK:
        return False
    return all(loss < LOSS_LIMIT for loss in recent)


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
) -> tuple:
    """Short label and one sentence for the current writing state."""
    if hold:
        return (
            "No",
            f"{WEAK_LIMIT} weak tries in a row. It reads proved sentences again before it may write.",
        )
    if burst_left > 0 and model_backlog >= high_water:
        return (
            "Waiting",
            "It may write, but its Lean lane is full"
            f" ({model_backlog} unfinished). This turn of {burst_left} equations waits and is not spent.",
        )
    if burst_left > 0:
        return (
            "Yes",
            f"Loss stayed under {LOSS_LIMIT} for {LOSS_STREAK} updates."
            f" {burst_left} of {SAMPLE_BURST} equations are still to add."
            f" Then it studies for {STUDY_STEPS} steps.",
        )
    if study_left > 0:
        return (
            "Studying",
            f"{study_left} study steps left after its last equations."
            f" Another turn starts only after {LOSS_STREAK} updates under {LOSS_LIMIT}.",
        )
    if last_loss is not None and streak == 0:
        shown = f"{float(last_loss):.3f}"
        return (
            f"0/{LOSS_STREAK}",
            f"The last update was {shown}, above {LOSS_LIMIT}."
            f" It needs {LOSS_STREAK} updates in a row under {LOSS_LIMIT},"
            f" then {SAMPLE_BURST} equations and {STUDY_STEPS} study steps.",
        )
    return (
        f"{streak}/{LOSS_STREAK}",
        f"{streak} updates in a row are under {LOSS_LIMIT}."
        f" At {LOSS_STREAK} it adds {SAMPLE_BURST} equations, then studies for {STUDY_STEPS} steps.",
    )


def remember_loss(losses, loss: float) -> list:
    recent = list(losses)
    recent.append(float(loss))
    return recent[-LOSS_STREAK:]


def open_burst(burst_left: int, study_left: int, ready: bool) -> tuple:
    """Start a batch of 10 only when loss is ready and the last batch is finished."""
    if burst_left > 0 or study_left > 0 or not ready:
        return burst_left, study_left
    return SAMPLE_BURST, study_left


def after_sample(burst_left: int, study_left: int, disposition: str) -> tuple:
    """A queued equation spends one of the 10. Then study resumes for 200 steps."""
    if disposition != "queued" or burst_left <= 0:
        return burst_left, study_left
    burst_left -= 1
    if burst_left == 0:
        study_left = STUDY_STEPS
    return burst_left, study_left


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
    """Return train, rehearse, sample, or wait.

    `sample` is one model equation during an open burst, and only when Lean
    still has room. A weak window rehearses. Otherwise the proved pile is read.
    """
    if hold:
        return "rehearse"
    if lean_backlog >= high_water:
        return "wait"
    if loss_ready and burst_left > 0:
        return "sample"
    return "train"


def observe(disposition: str, streak: int) -> tuple:
    """A proved equation clears the streak. Anything else counts toward the brake."""
    if disposition == "proved":
        return 0, False
    streak += 1
    return streak, streak >= WEAK_LIMIT
