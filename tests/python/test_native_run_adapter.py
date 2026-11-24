"""Keep complete saved 2D results and continuation through the native stage."""
import ctypes as ct
from collections.abc import Mapping
from dataclasses import replace
import json
from itertools import product

import numpy as np
import pytest

from tests.python.test_native_prepare_adapter import _same
from tests.python.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.data_types.portable_data import mutable_data
from sjtu_tpmshx.data_types.model_refs import freeze_value
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.file_io.result_io import load_result, save_result
from sjtu_tpmshx.cpp_interface import full_2d_stage
from tests.python import native_stage_support
from tests.python import result_stage_fixture


def _case(spatial=False, pair=('air', 'water')):
    config = (native_stage_support.continuous_plane_configuration(pair) if spatial else native_stage_support.plane_configuration(pair))
    native_stage_support.bound_plane_controls(config)
    return config, prepare_case(config, case_id='run-adapter')


def _control(events):
    return RunControl(cpu_threads=2, native_library=str(library_path()),
        progress=lambda *args: events.append(('progress', *args)),
        iteration=lambda *args: events.append(('iteration', *args)),
        outer_iteration=lambda *args: events.append(('outer', *args)),
        residual=lambda *args: events.append(('residual', *args)))


def _events_complete(events):
    """Require native outer work and the final run_case progress report."""
    assert any(row[0] == 'outer' for row in events)
    assert [row for row in events if row[0] == 'progress'][-1] == ('progress', 100)
    for side in 'AB':
        assert any(row[:2] == ('residual', side) for row in events)


def _same_resumed(resumed, complete, case):
    """Compare a resumed saved run with the complete run of the same controls."""
    assert resumed.metadata['continuation']['format'] == 'full_2d_continuation_v1'
    resumed = replace(resumed, result_id=complete.result_id, metadata={
        key: value for key, value in resumed.metadata.items() if key != 'continuation'})
    _same(resumed, complete, 'resumed result')


def _hdf_scalars(value):
    # HDF keeps NumPy array types but stores NumPy scalars as Python values.
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {key: _hdf_scalars(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_hdf_scalars(item) for item in value)
    return value


def _checked_applicability(actual, expected, case):
    from tests.python.applicability_evidence import capture_applicability
    from sjtu_tpmshx.solvers.execution_record import full_execution_record
    wanted = capture_applicability(case, expected, {})
    wanted.pop('scope_notes')
    metadata = dict(actual.metadata)
    execution = full_execution_record(case, expected)
    if 'execution_record' in metadata:
        _same(metadata.pop('execution_record'), freeze_value(execution), 'executed native record')
    _same(metadata.pop('_native_applicability'), freeze_value(wanted), 'native applicability transfer')
    return replace(actual, metadata=metadata)


def _compare(case, tmp_path, monkeypatch):
    """Run the saved stage once and check its independent records and saved readback."""
    from sjtu_tpmshx.cpp_interface import preparation_host
    events = []
    def forbidden(*args, **kwargs):
        raise AssertionError('saved stage must not prepare its inputs again')
    with monkeypatch.context() as patch:
        patch.setattr(preparation_host, 'operation', forbidden)
        result = full_2d_stage.run_case(case, _control(events))
    actual = _checked_applicability(result, result, case)
    for key in ('Ta', 'Tb', 'Ts'):
        assert np.shares_memory(actual.fields[key], actual.fields[key + '_display'])
    _events_complete(events)
    save_case(case, tmp_path / 'case.h5')
    save_result(result, tmp_path / 'stage.h5')
    stored_case = load_case(tmp_path / 'case.h5')
    _same(stored_case.grid, case.grid, 'case.grid')
    _same(stored_case.design_fields, _hdf_scalars(case.design_fields), 'case.design_fields')
    stored = load_result(tmp_path / 'stage.h5')
    save_result(stored, tmp_path / 'stage-again.h5')
    _same(load_result(tmp_path / 'stage-again.h5'), stored, 'saved stage readback')
    for name in ('fields', 'boundary_fluxes', 'pressure_evidence', 'run_status'):
        _same(_hdf_scalars(getattr(stored, name)), _hdf_scalars(getattr(result, name)), name)
    (tmp_path / 'events.json').write_text(json.dumps(events))
    (tmp_path / 'verdict.json').write_text(json.dumps(dict(native_records_checked=True, events_complete=True,
        preparation_forbidden=True, public_saved_readback=True)))
    return result


@pytest.mark.parametrize('spatial,pair', list(product((False, True), product(('air', 'water', 'sco2', 'co2'), repeat=2))))
def test_complete_saved_stage_result(spatial, pair, tmp_path, monkeypatch):
    config, case = _case(spatial, pair)
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict()))
    _compare(case, tmp_path, monkeypatch)


def test_spatial_sco2_notice_normalizes_saved_scalars_to_float64(tmp_path, monkeypatch):
    from sjtu_tpmshx.file_io.case_io import validate_case
    from sjtu_tpmshx.solvers.api import run_case

    _, case = _case(True, ('sco2', 'air'))
    parameters = dict(case.parameters)
    for name in ('L_cell_m', 't_wall_m'):
        parameters[name] = np.asarray(parameters[name], dtype=np.float16)
    case = replace(case, parameters=parameters)
    validate_case(case)
    monkeypatch.setenv('TPMSHX_RESULT_LIBRARY', str(tmp_path / 'missing-result'))
    result = run_case(case, _control([]))
    notice = next(text for text in result.metadata['applicability_evidence']['scope_notes']
                  if text.startswith('[sCO2 Nu evidence] 2D main-hv'))
    assert 'L=6.99997 mm, t=0.599861 mm' in notice
    assert notice in result.metadata['diagnostics']['warnings_list']


@pytest.mark.parametrize('change', ['thermal-fields', 'local-drag', 'static-application', 'missing-ranges', 'empty-ranges', 'uncaptured-range', 'no-finite'])
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
    elif change == 'no-finite':
        row = metadata['applicability_inputs'][0]
        row.update(minimum=None, maximum=None, low=0, high=0, nonfinite=row['size'])
    else:
        row = metadata['applicability_inputs'][0]
        row['captured'] = False
        for name in ('minimum', 'maximum', 'low', 'high', 'size', 'nonfinite'):
            row.pop(name, None)
    from sjtu_tpmshx.cpp_interface import full_2d_stage
    native_ranges, native_reports = [], []
    query_view = full_2d_stage.executed_view
    def inspect_result(query, result):
        view = ct.cast(ct.pointer(result.evidence), ct.POINTER(result_stage_fixture.Evidence)).contents
        native_reports.append(native_stage_support.evaluate_evidence(view))
        applicability = result.evidence.applicability.contents
        native_ranges.append((bool(applicability.inlet_recorded),
            [bool(applicability.inlet[i].captured) for i in range(len(metadata.get('applicability_inputs', ())))]))
        return query_view(query, result)
    monkeypatch.setattr(full_2d_stage, 'executed_view', inspect_result)
    modified = replace(case, parameters=parameters, metadata=metadata)
    actual = _compare(modified, tmp_path, monkeypatch)
    from tests.python.applicability_evidence import capture_applicability
    from sjtu_tpmshx.solvers.execution_record import full_execution_record
    public = replace(actual, metadata=dict(actual.metadata,
        execution_record=full_execution_record(modified, actual),
        applicability_evidence=capture_applicability(modified, actual, {})))
    expected_report = result_stage_fixture.python_report(public)
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
    config = (native_stage_support.continuous_plane_configuration(pair) if spatial else native_stage_support.plane_configuration(pair))
    native_stage_support.bound_plane_controls(config)
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
        events = []
        with pytest.raises(ValueError) as caught:
            full_2d_stage.run_case(case, _control(events))
        assert str(caught.value) == 'invalid native full enthalpy defaults request'
        assert events == []
        (tmp_path / 'verdict.json').write_text(json.dumps(dict(rejection=str(caught.value), events=events)))
    else:
        _compare(case, tmp_path, monkeypatch)


@pytest.mark.parametrize('spatial,pair', [(False, ('air', 'water')), (True, ('air', 'water')),
    (False, ('water', 'sco2')), (True, ('co2', 'air'))])
def test_saved_stage_states_and_resume(spatial, pair, tmp_path):
    _, case = _case(spatial, pair)
    stage_states = {}
    def collect(target, value):
        target.setdefault(int(value['state.phase'][0]), value)
    actual = full_2d_stage.run_case(case, _control([]), checkpoint=lambda value: collect(stage_states, value))
    _checked_applicability(actual, actual, case)
    assert {1, 2}.issubset(stage_states)
    runtime = replace(_control([]), cpu_threads=1)
    complete = full_2d_stage.run_case(case, runtime)
    _same(replace(complete, result_id=actual.result_id, metadata={
        key: value for key, value in complete.metadata.items() if key != 'runtime_resources'}),
        replace(actual, metadata={key: value for key, value in actual.metadata.items()
                                  if key != 'runtime_resources'}), 'checkpointed run')
    for phase, snapshot in stage_states.items():
        resumed = full_2d_stage.run_case(case, runtime, resume_state=snapshot)
        assert resumed.metadata['continuation']['saved_phase'] == phase
        _same_resumed(resumed, complete, case)
        np.savez(tmp_path / f'phase-{phase}.npz', **snapshot)
        save_result(resumed, tmp_path / f'resumed-{phase}.h5')
    if not spatial and pair == ('air', 'water'):
        saved = dict(stage_states[2])
        budget = 'state.result.outer_history.0.model_h_iterations.value.max_iterations'
        saved[budget] = np.zeros_like(saved[budget])
        with pytest.raises(RuntimeError, match='invalid native model-h iteration record'):
            full_2d_stage.run_case(case, runtime, resume_state=saved)
    (tmp_path / 'phases.json').write_text(json.dumps(sorted(stage_states)))


def test_experimental_saved_scope_is_checked_for_new_run_and_restore(tmp_path, monkeypatch):
    from sjtu_tpmshx.applications.execution.recovery import compute_run, read_run_checkpoint
    from sjtu_tpmshx.solvers.api import run_case
    from tests.python.native_preparation_abi import _configuration_fluids as _configuration

    config = _configuration('Gyroid', ('air', 'water'), mode='experimental')
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 7., .6
    config.geometry.L_dom_m, config.geometry.H_dom_m = .182, .042
    control = _control([])
    directory = tmp_path / 'experimental'
    _, original, _ = compute_run(config, directory, checkpoint_interval_s=30., control=control)
    saved, case, _ = read_run_checkpoint(directory / 'checkpoint.h5')
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', str(tmp_path / 'missing-preparation'))
    resumed = run_case(case, control, resume_state=saved.native_state)
    _same(resumed.fields, original.fields)
    assert resumed.run_status == original.run_status

    parameters = mutable_data(case.parameters)
    parameters['run_settings']['geometry']['L_dom_m'] = .180
    changed = replace(case, parameters=parameters)
    for resume_state in (None, saved.native_state):
        with pytest.raises(ValueError, match='experimental calibration side A is HX-effective'):
            run_case(changed, control, resume_state=resume_state)


@pytest.mark.parametrize('callback', ['progress', 'iteration', 'outer_iteration', 'residual'])
def test_saved_stage_callback_exception_identity(callback):
    _, case = _case()
    failure = LookupError('original callback error')
    def broken(*args):
        raise failure
    control = replace(_control([]), **{callback: broken})
    with pytest.raises(LookupError) as caught:
        full_2d_stage.run_case(case, control)
    assert caught.value is failure
    full_2d_stage.run_case(case, _control([]))


def test_saved_stage_cancellation_and_checkpoint_error():
    from sjtu_tpmshx.run_control.cancellation import CancelledError
    _, case = _case()
    cancel = []
    control = replace(_control([]), cancel_check=lambda: bool(cancel),
        outer_iteration=lambda *args: cancel.append(True))
    with pytest.raises(CancelledError):
        full_2d_stage.run_case(case, control)
    failure = RuntimeError('checkpoint storage failed')
    def broken(value):
        raise failure
    with pytest.raises(RuntimeError) as caught:
        full_2d_stage.run_case(case, _control([]), checkpoint=broken)
    assert caught.value is failure
    full_2d_stage.run_case(case, _control([]))


@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_unpacked_saved_settings_use_saved_v4(mode, monkeypatch):
    """Saved settings that the native experiment record cannot hold keep a defined route."""
    _, case = _case()
    parameters = mutable_data(case.parameters)
    settings = parameters['run_settings']
    if mode == 'experimental':
        settings['df_mode'] = mode
        geometry = settings['geometry']
        name, = (key for key in geometry if key.startswith('L_cell'))
        geometry[name] = np.float64(geometry[name])
    else:
        settings['df_mode'] = np.str_(mode)
    changed = replace(case, parameters=parameters)
    original, experiments = full_2d_stage.run_stage, []
    def observe(driver, case, cfg, prepared, control, entries, experiment, **options):
        experiments.append(bytes(experiment))
        return original(driver, case, cfg, prepared, control, entries, experiment, **options)
    monkeypatch.setattr(full_2d_stage, 'run_stage', observe)
    if mode == 'experimental':
        with pytest.raises(ValueError, match='saved experimental 2D settings lack the fields'):
            full_2d_stage.run_case(changed, _control([]))
        assert experiments == []
        return
    actual = full_2d_stage.run_case(changed, _control([]))
    # The native run reads the experiment record only for experimental D-F.
    assert experiments == [bytes(full_2d_stage._Experiment())]
    expected = full_2d_stage.run_case(case, _control([]))
    assert list(actual.fields) == list(expected.fields)
    for name, values in expected.fields.items():
        np.testing.assert_array_equal(actual.fields[name], values, err_msg=name)


@pytest.mark.parametrize('missing', ['tpmshx_stage_run_2d_abi_version', 'tpmshx_stage_run_2d_release_v1',
    'tpmshx_stage_run_2d_get_capture_v1', 'tpmshx_run_saved_case_2d_v5',
    'tpmshx_stage_run_2d_check_experiment_v4', 'tpmshx_stage_port_windows_fit_2d_v1'])
def test_incomplete_stage_protocol_is_rejected(monkeypatch, missing):
    original = full_2d_stage.StageDriver
    _, case = _case()

    class Library:
        def __init__(self, actual):
            self.actual = actual

        def __getattr__(self, name):
            if name == missing:
                raise AttributeError(name)
            return getattr(self.actual, name)

    class Driver(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.library = Library(self.library)

    monkeypatch.setattr(full_2d_stage, 'StageDriver', Driver)
    with pytest.raises(ValueError, match='incomplete saved 2D stage protocol'):
        full_2d_stage.run_case(case, _control([]))


@pytest.mark.parametrize('property_name', ['A_0', 'H_sf'])
def test_application_input_error_stays_after_native_execution(property_name):
    _, case = _case()
    parameters = mutable_data(case.parameters)
    parameters['static_properties']['A'][property_name] = -1.
    case = replace(case, parameters=parameters)
    events = []
    with pytest.raises(ValueError, match='A_0=.*, H_sf=.* must both be >= 0'):
        full_2d_stage.run_case(case, _control(events))
    # The application input check runs after the complete native execution.
    assert any(row[0] == 'outer' for row in events)


@pytest.mark.parametrize('spatial,algorithm', list(product((False, True), ('temperature_fou', 'legacy_h_fou'))))
def test_model_h_controls_keep_retired_algorithm_rejection(spatial, algorithm):
    config, _ = _case(spatial)
    config.solver.enthalpy_algorithm = algorithm
    case = prepare_case(config, case_id='model-h-rejection')
    events = []
    with pytest.raises(ValueError, match='^invalid native full enthalpy defaults request$'):
        full_2d_stage.run_case(case, _control(events))
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
    # The reference holds the same values widened to float64 before the native call.
    widened = mutable_data(case.parameters)
    geometry = widened['thermal_geometry']
    for group in ('uniform', 'fields'):
        if geometry[group] is not None:
            geometry[group] = {name: np.asarray(value, dtype=np.float64) if isinstance(value, np.ndarray)
                               else float(value) for name, value in geometry[group].items()}
    widened['L_cell_m'] = float(widened['L_cell_m'])
    reference = replace(case, parameters=widened, design_fields={
        name: value.astype(np.float64) if isinstance(value, np.ndarray) and value.dtype.kind == 'f' else value
        for name, value in case.design_fields.items()})
    snapshots = []
    class Paused(Exception):
        pass
    def pause(snapshot):
        snapshots.append(snapshot)
        raise Paused
    for saved in (reference, case):
        with pytest.raises(Paused):
            full_2d_stage.run_case(saved, _control([]), checkpoint=pause)
    native_stage_support.plane_state_equal(snapshots[1], snapshots[0])
    for key in ('input.cell_length', 'input.nu_geometry_ratio', 'input.reference_cell_length'):
        assert key in snapshots[1]
    np.savez(tmp_path / 'phase-1.npz', **snapshots[1])
    complete = _compare(case, tmp_path, monkeypatch)
    if selection == 'cell32':
        actual = full_2d_stage.run_case(case, _control([]), resume_state=snapshots[1])
        _same_resumed(actual, complete, case)
        save_result(actual, tmp_path / 'resumed-1.h5')


@pytest.mark.parametrize('fault, message', [
    ('length', 'grid does not cover'),
    ('stream', 'grid disagrees'),
    ('profile', 'out_profile_frac disagrees'),
])
def test_saved_stage_rejects_inconsistent_grid(fault, message):
    _, case = _case()
    parameters = mutable_data(case.parameters)
    if fault == 'length':
        parameters['L'] *= 1.1
    elif fault == 'stream':
        parameters['flow_inputs']['A']['dy'][0] *= 1.1
    else:
        parameters['boundary_openings']['A']['out_profile_frac'][0] += .25
    with pytest.raises(ValueError, match=message):
        full_2d_stage.run_case(replace(case, parameters=parameters), _control([]))


@pytest.mark.parametrize('fault, message', [
    ('version', 'unknown model resource'),
    ('nu', 'Nu settings and fluid A resource disagree'),
    ('fluid', 'fluid A and its model resource disagree'),
    ('topology', 'topology and Darcy-Forchheimer resource disagree'),
    ('roles', 'roles must account for every recorded resource'),
])
def test_saved_stage_checks_resource_identity(fault, message):
    _, case = _case()
    roles = dict(case.metadata['model_roles'])
    refs = list(case.model_refs)
    index = roles['darcy_forchheimer' if fault == 'topology' else 'fluid_A']
    ref = refs[index]
    params = mutable_data(ref.parameters)
    if fault == 'version':
        refs[index] = replace(ref, version='unknown')
    elif fault == 'roles':
        roles['fluid_A'] = roles['fluid_B']
    else:
        if fault == 'nu':
            params['sco2_nu']['source'] = 'different recorded source'
        elif fault == 'fluid':
            params['fluid'] = 'water'
        else:
            params['topology'] = 'Gyroid' if params['topology'] == 'Diamond' else 'Diamond'
        refs[index] = replace(ref, parameters=params)
    changed = replace(case, metadata={**case.metadata, 'model_roles': roles}, model_refs=refs)
    with pytest.raises(ValueError, match=message):
        full_2d_stage.run_case(changed, _control([]))


@pytest.mark.parametrize('fault, message', [
    ('eps_arr', 'uniform design field eps_arr'),
    ('L_field_m', 'uniform design field L_field'),
    ('K_ss_arr', 'uniform solid conductivity'),
    ('custom', 'design field custom'),
    ('K_m2', 'invalid prepared flow A K_m2'),
    ('seed_cF_per_m', 'invalid prepared flow A seed_cF_per_m'),
])
def test_saved_stage_checks_design_and_drag(fault, message):
    _, case = _case()
    fields, parameters = mutable_data(case.design_fields), mutable_data(case.parameters)
    if fault == 'custom':
        fields[fault] = np.full_like(fields['eps_arr'], np.nan)
    elif fault in fields:
        fields[fault][0, 0] *= .5
    elif fault == 'K_m2':
        parameters['flow_inputs']['A'][fault][0] = 0.
    else:
        parameters['flow_inputs']['A'][fault] = -1.
    invalid = replace(case, design_fields=fields, parameters=parameters)
    with pytest.raises(ValueError, match=message):
        full_2d_stage.run_case(invalid, _control([]))


@pytest.mark.parametrize('name, field', [('eps', 'eps_arr'), ('r_h', 'r_h_arr')])
def test_saved_uniform_checks_preserve_scalar_precision(name, field):
    _, case = _case()
    fields = mutable_data(case.design_fields)
    fields[field] = fields[field].astype(np.float32)
    scalar = np.nextafter(np.float64(fields[field][0, 0]), np.inf)
    changed = replace(case, design_fields=fields, parameters={**case.parameters, name: scalar})
    with pytest.raises(ValueError, match='uniform design field'):
        full_2d_stage.run_case(changed, _control([]))


def test_saved_grid_direction_matches_actual_solver_direction():
    _, case = _case()
    changed = replace(case, parameters={**case.parameters, 'dir_A': case.parameters['dir_A'] ^ 1})
    with pytest.raises(ValueError, match='direction disagrees with the solver direction'):
        full_2d_stage.run_case(changed, _control([]))
