# Stage 6: definitions

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`Definition` has an identifier, a name, parameters, a body, and a result type. `validate_definition` checks that the parameters are variables, the names do not repeat, the body type matches the declaration, there are no free variables outside the parameters, and the body does not call the definition itself.

The supported example:

```lean
def double (n : Nat) : Nat := (n + n)

theorem gen_double_zero : ((double 0) = 0) := rfl
```

The theorem depends on `def_double`, has the rule `use_definition`, and `discovered=False`. Lean accepts this file.

Rejected: a free variable, a `Nat` body under an `Int` declaration, and `Const("double", …)` in the body of `double`.

## 2. Tests

- `tests/test_stage6.py`: validation, export, registry
- Lean: `test_definition_and_dependent_theorem` gives `proved`

## 3. Commands and results

The shared run is in [stage-8.md](stage-8.md).

## 4. Limits

The fragment does not cover recursion, propositional definitions, or definitions that depend on other definitions beyond the one `double` example. The exporter does not repair an invalid definition.

## 5. Criteria

The stage 6 criterion is met: the definition is checked, a theorem uses it, the dependency is recorded, and Lean accepts the file.

## 6. Next step

Stage 7 assesses hypotheses separately from generating a proof.
