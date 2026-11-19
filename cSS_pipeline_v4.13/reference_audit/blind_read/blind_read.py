"""Blind whole-scan reader (pathway A). Opens ONLY the blinded case folders of a whole-scan packet - never the detector lists,
masks, scores, the meter or the case key - so a read here is blind to production by construction.
usage: python reference_audit/blind_read/blind_read.py PACKET READER [--port 8790] [--no-browser]
Serves http://127.0.0.1:<port>/ (this computer only). Every change is saved at once to
  whole_scan/<PACKET>/lesion_annotations_<READER>.csv  and  patient_annotations_<READER>.csv   (schema of annotation_schema.py)
plus an append-only blind_read_log_<READER>.csv. Rows of other cases are never touched."""
import sys, os, io, json, csv, time, threading, webbrowser, numpy as np, pandas as pd, nibabel as nib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import ra_common as R
from annotation_schema import LESION_COLUMNS, PATIENT_COLUMNS, ALLOWED

a = sys.argv[1:]
if len(a) < 2: sys.exit(__doc__)
PK, RD = a[0], a[1]; PORT = int(a[a.index("--port") + 1]) if "--port" in a else 8790
D = os.path.join(R.OUT, "whole_scan", PK); CASES = os.path.join(D, "cases")
if not os.path.isdir(CASES): sys.exit(f"no packet {D}")
LF, PF, LOG = f"{D}/lesion_annotations_{RD}.csv", f"{D}/patient_annotations_{RD}.csv", f"{D}/blind_read_log_{RD}.csv"
ORDER = f"{D}/reading_order_{RD}.csv"
codes = list(pd.read_csv(ORDER).case_code) if os.path.exists(ORDER) else sorted(os.listdir(CASES))
SEQ_ORDER = ["SWI", "FLAIR_on_SWI", "FLAIR", "T1", "PHASE", "GRE"]
cache = {}

def seqs(code):
    fs = os.listdir(f"{CASES}/{code}"); out = []
    for s in SEQ_ORDER:
        for ext in (".nii", ".nii.gz"):
            if s + ext in fs: out.append((s, s + ext))
    return out

def volume(code, seq):
    k = (code, seq)
    if k not in cache:
        if len(cache) > 6: cache.pop(next(iter(cache)))
        fn = dict(seqs(code))[seq]; img = nib.load(f"{CASES}/{code}/{fn}"); I = np.asarray(img.dataobj, np.float32)
        if I.ndim > 3: I = I[..., 0]
        nz = I[np.isfinite(I) & (I != 0)]; lo, hi = (np.percentile(nz, [0.5, 99.5]) if len(nz) else (0, 1))
        U = np.clip((I - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
        A = img.affine; vox = [float(v) for v in img.header.get_zooms()[:3]]
        cache[k] = dict(U=U, meta=dict(shape=list(U.shape), vox=vox, affine=A.tolist(),
                         # +i towards patient left? (RAS x increases to the right) -> used for radiological display
                         i_to_right=bool(A[0, 0] > 0)))
    return cache[k]

def read_rows(fn, cols):
    return pd.read_csv(fn, dtype=str).fillna("").reindex(columns=cols, fill_value="") if os.path.exists(fn) else pd.DataFrame(columns=cols)

def write_case(fn, cols, code, rows):
    old = read_rows(fn, cols); old = old[old.patient_id != code]
    new = pd.DataFrame(rows).reindex(columns=cols, fill_value="") if rows else pd.DataFrame(columns=cols)
    for c in new.columns: new[c] = new[c].astype(str).replace({"None": "", "nan": ""})
    pd.concat([old, new], ignore_index=True).to_csv(fn + ".tmp", index=False); os.replace(fn + ".tmp", fn)

def log(event, code, detail):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["time_utc", "reader", "event", "case", "detail"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), RD, event, code, detail])

class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def _send(self, obj, code=200, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/": return self._send(open(f"{HERE}/blind_read.html", "rb").read(), ctype="text/html; charset=utf-8")
            if u.path == "/api/session":
                L = read_rows(LF, LESION_COLUMNS); P = read_rows(PF, PATIENT_COLUMNS)
                st = [dict(code=c, n_lesions=int((L.patient_id == c).sum()), patient_done=bool((P.patient_id == c).any())) for c in codes]
                return self._send(dict(packet=PK, reader=RD, cases=st, allowed=ALLOWED, lesion_columns=LESION_COLUMNS, patient_columns=PATIENT_COLUMNS))
            if u.path == "/api/case":
                c = q["case"]; assert c in codes
                L = read_rows(LF, LESION_COLUMNS); P = read_rows(PF, PATIENT_COLUMNS)
                return self._send(dict(code=c, seqs=[s for s, _ in seqs(c)], lesions=L[L.patient_id == c].to_dict("records"),
                                       patient=(P[P.patient_id == c].to_dict("records") or [None])[0]))
            if u.path == "/api/meta": return self._send(volume(q["case"], q["seq"])["meta"])
            if u.path == "/api/vol":
                v = volume(q["case"], q["seq"]); return self._send(np.ascontiguousarray(v["U"].transpose(2, 1, 0)).tobytes(), ctype="application/octet-stream")
            return self._send(dict(error="not found"), 404)
        except Exception as e: return self._send(dict(error=f"{type(e).__name__}: {e}"), 500)
    def do_POST(self):
        u = urlparse(self.path)
        if self.headers.get("X-Blind") != "1": return self._send(dict(error="missing header"), 403)
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            c = d["case"]; assert c in codes
            if u.path == "/api/lesions":
                rows = [dict(r, reader_id=RD, patient_id=c, read_session=r.get("read_session") or "1") for r in d["lesions"]]
                write_case(LF, LESION_COLUMNS, c, rows); log("save_lesions", c, f"{len(rows)} lesions"); return self._send(dict(ok=True, n=len(rows)))
            if u.path == "/api/patient":
                r = dict(d["patient"], reader_id=RD, patient_id=c, read_session=d["patient"].get("read_session") or "1")
                write_case(PF, PATIENT_COLUMNS, c, [r]); log("save_patient", c, json.dumps({k: r.get(k, "") for k in ("css_present_L", "css_present_R")}))
                return self._send(dict(ok=True))
            return self._send(dict(error="not found"), 404)
        except Exception as e: return self._send(dict(error=f"{type(e).__name__}: {e}"), 500)

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H); url = f"http://127.0.0.1:{PORT}/"
    print(f"blind read {PK} / reader {RD}: {url}  (images only - no detector output; Ctrl+C to stop; saves as you go)", flush=True)
    log("start", "", url)
    if "--no-browser" not in a: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nstopped; everything was saved as you went")
