# Stages and completion criteria

The code implements stages 0–8. The default concrete generator from stage 1 stays as it is.

## Stage 0 — analysis

Status: done. Evidence: [stage-0.md](stage-0.md), [architecture.md](architecture.md).

Done when it is known which tools are available, which part of the system is in Python and which is in Lean, what the directories and the interface look like, and what the criteria of the later stages are.

## Stage 1 — concrete arithmetic

Status: done. Report: [stage-1.md](stage-1.md).

Done when, all at once:

- the same seed and the same configuration produce the same set of theorems
- a caller can ask for a given number of examples, including zero
- with `unique`, one set does not contain two sentences with the same key; when there is no room, the error is explicit
- the export is valid, narrow Lean 4 and does not change the meaning of the tree
- real Lean accepts the generated file
- a compile error, a timeout, and a missing tool are distinguished; a timeout is not a verdict of "false"
- unit, edge, deterministic, property, and Lean integration tests pass
- the stage report lists the commands that were run and their results

## Stage 2 — variables and general theorems

Status: done. Report: [stage-2.md](stage-2.md).

Done when the generator distinguishes a concrete sentence, a sentence for every element of a type, a sentence with assumptions, and an expression with no proof, and treats none of them as true merely because it was generated.

## Stage 3 — a wider AST

Status: done. Report: [stage-3.md](stage-3.md).

Done when every new construction has typing, export, and Lean tests, and a forbidden combination of types ends in an error instead of code with a different meaning.

## Stage 4 — registry and dependencies

Status: done. Report: [stage-4.md](stage-4.md).

Done when results have stable identifiers, a missing dependency and a cycle are visible, and the graph can be rebuilt from the recorded history. Using an earlier theorem is not counted as discovering it again.

## Stage 5 — complexity

Status: done. Report: [stage-5.md](stage-5.md).

Done when generation can hit a requested range of several measures (tree size, depth, number of variables, operators, dependencies, definitions), and the size of a number is not the only measure of difficulty.

## Stage 6 — definitions

Status: done. Report: [stage-6.md](stage-6.md).

Done when the system creates a definition in the supported representation, checks it, builds theorems from it, records the dependencies, and passes Lean.

## Stage 7 — hypotheses

Status: done. Report: [stage-7.md](stage-7.md).

Done when a hypothesis can be proved, refuted by a counterexample, left unresolved, or rejected as bad syntax or a bad type. Lack of a proof is not marked as false. There is a measurement of repetition and diversity.

## Stage 8 — open exploration

Status: done. Report: [stage-8.md](stage-8.md).

The system creates sentences it does not always decide itself. Lack of a proof, falsehood, and unprovability inside the registered fragment stay different results. There is no promise of full automation.
