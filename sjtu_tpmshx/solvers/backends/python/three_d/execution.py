"""Execute prepared 3D physical data without running preprocessing."""
import numpy as np

from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.catalog import resolve_model


def build_execution_inputs(case):
    if case.grid.get('dimension') != 3 or case.grid.get('length_unit') != 'm':
        raise ValueError('3D execution requires a prepared SI grid')
    cfg = mutable_data(case.parameters)
    prepared = cfg.pop('prepared')
    for axis, length_key in zip('xyz', ('L', 'H', 'Lz')):
        widths = np.asarray(case.grid['d' + axis], dtype=float).copy()
        if widths.ndim != 1 or not len(widths) or not np.all(np.isfinite(widths) & (widths > 0)):
            raise ValueError(f'invalid prepared {axis} cell widths')
        edges = np.r_[0., np.cumsum(widths)]
        if not np.isclose(edges[-1], cfg[length_key], rtol=1e-12, atol=1e-15):
            raise ValueError(f'prepared {axis} grid does not cover the physical domain')
        if not np.array_equal(edges, case.grid[axis + '_edges']):
            raise ValueError(f'prepared {axis} widths and edges disagree')
        if prepared['N' + axis] != len(widths):
            raise ValueError(f'prepared {axis} count and grid disagree')
        prepared['d' + axis] = widths
    shape = tuple(prepared['N' + axis] for axis in 'xyz')
    prepared['custom_grid'] = any(
        not np.all(prepared['d' + axis] == cfg[length] / count)
        for axis, length, count in zip('xyz', ('L', 'H', 'Lz'), shape))
    cfg['Lcell'] = cfg.pop('L_cell_m') * 1e3
    cfg['t_wall'] = cfg.pop('t_wall_m') * 1e3
    roles = case.metadata['model_roles']
    if set(roles) != {'fluid_A', 'fluid_B', 'geometry', 'darcy_forchheimer'} or sorted(roles.values()) != list(range(len(case.model_refs))):
        raise ValueError('3D model roles must account for every recorded resource')
    cfg['_models'] = {role: resolve_model(case.model_refs[index]) for role, index in roles.items()}
    for side in ('A', 'B'):
        ref = case.model_refs[roles['fluid_' + side]]
        if cfg['_models']['fluid_' + side].name != cfg['fluid_type_' + side]:
            raise ValueError(f'prepared fluid {side} and model resource disagree')
        if dict(ref.parameters['sco2_nu']) != cfg['sco2_nu']:
            raise ValueError(f'prepared Nu settings and fluid {side} resource disagree')
        axis = prepared['axes'].get(side)
        if axis is None:
            continue
        if cfg['fluid_' + side + '_cfg']['dir'] // 2 != axis['stream_real_axis']:
            raise ValueError(f'prepared fluid {side} direction and axis map disagree')
        for prefix, index_key in (('stream', 'stream_real_axis'), ('cross1', 'cross1_real_axis'), ('cross2', 'cross2_real_axis')):
            physical_axis = 'xyz'[axis[index_key]]
            if not np.array_equal(axis['d' + prefix], prepared['d' + physical_axis]):
                raise ValueError(f'prepared fluid {side} axis widths disagree with grid')
            if axis['N_' + prefix] != shape[axis[index_key]]:
                raise ValueError(f'prepared fluid {side} axis count disagrees with grid')
        init = axis['solver_init']
        for label, name in zip('xyz', ('cross1', 'stream', 'cross2')):
            if init['N' + label] != axis['N_' + name] or init['L' + label] != axis['L_' + name]:
                raise ValueError(f'prepared fluid {side} solver geometry and axis map disagree')
        if axis['is_reverse'] != bool(cfg['fluid_' + side + '_cfg']['dir'] % 2):
            raise ValueError(f'prepared fluid {side} reverse direction disagrees')
        for mask in prepared['openings'][side].values():
            if np.shape(mask) != (axis['N_cross1'], axis['N_cross2']) or not np.all(np.isfinite(mask) & (mask >= 0) & (mask <= 1)):
                raise ValueError(f'invalid prepared fluid {side} opening mask')
    if case.model_refs[roles['darcy_forchheimer']].parameters['topology'] != cfg['tpms_type']:
        raise ValueError('prepared topology and Darcy-Forchheimer resource disagree')
    cfg['sco2_nu'] = Sco2NuConfig(**cfg['sco2_nu'])
    if cfg.get('zone_grid_cells'):
        cfg['zone_grid_cells'] = [dict((('L' if key == 'L_m' else 't' if key == 't_m' else key),
                                       value * 1e3 if key in ('L_m', 't_m') else value)
                                      for key, value in cell.items()) for cell in cfg['zone_grid_cells']]
    design = mutable_data(case.design_fields)
    for key, value in design.items():
        arr = np.asarray(value)
        if arr.ndim and arr.shape != shape:
            raise ValueError(f'prepared design field {key} does not match the grid')
        if not np.all(np.isfinite(arr) & (arr > 0)):
            raise ValueError(f'prepared design field {key} must be finite and positive')
        if key.startswith('eps') and not np.all(arr < 1):
            raise ValueError(f'prepared porosity {key} must be below one')
    if case.metadata['design_mode'] == 'uniform':
        for key, scalar in (('L_field_m', cfg['Lcell'] * 1e-3),
                            ('t_field_m', cfg['t_wall'] * 1e-3), ('eps_arr', cfg['eps'])):
            if not np.all(np.asarray(design[key]) == scalar):
                raise ValueError(f'uniform design field {key} disagrees with scalar input')
        for key in ('K_m2', 'cF_per_m'):
            if not np.all(design[key] == design[key].flat[0]):
                raise ValueError(f'uniform design field {key} must be uniform')
    elif case.metadata['design_mode'] == 'xy_extruded':
        for key in ('L_field_m', 't_field_m', 'eps_arr', 'K_m2', 'cF_per_m'):
            if not np.all(design[key] == design[key][:, :, :1]):
                raise ValueError(f'3D design field {key} must be an xy extrusion')
    else:
        raise ValueError('unsupported prepared 3D design mode')
    prepared['design'] = design
    return cfg, prepared


def run_case(case, control=RunControl()):
    from . import runtime
    from .result_capture import capture_result
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    control.check_cancelled()
    cfg, prepared = build_execution_inputs(case)
    cfg['_capture_native'] = True
    cfg['_cancel_check'] = control.cancel_check
    cfg['_progress_cb'] = control.report_progress
    prob = runtime.build_problem(cfg, prepared)
    hv = runtime._build_hv_machinery(prob)
    outer = runtime._run_outer_coupling_3d(prob, hv)
    metrics = runtime._extract_3d_metrics(prob, hv, outer)
    raw = runtime._assemble_3d_verdict(prob, hv, outer, metrics)
    control.check_cancelled()
    result = capture_result(case, prob, outer, raw)
    control.report_progress(100)
    return result
