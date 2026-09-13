"""
sigmoid_field_3d.py — 3D sigmoid-interpolated continuous L(x,y,z) / t(x,y,z)

108-dim decision vector layout:
  x[0:54]   inlet  3×3×3 zones × (L, t) = 54
  x[54:108] outlet 3×3×3 zones × (L, t) = 54

Per-zone flat index: flat = 9*iy + 3*ix + iz  (iy = streamwise row,
ix = cross-stream x index, iz = cross-stream z index). Within each zone
the two vars are L (mm) then t (mm).

Blend pattern: tensor-product sigmoid paint-over — x blend for each z at
each y-row, then z blend across 3 x-lines, then y blend across 7 xz-layers
(3 inlet + 1 uniform + 3 outlet). Reuses 2D `_blend_1d` and `_sigmoid`.

Phase 1 additions:
  * 3D cross-stream + streamwise tensor product
  * L clip [4, 8] mm, t clip [0.3, 0.6] mm (same as 2D)
  * dimension-agnostic LUT query + property broadcasts
  * shape contract: all returned arrays (Nx, Ny, Nz) float64
"""

import numpy as np

from sjtu_tpmshx.models.sigmoid_field import _sigmoid, _blend_1d, _arrays_from_fields

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


def _xz_blend(ctrl_xz, x_frac, z_frac, width_x, width_z):
    """Tensor-product sigmoid paint-over in (x, z) plane.

    ctrl_xz : (3, 3) indexed [ix, iz]
    Returns : (Nx, Nz) field
    """
    s1x = _sigmoid(x_frac, 1.0 / 3, width_x)
    s2x = _sigmoid(x_frac, 2.0 / 3, width_x)

    x_lines = []
    for iz in range(3):
        v = np.full_like(x_frac, float(ctrl_xz[0, iz]))
        v = v + (float(ctrl_xz[1, iz]) - v) * s1x
        v = v + (float(ctrl_xz[2, iz]) - v) * s2x
        x_lines.append(v)

    Nx = len(x_frac); Nz = len(z_frac)
    lines_2d = [np.broadcast_to(line[:, None], (Nx, Nz)).copy() for line in x_lines]
    ZF2d = np.broadcast_to(z_frac[None, :], (Nx, Nz)).copy()
    z_bounds = [1.0 / 3, 2.0 / 3]
    return _blend_1d(ZF2d, z_bounds, lines_2d, width_z)


def sigmoid_field_3d(XF, YF, ZF,
                      ctrl_inlet, ctrl_outlet, val_uniform,
                      y_trans_in, y_trans_out,
                      width_x=0.05, width_y=0.02, width_z=0.05):
    """Build smooth 3D field from 3×3×3 inlet/outlet control cubes.

    XF, YF, ZF : fractional coord meshgrids (Nx, Ny, Nz)
    ctrl_inlet, ctrl_outlet : (3, 3, 3) indexed [iy, ix, iz]
    val_uniform : scalar central zone value
    """
    Nx, Ny, Nz = XF.shape
    x_frac = XF[:, 0, 0].astype(np.float64)
    z_frac = ZF[0, 0, :].astype(np.float64)

    layers = []
    for iy in range(3):
        f_xz = _xz_blend(ctrl_inlet[iy], x_frac, z_frac, width_x, width_z)
        layers.append(np.broadcast_to(f_xz[:, None, :], XF.shape).copy())
    layers.append(np.full(XF.shape, float(val_uniform)))
    for iy in range(3):
        f_xz = _xz_blend(ctrl_outlet[iy], x_frac, z_frac, width_x, width_z)
        layers.append(np.broadcast_to(f_xz[:, None, :], XF.shape).copy())

    dy_in = y_trans_in / 3.0
    dy_out = y_trans_out / 3.0
    y_bounds = [
        dy_in, 2 * dy_in, y_trans_in,
        1.0 - y_trans_out,
        1.0 - y_trans_out + dy_out,
        1.0 - y_trans_out + 2 * dy_out,
    ]
    return _blend_1d(YF, y_bounds, layers, width_y)


def _extract_control_cube(x, offset, fill_value, fix):
    """Extract (3, 3, 3) cube from flat decision-vector slice."""
    cube = np.empty((3, 3, 3), dtype=np.float64)
    for iy in range(3):
        for ix in range(3):
            for iz in range(3):
                flat = 9 * iy + 3 * ix + iz
                cube[iy, ix, iz] = fill_value if fix else float(x[offset + 2 * flat])
    return cube


def build_continuous_arrays_3d(x, L0, t0,
                                y_trans_inlet, y_trans_outlet,
                                Nx, Ny, Nz, L_domain, H_domain, D_domain,
                                tpms_type, k_s,
                                u_A, u_B, T_inA, T_inB,
                                lut, P_in=101325.0,
                                sigmoid_width_x=0.05,
                                sigmoid_width_y=0.02,
                                sigmoid_width_z=0.05,
                                fix_L=False, fix_t=False,
                                dx_arr=None, dy_arr=None, dz_arr=None,
                                allow_extrap=None, fluid_type='air', P_inB=None):
    """Construct per-cell property arrays from 108-d decision vector.

    Parameters
    ----------
    x : (108,) array
    L0, t0 : scalar uniform zone value [mm]
    Nx, Ny, Nz : grid size
    L_domain, H_domain, D_domain : physical extents [m]
    lut : GeometryLUT (shape-agnostic query)
    dx_arr/dy_arr/dz_arr : non-uniform 1D cell widths [m] or None

    Returns
    -------
    dict with all arrays shape (Nx, Ny, Nz):
      eps_arr, eps_f_arr, K_ffA_arr, K_ffB_arr, K_ss_arr,
      h_vA_arr, h_vB_arr, r_h_arr, A_0_arr, L_field, t_field,
      zone_id (zeros), axis='continuous_3d'
    """
    x = np.asarray(x, dtype=np.float64)
    if x.shape != (108,):
        raise ValueError(f"3D decision vector must be (108,), got {x.shape}")

    # Control cubes
    ctrl_L_in = _extract_control_cube(x, 0, L0, fix_L)
    ctrl_L_out = _extract_control_cube(x, 54, L0, fix_L)
    ctrl_t_in = np.empty((3, 3, 3), dtype=np.float64)
    ctrl_t_out = np.empty((3, 3, 3), dtype=np.float64)
    for iy in range(3):
        for ix in range(3):
            for iz in range(3):
                flat = 9 * iy + 3 * ix + iz
                ctrl_t_in[iy, ix, iz] = t0 if fix_t else float(x[2 * flat + 1])
                ctrl_t_out[iy, ix, iz] = t0 if fix_t else float(x[54 + 2 * flat + 1])

    # Fractional coord meshgrids
    if dx_arr is not None:
        x_frac = (np.cumsum(dx_arr) - dx_arr / 2) / L_domain
    else:
        x_frac = np.linspace(0.5 / Nx, 1.0 - 0.5 / Nx, Nx)
    if dy_arr is not None:
        y_frac = (np.cumsum(dy_arr) - dy_arr / 2) / H_domain
    else:
        y_frac = np.linspace(0.5 / Ny, 1.0 - 0.5 / Ny, Ny)
    if dz_arr is not None:
        z_frac = (np.cumsum(dz_arr) - dz_arr / 2) / D_domain
    else:
        z_frac = np.linspace(0.5 / Nz, 1.0 - 0.5 / Nz, Nz)

    XF, YF, ZF = np.meshgrid(x_frac, y_frac, z_frac, indexing='ij')

    L_field = sigmoid_field_3d(XF, YF, ZF, ctrl_L_in, ctrl_L_out, L0,
                                y_trans_inlet, y_trans_outlet,
                                sigmoid_width_x, sigmoid_width_y, sigmoid_width_z)
    t_field = sigmoid_field_3d(XF, YF, ZF, ctrl_t_in, ctrl_t_out, t0,
                                y_trans_inlet, y_trans_outlet,
                                sigmoid_width_x, sigmoid_width_y, sigmoid_width_z)

    return _arrays_from_fields(
        L_field, t_field, tpms_type, k_s, u_A, u_B, T_inA, T_inB, lut,
        P_in=P_in, P_inB=P_inB, allow_extrap=allow_extrap,
        fluid_type=fluid_type, axis='continuous_3d')


if __name__ == '__main__':
    from sjtu_tpmshx.models.sigmoid_field import get_geometry_lut
    print("=== sigmoid_field_3d smoke test ===")
    lut = get_geometry_lut('Diamond')
    x = np.array([6.0, 0.3] * 54)
    x[0:2] = [4.0, 0.4]  # one inlet zone
    x[106:108] = [8.0, 0.5]  # one outlet zone
    out = build_continuous_arrays_3d(
        x, 6.0, 0.3, 0.2, 0.2,
        Nx=20, Ny=15, Nz=8,
        L_domain=0.10, H_domain=0.05, D_domain=0.02,
        tpms_type='Diamond', k_s=17.0,
        u_A=10.0, u_B=10.0, T_inA=400.0, T_inB=300.0,
        lut=lut)
    print(f"  L_field shape={out['L_field'].shape} range=[{out['L_field'].min():.2f}, {out['L_field'].max():.2f}]")
    print(f"  eps range=[{out['eps_arr'].min():.4f}, {out['eps_arr'].max():.4f}]")
    print(f"  h_vA range=[{out['h_vA_arr'].min():.0f}, {out['h_vA_arr'].max():.0f}]")
    print("OK")
