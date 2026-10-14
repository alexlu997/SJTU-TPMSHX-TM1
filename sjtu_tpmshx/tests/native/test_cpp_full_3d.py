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
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
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
        samples = result.metadata['property_sampling']
        for label, fluid in zip('AB', pair.split('-')):
            hv = [r for r in samples if r['side'] == label and r['stage'] == 'thermal_hv' and r['quantity'] == 'conductivity']
            assert len(hv) == 1 and hv[0]['outer_index'] == result.run_status['outer_index']
            assert hv[0]['pressure'] == 'inlet'
            assert hv[0]['temperature'] == ('previous_thermal_or_seed' if fluid == 'sco2' else 'inlet')
        assert result.metadata['input_resolution']['source'] == 'CaseData.parameters'
    assert actual.metadata['execution_record']['property_sampling']['version'] == 'full_sampling_v1'
    for result in (actual,expected):
        _physical_gates(result)
        audit = evaluate_physical_balance(result)['energy']
        assert audit['status'] == 'available'
        assert abs(audit['telescoping_error']) < 1e-6
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


def test_pre_cancelled_case_skips_preparation_and_library_load(tmp_path):
    prepared = case()
    with patch('sjtu_tpmshx.solvers.backends.prepared_3d.build_execution_inputs',
               side_effect=AssertionError('cancelled case prepared for execution')):
        with pytest.raises(CancelledError):
            cpp_run(prepared, control(tmp_path/'missing.dll', cancel_check=lambda: True))


@pytest.mark.parametrize('during',[False,True])
def test_native_cancellation_never_returns_a_field_result(native_path,during):
    calls=[]
    def cancel():
        calls.append(1)
        return len(calls)>= (100 if during else 1)
    with pytest.raises(CancelledError):cpp_run(case(),control(native_path,cancel_check=cancel))


def test_interrupt_after_native_return_releases_owner(native_path, monkeypatch):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
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


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('failure', ['cancel', 'callback'])
@pytest.mark.parametrize('solid_dtype', [np.float64, np.float32])
def test_native_call_borrows_case_arrays_and_recovers(native_path, monkeypatch, dimension, failure, solid_dtype):
    import ctypes as ct
    from sjtu_tpmshx.solvers.backends.cpp import full_2d, full_3d
    from sjtu_tpmshx.tests.native.test_full_2d import configuration

    config = configuration(outer=2) if dimension == 2 else _config(3, True)
    config = replace(config, fluid_A=replace(config.fluid_A, T_in_K=300.),
                     fluid_B=replace(config.fluid_B, type='water', T_in_K=300., P_in_Pa=2e5))
    if dimension == 2:
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [6.8, 7., 7.1, 7.2, .5, .52, .55, .58],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    prepared = prepare_case(config, case_id='borrowed-native-input')
    solid_key = 'K_ss_arr' if dimension == 2 else 'K_ss'
    prepared = replace(prepared, design_fields={**prepared.design_fields,
        solid_key: prepared.design_fields[solid_key].astype(solid_dtype)})
    before = {key: value.copy() for key, value in prepared.design_fields.items()
              if isinstance(value, np.ndarray)}
    from sjtu_tpmshx.solvers.backends import prepared_2d as exec2
    from sjtu_tpmshx.solvers.backends import prepared_3d as exec3
    execution = exec2 if dimension == 2 else exec3
    builder = execution.build_execution_inputs
    with patch.object(execution, 'build_execution_inputs',
                      lambda case, **_: builder(case, copy_design=True)):
        reference = cpp_run(prepared, control(native_path))
    driver_type = full_2d.NativeFull2DDriver if dimension == 2 else full_3d.NativeFull3DDriver
    original_init, entered = driver_type.__init__, []

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        original_call = self.call

        def call(*args):
            if dimension == 2:
                pointers = {key: args[1][index] for key, index in (
                    ('K_ffA_arr', 3), ('K_ffB_arr', 4), ('K_ss_arr', 5), ('eps_arr', 6))}
            else:
                data = args[0]._obj
                pointers = {key: getattr(data, field).data for key, field in (
                    ('eps_arr', 'epsilon'), ('eps_A', 'epsilon_a'), ('eps_B', 'epsilon_b'),
                    ('K_m2', 'permeability'), ('cF_per_m', 'forchheimer'),
                    ('K_ss', 'solid_conductivity'), ('L_field_m', 'cell_length'))}
            for key, pointer in pointers.items():
                source = prepared.design_fields[key]
                same_buffer = ct.cast(pointer, ct.c_void_p).value == source.ctypes.data
                assert same_buffer == (source.dtype == np.float64)
                np.testing.assert_array_equal(np.ctypeslib.as_array(pointer, shape=(source.size,)), source.ravel())
            entered.append(True)
            return original_call(*args)

        call.argtypes = original_call.argtypes
        self.call = call

    monkeypatch.setattr(driver_type, '__init__', init)

    def fail(*_):
        raise RuntimeError('borrow callback sentinel')

    options = {'cancel_check': lambda: bool(entered)} if failure == 'cancel' else {'outer_iteration': fail}
    with pytest.raises(CancelledError if failure == 'cancel' else RuntimeError,
                       match='cancelled' if failure == 'cancel' else 'borrow callback sentinel'):
        cpp_run(prepared, control(native_path, **options))
    assert entered
    result = cpp_run(prepared, control(native_path))
    compare(result.fields, reference.fields)
    compare(result.run_status, reference.run_status)
    for key, expected in before.items():
        np.testing.assert_array_equal(prepared.design_fields[key], expected)
        assert not prepared.design_fields[key].flags.writeable


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
    if design_mode == 'asymmetric':
        audit = evaluate_physical_balance(a)['energy']
        assert audit['status'] == 'available' and abs(audit['telescoping_error']) < 1e-6
        assert evaluate_physical_balance(e)['energy']['status'] == 'unavailable'
        # The Python capacity-temperature path has no full energy audit.
        a = replace(a, boundary_fluxes=dict(a.boundary_fluxes, energy=None))
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
    with warning_scope(actual):result=adapter_run(prepared,control(native_path))
    last={(*row['source'],tuple(row['shape']),(row['side'],row['stage'],row['layout'])): row
          for row in result.metadata['_last_closure_ranges']}
    assert last.keys()=={key for key,value in expected.items() if isinstance(value,RangeRecord)}
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,RangeRecord):
            a=dict(vars(actual[key]));e=dict(vars(value))
            assert a.pop('last') is None
            sample=e.pop('last')
            for name in ('low','high','size','nonfinite'):
                assert last[key][name]==sample[name]
            for name in ('minimum','maximum'):
                got,want=last[key][name],sample[name]
                if want is None:
                    assert got is None
                else:
                    rtol,atol=(0.,.01) if value.quantity=='T' else (1e-4,1e-6)
                    assert np.isclose(got[0],want[0],rtol=rtol,atol=atol)
                    assert np.isclose(snapshots[key][-1][got[1]],want[0],rtol=rtol,atol=atol)
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
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
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
def test_public_full3d_missing_library_never_falls_back(tmp_path, relative):
    selected = control('missing.dll' if relative else tmp_path/'missing.dll')
    error, message = (ValueError, 'absolute') if relative else (FileNotFoundError, 'missing')
    with patch('sjtu_tpmshx.solvers.backends.python.three_d.runtime.build_problem',
               side_effect=AssertionError('Python numerical driver called')):
        with pytest.raises(error, match=message):
            cpp_run(case(), selected)


@pytest.mark.parametrize('pair,route,audit', [
    ('air-air', 'model_h', False), ('air-water', 'model_h', False),
    ('water-air', 'model_h', False), ('air-sco2', 'legacy_h_fou', False),
    ('sco2-water', 'legacy_h_fou', False), ('air-air', 'model_h', True),
    ('air-sco2', 'legacy_h_fou', True), ('sco2-water', 'legacy_h_fou', True),
    ('air-air', 'temperature_cc', False), ('air-air', 'temperature_staggered', False),
    ('air-sco2', 'temperature_fou', False), ('air-sco2', 'temperature_sou', False),
])
def test_application_capture_owns_shared_aliases_and_keeps_full_evidence(
        native_path, monkeypatch, tmp_path, pair, route, audit):
    from sjtu_tpmshx.io.result_io import load_result, save_result
    from sjtu_tpmshx.solvers.backends.cpp import full_3d
    from sjtu_tpmshx.solvers.backends.cpp.full_3d_capture import capture_result
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    prepared = case(pair, 2)
    cfg, p = build_execution_inputs(prepared)
    cfg.update(max_iter_simple=1, _emit_audit=audit, ltne_enthalpy_outer=2, ltne_enthalpy_nsweep=1)
    cfg['_environment'] = dict(cfg.get('_environment', {}), TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None)
    p.update(max_outer=1, ltne_max_iter=1)
    if route in ('temperature_cc', 'temperature_staggered'):
        cfg.update(variable_rho_cp=False, conservative_ltne=False,
                   force_cc_ltne=route.endswith('_cc'))
    elif route in ('temperature_fou', 'temperature_sou'):
        cfg['enthalpy_algorithm'] = route
    original = full_3d._detach
    complete = []

    def detach(*args, **kwargs):
        complete.append(original(*args, **dict(kwargs, application_only=False)))
        return original(*args, **kwargs)

    monkeypatch.setattr(full_3d, '_detach', detach)
    driver = full_3d.NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    raw = driver._run_prepared(cfg, p, application_only=True)
    full, = complete
    assert 'rho_cp' in full and 'rho_cp' not in raw
    for actual, expected in zip(raw['flow'], full['flow']):
        assert expected['d_u'].flags.writeable
        assert 'd_u' not in actual and 'face_velocity_real' not in actual
        assert ('u' in actual) is audit
    restored = dict(full, **raw)
    restored['flow'] = [dict(f, **a) for f, a in zip(full['flow'], raw['flow'])]
    result = capture_result(prepared, cfg, p, raw, driver.abi)
    expected = capture_result(prepared, cfg, p, restored, driver.abi)
    for key in ('fields', 'field_metadata', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'metadata'):
        compare(getattr(result, key), getattr(expected, key), key)
    aliases = [(result.fields[key], result.fields[key + '_display']) for key in ('Ta', 'Tb', 'Ts')]
    aliases += [(result.fields['P_report_' + side], result.fields['P_f' + side + '_display']) for side in 'AB']
    true_h = result.boundary_fluxes['true_h']
    if true_h is not None:
        aliases += [pair for side in 'AB' for pair in zip(
            result.boundary_fluxes['mass_' + side], true_h['mass_flux_' + side])]
    for left, right in aliases:
        assert left is not right and np.shares_memory(left, right)
        assert not left.flags.writeable and not right.flags.writeable
        with pytest.raises(ValueError):
            left.setflags(write=True)
        shape, dtype = right.shape, right.dtype
        left.shape = (left.size,)
        left.dtype = np.uint8
        assert right.shape == shape and right.dtype == dtype
        left.dtype, left.shape = dtype, shape
    path = tmp_path / 'shared-result.h5'
    save_result(result, path)
    loaded = load_result(path)
    for key in ('fields', 'boundary_fluxes', 'run_status'):
        compare(getattr(loaded, key), getattr(result, key), key)


@pytest.mark.parametrize('failure', ['detach', 'query'])
def test_application_failure_releases_native_owner(native_path, monkeypatch, failure):
    from sjtu_tpmshx.solvers.backends.cpp import full_3d
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    driver = full_3d.NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    release, released = driver.release, []

    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)

    def fail(*args, **kwargs):
        raise RuntimeError('capture failure')

    monkeypatch.setattr(driver, 'release', tracked)
    if failure == 'detach':
        monkeypatch.setattr(full_3d, '_detach', fail)
    else:
        monkeypatch.setattr(driver, '_bootstrap_traces', fail)
    cfg, p = prepared('air-air', counts=(4, 4, 4), max_iter_simple=1)
    p.update(max_outer=1, ltne_max_iter=1)
    with pytest.raises(RuntimeError, match='capture failure'):
        driver._run_prepared(cfg, p, application_only=True)
    assert released == [None]


@pytest.mark.parametrize('dimension,real_co2', [(2, False), (3, False), (2, True), (3, True)])
def test_public_applicability_keeps_original_inlet_and_last_local_sources(native_path, tmp_path, dimension, real_co2):
    from sjtu_tpmshx.domain.portable_data import mutable_data
    from sjtu_tpmshx.io.result_io import save_result, load_result
    from sjtu_tpmshx.postprocess.api import evaluate_applicability
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.tests.native.test_full_2d import configuration
    prepared = (prepare_case(configuration(outer=2), case_id='ranges-2d')
                if dimension == 2 else case('air-air', 2))
    if real_co2:
        from sjtu_tpmshx.tests.test_co2_model import co2_config
        config = co2_config(1 if dimension == 2 else 3)
        prepared = prepare_case(replace(config, solver=replace(config.solver, max_outer_ltne=2)), case_id='co2-ranges')
    summaries = []
    for backend in ('python', 'cpp'):
        result = run_case(prepared, control(native_path) if backend == 'cpp' else RunControl())
        summary = evaluate_applicability(result)
        assert summary['missing'] == []
        assert summary['status'] in ('within_limits', 'outside_limits')
        assert '_last_closure_ranges' not in result.metadata
        for side in 'AB':
            assert any(row['side'] == side and row['source'][0] == 'nu_raw'
                       and row['captured'] for row in summary['checks']['final'])
        if real_co2:
            assert any(row['source'] == ('nu_pr', 'co2', 'Gyroid')
                       for row in summary['checks']['final'])
        path = save_result(result, tmp_path / (backend + '.h5'))
        assert mutable_data(evaluate_applicability(load_result(path))) == mutable_data(summary)
        summaries.append(summary)
    assert summaries[0]['within_limits'] == summaries[1]['within_limits']
    assert {row['source'][1] for row in summaries[1]['checks']['inlet']
            if row['source'][0] == 'geometry'} == {'L_field_m', 't_field_m'}


@pytest.mark.parametrize('seeded', [False, True])
def test_first_thermal_sampling_distinguishes_inlet_and_seed(native_path, seeded):
    from sjtu_tpmshx.preprocess.api import prepare_research_case
    from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d
    cfg = _cheap_3d(max_outer_ltne=1, fluid_type_A='sco2', fluid_type_B='water',
                   u_A=.2, u_B=.2, T_inA=500., T_inB=300., P_inA=12e6, P_inB=2e6,
                   T_s_init=350. if seeded else None)
    prepared = prepare_research_case(cfg, case_id='first-sampling')
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    cfg, data = build_execution_inputs(prepared)
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    native = driver.run_prepared(cfg, data, control(native_path))
    reference = python_run(prepared)
    for rows in (native['property_sampling'], reference.metadata['property_sampling']):
        sample = next(row for row in rows if row['side'] == 'A' and row['stage'] == 'thermal_hv'
                      and row['quantity'] == 'conductivity')
        assert sample['outer_index'] == 0
        assert sample['temperature'] == ('previous_thermal_or_seed' if seeded else 'inlet')
        assert sample['operation'] == ('local_evaluation' if seeded else 'scalar_evaluation')
        assert any(row['stage'] == 'thermal_warmup' for row in rows)
        post = [row for row in rows if row['stage'] == 'flow_post']
        assert post and all(row['temperature'] == 'current_thermal_return' for row in post)


def test_inactive_python_side_has_no_flow_or_exchange_sampling():
    from sjtu_tpmshx.preprocess.api import prepare_research_case
    from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d
    cfg = _cheap_3d(max_outer_ltne=1)
    cfg.update(fluid_B_cfg=None, sweep_profile=None)
    result = python_run(prepare_research_case(cfg, case_id='inactive-sampling'))
    assert result.metadata['input_resolution']['active_sides'] == ('A',)
    energy = next(row for row in result.metadata['property_sampling'] if row['quantity'] == 'energy_relation')
    assert energy['temperature'] == 'inlet' and energy['operation'] == 'frozen_capacity_temperature'
    assert not [row for row in result.metadata['property_sampling']
                if row['side'] == 'B' and row['stage'] in ('thermal_hv', 'flow', 'flow_post')]


@pytest.mark.parametrize('pair', ['air-air', 'water-air'])
def test_public_model_h_controls_retain_native_calls_and_startup_budget(native_path, tmp_path, pair):
    from sjtu_tpmshx.io.case_io import load_case, save_case
    from sjtu_tpmshx.io.result_io import load_result, save_result
    prepared = case(pair, 2)
    prepared = replace(prepared, parameters={**prepared.parameters,
        'model_h_max_iterations': 17, 'model_h_temperature_tol_K': 1e-5, 'model_h_q_relative_tol': 1e-8})
    save_case(prepared, tmp_path/'case.h5')
    result = cpp_run(load_case(tmp_path/'case.h5'), control(native_path))
    records = result.metadata['model_h_iterations']['records']
    assert records and all(row['stage'] == 'outer_thermal' for row in records)
    assert all(row['settings']['max_iterations'] <= 17 and row['settings']['chunk_iterations'] == 250
               for row in records)
    assert all(row['settings']['temperature_update_tolerance_K'] == 1e-5
               and row['settings']['q_relative_tolerance'] == 1e-8 for row in records)
    assert result.metadata['execution_record']['numerics']['effective_settings'] == records[-1]['settings']
    assert not result.run_status['converged']
    for row in result.metadata['diagnostics']['_ltne_info']:
        if 'coupling_startup' in row:
            assert row['coupling_startup']['iteration_budget'] == 17
            assert row['coupling_startup']['total_iterations'] <= 17
    save_result(result, tmp_path/'result.h5')
    assert load_result(tmp_path/'result.h5').metadata['model_h_iterations'] == result.metadata['model_h_iterations']


def test_eos_route_rejects_model_h_override_before_native_work(native_path):
    prepared = case('air-sco2', 2)
    prepared = replace(prepared, parameters={**prepared.parameters, 'model_h_temperature_tol_K': 1e-5})
    callbacks = []
    with pytest.raises(ValueError, match=r'model-h iteration controls require an integral h\(T\) route'):
        cpp_run(prepared, control(native_path, progress=lambda *args: callbacks.append(args)))
    assert not callbacks


@pytest.mark.parametrize('nz', [1, 4])
def test_integral_temperature_delegate_receives_model_h_controls(native_path, nz):
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    cfg, data = prepared('air-air', directions=(0, 3), counts=(4, 4, nz),
                         conservative_ltne=False, force_cc_ltne=True)
    cfg.update(model_h_max_iterations=17, model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8)
    data['max_outer'] = 2
    raw = NativeFull3DDriver(native_path).run_prepared(cfg, data)
    calls = raw['model_h_iterations']['records']
    assert len(calls) == 2
    assert all(row['settings']['max_iterations'] == 17
               and row['settings']['chunk_iterations'] == (500 if nz == 1 else 250)
               and row['settings']['temperature_update_tolerance_K'] == 1e-5
               and row['settings']['q_relative_tolerance'] == 1e-8 for row in calls)


class _PauseCheckpoint(Exception):
    pass


def _exact_resume_values(actual, expected, path=''):
    if isinstance(expected, Mapping):
        assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            if key not in ('build_seconds', 'solve_seconds'):
                _exact_resume_values(actual[key], value, path+'/'+str(key))
    elif isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected), path
        for index, value in enumerate(expected):
            _exact_resume_values(actual[index], value, path+'/'+str(index))
    elif isinstance(expected, (np.ndarray, float, np.floating)):
        np.testing.assert_array_equal(actual, expected, err_msg=path)
    else:
        assert actual == expected, path


@pytest.mark.parametrize('pair', ['air-air', 'water-air', 'sco2-water'])
@pytest.mark.parametrize('cut', [0, 1, 3])
def test_native_checkpoint_hdf5_round_trip(native_path, tmp_path, pair, cut):
    from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.solver_checkpoint_io import (
        save_solver_checkpoint, load_solver_checkpoint, load_checkpoint_case)
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
    prepared_case = case(pair, cap=3)
    case_path = save_case(prepared_case, tmp_path/'case.h5')
    saved_path = tmp_path/'checkpoint.h5'
    expected = run_case(prepared_case, control(native_path))
    def save_at_boundary(state):
        if int(state['state.result.outer.size'][0]) == cut:
            saved = SolverCheckpoint(str(case_path), prepared_case.case_id, prepared_case.model_refs, state)
            save_solver_checkpoint(saved, saved_path)
            state['state.temperature.0'][0] = -1.
            assert saved.native_state['state.temperature.0'][0] > 0.
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared_case, control(native_path), checkpoint=save_at_boundary)
    saved = load_solver_checkpoint(saved_path)
    actual = run_case(load_checkpoint_case(saved), control(native_path), resume_state=saved.native_state)
    for key in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        _exact_resume_values(getattr(actual, key), getattr(expected, key), key)
    assert actual.metadata['continuation']['completed_outer_steps'] == cut
    _exact_resume_values({k: v for k, v in actual.metadata.items() if k != 'continuation'}, expected.metadata)


@pytest.mark.parametrize('damage', ['build', 'format', 'input', 'control', 'type', 'size', 'unknown', 'missing',
                                     'thermal', 'geometry', 'phase', 'nonfinite',
                                     'premature_finish', 'different_exit', 'thermal_mode', 'anderson_control'])
def test_native_checkpoint_rejects_damaged_fields(native_path, damage):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    cfg, p = build_execution_inputs(case(cap=3))
    if damage == 'anderson_control':
        cfg['outer_anderson'] = True
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    saved = {}
    def pause(state):
        if int(state['state.result.outer.size'][0]) == (0 if damage == 'premature_finish' else 1):
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        driver.run_prepared(cfg, p, checkpoint=pause)
    if damage == 'build':
        saved['build'] = 'another-build'
    elif damage == 'format':
        saved['format'][0] = 2
    elif damage == 'input':
        saved['input.a.inlet_velocity'][0] *= 1.01
    elif damage == 'control':
        saved['control.max_outer'][0] += 1
    elif damage == 'type':
        saved['state.temperature.0'] = saved['state.temperature.0'].astype(np.float32)
    elif damage == 'size':
        saved['state.temperature.0'] = saved['state.temperature.0'][:-1].copy()
    elif damage == 'unknown':
        saved['unknown'] = np.zeros(1)
    elif damage == 'thermal':
        saved['state.result.thermal.temperature.0'] = np.empty(0)
    elif damage == 'geometry':
        saved['state.result.flow.0.epsilon'][0] *= .99
    elif damage == 'phase':
        saved['state.phase'][0] = 0
    elif damage == 'premature_finish':
        saved['state.phase'][0] = 2
        saved['state.result.outer_ok'][0] = 1
    elif damage == 'different_exit':
        saved['state.result.stop'][0] = 2
    elif damage == 'anderson_control':
        saved['state.anderson.0.value.trust'][0] *= 2
    elif damage == 'thermal_mode':
        saved['state.result.thermal.mode'][0] = 2
    elif damage == 'nonfinite':
        saved['state.temperature.0'][0] = np.nan
    else:
        del saved['state.temperature.0']
    with pytest.raises((ValueError, TypeError), match='state|continuation'):
        driver.run_prepared(cfg, p, resume_state=saved)


_CHECKPOINT_CHILD = r'''
import os
from pathlib import Path
import sys
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.io.case_io import load_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.solver_checkpoint_io import (
    load_solver_checkpoint, save_solver_checkpoint, load_checkpoint_case)
from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
mode, case_path, saved_path, result_path, library, tables = sys.argv[1:]
control = RunControl(backend='cpp', native_library=library, native_table_directory=tables)
if mode == 'interrupt':
    case = load_case(case_path)
    def stop(state):
        if int(state['state.result.outer.size'][0]) == 1:
            save_solver_checkpoint(SolverCheckpoint(case_path, case.case_id, case.model_refs, state), saved_path)
            os._exit(23)
    run_case(case, control, checkpoint=stop)
    raise RuntimeError('checkpoint boundary was not reached')
saved = load_solver_checkpoint(saved_path)
result = run_case(load_checkpoint_case(saved), control, resume_state=saved.native_state)
save_result(result, result_path)
'''


@pytest.mark.parametrize('pair,overrides', [('air-air', {}), ('sco2-water', {}),
    ('water-air', dict(model_h_max_iterations=17, model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8))])
def test_native_checkpoint_continues_after_process_exit(native_path, tmp_path, pair, overrides):
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
    prepared_case = case(pair, cap=3)
    prepared_case = replace(prepared_case, parameters={**prepared_case.parameters, **overrides})
    case_path = save_case(prepared_case, tmp_path/'case.h5')
    saved_path, result_path = tmp_path/'checkpoint.h5', tmp_path/'result.h5'
    arguments = [str(case_path), str(saved_path), str(result_path), str(native_path),
                 control(native_path).native_table_directory]
    stopped = subprocess.run([sys.executable, '-c', _CHECKPOINT_CHILD, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    assert not result_path.exists()
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state['state.result.outer.size'][0] == 1
    finished = subprocess.run([sys.executable, '-c', _CHECKPOINT_CHILD, 'resume', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual = load_result(result_path)
    expected = run_case(prepared_case, control(native_path))
    for key in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        _exact_resume_values(getattr(actual, key), getattr(expected, key), key)
    _exact_resume_values({k: v for k, v in actual.metadata.items() if k != 'continuation'}, expected.metadata)
    actual_metrics, expected_metrics = evaluate(actual), evaluate(expected)
    for key, metric in expected_metrics.metrics.items():
        assert actual_metrics.metrics[key].status == metric.status
        _exact_resume_values(actual_metrics.metrics[key].value, metric.value, key)


def test_checkpoint_write_failure_keeps_previous_file(native_path, tmp_path, monkeypatch):
    from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
    from sjtu_tpmshx.io import hdf5_data
    from sjtu_tpmshx.io.solver_checkpoint_io import save_solver_checkpoint, load_solver_checkpoint
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
    prepared_case = case(cap=3)
    saved_path = tmp_path/'checkpoint.h5'
    states = []
    def pause(state):
        states.append(SolverCheckpoint(str(tmp_path/'case.h5'), prepared_case.case_id, prepared_case.model_refs, state))
        raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared_case, control(native_path), checkpoint=pause)
    original = states[0]
    save_solver_checkpoint(original, saved_path)
    def failed_replace(*_):
        raise OSError('injected checkpoint publication failure')
    monkeypatch.setattr(hdf5_data.os, 'replace', failed_replace)
    with pytest.raises(OSError, match='publication failure'):
        save_solver_checkpoint(original, saved_path)
    restored = load_solver_checkpoint(saved_path)
    _exact_resume_values(restored.native_state, original.native_state)
    assert list(tmp_path.glob('*.tmp')) == []


def test_checkpoint_process_kill_before_publish_keeps_previous_file(native_path, tmp_path):
    import time
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint
    prepared_case = case(cap=3)
    case_path = save_case(prepared_case, tmp_path/'case.h5')
    saved_path = tmp_path/'checkpoint.h5'
    arguments = [str(case_path), str(saved_path), str(tmp_path/'result.h5'), str(native_path),
                 control(native_path).native_table_directory]
    stopped = subprocess.run([sys.executable, '-c', _CHECKPOINT_CHILD, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    previous = load_solver_checkpoint(saved_path)
    ready = tmp_path/'before-publish'
    child = r'''
from pathlib import Path
import sys
import time
from sjtu_tpmshx.io import hdf5_data
from sjtu_tpmshx.io.solver_checkpoint_io import load_solver_checkpoint, save_solver_checkpoint
path, ready = map(Path, sys.argv[1:])
previous = load_solver_checkpoint(path)
def before_publish(*_):
    ready.write_text('temporary HDF5 file is closed')
    time.sleep(30)
    raise RuntimeError('parent did not interrupt publication')
hdf5_data.os.replace = before_publish
save_solver_checkpoint(previous, path)
'''
    process = subprocess.Popen([sys.executable, '-c', child, str(saved_path), str(ready)],
                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), 'child did not reach the checkpoint publication boundary'
        process.kill()
        process.communicate(timeout=10)
        assert process.returncode != 0
        _exact_resume_values(load_solver_checkpoint(saved_path).native_state, previous.native_state)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize('route', ['temperature_fou', 'temperature_sou',
                                  'single_cc', 'single_staggered', 'single_sco2_cc',
                                  'conservative_staggered', 'nz1_cc'])
@pytest.mark.parametrize('cut', [0, 1, 'final'])
def test_checkpoint_covers_energy_routes(native_path, route, cut):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    pair = 'sco2-water' if route.startswith('temperature') or route == 'single_sco2_cc' else 'air-air'
    cfg, p = prepared(pair, counts=(4, 4, 1) if route == 'nz1_cc' else None,
                      directions=(0, 3) if route == 'nz1_cc' else None)
    p['max_outer'] = 3
    if route.startswith('single'):
        cfg.update(fluid_B_cfg=None, conservative_ltne=False, force_cc_ltne=route.endswith('_cc'))
    elif route in ('conservative_staggered', 'nz1_cc'):
        cfg.update(variable_rho_cp=False, conservative_ltne=route == 'conservative_staggered',
                   force_cc_ltne=route == 'nz1_cc')
    else:
        cfg['enthalpy_algorithm'] = route
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    expected = driver.run_prepared(cfg, p)
    if cut == 'final':
        cut = len(expected['outer'])
    saved = {}
    def pause(state):
        if int(state['state.result.outer.size'][0]) == cut:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        driver.run_prepared(cfg, p, checkpoint=pause)
    actual = driver.run_prepared(cfg, p, resume_state=saved)
    assert actual.pop('continuation')['completed_outer_steps'] == cut
    _exact_resume_values(actual, expected)


def test_checkpoint_cancel_keeps_last_complete_boundary(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
    prepared_case = case(cap=3)
    saved = []
    cancel = False
    def checkpoint(state):
        nonlocal cancel
        saved.append(state)
        cancel = int(state['state.result.outer.size'][0]) == 1
    with pytest.raises(CancelledError):
        run_case(prepared_case, control(native_path, cancel_check=lambda: cancel), checkpoint=checkpoint)
    assert [int(s['state.result.outer.size'][0]) for s in saved] == [0, 1]
    actual = run_case(prepared_case, control(native_path), resume_state=saved[-1])
    expected = run_case(prepared_case, control(native_path))
    _exact_resume_values(actual.fields, expected.fields)
    _exact_resume_values(actual.run_status, expected.run_status)


def test_checkpoint_callback_error_keeps_original_exception(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import run_case
    original = OSError('checkpoint storage is unavailable')
    def failed_write(_):
        raise original
    with pytest.raises(OSError) as caught:
        run_case(case(cap=3), control(native_path), checkpoint=failed_write)
    assert caught.value is original


def test_full_checkpoint_keeps_active_pressure_hierarchies(native_path):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.tests.native.test_full_3d import prepared
    cfg, p = prepared('air-air', counts=(14, 14, 14), max_iter_simple=3, outer_anderson=True)
    p.update(max_outer=2, ltne_max_iter=10)
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    expected = driver.run_prepared(cfg, p)
    saved = {}
    def pause(state):
        if int(state['state.result.outer.size'][0]) == 1:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        driver.run_prepared(cfg, p, checkpoint=pause)
    for side in (0, 1):
        assert saved[f'state.simple.{side}.value.pressure.construction.present'][0] == 1
    actual = driver.run_prepared(cfg, p, resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)


@pytest.mark.parametrize('name,value', [('model_h_max_iterations', 18),
    ('model_h_temperature_tol_K', 1e-4), ('model_h_q_relative_tol', 1e-7)])
def test_checkpoint_rejects_changed_model_h_controls_before_flow(native_path, name, value):
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    cfg, p = build_execution_inputs(case('water-air', cap=3))
    cfg.update(model_h_max_iterations=17, model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8)
    driver = NativeFull3DDriver(native_path, table_directory=control(native_path).native_table_directory)
    saved = {}
    def pause(state):
        if int(state['state.result.outer.size'][0]) == 1:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        driver.run_prepared(cfg, p, checkpoint=pause)
    assert saved['control.model_h_iterations.max_iterations'][0] == 17
    assert saved['state.result.outer.0.model_h_iterations.0.total_iteration_budget'][0] == 17
    cfg[name] = value
    progress = []
    with pytest.raises(ValueError, match='model_h_iterations'):
        driver.run_prepared(cfg, p, control(native_path, residual=lambda *args: progress.append(args)), resume_state=saved)
    assert not progress
