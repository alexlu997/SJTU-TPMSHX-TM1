"""Keep saved 3D stage execution equal to the public low-level driver."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
import ctypes as ct
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_stage_3d as reference
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import _same
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.shared.domain.run_warnings import range_observations, warning_scope
from sjtu_tpmshx.shared.io.case_io import load_case, save_case
from sjtu_tpmshx.shared.io.result_io import load_result, save_result
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp import full_3d, full_3d_stage
from sjtu_tpmshx.solvers.backends.cpp.full_3d_capture import capture_result
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs


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
                if field.name != 'result_id'}
    if isinstance(value, Mapping):
        return {key: _normalized(item) for key, item in value.items()
                if key not in ('build_seconds', 'solve_seconds', 'source_result_id')}
    if isinstance(value, (list, tuple)):
        return type(value)(_normalized(item) for item in value)
    return value


def _run(case, *, stage, library=None):
    cfg, prepared = build_execution_inputs(case, copy_design=False)
    events, shown = [], []
    control = _control(events, library)
    driver = full_3d.NativeFull3DDriver(control.native_library, table_directory=control.native_table_directory)
    with warning_scope({}) as records, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        raw = driver._run_prepared(cfg, prepared, control, stage_case=case if stage else None)
    shown.extend((str(item.message), item.category.__name__) for item in caught)
    result = capture_result(case, cfg, prepared, raw, driver.abi)
    return raw, result, events, shown, range_observations(records), range_observations(records, last=True)


@pytest.mark.parametrize('layout,pair', [
    ('uniform', ('air', 'water')), ('fixed', ('water', 'air')), ('xy', ('air', 'water')),
    ('xyz', ('water', 'air')), ('grid', ('air', 'air')), ('asymmetric', ('water', 'air')),
    ('uniform', ('co2', 'water')), ('xy', ('water', 'co2')), ('xyz', ('sco2', 'air'))])
@pytest.mark.parametrize('audit', [False, True])
def test_complete_dto_saved_stage_matches_direct(layout, pair, audit, tmp_path):
    config, _ = reference._configuration(pair, layout)
    case = prepare_case(config, case_id='saved-stage-dto')
    case = replace(case, parameters=dict(case.parameters, _emit_audit=audit))
    save_case(case, tmp_path / 'case.h5')
    case = load_case(tmp_path / 'case.h5')
    expected = _run(case, stage=False)
    actual = _run(case, stage=True)
    scalars = actual[0].pop('capture_scalars')
    _same(_normalized(actual), _normalized(expected), 'complete 3D DTO, fields and events')
    assert scalars['q_net'].hex() == sum(expected[0]['solid_exchange']).hex()
    assert scalars['pressure_clip_hits'] == sum(flow['last']['pressure_clip_hits']
        for flow in expected[0]['flow'] if flow is not None)
    save_result(actual[1], tmp_path / 'result.h5')
    _same(load_result(tmp_path / 'result.h5'), actual[1], 'saved result')
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))


@pytest.mark.parametrize('change', ['conductivity32', 'length32', 'thermal32', 'drag',
                                    'missing', 'empty', 'uncaptured', 'no-finite'])
def test_saved_inputs_are_used_without_repreparation(change, monkeypatch, tmp_path):
    config, _ = reference._configuration(('air', 'water'), 'xyz')
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
    expected = _run(case, stage=False)
    from sjtu_tpmshx.preprocess import api
    def forbidden(*args, **kwargs):
        pytest.fail('saved execution must not prepare raw inputs')
    monkeypatch.setattr(api, 'prepare_case', forbidden)
    actual = _run(case, stage=True)
    actual[0].pop('capture_scalars')
    _same(_normalized(actual), _normalized(expected), change)
    before = {name: value.copy() for name, value in case.design_fields.items()}
    result = run_case(case, _control())
    for name, value in before.items():
        np.testing.assert_array_equal(case.design_fields[name], value)
        assert not case.design_fields[name].flags.writeable
    save_result(result, tmp_path / 'public-result.h5')


@pytest.mark.parametrize('missing', ['create_saved', 'restore_saved', 'advance_step', 'phase', 'snapshot',
                                     'take_result', 'release_run', 'release', 'get_capture', 'capture_version'])
def test_partial_stage_protocol_is_rejected_before_execution(missing, monkeypatch):
    config, _ = reference._configuration()
    case = prepare_case(config, case_id='partial-protocol')
    original_init = full_3d.NativeFull3DDriver.__init__
    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        library = self.library
        class Partial:
            def __getattr__(self, name):
                symbol = ('tpmshx_stage_capture_3d_abi_version' if missing == 'capture_version'
                          else 'tpmshx_stage_run_3d_' + missing + '_v1')
                if name == symbol:
                    raise AttributeError(name)
                return getattr(library, name)
        self.library = Partial()
    def forbidden(*args, **kwargs):
        pytest.fail('partial stage protocols must not execute')
    monkeypatch.setattr(full_3d.NativeFull3DDriver, '__init__', initialize)
    monkeypatch.setattr(full_3d.NativeFull3DDriver, '_run_prepared', forbidden)
    with pytest.raises(ValueError, match='incomplete saved 3D stage protocol'):
        run_case(case, _control())


@pytest.mark.parametrize('callback', ['progress', 'iteration', 'outer_iteration', 'cancel_check', 'checkpoint'])
def test_callback_baseexception_keeps_identity(callback, monkeypatch):
    config, _ = reference._configuration()
    case = prepare_case(config, case_id='callback-identity')
    sentinel = KeyboardInterrupt('3D callback sentinel')
    released = []
    original = full_3d_stage.SavedRun.close
    def close(self):
        original(self)
        released.append(not self.handle.value)
    monkeypatch.setattr(full_3d_stage.SavedRun, 'close', close)
    def fail(*args):
        raise sentinel
    kwargs = {'checkpoint': fail} if callback == 'checkpoint' else {}
    callbacks = {} if callback == 'checkpoint' else {callback: fail}
    with pytest.raises(KeyboardInterrupt) as caught:
        run_case(case, _control(**callbacks), **kwargs)
    assert caught.value is sentinel
    if callback != 'cancel_check':
        assert released and all(released)


@pytest.mark.parametrize('library_kind', ['current', 'archived', 'archived-stage'])
@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_public_resume_and_fresh_process_archive(library_kind, pair, tmp_path):
    archive = os.environ.get('TPMSHX_RETAINED_STAGE_SOLVER_LIBRARY' if library_kind == 'archived-stage'
                             else 'TPMSHX_RETAINED_SOLVER_LIBRARY')
    if library_kind != 'current' and not archive:
        pytest.skip('a retained solver is required for the archived-runtime check')
    library = Path(archive) if library_kind != 'current' else library_path()
    driver = full_3d.NativeFull3DDriver(library)
    assert full_3d_stage.has_saved_stage(driver.library) == (library_kind == 'current')
    if library_kind == 'archived-stage':
        assert hasattr(driver.library, 'tpmshx_stage_run_3d_create_saved_v1')
        assert not hasattr(driver.library, 'tpmshx_stage_run_3d_get_capture_v1')
    config, _ = reference._configuration(pair, 'xyz')
    case = prepare_case(config, case_id='relocated-saved-resume')
    save_case(case, tmp_path / 'case.h5')
    case = load_case(tmp_path / 'case.h5')
    saved, direct = {}, {}
    cfg, prepared = build_execution_inputs(case)
    driver.run_prepared(cfg, prepared, _control(library=library),
        checkpoint=lambda state: direct.setdefault(int(state['state.phase'][0]), state))
    expected = run_case(case, _control(library=library),
        checkpoint=lambda state: saved.setdefault(int(state['state.phase'][0]), state))
    assert saved.keys() == direct.keys() and {1, 2, 6, 7}.issubset(saved)
    for phase, state in saved.items():
        reference._state_equal(state, direct[phase])
        np.savez(tmp_path / f'phase-{phase}.npz', **state)
        actual = run_case(case, _control(library=library), resume_state=state)
        actual = replace(actual, metadata={key: value for key, value in actual.metadata.items() if key != 'continuation'})
        _same(_normalized(actual), _normalized(expected), f'phase {phase}')
    moved = tmp_path / 'relocated'
    moved.mkdir()
    (tmp_path / 'case.h5').rename(moved / 'case.h5')
    (tmp_path / 'phase-7.npz').rename(moved / 'state.npz')
    script = """import os,sys,numpy as np
from sjtu_tpmshx.shared.io.case_io import load_case
from sjtu_tpmshx.shared.io.result_io import save_result
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
with np.load(sys.argv[2],allow_pickle=False) as archive:
 state={key: (str(value) if value.dtype.kind=='U' else value) for key,value in archive.items()}
result=run_case(load_case(sys.argv[1]),RunControl(cpu_threads=2,native_library=sys.argv[4],
 native_table_directory=os.environ.get('TPMSHX_STAGE_TABLE_DIRECTORY')),resume_state=state)
save_result(result,sys.argv[3])
"""
    subprocess.run([sys.executable, '-c', script, str(moved / 'case.h5'), str(moved / 'state.npz'),
                    str(moved / 'result.h5'), str(library)], check=True)
    actual = load_result(moved / 'result.h5')
    actual = replace(actual, metadata={key: value for key, value in actual.metadata.items() if key != 'continuation'})
    _same(_normalized(actual), _normalized(expected), 'fresh process')
    save_result(expected, tmp_path / 'expected.h5')
    (tmp_path / 'resume-verdict.json').write_text(json.dumps(dict(phases=sorted(saved),
        state_exact=True, dto_exact=True, fresh_process=True, library=str(library), pair=pair)))


def test_capture_query_preserves_output_on_invalid_request(monkeypatch):
    config, _ = reference._configuration()
    case = prepare_case(config, case_id='capture-query-boundary')
    original, checked = full_3d_stage.copy_summary, []
    def inspect(library, result, *, emit_audit):
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
        return original(library, result, emit_audit=emit_audit)
    monkeypatch.setattr(full_3d_stage, 'copy_summary', inspect)
    run_case(case, _control())
    assert checked == [True]


@pytest.mark.parametrize('failure', ['summary', 'decode', 'warning'])
def test_capture_failure_releases_same_stage_owner(monkeypatch, failure):
    config, _ = reference._configuration(('sco2', 'air'))
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
        monkeypatch.setattr(full_3d, '_detach', fail)
    else:
        from sjtu_tpmshx.shared.models import nu_correlations
        monkeypatch.setattr(nu_correlations, 'warn_sco2_nu_evidence', fail)
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
    config, _ = reference._configuration(pair)
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
    save_case(case, tmp_path / 'case.h5')
    expected, actual = _run(case, stage=False), _run(case, stage=True)
    actual[0].pop('capture_scalars')
    _same(_normalized(actual), _normalized(expected), selection)
    save_result(actual[1], tmp_path / 'result.h5')


def test_unknown_capture_abi_is_rejected_before_execution(monkeypatch):
    config, _ = reference._configuration()
    case = prepare_case(config, case_id='unknown-capture-abi')
    original_init = full_3d.NativeFull3DDriver.__init__
    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.library.tpmshx_stage_capture_3d_abi_version = lambda: 99
    def forbidden(*args, **kwargs):
        pytest.fail('unknown capture ABIs must not execute')
    monkeypatch.setattr(full_3d.NativeFull3DDriver, '__init__', initialize)
    monkeypatch.setattr(full_3d.NativeFull3DDriver, '_run_prepared', forbidden)
    with pytest.raises(ValueError, match='unsupported saved 3D capture ABI 99'):
        run_case(case, _control())
