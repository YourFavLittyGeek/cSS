// import_wizard_view.js - v5.16 guided import: 1 data folder, 2 meaning of patient folder names (asked, never assumed), 3 Standard /
// Incognito, 4 Excel manifest (Percival_Import_Template.xlsx), 5 identifier validation, 6 preview, 7 confirmed import.
// The server builds and validates the plan; in Incognito the preview contains no MRN, name, accession, folder names or file paths.
const IW={folder:"",folder_is:"",mode:"",manifest:"",gen:false,cohort:"",plan:null,busy:false,done:null};
async function importWizardView(v){
  const s=IDV.st||await api("/api/id/state");const P=IW.plan;
  const step=(n,t,body,ok)=>`<div class="card" data-iw="step${n}"><div class="row"><b>${n} · ${t}</b>${ok?'<span class="pill ok">✓</span>':""}</div>${body}</div>`;
  const fi=[["mrn","MRN"],["name","Patient name"],["deid","De-identified patient code"]];
  v.innerHTML=`<div class="banner"><b>Guided import</b><span class="mut">Every MRI examination needs its identifier: the <b>accession number</b> (Standard) or the <b>de-identified study code</b> (Incognito).
     One patient can have several examinations. Nothing is imported until the preview is valid and you confirm it.</span></div>
   ${step(1,"Data folder",`<div class="row" style="flex-wrap:wrap"><input id="iw-f" style="width:min(560px,100%)" value="${esc(IW.folder)}" placeholder="folder with one sub-folder per patient"><button class="b" id="iw-fb">Browse…</button></div>`,!!IW.folder)}
   ${step(2,"What are the patient folder names?",`<p class="note">This tells Percival how to read the folder names. It never replaces the study identifier.</p>${seg("iw-fi",fi,IW.folder_is)}`,!!IW.folder_is)}
   ${step(3,"Identification mode for this import",`${seg("iw-m",[["standard","Standard (accession number)"],["incognito","Incognito (de-identified study code)"]],IW.mode)}
     ${IW.folder_is==="deid"&&IW.mode!=="incognito"?'<p class="warn" data-iw="recommend">The folders are named with de-identified patient codes: Incognito mode is recommended, so that no identifiable value is needed or shown.</p>':""}
     ${IW.mode==="standard"&&!s.unlocked?'<p class="warn">Standard mode stores MRN, name and accession only in the encrypted vault: unlock it first (header › Standard).</p>':""}`,!!IW.mode)}
   ${step(4,"Excel manifest",`<p class="note">One row per MRI examination; columns <code>MRN · patient_name · accession_number · code (de-identifier)</code> in this order.</p>
     <div class="row" style="flex-wrap:wrap"><a class="b" href="/api/id/template.xlsx" data-iw="template">Download template</a><input id="iw-x" style="width:min(460px,100%)" value="${esc(IW.manifest)}" placeholder="completed Percival_Import_Template.xlsx"><button class="b" id="iw-xb">Browse…</button></div>
     ${IW.mode==="incognito"?`<label class="note" style="display:block;margin-top:6px"><input type="checkbox" id="iw-gen" ${IW.gen?"checked":""}> Generate a de-identified study code for examinations without one (random, unique, generated once and kept)</label>`:""}
     <label class="note">Cohort <input id="iw-c" value="${esc(IW.cohort)}" style="width:200px"></label>`,!!IW.manifest||(IW.mode==="incognito"&&IW.gen))}
   <div class="row"><button class="b pri" id="iw-go" ${IW.folder&&IW.folder_is&&IW.mode?"":"disabled"}>5 · Validate identifiers and preview</button><span class="mut" id="iw-msg">${IW.busy?"checking…":""}</span></div>
   <div id="iw-prev"></div>`;
  bindSeg("iw-fi",x=>{IW.folder_is=x;IW.plan=null;importWizardView(v)});bindSeg("iw-m",x=>{IW.mode=x;IW.plan=null;importWizardView(v)});
  $("#iw-f").onchange=e=>{IW.folder=e.target.value.trim();IW.plan=null;importWizardView(v)};$("#iw-x").onchange=e=>{IW.manifest=e.target.value.trim();IW.plan=null;importWizardView(v)};
  $("#iw-c").onchange=e=>IW.cohort=e.target.value.trim();$("#iw-gen")&&($("#iw-gen").onchange=e=>{IW.gen=e.target.checked;IW.plan=null});
  $("#iw-fb").onclick=async()=>{const p=await pick("folder","Choose the folder with one sub-folder per patient");if(p){IW.folder=p;IW.plan=null;importWizardView(v)}};
  $("#iw-xb").onclick=async()=>{const p=await pick("file","Choose the completed import manifest (.xlsx)");if(p){IW.manifest=p;IW.plan=null;importWizardView(v)}};
  $("#iw-go").onclick=async()=>{IW.busy=true;$("#iw-msg").textContent="checking…";
    const r=await api("/api/id/import/plan",{folder:IW.folder,folder_is:IW.folder_is,mode:IW.mode,manifest:IW.manifest,generate_codes:IW.gen});IW.busy=false;
    if(r.ok===false&&r.error){$("#iw-msg").innerHTML=`<span class="bad">${esc(r.error)}</span>`;return}IW.plan=r;iwPreview()};
  if(P)iwPreview();if(IW.done)iwDone()}
function iwPreview(){const P=IW.plan,el=$("#iw-prev");if(!el||!P)return;const std=P.mode==="standard";
  const rowOpt=e=>`<select data-iwr="${esc(e.eid)}"><option value="">— no row —</option>${P.rows.map(r=>`<option value="${r.row}" ${e.row===r.row?"selected":""}>row ${r.row}${std?` · ${esc(r.accession||"no accession")} · ${esc(r.patient_name||"")}`:` · ${esc(r.code||"no code")}`}</option>`).join("")}</select>`;
  const dup=d=>!d.kind||d.kind==="new"?'<span class="ok">new</span>':d.kind==="same_patient_new_exam"?'<span class="ok">new exam of an existing patient</span>':d.kind==="same_exam"?`<span class="warn" title="${esc(d.why)}">already imported</span>`:`<span class="bad" title="${esc(d.why)}">conflict</span>`;
  el.innerHTML=`<div class="card" data-iw="preview"><div class="row"><h2 style="margin:0">6 · Preview</h2><span class="pill">${P.patients.length} patient folder(s)</span><span class="pill">${P.n_exams} examination(s)</span>
     <span class="pill ${P.ok?"ok":"bad"}">${P.ok?`ready: ${P.n_include} to import`:`${P.errors.length} problem(s)`}</span>${P.mode==="incognito"?'<span class="pill">Incognito: identifiers hidden</span>':""}</div>
   ${P.errors.length?`<div class="banner e" style="display:block" data-iw="errors">${P.errors.slice(0,30).map(e=>`<div>✗ ${esc(e.msg)}</div>`).join("")}</div>`:""}
   ${P.warnings.length?`<div class="banner w" style="display:block">${P.warnings.map(e=>`<div>⚠ ${esc(e.msg)}</div>`).join("")}</div>`:""}
   <div style="overflow-x:auto"><table data-iw="exams" style="table-layout:auto"><tr><th>Include</th><th>Patient</th><th>Exam</th><th>Series</th>${std?"<th>MRN · name</th><th>Accession number</th>":""}<th>De-identified study code</th><th>Manifest row</th><th>Status</th><th>Display name</th></tr>
    ${P.exams.map(e=>{const pt=P.patients.find(p=>p.idx===e.patient_idx)||{};return `<tr><td><input type="checkbox" data-iwi="${esc(e.eid)}" ${e.include?"checked":""}></td><td>${esc(pt.label||"")}</td><td class="mono">${esc(e.eid)}${std&&e.sub?` · ${esc(e.sub)}`:""}</td>
     <td class="note">${e.series.map(x=>esc(x.type)).join(", ")||'<span class="bad">no SWI</span>'}</td>${std?`<td class="note">${esc([e.mrn,e.patient_name].filter(Boolean).join(" · ")||"—")}</td><td>${e.accession?esc(e.accession):'<span class="bad">missing</span>'}</td>`:""}
     <td>${e.code?esc(e.code):e.code_generated?'<span class="note">generated at import</span>':'<span class="bad">missing</span>'}</td><td>${rowOpt(e)} <span class="note">${esc(e.matched_by||"")}</span></td>
     <td>${dup(e.duplicate||{})}${e.excluded_why?`<div class="note" style="max-width:260px">${esc(e.excluded_why)}</div>`:""}${e.problems.length&&e.include?`<div class="bad" style="max-width:280px">${e.problems.map(esc).join("<br>")}</div>`:""}</td>
     <td><input data-iwn="${esc(e.eid)}" value="${esc(e.display_name)}" placeholder="e.g. Brain MRI - SWI" style="width:170px"></td></tr>`}).join("")}</table></div>
   <div class="row" style="margin-top:10px"><button class="b pri" id="iw-imp" ${P.ok?"":"disabled"} data-iw="confirm">7 · Import ${P.n_include} examination(s)</button><span class="note">${P.ok?"":"fix the problems above (assign rows, correct the manifest, or untick examinations)"}</span></div></div>`;
  const upd=async ch=>{const r=await api("/api/id/import/update",{plan:P.id,changes:ch});if(r.ok===false&&r.error)return toast(esc(r.error),1);IW.plan=r;iwPreview()};
  el.querySelectorAll("[data-iwr]").forEach(s=>s.onchange=()=>upd([{eid:s.dataset.iwr,row:s.value}]));
  el.querySelectorAll("[data-iwi]").forEach(c=>c.onchange=()=>upd([{eid:c.dataset.iwi,include:c.checked}]));
  el.querySelectorAll("[data-iwn]").forEach(c=>c.onchange=()=>upd([{eid:c.dataset.iwn,display_name:c.value}]));
  $("#iw-imp").onclick=async()=>{if(!confirm(`Import ${P.n_include} examination(s) as shown in the preview?`))return;
    const r=await api("/api/id/import/commit",{plan:P.id,confirm:true,cohort:IW.cohort});if(!r.ok)return toast(esc(r.error),1);IW.done=r;IW.plan=null;iwDone()}}
function iwDone(){const el=$("#iw-prev");if(!el||!IW.done)return;const g=IW.done.imported.filter(x=>x.generated);
  el.innerHTML=`<div class="card" data-iw="done"><h2>Imported ${IW.done.imported.length} examination(s)</h2><p class="note">They are in the processing queue (Studies / Activity).</p>
   ${g.length?`<p><b>Generated de-identified study codes</b> (kept permanently; they are also in the Studies list and the exports):</p><table>${g.map(x=>`<tr><td class="mono">${esc(x.deid_code)}</td></tr>`).join("")}</table>`:""}
   <button class="b pri" onclick="IW.done=null;go('studies')">Open Studies</button></div>`}
