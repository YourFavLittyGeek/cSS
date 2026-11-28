"""2026-11-28 audit finding: the identity vault was PLAINTEXT (private/identity_vault.json) and an unreadable vault was silently replaced by an
empty one. Now: encrypted at rest with a random device key (macOS Keychain; under test isolation a FILE key store in the temporary HOME - the
real Keychain is never touched), verified migration of the plaintext file (moved to the Trash only after a decrypt round-trip), recovery key,
no empty overwrite. Synthetic identities only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
import identity as IDM          # noqa: E402
import keystore as KS           # noqa: E402

FAKE = dict(created="x", patients={"pu1": dict(mrn="TEST-MRN-0001", name="Test Person")}, studies={"su1": dict(accession="TEST-ACC-1")}, history=[])


class T(unittest.TestCase):
    def setUp(self):
        self.b = tempfile.mkdtemp(prefix="idv_"); self.ks = tempfile.mkdtemp(prefix="ks_")
        self.env = mock.patch.dict(os.environ, {"PERCIVAL_KEYSTORE_DIR": self.ks}); self.env.start()
        os.makedirs(os.path.join(self.b, "private"))

    def tearDown(self): self.env.stop()

    def plain(self, obj=FAKE, raw=None):
        with open(os.path.join(self.b, "private", "identity_vault.json"), "wb") as f: f.write(raw if raw is not None else json.dumps(obj).encode())

    def test_never_the_real_keychain_in_tests(self):
        with mock.patch.dict(os.environ, {"PERCIVAL_KEYSTORE_DIR": ""}):
            os.environ.pop("PERCIVAL_KEYSTORE_DIR")
            self.assertIsInstance(KS.store(), KS.FileKeyStore)                     # PERCIVAL_TEST_ISOLATION=1 -> file store in the temp HOME

    def test_plaintext_migrated_verified(self):
        self.plain()
        I = IDM.Identity(self.b)
        self.assertIsNone(I.problem); self.assertFalse(os.path.exists(os.path.join(self.b, "private", "identity_vault.json")))
        enc = os.path.join(self.b, "private", "identity_vault.local.enc"); raw = open(enc, "rb").read()
        self.assertNotIn(b"TEST-MRN-0001", raw); self.assertNotIn(b"Test Person", raw)                  # encrypted at rest
        self.assertEqual(json.loads(raw)["cipher"], "AES-256-GCM")
        self.assertTrue(os.path.exists(I.migrated["plaintext_moved_to"]))                               # in the Trash, not deleted
        self.assertTrue(I.migrated["plaintext_moved_to"].startswith(os.path.join(os.path.expanduser("~"), ".Trash")))
        I2 = IDM.Identity(self.b); self.assertEqual(I2._need()["patients"]["pu1"]["mrn"], "TEST-MRN-0001")     # reopens with the device key
        self.assertTrue(any(h.get("op") == "identity_vault_encrypted" for h in I2.R["history"]))

    def test_new_project_writes_encrypted(self):
        I = IDM.Identity(self.b); I._vault["patients"]["p"] = dict(mrn="TEST-2"); I._write_vault()
        self.assertFalse(os.path.exists(os.path.join(self.b, "private", "identity_vault.json")))
        self.assertNotIn(b"TEST-2", open(os.path.join(self.b, "private", "identity_vault.local.enc"), "rb").read())

    def test_unreadable_plaintext_never_replaced(self):
        self.plain(raw=b'{"patients": {"pu1": ')
        I = IDM.Identity(self.b); self.assertIsNotNone(I.problem)
        with self.assertRaises(IDM.VaultLocked): I._need()
        with self.assertRaises(IDM.IdentityError): I._write_plain_vault()
        self.assertEqual(open(os.path.join(self.b, "private", "identity_vault.json"), "rb").read(), b'{"patients": {"pu1": ')

    def test_failed_encryption_keeps_plaintext(self):
        self.plain()
        with mock.patch.object(KS.FileKeyStore, "get", return_value=None):          # the store "loses" the key -> verification fails
            I = IDM.Identity(self.b)
        self.assertIn("NOT encrypted", I.problem)
        self.assertTrue(os.path.exists(os.path.join(self.b, "private", "identity_vault.json")))
        self.assertFalse(os.path.exists(os.path.join(self.b, "private", "identity_vault.local.enc")))

    def test_missing_key_and_recovery(self):
        self.plain(); I = IDM.Identity(self.b); rk = I.recovery_key()
        for f in os.listdir(self.ks): os.remove(os.path.join(self.ks, f))           # e.g. another Mac: no key in its Keychain
        I2 = IDM.Identity(self.b); self.assertIsNotNone(I2.problem)
        with self.assertRaises(IDM.VaultLocked): I2._need()
        with self.assertRaises(IDM.VaultLocked): I2.restore_recovery_key("A" * 52)
        r = I2.restore_recovery_key(rk["recovery_key"]); self.assertTrue(r["ok"]); self.assertEqual(I2._need()["patients"]["pu1"]["name"], "Test Person")

    def test_recovery_key_needs_typed_confirmation(self):
        import identity_gui as IG
        self.plain()
        with mock.patch.object(IG, "ID", return_value=IDM.Identity(self.b)):
            self.assertFalse(IG.vault("recovery_key", {}, {})["ok"])
            r = IG.vault("recovery_key", dict(confirm="SHOW RECOVERY KEY"), {}); self.assertTrue(r["ok"]); self.assertGreater(len(r["recovery_key"]), 40)


if __name__ == "__main__":
    unittest.main()
