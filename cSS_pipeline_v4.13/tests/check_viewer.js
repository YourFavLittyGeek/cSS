// Browser checks of the reviewer (Playwright). usage: node tests/check_viewer.js URL     (server must be running on PH3)
// zoom stays at fit when moving between candidates, layouts 1/2/4, mirror round-trip keeps clicks on the right voxel,
// panel hide / auto-hide / pin, snapshot file name. Prints "RESULT viewer OK" or "FAIL: ...".
const {chromium} = require('playwright');
(async () => {
  const U = process.argv[2]; const b = await chromium.launch(); const pg = await b.newPage({viewport: {width: 1400, height: 860}});
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  const fail = async m => { console.log('FAIL: ' + m); await b.close(); process.exit(1); };
  const ev = f => pg.evaluate(f);
  await pg.goto(U); await pg.fill('#reviewer', 'Viewer Test'); await pg.dispatchEvent('#reviewer', 'change');
  for (let i = 0; i < 60; i++) { await pg.waitForTimeout(500); if (await ev(() => !!(M && vols.swi && panes[0].ready))) break; }
  await ev(() => document.activeElement.blur());
  if (await ev(() => zoom) !== 1) await fail('start zoom is not fit');
  await pg.keyboard.press('ArrowRight'); await pg.waitForTimeout(300);
  if (await ev(() => zoom) !== 1) await fail('zoom changed when moving to the next candidate');
  for (const [k, n] of [['Backslash', 2], ['Backslash', 4], ['Backslash', 1]]) { await pg.keyboard.press(k); await pg.waitForTimeout(250); if (await ev(() => panes.length) !== n) await fail('layout ' + n); }
  const rt = await ev(() => { const p = panes[0], g = geom(p), [x, y] = toScrG(g, cand().centre); return JSON.stringify([toVox(p, x, y), cand().centre]); });
  await pg.keyboard.press('Shift+H'); await pg.waitForTimeout(250);
  const rt2 = await ev(() => { const p = panes[0], g = geom(p), [x, y] = toScrG(g, cand().centre); return JSON.stringify([toVox(p, x, y), cand().centre, mir]); });
  const a = JSON.parse(rt), c = JSON.parse(rt2);
  if (JSON.stringify(a[0]) !== JSON.stringify(a[1]) || JSON.stringify(c[0]) !== JSON.stringify(c[1]) || c[2] !== true) await fail('mirror round-trip ' + rt + ' ' + rt2);
  await pg.keyboard.press('Shift+H');
  await pg.keyboard.press('Space'); await pg.waitForTimeout(250);
  if (await ev(() => getComputedStyle($('#panel')).display) !== 'none' || await ev(() => getComputedStyle($('#rail')).display) === 'none') await fail('Space must hide the panel and show the rail');
  await pg.click('#rail [data-r=pin]'); await pg.waitForTimeout(250);
  if (await ev(() => getComputedStyle($('#panel')).display) === 'none') await fail('pin must show the panel');
  // v5.7-B: theme switch with symbols (click + drag), validation symbol, decision buttons not cut
  const th0 = await ev(() => document.documentElement.dataset.theme);
  await pg.click('#themes span[data-t=light]'); if (await ev(() => document.documentElement.dataset.theme) !== 'light') await fail('theme symbol click');
  const bx = await pg.locator('#themes').boundingBox(); await pg.mouse.move(bx.x + 50, bx.y + 15); await pg.mouse.down(); await pg.mouse.move(bx.x + 12, bx.y + 15, {steps: 4}); await pg.mouse.up();
  if (await ev(() => document.documentElement.dataset.theme) !== 'dark') await fail('theme knob drag to the moon');
  await ev(t => theme(t), th0);
  const cut = await ev(() => [...document.querySelectorAll('#dec .b')].filter(b => b.scrollWidth > b.clientWidth + 1).map(b => b.textContent));
  if (cut.length) await fail('decision buttons cut: ' + cut.join(','));
  if (await ev(() => !!document.querySelector('#vbadge'))) await fail('the text badge must be gone');
  const nm = await ev(() => snapName('png'));
  if (!/^PH3_cand\d\d_x\d{3}_y\d{3}_z\d{3}_axial\.png$/.test(nm)) await fail('snapshot name ' + nm);
  if (errs.length) await fail('page errors: ' + errs.join(' | '));
  console.log('viewer: zoom stays fit, layouts 1/2/4, mirror round-trip, panel hide/pin, snapshot name ' + nm);
  // v5.9: 3-D shape card visible by default, draws a non-blank canvas, key 3 hides / shows it, the choice is remembered
  await ev(() => document.activeElement.blur());
  if (await ev(() => getComputedStyle($('#s3body')).display) === 'none') await fail('3-D card must be visible by default');
  let nz = 0; for (let i = 0; i < 40 && !nz; i++) { await pg.waitForTimeout(500); nz = await ev(() => { const c = $('#s3cv'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let k = 3; k < d.length; k += 4) if (d[k] > 0) n++; return n; }); }
  if (!nz) await fail('3-D canvas stays empty');
  const r0 = await ev(() => s3.ry); const cb = await pg.locator('#s3cv').boundingBox(); await pg.mouse.move(cb.x + 60, cb.y + 60); await pg.mouse.down(); await pg.mouse.move(cb.x + 120, cb.y + 60, {steps: 4}); await pg.mouse.up();
  if (await ev(() => s3.ry) === r0) await fail('dragging the 3-D canvas must rotate it');
  await pg.keyboard.press('3'); await pg.waitForTimeout(300);
  if (await ev(() => getComputedStyle($('#s3body')).display) !== 'none' || await ev(() => localStorage.getItem('css_s3')) !== 'false') await fail('key 3 must hide the 3-D card and remember it');
  await pg.keyboard.press('3'); await pg.waitForTimeout(300);
  if (await ev(() => getComputedStyle($('#s3body')).display) === 'none') await fail('key 3 must show the 3-D card again');
  console.log('3-D card: visible by default, drawn, rotates, hide / show with key 3');
  console.log('RESULT viewer OK'); await b.close();
})();
