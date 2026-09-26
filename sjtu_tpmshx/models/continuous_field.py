"""
continuous_field.py — Continuous L/t field parametrization in two or three dimensions for
optimization-friendly TPMS heat-exchanger design.

Replaces the discrete patch-zoning representation (18 patches × {L, t} = 36-D)
with a low-dimensional control-point representation (4×4 × {L, t} with optional
Y-mirror = 16-D) interpolated via bicubic B-spline tensor products. Gives:

  * continuous L/t parameter fields without patch jumps; smooth before
    clipping, which can introduce derivative discontinuities;
  * substantially smaller search space for the optimizer (16-D vs 36-D)
    while remaining expressive enough to describe the physically meaningful
    inlet-dense / outlet-coarse and lateral-graded patterns.

Parameter continuity does not establish explicit TPMS surface connectivity,
minimum geometric wall thickness, or manufacturability.

The legacy ``build_grid_arrays`` helper assembles quantized per-cell TPMS
properties in the same two-dimensional format as ``ZoneConfig``. Full-volume
preparation instead samples explicit XYZ controls with ``evaluate_volume``;
omitting z controls retains the existing XY representation.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple

from scipy.interpolate import RectBivariateSpline, make_interp_spline

from . import tpms_calc

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ─── Default decision-vector layout ─────────────────────────────────

DEFAULT_N_CTRL_X = 4
DEFAULT_N_CTRL_Y = 4
DEFAULT_SYMMETRIC_Y = True

# Geometry bounds [mm]; independent of per-fluid Nu applicability.
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L as DEFAULT_L_BOUNDS, TRAIN_T as DEFAULT_T_BOUNDS
# Manufacturability ratio: lower-bounded slightly below 0.3/8 = 0.0375 so
# the corner (L=8, t=0.3) does not trip the penalty; upper-bounded loose.
DEFAULT_RATIO_BOUNDS = (0.035, 0.20)   # t / L


def decision_dim(n_ctrl_x: int = DEFAULT_N_CTRL_X,
                 n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                 symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                 *, n_ctrl_z: int | None = None) -> int:
    """Return number of optimizer decision variables for the given layout.

    With symmetric_y, only the lower half of the y-axis is stored (rounded
    up for odd My); the upper half is mirrored at decode time. Supplying
    n_ctrl_z adds that many independently controlled planes in z.
    """
    for count in (n_ctrl_x, n_ctrl_y) + (() if n_ctrl_z is None else (n_ctrl_z,)):
        if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 2:
            raise ValueError('Need integer control counts >=2 per axis')
    My_eff = (n_ctrl_y + 1) // 2 if symmetric_y else n_ctrl_y
    return 2 * n_ctrl_x * My_eff * (1 if n_ctrl_z is None else n_ctrl_z)


def decision_bounds(n_ctrl_x: int = DEFAULT_N_CTRL_X,
                    n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                    symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                    L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS,
                    t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS,
                    *, n_ctrl_z: int | None = None
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """Return (lb, ub) numpy arrays of length decision_dim(...)."""
    n_per_field = decision_dim(n_ctrl_x, n_ctrl_y, symmetric_y, n_ctrl_z=n_ctrl_z) // 2
    lb = np.concatenate([np.full(n_per_field, L_bounds[0]),
                         np.full(n_per_field, t_bounds[0])])
    ub = np.concatenate([np.full(n_per_field, L_bounds[1]),
                         np.full(n_per_field, t_bounds[1])])
    return lb, ub


def decode_decision_vector(x: np.ndarray,
                           n_ctrl_x: int = DEFAULT_N_CTRL_X,
                           n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                           symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                           *, n_ctrl_z: int | None = None
                           ) -> Tuple[np.ndarray, np.ndarray]:
    """Decode flat decisions to (Mx, My) or (Mx, My, Mz) control grids.

    Layout: x = [L_unique_flat, t_unique_flat]. Under symmetric_y, the unique
    half is the first ⌈My/2⌉ rows along y; the remaining rows are mirrored
    in place from the half (excluding the seam row when My is odd).
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or not np.all(np.isfinite(x)):
        raise ValueError('decision vector must be one-dimensional and finite')
    My_eff = (n_ctrl_y + 1) // 2 if symmetric_y else n_ctrl_y
    n_per_field = decision_dim(n_ctrl_x, n_ctrl_y, symmetric_y, n_ctrl_z=n_ctrl_z) // 2
    expected = 2 * n_per_field
    if x.size != expected:
        raise ValueError(
            f"decision vector length {x.size} != expected {expected} "
            f"for layout n_ctrl=({n_ctrl_x},{n_ctrl_y}) symmetric_y={symmetric_y}"
        )

    shape = (n_ctrl_x, My_eff) + (() if n_ctrl_z is None else (n_ctrl_z,))
    L_half = x[:n_per_field].reshape(shape)
    t_half = x[n_per_field:].reshape(shape)

    if symmetric_y:
        # Mirror along y: drop the seam (centre row) when My is odd
        seam_skip = n_ctrl_y % 2
        L_mirror = L_half[:, ::-1][:, seam_skip:]
        t_mirror = t_half[:, ::-1][:, seam_skip:]
        L_full = np.concatenate([L_half, L_mirror], axis=1)
        t_full = np.concatenate([t_half, t_mirror], axis=1)
    else:
        L_full = L_half
        t_full = t_half

    return L_full, t_full


def encode_decision_vector(L_ctrl: np.ndarray,
                           t_ctrl: np.ndarray,
                           symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                           *, n_ctrl_z: int | None = None) -> np.ndarray:
    """Inverse of decode_decision_vector — useful for warm-starts / tests.

    With symmetric_y, only the lower half is taken; the function does NOT
    enforce symmetry of the input (caller's responsibility). Use a symmetric
    seed if you want symmetric_y=True to round-trip exactly.
    """
    L_ctrl = np.asarray(L_ctrl, dtype=np.float64)
    t_ctrl = np.asarray(t_ctrl, dtype=np.float64)
    if (L_ctrl.ndim not in (2, 3) or L_ctrl.shape != t_ctrl.shape
            or not np.all(np.isfinite(L_ctrl)) or not np.all(np.isfinite(t_ctrl))):
        raise ValueError('L/t controls must be finite, matching two- or three-dimensional grids')
    if n_ctrl_z is not None and (L_ctrl.ndim != 3 or L_ctrl.shape[2] != n_ctrl_z):
        raise ValueError('n_ctrl_z does not match the control grid')
    decision_dim(*L_ctrl.shape[:2], symmetric_y,
                 n_ctrl_z=n_ctrl_z if n_ctrl_z is not None else
                 (L_ctrl.shape[2] if L_ctrl.ndim == 3 else None))
    if symmetric_y:
        My = L_ctrl.shape[1]
        My_eff = (My + 1) // 2
        return np.concatenate([L_ctrl[:, :My_eff].ravel(),
                               t_ctrl[:, :My_eff].ravel()])
    return np.concatenate([L_ctrl.ravel(), t_ctrl.ravel()])


# ─── shared quantized TPMS-property scatter ─────────────────────────


def props_from_Lt_fields(L_field: np.ndarray, t_field: np.ndarray,
                         tpms_type: str, k_s: float,
                         u_A: float, u_B: float,
                         T_inA: float, T_inB: float,
                         P_in: float = 101325.0,
                         *, P_inB: float | None = None, quant_L: float = 0.05,
                         quant_t: float = 0.01) -> dict:
    """Per-cell TPMS property arrays from (L, t) fields via quantized scatter.

    Quantise (L, t) to the (quant_L, quant_t) mm grid, evaluate
    ``tpms_calc.compute`` once per UNIQUE (L, t) pair (A + B side), and
    gather the unique values into output arrays — calls compute()
    n_unique times instead of L_field.size. Shared by
    :meth:`ContinuousFieldConfig.build_grid_arrays` (2D) and
    ``models.screening._build_3d_arrays`` (3D, which z-broadcasts the result),
    so both dimensions use one quantisation + scatter (B3 C7).

    Returns a dict of nine ``L_field.shape`` arrays — ``eps_arr``,
    ``eps_f_arr``, ``K_ffA_arr``, ``K_ffB_arr``, ``K_ss_arr``, ``h_vA_arr``,
    ``h_vB_arr``, ``r_h_arr``, ``A_0_arr`` — plus ``n_unique``.
    """
    P_inB = P_in if P_inB is None else P_inB
    L_q = np.round(L_field / quant_L) * quant_L
    t_q = np.round(t_field / quant_t) * quant_t

    shp = L_field.shape
    # Evaluate each unique quantised pair once per side, then use the inverse
    # index to recover cell order without scanning the full grid per pair.
    L_key = np.round(L_q, 4)
    t_key = np.round(t_q, 4)
    pairs = np.stack([L_key.ravel(), t_key.ravel()], axis=1)
    uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    values = {name: np.empty(uniq.shape[0], dtype=np.float64) for name in (
        'eps_arr', 'eps_f_arr', 'K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
        'h_vA_arr', 'h_vB_arr', 'r_h_arr', 'A_0_arr')}
    for u_idx in range(uniq.shape[0]):
        L_u = float(uniq[u_idx, 0]); t_u = float(uniq[u_idx, 1])
        pA = tpms_calc.compute(tpms_type, L_u, t_u, u_A, T_inA, P_in, k_s)
        pB = tpms_calc.compute(tpms_type, L_u, t_u, u_B, T_inB, P_inB, k_s)
        values['eps_arr'][u_idx] = pA['epsilon']
        values['eps_f_arr'][u_idx] = pA['epsilon_A']
        values['K_ffA_arr'][u_idx] = pA['K_ff']
        values['K_ffB_arr'][u_idx] = pB['K_ff']
        values['K_ss_arr'][u_idx] = pA['K_ss']
        values['h_vA_arr'][u_idx] = pA['H_sf'] * pA['A_0']
        values['h_vB_arr'][u_idx] = pB['H_sf'] * pB['A_0']
        values['r_h_arr'][u_idx] = pA['D_h'] / 2.0
        values['A_0_arr'][u_idx] = pA['A_0']

    result = {name: table[inv].reshape(shp) for name, table in values.items()}
    result['n_unique'] = int(uniq.shape[0])
    return result


# ─── ContinuousFieldConfig ──────────────────────────────────────────


def _cell_centres(count, length, widths):
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 1:
        raise ValueError('grid counts must be positive integers')
    if widths is None:
        return (np.arange(count) + 0.5) * (length / count)
    widths = np.asarray(widths, dtype=np.float64)
    if (widths.shape != (count,) or not np.all(np.isfinite(widths) & (widths > 0))
            or not np.isclose(widths.sum(), length, rtol=1e-12, atol=0.)):
        raise ValueError('cell widths must be finite, positive and cover the field domain')
    edges = np.r_[0., np.cumsum(widths)]
    return 0.5 * (edges[:-1] + edges[1:])


@dataclass
class ContinuousFieldConfig:
    """Continuous spatial field of (L, t) parameters via B-spline interpolation
    over a coarse control grid. Drop-in producer for ZoneConfig.build_grid_arrays.

    Input control axes and values are copied at construction. To change a
    field's control axes or values, construct a new instance so its controls
    and interpolation state continue to describe the same geometry.

    Parameters
    ----------
    ctrl_x : (Mx,) array — control x positions [m] sorted, in [0, L_domain]
    ctrl_y : (My,) array — control y positions [m] sorted, in [0, H_domain]
    L_ctrl, t_ctrl : (Mx, My) or (Mx, My, Mz) arrays, values in mm
    tpms_type : 'Diamond' | 'Gyroid'
    k_s : solid conductivity [W/(m K)]
    L_domain, H_domain : HX domain size [m]
    ctrl_z, Lz_domain : optional z controls and domain depth for XYZ fields
    spline_order : tensor-product degree 1, 2 or 3 (default)
    L_bounds, t_bounds : physical clamps applied after spline evaluation
                         (defensive — splines can overshoot near boundaries)
    """

    ctrl_x: np.ndarray
    ctrl_y: np.ndarray
    L_ctrl: np.ndarray
    t_ctrl: np.ndarray
    tpms_type: str
    k_s: float
    L_domain: float
    H_domain: float
    spline_order: int = 3
    L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS
    t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS
    ctrl_z: np.ndarray | None = None
    Lz_domain: float | None = None

    def __post_init__(self):
        self.ctrl_x = np.array(self.ctrl_x, dtype=np.float64, copy=True)
        self.ctrl_y = np.array(self.ctrl_y, dtype=np.float64, copy=True)
        self.L_ctrl = np.array(self.L_ctrl, dtype=np.float64, copy=True)
        self.t_ctrl = np.array(self.t_ctrl, dtype=np.float64, copy=True)

        if (self.ctrl_z is None) != (self.Lz_domain is None):
            raise ValueError('ctrl_z and Lz_domain must be supplied together')
        if (isinstance(self.spline_order, (bool, np.bool_))
                or not isinstance(self.spline_order, (int, np.integer))
                or self.spline_order not in (1, 2, 3)):
            raise ValueError('spline_order must be 1, 2 or 3')
        axes = [(self.ctrl_x, self.L_domain), (self.ctrl_y, self.H_domain)]
        if self.ctrl_z is not None:
            self.ctrl_z = np.array(self.ctrl_z, dtype=np.float64, copy=True)
            axes.append((self.ctrl_z, self.Lz_domain))
        for nodes, length in axes:
            if not np.isfinite(length) or length <= 0:
                raise ValueError('field domain lengths must be finite and positive')
            if (nodes.ndim != 1 or nodes.size < 2 or not np.all(np.isfinite(nodes))
                    or not np.all(np.diff(nodes) > 0)
                    or nodes[0] != 0.0 or nodes[-1] != length):
                raise ValueError('control axes must increase from zero to the full domain length')
            if self.ctrl_z is not None and nodes.size <= self.spline_order:
                raise ValueError('3D fields need more controls per axis than spline_order')
        shape = tuple(nodes.size for nodes, _ in axes)
        for values in (self.L_ctrl, self.t_ctrl):
            if values.shape != shape or not np.all(np.isfinite(values)):
                raise ValueError(f'L/t controls must be finite arrays of shape {shape}')
        for bounds in (self.L_bounds, self.t_bounds):
            if len(bounds) != 2 or not np.all(np.isfinite(bounds)) or not 0 < bounds[0] < bounds[1]:
                raise ValueError('L/t bounds must be finite, positive and increasing')
        if self.ctrl_z is None:
            # Preserve the historical 2D spline, including its lower-order
            # fallback for small direct-call control grids.
            kx = min(self.spline_order, self.ctrl_x.size - 1)
            ky = min(self.spline_order, self.ctrl_y.size - 1)
            self._L_spline = RectBivariateSpline(
                self.ctrl_x, self.ctrl_y, self.L_ctrl, kx=kx, ky=ky)
            self._t_spline = RectBivariateSpline(
                self.ctrl_x, self.ctrl_y, self.t_ctrl, kx=kx, ky=ky)

    # ─── Field evaluation ────────────────────────────────────────────


    def evaluate_grid(self, Nx: int, Ny: int,
                      dx_arr: Optional[np.ndarray] = None,
                      dy_arr: Optional[np.ndarray] = None
                      ) -> Tuple[np.ndarray, np.ndarray]:
        """Evaluate L, t at cell centers of (Nx, Ny) grid. Returns
        (L_field, t_field) each shape (Nx, Ny), values in mm, clamped.
        """
        if self.ctrl_z is not None:
            raise ValueError('use evaluate_volume for a three-dimensional control field')
        xc = _cell_centres(Nx, self.L_domain, dx_arr)
        yc = _cell_centres(Ny, self.H_domain, dy_arr)

        L_field = self._L_spline(xc, yc, grid=True)   # shape (Nx, Ny)
        t_field = self._t_spline(xc, yc, grid=True)
        # Preserve the exact constant polynomial; spline roundoff must not
        # turn a uniform reference into a weakly varying coefficient field.
        if np.all(self.L_ctrl == self.L_ctrl.flat[0]):
            L_field.fill(self.L_ctrl.flat[0])
        if np.all(self.t_ctrl == self.t_ctrl.flat[0]):
            t_field.fill(self.t_ctrl.flat[0])
        np.clip(L_field, self.L_bounds[0], self.L_bounds[1], out=L_field)
        np.clip(t_field, self.t_bounds[0], self.t_bounds[1], out=t_field)
        return L_field, t_field

    def evaluate_volume(self, Nx: int, Ny: int, Nz: int,
                        dx_arr: Optional[np.ndarray] = None,
                        dy_arr: Optional[np.ndarray] = None,
                        dz_arr: Optional[np.ndarray] = None
                        ) -> Tuple[np.ndarray, np.ndarray]:
        """Sample true XYZ fields at physical cell centres; return mm arrays.

        Tensor-product interpolation supports linear, quadratic and cubic
        orders. Old XY inputs continue to use evaluate_grid explicitly.
        """
        if self.ctrl_z is None:
            raise ValueError('evaluate_volume requires ctrl_z and Lz_domain')
        centres = (_cell_centres(Nx, self.L_domain, dx_arr),
                   _cell_centres(Ny, self.H_domain, dy_arr),
                   _cell_centres(Nz, self.Lz_domain, dz_arr))
        fields = []
        for values, bounds in ((self.L_ctrl, self.L_bounds), (self.t_ctrl, self.t_bounds)):
            if np.all(values == values.flat[0]):
                sampled = np.full((Nx, Ny, Nz), values.flat[0], dtype=np.float64)
            else:
                sampled = values
                for axis, (nodes, points) in enumerate(zip(
                        (self.ctrl_x, self.ctrl_y, self.ctrl_z), centres)):
                    sampled = make_interp_spline(nodes, sampled, k=self.spline_order,
                                                  axis=axis)(points)
            np.clip(sampled, *bounds, out=sampled)
            fields.append(np.ascontiguousarray(sampled))
        return tuple(fields)

    # ─── Per-cell property assembly ──────────────────────────────────

    def build_grid_arrays(self, Nx: int, Ny: int,
                          u_A: float, u_B: float,
                          T_inA: float, T_inB: float,
                          P_in: float = 101325.0,
                          dx_arr: Optional[np.ndarray] = None,
                          dy_arr: Optional[np.ndarray] = None,
                          quant_L: float = 0.05,
                          quant_t: float = 0.01, *, P_inB: float | None = None) -> dict:
        """Build per-cell property arrays. Drop-in for ZoneConfig.build_grid_arrays.

        Strategy
        --------
        1. Evaluate (L, t) at every cell center via spline → (Nx, Ny) field.
        2. Quantize to (quant_L, quant_t) mm grid so we don't call
           ``tpms_calc.compute`` Nx·Ny times — typically a few hundred unique
           (L, t) combos at most.
        3. Pull props from the cache and pack into the standard dict shape.
        """
        L_field, t_field = self.evaluate_grid(Nx, Ny, dx_arr, dy_arr)
        # Quantized scatter shared with the 3D builder (B3 C7) — same ops,
        # same order, so bit-identical to the prior inline loop.
        p = props_from_Lt_fields(L_field, t_field, self.tpms_type, self.k_s,
                                 u_A, u_B, T_inA, T_inB, P_in,
                                 P_inB=P_inB, quant_L=quant_L, quant_t=quant_t)

        from .grid_schema import validate_grid_arrays
        return validate_grid_arrays({
            'zone_id':   np.zeros((Nx, Ny), dtype=np.int32),  # not used downstream
            'eps_arr':   p['eps_arr'],
            'eps_f_arr': p['eps_f_arr'],
            'K_ffA_arr': p['K_ffA_arr'],
            'K_ffB_arr': p['K_ffB_arr'],
            'K_ss_arr':  p['K_ss_arr'],
            'h_vA_arr':  p['h_vA_arr'],
            'h_vB_arr':  p['h_vB_arr'],
            'r_h_arr':   p['r_h_arr'],
            'A_0_arr':   p['A_0_arr'],
            'axis': 'continuous',
            'L_field': L_field,
            't_field': t_field,
            'cache_size': p['n_unique'],
        }, Nx, Ny, where='ContinuousFieldConfig.build_grid_arrays')

    # ─── Manufacturability checks ────────────────────────────────────

    def manufacturability_penalty(self,
                                  grad_threshold: float = 0.5,
                                  ratio_bounds: Tuple[float, float] = DEFAULT_RATIO_BOUNDS,
                                  weight_grad: float = 100.0,
                                  weight_ratio: float = 1000.0) -> float:
        """Soft penalty (≥ 0) for manufacturability hazards.

        Penalizes:
          * inter-control-point gradient |ΔL| > grad_threshold · L_avg
            (graded TPMS surface tearing risk per Yang 2018);
          * t/L ratio outside ratio_bounds (physically implausible aspect).

        Returns 0.0 when clean. Caller adds this to the dP objective so the
        optimizer learns to avoid hazards rather than the optimizer-side
        constraint machinery rejecting samples (which destabilizes BO).
        """
        pen = 0.0

        L = self.L_ctrl
        L_avg = float(L.mean())
        grad_max = max(np.abs(np.diff(L, axis=axis)).max() for axis in range(L.ndim))
        if grad_max > grad_threshold * L_avg:
            pen += weight_grad * (grad_max - grad_threshold * L_avg)

        ratio = self.t_ctrl / np.maximum(self.L_ctrl, 1e-9)
        rmin, rmax = ratio_bounds
        if ratio.max() > rmax:
            pen += weight_ratio * (float(ratio.max()) - rmax)
        if ratio.min() < rmin:
            pen += weight_ratio * (rmin - float(ratio.min()))

        return float(pen)


# ─── Constructor for the optimizer ──────────────────────────────────


def from_decision_vector(x: np.ndarray,
                         tpms_type: str,
                         k_s: float,
                         L_domain: float,
                         H_domain: float,
                         n_ctrl_x: int = DEFAULT_N_CTRL_X,
                         n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                         symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                         spline_order: int = 3,
                         L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS,
                         t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS,
                         *, Lz_domain: float | None = None,
                         n_ctrl_z: int | None = None
                         ) -> ContinuousFieldConfig:
    """Build a ContinuousFieldConfig from a flat optimizer decision vector.

    Control point positions are equispaced along each axis covering the full
    [0, L_domain] × [0, H_domain] domain, with [0, Lz_domain] when n_ctrl_z
    is supplied. Decisions flatten each control grid in C order: z varies
    fastest for XYZ grids, followed by y and x.
    """
    if (n_ctrl_z is None) != (Lz_domain is None):
        raise ValueError('n_ctrl_z and Lz_domain must be supplied together')
    L_ctrl, t_ctrl = decode_decision_vector(x, n_ctrl_x, n_ctrl_y, symmetric_y,
                                           n_ctrl_z=n_ctrl_z)
    ctrl_x = np.linspace(0.0, L_domain, n_ctrl_x)
    ctrl_y = np.linspace(0.0, H_domain, n_ctrl_y)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
        spline_order=spline_order,
        L_bounds=L_bounds, t_bounds=t_bounds,
        ctrl_z=None if n_ctrl_z is None else np.linspace(0.0, Lz_domain, n_ctrl_z),
        Lz_domain=Lz_domain,
    )


# ─── Convenience: uniform-field constructor ────────────────────────


def uniform_field(L_mm: float, t_mm: float,
                  tpms_type: str, k_s: float,
                  L_domain: float, H_domain: float,
                  n_ctrl_x: int = DEFAULT_N_CTRL_X,
                  n_ctrl_y: int = DEFAULT_N_CTRL_Y) -> ContinuousFieldConfig:
    """Build a uniform-field config (useful for sanity checks vs single-zone)."""
    L_ctrl = np.full((n_ctrl_x, n_ctrl_y), L_mm, dtype=np.float64)
    t_ctrl = np.full((n_ctrl_x, n_ctrl_y), t_mm, dtype=np.float64)
    ctrl_x = np.linspace(0.0, L_domain, n_ctrl_x)
    ctrl_y = np.linspace(0.0, H_domain, n_ctrl_y)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
    )
