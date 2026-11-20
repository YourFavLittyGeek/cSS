// image_ml_view.js - "Image ML" screen (Stage 2 prototype). SYNTHETIC DATA ONLY, experimental, research only, not a diagnosis.
// Talks to /api/im/* (app/image_ml_gui.py). It only READS results; it never changes a study, a list, a call, a score or an export.
// Three evidence streams are always shown apart: (1) Image ML (this screen's model), (2) Characteristic ML (Stage 1), (3) deterministic MATH.
const IMH=location.hash.match(/^#imageml:(\w+)(?::(\w+))?/)||[];
const IMV={study:IMH[1]||"",candRef:IMH[2]||"",cand:null,timer:null};   // #imageml:SYN001:c3 opens a study / candidate
const imF=(x,n=2)=>x===null||x===undefined||x===""||(typeof x==="number"&&!isFinite(x))?"–":(typeof x==="number"?x.toFixed(n):esc(String(x)));
const imBanner=w=>`<div class="card" data-im="banner" style="border-color:var(--bad);background:color-mix(in srgb,var(--bad) 13%,transparent)">
  <b class="bad">SYNTHETIC DATA ONLY</b> — ${esc(w||"experimental research prototype; outputs are not clinical results.")}</div>`;
const imStamp=`<span class="pill bad" data-im="stamp" title="trained and evaluated on invented phantom images only">SYNTHETIC · not clinical</span>`;
const imCat=c=>{const m={likely_cSS:["likely cSS","var(--ok)"],uncertain:["uncertain","var(--warn)"],unlikely_cSS:["unlikely cSS","var(--mut)"]}[c];
  return m?`<span class="pill" style="border-color:${m[1]};color:${m[1]};font-weight:700">${m[0]}</span>`:"–"};
const imStatus=c=>c.status==="ok"?'<span class="ok">scored</span>':`<span class="warn" title="${esc(c.reason||"")}">${esc(c.status.replace(/_/g," "))}</span>`;
function imDraw(cv,p,scale){if(!cv||!p)return;const h=p.gray.length,w=p.gray[0].length;cv.width=w*scale;cv.height=h*scale;const g=cv.getContext("2d");
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){const v=p.gray[y][x];g.fillStyle=p.valid[y][x]?`rgb(${v},${v},${v})`:"#3a1d1d";g.fillRect(x*scale,y*scale,scale,scale);
    if(p.mask[y][x]){g.fillStyle="rgba(255,70,70,.35)";g.fillRect(x*scale,y*scale,scale,scale)}}}
async function imageMlView(v){
  clearTimeout(IMV.timer);
  const st=await api("/api/im/state");
  if(st.error&&!st.studies){v.innerHTML=`${imBanner()}<div class="card"><b class="bad">Image ML screen unavailable</b><p class="note">${esc(st.error)}</p><p>The existing pipeline is unaffected.</p></div>`;return}
  if(!st.synthetic_base){v.innerHTML=`${imBanner(st.warning)}<div class="card" data-im="not-synthetic"><b>Image ML runs on a SYNTHETIC base only.</b>
    <p class="note">This project has no synthetic marker, so nothing is listed or read here. Start Percival on a synthetic cohort (see the launch instructions) to try the prototype.</p></div>`;return}
  const m=st.active_model,bad=(st.models||[]).filter(x=>x.status!=="ok");
  v.innerHTML=`${imBanner(st.warning)}
   <div class="row" style="justify-content:space-between"><div><b style="font-size:17px">Image ML</b> <span class="pill warn">EXPERIMENTAL</span> ${imStamp}
     ${m?`<span class="pill warn" data-im="model">model ${esc(m.name)} v${esc(m.version)} · ${esc(m.data_kind)} · ${esc(m.status)}</span>`:'<span class="pill bad" data-im="model">no healthy image model — predictions withheld</span>'}</div></div>
   ${bad.length?`<div class="card"><b>Models not used</b>${bad.map(x=>`<div class="note">${esc(x.name||x.path)}: <b>${esc(x.status)}</b> — ${esc((x.reasons||[]).join("; "))}</div>`).join("")}</div>`:""}
   <div class="card"><table data-im="studies"><tr><th>Synthetic study</th><th>Image ML run</th><th>Model applied</th><th>Categories</th><th>Inputs unchanged</th><th></th></tr>
   ${st.studies.map(s=>`<tr><td><b>${esc(s.code)}</b></td><td>${esc(s.job)}${s.created?` · ${esc(s.created)}`:""}</td>
     <td>${s.applied===true?'<span class="ok">yes</span>':s.applied===false?'<span class="warn">no</span>':"–"}</td>
     <td class="note">${s.counts?Object.entries(s.counts).map(([k,n])=>`${esc(k)} ${n}`).join(" · "):"–"}</td>
     <td>${s.unchanged===true?'<span class="ok">✓ verified</span>':s.unchanged===false?'<b class="bad">✗ CHANGED</b>':"–"}</td>
     <td><button class="b" data-imrun="${esc(s.code)}">Run inference</button> <button class="b pri" data-imopen="${esc(s.code)}">Open</button></td></tr>`).join("")}
   ${st.studies.length?"":'<tr><td colspan="6" class="note">No synthetic studies in this base.</td></tr>'}</table></div>
   <div id="im-study"></div>`;
  v.querySelectorAll("[data-imrun]").forEach(b=>b.onclick=async()=>{const r=await api("/api/im/run",{code:b.dataset.imrun});if(!r.ok)toast(esc(r.error),true);IMV.study=b.dataset.imrun;IMV.cand=null;imageMlView(v)});
  v.querySelectorAll("[data-imopen]").forEach(b=>b.onclick=()=>{IMV.study=b.dataset.imopen;IMV.cand=null;imStudy()});
  if(IMV.study)imStudy();
  if(st.studies.some(s=>s.job==="running"))IMV.timer=setTimeout(()=>{if(V==="imageml")imageMlView(v)},2000);
}
async function imStudy(){
  const el=$("#im-study");if(!el)return;const r=await api(`/api/im/result?study=${encodeURIComponent(IMV.study)}`);
  const sep=(n,t,body)=>`<div class="card" data-im="stream-${n}"><h2>${t}</h2>${body}</div>`;
  const mathRows=Object.entries((r.math||{}).rows||{}).filter(([k,x])=>Object.keys(x).length);
  const math=sep("math","3 · Deterministic MATH (existing detector)",(r.math||{}).available?`<table><tr><th>Ref</th><th>score_v4</th><th>tier</th><th>rule version</th></tr>${mathRows.map(([k,x])=>`<tr><td>${esc(k)}</td><td>${imF(+x.score_v4,3)}</td><td>${esc(x.review_tier||"–")}</td><td>${esc(x.rule_version||"–")}</td></tr>`).join("")}</table>`:`<p class="note" data-im="math-na">Not available — ${esc((r.math||{}).reason||"")}</p>`);
  const ch=r.characteristics||{};
  const chars=sep("characteristics","2 · Characteristic ML (Stage 1 Unified Score engine)",ch.available?`<table><tr><th>Ref</th><th>status</th><th>learned increment</th></tr>${Object.entries(ch.rows||{}).map(([k,x])=>`<tr><td>${esc(k)}</td><td>${esc(x.status||"–")}</td><td>${imF(x.increment,3)}</td></tr>`).join("")}</table>`:`<p class="note" data-im="chars-na">Not available — ${esc(ch.reason||"")}</p>`);
  if(!r.available){
    el.innerHTML=`${sep("image",`1 · Image ML — ${esc(IMV.study)} ${imStamp}`,`<p class="warn" data-im="no-result"><b>No Image ML result</b> — ${esc(r.error||"")}</p>
      ${r.job&&r.job.status==="failed"?`<p class="bad" data-im="failed"><b>Inference failed.</b> ${esc(r.job.error||"")}</p>`:""}
      <p class="note">Candidates as written by the detector (coordinates only, no prediction):</p>
      <table><tr><th>Ref</th><th>list</th><th>voxel (i, j, k)</th><th>volume mm³</th></tr>${(r.detector_rows||[]).map(x=>`<tr><td>${esc(x.ref)}</td><td>${esc(x.list)}</td><td>${esc(x.vox_ijk.join(", "))}</td><td>${esc(x.volume_mm3)}</td></tr>`).join("")}</table>`)}${chars}${math}`;
    return}
  const d=r.image_ml,M=d.model||{},S=d.study||{};
  const ev=(M.evaluation||{}),cv=ev.cv_train_cohort||{},te=ev.independent_synthetic_test||{},nc=ev.negative_control_cv||{};
  const prov=`<details data-im="provenance"><summary><b>Model provenance</b> ${imStamp}</summary><table>
    <tr><td>name / version</td><td>${esc(M.name)} v${esc(M.version)}</td></tr><tr><td>data kind</td><td><b class="bad">${esc(M.data_kind)}</b></td></tr>
    <tr><td>model hash</td><td class="mono">${esc(M.model_hash||"–")}</td></tr><tr><td>created</td><td>${esc(M.created||"–")}</td></tr>
    <tr><td>method</td><td class="note">image-derived patch features (${(M.features||[]).length}) + L2 multinomial logistic regression, patient-bootstrap intervals</td></tr>
    <tr><td>classes</td><td class="note">${esc((M.classes||[]).join(", "))}</td></tr>
    <tr><td>training</td><td class="note">${esc(JSON.stringify(M.training||{}))}</td></tr>
    <tr><td>synthetic evaluation</td><td class="note">CV within-patient AUC ${imF(cv.auc_within_patient)} · independent synthetic test ${imF(te.auc_within_patient)} · negative control ${imF(nc.auc_within_patient)}
      — numbers describe the invented generator, not cSS</td></tr>
    <tr><td>intended use</td><td class="note">${esc(M.intended_use||"")}</td></tr><tr><td>engine</td><td class="mono">${esc(d.engine_version)} · ${esc(d.imaging_version)} · ${esc(d.schema)}</td></tr></table></details>`;
  const head=`<div class="row"><span class="pill">study geometry: ${esc(S.index_status)}</span><span class="pill">channels: ${esc((S.usable_channels||[]).join(", ")||"–")}</span>
    <span class="pill ${d.original_inputs_unchanged?"ok":"bad"}">inputs unchanged ${d.original_inputs_unchanged?"✓":"✗"}</span><span class="pill">${M.applied?"model applied":"model NOT applied"}</span>
    <span class="note">run ${esc(d.created)}</span></div>${S.blocked?`<p class="warn"><b>Study not scorable:</b> ${esc(S.blocked)}</p>`:""}${!M.applied?`<p class="warn" data-im="model-na"><b>Predictions withheld:</b> ${esc(M.reason||M.status||"")}</p>`:""}
    ${r.stale_job_error?`<p class="bad"><b>Latest run failed</b> (showing the previous result): ${esc(r.stale_job_error)}</p>`:""}`;
  const tbl=`<table data-im="cands"><tr><th>Ref</th><th>voxel (i, j, k)</th><th>world centre (mm)</th><th>predicted class</th><th>p(cSS) [5–95 %]</th><th>confidence</th><th>category</th><th>status</th></tr>
    ${d.candidates.map((c,i)=>`<tr data-imc="${i}" style="cursor:pointer" class="${IMV.cand===i?"sel":""}"><td><b>${esc(c.ref)}</b> <span class="note">${esc(c.list)}</span></td>
     <td class="mono">${c.vox_ijk?esc(c.vox_ijk.join(", ")):"–"}</td><td class="mono">${c.world_centre_mm?c.world_centre_mm.map(x=>x.toFixed(1)).join(", "):"–"}</td>
     <td>${c.status==="ok"?esc(c.predicted_class.replace(/_/g," ")):"–"}</td><td>${c.status==="ok"?`<b>${imF(c.p_css,2)}</b> <span class="note">[${imF(c.p_css_interval[0],2)}–${imF(c.p_css_interval[1],2)}]</span>`:"–"}</td>
     <td>${c.status==="ok"?imF(c.confidence,2):"–"}</td><td>${c.status==="ok"?imCat(c.category):"–"}</td><td>${imStatus(c)}${c.quality_flags&&c.quality_flags.length?` <span class="warn" title="${esc(c.quality_flags.join("; "))}">⚑</span>`:""}</td></tr>`).join("")}</table>
    <p class="note">p(cSS) is the synthetic model's probability for the cSS class; confidence = probability of the predicted class. Categories are reading aids, never decisions.</p>`;
  el.innerHTML=`${sep("image",`1 · Image ML — ${esc(IMV.study)} ${imStamp}`,head+tbl+'<div id="im-cand"></div>'+prov)}${chars}${math}`;
  el.querySelectorAll("[data-imc]").forEach(tr=>tr.onclick=()=>{IMV.cand=+tr.dataset.imc;imCand(d)});
  if(IMV.cand===null&&IMV.candRef){const i=d.candidates.findIndex(c=>c.ref===IMV.candRef);if(i>=0)IMV.cand=i;IMV.candRef=""}
  if(IMV.cand!==null&&d.candidates[IMV.cand])imCand(d);
}
function imCand(d){
  const c=d.candidates[IMV.cand],el=$("#im-cand");if(!el||!c)return;
  document.querySelectorAll("[data-imc]").forEach(tr=>tr.classList.toggle("sel",+tr.dataset.imc===IMV.cand));
  const pv=c.previews;
  const probs=c.class_probabilities?Object.entries(c.class_probabilities).sort((a,b)=>b[1]-a[1]).map(([k,p])=>`<tr><td>${esc(k.replace(/_/g," "))}</td><td style="width:220px"><div style="height:9px;border-radius:4px;background:var(--acc);width:${Math.round(p*200)}px"></div></td><td>${imF(p,3)}</td></tr>`).join(""):"";
  el.innerHTML=`<div class="card" data-im="cand"><h2>${esc(c.ref)} · ${esc(c.list)} ${imStamp}</h2>
   ${pv?`<div class="row" style="align-items:flex-start;gap:18px" data-im="patches">
     <div><canvas id="imp1"></canvas><div class="note">surface patch, u × v at the surface<br>${esc(pv.axes.surface_uv)}</div></div>
     <div><canvas id="imp2"></canvas><div class="note">surface patch, v × n<br>${esc(pv.axes.surface_vn)}</div></div>
     <div><canvas id="imp3"></canvas><div class="note">native acquired slice (centre)<br>${esc(pv.axes.native_centre)}</div></div></div>
     <p class="note">red = object mask; dark red = outside the image / brain (invalid). Intensity scaled to the patch median.</p>`:'<p class="warn" data-im="no-patch">No patch for this object — '+esc(c.reason||"")+"</p>"}
   ${c.status==="ok"?`<table><tr><th>class</th><th></th><th>probability</th></tr>${probs}</table>
     ${c.quality_flags.length?`<p class="warn"><b>Quality flags:</b> ${esc(c.quality_flags.join("; "))}</p>`:""}
     <details><summary>Features used (${Object.keys(c.features).length})</summary><table>${Object.entries(c.features).map(([k,x])=>`<tr><td>${esc(k)}</td><td>${imF(x,3)}</td></tr>`).join("")}</table></details>
     <details><summary>Provenance (JSON)</summary><pre style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify({cand_uid:c.cand_uid,object_key:c.object_key,patch_sha:c.patch_sha,patch_path:c.patch_path,model_hash:d.model.model_hash,index_sha:d.study.index_sha},null,1))}</pre></details>`
     :`<p class="warn"><b>${esc(c.status.replace(/_/g," "))}</b> — ${esc(c.reason||"")}</p>`}</div>`;
  if(pv){imDraw($("#imp1"),pv.surface_uv,5);imDraw($("#imp2"),pv.surface_vn,5);imDraw($("#imp3"),pv.native_centre,3)}
}
