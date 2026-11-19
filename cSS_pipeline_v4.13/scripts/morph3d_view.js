// morph3d_view.js - 3-D morphology viewer for ONE candidate (served by review_web.py at /morph3d.js).
// WebGL 1, no libraries. Data: /api/morph3d (css_morph3d.py). Coordinates: mm, canonical RAS+ (x right, y anterior,
// z superior), origin = candidate centroid. Read-only: nothing here changes the candidate or any detector output.
"use strict";
const M3 = (() => {
  const COL = { tube: [0.29, 0.64, 1.0], sheet: [0.94, 0.63, 0.25], blob: [0.78, 0.49, 1.0], unc: [0.55, 0.56, 0.6],
    cand: [0.95, 0.62, 0.28], vessel: [0.29, 0.64, 1.0], vconn: [0.15, 0.45, 1.0], cortex: [0.62, 0.64, 0.68], dark: [0.42, 0.42, 0.45],
    skel: [1, 1, 1], branch: [1, 0.3, 0.3], marker: [1, 0.92, 0.2], foot: [0.36, 0.85, 0.5], contact: [1, 0.2, 0.6], slab: [1, 1, 1] };
  const CLS = ["tube", "sheet", "blob", "unc"];
  let gl, cv, P = {}, D = null, onPick = null, marker = null, buf = {}, opts = null, cam = { yaw: -0.7, pitch: 0.45, dist: 60, tx: 0, ty: 0, tz: 0, fov: 0.6 };
  const VS_L = `attribute vec3 p;attribute vec3 n;attribute vec3 c;uniform mat4 M;uniform float ps;varying vec3 vn;varying vec3 vc;
    void main(){vn=n;vc=c;gl_Position=M*vec4(p,1.0);gl_PointSize=ps;}`;
  const FS_L = `precision mediump float;varying vec3 vn;varying vec3 vc;uniform float a;uniform float lit;uniform vec3 L;
    void main(){float d=lit>0.5?0.35+0.65*abs(dot(normalize(vn),L)):1.0;gl_FragColor=vec4(vc*d,a);}`;
  const VS_T = `attribute vec3 p;attribute vec2 t;uniform mat4 M;varying vec2 vt;void main(){vt=t;gl_Position=M*vec4(p,1.0);}`;
  const FS_T = `precision mediump float;varying vec2 vt;uniform sampler2D s;uniform float a;void main(){float g=texture2D(s,vt).r;gl_FragColor=vec4(g,g,g,a);}`;
  function prog(vs, fs) {
    const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o };
    const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); return p;
  }
  // ---------------------------------------------------------------- matrices
  const mul = (a, b) => { const o = new Float32Array(16); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s } return o };
  function viewMat() {
    const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
    const eye = [cam.tx + cam.dist * cp * cy, cam.ty + cam.dist * cp * sy, cam.tz + cam.dist * sp];
    const f = norm([cam.tx - eye[0], cam.ty - eye[1], cam.tz - eye[2]]), up = [0, 0, 1];
    let s = norm(cross(f, up)); if (!isFinite(s[0]) || Math.hypot(...cross(f, up)) < 1e-6) s = [1, 0, 0];
    const u = cross(s, f);
    return new Float32Array([s[0], u[0], -f[0], 0, s[1], u[1], -f[1], 0, s[2], u[2], -f[2], 0, -dot(s, eye), -dot(u, eye), dot(f, eye), 1]);
  }
  function projMat() { const a = cv.width / cv.height, f = 1 / Math.tan(cam.fov / 2), n = 0.5, fr = 2000;
    return new Float32Array([f / a, 0, 0, 0, 0, f, 0, 0, 0, 0, (fr + n) / (n - fr), -1, 0, 0, 2 * fr * n / (n - fr), 0]) }
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l] };
  // ---------------------------------------------------------------- geometry helpers
  function meshNormals(v, f) { const n = new Float32Array(v.length);
    for (let i = 0; i < f.length; i += 3) { const a = f[i] * 3, b = f[i + 1] * 3, c = f[i + 2] * 3;
      const e1 = [v[b] - v[a], v[b + 1] - v[a + 1], v[b + 2] - v[a + 2]], e2 = [v[c] - v[a], v[c + 1] - v[a + 1], v[c + 2] - v[a + 2]], x = cross(e1, e2);
      for (const k of [a, b, c]) { n[k] += x[0]; n[k + 1] += x[1]; n[k + 2] += x[2] } }
    return n }
  function upload(key, pos, nrm, col, idx) { const b = buf[key] || (buf[key] = {}); const mk = (d, t) => { const o = gl.createBuffer(); gl.bindBuffer(t, o); gl.bufferData(t, d, gl.STATIC_DRAW); return o };
    for (const k of ["p", "n", "c", "i"]) if (b[k]) gl.deleteBuffer(b[k]);
    b.p = mk(new Float32Array(pos), gl.ARRAY_BUFFER); b.n = mk(nrm ? new Float32Array(nrm) : new Float32Array(pos.length), gl.ARRAY_BUFFER);
    b.c = mk(new Float32Array(col), gl.ARRAY_BUFFER); b.cnt = idx ? idx.length : pos.length / 3;
    if (idx) { b.u32 = pos.length / 3 > 65535; b.i = mk(b.u32 ? new Uint32Array(idx) : new Uint16Array(idx), gl.ELEMENT_ARRAY_BUFFER) }
    else b.i = null; return b }
  function cubes(points, size, colors) { // voxel representation: one box per voxel (exact mask, physical voxel size)
    const pos = [], nrm = [], col = [], idx = []; const [hx, hy, hz] = size.map(s => s / 2 * 0.96);
    const F = [[[1, 0, 0], [[1, -1, -1], [1, 1, -1], [1, 1, 1], [1, -1, 1]]], [[-1, 0, 0], [[-1, -1, -1], [-1, -1, 1], [-1, 1, 1], [-1, 1, -1]]],
      [[0, 1, 0], [[-1, 1, -1], [-1, 1, 1], [1, 1, 1], [1, 1, -1]]], [[0, -1, 0], [[-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1]]],
      [[0, 0, 1], [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]], [[0, 0, -1], [[-1, -1, -1], [-1, 1, -1], [1, 1, -1], [1, -1, -1]]]];
    points.forEach((p, k) => { for (const [n, q] of F) { const b = pos.length / 3; for (const c of q) { pos.push(p[0] + c[0] * hx, p[1] + c[1] * hy, p[2] + c[2] * hz); nrm.push(...n); col.push(...colors[k]) } idx.push(b, b + 1, b + 2, b, b + 2, b + 3) } });
    return { pos, nrm, col, idx } }
  function tex(plane) { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    const raw = atob(plane.data), a = new Uint8Array(raw.length); for (let i = 0; i < raw.length; i++) a[i] = raw.charCodeAt(i);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE, plane.nu, plane.nv, 0, gl.LUMINANCE, gl.UNSIGNED_BYTE, a);
    for (const p of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, p, gl.LINEAR);
    for (const p of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D, p, gl.CLAMP_TO_EDGE); return t }
  // ---------------------------------------------------------------- colours of the candidate
  function ramp(t) { t = Math.max(0, Math.min(1, t)); return [0.2 + 0.8 * t, 0.35 + 0.5 * Math.sin(Math.PI * t), 1 - 0.85 * t] }
  function voxColor(k) { const V = D.voxels, m = opts.color;
    if (m === "geometry") return COL[CLS[V.gcls[k]]];
    if (m === "hessian") return V.hcls ? COL[CLS[V.hcls[k]]] : COL.unc;
    if (m === "thickness") { const t = D.measures.thickness_mm; return ramp((V.thick[k] - t.p10) / Math.max(t.p90 - t.p10, 0.1)) }
    if (m === "component") { const c = V.comp[k]; return [[0.95, 0.62, 0.28], [0.4, 0.85, 0.55], [0.95, 0.4, 0.6], [0.7, 0.7, 0.3], [0.5, 0.75, 0.95]][(c - 1) % 5] }
    return COL.cand }
  const compOn = k => !opts.comp || opts.comp.has(D.voxels.comp[k]);
  function build() { // (re)build the GPU buffers from D and opts
    const V = D.voxels, nv = V.p.length;
    // A. original voxels (exact mask)
    const keep = [...Array(nv).keys()].filter(compOn);
    const cb = cubes(keep.map(k => V.p[k]), D.vox, keep.map(k => voxColor(k))); upload("vox", cb.pos, cb.nrm, cb.col, cb.idx);
    // B. reconstructed surface (display copy, Taubin-smoothed), coloured by the nearest voxel
    const m = D.mesh; if (m.f.length) { const col = new Array(m.v.length), f = [];
      for (let i = 0; i < m.vi.length; i++) { const c = voxColor(m.vi[i]); col[3 * i] = c[0]; col[3 * i + 1] = c[1]; col[3 * i + 2] = c[2] }
      for (let i = 0; i < m.f.length; i += 3) if (compOn(m.vi[m.f[i]]) && compOn(m.vi[m.f[i + 1]]) && compOn(m.vi[m.f[i + 2]])) f.push(m.f[i], m.f[i + 1], m.f[i + 2]);
      upload("surf", m.v, meshNormals(m.v, m.f), col, f) }
    for (const [k, key, c] of [["vessel_mesh", "ves", COL.vessel], ["vessel_conn_mesh", "vconn", COL.vconn], ["cortex_mesh", "ctx", COL.cortex], ["dark_mesh", "dark", COL.dark]]) {
      const o = D[k]; if (o && o.f.length) upload(key, o.v, meshNormals(o.v, o.f), new Array(o.v.length).fill(0).map((_, i) => c[i % 3]), o.f); else delete buf[key] }
    const pts = (key, arr, c) => { if (arr && arr.length) upload(key, arr.flat(), null, arr.map(() => c).flat(), null); else delete buf[key] };
    pts("skel", D.skeleton, COL.skel); pts("branch", D.branch, COL.branch); pts("foot", D.footprint, COL.foot); pts("contact", D.contact, COL.contact);
    const slabPts = opts.slab >= 0 && V.slab.length ? V.p.filter((_, k) => V.slab[k] === opts.slab) : []; pts("slab", slabPts, COL.slab);
    // principal axes (2 sd each way), drawn as lines
    const ax = D.measures.pca_axes, sd = D.measures.pca_sd_mm, L = [];
    ax.forEach((a, i) => { const s = 2 * sd[i]; L.push(-a[0] * s, -a[1] * s, -a[2] * s, a[0] * s, a[1] * s, a[2] * s) });
    upload("pca", L, null, [1, .3, .3, 1, .3, .3, .3, 1, .3, .3, 1, .3, .4, .6, 1, .4, .6, 1], null);
    if (!P.tex) P.tex = D.planes.map(tex);
  }
  function quad(pl) { const [u, v] = pl.uv, w = pl.axis, q = []; const C = (uu, vv) => { const p = [0, 0, 0]; p[u] = uu; p[v] = vv; p[w] = pl.at_mm; return p };
    return [C(pl.u0, pl.v0), C(pl.u1, pl.v0), C(pl.u1, pl.v1), C(pl.u0, pl.v0), C(pl.u1, pl.v1), C(pl.u0, pl.v1)].flat() }
  // ---------------------------------------------------------------- draw
  function draw() { if (!gl || !D) return; const W = cv.clientWidth, H = cv.clientHeight; if (cv.width !== W * devicePixelRatio) { cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio }
    gl.viewport(0, 0, cv.width, cv.height); const bg = opts.light ? [0.96, 0.96, 0.97] : [0.06, 0.07, 0.09]; gl.clearColor(bg[0], bg[1], bg[2], 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); const MV = mul(projMat(), viewMat()); P.MV = MV;
    gl.useProgram(P.l); gl.uniformMatrix4fv(P.lM, false, MV); const ey = viewMat(); gl.uniform3fv(P.lL, norm([-ey[2], -ey[6], -ey[10]]).map(x => -x));
    const draw1 = (key, mode, alpha, lit, ps) => { const b = buf[key]; if (!b) return; gl.uniform1f(P.la, alpha); gl.uniform1f(P.llit, lit); gl.uniform1f(P.lps, ps || 1);
      for (const [att, k, n] of [[P.ap, "p", 3], [P.an, "n", 3], [P.ac, "c", 3]]) { gl.bindBuffer(gl.ARRAY_BUFFER, b[k]); gl.enableVertexAttribArray(att); gl.vertexAttribPointer(att, n, gl.FLOAT, false, 0, 0) }
      if (b.i) { gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b.i); gl.drawElements(mode, b.cnt, b.u32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, 0) } else gl.drawArrays(mode, 0, b.cnt) };
    const ctxMode = opts.mode === "context", L = opts.layers;
    // opaque first: candidate
    if (opts.rep !== "voxels") draw1("surf", gl.TRIANGLES, 1, 1);
    if (opts.rep !== "surface") draw1("vox", gl.TRIANGLES, 1, 1);
    if (L.skeleton) { gl.disable(gl.DEPTH_TEST); draw1("skel", gl.POINTS, 1, 0, 4 * devicePixelRatio); draw1("branch", gl.POINTS, 1, 0, 9 * devicePixelRatio); gl.enable(gl.DEPTH_TEST) }
    if (L.pca) { gl.disable(gl.DEPTH_TEST); draw1("pca", gl.LINES, 1, 0); gl.enable(gl.DEPTH_TEST) }
    if (opts.slab >= 0) { gl.disable(gl.DEPTH_TEST); draw1("slab", gl.POINTS, 1, 0, 5 * devicePixelRatio); gl.enable(gl.DEPTH_TEST) }
    if (L.contact) draw1("contact", gl.POINTS, 1, 0, 6 * devicePixelRatio);
    if (L.footprint) draw1("foot", gl.POINTS, 1, 0, 3 * devicePixelRatio);
    if (marker) { upload("mk", marker.flat(), null, marker.map(() => COL.marker).flat(), null); gl.disable(gl.DEPTH_TEST); draw1("mk", gl.LINES, 1, 0); gl.enable(gl.DEPTH_TEST) }
    // translucent context last (never hides the candidate: depth write off)
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
    if (L.vessel) { draw1("ves", gl.TRIANGLES, 0.55, 1); draw1("vconn", gl.TRIANGLES, 0.8, 1) }
    if (L.dark) draw1("dark", gl.TRIANGLES, 0.22, 1);
    if (L.cortex) draw1("ctx", gl.TRIANGLES, 0.08, 1);
    if (L.mri) { gl.useProgram(P.t); gl.uniformMatrix4fv(P.tM, false, MV); gl.uniform1f(P.ta, 0.85);
      D.planes.forEach((pl, i) => { if (!L.mri[pl.name]) return; const q = quad(pl), t = [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1];
        const b1 = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b1); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(q), gl.STREAM_DRAW); gl.enableVertexAttribArray(P.tp); gl.vertexAttribPointer(P.tp, 3, gl.FLOAT, false, 0, 0);
        const b2 = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b2); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(t), gl.STREAM_DRAW); gl.enableVertexAttribArray(P.tt); gl.vertexAttribPointer(P.tt, 2, gl.FLOAT, false, 0, 0);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, P.tex[i]); gl.uniform1i(P.ts, 0); gl.drawArrays(gl.TRIANGLES, 0, 6); gl.deleteBuffer(b1); gl.deleteBuffer(b2) });
      gl.disableVertexAttribArray(P.tp); gl.disableVertexAttribArray(P.tt) }
    gl.depthMask(true); gl.disable(gl.BLEND);
    if (opts.onDraw) opts.onDraw();
  }
  // ---------------------------------------------------------------- camera
  function fit() { const V = D.voxels.p; let r = 4; for (const p of V) r = Math.max(r, Math.hypot(p[0], p[1], p[2]));
    if (opts.mode === "context") r = Math.max(r, D.margin_mm + r * 0.6);
    cam.tx = cam.ty = cam.tz = 0; cam.dist = r / Math.sin(cam.fov / 2) * 1.08; draw() }
  function view(k) { // camera from the named side (canonical axes: x right, y anterior, z superior)
    const Vw = { R: [0, 0], L: [Math.PI, 0], A: [Math.PI / 2, 0], P: [-Math.PI / 2, 0], S: [-Math.PI / 2, 1.55], I: [-Math.PI / 2, -1.55] }[k];
    // the most informative start: look along the THINNEST principal axis so a sheet is seen face-on, a tube side-on
    if (k === "best") { const a = D.measures.pca_axes[2]; cam.yaw = Math.atan2(a[1], a[0]); cam.pitch = Math.asin(Math.max(-1, Math.min(1, a[2]))) * 0.9; fit(); return }
    cam.yaw = Vw[0]; cam.pitch = Vw[1]; fit() }
  function bind() { let d = null, moved = 0;
    cv.addEventListener("pointerdown", e => { d = [e.clientX, e.clientY, e.button, e.shiftKey]; moved = 0; cv.setPointerCapture(e.pointerId) });
    cv.addEventListener("pointermove", e => { if (!d) return; const dx = e.clientX - d[0], dy = e.clientY - d[1]; moved += Math.abs(dx) + Math.abs(dy); d[0] = e.clientX; d[1] = e.clientY;
      if (d[2] === 2 || d[3]) { const s = cam.dist * 0.0018, v = viewMat(); for (let i = 0; i < 3; i++) { const r = [v[0], v[4], v[8]][i], u = [v[1], v[5], v[9]][i]; cam[["tx", "ty", "tz"][i]] -= (r * dx - u * dy) * s } }
      else { cam.yaw -= dx * 0.01; cam.pitch = Math.max(-1.55, Math.min(1.55, cam.pitch + dy * 0.01)) } draw() });
    cv.addEventListener("pointerup", e => { if (d && moved < 5 && d[2] === 0) pick(e); d = null });
    cv.addEventListener("contextmenu", e => e.preventDefault());
    cv.addEventListener("wheel", e => { e.preventDefault(); cam.dist *= e.deltaY < 0 ? 0.9 : 1.11; draw() }, { passive: false });
    cv.addEventListener("dblclick", () => view("best")) }
  function pick(e) { // nearest candidate voxel on screen -> the MRI slices jump there
    const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * 2 - 1, y = 1 - (e.clientY - r.top) / r.height * 2, M = P.MV; let best = -1, bd = 1e9, bz = 1e9;
    D.voxels.p.forEach((p, k) => { if (!compOn(k)) return; const w = M[3] * p[0] + M[7] * p[1] + M[11] * p[2] + M[15]; if (w <= 0) return;
      const sx = (M[0] * p[0] + M[4] * p[1] + M[8] * p[2] + M[12]) / w, sy = (M[1] * p[0] + M[5] * p[1] + M[9] * p[2] + M[13]) / w, sz = (M[2] * p[0] + M[6] * p[1] + M[10] * p[2] + M[14]) / w;
      const dd = Math.hypot((sx - x) * r.width / 2, (sy - y) * r.height / 2); if (dd < 10 && (dd < bd - 3 || (dd < bd + 3 && sz < bz))) { bd = dd; bz = sz; best = k } });
    if (best >= 0 && onPick) onPick(D.voxels.idx[best], best) }
  // ---------------------------------------------------------------- public
  function init(canvas, o) { cv = canvas; gl = cv.getContext("webgl", { antialias: true, preserveDrawingBuffer: true }); if (!gl) throw new Error("WebGL is not available");
    gl.getExtension("OES_element_index_uint");
    P.l = prog(VS_L, FS_L); P.ap = gl.getAttribLocation(P.l, "p"); P.an = gl.getAttribLocation(P.l, "n"); P.ac = gl.getAttribLocation(P.l, "c");
    P.lM = gl.getUniformLocation(P.l, "M"); P.la = gl.getUniformLocation(P.l, "a"); P.llit = gl.getUniformLocation(P.l, "lit"); P.lL = gl.getUniformLocation(P.l, "L"); P.lps = gl.getUniformLocation(P.l, "ps");
    P.t = prog(VS_T, FS_T); P.tp = gl.getAttribLocation(P.t, "p"); P.tt = gl.getAttribLocation(P.t, "t"); P.tM = gl.getUniformLocation(P.t, "M"); P.ta = gl.getUniformLocation(P.t, "a"); P.ts = gl.getUniformLocation(P.t, "s");
    opts = o; bind(); new ResizeObserver(() => draw()).observe(cv) }
  function load(data, pickCb) { D = data; onPick = pickCb; for (const k in buf) delete buf[k]; P.tex = null; opts.slab = -1; opts.comp = null; build(); view("best") }
  function setMarker(idxVox) { if (!D) return; if (!idxVox) { marker = null; draw(); return }
    const c = D.centroid_vox, v = D.vox, p = [0, 1, 2].map(i => (idxVox[i] - c[i]) * v[i]), s = 2.5;
    marker = [[p[0] - s, p[1], p[2]], [p[0] + s, p[1], p[2]], [p[0], p[1] - s, p[2]], [p[0], p[1] + s, p[2]], [p[0], p[1], p[2] - s], [p[0], p[1], p[2] + s]]; draw() }
  return { init, load, draw, rebuild: () => { if (D) { build(); draw() } }, view, fit, setMarker, data: () => D, COL, CLS };
})();
