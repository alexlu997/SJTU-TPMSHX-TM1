"""
zone_config.py — Zone-based domain partitioning for SJTU-TPMSHX

DEPRECATED FOR OPTIMIZER USE
============================
The optimizer (`optimization/optimizer_qnehvi.py` + `evaluator.py`) now
uses `solvers.continuous_field.ContinuousFieldConfig` (4×4 + Y-mirror = 16-D
bicubic B-spline) for continuous-field optimization, which superseded
the old patch-zoning NSGA-II workflow (2026-05-08 rewrite).

This module is RETAINED ONLY for the UI Compute path's "Define zones"
tab (`pipelines/stages_2d.py` consumes the ZoneInputConfig snapshot that
`ui/window_config.py` builds from window._zone_grid / the zone table).
New optimization code MUST NOT import ZoneConfig — use
ContinuousFieldConfig instead.

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
                           P_in: float = 101325.0):
        """Compute TPMS properties for each zone using tpms_calc.compute()."""
        self.validate()
        for z in self.zones:
            z.props_A = tpms_calc.compute(
                self.tpms_type, z.L_mm, z.t_mm, u_A, T_inA, P_in, self.k_s)
            z.props_B = tpms_calc.compute(
                self.tpms_type, z.L_mm, z.t_mm, u_B, T_inB, P_in, self.k_s)

    # ── Structured grid arrays ──────────────────────────────────

    def build_structured_arrays(self, Nx: int, Ny: int, H: float,
                                axis: str = 'y') -> dict:
        """Build 2D per-cell property arrays for structured rectangular grid.

        Parameters
        ----------
        Nx, Ny : grid cells in x and y
        H      : domain size along partition axis [m]
        axis   : 'y' or 'x' — which axis zones are defined along

        Returns
        -------
        dict with 2D arrays (Nx, Ny) + 'axis' key.
        """
        if not self.zones or not self.zones[0].props_A:
            raise RuntimeError("Call compute_properties() before building arrays.")

        N_ax = Ny if axis == 'y' else Nx
        d_ax = H / N_ax
        fc = np.array([(k + 0.5) * d_ax / H for k in range(N_ax)])

        zone_id_1d = np.zeros(N_ax, dtype=np.int32)
        for k in range(N_ax):
            for zi, z in enumerate(self.zones):
                if z.y_frac_start <= fc[k] < z.y_frac_end:
                    zone_id_1d[k] = zi
                    break
            else:
                zone_id_1d[k] = len(self.zones) - 1

        zone_id   = np.empty((Nx, Ny), dtype=np.int32)
        eps_arr   = np.empty((Nx, Ny), dtype=np.float64)
        eps_f_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffA_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffB_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ss_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vA_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vB_arr  = np.empty((Nx, Ny), dtype=np.float64)
        r_h_arr   = np.empty((Nx, Ny), dtype=np.float64)
        A_0_arr   = np.empty((Nx, Ny), dtype=np.float64)

        for k in range(N_ax):
            z = self.zones[zone_id_1d[k]]
            pA, pB = z.props_A, z.props_B
            eps = pA['epsilon']
            v = (zone_id_1d[k], eps, pA['epsilon_A'], pA['K_ff'], pB['K_ff'],
                 pA['K_ss'], pA['H_sf']*pA['A_0'], pB['H_sf']*pB['A_0'],
                 pA['D_h']/2.0, pA['A_0'])
            arrs = (zone_id, eps_arr, eps_f_arr, K_ffA_arr, K_ffB_arr,
                    K_ss_arr, h_vA_arr, h_vB_arr, r_h_arr, A_0_arr)
            for arr, val in zip(arrs, v):
                if axis == 'y':
                    arr[:, k] = val
                else:
                    arr[k, :] = val

        from .grid_schema import validate_grid_arrays
        return validate_grid_arrays({
            'zone_id':   zone_id,
            'eps_arr':   eps_arr,
            'eps_f_arr': eps_f_arr,
            'K_ffA_arr': K_ffA_arr,
            'K_ffB_arr': K_ffB_arr,
            'K_ss_arr':  K_ss_arr,
            'h_vA_arr':  h_vA_arr,
            'h_vB_arr':  h_vB_arr,
            'r_h_arr':   r_h_arr,
            'A_0_arr':   A_0_arr,
            'axis': axis,
            'zone_params': [
                {
                    'name': z.name,
                    'y_frac_start': z.y_frac_start,
                    'y_frac_end': z.y_frac_end,
                    'L_mm': z.L_mm, 't_mm': z.t_mm,
                    'epsilon': z.props_A['epsilon'],
                    'D_h': z.props_A['D_h'],
                    'r_h': z.props_A['D_h'] / 2.0,
                    'A_0': z.props_A['A_0'],
                    'mu': z.props_A['mu'],
                    'rho': z.props_A['rho'],
                }
                for z in self.zones
            ],
        }, Nx, Ny, where='ZoneConfig.build_structured_arrays')

    # ── Grid (2D) structured arrays ──────────────────────────────

    @staticmethod
    def build_grid_arrays(Nx, Ny, L, H, grid_cells,
                          tpms_type, k_s,
                          u_A, u_B, T_inA, T_inB, P_in=101325.0,
                          dx_arr=None, dy_arr=None):
        """Build per-cell arrays from a list of 2D zone rectangles.

        Parameters
        ----------
        Nx, Ny      : grid cells
        L, H        : domain size [m]
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
        props_cache = {}
        for gc in grid_cells:
            key = (gc['L'], gc['t'])
            if key not in props_cache:
                pA = tpms_calc.compute(tpms_type, gc['L'], gc['t'],
                                       u_A, T_inA, P_in, k_s)
                pB = tpms_calc.compute(tpms_type, gc['L'], gc['t'],
                                       u_B, T_inB, P_in, k_s)
                props_cache[key] = (pA, pB)

        zone_id   = np.full((Nx, Ny), -1, dtype=np.int32)
        eps_arr   = np.empty((Nx, Ny), dtype=np.float64)
        eps_f_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffA_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffB_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ss_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vA_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vB_arr  = np.empty((Nx, Ny), dtype=np.float64)
        r_h_arr   = np.empty((Nx, Ny), dtype=np.float64)
        A_0_arr   = np.empty((Nx, Ny), dtype=np.float64)

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

        for i in range(Nx):
            xf = float(xf_centres[i])
            for j in range(Ny):
                yf = float(yf_centres[j])
                # Find which grid cell this belongs to
                for gi, gc in enumerate(grid_cells):
                    if gc['x0'] <= xf < gc['x1'] and gc['y0'] <= yf < gc['y1']:
                        zone_id[i, j] = gi
                        pA, pB = props_cache[(gc['L'], gc['t'])]
                        eps = pA['epsilon']
                        eps_arr[i, j]   = eps
                        K_ffA_arr[i, j] = pA['K_ff']
                        K_ffB_arr[i, j] = pB['K_ff']
                        K_ss_arr[i, j]  = pA['K_ss']
                        h_vA_arr[i, j]  = pA['H_sf'] * pA['A_0']
                        h_vB_arr[i, j]  = pB['H_sf'] * pB['A_0']
                        eps_f_arr[i, j] = pA['epsilon_A']
                        r_h_arr[i, j]   = pA['D_h'] / 2.0
                        A_0_arr[i, j]   = pA['A_0']
                        break
                else:
                    # Cell not covered: use first grid cell as fallback
                    gc0 = grid_cells[0]
                    zone_id[i, j] = 0
                    pA, pB = props_cache[(gc0['L'], gc0['t'])]
                    eps = pA['epsilon']
                    eps_arr[i, j]   = eps
                    K_ffA_arr[i, j] = pA['K_ff']
                    K_ffB_arr[i, j] = pB['K_ff']
                    K_ss_arr[i, j]  = pA['K_ss']
                    h_vA_arr[i, j]  = pA['H_sf'] * pA['A_0']
                    h_vB_arr[i, j]  = pB['H_sf'] * pB['A_0']
                    eps_f_arr[i, j] = pA['epsilon_A']
                    r_h_arr[i, j]   = pA['D_h'] / 2.0
                    A_0_arr[i, j]   = pA['A_0']

        return {
            'zone_id':   zone_id,
            'eps_arr':   eps_arr,
            'eps_f_arr': eps_f_arr,
            'K_ffA_arr': K_ffA_arr,
            'K_ffB_arr': K_ffB_arr,
            'K_ss_arr':  K_ss_arr,
            'h_vA_arr':  h_vA_arr,
            'h_vB_arr':  h_vB_arr,
            'r_h_arr':   r_h_arr,
            'A_0_arr':   A_0_arr,
            'axis':      'grid',
            'y_bounds':  sorted(y_bounds - {0.0, 1.0}),
            'x_bounds':  sorted(x_bounds - {0.0, 1.0}),
            'grid_cells': grid_cells,
        }

    # ── Unstructured mesh arrays ────────────────────────────────

    def build_unstructured_arrays(self, cell_centers_y: np.ndarray,
                                  n_cells: int, H: float) -> dict:
        """Build 1D per-cell property arrays for unstructured FVM mesh.

        Parameters
        ----------
        cell_centers_y : 1D array of cell centre y-coordinates [m]
        n_cells : number of cells
        H : domain height [m]

        Returns
        -------
        dict with 1D arrays [n_cells]: same keys as structured version.
        """
        if not self.zones or not self.zones[0].props_A:
            raise RuntimeError("Call compute_properties() before building arrays.")

        yc_frac = cell_centers_y / H

        zone_id   = np.zeros(n_cells, dtype=np.int32)
        eps_arr   = np.empty(n_cells, dtype=np.float64)
        eps_f_arr = np.empty(n_cells, dtype=np.float64)
        K_ffA_arr = np.empty(n_cells, dtype=np.float64)
        K_ffB_arr = np.empty(n_cells, dtype=np.float64)
        K_ss_arr  = np.empty(n_cells, dtype=np.float64)
        h_vA_arr  = np.empty(n_cells, dtype=np.float64)
        h_vB_arr  = np.empty(n_cells, dtype=np.float64)
        r_h_arr   = np.empty(n_cells, dtype=np.float64)
        A_0_arr   = np.empty(n_cells, dtype=np.float64)

        for ci in range(n_cells):
            yf = yc_frac[ci]
            zi = len(self.zones) - 1
            for k, z in enumerate(self.zones):
                if z.y_frac_start <= yf < z.y_frac_end:
                    zi = k
                    break

            zone_id[ci] = zi
            z = self.zones[zi]
            pA, pB = z.props_A, z.props_B
            eps = pA['epsilon']

            eps_arr[ci]   = eps
            eps_f_arr[ci] = pA['epsilon_A']
            K_ffA_arr[ci] = pA['K_ff']
            K_ffB_arr[ci] = pB['K_ff']
            K_ss_arr[ci]  = pA['K_ss']
            h_vA_arr[ci]  = pA['H_sf'] * pA['A_0']
            h_vB_arr[ci]  = pB['H_sf'] * pB['A_0']
            r_h_arr[ci]   = pA['D_h'] / 2.0
            A_0_arr[ci]   = pA['A_0']

        return {
            'zone_id':   zone_id,
            'eps_arr':   eps_arr,
            'eps_f_arr': eps_f_arr,
            'K_ffA_arr': K_ffA_arr,
            'K_ffB_arr': K_ffB_arr,
            'K_ss_arr':  K_ss_arr,
            'h_vA_arr':  h_vA_arr,
            'h_vB_arr':  h_vB_arr,
            'r_h_arr':   r_h_arr,
            'A_0_arr':   A_0_arr,
            'zone_params': [
                {
                    'name': z.name,
                    'y_frac_start': z.y_frac_start,
                    'y_frac_end': z.y_frac_end,
                    'L_mm': z.L_mm, 't_mm': z.t_mm,
                    'epsilon': z.props_A['epsilon'],
                    'D_h': z.props_A['D_h'],
                    'r_h': z.props_A['D_h'] / 2.0,
                    'A_0': z.props_A['A_0'],
                    'mu': z.props_A['mu'],
                    'rho': z.props_A['rho'],
                }
                for z in self.zones
            ],
        }

    # ── Factory: single-zone (backward compatible) ──────────────

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


# ── Standalone test ─────────────────────────────────────────────

if __name__ == '__main__':
    print("=== ZoneConfig standalone test ===\n")

    # Test 1: single zone
    zc1 = ZoneConfig.single_zone(6.0, 0.3, 'Diamond', 15.0)
    zc1.compute_properties(u_A=5.0, u_B=3.0, T_inA=400, T_inB=300)
    a1 = zc1.build_structured_arrays(Nx=10, Ny=20, H=0.1)
    print(f"Single zone: eps = {a1['eps_arr'][0,0]:.4f}, "
          f"K_ffA = {a1['K_ffA_arr'][0,0]:.6f}, "
          f"h_vA = {a1['h_vA_arr'][0,0]:.1f}")
    assert np.all(a1['zone_id'] == 0), "Single zone: all zone_id should be 0"
    assert np.allclose(a1['eps_arr'], a1['eps_arr'][0, 0]), "Single zone: eps should be uniform"
    print("  PASS: single zone uniform\n")

    # Test 2: 3-zone config
    zc3 = ZoneConfig(
        zones=[
            Zone('inlet',  0.0, 0.2, L_mm=4.0, t_mm=0.4),
            Zone('middle', 0.2, 0.8, L_mm=6.0, t_mm=0.3),
            Zone('outlet', 0.8, 1.0, L_mm=4.0, t_mm=0.4),
        ],
        tpms_type='Diamond', k_s=15.0,
    )
    zc3.compute_properties(u_A=5.0, u_B=3.0, T_inA=400, T_inB=300)
    a3 = zc3.build_structured_arrays(Nx=10, Ny=100, H=0.1)

    # Check zone assignment
    n_zone0 = np.sum(a3['zone_id'][0, :] == 0)
    n_zone1 = np.sum(a3['zone_id'][0, :] == 1)
    n_zone2 = np.sum(a3['zone_id'][0, :] == 2)
    print(f"3-zone: cells per zone = [{n_zone0}, {n_zone1}, {n_zone2}]")
    assert n_zone0 == 20 and n_zone1 == 60 and n_zone2 == 20, "Zone counts wrong"

    # Check different properties per zone
    eps_inlet  = a3['eps_arr'][0, 5]
    eps_middle = a3['eps_arr'][0, 50]
    print(f"  eps(inlet zone) = {eps_inlet:.4f}")
    print(f"  eps(middle zone) = {eps_middle:.4f}")
    assert eps_inlet != eps_middle, "Different zones should have different eps"
    print("  PASS: 3-zone property variation\n")

    # Test 3: unstructured arrays
    cell_y = np.linspace(0.005, 0.095, 50)  # 50 cells over H=0.1
    a3u = zc3.build_unstructured_arrays(cell_y, 50, H=0.1)
    print(f"Unstructured: zone_id range = [{a3u['zone_id'].min()}, {a3u['zone_id'].max()}]")
    assert a3u['zone_id'].min() == 0 and a3u['zone_id'].max() == 2
    print("  PASS: unstructured arrays\n")

    # Test 4: validation errors
    try:
        bad = ZoneConfig(
            zones=[Zone('a', 0.0, 0.5, 6.0, 0.3), Zone('b', 0.6, 1.0, 6.0, 0.3)],
            tpms_type='Diamond', k_s=15.0
        )
        bad.validate()
        print("  FAIL: should have caught gap")
    except ValueError as e:
        print(f"  PASS: caught gap error: {e}\n")

    print("=== All tests passed ===")
