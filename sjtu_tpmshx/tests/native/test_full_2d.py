"""Prepared-case full2D coarse driver against the original production outer.

The Python oracle performs real prepare_case -> build_execution_inputs ->
_run_solvers. Its unchanged outer skeleton/thermal/SIMPLE calls execute; the
state is copied when the real outer loop returns and Richardson is stopped
at its entry. This qualifies coarse coupling, not completed 2D Richardson.

Frozen before comparison: T rtol=2e-9/atol=2e-7 K; P rtol=2e-8/atol=2e-5 Pa;
velocity/density rtol=2e-8/atol=2e-10. Stop, iterations and gates are exact.
Other frozen input/coefficient/diagnostic fields use rtol=2e-8 and a scale-
appropriate 2e-10 absolute tolerance; Q and dimensional thermal audit fields
use rtol=2e-8/atol=2e-7 W/m. Original physical gates are unchanged.
"""
from copy import deepcopy
import ctypes as ct
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.models.grid import _port_overlap_1d
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers import ltne_energy, simple_solver
from sjtu_tpmshx.solvers._solve_common import inlet_pressure_state
from sjtu_tpmshx.solvers.backends.python.two_d import coupling, execution, runtime
from sjtu_tpmshx.tests.native.test_simple_2d_c_api import arguments as simple_arguments

ROOT = Path(__file__).resolve().parents[3]
D = ct.POINTER(ct.c_double)
S = ct.c_size_t


class CoarseCaptured(Exception):
    """Stop before any Richardson work, after original final envelope gates."""


def configuration(*, directions=(0, 3), outer=4, partial=True, warm=False,
                  mode='model_h', simple_max=3000, pressure_shooting=True):
    lengths = (.06, .03)

    def port(direction, clipped):
        width = lengths[1 if direction < 2 else 0]
        center, opening = (width * .476, width * .457) if clipped else (width/2, width)
        return PartialBCConfig(dir=direction, in_ctr=center, in_w=opening,
                               out_ctr=center, out_w=opening)

    fluids = ('water', 'sco2') if mode == 'true_h' else ('air', 'water')
    pressure = 8e6 if mode == 'true_h' else 2e5
    return ComputeConfig(
        fluid_A=FluidConfig(type=fluids[0], u_mps=.05 if mode == 'true_h' else 3., T_in_K=350., P_in_Pa=pressure),
        fluid_B=FluidConfig(type=fluids[1], u_mps=.015 if mode == 'true_h' else .2,
                            T_in_K=320. if mode == 'true_h' else 300., P_in_Pa=pressure),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6, k_s_W_mK=16.,
            L_dom_m=lengths[0], H_dom_m=lengths[1], delta_levelset=.1 if mode == 'temperature' else 0.),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=outer, max_iter_simple=simple_max,
                            T_s_init_K=327. if warm else None),
        bc_A=port(directions[0], partial), bc_B=port(directions[1], False),
        extrap=ExtrapPolicy(allow=True))


def capture_python(case, *, pressure_shooting=True, full=False):
    """Observe original calls and closure-owned state; never replace numerics."""
    cfg, prepared = execution.build_execution_inputs(case)
    cfg['p_in_shooting'] = pressure_shooting
    record = dict(cfg=cfg, prepared=prepared, thermal_calls=[], simple_calls=[], outer_history=[], envelope={})
    original_outer, original_energy, original_simple = coupling.run_outer_coupling, coupling.solve_full_domain, simple_solver.SIMPLESolver.solve

    @wraps(original_simple)
    def flow(solver, *args, **kwargs):
        bound = inspect.signature(original_simple).bind(solver, *args, **kwargs)
        bound.apply_defaults()
        result = original_simple(solver, *args, **kwargs)
        record['simple_calls'].append((deepcopy(solver), result, bound.arguments))
        return result

    @wraps(original_energy)
    def energy(*args, **kwargs):
        bound = inspect.signature(original_energy).bind(*args, **kwargs)
        bound.apply_defaults()
        values = deepcopy(bound.arguments)
        result = original_energy(*args, **kwargs)
        record['thermal_calls'].append((values, deepcopy(result[3])))
        return result

    def outer(*, max_iter, step, post):
        state = inspect.getclosurevars(post).nonlocals['state']
        previous = None

        def observed_step(index):
            nonlocal previous
            result = step(index)
            fields = [state.Ta, state.Tb, state.Ts]
            deltas = ([np.inf] * 3 if previous is None else
                      [float(np.max(np.abs(x-p))) for x, p in zip(fields, previous)])
            previous = [x.copy() for x in fields]
            record['outer_history'].append(dict(iteration=index, thermal_iterations=state.e_info['iterations'],
                thermal_converged=state.e_info['converged'], outer_converged=result[0],
                relative_density_change=[state.drho_A, state.drho_B], temperature_change=deltas))
            return result

        result = original_outer(max_iter=max_iter, step=observed_step, post=post)
        record.update(state=deepcopy(state), outer_return=result,
                      coarse_thermal_calls=list(record['thermal_calls']))
        return result

    original_gate = coupling.gate_solution

    @wraps(original_gate)
    def gate(*args, **kwargs):
        result = original_gate(*args, **kwargs)
        record['envelope'][kwargs['dims']] = result
        return result

    original_refinement = coupling._compute_Q_richardson

    def refinement(*args, **kwargs):
        if not full:
            raise CoarseCaptured
        evidence = kwargs.setdefault('evidence', {})
        bound = inspect.signature(original_refinement).bind(*args, **kwargs)
        bound.apply_defaults()
        record['refinement_inputs'] = deepcopy(bound.arguments)
        result = original_refinement(*args, **kwargs)
        record['refinement_result'] = deepcopy(result)
        record['refinement_evidence'] = deepcopy(evidence)
        return result

    from sjtu_tpmshx.solvers import ltne_enthalpy_2d
    original_h = ltne_enthalpy_2d.solve_enthalpy_2d

    @wraps(original_h)
    def enthalpy(*args, **kwargs):
        bound = inspect.signature(original_h).bind(*args, **kwargs)
        bound.apply_defaults()
        values = deepcopy(bound.arguments)
        result = original_h(*args, **kwargs)
        record['thermal_calls'].append((values, deepcopy(result[3])))
        return result

    rt = runtime.build_runtime(cfg, prepared)
    with patch.object(coupling, 'run_outer_coupling', outer), patch.object(coupling, 'solve_full_domain', energy), \
         patch.object(coupling, '_compute_Q_richardson', refinement), patch.object(coupling, 'gate_solution', gate), \
         patch.object(simple_solver.SIMPLESolver, 'solve', flow), patch.object(ltne_enthalpy_2d, 'solve_enthalpy_2d', enthalpy):
        try:
            record['raw_return'] = coupling._run_solvers(cfg, rt, RunControl())
        except CoarseCaptured:
            record['refinement_stopped'] = True
    assert 'state' in record and len(record['coarse_thermal_calls']) == len(record['outer_history'])
    return record


def inputs(record):
    cfg, prepared, state = record['cfg'], record['prepared'], record['state']
    shape = (len(prepared['energy_dx']), len(prepared['energy_dy']))

    def cell(value):
        return np.ascontiguousarray(np.broadcast_to(np.asarray(value, dtype=np.float64), shape))

    geometry = cfg['thermal_geometry']['fields'] or cfg['thermal_geometry']['uniform']
    z = cfg['za']
    properties = cfg['static_properties']
    arrays = [prepared['energy_dx'], prepared['energy_dy'], np.ones(1),
        cell(properties['A']['K_ff'] if z is None else z['K_ffA_arr']),
        cell(properties['B']['K_ff'] if z is None else z['K_ffB_arr']),
        cell(properties['geometry']['K_ss'] if z is None else z['K_ss_arr']),
        cell(cfg['eps'] if z is None else z['eps_arr']), cell(geometry['A_0']), cell(geometry['D_h']),
        cell(cfg['Lcell'] * 1e-3 if z is None else z['L_field'] * 1e-3)]
    mode = ('true_h' if 'sco2' in (cfg['fluid_A'], cfg['fluid_B']) and cfg['zone_config'] is None else
            'model_h' if cfg['compute_cfg'].geometry.delta_levelset == 0 and
            (cfg['zone_config'] is None or cfg['z_axis'] == 'continuous') else 'temperature')
    multiplier = 1.
    if mode == 'true_h' and cfg['compute_cfg'].sco2_nu.mode != 'cfd_smooth':
        multiplier = getattr(cfg['compute_cfg'].sco2_nu, 'alpha_G' if cfg['tpms_type'] == 'Gyroid' else 'alpha_D')
    scalars = [cfg['Lcell'] * 1e-3, cfg['eps'], cfg['thermal_geometry']['split_A'], multiplier,
               cfg.get('T_s_init') or 0.]
    for side in ('A', 'B'):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg'+side]
        arrays.extend([flow['K_m2'], flow['cF_per_m'], flow.get('K_field_m2', np.empty(0)),
            flow.get('cF_field_per_m', np.empty(0)), opening['in_geom_frac'], opening['out_geom_frac'],
            opening['in_profile_frac'], opening['out_profile_frac'],
            _port_overlap_1d(flow['dx'], port['out_ctr']-port['out_w']/2,
                             port['out_ctr']+port['out_w']/2, staggered=True)])
        physical = getattr(cfg['compute_cfg'], 'fluid_'+side)
        side_geometry = (cfg['thermal_geometry']['side_geometry'] or {}).get(side, (0., 0., 0., 0.))
        scalars.extend([cfg['T_in'+side], physical.P_in_Pa, cfg['u_'+side], properties[side]['mu'],
            flow['seed_K_m2'], flow['seed_cF_per_m'], port['in_ctr']-port['in_w']/2, port['in_ctr']+port['in_w']/2,
            port['out_ctr']-port['out_w']/2, port['out_ctr']+port['out_w']/2, *side_geometry])
    simple = simple_arguments(state.simpA)['settings']
    f2 = simple['f2']
    thermal = record['thermal_calls'][0][0]
    has_water = 'water' in (cfg['fluid_A'], cfg['fluid_B'])
    thermal_tolerance = .1 if mode == 'true_h' else 1. if has_water else .5
    flags = [int(cfg['tpms_type'] == 'Gyroid'), ('temperature', 'model_h', 'true_h').index(mode),
        ('air', 'water', 'sco2').index(cfg['fluid_A']), ('air', 'water', 'sco2').index(cfg['fluid_B']),
        cfg['dir_A'], cfg['dir_B'], int(cfg['compute_cfg'].geometry.delta_levelset != 0), int(cfg.get('T_s_init') is not None),
        int(cfg['cfgA'].get('uniform_inlet_2d', False)), int(cfg['cfgB'].get('uniform_inlet_2d', False)),
        int(cfg['p_in_shooting']), int(ltne_energy._RB_ENERGY_2D and np.prod(shape) > ltne_energy._RB_ENERGY_2D_GATE),
        int(getattr(state.simpA, 'massflux_inlet', True)), 1, cfg['compute_cfg'].solver.max_iter_simple or 10000,
        2, cfg['compute_cfg'].solver.max_outer_ltne or 10, thermal['max_iter'],
        (thermal.get('conv_chunk') or 500) if mode != 'true_h' else 3,
        f2['confirmations'], f2['momentum_interval'], f2['stall_window'], 0, int(z is not None)]
    scalars.extend([.7, .3, state.simpA.alpha_rho, state.simpA.R_gas, state.simpA.cf_aniso,
        f2['momentum_tolerance'], f2['local_mass_tolerance'], f2['global_mass_tolerance'], f2['backflow_maximum'],
        f2['velocity_check_tolerance'], f2['stall_ratio'], cfg['compute_cfg'].solver.outer_tol_K or 1., .01, .7,
        min(thermal_tolerance * 2e-3, 1e-3), max(thermal_tolerance, 1e-8) / 100.])
    arrays.append(cell(geometry['D_h']*1000. / (cfg['Lcell'] if z is None else z['L_field'])))
    assert len(arrays) == 29 and len(flags) == 24 and len(scalars) == 49
    arrays = [np.ascontiguousarray(x, dtype=np.float64) for x in arrays]
    return dict(shape=shape, arrays=arrays, flags=flags, scalars=scalars, mode=mode,
                envelope=cfg.get('envelope_mode', 'raise'))


@pytest.fixture(scope='module')
def native():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    suffix = '.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'
    library = ROOT / '.cache/native-deps/build' / ('pilot-'+host) / (('' if os.name == 'nt' else 'lib')+'full_2d_test'+suffix)
    if not library.is_file():
        message = f'full2D coarse qualification library not built: {library}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    lib = ct.CDLL(str(library))
    lib.test_full_2d_run.argtypes = [ct.POINTER(S), ct.POINTER(D), ct.POINTER(S), ct.POINTER(S), D,
        ct.c_char_p, ct.c_char_p, ct.c_int, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_char), S]
    lib.test_full_2d_run.restype = ct.c_int
    lib.test_full_2d_json.argtypes, lib.test_full_2d_json.restype = [ct.c_void_p], ct.c_char_p
    lib.test_full_2d_destroy.argtypes, lib.test_full_2d_destroy.restype = [ct.c_void_p], None

    def run(request):
        arrays = request['arrays']
        handle, error = ct.c_void_p(), ct.create_string_buffer(2048)
        code = lib.test_full_2d_run((S * 2)(*request['shape']), (D * len(arrays))(*(a.ctypes.data_as(D) for a in arrays)),
            (S * len(arrays))(*(a.size for a in arrays)), (S * len(request['flags']))(*request['flags']),
            (ct.c_double * len(request['scalars']))(*request['scalars']),
            str(ROOT / '.cache/native-deps/tables/full2d-tests').encode(), request['envelope'].encode(), request.get('full', False),
            ct.byref(handle), error, len(error))
        if code:
            assert not handle.value
            return code, error.value.decode(), None
        try:
            return code, '', json.loads(lib.test_full_2d_json(handle))
        finally:
            lib.test_full_2d_destroy(handle)

    return run


def compare_array(actual, expected, kind='other'):
    if expected is None:
        assert np.isnan(actual)
        return
    expected = np.asarray(expected)
    tolerances = {'temperature': (2e-9, 2e-7), 'pressure': (2e-8, 2e-5),
                  'state': (2e-8, 2e-10), 'power': (2e-8, 2e-7), 'other': (2e-8, 2e-10)}
    rtol, atol = tolerances[kind]
    np.testing.assert_allclose(np.asarray(actual).reshape(expected.shape), expected, rtol=rtol, atol=atol, equal_nan=True)


def compare_coarse(actual, record):
    state, cfg = record['state'], record['cfg']
    assert not actual['cancelled']
    assert actual['outer_converged'] == record['outer_return'][1]
    assert actual['iterations'] == record['outer_return'][0] + 1
    assert actual['post_after_last_thermal'] == (not record['outer_return'][1])
    assert len(actual['outer_history']) == len(record['outer_history'])
    for got, expected in zip(actual['outer_history'], record['outer_history']):
        for key in ('iteration', 'thermal_iterations', 'thermal_converged', 'outer_converged'):
            assert got[key] == expected[key], (key, got, expected)
        compare_array(got['relative_density_change'], expected['relative_density_change'])
        compare_array(got['temperature_change'], expected['temperature_change'], 'temperature')
    thermal = actual['thermal']
    for got, name in zip(thermal['temperature'], ('Ta', 'Tb', 'Ts')):
        compare_array(got, getattr(state, name), 'temperature')
    for index, side in enumerate(('A', 'B')):
        solver, flow = getattr(state, 'simp'+side), actual['flow'][index]
        for key, name in (('dx', 'dx_arr'), ('dy', 'dy_arr'), ('u', 'u'), ('v', 'v'), ('pressure', 'P'),
            ('pressure_correction', 'Pp'), ('d_u', 'd_u'), ('d_v', 'd_v'), ('density', 'rho_field'),
            ('inlet_velocity', 'v_inlet_field'), ('viscosity', 'mu_field'), ('effective_viscosity', '_mu_eff_field'),
            ('temperature', 'T_field'), ('epsilon', 'eps_field')):
            kind = 'pressure' if key.startswith('pressure') else 'temperature' if key == 'temperature' else 'state'
            compare_array(flow[key], getattr(solver, name), kind)
        compare_array(flow['reference_pressure'], solver.P_ref_abs, 'pressure')
        compare_array(flow['taper_flux_scale'], solver._inlet_taper_flux_scale)
        compare_array(flow['massflux_target'], solver._massflux_target)
        for key in ('uc', 'vc'):
            compare_array(flow[key], getattr(state, key+side), 'state')
        direction = cfg['dir_'+side]
        pressure = coupling._simple_pressure_abs_2d(solver, direction, getattr(cfg['compute_cfg'], 'fluid_'+side).P_in_Pa)
        compare_array(flow['absolute_pressure'], pressure, 'pressure')
        compare_array(thermal['pressure'][index], pressure, 'pressure')
        for key, expected in zip(('mass_x', 'mass_y'), getattr(state, 'mass_flux_'+side)):
            compare_array(flow[key], expected)
            compare_array(thermal[key][index], expected)
        pressure_state = inlet_pressure_state(solver, getattr(cfg['compute_cfg'], 'fluid_'+side).P_in_Pa)
        if pressure_state is None:
            assert flow['pressure_state'] is None and flow['pressure_iterations'] == []
        else:
            for key, value in pressure_state.items():
                if key == 'iterations':
                    assert len(flow['pressure_iterations']) == len(value)
                    for got, expected in zip(flow['pressure_iterations'], value):
                        assert got.keys() == expected.keys()
                        for name, scalar in expected.items():
                            if isinstance(scalar, str):
                                assert got[name] == scalar
                            else:
                                compare_array(got[name], scalar, 'pressure')
                elif isinstance(value, (str, bool)):
                    assert flow['pressure_state'][key] == value
                else:
                    compare_array(flow['pressure_state'][key], value, 'pressure')
        expected_result = next(returned for s, returned, _ in reversed(record['simple_calls'])
                               if s.P.shape == solver.P.shape and np.array_equal(s.P, solver.P))
        result = flow['result']
        assert (result['converged'], result['iterations']) == expected_result
        assert result['stop'] == {'tol': 1, 'stall': 2, 'max_iter': 3, 'nonfinite': 4}[solver.exit_reason]
        assert result['post_closure_measured'] == (solver.f2_cert_post_rescale_ok is not None)
        assert result['post_closure_certified'] == bool(solver.f2_cert_post_rescale_ok)
        assert result['pressure_clip_hits'] == getattr(solver, '_p_clip_hits', 0)
        for got, expected in ((result['legacy_residual'], solver.final_res),
            (result['momentum']['maximum'], solver.final_res_mom), (result['mass']['local_residual'], solver.final_res_mass_local),
            (result['mass']['global_residual'], solver.final_res_mass_global), (result['mass']['backflow_fraction'], solver.outlet_backflow_frac)):
            compare_array(got, expected)
        for key, name in (('legacy', 'residuals'), ('local_mass', 'mass_local_residuals'), ('global_mass', 'mass_global_residuals')):
            compare_array(flow['history'][key], getattr(solver, name))
        assert len(flow['history']['momentum']) == len(solver.mom_residuals)
        for got, expected in zip(flow['history']['momentum'], solver.mom_residuals):
            assert got['iteration'] == expected['iter']
            compare_array(got['residual']['maximum'], expected['max'])
            compare_array(got['residual']['numerator'][:2], expected['num'])
            compare_array(got['residual']['denominator'][:2], expected['den'])
            compare_array(got['residual']['component'][:2], [expected['u'], expected['v']])
        for key, name in (('density', 'rho_'+side+'_field'), ('viscosity', 'mu_'+side), ('rho_cp', 'rho_cp_'+side)):
            compare_array(actual[key][index], np.broadcast_to(getattr(state, name), state.Ta.shape), 'state')
        expected_envelope = record['envelope'].get('2D-'+side, (True, []))
        assert actual['envelope'][index] == dict(valid=expected_envelope[0], reasons=expected_envelope[1])
    result = thermal['result']
    assert (result['stop'] == 0) == state.e_info['converged']
    assert result['iterations'] == state.e_info['iterations']
    compare_array(result['residual'], state.e_info['residual'], 'temperature')
    last_inputs = record['coarse_thermal_calls'][-1][0]
    for index, side in enumerate(('A', 'B')):
        compare_array(thermal['hv'][index], last_inputs['h_v'+side])
        if 'rho_cp_f'+side in last_inputs:
            compare_array(thermal['rho_cp'][index], np.broadcast_to(last_inputs['rho_cp_f'+side], state.Ta.shape), 'state')
            compare_array(thermal['conductivity'][index], np.broadcast_to(last_inputs['K_ff'+side], state.Ta.shape))
    compare_array(thermal['solid_conductivity'], np.broadcast_to(last_inputs.get('K_ss', last_inputs.get('k_s')), state.Ta.shape))
    if result['mode'] == 'model_h':
        expected = state.e_info['model_h_balance']
        audit = result['audit']
        assert result['audit_available']
        for key, name in {'boundary_complete': 'physical_boundary_complete', 'finite': 'finite', 'energy_ok': 'energy_ok',
            'solid_ok': 'solid_ok', 'equations_ok': 'equations_ok', 'passed': 'passed'}.items():
            assert audit[key] == expected[name]
        assert result['finishing_checks'] == state.e_info['energy_finishing_checks']
        for key, name in {'solid_sum': 'solid_residual_sum_W_per_m', 'solid_max': 'solid_residual_max_abs_W_per_m',
            'solid_cell_ratio': 'solid_residual_cellmax_rel', 'residual_sum': 'residual_sum_W_per_m',
            'telescoping_error': 'telescoping_error_W_per_m', 'net_boundary_in': 'net_boundary_in_W_per_m',
            'denominator': 'D2_W_per_m', 'energy_imbalance': 'energy_imbalance_rel', 'solid_imbalance': 'solid_imbalance_rel'}.items():
            compare_array(audit[key], expected[name], 'power' if name.endswith('_W_per_m') else 'other')
        for got, side in zip(audit['sides'], ('A', 'B')):
            target = expected[side]
            assert got['unknown_inflow_faces'] == target['unknown_inflow_faces']
            for key, name in {'q_advective': 'Q_advective_W_per_m', 'inlet_conduction': 'inlet_conduction_W_per_m',
                'exchange': 'exchange_W_per_m', 'residual_sum': 'residual_sum_W_per_m', 'residual_max': 'residual_max_abs_W_per_m',
                'linearized_sum': 'linearized_residual_sum_W_per_m', 'linearized_max': 'linearized_residual_max_abs_W_per_m',
                'defect_sum': 'linearization_defect_sum_W_per_m', 'defect_max': 'linearization_defect_max_abs_W_per_m',
                'mass_net': 'mass_net_out_kg_s_per_m', 'mass_local_max': 'mass_local_max_abs_kg_s_per_m',
                'mass_in': 'mass_in_kg_s_per_m', 'mass_out': 'mass_out_kg_s_per_m',
                'normalization': 'strict_normalization_W_per_m', 'cell_ratio': 'residual_cellmax_rel',
                'inlet_conduction_faces': 'inlet_conduction_faces_W_per_m', 'cp_coefficients': 'cp_coefficients'}.items():
                try:
                    compare_array(got[key], target[name], 'power' if name.endswith('_W_per_m') else 'other')
                except AssertionError as error:
                    raise AssertionError(f'Model-h audit side {side}: {name}') from error
            for key, name in {'boundary_mass_out': 'boundary_mass_out_kg_s_per_m',
                              'boundary_h_out': 'boundary_h_out_W_per_m', 'h_faces': 'h_faces_W_per_m'}.items():
                for face, expected_face in zip(got[key], target[name]):
                    compare_array(face, expected_face, 'power' if name.endswith('_W_per_m') else 'other')
        q_b = np.sum(last_inputs['h_vB'] * (state.Ts-state.Tb) * record['prepared']['energy_dx'][:, None]
                     * record['prepared']['energy_dy'][None, :])
        compare_array(result['q_b'], q_b, 'power')


@pytest.mark.parametrize('outer', [2, 4])
def test_prepared_air_water_model_h_coarse(native, outer):
    case = prepare_case(configuration(outer=outer), case_id=f'native-full2d-coarse-{outer}')
    reference = capture_python(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    compare_coarse(actual, reference)


@pytest.mark.parametrize('directions,warm', [((1, 2), False), ((2, 1), False), ((3, 0), True)])
def test_prepared_directions_and_solid_warm_start(native, directions, warm):
    case = prepare_case(configuration(directions=directions, warm=warm), case_id='native-full2d-directed')
    reference = capture_python(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    compare_coarse(actual, reference)


@pytest.mark.parametrize('mode', ['temperature', 'true_h'])
def test_prepared_other_thermal_routes(native, mode):
    case = prepare_case(configuration(mode=mode, outer=2), case_id='native-full2d-'+mode)
    reference = capture_python(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    compare_coarse(actual, reference)


@pytest.mark.parametrize('shooting', [False, True])
def test_prepared_pressure_shooting_with_capped_simple(native, shooting):
    case = prepare_case(configuration(outer=2, simple_max=10), case_id='native-full2d-capped-flow')
    reference = capture_python(case, pressure_shooting=shooting)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    compare_coarse(actual, reference)
    assert not all(flow['result']['converged'] for flow in actual['flow'])


@pytest.mark.parametrize('partial,continuous,directions', [
    (False, False, (0, 3)), (True, False, (0, 3)),
    (True, True, (0, 3)), (True, True, (1, 2)),
])
def test_prepared_completed_coarse_and_continuous_fields(native, partial, continuous, directions):
    cfg = configuration(partial=partial, directions=directions, outer=10)
    if continuous:
        cfg.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [6.7, 7.2, 7., 7.5, .45, .5, .55, .58],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    case = prepare_case(cfg, case_id='native-full2d-completed')
    reference = capture_python(case)
    request = inputs(reference)
    if continuous:
        assert np.ptp(request['arrays'][6]) > 0
        assert np.ptp(request['arrays'][9]) > 0
        assert all(request['arrays'][index].size == np.prod(request['shape']) for index in (12, 13, 21, 22))
    code, error, actual = native(request)
    assert code == 0, error
    compare_coarse(actual, reference)
    assert actual['outer_converged']
    assert all(flow['result']['converged'] for flow in actual['flow'])
