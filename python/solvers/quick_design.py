"""Run a saved Quick Design case and assemble its solver result."""
from collections.abc import Mapping
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.cpp_interface.quick_design import QuickSolver
from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.physical_models.fluid_props import Props, QuickDesignWaterFieldError, WaterStateError
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.run_warnings import current_warnings, range_context, record_sample


def _saved_case(case):
    from sjtu_tpmshx.data_types.persistence_validation import validate_grid
    from sjtu_tpmshx.model_configs.model_parameters import MODEL_VERSIONS

    shape = validate_grid(case.grid)
    if len(shape) != 3 or case.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise ValueError('unsupported quick-design physical model')
    p = case.parameters
    op = SimpleNamespace(**p['operating_point'])
    fractions = p.get('inlet_pressure_fractions')
    if not isinstance(fractions, Mapping) or set(fractions) != {'A', 'B'} or any(not np.isscalar(v) for v in fractions.values()):
        raise ValueError('quick-design requires prepared nonnegative inlet pressure fractions')
    if len(case.model_refs) != 3 or case.model_refs[0].name != 'quick_design':
        raise ValueError('quick-design model resources are incomplete')
    if case.model_refs[0].parameters:
        raise ValueError('quick-design closure takes no fixed parameters')
    for ref, fluid in zip(case.model_refs[1:], (op.hot_fluid, op.cold_fluid)):
        if ref.name != 'fluid' or dict(ref.parameters) != {'fluid': fluid}:
            raise ValueError('quick-design fluid resource disagrees with operating point')
    for ref in case.model_refs:
        if ref.version != MODEL_VERSIONS[ref.name]:
            raise ValueError(f'unknown model resource: {ref.name}@{ref.version}')
    fixed = case.design_fields
    if set(fixed) != {'eps', 'eps_A', 'K_ss'}:
        raise ValueError('unsupported quick-design fields')
    for name, field in fixed.items():
        array = np.asarray(field)
        if array.dtype.kind not in 'biuf':
            raise TypeError(f'quick-design {name} requires a real numeric field')
        if array.shape != shape or ((array.dtype.kind in 'iu' and array.itemsize >= 8 or array.itemsize > 8)
                                    and not np.all(array == array.flat[0])):
            raise ValueError(f'quick-design requires a finite uniform {name} field on its prepared grid')
    widths = tuple(np.asarray(case.grid['d' + axis]) for axis in 'xyz')
    for axis, width, length in zip('xyz', widths, (p['Lx'], p['s'], p['height'])):
        if not np.isclose(width.sum(), length, rtol=1e-12, atol=0.):
            raise ValueError(f'prepared {axis} grid disagrees with physical extent')
    return shape, p, op, widths, fixed


def _record_pass(records):
    for key, sample in records.items():
        if key[:2] == ('nu', 'sco2'):
            from sjtu_tpmshx.physical_models.nu_correlations import record_quick_sco2_pr_notice
            record_quick_sco2_pr_notice()
        record_sample(key, sample)


def _initial_fields(parameters, shape):
    """Read the warm start when the solver has bound the release function."""
    seed = parameters['initial_fields']
    if seed is None:
        return
    if len(seed) != 3 or any(np.shape(value) != shape for value in seed):
        raise ValueError('quick-design warm start disagrees with prepared grid')
    for value in seed:
        yield np.array(value, dtype=np.float64, order='C', copy=True)


def _saved_controls(parameters, check_native_size):
    settings = parameters['controls']
    if settings['maxit'] is None:
        raise ValueError('invalid quick-design numerical controls')
    for value in (settings['maxit'], settings['chunk']):
        if value is not None:
            if not isinstance(value, int) or value <= 0:
                raise ValueError('invalid quick-design numerical controls')
            check_native_size(value)
    if settings['dirB'] not in (1, 2):
        raise ValueError('quick-design flow direction disagrees with arrangement')
    return settings


def run_case(case, control):
    control.check_cancelled()
    if not control.native_library:
        raise ValueError('cpp requires RunControl.native_library for this host')
    solver = QuickSolver(control.native_library)
    shape, p, op, widths, fixed = _saved_case(case)
    pass_ranges = []
    try:
        output = solver.run(
            shape, p, op, widths, fixed, _initial_fields(p, shape), read_controls=_saved_controls,
            retained_fields={key: fixed[key] for key in ('K_ss', 'eps')},
            new_result_id=lambda: str(uuid4()), cancel=control.cancel_check, report_progress=control.report_progress,
            error_types={1: ValueError, 2: WaterStateError, 3: QuickDesignWaterFieldError,
                         4: FloatingPointError, 6: CancelledError},
            expected_passes=lambda: 2 if p['prop_model'] == 'mean' else 1,
            range_output=lambda: pass_ranges if current_warnings() is not None else None)
    finally:
        # Keep earlier observations if a later native range query fails.
        for records in pass_ranges:
            _record_pass(records)
    if not pass_ranges:
        from sjtu_tpmshx.physical_models.design_fluids import record_native_design_ranges
    pass_info = []
    for index, native_pass in enumerate(output.passes):
        pass_info.append(dict(converged=native_pass.stop == 0, iterations=native_pass.iterations,
                              residual=native_pass.residual, delegated_to_2d=shape[2] == 1))
        if not pass_ranges:
            stage = 'design-inlet-pass' if index == 0 else 'design-mean-pass'
            for side, fluid, evidence in zip(('A', 'B'), (op.hot_fluid, op.cold_fluid), native_pass.sides):
                with range_context(side=side, stage=stage, layout='scalar'):
                    record_native_design_ranges(fluid, p['topology'], evidence.evaluation_temperature, evidence.reynolds)
    a, b = output.passes[-1].sides
    props_a, props_b = (Props(s.rho, s.mu, s.k, s.cp, s.pr) for s in (a, b))
    pressure = {side: dict(inlet_absolute_Pa=inlet, outlet_absolute_Pa=outlet,
                           model='inlet_state_analytic_df', choked=choked)
                for side, (inlet, outlet, choked) in zip(('A', 'B'), output.pressure)}
    field_metadata = {name: dict(unit=unit, axes=('x', 'y', 'z'), location='cell', state=state)
                      for name, unit, state in output.declarations}
    return field_result(case, output.fields, props_a, props_b, a.speed, b.speed, pass_info,
                        field_metadata=field_metadata, result_id=output.result_id,
                        pressure=pressure, backend_id='cpp',
                        native_metadata=dict(solver_abi=solver.abi, capability='quick_design_v1',
                                             temperature_algorithm=output.algorithm))


def field_result(case, fields, props_a, props_b, u_a, u_b, pass_info, *,
                 pressure, backend_id, field_metadata, result_id, native_metadata=None):
    op = SimpleNamespace(**case.parameters['operating_point'])
    converged = bool(pass_info[-1]['converged'])
    return FieldResult(
        result_id=result_id, case_id=case.case_id, backend_id=backend_id,
        backend_version='quick_design_v1', grid=case.grid, fields=fields,
        field_metadata=field_metadata,
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
