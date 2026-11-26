"""Bind desktop inputs to the case configuration and capture the active case."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import chain
from math import isfinite
from typing import Literal, Optional, get_args

from sjtu_tpmshx.data_types.compute_config import (
    ComputeConfig, ExtrapPolicy, FeatureFlags, FluidConfig, FluidType,
    GeometryConfig, OptimizerConfig, PartialBCConfig, Sco2NuConfig, SolverConfig, TPMSType,
    ZoneAxis, ZoneInputConfig,
)
from sjtu_tpmshx.data_types.validator import parse_unit_value

DOMAIN_SHAPE_NOTICE = (
    "当前仅支持矩形二维／长方体三维计算。\n"
    "六边形／八边形配置已不再支持载入，请使用矩形配置。\n"
    "原文件未修改。"
)

# ── helpers ──────────────────────────────────────────────────────────


def _qt_text(widget) -> str:
    """Return ``widget.text()`` (QLineEdit) or ``widget.currentText()``
    (QComboBox) or ``''`` for any AttributeError/None.

    Optional widgets (le_PinB, combo_fluidB, …) are guarded
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


def _selected_topology(combo) -> TPMSType:
    name = combo.currentText()
    if name not in get_args(TPMSType):
        raise ValueError(f'Unsupported TPMS topology {name!r}')
    return name


def _qt_float(widget, default):
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


@dataclass(frozen=True)
class FieldSpec:
    """Bind a configuration leaf to its desktop input or state its other use."""

    path: str
    widget: str = ''
    family: str = ''  # Unit parser for a line edit.
    label: str = ''
    required_order: int = 0  # Order of errors on strict capture.
    when: Literal['always', '3d', 'velocity', 'mass_flow'] = 'always'
    disposition: Literal['edited', 'derived', 'api-only', 'archive'] = 'edited'
    positive: bool = True  # Immediate sign check in the numeric editor.

    @property
    def definition(self):
        section, _, name = self.path.rpartition('.')
        owner = ComputeConfig
        if section:
            # The optional optimizer archive has no default factory.
            owner = (OptimizerConfig if section == 'optimizer'
                     else ComputeConfig.__dataclass_fields__[section].default_factory)
        return owner.__dataclass_fields__[name]

    @property
    def default(self):
        return self.definition.default

    @property
    def unit(self):
        return self.definition.metadata['unit']

    def editor_text(self, title, side=''):
        """Return the quantity label and initial text for a numeric row."""
        symbol, _, subscript = self.definition.metadata['symbol'].partition('_')
        subscript = ','.join(part for part in (subscript, side) if part)
        quantity = f'<i>{symbol}</i>'
        if subscript:
            quantity += f'<sub>{subscript}</sub>'
        units = '' if self.family == 'count' else f' [{self.unit}]'
        initial = '' if self.default is None else str(self.default)
        return f'{title} {quantity}{units}', initial


# Line edits follow the file and preflight focus order. Each port row has one
# transverse coordinate. The second pair applies only to 3D openings.
CONFIG_FIELDS = (
    FieldSpec('geometry.L_dom_m', 'le_L', 'length', 'Domain Length (L)', 1),
    FieldSpec('geometry.H_dom_m', 'le_H', 'length', 'Domain Height (H)', 2),
    FieldSpec('geometry.Lz_m', 'le_Lz', 'length', 'Width Lz', 14, '3d'),
    FieldSpec('geometry.L_cell_mm', 'le_Lcell', 'length', 'TPMS L_cell', 9),
    FieldSpec('geometry.t_wall_mm', 'le_t', 'length', 'TPMS t', 10),
    FieldSpec('geometry.k_s_W_mK', 'le_ks', 'conductivity', 'TPMS k_s', 11),
    FieldSpec('fluid_A.u_mps', 'le_uA', 'speed', 'Velocity A (u_A)', 5, 'velocity'),
    FieldSpec('fluid_A.T_in_K', 'le_TinA', 'temp', 'Inlet Temp A (T_inA)', 7),
    FieldSpec('fluid_A.P_in_Pa', 'le_PinA', 'pressure', 'Inlet Pressure A (P_inA)'),
    FieldSpec('fluid_B.u_mps', 'le_uB', 'speed', 'Velocity B (u_B)', 6, 'velocity'),
    FieldSpec('fluid_B.T_in_K', 'le_TinB', 'temp', 'Inlet Temp B (T_inB)', 8),
    FieldSpec('fluid_B.P_in_Pa', 'le_PinB', 'pressure', 'Inlet Pressure B (P_inB)'),
    *(FieldSpec(f'fluid_{side}.mass_flow_kg_s', f'le_mass_flow{side}', 'mass_flow',
                f'Total mass flow {side} [kg/s]', order, 'mass_flow')
      for side, order in (('A', 12), ('B', 13))),
    FieldSpec('solver.Nx', 'le_Nx', 'count', 'Grid Nx', 3),
    FieldSpec('solver.Ny', 'le_Ny', 'count', 'Grid Ny', 4),
    FieldSpec('solver.Nz', 'le_Nz', 'count', 'Grid Nz', 15, '3d'),
    *(FieldSpec(f'bc_{side}.{name}', f'le_pipe{side}_{name}', 'length',
                f'Pipe {side} {name}', positive=False)
      for names in (('in_ctr', 'in_w', 'out_ctr', 'out_w'),
                    ('in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'))
      for side in 'AB' for name in names),
    FieldSpec('geometry.tpms', 'combo_tpms'),
    FieldSpec('df_mode', 'combo_df_mode'),
    *(FieldSpec(f'fluid_{side}.type', f'combo_fluid{side}') for side in 'AB'),
    *(FieldSpec(f'bc_{side}.dir', f'combo_dir{side}') for side in 'AB'),
    FieldSpec('flags.port_wall_refine', 'combo_grid'),
    FieldSpec('flags.temp_unit', '_temp_unit'),
    FieldSpec('extrap.allow', 'chk_allow_extrap'),
    FieldSpec('sco2_nu.mode', 'combo_sco2_nu_mode'),
    *(FieldSpec(f'sco2_nu.{name}', '_sco2_nu_parameters')
      for name in ('alpha_D', 'alpha_G', 'parameter_version', 'source', 'applicability')),
    FieldSpec('zones.enabled', 'chk_zones'),
    FieldSpec('zones.axis', 'combo_zone_axis'),
    FieldSpec('zones.grid', 'zone_table'),
    FieldSpec('zones.config', 'zone_table'),  # A loaded continuous field replaces the table.
    *(FieldSpec(f'zones.{name}', f'_{name}', disposition='derived')
      for name in ('pareto_x_decision', 'pareto_y_trans_inlet', 'pareto_y_trans_outlet')),
    FieldSpec('flags.variable_rho_cp', disposition='derived'),
    *(FieldSpec(f'bc_{side}.uniform_inlet_2d', disposition='derived') for side in 'AB'),
    FieldSpec('geometry.delta_levelset', disposition='api-only'),
    FieldSpec('envelope_mode', disposition='api-only'),
    *(FieldSpec(f'solver.{name}', disposition='api-only') for name in (
        'max_outer_ltne', 'outer_tol_K', 'max_iter_simple', 'simple_velocity_relaxation',
        'T_s_init_K', 'convergence_mode', 'mom_tol', 'mass_local_tol', 'mass_global_tol',
        'enthalpy_algorithm', 'enthalpy_temperature_tol_K', 'model_h_max_iterations',
        'model_h_temperature_tol_K', 'model_h_q_relative_tol', 'ltne_enthalpy_outer',
        'ltne_enthalpy_nsweep', 'ltne_enthalpy_omega', 'ltne_enthalpy_tol',
        'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol',
        'require_enthalpy_update_on_temperature')),
    *(FieldSpec(f'optimizer.{name}', disposition='archive') for name in (
        'max_outer_ltne', 'outer_tol_K', 'max_iter_simple', 'alpha_T')),
)
LINE_EDITS = {spec.widget: spec for spec in CONFIG_FIELDS if spec.family}
_BY_PATH = {spec.path: spec for spec in CONFIG_FIELDS}
_REQUIRED = sorted((spec for spec in LINE_EDITS.values() if spec.required_order != 0),
                   key=lambda spec: spec.required_order)


def _bound_input(window, path, default=None):
    return getattr(window, _BY_PATH[path].widget, default)


COUNT_TOKEN_WHITELIST = frozenset(('cells', 'cell', 'pts', 'points', 'nodes'))


def parse_field_value(field_attr: str, raw_value: float, unit_text: str,
                      temp_unit: str = 'K') -> Optional[float]:
    """Convert a quantity to the unit of its active editor."""
    spec = LINE_EDITS.get(field_attr)
    if spec is None:
        return None
    if spec.family == 'count':
        return raw_value if (unit_text or '').strip().lower() in COUNT_TOKEN_WHITELIST else None
    return parse_unit_value(raw_value, unit_text, spec.family,
                            target_unit=spec.unit, temp_unit=temp_unit)


def mass_flow_active(window, side, *, is_3d=None):
    if is_3d is None:
        dimension = getattr(window, 'combo_dim', None)
        is_3d = dimension is not None and dimension.currentIndex() == 1
    mode = getattr(window, 'combo_inlet_mode' + side, None)
    return bool(is_3d and mode is not None and mode.currentData() == 'mass_flow')


def inlet_input_active(window, name, *, is_3d=None):
    mode = LINE_EDITS[name].when
    if mode in ('velocity', 'mass_flow'):
        return mass_flow_active(window, name[-1], is_3d=is_3d) == (mode == 'mass_flow')
    return True


def field_active(window, spec, *, is_3d):
    if not is_3d and (spec.when == '3d' or 2 not in spec.definition.metadata['dimensions']):
        return False
    return inlet_input_active(window, spec.widget, is_3d=is_3d)


def blank_second_span(window, name):
    """Return True when both fields of a second transverse span are blank."""
    prefix, _, field = name.rpartition('_')
    if prefix not in ('le_pipeA_in_z', 'le_pipeA_out_z',
                      'le_pipeB_in_z', 'le_pipeB_out_z') or field not in ('ctr', 'w'):
        return False
    return all(not _qt_text(getattr(window, f'{prefix}_{suffix}', None)).strip()
               for suffix in ('ctr', 'w'))


def _read_section_fields(window, section, *, is_3d, speed_default=None):
    """Read the numeric inputs for one section in their stored units."""
    values = {}
    for spec in LINE_EDITS.values():
        owner, name = spec.path.split('.')
        if owner != section:
            continue
        if spec.when == '3d' and not is_3d:
            continue
        if spec.when == 'mass_flow' and not mass_flow_active(window, section[-1], is_3d=is_3d):
            continue
        widget = getattr(window, spec.widget, None)
        default = spec.default
        if spec.when == 'velocity' and speed_default is not None:
            default = speed_default
        elif spec.when == 'mass_flow':
            # A blank active flow is invalid. None would select velocity instead.
            default = 0.0
        if spec.family == 'count':
            values[name] = _qt_int(widget, default)
        elif spec.family == 'temp':
            values[name] = _temp_in_K(window, widget, default)
        else:
            values[name] = _qt_float(widget, default)
    return values


def _validate_required_widgets(window, *, is_3d: bool) -> None:
    """Report invalid active inputs in the submit order. Blank optional inputs use their defaults."""
    optional = (spec for spec in LINE_EDITS.values() if spec.required_order == 0)
    bad = []
    for spec in chain(_REQUIRED, optional):
        if not field_active(window, spec, is_3d=is_3d):
            continue
        text = _qt_text(getattr(window, spec.widget, None)).strip()
        required = spec.required_order != 0
        if not text and not required:
            continue
        try:
            value = int(text) if spec.family == 'count' else float(text)
        except ValueError:
            bad.append(spec.label)
            continue
        # Temperature can be in degrees Celsius. Validate its sign in kelvin.
        if not isfinite(value) or (required and spec.family != 'temp' and value <= 0):
            bad.append(spec.label)
    if bad:
        raise ValueError(f"Invalid input in: {', '.join(bad)}")


def _parse_fluid_label(combo) -> FluidType:
    """Map supported GUI fluid labels to their configuration keys."""
    if combo is None:
        return 'air'
    try:
        label = combo.currentText()
    except Exception:
        return 'air'
    if isinstance(label, str):
        fluid = label.strip().lower().replace('₂', '2')
        if not fluid:
            return 'air'
        if fluid in get_args(FluidType):
            return fluid
    raise ValueError(f'Unsupported fluid label {label!r}')


def fluid_types_from_window(window) -> dict[str, FluidType]:
    """Read the selected fluid for each side."""
    return {side: _parse_fluid_label(_bound_input(window, f'fluid_{side}.type')) for side in 'AB'}


def _temp_in_K(window, widget, default_K: float) -> float:
    """Read the selected temperature scale. A partial draft uses the default in kelvin."""
    if widget is None:
        return default_K
    converter = getattr(window, '_temp_to_K', None)
    if converter is not None:
        try:
            return float(converter(widget))
        except Exception:
            pass  # fall back to direct float read
    return _qt_float(widget, default_K)


def _read_partial_bc(window, side: Literal['A', 'B'], *, is_3d: bool) -> 'PartialBCConfig':
    """Snapshot the per-side partial-pipe BC widgets into a dataclass.

    Shared with ``Main_Menu._fluid_config(side)`` for its second-transverse
    spans. In 3D, each inlet/outlet pair is independent of the other end
    and widget visibility. Both fields blank means full extent; half a
    pair is invalid. In 2D these drafts are ignored and stay ``None``.

    ``side='B'`` defaults to ``dir=3`` (-y) when ``combo_dirB`` is missing.
    """
    section = f'bc_{side}'
    combo_dir = _bound_input(window, f'{section}.dir')
    default_dir = 3 if side == 'B' else 0
    dir_int = default_dir
    if combo_dir is not None:
        try:
            dir_int = int(combo_dir.currentIndex())
        except Exception:
            dir_int = default_dir
    bc = PartialBCConfig(
        dir=dir_int,
        **{name: _qt_float(_bound_input(window, f'{section}.{name}'), getattr(PartialBCConfig, name))
           for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w')},
        uniform_inlet_2d=True,
    )
    if is_3d:
        for end in ('in', 'out'):
            center_text = _qt_text(_bound_input(window, f'{section}.{end}_z_ctr')).strip()
            width_text = _qt_text(_bound_input(window, f'{section}.{end}_z_w')).strip()
            if not center_text and not width_text:
                continue
            label = f'Pipe {side} {end} second-transverse centre and width'
            if not center_text or not width_text:
                raise ValueError(f'{label} must be set together')
            try:
                center, width = float(center_text), float(width_text)
            except ValueError as error:
                raise ValueError(f'{label} must be finite numbers') from error
            if not isfinite(center) or not isfinite(width):
                raise ValueError(f'{label} must be finite numbers')
            setattr(bc, f'{end}_z_ctr', center)
            setattr(bc, f'{end}_z_w', width)
    return bc


def _read_zone_input(window, geometry: GeometryConfig) -> ZoneInputConfig:
    """Capture the active zone representation with the geometry of this case."""
    chk = _bound_input(window, 'zones.enabled')
    enabled = chk is not None and chk.isChecked()
    continuous = getattr(window, '_continuous_field_spec', None)
    if enabled and continuous is not None:
        return ZoneInputConfig(enabled=True, axis='continuous',
                               config=deepcopy(continuous)).validate()
    axis: ZoneAxis = 'y'
    combo = _bound_input(window, 'zones.axis')
    if combo is not None:
        try:
            idx = int(combo.currentIndex())
            axis = ('y', 'x', 'grid')[max(0, min(idx, 2))]
        except Exception:
            axis = 'y'

    config, grid = None, None
    if enabled:
        from sjtu_tpmshx.applications.gui.ui.zone_table import build_zone_config
        table = _bound_input(window, 'zones.grid' if axis == 'grid' else 'zones.config')
        config, grid = build_zone_config(table, axis, geometry.tpms, geometry.k_s_W_mK)
    return ZoneInputConfig(
        enabled=enabled, axis=axis, grid=grid, config=config,
        pareto_x_decision=deepcopy(_bound_input(window, 'zones.pareto_x_decision')),
        pareto_y_trans_inlet=float(_bound_input(window, 'zones.pareto_y_trans_inlet', ZoneInputConfig.pareto_y_trans_inlet)),
        pareto_y_trans_outlet=float(_bound_input(window, 'zones.pareto_y_trans_outlet', ZoneInputConfig.pareto_y_trans_outlet)),
    ).validate()


def _read_feature_flags(window) -> 'FeatureFlags':
    """Snapshot the current desktop mesh and transport policy."""
    unit = _bound_input(window, 'flags.temp_unit', 'K')
    if unit not in ('K', 'C'):
        unit = 'K'
    mesh = _bound_input(window, 'flags.port_wall_refine')
    return FeatureFlags(port_wall_refine=bool(mesh is not None and mesh.currentData()),
                        variable_rho_cp=True, temp_unit=unit)


def _read_extrap_policy(window) -> 'ExtrapPolicy':
    """Snapshot the surrogate-domain extrapolation allow flag."""
    chk = _bound_input(window, 'extrap.allow')
    allow = chk is not None and chk.isChecked()
    return ExtrapPolicy(allow=allow)


def validate_domain_shape(shape: int = 0) -> None:
    """Reject unsupported saved shapes before any desktop inputs are applied."""
    if type(shape) is not int or shape != 0:
        raise ValueError(DOMAIN_SHAPE_NOTICE)


def config_from_window(window, *, strict: bool = False,
                       force_3d: Optional[bool] = None) -> ComputeConfig:
    """Capture the case inputs. A strict read checks all active numeric fields.

    A partial read uses the dataclass defaults for missing values. A missing
    B speed uses the A speed. Without a dimension selector, Nz gives the dimension.
    """
    is_3d = force_3d
    if is_3d is None:
        combo_dim = getattr(window, 'combo_dim', None)
        is_3d = (combo_dim.currentIndex() == 1 if combo_dim is not None
                 else _qt_int(_bound_input(window, 'solver.Nz'), SolverConfig.Nz) >= 2)
    if strict:
        _validate_required_widgets(window, is_3d=is_3d)
    selected_2d = not is_3d and (force_3d is not None or
                                getattr(window, 'combo_dim', None) is not None)
    topology = _bound_input(window, 'geometry.tpms')
    geom = GeometryConfig(
        tpms=_selected_topology(topology) if topology is not None else GeometryConfig.tpms,
        **_read_section_fields(window, 'geometry', is_3d=is_3d),
    )
    solver = SolverConfig(**_read_section_fields(window, 'solver', is_3d=not selected_2d))
    if is_3d and solver.Nz < 2:
        raise ValueError('Grid Nz must be >= 2 for 3D compute')

    fluid_types = fluid_types_from_window(window)
    fluid_A = FluidConfig(type=fluid_types['A'], **_read_section_fields(window, 'fluid_A', is_3d=is_3d))
    fluid_B = FluidConfig(type=fluid_types['B'], **_read_section_fields(
        window, 'fluid_B', is_3d=is_3d, speed_default=fluid_A.u_mps))

    bc_A = _read_partial_bc(window, 'A', is_3d=is_3d)
    bc_B = _read_partial_bc(window, 'B', is_3d=is_3d)
    zones = _read_zone_input(window, geom)
    if zones.enabled and zones.axis == 'continuous' and ('n_ctrl_z' in zones.config) != is_3d:
        raise ValueError('Continuous field dimension differs from the current case; restore the original dimension or clear the field')
    flags = _read_feature_flags(window)
    extrap = _read_extrap_policy(window)

    return ComputeConfig(fluid_A=fluid_A, fluid_B=fluid_B, geometry=geom, solver=solver,
                         bc_A=bc_A, bc_B=bc_B, zones=zones, flags=flags, extrap=extrap,
                         df_mode=df_mode_from_window(window), sco2_nu=sco2_nu_from_window(window))


def df_mode_from_window(window):
    combo = _bound_input(window, 'df_mode')
    return (combo.currentData() if combo is not None else None) or ComputeConfig.df_mode


def sco2_nu_from_window(window):
    combo = _bound_input(window, 'sco2_nu.mode')
    mode = combo.currentData() if combo is not None else Sco2NuConfig.mode
    settings = Sco2NuConfig(**_bound_input(window, 'sco2_nu.alpha_D', {}))
    return replace(settings, mode=mode).validate()
