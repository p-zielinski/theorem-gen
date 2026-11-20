# Prompt: a continuously developed AI on top of the Lean 4 generator

Copy the whole block below (from `You are a senior engineer…` through the end of the block) as the full implementation instruction. This prompt does not promise that the model will "solve all of mathematics". It builds a system that can learn for a long time, with pause and resume, Lean as the arbiter, and SQLite as the memory.

Note for Markdown authors: the block is in a `text` fence of four backticks, so inner command examples do not cut copy-paste.

````text
You are a senior engineer in Python + Lean 4 + ML systems.
Extend the existing project in the current repository directory (the root with docs/,
theorem_gen/, tests/, lean/). Do not assume an absolute user path.

Long-term goal: an AI model that keeps learning on the loop
generation → Lean 4 validation → result classification → SQLite storage,
and that can be stopped and resumed at any moment.
The aspiration, after a very long training: steadily better solving of
mathematical tasks and hypotheses. Do NOT claim the system already can.
Do not promise full automation or that it "will solve every hypothesis".

## Existing code to keep

- Treat stages 0-8 as the base ONLY after a green audit with lake
  (not incomplete_without_lean). Otherwise fix the base first
  or run docs/prompts/audit-lean-generator.md.
- Python builds a typed AST; Lean 4.34.1 checks proofs (no Mathlib).
- The default generate() CLI still produces concrete Nat.
- Present: generate, generate_general, registry, complexity, definitions,
  assess_hypothesis, explore, verify_source.
- Existing tests (unittest, 134) must stay green.
- Prefer a typed AST + the existing exporter over arbitrary Lean text from a model.
- TDD, small phases, documentation that matches the code that exists.
- Do not ask the user; when in doubt pick the recommended option in this prompt.
- Keep the handoff in .cursor/work/continuous-lean-ai.md.

## Critique of "3 personas = no hallucinations" (required)

Three roles that agree do NOT eliminate hallucinations.
They can share weights, biases, a prompt, or copy one another's mistake.
Role agreement is a priority / working-quality signal, NEVER a formal status.
Only Lean may assign proved or refuted.
The analogy "a mirror / a recording of oneself" is good as an independent critique of artifacts,
but not as mathematical validation.

## Canonical statuses (SQLite + API)

Every candidate ends in exactly one status derived from evidence:

1. proved: Lean accepted a complete proof (no sorry).
2. refuted: Lean accepted a proof that the instantiated sentence is false
   (a counterexample certificate), not a Python heuristic by itself.
3. unresolved: no accepted proof and no certified counterexample;
   includes timeout, a failed search, no witness inside the bound, role agreement without Lean.
4. ill_formed: an AST/type error or Lean syntax/typing.
   Mapping from the existing assess_hypothesis:
   invalid_syntax | invalid_type → ill_formed;
   proved | refuted | unresolved keep their meaning.
   The continuous-AI SQLite/API does NOT introduce parallel synonyms for statuses.

Rules:
- Lack of a proof ≠ falsehood.
- A compile error ≠ a counterexample.
- The model/roles NEVER write proved/refuted directly.
- Python find_counterexample may propose a witness; refuted only after a Lean certificate.
- Reject: sorry, axiom, opaque, unsafe, #eval, run_io, run_cmd, unapproved imports.

## Phase 0: architecture before code

Before you write an implementation, record:
- docs/continuous-ai-architecture.md
- a draft DDL / migrations in docs (schema design); migration files + applying them = Phase 1 under TDD
- a loop diagram: propose → prove/critique → validate → classify → store → schedule
- a curriculum and promotion-gate plan
- a memory plan for a Mac with 24 GB RAM

Only then TDD and code.

## Phase 1: SQLite immediately (a minimal schema, not an archive)

Use SQLite with WAL, foreign keys, busy_timeout, transactions, migrations,
idempotency keys, and crash-safe commits.

Tables (minimum):
- schema_migrations
- runs: status, seed, config JSON, curriculum_level, model_version, created/updated
- candidates: stable_id, canonical AST JSON, structural_hash, kind
  (hypothesis|theorem|definition|expression), provenance, current_status, timestamps
- attempts: candidate_id, role, model_version, prompt_hash, raw_response,
  proof_artifact / critique_artifact, timings; IMMUTABLE
- validations: candidate_id, attempt_id, lean_version, toolchain_hash,
  validation_type (proof|counterexample|check), result, bounded stdout/stderr; IMMUTABLE
- counterexamples: candidate_id, assignment JSON, instantiated_prop, lean_certificate_id
- dependencies: from_id, to_id, relation (cites|uses_definition|generalizes|…)
- queue_jobs: type, priority, state, lease_owner, lease_expiry, retry_count, idempotency_key
- events: append-only state transitions
- curriculum_progress: level, windows, metrics, gate_status
- model_versions: path/hash, adapter_hash, eval_scores, champion/challenger/retired
- checkpoints: run_id, seq, event_cursor, scheduler_state, rng_state,
  curriculum_state, artifact hashes

A candidate's outcome is DERIVED from accepted validations, not from the model's opinion.

## Phase 2: pause / resume / checkpoint

- Checkpoint every 300 s by default; configurable only in the range 300-600 s.
- Also checkpoint on: pause, SIGINT/SIGTERM, curriculum promotion, model promotion.
- Pause: stop new dequeues, finish or release leases, commit, atomically publish the checkpoint, exit.
- Resume: integrity check, restore RNG/scheduler, reclaim expired leases, zero duplicate attempts.
- The snapshot must allow replay of a run from recorded raw_response without calling the model again.
- Keep the latest known-good checkpoint.

Trackers: run status, curriculum level, event cursor, queue depths, model version.
CLI minimum: start | pause | resume | status | replay.

## Phase 3: queues and workers (so the model is not idle)

Bounded queues:
- propose
- prove_primary
- prove_alternate_or_critique
- counterexample_search
- lean_validate

Requirements:
- backpressure at a high-water mark
- priority for jobs that unblock downstream work
- leases + heartbeats
- ONE loaded model server; roles multiplexed by request (not 3 full copies in RAM)
- start: 1 inference worker + 1-2 Lean workers; scale after measurement
- measure utilization and latency, but do not trade correctness for busyness

## Phase 4: curriculum: difficulty grows very slowly

Start from the existing concrete Nat generator (stage 1).
Extend the capabilities of stages 2→6 ONE level at a time.
Do not skip stages.

Level promotion gate (all conditions):
- ≥ 1000 candidates newly evaluated by Lean at the level
- 3 successive evaluation windows meet the thresholds
- zero correctness violations (false proved/refuted)
- stable diversity (structural novelty, diversity metrics)
- no regression on the held-out benchmark
- at most one promotion per finished checkpoint window

Complexity: use the existing measures (ast_size, depth, variables, operators,
dependencies, definitions). The size of a numeral is NOT difficulty.

After the stage 6 generator gate, introduce three isolated roles
as a stage 7 helper (hypotheses), not earlier:

1. theorem_proposer
   - emits a typed candidate (AST contract) + a short rationale
   - does NOT assign a verdict
   - "no context" mode: no history of other agents; only the AST contract,
     seed/randomness, optionally a small retrieval from SQLite by structural_hash / family
     (retrieval ≠ a shared chat scratchpad)

2. prover
   - an independent proof attempt; does not see the proposer's working notes beyond the candidate

3. alternate_prover_critic
   - first an independent proof attempt WITHOUT a view of the primary proof
   - then a critique of both artifacts (differences, gaps, an alternative)

Roles exchange only immutable artifacts through SQLite.
A "working solution" is stored for later training / retrieval ONLY when:
- Lean accepted a proof OR a certified counterexample, AND
- (optionally) the two prover paths are not contradictory about the same artifact.
Role agreement without Lean is NEVER enough.

A failed gate freezes advancement; it does not rewrite accepted evidence.

## Phase 5: model strategy on a Mac with 24 GB RAM

Default recommendation:
- one local 7B-8B instruct/code model, 4-bit quantization (MLX or llama.cpp)
- context 8K-16K
- peak process memory < ~18 GB (leave headroom for Lean and macOS)
- do NOT keep three resident copies of the model
- 14B 4-bit only as an optional benchmark after measuring latency/RAM

First teach the system through:
- a data flywheel (SQLite memory)
- retrieval of earlier proved/refuted
- ranking of templates / tactics / generator rules
- a contextual bandit / policy scheduling

LoRA / fine-tune ONLY later, offline between runs:
- train ONLY on Lean-validated proved/refuted
- NEVER on unresolved, ill_formed, role agreement alone, or uncertified witnesses
- challenger vs champion on held-out; rollback on regression
- every version: hash, eval scores, the ability to retire

## Phase 6: protection against self-training collapse

- An immutable seed corpus + a held-out benchmark (never in train).
- Dedup by structural_hash between train and eval.
- Balance family / outcome / difficulty.
- Cap descendants synthesized from one ancestor.
- Detect triviality gaming: novelty, AST complexity, dependency depth, proof diversity.
- Quarantine if the same candidate looks proved and refuted at once → a system defect.
- Promote a model/policy only when it improves correctness, solve rate, calibration, diversity, resource use.

## Phase 7: Lean validation

- Pin and store the toolchain (lean/lean-toolchain, hash).
- Validate candidates separately (one bad file does not spoil the batch).
- A counterexample = Lean accepts a theorem of the negation of the instantiated proposition.
- Limits: wall-clock, CPU, process-group kill, output truncate, controlled imports, temp files.
- reuse theorem_gen.verify where possible; do not build a second ad-hoc runner without a need.

## Phase 8: CLI and DX

Commands (repo root):

    python3 -m theorem_gen.learn start --run-id ... --curriculum ...
    python3 -m theorem_gen.learn pause --run-id ...
    python3 -m theorem_gen.learn resume --run-id ...
    python3 -m theorem_gen.learn status --run-id ...
    python3 -m theorem_gen.learn replay --run-id ... --from-checkpoint ...

The existing `python3 -m theorem_gen generate` must keep working with no regression.

## Acceptance tests (must pass, or have a measurable protocol)

1. The existing unittest suite stays green.
2. Migrations, FK, transactions, idempotency.
3. Three agreeing roles CANNOT mark a Lean-rejected file as proved.
4. A Python witness with no Lean certificate → unresolved.
5. A Lean-certified witness → refuted with reproducible evidence.
6. syntax/typing → ill_formed; timeout → unresolved.
7. Kill at ≥3 defined points (between dequeue→lease, after Lean validate
   before commit, during the checkpoint write) + resume → zero lost/duplicate attempts
   (checked by idempotency_key).
8. Pause → a valid checkpoint; resume restores the scheduler/RNG.
9. Expired leases are reclaimed; backpressure bounds the queues.
10. Under a synthetic load with eligible work: inference/Lean utilization above a threshold
    (for example ≥80% busy when the queue > 0): not "zero idle forever".
11. Curriculum does not advance early or from training metrics alone.
12. A failed challenger → rollback of the champion.
13. Replay from recorded outputs with no inference reproduces the outcomes.
14. Peak RSS of the inference process + workers + Lean inside the budget (~18 GB headroom on a 24 GB Mac),
    measured by a script/report in docs.
15. Forbidden Lean constructs rejected despite role agreement.
16. A phase report of commands actually run and their results.

## Delivery order

1. Architecture + schema draft + handoff
2. SQLite store + migrations + tests
3. Queue + pause/resume/checkpoint + tests
4. Lean validation adapter + classify + tests
5. Curriculum level 1 wired to the existing generate()
6. Slow gates through stage 6 capabilities
7. Three roles as a helper for stage 7
8. Retrieval / ranking / optional offline LoRA later
9. Docs: architecture, stage notes, measured commands

## Definition of "learning"

You may write that the system is learning ONLY when there is a persisted, evaluated
policy or model_version that beats a fixed baseline on held-out.
Storing a growing number of records in SQLite is experiment memory, not yet "the model learning".

## Out of scope at the start

- Mathlib
- three full models in RAM at once
- online fine-tune during serving
- a promise to solve an arbitrary hypothesis
- quietly rewriting the stage 0-8 generator

Start from the architecture and red SQLite/pause tests. Do not finish a phase without green tests and a command report.
````

## How to use

1. First (optionally) run the audit prompt from `docs/prompts/audit-lean-generator.md`, so the base is known.
2. Paste the whole `text` block above into a new chat with access to the repository and tools.
3. Keep the handoff in `.cursor/work/continuous-lean-ai.md`.
4. Ship curriculum and LoRA only after the gates are green: do not jump to "three personas" before stage 6.

## Recommended defaults (when an agent is unsure)

| Question | Choice |
|----------|--------|
| How many models in RAM? | 1 × 7-8B 4-bit |
| Checkpoint interval | 300 s |
| When do the 3 roles start? | After the curriculum gate that corresponds to stage 6 |
| When LoRA? | Offline, after a Lean-validated corpus and held-out |
| What counts as truth? | Only a Lean certificate |
| Proposer "with no context"? | No shared chat; a small SQLite retrieval is allowed |
