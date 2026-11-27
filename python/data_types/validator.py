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
from decimal import Context, Decimal, InvalidOperation, MAX_EMAX, MAX_PREC, MIN_EMIN
import math
from numbers import Integral
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

import numpy as np

from sjtu_tpmshx.model_configs.df_domain import TRAIN_L_NODES, TRAIN_T_NODES
from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K


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
    d = cfg.get('dir', 0)
    if isinstance(d, bool) or not isinstance(d, Integral):
        out.append(Warning(
            'pipe_bad_dir',
            f"pipe direction {cfg.get('dir')!r} is not an integer",
            severity='error'))
        return out
    d = cast(int, d)  # Integral includes NumPy integer keys; no runtime coercion.
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
            # float itself validates arbitrary external values in this try block.
            ctr = float(cast(Any, cfg.get(f'{io}_ctr', 0.0)))
            w = float(cast(Any, cfg.get(f'{io}_w', 0.0)))
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
                zc, zw = float(cast(Any, zc)), float(cast(Any, zw))
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


_UNIT_LENGTH_DEC = {
    'm': (Decimal('1'), Decimal('1')),
    'cm': (Decimal('1'), Decimal('100')),
    'mm': (Decimal('1'), Decimal('1000')),
    'μm': (Decimal('1'), Decimal('1000000')),
    'um': (Decimal('1'), Decimal('1000000')),
    'in': (Decimal('0.0254'), Decimal('1')),
    'inch': (Decimal('0.0254'), Decimal('1')),
    'ft': (Decimal('0.3048'), Decimal('1')),
}
_UNIT_PRESSURE_DEC = {
    'pa': (Decimal('1'), Decimal('1')),
    'kpa': (Decimal('1000'), Decimal('1')),
    'mpa': (Decimal('1000000'), Decimal('1')),
    'bar': (Decimal('100000'), Decimal('1')),
    'mbar': (Decimal('100'), Decimal('1')),
    'psi': (Decimal('6894.757'), Decimal('1')),
    'atm': (Decimal('101325'), Decimal('1')),
    'torr': (Decimal('133.322'), Decimal('1')),
    'mmhg': (Decimal('133.322'), Decimal('1')),
}
_UNIT_SPEED_DEC = {
    'm/s': (Decimal('1'), Decimal('1')),
    'cm/s': (Decimal('1'), Decimal('100')),
    'mm/s': (Decimal('1'), Decimal('1000')),
    'km/h': (Decimal('1'), Decimal('3.6')),
    'kph': (Decimal('1'), Decimal('3.6')),
    'mph': (Decimal('0.44704'), Decimal('1')),
    'ft/s': (Decimal('0.3048'), Decimal('1')),
}
_UNIT_MASS_FLOW_DEC = {
    'kg/s': (Decimal('1'), Decimal('1')),
    'g/s': (Decimal('1'), Decimal('1000')),
    'kg/min': (Decimal('1'), Decimal('60')),
    'g/min': (Decimal('1'), Decimal('60000')),
    'kg/h': (Decimal('1'), Decimal('3600')),
    'g/h': (Decimal('1'), Decimal('3600000')),
}
_UNIT_CONDUCTIVITY_DEC = {
    'W/(mK)': (Decimal('1'), Decimal('1')),
    'W/m/K': (Decimal('1'), Decimal('1')),
    'W/mK': (Decimal('1'), Decimal('1')),
    'kW/(mK)': (Decimal('1000'), Decimal('1')),
    'kW/m/K': (Decimal('1000'), Decimal('1')),
    'kW/mK': (Decimal('1000'), Decimal('1')),
}
_CELSIUS_ZERO_DEC = Decimal(str(CELSIUS_ZERO_K))

TempUnit = Literal['K', 'C']
# Addition, subtraction and normalize() in this context do not round and do not overflow.
EXACT_CONTEXT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)


def convert_temp_decimal(value: Decimal, from_unit: TempUnit, to_unit: TempUnit) -> Decimal:
    """Convert a temperature between K and degrees Celsius without rounding."""
    if from_unit == to_unit:
        return value
    if from_unit == 'C':
        return EXACT_CONTEXT.add(value, _CELSIUS_ZERO_DEC)
    return EXACT_CONTEXT.subtract(value, _CELSIUS_ZERO_DEC)


def temp_text_to_kelvin(text: str, unit: TempUnit) -> Decimal:
    """Read one inlet temperature text in the given unit and return kelvin."""
    raw = str(text).strip()
    # Compute and Save read this text with float(). Accept the same syntax, then convert the exact Decimal.
    float(raw)
    try:
        # Decimal() rejects an exponent outside its range, for example 1e-9999999999999999999.
        return convert_temp_decimal(Decimal(raw), unit, 'K')
    except InvalidOperation as exc:
        raise ValueError(f"could not convert string to float: {raw!r}") from exc


def kelvin_to_display(kelvin, unit: TempUnit):
    """Map result temperatures in K (float or ndarray) to the display unit.

    Use one binary64 subtraction for fields, color limits, hover, probe and readout.
    Compute color limits in K, then map them with this function.
    """
    return np.subtract(kelvin, CELSIUS_ZERO_K, dtype=np.float64) if unit == 'C' else kelvin


def parse_unit_decimal(raw_text: str, unit_text: str,
                       family: str, target_unit: Optional[str] = None,
                       temp_unit: TempUnit = 'K') -> Optional[Decimal]:
    """Convert ``raw_text [unit_text]`` to ``target_unit`` with exact Decimal factors."""
    try:
        dec = Decimal(str(raw_text).strip())
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite():
        return None
    u = unit_text.strip().lower().replace('·', '')
    if family in ('length', 'pressure', 'speed', 'mass_flow', 'conductivity'):
        if family == 'length':
            table, default_target = _UNIT_LENGTH_DEC, 'm'
            target = (target_unit or default_target).lower()
        elif family == 'pressure':
            table, default_target = _UNIT_PRESSURE_DEC, 'pa'
            target = (target_unit or default_target).lower()
        elif family == 'speed':
            table, default_target = _UNIT_SPEED_DEC, 'm/s'
            target = (target_unit or default_target).lower()
        elif family == 'mass_flow':
            table, default_target = _UNIT_MASS_FLOW_DEC, 'kg/s'
            target = (target_unit or default_target).lower()
        else:
            # Preserve SI prefix case. Accept the unit on the form and its slash notation.
            table = _UNIT_CONDUCTIVITY_DEC
            u = unit_text.strip().replace(' ', '').replace('·', '')
            target = (target_unit or 'W/(m·K)').replace(' ', '').replace('·', '')
        if u not in table or target not in table:
            return None
        src_mul, src_div = table[u]
        dst_mul, dst_div = table[target]
        num = dec * src_mul * dst_div
        den = src_div * dst_mul
        return num if den == 1 else num / den
    if family == 'temp':
        if u in ('k', 'kelvin'):
            return convert_temp_decimal(dec, 'K', temp_unit)
        if u in ('c', '°c', 'celsius', 'degc'):
            return convert_temp_decimal(dec, 'C', temp_unit)
        if u in ('f', '°f', 'fahrenheit', 'degf'):
            K = (dec - Decimal('32')) * Decimal('5') / Decimal('9') + _CELSIUS_ZERO_DEC
            return convert_temp_decimal(K, 'K', temp_unit)
        return None
    raise ValueError(f"unknown family {family!r}")


def parse_unit_value(value: float, unit_text: str,
                     family: str, target_unit: Optional[str] = None,
                     temp_unit: TempUnit = 'K') -> Optional[float]:
    """Convert ``value [unit_text]`` to ``target_unit`` for ``family``.

    Returns the converted scalar in ``target_unit``, or ``None`` if the
    unit token is unrecognised for the family.

    Temperature handling honours the GUI's current display toggle
    (``temp_unit``): if ``temp_unit='K'`` the return is Kelvin even if
    the user typed 25 °C. ``target_unit`` is ignored for temp.
    """
    converted = parse_unit_decimal(
        repr(float(value)), unit_text, family,
        target_unit=target_unit, temp_unit=temp_unit,
    )
    return None if converted is None else float(converted)


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
