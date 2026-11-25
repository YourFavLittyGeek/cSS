// qc_view.js - "Anatomy QC" screen (restored in v5.15): FreeSurfer installation, per-study FreeSurfer / SynthSeg / registration outputs,
// detector QC metrics, the QC image (labels + brain mask on the SWI) and Freeview. Talks to /api/fsqc/* (app/qc_gui.py).
// A study shows "QC ok" ONLY when the required files exist and the recorded QC status is ok; missing files are listed, never hidden.
const QCV={code:(location.hash.match(/^#qc:([\w-]+)/)||[])[1]||"",f:"all"};
const qcVerdict={ok:["QC ok","ok"],low_confidence:["low confidence","warn"],insufficient_quality:["insufficient quality","bad"],missing_outputs:["outputs missing","bad"],
  failed:["FreeSurfer error","bad"],not_processed:["not processed",""],unknown:["QC not recorded","warn"],in_pensieve:["in Pensieve","mut"]};
const qcPill=v=>{const m=qcVerdict[v]||[v,""];return `<span class="pill ${m[1]}" data-qcv="${esc(v)}">${esc(m[0])}</span>`};
const qcFile=s=>s==="present"?'<span class="ok">✓ present</span>':s==="missing"?'<span class="bad">✗ missing</span>':`<span class="warn">⚠ ${esc(s)}</span>`;
async function qcView(v){
  const st=await api("/api/fsqc/state");if(V!=="qc")return;
  if(st.error){v.innerHTML=`<div class="card"><b class="bad">Anatomy QC unavailable</b><p class="note">${esc(st.error)}</p></div>`;return}
  const I=st.install,L=I.license||{},S_=st.studies,cnt=k=>S_.filter(s=>k==="all"||s.verdict===k).length;
  const tools=Object.entries(I.tools||{}).map(([k,p])=>`<span class="pill ${p?"ok":"bad"}" title="${esc(p||"not found")}">${p?"✓":"✗"} ${esc(k)}</span>`).join(" ");
  v.innerHTML=`<div class="card" data-qc="install"><div class="row" style="justify-content:space-between"><h2 style="margin:0">FreeSurfer installation</h2>
     ${I.ready?'<span class="pill ok">ready</span>':'<span class="pill bad">needs attention</span>'}</div>
    <div class="kv" style="margin-top:8px"><div>Folder</div><div class="mono">${esc(I.home||"not set")}${I.home&&!I.home_exists?' <span class="bad">(folder not found)</span>':""}</div>
     <div>Version</div><div>${esc(I.version||"unknown (build-stamp.txt not found)")}</div>
     <div>Licence</div><div>${L.readable?`<span class="ok">✓ found and readable</span> <span class="mono">${esc(L.path)}</span>`:L.exists?'<span class="bad">✗ found but not readable</span>':'<span class="bad">✗ not found</span>'} <span class="note">(contents never shown)</span></div>
     <div>Tools</div><div>${tools}</div></div>
    ${I.ready?"":`<p class="note">Set the FreeSurfer folder and licence in <a href="#" onclick="W.setTab='system';go('set');return false">Settings › System</a>.</p>`}</div>
   <div class="tbar"><span class="seg">${[["all","All"],["ok","QC ok"],["low_confidence","Low confidence"],["missing_outputs","Outputs missing"],["insufficient_quality","Insufficient"],["not_processed","Not processed"]]
     .map(([k,t])=>`<button data-qf="${k}" class="${QCV.f===k?"on":""}">${t} <span class="mut">${cnt(k)}</span></button>`).join("")}</span></div>
   <div class="card" style="padding:0"><table data-qc="studies"><tr><th>Study</th><th>Anatomy route</th><th>QC</th><th>Label shift</th><th>Edge agreement</th><th>Registration</th><th>QC image</th><th>Why</th></tr>
    ${S_.filter(s=>QCV.f==="all"||s.verdict===QCV.f).map(s=>`<tr data-qcs="${esc(s.code)}" style="cursor:pointer" class="${QCV.code===s.code?"sel":""}"><td><b>${sidH(s.code)}</b></td><td>${esc(s.route)}</td><td>${qcPill(s.verdict)}</td>
      <td>${s.metrics.label_shift_mm!=null?`${(+s.metrics.label_shift_mm).toFixed(2)} mm`:"–"}</td><td>${s.metrics.edge_agreement_mm!=null?`${(+s.metrics.edge_agreement_mm).toFixed(2)} mm`:"–"}</td>
      <td class="note">${s.metrics.registration?esc(`${s.metrics.registration.method||""} ${s.metrics.registration.cost!=null?"cost "+s.metrics.registration.cost:""}`):"–"}</td>
      <td>${s.snapshot.exists?(s.snapshot.stale?'<span class="warn">older than inputs</span>':'<span class="ok">yes</span>'):'<span class="mut">none</span>'}</td><td class="note" style="max-width:340px">${esc(s.why)}</td></tr>`).join("")}
    ${S_.length?"":'<tr><td colspan="8" class="note">No studies in this project yet.</td></tr>'}</table></div><div id="qc-detail"></div>`;
  v.querySelectorAll("[data-qf]").forEach(b=>b.onclick=()=>{QCV.f=b.dataset.qf;qcView(v)});
  v.querySelectorAll("[data-qcs]").forEach(tr=>tr.onclick=()=>{QCV.code=tr.dataset.qcs;qcView(v)});
  if(QCV.code){const s=S_.find(x=>x.code===QCV.code);if(s)qcDetail(s)}}
function qcDetail(s){
  const el=$("#qc-detail");if(!el)return;const fs=Object.entries(s.freesurfer||{}),wk=Object.entries(s.work||{}),M=s.metrics||{};
  el.innerHTML=`<div class="card" data-qc="detail"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${sidH(s.code)} · ${esc(s.route)} ${qcPill(s.verdict)}</h2>
     <div class="row"><button class="b" id="qc-snap" ${s.snapshot.can_make?"":"disabled"} title="${esc(s.snapshot.why_not||"")}">${s.snapshot.exists?"Re-make QC image":"Make QC image"}</button>
      <button class="b" id="qc-fv1" title="SWI with the labels used by the detector">Freeview: labels on SWI</button>
      <button class="b" id="qc-fv2" ${s.freesurfer_dir?"":"disabled"} title="FreeSurfer orig + aparc+aseg + surfaces">Freeview: FreeSurfer recon</button></div></div>
    <p class="note">${esc(s.why)}</p>
    ${s.snapshot.exists?`<img data-qc="image" src="/api/qc?code=${encodeURIComponent(s.code)}&t=${Date.now()}" style="max-width:100%;border-radius:8px">
      <p class="note">Cyan = cortex labels, yellow = brain mask, on three SWI slices. They should follow the anatomy; a shift or a cut-off brain part means the registration or the mask is wrong.</p>`
     :`<p class="warn" data-qc="no-image">No QC image yet${s.snapshot.can_make?" — press Make QC image.":` — cannot be made: ${esc(s.snapshot.why_not)}.`}</p>`}
    <div class="row" style="align-items:flex-start;gap:24px;flex-wrap:wrap">
     <div><h3>Detector QC record</h3>${Object.keys(M).length?`<table>${Object.entries(M).map(([k,x])=>`<tr><td class="note">${esc(k)}</td><td>${esc(typeof x==="object"?JSON.stringify(x):x)}</td></tr>`).join("")}</table>`:'<p class="bad">no review/ID_qc.json</p>'}</div>
     <div><h3>Pipeline outputs</h3><table data-qc="work">${wk.map(([k,x])=>`<tr><td class="mono">${esc(k)}</td><td>${qcFile(x)}</td></tr>`).join("")}</table></div>
     ${fs.length?`<div><h3>FreeSurfer recon <span class="note">${esc(s.freesurfer_dir)} ${esc(s.freesurfer_version)}</span></h3><table data-qc="fs">${fs.map(([k,x])=>`<tr><td class="mono">${esc(k)}</td><td>${qcFile(x)}</td></tr>`).join("")}</table></div>`:""}
     ${s.stages&&!s.stages.error?`<div><h3>Reuse check (Process Manager)</h3><table>${Object.entries(s.stages).map(([k,x])=>`<tr><td>${esc(k)}</td><td>${esc(x.label)}</td><td class="note">${esc(x.why)}</td></tr>`).join("")}</table></div>`:""}</div></div>`;
  $("#qc-snap").onclick=async()=>{toast("making the QC image…");const r=await api("/api/fsqc/snapshot",{code:s.code});toast(r.ok?"QC image made":esc(r.error),!r.ok);qcView($("#view"))};
  $("#qc-fv1").onclick=async()=>{const r=await api("/api/fsqc/freeview",{code:s.code,what:"swi"});toast(r.ok?"Freeview opening…":esc(r.error),!r.ok)};
  $("#qc-fv2").onclick=async()=>{const r=await api("/api/fsqc/freeview",{code:s.code,what:"recon"});toast(r.ok?"Freeview opening…":esc(r.error),!r.ok)};
}
