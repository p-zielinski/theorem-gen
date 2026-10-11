"""Typed expressions. Closed Nat arithmetic stays compatible with stage 1."""

from __future__ import annotations

from dataclasses import dataclass

from theorem_gen.errors import ExprError, TypingError

_NAME = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
_TYPES = {"Nat", "Int", "Prop"}


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.match(name):
        raise ExprError(f"invalid name: {name!r}")


def arith_type(expr: object) -> str:
    if isinstance(expr, NatLit):
        return "Nat"
    if isinstance(expr, IntLit):
        return "Int"
    if isinstance(expr, Var):
        if expr.type_name not in {"Nat", "Int"}:
            raise TypingError(f"variable {expr.name} is not arithmetic")
        return expr.type_name
    if isinstance(expr, UnaryOp):
        return _unary_type(expr)
    if isinstance(expr, BinOp):
        return arith_type(expr.left)
    if isinstance(expr, Const):
        if expr.type_name not in {"Nat", "Int"}:
            raise TypingError(f"{expr.name} is not arithmetic")
        return expr.type_name
    raise TypingError(f"expected an arithmetic expression, got {type(expr).__name__}")


def _unary_type(expr: "UnaryOp") -> str:
    if expr.op == "succ":
        if arith_type(expr.arg) != "Nat":
            raise TypingError("succ expects Nat")
        return "Nat"
    if expr.op == "neg":
        if arith_type(expr.arg) != "Int":
            raise TypingError("neg expects Int")
        return "Int"
    raise TypingError(f"unknown unary operator: {expr.op}")


@dataclass(frozen=True)
class NatLit:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ExprError("Nat literal must be a non-negative int")
        if self.value < 0:
            raise ExprError("Nat literal must be >= 0")


@dataclass(frozen=True)
class IntLit:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ExprError("Int literal must be an int")


@dataclass(frozen=True)
class Var:
    name: str
    type_name: str

    def __post_init__(self) -> None:
        _check_name(self.name)
        if self.type_name not in _TYPES:
            raise TypingError(f"unknown type: {self.type_name}")


@dataclass(frozen=True)
class UnaryOp:
    op: str
    arg: object

    def __post_init__(self) -> None:
        if self.op == "pred":
            raise TypingError(
                "pred is rejected because the truncated Nat predecessor maps 0 to 0"
            )
        if self.op not in {"succ", "neg"}:
            raise TypingError(f"unknown unary operator: {self.op}")
        _unary_type(self)


@dataclass(frozen=True)
class BinOp:
    op: str
    left: object
    right: object

    def __post_init__(self) -> None:
        if self.op not in {"add", "mul"}:
            raise TypingError(f"unknown arithmetic operator: {self.op}")
        left = arith_type(self.left)
        right = arith_type(self.right)
        if left != right:
            raise TypingError(f"cannot apply {self.op} to {left} and {right}")


@dataclass(frozen=True)
class Const:
    name: str
    type_name: str
    args: tuple = ()

    def __post_init__(self) -> None:
        _check_name(self.name)
        if self.type_name not in _TYPES:
            raise TypingError(f"unknown type: {self.type_name}")
        if isinstance(self.args, str) or not isinstance(self.args, (tuple, list)):
            raise TypingError("const arguments must be a tuple")
        args = tuple(self.args)
        object.__setattr__(self, "args", args)
        if self.type_name in {"Nat", "Int"}:
            for arg in args:
                found = arith_type(arg)
                if found != self.type_name:
                    raise TypingError(f"cannot apply {self.name} to {found}")


@dataclass(frozen=True)
class Compare:
    op: str
    left: object
    right: object

    def __post_init__(self) -> None:
        if self.op not in {"eq", "le", "lt"}:
            raise TypingError(f"unknown comparison: {self.op}")
        left = arith_type(self.left)
        right = arith_type(self.right)
        if left != right:
            raise TypingError(f"cannot compare {left} with {right}")


@dataclass(frozen=True)
class Atom:
    name: str
    args: tuple = ()

    def __post_init__(self) -> None:
        _check_name(self.name)
        if isinstance(self.args, str) or not isinstance(self.args, (tuple, list)):
            raise TypingError("atom arguments must be a tuple")
        args = tuple(self.args)
        object.__setattr__(self, "args", args)
        for arg in args:
            if infer(arg) == "Prop":
                raise TypingError(f"atom {self.name} expects an expression")


@dataclass(frozen=True)
class Implies:
    premise: object
    conclusion: object

    def __post_init__(self) -> None:
        if infer(self.premise) != "Prop" or infer(self.conclusion) != "Prop":
            raise TypingError("implication expects propositions")


@dataclass(frozen=True)
class Forall:
    binders: tuple
    body: object

    def __post_init__(self) -> None:
        if not isinstance(self.binders, (tuple, list)) or not self.binders:
            raise TypingError("forall expects at least one binder")
        binders = tuple(self.binders)
        names = []
        for binder in binders:
            if not isinstance(binder, Var):
                raise TypingError("forall binders must be variables")
            if binder.name in names:
                raise TypingError(f"duplicate binder {binder.name}")
            names.append(binder.name)
        object.__setattr__(self, "binders", binders)
        if infer(self.body) != "Prop":
            raise TypingError("forall body must be a proposition")
        unknown = [item.name for item in free_vars(self.body) if item.name not in names]
        if unknown:
            raise TypingError(f"unbound variable {unknown[0]}")


def infer(expr: object) -> str:
    if isinstance(expr, (Compare, Implies, Forall, Atom)):
        return "Prop"
    if isinstance(expr, Var):
        return expr.type_name
    if isinstance(expr, Const) and expr.type_name == "Prop":
        return "Prop"
    return arith_type(expr)


def evaluate(expr: object) -> int:
    if isinstance(expr, NatLit):
        return expr.value
    if isinstance(expr, UnaryOp) and expr.op == "succ":
        return evaluate(expr.arg) + 1
    if isinstance(expr, BinOp):
        if arith_type(expr) != "Nat":
            raise TypingError("evaluate expects a closed Nat expression")
        left = evaluate(expr.left)
        right = evaluate(expr.right)
        if expr.op == "add":
            return left + right
        return left * right
    raise TypingError("evaluate expects a closed Nat expression")


def holds(prop: Compare) -> bool:
    if not isinstance(prop, Compare) or arith_type(prop.left) != "Nat":
        raise TypingError("holds expects a closed Nat comparison")
    left = evaluate(prop.left)
    right = evaluate(prop.right)
    if prop.op == "eq":
        return left == right
    if prop.op == "le":
        return left <= right
    return left < right


def free_vars(expr: object, bound: tuple = ()) -> tuple:
    names = set(bound)
    if isinstance(expr, Var):
        if expr.name in names:
            return ()
        return (expr,)
    if isinstance(expr, (NatLit, IntLit)):
        return ()
    if isinstance(expr, (UnaryOp,)):
        return free_vars(expr.arg, bound)
    if isinstance(expr, (BinOp, Compare)):
        return _merge(free_vars(expr.left, bound), free_vars(expr.right, bound))
    if isinstance(expr, Const):
        found = ()
        for arg in expr.args:
            found = _merge(found, free_vars(arg, bound))
        return found
    if isinstance(expr, Atom):
        found = ()
        for arg in expr.args:
            found = _merge(found, free_vars(arg, bound))
        return found
    if isinstance(expr, Implies):
        return _merge(free_vars(expr.premise, bound), free_vars(expr.conclusion, bound))
    if isinstance(expr, Forall):
        inner = bound + tuple(item.name for item in expr.binders)
        return free_vars(expr.body, inner)
    raise TypingError(f"cannot collect variables from {type(expr).__name__}")


def _merge(left: tuple, right: tuple) -> tuple:
    seen = {item.name for item in left}
    merged = list(left)
    for item in right:
        if item.name not in seen:
            seen.add(item.name)
            merged.append(item)
    return tuple(merged)


def structural_key(expr: object) -> tuple:
    if isinstance(expr, NatLit):
        return ("lit", expr.value)
    if isinstance(expr, IntLit):
        return ("int", expr.value)
    if isinstance(expr, Var):
        return ("var", expr.name, expr.type_name)
    if isinstance(expr, UnaryOp):
        return (expr.op, structural_key(expr.arg))
    if isinstance(expr, BinOp):
        return (expr.op, structural_key(expr.left), structural_key(expr.right))
    if isinstance(expr, Const):
        return ("const", expr.name, expr.type_name, tuple(structural_key(arg) for arg in expr.args))
    if isinstance(expr, Compare):
        return (expr.op, structural_key(expr.left), structural_key(expr.right))
    if isinstance(expr, Atom):
        return ("atom", expr.name, tuple(structural_key(arg) for arg in expr.args))
    if isinstance(expr, Implies):
        return ("implies", structural_key(expr.premise), structural_key(expr.conclusion))
    if isinstance(expr, Forall):
        binders = tuple((item.name, item.type_name) for item in expr.binders)
        return ("forall", binders, structural_key(expr.body))
    raise TypingError(f"cannot key {type(expr).__name__}")


def substitute(expr: object, env: dict) -> object:
    if isinstance(expr, Var) and expr.name in env:
        return env[expr.name]
    if isinstance(expr, (NatLit, IntLit, Var)):
        return expr
    if isinstance(expr, UnaryOp):
        return UnaryOp(expr.op, substitute(expr.arg, env))
    if isinstance(expr, BinOp):
        return BinOp(expr.op, substitute(expr.left, env), substitute(expr.right, env))
    if isinstance(expr, Const):
        return Const(expr.name, expr.type_name, tuple(substitute(arg, env) for arg in expr.args))
    if isinstance(expr, Compare):
        return Compare(expr.op, substitute(expr.left, env), substitute(expr.right, env))
    if isinstance(expr, Atom):
        return Atom(expr.name, tuple(substitute(arg, env) for arg in expr.args))
    if isinstance(expr, Implies):
        return Implies(substitute(expr.premise, env), substitute(expr.conclusion, env))
    if isinstance(expr, Forall):
        hidden = {item.name for item in expr.binders}
        inner = {key: value for key, value in env.items() if key not in hidden}
        return Forall(expr.binders, substitute(expr.body, inner))
    raise TypingError(f"cannot substitute in {type(expr).__name__}")
