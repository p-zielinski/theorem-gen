"""RSS of this process. A 7B–8B model is not loaded here."""

from __future__ import annotations

import resource
import sys

RAM_BUDGET_BYTES = 18 * 1024 ** 3
MACHINE_RAM_BYTES = 24 * 1024 ** 3


def peak_rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(rss)
    return int(rss) * 1024


def report(slot=None) -> dict:
    rss = peak_rss_bytes()
    copies = 0 if slot is None else slot.resident_copies
    weights_loaded = bool(slot and slot.loaded and slot.model_version not in {None, "none"})
    return {
        "peak_rss_bytes": rss,
        "budget_bytes": RAM_BUDGET_BYTES,
        "machine_ram_bytes": MACHINE_RAM_BYTES,
        "within_budget": rss < RAM_BUDGET_BYTES,
        "weights_loaded": False if slot is None or slot.model_version in {None, "none"} else weights_loaded,
        "resident_copies": copies,
        "note": (
            "Measured the Python control plane only. "
            "No 7B-8B weights were resident. "
            "The budget is 18 GB so Lean and macOS keep headroom on a 24 GB machine."
        ),
    }
