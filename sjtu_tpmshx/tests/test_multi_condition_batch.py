"""Serial batches retain real portable evidence and every requested condition."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.optimization import multi_condition as batch
from sjtu_tpmshx.postprocess import api as postprocess
from sjtu_tpmshx.solvers import api as execution


def test_batch_recovery_parses_prescribed_flow_before_old_speed(tmp_path):
    from sjtu_tpmshx.domain.paused_run import PausedRun
    from sjtu_tpmshx.tests.test_multi_condition_optimizer import _conditions as search_conditions
    name, config, a, b = search_conditions(3)[0]
    config.df_mode = 'experimental'
    config.fluid_A.u_mps = .001
    with pytest.raises(ValueError):
        config.validate()
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        batch._evaluate_condition_batch([(name, config, a, b)], output_dir=source,
            workers=1, pause_check=lambda: True)
    with pytest.raises(CancelledError):
        batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path / 'continued',
            workers=1, control=RunControl(cancel_check=lambda: True))
    saved = json.loads((tmp_path / 'continued/batch.json').read_text())
    assert saved['status'] == 'cancelled' and saved['conditions'][0]['status'] == 'not_run'


def _conditions(count=3):
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.04, H_dom_m=.04, Lz_m=.02,
                                L_cell_mm=7., t_wall_mm=.6),
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3),
        solver=SolverConfig(Nx=4, Ny=4, Nz=2), extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [6.3, 6.4, 6.5, 6.4, 6.5, 6.6, 6.5, 6.6, 6.7] + [.4]*9,
            'n_ctrl_x': 3, 'n_ctrl_y': 3, 'symmetric_y': False, 'spline_order': 2,
            'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    return [(name, replace(config, fluid_A=replace(config.fluid_A, T_in_K=380. + 10*i)),
             .001 * (i+1), .02 * (i+1)) for i, name in enumerate(('low', 'mid', 'high')[:count])]


def _native(case, *, q=100., dp_a=20., dp_b=40., index=0):
    """Hand-checkable native boundaries, following postprocess_tm1/test_three_d.

    Only numerical solving is replaced. Case preparation, native reductions,
    archive validation, HDF5 and strict metric JSON use production code.
    """
    shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
    pressure, faces, report = {}, {}, {}
    for side, dp in (('A', dp_a), ('B', dp_b)):
        axes = case.parameters['prepared']['axes'][side]
        widths = np.asarray(axes['dstream'])
        centres = np.cumsum(widths) - widths/2
        p = np.broadcast_to(dp * (1 - centres[None, :, None]/widths.sum()),
                            (axes['N_cross1'], axes['N_stream'], axes['N_cross2'])).copy()
        openings = case.parameters['prepared']['openings'][side]
        pressure[side] = dict(P=p, dx=axes['dcross1'], dy=widths, dz=axes['dcross2'],
                              inlet_frac=openings['inlet'], outlet_frac=openings['outlet'])
        inlet_eps = np.take(case.design_fields['eps_' + side],
                            -1 if axes['is_reverse'] else 0, axis=axes['stream_real_axis'])
        inlet_area = np.asarray(axes['dcross1'])[:, None] * np.asarray(axes['dcross2'])[None, :]
        inlet_mass = (case.parameters['u_' + side]
                      * case.parameters['prepared']['properties'][side]['rho']
                      * inlet_eps * openings['inlet'] * inlet_area)
        mass = []
        for axis in range(3):
            face_shape = list(shape)
            face_shape[axis] += 1
            value = np.zeros(face_shape)
            if axis == axes['stream_real_axis']:
                value[:] = (-1. if axes['is_reverse'] else 1.) * np.expand_dims(inlet_mass, axis)
            mass.append(value)
        faces['mass_' + side] = tuple(mass)
        report[side] = {'direction': case.parameters['fluid_' + side + '_cfg']['dir']}
    ledger = {side: {axis + sign: np.zeros(tuple(n for i, n in enumerate(shape) if i != a))
                     for a, axis in enumerate('xyz') for sign in ('-', '+')}
              for side in ('A', 'B')}
    for side, name, value in (('A', 'x-', -2*q), ('A', 'x+', q),
                              ('B', 'y+', -q), ('B', 'y-', 2*q)):
        ledger[side][name].flat[0] = value
    # Exact analytic budgets with independent range observations for consumer tests.
    from sjtu_tpmshx.tests.postprocess_tm1.test_applicability import result_with_evidence
    all_phases = ('A', 'B', 'solid')
    zeros = {name: np.zeros_like(value) for name, value in ledger['A'].items()}
    faces.update(report=report, model_h=ledger, state='analytic last thermal input', energy=dict(
        definition='physical_heat_ledger_v1', physical_dimension=3, power_units='W',
        physical_boundary_complete=True, solved=dict.fromkeys(all_phases, True),
        residual={phase: np.zeros(shape) for phase in all_phases},
        advective_out=dict(**ledger, solid=zeros),
        diffusive_out={phase: zeros for phase in all_phases},
        source_integral=dict.fromkeys(all_phases, 0.), prescribed_b_power=0.))
    fields = {'Ta': np.full(shape, 350.), 'Tb': np.full(shape, 320.), 'Ts': np.full(shape, 335.),
              'h_vB': np.full(shape, 1000.)}
    return FieldResult(
        str(uuid4()), case.case_id, 'analytic-native-test', grid=case.grid, fields=fields,
        field_metadata={name: dict(unit='W/(m3 K)' if name == 'h_vB' else 'K',
                                   axes=('x', 'y', 'z'), location='cell',
                                   state='analytic main thermal state') for name in fields},
        boundary_fluxes=faces, pressure_evidence=pressure,
        run_status={'execution': 'completed', 'converged': True}, model_refs=case.model_refs,
        metadata={'applicability_evidence': result_with_evidence().metadata['applicability_evidence'],
                  'execution_record': {'version': 'full_execution_v1', 'sides': {
                      side: dict(fluid=case.config_snapshot['fluid_' + side]['type'], solved=True)
                      for side in 'AB'}}, 'dimension': 3, 'quantity_basis': 'total', 'thermal_mode': 'model_h',
                  'parameters': case.parameters, 'fixture_index': index,
                  'design_mode': case.metadata['design_mode'], 'model_roles': case.metadata['model_roles'],
                  'df_metadata': {'mode': case.parameters['df_mode']},
                  'solid_density_kg_m3': 8000., 'design_fields': case.design_fields,
                  # The analytic ledger removes q from hot A and adds q to cold B;
                  # its two solid-to-fluid sources equal those signed budgets.
                  'diagnostics': {'eps_A_strict': 0., 'eps_A_strict_cellmax': 0.,
                                  'eps_B_strict': 0., 'eps_B_strict_cellmax': 0.,
                                  'Q_sA': -q, 'Q_sB': q,
                                  'model_h_balance': {'physical_boundary_complete': True, 'sides': {
                      side: {'physical_boundary_complete': True} for side in ('A', 'B')}}}})


def _baseline(conditions):
    rows = []
    for index, (condition_id, config, mdot_a, mdot_b) in enumerate(conditions):
        case = batch.prepare_fixed_mass_flow_case(
            replace(config, zones=ZoneInputConfig()),
            mass_flow_A_kg_s=mdot_a, mass_flow_B_kg_s=mdot_b, case_id=f'reference-{index}')
        field = _native(case)
        rows.append((condition_id, field, postprocess.evaluate(field)))
    return rows


def _manifest(directory):
    return json.loads((directory / 'batch.json').read_text(encoding='utf-8'))


@pytest.fixture
def native_control(tmp_path):
    library = tmp_path / 'analytic-library'
    library.write_bytes(b'non-executable test data')
    return RunControl(native_library=str(library), cpu_threads=1)


def _patch_solve(monkeypatch, solve):
    from sjtu_tpmshx.workflows import recovery
    monkeypatch.setattr(execution, 'run_case', solve)
    monkeypatch.setattr(recovery, 'run_case', lambda case, control, **kwargs: solve(case, control))


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('completed', [False, True])
def test_historical_batch_grid_recovery_never_prepares_again(tmp_path, monkeypatch, native_control,
                                                            enabled, completed):
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.result_io import save_result
    _patch_solve(monkeypatch, lambda case, control: _native(case))
    source = tmp_path / 'source'
    record = batch.evaluate_condition_batch(_conditions(1), output_dir=source, control=native_control, workers=1)
    assert record['status'] == 'completed'
    record = _manifest(source)
    path = source / 'batch-input.json'
    inputs = json.loads(path.read_text())
    inputs[0]['config']['flags']['wall_refine_3d'] = enabled
    path.write_text(json.dumps(inputs))
    row = record['conditions'][0]
    for path in (source / row['case_file'], source / row['directory'] / 'run/case.h5'):
        case = load_case(path)
        snapshot, parameters = mutable_data(case.config_snapshot), mutable_data(case.parameters)
        snapshot['flags']['wall_refine_3d'] = enabled
        parameters['wall_refine_3d'] = enabled
        save_case(replace(case, config_snapshot=snapshot, parameters=parameters), path)
    field = load_result(source / row['result_file'])
    metadata = mutable_data(field.metadata)
    metadata['parameters']['wall_refine_3d'] = enabled
    save_result(replace(field, metadata=metadata), source / row['result_file'])
    if not completed:
        row['status'] = record['status'] = 'cancelled'
        (source / 'batch.json').write_text(json.dumps(record))
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    monkeypatch.setattr(batch, 'prepare_fixed_mass_flow_case',
                        lambda *a, **k: pytest.fail('recovery rebuilt a saved grid'))
    target = tmp_path / 'resumed'
    resumed = batch.resume_condition_batch(source / 'batch.json', output_dir=target,
                                            control=native_control, workers=1)
    assert resumed['status'] == 'completed'
    assert resumed['conditions'][0]['recovery_mode'] == ('completed_copy' if completed else 'prepared_restart')
    restored = load_case(target / resumed['conditions'][0]['case_file'])
    assert restored.config_snapshot['flags']['wall_refine_3d'] is enabled
    for axis in 'xyz':
        np.testing.assert_array_equal(restored.grid['d' + axis], case.grid['d' + axis])
    again = batch.resume_condition_batch(target / 'batch.json', output_dir=tmp_path / 'again',
                                          control=native_control, workers=1)
    assert again['status'] == 'completed'
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()} == before


def test_historical_batch_without_saved_grid_cannot_use_a_new_constructor(tmp_path, monkeypatch, native_control):
    from sjtu_tpmshx.domain.paused_run import PausedRun
    source = tmp_path / 'source'
    with pytest.raises(PausedRun):
        batch._evaluate_condition_batch(_conditions(1), output_dir=source,
            control=native_control, workers=1, pause_check=lambda: True)
    path = source / 'batch-input.json'
    inputs = json.loads(path.read_text())
    inputs[0]['config']['flags']['wall_refine_3d'] = True
    path.write_text(json.dumps(inputs))
    monkeypatch.setattr(batch, 'prepare_fixed_mass_flow_case',
                        lambda *a, **k: pytest.fail('retired input reached grid construction'))
    resumed = batch.resume_condition_batch(source / 'batch.json', output_dir=tmp_path / 'resumed',
                                            control=native_control, workers=1)
    assert resumed['status'] == 'failed'
    assert 'wall_refine_3d is retired' in resumed['conditions'][0]['reason']


def test_solver_patch_restores_lazily_imported_recovery():
    import subprocess
    import sys

    child = subprocess.run([sys.executable, '-c', '''
import pytest
from sjtu_tpmshx.tests.test_multi_condition_batch import _patch_solve
from sjtu_tpmshx.solvers import api
original = api.run_case
with pytest.MonkeyPatch.context() as patch:
    _patch_solve(patch, lambda *args: None)
from sjtu_tpmshx.workflows import recovery
assert api.run_case is original and recovery.run_case is original
'''], text=True, capture_output=True, timeout=30)
    assert child.returncode == 0, child.stderr


@pytest.mark.parametrize('fluid', ['co2', 'sco2'])
def test_real_fluid_batch_reaches_the_original_solver_and_keeps_failure(tmp_path, monkeypatch, fluid, native_control):
    from sjtu_tpmshx.tests.test_co2_model import co2_config
    from sjtu_tpmshx.preprocess.api import prepare_inlet_mass_capacities
    config = co2_config(3)
    config.fluid_A.type = fluid
    capacity = prepare_inlet_mass_capacities(config)
    targets = [capacity[s]*getattr(config, 'fluid_' + s).u_mps for s in 'AB']
    def solve(case, control):
        assert case.config_snapshot['fluid_A']['type'] == fluid
        raise RuntimeError('recorded true-h solver failure')
    _patch_solve(monkeypatch, solve)
    report = batch.evaluate_condition_batch([('real', config, *targets)], output_dir=tmp_path/'batch', workers=1, control=native_control)
    row = report['conditions'][0]
    assert report['status'] == row['status'] == 'failed' and report['objectives'] is None
    assert row['stage'] == 'solve' and 'recorded true-h solver failure' in row['reason']


def test_batch_requires_the_same_fluid_pair_at_every_condition(tmp_path, native_control):
    conditions = _conditions(2)
    name, config, a, b = conditions[1]
    conditions[1] = (name, replace(config, fluid_A=replace(config.fluid_A, type='co2')), a, b)
    with pytest.raises(ValueError, match='must be fixed'):
        batch.evaluate_condition_batch(conditions, output_dir=tmp_path/'batch', workers=1, control=native_control)
    assert not (tmp_path/'batch').exists()


def test_success_keeps_independent_case_native_and_metric_files(tmp_path, monkeypatch):
    conditions = _conditions(2)
    baseline = _baseline(conditions)
    prepared, progress = [], []

    def solve(case, control):
        assert control.backend == 'cpp'
        prepared.append(case)
        for percent in (0, 40, 100):
            control.report_progress(percent)
        return _native(case, q=110., dp_a=10., dp_b=60.)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / 'success'
    library = tmp_path / 'test-library.dylib'
    library.write_bytes(b'non-executable test data')
    result = batch.evaluate_condition_batch(conditions, output_dir=directory,
        baseline=baseline, control=RunControl( progress=progress.append,
                                             native_library=str(library)), workers=1)
    manifest = _manifest(directory)
    assert result['status'] == manifest['status'] == 'completed'
    assert result['backend'] == manifest['backend'] == 'cpp'
    assert result['batch_id'] == manifest['batch_id']
    assert result['objectives'] == manifest['objectives'] == pytest.approx(
        {'heat_gain_percent': 10., 'pressure_ratio': 1.})
    assert [row['condition_id'] for row in manifest['conditions']] == ['low', 'mid']
    assert [row['status'] for row in manifest['conditions']] == ['completed', 'completed']
    assert result['conditions'] == manifest['conditions']
    assert len(result['results']) == 2
    assert len({row['case_id'] for row in manifest['conditions']}) == 2
    assert progress == sorted(progress) and progress[-1] == 100
    assert 20 in progress and 70 in progress  # 40% within each of two conditions.
    for index, (row, case, memory) in enumerate(zip(manifest['conditions'], prepared, result['results']), 1):
        subdir = directory / f'condition_{index:03d}'
        saved_input = json.loads((subdir / 'input.json').read_text())
        assert isinstance(saved_input, dict)
        assert 'optimizer' not in saved_input
        result_name = 'run/results.h5'
        metrics_name = 'run/metrics.json'
        for name, filename in (('case_file', 'case.yaml'), ('result_file', result_name), ('metrics_file', metrics_name)):
            assert not Path(row[name]).is_absolute()
            assert directory / row[name] == subdir / filename
        assert (subdir / 'case.h5').is_file()
        archived_case = load_case(directory / row['case_file'])
        assert 'optimizer' not in archived_case.config_snapshot
        native = load_result(directory / row['result_file'])
        performance = load_metrics(directory / row['metrics_file'])
        assert archived_case.case_id == native.case_id == row['case_id'] == case.case_id
        assert performance.source_result_id == native.result_id == memory[1].result_id
        assert memory[0] == row['condition_id'] and memory[2] == performance
        assert mutable_data(archived_case.config_snapshot) == mutable_data(case.config_snapshot)
        for field, values in case.design_fields.items():
            np.testing.assert_array_equal(archived_case.design_fields[field], values)
        reevaluated = postprocess.evaluate(native)
        assert reevaluated.metrics == performance.metrics
        assert performance.metrics['Q_B'].value == -110.
        assert row['qualification']['design']['eligible'] is True
        assert all(gate[1] is True for gate in row['qualification']['physical']['checks'])
        reference = baseline[index - 1]
        assert row['baseline'] == {
            'case_id': reference[1].case_id, 'result_id': reference[1].result_id,
            'metrics_id': reference[2].result_id,
            'metrics': {name: asdict(reference[2].metrics[name]) for name in ('Q_B', 'dP_A', 'dP_B')}}
        np.testing.assert_array_equal(native.fields['Ta'], memory[1].fields['Ta'])


def test_solve_exception_keeps_failed_member_and_continues(tmp_path, monkeypatch):
    conditions, calls = _conditions(), []
    baseline = _baseline(conditions)

    def solve(case, control):
        calls.append(case.case_id)
        if len(calls) == 2:
            raise RuntimeError('injected flow failure')
        return _native(case)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / 'solve-failure'
    library = tmp_path / 'test-library.dylib'
    library.write_bytes(b'non-executable test data')
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline,
        control=RunControl( native_library=str(library)), workers=1)
    assert len(calls) == 3
    assert result['status'] == 'failed' and result['objectives'] is None
    assert result['backend'] == _manifest(directory)['backend'] == 'cpp'
    rows = _manifest(directory)['conditions']
    assert [row['status'] for row in rows] == ['completed', 'failed', 'completed']
    assert 'injected flow failure' in rows[1]['reason']
    assert load_case(directory / rows[1]['case_file']).case_id == calls[1]
    assert not rows[1].get('result_file') and not rows[1].get('metrics_file')
    assert len(result['results']) == 2


@pytest.mark.parametrize('damage', ['unconverged', 'missing_Q_B', 'missing_dP_B'])
def test_unusable_condition_retains_native_metrics_and_has_no_fitness(tmp_path, monkeypatch, damage, native_control):
    conditions = _conditions(2)
    baseline = _baseline(conditions)
    calls = []

    def solve(case, control):
        calls.append(case.case_id)
        field = _native(case)
        if len(calls) != 2:
            return field
        if damage == 'unconverged':
            return replace(field, run_status={'execution': 'completed', 'converged': False})
        if damage == 'missing_dP_B':
            return replace(field, pressure_evidence={'A': field.pressure_evidence['A']})
        faces = mutable_data(field.boundary_fluxes)
        del faces['model_h']['B']
        return replace(field, boundary_fluxes=faces)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / damage
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    assert result['status'] == 'failed' and result['objectives'] is None
    rows = _manifest(directory)['conditions']
    assert [row['status'] for row in rows] == ['completed', 'failed']
    native = load_result(directory / rows[1]['result_file'])
    metrics = load_metrics(directory / rows[1]['metrics_file'])
    if damage == 'unconverged':
        assert native.run_status['converged'] is False
    else:
        name = damage.removeprefix('missing_')
        assert metrics.metrics[name].status == 'insufficient_data'
        assert metrics.metrics[name].value is None
    assert rows[1]['reason']


def test_postprocess_exception_still_archives_native_result(tmp_path, monkeypatch):
    conditions = _conditions(2)
    baseline = _baseline(conditions)
    original = postprocess.evaluate
    calls = []

    def evaluate(field):
        calls.append(field.result_id)
        if len(calls) == 1:
            raise RuntimeError('injected metric failure')
        return original(field)

    _patch_solve(monkeypatch, lambda case, control: _native(case))
    monkeypatch.setattr(postprocess, 'evaluate', evaluate)
    directory = tmp_path / 'postprocess-failure'
    library = tmp_path / 'test-library.dylib'
    library.write_bytes(b'non-executable test data')
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline,
        control=RunControl( native_library=str(library)), workers=1)
    assert result['objectives'] is None and result['status'] == 'failed'
    rows = _manifest(directory)['conditions']
    assert [row['status'] for row in rows] == ['failed', 'completed']
    assert load_result(directory / rows[0]['result_file']).result_id == calls[0]
    assert not rows[0].get('metrics_file')
    assert 'injected metric failure' in rows[0]['reason']


@pytest.mark.parametrize('damage, reason', [
    ('screening', 'requires full'),
    ('df_mode', 'D-F mode disagrees'),
    ('design_field', 'changes prepared design field L_field_m'),
    ('case_id', 'does not belong to the prepared case'),
])
def test_returned_evidence_must_match_full_prepared_case(tmp_path, monkeypatch, damage, reason, native_control):
    conditions = _conditions(1)
    baseline = _baseline(conditions)

    def solve(case, control):
        field = _native(case)
        if damage == 'case_id':
            return replace(field, case_id='another-condition-case')
        metadata = mutable_data(field.metadata)
        if damage == 'screening':
            metadata['mode'] = 'screening_3d'
        elif damage == 'df_mode':
            metadata['df_metadata']['mode'] = 'experimental'
        else:
            metadata['design_fields']['L_field_m'][0, 0, 0] += .0001
        return replace(field, metadata=metadata)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / damage
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    row = _manifest(directory)['conditions'][0]
    assert result['status'] == row['status'] == 'failed'
    assert result['objectives'] is None and result['results'] == []
    assert reason in row['reason']
    assert load_case(directory / row['case_file']).case_id == row['case_id']
    native = load_result(directory / row['result_file'])
    assert native.run_status['converged'] is True  # Convergence alone is insufficient.
    assert row['metrics_file'] is None


@pytest.mark.parametrize('damage, reason', [
    ('temperature', 'fixed input T_inA'),
    ('mass_flow', 'prescribed mass flow A differs'),
    ('environment', 'fixed input _environment'),
])
def test_same_id_baseline_requires_same_physical_inputs(tmp_path, monkeypatch, damage, reason, native_control):
    conditions = _conditions(1)
    condition_id, config, flow_a, flow_b = conditions[0]
    if damage == 'temperature':
        config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=390.))
    if damage == 'mass_flow':
        flow_a *= 1.1
    baseline = _baseline([(condition_id, config, flow_a, flow_b)])
    if damage == 'environment':
        name, field, metrics = baseline[0]
        metadata = mutable_data(field.metadata)
        metadata['parameters']['_environment']['OMP_NUM_THREADS'] = '7'
        baseline[0] = (name, replace(field, metadata=metadata), metrics)

    _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached mismatched baseline'))
    directory = tmp_path / damage
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    row = _manifest(directory)['conditions'][0]
    assert result['status'] == row['status'] == 'failed' and result['objectives'] is None
    assert row['stage'] == 'comparison' and reason in row['reason']
    assert load_case(directory / row['case_file']).case_id == row['case_id']
    assert row['result_file'] is None and row['metrics_file'] is None


@pytest.mark.parametrize('setting, value', [
    ('T_s_init_K', 335.), ('simple_velocity_relaxation', .35),
    ('model_h_max_iterations', 80), ('model_h_temperature_tol_K', 1e-5),
    ('model_h_q_relative_tol', 1e-4), ('ltne_enthalpy_outer', 80),
    ('ltne_enthalpy_nsweep', 3), ('ltne_enthalpy_omega', .4),
    ('ltne_enthalpy_tol', 1e-5), ('ltne_enthalpy_coupled_energy_tol', 1e-4),
    ('ltne_enthalpy_equation_energy_tol', 1e-4),
    ('require_enthalpy_update_on_temperature', True),
])
def test_baseline_requires_same_thermal_and_flow_controls(tmp_path, monkeypatch, setting, value, native_control):
    conditions = _conditions(1)
    name, config, flow_a, flow_b = conditions[0]
    reference = replace(config, solver=replace(config.solver, **{setting: value}))
    baseline = _baseline([(name, reference, flow_a, flow_b)])
    _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached mismatched controls'))
    directory = tmp_path / setting
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    row = _manifest(directory)['conditions'][0]
    key = 'T_s_init' if setting == 'T_s_init_K' else setting
    assert result['status'] == row['status'] == 'failed' and result['objectives'] is None
    assert row['stage'] == 'comparison' and f'solver setting {key} differs' in row['reason']
    assert load_case(directory / row['case_file']).case_id == row['case_id']
    assert row['result_file'] is None and row['metrics_file'] is None


def test_baseline_accepts_an_explicit_false_thermal_update_flag(tmp_path, monkeypatch, native_control):
    conditions = _conditions(1)
    baseline = _baseline(conditions)
    name, field, metrics = baseline[0]
    metadata = mutable_data(field.metadata)
    assert 'require_enthalpy_update_on_temperature' not in metadata['parameters']
    metadata['parameters']['require_enthalpy_update_on_temperature'] = False
    baseline[0] = name, replace(field, metadata=metadata), metrics
    _patch_solve(monkeypatch, lambda case, control: _native(case))
    result = batch.evaluate_condition_batch(conditions, output_dir=tmp_path / 'same', baseline=baseline, workers=1, control=native_control)
    assert result['status'] == 'completed' and result['objectives'] is not None


@pytest.mark.parametrize('target, source_imbalance', [
    ('baseline', False), ('candidate', False), ('candidate', True),
])
def test_energy_certificate_failure_cannot_produce_objectives(tmp_path, monkeypatch, target, source_imbalance, native_control):
    conditions = _conditions(1)
    baseline = _baseline(conditions)

    def failed_certificate(field):
        metadata = mutable_data(field.metadata)
        if source_imbalance:
            metadata['diagnostics']['Q_sB'] *= .9
        else:
            metadata['diagnostics']['eps_A_strict'] = .01
        return replace(field, metadata=metadata)

    if target == 'baseline':
        name, field, metrics = baseline[0]
        baseline[0] = (name, failed_certificate(field), metrics)
        _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached invalid baseline certificate'))
    else:
        _patch_solve(monkeypatch, lambda case, control: failed_certificate(_native(case)))
    directory = tmp_path / 'energy-failure'
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    row = _manifest(directory)['conditions'][0]
    assert result['status'] == row['status'] == 'failed' and result['objectives'] is None
    assert 'qualification failed: physical' in row['reason']
    if target == 'baseline':
        assert row['stage'] == 'comparison'
        assert row['result_file'] is None and row['metrics_file'] is None
    else:
        assert row['stage'] == 'qualification'
        assert row['qualification']['physical']['passed'] is False
        native = load_result(directory / row['result_file'])
        metrics = load_metrics(directory / row['metrics_file'])
        assert metrics.source_result_id == native.result_id
        assert all(metrics.metrics[name].status == 'available' for name in ('Q_B', 'dP_A', 'dP_B'))
        assert len(result['results']) == 1


@pytest.mark.parametrize('pre_cancelled', [False, True])
@pytest.mark.parametrize('entry', [batch.evaluate_condition_batch, batch._evaluate_condition_batch])
def test_cancellation_preserves_full_membership_and_is_reraised(tmp_path, monkeypatch, pre_cancelled, entry):
    conditions, calls = _conditions(), []
    cancelled = [pre_cancelled]

    def solve(case, control):
        calls.append(case.case_id)
        if len(calls) == 2:
            cancelled[0] = True
            control.check_cancelled()
        return _native(case)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / 'cancelled'
    library = tmp_path / 'test-library.dylib'
    library.write_bytes(b'non-executable test data')
    with pytest.raises(CancelledError):
        entry(conditions, output_dir=directory,
            control=RunControl(backend='cpp', native_library=str(library), cancel_check=lambda: cancelled[0]), workers=1)
    manifest = _manifest(directory)
    assert manifest['backend'] == 'cpp'
    assert manifest['status'] == 'cancelled' and manifest['objectives'] is None
    rows = manifest['conditions']
    assert [row['condition_id'] for row in rows] == ['low', 'mid', 'high']
    assert [row['status'] for row in rows] == (
        ['not_run']*3 if pre_cancelled else ['completed', 'cancelled', 'not_run'])
    assert len(calls) == (0 if pre_cancelled else 2)
    if not pre_cancelled:
        assert load_metrics(directory / rows[0]['metrics_file']).metrics['Q_B'].value == -100.
        assert load_case(directory / rows[1]['case_file']).case_id == calls[1]
        assert not rows[1].get('result_file') and not rows[2].get('case_file')


def test_existing_directory_is_never_overwritten(tmp_path, monkeypatch, native_control):
    directory = tmp_path / 'already-exists'
    directory.mkdir()
    sentinel = directory / 'batch.json'
    sentinel.write_text('prior batch evidence', encoding='utf-8')
    _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached existing output'))
    with pytest.raises((FileExistsError, ValueError)):
        batch.evaluate_condition_batch(_conditions(1), output_dir=directory, workers=1, control=native_control)
    assert sentinel.read_text() == 'prior batch evidence'
    assert list(directory.iterdir()) == [sentinel]


@pytest.mark.parametrize('damage', ['empty', 'duplicate', 'empty_id', 'bad_config', 'bad_tuple', 'nan_flow', 'zero_flow'])
def test_all_member_structure_is_checked_before_output_creation(tmp_path, monkeypatch, damage, native_control):
    conditions = _conditions(2)
    condition_id, config, mdot_a, mdot_b = conditions[1]
    if damage == 'empty':
        conditions = []
    elif damage == 'duplicate':
        conditions[1] = ('low', config, mdot_a, mdot_b)
    elif damage == 'empty_id':
        conditions[1] = ('', config, mdot_a, mdot_b)
    elif damage == 'bad_config':
        conditions[1] = (condition_id, asdict(config), mdot_a, mdot_b)
    elif damage == 'bad_tuple':
        conditions[1] = (condition_id, config, mdot_a)
    else:
        conditions[1] = (condition_id, config, float('nan') if damage == 'nan_flow' else 0., mdot_b)
    _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached invalid member list'))
    directory = tmp_path / 'invalid'
    with pytest.raises((ValueError, TypeError)):
        batch.evaluate_condition_batch(conditions, output_dir=directory, workers=1, control=native_control)
    assert not directory.exists()


@pytest.mark.parametrize('failure', [None, 'convergence', 'energy', 'save'])
def test_compact_batches_release_fields_before_next_solve(tmp_path, monkeypatch, failure, native_control):
    import weakref
    from sjtu_tpmshx.io import result_io

    conditions = _conditions(3)
    uniform = [(name, replace(cfg, zones=ZoneInputConfig()), a, b) for name, cfg, a, b in conditions]
    references, reads = [], []
    call_count = 0
    load, save = result_io.load_result, result_io.save_result

    def solve(case, control):
        nonlocal call_count
        assert all(ref() is None for ref in references + reads)
        call_count += 1
        field = _native(case)
        if call_count == 5 and failure == 'convergence':
            field = replace(field, run_status=dict(execution='completed', converged=False))
        elif call_count == 5 and failure == 'energy':
            field = replace(field, metadata={**field.metadata, 'diagnostics': {
                **field.metadata['diagnostics'], 'eps_A_strict': .5}})
        references.append(weakref.ref(field))
        return field

    def tracked_load(path):
        field = load(path)
        reads.append(weakref.ref(field))
        return field

    def tracked_save(field, path):
        if call_count == 5 and failure == 'save':
            raise OSError('result disk failure')
        save(field, path)

    _patch_solve(monkeypatch, solve)
    monkeypatch.setattr(result_io, 'load_result', tracked_load)
    monkeypatch.setattr(result_io, 'save_result', tracked_save)
    monkeypatch.setattr('sjtu_tpmshx.workflows.recovery.save_result', tracked_save)
    baseline = batch._evaluate_condition_batch(uniform, output_dir=tmp_path / 'baseline', workers=1, control=native_control)
    assert baseline['status'] == 'completed'
    assert all(ref() is None for ref in references)
    assert set(baseline['summaries']) == {'low', 'mid', 'high'}
    result = batch._evaluate_condition_batch(conditions, output_dir=tmp_path / 'candidate',
                                             baseline=baseline['summaries'], workers=1, control=native_control)
    assert call_count == 6
    assert all(ref() is None for ref in references + reads)
    assert result['status'] == ('completed' if failure is None else 'failed')
    assert [row['status'] for row in result['conditions']] == [
        'completed', 'completed' if failure is None else 'failed', 'completed']
    if failure is None:
        full_baseline = [(name, load(row['result_file']), row['performance'])
                         for name, row in baseline['summaries'].items()]
        full_results = [(name, load(row['result_file']), row['performance'])
                        for name, row in result['summaries'].items()]
        assert result['objectives'] == batch.aggregate_multi_condition(
            [row[0] for row in conditions], full_baseline, full_results)
    else:
        assert result['objectives'] is None


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'identity'])
def test_compact_baseline_archive_failures_cannot_produce_objectives(tmp_path, monkeypatch, damage, native_control):
    conditions = _conditions(2)
    uniform = [(name, replace(cfg, zones=ZoneInputConfig()), a, b) for name, cfg, a, b in conditions]
    _patch_solve(monkeypatch, lambda case, control: _native(case))
    baseline = batch._evaluate_condition_batch(uniform, output_dir=tmp_path / 'baseline', workers=1, control=native_control)
    path = baseline['summaries']['low']['result_file']
    if damage == 'missing':
        path.unlink()
    elif damage == 'corrupt':
        path.write_bytes(b'invalid HDF5')
    else:
        from sjtu_tpmshx.io.result_io import save_result
        save_result(replace(load_result(path), result_id='different-result'), path)
    if damage in ('missing', 'corrupt'):
        with pytest.raises(OSError):
            batch._evaluate_condition_batch(conditions, output_dir=tmp_path / 'candidate',
                baseline=baseline['summaries'], workers=1, control=native_control)
        saved = _manifest(tmp_path / 'candidate')
        assert saved['status'] == 'failed' and saved['objectives'] is None
        assert all(row['status'] == 'not_run' for row in saved['conditions'])
        assert all(row['result_file'] is None for row in saved['conditions'])
        return
    result = batch._evaluate_condition_batch(conditions, output_dir=tmp_path / 'candidate',
                                             baseline=baseline['summaries'], workers=1, control=native_control)
    assert result['status'] == 'failed' and result['objectives'] is None
    assert result['conditions'][0]['stage'] == 'comparison'
    assert result['conditions'][0]['status'] == 'failed'
    assert result['conditions'][1]['status'] == 'completed'


@pytest.mark.parametrize('target', ['baseline', 'candidate'])
def test_original_range_limit_excludes_otherwise_qualified_results(tmp_path, monkeypatch, target, native_control):
    conditions = _conditions(1)
    baseline = _baseline(conditions)
    def outside(field):
        metadata = mutable_data(field.metadata)
        metadata['applicability_evidence']['final'][0]['minimum'][0] = 89.
        return replace(field, metadata=metadata)
    if target == 'baseline':
        name, field, performance = baseline[0]
        baseline[0] = name, outside(field), performance
        _patch_solve(monkeypatch, lambda *args: pytest.fail('invalid baseline reached solve'))
    else:
        _patch_solve(monkeypatch, lambda case, control: outside(_native(case)))
    directory = tmp_path / 'ranges'
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline, workers=1, control=native_control)
    row, = result['conditions']
    assert row['status'] == result['status'] == 'failed' and result['objectives'] is None
    assert 'qualification failed: applicability' in row['reason']
    if target == 'candidate':
        native = load_result(directory / row['result_file'])
        performance = load_metrics(directory / row['metrics_file'])
        assert native.run_status['converged']
        assert performance.qualification['physical']['passed'] is True
        assert performance.qualification['metrics']['passed'] is True
        assert performance.qualification['design']['eligible'] is False


def test_nu_re_study_acceptance_keeps_strict_results_and_resumes(tmp_path, monkeypatch, native_control):
    def outside(field):
        metadata = mutable_data(field.metadata)
        metadata['applicability_evidence']['final'][0]['minimum'][0] = .001
        return replace(field, metadata=metadata)
    conditions = _conditions(1)
    _patch_solve(monkeypatch, lambda case, control: outside(_native(case)))
    rejected = batch.evaluate_condition_batch(conditions, output_dir=tmp_path/'strict',
                                             control=native_control, workers=1)
    assert rejected['status'] == 'failed'
    baseline = [(name, outside(field), postprocess.evaluate(outside(field)))
                for name, field, _ in _baseline(conditions)]
    source = tmp_path/'accepted'
    accepted = batch.evaluate_condition_batch(conditions, output_dir=source, baseline=baseline,
        control=native_control, workers=1, allow_nu_re_extrapolation=True)
    row, = accepted['conditions']
    assert accepted['status'] == row['status'] == 'completed'
    assert row['qualification']['optimization']['passed'] is False
    assert row['acceptance']['passed'] and row['acceptance']['nu_re_extrapolated']
    metrics = load_metrics(source/row['metrics_file'])
    assert metrics.qualification['design']['eligible'] is False
    _patch_solve(monkeypatch, lambda *args: pytest.fail('completed native result was recomputed'))
    resumed = batch.resume_condition_batch(source/'batch.json', output_dir=tmp_path/'resumed',
                                          control=native_control, workers=1)
    assert resumed['status'] == 'completed' and resumed['allow_nu_re_extrapolation'] is True
    assert resumed['conditions'][0]['acceptance'] == row['acceptance']
    with pytest.raises(ValueError, match='acceptance differs'):
        batch._evaluate_condition_batch(conditions, output_dir=tmp_path/'changed',
            control=native_control, workers=1, resume_from=(source, accepted))
    assert not (tmp_path/'changed').exists()
