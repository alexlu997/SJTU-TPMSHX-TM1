"""Run an already prepared 2D case; preprocessing is not an execution step."""

import numpy as np

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.portable_data import mutable_data as _mutable_data
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.models.catalog import resolve_model
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
from .runtime import build_runtime
from .coupling import _run_solvers


from sjtu_tpmshx.models.zone_units import _legacy_zone_units


def build_execution_inputs(case: CaseData):
    """Validate and detach the supplied data, without rebuilding a grid."""
    if case.grid.get('dimension') != 2 or case.grid.get('length_unit') != 'm':
        raise ValueError('2D execution requires a prepared SI grid')
    cfg = _mutable_data(case.parameters)
    missing = set(('thermal_geometry', 'flow_inputs')) - cfg.keys()
    if missing:
        raise ValueError(f'incomplete prepared 2D execution data: {sorted(missing)}')
    from sjtu_tpmshx.domain.persistence_validation import validate_thermal_geometry
    validate_thermal_geometry(cfg['thermal_geometry'],
                              tuple(len(case.grid['d' + axis]) for axis in 'xyz'[:case.grid['dimension']]))
    dx, dy = (np.asarray(case.grid[key], dtype=float).copy() for key in ('dx', 'dy'))
    for widths, axis, length in ((dx, 'x', cfg['L']), (dy, 'y', cfg['H'])):
        if widths.ndim != 1 or not len(widths) or not np.all(np.isfinite(widths) & (widths > 0)):
            raise ValueError(f'invalid prepared {axis} cell widths')
        expected = np.r_[0., np.cumsum(widths)]
        if not np.isclose(expected[-1], length, rtol=1e-12, atol=1e-15):
            raise ValueError(f'prepared {axis} grid does not cover the physical domain')
        if not np.array_equal(expected, case.grid[axis + '_edges']):
            raise ValueError(f'prepared {axis} widths and edges disagree')
    if set(cfg['flow_inputs']) != {'A', 'B'}:
        raise ValueError('prepared flow inputs require both physical sides')
    for side, flow in cfg['flow_inputs'].items():
        direction = cfg['cfg' + side]['dir']
        cross, stream = (dy, dx) if direction in (0, 1) else (dx, dy)
        if direction in (1, 3):
            stream = stream[::-1]
        if not np.array_equal(flow['dx'], cross) or not np.array_equal(flow['dy'], stream):
            raise ValueError(f'prepared flow {side} grid disagrees with the thermal grid')
        for key, positive in (('K_m2', True), ('cF_per_m', False)):
            values = np.asarray(flow[key])
            if (values.shape != stream.shape or not np.all(np.isfinite(values))
                    or np.any(values <= 0 if positive else values < 0)):
                raise ValueError(f'invalid prepared flow {side} {key}')
        for key, positive in (('seed_K_m2', True), ('seed_cF_per_m', False)):
            value = flow[key]
            if not np.isscalar(value) or not np.isfinite(value) or (value <= 0 if positive else value < 0):
                raise ValueError(f'invalid prepared flow {side} {key}')
    cfg['N_x'], cfg['N_y'] = len(dx), len(dy)
    cfg['Lcell'], cfg['t_wall'] = cfg.pop('L_cell_m') * 1e3, cfg.pop('t_wall_m') * 1e3
    run_settings = _legacy_zone_units(cfg.pop('run_settings'))
    cfg['compute_cfg'] = ComputeConfig.from_dict(run_settings)
    roles = case.metadata['model_roles']
    if set(roles) != {'fluid_A', 'fluid_B', 'geometry', 'darcy_forchheimer'} or sorted(roles.values()) != list(range(len(case.model_refs))):
        raise ValueError('2D model roles must account for every recorded resource')
    providers = {role: resolve_model(case.model_refs[index]) for role, index in roles.items()}
    for side in ('A', 'B'):
        model = providers['fluid_' + side]
        ref = case.model_refs[roles['fluid_' + side]]
        if dict(ref.parameters['sco2_nu']) != run_settings['sco2_nu']:
            raise ValueError(f'prepared Nu settings and fluid {side} resource disagree')
        if model.name != cfg['fluid_' + side]:
            raise ValueError(f'prepared fluid {side} and its model resource disagree')
    df_ref = case.model_refs[roles['darcy_forchheimer']]
    if df_ref.parameters['topology'] != cfg['tpms_type']:
        raise ValueError('prepared topology and Darcy-Forchheimer resource disagree')
    cfg['_models'] = providers
    cfg['_capture_native'] = True
    design = _legacy_zone_units(_mutable_data(case.design_fields))
    for key, value in design.items():
        if isinstance(value, np.ndarray) and value.ndim == 2:
            if value.shape != (len(dx), len(dy)) or not np.all(np.isfinite(value)):
                raise ValueError(f'prepared design field {key} does not match the physical grid')
    if case.metadata['design_mode'] == 'uniform':
        for field, scalar in (('eps_arr', cfg['eps']), ('r_h_arr', cfg['r_h']),
                              ('L_field', cfg['Lcell']), ('t_field', cfg['t_wall'])):
            if not np.all(np.asarray(design[field]) == scalar):
                raise ValueError(f'uniform design field {field} disagrees with its scalar input')
        cfg['eps'] = float(design['eps_arr'][0, 0])
        cfg['r_h'] = float(design['r_h_arr'][0, 0])
        solid = np.asarray(design['K_ss_arr'])
        if not np.all(solid == solid[0, 0]) or not np.all(solid > 0):
            raise ValueError('uniform solid conductivity must be positive and uniform')
        cfg['static_properties']['geometry']['K_ss'] = float(solid[0, 0])
        cfg['za'] = None
    else:
        cfg['za'] = design
    zone = _legacy_zone_units(cfg['zone_config'])
    if isinstance(zone, dict):
        zone['zones'] = [Zone(**item) for item in zone['zones']]
        zone = ZoneConfig(**zone)
    cfg['zone_config'] = zone
    prepared = dict(energy_dx=dx, energy_dy=dy,
                    _x_breaks=case.grid['x_breaks'], _y_breaks=case.grid['y_breaks'])
    return cfg, prepared


def run_case(case: CaseData, control: RunControl = RunControl()):
    """Execute only the numerical stages and capture portable raw evidence."""
    from .result_capture import capture_result
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    control.check_cancelled()
    cfg, prepared = build_execution_inputs(case)
    runtime = build_runtime(cfg, prepared, residual_cb=control.residual)
    raw = _run_solvers(cfg, runtime, control)
    control.check_cancelled()
    result = capture_result(case, raw)
    control.report_progress(100)
    return result
