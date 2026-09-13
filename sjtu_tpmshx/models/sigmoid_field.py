"""
sigmoid_field.py — Continuous L(x,y) and t(x,y) fields via Sigmoid interpolation

Replaces discrete zone assignment with smooth parameter fields.
Control points from the 3×3 inlet/outlet zones + uniform zone are
interpolated using sequential sigmoid paint-over blending.

Includes a precomputed geometry lookup table (LUT) for fast per-cell
evaluation of epsilon(L,t) and A_0(L,t).
"""

import os
import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .tpms_geometry import compute_geometry, _phi_grid, _C_from_tL, _eps_from_C, _A0_from_C
from .tpms_calc import (air_density, air_viscosity, air_conductivity)
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L, TRAIN_T

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ── Sigmoid basis ────────────────────────────────────────────

def _sigmoid(x, center, width):
    """Smooth sigmoid transition centered at `center`."""
    return 1.0 / (1.0 + np.exp(np.clip(-(x - center) / width, -50, 50)))


def _blend_1d(x, boundaries, values, width):
    """Sequential paint-over sigmoid blend along 1D axis.

    boundaries: N-1 transition points between N regions
    values: list of N value arrays (same shape as x)
    """
    result = values[0].copy() if hasattr(values[0], 'copy') else np.full_like(x, values[0])
    for i, b in enumerate(boundaries):
        alpha = _sigmoid(x, b, width)
        v_next = values[i + 1] if hasattr(values[i + 1], 'copy') else np.full_like(x, values[i + 1])
        result = result * (1.0 - alpha) + v_next * alpha
    return result


# ── 2D Sigmoid field construction ────────────────────────────

def sigmoid_field_2d(XF, YF,
                     ctrl_inlet, ctrl_outlet, val_uniform,
                     y_trans_in, y_trans_out,
                     width_x=0.05, width_y=0.02):
    """Build a smooth 2D field from zone control point values.

    Parameters
    ----------
    XF, YF : 2D arrays (Nx, Ny) — fractional cell centre coordinates [0,1]
    ctrl_inlet : (3, 3) array — values at inlet zone control points [row][col]
                 row 0 = bottom (y=0), col 0 = left (x=0)
    ctrl_outlet : (3, 3) array — values at outlet zone control points
    val_uniform : scalar — uniform zone value
    y_trans_in, y_trans_out : float — fractional transition region sizes
    width_x, width_y : float — sigmoid transition widths

    Returns
    -------
    field : 2D array (Nx, Ny) — smoothly interpolated values
    """
    # X-direction sigmoid weights (shared for all rows)
    s1x = _sigmoid(XF, 1.0 / 3, width_x)
    s2x = _sigmoid(XF, 2.0 / 3, width_x)

    def _xblend(row_vals):
        """Paint-over blend of 3 column values."""
        v = np.full_like(XF, row_vals[0])
        v = v + (row_vals[1] - v) * s1x
        v = v + (row_vals[2] - v) * s2x
        return v

    # Build 7 x-blended layers: 3 inlet + 1 uniform + 3 outlet
    layers = []
    for r in range(3):
        layers.append(_xblend(ctrl_inlet[r]))
    layers.append(np.full_like(XF, val_uniform))
    for r in range(3):
        layers.append(_xblend(ctrl_outlet[r]))

    # Y-direction boundaries (6 transitions between 7 layers)
    dy_in = y_trans_in / 3.0
    dy_out = y_trans_out / 3.0
    y_bounds = [
        dy_in,                          # inlet row 0 → row 1
        2 * dy_in,                      # inlet row 1 → row 2
        y_trans_in,                     # inlet → uniform
        1.0 - y_trans_out,              # uniform → outlet
        1.0 - y_trans_out + dy_out,     # outlet row 0 → row 1
        1.0 - y_trans_out + 2 * dy_out, # outlet row 1 → row 2
    ]

    return _blend_1d(YF, y_bounds, layers, width_y)


# ── Geometry Lookup Table ────────────────────────────────────

class GeometryLUT:
    """Precomputed lookup table for epsilon(L,t) and A_0(L,t).

    Uses bilinear interpolation on a regular (L, t) grid.
    Cached to disk as .npz file for fast loading.
    """

    def __init__(self, tpms_type, L_range=TRAIN_L, t_range=TRAIN_T,
                 n_L=41, n_t=31, N=256, cache_dir=None):
        self.tpms_type = tpms_type
        self.L_vals = np.linspace(L_range[0], L_range[1], n_L)
        self.t_vals = np.linspace(t_range[0], t_range[1], n_t)
        self.N = N

        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'solvers')
        # N (voxel resolution) MUST be in the cache key + load-validation: the
        # eps_table / A0_table are computed at resolution N (_phi_grid(...,N),
        # _A0_from_C(...,N)), so a different N produces a different table. The
        # old key omitted N → requesting N≠cached silently loaded the stale-
        # resolution geometry (audit 2026-06-28). Latent while N is the default
        # 256 everywhere, but a real silent-wrong-geometry bug if N varies.
        self._cache_path = os.path.join(
            cache_dir, f'lut_{tpms_type}_{n_L}x{n_t}_N{N}.npz')

        if not self._load():
            self._precompute()
            self._save()

        # Build interpolators
        self._interp_eps = RegularGridInterpolator(
            (self.L_vals, self.t_vals), self.eps_table, method='linear',
            bounds_error=False, fill_value=None)
        self._interp_A0 = RegularGridInterpolator(
            (self.L_vals, self.t_vals), self.A0_table, method='linear',
            bounds_error=False, fill_value=None)

    def _precompute(self):
        """Compute epsilon and A_0 over the full (L, t) grid."""
        n_L = len(self.L_vals)
        n_t = len(self.t_vals)
        self.eps_table = np.empty((n_L, n_t))
        self.A0_table = np.empty((n_L, n_t))

        phi = _phi_grid(self.tpms_type, self.N)

        for i, L_mm in enumerate(self.L_vals):
            L_m = L_mm / 1000.0
            for j, t_mm in enumerate(self.t_vals):
                tL = t_mm / L_mm
                C = _C_from_tL(self.tpms_type, tL)
                if C < 0:
                    C = 0.0
                self.eps_table[i, j] = _eps_from_C(phi, C)
                self.A0_table[i, j] = _A0_from_C(phi, C, L_m, self.N)

    def _save(self):
        np.savez_compressed(self._cache_path,
                            L_vals=self.L_vals, t_vals=self.t_vals,
                            eps_table=self.eps_table, A0_table=self.A0_table,
                            tpms_type=np.array([self.tpms_type]),
                            N=np.array([self.N]))

    def _load(self):
        if not os.path.exists(self._cache_path):
            return False
        try:
            data = np.load(self._cache_path, allow_pickle=True)
            if str(data['tpms_type'][0]) != self.tpms_type:
                return False
            if 'N' not in data or int(data['N'][0]) != int(self.N):
                return False   # resolution mismatch → recompute (audit 2026-06-28)
            if not np.array_equal(data['L_vals'], self.L_vals):
                return False
            if not np.array_equal(data['t_vals'], self.t_vals):
                return False
            self.eps_table = data['eps_table']
            self.A0_table = data['A0_table']
            return True
        except Exception:
            # Deliberate (except-audit 2026-07-03): a corrupt/stale cache
            # file must fall back to recompute (which rewrites the cache),
            # never crash the LUT build.
            return False

    def query(self, L_arr, t_arr):
        """Bilinear interpolation on the LUT. Supports 2D array inputs.

        Returns (eps_arr, A0_arr) with same shape as input.
        """
        shape = L_arr.shape
        pts = np.stack([L_arr.ravel(), t_arr.ravel()], axis=-1)
        eps = self._interp_eps(pts).reshape(shape)
        A0 = self._interp_A0(pts).reshape(shape)
        return eps, A0


# Singleton LUT cache
_lut_cache = {}


def get_geometry_lut(tpms_type, **kwargs):
    """Get or create a cached GeometryLUT instance.

    W7 (2026-07-07): the cache key includes the kwargs. The old
    tpms_type-only key ignored N / L_range / t_range on a hit — after any
    default-args call, a later ``get_geometry_lut('Diamond', N=512)``
    silently returned the N=256 LUT (the 2026-06-28 fix keyed the DISK
    cache correctly but left this in-memory half with the same defect).
    """
    key = (tpms_type,) + tuple(
        (k, tuple(v) if isinstance(v, (list, tuple)) else v)
        for k, v in sorted(kwargs.items()))
    if key not in _lut_cache:
        _lut_cache[key] = GeometryLUT(tpms_type, **kwargs)
    return _lut_cache[key]


# ── Vectorized property computation ──────────────────────────

def _nu_vec(tpms_type, Re, eps, L_mm, D_h_mm):
    """Back-compat thin wrapper. Delegates to ``nu_correlations.nu_vec``.

    The ``eps`` argument is kept for the legacy 5-arg signature (used by
    sigmoid_field_3d.py and tests/test_review_fixes.py) but unused since
    the 2026-05-28 audit Item 1 refactor (H1).

    Re_floor=10 preserves the legacy Re=np.maximum(Re, 10.0) behaviour.
    """
    del eps
    from .nu_correlations import nu_vec
    return nu_vec(tpms_type, Re, L_mm, D_h_mm)


# ── Main entry point ─────────────────────────────────────────

def build_continuous_arrays(x, L0, t0, y_trans_inlet, y_trans_outlet,
                            Nx, Ny, L_domain, H_domain,
                            tpms_type, k_s,
                            u_A, u_B, T_inA, T_inB,
                            lut, P_in=101325.0,
                            sigmoid_width_y=0.02, sigmoid_width_x=0.05,
                            fix_L=False, fix_t=False, opt_axis='y',
                            dx_arr=None, dy_arr=None,
                            allow_extrap=None, fluid_type='air', P_inB=None):
    """Build per-cell property arrays from sigmoid-interpolated L(x,y), t(x,y).

    AIR-ONLY: this builder hardcodes air ρ/μ/k/Nu (it predates the fluid
    registry). Guarded — a non-air fluid_type raises rather than silently
    using air properties (which would put h_v/K_ff off by 10-100×). Zoned/
    graded sCO2/water support is a deferred item; use uniform geometry for
    non-air fluids (the uniform path is per-fluid correct).

    Parameters
    ----------
    x : (36,) array — decision variables [L1,t1,...,L18,t18]
    L0, t0 : uniform zone parameters [mm]
    lut : GeometryLUT instance
    fix_L : if True, all L values fixed to L0 (optimize t only)
    fix_t : if True, all t values fixed to t0 (optimize L only)

    Returns
    -------
    dict with same keys as ZoneConfig.build_grid_arrays(), plus L_field, t_field
    """
    # 1. Extract control point arrays from decision variables
    ctrl_L_in = np.empty((3, 3))
    ctrl_t_in = np.empty((3, 3))
    ctrl_L_out = np.empty((3, 3))
    ctrl_t_out = np.empty((3, 3))
    for iy in range(3):
        for ix in range(3):
            idx_in = (iy * 3 + ix) * 2
            idx_out = 18 + (iy * 3 + ix) * 2
            ctrl_L_in[iy, ix] = L0 if fix_L else float(x[idx_in])
            ctrl_t_in[iy, ix] = t0 if fix_t else float(x[idx_in + 1])
            ctrl_L_out[iy, ix] = L0 if fix_L else float(x[idx_out])
            ctrl_t_out[iy, ix] = t0 if fix_t else float(x[idx_out + 1])

    # 2. Build fractional coordinate grids (support non-uniform)
    if dx_arr is not None:
        x_frac = (np.cumsum(dx_arr) - dx_arr / 2) / L_domain
    else:
        x_frac = np.linspace(0.5 / Nx, 1.0 - 0.5 / Nx, Nx)
    if dy_arr is not None:
        y_frac = (np.cumsum(dy_arr) - dy_arr / 2) / H_domain
    else:
        y_frac = np.linspace(0.5 / Ny, 1.0 - 0.5 / Ny, Ny)
    XF, YF = np.meshgrid(x_frac, y_frac, indexing='ij')  # (Nx, Ny)

    # 3. Sigmoid-interpolate L and t fields
    L_field = sigmoid_field_2d(XF, YF, ctrl_L_in, ctrl_L_out, L0,
                               y_trans_inlet, y_trans_outlet,
                               sigmoid_width_x, sigmoid_width_y)
    t_field = sigmoid_field_2d(XF, YF, ctrl_t_in, ctrl_t_out, t0,
                               y_trans_inlet, y_trans_outlet,
                               sigmoid_width_x, sigmoid_width_y)

    return _arrays_from_fields(
        L_field, t_field, tpms_type, k_s, u_A, u_B, T_inA, T_inB, lut,
        P_in=P_in, P_inB=P_inB, allow_extrap=allow_extrap,
        fluid_type=fluid_type, axis='continuous')


def _arrays_from_fields(L_field, t_field, tpms_type, k_s, u_A, u_B,
                        T_inA, T_inB, lut, *, P_in=101325., P_inB=None,
                        allow_extrap=None, fluid_type='air', axis):
    """Shared property assembly for the 2D and 3D sigmoid fields."""
    # Clip to fit range — bypassed under allow_extrap so user can sweep
    # outside the current CFD geometry grid.
    # Env var TPMSHX_ALLOW_EXTRAP=1 also triggers bypass for non-UI callers.
    if allow_extrap is None:
        import os as _os_ax
        allow_extrap = _os_ax.environ.get(
            'TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    if not allow_extrap:
        L_field = np.clip(L_field, *TRAIN_L)
        t_field = np.clip(t_field, *TRAIN_T)
    else:
        Lo, Lhi = float(L_field.min()), float(L_field.max())
        to, thi = float(t_field.min()), float(t_field.max())
        if Lo < TRAIN_L[0] or Lhi > TRAIN_L[1] or to < TRAIN_T[0] or thi > TRAIN_T[1]:
            import warnings as _w_ax
            _w_ax.warn(
                f"[geometry extrap] L=[{Lo:.2f},{Lhi:.2f}]mm "
                f"t=[{to:.3f},{thi:.3f}]mm outside fit "
                f"L{TRAIN_L} / t{TRAIN_T}; geometry LUT extrapolated.",
                stacklevel=2)

    # 4. Query LUT for epsilon and A_0
    eps_arr, A0_arr = lut.query(L_field, t_field)
    D_h_arr = 2.0 * eps_arr / (A0_arr + 1e-30)  # [m]

    # 5. Compute fluid properties (vectorized) — AIR ONLY (guarded above-call by
    # _check_zoned_fluid_support; this is the in-builder backstop so no caller
    # can silently get air props for a non-air fluid).
    if fluid_type != 'air':
        raise NotImplementedError(
            f"build_continuous_arrays hardcodes air properties; fluid_type="
            f"{fluid_type!r} would silently use air (h_v/K_ff off 10-100x). "
            "Zoned/graded non-air support is deferred — use uniform geometry.")
    k_fA = air_conductivity(T_inA)
    mu_A = air_viscosity(T_inA)
    rho_ref_A = air_density(T_inA, P_in)  # FIX (2026-06-24 audit): use actual P_in, not P_atm — Re scales with rho(P), matching tpms_calc.compute
    k_fB = air_conductivity(T_inB)
    mu_B = air_viscosity(T_inB)
    rho_ref_B = air_density(T_inB, P_in if P_inB is None else P_inB)

    # Reynolds (D_h convention, confirmed 2026-04-22)
    Re_A = np.maximum(rho_ref_A * u_A * D_h_arr / mu_A, 10.0)
    Re_B = np.maximum(rho_ref_B * u_B * D_h_arr / mu_B, 10.0)

    D_h_mm = D_h_arr * 1000.0
    Nu_A = _nu_vec(tpms_type, Re_A, eps_arr, L_field, D_h_mm)
    Nu_B = _nu_vec(tpms_type, Re_B, eps_arr, L_field, D_h_mm)

    H_sf_A = Nu_A * k_fA / D_h_arr
    H_sf_B = Nu_B * k_fB / D_h_arr
    h_vA_arr = H_sf_A * A0_arr
    h_vB_arr = H_sf_B * A0_arr

    K_ffA_arr = eps_arr * k_fA
    K_ffB_arr = eps_arr * k_fB
    # Apply the solid-conductivity factor χ_s to match the main field path
    # (run_stack_3d: K_ss = chi_s_eff(type, ε)·(1−ε)·k_s) and tpms_calc.
    # B2 (2026-07-06): per-cell fitted χ_s(type, ε) from unit-cell
    # homogenization; env TPMSHX_CHI_S constant still overrides.
    # (Thermal dispersion C_DISP is velocity-dependent and added downstream in
    #  the outer loop, not here; default C_DISP=0.0.)
    from sjtu_tpmshx.models.tpms_calc import chi_s_eff as _chi_s_eff
    K_ss_arr = _chi_s_eff(tpms_type, eps_arr) * (1.0 - eps_arr) * k_s

    return {
        'zone_id': np.zeros(L_field.shape, dtype=np.int32),  # continuous = single zone
        'eps_arr': eps_arr,
        'eps_f_arr': eps_arr / 2.0,
        'K_ffA_arr': K_ffA_arr,
        'K_ffB_arr': K_ffB_arr,
        'K_ss_arr': K_ss_arr,
        'h_vA_arr': h_vA_arr,
        'h_vB_arr': h_vB_arr,
        'r_h_arr': D_h_arr / 2.0,
        'A_0_arr': A0_arr,
        'L_field': L_field,
        't_field': t_field,
        'axis': axis,
    }


# compute_dP_continuous: REMOVED 2026-04-17.
# Legacy f-Re path that bypassed SIMPLE's D-F closure. All production dP
# extraction now goes through df_projection.extract_dP_from_simple() which
# uses SIMPLE's converged pressure field. See
# vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11.


# ── Standalone test ──────────────────────────────────────────

if __name__ == '__main__':
    print("=== GeometryLUT Test ===")
    lut = get_geometry_lut('Diamond')
    print(f"LUT shape: {lut.eps_table.shape}")

    # Verify against direct computation
    for L, t in [(4.0, 0.3), (6.0, 0.4), (8.0, 0.5)]:
        g = compute_geometry('Diamond', L, t)
        L_a = np.array([[L]]); t_a = np.array([[t]])
        eps_lut, A0_lut = lut.query(L_a, t_a)
        print(f"  L={L}, t={t}: eps_direct={g['epsilon']:.4f} eps_LUT={eps_lut[0,0]:.4f} "
              f"A0_direct={g['A_0']:.1f} A0_LUT={A0_lut[0,0]:.1f}")

    print("\n=== Sigmoid Field Test ===")
    Nx, Ny = 30, 15
    x = np.array([6.0, 0.3] * 18)  # uniform
    x[0:2] = [4.0, 0.4]  # make one inlet zone different
    za = build_continuous_arrays(
        x, 6.0, 0.3, 0.2, 0.2,
        Nx, Ny, 0.1, 0.05,
        'Diamond', 15.0,
        10.0, 10.0, 400.0, 300.0,
        lut)
    print(f"  L_field range: [{za['L_field'].min():.2f}, {za['L_field'].max():.2f}]")
    print(f"  t_field range: [{za['t_field'].min():.3f}, {za['t_field'].max():.3f}]")
    print(f"  eps range: [{za['eps_arr'].min():.4f}, {za['eps_arr'].max():.4f}]")
    print(f"  h_vA range: [{za['h_vA_arr'].min():.0f}, {za['h_vA_arr'].max():.0f}]")
    print("=== All tests passed ===")
