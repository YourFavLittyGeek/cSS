// GUI walkthrough for tests/e2e_rc1.py (synthetic data only). args: SOURCE_PROJECT SHOT_DIR
const {chromium}=require('playwright');const [SRC,O]=process.argv.slice(2);const U='http://127.0.0.1:8810';
let fails=0;const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(!c)fails++};
const shot=async(p,n)=>{await p.screenshot({path:`${O}/${n}.png`,fullPage:true})};
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1500,height:1000},deviceScaleFactor:1});
 const errs=[];p.on('pageerror',e=>errs.push(String(e)));p.on('dialog',d=>d.accept());
// UX redesign (2026-11): Studies list + study panel replace the Processing / Results tabs; same API calls underneath.
 await p.goto(U);await p.waitForTimeout(1500);await shot(p,'R01_studies');
 ok(await p.isVisible('nav button[data-v="add"]'),'Add studies section present');
 ok((await p.textContent('#view')).includes('No studies yet'),'empty experimental project: no study yet');
 await p.click('nav button[data-v="add"]');await p.waitForTimeout(800);await p.click('[data-at="project"]');await p.waitForTimeout(1200);
 await p.fill('#lsrc',SRC);await p.click('#lscan');await p.waitForTimeout(1200);await shot(p,'R02_bring_in_list');
 const n=await p.$$eval('[data-lk]',e=>e.length);ok(n===4,`4 studies listed in the source project (${n})`);
 for(const c of await p.$$('[data-lk]'))await c.check();
 await p.click('#lgo');await p.waitForTimeout(3500);
 const sheet=async(code,tab)=>{await p.click('nav button[data-v="studies"]');await p.waitForTimeout(1500);await p.click(`tr[data-st="${code}"]`);await p.waitForTimeout(1200);await p.click(`[data-tb="${tab}"]`);await p.waitForTimeout(1500)};
 await sheet('SYN01','technical');await shot(p,'R03_SYN01_found_unknown');
 let t=await p.textContent('#shb');ok(t.includes('8.2.0')&&t.includes('unknown'),'SYN01: linked FreeSurfer shown with version; status unknown until confirmed');
 await p.click('[data-tb="processing"]');await p.waitForTimeout(1500);await p.click('#adopt');await p.waitForTimeout(1800);
 await p.click('[data-tb="technical"]');await p.waitForTimeout(1500);await shot(p,'R04_SYN01_compatibility');
 t=await p.textContent('#shb');ok(t.includes('compatible'),'SYN01 confirmed: compatibility per stage');
 await p.click('[data-tb="processing"]');await p.waitForTimeout(1500);ok((await p.textContent('#pmh')).includes('found on disk'),'SYN01: first run recorded in the history');
 // SWI-only study: fresh detection
 await sheet('SYN02','processing');if(await p.$('#adopt')){await p.click('#adopt');await p.waitForTimeout(1800)}
 await p.click('[data-tb="technical"]');await p.waitForTimeout(1500);t=await p.textContent('#shb');ok(t.includes('not applicable'),'SYN02 (no T1): registration not applicable, not blocking');
 await p.click('[data-tb="processing"]');await p.waitForTimeout(1500);await shot(p,'R05_SYN02_before_run');
 await p.click('[data-c="fresh"]');await p.waitForTimeout(600);await shot(p,'R06_start_confirm');
 await p.click('#dlg button[data-v="yes"]');await p.waitForTimeout(2500);
 await p.click('nav button[data-v="act"]');await p.waitForTimeout(1500);await shot(p,'R07_running');
 ok((await p.textContent('#view')).includes('new detection run'),'Activity lists the running detection run');
 for(let i=0;i<240;i++){await p.waitForTimeout(2500);const a=await p.evaluate(async()=>(await fetch('/api/proc/audit?code=SYN02')).json());if(!a.busy)break}
 await sheet('SYN02','processing');
 const det=await p.$$('[data-det]');if(det.length)await det[0].click();await p.waitForTimeout(1200);await shot(p,'R08_history_after_run');
 t=await p.textContent('#pmh');ok(/completed/.test(t)&&t.includes('★ active'),'SYN02: new run completed and active; history shows both runs');
 ok(/surface|detect_css|candidates/.test(t),'run log visible in the history');
 await p.click('#shx');
 await p.click('nav button[data-v="studies"]');await p.waitForTimeout(2000);await shot(p,'R09_studies');
 ok((await p.textContent('#view')).includes('SYN02'),'linked studies listed in Studies');
 await p.click('#sexp');await p.click('[data-fmt="csv"]');await p.waitForTimeout(800);await shot(p,'R10_export_warning');
 ok((await p.textContent('#dlg')).includes('never uploaded'),'export shows the clinical-data warning first');
 await p.click('#dlg button[data-v="no"]');
 await p.click('nav button[data-v="set"]');await p.waitForTimeout(1000);await p.fill('#xd',process.env.HOME+'/Desktop');await p.click('#save');await p.waitForTimeout(800);await shot(p,'R11_settings_desktop_refused');
 ok((await p.textContent('#toast')).includes('refused'),'Desktop refused as export folder');
 // reviewer + 3-D for the new candidates
 const rv=await p.evaluate(async()=>{const r=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json','X-CSS-App':'1'},body:JSON.stringify({codes:['SYN02'],cohort:''})});return r.json()});
 ok(rv.ok,'reviewer started from the app');
 if(rv.ok){const q=await b.newPage({viewport:{width:1600,height:1000}});q.on('pageerror',e=>errs.push('reviewer: '+e));
  await q.goto(rv.url.replace(/\/$/,'')+'/?study=SYN02&cand=1');await q.waitForTimeout(3500);await q.screenshot({path:`${O}/R12_reviewer_new_candidates.png`});
  const bm=await q.$('#bM3');ok(!!bm,'3-D button present for the new candidate');
  if(bm){await bm.click();await q.waitForTimeout(5000);await q.screenshot({path:`${O}/R13_3d_morphology.png`});
   const tx=await q.evaluate(()=>document.body.innerText);ok(/Volume|Thickness/.test(tx),'3-D panel rendered with morphology measures')}}
 // thick-slice study: fresh detection, then the 3-D explanation of an acquisition-limited candidate
 const api=(u,d)=>p.evaluate(async([u,d])=>{const r=await fetch(u,d?{method:'POST',headers:{'Content-Type':'application/json','X-CSS-App':'1'},body:JSON.stringify(d)}:{});return r.json()},[u,d]);
 await api('/api/proc/adopt',{code:'SYN04'});const s4=await api('/api/proc/start',{code:'SYN04',choice:'selective',rerun_from:'detect'});ok(s4.ok,'SYN04 (2.4 mm slices): new detection run started');
 for(let i=0;i<240;i++){await p.waitForTimeout(2500);const a=await api('/api/proc/audit?code=SYN04');if(!a.busy)break}
 const rv4=await api('/api/review',{codes:['SYN04'],cohort:''});let found=false;
 for(const c of [1,2,3,4]){if(found||!rv4.ok)break;const q=await b.newPage({viewport:{width:1600,height:1100}});q.on('pageerror',e=>errs.push('reviewer: '+e));
  await q.goto(rv4.url.replace(/\/$/,'')+`/?study=SYN04&cand=${c}`);await q.waitForTimeout(3000);const bm=await q.$('#bM3');
  if(bm){await bm.click();await q.waitForTimeout(5000);const tx=await q.evaluate(()=>document.body.innerText);
   if(tx.includes('does not mean absent')){found=true;await q.screenshot({path:`${O}/R14_3d_acquisition_limited_explained.png`})}}
  await q.close()}
 ok(found,'3-D panel explains an acquisition-limited candidate and states that unresolved does not mean absent');
 ok(errs.length===0,'no page errors'+(errs.length?': '+errs.slice(0,3).join(' | '):''));
 await b.close();process.exit(fails?1:0)})();
