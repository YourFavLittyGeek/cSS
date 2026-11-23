// transfer_view.js - Dedicated Transfer Center Workspace for PERCIVAL.
// Authoritative tracking of active in-flight transfers, queues, searchable history,
// job timelines (Queued -> Preparing -> Copying -> Flushing -> Verifying -> Committing -> Completed),
// and crash/interruption recovery.

const TC = {
  activeTab: "active", // "active", "queue", "history", "interrupted"
  activeJobs: [],
  queue: [],
  history: [],
  interrupted: [],
  summary: {
    active_count: 0,
    queued_count: 0,
    completed_count: 0,
    failed_count: 0,
    interrupted_count: 0,
    total_active_bytes: 0
  },
  searchHistory: "",
  selectedJob: null,
  pollTimer: null
};

async function transferView(v) {
  v.innerHTML = `<div class="card" style="padding:20px;text-align:center"><span class="mut">Loading Transfer Center…</span></div>`;
  await fetchTransferData();
  renderTransferCenter(v);

  // Poll active jobs if on this screen
  if (TC.pollTimer) clearInterval(TC.pollTimer);
  TC.pollTimer = setInterval(async () => {
    if (window.V !== "transfer") {
      clearInterval(TC.pollTimer);
      TC.pollTimer = null;
      return;
    }
    await fetchTransferData(true);
    renderTransferCenter(v, true);
  }, 2000);
}

async function fetchTransferData(silent = false) {
  try {
    const [sumRes, actRes, qRes, histRes, intRes] = await Promise.all([
      api("/api/transfer/summary"),
      api("/api/transfer/active"),
      api("/api/transfer/queue"),
      api("/api/transfer/history?limit=100"),
      api("/api/transfer/interrupted")
    ]);
    if (sumRes && sumRes.ok) TC.summary = sumRes;
    if (actRes && actRes.ok) TC.activeJobs = actRes.active || [];
    if (qRes && qRes.ok) TC.queue = qRes.queue || [];
    if (histRes && histRes.ok) TC.history = histRes.history || [];
    if (intRes && intRes.ok) TC.interrupted = intRes.interrupted || [];

    // Update global badge in sidebar if present
    const badge = $("#cnt_transfer");
    if (badge) {
      const activeTotal = TC.activeJobs.length + TC.queue.length;
      badge.textContent = activeTotal > 0 ? activeTotal : "";
    }
  } catch (e) {
    if (!silent) console.error("Failed fetching transfer data:", e);
  }
}

function renderTransferCenter(v, isUpdate = false) {
  const sm = TC.summary;
  const activeBytesMb = round(sm.total_active_bytes / (1024 * 1024), 1);

  // Preserve scroll if live update
  const scrollPos = isUpdate ? v.scrollTop : 0;

  v.innerHTML = `
    <!-- Top Telemetry Summary Cards -->
    <div class="tiles" style="margin-bottom:16px">
      <div class="tile ${TC.activeTab === 'active' ? 'on' : ''}" id="tc-tab-active" style="cursor:pointer">
        <div class="n" style="color:var(--pri)">${TC.activeJobs.length}</div>
        <div class="t">Active Transfers (${activeBytesMb} MB)</div>
      </div>
      <div class="tile ${TC.activeTab === 'queue' ? 'on' : ''}" id="tc-tab-queue" style="cursor:pointer">
        <div class="n">${TC.queue.length}</div>
        <div class="t">Queued Jobs</div>
      </div>
      <div class="tile ${TC.activeTab === 'history' ? 'on' : ''}" id="tc-tab-history" style="cursor:pointer">
        <div class="n" style="color:var(--ok)">${sm.completed_count || TC.history.length}</div>
        <div class="t">Completed &amp; History</div>
      </div>
      <div class="tile ${TC.activeTab === 'interrupted' ? 'on' : ''}" id="tc-tab-interrupted" style="cursor:pointer">
        <div class="n" style="color:${(TC.interrupted.length > 0 || sm.failed_count > 0) ? 'var(--bad)' : 'var(--mut)'}">
          ${TC.interrupted.length + (sm.failed_count || 0)}
        </div>
        <div class="t">Interrupted / Recovery</div>
      </div>
    </div>

    <!-- Active Transfers View -->
    ${TC.activeTab === "active" ? `
      <div class="card" style="padding:16px">
        <div class="row" style="justify-content:space-between;margin-bottom:12px">
          <b>Active Data Movement (${TC.activeJobs.length} running)</b>
          <span class="note">Memory-bounded streaming with in-flight SHA-256</span>
        </div>
        ${TC.activeJobs.length === 0 ? `
          <div style="text-align:center;padding:36px;color:var(--mut)">
            No transfers currently in progress. All physical disk I/O is idle.
          </div>
        ` : `
          <div style="display:flex;flex-direction:column;gap:12px">
            ${TC.activeJobs.map(job => renderActiveJobCard(job)).join("")}
          </div>
        `}
      </div>
    ` : ""}

    <!-- Queue View -->
    ${TC.activeTab === "queue" ? `
      <div class="card" style="padding:16px">
        <div class="row" style="justify-content:space-between;margin-bottom:12px">
          <b>Sequential Transfer Queue (${TC.queue.length} waiting)</b>
          <span class="note">Single physical I/O worker prevents HDD head thrashing</span>
        </div>
        ${TC.queue.length === 0 ? `
          <div style="text-align:center;padding:36px;color:var(--mut)">Transfer queue is currently empty.</div>
        ` : `
          <div style="overflow-x:auto">
            <table>
              <thead>
                <tr>
                  <th>Position</th><th>Study ID</th><th>Target Action</th><th>Priority</th><th>Status</th><th>Enqueued</th>
                </tr>
              </thead>
              <tbody>
                ${TC.queue.map((it, idx) => `
                  <tr>
                    <td><b>#${idx + 1}</b></td>
                    <td><b>${esc(it.study_id || it.study_code || '—')}</b></td>
                    <td><span class="pill pri">${esc(it.action || 'archive')}</span></td>
                    <td>${it.priority || 0}</td>
                    <td><span class="pill warn">${esc(it.status || 'queued')}</span></td>
                    <td class="note">${it.enqueued_at ? new Date(it.enqueued_at * 1000).toLocaleTimeString() : '—'}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>
    ` : ""}

    <!-- History View -->
    ${TC.activeTab === "history" ? `
      <div class="card" style="padding:16px">
        <div class="row" style="justify-content:space-between;margin-bottom:12px">
          <b>Transfer &amp; Archival Audit History</b>
          <input id="tc-search-hist" placeholder="Filter history…" value="${esc(TC.searchHistory)}" style="width:200px;padding:4px 8px;font-size:12px">
        </div>
        <div style="max-height:550px;overflow-y:auto">
          <table>
            <thead>
              <tr>
                <th>Job ID / Study</th><th>Operation</th><th>Source → Destination</th><th>Files / Size</th><th>Verification</th><th>Durability</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${TC.history
                .filter(h => !TC.searchHistory || JSON.stringify(h).toLowerCase().includes(TC.searchHistory.toLowerCase()))
                .map(h => `
                  <tr style="cursor:pointer" data-view-job="${esc(h.job_id || '')}">
                    <td><b>${esc(h.study_id || h.job_id || '—')}</b></td>
                    <td><span class="pill pri">${esc(h.operation || 'transfer')}</span></td>
                    <td class="mono" style="font-size:11px" title="${esc(h.source)} → ${esc(h.destination)}">
                      ${esc((h.source || '').slice(-20))} → ${esc((h.destination || '').slice(-20))}
                    </td>
                    <td>${h.completed_files || 0} files (${round((h.completed_bytes || 0) / (1024 * 1024), 1)} MB)</td>
                    <td><span class="pill ${h.verification_status==='verified'?'ok':'mut'}">${esc(h.verification_status || 'unverified')}</span></td>
                    <td><span class="pill ${h.durability_level==='F_FULLFSYNC'?'ok':'pri'}">${esc(h.durability_level || 'standard')}</span></td>
                    <td><span class="pill ${h.status==='completed'?'ok':h.status==='failed'?'bad':'warn'}">${esc(h.status || 'unknown')}</span></td>
                  </tr>
                `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    ` : ""}

    <!-- Interrupted / Recovery View -->
    ${TC.activeTab === "interrupted" ? `
      <div class="card" style="padding:16px">
        <div class="row" style="justify-content:space-between;margin-bottom:12px">
          <b>Interrupted Transfer Recovery &amp; Quarantine Inspection</b>
          <span class="note">Crash-safe recovery of partial (.part) transfers</span>
        </div>
        ${TC.interrupted.length === 0 ? `
          <div style="text-align:center;padding:36px;color:var(--ok)">
            ✓ Zero interrupted transfers or corrupt partial files detected. Storage state is clean.
          </div>
        ` : `
          <div style="display:flex;flex-direction:column;gap:12px">
            ${TC.interrupted.map(it => `
              <div style="padding:12px;background:var(--panel2);border:1px solid var(--bad);border-radius:6px">
                <div class="row" style="justify-content:space-between;margin-bottom:6px">
                  <span style="font-weight:700;color:var(--bad)">⚠ ${esc(it.study_id || it.job_id)}</span>
                  <span class="pill bad">${esc(it.status || 'Interrupted')}</span>
                </div>
                <div class="note" style="margin-bottom:4px"><b>Target:</b> <span class="mono">${esc(it.destination || it.part_file_path || '—')}</span></div>
                <div class="note" style="margin-bottom:4px"><b>Last Confirmed State:</b> ${esc(it.last_confirmed_state || 'Unknown')}</div>
                <div class="note" style="margin-bottom:8px"><b>Recommended Recovery:</b> ${esc(it.recommended_action || 'Review and recopy from source')}</div>
                <div class="row" style="gap:8px;margin:0">
                  <button class="b sm pri" data-resume-job="${esc(it.job_id)}">Resume from Checkpoint</button>
                  <button class="b sm bad" data-discard-part="${esc(it.part_file_path || it.job_id)}">Discard Partial File</button>
                </div>
              </div>
            `).join("")}
          </div>
        `}
      </div>
    ` : ""}
  `;

  if (isUpdate) v.scrollTop = scrollPos;

  // Bind tab clicks
  ["active", "queue", "history", "interrupted"].forEach(tab => {
    const el = $(`#tc-tab-${tab}`);
    if (el) el.onclick = () => {
      TC.activeTab = tab;
      renderTransferCenter(v);
    };
  });

  // Search history binding
  const sh = $("#tc-search-hist");
  if (sh) {
    sh.oninput = (e) => {
      TC.searchHistory = e.target.value;
      renderTransferCenter(v, true);
    };
  }

  // Active job controls
  v.querySelectorAll("[data-pause-job]").forEach(b => {
    b.onclick = async () => {
      await api("/api/transfer/pause", { job_id: b.dataset.pauseJob });
      await fetchTransferData(true);
      renderTransferCenter(v, true);
    };
  });

  v.querySelectorAll("[data-cancel-job]").forEach(b => {
    b.onclick = async () => {
      if (!confirm("Are you sure you want to cancel this transfer safely?")) return;
      await api("/api/transfer/cancel", { job_id: b.dataset.cancelJob });
      await fetchTransferData(true);
      renderTransferCenter(v, true);
    };
  });
}

function renderActiveJobCard(job) {
  const pct = job.percent || 0;
  const speed = job.speed_str || `${round(job.current_mb_s, 1)} MB/s`;
  const eta = job.eta_str || (job.eta_seconds ? `${int(job.eta_seconds)}s` : "—");
  const curPhase = job.current_phase || "Copying";

  // Step timeline stages
  const stages = ["Queued", "Preparing", "Copying", "Flushing", "Verifying", "Committing", "Completed"];
  const curIdx = stages.indexOf(curPhase) >= 0 ? stages.indexOf(curPhase) : 2;

  return `
    <div style="padding:14px;background:var(--panel2);border:1px solid var(--line);border-radius:8px">
      <div class="row" style="justify-content:space-between;margin-bottom:8px">
        <div>
          <b style="font-size:14px">${esc(job.study_id || job.job_id)}</b>
          <span class="pill pri" style="margin-left:6px">${esc(job.operation || 'transfer')}</span>
        </div>
        <div class="row" style="gap:6px;margin:0">
          <button class="b sm" data-pause-job="${esc(job.job_id)}">⏸ Pause</button>
          <button class="b sm bad" data-cancel-job="${esc(job.job_id)}">✕ Cancel</button>
        </div>
      </div>

      <!-- Step Timeline -->
      <div style="display:flex;justify-content:space-between;margin:8px 0 12px;font-size:11px">
        ${stages.map((st, idx) => `
          <div style="display:flex;flex-direction:column;align-items:center;flex:1;opacity:${idx <= curIdx ? '1' : '0.4'}">
            <span style="width:14px;height:14px;border-radius:50%;background:${idx < curIdx ? 'var(--ok)' : idx === curIdx ? 'var(--pri)' : 'var(--mut)'};color:#fff;display:flex;align-items:center;justify-content:center;font-size:9px;margin-bottom:2px">
              ${idx < curIdx ? '✓' : idx + 1}
            </span>
            <span style="font-weight:${idx === curIdx ? '700' : '400'}">${st}</span>
          </div>
        `).join("")}
      </div>

      <!-- Progress Bar & Metrics -->
      <div class="bar" style="height:8px;margin-bottom:6px"><i style="width:${pct}%;background:var(--pri)"></i></div>
      
      <div class="row" style="justify-content:space-between;font-size:12px;color:var(--mut)">
        <span>${pct}% · ${job.completed_files || 0}/${job.total_files || 0} files (${round((job.completed_bytes || 0)/(1024*1024), 1)}/${round((job.total_bytes || 0)/(1024*1024), 1)} MB)</span>
        <span><b>Speed:</b> ${speed} · <b>ETA:</b> ${eta}</span>
      </div>

      ${job.current_file ? `
        <div class="note mono" style="font-size:11px;margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          Current file: ${esc(job.current_file)}
        </div>
      ` : ""}
    </div>
  `;
}
