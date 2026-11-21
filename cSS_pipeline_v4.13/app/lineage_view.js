// lineage_view.js - v5.17 "Compare runs": previous vs current detection of one study (candidate lineage), run history with model
// provenance, and the confirmations of earlier human calls whose candidate has only a POSSIBLE match (never transferred automatically).
async function openLineage(code){const r=await api(`/api/lineage/study?code=${encodeURIComponent(code)}`);
  const o=document.createElement("div");o.id="ln-ov";o.style.cssText="position:fixed;inset:0;background:#0009;z-index:65;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:40px 16px";
  o.onclick=e=>{if(e.target===o)o.remove()};document.body.appendChild(o);
  const L=r.lineage,S=(L||{}).summary||{},st={confident:["confident match","ok"],possible:["possible match - confirm","warn"],no_match:["no longer detected","bad"]};
  const f=(x,n=2)=>x===null||x===undefined?"–":(typeof x==="number"?x.toFixed(n):esc(String(x)));
  const runs=(r.runs||[]).slice().reverse();
  o.innerHTML=`<div class="card" style="width:min(1150px,100%);margin:0" data-ln="panel"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Compare runs · ${esc(code)}</h2><button class="b" id="ln-x">Close</button></div>
   ${r.error?`<p class="bad">${esc(r.error)}</p>`:""}
   <div class="card"><b>Runs</b> <span class="note">every run is kept; the active run is the one shown in the app</span><table data-ln="runs"><tr><th>Run</th><th>Status</th><th>What</th><th>Models</th><th>Candidates vs previous</th></tr>
    ${runs.map(m=>`<tr><td class="mono">${esc(m.run_id)}${m.run_id===r.active?' <span class="pill ok">active</span>':""}</td><td>${esc(m.status)}</td><td class="note">${esc(m.note||"")}</td>
     <td class="note">${m.models?Object.entries(m.models).map(([k,v])=>`${esc(k)}: ${esc(v)}`).join("<br>"):"–"}</td>
     <td class="note">${m.lineage?`${m.lineage.confident} confident · ${m.lineage.possible} possible · ${m.lineage.no_match} gone · ${m.lineage.new} new`:"–"}</td></tr>`).join("")||'<tr><td colspan="5" class="note">No processing runs recorded yet.</td></tr>'}</table></div>
   ${L?`<div class="card" data-ln="lineage"><div class="row"><b>Previous run ${esc(L.run_old)} → current run ${esc(L.run_new)}</b><span class="note">(${esc(L.method)}; confident = one-to-one, IoU ≥ ${L.thresholds.confident_iou})</span></div>
     <div class="row" style="margin:6px 0"><span class="pill ok">${S.confident} confident</span><span class="pill warn">${S.possible} possible</span><span class="pill bad">${S.no_match} no longer detected</span><span class="pill">${S.new} newly detected</span></div>
     <div style="max-height:340px;overflow:auto"><table><tr><th>Previous candidate</th><th>Lineage</th><th>Current candidate</th><th>IoU</th><th>score_v4 old → new</th><th>volume mm³ old → new</th><th>Why</th></tr>
     ${L.old.map(x=>`<tr><td class="mono">#${x.old_cand_id}</td><td><span class="pill ${st[x.status][1]}">${st[x.status][0]}</span></td><td class="mono">${x.new_cand_id!=null?"#"+x.new_cand_id:"–"}</td><td>${f(x.iou)}</td>
       <td>${f((x.old||{}).score_v4,3)} → ${f((x.new||{}).score_v4,3)}</td><td>${f((x.old||{}).volume_mm3,0)} → ${f((x.new||{}).volume_mm3,0)}</td><td class="note">${esc(x.why)}</td></tr>`).join("")}
     ${L.new.filter(x=>x.status==="new").map(x=>`<tr><td>–</td><td><span class="pill">newly detected</span></td><td class="mono">#${x.new_cand_id}</td><td colspan="4" class="note">not in the previous run: needs a call</td></tr>`).join("")}</table></div></div>`
    :'<p class="note">No lineage yet: it is computed when a re-processing run of this study finishes (the previous run is compared with the new one).</p>'}
   <div class="card" data-ln="pending"><b>Earlier calls waiting for your confirmation</b> <span class="note">${r.pending.length} · a possible match is never transferred automatically; confirming records it as YOUR call (the earlier call is kept)</span>
    ${r.pending.length?`<div class="row" style="margin:6px 0"><span class="note">Your name</span><input id="ln-by" style="width:180px" value="${esc(localStorage.getItem("css_reviewer")||"")}"></div><table>
     ${r.pending.map((e,i)=>`<tr><td><b>${esc(e.call)}</b> by ${esc(e.reviewer)} <span class="note">${esc(e.time)}</span></td><td class="note">${esc(e.lineage_why)}</td><td>→ current #${esc(e.suggested_new_cand_id)}</td>
       <td><button class="b sm pri" data-lnd="${i}|confirm">Confirm on #${esc(e.suggested_new_cand_id)}</button> <button class="b sm" data-lnd="${i}|reject">Keep as history only</button></td></tr>`).join("")}</table>`:'<p class="note">none</p>'}</div>
   <p class="note">Review state: <b>${esc((r.state||{}).label||"")}</b> — ${esc((r.state||{}).reason||"")}</p></div>`;
  $("#ln-x").onclick=()=>o.remove();
  o.querySelectorAll("[data-lnd]").forEach(b=>b.onclick=async()=>{const [i,dec]=b.dataset.lnd.split("|"),e=r.pending[+i],by=($("#ln-by").value||"").trim();if(!by)return toast("enter your name",1);
    localStorage.setItem("css_reviewer",by);const x=await api("/api/lineage/decide",{code,row_uid:e.row_uid,reviewer:e.reviewer,time:e.time,decision:dec,by});
    if(!x.ok)return toast(esc(x.error),1);toast(dec==="confirm"?"confirmed as your call":"kept as history");o.remove();openLineage(code);if(typeof render==="function")render()})}
