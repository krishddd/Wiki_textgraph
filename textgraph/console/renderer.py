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

  /* Studio shell: a slim left rail + (app bar / body) stacked to its right. */
  #app { display:grid; grid-template-columns:56px 1fr; grid-template-rows:auto 1fr;
    height:100vh; position:relative; }  /* positioning context for the slide-in source panel */

  /* Left rail — brand mark + vertical mode shortcuts (Semantica-style studio nav). */
  #rail { grid-row:1 / 3; display:flex; flex-direction:column; align-items:center; gap:6px;
    padding:12px 0; background:var(--panel); border-right:1px solid var(--line); }
  #rail .mark { width:26px; height:26px; border-radius:8px; margin-bottom:8px;
    background:linear-gradient(135deg,var(--acc),#8a6bff); box-shadow:var(--shadow); }
  .rail-btn { width:38px; height:38px; display:flex; align-items:center; justify-content:center;
    border-radius:10px; border:1px solid transparent; background:none; color:var(--fg2);
    cursor:pointer; font-size:16px; transition:background .12s,color .12s,border-color .12s; }
  .rail-btn:hover { background:var(--line2); color:var(--fg); }
  .rail-btn.on { background:var(--acc); color:#fff; }
  .rail-sp { flex:1; }

  /* App bar */
  header { grid-column:2; display:flex; align-items:center; gap:12px; padding:11px 18px;
    background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:center; gap:10px; font-weight:650; letter-spacing:-.01em;
    font-size:15px; white-space:nowrap; }
  .search { position:relative; flex:1; max-width:520px; }
  .search input { width:100%; padding:9px 14px 9px 36px; border-radius:11px;
    border:1px solid var(--line); background:var(--bg); color:var(--fg); font-size:14px;
    outline:none; transition:border-color .15s,box-shadow .15s; }
  .search input:focus { border-color:var(--acc); box-shadow:0 0 0 3px var(--acc-soft); }
  .search svg { position:absolute; left:12px; top:50%; transform:translateY(-50%);
    width:16px; height:16px; color:var(--mut); }
  .spacer { flex:1; }
  /* Segmented toolbar: labelled pill groups, like the Explore studio's CAMERA/LAYOUT bands. */
  .seg { display:flex; align-items:center; gap:2px; padding:3px; border-radius:12px;
    background:var(--bg); border:1px solid var(--line); }
  .seg .seg-l { font-size:9.5px; letter-spacing:.07em; text-transform:uppercase; color:var(--mut);
    padding:0 7px 0 5px; white-space:nowrap; }
  .btn { padding:7px 12px; border-radius:9px; border:1px solid transparent;
    background:none; color:var(--fg); cursor:pointer; font-size:12.5px; font-weight:550;
    white-space:nowrap; transition:background .15s,color .15s; }
  .btn:hover { background:var(--line2); color:var(--acc); }
  .btn.on { background:var(--acc); color:#fff; }
  /* Standalone buttons (outside a segment) keep a visible border. */
  header > .btn, header > .icon-btn { border-color:var(--line); background:var(--card); }
  header > .btn:hover { border-color:var(--acc); }
  .icon-btn { padding:7px 10px; }

  /* Body: canvas column + inspector */
  #body { grid-column:2; display:grid; grid-template-columns:1fr 340px; min-height:0;
    transition:grid-template-columns .2s ease; }
  #body.solo { grid-template-columns:1fr 0; }
  #body.solo aside { display:none; }
  #main { display:flex; flex-direction:column; min-width:0; min-height:0; padding:16px 16px 0;
    gap:12px; }

  /* Stat cards — the headline data points (compact: a slim strip, not tall boxes) */
  #stats { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:11px;
    padding:8px 13px; box-shadow:var(--shadow); min-width:0;
    display:flex; align-items:baseline; gap:9px; flex-wrap:wrap; }
  .stat .k { font-size:10px; letter-spacing:.05em; text-transform:uppercase; color:var(--mut);
    display:flex; align-items:center; gap:6px; order:2; }
  .stat .k .swatch { width:8px; height:8px; border-radius:2px; }
  .stat .v { font-size:20px; font-weight:700; letter-spacing:-.02em; order:1;
    font-variant-numeric:tabular-nums; line-height:1.1; }
  .stat .s { display:none; }  /* drop the sub-caption; the number + label is enough */

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
  #tplay { border:none; background:transparent; color:var(--fg2); cursor:pointer; font-size:13px;
    width:22px; height:22px; border-radius:6px; display:flex; align-items:center; justify-content:center; }
  #tplay:hover { background:var(--acc-soft); color:var(--acc); }
  /* Mini-map overview — bottom-right of the stage, drag to pan. */
  #minimap { position:absolute; right:12px; bottom:12px; z-index:5; display:none; cursor:pointer;
    background:color-mix(in srgb,var(--card) 88%,transparent); border:1px solid var(--line);
    border-radius:10px; box-shadow:var(--shadow); }
  #tip { position:absolute; pointer-events:none; padding:6px 10px; background:var(--panel);
    border:1px solid var(--line); border-radius:9px; font-size:12px; display:none; z-index:6;
    box-shadow:var(--shadow); max-width:260px; }
  #legend { position:absolute; top:12px; left:16px; display:flex; flex-wrap:wrap; gap:6px 12px;
    max-width:60%; z-index:5; pointer-events:none; }
  #legend .lg { display:flex; align-items:center; gap:5px; font-size:11.5px; color:var(--fg2); }
  #legend .lg .dot { width:9px; height:9px; border-radius:50%; }
  /* Ego / distance-intelligence banner (shown only in ego mode) */
  #egobar { position:absolute; top:10px; left:50%; transform:translateX(-50%); z-index:6;
    display:none; align-items:center; gap:14px; padding:8px 14px; border-radius:12px;
    background:var(--panel); border:1px solid var(--line); box-shadow:var(--shadow);
    font-size:12px; max-width:92%; }
  #egobar.on { display:flex; }
  #egobar .eg-anchor { font-weight:650; }
  #egobar .eg-anchor .mut { font-weight:400; }
  #egobar input[type=range] { width:120px; accent-color:var(--acc); vertical-align:middle; }
  #egobar .eg-depth { display:flex; align-items:center; gap:7px; white-space:nowrap; color:var(--fg2); }
  #egobar .eg-legend { display:flex; gap:10px; }
  #egobar .eg-legend .lg { display:flex; align-items:center; gap:4px; color:var(--fg2); }
  #egobar .eg-legend .dot { width:9px; height:9px; border-radius:50%; }
  #egobar .eg-x { cursor:pointer; color:var(--mut); border:none; background:none; font-size:15px;
    line-height:1; padding:0 2px; }
  #egobar .eg-x:hover { color:var(--sup); }

  /* Inspector — a flex column that always fits the page; long lists scroll inside their
     own section instead of pushing the panel off-screen. */
  aside { background:var(--panel); border-left:1px solid var(--line); overflow:hidden;
    display:flex; flex-direction:column; min-height:0; }
  aside h2 { font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:var(--mut);
    margin:12px 18px 7px; font-weight:600; flex:none; }
  aside h2:first-child { margin-top:14px; }
  /* Collapsible section headers (click to fold), like the studio inspector's cards. */
  aside h2.sec { cursor:pointer; display:flex; align-items:center; gap:6px; user-select:none; }
  aside h2.sec::after { content:'\\25BE'; margin-left:auto; font-size:9px; color:var(--mut);
    transition:transform .15s; }
  aside h2.sec.collapsed::after { transform:rotate(-90deg); }
  aside h2.sec:hover { color:var(--fg2); }
  /* Long lists (communities, top entities, documents) each cap out and scroll internally,
     so the panel never grows past the page. #detail takes whatever height is left. */
  #comms { overflow-y:auto; max-height:26vh; flex:none; }
  #tops  { overflow-y:auto; max-height:22vh; flex:none; }
  #docs  { overflow-y:auto; max-height:14vh; flex:none; }
  #tags, #all { flex:none; }
  .mut { color:var(--mut); font-weight:400; }
  .docrow { display:flex; align-items:center; gap:8px; padding:5px 18px; margin:0 8px;
    border-radius:8px; }
  .docrow:hover { background:var(--acc-soft); }
  .docrow .dn { flex:1; font-size:12.5px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }
  .docrow .ds { color:var(--mut); font-size:11px; font-variant-numeric:tabular-nums; }
  .docrow .drm { border:none; background:none; cursor:pointer; color:var(--mut); font-size:14px;
    padding:2px 4px; border-radius:6px; line-height:1; }
  .docrow .drm:hover { color:var(--sup,#d64); background:var(--line2); }
  .crow { display:flex; align-items:center; gap:9px; padding:4px 18px; cursor:pointer;
    border-radius:9px; margin:0 8px; transition:background .12s; }
  .crow:hover { background:var(--line2); }
  .crow .dot { width:11px; height:11px; border-radius:4px; flex:none; }
  .crow .lbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .crow .ct { color:var(--mut); font-variant-numeric:tabular-nums; font-size:12px; }
  .trow { display:flex; align-items:baseline; gap:9px; padding:4px 18px; cursor:pointer;
    border-radius:9px; margin:0 8px; transition:background .12s; }
  .trow:hover { background:var(--line2); }
  .trow .rank { color:var(--mut); font-size:12px; width:16px; font-variant-numeric:tabular-nums; }
  .trow .lbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .trow .bar { height:5px; border-radius:3px; background:var(--acc); flex:none; opacity:.85; }
  .tags { display:flex; flex-wrap:wrap; gap:7px; padding:0 18px 10px; }
  .tag { font-size:11.5px; padding:4px 11px; border-radius:20px; border:1px solid var(--line);
    cursor:pointer; user-select:none; transition:opacity .12s; }
  .tag.off { opacity:.4; text-decoration:line-through; }
  /* Relation-type filter: chips carry a count, plus All / Semantic-only shortcuts. The
     backbone chip is dotted so the dense CO_OCCURS scaffold reads as structural, not semantic. */
  .tag .n { color:var(--mut); font-variant-numeric:tabular-nums; margin-left:5px; }
  .tag.backbone { border-style:dashed; }
  #preds { max-height:19vh; overflow-y:auto; }
  .predbtns { display:flex; gap:7px; padding:0 18px 8px; }
  .minibtn { font-size:11px; padding:3px 10px; border-radius:20px; border:1px solid var(--line);
    background:transparent; color:var(--fg2); cursor:pointer; font-family:inherit; }
  .minibtn:hover { border-color:var(--acc); color:var(--fg); }
  #detail { padding:12px 18px 24px; border-top:1px solid var(--line); margin-top:6px;
    flex:1; overflow-y:auto; min-height:0; }
  #detail .title { font-weight:650; font-size:15px; margin-bottom:2px; letter-spacing:-.01em; }
  #detail .sub { color:var(--fg2); font-size:12px; margin-bottom:10px; }
  .fact { border-left:2px solid var(--line); padding:6px 0 6px 10px; margin:8px 0; font-size:13px; }
  .fact .cite { font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:var(--mut);
    word-break:break-all; margin-top:3px; }
  .fact.sup { border-color:var(--sup); }
  .adm { font-size:11.5px; color:var(--fg2); margin:5px 0; }
  .adm .k { text-transform:uppercase; letter-spacing:.06em; font-size:10px; color:var(--mut);
    margin-right:6px; }
  .adm.sup .k, .adm.sup { color:var(--sup); }
  .adm .pill { display:inline-block; padding:1px 7px; border-radius:20px; border:1px solid var(--line);
    font-size:10.5px; }
  .win { color:var(--mut); font-size:11.5px; } .win.sup { color:var(--sup); }
  .empty { color:var(--mut); padding:10px 0; }

  /* Ask — the grounded chat dock */
  #ask { display:flex; flex-direction:column; height:236px; flex:none; margin-bottom:14px;
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
    margin-bottom:4px; display:flex; gap:8px; align-items:center; }
  .msg .conf { color:var(--acc); font-weight:600; letter-spacing:0; text-transform:none; }
  .msg .conf.abstain { color:var(--sup); }
  .msg .cites { margin-top:7px; display:flex; flex-wrap:wrap; gap:5px; }
  .cite-chip { font-family:ui-monospace,Menlo,monospace; font-size:10px; padding:2px 7px;
    border-radius:6px; background:var(--acc-soft); color:var(--acc); }
  .cite-chip.live { cursor:pointer; }
  .cite-chip.live:hover { background:var(--acc); color:#fff; }
  .cite-chip.live:focus-visible { outline:2px solid var(--acc); outline-offset:1px; }
  /* Deterministic follow-up chips under an answer. */
  .msg .suggs { margin-top:9px; display:flex; flex-wrap:wrap; gap:6px; }
  .sugg { font-size:11.5px; padding:5px 10px; border-radius:20px; border:1px solid var(--line);
    background:transparent; color:var(--fg2); cursor:pointer; font-family:inherit; text-align:left; }
  .sugg:hover { border-color:var(--acc); color:var(--fg); }
  /* Routing inspector — how this answer was produced. */
  .routing { margin-top:8px; }
  .routing summary { cursor:pointer; color:var(--mut); font-size:11.5px; }
  .routing .rrow { display:flex; gap:8px; font-size:11.5px; margin:4px 0 0; }
  .routing .rrow span { color:var(--mut); min-width:58px; }
  .routing .rrow b { color:var(--fg2); font-weight:600; }
  /* Source panel: slides in over the graph to show the cited bytes. */
  #srcpanel { position:absolute; top:0; right:0; bottom:0; width:min(440px,86%); z-index:40;
    background:var(--card); border-left:1px solid var(--line); box-shadow:-14px 0 40px rgba(0,0,0,.16);
    transform:translateX(102%); transition:transform .22s ease; display:flex; flex-direction:column; }
  #srcpanel.open { transform:translateX(0); }
  .srchead { display:flex; align-items:center; gap:10px; padding:13px 16px; border-bottom:1px solid var(--line);
    font-size:13px; font-weight:600; }
  #srctitle { flex:1; overflow:hidden; text-overflow:ellipsis; }
  #srcclose { border:none; background:transparent; color:var(--mut); cursor:pointer; font-size:15px; }
  #srcclose:hover { color:var(--fg); }
  #srcbody { padding:16px; overflow:auto; font:13px/1.7 ui-monospace,Menlo,monospace;
    white-space:pre-wrap; word-break:break-word; }
  #srcbody .ctx { color:var(--mut); }
  #srcbody mark { background:var(--acc-soft); color:var(--fg); padding:1px 2px; border-radius:3px;
    box-shadow:0 0 0 1px var(--acc) inset; }
  #srctitle .ok { color:#2bb7a3; font-size:11px; font-weight:600; }
  #srctitle .bad { color:var(--sup); font-size:11px; font-weight:600; }
  #srctitle .mut { color:var(--mut); font-weight:400; font-size:11px; }
  .chain { margin-top:8px; }
  .chain summary { cursor:pointer; color:var(--mut); font-size:12px; }
  .chain .step { font-size:12px; margin:5px 0; padding-left:9px; border-left:2px solid var(--line);
    color:var(--fg2); }
  .chain .step b { color:var(--fg); font-weight:600; }
  /* Contradiction resolution hints */
  .chain .cx { margin:2px 0; }
  .chain .cx .ca, .chain .cx .cb { display:inline-block; width:15px; height:15px; line-height:15px;
    text-align:center; border-radius:4px; font-size:10px; font-weight:700; margin-right:5px; color:#fff; }
  .chain .cx .ca { background:var(--mut); } .chain .cx .cb { background:var(--acc); }
  .chain .hint { margin-top:4px; font-size:11.5px; }
  .hint-rec { display:inline-block; padding:1px 7px; border-radius:20px; font-size:10.5px;
    font-weight:600; background:var(--acc); color:#fff; margin-right:6px; }
  .hint-rec.none { background:var(--mut); }
  /* Analyst annotation editor in the inspector */
  .annot { margin-top:14px; padding-top:12px; border-top:1px dashed var(--line); }
  .annot .ah { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--mut); margin-bottom:6px; }
  .annsel { width:100%; padding:6px 8px; border:1px solid var(--line); border-radius:8px;
    background:var(--card); color:var(--fg); font:inherit; font-size:13px; margin-bottom:7px; }
  .annnote { width:100%; min-height:52px; padding:7px 9px; border:1px solid var(--line);
    border-radius:8px; background:var(--card); color:var(--fg); font:inherit; font-size:13px;
    resize:vertical; box-sizing:border-box; }
  .annrow { display:flex; align-items:center; gap:9px; margin-top:7px; }
  .annby { font-size:11px; color:var(--mut); margin-top:6px; }
  /* Collaboration: identity chip + team activity feed */
  #whoami { display:none; align-items:center; font-size:12px; color:var(--fg2); padding:5px 10px;
    border:1px solid var(--line); border-radius:20px; margin-right:4px; white-space:nowrap; }
  #activity { max-height:20vh; overflow-y:auto; padding:0 18px 8px; }
  .arow { font-size:12px; color:var(--fg2); padding:3px 0; border-bottom:1px solid var(--line); }
  .arow:last-child { border-bottom:none; }
  .arow b { color:var(--fg); }
  #askbar { display:flex; gap:8px; padding:11px 13px; border-top:1px solid var(--line);
    align-items:center; }
  #attach, #save { display:none; cursor:pointer; font-size:17px; line-height:1; padding:7px 9px;
    border-radius:9px; border:1px solid var(--line); background:var(--bg); color:var(--fg);
    user-select:none; }
  #attach:hover, #save:hover { border-color:var(--acc); }
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
  <div id="rail">
    <span class="mark" title="TextGraph"></span>
    <button class="rail-btn" id="r-fit" title="fit graph to screen">&#9633;</button>
    <button class="rail-btn" id="r-ego" title="ego / distance view">&#9673;</button>
    <button class="rail-btn" id="r-group" title="grouped (community) view">&#9635;</button>
    <button class="rail-btn on" id="r-focus" title="focus: fade unconnected nodes (F)">&#9678;</button>
    <button class="rail-btn" id="r-panel" title="expand graph to full width / show panel">&#8596;</button>
    <span class="rail-sp"></span>
    <button class="rail-btn" id="r-theme" title="toggle light / dark">&#9681;</button>
  </div>
  <header>
    <div class="brand">TextGraph</div>
    <div class="search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path></svg>
      <input id="q" placeholder="Search entities &amp; passages…  (Enter)">
    </div>
    <div class="spacer"></div>
    <div class="seg">
      <span class="seg-l">Analyze</span>
      <button class="btn" id="egobtn" title="ego / distance view — colour nodes by hops from a focus node">Ego</button>
      <button class="btn" id="pathbtn" title="click two nodes to trace a path">Path</button>
      <button class="btn" id="groupbtn" title="outline communities (grouped view)">Group</button>
      <button class="btn" id="heatbtn" title="contradiction heatmap — tint entities by contested claims">Heat</button>
    </div>
    <div class="seg">
      <span class="seg-l">View</span>
      <button class="btn" id="fit" title="fit graph to screen">Fit</button>
      <button class="btn" id="panel" title="expand graph to full width / show panel">&#8596;</button>
    </div>
    <span id="whoami" title="your collaboration identity (console --analyst)"></span>
    <button class="btn" id="minebtn" style="display:none" title="show only entities assigned to me">Mine</button>
    <button class="btn icon-btn" id="theme" title="toggle light / dark">&#9681;</button>
  </header>
  <div id="body">
    <div id="main">
      <div id="stats"></div>
      <div id="stage">
        <canvas id="c"></canvas>
        <div id="tip"></div>
        <div id="legend"></div>
        <div id="egobar"></div>
        <div id="note"></div>
        <div id="time">
          <button id="tplay" title="play the timeline">&#9654;</button>
          <input type="range" id="tslider" min="0" value="0" step="1">
          <span class="lbl" id="tlabel">all time</span>
        </div>
        <canvas id="minimap" title="overview — drag to pan"></canvas>
      </div>
      <div id="ask">
        <div id="askhead"><span class="dot"></span>Ask the graph<span class="chev">&#9662;</span></div>
        <div id="asklog"><div class="welcome">Ask a question in plain English — e.g. <em>&ldquo;how is Acme Corp connected to Delta Trust?&rdquo;</em> or <em>&ldquo;why does Acme matter?&rdquo;</em>. Answers are grounded in the graph, cited to the source, and highlighted on the canvas above.</div></div>
        <div id="askbar">
          <label id="attach" title="attach files to the graph">&#128206;<input type="file" id="attachin" multiple hidden></label>
          <button id="save" title="download a graph.json snapshot of the current graph">&#128190;</button>
          <select id="asktool" title="which tool to use">
            <option value="auto">Auto</option>
            <option value="narrate">Narrate (LLM)</option>
            <option value="reason">Reason</option>
            <option value="search">Search</option>
            <option value="path">Path</option>
            <option value="why">Why</option>
            <option value="neighbors">Neighbors</option>
            <option value="predict">Predict links</option>
            <option value="roles">Similar roles</option>
            <option value="rules">Rules (Datalog)</option>
            <option value="timeline">Timeline</option>
            <option value="contradictions">Contradictions</option>
            <option value="conflicts">Conflicts</option>
            <option value="trace">Trace decision</option>
            <option value="decisions">Find decisions</option>
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
      <h2>Relation types <span id="predhint" class="mut"></span></h2>
      <div class="predbtns">
        <button type="button" id="predall" class="minibtn">All</button>
        <button type="button" id="predsem" class="minibtn">Semantic only</button>
      </div>
      <div class="tags" id="preds"></div>
      <h2 id="acthdr" style="display:none">Team activity</h2>
      <div id="activity"></div>
      <h2 id="docshdr" style="display:none">Documents <span id="doccount" class="mut"></span></h2>
      <div id="docs"></div>
      <div id="detail"><div class="empty">Click a node to inspect its cited claims.</div></div>
    </aside>
  </div>
  <div id="srcpanel">
    <div class="srchead"><span id="srctitle"></span>
      <button type="button" id="srcclose" title="close">&#10005;</button></div>
    <div id="srcbody"></div>
  </div>
</div>
"""

# The renderer. Depends on a global async `TG` adapter: TG.graph(), TG.why(id),
# TG.path(source, target), TG.search(q). Each surface defines TG before this runs.
RENDERER_JS = r"""
const PALETTE = ['#4f6bff','#f59e42','#e0555b','#2bb7a3','#7bc043','#f2c14e','#c98bd6',
  '#ef8fb4','#9b7b5b','#8a94a6','#3aa0ff','#ff7a59','#59c1ff','#b08cff'];
const TAGS = ['STRUCTURAL','EXTRACTED','INFERRED','GENERATED'];
// The co-occurrence backbone is deliberately dense (it exists to connect the map), so it is
// the one predicate worth hiding in bulk — "Semantic only" leaves just the meaning relations.
const BACKBONE = 'CO_OCCURS';
const S = { g:null, scale:1, tx:0, ty:0, hidden:new Set(), tags:new Set(TAGS),
  q:'', match:null, sel:null, pathMode:false, pick:[], pathEdges:new Set(),
  predEdges:new Set(), date:null, grouped:false,
  ego:false, egoAnchor:null, egoDepth:3, egoDist:null, egoAdj:null,
  // Relation-type filter: `preds` holds the predicates currently shown (all, on load).
  // Filtering by predicate is view-only — it never touches graph.json.
  preds:new Set(), predCounts:{},
  // derived each load: degree map, always-labelled top-PageRank set, median edge length
  // (for long-chord fading), orphan count, and the focus-mode toggle (fade unconnected).
  deg:{}, topRank:new Set(), edgeLenMed:0, orphanCount:0, focusOrphans:true,
  // v4.10: contradiction heatmap toggle (+ max count, for the colour scale) and the
  // timeline play state (interval id + keyframe cursor).
  heat:false, heatMax:0, playing:false, playTimer:null,
  // v4.12+: collaboration overlay (sidecar, never graph.json). ann: node -> {status,note,author,
  // updated}; assign: node -> analyst; analyst: this console's declared identity; collabV: last
  // seen version (poll-sync); activity: recent change log; mineOnly: "assigned to me" filter.
  ann:{}, assign:{}, analyst:'', collabV:-1, activity:[], mineOnly:false };
const c = document.getElementById('c'), ctx = c.getContext('2d');
const tip = document.getElementById('tip'), note = document.getElementById('note');
const color = cid => PALETTE[((cid%PALETTE.length)+PALETTE.length)%PALETTE.length];
// Semantica-style: nodes are coloured by ENTITY TYPE (a small fixed legend), not by the
// dozens of communities (which cycle colours and look random).
const TYPE_COLOR = { Organization:'#4f6bff', Person:'#2bb7a3', Location:'#f59e42',
  Money:'#7bc043', Date:'#c98bd6', Work:'#ef8fb4', Term:'#59c1ff', LLM:'#e0555b' };
const OTHER_COLOR = '#8a94a6';
// Ego / distance-intelligence bands: colour a node by how many hops it sits from the focus.
const EGO_COLORS = { anchor:'#f2c14e', h1:'#2bb7a3', h23:'#7bc043', h46:'#4f6bff' };
function egoColor(d){ return d===0?EGO_COLORS.anchor : d===1?EGO_COLORS.h1 : d<=3?EGO_COLORS.h23 : EGO_COLORS.h46; }
function nodeColor(n){
  if(S.heat && n) return heatColor(n);   // contradiction heatmap overrides the type palette
  if(S.ego && S.egoDist && n){ const d=S.egoDist.get(n.id); if(d!=null) return egoColor(d); }
  return TYPE_COLOR[n && n.etype] || OTHER_COLOR;
}
function esc(s){ return String(s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }
function buildLegend(){
  const el=document.getElementById('legend'); if(!el||!S.g) return;
  if(S.heat){   // heatmap legend: how many entities carry contested claims, and the scale
    const flagged=S.g.nodes.filter(n=>n.contradictions>0).length;
    if(!flagged){ el.innerHTML=`<span class="lg mut">no contradictions in view</span>`; return; }
    el.innerHTML=`<span class="lg"><span class="dot" style="background:${heatColor({contradictions:S.heatMax})}"></span>most contested</span>`
      +`<span class="lg"><span class="dot" style="background:${heatColor({contradictions:1})}"></span>contested</span>`
      +`<span class="lg"><span class="dot" style="background:${heatColor({contradictions:0})}"></span>none</span>`
      +`<span class="lg mut">${flagged} contested entit${flagged===1?'y':'ies'}</span>`;
    return;
  }
  const counts={}; for(const n of S.g.nodes){ const t=n.etype||'Other'; counts[t]=(counts[t]||0)+1; }
  const types=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]);
  el.innerHTML=types.map(t=>`<span class="lg"><span class="dot" style="background:${nodeColor({etype:t})}"></span>${esc(t)} <span class="mut">${counts[t]}</span></span>`).join('');
}
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
// Radius rewards centrality AND connectivity, so a relation-bearing node is never a bare
// 3.5px dot lost among the orphans (the "floating dots" complaint).
const rad = n => 3.5 + Math.sqrt(n.pagerank)*46 + Math.min(6, (S.deg[n.id]||0)*1.1);
function visible(n){ return !S.hidden.has(n.community); }
function dim(n){ return (S.match && !S.match.has(n.id)); }
// A degree-0 node in focus mode fades to the background — unless it's a current match,
// selection, or path/ego pick, which always stay lit and clickable.
function isOrphan(n){ return !(S.deg[n.id]); }
function orphanDimmed(n){
  return S.focusOrphans && isOrphan(n) && !(S.match && S.match.has(n.id))
    && !(S.sel && S.sel.id===n.id) && !S.pick.includes(n.id);
}
// The single test for "is this edge in the current view" — confidence tag AND relation type.
// Every consumer (drawing, degree, neighbours, ego) goes through it, so the filters can
// never disagree with each other.
function edgeShown(e){ return S.tags.has(e.tag) && S.preds.has(e.predicate); }
// Recompute the derived structures: degree, the always-labelled top-PageRank set, median
// edge length (long-chord fade threshold), and the orphan tally. Degree counts only edges
// that pass the filters, so hiding the CO_OCCURS backbone correctly re-reveals which nodes
// are held up by *semantic* relations alone. Call after layout and after any filter change.
function computeDerived(){
  if(!S.g) return;
  const deg={}; S.g.nodes.forEach(n=>deg[n.id]=0);
  for(const e of S.g.edges){ if(!edgeShown(e)) continue;
    if(deg[e.source]!=null) deg[e.source]++; if(deg[e.target]!=null) deg[e.target]++; }
  S.deg=deg;
  S.orphanCount=S.g.nodes.filter(n=>!deg[n.id]).length;
  const ranked=[...S.g.nodes].sort((a,b)=>(b.pagerank||0)-(a.pagerank||0)||(a.id<b.id?-1:1));
  S.topRank=new Set(ranked.slice(0,25).map(n=>n.id));
  const lens=[]; for(const e of S.g.edges){ if(!edgeShown(e)) continue;
    const a=S.byId[e.source], b=S.byId[e.target];
    if(a&&b) lens.push(Math.hypot(a.x-b.x, a.y-b.y)); }
  lens.sort((x,y)=>x-y); S.edgeLenMed=lens.length?lens[Math.floor(lens.length/2)]:0;
  S.heatMax=S.g.nodes.reduce((m,n)=>Math.max(m, n.contradictions||0), 0);
}
// Contradiction heatmap tint: entities with contested claims glow red (deeper = more), the
// rest fade to a neutral grey so the eye lands on the contested zones.
function heatColor(n){
  const c=n.contradictions||0;
  if(!c) return '#8f97a6';
  const t=S.heatMax>0 ? c/S.heatMax : 1;          // 0..1 by relative contradiction load
  const r=Math.round(224), g=Math.round(120-70*t), b=Math.round(110-70*t);
  return `rgb(${r},${g},${b})`;
}
// Tally the predicates present in the payload and seed the filter to "everything on".
// Across a rebuild we keep whatever the analyst had switched *off* (for predicates that
// still exist), so a reload doesn't silently undo their filtering.
function computePredicates(){
  const prev=S.predCounts, hadFilter=S.preds.size>0;
  const off=new Set(hadFilter ? Object.keys(prev).filter(p=>!S.preds.has(p)) : []);
  const counts={}; for(const e of S.g.edges) counts[e.predicate]=(counts[e.predicate]||0)+1;
  S.predCounts=counts;
  S.preds=new Set(Object.keys(counts).filter(p=>!off.has(p)));
}
// Apply a relation-type change: degree/orphan/labels all shift with it, so recompute, and
// drop the ego adjacency cache so hop bands re-derive from the visible edges.
function applyPredFilter(){
  S.egoAdj=null; computeDerived();
  if(S.ego && S.egoAnchor) reEgo();
  buildPredBar(); draw();
}
function edgeActive(e){ if(S.date===null) return true;
  if(e.t_valid && e.t_valid > S.date) return false;
  if(e.t_invalid && S.date >= e.t_invalid) return false;
  return true; }

function drawGroups(labelColor){
  const g={};  // community -> {xs,ys,label,cid}
  for(const n of S.g.nodes){ if(!visible(n)||n.community<0||n.community==null) continue;
    (g[n.community]=g[n.community]||{xs:[],ys:[],label:n.community_label||('#'+n.community),cid:n.community});
    g[n.community].xs.push(SX(n)); g[n.community].ys.push(SY(n)); }
  // Rank clusters by size; only the largest ~18 get a label so text never piles up.
  const sized=Object.values(g).filter(m=>m.xs.length>=2).sort((a,b)=>b.xs.length-a.xs.length);
  const labelled=new Set(sized.slice(0,18).filter(m=>m.xs.length>=3).map(m=>m.cid));
  const ergb=cssv('--edge-rgb')||'120,130,150';
  for(const m of sized){
    const cx=m.xs.reduce((a,b)=>a+b,0)/m.xs.length, cy=m.ys.reduce((a,b)=>a+b,0)/m.ys.length;
    let rr=0; for(let i=0;i<m.xs.length;i++){ rr=Math.max(rr,Math.hypot(m.xs[i]-cx,m.ys[i]-cy)); }
    rr+=18; ctx.beginPath(); ctx.arc(cx,cy,rr,0,7);
    ctx.fillStyle='rgba('+ergb+',0.05)'; ctx.fill();
    ctx.strokeStyle='rgba('+ergb+',0.22)'; ctx.lineWidth=1; ctx.stroke();
    if(labelled.has(m.cid)){                       // a compact chip label above the bubble
      const txt=m.label.replace(/\s*\([^)]*\)\s*$/,'').slice(0,26);
      ctx.fillStyle=labelColor; ctx.font='600 11px ui-sans-serif,system-ui';
      ctx.textAlign='center'; ctx.fillText(txt, cx, cy-rr-4); ctx.textAlign='left';
    }
  }
}
function draw(){
  const r = c.getBoundingClientRect(); ctx.clearRect(0,0,r.width,r.height);
  const byId = S.byId; const ergb = cssv('--edge-rgb')||'120,130,150';
  const labelColor = cssv('--canvas-label')||'#334'; const accent = cssv('--acc')||'#4f6bff';
  const selColor = cssv('--fg')||'#111';
  if(S.grouped) drawGroups(labelColor);
  for(const e of S.g.edges){
    if(!edgeShown(e)) continue;
    const a=byId[e.source], b=byId[e.target]; if(!a||!b||!visible(a)||!visible(b)) continue;
    const inPath = S.pathEdges.has(e.source+'>'+e.target)||S.pathEdges.has(e.target+'>'+e.source);
    const active = edgeActive(e);
    // Long-chord fade: an edge stretching far past the typical length reads as a line "just
    // passing through". Unless it's highlighted, fade it hard so structure stays legible.
    const longChord = !inPath && S.edgeLenMed>0 &&
      Math.hypot(a.x-b.x, a.y-b.y) > S.edgeLenMed*3.2;
    let alpha = (dim(a)||dim(b)) ? 0.05 : (active ? 0.42 : 0.06);
    if(longChord && !dim(a) && !dim(b)) alpha=Math.min(alpha,0.05);
    ctx.beginPath(); ctx.moveTo(SX(a),SY(a)); ctx.lineTo(SX(b),SY(b));
    ctx.strokeStyle = inPath?accent:('rgba('+ergb+','+alpha+')');
    ctx.lineWidth = inPath?2.5:1; ctx.stroke();
    // Label relation predicates on highlighted edges, or on every edge when zoomed in.
    if(e.predicate && (inPath || S.scale>1.6) && !(dim(a)||dim(b))){
      const mx=(SX(a)+SX(b))/2, my=(SY(a)+SY(b))/2;
      ctx.fillStyle=inPath?accent:labelColor; ctx.font='10px ui-sans-serif,system-ui';
      ctx.fillText(e.predicate.replace(/_/g,' ').slice(0,22), mx+3, my-3);
    }
  }
  // Predicted "candidate" links — dashed, in the support colour, since they don't exist yet.
  if(S.predEdges&&S.predEdges.size){ const sup=cssv('--sup')||'#e0555b';
    ctx.save(); ctx.setLineDash([6,5]); ctx.strokeStyle=sup; ctx.lineWidth=1.6;
    for(const key of S.predEdges){ const [s,t]=key.split('>'); const a=byId[s], b=byId[t];
      if(!a||!b||!visible(a)||!visible(b)) continue;
      ctx.beginPath(); ctx.moveTo(SX(a),SY(a)); ctx.lineTo(SX(b),SY(b)); ctx.stroke(); }
    ctx.restore(); }
  for(const n of S.g.nodes){
    if(!visible(n)) continue;
    const x=SX(n),y=SY(n),rr=rad(n); const d=dim(n);
    // focus mode fades unconnected; "assigned to me" fades everything not owned by me.
    const notMine = S.mineOnly && S.analyst && S.assign[n.id]!==S.analyst && !(S.sel&&S.sel.id===n.id);
    const faded=orphanDimmed(n) || notMine;
    const isSel=S.sel&&S.sel.id===n.id;
    if(isSel){ ctx.save(); ctx.globalAlpha=0.22; ctx.beginPath(); ctx.arc(x,y,rr+9,0,7);
      ctx.fillStyle=accent; ctx.fill(); ctx.restore(); }   // soft selection halo
    ctx.beginPath(); ctx.arc(x,y,rr,0,7); ctx.fillStyle=nodeColor(n);
    ctx.globalAlpha = d?0.14:(faded?0.10:1); ctx.fill();
    if(isSel){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle=selColor; ctx.stroke(); }
    if(S.pick.includes(n.id)){ ctx.globalAlpha=1; ctx.lineWidth=2.5; ctx.strokeStyle=accent; ctx.stroke(); }
    ctx.globalAlpha=1;
    // Analyst annotation marker: a small coloured ring badge (confirmed/disputed/pending).
    const an=S.ann[n.id];
    if(an && an.status && an.status!=='none' && !d){
      const col={confirmed:'#2bb7a3',disputed:'#e0555b',pending:'#f2c14e'}[an.status]||'#8a94a6';
      ctx.beginPath(); ctx.arc(x+rr*0.72, y-rr*0.72, 3.4, 0, 7);
      ctx.fillStyle=col; ctx.fill(); ctx.lineWidth=1; ctx.strokeStyle='#fff'; ctx.stroke();
    }
    // Assignment cue: a small square badge (accent if it's mine, muted otherwise) + a name tag.
    const who=S.assign[n.id];
    if(who && !d){
      const mine = S.analyst && who===S.analyst;
      ctx.fillStyle = mine ? (cssv('--acc')||'#4f6bff') : '#8a94a6';
      ctx.fillRect(x-rr*0.72-3, y-rr*0.72-3, 6, 6);
      if(S.topRank.has(n.id) || rr*S.scale>6 || mine){
        ctx.fillStyle=labelColor; ctx.font='9px ui-sans-serif,system-ui';
        ctx.fillText('@'+who.slice(0,12), x+rr+4, y+rr+2); }
    }
    // Always label the top-PageRank nodes (scan-at-a-glance); others only when zoomed in.
    // Never label a dimmed/faded node.
    if(!d && !faded && (S.topRank.has(n.id) || rr*S.scale>6)){
      ctx.fillStyle=labelColor; ctx.font='11px ui-sans-serif,system-ui';
      ctx.fillText(n.name.slice(0,24), x+rr+4, y+3.5); }
  }
  // Count what's actually on screen, so the footer tracks the tag/relation-type filters.
  let shownEdges=0; for(const e of S.g.edges) if(edgeShown(e)) shownEdges++;
  const filtered = shownEdges!==S.g.edges.length ? ` of ${S.g.edges.length}` : '';
  const base = S.g.truncated ? `showing ${S.g.shown} of ${S.g.total} entities (top by PageRank)`
    : `${S.g.nodes.length} entities · ${shownEdges}${filtered} relations shown`;
  note.textContent = S.orphanCount
    ? `${base} · ${S.orphanCount} unconnected ${S.focusOrphans?'faded':'shown'} (F)`
    : base;
  drawMinimap(r);
}

// -- Mini-map: a corner overview with a viewport rectangle, essential past ~500 nodes -----
// Returns the world->minimap transform so click/drag can invert it to a pan.
function minimapTransform(mmw, mmh){
  const ns=S.g.nodes; if(!ns.length) return null;
  let minx=1e9,maxx=-1e9,miny=1e9,maxy=-1e9;
  for(const n of ns){ if(n.x<minx)minx=n.x; if(n.x>maxx)maxx=n.x; if(n.y<miny)miny=n.y; if(n.y>maxy)maxy=n.y; }
  const pad=8, sx=(mmw-2*pad)/((maxx-minx)||1), sy=(mmh-2*pad)/((maxy-miny)||1);
  const s=Math.min(sx,sy);
  const ox=pad+(mmw-2*pad-(maxx-minx)*s)/2, oy=pad+(mmh-2*pad-(maxy-miny)*s)/2;
  return { s, mx:v=>ox+(v-minx)*s, my:v=>oy+(v-miny)*s, minx, miny, ox, oy };
}
function drawMinimap(stageRect){
  const mm=document.getElementById('minimap'); if(!mm) return;
  if(!S.g||S.g.nodes.length<12){ mm.style.display='none'; return; }  // pointless for tiny graphs
  mm.style.display='block';
  const dpr=devicePixelRatio||1, W=150, H=108;
  if(mm.width!==W*dpr){ mm.width=W*dpr; mm.height=H*dpr; mm.style.width=W+'px'; mm.style.height=H+'px'; }
  const m=mm.getContext('2d'); m.setTransform(dpr,0,0,dpr,0,0); m.clearRect(0,0,W,H);
  const t=minimapTransform(W,H); if(!t) return;
  // Nodes as faint dots (heatmap-aware, so contested zones show in the overview too).
  for(const n of S.g.nodes){ if(!visible(n)) continue;
    m.beginPath(); m.arc(t.mx(n.x), t.my(n.y), 1.4, 0, 7);
    m.fillStyle=nodeColor(n); m.globalAlpha=(S.heat&&!n.contradictions)?0.35:0.75; m.fill(); }
  m.globalAlpha=1;
  // Viewport rectangle: invert the main SX/SY (screen = world*scale + t) back to world, then
  // to minimap space.
  const wx0=(0-S.tx)/S.scale, wy0=(0-S.ty)/S.scale;
  const wx1=(stageRect.width-S.tx)/S.scale, wy1=(stageRect.height-S.ty)/S.scale;
  const rx=t.mx(wx0), ry=t.my(wy0), rw=(wx1-wx0)*t.s, rh=(wy1-wy0)*t.s;
  m.strokeStyle=cssv('--acc')||'#4f6bff'; m.lineWidth=1.4;
  m.strokeRect(Math.max(0,rx), Math.max(0,ry), Math.min(W,rw), Math.min(H,rh));
}
// Click / drag on the mini-map recentres the main view on that world point.
function minimapPanTo(clientX, clientY){
  const mm=document.getElementById('minimap'); const r=mm.getBoundingClientRect();
  const t=minimapTransform(r.width, r.height); if(!t) return;
  const lx=clientX-r.left, ly=clientY-r.top;
  const wx=t.minx+(lx-t.ox)/t.s, wy=t.miny+(ly-t.oy)/t.s;   // minimap -> world
  const sr=c.getBoundingClientRect();
  _anim++; S.tx=sr.width/2-wx*S.scale; S.ty=sr.height/2-wy*S.scale; draw();
}

function hit(mx,my){ let best=null,bd=1e9;
  for(const n of S.g.nodes){ if(!visible(n)) continue;   // faded nodes are still clickable
    const dx=SX(n)-mx, dy=SY(n)-my, d=Math.hypot(dx,dy), rr=Math.max(7,rad(n));
    if(d<rr && d<bd){ bd=d; best=n; } } return best; }

// Smooth camera glide (easeInOutQuad) — used when a pick recentres the view.
let _anim=0;
function animateTo(tx,ty,scale,ms){
  const sx=S.tx, sy=S.ty, ss=S.scale, t0=performance.now(), id=++_anim;
  (function step(now){ if(id!==_anim) return;           // a newer animation supersedes this one
    let k=Math.min(1,(now-t0)/ms); k=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
    S.tx=sx+(tx-sx)*k; S.ty=sy+(ty-sy)*k; S.scale=ss+(scale-ss)*k; draw();
    if(k<1) requestAnimationFrame(step); })(t0);
}
function focusNode(n){ const r=c.getBoundingClientRect();   // glide the node toward centre
  animateTo(r.width/2-n.x*S.scale, r.height/2-n.y*S.scale, S.scale, 420); }
function clearSelection(){                                // "undo" a click: back to the full map
  S.sel=null; S.match=null; S.pathEdges=new Set(); S.predEdges=new Set();
  const d=document.getElementById('detail');
  if(d) d.innerHTML='<div class="empty">Click a node to inspect its cited claims.</div>';
  draw();
}

let drag=null;
c.addEventListener('mousedown',e=>{ _anim++;   // manual control cancels any camera glide
  drag={x:e.clientX,y:e.clientY,tx:S.tx,ty:S.ty,moved:0}; c.classList.add('grabbing'); });
addEventListener('mouseup',e=>{
  if(drag && drag.moved<4){ const r=c.getBoundingClientRect(); const n=hit(e.clientX-r.left,e.clientY-r.top);
    if(n) onPick(n);
    else if(!S.pathMode) clearSelection();   // click on empty canvas = deselect
  }
  drag=null; c.classList.remove('grabbing'); });
addEventListener('keydown',e=>{
  if(document.activeElement.tagName==='INPUT') return;
  if(e.key==='Escape'){ if(S.ego) setEgo(false); else clearSelection(); }
  if(e.key==='f'||e.key==='F'){ S.focusOrphans=!S.focusOrphans; syncRail&&syncRail(); draw(); }
});
addEventListener('mousemove',e=>{
  const r=c.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  if(drag){ drag.moved+=Math.abs(e.movementX)+Math.abs(e.movementY);
    S.tx=drag.tx+(e.clientX-drag.x); S.ty=drag.ty+(e.clientY-drag.y); draw(); return; }
  if(mx<0||my<0||mx>r.width||my>r.height){ tip.style.display='none'; return; }
  const n=hit(mx,my);
  if(n){ tip.style.display='block'; tip.style.left=(mx+14)+'px'; tip.style.top=(my+8)+'px';
    tip.innerHTML=`<b>${esc(n.name)}</b>${n.community_label?' · '+esc(n.community_label):''}`; c.style.cursor='pointer'; }
  else { tip.style.display='none'; c.style.cursor=drag?'grabbing':'grab'; } });
// Mini-map: click or drag to recentre the main view on that overview point.
(function(){ const mm=document.getElementById('minimap'); if(!mm) return; let mdrag=false;
  mm.addEventListener('mousedown',e=>{ e.preventDefault(); e.stopPropagation(); mdrag=true;
    minimapPanTo(e.clientX,e.clientY); });
  addEventListener('mousemove',e=>{ if(mdrag) minimapPanTo(e.clientX,e.clientY); });
  addEventListener('mouseup',()=>{ mdrag=false; });
})();
c.addEventListener('wheel',e=>{ e.preventDefault(); _anim++; const r=c.getBoundingClientRect();
  const mx=e.clientX-r.left,my=e.clientY-r.top, f=e.deltaY<0?1.1:1/1.1;
  S.tx=mx-(mx-S.tx)*f; S.ty=my-(my-S.ty)*f; S.scale*=f; draw(); },{passive:false});

function neighborsOf(id){ const set=new Set([id]); const edges=new Set();
  for(const e of S.g.edges){ if(!edgeShown(e)) continue;
    if(e.source===id){ set.add(e.target); edges.add(e.source+'>'+e.target); }
    else if(e.target===id){ set.add(e.source); edges.add(e.source+'>'+e.target); } }
  return {set,edges}; }

// -- Ego / distance intelligence: colour the graph by hops from a focus node ----
function egoAdjacency(){
  // Built from the *filtered* edge set (and cached), so hop distance reflects the relation
  // types on screen. `applyPredFilter` drops the cache so the bands recompute.
  if(S.egoAdj) return S.egoAdj; const m={};
  for(const e of S.g.edges){ if(!edgeShown(e)) continue;
    (m[e.source]=m[e.source]||[]).push(e.target);
    (m[e.target]=m[e.target]||[]).push(e.source); }
  S.egoAdj=m; return m;
}
function computeEgo(anchor){                 // BFS out to S.egoDepth hops
  const adj=egoAdjacency(), dist=new Map([[anchor,0]]); let frontier=[anchor];
  for(let d=1; d<=S.egoDepth && frontier.length; d++){ const next=[];
    for(const u of frontier) for(const v of (adj[u]||[])){ if(!dist.has(v)){ dist.set(v,d); next.push(v); } }
    frontier=next; }
  return dist;
}
function renderEgoBar(){
  const bar=document.getElementById('egobar'); if(!bar) return;
  bar.classList.toggle('on', S.ego); if(!S.ego){ bar.innerHTML=''; return; }
  const a=S.egoAnchor&&S.byId[S.egoAnchor]?S.byId[S.egoAnchor]:null;
  const count=S.egoDist?S.egoDist.size:0;
  const head = a ? `<span class="eg-anchor">Ego &middot; <span class="mut">focus</span> ${esc(a.name)}`
      +` &middot; ${count} within ${S.egoDepth} hops</span>`
    : `<span class="eg-anchor mut">Ego &middot; click a node to set the focus</span>`;
  const leg = `<span class="eg-legend">`
    +`<span class="lg"><span class="dot" style="background:${EGO_COLORS.anchor}"></span>0h</span>`
    +`<span class="lg"><span class="dot" style="background:${EGO_COLORS.h1}"></span>1h</span>`
    +`<span class="lg"><span class="dot" style="background:${EGO_COLORS.h23}"></span>2-3h</span>`
    +`<span class="lg"><span class="dot" style="background:${EGO_COLORS.h46}"></span>4+h</span></span>`;
  bar.innerHTML = head
    +`<span class="eg-depth">depth <input type="range" id="egodepth" min="1" max="6" value="${S.egoDepth}"> ${S.egoDepth}h</span>`
    + leg + `<button class="eg-x" id="egoclose" title="exit ego view">&times;</button>`;
  const sl=document.getElementById('egodepth'); if(sl) sl.oninput=()=>{ S.egoDepth=+sl.value; reEgo(); };
  const x=document.getElementById('egoclose'); if(x) x.onclick=()=>setEgo(false);
}
function reEgo(){
  if(!S.egoAnchor){ S.egoDist=null; S.match=null; renderEgoBar(); draw(); return; }
  S.egoDist=computeEgo(S.egoAnchor); S.match=new Set(S.egoDist.keys());
  S.sel=S.byId[S.egoAnchor]||null; renderEgoBar(); draw();
}
function setEgo(on){
  if(on && S.heat) setHeat(false);   // one colour encoding at a time
  S.ego=on; document.getElementById('egobtn').classList.toggle('on',on);
  const r=document.getElementById('r-ego'); if(r) r.classList.toggle('on',on);
  document.getElementById('legend').style.display = on ? 'none' : '';  // bands replace type legend
  if(on){ if(!S.egoAnchor && S.sel) S.egoAnchor=S.sel.id; reEgo(); }
  else { S.egoDist=null; S.egoAnchor=null; S.match=null; renderEgoBar(); draw(); }
}

function onPick(n){
  if(S.ego){ S.egoAnchor=n.id; reEgo(); focusNode(n); inspect(n); return; }   // re-root the ego view
  if(S.pathMode){ S.pick.push(n.id); if(S.pick.length===2){ runPath(); } draw(); return; }
  if(S.sel && S.sel.id===n.id){ clearSelection(); return; }   // click the same node = undo
  S.sel=n;
  const nb=neighborsOf(n.id);           // click-to-expand: light up the node's neighbourhood
  S.match = nb.set.size>1 ? nb.set : null;
  S.pathEdges = nb.edges;
  focusNode(n);                          // glide the picked node toward centre
  draw(); inspect(n);
}

function citeStr(cs){ return (cs||[]).map(x=>`[${x.doc_id.slice(0,18)}…:${x.start}-${x.end}]`).join(' '); }
function win(c){ if(c.t_valid&&c.t_invalid) return `<span class="win sup">valid [${c.t_valid}, ${c.t_invalid}) · superseded</span>`;
  if(c.t_valid) return `<span class="win">valid [${c.t_valid}, now)</span>`; return ''; }
async function inspect(n){
  const d=document.getElementById('detail');
  d.innerHTML=`<div class="title">${esc(n.name)}</div><div class="sub">${esc(n.community_label||'')} · pr ${n.pagerank}</div><div class="empty">loading…</div>`;
  // Admin view when the live server offers /api/inspect; fall back to why() offline.
  const data = (typeof TG.inspect==='function') ? await TG.inspect(n.id) : await TG.why(n.id);
  let h=`<div class="title">${esc(n.name)}</div><div class="sub">${esc(n.community_label||'')} · pr ${n.pagerank}</div>`;
  if(data.provenance && data.provenance.length){
    h+=`<div class="adm"><span class="k">provenance</span> <span class="cite">${esc(citeStr(data.provenance))}</span></div>`; }
  if(data.confidence_tiers && Object.keys(data.confidence_tiers).length){
    h+=`<div class="adm"><span class="k">tiers</span> `+Object.entries(data.confidence_tiers).map(([t,c])=>`<span class="pill">${esc(t)} ${c}</span>`).join(' ')+`</div>`; }
  if(data.same_as && data.same_as.canonical){
    h+=`<div class="adm"><span class="k">SAME_AS</span> → ${esc(data.same_as.canonical)} <span class="cite">(${(data.same_as.members||[]).map(esc).join(', ')})</span></div>`; }
  if(data.superseded_claims && data.superseded_claims.length){
    h+=`<div class="adm sup"><span class="k">invalidated</span> ${data.superseded_claims.length} superseded claim(s)</div>`; }
  if((data.claims||[]).length){ for(const c of data.claims){
    h+=`<div class="fact ${c.status==='superseded'?'sup':''}">${esc(c.subject)} —${esc(c.predicate)}→ ${esc(c.object)}${c.polarity==='neg'?' (negated)':''}<br>${win(c)}<div class="cite">${esc(citeStr(c.citations))}</div></div>`; }
  } else h+='<div class="empty">no claims</div>';
  h+=annotationEditor(n.id);
  d.innerHTML=h;
  wireAnnotationEditor(n.id);
}
// Analyst annotation + assignment editor: status, note, and who owns the entity. Saved to the
// shared sidecar with attribution; live server only.
function annotationEditor(nid){
  if(typeof TG==='undefined' || typeof TG.annotate!=='function') return '';
  const a=S.ann[nid]||{status:'none',note:''};
  const opt=(v,label)=>`<option value="${v}"${a.status===v?' selected':''}>${label}</option>`;
  const by = a.author ? `<div class="annby">last edited by <b>${esc(a.author)}</b>${a.updated?' · '+esc(a.updated):''}</div>` : '';
  const assignee = S.assign[nid]||'';
  return `<div class="annot"><div class="ah">Analyst note</div>`
    +`<select id="annstatus" class="annsel">`
    +opt('none','— unset —')+opt('confirmed','Confirmed')+opt('disputed','Disputed')+opt('pending','Pending')
    +`</select>`
    +`<textarea id="annnote" class="annnote" placeholder="add a note (shared with your team)…">${esc(a.note||'')}</textarea>`
    +`<div class="annrow"><button type="button" id="annsave" class="minibtn">Save note</button>`
    +`<span id="annstate" class="mut"></span></div>`+by
    +`<div class="ah" style="margin-top:10px">Assignment</div>`
    +`<div class="annrow"><input id="annassign" class="annsel" style="flex:1" placeholder="analyst name" value="${esc(assignee)}">`
    +`<button type="button" id="annassignbtn" class="minibtn">Assign</button></div>`
    +(S.analyst?`<button type="button" id="annassignme" class="minibtn" style="margin-top:6px">Assign to me</button>`:'')
    +`</div>`;
}
function wireAnnotationEditor(nid){
  const sel=document.getElementById('annstatus'), note=document.getElementById('annnote'),
    save=document.getElementById('annsave'), st=document.getElementById('annstate');
  if(!save) return;
  const doSave=async()=>{
    st.textContent='saving…';
    try{ const r=await TG.annotate(nid, sel.value, note.value);
      if(r&&r.ok){ if(r.annotation.status==='none'&&!r.annotation.note) delete S.ann[nid];
        else S.ann[nid]=r.annotation; if(r.version!=null) S.collabV=r.version; st.textContent='saved'; draw(); }
      else st.textContent='save failed';
    }catch(e){ st.textContent='save failed'; }
  };
  save.onclick=doSave; sel.onchange=doSave;
  const assignIn=document.getElementById('annassign'), assignBtn=document.getElementById('annassignbtn');
  const doAssign=async(who)=>{
    try{ const r=await TG.assign(nid, who);
      if(r&&r.ok){ if(r.assignee) S.assign[nid]=r.assignee; else delete S.assign[nid];
        if(r.version!=null) S.collabV=r.version; assignIn.value=r.assignee||''; draw(); } }catch(e){}
  };
  if(assignBtn) assignBtn.onclick=()=>doAssign(assignIn.value.trim());
  const me=document.getElementById('annassignme');
  if(me) me.onclick=()=>doAssign(S.analyst);
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
  const d=document.getElementById('detail');
  if(!S.q){ S.match=null; S.sel=null; draw();
    d.innerHTML='<div class="empty">Click a node to inspect its cited claims.</div>'; return; }
  let res; try{ res=await TG.search(S.q); }catch(e){
    d.innerHTML=`<div class="title">Search · "${esc(S.q)}"</div><div class="empty">search error: ${esc(e.message||e)}</div>`; return; }
  // Only entities actually on the canvas (the top-N view) can be highlighted.
  const matched=new Set(); const ql=S.q.toLowerCase();
  for(const hit of (res.hits||[])){ if(hit.kind==='entity' && S.byId[hit.node_id]) matched.add(hit.node_id); }
  for(const n of S.g.nodes){ if(n.name.toLowerCase().includes(ql)) matched.add(n.id); }
  const chunks=(res.hits||[]).filter(h=>h.kind==='chunk');
  const chunkHtml=chunks.map(h=>`<div class="fact">${esc(_clip(h.snippet||h.name,240))}<div class="cite">${esc(citeStr(h.citations))}</div></div>`).join('');
  if(matched.size===0){
    // No entity on the canvas matched — keep the whole graph visible (don't fade everything).
    S.match=null; S.sel=null; draw();
    const note = (res.hits&&res.hits.length) ? `${res.hits.length} passage match(es), but no shown entity` : 'no matches';
    d.innerHTML=`<div class="title">Search · "${esc(S.q)}"</div><div class="sub">${esc(note)}</div>`
      + (chunkHtml||'<div class="empty">Try an entity name you can see on the graph.</div>');
    return;
  }
  S.match=matched; S.sel=null; S.pathEdges=new Set();
  fitNodes([...matched]);   // glide the camera to the matches so you actually see them
  draw();
  d.innerHTML=`<div class="title">Search · "${esc(S.q)}"</div><div class="sub">${esc(res.routing||'')} routing · ${matched.size} match(es) shown</div>`
    + (chunkHtml||'<div class="empty">no passages</div>');
}
function _clip(s,n){ s=String(s||''); return s.length>n?s.slice(0,n)+'…':s; }

// Grouped layout: pack each community into its own tidy circular cluster laid out on a grid,
// so the community "bubbles" are separated and readable (instead of overlapping hulls). Node
// positions are saved first and restored when Group is turned off.
function groupLayout(){
  if(!S._preGroup){ S._preGroup={}; S.g.nodes.forEach(n=>{ S._preGroup[n.id]={x:n.x,y:n.y}; }); }
  const byComm={};
  for(const n of S.g.nodes){ const c=(n.community==null?-1:n.community);
    (byComm[c]=byComm[c]||[]).push(n); }
  const clusters=Object.entries(byComm).filter(([c,ns])=>c!=='-1'&&ns.length>=2)
    .sort((a,b)=>b[1].length-a[1].length);
  const singles=[]; for(const [c,ns] of Object.entries(byComm)){ if(c==='-1'||ns.length<2) singles.push(...ns); }
  const cols=Math.max(1,Math.ceil(Math.sqrt(clusters.length))), cell=560;
  clusters.forEach(([c,ns],i)=>{
    const gx=(i%cols)*cell, gy=Math.floor(i/cols)*cell, rad=34+Math.sqrt(ns.length)*30;
    ns.sort((a,b)=>b.pagerank-a.pagerank);
    ns.forEach((n,j)=>{ const a=2.399963*j, r=rad*Math.sqrt((j+0.5)/ns.length);
      n.x=gx+Math.cos(a)*r; n.y=gy+Math.sin(a)*r; });
  });
  const rows=Math.max(1,Math.ceil(clusters.length/cols)), spanX=cols*cell;
  const baseY=rows*cell+cell*0.35;   // singletons drift in a loose band below the clusters
  singles.forEach((n,i)=>{ const a=2.399963*i, r=Math.sqrt(i+1)*26;
    n.x=(spanX/2-cell/2)+Math.cos(a)*r; n.y=baseY+Math.sin(a)*r*0.5; });
}
function ungroupLayout(){
  if(!S._preGroup) return;
  S.g.nodes.forEach(n=>{ const p=S._preGroup[n.id]; if(p){ n.x=p.x; n.y=p.y; } });
  S._preGroup=null;
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

// Force-directed re-layout (Fruchterman-Reingold). The server ships positions that
// scatter when the graph is sparse; this self-organizes connected nodes into a
// NotebookLM-style radial mindmap and scatters the few unlinked nodes in a filled
// halo disc (a Vogel spiral, not a hard ring) so the map fills the whole canvas.
function relayout(){
  if(!S.g||!S.g.nodes.length) return;
  const nodes=S.g.nodes, deg={}; nodes.forEach(n=>deg[n.id]=0);
  const links=[];
  for(const e of S.g.edges){ const a=S.byId[e.source], b=S.byId[e.target];
    if(a&&b&&a!==b){ deg[a.id]++; deg[b.id]++; links.push([a,b]); } }
  const conn=nodes.filter(n=>deg[n.id]>0), iso=nodes.filter(n=>!deg[n.id]);
  if(conn.length<2) return;                       // no relations -> keep server layout
  const N=conn.length, k=Math.sqrt(1000*1000/N);
  conn.forEach((n,i)=>{ const a=2.399963*i, r=k*Math.sqrt(i+1)*0.5;
    n.x=Math.cos(a)*r; n.y=Math.sin(a)*r; });     // deterministic phyllotaxis seed
  const ITERS=N>350?120:200; let temp=k*0.9;
  for(let it=0; it<ITERS; it++){
    for(const n of conn){ n._dx=0; n._dy=0; }
    for(let i=0;i<N;i++){ const v=conn[i];
      for(let j=i+1;j<N;j++){ const u=conn[j];
        let dx=v.x-u.x, dy=v.y-u.y, d=Math.hypot(dx,dy)||0.01, f=k*k/d;
        const ux=dx/d*f, uy=dy/d*f; v._dx+=ux; v._dy+=uy; u._dx-=ux; u._dy-=uy; } }
    for(const [a,b] of links){ let dx=a.x-b.x, dy=a.y-b.y, d=Math.hypot(dx,dy)||0.01, f=d*d/k;
      const ux=dx/d*f, uy=dy/d*f; a._dx-=ux; a._dy-=uy; b._dx+=ux; b._dy+=uy; }
    for(const n of conn){ let d=Math.hypot(n._dx,n._dy)||0.01;
      n.x+=n._dx/d*Math.min(d,temp); n.y+=n._dy/d*Math.min(d,temp); n.x*=0.998; n.y*=0.998; }
    temp*=0.97;
  }
  // Scatter unlinked nodes as a FILLED disc surrounding the connected core (Vogel spiral:
  // r ~ sqrt(i) fills area evenly), so they read as a spread halo, never a hard circle.
  let R=300; conn.forEach(n=>{ R=Math.max(R,Math.hypot(n.x,n.y)); });
  const gA=Math.PI*(3-Math.sqrt(5)), inner=R*0.55, span=R*1.15;
  iso.forEach((n,i)=>{ const t=Math.sqrt((i+0.5)/(iso.length||1)), a=i*gA;
    const rr=inner+span*t; n.x=Math.cos(a)*rr; n.y=Math.sin(a)*rr; });
}

function buildSidebar(){
  const cw=document.getElementById('comms'); cw.innerHTML='';
  // Singleton communities are just isolated entities — hundreds of one-node "clusters" are
  // noise, not structure. Show only the real (size>=2) macro-clusters, then a single summary
  // row for everything that stands alone.
  const CAP=40, all=S.g.communities;
  const macro=all.filter(cm=>cm.size>=2), singles=all.filter(cm=>cm.size<2);
  const shown=macro.slice(0,CAP);
  for(const cm of shown){ const row=document.createElement('div'); row.className='crow';
    row.innerHTML=`<input type="checkbox" checked><span class="dot" style="background:${color(cm.community_id)}"></span><span class="lbl">${esc(cm.label||('#'+cm.community_id))}</span><span class="ct">${cm.size}</span>`;
    const cb=row.querySelector('input');
    row.onclick=e=>{ if(e.target!==cb) cb.checked=!cb.checked;
      if(cb.checked) S.hidden.delete(cm.community_id); else S.hidden.add(cm.community_id);
      document.getElementById('all').checked=S.hidden.size===0; draw(); };
    cw.appendChild(row); }
  if(macro.length>CAP){ const more=document.createElement('div'); more.className='crow';
    more.style.cursor='default'; more.innerHTML=`<span class="lbl mut">+ ${macro.length-CAP} smaller clusters</span>`;
    cw.appendChild(more); }
  if(singles.length){ const row=document.createElement('div'); row.className='crow';
    row.style.cursor='default';
    row.innerHTML=`<span class="dot" style="background:var(--mut)"></span><span class="lbl mut">${singles.length} isolated entities</span>`;
    cw.appendChild(row); }
  const tw=document.getElementById('tags'); tw.innerHTML='';
  for(const t of TAGS){ const el=document.createElement('span'); el.className='tag'; el.textContent=t;
    el.style.borderColor='var(--line)';
    el.onclick=()=>{ if(S.tags.has(t)){S.tags.delete(t);el.classList.add('off');} else {S.tags.add(t);el.classList.remove('off');}
      computeDerived(); draw(); };
    tw.appendChild(el); }
  buildPredBar();
}
// Relation-type chips, most frequent first, each with its edge count. Clicking one toggles
// that predicate across the whole view (drawing, degree, neighbours, ego).
function buildPredBar(){
  const pw=document.getElementById('preds'); if(!pw) return;
  pw.innerHTML='';
  const preds=Object.keys(S.predCounts).sort((a,b)=>
    S.predCounts[b]-S.predCounts[a] || (a<b?-1:1));
  for(const p of preds){
    const el=document.createElement('span');
    el.className='tag'+(p===BACKBONE?' backbone':'')+(S.preds.has(p)?'':' off');
    el.innerHTML=`${esc(p.replace(/_/g,' '))}<span class="n">${S.predCounts[p]}</span>`;
    el.title=`${p} — ${S.predCounts[p]} edge${S.predCounts[p]===1?'':'s'}`;
    el.onclick=()=>{ if(S.preds.has(p)) S.preds.delete(p); else S.preds.add(p); applyPredFilter(); };
    pw.appendChild(el);
  }
  const hint=document.getElementById('predhint');
  if(hint){ const on=S.preds.size, all=preds.length;
    hint.textContent = on===all ? `${all}` : `${on}/${all}`; }
}
function setPreds(keep){        // keep: predicate -> boolean
  const preds=Object.keys(S.predCounts);
  S.preds=new Set(preds.filter(keep));
  applyPredFilter();
}
// "Semantic only" drops the co-occurrence scaffold and leaves the meaning relations — the
// fastest way to go from a dense backbone to the story the corpus actually states.
function semanticOnly(){ setPreds(p=>p!==BACKBONE); }
function wirePredButtons(){
  const all=document.getElementById('predall'), sem=document.getElementById('predsem');
  if(all) all.onclick=()=>setPreds(()=>true);
  if(sem) sem.onclick=()=>{
    // Toggle: a second press restores everything, so the button is its own undo.
    if(!S.preds.has(BACKBONE) && S.preds.size===Object.keys(S.predCounts).length-1) setPreds(()=>true);
    else semanticOnly();
  };
}
function initTime(){
  const dates = S.g.dates || [];
  const box=document.getElementById('time'), sl=document.getElementById('tslider'),
    lab=document.getElementById('tlabel'), play=document.getElementById('tplay');
  if(!dates.length){ box.style.display='none'; stopTimeline(); return; }
  box.style.display='flex'; sl.max=String(dates.length); sl.value='0';
  // Apply keyframe index i (0 = all time, 1..n = up to dates[i-1]).
  const setDate=(i)=>{ sl.value=String(i); S.date = i===0 ? null : dates[i-1];
    lab.textContent = S.date || 'all time';
    const anySup = S.date && S.g.edges.some(e=>e.t_invalid && S.date>=e.t_invalid);
    lab.classList.toggle('sup', !!anySup); draw(); };
  sl.oninput=()=>{ stopTimeline(); setDate(+sl.value); };  // scrubbing by hand pauses playback
  S._setDate=setDate;
  play.onclick=()=>{ S.playing ? stopTimeline() : playTimeline(); };
}
// Timeline animation: step through the keyframes so edges appear/disappear as claims become
// valid/invalid. Deterministic order (the sorted `dates`); wraps from the end back to "all time".
function playTimeline(){
  const dates=S.g.dates||[]; if(dates.length<1||!S._setDate) return;
  S.playing=true; document.getElementById('tplay').innerHTML='&#10073;&#10073;';  // pause glyph
  document.getElementById('tplay').title='pause';
  if(+document.getElementById('tslider').value>=dates.length) S._setDate(0);  // restart from start
  S.playTimer=setInterval(()=>{
    const sl=document.getElementById('tslider'); const next=+sl.value+1;
    if(next>dates.length){ stopTimeline(); return; }   // stop at the final keyframe
    S._setDate(next);
  }, 1100);
}
function stopTimeline(){
  if(S.playTimer){ clearInterval(S.playTimer); S.playTimer=null; }
  S.playing=false; const play=document.getElementById('tplay');
  if(play){ play.innerHTML='&#9654;'; play.title='play the timeline'; }
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
// Keep the left-rail shortcut buttons visually in sync with the header toggles.
function syncRail(){
  const solo=document.getElementById('body').classList.contains('solo');
  document.getElementById('r-ego').classList.toggle('on', S.ego);
  document.getElementById('r-group').classList.toggle('on', S.grouped);
  document.getElementById('r-focus').classList.toggle('on', S.focusOrphans);
  document.getElementById('r-panel').classList.toggle('on', solo);
}
document.getElementById('fit').onclick=fit;
document.getElementById('panel').onclick=()=>{
  const b=document.getElementById('body'); b.classList.toggle('solo');
  document.getElementById('panel').classList.toggle('on', b.classList.contains('solo'));
  syncRail(); setTimeout(()=>{ resize(); fit(); }, 210); };  // transition then refit
document.getElementById('groupbtn').onclick=()=>{ S.grouped=!S.grouped;
  document.getElementById('groupbtn').classList.toggle('on',S.grouped); syncRail();
  if(S.grouped) groupLayout(); else ungroupLayout(); fit(); };
document.getElementById('egobtn').onclick=()=>setEgo(!S.ego);
document.getElementById('pathbtn').onclick=()=>setPathMode(!S.pathMode);
document.getElementById('heatbtn').onclick=()=>setHeat(!S.heat);
// Contradiction heatmap: recolour nodes by contested-claim load, and swap the legend for a
// red intensity scale. No-op-friendly: when nothing contradicts, every node is neutral.
function setHeat(on){
  S.heat=on; document.getElementById('heatbtn').classList.toggle('on',on);
  if(on && S.ego) setEgo(false);   // one colour encoding at a time
  buildLegend(); draw();
}
// Left-rail shortcuts proxy to the header controls (single source of truth for behaviour).
document.getElementById('r-fit').onclick=fit;
document.getElementById('r-ego').onclick=()=>document.getElementById('egobtn').click();
document.getElementById('r-group').onclick=()=>document.getElementById('groupbtn').click();
document.getElementById('r-focus').onclick=()=>{ S.focusOrphans=!S.focusOrphans; syncRail(); draw(); };
document.getElementById('r-panel').onclick=()=>document.getElementById('panel').click();
document.getElementById('r-theme').onclick=()=>document.getElementById('theme').click();
// Collapsible inspector sections: a header folds every following sibling up to the next
// header (or the always-on #detail pane).
document.querySelectorAll('aside h2').forEach(h=>{
  h.classList.add('sec');
  h.onclick=()=>{ h.classList.toggle('collapsed'); const off=h.classList.contains('collapsed');
    let el=h.nextElementSibling;
    while(el && el.tagName!=='H2' && el.id!=='detail'){ el.style.display=off?'none':''; el=el.nextElementSibling; }
  };
});
document.getElementById('q').addEventListener('keydown',e=>{ if(e.key==='Enter') search();
  if(e.key==='Escape'){ e.target.value=''; S.match=null; draw(); } });
addEventListener('resize',resize);

// -- Ask dock (grounded chat) ------------------------------------------------
// Citation chips are clickable when a server is present (TG.source) — clicking opens the
// source panel at the exact byte span, re-verified. In the offline graph.html (no server)
// they stay inert text, so nothing regresses.
function citeChips(ev){ if(!(ev&&ev.length)) return '';
  const live = typeof TG!=='undefined' && typeof TG.source==='function';
  return '<div class="cites">'+ev.map(c=>{
    const label=`[${esc(c.doc_id.slice(0,14))}…:${c.start}-${c.end}]`;
    if(!live) return `<span class="cite-chip">${label}</span>`;
    return `<span class="cite-chip live" role="button" tabindex="0"`
      +` data-doc="${esc(c.doc_id)}" data-start="${c.start}" data-end="${c.end}"`
      +` data-hash="${esc(c.hash||'')}" title="View the cited source span">${label}</span>`;
  }).join('')+'</div>'; }
// Deterministic follow-up chips: each fills the Ask box and sends, so a click is a question.
function suggestChips(sugg){ if(!(sugg&&sugg.length)) return '';
  return '<div class="suggs">'+sugg.map(s=>
    `<button type="button" class="sugg" data-q="${esc(s)}">${esc(s)}</button>`).join('')+'</div>'; }
// Routing inspector: a collapsed "how this was answered" line for power users.
function routingHtml(r){ if(!r) return '';
  const bits=[];
  bits.push(`<div class="rrow"><span>tool</span><b>${esc(r.tool||'')}</b></div>`);
  if(r.forced) bits.push(`<div class="rrow"><span>forced</span><b>${esc(r.forced)}</b></div>`);
  if(r.focus) bits.push(`<div class="rrow"><span>focus</span><b>${esc(r.focus)}</b></div>`);
  if(r.rewritten) bits.push(`<div class="rrow"><span>resolved</span><b>${esc(r.rewritten)}</b></div>`);
  if(r.question) bits.push(`<div class="rrow"><span>as</span><b>${esc(r.question)}</b></div>`);
  return `<details class="routing"><summary>how this was answered</summary>${bits.join('')}</details>`; }
function chainHtml(detail){
  if(!detail||!detail.length||!detail[0].role) return '';
  const steps=detail.map(s=>`<div class="step"><b>${esc(s.role)}</b> ${esc(s.content)}</div>`).join('');
  return `<details class="chain"><summary>reasoning · ${detail.length} steps</summary>${steps}</details>`;
}
// Structured detail for the decision/conflict tools (reason uses chainHtml above).
function detailHtml(ans){
  const d=ans.detail||[]; if(!d.length) return '';
  if(ans.tool==='trace'){
    const steps=d.map(s=>`<div class="step"><b>${esc(s.from)}</b> &mdash;${esc(s.relation)}&rarr; <b>${esc(s.to)}</b> <span style="color:var(--mut)">(${esc(s.direction)})</span></div>`).join('');
    return `<details class="chain" open><summary>causal chain · ${d.length} hop(s)</summary>${steps}</details>`;
  }
  if(ans.tool==='contradictions' && d[0] && d[0].a){
    const clm=c=>`${esc(c.subject)} ${esc(c.predicate)} ${esc(c.object)}${c.polarity==='neg'?' <span style="color:var(--sup)">(negated)</span>':''}${c.t_valid?` <span style="color:var(--mut)">[${esc(c.t_valid)}]</span>`:''}`;
    const steps=d.map(p=>{
      const h=p.hint||{}; const rec=h.recommend==='a'?'A':h.recommend==='b'?'B':null;
      const badge=rec?`<span class="hint-rec">recommends ${rec}</span>`:`<span class="hint-rec none">manual review</span>`;
      return `<div class="step"><div class="cx"><span class="ca">A</span> ${clm(p.a)}</div>`
        +`<div class="cx"><span class="cb">B</span> ${clm(p.b)}</div>`
        +`<div class="hint">${badge} <span class="mut">${esc(h.reason||'')}</span></div></div>`;
    }).join('');
    return `<details class="chain" open><summary>${d.length} contradiction(s) · resolution hints</summary>${steps}</details>`;
  }
  if(ans.tool==='conflicts'){
    const steps=d.map(c=>`<div class="step"><b>[${esc(c.severity)}]</b> ${esc(c.subject)} <b>${esc(c.predicate)}</b> {${esc((c.objects||[]).join(', '))}}${c.resolved_object?` &rarr; <b>${esc(c.resolved_object)}</b>`:''}</div>`).join('');
    return `<details class="chain" open><summary>${d.length} conflict(s)</summary>${steps}</details>`;
  }
  if(ans.tool==='decisions'){
    const steps=d.map(h=>`<div class="step">[${esc(h.category)}] ${esc(h.name)} <span style="color:var(--mut)">(${(+h.score).toFixed(2)})</span></div>`).join('');
    return `<details class="chain" open><summary>${d.length} decision(s)</summary>${steps}</details>`;
  }
  if(ans.tool==='predict'){
    const steps=d.map(p=>`<div class="step"><b>${esc(p.source)}</b> &middot;&middot;&middot; <b>${esc(p.target)}</b> <span style="color:var(--mut)">(${(+p.score).toFixed(3)})</span>`
      +(p.shared&&p.shared.length?`<br><span style="color:var(--mut)">via ${esc(p.shared.slice(0,4).join(', '))}</span>`:'')+`</div>`).join('');
    return `<details class="chain" open><summary>${d.length} candidate link(s)</summary>${steps}</details>`;
  }
  if(ans.tool==='roles'){
    const steps=d.map(r=>`<div class="step"><b>${esc(r.name)}</b> <span style="color:var(--mut)">(${(+r.score).toFixed(3)}, degree ${r.degree})</span>`
      +(r.shared?`<br><span style="color:var(--mut)">mostly ${esc(r.shared)}</span>`:'')+`</div>`).join('');
    return `<details class="chain" open><summary>${d.length} structural peer(s)</summary>${steps}</details>`;
  }
  if(ans.tool==='rules'){
    const steps=d.map(r=>`<div class="step"><b>${esc(r.source)}</b> &mdash;${esc(r.predicate)}&rarr; <b>${esc(r.target)}</b>`
      +(r.support&&r.support.length?`<br><span style="color:var(--mut)">${esc(r.rule)}: ${esc(r.support.join('; '))}</span>`:'')+`</div>`).join('');
    return `<details class="chain" open><summary>${d.length} derived fact(s)</summary>${steps}</details>`;
  }
  return '';
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
function applyHighlight(h, tool){
  S.match=(h&&h.nodes&&h.nodes.length)?new Set(h.nodes):null;
  // Predicted "candidate" links are drawn dashed (they don't exist in the graph yet);
  // every other tool's highlighted edges are solid path edges.
  S.predEdges=new Set(); S.pathEdges=new Set();
  if(h&&h.edges){ const bucket = tool==='predict' ? S.predEdges : S.pathEdges;
    h.edges.forEach(e=>{ if(e[0]&&e[1]) bucket.add(e[0]+'>'+e[1]); }); }
  fitNodes(h&&h.nodes); draw();
}
let asking=false;
async function ask(forced){
  if(asking) return; const inp=document.getElementById('askq');
  const q=(typeof forced==='string'?forced:inp.value).trim(); if(!q) return;
  // A suggestion chip forces 'auto' routing (the phrasing already encodes the intent).
  const tool=(typeof forced==='string')?'auto':document.getElementById('asktool').value;
  addMsg('user',esc(q)); if(typeof forced!=='string') inp.value='';
  const send=document.getElementById('asksend'); asking=true; send.disabled=true;
  const bubble=addMsg('bot','<span style="color:var(--mut)">thinking…</span>');
  try{
    const ans=await TG.chat(q,{tool, focus:S.lastFocus||''});
    S.lastFocus=ans.focus||S.lastFocus;
    const conf = ans.abstained ? '<span class="conf abstain">abstained</span>'
      : (typeof ans.confidence==='number' ? `<span class="conf">${Math.round(ans.confidence*100)}% grounded</span>` : '');
    bubble.innerHTML=`<div class="tooltag">${esc(ans.tool)}${conf}</div>${esc(ans.text)}`
      +chainHtml(ans.detail)+detailHtml(ans)+citeChips(ans.evidence)
      +routingHtml(ans.routing)+suggestChips(ans.suggestions);
    applyHighlight(ans.highlight, ans.tool);
  }catch(e){ bubble.innerHTML='<span style="color:var(--sup)">error: '+esc(e.message||e)+'</span>'; }
  asking=false; send.disabled=false; document.getElementById('asklog').scrollTop=1e9;
}
async function reloadGraph(){
  S.g=await TG.graph(); S.byId={}; S.g.nodes.forEach(n=>S.byId[n.id]=n);
  S.egoAdj=null; S._preGroup=null;  // caches stale after a rebuild
  if(S.ego && S.egoAnchor && !S.byId[S.egoAnchor]) S.egoAnchor=null;  // focus removed
  computePredicates();
  relayout(); if(S.grouped) groupLayout(); computeDerived();
  buildStats(); buildSidebar(); buildTops(); buildLegend(); initTime(); fit();
  if(S.ego) reEgo();
}
async function attachFiles(files){
  if(!files||!files.length) return;
  addMsg('user','&#128206; '+esc([...files].map(f=>f.name).join(', ')));
  const bubble=addMsg('bot','<span style="color:var(--mut)">ingesting…</span>');
  try{
    const res=await TG.ingest(files);
    if(!res.ok){ bubble.innerHTML='<span style="color:var(--sup)">'+esc(res.error||'ingest failed')+
      (res.rejected&&res.rejected.length?' (rejected: '+esc(res.rejected.join(', '))+')':'')+'</span>'; return; }
    await reloadGraph(); buildDocs();
    const added=res.added_entities||[];
    bubble.innerHTML=`<div class="tooltag">ingest</div>Added ${esc(res.written.join(', '))} — `+
      `${added.length} new entit${added.length===1?'y':'ies'}`+
      (added.length?': '+esc(added.slice(0,8).join(', ')):'')+'.'+
      (res.rejected&&res.rejected.length?`<div class="cites">rejected: ${esc(res.rejected.join(', '))}</div>`:'');
  }catch(e){ bubble.innerHTML='<span style="color:var(--sup)">error: '+esc(e.message||e)+'</span>'; }
}
async function saveSnapshot(){
  const bubble=addMsg('bot','<span style="color:var(--mut)">exporting graph.json…</span>');
  try{
    const url=(typeof _u==='function')?_u('/api/export'):'/api/export';
    const resp=await fetch(url); if(!resp.ok) throw new Error('HTTP '+resp.status);
    const blob=await resp.blob();
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='graph.json';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    bubble.innerHTML=`<div class="tooltag">export</div>Saved <b>graph.json</b> (${Math.round(blob.size/1024)} KB) to your downloads.`;
  }catch(e){ bubble.innerHTML='<span style="color:var(--sup)">export failed: '+esc(e.message||e)+'</span>'; }
}
// -- Citation click-through: show the cited source span, re-verified server-side --------
async function openSource(ds){
  const panel=document.getElementById('srcpanel'), body=document.getElementById('srcbody'),
    ttl=document.getElementById('srctitle');
  panel.classList.add('open');
  ttl.textContent='loading source…'; body.innerHTML='<span class="mut">reading…</span>';
  let r; try{ r=await TG.source(ds.doc, ds.start, ds.end, ds.hash); }catch(e){ r=null; }
  if(!r || !r.available){
    ttl.textContent='source unavailable';
    const why={'no-corpus':'this console has no source corpus (a graph.json / .duckdb snapshot)',
      'source-changed':'the source file changed since the graph was built',
      'not-on-disk':'the source file is no longer on disk','unknown-document':'unknown document'};
    body.innerHTML=`<div class="mut">${esc((r&&why[r.reason])||'the cited bytes could not be read')}.`
      +`<br>Citation: [${esc(ds.doc.slice(0,14))}…:${ds.start}-${ds.end}]</div>`;
    return;
  }
  ttl.innerHTML=`${esc(r.name)} <span class="mut">bytes ${r.start}-${r.end}</span>`
    +(r.verified===true?' <span class="ok">verified</span>':r.verified===false?' <span class="bad">hash mismatch</span>':'');
  body.innerHTML=`<span class="ctx">${esc(r.before)}</span>`
    +`<mark>${esc(r.span)}</mark><span class="ctx">${esc(r.after)}</span>`;
  const m=body.querySelector('mark'); if(m) m.scrollIntoView({block:'center'});
}
function closeSource(){ document.getElementById('srcpanel').classList.remove('open'); }

function initAsk(){
  const dock=document.getElementById('ask');
  if(!dock) return;
  // `const TG` is a lexical global, not a window property — test the binding via typeof.
  if(typeof TG==='undefined' || typeof TG.chat!=='function'){ dock.style.display='none'; return; } // offline graph.html has no server
  document.getElementById('askhead').onclick=()=>{ dock.classList.toggle('collapsed');
    setTimeout(()=>{ resize(); fit(); }, 200); };  // canvas buffer must follow the height change
  document.getElementById('asksend').onclick=()=>ask();
  document.getElementById('askq').addEventListener('keydown',e=>{ if(e.key==='Enter') ask(); });
  // One delegated handler for the whole log: suggestion chips ask, citation chips open source.
  const log=document.getElementById('asklog');
  log.addEventListener('click',e=>{
    const sg=e.target.closest('.sugg'); if(sg){ ask(sg.dataset.q); return; }
    const cc=e.target.closest('.cite-chip.live'); if(cc){ openSource(cc.dataset); return; }
  });
  log.addEventListener('keydown',e=>{
    if(e.key!=='Enter'&&e.key!==' ') return;
    const cc=e.target.closest('.cite-chip.live'); if(cc){ e.preventDefault(); openSource(cc.dataset); }
  });
  document.getElementById('srcclose').onclick=closeSource;
  // Save snapshot is read-only, so it's always available on the live console.
  const save=document.getElementById('save'); save.style.display='inline-block'; save.onclick=saveSnapshot;
  // File-attach is available only when the server was started with --allow-ingest.
  if(typeof TG.ingest==='function'){
    fetch(typeof _u==='function'?_u('/api/config'):'/api/config').then(r=>r.json()).then(cfg=>{
      if(cfg && cfg.ingest){
        const at=document.getElementById('attach'), inp=document.getElementById('attachin');
        at.style.display='inline-block';
        inp.onchange=()=>{ attachFiles(inp.files); inp.value=''; };
      }
    }).catch(()=>{});
  }
}

function fmtKB(b){ return b>=1024?Math.round(b/1024)+' KB':b+' B'; }
async function buildDocs(){
  const box=document.getElementById('docs'), hdr=document.getElementById('docshdr');
  const u=(typeof _u==='function')?_u('/api/docs'):'/api/docs';
  let data; try{ data=await (await fetch(u)).json(); }catch(e){ return; }
  const docs=data.docs||[];
  if(!docs.length){ hdr.style.display='none'; box.innerHTML=''; return; }
  hdr.style.display=''; document.getElementById('doccount').textContent='· '+docs.length;
  box.innerHTML=docs.map(d=>`<div class="docrow"><span class="dn" title="${esc(d.name)}">${esc(d.name)}</span>`
    +`<span class="ds">${fmtKB(d.bytes)}</span>`
    +(data.can_edit?`<button class="drm" data-n="${esc(d.name)}" title="remove this document">&#128465;</button>`:'')
    +`</div>`).join('');
  box.querySelectorAll('.drm').forEach(b=>b.onclick=()=>removeDoc(b.dataset.n));
}
async function removeDoc(name){
  if(!confirm('Remove "'+name+'" from the corpus and rebuild the graph?')) return;
  const u=(typeof _u==='function')?_u('/api/remove'):'/api/remove';
  try{
    const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
    const j=await r.json(); if(!j.ok){ alert('Remove failed: '+(j.error||r.status)); return; }
    await reloadGraph(); await buildDocs();
  }catch(e){ alert('Remove failed: '+(e.message||e)); }
}
(async function init(){
  S.g=await TG.graph();
  S.byId={}; S.g.nodes.forEach(n=>S.byId[n.id]=n);
  computePredicates();
  relayout(); computeDerived();
  buildStats(); buildSidebar(); buildTops(); buildLegend(); initTime(); initAsk(); buildDocs(); resize(); fit();
  wirePredButtons();
  loadAnnotations();
})();
// Load the collaboration overlay and start polling so a teammate's edits appear within seconds.
async function loadAnnotations(){
  if(typeof TG==='undefined' || typeof TG.collab!=='function') return;
  await refreshCollab(true);
  setInterval(()=>refreshCollab(false), 4000);   // poll-sync (cheap: only redraws on a version bump)
}
async function refreshCollab(force){
  try{
    const r=await TG.collab(); if(!r) return;
    if(!force && r.version===S.collabV) return;   // nothing changed since last poll
    S.collabV=r.version; S.ann=r.annotations||{}; S.assign=r.assignments||{};
    S.activity=r.activity||[]; if(r.analyst!=null) S.analyst=r.analyst;
    renderIdentity(); renderActivity();
    if(S.sel && document.getElementById('annstatus')) inspect(S.sel);  // refresh open editor
    draw();
  }catch(e){}
}
function renderIdentity(){
  const el=document.getElementById('whoami'); if(!el) return;
  el.textContent = S.analyst ? ('you: '+S.analyst) : '';
  el.style.display = S.analyst ? 'inline-flex' : 'none';
  const mb=document.getElementById('minebtn');
  if(mb){ mb.style.display = S.analyst ? '' : 'none';
    if(!mb._wired){ mb._wired=true; mb.onclick=()=>{ S.mineOnly=!S.mineOnly;
      mb.classList.toggle('on',S.mineOnly); draw(); }; } }
}
function renderActivity(){
  const box=document.getElementById('activity'); if(!box) return;
  const byId=S.byId||{};
  const name=nid=>(byId[nid]&&byId[nid].name)||nid;
  const rows=(S.activity||[]).slice().reverse().slice(0,30);
  document.getElementById('acthdr').style.display = rows.length?'':'none';
  box.innerHTML = rows.map(a=>`<div class="arow"><b>${esc(a.author||'?')}</b> ${esc(a.action||'')} `
    +`<span class="mut">${esc(name(a.node))}</span></div>`).join('')
    || '<div class="mut" style="padding:4px 18px">No activity yet.</div>';
}
"""
