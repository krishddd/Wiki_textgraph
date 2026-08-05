"""Recursive-descent parser for the TextGraph GQL subset (Phase 7).

Grammar (Cypher/ISO-GQL flavoured):

    MATCH [p '='] pattern [WHERE expr] RETURN [DISTINCT] items
          [ORDER BY keys] [SKIP n] [LIMIT n]
    pattern := node (rel node)*
    node    := '(' [var] (':' Label)* ['{' k ':' lit (',' ...)* '}'] ')'
    rel     := ('-'|'<-') ['[' [var] [':' Type ('|' Type)*] ['*' [int] ['..' [int]]] ']'] ('-'|'->')
    expr    := or; or := and (OR and)*; and := not (AND not)*; not := NOT not | cmp
    cmp     := operand [(= <> < <= > >= | CONTAINS | STARTS WITH | ENDS WITH | IN) operand]

Pure and deterministic; raises :class:`GQLError` with a position on any malformed
input. Quantified relationships (``*min..max``) are the ISO-GQL variable-length paths.
"""

from __future__ import annotations

from typing import Any

from textgraph.gql.ast import (
    BoolOp,
    Comparison,
    FuncCall,
    Literal,
    NodePattern,
    Not,
    OrderKey,
    PathPattern,
    Property,
    Query,
    RelPattern,
    ReturnItem,
)
from textgraph.gql.errors import GQLError
from textgraph.gql.tokenizer import Token, tokenize

_UNBOUNDED = 8  # cap for open-ended quantified paths like `*` / `*2..` (keeps search finite, G7)
_FUNCS = frozenset({"type", "count", "labels", "id"})


class Parser:
    def __init__(self, text: str) -> None:
        self._toks = tokenize(text)
        self._i = 0

    # -- token helpers ----------------------------------------------------------

    def _peek(self) -> Token:
        return self._toks[self._i]

    def _next(self) -> Token:
        t = self._toks[self._i]
        self._i += 1
        return t

    def _at(self, kind: str, value: str | None = None) -> bool:
        t = self._peek()
        return t.kind == kind and (value is None or t.value == value)

    def _eat(self, kind: str, value: str | None = None) -> Token:
        t = self._peek()
        if t.kind != kind or (value is not None and t.value != value):
            want = value or kind
            raise GQLError(f"expected {want!r}, found {t.value or t.kind!r}", t.pos)
        return self._next()

    def _int(self) -> int:
        """Eat a NON-negative integer literal (hop counts, SKIP, LIMIT are integers)."""
        t = self._eat("number")
        if "." in t.value:
            raise GQLError(f"expected an integer, found {t.value!r}", t.pos)
        return int(t.value)

    # -- entry ------------------------------------------------------------------

    def parse(self) -> Query:
        self._eat("keyword", "MATCH")
        pattern = self._pattern()
        where = None
        if self._at("keyword", "WHERE"):
            self._next()
            where = self._expr()
        self._eat("keyword", "RETURN")
        distinct = False
        if self._at("keyword", "DISTINCT"):
            self._next()
            distinct = True
        returns = self._return_items()
        order_by: tuple[OrderKey, ...] = ()
        if self._at("keyword", "ORDER"):
            self._next()
            self._eat("keyword", "BY")
            order_by = self._order_keys()
        skip = 0
        if self._at("keyword", "SKIP"):
            self._next()
            skip = self._int()
        limit = None
        if self._at("keyword", "LIMIT"):
            self._next()
            limit = self._int()
        if not self._at("eof"):
            t = self._peek()
            raise GQLError(f"unexpected trailing input {t.value!r}", t.pos)
        variables = self._collect_vars(pattern)
        return Query(pattern, where, returns, distinct, order_by, limit, skip, variables)

    # -- pattern ----------------------------------------------------------------

    def _pattern(self) -> PathPattern:
        path_var = None
        # `MATCH p = (...)`
        if self._at("ident") and self._toks[self._i + 1].value == "=":
            path_var = self._next().value
            self._eat("punct", "=")
        nodes = [self._node()]
        rels: list[RelPattern] = []
        while self._at("punct", "-") or self._at("punct", "<-"):
            rels.append(self._rel())
            nodes.append(self._node())
        return PathPattern(tuple(nodes), tuple(rels), path_var)

    def _node(self) -> NodePattern:
        self._eat("punct", "(")
        var = self._next().value if self._at("ident") else None
        labels: list[str] = []
        while self._at("punct", ":"):
            self._next()
            labels.append(self._eat("ident").value)
        props: list[tuple[str, Any]] = []
        if self._at("punct", "{"):
            props = self._prop_map()
        self._eat("punct", ")")
        return NodePattern(var, tuple(labels), tuple(props))

    def _prop_map(self) -> list[tuple[str, Any]]:
        self._eat("punct", "{")
        out: list[tuple[str, Any]] = []
        while not self._at("punct", "}"):
            key = self._eat("ident").value
            self._eat("punct", ":")
            out.append((key, self._literal().value))  # store the raw literal value
            if self._at("punct", ","):
                self._next()
        self._eat("punct", "}")
        return out

    def _rel(self) -> RelPattern:
        left_in = self._at("punct", "<-")
        self._next()  # consume '-' or '<-'
        var: str | None = None
        types: list[str] = []
        min_hops, max_hops = 1, 1
        if self._at("punct", "["):
            self._next()
            if self._at("ident"):
                var = self._next().value
            if self._at("punct", ":"):
                self._next()
                types.append(self._eat("ident").value)
                while self._at("punct", "|"):
                    self._next()
                    types.append(self._eat("ident").value)
            if self._at("punct", "*"):
                self._next()
                min_hops, max_hops = 1, _UNBOUNDED
                if self._at("number"):
                    min_hops = self._int()
                    max_hops = min_hops
                if self._at("punct", ".."):
                    self._next()
                    max_hops = self._int() if self._at("number") else _UNBOUNDED
            self._eat("punct", "]")
        right_out = self._at("punct", "->")
        if not (self._at("punct", "-") or self._at("punct", "->")):
            t = self._peek()
            raise GQLError(f"malformed relationship near {t.value!r}", t.pos)
        self._next()  # consume '-' or '->'
        if left_in and right_out:
            raise GQLError("relationship cannot point both directions", self._peek().pos)
        direction = "in" if left_in else "out" if right_out else "both"
        return RelPattern(var, tuple(types), direction, min_hops, max_hops)

    # -- expressions ------------------------------------------------------------

    def _expr(self) -> Any:
        return self._or()

    def _or(self) -> Any:
        clauses = [self._and()]
        while self._at("keyword", "OR"):
            self._next()
            clauses.append(self._and())
        return clauses[0] if len(clauses) == 1 else BoolOp("OR", tuple(clauses))

    def _and(self) -> Any:
        clauses = [self._not()]
        while self._at("keyword", "AND"):
            self._next()
            clauses.append(self._not())
        return clauses[0] if len(clauses) == 1 else BoolOp("AND", tuple(clauses))

    def _not(self) -> Any:
        if self._at("keyword", "NOT"):
            self._next()
            return Not(self._not())
        if self._at("punct", "("):
            self._next()
            inner = self._or()
            self._eat("punct", ")")
            return inner
        return self._comparison()

    def _comparison(self) -> Comparison:
        left = self._operand()
        t = self._peek()
        op: str | None = None
        if t.kind == "punct" and t.value in ("=", "<>", "<", "<=", ">", ">="):
            op = self._next().value
        elif self._at("keyword", "CONTAINS"):
            self._next()
            op = "CONTAINS"
        elif self._at("keyword", "IN"):
            self._next()
            op = "IN"
        elif self._at("keyword", "STARTS"):
            self._next()
            self._eat("keyword", "WITH")
            op = "STARTS_WITH"
        elif self._at("keyword", "ENDS"):
            self._next()
            self._eat("keyword", "WITH")
            op = "ENDS_WITH"
        if op is None:
            raise GQLError("expected a comparison operator in WHERE", t.pos)
        return Comparison(left, op, self._operand())

    def _operand(self) -> Any:
        if self._at("ident"):
            name = self._next().value
            if name in _FUNCS and self._at("punct", "("):
                return self._func_tail(name)
            if self._at("punct", "."):
                self._next()
                return Property(name, self._eat("ident").value)
            return Property(name, "")  # bare variable -> its display name
        return self._literal()

    def _func_tail(self, name: str) -> FuncCall:
        self._eat("punct", "(")
        arg: str | None = None
        if self._at("punct", "*"):
            self._next()
        elif self._at("ident"):
            arg = self._next().value
        self._eat("punct", ")")
        return FuncCall(name, arg)

    def _literal(self) -> Literal:
        t = self._peek()
        sign = 1
        if t.kind == "punct" and t.value == "-":  # negative number literal
            self._next()
            t = self._peek()
            if t.kind != "number":
                raise GQLError(f"expected a number after '-', found {t.value or t.kind!r}", t.pos)
            sign = -1
        if t.kind == "string":
            return Literal(self._next().value)
        if t.kind == "number":
            v = self._next().value
            return Literal(sign * (float(v) if "." in v else int(v)))
        if t.kind == "keyword" and t.value in ("TRUE", "FALSE"):
            self._next()
            return Literal(t.value == "TRUE")
        if t.kind == "keyword" and t.value == "NULL":
            self._next()
            return Literal(None)
        raise GQLError(f"expected a literal, found {t.value or t.kind!r}", t.pos)

    # -- return / order ---------------------------------------------------------

    def _return_items(self) -> tuple[ReturnItem, ...]:
        items = [self._return_item()]
        while self._at("punct", ","):
            self._next()
            items.append(self._return_item())
        return tuple(items)

    def _return_item(self) -> ReturnItem:
        expr = self._return_expr()
        alias = None
        if self._at("keyword", "AS"):
            self._next()
            alias = self._eat("ident").value
        return ReturnItem(expr, alias)

    def _return_expr(self) -> Any:
        if self._at("ident"):
            name = self._next().value
            if name in _FUNCS and self._at("punct", "("):
                return self._func_tail(name)
            if self._at("punct", "."):
                self._next()
                return Property(name, self._eat("ident").value)
            return name  # bare variable
        return self._literal()

    def _order_keys(self) -> tuple[OrderKey, ...]:
        keys = [self._order_key()]
        while self._at("punct", ","):
            self._next()
            keys.append(self._order_key())
        return tuple(keys)

    def _order_key(self) -> OrderKey:
        expr = self._return_expr()
        desc = False
        if self._at("keyword", "ASC"):
            self._next()
        elif self._at("keyword", "DESC"):
            self._next()
            desc = True
        return OrderKey(expr, desc)

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _collect_vars(pattern: PathPattern) -> tuple[str, ...]:
        seen: list[str] = []
        for np in pattern.nodes:
            if np.var and np.var not in seen:
                seen.append(np.var)
        for rp in pattern.rels:
            if rp.var and rp.var not in seen:
                seen.append(rp.var)
        if pattern.path_var and pattern.path_var not in seen:
            seen.append(pattern.path_var)
        return tuple(seen)


def parse(text: str) -> Query:
    """Parse a GQL query string into a :class:`Query` AST."""
    return Parser(text).parse()
