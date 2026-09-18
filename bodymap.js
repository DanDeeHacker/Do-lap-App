/* ============================================================
   bodymap.js — anatomická silueta pro označení bolesti
   Svalové skupiny jako polygony (spolehlivé zrcadlení), tvar
   se vyhlazuje Catmull-Rom křivkou, snopce se generují podle
   směru vláken každého svalu.
   Strana se určuje anatomicky: zepředu je levá polovina obrazu
   pravá strana těla, zezadu naopak.
   ========================================================= */
(function(){
'use strict';
const CTR=80, W=160, H=400;

const FRONT=[
 {id:'head', c:1,m:0,a:90,p:[[80,6],[92,10],[97,22],[95,36],[87,46],[80,48],[73,46],[65,36],[63,22],[68,10]]},
 {id:'neck', c:1,m:0,a:90,p:[[70,45],[90,45],[93,61],[67,61]]},
 {id:'trap', c:1,m:0,a:20,p:[[58,60],[80,55],[102,60],[110,73],[80,67],[50,73]]},
 {id:'delt', a:70,l:'Deltový sval',p:[[57,63],[46,67],[38,79],[37,92],[45,99],[55,94],[58,79]]},
 {id:'pec',  a:12,l:'Prsní sval',p:[[59,68],[78,66],[79,98],[70,103],[58,97],[55,80]]},
 {id:'bic',  a:80,l:'Biceps',p:[[41,97],[53,94],[56,116],[53,130],[42,128],[37,111]]},
 {id:'fore', c:1,a:80,p:[[41,133],[53,135],[52,160],[48,176],[38,172],[36,149]]},
 {id:'hand', c:1,a:80,p:[[39,178],[50,180],[49,198],[39,197]]},
 {id:'abs',  m:0,a:90,l:'Přímý břišní',p:[[67,100],[93,100],[94,140],[91,166],[80,170],[69,166],[66,140]]},
 {id:'obl',  a:55,l:'Šikmé břišní',p:[[56,104],[66,102],[67,158],[61,166],[53,150],[52,120]]},
 {id:'hip',  a:60,l:'Kyčelní flexory',p:[[58,168],[79,170],[79,192],[65,193],[56,183]]},
 {id:'addu', a:78,l:'Adduktory',p:[[67,194],[79,196],[79,240],[71,246],[65,220]]},
 {id:'rf',   a:86,l:'Rectus femoris',p:[[57,192],[71,194],[74,232],[72,262],[61,264],[55,226]]},
 {id:'vl',   a:76,l:'Vastus lateralis',p:[[46,198],[57,194],[56,232],[54,256],[45,252],[42,222]]},
 {id:'vm',   a:66,l:'Vastus medialis',p:[[61,246],[77,244],[79,262],[75,274],[63,272]]},
 {id:'itb',  a:88,l:'IT band',p:[[40,202],[46,201],[46,264],[41,266]]},
 {id:'knee', a:0,l:'Přední koleno',p:[[56,274],[78,274],[78,292],[58,292]]},
 {id:'ta',   a:84,l:'Tibialis anterior',p:[[58,296],[71,298],[70,330],[67,352],[58,350],[56,320]]},
 {id:'shin', a:88,l:'Holenní kost',p:[[71,298],[79,298],[78,330],[76,352],[68,352]]},
 {id:'ank',  a:0,l:'Kotník',p:[[58,354],[78,354],[78,368],[58,368]]},
 {id:'foot', a:14,l:'Nárt',p:[[56,370],[79,370],[83,384],[79,392],[57,390]]}
];
const BACK=[
 {id:'headB',c:1,m:0,a:90,p:[[80,6],[92,10],[97,22],[95,36],[87,46],[80,48],[73,46],[65,36],[63,22],[68,10]]},
 {id:'neckB',c:1,m:0,a:90,p:[[70,45],[90,45],[93,61],[67,61]]},
 {id:'trapB',m:0,a:28,l:'Trapéz',p:[[57,58],[80,54],[103,58],[111,74],[96,98],[80,107],[64,98],[49,74]]},
 {id:'deltB',c:1,a:70,p:[[57,63],[46,67],[38,79],[37,92],[45,99],[55,94],[58,79]]},
 {id:'lat',  a:38,l:'Široký sval zádový',p:[[55,100],[74,104],[76,132],[70,150],[57,146],[49,124]]},
 {id:'tri',  a:80,l:'Triceps',p:[[41,97],[53,94],[56,116],[53,130],[42,128],[37,111]]},
 {id:'foreB',c:1,a:80,p:[[41,133],[53,135],[52,160],[48,176],[38,172],[36,149]]},
 {id:'handB',c:1,a:80,p:[[39,178],[50,180],[49,198],[39,197]]},
 {id:'erec', a:90,l:'Vzpřimovače páteře',p:[[68,104],[78,104],[78,150],[76,166],[68,166],[66,132]]},
 {id:'ql',   a:58,l:'Bederní oblast',p:[[55,142],[67,144],[67,168],[57,166],[52,155]]},
 {id:'si',   m:0,a:40,l:'SI kloub',p:[[66,169],[94,169],[92,184],[68,184]]},
 {id:'gmed', a:28,l:'Gluteus medius',p:[[49,168],[67,172],[66,190],[49,188],[45,177]]},
 {id:'gmax', a:34,l:'Gluteus maximus',p:[[47,191],[79,193],[79,222],[63,229],[49,222],[43,207]]},
 {id:'bf',   a:82,l:'Biceps femoris',p:[[47,230],[61,228],[62,252],[60,278],[49,276],[44,252]]},
 {id:'st',   a:86,l:'Semitendinosus',p:[[63,228],[79,230],[79,254],[77,278],[64,278]]},
 {id:'popl', a:0,l:'Podkolení jamka',p:[[55,281],[79,281],[79,294],[56,294]]},
 {id:'gasl', a:78,l:'Gastrocnemius lat.',p:[[53,297],[66,295],[67,314],[64,334],[55,332],[50,314]]},
 {id:'gasm', a:84,l:'Gastrocnemius med.',p:[[67,295],[79,295],[79,316],[77,336],[67,334]]},
 {id:'sol',  a:86,l:'Soleus',p:[[56,337],[78,337],[78,352],[58,352]]},
 {id:'ach',  a:90,l:'Achillova šlacha',p:[[64,354],[78,354],[78,370],[64,370]]},
 {id:'heel', a:22,l:'Pata',p:[[59,371],[79,371],[81,386],[61,388]]}
];

const r=v=>Math.round(v*10)/10;
const flip=p=>p.map(([x,y])=>[W-x,y]);
function smooth(pts){
  const n=pts.length, P=(i)=>pts[(i%n+n)%n];
  let d=`M${r(pts[0][0])} ${r(pts[0][1])}`;
  for(let i=0;i<n;i++){
    const p0=P(i-1),p1=P(i),p2=P(i+1),p3=P(i+2);
    const c1=[p1[0]+(p2[0]-p0[0])/6,p1[1]+(p2[1]-p0[1])/6];
    const c2=[p2[0]-(p3[0]-p1[0])/6,p2[1]-(p3[1]-p1[1])/6];
    d+=`C${r(c1[0])} ${r(c1[1])} ${r(c2[0])} ${r(c2[1])} ${r(p2[0])} ${r(p2[1])}`;
  }
  return d+'Z';
}
/* Static defs shared by every render: gradients give each muscle a rounded,
   lit-from-above look instead of flat fill; the underlay filter dilates and
   blurs the *rendered* union of all muscle shapes and floods it skin-toned
   behind them — it derives the connecting silhouette from actual pixels,
   not from hand-guessed outline coordinates, so it can't drift out of sync
   with the muscle polygons (which keep their exact coordinates — pain
   points already saved against them, in seed data and real accounts,
   depend on that staying true). */
const STATIC_DEFS=`
  <radialGradient id="bm-mgrad" cx="32%" cy="22%" r="90%">
    <stop offset="0%" stop-color="#EEF3F9"/>
    <stop offset="55%" stop-color="#D9E4EF"/>
    <stop offset="100%" stop-color="#BFD0E1"/>
  </radialGradient>
  <radialGradient id="bm-mgrad-ctx" cx="32%" cy="22%" r="90%">
    <stop offset="0%" stop-color="#F4F8FB"/>
    <stop offset="100%" stop-color="#E1E9F1"/>
  </radialGradient>
  <radialGradient id="bm-shadow" cx="50%" cy="50%" r="50%">
    <stop offset="0%" stop-color="rgba(10,37,64,.22)"/>
    <stop offset="100%" stop-color="rgba(10,37,64,0)"/>
  </radialGradient>
  <filter id="bm-underlay" x="-30%" y="-15%" width="160%" height="130%">
    <feMorphology in="SourceAlpha" operator="dilate" radius="2.6" result="dilated"/>
    <feGaussianBlur in="dilated" stdDeviation="2.2" result="softened"/>
    <feFlood flood-color="#E4C6AC" flood-opacity=".95" result="skin"/>
    <feComposite in="skin" in2="softened" operator="in" result="skinBridge"/>
    <feMerge>
      <feMergeNode in="skinBridge"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>`;
const sideOf=(view,imgLeft)=>view==='front'?(imgLeft?'P':'L'):(imgLeft?'L':'P');
function fibers(clipId,angle,dense=9){
  let ls='';
  for(let i=0;i<dense;i++)ls+=`<line x1="-110" y1="${r(-100+i*(200/(dense-1)))}" x2="110" y2="${r(-100+i*(200/(dense-1)))}"/>`;
  return `<g clip-path="url(#${clipId})"><g transform="translate(${CTR} 200) rotate(${r(90-angle)})">${ls}</g></g>`;
}
function buildSvg(view){
  const src=view==='front'?FRONT:BACK;
  let defs='',shapes='',fib='',hit='';
  const add=(g,key,pts,imgLeft)=>{
    const d=smooth(pts), id=`${view}_${g.id}_${key}`;
    defs+=`<clipPath id="cl_${id}"><path d="${d}"/></clipPath>`;
    shapes+=`<path class="mus${g.c?' ctx':''}" d="${d}"/>`;
    fib+=`<g class="fib${g.c?' ctx':''}">${fibers('cl_'+id,g.a)}</g>`;
    if(!g.c&&g.l){
      const side=g.m===0?'S':sideOf(view,imgLeft);
      const lbl=g.l+(side==='P'?' vpravo':side==='L'?' vlevo':'');
      hit+=`<path class="hit" d="${d}" data-region="${g.l}" data-side="${side}" tabindex="0"
        role="button" aria-label="${lbl}"><title>${lbl}</title></path>`;
    }
  };
  src.forEach(g=>{
    if(g.m===0){add(g,'m',g.p,true);return}
    add(g,'l',g.p,true); add(g,'r',flip(g.p),false);
  });
  return{defs,shapes,fib,hit};
}

const PAIN_TYPES=['ostrá','tupá','píchavá','pálivá','ztuhlost','brnění'];
const WHEN=['na začátku','v průběhu','ke konci','až po běhu','ráno po'];
const sevColor=s=>s>=7?'#BB3A2B':s>=4?'#B0770F':'#2E7CF6';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const CSS=`
.bm-wrap{display:grid;grid-template-columns:1fr;gap:14px}
.bm-stage{position:relative;background:radial-gradient(120% 80% at 50% 8%,#FAFCFE,#E6EEF7);
  border-radius:20px;padding:6px;border:1px solid var(--glass-14);overflow:hidden;user-select:none}
.bm-stage svg{display:block;width:100%;height:auto;max-height:72vh;margin:0 auto;touch-action:manipulation}
.bm .mus{fill:url(#bm-mgrad);stroke:rgba(10,37,64,.32);stroke-width:.7;stroke-linejoin:round}
.bm .mus.ctx{fill:url(#bm-mgrad-ctx);stroke:rgba(10,37,64,.16)}
.bm .fib line{stroke:rgba(10,37,64,.22);stroke-width:.4}
.bm .fib.ctx line{stroke:rgba(10,37,64,.08)}
.bm .ground{fill:url(#bm-shadow)}
.bm .hit{fill:transparent;stroke:transparent;cursor:crosshair;transition:fill .16s,stroke .16s}
.bm .hit:hover,.bm .hit:focus-visible{fill:rgba(46,124,246,.3);stroke:#2E7CF6;stroke-width:1.3;outline:none}
.bm-pt{cursor:grab}.bm-pt:active{cursor:grabbing}
.bm-pt circle.halo{opacity:.3}
.bm-pt circle.core{stroke:#fff;stroke-width:2}
.bm-pt.sel circle.core{stroke-width:3}
.bm-toggle{position:absolute;top:10px;left:50%;transform:translateX(-50%);display:flex;
  background:rgba(255,255,255,.9);backdrop-filter:blur(10px);border-radius:99px;padding:3px;
  border:1px solid var(--glass-14);box-shadow:var(--sh-1);z-index:3}
.bm-toggle button{padding:6px 15px;border-radius:99px;font-size:12.5px;font-weight:700;color:var(--muted)}
.bm-toggle button[aria-pressed="true"]{background:var(--navy-800);color:#fff}
.bm-hint{position:absolute;bottom:9px;left:50%;transform:translateX(-50%);font-size:11.5px;
  color:var(--muted);background:rgba(255,255,255,.9);padding:5px 13px;border-radius:99px;
  border:1px solid var(--glass-14);white-space:nowrap;z-index:3;pointer-events:none}
.bm-live{position:absolute;top:10px;right:10px;background:var(--navy-800);color:#fff;font-size:11px;
  font-weight:700;padding:5px 11px;border-radius:99px;z-index:3;opacity:0;transition:opacity .18s}
.bm-live.on{opacity:1}
.bm-list{display:flex;flex-direction:column;gap:8px}
.bm-item{border:1px solid var(--glass-14);border-radius:14px;padding:12px;background:#fff;
  display:flex;gap:11px;align-items:flex-start;transition:border-color .2s,box-shadow .2s}
.bm-item.sel{border-color:var(--navy-600);box-shadow:0 0 0 3px var(--blue-soft)}
.bm-item .dot{width:26px;height:26px;border-radius:50%;flex:0 0 auto;display:grid;place-items:center;
  color:#fff;font-size:11px;font-weight:800;font-family:var(--mono)}
.bm-item .bd{flex:1;min-width:0}
.bm-item .bd b{font-size:13.5px;display:block}
.bm-item .bd em{font-style:normal;font-size:11.5px;color:var(--muted);display:block;margin-top:1px}
.bm-item .nt{font-size:12.5px;margin-top:6px;background:var(--glass-08);padding:7px 10px;border-radius:9px}
.bm-empty{padding:20px;text-align:center;color:var(--muted);font-size:13px;
  border:1px dashed var(--glass-24);border-radius:14px}
@media(min-width:820px){.bm-wrap{grid-template-columns:minmax(0,320px) 1fr}}
`;
function ensureCss(){
  if(document.getElementById('bm-css'))return;
  const s=document.createElement('style');s.id='bm-css';s.textContent=CSS;document.head.appendChild(s);
}
function ptsSvg(points,view,sel){
  return points.filter(p=>p.view===view).map(p=>`
    <g class="bm-pt ${sel===p.id?'sel':''}" data-pt="${p.id}" transform="translate(${p.x} ${p.y})">
      <circle class="halo" r="${r(9+p.severity*1.1)}" fill="${sevColor(p.severity)}"/>
      <circle class="core" r="8" fill="${sevColor(p.severity)}"/>
      <text y="3.4" text-anchor="middle" font-size="9" font-weight="800" fill="#fff">${p.severity}</text>
      <title>${esc(p.region)}${p.side==='P'?' vpravo':p.side==='L'?' vlevo':''} · ${p.severity}/10${p.note?' · '+esc(p.note):''}</title>
    </g>`).join('');
}

function BodyMap(host,opts={}){
  ensureCss();host.classList.add('bm');
  const st={view:'front',points:(opts.points||[]).map(p=>({...p})),sel:null,onChange:opts.onChange||(()=>{})};
  function listHtml(){
    if(!st.points.length)return `<div class="bm-empty">Zatím neoznačeno nic. Silueta rozliší levou a pravou stranu i konkrétní sval — ušetří to čas při vyšetření.</div>`;
    return `<div class="bm-list">${st.points.map(p=>`
      <div class="bm-item ${st.sel===p.id?'sel':''}" data-item="${p.id}">
        <div class="dot" style="background:${sevColor(p.severity)}">${p.severity}</div>
        <div class="bd"><b>${esc(p.region)}${p.side==='P'?' vpravo':p.side==='L'?' vlevo':''}</b>
          <em>${p.view==='front'?'zepředu':'zezadu'}${p.type?' · '+esc(p.type):''}${p.when?' · '+esc(p.when):''}</em>
          ${p.note?`<div class="nt">${esc(p.note)}</div>`:''}</div>
        <button class="btn ghost xs" data-bm="edit" data-id="${p.id}">Upravit</button>
        <button class="btn danger xs" data-bm="del" data-id="${p.id}">×</button></div>`).join('')}</div>`;
  }
  function paint(){
    const {defs,shapes,fib,hit}=buildSvg(st.view);
    host.innerHTML=`<div class="bm-wrap">
      <div class="bm-stage">
        <div class="bm-toggle">
          <button data-bm="view" data-v="front" aria-pressed="${st.view==='front'}">Zepředu</button>
          <button data-bm="view" data-v="back" aria-pressed="${st.view==='back'}">Zezadu</button></div>
        <div class="bm-live"></div>
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Silueta těla, ${st.view==='front'?'zepředu':'zezadu'}">
          <defs>${STATIC_DEFS}${defs}</defs>
          <ellipse class="ground" cx="${CTR}" cy="393" rx="46" ry="9"/>
          <g filter="url(#bm-underlay)">${shapes}</g><g>${fib}</g><g>${hit}</g>
          <g class="pts">${ptsSvg(st.points,st.view,st.sel)}</g></svg>
        <div class="bm-hint">${st.points.length?'Bod jde přetáhnout, klepnutím se upraví':'Klepněte na místo, kde to bolí'}</div>
      </div><div>${listHtml()}</div></div>`;
    bind();
  }
  function closeSheet(){document.getElementById('sheet')?.classList.remove('on');
    document.getElementById('scrim')?.classList.remove('on')}
  function editor(p){
    const sheet=document.getElementById('sheet'),body=document.getElementById('sheetbody');
    if(!sheet)return;
    body.innerHTML=`<h2>${esc(p.region)}${p.side==='P'?' vpravo':p.side==='L'?' vlevo':''}</h2>
      <p class="sub">${p.view==='front'?'Pohled zepředu':'Pohled zezadu'}. Charakter a načasování bolesti nasměrují vyšetření víc než samotná intenzita.</p>
      <form id="bmform">
        <label class="field"><span>Intenzita <span class="lh">1 = jen cítím · 10 = musím zastavit</span></span>
          <div class="rrow"><input type="range" name="severity" min="1" max="10" value="${p.severity}">
          <span class="rval">${p.severity}</span></div></label>
        <label class="field"><span>Charakter</span>
          <div class="pickrow">${PAIN_TYPES.map(l=>`<button type="button" class="pick" data-grp="type" data-v="${l}" aria-pressed="${p.type===l}">${l}</button>`).join('')}</div>
          <input type="hidden" name="type" value="${esc(p.type||'')}"></label>
        <label class="field"><span>Kdy se to ozve</span>
          <div class="pickrow">${WHEN.map(l=>`<button type="button" class="pick" data-grp="when" data-v="${l}" aria-pressed="${p.when===l}">${l}</button>`).join('')}</div>
          <input type="hidden" name="when" value="${esc(p.when||'')}"></label>
        <label class="field"><span>Poznámka k tomuto bodu</span>
          <textarea name="note" placeholder="Co to zhoršuje, co pomáhá, jestli to bylo i dřív…">${esc(p.note||'')}</textarea></label>
        <div class="btnrow"><button class="btn" type="submit">Uložit bod</button>
          <button class="btn danger" type="button" id="bmdel">Odstranit bod</button></div></form>`;
    sheet.classList.add('on');document.getElementById('scrim').classList.add('on');
    body.querySelectorAll('[data-grp]').forEach(b=>b.addEventListener('click',()=>{
      const g=b.dataset.grp, inp=body.querySelector(`input[name="${g}"]`);
      const was=inp.value===b.dataset.v;
      body.querySelectorAll(`[data-grp="${g}"]`).forEach(x=>x.setAttribute('aria-pressed','false'));
      b.setAttribute('aria-pressed',was?'false':'true'); inp.value=was?'':b.dataset.v;}));
    body.querySelector('input[name=severity]').addEventListener('input',e=>{
      e.target.closest('.rrow').querySelector('.rval').textContent=e.target.value});
    body.querySelector('#bmform').addEventListener('submit',e=>{
      e.preventDefault();const d=Object.fromEntries(new FormData(e.target));
      Object.assign(p,{severity:+d.severity,type:d.type||null,when:d.when||null,note:d.note||null});
      closeSheet();st.sel=p.id;paint();st.onChange(st.points)});
    body.querySelector('#bmdel').addEventListener('click',()=>{
      st.points=st.points.filter(x=>x.id!==p.id);closeSheet();paint();st.onChange(st.points)});
  }
  function bind(){
    const svgEl=host.querySelector('svg'), live=host.querySelector('.bm-live');
    const toLocal=e=>{const s=e.touches?e.touches[0]:e;const pt=svgEl.createSVGPoint();
      pt.x=s.clientX;pt.y=s.clientY;return pt.matrixTransform(svgEl.getScreenCTM().inverse())};
    host.querySelectorAll('[data-bm="view"]').forEach(b=>b.addEventListener('click',()=>{st.view=b.dataset.v;paint()}));
    host.querySelectorAll('[data-bm="edit"]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();
      const p=st.points.find(x=>x.id===b.dataset.id);st.sel=p.id;st.view=p.view;paint();editor(p)}));
    host.querySelectorAll('[data-bm="del"]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();
      st.points=st.points.filter(x=>x.id!==b.dataset.id);paint();st.onChange(st.points)}));
    host.querySelectorAll('[data-item]').forEach(el=>el.addEventListener('click',e=>{
      if(e.target.closest('button'))return;
      const p=st.points.find(x=>x.id===el.dataset.item);st.sel=p.id;st.view=p.view;paint()}));
    host.querySelectorAll('.hit').forEach(h=>{
      const lbl=()=>h.dataset.region+(h.dataset.side==='P'?' vpravo':h.dataset.side==='L'?' vlevo':'');
      h.addEventListener('mouseenter',()=>{live.textContent=lbl();live.classList.add('on')});
      h.addEventListener('mouseleave',()=>live.classList.remove('on'));
      const place=(x,y)=>{
        const p={id:'p'+Date.now().toString(36)+Math.random().toString(36).slice(2,5),view:st.view,
          x:r(x),y:r(y),region:h.dataset.region,side:h.dataset.side,severity:5,type:null,when:null,note:null};
        st.points.push(p);st.sel=p.id;paint();st.onChange(st.points);editor(p);};
      h.addEventListener('click',e=>{const l=toLocal(e);place(l.x,l.y)});
      h.addEventListener('keydown',e=>{if(e.key!=='Enter'&&e.key!==' ')return;e.preventDefault();
        const bb=h.getBBox();place(bb.x+bb.width/2,bb.y+bb.height/2)});
    });
    host.querySelectorAll('.bm-pt').forEach(g=>{
      let drag=false,moved=false;
      const start=e=>{drag=true;moved=false;st.sel=g.dataset.pt;e.stopPropagation()};
      const move=e=>{if(!drag)return;moved=true;if(e.cancelable)e.preventDefault();
        const loc=toLocal(e);g.setAttribute('transform',`translate(${r(loc.x)} ${r(loc.y)})`);
        const p=st.points.find(x=>x.id===g.dataset.pt);if(!p)return;
        p.x=r(loc.x);p.y=r(loc.y);
        const s=e.touches?e.touches[0]:e;
        const under=document.elementFromPoint(s.clientX,s.clientY);
        if(under&&under.classList.contains('hit')){p.region=under.dataset.region;p.side=under.dataset.side;
          live.textContent=p.region+(p.side==='P'?' vpravo':p.side==='L'?' vlevo':'');live.classList.add('on')}};
      const stop=()=>{if(!drag)return;drag=false;live.classList.remove('on');if(moved){paint();st.onChange(st.points)}};
      g.addEventListener('mousedown',start);g.addEventListener('touchstart',start,{passive:true});
      window.addEventListener('mousemove',move);window.addEventListener('touchmove',move,{passive:false});
      window.addEventListener('mouseup',stop);window.addEventListener('touchend',stop);
      g.addEventListener('click',e=>{e.stopPropagation();if(moved)return;
        const p=st.points.find(x=>x.id===g.dataset.pt);if(p)editor(p)});
    });
  }
  paint();
  return{get points(){return st.points},set points(v){st.points=v;paint()},repaint:paint};
}

function BodyMapView(host,points,opts={}){
  ensureCss();host.classList.add('bm');
  const has=v=>points.some(p=>p.view===v);
  let view=opts.view||(has('front')?'front':has('back')?'back':'front');
  function paint(){
    const {defs,shapes,fib}=buildSvg(view);
    const nf=points.filter(p=>p.view==='front').length,nb=points.filter(p=>p.view==='back').length;
    host.innerHTML=`<div class="bm-stage">
      <div class="bm-toggle">
        <button data-v="front" aria-pressed="${view==='front'}">Zepředu${nf?' · '+nf:''}</button>
        <button data-v="back" aria-pressed="${view==='back'}">Zezadu${nb?' · '+nb:''}</button></div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Označená bolestivá místa">
        <defs>${STATIC_DEFS}${defs}</defs>
        <ellipse class="ground" cx="${CTR}" cy="393" rx="46" ry="9"/>
        <g filter="url(#bm-underlay)">${shapes}</g><g>${fib}</g><g>${ptsSvg(points,view,null)}</g></svg></div>`;
    host.querySelectorAll('[data-v]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.v;paint()}));
  }
  paint();return{repaint:paint};
}

window.D=window.D||{};
Object.assign(window.D,{BodyMap,BodyMapView,PAIN_TYPES,WHEN,_bmBuild:buildSvg,
  bodyRegions:()=>[...new Set([...FRONT,...BACK].filter(g=>g.l&&!g.c).map(g=>g.l))]});
})();
