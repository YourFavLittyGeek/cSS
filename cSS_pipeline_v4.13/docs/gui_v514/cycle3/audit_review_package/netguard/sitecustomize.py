# test-only: every Python process started with this on PYTHONPATH refuses and logs non-loopback connections
import socket, os
_c = socket.socket.connect
def _g(self, addr):
    h = addr[0] if isinstance(addr, tuple) else addr
    if isinstance(h, str) and h not in ("127.0.0.1", "::1", "localhost") and not h.startswith("/"):
        open(os.environ.get("CSS_NETGUARD_LOG", "/dev/null"), "a").write(f"{os.getpid()} {h}\n")
        raise PermissionError("netguard: blocked " + h)
    return _c(self, addr)
socket.socket.connect = _g
