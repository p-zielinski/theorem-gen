"""Monitor grades for this Lean fragment.

The numeral in an equation is not the difficulty. The grade uses the proof
method together with the shape already stored on the candidate: `ast_size`
and `depth`. Rows whose `proof_method` is `model` stored a character count in
`ast_size`, so they stay ungraded. `statement_depth` reads the nesting of the
equation text instead. It does not use how long Lean took.
"""

from __future__ import annotations

from typing import Optional


def effort_level(proof_method: str, ast_size: int, depth: int) -> Optional[int]:
    """Return 1..4, or None when this row has no structural grade."""
    method = proof_method or ""
    if method in {"", "model"}:
        return None
    if method == "rewrite" or ast_size >= 12 or depth >= 4:
        return 4
    if method == "lemma" or ast_size >= 8 or depth >= 3:
        return 3
    if method == "rfl" or ast_size >= 5 or depth >= 2:
        return 2
    return 1


def statement_measures(text: str) -> Optional[dict]:
    """Depth, operator count, and node count of a statement.

    The three numbers match `complexity._depth`, `_operators`, and `_size`.
    A numeral of any size is one leaf. None means the text is not a statement
    of this fragment. It is not a depth of zero.
    """
    proposition = _proposition(text or "")
    if not proposition.strip():
        return None
    try:
        scan = _Scan(proposition)
        depth, operators, size = _prop(scan)
        if scan.peek():
            return None
    except ValueError:
        return None
    return {"depth": depth, "operators": operators, "size": size}


def statement_depth(text: str) -> int:
    """Nesting of a statement. Text outside this fragment counts as 0."""
    found = statement_measures(text)
    if found is None:
        return 0
    return int(found["depth"])


def remember_shapes(conn) -> None:
    """Fill shape columns that are still empty. Unparsed text stays NULL."""
    names = {row[1] for row in conn.execute("PRAGMA table_info(model_attempts)")}
    if "expr_depth" not in names:
        return
    rows = conn.execute(
        "SELECT id, equation FROM model_attempts WHERE expr_depth IS NULL"
    ).fetchall()
    for row in rows:
        found = statement_measures(row["equation"] or "")
        if found is None:
            continue
        conn.execute(
            """
            UPDATE model_attempts
            SET expr_depth=?, expr_operators=?, expr_size=?
            WHERE id=? AND expr_depth IS NULL
            """,
            (found["depth"], found["operators"], found["size"], row["id"]),
        )


def _proposition(text: str) -> str:
    """The part after the last colon that is outside parentheses."""
    depth = 0
    cut = None
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0:
            if index + 1 < len(text) and text[index + 1] == "=":
                continue
            if index > 0 and text[index - 1] == ":":
                continue
            cut = index + 1
    if cut is None:
        return text
    return text[cut:]


class _Scan:
    def __init__(self, text: str) -> None:
        cleaned = text.replace("≤", "<=").replace("≥", ">=").replace("→", "->")
        self.tokens = []
        index = 0
        while index < len(cleaned):
            char = cleaned[index]
            if char.isspace():
                index += 1
                continue
            if cleaned.startswith("<=", index) or cleaned.startswith(">=", index) or cleaned.startswith("->", index):
                self.tokens.append(cleaned[index : index + 2])
                index += 2
                continue
            if char in "()+*<>:=,-":
                self.tokens.append(char)
                index += 1
                continue
            if char.isdigit():
                end = index + 1
                while end < len(cleaned) and cleaned[end].isdigit():
                    end += 1
                self.tokens.append(cleaned[index:end])
                index = end
                continue
            if char.isalpha() or char == "_":
                end = index + 1
                while end < len(cleaned) and (cleaned[end].isalnum() or cleaned[end] in ".'"):
                    end += 1
                self.tokens.append(cleaned[index:end])
                index = end
                continue
            raise ValueError(char)
        self.index = 0

    def peek(self) -> str:
        if self.index >= len(self.tokens):
            return ""
        return self.tokens[self.index]

    def ahead(self, offset: int) -> str:
        position = self.index + offset
        if position >= len(self.tokens):
            return ""
        return self.tokens[position]

    def take(self, expected: Optional[str] = None) -> str:
        token = self.peek()
        if expected is not None and token != expected:
            raise ValueError(token or "end")
        if not token:
            raise ValueError("end")
        self.index += 1
        return token


def _leaf() -> tuple:
    return (0, 0, 1)


def _bin(left: tuple, right: tuple, counted: bool) -> tuple:
    return (
        1 + max(left[0], right[0]),
        left[1] + right[1] + (1 if counted else 0),
        1 + left[2] + right[2],
    )


def _wrap(child: tuple, counted: bool) -> tuple:
    return (1 + child[0], child[1] + (1 if counted else 0), 1 + child[2])


def _prop(scan: _Scan) -> tuple:
    if scan.peek() == "forall":
        scan.take("forall")
        binders = 0
        while scan.peek() == "(":
            scan.take("(")
            _name(scan)
            scan.take(":")
            _name(scan)
            scan.take(")")
            binders += 1
        if binders == 0:
            raise ValueError("forall")
        scan.take(",")
        body = _prop(scan)
        return (1 + body[0], body[1], 1 + binders + body[2])
    return _implies(scan)


def _implies(scan: _Scan) -> tuple:
    left = _compare(scan)
    if scan.peek() == "->":
        scan.take("->")
        return _bin(left, _implies(scan), False)
    return left


def _compare(scan: _Scan) -> tuple:
    left = _sum(scan)
    if scan.peek() in {"=", "<=", "<", ">=", ">"}:
        scan.take()
        return _bin(left, _sum(scan), False)
    return left


def _sum(scan: _Scan) -> tuple:
    shape = _mul(scan)
    while scan.peek() == "+":
        scan.take("+")
        shape = _bin(shape, _mul(scan), True)
    return shape


def _mul(scan: _Scan) -> tuple:
    shape = _unary(scan)
    while scan.peek() == "*":
        scan.take("*")
        shape = _bin(shape, _unary(scan), True)
    return shape


def _unary(scan: _Scan) -> tuple:
    if scan.peek() == "-":
        scan.take("-")
        return _wrap(_unary(scan), True)
    return _apply(scan)


def _apply(scan: _Scan) -> tuple:
    name = scan.peek()
    shape = _atom(scan)
    args = []
    while _starts_atom(scan.peek()):
        args.append(_atom(scan))
    if not args:
        return shape
    if name == "Nat.succ" and len(args) == 1:
        return _wrap(args[0], True)
    return (
        1 + max(arg[0] for arg in args),
        sum(arg[1] for arg in args),
        1 + sum(arg[2] for arg in args),
    )


def _atom(scan: _Scan) -> tuple:
    token = scan.peek()
    if token[:1].isdigit():
        scan.take()
        return _leaf()
    if token[:1].isalpha() or token[:1] == "_":
        if token == "forall":
            raise ValueError(token)
        scan.take()
        return _leaf()
    if token == "(":
        scan.take("(")
        if _typed_literal(scan):
            if scan.peek() == "-":
                scan.take("-")
            scan.take()
            scan.take(":")
            _name(scan)
            scan.take(")")
            return _leaf()
        shape = _prop(scan)
        scan.take(")")
        return shape
    raise ValueError(token or "end")


def _typed_literal(scan: _Scan) -> bool:
    """True when the next tokens are an optional minus, a numeral, and `: Type`."""
    offset = 0
    if scan.peek() == "-" and scan.ahead(1)[:1].isdigit():
        offset = 1
    number = scan.ahead(offset) if offset else scan.peek()
    if not number[:1].isdigit():
        return False
    return scan.ahead(offset + 1) == ":"


def _starts_atom(token: str) -> bool:
    if not token or token == "forall":
        return False
    return token[:1].isdigit() or token[:1].isalpha() or token[:1] == "_" or token == "("


def _name(scan: _Scan) -> None:
    token = scan.peek()
    if not token or not (token[:1].isalpha() or token[:1] == "_"):
        raise ValueError(token or "end")
    scan.take()


def lean_time_band(lean_ms: Optional[int]) -> Optional[str]:
    """How long one Lean process took. None means the row predates the column."""
    if lean_ms is None:
        return None
    if lean_ms < 100:
        return "fast"
    if lean_ms < 500:
        return "normal"
    if lean_ms < 2000:
        return "slow"
    return "heavy"
