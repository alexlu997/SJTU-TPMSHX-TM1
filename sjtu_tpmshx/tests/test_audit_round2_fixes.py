"""Round-2 adversarial-audit fixes (2026-06-26).

- r2-runs-01: design.sizing build-envelope caps must be read from the
  environment AT IMPORT, so loky-spawned sizing workers pick up a relaxed cap
  the parent set before import.
"""
import os
import subprocess
import sys
from pathlib import Path


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
