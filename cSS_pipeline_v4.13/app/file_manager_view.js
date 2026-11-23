// file_manager_view.js - Dedicated File Manager & Storage Management Screen for PERCIVAL.
// Provides complete file/folder browsing, multi-selection, manual operations (Copy, Move,
// Rename, New Folder, Delete, Archive, Restore, Verify SHA-256) across local NVMe SSD and Data Vault.

const FM = {
  currentCategory: "working",
  currentSubpath: "",
  search: "",
  sortBy: "name",
  sortDir: "asc",
  selected: new Set(),
  categories: {},
  overview: null,
  items: []
};

async function filesView(v) {
  v.innerHTML = `<div class="card" style="padding:20px;text-align:center"><span class="mut">Loading File Manager…</span></div>`;
  
  try {
    const catRes = await api("/api/files/categories");
    if (catRes.ok && catRes.categories) {
      FM.categories = catRes.categories;
    }
    const ovRes = await api("/api/files/overview");
    if (ovRes) {
      FM.overview = ovRes;
    }
  } catch (e) {
    v.innerHTML = `<div class="card bad">Failed to load storage topology: ${esc(e.message)}</div>`;
    return;
  }

  await renderFileManager(v);
}

async function renderFileManager(v) {
  // Fetch files in current category and subpath
  let data = null;
  try {
    const q = new URLSearchParams({
      category: FM.currentCategory,
      subpath: FM.currentSubpath,
      search: FM.search,
      sort_by: FM.sortBy,
      sort_dir: FM.sortDir
    });
    data = await api("/api/files/browse?" + q.toString());
  } catch (e) {
    data = { ok: false, error: e.message };
  }

  FM.items = (data && data.ok && data.items) ? data.items : [];
  FM.selected.clear();

  // Storage Overview bar
  const ssd = (FM.overview && FM.overview.local_ssd) || { free_gb: 0, total_gb: 0, free_pct: 0 };
  const vault = (FM.overview && FM.overview.data_vault) || { connected: false, free_gb: 0, total_gb: 0, free_pct: 0 };

  const ssdClass = ssd.free_gb < 5 ? "bad" : ssd.free_gb < 20 ? "warn" : "ok";
  const vaultClass = vault.connected ? (vault.free_gb < 50 ? "warn" : "ok") : "bad";

  const cat = FM.categories[FM.currentCategory] || { name: FM.currentCategory, path: "" };

  v.innerHTML = `
    <!-- Top Telemetry & Health Bar -->
    <div class="row" style="gap:16px;margin-bottom:12px">
      <div class="card" style="flex:1;margin:0;padding:12px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:6px">
          <b>Local Mac SSD Staging</b>
          <span class="pill ${ssdClass}">${ssd.free_gb} GB Free (${ssd.free_pct}%)</span>
        </div>
        <div class="bar" style="height:6px"><i style="width:${Math.min(100, 100 - ssd.free_pct)}%;background:var(--${ssdClass})"></i></div>
        <div class="note" style="margin-top:4px">${esc(ssd.path || "Internal NVMe SSD")}</div>
      </div>

      <div class="card" style="flex:1;margin:0;padding:12px 16px">
        <div class="row" style="justify-content:space-between;margin-bottom:6px">
          <b>External Data Vault (Pensieve Memory)</b>
          <span class="pill ${vaultClass}">${vault.connected ? `${vault.free_gb} GB Free` : "DISCONNECTED"}</span>
        </div>
        <div class="bar" style="height:6px"><i style="width:${vault.connected ? Math.min(100, 100 - vault.free_pct) : 0}%;background:var(--${vaultClass})"></i></div>
        <div class="note" style="margin-top:4px">${esc(vault.root_path || "No external vault configured")}</div>
      </div>
    </div>

    <!-- Main Two-Column File Manager Interface -->
    <div style="display:flex;gap:16px;align-items:flex-start">
      <!-- Left Category Navigation Sidebar -->
      <div class="card" style="width:260px;flex-shrink:0;margin:0;padding:8px">
        <div style="padding:6px 10px;font-weight:600;font-size:12px;text-transform:uppercase;color:var(--mut);letter-spacing:0.5px">Storage Categories</div>
        <div style="display:flex;flex-direction:column;gap:2px">
          ${Object.entries(FM.categories).map(([k, c]) => `
            <button class="b ${FM.currentCategory === k ? "pri" : ""}" data-cat="${esc(k)}" style="justify-content:flex-start;text-align:left;padding:7px 10px;border-radius:5px;font-size:13px;width:100%">
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.name)}</span>
            </button>
          `).join("")}
        </div>
      </div>

      <!-- Right Main Browser Pane -->
      <div class="card" style="flex:1;margin:0;padding:16px">
        <!-- Breadcrumbs & Search Toolbar -->
        <div class="row" style="justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px">
          <div class="row" style="gap:6px;align-items:center;margin:0">
            <b style="font-size:16px">${esc(cat.name)}</b>
            ${FM.currentSubpath ? `
              <span class="mut">/</span>
              <span class="mono" style="font-size:13px">${esc(FM.currentSubpath)}</span>
              <button class="b sm" id="fm-up">⬆ Up</button>
            ` : ""}
          </div>

          <div class="row" style="gap:8px;margin:0">
            <input id="fm-search" placeholder="Filter files…" value="${esc(FM.search)}" style="width:160px;padding:4px 8px;font-size:13px">
            <button class="b sm" id="fm-refresh" title="Refresh">↻ Refresh</button>
            <button class="b sm pri" id="fm-mkdir">+ New Folder</button>
          </div>
        </div>

        <!-- Operations Toolbar -->
        <div class="row" style="gap:8px;padding:8px 12px;background:var(--card);border:1px solid var(--line);border-radius:6px;margin-bottom:12px;flex-wrap:wrap">
          <span class="note" id="fm-sel-count" style="margin-right:8px">0 selected</span>
          <button class="b sm" id="fm-copy" disabled>📋 Copy…</button>
          <button class="b sm" id="fm-move" disabled>✂ Move…</button>
          <button class="b sm" id="fm-archive" disabled>📦 Archive to Vault</button>
          <button class="b sm" id="fm-restore" disabled>📥 Restore to Local</button>
          <button class="b sm bad" id="fm-del" disabled>🗑 Delete…</button>
        </div>

        <!-- File List Table -->
        ${(!data || !data.ok) ? `
          <div class="card bad">${esc(data ? data.error : "Failed reading category directory")}</div>
        ` : (FM.items.length === 0) ? `
          <div class="card" style="text-align:center;padding:30px;color:var(--mut)">No files or folders found in this location.</div>
        ` : `
          <div style="max-height:550px;overflow:auto;border:1px solid var(--line);border-radius:6px">
            <table style="width:100%;border-collapse:collapse">
              <thead>
                <tr style="border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:2">
                  <th style="width:36px;text-align:center"><input type="checkbox" id="fm-sel-all"></th>
                  <th style="text-align:left;padding:8px">Name</th>
                  <th style="width:110px;text-align:right;padding:8px">Size</th>
                  <th style="width:170px;text-align:left;padding:8px">Modified</th>
                  <th style="width:150px;text-align:center;padding:8px">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${FM.items.map((item, idx) => `
                  <tr style="border-bottom:1px solid var(--line);font-size:13px" class="fm-row" data-idx="${idx}">
                    <td style="text-align:center"><input type="checkbox" class="fm-chk" data-path="${esc(item.path)}"></td>
                    <td style="padding:7px 8px">
                      ${item.is_dir ? `
                        <a href="javascript:void(0)" class="fm-dir-link" data-sub="${esc(item.rel_path)}" style="font-weight:600;display:flex;align-items:center;gap:6px;text-decoration:none">
                          📁 ${esc(item.name)}
                        </a>
                      ` : `
                        <span style="display:flex;align-items:center;gap:6px">
                          📄 ${esc(item.name)}
                        </span>
                      `}
                    </td>
                    <td style="text-align:right;padding:7px 8px;font-family:monospace;color:var(--mut)">${esc(item.size_str)}</td>
                    <td style="padding:7px 8px;color:var(--mut);font-size:12px">${esc(item.mtime_str)}</td>
                    <td style="text-align:center;padding:7px 8px">
                      <div class="row" style="justify-content:center;gap:4px;margin:0">
                        <button class="b sm" data-rename="${esc(item.path)}" data-name="${esc(item.name)}" title="Rename">✎</button>
                        ${!item.is_dir ? `<button class="b sm" data-verify="${esc(item.path)}" title="Verify SHA-256">✓</button>` : ""}
                        <button class="b sm bad" data-del="${esc(item.path)}" data-name="${esc(item.name)}" title="Delete">✕</button>
                      </div>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>
    </div>
  `;

  // Bind category clicks
  v.querySelectorAll("[data-cat]").forEach(b => {
    b.onclick = () => {
      FM.currentCategory = b.dataset.cat;
      FM.currentSubpath = "";
      renderFileManager(v);
    };
  });

  // Directory traversal links
  v.querySelectorAll(".fm-dir-link").forEach(a => {
    a.onclick = () => {
      FM.currentSubpath = a.dataset.sub;
      renderFileManager(v);
    };
  });

  // Up button
  const upBtn = $("#fm-up");
  if (upBtn) {
    upBtn.onclick = () => {
      if (FM.currentSubpath) {
        const parts = FM.currentSubpath.split("/").filter(Boolean);
        parts.pop();
        FM.currentSubpath = parts.join("/");
        renderFileManager(v);
      }
    };
  }

  // Refresh
  const refBtn = $("#fm-refresh");
  if (refBtn) refBtn.onclick = () => renderFileManager(v);

  // Search input
  const sInput = $("#fm-search");
  if (sInput) {
    sInput.onchange = () => {
      FM.search = sInput.value.trim();
      renderFileManager(v);
    };
  }

  // Selection checkboxes
  const selAll = $("#fm-sel-all");
  const chks = v.querySelectorAll(".fm-chk");
  const updateSelButtons = () => {
    const n = FM.selected.size;
    const cntEl = $("#fm-sel-count");
    if (cntEl) cntEl.textContent = `${n} selected`;
    $("#fm-copy").disabled = (n === 0);
    $("#fm-move").disabled = (n === 0);
    $("#fm-del").disabled = (n === 0);
    $("#fm-archive").disabled = (n === 0 || !vault.connected);
    $("#fm-restore").disabled = (n === 0);
  };

  if (selAll) {
    selAll.onclick = () => {
      chks.forEach(c => {
        c.checked = selAll.checked;
        if (selAll.checked) FM.selected.add(c.dataset.path);
        else FM.selected.delete(c.dataset.path);
      });
      updateSelButtons();
    };
  }

  chks.forEach(c => {
    c.onclick = () => {
      if (c.checked) FM.selected.add(c.dataset.path);
      else FM.selected.delete(c.dataset.path);
      updateSelButtons();
    };
  });

  // New folder
  const mkdirBtn = $("#fm-mkdir");
  if (mkdirBtn) {
    mkdirBtn.onclick = async () => {
      const name = prompt("Enter new folder name:");
      if (!name || !name.trim()) return;
      const targetDir = data ? data.current_path : "";
      const res = await api("/api/files/mkdir", { parent_dir: targetDir, dir_name: name.trim() });
      if (res.ok) {
        toast(`Folder '${name}' created`);
        renderFileManager(v);
      } else {
        toast(`Error: ${res.error}`, true);
      }
    };
  }

  // Rename
  v.querySelectorAll("[data-rename]").forEach(b => {
    b.onclick = async () => {
      const p = b.dataset.rename;
      const oldName = b.dataset.name;
      const newName = prompt("Rename item:", oldName);
      if (!newName || !newName.trim() || newName.trim() === oldName) return;
      const res = await api("/api/files/rename", { path: p, new_name: newName.trim() });
      if (res.ok) {
        toast(`Renamed to '${newName}'`);
        renderFileManager(v);
      } else {
        toast(`Error: ${res.error}`, true);
      }
    };
  });

  // Verify SHA-256
  v.querySelectorAll("[data-verify]").forEach(b => {
    b.onclick = async () => {
      b.disabled = true;
      b.textContent = "…";
      const p = b.dataset.verify;
      const res = await api("/api/files/verify", { path: p });
      b.disabled = false;
      b.textContent = "✓";
      if (res.ok) {
        alert(`SHA-256 Verified:\nFile: ${esc(p)}\nChecksum: ${res.sha256}`);
      } else {
        toast(`Verification error: ${res.error}`, true);
      }
    };
  });

  // Single delete
  v.querySelectorAll("[data-del]").forEach(b => {
    b.onclick = async () => {
      const p = b.dataset.del;
      const name = b.dataset.name;
      if (!confirm(`Are you sure you want to permanently delete '${name}'?\n\nPath: ${p}`)) return;
      const res = await api("/api/files/delete", { path: p, confirm: true });
      if (res.ok) {
        toast(`Deleted '${name}'`);
        renderFileManager(v);
      } else {
        toast(`Delete failed: ${res.error}`, true);
      }
    };
  });

  // Bulk Delete
  $("#fm-del").onclick = async () => {
    const list = Array.from(FM.selected);
    if (!list.length) return;
    if (!confirm(`Permanently delete ${list.length} selected item(s)?\n\nThis cannot be undone.`)) return;
    let deleted = 0;
    for (const p of list) {
      const r = await api("/api/files/delete", { path: p, confirm: true });
      if (r.ok) deleted++;
    }
    toast(`Deleted ${deleted}/${list.length} items`);
    renderFileManager(v);
  };

  // Bulk Copy
  $("#fm-copy").onclick = async () => {
    const list = Array.from(FM.selected);
    const catKeys = Object.keys(FM.categories);
    const targetCat = prompt(`Copy ${list.length} item(s) to which category?\n\nOptions:\n${catKeys.join(", ")}`, "working");
    if (!targetCat || !FM.categories[targetCat]) return;
    const dstDir = FM.categories[targetCat].path;
    let copied = 0;
    for (const p of list) {
      const r = await api("/api/files/copy", { src: p, dst_dir: dstDir, conflict_mode: "keep_both" });
      if (r.ok) copied++;
    }
    toast(`Copied ${copied}/${list.length} items to ${targetCat}`);
    renderFileManager(v);
  };

  // Bulk Move
  $("#fm-move").onclick = async () => {
    const list = Array.from(FM.selected);
    const catKeys = Object.keys(FM.categories);
    const targetCat = prompt(`Move ${list.length} item(s) to which category?\n\nOptions:\n${catKeys.join(", ")}`, "working");
    if (!targetCat || !FM.categories[targetCat]) return;
    const dstDir = FM.categories[targetCat].path;
    let moved = 0;
    for (const p of list) {
      const r = await api("/api/files/move", { src: p, dst_dir: dstDir, conflict_mode: "keep_both" });
      if (r.ok) moved++;
    }
    toast(`Moved ${moved}/${list.length} items to ${targetCat}`);
    renderFileManager(v);
  };

  // Archive to Vault
  $("#fm-archive").onclick = async () => {
    const list = Array.from(FM.selected);
    if (!vault.connected) {
      alert("External Data Vault is not connected.");
      return;
    }
    let archived = 0;
    for (const p of list) {
      const r = await api("/api/files/archive", { src: p, vault_category: "archive" });
      if (r.ok) archived++;
    }
    toast(`Archived ${archived}/${list.length} item(s) to Data Vault with SHA-256 verification`);
    renderFileManager(v);
  };

  // Restore to Local
  $("#fm-restore").onclick = async () => {
    const list = Array.from(FM.selected);
    const dstDir = FM.categories.working.path;
    let restored = 0;
    for (const p of list) {
      const r = await api("/api/files/restore", { vault_path: p, dst_dir: dstDir });
      if (r.ok) restored++;
    }
    toast(`Restored ${restored}/${list.length} item(s) to local workspace`);
    renderFileManager(v);
  };
}
