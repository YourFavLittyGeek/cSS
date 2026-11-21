// setup_view.js - v5.17 first-run setup wizard: 1 installation checklist (required vs optional), 2 FreeSurfer folder + licence (browse,
// validate, test, save), 3 readiness report. Opens by itself on the first start; later from Settings › Setup. Never shows licence contents.
const SU={step:1,home:"",lic:"",v:null,l:null,t:null};
async function setupView(v){const r=await api("/api/setup/state");if(V!=="setup")return;
  if(r.error){v.innerHTML=`<div class="card bad">${esc(r.error)}</div>`;return}
  if(!SU.home)SU.home=r.settings.freesurfer_home||"";if(!SU.lic)SU.lic=r.settings.fs_license||"";
  const R=r.report,grp=[...new Set(r.items.map(i=>i.group))];
  const row=i=>`<tr data-su="${esc(i.id)}"><td style="width:28px" class="${i.ok?"ok":i.required?"bad":"warn"}">${i.ok?"✓":i.required?"✗":"–"}</td><td style="width:240px">${esc(i.label)} ${i.required?'<span class="pill">required</span>':'<span class="pill">optional</span>'}</td><td class="note" style="overflow-wrap:anywhere">${esc(i.detail)}</td></tr>`;
  const steps=[[1,"1 · Installation check"],[2,"2 · FreeSurfer and licence"],[3,"3 · Readiness report"]];
  v.innerHTML=`<div class="banner ${R.ready?"":"w"}" data-su="banner"><b>${r.first_run?"Welcome to Percival — first-run setup":"Setup"}</b><span class="mut">${R.ready?"Every required item is ready.":`${R.required_total-R.required_ok} required item(s) need attention.`} Optional items can be added later.</span></div>
   <div class="tbar">${seg("su-step",steps.map(([k,t])=>[String(k),t]),String(SU.step))}<span class="sp"></span><button class="b" id="su-retry">Check again</button></div><div id="su-body"></div>`;
  bindSeg("su-step",x=>{SU.step=+x;setupView(v)});$("#su-retry").onclick=()=>setupView(v);const el=$("#su-body");
  if(SU.step===1){el.innerHTML=grp.map(g=>`<div class="card"><b>${esc(g)}</b><table>${r.items.filter(i=>i.group===g).map(row).join("")}</table></div>`).join("")+
      `<div class="row"><button class="b pri" onclick="SU.step=2;setupView($('#view'))">Next: FreeSurfer ▸</button></div>`}
  if(SU.step===2){const fsItem=r.items.find(i=>i.id==="freesurfer"),lcItem=r.items.find(i=>i.id==="license");
    el.innerHTML=`<div class="card" data-su="fs"><h2>FreeSurfer installation</h2><p class="note">${fsItem.ok?"Found: "+esc(fsItem.detail):"FreeSurfer was not found. Choose its folder (it contains bin/ and build-stamp.txt, e.g. /Applications/freesurfer/8.2.0). Percival does not assume a fixed location."}</p>
      <div class="row" style="flex-wrap:wrap"><input id="su-home" style="width:min(520px,100%)" value="${esc(SU.home)}" placeholder="FreeSurfer folder"><button class="b" id="su-hb">Browse…</button><button class="b" id="su-hv">Validate</button></div>
      <p class="note" id="su-hm">${SU.v?(SU.v.ok?`<span class="ok">✓ FreeSurfer ${esc(SU.v.version||"")}</span>${SU.v.warning?` <span class="warn">${esc(SU.v.warning)}</span>`:""}`:`<span class="bad">✗ ${esc(SU.v.error)}</span>`):""}</p></div>
     <div class="card" data-su="lic"><h2>FreeSurfer licence</h2><p class="note">${lcItem.ok?"Found: "+esc(lcItem.detail):"Choose your FreeSurfer licence file (license.txt). It is checked on this computer; its contents are never shown, copied or sent anywhere."}</p>
      <div class="row" style="flex-wrap:wrap"><input id="su-lic" style="width:min(520px,100%)" value="${esc(SU.lic)}" placeholder="license.txt"><button class="b" id="su-lb">Browse…</button><button class="b" id="su-lv">Validate</button></div>
      <p class="note" id="su-lm">${SU.l?(SU.l.ok?'<span class="ok">✓ the file has the structure of a FreeSurfer licence (contents not shown)</span>':`<span class="bad">✗ ${esc(SU.l.error)}</span>`):""}</p></div>
     <div class="row"><button class="b" id="su-test">Test the installation</button><button class="b pri" id="su-save">Save configuration</button><span class="note" id="su-tm">${SU.t?(SU.t.ok?`<span class="ok">✓ FreeSurfer runs: ${esc(SU.t.version_line)}</span>`:`<span class="bad">✗ ${esc(SU.t.error)}</span>`):""}</span></div>
     <div class="row"><button class="b pri" onclick="SU.step=3;setupView($('#view'))">Next: readiness report ▸</button></div>`;
    $("#su-home").onchange=e=>SU.home=e.target.value.trim();$("#su-lic").onchange=e=>SU.lic=e.target.value.trim();
    $("#su-hb").onclick=async()=>{const p=await pick("folder","Choose the FreeSurfer folder");if(p){SU.home=p.replace(/\/$/,"");SU.v=await api("/api/setup/validate_fs",{path:SU.home});setupView(v)}};
    $("#su-lb").onclick=async()=>{const p=await pick("file","Choose the FreeSurfer licence file");if(p){SU.lic=p;SU.l=await api("/api/setup/validate_license",{path:SU.lic});setupView(v)}};
    $("#su-hv").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.v=await api("/api/setup/validate_fs",{path:SU.home});setupView(v)};
    $("#su-lv").onclick=async()=>{SU.lic=$("#su-lic").value.trim();SU.l=await api("/api/setup/validate_license",{path:SU.lic});setupView(v)};
    $("#su-test").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.lic=$("#su-lic").value.trim();$("#su-tm").textContent="testing…";SU.t=await api("/api/setup/test",{home:SU.home,license:SU.lic});setupView(v)};
    $("#su-save").onclick=async()=>{SU.home=$("#su-home").value.trim();SU.lic=$("#su-lic").value.trim();const x=await api("/api/setup/save",{home:SU.home,license:SU.lic});toast(x.ok?"configuration saved on this Mac":esc(x.error),!x.ok);setupView(v)}}
  if(SU.step===3){el.innerHTML=`<div class="card" data-su="report"><div class="row"><h2 style="margin:0">Readiness report</h2><span class="pill ${R.ready?"ok":"bad"}">${R.ready?"ready":"not ready"}</span><span class="note">required ${R.required_ok}/${R.required_total} · optional ${R.optional_ok}/${R.optional_total} · ${esc(R.created)}</span></div>
      <table>${r.items.map(row).join("")}</table>
      <p class="note">The report is saved in app_data/setup_report.json (no licence content). Percival works offline once these items are installed.</p>
      <div class="row"><button class="b pri" id="su-fin">${R.ready?"Finish setup":"Finish anyway (fix the ✗ items later in Settings › Setup)"}</button></div></div>`;
    $("#su-fin").onclick=async()=>{const x=await api("/api/setup/finish",{});if(!x.ok)return toast(esc(x.error),1);toast("setup finished");go("studies")}}}
(async()=>{try{const r=await api("/api/setup/first_run");if(r.first_run&&!location.hash)go("setup")}catch(e){}})();
