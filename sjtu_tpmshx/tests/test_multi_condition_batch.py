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
    faces.update(report=report, model_h={
        'A': {'x-': np.array([-2*q]), 'x+': np.array([q])},
        'B': {'y+': np.array([-q]), 'y-': np.array([2*q])}})
    fields = {'Ta': np.full(shape, 350.), 'Tb': np.full(shape, 320.), 'Ts': np.full(shape, 335.)}
    return FieldResult(
        str(uuid4()), case.case_id, 'analytic-native-test', grid=case.grid, fields=fields,
        field_metadata={name: dict(unit='K', axes=('x', 'y', 'z'), location='cell',
                                   state='analytic main thermal state') for name in fields},
        boundary_fluxes=faces, pressure_evidence=pressure,
        run_status={'execution': 'completed', 'converged': True}, model_refs=case.model_refs,
        metadata={'dimension': 3, 'quantity_basis': 'total', 'thermal_mode': 'model_h',
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


def _patch_solve(monkeypatch, solve):
    monkeypatch.setattr(execution, 'run_case', solve)


def test_success_keeps_independent_case_native_and_metric_files(tmp_path, monkeypatch):
    conditions = _conditions(2)
    baseline = _baseline(conditions)
    prepared, progress = [], []

    def solve(case, control):
        prepared.append(case)
        for percent in (0, 40, 100):
            control.report_progress(percent)
        return _native(case, q=110., dp_a=10., dp_b=60.)

    _patch_solve(monkeypatch, solve)
    directory = tmp_path / 'success'
    result = batch.evaluate_condition_batch(conditions, output_dir=directory,
                                            baseline=baseline, control=RunControl(progress=progress.append))
    manifest = _manifest(directory)
    assert result['status'] == manifest['status'] == 'completed'
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
        assert isinstance(json.loads((subdir / 'input.json').read_text()), dict)
        for name, filename in (('case_file', 'case.yaml'), ('result_file', 'result.h5'), ('metrics_file', 'metrics.json')):
            assert not Path(row[name]).is_absolute()
            assert directory / row[name] == subdir / filename
        assert (subdir / 'case.h5').is_file()
        archived_case = load_case(directory / row['case_file'])
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
        assert row['energy_gates'] and all(isinstance(gate, list) and gate[1] is True
                                          for gate in row['energy_gates'])
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
    assert len(calls) == 3
    assert result['status'] == 'failed' and result['objectives'] is None
    rows = _manifest(directory)['conditions']
    assert [row['status'] for row in rows] == ['completed', 'failed', 'completed']
    assert 'injected flow failure' in rows[1]['reason']
    assert load_case(directory / rows[1]['case_file']).case_id == calls[1]
    assert not rows[1].get('result_file') and not rows[1].get('metrics_file')
    assert len(result['results']) == 2


@pytest.mark.parametrize('damage', ['unconverged', 'missing_Q_B', 'missing_dP_B'])
def test_unusable_condition_retains_native_metrics_and_has_no_fitness(tmp_path, monkeypatch, damage):
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
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
def test_returned_evidence_must_match_full_prepared_case(tmp_path, monkeypatch, damage, reason):
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
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
def test_same_id_baseline_requires_same_physical_inputs(tmp_path, monkeypatch, damage, reason):
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
    row = _manifest(directory)['conditions'][0]
    assert result['status'] == row['status'] == 'failed' and result['objectives'] is None
    assert row['stage'] == 'comparison' and reason in row['reason']
    assert load_case(directory / row['case_file']).case_id == row['case_id']
    assert row['result_file'] is None and row['metrics_file'] is None


@pytest.mark.parametrize('target, source_imbalance', [
    ('baseline', False), ('candidate', False), ('candidate', True),
])
def test_energy_certificate_failure_cannot_produce_objectives(tmp_path, monkeypatch, target, source_imbalance):
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
    result = batch.evaluate_condition_batch(conditions, output_dir=directory, baseline=baseline)
    row = _manifest(directory)['conditions'][0]
    assert result['status'] == row['status'] == 'failed' and result['objectives'] is None
    assert 'certificate failed:' in row['reason']
    if target == 'baseline':
        assert row['stage'] == 'comparison'
        assert row['result_file'] is None and row['metrics_file'] is None
    else:
        assert row['stage'] == 'energy' and not all(gate[1] for gate in row['energy_gates'])
        native = load_result(directory / row['result_file'])
        metrics = load_metrics(directory / row['metrics_file'])
        assert metrics.source_result_id == native.result_id
        assert all(metrics.metrics[name].status == 'available' for name in ('Q_B', 'dP_A', 'dP_B'))
        assert len(result['results']) == 1


@pytest.mark.parametrize('pre_cancelled', [False, True])
def test_cancellation_preserves_full_membership_and_is_reraised(tmp_path, monkeypatch, pre_cancelled):
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
    with pytest.raises(CancelledError):
        batch.evaluate_condition_batch(conditions, output_dir=directory,
            control=RunControl(cancel_check=lambda: cancelled[0]))
    manifest = _manifest(directory)
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


def test_existing_directory_is_never_overwritten(tmp_path, monkeypatch):
    directory = tmp_path / 'already-exists'
    directory.mkdir()
    sentinel = directory / 'batch.json'
    sentinel.write_text('prior batch evidence', encoding='utf-8')
    _patch_solve(monkeypatch, lambda *args: pytest.fail('solve reached existing output'))
    with pytest.raises((FileExistsError, ValueError)):
        batch.evaluate_condition_batch(_conditions(1), output_dir=directory)
    assert sentinel.read_text() == 'prior batch evidence'
    assert list(directory.iterdir()) == [sentinel]


@pytest.mark.parametrize('damage', ['empty', 'duplicate', 'empty_id', 'bad_config', 'bad_tuple', 'nan_flow', 'zero_flow'])
def test_all_member_structure_is_checked_before_output_creation(tmp_path, monkeypatch, damage):
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
        batch.evaluate_condition_batch(conditions, output_dir=directory)
    assert not directory.exists()
