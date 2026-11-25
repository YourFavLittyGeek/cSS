// Progress window for background jobs (setup Finish, study import) - polls GET /api/job?id=...
// PROGRESS.open({job, title, blocking, background, onDone}) shows a small window: progress bar, "step k / N", what the app is doing now,
// elapsed and estimated remaining time, the recent steps. blocking=true keeps the app covered until the job ends (setup: nothing is safe
// to click before the configuration is written). background=true adds "Continue in background": the window shrinks to a pill in the
// corner that keeps the progress; the result then arrives as a notification + toast.
(function () {
  const css = `
  #pjob{position:fixed;inset:0;z-index:9000;display:flex;align-items:center;justify-content:center;background:rgba(5,8,14,.62);backdrop-filter:blur(2px)}
  #pjob .pw{width:min(520px,92vw);background:var(--panel,#151b26);border:1px solid var(--line,#2a3342);border-radius:12px;padding:20px 22px;box-shadow:0 18px 50px rgba(0,0,0,.45)}
  #pjob h3{margin:0 0 4px;font-size:16px}#pjob .sub{font-size:12px;color:var(--mut,#8b96a8);margin-bottom:14px}
  #pjob .bar{height:10px;border-radius:6px;background:var(--panel2,#1d2533);overflow:hidden}
  #pjob .fill{height:100%;width:0;background:linear-gradient(90deg,var(--pri,#3987e5),var(--ok,#199e70));transition:width .4s ease}
  #pjob .fill.ind{width:30%!important;animation:pjind 1.2s infinite ease-in-out}
  @keyframes pjind{0%{margin-left:-30%}100%{margin-left:100%}}
  #pjob .row{display:flex;justify-content:space-between;font-size:12px;margin-top:8px;color:var(--mut,#8b96a8)}
  #pjob .now{font-size:13px;margin-top:10px;min-height:18px}#pjob .now b{color:var(--txt,#e6ebf2)}
  #pjob .log{margin-top:10px;max-height:120px;overflow:auto;font-size:11px;color:var(--mut,#8b96a8);border-top:1px solid var(--line,#2a3342);padding-top:6px}
  #pjob .log div{padding:1px 0}#pjob .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
  #pjob .res-ok{color:var(--ok,#199e70);font-weight:600}#pjob .res-bad{color:var(--bad,#e5484d);font-weight:600}
  #pjpill{position:fixed;right:16px;bottom:16px;z-index:8000;background:var(--panel,#151b26);border:1px solid var(--line,#2a3342);border-radius:20px;
    padding:8px 14px;font-size:12px;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.35);display:flex;gap:10px;align-items:center}
  #pjpill .mini{width:90px;height:6px;border-radius:4px;background:var(--panel2,#1d2533);overflow:hidden}
  #pjpill .mini i{display:block;height:100%;background:var(--pri,#3987e5);width:0}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const T = s => { if (s == null) return "estimating…"; s = Math.round(s); if (s < 60) return s + " s"; const m = Math.floor(s / 60); return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`; };
  const ACTIVE = {};

  function render(o, j) {
    const done = j.state === "done", failed = j.state === "failed" || j.state === "unknown";
    const k = Math.min(j.done || 0, j.total || 0);
    const box = document.getElementById("pjob");
    if (o.mini) { pill(o, j); return; }
    if (!box) return;
    box.querySelector(".fill").style.width = (j.pct || 0) + "%";
    box.querySelector(".fill").classList.toggle("ind", !done && !failed && !k);
    box.querySelector(".steps").textContent = j.total ? `Step ${done ? j.total : Math.min(k + 1, j.total)} of ${j.total}` : "";
    box.querySelector(".pct").textContent = `${Math.round(j.pct || 0)} %`;
    box.querySelector(".el").textContent = "Elapsed " + T(j.elapsed_s);
    box.querySelector(".eta").textContent = done || failed ? "" : "Remaining ≈ " + T(j.eta_s);
    box.querySelector(".now").innerHTML = done ? `<span class="res-ok">✓ ${E(j.label || "Finished")}</span>`
      : failed ? `<span class="res-bad">✕ ${E(j.error || "stopped")}</span>` : `Now: <b>${E(j.label)}</b>`;
    box.querySelector(".log").innerHTML = (j.steps || []).slice().reverse().map(s => `<div>${E(T(s.t))} · ${E(s.label)}</div>`).join("");
    const bg = box.querySelector("[data-pj=bg]"); if (bg) bg.style.display = done || failed ? "none" : "";
    const cl = box.querySelector("[data-pj=close]"); if (cl) cl.style.display = (done || failed) && o.closeAtEnd !== false ? "" : "none";
  }
  function pill(o, j) {
    let p = document.getElementById("pjpill");
    if (!p) { p = document.createElement("div"); p.id = "pjpill"; document.body.appendChild(p); p.onclick = () => { o.mini = false; p.remove(); win(o); poll(o, true); }; }
    p.title = "Click to open the progress window";
    p.innerHTML = `<span>⏳ ${E(o.title)}</span><span class="mini"><i style="width:${j.pct || 0}%"></i></span><span>${j.total ? `${Math.min(j.done || 0, j.total)}/${j.total}` : ""}</span><span>${j.eta_s != null ? "≈ " + T(j.eta_s) : ""}</span>`;
  }
  function win(o) {
    let box = document.getElementById("pjob"); if (box) box.remove();
    box = document.createElement("div"); box.id = "pjob"; box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
    box.innerHTML = `<div class="pw"><h3>${E(o.title)}</h3><div class="sub">${E(o.subtitle || (o.blocking ? "Please wait - the app will be ready when this finishes." : ""))}</div>
      <div class="bar"><div class="fill"></div></div>
      <div class="row"><span class="steps"></span><span class="pct"></span></div>
      <div class="now"></div>
      <div class="row"><span class="el"></span><span class="eta"></span></div>
      <div class="log"></div>
      <div class="acts">${o.background ? `<button class="b" data-pj="bg">Continue in background</button>` : ""}<button class="b pri" data-pj="close" style="display:none">${E(o.closeLabel || "Close")}</button></div></div>`;
    document.body.appendChild(box);
    const bg = box.querySelector("[data-pj=bg]"); if (bg) bg.onclick = () => { o.mini = true; box.remove(); if (o.last) pill(o, o.last); };
    box.querySelector("[data-pj=close]").onclick = () => { box.remove(); if (o.afterClose) o.afterClose(o.last); };
  }
  async function poll(o, once) {
    if (o.polling && !once) return; o.polling = true; let misses = 0;
    while (true) {
      let j;
      try { j = await (await fetch("/api/job?id=" + encodeURIComponent(o.job))).json(); misses = 0; }
      catch (e) { if (++misses > 20) { j = { state: "failed", error: "the app stopped answering" }; } else { await new Promise(r => setTimeout(r, 700)); continue; } }
      o.last = j; render(o, j);
      if (j.state !== "running") {
        delete ACTIVE[o.job]; const p = document.getElementById("pjpill"); if (p && o.mini) p.remove();
        o.polling = false; if (o.onDone) await o.onDone(j, o); return j;
      }
      await new Promise(r => setTimeout(r, 600));
    }
  }
  window.PROGRESS = {
    open(opts) {
      const o = Object.assign({ blocking: false, background: false }, opts); ACTIVE[o.job] = o;
      win(o); return poll(o);
    },
    // keep a finished window open with a final message and buttons [{label, cls, fn}]
    finish(o, html, buttons) {
      const box = document.getElementById("pjob"); if (!box) return;
      box.querySelector(".now").innerHTML = html;
      const a = box.querySelector(".acts"); a.innerHTML = "";
      (buttons || []).forEach(b => { const x = document.createElement("button"); x.className = "b " + (b.cls || ""); x.textContent = b.label; x.onclick = () => { if (b.keep !== true) box.remove(); b.fn && b.fn(); }; a.appendChild(x); });
    },
    close() { const b = document.getElementById("pjob"); if (b) b.remove(); },
    active: ACTIVE,
  };
})();
