"""Robustness: the 2nd-order face-extracted Δp must be the SAME for any
streamwise flow direction (±x / ±y / ±z), since the UI lets users pick custom
geometry + inlet/outlet directions.

`SIMPLESolver3D.extract_dP_face_extrap` (like `extract_dP_weighted`) reads the
solver's axis 1. The pipeline's `_resolve_axis_map` permutes EVERY physical
direction so streamwise lands on solver axis 1 (inlet at index 0). So on a
rotation-symmetric problem (cube domain, uniform geometry, cube grid) the
extracted Δp_A must be identical whether the flow runs along x, y or z.

We rotate the whole two-stream frame cyclically x→y→z:
  (dir_A, dir_B) = (+x, −y) → (+y, −z) → (+z, −x)
and assert dP_A agrees. A failure would mean the dP fix (or the axis map) is
direction-dependent — exactly the regression this guards.
"""


from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack

# cube domain + cube grid + uniform geometry → x/y/z streams are the same
# physical problem in a rotated frame.
_S = 0.042   # cube side (m)
_N = 6       # cube grid


def _cfg(dir_A, dir_B):
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=8.0, T_in_K=420.0, P_in_Pa=150000.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=320.0, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=_S, H_dom_m=_S, Lz_m=_S),
        solver=SolverConfig(Nx=_N, Ny=_N, Nz=_N),
        bc_A=PartialBCConfig(dir=dir_A, in_ctr=_S / 2, in_w=_S,
                             out_ctr=_S / 2, out_w=_S),
        bc_B=PartialBCConfig(dir=dir_B, in_ctr=_S / 2, in_w=_S,
                             out_ctr=_S / 2, out_w=_S),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )


def _dP_A(dir_A, dir_B):
    raw = _run_3d_stack(_parse_inputs_3d_cfg(_cfg(dir_A, dir_B)))
    return float(raw.get('dP_A', raw.get('dP')))


def test_face_extrap_dp_is_direction_invariant():
    # cyclic rotation x→y→z of the whole frame
    dP_x = _dP_A(0, 3)   # A +x, B -y
    dP_y = _dP_A(2, 5)   # A +y, B -z
    dP_z = _dP_A(4, 1)   # A +z, B -x
    vals = {'x': dP_x, 'y': dP_y, 'z': dP_z}
    assert all(v > 0 for v in vals.values()), f"non-positive dP: {vals}"
    mean = (dP_x + dP_y + dP_z) / 3.0
    spread = max(abs(v - mean) for v in vals.values()) / mean
    # rotation-symmetric problem → identical dP up to staggered-grid / iteration
    # asymmetry; the fix would silently mis-apply on a non-x axis if this drifts.
    assert spread < 0.05, (
        f"face-extrap dP_A is direction-dependent: x={dP_x:.2f} y={dP_y:.2f} "
        f"z={dP_z:.2f} Pa, spread={spread:.3%}")
