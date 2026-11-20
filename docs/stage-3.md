# Stage 3: a wider AST

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

The tree gained: `IntLit`, `Var` (`Nat`, `Int`, `Prop`), `UnaryOp` (`succ`, `neg`), `Const`, `Atom`, `Implies`, `Forall`.

Forbidden combinations are not built and are not rewritten into another meaning:

- `Nat + Int` → `TypingError` (`cannot apply add to Nat and Int`)
- `neg` on `Nat` and `succ` on `Int` → a type error
- `pred` → an error, because a truncated predecessor on `Nat` turns 0 into 0
- a `Nat` constant applied to `Int`, and an atom applied to a sentence → a type error
- a free variable and a duplicated binder in `Forall` → an error

Export keeps the shape: `(Nat.succ 2)`, `((1 : Int) + (-1 : Int))`, `(-(1 : Int))`, `(P a)`. The stage 1 concrete generator does not draw these constructions. Lean rejects an atom with no declaration; a file that is only `#check` does not become a proof.

## 2. Tests

- `tests/test_stage3.py`: `succ` evaluation, export of `succ`, `neg`, and an atom, rejection of bad types, `pred`, binders, an implication with `Nat` instead of `Prop`
- Lean: `(Nat.succ 2) = 3`, `((1 : Int) + (-1 : Int)) = (0 : Int)`, and `(-(1 : Int)) = (-1 : Int)` end with status `proved`. `#check` of an undeclared atom `P` ends in an error.

## 3. Commands and results

The shared run is in [stage-8.md](stage-8.md). `test_succ_and_int_decide` passes on Lean 4.34.1.

## 4. Limits

There is no subtraction, division, or general theorems about `Int` in the generator. `Int` appears in hand-built trees and in the export. `Atom` has no interpretation in Lean; it is not sent as a theorem.

## 5. Criteria

The stage 3 criterion is met: the new constructions have typing, export, and Lean tests, and a bad combination of types ends in an exception.

## 6. Next step

Stage 4 records stable identifiers and dependencies.
