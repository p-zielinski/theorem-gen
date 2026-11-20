# Stage 5: complexity

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`measure_expr` and `measure_theorem` count:

- `ast_size`
- `depth`
- `variables`
- `operators`
- `dependencies`
- `definitions`

`NatLit(1)` and `NatLit(10**12)` have the same size and the same depth. The size of a numeral is not a measure. A sentence with a quantifier is larger than a big numeral by itself.

`GeneratorConfig.complexity_bounds` filters candidates of `generate` and `generate_general`. A pair `(low, high)` with `low > high` is rejected when the configuration is created. A bound that no candidate meets ends in `GenerationError` and text that this is a generation limit, not a mathematical verdict.

The generator hits each of the six measures:

- `ast_size` 5-5 and `variables` 0-0 for `add_zero` leaves `((8 + 0) = 8)`
- `depth` 2-2 and `operators` 1-1 also leave that sentence; `operators` 0-0 chooses `(8 <= 8)`
- `variables` 1-1 chooses `add_zero_all`, and 2-2 chooses `add_comm_all`
- `dependencies` 1-1 and `definitions` 1-1 with the rule `use_definition` choose the theorem about `double`; the citation has `discovered=False`

When every `add_zero` candidate fits `ast_size` 5-5 and `variables` 0-0, seed 1 still gives `((8 + 0) = 8)` and `((7 + 0) = 7)`. The concrete header stays with the stage 1 banner and adds a `complexity` line.

The definition count with no registry counts `Const` nodes. With a registry it counts dependencies whose record has kind `definition`.

## 2. Tests

`tests/test_stage5.py`: numeral size, hitting bounds, an impossible bound, a variable bound, a reversed pair, a definition dependency.

## 3. Commands and results

The shared run is in [stage-8.md](stage-8.md).

## 4. Limits

The bound filter works in `generate` and `generate_general`. `explore` has four fixed templates and does not read these bounds. The measures are structural: they do not grade how hard a proof is in Lean. The rule `use_definition` is not in the default stage 1 set.

## 5. Criteria

The stage 5 criterion is met: generation can stay inside a requested range of several measures, and a large number is not automatically harder.

## 6. Next step

Stage 6 adds a definition and a theorem that uses it.
