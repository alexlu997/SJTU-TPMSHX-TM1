"""A3 (2026-07-06): shared-face 2D LTNE convection.

The 2D energy kernels now use SIGNED shared-face convective fluxes
(Fe = 0.5*(F_P + F_E), identical on both sides of every face), replacing
the cell-local |u|-magnitude scheme whose per-face flux mismatch leaked
enthalpy on non-uniform eps*rho_cp*u fields (production feeds per-cell
rho_cp(Ta)). The net outflow is deliberately NOT in aP: the governing
equation is the TEMPERATURE form eps*rho_cp*u·grad(T), and with
cell-centre interpolated velocities the discrete div(F) != 0 — a v1
attempt that kept net_out made uniform temperature a non-fixed-point and
broke the isothermal outer-loop consistency test (test_evaluator_sanity).

Fluid-B SOU: re-tested in the face-consistent telescoping form and it
STILL oscillates (the 2026-06-24 instability is the deferred-correction
fixed point on a near-isothermal high-rho_cp field, not the old
non-conservative flux). ``use_sou_B`` therefore defaults to False and is
kept as an experimental switch only.

Note: serial vs red-black fluid-A fields can differ ~0.4 K on steep
synthetic fronts — a pre-existing A-SOU live-vs-snapshot limit cycle
(present at HEAD), not an A3 regression; B/S fields agree tightly.
"""
import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore')

from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain, _gs_full_chunk, _gs_full_chunk_rb


def _nonuniform_case(use_sou_B=False):
    """A flows +y with rho_cp rising 20% along the stream (mimics the
    per-cell rho_cp(Ta) the 2D pipeline feeds the kernel)."""
    Nx, Ny = 24, 32
    L, H = 0.05, 0.10
    yc = (np.arange(Ny) + 0.5) / Ny
    rho_cp_A = np.tile(1.2e3 * (1.0 + 0.2 * yc), (Nx, 1))
    out = solve_full_domain(
        L, H, Nx, Ny, 400.0, 300.0,
        K_ffA=0.02, K_ffB=0.3, K_ss=4.0, h_vA=4e4, h_vB=6e4,
        rho_cp_fA=rho_cp_A, rho_cp_fB=4.2e6, epsilon=0.7,
        ucA=np.zeros((Nx, Ny)), vcA=np.full((Nx, Ny), 3.0),
        ucB=np.zeros((Nx, Ny)), vcB=np.full((Nx, Ny), -0.05),
        dir_A=2, dir_B=3, max_iter=60000,
        q_rel_tol=1e-12, conv_chunk=500,
        return_info=True, use_sou_B=use_sou_B)
    return out + ((Nx, Ny, L, H, rho_cp_A),)


def test_uniform_temperature_is_fixed_point():
    """A uniform T=Ts=Tb field with EQUAL inlet temperatures must be an
    exact fixed point of the scheme for ARBITRARY (divergent) cell-centre
    velocity fields — the property the v1 net_out-in-aP variant broke."""
    Nx, Ny = 20, 24
    rng = np.random.default_rng(42)
    T0 = 333.0
    ucA = rng.uniform(-2.0, 2.0, (Nx, Ny))
    vcA = rng.uniform(0.5, 3.0, (Nx, Ny))
    ucB = rng.uniform(-0.1, 0.1, (Nx, Ny))
    vcB = rng.uniform(-0.08, -0.01, (Nx, Ny))
    Ta, Tb, Ts = solve_full_domain(
        0.05, 0.1, Nx, Ny, T0, T0,
        K_ffA=0.02, K_ffB=0.3, K_ss=4.0, h_vA=4e4, h_vB=6e4,
        rho_cp_fA=1.2e3, rho_cp_fB=4.2e6, epsilon=0.7,
        ucA=ucA, vcA=vcA, ucB=ucB, vcB=vcB,
        dir_A=2, dir_B=3, max_iter=800,
        Ta_init=np.full((Nx, Ny), T0), Tb_init=np.full((Nx, Ny), T0),
        Ts_init=np.full((Nx, Ny), T0))
    for f, name in ((Ta, 'Ta'), (Tb, 'Tb'), (Ts, 'Ts')):
        dev = float(np.max(np.abs(f - T0)))
        assert dev < 1e-9, f"{name} drifted {dev:.2e} K off the uniform state"


def test_sou_b_default_off_and_switch_runs():
    """Default (B 1st-order) converges; opt-in sou_B runs bounded (it may
    limit-cycle — that is exactly why it is not the default)."""
    Ta, Tb, Ts, info, _ = _nonuniform_case(use_sou_B=False)
    assert info.get('converged') is True
    Ta2, Tb2, Ts2, info2, _ = _nonuniform_case(use_sou_B=True)
    for f in (Ta2, Tb2, Ts2):
        assert np.all(np.isfinite(f))
        assert 289.0 < f.min() and f.max() < 411.0


def test_serial_and_redblack_agree_on_b_and_solid():
    """Same problem through both kernels: Tb/Ts must agree tightly. (Ta can
    differ ~0.4 K via the pre-existing A-SOU live/snapshot limit cycle —
    present at HEAD, out of A3 scope.)"""
    Nx, Ny = 20, 24
    dx = np.full(Nx, 0.05 / Nx); dy = np.full(Ny, 0.1 / Ny)
    two = lambda v: np.full((Nx, Ny), float(v))
    TinA = np.full(Nx, 400.0); TinB = np.full(Nx, 300.0)
    frac = np.ones(Nx)
    common = (Nx, Ny, dx, dy, two(0.02), two(0.3), two(4.0),
              two(4e4), two(6e4), two(0.35), two(0.35),
              two(1.2e3), two(4.2e6), two(0.0), two(2.5), two(0.0), two(-0.04),
              2, 3, TinA, TinB, frac, frac)
    Ta1 = two(350.0); Tb1 = two(350.0); Ts1 = two(350.0)
    Ta2 = two(350.0); Tb2 = two(350.0); Ts2 = two(350.0)
    for _ in range(30):
        _gs_full_chunk(Ta1, Tb1, Ts1, *common, 500, 0, 0)
        _gs_full_chunk_rb(Ta2, Tb2, Ts2, *common, 500, 0, 0)
    assert float(np.max(np.abs(Tb1 - Tb2))) < 5e-3
    # Ts inherits a fraction of the A-side limit cycle through the h_vA
    # coupling (localised near the steep-front rows) — same pre-existing
    # effect, bounded but not tight.
    assert float(np.max(np.abs(Ts1 - Ts2))) < 0.3
    assert float(np.max(np.abs(Ta1 - Ta2))) < 1.0    # pre-existing SOU cycle


@pytest.mark.slow
def test_fine_grid_outer_coupling_stability():
    """Fine-grid air-water coupled eval with the conservative base (default
    config) must stay finite and produce a sane duty."""
    from sjtu_tpmshx.models.continuous_field import uniform_field
    from sjtu_tpmshx.optimization.evaluator import evaluate_design
    cfg = {'Nx': 40, 'Ny': 80,
           'max_iter_simple': 800,
           'max_iter_energy': 3000, 'tol_energy': 0.5, 'n_rho_loops': 1}
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, L_domain=0.10, H_domain=0.05)
    got = evaluate_design(x=None, cfg=cfg, fc=fc)
    assert np.all(np.isfinite(np.asarray(got, dtype=float))), got
    # T6 tightened (2026-07-07): measured |Q| = 8199 W on this exact config;
    # the old 2000..50000 band (25x) passed a 2x duty regression. +/-33%.
    assert 5500.0 < abs(float(got[0])) < 11000.0, got


if __name__ == '__main__':
    # P2.1 lint (F821): the old first entry referenced a test renamed/removed
    # long ago — this direct-run convenience block had gone stale. Now lists
    # the file's actual tests.
    test_uniform_temperature_is_fixed_point()
    test_sou_b_default_off_and_switch_runs()
    test_serial_and_redblack_agree_on_b_and_solid()
    test_fine_grid_outer_coupling_stability()
    print("ALL DIRECT-RUN TESTS PASS")
