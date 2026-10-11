"""Definitions inside the supported fragment, then theorems that use them."""

from __future__ import annotations

from dataclasses import dataclass

from theorem_gen.errors import DefinitionError
from theorem_gen.expr import (
    BinOp,
    Compare,
    Const,
    NatLit,
    UnaryOp,
    Var,
    arith_type,
    free_vars,
    infer,
)
from theorem_gen.registry import Registry
from theorem_gen.theorem import Metadata, Proof, Theorem


@dataclass(frozen=True)
class Definition:
    identifier: str
    name: str
    params: tuple
    body: object
    result_type: str


def validate_definition(definition: Definition) -> None:
    if any(not isinstance(param, Var) for param in definition.params):
        raise DefinitionError("parameters must be variables")
    names = [param.name for param in definition.params]
    if len(names) != len(set(names)):
        raise DefinitionError("duplicate parameter")
    try:
        body_type = arith_type(definition.body) if definition.result_type != "Prop" else infer(definition.body)
    except Exception as exc:
        raise DefinitionError(str(exc)) from exc
    if body_type != definition.result_type:
        raise DefinitionError(
            f"body has type {body_type}, definition declares {definition.result_type}"
        )
    extra = [item.name for item in free_vars(definition.body) if item.name not in names]
    if extra:
        raise DefinitionError(f"free variable {extra[0]} is not a parameter")
    if _mentions(definition.body, definition.name):
        raise DefinitionError("recursive definitions are outside this fragment")


def double_definition() -> Definition:
    param = Var("n", "Nat")
    return Definition(
        identifier="def_double",
        name="double",
        params=(param,),
        body=BinOp("add", param, param),
        result_type="Nat",
    )


def theorem_about_double(definition: Definition = None) -> Theorem:
    definition = double_definition() if definition is None else definition
    validate_definition(definition)
    statement = Compare(
        "eq",
        Const(definition.name, "Nat", (NatLit(0),)),
        NatLit(0),
    )
    return Theorem(
        statement,
        Proof("rfl"),
        Metadata(
            identifier="gen_double_zero",
            kind="concrete",
            rules=("use_definition",),
            verification="unverified",
            dependencies=(definition.identifier,),
            discovered=False,
        ),
    )


def supporting_definitions(theorems) -> tuple:
    found = []
    seen = set()
    for theorem in theorems:
        if "def_double" in theorem.metadata.dependencies and "def_double" not in seen:
            found.append(double_definition())
            seen.add("def_double")
    return tuple(found)


def register_definition(definition: Definition, theorem: Theorem = None) -> Registry:
    validate_definition(definition)
    registry = Registry()
    registry.add(
        definition.identifier,
        kind="definition",
        rules=("define",),
        discovered=True,
    )
    if theorem is not None:
        registry.add(
            theorem.metadata.identifier,
            kind="theorem",
            dependencies=theorem.metadata.dependencies,
            rules=theorem.metadata.rules,
            discovered=theorem.metadata.discovered,
        )
    return registry


def _mentions(expr: object, name: str) -> bool:
    if isinstance(expr, Const):
        return expr.name == name or any(_mentions(arg, name) for arg in expr.args)
    if isinstance(expr, UnaryOp):
        return _mentions(expr.arg, name)
    if isinstance(expr, (BinOp, Compare)):
        return _mentions(expr.left, name) or _mentions(expr.right, name)
    return False
