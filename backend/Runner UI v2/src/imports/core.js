/* ============================================================
   Došlap — sdílené jádro (v2, na reálném backendu)
   Načítá se jako klasický skript ve všech HTML souborech.
   Data už nejsou v paměti prohlížeče — každá stránka si je při
   načtení natáhne z FastAPI backendu (/api/...) a uloží do
   window.DB, ve stejném tvaru, jaký měl dřívější demo generátor.
   Přihlášení je skutečné, na cookie relaci (viz AUTH níže).
   ========================================================= */
(function(){
'use strict';

/* ---------- 0 · utils ---------- */
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const uid=(p,n)=>p+'-'+String(n).padStart(4,'0');
const r1=n=>n==null?null:Math.round(n*10)/10, r2=n=>n==null?null:Math.round(n*100)/100;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:0;
const sd=a=>{if(a.length<2)return 0;const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))};
const DAY=864e5;
const today=()=>{const d=new Date();d.setHours(0,0,0,0);return d};
const iso=d=>d.toISOString().slice(0,10);
const dayAgo=n=>iso(new Date(today()-n*DAY));
const daysBetween=(a,b)=>Math.round((new Date(b)-new Date(a))/DAY);
const fmtD=s=>s?new Date(s).toLocaleDateString('cs-CZ',{day:'numeric',month:'short'}):'—';
const fmtDT=s=>s?new Date(s).toLocaleString('cs-CZ',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
const czk=n=>new Intl.NumberFormat('cs-CZ').format(Math.round(n))+' Kč';
const sgn=n=>n==null?'—':(n>0?'+':'')+n;
const initials=n=>String(n||'').split(' ').filter(w=>!w.includes('.')).map(w=>w[0]).slice(0,2).join('').toUpperCase();
const paceStr=s=>s==null?'—':Math.floor(s/60)+':'+String(Math.round(s%60)).padStart(2,'0');

/* ---------- hash router ---------- */
const H={
  all(){const o={};(location.hash.slice(1)||'').split('&').filter(Boolean)
    .forEach(p=>{const [k,v]=p.split('=');o[decodeURIComponent(k)]=decodeURIComponent(v||'')});return o},
  get(k,d){return this.all()[k]??d},
  set(patch,replace){const o={...this.all(),...patch};
    Object.keys(o).forEach(k=>{if(o[k]===''||o[k]==null)delete o[k]});
    const h='#'+Object.entries(o).map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
    if(replace)location.replace(h);else location.hash=h;},
  link(page,patch){const q=Object.entries(patch).map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
    return page+'#'+q}
};

/* ---------- 1 · Garmin export mapping (náhled v prohlížeči před uploadem) ---------- */
const GARMIN_MAP={
  'Activity Type':'activity_type','Date':'started_at','Title':'title','Distance':'distance_km',
  'Time':'duration_str','Avg HR':'avg_hr','Max HR':'max_hr','Avg Run Cadence':'cadence_spm',
  'Avg Pace':'pace_str','Total Ascent':'ascent_m','Total Descent':'descent_m',
  'Avg Stride Length':'stride_len_m','Avg Vertical Ratio':'vert_ratio_pct',
  'Avg Vertical Oscillation':'vert_osc_cm','Avg Ground Contact Time':'gct_ms',
  'Avg GCT Balance':'gct_balance_str','Min Temp':'temp_c','Calories':'calories','Number of Laps':'laps'
};
function parseGarminCsv(text){
  const rows=[];let i=0,f='',row=[],q=false;
  while(i<text.length){const c=text[i];
    if(q){if(c==='"'){if(text[i+1]==='"'){f+='"';i++}else q=false}else f+=c}
    else if(c==='"')q=true;
    else if(c===','){row.push(f);f=''}
    else if(c==='\n'||c==='\r'){if(f!==''||row.length){row.push(f);rows.push(row);row=[];f=''}
      if(c==='\r'&&text[i+1]==='\n')i++}
    else f+=c;
    i++}
  if(f!==''||row.length){row.push(f);rows.push(row)}
  if(!rows.length)return{ok:false,error:'Soubor je prázdný.'};
  const hdr=rows[0].map(h=>h.trim());
  const known=hdr.filter(h=>GARMIN_MAP[h]);
  if(known.length<4)return{ok:false,error:'Nevypadá to jako export z Garmin Connect. Chybí sloupce jako Distance nebo Avg Vertical Ratio.'};
  const num=v=>{const n=parseFloat(String(v).replace(/[^\d.,-]/g,'').replace(',','.'));return isNaN(n)?null:n};
  const acts=rows.slice(1).filter(r=>r.length>=hdr.length-2).map((r,idx)=>{
    const o={};hdr.forEach((h,j)=>{if(GARMIN_MAP[h])o[GARMIN_MAP[h]]=r[j]});
    const bal=String(o.gct_balance_str||'').split(/[/%]/)[0];
    const dur=String(o.duration_str||'').split(':').map(Number);
    return{id:'imp'+idx,provider:'garmin_csv',title:o.title||'',
      started_at:(o.started_at||'').slice(0,10),distance_km:num(o.distance_km),
      duration_min:dur.length===3?dur[0]*60+dur[1]+dur[2]/60:dur.length===2?dur[0]+dur[1]/60:null,
      avg_hr:num(o.avg_hr),cadence_spm:num(o.cadence_spm),stride_len_m:num(o.stride_len_m),
      vert_ratio_pct:num(o.vert_ratio_pct),vert_osc_cm:num(o.vert_osc_cm),gct_ms:num(o.gct_ms),
      gct_balance_l:num(bal),ascent_m:num(o.ascent_m),descent_m:num(o.descent_m),temp_c:num(o.temp_c),
      surface:/trail|terén/i.test(o.activity_type||'')?'trail':
              /treadmill|pás/i.test(o.activity_type||'')?'treadmill':'road'};
  }).filter(a=>a.distance_km&&a.started_at);
  const cov=k=>Math.round(acts.filter(a=>a[k]!=null).length/Math.max(1,acts.length)*100);
  return{ok:true,activities:acts,mapped:known,unmapped:hdr.filter(h=>!GARMIN_MAP[h]&&h),
    coverage:{vert_ratio_pct:cov('vert_ratio_pct'),gct_ms:cov('gct_ms'),
      gct_balance_l:cov('gct_balance_l'),cadence_spm:cov('cadence_spm')}};
}

/* ---------- 2 · slovník signálů — engine v0.4 (formule/why/limit/clear) ----------
   Čistě referenční text pro UI. Výpočet žije na backendu
   (backend/app/metrics/engine.py) — tohle je jeho zdokumentovaný slovník,
   ne druhá kopie logiky. */
const GRADE_NOTE={A:'Konzistentní prospektivní evidence u běžců.',
  B:'Smíšená nebo vznikající evidence — signál, ne důkaz.',
  C:'Mechanistická úvaha. Generuje hypotézu, nic víc.'};
const SIG_DOC={
 tavr:{t:'Terénně očištěný drift vertikálního poměru',g:'B',
  fx:`VR      = vertikální oscilace / délka kroku
TAVR_z  = (průměr VR za 28 dní − baseline) / SD
          baseline = dny 84 → 29
          skupiny: povrch × sklon × pásmo tempa`,
  why:'Vertikální oscilace sama o sobě je špatná jednotka — kdo prodlouží krok, zvedne VO bez ztráty ekonomiky. Normalizovaný vertikální poměr to řeší. Menší vertikální oscilace trupu souvisí s lepší běžeckou ekonomikou a s nižší vertikální mírou zatížení, a ta je uznávaným rizikovým faktorem zranění dolní končetiny. Rostoucí VR ve srovnatelných podmínkách proto naznačuje ztrátu elastického odrazu dřív, než to začne bolet.',
  limit:'Řetězec VO → zatížení → zranění je odvozený, ne prokázaný prospektivně. Hodnoty se navíc liší mezi zařízeními, takže při výměně hodinek je nutné baseline resetovat.',
  clear:'Signál zmizí, když se VR ve stejných podmínkách vrátí do pásma ±1 SD po dobu tří tréninků.'},
 gct:{t:'Prodloužený kontakt se zemí',g:'B',
  fx:`GCT_adj = GCT × (kadence / baseline_kadence)
z       = (GCT_adj − baseline) / SD   [14 dní]`,
  why:'Doba kontaktu se zemí roste s únavou — měřitelně stoupá od 10. kilometru dlouhého běhu spolu s vyšším extenčním momentem kyčle a addukčním úhlem. Trvale zvýšená hodnota při shodném tempu a kadenci naznačuje, že se únava mezi tréninky nestíhá odbourávat.',
  limit:'Citlivé na obuv. Přechod do vyšší tlumené boty GCT prodlouží bez jakékoli patologie — je potřeba se zeptat, ne jen měřit.',
  clear:'Dva až tři regenerační týdny obvykle vrátí GCT k baseline. Pokud ne, jde spíš o změnu techniky nebo obuvi.'},
 bal:{t:'Posun v symetrii kontaktu',g:'B',
  fx:`excursion = |GCT_balance_teď − GCT_balance_baseline|
NEporovnává se s populační normou`,
  why:'Sekundární analýza randomizované studie s více než 800 rekreačními běžci ukázala, že asymetrie chůze v prostorových a kinetických proměnných riziko zranění dolních končetin nezvyšuje. Často citovaný údaj o 75% výskytu zranění nad 10 % asymetrie pochází z vojenského základního výcviku a na rekreační běžce se nepřenáší. Platforma proto neoznačuje absolutní asymetrii — jen její změnu proti vlastní normě. Jemné posuny asymetrie, včetně obrácení poměru reakčních sil mezi končetinami, byly pozorovány před stresovým zraněním kosti u vysokoškolských běžců.',
  limit:'Běžec, který je celý život na 47,5/52,5, není nález. Zajímavý je ten, kdo se tam právě posunul.',
  clear:'Návrat do ±0,5 p.b. od vlastní normy po dobu 14 dnů.'},
 dec:{t:'Klesající odolnost proti únavě',g:'C',
  fx:`decoupling = (VR_poslední_třetina / VR_první_třetina − 1) × 100
trend      = sklon přes 6+ srovnatelných dlouhých běhů`,
  why:'Běžec, jehož technika drží 90 minut, je odolnější než ten, kterému se vertikální poměr v poslední třetině zhorší o 8 %. Rostoucí trend napříč srovnatelnými běhy znamená klesající odolnost proti únavě.',
  limit:'Stupeň C. Mechanisticky to dává smysl, prospektivní validace neexistuje. Zároveň je to metrika, která se hýbe nejdřív.',
  clear:'Trend se srovná, jakmile se doplní síla lýtka a hýždí nebo se sníží podíl dlouhých běhů.'},
 ewma:{t:'EWMA poměr zátěže (ACWR)',g:'B',
  fx:`acute   = EWMA(denní km, 7)
chronic = EWMA(denní km, 28)
ratio   = acute / chronic
          potlačeno, pokud chronic < 15 km/týden
          1,30–1,50 = mírně zvýšený · nad 1,50 = zvýšený`,
  why:'Běžecká evidence není prázdná: v prospektivní kohortě 435 běžců měli ti s ACWR pod 0,70 zhruba 10% predikovanou pravděpodobnost běžeckého zranění. Engine proto hlídá obě krajní hodnoty. Nově (v0.4) je horní pásmo rozdělené na dva stupně po vzoru metaanalýzy 46 studií z roku 2025: riziko je jen mírně zvýšené mezi 1,3–1,5 a zřetelněji stoupá až nad 1,5–2,0.',
  limit:'Klasický ACWR má vážné problémy: teoretický základ postrádá robustní evidenci, poměry se hroutí při nízké chronické zátěži a nálezy napříč studiemi si odporují. Známý obrázek „sweet spotu" byl publikován jen jako ilustrativní a pak opakovaně přetištěn, jako by byl validovaný. I metaanalýza z roku 2025 mluví jen o „mírně zvýšeném" riziku, ne o ostré hranici — proto dvoustupňové pásmo místo jednoho prahu.',
  clear:'Poměr se vrátí do 0,7–1,3 po dvou týdnech stabilního objemu.'},
 ewma_mild:{t:'Mírně zvýšený poměr zátěže',g:'B',
  fx:'stejný vzorec jako ewma, pásmo 1,30 < ratio ≤ 1,50',
  why:'2025 metaanalýza 46 studií ukázala, že poměr mezi 1,3 a 1,5 nese jen mírně zvýšené riziko oproti středním hodnotám — proto nižší váha bodů než u zřetelně zvýšeného pásma nad 1,5.',
  limit:'Hranice 1,3/1,5 jsou převzaté z agregátní evidence napříč sporty, ne kalibrované na běžeckou kohortu specificky.',
  clear:'Poměr klesne pod 1,3 po týdnu stabilizovaného objemu.'},
 mono:{t:'Monotónnost tréninku (Foster)',g:'B',
  fx:`monotony = průměr(denní zátěž) / SD(denní zátěž)   [14 dní]
strain   = Σ(zátěž) × monotony`,
  why:'Zachytí běžce, který nikdy nemá skutečně lehký den. Vysoká monotónnost při dostatečném objemu je jiný způsob selhání než objemový skok — metriky založené jen na objemu ji nevidí.',
  limit:'Jeden opravdu volný den v týdnu monotónnost srazí, aniž by se cokoli změnilo na celkové zátěži. Signál je citlivý na to, jak běžec plánuje, ne jen kolik naběhá.',
  clear:'Zařazení jednoho úplného volna a jednoho výrazně kratšího běhu týdně.'},
 desc:{t:'Excentrická zátěž z klesání',g:'C',
  fx:`descent_load = Σ(klesání_m) za 7 dní
spike        = descent_load / baseline`,
  why:'Sbíhání je hlavní zdroj excentrického poškození svalu. Pro trailovou část kohorty je celková vzdálenost zavádějící: 20 km po rovině a 20 km s 900 m klesání jsou stejná čísla a velmi odlišná mechanická zátěž.',
  limit:'Nerozlišuje strmost — proto doplňkový signál desc_steep, který sklon už rozlišuje. 900 m rozložených do dlouhého mírného sjezdu není totéž co 900 m technického srázu.',
  clear:'Týden bez sbíhání nad baseline.'},
 desc_steep:{t:'Nárůst strmého klesání (≥10 % sklon)',g:'C',
  fx:`profil = vzdálenost/nadmořská výška po segmentech (z FIT záznamů nebo syntetizováno pro demo)
buckety = klesání_m rozdělené po 2,5 % sklonu, 0–30 %+
steep_spike = (klesání_m v pásmech ≥10 % za 7 dní) / (týdenní průměr ≥10 % v baseline)`,
  why:'Doplňuje signál „desc" o skutečný sklon místo jen celkových metrů. Excentrické poškození svalu roste se strmostí nelineárně — pozvolný sjezd a technický sráz se stejným celkovým převýšením nejsou mechanicky totéž.',
  limit:'Stupeň C — mechanistická úvaha, ne prospektivně validovaný práh. U demo dat je profil syntetizovaný ze skutečného celkového převýšení běhu, ne měřený.',
  clear:'Týden bez strmého klesání nad baseline.'},
 aer:{t:'Aerobní decoupling',g:'B',
  fx:'decoupling = (tep:tempo 2. půle) / (tep:tempo 1. půle) − 1',
  why:'Nad zhruba 5 % na aerobním běhu naznačuje nedoléčenou únavu. V monitoringu vytrvalců zavedené.',
  limit:'Jako přímý prediktor zranění slabý — proto skóre jen dolaďuje, netvoří ho. Silně ovlivněno horkem a dehydratací.',
  clear:'Chladnější podmínky a týden nižší intenzity.'},
 hrv:{t:'Potlačená variabilita srdečního rytmu',g:'B',
  fx:`z = (HRV průměr 7 dní − baseline 28 dní) / SD
zdroj: noční měření z hodinek`,
  why:'Pokles HRV proti vlastní normě je zavedený marker nedokončené regenerace a autonomní zátěže. Používá se jako modulátor zátěžové osy, ne jako samostatný důvod k zásahu.',
  limit:'HRV reaguje na nemoc, alkohol, cestování i stres v práci stejně jako na trénink. Bez kontextu z check-inu se přeceňuje.',
  clear:'Návrat do ±1 SD po třech nocích.'},
 hrvcv:{t:'Kolísavá HRV mezi dny',g:'C',
  fx:`CV      = SD(HRV, 7 dní) / průměr(HRV, 7 dní) × 100
ratio   = CV_teď / CV_baseline (28 dní)`,
  why:'v0.4. Doplňuje signál potlačené HRV o jinou osu: ne kolik HRV klesla, ale jak nestabilní je den ku dni. Rostoucí den-k-dni variabilita bez poklesu průměru bývá raný marker autonomní nestability, který samotný z-score průměru přehlédne.',
  limit:'Stupeň C — jde o rozšíření zavedeného HRV signálu o novou osu, ne o samostatně prospektivně validovanou metriku. Citlivé na nepravidelné měření (vynechané noci).',
  clear:'Poměr klesne pod 1,2 po týdnu pravidelného měření.'},
 rhr:{t:'Zvýšený klidový tep',g:'B',
  fx:'z = (klidový tep 7 dní − baseline 28 dní) / SD',
  why:'Zvýšení klidového tepu proti vlastní normě obvykle předchází poklesu výkonu a doprovází nedoléčenou únavu nebo začínající infekt.',
  limit:'Nespecifické. Rozlišit infekt od přetížení bez dalších dat nelze — proto se váže na check-in.',
  clear:'Návrat k baseline po dvou až třech dnech.'},
 tsb:{t:'Nepříznivá bilance zátěže (fitness–fatigue)',g:'C',
  fx:`fitness = EWMA(denní km, 42) × 7
fatigue = EWMA(denní km, 7) × 7   (stejné jako 'acute')
balance = fitness − fatigue`,
  why:'v0.4. Banisterův impulz-odezva model z výkonnostní literatury, přenesený sem jako doplňkový pohled na EWMA poměr — lépe funguje při nízké chronické zátěži, kde se ACWR poměr chová nestabilně. Výrazně záporná bilance znamená, že akutní zátěž dlouhodobě předbíhá vybudovanou kapacitu.',
  limit:'Model je odvozený z výkonnosti vytrvalců, ne z prospektivní evidence o zraněních. Stupeň C — doplňkový signál, ne samostatný důvod k zásahu.',
  clear:'Bilance se vrátí nad −8 km/týden po týdnu sníženého objemu.'},
 niggle:{t:'Opakované bolestivé místo',g:'A',
  fx:`niggle_count = počet hodnocení po tréninku
                s příznakem na stejném místě za 21 dní`,
  why:'Sebehodnocená bolest zůstává nejsilnějším jednotlivým prediktorem. Opakované hlášení téhož místa po trénincích je klinicky významnější než jednorázová vysoká hodnota v týdenním check-inu, protože zachytí vzorec vázaný na konkrétní typ zátěže.',
  limit:'Závisí na tom, jestli běžec hodnocení skutečně vyplňuje. Nízká adherence signál umlčí.',
  clear:'Tři týdny bez hlášení na stejném místě.'},
 pain:{t:'Bolest při běhu',g:'A',fx:null,
  why:'Sebehodnocená bolest je nejsilnější jednotlivý prediktor a jediný signál stupně A, který má platforma průběžně k dispozici. Biomechanika ho doplňuje, nenahrazuje.',
  limit:'Retrospektivní a subjektivní. Běžci před závodem systematicky podhodnocují.',
  clear:'Pod 3/10 po dobu dvou týdnů.'},
 sore:{t:'Svalová únava',g:'B',fx:null,
  why:'Vysoká svalová bolestivost po tréninku jako doplňkový signál nedokončené regenerace.',
  limit:'Silně závislá na typu tréninku v předchozích dnech.',clear:'Pod 5/10.'},
 sleep:{t:'Spánkový dluh',g:'B',
  fx:'debt = (baseline_h − průměr_7_dní_h) × 7',
  why:'Spánek pod vlastní normou opakovaně snižuje toleranci zátěže a zhoršuje regeneraci měkkých tkání.',
  limit:'Měření spánku z hodinek je nepřesné, zvlášť u fází. Proto je hodnota ručně přepsatelná.',
  clear:'Týden na baseline.'},
 sleepreg:{t:'Nepravidelná délka spánku',g:'C',
  fx:`SD_teď      = SD(délka spánku, 14 dní)
SD_baseline = SD(délka spánku, 35 dní před tím)
ratio       = SD_teď / SD_baseline`,
  why:'v0.4. Doplňuje spánkový dluh o jinou osu: ne kolik spánku chybí proti průměru, ale jak nepravidelná je jeho délka den ku dni. Nepravidelný spánek je spojován s horší tolerancí zátěže i mimo běžeckou literaturu.',
  limit:'Aproximace — schéma platformy nemá čas usnutí/probuzení, jen délku spánku, takže jde o variabilitu délky, ne o skutečný index pravidelnosti spánkového režimu. Evidence je extrapolovaná, ne přímá.',
  clear:'Poměr klesne pod 1,2 po dvou týdnech pravidelnějšího režimu.'},
 feel:{t:'Zhoršující se pocit z běhu',g:'C',
  fx:'trend = sklon sebehodnocení (1–5) přes 21 dní',
  why:'Klesající subjektivní pocit z běhu při nezměněné zátěži bývá první věc, které si běžec všimne — dřív než bolesti.',
  limit:'Stupeň C. Ovlivněno počasím, motivací i tím, jak šel poslední závod.',
  clear:'Stabilní nebo rostoucí trend po dvou týdnech.'},
 stiffness:{t:'Ztuhlost nohou před během',g:'C',
  fx:`ignoreRate = (běhů s vysokou ztuhlostí A RPE ≥ 6) / (běhů s vysokou ztuhlostí)
trend      = sklon sebehodnocené ztuhlosti (1–5) přes 21 dní`,
  why:'v0.5. Ztuhlost nohou před během je subjektivní signál nedokončené regenerace, sbíraný retrospektivně při hodnocení běhu. Sama o sobě je to jen další symptom — zajímavější je vzorec, kdy běžec i přes hlášenou ztuhlost trénuje s vysokou vnímanou námahou: to naznačuje sníženou schopnost poslouchat vlastní tělo, ne jen únavu samotnou.',
  limit:'Stupeň C, čistě sebehodnocené. Závisí na tom, jak poctivě a pravidelně běžec vyplňuje hodnocení, a na tom, jak dobře umí ztuhlost od svalové bolesti rozeznat.',
  clear:'Ztuhlost před během klesne pod 4/5, nebo se poměr trénování navzdory ztuhlosti vrátí pod 50 %.'},
 taper:{t:'Blízký závod při zvýšené zátěži',g:'C',
  fx:'aktivní jen když dní_do_závodu ≤ 21 A (zátěžové skóre ≥ 25 NEBO EWMA poměr > 1,3)',
  why:'Cíl a termín se nikde v aplikaci nepoužívají jako primární rámec — jsou informační poznámka pod čarou. Tenhle signál je výjimka: kombinace blízkého závodu se zátěží, která už je zvýšená, je přesně situace, kdy běžci nejčastěji naskočí na trénink navzdory signálům místo odlehčení.',
  limit:'Stupeň C — logická kombinace dvou already-existujících signálů (termín + zátěž), ne samostatně validovaný prediktor. Nehodnotí kvalitu tréninkového plánu, jen jeho načasování.',
  clear:'Buď zátěžové skóre klesne pod práh, nebo závod proběhne/termín se posune.'},
 hist:{t:'Zranění v anamnéze',g:'A',fx:null,
  why:'Předchozí zranění je konzistentně nejsilnější prediktor dalšího zranění napříč studiemi.',
  limit:'Neměnný faktor. Nedá se odstranit, jen zohlednit ve váze ostatních signálů.',
  clear:'Po 12 měsících bez recidivy váha klesá.'}
};

const QUAD={
  stable:{t:'Stabilní',d:'Zátěž i mechanika sedí na vlastní normě.',c:'ok'},
  overreaching:{t:'Přetížení',d:'Zátěž vyskočila, ale technika zatím drží. Deload obvykle stačí.',c:'watch'},
  silent:{t:'Tichý drift',d:'Mechanika se mění bez nárůstu objemu. Tohle čistě objemové aplikace nevidí.',c:'info'},
  critical:{t:'Kritická kombinace',d:'Zátěž i mechanika se hýbou naráz.',c:'alert'}
};
const TIER={ok:'Nízké riziko',watch:'Sledovat',alert:'Vysoké riziko'};
const PHASE={offload:'odlehčení',rebuild:'budování',return:'návrat k běhu',prevent:'prevence'};
const AI_INTENTS=[
  ['summary','Shrň posledních 28 dní'],
  ['change','Co se změnilo od minulé kontroly'],
  ['where','Kde může být problém'],
  ['program','Co upravit v programu'],
  ['missing','Jaká data chybí']
];
const FEEL_LABEL={1:'špatný',2:'slabší',3:'normální',4:'dobrý',5:'výborný'};

/* ---------- 3 · reálné API ----------
   Nahrazuje dřívější mock nad in-memory DB. Stejné jméno metody, stejný
   tvar odpovědi (kde to dávalo smysl) — jen místo synchronní práce nad
   polem v paměti jde o fetch() na FastAPI backend přes cookie relaci. */
class ApiError extends Error{
  constructor(status,message){super(message);this.status=status;this.name='ApiError'}
}
const API_LOG=[];
async function apiCall(method,path,body,opts={}){
  const init={method,credentials:'include',headers:{}};
  if(body instanceof FormData){init.body=body}
  else if(body!==undefined){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
  const t0=performance.now();
  let res;
  try{res=await fetch(path,init)}
  catch(netErr){throw new ApiError(0,'Síť neodpovídá. Zkontrolujte připojení a zkuste to znovu.')}
  const ms=Math.round(performance.now()-t0);
  const text=await res.text();
  let data=null;
  if(text){try{data=JSON.parse(text)}catch(e){data=null}}
  API_LOG.unshift({m:method,p:path,ms,status:res.status,
    at:new Date().toLocaleTimeString('cs-CZ'),rows:Array.isArray(data)?data.length:1});
  if(API_LOG.length>50)API_LOG.pop();
  if(res.status===401&&!opts.skipAuthRedirect){
    AUTH._user=null;AUTH._loaded=true;
    const next=encodeURIComponent(location.pathname+location.hash);
    location.href='auth.html?next='+next;
    throw new ApiError(401,'Nepřihlášeno');
  }
  if(!res.ok){
    const msg=(data&&data.detail)?data.detail:`Chyba serveru (${res.status})`;
    throw new ApiError(res.status,msg);
  }
  return data;
}

const api={
  /* auth */
  authMe:()=>apiCall('GET','/api/auth/me',undefined,{skipAuthRedirect:true}),
  authRegister:payload=>apiCall('POST','/api/auth/register',payload),
  authSignIn:(email,password,expectedRole)=>apiCall('POST','/api/auth/session',
    {email,password,expected_role:expectedRole||undefined},{skipAuthRedirect:true}),
  authLogout:()=>apiCall('POST','/api/auth/logout'),
  getSettings:()=>apiCall('GET','/api/auth/settings'),
  patchSettings:patch=>apiCall('PATCH','/api/auth/settings',patch),

  /* runner-scoped */
  runner:id=>apiCall('GET',`/api/runners/${id}`),
  assessment:id=>apiCall('GET',`/api/runners/${id}/assessment`),
  bootstrap:id=>apiCall('GET',`/api/runners/${id}/bootstrap`),
  activities:(id,n=10)=>apiCall('GET',`/api/runners/${id}/activities?limit=${n}`),
  unrated:id=>apiCall('GET',`/api/runners/${id}/activities/unrated`),
  rateActivity:(rid,aid,body)=>apiCall('POST',`/api/runners/${rid}/activities/${aid}/rate`,body),
  daily:(id,n=14)=>apiCall('GET',`/api/runners/${id}/daily?days=${n}`),
  editDaily:(rid,date,patch,note)=>apiCall('PATCH',`/api/runners/${rid}/daily/${date}`,{patch,note}),
  checkin:(id,body)=>apiCall('POST',`/api/runners/${id}/checkins`,body),
  injuryReports:id=>apiCall('GET',`/api/runners/${id}/injury-reports`),
  reportInjury:(id,body)=>apiCall('POST',`/api/runners/${id}/injury-report`,body),
  setInterest:(rid,interested)=>apiCall('POST',`/api/runners/${rid}/physio-interest`,{interested}),
  bookingOptions:(dow,daypart)=>apiCall('GET',`/api/booking/options?dow=${dow||''}&daypart=${daypart||''}`),
  requestSlot:(slotId,kind)=>apiCall('POST','/api/booking/request',{slot_id:slotId,kind:kind||'assessment'}),
  cancelBooking:(rid,bid)=>apiCall('POST',`/api/runners/${rid}/bookings/${bid}/cancel`,{}),
  declinePhysio:(rid,pid)=>apiCall('POST',`/api/runners/${rid}/physios/${pid}/decline`,{}),
  bookings:id=>apiCall('GET',`/api/runners/${id}/bookings`),
  book:(rid,physioId,kind,daysAhead)=>apiCall('POST',`/api/runners/${rid}/bookings`,
    {physio_id:physioId,kind,days_ahead:daysAhead}),
  program:id=>apiCall('GET',`/api/runners/${id}/program`),
  logEx:(rid,exId)=>apiCall('PATCH',`/api/runners/${rid}/exercises/${exId}/log`,{}),
  messages:id=>apiCall('GET',`/api/runners/${id}/messages`),
  send:(id,sender,body)=>apiCall('POST',`/api/runners/${id}/messages`,{sender,body}),
  garminIngest:(file,fit)=>{const fd=new FormData();fd.append('file',file);
    return apiCall('POST',`/api/integrations/garmin/import?fit=${fit?'true':'false'}`,fd)},
  appleIngest:file=>{const fd=new FormData();fd.append('file',file);
    return apiCall('POST','/api/integrations/apple/import',fd)},
  garminConnect:(email,password)=>apiCall('POST','/api/integrations/garmin/connect',{email,password}),
  garminMfa:(mfaToken,mfaCode)=>apiCall('POST','/api/integrations/garmin/connect/mfa',{mfa_token:mfaToken,mfa_code:mfaCode}),

  /* physio-scoped */
  physioBootstrap:id=>apiCall('GET',`/api/physios/${id}/bootstrap`),
  queue:(status='open',scope='clinic')=>apiCall('GET',`/api/triage?status=${status}&scope=${scope}`),
  claim:tid=>apiCall('PATCH',`/api/triage/${tid}/claim`,{}),
  physioSlots:pid=>apiCall('GET',`/api/physios/${pid}/slots`),
  addSlot:(pid,slotAt,dur)=>apiCall('POST',`/api/physios/${pid}/slots`,{slot_at:slotAt,duration_min:dur||45}),
  removeSlot:sid=>apiCall('DELETE',`/api/physios/slots/${sid}`),
  confirmBooking:bid=>apiCall('POST',`/api/bookings/${bid}/confirm`,{}),
  declineBooking:bid=>apiCall('POST',`/api/bookings/${bid}/decline`,{}),
  setPrep:(bid,text)=>apiCall('PATCH',`/api/bookings/${bid}/prep`,{prep_info:text}),
  draftProgram:(rid,site)=>apiCall('POST','/api/programs',{runner_id:rid,site}),
  exerciseLibrary:(q,category)=>apiCall('GET',
    `/api/programs/exercise-library?q=${encodeURIComponent(q||'')}&category=${encodeURIComponent(category||'')}`),
  addExercise:(pid,ex)=>apiCall('POST',`/api/programs/${pid}/exercises`,ex),
  editExercise:(exId,patch,note)=>apiCall('PATCH',`/api/programs/exercises/${exId}`,{patch,note}),
  removeExercise:exId=>apiCall('DELETE',`/api/programs/exercises/${exId}`),
  sendProgram:(pid,note)=>apiCall('POST',`/api/programs/${pid}/send`,{note}),
  createRtr:body=>apiCall('POST','/api/rtr',body),
  rtr:pid=>apiCall('GET',`/api/rtr/${pid}`),
  logRtrSession:(pid,body)=>apiCall('POST',`/api/rtr/${pid}/session`,body),
  updateRtr:(pid,status)=>apiCall('PATCH',`/api/rtr/${pid}?status=${status}`,{}),
  openConclusion:bid=>apiCall('POST',`/api/bookings/${bid}/conclusion`,{}),
  conclusion:cid=>apiCall('GET',`/api/conclusions/${cid}`),
  editConclusion:(cid,patch)=>apiCall('PATCH',`/api/conclusions/${cid}`,patch),
  approveConclusion:cid=>apiCall('POST',`/api/conclusions/${cid}/approve`,{}),
  uploadConclusionAudio:(cid,blob,filename)=>{const fd=new FormData();
    fd.append('file',blob,filename||'session.webm');
    return apiCall('POST',`/api/conclusions/${cid}/audio`,fd)},
  aiBrief:(rid,intent)=>apiCall('POST','/api/ai/brief',{runner_id:rid,intent}),
  aiChat:(rid,message,history)=>apiCall('POST','/api/ai/chat',{runner_id:rid,message,history}),

  /* employer / partner */
  cohort:eid=>apiCall('GET',`/api/employers/${eid}/cohort`),
  refs:pid=>apiCall('GET',`/api/partners/${pid}/referrals`),
  directory:pid=>apiCall('GET',`/api/partners/${pid}/directory`)
};

/* ---------- 3b · účty a relace (reálné, na cookie session) ---------- */
const AUTH={
  _user:null,_loaded:false,
  async load(){
    if(this._loaded)return this._user;
    try{this._user=await api.authMe()}catch(e){this._user=null}
    this._loaded=true;
    return this._user;
  },
  current(){return this._user},
  async signIn(email,password,expectedRole){
    const u=await api.authSignIn(email,password,expectedRole);
    this._user=u;this._loaded=true;return u;
  },
  async register(payload){
    const u=await api.authRegister(payload);
    this._user=u;this._loaded=true;return u;
  },
  async signOut(){
    try{await api.authLogout()}catch(e){/* ignore */}
    this._user=null;this._loaded=true;
  }
};
const ROLE_HOME={runner:'runner.html',physio:'physio.html',employer:'employer.html',partner:'partner.html'};
const ROLE_LABEL_CS={runner:'běžec',physio:'fyzioterapeut',employer:'zaměstnavatel',partner:'partner'};

/* Zavolá se na začátku každé chráněné stránky. Nepřihlášený → auth.html.
   Špatná role pro tuhle stránku → vlastní domovská stránka té role. */
async function guard(...allowedRoles){
  const u=await AUTH.load();
  if(!u){
    const next=encodeURIComponent(location.pathname.split('/').pop()+location.hash);
    location.href='auth.html?role='+(allowedRoles[0]||'runner')+'&next='+next;
    return null;
  }
  if(allowedRoles.length&&!allowedRoles.includes(u.role)){
    location.href=ROLE_HOME[u.role]||'index.html';
    return null;
  }
  return u;
}

let SETTINGS={units:'metric',locale:'cs',share_with_physio:true,share_bodymap:true,
  employer_aggregate:true,notify_checkin:true,notify_drift:true};
async function loadSettings(){
  try{Object.assign(SETTINGS,await api.getSettings())}catch(e){/* zůstanou výchozí */}
  return SETTINGS;
}

/* ---------- 4 · UI komponenty ---------- */
function toast(m,k){const t=$('#toast');if(!t)return;
  t.innerHTML=(k?`<b>${esc(k)}</b>`:'')+esc(m);t.classList.add('on');
  clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('on'),3000)}
function openSheet(html){const s=$('#sheet');$('#sheetbody').innerHTML=html;
  s.classList.add('on');$('#scrim').classList.add('on')}
function closeSheet(){$('#sheet')?.classList.remove('on');$('#scrim')?.classList.remove('on')}
function errCard(err,retry){
  const msg=err instanceof ApiError?err.message:'Něco se nepovedlo. Zkuste to prosím znovu.';
  return `<div class="card"><div class="lbl" style="color:var(--alert)">Nepodařilo se načíst data</div>
    <p class="sub" style="margin-top:8px">${esc(msg)}</p>
    ${retry?`<button class="btn ghost sm" style="margin-top:12px" data-act="${retry}">Zkusit znovu</button>`:''}</div>`;
}
function skeleton(n=3){
  return `<div class="card"><div class="skel" style="height:16px;width:40%;margin-bottom:14px"></div>
    ${Array.from({length:n}).map(()=>'<div class="skel" style="height:12px;margin-bottom:10px"></div>').join('')}</div>`;
}

const _num=v=>v==null?'—':(Number.isInteger(v)?v:r1(v));
function sparkline(vals,color='var(--navy-600)',h=52){
  if(!vals||vals.length<2)return '';
  const w=300,mx=Math.max(...vals),mn=Math.min(...vals),rg=mx-mn||1,last=vals.at(-1);
  const pts=vals.map((v,i)=>[i/(vals.length-1)*w,h-((v-mn)/rg)*(h-8)-4]);
  const d=pts.map((p,i)=>`${i?'L':'M'}${r1(p[0])} ${r1(p[1])}`).join(' ');
  const area=`M0 ${h} L`+pts.map(p=>`${r1(p[0])} ${r1(p[1])}`).join(' L')+` L${w} ${h} Z`;
  return `<div class="sparkwrap">
    <svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path class="zone" d="${area}" fill="${color}"/>
      <path class="ln" d="${d}" stroke="${color}" style="--len:${w*1.4}"/>
      <circle cx="${r1(pts.at(-1)[0])}" cy="${r1(pts.at(-1)[1])}" r="3.5" fill="${color}"/></svg>
    <span class="sp-y sp-max">${_num(mx)}</span>
    <span class="sp-y sp-min">${_num(mn)}</span>
    <span class="sp-now" style="color:${color}">nyní ${_num(last)}</span></div>`;
}
/* Sloupcový graf s osou. `opts.labels` přepíše auto popisky osy X, `opts.timeLabels`
   (výchozí zapnuté) generuje „teď / −N t|d" podle délky série (12 = týdny, jinak dny). */
function barchart(vals,unit='km',opts={}){
  if(!vals||!vals.length)return '';
  const n=vals.length,mx=Math.max(...vals,1),dense=n>14,per=n<=13?'t':'d';
  const agoWord=(a,w)=>a===0?(w?'tento týden':'dnes'):`před ${a} ${w?(a>=2&&a<=4?'týdny':a===1?'týdnem':'týdny'):(a===1?'dnem':'dny')}`;
  const xlab=i=>{
    if(opts.labels)return opts.labels[i]||'';
    if(i===n-1)return 'teď';
    if(i===0)return `−${n-1}${per}`;
    if(i===Math.floor((n-1)/2))return `−${n-1-i}${per}`;
    return '';
  };
  const tip=i=>opts.labels?opts.labels[i]:agoWord(n-1-i,per==='t');
  return `<div class="chart">
    <div class="chart-body">
      <div class="chart-yax"><span>${_num(mx)}<small> ${esc(unit)}</small></span><span>0</span></div>
      <div class="chart-plot"><div class="chart-bars">${vals.map((v,i)=>{
        const last=i===n-1,showv=!dense||last||v===mx;
        return `<div class="chart-col${last?' hot':''}" title="${tip(i)}: ${_num(v)} ${esc(unit)}">
          ${showv?`<span class="v">${_num(v)}</span>`:''}
          <i style="height:${Math.max(3,v/mx*82)}%"></i></div>`;
      }).join('')}</div>
      <div class="chart-xax">${vals.map((_,i)=>`<span>${xlab(i)}</span>`).join('')}</div></div>
    </div>
  </div>`;
}
function recoveryGauge(score,label){
  if(score==null)return '';
  const pct=clamp(score,0,100);
  const col=pct>=65?'var(--ok)':pct>=40?'var(--navy-600)':pct>=20?'var(--watch)':'var(--alert)';
  const rad=42,circ=2*Math.PI*rad,off=circ*(1-pct/100);
  return `<div style="display:flex;align-items:center;gap:14px">
    <svg width="82" height="82" viewBox="0 0 100 100" style="flex:0 0 auto" aria-hidden="true">
      <circle cx="50" cy="50" r="${rad}" fill="none" stroke="var(--glass-14)" stroke-width="10"/>
      <circle cx="50" cy="50" r="${rad}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"
        stroke-dasharray="${r1(circ)}" stroke-dashoffset="${r1(off)}" transform="rotate(-90 50 50)"
        style="transition:stroke-dashoffset .8s cubic-bezier(.32,.72,.25,1)"/>
      <text x="50" y="46" text-anchor="middle" font-size="26" font-weight="800" font-family="var(--mono)" fill="var(--ink)">${pct}</text>
      <text x="50" y="64" text-anchor="middle" font-size="9" fill="var(--muted)">ze 100</text>
    </svg>
    <div><b style="font-size:15px">${esc(label)}</b><div class="sub" style="margin-top:2px">regenerace proti vaší vlastní normě, ne populačnímu průměru</div></div>
  </div>`;
}
function gradientChart(gd){
  if(!gd||!gd.buckets?.some(v=>v>0))return `<div class="empty">Za posledních 7 dní žádné klesání s profilem nadmořské výšky.</div>`;
  const mx=Math.max(...gd.buckets,1);
  return `<div style="display:flex;gap:8px;margin-top:10px">
    <div class="chart-yax" style="height:90px"><span>${_num(mx)}<small> m</small></span><span>0</span></div>
    <div style="flex:1;min-width:0">
      <div style="display:flex;align-items:flex-end;gap:3px;height:90px;border-bottom:1px solid var(--glass-14)">
        ${gd.buckets.map((v,i)=>`<div style="flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%">
          ${v>0?`<span style="font:600 8px var(--mono);color:var(--muted);margin-bottom:2px;line-height:1">${_num(v)}</span>`:''}
          <div style="width:100%;border-radius:3px 3px 0 0;height:${Math.max(2,v/mx*82)}%;
            background:${i>=4?'var(--alert)':'var(--navy-400)'};opacity:${i>=4?1:.6}" title="${gd.labels[i]}: ${v} m"></div>
          </div>`).join('')}</div>
      <div style="display:flex;gap:3px;margin-top:4px">
        ${gd.buckets.map((_,i)=>`<div style="flex:1;min-width:0;text-align:center;font-size:8.5px;color:var(--faint);writing-mode:vertical-rl;height:42px">${gd.labels[i]}</div>`).join('')}</div>
    </div>
  </div>
  <div class="sub" style="margin-top:8px">Osa Y = metry klesání v pásmu sklonu (osa X). ${gd.total7} m za 7 dní celkem · ${gd.steep7} m na sklonu ≥10 % (červené sloupce)${gd.steepSpike?` · ×${gd.steepSpike} proti obvyklému týdnu`:''}.</div>`;
}
const QUAD_TAKEAWAY={
  stable:'Nic tu teď nevyžaduje zásah — pokračujte podle plánu.',
  overreaching:'Objem je zvýšený, ale technika zatím drží — zvažte jeden odlehčený týden dřív, než na to dojde.',
  silent:'Technika se mění, i když objem neroste a nic nebolí — tohle je moment, kdy má vyšetření největší cenu.',
  critical:'Zátěž i technika se hýbou naráz — priorita je teď vyšetření, ne další trénink.',
};
function quadCard(a,opts={}){
  const q=QUAD[a.quadrant];
  return `<div class="card ${opts.tap?'tap lift':''}" ${opts.tap?'data-act="quaddoc"':''}>
    <div class="cardhead"><div><div class="lbl">Rizikový kvadrant</div>
      <h2 style="margin-top:8px">${q.t}</h2></div>
      <span class="chip ${a.tier}">${a.overall}/100</span></div>
    <div class="sub">${q.d}</div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <div style="writing-mode:vertical-rl;transform:rotate(180deg);display:flex;align-items:center;justify-content:space-between;
        font-size:10px;font-weight:700;letter-spacing:.04em;color:var(--faint);text-transform:uppercase;padding:2px 0">
        <span>zátěž vysoká</span><span>zátěž běžná</span></div>
      <div style="flex:1">
        <div class="quad">
          <div class="cell c-tl">Přetížení</div><div class="cell c-tr">Kritické</div>
          <div class="cell c-bl">Stabilní</div><div class="cell c-br">Tichý drift</div>
          <div class="dot" style="left:${clamp(a.mech,4,96)}%;bottom:${clamp(a.load,4,96)}%"></div>
        </div>
        <div class="quadax"><span>← mechanika stabilní</span><span>drift →</span></div>
      </div>
    </div>
    <div class="note" style="margin-top:12px">${esc(QUAD_TAKEAWAY[a.quadrant]||'')}</div>
    <div class="divide"></div>
    <div style="display:flex;gap:20px">
      <div style="flex:1"><div class="lbl">Mechanika</div><div class="mid">${a.mech}</div></div>
      <div style="flex:1"><div class="lbl">Zátěž</div><div class="mid">${a.load}</div></div>
      <div style="flex:1"><div class="lbl">Příznaky</div><div class="mid">${a.symp}</div></div>
    </div></div>`;
}
const GCOL={A:'var(--alert)',B:'var(--watch)',C:'var(--blue)'};
const GBG={A:'var(--alert-soft)',B:'var(--watch-soft)',C:'var(--blue-soft)'};
function signalRows(a,rid){
  if(!a.signals.length)return `<div class="empty">Žádný signál nad prahem. Trénink i mechanika sedí na vlastní normě.</div>`;
  return a.signals.map(s=>`<div class="mrow tap" data-act="sig" data-id="${s.id}" data-runner="${rid||a.runner_id}">
    <div class="ico" style="background:${GBG[s.grade]};color:${GCOL[s.grade]}">${s.grade}</div>
    <div class="nm"><b>${esc(s.name)}</b><em>${esc(s.detail)}</em></div>
    <div class="vl"><b>${esc(s.val)}</b><span class="sub" style="margin:0">+${s.pts} b.</span></div>
    <div class="arw">›</div></div>`).join('');
}
function confCard(c){
  const pct=Math.round(c.value*100);
  return `<div class="card tap lift" data-act="confdoc">
    <div class="cardhead"><div class="lbl">Spolehlivost baseline</div>
      <span class="chip ${c.value>=.6?'ok':'watch'}">${pct} %</span></div>
    <div class="meter"><i style="width:${pct}%;background:${c.value>=.6?'var(--ok)':'var(--watch)'}"></i></div>
    <div class="sub">${esc(c.note)} ${c.sessions} shodných tréninků za 28 dní · ${c.days} dní historie</div></div>`;
}

/* detail metriky — sdílený napříč entitami. `a` je assessment naposledy
   načtený tou stránkou (window.D.CURRENT_ASSESSMENT) */
function metricSheet(id,rid){
  const d=SIG_DOC[id];if(!d)return;
  const a=window.D.CURRENT_ASSESSMENT;
  const s=a?.signals?.find(x=>x.id===id);
  let live='';
  if(a){
    if(id==='tavr'&&a.tavr){
      live=`<h4>Data pacienta po profilech terénu</h4>
        <div class="tw"><table><thead><tr><th>Profil</th><th>Baseline</th><th>Teď</th><th>z</th><th>Běhů</th></tr></thead>
        <tbody>${a.tavr.detail.map(x=>`<tr><td>${esc(x.label)}</td><td class="mono">${x.base}</td>
          <td class="mono">${x.now}</td><td class="mono" style="color:${x.z>=1?'var(--watch)':'inherit'}">${sgn(x.z)}</td>
          <td class="mono">${x.nNow}/${x.nBase}</td></tr>`).join('')}</tbody></table></div>
        ${sparkline(a.tavr.series,'var(--watch)')}`;
    }
    if(id==='bal'&&a.bal)live=`<h4>Vývoj symetrie</h4>${sparkline(a.bal.series,'var(--watch)')}
      <p class="sub">Baseline ${a.bal.baseline} % · teď ${a.bal.now} % · posun ${a.bal.excursion} p.b. na stranu: ${a.bal.side}.</p>`;
    if(id==='dec'&&a.dec)live=`<h4>Rozpad techniky po bězích</h4>${sparkline(a.dec.series,'var(--alert)')}
      <p class="sub">${a.dec.dates.map((dt,i)=>`${fmtD(dt)}: ${sgn(a.dec.series[i])} %`).join(' · ')}</p>`;
    if((id==='ewma'||id==='ewma_mild')&&a.loadDetail)live=`<h4>Týdenní objem</h4>${barchart(a.loadDetail.weekly)}
      <p class="sub">Akutní ${a.loadDetail.acute} km · chronický ${a.loadDetail.chronic} km${a.loadDetail.valid?` · poměr ×${a.loadDetail.ratio}`:' · poměr potlačen, chronická zátěž pod 15 km'}.</p>`;
    if(id==='tsb'&&a.loadDetail)live=`<p class="sub">Fitness (42denní EWMA) ${a.loadDetail.fitness42} km/týden proti aktuální zátěži ${a.loadDetail.acute} km/týden · bilance ${sgn(a.loadDetail.tsbBalance)} km/týden.</p>`;
    if(id==='hrv'&&a.rcv)live=`<h4>HRV za 7 dní</h4>${sparkline(a.rcv.hrv.series,'var(--watch)')}
      <p class="sub">Baseline ${a.rcv.hrv.base} ms · teď ${a.rcv.hrv.now} ms.</p>`;
    if(id==='hrvcv'&&a.hrvCv)live=`<p class="sub">Den-k-dni variabilita HRV ${a.hrvCv.cvNow} % proti obvyklým ${a.hrvCv.cvBase} % (poměr ×${a.hrvCv.ratio}).</p>`;
    if(id==='rhr'&&a.rcv)live=`<h4>Klidový tep za 7 dní</h4>${sparkline(a.rcv.rhr.series,'var(--watch)')}`;
    if(id==='sleep'&&a.rcv)live=`<h4>Spánek za 7 dní</h4>${sparkline(a.rcv.sleep.series,'var(--navy-600)')}
      <p class="sub">Baseline ${a.rcv.sleep.base} h · teď ${a.rcv.sleep.now} h${a.rcv.edited?` · ${a.rcv.edited} dní ručně opraveno`:''}.</p>`;
    if(id==='sleepreg'&&a.sleepReg)live=`<p class="sub">Kolísání délky spánku ${a.sleepReg.sdNow} h proti obvyklým ${a.sleepReg.sdBase} h (poměr ×${a.sleepReg.ratio}).</p>`;
    if(id==='desc_steep'&&a.gradientDescent)live=`<h4>Klesání za 7 dní podle sklonu</h4>${gradientChart(a.gradientDescent)}`;
    if(id==='stiffness'&&a.stiffness)live=`<h4>Ztuhlost před během, poslední hodnocení</h4>${sparkline(a.stiffness.series,'var(--watch)')}
      <p class="sub">Průměr ${a.stiffness.mean}/5 za ${a.stiffness.n} hodnocení · trénováno navzdory ztuhlosti ${a.stiffness.pushedThroughCount}/${a.stiffness.highCount}×.</p>`;
    if(id==='niggle'&&a.fb&&a.fb.recent?.length)live=`<h4>Hlášení po trénincích</h4>
      <div class="tw"><table><thead><tr><th>Datum</th><th>Pocit</th><th>Bolest</th><th>Místo</th></tr></thead>
      <tbody>${a.fb.recent.map(f=>`<tr><td class="mono">${fmtD(f.submitted_at)}</td>
        <td>${FEEL_LABEL[f.feeling]||'—'}</td><td class="mono">${f.pain_during}/10</td>
        <td>${esc(f.pain_site||'—')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  openSheet(`
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
      <span class="chip grade ${d.g==='A'?'alert':d.g==='B'?'watch':'info'}">Stupeň ${d.g}</span>
      <span class="sub" style="margin:0">${esc(GRADE_NOTE[d.g])}</span>
      ${s?`<span class="chip glass">přispívá +${s.pts} b.</span>`:''}</div>
    <h2>${esc(d.t)}</h2>
    ${s?`<div class="note" style="margin-top:12px">Aktuální hodnota u tohoto běžce: <b>${esc(s.val)}</b> — ${esc(s.detail)}</div>`:''}
    ${d.fx?`<div class="fx">${esc(d.fx)}</div>`:''}
    <h4 style="margin-top:18px;font-size:12.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--navy-600)">Proč to sledujeme</h4>
    <p style="color:var(--muted);font-size:14px;margin-top:6px">${d.why}</p>
    <h4 style="margin-top:16px;font-size:12.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--navy-600)">Kde to selhává</h4>
    <p style="color:var(--muted);font-size:14px;margin-top:6px">${d.limit}</p>
    <h4 style="margin-top:16px;font-size:12.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--navy-600)">Kdy signál zmizí</h4>
    <p style="color:var(--muted);font-size:14px;margin-top:6px">${d.clear}</p>
    ${live?`<div class="divide"></div>${live}`:''}
    <button class="btn ghost" style="margin-top:22px;width:100%" data-act="close">Zavřít</button>`);
}
function quadSheet(){
  openSheet(`<h2>Proč dvě osy a ne jedno číslo</h2>
    <p style="color:var(--muted);font-size:14px;margin-top:10px">Zátěž a mechanika jsou různé třídy evidence a sčítat je do jednoho skóre by zamlžilo, co se vlastně děje. Kvadrant říká, jaký typ zásahu dává smysl.</p>
    <div class="fx">                  MECHANIKA →
                  stabilní      driftuje
  Z   vysoká   │ přetížení    │ kritické
  Á            │ deload       │ objednat fyzio
  T   ────────────────────────────────────
  Ě   běžná    │ stabilní     │ TICHÝ DRIFT
  Ž            │              │ ← obchodní klín</div>
    <p style="color:var(--muted);font-size:14px">Pravý dolní kvadrant je ten, kvůli kterému produkt existuje. Běžec, jehož mechanika se mění bez nárůstu objemu a bez bolesti, je pro čistě objemové aplikace neviditelný.</p>
    <button class="btn ghost" style="margin-top:20px;width:100%" data-act="close">Zavřít</button>`);
}
function confSheet(){
  const a=window.D.CURRENT_ASSESSMENT;
  openSheet(`<h2>Spolehlivost baseline</h2>
    <div class="fx">confidence = min(1, shodné_tréninky / 8)
           × min(1, dní_historie / 42)

pod 0,60 → mechanické signály se nezobrazují</div>
    <p style="color:var(--muted);font-size:14px">Běžec se třemi týdny dat a dvěma běhy v terénu nemá důvěryhodný trailový baseline. Vydat na tom červený alert je nejrychlejší způsob, jak přijít o uživatele. Poctivé „zatím nevím" je lepší produkt než sebejistá špatná odpověď.</p>
    ${a?`<div class="note" style="margin-top:14px">U tohoto běžce: ${a.confidence.sessions} shodných tréninků za 28 dní, ${a.confidence.days} dní historie, ${a.confidence.baseSessions} běhů v baseline okně.</div>`:''}
    <button class="btn ghost" style="margin-top:20px;width:100%" data-act="close">Zavřít</button>`);
}

/* ---------- 4b · gesta: swipe karty a odkrývání detailu ---------- */
function swipeCard(faces,opts={}){
  const id='sw'+Math.random().toString(36).slice(2,8);
  return `<div class="card swipe" id="${id}" data-swipe>
    ${faces.length>1?'<div class="swipe-cue">táhnout ‹›</div>':''}
    <div class="swipe-track">${faces.map(f=>`<div class="swipe-face">${f}</div>`).join('')}</div>
    ${faces.length>1?`<div class="swipe-dots">${faces.map((_,i)=>
      `<i class="${i?'':'on'}"></i>`).join('')}</div>`:''}</div>`;
}
function bindSwipes(root=document){
  root.querySelectorAll('[data-swipe]').forEach(el=>{
    if(el._bound)return; el._bound=true;
    const track=el.querySelector('.swipe-track'), dots=[...el.querySelectorAll('.swipe-dots i')];
    const n=el.querySelectorAll('.swipe-face').length;
    let i=0,x0=null,dx=0,dragging=false;
    const go=k=>{i=Math.max(0,Math.min(n-1,k));
      track.style.transform=`translateX(${-i*100}%)`;
      dots.forEach((d,j)=>d.classList.toggle('on',j===i));
      el.querySelector('.swipe-cue')?.style.setProperty('opacity',i===n-1?'0':'');};
    const start=e=>{if(n<2)return;dragging=true;x0=(e.touches?e.touches[0]:e).clientX;
      track.style.transition='none'};
    const move=e=>{if(!dragging)return;
      dx=(e.touches?e.touches[0]:e).clientX-x0;
      track.style.transform=`translateX(calc(${-i*100}% + ${dx}px))`;};
    const end=()=>{if(!dragging)return;dragging=false;
      track.style.transition='';
      if(Math.abs(dx)>44)go(i+(dx<0?1:-1));else go(i);dx=0};
    el.addEventListener('touchstart',start,{passive:true});
    el.addEventListener('touchmove',move,{passive:true});
    el.addEventListener('touchend',end);
    el.addEventListener('mousedown',start);
    window.addEventListener('mousemove',move);
    window.addEventListener('mouseup',end);
    dots.forEach((d,j)=>d.addEventListener('click',()=>go(j)));
  });
  root.querySelectorAll('.reveal-tag').forEach(t=>{
    if(t._bound)return;t._bound=true;
    t.addEventListener('click',()=>{
      const r=t.parentElement.querySelector('.reveal');
      if(!r)return;
      const on=r.classList.toggle('on');
      t.textContent=on?(t.dataset.less||'Skrýt detail ▴'):(t.dataset.more||'Zobrazit detail ▾');
    });
  });
}
function reveal(inner,moreLabel){
  return `<div class="reveal">${inner}</div>
    <span class="reveal-tag" data-more="${moreLabel||'Zobrazit detail ▾'}"
      data-less="Skrýt detail ▴">${moreLabel||'Zobrazit detail ▾'}</span>`;
}

/* ---------- 5 · navigace ---------- */
const ENTITIES=[['runner.html','Běžec'],['physio.html','Fyzioterapeut'],
  ['employer.html','Zaměstnavatel'],['partner.html','Partner'],['data.html','Data']];
const TABS={
  runner:[['today','Dnešek'],['post','Po tréninku'],['mech','Mechanika'],['load','Zátěž'],
    ['program','Program'],['msgs','Zprávy']],
  physio:[['queue','K posouzení'],['calendar','Kalendář'],['programs','Programy']],
  patient:[['overview','Přehled'],['mech','Mechanika'],['load','Zátěž a regenerace'],
    ['diary','Deník pacienta'],['program','Program'],['ai','AI souhrn']],
  employer:[['cohort','Kohorta'],['signals','Rizikové signály'],['roi','Návratnost'],['privacy','Ochrana dat']],
  partner:[['refs','Doporučení'],['payout','Provize'],['days','Diagnostické dny']],
  data:[['import','Import z Garminu'],['tables','Tabulky'],['engine','Engine'],['api','API log']]
};
const NAVICON={
 'runner.html':'<path d="M13 4a1.6 1.6 0 1 0 0-.1M8 20l2.5-5 2-2.5-1.5-4-3 2-1.5 3M12.5 8.5l3 2 1 3.5"/>',
 'physio.html':'<path d="M8 3v4M16 3v4M8 7a4 4 0 0 0 8 0M12 11v4a4 4 0 0 0 8 0v-1"/><circle cx="20" cy="8" r="2"/>',
 'employer.html':'<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-5h6v5"/>',
 'partner.html':'<path d="M4 8h16l-1 12H5Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
 'data.html':'<path d="M4 6a8 3 0 0 0 16 0a8 3 0 0 0-16 0M4 6v12a8 3 0 0 0 16 0V6M4 12a8 3 0 0 0 16 0"/>'
};
function renderBottomNav(page){
  let n=document.getElementById('bnav');
  if(!n){n=document.createElement('nav');n.id='bnav';document.body.appendChild(n)}
  const u=AUTH.current();
  const allowed=u?ENTITIES.filter(([h])=>h===ROLE_HOME[u.role]||h==='data.html'):ENTITIES;
  n.innerHTML=allowed.map(([h,l])=>
    `<a href="${h}" ${h===page?'aria-current="page"':''}>
      <span class="bi"><svg viewBox="0 0 24 24">${NAVICON[h]||''}</svg></span>${l}</a>`).join('');
}
function profileMenu(){
  const u=AUTH.current();
  if(!u)return '';
  const integ=window.D.DB?.integration;
  const st=integ?integ.status:null;
  return `<div class="menu" id="avmenu" role="menu">
    <div class="who"><b>${esc(u.name)}</b><span>${esc(u.email)}</span>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <span class="chip glass">${esc(ROLE_LABEL_CS[u.role]||u.role)}</span>
        ${u.provider==='google'?'<span class="chip info">Google</span>':''}
        ${u.role==='runner'&&integ?`<span class="chip ${st==='connected'?'ok':st==='demo'?'glass':'watch'}">Garmin: ${
          st==='connected'?'připojeno':st==='demo'?'demo data':'nepřipojeno'}</span>`:''}
      </div></div>
    <button data-act="settings" role="menuitem">Nastavení a soukromí</button>
    ${u.role==='runner'?'<a href="data.html#tab=connect" role="menuitem">Připojit Garmin</a>':''}
    <div class="sep"></div>
    <button data-act="signout" class="danger" role="menuitem">Odhlásit se</button>
  </div>`;
}
function settingsSheet(){
  const u=AUTH.current();
  const rows=[
    ['share_with_physio','Sdílet data s fyzioterapeutem','Bez tohohle vidí fyzio jen to, co mu napíšete ve zprávách.'],
    ['share_bodymap','Sdílet označená místa bolesti','Silueta s body a poznámkami jde do karty pacienta.'],
    ['employer_aggregate','Být v agregátu zaměstnavatele','Firma vidí jen souhrnná čísla, nikdy jméno ani diagnózu.'],
    ['notify_drift','Upozornit na drift mechaniky','Když se technika hne proti vlastní normě dřív, než to bolí.'],
    ['notify_checkin','Připomenout hodnocení po běhu','Jednou denně, jen pokud nějaký běh čeká.']
  ];
  openSheet(`<h2>Nastavení a soukromí</h2>
    <p class="sub">Účet ${esc(u.email)}${u.provider==='google'?' · přihlášen přes Google':''}</p>
    <div style="margin-top:16px">${rows.map(([k,t,d])=>`
      <div class="fld"><div style="flex:1;padding-right:14px"><b style="font-weight:600">${t}</b>
        <div class="sub" style="margin-top:2px">${d}</div></div>
        <button class="btn ${SETTINGS[k]?'':'ghost'} sm" data-act="toggleset" data-k="${k}">${
          SETTINGS[k]?'zapnuto':'vypnuto'}</button></div>`).join('')}</div>
    <div class="divide"></div>
    <div class="lbl">Data</div>
    <div class="btnrow" style="margin-top:10px">
      ${u.role==='runner'?'<a class="btn ghost sm" href="data.html#tab=connect">Správa připojení Garmin</a>':''}
      <button class="btn ghost sm" data-act="exportme">Stáhnout moje data</button></div>
    <div class="sub">Export obsahuje aktivity, denní metriky, hodnocení i označená místa bolesti ve strojově čitelném JSON.</div>
    <button class="btn ghost" style="margin-top:20px;width:100%" data-act="close">Zavřít</button>`);
}
function renderChrome(cfg){
  const {entity,tabset,badges={},selector}=cfg;
  const page=location.pathname.split('/').pop()||'runner.html';
  const u=AUTH.current();
  $('#ebar').innerHTML=`<div class="ebarin">
    <a class="logo" href="index.html">
      <svg width="24" height="24" viewBox="0 0 26 26" fill="none" aria-hidden="true">
        <rect width="26" height="26" rx="8" fill="#fff"/>
        <path d="M6 17.5C8.5 17.5 9.5 8.5 12 8.5C14.5 8.5 15.5 17.5 20 13" stroke="#0A2540" stroke-width="2.2" stroke-linecap="round" fill="none"/>
      </svg><span>Došlap</span></a>
    <nav class="elinks">${(u?ENTITIES.filter(([h])=>h===ROLE_HOME[u.role]||h==='data.html'):ENTITIES).map(([h,l])=>
      `<a class="elink" href="${h}" ${h===page?'aria-current="page"':''}>${l}</a>`).join('')}</nav>
    <div class="right">${selector?selector.html:''}
      <div class="avwrap">
        <div class="avatar" id="avbtn" tabindex="0" role="button" aria-haspopup="true"
          aria-label="Profil a nastavení">${esc(cfg.avatar||initials(u?.name)||'—')}</div>
        ${profileMenu()}
      </div></div></div>`;
  renderBottomNav(page);
  const tabs=TABS[tabset||entity]||[];
  const cur=H.get('tab',tabs[0]?.[0]);
  $('#tbar').innerHTML=`<div class="tbarin">${tabs.map(([k,l])=>{
    const b=badges[k];
    return `<button class="tab" data-tab="${k}" aria-current="${k===cur}">${l}${
      b?`<span class="badge ${b.tone||''}">${b.n}</span>`:''}</button>`}).join('')}</div>`;
  return cur;
}

/* ---------- 6 · boot & globální eventy ---------- */
window.DB={clinics:[],physios:[],employers:[],partners:[],runners:[],integrations:[],
  activities:[],activity_feedback:[],daily_metrics:[],checkins:[],assessments:[],
  triage:[],bookings:[],programs:[],exercises:[],program_revisions:[],messages:[],referrals:[]};

function bindGlobal(rerender){
  document.addEventListener('click',async e=>{
    const t=e.target.closest('[data-tab]');
    if(t){H.set({tab:t.dataset.tab});return}
    const b=e.target.closest('[data-act]');if(!b)return;
    const a=b.dataset.act;
    if(a==='close'){closeSheet();return}
    if(a==='sig'){metricSheet(b.dataset.id,b.dataset.runner);return}
    if(a==='quaddoc'){quadSheet();return}
    if(a==='confdoc'){confSheet();return}
    if(a==='settings'){document.getElementById('avmenu')?.classList.remove('on');settingsSheet();return}
    if(a==='toggleset'){
      const k=b.dataset.k;SETTINGS[k]=!SETTINGS[k];settingsSheet();
      try{await api.patchSettings({[k]:SETTINGS[k]})}catch(err){toast('Nastavení se neuložilo','Chyba')}
      return}
    if(a==='signout'){await AUTH.signOut();location.href='auth.html';return}
    if(a==='exportme'){
      const u=AUTH.current();
      const pack=u.role==='runner'?{runner:window.DB.runners[0],activities:window.DB.activities,
        daily_metrics:window.DB.daily_metrics,activity_feedback:window.DB.activity_feedback,
        assessment:window.DB.assessments[0]}:{account:u};
      const bl=new Blob([JSON.stringify(pack,null,1)],{type:'application/json'});
      const el=document.createElement('a');el.href=URL.createObjectURL(bl);
      el.download='dosslap-moje-data.json';el.click();URL.revokeObjectURL(el.href);
      toast('dosslap-moje-data.json','Staženo');return}
  });
  document.addEventListener('click',e=>{
    const m=document.getElementById('avmenu');if(!m)return;
    if(e.target.closest('#avbtn')){m.classList.toggle('on');return}
    if(!e.target.closest('#avmenu'))m.classList.remove('on');
  });
  document.getElementById('avbtn')?.addEventListener('keydown',e=>{
    if(e.key==='Enter'||e.key===' '){e.preventDefault();document.getElementById('avmenu')?.classList.toggle('on')}
  });
  $('#scrim')?.addEventListener('click',closeSheet);
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeSheet()});
  window.addEventListener('hashchange',rerender);
  const mo=new MutationObserver(()=>bindSwipes());
  const v=document.getElementById('view');
  if(v)mo.observe(v,{childList:true,subtree:false});
  document.addEventListener('input',e=>{
    if(e.target.type==='range'){const o=e.target.closest('.rrow')?.querySelector('.rval');
      if(o)o.textContent=e.target.dataset.label?(({1:'špatný',2:'slabší',3:'normální',4:'dobrý',5:'výborný'})[e.target.value]||e.target.value):e.target.value}
  });
}

/* MDR pozicování — Došlap je nástroj pro monitoring a podporu rozhodování,
   ne zdravotnický prostředek. Persistentní disclaimer se sám připojí na
   každou stránku, která načte core.js, aby žádné rozhraní neslibovalo
   „predikci zranění" bez tohoto orámování. */
const MDR_DISCLAIMER='Došlap je nástroj pro monitoring tréninkové zátěže a běžecké mechaniky a pro podporu rozhodování odborníka. Není zdravotnický prostředek, nestanovuje diagnózu ani neurčuje léčbu a nenahrazuje vyšetření fyzioterapeutem nebo lékařem.';
function mountDisclaimer(){
  if(document.getElementById('mdrbar'))return;
  const f=document.createElement('footer');
  f.id='mdrbar';f.className='mdrbar';f.textContent=MDR_DISCLAIMER;
  document.body.appendChild(f);
}
if(document.readyState!=='loading')mountDisclaimer();
else document.addEventListener('DOMContentLoaded',mountDisclaimer);

/* export */
window.D={AUTH,SETTINGS,loadSettings,guard,ROLE_HOME,ROLE_LABEL_CS,swipeCard,bindSwipes,reveal,MDR_DISCLAIMER,
  $,$$,esc,uid,r1,r2,clamp,mean,sd,DAY,today,iso,dayAgo,daysBetween,fmtD,fmtDT,czk,sgn,
  initials,paceStr,H,GARMIN_MAP,parseGarminCsv,AI_INTENTS,SIG_DOC,GRADE_NOTE,QUAD,TIER,PHASE,
  FEEL_LABEL,api,ApiError,API_LOG,toast,openSheet,closeSheet,errCard,skeleton,sparkline,barchart,gradientChart,recoveryGauge,quadCard,
  signalRows,confCard,metricSheet,quadSheet,confSheet,renderChrome,bindGlobal,ENTITIES,TABS,GCOL,GBG,
  CURRENT_ASSESSMENT:null,get DB(){return window.DB},set DB(v){window.DB=v}};
})();
