// study_admin_view.js - v5.20 study panel header (Standard: MRN · name first, cohort, the patient's examinations; Incognito: code only),
// Edit with Save / Discard (identifier checkpoint on the server), bulk edit, Archive (+ separate Archive screen), Remove / Purge.
function sheetHead(x){const i=sidOf(x.code),std=sidStd()&&!i.locked,p=x.p;
  const exams=std&&i.patient_uuid?((W.data&&W.data.rows)||[]).filter(r=>sidOf(r.code).patient_uuid===i.patient_uuid):[];
  const top=std?`<div style="font-size:20px;font-weight:650" data-id="sh-mrn">${i.mrn?`MRN <span class="mono">${esc(i.mrn)}</span>`:'<span class="bad">MRN missing</span>'}${i.patient_name?` · ${esc(i.patient_name)}`:""}</div>
      <div class="note">${esc(x.cohort||"no cohort")} · accession <b>${i.accession?esc(i.accession):'<span class="bad">missing</span>'}</b> · code <span class="mono">${esc(i.deid_code||x.code)}</span>${i.display_name?` · ${esc(i.display_name)}`:""}</div>`
    :`<div style="font-size:20px;font-weight:650" data-id="sh-code">${sidH(x.code)}</div><div class="note">${esc(x.cohort||"no cohort")}${i.display_name?` · ${esc(i.display_name)}`:""}</div>`;
  const list=exams.length>1?`<div class="sh-exams" data-id="sh-exams"><div class="note" style="margin:8px 0 4px">This patient's examinations (${exams.length})</div>
      ${exams.map(r=>{const j=sidOf(r.code);return `<div class="sh-ex ${r.code===x.code?"on":""}" data-shx="${esc(r.code)}"><b>${esc(j.accession||"accession missing")}</b> <span class="mut">${esc(r.cohort||"")}</span><span class="sp"></span><span class="st ${r.st.k}"><i></i>${esc(r.st.l)}</span></div>`}).join("")}</div>`:"";
  return top+list}
function bindSheetHead(){document.querySelectorAll("[data-shx]").forEach(e=>e.onclick=()=>openSheet(e.dataset.shx))}
// ---------- edit one study (Save / Discard)
function openStudyEdit(code){const x=((W.data&&W.data.rows)||[]).find(r=>r.code===code)||{code},i=sidOf(code),std=sidStd()&&!i.locked,el=$("#shedit");if(!el)return;
  const f=(k,l,v,hint)=>`<label class="sef"><span class="note">${l}</span><input data-sef="${k}" value="${esc(v||"")}"${hint?` placeholder="${esc(hint)}"`:""}></label>`;
  const coh=(S.cohorts||[]);
  el.innerHTML=`<div class="card" data-id="sh-editform" style="margin:10px 0"><h3 style="margin:0 0 6px">Edit ${sidH(code)}</h3>
    ${std?`<div class="note" style="margin-bottom:4px">Patient (every examination of this patient)</div><div class="row" style="flex-wrap:wrap">${f("mrn","MRN",i.mrn)}${f("patient_name","Patient name",i.patient_name,"optional")}</div>
      <div class="note" style="margin:8px 0 4px">This examination</div><div class="row" style="flex-wrap:wrap">${f("accession","Accession number",i.accession)}${f("deid_code","Code",i.deid_code)}${f("display_name","Display name",i.display_name,"optional")}</div>`
      :`<div class="row" style="flex-wrap:wrap">${f("deid_code","Code",i.deid_code)}${f("display_name","Display name",i.display_name,"optional")}</div><p class="note">MRN, patient name and accession number are edited in Standard mode.</p>`}
    <div class="row"><label class="sef"><span class="note">Cohort</span><input data-sef="cohort" list="sef-coh" value="${esc(x.cohort||"")}"></label><datalist id="sef-coh">${coh.map(c=>`<option value="${esc(c)}">`).join("")}</datalist>
      <label class="sef" style="flex:1"><span class="note">Reason (kept in the audit)</span><input data-sef-reason value="" placeholder="e.g. typo in the accession number"></label></div>
    <p class="note">Before saving, Percival checks that the accession number and the code are not used anywhere else (active and archived studies). Everything updates at once; the study library folder is renamed to match.</p>
    <div class="row"><span class="err" id="sef-err"></span><span class="sp"></span><button class="b" id="sef-x">Discard</button><button class="b pri" id="sef-ok">Save</button></div></div>`;
  const orig={};el.querySelectorAll("[data-sef]").forEach(q=>orig[q.dataset.sef]=q.value);
  $("#sef-x").onclick=()=>{el.innerHTML="";toast("changes discarded")};
  $("#sef-ok").onclick=async()=>{const ch={};el.querySelectorAll("[data-sef]").forEach(q=>{if(q.value.trim()!==orig[q.dataset.sef].trim())ch[q.dataset.sef]=q.value.trim()});
    if(!Object.keys(ch).length){el.innerHTML="";return toast("nothing changed")}
    const idf=["mrn","patient_name","accession","deid_code"].filter(k=>k in ch);
    if(idf.length&&!confirm(`Change ${idf.join(", ")} of this study? The change is audited and applied everywhere.`))return;
    const r=await api("/api/sa/edit",{code,fields:ch,confirm:true,reason:el.querySelector("[data-sef-reason]").value});
    if(!r.ok){$("#sef-err").textContent="✗ "+(r.error||"not saved");return}
    toast(`saved${r.library?" · "+esc(r.library):""}`);el.innerHTML="";S=await api("/api/state");W.data=null;await loadStudies();if(V==="studies")studiesView($("#view"));openSheet(code)}}
// ---------- bulk edit (cohort / display name)
async function bulkEdit(codes){if(!codes.length)return toast("tick the studies to edit first",1);
  const o=idModal(`<h2>Edit ${codes.length} studies</h2><p class="note">Change the cohort or the display name of every ticked study. Identifiers (MRN, accession number, code) are edited one study at a time, in its panel.</p>
    <div class="row"><label class="sef"><span class="note">Cohort</span><input id="be-c" list="be-cl" placeholder="leave empty: unchanged"></label><datalist id="be-cl">${(S.cohorts||[]).map(c=>`<option value="${esc(c)}">`).join("")}</datalist>
    <label class="sef"><span class="note">Display name</span><input id="be-d" placeholder="leave empty: unchanged"></label></div>
    <div class="row"><span class="err" id="be-err"></span><span class="sp"></span><button class="b" id="be-x">Discard</button><button class="b pri" id="be-ok">Save</button></div>`);
  o.querySelector("#be-x").onclick=()=>o.remove();
  o.querySelector("#be-ok").onclick=async()=>{const f={};const c=o.querySelector("#be-c").value.trim(),d=o.querySelector("#be-d").value.trim();if(c)f.cohort=c;if(d)f.display_name=d;
    if(!Object.keys(f).length)return o.remove();const r=await api("/api/sa/bulk",{codes,fields:f,confirm:true});
    if(!r.ok&&r.errors){o.querySelector("#be-err").innerHTML=r.errors.map(esc).join("<br>");return}o.remove();toast(`${r.n} studies updated`);W.data=null;S=await api("/api/state");render()}}
// ---------- archive
async function archiveStudies(codes,on){if(!codes.length)return toast("tick the studies first",1);
  if(!confirm(`${on?"Archive":"Restore"} ${codes.length} studies? ${on?"They leave the Studies, Activity and Review lists; every file is kept (Studies › Archive).":""}`))return;
  const r=await api("/api/sa/archive",{codes,on});toast(`${r.done.length} studies ${on?"archived":"restored"}${r.skipped.length?` · ${r.skipped.length} skipped (processing)`:""}`);W.sel.clear();W.data=null;S=await api("/api/state");render()}
async function archiveCohort(){const c=(S.cohorts||[]);if(!c.length)return toast("no cohort",1);
  const o=idModal(`<h2>Archive a cohort</h2><div class="row"><select id="ac-c">${c.map(x=>`<option>${esc(x)}</option>`).join("")}</select><span class="sp"></span><button class="b" id="ac-x">Cancel</button><button class="b pri" id="ac-ok">Archive cohort</button></div>`);
  o.querySelector("#ac-x").onclick=()=>o.remove();o.querySelector("#ac-ok").onclick=async()=>{const k=o.querySelector("#ac-c").value;o.remove();
    if(!confirm(`Archive every study of cohort ${k}?`))return;const r=await api("/api/sa/archive_cohort",{cohort:k,on:true});toast(`${r.done.length} studies archived`);W.data=null;S=await api("/api/state");render()}}
const AV={tab:"archived",sel:new Set()};
async function archiveView(v){await loadStudies();const A=W.archivedRows||[],Rt=W.retiredRows||[],std=sidStd();
  const L=AV.tab==="archived"?A:Rt;
  v.innerHTML=`<div class="subtabs" data-id="archtabs"><button data-av="archived" class="${AV.tab==="archived"?"on":""}">Archived (${A.length})</button><button data-av="retired" class="${AV.tab==="retired"?"on":""}">Removed, kept for ML (${Rt.length})</button></div>
   <p class="note">${AV.tab==="archived"?"Archived studies keep every file and their identifiers. They are hidden from Studies, Activity and Review. "+(S.settings.features&&S.settings.features.train_include_archived===false?"They are <b>excluded</b> from model training (Settings).":"They are <b>included</b> in model training (Settings › Features)."):
     "Removed studies: images and processing files were moved to the Trash; candidate tables, reviewer calls, labels and features are kept for machine learning under a new identifier (RET-…). Their accession number and code were released."}</p>
   ${AV.tab==="archived"?`<div class="row"><button class="b pri" id="av-res" ${AV.sel.size?"":"disabled"}>Restore ${AV.sel.size||""} selected</button><button class="b" onclick="go('studies')">◂ Studies</button></div>`:`<div class="row"><button class="b" onclick="go('studies')">◂ Studies</button></div>`}
   <div class="list"><table data-id="archive-list"><thead><tr>${AV.tab==="archived"?'<th style="width:34px"></th>':""}<th>${AV.tab==="retired"?"Identifier (retired)":std?"Accession number":"Code"}</th>${std&&AV.tab==="archived"?"<th>Patient name</th><th>MRN</th>":""}<th>Cohort</th><th>${AV.tab==="archived"?"Archived":"Removed"}</th><th>Candidates</th><th>Reviewed</th></tr></thead><tbody>
   ${L.map(x=>{const i=sidOf(x.code),pp=x.p||{},r=x.r||{},when=(AV.tab==="archived"?pp.archived_at:pp.retired_at)||"";
     return `<tr>${AV.tab==="archived"?`<td><input type="checkbox" data-avs="${esc(x.code)}" ${AV.sel.has(x.code)?"checked":""}></td>`:""}<td><b>${AV.tab==="retired"?esc(x.code):sidH(x.code)}</b></td>${std&&AV.tab==="archived"?`<td>${esc(i.patient_name||"—")}</td><td class="mono">${esc(i.mrn||"—")}</td>`:""}
       <td class="mut">${esc(x.cohort||"—")}</td><td class="note">${esc(when)}</td><td>${r.candidates??"—"}</td><td>${r.reviewed??"—"}</td></tr>`}).join("")||`<tr><td colspan="7" class="empty">Nothing here.</td></tr>`}</tbody></table></div>`;
  v.querySelectorAll("[data-av]").forEach(b=>b.onclick=()=>{AV.tab=b.dataset.av;AV.sel.clear();archiveView(v)});
  v.querySelectorAll("[data-avs]").forEach(c=>c.onchange=()=>{c.checked?AV.sel.add(c.dataset.avs):AV.sel.delete(c.dataset.avs);archiveView(v)});
  $("#av-res")&&($("#av-res").onclick=async()=>{const codes=[...AV.sel];const r=await api("/api/sa/archive",{codes,on:false});toast(`${r.done.length} studies restored`);AV.sel.clear();W.data=null;S=await api("/api/state");archiveView(v)})}
// ---------- remove / purge
const gbx=b=>b>=1e9?`${(b/1e9).toFixed(2)} GB`:`${Math.max(0,b/1e6).toFixed(1)} MB`;
async function openRemove(codes){if(!codes.length)return toast("tick the studies to remove first",1);
  const o=idModal(`<div data-id="rm-dlg"><h2>Remove ${codes.length} studies</h2>
    <label class="rmopt"><input type="radio" name="rmm" value="remove" checked> <b>Remove - keep results for machine learning</b><div class="note">Images and processing files go to the Trash. Candidate tables, every reviewer's calls, labels, scores, features and image patches are kept. The study gets a new identifier (RET-…) and its accession number and code are released, so a later import of the same examination is not a duplicate. The study can no longer be reviewed again.</div></label>
    <label class="rmopt"><input type="radio" name="rmm" value="purge"> <b>Purge - remove everything</b><div class="note">Every file of the study - images, processing, results and reviewer calls - goes to the Trash, and its record is deleted. Its identifiers become free.</div></label>
    <label class="note" style="display:block;margin-top:6px"><input type="checkbox" id="rm-lib" checked> also move the study library copy to the Trash</label>
    <div id="rm-pv" class="note" style="display:none;margin-top:6px"><b>Copy on the Pensieve drive:</b> <select id="rm-pvsel"><option value="">choose…</option><option value="keep">keep it on the drive</option><option value="trash">move it to the drive's Trash</option></select> <span id="rm-pvtxt"></span></div>
    <div id="rm-sum" class="note" style="margin:8px 0">checking…</div>
    <div class="row"><span class="note">Type <b id="rm-ph">REMOVE</b> to confirm</span><input id="rm-c" style="width:140px" autocomplete="off"><span class="sp"></span><button class="b" id="rm-x">Cancel</button><button class="b danger" id="rm-ok">Remove</button></div><p class="err" id="rm-err"></p></div>`);
  const mode=()=>o.querySelector('input[name="rmm"]:checked').value;
  const sum=async()=>{const r=await api("/api/sa/plan_remove",{codes,mode:mode()});const el=o.querySelector("#rm-sum");if(!r.ok){el.innerHTML=`<span class="bad">${esc(r.error)}</span>`;return}
    const ph=mode()==="purge"?"PURGE":"REMOVE";o.querySelector("#rm-ph").textContent=ph;o.querySelector("#rm-ok").textContent=mode()==="purge"?"Purge":"Remove";
    const ok=r.studies.filter(x=>!x.refused),calls=ok.filter(x=>x.has_calls).length,pv=ok.filter(x=>x.pensieve&&x.pensieve.exists);
    {const b=o.querySelector("#rm-pv");b.style.display=pv.length?"":"none";o.querySelector("#rm-pvtxt").textContent=pv.length?`${pv.length} of these studies (${gbx(pv.reduce((a,x)=>a+x.pensieve.bytes,0))})${pv.some(x=>x.pensieve.state==="in_pensieve")?" - for some, the images exist ONLY there":""}`:""}
    el.innerHTML=`${ok.length} studies · ${ok.reduce((a,x)=>a+x.n_trash,0)} items (${gbx(ok.reduce((a,x)=>a+x.bytes_trash,0))}) to the Trash${mode()==="remove"?` · ${ok.reduce((a,x)=>a+x.n_keep,0)} result files kept`:""}
      ${calls&&mode()==="purge"?`<div class="warn">⚠ ${calls} of these studies have reviewer calls (expert labels) - Purge deletes them too.</div>`:""}
      ${r.vault_needed?'<div class="warn">Remove releases the accession number into the encrypted audit: unlock the identity vault first (Standard).</div>':""}
      ${r.studies.filter(x=>x.refused).map(x=>`<div class="bad">${esc(x.label)}: ${esc(x.refused)}</div>`).join("")}
      <details><summary>per study</summary><table>${r.studies.map(x=>`<tr><td>${esc(x.label)}</td><td>${x.refused?esc(x.refused):`${x.n_trash} to the Trash (${gbx(x.bytes_trash)})${mode()==="remove"?` · ${x.n_keep} kept`:""}${x.has_calls?" · has reviewer calls":""}`}</td></tr>`).join("")}</table></details>`};
  o.querySelectorAll('input[name="rmm"]').forEach(x=>x.onchange=sum);o.querySelector("#rm-x").onclick=()=>o.remove();
  o.querySelector("#rm-ok").onclick=async()=>{const r=await api("/api/sa/remove",{codes,mode:mode(),confirm_phrase:o.querySelector("#rm-c").value,delete_library:o.querySelector("#rm-lib").checked,pensieve:o.querySelector("#rm-pvsel").value||null});
    if(r.needs_confirm||(!r.ok&&!r.done)){o.querySelector("#rm-err").textContent=r.error||(r.refused||[]).map(x=>x.why).join("; ");return}
    o.remove();toast(`${r.done.length} studies ${mode()==="purge"?"purged":"removed (results kept for ML)"} · moved to ${esc(r.trash||"the Trash")}${r.refused.length?` · ${r.refused.length} refused`:""}`);W.sel.clear();W.data=null;S=await api("/api/state");render()};
  sum()}
