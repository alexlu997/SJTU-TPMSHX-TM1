"""Keep complete saved 2D results and continuation through the native stage."""
import ctypes as ct
from collections.abc import Mapping
from dataclasses import replace
import json
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_stage_state as state
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import _same
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.shared.io.case_io import load_case, save_case
from sjtu_tpmshx.shared.io.result_io import load_result, save_result
from sjtu_tpmshx.solvers.backends.cpp import full_2d
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import capture_result
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs


def _case(spatial=False, pair=('air', 'water')):
    config = (state.continuous._configuration(pair) if spatial else state.uniform._configuration(pair))
    state._request(config)
    return config, prepare_case(config, case_id='run-adapter')


def _control(events):
    return RunControl(cpu_threads=2, native_library=str(library_path()),
        progress=lambda *args: events.append(('progress', *args)),
        iteration=lambda *args: events.append(('iteration', *args)),
        outer_iteration=lambda *args: events.append(('outer', *args)),
        residual=lambda *args: events.append(('residual', *args)))


def _old(case, control, **options):
    cfg, prepared = build_execution_inputs(case, copy_design=False)
    driver = full_2d.NativeFull2DDriver(control.native_library)
    native = driver.run_prepared(cfg, prepared, control, **options)
    control.check_cancelled()
    result = capture_result(case, cfg, prepared, native)
    control.report_progress(100)
    return result


def _events_equal(actual, expected):
    for kind in ('progress', 'iteration', 'outer'):
        assert [row for row in actual if row[0] == kind] == [row for row in expected if row[0] == kind]
    for side in 'AB':
        assert [row for row in actual if row[:2] == ('residual', side)] == [
            row for row in expected if row[:2] == ('residual', side)]


def _hdf_scalars(value):
    # HDF keeps NumPy array types but stores NumPy scalars as Python values.
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {key: _hdf_scalars(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_hdf_scalars(item) for item in value)
    return value


def _compare(case, tmp_path, monkeypatch):
    from sjtu_tpmshx.shared.models import _native_preparation_case
    expected_events, actual_events = [], []
    expected = _old(case, _control(expected_events))
    def forbidden(*args, **kwargs):
        raise AssertionError('saved stage must not prepare or use the old numerical packer')
    with monkeypatch.context() as patch:
        patch.setattr(full_2d, '_pack', forbidden)
        patch.setattr(_native_preparation_case, 'operation', forbidden)
        actual = full_2d.run_case(case, _control(actual_events))
    _same(replace(actual, result_id=expected.result_id), expected, 'result')
    _events_equal(actual_events, expected_events)
    save_case(case, tmp_path / 'case.h5')
    save_result(expected, tmp_path / 'reference.h5')
    save_result(actual, tmp_path / 'stage.h5')
    stored_case = load_case(tmp_path / 'case.h5')
    _same(stored_case.grid, case.grid, 'case.grid')
    _same(stored_case.design_fields, _hdf_scalars(case.design_fields), 'case.design_fields')
    _same(replace(load_result(tmp_path / 'stage.h5'), result_id=expected.result_id), load_result(tmp_path / 'reference.h5'))
    (tmp_path / 'events.json').write_text(json.dumps(dict(actual=actual_events, expected=expected_events)))
    (tmp_path / 'verdict.json').write_text(json.dumps(dict(complete_result_exact=True, events_exact=True,
        old_packer_forbidden=True, preparation_forbidden=True, public_saved_readback=True)))
    return actual


@pytest.mark.parametrize('spatial,pair', list(product((False, True), product(('air', 'water', 'sco2', 'co2'), repeat=2))))
def test_complete_saved_stage_result(spatial, pair, tmp_path, monkeypatch):
    config, case = _case(spatial, pair)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict()))
    _compare(case, tmp_path, monkeypatch)


@pytest.mark.parametrize('change', ['thermal-fields', 'local-drag', 'static-application', 'missing-ranges', 'empty-ranges', 'uncaptured-range'])
def test_modified_saved_inputs(change, tmp_path, monkeypatch):
    _, case = _case()
    parameters, metadata = mutable_data(case.parameters), mutable_data(case.metadata)
    shape = (len(case.grid['dx']), len(case.grid['dy']))
    if change == 'thermal-fields':
        uniform = parameters['thermal_geometry']['uniform']
        parameters['thermal_geometry']['fields'] = {key: np.full(shape, value) for key, value in uniform.items()}
        parameters['thermal_geometry']['fields']['A_0'][0, 0] *= 1.2
        parameters['thermal_geometry']['fields']['D_h'][0, 0] *= .95
    elif change == 'local-drag':
        for flow in parameters['flow_inputs'].values():
            flow['K_field_m2'] = np.tile(flow['K_m2'], (len(flow['dx']), 1))
            flow['cF_field_per_m'] = np.tile(flow['cF_per_m'], (len(flow['dx']), 1))
            flow['K_field_m2'][0, 0] *= 1.1
    elif change == 'static-application':
        parameters['static_properties']['A']['A_0'] *= 1.3
    elif change == 'missing-ranges':
        del metadata['applicability_inputs']
    elif change == 'empty-ranges':
        metadata['applicability_inputs'] = []
    else:
        row = metadata['applicability_inputs'][0]
        row['captured'] = False
        for name in ('minimum', 'maximum', 'low', 'high', 'size', 'nonfinite'):
            row.pop(name, None)
    from sjtu_tpmshx.solvers.backends.cpp import full_2d_stage
    native_ranges, native_reports = [], []
    take_result = full_2d_stage._Run.take_result
    def inspect_result(run):
        result = take_result(run)
        view = ct.cast(ct.pointer(result.evidence), ct.POINTER(state.uniform.report.Evidence)).contents
        native_reports.append(state.uniform._evaluate(view))
        applicability = result.evidence.applicability.contents
        native_ranges.append((bool(applicability.inlet_recorded),
            [bool(applicability.inlet[i].captured) for i in range(len(metadata.get('applicability_inputs', ())))]))
        return result
    monkeypatch.setattr(full_2d_stage._Run, 'take_result', inspect_result)
    modified = replace(case, parameters=parameters, metadata=metadata)
    actual = _compare(modified, tmp_path, monkeypatch)
    from sjtu_tpmshx.solvers.applicability_evidence import capture_applicability
    from sjtu_tpmshx.solvers.execution_record import full_execution_record
    public = replace(actual, metadata=dict(actual.metadata,
        execution_record=full_execution_record(modified, actual),
        applicability_evidence=capture_applicability(modified, actual, {})))
    expected_report = state.uniform.report.python_report(public)
    expected_report['source_result_id'] = case.case_id
    expected_report['qualification']['source_result_id'] = case.case_id
    (tmp_path / 'native-report.json').write_text(json.dumps(native_reports[0]))
    (tmp_path / 'reference-report.json').write_text(json.dumps(expected_report))
    _same(native_reports[0], expected_report, 'native evaluation')
    assert native_ranges == [('applicability_inputs' in metadata,
        [row['captured'] for row in metadata.get('applicability_inputs', ())])]


@pytest.mark.parametrize('selection', ['uniform-partial', 'continuous-partial', 'experimental',
    'temperature_fou', 'legacy_h_fou'])
def test_saved_stage_selected_controls(selection, tmp_path, monkeypatch):
    spatial = selection == 'continuous-partial'
    pair = ('air', 'water') if selection.endswith('partial') else ('sco2', 'water')
    config = (state.continuous._configuration(pair) if spatial else state.uniform._configuration(pair))
    state._request(config)
    if selection.endswith('partial'):
        config.solver.Nx = config.solver.Ny = 20
        config.flags.port_wall_refine = False
        config.bc_A.dir, config.bc_B.dir = 1, 2
        config.bc_A.in_ctr, config.bc_A.in_w = .012, .012
        config.bc_A.out_ctr, config.bc_A.out_w = .028, .016
        config.bc_B.in_ctr, config.bc_B.in_w = .08, .09
        config.bc_B.out_ctr, config.bc_B.out_w = .10, .07
    elif selection == 'experimental':
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='stage-comparison', source='existing experimental selection',
            applicability='uniform geometry')
    else:
        config.solver.enthalpy_algorithm = selection
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict()))
    case = prepare_case(config, case_id='run-adapter-controls')
    if selection in ('temperature_fou', 'legacy_h_fou'):
        errors, events = [], []
        for run in (_old, full_2d.run_case):
            observed = []
            with pytest.raises(ValueError) as caught:
                run(case, _control(observed))
            errors.append(str(caught.value))
            events.append(observed)
        assert errors == ['invalid native full enthalpy defaults request'] * 2
        _events_equal(*events)
        (tmp_path / 'verdict.json').write_text(json.dumps(dict(rejection=errors[0], events_exact=True)))
    else:
        _compare(case, tmp_path, monkeypatch)


@pytest.mark.parametrize('spatial,pair', [(False, ('air', 'water')), (True, ('air', 'water')),
    (False, ('water', 'sco2')), (True, ('co2', 'air'))])
def test_saved_stage_states_and_resume(spatial, pair, tmp_path):
    _, case = _case(spatial, pair)
    old_states, stage_states = {}, {}
    def collect(target, value):
        target.setdefault(int(value['state.phase'][0]), value)
    reference = _old(case, _control([]), checkpoint=lambda value: collect(old_states, value))
    actual = full_2d.run_case(case, _control([]), checkpoint=lambda value: collect(stage_states, value))
    _same(replace(actual, result_id=reference.result_id), reference)
    assert set(stage_states) == set(old_states)
    assert {1, 2}.issubset(stage_states)
    for phase, snapshot in stage_states.items():
        assert snapshot.keys() == old_states[phase].keys()
        for key, value in snapshot.items():
            if key.endswith(('.linear.build_seconds', '.linear.solve_seconds')):
                assert value.dtype == old_states[phase][key].dtype
                assert value.shape == old_states[phase][key].shape
                assert np.all(value >= 0) and np.all(old_states[phase][key] >= 0)
            else:
                _same(value, old_states[phase][key], f'state[{phase}].{key}')
        runtime = replace(_control([]), cpu_threads=1)
        expected = _old(case, runtime, resume_state=snapshot)
        resumed = full_2d.run_case(case, runtime, resume_state=snapshot)
        _same(replace(resumed, result_id=expected.result_id), expected)
        np.savez(tmp_path / f'phase-{phase}.npz', **snapshot)
        save_result(resumed, tmp_path / f'resumed-{phase}.h5')
    (tmp_path / 'phases.json').write_text(json.dumps(sorted(stage_states)))


@pytest.mark.parametrize('callback', ['progress', 'iteration', 'outer_iteration', 'residual'])
def test_saved_stage_callback_exception_identity(callback):
    _, case = _case()
    failure = LookupError('original callback error')
    def broken(*args):
        raise failure
    control = replace(_control([]), **{callback: broken})
    for run in (_old, full_2d.run_case):
        with pytest.raises(LookupError) as caught:
            run(case, control)
        assert caught.value is failure
    full_2d.run_case(case, _control([]))


def test_saved_stage_cancellation_and_checkpoint_error():
    from sjtu_tpmshx.shared.domain.cancellation import CancelledError
    _, case = _case()
    for run in (_old, full_2d.run_case):
        cancel = []
        control = replace(_control([]), cancel_check=lambda: bool(cancel),
            outer_iteration=lambda *args: cancel.append(True))
        with pytest.raises(CancelledError):
            run(case, control)
        failure = RuntimeError('checkpoint storage failed')
        def broken(value):
            raise failure
        with pytest.raises(RuntimeError) as caught:
            run(case, _control([]), checkpoint=broken)
        assert caught.value is failure
    full_2d.run_case(case, _control([]))


def test_selected_retained_runtime_has_no_new_stage_dependency(monkeypatch):
    import os
    retained = os.environ.get('TPMSHX_RETAINED_STAGE_LIBRARY')
    if not retained:
        pytest.skip('a retained stage runtime is checked by the external recovery acceptance')
    from sjtu_tpmshx.solvers.backends.cpp import full_2d_stage
    _, case = _case()
    control = replace(_control([]), native_library=retained)
    def forbidden(*args, **kwargs):
        raise AssertionError('retained runtime must not enter the new saved stage')
    monkeypatch.setattr(full_2d_stage, 'run_stage', forbidden)
    states = []
    expected = _old(case, control)
    actual = full_2d.run_case(case, control, checkpoint=states.append)
    _same(replace(actual, result_id=expected.result_id), expected)
    assert states
    resumed = full_2d.run_case(case, control, resume_state=states[0])
    wanted = _old(case, control, resume_state=states[0])
    _same(replace(resumed, result_id=wanted.result_id), wanted)


@pytest.mark.parametrize('missing', ['create', 'restore'])
@pytest.mark.parametrize('version', [1, 2])
def test_incomplete_stage_protocol_is_not_retried(monkeypatch, missing, version):
    original = full_2d.NativeFull2DDriver
    _, case = _case()
    class Library:
        def __init__(self, actual):
            self.actual = actual
        def __getattr__(self, name):
            if (name == f'tpmshx_stage_run_2d_{missing}_saved_v{version}'
                    or version == 1 and name.endswith('_saved_v2')):
                raise AttributeError(name)
            return getattr(self.actual, name)
    class Driver(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.library = Library(self.library)
        def run_prepared(self, *args, **kwargs):
            raise AssertionError('incomplete native protocol must not select the old driver')
    monkeypatch.setattr(full_2d, 'NativeFull2DDriver', Driver)
    with pytest.raises(ValueError, match='incomplete saved 2D stage protocol'):
        full_2d.run_case(case, _control([]))


@pytest.mark.parametrize('property_name', ['A_0', 'H_sf'])
def test_application_input_error_stays_after_native_execution(property_name):
    _, case = _case()
    parameters = mutable_data(case.parameters)
    parameters['static_properties']['A'][property_name] = -1.
    case = replace(case, parameters=parameters)
    messages, records = [], []
    for run in (_old, full_2d.run_case):
        events = []
        with pytest.raises(ValueError) as caught:
            run(case, _control(events))
        messages.append(str(caught.value))
        records.append(events)
    assert messages[0] == messages[1]
    assert any(row[0] == 'outer' for row in records[0])
    _events_equal(*records)


@pytest.mark.parametrize('spatial,algorithm', list(product((False, True), ('temperature_fou', 'legacy_h_fou'))))
def test_model_h_controls_keep_retired_algorithm_rejection(spatial, algorithm):
    config, _ = _case(spatial)
    config.solver.enthalpy_algorithm = algorithm
    case = prepare_case(config, case_id='model-h-rejection')
    for run in (_old, full_2d.run_case):
        events = []
        with pytest.raises(ValueError, match='^invalid native full enthalpy defaults request$'):
            run(case, _control(events))
        assert events == []


@pytest.mark.parametrize('selection', ['cell32', 'cell16', 'diameter32', 'both32', 'both16',
    'uniform-cell32', 'uniform-diameter32', 'uniform-fields32'])
def test_saved_geometry_precision_and_resume(selection, tmp_path, monkeypatch):
    spatial = not selection.startswith('uniform')
    _, case = _case(spatial)
    parameters, design = mutable_data(case.parameters), mutable_data(case.design_fields)
    dtype = np.float16 if selection.endswith('16') else np.float32
    if selection.startswith(('cell', 'both')) or selection == 'uniform-cell32':
        design['L_field_m'] = design['L_field_m'].astype(dtype)
    if selection == 'uniform-cell32':
        parameters['L_cell_m'] = dtype(parameters['L_cell_m'])
    geometry = parameters['thermal_geometry']
    if selection.startswith(('diameter', 'both')):
        geometry['fields']['D_h'] = geometry['fields']['D_h'].astype(dtype)
    elif selection == 'uniform-diameter32':
        geometry['uniform']['D_h'] = dtype(geometry['uniform']['D_h'])
    elif selection == 'uniform-fields32':
        shape = design['L_field_m'].shape
        geometry['fields'] = {name: np.full(shape, value, dtype=dtype)
                              for name, value in geometry['uniform'].items()}
    case = replace(case, parameters=parameters, design_fields=design)
    if spatial:
        save_case(case, tmp_path / 'typed-case.h5')
        case = load_case(tmp_path / 'typed-case.h5')
    snapshots = []
    class Paused(Exception):
        pass
    def pause(snapshot):
        snapshots.append(snapshot)
        raise Paused
    for run in (_old, full_2d.run_case):
        with pytest.raises(Paused):
            run(case, _control([]), checkpoint=pause)
    state._state_equal(snapshots[1], snapshots[0])
    for key in ('input.cell_length', 'input.nu_geometry_ratio', 'input.reference_cell_length'):
        assert key in snapshots[1]
    np.savez(tmp_path / 'phase-1.npz', **snapshots[1])
    _compare(case, tmp_path, monkeypatch)
    if selection == 'cell32':
        expected = _old(case, _control([]), resume_state=snapshots[0])
        actual = full_2d.run_case(case, _control([]), resume_state=snapshots[1])
        _same(replace(actual, result_id=expected.result_id), expected)
        save_result(actual, tmp_path / 'resumed-1.h5')
