// setup_view.js - First-run installation and storage configuration wizard.
// 1. Installation checklist (system, packages, tools)
// 2. Storage Topology & Data Vault (working directory, external vault for Pensieve, candidate re-detection & calling)
// 3. FreeSurfer folder + licence (browse, validate, test, save)
// 4. Readiness report & finalization. Never shows licence contents.

const SU={step:1,home:"",lic:"",work:"",vault:"",redetect:true,calling:true,v:null,l:null,t:null};

async function setupView(v){
  const r=await api("/api/setup/state");
  if(V!=="setup")return;
  if(r.error){v.innerHTML=`<div class="card bad">${esc(r.error)}</div>`;return}
  if(!SU.home)SU.home=r.settings.freesurfer_home||"";
  if(!SU.lic)SU.lic=r.settings.fs_license||"";
  if(!SU.work)SU.work=r.settings.workspace_dir||"";
  if(!SU.vault)SU.vault=r.settings.vault_mount||(r.detected_volumes&&r.detected_volumes[0]?r.detected_volumes[0].vault_path:"");
  if(r.settings.candidate_redetection!==undefined)SU.redetect=r.settings.candidate_redetection;
  if(r.settings.candidate_calling!==undefined)SU.calling=r.settings.candidate_calling;

  const R=r.report,grp=[...new Set(r.items.map(i=>i.group))];
  const row=i=>`<tr data-su="${esc(i.id)}"><td style="width:28px" class="${i.ok?"ok":i.required?"bad":"warn"}">${i.ok?"✓":i.required?"✗":"–"}</td><td style="width:240px">${esc(i.label)} ${i.required?'<span class="pill">required</span>':'<span class="pill">optional</span>'}</td><td class="note" style="overflow-wrap:anywhere">${esc(i.detail)}</td></tr>`;
  const steps=[
    [1,"1 · Installation check"],
    [2,"2 · Storage & Data Vault"],
    [3,"3 · FreeSurfer and licence"],
    [4,"4 · Readiness report"]
  ];

  v.innerHTML=`<div class="banner ${R.ready?"":"w"}" data-su="banner"><b>${r.first_run?"Welcome to Percival — First-Run Setup & Installation":"Setup & Configuration"}</b><span class="mut">${R.ready?"Every required item is ready.":`${R.required_total-R.required_ok} required item(s) need attention.`} Optional items can be configured later.</span></div>
   <div class="tbar">${seg("su-step",steps.map(([k,t])=>[String(k),t]),String(SU.step))}<span class="sp"></span><button class="b" id="su-retry">Check again</button></div><div id="su-body"></div>`;
  bindSeg("su-step",x=>{SU.step=+x;setupView(v)});
  $("#su-retry").onclick=()=>setupView(v);
  const el=$("#su-body");

  // Step 1: System and package checks
  if(SU.step===1){
    el.innerHTML=grp.map(g=>`<div class="card"><b>${esc(g)}</b><table>${r.items.filter(i=>i.group===g).map(row).join("")}</table></div>`).join("")+
      `<div class="row"><button class="b pri" onclick="SU.step=2;setupView($('#view'))">Next: Storage &amp; Data Vault ▸</button></div>`;
  }

  // Step 2: Storage Topology, Working Directory, External Vault (Pensieve), and Candidate Detection
  if(SU.step===2){
    const vols=r.detected_volumes||[];
    el.innerHTML=`<div class="card" data-su="storage">
      <h2>Storage Topology &amp; Data Vault Setup</h2>
      <p class="note">PERCIVAL uses a dual-storage topology to prevent internal Mac SSD exhaustion while guaranteeing ultra-fast processing speeds.</p>
      
      <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--line)">
        <b>1. Local Working Directory (Fast Internal Mac NVMe SSD)</b>
        <p class="note">High-speed local SSD directory for active MRI ingestion, intermediate FreeSurfer surface extraction, and scratch buffers.</p>
        <div class="row" style="flex-wrap:wrap">
          <input id="su-work" style="width:min(520px,100%)" value="${esc(SU.work)}" placeholder="e.g. /Users/tarabeah.selim/Percival_project">
          <button class="b" id="su-wb">Browse…</button>
        </div>
      </div>

      <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--line)">
        <b>2. External Storage Data Vault (Pensieve Memory &amp; Archival)</b>
        <p class="note">High-capacity external volume for permanent Pensieve SQLite database memory (pensieve_core.db), cold study archival, and audit ledgers.</p>
        ${vols.length?`<div class="row" style="margin-bottom:8px">
          <span class="lab" style="min-width:180px">Detected External Drive:</span>
          <select id="su-vols" style="width:min(440px,100%)">
            <option value="">-- Choose detected external volume --</option>
            ${vols.map(vl=>`<option value="${esc(vl.vault_path)}">${esc(vl.name)} (${esc(vl.free_gb)} GB free) → ${esc(vl.vault_path)}</option>`).join("")}
          </select>
        </div>`:""}
        <div class="row" style="flex-wrap:wrap">
          <input id="su-vault" style="width:min(520px,100%)" value="${esc(SU.vault)}" placeholder="/Volumes/Percival/PERCIVAL_VAULT">
          <button class="b" id="su-vb">Browse…</button>
        </div>
      </div>

      <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--line)">
        <b>3. Candidate Re-detection &amp; Calling Policy</b>
        <div class="row" style="margin-top:8px">
          <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer">
            <input type="checkbox" id="su-redetect" ${SU.redetect?"checked":""} style="margin-top:3px">
            <span><b>Re-detect all candidates from original MRI series on processing</b><br><span class="note">Runs detection from scratch on the SWI series to locate all siderosis lesions with current pipeline parameters.</span></span>
          </label>
        </div>
        <div class="row" style="margin-top:10px">
          <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer">
            <input type="checkbox" id="su-calling" ${SU.calling?"checked":""} style="margin-top:3px">
            <span><b>Automated Candidate Calling &amp; Spatial Fingerprint Matching</b><br><span class="note">Matches existing reviewer/radiologist calls to newly detected candidates by 3D centroid and volume overlap so human calls are never lost.</span></span>
          </label>
        </div>
      </div>

      <div class="row" style="margin-top:16px">
        <button class="b pri" id="su-save-store">Save Storage &amp; Candidate Configuration</button>
        <span class="note" id="su-store-msg"></span>
      </div>
    </div>
    <div class="row"><button class="b pri" onclick="SU.step=3;setupView($('#view'))">Next: FreeSurfer ▸</button></div>`;

    $("#su-work").onchange=e=>SU.work=e.target.value.trim();
    $("#su-vault").onchange=e=>SU.vault=e.target.value.trim();
    $("#su-redetect").onchange=e=>SU.redetect=e.target.checked;
    $("#su-calling").onchange=e=>SU.calling=e.target.checked;
    if($("#su-vols")) $("#su-vols").onchange=e=>{ if(e.target.value) { SU.vault=e.target.value; $("#su-vault").value=e.target.value; } };
    $("#su-wb").onclick=async()=>{const p=await pick("folder","Choose the Local Working Directory");if(p){SU.work=p.replace(/\/$/,"");$("#su-work").value=SU.work;}};
    $("#su-vb").onclick=async()=>{const p=await pick("folder","Choose the External Data Vault folder or drive");if(p){SU.vault=p.replace(/\/$/,"")+"/PERCIVAL_VAULT";$("#su-vault").value=SU.vault;}};
    $("#su-save-store").onclick=async()=>{
      SU.work=$("#su-work").value.trim();
      SU.vault=$("#su-vault").value.trim();
      SU.redetect=$("#su-redetect").checked;
      SU.calling=$("#su-calling").checked;
      const x=await api("/api/setup/save",{workspace_dir:SU.work,vault_mount:SU.vault,candidate_redetection:SU.redetect,candidate_calling:SU.calling});
      $("#su-store-msg").innerHTML=x.ok?'<span class="ok">✓ Storage topology &amp; candidate policy saved</span>':`<span class="bad">✗ ${esc(x.error)}</span>`;
      toast(x.ok?"Storage topology saved":esc(x.error),!x.ok);
    };
  }

  // Step 3: FreeSurfer and Licence
  if(SU.step===3){
    const fsItem=r.items.find(i=>i.id==="freesurfer"),lcItem=r.items.find(i=>i.id==="license");
    el.innerHTML=`<div class="card" data-su="fs"><h2>FreeSurfer installation</h2><p class="note">${fsItem.ok?"Found: "+esc(fsItem.detail):"FreeSurfer was not found. Choose its folder (it contains bin/ and build-stamp.txt, e.g. /Applications/freesurfer/8.2.0). Percival does not assume a fixed location."}</p>
      <div class="row" style="flex-wrap:wrap"><input id="su-home" style="width:min(520px,100%)" value="${esc(SU.home)}" placeholder="FreeSurfer folder"><button class="b" id="su-hb">Browse…</button><button class="b" id="su-hv">Validate</button></div>
      <p class="note" id="su-hm">${SU.v?(SU.v.ok?`<span class="ok">✓ FreeSurfer ${esc(SU.v.version||"")}</span>${SU.v.warning?` <span class="warn">${esc(SU.v.warning)}</span>`:""}`:`<span class="bad">✗ ${esc(SU.v.error)}</span>`):""}</p></div>
     <div class="card" data-su="lic"><h2>FreeSurfer licence</h2><p class="note">${lcItem.ok?"Found: "+esc(lcItem.detail):"Choose your FreeSurfer licence file (license.txt). It is checked on this computer; its contents are never shown, copied or sent anywhere."}</p>
      <div class="row" style="flex-wrap:wrap"><input id="su-lic" style="width:min(520px,100%)" value="${esc(SU.lic)}" placeholder="license.txt"><button class="b" id="su-lb">Browse…</button><button class="b" id="su-lv">Validate</button></div>
      <p class="note" id="su-lm">${SU.l?(SU.l.ok?'<span class="ok">✓ the file has the structure of a FreeSurfer licence (contents not shown)</span>':`<span class="bad">✗ ${esc(SU.l.error)}</span>`):""}</p></div>
     <div class="row"><button class="b" id="su-test">Test the installation</button><button class="b pri" id="su-save">Save configuration</button><span class="note" id="su-tm">${SU.t?(SU.t.ok?`<span class="ok">✓ FreeSurfer runs: ${esc(SU.t.version_line)}</span>`:`<span class="bad">✗ ${esc(SU.t.error)}</span>`):""}</span></div>
     <div class="row"><button class="b pri" onclick="SU.step=4;setupView($('#view'))">Next: readiness report ▸</button></div>`;
    $("#su-home").onchange=e=>SU.home=e.target.value.trim();
    $("#su-lic").onchange=e=>SU.lic=e.target.value.trim();
    $("#su-hb").onclick=async()=>{const p=await pick("folder","Choose the FreeSurfer folder");if(p){SU.home=p.replace(/\/$/,"");SU.v=await api("/api/setup/validate_fs",{path:SU.home});setupView(v)}};
    $("#su-lb").onclick=async()=>{const p=await pick("file","Choose the FreeSurfer licence file");if(p){SU.lic=p;SU.l=await api("/api/setup/validate_license",{path:SU.lic});setupView(v)}};
    $("#su-hv").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.v=await api("/api/setup/validate_fs",{path:SU.home});setupView(v)};
    $("#su-lv").onclick=async()=>{SU.lic=$("#su-lic").value.trim();SU.l=await api("/api/setup/validate_license",{path:SU.lic});setupView(v)};
    $("#su-test").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.lic=$("#su-lic").value.trim();$("#su-tm").textContent="testing…";SU.t=await api("/api/setup/test",{home:SU.home,license:SU.lic});setupView(v)};
    $("#su-save").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.lic=$("#su-lic").value.trim();const x=await api("/api/setup/save",{home:SU.home,license:SU.lic,workspace_dir:SU.work,vault_mount:SU.vault,candidate_redetection:SU.redetect,candidate_calling:SU.calling});toast(x.ok?"configuration saved on this Mac":esc(x.error),!x.ok);setupView(v)};
  }

  // Step 4: Readiness report & finish
  if(SU.step===4){
    el.innerHTML=`<div class="card" data-su="report"><div class="row"><h2 style="margin:0">Readiness report</h2><span class="pill ${R.ready?"ok":"bad"}">${R.ready?"ready":"not ready"}</span><span class="note">required ${R.required_ok}/${R.required_total} · optional ${R.optional_ok}/${R.optional_total} · ${esc(R.created)}</span></div>
      <table>${r.items.map(row).join("")}</table>
      <div style="margin-top:14px;padding:10px 14px;background:var(--card);border-radius:6px;border:1px solid var(--line)">
        <b>Selected Configuration:</b>
        <div class="note" style="margin-top:4px">
          • <b>Working Directory:</b> ${esc(SU.work || "Default project")} (Local SSD)<br>
          • <b>External Data Vault:</b> ${esc(SU.vault || "Local emergency fallback")} (Pensieve memory &amp; archival)<br>
          • <b>Candidate Re-detection:</b> ${SU.redetect ? '<span class="ok">ENABLED (YES)</span>' : '<span class="warn">DISABLED</span>'}<br>
          • <b>Candidate Calling:</b> ${SU.calling ? '<span class="ok">ENABLED (YES)</span>' : '<span class="warn">DISABLED</span>'}
        </div>
      </div>
      <p class="note" style="margin-top:10px">The report is saved in app_data/setup_report.json (no licence content). Percival works 100% offline once these items are confirmed.</p>
      <div class="row"><button class="b pri" id="su-fin">${R.ready?"Finish setup &amp; Open Workspace":"Finish anyway (fix any ✗ items later in Setup Wizard)"}</button></div></div>`;
    $("#su-fin").onclick=async()=>{
      // Save all parameters before finishing
      await api("/api/setup/save",{home:SU.home,license:SU.lic,workspace_dir:SU.work,vault_mount:SU.vault,candidate_redetection:SU.redetect,candidate_calling:SU.calling});
      const x=await api("/api/setup/finish",{});
      if(!x.ok)return toast(esc(x.error),1);
      toast("Setup finished — opening workspace");
      go("studies");
    };
  }
}

// Auto-open Setup Wizard on first launch
(async()=>{
  try{
    const r=await api("/api/setup/first_run");
    if(r.first_run&&(!location.hash||location.hash==="#"||location.hash==="#studies")){
      go("setup");
    }
  }catch(e){}
})();
