"""Public prepared-case handoff to the independent full native 3D driver."""
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.run_warnings import RangeRecord, warning_scope
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.solvers.backends.python.three_d.execution import run_case as python_run
from sjtu_tpmshx.solvers.api import run_case as cpp_run
from sjtu_tpmshx.tests.native.test_native_execution import _config
from sjtu_tpmshx.tests.native.test_full_3d import ROOT


@pytest.fixture(scope='module')
def native_path():
    host='windows-x64' if os.name=='nt' else 'macos-arm64'
    name='tpmshx_solver_shared.dll' if os.name=='nt' else 'libtpmshx_solver_shared.dylib'
    path=Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY',ROOT/'.cache/native-deps/build'/('pilot-'+host)/name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS')=='1':
            pytest.fail(f'native full library unavailable: {path}')
        pytest.skip(f'native full library unavailable: {path}')
    return path


def case(pair='air-air', cap=30):
    cfg=_config(3,True)
    def fluid(name,side):
        return FluidConfig(type=name,u_mps=3. if name=='air' else .2,
            T_in_K=(350. if name=='water' else 500.) if side==0 else 300.,
            P_in_Pa=12e6 if name=='sco2' else (2e6 if name=='water' else 2e5))
    cfg=replace(cfg,fluid_A=fluid(pair.split('-')[0],0),fluid_B=fluid(pair.split('-')[1],1),
                solver=replace(cfg.solver,max_outer_ltne=cap))
    return prepare_case(cfg,case_id='full-native-'+pair)


def control(path,**kwargs):
    # Match full 2D fixtures: this loaded library owns one EOS directory.
    return RunControl(backend='cpp',native_library=str(path),native_table_directory=str(ROOT/'.cache/native-deps/tables'),**kwargs)


def compare(actual,expected,path='', *, engineering=False):
    if isinstance(expected,Mapping):
        assert actual.keys()==expected.keys(),path
        for key,value in expected.items():compare(actual[key],value,path+'/'+str(key),engineering=engineering)
    elif isinstance(expected,(tuple,list)):
        assert len(actual)==len(expected),path
        for i,value in enumerate(expected):compare(actual[i],value,path+'/'+str(i),engineering=engineering)
    elif isinstance(expected,(np.ndarray,float,np.floating)):
        if isinstance(expected,np.ndarray):
            assert np.shape(actual)==expected.shape,path
            if expected.dtype.kind in 'biu':
                np.testing.assert_array_equal(actual,expected,err_msg=path)
                return
        rtol,atol=2e-7,1e-6
        if engineering:
            rtol=1e-4  # Intermediate fields: 0.01%, independently of physical gates.
            key=path.rsplit('/',1)[-1]
            if key.startswith(('Ta','Tb','Ts','T_out')) or 'temperature' in path:
                rtol,atol=0.,.01
            elif key in ('Q','Q_A','Q_B','dP_A','dP_B','mass_flow_A','mass_flow_B'):
                rtol,atol=.001,0.
            elif key=='energy_imbalance_rel':
                rtol,atol=0.,1e-5  # Compare near-zero ratios in absolute units.
        np.testing.assert_allclose(actual,expected,rtol=rtol,atol=atol,equal_nan=True,err_msg=path)
    else:
        assert actual==expected,path


def test_bootstrap_trace_records_recursive_caps_without_changing_legacy_summary(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    cfg, p = prepared('air-air', counts=(26, 26, 26), use_coarse_bootstrap=True,
                      coarse_bootstrap_max_iter=3, max_iter_simple=1)
    p['max_outer'] = p['ltne_max_iter'] = 1
    expected = runtime.build_problem(cfg, p)
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    actual = driver.run_prepared(cfg, p)
    for side, solver, flow in zip('AB', (expected.sA, expected.sB), actual['flow']):
        trace = actual['bootstrap_trace'][side]
        compare(trace, solver._coarse_bootstrap_trace, side)
        assert [row['depth'] for row in trace['levels']] == [1, 2]
        assert [row['coarse_shape'] for row in trace['levels']] == [(13, 13, 13), (6, 6, 6)]
        assert [row['iteration_cap'] for row in trace['levels']] == [3, 200]
        assert trace['actual_levels'] == 2 and trace['started_cap_sum'] == 203
        assert trace['total_charged_iterations'] == sum(row['charged_iterations'] for row in trace['levels']) > 3
        assert flow['bootstrap']['coarse_iters'] == trace['levels'][0]['charged_iterations'] == 3


def test_native_deep_bootstrap_cancel_keeps_partial_trace_without_field_result(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    cfg, p = prepared('air-air', counts=(26, 26, 26), use_coarse_bootstrap=True,
                      coarse_bootstrap_max_iter=7, max_iter_simple=1)
    checkpoints = []

    def cancel():
        checkpoints.append(True)
        # Host entry, native entry, deepest SIMPLE entry, first sweep,
        # then cancel before its second sweep. No extra checkpoint is added.
        return len(checkpoints) == 5

    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    with pytest.raises(CancelledError) as caught:
        driver.run_prepared(cfg, p, control(native_path, cancel_check=cancel))
    trace = caught.value.coarse_bootstrap_trace['A']
    assert len(checkpoints) == 5
    assert trace['decision'] == 'cancelled'
    assert [row['solve_started'] for row in trace['levels']] == [False, True]
    assert [row['charged_iterations'] for row in trace['levels']] == [0, 1]
    assert [row['stop'] for row in trace['levels']] == ['cancelled', 'cancelled']
    assert trace['actual_levels'] == 1 and trace['started_cap_sum'] == 200
    assert trace['total_charged_iterations'] == 1
    assert caught.value.coarse_bootstrap_trace['B']['actual_levels'] == 0


@pytest.mark.parametrize('enabled', [False, True])
def test_public_bootstrap_trace_roundtrip_and_old_diagnostics_remain_readable(native_path, tmp_path, enabled):
    from sjtu_tpmshx.io.result_io import load_result, save_result
    prepared = case('air-air', 2)
    prepared = replace(prepared, parameters=dict(prepared.parameters, use_coarse_bootstrap=enabled,
                                                 coarse_bootstrap_max_iter=7))
    expected = python_run(prepared)
    actual = cpp_run(prepared, control(native_path))
    trace = actual.metadata['diagnostics']['coarse_bootstrap_trace']
    compare(trace, expected.metadata['diagnostics']['coarse_bootstrap_trace'])
    for value in trace.values():
        assert value['decision'] == ('coarse-too-small' if enabled else 'disabled')
        assert value['actual_levels'] == value['started_cap_sum'] == value['total_charged_iterations'] == 0
    path = tmp_path / 'result.h5'
    save_result(actual, path)
    compare(load_result(path).metadata['diagnostics']['coarse_bootstrap_trace'], trace)
    # Old saved diagnostics have no new key and remain readable unchanged.
    diagnostics = dict(actual.metadata['diagnostics'])
    del diagnostics['coarse_bootstrap_trace']
    old = replace(actual, metadata=dict(actual.metadata, diagnostics=diagnostics))
    old_path = tmp_path / 'old-result.h5'
    save_result(old, old_path)
    restored = load_result(old_path)
    assert 'coarse_bootstrap_trace' not in restored.metadata['diagnostics']
    compare(restored.fields, old.fields)
    compare(restored.run_status, old.run_status)


def test_old_full3d_library_missing_trace_has_explicit_capability_error(native_path, monkeypatch):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d
    library = full_3d.ct.CDLL(str(native_path))

    class OldAPI:
        def __getattr__(self, name):
            if name == 'tpmshx_full_3d_get_bootstrap_trace_v1':
                raise AttributeError(name)
            return getattr(library, name)

    monkeypatch.setattr(full_3d.ct, 'CDLL', lambda path: OldAPI())
    with pytest.raises(ValueError, match='lacks bootstrap trace v1; rebuild'):
        full_3d.NativeFull3DDriver(native_path)


@pytest.mark.parametrize('pair',['air-air','air-water','water-air','air-sco2','sco2-water'])
def test_public_case_fields_native_ledgers_and_postprocess(native_path,pair):
    from sjtu_tpmshx.tests.native.test_backend_engineering_parity import _physical_gates
    prepared=case(pair);expected=python_run(prepared)
    # A Python numerical entry cannot supply any part of the native answer.
    with patch('sjtu_tpmshx.solvers.backends.python.three_d.runtime.build_problem',side_effect=AssertionError('Python numerical driver called')):
        actual=cpp_run(prepared,control(native_path))
    assert actual.backend_id=='cpp'
    for result in (actual,expected):
        _physical_gates(result)
    for key in ('fields','field_metadata','boundary_fluxes','pressure_evidence','run_status'):
        compare(getattr(actual,key),getattr(expected,key),key,engineering=True)
    for key in ('model_metadata','application','reporting_reference','df_metadata'):
        compare(actual.metadata[key],expected.metadata[key],key,engineering=key in ('application','reporting_reference'))
    for key in ('Q','Q_A','Q_B','dP_A','dP_B','T_out_A','T_out_B','mass_flow_A','mass_flow_B','energy_imbalance_rel'):
        a,e=evaluate(actual).metrics[key],evaluate(expected).metrics[key]
        assert a.status==e.status
        compare(a.value,e.value,key,engineering=True)
    for key in ('simple_ok','ltne_ok','outer_converged','fields_finite','envelope_ok','simple_exit_A','simple_exit_B'):
        compare(actual.metadata['diagnostics']['convergence_detail'][key],expected.metadata['diagnostics']['convergence_detail'][key],key)


def test_public_legacy_strict_v3_reports_executed_final_and_outer_settings(native_path):
    cfg = _config(3, True)
    cfg = replace(cfg, solver=replace(cfg.solver, max_outer_ltne=2,
        enthalpy_algorithm='legacy_h_fou', ltne_enthalpy_outer=1000,
        ltne_enthalpy_nsweep=25, ltne_enthalpy_omega=.6, ltne_enthalpy_tol=1e-6,
        ltne_enthalpy_coupled_energy_tol=1e-5, ltne_enthalpy_equation_energy_tol=1e-5))
    prepared = prepare_case(cfg, case_id='legacy-strict-full3d')
    # Reuse the module's explicit absolute table path; no C-smoke fallback,
    # new directory policy, or silent skip substitutes for legacy execution.
    actual = cpp_run(prepared, control(native_path))
    diagnostics = actual.metadata['diagnostics']
    assert actual.backend_id == 'cpp' and actual.backend_version == 'full_3d_v3'
    assert actual.metadata['thermal_mode'] == 'true_h'
    assert diagnostics['native_full_3d']['entry_version'] == 3
    history = diagnostics['_ltne_info']
    assert len(history) == 2
    expected = dict(update_tol=1e-6, coupled_energy_tol=1e-5, equation_energy_tol=1e-5,
        max_iterations=1000, sweeps=25, omega=.6, energy_algorithm='legacy_h_fou',
        require_enthalpy_update_on_temperature=False,
        effective_settings_source='native_completed_thermal_call', driver_abi=3)
    for balance in [diagnostics['true_h_balance'], *(row['true_h_balance'] for row in history)]:
        settings = balance['effective_settings']
        assert {key: settings[key] for key in expected} == expected
        assert 'temperature_update_tol_K' not in settings
        assert balance['converged'] and balance['exit_reason'] == 'converged'
        assert np.isfinite(balance['residual']) and balance['residual'] < 1e-6
        for key in ('coupled_energy_balance', 'equation_energy_balance'):
            assert np.isfinite(balance[key]['ratio']) and balance[key]['ratio'] <= 1e-5
        assert max(balance['enthalpy_clip_counts']['total']) == 0


def test_capped_public_keeps_distinct_pressure_states(native_path):
    prepared=case('air-sco2',2);a=cpp_run(prepared,control(native_path));e=python_run(prepared)
    assert not a.run_status['converged']
    assert a.metadata['diagnostics']['true_h_balance']['post_after_last_thermal']
    assert np.max(np.abs(a.fields['P_report_A']-a.fields['P_thermal_A']))>1e-5
    compare(a.fields,e.fields,'cap-fields',engineering=True)
    for key in ('P_A_offset_Pa','P_B_offset_Pa','P_A_range_Pa','P_B_range_Pa'):
        compare(a.metadata['diagnostics']['true_h_balance'][key],e.metadata['diagnostics']['true_h_balance'][key],key)


@pytest.mark.parametrize('during',[False,True])
def test_native_cancellation_never_returns_a_field_result(native_path,during):
    calls=[]
    def cancel():
        calls.append(1)
        return len(calls)>= (100 if during else 1)
    with pytest.raises(CancelledError):cpp_run(case(),control(native_path,cancel_check=cancel))


def test_interrupt_after_native_return_releases_owner(native_path, monkeypatch):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    driver = NativeFull3DDriver(native_path, table_directory=ROOT/'.cache/native-deps/tables')
    call, release, released = driver.call, driver.release, []
    def interrupted(*args):
        assert call(*args) == 0
        raise KeyboardInterrupt('native-return')
    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)
    monkeypatch.setattr(driver, 'call', interrupted)
    monkeypatch.setattr(driver, 'release', tracked)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        driver.run_prepared(*build_execution_inputs(case(cap=2)), control(native_path))
    assert released == [None]


def test_outer_and_progress_callback_exception_propagates(native_path):
    def fail(*_):raise RuntimeError('user callback sentinel')
    with pytest.raises(RuntimeError,match='user callback sentinel'):
        cpp_run(case(),control(native_path,outer_iteration=fail))


def test_owned_fields_survive_subsequent_and_parallel_calls(native_path):
    prepared=case();first=cpp_run(prepared,control(native_path));ta=first.fields['Ta'].copy()
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:cpp_run(prepared,control(native_path)),range(2)))
    np.testing.assert_array_equal(first.fields['Ta'],ta)
    for r in results:compare(r.fields,first.fields)


@pytest.mark.parametrize('pair',['air-air','air-sco2','sco2-water'])
def test_opt_in_audit_exports_final_capped_state_and_nu_observations(native_path,pair):
    prepared=case(pair,2)
    prepared=replace(prepared,parameters=dict(prepared.parameters,_emit_audit=True))
    a=cpp_run(prepared,control(native_path));e=python_run(prepared)
    compare(a.metadata['application'],e.metadata['application'],'application',engineering=True)
    expected=e.metadata['diagnostics'];actual=a.metadata['diagnostics']
    for key in expected:
        if key.startswith('_audit_') or key in ('sco2_nu_observations','envelope_reasons','envelope_warnings'):
            compare(actual[key],expected[key],key,engineering=True)


@pytest.mark.parametrize('design_mode',['grid','continuous','continuous_xyz','asymmetric'])
def test_prepared_spatial_and_asymmetric_geometry(native_path,design_mode):
    cfg=_config(3,True)
    cfg=replace(cfg,fluid_A=replace(cfg.fluid_A,type='air'),fluid_B=replace(cfg.fluid_B,type='air',u_mps=2.,P_in_Pa=2e5))
    if design_mode=='grid':
        cells=[dict(x0=0.,x1=.5,y0=0.,y1=1.,L=6.,t=.4),dict(x0=.5,x1=1.,y0=0.,y1=1.,L=8.,t=.6)]
        cfg=replace(cfg,zones=ZoneInputConfig(enabled=True,axis='grid',grid={'cells':cells}))
    elif design_mode in ('continuous','continuous_xyz'):
        xyz=design_mode=='continuous_xyz'
        coords=np.meshgrid(*([np.linspace(0.,1.,3)]*(3 if xyz else 2)),indexing='ij')
        field=sum((i+1)*v for i,v in enumerate(coords))
        values={'x_decision':np.r_[(6.+.2*field).ravel(),(.4+.02*field).ravel()].tolist(),
            'n_ctrl_x':3,'n_ctrl_y':3,'symmetric_y':False,'spline_order':2,'L_bounds':[4.,8.],'t_bounds':[.3,.6]}
        if xyz:values['n_ctrl_z']=3
        cfg=replace(cfg,zones=ZoneInputConfig(enabled=True,axis='continuous',config=values))
    else:
        cfg=replace(cfg,geometry=replace(cfg.geometry,delta_levelset=.05))
    prepared=prepare_case(cfg,case_id='native-'+design_mode)
    a=cpp_run(prepared,control(native_path));e=python_run(prepared)
    for key in ('fields','boundary_fluxes','pressure_evidence','run_status'):
        compare(getattr(a,key),getattr(e,key),design_mode+'/'+key)
    for key in ('Q','Q_A','Q_B','dP_A','dP_B','energy_imbalance_rel'):
        compare(evaluate(a).metrics[key].value,evaluate(e).metrics[key].value,key)


@pytest.mark.parametrize('pair',['air-air','air-water','water-air','air-sco2','sco2-water'])
def test_runtime_range_evidence_preserves_original_sources_and_denominators(native_path,pair,monkeypatch):
    # The public entry owns its warning scope; inspect the adapter's raw range
    # records here, while the remaining integration cases use the public entry.
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case as adapter_run
    from sjtu_tpmshx.domain import run_warnings
    from sjtu_tpmshx.models import tpms_props, nu_correlations
    prepared=case(pair,2);expected={};actual={};snapshots={}
    def observe(source,values,*args,**kwargs):
        array=np.asarray(values)
        key=(*source,array.shape,run_warnings._range_context.get())
        snapshots.setdefault(key,[]).append(array.copy())
        return run_warnings.record_range(source,values,*args,**kwargs)
    monkeypatch.setattr(tpms_props,'record_range',observe)
    monkeypatch.setattr(nu_correlations,'record_range',observe)
    with warning_scope(expected):python_run(prepared)
    with warning_scope(actual):adapter_run(prepared,control(native_path))
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,RangeRecord):
            a=dict(vars(actual[key]));e=dict(vars(value))
            for name in ('minimum','maximum'):
                got,want=a.pop(name),e.pop(name)
                if want is None:
                    assert got is None
                    continue
                label='temperature' if value.quantity=='T' else 'range'
                compare(got[0],want[0],label,engineering=True)
                if got[1]!=want[1]:
                    # Symmetric cells can exchange argmin/argmax after roundoff.
                    # The reported location must still carry the same extremum
                    # in an observed source snapshot, not merely be in bounds.
                    rtol,atol=(0.,.01) if value.quantity=='T' else (1e-4,1e-6)
                    assert any(np.isclose(row[got[1]],want[0],rtol=rtol,atol=atol)
                               for row in snapshots[key])
            compare(a,e,str(key))
        else:
            assert actual[key]==value


@pytest.mark.parametrize('converged', [False, True])
def test_public_saved_case_cli_replay_and_postprocess_without_python_kernels(
        native_path, tmp_path, converged):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.result_io import load_result
    prepared = (prepare_case(ComputeConfig.from_json(str(ROOT/'examples/three_module/air_3d.json')),
                            case_id='full3d-cpp-replay') if converged else case('air-sco2', 2))
    case_path, result_path = tmp_path/'case.h5', tmp_path/'result.h5'
    save_case(prepared, case_path)
    code = '''
import sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.workflows.cli import main
converged = sys.argv[5] == 'True'
status = main(['solve', sys.argv[1], sys.argv[2], '--backend', 'cpp',
    '--native-library', sys.argv[3], '--native-table-directory', sys.argv[4]])
assert status == (0 if converged else 2), status
result = load_result(sys.argv[2])
assert result.backend_id == 'cpp' and result.grid['dimension'] == 3
assert result.run_status['execution'] == 'completed'
assert result.run_status['converged'] == converged
assert evaluate(result).metrics['Q'].status == 'available'
assert main(['postprocess', sys.argv[2], sys.argv[2]+'.json']) == 0
assert load_metrics(sys.argv[2]+'.json').metrics == evaluate(result).metrics
assert sys.argv[3] not in str(result.metadata) and sys.argv[4] not in str(result.metadata)
forbidden = ('numba', 'sjtu_tpmshx.solvers.ltne_', 'sjtu_tpmshx.solvers.simple_',
    'sjtu_tpmshx.solvers._kernels', 'sjtu_tpmshx.solvers.backends.python.three_d.runtime')
assert not [name for name in sys.modules if name.startswith(forbidden)]
'''
    process = subprocess.run([sys.executable, '-c', code, str(case_path), str(result_path),
        str(native_path), str(tmp_path/'tables'), str(converged)], cwd=ROOT,
        capture_output=True, text=True, timeout=90)
    assert process.returncode == 0, process.stdout+process.stderr
    restored = load_result(result_path)
    assert restored.backend_id == 'cpp' and restored.run_status['converged'] == converged
    if not converged:
        assert restored.metadata['diagnostics']['true_h_balance']['post_after_last_thermal']
        assert np.max(np.abs(restored.fields['P_report_A']-restored.fields['P_thermal_A'])) > 1e-5


@pytest.mark.parametrize('relative', [False, True])
def test_public_full3d_missing_library_never_falls_back(native_path, tmp_path, relative):
    selected = control('missing.dll' if relative else tmp_path/'missing.dll')
    error, message = (ValueError, 'absolute') if relative else (FileNotFoundError, 'missing')
    with patch('sjtu_tpmshx.solvers.backends.python.three_d.runtime.build_problem',
               side_effect=AssertionError('Python numerical driver called')):
        with pytest.raises(error, match=message):
            cpp_run(case(), selected)
