// file_manager_view.js - Complete Three-Part Research-Data Workspace for PERCIVAL.
// Left: Storage Navigation (Mac SSD, External Vault, Study Workspaces, Categories, Recovery)
// Center: File and Study Browser (Study Workspaces Ledger & Directory Files Browser)
// Right: Collapsible Details & Activity Panel (Metadata, Provenance, Verification, Actions)

const FM = {
  viewMode: "studies", // "studies" or "files"
  currentCategory: "working",
  currentSubpath: "",
  search: "",
  sortBy: "name",
  sortDir: "asc",
  selected: new Set(),
  selectedItem: null,
  categories: {},
  overview: null,
  items: [],
  studies: [],
  reconciliation: null,
  rightPanelOpen: true
};

async function filesView(v) {
  v.innerHTML = `<div class="card" style="padding:20px;text-align:center"><span class="mut">Loading Research-Data Workspace…</span></div>`;
  if (typeof pvStates === "function") await pvStates();
  
  try {
    const [catRes, ovRes, studiesRes, recRes] = await Promise.all([
      api("/api/files/categories"),
      api("/api/storage/overview"),
      api("/api/workspace/studies"),
      api("/api/workspace/reconcile")
    ]);
    if (catRes.ok && catRes.categories) FM.categories = catRes.categories;
    if (ovRes) FM.overview = ovRes;
    if (studiesRes && studiesRes.studies) FM.studies = studiesRes.studies;
    if (recRes && recRes.ok) FM.reconciliation = recRes;
  } catch (e) {
    v.innerHTML = `<div class="card bad">Failed to load storage topology: ${esc(e.message)}</div>`;
    return;
  }

  await renderFileManager(v);
}

async function renderFileManager(v) {
  // If in files mode, fetch current directory files
  let data = null;
  if (FM.viewMode === "files") {
    try {
      const q = new URLSearchParams({
        category: FM.currentCategory,
        subpath: FM.currentSubpath,
        search: FM.search,
        sort_by: FM.sortBy,
        sort_dir: FM.sortDir
      });
      data = await api("/api/files/browse?" + q.toString());
      FM.items = (data && data.ok && data.items) ? data.items : [];
      FM.currentPath = (data && data.ok && data.current_path) || "";
    } catch (e) {
      data = { ok: false, error: e.message };
      FM.items = [];
    }
  }

  const mac = (FM.overview && FM.overview.mac_internal) || { free_gb: 0, total_gb: 0, free_pct: 0, mount_path: "Internal SSD" };
  const vault = (FM.overview && FM.overview.external_vault) || { connected: false, free_gb: 0, total_gb: 0, free_pct: 0, mount_path: "Disconnected" };
  const rec = FM.reconciliation || { unregistered_count: 0, total_discovered: 0, total_registered: 0 };

  const curCat = FM.categories[FM.currentCategory] || { name: FM.currentCategory, path: "" };

  v.innerHTML = `
    <!-- Top Telemetry Header Bar -->
    <div class="row" style="gap:16px;margin-bottom:14px">
      <div class="card" style="flex:1;margin:0;padding:12px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:4px">
          <b>Internal Mac SSD (Active Workspace)</b>
          <span class="pill ${mac.free_gb < 15 ? 'warn' : 'ok'}">${mac.free_gb} GB Free (${mac.free_pct}%)</span>
        </div>
        <div class="bar" style="height:6px"><i style="width:${Math.min(100, 100 - mac.free_pct)}%;background:var(--${mac.free_gb < 15 ? 'warn' : 'ok'})"></i></div>
        <div class="note" style="margin-top:4px">${esc(mac.mount_path)} · Active processing &amp; Pensieve</div>
      </div>

      <div class="card" style="flex:1;margin:0;padding:12px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:4px">
          <b>External Data Vault (Permanent Archive)</b>
          <span class="pill ${vault.connected ? 'ok' : 'bad'}">${vault.connected ? `${vault.free_gb} GB Free` : "DISCONNECTED"}</span>
        </div>
        <div class="bar" style="height:6px"><i style="width:${vault.connected ? Math.min(100, 100 - vault.free_pct) : 0}%;background:var(--${vault.connected ? 'ok' : 'bad'})"></i></div>
        <div class="note" style="margin-top:4px">${esc(vault.mount_path)} · Immutable originals &amp; cold archives</div>
      </div>
    </div>

    <!-- Mode Switcher Toolbar -->
    <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap">
      <div class="row" style="gap:8px;margin:0">
        <button class="b ${FM.viewMode==='studies'?'pri':''}" id="fm-tab-studies">🗂 Study Workspaces (${FM.studies.length})</button>
        <button class="b ${FM.viewMode==='files'?'pri':''}" id="fm-tab-files">📁 Directory Files Browser</button>
      </div>

      <div class="row" style="gap:8px;margin:0">
        ${rec.unregistered_count > 0 ? `
          <button class="b warn sm" id="fm-batch-reg-btn">
            ⚡ Reconcile: Register ${rec.unregistered_count} Discovered Studies
          </button>
        ` : ""}
        <button class="b sm" id="fm-toggle-right">${FM.rightPanelOpen ? 'Hide Details ⇥' : '⇤ Show Details'}</button>
      </div>
    </div>

    <!-- Three-Part Layout Container -->
    <div style="display:flex;gap:14px;align-items:stretch;min-height:580px">
      
      <!-- Part 1: Left Storage Navigation Rail (240px) -->
      <div class="card" style="width:240px;flex-shrink:0;margin:0;padding:10px;display:flex;flex-direction:column;gap:12px">
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px;padding:4px 8px">Storage Topology</div>
          <div style="display:flex;flex-direction:column;gap:2px">
            <button class="b sm ${FM.viewMode==='studies'?'pri':''}" id="nav-ws-ledger" style="justify-content:flex-start;text-align:left;width:100%;padding:6px 10px">
              🗂 Study Workspaces
            </button>
          </div>
        </div>

        <div>
          <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px;padding:4px 8px">Data Categories</div>
          <div style="display:flex;flex-direction:column;gap:2px">
            ${Object.entries(FM.categories).map(([k, c]) => `
              <button class="b sm ${FM.viewMode==='files' && FM.currentCategory===k ? 'pri' : ''}" data-nav-cat="${esc(k)}" style="justify-content:flex-start;text-align:left;width:100%;padding:6px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                📁 ${esc(c.name)}
              </button>
            `).join("")}
          </div>
        </div>

        <div style="margin-top:auto;border-top:1px solid var(--line);padding-top:10px">
          <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px;padding:4px 8px">Safety &amp; Recovery</div>
          <button class="b sm ${FM.viewMode==='files' && FM.currentCategory==='quarantine' ? 'pri' : ''}" data-nav-cat="quarantine" style="justify-content:flex-start;text-align:left;width:100%;padding:6px 10px;color:var(--bad)">
            ☣ Recovery &amp; Quarantine
          </button>
        </div>
      </div>

      <!-- Part 2: Center File & Study Browser (Flex-1) -->
      <div class="card" style="flex:1;margin:0;padding:14px;display:flex;flex-direction:column">
        ${FM.viewMode === "studies" ? renderStudiesCenterPane() : renderFilesCenterPane(data, curCat)}
      </div>

      <!-- Part 3: Right Collapsible Details & Activity Panel (280px) -->
      ${FM.rightPanelOpen ? `
        <div class="card" style="width:280px;flex-shrink:0;margin:0;padding:14px;background:var(--panel2)">
          ${renderRightDetailsPane()}
        </div>
      ` : ""}
    </div>
  `;

  bindFileManagerEvents(v, data);
}

function renderStudiesCenterPane() {
  const rec = FM.reconciliation || {};
  return `
    <div class="row" style="justify-content:space-between;margin-bottom:10px">
      <b>Authoritative Study Workspace Ledger (${FM.studies.length} Registered)</b>
      <span class="note">Managed by StudyWorkspaceManager</span>
    </div>

    ${rec.unregistered_count > 0 ? `
      <div style="padding:10px 14px;background:color-mix(in srgb,var(--warn) 12%,transparent);border:1px solid var(--warn);border-radius:6px;margin-bottom:12px;font-size:12px" class="row">
        <span style="flex:1"><b>Reconciliation Alert:</b> Found <b>${rec.unregistered_count}</b> preserved studies on disk not yet in the active ledger.</span>
        <button class="b pri sm" id="fm-cta-batch-reg">Register All Discovered ▶</button>
      </div>
    ` : ""}

    ${FM.studies.length === 0 ? `
      <div style="text-align:center;padding:40px;color:var(--mut);flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center">
        No studies registered in the active ledger yet.
        <div style="margin-top:10px">
          <button class="b pri" id="fm-cta-batch-reg-center">Discover &amp; Register Preserved Studies</button>
        </div>
      </div>
    ` : `
      <div style="flex:1;overflow-y:auto;max-height:500px;border:1px solid var(--line);border-radius:6px">
        <table>
          <thead>
            <tr>
              <th>Study ID</th><th>Lifecycle Phase</th><th>Original Location</th><th>Archive Status</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${FM.studies.map(s => `
              <tr class="fm-study-row ${FM.selectedItem && FM.selectedItem.study_id === s.study_id ? 'cur' : ''}" data-study-id="${esc(s.study_id)}" style="cursor:pointer">
                <td><b>${esc(s.study_id)}</b></td>
                <td><span class="pill ${s.state==='Archived'?'ok':s.state==='Ready for processing'?'pri':'warn'}">${esc(s.state)}</span></td>
                <td class="mono" style="font-size:11px" title="${esc(s.original_mri_location || '')}">${esc((s.original_mri_location || '—').slice(-25))}</td>
                <td><span class="pill ${s.archive_status==='archived_and_verified'?'ok':'mut'}">${esc(s.archive_status || 'not_archived')}</span></td>
                <td>
                  <div class="row" style="gap:4px;margin:0">
                    ${typeof pvCell === "function" ? pvCell(s.study_id) : ""}
                  </div>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `}
  `;
}

function renderFilesCenterPane(data, curCat) {
  return `
    <!-- Directory Toolbar -->
    <div class="row" style="justify-content:space-between;margin-bottom:10px;gap:8px;flex-wrap:wrap">
      <div class="row" style="gap:6px;align-items:center;margin:0">
        <b>${esc(curCat.name)}</b>
        ${FM.currentSubpath ? `
          <span class="mut">/</span>
          <span class="mono" style="font-size:12px">${esc(FM.currentSubpath)}</span>
          <button class="b sm" id="fm-up">⬆ Up</button>
        ` : ""}
      </div>
      <div class="row" style="gap:6px;margin:0">
        <input id="fm-search" placeholder="Filter files…" value="${esc(FM.search)}" style="width:140px;padding:4px 8px;font-size:12px">
        <button class="b sm" id="fm-refresh">↻</button>
        <button class="b sm pri" id="fm-mkdir">+ Folder</button>
      </div>
    </div>

    <!-- Bulk Operations Action Bar -->
    <div class="row" style="gap:6px;padding:6px 10px;background:var(--panel2);border:1px solid var(--line);border-radius:6px;margin-bottom:10px;font-size:12px">
      <span class="note" id="fm-sel-count" style="margin-right:6px">0 selected</span>
      <button class="b sm" id="fm-copy" disabled>📋 Copy</button>
      <button class="b sm" id="fm-move" disabled>✂ Move</button>
      <button class="b sm" id="fm-archive" disabled>📦 Archive</button>
      <button class="b sm" id="fm-restore" disabled>📥 Restore</button>
      <button class="b sm bad" id="fm-del" disabled>🗑 Delete</button>
    </div>

    <!-- File Table -->
    ${(!data || !data.ok) ? `
      <div class="card bad">${esc(data ? data.error : "Failed reading directory")}</div>
    ` : (FM.items.length === 0) ? `
      <div style="text-align:center;padding:40px;color:var(--mut);flex:1">No files found in this location.</div>
    ` : `
      <div style="flex:1;overflow-y:auto;max-height:480px;border:1px solid var(--line);border-radius:6px">
        <table>
          <thead>
            <tr>
              <th style="width:30px;text-align:center"><input type="checkbox" id="fm-sel-all"></th>
              <th>Name</th><th>Size</th><th>Modified</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${FM.items.map((it, idx) => `
              <tr class="fm-file-row ${FM.selectedItem && FM.selectedItem.path === it.path ? 'cur' : ''}" data-idx="${idx}" style="cursor:pointer">
                <td style="text-align:center"><input type="checkbox" class="fm-chk" data-path="${esc(it.path)}"></td>
                <td>
                  ${it.is_dir ? `
                    <a href="javascript:void(0)" class="fm-dir-link" data-sub="${esc(it.rel_path)}" style="font-weight:600;display:flex;align-items:center;gap:6px;text-decoration:none">
                      📁 ${esc(it.name)}
                    </a>
                  ` : `
                    <span style="display:flex;align-items:center;gap:6px">📄 ${esc(it.name)}</span>
                  `}
                </td>
                <td class="mono" style="font-size:11px">${esc(it.size_str)}</td>
                <td class="note" style="font-size:11px">${esc(it.mtime_str)}</td>
                <td>
                  <div class="row" style="gap:4px;margin:0">
                    <button class="b sm" data-rename="${esc(it.path)}" data-name="${esc(it.name)}" title="Rename">✎</button>
                    ${!it.is_dir ? `<button class="b sm" data-verify="${esc(it.path)}" title="Verify SHA-256">✓</button>` : ""}
                    <button class="b sm bad" data-del="${esc(it.path)}" data-name="${esc(it.name)}" title="Delete">✕</button>
                  </div>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `}
  `;
}

function renderRightDetailsPane() {
  const item = FM.selectedItem;
  if (!item) {
    return `
      <b style="font-size:13px;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px">Details Inspector</b>
      <div style="text-align:center;padding:50px 10px;color:var(--mut);font-size:12px">
        Select a study or file to inspect metadata, checksum verification, storage location, and available operations.
      </div>
    `;
  }

  const isStudy = !!item.study_id;
  return `
    <div style="font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Details Inspector</div>
    <b style="font-size:15px;display:block;margin-bottom:6px;overflow:hidden;text-overflow:ellipsis">${esc(item.name || item.study_id)}</b>
    
    <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;margin-top:12px">
      <div>
        <span class="mut">Classification:</span><br>
        <span class="pill pri" style="margin-top:2px">${isStudy ? 'Registered Study' : (item.is_dir ? 'Directory' : 'Research Data')}</span>
      </div>

      <div>
        <span class="mut">Full Path:</span><br>
        <span class="mono" style="font-size:10px;word-break:break-all">${esc(item.path || item.active_workspace_location || item.original_mri_location || '—')}</span>
      </div>

      <div>
        <span class="mut">Size:</span><br>
        <b>${esc(item.size_str || (item.total_size_mb ? `${item.total_size_mb} MB` : '—'))}</b>
      </div>

      ${isStudy ? `
        <div>
          <span class="mut">Lifecycle State:</span><br>
          <span class="pill ${item.state==='Archived'?'ok':'warn'}">${esc(item.state || 'Unknown')}</span>
        </div>
        <div>
          <span class="mut">Original Source:</span><br>
          <span class="mono" style="font-size:10px;word-break:break-all">${esc(item.original_mri_location || '—')}</span>
        </div>
        <div>
          <span class="mut">Archive Location:</span><br>
          <span class="mono" style="font-size:10px;word-break:break-all">${esc(item.hdd_archive_location || '—')}</span>
        </div>
      ` : `
        <div>
          <span class="mut">Modified:</span><br>
          <span class="note">${esc(item.mtime_str || '—')}</span>
        </div>
      `}
    </div>

    <div style="margin-top:20px;border-top:1px solid var(--line);padding-top:14px;display:flex;flex-direction:column;gap:6px">
      ${!isStudy && !item.is_dir ? `
        <button class="b sm" id="dtl-verify-btn" data-verify-path="${esc(item.path)}">✓ Verify SHA-256 Checksum</button>
      ` : ""}
      <button class="b sm" id="dtl-copy-path-btn">Copy Path to Clipboard</button>
    </div>
  `;
}

function bindFileManagerEvents(v, data) {
  // Navigation tabs
  const bStudies = $("#fm-tab-studies"), bFiles = $("#fm-tab-files");
  if (bStudies) bStudies.onclick = async () => { FM.viewMode = "studies"; await filesView(v); };
  if (bFiles) bFiles.onclick = async () => { FM.viewMode = "files"; await renderFileManager(v); };

  // Category navigation rail
  v.querySelectorAll("[data-nav-cat]").forEach(btn => {
    btn.onclick = async () => {
      FM.viewMode = "files";
      FM.currentCategory = btn.dataset.navCat;
      FM.currentSubpath = "";
      await renderFileManager(v);
    };
  });

  const navWs = $("#nav-ws-ledger");
  if (navWs) navWs.onclick = async () => { FM.viewMode = "studies"; await filesView(v); };

  // Toggle right panel
  const togBtn = $("#fm-toggle-right");
  if (togBtn) togBtn.onclick = () => {
    FM.rightPanelOpen = !FM.rightPanelOpen;
    renderFileManager(v);
  };

  // Batch register discovered studies
  const bBatchReg = $("#fm-batch-reg-btn") || $("#fm-cta-batch-reg") || $("#fm-cta-batch-reg-center");
  if (bBatchReg) bBatchReg.onclick = async () => {
    bBatchReg.disabled = true;
    bBatchReg.textContent = "Registering…";
    const res = await api("/api/workspace/batch_register", {});
    if (res.ok) {
      toast(`Successfully registered ${res.registered_count} studies into ledger!`);
      await filesView(v);
    } else {
      toast(`Registration error: ${res.error}`, true);
    }
  };

  // Study row clicks -> Select in Right Panel
  v.querySelectorAll(".fm-study-row").forEach(tr => {
    tr.onclick = (e) => {
      if (e.target.tagName === "BUTTON") return;
      const sid = tr.dataset.studyId;
      FM.selectedItem = FM.studies.find(s => s.study_id === sid) || null;
      renderFileManager(v);
    };
  });

  // File row clicks -> Select in Right Panel
  v.querySelectorAll(".fm-file-row").forEach(tr => {
    tr.onclick = (e) => {
      if (e.target.tagName === "BUTTON" || e.target.tagName === "INPUT" || e.target.tagName === "A") return;
      const idx = parseInt(tr.dataset.idx, 10);
      FM.selectedItem = FM.items[idx] || null;
      renderFileManager(v);
    };
  });

  // Subpath navigation
  v.querySelectorAll(".fm-dir-link").forEach(a => {
    a.onclick = async () => {
      FM.currentSubpath = a.dataset.sub;
      await renderFileManager(v);
    };
  });

  const upBtn = $("#fm-up");
  if (upBtn) upBtn.onclick = async () => {
    const parts = FM.currentSubpath.split("/").filter(Boolean);
    parts.pop();
    FM.currentSubpath = parts.join("/");
    await renderFileManager(v);
  };

  // Search input
  const srch = $("#fm-search");
  if (srch) srch.oninput = (e) => {
    FM.search = e.target.value;
    renderFileManager(v);
  };

  // Right panel copy path
  const cpBtn = $("#dtl-copy-path-btn");
  if (cpBtn && FM.selectedItem) {
    cpBtn.onclick = () => {
      const p = FM.selectedItem.path || FM.selectedItem.active_workspace_location || FM.selectedItem.original_mri_location || "";
      navigator.clipboard.writeText(p);
      toast("Path copied to clipboard");
    };
  }

  // Right panel verify SHA
  const verBtn = $("#dtl-verify-btn");
  if (verBtn) {
    verBtn.onclick = async () => {
      verBtn.disabled = true;
      verBtn.textContent = "Verifying…";
      const p = verBtn.dataset.verifyPath;
      const res = await api("/api/files/verify", { path: p });
      verBtn.disabled = false;
      verBtn.textContent = "✓ Verify SHA-256 Checksum";
      if (res.ok) alert(`SHA-256 Verified:\nFile: ${esc(p)}\nChecksum: ${res.sha256}`);
      else toast(`Error: ${res.error}`, true);
    };
  }

  // 2026-11-28 (audit: the file buttons had no handlers): every action calls the guarded backend (/api/files/*: safety policy, transfer
  // guard, SHA-256 verified copies); the server refuses what is protected and the reason is shown. Delete moves to the Trash.
  const sel = () => [...v.querySelectorAll(".fm-chk:checked")].map(c => c.dataset.path);
  const selCount = () => {const n = sel().length, el = $("#fm-sel-count"); if (el) el.textContent = `${n} selected`;
    ["fm-copy","fm-move","fm-archive","fm-del"].forEach(id => {const b = $("#"+id); if (b) b.disabled = !n});
    const r = $("#fm-restore"); if (r) r.disabled = !(n && FM.currentCategory && /vault|pensieve|archive/i.test(FM.currentCategory))};
  v.querySelectorAll(".fm-chk").forEach(c => c.onchange = selCount);
  const all = $("#fm-sel-all"); if (all) all.onchange = () => {v.querySelectorAll(".fm-chk").forEach(c => c.checked = all.checked); selCount()};
  selCount();
  const report = async (label, paths, call) => {let ok = 0, bad = [];
    for (const p of paths) {const r = await call(p); if (r && r.ok) ok++; else bad.push(`${p.split("/").pop()}: ${(r && (r.error || r.message)) || "failed"}`)}
    toast(`${label}: ${ok} done${bad.length ? ` · ${bad.length} refused - ${bad.slice(0, 3).join("; ")}` : ""}`, bad.length > 0); await renderFileManager(v)};
  const askDest = (what) => prompt(`${what} - destination folder (full path inside this project or the Data Vault):`, FM.currentPath || "");
  const mk = $("#fm-mkdir"); if (mk) mk.onclick = async () => {const n = prompt("New folder name:"); if (!n) return;
    const r = await api("/api/files/mkdir", {parent_dir: FM.currentPath, dir_name: n}); toast(r.ok ? `Folder '${esc(n)}' created` : esc(r.error || "refused"), !r.ok); if (r.ok) renderFileManager(v)};
  const cp = $("#fm-copy"); if (cp) cp.onclick = async () => {const d = askDest("Copy"); if (!d) return;
    await report("Copy (verified)", sel(), p => api("/api/files/copy", {src: p, dst_dir: d, conflict_mode: "keep_both"}))};
  const mv = $("#fm-move"); if (mv) mv.onclick = async () => {const d = askDest("Move"); if (!d) return;
    if (!confirm(`Move ${sel().length} item(s) to\n${d}?\n\nEach copy is verified before the original is removed.`)) return;
    await report("Move (verified)", sel(), p => api("/api/files/move", {src: p, dst_dir: d, conflict_mode: "keep_both"}))};
  const ar = $("#fm-archive"); if (ar) ar.onclick = async () => {if (!confirm(`Archive ${sel().length} item(s) to the Data Vault (verified copy; the originals stay)?`)) return;
    await report("Archive to the Data Vault", sel(), p => api("/api/files/archive", {src: p, vault_category: "archive"}))};
  const rs = $("#fm-restore"); if (rs) rs.onclick = async () => {const d = askDest("Restore to the Mac"); if (!d) return;
    await report("Restore (verified)", sel(), p => api("/api/files/restore", {vault_path: p, dst_dir: d}))};
  const del = async (paths) => {if (!paths.length) return; const t = prompt(`Move ${paths.length} item(s) to the Trash?\n${paths.slice(0, 5).map(p => p.split("/").pop()).join("\n")}\n\nProtected files (MRI, reviews, databases, identities) are refused by the app.\nType TRASH to confirm:`);
    if (t !== "TRASH") return; await report("Moved to the Trash", paths, p => api("/api/files/delete", {path: p, confirm: true}))};
  const db = $("#fm-del"); if (db) db.onclick = () => del(sel());
  v.querySelectorAll("[data-del]").forEach(b => b.onclick = () => del([b.dataset.del]));
  v.querySelectorAll("[data-rename]").forEach(b => b.onclick = async () => {const n = prompt("New name:", b.dataset.name); if (!n || n === b.dataset.name) return;
    const r = await api("/api/files/rename", {path: b.dataset.rename, new_name: n}); toast(r.ok ? "Renamed" : esc(r.error || "refused"), !r.ok); if (r.ok) renderFileManager(v)});
  v.querySelectorAll("[data-verify]").forEach(b => b.onclick = async () => {b.disabled = true; const r = await api("/api/files/verify", {path: b.dataset.verify}); b.disabled = false;
    toast(r.ok ? `SHA-256 ${r.sha256.slice(0, 16)}… (${esc(b.dataset.verify.split("/").pop())})` : esc(r.error || "refused"), !r.ok)});

  // Study actions (Stage, Archive, Clean)
  if (typeof pvBind === "function") pvBind(v, () => filesView(v));
  v.querySelectorAll("[data-ws-stage]").forEach(b => {
    b.onclick = async () => {
      b.disabled = true;
      b.textContent = "Staging…";
      const sid = b.dataset.wsStage;
      const r = await api("/api/workspace/stage", { study_id: sid });
      if (r.ok) { toast(`Staged ${sid} to local SSD workspace!`); filesView(v); }
      else { toast(`Stage failed: ${r.error || r.message}`, true); b.disabled = false; b.textContent = "Stage"; }
    };
  });

  v.querySelectorAll("[data-ws-archive]").forEach(b => {
    b.onclick = async () => {
      b.disabled = true;
      b.textContent = "Archiving…";
      const sid = b.dataset.wsArchive;
      const r = await api("/api/workspace/archive", { study_id: sid });
      if (r.ok) { toast(`Archived ${sid} to Data Vault and verified!`); filesView(v); }
      else { toast(`Archive failed: ${r.error || r.message}`, true); b.disabled = false; b.textContent = "Archive"; }
    };
  });

  v.querySelectorAll("[data-ws-clean]").forEach(b => {
    b.onclick = async () => {
      const sid = b.dataset.wsClean;
      if (!confirm(`Clean local SSD workspace for study '${sid}'?\n\nSafety check: Only permitted if study is verified in Vault and review is completed.`)) return;
      b.disabled = true;
      b.textContent = "Cleaning…";
      const r = await api("/api/workspace/clean", { study_id: sid });
      if (r.ok) { toast(`Cleaned local workspace for ${sid}`); filesView(v); }
      else { alert(`Clean refused by safety policy:\n${r.error || r.message}`); b.disabled = false; b.textContent = "Clean"; }
    };
  });
}
