"""Round-2 adversarial-audit fixes (2026-06-26).

- r2-runs-01: design.sizing build-envelope caps must be read from the
  environment AT IMPORT, so loky-spawned sizing workers pick up a relaxed cap
  the parent set before import.
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# ── r2-runs-01: build caps from env at import (fresh subprocess) ────────────
def _caps_in_subprocess(env_extra):
    env = dict(os.environ, PYTHONPATH=str(ROOT), **env_extra)
    out = subprocess.check_output(
        [sys.executable, '-c',
         'import sjtu_tpmshx.design.sizing as S; print(S.S_MAX, S.LX_MAX)'],
        env=env, text=True, stderr=subprocess.STDOUT)
    return out.strip().split()


def test_sizing_caps_default_without_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ('TPMSHX_BUILD_S_MAX', 'TPMSHX_BUILD_LX_MAX')}
    out = subprocess.check_output(
        [sys.executable, '-c', 'import sjtu_tpmshx.design.sizing as S; print(S.S_MAX, S.LX_MAX)'],
        env=dict(env, PYTHONPATH=str(ROOT)), text=True)
    assert out.strip().split() == ['0.45', '0.45']


def test_sizing_caps_relaxed_via_env():
    out = _caps_in_subprocess({'TPMSHX_BUILD_S_MAX': '2.0',
                               'TPMSHX_BUILD_LX_MAX': '2.0'})
    assert out == ['2.0', '2.0']


# ── xmod-eps: CLOSED by M2b (2026-07-09). evaluate_3d now installs the
# per-cell eps_field, so the mean-ε approximation (and its one-shot warning)
# is retired. The contract flips: NO graded warning may fire — graded or
# uniform — and a resurfacing warning means the installation regressed.
def test_evaluate_3d_no_graded_mean_eps_warning():
    import warnings as W
    from sjtu_tpmshx.optimization.evaluator_3d import evaluate_design_3d
    x = np.concatenate([np.array([5., 6., 7., 8., 5.5, 6.5, 7.5, 6.]),
                        np.array([0.40, 0.45, 0.50, 0.45, 0.42, 0.48, 0.46, 0.44])])
    cfg = {'Nx_3d': 8, 'Ny_3d': 6, 'Nz_3d': 3, 'max_outer_3d': 1,
           'max_iter_energy': 400, 'tol_energy': 0.5}
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        evaluate_design_3d(x, cfg)
    assert not any('graded' in str(w.message).lower() for w in rec), \
        "mean-ε graded warning resurfaced — eps_field installation regressed?"


def test_evaluate_3d_uniform_no_graded_warn():
    import warnings as W
    from sjtu_tpmshx.optimization.evaluator_3d import evaluate_design_3d
    x = np.concatenate([np.full(8, 6.0), np.full(8, 0.45)])   # uniform L, t
    cfg = {'Nx_3d': 8, 'Ny_3d': 6, 'Nz_3d': 3, 'max_outer_3d': 1,
           'max_iter_energy': 400, 'tol_energy': 0.5}
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        evaluate_design_3d(x, cfg)
    assert not any('graded' in str(w.message).lower() for w in rec)
