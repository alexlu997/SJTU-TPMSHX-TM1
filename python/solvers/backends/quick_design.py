"""Prepared-case validation for the original Quick Design stage ABI."""
from types import SimpleNamespace

import numpy as np

from sjtu_tpmshx.data_types.persistence_validation import validate_grid
from sjtu_tpmshx.data_types.portable_data import mutable_data
from sjtu_tpmshx.physical_models.catalog import resolve_model


def prepared_input(case):
    shape = validate_grid(case.grid)
    if len(shape) != 3 or case.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise ValueError('unsupported quick-design physical model')
    p = mutable_data(case.parameters)
    fractions = p.get('inlet_pressure_fractions')
    if (not isinstance(fractions, dict) or set(fractions) != {'A', 'B'}
            or any(not np.isscalar(value) or not np.isfinite(value) or value < 0
                   for value in fractions.values())):
        raise ValueError('quick-design requires prepared nonnegative inlet pressure fractions')
    op = SimpleNamespace(**p['operating_point'])
    if len(case.model_refs) != 3 or case.model_refs[0].name != 'quick_design':
        raise ValueError('quick-design model resources are incomplete')
    resolve_model(case.model_refs[0])
    for ref, fluid in zip(case.model_refs[1:], (op.hot_fluid, op.cold_fluid)):
        if ref.name != 'fluid' or dict(ref.parameters) != {'fluid': fluid}:
            raise ValueError('quick-design fluid resource disagrees with operating point')
        resolve_model(ref)
    if p['arrangement'] not in ('cross', 'counter') or p['prop_model'] not in ('const', 'mean'):
        raise ValueError('unsupported quick-design arrangement or property model')
    if p['controls']['dirB'] != (2 if p['arrangement'] == 'cross' else 1):
        raise ValueError('quick-design flow direction disagrees with arrangement')
    widths = tuple(np.asarray(case.grid['d' + axis]) for axis in 'xyz')
    for axis, width, length in zip('xyz', widths, (p['Lx'], p['s'], p['height'])):
        if not np.isclose(width.sum(), length, rtol=1e-12, atol=0.):
            raise ValueError(f'prepared {axis} grid disagrees with physical extent')
    fixed = mutable_data(case.design_fields)
    if set(fixed) != {'eps', 'eps_A', 'K_ss'}:
        raise ValueError('unsupported quick-design fields')
    for name, value in fixed.items():
        if np.shape(value) != shape or not np.all(np.isfinite(value)) or not np.all(value == value.flat[0]):
            raise ValueError(f'quick-design requires a finite uniform {name} field on its prepared grid')
    eps = float(fixed['eps'].flat[0]); eps_a = float(fixed['eps_A'].flat[0])
    if not 0 < eps < 1 or not np.isclose(eps_a, eps / 2, rtol=1e-12, atol=0.) or np.any(fixed['K_ss'] <= 0):
        raise ValueError('quick-design requires positive symmetric porosity and solid conduction')
    for name in ('tol', 'A_0', 'D_h'):
        if not np.isfinite(p[name]) or p[name] <= 0:
            raise ValueError(f'quick-design {name} must be finite and positive')
    arr = p['controls']
    if (not isinstance(arr['maxit'], int) or arr['maxit'] <= 0
            or not 0 < arr['alpha'] <= 1
            or (arr['qtol'] is not None and (not np.isfinite(arr['qtol']) or arr['qtol'] <= 0))
            or (arr['chunk'] is not None and (not isinstance(arr['chunk'], int) or arr['chunk'] <= 0))):
        raise ValueError('invalid quick-design numerical controls')
    return shape, p, op, widths, fixed
