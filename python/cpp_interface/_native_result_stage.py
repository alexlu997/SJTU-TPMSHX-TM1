"""Adapt stored result evidence to the independent native result stage."""
import ast
import ctypes as ct
import json
from math import prod
import warnings
import weakref
from collections.abc import Mapping
from uuid import uuid4

import numpy as np

from . import _native_result as core
from sjtu_tpmshx.data_types.metric_spec import MetricSpec
from sjtu_tpmshx.data_types.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.data_types.persistence_validation import validate_result_declarations

P = ct.POINTER
S, I, Z, D = ct.c_char_p, ct.c_int, ct.c_size_t, ct.c_double
AP, SP = P(core._Array), P(core._Scalar)


def record(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


Named = record('Named', [('name', S), ('value', core._Array)])

def solver_entry(library, name):
    """Return a required solver symbol. A missing symbol is a deployment error."""
    try:
        return getattr(library, name)
    except AttributeError as error:
        raise ValueError(f'native solver library lacks {name}; rebuild the library') from error


def execution_view_query(library, dimension, result_type, view_type):
    query = solver_entry(library, f'tpmshx_stage_run_{dimension}d_execution_view_v1')
    query.argtypes, query.restype = [ct.POINTER(result_type)], ct.POINTER(view_type)
    return query


def executed_view(query, result):
    view = query(ct.byref(result))
    if not view:
        raise RuntimeError('native stage returned no execution record')
    return view.contents


def completed_report(library, result):
    query = solver_entry(library, f'tpmshx_stage_run_{result.evidence.dimension}d_report_v1')
    query.argtypes, query.restype = [ct.POINTER(type(result)), ct.POINTER(ct.c_char), ct.c_size_t], ct.c_char_p
    error = ct.create_string_buffer(1024)
    data = query(ct.byref(result), error, len(error))
    if data is None:
        raise RuntimeError(error.value.decode() or 'native stage returned no execution report')
    return json.loads(data)


def link_execution(report, case, energy):
    """Attach portable model references to the completed solver report."""
    facts = report['facts']
    for side, record in facts['sides'].items():
        model = case.metadata['model_roles']['fluid_' + side]
        record['flow_and_exchange_model_ref'] = model
        record['energy']['model_ref'] = model if record['solved'] and 'fluid' not in record['energy'] else None
    index = report['last_main_model_h']
    rows = report['model_h_iterations']['records']
    facts['thermal']['effective_settings'] = (rows[index]['settings'] if index < len(rows) else
                                              energy['effective_settings'] if energy is not None else {})
    return facts


def _stage_array(value, shape):
    strides = tuple(8 * prod(shape[i + 1:]) for i in range(len(shape)))
    if (value.dtype != 12 or value.byte_order or value.offset or value.rank != len(shape)
            or tuple(value.shape[:value.rank]) != tuple(shape) or not value.data
            or value.bytes != prod(shape) * 8 or tuple(value.strides[:value.rank]) != strides):
        raise RuntimeError('native result array has an invalid layout')
    return np.frombuffer(ct.string_at(value.data, value.bytes), dtype=np.float64).reshape(shape)


def detach_stage_fields(evidence, shape, *, prepared_fields=None):
    """Copy each cell buffer once while the native stage owns it."""
    buffers = {}
    fields = {}
    for named in evidence.fields[:evidence.field_count]:
        name = named.name.decode()
        if prepared_fields is not None and name in prepared_fields:
            fields[name] = prepared_fields[name]
            continue
        value = named.value
        if value.data not in buffers:
            buffers[value.data] = _stage_array(value, shape)
        fields[name] = buffers[value.data]
    return fields, field_declarations(evidence)


def closure_records(rows, count):
    from sjtu_tpmshx.run_control.run_warnings import RangeRecord
    samples = []
    records: dict[tuple, RangeRecord] = {}
    for entry in rows[:count] if count else ():
        value = entry.sample.contents
        row = {name: getattr(value, name).decode() for name in ('view', 'model', 'topology', 'stage', 'layout')}
        shape = tuple(value.shape[:value.ndim])
        bounds = value.lower, value.upper
        row.update(side='AB'[value.side], shape=shape, bounds=bounds, low=value.low, high=value.high,
                   size=value.size, nonfinite=value.nonfinite)
        for key in ('minimum', 'maximum'):
            position = getattr(entry, key + '_index')
            row[key] = (getattr(value, key), tuple(position[:value.ndim])) if value.have_finite else None
        samples.append(row)
        source = (row['view'], row['model'], row['topology'])[:entry.source_count]
        source_key = (*source, shape, (row['side'], row['stage'], row['layout']))
        record = RangeRecord(entry.label.decode(), entry.quantity.decode(), entry.unit.decode(),
            bounds, row['minimum'], row['maximum'], value.low, value.high, value.size, value.nonfinite)
        previous = records.get(source_key)
        records[source_key] = record if previous is None else previous.merged(record)
    return samples, records


def nu_observation(value, shape, summary):
    if not value.available:
        return {}
    return dict(stage='last local h_v coefficient evaluation (lagged temperature)',
        shape=list(shape), cells=value.cells, floor_cells=value.floor_cells,
        floor_fraction=summary['floor_fraction'],
        floor=summary['floor'],
        pre_floor_min=value.raw_min, pre_floor_max=value.raw_max, Re_min=value.re_min, Re_max=value.re_max,
        Pr_min=value.pr_min, Pr_max=value.pr_max, T_min_K=value.temperature_min, T_max_K=value.temperature_max,
        P_abs_Pa=value.pressure)


def stage_closures(records):
    from sjtu_tpmshx.run_control.run_warnings import range_observations
    rows, warnings = closure_records(records.observations, records.observation_count)
    _, last = closure_records(records.last, records.last_count)
    return rows, warnings, range_observations(last)


def stage_ledger(thermal, temperature, shape):
    """Detach the cell residuals and signed face powers from the stage."""
    pointer = thermal.temperature if thermal.temperature else thermal.energy
    if not pointer:
        return None
    ledger = pointer.contents
    dimension = len(shape)
    if dimension != ledger.physical_dimension or ledger.phase_count != 3:
        raise RuntimeError('native stage ledger has an invalid dimension or phase count')
    output = dict(definition=ledger.definition.decode(), power_units=ledger.power_units.decode(),
        physical_dimension=dimension, physical_boundary_complete=bool(ledger.physical_boundary_complete),
        prescribed_b_power=_stage_array(ledger.prescribed_b_power.contents, ()).item())
    for key in ('solved', 'residual', 'source_integral', 'advective_out', 'diffusive_out'):
        output[key] = {}
    volume = (*shape, 1) if dimension == 2 else shape
    for phase in ledger.phases[:ledger.phase_count]:
        label = phase.name.decode()
        output['solved'][label] = bool(phase.solved)
        output['residual'][label] = _stage_array(phase.residual.contents, shape) if phase.solved else None
        output['source_integral'][label] = _stage_array(phase.source_integral.contents, ()).item() if phase.solved else None
        for key, count in (('advective_out', phase.advective_count), ('diffusive_out', phase.diffusive_count)):
            faces = None
            if phase.solved:
                faces = {}
                for named in getattr(phase, key)[:count]:
                    name = named.name.decode()
                    axis = 'xyz'.index(name[0])
                    faces[name] = _stage_array(named.value, volume[:axis] + volume[axis + 1:])
            output[key][label] = faces
    if thermal.temperature:
        info = temperature.contents
        output.update(algorithm=info.algorithm.decode('ascii'), cp_coefficients={
            side: np.array(info.cp_coefficients[i]) if info.solved[i] else None for i, side in enumerate('AB')})
    return output


def field_declarations(evidence):
    axes = ('x', 'y', 'z')[:evidence.dimension]
    return {row.name.decode(): dict(unit=row.unit.decode(), state=row.state.decode(),
            axes=axes, location='cell')
            for row in evidence.field_metadata[:evidence.field_metadata_count]}


Gate = record('Gate', [('name', S), ('value', I), ('recorded_number', SP), ('recorded_text', S)])
Grid = record('Grid', [('widths', AP * 3)])
Declaration = record('Declaration', [('name', S), ('unit', S), ('state', S)])
Pressure = record('Pressure', [('pressure', AP), ('grid', Grid), ('inlet_fraction', AP),
    ('outlet_fraction', AP), ('outlet_geom_fraction', AP), ('reference', SP),
    ('inlet_absolute', SP), ('outlet_absolute', SP), ('unit', S)])
Phase = record('Phase', [('name', S), ('solved', I), ('residual', AP),
    ('advective_out', P(Named)), ('diffusive_out', P(Named)),
    ('advective_count', Z), ('diffusive_count', Z), ('source_integral', AP)])
Energy = record('Energy', [('definition', S), ('power_units', S), ('physical_dimension', I),
    ('physical_boundary_complete', I), ('phases', P(Phase)), ('phase_count', Z), ('prescribed_b_power', AP)])
ModelSide = record('ModelSide', [('physical_boundary_complete', I), ('staggered_power', AP),
    ('staggered_count', Z), ('boundary_power', P(Named)), ('boundary_count', Z)])
Model = record('Model', [('passed', I), ('physical_boundary_complete', I), ('sides', ModelSide * 2)])
TrueH = record('TrueH', [('energy_algorithm', S), ('boundary_power_units', S),
    ('energy_algorithm_version', P(I)), ('physical_boundary_complete', I),
    ('enthalpy', AP * 2), ('inlet_enthalpy', SP * 2), ('mass', AP * 2), ('mass_count', Z * 2),
    ('boundary_power', P(Named) * 2), ('boundary_count', Z * 2), ('invalid_version_type', I)])
Thermal = record('Thermal', [('mass', AP * 2), ('mass_count', Z * 2), ('energy', P(Energy)),
    ('temperature', P(Energy)), ('true_h', P(TrueH)), ('model_h', P(Model)), ('report_direction', P(I) * 2)])
Fine = record('Fine', [('grid', Grid), ('fields', P(Named)), ('field_count', Z), ('thermal', Thermal),
    ('rho_cp', AP * 2), ('inlet_fraction', AP * 2), ('outlet_fraction', AP * 2), ('epsilon', AP), ('empty_record', I)])
TrueCertificate = record('TrueCertificate', [('converged', I), ('clip_counts', AP),
    ('ratios', SP * 2), ('tolerances', SP * 2)])
ModelLevel = record('ModelLevel', [('level', S), ('value', Model)])
ExecutionSide = record('ExecutionSide', [('side', S), ('fluid', S), ('solved', I)])
Range = record('Range', [('captured', I), ('side', S), ('quantity', S), ('constraint', S),
    ('stage', S), ('layout', S), ('unit', S), ('reason', S), ('source', P(S)), ('source_count', Z),
    ('bounds', D * 2), ('shape', P(Z)), ('rank', Z), ('size', Z), ('low', Z), ('high', Z), ('nonfinite', Z),
    ('minimum', P(D)), ('maximum', P(D)), ('minimum_index', P(Z)), ('maximum_index', P(Z))])
Required = record('Required', [('group', S), ('side', S), ('source', P(S)), ('source_count', Z)])
Applicability = record('Applicability', [('version', S), ('inlet', P(Range)), ('final_state', P(Range)),
    ('inlet_count', Z), ('final_count', Z), ('required', P(Required)), ('required_count', Z),
    ('inlet_recorded', I), ('scope_notes', P(S)), ('scope_note_count', Z)])
Quick = record('Quick', [(name, SP) for name in ('inlet_temperature', 'mass_flow', 'cp', 'rho', 'velocity', 'viscosity')])
Evidence = record('Evidence', [('abi_version', ct.c_uint32), ('struct_size', Z), ('result_id', S), ('dimension', I),
    ('metadata_dimension', P(I)), ('quantity_basis', S), ('mass_unit', S), ('mode', S), ('thermal_mode', S),
    ('temperature_transport', S), ('grid', Grid), ('fields', P(Named)), ('field_count', Z),
    ('field_metadata', P(Declaration)), ('field_metadata_count', Z), ('pressure', P(Pressure) * 2),
    ('thermal', Thermal), ('fine', P(Fine)), ('thermal_state', S), ('execution', S), ('converged', I),
    ('outer_index', P(I)), ('convergence_gates', P(Gate)), ('convergence_gate_count', Z),
    ('true_h_certificate', P(TrueCertificate)), ('model_certificates', P(ModelLevel)), ('model_certificate_count', Z),
    ('strict_ratios', P(D) * 4), ('source_power', P(D) * 2), ('model_active_b', I), ('richardson_extrapolated', I),
    ('execution_version', S), ('executed_sides', P(ExecutionSide)), ('executed_side_count', Z),
    ('applicability', P(Applicability)), ('active_fluids', I * 2), ('direction', P(I) * 2),
    ('inlet_temperature', SP * 2), ('inlet_geom_fraction', AP * 2), ('outlet_geom_fraction', AP * 2),
    ('rho_cp', AP * 2), ('parameter_epsilon', AP), ('design_epsilon', AP), ('split_a', SP), ('solid_density', SP),
    ('quick_model', S), ('arrangement', S), ('quick', Quick * 2), ('hydraulic_diameter', SP),
    ('absent_records', P(S)), ('absent_record_count', Z), ('model_certificate_error', S)])
Spec = record('Spec', [('name', S), ('unit', S), ('definition_version', S), ('description', S)])
Metric = record('Metric', [('name', S), ('spec', Spec), ('has_value', I), ('value', D), ('status', S), ('reason', S)])
Output = record('Output', [('struct_size', Z), ('owner', ct.c_void_p), ('json', S),
    ('metrics', P(Metric)), ('metric_count', Z), ('diagnostics', core._Diagnostics)])



InputError = record('InputError', [('value', ct.c_void_p), ('cause', ct.c_uint32),
    ('message', S), ('token', ct.c_uint64)])
HostError = record('HostError', [('cause', ct.c_uint32), ('error_number', ct.c_int32),
    ('token', ct.c_uint64), ('message', S)])
Events = ct.CFUNCTYPE(I, ct.c_void_p, P(core._Diagnostics), P(HostError))
Input = record('Input', [('abi_version', ct.c_uint32), ('struct_size', Z), ('evidence', P(Evidence)),
    ('errors', P(InputError)), ('error_count', Z), ('none_values', P(ct.c_void_p)), ('none_count', Z),
    ('solid_density', AP), ('split_a', AP), ('inlet_temperature', AP * 2), ('invalid_mode_repr', S), ('physical_dimension_index', P(I)), ('physical_dimension_slice', P(I)), ('qualification_error', P(I)),
    ('context', ct.c_void_p), ('events', Events)])
QuickValue = record('QuickValue', [('numeric', AP), ('object', ct.c_uint64)])
QVP = P(QuickValue)
StageLabel = record('StageLabel', [('text', S), ('value', QVP)])
QuickTextEqual = ct.CFUNCTYPE(I, ct.c_void_p, QVP, S, P(I), P(HostError))
QuickDifference = ct.CFUNCTYPE(I, ct.c_void_p, QVP, D, QVP, P(HostError))
QuickPair = ct.CFUNCTYPE(I, ct.c_void_p, QVP, QVP, QVP, P(HostError))
QuickDuty = ct.CFUNCTYPE(I, ct.c_void_p, QVP, QVP, I, QVP, P(HostError))
QuickFloat = ct.CFUNCTYPE(I, ct.c_void_p, QVP, P(D), P(HostError))
QuickEmptyMean = ct.CFUNCTYPE(I, ct.c_void_p, P(HostError))
QuickProtocols = record('QuickProtocols', [('context', ct.c_void_p), ('text_equal', QuickTextEqual),
    ('text_not_equal', QuickTextEqual),
    ('temperature_difference', QuickDifference), ('capacity_product', QuickPair), ('duty_product', QuickDuty),
    ('pressure_difference', QuickPair), ('reynolds_flow', QuickPair), ('reynolds_length', QuickPair),
    ('reynolds_quotient', QuickPair), ('metric_float', QuickFloat), ('empty_mean', QuickEmptyMean)])
QuickSide = record('QuickSide', [(name, P(I)) for name in ('boundary_access', 'properties_access', 'pressure_access')]
    + [(name, QVP) for name in ('inlet_temperature', 'mass_flow', 'cp', 'rho', 'velocity', 'viscosity', 'inlet_pressure', 'outlet_pressure')])
QuickInput = record('QuickInput', [('abi_version', ct.c_uint32), ('struct_size', Z), ('host', P(Input)),
    ('model', P(StageLabel)), ('arrangement', P(StageLabel)), ('execution_version', P(StageLabel)), ('sides', QuickSide * 2), ('hydraulic_diameter', QVP),
    ('protocol', QuickProtocols)])
_MISSING = object()
_REQUIRED = object()


class _Fault:
    def __init__(self, error):
        self.error = error


def _read(values, key, default=_REQUIRED):
    if isinstance(values, _Fault):
        return values
    try:
        return values[key] if default is _REQUIRED else values.get(key, default)
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        return _Fault(error)


def _cause(error):
    for exception, cause in ((ZeroDivisionError, 1), (OverflowError, 2), (ValueError, 3),
                             (TypeError, 4), (IndexError, 5), (KeyError, 6), (NotImplementedError, 7)):
        if isinstance(error, exception):
            return cause
    return 8


def _text(value):
    return value.encode('utf-8')


def _equality_flag(value):
    try:
        if isinstance(value, _Fault):
            raise value.error
        if value is None or value is _MISSING:
            return -1, None
        if type(value) is bool:
            return int(value), None
        return (-3 if False == value else -2), None
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
        return -2, error


def _truth(value):
    if value is None or value is _MISSING:
        return -1
    if type(value) is bool:
        return int(value)
    if value == False:
        return -3
    return -2 if value else -5


class _Packed:
    def __init__(self):
        self.keep = []
        self.errors = []
        self.exceptions = {}
        self.array_errors = {}
        self.none_values = []
        self.quick_objects = {}

    def pointer(self, value):
        self.keep.append(value)
        return ct.pointer(value)

    def sequence(self, kind, values):
        output = (kind * len(values))(*values)
        self.keep.append(output)
        return output

    def token(self, error):
        token = len(self.exceptions) + 1
        # Contexts and group members can also retain borrowed fields through frames.
        pending, visited = [error], set()
        while pending:
            current = pending.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            BaseException.with_traceback(current, None)
            # Read stored relations without calling an exception subclass accessor.
            relations = (BaseException.__dict__['__cause__'].__get__(current),
                         BaseException.__dict__['__context__'].__get__(current))
            pending.extend(value for value in relations if value is not None)
            if isinstance(current, BaseExceptionGroup):
                pending.extend(BaseExceptionGroup.__dict__['exceptions'].__get__(current))
        self.exceptions[token] = error
        return token

    def fault(self, pointer, error):
        address = ct.cast(pointer, ct.c_void_p).value
        self.errors.append(InputError(address, _cause(error), _text(str(error)), self.token(error)))
        return pointer

    def scalar(self, value):
        if value is _MISSING:
            return None
        try:
            if isinstance(value, _Fault):
                raise value.error
            return self.pointer(core.scalar(value))
        except (TypeError, ValueError, OverflowError, KeyError, IndexError, AttributeError) as error:
            return self.fault(self.pointer(core._Scalar()), error)

    def quick_object(self, value):
        token = len(self.quick_objects) + 1
        self.quick_objects[token] = value
        return self.pointer(QuickValue(object=token))

    def quick_value(self, value):
        if isinstance(value, _Fault):
            return self.fault(self.pointer(QuickValue()), value.error)
        protocol = (not isinstance(value, (int, float, complex, np.number))
            and not (isinstance(value, np.ndarray) and value.dtype.kind in 'biufc'))
        if protocol or core.integer_product_requires_python((value,)):
            return self.quick_object(value)
        owner = core.array(value)
        self.keep.append(owner)
        return self.pointer(QuickValue(numeric=self.pointer(owner.raw)))

    def quick_read(self, pointer):
        value = pointer.contents
        if value.object:
            return self.quick_objects[value.object]
        raw = value.numeric.contents
        dtype = core.NATIVE_DTYPES[raw.dtype]
        if raw.byte_order:
            dtype = dtype.newbyteorder('<' if raw.byte_order == 1 else '>')
        shape = tuple(raw.shape[:raw.rank])
        array = np.ndarray(shape, dtype=dtype, buffer=ct.string_at(raw.data, raw.bytes),
                           offset=raw.offset, strides=tuple(raw.strides[:raw.rank]))
        if raw.origin == 2:
            return array
        scalar = array[()]
        conversion = {0: float, 3: int, 4: bool, 5: complex}.get(raw.origin)
        return conversion(scalar) if conversion is not None else scalar

    def callback_error(self, error, failure):
        message = _text(str(error))
        self.keep.append(message)
        failure[0] = HostError(_cause(error), getattr(error, 'errno', 0) or 0, self.token(error), message)
        return 1

    def quick_protocols(self):
        # The query owns this state; callbacks must not extend its lifetime.
        owner = weakref.proxy(self)
        def result(output, failure, operation):
            try:
                output[0] = owner.quick_value(operation()).contents
                return 0
            except BaseException as error:
                return owner.callback_error(error, failure)

        @QuickTextEqual
        def text_equal(context, value, expected, output, failure):
            try:
                output[0] = bool(owner.quick_read(value) == expected.decode('utf-8'))
                return 0
            except BaseException as error:
                return owner.callback_error(error, failure)

        @QuickTextEqual
        def text_not_equal(context, value, expected, output, failure):
            try:
                output[0] = bool(owner.quick_read(value) != expected.decode('utf-8'))
                return 0
            except BaseException as error:
                return owner.callback_error(error, failure)

        @QuickDifference
        def temperature_difference(context, inlet, outlet, output, failure):
            return result(output, failure, lambda: owner.quick_read(inlet) - outlet)

        @QuickPair
        def capacity_product(context, mass, cp, output, failure):
            return result(output, failure, lambda: owner.quick_read(mass) * owner.quick_read(cp))

        @QuickDuty
        def duty_product(context, capacity, delta, cold, output, failure):
            return result(output, failure, lambda: owner.quick_read(capacity) * owner.quick_read(delta) * (-1 if cold else 1))

        @QuickPair
        def pressure_difference(context, inlet, outlet, output, failure):
            return result(output, failure, lambda: owner.quick_read(inlet) - owner.quick_read(outlet))

        @QuickPair
        def reynolds_flow(context, rho, velocity, output, failure):
            return result(output, failure, lambda: owner.quick_read(rho) * abs(owner.quick_read(velocity)))

        @QuickPair
        def reynolds_length(context, flow, diameter, output, failure):
            return result(output, failure, lambda: owner.quick_read(flow) * owner.quick_read(diameter))

        @QuickPair
        def reynolds_quotient(context, numerator, mu, output, failure):
            return result(output, failure, lambda: owner.quick_read(numerator) / owner.quick_read(mu))

        @QuickFloat
        def metric_float(context, value, output, failure):
            try:
                output[0] = float(owner.quick_read(value))
                return 0
            except BaseException as error:
                return owner.callback_error(error, failure)

        @QuickEmptyMean
        def empty_mean(context, failure):
            try:
                warnings.warn('Mean of empty slice', RuntimeWarning, stacklevel=6)
                return 0
            except BaseException as error:
                return owner.callback_error(error, failure)

        callbacks = (text_equal, text_not_equal, temperature_difference, capacity_product, duty_product, pressure_difference,
            reynolds_flow, reynolds_length, reynolds_quotient, metric_float, empty_mean)
        self.keep.extend(callbacks)
        return QuickProtocols(None, *callbacks)

    def label(self, value):
        if isinstance(value, _Fault):
            return self.fault(self.pointer(StageLabel()), value.error)
        if type(value) is str:
            try:
                encoded = value.encode('utf-8')
            except UnicodeEncodeError:
                pass
            else:
                if b'\0' not in encoded:
                    return self.pointer(StageLabel(text=encoded))
        return self.pointer(StageLabel(value=self.quick_object(value)))

    def quick_access(self, value):
        return self.fault(self.pointer(I()), value.error) if isinstance(value, _Fault) else self.pointer(I(1))

    def number(self, kind, value):
        if value is _MISSING or value is None:
            return None
        try:
            if isinstance(value, _Fault):
                raise value.error
            return self.pointer(kind(value))
        except (TypeError, ValueError, OverflowError, KeyError, IndexError, AttributeError) as error:
            return self.fault(self.pointer(kind()), error)

    def text(self, value):
        if value is _MISSING or value is None:
            return None
        try:
            if isinstance(value, _Fault):
                raise value.error
            return _text(value)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            owner = ct.create_string_buffer(1)
            self.keep.append(owner)
            return self.fault(ct.cast(owner, S), error)

    def array(self, value, *, preserve_origin=False, finite_protocol=False):
        if value is _MISSING:
            return None
        try:
            if isinstance(value, _Fault):
                raise value.error
            owner = core.array(value if preserve_origin else np.asarray(value))
            self.keep.append(owner)
            return self.pointer(owner.raw)
        except (TypeError, ValueError, OverflowError, KeyError, IndexError, AttributeError) as error:
            failure = error
            if finite_protocol and not isinstance(value, _Fault):
                try:
                    np.isfinite(np.asarray(value))
                except (TypeError, ValueError) as finite_error:
                    failure = finite_error
            raw = core._Array()
            try:
                shape = np.shape(value) if not isinstance(value, _Fault) else ()
            except (TypeError, ValueError):
                shape = ()
            raw.rank = len(shape)
            raw.shape = self.sequence(Z, shape)
            raw.strides = self.sequence(ct.c_ssize_t, [0] * len(shape))
            self.array_errors[ct.addressof(raw)] = failure
            return self.fault(self.pointer(raw), failure)

    def arrays(self, values):
        try:
            if isinstance(values, _Fault):
                raise values.error
            owners = [self.array(value) for value in values]
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            output = self.sequence(core._Array, [])
            return self.fault(output, error), 0
        output = self.sequence(core._Array, [value.contents for value in owners])
        for index, value in enumerate(owners):
            failure = self.array_errors.get(ct.addressof(value.contents))
            if failure is not None:
                self.fault(ct.pointer(output[index]), failure)
        return output, len(owners)

    def named(self, values, *, finite_keys=()):
        try:
            if isinstance(values, _Fault):
                raise values.error
            owners = [(name, self.array(value, finite_protocol=name in finite_keys))
                      for name, value in values.items()]
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            output = self.sequence(Named, [])
            return self.fault(output, error), 0
        output = self.sequence(Named, [Named(self.text(name), value.contents) for name, value in owners])
        for index, (_, value) in enumerate(owners):
            failure = self.array_errors.get(ct.addressof(value.contents))
            if failure is not None:
                self.fault(ct.pointer(output[index].value), failure)
        return output, len(owners)

    def strings(self, values):
        return self.sequence(S, [self.text(value) for value in values])

    def grid(self, values):
        return Grid((AP * 3)(*(self.array(_read(values, 'd' + axis, _MISSING)) for axis in 'xyz')))

    def record(self, kind, value, pack):
        if value is _MISSING or value is None:
            return None
        try:
            if isinstance(value, _Fault):
                raise value.error
            return self.pointer(pack(value))
        except (TypeError, ValueError, OverflowError, KeyError, IndexError, AttributeError) as error:
            return self.fault(self.pointer(kind()), error)

    def pressure(self, value):
        output = Pressure(grid=self.grid(value))
        output.pressure = self.array(_read(value, 'P', _MISSING))
        for member, names in (('inlet_fraction', ('inlet_frac', 'inlet_fraction')),
                              ('outlet_fraction', ('outlet_frac', 'outlet_fraction')),
                              ('outlet_geom_fraction', ('outlet_geom_frac',))):
            first = _read(value, names[0], _MISSING)
            if first is _MISSING and len(names) == 2:
                first = _read(value, names[1], _MISSING)
            setattr(output, member, self.array(first))
        reference = _read(value, 'P_ref_abs', _read(value, 'reference_abs_Pa', _MISSING))
        output.reference = self.scalar(reference)
        output.inlet_absolute = self.scalar(_read(value, 'inlet_absolute_Pa', _MISSING))
        output.outlet_absolute = self.scalar(_read(value, 'outlet_absolute_Pa', _MISSING))
        output.unit = self.text(_read(value, 'unit', None))
        return output

    def energy(self, value):
        output = Energy(definition=self.text(_read(value, 'definition')),
            power_units=self.text(_read(value, 'power_units')),
            physical_dimension=value['physical_dimension'],
            physical_boundary_complete=_truth(value['physical_boundary_complete']))
        phases = []
        for name, solved in value['solved'].items():
            phase = Phase(name=self.text(name), solved=_truth(solved))
            residual = _read(_read(value, 'residual'), name)
            source = _read(_read(value, 'source_integral'), name)
            phase.residual = self.array(_MISSING if residual is None else residual)
            phase.source_integral = self.array(_MISSING if source is None else source)
            for member in ('advective_out', 'diffusive_out'):
                powers = _read(_read(value, member), name)
                rows, count = self.named({} if powers is None else powers)
                setattr(phase, member, rows)
                setattr(phase, 'advective_count' if member == 'advective_out' else 'diffusive_count', count)
            phases.append(phase)
        output.phases, output.phase_count = self.sequence(Phase, phases), len(phases)
        output.prescribed_b_power = self.array(_read(value, 'prescribed_b_power'))
        return output

    def identity_flag(self, owner, name, value):
        setattr(owner, name, int(value) if type(value) is bool else -1 if value is None else -2)
        if isinstance(value, _Fault):
            self.fault(ct.byref(owner, getattr(type(owner), name).offset), value.error)

    def model(self, value, certificate=None, *, required=False, output=None):
        certificate = value if certificate is None else certificate
        output = Model() if output is None else output
        self.identity_flag(output, 'passed', _read(certificate, 'passed', _REQUIRED if required else None))
        self.identity_flag(output, 'physical_boundary_complete', _read(certificate, 'physical_boundary_complete', None))
        for index, side in enumerate('AB'):
            row = _read(value, side, _REQUIRED if required else {})
            recorded = _read(_read(certificate, 'sides', {}), side, row)
            self.identity_flag(output.sides[index], 'physical_boundary_complete',
                _read(recorded, 'physical_boundary_complete', _REQUIRED if required else None))
            if required:
                continue
            powers = _read(row, 'h_faces_W_per_m', ())
            output.sides[index].staggered_power, output.sides[index].staggered_count = self.arrays(powers)
            faces = {name: item for name, item in row.items()
                     if name not in ('physical_boundary_complete', 'h_faces_W_per_m', 'passed')}
            output.sides[index].boundary_power, output.sides[index].boundary_count = self.named(faces)
        return output

    def true_h(self, value):
        version = _read(value, 'energy_algorithm_version', _MISSING)
        output = TrueH(energy_algorithm=self.text(_read(value, 'energy_algorithm', None)),
            boundary_power_units=self.text(_read(value, 'boundary_power_units', None)),
            energy_algorithm_version=self.number(I, version if version is _MISSING or isinstance(version, _Fault)
                else version if type(version) is int and -(1 << 31) <= version < (1 << 31) else 0),
            invalid_version_type=int(version is not _MISSING and type(version) is not int),
            physical_boundary_complete=_truth(value['physical_boundary_complete']) if 'physical_boundary_complete' in value else -4)
        for index, side in enumerate('AB'):
            output.enthalpy[index] = self.array(_read(value, 'h_' + side, _MISSING))
            output.inlet_enthalpy[index] = self.scalar(_read(value, 'h_in_' + side, _MISSING))
            mass = _read(value, 'mass_flux_' + side, ())
            output.mass[index], output.mass_count[index] = self.arrays(mass)
            powers = _read(_read(value, 'boundary_power', {}), side, {})
            output.boundary_power[index], output.boundary_count[index] = self.named(powers)
        return output

    def thermal(self, value, model_certificate=None):
        output = Thermal()
        for index, side in enumerate('AB'):
            mass = _read(value, 'mass_' + side, _MISSING)
            if mass is not _MISSING:
                output.mass[index], output.mass_count[index] = self.arrays(() if mass is None else mass)
                if mass is None:
                    self.none_values.append(ct.cast(output.mass[index], ct.c_void_p).value)
            report = _read(_read(value, 'report', {}), side, {})
            output.report_direction[index] = self.number(I, _read(report, 'direction', _MISSING))
        output.energy = self.record(Energy, _read(value, 'energy', None), self.energy)
        output.temperature = self.record(Energy, _read(value, 'temperature', None), self.energy)
        output.true_h = self.record(TrueH, _read(value, 'true_h', None), self.true_h)
        model = _read(value, 'model_h', _read(value, 'model_h_balance', None))
        output.model_h = self.record(Model, model, lambda row: self.model(row, model_certificate))
        return output

    def fine(self, value):
        output = Fine(grid=self.grid(value), thermal=self.thermal(value), empty_record=int(not value))
        fields = {name: value[name] for name in ('Ta', 'Tb', 'Ts', 'ucA', 'vcA', 'ucB', 'vcB')
                  if _read(value, name, None) is not None}
        output.fields, output.field_count = self.named(fields, finite_keys=('Ta', 'Tb', 'Ts'))
        for index, side in enumerate('AB'):
            output.rho_cp[index] = self.array(_read(value, 'rho_cp_' + side, _MISSING))
            output.inlet_fraction[index] = self.array(_read(value, 'inlet_' + side, _MISSING))
            output.outlet_fraction[index] = self.array(_read(value, 'outlet_' + side, _MISSING))
        output.epsilon = self.array(_read(value, 'eps', _MISSING))
        return output

    def true_certificate(self, value):
        clips = _read(_read(value, 'enthalpy_clip_counts'), 'total')
        if isinstance(clips, _Fault):
            raise clips.error
        output = TrueCertificate(clip_counts=self.array(clips))
        self.identity_flag(output, 'converged', _read(value, 'converged'))
        settings = _read(value, 'effective_settings')
        for index, name in enumerate(('coupled', 'equation')):
            row = _read(value, name + '_energy_balance')
            output.ratios[index] = self.scalar(_read(row, 'ratio', _MISSING))
            output.tolerances[index] = self.scalar(_read(settings, name + '_energy_tol', _MISSING))
        return output

    def ranges(self, values):
        rows = []
        for value in values:
            row = Range(captured=_truth(value['captured']), side=self.text(value['side']),
                quantity=self.text(value['quantity']), constraint=self.text(value.get('constraint')),
                stage=self.text(value.get('stage')), layout=self.text(value.get('layout')),
                unit=self.text(value.get('unit')), reason=self.text(value.get('reason')))
            row.source, row.source_count = self.strings(value['source']), len(value['source'])
            if value['captured'] is True:
                row.bounds = (D * 2)(*value['bounds'])
                row.shape, row.rank = self.sequence(Z, value['shape']), len(value['shape'])
                row.size, row.low, row.high, row.nonfinite = (value[key] for key in ('size', 'low', 'high', 'nonfinite'))
                for name in ('minimum', 'maximum'):
                    extreme = value[name]
                    if extreme is not None:
                        setattr(row, name, self.number(D, extreme[0]))
                        setattr(row, name + '_index', self.sequence(Z, extreme[1]))
            rows.append(row)
        return self.sequence(Range, rows), len(rows)

    def applicability(self, value):
        output = Applicability(version=self.text(value['version']), inlet_recorded=_truth(value['inlet_recorded']))
        output.inlet, output.inlet_count = self.ranges(value['inlet'])
        output.final_state, output.final_count = self.ranges(value['final'])
        required = [Required(self.text(row['group']), self.text(row['side']), self.strings(row['source']), len(row['source']))
                    for row in value['required']]
        output.required, output.required_count = self.sequence(Required, required), len(required)
        output.scope_notes, output.scope_note_count = self.strings(value['scope_notes']), len(value['scope_notes'])
        return output


def _declaration_dimension(result, query):
    metadata = result.metadata
    dimension = result.grid.get('dimension', metadata.get('dimension'))
    # The C interface represents primary sides, integer dimensions and C strings.
    # Other host values keep their original comparison and exception semantics.
    def label(value):
        return type(value) is str and '\0' not in value and value.isascii()

    pressure = result.pressure_evidence
    if (query == 3 or type(dimension) is not int or dimension not in (2, 3)
            or type(metadata.get('dimension', dimension)) is not int
            or metadata.get('dimension', dimension) not in (2, 3)
            or any(key in row and not label(row[key]) for row, key in
                   ((metadata, 'mode'), (metadata, 'quantity_basis'), (result.boundary_fluxes, 'mass_unit')))
            or any(side not in ('A', 'B') or not isinstance(row, Mapping)
                   or ('unit' in row and not label(row['unit'])) for side, row in pressure.items())
            or any(not label(key) or not isinstance(row, Mapping) or not label(row.get('unit', ''))
                   for key, row in result.field_metadata.items())):
        return validate_result_declarations(result)
    return dimension


class _Evidence(_Packed):
    def pack(self, result, query):
        self.result, self.query = result, query
        self.density = self.split = self.invalid_mode_repr = self.dimension_index = self.dimension_slice = None
        self.qualification_error = None
        self.quick = None
        self.execution_label = None
        self.inlet_temperature = (AP * 2)()
        metadata, flux = result.metadata, result.boundary_fluxes
        output = self.raw = Evidence(abi_version=1, struct_size=ct.sizeof(Evidence),
            result_id=_text(result.result_id), mode=b'full', converged=-1,
            model_active_b=-1, richardson_extrapolated=-1, active_fluids=(I * 2)(1, 1))
        output.applicability = self.record(Applicability,
            metadata.get('applicability_evidence'), self.applicability)
        if query == 1:
            return
        try:
            dimension = _declaration_dimension(result, query)
            try:
                ()[:dimension]
            except TypeError as error:
                self.dimension_slice = self.fault(self.pointer(I()), error)
            try:
                range(dimension)
            except TypeError as error:
                self.dimension_index = self.fault(self.pointer(I()), error)
            dimension = (2 if dimension == 2 else 3) if dimension in (2, 3) else 0
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            dimension = 0
            address = ct.byref(output, Evidence.dimension.offset)
            self.fault(address, error)
        output.dimension = dimension
        if 'dimension' in metadata:
            declared = metadata['dimension']
            output.metadata_dimension = self.number(I, declared if type(declared) is int and declared in (2, 3) else dimension)
        output.quantity_basis = self.text(metadata.get('quantity_basis'))
        output.mass_unit = self.text(flux.get('mass_unit'))
        mode = metadata.get('mode', 'full')
        output.mode = self.text(mode if isinstance(mode, str) else repr(mode))
        if not isinstance(mode, str):
            self.invalid_mode_repr = _text(repr(mode))
        output.thermal_mode = self.text(metadata.get('thermal_mode'))
        output.temperature_transport = self.text(metadata.get('temperature_transport'))
        output.grid = self.grid(result.grid)
        state = flux.get('state')
        output.thermal_state = self.text(state) if isinstance(state, str) else None
        index = result.run_status.get('outer_index')
        output.outer_index = self.number(I, index) if type(index) is int and -(1 << 31) <= index < (1 << 31) else None
        parameters = metadata.get('parameters', {})
        diagnostics = metadata.get('diagnostics', {})
        output.thermal = self.thermal(flux, _read(diagnostics, 'model_h_balance', None) if dimension == 3 else None)
        output.fine = self.record(Fine, flux.get('fine'), self.fine)
        for index, side in enumerate('AB'):
            pressure = result.pressure_evidence.get(side)
            if mode != 'quick_design' or isinstance(pressure, Mapping):
                output.pressure[index] = self.record(Pressure, pressure, self.pressure)
        declarations = [Declaration(self.text(name), self.text(_read(row, 'unit', '')), self.text(row.get('state')) if isinstance(row, Mapping) and isinstance(row.get('state'), str) else None)
                        for name, row in result.field_metadata.items()]
        output.field_metadata, output.field_metadata_count = self.sequence(Declaration, declarations), len(declarations)
        containers: tuple[str, ...] = ('metadata.parameters', 'metadata.design_fields', 'metadata.diagnostics',
            'metadata.diagnostics.richardson_info', 'metadata.diagnostics.convergence_detail',
            'metadata.diagnostics.model_h_balance',
            'metadata.parameters.boundary_openings', 'metadata.parameters.boundary_openings.A',
            'metadata.parameters.boundary_openings.B', 'boundary_fluxes.report',
            'boundary_fluxes.report.A', 'boundary_fluxes.report.B')
        containers += tuple(prefix + '.' + name
            for prefix in ('boundary_fluxes.energy', 'boundary_fluxes.temperature',
                           'boundary_fluxes.fine.energy', 'boundary_fluxes.fine.temperature')
            for name in ('residual', 'source_integral', 'advective_out', 'diffusive_out'))
        containers += tuple(prefix + '.' + side
            for prefix in ('boundary_fluxes.model_h', 'boundary_fluxes.fine.model_h_balance')
            for side in ('A', 'B'))
        containers += tuple('boundary_fluxes.true_h.' + name
            for name in ('boundary_power', 'boundary_power.A', 'boundary_power.B'))
        absent = []
        for path in containers:
            value = {'metadata': metadata, 'boundary_fluxes': flux}
            for key in path.split('.'):
                if not isinstance(value, Mapping) or key not in value:
                    absent.append(path)
                    break
                value = value[key]
        output.absent_records, output.absent_record_count = self.strings(absent), len(absent)
        if query == 2:
            return
        output.fields, output.field_count = self.named(result.fields,
            finite_keys=tuple(name for name in result.fields if not name.endswith('_display')))
        self._qualification(metadata, diagnostics, parameters, dimension)
        if query == 3:
            return
        if mode == 'quick_design':
            self.quick = self._quick(metadata, flux, result.pressure_evidence)
            return
        for index, side in enumerate('AB'):
            output.active_fluids[index] = int(side in metadata.get('active_fluids', ('A', 'B')))
            output.direction[index] = self.number(I, _read(parameters, 'dir_' + side, _MISSING))
            temperature = _read(parameters, 'T_in' + side, _MISSING)
            self.inlet_temperature[index] = self.array(temperature)
            if temperature is None:
                self.none_values.append(ct.cast(self.inlet_temperature[index], ct.c_void_p).value)
            openings = _read(_read(parameters, 'boundary_openings', {}), side, {})
            output.inlet_geom_fraction[index] = self.array(_read(openings, 'in_geom_frac', _MISSING))
            output.outlet_geom_fraction[index] = self.array(_read(openings, 'out_geom_frac', _MISSING))
            output.rho_cp[index] = self.array(metadata.get('rho_cp_' + side, _MISSING))
        output.parameter_epsilon = self.array(_read(parameters, 'eps', _MISSING))
        output.design_epsilon = self.array(_read(metadata.get('design_fields', {}), 'eps_arr', _MISSING))
        self.split = self.array(metadata.get('split_A', _MISSING), preserve_origin=True)
        self.density = self.array(metadata.get('solid_density_kg_m3', _MISSING), preserve_origin=True)


    def _quick(self, metadata, flux, pressures):
        parameters = _read(metadata, 'parameters')
        output = QuickInput(3, ct.sizeof(QuickInput),
            model=self.label(_read(metadata, 'model')),
            arrangement=self.label(_read(parameters, 'arrangement')),
            hydraulic_diameter=self.quick_value(_read(parameters, 'D_h')), protocol=self.quick_protocols())
        properties = _read(metadata, 'properties')
        for index, side in enumerate('AB'):
            boundary, props, pressure = _read(flux, side), _read(properties, side), _read(pressures, side)
            output.sides[index] = QuickSide(
                self.quick_access(boundary), self.quick_access(props), self.quick_access(pressure),
                *(self.quick_value(_read(values, key)) for values, key in (
                    (boundary, 'inlet_temperature_K'), (boundary, 'mass_flow_kg_s'), (boundary, 'cp_J_kgK'),
                    (props, 'rho'), (boundary, 'velocity_m_s'), (props, 'mu'),
                    (pressure, 'inlet_absolute_Pa'), (pressure, 'outlet_absolute_Pa'))))
        return output

    def _qualification(self, metadata, diagnostics, parameters, dimension):
        output, result = self.raw, self.result
        detail = _read(diagnostics, 'convergence_detail', {})
        if isinstance(detail, _Fault):
            self.qualification_error = self.fault(self.pointer(I()), detail.error)
            return
        execution_state = result.run_status.get('execution')
        output.execution = self.text(execution_state if isinstance(execution_state, str) or execution_state is None else repr(execution_state))
        output.converged, failure = _equality_flag(result.run_status.get('converged'))
        if failure is not None:
            self.fault(ct.byref(output, Evidence.converged.offset), failure)
        gates, failures = [], []
        for name in ('simple_ok', 'ltne_ok', 'outer_converged', 'fields_finite', 'envelope_ok', 'richardson_ok'):
            if name not in detail:
                continue
            value = detail[name]
            flag, failure = _equality_flag(value)
            gates.append(Gate(name=_text(name), value=flag))
            failures.append(failure)
        output.convergence_gates, output.convergence_gate_count = self.sequence(Gate, gates), len(gates)
        for index, failure in enumerate(failures):
            if failure is not None:
                self.fault(ct.byref(output.convergence_gates[index], Gate.value.offset), failure)
        output.true_h_certificate = self.record(TrueCertificate,
            _read(diagnostics, 'true_h_balance', None), self.true_certificate)
        model = _read(diagnostics, 'model_h_balance', _MISSING)
        try:
            if isinstance(model, _Fault):
                raise model.error
            if dimension == 2 and model is not _MISSING:
                levels = list(model.items())
                output.model_certificates = self.sequence(ModelLevel,
                    [ModelLevel(level=self.text(level)) for level, _ in levels])
                output.model_certificate_count = len(levels)
                for index, (_, row) in enumerate(levels):
                    self.model(row, required=True, output=output.model_certificates[index].value)
            elif dimension == 3 and model is not _MISSING and model is not None:
                output.model_certificates = self.sequence(ModelLevel, [ModelLevel(level=b'main')])
                output.model_certificate_count = 1
                self.model({}, model, output=output.model_certificates[0].value)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            output.model_certificate_error = self.text(_Fault(error))
        for index, name in enumerate(('eps_A_strict', 'eps_A_strict_cellmax', 'eps_B_strict', 'eps_B_strict_cellmax')):
            output.strict_ratios[index] = self.number(D, _read(diagnostics, name, None))
        for index, side in enumerate('AB'):
            output.source_power[index] = self.number(D, _read(diagnostics, 'Q_s' + side, None))
        active_b = _read(parameters, 'fluid_B_cfg')
        if isinstance(active_b, _Fault):
            self.fault(ct.byref(output, Evidence.model_active_b.offset), active_b.error)
        else:
            output.model_active_b = int(active_b is not None)
        output.richardson_extrapolated = _truth(_read(_read(diagnostics, 'richardson_info', {}), 'extrapolated', None))
        execution = metadata.get('execution_record', {})
        self.execution_label = self.label(_read(execution, 'version', None))
        sides = _read(execution, 'sides', {})
        access = _read(sides, 'A', {})
        if isinstance(access, _Fault):
            self.fault(ct.byref(output, Evidence.executed_side_count.offset), access.error)
        try:
            if isinstance(sides, _Fault):
                raise sides.error
            if not isinstance(sides, Mapping):
                set(sides)
                sides.values()
            records = list(sides.items())
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            output.executed_sides = self.fault(self.pointer(ExecutionSide()), error)
            return
        output.executed_sides = self.sequence(ExecutionSide, [ExecutionSide() for _ in records])
        output.executed_side_count = len(records)
        for index, (name, row) in enumerate(records):
            target = output.executed_sides[index]
            target.side, target.fluid = self.text(name), self.text(_read(row, 'fluid', None))
            value = _read(row, 'solved', None)
            self.identity_flag(target, 'solved', value)
            if value is not None and type(value) is not bool and not isinstance(value, _Fault):
                try:
                    target.solved = -2 if bool(value) else -5
                except (TypeError, ValueError) as error:
                    self.fault(ct.byref(target, ExecutionSide.solved.offset), error)


def _spec(value):
    return Spec(*(_text(getattr(value, name)) for name in ('name', 'unit', 'definition_version', 'description')))


def _query(result, query, metric_spec=None, metrics=None):
    packed = _Evidence()
    output, diagnostics, token = Output(struct_size=ct.sizeof(Output)), core._Diagnostics(), ct.c_uint64()
    error = ct.create_string_buffer(4096)

    try:
        packed.pack(result, query)
        library = core.result_library.get()
        owner = weakref.proxy(packed)

        @Events
        def events(context, values, failure):
            try:
                core.notify(values.contents, stacklevel=6)
                return 0
            except BaseException as exception:
                identity = owner.token(exception)
                message = _text(str(exception))
                owner.keep.append(message)
                failure[0] = HostError(_cause(exception), 0, identity, message)
                return 1

        errors = packed.sequence(InputError, packed.errors)
        none_values = packed.sequence(ct.c_void_p, packed.none_values)
        borrowed = Input(2, ct.sizeof(Input), ct.pointer(packed.raw), errors, len(errors), none_values, len(none_values),
            packed.density, packed.split, packed.inlet_temperature, packed.invalid_mode_repr, packed.dimension_index, packed.dimension_slice, packed.qualification_error, None, events)
        selection = _spec(metric_spec) if metric_spec is not None else None
        rows = [Metric(_text(name), Spec(b'', b'', b'', b''), 0, 0., _text(value.status), None)
                for name, value in (metrics or {}).items()]
        supplied = packed.sequence(Metric, rows)
        if query in (0, 3):
            argument = packed.quick if packed.quick is not None else QuickInput(3, ct.sizeof(QuickInput),
                protocol=packed.quick_protocols())
            argument.execution_version = packed.execution_label
        else:
            # Applicability and physical-balance queries use no Quick operands, so the model stays NULL.
            argument = QuickInput(3, ct.sizeof(QuickInput))
        argument.host = ct.pointer(borrowed)
        call = library.bind('tpmshx_result_stage_query_v3',
            [P(type(argument)), ct.c_uint32, P(Spec), P(Metric), Z,
             P(Output), P(core._Diagnostics), P(ct.c_uint64), P(ct.c_char), Z])
        release = library.bind('tpmshx_result_stage_release_v1', [P(Output)], None)
        status = call(ct.byref(argument), query, ct.byref(selection) if selection is not None else None,
            supplied, len(rows), ct.byref(output), ct.byref(diagnostics), ct.byref(token), error, len(error))
        core.notify(diagnostics, stacklevel=5)
        if status:
            if token.value:
                raise packed.exceptions[token.value]
            message = error.value.decode('utf-8', errors='replace') or f'native result stage failed with status {status}'
            if status == 1:
                raise ValueError(message)
            if status == 2:
                raise MemoryError(message)
            if status == 4:
                cause = {1: ZeroDivisionError, 2: OverflowError, 3: ValueError, 4: TypeError,
                         5: IndexError, 6: KeyError, 7: NotImplementedError}.get(diagnostics.python_cause)
                if cause is None:
                    raise RuntimeError('native result stage returned an invalid numerical cause')
                if cause is KeyError:
                    message = ast.literal_eval(message)
                raise cause(message)
            raise RuntimeError(message)
        report = json.loads(output.json)
        if query == 1:
            return _restore_applicability_fields(report, result.metadata.get('applicability_evidence'))
        if query == 2:
            return _restore_balance_fields(report, result)
        if query == 3:
            return _restore_qualification_fields(report, result)
        _restore_qualification_fields(report['qualification'], result)
        restored = {}
        for index in range(output.metric_count):
            row = output.metrics[index]
            name = row.name.decode('utf-8')
            spec = metric_spec or MetricSpec(*(getattr(row.spec, key).decode('utf-8')
                for key in ('name', 'unit', 'definition_version', 'description')))
            restored[name] = MetricValue(row.value if row.has_value else None, spec,
                row.status.decode('utf-8'), row.reason.decode('utf-8'))
        return PerformanceResult(str(uuid4()), result.result_id, restored, report['qualification'])
    finally:
        try:
            if output.owner:
                release(ct.byref(output))
        finally:
            # Deferred tracebacks can refer to the query and its borrowed fields.
            packed.exceptions.clear()
            packed.array_errors.clear()


def _validated_query(result, query, metric_spec=None):
    try:
        return _query(result, query, metric_spec)
    except Exception:
        # Archived mappings retain their declaration error order on failure.
        validate_result_declarations(result)
        raise


def evaluate(result, metric_spec=None):
    return _validated_query(result, 0, metric_spec)


def evaluate_applicability(result):
    return _query(result, 1)


def evaluate_physical_balance(result):
    return _validated_query(result, 2)


def evaluate_qualification(result, metrics):
    return _query(result, 3, metrics=metrics)


def _restore_applicability_fields(report, evidence):
    if evidence is None or 'checks' not in report:
        return report
    for group, rows in report['checks'].items():
        restored = []
        for source, row in zip(evidence[group], rows, strict=True):
            output = dict(source)
            for name in ('allowed_bounds', 'allowance_fraction', 'status', 'within_limit',
                         'relative_extrapolation', 'reason'):
                if name in row:
                    output[name] = tuple(row[name]) if name == 'allowed_bounds' else row[name]
            restored.append(output)
        report['checks'][group] = restored
    report['missing'] = _restore_missing(report.get('missing', []), evidence)
    report['scope_notes'] = evidence['scope_notes']
    return report


def _restore_missing(rows, evidence):
    output = []
    for row in rows:
        if 'source' in row:
            match = next(value for value in evidence['required']
                if value['group'] == row['group'] and value['side'] == row['side']
                and tuple(value['source']) == tuple(row['source']))
            output.append(dict(match))
        else:
            output.append(row)
    return output


def _restore_qualification_fields(report, result):
    convergence = report['convergence']
    detail = result.metadata.get('diagnostics', {}).get('convergence_detail', {})
    convergence['gates'] = {name: detail[name] for name in convergence['gates']}
    convergence['thermal_state'] = result.boundary_fluxes.get('state')
    convergence['pressure_states'] = {side: result.field_metadata.get('P_report_' + side, {}).get('state')
        for side, value in result.pressure_evidence.items() if value is not None}
    report['execution']['state'] = result.run_status.get('execution')
    if 'balance' in report['physical']:
        _restore_balance_fields(report['physical']['balance'], result)
    application = report['applicability']
    evidence = result.metadata.get('applicability_evidence')
    if 'checks' in application:
        if evidence is None:
            application['missing'], application['scope_notes'] = (), ()
        else:
            inputs = [row for group in ('inlet', 'final') for row in evidence[group]]
            for row, source in zip(application['checks'], inputs, strict=True):
                row['source'] = source['source']
            application['missing'] = _restore_missing(application['missing'], evidence)
            application['scope_notes'] = evidence['scope_notes']
    return report


def _restore_balance_fields(report, result):
    report['physical_dimension'] = result.grid.get('dimension', result.metadata.get('dimension'))
    report['state'] = result.boundary_fluxes.get('state', 'not_recorded')
    report['outer_index'] = result.run_status.get('outer_index')
    return report


def copy_applicability(pointer, saved_inlet):
    """Copy selected evidence before the native result owner is released."""
    if not pointer or pointer.contents.version != b'applicability_evidence_v1':
        raise RuntimeError('native result lacks supported applicability evidence')
    value = pointer.contents
    if value.inlet_count < len(saved_inlet):
        raise RuntimeError('native applicability evidence lacks saved inlet rows')
    inlet = []
    for index in range(value.inlet_count):
        raw = value.inlet[index]
        # Saved rows retain host fields and scalar types absent from the C descriptor.
        row = dict(saved_inlet[index]) if index < len(saved_inlet) else _copy_range(raw)
        if raw.constraint is not None:
            row['constraint'] = raw.constraint.decode()
        inlet.append(row)
    return dict(version=value.version.decode(), inlet_recorded=bool(value.inlet_recorded),
        inlet=inlet, final=[_copy_range(value.final_state[index]) for index in range(value.final_count)],
        required=[dict(group=row.group.decode(), side=row.side.decode(),
            source=tuple(item.decode() for item in row.source[:row.source_count]))
            for row in value.required[:value.required_count]])


def _copy_range(value):
    row = {name: getattr(value, name).decode() for name in ('side', 'quantity', 'stage', 'layout', 'unit')}
    row.update(source=tuple(item.decode() for item in value.source[:value.source_count]),
        captured=bool(value.captured), shape=tuple(value.shape[:value.rank]), bounds=tuple(value.bounds))
    for name in ('constraint', 'reason'):
        if getattr(value, name) is not None:
            row[name] = getattr(value, name).decode()
    if value.captured:
        row.update({name: getattr(value, name) for name in ('size', 'low', 'high', 'nonfinite')})
        for name in ('minimum', 'maximum'):
            row[name] = ((getattr(value, name)[0], tuple(getattr(value, name + '_index')[:value.rank]))
                         if getattr(value, name) else None)
    return row


_ZoneTemperatures = record('ZoneTemperatures', [('cells', Z), ('mean', D * 3),
    ('deviation', D * 3), ('minimum', D * 2), ('maximum', D * 2)])


def _zone_temperatures(widths, temperatures, zone_id, zones, lengths, fractions, *, solver_library=None):
    """Read the native area-weighted summary for each saved zone."""
    widths = [core.array(value) for value in widths]
    fields = [core.array(value) for value in temperatures]
    labels = core.array(zone_id)
    output = (_ZoneTemperatures * len(zones))()
    boundaries = [(D * len(axis))(*axis) for axis in fractions]
    positions = [(D * len(axis))() for axis in fractions]
    name = ('tpmshx_stage_run_2d_zone_temperatures_v1' if solver_library is not None
            else 'tpmshx_result_zone_temperatures_2d_v1')
    core.call(name, [AP, AP, AP, Z, P(_ZoneTemperatures), D, D, P(D), Z, P(D), P(D), Z, P(D)],
              (core._Array * 2)(*(value.raw for value in widths)), ct.byref(labels.raw),
              (core._Array * 3)(*(value.raw for value in fields)), len(zones), output, *lengths,
              boundaries[0], len(boundaries[0]), positions[0], boundaries[1], len(boundaries[1]), positions[1],
              library=solver_library)
    stats = []
    for (name, length, wall), row in zip(zones, output):
        item = dict(name=name, n_cells=row.cells)
        if row.cells:
            item.update(L_mm=length, t_mm=wall)
            for phase, name in enumerate(('Ta', 'Tb', 'Ts')):
                item[name + '_mean'] = row.mean[phase]
                item[name + '_std'] = row.deviation[phase]
                if phase < 2:
                    item[name + '_min'] = row.minimum[phase]
                    item[name + '_max'] = row.maximum[phase]
        stats.append(item)
    return stats, list(positions[0]), list(positions[1])

def zone_result(cfg, prepared, temperature, *, solver_library=None):
    axis, design = cfg['z_axis'], cfg['za']
    if cfg['zone_config'] is None or design is None:
        return None
    if axis == 'continuous':
        return dict(axis_dir=axis, boundaries=[], boundaries_x=[], boundaries_y=[], stats=[])
    if axis == 'grid':
        zones = [(f'g{i}', cell['L'], cell['t']) for i, cell in enumerate(design.get('grid_cells', ()))]
        fractions = design.get('x_bounds', ()), design.get('y_bounds', ())
    else:
        config = cfg['zone_config']
        if isinstance(config, Mapping):
            definitions = config['zones']
            zones = [(row['name'], row['L_mm'], row['t_mm']) for row in definitions]
            ends = [row['y_frac_end'] for row in definitions[:-1]]
        else:
            definitions = config.zones
            zones = [(zone.name, zone.L_mm, zone.t_mm) for zone in definitions]
            ends = [zone.y_frac_end for zone in definitions[:-1]]
        fractions = ((), ends) if axis == 'y' else (ends, ())
    stats, x, y = _zone_temperatures((prepared['energy_dx'], prepared['energy_dy']), temperature,
                                     design['zone_id'], zones, (cfg['L'], cfg['H']), fractions,
                                     solver_library=solver_library)
    from sjtu_tpmshx.run_control.logutil import log_zone_report
    log_zone_report(stats)
    if axis == 'grid':
        return dict(axis_dir=axis, boundaries=[], boundaries_x=x, boundaries_y=y, stats=stats)
    return dict(axis_dir=axis, boundaries=y if axis == 'y' else x, boundaries_x=None, boundaries_y=None, stats=stats)
