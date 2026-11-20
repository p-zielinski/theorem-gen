# Stage 7: hypotheses

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`assess_hypothesis` returns one of these statuses:

| Status | When |
|--------|------|
| `proved` | a proof was supplied and the Lean verification has status `proved` |
| `refuted` | a finite search found a counterexample |
| `unresolved` | there is no counterexample and no accepted proof |
| `invalid_syntax` | a syntax error in the source |
| `invalid_type` | the sentence is not a well-typed `Prop`, or Lean reported a type error |

The counterexample is checked before a declared proof. A false `1 = 0` with a forged `proved` status stays `refuted`.

The search substitutes `Nat` from 0 through `search_bound` inclusive. `∀ a, a < a` gives the witness `a = 0`. `∀ a, a + a = a` at bound 0 stays `unresolved`, because `0 + 0 = 0` is not a counterexample; at bound 1 the witness is `a = 1`. No witness is not a proof of truth. A failed proof of a source with no tree is not falsehood either: the message says outright that a proof failure does not establish falsehood.

Closed `Int` comparisons are evaluated directly. `(1 + -1) = 1` is refuted, and `(1 + -1) = 0` with no proof stays `unresolved`.

`limit_repetition` folds sentences with the same structural key. `diversity_metrics` reports the count, the unique count, the ratio, and the shape entropy by root class. An empty set has ratio 1 and entropy 0.

Lean for `theorem witness : (0 < 0) := by decide` returns `failed` / `proof`, because the tactic showed the sentence is false (`proved that the proposition`).

## 2. Tests

`tests/test_stage7.py`, plus `test_concrete_false_comparison_is_a_proof_failure` and an addition in `tests/test_verify.py` for the `decide` message.

## 3. Commands and results

The shared run is in [stage-8.md](stage-8.md). The real Lean message for `0 < 0`:

```text
error: Tactic `decide` proved that the proposition
  0 < 0
is false
```

The classifier assigns it to `proof`, not to `other`.

## 4. Limits

The quantifier search covers only `Nat` binders. A sentence that cannot be evaluated after substitution is not refuted; the search ends with no witness. This is not a decision procedure for arbitrary arithmetic. Shape entropy groups by root class, so two different `Compare` comparisons have the same shape; repeats are caught separately by the structural key.

## 5. Criteria

The stage 7 criterion is met: a hypothesis can be proved, refuted, left unresolved, or rejected as bad syntax or a bad type. Lack of a proof is not falsehood. There is a measurement of repeats and diversity.

## 6. Next step

Stage 8 mixes these verdicts in one exploration and leaves sentences unresolved.
