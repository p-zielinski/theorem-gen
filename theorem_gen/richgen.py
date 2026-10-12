"""Equational Nat generator.

This sits beside `generate()`. It is not wired into the learn queue.
Statements quantify over variables. Proofs are a few rewrites on the left
side, then `ac_rfl`. They are not concrete `:= rfl` calculations.

Run a batch with `python3 -m theorem_gen.richgen --seed 1 --count 4`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from theorem_gen.errors import GenerationError
from theorem_gen.generate import seed_token
from theorem_gen.rng import LCG

_VARS = ("a", "b", "c", "d")
_FAMILIES = ("ac_add", "ac_mul", "ac_mix", "rewrite")
_PREFERENCE = (
    "Nat.add_zero",
    "Nat.zero_add",
    "Nat.mul_one",
    "Nat.one_mul",
    "Nat.add_mul",
    "Nat.mul_add",
)


@dataclass(frozen=True)
class RichTheorem:
    name: str
    source: str
    statement: str
    family: str
    proof_method: str
    depth: int
    size: int
    variables: tuple


def generate_rich(seed: int, count: int) -> tuple:
    """Return `count` deterministic theorems. Every fourth slot repeats the families."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GenerationError("seed must be an int")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise GenerationError("count must be >= 0")
    if count == 0:
        return ()
    return tuple(rich_theorem(seed, index) for index in range(count))


def rich_theorem(seed: int, index: int) -> RichTheorem:
    """One theorem. Index 0 does not replay when a later index is requested."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GenerationError("seed must be an int")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise GenerationError("index must be >= 0")
    family = _FAMILIES[index % len(_FAMILIES)]
    return _one(LCG(_slot_seed(seed, index)), seed, index, family)


def _slot_seed(seed: int, index: int) -> int:
    z = (seed + index * 0x9E3779B9) & 0xFFFFFFFF
    z = ((z ^ (z >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
    z = ((z ^ (z >> 15)) * 0x846CA68B) & 0xFFFFFFFF
    z = (z ^ (z >> 16)) & 0xFFFFFFFF
    return z or 1


def apply_first(expr, lemma: str):
    """Rewrite the leftmost preorder match of `lemma`. The same tree means no match."""
    rewritten = _descend(expr, lemma)
    return expr if rewritten is None else rewritten


def ac_key(expr):
    """Flatten `+` and `*` and sort the pieces. Association and order disappear."""
    if expr[0] in ("v", "n"):
        return expr
    parts = []

    def flatten(node) -> None:
        if node[0] == expr[0]:
            flatten(node[1])
            flatten(node[2])
            return
        parts.append(ac_key(node))

    flatten(expr)
    parts.sort(key=repr)
    return (expr[0], tuple(parts))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="theorem_gen.richgen")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    text = "".join(item.source for item in generate_rich(args.seed, args.count))
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


def _one(rng: LCG, seed: int, index: int, family: str) -> RichTheorem:
    for _ in range(40):
        made = _make(rng, family)
        if made is None:
            continue
        lhs, rhs, lemmas = made
        if _pretty(lhs) == _pretty(rhs):
            continue
        if max(_depth(lhs), _depth(rhs)) < 3:
            continue
        names = tuple(sorted(set(_variables(lhs)) | set(_variables(rhs))))
        if "a" not in names:
            continue
        statement = f"({_pretty(lhs)} = {_pretty(rhs)})"
        source = _source(seed, index, names, statement, lemmas)
        return RichTheorem(
            name=f"rich_s{seed_token(seed)}_{index:04d}",
            source=source,
            statement=statement,
            family=family,
            proof_method="ac_rfl" if not lemmas else "rewrite",
            depth=max(_depth(lhs), _depth(rhs)),
            size=max(_size(lhs), _size(rhs)),
            variables=names,
        )
    raise GenerationError(f"stopped before {family} theorem {index}")


def _make(rng: LCG, family: str):
    if family == "ac_add":
        return _ac_pair(rng, "+")
    if family == "ac_mul":
        return _ac_pair(rng, "*")
    if family == "ac_mix":
        return _ac_mix(rng)
    return _rewrite_family(rng)


def _ac_pair(rng: LCG, op: str):
    leaves = _leaves(rng, rng.randint(4, 6))
    leaves.append(("n", rng.randint(2, 9)))
    turned = leaves[1:] + leaves[:1]
    return _assoc(op, leaves), _assoc_right(op, turned), ()


def _ac_mix(rng: LCG):
    factors = [_assoc("*", _leaves(rng, 2)) for _ in range(3)]
    return _assoc("+", factors), _assoc_right("+", list(reversed(factors))), ()


def _rewrite_family(rng: LCG):
    left = _assoc("+", _leaves(rng, rng.randint(2, 3)))
    right = _assoc("+", _leaves(rng, rng.randint(2, 3)))
    expr = ("*", left, right)
    plant = rng.randint(0, 3)
    if plant == 1:
        expr = _plant(expr, lambda atom: ("+", atom, ("n", 0)))
    elif plant == 2:
        expr = _plant(expr, lambda atom: ("+", ("n", 0), atom))
    elif plant == 3:
        expr = _plant(expr, lambda atom: ("*", ("n", 1), atom))
    current = expr
    lemmas = []
    for lemma in _PREFERENCE:
        rewritten = apply_first(current, lemma)
        if rewritten != current:
            current = rewritten
            lemmas.append(lemma)
        if len(lemmas) >= 3:
            break
    if not lemmas:
        return None
    key = ac_key(current)
    rhs = _spine(key, "right")
    if _pretty(rhs) == _pretty(expr):
        rhs = _spine(key, "left")
    return expr, rhs, tuple(lemmas)


def _leaves(rng: LCG, count: int) -> list:
    chosen = [("v", _VARS[index % len(_VARS)]) for index in range(count)]
    if not any(name == "a" for _, name in chosen):
        chosen[0] = ("v", "a")
    for index in range(len(chosen) - 1, 0, -1):
        swap = rng.randint(0, index)
        chosen[index], chosen[swap] = chosen[swap], chosen[index]
    return chosen


def _assoc(op: str, leaves: list):
    expr = leaves[0]
    for leaf in leaves[1:]:
        expr = (op, expr, leaf)
    return expr


def _assoc_right(op: str, leaves: list):
    expr = leaves[-1]
    for leaf in reversed(leaves[:-1]):
        expr = (op, leaf, expr)
    return expr


def _plant(expr, wrap):
    if expr[0] == "v":
        return wrap(expr)
    if expr[0] in ("+", "*"):
        return (expr[0], _plant(expr[1], wrap), expr[2])
    return expr


def _spine(key, side: str):
    if key[0] in ("v", "n"):
        return key
    op, parts = key
    children = [_spine(part, side) for part in parts]
    if side == "right":
        children = list(reversed(children))
        expr = children[-1]
        for child in reversed(children[:-1]):
            expr = (op, child, expr)
        return expr
    expr = children[0]
    for child in children[1:]:
        expr = (op, expr, child)
    return expr


def _descend(expr, lemma: str):
    replaced = _at(expr, lemma)
    if replaced is not None:
        return replaced
    if expr[0] not in ("+", "*"):
        return None
    left = _descend(expr[1], lemma)
    if left is not None:
        return (expr[0], left, expr[2])
    right = _descend(expr[2], lemma)
    if right is not None:
        return (expr[0], expr[1], right)
    return None


def _at(expr, lemma: str):
    if lemma == "Nat.add_zero" and _is(expr, "+", None, ("n", 0)):
        return expr[1]
    if lemma == "Nat.zero_add" and _is(expr, "+", ("n", 0), None):
        return expr[2]
    if lemma == "Nat.mul_one" and _is(expr, "*", None, ("n", 1)):
        return expr[1]
    if lemma == "Nat.one_mul" and _is(expr, "*", ("n", 1), None):
        return expr[2]
    if lemma == "Nat.add_mul" and expr[0] == "*" and expr[1][0] == "+":
        left, right = expr[1], expr[2]
        return ("+", ("*", left[1], right), ("*", left[2], right))
    if lemma == "Nat.mul_add" and expr[0] == "*" and expr[2][0] == "+":
        left, right = expr[1], expr[2]
        return ("+", ("*", left, right[1]), ("*", left, right[2]))
    return None


def _is(expr, op: str, left, right) -> bool:
    if expr[0] != op:
        return False
    if left is not None and expr[1] != left:
        return False
    if right is not None and expr[2] != right:
        return False
    return True


def _source(seed: int, index: int, names: tuple, statement: str, lemmas: tuple) -> str:
    title = f"rich_s{seed_token(seed)}_{index:04d}"
    binders = " ".join(f"({name} : Nat)" for name in names)
    lines = [f"theorem {title} {binders} : {statement} := by"]
    for lemma in lemmas:
        lines.extend(["  conv =>", "    lhs", f"    rw [{lemma}]"])
    lines.append("  ac_rfl")
    return "\n".join(lines) + "\n"


def _pretty(expr) -> str:
    if expr[0] == "v":
        return expr[1]
    if expr[0] == "n":
        return str(expr[1])
    symbol = "+" if expr[0] == "+" else "*"
    return f"({_pretty(expr[1])} {symbol} {_pretty(expr[2])})"


def _variables(expr) -> tuple:
    if expr[0] == "v":
        return (expr[1],)
    if expr[0] == "n":
        return ()
    return _variables(expr[1]) + _variables(expr[2])


def _depth(expr) -> int:
    if expr[0] in ("v", "n"):
        return 0
    return 1 + max(_depth(expr[1]), _depth(expr[2]))


def _size(expr) -> int:
    if expr[0] in ("v", "n"):
        return 1
    return 1 + _size(expr[1]) + _size(expr[2])


if __name__ == "__main__":
    raise SystemExit(main())
