"""Keep saved 3D stage execution, its native records, and continuation consistent."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
import ctypes as ct
import os
import subprocess
import sys
import warnings

import numpy as np
import pytest

from tests.python.test_native_prepare_adapter import _same
from tests.python.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.data_types.portable_data import mutable_data
from sjtu_tpmshx.run_control.run_warnings import range_observations, warning_scope
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.file_io.result_io import load_result, save_result
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers import full_3d
from sjtu_tpmshx.cpp_interface import full_3d_stage
from tests.python import native_stage_support
from tests.python.test_native_run_adapter import _hdf_scalars


def _control(events=None, library=None, **kwargs):
    callbacks = {} if events is None else dict(
        progress=lambda value: events.append(('progress', value)),
        iteration=lambda value: events.append(('iteration', value)),
        outer_iteration=lambda done, total: events.append(('outer', done, total)))
    return RunControl(cpu_threads=2, native_library=str(library or library_path()),
        native_table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY'), **callbacks, **kwargs)


def _normalized(value):
    if is_dataclass(value):
        return {field.name: _normalized(getattr(value, field.name)) for field in fields(value)
                if field.name not in ('result_id', 'source_result_id')}
    if isinstance(value, Mapping):
        return {key: _normalized(item) for key, item in value.items()
                if key not in ('build_seconds', 'solve_seconds', 'source_result_id')}
    if isinstance(value, (list, tuple)):
        return type(value)(_normalized(item) for item in value)
    return value


def _run(case, *, library=None, checkpoint=None):
    """Run the saved stage and keep the raw record before capture."""
    events, shown, captured = [], [], []
    control = _control(events, library)
    with warning_scope({}) as records, warnings.catch_warnings(record=True) as caught, \
            pytest.MonkeyPatch.context() as patch:
        warnings.simplefilter('always')
        capture = full_3d.capture_result
        def keep(case, cfg, prepared, raw, abi, **options):
            captured.append(raw)
            return capture(case, cfg, prepared, raw, abi, **options)
        patch.setattr(full_3d, 'capture_result', keep)
        result = full_3d.run_case(case, control, checkpoint=checkpoint)
        raw, = captured
    shown.extend((str(item.message), item.category.__name__) for item in caught)
    return raw, result, events, shown, range_observations(records), range_observations(records, last=True)


def _widened(case):
    """Return the same saved case with every floating design and geometry array widened to float64."""
    parameters = mutable_data(case.parameters)
    geometry = parameters['thermal_geometry']
    for group in ('uniform', 'fields'):
        if geometry[group] is not None:
            geometry[group] = {name: np.asarray(value, dtype=np.float64) if isinstance(value, np.ndarray)
                               else float(value) for name, value in geometry[group].items()}
    design = {name: value.astype(np.float64) if isinstance(value, np.ndarray) and value.dtype.kind == 'f' else value
              for name, value in case.design_fields.items()}
    return replace(case, parameters=parameters, design_fields=design)


@pytest.mark.parametrize('layout,pair', [
    ('uniform', ('air', 'water')), ('fixed', ('water', 'air')), ('xy', ('air', 'water')),
    ('xyz', ('water', 'air')), ('grid', ('air', 'air')), ('asymmetric', ('water', 'air')),
    ('uniform', ('co2', 'water')), ('xy', ('water', 'co2')), ('xyz', ('sco2', 'air'))])
@pytest.mark.parametrize('audit', [False, True])
def test_complete_dto_saved_stage_records_and_saved_result(layout, pair, audit, tmp_path):
    config = native_stage_support.volume_configuration(pair, layout)
    case = prepare_case(config, case_id='saved-stage-dto')
    case = replace(case, parameters=dict(case.parameters, _emit_audit=audit))
    save_case(case, tmp_path / 'case.h5')
    case = load_case(tmp_path / 'case.h5')
    raw, result, events, *_ = _run(case)
    scalars = raw['capture_scalars']
    # The native capture summary repeats the raw solid exchange and pressure clipping records.
    assert scalars['q_net'].hex() == sum(raw['solid_exchange']).hex()
    assert scalars['pressure_clip_hits'] == sum(flow['last']['pressure_clip_hits']
        for flow in raw['flow'] if flow is not None)
    assert any(row[0] == 'outer' for row in events) and events[-1] == ('progress', 100)
    for flow in raw['flow']:
        if flow is not None:
            assert ('u' in flow) is audit and 'd_u' not in flow
    save_result(result, tmp_path / 'result.h5')
    _same(load_result(tmp_path / 'result.h5'), result, 'saved result')


@pytest.mark.parametrize('change', ['conductivity32', 'length32', 'thermal32', 'drag',
                                    'missing', 'empty', 'uncaptured', 'no-finite'])
def test_saved_inputs_are_used_without_repreparation(change, monkeypatch, tmp_path):
    config = native_stage_support.volume_configuration(('air', 'water'), 'xyz')
    case = prepare_case(config, case_id='saved-input-change')
    design, parameters, metadata = map(mutable_data, (case.design_fields, case.parameters, case.metadata))
    if change == 'conductivity32':
        design['K_ss'] = (design['K_ss'] * 1.07).astype(np.float32)
    elif change == 'length32':
        design['L_field_m'] = design['L_field_m'].astype(np.float32)
    elif change == 'thermal32':
        for key in ('A_0', 'D_h'):
            parameters['thermal_geometry']['fields'][key] = parameters['thermal_geometry']['fields'][key].astype(np.float32)
    elif change == 'drag':
        design['K_m2'][0, 0, 0] *= 1.08
        design['cF_per_m'][0, 0, 0] *= .96
    elif change == 'missing':
        del metadata['applicability_inputs']
    elif change == 'empty':
        metadata['applicability_inputs'] = []
    elif change == 'uncaptured':
        metadata['applicability_inputs'][0]['captured'] = False
    else:
        row = metadata['applicability_inputs'][0]
        row.update(minimum=None, maximum=None, low=0, high=0, nonfinite=row['size'])
    case = replace(case, design_fields=design, parameters=parameters, metadata=metadata)
    save_case(case, tmp_path / 'case.h5')
    case = load_case(tmp_path / 'case.h5')
    from sjtu_tpmshx.preprocess import api
    def forbidden(*args, **kwargs):
        pytest.fail('saved execution must not prepare raw inputs')
    before = {name: value.copy() for name, value in case.design_fields.items()}
    with monkeypatch.context() as patch:
        patch.setattr(api, 'prepare_case', forbidden)
        _, result, *_ = _run(case)
    if change.endswith('32'):
        # Narrow saved arrays reach the native run as the same values widened to float64.
        _, expected, *_ = _run(_widened(case))
        for name, value in expected.fields.items():
            if name != 'K_ss':
                np.testing.assert_array_equal(result.fields[name], value, err_msg=name)
    assert result.fields['K_ss'].dtype == case.design_fields['K_ss'].dtype
    assert np.shares_memory(result.fields['Ta'], result.fields['Ta_display'])
    for name, value in before.items():
        np.testing.assert_array_equal(case.design_fields[name], value)
        assert not case.design_fields[name].flags.writeable


def test_public_drag_capture_preserves_scalar_design_summary():
    config = native_stage_support.volume_configuration(('air', 'water'), 'xyz')
    case = prepare_case(config, case_id='scalar-drag')
    design = dict(case.design_fields)
    design['K_m2'] = np.asarray(design['K_m2'].flat[0])
    case = replace(case, design_fields=design)
    from sjtu_tpmshx.physical_models.df_surrogate.experimental_correction import cfd_metadata
    actual = run_case(case, _control()).metadata['df_metadata']
    base = cfd_metadata(design['K_m2'], design['cF_per_m'])
    assert actual['mode'] == 'cfd_smooth'
    for side in 'AB':
        assert actual[side]['base_K'] == base['base_K'] and actual[side]['base_cF'] == base['base_cF']
        assert set(actual[side]['applied_K']) == set(actual[side]['applied_cF']) == {'min', 'max'}
    assert actual['A']['base_K'] == design['K_m2'].item()


@pytest.mark.parametrize('missing', ['create_saved', 'restore_saved', 'advance_step', 'phase', 'snapshot',
                                     'take_result', 'release_run', 'release', 'get_capture', 'stage_version',
                                     'capture_version', 'run_saved'])
def test_partial_stage_protocol_is_rejected_before_execution(missing, monkeypatch):
    config = native_stage_support.volume_configuration()
    case = prepare_case(config, case_id='partial-protocol')
    open_library = full_3d_stage.open_library
    def initialize(*args, **kwargs):
        path, library, abi, table = open_library(*args, **kwargs)
        class Partial:
            def __getattr__(self, name):
                symbol = ('tpmshx_stage_run_3d_abi_version' if missing == 'stage_version' else
                          'tpmshx_stage_capture_3d_abi_version' if missing == 'capture_version' else
                          'tpmshx_run_saved_case_3d_v3' if missing == 'run_saved' else
                          'tpmshx_stage_run_3d_' + missing + ('_v3' if missing.endswith('_saved') else '_v1'))
                if name == symbol:
                    raise AttributeError(name)
                return getattr(library, name)
        return path, Partial(), abi, table
    def forbidden(*args, **kwargs):
        pytest.fail('partial stage protocols must not execute')
    monkeypatch.setattr(full_3d_stage, 'open_library', initialize)
    monkeypatch.setattr(full_3d_stage, 'run_saved', forbidden)
    with pytest.raises(ValueError, match='incomplete saved 3D stage protocol'):
        run_case(case, _control())


@pytest.mark.parametrize('callback', ['progress', 'iteration', 'outer_iteration', 'cancel_check', 'checkpoint'])
def test_callback_baseexception_keeps_identity(callback):
    config = native_stage_support.volume_configuration()
    case = prepare_case(config, case_id='callback-identity')
    sentinel = KeyboardInterrupt('3D callback sentinel')
    def fail(*args):
        raise sentinel
    kwargs = {'checkpoint': fail} if callback == 'checkpoint' else {}
    callbacks = {} if callback == 'checkpoint' else {callback: fail}
    with pytest.raises(KeyboardInterrupt) as caught:
        run_case(case, _control(**callbacks), **kwargs)
    assert caught.value is sentinel


@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_public_resume_and_fresh_process_archive(pair, tmp_path):
    library = library_path()
    config = native_stage_support.volume_configuration(pair, 'xyz')
    case = prepare_case(config, case_id='relocated-saved-resume')
    save_case(case, tmp_path / 'case.h5')
    case = load_case(tmp_path / 'case.h5')
    saved, repeated = {}, {}
    expected = run_case(case, _control(library=library),
        checkpoint=lambda state: saved.setdefault(int(state['state.phase'][0]), state))
    assert {1, 2, 6, 7}.issubset(saved)
    # A second checkpoint pass to the first boundary repeats the saved state exactly.
    class Paused(Exception):
        pass
    def pause(state):
        repeated.setdefault(int(state['state.phase'][0]), state)
        raise Paused
    with pytest.raises(Paused):
        run_case(case, _control(library=library), checkpoint=pause)
    (phase, state), = repeated.items()
    native_stage_support.volume_state_equal(state, saved[phase])
    for phase, state in saved.items():
        actual = run_case(case, _control(library=library), resume_state=state)
        actual = replace(actual, metadata={key: value for key, value in actual.metadata.items() if key != 'continuation'})
        _same(_normalized(actual), _normalized(expected), f'phase {phase}')
    moved = tmp_path / 'relocated'
    moved.mkdir()
    (tmp_path / 'case.h5').rename(moved / 'case.h5')
    np.savez(moved / 'state.npz', **saved[7])
    script = """import os,sys,numpy as np
from sjtu_tpmshx.file_io.case_io import load_case
from sjtu_tpmshx.file_io.result_io import save_result
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
with np.load(sys.argv[2],allow_pickle=False) as archive:
 state={key: (str(value) if value.dtype.kind=='U' else value) for key,value in archive.items()}
result=run_case(load_case(sys.argv[1]),RunControl(cpu_threads=2,native_library=sys.argv[4],
 native_table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY')),resume_state=state)
assert not any(name.startswith('sjtu_tpmshx.cpp_interface.solver_library.full_3d') for name in sys.modules)
save_result(result,sys.argv[3])
"""
    subprocess.run([sys.executable, '-c', script, str(moved / 'case.h5'), str(moved / 'state.npz'),
                    str(moved / 'result.h5'), str(library)], check=True)
    actual = load_result(moved / 'result.h5')
    actual = replace(actual, metadata={key: value for key, value in actual.metadata.items() if key != 'continuation'})
    _same(_normalized(actual), _normalized(expected), 'fresh process')


def test_capture_query_preserves_output_on_invalid_request(monkeypatch):
    config = native_stage_support.volume_configuration()
    case = prepare_case(config, case_id='capture-query-boundary')
    original, checked = full_3d_stage.copy_summary, []
    def inspect(library, result, *, emit_audit, copy_array):
        function = library.tpmshx_stage_run_3d_get_capture_v1
        function.argtypes = [ct.POINTER(full_3d_stage._StageResult), ct.c_uint32,
                             ct.POINTER(full_3d_stage._Summary)]
        function.restype = ct.c_int
        output = full_3d_stage._Summary(q_net=123., pressure_clip_hits=99)
        before = bytes(output)
        assert function(ct.byref(result), 2, ct.byref(output)) == 1
        assert bytes(output) == before
        assert function(None, 0, ct.byref(output)) == 1
        assert bytes(output) == before
        original_result = bytes(result)
        assert function(ct.byref(result), 0,
            ct.cast(ct.byref(result), ct.POINTER(full_3d_stage._Summary))) == 1
        assert bytes(result) == original_result
        result.abi_version = 99
        assert function(ct.byref(result), 0, ct.byref(output)) == 1
        assert bytes(output) == before
        result.abi_version = 1
        checked.append(True)
        return original(library, result, emit_audit=emit_audit, copy_array=copy_array)
    monkeypatch.setattr(full_3d_stage, 'copy_summary', inspect)
    run_case(case, _control())
    assert checked == [True]


@pytest.mark.parametrize('failure', ['summary', 'decode', 'warning'])
def test_capture_failure_releases_same_stage_owner(monkeypatch, failure):
    config = native_stage_support.volume_configuration(('sco2', 'air'))
    case = prepare_case(config, case_id='capture-failure')
    sentinel = RuntimeError('capture sentinel')
    original, released = full_3d_stage.release_result, []
    def release(library, result):
        assert result.owner
        original(library, result)
        released.append(not result.owner)
    def fail(*args, **kwargs):
        raise sentinel
    monkeypatch.setattr(full_3d_stage, 'release_result', release)
    if failure == 'summary':
        monkeypatch.setattr(full_3d_stage, 'copy_summary', fail)
    elif failure == 'decode':
        monkeypatch.setattr(full_3d_stage, '_detach', fail)
    else:
        monkeypatch.setattr(full_3d, 'replay_sco2_notices', fail)
    with pytest.raises(RuntimeError) as caught:
        run_case(case, _control())
    assert caught.value is sentinel
    assert released == [True]


@pytest.mark.parametrize('selection', ['model-controls', 'eos-controls', 'temperature', 'bootstrap',
                                       'Diamond', 'experimental-drag', 'experimental-nu', 'refined-ports',
                                       'reverse16', 'reverse32'])
def test_selected_controls_models_and_ports(selection, monkeypatch, tmp_path):
    pair = ('co2', 'air') if selection == 'eos-controls' else (
        ('sco2', 'water') if selection == 'experimental-nu' else ('air', 'water'))
    config = native_stage_support.volume_configuration(pair)
    if selection == 'Diamond':
        config.geometry.tpms = selection
    elif selection == 'experimental-drag':
        config.df_mode = 'experimental'
    elif selection == 'experimental-nu':
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='host-comparison', source='existing experimental selection', applicability='uniform geometry')
    elif selection == 'refined-ports':
        config.flags.port_wall_refine = True
        config.solver.Nx, config.solver.Ny, config.solver.Nz = 30, 30, 10
        config.bc_A.in_ctr = config.bc_A.out_ctr = .021
        config.bc_B.in_ctr = config.bc_B.out_ctr = .091
        config.bc_A.in_w = config.bc_A.out_w = .018
        config.bc_B.in_w = config.bc_B.out_w = .072
    elif selection.startswith('reverse'):
        kind = np.float16 if selection == 'reverse16' else np.float32
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = kind(7.), kind(.55)
        config.bc_A.dir, config.bc_B.dir = 1, 5
        config.bc_A.in_ctr = config.bc_A.out_ctr = .021
        config.bc_A.in_w, config.bc_A.out_w = .018, .024
        config.bc_B.in_z_ctr = config.bc_B.out_z_ctr = .021
        config.bc_B.in_z_w, config.bc_B.out_z_w = .022, .028
    case = prepare_case(config, case_id='saved-selected-controls')
    parameters = mutable_data(case.parameters)
    parameters['_emit_audit'] = True
    if selection == 'model-controls':
        parameters['prepared']['design'] = {'K_ss': 111.}
        monkeypatch.setenv('TPMSHX_PARALLEL_THRESHOLD', '1')
        parameters.update(outer_tol_K=.75, ltne_alpha_T=.65, simple_velocity_relaxation=.4,
            mom_tol=2e-4, mass_local_tol=3e-6, mass_global_tol=4e-6, T_s_init=335.,
            roughness_resolved=dict(mode='baseline', eps_m=80e-6), envelope_mode='off',
            use_adaptive_amg_tol=False, track_momentum_residual=True,
            _environment={'TPMSHX_P_IN_SHOOT': '0', 'TPMSHX_VAR_RHOCP': '1'})
    elif selection == 'eos-controls':
        parameters.update(ltne_enthalpy_nsweep=2, ltne_enthalpy_omega=.6, ltne_enthalpy_tol=2e-8,
            ltne_enthalpy_coupled_energy_tol=2e-3, ltne_enthalpy_equation_energy_tol=3e-3,
            require_enthalpy_update_on_temperature=True, _environment={'TPMSHX_SCO2_COMPRESSIBLE': '1'})
    elif selection == 'temperature':
        parameters.update(model_h_max_iterations=None, model_h_temperature_tol_K=None, model_h_q_relative_tol=None,
            variable_rho_cp=False, _environment={'TPMSHX_VAR_RHOCP': '0'})
        parameters['prepared']['ltne_max_iter'] = 9
    elif selection == 'bootstrap':
        parameters.update(use_coarse_bootstrap=True, coarse_bootstrap_max_iter=3)
    case = replace(case, parameters=parameters)
    states = []
    raw, actual, events, *_ = _run(case, checkpoint=lambda state: states or states.append(state))
    assert any(row[0] == 'outer' for row in events) and events[-1] == ('progress', 100)
    _check_resolved_controls(states[0], case, selection)
    np.testing.assert_array_equal(actual.metadata['application']['coeffs']['K_ss'], actual.fields['K_ss'])
    save_result(actual, tmp_path / 'result.h5')
    _same(_normalized(load_result(tmp_path / 'result.h5')), _hdf_scalars(_normalized(actual)), selection + ' saved result')


def _check_resolved_controls(state, case, selection):
    """Compare the native resolved run controls with the saved case selection."""
    cfg = case.parameters
    def value(key):
        return state[key][0]
    for index, side in enumerate('AB'):
        prefix = 'input.' + 'ab'[index] + '.'
        assert value(prefix + 'direction') == cfg['fluid_' + side + '_cfg']['dir']
        for key, name in (('inlet_temperature', 'T_in'), ('inlet_pressure', 'P_in'), ('inlet_velocity', 'u_')):
            assert value(prefix + key) == cfg[name + side], (side, key)
        scale = (cfg.get('df_application') or {}).get(side, {})
        assert value(prefix + 'permeability_scale') == scale.get('scale_K', 1.)
        assert value(prefix + 'forchheimer_scale') == scale.get('scale_F', 1.)
    assert value('input.topology') == ('Diamond', 'Gyroid').index(cfg['tpms_type'])
    assert value('input.geometry.reference_cell_length') == cfg['L_cell_m'] / 1e-3 * 1e-3
    assert value('control.refined_port_energy') == bool(cfg.get('port_wall_refine', False))
    if selection == 'model-controls':
        assert value('control.outer_temperature_tolerance') == .75
        assert value('control.thermal_relaxation') == .65
        assert value('control.simple.alpha_velocity') == .4
        assert value('control.simple.convergence.momentum_tolerance') == 2e-4
        assert value('control.simple.convergence.local_mass_tolerance') == 3e-6
        assert value('control.simple.convergence.global_mass_tolerance') == 4e-6
        assert value('control.initial_solid_temperature.present') == 1
        assert value('control.initial_solid_temperature.value') == 335.
        assert (value('control.roughness_mode'), value('control.roughness_height')) == (0, 80e-6)
        assert value('control.envelope_mode') == 2 and value('control.pressure_shooting') == 0
        assert value('control.simple.adaptive_pressure_tolerance') == 0 and value('control.simple.track_momentum') == 1
    elif selection == 'eos-controls':
        assert (value('control.enthalpy.sweeps'), value('control.enthalpy.omega')) == (2, .6)
        assert value('control.enthalpy.update_tolerance') == 2e-8
        assert value('control.enthalpy.coupled_energy_tolerance.value') == 2e-3
        assert value('control.enthalpy.equation_energy_tolerance.value') == 3e-3
        assert value('control.enthalpy.require_enthalpy_update_on_temperature') == 1
        assert value('control.sco2_local_pressure_a') == 1
    elif selection == 'temperature':
        assert value('control.variable_rho_cp') == 0 and value('control.thermal_iterations') == 9
    elif selection == 'bootstrap':
        assert (value('control.coarse_bootstrap'), value('control.coarse_iterations')) == (1, 3)
    elif selection == 'experimental-nu':
        nu = cfg['sco2_nu']
        assert value('input.a.sco2_nusselt_multiplier') == nu['alpha_D' if cfg['tpms_type'] == 'Diamond' else 'alpha_G']
    elif selection == 'experimental-drag':
        assert value('input.a.permeability_scale') != 1. or value('input.a.forchheimer_scale') != 1.


def test_unknown_capture_abi_is_rejected_before_execution(monkeypatch):
    config = native_stage_support.volume_configuration()
    case = prepare_case(config, case_id='unknown-capture-abi')
    open_library = full_3d_stage.open_library
    def initialize(*args, **kwargs):
        path, library, abi, table = open_library(*args, **kwargs)
        library.tpmshx_stage_capture_3d_abi_version = lambda: 99
        return path, library, abi, table
    def forbidden(*args, **kwargs):
        pytest.fail('unknown capture ABIs must not execute')
    monkeypatch.setattr(full_3d_stage, 'open_library', initialize)
    monkeypatch.setattr(full_3d_stage, 'run_saved', forbidden)
    with pytest.raises(ValueError, match='unsupported saved 3D capture ABI 99'):
        run_case(case, _control())


@pytest.mark.parametrize('dimension,layout,pair', [
    *[(2, layout, pair) for layout in (False, True) for pair in
      (('air', 'water'), ('water', 'air'), ('co2', 'water'), ('sco2', 'air'))],
    *[(3, layout, pair) for layout, pair in (
      ('uniform', ('air', 'water')), ('fixed', ('water', 'air')),
      ('xy', ('water', 'co2')), ('xyz', ('sco2', 'air')),
      ('asymmetric', ('water', 'air')), ('grid', ('air', 'air')))]])
def test_public_applicability_uses_native_selection(dimension, layout, pair, monkeypatch, tmp_path):
    from tests.python import test_native_run_adapter as two
    if dimension == 2:
        _, case = two._case(layout, pair)
    else:
        config = native_stage_support.volume_configuration(pair, layout)
        case = prepare_case(config, case_id='native-applicability')
    _compare_public_applicability(case, monkeypatch, tmp_path)


def test_spatial_sco2_notice_keeps_saved_field_precision(monkeypatch, tmp_path):
    config = native_stage_support.volume_configuration(('sco2', 'air'), 'xyz')
    case = prepare_case(config, case_id='sco2-notice-f32')
    design = dict(case.design_fields)
    for field in ('L_field_m', 't_field_m'):
        design[field] = design[field].astype(np.float32)
    _compare_public_applicability(replace(case, design_fields=design), monkeypatch, tmp_path)


def _compare_public_applicability(case, monkeypatch, tmp_path, *, control=None):
    """Check native applicability against the independent Python selection of the same run."""
    from tests.python import test_native_run_adapter as two
    from sjtu_tpmshx.cpp_interface import full_2d_stage
    from sjtu_tpmshx.postprocess.api import evaluate
    control = _control() if control is None else control
    stage = full_2d_stage if case.grid['dimension'] == 2 else full_3d
    original, kept = stage.run_case, []
    def keep(*args, **kwargs):
        kept.append(original(*args, **kwargs))
        return kept[-1]
    with monkeypatch.context() as current:
        current.setattr(stage, 'run_case', keep)
        actual = run_case(case, control)
    native, = kept
    # The independent Python selection reads the last closure ranges of the same native run.
    two._checked_applicability(native, native, case)
    assert '_native_applicability' not in actual.metadata
    assert '_last_closure_ranges' not in actual.metadata
    evidence = dict(actual.metadata['applicability_evidence'])
    evidence.pop('scope_notes')
    _same(evidence, native.metadata['_native_applicability'], 'public applicability evidence')
    report = evaluate(actual)
    assert report.source_result_id == actual.result_id
    save_result(actual, tmp_path / 'native-applicability.h5')
    loaded = load_result(tmp_path / 'native-applicability.h5')
    _same(_normalized(loaded), _hdf_scalars(_normalized(actual)), 'owned saved evidence')
    _same(_normalized(evaluate(loaded)), _hdf_scalars(_normalized(report)), 'saved public evaluation')
    return actual


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('change', ['missing', 'empty', 'uncaptured', 'no-finite', 'host-fields', 'host-notices'])
def test_public_applicability_keeps_saved_and_host_evidence(dimension, change, monkeypatch, tmp_path):
    from tests.python import test_native_run_adapter as two
    from sjtu_tpmshx.run_control.run_warnings import record_warning
    if dimension == 2:
        _, case = two._case()
    else:
        config = native_stage_support.volume_configuration(('air', 'water'), 'xyz')
        case = prepare_case(config, case_id='saved-applicability')
    metadata = mutable_data(case.metadata)
    control = _control()
    if change == 'missing':
        del metadata['applicability_inputs']
    elif change == 'empty':
        metadata['applicability_inputs'] = []
    elif change == 'uncaptured':
        metadata['applicability_inputs'][0]['captured'] = False
    elif change == 'no-finite':
        row = metadata['applicability_inputs'][0]
        row.update(minimum=None, maximum=None, low=0, high=0, nonfinite=row['size'])
    elif change == 'host-fields':
        for index, row in enumerate(metadata['applicability_inputs']):
            row.update(reason='saved reason', constraint='saved constraint', extra={'index': index})
            row['bounds'] = tuple(np.float32(value) for value in row['bounds'])
        metadata['applicability_inputs'][0]['captured'] = False
    else:
        metadata['notices'] = (*metadata['notices'], '', 'saved\0notice', 'same notice', 'same notice')
        def progress(value):
            record_warning(('nu-evidence', 'callback'), 'callback\0notice')
        control = replace(control, progress=progress)
    case = replace(case, metadata=metadata)
    result = _compare_public_applicability(case, monkeypatch, tmp_path, control=control)
    if change == 'host-notices':
        notes = result.metadata['applicability_evidence']['scope_notes']
        assert 'saved\0notice' in notes and 'callback\0notice' in notes
        assert '' in notes and notes.count('same notice') == 1


@pytest.mark.parametrize('dimension', [2, 3])
def test_applicability_transfer_error_releases_without_fallback(dimension, monkeypatch):
    from tests.python import test_native_run_adapter as two
    if dimension == 2:
        _, case = two._case()
    else:
        config = native_stage_support.volume_configuration()
        case = prepare_case(config, case_id='failed-transfer')
    sentinel = LookupError('evidence transfer failed')
    from sjtu_tpmshx.cpp_interface import full_2d_stage
    owners = []
    if dimension == 3:
        release = full_3d_stage.release_result
        def observe_release(library, result):
            owners.append(result)
            release(library, result)
        monkeypatch.setattr(full_3d_stage, 'release_result', observe_release)
    else:
        query_view = full_2d_stage.executed_view
        def observe_view(query, result):
            owners.append(result)
            return query_view(query, result)
        monkeypatch.setattr(full_2d_stage, 'executed_view', observe_view)
    def broken(pointer, saved):
        raise sentinel
    from sjtu_tpmshx.cpp_interface import _native_result_stage
    monkeypatch.setattr(_native_result_stage, 'copy_applicability', broken)
    with pytest.raises(LookupError) as caught:
        run_case(case, _control())
    assert caught.value is sentinel and len(owners) == 1
    assert not owners[0].owner
    monkeypatch.undo()
    run_case(case, _control())


@pytest.mark.parametrize('fault, message', [
    ('mask', 'openings disagree with rectangles'), ('nan_mask', 'opening mask'),
    ('permutation', 'axis permutation'),
    ('axis_length', 'solver geometry'), ('uniform', 'uniform design field'),
    ('extrusion', 'xy extrusion'), ('model', 'unknown model resource'),
    ('nu_mode', 'Nu settings'), ('incomplete_nu', 'Nu settings'),
    ('reverse_wrap', 'reverse direction'),
    ('strict_gate_and_convergence', 'must be real number, not str'),
    ('retired_energy_and_mask', 'invalid native full enthalpy defaults request'),
    ('missing_fluid_and_convergence', 'fluid_type_B'),
])
def test_saved_v2_rejects_inconsistent_inputs(fault, message):
    layout = 'xy' if fault == 'extrusion' else 'uniform'
    config = native_stage_support.volume_configuration(('air', 'water'), layout)
    case = prepare_case(config, case_id='saved-input-check')
    params = mutable_data(case.parameters)
    design = mutable_data(case.design_fields)
    side = params['prepared']['axes']['A']
    error = ValueError
    if fault == 'nan_mask':
        params['prepared']['openings']['A']['inlet'].flat[0] = np.nan
    elif fault == 'mask':
        mask = params['prepared']['openings']['A']['inlet']
        mask.flat[0] = 0.5 if mask.flat[0] != 0.5 else 0.25
    elif fault == 'permutation':
        side['solver_to_real_perm'] = [0, 0, 0]
    elif fault == 'axis_length':
        side['solver_init']['Lx'] = side['L_cross1'] = 2 * side['L_cross1']
    elif fault == 'reverse_wrap':
        side['is_reverse'] += 2**32
    elif fault == 'nu_mode':
        params['sco2_nu']['mode'] = 'typographical_error'
    elif fault == 'incomplete_nu':
        del params['sco2_nu']['source']
    elif fault == 'model':
        refs = list(case.model_refs)
        refs[0] = replace(refs[0], version='unknown')
        case = replace(case, model_refs=tuple(refs))
    elif fault == 'strict_gate_and_convergence':
        params.update(model_h_max_iterations=None, model_h_temperature_tol_K=None, model_h_q_relative_tol=None,
                      ltne_enthalpy_coupled_energy_tol='bad', convergence_mode='legacy')
        error = TypeError
    elif fault == 'retired_energy_and_mask':
        params['enthalpy_algorithm'] = 'temperature_fou'
        params['prepared']['openings']['A']['inlet'].flat[0] = -.5
    elif fault == 'missing_fluid_and_convergence':
        del params['fluid_type_B']
        params['convergence_mode'] = 'legacy'
        error = KeyError
    else:
        design['L_field_m'][0, 0, 1] *= 1.01
    with pytest.raises(error, match=message):
        run_case(replace(case, parameters=params, design_fields=design), control=_control())


def test_saved_3d_rejects_topology_without_a_nu_multiplier(monkeypatch):
    from sjtu_tpmshx.cpp_interface._native_values import TOPOLOGY_CODES
    from sjtu_tpmshx.physical_models.nu_correlations import sco2_effective_nu_config

    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    config.sco2_nu = sco2_effective_nu_config()
    case = prepare_case(config, case_id='unsupported-topology')
    params = dict(case.parameters, tpms_type='Primitive')
    shape, cell_mm, _, nu = full_3d.validate_saved_case(case)
    monkeypatch.setitem(TOPOLOGY_CODES, 'Primitive', 2)
    with pytest.raises(ValueError, match='Primitive'):
        full_3d.select_sco2_nu(params, nu)


def test_saved_opening_preserves_solver_roundoff_tolerance():
    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    case = prepare_case(config, case_id='rounded-opening')
    params = mutable_data(case.parameters)
    mask = params['prepared']['openings']['A']['inlet']
    index = mask.argmax()
    assert mask.flat[index] > 0.
    mask.flat[index] = np.nextafter(mask.flat[index], 0.)
    rounded = replace(case, parameters=params)
    states = []
    result = run_case(rounded, _control(), checkpoint=states.append)
    restored = run_case(rounded, _control(), resume_state=states[0])
    assert result.run_status['execution'] == restored.run_status['execution'] == 'completed'
    for field in result.fields:
        np.testing.assert_array_equal(restored.fields[field], result.fields[field])


def test_restore_rejects_matching_case_and_checkpoint_with_wrong_opening():
    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    case = prepare_case(config, case_id='restore-opening')
    states = []
    run_case(case, _control(), checkpoint=states.append)
    state = dict(states[0])
    params = mutable_data(case.parameters)
    opening = params['prepared']['openings']['A']['inlet']
    index = opening.argmax()
    assert opening.flat[index] == 1.
    opening.flat[index] = 0.5
    for key in ('input.a.inlet_opening', 'state.result.flow.0.inlet_opening'):
        state[key] = state[key].copy()
        state[key].flat[index] = 0.5
    with pytest.raises(ValueError, match='openings disagree with rectangles'):
        run_case(replace(case, parameters=params), _control(), resume_state=state)


def test_scalar_wall_and_stored_resolution_use_actual_grid():
    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    case = prepare_case(config, case_id='scalar-wall')
    design = dict(case.design_fields)
    design['t_field_m'] = np.asarray(design['t_field_m'].flat[0])
    params = dict(case.parameters, _input_resolution={'grid_shape': [1, 1, 1]})
    result = run_case(replace(case, design_fields=design, parameters=params), _control())
    assert tuple(result.metadata['input_resolution']['grid_shape']) == design['L_field_m'].shape


def test_unscoped_sco2_notice_emits_from_solver_host():
    config = native_stage_support.volume_configuration(('sco2', 'air'), 'xyz')
    case = prepare_case(config, case_id='unscoped-sco2-warning')
    with warnings.catch_warnings(record=True) as unscoped:
        warnings.simplefilter('always')
        direct = full_3d.run_case(case, _control())
    assert len(unscoped) == 1
    assert unscoped[0].category is UserWarning
    assert '[sCO2 Nu evidence] 3D h_v property refresh, side=A,' in str(unscoped[0].message)
    assert unscoped[0].filename.replace('\\', '/').endswith('/solvers/full_3d.py')
    with warnings.catch_warnings(record=True) as scoped:
        warnings.simplefilter('always')
        public = run_case(case, _control())
    assert scoped == []
    assert str(unscoped[0].message) in public.metadata['diagnostics']['warnings_list']
    assert str(unscoped[0].message) in public.metadata['applicability_evidence']['scope_notes']
    assert direct.fields.keys() == public.fields.keys()


def test_saved_3d_run_uses_only_solver_image(tmp_path):
    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    case = prepare_case(config, case_id='solver-image-only')
    case_path = tmp_path / 'case.h5'
    save_case(case, case_path)
    script = """import os, sys
from sjtu_tpmshx.file_io.case_io import load_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
result = run_case(
    load_case(sys.argv[1]),
    RunControl(cpu_threads=1, native_library=sys.argv[2],
               native_table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY')),
)
assert result.run_status['execution'] == 'completed'
assert result.fields['Ta'].shape == result.fields['K_ss'].shape
"""
    missing = str(tmp_path / 'unavailable-library')
    env = dict(
        os.environ,
        TPMSHX_PREPARATION_LIBRARY=missing,
        TPMSHX_RESULT_LIBRARY=missing,
        TPMSHX_GEOMETRY_LIBRARY=missing,
    )
    process = subprocess.run(
        [sys.executable, '-c', script, str(case_path), str(library_path())],
        env=env, capture_output=True, text=True, check=True,
    )
    assert process.returncode == 0


def test_detached_result_survives_release_mutation_and_second_run(monkeypatch):
    config = native_stage_support.volume_configuration(('air', 'water'), 'uniform')
    case = prepare_case(config, case_id='detached-ownership')
    reference = run_case(case, _control())
    original_release = full_3d_stage.release_result
    mutated = []

    def poison_before_release(library, result):
        assert result.owner
        for item in result.evidence.fields[:result.evidence.field_count]:
            name = item.name.decode()
            if name == 'K_ss':
                continue
            count = int(np.prod(tuple(item.value.shape[:item.value.rank])))
            if count and item.value.data:
                view = np.ctypeslib.as_array(
                    ct.cast(item.value.data, ct.POINTER(ct.c_double)), shape=(count,))
                view[:] = np.nan
                mutated.append(name)
        original_release(library, result)
        assert not result.owner

    monkeypatch.setattr(full_3d_stage, 'release_result', poison_before_release)
    first = run_case(case, _control())
    assert 'Ta' in mutated and 'P_report_A' in mutated
    assert np.shares_memory(first.fields['K_ss'], case.design_fields['K_ss'])
    assert not first.fields['K_ss'].flags.writeable
    for name, expected in reference.fields.items():
        np.testing.assert_array_equal(first.fields[name], expected, err_msg=name)
    assert first.field_metadata == reference.field_metadata

    other_params = mutable_data(case.parameters)
    other_params['T_inA'] = other_params['T_inA'] + 15.0
    second = run_case(replace(case, parameters=other_params), _control())
    assert not np.array_equal(second.fields['Ta'], first.fields['Ta'])
    for name, expected in reference.fields.items():
        np.testing.assert_array_equal(first.fields[name], expected, err_msg=name)
    assert first.field_metadata == reference.field_metadata
