# Stage 4: registry and dependencies

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

`Registry` holds records with an identifier, a kind, dependencies, rules, and a `discovered` flag. `extend` rejects:

- a repeated identifier
- a dependency outside the registry and outside the same transaction (`missing dependencies: …`)
- a cycle, including a self-loop (`cycle: …`)

`dependency_graph` and `Registry.replay(history)` rebuild the same graph. `stable_identifier` is a prefix and 16 characters of SHA-256 of the canonical JSON; dictionary key order does not change the result.

Using an earlier result is not discovering it again. The theorem about `double` has `discovered=False` and the rule `use_definition`. The definition has `discovered=True` and the rule `define`.

## 2. Tests

`tests/test_stage4.py`: citation, a missing dependency, a self-cycle and a mutual cycle, replay, a duplicate, a stable identifier.

## 3. Commands and results

The shared run is in [stage-8.md](stage-8.md).

## 4. Limits

The registry is in process memory. The history is a list of dictionaries, not a file. There is no durable theorem database between CLI runs.

## 5. Criteria

The stage 4 criterion is met: identifiers are stable, a missing dependency and a cycle are visible, the graph can be rebuilt, and a citation is not counted as a discovery.

## 6. Next step

Stage 5 measures the complexity of the tree independently of the size of a numeral.
