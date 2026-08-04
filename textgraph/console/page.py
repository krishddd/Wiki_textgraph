"""The self-contained console HTML page (inline CSS/JS, zero external requests, G2).

A single string: a query console that calls ``/api/call`` and renders the typed,
cited result objects. No CDN, no build step — mirrors the self-contained ``graph.html``
viewer. Theme-aware (respects the OS light/dark preference).
"""

from __future__ import annotations

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TextGraph Console</title>
<style>
  :root { color-scheme: light dark; --bg:#fff; --fg:#111; --mut:#666; --line:#e2e2e2;
          --acc:#2563eb; --card:#f7f7f8; --code:#f0f0f2; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1115; --fg:#e6e6e6; --mut:#9aa0a6; --line:#2a2d34;
            --acc:#7aa2ff; --card:#171a21; --code:#1c2027; } }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex;
           align-items:baseline; gap:12px; }
  header h1 { font-size:16px; margin:0; }
  header span { color:var(--mut); font-size:12px; }
  main { max-width:960px; margin:0 auto; padding:20px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
  select, input, button { font:inherit; padding:7px 10px; border:1px solid var(--line);
           border-radius:7px; background:var(--bg); color:var(--fg); }
  input { flex:1; min-width:160px; }
  button { background:var(--acc); color:#fff; border:none; cursor:pointer; }
  button:hover { opacity:.9; }
  .hint { color:var(--mut); font-size:12px; margin:2px 0 14px; }
  .hit { background:var(--card); border:1px solid var(--line); border-radius:9px;
         padding:10px 12px; margin-bottom:9px; }
  .hit .top { display:flex; justify-content:space-between; gap:10px; }
  .kind { color:var(--mut); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .name { font-weight:600; }
  .snip { color:var(--fg); margin-top:5px; white-space:pre-wrap; }
  .cite { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px;
          color:var(--mut); margin-top:6px; word-break:break-all; }
  .sup { color:#c0392b; font-weight:600; }
  pre { background:var(--code); padding:12px; border-radius:8px; overflow:auto; font-size:12px; }
  .err { color:#c0392b; }
</style>
</head>
<body>
<header><h1>TextGraph Console</h1><span>local &middot; read-only &middot; every row cited</span></header>
<main>
  <div class="row">
    <select id="tool">
      <option value="search">search</option>
      <option value="neighbors">neighbors</option>
      <option value="path">path</option>
      <option value="why">why</option>
      <option value="timeline">timeline</option>
      <option value="contradictions">contradictions</option>
      <option value="communities">communities</option>
      <option value="stats">stats</option>
    </select>
    <input id="a" placeholder="query / entity">
    <input id="b" placeholder="target (path only)" style="display:none">
    <button id="run">Run</button>
  </div>
  <div class="hint" id="hint">Hybrid BM25 + graph search. Type a question and hit Run.</div>
  <div id="out"></div>
</main>
<script>
const $ = s => document.querySelector(s);
const tool = $('#tool'), a = $('#a'), b = $('#b'), out = $('#out'), hint = $('#hint');
const HINTS = {
  search:'Hybrid BM25 + graph search. Type a question.',
  neighbors:'1-hop typed neighbors of an entity (id or name).',
  path:'Maximum-likelihood path between two entities.',
  why:'Cited claims explaining an entity, with validity windows.',
  timeline:'Claims about an entity ordered by time.',
  contradictions:'Opposite-polarity claim pairs.',
  communities:'Detected communities with auto-labels.',
  stats:'Graph counts and most central entities.'};
const NEEDS = {search:1, neighbors:1, path:2, why:1, timeline:1, contradictions:0,
  communities:0, stats:0};
function sync(){ const n = NEEDS[tool.value]; a.style.display = n>=1?'':'none';
  b.style.display = n>=2?'':'none'; hint.textContent = HINTS[tool.value]; }
tool.onchange = sync; sync();
function esc(s){ return String(s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function cites(cs){ return (cs||[]).map(c=>`[${c.doc_id.slice(0,20)}…:${c.start}-${c.end}]`).join(' '); }
function render(d){
  if(d.error){ out.innerHTML = `<div class="err">${esc(d.error)}</div>`; return; }
  let h = '';
  if(d.tool==='search') for(const x of d.hits) h += hit(x.kind, x.name, x.snippet, x.citations, x.score);
  else if(d.tool==='neighbors') for(const x of d.neighbors) h += hit(x.direction, `${x.predicate} → ${x.other_name}`, '', x.citations, x.confidence);
  else if(d.tool==='path'){ if(!d.paths.length) h='<div class="hint">no path found</div>';
    for(const p of d.paths){ h += `<div class="hit"><div class="name">${esc(p.nodes.join(' → '))} <span class="kind">likelihood ${p.likelihood}</span></div>`;
      for(const s of p.steps) h += `<div class="snip">${esc(s.subject)} —${esc(s.predicate)}→ ${esc(s.object)} <span class="cite">${cites(s.citations)}</span></div>`; h += '</div>'; } }
  else if(d.tool==='why'||d.tool==='timeline'){ const cl = d.claims||d.events;
    for(const c of cl){ const w = c.t_valid ? (c.t_invalid?`<span class="sup">valid [${c.t_valid}, ${c.t_invalid}) superseded</span>`:`valid [${c.t_valid}, now)`):'';
      h += hit(c.status||c.polarity, `${esc(c.subject)} —${esc(c.predicate)}→ ${esc(c.object)}`, w, c.citations, c.confidence); } }
  else if(d.tool==='contradictions'){ if(!d.pairs.length) h='<div class="hint">no contradictions</div>';
    for(const p of d.pairs) h += `<div class="hit"><div class="name">${esc(p.claim_a.subject)} —${esc(p.claim_a.predicate)}→ ${esc(p.claim_a.object)}</div><div class="snip">[${p.claim_a.polarity}] vs [${p.claim_b.polarity}]</div></div>`; }
  else if(d.tool==='communities') for(const c of d.communities) h += hit('#'+c.community_id, c.label, c.members.join(', '), [], c.size);
  else h = `<pre>${esc(JSON.stringify(d, null, 2))}</pre>`;
  out.innerHTML = h || '<div class="hint">no results</div>';
}
function hit(kind, name, snip, cs, score){
  return `<div class="hit"><div class="top"><span class="name">${esc(name)}</span><span class="kind">${esc(kind)}${score!==undefined?' · '+score:''}</span></div>`+
    (snip?`<div class="snip">${snip.startsWith('<')?snip:esc(snip)}</div>`:'')+
    (cs&&cs.length?`<div class="cite">${cites(cs)}</div>`:'')+`</div>`; }
async function run(){
  const p = new URLSearchParams({tool: tool.value});
  const n = NEEDS[tool.value];
  if(n>=1) p.set(tool.value==='search'?'query':(tool.value==='path'?'source':'node'), a.value);
  if(n>=2) p.set('target', b.value);
  out.innerHTML = '<div class="hint">…</div>';
  try { render(await (await fetch('/api/call?'+p)).json()); }
  catch(e){ out.innerHTML = `<div class="err">${esc(e)}</div>`; }
}
$('#run').onclick = run;
a.addEventListener('keydown', e => { if(e.key==='Enter') run(); });
b.addEventListener('keydown', e => { if(e.key==='Enter') run(); });
</script>
</body>
</html>
"""


def render_page() -> str:
    """Return the self-contained console HTML."""
    return _PAGE
