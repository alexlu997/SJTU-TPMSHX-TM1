"""
zone_config.py — Zone-based domain partitioning for SJTU-TPMSHX

Discrete zones belong to the full Compute path: preparation consumes a
ZoneInputConfig from the GUI or saved configuration. The optimizer uses
models.continuous_field.ContinuousFieldConfig for its continuous search space;
the GUI's single-point zone card does not participate in that search.

Defines discrete zones along the y-axis, each with independent TPMS
parameters (L, t). Computes per-zone properties and builds per-cell
arrays for use in solvers.

Usage:
    zc = ZoneConfig(
        zones=[
            Zone('inlet',  0.0, 0.2, L_mm=4, t_mm=0.4),
            Zone('middle', 0.2, 0.8, L_mm=6, t_mm=0.3),
            Zone('outlet', 0.8, 1.0, L_mm=4, t_mm=0.4),
        ],
        tpms_type='Diamond', k_s=15.0
    )
    zc.compute_properties(u_A=5.0, u_B=3.0, T_inA=400, T_inB=300, P_in=101325)
    arrays = zc.build_structured_arrays(Nx=60, Ny=80, H=0.1)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List
from . import tpms_calc

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


def _geometry_fields(zone_id, cells, tpms_type, k_s):
    """Scatter geometry-only zone values through the existing cell assignment."""
    values = [tpms_calc.geometry(tpms_type, cell, wall, k_s) for cell, wall in cells]
    fields = {
        key: np.asarray([item[prop] for item in values], dtype=np.float64)[zone_id]
        for key, prop in (('eps_arr', 'epsilon'), ('eps_f_arr', 'epsilon_A'),
                          ('K_ss_arr', 'K_ss'), ('A_0_arr', 'A_0'))
    }
    fields['r_h_arr'] = np.asarray([item['D_h'] / 2. for item in values])[zone_id]
    for index, key in enumerate(('L_field', 't_field')):
        fields[key] = np.asarray([pair[index] for pair in cells], dtype=np.float64)[zone_id]
    return {'zone_id': zone_id, **fields}


@dataclass
class Zone:
    """A single zone with its own TPMS geometry."""
    name: str
    y_frac_start: float      # 0.0 ~ 1.0
    y_frac_end: float
    L_mm: float               # unit cell size [mm]
    t_mm: float               # wall thickness [mm]
    # Filled by compute_properties():
    props_A: dict = field(default_factory=dict)   # tpms_calc.compute() for fluid A
    props_B: dict = field(default_factory=dict)   # tpms_calc.compute() for fluid B


@dataclass
class ZoneConfig:
    """Multi-zone domain configuration."""
    zones: List[Zone]
    tpms_type: str
    k_s: float                # solid conductivity [W/(m K)]

    # ── Validation ──────────────────────────────────────────────

    def validate(self):
        """Check zones cover [0, 1] without gaps or overlaps."""
        if not self.zones:
            raise ValueError("At least one zone is required")

        # Sort by start
        zs = sorted(self.zones, key=lambda z: z.y_frac_start)

        if abs(zs[0].y_frac_start) > 1e-9:
            raise ValueError(f"First zone must start at 0, got {zs[0].y_frac_start}")
        if abs(zs[-1].y_frac_end - 1.0) > 1e-9:
            raise ValueError(f"Last zone must end at 1.0, got {zs[-1].y_frac_end}")

        for i in range(len(zs) - 1):
            gap = abs(zs[i].y_frac_end - zs[i+1].y_frac_start)
            if gap > 1e-9:
                raise ValueError(
                    f"Gap/overlap between zone '{zs[i].name}' (end={zs[i].y_frac_end}) "
                    f"and '{zs[i+1].name}' (start={zs[i+1].y_frac_start})"
                )

        for z in zs:
            if z.y_frac_end <= z.y_frac_start:
                raise ValueError(f"Zone '{z.name}': end <= start")
            if not (1.0 <= z.L_mm <= 20.0):
                raise ValueError(f"Zone '{z.name}': L_mm={z.L_mm} outside [1, 20]")
            if not (0.1 <= z.t_mm <= 2.0):
                raise ValueError(f"Zone '{z.name}': t_mm={z.t_mm} outside [0.1, 2.0]")

        self.zones = zs  # store sorted

    # ── Property computation ────────────────────────────────────

    def compute_properties(self, u_A: float, u_B: float,
                           T_inA: float, T_inB: float,
                           P_in: float = 101325.0, *, P_inB: float | None = None):
        """Compute TPMS properties for each zone using tpms_calc.compute()."""
        self.validate()
        P_inB = P_in if P_inB is None else P_inB
        for z in self.zones:
            z.props_A = tpms_calc.compute(
                self.tpms_type, z.L_mm, z.t_mm, u_A, T_inA, P_in, self.k_s)
            z.props_B = tpms_calc.compute(
                self.tpms_type, z.L_mm, z.t_mm, u_B, T_inB, P_inB, self.k_s)

    # ── Structured grid arrays ──────────────────────────────────

    def build_structured_arrays(self, Nx: int, Ny: int, H: float,
                                axis: str = 'y', *, dx_arr=None, dy_arr=None) -> dict:
        """Build 2D per-cell property arrays for structured rectangular grid.

        Parameters
        ----------
        Nx, Ny : grid cells in x and y
        H      : domain size along partition axis [m]
        axis   : 'y' or 'x' — which axis zones are defined along
        dx_arr, dy_arr : actual cell widths [m]; None uses uniform centres.

        Returns
        -------
        dict with 2D arrays (Nx, Ny) + 'axis' key.
        """
        if not self.zones or not self.zones[0].props_A:
            raise RuntimeError("Call compute_properties() before building arrays.")

        arrays = self.build_structured_geometry(Nx, Ny, H, axis, dx_arr=dx_arr, dy_arr=dy_arr)
        zone_id = arrays['zone_id']
        for side in ('A', 'B'):
            properties = [getattr(zone, 'props_' + side) for zone in self.zones]
            arrays['K_ff' + side + '_arr'] = np.asarray(
                [props['K_ff'] for props in properties], dtype=np.float64)[zone_id]
            arrays['h_v' + side + '_arr'] = np.asarray(
                [props['H_sf'] * props['A_0'] for props in properties], dtype=np.float64)[zone_id]
        arrays['zone_params'] = [
            dict(name=z.name, y_frac_start=z.y_frac_start, y_frac_end=z.y_frac_end,
                 L_mm=z.L_mm, t_mm=z.t_mm, epsilon=z.props_A['epsilon'],
                 D_h=z.props_A['D_h'], r_h=z.props_A['D_h'] / 2., A_0=z.props_A['A_0'],
                 mu=z.props_A['mu'], rho=z.props_A['rho'])
            for z in self.zones]
        from .grid_schema import validate_grid_arrays
        return validate_grid_arrays(arrays, Nx, Ny, where='ZoneConfig.build_structured_arrays')

    def build_structured_geometry(self, Nx: int, Ny: int, H: float,
                                  axis: str = 'y', *, dx_arr=None, dy_arr=None) -> dict:
        """Sample stripe geometry without evaluating velocity-dependent properties."""
        self.validate()
        N_ax = Ny if axis == 'y' else Nx
        widths = dy_arr if axis == 'y' else dx_arr
        if widths is None:
            d_ax = H / N_ax
            fc = np.array([(k + 0.5) * d_ax / H for k in range(N_ax)])
        else:
            widths = np.asarray(widths, dtype=np.float64)
            fc = (np.cumsum(widths) - 0.5 * widths) / H

        zone_id_1d = np.zeros(N_ax, dtype=np.int32)
        for k in range(N_ax):
            for zi, z in enumerate(self.zones):
                if z.y_frac_start <= fc[k] < z.y_frac_end:
                    zone_id_1d[k] = zi
                    break
            else:
                zone_id_1d[k] = len(self.zones) - 1

        zone_id = np.broadcast_to(zone_id_1d if axis == 'y' else zone_id_1d[:, None],
                                  (Nx, Ny)).copy()
        return {**_geometry_fields(zone_id, [(z.L_mm, z.t_mm) for z in self.zones],
                                   self.tpms_type, self.k_s), 'axis': axis}

    # ── Grid (2D) structured arrays ──────────────────────────────

    @staticmethod
    def build_grid_arrays(Nx, Ny, grid_cells,
                          tpms_type, k_s,
                          u_A, u_B, T_inA, T_inB, P_in=101325.0,
                          dx_arr=None, dy_arr=None, *, P_inB=None):
        """Build per-cell arrays from a list of 2D zone rectangles.

        Parameters
        ----------
        Nx, Ny      : grid cells
        grid_cells  : list of dict, each with keys:
                      y0, y1 (frac 0~1), x0, x1 (frac 0~1), L (mm), t (mm)
        tpms_type, k_s, u_A, u_B, T_inA, T_inB, P_in : physics params
        dx_arr, dy_arr : optional 1D arrays (m) of actual cell widths for
                         non-uniform grid. Length must equal Nx, Ny respectively.
                         If None, uniform spacing is assumed.

        Returns
        -------
        dict with 2D arrays (Nx, Ny).
        """
        from . import tpms_calc

        # Compute properties for each unique (L, t)
        P_inB = P_in if P_inB is None else P_inB
        props_cache = {}
        for gc in grid_cells:
            key = (gc['L'], gc['t'])
            if key not in props_cache:
                pA = tpms_calc.compute(tpms_type, gc['L'], gc['t'],
                                       u_A, T_inA, P_in, k_s)
                pB = tpms_calc.compute(tpms_type, gc['L'], gc['t'],
                                       u_B, T_inB, P_inB, k_s)
                props_cache[key] = (pA, pB)

        arrays = ZoneConfig.build_grid_geometry(
            Nx, Ny, grid_cells, tpms_type, k_s, dx_arr, dy_arr)
        zone_id = arrays['zone_id']
        for side, index in (('A', 0), ('B', 1)):
            properties = [props_cache[(cell['L'], cell['t'])][index] for cell in grid_cells]
            arrays['K_ff' + side + '_arr'] = np.asarray(
                [props['K_ff'] for props in properties], dtype=np.float64)[zone_id]
            arrays['h_v' + side + '_arr'] = np.asarray(
                [props['H_sf'] * props['A_0'] for props in properties], dtype=np.float64)[zone_id]
        return arrays

    @staticmethod
    def build_grid_geometry(Nx, Ny, grid_cells, tpms_type, k_s,
                            dx_arr=None, dy_arr=None):
        """Sample rectangle geometry with the normal builder's first-cell fallback."""
        # Cell-centre fractional positions for non-uniform grid support
        if dx_arr is not None:
            dx = np.asarray(dx_arr, dtype=np.float64)
            x_total = dx.sum()
            x_cum = np.concatenate([[0.0], np.cumsum(dx)])
            xf_centres = 0.5 * (x_cum[:-1] + x_cum[1:]) / x_total
        else:
            xf_centres = (np.arange(Nx) + 0.5) / Nx
        if dy_arr is not None:
            dy = np.asarray(dy_arr, dtype=np.float64)
            y_total = dy.sum()
            y_cum = np.concatenate([[0.0], np.cumsum(dy)])
            yf_centres = 0.5 * (y_cum[:-1] + y_cum[1:]) / y_total
        else:
            yf_centres = (np.arange(Ny) + 0.5) / Ny

        # Collect unique y and x boundaries for visualization
        y_bounds = set()
        x_bounds = set()
        for gc in grid_cells:
            y_bounds.update([gc['y0'], gc['y1']])
            x_bounds.update([gc['x0'], gc['x1']])

        zone_id = np.zeros((Nx, Ny), dtype=np.int32)
        for i in range(Nx):
            xf = float(xf_centres[i])
            for j in range(Ny):
                yf = float(yf_centres[j])
                # Find which grid cell this belongs to
                for gi, gc in enumerate(grid_cells):
                    if gc['x0'] <= xf < gc['x1'] and gc['y0'] <= yf < gc['y1']:
                        zone_id[i, j] = gi
                        break

        return {
            **_geometry_fields(zone_id, [(cell['L'], cell['t']) for cell in grid_cells],
                               tpms_type, k_s),
            'axis':      'grid',
            'y_bounds':  sorted(y_bounds - {0.0, 1.0}),
            'x_bounds':  sorted(x_bounds - {0.0, 1.0}),
            'grid_cells': grid_cells,
        }

    # ── Factory: uniform zone ──────────────────────────────────

    @staticmethod
    def single_zone(L_mm: float, t_mm: float,
                    tpms_type: str, k_s: float) -> 'ZoneConfig':
        """Create a single-zone config covering the entire domain."""
        return ZoneConfig(
            zones=[Zone('uniform', 0.0, 1.0, L_mm, t_mm)],
            tpms_type=tpms_type,
            k_s=k_s,
        )


# ===================================================================
#  Zone statistics and post-processing
# ===================================================================

def compute_zone_statistics(Ta, Tb, Ts, zone_id, zones,
                            u=None, v=None, P=None,
                            cell_area=None):
    """Compute per-zone statistics from solution fields.

    Parameters
    ----------
    Ta, Tb, Ts : arrays — temperature fields (1D or 2D)
    zone_id    : array — zone index per cell (same shape as Ta)
    zones      : list of Zone objects
    u, v       : velocity arrays (optional)
    P          : pressure array (optional)
    cell_area  : array (same shape as Ta) — per-cell area for weighted stats

    Returns
    -------
    list of dicts, one per zone.
    """
    Ta_flat = np.ravel(Ta)
    Tb_flat = np.ravel(Tb)
    Ts_flat = np.ravel(Ts)
    zid_flat = np.ravel(zone_id)
    w_flat = np.ravel(cell_area) if cell_area is not None else None

    def _wmean(arr, w):
        if w is not None:
            return float(np.average(arr, weights=w))
        return float(arr.mean())

    def _wstd(arr, w):
        if w is not None:
            m = np.average(arr, weights=w)
            return float(np.sqrt(np.average((arr - m)**2, weights=w)))
        return float(arr.std())

    stats = []
    for zi, z in enumerate(zones):
        mask = zid_flat == zi
        n = mask.sum()
        if n == 0:
            stats.append({'name': z.name, 'n_cells': 0})
            continue

        w = w_flat[mask] if w_flat is not None else None
        s = {
            'name':    z.name,
            'n_cells': int(n),
            'L_mm':    z.L_mm,
            't_mm':    z.t_mm,
            'Ta_mean': _wmean(Ta_flat[mask], w),
            'Ta_std':  _wstd(Ta_flat[mask], w),
            'Ta_min':  float(Ta_flat[mask].min()),
            'Ta_max':  float(Ta_flat[mask].max()),
            'Tb_mean': _wmean(Tb_flat[mask], w),
            'Tb_std':  _wstd(Tb_flat[mask], w),
            'Tb_min':  float(Tb_flat[mask].min()),
            'Tb_max':  float(Tb_flat[mask].max()),
            'Ts_mean': _wmean(Ts_flat[mask], w),
            'Ts_std':  _wstd(Ts_flat[mask], w),
        }

        if u is not None and v is not None:
            u_flat = np.ravel(u)
            v_flat = np.ravel(v)
            umag = np.sqrt(u_flat[mask]**2 + v_flat[mask]**2)
            s['u_mean']    = _wmean(u_flat[mask], w)
            s['v_mean']    = _wmean(v_flat[mask], w)
            s['umag_mean'] = _wmean(umag, w)
            s['umag_cv']   = float(_wstd(umag, w) / max(_wmean(umag, w), 1e-10))

        if P is not None:
            P_flat = np.ravel(P)
            s['P_mean']    = _wmean(P_flat[mask], w)
            s['P_min']     = float(P_flat[mask].min())
            s['P_max']     = float(P_flat[mask].max())
            s['P_spread']  = float(P_flat[mask].max() - P_flat[mask].min())

        stats.append(s)

    return stats


def format_zone_report(stats):
    """Format zone statistics into a readable string."""
    lines = []
    for s in stats:
        if s['n_cells'] == 0:
            lines.append(f"  {s['name']}: (empty)")
            continue
        lines.append(f"  {s['name']} (L={s['L_mm']}mm, t={s['t_mm']}mm, "
                     f"{s['n_cells']} cells):")
        lines.append(f"    Ta: {s['Ta_mean']:.1f} +/- {s['Ta_std']:.1f} K "
                     f"[{s['Ta_min']:.1f}, {s['Ta_max']:.1f}]")
        lines.append(f"    Tb: {s['Tb_mean']:.1f} +/- {s['Tb_std']:.1f} K "
                     f"[{s['Tb_min']:.1f}, {s['Tb_max']:.1f}]")
        lines.append(f"    Ts: {s['Ts_mean']:.1f} +/- {s['Ts_std']:.1f} K")
        if 'umag_mean' in s:
            lines.append(f"    |U|: {s['umag_mean']:.3f} m/s "
                         f"(CV={s['umag_cv']:.1%})")
        if 'P_spread' in s:
            lines.append(f"    P spread: {s['P_spread']:.1f} Pa")
    return '\n'.join(lines)
