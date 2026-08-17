"""The live console page — shared renderer + a ``fetch``-based ``TG`` adapter.

Assembles the self-contained console from :mod:`textgraph.console.renderer` (the CSS,
HTML skeleton, and canvas renderer shared with the offline ``graph.html``) plus a tiny
adapter that wires the renderer's ``TG`` calls to the ``/api`` endpoints. No CDN, no
framework (G2). The offline artifact reuses the identical renderer with an embedded
adapter, so the two surfaces never drift.
"""

from __future__ import annotations

from textgraph.console.renderer import RENDERER_CSS, RENDERER_JS, SKELETON_HTML

# TG adapter: the renderer's data source, backed by the live JSON API. When the server was
# started with --token, the page carries it as ?token=… and every /api call appends it.
_API_ADAPTER = r"""
const _TOK = new URLSearchParams(location.search).get('token');
const _u = (u) => _TOK ? u + (u.includes('?')?'&':'?') + 'token=' + encodeURIComponent(_TOK) : u;
// A per-tab session id so the server can thread multi-turn Ask-dock memory across requests.
const _SID = 'sid-' + Math.random().toString(36).slice(2) + '-' + Date.now();
const TG = {
  graph:  ()    => fetch(_u('/api/graph')).then(r=>r.json()),
  why:    (id)  => fetch(_u('/api/call?'+new URLSearchParams({tool:'why',node:id}))).then(r=>r.json()),
  inspect:(id)  => fetch(_u('/api/inspect?'+new URLSearchParams({node:id}))).then(r=>r.json()),
  path:   (s,t) => fetch(_u('/api/call?'+new URLSearchParams({tool:'path',source:s,target:t}))).then(r=>r.json()),
  search: (q)   => fetch(_u('/api/call?'+new URLSearchParams({tool:'search',query:q,k:'8'}))).then(r=>r.json()),
  chat:   (q,o) => fetch(_u('/api/chat'),{method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(Object.assign({q, session_id:_SID}, o||{}))}).then(r=>r.json()),
  // Fetch the source bytes behind a citation (verified server-side); null when unavailable.
  source: (doc,start,end,hash) => fetch(_u('/api/source?'+new URLSearchParams(
                    Object.assign({doc, start, end}, hash?{hash}:{})))).then(r=>r.json()).catch(()=>null),
  ingest: (files) => { const fd=new FormData(); for(const f of files) fd.append('file', f, f.name);
                    return fetch(_u('/api/ingest'),{method:'POST',body:fd}).then(r=>r.json()); },
  // Analyst annotations (sidecar overlay; never touches graph.json).
  annotations: () => fetch(_u('/api/annotations')).then(r=>r.json()).catch(()=>null),
  annotate: (node,status,note) => fetch(_u('/api/annotate'),{method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({node,status,note})}).then(r=>r.json()),
};
"""

_PAGE = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>TextGraph Console</title>\n<style>"
    + RENDERER_CSS
    + "</style>\n</head>\n<body>\n"
    + SKELETON_HTML
    + "<script>\n"
    + _API_ADAPTER
    + RENDERER_JS
    + "\n</script>\n</body>\n</html>\n"
)


def render_page() -> str:
    """Return the self-contained interactive console HTML (live API adapter)."""
    return _PAGE
