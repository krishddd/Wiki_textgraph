"""AST for the TextGraph GQL subset (Phase 7).

A small, typed node set: a query is a MATCH path pattern + optional WHERE, then a
RETURN projection with optional ORDER BY / LIMIT. Enough to express property-graph
pattern matching with quantified (variable-length) relationships — the ISO/IEC 39075
core an agent needs — without pulling in the full language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodePattern:
    var: str | None
    labels: tuple[str, ...] = ()
    props: tuple[tuple[str, Any], ...] = ()  # (key, literal value)


@dataclass(frozen=True)
class RelPattern:
    var: str | None
    types: tuple[str, ...]  # any-of; empty = any predicate
    direction: str  # "out" | "in" | "both"
    min_hops: int = 1
    max_hops: int = 1  # == min for fixed-length; >1 range for quantified paths


@dataclass(frozen=True)
class PathPattern:
    """A chain: node (rel node)*. ``rels[i]`` connects ``nodes[i]`` to ``nodes[i+1]``."""

    nodes: tuple[NodePattern, ...]
    rels: tuple[RelPattern, ...]
    path_var: str | None = None  # `MATCH p = (...)...`


@dataclass(frozen=True)
class Property:
    var: str
    key: str


@dataclass(frozen=True)
class Literal:
    value: Any


@dataclass(frozen=True)
class FuncCall:
    name: str  # "type" | "count" | "labels"
    arg: str | None  # variable name, or None for count(*)


@dataclass(frozen=True)
class Comparison:
    left: Property | FuncCall | Literal
    op: str  # = <> < <= > >= CONTAINS STARTS_WITH ENDS_WITH IN
    right: Literal | Property


@dataclass(frozen=True)
class BoolOp:
    op: str  # AND | OR
    clauses: tuple[Any, ...]


@dataclass(frozen=True)
class Not:
    clause: Any


@dataclass(frozen=True)
class ReturnItem:
    expr: Property | FuncCall | Literal | str  # str = bare variable name
    alias: str | None = None


@dataclass(frozen=True)
class OrderKey:
    item: Property | FuncCall | str
    descending: bool = False


@dataclass(frozen=True)
class Query:
    pattern: PathPattern
    where: Any | None = None
    returns: tuple[ReturnItem, ...] = ()
    distinct: bool = False
    order_by: tuple[OrderKey, ...] = ()
    limit: int | None = None
    skip: int = 0
    variables: tuple[str, ...] = field(default_factory=tuple)
