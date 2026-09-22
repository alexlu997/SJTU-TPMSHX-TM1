"""M2 (2026-07-09) — VANS ε-ratio momentum terms, regression + physics gates.

Ledger B5 / plan ZONED-OPTIMIZATION-PLAN-CN §六 M2: the 2D momentum kernels
discretize the ε-DIVIDED volume-averaged form — every flux face carries
r_f = ε_f/ε_CV on both the convective flux and the diffusion conductance;
the pressure term needs no factor (−ε∇p/ε cancels) and the DF drag is
untouched (calibration-anchored).

Three gates:
1. UNIFORM-ε INVARIANCE — the kernels must be a function of ε RATIOS only:
   two different uniform ε values on otherwise identical frozen inputs must
   produce bit-identical output. This is stronger than "old vs new parity"
   (covered by the golden gates) — it proves no absolute-ε leaked in.
2. GRADED-ε LIVENESS — a graded ε field must change the momentum result
   (the new terms are actually wired, not dead).
3. GRADED-CHANNEL PHYSICS — end-to-end incompressible solve through a
   streamwise ε contraction: ε·ρ·v cross-sectional mass flux conserved and
   the velocity accelerates by the ε ratio (the "nozzle" that pre-M2
   momentum could not feel consistently).
"""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers._kernels_simple_2d import _sweep_u_jit_df, _sweep_v_jit_df


def _make_solver(eps=0.6, v_inlet=6.0, Nx=10, Ny=30,
                 fluid_type='incompressible'):
    return SIMPLESolver(
        W=0.042, H=0.09, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=eps, r_h=1e-3,
        rho=1.2, mu=1.8e-5, T_in=322.0,
        inlet_lo=0.0, inlet_hi=0.042, v_inlet=v_inlet,
        fluid_type=fluid_type,
        wall_refine=False,
    )


def _frozen_sweep_pair(eps_field_a, eps_field_b, s):
    """Run ONE u- and v-sweep from the same frozen state under two ε fields;
    return the four resulting arrays."""
    rng = np.random.default_rng(0)
    u0 = rng.normal(0.0, 0.5, s.u.shape)
    v0 = rng.normal(3.0, 0.5, s.v.shape)
    P0 = rng.normal(0.0, 10.0, s.P.shape)
    out = []
    # 2026-07-10 lateral-K: kernels take 2D K/cF fields — tile the per-row
    # arrays (laterally uniform → bit-identical to the old 1D path).
    K2d = np.ascontiguousarray(np.repeat(s._K_arr[None, :], s.Nx, axis=0))
    cF2d = np.ascontiguousarray(np.repeat(s._cF_arr[None, :], s.Nx, axis=0))
    for eps_f in (eps_field_a, eps_field_b):
        u = u0.copy(); v = v0.copy(); P = P0.copy()
        d_u = np.zeros_like(s.d_u); d_v = np.zeros_like(s.d_v)
        _sweep_u_jit_df(u, v, P, d_u, s.outlet_u_frac,
                        s.Nx, s.Ny, s.dx_arr, s.dy_arr,
                        s.rho_field, s._mu_eff_field,
                        K2d, cF2d, s.mu_field, eps_f, 0.7, 1, 0.0)
        _sweep_v_jit_df(u, v, P, d_v, s.inlet_frac, s.v_inlet_field,
                        s.outlet_frac,
                        s.Nx, s.Ny, s.dx_arr, s.dy_arr,
                        s.rho_field, s._mu_eff_field,
                        K2d, cF2d, s.mu_field, eps_f, 0.7, 1, 0.0)
        out.append((u, v))
    return out


def test_uniform_eps_value_never_enters_momentum():
    """Gate 1: kernels consume ε RATIOS only — any uniform ε value gives
    bit-identical momentum output (r ≡ 1.0 exactly for every face)."""
    s = _make_solver()
    eps_a = np.full((s.Nx, s.Ny), 0.60, dtype=np.float64)
    eps_b = np.full((s.Nx, s.Ny), 0.37, dtype=np.float64)
    (u_a, v_a), (u_b, v_b) = _frozen_sweep_pair(eps_a, eps_b, s)
    assert np.array_equal(u_a, u_b), "uniform-ε value leaked into u-momentum"
    assert np.array_equal(v_a, v_b), "uniform-ε value leaked into v-momentum"


def test_graded_eps_changes_momentum():
    """Gate 2: a graded ε field must actually change the sweep result."""
    s = _make_solver()
    eps_uni = np.full((s.Nx, s.Ny), 0.60, dtype=np.float64)
    eps_grad = np.tile(np.linspace(0.6, 0.4, s.Ny)[None, :], (s.Nx, 1))
    eps_grad = np.ascontiguousarray(eps_grad)
    (u_u, v_u), (u_g, v_g) = _frozen_sweep_pair(eps_uni, eps_grad, s)
    assert not np.array_equal(v_u, v_g), "graded ε had no momentum effect"


def test_graded_channel_mass_conservation_and_acceleration():
    """Gate 3: streamwise ε contraction 0.6 → 0.4 (incompressible, so density
    plays no role): the ε·ρ·v cross-sectional mass flux must be conserved
    along the channel, and the bulk velocity must accelerate by ≈ ε_in/ε_out
    (quasi-1D continuity, the nozzle effect)."""
    s = _make_solver()
    eps_grad = np.tile(np.linspace(0.6, 0.4, s.Ny)[None, :], (s.Nx, 1))
    s.eps_field = np.ascontiguousarray(eps_grad, dtype=np.float64)
    conv, _ = s.solve(max_iter=4000, verbose=False)

    # ε·ρ·v mass flux per cross-section (v faces j=0..Ny; use interior faces,
    # face ε/ρ = mean of adjacent cells)
    fluxes = []
    for j in range(1, s.Ny):
        eps_f = 0.5 * (s.eps_field[:, j - 1] + s.eps_field[:, j])
        rho_f = 0.5 * (s.rho_field[:, j - 1] + s.rho_field[:, j])
        fluxes.append(float(np.sum(eps_f * rho_f * s.v[:, j] * s.dx_arr)))
    fluxes = np.asarray(fluxes)
    rel_spread = (fluxes.max() - fluxes.min()) / abs(fluxes.mean())
    assert rel_spread < 0.02, (
        f"ε·ρ·v cross-flux not conserved along graded channel: "
        f"spread {rel_spread:.3%}")

    # Nozzle acceleration: bulk v near outlet vs near inlet ≈ ε_in/ε_out.
    v_in_bulk = float(np.mean(s.v[:, 2]))
    v_out_bulk = float(np.mean(s.v[:, s.Ny - 2]))
    eps_in = float(np.mean(s.eps_field[:, 2]))
    eps_out = float(np.mean(s.eps_field[:, s.Ny - 2]))
    expected = eps_in / eps_out
    assert v_out_bulk / v_in_bulk == pytest.approx(expected, rel=0.05), (
        f"nozzle acceleration off: v ratio {v_out_bulk / v_in_bulk:.3f} vs "
        f"ε ratio {expected:.3f}")
