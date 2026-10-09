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

Full preparation samples XY controls with ``evaluate_grid`` or explicit XYZ
controls with ``evaluate_volume`` before resolving local material properties.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple

from scipy.interpolate import RectBivariateSpline, make_interp_spline

# ─── Default decision-vector layout ─────────────────────────────────

DEFAULT_N_CTRL_X = 4
DEFAULT_N_CTRL_Y = 4
DEFAULT_SYMMETRIC_Y = True

# Geometry bounds [mm]; independent of per-fluid Nu applicability.
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L as DEFAULT_L_BOUNDS, TRAIN_T as DEFAULT_T_BOUNDS


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
        if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 1:
            raise ValueError('Need integer control counts >=1 per axis')
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


def control_axis(count, length):
    """Equally spaced controls; a constant axis is recorded at its midplane."""
    return np.array([length / 2.]) if count == 1 else np.linspace(0., length, count)


@dataclass
class ContinuousFieldConfig:
    """Continuous spatial field of (L, t) parameters via B-spline interpolation
    over a coarse control grid for full preparation and geometry export.

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
            if (nodes.ndim != 1 or nodes.size < 1 or not np.all(np.isfinite(nodes))
                    or not np.all(np.diff(nodes) > 0)
                    or (nodes[0] != length / 2. if nodes.size == 1 else
                        nodes[0] != 0.0 or nodes[-1] != length)):
                raise ValueError('control axes must increase across the domain, or use its midpoint for one control')
        shape = tuple(nodes.size for nodes, _ in axes)
        for values in (self.L_ctrl, self.t_ctrl):
            if values.shape != shape or not np.all(np.isfinite(values)):
                raise ValueError(f'L/t controls must be finite arrays of shape {shape}')
        for bounds in (self.L_bounds, self.t_bounds):
            if len(bounds) != 2 or not np.all(np.isfinite(bounds)) or not 0 < bounds[0] < bounds[1]:
                raise ValueError('L/t bounds must be finite, positive and increasing')
        if self.ctrl_z is None and min(self.ctrl_x.size, self.ctrl_y.size) > 1:
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

        return self.evaluate_axes(xc, yc)

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
        return self.evaluate_axes(*centres)

    def evaluate_axes(self, *coordinates):
        """Evaluate the same physical field on Cartesian sampling axes in m."""
        nodes = (self.ctrl_x, self.ctrl_y) + (() if self.ctrl_z is None else (self.ctrl_z,))
        lengths = (self.L_domain, self.H_domain) + (() if self.ctrl_z is None else (self.Lz_domain,))
        if len(coordinates) != len(nodes):
            raise ValueError('sampling axes must match the field dimension')
        coordinates = tuple(np.asarray(points, dtype=float) for points in coordinates)
        for points, length in zip(coordinates, lengths):
            if (points.ndim != 1 or not points.size or not np.all(np.isfinite(points))
                    or np.any(np.diff(points) <= 0) or points[0] < 0 or points[-1] > length):
                raise ValueError('sampling axes must be finite, increasing and inside the field domain')
        shape = tuple(points.size for points in coordinates)
        fields = []
        for values, bounds, name in ((self.L_ctrl, self.L_bounds, '_L_spline'),
                                     (self.t_ctrl, self.t_bounds, '_t_spline')):
            if np.all(values == values.flat[0]):
                sampled = np.full(shape, values.flat[0], dtype=np.float64)
            elif self.ctrl_z is None and min(self.ctrl_x.size, self.ctrl_y.size) > 1:
                sampled = getattr(self, name)(*coordinates, grid=True)
            else:
                sampled = values
                for axis, (control, points) in enumerate(zip(nodes, coordinates)):
                    if control.size == 1:
                        sampled = np.repeat(sampled, points.size, axis=axis)
                    else:
                        sampled = make_interp_spline(control, sampled,
                            k=min(self.spline_order, control.size - 1), axis=axis)(points)
            np.clip(sampled, *bounds, out=sampled)
            fields.append(np.ascontiguousarray(sampled))
        return tuple(fields)


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
    ctrl_x = control_axis(n_ctrl_x, L_domain)
    ctrl_y = control_axis(n_ctrl_y, H_domain)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
        spline_order=spline_order,
        L_bounds=L_bounds, t_bounds=t_bounds,
        ctrl_z=None if n_ctrl_z is None else control_axis(n_ctrl_z, Lz_domain),
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
    ctrl_x = control_axis(n_ctrl_x, L_domain)
    ctrl_y = control_axis(n_ctrl_y, H_domain)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
    )
