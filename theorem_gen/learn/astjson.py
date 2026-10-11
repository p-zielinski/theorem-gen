"""Canonical JSON for the typed AST. The hash follows structural_key."""

from __future__ import annotations

import hashlib
import json

from theorem_gen.errors import ExprError, TypingError
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
    infer,
    structural_key,
)


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def structural_hash(expr: object) -> str:
    payload = json.dumps(_jsonable(structural_key(expr)), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dump_expr(expr: object) -> dict:
    if isinstance(expr, NatLit):
        return {"type": "NatLit", "value": expr.value}
    if isinstance(expr, IntLit):
        return {"type": "IntLit", "value": expr.value}
    if isinstance(expr, Var):
        return {"type": "Var", "name": expr.name, "type_name": expr.type_name}
    if isinstance(expr, UnaryOp):
        return {"type": "UnaryOp", "op": expr.op, "arg": dump_expr(expr.arg)}
    if isinstance(expr, BinOp):
        return {
            "type": "BinOp",
            "op": expr.op,
            "left": dump_expr(expr.left),
            "right": dump_expr(expr.right),
        }
    if isinstance(expr, Const):
        return {
            "type": "Const",
            "name": expr.name,
            "type_name": expr.type_name,
            "args": [dump_expr(arg) for arg in expr.args],
        }
    if isinstance(expr, Compare):
        return {
            "type": "Compare",
            "op": expr.op,
            "left": dump_expr(expr.left),
            "right": dump_expr(expr.right),
        }
    if isinstance(expr, Atom):
        return {
            "type": "Atom",
            "name": expr.name,
            "args": [dump_expr(arg) for arg in expr.args],
        }
    if isinstance(expr, Implies):
        return {
            "type": "Implies",
            "premise": dump_expr(expr.premise),
            "conclusion": dump_expr(expr.conclusion),
        }
    if isinstance(expr, Forall):
        return {
            "type": "Forall",
            "binders": [dump_expr(item) for item in expr.binders],
            "body": dump_expr(expr.body),
        }
    raise TypingError(f"cannot encode {type(expr).__name__}")


def canonical_json(expr: object) -> str:
    return json.dumps(dump_expr(expr), sort_keys=True, separators=(",", ":"))


def load_expr(data: object) -> object:
    if not isinstance(data, dict) or "type" not in data:
        raise TypingError("AST node must be an object with a type")
    kind = data["type"]
    if kind == "NatLit":
        return NatLit(data["value"])
    if kind == "IntLit":
        return IntLit(data["value"])
    if kind == "Var":
        return Var(data["name"], data["type_name"])
    if kind == "UnaryOp":
        return UnaryOp(data["op"], load_expr(data["arg"]))
    if kind == "BinOp":
        return BinOp(data["op"], load_expr(data["left"]), load_expr(data["right"]))
    if kind == "Const":
        return Const(
            data["name"],
            data["type_name"],
            tuple(load_expr(arg) for arg in data.get("args", ())),
        )
    if kind == "Compare":
        return Compare(data["op"], load_expr(data["left"]), load_expr(data["right"]))
    if kind == "Atom":
        return Atom(data["name"], tuple(load_expr(arg) for arg in data.get("args", ())))
    if kind == "Implies":
        return Implies(load_expr(data["premise"]), load_expr(data["conclusion"]))
    if kind == "Forall":
        return Forall(tuple(load_expr(item) for item in data["binders"]), load_expr(data["body"]))
    raise TypingError(f"unknown AST type: {kind}")


def load_prop(text: str) -> object:
    try:
        expr = load_expr(json.loads(text))
    except (ExprError, TypingError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise TypingError(str(exc)) from exc
    if infer(expr) != "Prop":
        raise TypingError("hypothesis must have type Prop")
    return expr
