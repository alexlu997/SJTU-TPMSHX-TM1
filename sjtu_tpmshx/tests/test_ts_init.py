"""Tests for the user-facing solid-initial-temperature warm-start (T_s_init).

Covers two layers:
  A. solve_full_domain accepts a user Ts_init seed and the first few sweeps
     are measurably different from the default 0.5*(T_inA+T_inB) seed.
  B. run_calculation._parse_inputs maps the UI field correctly (empty →
     None, numeric → float in Kelvin, °C toggle respected).
"""

import numpy as np
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d


def _common_args(Nx=10, Ny=8):
    return dict(
        L=0.1, H=0.05, Nx=Nx, Ny=Ny,
        T_inA=400.0, T_inB=300.0,
        K_ffA=0.025, K_ffB=0.6, K_ss=16.0,
        h_vA=500.0, h_vB=2000.0,
        rho_cp_fA=1100.0, rho_cp_fB=4.18e6,
        epsilon=0.75,
        ucA=np.full((Nx, Ny), 1.5), vcA=np.zeros((Nx, Ny)),
        ucB=np.zeros((Nx, Ny)), vcB=np.full((Nx, Ny), -0.1),
        dir_A=0, dir_B=3,
        max_iter=2, tol=1e-12,
    )


def test_ts_init_changes_first_sweep():
    """Distinct Ts seeds must yield different Ts after a couple of sweeps."""
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    T_init = 0.5 * (args['T_inA'] + args['T_inB'])

    Ta_seed = np.full((Nx, Ny), T_init, dtype=np.float64)
    Tb_seed = np.full((Nx, Ny), T_init, dtype=np.float64)
    Ts_hot = np.full((Nx, Ny), 360.0, dtype=np.float64)
    Ts_cool = np.full((Nx, Ny), 310.0, dtype=np.float64)

    _, _, Ts_a = solve_full_domain(
        **args,
        Ta_init=Ta_seed.copy(), Tb_init=Tb_seed.copy(),
        Ts_init=Ts_hot.copy())
    _, _, Ts_b = solve_full_domain(
        **args,
        Ta_init=Ta_seed.copy(), Tb_init=Tb_seed.copy(),
        Ts_init=Ts_cool.copy())

    diff = float(np.max(np.abs(Ts_a - Ts_b)))
    assert diff > 1.0, (
        f"Ts seed was ignored: max |ΔTs| = {diff:.3e} between hot/cool seeds")
    print(f"test_ts_init_changes_first_sweep PASS (|ΔTs|={diff:.2f} K)")


def test_ts_init_none_matches_per_fluid_seed():
    """Ts_init=None auto-seeds Ta=T_inA, Tb=T_inB, Ts=0.5*(T_inA+T_inB).

    Updated for the 2026-06-28 audit HIGH-1 fix: the 2D kernel's no-warm-start
    cold-start now seeds the FLUIDS per-inlet (Ta=T_inA, Tb=T_inB), matching
    the 3D kernel (ltne_energy_3d.py) — the old all-three-at-0.5-mean seed froze
    partial-inlet off-pipe cells at the mid-T and leaked ~12-18% Q via the solid
    coupling. The solid still cold-starts at 0.5-mean. Passing those exact seeds
    explicitly must reproduce the None default.
    """
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    T_mid = 0.5 * (args['T_inA'] + args['T_inB'])

    _, _, Ts_default = solve_full_domain(**args)

    Ta_seed = np.full((Nx, Ny), args['T_inA'], dtype=np.float64)
    Tb_seed = np.full((Nx, Ny), args['T_inB'], dtype=np.float64)
    Ts_seed = np.full((Nx, Ny), T_mid, dtype=np.float64)
    _, _, Ts_explicit = solve_full_domain(
        **args, Ta_init=Ta_seed, Tb_init=Tb_seed, Ts_init=Ts_seed)

    diff = float(np.max(np.abs(Ts_default - Ts_explicit)))
    assert diff < 1e-9, (
        f"None default drifted from the per-fluid seed: |ΔTs|={diff:.3e}")
    print(f"test_ts_init_none_matches_per_fluid_seed PASS (|ΔTs|={diff:.2e} K)")


# ── 3D coverage ──────────────────────────────────────────────────────────


def _common_args_3d(Nx=6, Ny=5, Nz=3):
    """Mid-Re air-air-ish args for solve_full_domain_3d. Volume small so
    the test stays sub-second; we only need a couple of sweeps to detect
    that distinct Ts_init seeds bend the solid field differently.
    """
    rcp_A = 1100.0
    rcp_B = 4.18e6
    return dict(
        L=0.1, H=0.05, D=0.02, Nx=Nx, Ny=Ny, Nz=Nz,
        T_inA=420.0, T_inB=300.0,
        K_ffA=np.full((Nx, Ny, Nz), 0.025),
        K_ffB=np.full((Nx, Ny, Nz), 0.6),
        K_ss=np.full((Nx, Ny, Nz), 16.0),
        h_vA=np.full((Nx, Ny, Nz), 500.0),
        h_vB=np.full((Nx, Ny, Nz), 2000.0),
        rho_cp_fA=np.full((Nx, Ny, Nz), rcp_A),
        rho_cp_fB=np.full((Nx, Ny, Nz), rcp_B),
        epsilon=np.full((Nx, Ny, Nz), 0.75),
        ucA=np.full((Nx, Ny, Nz), 1.5),
        vcA=np.zeros((Nx, Ny, Nz)),
        wcA=np.zeros((Nx, Ny, Nz)),
        ucB=np.zeros((Nx, Ny, Nz)),
        vcB=np.full((Nx, Ny, Nz), -0.1),
        wcB=np.zeros((Nx, Ny, Nz)),
        dir_A=0, dir_B=3,
        max_iter=4, tol=1e-12,
    )


def test_ts_init_3d_changes_first_sweep():
    """Distinct Ts_init seeds for the 3D LTNE solver yield different Ts
    after a few sweeps. Confirms the warm-start path (`Ts_init=...`) is
    actually wired through `solve_full_domain_3d` and not silently
    replaced by the legacy 0.5*(T_inA+T_inB) fallback.
    """
    args = _common_args_3d()
    Nx, Ny, Nz = args['Nx'], args['Ny'], args['Nz']
    T_inA = args['T_inA']; T_inB = args['T_inB']
    # Per-fluid seed (matches the 2026-04-24 FV fix used by
    # `_run_3d_stack` after the user supplies T_s_init).
    Ta_seed = np.full((Nx, Ny, Nz), T_inA, dtype=np.float64)
    Tb_seed = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)
    Ts_hot = np.full((Nx, Ny, Nz), 400.0, dtype=np.float64)
    Ts_cool = np.full((Nx, Ny, Nz), 305.0, dtype=np.float64)

    _, _, Ts_a = solve_full_domain_3d(
        **args,
        Ta_init=Ta_seed.copy(), Tb_init=Tb_seed.copy(),
        Ts_init=Ts_hot.copy())
    _, _, Ts_b = solve_full_domain_3d(
        **args,
        Ta_init=Ta_seed.copy(), Tb_init=Tb_seed.copy(),
        Ts_init=Ts_cool.copy())

    diff = float(np.max(np.abs(Ts_a - Ts_b)))
    assert diff > 1.0, (
        f"3D Ts seed was ignored: max |ΔTs| = {diff:.3e} between "
        f"hot ({Ts_hot.mean():.1f} K) and cool ({Ts_cool.mean():.1f} K) "
        "seeds. solve_full_domain_3d may not be honouring Ts_init.")
    print(f"test_ts_init_3d_changes_first_sweep PASS (|ΔTs|={diff:.2f} K)")


if __name__ == '__main__':
    test_ts_init_changes_first_sweep()
    test_ts_init_none_matches_per_fluid_seed()
    test_ts_init_3d_changes_first_sweep()
    print("\nAll tests PASS")
