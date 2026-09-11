"""Asymmetric porosity (ε_A ≠ ε_B) — 2D LTNE kernel parity tests (Phase 1).

Mirrors `test_asym_porosity_3d.py` at the kernel level. Guards:
  - the new asymmetric path: `solve_full_domain` runs (no NotImplementedError)
    and conserves energy (A→solid heat == solid→B heat, insulated solid);
  - the δ=0 bit-identity contract: explicit ε_A = ε_B = ε/2 reproduces the
    default single-`eps_f_arr` path bit-for-bit (golden 2D / Shanghai 2D safe);
  - the total-void guard still rejects ε_A + ε_B > ε.
"""

import numpy as np
import pytest

from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain


def _common_args(Nx=12, Ny=10):
    L, H = 0.1, 0.05
    T_inA, T_inB = 400.0, 300.0
    K_ffA = 0.025; K_ffB = 0.6; K_ss = 16.0
    h_vA = 500.0; h_vB = 2000.0
    rho_cp_fA = 1100.0; rho_cp_fB = 4.18e6
    epsilon = 0.75
    ucA = np.full((Nx, Ny), 1.5);  vcA = np.zeros((Nx, Ny))
    ucB = np.zeros((Nx, Ny));      vcB = np.full((Nx, Ny), -0.1)
    return dict(L=L, H=H, Nx=Nx, Ny=Ny,
                T_inA=T_inA, T_inB=T_inB,
                K_ffA=K_ffA, K_ffB=K_ffB, K_ss=K_ss,
                h_vA=h_vA, h_vB=h_vB,
                rho_cp_fA=rho_cp_fA, rho_cp_fB=rho_cp_fB,
                epsilon=epsilon,
                ucA=ucA, vcA=vcA, ucB=ucB, vcB=vcB,
                dir_A=0, dir_B=3,
                max_iter=4000, tol=1e-6)


def _solid_balance(args, Ta, Tb, Ts):
    """A→solid heat vs solid→B heat. Solid is insulated (zero-flux boundary
    stencil), so at convergence these two integrals must match."""
    Nx, Ny = args['Nx'], args['Ny']
    area = (args['L'] / Nx) * (args['H'] / Ny)
    Q_As = float(np.sum(args['h_vA'] * (Ta - Ts) * area))   # A → solid
    Q_sB = float(np.sum(args['h_vB'] * (Ts - Tb) * area))   # solid → B
    return Q_As, Q_sB


def test_asymmetric_runs_and_conserves():
    """ε_A ≠ ε_B (ε_A + ε_B ≤ ε) solves without NotImplementedError and the
    insulated-solid energy balance closes (A→solid == solid→B)."""
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    eps = args['epsilon']
    eps_A = np.full((Nx, Ny), 0.45)
    eps_B = np.full((Nx, Ny), 0.30)        # 0.45 + 0.30 = 0.75 = ε
    assert eps_A.mean() + eps_B.mean() <= eps + 1e-12

    Ta, Tb, Ts = solve_full_domain(**args, eps_A=eps_A, eps_B=eps_B)
    assert np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb)) and np.all(np.isfinite(Ts))

    Q_As, Q_sB = _solid_balance(args, Ta, Tb, Ts)
    rel = abs(Q_As - Q_sB) / max(abs(Q_As), abs(Q_sB), 1e-30)
    assert rel < 1e-3, f"solid energy balance broke: Q_As={Q_As:.3f} Q_sB={Q_sB:.3f} rel={rel:.2e}"


def test_asymmetric_differs_from_symmetric():
    """Per-side weighting actually bites: an asymmetric split moves the field
    away from the symmetric ε/2 result."""
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    Ta_s, Tb_s, Ts_s = solve_full_domain(**args)
    eps_A = np.full((Nx, Ny), 0.50)
    eps_B = np.full((Nx, Ny), 0.25)
    Ta_a, Tb_a, Ts_a = solve_full_domain(**args, eps_A=eps_A, eps_B=eps_B)
    assert not np.allclose(Ta_a, Ta_s) or not np.allclose(Tb_a, Tb_s)


def test_symmetric_explicit_is_bit_identical():
    """δ=0 contract: explicit ε_A = ε_B = ε/2 reproduces the default
    single-`eps_f_arr` path bit-for-bit (not approx — exactly)."""
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    half = np.full((Nx, Ny), 0.5 * args['epsilon'])

    Ta0, Tb0, Ts0 = solve_full_domain(**args)                      # default path
    Ta1, Tb1, Ts1 = solve_full_domain(**args, eps_A=half, eps_B=half)

    assert np.max(np.abs(Ta1 - Ta0)) == 0.0
    assert np.max(np.abs(Tb1 - Tb0)) == 0.0
    assert np.max(np.abs(Ts1 - Ts0)) == 0.0


def test_over_allocation_rejected():
    """ε_A + ε_B > ε is still a ValueError (total-void guard preserved)."""
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    eps_A = np.full((Nx, Ny), 0.50)
    eps_B = np.full((Nx, Ny), 0.40)        # 0.90 > 0.75 = ε
    with pytest.raises(ValueError):
        solve_full_domain(**args, eps_A=eps_A, eps_B=eps_B)


# ── Phase 2: end-to-end through Pipeline2D (δ split plumbing) ─────────────────

def _air_air_delta_cfg(delta):
    """Golden 2D air-air cfg with the offset δ set on the geometry."""
    from sjtu_tpmshx.runs._out._golden_2d import _air_air_cfg
    cc = _air_air_cfg()
    cc.geometry.delta_levelset = float(delta)
    return cc


def test_delta_pos_pipeline_runs_and_conserves():
    """A δ≠0 config runs end-to-end through Pipeline2D, returns finite headline
    scalars, and the A↔B energy balance still closes (split conserves)."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    p0 = Pipeline2D(_air_air_delta_cfg(0.0))
    raw0 = p0.run_solvers(p0.build_fields()).metadata['diagnostics']
    pd = Pipeline2D(_air_air_delta_cfg(0.6))
    rawd = pd.run_solvers(pd.build_fields()).metadata['diagnostics']

    assert np.isfinite(rawd['Q_total']) and rawd['Q_total'] > 0.0
    assert np.isfinite(rawd['dP_A']) and np.isfinite(rawd['dP_B'])
    # The asymmetric split must not degrade the AB energy balance relative to
    # the symmetric run (conservation is preserved by the ε·split).
    assert rawd['energy_imbalance_rel'] <= max(0.05, 1.5 * raw0['energy_imbalance_rel'])


def test_delta_pos_differs_from_symmetric_pipeline():
    """δ≠0 actually drives an asymmetric run end-to-end — at least one headline
    scalar moves vs the symmetric δ=0 path (guards that δ is plumbed at all)."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    r0 = Pipeline2D(_air_air_delta_cfg(0.0)).run()
    rd = Pipeline2D(_air_air_delta_cfg(0.6)).run()
    assert (rd.Q_W != r0.Q_W) or (rd.dP_A_Pa != r0.dP_A_Pa) or (rd.T_out_A_K != r0.T_out_A_K)


if __name__ == '__main__':
    test_symmetric_explicit_is_bit_identical()
    test_asymmetric_runs_and_conserves()
    test_asymmetric_differs_from_symmetric()
    test_over_allocation_rejected()
    test_delta_pos_pipeline_runs_and_conserves()
    test_delta_pos_differs_from_symmetric_pipeline()
    print("All 2D asym tests PASS")
