// calls_view.js - "Reviewer calls" panel, opened from the Studies screen and from the Model (training) screen.
// Phase 3A.3/3A.4: every reviewer's calls are kept. The EFFECTIVE call of a candidate (used for the score, the results and training) comes from
// the CONSENSUS of designated EXPERTS (or one reference expert); disagreements, abstentions and candidates without an expert call stay
// UNRESOLVED until an expert with the adjudication permission decides (recorded, reviewers' calls unchanged). Roles and the adjudication
// permission are set here by the local administrator with a typed confirmation and a reason; every change is kept in an append-only history.
// Newest-wins, the automatic primary reviewer and "rewrite old calls" were removed.
const CV={scope:"all",target:"",mode:"consensus",quorum:1,reviewer:"",fallback:"none"};
function cvClose(){const o=$("#cv-ov");if(o)o.remove()}
async function openCalls(){cvClose();const o=document.createElement("div");o.id="cv-ov";
  o.style.cssText="position:fixed;inset:0;background:#0009;z-index:60;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:40px 16px";
  o.innerHTML='<div class="card" id="cv" style="width:min(1100px,100%);margin:0" data-cv="panel"><span class="mut">loading…</span></div>';
  o.onclick=e=>{if(e.target===o)cvClose()};document.body.appendChild(o);document.addEventListener("keydown",cvEsc);cvRender()}
function cvEsc(e){if(e.key==="Escape"){cvClose();document.removeEventListener("keydown",cvEsc)}}
function cvAsk(q){const v=prompt(q);return v===null?null:v.trim()}
async function cvAdmin(op,body,phrase){const by=cvAsk("Your name (administrator):");if(!by)return;const reason=cvAsk("Reason (kept in the history):");if(!reason)return;
  const c=cvAsk(`Type exactly: ${phrase}`);if(c===null)return;const x=await api("/api/calls/"+op,Object.assign({by,reason,confirm:c},body));
  if(!x.ok)return toast(esc(x.error||"refused"),1);toast("recorded");cvRender()}
async function cvRender(){
  const el=$("#cv");if(!el)return;const r=await api("/api/calls/policy");
  if(r.error){el.innerHTML=`<b class="bad">Reviewer calls unavailable</b><p class="note">${esc(r.error)}</p>`;return}
  const P=r.policy,coh=r.cohorts,codes=r.studies.map(s=>s.code),R=r.roles||{};
  const names=[...new Set(r.reviewers.concat(Object.values(R).map(x=>x.name)))].sort();
  const roleOf=n=>{const x=Object.values(R).find(v=>v.name===n);return x||{role:"unknown",adjudicator:false}};
  const experts=names.filter(n=>roleOf(n).role==="expert");
  const ruleTxt=x=>x.mode==="reference"?`calls of the reference expert <b>${esc(x.reviewer)}</b>${x.fallback==="consensus"?" (expert consensus where they did not call)":" only"}`:
    `<b>consensus of designated experts</b> (at least ${x.quorum||1} definite expert call${(x.quorum||1)>1?"s":""}, all agreeing)${x.upgraded_from?` <span class="mut">(was '${esc(x.upgraded_from)}')</span>`:""}`;
  const targets=CV.scope==="cohort"?coh:CV.scope==="study"?codes:[];if(CV.scope!=="all"&&!targets.includes(CV.target))CV.target=targets[0]||"";
  const hist=(P.history||[]).slice(-8).reverse();const sc=s=>s.status_counts||{};
  el.innerHTML=`<div class="row" style="justify-content:space-between"><h2 style="margin:0">Reviewer calls</h2><button class="b" onclick="cvClose()">Close</button></div>
   <p class="note" style="max-width:900px">Every reviewer's calls are kept. A candidate's <b>effective call</b> (reader score, results, training) needs the agreement of the
   designated <b>experts</b>; disagreements, abstentions (Unsure) and candidates without an expert call stay <b>unresolved</b> until an adjudicator decides.
   Trainee, other and unknown reviewers are kept and shown but never decide. Imported or inherited calls do not count as independent reviews.</p>
   <div class="card" data-cv="roles"><b>Reviewer roles</b> <span class="note">(nobody is an expert until you say so; every change is kept in the history)</span>
     <table><tr><th>Reviewer</th><th>Role</th><th>Adjudication</th><th></th></tr>
     ${names.map(n=>{const x=roleOf(n);return `<tr><td>${esc(n)}</td><td><b>${esc(x.role)}</b></td><td>${x.adjudicator&&x.role==="expert"?"allowed":"–"}</td>
       <td><button class="b sm" data-cvrole="${esc(n)}">Set role…</button> ${x.role==="expert"?`<button class="b sm" data-cvadj="${esc(n)}|${x.adjudicator?0:1}">${x.adjudicator?"Withdraw adjudication…":"Allow adjudication…"}</button>`:""}</td></tr>`}).join("")||'<tr><td colspan="4" class="mut">no reviewer yet</td></tr>'}</table>
     <button class="b sm" id="cv-addrole">Add a reviewer name…</button></div>
   <div class="card" data-cv="current"><b>Current rules</b><table><tr><th style="width:150px">Applies to</th><th>Rule</th></tr>
     <tr><td>All studies</td><td>${ruleTxt(P.default)}</td></tr>
     ${Object.entries(P.cohorts).map(([k,x])=>`<tr><td>cohort ${esc(k)}</td><td>${ruleTxt(x)} <button class="b sm" data-cvrm="cohort|${esc(k)}">remove</button></td></tr>`).join("")}
     ${Object.entries(P.studies).map(([k,x])=>`<tr><td>study ${esc(k)}</td><td>${ruleTxt(x)} <button class="b sm" data-cvrm="study|${esc(k)}">remove</button></td></tr>`).join("")}</table></div>
   <div class="card" data-cv="set"><b>Change the rule</b>
     <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:8px">
      <label>Apply to ${seg("cv-scope",[["all","All studies"],["cohort","A cohort"],["study","One study"]],CV.scope)}</label>
      ${CV.scope!=="all"?`<select id="cv-target">${targets.map(t=>`<option ${t===CV.target?"selected":""}>${esc(t)}</option>`).join("")}</select>`:""}
      <label>Use ${seg("cv-mode",[["consensus","Expert consensus (default)"],["reference","One reference expert"]],CV.mode)}</label>
      ${CV.mode==="consensus"?`<label class="note">at least <select id="cv-q">${[1,2,3].map(q=>`<option ${q===CV.quorum?"selected":""}>${q}</option>`).join("")}</select> definite expert call(s)</label>`:
        `<select id="cv-rev">${experts.map(n=>`<option ${n===CV.reviewer?"selected":""}>${esc(n)}</option>`).join("")}</select>
        <label class="note"><input type="checkbox" id="cv-fb" ${CV.fallback==="consensus"?"checked":""}> where this expert did not call: expert consensus</label>`}
      <button class="b pri" id="cv-apply" ${CV.mode==="reference"&&!experts.length?"disabled":""}>Apply</button></div></div>
   <div class="card" data-cv="studies"><b>Ground truth per study</b><div style="max-height:320px;overflow:auto"><table><tr><th>Study</th><th>Rule</th><th>Reviewers</th><th>Resolved</th><th>Disagree</th><th>Abstained</th><th>No expert call</th><th>Training ground truth</th><th></th></tr>
     ${r.studies.map(s=>`<tr><td><b>${sidH(s.code)}</b></td><td class="note">${esc(s.rule_text)} <span class="mut">(${esc(s.scope)})</span></td><td class="note">${esc(s.reviewers.join(", ")||"–")}</td>
       <td>${(sc(s).resolved||0)+(sc(s).adjudicated||0)} <span class="mut">of ${s.n_candidates}</span></td><td>${sc(s).disagreement||"–"}</td><td>${sc(s).abstained||"–"}</td><td>${(sc(s).no_expert||0)+(sc(s).missing||0)||"–"}</td>
       <td>${s.primary_eligible||"–"}${(s.problems||[]).length?` <span class="bad" title="${esc(s.problems.join("; "))}">needs repair</span>`:""}</td>
       <td>${sc(s).disagreement||sc(s).abstained||sc(s).insufficient?`<button class="b sm" data-cvadjud="${esc(s.code)}">Adjudicate…</button>`:""}</td></tr>`).join("")}</table></div></div>
   ${hist.length?`<details><summary class="note">Recent rule changes</summary><table>${hist.map(h=>`<tr><td class="mono">${esc(h.time)}</td><td>${esc(h.scope)} ${esc(h.target||"")}</td><td class="note">${h.rule?ruleTxt(h.rule):"override removed"}</td><td class="note">${esc(h.by||"")}</td></tr>`).join("")}</table></details>`:""}`;
  bindSeg("cv-scope",x=>{CV.scope=x;cvRender()});bindSeg("cv-mode",x=>{CV.mode=x;if(!CV.reviewer)CV.reviewer=experts[0]||"";cvRender()});
  $("#cv-target")&&($("#cv-target").onchange=e=>CV.target=e.target.value);$("#cv-rev")&&($("#cv-rev").onchange=e=>CV.reviewer=e.target.value);
  $("#cv-q")&&($("#cv-q").onchange=e=>CV.quorum=+e.target.value);$("#cv-fb")&&($("#cv-fb").onchange=e=>CV.fallback=e.target.checked?"consensus":"none");
  if(CV.mode==="reference"&&!CV.reviewer)CV.reviewer=experts[0]||"";
  $("#cv-apply").onclick=async()=>{const rule=CV.mode==="reference"?{mode:"reference",reviewer:CV.reviewer,fallback:CV.fallback}:{mode:"consensus",quorum:CV.quorum};
    const where=CV.scope==="all"?"all studies":`${CV.scope} ${CV.target}`;if(!confirm(`Apply this rule to ${where}? The effective calls and scores are re-built; reviewers' own calls are not changed.`))return;
    const x=await api("/api/calls/policy",{scope:CV.scope,target:CV.target,rule,by:localStorage.getItem("cssapp_reviewer")||"app user"});if(!x.ok)return toast(esc(x.error),1);
    toast(`rule applied · ${x.updated.length} studies · ${x.updated.filter(u=>u.changed).length} changed`);cvRender();if(typeof render==="function")render()};
  el.querySelectorAll("[data-cvrm]").forEach(b=>b.onclick=async()=>{const [s,t]=b.dataset.cvrm.split("|");if(!confirm(`Remove the rule for ${s} ${t}? It then follows the broader rule.`))return;
    const x=await api("/api/calls/policy",{scope:s,target:t,rule:null});if(!x.ok)toast(esc(x.error),1);cvRender()});
  el.querySelectorAll("[data-cvrole]").forEach(b=>b.onclick=()=>{const role=cvAsk(`Role for ${b.dataset.cvrole} (${r.role_names.join(" / ")}):`);if(!role)return;
    cvAdmin("role",{name:b.dataset.cvrole,role},r.confirm.role)});
  $("#cv-addrole").onclick=()=>{const n=cvAsk("Reviewer name (exactly as typed in the reviewer):");if(!n)return;const role=cvAsk(`Role for ${n} (${r.role_names.join(" / ")}):`);if(!role)return;cvAdmin("role",{name:n,role},r.confirm.role)};
  el.querySelectorAll("[data-cvadj]").forEach(b=>b.onclick=()=>{const [n,a]=b.dataset.cvadj.split("|");cvAdmin("adjudicator",{name:n,allowed:a==="1"},r.confirm.adjudicator)});
  el.querySelectorAll("[data-cvadjud]").forEach(b=>b.onclick=async()=>{const code=b.dataset.cvadjud,S=await api(`/api/calls/study?code=${encodeURIComponent(code)}`);
    const U=(S.rows||[]).filter(x=>["disagreement","abstained","insufficient"].includes(x.status));
    const list=U.map(x=>`#${x.cand_id} ${x.status}: `+x.history.map(e=>`${e.reviewer} (${e.role}) ${e.call}`).join(", ")).join("\n");
    const cid=cvAsk(`Unresolved candidates of ${code}:\n${list}\n\nCandidate number to adjudicate:`);if(!cid)return;
    const call=cvAsk("Adjudicated call (cSS / Vessel / Normal / Artifact / Microbleed / Near ICH):");if(!call)return;
    const who=cvAsk("Adjudicator (an expert with the adjudication permission):");if(!who)return;const reason=cvAsk("Reason (kept with the decision):");if(!reason)return;
    const x=await api("/api/calls/adjudicate",{code,cand_id:+cid,call,adjudicator:who,reason});if(!x.ok)return toast(esc(x.error||"refused"),1);toast("adjudication recorded");cvRender()});
}
