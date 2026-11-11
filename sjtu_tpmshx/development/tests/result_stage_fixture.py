"""Pack recorded test evidence for the independent result stage C ABI."""
import ctypes as ct
import json
from dataclasses import asdict

from sjtu_tpmshx.shared import _native_result as core

P = ct.POINTER
S, I, Z, D = ct.c_char_p, ct.c_int, ct.c_size_t, ct.c_double
AP, SP = P(core._Array), P(core._Scalar)


def record(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


Named = record('Named', [('name', S), ('value', core._Array)])
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


def text(value):
    return None if value is None else value.encode('utf-8')


def truth(value):
    if value is None: return -1
    if type(value) is bool: return int(value)
    if value == False: return -3
    return -2 if value else -5


class PackedEvidence:
    def __init__(self, result):
        self.keep = []
        self.result = result
        m, f, p = result.metadata, result.boundary_fluxes, result.metadata.get('parameters', {})
        diagnostics = m.get('diagnostics', {})
        d = result.grid.get('dimension', m.get('dimension', 0))
        e = self.raw = Evidence(abi_version=1, struct_size=ct.sizeof(Evidence),
            result_id=text(result.result_id), dimension=d, metadata_dimension=self.number(I, m.get('dimension')),
            quantity_basis=text(m.get('quantity_basis')), mass_unit=text(f.get('mass_unit')), mode=text(m.get('mode')),
            thermal_mode=text(m.get('thermal_mode')), temperature_transport=text(m.get('temperature_transport')))
        e.grid = self.grid(result.grid)
        e.fields, e.field_count = self.named(result.fields)
        declarations = [Declaration(text(k), text(v.get('unit', '')), text(v.get('state'))) for k, v in result.field_metadata.items()]
        e.field_metadata, e.field_metadata_count = self.sequence(Declaration, declarations), len(declarations)
        for i, side in enumerate('AB'):
            if result.pressure_evidence.get(side) is not None:
                row = result.pressure_evidence[side]
                pressure = Pressure(self.array(row.get('P')), self.grid(row), self.array(row.get('inlet_frac', row.get('inlet_fraction'))),
                    self.array(row.get('outlet_frac', row.get('outlet_fraction'))), self.array(row.get('outlet_geom_frac')),
                    self.scalar(row.get('P_ref_abs', row.get('reference_abs_Pa'))), self.scalar(row.get('inlet_absolute_Pa')),
                    self.scalar(row.get('outlet_absolute_Pa')), text(row.get('unit')))
                e.pressure[i] = self.pointer(pressure)
        e.thermal = self.thermal(f, diagnostics.get('model_h_balance') if d == 3 else None)
        fine = f.get('fine')
        if fine is not None:
            fine_record = Fine(grid=self.grid(fine), thermal=self.thermal(fine), empty_record=int(not fine))
            fine_record.fields, fine_record.field_count = self.named({k: fine[k] for k in ('Ta', 'Tb', 'Ts', 'ucA', 'vcA', 'ucB', 'vcB') if fine.get(k) is not None})
            for i, side in enumerate('AB'):
                fine_record.rho_cp[i] = self.array(fine.get('rho_cp_' + side))
                fine_record.inlet_fraction[i] = self.array(fine.get('inlet_' + side))
                fine_record.outlet_fraction[i] = self.array(fine.get('outlet_' + side))
            fine_record.epsilon = self.array(fine.get('eps'))
            e.fine = self.pointer(fine_record)
        e.thermal_state, e.execution = text(f.get('state')), text(result.run_status.get('execution'))
        e.converged = truth(result.run_status.get('converged'))
        e.outer_index = self.number(I, result.run_status.get('outer_index'))
        detail = diagnostics.get('convergence_detail', {})
        gates = []
        for k in ('simple_ok', 'ltne_ok', 'outer_converged', 'fields_finite', 'envelope_ok', 'richardson_ok'):
            if k not in detail: continue
            value = detail[k]
            gate = Gate(text(k), truth(value))
            if value is not None and type(value) is not bool:
                if isinstance(value, str): gate.recorded_text = text(value)
                else: gate.recorded_number = self.scalar(value)
            gates.append(gate)
        e.convergence_gates, e.convergence_gate_count = self.sequence(Gate, gates), len(gates)
        true_certificate = diagnostics.get('true_h_balance')
        if true_certificate:
            row = true_certificate
            cert = TrueCertificate(converged=truth(row.get('converged')), clip_counts=self.array(row.get('enthalpy_clip_counts', {}).get('total')))
            for i, name in enumerate(('coupled', 'equation')):
                cert.ratios[i] = self.scalar(row.get(name + '_energy_balance', {}).get('ratio'))
                cert.tolerances[i] = self.scalar(row.get('effective_settings', {}).get(name + '_energy_tol'))
            e.true_h_certificate = self.pointer(cert)
        levels = []
        if d == 2:
            for level, row in (diagnostics.get('model_h_balance') or {}).items():
                if isinstance(row, dict) or hasattr(row, 'get'):
                    levels.append(ModelLevel(text(level), self.model(row)))
                elif e.model_certificate_error is None:
                    e.model_certificate_error = text(f"'{type(row).__name__}' object is not subscriptable")
        elif diagnostics.get('model_h_balance') is not None:
            levels.append(ModelLevel(b'main', self.model({}, diagnostics['model_h_balance'])))
        e.model_certificates, e.model_certificate_count = self.sequence(ModelLevel, levels), len(levels)
        for i, key in enumerate(('eps_A_strict', 'eps_A_strict_cellmax', 'eps_B_strict', 'eps_B_strict_cellmax')):
            e.strict_ratios[i] = self.number(D, diagnostics.get(key))
        for i, side in enumerate('AB'):
            e.source_power[i] = self.number(D, diagnostics.get('Q_s' + side))
        e.model_active_b = -1 if 'fluid_B_cfg' not in p else int(p['fluid_B_cfg'] is not None)
        e.richardson_extrapolated = truth(diagnostics.get('richardson_info', {}).get('extrapolated'))
        execution = m.get('execution_record', {})
        e.execution_version = text(execution.get('version'))
        sides = [ExecutionSide(text(k), text(v.get('fluid')), truth(v.get('solved'))) for k, v in execution.get('sides', {}).items()]
        e.executed_sides, e.executed_side_count = self.sequence(ExecutionSide, sides), len(sides)
        e.applicability = self.applicability(m.get('applicability_evidence'))
        for i, side in enumerate('AB'):
            e.active_fluids[i] = int(side in m.get('active_fluids', ('A', 'B')))
            e.direction[i] = self.number(I, p.get('dir_' + side))
            e.inlet_temperature[i] = self.scalar(p.get('T_in' + side))
            openings = p.get('boundary_openings', {}).get(side, {})
            e.inlet_geom_fraction[i] = self.array(openings.get('in_geom_frac'))
            e.outlet_geom_fraction[i] = self.array(openings.get('out_geom_frac'))
            e.rho_cp[i] = self.array(m.get('rho_cp_' + side))
            boundary, props = f.get(side, {}), m.get('properties', {}).get(side, {})
            e.quick[i] = Quick(self.scalar(boundary.get('inlet_temperature_K')), self.scalar(boundary.get('mass_flow_kg_s')),
                self.scalar(boundary.get('cp_J_kgK')), self.scalar(props.get('rho')), self.scalar(boundary.get('velocity_m_s')), self.scalar(props.get('mu')))
        e.parameter_epsilon, e.design_epsilon = self.array(p.get('eps')), self.array(m.get('design_fields', {}).get('eps_arr'))
        e.split_a, e.solid_density = self.scalar(m.get('split_A')), self.scalar(m.get('solid_density_kg_m3'))
        e.quick_model, e.arrangement = text(m.get('model')), text(p.get('arrangement'))
        e.hydraulic_diameter = self.scalar(p.get('D_h'))
        containers = ('metadata.parameters', 'metadata.design_fields', 'metadata.diagnostics',
            'metadata.diagnostics.richardson_info', 'metadata.diagnostics.convergence_detail',
            'metadata.parameters.boundary_openings', 'metadata.parameters.boundary_openings.A',
            'metadata.parameters.boundary_openings.B', 'boundary_fluxes.report',
            'boundary_fluxes.report.A', 'boundary_fluxes.report.B', 'metadata.properties',
            'metadata.properties.A', 'metadata.properties.B', 'boundary_fluxes.A', 'boundary_fluxes.B')
        containers += tuple(prefix + '.' + field
            for prefix in ('boundary_fluxes.energy', 'boundary_fluxes.temperature',
                           'boundary_fluxes.fine.energy', 'boundary_fluxes.fine.temperature')
            for field in ('residual', 'source_integral', 'advective_out', 'diffusive_out'))
        containers += tuple('boundary_fluxes.true_h.' + field
            for field in ('boundary_power', 'boundary_power.A', 'boundary_power.B'))
        absent = []
        for path in containers:
            node = {'metadata': m, 'boundary_fluxes': f}
            for key in path.split('.'):
                if node is None or not hasattr(node, '__contains__') or key not in node:
                    absent.append(path)
                    break
                node = node[key]
        e.absent_records, e.absent_record_count = self.strings(absent), len(absent)

    def pointer(self, value):
        self.keep.append(value)
        return ct.pointer(value)

    def sequence(self, kind, values):
        out = (kind * len(values))(*values)
        self.keep.append(out)
        return out

    def strings(self, values):
        return self.sequence(S, [text(v) for v in values])

    def number(self, kind, value):
        return None if value is None else self.pointer(kind(value))

    def scalar(self, value):
        return None if value is None else self.pointer(core.scalar(value))

    def array(self, value):
        if value is None:
            return None
        owner = core.array(value)
        self.keep.append(owner)
        return self.pointer(owner.raw)

    def array_sequence(self, values):
        owners = [core.array(v) for v in values]
        self.keep.extend(owners)
        return self.sequence(core._Array, [v.raw for v in owners])

    def named(self, values):
        values = values or {}
        rows = [Named(text(k), self.array(v).contents) for k, v in values.items()]
        return self.sequence(Named, rows), len(rows)

    def grid(self, values):
        out = Grid()
        for i, axis in enumerate('xyz'):
            out.widths[i] = self.array(values.get('d' + axis))
        return out

    def energy(self, values):
        if values is None:
            return None
        out = Energy(definition=text(values.get('definition')), power_units=text(values.get('power_units')),
            physical_dimension=values.get('physical_dimension', 0), physical_boundary_complete=truth(values.get('physical_boundary_complete')))
        phases = []
        for name, solved in values.get('solved', {}).items():
            phase = Phase(name=text(name), solved=truth(solved), residual=self.array(values.get('residual', {}).get(name)),
                source_integral=self.array(values.get('source_integral', {}).get(name)))
            phase.advective_out, phase.advective_count = self.named(values.get('advective_out', {}).get(name))
            phase.diffusive_out, phase.diffusive_count = self.named(values.get('diffusive_out', {}).get(name))
            phases.append(phase)
        out.phases, out.phase_count = self.sequence(Phase, phases), len(phases)
        out.prescribed_b_power = self.array(values.get('prescribed_b_power'))
        return self.pointer(out)

    def model(self, values, certificate=None):
        certificate = values if certificate is None else certificate
        out = Model(passed=truth(certificate.get('passed')), physical_boundary_complete=truth(certificate.get('physical_boundary_complete')))
        for i, side in enumerate('AB'):
            row = values.get(side, {})
            cert = certificate.get('sides', {}).get(side, row)
            out.sides[i].physical_boundary_complete = truth(cert.get('physical_boundary_complete'))
            powers = row.get('h_faces_W_per_m', ())
            out.sides[i].staggered_power, out.sides[i].staggered_count = self.array_sequence(powers), len(powers)
            out.sides[i].boundary_power, out.sides[i].boundary_count = self.named({k: row[k] for k in ('x-', 'x+', 'y-', 'y+', 'z-', 'z+') if k in row})
        return out

    def thermal(self, values, model_certificate=None):
        out = Thermal()
        for i, side in enumerate('AB'):
            mass = values.get('mass_' + side) or ()
            out.mass[i], out.mass_count[i] = self.array_sequence(mass), len(mass)
            out.report_direction[i] = self.number(I, values.get('report', {}).get(side, {}).get('direction'))
        out.energy, out.temperature = self.energy(values.get('energy')), self.energy(values.get('temperature'))
        model = values.get('model_h', values.get('model_h_balance'))
        if model is not None:
            out.model_h = self.pointer(self.model(model, model_certificate))
        native = values.get('true_h')
        if native is not None:
            row = TrueH(energy_algorithm=text(native.get('energy_algorithm')), boundary_power_units=text(native.get('boundary_power_units')),
                energy_algorithm_version=self.number(I, int(native['energy_algorithm_version']) if native.get('energy_algorithm_version') is not None else None),
                invalid_version_type=int('energy_algorithm_version' in native and type(native['energy_algorithm_version']) is not int),
                physical_boundary_complete=truth(native['physical_boundary_complete']) if 'physical_boundary_complete' in native else -4)
            for i, side in enumerate('AB'):
                row.enthalpy[i], row.inlet_enthalpy[i] = self.array(native.get('h_' + side)), self.scalar(native.get('h_in_' + side))
                mass = native.get('mass_flux_' + side) or ()
                row.mass[i], row.mass_count[i] = self.array_sequence(mass), len(mass)
                row.boundary_power[i], row.boundary_count[i] = self.named(native.get('boundary_power', {}).get(side, {}))
            out.true_h = self.pointer(row)
        return out

    def ranges(self, values):
        out = []
        for value in values:
            sample = Range(captured=truth(value['captured']), side=text(value['side']), quantity=text(value['quantity']),
                constraint=text(value.get('constraint')), stage=text(value.get('stage')), layout=text(value.get('layout')),
                unit=text(value.get('unit')), reason=text(value.get('reason')))
            source, shape = value['source'], value.get('shape', ())
            sample.source, sample.source_count = self.strings(source), len(source)
            sample.shape, sample.rank = self.sequence(Z, shape), len(shape)
            sample.bounds = (D * 2)(*value.get('bounds', (0, 0)))
            for key in ('size', 'low', 'high', 'nonfinite'):
                setattr(sample, key, value.get(key, 0))
            for key in ('minimum', 'maximum'):
                extreme = value.get(key)
                if extreme is not None:
                    setattr(sample, key, self.number(D, extreme[0]))
                    setattr(sample, key + '_index', self.sequence(Z, extreme[1]))
            out.append(sample)
        return self.sequence(Range, out), len(out)

    def applicability(self, value):
        if value is None:
            return None
        out = Applicability(version=text(value['version']), inlet_recorded=truth(value['inlet_recorded']))
        out.inlet, out.inlet_count = self.ranges(value['inlet'])
        out.final_state, out.final_count = self.ranges(value['final'])
        required = [Required(text(v['group']), text(v['side']), self.strings(v['source']), len(v['source'])) for v in value['required']]
        out.required, out.required_count = self.sequence(Required, required), len(required)
        out.scope_notes, out.scope_note_count = self.strings(value['scope_notes']), len(value['scope_notes'])
        return self.pointer(out)


def native_report(result, library, query='evaluate', request=None, metrics=None):
    packed, output, error = PackedEvidence(result), Output(struct_size=ct.sizeof(Output)), ct.create_string_buffer(4096)
    function = getattr(library, 'tpmshx_result_stage_' + query + '_v1')
    arguments, types = [ct.byref(packed.raw)], [P(Evidence)]
    if query == 'evaluate':
        spec = None if request is None else Spec(*(text(getattr(request, key)) for key in ('name', 'unit', 'definition_version', 'description')))
        arguments.append(None if spec is None else ct.byref(spec))
        types.append(P(Spec))
    if query == 'qualification':
        records = []
        for key, metric in metrics.items():
            spec = Spec(*(text(getattr(metric.spec, key)) for key in ('name', 'unit', 'definition_version', 'description')))
            records.append(Metric(text(key), spec, int(metric.value is not None), metric.value or 0., text(metric.status), text(metric.reason)))
        values = (Metric * len(records))(*records)
        arguments.extend((values, len(values)))
        types.extend((P(Metric), Z))
    arguments.extend((ct.byref(output), error, len(error)))
    function.argtypes, function.restype = types + [P(Output), P(ct.c_char), Z], I
    status = function(*arguments)
    if status:
        raise ValueError(error.value.decode())
    release = library.tpmshx_result_stage_release_v1
    release.argtypes, release.restype = [P(Output)], None
    try:
        return json.loads(output.json)
    finally:
        release(ct.byref(output))


def python_report(result, request=None):
    from sjtu_tpmshx.postprocess.api import evaluate
    value = evaluate(result, request)
    return {'source_result_id': value.source_result_id,
            'metrics': {k: asdict(v) for k, v in value.metrics.items()},
            'qualification': thaw(value.qualification)}


def thaw(value):
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    return value
