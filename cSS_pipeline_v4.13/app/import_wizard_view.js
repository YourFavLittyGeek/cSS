// import_wizard_view.js - v5.18 Add studies › From folders: THE import pathway (the v5.16 guided import and the earlier batch table, merged).
// 1 data folder · 2 what the folder names are (patient name · MRN · accession number · code · irrelevant) · 3 Standard / Incognito ·
// 4 Excel file (identifiers, optional folder / date / grades) · 5 study library (verified COPY; originals untouched) · 6 processing ·
// 7 preview: (1) series review - thumbnail + choice of SWI / T1 / FLAIR / phase with warnings and recommendations per examination,
//   (2) identifiers (patient name, MRN, accession, code in separate columns; Incognito: icon + code), pathway, library place · import and start.
// The server builds and validates the plan; in Incognito the preview holds no MRN, name, accession, folder names or file paths.
const IW={tab:"series",folder:"",folder_is:"",sub_is:"",mode:"",manifest:"",gen:false,plan:null,busy:false,done:null,job:null,
  lib:null,proc:{cohort:"",anatomy:"synthseg",run_mode:"semi",results_dir:""}};
const INCOG_ICON=`<span class="incog" title="hidden in Incognito" data-id="incog"><svg width="18" height="14" viewBox="0 0 24 18" fill="currentColor" aria-label="Incognito"><path d="M3 7h18l-2-6c-.2-.6-.8-.9-1.4-.7L12 2 6.4.3C5.8.1 5.2.4 5 1L3 7zm-2 1.5h22v1.6H1z"/><circle cx="6.5" cy="14" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="17.5" cy="14" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M9.7 13.6c1.4-.8 3.2-.8 4.6 0" fill="none" stroke="currentColor" stroke-width="1.6"/></svg></span>`;
const FI_HELP={name:"each folder is named after the patient · a de-identified study code is given to each examination",mrn:"each folder is a patient's MRN · the examinations inside get their accession number from accession-number sub-folders or the Excel file",
  accession:"each examination folder is its accession number (the study identifier) · the MRN comes from the Excel file or the scan header",
  code:"each folder is a de-identified code · it becomes the study code (one examination) or the patient code (several examination sub-folders)",
  none:"folder names mean nothing · every Excel row must name its examination's folder (column 'folder'); Percival matches by that column"};
async function importWizardView(v){
  const s=IDV.st||await api("/api/id/state");if(!IW.mode)IW.mode=s.mode||"incognito";const P=IW.plan,set=S.settings||{};
  if(!IW.lib)IW.lib={enabled:!!set.library_dir,root:set.library_dir||"",whole_exam:!!set.library_whole_exam};
  if(!IW.proc.cohort&&S.cohorts&&S.cohorts.length)IW.proc.cohort=S.cohorts[0];
  const step=(n,t,body,ok)=>`<div class="card" data-iw="step${n}"><div class="row"><b>${n} · ${t}</b>${ok?'<span class="pill ok">✓</span>':""}</div>${body}</div>`;
  const fi=[["name","Patient name"],["mrn","MRN"],["accession","Accession number"],["code","Code"],["none","Irrelevant"]];
  const coh=S.cohorts||[];
  v.innerHTML=`<p class="note" style="margin-top:0;max-width:900px">Every MRI examination needs its identifier: the <b>accession number</b> (Standard) or the <b>de-identified study code</b> (Incognito).
     One patient can have several examinations. Your folders are only read: nothing is renamed or moved. Nothing is imported until the preview is valid and you confirm it.</p>
   ${step(1,"Data folder",`<div class="row" style="flex-wrap:wrap"><input id="iw-f" style="width:min(620px,100%)" value="${esc(IW.folder)}" placeholder="one examination folder, or a folder holding many (one sub-folder per patient or examination)"><button class="b" id="iw-fb">Choose folder…</button></div>`,!!IW.folder)}
   ${step(2,"The folder names are",`${seg("iw-fi",fi,IW.folder_is)}<p class="note" data-iw="fihelp">${IW.folder_is?esc(FI_HELP[IW.folder_is]):"Tell Percival what the folder names mean - it never guesses."}</p>
     ${P&&P.has_subfolders?`<div class="row"><span class="note">Examination sub-folders are named</span>${seg("iw-si",[["","(no meaning)"],["accession","Accession numbers"],["code","Codes"]],IW.sub_is)}</div>`:""}`,!!IW.folder_is)}
   ${step(3,"Identification mode for this import",`${seg("iw-m",[["standard","Standard (accession number)"],["incognito","Incognito (de-identified study code)"]],IW.mode)}
     ${IW.folder_is==="code"&&IW.mode!=="incognito"?'<p class="warn" data-iw="recommend">The folders are named with de-identified codes: Incognito mode is recommended, so that no identifiable value is needed or shown.</p>':""}
     <p class="note">${IW.mode==="standard"?"Standard: every examination needs its <b>MRN</b> and <b>accession number</b> (Excel file or folder names); the patient name is optional; examinations are grouped by MRN. A blank code is generated, so the study also works in Incognito.":
       "Incognito: upload the <b>key</b> (Excel file with MRN, name, accession number and code); every examination needs its <b>code</b>, its unique identifier. The key is stored only in the encrypted vault; the screens show codes only, with no grouping."}</p>
     ${!s.unlocked?`<div class="row" data-iw="vault" style="flex-wrap:wrap"><span class="warn">${s.vault_exists?"Enter the vault passphrase":"Create the identity vault (choose a passphrase, at least 10 characters)"} - MRN, name and accession number are stored only there${IW.mode==="incognito"?"; the screens stay de-identified":""}.</span>
       <input type="password" id="iw-pw" placeholder="vault passphrase" style="width:220px"><button class="b" id="iw-pwb">${s.vault_exists?"Unlock":"Create vault"}</button></div>`:'<p class="note ok" data-iw="vault-ok">✓ identity vault unlocked for this import</p>'}`,!!IW.mode&&s.unlocked)}
   ${step(4,"Excel file",`<p class="note">One row per MRI examination: <code>MRN · patient_name · accession_number · code (de-identifier)</code>, optional <code>folder · study_date · radiologist · grade_R · grade_L</code>.
       ${IW.folder_is==="none"?"<b>Needed</b>, with the <code>folder</code> column filled on every row: the folder names mean nothing, so each row must say which folder holds its examination.":
         IW.mode==="incognito"?"<b>Needed</b>: this is the key (MRN, name, accession number, code). The <code>folder</code> column is not needed - the folder names fill in what they hold.":
         "Needed unless the folder names give both the MRN and the accession number (e.g. MRN folders with accession-number sub-folders). The <code>folder</code> column is not needed."}</p>
     <div class="row" style="flex-wrap:wrap"><button class="b" id="iw-tpl" data-iw="template">Save template…</button><input id="iw-x" style="width:min(460px,100%)" value="${esc(IW.manifest)}" placeholder="completed Percival_Import_Template.xlsx"><button class="b" id="iw-xb">Choose file…</button>${IW.manifest?'<button class="b" id="iw-xc">Remove</button>':""}</div>
`,!!IW.manifest)}
   ${step(5,"Study library (a verified copy of your MRI)",`<label class="note" style="display:block"><input type="checkbox" id="iw-le" ${IW.lib.enabled?"checked":""}> Copy each imported examination into the study library - your original folders are never renamed, moved or changed</label>
     ${IW.lib.enabled?`<div class="row" style="flex-wrap:wrap"><input id="iw-lr" style="width:min(520px,100%)" value="${esc(IW.lib.root)}" placeholder="where to keep the library, e.g. /Volumes/LabDisk/Percival_library"><button class="b" id="iw-lb">Choose folder…</button></div>
     <div class="row">${seg("iw-lw",[["sel","Chosen series (SWI, T1, FLAIR, phase)"],["all","Whole examination (every series)"]],IW.lib.whole_exam?"all":"sel")}</div>
     <p class="note" data-iw="liblayout">Layout: ${IW.mode==="standard"?"<code>library / MRN / accession number / T1, SWI …</code> - folder names hold identifiers: keep the library on an encrypted local disk":"<code>library / code / T1, SWI …</code> (one folder per study code, no grouping)"}. Every file is checked (sha256) after copying; an existing folder is never overwritten.</p>`:""}`,IW.lib.enabled&&!!IW.lib.root)}
   ${step(6,"Processing",`<div class="row" style="flex-wrap:wrap"><span class="lab" style="width:auto">Cohort</span><select id="iw-c">${coh.map(c=>`<option ${c===IW.proc.cohort?"selected":""}>${esc(c)}</option>`).join("")}<option value="__new" ${IW.proc.cohort&&!coh.includes(IW.proc.cohort)?"selected":""}>+ New cohort…</option></select>
       <input id="iw-cn" placeholder="new cohort name" value="${IW.proc.cohort&&!coh.includes(IW.proc.cohort)?esc(IW.proc.cohort):""}" class="${(IW.proc.cohort&&!coh.includes(IW.proc.cohort))||!coh.length?"":"hide"}" style="width:180px">
       <span class="lab" style="width:auto">Anatomy</span>${seg("iw-an",[["synthseg","SynthSeg · fast"],["recon","recon-all · full"]],IW.proc.anatomy)}
       <span class="lab" style="width:auto">Mode</span>${seg("iw-rm",[["semi","Semi-automatic"],["auto","Automatic"]],IW.proc.run_mode)}</div>
     <div class="row" style="flex-wrap:wrap"><span class="lab" style="width:auto">Save results also in</span><input id="iw-rd" style="width:min(420px,100%)" value="${esc(IW.proc.results_dir)}" placeholder="optional - results stay in the project"><button class="b" id="iw-rb">Choose folder…</button></div>
     <div class="note">${IW.proc.run_mode==="semi"?"Semi-automatic: a radiologist reviews the AI candidates; the score is the reader's.":"Automatic: the AI result is scored with no review - labelled \"AI only, not validated\" everywhere."}</div>`,!!IW.proc.cohort)}
   <div class="row"><button class="b pri" id="iw-go" ${IW.folder&&IW.folder_is&&IW.mode?"":"disabled"}>7 · Check and preview</button><span class="mut" id="iw-msg">${IW.busy?"checking…":""}</span></div>
   <div id="iw-prev"></div>`;
  const re=()=>importWizardView(v),inval=()=>{IW.plan=null;IW.done=null};
  bindSeg("iw-fi",x=>{IW.folder_is=x;IW.sub_is="";inval();re()});bindSeg("iw-si",x=>{IW.sub_is=x;iwPlan(v)});bindSeg("iw-m",x=>{IW.mode=x;inval();re()});
  $("#iw-f").onchange=e=>{IW.folder=e.target.value.trim();inval();re()};$("#iw-x").onchange=e=>{IW.manifest=e.target.value.trim();inval();re()};
  $("#iw-xc")&&($("#iw-xc").onclick=()=>{IW.manifest="";inval();re()});
  $("#iw-tpl").onclick=()=>saveTemplate(p=>{IW.manifest=p;inval();re()});
  $("#iw-pwb")&&($("#iw-pwb").onclick=async()=>{const pw=$("#iw-pw").value;const r=await api(s.vault_exists?"/api/id/vault/unlock":"/api/id/vault/create",{passphrase:pw});
    if(r.ok===false||r.error)return toast(esc(r.error||"not unlocked"),1);IDV.st=await api("/api/id/state");if(IW.plan)await iwPlan(v);re()});
  $("#iw-fb").onclick=async()=>{const p=await pick("folder","Choose the data folder (one examination, or a folder holding many)");if(p){IW.folder=p.replace(/\/$/,"");inval();re()}};
  $("#iw-xb").onclick=async()=>{const p=await pick("file","Choose the completed Excel file (.xlsx)");if(p){IW.manifest=p;inval();re()}};
  const libch=async()=>{if(IW.plan)await iwUpdate([{library:IW.lib}]);re()};
  $("#iw-le").onchange=e=>{IW.lib.enabled=e.target.checked;libch()};$("#iw-lr")&&($("#iw-lr").onchange=e=>{IW.lib.root=e.target.value.trim();libch()});
  $("#iw-lb")&&($("#iw-lb").onclick=async()=>{const p=await pick("folder","Choose where to keep the study library");if(p){IW.lib.root=p.replace(/\/$/,"");libch()}});
  bindSeg("iw-lw",x=>{IW.lib.whole_exam=x==="all";libch()});
  const procch=async()=>{if(IW.plan)await iwUpdate([{processing:IW.proc}]);re()};
  $("#iw-c").onchange=e=>{if(e.target.value==="__new"){IW.proc.cohort="";$("#iw-cn").classList.remove("hide");$("#iw-cn").focus()}else{IW.proc.cohort=e.target.value;procch()}};
  $("#iw-cn").onchange=e=>{IW.proc.cohort=e.target.value.trim();procch()};
  bindSeg("iw-an",x=>{IW.proc.anatomy=x;procch()});bindSeg("iw-rm",x=>{IW.proc.run_mode=x;procch()});
  $("#iw-rd").onchange=e=>{IW.proc.results_dir=e.target.value.trim();procch()};
  $("#iw-rb").onclick=async()=>{const p=await pick("save","Choose where to save results");if(p){IW.proc.results_dir=p;procch()}};
  $("#iw-go").onclick=()=>iwPlan(v);
  if(IW.plan)iwPreview();if(IW.done)iwDone()}
async function iwPlan(v){IW.busy=true;const m=$("#iw-msg");if(m)m.textContent="checking…";
  const r=await api("/api/id/import/plan",{folder:IW.folder,folder_is:IW.folder_is,sub_is:IW.sub_is,mode:IW.mode,manifest:IW.manifest,generate_codes:IW.gen,library:IW.lib,processing:IW.proc});IW.busy=false;
  if(r.ok===false&&r.error){const m2=$("#iw-msg");if(m2)m2.innerHTML=`<span class="bad">${esc(r.error)}</span>`;return}
  const m3=$("#iw-msg");if(m3)m3.textContent="";const had=!!(IW.plan&&IW.plan.has_subfolders);IW.plan=r;if(r.has_subfolders!==had)return importWizardView(v);iwPreview()}
async function iwUpdate(ch){const P=IW.plan;if(!P)return;const r=await api("/api/id/import/update",{plan:P.id,changes:ch});if(r.ok===false&&r.error){toast(esc(r.error),1);return}IW.plan=r;iwPreview()}
async function saveTemplate(then){const d=await pick("folder","Choose where to save Percival_Import_Template.xlsx (a local folder)");if(!d)return;
  const r=await api("/api/id/template/save",{dest:d,open:true});if(!r.ok)return toast(esc(r.error),1);
  toast(`template saved: ${esc(r.path)} - it opens in Excel; fill it in, save it, then it is already chosen as the Excel file`);if(then)then(r.path)}
function iwPatient(e,std){if(!std)return INCOG_ICON;const v=[e.patient_name,e.mrn?`MRN ${e.mrn}`:""].filter(Boolean).join(" · ");return v?`${esc(v)}${e.mrn_source?` <span class="note">(${esc(e.mrn_source)})</span>`:""}`:'<span class="bad">MRN missing</span>'}
function iwPreview(){const P=IW.plan,el=$("#iw-prev");if(!el||!P)return;const std=P.mode==="standard";if(!IW.tab)IW.tab="series";
  const lbl=e=>std?(e.accession||"accession missing"):(e.code||"code missing");
  const dup=d=>!d.kind||d.kind==="new"?'<span class="ok">new</span>':d.kind==="same_patient_new_exam"?'<span class="ok">new exam of an existing patient</span>':d.kind==="same_exam"?`<span class="warn" title="${esc(d.why)}">already imported</span>`:`<span class="bad" title="${esc(d.why)}">conflict</span>`;
  const head=`<div class="row" style="flex-wrap:wrap"><h2 style="margin:0">Preview</h2><span class="pill">${P.layout==="one"?"one examination folder":`${P.patients.length} folder(s)`}</span><span class="pill">${P.n_exams} examination(s)</span>
     <span class="pill ${P.ok?"ok":P.errors.length?"bad":""}" data-iw="state">${P.ok?`ready: ${P.n_include} to import`:P.errors.length?`${P.errors.length} problem(s)`:P.n_include?"not ready":"nothing to import (all already imported or unticked)"}</span>${!std?'<span class="pill">Incognito: identifiers hidden</span>':""}${P.library.enabled?`<span class="pill ${P.library.root_ok?"ok":"bad"}">library ${P.library.root_ok?"✓":"✗"}</span>`:""}</div>
   <div class="subtabs" data-iw="tabs" style="margin-top:10px"><button data-iwt="series" class="${IW.tab==="series"?"on":""}">1 · Series review</button><button data-iwt="ids" class="${IW.tab==="ids"?"on":""}">2 · Identifiers and import</button></div>
   ${P.errors.length?`<div class="banner e" style="display:block" data-iw="errors">${P.errors.slice(0,30).map(e=>`<div>✗ ${esc(e.msg)}</div>`).join("")}${P.errors.length>30?`<div>… ${P.errors.length-30} more</div>`:""}</div>`:""}
   ${P.warnings.length?`<div class="banner w" style="display:block">${P.warnings.map(e=>`<div>⚠ ${esc(e.msg)}</div>`).join("")}</div>`:""}`;
  const thumb=(e,i)=>i==null?'<div class="th0">none</div>':`<img loading="lazy" class="th" src="/api/id/import/thumb?plan=${encodeURIComponent(P.id)}&eid=${encodeURIComponent(e.eid)}&i=${i}" alt="">`;
  const vox=s=>(s.voxel||[]).filter(Boolean).map(x=>(+x).toFixed(1)).join("×");
  const pickCell=(e,t)=>{const cur=e.chosen[t];return `<td class="sv">${thumb(e,cur)}<select data-iwss="${esc(e.eid)}" data-t="${t}"><option value="">— none —</option>${e.all_series.map(s=>`<option value="${s.i}" ${cur===s.i?"selected":""}>${esc(s.type)} · ${esc(s.description||"series "+(s.i+1))} · ${vox(s)} mm${(e.auto_why||{})[t]&&cur===s.i&&!e.user_series?" ✓":""}</option>`).join("")}</select></td>`};
  const adv=e=>(e.advice||[]).map(a=>`<div class="${a.level==="warn"?"warn":"note"}">${a.level==="warn"?"⚠ ":"• "}${esc(a.msg)}</div>`).join("")||'<span class="ok">✓ series look complete</span>';
  const series=`<p class="note">Check the series Percival chose for each examination. Each picture is the middle slice of the chosen series (made on this Mac). Choose another series from the list where needed; the recommendations are on the right.</p>
   <table class="iwt svt" data-iw="series-review"><colgroup><col style="width:64px"><col style="width:13%"><col><col><col><col><col style="width:22%"></colgroup>
    <tr><th>Include</th><th>${std?"Accession number":"Code"}</th><th>SWI</th><th>T1</th><th>FLAIR</th><th>Phase</th><th>Warnings and recommendations</th></tr>
    ${P.exams.map(e=>`<tr data-iwe="${esc(e.eid)}"><td><input type="checkbox" data-iwi="${esc(e.eid)}" ${e.include?"checked":""}></td><td><b>${esc(lbl(e))}</b>${e.user_series?'<div><span class="pill" data-iw="byyou">chosen by you</span></div>':""}${!e.include&&e.excluded_why?`<div class="note">${esc(e.excluded_why)}</div>`:""}</td>
      ${["SWI","T1","FLAIR","PHASE"].map(t=>pickCell(e,t)).join("")}<td data-iw="advice">${adv(e)}</td></tr>`).join("")}</table>
   <div class="row" style="margin-top:10px"><button class="b pri" id="iw-next" data-iw="next">Series look right · next: identifiers ▸</button></div>`;
  const rowOpt=e=>P.rows.length?`<select data-iwr="${esc(e.eid)}"><option value="">— no row —</option>${P.rows.map(r=>`<option value="${r.row}" ${e.row===r.row?"selected":""}>row ${r.row}${std?` · ${esc(r.accession||"no accession")}`:` · ${esc(r.code||"no code")}`}</option>`).join("")}</select><div class="note">${esc(e.matched_by||"")}</div>`:'<span class="mut">no Excel file</span>';
  const src=x=>x?` <span class="note">(${esc(x)})</span>`:"";
  const ids=`<table data-iw="exams" class="iwt"><colgroup><col style="width:52px">${std?'<col style="width:12%"><col style="width:10%"><col style="width:12%">':'<col style="width:6%">'}<col style="width:14%"><col style="width:12%"><col style="width:14%"><col></colgroup>
    <tr><th>Include</th>${std?"<th>Patient name</th><th>MRN</th><th>Accession number</th>":"<th>Patient</th>"}<th>Code</th><th>Excel row</th><th>Pathway</th><th>Library · status</th></tr>
    ${P.exams.map(e=>`<tr data-iwe="${esc(e.eid)}"><td><input type="checkbox" data-iwi="${esc(e.eid)}" ${e.include?"checked":""}></td>
     ${std?`<td data-iw="patient">${e.patient_name?esc(e.patient_name)+src(e.patient_name&&e.mrn_source==="Excel"?"Excel":""):'<span class="mut">—</span>'}</td><td>${e.mrn?`<span class="mono">${esc(e.mrn)}</span>${src(e.mrn_source)}`:'<span class="bad">missing</span>'}</td>
       <td>${e.accession?`<b>${esc(e.accession)}</b>${src(e.accession_source)}`:'<span class="bad">missing</span>'}${e.study_date?`<div class="note">${esc(e.study_date)}</div>`:""}</td>`:`<td data-iw="patient">${INCOG_ICON}</td>`}
     <td><input data-iwk="${esc(e.eid)}" value="${esc(e.code)}" placeholder="${e.code_generated?"generated at import":"code (required)"}" style="width:100%" title="de-identified study code">${e.code_source&&e.code_source!=="you"?src(e.code_source):""}${e.has_grades?'<div class="note">grades from Excel</div>':""}</td>
     <td>${rowOpt(e)}</td>
     <td>${e.check==="cannot"?'<span class="bad">cannot run</span>':(typeof pwSel==="function"&&S.pathways?pwSel(e.pathway,e.pathway_rec,`data-iwp="${esc(e.eid)}" style="width:100%"`):esc(e.pathway))}${e.pathway_reason&&e.check!=="ok"?`<div class="note warn">${esc(e.pathway_reason)}</div>`:""}</td>
     <td>${P.library.enabled?`<div class="mono note" style="overflow-wrap:anywhere" data-iw="lib">${e.library?esc(e.library):`<span class="${std?"bad":"mut"}">${esc(e.library_why||"—")}</span>`}${e.library_state?` · ${esc(e.library_state)}`:""}</div>`:""}
       ${dup(e.duplicate||{})}${e.excluded_why?`<div class="note">${esc(e.excluded_why)}</div>`:""}${e.problems.length&&e.include?`<div class="bad">${e.problems.map(esc).join("<br>")}</div>`:""}${(e.notes||[]).length?`<div class="note">${e.notes.map(esc).join("<br>")}</div>`:""}
       <input data-iwn="${esc(e.eid)}" value="${esc(e.display_name)}" placeholder="display name (optional)" style="width:100%;margin-top:4px"></td></tr>`).join("")}</table>
   <div class="row" style="margin-top:10px"><button class="b" data-iwt="series">◂ Series review</button><button class="b pri" id="iw-imp" ${P.ok?"":"disabled"} data-iw="confirm">Import ${P.n_include} examination(s) and start ▶</button><span class="note">${P.ok?`cohort ${esc(P.processing.cohort||"—")} · ${P.processing.run_mode==="semi"?"semi-automatic":"automatic"}${P.library.enabled?" · library copy after import":""}`:(P.errors.length?"fix the problems above (assign rows, choose series, correct the Excel file, or untick examinations)":"tick at least one examination")}</span></div>`;
  el.innerHTML=`<div class="card" data-iw="preview">${head}${IW.tab==="series"?series:ids}</div>`;
  setTimeout(iwMeasure,60);
  el.querySelectorAll("[data-iwt]").forEach(b=>b.onclick=()=>{IW.tab=b.dataset.iwt;iwPreview()});
  $("#iw-next")&&($("#iw-next").onclick=()=>{IW.tab="ids";iwPreview()});
  el.querySelectorAll("[data-iwss]").forEach(s=>s.onchange=()=>iwUpdate([{eid:s.dataset.iwss,series:{[s.dataset.t]:s.value}}]));
  el.querySelectorAll("[data-iwr]").forEach(s=>s.onchange=()=>iwUpdate([{eid:s.dataset.iwr,row:s.value}]));
  el.querySelectorAll("[data-iwi]").forEach(c=>c.onchange=()=>iwUpdate([{eid:c.dataset.iwi,include:c.checked}]));
  el.querySelectorAll("[data-iwn]").forEach(c=>c.onchange=()=>iwUpdate([{eid:c.dataset.iwn,display_name:c.value}]));
  el.querySelectorAll("[data-iwk]").forEach(c=>c.onchange=()=>iwUpdate([{eid:c.dataset.iwk,code:c.value.trim()}]));
  el.querySelectorAll("[data-iwp]").forEach(s=>s.onchange=async()=>{const e=P.exams.find(x=>x.eid===s.dataset.iwp),r=typeof confirmPath==="function"?await confirmPath(e.code||e.eid,s.value,e.pathway_rec,e.pathway_reason):true;
    iwUpdate([{eid:e.eid,pathway:r===true?s.value:r==="rec"?e.pathway_rec:e.pathway}])});
  $("#iw-imp")&&($("#iw-imp").onclick=async()=>{if(!confirm(`Import ${P.n_include} examination(s) as shown in the preview and start processing?`))return;
    const r=await api("/api/id/import/commit",{plan:P.id,confirm:true,cohort:P.processing.cohort});if(!r.ok)return toast(esc(r.error),1);IW.done=r;IW.plan=null;IW.tab="series";iwDone()})}
function iwMeasure(){const c=$('[data-iw="preview"]'),t=$('[data-iw="exams"]')||$('[data-iw="series-review"]');if(!c||!t)return;      // layout self-check (tests read these)
  c.dataset.overflow=t.scrollWidth>c.clientWidth+2?"yes":"no";const bad=[];
  t.querySelectorAll("td").forEach(td=>{const r=td.getBoundingClientRect();td.querySelectorAll("input,select,button").forEach(x=>{const q=x.getBoundingClientRect();if(q.width&&(q.right>r.right+1||q.left<r.left-1))bad.push(x.tagName.toLowerCase()+(x.type?":"+x.type:""))})});
  c.dataset.clipped=bad.length?"yes":"no";c.dataset.clipwhat=[...new Set(bad)].join(",")}
async function iwSeries(eid){const P=IW.plan,r=await api(`/api/id/import/series?plan=${encodeURIComponent(P.id)}&eid=${encodeURIComponent(eid)}`);if(r.error)return toast(esc(r.error),1);
  const cur=t=>{const x=r.series.find(s=>s.chosen_as.includes(t));return x?x.i:""},vox=s=>(s.voxel||[]).filter(Boolean).map(x=>(+x).toFixed(2)).join("×");
  const opt=t=>`<label style="display:inline-block;margin-right:18px"><b>${t}</b> <select data-ss="${t}"><option value="">— none —</option>${r.series.map(s=>`<option value="${s.i}" ${cur(t)===s.i?"selected":""}>#${s.i+1} ${esc(s.type||"?")} · ${esc((s.description||s.name||"series").slice(0,40))} · ${vox(s)} mm${s.auto_as.includes(t)?" ✓ automatic":""}</option>`).join("")}</select></label>`;
  const o=idModal(`<h2>Series of examination ${esc(eid)}</h2><p class="note">Percival chose automatically: ${Object.entries(r.auto_why||{}).map(([k,w])=>`<b>${esc(k)}</b> - ${esc(w)}`).join(" · ")||"nothing usable"}.
      You can choose any other series; your choice is marked "chosen by you".</p>
    <div class="row" style="flex-wrap:wrap">${opt("SWI")}${opt("T1")}${opt("FLAIR")}${opt("PHASE")}</div>
    <div style="max-height:52vh;overflow:auto"><table data-iw="series"><tr><th></th><th>#</th><th>Detected</th><th>Description</th><th>Voxel (mm)</th><th>Files / slices</th><th>TE</th><th>Why</th></tr>
     ${r.series.map(s=>`<tr><td style="width:96px"><img loading="lazy" src="/api/id/import/thumb?plan=${encodeURIComponent(P.id)}&eid=${encodeURIComponent(eid)}&i=${s.i}" style="width:88px;height:88px;object-fit:contain;background:#000;border-radius:4px" alt=""></td>
       <td class="mono">${s.i+1}${s.chosen_as.length?`<div class="ok">${s.chosen_as.join(", ")}</div>`:""}</td><td>${esc(s.type||"?")}</td><td style="overflow-wrap:anywhere">${esc(s.description||"")}${s.name?`<div class="note">${esc(s.name)}</div>`:""}</td>
       <td>${vox(s)}</td><td>${s.files||""}${s.shape&&s.shape[2]?` / ${s.shape[2]}`:""}</td><td>${s.te?(+s.te).toFixed(1):""}</td><td class="note">${esc([s.reason,s.usable_t1].filter(Boolean).join(" · "))}</td></tr>`).join("")}</table></div>
    <div class="row" style="margin-top:10px"><span class="sp"></span><button class="b" id="ss-x">Cancel</button><button class="b pri" id="ss-ok">Use these series</button></div>`);
  o.querySelector("#ss-x").onclick=()=>o.remove();
  o.querySelector("#ss-ok").onclick=async()=>{const ch={};o.querySelectorAll("[data-ss]").forEach(s=>ch[s.dataset.ss]=s.value);o.remove();await iwUpdate([{eid,series:ch}])}}
function iwDone(){const el=$("#iw-prev");if(!el||!IW.done)return;const D=IW.done,g=D.imported.filter(x=>x.generated);
  el.innerHTML=`<div class="card" data-iw="done"><h2>Imported ${D.imported.length} examination(s)</h2><p class="note">They are in the processing queue (Studies / Activity).</p>
   ${g.length?`<p><b>Generated de-identified study codes</b> (kept permanently; also in the Studies list and the exports):</p><table>${g.map(x=>`<tr><td class="mono">${esc(x.deid_code)}</td></tr>`).join("")}</table>`:""}
   ${D.library_job?`<div data-iw="libjob" class="note">Study library: copying…</div>`:""}
   <button class="b pri" onclick="IW.done=null;go('studies')">Open Studies</button></div>`;
  if(D.library_job)iwJob(D.library_job)}
async function iwJob(id){const j=await api(`/api/id/library/job?id=${encodeURIComponent(id)}`),el=$('[data-iw="libjob"]');if(!el||j.error)return;
  const n=s=>j.items.filter(x=>x.state===s).length;
  el.innerHTML=`Study library: ${j.done} / ${j.total} examination(s) · ${n("copied")} copied and verified${n("already")?` · ${n("already")} already there`:""}${n("conflict")?` · <span class="bad">${n("conflict")} conflict (nothing overwritten)</span>`:""}${n("failed")?` · <span class="bad">${n("failed")} failed: ${esc(j.items.filter(x=>x.state==="failed").map(x=>x.msg).join("; "))}</span>`:""}${j.state==="finished"?" · done":""}`;
  if(j.state!=="finished")setTimeout(()=>iwJob(id),1200)}
