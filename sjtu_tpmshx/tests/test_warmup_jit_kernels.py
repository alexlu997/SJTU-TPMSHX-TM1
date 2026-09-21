"""Imports must remain cancellable setup; explicit warmup still covers LTNE routes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('module,symbol', [
    ('simple_solver', '_assemble_pp_data_jit'),
    ('simple_solver_3d', '_sweep_u_jit_df_3d'),
    ('ltne_energy', '_gs_full_chunk'),
    ('ltne_energy_3d', '_gs_full_chunk_3d_stag'),
])
def test_import_does_not_compile_solver_kernels(module, symbol):
    code = (
        f"from sjtu_tpmshx.solvers import {module} as M;"
        f"assert not M.{symbol}.signatures"
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, cwd=ROOT, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]


def test_explicit_warmup_compiles_all_3d_ltne_routes():
    # Retain the earlier missing-signature regression, without causing it on
    # import before the real solver's cooperative cancellation is reachable.
    code = (
        "from sjtu_tpmshx.solvers import ltne_energy_3d as M;"
        "M._warmup_jit();"
        "assert M._gs_full_chunk_3d.signatures;"
        "assert M._gs_full_chunk_3d_stag.signatures;"
        "assert M._gs_full_chunk_3d_stag_rb.signatures"
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, cwd=ROOT, timeout=180)
    assert result.returncode == 0, result.stderr[-2000:]
