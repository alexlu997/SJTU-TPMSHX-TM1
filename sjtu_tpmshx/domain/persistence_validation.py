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


def validate_case(case):
    shape = validate_grid(case.grid)
    for key, value in case.design_fields.items():
        if isinstance(value, np.ndarray) and value.ndim and value.shape != shape:
            raise ValueError(f'design field {key} shape disagrees with grid')
    return case


def validate_result(result):
    shape = validate_grid(result.grid)
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
