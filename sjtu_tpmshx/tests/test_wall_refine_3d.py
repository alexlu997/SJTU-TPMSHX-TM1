"""wall_refine_3d solve-level coverage (blind-spot audit T5, 2026-07-07).

Until this file, NO test actually solved on the 6-wall refined grid: config
round-trips touched the flag (always False) while the refined momentum /
pressure / LTNE path had zero solve coverage — the N4 diffusion-distance
defect lived exactly there, undetected. Assertions are physical-consistency
checks, not pinned values, so the test is valid both before and after the
N4 kernel fix; the refined-vs-uniform agreement bands are the guard.
"""

import numpy as np
import pytest


def _full_face_cfg(**overrides):
    """Small full-face air-air cross-flow (Shanghai-like), both dirs open."""
    cfg = dict(
        L=0.182, H=0.042, Lz=0.042,
        Nx=8, Ny=6, Nz=6,
        u_A=10.0, u_B=20.0, T_inA=422.0, T_inB=322.0,
        P_inA=192362.0, P_inB=101325.0,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=dict(dir=3, in_ctr=0.091, in_w=0.182,
                         out_ctr=0.091, out_w=0.182,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=True,
    )
    cfg.update(overrides)
    return cfg


@pytest.mark.slow
def test_wall_refine_3d_solves_and_matches_uniform():
    """Refined-grid solve is finite, conservative, and agrees with the
    uniform-grid solution of the same physical case."""
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack

    r = _run_3d_stack(_full_face_cfg())
    for key in ('T_A_out', 'T_B_out', 'dP_A',
                'Q_enthalpy_A', 'Q_enthalpy_B'):
        assert np.isfinite(r[key]), f"{key} not finite on refined grid"
    assert r['dP_A'] > 0.0
    assert np.isfinite(r['mass_imbalance_rel_A'])
    assert r['mass_imbalance_rel_A'] < 0.05

    Qa, Qb = abs(r['Q_enthalpy_A']), abs(r['Q_enthalpy_B'])
    assert Qa > 1.0 and Qb > 1.0, f"degenerate duties: {Qa:.3g}/{Qb:.3g}"
    assert abs(Qa - Qb) / max(Qa, Qb) < 0.15, \
        f"A/B energy imbalance on refined grid: {Qa:.1f} vs {Qb:.1f}"

    # Same case on the uniform grid — refinement must not move the answer
    # far (E1 measured ~0.6% dP shift at Shanghai scale; bands are generous
    # because this grid is much coarser).
    ru = _run_3d_stack(_full_face_cfg(wall_refine_3d=False))
    dP_u, dP_r = ru['dP_A'], r['dP_A']
    assert abs(dP_r - dP_u) / dP_u < 0.15, \
        f"refined dP {dP_r:.0f} vs uniform {dP_u:.0f} (>15%)"
    Qu = abs(ru['Q_enthalpy_A'])
    assert abs(Qa - Qu) / Qu < 0.10, \
        f"refined Q {Qa:.0f} vs uniform {Qu:.0f} (>10%)"
