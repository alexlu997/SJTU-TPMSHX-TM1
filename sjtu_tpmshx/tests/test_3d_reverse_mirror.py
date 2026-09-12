"""Ground-truth: a reverse-direction (-y) fluid B must produce the exact
y-mirror image of the same case run as a forward (+y) fluid.

Physics: relabeling B's flow +y <-> -y with the inlet/outlet y-mirrored is
the SAME physical problem. So Tb_rev(x, y, z) == Tb_fwd(x, H-y, z) (and Ta, Ts).
Fluid A is air +x with a full-face (y-symmetric) inlet, so the whole coupled
solution mirrors.

This isolates the reverse-dir velocity-transform handling
(_solver_staggered_to_real / _solver_velocity_to_real): the forward (+y, dir=2,
is_reverse=False) path is the trusted reference; the reverse (-y, dir=3) path is
under test. A missing stream-axis flip in the reverse handling breaks the
mirror symmetry.
"""
import numpy as np

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def _cfg(dir_B, in_ctr, out_ctr):
    cc = ComputeConfig(
        fluid_A=FluidConfig(type='air',   u_mps=12.0,  T_in_K=420.0, P_in_Pa=150000.0),
        fluid_B=FluidConfig(type='water', u_mps=0.30,  T_in_K=300.0, P_in_Pa=120000.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.5,
                                k_s_W_mK=16.0, L_dom_m=0.10, H_dom_m=0.042, Lz_m=0.030),
        solver=SolverConfig(Nx=12, Ny=12, Nz=4),
        # A: +x, full-face on the cross (y) faces -> y-symmetric
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        # B: dir_B with staggered x-strips (cross-stream = x for +/-y flow)
        bc_B=PartialBCConfig(dir=dir_B, in_ctr=in_ctr, in_w=0.042,
                             out_ctr=out_ctr, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )
    return _parse_inputs_3d_cfg(cc)


# 2026-06-09 FIXED (was xfail). Root cause was NOT the interior negate+flip
# transform (proven machine-exact: ΣD ≡ net stream-boundary flux, telescoping
# clean). It was a discrete global-mass-balance violation: SIMPLE's small
# continuity residual, amplified by partial-BC inlet/outlet masks + the outlet
# taper on offset/reverse fluids, left a net ∮F·n the homogeneous-Neumann MAC
# projection cannot remove (constant null space) → uniform spurious energy
# divergence → reverse y-mirror broke at rel~0.174 + spurious over-heating.
# Fix = `_balance_stream_outflow` enforces Σ_inlet=Σ_outlet on the extracted
# stream-boundary faces BEFORE the projection (run_calculation_3d.py), so ΣD→0
# and the strict conservative-LTNE kernel telescopes to machine precision.
# Near-balanced cases (Shanghai full-face) get scale≈1 → no-op.
def test_reverse_y_is_mirror_of_forward_y():
    # FORWARD +y (dir=2): inlet at BOTTOM (y=0) x-strip @0.07, outlet TOP @0.03
    cfg_fwd = _cfg(dir_B=2, in_ctr=0.07, out_ctr=0.03)
    # REVERSE -y (dir=3): inlet at TOP (y=H) x-strip @0.07, outlet BOTTOM @0.03
    # This is the exact y-mirror of the forward case.
    cfg_rev = _cfg(dir_B=3, in_ctr=0.07, out_ctr=0.03)

    res_fwd = _run_3d_stack(cfg_fwd)
    res_rev = _run_3d_stack(cfg_rev)

    Tb_fwd = res_fwd['Tb']
    Tb_rev = res_rev['Tb']
    # mirror the forward field along the real y-axis (axis=1)
    Tb_fwd_mirrored = Tb_fwd[:, ::-1, :]

    # Relative L2 mismatch of the (cold) water field, normalized by the
    # driving temperature span so the gate is dimensionless.
    span = float(Tb_fwd.max() - Tb_fwd.min())
    assert span > 1.0, "degenerate: no thermal variation to compare"
    rel = float(np.sqrt(np.mean((Tb_rev - Tb_fwd_mirrored) ** 2)) / span)
    # Gate 0.05: the reverse-dir transform bug gave rel ≈ 0.54 (and a spurious
    # >100°C over-boiling peak). With the stream-axis flip in the velocity
    # transforms + no mask in/out swap, rel ≈ 0.02 — the residual is genuine
    # numerical asymmetry between two independent SIMPLE+LTNE solves on this
    # coarse 12³ grid (convergence tol + half-cell mask placement), NOT the
    # systematic mirror error. 0.05 sits 10× below the bug, 2.5× above the
    # converged residual.
    assert rel < 0.05, (
        f"reverse(-y) B is NOT the y-mirror of forward(+y): "
        f"rel L2 = {rel:.4f} (gate 0.05; bug regime ≈ 0.54). "
        f"Tb_fwd[max/min]={Tb_fwd.max()-273.15:.1f}/{Tb_fwd.min()-273.15:.1f}C "
        f"Tb_rev[max/min]={Tb_rev.max()-273.15:.1f}/{Tb_rev.min()-273.15:.1f}C"
    )

    # ── Pressure-B must mirror too (approach-(a) reverse flip) ──────────
    # sB.P lives in SOLVER coords; the real-coord map must spatially flip
    # along the stream axis for is_reverse, exactly like the velocity
    # transforms. Bug regime (transpose-only, no flip): rel ≈ 0.17 AND the
    # reverse-fluid high-pressure end lands at the real OUTLET (y=0) instead
    # of the real INLET (y=H). Both checks below.
    Pb_fwd = res_fwd['P_Pa_B']
    Pb_rev = res_rev['P_Pa_B']
    Pb_fwd_mirrored = Pb_fwd[:, ::-1, :]
    p_span = float(Pb_fwd.max() - Pb_fwd.min())
    assert p_span > 1.0, "degenerate: no pressure variation to compare"
    rel_p = float(np.sqrt(np.mean((Pb_rev - Pb_fwd_mirrored) ** 2)) / p_span)
    assert rel_p < 0.05, (
        f"Pressure-B reverse(-y) is NOT the y-mirror of forward(+y): "
        f"rel L2 = {rel_p:.4f} (gate 0.05; transpose-only bug ≈ 0.17). "
        f"P_real_B missing the is_reverse stream-axis np.flip (run_calc 3D)."
    )

    # Physical direction check: reverse(-y) real inlet is at y=H (last idx).
    # Pressure must DROP from inlet (y=H) to outlet (y=0): P[y=H] > P[y=0].
    prof_rev = Pb_rev.mean(axis=(0, 2))
    assert prof_rev[-1] > prof_rev[0], (
        f"reverse(-y) B pressure inverted: inlet end (y=H)={prof_rev[-1]:.1f} Pa "
        f"<= outlet end (y=0)={prof_rev[0]:.1f} Pa — high pressure on the "
        f"WRONG (outlet) end, the un-flipped-pressure symptom."
    )


def test_displayed_pressure_is_absolute_matches_inlet():
    """The 3D vis pressure field must be ABSOLUTE (P_ref_abs + gauge), so the
    inlet high-pressure end reads ~ the user-input inlet pressure — matching
    the 2D-native path (run_calculation.py:821 P_fA = P_inA + (P_g - P_ref)).

    Pre-change the 3D path exported GAUGE (outlet pinned 0, inlet ~ dP of a few
    kPa), so the plotted inlet did NOT match the input P_in. Gate distinguishes
    absolute (max ~ P_in) from gauge (max ~ dP << 0.5·P_in).
    """
    P_inA, P_inB = 150000.0, 120000.0   # must match _cfg() FluidConfig P_in_Pa
    res = _run_3d_stack(_cfg(dir_B=2, in_ctr=0.07, out_ctr=0.03))
    P_A = np.asarray(res['P_Pa'])         # fluid A (air, +x)
    P_B = np.asarray(res['P_Pa_B'])       # fluid B (water, +y)

    # Inlet is anchored to the input P_in (abs = P_in - dP + gauge), so the
    # high-pressure end reads ~ input within ~3 % (residual = gauge-max vs
    # weighted-dP + outlet-pin). Gauge would be ~dP (few kPa) << 0.5·P_in.
    assert P_A.max() > 0.5 * P_inA, (
        f"P_A looks like GAUGE not ABSOLUTE: max={P_A.max():.0f} Pa "
        f"<< P_inA={P_inA:.0f}")
    assert abs(P_A.max() - P_inA) < 0.03 * P_inA, (
        f"P_A inlet abs {P_A.max():.0f} Pa != input P_inA {P_inA:.0f} Pa")

    assert P_B.max() > 0.5 * P_inB, (
        f"P_B looks like GAUGE not ABSOLUTE: max={P_B.max():.0f} Pa "
        f"<< P_inB={P_inB:.0f}")
    assert abs(P_B.max() - P_inB) < 0.03 * P_inB, (
        f"P_B inlet abs {P_B.max():.0f} Pa != input P_inB {P_inB:.0f} Pa")
