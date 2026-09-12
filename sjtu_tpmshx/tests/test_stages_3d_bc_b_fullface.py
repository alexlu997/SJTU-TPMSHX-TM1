"""Regression: a degenerate (default) bc_B at the ComputeConfig→3D boundary
must become a FULL-FACE ``fluid_B_cfg``, not ``None``.

Bug (2026-06-24): ``PartialBCConfig`` defaults to ``in_w=out_w=0``;
``bc_to_dict(side='B')`` maps that to ``None``; ``_run_3d_stack``'s
``if fB is not None`` gate then SKIPS the entire B SIMPLE build (the
single-fluid A-alone path), so a 2-fluid 3D ``ComputeConfig`` that left the B
widths at default silently returned nan (air uncooled, ``T_out_B=nan``,
``E_imbal=1.0``).

Via ``ComputeConfig`` fluid_B is always a configured second fluid (validated in
``_parse_inputs_3d_cfg``), so a None B BC at THIS boundary means "full-face
cross-flow", not single-fluid. The genuine single-fluid path
(``validation/cases/audit_3d_conservation.py`` T5) calls ``_run_3d_stack`` directly
with an explicit ``fluid_B_cfg=None`` and bypasses this boundary, so it — and
``bc_to_dict``'s documented side-B None asymmetry (``tests/test_bc_to_dict.py``)
— are unaffected by the fix.
"""
from __future__ import annotations

import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, PartialBCConfig)
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg


def _cfg(dir_B):
    c = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10.0, T_in_K=400.0, P_in_Pa=130000.0),
        fluid_B=FluidConfig(type='air', u_mps=5.0, T_in_K=300.0, P_in_Pa=130000.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.4,
                                k_s_W_mK=16.0, L_dom_m=0.182, H_dom_m=0.042,
                                Lz_m=0.042),
        solver=SolverConfig(Nx=12, Ny=10, Nz=4),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=dir_B),   # default in_w=out_w=0 → was None
    )
    c.extrap.allow = True                  # air uB=5 may be below the Re window
    return c


@pytest.mark.parametrize('dir_B', [1, 2, 3, 5])
def test_degenerate_bc_b_becomes_full_face(dir_B):
    parsed = _parse_inputs_3d_cfg(_cfg(dir_B))
    fb = parsed['fluid_B_cfg']
    assert fb is not None, (
        "degenerate bc_B at the ComputeConfig boundary must become full-face, "
        "not None (None → _run_3d_stack skips the B SIMPLE build → silent nan)")
    assert fb['dir'] == dir_B
    assert fb['in_w'] > 0 and fb['out_w'] > 0, (
        "full-face B must span the cross-stream dimension")
