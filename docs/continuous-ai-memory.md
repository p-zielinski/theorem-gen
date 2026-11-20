# Process memory

> Measured: 2026-10-12, branch `main`, loop audit.
> Command: `python3 -m theorem_gen.learn memory`

```
peak_rss_bytes: 16646144
budget_bytes: 19327352832
within_budget: yes
weights_loaded: no
resident_copies: 0
Measured the Python control plane only. No 7B-8B weights were resident. The budget is 18 GB so Lean and macOS keep headroom on a 24 GB machine.
```

Exit code: 0.

16646144 bytes is the peak RSS of this Python process (on macOS `ru_maxrss` is in bytes). The budget of 19327352832 bytes is 18 GiB. The machine assumed in the plan has 24 GB. The measurement did not load a model.

7B-8B weights were not loaded. `resident_copies` is the number of copies in `ModelSlot`, not the number of Lean processes. Three resident copies of a model never appeared, because the slot refuses a second one.

This report is a measurement from before the 50M transformer. It does not describe the RSS of a process that holds that network and the Lean workers at the same time. The role backend can still be `RaiseBackend`. The transformer weights are a separate file, `var/lm/<run-id>/model.safetensors`.
