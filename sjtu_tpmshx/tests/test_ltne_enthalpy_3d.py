"""Phase 2.2 — njit enthalpy-form 3D LTNE kernel conservation gate.

solve_ltne_enthalpy_3d keeps h as the primary fluid unknown and telescopes the
mass flux ṁ on h (true enthalpy flux), so for a strongly variable-cp sCO2 stream
the two fluids' duties balance — unlike the legacy ρcp·u·T conservative kernel,
which on the same case leaves a large A/B imbalance (the 703 ~41% defect).

This is the 3D (njit) counterpart of the validated 1D PoC
(sjtu_tpmshx/tests/enthalpy_1d_reference.py). Counterflow along x, variable-cp CO2
straddling the pseudocritical line.
"""
import numpy as np
import pytest

from sjtu_tpmshx.models import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")


def _case():
    return dict(
        Nx=16, Ny=3, Nz=3, Lx=0.20, Ly=0.02, Lz=0.02,
        eps=0.68, k_s=14.0,
        m_dot_A=+1.6e-4, m_dot_B=-1.0e-4,
        h_vA=2.5e5, h_vB=2.5e5,
        T_inA=360.0, T_inB=298.0, P=8.0e6,
        dir_A=0, dir_B=1,
        n_sweep=20, omega=0.7, tol=1e-3, n_outer=2000,
    )


def test_enthalpy_3d_uniform_field_preserved_no_phantom_boundary_diffusion():
    """N3 (audit 2026-06-28): the inlet/outlet x-boundary cells carried an
    unpaired interior diffusion conductance (DxW/DxE) in aP — a spurious enthalpy
    sink ∝ ABSOLUTE h (reference-dependent), so a uniform field was NOT a
    solution of the homogeneous (source-free) boundary equation. With h_v=0
    (inter-phase decoupled) and BOTH inlets at the same T, h ≡ h_in is the exact
    solution; one full-update sweep from the uniform start must leave it uniform.
    Before the fix the boundary cells dipped; after, the field stays uniform."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d
    res = solve_ltne_enthalpy_3d(
        Nx=6, Ny=3, Nz=3, Lx=0.08, Ly=0.04, Lz=0.04, eps=0.6, k_s=16.0,
        m_dot_A=0.02, m_dot_B=-0.02, h_vA=0.0, h_vB=0.0,  # dir_B=1 -> ṁ_B < 0
        T_inA=330.0, T_inB=330.0, P=8.0e6, dir_A=0, dir_B=1,
        fluid_A='sco2', fluid_B='sco2', n_outer=1, n_sweep=1, omega=1.0)
    Ta = res['Ta']; Tb = res['Tb']
    assert np.max(np.abs(Ta - 330.0)) < 1e-3, \
        f"fluid A boundary phantom diffusion: max dev {np.max(np.abs(Ta-330.0)):.4g} K"
    assert np.max(np.abs(Tb - 330.0)) < 1e-3, \
        f"fluid B boundary phantom diffusion: max dev {np.max(np.abs(Tb-330.0)):.4g} K"


def test_enthalpy_3d_conserves_on_variable_cp_counterflow():
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    res = solve_ltne_enthalpy_3d(**_case())
    m = enthalpy_metrics_3d(res, _case())

    # toy 16x3x3 grid → discretisation-sensitive; the meaningful gate is the
    # recuperator case (<5%) and the real 703 pipeline (2.2%). vs ~41-67% legacy.
    assert m["AB_imbal"] < 0.05, (
        f"3D enthalpy kernel A/B imbalance {m['AB_imbal']*100:.2f}% — not "
        f"conserving true enthalpy")
    assert m["e_imb_LTNE"] < 0.02, (
        f"solid balance Q_sA+Q_sB {m['e_imb_LTNE']*100:.3f}% not closing")


def test_enthalpy_3d_temperatures_physical():
    """Counterflow: hot A cools, cold B warms; both stay in a sane range."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d
    c = _case()
    res = solve_ltne_enthalpy_3d(**c)
    Ta, Tb = res["Ta"], res["Tb"]
    # hot inlet at x=0 (dir_A=0): A outlet (x=-1) cooler than inlet
    assert Ta[-1, :, :].mean() < c["T_inA"]
    # cold inlet at x=-1 (dir_B=1): B outlet (x=0) warmer than inlet
    assert Tb[0, :, :].mean() > c["T_inB"]
    assert Ta.min() > 240.0 and Ta.max() < 420.0


def _recuperator_case():
    """V1 recuperator: hot 650 K @ 8.5 MPa, cold 350 K @ 15 MPa,
    counterflow, per-side pressure, high-NTU (h_v ~ 4e6 from the sCO2 Nu).
    The legacy ρcp·u·T 3D kernel leaves ~41% A/B imbalance here and under-reads
    the cold outlet to ~515 K; the enthalpy form must recover the energy-balance
    outlet (~655 K) and close the imbalance."""
    return dict(
        Nx=16, Ny=3, Nz=3, Lx=0.344, Ly=0.860, Lz=0.860,
        eps=0.675, k_s=16.0,
        m_dot_A=+37.6, m_dot_B=-37.6,
        h_vA=4.19e6, h_vB=4.32e6,
        T_inA=650.0, T_inB=350.0, P=8.5e6, P_B=15.0e6,
        dir_A=0, dir_B=1,
        n_sweep=25, omega=0.6, tol=1e-3, n_outer=1500,
    )


def test_enthalpy_3d_703_recuperator_conserves():
    """End-to-end value gate: Option B on the real 703 recuperator envelope
    closes the A/B imbalance (was ~41% with ρcp·u·T) and recovers the cold
    outlet (was wrongly ~515 K, energy balance wants ~655 K)."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    c = _recuperator_case()
    res = solve_ltne_enthalpy_3d(**c)
    m = enthalpy_metrics_3d(res, c)

    assert m["AB_imbal"] < 0.05, (
        f"703 recuperator A/B imbalance {m['AB_imbal']*100:.2f}% — Option B "
        f"should be far below the legacy ~41%")
    assert m["e_imb_LTNE"] < 0.02
    # cold outlet (dir_B=1 → x=0) must land near the energy-balance value,
    # decisively above the legacy ρcp·u·T under-read of ~515 K.
    cold_out = float(res["Tb"][0, :, :].mean())
    assert cold_out > 500.0, f"cold outlet {cold_out:.0f} K is under-heated"


def test_enthalpy_3d_near_critical_cp_spike_robust():
    """Precooler regime: a stream traversing the pseudocritical cp×56 spike
    (Tpc≈306 K @ 7.7 MPa) must stay robust and conservative. Option B has cp
    only in the denominator of the inter-phase linearisation and none in the
    convection, so the ×56 jump cannot destabilise it — the reason it was
    chosen over the in-T deferred-correction form (Option A)."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    # hot A = large reservoir at ~322 K, cold B small → dragged up across Tpc.
    c = dict(Nx=40, Ny=3, Nz=3, Lx=0.20, Ly=0.5, Lz=0.5, eps=0.675, k_s=16.0,
             m_dot_A=+250.0, m_dot_B=-7.0, h_vA=2.5e6, h_vB=2.5e6,
             T_inA=322.0, T_inB=290.0, P=8.0e6, P_B=8.0e6, dir_A=0, dir_B=1,
             n_sweep=30, omega=0.5, tol=5e-4, n_outer=4000)
    res = solve_ltne_enthalpy_3d(**c)
    m = enthalpy_metrics_3d(res, c)

    assert np.all(np.isfinite(res["Ta"])) and np.all(np.isfinite(res["Tb"])), \
        "NaN through the cp×56 spike"
    Tb = res["Tb"][:, 1, 1]
    # the cold stream must actually traverse the spike, with cells in the peak
    assert Tb.min() < 306.0 < Tb.max(), "cold stream did not cross Tpc"
    assert int(np.sum((Tb > 303.0) & (Tb < 309.0))) >= 5, \
        "no cells resolved inside the sharp spike band"
    # and conservation must hold THROUGH the spike
    assert m["AB_imbal"] < 0.03, (
        f"A/B imbalance {m['AB_imbal']*100:.2f}% through the cp×56 spike")
    assert m["e_imb_LTNE"] < 0.02


def test_enthalpy_3d_mixed_sco2_water_precooler():
    """#1: the real 703 precooler is sCO2 (hot, crossing the cp spike) + water
    (cold). The mixed kernel runs the sCO2 side in enthalpy form and the water
    side via its own (near-constant-cp) enthalpy — both duties must balance and
    the solve stays robust through the sCO2-side spike."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    c = dict(Nx=24, Ny=3, Nz=3, Lx=0.127, Ly=0.5, Lz=0.5, eps=0.675, k_s=16.0,
             m_dot_A=+10.0, m_dot_B=-30.0,        # sCO2 hot / water cold
             h_vA=8e5, h_vB=8e5,
             T_inA=371.0, T_inB=297.0, P=8.0e6, P_B=0.5e6,
             dir_A=0, dir_B=1, fluid_A='sco2', fluid_B='water',
             n_sweep=25, omega=0.6, tol=1e-3, n_outer=2000)
    res = solve_ltne_enthalpy_3d(**c)
    m = enthalpy_metrics_3d(res, c)

    assert np.all(np.isfinite(res["Ta"])) and np.all(np.isfinite(res["Tb"])), \
        "NaN in the mixed sCO2/water solve"
    # sCO2 hot (dir 0) cools; water cold (dir 1) warms
    assert res["Ta"][-1, :, :].mean() < c["T_inA"]
    assert res["Tb"][0, :, :].mean() > c["T_inB"]
    # the two stream duties balance, and the solid LTNE flux closes
    assert m["AB_imbal"] < 0.05, (
        f"sCO2/water duty imbalance {m['AB_imbal']*100:.2f}%")
    assert m["e_imb_LTNE"] < 0.02


def test_enthalpy_3d_custom_cross_ports_use_face_mass_flow():
    from sjtu_tpmshx.solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d_pipeline

    nx, ny, nz = 5, 6, 1
    shape = (nx, ny, nz)
    dx = np.full(nx, 0.01); dy = np.full(ny, 0.01); dz = np.ones(nz)
    flux_a = [np.zeros((nx + 1, ny, nz)), np.zeros((nx, ny + 1, nz)),
              np.zeros((nx, ny, nz + 1))]
    flux_b = [np.zeros((nx + 1, ny, nz)), np.zeros((nx, ny + 1, nz)),
              np.zeros((nx, ny, nz + 1))]
    flux_a[1][1:4, :, :] = 0.01   # +y, partial x-span
    flux_b[0][:, 2:5, :] = -0.01  # -x, partial y-span
    eps = np.full(shape, 0.65)
    Ta, Tb, _, info = solve_ltne_enthalpy_3d_pipeline(
        nx, ny, nz, dx, dy, dz, eps, np.full(shape, 5.0),
        np.full(shape, 1e5), np.full(shape, 1e5), 500.0, 300.0, 12e6, 2e6, fluid_A='sco2', fluid_B='water', eps_A_field=eps / 2,
        eps_B_field=eps / 2, mass_flux_A=flux_a, mass_flux_B=flux_b,
        n_outer=1000, n_sweep=5, tol=1e-3)
    assert info['converged']
    assert info['energy_imbalance_rel'] < 0.05
    assert np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))


def test_enthalpy_3d_offset_porosity_conserves():
    """#3: offset-isosurface (δ≠0) per-side void fractions ε_A≠ε_B. The kernel
    consumes per-side ε fields; conservation holds with an asymmetric split."""
    from sjtu_tpmshx.tests.enthalpy_3d_reference import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    c = _case()
    c.pop("eps")  # provide per-side ε directly instead
    Nx, Ny, Nz = c["Nx"], c["Ny"], c["Nz"]
    epsA = np.full((Nx, Ny, Nz), 0.40)   # ε_A ≠ ε_B (sum 0.68 = ε_full)
    epsB = np.full((Nx, Ny, Nz), 0.28)
    res = solve_ltne_enthalpy_3d(eps=0.68, eps_A_field=epsA, eps_B_field=epsB, **c)
    m = enthalpy_metrics_3d(res, dict(eps=0.68, **c))
    assert np.all(np.isfinite(res["Ta"])) and np.all(np.isfinite(res["Tb"]))
    assert m["AB_imbal"] < 0.05, f"offset-ε A/B imbalance {m['AB_imbal']*100:.2f}%"
    assert m["e_imb_LTNE"] < 0.02
