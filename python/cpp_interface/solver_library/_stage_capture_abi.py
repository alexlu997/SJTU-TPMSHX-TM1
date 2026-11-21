"""Borrowed records from a completed native 2D or 3D stage."""

import ctypes as ct

import numpy as np

from sjtu_tpmshx.data_types.case_data import resolved_input_record
from .._df_abi import DragSummary
from .closure_evidence import RangeObservation
from ._thermal_abi import _Acceleration, _ENERGY_NAMES, _EnergyUpdateScale, _IterationRecords
from .temperature_evidence import TemperatureEvidence


class _Sample(ct.Structure):
    _fields_ = [('side', ct.c_uint32), ('outer_index', ct.c_int64)]
    _fields_ += [(name, ct.c_char_p) for name in
                ('stage', 'quantity', 'provider', 'temperature', 'pressure', 'operation')]


class _Sampling(ct.Structure):
    _fields_ = [('records', ct.POINTER(_Sample)), ('count', ct.c_size_t)]


class RangeRecordView(ct.Structure):
    _fields_ = [('sample', ct.POINTER(RangeObservation)), ('label', ct.c_char_p),
                ('quantity', ct.c_char_p), ('unit', ct.c_char_p), ('source_count', ct.c_size_t),
                ('minimum_index', ct.c_size_t * 3), ('maximum_index', ct.c_size_t * 3)]


class EnergyRelation(ct.Structure):
    _fields_ = [(name, ct.c_char_p) for name in ('relation', 'provider', 'state_update', 'eos_fluid')]
    _fields_ += [('solved', ct.c_uint32)]


class StageRecords(ct.Structure):
    _fields_ = [('sampling', _Sampling), ('observations', ct.POINTER(RangeRecordView)),
                ('last', ct.POINTER(RangeRecordView)), ('observation_count', ct.c_size_t), ('last_count', ct.c_size_t),
                ('temperature', ct.POINTER(TemperatureEvidence) * 2), ('simple_stop', ct.c_char_p * 2),
                ('energy', EnergyRelation * 2), ('transient_failures', ct.POINTER(ct.c_char_p)),
                ('final_failures', ct.POINTER(ct.c_char_p)), ('transient_count', ct.c_size_t),
                ('final_count', ct.c_size_t), ('base_drag', DragSummary * 2), ('applied_drag', (DragSummary * 2) * 2),
                ('thermal_history_converged', ct.c_uint32)]


class StageExecution(ct.Structure):
    _fields_ = [('records', ct.POINTER(StageRecords)),
                ('update_scale', _EnergyUpdateScale), ('model_h', _IterationRecords),
                ('acceleration', ct.POINTER(_Acceleration)), ('last_main_model_h', ct.c_size_t),
                ('unknown', ct.c_char_p), ('algorithm', ct.c_char_p), ('sco2_notices', ct.c_char_p * 2),
                ('red_black', ct.c_uint32)]


def execution_facts(executed, evidence, case, declarations, iterations, energy):
    """Detach the executed states before the solver releases its result."""
    if executed.last_main_model_h < executed.model_h.count:
        settings = iterations['records'][executed.last_main_model_h]['settings']
    else:
        settings = {} if energy is None else energy['effective_settings']
    thermal = dict(thermal_mode=evidence.thermal_mode.decode(), unknown=executed.unknown.decode(),
                   temperature_transport=evidence.temperature_transport.decode() if evidence.temperature_transport else None,
                   effective_settings=settings)
    states = dict(thermal_state=declarations['Ta']['state'], mass_state=evidence.thermal_state.decode(),
                  pressure_report_states={side: declarations['P_report_' + side]['state']
                                          for side, pressure in zip('AB', evidence.pressure) if pressure},
                  outer_index=evidence.outer_index[0])
    return dict(version=evidence.execution_version.decode(), dimension=evidence.dimension,
                sides=execution_sides(executed.records.contents, evidence, case, declarations),
                thermal=thermal, evidence=states)


def stage_records(library, result):
    query = getattr(library, f'tpmshx_stage_run_{result.evidence.dimension}d_records_v1', None)
    if query is None:
        return None
    query.argtypes, query.restype = [ct.POINTER(type(result))], ct.POINTER(StageRecords)
    records = query(ct.byref(result))
    if not records:
        raise RuntimeError('native stage returned no result records')
    return records.contents


def sampling_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_property_sampling_v1')
    except AttributeError as exc:
        raise ValueError('native library lacks property sampling records; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(_Sampling)]
    query.restype = ct.c_int
    return query


def copy_sampling(query, result):
    view = _Sampling()
    if query(ct.byref(result), ct.byref(view)):
        raise RuntimeError('native property sampling query failed')
    return sampling_records(view)


def sampling_records(view):
    records = []
    for sample in view.records[:view.count] if view.count else ():
        row = dict(side='AB'[sample.side], outer_index=sample.outer_index)
        for name, _ in sample._fields_[2:]:
            value = getattr(sample, name)
            row[name] = value.decode('ascii') if value is not None else None
        records.append(row)
    return records


def executed_inputs(case, evidence):
    shape = tuple(width.contents.shape[0] for width in evidence.grid.widths[:evidence.dimension])
    directions = evidence.direction if evidence.dimension == 2 else evidence.thermal.report_direction
    fluids = {side.side.decode(): side.fluid.decode()
              for side in evidence.executed_sides[:evidence.executed_side_count]}
    return resolved_input_record(case, fluids, shape,
        {side: direction[0] for side, direction, active in zip('AB', directions, evidence.active_fluids) if active})


def execution_sides(records, evidence, case, declarations):
    roles = case.metadata['model_roles']
    sides = {}
    for index, row in enumerate(records.energy):
        side = evidence.executed_sides[index].side.decode()
        model = roles['fluid_' + side]
        energy = dict(relation=row.relation.decode(), property_provider=row.provider.decode() if row.provider else None,
                      model_ref=model if row.solved and not row.eos_fluid else None, temperature_field=('Ta', 'Tb')[index])
        evaluation = dict(state_update=row.state_update.decode() if row.state_update else None)
        if row.eos_fluid:
            field = 'P_thermal_' + side
            energy.update(fluid=row.eos_fluid.decode(), pressure_field=field, pressure_state=declarations[field]['state'])
            evaluation['final_property_backend'] = 'HEOS'
        sides[side] = dict(fluid=evidence.executed_sides[index].fluid.decode(), solved=bool(row.solved),
                           flow_and_exchange_model_ref=model, energy=energy, property_evaluation=evaluation)
    return sides


def _update_scale_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_energy_update_scale_v1')
    except AttributeError as error:
        raise ValueError('native library lacks energy update scales; rebuild the library') from error
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(_EnergyUpdateScale)]
    query.restype = ct.c_int
    return query


def _copy_update_scale(query, result):
    scale = _EnergyUpdateScale()
    if query(ct.byref(result), ct.byref(scale)):
        raise RuntimeError('native energy update scale query failed')
    return _decode_update_scale(scale)


def _decode_update_scale(scale):
    if scale.available == 0:
        return None
    if scale.available != 1 or scale.reference_independent not in (0, 1):
        raise RuntimeError('native energy update scale has invalid flags')
    if any(not np.isfinite(value) or value < 1 for value in scale.scale):
        raise RuntimeError('native energy update scale must be finite and at least 1 J/kg')
    return dict(definition=('inlet_cp_times_temperature_difference_v1'
                            if scale.reference_independent else 'inlet_enthalpy_difference_v1'),
                unit='J/kg', sides=dict(zip('AB', scale.scale)),
                source='native_completed_thermal_call')


def _result_info(result, *, update_tol, coupled_energy_tol, equation_energy_tol,
                 max_iterations, sweeps, omega, abi=1):
    """Detach the common scalar audit returned by each complete true-h driver."""
    info = dict(iterations=result.iterations, converged=result.stop == 0,
        residual=result.residual, enthalpy_mode=True, Q_A=result.q_a, Q_B=result.q_b,
        energy_imbalance_rel=result.energy_imbalance,
        exit_reason=('converged', 'enthalpy_limited', 'iteration_limit', 'cancelled')[result.stop],
        enthalpy_clip_counts=dict(total=list(result.total_clips), last=list(result.last_clips)),
        effective_settings=dict(update_tol=float(update_tol), coupled_energy_tol=coupled_energy_tol,
            equation_energy_tol=equation_energy_tol, max_iterations=max_iterations, sweeps=sweeps,
            omega=float(omega), sweep_kernel='cpp', energy_audit='cpp', thermal_driver='cpp', driver_abi=abi))
    if result.audit_available:
        a = result.audit
        info['coupled_energy_balance'] = dict(net=a.net, solid_abs_sum=a.solid_abs_sum,
                                             denominator=a.denominator, ratio=a.coupled_ratio)
        if a.fluid_equations_computed:
            info['equation_energy_balance'] = dict(fluid_abs_sum=list(a.fluid_abs_sum),
                fluid_cell_max=list(a.fluid_cell_max), solid_abs_sum=a.solid_abs_sum,
                denominator=a.denominator, ratio=a.equation_ratio)
    return info


def _executed_energy_settings(info, actual, abi):
    if actual.available != 1 or actual.algorithm not in range(len(_ENERGY_NAMES)):
        raise RuntimeError('native full driver omitted executed thermal settings')
    info['effective_settings'].update(
        update_tol=actual.update_tolerance,
        coupled_energy_tol=actual.coupled_energy_tolerance,
        equation_energy_tol=actual.equation_energy_tolerance,
        max_iterations=actual.max_iterations, sweeps=actual.sweeps, omega=actual.omega,
        energy_algorithm=_ENERGY_NAMES[actual.algorithm],
        require_enthalpy_update_on_temperature=bool(actual.require_enthalpy_update_on_temperature),
        effective_settings_source='native_completed_thermal_call', driver_abi=abi)
    if actual.algorithm:
        info['effective_settings']['temperature_update_tol_K'] = actual.temperature_update_tolerance


def _full_enthalpy_info(result, actual, abi):
    info = _result_info(result, update_tol=actual.update_tolerance,
        coupled_energy_tol=actual.coupled_energy_tolerance, equation_energy_tol=actual.equation_energy_tolerance,
        max_iterations=actual.max_iterations, sweeps=actual.sweeps, omega=actual.omega, abi=abi)
    _executed_energy_settings(info, actual, abi)
    return info


def _energy_result_info(info, result, *, temperature_tol, abi, version_query=None, version=None,
                        state_update='HEOS_PT'):
    """Decode executed native identity, independently of the requested option."""
    if result.algorithm not in range(len(_ENERGY_NAMES)):
        raise RuntimeError('native energy returned an unknown algorithm')
    name = _ENERGY_NAMES[result.algorithm]
    if name == 'legacy_h_fou' or result.has_temperature_update != 1:
        raise RuntimeError('native candidate energy omitted its executed state')
    if not np.isfinite(result.temperature_update) or result.temperature_update < 0:
        raise RuntimeError('native energy returned an invalid temperature update')
    if not np.isfinite(result.picard_relaxation) or not 0 < result.picard_relaxation <= 1:
        raise RuntimeError('native energy returned an invalid Picard relaxation')
    if version is None:
        version = version_query(result.algorithm)
    if type(version) is not int or version not in ((1,) if result.algorithm == 1 else (1, 2)):
        raise RuntimeError('native energy returned an unsupported algorithm version')
    info.update(energy_algorithm=name, energy_algorithm_version=version,
                temperature_update_K=result.temperature_update)
    info['effective_settings'].update(energy_algorithm=name, energy_algorithm_version=version,
        temperature_update_tol_K=float(temperature_tol), driver_abi=abi,
        picard_relaxation=result.picard_relaxation,
        nonlinear_state_update=state_update,
        enthalpy_face_reconstruction='FOU' if result.algorithm == 1 else 'h_minmod_outlet_v1',
        solid_omega=info['effective_settings']['omega'] if result.algorithm == 1 else 1.)
    return info


def _energy_native_state(info, evidence, shape, units):
    """Copy native face powers; never reconstruct SOU in the Python binding."""
    if evidence.available != 1:
        raise RuntimeError('native energy omitted final boundary evidence')
    def copy(value, expected):
        return np.ctypeslib.as_array(value.data, (value.size,)).copy().reshape(expected)
    planes = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
    boundary = {}
    state = info['_native_state']
    for side, label in enumerate('AB'):
        boundary[label] = {name: copy(evidence.boundary_power[side][index],
            tuple(n for axis, n in enumerate(shape) if axis != index // 2))
            for index, name in enumerate(planes)}
        state['actual_conductivity_' + label] = copy(evidence.actual_conductivity[side], shape)
    state.update(energy_algorithm=info['energy_algorithm'], energy_algorithm_version=info['energy_algorithm_version'],
                 boundary_power=boundary, boundary_power_units=units, physical_boundary_complete=True)


def _iteration_query(library, dimension, result_type):
    try:
        query = getattr(library, f'tpmshx_full_{dimension}d_get_model_h_iterations_v1')
    except AttributeError as exc:
        raise ValueError('native library lacks model-h iteration records; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.POINTER(_IterationRecords)]
    query.restype = ct.c_int
    return query


def _acceleration_query(library, result_type):
    try:
        query = library.tpmshx_full_3d_get_model_h_acceleration_v1
    except AttributeError as exc:
        raise ValueError('native library lacks model-h acceleration records; rebuild the library') from exc
    query.argtypes = [ct.POINTER(result_type), ct.c_size_t, ct.POINTER(_Acceleration)]
    query.restype = ct.c_int
    return query


def _copy_iteration_records(query, result, acceleration_query=None):
    view = _IterationRecords()
    if query(ct.byref(result), ct.byref(view)):
        raise RuntimeError('native model-h iteration query failed')
    return _decode_iteration_records(view, acceleration_query=acceleration_query, result=result)


def _decode_iteration_records(view, acceleration=None, *, acceleration_query=None, result=None):
    if view.count and not view.records:
        raise RuntimeError('native model-h iteration records are missing')
    records = []
    for index in range(view.count):
        row = view.records[index]
        if (row.refined not in (0, 1) or not row.max_iterations or not row.chunk_iterations
                or row.total_iteration_budget < row.max_iterations
                or not np.isfinite(row.temperature_tolerance) or row.temperature_tolerance <= 0.
                or not np.isfinite(row.q_relative_tolerance) or row.q_relative_tolerance < 0.):
            raise RuntimeError('invalid native model-h iteration record')
        records.append(dict(outer_index=row.outer_index, attempt=row.attempt,
            stage='refined_thermal' if row.refined else 'outer_thermal',
            settings=dict(max_iterations=row.max_iterations, chunk_iterations=row.chunk_iterations,
                          temperature_update_tolerance_K=row.temperature_tolerance,
                          q_relative_tolerance=row.q_relative_tolerance,
                          total_iteration_budget=row.total_iteration_budget)))
        if acceleration is not None or acceleration_query is not None:
            if acceleration is not None:
                policy = acceleration[index]
            else:
                policy = _Acceleration()
                if acceleration_query(ct.byref(result), index, ct.byref(policy)):
                    raise RuntimeError('native model-h acceleration query failed')
            if policy.enabled not in (0, 1) or not policy.sweeps_per_block or policy.history_limit < 2:
                raise RuntimeError('invalid native model-h acceleration record')
            records[-1]['settings']['acceleration'] = dict(enabled=bool(policy.enabled),
                sweeps_per_block=policy.sweeps_per_block, history_limit=policy.history_limit)
    return dict(version='model_h_iterations_v1', records=records)


def _copy_model_h_array(view, shape=None):
    result = np.ctypeslib.as_array(view.data, shape=(view.size,)).copy()
    return result if shape is None else result.reshape(shape)


def _plane_info(result, shape, widths, masses, *, capture_scalars=None):
    audit = result.plane
    sides = {}
    for label, side, mass in zip(('A', 'B'), audit.sides, masses):
        sides[label] = dict(
            Q_advective_W_per_m=side.q_advective, inlet_conduction_W_per_m=side.inlet_conduction,
            exchange_W_per_m=side.exchange, source_W_per_m=0., residual_sum_W_per_m=side.residual_sum,
            residual_max_abs_W_per_m=side.residual_max,
            linearized_residual_sum_W_per_m=side.linearized_sum,
            linearized_residual_max_abs_W_per_m=side.linearized_max,
            linearization_defect_sum_W_per_m=side.defect_sum,
            linearization_defect_max_abs_W_per_m=side.defect_max,
            mass_net_out_kg_s_per_m=side.mass_net, mass_local_max_abs_kg_s_per_m=side.mass_local_max,
            mass_in_kg_s_per_m=side.mass_in, mass_out_kg_s_per_m=side.mass_out,
            boundary_mass_out_kg_s_per_m=[_copy_model_h_array(x).tolist() for x in side.boundary_mass_out],
            boundary_h_out_W_per_m=[_copy_model_h_array(x).tolist() for x in side.boundary_h_out],
            mass_faces_kg_s_per_m=[x.tolist() for x in mass],
            h_faces_W_per_m=[_copy_model_h_array(x, m.shape).tolist() for x, m in zip(side.h_faces, mass)],
            inlet_conduction_faces_W_per_m=_copy_model_h_array(side.inlet_conduction_faces).tolist(),
            cp_coefficients=list(side.cp_coefficients), unknown_inflow_faces=side.unknown_inflow_faces,
            physical_boundary_complete=side.unknown_inflow_faces == 0,
            strict_normalization_W_per_m=side.normalization, residual_cellmax_rel=side.cell_ratio)
    if capture_scalars is None:
        from sjtu_tpmshx.cpp_interface._native_result_metrics import capture_area
    return dict(
        units='W/m; kg/(s m)', state='raw final thermal return', boundary_order=['-x', '+x', '-y', '+y'],
        **sides, sou_A=True, sou_B=True,
        cell_count=int(np.prod(shape)) if capture_scalars is None else capture_scalars['cell_count'],
        dx_m=widths[0].tolist(), dy_m=widths[1].tolist(),
        area_m2=capture_area(widths[0], widths[1]) if capture_scalars is None else capture_scalars['area_m2'],
        solid_boundary_W_per_m=0., solid_source_W_per_m=0.,
        solid_residual_sum_W_per_m=audit.solid_sum, solid_residual_max_abs_W_per_m=audit.solid_max,
        solid_residual_cellmax_rel=audit.solid_cell_ratio, equation_tolerance=.01,
        residual_sum_W_per_m=audit.residual_sum, telescoping_error_W_per_m=audit.telescoping_error,
        net_boundary_in_W_per_m=audit.net_boundary_in, D2_W_per_m=audit.denominator,
        energy_imbalance_rel=audit.energy_imbalance, solid_imbalance_rel=audit.solid_imbalance,
        physical_boundary_complete=bool(audit.boundary_complete), finite=bool(audit.finite),
        energy_ok=bool(audit.energy_ok), solid_ok=bool(audit.solid_ok),
        equations_ok=bool(audit.equations_ok), passed=bool(audit.passed),
        thermal_converged=result.stop == 0, thermal_iterations=result.iterations,
        thermal_residual_K=result.residual)


def _volume_info(result, shape, *, include_faces=True, cell_count=None):
    audit = result.volume
    sides, native_faces, strict = {}, {}, {}
    for label, side in zip(('A', 'B'), audit.sides):
        faces, owned_faces = {}, {}
        for index, (name, face) in enumerate(zip(('x-', 'x+', 'y-', 'y+', 'z-', 'z+'), side.boundaries)):
            faces[name] = dict(outward_mass_kg_s=face.mass_out, outward_model_h_W=face.enthalpy_out,
                non_inlet_inward_mass_kg_s=face.unknown_mass_in, unknown_inflow_count=face.unknown_inflow_count,
                inlet_reverse_outward_mass_kg_s=face.inlet_reverse_mass_out)
            face_shape = tuple(n for axis, n in enumerate(shape) if axis != index // 2)
            if include_faces:
                owned_faces[name] = _copy_model_h_array(face.enthalpy_faces, face_shape)
        native_faces[label] = owned_faces
        sides[label] = dict(faces=faces, physical_boundary_complete=bool(side.boundary_complete),
            model_cp_coefficients=list(side.cp_coefficients),
            temperature_range_K=[side.temperature_min, side.temperature_max], net_outward_mass_kg_s=side.mass_net,
            convective_inward_W=side.advective_in, inlet_diffusion_inward_W=side.diffusion_in,
            numerical_external_inward_W=side.numerical_external_in,
            physical_external_inward_W=side.numerical_external_in if side.boundary_complete else None,
            fluid_solid_exchange_to_fluid_W=side.exchange, explicit_source_W=side.source,
            residual_sum_W=side.residual_sum, residual_max_abs_W=side.residual_max,
            strict_normalization_W=side.normalization)
        strict.update({f'eps_{label}_strict': side.global_ratio, f'eps_{label}_strict_cellmax': side.cell_ratio,
                       f'Q_s{label}': side.exchange})
    balance = dict(reference_K=audit.sides[0].cp_coefficients[4], cell_count=int(np.prod(shape)) if cell_count is None else cell_count,
        full_volume_m3=audit.volume, mass_source='completed SIMPLE raw faces before capacity balance/MAC',
        thermal_state='last returned temperatures; nonlinear model h and temperature SOU', sides=sides,
        physical_boundary_complete=bool(audit.boundary_complete), numerical_external_inward_W=audit.numerical_external_in,
        physical_external_inward_W=audit.numerical_external_in if audit.boundary_complete else None,
        explicit_source_W=audit.explicit_source, solid_external_diffusion_W=0.,
        solid_residual_sum_W=audit.solid_sum, solid_residual_max_abs_W=audit.solid_max,
        full_residual_sum_W=audit.full_residual_sum, telescoping_error_W=audit.telescoping_error,
        qualification='No physical acceptance inferred. Non-inlet inflow uses numerical self-extrapolation; its external h is unspecified.')
    return dict(model_h_balance=balance, _native_model_h=native_faces, **strict, delegated_to_2d=False)


def _model_h_algorithm(library, dimension):
    """Copy the recipe identity from the same native library used to solve."""
    try:
        query = library.tpmshx_model_h_algorithm_v1
    except AttributeError as error:
        raise ValueError('native library lacks tpmshx_model_h_algorithm_v1') from error
    query.argtypes, query.restype = [ct.c_uint32], ct.c_char_p
    identity = query(dimension)
    if not identity:
        raise ValueError(f'native library has no model-h algorithm for dimension {dimension}')
    return identity.decode('ascii')
