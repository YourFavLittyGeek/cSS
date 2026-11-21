// export_view.js - v5.18 Studies › Export › Studies with files…: results and (as chosen) processed files, FreeSurfer, MRI and logs,
// copied to a local folder the user chooses and verified (sha256). Standard: <MRN>/<accession>/ · Incognito: <code>/ (no grouping).
const XE={parts:{results:true,processed:true,freesurfer:false,mri:false,logs:false},dest:""};
const XE_LBL={results:["Results","candidate tables, every reviewer's calls, scores, QC, lineage, Unified / Shadow / Image ML outputs, QC image (always)"],
  processed:["Processed files","pipeline images, registrations, segmentations, masks, candidate maps, run archive"],
  freesurfer:["FreeSurfer / SynthSeg folder","the study's anatomy folder (large)"],
  mri:["Original MRI","the study library copy (else the project's import copy); Incognito: NIfTI only - DICOM headers hold identifiers"],
  logs:["Processing logs","source paths hidden in Incognito"]};
const gb=b=>b>=1e9?`${(b/1e9).toFixed(2)} GB`:`${Math.max(0.01,b/1e6).toFixed(2)} MB`;
async function openFileExport(codes,label){if(!codes||!codes.length)return toast("no study to export",1);
  if(!XE.dest)XE.dest=(S.settings||{}).export_files_dir||(S.settings||{}).export_dir||"";
  const o=idModal(`<div data-xe="dlg"><h2>Export studies with files</h2><p class="note">${codes.length} studies (${esc(label||"")}). Files are copied to the folder you choose, then each is verified (sha256). Nothing is uploaded.</p>
    <div>${Object.entries(XE_LBL).map(([k,[t,d]])=>`<label style="display:block;margin:5px 0"><input type="checkbox" data-xp="${k}" ${XE.parts[k]?"checked":""} ${k==="results"?"disabled":""}> <b>${t}</b> <span class="note">${d}</span></label>`).join("")}</div>
    <div class="row" style="flex-wrap:wrap;margin-top:8px"><span class="lab" style="width:auto">Save in</span><input id="xe-d" style="width:min(460px,100%)" value="${esc(XE.dest)}" placeholder="a local folder, e.g. /Volumes/LabDisk/exports"><button class="b" id="xe-db">Choose folder…</button></div>
    <div id="xe-sum" class="note" style="margin:8px 0">checking…</div>
    <label class="note" style="display:block"><input type="checkbox" id="xe-ok"> I understand this export holds clinical-derived data${IDV.st&&IDV.st.mode==="standard"?" and patient identifiers (folders are named MRN / accession number)":""} and stays on approved local storage</label>
    <div class="row" style="margin-top:10px"><span class="sp"></span><button class="b" id="xe-x">Close</button><button class="b pri" id="xe-go" disabled>Export</button></div></div>`);
  const sum=async()=>{const r=await api("/api/xs/plan",{codes,parts:XE.parts,dest:XE.dest});const el=o.querySelector("#xe-sum");if(!el)return;
    if(r.ok===false){el.innerHTML=`<span class="bad">${esc(r.error)}</span>`;o.querySelector("#xe-go").disabled=true;return}
    const bad=r.problems.length||!r.dest_ok;
    el.innerHTML=`<b>${r.n_studies}</b> studies · <b>${r.n_files}</b> files · <b>${gb(r.bytes)}</b>${r.dest_ok?` · ${gb(r.free)} free at the destination`:""} · folders named ${r.mode==="standard"?"<code>MRN / accession number</code>":"<code>code</code>"}
      ${!r.dest_ok?`<div class="bad">${esc(r.dest_why)}</div>`:""}${r.problems.length?`<div class="bad">${r.problems.slice(0,8).map(esc).join("<br>")}</div>`:""}
      <details style="margin-top:4px"><summary>per study</summary><table>${r.studies.map(x=>`<tr><td class="mono">${esc(x.folder||x.study_id)}</td><td>${x.files} files</td><td>${gb(x.bytes)}</td><td class="bad">${esc(x.why||"")}</td></tr>`).join("")}</table></details>`;
    o.querySelector("#xe-go").disabled=bad};
  o.querySelectorAll("[data-xp]").forEach(c=>c.onchange=()=>{XE.parts[c.dataset.xp]=c.checked;sum()});
  o.querySelector("#xe-d").onchange=e=>{XE.dest=e.target.value.trim();sum()};
  o.querySelector("#xe-db").onclick=async()=>{const p=await pick("folder","Choose where to save the export");if(p){XE.dest=p.replace(/\/$/,"");o.querySelector("#xe-d").value=XE.dest;sum()}};
  o.querySelector("#xe-x").onclick=()=>o.remove();
  o.querySelector("#xe-go").onclick=async()=>{if(!o.querySelector("#xe-ok").checked)return toast("tick the confirmation first",1);
    const r=await api("/api/xs/start",{codes,parts:XE.parts,dest:XE.dest,confirm_clinical:true});if(!r.ok)return toast(esc(r.error),1);
    const el=o.querySelector("#xe-sum");o.querySelector("#xe-go").disabled=true;
    const poll=async()=>{const j=await api(`/api/xs/job?id=${encodeURIComponent(r.job)}`);if(!o.isConnected)return;
      el.innerHTML=j.state==="finished"?`<span class="ok" data-xe="done">✓ exported and verified: ${j.total_files} files</span> → <span class="mono">${esc(j.folder)}</span> <button class="b sm" id="xe-open">Open folder</button>`:
        j.state==="failed"?`<span class="bad">export failed: ${esc(j.error)} (nothing was left behind)</span>`:`copying… ${j.done_files} / ${j.total_files} files`;
      const ob=o.querySelector("#xe-open");if(ob)ob.onclick=()=>api("/api/open",{path:j.folder});
      if(j.state==="running")setTimeout(poll,800)};poll()};
  sum()}
