"""Stable records and dependency history."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from theorem_gen.errors import RegistryError


def stable_identifier(prefix: str, payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class Record:
    identifier: str
    kind: str
    dependencies: tuple
    rules: tuple
    discovered: bool


class Registry:
    def __init__(self) -> None:
        self._items = {}
        self.history = []

    def add(
        self,
        identifier: str,
        *,
        kind: str,
        dependencies: tuple = (),
        rules: tuple = (),
        discovered: bool = True,
    ) -> Record:
        self.extend(
            (
                {
                    "identifier": identifier,
                    "kind": kind,
                    "dependencies": tuple(dependencies),
                    "rules": tuple(rules),
                    "discovered": discovered,
                },
            )
        )
        return self._items[identifier]

    def extend(self, records) -> None:
        pending = [dict(record) for record in records]
        for record in pending:
            record["dependencies"] = tuple(record.get("dependencies", ()))
            record["rules"] = tuple(record.get("rules", ()))
            record["discovered"] = record.get("discovered", True)
        known = set(self._items)
        proposed = {record["identifier"] for record in pending}
        if len(proposed) != len(pending) or proposed & known:
            raise RegistryError("identifier is already registered")
        for record in pending:
            missing = [
                item
                for item in record["dependencies"]
                if item not in known and item not in proposed
            ]
            if missing:
                raise RegistryError("missing dependencies: " + ", ".join(missing))
        graph = {identifier: set(record.dependencies) for identifier, record in self._items.items()}
        for record in pending:
            graph[record["identifier"]] = set(record["dependencies"])
        cycles = find_cycles(graph)
        if cycles:
            rendered = " -> ".join(cycles[0])
            raise RegistryError(f"cycle: {rendered}")
        for record in _topological(pending, known):
            self._commit(record)

    def _commit(self, record: dict) -> None:
        stored = Record(
            identifier=record["identifier"],
            kind=record["kind"],
            dependencies=tuple(record["dependencies"]),
            rules=tuple(record["rules"]),
            discovered=bool(record["discovered"]),
        )
        self._items[stored.identifier] = stored
        self.history.append(
            {
                "identifier": stored.identifier,
                "kind": stored.kind,
                "dependencies": stored.dependencies,
                "rules": stored.rules,
                "discovered": stored.discovered,
            }
        )

    def get(self, identifier: str) -> Record:
        try:
            return self._items[identifier]
        except KeyError as exc:
            raise RegistryError(f"missing identifier: {identifier}") from exc

    def dependencies(self, identifier: str) -> tuple:
        return self.get(identifier).dependencies

    def dependency_graph(self) -> dict:
        return {identifier: record.dependencies for identifier, record in self._items.items()}

    def cycles(self) -> tuple:
        return find_cycles(
            {identifier: set(record.dependencies) for identifier, record in self._items.items()}
        )

    @classmethod
    def replay(cls, history) -> "Registry":
        registry = cls()
        for event in history:
            registry.add(
                event["identifier"],
                kind=event["kind"],
                dependencies=event["dependencies"],
                rules=event["rules"],
                discovered=event["discovered"],
            )
        return registry


def find_cycles(graph: dict) -> tuple:
    color = {}
    cycles = []

    def visit(node, stack):
        color[node] = "gray"
        stack.append(node)
        for nxt in graph.get(node, ()):
            if nxt not in graph:
                continue
            if color.get(nxt) == "gray":
                start = stack.index(nxt)
                cycles.append(tuple(stack[start:] + [nxt]))
            elif color.get(nxt) != "black":
                visit(nxt, stack)
        stack.pop()
        color[node] = "black"

    for node in graph:
        if node not in color:
            visit(node, [])
    return tuple(cycles)


def _topological(records, already_known: set) -> list:
    pending = {record["identifier"]: record for record in records}
    done = set(already_known)
    ordered = []
    while pending:
        ready = [
            record
            for record in pending.values()
            if set(record["dependencies"]) <= done
        ]
        if not ready:
            raise RegistryError("cycle")
        ready.sort(key=lambda record: record["identifier"])
        chosen = ready[0]
        ordered.append(chosen)
        done.add(chosen["identifier"])
        del pending[chosen["identifier"]]
    return ordered
