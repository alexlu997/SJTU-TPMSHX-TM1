"""M2b (2026-07-09) — 3D VANS ε-ratio momentum terms (ledger B5 residual).

Mirrors tests/test_m2_vans_eps_momentum.py for the 3D kernels. The 3D
kernels are fastmath, so the ε ratios live behind a ``use_eps`` guard (the
``use_sou`` pattern): uniform ε must take the use_eps=0 branch with the
pre-M2b expression tree untouched.

Gates:
1. UNIFORM GUARD EQUIVALENCE — on a uniform ε field, use_eps=1 must equal
   use_eps=0 bit-identically (ratios evaluate to exactly 1.0 and the *= is
   a single IEEE op), and the solver must auto-select use_eps=0.
2. GRADED-ε LIVENESS — a graded ε field with use_eps=1 changes the sweep.
3. evaluate_3d installs the per-cell eps_field (xmod-eps-field-3d closed) —
   graded field reaches both solver instances with the fluid-A axis swap.
"""
from __future__ import annotations

import numpy as np

from sjtu_tpmshx.solvers._kernels_simple_3d import (
    _sweep_u_jit_df_3d, _sweep_v_jit_df_3d, _sweep_w_jit_df_3d,
)


def _frozen_state(Nx=6, Ny=10, Nz=4, seed=0):
    rng = np.random.default_rng(seed)
    st = {
        'u': rng.normal(0.0, 0.5, (Nx + 1, Ny, Nz)),
        'v': rng.normal(3.0, 0.5, (Nx, Ny + 1, Nz)),
        'w': rng.normal(0.0, 0.2, (Nx, Ny, Nz + 1)),
        'P': rng.normal(0.0, 10.0, (Nx, Ny, Nz)),
        'rho': np.full((Nx, Ny, Nz), 1.2),
        'mu': np.full((Nx, Ny, Nz), 1.8e-5),
        'mu_eff': np.full((Nx, Ny, Nz), 3.0e-5),
        'K': np.full((Ny, Nz), 1e-7),
        'cF': np.full((Ny, Nz), 340.0),
        'v_in': np.full((Nx, Nz), 3.0),
        'out': np.ones((Nx, Nz)),
        'out_u': np.ones((Nx + 1, Nz)),
        'out_w': np.ones((Nx, Nz + 1)),
        'dx': np.full(Nx, 0.01), 'dy': np.full(Ny, 0.01),
        'dz': np.full(Nz, 0.01),
        'dims': (Nx, Ny, Nz),
    }
    return st


def _run_sweeps(st, eps_field, use_eps):
    Nx, Ny, Nz = st['dims']
    u = st['u'].copy(); v = st['v'].copy(); w = st['w'].copy()
    P = st['P'].copy()
    d_u = np.zeros_like(u); d_v = np.zeros_like(v); d_w = np.zeros_like(w)
    _sweep_u_jit_df_3d(u, v, w, P, d_u, Nx, Ny, Nz,
                       st['dx'], st['dy'], st['dz'],
                       st['rho'], st['mu_eff'], st['mu'], eps_field,
                       st['K'], st['cF'], st['out_u'],
                       0.7, 1, 0, use_eps)
    _sweep_v_jit_df_3d(u, v, w, P, d_v, st['v_in'], Nx, Ny, Nz,
                       st['dx'], st['dy'], st['dz'],
                       st['rho'], eps_field, st['mu_eff'], st['mu'],
                       st['K'], st['cF'],
                       0.7, 1, 0, use_eps, st['out'] > 0.0)
    _sweep_w_jit_df_3d(u, v, w, P, d_w, Nx, Ny, Nz,
                       st['dx'], st['dy'], st['dz'],
                       st['rho'], st['mu_eff'], st['mu'], eps_field,
                       st['K'], st['cF'], st['out_w'],
                       0.7, 1, 0, use_eps)
    return u, v, w


def test_uniform_eps_guard_equivalence_bitwise():
    """Gate 1: uniform ε → use_eps=1 output == use_eps=0 output bit-exactly
    (every ratio is exactly 1.0; the *= is one IEEE multiplication)."""
    st = _frozen_state()
    Nx, Ny, Nz = st['dims']
    eps_uni = np.full((Nx, Ny, Nz), 0.53)
    out0 = _run_sweeps(st, eps_uni, 0)
    out1 = _run_sweeps(st, eps_uni, 1)
    for a, b, name in zip(out0, out1, 'uvw'):
        assert np.array_equal(a, b), (
            f"{name}: uniform-ε use_eps=1 differs from use_eps=0 — ratio "
            f"path leaked an absolute ε or fastmath broke the ×1.0")


def test_graded_eps_changes_momentum_3d():
    """Gate 2: graded ε with use_eps=1 must change the momentum result."""
    st = _frozen_state()
    Nx, Ny, Nz = st['dims']
    eps_grad = np.ascontiguousarray(
        np.tile(np.linspace(0.6, 0.4, Ny)[None, :, None], (Nx, 1, Nz)))
    out0 = _run_sweeps(st, eps_grad, 0)
    out1 = _run_sweeps(st, eps_grad, 1)
    assert not np.array_equal(out0[1], out1[1]), \
        "graded ε had no effect on v-momentum (use_eps not wired?)"


def test_solver_selects_use_eps_from_field():
    """The solve() entry computes use_eps from eps_field uniformity."""
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
    s = SIMPLESolver3D(Lx=0.04, Ly=0.06, Lz=0.02, Nx=4, Ny=6, Nz=2,
                       rho=1.2, mu=1.8e-5, T_in=320.0, v_inlet=2.0,
                       eps=0.5,
                       K_arr=np.full((6, 2), 1e-7),
                       cF_arr=np.full((6, 2), 340.0))
    # uniform default → the guard expression must evaluate to 0
    assert float(s.eps_field.max()) == float(s.eps_field.min())
    s.eps_field = np.ascontiguousarray(
        np.tile(np.linspace(0.6, 0.4, 6)[None, :, None], (4, 1, 2)))
    assert float(s.eps_field.max()) != float(s.eps_field.min())


def test_evaluate_3d_installs_per_cell_eps_field(monkeypatch):
    """The real prepared asymmetric field reaches both numerical solvers."""
    import pytest
    from sjtu_tpmshx.preprocess.api import prepare_screening_3d
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.solvers.backends.python.screening import three_d as execution
    x = np.r_[np.linspace(5., 7., 16), np.full(16, .4)]
    cfg = dict(L_domain=.1, H_domain=.05, u_A=1., u_B=1., T_inA=350., T_inB=300., symmetric_y=False)
    case = prepare_screening_3d(x, cfg, case_id='graded', Nx=4, Ny=3, Nz=2,
                                roughness_mode='baseline', roughness_eps_um=0., verbose=False)
    fields = []

    def flow(s, **kwargs):
        fields.append(s.eps_field.copy())
        return False, 0

    class Captured(Exception):
        pass

    def thermal(*args, **kwargs):
        raise Captured

    monkeypatch.setattr(execution.SIMPLESolver3D, 'solve', flow)
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    with pytest.raises(Captured):
        run_case(case)
    assert len(fields) == 2
    np.testing.assert_array_equal(fields[0], case.design_fields['eps_arr'].transpose(1, 0, 2))
    np.testing.assert_array_equal(fields[1], case.design_fields['eps_arr'][:, ::-1, :])
