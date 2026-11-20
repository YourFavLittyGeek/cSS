import os, sys, tempfile
ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = ENGINE
sys.path.insert(0, ENGINE)
# never a real project, even if a legacy module reads CSS_BASE
os.environ["CSS_BASE"] = os.environ.get("CSS_ENGINE_TEST_BASE") or tempfile.mkdtemp(prefix="uengine_test_base_")
