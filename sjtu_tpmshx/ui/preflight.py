"""Grid-legality preflight.

Pure functions (no PySide6) so the rules are testable in isolation. The
UI wrapper in ``main.py`` passes captured compute inputs to
``compute_preflight`` and shows the findings in a QMessageBox.

Rules:
  * Use the physical grid constructors and the captured zone state.
    A failed grid construction is an ERROR. Keep independent port bounds
    checks, but do not report an effective grid or coverage after failure.
    A rejected 2D wall refinement is an ERROR even when preparation can
    use its existing uniform fallback.
  * Inlet/outlet must cover at least one cell (ERROR at 0, WARNING at 1-2)
    on the cross-axis. Pipe span outside the domain is a hard ERROR.
  * Stream-axis resolution < 20 cells → WARNING (SIMPLE may be
    under-resolved).
  * 2D Richardson doubles Nx × Ny → WARNING above 500 k cells (energy
    solve runtime becomes painful).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from sjtu_tpmshx.domain.validator import cross_axes_for_dir
from sjtu_tpmshx.models.grid import (
    build_grid_2d, build_port_wall_grid,
)

_STREAM_MIN_CELLS = 20
_PORT_MIN_CELLS = 3
_RICHARDSON_WARN_CELLS = 500_000


@dataclass
class FluidCfg:
    """Port values required by grid preflight."""
    dir: int
    in_ctr: float
    in_w: float
    out_ctr: float
    out_w: float
    z_in_ctr: Optional[float] = None
    z_in_w: Optional[float] = None
    z_out_ctr: Optional[float] = None
    z_out_w: Optional[float] = None


@dataclass
class Preflight:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors and not self.warnings


def _count_cells(edges, lo: float, hi: float, tol: float = 0.01) -> int:
    if edges is None or hi <= lo:
        return 0
    cells = 0
    for i in range(len(edges) - 1):
        e0, e1 = edges[i], edges[i + 1]
        overlap = max(0.0, min(e1, hi) - max(e0, lo))
        if overlap / (e1 - e0) > tol:
            cells += 1
    return cells


def _axis_extent(axis_name: str, L: float, H: float, Lz: float):
    return {'x': L, 'y': H, 'z': Lz}[axis_name]


def _stream_axis(d: int) -> str:
    return {0: 'x', 1: 'x', 2: 'y', 3: 'y', 4: 'z', 5: 'z'}[d]


def compute_preflight(
    L: float, H: float, Lz: float,
    Nx: int, Ny: int, Nz: int,
    is_3d: bool,
    fluid_A: Optional[FluidCfg] = None,
    fluid_B: Optional[FluidCfg] = None,
    T_inA: Optional[float] = None,
    T_inB: Optional[float] = None,
    port_wall_refine: bool = False,
    zone_axis: Optional[str] = None,
) -> Preflight:
    """Run the grid-legality checks. Returns findings; never raises."""
    out = Preflight()

    # Main duty uses the magnitude of the native side-A boundary enthalpy flow.
    if T_inA is not None and T_inB is not None and T_inA < T_inB - 1e-6:
        out.info.append(
            f"T_inA ({T_inA:.1f} K) < T_inB ({T_inB:.1f} K): B is the hot "
            f"side. Q is reported as the unsigned heat duty of fluid A.")

    ports = []
    for cfg in (fluid_A, fluid_B):
        if cfg is None:
            continue
        port = {key: getattr(cfg, key) for key in ('dir', 'in_ctr', 'in_w', 'out_ctr', 'out_w')}
        for end in ('in', 'out'):
            for key in ('ctr', 'w'):
                value = getattr(cfg, f'z_{end}_{key}')
                if value is not None:
                    port[f'{end}_z_{key}'] = value
        ports.append(port)

    grid_edges = {}
    refine_tag = 'uniform (no refine)'
    try:
        if not is_3d:
            dx, dy, x_breaks, y_breaks, refinement_error = build_grid_2d(
                L, H, Nx, Ny, ports, zone_axis=zone_axis, port_wall_refine=port_wall_refine)
            if refinement_error:
                raise ValueError(refinement_error)
            widths = (dx, dy)
            if (len(dx), len(dy)) != (Nx, Ny):
                refine_tag = 'wall-refined'
            elif x_breaks or y_breaks:
                refine_tag = 'port-aligned (no wall refine)'
        elif port_wall_refine:
            widths = build_port_wall_grid(
                (L, H, Lz), (Nx, Ny, Nz), ports)
        else:
            widths = tuple(np.full(n, span / n) for span, n in zip((L, H, Lz), (Nx, Ny, Nz)))
        grid_edges = {axis: np.r_[0., np.cumsum(w)] for axis, w in zip('xyz', widths)}
    except ValueError as error:
        out.errors.append(str(error))
    if port_wall_refine:
        refine_tag = "port/wall graded; counts include refinement"
    grid_available = bool(grid_edges)
    Nx_r, Ny_r, Nz_r = (len(grid_edges[axis]) - 1 if axis in grid_edges else 1 for axis in 'xyz')
    if grid_available and is_3d:
        out.info.append(
            f"Effective grid: {Nx_r} × {Ny_r} × {Nz_r} "
            f"= {Nx_r * Ny_r * Nz_r:,} cells ({refine_tag}).")
    elif grid_available:
        out.info.append(
            f"Effective grid: {Nx_r} × {Ny_r} "
            f"= {Nx_r * Ny_r:,} cells ({refine_tag}).")

    # Stream-axis resolution check + inlet/outlet cell coverage.
    for side, cfg in [('A', fluid_A), ('B', fluid_B)]:
        if cfg is None:
            continue
        d = cfg.dir
        stream = _stream_axis(d)
        cross_axes = [axis.lower() for axis in cross_axes_for_dir(d)]

        N_stream = {'x': Nx_r, 'y': Ny_r, 'z': Nz_r}[stream]
        if grid_available and N_stream < _STREAM_MIN_CELLS and not port_wall_refine:
            out.warnings.append(
                f"Fluid {side}: stream axis {stream} has only {N_stream} "
                f"cells (< {_STREAM_MIN_CELLS}). SIMPLE may be "
                f"under-resolved.")

        for cross_index, axis in enumerate(cross_axes[:2 if is_3d else 1]):
            span = _axis_extent(axis, L, H, Lz)
            for end, label in (('in', 'inlet'), ('out', 'outlet')):
                prefix = 'z_' if cross_index else ''
                ctr = getattr(cfg, f'{prefix}{end}_ctr')
                width = getattr(cfg, f'{prefix}{end}_w')
                # An unspecified second transverse span means the full face.
                if ctr is None and width is None:
                    ctr, width = span / 2, span
                elif ctr is None or width is None:
                    out.errors.append(
                        f"Fluid {side} {label} {axis} centre and width "
                        "must be set together.")
                    continue
                lo, hi = ctr - width / 2, ctr + width / 2
                if lo < -1e-9 or hi > span + 1e-9:
                    out.errors.append(
                        f"Fluid {side} {label} [{lo * 1e3:.2f}, "
                        f"{hi * 1e3:.2f}] mm exceeds {axis} domain "
                        f"[0, {span * 1e3:.2f}] mm.")
                elif grid_available:
                    cells = _count_cells(grid_edges[axis], lo, hi)
                    if cells == 0:
                        out.errors.append(
                            f"Fluid {side} {label} covers 0 cells on {axis} axis "
                            f"(width {width * 1e3:.2f} mm).")
                    elif cells < _PORT_MIN_CELLS:
                        out.warnings.append(
                            f"Fluid {side} {label} covers only {cells} cell(s) on "
                            f"{axis} axis (width {width * 1e3:.2f} mm). "
                            f"< {_PORT_MIN_CELLS} can blur the BC; widen the pipe "
                            f"or increase N{axis}.")
                    else:
                        out.info.append(
                            f"Fluid {side} {label} covers {cells} cells on {axis} axis.")

    # Richardson doubling — 2D only (3D code path skips Richardson).
    if grid_available and not is_3d:
        rich = (Nx_r * 2) * (Ny_r * 2)
        if rich > _RICHARDSON_WARN_CELLS:
            out.warnings.append(
                f"Richardson 2× grid would be {Nx_r * 2} × {Ny_r * 2} "
                f"= {rich:,} cells. Energy solve scales ~linearly, expect "
                f"long wait. Reduce Nx/Ny or skip Richardson post-hoc.")

    return out
