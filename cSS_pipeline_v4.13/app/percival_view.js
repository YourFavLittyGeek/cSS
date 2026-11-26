// percival_view.js - v5.25 PERCIVAL & Training Center
// Standard View (clinical language) & Advanced Research View (technical algorithms)
const PV={tab:"system",study:"",q:"",viewMode:localStorage.getItem("pv_view_mode")||"standard"};
const PC={percival:"var(--lv-1)",dev:"var(--lv-2)",math:"var(--lv-math)"};
// 2026-11-25 architecture: ALBUS (detects) -> NOX (measures) + LUMOS (sees the image) -> PERCIVAL (the only combiner). No Unified, no Fusion.
const CN_STD={math:"ALBUS · Mathematical Detection",char:"NOX · Quantitative measurements",image:"LUMOS · Visual Intelligence"};
const CN_ADV={math:"ALBUS: score_v4 (Platt-recalibrated)",char:"NOX: 30 measurements (logistic / trees / forest)",image:"LUMOS: image model on MRI patches"};
const CN=new Proxy({},{get:(t,p)=>(PV.viewMode==="standard"?CN_STD[p]:CN_ADV[p])||p});

const MN_STD={
  math_only:"Quantitative Detection Alone",
  equal_mean:"Balanced Multi-source Average",
  stack_logit:"Calibrated Model Adaptation",
  stack_reg:"Model Adaptation with Disagreement Analysis",
  boosted:"Adaptive Gradient Decision Ensemble"
};
const MN_ADV={
  math_only:"ALBUS alone (recalibrated)",
  equal_mean:"Equal-weight arithmetic mean",
  stack_logit:"Logistic regression stacking",
  stack_reg:"Regularised stacking + disagreement interaction",
  boosted:"Gradient-boosted decision stumps"
};
const MN=new Proxy({},{get:(t,p)=>(PV.viewMode==="standard"?MN_STD[p]:MN_ADV[p])||p});
const g3=v=>v==null?"—":(+v).toFixed(3),pct=v=>v==null?"—":`${Math.round(v)}`;
function pvCurve(H){if(!H.length)return '<p class="note">The learning curve appears after the first training cycle.</p>';
  const W=760,Hh=270,L=46,R=170,T=14,Bm=40,pw=W-L-R,ph=Hh-T-Bm,n=H.length,X=i=>L+(n===1?pw/2:pw*i/(n-1));
  const vals=H.flatMap(h=>[h.test_auc,h.test_math_auc,(h.dev||{})[h.chosen],...(h.test_ci||[])]).filter(v=>v!=null),lo=Math.max(0,Math.floor((Math.min(0.5,...vals)-0.02)*10)/10),Y=v=>T+ph*(1-(v-lo)/(1-lo));
  const grid=[];for(let v=lo;v<=1.0001;v+=0.1)grid.push(`<line x1="${L}" x2="${L+pw}" y1="${Y(v)}" y2="${Y(v)}" class="lv-grid"/><text x="${L-6}" y="${Y(v)+4}" class="lv-ax" text-anchor="end">${v.toFixed(1)}</text>`);
  const ser=[["percival",h=>h.test_auc,"PERCIVAL score · locked test"],["dev",h=>(h.dev||{})[h.chosen],"chosen model · development CV"],["math",h=>h.test_math_auc,"ALBUS alone · locked test"]];
  const band=n>1&&H.every(h=>h.test_ci)?`<path class="lv-band" d="M${H.map((h,i)=>`${X(i)},${Y(h.test_ci[1])}`).join("L")}L${H.slice().reverse().map((h,i)=>`${X(n-1-i)},${Y(h.test_ci[0])}`).join("L")}Z"/>`:"";
  const line=([k,f,nm])=>{const pts=H.map((h,i)=>f(h)!=null?[X(i),Y(f(h)),f(h)]:null).filter(Boolean);if(!pts.length)return"";const l=pts[pts.length-1];
    return `<path d="M${pts.map(p=>p[0]+","+p[1]).join("L")}" class="lv-line ${k==="math"?"lv-dash":""}" style="stroke:${PC[k]}"/>${pts.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="4" class="lv-dot" style="fill:${PC[k]}"/>`).join("")}<text x="${l[0]+8}" y="${l[1]+4}" class="lv-lab">${nm.split(" · ")[0]} ${g3(l[2])}</text>`};
  return `<div class="lv-legend">${ser.map(([k,,nm])=>`<span><i style="background:${PC[k]}" class="${k==="math"?"dash":""}"></i>${nm}</span>`).join("")}<span><i class="band"></i>95 % CI (locked test)</span></div>
   <div style="position:relative"><svg viewBox="0 0 ${W} ${Hh}" class="lv-svg" role="img" aria-label="AUC per model version">${grid.join("")}${band}${ser.map(line).join("")}
   ${H.map((h,i)=>`<text x="${X(i)}" y="${Hh-22}" class="lv-ax" text-anchor="middle">${esc(h.version)}</text><text x="${X(i)}" y="${Hh-9}" class="lv-ax" text-anchor="middle">${h.studies} st.</text>`).join("")}
   ${H.map((h,i)=>`<rect x="${X(i)-12}" y="${T}" width="24" height="${ph}" class="lv-hit" data-pvi="${i}"/>`).join("")}</svg><div class="lv-tip hide" id="pvtip"></div></div>`}
function pvTip(H){const tip=$("#pvtip");if(!tip)return;document.querySelectorAll("[data-pvi]").forEach(r=>{r.onmouseenter=()=>{const h=H[+r.dataset.pvi];
  tip.innerHTML=`<b>${esc(h.version)}</b> · ${esc((h.at||"").replace("T"," "))}<br>${h.studies} studies · ${h.candidates} candidates<br>chosen: ${esc(MN[h.chosen]||h.chosen)}<br>locked test AUC <b>${g3(h.test_auc)}</b>${h.test_ci?` [${g3(h.test_ci[0])}–${g3(h.test_ci[1])}]`:""} · ALBUS ${g3(h.test_math_auc)}<br>${h.promoted?"promoted":h.passed?"passed":"not promoted"}`;
  tip.classList.remove("hide");const b=r.getBoundingClientRect(),p=r.closest("div").getBoundingClientRect();tip.style.left=Math.min(b.left-p.left+16,p.width-230)+"px";tip.style.top="8px"};r.onmouseleave=()=>tip.classList.add("hide")})}
function pvMetricsRow(name,m,sw){m=m||{};return `<tr><td>${sw?`<i class="lv-sw" style="background:${sw}"></i>`:""}${name}</td><td class="mono">${g3(m.auc)}</td><td class="mono">${m.auc_ci?`${g3(m.auc_ci[0])}–${g3(m.auc_ci[1])}`:"—"}</td><td class="mono">${g3(m.pr_auc)}</td><td class="mono">${g3(m.brier)}</td><td class="mono">${g3(m.calib_slope)}</td><td>${m.n??"—"}</td></tr>`}
// v5.25 training progress: one card for the PERCIVAL header and the Training Center - stages done / current / left, elapsed and
// remaining time, stall warning and the last log lines. The button reads "Training…" (greyed, locked) while a cycle is active.
const PV_ACTIVE=j=>!!j&&(j.active||j.state==="preparing"||j.state==="running");
function pvDur(x){if(x==null||!isFinite(x))return "—";x=Math.max(0,Math.round(x));const h=Math.floor(x/3600),m=Math.floor(x%3600/60),sec=x%60;return h?`${h} h ${m} min`:m?`${m} min ${sec} s`:`${sec} s`}
function pvTrainBtn(j,id,idle){const on=PV_ACTIVE(j);return `<button class="b pri" id="${id}" data-pv="train-btn" ${on?'disabled aria-disabled="true" title="a training cycle is running - this unlocks when it finishes"':""}>${on?"Training…":idle}</button>`}
function pvJobCard(j,full){j=j||{};const on=PV_ACTIVE(j),st=j.stages||[];if(!on&&!full&&!["finished","failed","cancelled","insufficient_data","interrupted"].includes(j.state))return "";
  const pc=Math.round(100*(j.progress||0)),E=j.eta||{},done=st.filter(x=>x.status==="done"||x.status==="skipped").length,cur=st.find(x=>x.status==="current");
  const rem=on?(E.eta_s!=null?`${pvDur(E.eta_s)}${E.eta_range_s&&E.eta_range_s[0]!=null&&E.eta_range_s[1]!=null?` (range ${pvDur(E.eta_range_s[0])} – ${pvDur(E.eta_range_s[1])})`:""}${E.reliable?"":" · early estimate"}`:"estimating…"):"—";
  const icon=x=>x.status==="done"?'<span class="ok">✓</span>':x.status==="current"?'<span class="pulse">●</span>':x.status==="skipped"?'<span class="note">–</span>':x.status==="stopped"?'<span class="bad">✗</span>':'<span class="note">○</span>';
  const head=on?`<b>${esc(j.state_label||"Training")}</b> · stage ${Math.min(done+1,st.length||7)} of ${st.length||7}${cur?`: ${esc(cur.label)}`:""}`:`<b>${esc(j.state_label||j.state||"Idle")}</b>`;
  return `<div class="card" data-pv="job-card" style="margin:10px 0">
   <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><span>${head}</span><span class="mono">${pc} %</span></div>
   <div style="background:var(--border);height:10px;border-radius:5px;overflow:hidden;margin:6px 0"><div style="background:var(--lv-1);height:100%;width:${pc}%;transition:width .3s"></div></div>
   <div class="row" style="gap:18px;flex-wrap:wrap"><span class="note">Elapsed <b>${pvDur(j.elapsed_s)}</b></span><span class="note">Remaining <b>${rem}</b></span>
    <span class="note">Stages left <b>${on?j.stages_left??"—":0}</b> of ${st.length||7}</span>${on&&j.heartbeat_age_s!=null?`<span class="note">last activity ${pvDur(j.heartbeat_age_s)} ago</span>`:""}<span class="sp"></span>${on&&!j.cancel?`<button class="b sm danger" data-pv-cancel="1" title="stops at the next step; no model is registered">Cancel cycle</button>`:on&&j.cancel?'<span class="note">cancelling at the next step…</span>':""}</div>
   ${j.stall?`<p class="warn" style="margin:6px 0">${esc(j.stall.reason)}</p>`:""}${j.state==="failed"||j.state==="insufficient_data"?`<p class="${j.state==="failed"?"bad":"warn"}" style="margin:6px 0">${esc(j.error||"")}</p>`:""}
   <ol style="margin:8px 0 4px;padding-left:20px">${st.map(x=>`<li style="margin:2px 0;${x.status==="current"?"font-weight:600":x.status==="left"?"opacity:.6":""}">${icon(x)} ${esc(x.label)}${x.duration_s!=null?` <span class="note">· ${pvDur(x.duration_s)}</span>`:""}${x.status==="skipped"?' <span class="note">· not run</span>':""}</li>`).join("")}</ol>
   ${(j.log||[]).length?`<details data-pv-logd="1" ${(typeof PV!=="undefined"&&PV.logOpen!=null?PV.logOpen:on&&full)?"open":""}><summary class="note" style="cursor:pointer">What is happening now (last ${Math.min(8,j.log.length)} steps)</summary><pre class="mono" style="white-space:pre-wrap;font-size:11.5px;margin:4px 0">${j.log.slice(-8).map(esc).join("\n")}</pre></details>`:""}
   <p class="note" style="margin:4px 0 0">The remaining time is estimated from the progress so far; image training (LUMOS) is the longest stage. Keep the app open and the drive connected.</p></div>`}
// v5.25 (2026-11-26): while a cycle runs only the progress card(s) and the training button are updated in place (light
// /api/percival/job poll every 3 s) - the page is no longer rebuilt (it flashed, jumped to the top and closed what was open).
// One full refresh when the cycle ends, to show the new model.
function pvBindJob(v){
  v.querySelectorAll("[data-pv-cancel]").forEach(b=>b.onclick=async()=>{if(!confirm("Cancel the running training cycle? It stops at its next step and no model is registered."))return;b.disabled=true;const r=await api("/api/percival/job",{action:"cancel"});toast(r.ok?"cancelling - stops at the next step":esc(r.error),!r.ok);pvJobPoll(v)});
  v.querySelectorAll("[data-pv-logd]").forEach(d=>d.ontoggle=()=>{PV.logOpen=d.open})}
async function pvJobPoll(v,g){g=g??PV.jg;clearTimeout(PV.jt);if(V!=="intel"||g!==PV.jg)return;   // g: one poll chain only
  let j;try{j=await api("/api/percival/job")}catch(e){if(g===PV.jg)PV.jt=setTimeout(()=>pvJobPoll(v,g),5000);return}
  if(V!=="intel"||g!==PV.jg)return;
  if(!PV_ACTIVE(j)){PV.logOpen=null;return intelView(v)}                 // finished / failed / cancelled: one full refresh
  v.querySelectorAll("[data-pv-jobslot]").forEach(sl=>{const full=sl.dataset.pvJobslot==="1";if(!full&&PV.tab==="center")return;
    const y=window.scrollY;sl.innerHTML=pvJobCard(j,full);window.scrollTo(0,y)});
  ["pv-train","pvc-start-train"].forEach(id=>{const b=document.getElementById(id);if(b){b.disabled=true;b.textContent="Training…"}});
  pvBindJob(v);PV.jt=setTimeout(()=>pvJobPoll(v,g),3000)}
const PVMH='<tr><th></th><th>AUC</th><th>95 % CI</th><th>PR-AUC</th><th>Brier</th><th>calibration slope</th><th>n</th></tr>';
async function intelView(v){{const hq=location.hash.match(/^#intel\?tab=(\w+)/);if(hq&&PV._hq!==hq[1]){PV._hq=hq[1];PV.tab=hq[1]}}
  PV.tab=({training:"center",registry:"models"})[PV.tab]||PV.tab;   // v5.24 names (old deep links still work)   // v5.23 deep link #intel?tab=evidence
  const s=await api("/api/percival/state");if(V!=="intel")return;
  if(s.store&&!s.store.ok){v.innerHTML=`<div class="banner w" data-pv="store-error"><b>Percival data could not be opened</b><span>${esc(s.store.error)}</span></div><p class="note">Nothing was changed. Backups of earlier states are in the project folder under backups/percival/. Data integrity details: Settings › About, or reopen the previous Percival version.</p>`;return}const M=s.active,Lt=s.latest,H=s.history||[],job=s.job||{},d=(M||Lt||{}).data;
  const status=!s.authorized?'<span class="pill bad">local learning switched off</span>':!M?(Lt?'<span class="pill warn">no model active yet - make one active in Model Center</span>':'<span class="pill">no model yet</span>'):M.ready?'<span class="pill ok">PERCIVAL score in use</span>':`<span class="pill warn">learning · minimum ${s.minimum.studies} studies / ${s.minimum.candidates} candidates</span>`;
  v.innerHTML=`<div class="banner ${s.authorized?"":"w"}" data-pv="banner"><b>PERCIVAL</b><span class="mut">${PV.viewMode==="standard"?"AI-Assisted Cerebral Superficial Siderosis detection and neuroimaging intelligence. Learns locally on this Mac from expert radiologist reviews.":"Multimodal evidence integration: ALBUS quantitative discovery, LUMOS 3D visual intelligence, NOX morphological analysis, and PERCIVAL Core meta-learning."}</span></div>
   <div class="row" style="flex-wrap:wrap;gap:10px;margin:10px 0;align-items:center">${status}
    <div style="display:inline-flex;gap:4px;background:var(--panel2);padding:2px;border-radius:6px">
      <button class="b sm ${PV.viewMode==='standard'?'pri':''}" id="pv-mode-std" title="Clinical research terminology">Standard View</button>
      <button class="b sm ${PV.viewMode==='advanced'?'pri':''}" id="pv-mode-adv" title="In-depth algorithmic formulas and metrics">Advanced Research View</button>
    </div>
    ${s.authorized?`${pvTrainBtn(job,"pv-train","Start a training cycle")}<span class="note">next automatic cycle after ${Math.max(0,s.cycle_n-s.since_last)} more finished studies</span>`
      :'<button class="b pri" id="pv-on" data-pv="switch-on">Switch on local learning</button><span class="note">lets the app learn from this project\'s MRI and expert reviews - on this Mac only</span>'}
    <span class="sp"></span>${job.state==="failed"?`<span class="bad">last cycle failed: ${esc(job.error)}</span>`:job.state==="insufficient_data"?`<span class="warn">training paused: expert review needed</span>`:""}</div>
   <div data-pv-jobslot="0">${PV.tab==="center"?"":pvJobCard(job,false)}</div>
   <div class="tiles" data-pv="tiles">
    <div class="tile"><div class="n">${d?d.studies:0}</div><div class="t">studies learned</div></div>
    <div class="tile"><div class="n">${d?d.dev_candidates+d.test_candidates:0}</div><div class="t">candidates${d?` · ${d.css} cSS / ${d.not_css} not`:""}</div></div>
    <div class="tile"><div class="n">${g3((((M||Lt||{}).test||{}).percival||{}).auc)}</div><div class="t">PERCIVAL AUC · locked test${d?` (${d.test_patients} patients)`:""}</div></div>
    <div class="tile"><div class="n">${g3((((M||Lt||{}).test||{}).math||{}).auc)}</div><div class="t">ALBUS alone · same test</div></div>
    <div class="tile"><div class="n">${M?esc(M.version):"—"}</div><div class="t">active model${M?` · ${esc(MN[M.discovery.chosen]||M.discovery.chosen)}`:""}</div></div></div>
   <div class="subtabs" data-pv="tabs">${[["system","System","PERCIVAL · the integrated system: every component and its state"],["overview","Overview","learning curve and the locked-test evaluation"],["center",`Training Center (${s.n_selected})`,"eligible expert labels, readiness, training"],["models",`Model Center (${s.versions.length})`,"trained versions, acceptance, explicit approval"],["albus","ALBUS","ALBUS · Mathematical Detection: detector versions, sensitivity, false positives"],["pensieve","PENSIEVE","PENSIEVE · AI Memory and History"],["shadow","SHADOW","SHADOW · Experimental Discovery Lab"],["vault","Data Vault","storage"],["integrity","Integrity","data integrity"],["|","Advanced:"],["components","Components","Components & agreement"],["evidence","Evidence","Evidence & reliability"],["meta","Meta-model","PERCIVAL Decision Engine: meta-model and calibration"],["explore","Candidates","Candidate explorer: every component per candidate"]].map(([k,l,t])=>k==="|"?`<span class="note" style="margin:0 4px 0 14px;white-space:nowrap;align-self:center">${l}</span>`:`<button data-pvt="${k}" class="${PV.tab===k?"on":""}" title="${esc(t||l)}">${l}</button>`).join("")}</div><div id="pvb"></div>`;
  const el=$("#pvb"),X=M||Lt;
  if(PV.tab==="overview"){el.innerHTML=pvFlow(s,X)+`<div class="card"><h3 style="margin:0 0 4px">Learning curve</h3><p class="note" style="margin-top:0">One point per training cycle. The locked test cohort (${Math.round(100*s.test_fraction)} % of patients, assigned permanently) is never used for training or selection.</p>${pvCurve(H)}</div>
    ${X?`<div class="card"><h3 style="margin:0 0 6px">Locked test cohort (${esc(X.version)})</h3><table data-pv="test">${PVMH}${pvMetricsRow("PERCIVAL score",(X.test||{}).percival,PC.percival)}${pvMetricsRow("ALBUS alone",(X.test||{}).math,PC.math)}</table>
      <p class="note">${(X.test||{}).at_red?`At the red threshold: sensitivity ${g3(X.test.at_red.sensitivity)}, specificity ${g3(X.test.at_red.specificity)} · at the green threshold: sensitivity ${g3(X.test.at_green.sensitivity)}, specificity ${g3(X.test.at_green.specificity)}.`:""}
      ${X.acceptance?` Acceptance: <b>${X.acceptance.passed?"passed":"not passed"}</b>${X.acceptance.reasons.length?" - "+X.acceptance.reasons.map(esc).join("; "):""}.`:""}</p></div>`:""}
    ${(s.log||[]).length?`<details class="card"><summary>Last training log</summary><pre class="note" style="white-space:pre-wrap">${esc(s.log.join("\n"))}</pre></details>`:""}`;pvTip(H)}
  if(PV.tab==="components"&&X){const A=X.agreement||[];const names=["math","char","image"];
    el.innerHTML=`<div class="card"><h3 style="margin:0 0 4px">Independent assessment sources</h3><p class="note" style="margin-top:0">Out-of-fold performance on the development cohort (each candidate scored by models that never saw its patient).</p><table data-pv="components">${PVMH}${names.map(c=>pvMetricsRow(CN[c],(X.component_metrics||{})[c])).join("")}</table>
      <p class="note">PERCIVAL is the only place where ALBUS, NOX and LUMOS are combined (no Fusion layer in between).</p></div>
     ${pvModules(X)}
     <div class="card"><h3 style="margin:0 0 4px">Agreement and dependence</h3><p class="note" style="margin-top:0">Spearman correlation of the sources' log-odds (dependence) and how often their calls (≥ 50 %) agree. Agreement is not correctness; disagreement is tested for its predictive value in the meta-model comparison.</p>
      <table data-pv="agreement"><tr><th></th>${names.map(c=>`<th>${CN[c]}</th>`).join("")}</tr>${names.map(a=>`<tr><td><b>${CN[a]}</b></td>${names.map(b=>{if(a===b)return'<td class="mut">—</td>';const x=A.find(q=>(q.a===a&&q.b===b)||(q.a===b&&q.b===a));return x?`<td class="mono" style="background:color-mix(in srgb,var(--lv-1) ${Math.round(40*Math.max(0,x.spearman))}%,transparent)">ρ ${x.spearman.toFixed(2)}<div class="note">calls agree ${Math.round(100*x.call_agreement)} %</div></td>`:'<td class="mut">—</td>'}).join("")}</tr>`).join("")}</table></div>`}
  if(PV.tab==="meta"&&X){const D=X.discovery,co=X.meta&&X.meta.type==="logistic"?X.meta:null,th=X.thresholds,te=X.test||{};
    el.innerHTML=`<div class="card"><h3 style="margin:0 0 4px">How PERCIVAL score is combined - discovered, not assigned</h3><p class="note" style="margin-top:0">Seven ways to combine the sources were compared by patient-grouped cross-validation on the development cohort. Rule: ${esc(D.rule)}.</p>
      <table data-pv="discovery"><tr><th>Candidate</th><th>AUC</th><th>PR-AUC</th><th>log loss</th><th>± SE</th><th>Brier</th><th>calibration slope</th><th></th></tr>
      ${Object.keys(MN).map(k=>{const m=D.results[k]||{};return `<tr class="${k===D.chosen?"pv-chosen":""}"><td>${esc(MN[k])}</td>${m.skipped?`<td colspan="6" class="note">skipped: ${esc(m.skipped)}</td>`:`<td class="mono">${g3(m.auc)}</td><td class="mono">${g3(m.pr_auc)}</td><td class="mono">${g3(m.logloss)}</td><td class="mono">${g3(m.logloss_se)}</td><td class="mono">${g3(m.brier)}</td><td class="mono">${g3(m.calib_slope)}</td>`}<td>${k===D.chosen?'<span class="pill ok">chosen</span>':k===D.best_logloss?'<span class="pill">lowest log loss</span>':""}</td></tr>`}).join("")}</table></div>
     <div class="card"><h3 style="margin:0 0 4px">The chosen model's actual calculation</h3>${co?`<p class="note" style="margin-top:0">log-odds = ${g3(co.beta[0])} (intercept) + Σ coefficient × standardised input; then calibrated: p = σ(${g3(X.calibration.a)} + ${g3(X.calibration.b)} × log-odds); PERCIVAL score = 100 × p.</p>
       <table class="lv-w"><tr><th>Input</th><th>Coefficient</th><th style="width:40%"></th></tr>${co.columns.map((c,i)=>{const b=co.beta[i+1],mx=Math.max(0.3,...co.beta.slice(1).map(Math.abs));return `<tr><td>${esc(c.replace("_missing"," missing").replace("disagreement_","disagreement · ").replace(/^(math|unified|char|image|fusion)$/,m=>CN[m]))}</td><td class="mono">${b>=0?"+":""}${b.toFixed(3)}</td><td><div class="lv-bar"><span class="${b>=0?"pos":"neg"}" style="width:${Math.round(50*Math.abs(b)/mx)}%;${b>=0?"left:50%":"right:50%"}"></span><i></i></div></td></tr>`}).join("")}</table>
       <p class="note">Coefficients describe this model's arithmetic on this project's data; they are associations, not causes.</p>`:`<p class="note">The chosen model is ${esc(MN[D.chosen])}${X.meta&&X.meta.type==="stumps"?` (${X.meta.trees.length} stumps)`:""}.</p>`}</div>
     <div class="card"><h3 style="margin:0 0 4px">Red / yellow / green thresholds</h3><p class="note" style="margin-top:0">${esc(th.strategy)}.</p>
      <table data-pv="thresholds"><tr><th></th><th>PERCIVAL score</th><th>development sensitivity</th><th>development specificity</th><th>locked-test sensitivity</th><th>locked-test specificity</th></tr>
       <tr><td><span class="pvb red"></span> red below</td><td class="mono">${pct(100*th.red_below)}</td><td class="mono">${g3(th.dev_at_red.sensitivity)}</td><td class="mono">${g3(th.dev_at_red.specificity)}</td><td class="mono">${g3((te.at_red||{}).sensitivity)}</td><td class="mono">${g3((te.at_red||{}).specificity)}</td></tr>
       <tr><td><span class="pvb green"></span> green from</td><td class="mono">${pct(100*th.green_from)}</td><td class="mono">${g3(th.dev_at_green.sensitivity)}</td><td class="mono">${g3(th.dev_at_green.specificity)}</td><td class="mono">${g3((te.at_green||{}).sensitivity)}</td><td class="mono">${g3((te.at_green||{}).specificity)}</td></tr></table></div>
     <div class="card"><h3 style="margin:0 0 4px">Robustness on the locked test cohort</h3><table data-pv="subgroups">${PVMH}${["complete_inputs","missing_inputs","low_disagreement","high_disagreement"].map(k=>pvMetricsRow(k.replace("_"," "),te["subgroup_"+k])).join("")}</table><p class="note">${te.insufficient||0} test candidates had insufficient evidence (no learned source).</p></div>`}
  if(PV.tab==="explore"){const st=(s.selection||[]);if(!PV.study&&st.length)PV.study=st[0].code;const sc=PV.study?await api(`/api/percival/score?code=${encodeURIComponent(PV.study)}`):null,hi=PV.study?await api(`/api/percival/history?code=${encodeURIComponent(PV.study)}`):{ledger:[]};
    el.innerHTML=`<div class="card"><div class="row"><span class="note">Study</span><select id="pv-st">${st.map(x=>`<option value="${esc(x.code)}" ${x.code===PV.study?"selected":""}>${esc(x.label)}</option>`).join("")}</select>${sc&&!sc.none?`<span class="note">model ${esc(sc.model)} · run ${esc(sc.run)}</span>`:""}${sc&&sc.hidden?`<span class="note" data-pv="hidden">hidden until the study's blind review is complete 🔒 (${esc(sc.reason||"")})</span>`:""}</div>
      ${sc&&!sc.none?`<table data-pv="explore"><tr><th>#</th><th>Percival</th><th>status</th><th>± (bootstrap)</th>${["math","char","image"].map(c=>`<th>${CN[c]}</th>`).join("")}<th>missing</th><th>disagreement</th><th>why uncertain</th></tr>
       ${sc.candidates.map(c=>`<tr><td class="mono">${c.cand_id}</td><td>${c.percival_score==null?'<span class="mut">—</span>':`<span class="pvb ${c.band}"></span> <b>${pct(c.percival_score)}</b>`}</td><td class="note">${esc(c.status)}</td><td class="mono">${c.uncertainty_sd}</td>${["math","char","image"].map(k=>`<td class="mono">${pct(c.components[k])}</td>`).join("")}<td class="note">${c.missing.map(m=>CN[m]).join(", ")||"—"}</td><td class="mono">${c.disagreement}</td><td class="note">${esc((c.reasons||[]).join("; "))||"—"}</td></tr>`).join("")}</table>
       <p class="note">Component columns: each source alone, in % (not the final score). AI predictions - never a human review.</p>`:'<p class="note">No Percival assessment for this study yet (no active model, or not processed).</p>'}
      ${(hi.ledger||[]).length>1?`<p class="note">Earlier assessments of this study are kept unchanged: ${hi.ledger.map(l=>`${esc(l.model)} (${esc(l.created)})`).join(" · ")}</p>`:""}</div>`;
    $("#pv-st")&&($("#pv-st").onchange=e=>{PV.study=e.target.value;intelView(v)})}
  if(PV.tab==="center"){await pvCenter(el,s,v);await pvReadiness(el)}
  if(PV.tab==="integrity"){await pvIntegrity(el,s,v)}
  if(PV.tab==="models")el.innerHTML=`<div class="card"><h3 style="margin:0 0 4px">Model Center</h3><p class="note" style="margin-top:0">Every model is kept with its data version, configuration, metrics and acceptance result. <b>No model becomes active by itself</b>: a new version is <i>experimental</i> (did not pass the acceptance criteria) or a <i>candidate</i> (passed, waiting for your approval). You make a version active; the one it replaces becomes <i>retired</i>; roll back returns to it. A <i>rejected</i> version cannot be made active until restored.</p>
    <div class="row"><button class="b" id="pv-rb">Roll back to the previous model</button></div>
    <table data-pv="registry"><tr><th>Version</th><th>Trained</th><th>Studies</th><th>Dataset</th><th>Chosen meta-model</th><th>Locked-test AUC</th><th>ALBUS</th><th>Acceptance</th><th>Status</th><th></th></tr>
    ${H.slice().reverse().map(h=>`<tr><td class="mono"><b>${esc(h.version)}</b></td><td class="note">${esc((h.at||"").replace("T"," "))} · ${esc(h.reason||"")}</td><td>${h.studies}</td><td class="mono">${h.dataset?`<a href="#" data-pvds="${esc(h.dataset)}">${esc(h.dataset)}</a>`:'<span class="mut" title="trained before v5.24">—</span>'}</td><td class="note">${esc(MN[h.chosen]||h.chosen)}</td><td class="mono">${g3(h.test_auc)}</td><td class="mono">${g3(h.test_math_auc)}</td><td>${h.passed?'<span class="ok">passed</span>':'<span class="warn">not passed</span>'}</td>
      <td>${pvStatus((s.status||{})[h.version])}</td><td>${M&&M.version===h.version?'':((s.status||{})[h.version]||{}).status==="rejected"?`<button class="b sm" data-pvst="${esc(h.version)}" data-st="restore">Restore</button>`:`<button class="b sm" data-pvp="${esc(h.version)}">Make active</button> <button class="b sm" data-pvsh="${esc(h.version)}" title="score every study with this version in shadow - reviewers never see it">Run in shadow</button> <button class="b sm" data-pvst="${esc(h.version)}" data-st="rejected">Reject</button>`}</td></tr>`).join("")||'<tr><td colspan="10" class="empty">No model yet.</td></tr>'}</table>
    ${(s.registry||[]).length?`<details data-pv="registry-detail"><summary>Registry details (identity, components, architecture, dataset, configuration, artifact)</summary><table><tr><th>Model</th><th>Status</th><th>Components (architecture chosen)</th><th>Dataset</th><th>Schemas</th><th>Run</th><th>Artifact</th></tr>
      ${s.registry.slice().reverse().map(r=>`<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.status)}</td><td class="note">${r.components.map(c=>`${esc(c.name)}: <b>${esc(MN[c.architecture]||c.architecture||"—")}</b>`).join(" · ")}</td><td class="mono">${esc(r.dataset||"—")}</td><td class="note">${esc(r.feature_schema||"—")} · ${esc(r.patch_spec||"")} · ${esc(r.eligibility_rules||"")}</td><td class="mono">${esc(r.run||"—")}</td><td class="mono note">${esc(r.artifact)}</td></tr>`).join("")}</table></details>`:""}
    ${(s.promotions||[]).length?`<details><summary>Promotion log</summary><table>${s.promotions.slice().reverse().map(p=>`<tr><td class="mono">${esc(p.version)}</td><td class="note">${esc(p.at)} · ${esc(p.by)} · ${esc(p.why)}${p.previous?` · previous ${esc(p.previous)}`:""}</td></tr>`).join("")}</table></details>`:""}</div>`;
  if(PV.tab==="models"){const SH=await api("/api/percival/shadow"),j=SH.job||{};el.insertAdjacentHTML("beforeend",`<div class="card" data-pv="shadow"><h3 style="margin:0 0 4px">Shadow mode</h3>
    <p class="note" style="margin-top:0">A version that was trained but not made active can be run <b>in shadow</b>: it scores every study, its results are kept apart (percival/shadow/) and are never shown to reviewers or used for any result. It is compared with the active model and with expert calls it never learned from (prospective). Only <b>Make active</b> deploys a version.${j.state==="running"?` <b>Running ${esc(j.version)} … ${Math.round(100*(j.progress||0))} %</b>`:j.state==="failed"?` <span class="bad">last shadow run failed: ${esc(j.error)}</span>`:""}</p>
    <table><tr><th>Version</th><th>Run</th><th>vs active</th><th>band agreement</th><th>mean |difference|</th><th>prospective calls</th><th>AUC shadow (unseen)</th><th>Head-to-head AUC shadow vs active</th></tr>
    ${(SH.runs||[]).map(r=>`<tr><td class="mono"><b>${esc(r.version)}</b></td><td class="note">${esc(r.at)} · ${r.studies} studies</td><td class="mono">${esc(r.active||"—")}</td><td class="mono">${r.band_agreement==null?"—":Math.round(100*r.band_agreement)+" %"}</td><td class="mono">${r.mean_abs_difference==null?"—":r.mean_abs_difference.toFixed(1)}</td><td class="mono">${r.prospective.n} (${r.prospective.css} cSS)</td><td class="mono">${g3((r.prospective.shadow||{}).auc)}</td><td class="mono" title="${r.prospective.n_fair??0} calls neither model learned from">${r.prospective.n_fair?`${g3((r.prospective.fair_shadow||{}).auc)} vs ${g3((r.prospective.active||{}).auc)} <span class="note">(n ${r.prospective.n_fair})</span>`:'<span class="mut">no calls unseen by both</span>'}</td></tr>`).join("")||'<tr><td colspan="8" class="empty">No shadow run yet.</td></tr>'}</table>
    <p class="note">AUC shadow: on expert calls this version never learned from. Head-to-head: only calls that <b>neither</b> model learned from (otherwise the active model would be judged on its own training data). Synthetic or small projects give unstable numbers; these are not clinical results.</p></div>`);
    clearTimeout(PV.sht);if(j.state==="running")PV.sht=setTimeout(()=>V==="intel"&&PV.tab==="models"&&intelView(v),5000)}
  if(PV.tab==="system"){await pvSystem(el)}
  if(PV.tab==="albus"){await pvAlbus(el)}
  if(PV.tab==="pensieve"){await pvPensieve(el)}
  if(PV.tab==="shadow"){await pvShadow(el,v)}
  if(PV.tab==="vault"){
    const ov=await api("/api/storage/overview");
    const stList=(await api("/api/storage/studies")).studies||[];
    if(typeof pvStates==="function")await pvStates();
    const adv=await api("/api/storage/advisor");
    const vt=await api("/api/percival/vault");
    const st=vt.stats||{};
    const cats=st.categories||{};
    const fmtGb=b=>(b/(1024**3)).toFixed(2)+" GB";
    const ssd=ov.local_ssd||{};
    const cap=adv.capacity||{};

    const statusBadge=s=>{
      if(s==="SYNCHRONIZED")return '<span class="pill ok">Synchronized</span>';
      if(s==="LOCAL_ONLY")return '<span class="pill">Mac SSD Only</span>';
      if(s==="STAGED")return '<span class="pill warn">Staged for Compute</span>';
      if(s==="ARCHIVED")return '<span class="pill ok">Archived in Vault</span>';
      if(s==="ARCHIVED_DRIVE_REQUIRED")return '<span class="pill bad">ARCHIVED — DRIVE REQUIRED</span>';
      return `<span class="pill">${esc(s)}</span>`;
    };

    el.innerHTML=`<div class="card" data-pv="vault">
      <div class="row" style="justify-content:space-between">
        <div>
          <h3 style="margin:0 0 4px">PERCIVAL Storage Dashboard & File Manager</h3>
          <p class="note" style="margin:0">Dual-storage topology: Fast local Mac SSD for active compute &amp; authoritative external Data Vault for long-term storage.</p>
        </div>
        <span class="pill ${st.connected?'ok':'bad'}">${st.connected?'Data Vault Connected':'EXTERNAL DATA VAULT DISCONNECTED (DEGRADED MODE)'}</span>
      </div>

      <div class="row" style="margin:12px 0 16px;gap:12px;flex-wrap:wrap">
        <div class="tile"><div class="n">${ssd.free_gb||0} GB</div><div class="t">Mac SSD free (${ssd.free_pct||0}%)</div></div>
        <div class="tile"><div class="n">${fmtGb(st.free_bytes||0)}</div><div class="t">Data Vault free</div></div>
        <div class="tile"><div class="n">${stList.length}</div><div class="t">total studies tracked</div></div>
        <div class="tile"><div class="n"><span class="pill ${cap.tier==='HEALTHY'?'ok':cap.tier==='WARNING'?'warn':'bad'}">${cap.tier||'OK'}</span></div><div class="t">storage advisor tier</div></div>
      </div>

      <div class="card" style="margin-bottom:14px">
        <h4 style="margin:0 0 6px">Active Storage Topology</h4>
        <div class="kv">
          <div>Local Workspace (SSD)</div><div class="mono">${esc(ssd.path||"")}</div>
          <div>External Data Vault</div><div class="mono">${esc(st.root_path||"No vault connected")}</div>
          <div>Volume UUID</div><div class="mono">${esc(vt.volume_uuid||"Verified Local")}</div>
          <div>Integrity Check</div><div>${esc(vt.integrity&&vt.integrity.ok?'PRAGMA OK':'CHECK')}</div>
        </div>
        ${st.warning?`<p class="bad" style="margin:6px 0 0">${esc(st.warning)}</p>`:""}
      </div>

      <h4 style="margin:16px 0 6px">File Manager — Studies Across Topology</h4>
      <table>
        <tr><th>Study Code</th><th>Lifecycle Status</th><th>Local Size</th><th>Actions</th></tr>
        ${stList.slice(0,30).map(s=>`<tr>
          <td class="mono"><b>${esc(s.study_code)}</b></td>
          <td>${statusBadge(s.status)}</td>
          <td class="mono">${s.local_size_mb||0} MB</td>
          <td>
            <button class="b" data-fm-tree="${esc(s.study_code)}">Files</button>
            ${typeof pvCell==="function"?pvCell(s.study_code):""}
          </td>
        </tr>`).join("")}
      </table>
      ${stList.length>30?`<p class="note">Showing 30 of ${stList.length} studies.</p>`:""}

      <h4 style="margin:20px 0 6px">Storage Intelligence &amp; Reclamation Recommendations</h4>
      ${(adv.recommendations||[]).length?`<table>
        <tr><th>Action</th><th>Target Area</th><th>Reclaimable</th><th>Run</th></tr>
        ${adv.recommendations.map(r=>`<tr>
          <td><b>${esc(r.action)}</b></td>
          <td>${esc(r.description)}</td>
          <td class="mono">${r.reclaimable_mb} MB</td>
          <td><button class="b pri" data-fm-prune="${esc(r.action)}" data-fm-days="${r.days_threshold}">Reclaim</button></td>
        </tr>`).join("")}
      </table>`:'<p class="note">No expired scratch, staging, or failed run artifacts. Storage is fully optimized.</p>'}

      <h4 style="margin:20px 0 6px">Vault Scientific Distribution</h4>
      <table><tr><th>Category</th><th>Artifacts</th><th>Size</th></tr>
      <tr><td><b>original_mri</b></td><td>Raw DICOM and NIfTI acquisitions</td><td class="mono">${fmtGb(cats.original_mri||0)}</td></tr>
      <tr><td><b>processed_mri</b></td><td>Resampled volumes &amp; masks</td><td class="mono">${fmtGb(cats.processed_mri||0)}</td></tr>
      <tr><td><b>PENSIEVE</b></td><td>Persistent memory database &amp; snapshots</td><td class="mono">${fmtGb(cats.PENSIEVE||0)}</td></tr>
      <tr><td><b>models</b></td><td>LUMOS image-network weights; CORE fixed-weight baseline</td><td class="mono">${fmtGb(cats.models||0)}</td></tr>
      <tr><td><b>backups</b></td><td>Independent recovery archives</td><td class="mono">${fmtGb(cats.backups||0)}</td></tr></table>

      <div class="row" style="gap:10px;margin-top:16px">
        <button class="b pri" id="vt-backup">Create Vault Backup</button>
        <button class="b" id="vt-eject">Safe Eject Storage</button>
        <button class="b" id="vt-health">Run Full System Health Check</button>
      </div>
    </div>`;

    el.querySelectorAll("[data-fm-tree]").forEach(b=>b.onclick=async()=>{
      const code=b.dataset.fmTree;
      const t=await api("/api/storage/tree?code="+encodeURIComponent(code));
      alert(`Study: ${code}\nLocal files (${t.local_files_count}):\n${t.local_files.map(f=>f.name+" ("+f.location+")").join("\n") || "None"}\n\nVault files (${t.vault_files_count}):\n${t.vault_files.map(f=>f.name+" ("+f.location+")").join("\n") || "None"}`);
    });
    if(typeof pvBind==="function")pvBind(el,()=>intelView(v));
    el.querySelectorAll("[data-fm-arch]").forEach(b=>b.onclick=async()=>{
      const code=b.dataset.fmArch;
      const r=await api("/api/storage/archive",{code});
      toast(r.files_archived?`Archived ${r.files_archived} files to Data Vault`:`Failed to archive: ${r.error||"unknown error"}`,!r.files_archived);
      intelView(v);
    });
    el.querySelectorAll("[data-fm-stg]").forEach(b=>b.onclick=async()=>{
      const code=b.dataset.fmStg;
      const r=await api("/api/storage/stage",{code});
      toast(r.files_staged?`Staged ${r.files_staged} files to local SSD`:r.error,!r.files_staged);
      intelView(v);
    });
    el.querySelectorAll("[data-fm-vrf]").forEach(b=>b.onclick=async()=>{
      const code=b.dataset.fmVrf;
      const r=await api("/api/storage/verify",{code});
      alert(`Study ${code} Checksum Verification:\nAll Match: ${r.all_match?'YES (Identical SHA-256)':'MISMATCH'}\nFiles compared: ${r.common_files_count}`);
    });
    el.querySelectorAll("[data-fm-cln]").forEach(b=>b.onclick=async()=>{
      const code=b.dataset.fmCln;
      const r=await api("/api/storage/clean",{code});
      toast(`Cleaned staging: reclaimed ${r.reclaimed_mb} MB`);
      intelView(v);
    });
    el.querySelectorAll("[data-fm-prune]").forEach(b=>b.onclick=async()=>{
      const act=b.dataset.fmPrune,days=b.dataset.fmDays;
      const r=await api("/api/storage/prune",{action:act,days:+days});
      toast(`Reclaimed ${r.reclaimed_mb} MB (${r.items_removed} items)`);
      intelView(v);
    });
    $("#vt-health")&&($("#vt-health").onclick=async()=>{
      const hc=await api("/api/health");
      alert(`PERCIVAL Startup Health Check:\nOverall Status: ${hc.status}\nPassed: ${hc.passed} / ${hc.total_checks}\nWarnings: ${hc.warnings}\nDegraded: ${hc.degraded}\nBlocked: ${hc.blocked}\nRepairs Applied: ${hc.repairs_applied.length}`);
    });
    $("#vt-backup")&&($("#vt-backup").onclick=async()=>{
      const dest=prompt("Enter destination directory for scientific backup:");
      if(!dest||!dest.trim())return;
      const r=await api("/api/percival/vault_backup",{destination:dest.trim()});
      toast(r.ok?r.message:esc(r.error),!r.ok);
      intelView(v);
    });
    $("#vt-eject")&&($("#vt-eject").onclick=async()=>{
      if(!confirm("Safely prepare external Data Vault for disconnection? Active jobs will be checkpointed."))return;
      const r=await api("/api/percival/vault_eject",{});
      toast(r.ok?r.message:esc(r.error),!r.ok);
      intelView(v);
    });
  }
  if(PV.tab==="evidence"&&X)el.innerHTML=pvEvidence(X,s);
  if((PV.tab==="components"||PV.tab==="meta"||PV.tab==="evidence")&&!X)el.innerHTML='<div class="card"><p class="note">No model yet - start a training cycle.</p></div>';
  v.querySelectorAll("[data-pvt]").forEach(b=>b.onclick=()=>{PV.tab=b.dataset.pvt;intelView(v)});
  v.querySelectorAll("[data-pvp]").forEach(b=>b.onclick=async()=>{const ver=b.dataset.pvp;if(!confirm(`Make ${ver} the active Percival model? Studies are re-assessed; earlier assessments stay in the ledger.`))return;let r=await api("/api/percival/promote",{version:ver});
    if(!r.ok&&r.needs_override){const why=prompt(`${r.error}\n\nType the reason to make it active anyway (recorded in the promotion log), or cancel:`);if(!why||!why.trim()){toast("not made active");return}r=await api("/api/percival/promote",{version:ver,override:true,why:why.trim()})}
    toast(r.ok?`${esc(r.version)} active`:esc(r.error),!r.ok);intelView(v)});
  v.querySelectorAll("[data-pvst]").forEach(b=>b.onclick=async()=>{const st=b.dataset.st;let why="";if(st!=="restore"){why=prompt(`Reason to mark ${b.dataset.pvst} as ${st}:`);if(!why||!why.trim())return}
    const r=await api("/api/percival/status",{version:b.dataset.pvst,status:st,why});toast(r.ok?`${esc(r.version)}: ${esc(r.status)}`:esc(r.error),!r.ok);intelView(v)});
  $("#pv-mode-std")&&($("#pv-mode-std").onclick=()=>{PV.viewMode="standard";localStorage.setItem("pv_view_mode","standard");intelView(v)});
  $("#pv-mode-adv")&&($("#pv-mode-adv").onclick=()=>{PV.viewMode="advanced";localStorage.setItem("pv_view_mode","advanced");intelView(v)});
  $("#pv-rb")&&($("#pv-rb").onclick=async()=>{const r=await api("/api/percival/rollback",{});toast(r.ok?`rolled back to ${esc(r.version)}`:esc(r.error),!r.ok);intelView(v)});
  $("#pv-on")&&($("#pv-on").onclick=async()=>{if(!confirm("Switch on local learning? Percival will read this project's MRI and expert reviews to learn - on this Mac only; nothing is uploaded and no external AI service is used."))return;await api("/api/percival/authorize",{on:true});await api("/api/percival/train",{});toast("switched on - the first training cycle started");intelView(v)});
  $("#pv-train")&&($("#pv-train").onclick=async()=>{await api("/api/percival/train",{});toast("training cycle started");intelView(v)});
  v.querySelectorAll("[data-pvsh]").forEach(b=>b.onclick=async()=>{const r=await api("/api/percival/shadow",{version:b.dataset.pvsh});toast(r.ok?`shadow run of ${esc(b.dataset.pvsh)} started`:esc(r.error),!r.ok);intelView(v)});
  v.querySelectorAll("[data-pvds]").forEach(a=>a.onclick=e=>{e.preventDefault();PV.tab="center";PV.ds=a.dataset.pvds;intelView(v)});
  pvBindJob(v);clearTimeout(PV.jt);const g=PV.jg=(PV.jg||0)+1;if(PV_ACTIVE(job))PV.jt=setTimeout(()=>pvJobPoll(v,g),3000)}   // while preparing AND training: in-place updates only

// 2026-11-25 one learning loop per module: each module checked on its own against its previous version
function pvModules(X){const Mo=(X||{}).modules;if(!Mo)return "";const v=r=>r.verdict==="improved"?'<span class="pill ok">improved</span>':r.verdict==="not improved"?'<span class="pill warn">not improved - previous version kept</span>':`<span class="pill">${esc(r.verdict||"")}</span>`;
  return `<div class="card" data-pv="modules"><h3 style="margin:0 0 4px">Learning loop of every module</h3><p class="note" style="margin-top:0">Each module is checked on its own (development patients, out-of-fold) against the same module in the previous model. NOX and LUMOS are adopted (Freeze) only when they improved; ALBUS changes only through a new detector version that may not lose any cSS; PERCIVAL becomes active only after the locked test and your approval.</p>
   <table><tr><th>Module</th><th>Model</th><th>AUC</th><th>log loss</th><th>previous</th><th>verdict</th><th>loop</th></tr>${["ALBUS","NOX","LUMOS","PERCIVAL"].filter(k=>Mo[k]).map(k=>{const r=Mo[k];return `<tr><td><b>${k}</b></td><td class="note">${esc(r.family||"")}</td><td class="mono">${g3(r.auc)}</td><td class="mono">${g3(r.logloss)}</td><td class="mono">${r.previous_model?`${esc(r.previous_model)} · ${g3(r.previous_logloss)}`:"—"}</td><td>${v(r)}</td><td class="note">${esc(r.loop||"")}${k==="LUMOS"&&r.missed_marks!=null?` <span class="pill">${r.missed_marks} missed-cSS mark${r.missed_marks===1?"":"s"} learned</span>`:""}</td></tr>`}).join("")}</table>${pvMarkLoop(X)}${pvSecondLook(X)}<div id="pv-amiss" data-pv="albus-misses"></div></div>`+(setTimeout(pvAlbusMiss,0),"")}
function pvMarkLoop(X){const ch=((((X||{}).intelligence||{}).families||{}).char||{}).missed_marks,pm=(X||{}).percival_marks,tm=((X||{}).test||{}).missed_lesions;if(!ch&&!pm)return "";
  const pc=r=>r&&r.n?`${r.recognised} of ${r.n} (${Math.round(100*r.recall)} %)`:"—";
  return `<div data-pv="mark-loop" style="margin-top:10px"><b>Expert-marked missed cSS</b>
   <p class="note" style="margin:4px 0 0">ALBUS re-detects every mark and measures the lesion; once you confirm ALBUS's outline in the reviewer, NOX learns from its measurements and PERCIVAL scores it without an ALBUS score (NOX + LUMOS only).</p>
   <p class="note" style="margin:4px 0 0"><b>NOX:</b> ${ch?`${ch.available} confirmed marks · ${esc(ch.decision||"")}${ch.origin_auc!=null?` · origin AUC ${ch.origin_auc.toFixed(2)} (≤ 0.75 needed)`:""} · recognises ${pc(ch.heldout_check)} held-out marks`:"—"}</p>
   <p class="note" style="margin:4px 0 0"><b>PERCIVAL:</b> recognises ${pc(pm&&pm.development)} development marks (out-of-fold) · locked test ${pc(tm)}${tm&&tm.note?" - "+esc(tm.note):""}</p></div>`}
async function pvAlbusMiss(){const el=document.getElementById("pv-amiss");if(!el||el.dataset.done)return;el.dataset.done="1";let R;try{R=await api("/api/percival/albus_misses")}catch(e){return}
  if(!R||!R.n_marks){el.innerHTML='<p class="note" style="margin-top:10px"><b>Where ALBUS loses cSS:</b> no expert-marked missed cSS yet.</p>';return}
  el.innerHTML=`<div style="margin-top:10px"><b>Where ALBUS loses cSS</b> <span class="note">${R.n_missed} of ${R.n_marks} marks were not shown by ALBUS</span>
   <table><tr><th>Lost at</th><th>Cause</th><th>Marks</th></tr>${R.table.map(t=>`<tr><td>${esc({excluded:"exclusion rule",gate:"generation gate",not_generated:"never generated"}[t.category]||t.category)}</td><td class="note">${esc(t.cause)}</td><td class="mono">${t.n}</td></tr>`).join("")||'<tr><td colspan="3" class="empty">none</td></tr>'}</table>
   <p class="note">${esc(R.note)}</p></div>`}
function pvSecondLook(X){const S=(X||{}).second_look;if(!S)return "";const L=(Mo=>Mo&&Mo.LUMOS)((X||{}).modules)||{},hc=L.missed_marks_check||S.heldout||{};
  return `<div data-pv="second-look" style="margin-top:10px"><b>LUMOS second look</b> ${S.ready?'<span class="pill ok">ready - suggestions shown in the reviewer when this model is active</span>':'<span class="pill">inactive</span>'}
   <p class="note" style="margin:4px 0 0">LUMOS looks at dark spots on the cortex that ALBUS did not show and suggests possible missed cSS; you accept (saved as a missed-cSS mark) or reject (LUMOS learns "not cSS", so false suggestions drop with training). It switches itself on when LUMOS learned from ${S.gate.min_marks} expert-marked missed cSS in ${S.gate.min_patients} patients and recognises ${Math.round(100*S.gate.min_recall)} % of the marks of patients it was not trained on.</p>
   <p class="note" style="margin:4px 0 0">Now: ${S.n_marks} marks · ${S.n_patients} patients · LUMOS recognises ${hc.n?`${hc.recognised} of ${hc.n} held-out marks (${Math.round(100*hc.recall)} %)`:"— (no held-out marks yet)"}${L.rejected_suggestions?` · ${L.rejected_suggestions} rejected suggestions learned`:""}.${S.reasons&&S.reasons.length?" Missing: "+S.reasons.map(esc).join("; ")+".":""}</p></div>`}
// ------------------------------------------------------------------ v5.23 Evidence & reliability (PERCIVAL analyses of the model)
const FAM={char:["NOX measurement model",{logistic:"Logistic regression (L2)",gbt:"Gradient-boosted trees (depth 2)",forest:"Random forest"}],
  image:["LUMOS image network",{pixel_logistic:"Pixel logistic (3×7×5 block means) - baseline",cnn:"Convolutional network (SmallCNN)",cnn_ensemble:"CNN seed ensemble"}]};
function pvCal(R,Rt){if(!R||!R.length)return '<p class="note">Not enough candidates for a calibration table.</p>';
  const W=420,Hh=300,L=44,Bm=36,T=10,Rr=10,pw=W-L-Rr,ph=Hh-T-Bm,X=v=>L+pw*v,Y=v=>T+ph*(1-v);
  const g=[0,.25,.5,.75,1].map(v=>`<line x1="${X(0)}" x2="${X(1)}" y1="${Y(v)}" y2="${Y(v)}" class="lv-grid"/><text x="${L-6}" y="${Y(v)+4}" class="lv-ax" text-anchor="end">${v}</text><text x="${X(v)}" y="${Hh-18}" class="lv-ax" text-anchor="middle">${100*v}</text>`).join("");
  const pts=(A,c)=>A.map(r=>`<line x1="${X(r.mean_score)}" x2="${X(r.mean_score)}" y1="${Y(r.ci[0]??r.observed)}" y2="${Y(r.ci[1]??r.observed)}" style="stroke:${c};stroke-width:1.5;opacity:.6"/><circle cx="${X(r.mean_score)}" cy="${Y(r.observed)}" r="${3+Math.min(5,Math.sqrt(r.n)/2)}" style="fill:${c}"><title>score ${Math.round(100*r.mean_score)} · observed ${Math.round(100*r.observed)} % cSS · n ${r.n}</title></circle>`).join("");
  return `<div class="lv-legend"><span><i style="background:${PC.dev}"></i>development (out-of-fold)</span>${Rt&&Rt.length?`<span><i style="background:${PC.percival}"></i>locked test</span>`:""}<span><i class="dash" style="background:var(--mut)"></i>perfect calibration</span></div>
   <svg viewBox="0 0 ${W} ${Hh}" class="lv-svg" style="max-width:440px" role="img" aria-label="calibration">${g}<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" class="lv-line lv-dash" style="stroke:var(--mut)"/>${pts(R,PC.dev)}${Rt?pts(Rt,PC.percival):""}
   <text x="${L+pw/2}" y="${Hh-3}" class="lv-ax" text-anchor="middle">PERCIVAL score</text><text x="12" y="${T+ph/2}" class="lv-ax" text-anchor="middle" transform="rotate(-90 12 ${T+ph/2})">observed cSS rate</text></svg>`}
function pvEvidence(X,s){const I=X.intelligence;if(!I)return '<div class="card"><p class="note">This model was trained before v5.23 and has no evidence analysis. Start a training cycle.</p></div>';
  const F=I.families||{},ab=I.ablation||{};
  const famCard=Object.keys(FAM).filter(k=>F[k]).map(k=>{const f=F[k],[t,nm]=FAM[k];return `<h4 style="margin:12px 0 4px">${t}</h4><table data-pv="family-${k}"><tr><th>Model</th><th>AUC</th><th>log loss</th><th>± SE</th><th>calibration slope</th><th>n</th></tr>
    ${Object.keys(nm).map(m=>{const r=(f.results||{})[m]||{};return `<tr class="${m===f.chosen?"pv-chosen":""}"><td>${esc(nm[m])}${m===f.chosen?' <span class="pill ok">chosen</span>':""}</td><td class="mono">${g3(r.auc)}</td><td class="mono">${g3(r.logloss)}</td><td class="mono">${g3(r.logloss_se)}</td><td class="mono">${g3(r.calib_slope)}</td><td class="mono">${r.n??"—"}</td></tr>`}).join("")}</table><p class="note">${esc(f.rule||"")}</p>`}).join("");
  const ov=(I.overlap||[]).filter(o=>o.shared.length).map(o=>`<tr><td><b>${CN[o.a]}</b> · <b>${CN[o.b]}</b></td><td class="mono">${o.jaccard}</td><td class="note">${o.shared.map(x=>esc(x.replace(/_/g," "))).join(", ")}</td></tr>`).join("");
  const abRows=Object.keys(ab.without||{}).map(c=>{const w=ab.without[c],a=(ab.alone||{})[c]||{};return `<tr><td><b>${CN[c]}</b></td><td class="mono">${g3(a.auc)}</td><td class="mono">${g3(w.auc)}</td><td class="mono">${w.delta_logloss>=0?"+":""}${w.delta_logloss.toFixed(3)}</td><td class="mono">${w.delta_ci[0].toFixed(3)} to ${w.delta_ci[1].toFixed(3)}</td><td>${w.verdict==="adds information"?'<span class="pill ok">adds information</span>':w.verdict==="uncertain"?'<span class="pill warn">uncertain</span>':'<span class="pill">redundant</span>'}</td></tr>`}).join("");
  const dis=(I.disagreement||[]).map(d=>{const P=d.patterns,cell=k=>{const x=P[k]||{};return `<td class="mono">${x.n||0}${x.n?` · ${Math.round(100*x.css_rate)} %`:""}</td>`};return `<tr><td><b>${CN[d.a]}</b> vs <b>${CN[d.b]}</b></td>${cell("both_high")}${cell("both_low")}${cell(d.a+"_only")}${cell(d.b+"_only")}<td class="mono">${d.n_disagree}</td><td class="note">${d.n_disagree?`${CN[d.a]} ${Math.round(100*d.a_right)} % · ${CN[d.b]} ${Math.round(100*d.b_right)} %`:"—"}</td></tr>`}).join("");
  return `<div class="card"><h3 style="margin:0 0 4px">Which model family each source uses - compared, not assumed</h3><p class="note" style="margin-top:0">Patient-grouped cross-validation on the development cohort; the simplest model within one standard error of the best is used (a more complex model must earn its place).</p>${famCard}</div>
   <div class="card"><h3 style="margin:0 0 4px">Shared inputs - the sources are not independent</h3><p class="note" style="margin-top:0">Measurements each source consumes (from the code). Sources that share measurements must not be counted as separate evidence; the meta-model learns their weights jointly.</p>
    <table data-pv="overlap"><tr><th>Pair</th><th>overlap (Jaccard)</th><th>shared measurements</th></tr>${ov||'<tr><td colspan="3" class="empty">none</td></tr>'}</table></div>
   <div class="card"><h3 style="margin:0 0 4px">Incremental value of each source</h3><p class="note" style="margin-top:0">${esc(ab.note||"")} A source with a high AUC on its own can still add nothing when the others already carry its information.</p>
    <table data-pv="ablation"><tr><th>Source</th><th>AUC alone</th><th>AUC of the others without it</th><th>Δ log loss when removed</th><th>95 % CI</th><th></th></tr>${abRows||'<tr><td colspan="6" class="empty">not available</td></tr>'}</table></div>
   <div class="card"><h3 style="margin:0 0 4px">Disagreement - learned from expert reviews</h3><p class="note" style="margin-top:0">For every pair of sources: how many expert-reviewed candidates fell in each pattern and how many of those were cSS (n · % cSS). In the reviewer, each candidate shows its own pattern and this historical rate.</p>
    <table data-pv="disagreement"><tr><th>Pair</th><th>both cSS</th><th>both not</th><th>first only</th><th>second only</th><th>disagree</th><th>right when they disagree</th></tr>${dis}</table></div>
   <div class="card"><h3 style="margin:0 0 4px">Calibration - does a score of 70 mean 70 % cSS?</h3><p class="note" style="margin-top:0">Mean PERCIVAL score vs the observed cSS rate per decile (with 95 % intervals). Only on this project's expert-reviewed candidates: it is a property of this model on these data, not a validated clinical probability.</p>
    <div data-pv="calibration">${pvCal(I.reliability,(X.test||{}).reliability)}</div></div>
   <div class="card"><h3 style="margin:0 0 4px">Expert-review snapshots</h3><p class="note" style="margin-top:0"><b>${s.n_review_snapshots||0}</b> final expert reviews are stored with the exact model outputs available when they were saved (labels never overwritten; whether the score was visible to the reviewer is recorded).</p></div>`}

// ------------------------------------------------------------------ v5.24 how the parts fit together (one pipeline, one score)
function pvFlow(s,X){const I=s.inputs||{},n=I.studies||0,F=((X||{}).intelligence||{}).families||{},on=s.authorized,
  ch=k=>{const f=F[k];return f&&f.chosen?(FAM[k][1][f.chosen]||f.chosen):null},
  st=(ok,txt)=>`<span class="${ok?"ok":"mut"}">${ok?"●":"○"} ${txt}</span>`,
  row=(name,gets,status)=>`<tr><td><b>${name}</b></td><td class="note">${gets}</td><td class="note">${status}</td></tr>`;
 return `<div class="card" data-pv="flow"><h3 style="margin:0 0 4px">How Percival works - one pipeline, one score</h3>
  <p class="note" style="margin-top:0">Every part below is trained and switched on <b>automatically</b> in each training cycle when its input exists - there is no separate switch per model. The only switch is <b>local learning</b> (${on?'<span class="ok">on</span>':'<span class="bad">off</span>'}).</p>
  <table><tr><th>Part</th><th>What it receives</th><th>In this project</th></tr>
  ${row("1 · ALBUS · detection","finds the candidates and gives each its detector score (score_v4)",st(I.candidates>0,`${I.candidates||0} of ${n} learning studies`))}
  ${row("2 · NOX · measurements","30 measurements per candidate: 27 from the detector (surface, shape, darkness, vessel, position) + 3 extracted (vessel continuity, core contrast, extracranial continuation); compares logistic / boosted trees / random forest",st(!!ch("char")||I.predictor_candidates>0,ch("char")?`chosen: ${esc(ch("char"))}`:`${I.predictors||0} of ${n} studies with the 3 extracted measurements · trained in the next cycle`))}
  ${row("3 · LUMOS · image","the MRI patch around each candidate; compares a pixel baseline with a small CNN (CNN only if it wins)",st(I.image>0,`${I.image||0} of ${n} studies with image patches${ch("image")?` · chosen: ${esc(ch("image"))}`:""}`))}
  ${row("→ PERCIVAL score","1-3 combined by ONE meta-model learned from your expert calls (it also learns when they disagree), calibrated, red / yellow / green",st(!!s.active,s.active?`model ${esc(s.active.version)} in use`:"no model in use yet"))}
  </table>
  <p class="note">Labels: your expert calls in Review (cSS = 1; Vessel / Normal / Artifact / Microbleed = 0; Unsure and Near ICH are not used). The other screens under <i>Older prototypes</i> (Training, uScore scorer, Stage-1 shadow-mode prototype, Image ML prototype) are the separate research prototypes these parts were developed from; they do <b>not</b> feed the PERCIVAL score. <i>Stage-1 shadow-mode prototype</i> = the earlier Unified-Score engine run in "shadow mode": it computes its predictions next to the pipeline for comparison and never changes a result.</p></div>`}

// ------------------------------------------------------------------ v5.25 Training Center: 14 Modular Sections (Standard & Advanced View)
const PVR={NOT_REVIEWED:"not reviewed",UNCERTAIN:"Unsure",OUT_OF_SCOPE:"Near ICH (out of scope)",CONFLICT:"reviewers disagree",STUDY_EXCLUDED:"study left out",
  STUDY_ARCHIVED:"archived",DUPLICATE_STUDY:"duplicate examination",NOT_AUTHORIZED:"learning off",NO_IMAGE:"no MRI patch",NO_MEASUREMENTS:"no measurements",
  LOCKED_TEST:"locked test",HISTORICAL_LABEL:"earlier-version label",QC_LOW:"QC low",NO_PREDICTORS:"no reliable predictor",UNRECOGNISED_CALL:"call not recognised"};
const PVCN={char:"NOX measurement model",image:"LUMOS image network",meta:"PERCIVAL meta-model",shadow:"Shadow",detection:"Candidate Detection (ALBUS)",segmentation:"Lesion Segmentation"};
function pvStatus(e){e=e||{};const k=e.status||"—",c={active:"ok",candidate:"warn",experimental:"",retired:"",rejected:"bad"}[k]||"";return `<span class="pill ${c}" title="${esc((e.why||"")+(e.at?" · "+e.at:""))}">${esc(k)}</span>`}

async function pvCenter(el,s,v){
  const O=s.overview||{},LS=s.learn_settings||{},DSs=s.datasets||[],last=DSs[DSs.length-1];
  const L=s.labels||{},j=s.job||{},M=s.active,Lt=s.latest,runs=s.runs||[],H=s.history||[];
  const sel=(s.selection||[]).filter(x=>!PV.q||(x.label+" "+x.cohort).toLowerCase().includes(PV.q.toLowerCase()));
  const isAdv=PV.viewMode==="advanced";
  const missedList=L.missed_detail||[];

  const tile=(n,t,k,badge)=>`<div class="tile" ${k?`data-pv="${k}"`:""}><div class="n">${n??0} ${badge?`<small class="pill sm ${badge.cls||''}">${badge.txt}</small>`:''}</div><div class="t">${t}</div></div>`;

  // Pre-flight validation diagnostics
  const validMriOk=(s.valid_mri_count||O.registered||0)>0;
  const devCssCount=(L.css_dev||0);
  const devMimicCount=(L.mimic_dev||0);
  const minReqsMet=devCssCount>=3 && devMimicCount>=3 && (devCssCount+devMimicCount)>=10;
  const preflightPass=validMriOk && minReqsMet;

  // Component breakdown for Dataset Builder
  const comp=last?["char","image","meta","shadow","detection","segmentation"].filter(k=>(last.components||{})[k]).map(k=>{
    const c=(last.components||{})[k]||{},d=c.development||{},t=c.test||{};
    const nameMap={char:"NOX measurement model",image:"LUMOS image network",meta:"PERCIVAL Decision Engine (meta-model)",shadow:"SHADOW evaluation",detection:"ALBUS Candidate Detection",segmentation:"cSS Lesion Segmentation"};
    return `<tr><td><b>${nameMap[k]||k}</b></td><td class="mono">${d.n??0}</td><td class="mono">${d.css??0} / ${d.not_css??0}</td><td class="mono">${d.patients??0}</td><td class="mono">${t.n??0}</td><td class="mono">${t.css??0} / ${t.not_css??0}</td><td class="mono">${t.patients??0}</td></tr>`;
  }).join(""):"";

  el.innerHTML=`
  <!-- SECTION 1: Training Overview -->
  <div class="card" data-pv="section-overview">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">1. Training Overview</h3>
        <p class="note" style="margin:0">${isAdv?"State telemetry: study registry, ALBUS candidate discovery, expert ground truth, missed lesions, and cohort partitioning.":"Summary of registered MRI scans, candidate discovery, expert radiologist annotations, and learning readiness."}</p>
      </div>
      <span class="pill ${preflightPass?'ok':PV_ACTIVE(s.job)?'warn':L.stale?'warn':'bad'}">${PV_ACTIVE(s.job)?'Training Active':preflightPass?'Ready for Training':minReqsMet?'Awaiting Pre-flight':'More Annotations Needed'}</span>
    </div>
    <div class="tiles" style="margin-top:12px">
      ${tile(O.registered,isAdv?"Registered Studies":"Total Studies Registered")}
      ${tile(s.valid_mri_count||O.registered,isAdv?"Valid NIfTI/DICOM Scans":"MRI Scans Available")}
      ${tile(O.processed,isAdv?"ALBUS Processed Studies":"Processed Studies")}
      ${tile(O.candidates,isAdv?"Candidates Extracted":"Candidates Detected")}
      ${tile(s.awaiting_review_count||Math.max(0,(O.registered||0)-(O.reviewed_studies||0)),"Awaiting Review")}
      ${tile(O.reviewed_studies,isAdv?"Finalized Review Studies":"Finished Reviews")}
      ${tile((L.css_dev||0)+(L.css_test||0),"Confirmed cSS Lesions")}
      ${tile(s.missed_lesions_count||L.n_missed||0,"Expert Missed Lesions",{cls:"ok",txt:"Learned"})}
      ${tile((L.mimic_dev||0)+(L.mimic_test||0),"Mimic Findings")}
      ${tile(O.eligible_dev||0,isAdv?"Dev Cohort Candidates":"Eligible for Learning")}
    </div>
  </div>

  <!-- SECTION 2: Available Studies -->
  <div class="card" data-pv="section-studies">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">2. Available Studies</h3>
        <p class="note" style="margin:0">Inspection of MRI examinations across local workspace and storage topology.</p>
      </div>
      <div class="row" style="gap:6px">
        <input id="pv-q" placeholder="Search studies or cohort..." value="${esc(PV.q)}" style="width:220px">
        <button class="b sm" id="pv-inc">Include Selected</button>
        <button class="b sm" id="pv-exc">Exclude Selected</button>
      </div>
    </div>
    <div style="max-height:300px;overflow-y:auto;margin-top:10px">
      <table data-pv="selection">
        <tr>
          <th style="width:34px"><input type="checkbox" id="pv-all"></th>
          <th>Study Code</th>
          <th>Candidate Detection</th>
          <th>Review State</th>
          <th>Annotated</th>
          <th>cSS / Mimic</th>
          <th>Eligible</th>
          <th>Partition</th>
          <th>Inclusion Status</th>
          <th>Action</th>
        </tr>
        ${sel.map(x=>`<tr>
          <td><input type="checkbox" data-pvs="${esc(x.code)}"></td>
          <td><b>${esc(x.label)}</b>${x.retired?' <span class="pill sm">archived</span>':""}<div class="note">${esc(x.cohort||"")}</div></td>
          <td>${x.processed?`<span class="ok">✓</span> <span class="note">${x.n_candidates} cands</span>`:'<span class="mut">Pending ALBUS</span>'}</td>
          <td class="note">${x.reviewed?'<span class="ok">Finished</span>':esc(x.review_state||"Pending")}</td>
          <td class="mono">${x.n_labelled}${x.n_historical?` <span class="note" title="labels from earlier versions">(${x.n_historical} earlier)</span>`:""}${x.n_stale?` <span class="warn" title="calls that no longer match current candidates">+${x.n_stale} stale</span>`:""}</td>
          <td class="mono">${x.n_css} / ${x.n_mimic}</td>
          <td class="mono">${x.n_eligible}${x.n_adjudication?` <span class="warn" title="disagreement">⚑</span>`:""}</td>
          <td class="note">${x.partition==="test"?"Locked Test":"Development"}</td>
          <td>${x.included?'<span class="ok">✓ Included</span>':`<span class="mut">${esc(x.excluded_why||x.why||"Excluded")}</span>`}${x.label_error?` <span class="warn">${esc(x.label_error)}</span>`:""}</td>
          <td>${x.n_labelled?`<button class="b sm" data-pvc="${esc(x.code)}">Inspect</button>`:""}</td>
        </tr>
        ${PV.open===x.code?`<tr><td></td><td colspan="9" id="pv-cands" class="note">Loading candidate breakdown…</td></tr>`:""}`).join("")}
      </table>
    </div>
  </div>

  <!-- SECTION 3: Expert Review Status -->
  <div class="card" data-pv="section-review-status">
    <h3 style="margin:0 0 4px">3. Expert Review Status</h3>
    <p class="note" style="margin-top:0">Distinguishes individual candidate calls from formal study-level completion and missed-lesion assessment.</p>
    <div class="row" style="gap:12px;margin-bottom:8px">
      <div class="tile" style="flex:1"><div class="n">${O.reviewed_studies||0} / ${O.registered||0}</div><div class="t">Study-Level Reviews Completed</div></div>
      <div class="tile" style="flex:1"><div class="n">${O.called||0} / ${O.candidates||0}</div><div class="t">Candidates Explicitly Called</div></div>
      <div class="tile" style="flex:1"><div class="n">${missedList.length}</div><div class="t">Missed-Lesion Evaluations Recorded</div></div>
    </div>
    <p class="note">A study is only marked <b>Finished</b> for training when all generated candidates have explicit calls, missed lesion review is finalized, and study-level classification is confirmed.</p>
  </div>

  <!-- SECTION 4: Candidate Annotations -->
  <div class="card" data-pv="section-candidate-annotations">
    <h3 style="margin:0 0 4px">4. Candidate Annotations &amp; Clinical Vocabulary</h3>
    <p class="note" style="margin-top:0">${isAdv?"Ground-truth labels categorized by formal clinical classification ontology (LABELS).":"Candidate labels verified by expert neuroradiologists, distinguishing genuine cSS from non-cSS mimickers."}</p>
    <table class="lv-w">
      <tr><th>Clinical Category</th><th>Classification Meaning</th><th>Model Target Label</th><th>Development Cohort</th><th>Locked Test Cohort</th></tr>
      <tr><td><b>Confirmed cSS</b></td><td>Definite cortical superficial siderosis lesion</td><td><span class="pill ok">Positive (y = 1)</span></td><td class="mono">${L.css_dev||0}</td><td class="mono">${L.css_test||0}</td></tr>
      <tr><td><b>Rejected Not cSS</b></td><td>Definitive non-cSS candidate</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono">${L.mimic_dev||0}</td><td class="mono">${L.mimic_test||0}</td></tr>
      <tr><td><b>Cortical / Pial Vessel</b></td><td>Normal pial or subarachnoid vessel mimic</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Prominent Vessel or Vein</b></td><td>Prominent vascular signal or draining vein</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Vascular Flow-Related Signal</b></td><td>Flow void, pulsation, or inflow artifact</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Susceptibility Artifact</b></td><td>Air-bone interface or skull-base distortion</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Calcification</b></td><td>Dural or parenchymal calcification mimic</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Other Hemorrhagic / Abnormality</b></td><td>Microbleed, cavernoma, hemorrhage, or trauma</td><td><span class="pill">Negative (y = 0)</span></td><td class="mono note">Categorized</td><td class="mono note">Categorized</td></tr>
      <tr><td><b>Uncertain / Needs Further Review</b></td><td>Ambiguous finding requiring secondary review</td><td><span class="pill warn">Excluded from Training</span></td><td class="mono note">${O.excluded_unsure||0}</td><td class="mono note">—</td></tr>
    </table>
  </div>

  <!-- SECTION 5: Missed-Lesion Annotations -->
  <div class="card" data-pv="section-missed-lesions">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">5. Missed-Lesion Annotations (Learned from Expert Freehand Annotations)</h3>
        <p class="note" style="margin:0">cSS lesions identified and drawn by expert reviewers that were initially missed by ALBUS candidate discovery. Stored in PENSIEVE memory and ingested into training.</p>
      </div>
      <span class="pill ok">${missedList.length} Missed Lesions Available</span>
    </div>
    ${missedList.length?`
    <div style="max-height:220px;overflow-y:auto;margin-top:10px">
      <table>
        <tr><th>Study ID</th><th>Lesion ID</th><th>Slice / Z</th><th>Physical Coordinates (mm)</th><th>Detection Fate</th><th>Target Training Tasks</th><th>Learning Weight</th></tr>
        ${missedList.map(m=>`<tr>
          <td class="mono"><b>${esc(m.study_id)}</b></td>
          <td class="mono">${esc(m.lesion_id)}</td>
          <td class="mono">Slice ${esc(m.slice||"—")}</td>
          <td class="mono note">${m.x_mm!=null?`(${g3(m.x_mm)}, ${g3(m.y_mm)}, ${g3(m.z_mm)})`:"—"}</td>
          <td><span class="pill warn">${esc(m.detector_fate||"albus_missed")}</span></td>
          <td class="note">${(m.eligible_for||["detection","meta","segmentation"]).join(" · ")}</td>
          <td><span class="pill ok">Positive (y = 1)</span></td>
        </tr>`).join("")}
      </table>
    </div>
    <p class="note">These annotations feed directly into <b>ALBUS candidate detection</b> retraining, <b>LUMOS/NOX meta-learning</b>, and <b>lesion segmentation</b>. They are never assigned negative labels.</p>
    `:`<p class="note" style="margin-top:8px">No missed lesions drawn yet. Reviewers can draw missed lesions in the MRI viewer; they are preserved in PENSIEVE and ingested automatically.</p>`}
  </div>

  <!-- SECTION 6: Training Eligibility -->
  <div class="card" data-pv="section-eligibility">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">6. Task-Specific Training Eligibility</h3>
        <p class="note" style="margin:0">Evaluates suitability for distinct model objectives: Candidate Classification, Candidate Discovery, Segmentation, and Study-Level Learning.</p>
      </div>
      <button class="b sm" id="pv-elig">Evaluate Eligibility Now</button>
    </div>
    ${(()=>{
      const E=s.eligibility_record||{};
      const bc=E.by_component||{};
      return `
      <table style="margin-top:10px">
        <tr><th>Learning Task</th><th>Target Pipeline Component</th><th>Eligible Candidates</th><th>Eligibility Criteria</th><th>Status</th></tr>
        <tr><td><b>Candidate Classification</b></td><td>LUMOS, NOX &amp; PERCIVAL Decision Engine</td><td class="mono"><b>${bc.char||bc.meta||O.eligible||0}</b></td><td>Complete feature vector, valid MRI patch, unambiguous expert label</td><td><span class="pill ok">Active</span></td></tr>
        <tr><td><b>Candidate Discovery &amp; Detection</b></td><td>ALBUS (Candidate Generator)</td><td class="mono"><b>${(O.candidates||0) + missedList.length}</b></td><td>All ALBUS candidates + reviewer-drawn missed lesions</td><td><span class="pill ok">Active</span></td></tr>
        <tr><td><b>Lesion Segmentation</b></td><td>NOX Morphological Boundary Engine</td><td class="mono"><b>${(L.css_dev||0)+(L.css_test||0) + missedList.length}</b></td><td>Pixel-level pen stroke masks and candidate bounding boxes</td><td><span class="pill ok">Active</span></td></tr>
        <tr><td><b>Study-Level Siderosis Evaluation</b></td><td>PERCIVAL study aggregation</td><td class="mono"><b>${O.reviewed_studies||0} studies</b></td><td>Finished study review, all candidates verified, missed lesions addressed</td><td><span class="pill ${O.reviewed_studies>0?'ok':'warn'}">${O.reviewed_studies>0?'Ready':'Pending Reviews'}</span></td></tr>
      </table>`;
    })()}
  </div>

  <!-- SECTION 7: Training Dataset Builder -->
  <div class="card" data-pv="section-dataset-builder">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">7. Training Dataset Builder</h3>
        <p class="note" style="margin:0">Immutable dataset snapshot manifests with patient-stratified cohort splitting and reproducible hashing.</p>
      </div>
      ${last?`<button class="b sm" id="pv-repro">Verify Reproducibility</button>`:""}
    </div>
    ${last?`
    <div class="kv" style="margin:10px 0">
      <div>Manifest Identifier</div><div class="mono"><b>${esc(last.id)}</b></div>
      <div>Content SHA-256 Hash</div><div class="mono">${esc(last.content_hash)}</div>
      <div>Rules &amp; Feature Schema</div><div class="mono">${esc(last.rules_version)} · ${esc(last.feature_schema)}</div>
      <div>Created Timestamp</div><div class="mono">${esc(last.created)}</div>
    </div>
    <table>
      <tr><th>Component</th><th>Dev Cohort (n)</th><th>Dev cSS / Mimic</th><th>Dev Patients</th><th>Locked Test (n)</th><th>Test cSS / Mimic</th><th>Test Patients</th></tr>
      ${comp}
    </table>
    <p class="note">Manifest versions available: ${DSs.map(d=>`<a href="#" data-pvdl="${esc(d.id)}">${esc(d.id)}</a>`).join(" · ")} <span id="pv-repro-r" style="margin-left:12px"></span></p>
    `:`<p class="note" style="margin-top:8px">No dataset snapshot created yet. Snapshots are compiled immutably at the start of each training cycle.</p>`}
  </div>

  <!-- SECTION 8: Training Configuration -->
  <div class="card" data-pv="section-config">
    <h3 style="margin:0 0 4px">8. Training Configuration</h3>
    <p class="note" style="margin-top:0">Operational parameters governing cohort selection, conflict arbitration, and automatic learning triggers.</p>
    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:10px">
      <label class="note">Learning Inclusion Policy:
        <select id="pv-lf" style="margin-left:6px">
          <option value="labelled" ${LS.learn_from!=="finished"?"selected":""}>Every study with expert calls (called candidates only)</option>
          <option value="finished" ${LS.learn_from==="finished"?"selected":""}>Finalized studies only (full study review complete)</option>
        </select>
      </label>
      <label class="note">Reviewer Conflict Handling:
        <select id="pv-cf" style="margin-left:6px">
          <option value="exclude" ${LS.conflicts!=="effective"?"selected":""}>Exclude conflicting calls until adjudicated</option>
          <option value="effective" ${LS.conflicts==="effective"?"selected":""}>Use effective consolidated call</option>
        </select>
      </label>
      <label class="note" style="display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="pv-hi" ${LS.use_historical!==false?"checked":""}> Include verified labels from historical projects
      </label>
    </div>
    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:10px;align-items:center">
      <label class="note" style="display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="pv-ac" ${s.autocycle?"checked":""}> Auto-start training cycle after
      </label>
      <input id="pv-n" type="number" min="1" value="${s.cycle_n}" style="width:70px">
      <span class="note">newly reviewed studies</span>
      <span class="note" style="margin-left:14px">Locked Test Fraction:</span>
      <input id="pv-tf" type="number" min="0.1" max="0.4" step="0.05" value="${s.test_fraction}" style="width:80px">
      <span class="note">(permanent holdout)</span>
      <button class="b pri sm" id="pv-save" style="margin-left:auto">Save Configuration</button>
    </div>
  </div>

  <!-- SECTION 9: Start Training Cycle (Pre-Flight Diagnostics & Action) -->
  <div class="card" data-pv="section-start-training" style="background:var(--panel2)">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">9. Start Training Cycle</h3>
        <p class="note" style="margin:0">Pre-flight readiness audit and manual training execution trigger.</p>
      </div>
      ${pvTrainBtn(j,"pvc-start-train","Start Training Cycle")}
    </div>
    <div style="background:var(--bg);border-radius:6px;padding:12px;margin-top:12px">
      <h4 style="margin:0 0 8px">Pre-Flight Diagnostic Checklist</h4>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px">
        <div>${validMriOk?'<span class="ok">✓</span>':'<span class="bad">✗</span>'} Scans: <b>${s.valid_mri_count||O.registered||0} available</b></div>
        <div>${devCssCount>=3?'<span class="ok">✓</span>':'<span class="warn">!</span>'} Positive cSS (Dev): <b>${devCssCount} / 3 min</b></div>
        <div>${devMimicCount>=3?'<span class="ok">✓</span>':'<span class="warn">!</span>'} Mimic Non-cSS (Dev): <b>${devMimicCount} / 3 min</b></div>
        <div>${(devCssCount+devMimicCount)>=10?'<span class="ok">✓</span>':'<span class="warn">!</span>'} Total Dev Candidates: <b>${devCssCount+devMimicCount} / 10 min</b></div>
        <div>${missedList.length>0?'<span class="ok">✓</span>':'<span class="note">○</span>'} Missed Lesions: <b>${missedList.length} included</b></div>
      </div>
      ${!minReqsMet?`
      <p class="warn" style="margin:10px 0 0"><b>Expert Review Required:</b> Training requires at least 3 confirmed cSS lesions and 3 non-cSS mimics in the development cohort (currently ${devCssCount} cSS, ${devMimicCount} mimics). Open <b>Review</b> to confirm candidate classifications.</p>
      `:''}
    </div>
  </div>

  <!-- SECTION 10: Live Training Progress -->
  <div class="card" data-pv="section-progress">
    <h3 style="margin:0 0 4px">10. Live Training Progress &amp; Heartbeat</h3>
    <p class="note" style="margin-top:0">Monitors background training worker, feature extraction, cross-validation folds, and model convergence.</p>
    <div data-pv-jobslot="1">${pvJobCard(j,true)}</div>
  </div>

  <!-- SECTION 11: Evaluation Results -->
  <div class="card" data-pv="section-evaluation">
    <h3 style="margin:0 0 4px">11. Model Evaluation Results</h3>
    <p class="note" style="margin-top:0">${isAdv?"Locked permanent holdout metrics: ROC-AUC (DeLong 95% CI), PR-AUC, Brier score, log loss, and calibration slope.":"Performance on locked holdout patients who were never used during training or model selection."}</p>
    ${Lt?`
    <table>
      <tr><th>Model / Predictor</th><th>Locked-Test AUC</th>${isAdv?`<th>PR-AUC</th><th>Brier Score</th><th>Log Loss</th><th>Calib Slope</th>`:""}<th>Operating Sensitivity</th><th>Operating Specificity</th></tr>
      <tr>
        <td><b>PERCIVAL score (${esc(Lt.version)})</b></td>
        <td class="mono"><b>${g3(((Lt.test||{}).percival||{}).auc)}</b></td>
        ${isAdv?`<td class="mono">${g3(((Lt.test||{}).percival||{}).pr_auc)}</td><td class="mono">${g3(((Lt.test||{}).percival||{}).brier)}</td><td class="mono">${g3(((Lt.test||{}).percival||{}).logloss)}</td><td class="mono">${g3(((Lt.test||{}).percival||{}).calib_slope)}</td>`:""}
        <td class="mono">${pct(100*((Lt.test||{}).at_red||{}).sensitivity)}%</td>
        <td class="mono">${pct(100*((Lt.test||{}).at_red||{}).specificity)}%</td>
      </tr>
      <tr>
        <td><b>Deterministic Candidate Detection Alone</b></td>
        <td class="mono">${g3(((Lt.test||{}).math||{}).auc)}</td>
        ${isAdv?`<td class="mono">${g3(((Lt.test||{}).math||{}).pr_auc)}</td><td class="mono">${g3(((Lt.test||{}).math||{}).brier)}</td><td class="mono">${g3(((Lt.test||{}).math||{}).logloss)}</td><td class="mono">—</td>`:""}
        <td class="mono">—</td>
        <td class="mono">—</td>
      </tr>
    </table>
    <p class="note">${Lt.acceptance?`Governance Acceptance: <b>${Lt.acceptance.passed?"PASSED":"NOT PASSED"}</b>${Lt.acceptance.reasons.length?" — "+Lt.acceptance.reasons.map(esc).join("; "):""}.`:""}</p>
    `:`<p class="note">Evaluation metrics will appear here after the first completed training cycle.</p>`}
  </div>

  <!-- SECTION 12: Model Versions -->
  <div class="card" data-pv="section-versions">
    <div class="row" style="justify-content:space-between;align-items:center">
      <div>
        <h3 style="margin:0 0 4px">12. Model Versions &amp; Model Registry</h3>
        <p class="note" style="margin:0">Active, candidate, experimental, and retired models. Models require explicit promotion to become active.</p>
      </div>
      <button class="b sm" id="pvc-rollback">Roll Back to Previous Version</button>
    </div>
    <table style="margin-top:10px">
      <tr><th>Version</th><th>Trained</th><th>Studies</th><th>Dataset</th><th>Meta-Architecture</th><th>Test AUC</th><th>ALBUS</th><th>Acceptance</th><th>Status</th><th>Actions</th></tr>
      ${H.slice().reverse().map(h=>`<tr>
        <td class="mono"><b>${esc(h.version)}</b></td>
        <td class="note">${esc((h.at||"").replace("T"," "))}</td>
        <td>${h.studies}</td>
        <td class="mono">${h.dataset?`<a href="#" data-pvdl="${esc(h.dataset)}">${esc(h.dataset)}</a>`:'—'}</td>
        <td class="note">${esc(MN[h.chosen]||h.chosen)}</td>
        <td class="mono">${g3(h.test_auc)}</td>
        <td class="mono">${g3(h.test_math_auc)}</td>
        <td>${h.passed?'<span class="ok">Passed</span>':'<span class="warn">Flagged</span>'}</td>
        <td>${pvStatus((s.status||{})[h.version])}</td>
        <td>${M&&M.version===h.version?'<span class="ok">Active</span>':`<button class="b sm" data-pvp="${esc(h.version)}">Make Active</button>`}</td>
      </tr>`).join("")||'<tr><td colspan="10" class="empty">No models registered yet.</td></tr>'}
    </table>
  </div>

  <!-- SECTION 13: Training History -->
  <div class="card" data-pv="section-history">
    <h3 style="margin:0 0 4px">13. Training History &amp; Run Ledger</h3>
    <p class="note" style="margin-top:0">Full audit trail of all previous training invocations, parameters, and results.</p>
    ${runs.length?`
    <table style="margin-top:10px">
      <tr><th>Run ID</th><th>Started</th><th>Trigger Reason</th><th>State</th><th>Dataset Snapshot</th><th>Target Version</th><th>Execution Outcome</th></tr>
      ${runs.slice().reverse().map(r=>`<tr>
        <td class="mono">${esc(r.id)}</td>
        <td class="note">${esc(r.started||"")}${r.finished?" → "+esc(r.finished.slice(11)):""}</td>
        <td class="note">${esc(r.reason||r.kind||"Manual trigger")}</td>
        <td>${{finished:'<span class="ok">Finished</span>',failed:'<span class="bad">Failed</span>',running:'<span class="warn">Running</span>',interrupted:'<span class="warn">Interrupted</span>',insufficient_data:'<span class="warn">Paused</span>'}[r.state]||esc(r.state)}</td>
        <td class="mono">${esc(r.dataset||"—")}</td>
        <td class="mono">${esc(r.version||"—")}</td>
        <td class="note">${r.error?esc(r.error.slice(0,160)):r.status?esc(r.status):esc(r.kind||"Completed")}</td>
      </tr>`).join("")}
    </table>
    `:`<p class="note" style="margin-top:8px">No training runs logged in ledger yet.</p>`}
  </div>

  <!-- SECTION 14: Failed or Interrupted Runs -->
  <div class="card" data-pv="section-diagnostics">
    <h3 style="margin:0 0 4px">14. Diagnostic Review for Failed / Interrupted Runs</h3>
    <p class="note" style="margin-top:0">Root-cause diagnostic analysis, exception inspection, and targeted recovery recommendations.</p>
    ${(()=>{
      const failedRun=runs.slice().reverse().find(r=>r.state==="failed"||r.state==="interrupted"||r.state==="insufficient_data"||r.error);
      if(!failedRun){
        return '<p class="ok" style="margin-top:8px">✓ No failed or interrupted training runs detected. Training subsystem is healthy.</p>';
      }
      return `
      <div style="background:var(--bg);border-left:4px solid var(--lv-red);padding:12px;border-radius:4px;margin-top:10px">
        <div class="row" style="justify-content:space-between">
          <b>Run ${esc(failedRun.id)}: ${esc(failedRun.state)}</b>
          <span class="note">${esc(failedRun.started||"")}</span>
        </div>
        <p class="bad" style="margin:6px 0">${esc(failedRun.error||"Run paused or interrupted.")}</p>
        <p class="note" style="margin:4px 0"><b>Targeted Recovery Advice:</b> ${
          failedRun.state==="insufficient_data" || (failedRun.error&&failedRun.error.includes("Not enough labelled candidates"))
          ? "Provide at least 3 confirmed cSS labels and 3 mimic labels in the Review screen before retraining."
          : failedRun.error&&failedRun.error.includes("features")
          ? "Ensure candidate feature extraction has finished for the selected studies."
          : "Review the system log below and verify file permissions in the project workspace."
        }</p>
      </div>`;
    })()}
    ${(s.log||[]).length?`
    <details style="margin-top:12px">
      <summary class="note">View Recent Pipeline Log Entries</summary>
      <pre class="note" style="white-space:pre-wrap;margin-top:6px;max-height:160px;overflow-y:auto">${esc(s.log.join("\n"))}</pre>
    </details>
    `:''}
  </div>
  `;

  // Bind interactive handlers
  $("#pv-save")&&($("#pv-save").onclick=async()=>{
    await api("/api/percival/settings",{
      percival_autocycle:$("#pv-ac").checked,
      percival_cycle_n:Math.max(1,+$("#pv-n").value||5),
      percival_test_fraction:Math.min(0.4,Math.max(0.1,+$("#pv-tf").value||0.2)),
      percival_learn_from:$("#pv-lf").value,
      percival_conflicts:$("#pv-cf").value,
      percival_use_historical:$("#pv-hi").checked
    });
    toast("Settings saved successfully");
    intelView(v);
  });

  $("#pv-elig")&&($("#pv-elig").onclick=async()=>{
    const r=await api("/api/percival/eligibility",{});
    toast(r.error?esc(r.error):`Eligibility evaluated: ${r.n} candidates`,!!r.error);
    intelView(v);
  });

  $("#pvc-start-train")&&($("#pvc-start-train").onclick=async()=>{
    const res=await api("/api/percival/train",{});
    toast(res.ok?"Training cycle started":esc(res.error||"Training started"),!res.ok);
    intelView(v);
  });

  $("#pvc-rollback")&&($("#pvc-rollback").onclick=async()=>{
    const r=await api("/api/percival/rollback",{});
    toast(r.ok?`Rolled back to ${esc(r.version)}`:esc(r.error),!r.ok);
    intelView(v);
  });

  $("#pv-repro")&&($("#pv-repro").onclick=async()=>{
    const out=$("#pv-repro-r");
    if(out)out.textContent="Verifying reproducibility…";
    const r=await api("/api/percival/reproduce",{id:last.id});
    if(out){
      out.innerHTML=r.identical
        ? `<span class="ok">✓ Identical manifest (${esc(r.rebuilt_hash)})</span>`
        : `<span class="warn">Differs: ${r.n_differences} differences</span>`;
    }
  });

  $("#pv-q")&&($("#pv-q").oninput=e=>{
    PV.q=e.target.value;
    clearTimeout(PV.t);
    PV.t=setTimeout(()=>intelView(v),250);
  });

  $("#pv-all")&&($("#pv-all").onchange=e=>el.querySelectorAll("[data-pvs]").forEach(c=>c.checked=e.target.checked));
  const ticked=()=>[...el.querySelectorAll("[data-pvs]:checked")].map(c=>c.dataset.pvs);

  $("#pv-inc")&&($("#pv-inc").onclick=async()=>{
    await api("/api/percival/select",{codes:ticked(),include:true});
    intelView(v);
  });
  $("#pv-exc")&&($("#pv-exc").onclick=async()=>{
    await api("/api/percival/select",{codes:ticked(),include:false});
    intelView(v);
  });

  el.querySelectorAll("[data-pvc]").forEach(b=>b.onclick=()=>{
    PV.open=PV.open===b.dataset.pvc?"":b.dataset.pvc;
    intelView(v);
  });

  el.querySelectorAll("[data-pvdl]").forEach(a=>a.onclick=async e=>{
    e.preventDefault();
    const d=await api(`/api/percival/dataset?id=${encodeURIComponent(a.dataset.pvdl)}`);
    const w=window.open("","_blank");
    if(w){
      w.document.title=d.id||"Dataset Manifest";
      w.document.body.innerHTML=`<pre style="white-space:pre-wrap;font:12px monospace">${esc(JSON.stringify(d,null,1))}</pre>`;
    }
  });

  if(PV.open){
    const C=await api(`/api/percival/candidates?code=${encodeURIComponent(PV.open)}`),t=$("#pv-cands");
    if(t){
      t.innerHTML=`<table data-pv="candidates" style="margin:8px 0">
        <tr><th>#</th><th>Call</th><th>Label Source</th><th>Status</th><th>NOX</th><th>LUMOS</th><th>PERCIVAL</th><th>Missing</th><th>Reason</th></tr>
        ${(C.candidates||[]).map(c=>`<tr>
          <td class="mono">${c.cand_id}</td>
          <td><b>${esc(c.call)}</b></td>
          <td class="note">${c.label_source==="historical"?"earlier version":"current review"}${c.reviewer?` · ${esc(c.reviewer)}`:""}</td>
          <td>${{eligible:'<span class="ok">Eligible</span>',needs_adjudication:'<span class="warn">Adjudication</span>',excluded:'<span class="mut">Excluded</span>'}[c.status]||esc(c.status)}</td>
          ${["char","image","meta"].map(k=>`<td>${c.components[k]?'<span class="ok">✓</span>':`<span class="mut" title="${esc(((c.component_reasons_text||{})[k]||[]).join("; "))}">✗</span>`}</td>`).join("")}
          <td class="note">${esc((c.missing||[]).join("; "))||"—"}</td>
          <td class="note">${esc((c.reasons_text||[]).join("; "))||"—"}</td>
        </tr>`).join("")}
      </table>`;
    }
  }
}

// ------------------------------------------------------------------ v5.24 Data integrity: store schema, migrations, backups, compatibility of every study
async function pvIntegrity(el,s,v){const R=await api("/api/percival/compat"),S=R.store||{};
  el.innerHTML=`<div class="card" data-pv="integrity"><h3 style="margin:0 0 4px">Percival data store</h3>
    <p class="note" style="margin-top:0">Location <span class="mono">${esc(S.path||"")}</span> · schema <b>${S.schema}</b> (this app supports ${S.schema_supported}) · ${S.ok?'<span class="ok">readable</span>':`<span class="bad">${esc(S.error)}</span>`}${S.legacy_left?' · old location kept (moved copy verified)':""}</p>
    ${(S.history||[]).length?`<table data-pv="migrations"><tr><th>When</th><th>Schema</th><th>App</th><th>Steps</th><th>Backup</th></tr>${S.history.map(h=>`<tr><td class="note">${esc(h.at)}</td><td class="mono">${h.frm} → ${h.to}</td><td>${esc(h.app)}</td><td class="note">${(h.steps||[]).map(esc).join("<br>")}</td><td class="note mono">${esc((h.backup||"—").split("/").slice(-2).join("/"))}</td></tr>`).join("")}</table>`:""}
    <p class="note">Backups: ${(S.backups||[]).length?S.backups.map(esc).join(" · "):"none yet"} (project folder › backups/percival/). Updating the app replaces program files only; studies, reviews, models and predictions stay in the project folder.</p></div>
   <div class="card"><h3 style="margin:0 0 4px">Studies (${R.n_registered} in the list${R.n_orphans?`, ${R.n_orphans} found on disk only`:""}; ${R.n_with_issues} with notes)</h3>
    <table data-pv="compat"><tr><th>Study</th><th>In list</th><th>Processed</th><th>MRI</th><th>Review files</th><th>Labels now / earlier</th><th>Predictions</th><th>Notes</th></tr>
    ${(R.studies||[]).map(x=>`<tr><td><b>${esc(x.label)}</b></td><td>${x.registered?"✓":'<span class="warn">no</span>'}</td><td>${x.processed?"✓":"—"}</td><td>${x.mri?"✓":'<span class="mut">missing</span>'}</td><td class="note">${esc(x.review_format)}${x.historical_reviews?` · ${x.historical_reviews} from earlier projects`:""}</td><td class="mono">${x.labels_current} / ${x.labels_historical}</td><td class="mono">${x.predictions}</td><td class="note">${x.issues.map(esc).join("<br>")}</td></tr>`).join("")}</table></div>
   <div class="card"><h3 style="margin:0 0 4px">Models</h3><table><tr><th>Version</th><th>Engine</th><th>Trained</th><th>Dataset</th><th>Readable</th></tr>${(R.models||[]).map(m=>`<tr><td class="mono">${esc(m.version)}</td><td class="note">${esc(m.engine)}</td><td class="note">${esc(m.created||"")}</td><td class="mono">${esc(m.dataset||"— (before v5.24)")}</td><td>${m.readable?"✓":'<span class="bad">no</span>'}</td></tr>`).join("")||'<tr><td colspan="5" class="empty">No model yet.</td></tr>'}</table></div>
   <div class="card"><h3 style="margin:0 0 4px">Reviews made in earlier projects</h3><p class="note" style="margin-top:0">Finds examinations of this project that were reviewed in another Percival / production project on this Mac (same image fingerprint) and copies those review files here as <i>earlier-version labels</i> (verified copy; the other project is only read; nothing is overwritten). They are matched to the current candidates by position and volume.</p>
    <div class="row"><button class="b" id="pv-find">Find reviews in earlier projects</button><span id="pv-found" class="note"></span></div></div>`;
  $("#pv-find").onclick=async()=>{const r=await api("/api/percival/recoverable"),f=$("#pv-found");const it=r.items||[];
    if(!it.length){f.textContent="nothing to bring in";return}
    f.innerHTML=`${it.length} studies: ${it.map(x=>`${esc(x.label)} (${x.files} files, ${esc(x.kind)})`).join(" · ")} <button class="b pri" id="pv-rec">Bring them in</button>`;
    $("#pv-rec").onclick=async()=>{const q=await api("/api/percival/recover",{});toast(`${(q.recovered||[]).length} studies: earlier reviews brought in`);intelView(v)}}}

// Phase 3D: training readiness, computed by the server (expert roles, eligible labels, patient identities, locked split, last leakage audit).
// Display only: training itself re-checks the dataset and refuses on a failed leakage audit or a non-eligible label.
async function pvReadiness(el){let R;try{R=await api("/api/percival/readiness")}catch(e){return}
  const CAT={real_data:"real data",expert:"expert",approval:"approval",setting:"setting"};
  const rows=(R.checks||[]).map(c=>`<tr><td>${c.ok?'<span class="ok">✓</span>':'<span class="bad">✗</span>'}</td><td>${esc(c.name)}</td><td><span class="pill">${esc(CAT[c.category]||c.category||"")}</span></td><td class="note">${esc(c.detail||"")}</td></tr>`).join("");
  el.insertAdjacentHTML("afterbegin",`<div class="card" data-pv="readiness"><h3 style="margin:0 0 4px">Ready for a scientifically defensible training run? ${R.ready?'<span class="ok">yes</span>':'<span class="warn">not yet</span>'}</h3>
   <table>${rows}</table>${R.ready?"":`<p class="note"><b>Still missing:</b> ${Object.entries(R.missing||{}).filter(([k,v])=>v.length).map(([k,v])=>`<b>${esc(CAT[k])}</b>: ${v.map(esc).join("; ")}`).join(" · ")}</p>`}
   <p class="note">${esc(R.policy||"")}. Synthetic test data never counts as real-data performance.</p></div>`)}

// ------------------------------------------------------------------ PERCIVAL architecture screens (System, ALBUS, PENSIEVE, SHADOW)
// Every state shown here comes from /api/percival/architecture (what exists in THIS project) - a component is never shown as active because
// its code exists. Experimental / synthetic results are labelled as such; nothing here trains, promotes or changes a label.
const ARS={experimental:["warn","experimental"],unavailable:["","unavailable"],active:["ok","active"],awaiting_data:["warn","awaiting data"],untrained:["warn","untrained"],trained_not_active:["warn","trained · not active"],
  valid:["ok","trained weights"],off:["","off"],enabled_comparison:["warn","on · comparison only"],built:["ok","built"],not_built:["warn","not built"],available:["ok","available"]};
const arPill=s=>{const[c,l]=ARS[s]||["",s||"—"];return `<span class="pill ${c}">${esc(l)}</span>`};
const arWho=()=>localStorage.getItem("cssapp_reviewer")||"";
async function pvSystem(el){const A=await api("/api/percival/architecture");if(A.error){el.innerHTML=`<div class="card"><p class="bad">${esc(A.error)}</p></div>`;return}
  const R=await api("/api/percival/components_report");
  el.innerHTML=`<div class="card" data-pv="system"><h3 style="margin:0 0 4px">PERCIVAL · Integrated cSS AI system</h3>
   <p class="note" style="margin-top:0">PERCIVAL combines ALBUS mathematical detection, NOX quantitative MRI analysis and LUMOS visual intelligence in one
   learned decision, remembers every expert decision and prediction in PENSIEVE, and tests proposed improvements in SHADOW before you approve them.
   States below are read from this project; research software, not for clinical use.</p>
   <div class="arflow">${A.flow.map((s,i)=>`<span class="arstep">${i+1}. ${esc(s)}</span>`).join('<span class="mut">→</span>')}</div></div>
   <div class="argrid">${A.components.map(c=>`<div class="card arcard" data-arc="${c.key}"><div class="row" style="justify-content:space-between;align-items:center"><h4 style="margin:0">${esc(c.name)}</h4>${arPill(c.state)}</div>
     ${(()=>{const d=(A.described||{})[c.key]||{};return `<p class="note" style="margin:6px 0 2px"><b>Purpose:</b> ${esc(d.purpose||"")}</p>
     <p class="note" style="margin:0 0 2px"><b>Inputs:</b> ${esc(d.inputs||"")} · <b>Outputs:</b> ${esc(d.outputs||"")}</p>
     <p class="note" style="margin:0 0 2px"><b>Status:</b> ${arPill(c.status)}${d.version?` · <b>Version:</b> <span class="mono">${esc(d.version)}</span>`:""}${d.signature_ok===false?' · <span class="bad">approval signature invalid</span>':""}</p>`})()}
     <p class="note" style="margin:6px 0 4px"><b>Implementation:</b> ${esc(c.implementation)}</p>
     <p class="note" style="margin:0 0 4px">${esc(c.detail||"")}</p>
     ${c.registry?`<p class="note" style="margin:0 0 4px">Approved configuration: <span class="mono">${esc(c.registry)}</span>${c.registry==="v000"?" (built-in)":""}</p>`:""}
     ${c.model?`<p class="note" style="margin:0 0 4px">Model <span class="mono">${esc(c.model)}</span> · acceptance ${c.accepted?'<span class="ok">passed</span>':'<span class="warn">not passed</span>'}${c.ready===false?" · below the minimum data":""}</p>`:""}
     <p class="note" style="margin:0"><b>Validation:</b> ${esc(c.validation||"")}</p></div>`).join("")}</div>
   <div class="card"><h3 style="margin:0 0 4px">Component evaluation</h3>${!R.available?`<p class="note">${esc(R.reason||"No trained model yet")}. Component metrics appear after the first training cycle on eligible expert labels.</p>`:
    `<p class="note" style="margin-top:0">${esc(R.basis)} · model <span class="mono">${esc(R.model)}</span>. Locked-test numbers are separate and are evaluated once per model.</p>
     <table><tr><th>Component</th><th>Engine input</th><th>AUC (development, out-of-fold)</th><th>Version (hash)</th></tr>
     ${Object.entries(R.components).map(([k,c])=>`<tr><td><b>${esc(c.owner)}</b></td><td>${esc(c.label)}</td><td class="mono">${c.available?g3((c.development_oof||{}).auc):"— (not available)"}</td><td class="mono">${esc(((R.component_versions||{})[k]||{}).sha256||"—")}</td></tr>`).join("")}
     <tr><td><b>PERCIVAL</b></td><td>decision (${esc(MN[R.percival.chosen_meta_model]||R.percival.chosen_meta_model||"—")})</td><td class="mono">nested ${g3((R.percival.nested_development||{}).auc)} · locked test ${g3((R.percival.locked_test||{}).auc)}</td><td class="mono">${esc(((R.component_versions||{}).meta||{}).sha256||"—")}</td></tr></table>`}</div>
   <div id="pv-sys-ready"></div>
   <div class="card" data-pv="governance"><h3 style="margin:0 0 4px">Validation governance</h3><div id="pv-sys-plan"><p class="note">loading…</p></div></div>
   <div class="card" data-pv="test-group"><h3 style="margin:0 0 4px">Locked test group</h3><div id="pv-sys-tg"><p class="note">loading…</p></div></div>
   <div class="card" data-pv="honesty"><h3 style="margin:0 0 4px">Small-data honesty (development cohort)</h3><div id="pv-sys-an"><p class="note">loading…</p></div></div>
   <div class="card" data-pv="provenance"><h3 style="margin:0 0 4px">Configuration and audit trail</h3>
     <p class="note" style="margin-top:0">Configuration <span class="mono">${esc((A.config||{}).sha256||"—")}</span> · engine ${esc((A.config||{}).engine||"")} · eligibility rules ${esc((A.config||{}).eligibility_rules||"")} · split ${esc((A.config||{}).split_version||"not created")} · automatic cycles ${((A.config||{}).settings||{}).percival_autocycle?'<span class="warn">on</span>':"off"}</p>
     <p class="note">Event log: ${esc(String((A.events||{}).events??"—"))} events · chain ${(A.events||{}).chain_ok?'<span class="ok">intact</span>':'<span class="bad">broken</span>'} · component registry ${(A.events||{}).registry_matches_events?'<span class="ok">matches the events</span>':'<span class="bad">differs from the events</span>'}</p>
     <details><summary class="note">Retired layers (${(A.retired||[]).length}) - docs/engineering/DEPRECATIONS.md</summary><table><tr><th>Item</th><th>Replacement</th><th>State</th></tr>
     ${(A.retired||[]).map(r=>`<tr><td>${esc(r.item)}</td><td class="note">${esc(r.replacement)}</td><td class="note">${esc(r.state)}</td></tr>`).join("")}</table></details></div>`;
  pvReadiness($("#pv-sys-ready")); pvPlan($("#pv-sys-plan")); pvTestGroup($("#pv-sys-tg")); pvHonesty($("#pv-sys-an"))}
async function pvTestGroup(el){const T=await api("/api/percival/test_group"),C=T.counts||{},Pn=T.plan||{},a=Pn.by_class||{},n=T.minimum;
  const row=(k,lab)=>`<tr><td>${lab}</td><td class="mono">${(C[k]||{}).test??0}</td><td class="mono">${(C[k]||{}).development??0}</td><td class="mono">${(Pn.after||{})[k]??"—"}${a[k]?` <span class="note">(+${a[k]})</span>`:""}</td></tr>`;
  el.innerHTML=`<p class="note" style="margin-top:0">Patients are put in the locked test group by a fixed hash of their id (about 20 %), never by hand and never by cSS status - so a small project can end up with too few test patients with or without cSS. Acceptance needs at least ${n} of each.
    <b>Balance</b> adds development patients of the short class in a fixed hash order: only patients whose expert review is finished and that no model was ever trained on; the current test patients stay; at least 8 per class stay for training. A new split version is written (the old one is kept).</p>
   <table><tr><th>Patients</th><th>test</th><th>development</th><th>test after balancing</th></tr>${row("css","with cSS")}${row("no_css","without cSS")}</table>
   <p class="note">Split ${esc(T.version||"—")} (${esc(T.mode||"hash")})${T.unclassified?` · ${T.unclassified} patient(s) without a finished review are not counted`:""}${Object.keys(Pn.short||{}).length?" · still short: "+Object.entries(Pn.short).map(([k,v])=>`${k==="css"?"with cSS":"without cSS"} ${esc(v)}`).join("; "):""}</p>
   <div class="row"><button class="btn" id="pv-tg-bal" ${Pn.add?"":"disabled"}>Balance the test group (+${Pn.add||0} patient${Pn.add===1?"":"s"})…</button></div>`;
  const b=document.getElementById("pv-tg-bal");if(b)b.onclick=async()=>{const by=prompt("Your name (recorded):",arWho()||"");if(!by)return;const why=prompt("Reason:");if(!why)return;
    const c=prompt(`Type ${T.confirm} to write the balanced split:`);const r=await api("/api/percival/test_group_balance",{by,reason:why,confirm:c});
    r.ok?toast(`split ${esc(r.version)}: ${r.added} patient(s) added to the test group`):toast(esc(r.error),1);pvTestGroup(el)}}
async function pvPlan(el){const E=await api("/api/percival/evaluation_plan");const P=E.plan,C=E.consultations||[];
  el.innerHTML=`<p class="note" style="margin-top:0">The locked test cohort supports acceptance <b>once per pre-registered milestone</b>; every consultation is recorded.
   Automatic training cycles are off by default for the pilot.</p>
   ${P?`<p class="note">Plan version ${P.version} by ${esc(P.registered_by)} (${esc(P.at)}) · test size ≥ ${esc(String((P.test_size||{}).min_test_patients_per_class))} patients per class · primary: ${esc(P.primary_metric)}</p>
     <p class="note">Milestones: ${(P.milestones||[]).map(m=>`<span class="pill">${esc(m.id)} ${esc(m.name)}</span>`).join(" ")||"none declared"} · external / temporal validation: ${esc(((P.external_validation||{}).planned)||"not planned yet - required before any claim of generalisation")}</p>`
     :`<p class="warn">No evaluation plan is registered: a locked-test result is reported but cannot support acceptance.</p>`}
   <table><tr><th>Model</th><th>Milestone</th><th>Test patients</th><th>Used for acceptance</th><th>When</th></tr>${C.slice(-8).map(c=>`<tr><td class="mono">${esc(c.version)}</td><td>${esc(c.milestone||"—")}</td><td>${c.n_patients}</td><td>${c.used_for_acceptance?'<span class="ok">yes</span>':"no (reported only)"}</td><td class="note">${esc(c.at)}</td></tr>`).join("")||'<tr><td colspan="5" class="empty">The locked test cohort has not been consulted yet.</td></tr>'}</table>
   <div class="row"><button class="btn" id="pv-plan-reg">${P?"Amend":"Register"} evaluation plan…</button><button class="btn" id="pv-plan-ms" ${P?"":"disabled"}>Declare next milestone…</button></div>`;
  const who=()=>prompt("Your name (recorded):",arWho()||"");
  $("#pv-plan-reg").onclick=async()=>{const by=who();if(!by)return;const why=prompt("Reason:");if(!why)return;const n=prompt("Minimum locked-test patients per class (>= 5):","5");if(!n)return;
    const c=prompt(`Type ${E.confirm_phrase} to register:`);const r=await api("/api/percival/evaluation_plan",{plan:{test_size:{min_test_patients_per_class:+n}},by,reason:why,confirm:c});r.ok?toast("evaluation plan registered"):toast(esc(r.error),1);pvPlan(el)};
  $("#pv-plan-ms").onclick=async()=>{const by=who();if(!by)return;const nm=prompt("Milestone name:");if(!nm)return;const why=prompt("Reason:");if(!why)return;
    const c=prompt(`Type ${E.confirm_phrase} to declare it:`);const r=await api("/api/percival/milestone",{name:nm,by,reason:why,confirm:c});r.ok?toast("milestone "+esc(r.milestone.id)+" declared"):toast(esc(r.error),1);pvPlan(el)}}
async function pvHonesty(el){const A=await api("/api/percival/analysis");
  if(!A.available){el.innerHTML=`<p class="note">${esc(A.reason||"No model yet")}. These analyses appear after the first training cycle on eligible expert labels.</p>`;return}
  const pts=((A.learning_curve||{}).points||[]),ab=(((A.abstention||{}).development||{}).points||[]),md=((A.missing_data||{}).patterns||{});
  el.innerHTML=`<p class="note" style="margin-top:0">Model <span class="mono">${esc(A.version)}</span> · reproducibility hash <span class="mono">${esc(A.model_hash||"—")}</span> · NOX feature set ${esc(((A.features||{}).nox_version)||"v000")} (${((A.features||{}).char||[]).length} measurements). ${esc(A.note||"")}</p>
   <table><tr><th>Inputs available</th><th>Candidates</th><th>cSS</th><th>AUC</th></tr>${Object.entries(md).map(([k,v])=>`<tr><td class="mono">${esc(k)}</td><td>${v.n}</td><td>${v.n_css}</td><td class="mono">${g3(v.auc)}</td></tr>`).join("")}</table>
   <p class="note"><b>Learning curve</b> (${esc((A.learning_curve||{}).basis||"")}): ${pts.map(p=>`${p.patients} patients → ${g3(p.auc_mean)}`).join(" · ")||"—"}${(A.learning_curve||{}).still_improving?' · <span class="warn">still improving with more patients</span>':""}</p>
   <p class="note"><b>Abstention</b>: ${esc((A.abstention||{}).policy||"")}<br>${ab.map(p=>`coverage ${Math.round(p.coverage*100)} % → accuracy ${g3(p.accuracy)}`).join(" · ")}</p>
   <p class="note"><b>Subgroup calibration</b>: ${Object.entries(((A.subgroup_calibration||{}).subgroups)||{}).map(([k,lv])=>`${esc(k)}: ${Object.entries(lv).map(([l,e])=>`${esc(l)} (n ${e.n}, ${esc(e.recalibration)})`).join(", ")}`).join(" · ")} - never recalibrated automatically.</p>`}
async function pvAlbus(el){const A=await api("/api/percival/albus");const E=Object.entries(A.evaluation||{}).filter(([k])=>k!=="unreadable");
  el.innerHTML=`<div class="card" data-pv="albus"><h3 style="margin:0 0 4px">ALBUS · Mathematical Detection</h3>
   <p class="note" style="margin-top:0">The detector (scripts/detect_css.py: candidate generation, rules E1–E30, score_v4) measured per detector version against
   <b>eligible expert ground truth</b>. ${esc(A.note||"")}</p>
   <table><tr><th>Detector version</th><th>Studies</th><th>cSS detected</th><th>cSS missed (expert marks)</th><th>Sensitivity [95 % CI]</th><th>False positives / study</th><th>Candidates / study</th><th>Whole-study searches</th></tr>
   ${E.map(([v,m])=>`<tr><td class="mono">${esc(v)}</td><td>${m.studies.length}</td><td>${m.detected}</td><td>${m.missed}</td><td class="mono">${m.sensitivity==null?"— (no expert-found lesion yet)":g3(m.sensitivity)+(m.sensitivity_ci?` [${g3(m.sensitivity_ci[0])}–${g3(m.sensitivity_ci[1])}]`:"")}</td><td class="mono">${m.fp_per_study??"—"}</td><td class="mono">${m.candidates_per_study??"—"}</td><td>${m.whole_study_searched} / ${m.studies.length}</td></tr>`).join("")||'<tr><td colspan="8" class="empty">No study has a candidate list yet - awaiting MRI processing.</td></tr>'}</table>
   <p class="note">A new detector version is accepted only if it keeps every eligible cSS the previous version found (sensitivity first, then fewer false positives).
   Approved versions are recorded below and never applied automatically.</p>
   <h4 style="margin:12px 0 6px">Approved detector configurations</h4>
   <table><tr><th>Version</th><th>Event</th><th>By</th><th>Reason</th><th>When</th></tr>${((A.registry||{}).history||[]).map(h=>`<tr><td class="mono">${esc(h.version)}</td><td>${esc(h.event)}</td><td>${esc(h.by)}</td><td>${esc(h.reason||"")}</td><td class="note">${esc(h.at)}</td></tr>`).join("")||'<tr><td colspan="5" class="empty">Built-in detector (v000) - no change approved.</td></tr>'}</table></div>`}
async function pvPensieve(el){const P=await api("/api/percival/pensieve_index");
  el.innerHTML=`<div class="card" data-pv="pensieve"><div class="row" style="justify-content:space-between;align-items:center"><div><h3 style="margin:0 0 4px">PENSIEVE · AI Memory and History</h3>
   <p class="note" style="margin:0">One memory per project, rebuilt from the authoritative records (reviewer journals, call ledger, missed-cSS marks, prediction ledger).
   Expert decisions and AI predictions are kept apart; a prediction never becomes a label. The reviewer updates the memory after every save.</p></div>
   <button class="b" id="pns-rebuild">${P.built?"Rebuild from records":"Build memory"}</button></div>
   ${!P.built?'<p class="note">Not built yet for this project.</p>':`
   <div class="row" style="margin:12px 0">${Object.entries(P.counts).map(([k,n])=>`<div class="tile"><div class="n">${n}</div><div class="t">${esc(k.replace("_"," "))}</div></div>`).join("")}</div>
   <p class="note">Content digest <span class="mono">${esc(P.digest)}</span> (the same records always give the same digest) · expert / prediction separation ${P.separation_ok?'<span class="ok">verified</span>':'<span class="bad">VIOLATED</span>'}
   ${((P.status||{}).last_update||{}).ok===false?` · <span class="bad">last update failed: ${esc(P.status.last_update.error)}</span>`:""}${(((P.status||{}).last_rebuild||{}).errors||[]).length?` · <span class="warn">${P.status.last_rebuild.errors.length} studies could not be read</span>`:""}</p>
   <h4 style="margin:12px 0 6px">Detection corrections (from expert decisions)</h4>
   <table><tr><th>Study</th><th>Event</th><th>Responsible</th><th>Detector version</th><th>Expert basis</th><th>Eligible</th></tr>
   ${P.corrections.map(c=>`<tr><td class="mono">${esc(c.study_id)}</td><td>${esc(c.event_type.replace(/_/g," "))}</td><td><b>${esc(c.responsible_component)}</b></td><td class="mono">${esc(c.responsible_version)}</td><td class="note">${esc(c.expert_basis)}</td><td>${c.eligible?"yes":"no"}</td></tr>`).join("")||'<tr><td colspan="6" class="empty">No correction recorded yet.</td></tr>'}</table>`}</div>`;
  $("#pns-rebuild").onclick=async()=>{const r=await api("/api/percival/pensieve_rebuild",{});toast(r.ok?`PENSIEVE rebuilt · digest ${esc(r.digest)}`:`PENSIEVE: ${esc((r.errors||[]).join("; ")||r.error||"failed")}`,!r.ok);pvPensieve(el)}}
async function pvShadow(el,v){const S=await api("/api/percival/shadow_gov"),H=S.hypotheses||[];
  const st=h=>({registered:["","registered"],discovery_done:["warn","discovery done · awaiting PERCIVAL confirmation"],confirmed:["ok","confirmed by PERCIVAL"],not_confirmed:["bad","not confirmed"],
    confirmation_insufficient:["warn","too few confirmation patients"],approved:["ok","approved"],not_implemented:["","experiment not implemented"]})[h.status]||["",h.status];
  el.innerHTML=`<div class="card" data-pv="shadow-lab"><h3 style="margin:0 0 4px">SHADOW · Experimental Discovery Lab</h3>
   <p class="note" style="margin-top:0">SHADOW tests one registered hypothesis at a time on <b>discovery</b> patients of the development cohort.
   PERCIVAL then evaluates it once on separate <b>confirmation</b> patients SHADOW never saw. Only after that, a named person can approve it, which creates a new
   component version (the previous one stays available for rollback). SHADOW never changes a model, rule or label by itself; locked-test patients are never used.</p>
   <p class="note">Data: ${esc(S.source)} · ${S.n_examples} eligible development candidates${S.split?` · ${S.split.discovery} discovery / ${S.split.confirmation} confirmation patients`:""} · NOX configuration <span class="mono">${esc((S.nox||{}).version||"v000")}</span></p>
   <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center"><b>New hypothesis</b><select id="shg-var">${(S.measurements||[]).map(m=>`<option>${esc(m)}</option>`).join("")||"<option value=\"\">(no measurements yet)</option>"}</select>
    <input id="shg-why" placeholder="rationale (why this measurement may separate cSS from mimics)" style="min-width:340px"><button class="b" id="shg-reg" ${S.n_examples?"":"disabled title=\"needs eligible expert labels (train PERCIVAL once)\""}>Register</button></div>
   <table style="margin-top:10px"><tr><th>ID</th><th>Target</th><th>Variable</th><th>Status</th><th>Discovery ΔAUC [CI]</th><th>Confirmation ΔAUC [CI]</th><th></th></tr>
   ${H.map(h=>{const d=(h.discovery||{}).result||{},c=(h.confirmation||{}).result||{},[pc,pl]=st(h);const ci=x=>x?` [${g3(x[0])}–${g3(x[1])}]`:"";
     return `<tr><td class="mono">${esc(h.id)}</td><td><b>${esc(h.target_component)}</b></td><td class="mono">${esc((h.variables||[]).join(", "))}</td><td><span class="pill ${pc}">${esc(pl)}</span>${(h.discovery||{}).synthetic?' <span class="pill warn">SYNTHETIC</span>':""}</td>
      <td class="mono">${d.delta_auc==null?"—":g3(d.delta_auc)+ci(d.delta_auc_ci)}</td><td class="mono">${c.delta_auc==null?"—":g3(c.delta_auc)+ci(c.delta_auc_ci)}</td>
      <td>${h.status==="registered"?`<button class="b sm" data-shg="discovery" data-id="${esc(h.id)}">Run discovery</button>`:h.status==="discovery_done"?`<button class="b sm" data-shg="confirm" data-id="${esc(h.id)}">PERCIVAL confirmation</button>`:(h.status==="confirmed"||h.status==="not_confirmed")?`<button class="b sm" data-shg="approve" data-id="${esc(h.id)}" data-pass="${h.status==="confirmed"?1:0}">Approve…</button>`:""}</td></tr>`}).join("")||'<tr><td colspan="7" class="empty">No hypothesis registered.</td></tr>'}</table>
   ${(S.nox||{}).version&&(S.nox||{}).version!=="v000"?`<p class="note">Active NOX configuration ${esc(S.nox.version)} (parent ${esc(S.nox.parent)}) <button class="b sm" id="shg-rb">Roll back…</button></p>`:""}
   <p class="note">Approved NOX configurations are versioned and reversible. The PERCIVAL Decision Engine still trains on its built-in measurement set; reading the
   approved configuration during training is the next integration step (not yet active).</p>
   <details style="margin-top:10px"><summary class="note">Older demonstration trials (SYNTHETIC random cohort - never evidence)</summary><p class="note">${esc(S.legacy_note)}</p>
    <button class="b sm" id="shd-run">Run a synthetic demonstration trial</button></details></div>`;
  $("#shg-reg").onclick=async()=>{const r=await api("/api/percival/shadow_gov_register",{target:"NOX",kind:"nox_measurement",variables:[$("#shg-var").value],rationale:$("#shg-why").value,by:arWho()});toast(r.ok?`registered ${esc(r.hypothesis.id)}`:esc(r.error),!r.ok);pvShadow(el,v)};
  el.querySelectorAll("[data-shg]").forEach(b=>b.onclick=async()=>{const op=b.dataset.shg,id=b.dataset.id;let body={id};
    if(op==="approve"){const by=(prompt("Approve "+id+" - your name (the approver):",arWho())||"").trim();if(!by)return;const why=(prompt("Reason:")||"").trim();if(!why)return;
      const c=prompt("Type exactly: APPROVE COMPONENT CHANGE");if(c===null)return;body=Object.assign(body,{by,reason:why,confirm:c.trim(),override:b.dataset.pass!=="1"})}
    b.disabled=true;const r=await api("/api/percival/shadow_gov_"+op,body);toast(r.ok?`${id}: ${esc(op)} done`:esc(r.error),!r.ok);pvShadow(el,v)});
  $("#shg-rb")&&($("#shg-rb").onclick=async()=>{const by=(prompt("Roll back NOX - your name:",arWho())||"").trim();if(!by)return;const why=(prompt("Reason:")||"").trim();if(!why)return;
    const c=prompt("Type exactly: APPROVE COMPONENT CHANGE");if(c===null)return;const r=await api("/api/percival/shadow_gov_rollback",{component:"NOX",by,reason:why,confirm:c.trim()});toast(r.ok?"rolled back":esc(r.error),!r.ok);pvShadow(el,v)});
  $("#shd-run").onclick=async()=>{const r=await api("/api/percival/shadow_run",{target:"ALBUS",hypothesis:"synthetic demonstration",config:{formula:"formula_adaptive_subpial",threshold:0.45}});
    toast(r.ok?`Synthetic demonstration finished (not evidence): AUC ${g3((r.metrics_experimental||{}).auc)}`:esc(r.error),!r.ok)}}
