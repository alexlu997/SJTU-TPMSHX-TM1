"""Red-black parallel energy kernel equivalence + parity-trap guard.

`_gs_full_chunk_3d_stag_rb` is the multi-core twin of the serial
`_gs_full_chunk_3d_stag`, used on large grids (> `_RB_ENERGY_GATE`). It sweeps
cells by checkerboard colour and reads the 2-away SOU deferred correction from a
start-of-sweep snapshot (the only same-colour dependency). These tests force RB
on a small z-symmetric cross-flow (by zeroing the gate) and assert it:
  * converges to the SAME field as the serial kernel (deferred SOU changes the
    path, not the fixpoint),
  * stays z-symmetric — the parity trap (z-reflection flips colour for even Nz)
    does NOT survive to the converged solution,
  * keeps the strict-conservation certificate < 1%.
"""

import numpy as np
import pytest
import sjtu_tpmshx.solvers.ltne_energy_3d as le
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def _z_asym_pct(field):
    a = np.asarray(field, dtype=float)
    rng = max(a.max() - a.min(), 1e-12)
    return 100.0 * np.abs(a - np.flip(a, axis=-1)).max() / rng


def _symmetric_crossflow_cfg():
    L, H, Lz = 0.182, 0.042, 0.042
    g = tpms_geometry('Gyroid', 7.0, 0.6, 16.0)
    return dict(
        L=L, H=H, Lz=Lz, Nx=16, Ny=10, Nz=8,
        u_A=2.0, u_B=0.133, T_inA=422.0, T_inB=300.0,
        P_inA=192362.0, P_inB=101973.0, T_s_init=300.0,
        Lcell=7.0, t_wall=0.6, k_s=16.0, tpms_type='Gyroid',
        eps=g['epsilon'], D_h=g['D_h'],
        fluid_A_cfg=dict(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H,
                         in_z_ctr=Lz / 2, in_z_w=Lz, out_z_ctr=Lz / 2, out_z_w=Lz),
        fluid_B_cfg=dict(dir=3, in_ctr=L / 2, in_w=L, out_ctr=L / 2, out_w=L,
                         in_z_ctr=Lz / 2, in_z_w=Lz, out_z_ctr=Lz / 2, out_z_w=Lz),
        wall_refine_3d=False, zone_grid_cells=None,
        fluid_type_A='air', fluid_type_B='water')


@pytest.mark.slow
def test_rb_energy_matches_serial_and_preserves_symmetry(monkeypatch):
    monkeypatch.setattr(le, '_RB_ENERGY_GATE', 0)   # force RB even on this small grid

    monkeypatch.setattr(le, '_RB_ENERGY', False)
    s = _run_3d_stack(_symmetric_crossflow_cfg())

    monkeypatch.setattr(le, '_RB_ENERGY', True)
    r = _run_3d_stack(_symmetric_crossflow_cfg())

    # Same converged solution (deferred SOU shifts the path, not the fixpoint).
    dTa = float(np.abs(np.asarray(s['Ta']) - np.asarray(r['Ta'])).max())
    dTs = float(np.abs(np.asarray(s['Ts']) - np.asarray(r['Ts'])).max())
    assert dTa < 1.0e-2, f"RB vs serial T_A diverged: {dTa:.3e} K"
    assert dTs < 1.0e-2, f"RB vs serial T_s diverged: {dTs:.3e} K"

    # Parity trap: a z-symmetric setup must stay z-symmetric under RB.
    assert _z_asym_pct(r['Ta']) < 2.0, \
        f"RB broke z-symmetry: T_A asym {_z_asym_pct(r['Ta']):.2f}%"
    assert _z_asym_pct(r['Ts']) < 2.0, \
        f"RB broke z-symmetry: T_s asym {_z_asym_pct(r['Ts']):.2f}%"

    # Strict conservation preserved on the RB path.
    assert r.get('eps_A_strict', 1.0) < 0.01, \
        f"RB conservation A {r.get('eps_A_strict')*100:.3f}% not < 1%"
    assert r.get('eps_B_strict', 1.0) < 0.01, \
        f"RB conservation B {r.get('eps_B_strict')*100:.3f}% not < 1%"
