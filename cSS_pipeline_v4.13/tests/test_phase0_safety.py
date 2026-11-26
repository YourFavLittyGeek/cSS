"""Phase 0 safety regression tests (S1-S14 of docs/engineering/PHASE0_SAFETY_PLAN.md).

Synthetic files in temporary directories only (tests/_isolation.py). No real MRI, no real Vault, no diskutil."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from uengine import safety as SF                                     # noqa: E402
from uengine import unified_transfer_engine as UTE                   # noqa: E402
from uengine.file_manager import FileManager                         # noqa: E402
from uengine.cleaning_manager import CleaningManager                 # noqa: E402
from uengine.study_workspace_manager import StudyWorkspaceManager    # noqa: E402
from uengine.storage.storage_paths import StoragePathsService        # noqa: E402
from uengine.storage.sync_manager import SyncManager                 # noqa: E402
from uengine.storage import eject_manager as EJ                      # noqa: E402
from uengine.storage.models import VolumeInfo, DriveSafetyState      # noqa: E402


def _w(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Project:
    """a synthetic project base + Vault with every protected category populated"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="p0_")
        self.base = os.path.join(self.tmp, "proj")
        self.vroot = os.path.join(self.tmp, "Volumes", "Percival")
        self.vault = os.path.join(self.vroot, "PERCIVAL_VAULT")
        b, v = self.base, self.vault
        self.raw = _w(os.path.join(b, "raw", "M01", "SWI", "swi.nii"), b"RAW-ORIGINAL")
        self.preserved = _w(os.path.join(b, "raw", "import_source_preserved", "M30", "a.dcm"), b"DCM")
        self.data = _w(os.path.join(b, "data", "M01_swi.nii"), b"DATA-SWI")
        self.import_src = _w(os.path.join(b, "app_data", "import_src", "STUDY-016", "b.dcm"), b"IMPORT")
        self.cand = _w(os.path.join(b, "review", "M01_candidates.csv"), "cand_id\n1\n")
        self.cand10 = _w(os.path.join(b, "review", "M10_candidates.csv"), "cand_id\n1\n")
        self.calls = _w(os.path.join(b, "review", "M01_calls_alice.csv"), "cand_id,call\n1,cSS\n")
        self.missed = _w(os.path.join(b, "review", "M01_missed.csv"), "missed_id\n1\n")
        self.final = _w(os.path.join(b, "review", "M01_final.json"), "{}")
        self.policy_file = _w(os.path.join(b, "review", "call_policy.json"), "{}")
        self.labels = _w(os.path.join(b, "labels", "candidate_labels.csv"), "x\n")
        self.model = _w(os.path.join(b, "percival", "registry", "v1.json"), "{}")
        self.settings = _w(os.path.join(b, "app_data", "settings.json"), "{}")
        self.pensieve = _w(os.path.join(b, "app_data", "pensieve.db"), b"SQLITE")
        self.stg = _w(os.path.join(b, "app_data", "staging", "M01", "f.nii"), b"STG")
        self.stg10 = _w(os.path.join(b, "app_data", "staging", "M10", "f.nii"), b"STG10")
        self.work = _w(os.path.join(b, "work", "M01", "out.nii"), b"WORK-OUT")
        _w(os.path.join(v, "manifest", "vault_manifest.json"), "{}")
        self.v_study = _w(os.path.join(v, "studies", "M01", "archived.nii"), b"ARCHIVED")
        self.v_orig = _w(os.path.join(v, "original_mri", "M01", "orig.dcm"), b"VAULT-ORIG")
        self.v_pens = _w(os.path.join(v, "PENSIEVE", "pensieve.db"), b"SQL")
        self.dicom = _w(os.path.join(self.vroot, "Dicom", "M01", "c.dcm"), b"DICOM")
        self.protected_files = [self.raw, self.preserved, self.data, self.import_src, self.cand, self.calls, self.missed,
                                self.final, self.policy_file, self.labels, self.model, self.settings, self.pensieve,
                                self.v_study, self.v_orig, self.v_pens, self.dicom]
        self.sums = {p: _sha(p) for p in self.protected_files}

    def intact(self, tc):
        for p, h in self.sums.items():
            tc.assertTrue(os.path.isfile(p), f"protected file missing: {p}")
            tc.assertEqual(_sha(p), h, f"protected file changed: {p}")

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.P = Project()
        self.fm = FileManager(self.P.base, vault_root=self.P.vault)
        self.cm = CleaningManager(self.P.base, vault_root=self.P.vault)

    def tearDown(self):
        self.P.close()


# S1 / S2 ---------------------------------------------------------------------------------------------------------------
class TestStudyCodes(Base):
    BAD = ["", " ", "..", ".", "M01/../x", "../M01", "M01/", "*", "M0?", "M[0]1", "M 01", "M01\x00", "-M01", "_x", "a" * 65, None, 5, ["M01"]]

    def test_s1_empty_code_is_refused_everywhere(self):
        self.assertFalse(self.fm.delete_study("")["ok"])
        self.assertFalse(self.fm.clean_staging("")["ok"])
        self.assertFalse(self.cm.delete_by_study("")["ok"])
        self.assertFalse(self.cm.delete_by_study("", target="all")["ok"])
        self.assertFalse(self.fm.stage_study("").get("ok", True))
        self.assertFalse(self.fm.archive_study("").get("ok", True))
        ok, _ = StudyWorkspaceManager(self.P.base, self.P.vault).clean_eligible_workspace("")
        self.assertFalse(ok)
        self.assertTrue(os.path.isfile(self.P.stg) and os.path.isfile(self.P.stg10))
        self.P.intact(self)

    def test_s2_invalid_codes_are_refused(self):
        for c in self.BAD:
            with self.subTest(code=c):
                with self.assertRaises(SF.SafetyError):
                    SF.validate_study_code(c)
                self.assertFalse(self.fm.delete_study(c)["ok"])
                self.assertFalse(self.fm.clean_staging(c)["ok"])
                self.assertFalse(self.cm.delete_by_study(c)["ok"])
        for good in ("M01", "STUDY-016", "P006", "SYN001", "ID_R1"):
            self.assertEqual(SF.validate_study_code(good), good)
        self.assertEqual(SF.parse_study_codes("M01,M02"), ["M01", "M02"])
        self.P.intact(self)

    def test_s2_code_boundary_m1_does_not_match_m10(self):
        self.assertTrue(SF.study_file_matches("M1_candidates.csv", "M1"))
        self.assertFalse(SF.study_file_matches("M10_candidates.csv", "M1"))
        res = self.fm.archive_study("M1")
        self.assertEqual(res["files_archived"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.P.vault, "studies", "M1", "M10_candidates.csv")))


# S3 ----------------------------------------------------------------------------------------------------------------------
class TestTraversal(Base):
    def test_s3_traversal_and_outside_paths_are_refused(self):
        trav = os.path.join(self.P.base, "work", "..", "raw", "M01")
        self.assertFalse(self.fm.delete_item(trav, confirm=True)["ok"])
        outside = _w(os.path.join(self.P.tmp, "outside", "keep.txt"), b"OUT")
        self.assertFalse(self.fm.delete_item(outside, confirm=True)["ok"])
        self.assertFalse(self.fm.copy_item(self.P.work, os.path.join(self.P.tmp, "outside"))["ok"])
        self.assertFalse(self.fm.create_directory(os.path.join(self.P.tmp, "outside"), "x")["ok"])
        self.assertFalse(self.fm.rename_item(self.P.work, "../../escaped")["ok"])
        self.assertTrue(os.path.isfile(outside))
        self.assertTrue(os.path.isfile(self.P.work))
        self.P.intact(self)

    def test_s3_symlink_into_originals_is_not_followed(self):
        link = os.path.join(self.P.base, "app_data", "staging", "M01", "link_to_raw")
        os.symlink(os.path.join(self.P.base, "raw", "M01"), link)
        self.assertFalse(self.fm.delete_item(link, confirm=True)["ok"])
        self.assertTrue(os.path.islink(link))
        # cleaning the staging folder removes the LINK, never what it points to
        self.assertTrue(self.fm.clean_staging("M01")["ok"])
        self.assertFalse(os.path.lexists(link))
        self.P.intact(self)

    def test_s3_quarantine_ids_cannot_traverse(self):
        for qid in ("../settings.json", "..", "/etc/hosts", "a/b", ""):
            with self.subTest(qid=qid):
                self.assertFalse(self.cm.restore_quarantine(qid)["ok"])
                r = self.cm.purge_quarantine(qid) if qid else self.cm.purge_quarantine(None)
                self.assertFalse(r["ok"])
        self.P.intact(self)

    def test_s3_http_get_rejects_traversal(self):
        import css_app
        srv = css_app.ThreadingHTTPServer(("127.0.0.1", 0), css_app.H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            port = srv.server_address[1]
            for url in (f"/api/log?code=../../../../etc/passwd", f"/api/log?code=..%2F..%2Fx", "/qc_png?code=../x"):
                with self.subTest(url=url):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}{url}", timeout=10)
                        self.fail("traversal request was served")
                    except urllib.error.HTTPError as e:
                        self.assertEqual(e.code, 400)
            # a .js file OUTSIDE app/ (tests/check_viewer.js exists) must not be served through the static handler
            import http.client
            outside = open(os.path.join(ROOT, "tests", "check_viewer.js"), "rb").read()
            for path in ("/../tests/check_viewer.js", "/..//tests/check_viewer.js"):
                with self.subTest(path=path):
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    c.request("GET", path)
                    resp = c.getresponse()
                    body = resp.read()
                    c.close()
                    self.assertNotEqual(resp.status, 200)
                    self.assertNotEqual(body, outside)
            ok = urllib.request.urlopen(f"http://127.0.0.1:{port}/settings_view.js", timeout=10)
            self.assertEqual(ok.status, 200)
        finally:
            srv.shutdown()
            srv.server_close()


# S4 / S5 / S6 ----------------------------------------------------------------------------------------------------------
class TestProtectedLocations(Base):
    def test_s4_original_mri_cannot_be_deleted_moved_renamed_or_overwritten(self):
        targets = [self.P.raw, os.path.join(self.P.base, "raw", "M01"), os.path.join(self.P.base, "raw"),
                   self.P.preserved, self.P.data, os.path.join(self.P.base, "data"), self.P.import_src,
                   os.path.join(self.P.base, "app_data", "import_src"), self.P.v_orig,
                   os.path.join(self.P.vault, "original_mri"), self.P.dicom, os.path.join(self.P.vroot, "Dicom", "M01"),
                   os.path.join(self.P.base, "RAW", "M01")]
        for t in targets:
            with self.subTest(target=t):
                self.assertFalse(self.fm.delete_item(t, confirm=True)["ok"])
                self.assertFalse(self.fm.rename_item(t, "renamed")["ok"])
                self.assertFalse(self.fm.move_item(t, os.path.join(self.P.base, "work"))["ok"])
        for d in (os.path.join(self.P.base, "raw", "M01", "SWI"), os.path.join(self.P.base, "data"),
                  os.path.join(self.P.vault, "original_mri", "M01")):
            with self.subTest(dst=d):
                self.assertFalse(self.fm.copy_item(self.P.work, d)["ok"])
                self.assertFalse(self.fm.create_directory(d, "new")["ok"])
        # reading originals is still allowed (copy OUT of raw/ into the work area)
        out = self.fm.copy_item(self.P.raw, os.path.join(self.P.base, "work", "M01"))
        self.assertTrue(out["ok"], out)
        self.P.intact(self)

    def test_s5_reader_calls_annotations_and_call_ledger_are_protected(self):
        for t in (self.P.calls, self.P.missed, self.P.final, self.P.policy_file, self.P.cand, self.P.labels,
                  os.path.join(self.P.base, "review"), self.P.model, self.P.settings, self.P.pensieve):
            with self.subTest(target=t):
                self.assertFalse(self.fm.delete_item(t, confirm=True)["ok"])
                self.assertFalse(self.fm.rename_item(t, "renamed")["ok"])
        r = self.fm.copy_item(self.P.work, os.path.join(self.P.base, "review"), conflict_mode="replace")
        self.assertFalse(r["ok"])
        # delete_study removes the staging copy only - every review/ file survives
        res = self.fm.delete_study("M01")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["review_records_preserved"])
        self.assertFalse(os.path.exists(os.path.join(self.P.base, "app_data", "staging", "M01")))
        self.assertTrue(os.path.isfile(self.P.stg10))
        self.P.intact(self)

    def test_s6_vault_wide_and_structural_deletion_is_refused(self):
        v, b = self.P.vault, self.P.base
        os.makedirs(os.path.join(v, "archive"), exist_ok=True)
        os.makedirs(os.path.join(v, "processed_mri"), exist_ok=True)
        for t in (v, self.P.vroot, os.path.join(v, "studies"), os.path.join(v, "STUDIES"), os.path.join(v, "archive"),
                  os.path.join(v, "processed_mri"), os.path.join(v, "Processed_MRI"), os.path.join(v, "PENSIEVE"),
                  os.path.join(v, "manifest"), b, os.path.join(b, "work"), os.path.join(b, "app_data"),
                  os.path.join(b, "app_data", "staging"), "/", self.P.tmp):
            with self.subTest(target=t):
                if os.path.lexists(t):
                    self.assertFalse(self.fm.delete_item(t, confirm=True)["ok"])
        for tgt in ("vault", "all"):
            self.assertFalse(self.fm.delete_study("M01", target=tgt)["ok"])
        self.assertTrue(os.path.isdir(os.path.join(v, "studies", "M01")))
        # a single non-protected item inside a managed folder can still be deleted (the policy is not a blanket ban)
        self.assertTrue(self.fm.delete_item(self.P.work, confirm=True)["ok"])
        self.P.intact(self)

    def test_s6_cleaning_never_touches_protected_items(self):
        os.utime(self.P.stg, (1, 1))
        os.utime(os.path.dirname(self.P.stg), (1, 1))
        inc = _w(os.path.join(self.P.base, "review", "M01_x.incomplete"), b"inc")
        os.utime(inc, (1, 1))
        with open(self.cm.policy_file, "w") as f:
            json.dump({"categories": {"failed_temp": 1, "training_staging": 1}}, f)
        res = self.cm.execute_clean(["failed_temp", "training_staging"], use_quarantine=True)
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.isfile(inc))                      # review/ is protected: refused and reported
        self.assertGreaterEqual(res["refused_count"], 1)
        self.P.intact(self)

    def test_s6_quarantine_purge_all_must_be_explicit_and_restore_never_overwrites(self):
        q = _w(os.path.join(self.cm.quarantine_dir, "1_x_f.nii"), b"Q")
        with open(q + ".meta", "w") as f:
            json.dump({"original_path": self.P.work}, f)        # the original location exists again
        self.assertFalse(self.cm.purge_quarantine(None)["ok"])
        self.assertTrue(os.path.isfile(q))
        r = self.cm.restore_quarantine("1_x_f.nii")
        self.assertFalse(r["ok"])
        self.assertEqual(open(self.P.work, "rb").read(), b"WORK-OUT")
        with open(q + ".meta", "w") as f:
            json.dump({"original_path": os.path.join(self.P.base, "raw", "M01", "planted.nii")}, f)
        self.assertFalse(self.cm.restore_quarantine("1_x_f.nii")["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.P.base, "raw", "M01", "planted.nii")))
        self.assertTrue(self.cm.purge_quarantine(None, purge_all=True)["ok"])
        self.assertFalse(os.path.exists(q))
        self.P.intact(self)


# S7 ----------------------------------------------------------------------------------------------------------------------
class TestSync(Base):
    def setUp(self):
        super().setUp()
        self.new = _w(os.path.join(self.P.base, "work", "M01", "new_output.nii"), b"NEW-OUTPUT")
        self.sm = SyncManager(StoragePathsService(self.P.base, self.P.vault))

    def test_s7_forged_source_or_destination_is_refused(self):
        prev = self.sm.generate_sync_preview(study_ids="M01").to_dict()       # comma string, as from a query
        self.assertTrue(prev["can_proceed"], prev)
        rels = {i["relative_path"] for i in prev["items_to_copy"]}
        self.assertIn("new_output.nii", rels)
        forged = [
            dict(study_id="M01", relative_path="new_output.nii", source_path=self.P.raw,
                 destination_path=os.path.join(self.P.vault, "original_mri", "M01", "evil.nii")),
            dict(study_id="M01", relative_path="../../raw/M01/SWI/swi.nii", source_path=self.P.raw, destination_path=self.P.v_orig),
            dict(study_id="M01", relative_path="not_in_plan.nii", source_path=self.P.raw, destination_path=self.P.v_study),
            dict(study_id="../M01", relative_path="new_output.nii"),
        ]
        for it in forged:
            with self.subTest(item=it):
                r = self.sm.execute_sync({"items_to_copy": [it]})
                self.assertFalse(r["ok"], r)
                self.assertEqual(r["transferred_count"], 0)
        # a forged item mixed into a valid plan refuses the whole request: nothing is copied
        r = self.sm.execute_sync({"items_to_copy": prev["items_to_copy"] + [forged[0]]})
        self.assertFalse(r["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.P.vault, "studies", "M01", "new_output.nii")))
        self.assertFalse(os.path.exists(os.path.join(self.P.vault, "original_mri", "M01", "evil.nii")))
        self.P.intact(self)

    def test_s7_valid_plan_still_syncs_and_never_overwrites(self):
        prev = self.sm.generate_sync_preview(study_ids=["M01"]).to_dict()
        r = self.sm.execute_sync(prev)
        self.assertTrue(r["ok"], r)
        self.assertEqual(open(os.path.join(self.P.vault, "studies", "M01", "new_output.nii"), "rb").read(), b"NEW-OUTPUT")
        self.P.intact(self)


# S8 ----------------------------------------------------------------------------------------------------------------------
class _Paths:
    def __init__(self, mount, workspace_root=None):
        self.mount = mount
        self.workspace_root = workspace_root or tempfile.mkdtemp(prefix="p0ws_")   # 1e: the journal lives here

    def get_vault_info(self):
        return VolumeInfo(mount_point=self.mount, volume_name=os.path.basename(self.mount), filesystem="apfs", device_node="disk9s1",
                          volume_uuid="U", total_bytes=1, available_bytes=1, used_bytes=0, is_vault=True, is_connected=True)


class _State:
    def __init__(self, jobs=None):
        self.jobs, self.events = jobs or [], []

    def get_all_jobs(self, limit=20):
        return self.jobs

    def record_audit_event(self, *a, **k):
        self.events.append((a, k))


class TestForceFlags(Base):
    def setUp(self):
        super().setUp()
        self.mount = os.path.join(os.environ["PERCIVAL_VOLUMES_ROOT"], "Percival")
        os.makedirs(self.mount, exist_ok=True)
        self.calls = []

    def _em(self, rc_normal=1, jobs=None):
        def runner(cmd):
            self.calls.append(list(cmd))
            return types.SimpleNamespace(returncode=0 if "force" in cmd else rc_normal, stdout="", stderr="Resource busy")
        no_open_files = lambda cmd: types.SimpleNamespace(returncode=1, stdout="", stderr="")   # 1e: lsof finds nothing
        return EJ.EjectManager(_Paths(self.mount), _State(jobs), runner=runner, lsof_runner=no_open_files)

    def test_s8_force_eject_needs_server_token_and_typed_volume_name(self):
        with mock.patch("os.path.ismount", return_value=True):
            em = self._em()
            r = em.eject_vault(emergency=True, force=True)                         # client-only force: refused
            self.assertFalse(r["ok"])
            self.assertEqual(self.calls, [])
            r = em.eject_vault(emergency=True, force=True, force_token="made-up", confirm_volume_name="Percival")
            self.assertFalse(r["ok"])
            self.assertEqual(self.calls, [])
            r1 = self._em().eject_vault(emergency=True)                            # refused normal unmount -> token
            self.assertTrue(r1["needs_force_confirmation"])
            tok = r1["force_token"]
            self.assertEqual(self.calls, [["diskutil", "unmount", os.path.realpath(self.mount)]])
            r2 = self._em().eject_vault(emergency=True, force=True, force_token=tok, confirm_volume_name="wrong")
            self.assertFalse(r2["ok"])
            r3 = self._em().eject_vault(emergency=True, force=True, force_token=tok, confirm_volume_name="Percival")
            self.assertFalse(r3["ok"])                                               # single use: consumed by r2
            self.assertEqual(len(self.calls), 1)
            r1 = self._em().eject_vault(emergency=True)
            r4 = self._em().eject_vault(emergency=True, force=True, force_token=r1["force_token"], confirm_volume_name="Percival")
            self.assertTrue(r4["ok"], r4)
            self.assertEqual(self.calls[-1], ["diskutil", "unmount", "force", os.path.realpath(self.mount)])

    def test_s8_normal_eject_respects_safety_check_and_real_mount_points(self):
        with mock.patch("os.path.ismount", return_value=True):
            r = self._em(jobs=[{"job_id": "j1", "status": "transferring"}]).eject_vault()
            self.assertFalse(r["ok"])
            self.assertEqual(self.calls, [])
        r = self._em().eject_vault()                                                 # not a real mount point
        self.assertFalse(r["ok"])
        self.assertEqual(self.calls, [])
        inner = os.path.join(self.mount, "PERCIVAL_VAULT")
        os.makedirs(inner, exist_ok=True)
        with mock.patch("os.path.ismount", return_value=True):
            r = EJ.EjectManager(_Paths(inner), _State(), runner=lambda c: self.calls.append(c)).eject_vault()
            self.assertFalse(r["ok"])                                                # a folder inside a volume
            self.assertEqual(self.calls, [])

    def test_s8_api_ignores_client_force_on_workspace_clean(self):
        import css_app
        swm = StudyWorkspaceManager(css_app.B, vault_root=None)
        ws = _w(os.path.join(css_app.B, "work", "W01", "keep.nii"), b"KEEP")
        swm.register_study("W01", os.path.join(css_app.B, "raw", "W01"))
        swm._ledger["W01"]["active_workspace_location"] = os.path.dirname(ws)
        swm._save_ledger()
        r = css_app.workspace_post("clean", {"study_id": "W01", "force": True})
        self.assertFalse(r["ok"], r)
        self.assertTrue(os.path.isfile(ws))
        r = css_app.storage_post("delete", {"code": ""})
        self.assertFalse(r["ok"])
        r = css_app.clean_post("quarantine_purge", {})
        self.assertFalse(r["ok"])


# S9 / S10 -----------------------------------------------------------------------------------------------------------------
class TestReplaceSafety(Base):
    def _bad_part_hash(self):
        real = UTE.compute_sha256
        return mock.patch.object(UTE, "compute_sha256", side_effect=lambda p, *a, **k: "0" * 64 if str(p).endswith(".part") else real(p, *a, **k))

    def test_s9_checksum_failure_keeps_existing_destination(self):
        src = _w(os.path.join(self.P.base, "work", "M01", "new.nii"), b"NEW-CONTENT")
        dst = _w(os.path.join(self.P.base, "work", "M02", "new.nii"), b"OLD-VALID")
        eng = UTE.UnifiedTransferEngine(os.path.join(self.P.base, "app_data", "transfers"))
        with self._bad_part_hash():
            with self.assertRaises(IOError):
                eng.copy_file_streaming(src, dst, verify_sha=True)
        self.assertEqual(open(dst, "rb").read(), b"OLD-VALID")
        self.assertFalse(os.path.exists(dst + ".part"))
        for clone in (True, False):
            with self.subTest(prefer_clone=clone), self._bad_part_hash():
                ok, _, _ = eng.transfer_path(src, dst, operation="copy", verify_sha=True, prefer_clone=clone)
                self.assertFalse(ok)
                self.assertEqual(open(dst, "rb").read(), b"OLD-VALID")
                self.assertFalse(os.path.exists(dst + ".part"))

    def test_s9_file_manager_replace_keeps_target_until_verified(self):
        src = _w(os.path.join(self.P.base, "work", "M01", "out.nii"), b"WORK-OUT")
        dst_dir = os.path.join(self.P.base, "work", "M02")
        target = _w(os.path.join(dst_dir, "out.nii"), b"OLD-VALID")
        tree_src = _w(os.path.join(self.P.base, "work", "T1", "seg", "a.nii"), b"A-NEW")
        tree_tgt = _w(os.path.join(self.P.base, "work", "M02", "seg", "a.nii"), b"A-OLD")
        from uengine.transfer import copier as CP                  # Phase 1b: File Manager copies use the verified copier
        real = CP._hash_file
        bad = mock.patch.object(CP, "_hash_file", side_effect=lambda p, nocache=False, chunk=CP.CHUNK:
                                ("0" * 64, nocache) if nocache else real(p, nocache, chunk))
        with bad:
            self.assertFalse(self.fm.copy_item(src, dst_dir, conflict_mode="replace")["ok"])
            self.assertFalse(self.fm.copy_item(os.path.dirname(tree_src), dst_dir, conflict_mode="replace")["ok"])
        self.assertEqual(open(target, "rb").read(), b"OLD-VALID")
        self.assertEqual(open(tree_tgt, "rb").read(), b"A-OLD")
        self.assertEqual([n for n in os.listdir(dst_dir) if ".incoming-" in n or ".replaced-" in n], [])
        # without the fault the replacement happens - and only then is the old copy gone
        self.assertTrue(self.fm.copy_item(src, dst_dir, conflict_mode="replace")["ok"])
        self.assertEqual(open(target, "rb").read(), b"WORK-OUT")
        self.assertTrue(self.fm.copy_item(os.path.dirname(tree_src), dst_dir, conflict_mode="replace")["ok"])
        self.assertEqual(open(tree_tgt, "rb").read(), b"A-NEW")
        self.P.intact(self)

    def test_s10_move_never_deletes_uncopied_source_files(self):
        # Phase 1b: hidden files ARE copied (they can be data) and then removed from the source like any verified file;
        # items that are never copied (symlinks, Finder metadata) must stay at the source.
        src_dir = os.path.join(self.P.base, "work", "MV")
        a = _w(os.path.join(src_dir, "a.nii"), b"A")
        hidden = _w(os.path.join(src_dir, "sub", ".hidden_notes"), b"H")
        dsstore = _w(os.path.join(src_dir, "sub", ".DS_Store"), b"finder")
        link = os.path.join(src_dir, "link_to_raw")
        os.symlink(os.path.join(self.P.base, "raw", "M01"), link)
        r = self.fm.move_item(src_dir, os.path.join(self.P.base, "work", "M01"))
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.exists(a))
        self.assertFalse(os.path.exists(hidden))                                   # copied + verified -> removed
        self.assertEqual(open(os.path.join(r["target_path"], "sub", ".hidden_notes"), "rb").read(), b"H")
        self.assertTrue(os.path.isfile(dsstore))                                   # not copied -> not deleted
        self.assertTrue(os.path.islink(link))                                      # not copied -> not deleted
        self.assertFalse(os.path.lexists(os.path.join(r["target_path"], "link_to_raw")))
        self.assertEqual(open(os.path.join(r["target_path"], "a.nii"), "rb").read(), b"A")
        self.P.intact(self)


# S11 - S14 ----------------------------------------------------------------------------------------------------------------
class TestScientificIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import percival_gui as PG
        cls.PG = PG

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="p0sci_")
        os.makedirs(os.path.join(self.base, "review"))
        self.set = {"features": {"experimental_core": False}, "percival_use_historical": False}
        self.ctx = mock.patch.dict(self.PG.CTX, {"B": self.base, "SC": os.path.join(ROOT, "scripts"), "SET": self.set}, clear=False)
        self.ctx.start()
        self.store = mock.patch.dict(self.PG.STORE, {"ok": True, "error": ""})
        self.store.start()
        self.M = dict(version="v-test", ready=True, thresholds={}, note="", data={})
        self.rows = [dict(cand_id=1, hemi="L"), dict(cand_id=2, hemi="R")]

    def tearDown(self):
        self.store.stop()
        self.ctx.stop()
        shutil.rmtree(self.base, ignore_errors=True)

    def _score(self, scored, core_none=True):
        runs = []

        real_run = self.PG.subprocess.run

        def fake_run(cmd, *a, **k):
            if not any("score_css.py" in str(x) for x in (cmd if isinstance(cmd, (list, tuple)) else [cmd])):
                return real_run(cmd, *a, **k)                 # other programs (e.g. read-only diskutil info) unchanged
            runs.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        patches = [mock.patch.object(self.PG, "gather", return_value=self.rows),
                   mock.patch("uengine.percival.meta.score_rows", return_value=[dict(s) for s in scored]),
                   mock.patch.object(self.PG.subprocess, "run", side_effect=fake_run)]
        if core_none:
            patches.append(mock.patch("uengine.percival_core.PercivalCoreIntelligence.evaluate_candidate",
                                      return_value=types.SimpleNamespace(percival_score=None, band="insufficient",
                                                                         status="incomplete_visual_data", uncertainty=None)))
        for p in patches:
            p.start()
        try:
            rec = self.PG.score_study("SYN1", self.M)
        finally:
            for p in reversed(patches):
                p.stop()
        return rec, runs

    SCORED = [dict(cand_id=1, percival_score=72.0, band="green", status="reliable"),      # the bands score_rows writes (red / yellow / green)
              dict(cand_id=2, percival_score=30.0, band="red", status="reliable")]

    def test_s11_missing_core_output_never_overwrites_the_trained_score(self):
        self.set["features"]["experimental_core"] = True          # even with the experimental layer ON
        rec, runs = self._score(self.SCORED)
        c = {s["cand_id"]: s for s in rec["candidates"]}
        self.assertEqual(c[1]["percival_score"], 72.0)
        self.assertEqual(c[1]["band"], "green")
        self.assertEqual(c[1]["status"], "reliable")
        self.assertEqual(c[2]["percival_score"], 30.0)
        self.assertIn("EXPERIMENTAL", c[1]["experimental_core"]["label"])
        self.assertIsNone(c[1]["experimental_core"]["score"])
        self.assertEqual(c[1]["experimental_core"]["status"], "unavailable")
        self.assertEqual(rec["study_score"]["status"], "scored")
        self.assertEqual(rec["study_score"]["called_ids"], [1])
        self.assertEqual(len(runs), 1)
        self.assertIn("1", runs[0][runs[0].index("--accept-ids") + 1].split(","))

    def test_s12_unassessable_study_is_never_recorded_as_zero(self):
        rec, runs = self._score([dict(cand_id=1, percival_score=None, band="insufficient", status="insufficient"),
                                 dict(cand_id=2, percival_score=None, band="insufficient", status="insufficient")])
        st = rec["study_score"]
        self.assertEqual(st["status"], "unassessable")
        self.assertIsNone(st["total"])
        self.assertIsNone(st["L_score"])
        self.assertIsNone(st["R_score"])
        self.assertIn("not a negative", st["reason"])
        self.assertEqual(runs, [])                                    # score_css.py --accept-ids none is NOT run
        saved = json.load(open(os.path.join(self.base, "percival", "scores", "SYN1.json")))
        self.assertEqual(saved["study_score"]["status"], "unassessable")
        self.assertIsNone(saved["study_score"]["total"])

    def test_s12_model_scored_zero_calls_is_a_scored_prediction_not_unassessable(self):
        rec, runs = self._score([dict(cand_id=1, percival_score=10.0, band="unlikely", status="reliable")])
        self.assertEqual(rec["study_score"]["status"], "scored")
        self.assertEqual(len(runs), 1)

    def test_s14_experimental_layer_is_off_by_default(self):
        self.assertFalse(self.PG.experimental_core_enabled())
        with mock.patch.object(self.PG, "_experimental_core", side_effect=AssertionError("must not run")):
            rec, _ = self._score(self.SCORED, core_none=False)
        self.assertTrue(all("experimental_core" not in s for s in rec["candidates"]))
        r = self.PG.score_study_unified("SYN1")
        self.assertFalse(r["ok"])
        self.assertTrue(r["experimental"])
        import css_app
        self.assertIs(css_app.SET["features"]["experimental_core"], False)

    def test_s13_unreviewed_unsure_or_failed_labels_never_become_negatives(self):
        import pandas as pd
        rv = os.path.join(self.base, "review")
        cand = pd.DataFrame(dict(cand_id=[1, 2, 3, 4], vox_i=[10, 40, 70, 100], vox_j=[10, 40, 70, 100], vox_k=[5, 6, 7, 8],
                                 volume_mm3=[30.0, 40.0, 50.0, 60.0]))
        cand.to_csv(os.path.join(rv, "SYN1_candidates.csv"), index=False)
        calls = cand.iloc[:3].assign(call=["cSS", "Vessel", "Unsure"], reviewer="alice", time="2026-11-23 10:00:00", comment="")
        calls.to_csv(os.path.join(rv, "SYN1_calls_alice.csv"), index=False)
        import gt_fixture; gt_fixture.ground_truth(self.base, ["alice"], ["SYN1"])    # Phase 3A: a designated expert + documented verification
        spec = importlib.util.spec_from_file_location("call_ledger_p0", os.path.join(ROOT, "scripts", "call_ledger.py"))
        L = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(L)
        self.PG._LCACHE.clear()
        with mock.patch.object(self.PG, "_ledger_mod", return_value=L):
            res = self.PG.label_summary("SYN1")
        self.assertEqual(res["labels"], {1: 1, 2: 0}, res)                # explicit expert calls only
        self.assertNotIn(3, res["labels"])                                 # Unsure -> not a label
        self.assertNotIn(4, res["labels"])                                 # never reviewed -> not a negative
        self.PG._LCACHE.clear()
        with mock.patch.object(self.PG, "_ledger_mod", side_effect=RuntimeError("ledger unreadable")):
            res = self.PG.label_summary("SYN1")
        self.assertEqual(res["labels"], {})                                # failure -> no labels at all, never y=0
        self.assertEqual(res["state"], "error")
        self.PG._LCACHE.clear()


if __name__ == "__main__":
    unittest.main()
