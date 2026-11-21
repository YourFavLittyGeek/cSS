// unified_view.js - "Unified (experimental)" tab of the cSS Pipeline app (screens A and C). EXPERIMENTAL, research only.
// Talks to /api/u/* (app/unified_gui.py, app/gui_protocol.py). Never writes reader files; no held-out evaluation from here.
const U={tab:"flow",step:"selection",study:"",cand:null,timer:null,seeds:3};
const STEPS=[["selection","0","Study selection"],["audit","1","Cohort audit"],["features","2","Features"],["reliability","3","Reliability"],["train","4","Train & validate"],
  ["freeze","5","Model & freeze"],["candidates","6","Candidates"],["robustness","7","Robustness"],["export","8","Export"]];
const ST_COL={done:"var(--ok)",completed:"var(--ok)",review:"var(--warn)",partial:"var(--warn)",running:"var(--acc)",failed:"var(--bad)",todo:"var(--line)"};
const ST_TXT={done:"done",completed:"done",review:"review flags",partial:"partial",running:"running…",failed:"FAILED",todo:"to do"};
const f2=(x,n=2)=>x===null||x===undefined||x===""?"–":(typeof x==="number"?x.toFixed(n):esc(x));
const relPill=s=>`<span class="pill" style="border-color:${s==="reliable"?"var(--ok)":s==="unreliable"?"var(--warn)":"var(--line)"};color:${s==="reliable"?"var(--ok)":s==="unreliable"?"var(--warn)":"var(--mut)"}">${esc(s)}</span>`;
const catPill=c=>{const m={css_compatible:["cSS-compatible / prioritized","var(--ok)"],uncertain:["Uncertain / requires review","var(--warn)"],alternative_high_confidence:["High-confidence alternative","#b48cff"]}[c]||[c,"var(--mut)"];
  return `<span class="pill" style="border-color:${m[1]};color:${m[1]};font-weight:700">${esc(m[0])}</span>`};
const PN={x1_vessel_continuity_mm:"x1 vessel continuity",x2_core_contrast_nu:"x2 dark-core contrast",x3_pial_distance_mm:"x3 distance to surface",x4_sulcal_alignment:"x4 surface conformity",x5_extracranial_mm:"x5 extracranial continuation"};

// rc4 UI fix: the page used to be rebuilt every 2 s while a job ran (scroll jumped to the top, opened sections closed). Now a poll only
// updates job boxes and step-card colours in place; the page is rebuilt only when a job ends or a step changes state, and even then
// the scroll position and the opened <details> sections are kept.
const uSig=st=>JSON.stringify([Object.entries(st.jobs).map(([k,j])=>[k,j.status]),st.steps,st.patients.map(p=>p.unified)]);
async function uniPoll(v){clearTimeout(U.timer);if(V!=="uni"||$("#shade").style.display==="flex"){U.timer=setTimeout(()=>uniPoll(v),2000);return}
  const st=await api("/api/u/state");
  if(uSig(st)!==U.sig){U.st=st;return uniView(v,true)}
  U.st=st;document.querySelectorAll("[data-jobbox]").forEach(e=>{const n=e.dataset.jobbox;e.innerHTML=jobBoxInner(n,st.jobs[n]);bindJobs(e)});
  U.timer=setTimeout(()=>uniPoll(v),2000)}
async function uniView(v,keep){
  clearTimeout(U.timer);const y=window.scrollY,openD=[...document.querySelectorAll("#u-step details")].map(d=>d.open);
  const st=await api("/api/u/state");U.st=st;U.sig=uSig(st);
  const banner=st.synthetic?`<div class="card" style="border-color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,transparent)"><b class="bad">SYNTHETIC DEMO</b> — SYN studies only. Nothing on this page is a result.</div>`:"";
  v.innerHTML=`${banner}<div class="row" style="justify-content:space-between"><div><b style="font-size:17px">Unified cSS scoring</b> <span class="pill warn">EXPERIMENTAL · research only · not a diagnosis</span>
    <span class="pill ok" id="u-supp">suppression: ${st.suppression?"ON":"OFF"}</span> <span class="pill" title="${esc(st.heldout.why)}">held-out: locked</span> <button class="b sm" onclick="typeof openCalls==='function'&&openCalls()" title="which reviewer's calls are used as training labels">Reviewer calls used for training</button></div>
    <div class="row"><span class="mut">Run after each patient</span>${seg("u-en",[["0","Off"],["1","On"]],st.enabled?"1":"0")}
    ${seg("u-tab",[["flow","Workflow"],["tests","Test protocol"]],U.tab)}</div></div><div id="u-body"></div>`;
  bindSeg("u-en",async x=>{if(x==="1"){const r=await ask("Turn on the unified score after each patient?","After a patient finishes and its original results are saved, the experimental unified score runs in the background (15-minute limit). It never changes the detector output, reader files or the original export.",[["no","Cancel"],["yes","Turn on","pri"]]);if(r!=="yes")return render()}
    await api("/api/u/enable",{on:x==="1"});toast(`unified score after each patient: ${x==="1"?"on":"off"}`);render()});
  bindSeg("u-tab",x=>{U.tab=x;render()});
  if(U.tab==="tests")return testsView($("#u-body"));
  const cards=STEPS.map(([k,n,t])=>{const s=st.steps[k]||"todo";return `<div class="card" data-step="${k}" style="flex:1;min-width:104px;padding:9px 10px;cursor:pointer;margin:0;border:2px solid ${U.step===k?"var(--acc)":ST_COL[s]}">
     <b style="color:${ST_COL[s]};font-size:16px">${n}</b> <b style="font-size:13px">${t}</b><div class="note" style="color:${ST_COL[s]}">${ST_TXT[s]||s}</div></div>`}).join("");
  $("#u-body").innerHTML=`<div class="row" style="gap:6px;align-items:stretch;flex-wrap:nowrap;overflow-x:auto">${cards}</div>
    <div class="row" style="align-items:flex-start;gap:12px;margin-top:12px"><div class="card" style="width:330px;flex:none">${cohortPanel(st)}</div><div class="card" style="flex:1;min-width:520px" id="u-step"></div></div>`;
  document.querySelectorAll("[data-step]").forEach(e=>e.onclick=()=>{U.step=e.dataset.step;uniView(v)});
  await stepView($("#u-step"));
  if(keep){document.querySelectorAll("#u-step details").forEach((d,i)=>{if(openD[i])d.open=true});window.scrollTo(0,y)}
  if(Object.values(st.jobs).some(j=>j.status==="running")||st.patients.some(p=>["pending","running"].includes(p.unified)))U.timer=setTimeout(()=>uniPoll(v),2000)}

function cohortPanel(st){const chip=(s,c)=>`<span class="pill" style="border-color:${c};margin:2px" title="${s.features?`features: ${s.n} candidates`:"no features yet"}${s.scored?" · scored":""}">${esc(s.study)}${s.features?" ✓":""}</span>`;
  const dev=st.studies.filter(s=>s.role==="development"),ho=st.studies.filter(s=>s.role==="held-out");
  return `<h2>Cohort</h2><div class="note">${st.synthetic?"synthetic manifest":"manifest cohort_manifest_RECONCILED.csv (M studies only)"}</div>
   <div style="margin-top:8px"><b class="ok">Development</b> <span class="note">training + nested validation (${dev.length})</span><div>${dev.map(s=>chip(s,"var(--ok)")).join("")}</div></div>
   <div style="margin-top:8px"><b class="warn">Held-out</b> <span class="note">labels locked (${ho.length})</span><div>${ho.map(s=>chip(s,"var(--warn)")).join("")}</div></div>
   <div class="note" style="margin-top:8px">✓ = features extracted. Held-out studies are scored for display only; their labels are never read here (label reads logged: ${st.heldout_reads} held-out).</div>
   ${st.audit_summary?`<div class="tip">Last audit ${esc(st.audit_summary.time)} · checks ${st.audit_summary.checks_ok?'<span class="ok">ok</span>':'<span class="bad">problem</span>'} · ${st.audit_summary.problems} notes</div>`:'<div class="tip warn">No cohort audit yet</div>'}`}

function jobBox(name,j){return `<div data-jobbox="${name}">${jobBoxInner(name,j)}</div>`}
function jobBoxInner(name,j){if(!j||j.status==="idle")return "";const pct=Math.round(100*(j.progress||0));
  return `<div class="tip"><div class="row"><b>${esc(name)}</b> <span style="color:${ST_COL[j.status]||"var(--mut)"}">${esc(j.status)}</span>
   ${j.status==="running"?`<div class="bar" style="flex:1"><i style="width:${Math.max(pct,3)}%"></i></div><button class="b" data-stop="${name}">Stop</button>`:""}
   <button class="b" data-log="${name}">Log</button></div>${j.error?`<div class="err" style="white-space:pre-wrap">${esc(j.error)}</div>`:""}</div>`}
function bindJobs(el){el.querySelectorAll("[data-stop]").forEach(b=>b.onclick=async()=>{await api("/api/u/stop",{job:b.dataset.stop});toast("stopping…")});
  el.querySelectorAll("[data-log]").forEach(b=>b.onclick=async()=>{const r=await api("/api/u/log?job="+b.dataset.log);
    $("#dlg").innerHTML=`<h2>Log · ${esc(b.dataset.log)}</h2><pre style="max-height:50vh;overflow:auto;font-size:11px;white-space:pre-wrap">${esc((r.log||[]).join("\n")||"(empty)")}</pre><div class="acts"><button class="b pri">Close</button></div>`;
    $("#shade").style.display="flex";$("#dlg").querySelector("button").onclick=()=>$("#shade").style.display="none"})}
async function run(op,body,msg){const r=await api("/api/u/"+op,body||{});if(r.ok===false)toast(esc(r.error),1);else if(msg)toast(msg);render();return r}

async function stepView(el){const st=U.st,J=st.jobs,k=U.step;
  if(k==="selection")return selView(el);
  if(k==="audit"){const a=await api("/api/u/audit");
    el.innerHTML=`<h2>1 · Cohort audit and study eligibility</h2><div class="row"><button class="b pri" id="go">Run cohort audit</button><span class="note">read-only: manifest, files present, registration state, duplicates</span></div>${jobBox("audit",J.audit)}
     ${a.available===false?'<p class="mut">Not run yet.</p>':`<div class="row note">${a.n_identifiers} identifiers · ${a.studies.length} included · ${a.n_excluded} excluded · manifest ${esc(a.manifest_sha)}</div>
     <table><tr><th>Check</th><th></th></tr>${a.checks.map(([n,o])=>`<tr><td>${esc(n)}</td><td>${o?'<span class="ok">✔</span>':'<span class="bad">✘</span>'}</td></tr>`).join("")}</table>
     ${a.problems.length?`<div class="tip warn">${a.problems.map(esc).join("<br>")}</div>`:""}
     <table class="fix" style="margin-top:8px"><tr><th>Study</th><th>Role</th><th>Processed</th><th>Registration</th><th>Raw SWI</th><th>Vessel map</th><th>Note</th></tr>
     ${a.studies.map(s=>`<tr><td>${esc(s.study)}</td><td>${esc(s.role)}</td><td>${s.processed?"✔":'<span class="warn">not yet</span>'}</td><td class="${s.registration==="ok"?"ok":["unreliable","swi_only"].includes(s.registration)?"bad":"warn"}">${esc(s.registration)}${s.label_shift_mm!=null?` (${f2(s.label_shift_mm)} mm)`:""}</td><td>${s.raw_swi?"✔":"–"}</td><td>${s.vessels?"✔":"–"}</td><td class="note">${esc(s.note)}</td></tr>`).join("")}</table>
     <details style="margin-top:8px"><summary class="mut">Excluded identifiers (${a.excluded.length}), each with its reason</summary><table>${a.excluded.map(e=>`<tr><td>${esc(e.study)}</td><td class="note">${esc(e.reason)}</td></tr>`).join("")}</table></details>`}`;
    el.querySelector("#go").onclick=()=>run("audit",{},"cohort audit started");bindJobs(el);return}
  if(k==="features"){el.innerHTML=`<h2>2 · Feature extraction</h2><div class="row"><button class="b pri" id="all">Extract all included studies</button><button class="b" id="miss">Only missing</button>
     <span class="note">features, dark-core decomposition, detectors and 16 perturbations per candidate; no labels are read</span></div>${jobBox("extract",J.extract)}
     <table style="margin-top:8px"><tr><th>Study</th><th>Role</th><th>Features</th><th>Candidates</th><th>Unified report</th></tr>${st.studies.map(s=>`<tr><td>${esc(s.study)}</td><td>${esc(s.role)}</td><td>${s.features?'<span class="ok">✔</span>':'<span class="mut">–</span>'}</td><td>${s.n??"–"}</td><td>${s.scored?"✔":"–"}</td></tr>`).join("")}</table>`;
    el.querySelector("#all").onclick=()=>run("extract",{which:"all"},"feature extraction started");el.querySelector("#miss").onclick=()=>run("extract",{which:"missing"},"extraction of missing studies started");bindJobs(el);return}
  if(k==="reliability"){const R=await api("/api/u/reliability");const ks=Object.keys(PN);
    el.innerHTML=`<h2>3 · Feature reliability</h2><p class="note">An unreliable or unavailable feature contributes <b>nothing</b> to the score — it is never treated as evidence against cSS.</p>
     ${R.per_study.length?`<table><tr><th>Study</th><th>n</th><th>Registration</th>${ks.map(x=>`<th>${PN[x]}</th>`).join("")}</tr>${R.per_study.map(r=>`<tr><td>${esc(r.study)}</td><td>${r.n}</td><td>${esc(r.registration)}</td>${ks.map(x=>`<td><span class="ok">${r[x].reliable}</span> / <span class="warn">${r[x].unreliable}</span> / <span class="mut">${r[x].unavailable}</span></td>`).join("")}</tr>`).join("")}</table>
     <div class="note">reliable / unreliable / unavailable candidates</div>
     <h2 style="margin-top:12px">Why features are not reliable</h2>${ks.map(x=>`<div><b>${PN[x]}</b>: ${Object.entries(R.reasons[x]).map(([w,n])=>`${esc(w)} (${n})`).join("; ")||'<span class="mut">none</span>'}</div>`).join("")}
     <details style="margin-top:8px"><summary class="mut">Flagged measurements (${R.flagged.length})</summary><table>${R.flagged.slice(0,300).map(f=>`<tr><td>${esc(f.study)} #${f.cand}</td><td>${PN[f.feature]}</td><td>${relPill(f.status)}</td><td class="note">${esc(f.why)}</td></tr>`).join("")}</table></details>`:'<p class="mut">No features extracted yet (step 2).</p>'}`;return}
  if(k==="train"){const T=await api("/api/u/validation");const G=(await api("/api/sel/status")).gate||{open:true};
    el.innerHTML=`<h2>4 · Train and validate on the development studies</h2><div class="row"><button class="b pri" id="tr">Train (development only)</button>
     <span class="note">ridge logistic regression on five predictors · nested leave-one-patient-out · calibration fitted inside each outer fold · held-out labels never read · training does NOT freeze</span></div>${jobBox("train",J.train)}
     ${T.available?valHtml(T):'<p class="mut">No validation yet.</p>'}`;
    if(!G.open){const b=el.querySelector("#tr");b.disabled=true;b.insertAdjacentHTML("afterend",' <span class="warn">training gate is CLOSED — open it in step 0 (Study selection)</span>')}
    el.querySelector("#tr").onclick=async()=>{const r=await ask("Train the unified model?","Uses the reader labels of the <b>development</b> studies only (every label read is logged). Takes minutes to hours depending on the number of candidates. The trained model is not frozen; freezing is step 5.",[["no","Cancel"],["yes","Train","pri"]]);if(r==="yes")run("train",{},"training started")};bindJobs(el);return}
  if(k==="freeze"){const M=st.model;
    el.innerHTML=`<h2>5 · Model and freeze</h2><table><tr><td class="lab">Trained model</td><td>${M.trained?`<code>${esc(M.trained_hash.slice(0,16))}</code> · ${esc(M.trained_at)}`:'<span class="mut">none</span>'}</td></tr>
     <tr><td class="lab">Frozen model</td><td>${M.frozen?`<code>${esc(M.frozen_hash.slice(0,16))}</code> · frozen ${esc(M.frozen_at)}`:'<span class="warn">not frozen</span>'}${M.stale_frozen?' <span class="bad">— differs from the latest trained model</span>':""}</td></tr>
     <tr><td class="lab">Versions</td><td>${esc(M.model_version||"–")} · ${esc(M.feature_version||"–")}</td></tr><tr><td class="lab">Predictors</td><td>${(M.predictors||[]).map(p=>PN[p]).join(", ")||"–"}</td></tr>
     <tr><td class="lab">Ridge λ / effective df</td><td>${f2(M.lam,3)} / ${f2(M.edf)}</td></tr><tr><td class="lab">Probability output</td><td>${M.trained?(M.probability_output?'<span class="ok">allowed</span>':'<span class="warn">WITHHELD — raw score and feature profile only</span>'):"–"}</td></tr></table>
     <div class="row" style="margin-top:10px"><button class="b pri" id="fz" ${M.trained?"":"disabled"}>Freeze model…</button><span class="note">freezing fixes the model and its hash; candidates are then scored with this model</span></div>
     <div class="tip"><b>Held-out evaluation: locked.</b> ${esc(st.heldout.why)}. It is <b>not available from the app</b>: it needs a frozen model and a separate written authorization from you, outside the app. A hash or a confirmation here is not enough.</div>`;
    el.querySelector("#fz").onclick=async()=>{$("#dlg").innerHTML=`<h2 class="warn">⚠ Freeze the trained model?</h2><p>Model <code>${esc(M.trained_hash.slice(0,16))}</code>. Type <b>FREEZE</b> to confirm.</p><input id="fzt" autocomplete="off"><div class="acts"><button class="b" data-v="no">Cancel</button><button class="b pri" data-v="yes">Freeze</button></div>`;
      $("#shade").style.display="flex";$("#dlg").querySelectorAll("button").forEach(b=>b.onclick=async()=>{const t=$("#fzt").value;$("#shade").style.display="none";if(b.dataset.v==="yes"){const r=await api("/api/u/freeze",{confirm:t});if(r.ok===false)toast(esc(r.error),1);else toast("model frozen "+esc(r.model_hash.slice(0,16)));render()}})};return}
  if(k==="candidates")return candView(el);
  if(k==="robustness"){const R=await api("/api/u/robustness");
    el.innerHTML=`<h2>7 · Robustness</h2><h3 style="margin:6px 0">Synthetic adversarial suite <span class="note">(synthetic scenes only — never part of the M cohort)</span></h3>
     <div class="row"><span class="mut">Seeds per scene</span><select id="sd">${[1,3,5].map(n=>`<option ${n===U.seeds?"selected":""}>${n}</option>`).join("")}</select><button class="b pri" id="rb">Run synthetic suite</button><span class="note">critical failure = a genuine cSS scene called a high-confidence alternative</span></div>${jobBox("robustness",J.robustness)}
     ${R.available===false?'<p class="mut">Not run yet.</p>':`<div class="${R.critical.length?"bad":"ok"}"><b>${R.critical.length?`CRITICAL FAILURES: ${esc(JSON.stringify(R.critical))}`:"0 critical failures"}</b> · ${R.seeds} seeds per scene</div>
     <table><tr><th>Scene</th><th>Outcomes</th></tr>${Object.entries(R.table).map(([n,c])=>`<tr><td>${esc(n)}</td><td>${Object.entries(c).map(([k,v])=>`${esc(k)}: ${v}`).join(" · ")}</td></tr>`).join("")}</table>`}
     <h3 style="margin:12px 0 6px">Perturbation stability of real candidates</h3><p class="note">16 perturbations per candidate (erosion / dilation, threshold ±0.25, registration ±1 voxel x/y/z, vessel map ±1 voxel x/y/z) are computed during feature extraction. Open a candidate in step 6 to see its table. Instability only adds uncertainty.</p>`;
    el.querySelector("#sd").onchange=e=>U.seeds=+e.target.value;el.querySelector("#rb").onclick=()=>run("robustness",{seeds:U.seeds},"synthetic suite started");bindJobs(el);return}
  if(k==="export"){el.innerHTML=`<h2>8 · Reports and exports</h2><div class="row"><button class="b pri" id="ex">Export unified results (Excel)</button><button class="b" id="op">Open results folder</button></div>
     <p class="note">Sheets: about (model, estimate type, held-out status), candidates (category, reasons, five predictors with reliability, detectors), coefficients (cross-validation), cross-validation metrics, unreliable features. The cohort report (markdown) is copied beside it. The original results workbook is unchanged and still written after every patient.</p><div id="exr"></div>`;
    el.querySelector("#ex").onclick=async()=>{const r=await api("/api/u/export",{});if(r.ok===false)toast(esc(r.error),1);else{el.querySelector("#exr").innerHTML=`<div class="tip ok">written: ${esc(r.path)} (${r.n_candidates} candidates)</div>`;toast("export written")}};
    el.querySelector("#op").onclick=()=>api("/api/open_results",{});return}}

function valHtml(T){const B=T.coefficient_stability||{},bins=T.reliability_bins||[];const W=260,H=200;
  const pts=bins.map(b=>`${20+b.p_mean*W},${H-10-b.observed*(H-30)}`).join(" ");
  const svg=`<svg width="${W+40}" height="${H+10}"><line x1="20" y1="${H-10}" x2="${20+W}" y2="20" stroke="#666" stroke-dasharray="4"/><polyline points="${pts}" fill="none" stroke="var(--acc)" stroke-width="2"/>${bins.map(b=>`<circle cx="${20+b.p_mean*W}" cy="${H-10-b.observed*(H-30)}" r="4" fill="var(--acc)"><title>predicted ${b.p_mean.toFixed(2)}, observed ${b.observed.toFixed(2)}, n ${b.n}</title></circle>`).join("")}<text x="20" y="${H+8}" fill="#999" font-size="10">predicted →</text><text x="2" y="14" fill="#999" font-size="10">observed</text></svg>`;
  const mx=Math.max(0.01,...Object.values(B.coef_mean||{}).map(Math.abs));
  return `<div class="tip"><b>Estimate type: CROSS-VALIDATION</b> (nested leave-one-patient-out on ${T.n_patients} development patients; every prediction out-of-fold). Not an independent held-out result.</div>
   <div class="row" style="align-items:flex-start;gap:16px"><div><h3 style="margin:6px 0">Calibration (out-of-fold)</h3>${svg}<div class="note">slope ${f2(T.calibration_slope)} · intercept ${f2(T.calibration_intercept)} · Brier ${f2(T.outer_brier,3)}</div></div>
   <div style="flex:1;min-width:320px"><h3 style="margin:6px 0">Discrimination</h3><div>AUC ${f2(T.outer_auc_calibrated)} <span class="note">95 % CI ${T.outer_auc_ci?T.outer_auc_ci.map(x=>x.toFixed(2)).join("–"):"–"} (patient bootstrap)</span></div>
    <div class="note">${T.n_candidates} labelled candidates, ${T.n_cSS} cSS · at the ordering cut ${f2(T.ordering_cut)}: sensitivity ${f2(T.candidate_sensitivity)}, specificity ${f2(T.candidate_specificity)}, patient sensitivity ${f2(T.patient_sensitivity)}, FP / patient ${f2(T.fp_per_patient)}</div>
    <h3 style="margin:10px 0 6px">Coefficients across outer folds (standardised)</h3><table>${(T.predictors||[]).map(p=>{const m=B.coef_mean[p],sa=B.sign_agreement[p];const w=Math.round(80*Math.abs(m)/mx);
      return `<tr><td>${PN[p]}</td><td style="width:180px"><div style="display:flex;justify-content:center"><div style="width:90px;display:flex;justify-content:flex-end">${m<0?`<i style="display:block;height:10px;width:${w}px;background:var(--bad)"></i>`:""}</div><div style="width:90px">${m>0?`<i style="display:block;height:10px;width:${w}px;background:var(--ok)"></i>`:""}</div></div></td><td>${f2(m)} ± ${f2(B.coef_sd[p])}</td><td class="${sa>=0.8?"ok":"warn"}">signs ${Math.round(100*sa)} %</td></tr>`}).join("")}</table>
    <div class="note">fallback: ${(T.fallback_log||[]).length?T.fallback_log.map(esc).join("; "):"none"}${T.penalty_at_grid_boundary?' · <span class="warn">penalty at the edge of the grid in some folds</span>':""}</div></div></div>
   <h3 style="margin:10px 0 6px">Result gate</h3><table>${T.gate.map(g=>`<tr><td>${g.ok?'<span class="ok">✔</span>':'<span class="warn">✘</span>'}</td><td>${esc(g.rule)}</td><td class="note">${f2(g.value)}</td></tr>`).join("")}</table>
   <div class="note"><b>x4 surface conformity</b> measures how the candidate's geometry relates to the brain surface (a line: tangent to the surface; a sheet: lying in the surface / sulcal wall). It is <b>not</b> alignment along a sulcus: a line running along a sulcus and one crossing a gyral crown can both score 1. The sulcal-axis measure (x4b) is a separate exploratory descriptor and is not in the model. Unavailable without T1 anatomy; unreliable with label shift &gt; 0.5 mm, SWI-only anatomy, a blob-like shape or incoherent surface normals. Internal key: x4_sulcal_alignment (kept for file compatibility). See docs/FEATURE_DICTIONARY_v514.md.</div>
   <div class="${T.probability_output?"ok":"warn"}"><b>→ probability output ${T.probability_output?"allowed":"WITHHELD (raw score and feature profile only)"}</b></div>
   <details style="margin-top:8px"><summary class="mut">v5.10 confidence model — separate, not comparable</summary><p class="note">v5.10 was fitted on these same development calls, so its AUC on them (${f2(T.v510_auc_same_candidates)}) is an <b>in-sample</b> figure and is not shown beside the cross-validation estimate. A fair comparison is only possible on the independent held-out cohort.</p></details>`}

async function candView(el){const st=U.st;const opts=[...new Set(st.studies.filter(s=>s.scored).map(s=>s.study).concat(st.patients.filter(p=>p.unified==="completed").map(p=>p.code)))];
  if(!U.study&&opts.length)U.study=opts[0];
  const C=U.study?(await api("/api/u/candidates?study="+encodeURIComponent(U.study))).candidates:[];
  const pts=st.patients.filter(p=>p.status==="done");
  el.innerHTML=`<h2>6 · Candidate-level results</h2><div class="row"><span class="mut">Study</span><select id="cs">${opts.map(o=>`<option ${o===U.study?"selected":""}>${esc(o)}</option>`).join("")||"<option>(none scored)</option>"}</select>
    <button class="b pri" id="sa" ${st.model.frozen?"":"disabled"} title="${st.model.frozen?"":"freeze a model first (step 5)"}">Score all extracted studies</button>
    <span class="mut">Patient</span><select id="pp">${pts.map(p=>`<option>${esc(p.code)}</option>`).join("")}</select><button class="b" id="sp">Score patient</button></div>${jobBox("score",st.jobs.score)}
    <table class="fix"><tr><th style="width:52px">#</th><th>Category</th><th style="width:90px">Score</th><th>Reliability (x1…x5)</th><th>Alternative detectors</th></tr>
    ${C.map(r=>`<tr data-c="${r.cand_id}" style="cursor:pointer;${U.cand==r.cand_id?"background:var(--in)":""}"><td>${r.cand_id}</td><td>${catPill(r.category)}</td><td>${r.probability!=null?f2(r.probability)+" p":r.raw_score!=null?f2(r.raw_score)+" raw":"–"}</td>
      <td>${Object.values(r.predictors).map(p=>`<span title="${esc(p.status)}" style="color:${p.status==="reliable"?"var(--ok)":p.status==="unreliable"?"var(--warn)":"var(--mut)"}">●</span>`).join(" ")}</td>
      <td class="note">${(r.alternative_detectors||[]).map(d=>`${esc(d.detector.replace("_"," "))}: ${esc(d.status)}`).join(" · ")}</td></tr>`).join("")||'<tr><td colspan="5" class="mut">No unified report for this study yet.</td></tr>'}</table><div id="cd"></div>`;
  el.querySelector("#cs").onchange=e=>{U.study=e.target.value;U.cand=null;candView(el)};
  el.querySelector("#sa").onclick=()=>run("score",{},"scoring started");
  el.querySelector("#sp").onclick=()=>{const c=el.querySelector("#pp").value;if(c)run("score_patient",{code:c},`${c}: unified step queued (background)`)};
  el.querySelectorAll("[data-c]").forEach(t=>t.onclick=()=>{U.cand=+t.dataset.c;candView(el)});
  if(U.cand!=null){const r=C.find(x=>x.cand_id==U.cand);const P=await api(`/api/u/perturb?study=${encodeURIComponent(U.study)}&cand=${U.cand}`);el.querySelector("#cd").innerHTML=candDetail(r,P);
    const o=el.querySelector("#open3d");if(o)o.onclick=()=>api("/api/review",{codes:[U.study],start:U.study,cand:U.cand}).then(x=>{if(x&&x.url&&!x.opened)window.open(x.url+(x.url.includes("?")?"&":"?")+"study="+encodeURIComponent(U.study)+"&cand="+U.cand,"review");else if(x&&x.error)toast(esc(x.error),1)})}bindJobs(el)}

function candDetail(r,P){if(!r)return "";const con=r.contributions||{};
  return `<div class="card" style="margin-top:10px"><h2>Candidate #${r.cand_id} · ${catPill(r.category)}</h2><div class="note">${(r.category_reasons||[]).map(esc).join("; ")}</div>
   <div style="margin:6px 0">${r.probability!=null?`probability ${f2(r.probability)}`:r.raw_score!=null?`raw score ${f2(r.raw_score)} <span class="warn">(not a probability: ${esc(r.score_note||"")})</span>`:`<span class="warn">${esc(r.score_note||"no score")}</span>`}</div>
   <table><tr><th>Predictor</th><th>Value</th><th>Reliability</th><th>Contribution (log-odds)</th></tr>${Object.entries(r.predictors).map(([k,p])=>`<tr><td>${PN[k]}</td><td>${p.value==null?"–":f2(p.value)} ${esc(p.unit)}</td><td>${relPill(p.status)} <span class="note">${esc((p.reasons||[]).join("; "))}</span></td><td>${con[k]?(con[k].imputed?'<span class="mut">0 (no evidence)</span>':f2(con[k].contribution)):"–"}</td></tr>`).join("")}</table>
   <h3 style="margin:10px 0 6px">Alternative explanations (independent of the cSS score)</h3><table>${(r.alternative_detectors||[]).map(d=>`<tr><td>${esc(d.detector)}</td><td><b>${esc(d.status)}</b></td><td class="note">for: ${esc(JSON.stringify(d.support))}<br>against: ${esc((d.against||[]).join("; ")||"–")}<br>unresolved: ${esc((d.unresolved||[]).join("; ")||"–")}</td></tr>`).join("")}</table>
   <div style="margin-top:8px"><b>Protective conditions:</b> ${(r.protective_flags||[]).map(esc).join("; ")||'<span class="mut">none</span>'}</div>
   <div><b>Perturbation stability:</b> ${r.stability?`${r.stability.unstable?'<span class="warn">unstable</span>':'<span class="ok">stable</span>'} · score range ${r.stability.score_range?r.stability.score_range.map(x=>x.toFixed(2)).join("–"):"–"} · core Jaccard ${f2(r.stability.core_jaccard_median)}`:"–"}</div>
   ${P.available?`<details><summary class="mut">Perturbation table (${P.rows.length})</summary><table><tr><th>Perturbation</th>${Object.keys(PN).map(k=>`<th>${PN[k].split(" ")[0]}</th>`).join("")}<th>core Jaccard</th></tr>${P.rows.map(x=>`<tr><td>${esc(x.perturbation)}</td>${Object.keys(PN).map(k=>`<td class="${x[k+"_unstable"]?"warn":""}">${x[k]==null?"–":f2(x[k])}</td>`).join("")}<td>${f2(x.core_jaccard)}</td></tr>`).join("")}</table></details>`:""}
   <div class="note">Dark core (experimental representation, not ground truth): ${r.decomposition?`${r.decomposition.core_voxels} voxels in ${r.decomposition.core_pieces} piece(s), unstable ${f2(r.decomposition.core_unstable_frac)}`:"–"}</div>
   <div class="row"><button class="b pri" id="open3d">Open in reviewer (3-D + layers)</button><span class="note">model ${esc((r.model_hash||"none").slice(0,12))} · ${esc(r.feature_version||"")}</span></div></div>`}

async function testsView(el){const P=await api("/api/u/protocol");const col={pass:"var(--ok)",fail:"var(--bad)","not run":"var(--mut)","n/a":"var(--mut)"};
  const row=i=>`<tr><td>${i.id}</td><td>${esc(i.name)}</td><td class="note">${esc(i.what)}</td><td style="color:${col[i.result]};font-weight:700">${esc(i.result)}</td><td class="note">${esc(i.note)}${i.time?` <span class="mut">(${esc(i.time)})</span>`:""}</td>
     <td>${i.kind==="manual"?`<button class="b" data-m="${i.id}" data-r="pass">Pass</button> <button class="b" data-m="${i.id}" data-r="fail">Fail</button>`:'<span class="mut">set by the app</span>'}</td></tr>`;
  const head='<tr><th style="width:52px">ID</th><th style="width:250px">Test</th><th>What is checked</th><th style="width:80px">Result</th><th>Evidence / note</th><th style="width:150px"></th></tr>';
  const A=P.items.filter(i=>i.kind==="auto"),Mn=P.items.filter(i=>i.kind==="manual");
  el.innerHTML=`<div class="card"><h2>Test protocol (screen C)</h2><div class="row"><button class="b pri" id="ra">Run automatic checks</button><button class="b" id="sv">Save test record (Excel)</button>
   <span class="note">Nothing here changes reader files or detector outputs.</span></div>
   <h3 style="margin:10px 0 4px">Automatic checks <span class="pill">AUTO</span> <span class="note">the app verifies these; results cannot be edited by hand</span></h3>
   <table class="fix">${head}${A.map(row).join("")}</table>
   <h3 style="margin:14px 0 4px">Manual checks <span class="pill warn">MANUAL — you must confirm</span> <span class="note">only you can pass these, by using the app; an automatic check never passes them (e.g. T5a only shows that the 3-D viewer's files are installed — T5 is whether the viewer actually works)</span></h3>
   <table class="fix">${head}${Mn.map(row).join("")}</table></div>`;
  el.querySelector("#ra").onclick=async()=>{toast("running automatic checks…");const r=await api("/api/u/protocol_run",{});if(r.ok===false)toast(esc(r.error),1);render()};
  el.querySelector("#sv").onclick=async()=>{const r=await api("/api/u/protocol_save",{});toast(r.ok===false?esc(r.error):"saved "+esc(r.path),r.ok===false)};
  el.querySelectorAll("[data-m]").forEach(b=>b.onclick=async()=>{let note="";if(b.dataset.r==="fail"){note=prompt("What failed?")||""}await api("/api/u/protocol_mark",{id:b.dataset.m,result:b.dataset.r,note});render()})}

// ---------------- step 0: study selection & training gate (v5.14.2-rc4, sketches v2 + v3)
U.pend={};U.selF="all";U.selChk=new Set();
const RL={train:["Train","#2e6b47"],test:["Test","#7a6418"],hold:["Hold","#245089"],exclude:["Excl","#4a4f5a"]};
const LBC={trained:"ok",stale:"bad",conflict:"bad",test:"warn",spent:"warn",hold:"",exclude:"mut",unread:"mut"};
function askText(title,label,def){return new Promise(res=>{$("#dlg").innerHTML=`<h2>${title}</h2><p class="note">${label}</p><input id="atx" style="width:100%" value="${esc(def||"")}"><div class="acts" style="margin-top:10px"><button class="b" data-v="no">Cancel</button><button class="b pri" data-v="ok">OK</button></div>`;
  $("#shade").style.display="flex";const i=$("#atx");i.focus();i.select();const done=v=>{$("#shade").style.display="none";res(v)};
  $("#dlg").querySelectorAll("button").forEach(b=>b.onclick=()=>done(b.dataset.v==="ok"?i.value.trim():null));i.onkeydown=e=>{if(e.key==="Enter")done(i.value.trim());if(e.key==="Escape")done(null)}})}
async function setRole(rows,ids,role,reasonDef){if(!ids.length)return;let reason="";
  if(role==="exclude"||role==="hold"){reason=await askText(role==="exclude"?"Exclude from training and test":"Hold (temporarily out of training)",`Reason for ${ids.join(", ")} (required, kept in the record)`,reasonDef||"");if(!reason)return}
  for(const id of ids){const r=rows.find(x=>x.study===id);const cur=(U.pend[id]||{}).role??r.role;if(cur===role&&!reason)continue;U.pend[id]={...(U.pend[id]||{}),role,...(reason?{reason}:{})};if(r.role===role&&!reason&&!U.pend[id].patient)delete U.pend[id]}}
async function selView(el){const R=await api("/api/sel/status");if(U.step!=="selection")return;const rows=R.rows,P=U.pend,G=R.gate,A=R.autotrain;
  const eff=r=>(P[r.study]&&P[r.study].role)||r.role;
  const vis=rows.filter(r=>U.selF==="all"||(U.selF==="reviewed"&&r.calls)||(U.selF==="unread"&&!r.calls)||(U.selF==="nofeat"&&!r.features)||(U.selF==="rec"&&r.recommendation));
  const coh=[...new Set(rows.map(r=>r.cohort).filter(Boolean))];
  const cnt=k=>rows.filter(r=>eff(r)===k).length;
  const pendN=Object.keys(P).length;
  el.innerHTML=`<h2>0 · Study selection &amp; training gate</h2>
   <div class="card" style="margin:0 0 10px"><div class="row"><b style="width:170px">Training gate</b>${seg("gate",[["1","OPEN"],["0","CLOSED"]],G.open?"1":"0")}<span class="note">${G.configured===false?"not configured yet — training allowed (legacy); close it to block training":`${G.open?"opened":"closed"} ${esc(G.at||"")} by ${esc(G.by||"")}`} · selection v${R.version??"— (manifest roles)"} · ${cnt("train")} train / ${cnt("test")} test / ${cnt("hold")} hold / ${cnt("exclude")} excluded</span></div>
    <div class="row"><b style="width:170px">Auto-train after review</b>${seg("autot",[["0","Off"],["1","On"]],A.on?"1":"0")}<span class="note">when a Train study's read is saved and at least</span><input id="athr" type="number" min="1" max="50" value="${A.threshold}" style="width:60px"><span class="note">new / changed Train studies are waiting (now: ${R.pending.length}) → training starts in the background, only if the gate is open. The result is a <b>trained model, never active</b>; freezing stays manual.</span></div></div>
   <div class="note" style="margin-bottom:6px"><b>Train</b> = learns from it · <b>Test</b> = held out to judge the model (labels locked) · <b>Hold</b> = temporarily out of training · <b>Excl</b> = takes no part (reason required) · ★ = recommended by the app, never applied by itself</div>
   <div class="row" style="flex-wrap:wrap;gap:6px"><span class="note">Show</span>${seg("self",[["all","all"],["reviewed","reviewed"],["unread","not reviewed"],["nofeat","features missing"],["rec","★ recommendations"]],U.selF)}
    <span class="note" style="margin-left:8px">Quick</span>${coh.length?`<select id="qcoh">${coh.map(c=>`<option>${esc(c)}</option>`).join("")}</select><button class="b" data-q="coh-train">cohort → Train</button><button class="b" data-q="coh-test">cohort → Test</button>`:""}<button class="b" data-q="m-train">M01–M26 → Train</button><button class="b" data-q="m-test">M27–M36 → Test</button><button class="b" data-q="rand">Random 20 % test (by patient)</button></div>
   <div class="row" style="gap:6px"><span class="note">Selected (${U.selChk.size})</span><button class="b" data-bt="train">Train</button><button class="b" data-bt="test">Test</button><button class="b" data-bt="hold">Hold</button><button class="b" data-bt="exclude">Exclude</button><button class="b" id="selnone">clear selection</button></div>
   <div style="overflow-x:auto"><table class="fix" style="min-width:900px"><colgroup><col style="width:30px"><col style="width:62px"><col style="width:90px"><col style="width:96px"><col style="width:220px"><col><col style="width:78px"></colgroup>
   <tr><th><input type="checkbox" id="selall"></th><th>Study</th><th>Cohort</th><th>Patient key</th><th>Role</th><th>Status · recommendation</th><th>Calls / cSS</th></tr>
   ${vis.map(r=>{const e=eff(r),rec=r.recommendation,ch=P[r.study];
     const segs=["train","test","hold","exclude"].map(k=>`<span data-rs="${r.study}" data-r="${k}" style="padding:2px 7px;cursor:pointer;font-size:11.5px;${e===k?`background:${RL[k][1]};color:#fff`:""}${rec&&rec.kind===k&&e!==k?";outline:2px dashed var(--warn);outline-offset:-2px":""}">${RL[k][0]}${rec&&rec.kind===k?" ★":""}</span>`).join("");
     return `<tr${ch?' style="background:color-mix(in srgb,var(--acc) 9%,transparent)"':""}><td><input type="checkbox" data-ck="${r.study}" ${U.selChk.has(r.study)?"checked":""}></td><td><b>${esc(r.study)}</b></td><td class="note">${esc(r.cohort||"—")}</td>
      <td><input data-pk="${r.study}" value="${esc((ch&&ch.patient!==undefined)?ch.patient:r.patient)}" placeholder="PT-…" style="width:84px;min-width:0;padding:2px 5px"></td>
      <td><span style="display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden">${segs}</span>${ch&&ch.role&&ch.role!==r.role?`<div class="note warn">${r.role} → ${ch.role} (pending)</div>`:""}</td>
      <td>${r.labels.map(l=>`<span class="pill ${LBC[l.kind]||""}" style="margin:1px;font-size:11px">${esc(l.text)}</span>${l.kind==="stale"?` <button class="b" data-stale="retrain" data-s="${r.study}" style="font-size:11px;padding:1px 7px">Retrain</button><button class="b" data-stale="hold" data-s="${r.study}" style="font-size:11px;padding:1px 7px">Hold</button><button class="b" data-stale="keep" data-s="${r.study}" style="font-size:11px;padding:1px 7px">Keep</button>`:""}`).join("")}
       ${rec&&e!==rec.kind?`<div class="note" style="margin-top:3px"><span class="pill warn" style="font-size:11px">★ ${rec.kind==="exclude"?"Exclude":"Hold"} recommended</span> ${esc(rec.why)} <button class="b" data-acc="${r.study}" data-k="${rec.kind}" style="font-size:11px;padding:1px 7px">Accept</button></div>`:""}</td>
      <td>${r.calls!=null?`${r.calls} / ${r.css}`:'<span class="mut">—</span>'}</td></tr>`}).join("")||'<tr><td colspan="7" class="mut">no studies</td></tr>'}</table></div>
   <div class="card" style="margin-top:10px;${pendN?"border-color:var(--acc)":""}"><h2>Pending changes (${pendN}) ${pendN?"— nothing has changed yet":""}</h2>
    ${pendN?`<table>${Object.entries(P).map(([k,v])=>{const r=rows.find(x=>x.study===k)||{};return `<tr><td style="width:70px"><b>${esc(k)}</b></td><td>${v.role&&v.role!==r.role?`${esc(r.role)} → <b>${esc(v.role)}</b>`:""}${v.patient!==undefined&&v.patient!==r.patient?` patient key → <b>${esc(v.patient||"(none)")}</b>`:""}${v.reason?` <span class="note">reason: ${esc(v.reason)}</span>`:""}${(r.labels||[]).some(l=>l.kind==="spent")&&v.role==="train"?' <span class="warn">spent test study: needs your confirmation</span>':""}</td><td style="width:60px"><button class="b" data-un="${k}" style="font-size:11px;padding:1px 7px">undo</button></td></tr>`}).join("")}</table>
    <div class="row"><input id="selnote" placeholder="note for this version (optional)" style="flex:1">${Object.keys(P).some(k=>(rows.find(x=>x.study===k)||{labels:[]}).labels.some(l=>l.kind==="spent")&&P[k].role==="train")?'<label><input type="checkbox" id="selspent"> I confirm moving spent test studies to Train</label>':""}</div>`:'<div class="note">Change roles above (one by one, ticked rows, or the quick buttons). Nothing is saved until you press Apply.</div>'}
    <div class="note" style="margin:6px 0">Apply checks: a reason for Hold / Exclude · the same patient may not be on both Train and Test · spent test studies need a confirmation. Every Apply creates a new selection version; older versions stay restorable; each trained model records the version it used.</div>
    <div class="row"><button class="b pri" id="selap" ${pendN?"":"disabled"}>Apply changes (creates v${(R.version||0)+1})</button><button class="b" id="seldis" ${pendN?"":"disabled"}>Discard</button><button class="b" id="selhist">History of versions…</button></div></div>`;
  const re=()=>selView(el);
  bindSeg("gate",async x=>{if(x==="1"&&await ask("Open the training gate?","While open, training can run (from the app, auto-train or the command line). Every open / close is logged.",[["no","Cancel"],["yes","Open","pri"]])!=="yes")return re();
    const r=await api("/api/sel/gate",{open:x==="1"});toast(r.ok?`training gate ${x==="1"?"opened":"closed"}`:esc(r.error),!r.ok);re()});
  bindSeg("autot",async x=>{await api("/api/sel/autotrain",{on:x==="1",threshold:+$("#athr").value||3});toast(`auto-train ${x==="1"?"on":"off"}`);re()});
  $("#athr").onchange=async e=>{await api("/api/sel/autotrain",{on:A.on,threshold:+e.target.value||3});toast("auto-train threshold saved")};
  bindSeg("self",x=>{U.selF=x;re()});
  el.querySelectorAll("[data-ck]").forEach(c=>c.onchange=()=>{c.checked?U.selChk.add(c.dataset.ck):U.selChk.delete(c.dataset.ck);re()});
  $("#selall").onchange=e=>{vis.forEach(r=>e.target.checked?U.selChk.add(r.study):U.selChk.delete(r.study));re()};$("#selnone").onclick=()=>{U.selChk.clear();re()};
  el.querySelectorAll("[data-rs]").forEach(b=>b.onclick=async()=>{await setRole(rows,[b.dataset.rs],b.dataset.r);re()});
  el.querySelectorAll("[data-bt]").forEach(b=>b.onclick=async()=>{await setRole(rows,[...U.selChk],b.dataset.bt);re()});
  el.querySelectorAll("[data-pk]").forEach(i=>i.onchange=()=>{const id=i.dataset.pk,r=rows.find(x=>x.study===id);U.pend[id]={...(U.pend[id]||{}),patient:i.value.trim()};if(U.pend[id].patient===r.patient&&!U.pend[id].role)delete U.pend[id];re()});
  el.querySelectorAll("[data-acc]").forEach(b=>b.onclick=async()=>{const r=rows.find(x=>x.study===b.dataset.acc);await setRole(rows,[r.study],b.dataset.k,r.recommendation.why.slice(0,120));re()});
  el.querySelectorAll("[data-un]").forEach(b=>b.onclick=()=>{delete U.pend[b.dataset.un];re()});
  el.querySelectorAll("[data-stale]").forEach(b=>b.onclick=async()=>{const s_=b.dataset.s,a=b.dataset.stale;
    if(a==="hold"){await setRole(rows,[s_],"hold","calls changed after training");return re()}
    if(a==="keep"){toast(`${s_}: kept — the existing model stays as it is (label stays until you retrain)`);const n=await api("/api/notif/list");const it=(n.items||[]).find(i=>i.key===`stale:${s_}`);if(it)await api("/api/notif/act",{id:it.id,op:"remove",minutes:1440});return}
    if(!G.open)return toast("the training gate is closed — open it first",1);
    if(await ask("Retrain with all current calls?","A new trained model (not active) is made from the Train studies of the current selection.",[["no","Cancel"],["yes","Retrain","pri"]])==="yes"){await api("/api/u/train",{});toast("training started")}});
  el.querySelectorAll("[data-q]").forEach(b=>b.onclick=async()=>{const q=b.dataset.q;const num=s=>+String(s).replace(/\D/g,"");
    let ids=[],role="";
    if(q==="coh-train"||q==="coh-test"){const c=$("#qcoh").value;ids=rows.filter(r=>r.cohort===c).map(r=>r.study);role=q==="coh-train"?"train":"test"}
    if(q==="m-train"){ids=rows.filter(r=>/^M\d+$/.test(r.study)&&num(r.study)>=1&&num(r.study)<=26).map(r=>r.study);role="train"}
    if(q==="m-test"){ids=rows.filter(r=>/^M\d+$/.test(r.study)&&num(r.study)>=27&&num(r.study)<=36).map(r=>r.study);role="test"}
    if(q==="rand"){const pool=rows.filter(r=>["train","test"].includes(eff(r)));const grp={};pool.forEach(r=>{const k=(P[r.study]&&P[r.study].patient)||r.patient||r.study;(grp[k]=grp[k]||[]).push(r.study)});
      const keys=Object.keys(grp).sort(()=>Math.random()-0.5);let n=0;const want=Math.max(1,Math.round(pool.length*0.2)),test=new Set();for(const k of keys){if(n>=want)break;grp[k].forEach(s=>test.add(s));n+=grp[k].length}
      await setRole(rows,pool.filter(r=>test.has(r.study)).map(r=>r.study),"test");await setRole(rows,pool.filter(r=>!test.has(r.study)).map(r=>r.study),"train");toast(`random split: ${test.size} test / ${pool.length-test.size} train (patients kept together)`);return re()}
    await setRole(rows,ids,role);re()});
  $("#seldis").onclick=()=>{U.pend={};re()};
  $("#selap").onclick=async()=>{const r=await api("/api/sel/apply",{changes:U.pend,note:($("#selnote")||{}).value||"",confirm_spent:!!($("#selspent")||{}).checked});
    if(r.ok){U.pend={};toast(`selection v${r.version} applied`);re()}else{$("#dlg").innerHTML=`<h2 class="warn">⚠ Not applied</h2><ul>${r.errors.map(e=>`<li>${esc(e)}</li>`).join("")}</ul><div class="acts"><button class="b pri">OK</button></div>`;$("#shade").style.display="flex";$("#dlg").querySelector("button").onclick=()=>$("#shade").style.display="none"}};
  $("#selhist").onclick=async()=>{const h=await api("/api/sel/versions");$("#dlg").innerHTML=`<h2>Selection versions</h2><div style="max-height:55vh;overflow:auto"><table>${h.versions.slice().reverse().map(v=>`<tr><td><b>v${v.version}</b>${v.version===h.current?" ★ current":""}</td><td class="note">${esc(v.at)} · ${esc(v.by)}${v.note?" · "+esc(v.note):""}<div>${Object.entries(v.changes||{}).map(([k,c])=>`${esc(k)} ${esc(c)}`).join("; ")||"—"}</div></td><td>${v.version!==h.current?`<button class="b" data-rv="${v.version}" style="font-size:11px">Restore</button>`:""}</td></tr>`).join("")||'<tr><td class="mut">no versions yet (manifest roles in force)</td></tr>'}</table></div><div class="acts"><button class="b pri" id="hclose">Close</button></div>`;
    $("#shade").style.display="flex";$("#hclose").onclick=()=>$("#shade").style.display="none";
    $("#dlg").querySelectorAll("[data-rv]").forEach(b=>b.onclick=async()=>{const r=await api("/api/sel/restore",{version:+b.dataset.rv});$("#shade").style.display="none";toast(r.ok?`restored as v${r.version}`:esc(r.errors.join("; ")),!r.ok);re()})}}
