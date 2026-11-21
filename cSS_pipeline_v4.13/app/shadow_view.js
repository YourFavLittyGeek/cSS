// shadow_view.js - "Shadow ML" screen: Unified Score engine in SHADOW MODE. EXPERIMENTAL, research only, not a diagnosis.
// Talks to /api/se/* (app/shadow_engine_gui.py). It only READS engine results; it never changes a study, a list, a call or an export.
// Three outputs are always shown apart: (1) the EXISTING deterministic score, (2) the EXPERIMENTAL ML output, (3) the EXPERIMENTAL Unified Score.
const SE={study:(location.hash.match(/^#shadow:(\w+)/)||[])[1]||"",cand:null,timer:null};   // #shadow:SYN02 opens a study
const seF=(x,n=2)=>x===null||x===undefined||x===""||(typeof x==="number"&&!isFinite(x))?"–":(typeof x==="number"?x.toFixed(n):esc(x));
const seCat=c=>{const m={likely_cSS:["likely cSS","var(--ok)"],uncertain:["uncertain – review","var(--warn)"],unlikely_cSS:["unlikely cSS","var(--mut)"],not_scorable:["not scorable","var(--bad)"]}[c];
  return m?`<span class="pill" style="border-color:${m[1]};color:${m[1]};font-weight:700">${m[0]}</span>`:`<span class="pill" title="ML not applied">deterministic fallback</span>`};
const seModelPill=m=>!m?`<span class="pill bad" data-se="model">model: none healthy → deterministic fallback</span>`:
  `<span class="pill ${m.data_kind==="synthetic"?"warn":"ok"}" data-se="model" title="${esc((m.model_hash||"").slice(0,16))}">model ${esc(m.name)} v${esc(m.version)} · ${esc(m.data_kind)} · ${esc(m.status)}</span>`;
const seBanner=`<div class="card" data-se="banner" style="border-color:var(--warn);background:color-mix(in srgb,var(--warn) 12%,transparent)"><b class="warn">SHADOW MODE</b> — the engine runs next to the existing pipeline and
  cannot change any score, list, call, decision or export. Every value marked <b>experimental</b> is research output only, not a diagnosis, not clinically validated.</div>`;
async function shadowView(v){
  clearTimeout(SE.timer);
  const st=await api("/api/se/state");
  if(st.error){v.innerHTML=`${seBanner}<div class="card"><b class="bad">Shadow engine screen unavailable</b><p class="note">${esc(st.error)}</p><p>The existing pipeline is unaffected.</p></div>`;return}
  const syn=st.synthetic_base?`<div class="card" data-se="synthetic" style="border-color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,transparent)"><b class="bad">SYNTHETIC DEMO BASE</b> — SYN studies, invented data. The model is trained on synthetic data; nothing here is a result.</div>`:"";
  const bad=st.models.filter(m=>m.status!=="ok");
  v.innerHTML=`${seBanner}${syn}<div class="row" style="justify-content:space-between"><div><b style="font-size:17px">Unified Score engine</b>
    <span class="pill warn">EXPERIMENTAL · shadow mode</span> ${seModelPill(st.active_model)}</div>
    <div class="row"><span class="mut">Run after each finished study</span><button class="b" id="se-en">${st.enabled?"On":"Off"}</button><button class="b" id="se-all">Run all finished studies</button></div></div>
    ${bad.length?`<div class="card"><b>Models not used</b>${bad.map(m=>`<div class="note">${esc(m.name||m.path)}: <b>${esc(m.status)}</b> — ${esc((m.reasons||[]).join("; "))}</div>`).join("")}</div>`:""}
    ${st.models_error?`<div class="card"><b class="bad">Model registry error</b><div class="note">${esc(st.models_error)}</div></div>`:""}
    <div class="card"><table data-se="studies"><tr><th>Study</th><th>Study status</th><th>Shadow run</th><th>ML</th><th>Unified categories</th><th>Existing outputs unchanged</th><th></th></tr>
    ${st.studies.map(s=>`<tr><td><b>${sidH(s.code)}</b></td><td>${esc(s.status)}</td><td>${esc(s.shadow)}${s.created?` · ${esc(s.created)}`:""}</td>
      <td>${s.ml_applied===true?'<span class="ok">applied</span>':s.ml_applied===false?'<span class="warn">withheld (fallback)</span>':"–"}</td>
      <td class="note">${s.counts?Object.entries(s.counts).map(([k,n])=>`${esc(k)} ${n}`).join(" · "):"–"}</td>
      <td>${s.unchanged===true?'<span class="ok">✓ verified</span>':s.unchanged===false?'<b class="bad">✗ CHANGED</b>':"–"}</td>
      <td><button class="b" data-run="${esc(s.code)}" ${s.status!=="done"?"disabled":""}>Run</button> <button class="b pri" data-open="${esc(s.code)}">Open</button></td></tr>`).join("")}</table></div>
    <div id="se-study"></div>`;
  $("#se-en").onclick=async()=>{await api("/api/se/enable",{on:!st.enabled});shadowView(v)};
  $("#se-all").onclick=async()=>{const r=await api("/api/se/run_all",{});toast(`shadow runs started: ${r.started??0}`);shadowView(v)};
  v.querySelectorAll("[data-run]").forEach(b=>b.onclick=async()=>{const r=await api("/api/se/run",{code:b.dataset.run});if(!r.ok)toast(r.error,true);SE.study=b.dataset.run;shadowView(v)});
  v.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>{SE.study=b.dataset.open;SE.cand=null;seStudy()});
  if(SE.study)seStudy();
  if(st.studies.some(s=>s.shadow==="running"))SE.timer=setTimeout(()=>{if(V==="shadow")shadowView(v)},2000);
}
async function seStudy(){
  const el=$("#se-study");if(!el)return;const r=await api(`/api/se/result?study=${encodeURIComponent(SE.study)}`);
  if(!r.available){
    el.innerHTML=`<div class="card" data-se="fallback"><h2>${esc(SE.study)} — existing deterministic output</h2><p class="warn"><b>ML engine output not available</b> — ${esc(r.error)}. The existing deterministic values below come straight from the detector's lists.</p>
     <table><tr><th>Ref</th><th>List</th><th>Region</th><th>score_v4</th><th>Evidence cSS / vein</th><th>Rule</th><th>Tier</th></tr>
     ${(r.deterministic_rows||[]).map(x=>`<tr><td>${esc(x.ref)}</td><td>${esc(x.list)}</td><td>${esc((x.region||"").replace(/ctx-[lr]h-/,""))}</td><td>${seF(+x.score_v4)}</td><td>${seF(+x.css_evidence)} / ${seF(+x.vein_evidence)}</td><td>${esc(x.rule_version)}</td><td>${esc(x.review_tier)}</td></tr>`).join("")}</table></div>`;return}
  const ps=r.deterministic_patient_score;
  el.innerHTML=`<div class="card" data-se="detail"><h2>${esc(r.study)} ${r.synthetic?'<span class="pill bad">SYNTHETIC</span>':""}</h2>
   <div class="row" style="gap:18px;flex-wrap:wrap"><div><span class="mut">1 · Existing deterministic 0–4 score</span><br><b>${ps?`L ${esc(ps.L)} · R ${esc(ps.R)} · total ${esc(ps.total)}`:"not scored"}</b></div>
    <div><span class="mut">2 · Experimental ML</span><br><b class="${r.ml_applied?"ok":"warn"}">${r.ml_applied?"applied":"withheld"}</b> <span class="note">${esc(r.ml_status)}</span></div>
    <div><span class="mut">3 · Experimental Unified Score</span><br>${r.category_counts?Object.entries(r.category_counts).map(([k,n])=>`${seCat(k)} ${n}`).join(" "):"<b>deterministic fallback</b>"}</div>
    <div><span class="mut">Model</span><br>${esc((r.model||{}).name||"none")} v${esc((r.model||{}).version||"–")} · ${esc((r.model||{}).data_kind||"")} · engine ${esc(r.engine)}</div>
    <div><span class="mut">Registration</span><br>${esc(r.registration)}</div><div><span class="mut">Existing outputs</span><br>${r.original_outputs_unchanged?'<span class="ok">unchanged ✓</span>':'<b class="bad">CHANGED</b>'}</div></div>
   <p class="note">${esc(r.disclaimer)} ${r.input_validation&&Object.keys(r.input_validation.corrupt||{}).length?` · corrupt inputs: ${esc(JSON.stringify(r.input_validation.corrupt))}`:""}</p>
   <table data-se="cands"><tr><th rowspan="2">Candidate</th><th colspan="3" style="text-align:center">1 · Existing deterministic</th><th style="text-align:center">2 · Experimental ML</th><th colspan="2" style="text-align:center">3 · Experimental Unified</th><th rowspan="2">Missing / flags</th><th rowspan="2" title="per-feature learned contributions ADDED to the MATH logit; the final p also contains the MATH logit">Largest learned corrections to MATH (log-odds)</th></tr>
    <tr><th>score_v4</th><th>tier</th><th>rule</th><th>increment</th><th>p [5–95 %]</th><th>category</th></tr>
    ${r.candidates.map((c,i)=>{const d=c.deterministic,u=c.unified,m=c.ml;const con=Object.entries(m.contributions||{}).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])).slice(0,2);
      return `<tr data-cand="${i}" style="cursor:pointer"><td><b>${esc(c.ref)}</b> <span class="note">${esc(c.list)} · ${esc((c.region||"").replace(/ctx-[lr]h-/,""))}</span></td>
       <td>${seF(d.score_v4)}</td><td>${esc(d.review_tier??"–")}</td><td>${esc(d.rule_fate||"–")}</td>
       <td>${m.status==="applied"?seF(m.increment):'<span class="note">withheld</span>'}</td>
       <td>${u.p===null||u.p===undefined?"–":`${seF(u.p)} <span class="note">[${seF(u.p_lo)}–${seF(u.p_hi)}]</span>`}</td><td>${seCat(u.category)}</td>
       <td class="note">${c.characteristics.n_missing_or_invalid?`<span class="warn">${c.characteristics.n_missing_or_invalid} missing/invalid</span> `:""}${(c.quality_flags||[]).map(esc).join("; ")}</td>
       <td class="note">${con.map(([k,x])=>`${esc(k)} ${x>0?"+":""}${seF(x)}`).join(", ")||"–"}</td></tr>`}).join("")}</table>
   <div id="se-cand"></div></div>`;
  el.querySelectorAll("[data-cand]").forEach(t=>t.onclick=()=>{const c=r.candidates[+t.dataset.cand];
    $("#se-cand").innerHTML=`<div class="card" data-se="trace"><h3>${esc(c.key)} — how the result was produced</h3>
     <p class="note">Formula: <b>${esc((c.trace||{}).calculation||"no fusion (deterministic fallback)")}</b> · model hash ${esc(((c.trace||{}).model_hash||"").slice(0,16))}</p>
     <table><tr><th>Characteristic</th><th>Value used</th><th>Status</th><th>Contribution</th></tr>${Object.entries(c.characteristics.values).map(([k,x])=>`<tr><td>${esc(k)}</td><td>${seF(x,3)}</td><td>${esc(c.characteristics.status[k])}</td><td>${seF((c.ml.contributions||{})[k],3)}</td></tr>`).join("")}</table>
     <details><summary>Full trace (JSON)</summary><pre style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify({deterministic:c.deterministic,ml:c.ml,unified:c.unified,trace:c.trace},null,1))}</pre></details></div>`})
}
window.shadowView=shadowView;
