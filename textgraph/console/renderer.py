"""Shared interactive-graph renderer — one canvas viewer, two surfaces (G2, G6).

The live ``textgraph console`` and the offline ``graph.html`` artifact render with the
*same* CSS, HTML skeleton, and JavaScript from this module, so they look and behave
identically. The renderer talks to a small global ``TG`` adapter (``graph`` / ``why`` /
``path`` / ``search``); each surface supplies its own adapter — the console over
``fetch``, ``graph.html`` over data embedded in the file — so the drawing/interaction
code never forks. Hand-rolled canvas, zero third-party JS, no CDN.
"""

from __future__ import annotations

RENDERER_CSS = """
  :root { --bg:#0b0e14; --panel:#11151d; --line:#1e2430; --fg:#e6e9ef; --mut:#8b94a3;
          --acc:#5b8cff; --sup:#e0555b; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg);
    font:13px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; overflow:hidden; }
  #app { display:grid; grid-template-columns:1fr 300px; height:100vh; }
  #stage { position:relative; }
  canvas { display:block; width:100%; height:100%; cursor:grab; }
  canvas.grabbing { cursor:grabbing; }
  #bar { position:absolute; top:12px; left:12px; right:12px; display:flex; gap:8px;
    align-items:center; z-index:5; }
  #bar input { flex:1; padding:8px 12px; border-radius:8px; border:1px solid var(--line);
    background:rgba(17,21,29,.9); color:var(--fg); backdrop-filter:blur(6px); }
  .btn { padding:8px 12px; border-radius:8px; border:1px solid var(--line);
    background:rgba(17,21,29,.9); color:var(--fg); cursor:pointer; white-space:nowrap; }
  .btn.on { background:var(--acc); color:#fff; border-color:var(--acc); }
  #note { position:absolute; bottom:10px; left:14px; color:var(--mut); font-size:11px; z-index:5; }
  #time { position:absolute; bottom:12px; left:50%; transform:translateX(-50%); z-index:5;
    display:none; align-items:center; gap:10px; padding:8px 14px; border-radius:10px;
    background:rgba(17,21,29,.92); border:1px solid var(--line); backdrop-filter:blur(6px); }
  #time input[type=range] { width:220px; accent-color:var(--acc); }
  #time .lbl { font-variant-numeric:tabular-nums; min-width:78px; text-align:center; }
  #time .lbl.sup { color:var(--sup); }
  #tip { position:absolute; pointer-events:none; padding:4px 8px; background:#000c;
    border:1px solid var(--line); border-radius:6px; font-size:12px; display:none; z-index:6; }
  aside { background:var(--panel); border-left:1px solid var(--line); overflow-y:auto; }
  aside h2 { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--mut);
    margin:16px 16px 8px; }
  .crow { display:flex; align-items:center; gap:8px; padding:4px 16px; cursor:pointer; }
  .crow:hover { background:#0003; }
  .crow .dot { width:11px; height:11px; border-radius:50%; flex:none; }
  .crow .lbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .crow .ct { color:var(--mut); font-variant-numeric:tabular-nums; }
  .tags { display:flex; flex-wrap:wrap; gap:6px; padding:0 16px 8px; }
  .tag { font-size:11px; padding:3px 8px; border-radius:20px; border:1px solid var(--line);
    cursor:pointer; user-select:none; }
  .tag.off { opacity:.35; text-decoration:line-through; }
  #detail { padding:8px 16px 24px; border-top:1px solid var(--line); margin-top:8px; }
  #detail .title { font-weight:600; margin-bottom:2px; }
  #detail .sub { color:var(--mut); font-size:11px; margin-bottom:8px; }
  .fact { border-left:2px solid var(--line); padding:4px 0 4px 8px; margin:6px 0; }
  .fact .cite { font-family:ui-monospace,Menlo,monospace; font-size:10px; color:var(--mut);
    word-break:break-all; }
  .fact.sup { border-color:var(--sup); }
  .win { color:var(--mut); font-size:11px; } .win.sup { color:var(--sup); }
  .empty { color:var(--mut); padding:8px 0; }
"""

SKELETON_HTML = """
<div id="app">
  <div id="stage">
    <div id="bar">
      <input id="q" placeholder="Search entities & passages…  (Enter)">
      <button class="btn" id="pathbtn" title="click two nodes to trace a path">Path</button>
      <button class="btn" id="fit" title="fit to screen">Fit</button>
    </div>
    <canvas id="c"></canvas>
    <div id="tip"></div>
    <div id="note"></div>
    <div id="time">
      <span>&#9201;</span>
      <input type="range" id="tslider" min="0" value="0" step="1">
      <span class="lbl" id="tlabel">all time</span>
    </div>
  </div>
  <aside>
    <h2>Communities</h2>
    <div class="crow" style="font-weight:600"><input type="checkbox" id="all" checked>
      <span class="lbl">Select All</span></div>
    <div id="comms"></div>
    <h2>Confidence tags</h2>
    <div class="tags" id="tags"></div>
    <div id="detail"><div class="empty">Click a node to inspect its cited claims.</div></div>
  </aside>
</div>
"""

# The renderer. Depends on a global async `TG` adapter: TG.graph(), TG.why(id),
# TG.path(source, target), TG.search(q). Each surface defines TG before this runs.
RENDERER_JS = r"""
const PALETTE = ['#5b8cff','#f59e42','#e0555b','#4bc4a3','#7bc043','#f2c14e','#c98bd6',
  '#ef8fb4','#9b7b5b','#9aa4b2','#5b8cff','#f59e42','#e0555b','#4bc4a3'];
const TAGS = ['STRUCTURAL','EXTRACTED','INFERRED','GENERATED'];
const S = { g:null, scale:1, tx:0, ty:0, hidden:new Set(), tags:new Set(TAGS),
  q:'', match:null, sel:null, pathMode:false, pick:[], pathEdges:new Set(), date:null };
const c = document.getElementById('c'), ctx = c.getContext('2d');
const tip = document.getElementById('tip'), note = document.getElementById('note');
const color = cid => PALETTE[((cid%PALETTE.length)+PALETTE.length)%PALETTE.length];
function esc(s){ return String(s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }

function resize(){ const r = c.getBoundingClientRect(), d = devicePixelRatio||1;
  c.width = r.width*d; c.height = r.height*d; ctx.setTransform(d,0,0,d,0,0); draw(); }
function fit(){ if(!S.g||!S.g.nodes.length) return;
  let xs=S.g.nodes.map(n=>n.x), ys=S.g.nodes.map(n=>n.y);
  const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
  const r=c.getBoundingClientRect(), pad=60;
  const sx=(r.width-2*pad)/((maxx-minx)||1), sy=(r.height-2*pad)/((maxy-miny)||1);
  S.scale=Math.min(sx,sy,3); S.tx=r.width/2-((minx+maxx)/2)*S.scale;
  S.ty=r.height/2-((miny+maxy)/2)*S.scale; draw(); }
const SX = n => n.x*S.scale + S.tx, SY = n => n.y*S.scale + S.ty;
const rad = n => 3 + Math.sqrt(n.pagerank)*46;
function visible(n){ return !S.hidden.has(n.community); }
function dim(n){ return (S.match && !S.match.has(n.id)); }
function edgeActive(e){ if(S.date===null) return true;
  if(e.t_valid && e.t_valid > S.date) return false;
  if(e.t_invalid && S.date >= e.t_invalid) return false;
  return true; }

function draw(){
  const r = c.getBoundingClientRect(); ctx.clearRect(0,0,r.width,r.height);
  const byId = S.byId;
  for(const e of S.g.edges){
    if(!S.tags.has(e.tag)) continue;
    const a=byId[e.source], b=byId[e.target]; if(!a||!b||!visible(a)||!visible(b)) continue;
    const inPath = S.pathEdges.has(e.source+'>'+e.target)||S.pathEdges.has(e.target+'>'+e.source);
    const active = edgeActive(e);
    const alpha = (dim(a)||dim(b)) ? 0.04 : (active ? 0.14 : 0.025);
    ctx.beginPath(); ctx.moveTo(SX(a),SY(a)); ctx.lineTo(SX(b),SY(b));
    ctx.strokeStyle = inPath?'#5b8cff':'rgba(120,130,150,'+alpha+')';
    ctx.lineWidth = inPath?2.5:1; ctx.stroke();
  }
  for(const n of S.g.nodes){
    if(!visible(n)) continue;
    const x=SX(n),y=SY(n),rr=rad(n); const d=dim(n);
    ctx.beginPath(); ctx.arc(x,y,rr,0,7); ctx.fillStyle=color(n.community);
    ctx.globalAlpha = d?0.15:1; ctx.fill();
    if(S.sel&&S.sel.id===n.id){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle='#fff'; ctx.stroke(); }
    if(S.pick.includes(n.id)){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle='#5b8cff'; ctx.stroke(); }
    ctx.globalAlpha=1;
    if(rr*S.scale>6 && !d){ ctx.fillStyle='#cdd3dd'; ctx.font='11px system-ui';
      ctx.fillText(n.name.slice(0,22), x+rr+3, y+3); }
  }
  note.textContent = S.g.truncated ? `showing ${S.g.shown} of ${S.g.total} entities (top by PageRank)`
    : `${S.g.nodes.length} entities · ${S.g.edges.length} relations`;
}

function hit(mx,my){ let best=null,bd=1e9;
  for(const n of S.g.nodes){ if(!visible(n)||dim(n)) continue;
    const dx=SX(n)-mx, dy=SY(n)-my, d=Math.hypot(dx,dy), rr=Math.max(6,rad(n));
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
  const n=hit(mx,my);
  if(n){ tip.style.display='block'; tip.style.left=(mx+14)+'px'; tip.style.top=(my+8)+'px';
    tip.innerHTML=`<b>${esc(n.name)}</b> · ${esc(n.community_label||'')}`; c.style.cursor='pointer'; }
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
  d.innerHTML=`<div class="title">Search · "${esc(S.q)}"</div><div class="sub">${res.routing||''} routing</div>`+
    (chunks.map(h=>`<div class="fact">${esc(h.snippet||h.name)}<div class="cite">${esc(citeStr(h.citations))}</div></div>`).join('')||'<div class="empty">no passages</div>');
  draw();
}

function setPathMode(on){ S.pathMode=on; S.pick=[]; document.getElementById('pathbtn').classList.toggle('on',on); }
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
document.getElementById('all').onchange=e=>{ S.hidden.clear();
  if(!e.target.checked) S.g.communities.forEach(c=>S.hidden.add(c.community_id));
  document.querySelectorAll('#comms input').forEach(cb=>cb.checked=e.target.checked); draw(); };
document.getElementById('fit').onclick=fit;
document.getElementById('pathbtn').onclick=()=>setPathMode(!S.pathMode);
document.getElementById('q').addEventListener('keydown',e=>{ if(e.key==='Enter') search();
  if(e.key==='Escape'){ e.target.value=''; S.match=null; draw(); } });
addEventListener('resize',resize);

(async function init(){
  S.g=await TG.graph();
  S.byId={}; S.g.nodes.forEach(n=>S.byId[n.id]=n);
  buildSidebar(); initTime(); resize(); fit();
})();
"""
