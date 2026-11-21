// identity_view.js - v5.16 Standard / Incognito mode switch (header), identity vault, Edit identifiers dialog, study identifier cell.
// The server decides what is shown: in Incognito or with a locked vault it never sends MRN, patient name or accession number.
const IDV={st:null};
async function idRefresh(){try{IDV.st=await api("/api/id/state")}catch(e){IDV.st=null}idSwitch()}
function idSwitch(){const el=$("#idmode");if(!el||!IDV.st)return;const s=IDV.st,std=s.mode==="standard";
  el.innerHTML=`<span class="seg" data-id="mode" title="Standard: accession number + MRN / name (vault unlocked). Incognito: de-identified study codes only.">
    <button data-m="standard" class="${std?"on":""}">${std&&!s.unlocked?"🔒 ":""}Standard</button><button data-m="incognito" class="${std?"":"on"}">Incognito</button></span>
   ${std&&!s.unlocked?'<button class="b sm" id="idunlock" title="identities hidden until the vault is unlocked">Unlock</button>':""}`;
  el.querySelectorAll("[data-m]").forEach(b=>b.onclick=()=>idSetMode(b.dataset.m));$("#idunlock")&&($("#idunlock").onclick=()=>idSetMode("standard"))}
function idModal(html){const o=document.createElement("div");o.id="id-ov";o.style.cssText="position:fixed;inset:0;background:#0009;z-index:70;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:50px 16px";
  o.innerHTML=`<div class="card" style="width:min(760px,100%);margin:0" data-id="modal">${html}</div>`;o.onclick=e=>{if(e.target===o)o.remove()};document.body.appendChild(o);return o}
async function idSetMode(m){const s=IDV.st||{};
  if(m==="incognito"){const r=await api("/api/id/mode",{mode:"incognito"});if(!r.ok)return toast(esc(r.error),1);await idRefresh();return render()}
  if(!s.vault_exists)return idCreateVault();
  if(s.unlocked){const r=await api("/api/id/mode",{mode:"standard"});if(!r.ok)return toast(esc(r.error),1);await idRefresh();return render()}
  const o=idModal(`<h2>Show patient identities</h2><p class="note">Standard mode shows MRN, patient name and accession number from the encrypted identity vault on this computer.
    Enter the vault passphrase (it is kept in memory only until you quit or switch to Incognito).</p>
    <div class="row"><input type="password" id="id-pw" style="width:300px" autocomplete="off" placeholder="vault passphrase"><button class="b pri" id="id-go">Unlock</button><button class="b" id="id-x">Cancel</button></div><p class="bad" id="id-err"></p>`);
  const go=async()=>{const r=await api("/api/id/mode",{mode:"standard",passphrase:$("#id-pw").value});if(!r.ok){$("#id-err").textContent=r.error;return}o.remove();await idRefresh();render()};
  $("#id-go").onclick=go;$("#id-pw").onkeydown=e=>{if(e.key==="Enter")go()};$("#id-x").onclick=()=>o.remove();$("#id-pw").focus()}
function idCreateVault(){const o=idModal(`<h2>Set up the identity vault</h2><p class="note">MRN, patient names and accession numbers are kept ONLY in an encrypted file on this computer
   (private/identity_vault.enc, AES-256-GCM). Choose a passphrase of at least 10 characters. There is no recovery without it: keep it safe, and make a vault backup
   (Settings › Identity). Existing names in private/names.csv are copied in; that file is not changed.</p>
   <div class="row" style="flex-wrap:wrap"><input type="password" id="id-p1" placeholder="passphrase" style="width:240px" autocomplete="new-password"><input type="password" id="id-p2" placeholder="repeat passphrase" style="width:240px" autocomplete="new-password">
   <button class="b pri" id="id-mk">Create vault</button><button class="b" id="id-x">Cancel</button></div><p class="bad" id="id-err"></p>`);
  $("#id-x").onclick=()=>o.remove();
  $("#id-mk").onclick=async()=>{if($("#id-p1").value!==$("#id-p2").value){$("#id-err").textContent="the two passphrases differ";return}
    const r=await api("/api/id/vault/create",{passphrase:$("#id-p1").value});if(!r.ok){$("#id-err").textContent=r.error;return}
    const m=await api("/api/id/mode",{mode:"standard"});o.remove();toast(`vault created${r.names_copied?` · ${r.names_copied} names copied in`:""}`);await idRefresh();render()}}
function idCell(x){const r=x.r||{},i=r.ident||(x.p&&x.p.ident)||{},s=IDV.st||{};
  const id=i.study_id||x.code,kind=i.id_kind||"study code";
  return `<span class="code" title="${esc(kind)}">${esc(id||"—")}</span>${i.accession_missing?' <span class="pill bad" data-id="acc-missing" title="Standard mode: enter the accession number">accession missing</span>':""}
   ${i.display_name?`<span class="sub2">${esc(i.display_name)}</span>`:""}`}
// v5.18 Patient column: Standard shows name · MRN (examinations grouped by MRN); Incognito shows only the incognito icon (no grouping)
function patCell(x){const r=x.r||{},i=r.ident||(x.p&&x.p.ident)||{},s=IDV.st||{};
  if(s.mode!=="standard"||i.locked)return typeof INCOG_ICON!=="undefined"?INCOG_ICON:'<span class="mut" title="hidden in Incognito">hidden</span>';
  const pat=[i.patient_name,i.mrn?`MRN ${i.mrn}`:""].filter(Boolean).join(" · ");
  return pat?`${esc(pat)}${i.n_exams_of_patient>1?`<span class="sub2">${i.n_exams_of_patient} examinations</span>`:""}`:'<span class="bad">MRN missing</span>'}
async function openIdEdit(code){const v=await api(`/api/id/study?code=${encodeURIComponent(code)}`),s=IDV.st||{},std=s.mode==="standard"&&!v.locked;
  const H=await api(`/api/id/history?code=${encodeURIComponent(code)}`);
  const f=(k,l,val,note)=>`<label style="display:block;margin:6px 0"><span class="note" style="display:inline-block;width:190px">${l}</span><input data-f="${k}" value="${esc(val||"")}" style="width:300px">${note?` <span class="note">${note}</span>`:""}</label>`;
  const o=idModal(`<h2>Edit identifiers · ${esc(v.study_id||code)}</h2>
   <p class="note">Internal identifiers never change (study ${esc((v.study_uuid||"").slice(0,8))}… · file key ${esc(v.file_key||code)}). Processing history, calls, candidates and AI results stay linked.</p>
   <div class="card"><b>Patient</b> <span class="note">applies to all ${v.n_exams_of_patient||1} examination(s) of this patient</span>
    ${std?f("mrn","MRN",v.mrn)+f("patient_name","Patient name",v.patient_name):f("pseudonym","De-identified patient identity",v.patient_pseudonym)}</div>
   <div class="card"><b>This examination</b>${f("display_name","Study display name",v.display_name,"free text, not an identifier")}
    ${std?f("accession","Accession number",v.accession,"unique; required in Standard mode"):""}${f("deid_code","De-identified study code",v.deid_code,"unique; required")}</div>
   ${s.mode==="standard"&&v.locked?'<p class="warn">The vault is locked: MRN, name and accession can be edited after unlocking.</p>':""}
   <label class="note">Reason for the change <input id="id-why" style="width:420px" placeholder="e.g. typo in the accession number"></label>
   <div class="row" style="margin-top:10px"><button class="b pri" id="id-save">Save</button><button class="b" id="id-x">Cancel</button><span class="bad" id="id-err"></span></div>
   ${(H.history||[]).length?`<details style="margin-top:10px"><summary class="note">Change history (${H.history.length})</summary><table>${H.history.slice(-30).reverse().map(h=>`<tr><td class="mono">${esc(h.time)}</td><td>${esc(h.field)}</td><td class="note">${h.old!==undefined?`${esc(h.old)} → ${esc(h.new)}`:"(sensitive: values in the vault)"}</td><td class="note">${esc(h.by||"")} ${esc(h.reason||"")}</td></tr>`).join("")}</table></details>`:""}`);
  $("#id-x").onclick=()=>o.remove();
  $("#id-save").onclick=async()=>{const d={code,reason:$("#id-why").value};o.querySelectorAll("[data-f]").forEach(el=>{const k=el.dataset.f,old=v[k]||"";if(el.value.trim()!==old)d[k]=el.value.trim()});
    if(Object.keys(d).length<=2){o.remove();return}
    const sens=["mrn","patient_name","accession"].filter(k=>k in d);
    if(sens.length&&!confirm(`Change ${sens.join(", ")} of this ${sens.some(k=>k!=="accession")?"patient (all examinations)":"examination"}? The previous value is kept in the encrypted audit history.`))return;
    if(sens.length)d.confirm=true;const r=await api("/api/id/edit",d);if(!r.ok){$("#id-err").textContent=r.error;return}o.remove();toast("identifiers saved");render()}}
async function openVault(){const s=IDV.st||await api("/api/id/state");
  const o=idModal(`<h2>Identity vault</h2><p class="note">Encrypted file on this computer: MRN, names, accession numbers and their change history. Never exported, uploaded or logged.</p>
   <div class="kv"><div>Vault</div><div>${s.vault_exists?(s.unlocked?'<span class="ok">unlocked (this session)</span>':"locked"):'<span class="warn">not set up</span>'}</div><div>Mode</div><div>${esc(s.mode)}</div>
    <div>Studies / patients</div><div>${s.n_studies} / ${s.n_patients}</div><div>Missing accession numbers</div><div>${s.accession_missing}</div></div>
   <div class="row" style="flex-wrap:wrap;margin-top:10px">${s.vault_exists?"":'<button class="b pri" id="iv-new">Set up vault</button>'}
    ${s.unlocked?'<button class="b" id="iv-lock">Lock now</button><button class="b" id="iv-bk">Back up (encrypted)…</button><button class="b" id="iv-pw">Change passphrase…</button>':""}
    <button class="b" id="iv-rs">Validate / restore a backup…</button><a class="b" href="/api/id/template.xlsx" data-id="template">Download Percival_Import_Template.xlsx</a><button class="b" id="iv-x">Close</button></div><p class="bad" id="iv-err"></p>`);
  const E=m=>$("#iv-err").textContent=m;$("#iv-x").onclick=()=>o.remove();$("#iv-new")&&($("#iv-new").onclick=()=>{o.remove();idCreateVault()});
  $("#iv-lock")&&($("#iv-lock").onclick=async()=>{await api("/api/id/vault/lock",{});o.remove();await idRefresh();render()});
  $("#iv-bk")&&($("#iv-bk").onclick=async()=>{const d=await pick("folder","Choose a LOCAL folder for the encrypted vault backup");if(!d)return;const r=await api("/api/id/vault/backup",{dest:d});r.ok?toast("backup written: "+esc(r.path)):E(r.error)});
  $("#iv-pw")&&($("#iv-pw").onclick=async()=>{const a=prompt("Current passphrase");if(a===null)return;const b=prompt("New passphrase (10+ characters)");if(!b)return;const r=await api("/api/id/vault/change",{old:a,new:b});r.ok?toast("passphrase changed"):E(r.error)});
  $("#iv-rs").onclick=async()=>{const f=await pick("file","Choose an encrypted vault backup (.enc)");if(!f)return;const pw=prompt("Passphrase of that backup");if(pw===null)return;
    const v=await api("/api/id/vault/validate",{path:f,passphrase:pw});if(v.error||v.ok===false)return E(v.error||"invalid backup");
    if(!confirm(`Backup is valid: ${v.patients} patients, ${v.studies} studies. Replace the current vault with it? (the current vault is kept as a backup first)`))return;
    const r=await api("/api/id/vault/restore",{path:f,passphrase:pw});r.ok?(toast("vault restored"),o.remove(),idRefresh().then(render)):E(r.error)}}
idRefresh();
