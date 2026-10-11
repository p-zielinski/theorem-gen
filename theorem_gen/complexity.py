"""Several structural measures. A large numeral is not automatically harder."""

from __future__ import annotations

from theorem_gen.expr import (
    Atom,
    BinOp,
    Compare,
    Const,
    Forall,
    Implies,
    IntLit,
    NatLit,
    UnaryOp,
    Var,
)


def measure_expr(expr: object) -> dict:
    return {
        "ast_size": _size(expr),
        "depth": _depth(expr),
        "variables": len({item.name for item in _variables(expr)}),
        "operators": _operators(expr),
        "dependencies": 0,
        "definitions": _definitions(expr),
    }


def measure_theorem(theorem, registry=None) -> dict:
    measures = measure_expr(theorem.statement)
    dependencies = tuple(theorem.metadata.dependencies)
    measures["dependencies"] = len(dependencies)
    if registry is None:
        return measures
    measures["definitions"] = sum(
        1 for identifier in dependencies if registry.get(identifier).kind == "definition"
    )
    return measures


def within_bounds(measures: dict, bounds: dict) -> bool:
    for key, (low, high) in bounds.items():
        if measures[key] < low or measures[key] > high:
            return False
    return True


def _size(expr: object) -> int:
    if isinstance(expr, (NatLit, IntLit, Var)):
        return 1
    if isinstance(expr, UnaryOp):
        return 1 + _size(expr.arg)
    if isinstance(expr, (BinOp, Compare)):
        return 1 + _size(expr.left) + _size(expr.right)
    if isinstance(expr, (Const, Atom)):
        return 1 + sum(_size(arg) for arg in expr.args)
    if isinstance(expr, Implies):
        return 1 + _size(expr.premise) + _size(expr.conclusion)
    if isinstance(expr, Forall):
        return 1 + len(expr.binders) + _size(expr.body)
    raise TypeError(f"cannot measure {type(expr).__name__}")


def _depth(expr: object) -> int:
    if isinstance(expr, (NatLit, IntLit, Var)):
        return 0
    if isinstance(expr, UnaryOp):
        return 1 + _depth(expr.arg)
    if isinstance(expr, (BinOp, Compare)):
        return 1 + max(_depth(expr.left), _depth(expr.right))
    if isinstance(expr, (Const, Atom)):
        if not expr.args:
            return 0
        return 1 + max(_depth(arg) for arg in expr.args)
    if isinstance(expr, Implies):
        return 1 + max(_depth(expr.premise), _depth(expr.conclusion))
    if isinstance(expr, Forall):
        return 1 + _depth(expr.body)
    raise TypeError(f"cannot measure {type(expr).__name__}")


def _operators(expr: object) -> int:
    if isinstance(expr, (UnaryOp, BinOp)):
        own = 1
    else:
        own = 0
    if isinstance(expr, UnaryOp):
        return own + _operators(expr.arg)
    if isinstance(expr, (BinOp, Compare)):
        return own + _operators(expr.left) + _operators(expr.right)
    if isinstance(expr, (Const, Atom)):
        return own + sum(_operators(arg) for arg in expr.args)
    if isinstance(expr, Implies):
        return _operators(expr.premise) + _operators(expr.conclusion)
    if isinstance(expr, Forall):
        return _operators(expr.body)
    return own


def _definitions(expr: object) -> int:
    if isinstance(expr, Const):
        return 1 + sum(_definitions(arg) for arg in expr.args)
    if isinstance(expr, UnaryOp):
        return _definitions(expr.arg)
    if isinstance(expr, (BinOp, Compare)):
        return _definitions(expr.left) + _definitions(expr.right)
    if isinstance(expr, Atom):
        return sum(_definitions(arg) for arg in expr.args)
    if isinstance(expr, Implies):
        return _definitions(expr.premise) + _definitions(expr.conclusion)
    if isinstance(expr, Forall):
        return _definitions(expr.body)
    return 0


def _variables(expr: object) -> tuple:
    if isinstance(expr, Var):
        return (expr,)
    if isinstance(expr, UnaryOp):
        return _variables(expr.arg)
    if isinstance(expr, (BinOp, Compare)):
        return _variables(expr.left) + _variables(expr.right)
    if isinstance(expr, (Const, Atom)):
        found = ()
        for arg in expr.args:
            found += _variables(arg)
        return found
    if isinstance(expr, Implies):
        return _variables(expr.premise) + _variables(expr.conclusion)
    if isinstance(expr, Forall):
        return tuple(expr.binders) + _variables(expr.body)
    return ()
