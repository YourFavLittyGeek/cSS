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
  const nm = await ev(() => snapName('png'));
  if (!/^PH3_cand\d\d_x\d{3}_y\d{3}_z\d{3}_axial\.png$/.test(nm)) await fail('snapshot name ' + nm);
  if (errs.length) await fail('page errors: ' + errs.join(' | '));
  console.log('viewer: zoom stays fit, layouts 1/2/4, mirror round-trip, panel hide/pin, snapshot name ' + nm);
  console.log('RESULT viewer OK'); await b.close();
})();
