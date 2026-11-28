"""Where the identity-vault DEVICE KEY lives (2026-11-28: identity vault encrypted at rest by default).

The key is a random 256-bit secret created on this Mac (never hard-coded, never derived from anything guessable). It is kept in the macOS
login Keychain (generic password, service "Percival identity vault", account = the vault's key id), so the encrypted vault file alone - on the
drive, in a backup or in a copied project folder - cannot be read. The recovery key (the same secret, shown once on request) lets the vault be
opened on another Mac.

Tests NEVER touch the real Keychain: under test isolation (PERCIVAL_TEST_ISOLATION=1) or with PERCIVAL_KEYSTORE_DIR set, a file key store in
that (temporary) folder is used. Elsewhere than macOS no store is available (the caller keeps working and reports it).
Note: /usr/bin/security receives the secret as a command-line argument for the few milliseconds of the call (visible to processes of the same
user only); the stored value never touches the project folder or a log."""
import base64, os, subprocess, sys

SERVICE = "Percival identity vault"
SECURITY = "/usr/bin/security"


class KeyStoreError(RuntimeError):
    pass


class FileKeyStore:
    kind = "file (test / explicit folder)"

    def __init__(self, d): self.d = d; os.makedirs(d, exist_ok=True)
    def _p(self, key_id): return os.path.join(self.d, f"{key_id}.key")
    def put(self, key_id, key):
        p = self._p(key_id); tmp = p + ".tmp"
        with open(tmp, "w") as f: f.write(base64.b64encode(key).decode())
        os.chmod(tmp, 0o600); os.replace(tmp, p)
    def get(self, key_id):
        try:
            with open(self._p(key_id)) as f: return base64.b64decode(f.read().strip())
        except FileNotFoundError: return None
    def delete(self, key_id):
        try: os.remove(self._p(key_id))
        except FileNotFoundError: pass


class MacKeychain:
    kind = "macOS login Keychain"

    def _run(self, args):
        return subprocess.run([SECURITY] + args, capture_output=True, text=True, timeout=30)
    def put(self, key_id, key):
        r = self._run(["add-generic-password", "-U", "-a", key_id, "-s", SERVICE, "-l", SERVICE, "-w", base64.b64encode(key).decode()])
        if r.returncode: raise KeyStoreError(f"Keychain refused to store the key ({r.returncode}): {r.stderr.strip()[:200]}")
    def get(self, key_id):
        r = self._run(["find-generic-password", "-a", key_id, "-s", SERVICE, "-w"])
        if r.returncode: return None
        try: return base64.b64decode(r.stdout.strip())
        except Exception: return None
    def delete(self, key_id):
        self._run(["delete-generic-password", "-a", key_id, "-s", SERVICE])


def store():
    d = os.environ.get("PERCIVAL_KEYSTORE_DIR")
    if d: return FileKeyStore(d)
    if os.environ.get("PERCIVAL_TEST_ISOLATION") == "1":
        return FileKeyStore(os.path.join(os.path.expanduser("~"), ".percival_test_keystore"))
    if sys.platform == "darwin" and os.path.exists(SECURITY): return MacKeychain()
    return None
