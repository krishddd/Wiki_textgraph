"""graph.html generator (L9) — the offline twin of the live console.

A single self-contained file (no CDN, no external assets, G2) that renders with the
*same* canvas viewer as ``textgraph console`` — nodes coloured by community and sized
by PageRank, the communities sidebar, confidence-tag filter, click-to-inspect (cited
claims + validity windows), path finder, and temporal slider. The only difference is
the data source: the console fetches ``/api``; this file embeds the graph, the
per-node claims, and enough to run search/path **client-side**, so the emailed
artifact is fully interactive with zero server. See
:mod:`textgraph.console.renderer` for the shared renderer.
"""

from __future__ import annotations

import json
from typing import Any

from textgraph.console.renderer import RENDERER_CSS, RENDERER_JS, SKELETON_HTML
from textgraph.core.layout import IngestResult
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.l9_artifacts.analytics_lite import Diagnostics
from textgraph.store.base import Edge, Node

# Offline adapter: the renderer's TG, backed by data embedded in the file. `why` reads
# the precomputed claims map; `path` runs a client-side Dijkstra over the embedded
# edges (weight -log(confidence), like the server's maximum-likelihood path); `search`
# is a name-substring match (chunk passages need the engine, so they are omitted here).
_EMBEDDED_ADAPTER = r"""
const D = window.__TG_DATA__;
function clientPath(s, t){
  const adj = {}; const byId = {}; D.graph.nodes.forEach(n => byId[n.id]=n);
  for(const e of D.graph.edges){ (adj[e.source] ||= []).push([e.target, e]);
    (adj[e.target] ||= []).push([e.source, e]); }
  const dist = {[s]:0}, prev = {}, seen = new Set(); const pq = [[0, s]];
  while(pq.length){ pq.sort((a,b)=>a[0]-b[0]); const [d,u] = pq.shift();
    if(seen.has(u)) continue; seen.add(u); if(u===t) break;
    for(const [v,e] of (adj[u]||[])){ if(seen.has(v)) continue;
      const w = d - Math.log(Math.max(1e-6, Math.min(1, e.confidence)));
      if(w < (dist[v] ?? Infinity)){ dist[v]=w; prev[v]=[u,e]; pq.push([w,v]); } } }
  if(prev[t]===undefined && s!==t) return [];
  const chain=[]; let cur=t; while(cur!==s){ if(!prev[cur]) return []; const [pu,pe]=prev[cur];
    chain.push([cur,pe]); cur=pu; } chain.reverse();
  const nm = id => (byId[id]||{}).name || id;
  let lk = 1; const steps = chain.map(([,e]) => { lk *= Math.max(1e-6, Math.min(1, e.confidence));
    return { subject:nm(e.source), predicate:e.predicate, object:nm(e.target), citations:[] }; });
  return [{ nodes: [nm(s), ...chain.map(([v])=>nm(v))], steps, likelihood: Math.round(lk*1e6)/1e6 }];
}
function clientSearch(q){ const ql=q.toLowerCase();
  return D.graph.nodes.filter(n=>n.name.toLowerCase().includes(ql))
    .map(n=>({ kind:'entity', node_id:n.id, name:n.name, citations:[] })); }
const TG = {
  graph:  async ()    => D.graph,
  why:    async (id)  => ({ claims: D.claims[id] || [] }),
  path:   async (s,t) => ({ paths: clientPath(s,t) }),
  search: async (q)   => ({ routing:'offline', hits: clientSearch(q) }),
};
"""


def build_html(
    *,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
    diag: Diagnostics,
    config_hash: str,
) -> str:
    """Render the self-contained, interactive graph.html artifact."""
    engine = QueryEngine(nodes, edges)
    graph = engine.graph_view()
    # Precompute each shown entity's cited claims for offline click-to-inspect.
    claims: dict[str, list[dict[str, Any]]] = {
        str(n["id"]): engine.why(str(n["id"])).to_dict()["claims"] for n in graph["nodes"]
    }
    data_json = json.dumps(
        {"graph": graph, "claims": claims, "config_hash": config_hash},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>TextGraph &mdash; graph.html ({config_hash[:12]})</title>\n<style>"
        + RENDERER_CSS
        + "</style>\n</head>\n<body>\n"
        + SKELETON_HTML
        + "<script>\nwindow.__TG_DATA__ = "
        + data_json
        + ";\n"
        + _EMBEDDED_ADAPTER
        + RENDERER_JS
        + "\n</script>\n</body>\n</html>\n"
    )
