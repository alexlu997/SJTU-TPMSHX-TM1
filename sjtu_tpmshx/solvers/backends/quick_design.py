"""Prepared Quick Design validation and FieldResult mapping shared by backends."""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.persistence_validation import validate_grid
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.catalog import resolve_model


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
    model = resolve_model(case.model_refs[0])
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
    return shape, p, op, model, widths, fixed


def field_result(case, fields, props_a, props_b, u_a, u_b, pass_info, *,
                 backend_id, native_metadata=None):
    op = SimpleNamespace(**case.parameters['operating_point'])
    fractions = case.parameters['inlet_pressure_fractions']
    dph, dpc = fractions['A'], fractions['B']
    units = {**{k: 'K' for k in ('Ta', 'Tb', 'Ts')},
             **{k: 'm/s' for k in ('ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB')},
             **{k: 'W/(m K)' for k in ('K_ffA', 'K_ffB', 'K_ss')},
             'h_vA': 'W/(m3 K)', 'h_vB': 'W/(m3 K)', 'eps': '1'}
    pressure = {side: dict(inlet_absolute_Pa=pin, outlet_absolute_Pa=pin * (1. - fraction),
                           model='inlet_state_analytic_df', choked=bool(fraction >= 1.))
                for side, pin, fraction in (('A', op.P_in_h, dph), ('B', op.P_in_c, dpc))}
    converged = bool(pass_info[-1]['converged'])
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id, backend_id=backend_id,
        backend_version='quick_design_v1', grid=case.grid, fields=fields,
        field_metadata={key: dict(unit=units[key], axes=('x', 'y', 'z'), location='cell',
                                  state='last quick-design thermal pass') for key in fields},
        pressure_evidence=pressure,
        boundary_fluxes={side: dict(mass_flow_kg_s=mdot, inlet_temperature_K=tin,
                                    cp_J_kgK=props.cp, velocity_m_s=speed, density_kg_m3=props.rho)
                         for side, mdot, tin, props, speed in
                         (('A', op.mdot_h, op.T_in_h, props_a, u_a), ('B', op.mdot_c, op.T_in_c, props_b, u_b))},
        model_refs=case.model_refs,
        run_status=dict(execution='completed', converged=converged, screening=True,
                        physical_validation='not_established', passes=pass_info),
        metadata=dict(mode='quick_design', dimension=3, quantity_basis='total',
                      model=case.metadata['model'], parameters=case.parameters,
                      properties={'A': asdict(props_a), 'B': asdict(props_b)},
                      **({} if native_metadata is None else {'native': native_metadata}),
                      diagnostics={'warnings_list': ([] if converged else ['Quick-design thermal solve did not converge.'])},
                      applicability=case.metadata['applicability']))
