// calls_view.js - "Reviewer calls" panel (v5.15), opened from the Studies screen and from the Model (training) screen.
// Every reviewer's calls are kept. The EFFECTIVE call of a candidate (used for the score, the results and training) is by default the
// NEWEST call of any reviewer; a rule can choose one reviewer instead, for one study, a cohort, or all studies (study > cohort > all).
// "Rewrite old calls" is the only destructive action: it needs the typed confirmation phrase, archives every file first and can be undone.
const CV={scope:"all",target:"",mode:"newest",reviewer:"",fallback:"newest",danger:false,plan:null};
function cvClose(){const o=$("#cv-ov");if(o)o.remove()}
async function openCalls(){cvClose();const o=document.createElement("div");o.id="cv-ov";
  o.style.cssText="position:fixed;inset:0;background:#0009;z-index:60;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:40px 16px";
  o.innerHTML='<div class="card" id="cv" style="width:min(1100px,100%);margin:0" data-cv="panel"><span class="mut">loading…</span></div>';
  o.onclick=e=>{if(e.target===o)cvClose()};document.body.appendChild(o);document.addEventListener("keydown",cvEsc);cvRender()}
function cvEsc(e){if(e.key==="Escape"){cvClose();document.removeEventListener("keydown",cvEsc)}}
async function cvRender(){
  const el=$("#cv");if(!el)return;const r=await api("/api/calls/policy");
  if(r.error){el.innerHTML=`<b class="bad">Reviewer calls unavailable</b><p class="note">${esc(r.error)}</p>`;return}
  const P=r.policy,rv=r.reviewers,coh=r.cohorts,codes=r.studies.map(s=>s.code);
  const ruleTxt=x=>x.mode==="reviewer"?`calls of <b>${esc(x.reviewer)}</b>${x.fallback==="newest"?" (newest where they did not call)":" only"}`:"<b>newest</b> call of any reviewer";
  const targets=CV.scope==="cohort"?coh:CV.scope==="study"?codes:[];if(CV.scope!=="all"&&!targets.includes(CV.target))CV.target=targets[0]||"";
  const hist=(P.history||[]).slice(-8).reverse();
  el.innerHTML=`<div class="row" style="justify-content:space-between"><h2 style="margin:0">Reviewer calls</h2><button class="b" onclick="cvClose()">Close</button></div>
   <p class="note" style="max-width:900px">Every reviewer's calls are kept with their date and time (the Excel export has one call and one date-time column per reviewer).
   The <b>effective call</b> of each candidate — used for the reader score, the results and model training — is by default the <b>newest</b> call of any reviewer.
   You can choose one reviewer instead, for one study, a cohort or all studies (a study setting overrides its cohort; a cohort overrides all studies).
   Changing the rule never edits a reviewer's own calls; the previous effective files are archived.</p>
   <div class="card" data-cv="current"><b>Current rules</b><table><tr><th style="width:150px">Applies to</th><th>Rule</th></tr>
     <tr><td>All studies</td><td>${ruleTxt(P.default)}</td></tr>
     ${Object.entries(P.cohorts).map(([k,x])=>`<tr><td>cohort ${esc(k)}</td><td>${ruleTxt(x)} <button class="b sm" data-cvrm="cohort|${esc(k)}">remove</button></td></tr>`).join("")}
     ${Object.entries(P.studies).map(([k,x])=>`<tr><td>study ${esc(k)}</td><td>${ruleTxt(x)} <button class="b sm" data-cvrm="study|${esc(k)}">remove</button></td></tr>`).join("")}</table></div>
   <div class="card" data-cv="set"><b>Change the rule</b>
     <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:8px">
      <label>Apply to ${seg("cv-scope",[["all","All studies"],["cohort","A cohort"],["study","One study"]],CV.scope)}</label>
      ${CV.scope!=="all"?`<select id="cv-target">${targets.map(t=>`<option ${t===CV.target?"selected":""}>${esc(t)}</option>`).join("")}</select>`:""}
      <label>Use ${seg("cv-mode",[["newest","Newest call (default)"],["reviewer","One reviewer"]],CV.mode)}</label>
      ${CV.mode==="reviewer"?`<select id="cv-rev">${rv.map(n=>`<option ${n===CV.reviewer?"selected":""}>${esc(n)}</option>`).join("")}</select>
        <label class="note"><input type="checkbox" id="cv-fb" ${CV.fallback==="newest"?"checked":""}> where this reviewer did not call: use the newest call</label>`:""}
      <button class="b pri" id="cv-apply" ${CV.mode==="reviewer"&&!rv.length?"disabled":""}>Apply</button></div></div>
   <div class="card" data-cv="studies"><b>Effective calls per study</b><div style="max-height:300px;overflow:auto"><table><tr><th>Study</th><th>Cohort</th><th>Rule (set for)</th><th>Reviewers</th><th>Effective calls from</th><th>Candidates with disagreement</th></tr>
     ${r.studies.map(s=>`<tr><td><b>${esc(s.code)}</b></td><td>${esc(s.cohort)}</td><td class="note">${esc(s.rule_text)} <span class="mut">(${esc(s.scope)})</span></td><td class="note">${esc(s.reviewers.join(", ")||"–")}</td>
       <td class="note">${Object.entries(s.from_reviewer).filter(([k,n])=>n).map(([k,n])=>`${esc(k)} ${n}`).join(" · ")||"–"} <span class="mut">of ${s.n_candidates}</span></td><td>${s.disagreements||"–"}</td></tr>`).join("")}</table></div></div>
   ${hist.length?`<details><summary class="note">Recent rule changes</summary><table>${hist.map(h=>`<tr><td class="mono">${esc(h.time)}</td><td>${esc(h.scope)} ${esc(h.target||"")}</td><td class="note">${h.rule?ruleTxt(h.rule):"override removed"}</td><td class="note">${esc(h.by||"")}</td></tr>`).join("")}</table></details>`:""}
   <details data-cv="danger" ${CV.danger?"open":""}><summary><b class="bad">Rewrite old calls — keep only the newest</b></summary>
     <div class="card" style="border-color:var(--bad)"><p class="note">This removes, from the reviewers' own files, every call that is not the newest call of its candidate. It is the only step here that
      changes reviewers' files. Every affected file is archived first (review/call_history/) and can be restored. Scope:</p>
      <div class="row">${seg("cv-dscope",[["study","One study"],["cohort","A cohort"],["all","All studies"]],CV.dscope||"study")}
       ${(CV.dscope||"study")!=="all"?`<select id="cv-dtarget">${((CV.dscope||"study")==="cohort"?coh:codes).map(t=>`<option ${t===CV.dtarget?"selected":""}>${esc(t)}</option>`).join("")}</select>`:""}
       <button class="b" id="cv-plan">Show what would change</button></div>
      ${CV.plan?`<table data-cv="plan"><tr><th>Study</th><th>Candidates with several calls</th><th>Calls that would be removed</th></tr>${CV.plan.plan.map(x=>`<tr><td>${esc(x.study)}</td><td>${x.candidates_with_history}</td><td><b>${x.calls_to_remove}</b></td></tr>`).join("")}</table>
       <p class="bad"><b>${esc(CV.plan.warning)}</b></p><p>To continue, type <code>${esc(CV.plan.confirm_phrase)}</code>:</p>
       <div class="row"><input id="cv-phrase" style="width:260px" autocomplete="off"><button class="b danger" id="cv-go" disabled>Rewrite old calls</button></div>`:""}</div></details>`;
  bindSeg("cv-scope",x=>{CV.scope=x;cvRender()});bindSeg("cv-mode",x=>{CV.mode=x;if(!CV.reviewer)CV.reviewer=rv[0]||"";cvRender()});bindSeg("cv-dscope",x=>{CV.dscope=x;CV.plan=null;CV.danger=true;cvRender()});
  $("#cv-target")&&($("#cv-target").onchange=e=>CV.target=e.target.value);$("#cv-rev")&&($("#cv-rev").onchange=e=>CV.reviewer=e.target.value);
  $("#cv-fb")&&($("#cv-fb").onchange=e=>CV.fallback=e.target.checked?"newest":"none");$("#cv-dtarget")&&($("#cv-dtarget").onchange=e=>{CV.dtarget=e.target.value;CV.plan=null});
  if(CV.mode==="reviewer"&&!CV.reviewer)CV.reviewer=rv[0]||"";
  $("#cv-apply").onclick=async()=>{const rule=CV.mode==="reviewer"?{mode:"reviewer",reviewer:CV.reviewer,fallback:CV.fallback}:{mode:"newest"};
    const where=CV.scope==="all"?"all studies":`${CV.scope} ${CV.target}`;if(!confirm(`Use ${CV.mode==="reviewer"?CV.reviewer+"'s calls":"the newest call"} for ${where}? The effective calls and scores are re-written; reviewers' own calls are not changed.`))return;
    const x=await api("/api/calls/policy",{scope:CV.scope,target:CV.target,rule});if(!x.ok)return toast(esc(x.error),1);
    toast(`rule applied · ${x.updated.length} studies · ${x.updated.filter(u=>u.changed).length} changed`);cvRender();if(typeof render==="function")render()};
  el.querySelectorAll("[data-cvrm]").forEach(b=>b.onclick=async()=>{const [s,t]=b.dataset.cvrm.split("|");if(!confirm(`Remove the rule for ${s} ${t}? It then follows the broader rule.`))return;
    const x=await api("/api/calls/policy",{scope:s,target:t,rule:null});if(!x.ok)toast(esc(x.error),1);cvRender()});
  $("#cv-plan").onclick=async()=>{const s=CV.dscope||"study",t=s==="all"?"":(CV.dtarget||((s==="cohort"?coh:codes)[0]||""));CV.dtarget=t;
    CV.plan=await api(`/api/calls/consolidate_plan?scope=${s}&target=${encodeURIComponent(t)}`);CV.danger=true;cvRender()};
  if($("#cv-phrase")){const ph=$("#cv-phrase"),go=$("#cv-go");ph.oninput=()=>go.disabled=ph.value!==CV.plan.confirm_phrase;
    go.onclick=async()=>{const n=CV.plan.plan.reduce((a,x)=>a+x.calls_to_remove,0);if(!confirm(`FINAL CHECK: remove ${n} older call(s) from the reviewers' files? (archived first, can be restored)`))return;
      const x=await api("/api/calls/consolidate",{scope:CV.dscope||"study",target:CV.dtarget||"",confirm:ph.value});if(!x.ok)return toast(esc(x.error),1);
      toast(`rewritten · archive ${esc((x.done[0]||{}).archive||"")}`);CV.plan=null;cvRender()}}
}
