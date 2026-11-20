# Stage 8: open exploration

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`explore(seed, count)` draws four templates without replacement, and after the pool is exhausted it starts again. The same seed gives the same list.

| Template | Status | Meaning |
|----------|--------|---------|
| `proved_add_zero` | `proved` | a citation of the registered `Nat.add_zero`; `discovered=False` |
| `refuted_lt` | `refuted` | `∀ a, a < a`, witness `a = 0` |
| `bounded_le` | `no_proof` | `∀ a b, a ≤ a + b` fits a small search and has no proof here |
| `atom_p` | `unprovable_in_fragment` | the atom `P` has no rule in this fragment |

`no_proof` is not a refutation. `unprovable_in_fragment` speaks only about the registered fragment, not about unprovability in mathematics.

Export of a citation leaves the theorem `unverified` until Lean checks it. `theorem_from_proved` prints `:= Nat.add_zero a`. Lean accepts that file.

Seed 1 and count 4 give, in this order: `proved`, `refuted`, `no_proof`, `unprovable_in_fragment`. Other seeds change the order. The set of four statuses at `count=4` is complete.

## 2. Tests

- `tests/test_stage8.py`: four statuses, separation of a witness, no proof, and the fragment, the citation registry, export still `unverified`, empty and negative `count`
- Lean: `test_cited_exploration_theorem_is_accepted`

## 3. Commands actually run

From the repository root, after stages 2-8:

```sh
python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
python3 -m compileall -q theorem_gen tests
git diff --check
```

`lake build` ran inside the test `test_package_build_accepts_the_generated_module` in the same suite. The local elan sets `ELAN_HOME` to `.toolchains/elan`.

## 4. Results

```text
Ran 134 tests
OK

generated 8 theorems
wrote lean/TheoremGen/Generated.lean
verification: proved
Lean accepted the file with exit code 0.
```

`compileall` and `git diff --check` exit 0. The stage 1 example stays in agreement with the generator.

Separately, `explore(1, 4)`:

```text
explore_0000 proved witness=() deps=('lemma_Nat_add_zero',)
explore_0001 refuted witness=(('a', 0),) deps=()
explore_0002 no_proof witness=() deps=()
explore_0003 unprovable_in_fragment witness=() deps=()
```

## 5. Limits

Exploration has four templates, not an arbitrary space of sentences. The status `proved` in an exploration result means a registered lemma matches; the theorem in the export still waits for Lean. That is not `claimed_true(theorem)`: see also the table in `README.md`. The system does not promise to decide sentences outside these templates. Lack of a proof, falsehood, and unprovability in the fragment remain three different results.

## 6. Criteria

The stage 8 criterion is met. After stages 2-7 the system creates sentences it does not always decide itself, and it does not identify lack of a proof with falsehood, or with unprovability outside the registered fragment.

## 7. Next step

Stages 0-8 are closed. Further work, if any, would be new constructions or a durable registry, not closing this series.
