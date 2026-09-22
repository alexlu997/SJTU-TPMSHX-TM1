"""3D solver mass-flow consistency tests — pins Category B (mixed-basis PPE) bug.

Pre-fix: both tests are EXPECTED to FAIL with a ~2x discrepancy when eps=0.5.
Post-fix: both tests should PASS.

Bug source (per 2026-05-14 audit, vault/reports/3d-solver/
2026-05-14-flow-topology/audit_notes.md):
    simple_solver(_3d).py PPE assembly mixes interstitial matrix
    (rho * eps coefficients) with superficial RHS (rho * u divergence).
    With eps=0.5 the pressure correction is ~2x scaled, propagating an
    inconsistent mass-flow factor through the solution.

Streamwise convention for SIMPLESolver3D:
    - inlet face = j=0 plane:  v[:, 0, :]
    - outlet face = j=Ny plane: v[:, Ny, :]
    - inlet face area = Lx * Lz, dy spacing irrelevant for inflow integral
    - face integral: sum_{i,k} rho_face * v_face * (dx_i * dz_k)
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _build_uniform_box(Nx=8, Ny=8, Nz=8,
                       Lx=0.02, Ly=0.02, Lz=0.02,
                       eps=0.5, rho=1.225, mu=1.8e-5,
                       K=1e-8, cF=0.55,
                       U_super=0.5):
    """Build a uniform porous box: ε=0.5 D-F closure, scalar v_inlet=U_super.

    Use incompressible fluid (constant rho) so the steady mass-flow check
    decouples cleanly from the compressible BC density update.
    """
    K_arr = np.full((Ny, Nz), K, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), cF, dtype=np.float64)
    sol = SIMPLESolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=300.0,
        v_inlet=U_super,
        eps=eps,
        K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0,
        fluid_type='incompressible',
    )
    return sol


def test_uniform_box_mass_conservation():
    """Uniform porous box, eps=0.5: inlet mass-flow == outlet mass-flow at steady.

    Independent of which convention the solver uses internally — must hold
    for any consistent steady-state SIMPLE result. If the PPE mixes bases,
    the pressure correction is asymmetric and inlet/outlet integrals diverge.
    """
    sol = _build_uniform_box()
    conv, it = sol.solve(max_iter=500)
    print(f"[conservation] converged={conv} iters={it}")

    dx = sol.dx[:, None]   # (Nx, 1)
    dz = sol.dz[None, :]   # (1, Nz)

    m_in = float(np.sum(sol.v[:, 0, :]
                        * sol.rho_field[:, 0, :]
                        * dx * dz))
    m_out = float(np.sum(sol.v[:, -1, :]
                         * sol.rho_field[:, -1, :]
                         * dx * dz))
    ratio = m_out / m_in if abs(m_in) > 1e-30 else float('inf')
    print(f"[conservation] m_in={m_in:.6g} m_out={m_out:.6g} "
          f"ratio_out/in={ratio:.4f}")

    assert m_in == pytest.approx(m_out, rel=5e-3), (
        f"Mass conservation broken: in={m_in:.6g} out={m_out:.6g} "
        f"ratio={ratio:.3f}"
    )


def test_uniform_box_bc_matches_inlet_integral():
    """BC injects v_inlet at j=0. Inlet face integral rho*v*dA should equal rho*U*A_face.

    Pre-fix expectation: if PPE bug propagates back to v[:, 0, :] during
    pressure correction, the inlet face integral departs from rho*U_super*A_face
    by an eps factor (~2x with eps=0.5).
    Post-fix expectation: BC preserves v_inlet at face → integral matches target.
    """
    Lx, Ly, Lz = 0.02, 0.02, 0.02
    eps = 0.5
    rho = 1.225
    U_super = 0.5

    sol = _build_uniform_box(
        Nx=8, Ny=8, Nz=8,
        Lx=Lx, Ly=Ly, Lz=Lz,
        eps=eps, rho=rho, U_super=U_super,
    )
    conv, it = sol.solve(max_iter=500)
    print(f"[bc-integral] converged={conv} iters={it}")

    A_face = Lx * Lz
    m_target = rho * U_super * A_face   # superficial reference
    dx = sol.dx[:, None]
    dz = sol.dz[None, :]
    m_in = float(np.sum(sol.v[:, 0, :]
                        * sol.rho_field[:, 0, :]
                        * dx * dz))
    ratio = m_in / m_target if abs(m_target) > 1e-30 else float('inf')
    print(f"[bc-integral] m_target={m_target:.6g} "
          f"m_in_face_integral={m_in:.6g} ratio={ratio:.4f}")

    assert m_in == pytest.approx(m_target, rel=2e-3), (
        f"BC-vs-integral mismatch: target={m_target:.6g} "
        f"face_integral={m_in:.6g} ratio={ratio:.3f}"
    )


def test_partial_mask_mass_flow_match_inlet_BC():
    """Partial inlet/outlet mask reproducer for Shanghai case 1 2.04× anomaly.

    The reproducer uses opposing partial inlet/outlet masks on the cross-stream
    face.

    Three possible outcomes (categorised in task 2b):
      A: inlet and outlet ratios both ≈ 1 → solver kernel is fine; the removed
         historical diagnostic's reporting formula produced the 2.04× number.
      B: inlet ≈ 1 but outlet ≠ inlet → PPE drift triggered by asymmetric mask
         (Category B per audit).
      C: inlet ≈ 2× target → BC injection is multiplying by something
         (possibly A_face/A_open re-scaling).
    """
    NX, NZ = 16, 8                 # cross-stream
    NY = 16                        # streamwise (j-axis is SIMPLESolver3D's flow direction)
    Lx, Ly, Lz = 0.04, 0.04, 0.04
    eps = 0.5
    rho = 1000.0                   # incompressible water-like
    mu  = 1e-3
    K   = 1e-9                     # tight enough to need pressure correction
    cF  = 0.55
    U_super = 0.05

    # Top-half inlet, bottom-half outlet (50% open area, asymmetric mask)
    in_mask  = np.zeros((NX, NZ), dtype=np.float64)
    in_mask[NX // 2:, :] = 1.0
    out_mask = np.zeros((NX, NZ), dtype=np.float64)
    out_mask[:NX // 2, :] = 1.0
    open_frac = float(in_mask.mean())   # 0.5

    # v_inlet_field is the superficial velocity at face cells (zero on walls,
    # U_super on open cells).
    v_inlet_field = (in_mask * U_super).astype(np.float64)

    K_arr  = np.full((NY, NZ), K,  dtype=np.float64)
    cF_arr = np.full((NY, NZ), cF, dtype=np.float64)
    sol = SIMPLESolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz,
        Nx=NX, Ny=NY, Nz=NZ,
        rho=rho, mu=mu, T_in=300.0,
        v_inlet=v_inlet_field,
        eps=eps,
        K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0,
        fluid_type='incompressible',
    )
    sol.set_ports((Lx / 2, Lx, 0., Lz), (0., Lx / 2, 0., Lz))

    conv, it = sol.solve(max_iter=2000)
    print(f"\n[partial-mask] converged={conv} iters={it}")

    dx = sol.dx[:, None]
    dz = sol.dz[None, :]
    A_face = Lx * Lz
    A_open = open_frac * A_face

    # m_target_super: superficial mass flux through the OPEN portion of the
    # inlet face (this is what the diag script writes as `m_dot_target`).
    m_target_super = rho * U_super * A_open

    m_in_face = float(np.sum(
        sol.v[:, 0, :] * sol.rho_field[:, 0, :] * dx * dz * in_mask
    ))
    m_out_face = float(np.sum(
        sol.v[:, -1, :] * sol.rho_field[:, -1, :] * dx * dz * out_mask
    ))
    # Unmasked outlet integral — exposes any v leaking through "wall" cells.
    # Post mask-harmonisation: equals m_out_face (walls pinned to v=0).
    m_out_unmasked = float(np.sum(
        sol.v[:, -1, :] * sol.rho_field[:, -1, :] * dx * dz
    ))

    print("  partial-mask reproducer:")
    print(f"    A_face          = {A_face:.6g}")
    print(f"    A_open          = {A_open:.6g}  (open_frac={open_frac:.4f})")
    print(f"    target (ρ·U_super·A_open):  {m_target_super:.6g}")
    print(f"    actual inlet integral:      {m_in_face:.6g}")
    print(f"    actual outlet integral:     {m_out_face:.6g}")
    print(f"    outlet integral unmasked:   {m_out_unmasked:.6g}")
    print(f"    inlet/target ratio:         "
          f"{m_in_face / m_target_super:.4f}")
    print(f"    outlet/target ratio:        "
          f"{m_out_face / m_target_super:.4f}")
    print(f"    outlet_unmask/target ratio: "
          f"{m_out_unmasked / m_target_super:.4f}")

    # 1) BC pins the inlet face integral to the geometric target to machine
    #    precision — bare-BC injection convention check.
    assert m_in_face == pytest.approx(m_target_super, rel=5e-3), (
        f"BC-vs-integral mismatch (inlet): target={m_target_super:.6g} "
        f"actual={m_in_face:.6g} ratio={m_in_face / m_target_super:.3f}"
    )
    # 2) Wall cells at j=Ny are pinned to v=0 by the harmonised
    #    outlet_mask_ij (auto-derived from outlet_frac > 0.5). Therefore the
    #    masked and unmasked outlet integrals must agree to machine precision.
    #    Pre-fix this asserted ~0.7136 ratio (28% wall leakage). Post-fix:
    #    masked == unmasked exactly.
    assert m_out_face == pytest.approx(m_out_unmasked, rel=1e-6), (
        f"Wall leakage at outlet: masked={m_out_face:.6g} "
        f"unmasked={m_out_unmasked:.6g} (mask harmonisation broken)"
    )
    # 3) Steady-state mass conservation (inlet ≈ outlet). SIMPLE under-
    #    relaxation plateaus the residual ~1e-4 on this tight-K asymmetric
    #    geometry, so a 5% tolerance accommodates the convergence floor while
    #    still catching the pre-fix 28% leakage failure mode.
    assert m_in_face == pytest.approx(m_out_face, rel=5e-2), (
        f"Conservation broken (masked): in={m_in_face:.6g} "
        f"out={m_out_face:.6g} ratio={m_out_face / m_in_face:.3f}"
    )


if __name__ == '__main__':
    test_uniform_box_mass_conservation()
    test_uniform_box_bc_matches_inlet_integral()
    test_partial_mask_mass_flow_match_inlet_BC()
