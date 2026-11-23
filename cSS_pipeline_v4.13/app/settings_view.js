// settings_view.js - Master Redesigned Settings Control Centre for PERCIVAL
// Implements 23 full-page hierarchical sections organized across Groups A through E:
// A. Application (1-4)
// B. Processing & Performance (5-8)
// C. Storage & Data Management (9-16, including Storage Overview, File Manager, Transfer Manager, Cleaning Manager)
// D. Research & Scientific Data (17-20)
// E. System & Recovery (21-23)

const SV = {
  currentSection: "c_overview",
  searchQuery: "",
  storageData: null,
  transferQueue: [],
  cleaningDashboard: null,
  quarantineItems: []
};

const SETTINGS_SECTIONS = [
  // Group A: Application
  { id: "a_general", group: "A. Application", num: 1, title: "General & Appearance", desc: "Display themes, system awake locks, and project identity.", keywords: "theme dark light awake keepawake name project" },
  { id: "a_notif", group: "A. Application", num: 2, title: "Notifications", desc: "Alert banners, notification curtain, and audible system alerts.", keywords: "notifications alerts sound banners finished failed" },
  { id: "a_setup", group: "A. Application", num: 3, title: "Installation & Setup", desc: "System readiness, FreeSurfer installation, and licences.", keywords: "setup wizard freesurfer licence installation preflight" },
  { id: "a_security", group: "A. Application", num: 4, title: "Security & Permissions", desc: "Application passphrase lock, patient name protection, and identity vault.", keywords: "security lock password passphrase filevault privacy incognito permissions" },

  // Group B: Processing & Performance
  { id: "b_processing", group: "B. Processing & Performance", num: 5, title: "Processing Configuration", desc: "Pathway fallback logic, automatic retry heuristics, and re-run rules.", keywords: "pathway synthseg synthmorph recon-all retry auto_path rerun" },
  { id: "b_hardware", group: "B. Processing & Performance", num: 6, title: "CPU, GPU & Memory", desc: "Concurrency, multi-threading allocation, and RAM pressure zones.", keywords: "threads cpu memory ram parallel gpu concurrency" },
  { id: "b_scratch", group: "B. Processing & Performance", num: 7, title: "Scratch & Temporary Storage", desc: "Intermediate resampling buffer paths, quotas, and fast cleanup.", keywords: "scratch temp temporary buffer quota" },
  { id: "b_pipeline", group: "B. Processing & Performance", num: 8, title: "Pipeline Configuration", desc: "Quality indicators, duplicate checks, and radiologist review viewer settings.", keywords: "pipeline features duplicate qc_snapshot preflight reviewer" },

  // Group C: Storage & Data Management
  { id: "c_overview", group: "C. Storage & Data Management", num: 9, title: "Storage Overview", desc: "Live visual capacity bars for Mac Internal SSD and External Data Vault.", keywords: "storage overview bars capacity disk mac hdd free space usage gb tb" },
  { id: "c_filemanager", group: "C. Storage & Data Management", num: 10, title: "File Manager", desc: "Full-page storage browser, study discovery, transfers, and file operations.", keywords: "file manager files browse copy move rename delete archive restore verify sha256" },
  { id: "c_vault", group: "C. Storage & Data Management", num: 11, title: "PERCIVAL Data Vault", desc: "External permanent research archive, stable volume UUID, and Finder integration.", keywords: "vault data_vault external drive hdd finder uuid manifest verify connect" },
  { id: "c_locations", group: "C. Storage & Data Management", num: 12, title: "Storage Locations & Destinations", desc: "Independent folder destinations for all 10 managed scientific data categories.", keywords: "locations destinations paths working_dir scratch originals subjects albus exports" },
  { id: "c_transfer", group: "C. Storage & Data Management", num: 13, title: "Automatic Transfer & Migration", desc: "Category-specific archival policies, transfer queue, and Free Up Mac Space.", keywords: "transfer migration queue free_space mac move copy auto archive policies" },
  { id: "c_cleaning", group: "C. Storage & Data Management", num: 14, title: "Cleaning Manager", desc: "Lifecycle retention by days, quarantine inspection, study/cohort deletion.", keywords: "clean cleaning retention days purge quarantine restore delete prune history" },
  { id: "c_archive", group: "C. Storage & Data Management", num: 15, title: "Archiving & Retention", desc: "Cold storage retention schedules and preservation safeguards.", keywords: "archive retention permanent policy schedule" },
  { id: "c_backup", group: "C. Storage & Data Management", num: 16, title: "Backup & Integrity", desc: "Zero-corruption Pensieve database snapshots and journal integrity.", keywords: "backup pensieve snapshot restore database integrity" },

  // Group D: Research & Scientific Data
  { id: "d_pensieve", group: "D. Research & Scientific Data", num: 17, title: "Pensieve Core Memory", desc: "SQLite transactional database, candidate identities, and missed lesion ledger.", keywords: "pensieve memory sqlite candidates missed_lesions journal provenance" },
  { id: "d_training", group: "D. Research & Scientific Data", num: 18, title: "Training & Dataset Management", desc: "Supervised label datasets, patient-grouped splits, and leakage prevention.", keywords: "training datasets splits leakage cross-validation manifest" },
  { id: "d_models", group: "D. Research & Scientific Data", num: 19, title: "Models & Checkpoints", desc: "Active and historical neural network weights, calibrations, and checkpoints.", keywords: "models checkpoints weights calibration albus lumos nox percival" },
  { id: "d_advanced", group: "D. Research & Scientific Data", num: 20, title: "Advanced Research Settings", desc: "Shadow ML laboratory, unified scoring prototypes, and experimental flags.", keywords: "shadow_ml research experimental prototypes unified_score" },

  // Group E: System & Recovery
  { id: "e_recovery", group: "E. System & Recovery", num: 21, title: "Recovery Centre", desc: "Crash recovery, interrupted run resumption, and transactional job logs.", keywords: "recovery resume crash interrupted jobs transactions" },
  { id: "e_health", group: "E. System & Recovery", num: 22, title: "Startup Health & Diagnostics", desc: "19-point diagnostic engine, degraded mode telemetry, and self-repair.", keywords: "health diagnostics 19-point check degraded repair" },
  { id: "e_activity", group: "E. System & Recovery", num: 23, title: "Activity & Operation History", desc: "Audit logs, migration journals, and data lifecycle transaction records.", keywords: "activity history audit log journal operations" },
];

async function settingsControlCentre(v, initialSection) {
  if (initialSection) SV.currentSection = initialSection;

  // Load live storage overview data for persistent widget
  try {
    SV.storageData = await api("/api/storage/overview");
  } catch (e) {
    SV.storageData = null;
  }

  renderSettingsLayout(v);
}

function renderSettingsLayout(v) {
  const q = SV.searchQuery.toLowerCase().trim();
  const filtered = q
    ? SETTINGS_SECTIONS.filter(s => s.title.toLowerCase().includes(q) || s.desc.toLowerCase().includes(q) || s.keywords.includes(q))
    : SETTINGS_SECTIONS;

  // Group sections
  const groups = {};
  filtered.forEach(s => {
    if (!groups[s.group]) groups[s.group] = [];
    groups[s.group].push(s);
  });

  // Capacity mini widgets
  const mac = (SV.storageData && SV.storageData.mac_internal) || { free_pct: 0, available_gb: 0, total_gb: 0, tier: "HEALTHY" };
  const vault = (SV.storageData && SV.storageData.external_vault) || { connected: false, free_pct: 0, available_gb: 0, tier: "DISCONNECTED" };
  const macClass = mac.tier === "EMERGENCY" ? "bad" : mac.tier === "CRITICAL" ? "warn" : "ok";
  const vaultClass = vault.connected ? (vault.tier === "EMERGENCY" ? "bad" : vault.tier === "CRITICAL" ? "warn" : "ok") : "bad";

  v.innerHTML = `
    <div style="display:flex;gap:20px;min-height:750px;align-items:flex-start">
      <!-- Left Persistent Settings Navigation Sidebar -->
      <div style="width:280px;flex-shrink:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px;display:flex;flex-direction:column;gap:12px">
        
        <!-- Search Settings Toolbar -->
        <div>
          <input id="set-search-input" value="${esc(SV.searchQuery)}" placeholder="🔍 Search all 23 settings…" style="width:100%;font-size:13px;padding:8px 10px">
        </div>

        <!-- Section Navigation Links -->
        <div style="display:flex;flex-direction:column;gap:14px;max-height:560px;overflow-y:auto;padding-right:4px">
          ${Object.keys(groups).length === 0 ? `<div class="note" style="padding:10px">No matching settings found.</div>` : ''}
          ${Object.entries(groups).map(([grpName, items]) => `
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;padding-left:6px">${esc(grpName)}</div>
              <div style="display:flex;flex-direction:column;gap:2px">
                ${items.map(it => `
                  <button class="b sm ${SV.currentSection === it.id ? "pri" : ""}" data-set-sec="${it.id}" style="justify-content:flex-start;text-align:left;padding:7px 10px;border-radius:6px;width:100%;display:flex;align-items:center;gap:8px">
                    <span style="opacity:0.6;font-family:monospace;font-size:11px;min-width:18px">${it.num}.</span>
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;flex:1">${esc(it.title)}</span>
                  </button>
                `).join("")}
              </div>
            </div>
          `).join("")}
        </div>

        <!-- Compact Storage Summary Mini-Pill -->
        <div style="border-top:1px solid var(--line);padding-top:12px;margin-top:auto">
          <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Live Storage Monitor</div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <div style="cursor:pointer;background:var(--panel2);padding:6px 8px;border-radius:6px;font-size:12px" data-set-sec="c_overview">
              <div style="display:flex;justify-content:space-between">
                <span>Mac NVMe SSD</span>
                <span class="pill ${macClass}" style="font-size:10px;padding:0 5px">${mac.available_gb} GB free</span>
              </div>
              <div class="bar" style="height:4px;margin-top:4px"><i style="width:${Math.min(100, 100 - mac.free_pct)}%;background:var(--${macClass})"></i></div>
            </div>
            <div style="cursor:pointer;background:var(--panel2);padding:6px 8px;border-radius:6px;font-size:12px" data-set-sec="c_overview">
              <div style="display:flex;justify-content:space-between">
                <span>External Vault</span>
                <span class="pill ${vaultClass}" style="font-size:10px;padding:0 5px">${vault.connected ? `${vault.available_gb} GB free` : 'DISCONNECTED'}</span>
              </div>
              <div class="bar" style="height:4px;margin-top:4px"><i style="width:${vault.connected ? Math.min(100, 100 - vault.free_pct) : 0}%;background:var(--${vaultClass})"></i></div>
            </div>
          </div>
        </div>

      </div>

      <!-- Right Main Full-Page Configuration Content Pane -->
      <div id="settings-content-pane" style="flex:1;min-width:0">
        <!-- Rendered dynamically below -->
      </div>
    </div>
  `;

  // Bind Search Input
  const searchInput = $("#set-search-input");
  if (searchInput) {
    searchInput.oninput = (e) => {
      SV.searchQuery = e.target.value;
      renderSettingsLayout(v);
      const inputAfter = $("#set-search-input");
      if (inputAfter) {
        inputAfter.focus();
        inputAfter.setSelectionRange(inputAfter.value.length, inputAfter.value.length);
      }
    };
  }

  // Bind Section Links
  v.querySelectorAll("[data-set-sec]").forEach(b => {
    b.onclick = () => {
      SV.currentSection = b.dataset.setSec;
      renderSettingsSection(v);
    };
  });

  renderSettingsSection(v);
}

async function renderSettingsSection(v) {
  const pane = $("#settings-content-pane");
  if (!pane) return;

  // Update active state in sidebar
  v.querySelectorAll("[data-set-sec]").forEach(b => {
    if (b.dataset.setSec === SV.currentSection) {
      b.classList.add("pri");
    } else {
      b.classList.remove("pri");
    }
  });

  const secMeta = SETTINGS_SECTIONS.find(s => s.id === SV.currentSection) || SETTINGS_SECTIONS[0];

  // Header banner for current section
  const headerHtml = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;border-bottom:1px solid var(--line);padding-bottom:12px">
      <div>
        <div class="note" style="font-size:12px;margin-bottom:2px">${esc(secMeta.group)} › Section ${secMeta.num}</div>
        <h2 style="margin:0;font-size:20px;font-weight:700">${esc(secMeta.title)}</h2>
        <div class="mut" style="font-size:13px;margin-top:4px">${esc(secMeta.desc)}</div>
      </div>
      <div>
        <span class="pill ok">Active</span>
      </div>
    </div>
  `;

  pane.innerHTML = headerHtml + `<div id="section-inner-host"><div class="card" style="text-align:center;padding:30px"><span class="mut">Loading configuration…</span></div></div>`;
  const host = $("#section-inner-host");

  // Route to section implementation
  try {
    switch (SV.currentSection) {
      case "a_general":
        await renderSectionGeneral(host);
        break;
      case "a_notif":
        await renderSectionNotifications(host);
        break;
      case "a_setup":
        await renderSectionSetup(host);
        break;
      case "a_security":
        await renderSectionSecurity(host);
        break;
      case "b_processing":
        await renderSectionProcessing(host);
        break;
      case "b_hardware":
        await renderSectionHardware(host);
        break;
      case "b_scratch":
        await renderSectionScratch(host);
        break;
      case "b_pipeline":
        await renderSectionPipeline(host);
        break;
      case "c_overview":
        await renderSectionStorageOverview(host);
        break;
      case "c_filemanager":
        await renderSectionFileManager(host);
        break;
      case "c_vault":
        await renderSectionVault(host);
        break;
      case "c_locations":
        await renderSectionLocations(host);
        break;
      case "c_transfer":
        await renderSectionTransfer(host);
        break;
      case "c_cleaning":
        await renderSectionCleaning(host);
        break;
      case "c_archive":
        await renderSectionArchive(host);
        break;
      case "c_backup":
        await renderSectionBackup(host);
        break;
      case "d_pensieve":
        await renderSectionPensieve(host);
        break;
      case "d_training":
        await renderSectionTraining(host);
        break;
      case "d_models":
        await renderSectionModels(host);
        break;
      case "d_advanced":
        await renderSectionAdvanced(host);
        break;
      case "e_recovery":
        await renderSectionRecovery(host);
        break;
      case "e_health":
        await renderSectionHealth(host);
        break;
      case "e_activity":
        await renderSectionActivity(host);
        break;
      default:
        await renderSectionStorageOverview(host);
    }
  } catch (err) {
    host.innerHTML = `<div class="card bad">Error loading section: ${esc(err.message)}</div>`;
  }
}

// ----------------------------------------------------------------------------
// Section C.9: Storage Overview (Live Mac and External HDD Capacity Bars)
// ----------------------------------------------------------------------------
async function renderSectionStorageOverview(el) {
  const data = await api("/api/storage/overview");
  SV.storageData = data;
  const mac = data.mac_internal || {};
  const v = data.external_vault || {};
  const bd = mac.breakdown || {};

  const macClass = mac.tier === "EMERGENCY" ? "bad" : mac.tier === "CRITICAL" ? "warn" : "ok";
  const vaultClass = v.connected ? (v.tier === "EMERGENCY" ? "bad" : v.tier === "CRITICAL" ? "warn" : "ok") : "bad";

  el.innerHTML = `
    <!-- Top Action Toolbar -->
    <div class="row" style="justify-content:space-between;margin-bottom:14px">
      <span class="note">Last measured: <b>${esc(data.updated_at || "Just now")}</b></span>
      <div class="row" style="gap:8px;margin:0">
        <button class="b sm" id="so-refresh">↻ Refresh Storage Capacity</button>
        <button class="b sm pri" id="so-free-mac">Free Up Mac Space…</button>
      </div>
    </div>

    <!-- 1. Mac Storage Bar -->
    <div class="card" style="padding:18px;margin-bottom:16px">
      <div class="row" style="justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <b style="font-size:16px">${esc(mac.volume_name || "Mac Internal Storage")}</b>
          <div class="mono" style="font-size:12px;color:var(--mut)">Mount: ${esc(mac.mount_point || "/")} · Path: ${esc(mac.path || "")}</div>
        </div>
        <div style="text-align:right">
          <span class="pill ${macClass}" style="font-weight:700">${mac.available_gb} GB Free (${mac.free_pct}%)</span>
          <div class="note" style="margin-top:4px">Used: ${mac.used_gb} GB / Total: ${mac.total_gb} GB</div>
        </div>
      </div>

      <div class="bar" style="height:12px;border-radius:6px;margin:12px 0 8px">
        <i style="width:${Math.min(100, mac.used_pct || 0)}%;background:var(--${macClass});border-radius:6px"></i>
      </div>

      <div class="note" style="margin-bottom:12px">${esc(mac.status_message || "")}</div>

      <!-- Category Breakdown -->
      <div style="background:var(--panel2);border-radius:8px;padding:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;font-size:12.5px">
        <div>Active Working Space: <b>${bd.active_workspace_mb || 0} MB</b></div>
        <div>Temporary Scratch: <b>${bd.scratch_mb || 0} MB</b></div>
        <div>Multi-Study Staging: <b>${bd.staging_mb || 0} MB</b></div>
        <div>Original MRI Data: <b>${bd.original_mri_mb || 0} MB</b></div>
        <div>Quarantined Files: <b>${bd.quarantine_mb || 0} MB</b></div>
        <div>PERCIVAL Managed Total: <b>${mac.percival_managed_gb || 0} GB</b></div>
      </div>
    </div>

    <!-- 2. External HDD Storage Bar -->
    <div class="card" style="padding:18px">
      <div class="row" style="justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <b style="font-size:16px">${esc(v.volume_name || "External Data Vault")}</b>
          <div class="mono" style="font-size:12px;color:var(--mut)">
            ${v.connected ? `Mount: ${esc(v.mount_point)} · UUID: ${esc(v.volume_uuid || "Stable")}` : "External drive not detected at expected mount path"}
          </div>
        </div>
        <div style="text-align:right">
          <span class="pill ${vaultClass}" style="font-weight:700">
            ${v.connected ? `${v.available_gb} GB Free (${v.free_pct}%)` : "DISCONNECTED / UNAVAILABLE"}
          </span>
          <div class="note" style="margin-top:4px">
            ${v.connected ? `Used: ${v.used_gb} GB / Total: ${v.total_gb} GB` : "Connect external drive containing PERCIVAL_VAULT"}
          </div>
        </div>
      </div>

      <div class="bar" style="height:12px;border-radius:6px;margin:12px 0 8px">
        <i style="width:${v.connected ? Math.min(100, v.used_pct || 0) : 0}%;background:var(--${vaultClass});border-radius:6px"></i>
      </div>

      <div class="note" style="margin-bottom:12px">${esc(v.status_message || "")}</div>

      <div style="background:var(--panel2);border-radius:8px;padding:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;font-size:12.5px">
        <div>PERCIVAL_VAULT Size: <b>${v.vault_usage_gb || 0} GB</b></div>
        <div>Pending Transfers: <b>${v.pending_transfers || 0}</b></div>
        <div>Archive Status: <b>${esc(v.archive_status || "Offline")}</b></div>
        <div>Hardware Identity: <span class="mono">${esc((v.volume_uuid || "—").slice(0, 16))}</span></div>
      </div>

      <div class="row" style="margin-top:14px;gap:8px">
        ${v.connected ? `<button class="b sm" id="so-open-finder">Reveal Vault in Finder</button>` : ''}
        <button class="b sm" id="so-reconnect">Detect / Connect Drive…</button>
      </div>
    </div>
  `;

  // Bind actions
  $("#so-refresh").onclick = async () => {
    toast("Refreshing storage telemetry…");
    const r = await api("/api/storage/overview?force=1");
    SV.storageData = r;
    renderSectionStorageOverview(el);
  };

  $("#so-free-mac").onclick = () => {
    SV.currentSection = "c_transfer";
    renderSettingsSection($("#view"));
  };

  if ($("#so-open-finder")) {
    $("#so-open-finder").onclick = async () => {
      await api("/api/vault/open_finder", {});
    };
  }

  $("#so-reconnect").onclick = async () => {
    const p = await pick("folder", "Select external drive or PERCIVAL_VAULT root");
    if (!p) return;
    const res = await api("/api/vault/connect", { path: p });
    toast(res.ok ? "Connected to Data Vault" : esc(res.message || "Failed to connect"), !res.ok);
    renderSectionStorageOverview(el);
  };
}

// ----------------------------------------------------------------------------
// Section C.10: Full-Page File Manager
// ----------------------------------------------------------------------------
async function renderSectionFileManager(el) {
  el.innerHTML = `<div id="embedded-fm-container"></div>`;
  const container = $("#embedded-fm-container");
  if (typeof filesView === "function") {
    await filesView(container);
  } else {
    container.innerHTML = `<div class="card bad">File Manager component failed to initialize.</div>`;
  }
}

// ----------------------------------------------------------------------------
// Section C.11: PERCIVAL Data Vault
// ----------------------------------------------------------------------------
async function renderSectionVault(el) {
  const vdata = await api("/api/vault/status");
  const stats = vdata.stats || {};
  const status = vdata.status || {};
  const integrity = vdata.integrity || {};
  const detected = vdata.detected_volumes || [];

  el.innerHTML = `
    <div class="card" style="padding:18px">
      <div class="row" style="justify-content:space-between;margin-bottom:12px">
        <div>
          <b>Standard Directory Topology: PERCIVAL_VAULT</b>
          <p class="note" style="margin:2px 0 0">Dedicated research archive located at external storage volume root.</p>
        </div>
        <span class="pill ${status.connected ? 'ok' : 'bad'}">${status.connected ? 'CONNECTED' : 'DISCONNECTED'}</span>
      </div>

      <div class="kv" style="margin-bottom:16px">
        <div>Root Directory</div><div class="mono">${esc(stats.root_path || "Not configured")}</div>
        <div>Volume Identity (UUID)</div><div class="mono">${esc(stats.volume_uuid || "Unknown")}</div>
        <div>Free Storage Space</div><div><b>${stats.free_gb || 0} GB Free</b> (${stats.free_pct || 0}%)</div>
        <div>Vault Integrity</div><div>${integrity.ok ? '<span class="ok">✓ Verified Valid Manifest</span>' : '<span class="warn">Manifest unverified or drive offline</span>'}</div>
      </div>

      <div class="row" style="gap:10px;flex-wrap:wrap">
        <button class="b sm pri" id="sv-open-finder" ${!status.connected ? "disabled" : ""}>Reveal in macOS Finder</button>
        <button class="b sm" id="sv-verify" ${!status.connected ? "disabled" : ""}>Verify Vault Integrity</button>
        <button class="b sm" id="sv-reindex" ${!status.connected ? "disabled" : ""}>Rebuild File Index</button>
        <button class="b sm" id="sv-change">Choose Drive or Folder…</button>
        <button class="b sm" id="sv-create">Create New Vault…</button>
      </div>
    </div>

    <div class="card" style="padding:18px;margin-top:14px">
      <div class="row" style="justify-content:space-between;margin-bottom:8px">
        <b>Detected External Storage Volumes</b>
        <button class="b sm" id="sv-refresh-drives">Scan Volumes Now</button>
      </div>
      <p class="note" style="margin:0 0 12px">Physical external drives detected on this Mac. Select a drive to connect or initialize PERCIVAL_VAULT automatically.</p>
      ${detected.length ? `
        <table style="width:100%;font-size:13px">
          <thead>
            <tr><th>Volume</th><th>Mount Point</th><th>UUID</th><th>Free Space</th><th>Status</th><th>Action</th></tr>
          </thead>
          <tbody>
            ${detected.map(d => `
              <tr>
                <td><b>${esc(d.name)}</b></td>
                <td class="mono" style="font-size:11px">${esc(d.mount_point)}</td>
                <td class="mono" style="font-size:11px">${esc((d.volume_uuid || '').slice(0, 16))}…</td>
                <td><b>${d.free_gb} GB</b> / ${d.total_gb} GB</td>
                <td><span class="pill ${d.has_vault ? 'ok' : (d.writable ? 'warn' : 'bad')}">${d.has_vault ? 'Vault Ready' : (d.writable ? 'Not Initialized' : 'Read-Only')}</span></td>
                <td>
                  <button class="b sm ${d.has_vault ? 'pri' : ''}" data-vdrive="${esc(d.mount_point)}">
                    ${d.has_vault ? 'Connect Vault' : 'Auto-Create Vault'}
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : `<p class="note">No external drives currently detected in /Volumes. Connect an external HDD and click Scan Volumes Now.</p>`}
    </div>
  `;

  $("#sv-open-finder").onclick = async () => {
    await api("/api/vault/open_finder", {});
  };
  $("#sv-verify").onclick = async () => {
    const res = await api("/api/vault/verify", {});
    alert(`Vault Integrity Check:\n${res.integrity && res.integrity.ok ? '✓ Manifest and structure valid' : '✗ Issues detected: ' + JSON.stringify(res.integrity)}`);
  };
  $("#sv-reindex").onclick = async () => {
    const res = await api("/api/vault/reindex", {});
    toast(res.ok ? "Vault index updated" : "Reindex failed", !res.ok);
  };
  $("#sv-refresh-drives").onclick = () => renderSectionVault(el);
  $("#sv-change").onclick = async () => {
    const p = await pick("folder", "Select external drive or PERCIVAL_VAULT folder");
    if (p) {
      const r = await api("/api/vault/connect", { path: p });
      toast(r.ok ? (r.message || "Connected to Data Vault") : esc(r.message || r.error), !r.ok);
      renderSectionVault(el);
    }
  };
  $("#sv-create").onclick = async () => {
    const p = await pick("folder", "Choose external drive root to create PERCIVAL_VAULT");
    if (p) {
      const r = await api("/api/vault/create", { destination: p, name: "PERCIVAL_VAULT" });
      toast(r.ok ? "Created PERCIVAL_VAULT" : esc(r.error), !r.ok);
      renderSectionVault(el);
    }
  };
  el.querySelectorAll("[data-vdrive]").forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "Connecting…";
      const p = btn.dataset.vdrive;
      const r = await api("/api/vault/connect", { path: p });
      toast(r.ok ? (r.message || "Connected to Data Vault") : esc(r.message || r.error), !r.ok);
      renderSectionVault(el);
    };
  });
}

// ----------------------------------------------------------------------------
// Section C.12: Storage Locations & Destinations
// ----------------------------------------------------------------------------
async function renderSectionLocations(el) {
  const s = S.settings || {};
  const cats = [
    { key: "workspace_dir", name: "Working Directory", desc: "Active staging & fast NVMe SSD workspace", path: S.project.path || "Default", mig: true },
    { key: "vault_mount", name: "External Data Vault", desc: "Pensieve database & long-term archive", path: s.vault_mount || "/Volumes/Percival/PERCIVAL_VAULT" },
    { key: "scratch_dir", name: "Scratch Directory", desc: "Intermediate resamplings & matrices", path: s.scratch_dir || (S.project.path + "/app_data/scratch") },
    { key: "originals_dir", name: "Original MRI Acquisitions", desc: "Immutable raw DICOM/NIfTI scans", path: s.originals_dir || (S.project.path + "/data") },
    { key: "processed_dir", name: "Processed MRI (FreeSurfer)", desc: "Cortical surface extractions & masks", path: s.processed_dir || (S.project.path + "/subjects") },
    { key: "albus_dir", name: "ALBUS Outputs", desc: "Sulcal geometries & candidate coordinate tables", path: s.albus_dir || (S.project.path + "/review") },
    { key: "lumos_dir", name: "LUMOS Outputs", desc: "Neural inferences & heatmaps", path: s.lumos_dir || (S.project.path + "/unified_engine/percival") },
    { key: "nox_dir", name: "NOX Outputs", desc: "Quantitative morphology & uncertainty maps", path: s.nox_dir || (S.project.path + "/results/nox") },
    { key: "pensieve_backups_dir", name: "Pensieve Backups", desc: "Zero-corruption SQLite snapshots", path: s.pensieve_backups_dir || (S.project.path + "/app_data/pensieve_snapshots") },
    { key: "export_dir", name: "Reports & Exports", desc: "Clinical PDFs & Excel spreadsheets", path: s.export_dir || (S.project.path + "/results") },
  ];

  el.innerHTML = `
    <div class="card" style="padding:18px">
      <p class="note" style="margin-top:0">All 10 storage categories can be mapped to independent storage destinations across local SSD and external volumes.</p>
      <table>
        <thead>
          <tr><th style="padding:6px">Category</th><th style="padding:6px">Current Path</th><th style="text-align:center;width:120px;padding:6px">Action</th></tr>
        </thead>
        <tbody>
          ${cats.map(c => `
            <tr>
              <td style="padding:8px"><b>${esc(c.name)}</b><div class="note">${esc(c.desc)}</div></td>
              <td class="mono" style="padding:8px;font-size:12px">${esc(c.path)}</td>
              <td style="text-align:center;padding:8px">
                <button class="b sm ${c.mig ? 'pri' : ''}" data-loc="${c.key}">${c.mig ? 'Migrate…' : 'Change…'}</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;

  el.querySelectorAll("[data-loc]").forEach(b => {
    b.onclick = async () => {
      const k = b.dataset.loc;
      if (k === "workspace_dir") {
        const p = await pick("folder", "Choose New Working Directory");
        if (!p) return;
        const plan = await api("/api/storage/migrate_plan", { target_dir: p });
        if (!plan.ok) { alert(`Cannot migrate:\n${plan.error}`); return; }
        if (confirm(`Migrate ${plan.file_count} files (${plan.total_gb} GB) to:\n${plan.target_dir}?`)) {
          toast("Migrating working directory…");
          const res = await api("/api/storage/migrate_execute", { target_dir: p, verify_checksums: true });
          alert(res.ok ? "Migration complete. Restart Percival to switch." : "Migration failed: " + res.error);
        }
      } else {
        const p = await pick("folder", `Select destination for ${k}`);
        if (p) {
          const upd = {}; upd[k] = p;
          await api("/api/settings", upd);
          toast("Location updated");
          renderSectionLocations(el);
        }
      }
    };
  });
}

// ----------------------------------------------------------------------------
// Section C.13: Automatic Transfer & Migration
// ----------------------------------------------------------------------------
async function renderSectionTransfer(el) {
  const [qRes, polRes, previewRes] = await Promise.all([
    api("/api/transfer/queue"),
    api("/api/transfer/policies"),
    api("/api/storage/free_space_preview")
  ]);

  const queue = qRes.queue || [];
  const policies = polRes.policies || {};
  const prev = previewRes || {};

  el.innerHTML = `
    <!-- Free Up Mac Space Card -->
    <div class="card" style="padding:18px;background:var(--panel2);border:1px solid var(--acc);margin-bottom:18px">
      <div class="row" style="justify-content:space-between;align-items:center">
        <div>
          <b style="font-size:16px">Free Up Mac Space</b>
          <p class="note" style="margin:2px 0 0">Reclaim local storage by cleaning verified temporary data and staged caches.</p>
        </div>
        <button class="b pri" id="st-free-btn" ${prev.total_reclaimable_mb > 0 ? '' : 'disabled'}>
          Reclaim ${prev.total_reclaimable_gb || 0} GB Now
        </button>
      </div>
      <div class="note" style="margin-top:8px">
        Audit identified <b>${(prev.items || []).length} items</b> (${prev.total_reclaimable_mb || 0} MB) eligible for immediate safe reclamation.
      </div>
    </div>

    <!-- Transfer Queue -->
    <div class="card" style="padding:18px;margin-bottom:18px">
      <div class="row" style="justify-content:space-between;margin-bottom:10px">
        <b>Durable Transfer Queue (${queue.length} jobs)</b>
        <button class="b sm" id="st-proc-btn">Process Next Transfer</button>
      </div>
      ${queue.length === 0 ? `<div class="note">Queue is currently empty. All data is synchronized.</div>` : `
        <table>
          <thead>
            <tr><th>Job ID</th><th>Study</th><th>Action</th><th>Files</th><th>Size</th><th>Status</th></tr>
          </thead>
          <tbody>
            ${queue.slice(0, 10).map(j => `
              <tr>
                <td class="mono" style="font-size:11px">${esc(j.job_id)}</td>
                <td><b>${esc(j.study_code)}</b></td>
                <td>${esc(j.action)}</td>
                <td>${j.total_files}</td>
                <td>${(j.total_bytes / (1024**2)).toFixed(1)} MB</td>
                <td><span class="pill ${j.status==='completed'?'ok':j.status==='failed'?'bad':'warn'}">${esc(j.status)}</span></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `}
    </div>

    <!-- Archival Policies -->
    <div class="card" style="padding:18px">
      <b>Category Transfer Policies</b>
      <p class="note" style="margin:2px 0 12px">Automatic background migration rules when studies finish processing.</p>
      <div class="row">
        <label style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="st-rem-orig" ${policies.remove_local_original_after_verify ? 'checked' : ''}>
          Remove local original MRI after verified SHA-256 archive (DEFAULT: OFF)
        </label>
      </div>
    </div>
  `;

  $("#st-free-btn").onclick = async () => {
    if (!confirm(`Reclaim ${prev.total_reclaimable_gb} GB from local Mac SSD?`)) return;
    toast("Reclaiming space…");
    const r = await api("/api/storage/free_space_execute", {});
    toast(r.ok ? `Reclaimed ${r.reclaimed_gb} GB` : "Reclamation failed", !r.ok);
    renderSectionTransfer(el);
  };

  $("#st-proc-btn").onclick = async () => {
    toast("Processing transfer…");
    const r = await api("/api/transfer/process_next", {});
    toast(r.ok ? (r.job_id ? "Transfer completed" : "Queue empty") : esc(r.error), !r.ok);
    renderSectionTransfer(el);
  };

  $("#st-rem-orig").onchange = async (e) => {
    await api("/api/transfer/policies", { policies: { remove_local_original_after_verify: e.target.checked } });
    toast("Transfer policy updated");
  };
}

// ----------------------------------------------------------------------------
// Section C.14: Cleaning Manager
// ----------------------------------------------------------------------------
async function renderSectionCleaning(el) {
  const [dashRes, qRes] = await Promise.all([
    api("/api/clean/dashboard"),
    api("/api/clean/quarantine")
  ]);

  const dash = dashRes || {};
  const cats = dash.categories || [];
  const qItems = (qRes && qRes.items) || [];

  el.innerHTML = `
    <!-- Cleaning Summary Header -->
    <div class="row" style="gap:12px;margin-bottom:14px">
      <div class="card" style="flex:1;margin:0;padding:12px">
        <div class="note">Recoverable Space</div>
        <b style="font-size:18px;color:var(--ok)">${dash.total_reclaimable_mb || 0} MB</b>
      </div>
      <div class="card" style="flex:1;margin:0;padding:12px">
        <div class="note">Quarantine Buffer</div>
        <b style="font-size:18px">${qItems.length} items (${dash.quarantine_mb || 0} MB)</b>
      </div>
      <div class="card" style="flex:1;margin:0;padding:12px">
        <div class="note">Cleaning Policy Mode</div>
        <b style="font-size:18px">${esc(String(dash.mode || "assisted").toUpperCase())}</b>
      </div>
    </div>

    <!-- 16 Lifecycle Categories Table -->
    <div class="card" style="padding:18px;margin-bottom:16px">
      <div class="row" style="justify-content:space-between;margin-bottom:10px">
        <b>Data Lifecycle Retention by Category</b>
        <div class="row" style="gap:8px;margin:0">
          <button class="b sm pri" id="cl-run-btn">Execute Safe Cleaning</button>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>Category</th><th>Retention Period</th><th>Eligible Files</th><th>Space</th></tr>
        </thead>
        <tbody>
          ${cats.map(c => `
            <tr>
              <td><b>${esc(c.name)}</b></td>
              <td>
                <select data-cat-ret="${c.id}" style="font-size:12px;padding:3px 8px">
                  <option value="7" ${c.retention_days === 7 ? 'selected' : ''}>7 Days</option>
                  <option value="14" ${c.retention_days === 14 ? 'selected' : ''}>14 Days</option>
                  <option value="30" ${c.retention_days === 30 ? 'selected' : ''}>30 Days</option>
                  <option value="60" ${c.retention_days === 60 ? 'selected' : ''}>60 Days</option>
                  <option value="90" ${c.retention_days === 90 ? 'selected' : ''}>90 Days</option>
                  <option value="-1" ${c.retention_days === -1 ? 'selected' : ''}>Never Delete</option>
                </select>
              </td>
              <td>${c.eligible_count} files</td>
              <td><b>${c.eligible_mb} MB</b></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>

    <!-- Quarantine & Restoration Area -->
    <div class="card" style="padding:18px">
      <div class="row" style="justify-content:space-between;margin-bottom:10px">
        <b>Managed Quarantine Area (${qItems.length} items)</b>
        ${qItems.length ? `<button class="b sm bad" id="cl-purge-all">Purge All Quarantined</button>` : ''}
      </div>
      <p class="note" style="margin:2px 0 10px">Deleted items are safely moved to quarantine first to allow 100% reversible restoration.</p>
      ${qItems.length === 0 ? `<div class="note">Quarantine is empty.</div>` : `
        <table>
          <thead>
            <tr><th>File</th><th>Category</th><th>Size</th><th>Quarantined At</th><th>Action</th></tr>
          </thead>
          <tbody>
            ${qItems.map(it => `
              <tr>
                <td><b>${esc(it.filename)}</b><div class="mono" style="font-size:10px">${esc(it.original_path)}</div></td>
                <td><span class="pill">${esc(it.category)}</span></td>
                <td>${it.size_str}</td>
                <td style="font-size:12px">${esc(it.quarantined_at)}</td>
                <td>
                  <button class="b sm ok" data-q-rest="${esc(it.quarantine_id)}">Restore</button>
                  <button class="b sm bad" data-q-purge="${esc(it.quarantine_id)}">Purge</button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `}
    </div>
  `;

  // Bind category change
  el.querySelectorAll("[data-cat-ret]").forEach(sel => {
    sel.onchange = async () => {
      const cid = sel.dataset.catRet;
      const days = parseInt(sel.value);
      const pol = { categories: {} };
      pol.categories[cid] = days;
      await api("/api/clean/policies", { policies: pol });
      toast("Retention policy updated");
    };
  });

  // Execute cleaning
  $("#cl-run-btn").onclick = async () => {
    if (!confirm("Execute safe cleaning on all policy-eligible categories? Files will be safely moved to quarantine.")) return;
    toast("Cleaning eligible items…");
    const r = await api("/api/clean/execute", { use_quarantine: true });
    toast(r.ok ? `Cleaned ${r.items_cleaned} items (${r.reclaimed_mb} MB reclaimed)` : "Cleaning failed", !r.ok);
    renderSectionCleaning(el);
  };

  // Quarantine restore & purge
  el.querySelectorAll("[data-q-rest]").forEach(b => {
    b.onclick = async () => {
      const qid = b.dataset.qRest;
      const r = await api("/api/clean/quarantine_restore", { quarantine_id: qid });
      toast(r.ok ? "Restored file" : esc(r.error), !r.ok);
      renderSectionCleaning(el);
    };
  });

  el.querySelectorAll("[data-q-purge]").forEach(b => {
    b.onclick = async () => {
      if (!confirm("Permanently delete this quarantined item? This action cannot be undone.")) return;
      const qid = b.dataset.qPurge;
      const r = await api("/api/clean/quarantine_purge", { quarantine_id: qid });
      toast(r.ok ? "Permanently purged" : esc(r.error), !r.ok);
      renderSectionCleaning(el);
    };
  });

  if ($("#cl-purge-all")) {
    $("#cl-purge-all").onclick = async () => {
      if (!confirm("Permanently purge ALL items in quarantine?")) return;
      const r = await api("/api/clean/quarantine_purge", {});
      toast(r.ok ? `Purged ${r.purged_count} items` : esc(r.error), !r.ok);
      renderSectionCleaning(el);
    };
  }
}

// ----------------------------------------------------------------------------
// Other Standard Section Renderers
// ----------------------------------------------------------------------------
async function renderSectionGeneral(el) {
  const s = S.settings || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <div class="row"><span class="lab">Application Version</span><span class="mono">${esc(S.version)}</span></div>
      <div class="row"><span class="lab">Working Project</span><b>${esc(S.project.name || "Default")}</b></div>
      <div class="row">
        <span class="lab">Appearance Theme</span>
        <span class="seg" data-seg="gen-thm">
          <button data-v="dark" class="${s.theme==='dark'?'on':''}">Dark</button>
          <button data-v="light" class="${s.theme==='light'?'on':''}">Light</button>
        </span>
      </div>
      <div class="row" style="margin-top:14px">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="gen-awake" ${s.awake ? 'checked' : ''}> Keep Mac awake while processing studies
        </label>
      </div>
    </div>
  `;
  bindSeg("gen-thm", async t => {
    await api("/api/settings", { theme: t });
    refresh();
  });
  $("#gen-awake").onchange = async e => {
    await api("/api/settings", { awake: e.target.checked });
  };
}

async function renderSectionNotifications(el) {
  el.innerHTML = `<div class="card" style="padding:18px">${typeof notifSettingsCard === "function" ? notifSettingsCard() : 'Notification Centre active.'}</div>`;
  if (typeof bindNotifSettings === "function") bindNotifSettings();
}

async function renderSectionSetup(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Installation &amp; Setup Wizard</b>
      <p class="note" style="margin:2px 0 14px">Run first-time setup or configure FreeSurfer binaries and research license.</p>
      <div class="row" style="gap:10px">
        <button class="b pri" onclick="go('setup')">Open Setup Wizard ▸</button>
        <button class="b" onclick="systemPanel(el)">Run System Preflight Check</button>
      </div>
    </div>
  `;
}

async function renderSectionSecurity(el) {
  const s = S.settings || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Application Security &amp; Isolation</b>
      <p class="note" style="margin:2px 0 14px">Control access controls, authentication prompts, and patient de-identification.</p>
      <div class="row">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="sec-app-lock" ${s.app_lock_enabled ? 'checked' : ''}>
          Enable Application Passphrase Lock on launch (DEFAULT: DISABLED)
        </label>
      </div>
      <p class="note" style="margin-top:8px">When disabled, PERCIVAL launches directly without password gates, relying on macOS account isolation and FileVault full-disk encryption.</p>
    </div>
  `;
  $("#sec-app-lock").onchange = async e => {
    await api("/api/settings", { app_lock_enabled: e.target.checked });
    toast("Security setting saved");
  };
}

async function renderSectionProcessing(el) {
  const s = S.settings || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Pathway &amp; Heuristic Heuristics</b>
      <p class="note" style="margin:2px 0 14px">Production-calibrated anatomical segmentation and registration options.</p>
      <div class="row">
        <span class="lab">SynthSeg Fallback</span>
        ${seg("proc-ap", [["1", "Switch automatically + notify"], ["0", "Ask first"]], s.auto_path === false ? "0" : "1")}
      </div>
      <div class="row" style="margin-top:10px">
        <span class="lab">T1/SWI Misalignment Retry</span>
        ${seg("proc-ar", [["1", "Retry automatically (SynthMorph)"], ["0", "Ask first"]], s.auto_retry === false ? "0" : "1")}
      </div>
    </div>
  `;
  bindSeg("proc-ap", async x => { await api("/api/settings", { auto_path: x === "1" }); });
  bindSeg("proc-ar", async x => { await api("/api/settings", { auto_retry: x === "1" }); });
}

async function renderSectionHardware(el) {
  const s = S.settings || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>CPU &amp; Memory Allocation</b>
      <div class="row" style="margin-top:10px">
        <span class="lab">Processing CPU Threads</span>
        <input type="number" id="hw-threads" min="1" max="16" value="${s.threads || 4}" style="width:80px">
        <span class="note">Recommended: 4 threads for high-performance SynthSeg / recon-all</span>
      </div>
      <div class="row" style="margin-top:10px">
        <span class="lab">Parallel Study Processing</span>
        <input type="number" id="hw-parallel" min="1" max="4" value="${s.parallel || 1}" style="width:80px">
        <span class="note">Number of studies processing concurrently</span>
      </div>
    </div>
  `;
  $("#hw-threads").onchange = async e => { await api("/api/settings", { threads: +e.target.value }); };
  $("#hw-parallel").onchange = async e => { await api("/api/settings", { parallel: +e.target.value }); };
}

async function renderSectionScratch(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Scratch &amp; Temporary Working Buffers</b>
      <p class="note">Scratch space on fast Mac SSD used during slice extraction and deformation tensor computation.</p>
      <div class="row">
        <button class="b sm" onclick="api('/api/storage/clean_staging',{})">Clean Orphan Staging Buffers</button>
      </div>
    </div>
  `;
}

async function renderSectionPipeline(el) {
  const s = S.settings || {};
  const F = s.features || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Pipeline Scientific Verification Guards</b>
      <div class="row" style="margin-top:8px"><label><input type="checkbox" data-pf="duplicate_check" ${F.duplicate_check?'checked':''}> Check for duplicate examination series</label></div>
      <div class="row"><label><input type="checkbox" data-pf="preflight" ${F.preflight?'checked':''}> Run pre-flight integrity check before processing</label></div>
      <div class="row"><label><input type="checkbox" data-pf="qc_snapshot" ${F.qc_snapshot?'checked':''}> Generate QC slice snapshot per study</label></div>
      <div class="row"><label><input type="checkbox" data-pf="version_stamp" ${F.version_stamp?'checked':''}> Embed cryptographic version stamp on outputs</label></div>
    </div>
  `;
  el.querySelectorAll("[data-pf]").forEach(chk => {
    chk.onchange = async () => {
      F[chk.dataset.pf] = chk.checked;
      await api("/api/settings", { features: F });
    };
  });
}

async function renderSectionArchive(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Archiving &amp; Research Preservation</b>
      <p class="note">Archived studies are kept safe in cold storage and remain accessible for machine learning datasets.</p>
    </div>
  `;
}

async function renderSectionBackup(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Pensieve Memory Backup &amp; Integrity</b>
      <p class="note">Creates atomic SQLite snapshots of pensieve_core.db and audit ledgers.</p>
      <div class="row">
        <button class="b sm pri" id="sb-create">Create Instant Pensieve Backup</button>
      </div>
    </div>
  `;
  $("#sb-create").onclick = async () => {
    toast("Creating backup…");
    const r = await api("/api/percival/vault_backup", { destination: S.project.path + "/app_data/pensieve_snapshots" });
    toast(r.ok ? "Backup complete" : esc(r.message), !r.ok);
  };
}

async function renderSectionPensieve(el) {
  const p = await api("/api/percival/pensieve");
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Pensieve Core Memory (Unified SQLite Memory)</b>
      <div class="kv" style="margin-top:10px">
        <div>Database Status</div><div><span class="pill ok">${esc(p.status || "Operational")}</span></div>
        <div>Total Known Candidates</div><div><b>${p.total_candidates || 0}</b></div>
        <div>Expert Confirmed Decisions</div><div><b>${p.expert_confirmed || 0}</b></div>
        <div>Recorded Missed Lesions</div><div><b>${p.missed_lesions_count || 0}</b></div>
      </div>
    </div>
  `;
}

async function renderSectionTraining(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Training &amp; Dataset Management</b>
      <p class="note">Direct route to the 14-section modular Training Centre in Percival Intelligence.</p>
      <button class="b pri" onclick="go('intel')">Open Training Centre ▸</button>
    </div>
  `;
}

async function renderSectionModels(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Models &amp; Calibrated Weights</b>
      <p class="note">Inspect neural network architectures for ALBUS, LUMOS, NOX, and PERCIVAL CORE.</p>
    </div>
  `;
}

async function renderSectionAdvanced(el) {
  const s = S.settings || {};
  const F = s.features || {};
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Advanced Research Prototypes</b>
      <div class="row">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="adv-proto" ${F.show_prototypes ? 'checked' : ''}>
          Show older research prototypes in navigation (Training, Unified Score, Shadow ML, Image ML)
        </label>
      </div>
    </div>
  `;
  $("#adv-proto").onchange = async e => {
    F.show_prototypes = e.target.checked;
    await api("/api/settings", { features: F });
    refresh();
  };
}

async function renderSectionRecovery(el) {
  const rc = await api("/api/recovery/summary");
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Job Recovery Centre</b>
      <div class="kv" style="margin-top:10px">
        <div>Active Transactional Jobs</div><div><b>${rc.active_jobs || 0}</b></div>
        <div>Completed Jobs</div><div><b>${rc.completed_jobs || 0}</b></div>
        <div>Resumable Interrupted Runs</div><div><b>${rc.resumable_jobs_count || 0}</b></div>
      </div>
    </div>
  `;
}

async function renderSectionHealth(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Startup Health &amp; Diagnostics Engine</b>
      <p class="note">Runs the full 19-point diagnostic checklist across environment, volumes, Pensieve, and permissions.</p>
      <button class="b pri" id="sh-run">Run Full Diagnostics Check</button>
      <div id="sh-results" style="margin-top:14px"></div>
    </div>
  `;
  $("#sh-run").onclick = async () => {
    $("#sh-results").innerHTML = `<div class="note">Running diagnostics…</div>`;
    const r = await api("/api/health");
    $("#sh-results").innerHTML = `
      <div class="banner ${r.status==='HEALTHY'?'':'w'}">
        <b>Status: ${esc(r.status)}</b> · Passed ${r.passed}/${r.total_checks} checks · Repairs applied: ${r.repairs_applied.length}
      </div>
    `;
  };
}

async function renderSectionActivity(el) {
  el.innerHTML = `
    <div class="card" style="padding:18px">
      <b>Activity &amp; Operation History</b>
      <p class="note">Audit logs and transactional history records.</p>
      <button class="b" onclick="go('act')">Open Pipeline Activity Monitor ▸</button>
    </div>
  `;
}
