"""v5.10 confidence model: css_confidence unit checks + fit_confidence.py + detect_css.py CSS_CONF=1 on copies of the PH3 phantom ($CSS_BASE).
1. unit: a table where one measure separates the classes -> the fitted confidence orders them (AUC 1), is 0..100, explain() names a domain, a foreign schema is refused.
2. fit: PH3's list copied as 5 'patients' with calls from the phantom truth (+ one radiologist-negative hemisphere) -> model file with a cut below every protected cSS.
3. detect with the model: confidence_pct filled; CSS_CONF unset -> nobody excluded by E30; CSS_CONF=1 -> every E30 object is below the cut and no true lesion is lost.
usage: check_confidence.py   (no patient data)"""
import os, sys, json, glob, shutil, subprocess, numpy as np, pandas as pd, nibabel as nib
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); sys.path.insert(0, S); B = os.environ["CSS_BASE"]
import css_confidence as cc, css_model as cm
def fail(m): print("FAIL:", m); sys.exit(1)
rng = np.random.default_rng(0); n = 80; y = (np.arange(n) % 2).astype(int)
df = pd.DataFrame({f: rng.normal(size=n) for f in ("skullbase_frac", "struct_cont", "dark_cv", "minip_cont", "volume_mm3")}); df["volume_mm3"] = 50 + 10 * df.volume_mm3.abs()
df["struct_ctx_frac"] = np.where(y == 1, 0.9, 0.2) + rng.normal(scale=0.05, size=n); df["struct_cls"] = np.where(y == 1, "RIBBON", "TUBE")
m = cc.fit(df, y); p = cc.confidence(m, df)
if cm.auc(y, p) < 0.999 or p.min() < 0 or p.max() > 100: fail(f"unit: AUC {cm.auc(y, p)}, range {p.min()}..{p.max()}")
if not any(k in cc.explain(m, df.iloc[0]) for k in cc.DOMAINS): fail("explain must name an evidence domain")
bad = f"{B}/review/_bad_model.json"; json.dump(dict(m, schema="x"), open(bad, "w"))
try: cc.load(bad); fail("a foreign schema must be refused")
except ValueError: pass
os.remove(bad)
def run(args, **env):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, **env))
    if r.returncode: fail(f"{' '.join(args[-3:])} exit {r.returncode}\n{r.stdout[-700:]}\n{r.stderr[-700:]}")
    return r.stdout
keep = {f: open(f, "rb").read() for f in glob.glob(f"{B}/review/PH3_candidates*") + glob.glob(f"{B}/review/PH3_excluded*")}
made = []
try:
    run([f"{S}/detect_css.py", "PH3"])
    c = pd.read_csv(f"{B}/review/PH3_candidates.csv"); L = np.asanyarray(nib.load(f"{B}/review/PH3_candidates.nii.gz").dataobj).astype(int)
    truth = nib.load(f"{B}/work/PH3_truth.nii.gz").get_fdata().astype(int)
    tl = {int(i) for i in c.cand_id if ((L == i) & (truth > 0)).mean() > 0}
    if len(tl) < 2 or len(c) - len(tl) < 2: fail(f"phantom gives too few of a class: lesions {len(tl)} of {len(c)}")
    x = c[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy(); x["call"] = ["cSS" if int(i) in tl else "Vessel" for i in c.cand_id]; x["comment"] = ""
    ids = [f"Q{k}" for k in range(1, 6)]
    for q in ids:
        for ext in ("candidates.csv", "candidates.nii.gz"): shutil.copy(f"{B}/review/PH3_{ext}", f"{B}/review/{q}_{ext}"); made.append(f"{B}/review/{q}_{ext}")
        x.to_csv(f"{B}/review/{q}_calls_CfT.csv", index=False); made.append(f"{B}/review/{q}_calls_CfT.csv")
    gf = f"{B}/review/_grades.csv"; pd.DataFrame([dict(study_id="Q1", R=0, L=1)]).to_csv(gf, index=False); made.append(gf)
    out = run([f"{S}/fit_confidence.py", ",".join(ids), "--reads", "CfT", "--grades", gf]); made += [f"{B}/review/confidence_fit.csv", f"{B}/review/confidence_fit_summary.txt", f"{B}/review/confidence_model.json"]
    mj = json.load(open(f"{B}/review/confidence_model.json")); fit = pd.read_csv(f"{B}/review/confidence_fit.csv")
    if not (fit[fit.y == 1].confidence_pct >= mj["cut_pct"]).all(): fail("the cut must lie below every protected cSS")
    if not (fit[fit.y == 1].confidence_lopo_pct >= mj["cut_pct"]).all(): fail("the cut must also lie below every leave-one-patient-out confidence of a protected cSS")
    if not (fit[(fit.study_id == "Q1") & (fit.hemi == "R")].y == 0).all(): fail("objects in a radiologist-negative hemisphere must be negatives")
    if "leave-one-patient-out AUC" not in out or "HONEST CHECK" not in out: fail("summary text")
    run([f"{S}/detect_css.py", "PH3"]); a0 = pd.read_csv(f"{B}/review/PH3_candidates.csv")
    if a0.confidence_pct.isna().any() or len(a0) != len(c): fail("with a model file every object gets a confidence and nothing is excluded without CSS_CONF=1")
    run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1"); a1 = pd.read_csv(f"{B}/review/PH3_candidates.csv"); x1 = pd.read_csv(f"{B}/review/PH3_excluded.csv")
    e30 = x1[x1.reason.astype(str).str.startswith("low confidence")] if len(x1) else x1
    if len(e30) and not (e30.confidence_pct < mj["cut_pct"]).all(): fail("E30 excluded an object at or above the cut")
    if (a1.confidence_pct < mj["cut_pct"]).any(): fail("an object below the cut is still shown with CSS_CONF=1")
    L1 = np.asanyarray(nib.load(f"{B}/review/PH3_candidates.nii.gz").dataobj).astype(int)
    lost = [k for k in np.unique(truth[truth > 0]) if ((truth == k) & (L > 0)).any() and not ((truth == k) & (L1 > 0)).any()]
    if lost: fail(f"CSS_CONF=1 lost true lesions {lost}")
    # side guard: a cut above every object would empty both hemispheres -> each side keeps exactly its highest-confidence object; CSS_CONF_GUARD=0 -> none
    json.dump(dict(mj, cut_pct=101.0), open(f"{B}/review/confidence_model.json", "w"))
    run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1"); g1 = pd.read_csv(f"{B}/review/PH3_candidates.csv")
    sides = set(a0.hemi)
    if set(g1.hemi) != sides or len(g1) != len(sides) or not (g1.conf_guard == 1).all(): fail(f"side guard: {g1[['cand_id', 'hemi', 'confidence_pct', 'conf_guard']]}")
    for h in sides:
        if float(g1[g1.hemi == h].confidence_pct.iloc[0]) != float(a0[a0.hemi == h].confidence_pct.max()): fail(f"side guard must keep the highest-confidence object of side {h}")
    run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1", CSS_CONF_GUARD="0"); g0 = pd.read_csv(f"{B}/review/PH3_candidates.csv")
    if len(g0): fail("with CSS_CONF_GUARD=0 the cut above every object must remove them all")
    print(f"side guard: cut above everything keeps 1 object per side ({sorted(sides)}), off -> 0")
    print(f"confidence: unit AUC 1.00; fit on 5 phantom patients, cut {mj['cut_pct']} %, LOPO AUC {mj['lopo_auc']}; detect: {len(a0)} shown -> {len(a1)} with CSS_CONF=1 ({len(e30)} low confidence), no true lesion lost")
finally:
    for f in made:
        if os.path.exists(f): os.remove(f)
    for f, b in keep.items(): open(f, "wb").write(b)
    run([f"{S}/detect_css.py", "PH3"])
print("RESULT confidence OK")
