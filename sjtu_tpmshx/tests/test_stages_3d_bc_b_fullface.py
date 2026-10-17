"""Default B ports must prepare a full second-fluid face in every direction."""
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
        "not None (None → backend skips the B SIMPLE build → silent nan)")
    assert fb['dir'] == dir_B
    assert fb['in_w'] > 0 and fb['out_w'] > 0, (
        "full-face B must span the cross-stream dimension")
