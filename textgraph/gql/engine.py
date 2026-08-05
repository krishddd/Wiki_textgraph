"""GQL execution engine over the TextGraph property graph (Phase 7).

Runs a parsed :class:`~textgraph.gql.ast.Query` against the very same ``(nodes, edges)``
the L8 ``QueryEngine`` holds — so the standards-based query surface and the typed tools
read one graph, never two. Pure-Python and deterministic (G1): adjacency is iterated in
sorted order, and result rows are stably ordered before ORDER BY / LIMIT apply. It only
*reads* the graph, so G1/G2/G3 are untouched — provenance (``source_spans``) is still
reachable through edge properties.

Supports property-graph pattern matching with quantified (variable-length)
relationships, WHERE filters, RETURN projection with ``count(*)`` aggregation, DISTINCT,
ORDER BY, SKIP, and LIMIT. Path search is loop-free and depth-capped (G7).
"""

from __future__ import annotations

from dataclasses import dataclass
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
from textgraph.gql.parser import parse
from textgraph.store.base import Edge, Node

_MAX_ROWS = 10_000  # runaway guard for variable-length patterns (G7)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]

    def to_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r, strict=True)) for r in self.rows]


class GQLEngine:
    """Execute GQL queries against an in-memory property graph."""

    def __init__(self, nodes: list[Node], edges: list[Edge]) -> None:
        self._node = {n.node_id: n for n in nodes}
        self._edges = sorted(edges, key=lambda e: e.edge_id)
        # Directed adjacency: out[node] and in[node], each sorted by edge id.
        self._out: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}
        for e in self._edges:
            self._out.setdefault(e.subject, []).append(e)
            self._in.setdefault(e.object, []).append(e)

    # -- public -----------------------------------------------------------------

    def query(self, text: str) -> QueryResult:
        return self.run(parse(text))

    def run(self, q: Query) -> QueryResult:
        bindings = self._match(q.pattern)
        if q.where is not None:
            bindings = [b for b in bindings if self._truth(q.where, b)]
        return self._project(q, bindings)

    # -- pattern matching -------------------------------------------------------

    def _match_node(self, np: NodePattern, node_id: str) -> bool:
        node = self._node.get(node_id)
        if node is None:
            return False
        if any(lbl not in node.labels for lbl in np.labels):
            return False
        return all(node.properties.get(k) == v for k, v in np.props)

    def _rel_matches(self, rp: RelPattern, edge: Edge) -> bool:
        return not rp.types or edge.predicate in rp.types

    def _neighbors(self, node_id: str, rp: RelPattern) -> list[tuple[str, Edge]]:
        """(other_node, edge) reachable in one hop under this rel's direction/type."""
        out: list[tuple[str, Edge]] = []
        if rp.direction in ("out", "both"):
            out += [(e.object, e) for e in self._out.get(node_id, []) if self._rel_matches(rp, e)]
        if rp.direction in ("in", "both"):
            out += [(e.subject, e) for e in self._in.get(node_id, []) if self._rel_matches(rp, e)]
        return sorted(out, key=lambda oe: (oe[0], oe[1].edge_id))

    def _expand(
        self, start: str, rp: RelPattern, target: NodePattern, blocked: frozenset[str]
    ) -> list[tuple[str, list[Edge]]]:
        """End nodes reachable from ``start`` in [min,max] hops matching ``target``.

        Loop-free (never revisits a node already on the path or in ``blocked``) and
        depth-bounded, so quantified patterns terminate (G7).
        """
        results: list[tuple[str, list[Edge]]] = []
        # frontier entries: (node, edges_so_far, visited_on_this_path)
        frontier: list[tuple[str, list[Edge], frozenset[str]]] = [(start, [], blocked | {start})]
        for depth in range(1, rp.max_hops + 1):
            nxt: list[tuple[str, list[Edge], frozenset[str]]] = []
            for node, epath, visited in frontier:
                for other, edge in self._neighbors(node, rp):
                    if other in visited:
                        continue
                    new_path = [*epath, edge]
                    if depth >= rp.min_hops and self._match_node(target, other):
                        results.append((other, new_path))
                    nxt.append((other, new_path, visited | {other}))
            frontier = nxt
            if not frontier:
                break
        return results

    def _match(self, pattern: PathPattern) -> list[dict[str, Any]]:
        starts = sorted(nid for nid in self._node if self._match_node(pattern.nodes[0], nid))
        bindings: list[dict[str, Any]] = []
        for s in starts:
            init: dict[str, Any] = {"__path__": [s]}
            if pattern.nodes[0].var:
                init[pattern.nodes[0].var] = s
            self._extend(pattern, 0, s, init, bindings)
            if len(bindings) >= _MAX_ROWS:
                break
        if pattern.path_var:
            for b in bindings:
                b[pattern.path_var] = list(b["__path__"])
        return bindings

    def _extend(
        self,
        pattern: PathPattern,
        i: int,
        current: str,
        partial: dict[str, Any],
        out: list[dict[str, Any]],
    ) -> None:
        if i == len(pattern.rels):
            out.append(partial)
            return
        rp, target = pattern.rels[i], pattern.nodes[i + 1]
        blocked = frozenset(partial["__path__"])
        for end, edges in self._expand(current, rp, target, blocked):
            if len(out) >= _MAX_ROWS:
                return
            nb = dict(partial)
            nb["__path__"] = [*partial["__path__"], end]
            if target.var:
                nb[target.var] = end
            if rp.var:
                nb[rp.var] = edges
            self._extend(pattern, i + 1, end, nb, out)

    # -- expression evaluation --------------------------------------------------

    def _truth(self, clause: Any, b: dict[str, Any]) -> bool:
        if isinstance(clause, BoolOp):
            vals = [self._truth(c, b) for c in clause.clauses]
            return all(vals) if clause.op == "AND" else any(vals)
        if isinstance(clause, Not):
            return not self._truth(clause.clause, b)
        if isinstance(clause, Comparison):
            return self._compare(clause, b)
        raise GQLError("invalid WHERE expression")

    def _compare(self, cmp: Comparison, b: dict[str, Any]) -> bool:
        left = self._eval(cmp.left, b)
        right = self._eval(cmp.right, b)
        op = cmp.op
        if op == "CONTAINS":
            return isinstance(left, str) and isinstance(right, str) and right in left
        if op == "STARTS_WITH":
            return isinstance(left, str) and left.startswith(str(right))
        if op == "ENDS_WITH":
            return isinstance(left, str) and left.endswith(str(right))
        if op == "IN":
            return isinstance(right, list | tuple) and left in right
        if op == "=":
            return bool(left == right)
        if op == "<>":
            return bool(left != right)
        if left is None or right is None:
            return False
        try:
            if op == "<":
                return bool(left < right)
            if op == "<=":
                return bool(left <= right)
            if op == ">":
                return bool(left > right)
            if op == ">=":
                return bool(left >= right)
        except TypeError:
            return False
        raise GQLError(f"unknown operator {op!r}")

    def _eval(self, expr: Any, b: dict[str, Any]) -> Any:
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Property):
            return self._prop(expr.var, expr.key, b)
        if isinstance(expr, FuncCall):
            return self._func(expr, b)
        if isinstance(expr, str):  # bare variable
            return self._prop(expr, "", b)
        raise GQLError("cannot evaluate expression")

    def _prop(self, var: str, key: str, b: dict[str, Any]) -> Any:
        val = b.get(var)
        if isinstance(val, str) and val in self._node:  # node variable
            node = self._node[val]
            if key == "":
                return node.properties.get("name", val)
            return node.properties.get(key)
        if isinstance(val, list) and val and isinstance(val[0], Edge):  # rel variable
            edge = val[-1]
            if key == "":
                return edge.predicate
            if key == "confidence":
                return edge.confidence
            return edge.properties.get(key)
        return None

    def _func(self, fn: FuncCall, b: dict[str, Any]) -> Any:
        if fn.name == "count":
            return None  # aggregation handled in projection
        val = b.get(fn.arg) if fn.arg else None
        if fn.name == "type" and isinstance(val, list) and val:
            return val[-1].predicate if isinstance(val[-1], Edge) else None
        if fn.name == "id":
            return val if isinstance(val, str) else None
        if fn.name == "labels" and isinstance(val, str) and val in self._node:
            return list(self._node[val].labels)
        return None

    # -- projection -------------------------------------------------------------

    def _col_name(self, item: ReturnItem) -> str:
        if item.alias:
            return item.alias
        e = item.expr
        if isinstance(e, str):
            return e
        if isinstance(e, Property):
            return f"{e.var}.{e.key}" if e.key else e.var
        if isinstance(e, FuncCall):
            return f"{e.name}(*)" if e.arg is None else f"{e.name}({e.arg})"
        if isinstance(e, Literal):
            return str(e.value)
        return "col"

    def _project(self, q: Query, bindings: list[dict[str, Any]]) -> QueryResult:
        columns = [self._col_name(it) for it in q.returns]
        has_count = any(
            isinstance(it.expr, FuncCall) and it.expr.name == "count" for it in q.returns
        )

        if has_count:
            rows = self._aggregate(q, bindings)
        else:
            rows = [[self._eval_return(it.expr, b) for it in q.returns] for b in bindings]

        # Deterministic base order, then honour ORDER BY (stable, last key first).
        rows.sort(key=_sort_key)
        for key in reversed(q.order_by):
            idx = self._order_index(q, key)

            def one_col(r: list[Any], _i: int = idx) -> tuple[Any, ...]:
                return _sort_key([r[_i]])

            rows.sort(key=one_col, reverse=key.descending)

        if q.distinct:
            seen: set[str] = set()
            deduped: list[list[Any]] = []
            for r in rows:
                sig = repr(r)
                if sig not in seen:
                    seen.add(sig)
                    deduped.append(r)
            rows = deduped

        if q.skip:
            rows = rows[q.skip :]
        if q.limit is not None:
            rows = rows[: q.limit]
        return QueryResult(columns, rows)

    def _eval_return(self, expr: Any, b: dict[str, Any]) -> Any:
        if isinstance(expr, str):
            val = b.get(expr)
            # A bare path variable resolves to the sequence of node names it traversed.
            if isinstance(val, list) and val and isinstance(val[0], str):
                return [
                    self._node[v].properties.get("name", v) if v in self._node else v for v in val
                ]
        return self._eval(expr, b)

    @staticmethod
    def _is_count(it: ReturnItem) -> bool:
        return isinstance(it.expr, FuncCall) and it.expr.name == "count"

    def _aggregate(self, q: Query, bindings: list[dict[str, Any]]) -> list[list[Any]]:
        group_items = [it for it in q.returns if not self._is_count(it)]
        groups: dict[tuple[Any, ...], int] = {}
        keys_order: list[tuple[Any, ...]] = []
        for b in bindings:
            key = tuple(self._eval_return(it.expr, b) for it in group_items)
            if key not in groups:
                groups[key] = 0
                keys_order.append(key)
            groups[key] += 1
        rows: list[list[Any]] = []
        for key in keys_order:
            row: list[Any] = []
            gi = 0
            for it in q.returns:
                if self._is_count(it):
                    row.append(groups[key])
                else:
                    row.append(key[gi])
                    gi += 1
            rows.append(row)
        return rows

    def _order_index(self, q: Query, key: OrderKey) -> int:
        target = self._col_name(ReturnItem(key.item))
        for i, it in enumerate(q.returns):
            if self._col_name(it) == target:
                return i
        raise GQLError(f"ORDER BY {target!r} is not in the RETURN list")


def _sort_key(row: list[Any]) -> tuple[Any, ...]:
    """Total, type-stable ordering key so mixed None/str/num rows sort deterministically."""
    out: list[tuple[int, Any]] = []
    for v in row:
        if v is None:
            out.append((0, 0))
        elif isinstance(v, bool):
            out.append((1, int(v)))
        elif isinstance(v, int | float):
            out.append((2, v))
        elif isinstance(v, str):
            out.append((3, v))
        else:
            out.append((4, repr(v)))
    return tuple(out)
