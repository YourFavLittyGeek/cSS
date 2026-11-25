// transfer_view.js - Transfer Center (Phase 1e.3).
// The screen is a VIEW of the durable transfer journal: every refresh replaces all job data with what
// /api/transfer/* returns. The only client-side state is UI choice (tab, selected job, search text).
// Controls follow the job's journaled state; pause / resume / discard / cancel go through the backend
// (Phase 1c recovery for resume and discard). Nothing here decides or remembers a job's outcome.

const TC = { tab: "attention", selected: null, search: "", data: null, detail: null, assess: null, timer: null };

const TC_ACTIVE = ["preparing", "copying", "flushing", "verifying", "committing", "removing_sources", "rolling_back", "recovering", "cancel_requested"];
const TC_ATTENTION = ["paused", "interrupted", "needs_attention", "failed"];
const TC_TERMINAL = ["completed", "completed_with_retained_sources", "cancelled"];
const TC_LABEL = {
  queued: "Queued", preparing: "Preparing", copying: "Copying", flushing: "Flushing to disk", verifying: "Verifying",
  committing: "Committing", removing_sources: "Removing verified sources", rolling_back: "Rolling back",
  recovering: "Recovering", cancel_requested: "Stopping", paused: "Paused", interrupted: "Interrupted",
  needs_attention: "Needs attention", failed: "Failed", completed: "Completed",
  completed_with_retained_sources: "Completed (some sources kept)", cancelled: "Cancelled"
};
const TC_STEPS = ["queued", "preparing", "copying", "flushing", "verifying", "committing", "completed"];

function tcEsc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function tcBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"]; let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return `${(Math.round(n * 10) / 10).toFixed(1)} ${u[i]}`;
}
function tcPill(state) {
  const cls = TC_TERMINAL.includes(state) ? (state === "cancelled" ? "mut" : "ok")
    : TC_ACTIVE.includes(state) ? "pri" : state === "queued" ? "mut" : "warn";
  return `<span class="pill ${cls}" data-state="${tcEsc(state)}">${tcEsc(TC_LABEL[state] || state)}</span>`;
}

// Allowed controls are a pure function of the journaled state (the backend re-checks every request).
function tcActions(job) {
  const s = job.state;
  if (s === "queued") return ["pause", "cancel"];
  if (TC_ACTIVE.includes(s)) return (s === "rolling_back" || s === "cancel_requested") ? [] : ["pause"];
  if (s === "paused" || s === "interrupted") {
    if (job.recovery_decision === "discard") return ["discard", "assess"];
    if (job.recovery_decision === "resume") return ["resume", "assess"];
    return ["resume", "discard", "assess"];
  }
  if (s === "needs_attention") {
    if (job.recovery_decision === "discard") return ["discard", "assess"];
    if (job.recovery_decision === "resume") return ["assess", "resume"];
    return ["assess", "resume", "discard"];
  }
  if (s === "failed") return ["discard", "assess"];
  return [];
}

function tcGroup(jobs) {
  const g = { attention: [], active: [], queued: [], history: [] };
  for (const j of jobs || []) {
    if (TC_ATTENTION.includes(j.state)) g.attention.push(j);
    else if (TC_ACTIVE.includes(j.state)) g.active.push(j);
    else if (j.state === "queued") g.queued.push(j);
    else g.history.push(j);
  }
  return g;
}

function tcTimeline(state) {
  const at = TC_STEPS.indexOf(state === "completed_with_retained_sources" ? "completed" : state);
  return `<div class="tc-steps">${TC_STEPS.map((s, i) =>
    `<span class="tc-step ${at < 0 ? "" : i < at ? "done" : i === at ? "now" : ""}">${tcEsc(TC_LABEL[s])}</span>`).join("")}</div>`;
}

const TC_BUTTON = {
  pause: ["Pause", "Stop at the next safe point (nothing is rolled back)"],
  resume: ["Resume", "Verify what was already done, then finish the job"],
  discard: ["Discard…", "Undo only what this job wrote (sources are never touched)"],
  cancel: ["Cancel", "Remove this job from the queue (it has not started)"],
  assess: ["Check", "Read-only recovery check of every file"]
};

function tcJobRow(j) {
  const p = j.progress || {};
  const pct = TC_TERMINAL.includes(j.state) ? (j.state === "cancelled" ? 0 : 100) : (Number(p.percent_committed) || 0);
  const staged = p.bytes_total ? Math.min(100, Math.round(100 * (p.bytes_staged || 0) / p.bytes_total)) : 0;
  const err = j.error ? `<div class="bad tc-err">${tcEsc(j.error.message)}</div>` : "";
  const acts = tcActions(j).map(a =>
    `<button class="b tc-act" data-act="${a}" data-job="${tcEsc(j.job_id)}" title="${tcEsc(TC_BUTTON[a][1])}">${tcEsc(TC_BUTTON[a][0])}</button>`).join("");
  return `<div class="card tc-job${TC.selected === j.job_id ? " sel" : ""}" data-job-row="${tcEsc(j.job_id)}">
    <div class="tc-head"><b>${tcEsc(j.operation)}</b> ${j.study_id ? `<span class="mono">${tcEsc(j.study_id)}</span>` : ""}
      ${tcPill(j.state)} ${j.running ? '<span class="pill pri">worker running</span>' : ""}
      <span class="mut mono tc-id">${tcEsc(j.job_id)}</span></div>
    <div class="tc-progress"><div class="tc-bar"><i style="width:${staged}%" class="staged"></i><i style="width:${pct}%"></i></div>
      ${tcProgressText(j)}</div>
    ${j.recovery_decision ? `<div class="mut">Recovery decision: <b>${tcEsc(j.recovery_decision)}</b> (cannot be switched)</div>` : ""}
    ${err}<div class="tc-actions">${acts}</div></div>`;
}

// What is happening now, in words. A job copies + verifies every file first (bytes_staged grows), then commits them
// all at once (files_done / bytes_committed jump) - so while copying, the copied bytes are the honest progress.
function tcProgressText(j) {
  const p = j.progress || {}, s = j.state, tot = p.bytes_total || 0;
  const pctOf = n => tot ? ` (${Math.min(100, Math.round(100 * n / tot))} %)` : "";
  const cur = p.current_file ? `<div class="tc-cur">Now: <span class="mono">${tcEsc(p.current_file)}</span></div>` : "";
  if (["copying", "flushing", "verifying", "preparing"].includes(s))
    return `<span class="mut">${tcEsc(TC_LABEL[s])} · ${tcBytes(p.bytes_staged)} of ${tcBytes(tot)} copied${pctOf(p.bytes_staged)} · ${tcEsc(p.files_total || 0)} files</span>${cur}`;
  if (s === "committing" || s === "removing_sources")
    return `<span class="mut">${tcEsc(TC_LABEL[s])} · ${tcEsc(p.files_done || 0)} of ${tcEsc(p.files_total || 0)} files in place · ${tcBytes(p.bytes_committed)} of ${tcBytes(tot)}</span>${cur}`;
  if (s === "queued") return `<span class="mut">Waiting to start · ${tcEsc(p.files_total || 0)} files · ${tcBytes(tot)}</span>`;
  return `<span class="mut">${tcEsc(p.files_done || 0)} of ${tcEsc(p.files_total || 0)} files · ${tcBytes(p.bytes_committed)} of ${tcBytes(tot)} in place</span>${TC_ACTIVE.includes(s) ? cur : ""}`;
}

function tcDetail(d, assess) {
  if (!d || !d.job) return "";
  const files = (d.files || []).map(f => `<tr><td class="mono">${tcEsc(f.rel_path)}</td><td>${tcBytes(f.size)}</td>
    <td>${tcEsc(f.state)}</td><td class="bad">${tcEsc(f.error || "")}</td></tr>`).join("");
  const skipped = (d.skipped || []).map(s => `<li><span class="mono">${tcEsc(s.rel)}</span> — ${tcEsc(s.reason)}</li>`).join("");
  const ev = (d.events || []).slice(-15).reverse().map(e =>
    `<li><span class="mut">${new Date(e.ts * 1000).toLocaleTimeString()}</span> ${tcEsc(e.kind)} ${tcEsc(e.from_state || "")} → ${tcEsc(e.to_state || "")}</li>`).join("");
  let a = "";
  if (assess) {
    const amb = (assess.ambiguous || []).map(x => `<li class="bad">${tcEsc(x.rel)}: ${tcEsc(x.reason)}</li>`).join("");
    a = `<div class="card tc-assess"><b>Recovery check</b> (read-only):
      ${assess.unavailable && assess.unavailable.length ? `<div class="bad">${assess.unavailable.map(tcEsc).join("<br>")}</div>` : ""}
      <div>Resume possible: <b>${assess.resumable ? "yes" : "no"}</b> · Discard possible: <b>${assess.discardable ? "yes" : "no"}</b></div>
      ${amb ? `<ul>${amb}</ul><div class="mut">Ambiguous items are never resolved automatically and never deleted.</div>` : ""}
      ${(assess.notes || []).map(n => `<div class="mut">${tcEsc(n)}</div>`).join("")}</div>`;
  }
  return `<div class="card tc-detail"><h3>Job ${tcEsc(d.job.job_id)}</h3>${tcTimeline(d.job.state)}${a}
    <table class="tbl"><thead><tr><th>File</th><th>Size</th><th>State</th><th>Error</th></tr></thead><tbody>${files}</tbody></table>
    ${skipped ? `<div><b>Not copied</b> (reported, never deleted):<ul>${skipped}</ul></div>` : ""}
    <div><b>Journal</b> (most recent first):<ul class="tc-events">${ev}</ul></div></div>`;
}

function tcVault(vault, eject) {
  const v = vault || {}, e = eject || {};
  const verdict = { archive_ok: "Archive ready", not_external: "Not an external drive", read_only: "Source only (read-only)",
                    not_a_vault: "Not a Pensieve drive", unavailable: "Not connected" }[v.verdict] || "Unknown";
  return `<div class="card tc-vault"><b>Pensieve drive</b>: <span data-verdict="${tcEsc(v.verdict)}">${tcEsc(verdict)}</span>
    ${v.filesystem ? `· ${tcEsc(v.filesystem)}` : ""} ${v.free_bytes != null ? `· ${tcBytes(v.free_bytes)} free` : ""}
    ${(v.reasons || []).map(r => `<div class="mut">${tcEsc(r)}</div>`).join("")}
    <div>Eject: <b data-eject="${tcEsc(e.state)}">${tcEsc(e.state || "?")}</b> — ${tcEsc(e.reason || "")}</div></div>`;
}

// Work on this Mac that is not a drive transfer: imports (copy from the source folder), setup, deletion of temporary copies.
function tcMac(jobs) {
  if (!jobs || !jobs.length) return "";
  const kind = { import: "Import (copy to the Mac)", cleanup: "Clean-up", setup_finish: "Setup", pensieve: "Pensieve move" };
  const row = j => {
    const run = j.state === "running";
    const when = j.ended ? new Date(j.ended * 1000).toLocaleTimeString() : "";
    const eta = run && j.eta_s != null ? ` · about ${Math.max(1, Math.round(j.eta_s / 60))} min left` : "";
    return `<div class="tc-macrow"><b>${tcEsc(j.title)}</b> <span class="pill ${run ? "pri" : j.state === "failed" ? "warn" : "ok"}">${run ? "Running" : j.state === "failed" ? "Failed" : "Done"}</span>
      <span class="mut">${tcEsc(kind[j.kind] || j.kind)}${when && !run ? ` · ${tcEsc(when)}` : ""}</span>
      ${run ? `<div class="tc-bar"><i style="width:${Number(j.pct) || 0}%"></i></div>` : ""}
      <div class="mut">${tcEsc(run ? `${j.label} (${Math.min(j.done, j.total)}/${j.total})${eta}` : (j.error || j.label))}</div></div>`;
  };
  return `<div class="card tc-mac"><b>On this Mac</b> <span class="mut">(imports and clean-ups since the app started)</span>${jobs.map(row).join("")}</div>`;
}

function tcRender(data, ui) {
  ui = ui || TC;
  const g = tcGroup(data.jobs || []);
  const q = (ui.search || "").toLowerCase();
  const tabs = [["attention", "Needs your decision"], ["active", "Running"], ["queued", "Queued"], ["history", "History"]];
  let list = g[ui.tab] || [];
  if (ui.tab === "history" && q) list = list.filter(j => `${j.job_id} ${j.operation} ${j.study_id || ""} ${j.state}`.toLowerCase().includes(q));
  const w = data.workers || {};
  return `<div class="tc">
    ${tcVault(data.vault, data.eject)}
    ${tcMac(data.mac)}
    <div class="tc-tabs">${tabs.map(([k, t]) => `<button class="b tc-tab${ui.tab === k ? " on" : ""}" data-tab="${k}">${t} (${g[k].length})</button>`).join("")}
      <span class="mut">Workers: ${w.alive ? "running" : "<b class='bad'>not running</b>"}</span></div>
    ${ui.tab === "history" ? `<input class="tc-search" placeholder="Search history" value="${tcEsc(ui.search || "")}">` : ""}
    <div class="tc-list">${list.length ? list.map(tcJobRow).join("") : '<div class="mut">Nothing here.</div>'}</div>
    ${tcDetail(ui.selected && data.detail && data.detail.job && data.detail.job.job_id === ui.selected ? data.detail : null, ui.assess)}
  </div>`;
}

async function tcFetch() {
  const [jobs, workers, vault, eject, mac] = await Promise.all([
    api("/api/transfer/jobs?limit=200"), api("/api/transfer/workers"), api("/api/transfer/vault_check"), api("/api/storage/eject_check"),
    Promise.resolve().then(() => api("/api/transfer/mac_activity")).catch(() => ({}))]);
  const data = { jobs: jobs.ok ? jobs.jobs : [], workers: workers.ok ? workers.workers : {}, vault: vault.ok ? vault.vault : {},
                 eject: eject, mac: mac && mac.ok ? mac.jobs : [], error: jobs.ok ? null : jobs.error };
  if (TC.selected) {
    const d = await api(`/api/transfer/job?id=${encodeURIComponent(TC.selected)}`);
    data.detail = d.ok ? d : null;
    if (!d.ok) TC.selected = null;
  }
  TC.data = data;                                        // replaced completely on every refresh
  return data;
}

async function tcAct(act, jobId) {
  if (act === "assess") {
    const r = await api(`/api/transfer/assess?id=${encodeURIComponent(jobId)}`);
    TC.selected = jobId; TC.assess = r.ok ? r.assessment : null;
    if (!r.ok) toast(tcEsc(r.error.message), true);
    return r;
  }
  if (act === "discard" && !confirm("Discard this job?\n\nOnly files this job wrote are removed (each checked by identity and content). " +
      "Sources, files changed by others and unrecognized temporary files are never touched.")) return null;
  const r = await api(`/api/transfer/jobs/${act}`, { job_id: jobId });
  toast(r.ok ? `${TC_BUTTON[act][0].replace("…", "")}: request sent` : tcEsc(r.error.message), !r.ok);
  return r;
}

function tcBind(v) {
  v.querySelectorAll(".tc-tab").forEach(b => b.onclick = () => { TC.tab = b.dataset.tab; tcPaint(v); });
  v.querySelectorAll(".tc-act").forEach(b => b.onclick = async ev => { ev.stopPropagation(); await tcAct(b.dataset.act, b.dataset.job); await tcRefresh(v); });
  v.querySelectorAll("[data-job-row]").forEach(r => r.onclick = async () => {
    TC.selected = r.dataset.jobRow; TC.assess = null; await tcRefresh(v); });
  const s = v.querySelector(".tc-search");
  if (s) s.oninput = () => { TC.search = s.value; const pos = s.selectionStart; tcPaint(v); const n = v.querySelector(".tc-search"); if (n) { n.focus(); n.setSelectionRange(pos, pos); } };
}

function tcPaint(v) {
  if (!TC.data) return;
  v.innerHTML = TC.data.error ? `<div class="card bad">${tcEsc(TC.data.error.message || TC.data.error)}</div>` : tcRender(TC.data, TC);
  tcBind(v);
}

async function tcRefresh(v) {
  try { await tcFetch(); tcPaint(v); }
  catch (e) { v.innerHTML = `<div class="card bad">Transfer Center unavailable: ${tcEsc(e.message)}</div>`; }
}

const TC_CSS = `.tc-job{margin:8px 0;cursor:pointer}.tc-job.sel{outline:2px solid var(--pri,#3987e5)}
.tc-head{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.tc-id{margin-left:auto;font-size:11px}
.tc-bar{position:relative;height:6px;background:var(--line,#333);border-radius:3px;margin:6px 0;overflow:hidden}
.tc-bar i{position:absolute;left:0;top:0;bottom:0;background:var(--ok,#3a3)}.tc-bar i.staged{background:var(--mut,#777);opacity:.5}
.tc-tabs{display:flex;gap:6px;align-items:center;margin:8px 0}.tc-tab.on{outline:2px solid var(--pri,#3987e5)}
.tc-actions{display:flex;gap:6px;margin-top:6px}.tc-cur{font-size:11px;margin-top:2px;word-break:break-all}.tc-macrow{margin-top:8px}.tc-steps{display:flex;gap:4px;flex-wrap:wrap;margin:6px 0}
.tc-step{font-size:11px;padding:2px 6px;border-radius:3px;background:var(--line,#333);opacity:.5}
.tc-step.done{opacity:.8}.tc-step.now{opacity:1;outline:1px solid var(--pri,#3987e5)}.tc-events{font-size:12px}`;

async function transferView(v) {
  if (typeof document !== "undefined" && !document.getElementById("tc-css")) {
    const st = document.createElement("style"); st.id = "tc-css"; st.textContent = TC_CSS; document.head.appendChild(st);
  }
  v.innerHTML = `<div class="card" style="padding:20px;text-align:center"><span class="mut">Loading Transfer Center…</span></div>`;
  await tcRefresh(v);
  if (TC.timer) clearInterval(TC.timer);
  TC.timer = setInterval(async () => {
    if (typeof V === "undefined" || V !== "transfer") { clearInterval(TC.timer); TC.timer = null; return; }
    await tcRefresh(v);
  }, 2000);
}

if (typeof module !== "undefined") module.exports = { TC, tcActions, tcGroup, tcRender, tcFetch, tcAct, tcBytes, tcEsc, tcTimeline, tcProgressText, tcMac, tcVault };
