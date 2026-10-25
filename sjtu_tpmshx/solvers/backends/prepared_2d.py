"""Validate prepared 2D inputs for native execution."""

import numpy as np

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.portable_data import mutable_data as _mutable_data
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.persistence_validation import validate_grid, validate_thermal_geometry
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
from .prepared_models import resolve_models, validate_fluid, validate_nu_settings, validate_topology


from sjtu_tpmshx.models.zone_units import _legacy_zone_units


def build_execution_inputs(case: CaseData, *, copy_design=True):
    if case.grid.get('dimension') != 2:
        raise ValueError('2D execution requires a prepared 2D grid')
    cfg = _mutable_data(case.parameters)
    missing = set(('thermal_geometry', 'flow_inputs')) - cfg.keys()
    if missing:
        raise ValueError(f'incomplete prepared 2D execution data: {sorted(missing)}')
    shape = validate_grid(case.grid)
    validate_thermal_geometry(cfg['thermal_geometry'], shape)
    dx, dy = (np.asarray(case.grid[key], dtype=float).copy() for key in ('dx', 'dy'))
    for widths, axis, length in ((dx, 'x', cfg['L']), (dy, 'y', cfg['H'])):
        if not np.isclose(np.cumsum(widths)[-1], length, rtol=1e-12, atol=1e-15):
            raise ValueError(f'prepared {axis} grid does not cover the physical domain')
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
        if case.metadata['design_mode'] == 'continuous':
            for key, positive in (('K_field_m2', True), ('cF_field_per_m', False)):
                values = np.asarray(flow.get(key))
                if (values.shape != (len(cross), len(stream)) or not np.all(np.isfinite(values))
                        or np.any(values <= 0 if positive else values < 0)):
                    raise ValueError(f'invalid prepared local flow {side} {key}')
    cfg['N_x'], cfg['N_y'] = len(dx), len(dy)
    cfg['Lcell'], cfg['t_wall'] = cfg.pop('L_cell_m') * 1e3, cfg.pop('t_wall_m') * 1e3
    run_settings = _legacy_zone_units(cfg.pop('run_settings'))
    if case.metadata['design_mode'] == 'continuous':
        run_settings['zones'] = dict(enabled=True, axis='continuous', config=cfg['continuous_field'])
    cfg['compute_cfg'] = ComputeConfig.from_dict(run_settings, prepared_grid=True)
    providers = resolve_models(case)
    for side in ('A', 'B'):
        validate_nu_settings(case, side, run_settings['sco2_nu'])
        validate_fluid(case, providers, side, cfg['fluid_' + side])
    validate_topology(case, cfg['tpms_type'])
    cfg['_models'] = providers
    design = _legacy_zone_units({
        key: value if not copy_design and isinstance(value, np.ndarray) else _mutable_data(value)
        for key, value in case.design_fields.items()})
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
        for field in ('L_field', 't_field'):
            values = np.asarray(design.get(field))
            if (values.shape != (len(dx), len(dy))
                    or not np.all(np.isfinite(values) & (values > 0))):
                raise ValueError(
                    f'prepared zoned 2D case requires a positive {field}; '
                    'prepare the original configuration again')
        if cfg['thermal_geometry']['fields'] is None:
            raise ValueError(
                'prepared zoned 2D case requires per-cell thermal geometry; '
                'prepare the original configuration again')
        cfg['za'] = design
    zone = _legacy_zone_units(cfg['zone_config'])
    if isinstance(zone, dict):
        zone['zones'] = [Zone(**item) for item in zone['zones']]
        zone = ZoneConfig(**zone)
    cfg['zone_config'] = zone
    prepared = dict(energy_dx=dx, energy_dy=dy)
    from sjtu_tpmshx.solvers.execution_record import resolved_input_record
    cfg['_input_resolution'] = resolved_input_record(
        case, cfg['_models'], shape, {side: cfg['cfg' + side]['dir'] for side in ('A', 'B')})
    return cfg, prepared
