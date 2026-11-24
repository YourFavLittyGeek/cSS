"""approval_signing.py - local integrity signatures for approval records (Stage 7: role and approval integrity beyond typed confirmations).

Every component-registry version (an approval) is signed with HMAC-SHA256 under a key that lives OUTSIDE the project folder, on this Mac
(~/.percival/approval_signing.key, created once, mode 600). A record edited by hand, copied from another computer or written by a tool
that bypassed the app no longer verifies, and PERCIVAL › System shows it as 'signature invalid'.

What this does NOT do (documented, deferred): it does not authenticate WHO approved - names are typed, there are no user accounts or
passwords in this local, single-user research application. Anyone who can run the app on this Mac can sign. Real per-person authentication
(macOS keychain / smart-card signing) is deferred until the app has multi-user deployment; see docs/engineering/DEPRECATIONS.md and the
Stage 7 notes in docs/engineering/ARCHITECTURE_INTEGRATION.md.
"""
import hashlib
import hmac
import json
import os
import secrets

SCHEME = "hmac-sha256/local-key-v1"


def key_path():
    return os.path.join(os.path.expanduser("~"), ".percival", "approval_signing.key")


def _key():
    p = key_path()
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f: f.write(secrets.token_hex(32))
    with open(p) as f: return bytes.fromhex(f.read().strip())


def _payload(rec):
    return json.dumps({k: v for k, v in rec.items() if k not in ("signature", "signature_ok")}, sort_keys=True, default=str).encode()


def sign(rec):
    return dict(scheme=SCHEME, mac=hmac.new(_key(), _payload(rec), hashlib.sha256).hexdigest(), key_id=hashlib.sha256(_key()).hexdigest()[:12])


def verify(rec):
    """True / False for a signed record; None for a record written before signing existed (reported as 'unsigned')"""
    s = (rec or {}).get("signature")
    if not s: return None
    try: return hmac.compare_digest(s.get("mac", ""), hmac.new(_key(), _payload(rec), hashlib.sha256).hexdigest())
    except Exception: return False
