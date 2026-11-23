// Phase 1e.3 test harness: loads app/transfer_view.js in Node with stubbed browser globals and exercises its pure
// render / action logic against backend payloads (written by tests/test_phase1e_gui.py). No DOM library needed.
// usage: node gui_transfer_harness.js <fixture.json>  ->  prints a JSON report
const fs = require("fs");
const path = require("path");
const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const calls = [];
let confirmAnswer = false;
global.toast = () => {};
global.confirm = () => confirmAnswer;
global.api = async (url, body) => {
  calls.push({ url, body: body || null });
  const u = url.split("?")[0];
  if (body) return { ok: true, requested: true };
  if (u.endsWith("/jobs")) return { ok: true, jobs: fixture.jobs };
  if (u.endsWith("/workers")) return { ok: true, workers: fixture.workers };
  if (u.endsWith("/vault_check")) return { ok: true, vault: fixture.vault };
  if (u.endsWith("/eject_check")) return fixture.eject;
  if (u.endsWith("/job")) return fixture.detail;
  if (u.endsWith("/assess")) return { ok: true, assessment: fixture.assess };
  return { ok: false, error: { code: "not_found", message: url } };
};
const TV = require(path.join(__dirname, "..", "app", "transfer_view.js"));

(async () => {
  const out = { tabs: {}, actions: {}, states_shown: {}, calls: null };
  for (const tab of ["attention", "active", "queued", "history"]) {
    const html = TV.tcRender(fixture, { tab, search: "", selected: null });
    out.tabs[tab] = html;
    out.states_shown[tab] = [...html.matchAll(/data-job-row="([^"]+)"/g)].map(m => m[1]);
  }
  out.search = [...TV.tcRender(fixture, { tab: "history", search: fixture.search || "" }).matchAll(/data-job-row="([^"]+)"/g)].map(m => m[1]);
  for (const j of fixture.jobs) out.actions[j.job_id] = TV.tcActions(j);
  // a refresh REPLACES all client data with the backend payload (a stale job never survives)
  TV.TC.data = { jobs: [{ job_id: "stale-client-only", state: "copying", progress: {} }] };
  TV.TC.selected = fixture.detail_id;
  await TV.tcFetch();
  out.after_fetch_ids = TV.TC.data.jobs.map(j => j.job_id);
  out.detail_html = TV.tcRender(TV.TC.data, { tab: "attention", selected: fixture.detail_id, assess: fixture.assess });
  // controls post to the backend; discard needs an explicit confirmation
  calls.length = 0;
  await TV.tcAct("pause", "J-PAUSE");
  confirmAnswer = false; await TV.tcAct("discard", "J-NO");
  confirmAnswer = true; await TV.tcAct("discard", "J-YES");
  await TV.tcAct("resume", "J-RES");
  await TV.tcAct("cancel", "J-CAN");
  out.calls = calls.map(c => ({ url: c.url, body: c.body }));
  out.escaped = TV.tcRender({ jobs: [{ job_id: "x", operation: "<img src=x onerror=alert(1)>", state: "failed",
    progress: {}, error: { code: "failed", message: "<script>bad()</script>" } }] }, { tab: "attention" });
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(2); });
