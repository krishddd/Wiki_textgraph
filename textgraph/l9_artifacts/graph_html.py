"""graph.html generator (L9, §12.2).

A single self-contained file — no CDN, no external assets (G2). Layout is
precomputed server-side and deterministic (nodes placed on per-label rings, sorted
by id), so the file is byte-stable. Renders with inline SVG + vanilla JS: filter by
confidence tag, click a node to see its edges, click an edge to see the exact cited
source span. The full WebGL/sigma.js viewer is Phase 6; this is the Phase-1 spine.
"""

from __future__ import annotations

import json
import math
from typing import Any

from textgraph import __version__
from textgraph.core.layout import IngestResult
from textgraph.l1_structure.emit import sanitize
from textgraph.l9_artifacts.analytics_lite import Diagnostics
from textgraph.store.base import Edge, Node

_CANVAS = 1000.0


def _layout(nodes: list[Node], by_label: dict[str, list[Node]]) -> dict[str, tuple[float, float]]:
    """Deterministic per-label concentric-ring layout."""
    labels = sorted(by_label)
    pos: dict[str, tuple[float, float]] = {}
    center = _CANVAS / 2
    for ring, label in enumerate(labels):
        members = sorted(by_label[label], key=lambda n: n.node_id)
        radius = 70 + ring * (center - 90) / max(1, len(labels))
        count = len(members)
        for i, n in enumerate(members):
            angle = 2 * math.pi * i / max(1, count)
            pos[n.node_id] = (
                round(center + radius * math.cos(angle), 2),
                round(center + radius * math.sin(angle), 2),
            )
    return pos


def _edge_snippet(ir_by_doc: dict[str, IngestResult], edge: Edge) -> str:
    if not edge.source_spans:
        return ""
    span = edge.source_spans[0]
    ir = ir_by_doc.get(span.doc_id)
    if ir is None:
        return ""
    raw = ir.raw[span.start : span.end]
    text = raw.decode("utf-8", errors="replace")
    return sanitize(text)[:240]


def build_html(
    *,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
    diag: Diagnostics,
    config_hash: str,
) -> str:
    pos = _layout(nodes, diag.by_label)
    ir_by_doc = {ir.doc_id: ir for ir in results}
    labels = sorted(diag.by_label)
    palette = [
        "#2f5d8a",
        "#3f7d4e",
        "#8a5a2f",
        "#7a4fa0",
        "#a0402f",
        "#2f8a86",
        "#8a2f6b",
        "#57606a",
        "#8a7a2f",
        "#402f8a",
    ]
    color = {label: palette[i % len(palette)] for i, label in enumerate(labels)}

    node_data: list[dict[str, Any]] = [
        {
            "id": n.node_id,
            "label": n.labels[0] if n.labels else "?",
            "name": sanitize(str(n.properties.get("name", n.node_id)))[:80],
            "x": pos[n.node_id][0],
            "y": pos[n.node_id][1],
            "deg": diag.degree.get(n.node_id, 0),
        }
        for n in nodes
        if n.node_id in pos
    ]
    edge_data: list[dict[str, Any]] = [
        {
            "s": e.subject,
            "o": e.object,
            "pred": e.predicate,
            "tag": str(e.tag),
            "cite": (
                f"{ir_by_doc[e.source_spans[0].doc_id].source_name}"
                f"[{e.source_spans[0].start}:{e.source_spans[0].end}]"
                if e.source_spans and e.source_spans[0].doc_id in ir_by_doc
                else ""
            ),
            "snippet": _edge_snippet(ir_by_doc, e),
        }
        for e in edges
    ]
    data_json = json.dumps(
        {"nodes": node_data, "edges": edge_data, "color": color},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return _TEMPLATE.format(
        version=__version__,
        config_hash=config_hash,
        node_count=len(node_data),
        edge_count=len(edge_data),
        data_json=data_json,
        canvas=int(_CANVAS),
    )


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TextGraph — graph.html</title>
<style>
:root {{ color-scheme: light dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font:14px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:#f5f3ec; color:#1f1f1f; }}
@media (prefers-color-scheme: dark) {{ body {{ background:#161513; color:#e8e6df; }} }}
header {{ padding:10px 16px; border-bottom:1px solid #8883; display:flex; gap:16px;
  align-items:center; flex-wrap:wrap; }}
header b {{ font-size:16px; }}
.tag {{ font-size:11px; padding:2px 6px; border:1px solid #8886; border-radius:4px; }}
#wrap {{ display:flex; height:calc(100vh - 52px); }}
#stage {{ flex:1; overflow:hidden; }}
#side {{ width:340px; border-left:1px solid #8883; padding:12px; overflow:auto; }}
svg {{ width:100%; height:100%; }}
circle {{ cursor:pointer; }}
line {{ stroke:#8886; stroke-width:1; }}
.hi {{ stroke:#d08a2f; stroke-width:2.5; }}
.snippet {{ white-space:pre-wrap; background:#8881; padding:8px; border-radius:4px;
  margin-top:6px; font-size:12px; }}
label.f {{ display:inline-flex; align-items:center; gap:4px; margin-right:8px; }}
h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.05em; opacity:.7; }}
</style></head>
<body>
<header>
  <b>TextGraph</b>
  <span class="tag">v{version}</span>
  <span class="tag">{node_count} nodes</span>
  <span class="tag">{edge_count} edges</span>
  <span class="tag">config {config_hash:.12}…</span>
  <span id="filters"></span>
</header>
<div id="wrap">
  <div id="stage"><svg id="svg" viewBox="0 0 {canvas} {canvas}" preserveAspectRatio="xMidYMid meet"></svg></div>
  <div id="side"><h2>Click a node</h2><div id="detail">Filter by type above; click any node to see its edges and cited source spans.</div></div>
</div>
<script>
const DATA = {data_json};
const svg = document.getElementById('svg');
const NS = 'http://www.w3.org/2000/svg';
const byId = Object.fromEntries(DATA.nodes.map(n => [n.id, n]));
const active = new Set(DATA.nodes.map(n => n.label));
const adj = {{}};
DATA.edges.forEach(e => {{ (adj[e.s] ||= []).push(e); (adj[e.o] ||= []).push(e); }});

function esc(s) {{ return (s||'').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}

function draw() {{
  svg.innerHTML = '';
  const shown = new Set(DATA.nodes.filter(n => active.has(n.label)).map(n => n.id));
  for (const e of DATA.edges) {{
    if (!shown.has(e.s) || !shown.has(e.o)) continue;
    const a = byId[e.s], b = byId[e.o]; if (!a || !b) continue;
    const l = document.createElementNS(NS,'line');
    l.setAttribute('x1',a.x); l.setAttribute('y1',a.y);
    l.setAttribute('x2',b.x); l.setAttribute('y2',b.y);
    svg.appendChild(l);
  }}
  for (const n of DATA.nodes) {{
    if (!active.has(n.label)) continue;
    const c = document.createElementNS(NS,'circle');
    c.setAttribute('cx',n.x); c.setAttribute('cy',n.y);
    c.setAttribute('r', 4 + Math.min(8, n.deg));
    c.setAttribute('fill', DATA.color[n.label] || '#888');
    c.setAttribute('title', n.name);
    c.onclick = () => select(n.id);
    svg.appendChild(c);
  }}
}}

function select(id) {{
  const n = byId[id];
  const edges = (adj[id]||[]);
  let html = '<h2>'+esc(n.label)+'</h2><b>'+esc(n.name)+'</b>'
    + '<div style="opacity:.6;font-size:11px">'+esc(n.id)+'</div>'
    + '<h2 style="margin-top:12px">'+edges.length+' edge(s)</h2>';
  for (const e of edges) {{
    const other = e.s===id ? e.o : e.s;
    const dir = e.s===id ? '→' : '←';
    html += '<div style="margin:8px 0;border-top:1px solid #8883;padding-top:6px">'
      + '<span class="tag">'+esc(e.tag)+'</span> <b>'+esc(e.pred)+'</b> '+dir+' '
      + esc((byId[other]||{{}}).name || other)
      + (e.cite ? '<div style="opacity:.6;font-size:11px">'+esc(e.cite)+'</div>' : '')
      + (e.snippet ? '<div class="snippet">'+esc(e.snippet)+'</div>' : '')
      + '</div>';
  }}
  document.getElementById('detail').innerHTML = html;
}}

const fbox = document.getElementById('filters');
[...new Set(DATA.nodes.map(n=>n.label))].sort().forEach(label => {{
  const id='f_'+label;
  const wrap=document.createElement('label'); wrap.className='f';
  wrap.innerHTML='<input type="checkbox" id="'+id+'" checked> '
    +'<span style="color:'+(DATA.color[label]||'#888')+'">■</span>'+esc(label);
  wrap.querySelector('input').onchange = ev => {{
    ev.target.checked ? active.add(label) : active.delete(label); draw();
  }};
  fbox.appendChild(wrap);
}});
draw();
</script>
</body></html>
"""
