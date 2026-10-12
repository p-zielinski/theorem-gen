# Stage 2 — variables and general theorems

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`generate_general` distinguishes four kinds of result:

| Kind | Example | Proof in the export |
|------|---------|---------------------|
| `concrete` | stays in `generate` | `rfl` or `decide` |
| `universal` | `∀ a, a + 0 = a` | a lemma application, for example `Nat.add_zero a` |
| `conditional` | `a = b → a + 0 = b` | `rw` and `exact h` |
| `expression` | `∀ a, a + a = a` | none; the file has only `#check` |

A generated sentence has status `unverified`. `claimed_true` is true only when a proof exists and Lean has marked the metadata copy `proved`. An expression with no proof does not get `proved`, even when the surrounding file compiles.

General rules: `add_zero_all`, `zero_add_all`, `add_comm_all`, `mul_comm_all`, `mul_one_all`, `one_mul_all`, `le_refl_all`, `eq_implies_add_zero`, `open_double_eq`.

`generate` rejects a general rule name. The default concrete generator and `lean/TheoremGen/Generated.lean` stay unchanged.

When `GeneratorConfig.rules` is `None`, `generate` uses the stage 1 rules and `generate_general` uses the general rules. A general export header must be built with `config_for_export`, or the comment would print the concrete rule list.

## 2. Tests

- `tests/test_stage2.py`: exact universal, commutative, and conditional export; an expression with no `:=` and no `sorry`; the rule header; seed repeatability; uniqueness exhaustion; the concrete generator rejecting a general rule
- `tests/test_lean_integration.py`: Lean accepts every general schema that has a proof (`add_zero_all`, `zero_add_all`, `add_comm_all`, `mul_comm_all`, `mul_one_all`, `one_mul_all`, `le_refl_all`, `eq_implies_add_zero`). An expression with no proof stays `unverified`, even when the rest of the file passes.

## 3. Commands and results

The same commands as in [stage-8.md](stage-8.md). For this stage the deciding test is `test_universal_conditional_and_unproved_expression`: the file status is `proved`, and the expression with no proof is not marked true.

## 4. Limits

Each general rule has one schema. This is not a search over arbitrary formulas. `open_double_eq` is false, but the generator does not refute it; refutation belongs to stage 7.

## 5. Criteria

The stage 2 criterion is met: the system distinguishes a concrete sentence, a sentence for all, a sentence with an assumption, and an expression with no proof, and it does not treat any of them as true merely because it generated it.

## 6. Next step

Stage 3 extends the AST with `Int`, `succ`, and rejection of combinations that would change the meaning.
