# experimental app only (PYTHONPATH set by its launcher): install the production write guard in every Python process,
# then run any other sitecustomize.py further down sys.path (so site-wide or test customisations still load)
import os, sys
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
try:
    import css_writeguard; css_writeguard.install()
finally:
    sys.path.remove(_here)
for _p in sys.path:
    _f = os.path.join(_p or ".", "sitecustomize.py")
    if os.path.abspath(_p or ".") != _here and os.path.isfile(_f):
        exec(compile(open(_f).read(), _f, "exec"), {"__name__": "sitecustomize_chained", "__file__": _f}); break
