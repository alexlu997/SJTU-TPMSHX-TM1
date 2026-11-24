"""Public prepared-case handoff to the saved full native 3D stage."""
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.data_types.compute_config import FluidConfig, ZoneInputConfig
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.run_warnings import warning_scope
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.physical_models.envelope import R_AIR_DEFAULT
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.solvers.api import run_case as cpp_run
from tests.python.native.test_native_execution import _config
from tests.python.native.test_full_3d import ROOT
from tests.python.native.full_result_audit import physical_gates
from tests.python.native.shared_library import library_path
from tests.python.native.stage_interception import run_stage


@pytest.fixture(scope='module')
def native_path():
    return library_path()


def case(pair='air-air', cap=30):
    cfg=_config(3,True)
    def fluid(name,side):
        return FluidConfig(type=name,u_mps=3. if name=='air' else .2,
            T_in_K=(350. if name=='water' else 500.) if side==0 else 300.,
            P_in_Pa=12e6 if name=='sco2' else (2e6 if name=='water' else 2e5))
    cfg=replace(cfg,fluid_A=fluid(pair.split('-')[0],0),fluid_B=fluid(pair.split('-')[1],1),
                solver=replace(cfg.solver,max_outer_ltne=cap))
    return prepare_case(cfg,case_id='full-native-'+pair)


def saved_case(pair='air-air', *, prepared_values=(), environment=(), directions=None, counts=None, mesh=None,
               **parameters):
    """Return a prepared 3D case with changed saved parameters, environment and run limits."""
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from tests.python.native.test_full_3d import prepared_case
    base = prepared_case(pair, directions=directions, counts=counts, mesh=mesh)
    values = mutable_data(base.parameters)
    values.update(parameters)
    values['prepared'].update(prepared_values)
    values['_environment'].update(environment)
    return replace(base, parameters=values)


def native_run(saved, *args, **kwargs):
    """Return the raw native capture of one saved-stage run."""
    return run_stage(saved, *args, **kwargs).native


def control(path,**kwargs):
    # Match full 2D fixtures: this loaded library owns one EOS directory.
    return RunControl(backend='cpp',native_library=str(path),native_table_directory=str(ROOT/'.cache/native-deps/tables'),**kwargs)


def compare(actual,expected,path=''):
    if isinstance(expected,Mapping):
        assert actual.keys()==expected.keys(),path
        for key,value in expected.items():compare(actual[key],value,path+'/'+str(key))
    elif isinstance(expected,(tuple,list)):
        assert len(actual)==len(expected),path
        for i,value in enumerate(expected):compare(actual[i],value,path+'/'+str(i))
    elif isinstance(expected,(np.ndarray,float,np.floating)):
        if isinstance(expected,np.ndarray):
            assert np.shape(actual)==expected.shape,path
            if expected.dtype.kind in 'biu':
                np.testing.assert_array_equal(actual,expected,err_msg=path)
                return
        rtol,atol=2e-7,1e-6
        np.testing.assert_allclose(actual,expected,rtol=rtol,atol=atol,equal_nan=True,err_msg=path)
    else:
        assert actual==expected,path


def test_bootstrap_trace_records_recursive_caps_without_changing_legacy_summary(native_path):
    prepared = saved_case('air-air', counts=(26, 26, 26), use_coarse_bootstrap=True, coarse_bootstrap_max_iter=3,
                          max_iter_simple=1, prepared_values=dict(max_outer=1, ltne_max_iter=1))
    actual = native_run(prepared, control(native_path))
    for side, flow in zip('AB', actual['flow']):
        trace = actual['bootstrap_trace'][side]
        assert [row['depth'] for row in trace['levels']] == [1, 2]
        assert [row['coarse_shape'] for row in trace['levels']] == [(13, 13, 13), (6, 6, 6)]
        assert [row['iteration_cap'] for row in trace['levels']] == [3, 200]
        assert trace['actual_levels'] == 2 and trace['started_cap_sum'] == 203
        assert trace['total_charged_iterations'] == sum(row['charged_iterations'] for row in trace['levels']) > 3
        assert flow['bootstrap']['coarse_iters'] == trace['levels'][0]['charged_iterations'] == 3


def test_native_deep_bootstrap_cancel_keeps_partial_trace_without_field_result(native_path):
    prepared = saved_case('air-air', counts=(26, 26, 26), use_coarse_bootstrap=True,
                          coarse_bootstrap_max_iter=7, max_iter_simple=1)
    checkpoints = []

    def cancel():
        checkpoints.append(True)
        # run_case entry, saved-run entry, native entry, deepest SIMPLE entry,
        # first sweep, then cancel before its second sweep. No extra checkpoint is added.
        return len(checkpoints) == 6

    with pytest.raises(CancelledError) as caught:
        cpp_run(prepared, control(native_path, cancel_check=cancel))
    trace = caught.value.coarse_bootstrap_trace['A']
    assert len(checkpoints) == 6
    assert trace['decision'] == 'cancelled'
    assert [row['solve_started'] for row in trace['levels']] == [False, True]
    assert [row['charged_iterations'] for row in trace['levels']] == [0, 1]
    assert [row['stop'] for row in trace['levels']] == ['cancelled', 'cancelled']
    assert trace['actual_levels'] == 1 and trace['started_cap_sum'] == 200
    assert trace['total_charged_iterations'] == 1
    assert caught.value.coarse_bootstrap_trace['B']['actual_levels'] == 0


@pytest.mark.parametrize('enabled', [False, True])
def test_public_bootstrap_trace_roundtrip_and_old_diagnostics_remain_readable(native_path, tmp_path, enabled):
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    prepared = case('air-air', 2)
    prepared = replace(prepared, parameters=dict(prepared.parameters, use_coarse_bootstrap=enabled,
                                                 coarse_bootstrap_max_iter=7))
    actual = cpp_run(prepared, control(native_path))
    trace = actual.metadata['diagnostics']['coarse_bootstrap_trace']
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


@pytest.mark.parametrize('symbol', ['tpmshx_full_3d_get_bootstrap_trace_v1'])
def test_full3d_library_missing_query_has_explicit_capability_error(native_path, monkeypatch, symbol):
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    prepared = case(cap=2)
    open_library = full_3d_stage.open_library

    def partial(*args):
        path, library, abi, table = open_library(*args)

        class PartialLibrary:
            def __getattr__(self, name):
                if name == symbol:
                    raise AttributeError(name)
                return getattr(library, name)
        return path, PartialLibrary(), abi, table

    monkeypatch.setattr(full_3d_stage, 'open_library', partial)
    progress = []
    with pytest.raises(ValueError, match='lacks bootstrap trace v1; rebuild'):
        cpp_run(prepared, control(native_path, progress=progress.append))
    assert not progress


def run_observed(prepared, native_path):
    stage = run_stage(prepared, control(native_path))
    return stage.result, stage


def check_portable(actual, stage, prepared):
    """Compare the published result with the raw native capture of the same run."""
    raw, arrays = stage.native, stage.arrays
    assert actual.backend_id == 'cpp' and actual.case_id == prepared.case_id
    compare(actual.grid, prepared.grid, 'grid')
    compare(actual.metadata['parameters'], prepared.parameters, 'parameters')
    compare(actual.metadata['design_fields'], prepared.design_fields, 'design')
    assert actual.run_status == dict(execution='completed', converged=raw['converged'], outer_index=raw['outer_index'])
    for name, value in zip(('Ta', 'Tb', 'Ts'), arrays['temperature']):
        np.testing.assert_array_equal(actual.fields[name], value)
        assert actual.field_metadata[name]['unit'] == 'K'
    from tests.python.native.result_reference.shared_math import pressure_face_values
    drops = []
    for side, name in enumerate('AB'):
        flow, real = raw['flow'][side], arrays['flow'][side]
        np.testing.assert_array_equal(actual.fields['P_thermal_'+name], arrays['thermal_pressure'][side])
        np.testing.assert_array_equal(actual.fields['P_report_'+name], real['pressure_real'])
        np.testing.assert_array_equal(actual.fields['h_v'+name], arrays['hv'][side])
        for key, value in zip(('uc', 'vc', 'wc'), real['velocity_real']):
            np.testing.assert_array_equal(actual.fields[key+name], value)
            assert actual.field_metadata[key+name]['unit'] == 'm/s'
        for kind in ('mass', 'face_velocity'):
            compare(actual.boundary_fluxes[kind+'_'+name], raw[kind][side], kind)
        inlet, outlet = pressure_face_values(flow['pressure'], flow['widths'][1])
        area = flow['widths'][0][:,None]*flow['widths'][2][None,:]
        drops.append(np.average(inlet, weights=area*flow['inlet_opening'])
            - np.average(outlet, weights=area*flow['outlet_opening']))
        detail = actual.metadata['diagnostics']['convergence_detail']['simple_'+name]
        for key in ('final_res_mom', 'final_res_mass_local', 'final_res_mass_global', 'outlet_backflow_frac'):
            assert detail[key] == flow['last'][key]
    from tests.python.native.enthalpy_fv_audit import sou_advection
    duties, masses, outlets = [], [], []
    for index, side in enumerate('AB'):
        if raw['mode'] == 'model_h':
            ledger = raw['model_h']['_native_model_h'][side]
            compare(actual.boundary_fluxes['model_h'][side], ledger, 'heat faces')
            duties.append(-sum(float(np.sum(face)) for face in ledger.values()))
        else:
            state = raw['true_h']['_native_state']
            duties.append(sou_advection(state['h_'+side], state['h_in_'+side], raw['mass'][index],
                tuple(prepared.grid['d'+axis] for axis in 'xyz'))[1])
        mass = raw['mass'][index]
        masses.append(sum(float(np.maximum(-sign*np.take(face,end,axis=axis),0.).sum())
            for axis,face in enumerate(mass) for end,sign in ((0,-1),(-1,1))))
        direction = prepared.parameters['fluid_'+side+'_cfg']['dir']
        axis, end, sign = direction//2, (-1 if direction%2==0 else 0), (1 if direction%2==0 else -1)
        weights = np.maximum(sign*np.take(mass[axis],end,axis=axis),0.)
        outlets.append(np.average(np.take(arrays['temperature'][index],end,axis=axis),weights=weights))
    metrics = evaluate(actual).metrics
    expected = dict(Q=abs(duties[0]), Q_A=duties[0], Q_B=duties[1],
        dP_A=drops[0], dP_B=drops[1], T_out_A=outlets[0], T_out_B=outlets[1],
        mass_flow_A=masses[0], mass_flow_B=masses[1],
        energy_imbalance_rel=abs(sum(duties))/max(*(abs(x) for x in duties),1e-30))
    for key,value in expected.items():
        assert metrics[key].status == 'available', key
        compare(metrics[key].value, value, key)
    audit = evaluate_physical_balance(actual)['energy']
    assert audit['status'] == 'available' and abs(audit['telescoping_error']) < 1e-6


@pytest.mark.parametrize('pair',['air-air','air-water','water-air','air-sco2','sco2-water'])
def test_public_case_fields_native_ledgers_and_postprocess(native_path, pair):
    prepared = case(pair)
    actual, raw = run_observed(prepared, native_path)
    check_portable(actual, raw, prepared)
    physical_gates(actual)
    samples = actual.metadata['property_sampling']
    for label, fluid in zip('AB', pair.split('-')):
        hv = [r for r in samples if r['side'] == label and r['stage'] == 'thermal_hv' and r['quantity'] == 'conductivity']
        assert len(hv) == 1 and hv[0]['outer_index'] == actual.run_status['outer_index']
        assert hv[0]['pressure'] == 'inlet'
        assert hv[0]['temperature'] == ('previous_thermal_or_seed' if fluid == 'sco2' else 'inlet')
    assert actual.metadata['input_resolution']['source'] == 'CaseData.parameters'
    assert actual.metadata['execution_record']['property_sampling']['version'] == 'full_sampling_v1'


def test_public_sou_strict_v3_reports_executed_final_and_outer_settings(native_path):
    cfg = _config(3, True)
    cfg = replace(cfg, solver=replace(cfg.solver, max_outer_ltne=2,
        enthalpy_algorithm='temperature_sou', ltne_enthalpy_outer=1000,
        ltne_enthalpy_nsweep=25, ltne_enthalpy_omega=.6, ltne_enthalpy_tol=1e-6,
        ltne_enthalpy_coupled_energy_tol=1e-5, ltne_enthalpy_equation_energy_tol=1e-5))
    prepared = prepare_case(cfg, case_id='sou-strict-full3d')
    actual = cpp_run(prepared, control(native_path))
    diagnostics = actual.metadata['diagnostics']
    assert actual.backend_id == 'cpp' and actual.backend_version == 'full_3d_v5'
    assert actual.metadata['thermal_mode'] == 'conservative_energy'
    assert diagnostics['native_full_3d']['entry_version'] == 5
    history = diagnostics['_ltne_info']
    assert len(history) == 2
    expected = dict(update_tol=1e-6, coupled_energy_tol=1e-5, equation_energy_tol=1e-5,
        max_iterations=1000, sweeps=25, omega=.6, energy_algorithm='temperature_sou',
        require_enthalpy_update_on_temperature=False,
        effective_settings_source='native_completed_thermal_call', driver_abi=5)
    for balance in [diagnostics['true_h_balance'], *(row['true_h_balance'] for row in history)]:
        settings = balance['effective_settings']
        assert {key: settings[key] for key in expected} == expected
        assert settings['temperature_update_tol_K'] == 1e-8
        assert balance['converged'] and balance['exit_reason'] == 'converged'
        assert np.isfinite(balance['residual']) and balance['residual'] < 1e-6
        for key in ('coupled_energy_balance', 'equation_energy_balance'):
            assert np.isfinite(balance[key]['ratio']) and balance[key]['ratio'] <= 1e-5
        assert max(balance['enthalpy_clip_counts']['total']) == 0


def test_capped_public_keeps_distinct_pressure_states(native_path):
    prepared = case('air-sco2', 2)
    actual, raw = run_observed(prepared, native_path)
    check_portable(actual, raw, prepared)
    assert not actual.run_status['converged']
    balance = actual.metadata['diagnostics']['true_h_balance']
    assert balance['post_after_last_thermal']
    assert np.max(np.abs(actual.fields['P_report_A']-actual.fields['P_thermal_A'])) > 1e-5
    for side, name in enumerate('AB'):
        assert balance['P_'+name+'_offset_Pa'] == raw.native['outer'][-1]['pressure_reference'][side]
        compare(balance['P_'+name+'_range_Pa'], raw.native['outer'][-1]['pressure_range'][side])


def test_pre_cancelled_case_skips_preparation_and_library_load(tmp_path):
    prepared = case()
    with patch('sjtu_tpmshx.cpp_interface.full_3d_stage.validate_saved_case',
               side_effect=AssertionError('cancelled case prepared for execution')), \
            patch('sjtu_tpmshx.cpp_interface.full_3d_stage.open_library',
                  side_effect=AssertionError('cancelled case loaded a library')):
        with pytest.raises(CancelledError):
            cpp_run(prepared, control(tmp_path/'missing.dll', cancel_check=lambda: True))


@pytest.mark.parametrize('during',[False,True])
def test_native_cancellation_never_returns_a_field_result(native_path,during):
    calls=[]
    def cancel():
        calls.append(1)
        return len(calls)>= (100 if during else 1)
    with pytest.raises(CancelledError):cpp_run(case(),control(native_path,cancel_check=cancel))


def tracked_release(monkeypatch):
    """Record the owner of each released saved 3D result after its release."""
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    release, released = full_3d_stage.release_result, []

    def tracked(library, result):
        assert result.owner
        release(library, result)
        released.append(result.owner)

    monkeypatch.setattr(full_3d_stage, 'release_result', tracked)
    return released


def test_interrupt_after_native_return_releases_owner(native_path, monkeypatch):
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    released = tracked_release(monkeypatch)
    require_completed = full_3d_stage.require_completed

    def interrupted(result, traces):
        require_completed(result, traces)
        raise KeyboardInterrupt('native-return')
    monkeypatch.setattr(full_3d_stage, 'require_completed', interrupted)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        cpp_run(case(cap=2), control(native_path))
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
    from sjtu_tpmshx.cpp_interface import full_2d_stage, full_3d_stage
    from tests.python.native.test_full_2d import configuration

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
    copied = replace(prepared, design_fields={**prepared.design_fields, **before})
    reference = cpp_run(copied, control(native_path))
    entered = []

    def check_buffers(pointers):
        for key, pointer in pointers.items():
            source = prepared.design_fields[key]
            same_buffer = ct.cast(pointer, ct.c_void_p).value == source.ctypes.data
            assert same_buffer == (source.dtype == np.float64)
            np.testing.assert_array_equal(np.ctypeslib.as_array(pointer, shape=(source.size,)), source.ravel())
        entered.append(True)

    table = control(native_path).native_table_directory
    if dimension == 2:
        driver = full_2d_stage.StageDriver(native_path, table_directory=table)
        monkeypatch.setattr(full_2d_stage, 'StageDriver', lambda *args, **kwargs: driver)
        library, symbol = driver.library, 'tpmshx_run_saved_case_2d_v5'
    else:
        runtime = full_3d_stage.open_library(native_path, table)
        monkeypatch.setattr(full_3d_stage, 'open_library', lambda *_: runtime)
        library, symbol = runtime[1], 'tpmshx_run_saved_case_3d_v3'
    complete = getattr(library, symbol)

    def observe_saved(*args):
        if dimension == 2:
            saved = args[0]._obj
            data = saved.prepared.contents
            check_buffers({'K_ffA_arr': saved.fluid_conductivity[0].data,
                           'K_ffB_arr': saved.fluid_conductivity[1].data,
                           'K_ss_arr': data.solid_conductivity.data, 'eps_arr': data.total_porosity.data})
        else:
            data = args[0]._obj.input.contents
            assert data.area_density.size == data.hydraulic_diameter.size == 1
            for axis, width in zip('xyz', data.widths):
                assert ct.cast(width.data, ct.c_void_p).value == prepared.grid['d'+axis].ctypes.data
            check_buffers({key: getattr(data, field).data for key, field in (
                ('eps_arr', 'epsilon'), ('eps_A', 'epsilon_a'), ('eps_B', 'epsilon_b'),
                ('K_m2', 'permeability'), ('cF_per_m', 'forchheimer'),
                ('K_ss', 'solid_conductivity'), ('L_field_m', 'cell_length'))})
        complete.argtypes = observe_saved.argtypes
        return complete(*args)

    monkeypatch.setattr(library, symbol, observe_saved)

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
def test_opt_in_audit_exports_final_capped_state_and_nu_observations(native_path, pair):
    prepared = case(pair, 2)
    prepared = replace(prepared, parameters=dict(prepared.parameters, _emit_audit=True))
    actual, stage = run_observed(prepared, native_path)
    check_portable(actual, stage, prepared)
    raw = stage.native
    diagnostics = actual.metadata['diagnostics']
    compare(diagnostics['sco2_nu_observations'], raw['nu_observations'])
    compare(diagnostics['envelope_reasons'], raw['envelope_reasons'])
    for side, name in enumerate('AB'):
        face = diagnostics['_audit_s'+name+'_face']
        for target, source in (('u','u'), ('v','v'), ('w','w'), ('rho','density'), ('eps','epsilon'),
                               ('inlet_frac','inlet_opening'), ('outlet_frac','outlet_opening')):
            np.testing.assert_array_equal(face[target], raw['flow'][side][source])
        for axis, width in zip('xyz', raw['flow'][side]['widths']):
            np.testing.assert_array_equal(face['d'+axis], width)
        assert diagnostics['_audit_m_dot_'+name+'_simple'] == raw['inlet_mass'][side]
        assert diagnostics['_audit_cp_'+name] == raw['inlet_cp'][side]
    assert diagnostics['_audit_m_dot_B_phys_in'] == raw['physical_mass_in'][1]
    assert diagnostics['_audit_m_dot_B_phys_out'] == raw['physical_mass_out'][1]


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
    actual, raw = run_observed(prepared, native_path)
    check_portable(actual, raw, prepared)
    physical_gates(actual)
    if design_mode == 'asymmetric':
        assert actual.metadata['native']['algorithm'] == 'model_h_tface_sou_sou_strict_v3'


@pytest.mark.parametrize('pair,offset', [('water-water', 0.), ('air-air', .05),
                                        ('water-air', .05), ('air-water', .05)])
def test_two_sided_integral_defaults_keep_physics_and_saved_evidence(native_path, tmp_path, pair, offset):
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    cfg = _config(3, True)
    fluids = [replace(getattr(cfg, 'fluid_'+side), type=fluid,
                      u_mps=3. if fluid == 'air' else .2,
                      T_in_K=(350. if fluid == 'water' else 500.) if side == 'A' else 300.,
                      P_in_Pa=2e5 if fluid == 'air' else 2e6)
              for side, fluid in zip('AB', pair.split('-'))]
    cfg = replace(cfg, fluid_A=fluids[0], fluid_B=fluids[1],
                  geometry=replace(cfg.geometry, delta_levelset=offset))
    prepared = prepare_case(cfg, case_id='integral-'+pair)
    actual = cpp_run(prepared, control(native_path))
    physical_gates(actual)
    record = actual.metadata['execution_record']
    assert record['numerics']['thermal_mode'] == 'model_h'
    assert record['numerics']['algorithm'] == 'model_h_tface_sou_sou_strict_v3'
    for side, fluid in zip('AB', pair.split('-')):
        selected = record['sides'][side]
        assert selected['fluid'] == fluid and selected['solved']
        assert selected['energy']['relation'] == 'integral_cp_T'
        assert selected['energy']['property_provider'] == 'model_resource'
    for call in record['numerics']['model_h_iterations']['records']:
        assert call['settings']['acceleration'] == dict(enabled=False, sweeps_per_block=5, history_limit=16)
    ledger = actual.boundary_fluxes['energy']
    assert ledger['physical_boundary_complete']
    assert all(np.isfinite(value).all() for value in ledger['residual'].values())
    save_result(actual, tmp_path/'result.h5')
    restored = load_result(tmp_path/'result.h5')
    for name in ('fields', 'field_metadata', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'metadata'):
        _exact_resume_values(getattr(restored, name), getattr(actual, name), name)


@pytest.mark.parametrize('pair',['air-air','air-water','water-air','air-sco2','sco2-water'])
def test_runtime_range_evidence_preserves_original_sources_and_denominators(native_path, pair):
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case as adapter_run
    from tests.python.native.test_cpp_full_2d_capture import check_range_records
    records, captured = {}, []
    original = full_3d_stage.stage_closures
    def observed(*args):
        rows, warnings, last = original(*args)
        captured.append((rows, last))
        return rows, warnings, last
    with warning_scope(records), patch.object(full_3d_stage, 'stage_closures', observed):
        result = adapter_run(case(pair, 2), control(native_path))
    (rows, last), = captured
    check_range_records(records, rows)
    compare(result.metadata['_last_closure_ranges'], last)
    for row in last:
        assert row['size'] == int(np.prod(row['shape']))
        for kind in ('minimum', 'maximum'):
            if row[kind] is not None:
                assert len(row[kind][1]) == len(row['shape'])
                assert all(0 <= index < size for index,size in zip(row[kind][1],row['shape']))


@pytest.mark.parametrize('converged', [False, True])
def test_public_saved_case_cli_replay_and_postprocess_without_python_kernels(
        native_path, tmp_path, converged):
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.result_io import load_result
    prepared = (prepare_case(ComputeConfig.from_json(str(ROOT/'examples/three_module/air_3d.json')),
                            case_id='full3d-cpp-replay') if converged else case('air-sco2', 2))
    case_path, result_path = tmp_path/'case.h5', tmp_path/'result.h5'
    save_case(prepared, case_path)
    code = '''
import sys
from sjtu_tpmshx.file_io.result_io import load_result
from sjtu_tpmshx.file_io.metrics_io import load_metrics
from sjtu_tpmshx.postprocess.api import evaluate, evaluate_physical_balance
from sjtu_tpmshx.applications.cli.stages import main
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
    with pytest.raises(FileNotFoundError, match='missing'):
        cpp_run(case(), selected)


@pytest.mark.parametrize('pair,route,audit', [
    ('air-air', 'model_h', False), ('air-water', 'model_h', False),
    ('water-air', 'model_h', False), ('air-sco2', 'temperature_sou', False),
    ('sco2-water', 'temperature_sou', False), ('air-air', 'model_h', True),
    ('air-sco2', 'temperature_sou', True), ('sco2-water', 'temperature_sou', True),
    ('air-air', 'temperature_cc', False), ('air-air', 'temperature_staggered', False),
])
def test_application_capture_owns_shared_aliases_and_keeps_full_evidence(
        native_path, tmp_path, pair, route, audit):
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    prepared = case(pair, 2)
    parameters = dict(prepared.parameters, max_iter_simple=1, _emit_audit=audit, ltne_enthalpy_outer=2,
                      ltne_enthalpy_nsweep=1, prepared=dict(prepared.parameters['prepared'], max_outer=1, ltne_max_iter=1))
    parameters['_environment'] = dict(parameters.get('_environment', {}), TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None)
    if route in ('temperature_cc', 'temperature_staggered'):
        parameters.update(variable_rho_cp=False, conservative_ltne=False, force_cc_ltne=route.endswith('_cc'))
    elif route in ('temperature_sou'):
        parameters['enthalpy_algorithm'] = route
    prepared = replace(prepared, parameters=parameters)
    stage = run_stage(prepared, control(native_path))
    raw, result = stage.native, stage.result
    # The application capture detaches only the arrays that the result and its audit need.
    assert 'rho_cp' not in raw and 'conductivity' not in raw and 'inlet_capacity' not in raw
    for actual in raw['flow']:
        assert 'd_u' not in actual and 'face_velocity_real' not in actual and 'local_mass' not in actual
        assert ('u' in actual) is audit
    for name, value in zip(('Ta', 'Tb', 'Ts'), stage.arrays['temperature']):
        np.testing.assert_array_equal(result.fields[name], value)
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
    from sjtu_tpmshx.cpp_interface import full_3d_stage
    released = tracked_release(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError('capture failure')

    monkeypatch.setattr(full_3d_stage, '_detach' if failure == 'detach' else 'bootstrap_traces', fail)
    prepared = saved_case('air-air', counts=(4, 4, 4), max_iter_simple=1,
                          prepared_values=dict(max_outer=1, ltne_max_iter=1))
    with pytest.raises(RuntimeError, match='capture failure'):
        cpp_run(prepared, control(native_path))
    assert released == [None]


@pytest.mark.parametrize('dimension,real_co2', [(2, False), (3, False), (2, True), (3, True)])
def test_public_applicability_keeps_original_inlet_and_last_local_sources(native_path, tmp_path, dimension, real_co2):
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.file_io.result_io import save_result, load_result
    from sjtu_tpmshx.postprocess.api import evaluate_applicability
    from sjtu_tpmshx.solvers.api import run_case
    from tests.python.native.test_full_2d import configuration
    from tests.python.native.test_cpp_full_2d_capture import check_model_range_bounds
    prepared = (prepare_case(configuration(outer=2), case_id='ranges-2d')
                if dimension == 2 else case('air-air', 2))
    if real_co2:
        from tests.python.test_co2_model import co2_config
        config = co2_config(1 if dimension == 2 else 3)
        prepared = prepare_case(replace(config, solver=replace(config.solver, max_outer_ltne=2)), case_id='co2-ranges')
    summaries = []
    for backend in ('cpp',):
        result = run_case(prepared, control(native_path))
        summary = evaluate_applicability(result)
        assert summary['missing'] == []
        assert summary['status'] in ('within_limits', 'outside_limits')
        assert '_last_closure_ranges' not in result.metadata
        for group in ('inlet', 'final'):
            for row in result.metadata['applicability_evidence'][group]:
                check_model_range_bounds(row['source'], row['bounds'])
        for side in 'AB':
            assert any(row['side'] == side and row['source'][0] == 'nu_raw'
                       and row['captured'] for row in summary['checks']['final'])
        if real_co2:
            assert any(row['source'] == ('nu_pr', 'co2', 'Gyroid')
                       for row in summary['checks']['final'])
        path = save_result(result, tmp_path / (backend + '.h5'))
        assert mutable_data(evaluate_applicability(load_result(path))) == mutable_data(summary)
        summaries.append(summary)
    assert {row['source'][1] for row in summaries[0]['checks']['inlet']
            if row['source'][0] == 'geometry'} == {'L_field_m', 't_field_m'}


@pytest.mark.parametrize('seeded', [False, True])
def test_first_thermal_sampling_distinguishes_inlet_and_seed(native_path, seeded):
    prepared = case('sco2-water', 2)
    prepared = replace(prepared, parameters=dict(prepared.parameters, T_s_init=350. if seeded else None,
                       prepared=dict(prepared.parameters['prepared'], max_outer=1)))
    native = native_run(prepared, control(native_path))
    rows = native['property_sampling']
    sample = next(row for row in rows if row['side'] == 'A' and row['stage'] == 'thermal_hv'
                  and row['quantity'] == 'conductivity')
    assert sample['outer_index'] == 0
    assert sample['temperature'] == ('previous_thermal_or_seed' if seeded else 'inlet')
    assert sample['operation'] == ('local_evaluation' if seeded else 'scalar_evaluation')
    assert any(row['stage'] == 'thermal_prepare' for row in rows)
    assert not any(row['stage'] == 'thermal_warmup' for row in rows)
    post = [row for row in rows if row['stage'] == 'flow_post']
    assert post and all(row['temperature'] == 'current_thermal_return' for row in post)


@pytest.mark.parametrize('directions', [(4, 1), (5, 0)])
@pytest.mark.parametrize('local_pressure', [False, True])
def test_outer_transport_keeps_changed_temperature_and_pressure(native_path, directions, local_pressure):
    from sjtu_tpmshx.physical_models.fluid_props import get
    stages = []
    for outer in (1, 2):
        prepared = saved_case('sco2-water', directions=directions, counts=(3, 4, 5), _emit_audit=True,
                              prepared_values=dict(max_outer=outer),
                              environment=dict(TPMSHX_SCO2_COMPRESSIBLE='1' if local_pressure else '0'))
        stages.append(run_stage(prepared, control(native_path, cpu_threads=1)))
    previous, current = stages
    cfg = prepared.parameters
    assert len(current.native['outer']) == 2 and current.native['post_after_last_thermal']
    for side, label in enumerate('AB'):
        temperature = current.arrays['temperature'][side]
        assert np.max(np.abs(temperature - previous.arrays['temperature'][side])) > 1e-5
        model = get(cfg['fluid_type_' + label])
        pressure = cfg['P_in' + label]
        old = previous.arrays['flow'][side]
        sampled_pressure = old['pressure_real'] if side == 0 and local_pressure else pressure
        density = .6 * model.rho(temperature, sampled_pressure) + .4 * old['density_real']
        np.testing.assert_allclose(current.arrays['flow'][side]['density_real'], density, rtol=2e-12, atol=1e-10)
        conductivity = np.asarray(prepared.design_fields['eps_' + label]) * model.k(temperature, pressure)
        np.testing.assert_allclose(current.native['final_conductivity'][side], conductivity, rtol=2e-12, atol=1e-12)
        capacity = (density if side == 0 else model.rho(temperature, pressure)) * model.cp(temperature, pressure)
        np.testing.assert_allclose(current.native['final_rho_cp'][side], capacity, rtol=2e-12, atol=1e-8)


@pytest.mark.parametrize('pair', ['air-air', 'water-air'])
def test_inactive_native_side_has_no_flow_or_exchange_sampling(native_path, pair):
    prepared = saved_case(pair, fluid_B_cfg=None, prepared_values=dict(max_outer=1))
    stage = run_stage(prepared, control(native_path))
    result = stage.native
    assert result['flow'][1] is None
    np.testing.assert_array_equal(stage.arrays['temperature'][1], prepared.parameters['T_inB'])
    energy = next(row for row in result['property_sampling'] if row['quantity'] == 'energy_relation')
    assert energy['temperature'] == 'inlet' and energy['operation'] == 'frozen_capacity_temperature'
    assert not [row for row in result['property_sampling']
                if row['side'] == 'B' and row['stage'] in ('thermal_hv', 'flow', 'flow_post')]


@pytest.mark.parametrize('nz,conservative,force_cc', [
    (1, False, True), (2, False, True), (2, False, False), (2, True, False)])
def test_retired_single_sco2_rejected_before_numerical_work(native_path, nz, conservative, force_cc):
    prepared = saved_case('sco2-water', counts=(3, 4, nz), directions=(0, 3),
                          conservative_ltne=conservative, force_cc_ltne=force_cc, fluid_B_cfg=None)
    entered = []
    with pytest.raises(ValueError, match='single-A sCO2 execution is retired'):
        cpp_run(prepared, control(native_path, outer_iteration=lambda *args: entered.append(args)))
    assert not entered


@pytest.mark.parametrize('pair', ['air-air', 'water-air'])
def test_public_model_h_controls_retain_native_calls_and_startup_budget(native_path, tmp_path, pair):
    from sjtu_tpmshx.file_io.case_io import load_case, save_case
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
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
    assert all(row['settings']['acceleration'] == dict(enabled=False, sweeps_per_block=25, history_limit=6)
               for row in records)
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
    prepared = saved_case('air-air', directions=(0, 3), counts=(4, 4, nz),
                          conservative_ltne=False, force_cc_ltne=True, model_h_max_iterations=17,
                          model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8,
                          prepared_values=dict(max_outer=2))
    raw = native_run(prepared, control(native_path))
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


# Each pair and each cut occurs once. The pairs do not change the cut logic.
@pytest.mark.parametrize('pair, cut', [('air-air', 0), ('water-air', 1), ('sco2-water', 3)])
def test_native_checkpoint_hdf5_round_trip(native_path, tmp_path, pair, cut):
    from sjtu_tpmshx.data_types.solver_checkpoint import SolverCheckpoint
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.solver_checkpoint_io import (
        save_solver_checkpoint, load_solver_checkpoint, load_checkpoint_case)
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    prepared_case = case(pair, cap=3)
    case_path = save_case(prepared_case, tmp_path/'case.h5')
    saved_path = tmp_path/'checkpoint.h5'
    expected = run_case(prepared_case, control(native_path))
    def save_at_boundary(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == cut:
            saved = SolverCheckpoint(str(case_path), prepared_case.case_id, prepared_case.model_refs, state)
            save_solver_checkpoint(saved, saved_path)
            state['state.temperature.0'][0] = -1.
            assert saved.native_state['state.temperature.0'][0] > 0.
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared_case, control(native_path), checkpoint=save_at_boundary)
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state['control.simple.gas_constant'][0] == R_AIR_DEFAULT
    actual = run_case(load_checkpoint_case(saved), control(native_path), resume_state=saved.native_state)
    for key in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        _exact_resume_values(getattr(actual, key), getattr(expected, key), key)
    assert actual.metadata['continuation']['completed_outer_steps'] == cut
    _exact_resume_values({k: v for k, v in actual.metadata.items() if k != 'continuation'}, expected.metadata)


@pytest.mark.parametrize('damage', ['build', 'format', 'input', 'control', 'type', 'size', 'unknown', 'missing',
                                     'thermal', 'geometry', 'phase', 'nonfinite',
                                     'premature_finish', 'different_exit', 'thermal_mode'])
def test_native_checkpoint_rejects_damaged_fields(native_path, damage):
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    prepared = case(cap=3)
    saved = {}
    def pause(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == (0 if damage == 'premature_finish' else 1):
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared, control(native_path), checkpoint=pause)
    if damage == 'build':
        saved['build'] = 'another-build'
    elif damage == 'format':
        saved['format'][0] += 1
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
    elif damage == 'thermal_mode':
        saved['state.result.thermal.mode'][0] = 2
    elif damage == 'nonfinite':
        saved['state.temperature.0'][0] = np.nan
    else:
        del saved['state.temperature.0']
    with pytest.raises((ValueError, TypeError), match='state|continuation'):
        run_case(prepared, control(native_path), resume_state=saved)


_CHECKPOINT_CHILD = r'''
import os
from pathlib import Path
import sys
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.data_types.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.file_io.case_io import load_case
from sjtu_tpmshx.file_io.result_io import save_result
from sjtu_tpmshx.file_io.solver_checkpoint_io import (
    load_solver_checkpoint, save_solver_checkpoint, load_checkpoint_case)
from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
mode, case_path, saved_path, result_path, library, tables = sys.argv[1:]
control = RunControl(backend='cpp', native_library=library, native_table_directory=tables)
if mode == 'interrupt':
    case = load_case(case_path)
    def stop(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == 1:
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
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.result_io import load_result
    from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
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
    from sjtu_tpmshx.data_types.solver_checkpoint import SolverCheckpoint
    from sjtu_tpmshx.file_io import hdf5_data
    from sjtu_tpmshx.file_io.solver_checkpoint_io import save_solver_checkpoint, load_solver_checkpoint
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
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
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint
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
from sjtu_tpmshx.file_io import hdf5_data
from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint, save_solver_checkpoint
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


# Each energy route and each cut occurs once.
@pytest.mark.parametrize('route, cut', [
    ('temperature_sou', 1), ('single_cc', 0), ('single_staggered', 'final'),
    ('conservative_staggered', 1), ('nz1_cc', 'final')])
def test_checkpoint_covers_energy_routes(native_path, route, cut):
    pair = 'sco2-water' if route.startswith('temperature') else 'air-air'
    options = {}
    if route.startswith('single'):
        options = dict(fluid_B_cfg=None, conservative_ltne=False, force_cc_ltne=route.endswith('_cc'))
    elif route in ('conservative_staggered', 'nz1_cc'):
        options = dict(variable_rho_cp=False, conservative_ltne=route == 'conservative_staggered',
                       force_cc_ltne=route == 'nz1_cc')
    else:
        options['enthalpy_algorithm'] = route
    prepared = saved_case(pair, counts=(4, 4, 1) if route == 'nz1_cc' else None,
                          directions=(0, 3) if route == 'nz1_cc' else None,
                          prepared_values=dict(max_outer=3), **options)
    expected = native_run(prepared, control(native_path))
    if cut == 'final':
        cut = len(expected['outer'])
    saved = {}
    def pause(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == cut:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    actual = native_run(prepared, control(native_path), resume_state=saved)
    assert actual.pop('continuation')['completed_outer_steps'] == cut
    _exact_resume_values(actual, expected)


def test_checkpoint_cancel_keeps_last_complete_boundary(native_path):
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    prepared_case = case(cap=3)
    saved = []
    cancel = False
    def checkpoint(state):
        nonlocal cancel
        if int(state['state.phase'][0]) not in (1, 2):
            return
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
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    original = OSError('checkpoint storage is unavailable')
    def failed_write(_):
        raise original
    with pytest.raises(OSError) as caught:
        run_case(case(cap=3), control(native_path), checkpoint=failed_write)
    assert caught.value is original


def test_full_checkpoint_keeps_active_pressure_hierarchies(native_path):
    prepared = saved_case('air-air', counts=(14, 14, 14), max_iter_simple=3,
                          prepared_values=dict(max_outer=2, ltne_max_iter=10))
    expected = native_run(prepared, control(native_path))
    saved = {}
    def pause(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == 1:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    for side in (0, 1):
        assert saved[f'state.simple.{side}.value.pressure.construction.present'][0] == 1
    actual = native_run(prepared, control(native_path), resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)


@pytest.mark.parametrize('name,value', [('model_h_max_iterations', 18),
    ('model_h_temperature_tol_K', 1e-4), ('model_h_q_relative_tol', 1e-7)])
def test_checkpoint_rejects_changed_model_h_controls_before_flow(native_path, name, value):
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    controls = dict(model_h_max_iterations=17, model_h_temperature_tol_K=1e-5, model_h_q_relative_tol=1e-8)
    prepared = case('water-air', cap=3)
    prepared = replace(prepared, parameters=dict(prepared.parameters, **controls))
    saved = {}
    def pause(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == 1:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared, control(native_path), checkpoint=pause)
    assert saved['control.model_h_iterations.max_iterations'][0] == 17
    assert saved['state.result.outer.0.model_h_iterations.0.total_iteration_budget'][0] == 17
    changed = replace(prepared, parameters=dict(prepared.parameters, **{name: value}))
    progress = []
    with pytest.raises(ValueError, match='model_h_iterations'):
        run_case(changed, control(native_path, residual=lambda *args: progress.append(args)), resume_state=saved)
    assert not progress


@pytest.mark.parametrize('relaxation', [None, .35])
def test_prepared_velocity_relaxation_is_executed_and_saved(native_path, tmp_path, relaxation):
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.file_io.result_io import load_result, save_result
    prepared = case(cap=2)
    parameters = mutable_data(prepared.parameters)
    parameters['simple_velocity_relaxation'] = relaxation
    snapshot = mutable_data(prepared.config_snapshot)
    snapshot['solver']['simple_velocity_relaxation'] = .9
    prepared = replace(prepared, parameters=parameters, config_snapshot=snapshot)
    actual = cpp_run(prepared, control(native_path))
    expected = .5 if relaxation is None else relaxation
    assert actual.metadata['simple_velocity_relaxation'] == expected
    assert actual.metadata['execution_record']['numerics']['simple_velocity_relaxation'] == expected
    path = tmp_path / 'result.h5'
    save_result(actual, path)
    assert load_result(path).metadata['execution_record'] == actual.metadata['execution_record']


def test_checkpoint_rejects_changed_velocity_relaxation(native_path):
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    prepared = case(cap=3)
    prepared = replace(prepared, parameters=dict(prepared.parameters, simple_velocity_relaxation=.35))
    saved = {}
    def pause(state):
        if int(state['state.phase'][0]) in (1, 2) and int(state['state.result.outer.size'][0]) == 1:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        run_case(prepared, control(native_path), checkpoint=pause)
    changed = replace(prepared, parameters=dict(prepared.parameters, simple_velocity_relaxation=.4))
    entered = []
    with pytest.raises(ValueError, match='state|continuation'):
        run_case(changed, control(native_path, outer_iteration=lambda *args: entered.append(args)),
                 resume_state=saved)
    assert not entered


def _inner_prepared(route):
    """Return the saved case of one inner-checkpoint thermal route."""
    eos = route in ('true_h', 'true_h_cc', 'temperature_sou')
    pair = 'sco2-water' if eos else 'water-water' if route == 'strict_water' else 'air-air'
    options = dict(max_iter_simple=40)
    counts = (3, 4, 1) if route == 'nz1_cc' else (3, 4, 2)
    if route in ('model_h_accelerated', 'strict_water'):
        options['port_wall_refine'] = True
    elif route in ('temperature_cc', 'nz1_cc'):
        options.update(variable_rho_cp=False, conservative_ltne=False, force_cc_ltne=True)
    elif route in ('staggered', 'staggered_conservative', 'staggered_rb'):
        options.update(variable_rho_cp=False, conservative_ltne=route != 'staggered', force_cc_ltne=False)
        if route == 'staggered_rb':
            # The native stage selects red-black energy above 30000 cells.
            counts = (32, 32, 30)
    elif route.startswith('single'):
        options.update(fluid_B_cfg=None, conservative_ltne=False, force_cc_ltne=True)
    if eos:
        options.update(ltne_enthalpy_outer=12, ltne_enthalpy_nsweep=3)
    if route.startswith('temperature_') and eos:
        options['enthalpy_algorithm'] = route
    if route == 'true_h_cc':
        options['conservative_ltne'] = False
    return saved_case(pair, counts=counts, directions=(0, 3) if route == 'nz1_cc' else None,
                      prepared_values=dict(max_outer=2, ltne_max_iter=800), **options)


def _inner_position(state):
    prefix = 'state.thermal.value.'
    for owner in ('model_h_2d', 'model_h_3d', 'staggered', 'enthalpy'):
        if state[prefix+owner+'.present'][0]:
            path = prefix+owner+'.value.'
            result = path+('iteration.' if owner == 'staggered' else '')+'result.'
            position = int(state[result+'iterations'][0])
            if owner.startswith('model_h') and state[path+'iteration.chunk.present'][0]:
                position += int(state[path+'iteration.chunk.value.completed'][0])
            return owner, position
    raise AssertionError('active thermal state has no owner')


# Each route occurs once. The model-h, staggered and enthalpy owners each pause before and after an update.
@pytest.mark.parametrize('route, after_update', [
    ('model_h', False), ('model_h_accelerated', True), ('strict_water', True),
    ('temperature_cc', False), ('nz1_cc', True), ('single_cc', False),
    ('staggered', False), ('staggered_conservative', True), ('staggered_rb', False),
    ('true_h', False), ('true_h_cc', True), ('temperature_sou', False)])
def test_inner_thermal_checkpoint_keeps_complete_result(native_path, route, after_update):
    prepared = _inner_prepared(route)
    expected = native_run(prepared, control(native_path))
    saved = {}
    def pause(state):
        if state['state.phase'][0] != 8:
            return
        owner, position = _inner_position(state)
        if route in ('true_h', 'true_h_cc', 'temperature_sou') and owner != 'enthalpy':
            return
        if bool(position) != after_update:
            return
        saved.update(state)
        raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    assert saved['format'][0] == 2
    owner, position = _inner_position(saved)
    assert bool(position) == after_update
    actual = native_run(prepared, control(native_path), resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)


# The native stage never selects red-black energy for true h; test_full_3d checks that kernel option.
@pytest.mark.parametrize('nz,conservative', [(1, False), (2, False), (2, True)])
@pytest.mark.parametrize('cut_outer', [0, 1])
def test_true_h_preparation_hands_unchanged_fields_to_eos_checkpoint(native_path, nz, conservative, cut_outer):
    prepared = saved_case('sco2-water', counts=(3, 4, nz), directions=(0, 3),
                          max_iter_simple=40, conservative_ltne=conservative, force_cc_ltne=True,
                          ltne_enthalpy_outer=12, ltne_enthalpy_nsweep=3,
                          prepared_values=dict(max_outer=2, ltne_max_iter=800))
    expected = native_run(prepared, control(native_path))
    saved = {}
    def pause(state):
        if state['state.phase'][0] != 8:
            return
        assert _inner_position(state)[0] == 'enthalpy'
        if (state['state.thermal.value.record.outer_index'][0] == cut_outer
                and _inner_position(state)[1] == 0):
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    assert saved['state.thermal.value.budget'][0] == 0
    for field in range(3):
        np.testing.assert_array_equal(saved[f'state.temperature.{field}'],
                                      saved[f'state.thermal.value.initial.{field}'])
    evidence = 'state.thermal.value.evidence.'
    assert bool(saved[evidence+'staggered.present'][0]) == (nz > 1 and conservative)
    if nz > 1 and conservative:
        assert saved[evidence+'staggered.value.iteration.iterations'][0] == 0
    for side in range(2):
        for axis in range(3):
            mass = saved[evidence+f'mass.{side}.{axis}']
            assert mass.size and np.isfinite(mass).all()
    actual = native_run(prepared, control(native_path), resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)
    saved['state.thermal.value.budget'][0] = 2
    with pytest.raises(ValueError, match='continuation thermal budget'):
        native_run(prepared, control(native_path), resume_state=saved)


# Each flow phase and each iteration occurs once.
@pytest.mark.parametrize('phase, iteration', [(6, 0), (7, 1), (9, 7), (10, 1)])
def test_inner_flow_checkpoint_keeps_complete_result(native_path, phase, iteration):
    prepared = _inner_prepared('model_h_accelerated')
    expected = native_run(prepared, control(native_path))
    saved = {}
    def pause(state):
        if state['state.phase'][0] == phase and state['state.flow_iteration.value.iterations'][0] == iteration:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    actual = native_run(prepared, control(native_path), resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)


@pytest.mark.parametrize('damage', ['flow_budget', 'flow_monitor', 'flow_previous', 'flow_field',
                                    'thermal_budget', 'remaining_budget', 'owner', 'initial',
                                    'shared_field', 'iteration', 'thermal_input', 'record_budget', 'initial_value',
                                    'acceleration', 'acceleration_sweeps', 'acceleration_history', 'sweep_block'])
def test_inner_checkpoint_rejects_damaged_iteration(native_path, damage):
    prepared = _inner_prepared('model_h_accelerated')
    saved = {}
    def pause(state):
        if damage.startswith('flow'):
            selected = state['state.phase'][0] == 6 and state['state.flow_iteration.value.iterations'][0] == 2
        else:
            selected = state['state.phase'][0] == 8 and _inner_position(state)[1] > 0
        if selected:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    if damage == 'flow_budget':
        saved['state.flow_iteration.value.iterations'][0] = 40
    elif damage == 'flow_monitor':
        saved['state.flow_convergence.value.streak'][0] = 100
    elif damage == 'flow_previous':
        saved['state.flow_convergence.value.previous.0'] = np.empty(0)
    elif damage == 'flow_field':
        saved['state.result.flow.0.density'][0] = np.nan
    elif damage == 'thermal_budget':
        saved['state.thermal.value.budget'][0] += 1
    elif damage == 'remaining_budget':
        saved['state.thermal.value.remaining'][0] -= 1
    elif damage == 'owner':
        saved['state.thermal.value.model_h_3d.present'][0] = 0
    elif damage == 'initial':
        saved['state.thermal.value.initial.0'][0] = np.nan
    elif damage == 'initial_value':
        saved['state.thermal.value.initial.0'][0] += 1.
    elif damage == 'record_budget':
        saved['state.thermal.value.record.model_h_iterations.0.max_iterations'][0] += 1
    elif damage in ('acceleration', 'acceleration_sweeps', 'acceleration_history'):
        field = 'accelerate' if damage == 'acceleration' else damage
        saved['state.thermal.value.record.model_h_iterations.0.'+field][0] = 0
    elif damage == 'sweep_block':
        saved['state.thermal.value.model_h_3d.value.iteration.chunk.value.sweep_block'][0] = 5
    elif damage == 'shared_field':
        saved['state.thermal.value.model_h_3d.value.iteration.temperature.0'] = saved['state.temperature.0'].copy()
    elif damage == 'iteration':
        saved['state.thermal.value.model_h_3d.value.iteration.chunk.value.completed'][0] = 99999
    else:
        saved['state.thermal.value.evidence.hv.0'][0] += 1.
    with pytest.raises(ValueError, match='state|continuation|SIMPLE|model-h|chunk|monitor'):
        native_run(prepared, control(native_path), resume_state=saved)


@pytest.mark.parametrize('phase', [6, 8, 9])
def test_inner_cancel_retains_previous_boundary(native_path, phase):
    prepared = _inner_prepared('model_h')
    saved = []
    cancel = False
    def checkpoint(state):
        nonlocal cancel
        saved.append(state)
        cancel = state['state.phase'][0] == phase and (
            _inner_position(state)[1] > 0 if phase == 8 else state['state.flow_iteration.value.iterations'][0] >= 2)
    with pytest.raises(CancelledError):
        native_run(prepared, control(native_path, cancel_check=lambda: cancel), checkpoint=checkpoint)
    assert saved[-1]['state.phase'][0] == phase
    actual = native_run(prepared, control(native_path), resume_state=saved[-1])
    actual.pop('continuation')
    _exact_resume_values(actual, native_run(prepared, control(native_path)))


_INNER_CHECKPOINT_CHILD = r'''
import os
from pathlib import Path
import sys
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.data_types.solver_checkpoint import SolverCheckpoint
from sjtu_tpmshx.file_io.case_io import load_case
from sjtu_tpmshx.file_io.result_io import save_result
from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint, save_solver_checkpoint, load_checkpoint_case
from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
from tests.python.native.test_cpp_full_3d import _inner_position
mode, case_path, saved_path, result_path, library, tables, target = sys.argv[1:]
control = RunControl(backend='cpp', native_library=library, native_table_directory=tables)
if mode == 'interrupt':
    case = load_case(case_path)
    def stop(state):
        phase = int(state['state.phase'][0])
        selected = (target.isdigit() and phase == int(target)
                    and state['state.flow_iteration.value.iterations'][0] == 3)
        if phase == 8 and target in ('model_h_3d', 'enthalpy'):
            owner, position = _inner_position(state)
            selected = owner == target and position > 0
        if selected:
            save_solver_checkpoint(SolverCheckpoint(case_path, case.case_id, case.model_refs, state), saved_path)
            os._exit(23)
    run_case(case, control, checkpoint=stop)
    raise RuntimeError('inner checkpoint was not reached')
saved = load_solver_checkpoint(saved_path)
result = run_case(load_checkpoint_case(saved), control, resume_state=saved.native_state)
save_result(result, result_path)
'''


@pytest.mark.parametrize('target,algorithm', [('6', 'temperature_sou'), ('7', 'temperature_sou'),
    ('9', 'temperature_sou'), ('10', 'temperature_sou'), ('model_h_3d', 'temperature_sou'),
    ('strict_water', 'temperature_sou'),
    ('enthalpy', 'temperature_sou')])
def test_inner_checkpoint_continues_after_process_exit(native_path, tmp_path, target, algorithm):
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.result_io import load_result
    from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint
    from sjtu_tpmshx.cpp_interface.full_3d_stage import run_case
    pair = 'sco2-water' if target == 'enthalpy' else 'water-water' if target == 'strict_water' else 'air-air'
    prepared_case = case(pair, cap=2)
    parameters = dict(prepared_case.parameters, max_iter_simple=40, ltne_max_iter=800,
                      ltne_enthalpy_outer=12, ltne_enthalpy_nsweep=3, enthalpy_algorithm=algorithm)
    if target == 'strict_water':
        parameters['port_wall_refine'] = True
        target = 'model_h_3d'
    prepared_case = replace(prepared_case, parameters=parameters)
    case_path = save_case(prepared_case, tmp_path/'case.h5')
    saved_path, result_path = tmp_path/'inner.h5', tmp_path/'result.h5'
    args = [str(case_path), str(saved_path), str(result_path), str(native_path),
            control(native_path).native_table_directory, target]
    stopped = subprocess.run([sys.executable, '-c', _INNER_CHECKPOINT_CHILD, 'interrupt', *args],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    assert not result_path.exists()
    saved = load_solver_checkpoint(saved_path)
    assert saved.native_state['state.phase'][0] in (6, 7, 8, 9, 10)
    finished = subprocess.run([sys.executable, '-c', _INNER_CHECKPOINT_CHILD, 'resume', *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual, expected = load_result(result_path), run_case(prepared_case, control(native_path))
    for key in ('grid', 'fields', 'boundary_fluxes', 'pressure_evidence', 'run_status', 'field_metadata'):
        _exact_resume_values(getattr(actual, key), getattr(expected, key), key)
    _exact_resume_values({k: v for k, v in actual.metadata.items() if k != 'continuation'}, expected.metadata)
    actual_metrics, expected_metrics = evaluate(actual), evaluate(expected)
    for key, metric in expected_metrics.metrics.items():
        assert actual_metrics.metrics[key].status == metric.status
        _exact_resume_values(actual_metrics.metrics[key].value, metric.value, key)


@pytest.mark.parametrize('rejected', [1, 3, 7])
def test_inner_checkpoint_retains_water_startup_retry_budget(native_path, rejected):
    # A physical source forces the unchanged water gate to shorten startup.
    prepared = saved_case('water-air', counts=(3, 4, 2), max_iter_simple=40,
                          mms_S_A_field=np.full((3, 4, 2), 1e9), prepared_values=dict(max_outer=1, ltne_max_iter=800))
    expected = native_run(prepared, control(native_path))
    startup = expected['outer'][0]['coupling_startup']
    assert [row['iterations'] for row in startup['rejected_attempts']] == [250, 125, 62, 31, 15, 7, 3]
    assert startup['total_iterations'] == 494
    saved = {}
    def pause(state):
        if state['state.phase'][0] == 8 and len(state['state.thermal.value.record.rejected_startup_iterations']) == rejected:
            saved.update(state)
            raise _PauseCheckpoint
    with pytest.raises(_PauseCheckpoint):
        native_run(prepared, control(native_path), checkpoint=pause)
    charged = sum(saved['state.thermal.value.record.rejected_startup_iterations'])
    assert saved['state.thermal.value.remaining'][0] == 800-charged
    assert _inner_position(saved)[1] == 0
    actual = native_run(prepared, control(native_path), resume_state=saved)
    actual.pop('continuation')
    _exact_resume_values(actual, expected)




@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('side', ['A', 'B'])
def test_co2_pt_state_continues_after_process_exit(native_path, tmp_path, dimension, side):
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.file_io.result_io import load_result
    from sjtu_tpmshx.file_io.solver_checkpoint_io import load_solver_checkpoint
    from sjtu_tpmshx.cpp_interface import full_2d_stage, full_3d_stage
    from tests.python.native import test_cpp_full_2d_run as planar
    from tests.python.test_co2_model import co2_config

    config = co2_config(1 if dimension == 2 else 2, side=side)
    config = replace(config, solver=replace(config.solver, Nx=4, Ny=3,
        max_outer_ltne=2, max_iter_simple=40, ltne_enthalpy_outer=12,
        ltne_enthalpy_nsweep=3))
    prepared = prepare_case(config, case_id='co2-pt-resume')
    case_path = save_case(prepared, tmp_path / 'case.h5')
    saved_path, result_path = tmp_path / 'state.h5', tmp_path / 'result.h5'
    arguments = [str(case_path), str(saved_path), str(result_path), str(native_path),
                 control(native_path).native_table_directory]
    if dimension == 2:
        script, arguments = planar.INNER_CHILD, ['7', *arguments]
        run = full_2d_stage.run_case
    else:
        script, arguments = _INNER_CHECKPOINT_CHILD, [*arguments, 'enthalpy']
        run = full_3d_stage.run_case
    stopped = subprocess.run([sys.executable, '-c', script, 'interrupt', *arguments],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert stopped.returncode == 23, stopped.stderr
    saved = load_solver_checkpoint(saved_path)
    used = saved.native_state['state.thermal.value.enthalpy.value.result.used_bicubic']
    assert not used.any()
    assert saved.native_state['state.thermal.value.enthalpy.value.result.algorithm'][0] == 2
    finished = subprocess.run([sys.executable, '-c', script, 'resume', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert finished.returncode == 0, finished.stderr
    actual, expected = load_result(result_path), run(prepared, control(native_path))
    planar.compare_result(actual, expected)
    assert 'enthalpy_eos' not in actual.metadata['model_metadata']
    assert actual.metadata['thermal_mode'] == 'conservative_energy'
    actual_metrics, expected_metrics = evaluate(actual), evaluate(expected)
    for name, metric in expected_metrics.metrics.items():
        assert actual_metrics.metrics[name].status == metric.status
        _exact_resume_values(actual_metrics.metrics[name].value, metric.value, name)
