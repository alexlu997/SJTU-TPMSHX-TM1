"""Grid-legality preflight.

Pure functions (no PySide6) so the rules are testable in isolation. The
UI wrapper in ``main.py`` reads the line-edit state, hands it to
``compute_preflight``, and renders the returned findings in a QMessageBox.

Rules:
  * Wall-refine geometric series (n=8, first_cell=0.02 mm, growth=1.8) must
    fit inside every refined axis. Total refine width per pair of walls is
    ~5.46 mm — domain axes below that abort the refine branch inside the
    solver and fall back to uniform; we surface this as an ERROR so the
    user sees why the BL is unresolved.
  * Inlet/outlet must cover at least one cell (ERROR at 0, WARNING at 1-2)
    on the cross-axis. Pipe span outside the domain is a hard ERROR.
  * Stream-axis refined resolution < 20 cells → WARNING (SIMPLE may be
    under-resolved).
  * 2D Richardson doubles Nx × Ny → WARNING above 500 k cells (energy
    solve runtime becomes painful).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sjtu_tpmshx.domain.validator import cross_axes_for_dir


# Match df_projection.py / simple_solver.py defaults (2026-04-17).
_N_REFINE = 8
_FIRST_CELL = 0.02e-3
_GROWTH = 1.8
_REFINE_SIZES = [_FIRST_CELL * _GROWTH ** k for k in range(_N_REFINE)]
_REFINE_WIDTH = 2.0 * sum(_REFINE_SIZES)  # ≈ 5.46 mm

_STREAM_MIN_CELLS = 20
_PORT_MIN_CELLS = 3
_RICHARDSON_WARN_CELLS = 500_000


@dataclass
class FluidCfg:
    """Minimal pipe config — what the preflight needs from ``_fluid_config``."""
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

    def blocking(self) -> bool:
        return bool(self.errors)


def _refined_edges(W: float, N_bulk: int, refine: bool):
    """1D cell edges (len N+1) for a wall-refined or uniform axis."""
    if refine and W > _REFINE_WIDTH and N_bulk > 0:
        bulk_dx = (W - _REFINE_WIDTH) / N_bulk
        sizes = list(reversed(_REFINE_SIZES)) + [bulk_dx] * N_bulk + list(_REFINE_SIZES)
    else:
        if N_bulk <= 0:
            return None
        sizes = [W / N_bulk] * N_bulk
    edges = [0.0]
    acc = 0.0
    for s in sizes:
        acc += s
        edges.append(acc)
    return edges


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


def _refined_N(N_bulk: int, refine: bool) -> int:
    return N_bulk + 2 * _N_REFINE if refine else N_bulk


def _stream_axis(d: int) -> str:
    return {0: 'x', 1: 'x', 2: 'y', 3: 'y', 4: 'z', 5: 'z'}[d]


def compute_preflight(
    L: float, H: float, Lz: float,
    Nx: int, Ny: int, Nz: int,
    is_3d: bool,
    wall_refine_3d: bool,
    fluid_A: Optional[FluidCfg] = None,
    fluid_B: Optional[FluidCfg] = None,
    T_inA: Optional[float] = None,
    T_inB: Optional[float] = None,
    port_wall_refine: bool = False,
) -> Preflight:
    """Run the grid-legality checks. Returns findings; never raises."""
    out = Preflight()

    # Main duty uses the magnitude of the native side-A boundary enthalpy flow.
    if T_inA is not None and T_inB is not None and T_inA < T_inB - 1e-6:
        out.info.append(
            f"T_inA ({T_inA:.1f} K) < T_inB ({T_inB:.1f} K): B is the hot "
            f"side. Q is reported as the unsigned heat duty of fluid A.")

    # 2D wall refine only kicks in when BOTH fluid inlets/outlets are full
    # width along their cross-axis. Otherwise the 2D grid preparation falls back
    # to _aligned_grid (uniform with zone breakpoints).
    def _is_full(cfg: Optional[FluidCfg], span: float) -> bool:
        if cfg is None:
            return True
        return abs(cfg.in_w - span) < span * 0.01 and abs(cfg.out_w - span) < span * 0.01

    if port_wall_refine:
        apply_refine = False  # supplied counts already include graded cells
    elif is_3d:
        apply_refine = wall_refine_3d
    else:
        # Cross-axis span depends on each fluid's direction — approximate by
        # insisting both A and B see a full-width span on their respective
        # cross-axis. If either partial, 2D falls back to uniform grid.
        full_A = True
        full_B = True
        if fluid_A is not None:
            c1A = cross_axes_for_dir(fluid_A.dir)[0].lower()
            full_A = _is_full(fluid_A, _axis_extent(c1A, L, H, Lz))
        if fluid_B is not None:
            c1B = cross_axes_for_dir(fluid_B.dir)[0].lower()
            full_B = _is_full(fluid_B, _axis_extent(c1B, L, H, Lz))
        apply_refine = full_A and full_B

    # Wall-refine must fit on every axis we intend to refine.
    refine_axes = []
    if apply_refine:
        refine_axes = [('L', L), ('H', H)]
        if is_3d:
            refine_axes.append(('Lz', Lz))
    for name, val in refine_axes:
        if val <= _REFINE_WIDTH:
            out.errors.append(
                f"{name} = {val * 1e3:.2f} mm too small for wall refinement "
                f"(needs > {_REFINE_WIDTH * 1e3:.2f} mm for 8 BL cells per "
                f"wall). Choose a compatible mesh scheme or review the "
                f"domain dimensions.")

    # Refined per-axis cell counts the solver will actually run on.
    Nx_r = _refined_N(Nx, apply_refine)
    Ny_r = _refined_N(Ny, apply_refine)
    Nz_r = _refined_N(Nz, apply_refine) if is_3d else 1

    refine_tag = "wall-refined" if apply_refine else "uniform (no refine)"
    port_edges = {}
    if port_wall_refine:
        import numpy as np
        from sjtu_tpmshx.models.grid import build_port_wall_grid
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
        try:
            widths = build_port_wall_grid(
                (L, H, Lz) if is_3d else (L, H),
                (Nx, Ny, Nz) if is_3d else (Nx, Ny), ports)
            port_edges = {axis: np.r_[0., np.cumsum(w)] for axis, w in zip('xyz', widths)}
        except ValueError as error:
            out.errors.append(str(error))
        refine_tag = "port/wall graded; counts include refinement"
    grid_available = not port_wall_refine or bool(port_edges)
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
        if N_stream < _STREAM_MIN_CELLS and not port_wall_refine:
            out.warnings.append(
                f"Fluid {side}: stream axis {stream} has only {N_stream} "
                f"refined cells (< {_STREAM_MIN_CELLS}). SIMPLE may be "
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
                    # No coverage claims when the requested graded grid failed.
                    n_bulk = {'x': Nx, 'y': Ny, 'z': Nz}[axis]
                    edges = (port_edges[axis] if axis in port_edges else
                             _refined_edges(span, n_bulk, apply_refine))
                    cells = _count_cells(edges, lo, hi)
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
    if not is_3d:
        rich = (Nx_r * 2) * (Ny_r * 2)
        if rich > _RICHARDSON_WARN_CELLS:
            out.warnings.append(
                f"Richardson 2× grid would be {Nx_r * 2} × {Ny_r * 2} "
                f"= {rich:,} cells. Energy solve scales ~linearly, expect "
                f"long wait. Reduce Nx/Ny or skip Richardson post-hoc.")

    return out
