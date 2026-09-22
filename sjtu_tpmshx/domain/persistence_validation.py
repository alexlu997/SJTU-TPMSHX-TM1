"""Physical schema checks at portable file trust boundaries."""
import numpy as np


def validate_grid(grid):
    dimension = grid.get('dimension')
    if dimension not in (2, 3) or grid.get('length_unit') != 'm':
        raise ValueError('persisted physical grid requires dimension 2/3 and length unit m')
    axes = tuple('xyz'[:dimension])
    if tuple(grid.get('axis_order', ())) != axes:
        raise ValueError('persisted physical grid axis order is invalid')
    shape = []
    for axis in axes:
        widths = np.asarray(grid['d' + axis])
        if widths.dtype.kind not in 'fiu' or widths.ndim != 1 or not len(widths) or not np.all(np.isfinite(widths) & (widths > 0)):
            raise ValueError(f'invalid {axis} grid widths')
        if not np.array_equal(np.r_[0., np.cumsum(widths)], grid[axis + '_edges']):
            raise ValueError(f'inconsistent {axis} grid edges')
        shape.append(len(widths))
    return tuple(shape)


def validate_thermal_geometry(data, shape):
    def check_geometry(geometry, expected):
        for key in ('A_0', 'D_h', 'epsilon'):
            value = np.asarray(geometry[key])
            if value.shape != expected or not np.all(np.isfinite(value) & (value > 0)):
                raise ValueError(f'invalid prepared thermal geometry {key}')
            if key == 'epsilon' and not np.all(value < 1):
                raise ValueError('prepared thermal porosity must be below one')
    check_geometry(data['uniform'], ())
    if data['fields'] is not None:
        check_geometry(data['fields'], shape)
    split = data['split_A']
    if not np.isscalar(split) or not np.isfinite(split) or not 0 < split < 1:
        raise ValueError('invalid prepared thermal side split')
    sides = data['side_geometry']
    if sides is not None:
        if set(sides) != {'A', 'B'}:
            raise ValueError('prepared asymmetric geometry requires both sides')
        for values in sides.values():
            values = np.asarray(values)
            if values.shape != (4,) or not np.all(np.isfinite(values) & (values > 0)):
                raise ValueError('invalid prepared asymmetric geometry')
    # Historical cases may contain these unused initial fields. New preparation
    # omits them; keep validating archived fields when they are present.
    for values in data.get('air_bulk_hv', {}).values():
        values = np.asarray(values)
        if values.shape != shape or not np.all(np.isfinite(values) & (values >= 0)):
            raise ValueError('invalid prepared bulk heat transfer field')


def validate_case(case):
    shape = validate_grid(case.grid)
    if "thermal_geometry" in case.parameters:
        validate_thermal_geometry(case.parameters["thermal_geometry"], shape)
    for key, value in case.design_fields.items():
        if isinstance(value, np.ndarray) and value.ndim and value.shape != shape:
            raise ValueError(f'design field {key} shape disagrees with grid')
    return case


def validate_result_declarations(result):
    """Reject contradictory declared physics, including direct metric inputs."""
    dimension = result.grid.get('dimension', result.metadata.get('dimension'))
    if result.metadata.get('dimension', dimension) != dimension:
        raise ValueError('result metadata dimension disagrees with grid')
    mode_dimension = {'screening_2d': 2, 'screening_3d': 3, 'quick_design': 3}
    if mode_dimension.get(result.metadata.get('mode'), dimension) != dimension:
        raise ValueError('result mode dimension disagrees with grid')
    for key, metadata in result.field_metadata.items():
        name = key.removesuffix('_display')
        units = (('K',) if name in ('Ta', 'Tb', 'Ts') else
                 ('Pa',) if name.startswith('P_') else
                 ('m/s',) if name in ('ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB') else
                 ('W/(m3 K)', 'W/(m^3 K)') if name.startswith('h_v') else
                 ('W/(m K)',) if name in ('K_ss', 'K_ss_arr', 'K_ffA_arr', 'K_ffB_arr') else
                 ('1',) if name == 'eps_arr' else None)
        if units is not None and metadata.get('unit') not in units:
            raise ValueError(f'field {key} unit must be one of {units}')


def validate_result(result):
    shape = validate_grid(result.grid)
    validate_result_declarations(result)
    execution = result.run_status.get('execution')
    if execution not in ('completed', 'rejected'):
        raise ValueError('not a completed or explicitly rejected result archive')
    if execution == 'rejected' and (result.run_status.get('converged') is not False
                                    or not result.run_status.get('reason')
                                    or result.run_status.get('rejection_stage') not in ('pre_solve', 'initial_flow', 'hot_reseed', 'post_solve_envelope')):
        raise ValueError('rejected result requires a reason, stage and false convergence flag')
    if not isinstance(result.run_status.get('converged'), bool):
        raise ValueError('result requires an explicit numerical convergence flag')
    if set(result.fields) != set(result.field_metadata):
        raise ValueError('every field must have unit, axes and state metadata')
    for key, value in result.fields.items():
        metadata = result.field_metadata[key]
        if not metadata.get('unit') or not metadata.get('state') or metadata.get('location') != 'cell':
            raise ValueError(f'field {key} metadata is incomplete')
        if tuple(metadata.get('axes', ())) != tuple(result.grid['axis_order']):
            raise ValueError(f'field {key} axes disagree with grid')
        if np.shape(value) != shape:
            raise ValueError(f'field {key} shape disagrees with grid')
    return result
