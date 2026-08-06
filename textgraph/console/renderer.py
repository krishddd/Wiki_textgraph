"""Shared interactive-graph renderer — one canvas viewer, two surfaces (G2, G6).

The live ``textgraph console`` and the offline ``graph.html`` artifact render with the
*same* CSS, HTML skeleton, and JavaScript from this module, so they look and behave
identically. The renderer talks to a small global ``TG`` adapter (``graph`` / ``why`` /
``path`` / ``search``); each surface supplies its own adapter — the console over
``fetch``, ``graph.html`` over data embedded in the file — so the drawing/interaction
code never forks. Hand-rolled canvas, zero third-party JS, no CDN.

The layout is a clean, spacious dashboard: a top app bar (brand + search + actions), a
row of stat cards that surface the graph's headline data points, the force-laid graph on
a canvas card, and a right inspector with the community roster, a top-entities list, the
confidence-tag filter, and the cited-claim detail for whatever is selected. It is
theme-aware (light by default, dark via the system preference or the in-app toggle).
"""

from __future__ import annotations

RENDERER_CSS = """
  :root {
    --bg:#f4f5f8; --panel:#ffffff; --card:#ffffff; --line:#e5e8ef; --line2:#eef1f6;
    --fg:#1a1f2b; --fg2:#5a6474; --mut:#8b94a3; --acc:#4f6bff; --acc-soft:#eef1ff;
    --sup:#e0555b; --shadow:0 1px 2px rgba(20,30,60,.06),0 6px 20px rgba(20,30,60,.06);
    --edge-rgb:90,100,120; --canvas-label:#3a4252;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0b0e14; --panel:#11151d; --card:#141922; --line:#232a37; --line2:#1b212c;
      --fg:#e9ecf3; --fg2:#aeb6c4; --mut:#7c8698; --acc:#6d86ff; --acc-soft:#1b2138;
      --sup:#f0666c; --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);
      --edge-rgb:140,150,172; --canvas-label:#c7cede; }
  }
  :root[data-theme="light"] { --bg:#f4f5f8; --panel:#ffffff; --card:#ffffff; --line:#e5e8ef;
    --line2:#eef1f6; --fg:#1a1f2b; --fg2:#5a6474; --mut:#8b94a3; --acc:#4f6bff;
    --acc-soft:#eef1ff; --sup:#e0555b; --shadow:0 1px 2px rgba(20,30,60,.06),0 6px 20px rgba(20,30,60,.06);
    --edge-rgb:90,100,120; --canvas-label:#3a4252; }
  :root[data-theme="dark"] { --bg:#0b0e14; --panel:#11151d; --card:#141922; --line:#232a37;
    --line2:#1b212c; --fg:#e9ecf3; --fg2:#aeb6c4; --mut:#7c8698; --acc:#6d86ff;
    --acc-soft:#1b2138; --sup:#f0666c; --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);
    --edge-rgb:140,150,172; --canvas-label:#c7cede; }

  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg);
    font:14px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    overflow:hidden; -webkit-font-smoothing:antialiased; }

  #app { display:grid; grid-template-rows:auto 1fr; height:100vh; }

  /* App bar */
  header { display:flex; align-items:center; gap:14px; padding:14px 20px;
    background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:center; gap:10px; font-weight:650; letter-spacing:-.01em;
    font-size:15px; white-space:nowrap; }
  .brand .mark { width:22px; height:22px; border-radius:7px;
    background:linear-gradient(135deg,var(--acc),#8a6bff); box-shadow:var(--shadow); }
  .search { position:relative; flex:1; max-width:560px; }
  .search input { width:100%; padding:10px 14px 10px 38px; border-radius:11px;
    border:1px solid var(--line); background:var(--bg); color:var(--fg); font-size:14px;
    outline:none; transition:border-color .15s,box-shadow .15s; }
  .search input:focus { border-color:var(--acc); box-shadow:0 0 0 3px var(--acc-soft); }
  .search svg { position:absolute; left:12px; top:50%; transform:translateY(-50%);
    width:16px; height:16px; color:var(--mut); }
  .spacer { flex:1; }
  .btn { padding:9px 14px; border-radius:11px; border:1px solid var(--line);
    background:var(--card); color:var(--fg); cursor:pointer; font-size:13px; font-weight:550;
    white-space:nowrap; transition:background .15s,border-color .15s,color .15s; }
  .btn:hover { border-color:var(--acc); color:var(--acc); }
  .btn.on { background:var(--acc); color:#fff; border-color:var(--acc); }
  .icon-btn { padding:9px 11px; }

  /* Body: canvas column + inspector */
  #body { display:grid; grid-template-columns:1fr 340px; min-height:0; }
  #main { display:flex; flex-direction:column; min-width:0; padding:18px 18px 0; gap:16px; }

  /* Stat cards — the headline data points */
  #stats { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:14px 16px; box-shadow:var(--shadow); min-width:0; }
  .stat .k { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--mut);
    display:flex; align-items:center; gap:7px; }
  .stat .k .swatch { width:9px; height:9px; border-radius:3px; }
  .stat .v { font-size:26px; font-weight:700; letter-spacing:-.02em; margin-top:4px;
    font-variant-numeric:tabular-nums; }
  .stat .s { font-size:12px; color:var(--fg2); margin-top:2px; }

  /* Canvas card */
  #stage { position:relative; flex:1; min-height:0; background:var(--card);
    border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow);
    overflow:hidden; }
  canvas { display:block; width:100%; height:100%; cursor:grab; }
  canvas.grabbing { cursor:grabbing; }
  #note { position:absolute; bottom:12px; left:16px; color:var(--mut); font-size:12px; z-index:5;
    background:color-mix(in srgb,var(--card) 82%,transparent); padding:3px 9px; border-radius:8px; }
  #time { position:absolute; bottom:12px; left:50%; transform:translateX(-50%); z-index:5;
    display:none; align-items:center; gap:12px; padding:9px 16px; border-radius:12px;
    background:var(--panel); border:1px solid var(--line); box-shadow:var(--shadow); }
  #time input[type=range] { width:220px; accent-color:var(--acc); }
  #time .lbl { font-variant-numeric:tabular-nums; min-width:82px; text-align:center; font-size:13px; }
  #time .lbl.sup { color:var(--sup); }
  #tip { position:absolute; pointer-events:none; padding:6px 10px; background:var(--panel);
    border:1px solid var(--line); border-radius:9px; font-size:12px; display:none; z-index:6;
    box-shadow:var(--shadow); max-width:260px; }

  /* Inspector */
  aside { background:var(--panel); border-left:1px solid var(--line); overflow-y:auto; }
  aside h2 { font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:var(--mut);
    margin:18px 18px 10px; font-weight:600; }
  .crow { display:flex; align-items:center; gap:9px; padding:6px 18px; cursor:pointer;
    border-radius:9px; margin:0 8px; transition:background .12s; }
  .crow:hover { background:var(--line2); }
  .crow .dot { width:11px; height:11px; border-radius:4px; flex:none; }
  .crow .lbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .crow .ct { color:var(--mut); font-variant-numeric:tabular-nums; font-size:12px; }
  .trow { display:flex; align-items:baseline; gap:9px; padding:6px 18px; cursor:pointer;
    border-radius:9px; margin:0 8px; transition:background .12s; }
  .trow:hover { background:var(--line2); }
  .trow .rank { color:var(--mut); font-size:12px; width:16px; font-variant-numeric:tabular-nums; }
  .trow .lbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .trow .bar { height:5px; border-radius:3px; background:var(--acc); flex:none; opacity:.85; }
  .tags { display:flex; flex-wrap:wrap; gap:7px; padding:0 18px 10px; }
  .tag { font-size:11.5px; padding:4px 11px; border-radius:20px; border:1px solid var(--line);
    cursor:pointer; user-select:none; transition:opacity .12s; }
  .tag.off { opacity:.4; text-decoration:line-through; }
  #detail { padding:12px 18px 28px; border-top:1px solid var(--line); margin-top:10px; }
  #detail .title { font-weight:650; font-size:15px; margin-bottom:2px; letter-spacing:-.01em; }
  #detail .sub { color:var(--fg2); font-size:12px; margin-bottom:10px; }
  .fact { border-left:2px solid var(--line); padding:6px 0 6px 10px; margin:8px 0; font-size:13px; }
  .fact .cite { font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:var(--mut);
    word-break:break-all; margin-top:3px; }
  .fact.sup { border-color:var(--sup); }
  .win { color:var(--mut); font-size:11.5px; } .win.sup { color:var(--sup); }
  .empty { color:var(--mut); padding:10px 0; }

  /* Ask — the grounded chat dock */
  #ask { display:flex; flex-direction:column; height:280px; margin-bottom:18px;
    background:var(--card); border:1px solid var(--line); border-radius:16px;
    box-shadow:var(--shadow); overflow:hidden; transition:height .18s ease; }
  #ask.collapsed { height:46px; }
  #askhead { display:flex; align-items:center; gap:8px; padding:11px 16px;
    border-bottom:1px solid var(--line); cursor:pointer; user-select:none; font-weight:600;
    font-size:13px; }
  #askhead .dot { width:8px; height:8px; border-radius:50%; background:var(--acc); }
  #askhead .chev { margin-left:auto; color:var(--mut); transition:transform .18s; }
  #ask.collapsed #askhead .chev { transform:rotate(180deg); }
  #ask.collapsed #asklog, #ask.collapsed #askbar { display:none; }
  #asklog { flex:1; overflow-y:auto; padding:14px 16px; display:flex; flex-direction:column;
    gap:11px; }
  #asklog .welcome { color:var(--mut); font-size:13px; margin:auto; text-align:center;
    max-width:420px; line-height:1.6; }
  .msg { max-width:88%; padding:9px 13px; border-radius:13px; font-size:13.5px; line-height:1.5;
    word-wrap:break-word; }
  .msg.user { align-self:flex-end; background:var(--acc); color:#fff; border-bottom-right-radius:4px; }
  .msg.bot { align-self:flex-start; background:var(--bg); border:1px solid var(--line);
    border-bottom-left-radius:4px; }
  .msg .tooltag { font-size:10px; letter-spacing:.06em; text-transform:uppercase; color:var(--mut);
    margin-bottom:4px; }
  .msg .cites { margin-top:7px; display:flex; flex-wrap:wrap; gap:5px; }
  .cite-chip { font-family:ui-monospace,Menlo,monospace; font-size:10px; padding:2px 7px;
    border-radius:6px; background:var(--acc-soft); color:var(--acc); }
  .chain { margin-top:8px; }
  .chain summary { cursor:pointer; color:var(--mut); font-size:12px; }
  .chain .step { font-size:12px; margin:5px 0; padding-left:9px; border-left:2px solid var(--line);
    color:var(--fg2); }
  .chain .step b { color:var(--fg); font-weight:600; }
  #askbar { display:flex; gap:8px; padding:11px 13px; border-top:1px solid var(--line);
    align-items:center; }
  #attach { display:none; cursor:pointer; font-size:17px; line-height:1; padding:7px 9px;
    border-radius:9px; border:1px solid var(--line); background:var(--bg); user-select:none; }
  #attach:hover { border-color:var(--acc); }
  #askbar select { padding:8px 9px; border-radius:9px; border:1px solid var(--line);
    background:var(--bg); color:var(--fg); font-size:12.5px; }
  #askq { flex:1; padding:9px 13px; border-radius:10px; border:1px solid var(--line);
    background:var(--bg); color:var(--fg); font-size:13.5px; outline:none; }
  #askq:focus { border-color:var(--acc); box-shadow:0 0 0 3px var(--acc-soft); }
  #asksend { padding:9px 16px; border-radius:10px; border:none; background:var(--acc); color:#fff;
    font-weight:600; font-size:13px; cursor:pointer; }
  #asksend:disabled { opacity:.5; cursor:default; }

  @media (max-width:920px) {
    #body { grid-template-columns:1fr; }
    aside { display:none; }
    #stats { grid-template-columns:repeat(2,1fr); }
  }
"""

SKELETON_HTML = """
<div id="app">
  <header>
    <div class="brand"><span class="mark"></span>TextGraph</div>
    <div class="search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path></svg>
      <input id="q" placeholder="Search entities &amp; passages…  (Enter)">
    </div>
    <div class="spacer"></div>
    <button class="btn" id="pathbtn" title="click two nodes to trace a path">Path</button>
    <button class="btn" id="fit" title="fit graph to screen">Fit</button>
    <button class="btn icon-btn" id="theme" title="toggle light / dark">&#9681;</button>
  </header>
  <div id="body">
    <div id="main">
      <div id="stats"></div>
      <div id="stage">
        <canvas id="c"></canvas>
        <div id="tip"></div>
        <div id="note"></div>
        <div id="time">
          <span>&#9201;</span>
          <input type="range" id="tslider" min="0" value="0" step="1">
          <span class="lbl" id="tlabel">all time</span>
        </div>
      </div>
      <div id="ask">
        <div id="askhead"><span class="dot"></span>Ask the graph<span class="chev">&#9662;</span></div>
        <div id="asklog"><div class="welcome">Ask a question in plain English — e.g. <em>&ldquo;how is Acme Corp connected to Delta Trust?&rdquo;</em> or <em>&ldquo;why does Acme matter?&rdquo;</em>. Answers are grounded in the graph, cited to the source, and highlighted on the canvas above.</div></div>
        <div id="askbar">
          <label id="attach" title="attach files to the graph">&#128206;<input type="file" id="attachin" multiple hidden></label>
          <select id="asktool" title="which tool to use">
            <option value="auto">Auto</option>
            <option value="reason">Reason</option>
            <option value="search">Search</option>
            <option value="path">Path</option>
            <option value="why">Why</option>
            <option value="neighbors">Neighbors</option>
            <option value="timeline">Timeline</option>
            <option value="contradictions">Contradictions</option>
            <option value="communities">Communities</option>
            <option value="stats">Stats</option>
            <option value="gql">GQL</option>
          </select>
          <input id="askq" placeholder="Ask a question…  (Enter)" autocomplete="off">
          <button id="asksend">Ask</button>
        </div>
      </div>
    </div>
    <aside>
      <h2>Communities</h2>
      <div class="crow" style="font-weight:600"><input type="checkbox" id="all" checked>
        <span class="lbl">Select all</span></div>
      <div id="comms"></div>
      <h2>Top entities &middot; PageRank</h2>
      <div id="tops"></div>
      <h2>Confidence tags</h2>
      <div class="tags" id="tags"></div>
      <div id="detail"><div class="empty">Click a node to inspect its cited claims.</div></div>
    </aside>
  </div>
</div>
"""

# The renderer. Depends on a global async `TG` adapter: TG.graph(), TG.why(id),
# TG.path(source, target), TG.search(q). Each surface defines TG before this runs.
RENDERER_JS = r"""
const PALETTE = ['#4f6bff','#f59e42','#e0555b','#2bb7a3','#7bc043','#f2c14e','#c98bd6',
  '#ef8fb4','#9b7b5b','#8a94a6','#3aa0ff','#ff7a59','#59c1ff','#b08cff'];
const TAGS = ['STRUCTURAL','EXTRACTED','INFERRED','GENERATED'];
const S = { g:null, scale:1, tx:0, ty:0, hidden:new Set(), tags:new Set(TAGS),
  q:'', match:null, sel:null, pathMode:false, pick:[], pathEdges:new Set(), date:null };
const c = document.getElementById('c'), ctx = c.getContext('2d');
const tip = document.getElementById('tip'), note = document.getElementById('note');
const color = cid => PALETTE[((cid%PALETTE.length)+PALETTE.length)%PALETTE.length];
function esc(s){ return String(s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }
function cssv(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function resize(){ const r = c.getBoundingClientRect(), d = devicePixelRatio||1;
  c.width = r.width*d; c.height = r.height*d; ctx.setTransform(d,0,0,d,0,0); draw(); }
function fit(){ if(!S.g||!S.g.nodes.length) return;
  let xs=S.g.nodes.map(n=>n.x), ys=S.g.nodes.map(n=>n.y);
  const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
  const r=c.getBoundingClientRect(), pad=70;
  const sx=(r.width-2*pad)/((maxx-minx)||1), sy=(r.height-2*pad)/((maxy-miny)||1);
  S.scale=Math.min(sx,sy,3); S.tx=r.width/2-((minx+maxx)/2)*S.scale;
  S.ty=r.height/2-((miny+maxy)/2)*S.scale; draw(); }
const SX = n => n.x*S.scale + S.tx, SY = n => n.y*S.scale + S.ty;
const rad = n => 3.5 + Math.sqrt(n.pagerank)*46;
function visible(n){ return !S.hidden.has(n.community); }
function dim(n){ return (S.match && !S.match.has(n.id)); }
function edgeActive(e){ if(S.date===null) return true;
  if(e.t_valid && e.t_valid > S.date) return false;
  if(e.t_invalid && S.date >= e.t_invalid) return false;
  return true; }

function draw(){
  const r = c.getBoundingClientRect(); ctx.clearRect(0,0,r.width,r.height);
  const byId = S.byId; const ergb = cssv('--edge-rgb')||'120,130,150';
  const labelColor = cssv('--canvas-label')||'#334'; const accent = cssv('--acc')||'#4f6bff';
  const selColor = cssv('--fg')||'#111';
  for(const e of S.g.edges){
    if(!S.tags.has(e.tag)) continue;
    const a=byId[e.source], b=byId[e.target]; if(!a||!b||!visible(a)||!visible(b)) continue;
    const inPath = S.pathEdges.has(e.source+'>'+e.target)||S.pathEdges.has(e.target+'>'+e.source);
    const active = edgeActive(e);
    const alpha = (dim(a)||dim(b)) ? 0.05 : (active ? 0.22 : 0.05);
    ctx.beginPath(); ctx.moveTo(SX(a),SY(a)); ctx.lineTo(SX(b),SY(b));
    ctx.strokeStyle = inPath?accent:('rgba('+ergb+','+alpha+')');
    ctx.lineWidth = inPath?2.5:1; ctx.stroke();
  }
  for(const n of S.g.nodes){
    if(!visible(n)) continue;
    const x=SX(n),y=SY(n),rr=rad(n); const d=dim(n);
    ctx.beginPath(); ctx.arc(x,y,rr,0,7); ctx.fillStyle=color(n.community);
    ctx.globalAlpha = d?0.14:1; ctx.fill();
    if(S.sel&&S.sel.id===n.id){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle=selColor; ctx.stroke(); }
    if(S.pick.includes(n.id)){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle=accent; ctx.stroke(); }
    ctx.globalAlpha=1;
    if(rr*S.scale>6 && !d){ ctx.fillStyle=labelColor; ctx.font='11px ui-sans-serif,system-ui';
      ctx.fillText(n.name.slice(0,24), x+rr+4, y+3.5); }
  }
  note.textContent = S.g.truncated ? `showing ${S.g.shown} of ${S.g.total} entities (top by PageRank)`
    : `${S.g.nodes.length} entities · ${S.g.edges.length} relations shown`;
}

function hit(mx,my){ let best=null,bd=1e9;
  for(const n of S.g.nodes){ if(!visible(n)||dim(n)) continue;
    const dx=SX(n)-mx, dy=SY(n)-my, d=Math.hypot(dx,dy), rr=Math.max(7,rad(n));
    if(d<rr && d<bd){ bd=d; best=n; } } return best; }

let drag=null;
c.addEventListener('mousedown',e=>{ drag={x:e.clientX,y:e.clientY,tx:S.tx,ty:S.ty,moved:0}; c.classList.add('grabbing'); });
addEventListener('mouseup',e=>{
  if(drag && drag.moved<4){ const r=c.getBoundingClientRect(); const n=hit(e.clientX-r.left,e.clientY-r.top);
    if(n) onPick(n); }
  drag=null; c.classList.remove('grabbing'); });
addEventListener('mousemove',e=>{
  const r=c.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  if(drag){ drag.moved+=Math.abs(e.movementX)+Math.abs(e.movementY);
    S.tx=drag.tx+(e.clientX-drag.x); S.ty=drag.ty+(e.clientY-drag.y); draw(); return; }
  if(mx<0||my<0||mx>r.width||my>r.height){ tip.style.display='none'; return; }
  const n=hit(mx,my);
  if(n){ tip.style.display='block'; tip.style.left=(mx+14)+'px'; tip.style.top=(my+8)+'px';
    tip.innerHTML=`<b>${esc(n.name)}</b>${n.community_label?' · '+esc(n.community_label):''}`; c.style.cursor='pointer'; }
  else { tip.style.display='none'; c.style.cursor=drag?'grabbing':'grab'; } });
c.addEventListener('wheel',e=>{ e.preventDefault(); const r=c.getBoundingClientRect();
  const mx=e.clientX-r.left,my=e.clientY-r.top, f=e.deltaY<0?1.1:1/1.1;
  S.tx=mx-(mx-S.tx)*f; S.ty=my-(my-S.ty)*f; S.scale*=f; draw(); },{passive:false});

function onPick(n){
  if(S.pathMode){ S.pick.push(n.id); if(S.pick.length===2){ runPath(); } draw(); return; }
  S.sel=n; draw(); inspect(n);
}

function citeStr(cs){ return (cs||[]).map(x=>`[${x.doc_id.slice(0,18)}…:${x.start}-${x.end}]`).join(' '); }
function win(c){ if(c.t_valid&&c.t_invalid) return `<span class="win sup">valid [${c.t_valid}, ${c.t_invalid}) · superseded</span>`;
  if(c.t_valid) return `<span class="win">valid [${c.t_valid}, now)</span>`; return ''; }
async function inspect(n){
  const d=document.getElementById('detail');
  d.innerHTML=`<div class="title">${esc(n.name)}</div><div class="sub">${esc(n.community_label||'')} · pr ${n.pagerank}</div><div class="empty">loading…</div>`;
  const why=await TG.why(n.id);
  let h=`<div class="title">${esc(n.name)}</div><div class="sub">${esc(n.community_label||'')} · pr ${n.pagerank}</div>`;
  if((why.claims||[]).length){ for(const c of why.claims){
    h+=`<div class="fact ${c.status==='superseded'?'sup':''}">${esc(c.subject)} —${esc(c.predicate)}→ ${esc(c.object)}${c.polarity==='neg'?' (negated)':''}<br>${win(c)}<div class="cite">${esc(citeStr(c.citations))}</div></div>`; }
  } else h+='<div class="empty">no claims</div>';
  d.innerHTML=h;
}
async function runPath(){
  const [s,t]=S.pick; const res=await TG.path(s,t);
  S.pathEdges=new Set();
  const d=document.getElementById('detail');
  if(!res.paths||!res.paths.length){ d.innerHTML='<div class="empty">no path found</div>'; S.pick=[]; draw(); return; }
  const p=res.paths[0]; let h=`<div class="title">Path · likelihood ${p.likelihood}</div><div class="sub">${esc(p.nodes.join(' → '))}</div>`;
  const byName={}; S.g.nodes.forEach(n=>byName[n.name]=n.id);
  for(const st of p.steps){ const a=byName[st.subject],b=byName[st.object]; if(a&&b) S.pathEdges.add(a+'>'+b);
    h+=`<div class="fact">${esc(st.subject)} —${esc(st.predicate)}→ ${esc(st.object)}<div class="cite">${esc(citeStr(st.citations))}</div></div>`; }
  d.innerHTML=h; S.pick=[]; setPathMode(false); draw();
}
async function search(){
  S.q=document.getElementById('q').value.trim();
  if(!S.q){ S.match=null; draw(); return; }
  const res=await TG.search(S.q);
  S.match=new Set();
  for(const hit of res.hits){ if(hit.kind==='entity'){ S.match.add(hit.node_id); } }
  const ql=S.q.toLowerCase();
  for(const n of S.g.nodes){ if(n.name.toLowerCase().includes(ql)) S.match.add(n.id); }
  const d=document.getElementById('detail');
  const chunks=res.hits.filter(h=>h.kind==='chunk');
  d.innerHTML=`<div class="title">Search · "${esc(S.q)}"</div><div class="sub">${res.routing||''} routing · ${S.match.size} match(es)</div>`+
    (chunks.map(h=>`<div class="fact">${esc(h.snippet||h.name)}<div class="cite">${esc(citeStr(h.citations))}</div></div>`).join('')||'<div class="empty">no passages</div>');
  draw();
}

function setPathMode(on){ S.pathMode=on; S.pick=[]; document.getElementById('pathbtn').classList.toggle('on',on); }

function buildStats(){
  const g=S.g; const rels=g.edges.length;
  const cards=[
    {k:'Entities', v:g.total, s:g.truncated?`showing top ${g.shown}`:'all shown'},
    {k:'Relations', v:rels, s:'links between shown entities'},
    {k:'Communities', v:(g.communities||[]).length, s:'detected clusters'},
    {k:'Time points', v:(g.dates||[]).length, s:(g.dates||[]).length?'drag the slider':'no dated claims'},
  ];
  document.getElementById('stats').innerHTML = cards.map(x=>
    `<div class="stat"><div class="k">${x.k}</div><div class="v">${x.v}</div><div class="s">${x.s}</div></div>`
  ).join('');
}

function buildTops(){
  const top=[...S.g.nodes].sort((a,b)=>b.pagerank-a.pagerank).slice(0,8);
  const max=top.length?top[0].pagerank:1;
  document.getElementById('tops').innerHTML = top.map((n,i)=>
    `<div class="trow" data-id="${n.id}"><span class="rank">${i+1}</span>`+
    `<span class="dot" style="width:9px;height:9px;border-radius:3px;background:${color(n.community)}"></span>`+
    `<span class="lbl">${esc(n.name)}</span>`+
    `<span class="bar" style="width:${Math.max(6,Math.round(46*n.pagerank/(max||1)))}px"></span></div>`
  ).join('');
  document.querySelectorAll('#tops .trow').forEach(row=>{
    row.onclick=()=>{ const n=S.byId[row.dataset.id]; if(n){ S.sel=n; fitTo(n); inspect(n); } };
  });
}
function fitTo(n){ const r=c.getBoundingClientRect(); S.scale=Math.max(S.scale,1.4);
  S.tx=r.width/2-n.x*S.scale; S.ty=r.height/2-n.y*S.scale; draw(); }

function buildSidebar(){
  const cw=document.getElementById('comms'); cw.innerHTML='';
  for(const cm of S.g.communities){ const row=document.createElement('div'); row.className='crow';
    row.innerHTML=`<input type="checkbox" checked><span class="dot" style="background:${color(cm.community_id)}"></span><span class="lbl">${esc(cm.label||('#'+cm.community_id))}</span><span class="ct">${cm.size}</span>`;
    const cb=row.querySelector('input');
    row.onclick=e=>{ if(e.target!==cb) cb.checked=!cb.checked;
      if(cb.checked) S.hidden.delete(cm.community_id); else S.hidden.add(cm.community_id);
      document.getElementById('all').checked=S.hidden.size===0; draw(); };
    cw.appendChild(row); }
  const tw=document.getElementById('tags'); tw.innerHTML='';
  for(const t of TAGS){ const el=document.createElement('span'); el.className='tag'; el.textContent=t;
    el.style.borderColor='var(--line)';
    el.onclick=()=>{ if(S.tags.has(t)){S.tags.delete(t);el.classList.add('off');} else {S.tags.add(t);el.classList.remove('off');} draw(); };
    tw.appendChild(el); }
}
function initTime(){
  const dates = S.g.dates || [];
  if(!dates.length) return;
  const box=document.getElementById('time'), sl=document.getElementById('tslider'),
    lab=document.getElementById('tlabel');
  box.style.display='flex'; sl.max=String(dates.length); sl.value='0';
  sl.oninput=()=>{ const i=+sl.value; S.date = i===0 ? null : dates[i-1];
    lab.textContent = S.date || 'all time';
    const anySup = S.date && S.g.edges.some(e=>e.t_invalid && S.date>=e.t_invalid);
    lab.classList.toggle('sup', !!anySup); draw(); };
}

function applyTheme(t){ document.documentElement.setAttribute('data-theme',t);
  try{ localStorage.setItem('tg-theme',t); }catch(e){} draw(); }
document.getElementById('theme').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  applyTheme(cur==='dark'?'light':'dark'); };
try{ const saved=localStorage.getItem('tg-theme'); if(saved) document.documentElement.setAttribute('data-theme',saved); }catch(e){}

document.getElementById('all').onchange=e=>{ S.hidden.clear();
  if(!e.target.checked) S.g.communities.forEach(c=>S.hidden.add(c.community_id));
  document.querySelectorAll('#comms input').forEach(cb=>cb.checked=e.target.checked); draw(); };
document.getElementById('fit').onclick=fit;
document.getElementById('pathbtn').onclick=()=>setPathMode(!S.pathMode);
document.getElementById('q').addEventListener('keydown',e=>{ if(e.key==='Enter') search();
  if(e.key==='Escape'){ e.target.value=''; S.match=null; draw(); } });
addEventListener('resize',resize);

// -- Ask dock (grounded chat) ------------------------------------------------
function citeChips(ev){ return (ev&&ev.length) ? '<div class="cites">'+
  ev.map(c=>`<span class="cite-chip">[${esc(c.doc_id.slice(0,14))}…:${c.start}-${c.end}]</span>`).join('')+'</div>' : ''; }
function chainHtml(detail){
  if(!detail||!detail.length||!detail[0].role) return '';
  const steps=detail.map(s=>`<div class="step"><b>${esc(s.role)}</b> ${esc(s.content)}</div>`).join('');
  return `<details class="chain"><summary>reasoning · ${detail.length} steps</summary>${steps}</details>`;
}
function addMsg(cls,html){ const log=document.getElementById('asklog');
  const w=log.querySelector('.welcome'); if(w) w.remove();
  const d=document.createElement('div'); d.className='msg '+cls; d.innerHTML=html;
  log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
function fitNodes(ids){ const pts=(ids||[]).map(i=>S.byId[i]).filter(Boolean); if(!pts.length) return;
  const xs=pts.map(n=>n.x), ys=pts.map(n=>n.y);
  const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
  const r=c.getBoundingClientRect(), pad=90;
  const sx=(r.width-2*pad)/((maxx-minx)||1), sy=(r.height-2*pad)/((maxy-miny)||1);
  S.scale=Math.min(Math.max(Math.min(sx,sy),0.6),2.4);
  S.tx=r.width/2-((minx+maxx)/2)*S.scale; S.ty=r.height/2-((miny+maxy)/2)*S.scale; }
function applyHighlight(h){
  S.match=(h&&h.nodes&&h.nodes.length)?new Set(h.nodes):null;
  S.pathEdges=new Set(); if(h&&h.edges) h.edges.forEach(e=>{ if(e[0]&&e[1]) S.pathEdges.add(e[0]+'>'+e[1]); });
  fitNodes(h&&h.nodes); draw();
}
let asking=false;
async function ask(){
  if(asking) return; const inp=document.getElementById('askq'), q=inp.value.trim(); if(!q) return;
  const tool=document.getElementById('asktool').value;
  addMsg('user',esc(q)); inp.value='';
  const send=document.getElementById('asksend'); asking=true; send.disabled=true;
  const bubble=addMsg('bot','<span style="color:var(--mut)">thinking…</span>');
  try{
    const ans=await TG.chat(q,{tool, focus:S.lastFocus||''});
    S.lastFocus=ans.focus||S.lastFocus;
    bubble.innerHTML=`<div class="tooltag">${esc(ans.tool)}</div>${esc(ans.text)}`+chainHtml(ans.detail)+citeChips(ans.evidence);
    applyHighlight(ans.highlight);
  }catch(e){ bubble.innerHTML='<span style="color:var(--sup)">error: '+esc(e.message||e)+'</span>'; }
  asking=false; send.disabled=false; document.getElementById('asklog').scrollTop=1e9;
}
async function reloadGraph(){
  S.g=await TG.graph(); S.byId={}; S.g.nodes.forEach(n=>S.byId[n.id]=n);
  buildStats(); buildSidebar(); buildTops(); initTime(); draw();
}
async function attachFiles(files){
  if(!files||!files.length) return;
  addMsg('user','&#128206; '+esc([...files].map(f=>f.name).join(', ')));
  const bubble=addMsg('bot','<span style="color:var(--mut)">ingesting…</span>');
  try{
    const res=await TG.ingest(files);
    if(!res.ok){ bubble.innerHTML='<span style="color:var(--sup)">'+esc(res.error||'ingest failed')+
      (res.rejected&&res.rejected.length?' (rejected: '+esc(res.rejected.join(', '))+')':'')+'</span>'; return; }
    await reloadGraph();
    const added=res.added_entities||[];
    bubble.innerHTML=`<div class="tooltag">ingest</div>Added ${esc(res.written.join(', '))} — `+
      `${added.length} new entit${added.length===1?'y':'ies'}`+
      (added.length?': '+esc(added.slice(0,8).join(', ')):'')+'.'+
      (res.rejected&&res.rejected.length?`<div class="cites">rejected: ${esc(res.rejected.join(', '))}</div>`:'');
  }catch(e){ bubble.innerHTML='<span style="color:var(--sup)">error: '+esc(e.message||e)+'</span>'; }
}
function initAsk(){
  const dock=document.getElementById('ask');
  if(!dock) return;
  // `const TG` is a lexical global, not a window property — test the binding via typeof.
  if(typeof TG==='undefined' || typeof TG.chat!=='function'){ dock.style.display='none'; return; } // offline graph.html has no server
  document.getElementById('askhead').onclick=()=>dock.classList.toggle('collapsed');
  document.getElementById('asksend').onclick=ask;
  document.getElementById('askq').addEventListener('keydown',e=>{ if(e.key==='Enter') ask(); });
  // File-attach is available only when the server was started with --allow-ingest.
  if(typeof TG.ingest==='function'){
    fetch('/api/config').then(r=>r.json()).then(cfg=>{
      if(cfg && cfg.ingest){
        const at=document.getElementById('attach'), inp=document.getElementById('attachin');
        at.style.display='inline-block';
        inp.onchange=()=>{ attachFiles(inp.files); inp.value=''; };
      }
    }).catch(()=>{});
  }
}

(async function init(){
  S.g=await TG.graph();
  S.byId={}; S.g.nodes.forEach(n=>S.byId[n.id]=n);
  buildStats(); buildSidebar(); buildTops(); initTime(); initAsk(); resize(); fit();
})();
"""
