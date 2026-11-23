// sync_view.js - Dedicated Synchronization Center for PERCIVAL.
// Manages policy-driven, category-aware synchronization between Mac SSD active workspace
// and External Data Vault with pre-sync dry run preview, conflict management, and auto triggers.

const SYNC = {
  overview: null,
  preview: null,
  policy: null,
  activeTab: "overview", // "overview", "preview", "activity", "policies"
  isSyncing: false
};

async function syncView(v) {
  v.innerHTML = `<div class="card" style="padding:20px;text-align:center"><span class="mut">Loading Sync Center…</span></div>`;
  await fetchSyncData();
  renderSyncCenter(v);
}

async function fetchSyncData() {
  try {
    const [ovRes, polRes, prevRes] = await Promise.all([
      api("/api/storage/sync_overview"),
      api("/api/storage/sync_policy"),
      api("/api/storage/sync_preview?mode=preview")
    ]);
    if (ovRes && ovRes.ok) SYNC.overview = ovRes;
    if (polRes && polRes.ok) SYNC.policy = polRes.policy;
    if (prevRes) SYNC.preview = prevRes;
  } catch (e) {
    console.error("Failed fetching sync data:", e);
  }
}

function renderSyncCenter(v) {
  const ov = SYNC.overview || {};
  const pol = SYNC.policy || {};
  const prev = SYNC.preview || {};

  const isConnected = ov.external_connected;
  const connClass = isConnected ? "ok" : "bad";

  v.innerHTML = `
    <!-- Top Telemetry & Status Bar -->
    <div class="row" style="gap:16px;margin-bottom:16px">
      <div class="card" style="flex:1;margin:0;padding:14px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:6px">
          <b>External Data Vault Connection</b>
          <span class="pill ${connClass}">${isConnected ? "CONNECTED" : "DISCONNECTED"}</span>
        </div>
        <div class="note">${esc(ov.vault_mount || "No external volume mounted")}</div>
      </div>

      <div class="card" style="flex:1;margin:0;padding:14px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:6px">
          <b>Pending Sync Data</b>
          <span class="pill ${ov.pending_items_count > 0 ? 'warn' : 'ok'}">${ov.pending_items_count || 0} items (${ov.pending_mb || 0} MB)</span>
        </div>
        <div class="note">Last successful sync: ${ov.last_successful_sync ? new Date(ov.last_successful_sync * 1000).toLocaleString() : 'Never / Clean State'}</div>
      </div>
    </div>

    <!-- Mode Tabs & Manual Sync Action Header -->
    <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:16px;gap:12px;flex-wrap:wrap">
      <div class="subtabs" style="margin:0">
        <button class="${SYNC.activeTab === 'overview' ? 'on' : ''}" id="sync-tab-ov">Sync Overview</button>
        <button class="${SYNC.activeTab === 'preview' ? 'on' : ''}" id="sync-tab-prev">Dry-Run Preview (${(prev.items_to_copy || []).length})</button>
        <button class="${SYNC.activeTab === 'policies' ? 'on' : ''}" id="sync-tab-pol">Policies &amp; Triggers</button>
      </div>

      <div class="row" style="gap:8px;margin:0">
        <button class="b" id="sync-recheck-btn">↻ Recheck Status</button>
        <button class="b pri" id="sync-now-btn" ${(!isConnected || (prev.items_to_copy || []).length === 0) ? 'disabled' : ''}>
          ⚡ Manual Sync Now
        </button>
      </div>
    </div>

    <!-- Sync Overview Tab -->
    ${SYNC.activeTab === "overview" ? `
      <div class="card" style="padding:16px">
        <b style="font-size:15px;display:block;margin-bottom:12px">Synchronization Health &amp; Category Status</b>
        <table>
          <thead>
            <tr>
              <th>Scientific Data Category</th><th>Recommended Storage Rule</th><th>Status in Vault</th><th>Sync Enabled</th>
            </tr>
          </thead>
          <tbody>
            ${Object.entries((pol.categories || {})).map(([catKey, catVal]) => `
              <tr>
                <td><b>${esc(catKey.replace(/_/g, ' ').toUpperCase())}</b></td>
                <td>${esc(catVal.description || '—')}</td>
                <td><span class="pill ${catVal.enabled ? 'ok' : 'mut'}">${catVal.immutable ? 'Immutable Permanent' : (catVal.enabled ? 'Synchronized' : 'Excluded')}</span></td>
                <td>
                  <input type="checkbox" class="sync-cat-chk" data-cat="${esc(catKey)}" ${catVal.enabled ? 'checked' : ''} ${catVal.immutable ? 'disabled' : ''}>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>

        <div style="margin-top:16px;padding:12px;background:var(--panel2);border:1px solid var(--line);border-radius:6px">
          <div style="font-weight:600;margin-bottom:4px">Durability &amp; Invariant Guarantee:</div>
          <div class="note">
            Synchronization archives verified studies and Pensieve database snapshots from Mac SSD to external Vault.
            <b>Cleanup is strictly separated:</b> synchronization never deletes local or source data. Local workspace cleanup requires its own explicit review eligibility check.
          </div>
        </div>
      </div>
    ` : ""}

    <!-- Dry-Run Preview Tab -->
    ${SYNC.activeTab === "preview" ? `
      <div class="card" style="padding:16px">
        <div class="row" style="justify-content:space-between;margin-bottom:12px">
          <b>Pre-Sync Dry-Run Inspection</b>
          <span class="note">${(prev.items_to_copy || []).length} new/changed, ${(prev.items_conflicting || []).length} conflicts, ${(prev.items_skipped || []).length} skipped</span>
        </div>
        ${(prev.items_to_copy || []).length === 0 ? `
          <div style="text-align:center;padding:36px;color:var(--ok)">
            ✓ External Data Vault is fully up to date with active workspace. No files pending transfer.
          </div>
        ` : `
          <div style="max-height:480px;overflow-y:auto">
            <table>
              <thead>
                <tr>
                  <th>Study ID</th><th>Relative Path</th><th>Source (SSD)</th><th>Size</th><th>Action</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                ${(prev.items_to_copy || []).map(it => `
                  <tr>
                    <td><b>${esc(it.study_id)}</b></td>
                    <td class="mono" style="font-size:11px">${esc(it.relative_path)}</td>
                    <td class="mono" style="font-size:11px" title="${esc(it.source_path)}">${esc((it.source_path || '').slice(-25))}</td>
                    <td>${(Math.round(((it.size_bytes || 0) / (1024 * 1024)) * 100) / 100).toFixed(2)} MB</td>
                    <td><span class="pill pri">Archive</span></td>
                    <td class="note">${esc(it.reason || 'New output')}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>
    ` : ""}

    <!-- Policies & Triggers Tab -->
    ${SYNC.activeTab === "policies" ? `
      <div class="card" style="padding:16px">
        <b style="font-size:15px;display:block;margin-bottom:12px">Configurable Automatic Triggers</b>
        <div style="display:flex;flex-direction:column;gap:10px">
          <label class="row" style="gap:10px;margin:0;cursor:pointer">
            <input type="checkbox" id="sync-trig-study" ${(pol.auto_triggers || {}).on_study_completed ? 'checked' : ''}>
            <span><b>On Study Completion:</b> Automatically trigger archival when a study finishes scientific processing</span>
          </label>
          <label class="row" style="gap:10px;margin:0;cursor:pointer">
            <input type="checkbox" id="sync-trig-review" ${(pol.auto_triggers || {}).on_review_completed ? 'checked' : ''}>
            <span><b>After Expert Review:</b> Immediately preserve and backup expert annotations to Vault</span>
          </label>
          <label class="row" style="gap:10px;margin:0;cursor:pointer">
            <input type="checkbox" id="sync-trig-reconnect" ${(pol.auto_triggers || {}).on_drive_reconnect ? 'checked' : ''}>
            <span><b>On External Drive Reconnect:</b> Automatically resume pending sync queues when Vault is mounted</span>
          </label>
          <div class="row" style="gap:10px;margin-top:6px">
            <span><b>Scheduled Interval (minutes):</b></span>
            <input type="number" id="sync-interval" value="${(pol.auto_triggers || {}).schedule_interval_minutes || 60}" style="width:80px;padding:4px 8px">
          </div>
        </div>
        <div style="margin-top:16px">
          <button class="b pri" id="sync-save-policy-btn">Save Policy Configuration</button>
        </div>
      </div>
    ` : ""}
  `;

  // Bind tab switching
  const bOv = $("#sync-tab-ov"), bPrev = $("#sync-tab-prev"), bPol = $("#sync-tab-pol");
  if (bOv) bOv.onclick = () => { SYNC.activeTab = "overview"; renderSyncCenter(v); };
  if (bPrev) bPrev.onclick = () => { SYNC.activeTab = "preview"; renderSyncCenter(v); };
  if (bPol) bPol.onclick = () => { SYNC.activeTab = "policies"; renderSyncCenter(v); };

  // Recheck button
  const bRecheck = $("#sync-recheck-btn");
  if (bRecheck) bRecheck.onclick = async () => {
    bRecheck.disabled = true;
    bRecheck.textContent = "Checking…";
    await fetchSyncData();
    renderSyncCenter(v);
  };

  // Manual Sync Now button
  const bSyncNow = $("#sync-now-btn");
  if (bSyncNow) bSyncNow.onclick = async () => {
    const toCopy = prev.items_to_copy || [];
    if (!confirm(`Execute Manual Synchronization?\n\nFiles to archive: ${toCopy.length} (${(Math.round(prev.total_bytes / (1024 * 1024) * 10) / 10).toFixed(1)} MB)\nDestination: External Data Vault\nIntegrity: In-flight SHA-256 + atomic commit\n\nClick OK to proceed.`)) return;

    bSyncNow.disabled = true;
    bSyncNow.textContent = "Synchronizing…";
    const res = await api("/api/storage/sync_execute", { preview: prev });
    if (res.ok) {
      toast(`Sync Complete: ${res.transferred_count} files archived to Vault!`);
      await fetchSyncData();
      renderSyncCenter(v);
    } else {
      toast(`Sync error: ${res.error}`, true);
      bSyncNow.disabled = false;
      bSyncNow.textContent = "⚡ Manual Sync Now";
    }
  };

  // Save Policy button
  const bSavePol = $("#sync-save-policy-btn");
  if (bSavePol) bSavePol.onclick = async () => {
    const newPol = JSON.parse(JSON.stringify(SYNC.policy || {}));
    if (!newPol.auto_triggers) newPol.auto_triggers = {};
    newPol.auto_triggers.on_study_completed = $("#sync-trig-study").checked;
    newPol.auto_triggers.on_review_completed = $("#sync-trig-review").checked;
    newPol.auto_triggers.on_drive_reconnect = $("#sync-trig-reconnect").checked;
    newPol.auto_triggers.schedule_interval_minutes = parseInt($("#sync-interval").value, 10) || 60;

    const res = await api("/api/storage/sync_policy", { policy: newPol });
    if (res.ok) {
      toast("Sync policy updated successfully");
      SYNC.policy = res.policy;
      renderSyncCenter(v);
    } else {
      toast(`Error saving policy: ${res.error}`, true);
    }
  };
}
