"""Derive display fields and describe recorded result fields without Qt."""
from __future__ import annotations

from dataclasses import dataclass

COLORMAP_CHOICES = ('coolwarm', 'turbo', 'viridis', 'cividis')
COLORMAP_QUANTITIES = ('temperature', 'speed', 'pressure', 'design')
DEFAULT_COLORMAPS = {
    'temperature': 'coolwarm',
    'speed': 'viridis',
    'pressure': 'viridis',
    'design': 'turbo',
}


@dataclass(frozen=True)
class ResultFieldSpec:
    """Qt-free display contract for one canonical ComputeResult scalar field."""

    key: str
    panel_key: str
    quantity: str
    phase: str
    symbol: str
    symbol_tex: str
    symbol_html: str
    stored_unit: str
    display_unit: str
    display_scale: float
    default_cmap: str
    fmt: str
    title_plain: str
    label: str
    dims: tuple[int, ...]


_SPEC_ROWS = (
    ResultFieldSpec(
        key='Ta', panel_key='Ta', quantity='temperature', phase='A',
        symbol='T_fA', symbol_tex=r'$T_{f,A}$', symbol_html='<i>T</i><sub>f,A</sub>',
        stored_unit='K', display_unit='K', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['temperature'], fmt='%.1f',
        title_plain='Ta (K)', label='Temperature A', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='Tb', panel_key='Tb', quantity='temperature', phase='B',
        symbol='T_fB', symbol_tex=r'$T_{f,B}$', symbol_html='<i>T</i><sub>f,B</sub>',
        stored_unit='K', display_unit='K', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['temperature'], fmt='%.1f',
        title_plain='Tb (K)', label='Temperature B', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='Ts', panel_key='Ts', quantity='temperature', phase='solid',
        symbol='T_s', symbol_tex=r'$T_s$', symbol_html='<i>T</i><sub>s</sub>',
        stored_unit='K', display_unit='K', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['temperature'], fmt='%.1f',
        title_plain='Ts (K)', label='Temperature Solid', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='vmag_A', panel_key='vmag', quantity='speed', phase='A',
        symbol='|u_A|', symbol_tex=r'$|\mathbf{u}_A|$', symbol_html='|<i>u</i>|<sub>A</sub>',
        stored_unit='m/s', display_unit='m/s', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['speed'], fmt='%.2f',
        title_plain='speed A (m/s)', label='Velocity A', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='vmag_B', panel_key='vmag_B', quantity='speed', phase='B',
        symbol='|u_B|', symbol_tex=r'$|\mathbf{u}_B|$', symbol_html='|<i>u</i>|<sub>B</sub>',
        stored_unit='m/s', display_unit='m/s', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['speed'], fmt='%.2f',
        title_plain='speed B (m/s)', label='Velocity B', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='P_fA', panel_key='P_kPa', quantity='pressure', phase='A',
        symbol='P_A', symbol_tex=r'$P_A$', symbol_html='<i>P</i><sub>A</sub>',
        stored_unit='Pa', display_unit='kPa', display_scale=1e-3,
        default_cmap=DEFAULT_COLORMAPS['pressure'], fmt='%.1f',
        title_plain='PA abs (kPa)', label='Pressure A', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='P_fB', panel_key='P_B_kPa', quantity='pressure', phase='B',
        symbol='P_B', symbol_tex=r'$P_B$', symbol_html='<i>P</i><sub>B</sub>',
        stored_unit='Pa', display_unit='kPa', display_scale=1e-3,
        default_cmap=DEFAULT_COLORMAPS['pressure'], fmt='%.1f',
        title_plain='PB abs (kPa)', label='Pressure B', dims=(2, 3),
    ),
    ResultFieldSpec(
        key='L_mm', panel_key='L_mm', quantity='design', phase='geometry',
        symbol='L', symbol_tex=r'$L$', symbol_html='<i>L</i>',
        stored_unit='mm', display_unit='mm', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['design'], fmt='%.2f',
        title_plain='L (mm)', label='Design L', dims=(3,),
    ),
    ResultFieldSpec(
        key='t_mm', panel_key='t_mm', quantity='design', phase='geometry',
        symbol='t', symbol_tex=r'$t$', symbol_html='<i>t</i>',
        stored_unit='mm', display_unit='mm', display_scale=1.0,
        default_cmap=DEFAULT_COLORMAPS['design'], fmt='%.3f',
        title_plain='t (mm)', label='Wall thickness t', dims=(3,),
    ),
)

RESULT_FIELD_SPECS: dict[str, ResultFieldSpec] = {spec.key: spec for spec in _SPEC_ROWS}
PANEL_FIELD_SPECS: dict[str, ResultFieldSpec] = {spec.panel_key: spec for spec in _SPEC_ROWS}


def field_spec(key: str) -> ResultFieldSpec:
    """Return the display specification for a canonical or 3D panel field key."""
    if key in RESULT_FIELD_SPECS:
        return RESULT_FIELD_SPECS[key]
    return PANEL_FIELD_SPECS[key]


def extrapolation_model_label(metadata: dict | None) -> str:
    """Return the recorded Darcy-Forchheimer model ID for one result."""
    if not isinstance(metadata, dict):
        raise ValueError('Result metadata must provide the recorded darcy_forchheimer model reference')
    for ref in metadata.get('model_refs') or ():
        if isinstance(ref, dict) and ref.get('name') == 'darcy_forchheimer':
            version = ref.get('version')
            if isinstance(version, str) and version.strip():
                mode = metadata['darcy_forchheimer']['mode']
                return f'{version}（实验标定）' if mode == 'experimental' else version
    raise ValueError('Result metadata is missing the recorded darcy_forchheimer model reference')


def extrapolation_watermark(metadata: dict | None, reasons, *, multiline: bool = False) -> str:
    """Build figure watermark text from the recorded run model and reasons."""
    items = list(dict.fromkeys(str(reason) for reason in (reasons or ()) if reason))
    if not items:
        return ''
    prefix = f'⚠ {extrapolation_model_label(metadata)} 外推'
    if multiline:
        short = [item.split(' (')[0].rstrip('.') for item in items]
        return prefix + '\n' + '\n'.join(short)
    return prefix + '：' + ' | '.join(items)


def display_fields_2d(temperature, pressure, velocity):
    """Keep display aliases at the original cell values."""
    fields = dict(zip(('Ta_display', 'Tb_display', 'Ts_display'), temperature))
    for side, label in enumerate('AB'):
        fields.update({'P_f' + label + '_display': pressure[side],
                       'uc' + label: velocity[side][0], 'vc' + label: velocity[side][1]})
    return fields


def describe_fields(fields, dimension):
    """Return the existing units, axes and states for 2D or 3D fields."""
    metadata = {}
    axes = ('x', 'y') if dimension == 2 else ('x', 'y', 'z')
    for key in fields:
        unit = ('K' if key.startswith(('Ta', 'Tb', 'Ts')) else
                'Pa' if key.startswith('P_') else
                'W/(m3 K)' if key.startswith('h_v') else
                'W/(m K)' if key == 'K_ss' else
                'm/s' if dimension == 2 or key.startswith(('uc', 'vc', 'wc', 'vmag_')) else
                'W/(m K)')
        if key.endswith('_display'):
            state = 'display'
        elif dimension == 2:
            state = ('last thermal input' if key.startswith(('P_thermal', 'h_v')) or key == 'K_ss' else
                     'final flow/report' if key.startswith(('P_report', 'uc', 'vc')) else
                     'raw last main thermal return')
        else:
            state = ('final flow/report' if key.startswith(('uc', 'vc', 'wc', 'vmag_')) else
                     'final SIMPLE flow' if key.startswith(('P_report', 'P_gauge')) else
                     'last thermal solve')
        metadata[key] = dict(unit=unit, axes=axes, location='cell', state=state)
    return metadata


def zone_statistics_2d(z_axis, zone_config, za, L, H,
                       energy_dx, energy_dy, Ta, Tb, Ts):
    """Return area-weighted zone statistics and physical boundary positions."""
    if zone_config is None or za is None:
        return None
    if z_axis == 'continuous':
        return dict(axis_dir=z_axis, boundaries=[], boundaries_x=[], boundaries_y=[], stats=[])
    from sjtu_tpmshx.physical_models.zone_config import Zone, compute_zone_statistics
    from sjtu_tpmshx.cpp_interface._native_result_metrics import capture_area_weights
    zones = dict(axis_dir=z_axis)
    if z_axis == 'grid':
        zones.update(boundaries=[], boundaries_x=[b * L for b in za.get('x_bounds', [])],
                     boundaries_y=[b * H for b in za.get('y_bounds', [])])
        definitions = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                       for r, gc in enumerate(za.get('grid_cells', []))]
    else:
        definitions = zone_config.zones
        zones.update(boundaries_x=None, boundaries_y=None,
                     boundaries=[z.y_frac_end * (H if z_axis == 'y' else L)
                                 for z in definitions[:-1]])
    zones['stats'] = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'], definitions,
        cell_area=capture_area_weights(energy_dx, energy_dy))
    from sjtu_tpmshx.run_control.logutil import log_zone_report
    log_zone_report(zones['stats'])
    return zones
