"""Pure-function domain validation + helpers for TPMS HX.

Phase 4 of 2026-05-06 main.py refactor (audit fix #4). See
``domain/__init__.py`` for the rationale and high-level surface.

Every function here is **Qt-free**: takes scalars / dicts, returns
scalars / dicts / list of :class:`Warning`. No widget access, no
side effects. This is what ``Main_Menu`` calls *after* it has
collected the user's text from ``QLineEdit.text()``.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple

from sjtu_tpmshx.df_surrogate._domain import TRAIN_L_NODES, TRAIN_T_NODES


# ---------------------------------------------------------------- types


@dataclass
class Warning:
    """One domain warning. Severity is informational only — the GUI
    decides how to render it (status bar flash vs modal vs red border).

    ``code`` is a short identifier (e.g. ``'t_over_L_extrapolation'``)
    for programmatic filtering / unit testing without string matching.
    """
    code: str
    message: str
    severity: str = 'warn'   # 'info' | 'warn' | 'error'

    def __str__(self) -> str:   # pragma: no cover (cosmetic)
        return f'[{self.severity}] {self.code}: {self.message}'


# ---------------------------------------------------------------- grid suggestion


def suggest_grid_3d(L_dom: float, H_dom: float, Lz_dom: float,
                    D_h: float, max_cells: int = 50_000, *,
                    port_wall_refine: bool = False, ports=()) -> Tuple[int, int, int]:
    """Suggest total cell counts for the selected desktop mesh scheme.

    Hydraulic-diameter spacing is a starting heuristic, not an accuracy
    guarantee. Port/wall counts already include all refinement layers; their
    minimum comes from the same port segmentation as the grid builder.
    The budget applies to Nx * Ny * Nz, without a retired six-wall padding.
    """
    lengths = (L_dom, H_dom, Lz_dom)
    for name, v in zip(('L_dom', 'H_dom', 'Lz_dom', 'D_h'), (*lengths, D_h)):
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f'{name} must be finite and > 0, got {v}')
    minimum = (14, 8, 3)
    if port_wall_refine:
        from sjtu_tpmshx.models.grid import port_wall_min_counts
        minimum = tuple(max(base, needed) for base, needed in
                        zip(minimum, port_wall_min_counts(lengths, ports)))
    if max_cells < math.prod(minimum):
        raise ValueError(f'Grid budget {max_cells} is below the required minimum '
                         f'{minimum} ({math.prod(minimum)} cells)')
    counts = [max(floor, round(length / (spacing * D_h)))
              for floor, length, spacing in zip(minimum, lengths, (1., .5, .5))]
    while math.prod(counts) > max_cells:
        axis = max(range(3), key=lambda i: counts[i] / minimum[i])
        counts[axis] = max(minimum[axis], int(counts[axis] * .8))
    return tuple(counts)


# ---------------------------------------------------------------- geometry


def validate_geometry(L_dom: float, H_dom: float, Lz_dom: Optional[float],
                      L_cell_mm: float, t_mm: float,
                      ks: float = 16.0,
                      is_3d: bool = False) -> List[Warning]:
    """Sanity-check the geometric inputs. Returns a (possibly empty)
    list of warnings; raises ``ValueError`` only on hard nonsense
    (e.g. zero cell size).

    Hard rules (raise):
      * ``L_dom``, ``H_dom``, ``L_cell_mm``, ``t_mm``, ``ks`` all > 0
      * 3D mode requires ``Lz_dom > 0``

    Soft rules (warn):
      * ``(L_cell_mm, t_mm)`` outside the current fixed geometry/D-F grid.
        Nu and experimental-calibration applicability remain separate checks.
      * ``L_cell_mm > min(L_dom, H_dom) * 1000`` — cell larger than a
        domain dimension means single-cell HX, results untrustworthy.
    """
    for name, v in (('L_dom', L_dom), ('H_dom', H_dom),
                    ('L_cell_mm', L_cell_mm), ('t_mm', t_mm),
                    ('ks', ks)):
        if v is None or v <= 0:
            raise ValueError(f'{name} must be > 0, got {v}')
    if is_3d:
        if Lz_dom is None or Lz_dom <= 0:
            raise ValueError(
                f'3D mode requires Lz_dom > 0, got {Lz_dom}')

    out: List[Warning] = []
    geometry_warning = geometry_extrapolation_warning(L_cell_mm, t_mm)
    if geometry_warning is not None:
        out.append(geometry_warning)

    L_min_mm = min(L_dom, H_dom) * 1000.0
    if is_3d and Lz_dom is not None:
        L_min_mm = min(L_min_mm, Lz_dom * 1000.0)
    if L_cell_mm > L_min_mm:
        out.append(Warning(
            'cell_larger_than_domain',
            f'TPMS cell {L_cell_mm} mm exceeds smallest domain '
            f'extent {L_min_mm:.1f} mm — domain holds < 1 cell, '
            f'closures invalid.',
            severity='error'))

    return out


def geometry_extrapolation_warning(L_cell_mm: float,
                                    t_mm: float) -> Optional[Warning]:
    """Check the fixed geometry/D-F grid, including interpolated points.

    This is not the applicability envelope of a Nu correlation or an
    experimental correction; those are checked by their selected models.

    Lighter-weight than full ``validate_geometry`` — used by the live
    UI to flash an inline tip without recomputing every check.
    """
    L_train = TRAIN_L_NODES
    t_train = TRAIN_T_NODES
    in_L = L_train[0] <= L_cell_mm <= L_train[-1]
    in_t = t_train[0] <= t_mm <= t_train[-1]
    if in_L and in_t:
        return None
    return Warning(
        'geometry_extrapolation',
        f'Fixed geometry/D-F: (L={L_cell_mm}, t={t_mm}) outside CFD grid '
        f'[{L_train[0]}, {L_train[-1]}] × [{t_train[0]}, {t_train[-1]}] mm. '
        'Nu correlations and experimental corrections have separate applicability limits.')


# ---------------------------------------------------------------- physics


def compute_volumetric_htc(A_0: float, H_sf: float) -> float:
    """Convert face HTC [W/(m²·K)] to volumetric HTC [W/(m³·K)].

    ``h_v = A_0 * H_sf`` where ``A_0`` is the specific surface area
    [m²/m³] from the TPMS geometry.
    """
    if A_0 < 0 or H_sf < 0:
        raise ValueError(f'A_0={A_0}, H_sf={H_sf} must both be >= 0')
    return float(A_0) * float(H_sf)


# ---------------------------------------------------------------- direction maps


_INLET_WALL = {0: 'left', 1: 'right',
               2: 'bottom', 3: 'top',
               4: 'front', 5: 'back'}
_OUTLET_WALL = {0: 'right', 1: 'left',
                2: 'top', 3: 'bottom',
                4: 'back', 5: 'front'}
_CROSS_AXES = {
    0: ('Y', 'Z'), 1: ('Y', 'Z'),
    2: ('X', 'Z'), 3: ('X', 'Z'),
    4: ('X', 'Y'), 5: ('X', 'Y'),
}


def wall_for_dir(d: int, role: str = 'inlet') -> str:
    """Map flow-axis index ``d`` (0..5) and role to wall name.

    ``d``: 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z
    ``role``: ``'inlet'`` or ``'outlet'``
    """
    if d not in _INLET_WALL:
        raise ValueError(f'unknown direction {d}, expected 0-5')
    if role == 'inlet':
        return _INLET_WALL[d]
    if role == 'outlet':
        return _OUTLET_WALL[d]
    raise ValueError(f"role must be 'inlet' or 'outlet', got {role!r}")


def cross_axes_for_dir(d: int) -> Tuple[str, str]:
    """Return (cross1, cross2) axis labels for flow-axis index ``d``.

    The UI's ``in_ctr/in_w`` always controls ``cross1`` (e.g. Y for
    x-flow); ``in_z_ctr`` always controls ``cross2`` (e.g. Z for x-flow).
    """
    if d not in _CROSS_AXES:
        raise ValueError(f'unknown direction {d}, expected 0-5')
    return _CROSS_AXES[d]


# ---------------------------------------------------------------- pipe config


def validate_pipe_config(cfg: Dict[str, object],
                         L_dom: float, H_dom: float,
                         Lz_dom: Optional[float] = None,
                         is_3d: bool = False) -> List[Warning]:
    """Sanity-check a pipe BC dict (output of ``Main_Menu._fluid_config``).

    cfg keys: ``dir`` (0-5), ``in_ctr``, ``in_w``, ``out_ctr``, ``out_w``,
    optional ``in_z_ctr``, ``in_z_w``, ``out_z_ctr``, ``out_z_w``.

    Checks:
      * inlet/outlet centre ± width/2 stays inside the cross-axis range
      * width > 0
      * optional second-cross-axis fields are complete and in range in 3D
      * 2D accepts only x/y directions; 3D also accepts z directions
    """
    out: List[Warning] = []
    try:
        d = int(cfg.get('dir', 0))
    except (TypeError, ValueError, OverflowError):
        out.append(Warning(
            'pipe_bad_dir',
            f"pipe direction {cfg.get('dir')!r} is not an integer",
            severity='error'))
        return out
    if d not in _CROSS_AXES:
        out.append(Warning(
            'pipe_bad_dir',
            f'pipe direction {d} not in 0..5', severity='error'))
        return out
    if not is_3d and d in (4, 5):
        out.append(Warning(
            'pipe_bad_dir',
            f'2D pipe direction {d} must be in 0..3', severity='error'))
        return out

    # Cross axis 1 length depends on flow axis
    cross1_len = {0: H_dom, 1: H_dom,
                  2: L_dom, 3: L_dom,
                  4: L_dom, 5: L_dom}[d]
    cross2_len = (Lz_dom if (is_3d and Lz_dom is not None)
                  else None)
    if d in (4, 5):
        cross2_len = H_dom

    for io in ('in', 'out'):
        try:
            ctr = float(cfg.get(f'{io}_ctr', 0.0))
            w = float(cfg.get(f'{io}_w', 0.0))
        except (TypeError, ValueError):
            out.append(Warning(
                f'pipe_{io}_invalid',
                f'{io} centre and width must be finite numbers',
                severity='error'))
            continue
        if not math.isfinite(ctr) or not math.isfinite(w):
            out.append(Warning(
                f'pipe_{io}_invalid',
                f'{io} centre and width must be finite numbers',
                severity='error'))
            continue
        if w <= 0:
            out.append(Warning(
                f'pipe_{io}_w_nonpos',
                f'{io}_w = {w} must be > 0',
                severity='error'))
            continue
        if ctr - w / 2 < 0 or ctr + w / 2 > cross1_len:
            out.append(Warning(
                f'pipe_{io}_out_of_domain',
                f'{io}_ctr ± {io}_w/2 = '
                f'[{ctr - w/2:.3g}, {ctr + w/2:.3g}] m '
                f'leaves the cross-axis range [0, {cross1_len:.3g}].',
                severity='error'))

    cross2_fields = tuple(
        cfg.get(name) for name in
        ('in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'))
    if not is_3d and any(value is not None for value in cross2_fields):
        out.append(Warning(
            'pipe_cross2_in_2d',
            'second-cross-axis port fields are only valid in 3D',
            severity='error'))
    if is_3d and cross2_len is not None:
        cross2_name = _CROSS_AXES[d][1]
        for io in ('in', 'out'):
            zc = cfg.get(f'{io}_z_ctr')
            zw = cfg.get(f'{io}_z_w')
            if zc is None and zw is None:
                continue   # omitted pair means full face on cross2
            if zc is None or zw is None:
                out.append(Warning(
                    f'pipe_{io}_z_incomplete',
                    f'{io} second-cross-axis centre and width must be set together',
                    severity='error'))
                continue
            try:
                zc, zw = float(zc), float(zw)
            except (TypeError, ValueError):
                out.append(Warning(
                    f'pipe_{io}_z_invalid',
                    f'{io} second-cross-axis centre and width must be finite numbers',
                    severity='error'))
                continue
            if not math.isfinite(zc) or not math.isfinite(zw):
                out.append(Warning(
                    f'pipe_{io}_z_invalid',
                    f'{io} second-cross-axis centre and width must be finite numbers',
                    severity='error'))
                continue
            if zw <= 0:
                out.append(Warning(
                    f'pipe_{io}_z_w_nonpos',
                    f'{io}_z_w = {zw} must be > 0',
                    severity='error'))
                continue
            if zc - zw / 2 < 0 or zc + zw / 2 > cross2_len:
                out.append(Warning(
                    f'pipe_{io}_z_out_of_domain',
                    f'{io}_z_ctr ± {io}_z_w/2 = '
                    f'[{zc - zw/2:.3g}, {zc + zw/2:.3g}] m '
                    f'leaves {cross2_name}-range [0, {cross2_len:.3g}].',
                    severity='error'))
    return out


# ---------------------------------------------------------------- unit parser


_UNIT_LENGTH = {
    'm': 1.0, 'cm': 1e-2, 'mm': 1e-3, 'μm': 1e-6, 'um': 1e-6,
    'in': 0.0254, 'inch': 0.0254, 'ft': 0.3048,
}
_UNIT_PRESSURE = {
    'pa': 1.0, 'kpa': 1e3, 'mpa': 1e6, 'bar': 1e5, 'mbar': 1e2,
    'psi': 6894.757, 'atm': 101325.0, 'torr': 133.322, 'mmhg': 133.322,
}
_UNIT_SPEED = {
    'm/s': 1.0, 'cm/s': 1e-2, 'mm/s': 1e-3,
    'km/h': 1.0 / 3.6, 'kph': 1.0 / 3.6,
    'mph': 0.44704, 'ft/s': 0.3048,
}


def parse_unit_value(value: float, unit_text: str,
                     family: str, target_unit: Optional[str] = None,
                     temp_unit: str = 'K') -> Optional[float]:
    """Convert ``value [unit_text]`` to ``target_unit`` for ``family``.

    family ∈ {'length', 'pressure', 'speed', 'temp'}.
    Returns the converted scalar in ``target_unit``, or ``None`` if the
    unit token is unrecognised for the family.

    Temperature handling honours the GUI's current display toggle
    (``temp_unit``): if ``temp_unit='K'`` the return is Kelvin even if
    the user typed 25 °C. ``target_unit`` is ignored for temp.
    """
    u = unit_text.strip().lower().replace('·', '')
    if family == 'length':
        if u not in _UNIT_LENGTH:
            return None
        si = value * _UNIT_LENGTH[u]
        return si / _UNIT_LENGTH.get((target_unit or 'm').lower(), 1.0)
    if family == 'pressure':
        if u not in _UNIT_PRESSURE:
            return None
        si = value * _UNIT_PRESSURE[u]
        return si / _UNIT_PRESSURE.get((target_unit or 'pa').lower(), 1.0)
    if family == 'speed':
        if u not in _UNIT_SPEED:
            return None
        si = value * _UNIT_SPEED[u]
        return si / _UNIT_SPEED.get((target_unit or 'm/s').lower(), 1.0)
    if family == 'temp':
        want_K = (temp_unit == 'K')
        if u in ('k', 'kelvin'):
            return value if want_K else value - 273.15
        if u in ('c', '°c', 'celsius', 'degc'):
            return value + 273.15 if want_K else value
        if u in ('f', '°f', 'fahrenheit', 'degf'):
            K = (value - 32.0) * 5.0 / 9.0 + 273.15
            return K if want_K else K - 273.15
        return None
    raise ValueError(f"unknown family {family!r}")


# UI mapping: QLineEdit attribute → (family, target unit). Lives in
# the domain layer (not main.py) so the unit-parsing concern is
# centralised — main.py only does Qt plumbing.
#
# Audit C5 Phase 4 (L-b, 2026-05-28): hoisted from
# ``Main_Menu._FIELD_UNITS`` so future widgets / scripts can read
# the same canonical map.
FIELD_UNITS = {
    # geometry — metres
    'le_L': ('length', 'm'), 'le_H': ('length', 'm'),
    'le_Lz': ('length', 'm'),
    'le_pipeA_in_ctr': ('length', 'm'), 'le_pipeA_in_w':  ('length', 'm'),
    'le_pipeA_out_ctr': ('length', 'm'), 'le_pipeA_out_w': ('length', 'm'),
    'le_pipeB_in_ctr': ('length', 'm'), 'le_pipeB_in_w':  ('length', 'm'),
    'le_pipeB_out_ctr': ('length', 'm'), 'le_pipeB_out_w': ('length', 'm'),
    # TPMS geometry — millimetres
    'le_Lcell': ('length', 'mm'), 'le_t': ('length', 'mm'),
    # flow / thermo
    'le_uA': ('speed', 'm/s'), 'le_uB': ('speed', 'm/s'),
    'le_PinA': ('pressure', 'Pa'), 'le_PinB': ('pressure', 'Pa'),
    'le_TinA': ('temp', None), 'le_TinB': ('temp', None),
    # counts (no unit allowed)
    'le_Nx': ('count', None), 'le_Ny': ('count', None),
    'le_Nz': ('count', None),
}


# Fields that must be strictly positive after unit-parse + numeric
# conversion (superset of FIELD_UNITS that adds the non-parseable
# positives like ``le_rho_s``).
POSITIVE_FIELDS = frozenset((
    'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t', 'le_ks',
    'le_uA', 'le_uB',
    'le_TinA', 'le_TinB', 'le_PinA', 'le_PinB',
    'le_Nx', 'le_Ny', 'le_Nz',
    'le_rho_s',
))


# Whitelist of unit tokens that count-family fields accept (they
# don't actually convert — just strip).
COUNT_TOKEN_WHITELIST = frozenset((
    'cells', 'cell', 'pts', 'points', 'nodes',
))


def format_unit_value(value: float, family: str) -> str:
    """Format a parsed value for UI display.

    Counts → ``int`` string.  Values outside ``[0.01, 1000)`` use
    ``%.6g`` (compact scientific).  Everything else uses ``%.4g``.
    Centralises the format heuristic that was inline in
    ``Main_Menu._install_inline_unit_parser`` pre-C5.
    """
    if family == 'count':
        return f"{int(round(value))}"
    if abs(value) >= 1000 or abs(value) < 0.01:
        return f"{value:.6g}"
    return f"{value:.4g}"


def parse_field_value(field_attr: str, raw_value: float, unit_text: str,
                      temp_unit: str = 'K') -> Optional[float]:
    """One-shot: look up the FIELD_UNITS entry for ``field_attr`` then
    delegate to :func:`parse_unit_value`.  Returns ``None`` when the
    field is not in the map, when the unit is rejected, or for
    count-family fields that received a non-whitelisted unit token.

    Audit C5 Phase 4 (L-b, 2026-05-28).
    """
    fam_target = FIELD_UNITS.get(field_attr)
    if fam_target is None:
        return None
    family, target_unit = fam_target
    if family == 'count':
        u = (unit_text or '').strip().lower()
        if u in COUNT_TOKEN_WHITELIST:
            return raw_value
        return None
    return parse_unit_value(raw_value, unit_text, family,
                            target_unit=target_unit, temp_unit=temp_unit)
