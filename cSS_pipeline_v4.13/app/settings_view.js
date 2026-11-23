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
  // Group 1: General
  { id: "a_general", group: "1. General", title: "General & Appearance", desc: "Display themes, system awake locks, and project identity.", keywords: "theme dark light awake keepawake name project" },
  { id: "a_notif", group: "1. General", title: "Notifications & Alerts", desc: "Alert banners, notification curtain, and audible system alerts.", keywords: "notifications alerts sound banners finished failed" },
  { id: "a_security", group: "1. General", title: "Security & Permissions", desc: "Application passphrase lock, patient name protection, and identity vault.", keywords: "security lock password passphrase filevault privacy incognito permissions" },

  // Group 2: System Resources
  { id: "b_hardware", group: "2. System Resources", title: "CPU, GPU & Memory", desc: "Concurrency, multi-threading allocation, and RAM pressure zones.", keywords: "threads cpu memory ram parallel gpu concurrency" },
  { id: "b_processing", group: "2. System Resources", title: "Processing Configuration", desc: "Pathway fallback logic, automatic retry heuristics, and re-run rules.", keywords: "pathway synthseg synthmorph recon-all retry auto_path rerun" },
  { id: "b_scratch", group: "2. System Resources", title: "Scratch & Temporary Storage", desc: "Intermediate resampling buffer paths, quotas, and fast cleanup.", keywords: "scratch temp temporary buffer quota" },
  { id: "e_health", group: "2. System Resources", title: "Startup Health & Diagnostics", desc: "19-point diagnostic engine, degraded mode telemetry, and self-repair.", keywords: "health diagnostics 19-point check degraded repair" },

  // Group 3: Pipeline Configuration
  { id: "a_setup", group: "3. Pipeline Configuration", title: "Installation & Setup Center", desc: "Targeted discovery, Python 3.11, FreeSurfer 8.2, licenses, and readiness matrix.", keywords: "setup wizard freesurfer licence installation preflight discovery validation" },
  { id: "b_pipeline", group: "3. Pipeline Configuration", title: "Pipeline & Reviewer Settings", desc: "Quality indicators, duplicate checks, and radiologist review viewer settings.", keywords: "pipeline features duplicate qc_snapshot preflight reviewer" },
  { id: "d_models", group: "3. Pipeline Configuration", title: "Neural Models & Checkpoints", desc: "Active and historical neural network weights, calibrations, and checkpoints.", keywords: "models checkpoints weights calibration albus lumos nox percival" },
  { id: "d_advanced", group: "3. Pipeline Configuration", title: "Advanced Prototypes", desc: "Shadow ML laboratory, unified scoring prototypes, and experimental flags.", keywords: "shadow_ml research experimental prototypes unified_score" },

  // Group 4: Storage & Data Management
  { id: "c_overview", group: "4. Storage & Data Management", title: "Storage Overview", desc: "Authoritative capacity metrics distinguishing volume, archive, workspace, and Pensieve.", keywords: "storage overview bars capacity disk mac hdd free space usage gb tb" },
  { id: "c_filemanager", group: "4. Storage & Data Management", title: "File Manager Workspace", desc: "Three-part research-data workspace, categories, operations, and details inspector.", keywords: "file manager files browse copy move rename delete archive restore verify sha256" },
  { id: "c_vault", group: "4. Storage & Data Management", title: "PERCIVAL Data Vault", desc: "External permanent research archive, stable volume UUID, and Finder integration.", keywords: "vault data_vault external drive hdd finder uuid manifest verify connect" },
  { id: "c_locations", group: "4. Storage & Data Management", title: "Storage Locations & Paths", desc: "Independent folder destinations for all 10 managed scientific data categories.", keywords: "locations destinations paths working_dir scratch originals subjects albus exports" },
  { id: "c_transfer", group: "4. Storage & Data Management", title: "Transfer Center & Migration", desc: "Active transfers, queue order, searchable history, and crash recovery.", keywords: "transfer migration queue free_space mac move copy auto archive policies" },
  { id: "c_cleaning", group: "4. Storage & Data Management", title: "Retention & Cleanup", desc: "Lifecycle retention by days, quarantine inspection, and safe eligible cleaning.", keywords: "clean cleaning retention days purge quarantine restore delete prune history" },
  { id: "c_archive", group: "4. Storage & Data Management", title: "Archiving & Verification", desc: "Cold storage retention schedules and SHA-256 preservation safeguards.", keywords: "archive retention permanent policy schedule" },
  { id: "c_backup", group: "4. Storage & Data Management", title: "Backup & Durability", desc: "Zero-corruption Pensieve database snapshots and journal integrity.", keywords: "backup pensieve snapshot restore database integrity" },

  // Group 5: Research & Scientific Data
  { id: "d_pensieve", group: "5. Research & Scientific Data", title: "Pensieve Core Memory", desc: "SQLite transactional database, candidate identities, and missed lesion ledger.", keywords: "pensieve memory sqlite candidates missed_lesions journal provenance" },
  { id: "d_training", group: "5. Research & Scientific Data", title: "Training Datasets", desc: "Supervised label datasets, patient-grouped splits, and leakage prevention.", keywords: "training datasets splits leakage cross-validation manifest" },
  { id: "e_activity", group: "5. Research & Scientific Data", title: "Activity & Provenance Audit", desc: "Audit logs, migration journals, and data lifecycle transaction records.", keywords: "activity history audit log journal operations" },
  { id: "e_recovery", group: "5. Research & Scientific Data", title: "Recovery Center", desc: "Crash recovery, interrupted run resumption, and transactional job logs.", keywords: "recovery resume crash interrupted jobs transactions" }
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
          <input id="set-search-input" value="${esc(SV.searchQuery)}" placeholder="🔍 Search System Control Centre…" style="width:100%;font-size:13px;padding:8px 10px">
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
        <div class="note" style="font-size:12px;margin-bottom:2px">Settings › ${esc(secMeta.group)} › ${esc(secMeta.title)}</div>
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
  const dm = data.detailed_metrics || {};

  const macClass = mac.tier === "EMERGENCY" ? "bad" : mac.tier === "CRITICAL" ? "warn" : "ok";
  const vaultClass = v.connected ? (v.tier === "EMERGENCY" ? "bad" : v.tier === "CRITICAL" ? "warn" : "ok") : "bad";

  el.innerHTML = `
    <!-- Top Action Toolbar -->
    <div class="row" style="justify-content:space-between;margin-bottom:14px">
      <span class="note">Last measured: <b>${esc(data.updated_at || "Just now")}</b></span>
      <div class="row" style="gap:8px;margin:0">
        <button class="b sm" id="so-refresh">↻ Refresh Storage Capacity</button>
        <button class="b sm" id="so-diagnostics">Run Storage Diagnostics…</button>
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
        <div>Active Working Space: <b>${dm.mac_internal ? `${dm.mac_internal.active_workspace_gb} GB` : `${bd.active_workspace_mb || 0} MB`}</b></div>
        <div>Temporary Scratch: <b>${dm.mac_internal ? `${dm.mac_internal.temporary_scratch_mb} MB` : `${bd.scratch_mb || 0} MB`}</b></div>
        <div>Pensieve Database: <b>${dm.mac_internal ? `${dm.mac_internal.pensieve_database_mb} MB` : 'Active'}</b></div>
        <div>Preserved Raw MRI: <b>${dm.mac_internal ? `${round((dm.mac_internal.preserved_raw_bytes || 0) / (1024*1024), 1)} MB` : `${bd.original_mri_mb || 0} MB`}</b></div>
        <div>Quarantined Files: <b>${dm.mac_internal ? `${round((dm.mac_internal.quarantined_bytes || 0) / (1024*1024), 1)} MB` : `${bd.quarantine_mb || 0} MB`}</b></div>
        <div>PERCIVAL Managed Total: <b>${dm.mac_internal ? `${dm.mac_internal.percival_managed_gb} GB` : `${mac.percival_managed_gb || 0} GB`}</b></div>
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
        <div>PERCIVAL Vault Managed: <b>${dm.external_vault && dm.external_vault.connected ? `${dm.external_vault.percival_managed_gb} GB` : `${v.vault_usage_gb || 0} GB`}</b></div>
        <div>Original MRI Archive: <b>${dm.external_vault && dm.external_vault.connected ? `${dm.external_vault.original_mri_archive_gb} GB` : '—'}</b></div>
        <div>Verified Study Archive: <b>${dm.external_vault && dm.external_vault.connected ? `${dm.external_vault.verified_archive_gb} GB` : '—'}</b></div>
        <div>Pensieve Versioned Backups: <b>${dm.external_vault && dm.external_vault.connected ? `${dm.external_vault.pensieve_backup_mb} MB` : '—'}</b></div>
        <div>Unregistered Data on Volume: <b>${dm.external_vault && dm.external_vault.connected ? `${dm.external_vault.unregistered_gb} GB` : '—'}</b></div>
        <div>Hardware UUID: <span class="mono">${esc((v.volume_uuid || "—").slice(0, 16))}</span></div>
      </div>

      <div class="row" style="margin-top:14px;gap:8px;flex-wrap:wrap">
        ${v.connected ? `<button class="b sm" id="so-open-finder">Reveal Vault in Finder</button>` : ''}
        <button class="b sm" id="so-reconnect">Detect / Connect Drive…</button>
        <button class="b sm pri" onclick="nav('sync')">Open Sync Center ▸</button>
        <button class="b sm" onclick="nav('transfer')">Open Transfer Center ▸</button>
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

  $("#so-diagnostics").onclick = async () => {
    const btn = $("#so-diagnostics");
    btn.disabled = true;
    btn.textContent = "Running Diagnostics…";
    try {
      const res = await api("/api/storage/diagnostics");
      const tests = res.tests || [];
      const passCount = tests.filter(t => t.status === "PASS").length;
      const warnCount = tests.filter(t => t.status === "WARNING").length;
      const failCount = tests.filter(t => t.status === "FAIL").length;
      
      const badge = failCount > 0 ? "bad" : (warnCount > 0 ? "warn" : "ok");
      const summaryText = `${passCount} PASS · ${warnCount} WARNING · ${failCount} FAIL`;

      $("#dlg").innerHTML = `
        <h2>Storage &amp; Data Integrity Diagnostics</h2>
        <div class="row" style="margin-bottom:12px">
          <span class="pill ${badge}" style="font-weight:700">${summaryText}</span>
        </div>
        <div style="max-height:60vh;overflow-y:auto;border:1px solid var(--bd);border-radius:6px">
          <table style="width:100%;font-size:12.5px;border-collapse:collapse">
            <thead>
              <tr style="background:var(--panel2);text-align:left">
                <th style="padding:8px">Test</th>
                <th style="padding:8px">Status</th>
                <th style="padding:8px">Details</th>
                <th style="padding:8px">Recommended Action</th>
              </tr>
            </thead>
            <tbody>
              ${tests.map(t => `
                <tr style="border-top:1px solid var(--bd)">
                  <td style="padding:7px 8px"><b>${esc(t.name)}</b></td>
                  <td style="padding:7px 8px"><span class="pill ${t.status === 'PASS' ? 'ok' : (t.status === 'WARNING' ? 'warn' : 'bad')}">${esc(t.status)}</span></td>
                  <td style="padding:7px 8px;color:var(--txt)">${esc(t.details)}</td>
                  <td style="padding:7px 8px;color:var(--mut)">${esc(t.action)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
        <div class="acts" style="display:flex;justify-content:flex-end;margin-top:14px">
          <button class="b pri" id="diag-close">Close</button>
        </div>
      `;
      $("#shade").style.display = "flex";
      $("#diag-close").onclick = () => { $("#shade").style.display = "none"; };
    } catch (e) {
      toast(`Diagnostics failed: ${e.message}`, 1);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Storage Diagnostics…";
    }
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
        <button class="b sm" id="sv-eject-btn" ${!status.connected ? "disabled" : ""}>Safely Eject Drive ⏏</button>
        <button class="b sm bad" id="sv-emergency-eject-btn" ${!status.connected ? "disabled" : ""}>Emergency Interruption &amp; Eject</button>
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
  $("#sv-eject-btn") && ($("#sv-eject-btn").onclick = async () => {
    if (!confirm("Safely eject and unmount external Data Vault drive?")) return;
    toast("Unmounting external drive…");
    const r = await api("/api/storage/eject", { emergency: false });
    toast(r.ok ? r.message : r.error, !r.ok);
    renderSectionVault(el);
  });
  $("#sv-emergency-eject-btn") && ($("#sv-emergency-eject-btn").onclick = async () => {
    if (!confirm("EMERGENCY UNMOUNT WARNING:\nThis will safely interrupt active PERCIVAL operations, commit the recovery journal, and request unmount.\n\nProceed?")) return;
    toast("Interrupting operations and unmounting…");
    const r = await api("/api/storage/eject", { emergency: true });
    toast(r.ok ? r.message : r.error, !r.ok);
    renderSectionVault(el);
  });
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
  const [qRes, polRes, previewRes, jobsRes] = await Promise.all([
    api("/api/transfer/queue"),
    api("/api/transfer/policies"),
    api("/api/storage/free_space_preview"),
    api("/api/storage/jobs?limit=15")
  ]);

  const queue = qRes.queue || [];
  const policies = polRes.policies || {};
  const prev = previewRes || {};
  const journalJobs = (jobsRes && jobsRes.jobs) ? jobsRes.jobs : [];

  el.innerHTML = `
    <!-- Top Sync Center Control Header -->
    <div class="card" style="padding:18px;background:var(--panel2);border:1px solid var(--acc);margin-bottom:18px">
      <div class="row" style="justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <b style="font-size:16px">Sync &amp; Transfer Operational Centre</b>
          <p class="note" style="margin:2px 0 0">Synchronize study workspaces between Mac SSD and External Data Vault with SHA-256 integrity.</p>
        </div>
        <div style="display:flex;gap:8px">
          <button class="b pri" id="st-sync-preview-btn">🔍 Preview Sync with Vault</button>
          <button class="b" id="st-proc-btn">Process Next Transfer</button>
        </div>
      </div>
      <div id="st-sync-preview-box" style="display:none;margin-top:14px;padding:12px;background:var(--panel);border-radius:6px;border:1px solid var(--line)"></div>
    </div>

    <!-- Active & Recent Transfers from Authoritative Journal -->
    <div class="card" style="padding:18px;margin-bottom:18px">
      <div class="row" style="justify-content:space-between;margin-bottom:10px">
        <b>Transfer Activity &amp; Journal History (${journalJobs.length} records)</b>
        <span class="note">Backed by transactional SQLite journal on SSD</span>
      </div>
      ${journalJobs.length === 0 ? `<div class="note">No transfers recorded in active journal.</div>` : `
        <table>
          <thead>
            <tr><th>Job ID</th><th>Study</th><th>Op</th><th>Files</th><th>Progress</th><th>Rate</th><th>Status</th></tr>
          </thead>
          <tbody>
            ${journalJobs.map(j => {
              const pct = j.total_bytes > 0 ? Math.round((j.completed_bytes / j.total_bytes) * 100) : 0;
              return `
              <tr>
                <td class="mono" style="font-size:11px">${esc(j.job_id)}</td>
                <td><b>${esc(j.study_id)}</b></td>
                <td>${esc(j.operation)}</td>
                <td>${j.completed_files}/${j.total_files}</td>
                <td>
                  <div style="display:flex;align-items:center;gap:6px">
                    <div class="bar" style="width:70px;height:6px"><i style="width:${pct}%;background:var(--acc)"></i></div>
                    <span style="font-size:11px">${pct}%</span>
                  </div>
                </td>
                <td style="font-size:11px">${j.current_mb_s ? `${j.current_mb_s.toFixed(1)} MB/s` : (j.avg_mb_s ? `${j.avg_mb_s.toFixed(1)} avg` : '—')}</td>
                <td><span class="pill ${j.status==='completed'?'ok':j.status==='failed'?'bad':j.status==='running'?'pri':'warn'}">${esc(j.status)}</span></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      `}
    </div>

    <!-- Free Up Mac Space Card -->
    <div class="card" style="padding:18px;margin-bottom:18px">
      <div class="row" style="justify-content:space-between;align-items:center">
        <div>
          <b>Free Up Mac Space (Eligible Temporary Cleanups)</b>
          <p class="note" style="margin:2px 0 0">Reclaim local storage by cleaning verified temporary data and staged caches.</p>
        </div>
        <button class="b" id="st-free-btn" ${prev.total_reclaimable_mb > 0 ? '' : 'disabled'}>
          Reclaim ${prev.total_reclaimable_gb || 0} GB
        </button>
      </div>
      <div class="note" style="margin-top:8px">
        Audit identified <b>${(prev.items || []).length} items</b> (${prev.total_reclaimable_mb || 0} MB) eligible for immediate safe reclamation.
      </div>
    </div>

    <!-- Archival Policies -->
    <div class="card" style="padding:18px">
      <b>Category Archival Policies</b>
      <p class="note" style="margin:2px 0 12px">Automatic background migration rules when studies finish processing.</p>
      <div class="row">
        <label style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="st-rem-orig" ${policies.remove_local_original_after_verify ? 'checked' : ''}>
          Remove local original MRI after verified SHA-256 archive (DEFAULT: OFF)
        </label>
      </div>
    </div>
  `;

  // Sync Preview handler
  $("#st-sync-preview-btn").onclick = async () => {
    const box = $("#st-sync-preview-box");
    box.style.display = "block";
    box.innerHTML = `<span class="mut">Scanning study workspaces and comparing with Vault…</span>`;
    try {
      const prevRes = await api("/api/storage/sync_preview?mode=manual");
      if (!prevRes.can_proceed && prevRes.destination_available_gb === 0) {
        box.innerHTML = `<div class="bad"><b>Cannot sync:</b> ${esc(prevRes.message)}</div>`;
        return;
      }
      box.innerHTML = `
        <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:8px">
          <b>Sync Preview: ${prevRes.to_copy_count} files to archive (${prevRes.total_mb} MB)</b>
          <button class="b pri sm" id="st-sync-exec-btn" ${prevRes.to_copy_count > 0 ? '' : 'disabled'}>Execute Synchronisation ▶</button>
        </div>
        <div style="font-size:12px;margin-bottom:6px">
          • <b>Files to copy:</b> ${prevRes.to_copy_count} | • <b>Identical (skipped):</b> ${prevRes.skipped_count} | • <b>Conflicts:</b> ${prevRes.conflict_count}
        </div>
        ${prevRes.conflict_count > 0 ? `<div class="warn" style="font-size:12px;margin-top:4px">⚠ Conflicts detected! Both copies exist with different sizes. Manual resolution required.</div>` : ''}
      `;
      if ($("#st-sync-exec-btn")) {
        $("#st-sync-exec-btn").onclick = async () => {
          toast("Executing synchronisation…");
          const r = await api("/api/storage/sync_execute", { preview: prevRes });
          toast(r.ok ? r.message : r.error, !r.ok);
          renderSectionTransfer(el);
        };
      }
    } catch (e) {
      box.innerHTML = `<div class="bad">Sync preview error: ${esc(e.message)}</div>`;
    }
  };

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
  el.innerHTML = `<div style="text-align:center;padding:30px;color:var(--mut)"><div class="spin" style="margin:0 auto 12px;width:24px;height:24px;border:2px solid var(--bd);border-top-color:var(--pri);border-radius:50%"></div>Loading System Configuration Center…</div>`;

  try {
    const [lifeRes, discRes, readRes] = await Promise.all([
      api("/api/setup/lifecycle"),
      api("/api/setup/discovery"),
      api("/api/setup/readiness")
    ]);

    const life = lifeRes || {};
    const disc = discRes.discovery || {};
    const read = readRes.readiness || {};
    const deps = readRes.dependencies || [];
    const cfg = life.validated_config || {};
    const sys = disc.system || {};

    el.innerHTML = `
    <!-- Top Action Bar -->
    <div class="card" style="padding:16px 20px;margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <h2 style="font-size:17px;margin:0 0 4px">Permanent System Configuration Center</h2>
          <span class="note">Modify individual paths, swap Python runtimes, revalidate tools, or re-run Guided Setup without losing study data.</span>
        </div>
        <div style="display:flex;gap:8px">
          <button class="b" onclick="sysConfigRescan()" style="font-size:12px">⟳ Re-scan System</button>
          <button class="b" onclick="sysConfigRevert()" style="font-size:12px">↺ Revert Changes</button>
          <button class="b" onclick="exportDiagnostics()" style="font-size:12px">Export Report</button>
          <button class="b pri" onclick="go('setup')" style="font-size:12px">Guided Setup Wizard ▸</button>
        </div>
      </div>
    </div>

    <!-- 1. System Overview & Host Hardware -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <h3 style="font-size:15px;margin:0">1. System Overview &amp; Host Hardware</h3>
        <span class="pill ok">${esc(sys.os_name || "macOS")} ${esc(sys.os_version || "")} (${esc(sys.architecture || "arm64")})</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;font-size:12px">
        <div style="background:var(--panel2);padding:8px 10px;border-radius:6px;border:1px solid var(--bd)">
          <div class="mut">Processor / Architecture</div>
          <div style="font-weight:600;margin-top:2px">${esc(sys.cpu_brand || "Apple Silicon")}</div>
        </div>
        <div style="background:var(--panel2);padding:8px 10px;border-radius:6px;border:1px solid var(--bd)">
          <div class="mut">Total System Memory</div>
          <div style="font-weight:600;margin-top:2px">${sys.total_ram_gb || 16} GB RAM</div>
        </div>
        <div style="background:var(--panel2);padding:8px 10px;border-radius:6px;border:1px solid var(--bd)">
          <div class="mut">Internal SSD Headroom</div>
          <div style="font-weight:600;margin-top:2px">${sys.free_ssd_gb || 0} GB Free</div>
        </div>
        <div style="background:var(--panel2);padding:8px 10px;border-radius:6px;border:1px solid var(--bd)">
          <div class="mut">Setup State</div>
          <div style="font-weight:600;margin-top:2px">${esc(life.state || "SETUP_COMPLETED")}</div>
        </div>
      </div>
    </div>

    <!-- 2. Python Environment -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <h3 style="font-size:15px;margin:0">2. Python Scientific Runtime (3.10+)</h3>
        <span class="pill ${cfg.python_valid !== false ? 'ok' : 'bad'}">${cfg.python_version ? `Python ${esc(cfg.python_version)}` : 'ACTIVE'}</span>
      </div>
      <p class="note" style="margin:0 0 10px">Required: numpy, scipy, nibabel, pandas, skimage, matplotlib, pydicom, openpyxl, cryptography</p>
      <div class="row">
        <span class="lab">Executable Path</span>
        <input class="wide mono" id="sc-py-path" value="${esc(cfg.python_executable || "")}" placeholder="/Users/.../miniforge3/envs/css/bin/python3">
        <button class="b" onclick="sysConfigValidateComponent('python', $('#sc-py-path').value)">Validate</button>
        <button class="b pri" onclick="sysConfigSaveComponent({python_executable:$('#sc-py-path').value})">Save</button>
      </div>
      <div id="sc-val-python" class="note" style="margin-top:4px"></div>
    </div>

    <!-- 3. Pipeline Installation & Version Rollback -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <h3 style="font-size:15px;margin:0">3. PERCIVAL Pipeline Algorithms</h3>
        <span class="pill ok">${esc(cfg.pipeline_version || "v5.26-dev")}</span>
      </div>
      <p class="note" style="margin:0 0 10px">Entry points: run_css.sh, detect_css.py, align_seg.py, score_css.py</p>
      <div class="row">
        <span class="lab">Pipeline Root</span>
        <input class="wide mono" id="sc-pipe-path" value="${esc(cfg.pipeline_dir || "")}" placeholder="/Users/.../cSS_pipeline_v4.13">
        <button class="b" onclick="sysConfigValidateComponent('pipeline', $('#sc-pipe-path').value)">Validate</button>
        <button class="b pri" onclick="sysConfigSaveComponent({pipeline_dir:$('#sc-pipe-path').value})">Save</button>
      </div>
      <div id="sc-val-pipeline" class="note" style="margin-top:4px"></div>
    </div>

    <!-- 4. FreeSurfer Suite & License -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <h3 style="font-size:15px;margin:0">4. FreeSurfer Suite &amp; License</h3>
        <span class="pill ${cfg.freesurfer_valid ? 'ok' : 'warn'}">${cfg.freesurfer_valid ? 'VALIDATED' : 'CHECK REQUIRED'}</span>
      </div>
      <p class="note" style="margin:0 0 10px">Provides automated cortical segmentation (mri_synthseg) and spatial co-registration</p>
      <div class="row">
        <span class="lab">FREESURFER_HOME</span>
        <input class="wide mono" id="sc-fs-path" value="${esc(cfg.freesurfer_home || S.settings.freesurfer_home || "")}" placeholder="/Applications/freesurfer/8.2.0">
        <button class="b" onclick="sysConfigValidateComponent('freesurfer', $('#sc-fs-path').value)">Validate</button>
      </div>
      <div class="row" style="margin-top:8px">
        <span class="lab">License Path</span>
        <input class="wide mono" id="sc-lic-path" value="${esc(cfg.fs_license || S.settings.fs_license || "")}" placeholder="/Users/.../Downloads/license.txt">
        <button class="b" onclick="sysConfigValidateComponent('license', $('#sc-lic-path').value)">Validate</button>
        <button class="b pri" onclick="sysConfigSaveComponent({home:$('#sc-fs-path').value,license:$('#sc-lic-path').value})">Save Pair</button>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="b" onclick="sysConfigTestFreeSurfer($('#sc-fs-path').value, $('#sc-lic-path').value)">Test Execution (mri_convert --version)</button>
      </div>
      <div id="sc-val-freesurfer" class="note" style="margin-top:4px"></div>
    </div>

    <!-- 5. MRI Processing Tools -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <h3 style="font-size:15px;margin:0">5. MRI Conversion Tools (dcm2niix)</h3>
        <span class="pill ok">INSTALLED</span>
      </div>
      <div class="row">
        <span class="lab">dcm2niix Path</span>
        <input class="wide mono" id="sc-dcm-path" value="${esc(cfg.dcm2niix_path || "/opt/homebrew/bin/dcm2niix")}">
        <button class="b" onclick="sysConfigValidateComponent('mri_tool', $('#sc-dcm-path').value, {tool_name:'dcm2niix'})">Validate</button>
      </div>
      <div id="sc-val-dcm2niix" class="note" style="margin-top:4px"></div>
    </div>

    <!-- 6. Storage Topology & Vault Integration -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <h3 style="font-size:15px;margin:0">6. Dual-Tier Storage Architecture</h3>
        <span class="pill ok">HYBRID NVME + USB VAULT</span>
      </div>
      <div class="row">
        <span class="lab">SSD Workspace</span>
        <input class="wide mono" id="sc-ws-path" value="${esc(cfg.workspace_dir || "~/Percival_project")}">
        <button class="b" onclick="sysConfigValidateComponent('workspace', $('#sc-ws-path').value)">Validate</button>
        <button class="b pri" onclick="sysConfigSaveComponent({workspace_dir:$('#sc-ws-path').value})">Save</button>
      </div>
      <div class="row" style="margin-top:8px">
        <span class="lab">External Vault Root</span>
        <input class="wide mono" id="sc-vault-path" value="${esc(cfg.vault_mount || "/Volumes/Percival/PERCIVAL_VAULT")}">
        <button class="b" onclick="sysConfigValidateComponent('vault', $('#sc-vault-path').value)">Validate</button>
        <button class="b pri" onclick="sysConfigSaveComponent({vault_mount:$('#sc-vault-path').value})">Save</button>
      </div>
      <div id="sc-val-vault" class="note" style="margin-top:4px"></div>
    </div>

    <!-- 7. Analysis & Calling Policy -->
    <div class="card" style="margin-bottom:16px">
      <h3 style="font-size:15px;margin:0 0 8px">7. Scientific Analysis &amp; Calling Policy</h3>
      <div class="row" style="margin-bottom:6px">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="sc-opt-redetect" ${cfg.candidate_redetection !== false ? 'checked' : ''}>
          <span><b>Candidate Re-Detection:</b> Always re-extract candidate fingerprints from raw MRI</span>
        </label>
      </div>
      <div class="row">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="sc-opt-calling" ${cfg.candidate_calling !== false ? 'checked' : ''}>
          <span><b>Spatial Fingerprint Calling:</b> Automated matching against historical Pensieve calls</span>
        </label>
      </div>
      <div style="margin-top:10px">
        <button class="b pri" onclick="sysConfigSaveComponent({candidate_redetection:$('#sc-opt-redetect').checked, candidate_calling:$('#sc-opt-calling').checked})">Save Calling Policy</button>
      </div>
    </div>

    <!-- 8. System Dependency Graph -->
    <div class="card" style="margin-bottom:16px">
      <h3 style="font-size:15px;margin:0 0 10px">8. System Component Dependency Map</h3>
      <p class="note" style="margin-bottom:12px">Visual graph of component prerequisites. Modifying one component triggers targeted revalidation of its dependents.</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:10px">
        ${deps.map(n => `
        <div style="background:var(--panel2);border:1px solid var(--bd);border-radius:6px;padding:10px">
          <div style="font-weight:600;font-size:13px;color:var(--txt)">${esc(n.label)}</div>
          <div class="mut" style="font-size:11px;margin-top:4px">Depends on: ${n.depends_on.length ? n.depends_on.map(d=>`<code>${esc(d)}</code>`).join(", ") : '<em>none (root)</em>'}</div>
          <div class="mut" style="font-size:11px;margin-top:2px">Dependents: ${n.dependents.length ? n.dependents.map(d=>`<code>${esc(d)}</code>`).join(", ") : '<em>leaf</em>'}</div>
        </div>
        `).join("")}
      </div>
    </div>
    `;
  } catch (err) {
    el.innerHTML = `<div class="card bad"><h3>Failed to load System Configuration Center</h3><p>${esc(err.message || String(err))}</p></div>`;
  }
}

async function sysConfigValidateComponent(comp, p, extra) {
  const statusEl = $(`#sc-val-${comp}`);
  if (statusEl) statusEl.innerHTML = `<span class="mut">Validating ${esc(comp)}…</span>`;
  try {
    const payload = Object.assign({ component: comp, path: p }, extra || {});
    const r = await api("/api/setup/validate_component", payload);
    if (r.ok) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--ok)">✓ Validated successfully: ${esc(r.version || r.free_gb ? `${r.free_gb} GB free` : 'Ready')}</span>`;
      toast(`${comp} validated successfully.`);
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--bad)">✗ Validation failed: ${esc(r.error || "Invalid path")}</span>`;
      toast(`Validation failed: ${r.error}`, true);
    }
  } catch (err) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--bad)">✗ Error: ${esc(err.message)}</span>`;
  }
}

async function sysConfigSaveComponent(payload) {
  toast("Saving configuration component…");
  const r = await api("/api/setup/save_config", payload);
  if (r.ok) {
    toast("Configuration component updated and committed.");
    if (typeof refresh === "function") refresh();
    const host = $("#section-inner-host");
    if (host) renderSectionSetup(host);
  } else {
    toast(`Failed to save: ${r.error}`, true);
  }
}

async function sysConfigTestFreeSurfer(home, lic) {
  toast("Testing FreeSurfer execution (mri_convert --version)…");
  const r = await api("/api/setup/test", { home, license: lic });
  if (r.ok) {
    alert(`FreeSurfer Execution Succeeded!\n\nVersion banner:\n${r.version_line}`);
  } else {
    alert(`FreeSurfer Execution Failed:\n${r.error}`);
  }
}

async function sysConfigRescan() {
  toast("Re-scanning host system and connected volumes…");
  await api("/api/setup/rescan", {});
  toast("Re-scan complete.");
  const host = $("#section-inner-host");
  if (host) renderSectionSetup(host);
}

async function sysConfigRevert() {
  if (!confirm("Revert to the previous working configuration?")) return;
  const r = await api("/api/setup/revert", {});
  if (r.ok) {
    toast(r.message || "Reverted to previous working configuration.");
    const host = $("#section-inner-host");
    if (host) renderSectionSetup(host);
  } else {
    toast(r.error || "Reversion failed.", true);
  }
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
