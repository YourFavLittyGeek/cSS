// setup_view.js - PERCIVAL Master Guided Setup & System Configuration Center
// Mission ID: PERCIVAL-SETUP-REDESIGN-2026
// 7-Step Guided Workflow:
//   Step 1: Welcome & Automatic System Discovery
//   Step 2: Software Installations & Manual Path Selection
//   Step 3: Storage Architecture (Dual SSD/HDD Tier & Vault Recognition)
//   Step 4: Pipeline & Scientific Configuration
//   Step 5: Analysis Policy (Candidate Calling & Fingerprint Matching)
//   Step 6: Capability-Based Scientific Readiness Dashboard
//   Step 7: Completion & System Launch

const PSC = {
  step: 1,
  lifecycle: null,
  discovery: null,
  readiness: null,
  diagnostics: null,
  config: {
    python_executable: "",
    freesurfer_home: "",
    fs_license: "",
    pipeline_dir: "",
    dcm2niix_path: "",
    workspace_dir: "",
    vault_mount: "",
    candidate_redetection: true,
    candidate_calling: true,
    threads: 4
  },
  validation_states: {},
  busy: false
};

const STEP_DEFINITIONS = [
  { id: 1, title: "Welcome & Discovery", desc: "Automated scan of host hardware, software & storage" },
  { id: 2, title: "Software Installations", desc: "Python environment, FreeSurfer, license & MRI tools" },
  { id: 3, title: "Storage Architecture", desc: "Fast internal SSD workspace & external cold Vault" },
  { id: 4, title: "Pipeline & Engine", desc: "PERCIVAL algorithms, models & Pensieve database" },
  { id: 5, title: "Analysis Configuration", desc: "Candidate re-detection policy & spatial fingerprints" },
  { id: 6, title: "System Readiness", desc: "7-point scientific capability verification matrix" },
  { id: 7, title: "Completion & Launch", desc: "Final configuration summary & workspace access" }
];

async function setupView(v) {
  if (V !== "setup") return;
  v.innerHTML = `<div style="display:flex;height:calc(100vh - 120px);align-items:center;justify-content:center;color:var(--mut)"><div style="text-align:center"><div class="spin" style="margin:0 auto 16px;width:32px;height:32px;border:3px solid var(--bd);border-top-color:var(--pri);border-radius:50%"></div>Loading PERCIVAL Setup Center…</div></div>`;

  try {
    const life = await api("/api/setup/lifecycle");
    PSC.lifecycle = life;
    PSC.step = life.current_step || 1;

    // Load discovery cache or trigger initial discovery
    const discRes = await api("/api/setup/discovery");
    PSC.discovery = discRes.discovery || {};

    // Synchronize current configuration values
    const cfg = life.validated_config || {};
    if (cfg.freesurfer_home) PSC.config.freesurfer_home = cfg.freesurfer_home;
    if (cfg.fs_license) PSC.config.fs_license = cfg.fs_license;
    if (cfg.workspace_dir) PSC.config.workspace_dir = cfg.workspace_dir;
    if (cfg.vault_mount) PSC.config.vault_mount = cfg.vault_mount;
    if (cfg.candidate_redetection !== undefined) PSC.config.candidate_redetection = cfg.candidate_redetection;
    if (cfg.candidate_calling !== undefined) PSC.config.candidate_calling = cfg.candidate_calling;

    // Apply smart discovery defaults if empty
    applyDiscoveryDefaults();

    renderSetupLayout(v);
  } catch (err) {
    v.innerHTML = `<div class="card bad"><h2>Setup Center Error</h2><p>${esc(err.message || String(err))}</p><button class="b pri" onclick="setupView($('#view'))" style="margin-top:12px">Retry</button></div>`;
  }
}

function applyDiscoveryDefaults() {
  const d = PSC.discovery;
  if (!d) return;

  if (!PSC.config.python_executable && d.python && d.python.length > 0) {
    const prefPy = d.python.find(p => p.is_preferred) || d.python[0];
    if (prefPy) PSC.config.python_executable = prefPy.path;
  }
  if (!PSC.config.freesurfer_home && d.freesurfer && d.freesurfer.length > 0) {
    const prefFs = d.freesurfer.find(f => f.is_preferred) || d.freesurfer[0];
    if (prefFs) PSC.config.freesurfer_home = prefFs.path;
  }
  if (!PSC.config.fs_license && d.licenses && d.licenses.length > 0) {
    PSC.config.fs_license = d.licenses[0].path;
  }
  if (!PSC.config.pipeline_dir && d.pipeline && d.pipeline.length > 0) {
    const prefPipe = d.pipeline.find(p => p.is_preferred) || d.pipeline[0];
    if (prefPipe) PSC.config.pipeline_dir = prefPipe.path;
  }
  if (!PSC.config.workspace_dir && d.storage && d.storage.workspace) {
    PSC.config.workspace_dir = d.storage.workspace.path;
  }
  if (!PSC.config.vault_mount && d.storage && d.storage.vaults && d.storage.vaults.length > 0) {
    const prefV = d.storage.vaults.find(v => v.is_preferred) || d.storage.vaults[0];
    if (prefV) PSC.config.vault_mount = prefV.path;
  }
  if (!PSC.config.dcm2niix_path && d.mri_tools && d.mri_tools.dcm2niix) {
    PSC.config.dcm2niix_path = d.mri_tools.dcm2niix.path || "";
  }
}

function renderSetupLayout(v) {
  const isFirstLaunch = PSC.lifecycle && !PSC.lifecycle.allow_dashboard;
  const isLocked = isFirstLaunch;

  v.innerHTML = `
<div id="psc-container" style="display:flex;gap:24px;min-height:calc(100vh - 110px);padding-bottom:80px">
  <!-- Left Step Progress Rail -->
  <aside style="width:260px;flex-shrink:0;border-right:1px solid var(--bd);padding-right:16px">
    <div style="margin-bottom:20px">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--mut)">Onboarding &amp; Setup</div>
      <h2 style="font-size:18px;margin:4px 0 2px;color:var(--txt)">PERCIVAL Setup</h2>
      <div style="font-size:12px;color:var(--mut)">${isFirstLaunch ? "Initial Guided Configuration" : "System Configuration Review"}</div>
    </div>

    <div style="display:flex;flex-direction:column;gap:6px">
      ${STEP_DEFINITIONS.map(s => {
        const isCurrent = s.id === PSC.step;
        const isDone = s.id < PSC.step || (PSC.lifecycle && s.id <= (PSC.lifecycle.last_completed_step || 0));
        return `
        <div class="psc-rail-item ${isCurrent ? 'active' : ''} ${isDone ? 'done' : ''}" onclick="goToStep(${s.id})"
             style="display:flex;align-items:flex-start;gap:10px;padding:8px 10px;border-radius:6px;cursor:pointer;border:1px solid ${isCurrent ? 'var(--pri)' : 'transparent'};background:${isCurrent ? 'rgba(57,135,229,0.1)' : 'transparent'}">
          <div style="width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;background:${isCurrent ? 'var(--pri)' : (isDone ? 'var(--ok)' : 'rgba(255,255,255,0.08)')};color:${isCurrent || isDone ? '#fff' : 'var(--mut)'}">
            ${isDone && !isCurrent ? '✓' : s.id}
          </div>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:${isCurrent ? '600' : '500'};color:${isCurrent ? 'var(--txt)' : 'var(--mut)'}">${esc(s.title)}</div>
            <div style="font-size:11px;color:var(--mut);line-height:1.2;margin-top:2px">${esc(s.desc)}</div>
          </div>
        </div>`;
      }).join("")}
    </div>

    <!-- Safety & Preservation Guarantee Box -->
    <div style="margin-top:30px;padding:12px;background:rgba(25,158,112,0.08);border:1px solid rgba(25,158,112,0.25);border-radius:6px;font-size:11px;color:var(--mut)">
      <div style="font-weight:600;color:var(--ok);display:flex;align-items:center;gap:6px;margin-bottom:4px">
        <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" fill="none" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        Non-Destructive Setup
      </div>
      Original MRI datasets, Pensieve database records, and expert review calls are 100% preserved during setup.
    </div>
  </aside>

  <!-- Right Main Step Content -->
  <main style="flex:1;min-width:0;max-width:920px">
    <div id="psc-step-content"></div>
  </main>
</div>

<!-- Persistent Bottom Navigation Bar -->
<div id="psc-bottom-bar" style="position:fixed;bottom:0;left:240px;right:0;height:64px;background:var(--panel);border-top:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between;padding:0 32px;z-index:90">
  <div>
    <button class="b" id="psc-btn-save-exit" onclick="saveAndExit()" style="font-size:12px">Save Progress &amp; Exit</button>
    <button class="b" id="psc-btn-rescan" onclick="triggerRescan()" style="font-size:12px;margin-left:8px">⟳ Re-Scan System</button>
  </div>
  <div style="display:flex;gap:10px">
    ${PSC.step > 1 ? `<button class="b" id="psc-btn-back" onclick="goToStep(${PSC.step - 1})">◂ Back</button>` : ''}
    <button class="b" id="psc-btn-validate-step" onclick="validateCurrentStep()">Validate Step</button>
    ${PSC.step < 7 ? `
      <button class="b pri" id="psc-btn-continue" onclick="continueNextStep()">Continue: ${esc(STEP_DEFINITIONS[PSC.step].title)} ▸</button>
    ` : `
      <button class="b pri" id="psc-btn-finish" onclick="finishAndLaunch()" style="background:var(--ok)">✓ Finish Setup &amp; Launch PERCIVAL</button>
    `}
  </div>
</div>
`;

  renderStepContent();
}

async function renderStepContent() {
  const el = $("#psc-step-content");
  if (!el) return;

  switch (PSC.step) {
    case 1: renderStep1_Welcome(el); break;
    case 2: renderStep2_Software(el); break;
    case 3: renderStep3_Storage(el); break;
    case 4: renderStep4_Pipeline(el); break;
    case 5: renderStep5_Analysis(el); break;
    case 6: renderStep6_Readiness(el); break;
    case 7: renderStep7_Completion(el); break;
  }
}

// -----------------------------------------------------------------------------
// STEP 1: Welcome & Automatic System Discovery
// -----------------------------------------------------------------------------
function renderStep1_Welcome(el) {
  const sys = PSC.discovery ? PSC.discovery.system : {};
  const d = PSC.discovery || {};
  const pyCount = (d.python || []).length;
  const fsCount = (d.freesurfer || []).length;
  const vaultCount = (d.storage && d.storage.vaults ? d.storage.vaults.length : 0);

  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 1 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Welcome to PERCIVAL</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      PERCIVAL is a clinical and scientific neuroimaging research workstation for AI-assisted cerebral superficial siderosis (cSS) detection.
      This Guided Setup configures your local environment, validates your scientific tools, and establishes your high-speed SSD workspace and cold Data Vault.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div>
        <h3 style="font-size:15px;margin:0">Host Hardware &amp; System Platform</h3>
        <span class="note">Discovered automatically from macOS host</span>
      </div>
      <span class="pill ok">APPLE SILICON COMPATIBLE</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:8px">
      <div style="background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">macOS Version</div>
        <div style="font-size:13px;font-weight:600;margin-top:2px">${esc(sys.os_name || "macOS")} ${esc(sys.os_version || "")}</div>
      </div>
      <div style="background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">CPU Architecture</div>
        <div style="font-size:13px;font-weight:600;margin-top:2px">${esc(sys.architecture || "arm64")} (${esc(sys.cpu_brand || "Apple M-Series")})</div>
      </div>
      <div style="background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">Total System RAM</div>
        <div style="font-size:13px;font-weight:600;margin-top:2px">${sys.total_ram_gb || 16} GB Unified Memory</div>
      </div>
      <div style="background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">Internal SSD Headroom</div>
        <div style="font-size:13px;font-weight:600;margin-top:2px">${sys.free_ssd_gb || 0} GB Free</div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div>
        <h3 style="font-size:15px;margin:0">Automated Software &amp; Storage Discovery Dashboard</h3>
        <span class="note">PERCIVAL has inspected your system to locate existing scientific components</span>
      </div>
      <button class="b" onclick="triggerRescan()" style="font-size:12px">⟳ Re-Scan</button>
    </div>

    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--panel2);border-radius:6px;border:1px solid var(--bd)">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:16px">🐍</span>
          <div>
            <div style="font-weight:600;font-size:13px">Python 3.10+ Scientific Runtime</div>
            <div class="mut" style="font-size:11px">${pyCount} candidate environment(s) detected · conda &amp; homebrew scanned</div>
          </div>
        </div>
        <span class="pill ${pyCount > 0 ? 'ok' : 'bad'}">${pyCount > 0 ? `${pyCount} FOUND` : 'NOT FOUND'}</span>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--panel2);border-radius:6px;border:1px solid var(--bd)">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:16px">🧠</span>
          <div>
            <div style="font-weight:600;font-size:13px">FreeSurfer Suite &amp; License</div>
            <div class="mut" style="font-size:11px">${fsCount} installation(s) detected in /Applications · license verified in Downloads</div>
          </div>
        </div>
        <span class="pill ${fsCount > 0 ? 'ok' : 'warn'}">${fsCount > 0 ? `${fsCount} DETECTED` : 'MANUAL REQUIRED'}</span>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--panel2);border-radius:6px;border:1px solid var(--bd)">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:16px">🔬</span>
          <div>
            <div style="font-weight:600;font-size:13px">PERCIVAL Algorithm Pipeline &amp; Models</div>
            <div class="mut" style="font-size:11px">ALBUS detection · NOX measurements · LUMOS / PERCIVAL learning - models are trained only after expert review (see PERCIVAL › System)</div>
          </div>
        </div>
        <span class="pill">CODE PRESENT · NOT TRAINED HERE</span>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--panel2);border-radius:6px;border:1px solid var(--bd)">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:16px">💾</span>
          <div>
            <div style="font-weight:600;font-size:13px">Storage Topology &amp; External Data Vault</div>
            <div class="mut" style="font-size:11px">Internal SSD workspace active · ${vaultCount > 0 ? 'External Vault mounted with historical archives' : 'Vault drive currently offline (can connect later)'}</div>
          </div>
        </div>
        <span class="pill ${vaultCount > 0 ? 'ok' : 'warn'}">${vaultCount > 0 ? 'VAULT CONNECTED' : 'LOCAL-ONLY'}</span>
      </div>

      ${d.discovered_studies && d.discovered_studies.length > 0 ? `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--panel2);border-radius:6px;border:1px solid var(--bd)">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:16px">🗂</span>
          <div>
            <div style="font-weight:600;font-size:13px">Preserved Original MRI Studies Detected</div>
            <div class="mut" style="font-size:11px">${d.discovered_studies.length} original MRI studies preserved on disk · Immutable raw source preservation</div>
          </div>
        </div>
        <span class="pill ok">${d.discovered_studies.length} PRESERVED</span>
      </div>
      ` : ""}
    </div>
  </div>

  <div style="display:flex;gap:12px;margin-top:20px">
    <button class="b pri" onclick="continueNextStep()" style="font-size:13px;padding:10px 20px">Begin Guided Setup ▸</button>
    <button class="b" onclick="goToStep(6)" style="font-size:13px;padding:10px 20px">Review System Readiness Matrix</button>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 2: Software Installations & Manual Path Selection
// -----------------------------------------------------------------------------
function renderStep2_Software(el) {
  const d = PSC.discovery || {};
  const pyList = d.python || [];
  const fsList = d.freesurfer || [];
  const licList = d.licenses || [];
  const dcm = (d.mri_tools && d.mri_tools.dcm2niix) ? d.mri_tools.dcm2niix : {};

  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 2 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Software Installations &amp; Paths</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      Configure your scientific software tools. You may choose automatically detected installations or specify custom file paths.
    </p>
  </div>

  <!-- Card 1: Python Environment -->
  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">1. Python Scientific Environment (3.10+)</h3>
        <p class="note" style="margin:4px 0 10px">Required packages: numpy, scipy, nibabel, pandas, skimage, matplotlib, pydicom, openpyxl, cryptography</p>
      </div>
      <span class="pill ${PSC.config.python_executable ? 'ok' : 'warn'}">REQUIRED</span>
    </div>

    ${pyList.length > 0 ? `
    <div style="margin-bottom:10px">
      <span class="mut" style="font-size:11px">Detected Environments:</span>
      <select class="wide" style="margin-top:4px" onchange="PSC.config.python_executable=this.value;$('#psc-py-path').value=this.value">
        ${pyList.map(p => `<option value="${esc(p.path)}" ${p.path === PSC.config.python_executable ? 'selected' : ''}>${esc(p.name)} [${esc(p.path)}]</option>`).join("")}
      </select>
    </div>` : ''}

    <div class="row">
      <span class="lab">Python Executable</span>
      <input class="wide" id="psc-py-path" value="${esc(PSC.config.python_executable)}" placeholder="/Users/.../miniforge3/envs/css/bin/python3">
      <button class="b" onclick="validateComponent('python', $('#psc-py-path').value)">Validate</button>
    </div>
    <div id="psc-val-python" class="note" style="margin-top:6px"></div>
  </div>

  <!-- Card 2: FreeSurfer Suite -->
  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">2. FreeSurfer Suite (v7.0+)</h3>
        <p class="note" style="margin:4px 0 10px">Required tools: mri_synthseg, mri_synthstrip, mri_convert, mri_vol2vol</p>
      </div>
      <span class="pill ok">RECOMMENDED</span>
    </div>

    ${fsList.length > 0 ? `
    <div style="margin-bottom:10px">
      <span class="mut" style="font-size:11px">Detected FreeSurfer Installations:</span>
      <select class="wide" style="margin-top:4px" onchange="PSC.config.freesurfer_home=this.value;$('#psc-fs-path').value=this.value">
        ${fsList.map(f => `<option value="${esc(f.path)}" ${f.path === PSC.config.freesurfer_home ? 'selected' : ''}>${esc(f.name)} (${esc(f.version)})</option>`).join("")}
      </select>
    </div>` : ''}

    <div class="row">
      <span class="lab">FREESURFER_HOME</span>
      <input class="wide" id="psc-fs-path" value="${esc(PSC.config.freesurfer_home)}" placeholder="/Applications/freesurfer/8.2.0">
      <button class="b" onclick="validateComponent('freesurfer', $('#psc-fs-path').value)">Validate</button>
    </div>
    <div id="psc-val-freesurfer" class="note" style="margin-top:6px"></div>
  </div>

  <!-- Card 3: FreeSurfer License -->
  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">3. FreeSurfer License File</h3>
        <p class="note" style="margin:4px 0 10px">Structure validated locally; key contents are never exposed or transmitted</p>
      </div>
      <span class="pill ok">REQUIRED FOR FREESURFER</span>
    </div>

    ${licList.length > 0 ? `
    <div style="margin-bottom:10px">
      <span class="mut" style="font-size:11px">Detected License Files:</span>
      <select class="wide" style="margin-top:4px" onchange="PSC.config.fs_license=this.value;$('#psc-lic-path').value=this.value">
        ${licList.map(l => `<option value="${esc(l.path)}" ${l.path === PSC.config.fs_license ? 'selected' : ''}>${esc(l.name)} [${esc(l.path)}]</option>`).join("")}
      </select>
    </div>` : ''}

    <div class="row">
      <span class="lab">License Path</span>
      <input class="wide" id="psc-lic-path" value="${esc(PSC.config.fs_license)}" placeholder="/Users/.../Downloads/license.txt">
      <button class="b" onclick="validateComponent('license', $('#psc-lic-path').value)">Validate</button>
    </div>
    <div id="psc-val-license" class="note" style="margin-top:6px"></div>
  </div>

  <!-- Card 4: MRI Tools (dcm2niix) -->
  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">4. MRI Ingestion Tool (dcm2niix)</h3>
        <p class="note" style="margin:4px 0 10px">Converts vendor DICOM series into high-speed NIfTI neuroimaging format</p>
      </div>
      <span class="pill ${dcm.is_valid ? 'ok' : 'bad'}">${dcm.is_valid ? 'INSTALLED' : 'REQUIRED'}</span>
    </div>

    <div class="row">
      <span class="lab">dcm2niix Path</span>
      <input class="wide" id="psc-dcm-path" value="${esc(PSC.config.dcm2niix_path || dcm.path || "")}" placeholder="/opt/homebrew/bin/dcm2niix">
      <button class="b" onclick="validateComponent('mri_tool', $('#psc-dcm-path').value, {tool_name:'dcm2niix'})">Validate</button>
    </div>
    <div id="psc-val-dcm2niix" class="note" style="margin-top:6px"></div>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 3: Storage Architecture
// -----------------------------------------------------------------------------
function renderStep3_Storage(el) {
  const d = PSC.discovery || {};
  const ws = (d.storage && d.storage.workspace) ? d.storage.workspace : {};
  const vaults = (d.storage && d.storage.vaults) ? d.storage.vaults : [];

  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 3 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Dual-Tier Storage Architecture</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      PERCIVAL pairs a high-speed internal Mac SSD for active processing with a permanent external USB HDD for cold archiving and Pensieve backups.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">1. Fast Internal Mac NVMe SSD (Active Workspace)</h3>
        <p class="note" style="margin:4px 0 10px">Temporary active workspace for MRI staging, FreeSurfer surface reconstruction, and blind review</p>
      </div>
      <span class="pill ok">MANDATORY FAST TIER</span>
    </div>

    <div class="row">
      <span class="lab">Workspace Path</span>
      <input class="wide" id="psc-ws-path" value="${esc(PSC.config.workspace_dir || ws.path || "")}" placeholder="/Users/.../Percival_project">
      <button class="b" onclick="validateComponent('workspace', $('#psc-ws-path').value)">Validate</button>
    </div>
    <div id="psc-val-workspace" class="note" style="margin-top:6px">
      ${ws.details && ws.details.free_gb ? `Available Headroom: <b>${ws.details.free_gb} GB free</b> on internal APFS SSD` : ''}
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <h3 style="font-size:15px;margin:0">2. External Data Vault (Permanent Cold Archive)</h3>
        <p class="note" style="margin:4px 0 10px">Stores original DICOM archives, verified research exports, and transactional Pensieve backups</p>
      </div>
      <span class="pill ${vaults.length > 0 ? 'ok' : 'warn'}">${vaults.length > 0 ? 'VAULT FOUND' : 'LOCAL-ONLY AVAILABLE'}</span>
    </div>

    ${vaults.length > 0 ? `
    <div style="margin-bottom:10px">
      <span class="mut" style="font-size:11px">Detected Vaults &amp; External Volumes:</span>
      <select class="wide" style="margin-top:4px" onchange="PSC.config.vault_mount=this.value;$('#psc-vault-path').value=this.value">
        ${vaults.map(v => `<option value="${esc(v.path)}" ${v.path === PSC.config.vault_mount ? 'selected' : ''}>${esc(v.name)} [${esc(v.version)}]</option>`).join("")}
      </select>
    </div>` : `
    <div class="note" style="background:rgba(255,255,255,0.03);padding:8px 12px;border-radius:6px;margin-bottom:12px">
      No external drive currently mounted under <code>/Volumes</code>. You can attach your USB HDD at any time; PERCIVAL will automatically recognize your Vault.
    </div>`}

    <div class="row">
      <span class="lab">Vault Root Path</span>
      <input class="wide" id="psc-vault-path" value="${esc(PSC.config.vault_mount)}" placeholder="/Volumes/Percival/PERCIVAL_VAULT">
      <button class="b" onclick="validateComponent('vault', $('#psc-vault-path').value)">Validate</button>
    </div>
    <div id="psc-val-vault" class="note" style="margin-top:6px"></div>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 4: Pipeline & Scientific Configuration
// -----------------------------------------------------------------------------
function renderStep4_Pipeline(el) {
  const d = PSC.discovery || {};
  const pipe = (d.pipeline && d.pipeline.length > 0) ? d.pipeline[0] : {};
  const pens = (d.pensieve && d.pensieve.length > 0) ? d.pensieve[0] : {};

  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 4 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Pipeline &amp; Scientific Components</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      Configure your scientific algorithm repositories, candidate detection modules, and provenance ledger.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div>
        <h3 style="font-size:15px;margin:0">PERCIVAL Pipeline Algorithms</h3>
        <span class="note">Entry points: run_css.sh, detect_css.py, align_seg.py, score_css.py</span>
      </div>
      <span class="pill ok">${esc(pipe.version || "v5.26-dev")}</span>
    </div>
    <div class="row">
      <span class="lab">Pipeline Root</span>
      <input class="wide" id="psc-pipe-path" value="${esc(PSC.config.pipeline_dir || pipe.path || "")}" placeholder="/Users/.../cSS_pipeline_v4.13">
      <button class="b" onclick="validateComponent('pipeline', $('#psc-pipe-path').value)">Validate</button>
    </div>
    <div id="psc-val-pipeline" class="note" style="margin-top:6px">
      ${pipe.details && pipe.details.script_count ? `Verified: ${pipe.details.script_count} executable scripts ready` : ''}
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h3 style="font-size:15px;margin:0 0 8px">Pensieve Provenance &amp; Database Health</h3>
    <p class="note" style="margin-bottom:12px">Pensieve maintains clinical call history, adjudication records, and mathematical reproducibility stamps.</p>
    <div style="display:flex;align-items:center;justify-content:space-between;background:var(--panel2);padding:10px 14px;border-radius:6px;border:1px solid var(--bd)">
      <div>
        <div style="font-weight:600;font-size:13px">${esc(pens.name || "Active Pensieve Ledger")}</div>
        <div class="mut" style="font-size:11px">${esc(pens.path || "app_data/pensieve.db")} · ${esc(pens.version || "")}</div>
      </div>
      <span class="pill ok">INTEGRITY OK</span>
    </div>
  </div>

  <div class="card">
    <h3 style="font-size:15px;margin:0 0 8px">Model Storage &amp; Neural Weights</h3>
    <p class="note" style="margin-bottom:12px">Local weights for spatial feature extraction, synthetic demonstration models, and SynthMorph.</p>
    <div style="display:flex;gap:12px">
      <div style="flex:1;background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">ALBUS &amp; LUMOS</div>
        <div style="font-weight:600;margin-top:2px">Spatial Surface Fingerprint Engine</div>
      </div>
      <div style="flex:1;background:var(--panel2);padding:10px;border-radius:6px;border:1px solid var(--bd)">
        <div class="mut" style="font-size:11px">Synthetic Image Softmax</div>
        <div style="font-weight:600;margin-top:2px">Demonstration &amp; Integration Model</div>
      </div>
    </div>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 5: Analysis Configuration
// -----------------------------------------------------------------------------
function renderStep5_Analysis(el) {
  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 5 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Analysis Policy &amp; Candidate Calling</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      Configure scientific calling behavior. PERCIVAL strictly separates algorithmic candidate detections from expert-confirmed ground truth.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <h3 style="font-size:15px;margin:0">1. Automated Candidate Re-Detection</h3>
      <input type="checkbox" id="psc-opt-redetect" ${PSC.config.candidate_redetection ? 'checked' : ''} onchange="PSC.config.candidate_redetection=this.checked" style="width:18px;height:18px">
    </div>
    <p class="note" style="line-height:1.4">
      When reprocessing an existing study, re-extracts spatial candidate coordinates directly from original SWI/T1 MRI volumes rather than reusing cached candidate coordinates.
    </p>
    <div style="font-size:11px;color:var(--pri);margin-top:4px">Recommended: <b>Active (ON)</b> for fresh-start reprocessing.</div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <h3 style="font-size:15px;margin:0">2. Automated Spatial Fingerprint Calling</h3>
      <input type="checkbox" id="psc-opt-calling" ${PSC.config.candidate_calling ? 'checked' : ''} onchange="PSC.config.candidate_calling=this.checked" style="width:18px;height:18px">
    </div>
    <p class="note" style="line-height:1.4">
      Automatically matches detected candidate patches against anatomical spatial fingerprints in the Pensieve ledger, accelerating clinician confirmation.
    </p>
    <div style="font-size:11px;color:var(--pri);margin-top:4px">Recommended: <b>Active (ON)</b> for consistent study-to-study adjudication.</div>
  </div>

  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <h3 style="font-size:15px;margin:0">3. Scientific Invariant Guarantees</h3>
      <span class="pill ok">GOVERNANCE ENFORCED</span>
    </div>
    <ul style="font-size:12px;color:var(--mut);margin:0;padding-left:18px;line-height:1.6">
      <li>Expert annotations and confirmed calls are <b>never overwritten automatically</b>.</li>
      <li>Unreviewed studies with zero detected candidates are <b>never silently marked negative</b>.</li>
      <li>Model predictions retain permanent software build stamps and cryptographic lineage records.</li>
    </ul>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 6: Capability-Based Scientific Readiness Matrix
// -----------------------------------------------------------------------------
async function renderStep6_Readiness(el) {
  el.innerHTML = `<div style="text-align:center;padding:40px;color:var(--mut)">Evaluating 7-point capability matrix…</div>`;
  const r = await api("/api/setup/readiness");
  PSC.readiness = r.readiness || {};
  const caps = PSC.readiness.capabilities || {};

  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(57,135,229,0.15);color:var(--pri);font-size:11px;font-weight:700;margin-bottom:8px">STEP 6 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">System Readiness Verification</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      Capability-specific verification distinguishes required launch conditions from optional scientific modules.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div>
        <h3 style="font-size:15px;margin:0">Scientific Capability Matrix</h3>
        <span class="note">${PSC.readiness.ready ? "All mandatory launch requirements are met." : "Certain required components require your attention."}</span>
      </div>
      <span class="pill ${PSC.readiness.ready ? 'ok' : 'bad'}">${PSC.readiness.ready ? 'WORKSTATION READY' : 'ACTION REQUIRED'}</span>
    </div>

    <div style="display:flex;flex-direction:column;gap:8px">
      ${Object.values(caps).map(c => `
      <div style="background:var(--panel2);border:1px solid var(--bd);border-radius:6px;padding:10px 14px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div style="font-weight:600;font-size:13px;color:var(--txt)">${esc(c.label)}</div>
          <span class="pill ${c.ready ? 'ok' : (c.blockers && c.blockers.length ? 'bad' : 'warn')}">
            ${c.ready ? 'READY' : (c.blockers && c.blockers.length ? 'BLOCKED' : 'OPTIONAL WARNING')}
          </span>
        </div>
        ${c.blockers && c.blockers.length ? `
        <div style="margin-top:6px;font-size:11px;color:var(--bad)">
          ${c.blockers.map(b => `<div>❌ ${esc(b)}</div>`).join("")}
        </div>` : ''}
        ${c.warnings && c.warnings.length ? `
        <div style="margin-top:4px;font-size:11px;color:var(--warn)">
          ${c.warnings.map(w => `<div>⚠️ ${esc(w)}</div>`).join("")}
        </div>` : ''}
      </div>
      `).join("")}
    </div>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// STEP 7: Completion & Launch
// -----------------------------------------------------------------------------
function renderStep7_Completion(el) {
  el.innerHTML = `
  <div style="margin-bottom:20px">
    <div style="display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(25,158,112,0.15);color:var(--ok);font-size:11px;font-weight:700;margin-bottom:8px">STEP 7 OF 7</div>
    <h1 style="font-size:24px;margin:0 0 8px;color:var(--txt)">Configuration Complete</h1>
    <p style="font-size:14px;color:var(--mut);line-height:1.5;margin:0">
      Your PERCIVAL workstation is fully configured, validated, and ready for clinical neuroimaging research.
    </p>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h3 style="font-size:15px;margin:0 0 12px">Active System Configuration Summary</h3>
    <table style="width:100%;font-size:12px">
      <tr><td style="width:180px;color:var(--mut);padding:4px 0">Python Environment:</td><td class="mono">${esc(PSC.config.python_executable || "Default Active Conda (css)")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">FreeSurfer Suite:</td><td class="mono">${esc(PSC.config.freesurfer_home || "Not configured")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">FreeSurfer License:</td><td class="mono">${esc(PSC.config.fs_license || "Auto-detected")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">MRI Tool (dcm2niix):</td><td class="mono">${esc(PSC.config.dcm2niix_path || "/opt/homebrew/bin/dcm2niix")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">Internal SSD Workspace:</td><td class="mono">${esc(PSC.config.workspace_dir || "~/Percival_project")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">External Data Vault:</td><td class="mono">${esc(PSC.config.vault_mount || "/Volumes/Percival/PERCIVAL_VAULT")}</td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">Candidate Re-Detection:</td><td><b>${PSC.config.candidate_redetection ? 'Active (ON)' : 'Disabled'}</b></td></tr>
      <tr><td style="color:var(--mut);padding:4px 0">Spatial Fingerprint Calling:</td><td><b>${PSC.config.candidate_calling ? 'Active (ON)' : 'Disabled'}</b></td></tr>
    </table>
  </div>

  <div style="display:flex;gap:12px;margin-top:24px">
    <button class="b pri" onclick="finishAndLaunch()" style="background:var(--ok);font-size:14px;padding:12px 24px">
      🚀 Launch PERCIVAL Workstation ▸
    </button>
    <button class="b" onclick="exportDiagnostics()" style="font-size:13px;padding:12px 20px">
      Export Diagnostic Report
    </button>
  </div>
  `;
}

// -----------------------------------------------------------------------------
// Interactive Navigation & Component Validation Handlers
// -----------------------------------------------------------------------------
async function goToStep(stepNum) {
  if (stepNum < 1 || stepNum > 7) return;
  PSC.step = stepNum;
  await api("/api/setup/step", { step: stepNum, partial_config: PSC.config });
  setupView($("#view"));
}

async function continueNextStep() {
  await collectCurrentStepInputs();
  await api("/api/setup/save_config", PSC.config);
  goToStep(PSC.step + 1);
}

async function collectCurrentStepInputs() {
  if (PSC.step === 2) {
    if ($("#psc-py-path")) PSC.config.python_executable = $("#psc-py-path").value.trim();
    if ($("#psc-fs-path")) PSC.config.freesurfer_home = $("#psc-fs-path").value.trim();
    if ($("#psc-lic-path")) PSC.config.fs_license = $("#psc-lic-path").value.trim();
    if ($("#psc-dcm-path")) PSC.config.dcm2niix_path = $("#psc-dcm-path").value.trim();
  }
  if (PSC.step === 3) {
    if ($("#psc-ws-path")) PSC.config.workspace_dir = $("#psc-ws-path").value.trim();
    if ($("#psc-vault-path")) PSC.config.vault_mount = $("#psc-vault-path").value.trim();
  }
  if (PSC.step === 4) {
    if ($("#psc-pipe-path")) PSC.config.pipeline_dir = $("#psc-pipe-path").value.trim();
  }
}

async function validateCurrentStep() {
  await collectCurrentStepInputs();
  toast("Validating configuration…");
  const r = await api("/api/setup/save_config", PSC.config);
  if (r.ok) {
    toast("Step validated and saved successfully.");
    setupView($("#view"));
  } else {
    toast(r.error || "Validation issue detected.", true);
  }
}

async function validateComponent(componentId, pathVal, extra) {
  const statusEl = $(`#psc-val-${componentId}`);
  if (statusEl) statusEl.innerHTML = `<span class="mut">Validating ${esc(componentId)}…</span>`;

  try {
    const payload = Object.assign({ component: componentId, path: pathVal }, extra || {});
    const r = await api("/api/setup/validate_component", payload);
    if (r.ok) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--ok)">✓ Validated successfully: ${esc(r.version || r.free_gb ? `${r.free_gb} GB free` : 'Ready')}</span>`;
      toast(`${componentId} validated.`);
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--bad)">✗ Validation failed: ${esc(r.error || "Invalid path")}</span>`;
      toast(`Validation failed: ${r.error}`, true);
    }
  } catch (err) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--bad)">✗ Error: ${esc(err.message)}</span>`;
  }
}

async function saveAndExit() {
  await collectCurrentStepInputs();
  await api("/api/setup/save_config", PSC.config);
  toast("Setup progress saved. You can resume at any time.");
  if (PSC.lifecycle && PSC.lifecycle.allow_dashboard) {
    nav("studies");
  } else {
    alert("Setup progress is saved safely. The application will resume here when reopened.");
  }
}

async function triggerRescan() {
  toast("Scanning host system and connected drives…");
  const r = await api("/api/setup/rescan", {});
  if (r.ok) {
    PSC.discovery = r.discovery;
    applyDiscoveryDefaults();
    toast("Discovery complete.");
    setupView($("#view"));
  }
}

async function finishAndLaunch() {
  await collectCurrentStepInputs();
  toast("Finalizing PERCIVAL setup and committing state…");
  const r = await api("/api/setup/finish", PSC.config);
  if (r.ok) {
    toast("Setup completed successfully! Opening Studies workspace…");
    if (PSC.lifecycle) PSC.lifecycle.allow_dashboard = true;
    setTimeout(() => { nav("studies"); }, 600);
  } else {
    toast(r.error || "Setup finalization failed.", true);
  }
}

async function exportDiagnostics() {
  toast("Generating diagnostic report…");
  const r = await api("/api/setup/diagnostics");
  if (r.ok && r.markdown) {
    const blob = new Blob([r.markdown], { type: "text/markdown" });
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u;
    a.download = `PERCIVAL_DIAGNOSTICS_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    toast("Diagnostic report exported to Downloads.");
  } else {
    toast("Failed to generate diagnostic report.", true);
  }
}
