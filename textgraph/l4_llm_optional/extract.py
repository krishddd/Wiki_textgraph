"""Optional LLM relation extraction (input) — GENERATED-tagged enrichment.

The deterministic rule/GLiNER extractors (L3) favour precision; a general LLM can catch
relations they miss ("X is the notified body for Y", "A amends B"). This pass runs the LLM
over the highest-signal chunks and emits any (subject, predicate, object) triples it finds
as **``GENERATED``** entity nodes + relation edges — quarantined by tag so they can never be
confused with re-verifiable extracted facts (G4). Each GENERATED edge still cites the chunk
it came from (a coarse but real provenance anchor).

Off by default (``Config.llm_extract``). Bounded by ``max_calls`` (G7) and cached by prompt,
so a re-run is free and cost stays auditable. Because it is opt-in, the default build has
zero GENERATED edges and the determinism/provenance gates are untouched.
"""

from __future__ import annotations

import json

from textgraph.core.content_address import hash_text
from textgraph.l1_structure.emit import normalize_key
from textgraph.l4_llm_optional.cache import PromptCache
from textgraph.l4_llm_optional.client import LLMClient, LLMError
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

_SYSTEM = (
    "You extract factual relationships from text. Return ONLY a compact JSON array of "
    '{"subject","predicate","object"} objects. Predicates must be UPPER_SNAKE_CASE verbs '
    "(e.g. REGULATES, AMENDS, DESIGNATES, APPLIES_TO). Use entity names exactly as written. "
    "If there are no clear relationships, return []. No prose, no markdown."
)
# A hard cap so one noisy chunk can't flood the graph (G7).
_MAX_TRIPLES_PER_CHUNK = 12


def _parse_triples(raw: str) -> list[tuple[str, str, str]]:
    """Parse the model's JSON array, tolerating markdown fences and stray prose."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1].removeprefix("json").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        rows = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        s, p, o = row.get("subject"), row.get("predicate"), row.get("object")
        if isinstance(s, str) and isinstance(p, str) and isinstance(o, str) and s and p and o:
            out.append((s.strip(), p.strip().upper().replace(" ", "_"), o.strip()))
    return out[:_MAX_TRIPLES_PER_CHUNK]


def _entity(name: str) -> Node:
    nid = "entity:LLM:" + normalize_key(name)
    return Node(nid, ("Entity",), {"name": name, "etype": "LLM", "source": "llm"})


def extract_llm_relations(
    chunks: list[tuple[str, str, SourceSpan]],
    client: LLMClient,
    cache: PromptCache,
    *,
    max_calls: int = 40,
) -> tuple[list[Node], list[Edge]]:
    """Run the LLM over ``(chunk_id, text, span)`` items; emit GENERATED nodes + edges.

    Deterministic given a fixed model + cache: prompts are cached by content, results are
    sorted, and ids are content-addressed. Stops after ``max_calls`` uncached chunks.
    """
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    calls = 0
    for _cid, text, span in sorted(chunks, key=lambda c: c[0]):
        snippet = text.strip()
        if len(snippet) < 40:
            continue
        key = hash_text(f"llm-extract|{client.model}|{snippet}")
        cached = cache.get(key)
        if cached is None:
            if calls >= max_calls:
                break
            calls += 1
            try:
                cached = client.complete(_SYSTEM, snippet[:2000])
            except LLMError:
                continue
            cache.put(key, cached)
        for subj, pred, obj in _parse_triples(cached):
            sn, on = _entity(subj), _entity(obj)
            nodes.setdefault(sn.node_id, sn)
            nodes.setdefault(on.node_id, on)
            eid = "edge:" + hash_text(f"{sn.node_id}|{pred}|{on.node_id}|{span.doc_id}")
            edges.setdefault(
                eid,
                Edge(
                    edge_id=eid,
                    subject=sn.node_id,
                    predicate=pred,
                    object=on.node_id,
                    tag=ConfidenceTag.GENERATED,
                    confidence=0.5,
                    evidence_count=1,
                    source_spans=(span,),
                    properties={"source": "llm"},
                ),
            )
    nodes_out = sorted(nodes.values(), key=lambda n: n.node_id)
    edges_out = sorted(edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out
