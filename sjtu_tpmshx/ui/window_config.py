"""Window-harvest adapter: Qt widgets -> ComputeConfig (contracts-layer).

Split out of ``controllers/compute_config.py`` (openspec contracts-layer,
2026-07-02): the contracts (dataclasses, ``bc_to_dict``, JSON adapters) now
live in ``domain.compute_config``; THIS module is the only place that reads
``window.le_*`` / ``window.combo_*`` widget values.

Duck-typed throughout (``getattr`` + ``text()``/``currentText()`` probing) —
deliberately imports no Qt, so headless tests can pass plain stub objects.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Optional

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FeatureFlags, FluidConfig, FluidType,
    GeometryConfig, PartialBCConfig, SolverConfig, ZoneAxis, ZoneInputConfig,
)

DOMAIN_SHAPE_NOTICE = (
    "当前仅支持 Rectangle（矩形）2D / 3D 计算。\n"
    "Hexagon / Octagon 暂停计算，旧配置仍可查看和保存。\n"
    "如需计算，请明确切换为 Rectangle。"
)

# ── helpers ──────────────────────────────────────────────────────────


def _qt_text(widget) -> str:
    """Return ``widget.text()`` (QLineEdit) or ``widget.currentText()``
    (QComboBox) or ``''`` for any AttributeError/None.

    Optional widgets (le_TsInit, le_PinB, combo_fluidB, …) are guarded
    by ``hasattr`` upstream; mirror that here so the adapter never
    raises on a stripped-down test stub.
    """
    if widget is None:
        return ''
    text_fn = getattr(widget, 'text', None) or getattr(
        widget, 'currentText', None)
    if text_fn is None:
        return ''
    try:
        return text_fn()
    except Exception:
        return ''


def _qt_float(widget, default: float) -> float:
    """Parse ``widget.text()`` as float, fall back to ``default``."""
    txt = _qt_text(widget).strip()
    if not txt:
        return default
    try:
        return float(txt)
    except (TypeError, ValueError):
        return default


def _qt_int(widget, default: int) -> int:
    """Parse ``widget.text()`` as int, fall back to ``default``."""
    txt = _qt_text(widget).strip()
    if not txt:
        return default
    try:
        return int(txt)
    except (TypeError, ValueError):
        return default


# Required widget attributes for strict-mode validation. The labels mirror
# the human-friendly names that the legacy ``pipelines.stages_2d._parse``
# helper surfaced in its ``ValueError`` payload.
@dataclass(frozen=True)
class FieldSpec:
    """One scalar ComputeConfig field's wiring: dataclass slot ↔ Qt widget
    ↔ parse kind ↔ required-validation membership (B2 2.4, 2026-06-12).

    Single source for the add-a-field procedure — previously adding one
    field meant touching the dataclass, ``config_from_window``, and the
    ``_REQUIRED_*`` lists independently (silent-default drift when one
    was missed). ``kind``: 'float' | 'int' | 'temp' (unit-aware Kelvin).
    ``special=True`` rows participate in validation only; their read has
    bespoke semantics kept explicit in ``config_from_window`` (cross-field
    defaults, None-when-missing, combo parsing).
    """
    section: str            # 'geometry' | 'solver' | 'fluid_A' | 'fluid_B'
    name: str               # dataclass field name
    widget: str             # window attribute, e.g. 'le_Lcell'
    kind: str               # 'float' | 'int' | 'temp'
    default: Any
    label: str = ''         # human label for the validation message
    required_2d: bool = False
    required_3d_extra: bool = False
    special: bool = False   # validated here, read bespokely


# Declaration order == legacy validation-message order (2D block first,
# then the 3D extras), preserved verbatim from the retired _REQUIRED_* lists.
CONFIG_FIELDS: tuple = (
    FieldSpec('geometry', 'L_dom_m',   'le_L',     'float', 0.182,
              label="Domain Length (L)", required_2d=True),
    FieldSpec('geometry', 'H_dom_m',   'le_H',     'float', 0.042,
              label="Domain Height (H)", required_2d=True),
    FieldSpec('solver',   'Nx',        'le_Nx',    'int',   30,
              label="Grid Nx", required_2d=True),
    FieldSpec('solver',   'Ny',        'le_Ny',    'int',   60,
              label="Grid Ny", required_2d=True),
    FieldSpec('fluid_A',  'u_mps',     'le_uA',    'float', 5.0,
              label="Velocity A (u_A)", required_2d=True),
    FieldSpec('fluid_B',  'u_mps',     'le_uB',    'float', None,
              label="Velocity B (u_B)", required_2d=True,
              special=True),   # default = fluid_A.u_mps (cross-field)
    FieldSpec('fluid_A',  'T_in_K',    'le_TinA',  'temp',  300.0,
              label="Inlet Temp A (T_inA)", required_2d=True),
    FieldSpec('fluid_B',  'T_in_K',    'le_TinB',  'temp',  300.0,
              label="Inlet Temp B (T_inB)", required_2d=True),
    FieldSpec('geometry', 'L_cell_mm', 'le_Lcell', 'float', 7.0,
              label="TPMS L_cell", required_2d=True),
    FieldSpec('geometry', 't_wall_mm', 'le_t',     'float', 0.6,
              label="TPMS t", required_2d=True),
    FieldSpec('geometry', 'k_s_W_mK',  'le_ks',    'float', 16.0,
              label="TPMS k_s", required_2d=True),
    FieldSpec('geometry', 'Lz_m',      'le_Lz',    'float', 0.042,
              label="Width Lz", required_3d_extra=True,
              special=True),   # None when the widget is absent (2D flag)
    FieldSpec('solver',   'Nz',        'le_Nz',    'int',   1,
              label="Grid Nz", required_3d_extra=True),
    # Non-required scalars — blank keeps the default, but NON-EMPTY text
    # must parse (W2, 2026-07-07; enforced in _validate_required_widgets):
    FieldSpec('fluid_A',  'P_in_Pa',   'le_PinA',  'float', 101325.0,
              label="Inlet Pressure A (P_inA)"),
    FieldSpec('fluid_B',  'P_in_Pa',   'le_PinB',  'float', 101325.0,
              label="Inlet Pressure B (P_inB)"),
)


def _read_section_fields(window, section: str) -> dict:
    """Table-driven scalar reads for one config section (non-special rows)."""
    out = {}
    for fs in CONFIG_FIELDS:
        if fs.section != section or fs.special:
            continue
        w = getattr(window, fs.widget, None)
        if fs.kind == 'float':
            out[fs.name] = _qt_float(w, fs.default)
        elif fs.kind == 'int':
            out[fs.name] = _qt_int(w, fs.default)
        elif fs.kind == 'temp':
            out[fs.name] = _temp_in_K(window, w, default_K=fs.default)
    return out


def _validate_required_widgets(window, *, is_3d: bool) -> None:
    """Raise ``ValueError`` listing every invalid input widget.

    Existing numeric widgets reject blank, malformed and nonfinite text.
    Missing optional widgets use their declared defaults; a blank widget is
    not a missing widget. Temperature input is interpreted in the selected
    display unit before ComputeConfig checks positive Kelvin values.
    """
    import math as _math
    required = [fs for fs in CONFIG_FIELDS if fs.required_2d]
    if is_3d:
        required += [fs for fs in CONFIG_FIELDS if fs.required_3d_extra]
    bad = []
    for fs in required:
        widget = getattr(window, fs.widget, None)
        if widget is None:
            bad.append(fs.label)
            continue
        txt = _qt_text(widget).strip()
        if not txt:
            bad.append(fs.label)
            continue
        caster = int if fs.kind == 'int' else float
        try:
            v = float(caster(txt))
        except ValueError:
            bad.append(fs.label)
            continue
        # robustness-hardening (2026-07-03): `float("nan")`/`float("inf")`
        # parse successfully, so castability alone let non-finite values
        # into ComputeConfig. All required fields are physically positive;
        # 'temp' fields are exempt from the sign check here because the raw
        # text may be °C (negative is legit) — their Kelvin positivity is
        # enforced by ComputeConfig.validate() downstream.
        if not _math.isfinite(v):
            bad.append(fs.label)
        elif fs.kind != 'temp' and v <= 0:
            bad.append(fs.label)
    # Optional CONFIG_FIELDS rows (e.g. P_in_Pa): non-empty must parse
    # finite. No sign check — downstream validation owns physics bounds.
    _seen = {fs.widget for fs in required}
    for fs in CONFIG_FIELDS:
        if fs.widget in _seen or fs.special:
            continue
        widget = getattr(window, fs.widget, None)
        if widget is None:
            continue
        txt = _qt_text(widget).strip()
        if not txt:
            continue
        caster = int if fs.kind == 'int' else float
        try:
            v = float(caster(txt))
        except ValueError:
            bad.append(fs.label or fs.name)
            continue
        if not _math.isfinite(v):
            bad.append(fs.label or fs.name)
    # Partial-BC pipe widgets (read via _qt_float(…, 0.0) in
    # _read_partial_bc): a parse failure there silently zeroed the pipe
    # geometry. Non-empty must parse finite; 0.0 itself stays legal.
    for side in ('A', 'B'):
        for suffix in ('in_ctr', 'in_w', 'out_ctr', 'out_w',
                       'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
            w = getattr(window, f'le_pipe{side}_{suffix}', None)
            if w is None:
                continue
            txt = _qt_text(w).strip()
            if not txt:
                continue
            try:
                v = float(txt)
            except (TypeError, ValueError):
                bad.append(f"Pipe {side} {suffix}")
                continue
            if not _math.isfinite(v):
                bad.append(f"Pipe {side} {suffix}")
    if bad:
        raise ValueError(f"Invalid input in: {', '.join(bad)}")


def _parse_fluid_label(combo) -> FluidType:
    """Inline copy of ``solvers.tpms_calc.parse_fluid_type``.

    Keeping the small mapping inline avoids importing the solver
    package from this controller module (purity rule, see header).
    """
    if combo is None:
        return 'air'
    try:
        text = combo.currentText().lower().replace('₂', '2')
    except Exception:
        return 'air'
    if 'co2' in text or 'sco' in text:
        return 'sco2'
    if 'water' in text:
        return 'water'
    return 'air'


def _temp_in_K(window, widget, default_K: float) -> float:
    """Honour the window's ``_temp_to_K`` toggle if present.

    Both ``run_calculation._parse_inputs`` and
    ``run_calculation_3d._parse_inputs`` route inlet-temperature reads
    through ``window._temp_to_K`` so the K/°C UI toggle is honoured.
    We do the same here so ``config_from_window`` always returns Kelvin.
    """
    if widget is None:
        return default_K
    converter = getattr(window, '_temp_to_K', None)
    if converter is not None:
        try:
            return float(converter(widget))
        except Exception:
            pass  # fall back to direct float read
    return _qt_float(widget, default_K)


def _read_partial_bc(window, side: Literal['A', 'B']) -> 'PartialBCConfig':
    """Snapshot the per-side partial-pipe BC widgets into a dataclass.

    Mirrors ``Main_Menu._fluid_config(side)`` but does not call back into
    the window once the cfg is built. Optional z-partial widgets are
    only honoured when the matching ``le_pipe<side>_in_z_*`` widgets
    exist and are visible (3D mode); otherwise the z-fields stay
    ``None`` and the solver treats the z-axis as full-face.

    ``side='B'`` defaults to ``dir=3`` (-y) when ``combo_dirB`` is
    missing, matching the legacy ``pipelines.stages_2d._parse_inputs``
    fall-through (``cfgB = dict(dir=3, …)``).
    """
    le_prefix = f'le_pipe{side}'
    combo_dir = getattr(window, f'combo_dir{side}', None)
    default_dir = 3 if side == 'B' else 0
    dir_int = default_dir
    if combo_dir is not None:
        try:
            dir_int = int(combo_dir.currentIndex())
        except Exception:
            dir_int = default_dir
    bc = PartialBCConfig(
        dir=dir_int,
        in_ctr=_qt_float(getattr(window, f'{le_prefix}_in_ctr', None), 0.0),
        in_w=_qt_float(getattr(window, f'{le_prefix}_in_w', None), 0.0),
        out_ctr=_qt_float(getattr(window, f'{le_prefix}_out_ctr', None), 0.0),
        out_w=_qt_float(getattr(window, f'{le_prefix}_out_w', None), 0.0),
    )
    # 3D z-partial widgets are only present (and visible) in 3D mode.
    le_in_z_ctr = getattr(window, f'{le_prefix}_in_z_ctr', None)
    if le_in_z_ctr is not None:
        try:
            visible = not le_in_z_ctr.isHidden()
        except Exception:
            visible = True
        if visible:
            # FIX (2026-06-24 audit): parse all four z-values into locals first,
            # then commit to bc only if EVERY parse succeeds. The old code mutated
            # bc field-by-field, so a mid-sequence ValueError/AttributeError (e.g.
            # one z-widget blank/non-numeric) left a HALF-populated config (some
            # float, some None). bc_to_dict gates only on in_z_ctr is not None and
            # then emits all four keys, so a half state writes out_z_w=None, and
            # _build_partial_masks (stages_3d) crashes on `None / 2`. Atomic
            # all-or-nothing matches the documented all-None fallback.
            try:
                _in_z_ctr  = float(le_in_z_ctr.text())
                _in_z_w    = float(getattr(window, f'{le_prefix}_in_z_w').text())
                _out_z_ctr = float(getattr(window, f'{le_prefix}_out_z_ctr').text())
                _out_z_w   = float(getattr(window, f'{le_prefix}_out_z_w').text())
            except (AttributeError, ValueError):
                # Leave z-fields as None — solver treats as full face.
                pass
            else:
                bc.in_z_ctr, bc.in_z_w = _in_z_ctr, _in_z_w
                bc.out_z_ctr, bc.out_z_w = _out_z_ctr, _out_z_w
    return bc


def _read_zone_input(window) -> 'ZoneInputConfig':
    """Snapshot zone / sigmoid-field control state.

    Reads ``chk_zones``, ``combo_zone_axis``, ``_zone_grid``, and the
    ``_pareto_*`` attributes. When ``chk_zones`` is checked, also
    pre-resolves the ``ZoneConfig`` instance via
    ``ui.zone_table.build_zone_config(window)`` so the downstream
    Pipeline2D / Pipeline3D layer never touches the Qt zone-table
    widget.

    Invalid enabled zones propagate through the existing input-error channel.
    Mutable grid and Pareto inputs belong to this snapshot after capture.
    """
    chk = getattr(window, 'chk_zones', None)
    enabled = bool(chk is not None and getattr(chk, 'isChecked', lambda: False)())
    axis: ZoneAxis = 'y'
    combo = getattr(window, 'combo_zone_axis', None)
    if combo is not None:
        try:
            idx = int(combo.currentIndex())
            axis = ('y', 'x', 'grid')[max(0, min(idx, 2))]
        except Exception:
            axis = 'y'

    # Pre-resolve ZoneConfig (1D zone mode needs the zone-table rows).
    # Grid mode populates ``window._zone_grid`` as a side effect.
    resolved_config = None
    if enabled:
        from sjtu_tpmshx.ui.zone_table import build_zone_config as _bzc
        resolved_config = _bzc(window)
    grid = getattr(window, '_zone_grid', None)
    return deepcopy(ZoneInputConfig(
        enabled=enabled,
        axis=axis,
        grid=grid if isinstance(grid, dict) else None,
        config=resolved_config,
        pareto_x_decision=getattr(window, '_pareto_x_decision', None),
        pareto_y_trans_inlet=float(
            getattr(window, '_pareto_y_trans_inlet', 0.2)),
        pareto_y_trans_outlet=float(
            getattr(window, '_pareto_y_trans_outlet', 0.2)),
    )).validate()


def _read_feature_flags(window) -> 'FeatureFlags':
    """Snapshot UI feature-flag toggles that survive into the solver."""
    chk_wall = getattr(window, 'chk_wall_refine_3d', None)
    wall = bool(chk_wall is not None and
                getattr(chk_wall, 'isChecked', lambda: False)())
    # variable_rho_cp defaults ON (2026-06-09); an absent toggle (old/partial
    # window) keeps the default, a present one mirrors its checked state.
    chk_vrc = getattr(window, 'chk_var_rhocp', None)
    var_rhocp = (bool(getattr(chk_vrc, 'isChecked', lambda: True)())
                 if chk_vrc is not None else True)
    unit = getattr(window, '_temp_unit', 'K')
    if unit not in ('K', 'C'):
        unit = 'K'
    return FeatureFlags(wall_refine_3d=wall, variable_rho_cp=var_rhocp,
                        temp_unit=unit)


def _read_extrap_policy(window) -> 'ExtrapPolicy':
    """Snapshot the surrogate-domain extrapolation allow flag."""
    chk = getattr(window, 'chk_allow_extrap', None)
    allow = bool(chk is not None and
                 getattr(chk, 'isChecked', lambda: False)())
    return ExtrapPolicy(allow=allow)


def validate_domain_shape(window) -> None:
    """Reject a polygon selection before it can become a rectangular config."""
    shape = _qt_text(getattr(window, 'combo_shape', None))
    if shape and shape != 'Rectangle':
        raise ValueError(DOMAIN_SHAPE_NOTICE)


def config_from_window(window, *, strict: bool = False,
                       force_3d: Optional[bool] = None) -> ComputeConfig:
    """Build a :class:`ComputeConfig` from the main UI window.

    Free-function form of the retired ``ComputeConfig.from_qt_window``
    classmethod (contracts-layer split). Reads ``window.le_*`` /
    ``window.combo_*`` exactly once; missing optional widgets fall back
    to the dataclass defaults. ``strict=True`` raises ``ValueError``
    listing every blank / non-numeric required widget; ``force_3d``
    selects the effective dimension (None = combo_dim, or le_Nz for
    headless callers). Hidden widget values are never changed.
    """
    validate_domain_shape(window)
    is_3d = force_3d
    if is_3d is None:
        combo_dim = getattr(window, 'combo_dim', None)
        is_3d = (combo_dim.currentIndex() == 1 if combo_dim is not None
                 else _qt_int(getattr(window, 'le_Nz', None), 1) >= 2)
    if strict:
        _validate_required_widgets(window, is_3d=is_3d)
    # ── table-driven scalar reads (B2 2.4: CONFIG_FIELDS single source;
    # ── special rows keep their bespoke semantics explicit below) ──
    # geometry — tpms combo parse + Lz None-when-absent are special:
    tpms = _qt_text(getattr(window, 'combo_tpms', None)) or 'Gyroid'
    if tpms not in ('Diamond', 'Gyroid'):
        tpms = 'Gyroid'
    geom = GeometryConfig(
        tpms=tpms,
        Lz_m=(_qt_float(getattr(window, 'le_Lz', None), 0.042)
              if getattr(window, 'le_Lz', None) is not None else None),
        **_read_section_fields(window, 'geometry'),
    )

    # solver — optional Ts init (empty / None → solver default seed):
    T_s_init: Optional[float] = None
    le_ts = getattr(window, 'le_TsInit', None)
    if le_ts is not None and _qt_text(le_ts).strip():
        # robustness-hardening: the old `... or None` coerced a legit
        # 0.0 K parse to None AND let absurd seeds through. Explicit
        # None-compare + a loose physical range (anything outside is a
        # typo, not a use case).
        _ts = _temp_in_K(window, le_ts, default_K=0.0)
        T_s_init = _ts if (_ts is not None and 150.0 <= _ts <= 2000.0) \
            else None
    solver = SolverConfig(
        T_s_init_K=T_s_init,
        # remaining knobs keep dataclass defaults; UI does not surface
        # them yet (audit deferred to a later phase)
        **_read_section_fields(window, 'solver'),
    )
    if not is_3d and (force_3d is not None or
                      getattr(window, 'combo_dim', None) is not None):
        solver.Nz = 1
    elif is_3d and solver.Nz < 2:
        raise ValueError('Grid Nz must be >= 2 for 3D compute')

    # fluids — type combos special; fluid_B.u_mps defaults to A's value:
    fluid_A = FluidConfig(
        type=_parse_fluid_label(getattr(window, 'combo_fluidA', None)),
        **_read_section_fields(window, 'fluid_A'),
    )
    fluid_B = FluidConfig(
        type=_parse_fluid_label(getattr(window, 'combo_fluidB', None)),
        u_mps=_qt_float(getattr(window, 'le_uB', None), fluid_A.u_mps),
        **_read_section_fields(window, 'fluid_B'),
    )

    # ── audit C4 additions ──────────────────────────────────
    # Partial-pipe BC + zone state + feature flags + extrap policy.
    # Defaults preserve legacy behaviour when widgets are missing
    # (test stubs, headless scripts).
    bc_A = _read_partial_bc(window, 'A')
    bc_B = _read_partial_bc(window, 'B')
    zones = _read_zone_input(window)
    flags = _read_feature_flags(window)
    extrap = _read_extrap_policy(window)

    _df_combo = getattr(window, 'combo_df_mode', None)
    df_mode = (_df_combo.currentData() if _df_combo is not None else None)

    nu = sco2_nu_from_window(window)

    return ComputeConfig(fluid_A=fluid_A, fluid_B=fluid_B,
               geometry=geom, solver=solver,
               bc_A=bc_A, bc_B=bc_B,
               zones=zones, flags=flags, extrap=extrap,
               df_mode=df_mode or 'cfd_smooth', sco2_nu=nu)


__all__ = ['config_from_window', 'FieldSpec', 'CONFIG_FIELDS']


def sco2_nu_from_window(window):
    from dataclasses import replace
    from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
    combo = getattr(window, 'combo_sco2_nu_mode', None)
    mode = combo.currentData() if combo is not None else 'cfd_smooth'
    settings = Sco2NuConfig(**getattr(window, '_sco2_nu_parameters', {}))
    return replace(settings, mode=mode).validate()
