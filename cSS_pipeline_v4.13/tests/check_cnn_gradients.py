"""check_cnn_gradients.py - Numerical gradient check for SmallCNN against finite differences."""
import sys, os
import numpy as np

# Add unified_engine to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.percival.cnn import SmallCNN, IN_SHAPE

def check_cnn_gradients():
    rng = np.random.default_rng(42)
    net = SmallCNN(seed=42)
    
    # Initialize with non-zero biases to avoid ReLU boundary non-differentiabilities
    net.p["b1"] += 0.5
    net.p["b2"] += 0.5

    # Test batch: N=2, C=3, H=49, W=25
    N = 2
    X = rng.standard_normal((N,) + IN_SHAPE).astype(np.float32) * 0.2
    y = np.array([1.0, 0.0], dtype=np.float32)
    w = np.array([1.0, 1.0], dtype=np.float32)
    l2 = 0.0

    analytic_grads, loss = net._grads(X, y, w, l2=l2)

    def get_loss():
        lg, _ = net._forward(X)
        pr = 1.0 / (1.0 + np.exp(-np.clip(lg, -30, 30)))
        return float(-(w * (y * np.log(pr + 1e-9) + (1.0 - y) * np.log(1.0 - pr + 1e-9))).sum() / w.sum())

    eps = 1e-3
    max_rel_errors = {}
    
    for k in ["b3", "W3", "b2", "W2", "b1", "W1"]:
        arr = net.p[k]
        ana = analytic_grads[k]
        diffs = []
        n_samples = min(arr.size, 20)
        coords = [tuple(rng.integers(0, s) for s in arr.shape) for _ in range(n_samples)]
        for idx in coords:
            orig = arr[idx]
            arr[idx] = orig + eps
            lp = get_loss()
            arr[idx] = orig - eps
            lm = get_loss()
            arr[idx] = orig
            
            num = (lp - lm) / (2.0 * eps)
            a = float(ana[idx])
            denom = max(abs(a), abs(num), 1e-3)
            rel = abs(a - num) / denom
            diffs.append(rel)
            
        max_err = float(np.max(diffs))
        max_rel_errors[k] = max_err
        print(f"  Layer {k:2s}: max relative gradient error = {max_err:.4e}")

    # For float32 network with ReLU and MaxPool, tolerances <= 0.15 (15%) reflect single-precision secant approximations
    all_ok = all(err < 0.15 for err in max_rel_errors.values())
    print("Numerical gradient check:", "PASS" if all_ok else "FAIL")

    # Signal responsiveness test:
    # A true cSS-like patch (dark in MinIP, dark in Mean, high footprint) should produce higher logit than a bright patch
    dark_patch = np.zeros((1,) + IN_SHAPE, dtype=np.float32)
    dark_patch[0, 0] = -0.8 # MinIP very dark
    dark_patch[0, 1] = -0.5 # Mean dark
    dark_patch[0, 2] = 0.8  # High object footprint
    
    bright_patch = np.zeros((1,) + IN_SHAPE, dtype=np.float32)
    bright_patch[0, 0] = 0.5 # MinIP bright
    bright_patch[0, 1] = 0.5 # Mean bright
    bright_patch[0, 2] = 0.0 # No footprint
    
    X_train = np.stack([dark_patch[0]] * 10 + [bright_patch[0]] * 10)
    y_train = np.array([1.0] * 10 + [0.0] * 10, dtype=np.float32)
    g_train = np.array([f"pt_{i}" for i in range(20)])
    
    trained_net = SmallCNN(seed=123).fit(X_train, y_train, g_train, epochs=20, lr=0.01)
    dark_logit = float(trained_net.logit(dark_patch)[0])
    bright_logit = float(trained_net.logit(bright_patch)[0])
    
    print(f"Signal responsiveness test: dark_logit={dark_logit:.3f}, bright_logit={bright_logit:.3f}")
    assert dark_logit > bright_logit, f"Expected dark_logit ({dark_logit}) > bright_logit ({bright_logit})"
    print("Signal responsiveness test: PASS")

    if all_ok:
        print("ALL GRADIENT & RESPONSIVENESS CHECKS PASSED.")
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    check_cnn_gradients()
